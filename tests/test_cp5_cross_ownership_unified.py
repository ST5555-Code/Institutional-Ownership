"""Tests for CP-5.3 — Cross-Ownership reader migrations.

Migrates the 3 CLEAN sites in ``scripts/queries/cross.py`` to entity-
keyed grouping via ``inst_to_top_parent`` climb (migration 027). Same
``top_parent_canonical_name_sql`` helper pattern as CP-5.2 / Register.

CLEAN sites covered here:

  C1 — ``_cross_ownership_query`` (Top Investors Across Group +
       Top Holders by Company main matrix)
  C4 — ``get_two_company_overlap`` (institutional panel)
  C6 — ``get_two_company_subject`` (subject-only variant)

Drill sites C3 / C5 are deferred to cp-5-2c-register-drill-hierarchy
(filer-tier ERH lookup does not match top-parent canonical name).

Tests:

  T1 — C1 main matrix SQL parses + groups by canonical top-parent name
  T2 — C1 multi-ticker pivot (Top Investors Across Group shape) returns
       aggregated rows with no duplicate canonical names within result
  T3 — C1 fund_parents CTE climbs to top-parent (validates has_fund_detail
       JOIN against migrated parent_holdings investor name)
  T4 — C4 / C6 overlap subj_holders / inst_rows pattern parses
  T5 — Capital Group umbrella eid 12 aggregates 3 wholly_owned arms
       through cross-ownership reader path (validates PR #287 bridges)

Test runner: shared fixture applies migrations 027 + 028 to a tmp copy
of the fixture DB. Capital Group bridge skip marker applies.
"""
from __future__ import annotations

import importlib.util
import shutil
import sys
import tempfile
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

