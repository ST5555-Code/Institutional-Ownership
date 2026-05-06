#!/usr/bin/env python3
# pylint: disable=invalid-name  # migration files follow NNN_description.py convention
"""Migration 027 — unified_holdings + inst_to_top_parent views (CP-5.1).

Foundation for CP-5 reader migrations. Adds two read-only views:

* ``inst_to_top_parent`` — recursive CTE that climbs every entity up
  the ownership graph (``entity_relationships`` rows where
  ``control_type IN ('control','mutual','merge')``) to its top parent,
  with deterministic tie-break ``ARG_MAX(top_parent, ROW(hops, -top_parent))``
  (highest hops, then smallest entity_id at that depth). Walks
  excluding ``advisory`` (sponsor layer) per the two-relationship-layer
  coexistence pattern (PR #287).

* ``unified_holdings`` — per-(top_parent_entity_id, cusip, ticker)
  aggregate combining 13F (``holdings_v2``) and fund-tier
  (``fund_holdings_v2`` via ``decision_maker_v1`` ERH JOIN) legs.
  Implements the modified R5 rule from
  docs/findings/cp-5-bundle-a-discovery.md §1.4:

  ``r5_aum = GREATEST(thirteen_f_aum, fund_tier_aum)``

  Bundle A §1.4 specified an intra-family FoF subtraction on the
  fund-tier leg, but the data model does not currently support it:
  fund entities lack CUSIP identifiers in ``entity_identifiers`` (they
  carry ``series_id`` and rare ``cik`` only), so there is no canonical
  CUSIP→fund-entity path. The CTE was therefore removed before
  shipping. Tracked as P2 follow-up
  ``cp-5-fof-subtraction-cusip-linkage`` (build the bridge then
  re-introduce the subtraction).

Design decisions (from chat 2026-05-05):
  Q1 — recursive CTE inline, no precomputed climb table.
  Q2 — ``is_latest = TRUE`` pinned (parameterized variant deferred).
       The view sums across all ``is_latest=TRUE`` rows, which spans
       multiple quarters. Readers that need single-quarter slices must
       continue to filter against the source tables directly until a
       parameterized variant lands in a follow-up.
  Q3 — suffix per codebase precedent.
  Q4 — ``top_parent_holdings_join()`` helper in scripts/queries/common.py.
  Q5 — intra-family FoF subtraction only (no other adjustments).

Climb anchor: every ``entities`` row, regardless of entity_type. Funds,
institutions, and other types are all valid climb starting points; the
recursive step only walks up via the 3 ownership-layer ``control_type``
values, so non-institutional anchors that have no incoming ownership
edges simply self-rollup at hops=0.

Hard guards (post-migration):
  G1 — ``SELECT COUNT(*) FROM inst_to_top_parent`` ≥ ``COUNT(*) FROM entities``
       (every entity is its own anchor; some have additional climb rows).
  G2 — ``SELECT COUNT(DISTINCT entity_id) FROM inst_to_top_parent``
       = ``COUNT(*) FROM entities`` (every entity climbed).
  G3 — No climber reaches hops=10 (cycle detection: pre-existing cycles
       were merged in PR #285; this guard catches future re-introductions).
  G4 — Capital Group umbrella eid 12 attracts at least 3 climbers from
       its known wholly_owned arms (eid 6657, 7125, 7136 per PR #287).
  G5 — ``SELECT COUNT(*) FROM unified_holdings`` > 0 (smoke test).

Idempotent: each view is dropped + re-created. Forward-only per standard
policy. View-only migration: zero row mutations.

Usage::

    python3 scripts/migrations/027_unified_holdings_view.py --dry-run
    python3 scripts/migrations/027_unified_holdings_view.py --prod
    python3 scripts/migrations/027_unified_holdings_view.py --staging
"""
from __future__ import annotations

import argparse
import os

import duckdb


VERSION = "027_unified_holdings_view"
NOTES = (
    "create inst_to_top_parent + unified_holdings views "
    "(CP-5.1 foundation; recursive ownership climb + R5 cross-source "
    "aggregate; Method A canonical reads via decision_maker_v1 ERH JOIN)"
)

# Reusable CTE fragment for the recursive ownership climb. Used inside
# the view DDL only — exposed to readers via the inst_to_top_parent
# view, not via raw SQL surface.
_ENTITY_CLIMB_DDL = """
CREATE OR REPLACE VIEW inst_to_top_parent AS
WITH RECURSIVE entity_climb AS (
    -- Anchor: every entity is its own climber at hops=0.
    SELECT
        entity_id AS climber_entity_id,
        entity_id AS top_parent,
        0 AS hops
    FROM entities

    UNION ALL

    -- Recursive step: walk up via control/mutual/merge edges.
    -- Excludes advisory (sponsor layer) per
    -- project_two_relationship_layer_coexistence pattern (PR #287).
    SELECT
        ec.climber_entity_id,
        er.parent_entity_id AS top_parent,
        ec.hops + 1
    FROM entity_climb ec
    JOIN entity_relationships er
        ON er.child_entity_id = ec.top_parent
    WHERE er.valid_to = DATE '9999-12-31'
        AND er.control_type IN ('control', 'mutual', 'merge')
        AND ec.hops < 10
)
SELECT
    climber_entity_id AS entity_id,
    -- Deterministic tie-break: highest hops, then smallest top_parent
    -- eid at that depth (mutual-control cycles produce tied hops; the
    -- -top_parent component picks the lower eid for stability).
    ARG_MAX(top_parent, ROW(hops, -top_parent))
        AS top_parent_entity_id,
    MAX(hops) AS hops_at_top
FROM entity_climb
GROUP BY climber_entity_id
"""

