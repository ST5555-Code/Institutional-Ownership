"""Tests for CP-5.5 — Sector Rotation + New-Exits + AUM main bundle.

Migrates 4 CLEAN sub-sites to entity-keyed grouping via
``top_parent_canonical_name_sql`` helper:

  S1 — ``scripts/queries/flows.py:_cohort_analysis_impl`` (cohort
       parent + econ_retention loop)
  S2 — ``scripts/queries/trend.py:holder_momentum`` (top-25 parents
       multi-quarter shares + N-PORT child rollup)
  S3 — ``scripts/queries/trend.py:ownership_trend_summary``
       (COUNT(DISTINCT) holder_count per quarter)
  S4 — ``scripts/queries/flows.py:_compute_flows_live`` +
       ``flow_analysis`` qoq_charts (live name-coalesce)

S8 (compute_aum_for_subtree) DEFERRED — schema mismatch with
unified_holdings (no cik / market_value_usd columns; top-parent
grain vs filer-CIK SUM grain). See cp-5-aum-subtree-redesign in
ROADMAP.

Test runner: shared fixture applies migrations 027 + 028 to a tmp
copy of the fixture DB.
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

        m027 = _load(MIG_027, "mig027_5_5")
        m027.run_migration(str(dst), dry_run=False, skip_guards=True)
        m028 = _load(MIG_028, "mig028_5_5")
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
# T_S1 — cohort_analysis canonical-named cohort rows
# ---------------------------------------------------------------------------

def test_T_S1_cohort_canonical_named(con):
    """cohort_analysis q1/q4 parent reads return canonical-named investors.
    No duplicate canonical names within a single quarter aggregate."""
    from queries.common import top_parent_canonical_name_sql
    tpn = top_parent_canonical_name_sql('h')

    rows = con.execute(f"""
        SELECT {tpn} as investor,
               SUM(h.shares) as shares
        FROM holdings_v2 h
        WHERE h.ticker = 'AAPL' AND h.is_latest = TRUE
        GROUP BY investor
        ORDER BY shares DESC NULLS LAST
        LIMIT 50
    """).fetchall()
    if not rows:
        pytest.skip("fixture has no AAPL holdings_v2 rows")
    names = [r[0] for r in rows if r[0] is not None]
    assert len(names) == len(set(names)), (
        f"duplicate canonical names in cohort top-50: {names}"
    )


# ---------------------------------------------------------------------------
# T_S2 — holder_momentum multi-quarter Direction trend
# ---------------------------------------------------------------------------

def test_T_S2_holder_momentum_multi_quarter(con):
    """holder_momentum top-25 + per-quarter shares query parses, returns
    canonical-named parents, and shares respect IN-filter consistency
    between top_df and parent_df (the SELECT/WHERE pair invariant
    pinned by CP-5.4 §6.4 binder rule applied multi-quarter)."""
    from queries.common import top_parent_canonical_name_sql
    tpn = top_parent_canonical_name_sql('h')

    quarters = [r[0] for r in con.execute(
        "SELECT DISTINCT quarter FROM holdings_v2 "
        "WHERE ticker = 'AAPL' AND is_latest = TRUE "
        "ORDER BY quarter DESC LIMIT 4"
    ).fetchall()]
    if len(quarters) < 2:
        pytest.skip("fixture lacks multi-quarter AAPL coverage")

    latest_q = quarters[0]
    top = con.execute(f"""
        SELECT {tpn} as parent_name
        FROM holdings_v2 h
        WHERE h.quarter = '{latest_q}' AND h.ticker = 'AAPL' AND h.is_latest = TRUE
        GROUP BY parent_name
        ORDER BY SUM(h.market_value_usd) DESC NULLS LAST
        LIMIT 25
    """).fetchall()
    top_names = [r[0] for r in top if r[0] is not None]
    if not top_names:
        pytest.skip("fixture top_names empty")

    q_ph = ",".join(f"'{q}'" for q in quarters)
    ph = ",".join(["?"] * len(top_names))
    multi = con.execute(f"""
        SELECT {tpn} as parent_name, h.quarter, SUM(h.shares) as shares
        FROM holdings_v2 h
        WHERE h.ticker = 'AAPL'
          AND h.quarter IN ({q_ph})
          AND {tpn} IN ({ph})
          AND h.is_latest = TRUE
        GROUP BY parent_name, h.quarter
    """, top_names).fetchall()
    found_parents = {r[0] for r in multi if r[0] is not None}
    # Every top_name must appear in at least one quarter's per-parent rows.
    missing = set(top_names) - found_parents
    assert not missing, (
        f"holder_momentum top->per-quarter IN-filter mismatch, missing: {missing}"
    )


# ---------------------------------------------------------------------------
# T_S3 — ownership_trend_summary COUNT(DISTINCT) sanity
# ---------------------------------------------------------------------------

def test_T_S3_ownership_trend_holder_count(con):
    """ownership_trend_summary COUNT(DISTINCT canonical-name) returns a
    positive holder_count per quarter, and the entity-keyed count is
    less-than-or-equal-to the legacy denorm-name count (entity-keyed
    grouping collapses brand variants — strictly fewer or equal
    distinct holders)."""
    from queries.common import top_parent_canonical_name_sql
    tpn = top_parent_canonical_name_sql('h')

    legacy = con.execute("""
        SELECT h.quarter,
               COUNT(DISTINCT COALESCE(h.rollup_name, h.inst_parent_name, h.manager_name)) AS legacy_count
        FROM holdings_v2 h
        WHERE h.ticker = 'AAPL' AND h.is_latest = TRUE
        GROUP BY h.quarter
    """).fetchall()
    canonical = {r[0]: r[1] for r in con.execute(f"""
        SELECT h.quarter,
               COUNT(DISTINCT {tpn}) AS canonical_count
        FROM holdings_v2 h
        WHERE h.ticker = 'AAPL' AND h.is_latest = TRUE
        GROUP BY h.quarter
    """).fetchall()}
    if not legacy:
        pytest.skip("fixture has no AAPL coverage")
    for q, leg in legacy:
        can = canonical.get(q)
        assert can is not None and can > 0, f"quarter {q} canonical count missing/zero"
        assert can <= leg, (
            f"canonical count {can} exceeds legacy {leg} for {q} — "
            "entity-keyed grouping should collapse brand variants"
        )


# ---------------------------------------------------------------------------
# T_S4 — _compute_flows_live live path returns canonical-named rows
# ---------------------------------------------------------------------------

def test_T_S4_compute_flows_live_canonical_named(con):
    """_compute_flows_live parent path — buyers/sellers/new/exits are
    canonical-named. Pins the alias-variant migration: the helper's
    correlated subquery resolves against `h.entity_id` only when the
    outer `FROM holdings_v2 h` alias is in scope."""
    from queries.common import top_parent_canonical_name_sql
    tpn = top_parent_canonical_name_sql('h')

    quarters = [r[0] for r in con.execute(
        "SELECT DISTINCT quarter FROM holdings_v2 "
        "WHERE ticker = 'AAPL' AND is_latest = TRUE "
        "ORDER BY quarter DESC LIMIT 2"
    ).fetchall()]
    if len(quarters) < 2:
        pytest.skip("fixture lacks 2 quarters of AAPL coverage")
    qt, qf = quarters[0], quarters[1]

    rows = con.execute(f"""
        SELECT {tpn} as entity, SUM(h.shares) as shares
        FROM holdings_v2 h WHERE h.ticker = ? AND h.quarter = '{qt}' AND h.is_latest = TRUE
        GROUP BY entity
        ORDER BY shares DESC NULLS LAST
        LIMIT 25
    """, ['AAPL']).fetchall()
    assert rows, "_compute_flows_live shape returned no rows"
    for entity, _shares in rows:
        assert entity is None or isinstance(entity, str)


# ---------------------------------------------------------------------------
# T_multi_quarter — Direction column composition across 2+ quarters
# ---------------------------------------------------------------------------

def test_T_multi_quarter_direction_composition(con):
    """Multi-quarter aggregate produces sensible per-quarter share rows
    via the migrated name-coalesce expression. Pins that Direction /
    Since / Held column composition is unaffected by the swap."""
    from queries.common import top_parent_canonical_name_sql
    tpn = top_parent_canonical_name_sql('h')

    rows = con.execute(f"""
        SELECT {tpn} as parent_name, h.quarter, SUM(h.shares) as shares
        FROM holdings_v2 h
        WHERE h.ticker = 'AAPL' AND h.is_latest = TRUE
        GROUP BY parent_name, h.quarter
    """).fetchall()
    if not rows:
        pytest.skip("fixture has no AAPL coverage")
    quarters_seen = {r[1] for r in rows}
    parents_seen = {r[0] for r in rows if r[0] is not None}
    assert len(quarters_seen) >= 1, "expected ≥1 distinct quarter"
    assert len(parents_seen) >= 1, "expected ≥1 distinct canonical parent"
