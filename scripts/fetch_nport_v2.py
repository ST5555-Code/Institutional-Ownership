#!/usr/bin/env python3
# CHECKPOINT GRANULARITY POLICY
# Mode 1 (DERA bulk): unit = one quarter's ZIP. One manifest row per
# accession within the ZIP, one impact row per (series_id, report_month)
# tuple. A crash mid-quarter leaves some (series, month) rows committed
# and others un-started — re-running the same quarter resumes via the
# DELETE+INSERT-per-tuple load path in fetch_dera_nport.load_to_staging.
# Mode 2 (monthly topup, XML): unit = one series within one accession
# (same as the pre-Session-2 behaviour of this file).
"""fetch_nport_v2.py — N-PORT orchestrator (Session 2).

Session 2 rewrite. DERA ZIP is the primary bulk path for complete
quarters; XML per-accession is retained only as the monthly top-up path
for the current incomplete quarter. Session 1's parity test
(commit 5cf3585) cleared all 7 BLOCK checks on 21 accessions; Session 2
rolls that harness out to the full historical backfill.

Modes:
  python3 scripts/fetch_nport_v2.py --staging [--all | --limit N]
      Mode 1 DERA bulk (default). ``--all`` loads every missing DERA
      quarter through today's last complete quarter. ``--limit N`` stops
      after N quarters — resume with another run.

  python3 scripts/fetch_nport_v2.py --staging --monthly-topup [--limit N]
      Mode 2 XML per-accession, scoped to the current incomplete quarter.
      ``--limit N`` counts successful accession fetches (unchanged
      semantics from the pre-Session-2 batch flag).

  python3 scripts/fetch_nport_v2.py --staging --test
      Mode 3 parity — delegates to fetch_dera_nport.run_test_mode().

  python3 scripts/fetch_nport_v2.py --dry-run
      Mode 4 — show the plan for Mode 1. No downloads, no DB writes.

Additional flag:
  --zip PATH   File or directory containing pre-downloaded DERA ZIPs
               (named ``{YYYY}q{N}_nport.zip``). When a match is found,
               the network download is skipped. Falls back to
               auto-download when no match is present.

All DB writes go through ``--staging`` — the ``promote_nport.py`` script
owns the staging -> prod transition, unchanged from Session 1.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from datetime import date, datetime
from typing import Any, Optional

import duckdb

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

from db import (  # noqa: E402
    get_db_path, get_read_db_path, set_staging_mode, is_staging_mode,
    crash_handler, STAGING_DB,
)
from fetch_dera_nport import (  # noqa: E402
    REFERENCE_FUNDS,
    build_dera_dataset,
    dera_zip_url,
    download_dera_zip,
    load_to_staging as dera_load_to_staging,
    parse_quarter,
    quarter_label_for_date,
    resolve_amendments,
    resolve_zip_path,
    run_test_mode,
    _ensure_staging_schema,
)
from pipeline.nport_parsers import parse_nport_xml, classify_fund  # noqa: E402

from pipeline.manifest import (  # noqa: E402
    get_or_create_manifest_row, update_manifest_status, write_impact,
)
from pipeline.protocol import (  # noqa: E402
    DownloadTarget, FetchResult, ParseResult, QCFailure,
)
from pipeline.shared import sec_fetch  # noqa: E402


from config import SEC_HEADERS, configure_edgar_identity

L1_DIR = os.path.join(BASE_DIR, "data", "nport_raw")
PARSER_VERSION = "nport_v2.1"

# Backward-compat alias for any caller that still reads TEST_FUNDS as the
# old fund_name -> cik dict. New code should prefer REFERENCE_FUNDS.
TEST_FUNDS: dict[str, int] = {f["name"]: f["cik"] for f in REFERENCE_FUNDS}


# ---------------------------------------------------------------------------
# Mode 1 — DERA bulk
# ---------------------------------------------------------------------------

# First DERA N-PORT ZIP published for 2019Q4. Anything earlier is XML-only.
_DERA_EPOCH = (2019, 4)


def _last_complete_dera_quarter(today: Optional[date] = None) -> tuple[int, int]:
    """Return the most recent published DERA quarter as (year, quarter).

    Published quarters lag real time by one calendar quarter — the SEC
    compiles each ZIP from filings that arrived during the named quarter,
    so the ZIP for 2026Q2 doesn't exist until early April 2026 at the
    earliest (first 2026Q2 filings posted). We conservatively return the
    previous calendar quarter.
    """
    t = today or date.today()
    q_now = (t.month - 1) // 3 + 1
    if q_now == 1:
        return t.year - 1, 4
    return t.year, q_now - 1


def _quarter_after(year: int, quarter: int) -> tuple[int, int]:
    if quarter == 4:
        return year + 1, 1
    return year, quarter + 1


def _already_loaded_quarters(con: duckdb.DuckDBPyConnection) -> set[tuple[int, int]]:
    """Return {(year, quarter)} for DERA ZIPs already recorded in the
    manifest with a terminal fetch_status.

    object_key convention for DERA ZIPs: ``DERA_ZIP:{YYYY}Q{N}``. Anything
    matching that pattern with fetch_status='complete' counts as loaded.
    """
    out: set[tuple[int, int]] = set()
    try:
        rows = con.execute(
            "SELECT object_key FROM ingestion_manifest "
            "WHERE source_type = 'NPORT' "
            "  AND object_type = 'DERA_ZIP' "
            "  AND fetch_status = 'complete'"
        ).fetchall()
    except duckdb.CatalogException:
        return out
    for (key,) in rows:
        if not key or not key.startswith("DERA_ZIP:"):
            continue
        try:
            y, q = parse_quarter(key.split(":", 1)[1])
            out.add((y, q))
        except ValueError:
            continue
    return out


def discover_missing_quarters(con: duckdb.DuckDBPyConnection,
                              today: Optional[date] = None) -> list[tuple[int, int]]:
    """Return DERA ZIPs the caller should fetch, oldest first.

    The mental model is ``ingestion_manifest`` is the source of truth for
    "what DERA ZIPs have been loaded." Given today's last complete DERA
    quarter ``last``:

      * No DERA loads yet + no prod data  → seed with the 4 most recent
        complete quarters.
      * No DERA loads yet + prod data     → load the 2 most recent
        complete quarters. This is the Session 2 first-run case: the
        user wants 2025Q4 + 2026Q1 when prod already has data through
        Nov 2025 via the XML path. Amendment resolution + per-tuple
        DELETE+INSERT means re-loading an already-represented month is
        safe and idempotent.
      * DERA loads exist                  → load anything newer than the
        latest loaded quarter, through ``last``.

    Returns [] when there's nothing newer than what's in the manifest.
    """
    last = _last_complete_dera_quarter(today)
    loaded = _already_loaded_quarters(con)

    prod_newest = con.execute(
        "SELECT MAX(report_date) FROM fund_holdings_v2"
    ).fetchone()[0]

    def _walk_backwards(from_yq: tuple[int, int], n: int) -> list[tuple[int, int]]:
        out = [from_yq]
        y, q = from_yq
        for _ in range(n - 1):
            if q == 1:
                y, q = y - 1, 4
            else:
                q -= 1
            out.append((y, q))
        return out

    candidates: list[tuple[int, int]]
    if not loaded:
        seed_count = 4 if prod_newest is None else 2
        candidates = sorted(_walk_backwards(last, seed_count))
    else:
        start = _quarter_after(*max(loaded))
        candidates = []
        cur = start
        while cur <= last:
            candidates.append(cur)
            cur = _quarter_after(*cur)

    # Clamp to DERA epoch (first ZIP was 2019Q4).
    return [yq for yq in candidates
            if yq >= _DERA_EPOCH and yq not in loaded]


def _staging_dera_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Ensure both control-plane and staging table DDL exist.

    The DERA load path writes manifest + impact rows; the control plane
    tables (``ingestion_manifest`` / ``ingestion_impacts``) are created by
    migration 001 in both prod and staging DBs, but tests run against
    freshly-created parity databases that need migration applied first.
    Staging (the default target) already has them — no-op in practice.
    """
    _ensure_staging_schema(con)