_UNIFIED_HOLDINGS_DDL = """
CREATE OR REPLACE VIEW unified_holdings AS
WITH thirteen_f_leg AS (
    SELECT
        ittp.top_parent_entity_id,
        h.cusip,
        h.ticker,
        SUM(h.market_value_usd) / 1e9 AS thirteen_f_aum_b
    FROM holdings_v2 h
    JOIN inst_to_top_parent ittp
        ON ittp.entity_id = h.entity_id
    WHERE h.is_latest = TRUE
    GROUP BY 1, 2, 3
),
-- Fund-tier leg via Method A (read-time decision_maker_v1 ERH JOIN,
-- canonical per PR #280) → entity climb to top parent. Bundle A §1.4
-- specified an intra-family FoF subtraction here, but the data model
-- has no CUSIP→fund-entity bridge today (fund entities carry
-- series_id, not cusip, in entity_identifiers), so the subtraction
-- ships as a no-op and fund_tier_aum_b is the raw rollup. Tracked as
-- P2 follow-up cp-5-fof-subtraction-cusip-linkage.
fund_tier_leg AS (
    SELECT
        ittp.top_parent_entity_id,
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
    GROUP BY 1, 2, 3
)
SELECT
    COALESCE(t.top_parent_entity_id, f.top_parent_entity_id)
        AS top_parent_entity_id,
    e.canonical_name AS top_parent_name,
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


def _run_hard_guards(con) -> None:
    """Run G1..G5 post-creation guards. Raises SystemExit on any failure."""
    n_entities = con.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
    n_climb = con.execute(
        "SELECT COUNT(*) FROM inst_to_top_parent"
    ).fetchone()[0]
    n_distinct = con.execute(
        "SELECT COUNT(DISTINCT entity_id) FROM inst_to_top_parent"
    ).fetchone()[0]
    n_cycles = con.execute(
        "SELECT COUNT(*) FROM inst_to_top_parent WHERE hops_at_top = 10"
    ).fetchone()[0]
    n_cap_group = con.execute("""
        SELECT COUNT(*) FROM inst_to_top_parent
        WHERE entity_id IN (6657, 7125, 7136)
          AND top_parent_entity_id = 12
    """).fetchone()[0]
    n_unified = con.execute(
        "SELECT COUNT(*) FROM unified_holdings"
    ).fetchone()[0]

    print(f"  G1 entities count:                      {n_entities:,}")
    print(f"  G1 inst_to_top_parent rows:           {n_climb:,}")
    print(f"  G2 distinct climber entity_ids:         {n_distinct:,}")
    print(f"  G3 climbers reaching hops=10 (cycles):  {n_cycles}")
    print(f"  G4 Capital Group arms -> umbrella 12:   {n_cap_group} of 3")
    print(f"  G5 unified_holdings rows:               {n_unified:,}")

    if n_climb < n_entities:
        raise SystemExit(
            f"  GUARD G1 FAILED: inst_to_top_parent rows "
            f"({n_climb:,}) < entities ({n_entities:,})"
        )
    if n_distinct != n_entities:
        raise SystemExit(
            f"  GUARD G2 FAILED: distinct climbers ({n_distinct:,}) "
            f"!= entities ({n_entities:,})"
        )
    if n_cycles > 0:
        raise SystemExit(
            f"  GUARD G3 FAILED: {n_cycles} climbers reached hops=10 "
            "— cycle re-introduced post PR #285. Investigate "
            "entity_relationships before unblocking this migration."
        )
    if n_cap_group != 3:
        raise SystemExit(
            f"  GUARD G4 FAILED: Capital Group climb covers "
            f"{n_cap_group}/3 arms (eid 6657/7125/7136 -> 12). "
            "Check PR #287 wholly_owned bridges remain open."
        )
    if n_unified == 0:
        raise SystemExit(
            "  GUARD G5 FAILED: unified_holdings is empty"
        )


def run_migration(db_path: str, dry_run: bool,
                  skip_guards: bool = False) -> None:
    """Apply migration 027 to ``db_path``. ``--dry-run`` reports only.

    ``skip_guards`` (test-only) skips the G1..G5 hard guards. Used by
    tests against the fixture DB, which pre-dates PR #285 (cycle
    truncation) and PR #287 (Capital Group bridges) and would
    legitimately fail G3/G4 on stale relationship data. The guards
    still run on every prod/staging invocation through the CLI.
    """
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
            "entity_identifiers",
            "holdings_v2",
            "fund_holdings_v2",
        ):
            if not _has_table(con, tbl):
                raise SystemExit(
                    f"  MIGRATION FAILED: required table {tbl} missing"
                )

        stamped = _already_stamped(con, VERSION)
        existed_climb = _has_view(con, "inst_to_top_parent")
        existed_unified = _has_view(con, "unified_holdings")

        print(f"  inst_to_top_parent BEFORE: "
              f"{'PRESENT' if existed_climb else 'ABSENT'}")
        print(f"  unified_holdings BEFORE:     "
              f"{'PRESENT' if existed_unified else 'ABSENT'}")
        print(f"  schema_versions stamped:     {stamped}")

        if dry_run:
            print("  Would execute:")
            print("    CREATE OR REPLACE VIEW inst_to_top_parent AS …")
            print("    CREATE OR REPLACE VIEW unified_holdings AS …")
            print("    Run G1..G5 hard guards.")
            if not stamped:
                print(f"    INSERT schema_versions: {VERSION}")
            print("  DRY-RUN: no writes performed")
            return

        print("  Creating inst_to_top_parent …")
        con.execute(_ENTITY_CLIMB_DDL)

        print("  Creating unified_holdings …")
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
        print("  migration 027 applied successfully")
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
