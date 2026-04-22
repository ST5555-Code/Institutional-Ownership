"""Unit tests for scripts/pipeline/base.py (p2-01).

Covers the SourcePipeline ABC against a MockPipeline subclass. All tests
run against temp DuckDB files so no real prod / staging state is touched.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import duckdb
import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from pipeline.base import (  # noqa: E402
    FetchResult,
    InvalidStateTransitionError,
    ParseResult,
    PromoteResult,
    SourcePipeline,
)


# ---------------------------------------------------------------------------
# Control-plane DDL (copied from migration 001, stripped of sequences)
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

DDL_PENDING = """
CREATE TABLE pending_entity_resolution (
    resolution_id     BIGINT PRIMARY KEY,
    manifest_id       BIGINT,
    source_type       VARCHAR NOT NULL,
    identifier_type   VARCHAR NOT NULL,
    identifier_value  VARCHAR NOT NULL,
    resolution_status VARCHAR NOT NULL DEFAULT 'pending',
    pending_key       VARCHAR UNIQUE
)
"""

DDL_FRESHNESS = """
CREATE TABLE data_freshness (
    table_name       VARCHAR PRIMARY KEY,
    last_computed_at TIMESTAMP,
    row_count        BIGINT
)
"""

DDL_MOCK_HOLDINGS = """
CREATE TABLE mock_holdings (
    cik              INTEGER,
    quarter          VARCHAR,
    accession_number VARCHAR,
    shares           BIGINT,
    is_latest        BOOLEAN
)
"""


def _init_prod_db(path: str) -> None:
    con = duckdb.connect(path)
    try:
        con.execute(DDL_MANIFEST)
        con.execute(DDL_IMPACTS)
        con.execute(DDL_PENDING)
        con.execute(DDL_FRESHNESS)
        con.execute(DDL_MOCK_HOLDINGS)
        con.execute("CHECKPOINT")
    finally:
        con.close()


def _current_db_path(con) -> str:
    row = con.execute(
        "SELECT path FROM duckdb_databases() "
        "WHERE database_name = current_database()"
    ).fetchone()
    return row[0] if row and row[0] else ""


# ---------------------------------------------------------------------------
# MockPipeline
# ---------------------------------------------------------------------------

class MockPipeline(SourcePipeline):
    name = "mock_test"
    target_table = "mock_holdings"
    amendment_strategy = "append_is_latest"
    amendment_key = ("cik", "quarter")

    def __init__(self, *, rows: int = 10, accession: str = "A1", **kw):
        super().__init__(**kw)
        self._rows = rows
        self._accession = accession
        self.fetch_call_count = 0
        self.parse_call_count = 0
        self.fetch_db_path = ""
        self.parse_db_path = ""

    def fetch(self, scope, staging_con):
        self.fetch_call_count += 1
        self.fetch_db_path = _current_db_path(staging_con)
        staging_con.execute("DROP TABLE IF EXISTS mock_holdings")
        staging_con.execute(
            """
            CREATE TABLE mock_holdings (
                cik              INTEGER,
                quarter          VARCHAR,
                accession_number VARCHAR,
                shares           BIGINT,
                is_latest        BOOLEAN
            )
            """
        )
        q = scope["quarter"]
        for i in range(self._rows):
            staging_con.execute(
                "INSERT INTO mock_holdings VALUES (?, ?, ?, ?, TRUE)",
                [1, q, self._accession, (i + 1) * 100],
            )
        return FetchResult(run_id="", rows_staged=self._rows)

    def parse(self, staging_con):
        self.parse_call_count += 1
        self.parse_db_path = _current_db_path(staging_con)
        return ParseResult(
            run_id="",
            rows_parsed=self._rows,
            target_staging_table="mock_holdings",
        )

    def target_table_spec(self):
        return {
            "columns": [
                ("cik", "INTEGER"),
                ("quarter", "VARCHAR"),
                ("accession_number", "VARCHAR"),
                ("shares", "BIGINT"),
                ("is_latest", "BOOLEAN"),
            ],
            "pk": ["cik", "quarter", "accession_number"],
            "indexes": [],
        }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_dbs(tmp_path):
    prod = tmp_path / "prod.duckdb"
    staging = tmp_path / "staging.duckdb"
    backup = tmp_path / "backups"
    backup.mkdir()
    _init_prod_db(str(prod))
    return {
        "prod": str(prod),
        "staging": str(staging),
        "backup": str(backup),
    }


@pytest.fixture
def pipeline(tmp_dbs):
    return MockPipeline(
        prod_db_path=tmp_dbs["prod"],
        staging_db_path=tmp_dbs["staging"],
        backup_dir=tmp_dbs["backup"],
    )


def _manifest_status(prod_path: str, run_id: str) -> str:
    con = duckdb.connect(prod_path, read_only=True)
    try:
        row = con.execute(
            "SELECT fetch_status FROM ingestion_manifest WHERE run_id = ?",
            [run_id],
        ).fetchone()
    finally:
        con.close()
    assert row is not None, f"no manifest row for {run_id}"
    return row[0]


def _count_latest(prod_path: str) -> int:
    con = duckdb.connect(prod_path, read_only=True)
    try:
        return con.execute(
            "SELECT COUNT(*) FROM mock_holdings WHERE is_latest = TRUE"
        ).fetchone()[0]
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_run_creates_manifest_row(pipeline):
    run_id = pipeline.run({"quarter": "2026Q1"})
    assert _manifest_status(pipeline._prod_db_path, run_id) == "pending_approval"


def test_run_idempotent(pipeline):
    run_id1 = pipeline.run({"quarter": "2026Q1"})
    assert pipeline.fetch_call_count == 1
    run_id2 = pipeline.run({"quarter": "2026Q1"})
    assert run_id1 == run_id2
    assert pipeline.fetch_call_count == 1, "fetch() should not re-run on idempotent call"


def test_approve_promotes(pipeline):
    run_id = pipeline.run({"quarter": "2026Q1"})
    result = pipeline.approve_and_promote(run_id)
    assert isinstance(result, PromoteResult)
    assert result.rows_inserted == 10
    assert result.rows_flipped == 0
    assert _manifest_status(pipeline._prod_db_path, run_id) == "complete"
    assert _count_latest(pipeline._prod_db_path) == 10

    con = duckdb.connect(pipeline._prod_db_path, read_only=True)
    try:
        impact_actions = [
            r[0] for r in con.execute(
                """
                SELECT unit_type FROM ingestion_impacts
                 WHERE manifest_id = (
                    SELECT manifest_id FROM ingestion_manifest
                     WHERE run_id = ?
                 )
                """,
                [run_id],
            ).fetchall()
        ]
    finally:
        con.close()
    assert "insert" in impact_actions
    assert "flip_is_latest" in impact_actions


def test_reject(pipeline):
    run_id = pipeline.run({"quarter": "2026Q1"})
    pipeline.reject(run_id, "not this quarter")
    assert _manifest_status(pipeline._prod_db_path, run_id) == "rejected"

    # Staging table is not dropped on reject — retained for inspection.
    con = duckdb.connect(pipeline._staging_db_path, read_only=True)
    try:
        rows = con.execute("SELECT COUNT(*) FROM mock_holdings").fetchone()[0]
    finally:
        con.close()
    assert rows == 10, "reject() must preserve staging for human review"


def test_rollback_reverses_inserts(pipeline):
    run_id = pipeline.run({"quarter": "2026Q1"})
    pipeline.approve_and_promote(run_id)
    assert _count_latest(pipeline._prod_db_path) == 10

    pipeline.rollback(run_id)
    assert _count_latest(pipeline._prod_db_path) == 0
    assert _manifest_status(pipeline._prod_db_path, run_id) == "rolled_back"


def test_rollback_flips_is_latest_back(tmp_dbs):
    """After a second-generation amendment promote, rollback of the
    amendment should restore is_latest=TRUE on the prior-generation rows."""
    # First run — accession A1, 10 rows, is_latest=TRUE after approve.
    p1 = MockPipeline(
        prod_db_path=tmp_dbs["prod"],
        staging_db_path=tmp_dbs["staging"],
        backup_dir=tmp_dbs["backup"],
        accession="A1",
    )
    run1 = p1.run({"quarter": "2026Q1"})
    p1.approve_and_promote(run1)
    assert _count_latest(tmp_dbs["prod"]) == 10

    # Second run — accession A2, same quarter, flips A1 rows to is_latest=FALSE.
    p2 = MockPipeline(
        prod_db_path=tmp_dbs["prod"],
        staging_db_path=tmp_dbs["staging"],
        backup_dir=tmp_dbs["backup"],
        accession="A2",
    )
    run2 = p2.run({"quarter": "2026Q2"})  # different scope -> fresh manifest
    result = p2.approve_and_promote(run2)
    assert result.rows_inserted == 10

    # Rollback of run2 should leave run1 untouched (different amendment_key).
    p2.rollback(run2)
    assert _count_latest(tmp_dbs["prod"]) == 10


def test_invalid_state_transition(pipeline):
    run_id = pipeline.run({"quarter": "2026Q1"})
    pipeline.reject(run_id, "no")
    with pytest.raises((ValueError, InvalidStateTransitionError)):
        pipeline.approve_and_promote(run_id)


def test_snapshot_created(pipeline):
    run_id = pipeline.run({"quarter": "2026Q1"})
    pipeline.approve_and_promote(run_id)
    snap = Path(pipeline._backup_dir) / f"mock_test_{run_id}.duckdb"
    assert snap.exists(), f"snapshot not created at {snap}"

    # Snapshot should contain the pre-promote state (empty table).
    con = duckdb.connect(str(snap), read_only=True)
    try:
        count = con.execute("SELECT COUNT(*) FROM mock_holdings").fetchone()[0]
    finally:
        con.close()
    assert count == 0


def test_prune_old_snapshots(pipeline):
    old = pipeline._backup_dir / "mock_test_old.duckdb"
    old.write_bytes(b"x")
    old_ts = time.time() - 30 * 86400
    os.utime(old, (old_ts, old_ts))

    new = pipeline._backup_dir / "mock_test_new.duckdb"
    new.write_bytes(b"x")

    pruned = pipeline.prune_old_snapshots(retention_days=14)
    assert pruned == 1
    assert not old.exists()
    assert new.exists()


def test_staging_isolation(pipeline):
    pipeline.run({"quarter": "2026Q1"})
    # fetch() and parse() must have been handed the staging DB path
    assert pipeline.fetch_db_path != ""
    assert pipeline.parse_db_path != ""
    # Resolve through realpath so tmp_path symlinks on macOS don't trip us up.
    def _real(p):
        return os.path.realpath(p) if p else p
    assert _real(pipeline.fetch_db_path) == _real(pipeline._staging_db_path)
    assert _real(pipeline.parse_db_path) == _real(pipeline._staging_db_path)
    assert _real(pipeline.fetch_db_path) != _real(pipeline._prod_db_path)


def test_promote_is_atomic_rollback_on_failure(pipeline):
    """If record_impact raises after the flip UPDATE commits would be lost
    unless the promote is wrapped in a transaction. Verifies ROLLBACK
    restores is_latest on the previously-flipped rows and leaves no new
    inserted rows behind."""
    # Seed prod with 5 rows at (cik=1, quarter='2026Q1'), all is_latest=TRUE.
    con = duckdb.connect(pipeline._prod_db_path)
    try:
        for i in range(5):
            con.execute(
                "INSERT INTO mock_holdings "
                "VALUES (1, '2026Q1', 'A_PRIOR', ?, TRUE)",
                [100 + i],
            )
        con.execute(
            "INSERT INTO ingestion_manifest "
            "(manifest_id, source_type, object_type, object_key, "
            " run_id, fetch_status) VALUES "
            "(1, 'mock_test', 'SCOPE', 'mock_test:q=2026Q1#atomic', "
            " 'atomic_test', 'approved')"
        )
        con.execute("CHECKPOINT")
    finally:
        con.close()

    # Stage 3 new rows with same amendment_key.
    staging = duckdb.connect(pipeline._staging_db_path)
    try:
        staging.execute(DDL_MOCK_HOLDINGS)
        for i in range(3):
            staging.execute(
                "INSERT INTO mock_holdings "
                "VALUES (1, '2026Q1', 'A_NEW', ?, TRUE)",
                [200 + i],
            )
        staging.execute("CHECKPOINT")
    finally:
        staging.close()

    # Make record_impact fail on the post-INSERT "insert" action.
    orig = pipeline.record_impact

    def failing(prod_con, **kw):
        if kw.get("action") == "insert":
            raise RuntimeError("simulated post-insert failure")
        return orig(prod_con, **kw)

    pipeline.record_impact = failing

    prod_con = duckdb.connect(pipeline._prod_db_path)
    try:
        with pytest.raises(RuntimeError, match="simulated"):
            pipeline._promote_append_is_latest("atomic_test", prod_con)
    finally:
        prod_con.close()

    # After rollback: original 5 rows remain, all is_latest=TRUE.
    con = duckdb.connect(pipeline._prod_db_path, read_only=True)
    try:
        total = con.execute(
            "SELECT COUNT(*) FROM mock_holdings"
        ).fetchone()[0]
        latest = con.execute(
            "SELECT COUNT(*) FROM mock_holdings WHERE is_latest = TRUE"
        ).fetchone()[0]
        impacts = con.execute(
            "SELECT COUNT(*) FROM ingestion_impacts WHERE manifest_id = 1"
        ).fetchone()[0]
    finally:
        con.close()

    assert total == 5, "INSERT must not have committed (rollback)"
    assert latest == 5, "flip UPDATE must have rolled back"
    assert impacts == 0, "impact rows must have rolled back with the promote"


def test_promote_excludes_prod_only_columns(tmp_path):
    """Prod has a row_id column with a sequence DEFAULT that staging
    lacks. SELECT * would fail with column-count mismatch. An explicit
    column list driven by the staging schema lets the DEFAULT populate
    row_id for the new rows."""
    prod = str(tmp_path / "prod.duckdb")
    staging = str(tmp_path / "staging.duckdb")
    backup = tmp_path / "backups"
    backup.mkdir()

    con = duckdb.connect(prod)
    try:
        con.execute(DDL_MANIFEST)
        con.execute(DDL_IMPACTS)
        con.execute(DDL_PENDING)
        con.execute(DDL_FRESHNESS)
        con.execute("CREATE SEQUENCE mock_row_id_seq START 1")
        con.execute(
            """
            CREATE TABLE mock_holdings (
                cik              INTEGER,
                quarter          VARCHAR,
                accession_number VARCHAR,
                shares           BIGINT,
                row_id           BIGINT DEFAULT nextval('mock_row_id_seq'),
                is_latest        BOOLEAN
            )
            """
        )
        con.execute("CHECKPOINT")
    finally:
        con.close()

    p = MockPipeline(
        prod_db_path=prod,
        staging_db_path=staging,
        backup_dir=str(backup),
    )
    run_id = p.run({"quarter": "2026Q1"})
    result = p.approve_and_promote(run_id)

    assert result.rows_inserted == 10

    con = duckdb.connect(prod, read_only=True)
    try:
        rows = con.execute(
            "SELECT row_id, shares FROM mock_holdings ORDER BY row_id"
        ).fetchall()
    finally:
        con.close()
    assert len(rows) == 10
    assert all(r[0] is not None for r in rows), "row_id must be populated by DEFAULT"


def test_amendment_strategy_dispatch(pipeline, monkeypatch):
    called: list[str] = []

    def fake_append(run_id, prod_con):
        called.append("append")
        return PromoteResult(run_id=run_id)

    def fake_scd(run_id, prod_con):
        called.append("scd")
        return PromoteResult(run_id=run_id)

    def fake_direct(run_id, prod_con):
        called.append("direct")
        return PromoteResult(run_id=run_id)

    monkeypatch.setattr(pipeline, "_promote_append_is_latest", fake_append)
    monkeypatch.setattr(pipeline, "_promote_scd_type2", fake_scd)
    monkeypatch.setattr(pipeline, "_promote_direct_write", fake_direct)

    con = duckdb.connect(pipeline._prod_db_path)
    try:
        # append_is_latest
        pipeline.amendment_strategy = "append_is_latest"
        pipeline.promote("r1", con)
        # scd_type2
        pipeline.amendment_strategy = "scd_type2"
        pipeline.promote("r2", con)
        # direct_write
        pipeline.amendment_strategy = "direct_write"
        pipeline.promote("r3", con)
    finally:
        con.close()

    assert called == ["append", "scd", "direct"]