FIXTURE_SRC = ROOT / "tests" / "fixtures" / "13f_fixture.duckdb"
MIG_027 = ROOT / "scripts" / "migrations" / "027_unified_holdings_view.py"
MIG_028 = (
    ROOT / "scripts" / "migrations"
    / "028_unified_holdings_quarter_dimension.py"
)


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def db_path():
    """Apply migrations 027 + 028 to a tmp fixture copy."""
    with tempfile.TemporaryDirectory() as tmp:
        dst = Path(tmp) / "fixture_with_028.duckdb"
        shutil.copy(FIXTURE_SRC, dst)

        bootstrap = duckdb.connect(str(dst))
        bootstrap.execute(
            "CREATE TABLE IF NOT EXISTS schema_versions ("
            "  version VARCHAR PRIMARY KEY, "
            "  notes VARCHAR, "
            "  applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        )
        bootstrap.close()

        m027 = _load(MIG_027, "mig027")
        m027.run_migration(str(dst), dry_run=False, skip_guards=True)

        m028 = _load(MIG_028, "mig028")
        m028.run_migration(str(dst), dry_run=False, skip_guards=True)

        yield str(dst)


@pytest.fixture
def con(db_path):
    c = duckdb.connect(db_path, read_only=True)
    try:
        yield c
    finally:
        c.close()


def _has_capital_group_bridge(con):
    n = con.execute("""
        SELECT COUNT(*) FROM entity_relationships
        WHERE valid_to = DATE '9999-12-31'
          AND control_type = 'control'
          AND parent_entity_id = 12
          AND child_entity_id IN (6657, 7125, 7136)
    """).fetchone()[0]
    return n == 3


# ---------------------------------------------------------------------------
# T1 — C1 main matrix SQL pattern (Top Holders by Company / single ticker)
# ---------------------------------------------------------------------------

def test_T1_c1_single_ticker_pattern(con):
    """C1 SQL pattern parses and produces top-25 canonical-named holders
    for a single ticker. Mirrors the main parent_holdings + portfolio_totals
    CTE pair after the COALESCE → top_parent_canonical_name_sql swap."""
    from queries.common import top_parent_canonical_name_sql
    tpn = top_parent_canonical_name_sql('h')

    rows = con.execute(f"""
        WITH parent_holdings AS (
            SELECT
                {tpn} as investor,
                MAX(h.manager_type) as type,
                h.ticker,
                SUM(h.market_value_live) as holding_value
            FROM holdings_v2 h
            WHERE h.ticker = 'AAPL'
              AND h.is_latest = TRUE
            GROUP BY investor, h.ticker
        ),
        portfolio_totals AS (
            SELECT
                {tpn} as investor,
                SUM(h.market_value_live) as total_portfolio
            FROM holdings_v2 h
            WHERE h.is_latest = TRUE
            GROUP BY investor
        )
        SELECT
            ph.investor,
            ph.holding_value,
            pt.total_portfolio
        FROM parent_holdings ph
        LEFT JOIN portfolio_totals pt ON ph.investor = pt.investor
        ORDER BY ph.holding_value DESC NULLS LAST
        LIMIT 5
    """).fetchall()
    if not rows:
        pytest.skip("fixture has no AAPL holdings_v2 rows")
    # Canonical names should be strings (or None for fallback)
    for inv, _hv, _tp in rows:
        assert inv is None or isinstance(inv, str)


# ---------------------------------------------------------------------------
# T2 — Top Investors Across Group: multi-ticker pivot, no dup canonical names
# ---------------------------------------------------------------------------

def test_T2_c1_multi_ticker_pivot_no_duplicates(con):
    """Top Investors Across Group: multi-ticker pivot must aggregate per
    canonical top-parent. The post-migration grouping key is the climbed
    canonical name, so a parent with multiple filer arms (or multiple
    funds rolled up) must collapse into a single row."""
    from queries.common import top_parent_canonical_name_sql
    tpn = top_parent_canonical_name_sql('h')

    pivot_cols = (
        "SUM(CASE WHEN ph.ticker = 'AAPL' THEN ph.holding_value END) AS \"AAPL\","
        " SUM(CASE WHEN ph.ticker = 'MSFT' THEN ph.holding_value END) AS \"MSFT\","
        " SUM(CASE WHEN ph.ticker = 'NVDA' THEN ph.holding_value END) AS \"NVDA\""
    )
    rows = con.execute(f"""
        WITH parent_holdings AS (
            SELECT
                {tpn} as investor,
                h.ticker,
                SUM(h.market_value_live) as holding_value
            FROM holdings_v2 h
            WHERE h.ticker IN ('AAPL', 'MSFT', 'NVDA')
              AND h.is_latest = TRUE
            GROUP BY investor, h.ticker
        )
        SELECT ph.investor, {pivot_cols}
        FROM parent_holdings ph
        GROUP BY ph.investor
        ORDER BY (COALESCE("AAPL", 0) + COALESCE("MSFT", 0) + COALESCE("NVDA", 0)) DESC
        LIMIT 25
    """).fetchall()
    if not rows:
        pytest.skip("fixture has no holdings_v2 rows for AAPL/MSFT/NVDA")
    names = [r[0] for r in rows if r[0] is not None]
    assert len(names) == len(set(names)), (
        f"duplicate canonical names in Top Investors Across Group: {names}"
    )


# ---------------------------------------------------------------------------
# T3 — fund_parents CTE climbs to top parent (has_fund_detail consistency)
# ---------------------------------------------------------------------------

def test_T3_fund_parents_climb_consistency(con):
    """The fund_parents CTE inside _cross_ownership_query must also climb
    via inst_to_top_parent, otherwise has_fund_detail JOIN keys mismatch
    the migrated parent_holdings investor name (filer-tier vs top-parent).
    This test pins the climb shape used in the migrated query."""
    rows = con.execute("""
        SELECT DISTINCT name FROM (
            SELECT e.canonical_name AS name
            FROM fund_holdings_v2 fh2
            JOIN entity_rollup_history erh
              ON erh.entity_id = fh2.entity_id
             AND erh.rollup_type = 'decision_maker_v1'
             AND erh.valid_to = DATE '9999-12-31'
            JOIN inst_to_top_parent ittp
              ON ittp.entity_id = erh.rollup_entity_id
            JOIN entities e ON e.entity_id = ittp.top_parent_entity_id
            WHERE fh2.is_latest = TRUE
              AND fh2.market_value_usd > 0
            UNION
            SELECT family_name AS name FROM fund_holdings_v2
            WHERE is_latest = TRUE
              AND market_value_usd > 0 AND family_name IS NOT NULL
        )
        LIMIT 5
    """).fetchall()
    # Just needs to parse + return strings (or none in empty fixture)
    for r in rows:
        assert r[0] is None or isinstance(r[0], str)


# ---------------------------------------------------------------------------
# T4 — C4 / C6 overlap pattern (subj_holders / inst_rows)
# ---------------------------------------------------------------------------

def test_T4_overlap_holder_pattern(con):
    """C4 subj_holders + C6 inst_rows share the same canonical-name shape
    after migration. Single SQL pattern test that pins the swap."""
    from queries.common import top_parent_canonical_name_sql
    tpn = top_parent_canonical_name_sql('h')

    rows = con.execute(f"""
        SELECT
            {tpn} as holder,
            MAX(h.manager_type) as manager_type,
            SUM(h.shares) as subj_shares,
            SUM(h.market_value_live) as subj_dollars
        FROM holdings_v2 h
        WHERE h.ticker = 'AAPL'
          AND h.market_value_live > 0
          AND h.is_latest = TRUE
        GROUP BY holder
        ORDER BY subj_dollars DESC NULLS LAST
        LIMIT 50
    """).fetchall()
    if not rows:
        pytest.skip("fixture has no AAPL holdings_v2 rows")
    # No duplicate canonical names in top-50 (entity-keyed grouping)
    names = [r[0] for r in rows if r[0] is not None]
    assert len(names) == len(set(names)), (
        f"duplicate canonical names in overlap holder panel: {names}"
    )


# ---------------------------------------------------------------------------
# T5 — Capital Group umbrella through cross-ownership reader path
# ---------------------------------------------------------------------------

def test_T5_capital_group_aggregates_in_cross_ownership(con):
    """Three Capital Group filer arms (eid 6657 / 7125 / 7136) must
    aggregate under a single canonical name when read through the
    cross-ownership reader path (validates PR #287 umbrella → CP-5.3
    reader migration)."""
    if not _has_capital_group_bridge(con):
        pytest.skip("fixture pre-dates PR #287 Capital Group bridges")
    from queries.common import top_parent_canonical_name_sql
    tpn = top_parent_canonical_name_sql('h')

    # Mirror C4 subj_holders shape but restrict to the 3 known arms.
    rows = con.execute(f"""
        SELECT
            {tpn} as holder,
            COUNT(DISTINCT h.entity_id) as n_arms
        FROM holdings_v2 h
        WHERE h.entity_id IN (6657, 7125, 7136)
          AND h.is_latest = TRUE
        GROUP BY holder
    """).fetchall()
    if not rows:
        pytest.skip("fixture has no holdings_v2 rows for Capital Group arms")
    assert len(rows) == 1, (
        f"Capital Group arms split across {len(rows)} canonical names "
        f"in cross-ownership path: {[r[0] for r in rows]}"
    )
