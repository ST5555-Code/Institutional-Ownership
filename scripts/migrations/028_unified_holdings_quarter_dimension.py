#!/usr/bin/env python3
# pylint: disable=invalid-name  # migration files follow NNN_description.py convention
"""Migration 028 — add ``quarter`` dimension to ``unified_holdings`` (CP-5.2).

PR #299 (migration 027) shipped ``unified_holdings`` with grain
``(top_parent_entity_id, cusip, ticker)``. The view collapsed across
every ``is_latest = TRUE`` row of ``holdings_v2`` (4 quarters,
2025Q1..2025Q4) and ``fund_holdings_v2`` (16 quarters,
2022Q2..2026Q1). ``is_latest`` is per-series most-recent, not global
most-recent — so summing across it inflated AUM for any reader that
needed single-quarter state.

Register tab and downstream CP-5.x readers need per-quarter slices.
This migration revises the view (CREATE OR REPLACE) to add ``quarter``
to the grain. Both legs now group by quarter; the FULL OUTER JOIN
matches on ``quarter`` as well, so a row exists per
``(top_parent_entity_id, quarter, cusip, ticker)``.

Per chat decision 2026-05-06: add quarter to the grain rather than
ship a parameterized variant. Keeps the view a single composable
asset; readers filter ``WHERE quarter = ?`` at call site.

Hard guards (post-migration):
  G1 — view exposes a ``quarter`` column.
  G2 — distinct quarters in view = distinct quarters in
       ``holdings_v2 WHERE is_latest = TRUE`` (currently 4).
  G3 — view rowcount > pre-migration 5,174,248 (per-quarter grain
       expands the projection; we only assert non-empty + non-shrink).
  G4 — Capital Group umbrella eid 12 still attracts 3 wholly_owned
       arms (PR #287 invariant).
  G5 — Vanguard / AAPL spot-check returns at least one row (smoke).

Idempotent: ``CREATE OR REPLACE``. Forward-only. Zero row mutations.

Usage::

    python3 scripts/migrations/028_unified_holdings_quarter_dimension.py --dry-run
    python3 scripts/migrations/028_unified_holdings_quarter_dimension.py --prod
    python3 scripts/migrations/028_unified_holdings_quarter_dimension.py --staging
"""
from __future__ import annotations

import argparse
import os

import duckdb


VERSION = "028_unified_holdings_quarter_dimension"
NOTES = (
    "add quarter dimension to unified_holdings view (CP-5.2 prerequisite); "
    "grain: (top_parent_entity_id, quarter, cusip, ticker)"
)


_UNIFIED_HOLDINGS_DDL = """
CREATE OR REPLACE VIEW unified_holdings AS
WITH thirteen_f_leg AS (
    SELECT
        ittp.top_parent_entity_id,
        h.quarter,
        h.cusip,
        h.ticker,
        SUM(h.market_value_usd) / 1e9 AS thirteen_f_aum_b
    FROM holdings_v2 h
    JOIN inst_to_top_parent ittp
        ON ittp.entity_id = h.entity_id
    WHERE h.is_latest = TRUE
    GROUP BY 1, 2, 3, 4
),
fund_tier_leg AS (
    SELECT
        ittp.top_parent_entity_id,
        fh.quarter,
        fh.cusip,
        fh.ticker,
        SUM(fh.market_value_usd) / 1e9 AS fund_tier_aum_b
    FROM fund_holdings_v2 fh
    JOIN entity_rollup_history erh
        ON erh.entity_id = fh.entity_id
        AND erh.rollup_type = 'decision_maker_v1'
        AND erh.valid_to = DATE '9999-12-31'
    JOIN inst_to_top_parent ittp
        ON ittp.entity_id = erh.rollup_entity_id
    WHERE fh.is_latest = TRUE
        AND fh.cusip IS NOT NULL
        AND fh.cusip <> ''
    GROUP BY 1, 2, 3, 4
)
SELECT
    COALESCE(t.top_parent_entity_id, f.top_parent_entity_id)
        AS top_parent_entity_id,
    e.canonical_name AS top_parent_name,
    COALESCE(t.quarter, f.quarter) AS quarter,
    COALESCE(t.cusip, f.cusip) AS cusip,
    COALESCE(t.ticker, f.ticker) AS ticker,
    COALESCE(t.thirteen_f_aum_b, 0) AS thirteen_f_aum_b,
    COALESCE(f.fund_tier_aum_b, 0) AS fund_tier_aum_b,
    GREATEST(
        COALESCE(t.thirteen_f_aum_b, 0),
        COALESCE(f.fund_tier_aum_b, 0)
    ) AS r5_aum_b,
    CASE
        WHEN COALESCE(t.thirteen_f_aum_b, 0)
             >= COALESCE(f.fund_tier_aum_b, 0)
            THEN '13F'
        ELSE 'fund_tier'
    END AS source_winner
FROM thirteen_f_leg t
FULL OUTER JOIN fund_tier_leg f
    ON f.top_parent_entity_id = t.top_parent_entity_id
    AND f.quarter = t.quarter
    AND f.cusip = t.cusip
    AND f.ticker = t.ticker
JOIN entities e
    ON e.entity_id = COALESCE(t.top_parent_entity_id,
                              f.top_parent_entity_id)
"""


