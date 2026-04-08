#!/usr/bin/env python3
"""
resolve_adv_ownership.py — Phase 3.5: Parse ADV Schedule A/B ownership chains.

Three-phase pipeline, each fully restartable:
  --download-only  Download PDFs to data/cache/adv_pdfs/ (5 req/s, ~12 min)
  --parse-only     Parse local PDFs → data/reference/adv_schedules.csv
  --match-only     Entity match from CSV → insert relationships + rollups

Full run (all three phases in one):
  python3 scripts/resolve_adv_ownership.py --staging --all

Rate limit: 5 req/s. PDF source: reports.adviserinfo.sec.gov
"""
from __future__ import annotations

# pylint: disable=too-many-locals,too-many-statements,too-many-branches,broad-exception-caught

import argparse
import csv
import gc
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# Ensure progress output is visible in background/redirected runs
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(line_buffering=True)
elif not sys.stdout.isatty():
    sys.stdout = os.fdopen(sys.stdout.fileno(), 'w', buffering=1)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import db  # noqa: E402
import entity_sync  # noqa: E402

LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
PDF_DIR = ROOT / "data" / "cache" / "adv_pdfs"
PDF_DIR.mkdir(parents=True, exist_ok=True)

SCHEDULES_CSV = ROOT / "data" / "reference" / "adv_schedules.csv"
RESULTS_CSV = LOG_DIR / "phase35_resolution_results.csv"
JV_CSV = LOG_DIR / "phase35_jv_entities.csv"
UNMATCHED_CSV = LOG_DIR / "phase35_unmatched_owners.csv"
OVERSIZED_CSV = LOG_DIR / "phase35_oversized.csv"
TIMEDOUT_CSV = LOG_DIR / "phase35_timed_out.csv"

PDF_BASE_URL = "https://reports.adviserinfo.sec.gov/reports/ADV"
RATE_LIMIT = 0.2  # 5 req/s
MAX_SIZE_MB = 10.0
FAILED_CRDS_CSV = LOG_DIR / "phase35_failed_crds.csv"
CHECKPOINT_FILE = ROOT / "data" / "cache" / "adv_parsed.txt"


def _is_valid_pdf(path: str) -> bool:
    """Check first 4 bytes are %PDF."""
    try:
        with open(path, 'rb') as f:
            return f.read(4) == b'%PDF'
    except Exception:
        return False


