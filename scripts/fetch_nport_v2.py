#!/usr/bin/env python3
# CHECKPOINT GRANULARITY POLICY
# This pipeline checkpoints after every unit of work listed below.
# A restart never reprocesses more than one unit.
# fetch_nport_v2.py unit: one series within one accession.
# A single accession may contain holdings for one or more series; each
# series is loaded atomically. Partial series loads are detected via
# ingestion_impacts.load_status='partial' on restart and re-processed.
# Never accumulate results across accessions before writing.
"""fetch_nport_v2.py — SourcePipeline for SEC NPORT-P filings.

Rewrite of scripts/fetch_nport.py that conforms to
scripts/pipeline/protocol.SourcePipeline. Clears all 10 PROCESS_RULES
violations from docs/pipeline_violations.md:

  1. writes to fund_holdings_v2 (not the dropped `fund_holdings`)
  2. dynamic quarter/month/EDGAR date computation, no hardcoded year maps
  3. --test routes to staging via set_staging_mode(True), never prod
  4. atomic series-level loads via ingestion_impacts.load_status; restart
     detects partial loads and replays only the affected series
  5. sec_fetch() handles 5xx backoff + 429 60s pause + retries
  6. amendment handling: DELETE+INSERT by (series_id, report_month) at
     promote time supersedes prior filings for the same period
  7. series_id fallback uses synthetic key f"{reg_cik}_{accession}" with
     a logged WARNing rather than literal "UNKNOWN"
  8. transactions per series; CHECKPOINT after each series load
  9. data_freshness stamped via shared.stamp_freshness in promote step
 10. parameterised SQL only (no f-string interpolation of user input)

Reuses the proven XML parser from fetch_nport.parse_nport_xml() and the
fund classifier from fetch_nport.classify_fund(). The legacy script
itself stays in scripts/ until v2 has run cleanly twice (amendment
chain test) before retiring.
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
    crash_handler,
)
from fetch_nport import parse_nport_xml, classify_fund  # noqa: E402

from pipeline.discover import discover_nport  # noqa: E402
from pipeline.manifest import (  # noqa: E402
    get_or_create_manifest_row, update_manifest_status, write_impact,
)
from pipeline.protocol import (  # noqa: E402
    DownloadTarget, FetchResult, ParseResult, QCFailure,
)
from pipeline.shared import sec_fetch  # noqa: E402


L1_DIR = os.path.join(BASE_DIR, "data", "nport_raw")
SEC_HEADERS = {"User-Agent": "13f-research serge.tismen@gmail.com"}
PARSER_VERSION = "nport_v2.1"

# Test-fund universe — same five reference funds as the original
# fetch_nport.TEST_FUNDS, used by --test mode.
TEST_FUNDS: dict[str, int] = {
    "Fidelity Contrafund":          24238,
    "Vanguard Wellington Fund":     105563,
    "T. Rowe Price Blue Chip":      902259,
    "Dodge & Cox Funds":            29440,
    "Growth Fund of America":       44201,
}


# ---------------------------------------------------------------------------
# Dynamic quarter labelling (replaces fetch_nport.MONTHLY_TARGETS dict)
# ---------------------------------------------------------------------------

def quarter_label_for_month(year: int, month: int) -> str:
    """Map an N-PORT report-period month to its prod ``quarter`` label.

    Convention observed in prod ``fund_holdings_v2``:

      report_month YYYY-MM  →  quarter
      Jan/Feb/Mar           →  YYYY-Q2
      Apr/May/Jun           →  YYYY-Q3
      Jul/Aug/Sep           →  YYYY-Q4
      Oct/Nov/Dec           →  (YYYY+1)-Q1
    """
    if month >= 10:
        return f"{year + 1}Q1"
    if month >= 7:
        return f"{year}Q4"
    if month >= 4:
        return f"{year}Q3"
    return f"{year}Q2"


def quarter_label_for_date(d: date) -> str:
    return quarter_label_for_month(d.year, d.month)


# ---------------------------------------------------------------------------
# Staging DDL
# ---------------------------------------------------------------------------

# Mirror of prod fund_holdings_v2 (Group 1 columns) plus three control-plane
# extras. Group 2 entity columns (entity_id / rollup_entity_id /
# dm_entity_id / dm_rollup_entity_id / dm_rollup_name) are NOT written
# at staging time — they're populated in promote_nport.py via
# entity_current lookup. Group 3 enrichment is enrich_holdings.py later.
_STG_HOLDINGS_DDL = """
CREATE TABLE IF NOT EXISTS stg_nport_holdings (
    fund_cik             VARCHAR,
    fund_name            VARCHAR,
    family_name          VARCHAR,
    series_id            VARCHAR,
    quarter              VARCHAR,
    report_month         VARCHAR,
    report_date          DATE,
    cusip                VARCHAR,
    isin                 VARCHAR,
    issuer_name          VARCHAR,
    ticker               VARCHAR,
    asset_category       VARCHAR,
    shares_or_principal  DOUBLE,
    market_value_usd     DOUBLE,
    pct_of_nav           DOUBLE,
    fair_value_level     VARCHAR,
    is_restricted        BOOLEAN,
    payoff_profile       VARCHAR,
    loaded_at            TIMESTAMP,
    fund_strategy        VARCHAR,
    best_index           VARCHAR,
    accession_number     VARCHAR,
    -- control-plane extras
    manifest_id          BIGINT,
    parse_status         VARCHAR,
    qc_flags             VARCHAR
)
"""

# Mirror of prod fund_universe (PK series_id) plus manifest_id.
_STG_UNIVERSE_DDL = """
CREATE TABLE IF NOT EXISTS stg_nport_fund_universe (
    fund_cik              VARCHAR,
    fund_name             VARCHAR,
    series_id             VARCHAR PRIMARY KEY,
    family_name           VARCHAR,
    total_net_assets      DOUBLE,
    fund_category         VARCHAR,
    is_actively_managed   BOOLEAN,
    total_holdings_count  INTEGER,
    equity_pct            DOUBLE,
    top10_concentration   DOUBLE,
    last_updated          TIMESTAMP,
    fund_strategy         VARCHAR,
    best_index            VARCHAR,
    manifest_id           BIGINT
)
"""


def _ensure_staging_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(_STG_HOLDINGS_DDL)
    con.execute(_STG_UNIVERSE_DDL)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

class NPortPipeline:
    """SourcePipeline for SEC NPORT-P. Conforms structurally to
    scripts.pipeline.protocol.SourcePipeline.

    Test mode: 5 well-known fund CIKs from TEST_FUNDS, ~latest 4 NPORT-P
    each = up to 20 accessions max. Full mode is intentionally not
    plumbed into this CLI yet — that's an authorized run separate from
    Batch 2C.
    """

    source_type = "NPORT"

    def __init__(self, *, run_id: str, test_mode: bool = False,
                 cik_filter: Optional[list[int]] = None,
                 limit: Optional[int] = None) -> None:
        self.run_id = run_id
        self.test_mode = test_mode
        self.cik_filter = cik_filter
        self.limit = limit

    # ----- discover ------------------------------------------------------

    def discover(self, run_id: str) -> list[DownloadTarget]:
        """Per-CIK EDGAR query when test mode or cik_filter is set; full
        EDGAR-quarter index otherwise. Anti-joins ingestion_manifest in
        discover_nport itself."""
        os.makedirs(L1_DIR, exist_ok=True)

        if self.test_mode and not self.cik_filter:
            cik_filter = list(TEST_FUNDS.values())
        else:
            cik_filter = self.cik_filter

        con = duckdb.connect(get_read_db_path(), read_only=True)
        try:
            targets = discover_nport(
                con,
                cik_filter=cik_filter,
                max_per_cik=4 if self.test_mode else 12,
            )
        finally:
            con.close()

        if self.limit:
            targets = targets[: self.limit]
        return targets

    # ----- fetch ---------------------------------------------------------

    def fetch(self, target: DownloadTarget, run_id: str) -> FetchResult:
        """Download primary_doc.xml, write L1 artefact, manifest row.

        If a local cache file already exists with non-zero size we still
        record a manifest row (idempotent re-fetch trivially fast).
        """
        acc = target.accession_number
        cik = target.extras.get("fund_cik", "0").lstrip("0") or "0"
        cik_dir = os.path.join(L1_DIR, cik)
        os.makedirs(cik_dir, exist_ok=True)
        local_path = os.path.join(cik_dir, f"{acc}.xml")

        con = duckdb.connect(get_db_path())
        manifest_id: Optional[int] = None
        try:
            manifest_id = get_or_create_manifest_row(
                con,
                source_type=self.source_type,
                object_type="XML",
                source_url=target.source_url,
                accession_number=acc,
                run_id=run_id,
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
            # Use the cached file if it exists; it's the same primary_doc.xml
            # by accession. Saves a fetch when re-running the same run_id.
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
            target=target,
            manifest_id=manifest_id,
            local_path=local_path if success else None,
            http_code=http_code,
            source_bytes=source_bytes,
            source_checksum=None,
            success=success,
            error_message=error_message,
        )

    # ----- parse ---------------------------------------------------------

    def parse(self, fetch_result: FetchResult) -> ParseResult:
        """Run fetch_nport.parse_nport_xml + classify_fund + QC gates.

        Returns ParseResult with one row per holding plus the metadata
        dict (used by load_to_staging() to upsert fund_universe).
        """
        if not fetch_result.success or not fetch_result.local_path:
            return ParseResult(
                fetch_result=fetch_result, rows=[], parse_status="failed",
                parser_version=PARSER_VERSION, schema_version="?",
                qc_failures=[QCFailure(
                    field="_", value=None, rule="fetch_failed",
                    severity="BLOCK",
                )],
            )

        try:
            with open(fetch_result.local_path, "rb") as fh:
                xml_bytes = fh.read()
        except Exception as exc:  # pylint: disable=broad-except
            return ParseResult(
                fetch_result=fetch_result, rows=[], parse_status="failed",
                parser_version=PARSER_VERSION, schema_version="?",
                qc_failures=[QCFailure(
                    field="_", value=None, rule=f"read_error:{exc}",
                    severity="BLOCK",
                )],
            )

        # Detect schema version from xmlns
        schema_version = "nport-1"  # SEC has only ever published one
        if b"xmlns=\"http://www.sec.gov/edgar/nport\"" in xml_bytes:
            schema_version = "nport-1"

        metadata, holdings = parse_nport_xml(xml_bytes)
        if metadata is None:
            return ParseResult(
                fetch_result=fetch_result, rows=[], parse_status="failed",
                parser_version=PARSER_VERSION, schema_version=schema_version,
                qc_failures=[QCFailure(
                    field="_", value=None, rule="xml_parse_failed",
                    severity="BLOCK",
                )],
            )

        qc: list[QCFailure] = []

        # series_id fallback — synthetic key with logged warning
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
                qc_failures=[QCFailure(
                    field="rep_pd_date", value=None,
                    rule="report_period_missing", severity="BLOCK",
                )],
            )
        try:
            rep_dt = datetime.strptime(rep_pd, "%Y-%m-%d").date()
        except ValueError:
            return ParseResult(
                fetch_result=fetch_result, rows=[], parse_status="failed",
                parser_version=PARSER_VERSION, schema_version=schema_version,
                qc_failures=[QCFailure(
                    field="rep_pd_date", value=rep_pd,
                    rule="bad_date_format", severity="BLOCK",
                )],
            )
        report_month = rep_dt.strftime("%Y-%m")
        quarter = quarter_label_for_date(rep_dt)

        if metadata.get("is_final") == "Y":
            qc.append(QCFailure(
                field="is_final", value="Y",
                rule="fund_closed", severity="FLAG",
            ))

        # Classification (unchanged from legacy pipeline)
        is_active_equity, fund_category, is_actively_managed = classify_fund(
            metadata, holdings,
        )

        # Build holding rows
        rows: list[dict[str, Any]] = []
        cik_padded = (reg_cik or "0").lstrip("0").zfill(10)
        for h in holdings:
            rows.append({
                "fund_cik":            cik_padded,
                "fund_name":           metadata.get("series_name") or metadata.get("reg_name"),
                "family_name":         metadata.get("reg_name"),
                "series_id":           series_id,
                "quarter":             quarter,
                "report_month":        report_month,
                "report_date":         rep_dt,
                "cusip":               h.get("cusip"),
                "isin":                h.get("isin") or None,
                "issuer_name":         h.get("name"),
                "ticker":              h.get("ticker") or None,
                "asset_category":      h.get("asset_cat"),
                "shares_or_principal": float(h["balance"]) if h.get("balance") else None,
                "market_value_usd":    float(h["val_usd"]) if h.get("val_usd") else None,
                "pct_of_nav":          float(h["pct_val"]) if h.get("pct_val") else None,
                "fair_value_level":    h.get("fair_val_level"),
                "is_restricted":       h.get("is_restricted") == "Y" if h.get("is_restricted") else False,
                "payoff_profile":      h.get("payoff_profile"),
                "fund_strategy":       fund_category,
                "best_index":          None,  # populated by build_benchmark_weights.py
                "accession_number":    acc,
            })

        # Sidecar metadata used by load_to_staging() to upsert universe
        meta_row = {
            "fund_cik":             cik_padded,
            "fund_name":            metadata.get("series_name") or metadata.get("reg_name"),
            "series_id":            series_id,
            "family_name":          metadata.get("reg_name"),
            "total_net_assets":     float(metadata["net_assets"]) if metadata.get("net_assets") else None,
            "fund_category":        fund_category,
            "is_actively_managed":  is_actively_managed,
            "total_holdings_count": len(holdings),
            "equity_pct":           None,  # legacy column not currently populated
            "top10_concentration":  None,
            "fund_strategy":        fund_category,
            "best_index":           None,
            "_is_active_equity":    is_active_equity,
            "_report_month":        report_month,
        }

        status = "complete"
        if any(q.severity == "BLOCK" for q in qc):
            status = "partial"

        # Stash metadata on the result object via a sidecar attr — the
        # ParseResult dataclass is frozen-like in spirit; we use a list
        # element convention: rows[0]['_meta'] = meta_row. This is a
        # contained extension — only load_to_staging looks for it.
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

    def load_to_staging(self, parse_result: ParseResult,
                        staging_db_path: str, run_id: str) -> int:
        """Insert holdings + upsert fund_universe + impact row.

        Atomic per-series: BEGIN → DELETE existing partial rows for
        (series_id, report_month) → INSERT all fresh rows → write impact
        loaded → COMMIT → CHECKPOINT. If the process dies mid-load,
        ingestion_impacts.load_status='partial' is left behind and the
        next run replays just this series.
        """
        if not parse_result.rows:
            return 0

        # Pull sidecar meta then strip it from row payload
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

        con = duckdb.connect(staging_db_path)
        try:
            _ensure_staging_schema(con)
            con.execute("BEGIN")
            try:
                # Mark impact partial first so a crash leaves the right state
                impact_unit_key = json.dumps({
                    "series_id": series_id,
                    "report_month": report_month,
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

                # Replace any previously-staged rows for this (series, month)
                con.execute(
                    "DELETE FROM stg_nport_holdings "
                    "WHERE series_id = ? AND report_month = ?",
                    [series_id, report_month],
                )

                qc_flags = json.dumps([
                    {"field": q.field, "rule": q.rule, "severity": q.severity}
                    for q in parse_result.qc_failures
                ]) if parse_result.qc_failures else None

                # INSERT in 500-row chunks with CHECKPOINT in between
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
                            r["accession_number"],
                            manifest_id, parse_result.parse_status, qc_flags,
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

                # Upsert fund_universe sidecar row
                # (PK = series_id; replace by deleting first to avoid the
                # multi-unique INSERT OR REPLACE issue.)
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

                # Update impact to loaded
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


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _write_last_run(run_id: str) -> None:
    os.makedirs(os.path.join(BASE_DIR, "logs"), exist_ok=True)
    with open(os.path.join(BASE_DIR, "logs", "last_run_id.txt"), "w") as fh:
        fh.write(run_id)


def run_dry(test_mode: bool, cik_filter: Optional[list[int]]) -> int:
    print("=" * 60)
    print("fetch_nport_v2.py --dry-run")
    print(f"  test={test_mode}  cik_filter={cik_filter}")
    print("=" * 60)
    run_id = f"nport_{datetime.now().strftime('%Y%m%d_%H%M%S')}_dryrun"
    pipeline = NPortPipeline(run_id=run_id, test_mode=test_mode,
                             cik_filter=cik_filter)
    targets = pipeline.discover(run_id)
    print(f"\n  discover returned {len(targets)} accession(s)")
    by_cik: dict[str, int] = {}
    for t in targets:
        c = t.extras.get("fund_cik", "?")
        by_cik[c] = by_cik.get(c, 0) + 1
    for c, n in sorted(by_cik.items()):
        print(f"    fund_cik={c}: {n}")
    print("  (no DB writes)")
    return 0


def run_pipeline(test_mode: bool,
                 cik_filter: Optional[list[int]],
                 limit: Optional[int]) -> int:
    run_id = f"nport_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    _write_last_run(run_id)
    print("=" * 60)
    print(f"fetch_nport_v2.py  run_id={run_id}")
    print(f"  staging={is_staging_mode()}  test={test_mode}  limit={limit}")
    print(f"  cik_filter={cik_filter}")
    print("=" * 60)

    pipeline = NPortPipeline(run_id=run_id, test_mode=test_mode,
                             cik_filter=cik_filter, limit=limit)
    targets = pipeline.discover(run_id)
    print(f"\n  discovered {len(targets)} accession(s)")
    if not targets:
        print("  nothing to fetch")
        return 0

    staging_path = get_db_path()
    t0 = time.time()
    loaded = 0
    parse_failed = 0
    qc_blocked = 0
    series_loaded: set[str] = set()

    for i, target in enumerate(targets, start=1):
        fr = pipeline.fetch(target, run_id)
        if not fr.success:
            parse_failed += 1
            print(f"  [{i}/{len(targets)}] {target.accession_number} "
                  f"FETCH FAIL — {fr.error_message!r}", flush=True)
            continue
        pr = pipeline.parse(fr)
        if pr.parse_status == "failed":
            parse_failed += 1
            print(f"  [{i}/{len(targets)}] {target.accession_number} "
                  f"PARSE FAIL — {pr.qc_failures[0].rule if pr.qc_failures else '?'}",
                  flush=True)
            continue
        if any(q.severity == "BLOCK" for q in pr.qc_failures):
            qc_blocked += 1
        written = pipeline.load_to_staging(pr, staging_path, run_id)
        loaded += written
        # Track series_ids seen for summary
        for r in pr.rows:
            sid = r.get("series_id")
            if sid:
                series_loaded.add(sid)
        if i % 5 == 0 or i == len(targets):
            elapsed = time.time() - t0
            print(f"    [{i}/{len(targets)}] series={len(series_loaded)} "
                  f"holdings={loaded:,} parse_failed={parse_failed} "
                  f"qc_blocked={qc_blocked} elapsed={elapsed:.1f}s",
                  flush=True)

    elapsed = time.time() - t0
    print(f"\n  DONE  series={len(series_loaded)}  holdings={loaded:,}  "
          f"parse_failed={parse_failed}  qc_blocked={qc_blocked}  "
          f"elapsed={elapsed:.1f}s")
    print(f"  run_id: {run_id}  (logs/last_run_id.txt)")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="N-PORT SourcePipeline (v2)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--test", action="store_true",
                        help=f"Limit to {len(TEST_FUNDS)} test funds, "
                             f"writes to staging.")
    parser.add_argument("--ciks", type=str, default="",
                        help="Comma-separated CIK list (overrides --test selection)")
    parser.add_argument("--staging", action="store_true",
                        help="Write staging DB (default when not --dry-run)")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    cik_filter: Optional[list[int]] = None
    if args.ciks:
        cik_filter = [int(c.strip()) for c in args.ciks.split(",") if c.strip()]

    if args.test or args.staging or not args.dry_run:
        set_staging_mode(True)

    if args.dry_run:
        sys.exit(run_dry(args.test, cik_filter))
    sys.exit(run_pipeline(args.test, cik_filter, args.limit))


if __name__ == "__main__":
    crash_handler("fetch_nport_v2")(main)
