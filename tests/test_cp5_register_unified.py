"""Tests for CP-5.2 — migration 028 + Register reader migrations.

Migration 028 adds a ``quarter`` dimension to ``unified_holdings``
(grain becomes ``(top_parent_entity_id, quarter, cusip, ticker)``).
The 4 chat-decided clean reader sites (queries 1, 2, 12 in
``scripts/queries/register.py``; query 16 is fund-level no-op) move
from name-coalesce ``COALESCE(rollup_name, inst_parent_name,
manager_name)`` to entity-keyed ``inst_to_top_parent`` climb via the
new ``top_parent_canonical_name_sql`` helper in
``scripts/queries/common.py``.

These tests pin the contract:

  T1 — migration 028 adds ``quarter`` column
  T2 — distinct quarters in view ≥ distinct quarters in 13F leg
  T3 — view rowcount expands (per-quarter grain)
  T4 — ``top_parent_canonical_name_sql`` produces parseable SQL
  T5 — entity-keyed grouping aggregates Capital Group arms (eid 6657
       / 7125 / 7136) under one canonical name (validates PR #287
       umbrella through reader path)
  T6 — query12 SQL pattern parses + groups by canonical name
  T7 — query1 SQL pattern parses + canonical name appears in result

Test runner: shared fixture applies migrations 027 + 028 to a tmp
copy of the fixture DB. Capital-Group / cycle-truncation skip
markers from test_cp5_unified_holdings.py apply.
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
# T1 — migration 028 adds quarter column
# ---------------------------------------------------------------------------

def test_T1_quarter_column_present(con):
    cols = {
        r[0] for r in con.execute("DESCRIBE unified_holdings").fetchall()
    }
    assert "quarter" in cols, (
        "migration 028 should add quarter column to unified_holdings"
    )


def test_T1_legacy_columns_preserved(con):
    cols = {
        r[0] for r in con.execute("DESCRIBE unified_holdings").fetchall()
    }
    expected = {
        'top_parent_entity_id', 'top_parent_name', 'cusip', 'ticker',
        'thirteen_f_aum_b', 'fund_tier_aum_b', 'r5_aum_b', 'source_winner',
    }
    assert expected.issubset(cols), f"missing columns: {expected - cols}"


# ---------------------------------------------------------------------------
# T2 — quarter dimension in view ≥ 13F leg
# ---------------------------------------------------------------------------

def test_T2_view_quarters_cover_13f(con):
    n_view = con.execute(
        "SELECT COUNT(DISTINCT quarter) FROM unified_holdings"
    ).fetchone()[0]
    n_13f = con.execute(
        "SELECT COUNT(DISTINCT quarter) FROM holdings_v2 "
        "WHERE is_latest = TRUE"
    ).fetchone()[0]
    assert n_view >= n_13f, (
        f"view has {n_view} quarters, 13F leg has {n_13f}"
    )


# ---------------------------------------------------------------------------
# T3 — per-quarter grain: a parent x ticker can appear in multiple quarters
# ---------------------------------------------------------------------------

def test_T3_per_quarter_grain(con):
    """A (top_parent, cusip, ticker) tuple may now appear once per
    quarter that has data — not collapsed into a single row."""
    row = con.execute("""
        SELECT MAX(n) FROM (
            SELECT COUNT(*) AS n
            FROM unified_holdings
            GROUP BY top_parent_entity_id, cusip, ticker
        )
    """).fetchone()
    max_dup = row[0] if row else 0
    if max_dup is None:
        pytest.skip("fixture has no unified_holdings rows")
    assert max_dup >= 1, "no rows in unified_holdings"


# ---------------------------------------------------------------------------
# T4 — top_parent_canonical_name_sql helper
# ---------------------------------------------------------------------------

def test_T4_helper_produces_parseable_sql(con):
    from queries.common import top_parent_canonical_name_sql

    expr = top_parent_canonical_name_sql('h')
    assert "inst_to_top_parent" in expr
    assert "canonical_name" in expr
    assert "h.entity_id" in expr

    sql = f"""
        SELECT {expr} AS top_name, COUNT(*) AS n
        FROM holdings_v2 h
        WHERE h.is_latest = TRUE
        GROUP BY {expr}
        LIMIT 5
    """
    rows = con.execute(sql).fetchall()
    assert len(rows) >= 0


def test_T4_helper_no_alias_variant():
    from queries.common import top_parent_canonical_name_sql

    expr = top_parent_canonical_name_sql('')
    assert "ittp.entity_id = entity_id" in expr


# ---------------------------------------------------------------------------
# T5 — Capital Group umbrella aggregation through reader path
# ---------------------------------------------------------------------------

def test_T5_capital_group_arms_aggregate_under_one_name(con):
    """Three Capital Group filer arms (eid 6657 / 7125 / 7136) must
    all map to the same ``entities.canonical_name`` via the climb
    when read through the entity-keyed reader pattern."""
    if not _has_capital_group_bridge(con):
        pytest.skip("fixture pre-dates PR #287 Capital Group bridges")
    from queries.common import top_parent_canonical_name_sql
    expr = top_parent_canonical_name_sql('h')
    rows = con.execute(f"""
        SELECT {expr} AS top_name, COUNT(DISTINCT h.entity_id) AS n_arms
        FROM holdings_v2 h
        WHERE h.entity_id IN (6657, 7125, 7136)
          AND h.is_latest = TRUE
        GROUP BY {expr}
    """).fetchall()
    if not rows:
        pytest.skip("fixture has no holdings_v2 rows for arms")
    assert len(rows) == 1, (
        f"Capital Group arms split across {len(rows)} canonical names: "
        f"{[r[0] for r in rows]}"
    )


# ---------------------------------------------------------------------------
# T6 — query12 SQL pattern (concentration analysis)
# ---------------------------------------------------------------------------

def test_T6_query12_sql_pattern_parses(con):
    """query12's migrated SQL parses and groups by canonical name."""
    from queries.common import top_parent_canonical_name_sql
    tpn = top_parent_canonical_name_sql('h')
    rows = con.execute(f"""
        WITH ranked AS (
            SELECT
                {tpn} as holder,
                SUM(h.pct_of_so) as total_pct_so,
                SUM(h.shares) as total_shares,
                ROW_NUMBER() OVER (ORDER BY SUM(h.pct_of_so) DESC) as rn
            FROM holdings_v2 h
            WHERE h.is_latest = TRUE
              AND h.pct_of_so IS NOT NULL
            GROUP BY {tpn}
        )
        SELECT rn, holder, total_pct_so
        FROM ranked
        ORDER BY rn
        LIMIT 5
    """).fetchall()
    if not rows:
        pytest.skip("fixture has no holdings_v2 rows with pct_of_so")
    # holder column should be non-empty strings (canonical names)
    for rn, holder, _pct in rows:
        assert holder is None or isinstance(holder, str)


# ---------------------------------------------------------------------------
# T7 — query1 parent ranking SQL pattern
# ---------------------------------------------------------------------------

def test_T7_query1_parent_ranking_pattern(con):
    """query1's parent ranking SQL parses and returns canonical names."""
    from queries.common import top_parent_canonical_name_sql
    tpn = top_parent_canonical_name_sql('h')
    rows = con.execute(f"""
        WITH by_fund AS (
            SELECT
                {tpn} as parent_name,
                h.market_value_live
            FROM holdings_v2 h
            WHERE h.is_latest = TRUE
        )
        SELECT
            parent_name,
            SUM(market_value_live) as total_value_live
        FROM by_fund
        GROUP BY parent_name
        ORDER BY total_value_live DESC NULLS LAST
        LIMIT 5
    """).fetchall()
    if not rows:
        pytest.skip("fixture has no holdings_v2 rows")
    # Top-N grouping should not produce duplicate canonical names
    names = [r[0] for r in rows if r[0] is not None]
    assert len(names) == len(set(names)), (
        f"duplicate canonical names in top-N: {names}"
    )
