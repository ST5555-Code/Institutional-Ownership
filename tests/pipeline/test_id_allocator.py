"""Unit tests for scripts/pipeline/id_allocator.py (obs-03 Phase 1)."""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import duckdb
import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from pipeline.id_allocator import (  # noqa: E402
    _ID_TABLES,
    allocate_id,
    reserve_ids,
)
from pipeline import manifest as manifest_module  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

DDL_IMPACTS = """
CREATE TABLE ingestion_impacts (
    impact_id      BIGINT PRIMARY KEY,
    manifest_id    BIGINT,
    target_table   VARCHAR,
    unit_type      VARCHAR,
    unit_key_json  VARCHAR,
    report_date    DATE,
    rows_staged    INTEGER,
    load_status    VARCHAR,
    validation_tier VARCHAR,
    promote_status VARCHAR DEFAULT 'pending'
)
"""

DDL_MANIFEST = """
CREATE TABLE ingestion_manifest (
    manifest_id              BIGINT PRIMARY KEY,
    source_type              VARCHAR,
    object_type              VARCHAR,
    object_key               VARCHAR UNIQUE,
    source_url               VARCHAR,
    accession_number         VARCHAR,
    run_id                   VARCHAR,
    fetch_status             VARCHAR,
    superseded_by_manifest_id BIGINT,
    is_amendment             BOOLEAN
)
"""


@pytest.fixture
def con(tmp_path):
    """Isolated DuckDB with the two control-plane tables."""
    db = tmp_path / "alloc_test.duckdb"
    c = duckdb.connect(str(db))
    c.execute(DDL_IMPACTS)
    c.execute(DDL_MANIFEST)
    yield c
    c.close()


# ---------------------------------------------------------------------------
# allocate_id
# ---------------------------------------------------------------------------


class TestAllocateId:
    def test_empty_table_returns_one(self, con):
        assert allocate_id(con, "ingestion_impacts", "impact_id") == 1

    def test_max_plus_one(self, con):
        con.execute("INSERT INTO ingestion_impacts (impact_id) VALUES (42)")
        assert allocate_id(con, "ingestion_impacts", "impact_id") == 43

    def test_monotonic_after_insert(self, con):
        first = allocate_id(con, "ingestion_impacts", "impact_id")
        con.execute(
            "INSERT INTO ingestion_impacts (impact_id) VALUES (?)", [first]
        )
        second = allocate_id(con, "ingestion_impacts", "impact_id")
        assert second == first + 1

    def test_both_allowlisted_tables(self, con):
        assert allocate_id(con, "ingestion_manifest", "manifest_id") == 1
        assert allocate_id(con, "ingestion_impacts", "impact_id") == 1

    def test_rejects_unknown_table(self, con):
        with pytest.raises(ValueError, match="allow-list"):
            allocate_id(con, "ingestion_manifests", "manifest_id")

    def test_rejects_unknown_column(self, con):
        with pytest.raises(ValueError, match="allow-list"):
            allocate_id(con, "ingestion_impacts", "id")


# ---------------------------------------------------------------------------
# reserve_ids
# ---------------------------------------------------------------------------


class TestReserveIds:
    def test_empty_table_starts_at_one(self, con):
        r = reserve_ids(con, "ingestion_impacts", "impact_id", 5)
        assert list(r) == [1, 2, 3, 4, 5]

    def test_contiguous_range_length(self, con):
        r = reserve_ids(con, "ingestion_impacts", "impact_id", 1000)
        assert len(r) == 1000
        assert r[0] == 1
        assert r[-1] == 1000

    def test_starts_at_max_plus_one(self, con):
        con.execute(
            "INSERT INTO ingestion_impacts (impact_id) VALUES (40_000)"
        )
        r = reserve_ids(con, "ingestion_impacts", "impact_id", 3)
        assert list(r) == [40_001, 40_002, 40_003]

    def test_zero_returns_empty_range(self, con):
        r = reserve_ids(con, "ingestion_impacts", "impact_id", 0)
        assert list(r) == []

    def test_negative_raises(self, con):
        with pytest.raises(ValueError, match="must be >= 0"):
            reserve_ids(con, "ingestion_impacts", "impact_id", -1)

    def test_allocate_after_reserve_respects_insert(self, con):
        reserved = reserve_ids(con, "ingestion_impacts", "impact_id", 10)
        # Caller is expected to INSERT the reserved rows. Simulate that.
        con.executemany(
            "INSERT INTO ingestion_impacts (impact_id) VALUES (?)",
            [[i] for i in reserved],
        )
        next_id = allocate_id(con, "ingestion_impacts", "impact_id")
        assert next_id == reserved[-1] + 1

    def test_rejects_unknown_table(self, con):
        with pytest.raises(ValueError, match="allow-list"):
            reserve_ids(con, "random_table", "impact_id", 5)