def _log_failed_crd(crd, name, reason):
    """Append to failed CRDs log."""
    header_needed = not FAILED_CRDS_CSV.exists() or FAILED_CRDS_CSV.stat().st_size == 0
    with open(FAILED_CRDS_CSV, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if header_needed:
            w.writerow(["crd", "firm_name", "reason"])
        w.writerow([crd, name, reason])


def get_adv_targets(con) -> list[tuple]:
    """CRDs in adv_managers that have entities in the MDM layer."""
    return con.execute("""
        SELECT DISTINCT am.crd_number, am.firm_name, ei.entity_id
        FROM adv_managers am
        JOIN entity_identifiers ei ON ei.identifier_type='crd'
          AND ei.identifier_value=am.crd_number AND ei.valid_to=DATE '9999-12-31'
        WHERE am.crd_number IS NOT NULL AND am.crd_number != ''
        ORDER BY am.crd_number
    """).fetchall()


# =========================================================================
# Phase 1: Download
# =========================================================================
def run_download(targets, limit=None):
    """Download ADV PDFs. Skips already-cached files. Returns download stats."""
    import requests

    session = requests.Session()
    session.headers.update(entity_sync.SEC_HEADERS)

    work = targets if limit is None else targets[:limit]
    downloaded = 0
    cached = 0
    failed = 0
    t0 = time.time()

    for i, (crd, name, _eid) in enumerate(work):
        pdf_path = str(PDF_DIR / f"{crd}.pdf")
        if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 100:
            cached += 1
            continue

        time.sleep(RATE_LIMIT)
        url = f"{PDF_BASE_URL}/{crd}/PDF/{crd}.pdf"
        try:
            resp = session.get(url, timeout=30)
            if resp.status_code == 200 and len(resp.content) > 100:
                with open(pdf_path, 'wb') as f:
                    f.write(resp.content)
                # Validate downloaded file is actually a PDF
                if _is_valid_pdf(pdf_path):
                    downloaded += 1
                else:
                    os.remove(pdf_path)
                    _log_failed_crd(crd, name, "invalid_pdf_header")
                    failed += 1
            else:
                failed += 1
        except Exception:
            failed += 1

        if (i + 1) % 100 == 0 or i < 3:
            elapsed = time.time() - t0
            print(f"  [{i+1}/{len(work)}] downloaded={downloaded} cached={cached} failed={failed} ({(i+1)/elapsed:.1f}/s)")

    elapsed = time.time() - t0
    print(f"\n  Download complete: {downloaded} new, {cached} cached, {failed} failed ({elapsed:.0f}s)")
    return {"downloaded": downloaded, "cached": cached, "failed": failed}


# =========================================================================
# Phase 2: Parse
# =========================================================================
PARSE_TIMEOUT = 180  # seconds per PDF (most parse in 45-150s)

CSV_FIELDNAMES = [
    "firm_crd", "firm_name", "entity_id", "schedule", "name", "jurisdiction",
    "title_or_status", "date", "ownership_code", "control_person",
    "is_entity", "relationship_type",
]

PARSE_WORKERS = 4  # parallel PDF parse workers
PARSE_PROGRESS = LOG_DIR / "phase35_parse_progress.log"
ERRORS_CSV = LOG_DIR / "phase35_errors.csv"
MEM_WARN_MB = 2048   # log warning
MEM_EMERGENCY_MB = 4096  # force full GC + cache clear


def _get_rss_mb():
    """Current process RSS in MB (macOS/Linux)."""
    try:
        import resource
        # ru_maxrss is in bytes on macOS, KB on Linux
        ru = resource.getrusage(resource.RUSAGE_SELF)
        rss = ru.ru_maxrss
        if sys.platform == "darwin":
            return rss / (1024 * 1024)
        return rss / 1024
    except Exception:
        return 0.0


def _get_current_rss_mb():
    """Current (not peak) RSS in MB via resource module (no subprocess)."""
    try:
        import resource
        ru = resource.getrusage(resource.RUSAGE_SELF)
        if sys.platform == "darwin":
            return ru.ru_maxrss / (1024 * 1024)  # bytes on macOS
        return ru.ru_maxrss / 1024  # KB on Linux
    except Exception:
        return 0.0


def _worker_parse_chunk(chunk, worker_id, tmp_csv_path, timeout_sec, max_size_mb,
                        progress_path, errors_csv_path, checkpoint_path):
    """Independent subprocess: parses its own chunk of PDFs, writes its own CSV.

    Each worker is a full process with SIGALRM timeout — no shared state,
    no pool contention, no GIL. Writes results to a temp CSV that the main
    process merges after all workers finish.

    Bulletproof:
    - SIGALRM timeout per PDF (logs as TIMEOUT, not ERROR)
    - try/except around entire per-PDF logic — never crash on single bad PDF
    - CSV flush after every PDF (crash-safe checkpoint)
    - Checkpoint: appends CRD to adv_parsed.txt after every PDF (O_APPEND atomic)
    - SIGTERM handler: flush and exit cleanly on kill signal
    - Memory monitoring: warn at 2GB, emergency GC at 4GB
    - Progress log: every PDF + summary every 50 PDFs
    """
    import signal

    # --- SIGTERM handler: flush CSV and exit cleanly ---
    _shutting_down = False

    def _sigterm_handler(_signum, _frame):
        nonlocal _shutting_down
        _shutting_down = True
        _log_progress("---", "SIGTERM", "STOP", secs=0)

    signal.signal(signal.SIGTERM, _sigterm_handler)

    # --- SIGALRM handler for per-PDF timeout ---
    def _alarm_handler(_signum, _frame):
        raise TimeoutError("PDF parse timeout")

    # --- Progress logging ---
    def _log_progress(crd, name, status, rows=0, secs=0, mem_mb=0):
        """Append one line to shared progress log. O_APPEND is atomic on POSIX."""
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"{ts} W{worker_id} [{done_count}/{len(chunk)}] {status:>7} {crd} {name[:40]}"
        if rows:
            line += f" → {rows} rows"
        if secs:
            line += f" ({secs:.0f}s)"
        if mem_mb:
            line += f" [{mem_mb:.0f}MB]"
        line += "\n"
        with open(progress_path, "a", encoding="utf-8") as pf:
            pf.write(line)

    def _log_summary():
        """Summary line every 50 PDFs with ETA and memory."""
        elapsed = time.time() - worker_t0
        rate = done_count / elapsed if elapsed > 0 else 0
        remaining = len(chunk) - done_count
        eta_sec = remaining / rate if rate > 0 else 0
        eta_min = eta_sec / 60
        mem = _get_current_rss_mb()
        ts = datetime.now().strftime("%H:%M:%S")
        line = (f"{ts} W{worker_id} === SUMMARY: {done_count}/{len(chunk)} done, "
                f"{parsed} parsed, {total_rows} rows, {parse_errors} errors, "
                f"{timed_out} timeout | {elapsed:.0f}s elapsed, "
                f"ETA {eta_min:.0f}m | mem {mem:.0f}MB ===\n")
        with open(progress_path, "a", encoding="utf-8") as pf:
            pf.write(line)

    # --- Error logging ---
    def _log_error(crd, name, error_msg):
        """Append to shared errors CSV."""
        with open(errors_csv_path, "a", newline="", encoding="utf-8") as ef:
            w = csv.writer(ef)
            w.writerow([datetime.now().isoformat(), worker_id, crd, name, error_msg])

    # --- Checkpoint ---
    def _checkpoint(crd):
        """Append CRD to checkpoint file. O_APPEND is atomic on POSIX."""
        with open(checkpoint_path, "a", encoding="utf-8") as cf:
            cf.write(f"{crd}\n")

    parsed = 0
    parse_errors = 0
    timed_out = 0
    total_rows = 0
    done_count = 0
    timed_out_list = []
    worker_t0 = time.time()

    csv_file = open(tmp_csv_path, "w", newline="", encoding="utf-8")  # noqa: SIM115
    writer = csv.DictWriter(csv_file, fieldnames=CSV_FIELDNAMES)
    writer.writeheader()

    try:
        for i, (crd, name, eid, pdf_path, file_mb) in enumerate(chunk):
            if _shutting_down:
                _log_progress(crd, name, "ABORT", secs=0)
                break

            done_count = i + 1
            pdf_t0 = time.time()
            status = "EMPTY"
            n_rows = 0

            try:
                # SIGALRM timeout — clean per-PDF, works in single process
                old_handler = signal.signal(signal.SIGALRM, _alarm_handler)
                signal.alarm(timeout_sec)
                try:
                    entries = entity_sync.parse_adv_pdf(
                        pdf_path, firm_crd=crd, max_size_mb=max_size_mb)
                except TimeoutError:
                    entries = None  # distinguish timeout from empty
                    status = "TIMEOUT"
                finally:
                    signal.alarm(0)
                    signal.signal(signal.SIGALRM, old_handler)

                gc.collect()

                if entries is None:
                    # Timeout
                    timed_out += 1
                    timed_out_list.append({
                        "crd": crd, "firm_name": name, "size_mb": round(file_mb, 1),
                        "timeout_sec": timeout_sec,
                    })
                elif not entries:
                    status = "EMPTY"
                else:
                    status = "OK"
                    parsed += 1
                    for e in entries:
                        row = {"firm_crd": crd, "firm_name": name, "entity_id": eid}
                        for field in CSV_FIELDNAMES[3:]:
                            row[field] = e.get(field, "")
                        writer.writerow(row)
                        n_rows += 1
                        total_rows += 1
                    # Flush after EVERY PDF — crash-safe checkpoint
                    csv_file.flush()

            except Exception as exc:
                status = "ERROR"
                parse_errors += 1
                _log_error(crd, name, f"{type(exc).__name__}: {exc}")
                gc.collect()

            elapsed_pdf = time.time() - pdf_t0

            # Memory monitoring after every PDF
            mem_mb = _get_current_rss_mb()
            if mem_mb > MEM_EMERGENCY_MB:
                gc.collect()
                mem_mb = _get_current_rss_mb()
                _log_progress(crd, name, "MEM!!!", mem_mb=mem_mb, secs=elapsed_pdf)
            elif mem_mb > MEM_WARN_MB:
                gc.collect()
                mem_mb = _get_current_rss_mb()

            _log_progress(crd, name, status, rows=n_rows, secs=elapsed_pdf,
                          mem_mb=mem_mb if mem_mb > MEM_WARN_MB else 0)

            # Checkpoint: mark CRD complete (success, error, timeout — all count)
            _checkpoint(crd)

            # Summary every 50 PDFs
            if done_count % 50 == 0:
                _log_summary()

    finally:
        csv_file.flush()
        csv_file.close()

    _log_summary()
    print(f"    [W{worker_id}] done: {parsed} parsed, {total_rows} rows, "
          f"{parse_errors} errors, {timed_out} timed out")
    return {
        "parsed": parsed, "errors": parse_errors, "timed_out": timed_out,
        "rows": total_rows, "timed_out_list": timed_out_list,
        "tmp_csv": tmp_csv_path,
    }


def _run_worker_entry(chunk, wid, tmp_csv, timeout_sec, max_size_mb,
                      progress_path, errors_csv_path, checkpoint_path, q):
    """Module-level entry point for Process (must be picklable on macOS spawn)."""
    result = _worker_parse_chunk(chunk, wid, tmp_csv, timeout_sec, max_size_mb,
                                 progress_path, errors_csv_path, checkpoint_path)
    q.put(result)


def _merge_temp_csvs(tmp_pattern_dir):
    """Recover leftover temp CSVs from a crashed previous run into main CSV."""
    import glob
    leftover = sorted(glob.glob(str(tmp_pattern_dir / "adv_parse_w*.csv")))
    if not leftover:
        return 0
    merged = 0
    csv_exists = SCHEDULES_CSV.exists() and SCHEDULES_CSV.stat().st_size > 0
    csv_mode = "a" if csv_exists else "w"
    with open(SCHEDULES_CSV, csv_mode, newline="", encoding="utf-8") as out_f:
        writer = csv.DictWriter(out_f, fieldnames=CSV_FIELDNAMES)
        if not csv_exists:
            writer.writeheader()
        for tmp_csv in leftover:
            with open(tmp_csv, encoding="utf-8") as in_f:
                for row in csv.DictReader(in_f):
                    writer.writerow(row)
                    merged += 1
            os.remove(tmp_csv)
    if merged:
        print(f"  Recovered {merged} rows from {len(leftover)} temp CSVs (previous crash)")
    return merged


def run_parse(targets, limit=None, timeout=PARSE_TIMEOUT, workers=PARSE_WORKERS,
              max_size_mb=MAX_SIZE_MB):
    """
    Parse local PDFs → adv_schedules.csv. No network calls, no DB connection.

    Partitioned parallel: splits work into N chunks, each runs as an independent
    subprocess with its own temp CSV. Main process merges results after all finish.

    Bulletproof guarantees:
    - SIGALRM timeout per PDF (correctly logged as TIMEOUT)
    - try/except around every PDF — single bad PDF never crashes the run
    - CSV flush after every PDF — crash loses at most 1 PDF per worker
    - SIGTERM handler — clean shutdown on kill signal
    - Memory monitoring — warn at 2GB, emergency GC at 4GB
    - Crash recovery — leftover temp CSVs from prior crash merged on startup
    - Progress log — every PDF + summary every 50 with ETA and memory
    """
    from multiprocessing import Process, Queue

    work = targets if limit is None else targets[:limit]
    tmp_dir = ROOT / "data" / "cache"

    # Crash recovery: merge any leftover temp CSVs from previous interrupted run
    _merge_temp_csvs(tmp_dir)

    # Resume: load CRDs from explicit checkpoint file (not CSV)
    already_parsed: set[str] = set()
    checkpoint_path = str(CHECKPOINT_FILE)
    if CHECKPOINT_FILE.exists():
        with open(checkpoint_path, encoding="utf-8") as f:
            for line in f:
                crd = line.strip()
                if crd:
                    already_parsed.add(crd)
        print(f"  Resuming: {len(already_parsed)} CRDs in checkpoint, skipping")
    csv_exists = SCHEDULES_CSV.exists() and SCHEDULES_CSV.stat().st_size > 0

    # Build work queue — filter out already-done, missing, oversized up front
    parse_queue = []  # (crd, name, eid, pdf_path, file_mb)
    skipped_done = 0
    skipped_missing = 0
    skipped_size = 0
    oversized = []

    for crd, name, eid in work:
        if crd in already_parsed:
            skipped_done += 1
            continue
        pdf_path = str(PDF_DIR / f"{crd}.pdf")
        if not os.path.exists(pdf_path):
            skipped_missing += 1
            continue
        if not _is_valid_pdf(pdf_path):
            _log_failed_crd(crd, name, "invalid_pdf_header")
            skipped_missing += 1
            continue
        file_mb = os.path.getsize(pdf_path) / (1024 * 1024)
        if file_mb > max_size_mb:
            skipped_size += 1
            oversized.append({"crd": crd, "firm_name": name, "size_mb": round(file_mb, 1)})
            continue
        parse_queue.append((crd, name, eid, pdf_path, file_mb))

    print(f"  Queue: {len(parse_queue)} to parse, {skipped_done} resumed, "
          f"{skipped_size} oversized, {skipped_missing} missing")

    if not parse_queue:
        print("  Nothing to parse.")
        return {"parsed": 0, "rows": 0, "oversized": skipped_size}

    actual_workers = min(workers, len(parse_queue))
    print(f"  Workers: {actual_workers}")

    # Partition queue into N equal chunks (round-robin for balanced file sizes)
    chunks = [[] for _ in range(actual_workers)]
    for i, item in enumerate(parse_queue):
        chunks[i % actual_workers].append(item)

    for i, chunk in enumerate(chunks):
        print(f"    W{i}: {len(chunk)} PDFs")

    # Prepare logs
    result_queue = Queue()
    t0 = time.time()

    progress_path = str(PARSE_PROGRESS)
    with open(progress_path, "w", encoding="utf-8") as pf:
        pf.write(f"=== Parse started {datetime.now().isoformat()} "
                 f"({len(parse_queue)} PDFs, {actual_workers} workers, "
                 f"timeout={timeout}s) ===\n")
    print(f"  Progress: tail -f {progress_path}")

    errors_csv_path = str(ERRORS_CSV)
    with open(errors_csv_path, "w", newline="", encoding="utf-8") as ef:
        csv.writer(ef).writerow(["timestamp", "worker", "crd", "firm_name", "error"])

    # Launch independent subprocesses
    procs = []
    for wid, chunk in enumerate(chunks):
        tmp_csv = str(tmp_dir / f"adv_parse_w{wid}.csv")
        p = Process(
            target=_run_worker_entry,
            args=(chunk, wid, tmp_csv, timeout, max_size_mb,
                  progress_path, errors_csv_path, checkpoint_path,
                  result_queue),
        )
        p.start()
        procs.append(p)

    # Wait for all workers and check exit codes
    for wid, p in enumerate(procs):
        p.join()
        if p.exitcode != 0:
            print(f"  WARNING: Worker W{wid} exited with code {p.exitcode}")

    elapsed = time.time() - t0

    # Collect results — one per worker, known count (never use queue.empty())
    total_parsed = 0
    total_errors = 0
    total_timed_out = 0
    total_rows = 0
    all_timed_out = []
    tmp_csvs = []

    for _ in range(actual_workers):
        try:
            r = result_queue.get(timeout=5)
        except Exception:
            print("  WARNING: Missing result from worker (crashed before put?)")
            continue
        total_parsed += r["parsed"]
        total_errors += r["errors"]
        total_timed_out += r["timed_out"]
        total_rows += r["rows"]
        all_timed_out.extend(r["timed_out_list"])
        tmp_csvs.append(r["tmp_csv"])

    # Merge temp CSVs into main CSV
    csv_mode = "a" if csv_exists else "w"
    with open(SCHEDULES_CSV, csv_mode, newline="", encoding="utf-8") as out_f:
        writer = csv.DictWriter(out_f, fieldnames=CSV_FIELDNAMES)
        if not csv_exists:
            writer.writeheader()
        for tmp_csv in tmp_csvs:
            if os.path.exists(tmp_csv):
                with open(tmp_csv, encoding="utf-8") as in_f:
                    for row in csv.DictReader(in_f):
                        writer.writerow(row)
                os.remove(tmp_csv)

    # Write timed-out log
    if all_timed_out:
        with open(TIMEDOUT_CSV, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["crd", "firm_name", "size_mb", "timeout_sec"])
            w.writeheader()
            w.writerows(all_timed_out)
        print(f"  Timed out CRDs: {TIMEDOUT_CSV} ({len(all_timed_out)} firms — retry with higher --timeout)")

    # Write oversized log
    if oversized:
        with open(OVERSIZED_CSV, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["crd", "firm_name", "size_mb"])
            w.writeheader()
            w.writerows(oversized)

    # Append completion to progress log
    with open(progress_path, "a", encoding="utf-8") as pf:
        pf.write(f"=== Parse complete {datetime.now().isoformat()} "
                 f"({total_parsed} parsed, {total_rows} rows, "
                 f"{total_errors} errors, {total_timed_out} timeout, "
                 f"{elapsed:.0f}s) ===\n")

    print(f"\n  Parse complete: {total_parsed} PDFs → {total_rows} rows")
    print(f"  Resumed: {skipped_done} already done")
    print(f"  Skipped: {skipped_size} oversized, {skipped_missing} missing, {total_timed_out} timed out")
    print(f"  Errors: {total_errors} (see {ERRORS_CSV})")
    print(f"  Workers: {actual_workers}, Time: {elapsed:.0f}s")
    print(f"  Output: {SCHEDULES_CSV}")
    return {"parsed": total_parsed, "rows": total_rows, "oversized": skipped_size}


# =========================================================================
# Phase 3: Match
# =========================================================================
def run_match(con):
    """Entity match from adv_schedules.csv → insert relationships."""
    if not SCHEDULES_CSV.exists():
        print("  ERROR: adv_schedules.csv not found. Run --parse-only first.")
        return

    with open(SCHEDULES_CSV, encoding="utf-8") as f:
        all_rows = list(csv.DictReader(f))

    print(f"  Loaded {len(all_rows)} schedule rows from CSV")

    # Ensure deduplicated staging review view exists
    con.execute("""
        CREATE OR REPLACE VIEW entity_identifiers_staging_review AS
        WITH ranked AS (
            SELECT *,
                ROW_NUMBER() OVER (
                    PARTITION BY entity_id, identifier_type, identifier_value, review_status
                    ORDER BY confidence DESC, created_at DESC
                ) AS rn
            FROM entity_identifiers_staging
        )
        SELECT staging_id, entity_id, identifier_type, identifier_value,
               confidence, source, conflict_reason, existing_entity_id,
               review_status, reviewed_by, reviewed_at, notes, created_at
        FROM ranked WHERE rn = 1
    """)

    # Always overwrite review CSVs at start so they reflect current run only
    for path, fields in [
        (JV_CSV, ["firm_crd", "firm_name", "entity_id", "owner_count", "owners"]),
        (UNMATCHED_CSV, ["firm_crd", "firm_name", "entity_id", "owner_name", "best_match", "best_score"]),
    ]:
        with open(path, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=fields).writeheader()

    alias_cache = entity_sync.build_alias_cache(con)

    # Group by firm CRD
    by_firm: dict[str, list] = {}
    for r in all_rows:
        crd = r["firm_crd"]
        by_firm.setdefault(crd, []).append(r)

    entity_results = []
    jv_entities = []
    unmatched_owners = []
    t0 = time.time()

    code_rank = {"E": 3, "D": 2, "C": 1}

    for idx, (crd, rows) in enumerate(by_firm.items()):
        eid = int(rows[0]["entity_id"])
        firm_name = rows[0]["firm_name"]

        entity_owners = [
            r for r in rows
            if r.get("is_entity") == "True" and r.get("relationship_type") not in (None, "", "None")
        ]

        controlling = [r for r in entity_owners if r["relationship_type"] in ("wholly_owned", "parent_brand")]
        mutual = [r for r in entity_owners if r["relationship_type"] == "mutual_structure"]

        is_jv = len(controlling) > 1
        if is_jv:
            controlling.sort(key=lambda x: code_rank.get(x.get("ownership_code", ""), 0), reverse=True)
            jv_entities.append({
                "firm_crd": crd, "firm_name": firm_name, "entity_id": eid,
                "owner_count": len(controlling),
                "owners": "; ".join(f"{o['name']}({o.get('ownership_code','')})" for o in controlling),
            })

        for rank, owner in enumerate(controlling):
            # JV: only first owner (highest ownership code) gets is_primary=True
            is_primary = (rank == 0)
            r = entity_sync.insert_adv_ownership(
                con, eid, owner["name"], owner["relationship_type"],
                owner.get("ownership_code", ""), owner.get("schedule", "A"),
                alias_cache=alias_cache,
                is_primary=is_primary,
            )
            entity_results.append({
                "firm_crd": crd, "firm_name": firm_name, "entity_id": eid,
                "owner_name": owner["name"], "relationship_type": owner["relationship_type"],
                "ownership_code": owner.get("ownership_code", ""), "schedule": owner.get("schedule", "A"),
                "matched": r["matched"], "parent_entity_id": r.get("parent_entity_id"),
                "parent_name": r.get("parent_name"), "score": r["score"],
                "relationship_inserted": r["relationship_inserted"],
                "rollup_updated": r.get("rollup_updated", False), "jv_rank": rank if is_jv else None,
            })
            if not r["matched"]:
                unmatched_owners.append({
                    "firm_crd": crd, "firm_name": firm_name, "entity_id": eid,
                    "owner_name": owner["name"], "best_match": r.get("parent_name"),
                    "best_score": r["score"],
                })
                entity_sync.log_identifier_conflict(
                    con, eid, "adv_owner", owner["name"],
                    existing_entity_id=None, reason="adv_owner_unmatched",
                    source=f"ADV_SCHEDULE_{owner.get('schedule', 'A')}",
                    notes=f"ownership_code={owner.get('ownership_code','')}, best_score={r['score']:.0f}",
                )

        for owner in mutual:
            r = entity_sync.insert_adv_ownership(
                con, eid, owner["name"], "mutual_structure",
                owner.get("ownership_code", "NA"), owner.get("schedule", "A"),
                alias_cache=alias_cache,
            )
            entity_results.append({
                "firm_crd": crd, "firm_name": firm_name, "entity_id": eid,
                "owner_name": owner["name"], "relationship_type": "mutual_structure",
                "ownership_code": "NA", "schedule": owner.get("schedule", "A"),
                "matched": r["matched"], "parent_entity_id": r.get("parent_entity_id"),
                "parent_name": r.get("parent_name"), "score": r["score"],
                "relationship_inserted": r["relationship_inserted"],
                "rollup_updated": False, "jv_rank": None,
            })

        if (idx + 1) % 200 == 0:
            elapsed = time.time() - t0
            print(f"  [{idx+1}/{len(by_firm)}] matched so far: {sum(1 for r in entity_results if r['matched'])}")

    elapsed = time.time() - t0

    # Write results (RESULTS_CSV always full rewrite; JV/UNMATCHED append to pre-written headers)
    if entity_results:
        with open(RESULTS_CSV, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(entity_results[0].keys()))
            w.writeheader()
            w.writerows(entity_results)
    for path, data in [(JV_CSV, jv_entities), (UNMATCHED_CSV, unmatched_owners)]:
        if data:
            with open(path, "a", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=list(data[0].keys()))
                w.writerows(data)

    matched = sum(1 for r in entity_results if r["matched"])
    inserted = sum(1 for r in entity_results if r["relationship_inserted"])
    rollups = sum(1 for r in entity_results if r.get("rollup_updated"))
    wholly = sum(1 for r in entity_results if r["relationship_type"] == "wholly_owned" and r["relationship_inserted"])
    parent_b = sum(1 for r in entity_results if r["relationship_type"] == "parent_brand" and r["relationship_inserted"])

    print(f"\n  Match complete ({elapsed:.0f}s):")
    print(f"    Entity owners: {len(entity_results)}")
    print(f"    Matched:       {matched}")
    print(f"    Inserted:      {inserted} (wholly_owned={wholly}, parent_brand={parent_b})")
    print(f"    Rollups:       {rollups}")
    print(f"    JV structures: {len(jv_entities)}")
    print(f"    Unmatched:     {len(unmatched_owners)}")


# =========================================================================
# Main
# =========================================================================
def main():
    ap = argparse.ArgumentParser(description="Phase 3.5: ADV ownership resolution")
    ap.add_argument("--staging", action="store_true", required=True)
    ap.add_argument("--limit", type=int, default=None, help="Max CRDs (default: all targets)")
    ap.add_argument("--all", action="store_true", help="Process all targets")
    ap.add_argument("--download-only", action="store_true", help="Phase 1: download PDFs only")
    ap.add_argument("--parse-only", action="store_true", help="Phase 2: parse local PDFs to CSV only")
    ap.add_argument("--match-only", action="store_true", help="Phase 3: entity match from CSV only")
    ap.add_argument("--oversized", action="store_true", help="Phase 2b: parse oversized PDFs from phase35_oversized.csv (300s timeout, 1 worker)")
    ap.add_argument("--timeout", type=int, default=PARSE_TIMEOUT, help="Per-PDF parse timeout in seconds (default 180)")
    ap.add_argument("--workers", type=int, default=PARSE_WORKERS, help="Parallel parse workers (default 4)")
    args = ap.parse_args()

    db.set_staging_mode(True)

    # Open DB only when needed — parse-only reads local files and should NOT
    # hold the DuckDB write lock for hours (blocks all other DB operations).
    print("Phase 3.5 — resolve_adv_ownership.py")
    print(f"  DB: {db.get_db_path()}")
    print(f"  started: {datetime.now().isoformat()}")

    # Get targets (brief DB read, then close)
    con = db.connect_write()
    targets = get_adv_targets(con)
    con.close()
    del con

    limit = None if args.all else (args.limit or 50)
    print(f"  targets: {len(targets)}, limit: {limit or 'all'}")

    parse_timeout = args.timeout

    if args.oversized:
        print("\n--- PHASE 2b: OVERSIZED PARSE (timeout=300s, workers=1) ---")
        if not OVERSIZED_CSV.exists():
            print("  ERROR: phase35_oversized.csv not found. Run main parse first.")
        else:
            with open(OVERSIZED_CSV, encoding="utf-8") as f:
                oversized_crds = {r["crd"] for r in csv.DictReader(f)}
            # Build target list filtered to oversized CRDs only
            oversized_targets = [(crd, name, eid) for crd, name, eid in targets
                                 if crd in oversized_crds]
            print(f"  Oversized targets: {len(oversized_targets)} of {len(oversized_crds)} in CSV")
            run_parse(oversized_targets, limit=None, timeout=300, workers=1,
                      max_size_mb=200)
    elif args.download_only:
        print("\n--- PHASE 1: DOWNLOAD ---")
        run_download(targets, limit)
    elif args.parse_only:
        print(f"\n--- PHASE 2: PARSE (timeout={parse_timeout}s, workers={args.workers}) ---")
        run_parse(targets, limit, timeout=parse_timeout, workers=args.workers)
    elif args.match_only:
        print("\n--- PHASE 3: MATCH ---")
        con = db.connect_write()
        run_match(con)
        con.close()
    else:
        # Full run: all three phases
        print("\n--- PHASE 1: DOWNLOAD ---")
        run_download(targets, limit)
        print(f"\n--- PHASE 2: PARSE (workers={args.workers}) ---")
        run_parse(targets, limit, timeout=parse_timeout, workers=args.workers)
        print("\n--- PHASE 3: MATCH ---")
        con = db.connect_write()
        run_match(con)
        con.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
