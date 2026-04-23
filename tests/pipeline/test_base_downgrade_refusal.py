"""Unit tests for int-23: downgrade-refusal invariant on ``_promote_append_is_latest``.

Replays the int-22 failure class (2026-04-22) and verifies the fix in
``scripts/pipeline/base.py``. See ``docs/findings/int-23-design.md`` for
the design and ``docs/findings/int-22-*`` for the incident history.

Scenarios covered:
  T1. int-22 replay — displaced ticker-enriched rows, staged all-NULL →
      DowngradeRefusalError, transaction rolled back, manifest failed.
  T2. Clean first load — empty prod, NULL-heavy staged → flip proceeds.
  T3. Mixed keys — any offender fails the whole run (no partial commit).
  T4. Column existence guard — sensitive columns absent from target → no-op.
  T5. Non-``append_is_latest`` strategies — check not invoked.
  T6. Manifest error_message carries structured JSON payload.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import duckdb
import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from pipeline.base import (  # noqa: E402
    DowngradeRefusalError,
    FetchResult,
    ParseResult,
    SourcePipeline,
)


# ---------------------------------------------------------------------------
# Control-plane DDL (subset of migration 001)
# ---------------------------------------------------------------------------

DDL_MANIFEST = """
CREATE TABLE ingestion_manifest (
    manifest_id              BIGINT PRIMARY KEY,
    source_type              VARCHAR NOT NULL,
    object_type              VARCHAR NOT NULL,
    object_key               VARCHAR NOT NULL UNIQUE,
    source_url               VARCHAR,
    accession_number         VARCHAR,
    run_id                   VARCHAR NOT NULL,
    fetch_status             VARCHAR NOT NULL DEFAULT 'pending',
    error_message            VARCHAR,
    superseded_by_manifest_id BIGINT,
    is_amendment             BOOLEAN DEFAULT FALSE,
    retry_count              INTEGER DEFAULT 0
)
"""

DDL_IMPACTS = """
CREATE TABLE ingestion_impacts (
    impact_id       BIGINT PRIMARY KEY,
    manifest_id     BIGINT NOT NULL,
    target_table    VARCHAR NOT NULL,
    unit_type       VARCHAR NOT NULL,
    unit_key_json   VARCHAR NOT NULL,
    report_date     DATE,
    rows_staged     INTEGER DEFAULT 0,
    load_status     VARCHAR DEFAULT 'pending',
    validation_tier VARCHAR,
    promote_status  VARCHAR DEFAULT 'pending'
)
"""

DDL_FRESHNESS = """
CREATE TABLE data_freshness (
    table_name       VARCHAR PRIMARY KEY,
    last_computed_at TIMESTAMP,
    row_count        BIGINT
)
"""

# Target table mirrors the int-22 scenario: ticker column present, plus
# entity_id/rollup_entity_id so the existence guard is exercised on all
# three sensitive columns.
DDL_HOLDINGS = """
CREATE TABLE holdings_v2_like (
    cik              INTEGER,
    quarter          VARCHAR,
    accession_number VARCHAR,
    cusip            VARCHAR,
    ticker           VARCHAR,
    entity_id        BIGINT,
    rollup_entity_id BIGINT,
    shares           BIGINT,
    is_latest        BOOLEAN
)
"""

# Target table with NO sensitive columns — exercises the existence guard.
DDL_UNSENSITIVE = """
CREATE TABLE ncen_fund_series (
    cik              INTEGER,
    fiscal_year      VARCHAR,
    accession_number VARCHAR,
    shares           BIGINT,
    is_latest        BOOLEAN
)
"""


def _init_prod_db(path: str, *, ddl_target: str = DDL_HOLDINGS) -> None:
    con = duckdb.connect(path)
    try:
        con.execute(DDL_MANIFEST)
        con.execute(DDL_IMPACTS)
        con.execute(DDL_FRESHNESS)
        con.execute(ddl_target)
        con.execute("CHECKPOINT")
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Pipelines
# ---------------------------------------------------------------------------

class HoldingsPipeline(SourcePipeline):
    """append_is_latest against a holdings-shaped target with ticker."""

    name = "holdings_test"
    target_table = "holdings_v2_like"
    amendment_strategy = "append_is_latest"
    amendment_key = ("cik", "quarter")

    def __init__(self, *, staged_rows=None, **kw):
        super().__init__(**kw)
        self._staged_rows = staged_rows or []

    def fetch(self, scope, staging_con):
        staging_con.execute("DROP TABLE IF EXISTS holdings_v2_like")
        staging_con.execute(DDL_HOLDINGS)
        for row in self._staged_rows:
            staging_con.execute(
                "INSERT INTO holdings_v2_like "
                "(cik, quarter, accession_number, cusip, ticker, "
                " entity_id, rollup_entity_id, shares, is_latest) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    row.get("cik"), row.get("quarter"),
                    row.get("accession_number"), row.get("cusip"),
                    row.get("ticker"), row.get("entity_id"),
                    row.get("rollup_entity_id"), row.get("shares"),
                    row.get("is_latest", True),
                ],
            )
        return FetchResult(run_id="", rows_staged=len(self._staged_rows))

    def parse(self, staging_con):
        return ParseResult(
            run_id="", rows_parsed=len(self._staged_rows),
            target_staging_table="holdings_v2_like",
        )

    def target_table_spec(self):
        return {"columns": [], "pk": [], "indexes": []}


class UnsensitivePipeline(HoldingsPipeline):
    """append_is_latest against a target with NO sensitive columns."""

    target_table = "ncen_fund_series"
    amendment_key = ("cik", "fiscal_year")

    def fetch(self, scope, staging_con):
        staging_con.execute("DROP TABLE IF EXISTS ncen_fund_series")
        staging_con.execute(DDL_UNSENSITIVE)
        for row in self._staged_rows:
            staging_con.execute(
                "INSERT INTO ncen_fund_series "
                "(cik, fiscal_year, accession_number, shares, is_latest) "
                "VALUES (?, ?, ?, ?, ?)",
                [
                    row.get("cik"), row.get("fiscal_year"),
                    row.get("accession_number"), row.get("shares"),
                    row.get("is_latest", True),
                ],
            )
        return FetchResult(run_id="", rows_staged=len(self._staged_rows))


class SCDPipeline(HoldingsPipeline):
    """scd_type2 variant — downgrade check must NOT fire."""

    amendment_strategy = "scd_type2"
    target_table = "scd_table"

    def fetch(self, scope, staging_con):
        staging_con.execute("DROP TABLE IF EXISTS scd_table")
        staging_con.execute(
            """
            CREATE TABLE scd_table (
                cik              INTEGER,
                quarter          VARCHAR,
                accession_number VARCHAR,
                ticker           VARCHAR,
                shares           BIGINT,
                valid_to         DATE
            )
            """
        )
        for row in self._staged_rows:
            staging_con.execute(
                "INSERT INTO scd_table "
                "(cik, quarter, accession_number, ticker, shares, valid_to) "
                "VALUES (?, ?, ?, ?, ?, DATE '9999-12-31')",
                [
                    row.get("cik"), row.get("quarter"),
                    row.get("accession_number"), row.get("ticker"),
                    row.get("shares"),
                ],
            )
        return FetchResult(run_id="", rows_staged=len(self._staged_rows))


class DirectWritePipeline(HoldingsPipeline):
    """direct_write variant — downgrade check must NOT fire."""

    amendment_strategy = "direct_write"
    target_table = "direct_table"

    def fetch(self, scope, staging_con):
        staging_con.execute("DROP TABLE IF EXISTS direct_table")
        staging_con.execute(
            """
            CREATE TABLE direct_table (
                cik              INTEGER,
                quarter          VARCHAR,
                accession_number VARCHAR,
                ticker           VARCHAR,
                shares           BIGINT
            )
            """
        )
        for row in self._staged_rows:
            staging_con.execute(
                "INSERT INTO direct_table "
                "(cik, quarter, accession_number, ticker, shares) "
                "VALUES (?, ?, ?, ?, ?)",
                [
                    row.get("cik"), row.get("quarter"),
                    row.get("accession_number"), row.get("ticker"),
                    row.get("shares"),
                ],
            )
        return FetchResult(run_id="", rows_staged=len(self._staged_rows))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_dbs(tmp_path):
    prod = tmp_path / "prod.duckdb"
    staging = tmp_path / "staging.duckdb"
    backup = tmp_path / "backups"
    backup.mkdir()
    _init_prod_db(str(prod), ddl_target=DDL_HOLDINGS)
    return {
        "prod": str(prod),
        "staging": str(staging),
        "backup": str(backup),
    }


def _seed_prod(prod_path: str, rows: list[dict]) -> None:
    con = duckdb.connect(prod_path)
    try:
        for row in rows:
            con.execute(
                "INSERT INTO holdings_v2_like "
                "(cik, quarter, accession_number, cusip, ticker, "
                " entity_id, rollup_entity_id, shares, is_latest) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    row.get("cik"), row.get("quarter"),
                    row.get("accession_number"), row.get("cusip"),
                    row.get("ticker"), row.get("entity_id"),
                    row.get("rollup_entity_id"), row.get("shares"),
                    row.get("is_latest", True),
                ],
            )
        con.execute("CHECKPOINT")
    finally:
        con.close()


def _manifest_row(prod_path: str, run_id: str):
    con = duckdb.connect(prod_path, read_only=True)
    try:
        return con.execute(
            "SELECT fetch_status, error_message FROM ingestion_manifest "
            "WHERE run_id = ?",
            [run_id],
        ).fetchone()
    finally:
        con.close()


def _prod_rows(prod_path: str, sql: str):
    con = duckdb.connect(prod_path, read_only=True)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


# ---------------------------------------------------------------------------
# T1 — int-22 replay
# ---------------------------------------------------------------------------

def test_int22_replay_downgrade_refused(tmp_dbs):
    """Displaced rows carry ticker='AAPL'; staged rows are all NULL.
    Promote must raise DowngradeRefusalError, roll back the flip, and
    leave prod untouched.
    """
    # Seed prod: 10 ticker-enriched rows for (cik=320193, quarter=2025Q4).
    _seed_prod(tmp_dbs["prod"], [
        {"cik": 320193, "quarter": "2025Q4", "accession_number": "A_OLD",
         "cusip": f"C{i:05d}", "ticker": "AAPL",
         "entity_id": 10, "rollup_entity_id": 10,
         "shares": 1000 + i, "is_latest": True}
        for i in range(10)
    ])

    staged = [
        # 12 new rows, same key, ticker=NULL — the int-22 pattern.
        {"cik": 320193, "quarter": "2025Q4", "accession_number": "A_NEW",
         "cusip": f"C{i:05d}", "ticker": None,
         "entity_id": 10, "rollup_entity_id": 10, "shares": 2000 + i}
        for i in range(12)
    ]

    pipeline = HoldingsPipeline(
        prod_db_path=tmp_dbs["prod"],
        staging_db_path=tmp_dbs["staging"],
        backup_dir=tmp_dbs["backup"],
        staged_rows=staged,
    )
    run_id = pipeline.run({"quarter": "2025Q4"})

    with pytest.raises(DowngradeRefusalError) as exc_info:
        pipeline.approve_and_promote(run_id)

    err = exc_info.value
    assert err.target_table == "holdings_v2_like"
    assert err.column_breakdown == {"ticker": 1}
    assert err.total_refused_keys == 1
    assert err.refusals[0][1] == "ticker"
    assert err.refusals[0][2] == 10  # displaced non-null count

    # Prod state untouched: 10 ticker='AAPL' rows, all is_latest=TRUE,
    # no NULL-ticker rows leaked through.
    latest = _prod_rows(
        tmp_dbs["prod"],
        "SELECT COUNT(*) FROM holdings_v2_like "
        "WHERE is_latest = TRUE AND ticker = 'AAPL'",
    )[0][0]
    assert latest == 10, "displaced rows must remain is_latest=TRUE"

    null_ticker = _prod_rows(
        tmp_dbs["prod"],
        "SELECT COUNT(*) FROM holdings_v2_like WHERE ticker IS NULL",
    )[0][0]
    assert null_ticker == 0, "new NULL-ticker rows must not have been inserted"

    # Manifest transitioned to failed with structured payload.
    status, err_msg = _manifest_row(tmp_dbs["prod"], run_id)
    assert status == "failed"
    assert err_msg is not None
    payload = json.loads(err_msg)
    assert payload["kind"] == "downgrade_refusal"
    assert payload["target_table"] == "holdings_v2_like"
    assert payload["total_refused_keys"] == 1
    assert payload["column_breakdown"] == {"ticker": 1}


# ---------------------------------------------------------------------------
# T2 — Clean first load with legitimate NULL columns
# ---------------------------------------------------------------------------

def test_clean_first_load_passes(tmp_dbs):
    """Empty prod, staged rows with ticker=NULL. No prior state to
    downgrade → promote succeeds."""
    staged = [
        {"cik": 100 + i, "quarter": "2026Q1",
         "accession_number": "A_FIRST",
         "cusip": f"C{i:05d}", "ticker": None,
         "entity_id": None, "rollup_entity_id": None,
         "shares": 500 + i}
        for i in range(8)
    ]
    pipeline = HoldingsPipeline(
        prod_db_path=tmp_dbs["prod"],
        staging_db_path=tmp_dbs["staging"],
        backup_dir=tmp_dbs["backup"],
        staged_rows=staged,
    )
    run_id = pipeline.run({"quarter": "2026Q1"})
    result = pipeline.approve_and_promote(run_id)

    assert result.rows_inserted == 8
    assert result.rows_flipped == 0

    status, _ = _manifest_row(tmp_dbs["prod"], run_id)
    assert status == "complete"

    latest_null = _prod_rows(
        tmp_dbs["prod"],
        "SELECT COUNT(*) FROM holdings_v2_like "
        "WHERE is_latest = TRUE AND ticker IS NULL",
    )[0][0]
    assert latest_null == 8


# ---------------------------------------------------------------------------
# T3 — Mixed keys: any offender fails the whole run
# ---------------------------------------------------------------------------

def test_mixed_keys_fail_whole_run(tmp_dbs):
    """Three keys: A (ticker='AAPL'), B (ticker='MSFT'), C (ticker=NULL
    in prod). Staged rows for all three are ticker=NULL. A+B would
    downgrade; C would not. Whole run fails and no rows are inserted
    or flipped.
    """
    _seed_prod(tmp_dbs["prod"], [
        # Key A: ticker populated
        {"cik": 1, "quarter": "2026Q1", "accession_number": "A_OLD",
         "cusip": "C00001", "ticker": "AAPL",
         "entity_id": None, "rollup_entity_id": None,
         "shares": 10, "is_latest": True},
        # Key B: ticker populated
        {"cik": 2, "quarter": "2026Q1", "accession_number": "A_OLD",
         "cusip": "C00002", "ticker": "MSFT",
         "entity_id": None, "rollup_entity_id": None,
         "shares": 20, "is_latest": True},
        # Key C: ticker NULL already (no downgrade)
        {"cik": 3, "quarter": "2026Q1", "accession_number": "A_OLD",
         "cusip": "C00003", "ticker": None,
         "entity_id": None, "rollup_entity_id": None,
         "shares": 30, "is_latest": True},
    ])

    staged = [
        {"cik": 1, "quarter": "2026Q1", "accession_number": "A_NEW",
         "cusip": "C00001", "ticker": None, "shares": 11},
        {"cik": 2, "quarter": "2026Q1", "accession_number": "A_NEW",
         "cusip": "C00002", "ticker": None, "shares": 21},
        {"cik": 3, "quarter": "2026Q1", "accession_number": "A_NEW",
         "cusip": "C00003", "ticker": None, "shares": 31},
    ]
    pipeline = HoldingsPipeline(
        prod_db_path=tmp_dbs["prod"],
        staging_db_path=tmp_dbs["staging"],
        backup_dir=tmp_dbs["backup"],
        staged_rows=staged,
    )
    run_id = pipeline.run({"quarter": "2026Q1"})

    with pytest.raises(DowngradeRefusalError) as exc_info:
        pipeline.approve_and_promote(run_id)

    err = exc_info.value
    assert err.total_refused_keys == 2, "only A and B should be refused"
    refused_keys = {
        (r[0]["cik"], r[0]["quarter"]) for r in err.refusals
    }
    assert refused_keys == {(1, "2026Q1"), (2, "2026Q1")}

    # No partial work: all three prod rows intact, no staged rows inserted.
    total = _prod_rows(
        tmp_dbs["prod"],
        "SELECT COUNT(*) FROM holdings_v2_like",
    )[0][0]
    assert total == 3, "no staged inserts must have committed"

    # Original 3 rows still is_latest=TRUE (including key C's NULL row).
    latest = _prod_rows(
        tmp_dbs["prod"],
        "SELECT COUNT(*) FROM holdings_v2_like WHERE is_latest = TRUE",
    )[0][0]
    assert latest == 3

    # Manifest shows failed with both keys in payload.
    status, err_msg = _manifest_row(tmp_dbs["prod"], run_id)
    assert status == "failed"
    payload = json.loads(err_msg)
    assert payload["total_refused_keys"] == 2


# ---------------------------------------------------------------------------
# T4 — Column existence guard
# ---------------------------------------------------------------------------

def test_column_existence_guard(tmp_path):
    """Target table lacks every sensitive column. Promote proceeds
    without error regardless of staged NULL coverage.
    """
    prod = str(tmp_path / "prod.duckdb")
    staging = str(tmp_path / "staging.duckdb")
    backup = tmp_path / "backups"
    backup.mkdir()
    _init_prod_db(prod, ddl_target=DDL_UNSENSITIVE)

    # Seed one prior row.
    con = duckdb.connect(prod)
    try:
        con.execute(
            "INSERT INTO ncen_fund_series "
            "(cik, fiscal_year, accession_number, shares, is_latest) "
            "VALUES (1, '2025', 'A_OLD', 100, TRUE)"
        )
        con.execute("CHECKPOINT")
    finally:
        con.close()

    staged = [
        {"cik": 1, "fiscal_year": "2025", "accession_number": "A_NEW",
         "shares": 200},
    ]
    pipeline = UnsensitivePipeline(
        prod_db_path=prod,
        staging_db_path=staging,
        backup_dir=str(backup),
        staged_rows=staged,
    )
    run_id = pipeline.run({"fiscal_year": "2025"})
    result = pipeline.approve_and_promote(run_id)

    assert result.rows_inserted == 1
    assert result.rows_flipped == 1
    status, _ = _manifest_row(prod, run_id)
    assert status == "complete"


# ---------------------------------------------------------------------------
# T5 — Non-append_is_latest strategies skip the check
# ---------------------------------------------------------------------------

def test_scd_type2_does_not_trigger_check(tmp_path):
    """scd_type2 has its own supersession semantics. The downgrade check
    is gated on append_is_latest only — verify scd runs are untouched
    by the new logic.
    """
    prod = str(tmp_path / "prod.duckdb")
    staging = str(tmp_path / "staging.duckdb")
    backup = tmp_path / "backups"
    backup.mkdir()
    con = duckdb.connect(prod)
    try:
        con.execute(DDL_MANIFEST)
        con.execute(DDL_IMPACTS)
        con.execute(DDL_FRESHNESS)
        con.execute(
            """
            CREATE TABLE scd_table (
                cik              INTEGER,
                quarter          VARCHAR,
                accession_number VARCHAR,
                ticker           VARCHAR,
                shares           BIGINT,
                valid_to         DATE
            )
            """
        )
        # Seed one open SCD row with ticker populated — would be a
        # downgrade under append_is_latest semantics, but scd_type2
        # closes the old row via valid_to rather than flipping is_latest.
        con.execute(
            "INSERT INTO scd_table VALUES "
            "(1, '2026Q1', 'A_OLD', 'AAPL', 100, DATE '9999-12-31')"
        )
        con.execute("CHECKPOINT")
    finally:
        con.close()

    staged = [
        {"cik": 1, "quarter": "2026Q1", "accession_number": "A_NEW",
         "ticker": None, "shares": 200},
    ]
    pipeline = SCDPipeline(
        prod_db_path=prod,
        staging_db_path=staging,
        backup_dir=str(backup),
        staged_rows=staged,
    )
    run_id = pipeline.run({"quarter": "2026Q1"})
    # Must not raise.
    result = pipeline.approve_and_promote(run_id)
    assert result.rows_inserted == 1
    status, _ = _manifest_row(prod, run_id)
    assert status == "complete"


def test_direct_write_does_not_trigger_check(tmp_path):
    """direct_write has no is_latest semantics. Verify unaffected."""
    prod = str(tmp_path / "prod.duckdb")
    staging = str(tmp_path / "staging.duckdb")
    backup = tmp_path / "backups"
    backup.mkdir()
    con = duckdb.connect(prod)
    try:
        con.execute(DDL_MANIFEST)
        con.execute(DDL_IMPACTS)
        con.execute(DDL_FRESHNESS)
        con.execute(
            """
            CREATE TABLE direct_table (
                cik              INTEGER,
                quarter          VARCHAR,
                accession_number VARCHAR,
                ticker           VARCHAR,
                shares           BIGINT
            )
            """
        )
        con.execute(
            "INSERT INTO direct_table "
            "VALUES (1, '2026Q1', 'A_OLD', 'AAPL', 100)"
        )
        con.execute("CHECKPOINT")
    finally:
        con.close()

    staged = [
        {"cik": 1, "quarter": "2026Q1", "accession_number": "A_NEW",
         "ticker": None, "shares": 200},
    ]
    pipeline = DirectWritePipeline(
        prod_db_path=prod,
        staging_db_path=staging,
        backup_dir=str(backup),
        staged_rows=staged,
    )
    run_id = pipeline.run({"quarter": "2026Q1"})
    result = pipeline.approve_and_promote(run_id)
    assert result.rows_upserted == 1
    status, _ = _manifest_row(prod, run_id)
    assert status == "complete"


# ---------------------------------------------------------------------------
# T6 — Sample cap on manifest payload
# ---------------------------------------------------------------------------

def test_manifest_payload_truncated_to_100(tmp_dbs):
    """With >100 offending keys, the error stores the full count in
    total_refused_keys but only 100 sample entries in refused_keys.
    """
    # Seed 120 keys, each with a prior ticker-populated row.
    prior_rows = [
        {"cik": i, "quarter": "2026Q1", "accession_number": "A_OLD",
         "cusip": f"C{i:05d}", "ticker": "PRIOR",
         "entity_id": None, "rollup_entity_id": None,
         "shares": i, "is_latest": True}
        for i in range(120)
    ]
    _seed_prod(tmp_dbs["prod"], prior_rows)

    staged = [
        {"cik": i, "quarter": "2026Q1", "accession_number": "A_NEW",
         "cusip": f"C{i:05d}", "ticker": None,
         "entity_id": None, "rollup_entity_id": None,
         "shares": 999}
        for i in range(120)
    ]
    pipeline = HoldingsPipeline(
        prod_db_path=tmp_dbs["prod"],
        staging_db_path=tmp_dbs["staging"],
        backup_dir=tmp_dbs["backup"],
        staged_rows=staged,
    )
    run_id = pipeline.run({"quarter": "2026Q1"})
    with pytest.raises(DowngradeRefusalError) as exc_info:
        pipeline.approve_and_promote(run_id)

    err = exc_info.value
    assert err.total_refused_keys == 120
    assert len(err.refusals) == 100

    status, err_msg = _manifest_row(tmp_dbs["prod"], run_id)
    assert status == "failed"
    # manifest.error_message is capped at 500 chars. Ensure the payload
    # fits or is gracefully truncated without breaking the failed status.
    assert err_msg is not None
    # Even truncated, we can still confirm the "kind" field made it in.
    assert "downgrade_refusal" in err_msg