# ---------------------------------------------------------------------------
# API compatibility — write_impact still works after rewire
# ---------------------------------------------------------------------------


class TestWriteImpactCompatibility:
    def test_write_impact_returns_allocated_id(self, con):
        # Register a manifest first so FK logic in real DB would be happy.
        mid = manifest_module.get_or_create_manifest_row(
            con,
            source_type="NPORT",
            object_type="filing",
            source_url="https://example",
            accession_number="0000000000-00-000001",
            run_id="TEST",
            object_key="TEST/key/1",
        )
        assert mid == 1
        impact_id = manifest_module.write_impact(
            con,
            manifest_id=mid,
            target_table="fund_holdings_v2",
            unit_type="series_month",
            unit_key_json='{"series_id":"S1","report_month":"2024-03"}',
            rows_staged=100,
        )
        assert impact_id == 1

        # Second impact increments monotonically.
        impact_id_2 = manifest_module.write_impact(
            con,
            manifest_id=mid,
            target_table="fund_holdings_v2",
            unit_type="series_month",
            unit_key_json='{"series_id":"S2","report_month":"2024-03"}',
            rows_staged=50,
        )
        assert impact_id_2 == 2

    def test_manifest_id_allocator_drives_pk(self, con):
        for i in range(3):
            manifest_module.get_or_create_manifest_row(
                con,
                source_type="NPORT",
                object_type="filing",
                source_url="https://example",
                accession_number=f"000-{i}",
                run_id="TEST",
                object_key=f"TEST/key/{i}",
            )
        rows = con.execute(
            "SELECT manifest_id FROM ingestion_manifest ORDER BY manifest_id"
        ).fetchall()
        assert [r[0] for r in rows] == [1, 2, 3]


# ---------------------------------------------------------------------------
# Concurrency — two python subprocesses against the same DuckDB file
# ---------------------------------------------------------------------------


def test_two_writers_serialize(tmp_path):
    """Second concurrent writer must fail with DuckDB's own file lock
    rather than racing past the advisory lock and double-allocating.

    DuckDB refuses to open a DB already held open for writes by another
    process. The advisory flock is a secondary safety net; the primary
    guarantee here is DuckDB's lock. If this invariant ever breaks (e.g.
    DuckDB moves to multi-writer), the advisory flock still prevents
    torn MAX+1 reads because both processes would serialize on
    `data/.ingestion_lock`.
    """
    db = tmp_path / "concurrent.duckdb"
    con = duckdb.connect(str(db))
    con.execute(DDL_IMPACTS)
    con.execute(DDL_MANIFEST)
    # Keep the writer handle open — a second attempt must fail.
    script = textwrap.dedent(
        f"""
        import sys
        sys.path.insert(0, {str(ROOT / 'scripts')!r})
        import duckdb
        try:
            duckdb.connect({str(db)!r}, read_only=False)
            print('UNEXPECTED_OPEN')
        except duckdb.IOException as exc:
            print('LOCKED', exc.__class__.__name__)
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, check=False, timeout=30,
    )
    con.close()
    assert "LOCKED" in result.stdout, (
        f"Expected LOCKED, got stdout={result.stdout!r} "
        f"stderr={result.stderr!r}"
    )


# ---------------------------------------------------------------------------
# Allow-list sanity
# ---------------------------------------------------------------------------


def test_allowlist_shape():
    """The allow-list is the sole guard against MAX+1 against the wrong
    table. Pin the membership so a careless broadening of the set shows
    up in the diff."""
    assert _ID_TABLES == frozenset({
        ("ingestion_manifest", "manifest_id"),
        ("ingestion_impacts", "impact_id"),
    })
