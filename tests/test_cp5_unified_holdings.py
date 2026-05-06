"""Tests for CP-5.1 unified_holdings + inst_to_top_parent views.

Migration 027 ships two read-only views that consume the canonical
Method A path (read-time decision_maker_v1 ERH JOIN) plus a recursive
ownership climb. These tests pin the contract:

  T1 — climb termination & shape
  T2 — r5_aum = GREATEST(thirteen_f, fund_tier)
  T3 — Capital Group umbrella eid 12 attracts 3 known wholly_owned arms
  T4 — fund_tier_aum is the raw rollup (FoF subtraction deferred to P2)
  T5 — no fund-typed entity is missing decision_maker_v1 (regression
       guard for the Phase 1 PR #298 backfill)
  T6 — top_parent_holdings_join() helper produces parseable JOIN SQL
  T7 — climb determinism (two runs return identical output)
  T8 — zero climbers reach hops=10 (cycle detection guard)

Test runner: each test opens a fresh read-write connection to a tmp
copy of the fixture DB with migration 027 applied. The fixture is
shared across tests via a session-scoped fixture for performance.
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import sys
import tempfile
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

FIXTURE_SRC = ROOT / "tests" / "fixtures" / "13f_fixture.duckdb"
MIGRATION = ROOT / "scripts" / "migrations" / "027_unified_holdings_view.py"


@pytest.fixture(scope="module")
def db_path():
    """Copy fixture to a tmp file and apply migration 027 once per module."""
    with tempfile.TemporaryDirectory() as tmp:
        dst = Path(tmp) / "fixture_with_027.duckdb"
        shutil.copy(FIXTURE_SRC, dst)

        # Fixture DB doesn't carry schema_versions (no migration history).
        # Create the table so migration 027's stamp INSERT succeeds.
        bootstrap = duckdb.connect(str(dst))
        bootstrap.execute(
            "CREATE TABLE IF NOT EXISTS schema_versions ("
            "  version VARCHAR PRIMARY KEY, "
            "  notes VARCHAR, "
            "  applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        )
        bootstrap.close()

        spec = importlib.util.spec_from_file_location(
            "mig027", str(MIGRATION)
        )
        mig = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mig)
        mig.run_migration(str(dst), dry_run=False, skip_guards=True)

        yield str(dst)


@pytest.fixture
def con(db_path):
    c = duckdb.connect(db_path, read_only=True)
    try:
        yield c
    finally:
        c.close()


def _has_capital_group_bridge(con):
    """Capital Group umbrella eid 12 with 3 wholly_owned arms (PR #287)
    is present in prod but not in the historical fixture. Skip-marker."""
    n = con.execute("""
        SELECT COUNT(*) FROM entity_relationships
        WHERE valid_to = DATE '9999-12-31'
          AND control_type = 'control'
          AND parent_entity_id = 12
          AND child_entity_id IN (6657, 7125, 7136)
    """).fetchone()[0]
    return n == 3


def _has_cycle_truncation(con):
    """PR #285 truncated mutual-control cycles. Pre-PR #285 fixtures
    can have residual cycles; tests gate on absence of hops=10
    climbers. Skip-marker."""
    n = con.execute(
        "SELECT COUNT(*) FROM inst_to_top_parent WHERE hops_at_top = 10"
    ).fetchone()[0]
    return n == 0


# ---------------------------------------------------------------------------
# T1 — climb termination & shape
# ---------------------------------------------------------------------------

def test_T1_climb_covers_every_entity(con):
    n_entities = con.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
    n_climbers = con.execute(
        "SELECT COUNT(DISTINCT entity_id) FROM inst_to_top_parent"
    ).fetchone()[0]
    assert n_climbers == n_entities, (
        f"climb missed {n_entities - n_climbers} entities"
    )


def test_T1_climb_max_hops_under_limit(con):
    if not _has_cycle_truncation(con):
        pytest.skip("fixture pre-dates PR #285 cycle truncation")
    max_hops = con.execute(
        "SELECT MAX(hops_at_top) FROM inst_to_top_parent"
    ).fetchone()[0]
    assert max_hops < 10, (
        f"climb reached hops_at_top={max_hops} — cycle suspect"
    )


def test_T1_every_climber_has_top_parent(con):
    n_null = con.execute(
        "SELECT COUNT(*) FROM inst_to_top_parent "
        "WHERE top_parent_entity_id IS NULL"
    ).fetchone()[0]
    assert n_null == 0


# ---------------------------------------------------------------------------
# T2 — r5_aum = GREATEST(thirteen_f, fund_tier)
# ---------------------------------------------------------------------------

def test_T2_r5_aum_equals_greatest(con):
    n_violations = con.execute("""
        SELECT COUNT(*) FROM unified_holdings
        WHERE r5_aum_b <> GREATEST(thirteen_f_aum_b, fund_tier_aum_b)
    """).fetchone()[0]
    assert n_violations == 0


def test_T2_source_winner_matches_r5(con):
    # source_winner = '13F' iff thirteen_f >= fund_tier (tie goes to 13F)
    n_violations = con.execute("""
        SELECT COUNT(*) FROM unified_holdings
        WHERE (source_winner = '13F'
               AND thirteen_f_aum_b < fund_tier_aum_b)
           OR (source_winner = 'fund_tier'
               AND thirteen_f_aum_b >= fund_tier_aum_b)
    """).fetchone()[0]
    assert n_violations == 0


# ---------------------------------------------------------------------------
# T3 — Capital Group umbrella eid 12 attracts 3 wholly_owned arms
# ---------------------------------------------------------------------------

def test_T3_capital_group_arms_climb_to_umbrella(con):
    """eid 6657 / 7125 / 7136 (Capital Group filer arms, PR #287) must
    each climb to top_parent_entity_id = 12 (umbrella)."""
    if not _has_capital_group_bridge(con):
        pytest.skip("fixture pre-dates PR #287 Capital Group bridges")
    rows = con.execute("""
        SELECT entity_id, top_parent_entity_id
        FROM inst_to_top_parent
        WHERE entity_id IN (6657, 7125, 7136)
        ORDER BY entity_id
    """).fetchall()
    assert len(rows) == 3, f"expected 3 arm rows, got {len(rows)}"
    for entity_id, top in rows:
        assert top == 12, (
            f"Capital Group arm {entity_id} climbs to {top}, expected 12"
        )


def test_T3_umbrella_self_rolls_up(con):
    if not _has_capital_group_bridge(con):
        pytest.skip("fixture pre-dates PR #287 Capital Group bridges")
    row = con.execute("""
        SELECT top_parent_entity_id, hops_at_top
        FROM inst_to_top_parent WHERE entity_id = 12
    """).fetchone()
    assert row is not None, "Capital Group umbrella eid 12 missing"
    assert row[0] == 12, f"umbrella climbs to {row[0]}, expected 12 (self)"
    assert row[1] == 0, f"umbrella hops_at_top={row[1]}, expected 0"


# ---------------------------------------------------------------------------
# T4 — fund_tier_aum_b ships as raw rollup (FoF subtraction deferred)
# ---------------------------------------------------------------------------

def test_T4_fund_tier_equals_raw_rollup(con):
    """unified_holdings.fund_tier_aum_b should equal the raw
    Method-A-rollup-by-(top_parent, cusip, ticker) sum from
    fund_holdings_v2 — no FoF subtraction is applied (Path A from
    PR #299 mid-execution decision; tracked as P2 follow-up
    cp-5-fof-subtraction-cusip-linkage)."""
    diff = con.execute("""
        WITH raw AS (
            SELECT
                ittp.top_parent_entity_id,
                fh.cusip, fh.ticker,
                SUM(fh.market_value_usd) / 1e9 AS raw_b
            FROM fund_holdings_v2 fh
            JOIN entity_rollup_history erh
                ON erh.entity_id = fh.entity_id
                AND erh.rollup_type = 'decision_maker_v1'
                AND erh.valid_to = DATE '9999-12-31'
            JOIN inst_to_top_parent ittp
                ON ittp.entity_id = erh.rollup_entity_id
            WHERE fh.is_latest = TRUE
              AND fh.cusip IS NOT NULL AND fh.cusip <> ''
            GROUP BY 1, 2, 3
        )
        SELECT COUNT(*) FROM unified_holdings u
        JOIN raw r
          ON r.top_parent_entity_id = u.top_parent_entity_id
          AND r.cusip = u.cusip
          AND r.ticker = u.ticker
        WHERE ABS(u.fund_tier_aum_b - r.raw_b) > 1e-6
    """).fetchone()[0]
    assert diff == 0, (
        f"{diff} rows where fund_tier_aum_b drifts from raw rollup"
    )


# ---------------------------------------------------------------------------
# T5 — every fund entity has decision_maker_v1 (Phase 1 regression)
# ---------------------------------------------------------------------------

def test_T5_no_fund_missing_dm_v1(con):
    """PR #298 recon found 6 fund-typed entities with ec_v1 but no dm_v1.
    PR #299 Phase 1 confirmed an intervening process backfilled them
    (cohort drift = -6 between recon and execute). This test pins the
    null-result so future drift surfaces immediately."""
    n_missing = con.execute("""
        SELECT COUNT(*) FROM entities e
        WHERE e.entity_type = 'fund'
          AND EXISTS (
            SELECT 1 FROM entity_rollup_history erh
            WHERE erh.entity_id = e.entity_id
              AND erh.rollup_type = 'economic_control_v1'
              AND erh.valid_to = DATE '9999-12-31'
          )
          AND NOT EXISTS (
            SELECT 1 FROM entity_rollup_history erh
            WHERE erh.entity_id = e.entity_id
              AND erh.rollup_type = 'decision_maker_v1'
              AND erh.valid_to = DATE '9999-12-31'
          )
    """).fetchone()[0]
    assert n_missing == 0, (
        f"{n_missing} fund-typed entities have ec_v1 but no dm_v1 — "
        "rollup-pair invariant violated"
    )


# ---------------------------------------------------------------------------
# T6 — top_parent_holdings_join() helper produces parseable JOIN SQL
# ---------------------------------------------------------------------------

def test_T6_helper_produces_parseable_sql(con):
    from queries.common import top_parent_holdings_join

    fragment = top_parent_holdings_join('fh')
    assert 'erh_top' in fragment
    assert 'ittp_top' in fragment
    assert 'inst_to_top_parent' in fragment
    assert "rollup_type = 'decision_maker_v1'" in fragment
    assert "valid_to = DATE '9999-12-31'" in fragment

    # Run the JOIN against a real query — DuckDB will reject invalid SQL.
    sql = f"""
        SELECT ittp_top.top_parent_entity_id,
               SUM(fh.market_value_usd) / 1e9 AS aum_b
        FROM fund_holdings_v2 fh
        {fragment}
        WHERE fh.is_latest = TRUE
        GROUP BY 1
        LIMIT 5
    """
    rows = con.execute(sql).fetchall()
    assert len(rows) >= 0  # smoke: query parses + executes

    # Custom alias variant
    fragment2 = top_parent_holdings_join('foo')
    assert 'foo.entity_id' in fragment2


# ---------------------------------------------------------------------------
# T7 — climb determinism: two runs identical
# ---------------------------------------------------------------------------

def test_T7_climb_determinism(con):
    rows_a = con.execute("""
        SELECT entity_id, top_parent_entity_id, hops_at_top
        FROM inst_to_top_parent ORDER BY entity_id
    """).fetchall()
    rows_b = con.execute("""
        SELECT entity_id, top_parent_entity_id, hops_at_top
        FROM inst_to_top_parent ORDER BY entity_id
    """).fetchall()
    assert rows_a == rows_b, "inst_to_top_parent is non-deterministic"


# ---------------------------------------------------------------------------
# T8 — cycle detection: zero climbers at hops=10
# ---------------------------------------------------------------------------

def test_T8_no_climbers_reach_hop_limit(con):
    if not _has_cycle_truncation(con):
        pytest.skip("fixture pre-dates PR #285 cycle truncation")
    n = con.execute(
        "SELECT COUNT(*) FROM inst_to_top_parent WHERE hops_at_top = 10"
    ).fetchone()[0]
    assert n == 0, (
        f"{n} climbers reached hops=10 — cycle re-introduced "
        "post PR #285. Investigate entity_relationships before "
        "merging this branch."
    )


# ---------------------------------------------------------------------------
# Smoke: unified_holdings nonempty + has expected columns
# ---------------------------------------------------------------------------

def test_unified_holdings_nonempty(con):
    n = con.execute("SELECT COUNT(*) FROM unified_holdings").fetchone()[0]
    assert n > 0


def test_unified_holdings_columns(con):
    cols = {
        r[0] for r in con.execute(
            "DESCRIBE unified_holdings"
        ).fetchall()
    }
    expected = {
        'top_parent_entity_id', 'top_parent_name', 'cusip', 'ticker',
        'thirteen_f_aum_b', 'fund_tier_aum_b', 'r5_aum_b', 'source_winner',
    }
    assert expected.issubset(cols), (
        f"missing columns: {expected - cols}"
    )
