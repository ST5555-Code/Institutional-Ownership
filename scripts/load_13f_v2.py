#!/usr/bin/env python3
"""load_13f_v2.py — first SourcePipeline subclass (p2-05).

Combines fetch_13f.py (EDGAR bulk ZIP download + TSV extraction) and
load_13f.py (raw TSV → typed rows) into a single pipeline with
amendment_strategy = 'append_is_latest' on holdings_v2.

Scope: ``{"quarter": "2025Q4"}``. One quarterly bulk ZIP per run.

Amendment handling (owned by the base class):
  * On first load for a (cik, quarter) no prior rows exist; pure inserts.
  * On a subsequent load where a 13F-HR/A bumps the latest accession,
    prior rows for that (cik, quarter) flip to is_latest=FALSE and the
    new amendment's rows insert as is_latest=TRUE.

Reference tables — filings / filings_deduped / other_managers — are
handled separately in an override of promote(): INSERT new rows (dedup
on accession_number), rebuild filings_deduped from filings. They are
NOT fact tables, so they have no is_latest and are not recorded as
ingestion_impacts (rollback handles holdings_v2 only).

Absorbs deferred mig-12.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import zipfile
from typing import Any, Optional

import duckdb
import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

from config import QUARTER_URLS, SEC_HEADERS  # noqa: E402
from db import crash_handler  # noqa: E402
from pipeline.base import (  # noqa: E402
    FetchResult, ParseResult, PromoteResult, SourcePipeline,
    ValidationResult,
)
from pipeline.cadence import PIPELINE_CADENCE  # noqa: E402
from pipeline.shared import entity_gate_check  # noqa: E402


RAW_DIR = os.path.join(BASE_DIR, "data", "raw")
EXTRACT_DIR = os.path.join(BASE_DIR, "data", "extracted")


# ---------------------------------------------------------------------------
# Staging DDL
# ---------------------------------------------------------------------------

_STG_RAW_SUBMISSIONS_DDL = """
CREATE TABLE IF NOT EXISTS stg_13f_submissions (
    accession_number   VARCHAR,
    filing_date        VARCHAR,
    submission_type    VARCHAR,
    cik                VARCHAR,
    period_of_report   VARCHAR,
    quarter            VARCHAR
)
"""

_STG_RAW_INFOTABLE_DDL = """
CREATE TABLE IF NOT EXISTS stg_13f_infotable (
    accession_number   VARCHAR,
    issuer_name        VARCHAR,
    title_of_class     VARCHAR,
    cusip              VARCHAR,
    figi               VARCHAR,
    value              BIGINT,
    shares             BIGINT,
    shares_type        VARCHAR,
    put_call           VARCHAR,
    discretion         VARCHAR,
    other_manager      VARCHAR,
    vote_sole          BIGINT,
    vote_shared        BIGINT,
    vote_none          BIGINT,
    quarter            VARCHAR
)
"""

_STG_RAW_COVERPAGE_DDL = """
CREATE TABLE IF NOT EXISTS stg_13f_coverpage (
    accession_number        VARCHAR,
    report_calendar         VARCHAR,
    is_amendment            VARCHAR,
    amendment_no            VARCHAR,
    filing_manager_name     VARCHAR,
    filing_manager_city     VARCHAR,
    filing_manager_state    VARCHAR,
    crd_number              VARCHAR,
    sec_file_number         VARCHAR,
    quarter                 VARCHAR
)
"""

_STG_RAW_OTHERMANAGER_DDL = """
CREATE TABLE IF NOT EXISTS stg_13f_othermanager (
    accession_number      VARCHAR,
    sequence_number       VARCHAR,
    other_cik             VARCHAR,
    form13f_file_number   VARCHAR,
    crd_number            VARCHAR,
    sec_file_number       VARCHAR,
    name                  VARCHAR,
    quarter               VARCHAR
)
"""

# Typed staging for holdings_v2. Column list and types mirror the prod
# table exactly so _read_staged_rows()/INSERT SELECT * alignment holds.
# row_id is omitted — prod has a DEFAULT sequence that assigns it.
_STG_HOLDINGS_V2_DDL = """
CREATE TABLE IF NOT EXISTS holdings_v2 (
    accession_number        VARCHAR,
    cik                     VARCHAR,
    manager_name            VARCHAR,
    inst_parent_name        VARCHAR,
    quarter                 VARCHAR,
    report_date             VARCHAR,
    cusip                   VARCHAR,
    ticker                  VARCHAR,
    issuer_name             VARCHAR,
    market_value_usd        BIGINT,
    shares                  BIGINT,
    pct_of_portfolio        DOUBLE,
    pct_of_so               DOUBLE,
    manager_type            VARCHAR,
    is_passive              BOOLEAN,
    is_activist             BOOLEAN,
    discretion              VARCHAR,
    vote_sole               BIGINT,
    vote_shared             BIGINT,
    vote_none               BIGINT,
    put_call                VARCHAR,
    market_value_live       DOUBLE,
    security_type_inferred  VARCHAR,
    fund_name               VARCHAR,
    classification_source   VARCHAR,
    entity_id               BIGINT,
    rollup_entity_id        BIGINT,
    rollup_name             VARCHAR,
    entity_type             VARCHAR,
    dm_rollup_entity_id     BIGINT,
    dm_rollup_name          VARCHAR,
    pct_of_so_source        VARCHAR,
    is_latest               BOOLEAN,
    loaded_at               TIMESTAMP,
    backfill_quality        VARCHAR
)
"""

_STG_FILINGS_DDL = """
CREATE TABLE IF NOT EXISTS stg_13f_filings (
    accession_number   VARCHAR,
    cik                VARCHAR,
    manager_name       VARCHAR,
    crd_number         VARCHAR,
    quarter            VARCHAR,
    report_date        VARCHAR,
    filing_type        VARCHAR,
    amended            BOOLEAN,
    filed_date         VARCHAR
)
"""

_STG_FILINGS_DEDUPED_DDL = """
CREATE TABLE IF NOT EXISTS stg_13f_filings_deduped (
    accession_number   VARCHAR,
    cik                VARCHAR,
    manager_name       VARCHAR,
    crd_number         VARCHAR,
    quarter            VARCHAR,
    report_date        VARCHAR,
    filing_type        VARCHAR,
    amended            BOOLEAN,
    filed_date         VARCHAR
)
"""

_STG_OTHER_MANAGERS_DDL = """
CREATE TABLE IF NOT EXISTS stg_13f_other_managers (
    accession_number       VARCHAR,
    sequence_number        VARCHAR,
    other_cik              VARCHAR,
    form13f_file_number    VARCHAR,
    crd_number             VARCHAR,
    sec_file_number        VARCHAR,
    name                   VARCHAR,
    quarter                VARCHAR
)
"""


_TARGET_TABLE_COLUMNS: list[tuple[str, str]] = [
    ("accession_number", "VARCHAR"),
    ("cik", "VARCHAR"),
    ("manager_name", "VARCHAR"),
    ("inst_parent_name", "VARCHAR"),
    ("quarter", "VARCHAR"),
    ("report_date", "VARCHAR"),
    ("cusip", "VARCHAR"),
    ("ticker", "VARCHAR"),
    ("issuer_name", "VARCHAR"),
    ("market_value_usd", "BIGINT"),
    ("shares", "BIGINT"),
    ("pct_of_portfolio", "DOUBLE"),
    ("pct_of_so", "DOUBLE"),
    ("manager_type", "VARCHAR"),
    ("is_passive", "BOOLEAN"),
    ("is_activist", "BOOLEAN"),
    ("discretion", "VARCHAR"),
    ("vote_sole", "BIGINT"),
    ("vote_shared", "BIGINT"),
    ("vote_none", "BIGINT"),
    ("put_call", "VARCHAR"),
    ("market_value_live", "DOUBLE"),
    ("security_type_inferred", "VARCHAR"),
    ("fund_name", "VARCHAR"),
    ("classification_source", "VARCHAR"),
    ("entity_id", "BIGINT"),
    ("rollup_entity_id", "BIGINT"),
    ("rollup_name", "VARCHAR"),
    ("entity_type", "VARCHAR"),
    ("dm_rollup_entity_id", "BIGINT"),
    ("dm_rollup_name", "VARCHAR"),
    ("pct_of_so_source", "VARCHAR"),
    ("is_latest", "BOOLEAN"),
    ("loaded_at", "TIMESTAMP"),
    ("backfill_quality", "VARCHAR"),
]


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

class Load13FPipeline(SourcePipeline):
    """SourcePipeline for 13F quarterly bulk TSV ZIPs.

    scope = {"quarter": "YYYYQN"}. The pipeline downloads the bulk ZIP
    from the URL in ``config.QUARTER_URLS``, extracts it, and parses
    raw TSVs into stg_holdings_v2 plus the reference tables.
    """

    name = "13f_holdings"
    target_table = "holdings_v2"
    amendment_strategy = "append_is_latest"
    amendment_key = ("cik", "quarter")

    def __init__(self, *, skip_fetch: bool = False, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._skip_fetch = skip_fetch

    # ---- target_table_spec --------------------------------------------

    def target_table_spec(self) -> dict:
        return {
            "columns": list(_TARGET_TABLE_COLUMNS),
            "pk": ["accession_number", "cusip", "is_latest"],
            "indexes": [
                ["cik", "quarter"],
                ["cusip"],
                ["quarter"],
            ],
        }

    # ---- fetch ---------------------------------------------------------

    def fetch(self, scope: dict, staging_con: Any) -> FetchResult:
        t0 = time.monotonic()
        quarter = scope["quarter"]
        if quarter not in QUARTER_URLS:
            raise ValueError(
                f"unknown quarter {quarter!r}; edit config.QUARTER_URLS"
            )
        url = QUARTER_URLS[quarter]

        os.makedirs(RAW_DIR, exist_ok=True)
        os.makedirs(EXTRACT_DIR, exist_ok=True)

        zip_path = os.path.join(RAW_DIR, f"{quarter}_form13f.zip")
        extract_to = os.path.join(EXTRACT_DIR, quarter)
        os.makedirs(extract_to, exist_ok=True)

        # 1. Download (skip if cached or --skip-fetch)
        if not self._skip_fetch:
            self._download_zip(url, zip_path, quarter)

        # 2. Extract (skip if already extracted)
        self._extract_zip(zip_path, extract_to, quarter)

        # 3. Raw staging load — drop+create, then copy TSVs in
        for ddl in (
            _STG_RAW_SUBMISSIONS_DDL,
            _STG_RAW_INFOTABLE_DDL,
            _STG_RAW_COVERPAGE_DDL,
            _STG_RAW_OTHERMANAGER_DDL,
        ):
            staging_con.execute(ddl)
        for tbl in (
            "stg_13f_submissions", "stg_13f_infotable",
            "stg_13f_coverpage", "stg_13f_othermanager",
        ):
            staging_con.execute(
                f"DELETE FROM {tbl} WHERE quarter = ?", [quarter]
            )

        sub_path = os.path.join(extract_to, "SUBMISSION.tsv")
        info_path = os.path.join(extract_to, "INFOTABLE.tsv")
        cover_path = os.path.join(extract_to, "COVERPAGE.tsv")
        om2_path = os.path.join(extract_to, "OTHERMANAGER2.tsv")
        for p in (sub_path, info_path, cover_path, om2_path):
            if not os.path.exists(p):
                raise FileNotFoundError(
                    f"missing required 13F TSV for {quarter}: {p}"
                )

        staging_con.execute(
            "INSERT INTO stg_13f_submissions SELECT "
            "ACCESSION_NUMBER, FILING_DATE, SUBMISSIONTYPE, "
            "CAST(CIK AS VARCHAR) AS CIK, PERIODOFREPORT, ? AS quarter "
            "FROM read_csv_auto(?, delim='\t', header=true, "
            "all_varchar=true, ignore_errors=true)",
            [quarter, sub_path],
        )
        staging_con.execute("CHECKPOINT")

        staging_con.execute(
            "INSERT INTO stg_13f_infotable SELECT "
            "ACCESSION_NUMBER, NAMEOFISSUER, TITLEOFCLASS, CUSIP, FIGI, "
            "CAST(VALUE AS BIGINT), CAST(SSHPRNAMT AS BIGINT), "
            "SSHPRNAMTTYPE, PUTCALL, INVESTMENTDISCRETION, OTHERMANAGER, "
            "CAST(VOTING_AUTH_SOLE AS BIGINT), "
            "CAST(VOTING_AUTH_SHARED AS BIGINT), "
            "CAST(VOTING_AUTH_NONE AS BIGINT), ? AS quarter "
            "FROM read_csv_auto(?, delim='\t', header=true, "
            "all_varchar=true, ignore_errors=true)",
            [quarter, info_path],
        )
        staging_con.execute("CHECKPOINT")

        staging_con.execute(
            "INSERT INTO stg_13f_coverpage SELECT "
            "ACCESSION_NUMBER, REPORTCALENDARORQUARTER, ISAMENDMENT, "
            "AMENDMENTNO, FILINGMANAGER_NAME, FILINGMANAGER_CITY, "
            "FILINGMANAGER_STATEORCOUNTRY, CRDNUMBER, SECFILENUMBER, "
            "? AS quarter "
            "FROM read_csv_auto(?, delim='\t', header=true, "
            "all_varchar=true, ignore_errors=true)",
            [quarter, cover_path],
        )
        staging_con.execute("CHECKPOINT")

        staging_con.execute(
            "INSERT INTO stg_13f_othermanager SELECT "
            "ACCESSION_NUMBER, SEQUENCENUMBER, CIK, FORM13FFILENUMBER, "
            "CRDNUMBER, SECFILENUMBER, NAME, ? AS quarter "
            "FROM read_csv_auto(?, delim='\t', header=true, "
            "all_varchar=true, ignore_errors=true)",
            [quarter, om2_path],
        )
        staging_con.execute("CHECKPOINT")

        rows_staged = staging_con.execute(
            "SELECT COUNT(*) FROM stg_13f_infotable WHERE quarter = ?",
            [quarter],
        ).fetchone()[0]

        return FetchResult(
            run_id="",
            rows_staged=int(rows_staged),
            raw_tables=[
                "stg_13f_submissions", "stg_13f_infotable",
                "stg_13f_coverpage", "stg_13f_othermanager",
            ],
            duration_seconds=time.monotonic() - t0,
        )

    def _download_zip(self, url: str, zip_path: str, quarter: str) -> None:
        if os.path.exists(zip_path) and os.path.getsize(zip_path) > 1000:
            print(f"  {quarter}: cached ({os.path.getsize(zip_path) / 1_000_000:.1f} MB)",
                  flush=True)
            return
        print(f"  {quarter}: downloading {url}", flush=True)
        r = requests.get(url, headers=SEC_HEADERS, timeout=300, stream=True)
        r.raise_for_status()
        with open(zip_path, "wb") as fh:
            for chunk in r.iter_content(chunk_size=1_000_000):
                fh.write(chunk)
        print(f"  {quarter}: downloaded {os.path.getsize(zip_path) / 1_000_000:.1f} MB",
              flush=True)

    def _extract_zip(self, zip_path: str, extract_to: str, quarter: str) -> None:
        existing = [f for f in os.listdir(extract_to) if f.upper().endswith(".TSV")]
        if len(existing) >= 4:
            print(f"  {quarter}: extracted ({len(existing)} TSVs cached)", flush=True)
            return
        z = zipfile.ZipFile(zip_path)
        try:
            bad = z.testzip()
            if bad:
                raise zipfile.BadZipFile(f"corrupt member in ZIP: {bad}")
            z.extractall(extract_to)
        finally:
            z.close()
        print(f"  {quarter}: extracted {len(os.listdir(extract_to))} files",
              flush=True)

    # ---- parse ---------------------------------------------------------

    def parse(self, staging_con: Any) -> ParseResult:
        t0 = time.monotonic()

        # 1. Reference tables in staging: filings + filings_deduped + other_managers
        staging_con.execute(_STG_FILINGS_DDL)
        staging_con.execute(_STG_FILINGS_DEDUPED_DDL)
        staging_con.execute(_STG_OTHER_MANAGERS_DDL)
        for t in ("stg_13f_filings", "stg_13f_filings_deduped",
                  "stg_13f_other_managers"):
            staging_con.execute(f"DELETE FROM {t}")

        staging_con.execute(
            """
            INSERT INTO stg_13f_filings
            SELECT
                s.accession_number,
                LPAD(s.cik, 10, '0') AS cik,
                c.filing_manager_name AS manager_name,
                c.crd_number,
                s.quarter,
                s.period_of_report AS report_date,
                s.submission_type AS filing_type,
                CASE WHEN s.submission_type LIKE '%/A' THEN TRUE ELSE FALSE END
                    AS amended,
                s.filing_date AS filed_date
            FROM stg_13f_submissions s
            LEFT JOIN stg_13f_coverpage c
                ON s.accession_number = c.accession_number
            """
        )
        staging_con.execute("CHECKPOINT")

        staging_con.execute(
            """
            INSERT INTO stg_13f_filings_deduped
            WITH ranked AS (
                SELECT *,
                    ROW_NUMBER() OVER (
                        PARTITION BY cik, quarter
                        ORDER BY amended DESC, filed_date DESC
                    ) AS rn
                FROM stg_13f_filings
            )
            SELECT accession_number, cik, manager_name, crd_number, quarter,
                   report_date, filing_type, amended, filed_date
            FROM ranked WHERE rn = 1
            """
        )
        staging_con.execute("CHECKPOINT")

        staging_con.execute(
            """
            INSERT INTO stg_13f_other_managers
            SELECT accession_number, sequence_number, other_cik,
                   form13f_file_number, crd_number, sec_file_number,
                   name, quarter
            FROM stg_13f_othermanager
            """
        )
        staging_con.execute("CHECKPOINT")

        # 2. Typed target staging — stg holdings_v2 in staging DB.
        # Only the LATEST amendment's rows for each (cik, quarter) are
        # staged (join against stg_13f_filings_deduped). This matches
        # the amendment_key (cik, quarter) — base class will flip any
        # prior prod rows for that key to is_latest=FALSE and INSERT
        # these as is_latest=TRUE.
        staging_con.execute("DROP TABLE IF EXISTS holdings_v2")
        staging_con.execute(_STG_HOLDINGS_V2_DDL)

        staging_con.execute(
            """
            INSERT INTO holdings_v2 (
                accession_number, cik, manager_name,
                inst_parent_name, quarter, report_date, cusip, ticker,
                issuer_name, market_value_usd, shares,
                pct_of_portfolio, pct_of_so, manager_type, is_passive,
                is_activist, discretion, vote_sole, vote_shared,
                vote_none, put_call, market_value_live,
                security_type_inferred, fund_name, classification_source,
                entity_id, rollup_entity_id, rollup_name, entity_type,
                dm_rollup_entity_id, dm_rollup_name, pct_of_so_source,
                is_latest, loaded_at, backfill_quality
            )
            SELECT
                i.accession_number,
                fd.cik,
                fd.manager_name,
                NULL AS inst_parent_name,
                i.quarter,
                fd.report_date,
                i.cusip,
                NULL AS ticker,
                i.issuer_name,
                -- SEC reports value in $1000s; promote to dollars.
                CAST(i.value * 1000 AS BIGINT) AS market_value_usd,
                i.shares,
                -- pct_of_portfolio = per-row value / accession total
                CAST(i.value AS DOUBLE)
                    / NULLIF(SUM(i.value) OVER (
                        PARTITION BY i.accession_number), 0)
                    AS pct_of_portfolio,
                NULL AS pct_of_so,
                NULL AS manager_type,
                NULL AS is_passive,
                NULL AS is_activist,
                i.discretion,
                i.vote_sole,
                i.vote_shared,
                i.vote_none,
                i.put_call,
                NULL AS market_value_live,
                NULL AS security_type_inferred,
                NULL AS fund_name,
                NULL AS classification_source,
                NULL AS entity_id,
                NULL AS rollup_entity_id,
                NULL AS rollup_name,
                NULL AS entity_type,
                NULL AS dm_rollup_entity_id,
                NULL AS dm_rollup_name,
                NULL AS pct_of_so_source,
                TRUE AS is_latest,
                NOW() AS loaded_at,
                'direct' AS backfill_quality
            FROM stg_13f_infotable i
            JOIN stg_13f_filings_deduped fd
                ON i.accession_number = fd.accession_number
            """
        )
        staging_con.execute("CHECKPOINT")

        rows_parsed = staging_con.execute(
            "SELECT COUNT(*) FROM holdings_v2"
        ).fetchone()[0]

        qc_failures: list[dict] = []
        if rows_parsed == 0:
            qc_failures.append({
                "field": "_",
                "rule": "zero_rows_parsed",
                "severity": "BLOCK",
            })
        filings_count = staging_con.execute(
            "SELECT COUNT(*) FROM stg_13f_filings_deduped"
        ).fetchone()[0]
        if filings_count == 0:
            qc_failures.append({
                "field": "_",
                "rule": "zero_filings",
                "severity": "BLOCK",
            })
        # FLAG: any filer with zero holdings rows
        orphan_filers = staging_con.execute(
            """
            SELECT COUNT(*) FROM stg_13f_filings_deduped fd
             WHERE NOT EXISTS (
                   SELECT 1 FROM holdings_v2 h
                    WHERE h.accession_number = fd.accession_number
             )
            """
        ).fetchone()[0]
        if orphan_filers:
            qc_failures.append({
                "field": "filings_deduped",
                "rule": f"{orphan_filers}_filers_with_zero_holdings",
                "severity": "FLAG",
            })

        return ParseResult(
            run_id="",
            rows_parsed=int(rows_parsed),
            target_staging_table=self.target_table,
            qc_failures=qc_failures,
            duration_seconds=time.monotonic() - t0,
        )

    # ---- validate ------------------------------------------------------

    def validate(self, staging_con: Any, prod_con: Any) -> ValidationResult:
        vr = ValidationResult()

        staged = staging_con.execute(
            "SELECT COUNT(*) FROM holdings_v2"
        ).fetchone()[0]
        if staged == 0:
            vr.blocks.append("zero_rows_parsed")
            return vr

        # min_rows / max_rows range check
        ranges = PIPELINE_CADENCE[self.name].get("expected_delta", {})
        min_rows = ranges.get("min_rows")
        max_rows = ranges.get("max_rows")
        if min_rows is not None and staged < min_rows:
            vr.warns.append(f"row_count={staged} below min_rows={min_rows}")
        if max_rows is not None and staged > max_rows:
            vr.warns.append(f"row_count={staged} above max_rows={max_rows}")

        # Entity gate — collect distinct filer CIKs and check against MDM.
        ciks = [
            r[0] for r in staging_con.execute(
                "SELECT DISTINCT cik FROM holdings_v2 WHERE cik IS NOT NULL"
            ).fetchall()
        ]
        if ciks:
            gate = entity_gate_check(
                prod_con,
                source_type=self.name,
                identifier_type="cik",
                staged_identifiers=ciks,
                rollup_types=["economic_control_v1", "decision_maker_v1"],
                requires_classification=False,
            )
            if gate.new_entities_pending:
                vr.pending_entities.extend(gate.new_entities_pending)
                max_new = ranges.get("max_new_pending")
                if max_new is not None and len(gate.new_entities_pending) > max_new:
                    vr.flags.append(
                        f"pending_entities={len(gate.new_entities_pending)} "
                        f"above max_new_pending={max_new}"
                    )
        return vr

    # ---- promote (override for reference tables) -----------------------

    def promote(self, run_id: str, prod_con: Any) -> PromoteResult:
        """Delegate holdings_v2 promote to the base class, then handle
        the three reference tables (filings, filings_deduped,
        other_managers) in the same prod connection / transaction."""
        result = super().promote(run_id, prod_con)
        self._promote_reference_tables(prod_con)
        return result

    def _promote_reference_tables(self, prod_con: Any) -> None:
        """INSERT new reference rows + rebuild filings_deduped.

        filings / other_managers: dedupe by primary natural key so
        re-runs and amendments do not create duplicates. filings_deduped
        is a full CTAS rebuild from filings — cheap at this scale.
        """
        staging_con = duckdb.connect(self._staging_db_path, read_only=True)
        try:
            try:
                filings_df = staging_con.execute(
                    "SELECT * FROM stg_13f_filings"
                ).fetchdf()
            except Exception:
                filings_df = None
            try:
                other_df = staging_con.execute(
                    "SELECT * FROM stg_13f_other_managers"
                ).fetchdf()
            except Exception:
                other_df = None
        finally:
            staging_con.close()

        if filings_df is not None and not filings_df.empty:
            prod_con.register("stg_filings_df", filings_df)
            try:
                prod_con.execute(
                    """
                    INSERT INTO filings
                    SELECT * FROM stg_filings_df s
                     WHERE NOT EXISTS (
                         SELECT 1 FROM filings f
                          WHERE f.accession_number = s.accession_number
                     )
                    """
                )
            finally:
                prod_con.unregister("stg_filings_df")

            # Rebuild filings_deduped from filings (latest amendment per cik+quarter)
            prod_con.execute("DROP TABLE IF EXISTS filings_deduped")
            prod_con.execute(
                """
                CREATE TABLE filings_deduped AS
                WITH ranked AS (
                    SELECT *,
                        ROW_NUMBER() OVER (
                            PARTITION BY cik, quarter
                            ORDER BY amended DESC, filed_date DESC
                        ) AS rn
                    FROM filings
                )
                SELECT * EXCLUDE(rn) FROM ranked WHERE rn = 1
                """
            )

        if other_df is not None and not other_df.empty:
            prod_con.register("stg_other_df", other_df)
            try:
                prod_con.execute(
                    """
                    INSERT INTO other_managers
                    SELECT * FROM stg_other_df s
                     WHERE NOT EXISTS (
                         SELECT 1 FROM other_managers o
                          WHERE o.accession_number = s.accession_number
                            AND COALESCE(o.sequence_number, '') =
                                COALESCE(s.sequence_number, '')
                     )
                    """
                )
            finally:
                prod_con.unregister("stg_other_df")

    # ---- cleanup override (drop reference staging too) ------------------

    def _cleanup_staging(self, run_id: str) -> None:
        super()._cleanup_staging(run_id)
        try:
            staging_con = duckdb.connect(self._staging_db_path)
            try:
                for t in (
                    "stg_13f_submissions", "stg_13f_infotable",
                    "stg_13f_coverpage", "stg_13f_othermanager",
                    "stg_13f_filings", "stg_13f_filings_deduped",
                    "stg_13f_other_managers",
                ):
                    staging_con.execute(f"DROP TABLE IF EXISTS {t}")
                staging_con.execute("CHECKPOINT")
            finally:
                staging_con.close()
        except Exception as e:
            self._logger.warning("cleanup 13F staging: %s", e)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli_main() -> None:
    parser = argparse.ArgumentParser(
        description="13F SourcePipeline (p2-05)",
    )
    parser.add_argument(
        "--quarter", required=True,
        help=f"Quarter label, e.g. one of {sorted(QUARTER_URLS)}",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Run fetch + parse + validate, halt at pending_approval")
    parser.add_argument("--staging", action="store_true",
                        help="Use staging DB as prod target")
    parser.add_argument("--keep-staging", action="store_true",
                        help="Retain staging tables after promote")
    parser.add_argument("--skip-fetch", action="store_true",
                        help="Skip download, use existing extracted TSVs")
    parser.add_argument("--auto-approve", action="store_true",
                        help="Promote after run() succeeds (terminal mode)")
    args = parser.parse_args()

    prod_path: Optional[str] = None
    if args.staging:
        from db import STAGING_DB  # noqa: WPS433
        prod_path = STAGING_DB

    pipeline = Load13FPipeline(
        skip_fetch=args.skip_fetch,
        prod_db_path=prod_path,
    )
    scope = {"quarter": args.quarter}

    run_id = pipeline.run(scope)
    print(f"run_id: {run_id}")

    if args.dry_run:
        print(f"Dry run complete. Review diff, then call "
              f"approve_and_promote({run_id!r}).")
        return

    if args.auto_approve:
        result = pipeline.approve_and_promote(run_id)
        print(
            f"Promoted run_id={run_id}: "
            f"inserted={result.rows_inserted} flipped={result.rows_flipped} "
            f"upserted={result.rows_upserted}"
        )
        if not args.keep_staging:
            return
        # keep-staging: base class already cleaned; warn the user explicitly.
        print("--keep-staging: staging already cleaned by promote; "
              "use --dry-run next time to inspect before promote.")
    else:
        print(f"Run {run_id} ready for approval. Either call "
              f"approve_and_promote({run_id!r}) from the admin UI/REPL, "
              f"or re-run with --auto-approve.")


def main() -> None:
    _cli_main()


if __name__ == "__main__":
    crash_handler("load_13f_v2")(main)