def _load_one_dera_quarter(
    year: int, quarter: int, run_id: str, zip_spec: Optional[str],
) -> dict[str, Any]:
    """Download (or resolve) + build + amendment-resolve + stage one DERA
    ZIP. Returns a stats dict suitable for the CLI progress line.
    """
    t0 = time.time()
    zip_path = download_dera_zip(year, quarter, zip_spec=zip_spec)

    dataset = build_dera_dataset(zip_path, filter_ciks=None)
    submissions = dataset["submissions"]

    # Open a short-lived read-only staging connection so resolve_amendments
    # can consult prior ZIPs' impacts for cross-ZIP dedupe. The load step
    # takes its own write connection right after this; DuckDB allows the
    # read handle to be opened and closed around it.
    try:
        resolve_con = duckdb.connect(STAGING_DB, read_only=True)
    except duckdb.IOException:
        # Another writer holds the lock — fall back to within-ZIP dedupe
        # only. Cross-ZIP duplicates will surface as _block_dup_series_month
        # and can be cleaned up post-hoc (see Session 2 close notes).
        resolve_con = None
    try:
        submissions_kept = resolve_amendments(submissions, staging_con=resolve_con)
    finally:
        if resolve_con is not None:
            resolve_con.close()
    n_dropped = len(submissions) - len(submissions_kept)

    holdings_written, series_written = dera_load_to_staging(
        dataset, submissions_kept, run_id,
    )

    # Stamp the ZIP itself as one control-plane row so repeat runs skip it.
    con = duckdb.connect(STAGING_DB)
    try:
        _staging_dera_schema(con)
        zip_key = f"DERA_ZIP:{year}Q{quarter}"
        manifest_id = get_or_create_manifest_row(
            con,
            source_type="NPORT",
            object_type="DERA_ZIP",
            source_url=dera_zip_url(year, quarter),
            accession_number=None,
            run_id=run_id,
            object_key=zip_key,
            fetch_status="complete",
            fetch_started_at=datetime.now(),
            fetch_completed_at=datetime.now(),
            local_path=str(zip_path),
            source_bytes=os.path.getsize(zip_path),
        )
        write_impact(
            con,
            manifest_id=manifest_id,
            target_table="fund_holdings_v2",
            unit_type="quarter",
            unit_key_json=json.dumps({"year": year, "quarter": quarter}),
            report_date=None,
            rows_staged=holdings_written,
            load_status="loaded",
        )
        con.execute("CHECKPOINT")
    finally:
        con.close()

    return {
        "year": year,
        "quarter": quarter,
        "holdings_written": holdings_written,
        "series_written": series_written,
        "submissions_total": len(submissions),
        "submissions_kept": len(submissions_kept),
        "amendments_dropped": n_dropped,
        "elapsed_s": round(time.time() - t0, 1),
        "zip_path": str(zip_path),
    }


