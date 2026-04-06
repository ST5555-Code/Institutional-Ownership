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

PDF_BASE_URL = "https://reports.adviserinfo.sec.gov/reports/ADV"
RATE_LIMIT = 0.2  # 5 req/s
MAX_SIZE_MB = 10.0


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
                downloaded += 1
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
PARSE_TIMEOUT = 30  # seconds per PDF — skip if pdfplumber hangs

CSV_FIELDNAMES = [
    "firm_crd", "firm_name", "entity_id", "schedule", "name", "jurisdiction",
    "title_or_status", "date", "ownership_code", "control_person",
    "is_entity", "relationship_type",
]


def _parse_with_timeout(pdf_path, firm_crd, timeout_sec=PARSE_TIMEOUT):
    """Parse a PDF with a timeout. Returns entries or empty list on timeout."""
    import signal

    def _handler(_signum, _frame):
        raise TimeoutError(f"PDF parse exceeded {timeout_sec}s")

    old = signal.signal(signal.SIGALRM, _handler)
    signal.alarm(timeout_sec)
    try:
        return entity_sync.parse_adv_pdf(pdf_path, firm_crd=firm_crd, max_size_mb=MAX_SIZE_MB)
    except TimeoutError:
        return []
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)


def run_parse(targets, limit=None):
    """
    Parse local PDFs → adv_schedules.csv. No network calls, no DB connection.

    Incremental: writes each firm's results to CSV immediately after parsing.
    Resumable: loads already-parsed CRDs from existing CSV at startup, skips them.
    Timeout: skips any PDF that takes >30s to parse.
    """
    work = targets if limit is None else targets[:limit]

    # Resume: load CRDs already in the CSV
    already_parsed: set[str] = set()
    csv_exists = SCHEDULES_CSV.exists() and SCHEDULES_CSV.stat().st_size > 0
    if csv_exists:
        with open(SCHEDULES_CSV, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                already_parsed.add(row.get("firm_crd", ""))
        print(f"  Resuming: {len(already_parsed)} CRDs already in CSV, skipping")

    # Open CSV in append mode (or write mode if new)
    csv_mode = "a" if csv_exists else "w"
    csv_file = open(SCHEDULES_CSV, csv_mode, newline="", encoding="utf-8")  # noqa: SIM115
    writer = csv.DictWriter(csv_file, fieldnames=CSV_FIELDNAMES)
    if not csv_exists:
        writer.writeheader()

    parsed = 0
    skipped_size = 0
    skipped_missing = 0
    skipped_done = 0
    parse_errors = 0
    timed_out = 0
    total_rows = 0
    oversized = []
    t0 = time.time()

    try:
        for i, (crd, name, eid) in enumerate(work):
            # Resume check
            if crd in already_parsed:
                skipped_done += 1
                continue

            pdf_path = str(PDF_DIR / f"{crd}.pdf")
            if not os.path.exists(pdf_path):
                skipped_missing += 1
                continue

            file_mb = os.path.getsize(pdf_path) / (1024 * 1024)
            if file_mb > MAX_SIZE_MB:
                skipped_size += 1
                oversized.append({"crd": crd, "firm_name": name, "size_mb": round(file_mb, 1)})
                continue

            try:
                entries = _parse_with_timeout(pdf_path, firm_crd=crd)
            except Exception:
                parse_errors += 1
                continue

            if not entries:
                # Could be timeout or genuinely empty schedule
                if file_mb > 5:
                    timed_out += 1
                continue

            parsed += 1
            # Write immediately — no data loss on crash
            for e in entries:
                row = {"firm_crd": crd, "firm_name": name, "entity_id": eid}
                for field in CSV_FIELDNAMES[3:]:
                    row[field] = e.get(field, "")
                writer.writerow(row)
                total_rows += 1
            csv_file.flush()

            if (i + 1) % 100 == 0 or i < 3:
                elapsed = time.time() - t0
                rate = (i + 1 - skipped_done) / elapsed if elapsed > 0 else 0
                print(
                    f"  [{i+1}/{len(work)}] parsed={parsed} rows={total_rows} "
                    f"errors={parse_errors} timeout={timed_out} "
                    f"oversized={skipped_size} ({rate:.1f}/s)"
                )
    finally:
        csv_file.close()

    elapsed = time.time() - t0

    # Write oversized log
    if oversized:
        with open(OVERSIZED_CSV, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["crd", "firm_name", "size_mb"])
            w.writeheader()
            w.writerows(oversized)

    print(f"\n  Parse complete: {parsed} PDFs → {total_rows} rows")
    print(f"  Resumed: {skipped_done} already done")
    print(f"  Skipped: {skipped_size} oversized, {skipped_missing} missing, {timed_out} timed out")
    print(f"  Errors: {parse_errors}")
    print(f"  Output: {SCHEDULES_CSV} ({elapsed:.0f}s)")
    return {"parsed": parsed, "rows": total_rows, "oversized": skipped_size}


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
            r = entity_sync.insert_adv_ownership(
                con, eid, owner["name"], owner["relationship_type"],
                owner.get("ownership_code", ""), owner.get("schedule", "A"),
                alias_cache=alias_cache,
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

    # Write results
    for path, data in [(RESULTS_CSV, entity_results), (JV_CSV, jv_entities), (UNMATCHED_CSV, unmatched_owners)]:
        if data:
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=list(data[0].keys()))
                w.writeheader()
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

    if args.download_only:
        print("\n--- PHASE 1: DOWNLOAD ---")
        run_download(targets, limit)
    elif args.parse_only:
        print("\n--- PHASE 2: PARSE ---")
        # No DB connection needed — reads local PDFs, writes CSV
        run_parse(targets, limit)
    elif args.match_only:
        print("\n--- PHASE 3: MATCH ---")
        con = db.connect_write()
        run_match(con)
        con.close()
    else:
        # Full run: all three phases
        print("\n--- PHASE 1: DOWNLOAD ---")
        run_download(targets, limit)
        print("\n--- PHASE 2: PARSE ---")
        run_parse(targets, limit)
        print("\n--- PHASE 3: MATCH ---")
        con = db.connect_write()
        run_match(con)
        con.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