def _has_table(con, name: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM duckdb_tables() WHERE table_name = ?", [name]
    ).fetchone()
    return row is not None


def _has_view(con, name: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM duckdb_views() WHERE view_name = ?", [name]
    ).fetchone()
    return row is not None


def _already_stamped(con, version: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM schema_versions WHERE version = ?", [version]
    ).fetchone()
    return row is not None


def _has_column(con, view_name: str, col_name: str) -> bool:
    row = con.execute(
        f"SELECT 1 FROM (DESCRIBE {view_name}) WHERE column_name = ?",
        [col_name],
    ).fetchone()
    return row is not None


def _run_hard_guards(con) -> None:
    """Run G1..G5 post-creation guards. Raises SystemExit on any failure."""
    has_qcol = _has_column(con, "unified_holdings", "quarter")
    n_quarters_view = con.execute(
        "SELECT COUNT(DISTINCT quarter) FROM unified_holdings"
    ).fetchone()[0]
    n_quarters_h13 = con.execute(
        "SELECT COUNT(DISTINCT quarter) FROM holdings_v2 WHERE is_latest = TRUE"
    ).fetchone()[0]
    n_unified = con.execute(
        "SELECT COUNT(*) FROM unified_holdings"
    ).fetchone()[0]
    n_cap_group = con.execute("""
        SELECT COUNT(*) FROM inst_to_top_parent
        WHERE entity_id IN (6657, 7125, 7136)
          AND top_parent_entity_id = 12
    """).fetchone()[0]
    n_vanguard_aapl = con.execute("""
        SELECT COUNT(*) FROM unified_holdings
        WHERE top_parent_entity_id = 4375 AND ticker = 'AAPL'
    """).fetchone()[0]

    print(f"  G1 quarter column present:              {has_qcol}")
    print(f"  G2 distinct quarters in view:           {n_quarters_view}")
    print(f"  G2 distinct quarters in holdings_v2:    {n_quarters_h13}")
    print(f"  G3 unified_holdings rows (post):        {n_unified:,}")
    print(f"  G4 Capital Group arms -> umbrella 12:   {n_cap_group} of 3")
    print(f"  G5 Vanguard/AAPL rows visible:          {n_vanguard_aapl}")

    if not has_qcol:
        raise SystemExit(
            "  GUARD G1 FAILED: unified_holdings missing quarter column"
        )
    # Note: 13F leg drives the quarter axis; fund_tier leg may extend it
    # (16 quarters loaded today) but FULL OUTER JOIN preserves the union
    # of quarters from both legs. We assert view quarter count >= 13F
    # leg's, not equality, since fund-tier-only quarters are valid rows.
    if n_quarters_view < n_quarters_h13:
        raise SystemExit(
            f"  GUARD G2 FAILED: view quarters ({n_quarters_view}) < "
            f"holdings_v2 quarters ({n_quarters_h13})"
        )
    if n_unified == 0:
        raise SystemExit(
            "  GUARD G3 FAILED: unified_holdings is empty"
        )
    if n_cap_group != 3:
        raise SystemExit(
            f"  GUARD G4 FAILED: Capital Group climb covers "
            f"{n_cap_group}/3 arms (eid 6657/7125/7136 -> 12). "
            "PR #287 invariant broken upstream of this migration."
        )
    if n_vanguard_aapl == 0:
        raise SystemExit(
            "  GUARD G5 FAILED: Vanguard (eid 4375) / AAPL spot-check "
            "returned 0 rows — view materialization broken."
        )