def run_dera_bulk(limit: Optional[int], all_mode: bool, dry_run: bool,
                  zip_spec: Optional[str]) -> int:
    """Mode 1. Walk missing DERA quarters, load each into staging."""
    run_id = f"nport_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    _write_last_run(run_id)

    # Open the read DB (prod in staging mode) — holds the holdings floor.
    read_con = duckdb.connect(get_read_db_path(), read_only=True)
    try:
        all_quarters = discover_missing_quarters(read_con)
    finally:
        read_con.close()

    # Staging may hold DERA_ZIP keys stamped by prior runs. We only
    # consult it outside dry-run — under dry-run we can't always get a
    # read lock (e.g. a concurrent CUSIP staging writer holds it) and
    # "show the plan" has no side effects anyway.
    loaded: set[tuple[int, int]] = set()
    if not dry_run:
        try:
            staging_con = duckdb.connect(STAGING_DB, read_only=True)
            try:
                loaded = _already_loaded_quarters(staging_con)
            finally:
                staging_con.close()
        except duckdb.IOException as exc:
            print(f"  WARN: could not open staging read-only ({exc}). "
                  "Proceeding without prior-run filter; "
                  "load_to_staging DELETE+INSERT will idempotently "
                  "replace any conflicting rows.", flush=True)

    all_quarters = [yq for yq in all_quarters if yq not in loaded]

    if all_mode:
        quarters = all_quarters
    elif limit is not None:
        quarters = all_quarters[:limit]
    else:
        # Default behaviour: also treat as "all". Matches the pre-Session-2
        # CLI contract where ``--staging`` with no batch flag meant "full
        # run". Printed warning keeps slow-connection users honest.
        quarters = all_quarters

    print("=" * 60)
    print(f"fetch_nport_v2.py — Mode 1 DERA bulk  run_id={run_id}")
    print(f"  staging = {is_staging_mode()}  dry_run = {dry_run}")
    print(f"  zip_spec = {zip_spec!r}")
    print(f"  missing quarters ({len(all_quarters)}): "
          f"{[f'{y}Q{q}' for y,q in all_quarters]}")
    if limit is not None and not all_mode:
        print(f"  --limit {limit} -> processing first "
              f"{min(limit, len(all_quarters))}")
    print("=" * 60)

    if not quarters:
        print("  nothing to fetch — prod is already at the DERA frontier.")
        return 0

    if dry_run:
        for y, q in quarters:
            path = resolve_zip_path(y, q, zip_spec)
            src = f"local:{path}" if path else dera_zip_url(y, q)
            print(f"    would load {y}Q{q} from {src}")
        print("\n  dry-run — no downloads, no DB writes")
        return 0

    stats: list[dict[str, Any]] = []
    for y, q in quarters:
        print(f"\n[{y}Q{q}] starting...")
        result = _load_one_dera_quarter(y, q, run_id, zip_spec)
        stats.append(result)
        print(f"[{y}Q{q}] complete in {result['elapsed_s']}s — "
              f"{result['holdings_written']:,} holdings, "
              f"{result['series_written']:,} series, "
              f"{result['submissions_kept']:,} accessions "
              f"({result['amendments_dropped']} amendments dropped)")

    total_h = sum(s["holdings_written"] for s in stats)
    total_s = sum(s["series_written"] for s in stats)
    print("\n" + "=" * 60)
    print(f"DONE — {len(stats)} quarter(s) loaded, "
          f"{total_h:,} holdings, {total_s:,} series entries")
    print(f"run_id: {run_id}")
    print("  logs/last_run_id.txt written")
    print("Next:")
    print(f"  python3 scripts/validate_nport.py --changes-only --run-id {run_id} --staging")
    print(f"  python3 scripts/validate_nport.py --run-id {run_id} --staging")
    print("  # For large runs (>~10K series) use the fast subset validator +")
    print("  # queue step (validator is read-only; queue writes the pending rows):")
    print(f"  #   python3 scripts/validate_nport_subset.py --run-id {run_id} "
          "--resolved-file <resolved.txt> --excluded-file <excluded.txt> --staging")
    print("  #   python3 scripts/queue_nport_excluded.py --excluded-file <excluded.txt>")
    return 0


