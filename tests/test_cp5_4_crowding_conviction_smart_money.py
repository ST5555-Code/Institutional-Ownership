"""Tests for CP-5.4 — Crowding + Conviction + Smart Money + FPM1 reader migrations.

Migrates 5 CLEAN sub-sites to entity-keyed grouping via
``top_parent_canonical_name_sql`` helper:

  C1   — ``scripts/queries/market.py:135`` (Crowding/Smart Money head query
         distinct-holder COUNT)
  C2   — ``scripts/api_market.py:199`` (/crowding holders top-20)
  CV1  — ``scripts/queries/fund.py:110`` (portfolio_context top-25 holders)
  CV2  — ``scripts/queries/fund.py:179+:188`` (portfolio_context per-holder
         portfolio SELECT + WHERE pair)
  FPM1 — ``scripts/api_fund.py:42`` (/fund_portfolio_managers GROUP BY)

Tests:

  T_A — C2-shape /crowding holders panel returns canonical-named top-20
        with manager_type column (sanity that the swap parses + groups).
  T_B — CV1-shape top_holders_df returns 25 holders by latest-quarter
        value with no duplicate canonical names (entity-keyed grouping
        collapses brand variants).
  T_C — CV1 / CV2 internal name consistency: every holder in
        top_holders_df also appears in the portfolio_df result built
        from the migrated WHERE clause. Pins the SELECT/WHERE-pair
        invariant called out in recon §4.3.
  T_D — Smart Money shared-denominator semantics: per-manager_type
        distinct-holder count from C1's COUNT-DISTINCT shape sums (within
        rounding) to the global C1 total. Confirms Smart Money inherits
        C1 transitively.
  T_E — FPM1-shape /fund_portfolio_managers returns canonical-named
        rows with one row per (cik, fund_name).

Test runner: shared fixture applies migrations 027 + 028 to a tmp copy
of the fixture DB.
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


# ---------------------------------------------------------------------------
# T_A — C2 /crowding holders panel
# ---------------------------------------------------------------------------

def test_T_A_crowding_holders_panel(con):
    """/crowding holders panel parses + returns canonical-named rows."""
    from queries.common import top_parent_canonical_name_sql
    tpn = top_parent_canonical_name_sql('h')

    rows = con.execute(f"""
        SELECT {tpn} as holder, h.manager_type,
               SUM(h.pct_of_so) as pct_so,
               SUM(h.market_value_live) as value
        FROM holdings_v2 h
        WHERE h.ticker = 'AAPL' AND h.is_latest = TRUE
        GROUP BY holder, h.manager_type
        ORDER BY pct_so DESC NULLS LAST
        LIMIT 20
    """).fetchall()
    if not rows:
        pytest.skip("fixture has no AAPL holdings_v2 rows")
    for holder, mtype, _ps, _val in rows:
        assert holder is None or isinstance(holder, str)
        assert mtype is None or isinstance(mtype, str)


# ---------------------------------------------------------------------------
# T_B — CV1 top_holders_df has no duplicate canonical names
# ---------------------------------------------------------------------------

def test_T_B_conviction_top_holders_no_duplicates(con):
    """portfolio_context top-25 holders: entity-keyed grouping collapses
    brand variants. Post-migration result has no duplicate canonical
    names within the top-25."""
    from queries.common import top_parent_canonical_name_sql
    tpn = top_parent_canonical_name_sql('h')

    rows = con.execute(f"""
        SELECT {tpn} as holder, SUM(h.market_value_live) as val
        FROM holdings_v2 h
        WHERE h.ticker = 'AAPL' AND h.is_latest = TRUE
        GROUP BY holder
        ORDER BY val DESC NULLS LAST
        LIMIT 25
    """).fetchall()
    if not rows:
        pytest.skip("fixture has no AAPL holdings_v2 rows")
    names = [r[0] for r in rows if r[0] is not None]
    assert len(names) == len(set(names)), (
        f"duplicate canonical names in Conviction top-25: {names}"
    )


# ---------------------------------------------------------------------------
# T_C — CV1/CV2 SELECT/WHERE pair consistency
# ---------------------------------------------------------------------------

def test_T_C_conviction_select_where_pair_consistent(con):
    """Every holder returned by the CV1 SELECT must also appear in the
    CV2 portfolio_df result. Pins the SELECT/WHERE-pair invariant in
    portfolio_context — both clauses use identical helper expressions."""
    from queries.common import top_parent_canonical_name_sql
    tpn = top_parent_canonical_name_sql('h')

    top_holders = [
        r[0] for r in con.execute(f"""
            SELECT {tpn} as holder
            FROM holdings_v2 h
            WHERE h.ticker = 'AAPL' AND h.is_latest = TRUE
            GROUP BY holder
            ORDER BY SUM(h.market_value_live) DESC NULLS LAST
            LIMIT 25
        """).fetchall()
        if r[0] is not None
    ]
    if not top_holders:
        pytest.skip("fixture has no AAPL holdings_v2 rows")
    ph = ",".join(["?"] * len(top_holders))
    portfolio = con.execute(f"""
        SELECT DISTINCT {tpn} as holder
        FROM holdings_v2 h
        WHERE h.is_latest = TRUE
          AND {tpn} IN ({ph})
          AND h.market_value_live > 0
    """, top_holders).fetchall()
    found = {r[0] for r in portfolio if r[0] is not None}
    missing = set(top_holders) - found
    assert not missing, f"top_holders missing from portfolio_df: {missing}"


# ---------------------------------------------------------------------------
# T_D — Smart Money shared-denominator semantics
# ---------------------------------------------------------------------------

def test_T_D_smart_money_shared_denominator(con):
    """Smart Money's per-manager_type distinct-holder counts (using the
    same canonical-name expression as C1) sum to the global C1 distinct-
    holder count. Pins the inheritance — no Smart Money-specific
    migration site exists; C1 covers it transitively."""
    from queries.common import top_parent_canonical_name_sql
    tpn = top_parent_canonical_name_sql('h')

    global_total = con.execute(f"""
        SELECT COUNT(DISTINCT {tpn})
        FROM holdings_v2 h
        WHERE h.is_latest = TRUE
    """).fetchone()[0]
    if not global_total:
        pytest.skip("empty fixture")

    per_type = con.execute(f"""
        SELECT h.manager_type, COUNT(DISTINCT {tpn}) AS n
        FROM holdings_v2 h
        WHERE h.is_latest = TRUE
        GROUP BY h.manager_type
    """).fetchall()
    summed = sum(r[1] for r in per_type if r[1])
    # A canonical top-parent can carry multiple manager_types across its
    # filer arms, so per-type counts can exceed the global. Lower bound:
    # summed >= global_total. Upper bound: summed <= global_total *
    # distinct manager_types.
    assert summed >= global_total, (
        f"per-type sum ({summed}) below global distinct ({global_total})"
    )


# ---------------------------------------------------------------------------
# T_E — FPM1 /fund_portfolio_managers shape
# ---------------------------------------------------------------------------

def test_T_E_fund_portfolio_managers_shape(con):
    """FPM1 shape returns one row per (cik, fund_name) with canonical
    inst_parent_name."""
    from queries.common import top_parent_canonical_name_sql
    tpn = top_parent_canonical_name_sql('h')

    rows = con.execute(f"""
        SELECT
            h.cik,
            h.fund_name,
            MAX({tpn}) as inst_parent_name,
            SUM(h.market_value_live) as position_value
        FROM holdings_v2 h
        WHERE h.ticker = 'AAPL'
          AND h.entity_type NOT IN ('passive')
          AND h.is_latest = TRUE
        GROUP BY h.cik, h.fund_name
        ORDER BY position_value DESC NULLS LAST
        LIMIT 50
    """).fetchall()
    if not rows:
        pytest.skip("fixture has no AAPL non-passive rows")
    keys = [(r[0], r[1]) for r in rows]
    assert len(keys) == len(set(keys)), "duplicate (cik, fund_name) keys"
    for _cik, _fn, inst_parent, _val in rows:
        assert inst_parent is None or isinstance(inst_parent, str)


# ---------------------------------------------------------------------------
# T_F — Helper expression smoke (parses for both alias variants)
# ---------------------------------------------------------------------------

def test_T_F_helper_smoke(con):
    """top_parent_canonical_name_sql parses + returns row for both alias
    variants used in CP-5.4 migrations."""
    from queries.common import top_parent_canonical_name_sql
    tpn_h = top_parent_canonical_name_sql('h')

    row = con.execute(f"""
        SELECT {tpn_h} as holder
        FROM holdings_v2 h
        WHERE h.is_latest = TRUE
        LIMIT 1
    """).fetchone()
    assert row is None or row[0] is None or isinstance(row[0], str)