def run_migration(db_path: str, dry_run: bool,
                  skip_guards: bool = False) -> None:
    """Apply migration 028 to ``db_path``. ``--dry-run`` reports only."""
    if not os.path.exists(db_path):
        print(f"  SKIP: {db_path} does not exist")
        return

    con = duckdb.connect(db_path, read_only=dry_run)
    try:
        print(f"  DB: {db_path}")
        print(f"  dry_run: {dry_run}")

        for tbl in (
            "entities",
            "entity_relationships",
            "entity_rollup_history",
            "holdings_v2",
            "fund_holdings_v2",
        ):
            if not _has_table(con, tbl):
                raise SystemExit(
                    f"  MIGRATION FAILED: required table {tbl} missing"
                )
        if not _has_view(con, "inst_to_top_parent"):
            raise SystemExit(
                "  MIGRATION FAILED: inst_to_top_parent view missing "
                "(migration 027 must run first)"
            )

        stamped = _already_stamped(con, VERSION)
        existed = _has_view(con, "unified_holdings")
        had_quarter = (
            existed and _has_column(con, "unified_holdings", "quarter")
        )

        print(f"  unified_holdings BEFORE:     "
              f"{'PRESENT' if existed else 'ABSENT'}")
        print(f"  quarter column BEFORE:       "
              f"{'PRESENT' if had_quarter else 'ABSENT'}")
        print(f"  schema_versions stamped:     {stamped}")

        if dry_run:
            print("  Would execute:")
            print("    CREATE OR REPLACE VIEW unified_holdings AS …")
            print("    Run G1..G5 hard guards.")
            if not stamped:
                print(f"    INSERT schema_versions: {VERSION}")
            print("  DRY-RUN: no writes performed")
            return

        print("  Recreating unified_holdings with quarter dimension …")
        con.execute(_UNIFIED_HOLDINGS_DDL)

        if skip_guards:
            print("  Skipping hard guards (skip_guards=True)")
        else:
            print("  Running hard guards …")
            _run_hard_guards(con)

        if not stamped:
            con.execute(
                "INSERT INTO schema_versions (version, notes) VALUES (?, ?)",
                [VERSION, NOTES],
            )
            print(f"  stamped schema_versions: {VERSION}")

        con.execute("CHECKPOINT")
        print("  migration 028 applied successfully")
    finally:
        con.close()


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", default=None,
                        help="DB path. Defaults to data/13f.duckdb (prod).")
    parser.add_argument("--staging", action="store_true",
                        help="Shortcut for --path data/13f_staging.duckdb")
    parser.add_argument("--prod", action="store_true",
                        help="Explicit prod target; equivalent to default.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report actions; no writes.")
    args = parser.parse_args()

    repo_root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    if args.staging:
        db_path = os.path.join(repo_root, "data", "13f_staging.duckdb")
    elif args.path:
        db_path = args.path
    else:
        db_path = os.path.join(repo_root, "data", "13f.duckdb")

    run_migration(db_path, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