# ---------------------------------------------------------------------------
# Mode 2 — monthly topup via XML (legacy per-accession path)
# ---------------------------------------------------------------------------

class NPortXMLPipeline:
    """XML per-accession pipeline — preserved verbatim from Session 1's
    ``NPortPipeline`` for the monthly topup path. Used only by Mode 2
    now; Mode 1 bypasses XML entirely.
    """

    source_type = "NPORT"

    def __init__(self, *, run_id: str, cik_filter: Optional[list[int]],
                 current_quarter: tuple[int, int],
                 since_date: Optional[date]) -> None:
        self.run_id = run_id
        self.cik_filter = cik_filter
        self.current_quarter = current_quarter
        self.since_date = since_date

    # ----- discover ------------------------------------------------------

    def discover(self) -> list[DownloadTarget]:
        """Current-quarter N-PORT filings filed since ``since_date``.

        Mode 2's whole point is to pick up NEW monthly filings that have
        posted after the last DERA bulk ZIP. We call edgar.get_filings()
        once for the current calendar quarter — NOT once per historical
        quarter — and anti-join the manifest on accession_number.
        """
        from edgar import get_filings  # local import
        configure_edgar_identity()

        year, quarter = self.current_quarter
        try:
            q_filings = get_filings(year=year, quarter=quarter, form="NPORT-P")
        except Exception as exc:  # pylint: disable=broad-except
            print(f"  monthly-topup: edgar.get_filings({year}Q{quarter}) "
                  f"failed — {exc}", flush=True)
            return []
        if q_filings is None:
            return []

        df = q_filings.data.to_pandas()
        if df.empty:
            return []

        if self.since_date is not None:
            df = df[df["filing_date"] > self.since_date]
        df = df.reset_index(drop=True)

        con = duckdb.connect(get_read_db_path(), read_only=True)
        try:
            already = set(con.execute(
                "SELECT accession_number FROM ingestion_manifest "
                "WHERE source_type = 'NPORT' AND fetch_status = 'complete'"
            ).fetchdf()["accession_number"].tolist())
        finally:
            con.close()

        targets: list[DownloadTarget] = []
        for _, row in df.iterrows():
            acc = row["accession_number"]
            if acc in already:
                continue
            cik = int(row["cik"])
            if self.cik_filter and cik not in self.cik_filter:
                continue
            url = (
                f"https://www.sec.gov/Archives/edgar/data/"
                f"{cik}/{acc.replace('-', '')}/primary_doc.xml"
            )
            targets.append(DownloadTarget(
                source_type="NPORT",
                object_type="XML",
                source_url=url,
                accession_number=acc,
                filing_date=row["filing_date"],
                extras={"fund_cik": str(cik).zfill(10)},
            ))
        return targets

    # ----- fetch ---------------------------------------------------------

    def fetch(self, target: DownloadTarget) -> FetchResult:
        acc = target.accession_number
        cik = target.extras.get("fund_cik", "0").lstrip("0") or "0"
        cik_dir = os.path.join(L1_DIR, cik)
        os.makedirs(cik_dir, exist_ok=True)
        local_path = os.path.join(cik_dir, f"{acc}.xml")

        con = duckdb.connect(get_db_path())
        try:
            manifest_id = get_or_create_manifest_row(
                con,
                source_type=self.source_type,
                object_type="XML",
                source_url=target.source_url,
                accession_number=acc,
                run_id=self.run_id,
                object_key=acc,
                fetch_status="fetching",
                fetch_started_at=datetime.now(),
            )
            con.execute("CHECKPOINT")
        finally:
            con.close()

        success = True
        http_code = None
        source_bytes = 0
        error_message: Optional[str] = None

        try:
            if os.path.exists(local_path) and os.path.getsize(local_path) > 0:
                source_bytes = os.path.getsize(local_path)
                http_code = 200
            else:
                resp, log = sec_fetch(target.source_url, headers=SEC_HEADERS,
                                      max_retries=3, timeout=30)
                content = resp.content
                source_bytes = len(content)
                http_code = log.http_code
                with open(local_path, "wb") as fh:
                    fh.write(content)
        except Exception as exc:  # pylint: disable=broad-except
            success = False
            error_message = str(exc)[:500]

        con = duckdb.connect(get_db_path())
        try:
            update_manifest_status(
                con, manifest_id,
                "complete" if success else "failed",
                fetch_completed_at=datetime.now(),
                http_code=http_code,
                source_bytes=source_bytes,
                local_path=local_path if success else None,
                error_message=error_message,
            )
            con.execute("CHECKPOINT")
        finally:
            con.close()

        return FetchResult(
            target=target, manifest_id=manifest_id,
            local_path=local_path if success else None,
            http_code=http_code, source_bytes=source_bytes,
            source_checksum=None, success=success,
            error_message=error_message,
        )

    # ----- parse ---------------------------------------------------------

    def parse(self, fetch_result: FetchResult) -> ParseResult:
        if not fetch_result.success or not fetch_result.local_path:
            return ParseResult(
                fetch_result=fetch_result, rows=[], parse_status="failed",
                parser_version=PARSER_VERSION, schema_version="?",
                qc_failures=[QCFailure(field="_", value=None,
                                       rule="fetch_failed", severity="BLOCK")],
            )

        try:
            with open(fetch_result.local_path, "rb") as fh:
                xml_bytes = fh.read()
        except Exception as exc:  # pylint: disable=broad-except
            return ParseResult(
                fetch_result=fetch_result, rows=[], parse_status="failed",
                parser_version=PARSER_VERSION, schema_version="?",
                qc_failures=[QCFailure(field="_", value=None,
                                       rule=f"read_error:{exc}",
                                       severity="BLOCK")],
            )

        schema_version = "nport-1"
        metadata, holdings = parse_nport_xml(xml_bytes)
        if metadata is None:
            return ParseResult(
                fetch_result=fetch_result, rows=[], parse_status="failed",
                parser_version=PARSER_VERSION, schema_version=schema_version,
                qc_failures=[QCFailure(field="_", value=None,
                                       rule="xml_parse_failed",
                                       severity="BLOCK")],
            )

        qc: list[QCFailure] = []
        series_id = metadata.get("series_id")
        acc = fetch_result.target.accession_number
        reg_cik = metadata.get("reg_cik") or fetch_result.target.extras.get("fund_cik", "")
        if not series_id:
            series_id = f"{reg_cik}_{acc}"
            qc.append(QCFailure(
                field="series_id", value=None,
                rule="series_id_synthetic_fallback", severity="FLAG",
            ))
            print(f"  WARN: series_id missing in {acc}, "
                  f"using synthetic key '{series_id}'", flush=True)

        rep_pd = metadata.get("rep_pd_date") or metadata.get("rep_pd_end")
        if not rep_pd:
            return ParseResult(
                fetch_result=fetch_result, rows=[], parse_status="failed",
                parser_version=PARSER_VERSION, schema_version=schema_version,
                qc_failures=[QCFailure(field="rep_pd_date", value=None,
                                       rule="report_period_missing",
                                       severity="BLOCK")],
            )
        try:
            rep_dt = datetime.strptime(rep_pd, "%Y-%m-%d").date()
        except ValueError:
            return ParseResult(
                fetch_result=fetch_result, rows=[], parse_status="failed",
                parser_version=PARSER_VERSION, schema_version=schema_version,
                qc_failures=[QCFailure(field="rep_pd_date", value=rep_pd,
                                       rule="bad_date_format",
                                       severity="BLOCK")],
            )
        report_month = rep_dt.strftime("%Y-%m")
        quarter = quarter_label_for_date(rep_dt)

        if metadata.get("is_final") == "Y":
            qc.append(QCFailure(field="is_final", value="Y",
                                rule="fund_closed", severity="FLAG"))

        is_active_equity, fund_category, is_actively_managed = classify_fund(
            metadata, holdings,
        )

        rows: list[dict[str, Any]] = []
        cik_padded = (reg_cik or "0").lstrip("0").zfill(10)
        for h in holdings:
            rows.append({
                "fund_cik": cik_padded,
                "fund_name": metadata.get("series_name") or metadata.get("reg_name"),
                "family_name": metadata.get("reg_name"),
                "series_id": series_id,
                "quarter": quarter,
                "report_month": report_month,
                "report_date": rep_dt,
                "cusip": h.get("cusip"),
                "isin": h.get("isin") or None,
                "issuer_name": h.get("name"),
                "ticker": h.get("ticker") or None,
                "asset_category": h.get("asset_cat"),
                "shares_or_principal": float(h["balance"]) if h.get("balance") else None,
                "market_value_usd": float(h["val_usd"]) if h.get("val_usd") else None,
                "pct_of_nav": float(h["pct_val"]) if h.get("pct_val") else None,
                "fair_value_level": h.get("fair_val_level"),
                "is_restricted": h.get("is_restricted") == "Y" if h.get("is_restricted") else False,
                "payoff_profile": h.get("payoff_profile"),
                "fund_strategy": fund_category,
                "best_index": None,
                "accession_number": acc,
            })

        meta_row = {
            "fund_cik": cik_padded,
            "fund_name": metadata.get("series_name") or metadata.get("reg_name"),
            "series_id": series_id,
            "family_name": metadata.get("reg_name"),
            "total_net_assets": float(metadata["net_assets"]) if metadata.get("net_assets") else None,
            "fund_category": fund_category,
            "is_actively_managed": is_actively_managed,
            "total_holdings_count": len(holdings),
            "equity_pct": None,
            "top10_concentration": None,
            "fund_strategy": fund_category,
            "best_index": None,
            "_is_active_equity": is_active_equity,
            "_report_month": report_month,
        }

        status = "partial" if any(q.severity == "BLOCK" for q in qc) else "complete"

        if rows:
            rows[0]["_meta"] = meta_row
        else:
            rows.append({"_meta": meta_row, "_empty_holdings": True})

        return ParseResult(
            fetch_result=fetch_result, rows=rows, parse_status=status,
            parser_version=PARSER_VERSION, schema_version=schema_version,
            qc_failures=qc,
        )

    # ----- load_to_staging ----------------------------------------------

    def load(self, parse_result: ParseResult) -> int:
        if not parse_result.rows:
            return 0
        meta_row = None
        clean_rows: list[dict[str, Any]] = []
        for r in parse_result.rows:
            m = r.pop("_meta", None)
            if m and meta_row is None:
                meta_row = m
            if r.get("_empty_holdings"):
                continue
            clean_rows.append(r)
        if meta_row is None:
            return 0

        series_id = meta_row["series_id"]
        report_month = meta_row["_report_month"]
        manifest_id = parse_result.fetch_result.manifest_id
        now = datetime.now()

        con = duckdb.connect(get_db_path())
        try:
            _ensure_staging_schema(con)
            con.execute("BEGIN")
            try:
                impact_unit_key = json.dumps({
                    "series_id": series_id, "report_month": report_month,
                })
                write_impact(
                    con,
                    manifest_id=manifest_id,
                    target_table="fund_holdings_v2",
                    unit_type="series_month",
                    unit_key_json=impact_unit_key,
                    report_date=meta_row.get("_report_month") + "-01"
                                if meta_row.get("_report_month") else None,
                    rows_staged=len(clean_rows),
                    load_status="partial",
                )
                con.execute(
                    "DELETE FROM stg_nport_holdings "
                    "WHERE series_id = ? AND report_month = ?",
                    [series_id, report_month],
                )
                qc_flags = json.dumps([
                    {"field": q.field, "rule": q.rule, "severity": q.severity}
                    for q in parse_result.qc_failures
                ]) if parse_result.qc_failures else None

                CHUNK = 500
                for start in range(0, len(clean_rows), CHUNK):
                    chunk = clean_rows[start:start + CHUNK]
                    payload = [
                        [
                            r["fund_cik"], r["fund_name"], r["family_name"],
                            r["series_id"], r["quarter"], r["report_month"],
                            r["report_date"], r["cusip"], r["isin"],
                            r["issuer_name"], r["ticker"], r["asset_category"],
                            r["shares_or_principal"], r["market_value_usd"],
                            r["pct_of_nav"], r["fair_value_level"],
                            r["is_restricted"], r["payoff_profile"], now,
                            r["fund_strategy"], r["best_index"],
                            r["accession_number"], manifest_id,
                            parse_result.parse_status, qc_flags,
                        ]
                        for r in chunk
                    ]
                    con.executemany(
                        """
                        INSERT INTO stg_nport_holdings (
                            fund_cik, fund_name, family_name, series_id,
                            quarter, report_month, report_date, cusip, isin,
                            issuer_name, ticker, asset_category,
                            shares_or_principal, market_value_usd, pct_of_nav,
                            fair_value_level, is_restricted, payoff_profile,
                            loaded_at, fund_strategy, best_index,
                            accession_number, manifest_id, parse_status, qc_flags
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        payload,
                    )

                con.execute(
                    "DELETE FROM stg_nport_fund_universe WHERE series_id = ?",
                    [series_id],
                )
                con.execute(
                    """
                    INSERT INTO stg_nport_fund_universe (
                        fund_cik, fund_name, series_id, family_name,
                        total_net_assets, fund_category, is_actively_managed,
                        total_holdings_count, equity_pct, top10_concentration,
                        last_updated, fund_strategy, best_index, manifest_id
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    [
                        meta_row["fund_cik"], meta_row["fund_name"],
                        meta_row["series_id"], meta_row["family_name"],
                        meta_row["total_net_assets"], meta_row["fund_category"],
                        meta_row["is_actively_managed"],
                        meta_row["total_holdings_count"], meta_row["equity_pct"],
                        meta_row["top10_concentration"], now,
                        meta_row["fund_strategy"], meta_row["best_index"],
                        manifest_id,
                    ],
                )
                con.execute(
                    """
                    UPDATE ingestion_impacts
                       SET load_status = 'loaded'
                     WHERE manifest_id = ?
                       AND unit_type = 'series_month'
                       AND unit_key_json = ?
                    """,
                    [manifest_id, impact_unit_key],
                )
                con.execute("COMMIT")
                con.execute("CHECKPOINT")
            except Exception:
                con.execute("ROLLBACK")
                raise
            return len(clean_rows)
        finally:
            con.close()


def _current_quarter(today: Optional[date] = None) -> tuple[int, int]:
    t = today or date.today()
    return t.year, (t.month - 1) // 3 + 1


def _most_recent_dera_ziped_date(staging_con) -> Optional[date]:
    """The last REPORT_DATE represented by a DERA ZIP manifest row in
    staging — used as the ``since_date`` floor for Mode 2 so we only
    fetch XML for filings that post after the last ZIP's cutoff."""
    try:
        rows = staging_con.execute(
            "SELECT object_key FROM ingestion_manifest "
            "WHERE source_type='NPORT' AND object_type='DERA_ZIP' "
            "  AND fetch_status='complete'"
        ).fetchall()
    except duckdb.CatalogException:
        return None
    latest: Optional[tuple[int, int]] = None
    for (key,) in rows:
        if not key or not key.startswith("DERA_ZIP:"):
            continue
        try:
            y, q = parse_quarter(key.split(":", 1)[1])
        except ValueError:
            continue
        if latest is None or (y, q) > latest:
            latest = (y, q)
    if latest is None:
        return None
    # DERA ZIP for YYYYqN is compiled ~end of that quarter; use quarter-end
    # as a conservative lower bound.
    y, q = latest
    month_end = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}[q]
    return date(y, *month_end)


def run_monthly_topup(limit: Optional[int], dry_run: bool) -> int:
    """Mode 2. XML per-accession for the current incomplete quarter."""
    run_id = f"nport_topup_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    _write_last_run(run_id)

    cur = _current_quarter()
    staging_con = duckdb.connect(STAGING_DB, read_only=True)
    try:
        since = _most_recent_dera_ziped_date(staging_con)
    finally:
        staging_con.close()

    print("=" * 60)
    print(f"fetch_nport_v2.py — Mode 2 monthly topup  run_id={run_id}")
    print(f"  current quarter: {cur[0]}Q{cur[1]}")
    print(f"  since_date:      {since}")
    print(f"  limit:           {limit}")
    print(f"  dry_run:         {dry_run}")
    print("=" * 60)

    pipeline = NPortXMLPipeline(
        run_id=run_id, cik_filter=None, current_quarter=cur,
        since_date=since,
    )
    targets = pipeline.discover()
    print(f"  discovered {len(targets)} candidate accession(s)")

    if dry_run:
        for t in targets[:25]:
            print(f"    would fetch {t.accession_number}  cik={t.extras.get('fund_cik')}")
        if len(targets) > 25:
            print(f"    ... and {len(targets)-25} more")
        return 0
    if not targets:
        print("  nothing new to fetch")
        return 0

    t0 = time.time()
    fetched_ok = 0
    parse_failed = 0
    qc_blocked = 0
    loaded = 0
    for i, target in enumerate(targets, start=1):
        fr = pipeline.fetch(target)
        if not fr.success:
            parse_failed += 1
            continue
        fetched_ok += 1
        pr = pipeline.parse(fr)
        if pr.parse_status == "failed":
            parse_failed += 1
            continue
        if any(q.severity == "BLOCK" for q in pr.qc_failures):
            qc_blocked += 1
        loaded += pipeline.load(pr)
        if i % 10 == 0 or i == len(targets):
            print(f"  [{i}/{len(targets)}] ok={fetched_ok} "
                  f"loaded={loaded:,} parse_fail={parse_failed} "
                  f"qc_blocked={qc_blocked} "
                  f"elapsed={time.time()-t0:.1f}s", flush=True)
        if limit is not None and fetched_ok >= limit:
            print(f"  --limit {limit} reached, stopping")
            break

    print(f"\nDONE topup — ok={fetched_ok} holdings={loaded:,} "
          f"parse_fail={parse_failed} qc_blocked={qc_blocked}")
    print(f"run_id: {run_id}")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _write_last_run(run_id: str) -> None:
    os.makedirs(os.path.join(BASE_DIR, "logs"), exist_ok=True)
    with open(os.path.join(BASE_DIR, "logs", "last_run_id.txt"), "w") as fh:
        fh.write(run_id)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="N-PORT orchestrator (DERA bulk + XML topup)")
    parser.add_argument("--staging", action="store_true",
                        help="Write to staging DB (required unless --dry-run/--test).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show the plan for Mode 1. No writes.")
    parser.add_argument("--test", action="store_true",
                        help="Mode 3: parity test. Delegates to "
                             "fetch_dera_nport.run_test_mode().")
    parser.add_argument("--monthly-topup", action="store_true",
                        help="Mode 2: XML per-accession for the current "
                             "incomplete quarter.")
    parser.add_argument("--limit", type=int, metavar="N", default=None,
                        help="Mode 1: number of quarters. Mode 2: number "
                             "of accessions. Resume on next run.")
    parser.add_argument("--all", action="store_true",
                        help="Mode 1: process all missing quarters "
                             "(default behaviour; flag kept for parity "
                             "with the pre-Session-2 CLI).")
    parser.add_argument("--zip", type=str, default="",
                        help="File or directory with pre-downloaded DERA "
                             "ZIPs ({YYYY}q{N}_nport.zip). Skips download "
                             "when a match is present.")
    parser.add_argument("--ciks", type=str, default="",
                        help="(Mode 2 only) comma-separated CIK filter.")
    args = parser.parse_args()

    if args.limit is not None and args.all:
        sys.stderr.write(
            "ERROR: --limit and --all are mutually exclusive.\n"
        )
        sys.exit(2)

    zip_spec = args.zip or None

    # Mode 3 — parity test
    if args.test:
        set_staging_mode(True)
        sys.exit(run_test_mode(zip_spec=zip_spec))

    # Mode 2 — monthly topup (XML)
    if args.monthly_topup:
        if not args.staging and not args.dry_run:
            sys.stderr.write(
                "ERROR: --monthly-topup must run with --staging or --dry-run.\n"
            )
            sys.exit(2)
        set_staging_mode(True)
        sys.exit(run_monthly_topup(args.limit, args.dry_run))

    # Mode 1 — DERA bulk (default)
    if not args.staging and not args.dry_run:
        sys.stderr.write(
            "ERROR: non-test runs must pass --staging or --dry-run.\n"
        )
        sys.exit(2)
    if args.staging:
        set_staging_mode(True)
    sys.exit(run_dera_bulk(
        limit=args.limit, all_mode=args.all,
        dry_run=args.dry_run, zip_spec=zip_spec,
    ))


if __name__ == "__main__":
    crash_handler("fetch_nport_v2")(main)
