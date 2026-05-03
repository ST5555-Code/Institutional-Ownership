"""CP-4b discovery — Phase 1 inventory.

Read-only investigation. Recomputes invisible-brand cohort split
(TRUE_BRIDGE_ENCODED vs AUTHOR_NEW_BRIDGE) directly from prod
DuckDB at runtime, since prior eid_inventory.csv snapshots have
drifted.

Refs docs/decisions/inst_eid_bridge_decisions.md (CP-4b sequencing).
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb

DB_PATH = "/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership/data/13f.duckdb"
SENTINEL = "DATE '9999-12-31'"


def main() -> int:
    con = duckdb.connect(DB_PATH, read_only=True)

    # --- sanity gates ---
    sentinel_count = con.execute(
        "SELECT COUNT(*) FROM entity_relationships "
        f"WHERE valid_to = {SENTINEL}"
    ).fetchone()[0]
    if sentinel_count == 0:
        print(f"ABORT: entity_relationships sentinel missing", file=sys.stderr)
        return 2

    adv_n = con.execute("SELECT COUNT(*) FROM adv_managers").fetchone()[0]
    if adv_n < 1000:
        print(f"ABORT: adv_managers too small ({adv_n})", file=sys.stderr)
        return 2

    print(f"adv_managers rows: {adv_n:,}")
    print(f"entity_relationships open rows: {sentinel_count:,}")
    print()

    # --- (a) invisible brand universe ---
    invisible_sql = f"""
    WITH brand_universe AS (
        SELECT
            dm_rollup_entity_id AS eid,
            SUM(market_value_usd) AS fund_aum
        FROM fund_holdings_v2
        WHERE is_latest = TRUE
          AND dm_rollup_entity_id IS NOT NULL
        GROUP BY dm_rollup_entity_id
    ),
    visible_filers AS (
        SELECT DISTINCT entity_id AS eid
        FROM holdings_v2
        WHERE is_latest = TRUE
          AND entity_id IS NOT NULL
        UNION
        SELECT DISTINCT dm_rollup_entity_id AS eid
        FROM holdings_v2
        WHERE is_latest = TRUE
          AND dm_rollup_entity_id IS NOT NULL
    )
    SELECT
        bu.eid,
        bu.fund_aum
    FROM brand_universe bu
    LEFT JOIN visible_filers vf ON bu.eid = vf.eid
    WHERE vf.eid IS NULL
    """
    invisible = con.execute(invisible_sql).fetchdf()
    print(f"invisible brands (no holdings_v2 entity_id match): {len(invisible):,}")
    print(f"  fund AUM exposure: ${invisible['fund_aum'].sum() / 1e12:,.2f}T")
    print()

    # --- visible filer set as a temp staging table for the bridge join ---
    con.execute("CREATE TEMP TABLE _vis_filers AS "
                "SELECT DISTINCT entity_id AS eid FROM holdings_v2 "
                "WHERE is_latest = TRUE AND entity_id IS NOT NULL "
                "UNION "
                "SELECT DISTINCT dm_rollup_entity_id AS eid FROM holdings_v2 "
                "WHERE is_latest = TRUE AND dm_rollup_entity_id IS NOT NULL")
    con.register("invisible_df", invisible)
    con.execute("CREATE OR REPLACE TEMP TABLE _invisible AS SELECT * FROM invisible_df")

    # --- (b) bridge classification ---
    bridge_sql = f"""
    WITH inv AS (SELECT eid, fund_aum FROM _invisible),
         bridges AS (
             SELECT DISTINCT
                 CASE WHEN er.parent_entity_id IN (SELECT eid FROM inv) THEN er.parent_entity_id
                      WHEN er.child_entity_id  IN (SELECT eid FROM inv) THEN er.child_entity_id
                 END AS brand_eid,
                 CASE WHEN er.parent_entity_id IN (SELECT eid FROM inv) THEN er.child_entity_id
                      WHEN er.child_entity_id  IN (SELECT eid FROM inv) THEN er.parent_entity_id
                 END AS counterparty_eid
             FROM entity_relationships er
             WHERE er.valid_to = {SENTINEL}
               AND (er.parent_entity_id IN (SELECT eid FROM inv)
                    OR er.child_entity_id  IN (SELECT eid FROM inv))
         ),
         visible_bridges AS (
             SELECT DISTINCT b.brand_eid
             FROM bridges b
             JOIN _vis_filers vf ON b.counterparty_eid = vf.eid
         )
    SELECT
        inv.eid,
        inv.fund_aum,
        CASE WHEN vb.brand_eid IS NOT NULL THEN 'TRUE_BRIDGE_ENCODED'
             ELSE 'AUTHOR_NEW_BRIDGE'
        END AS cohort
    FROM inv
    LEFT JOIN visible_bridges vb ON inv.eid = vb.brand_eid
    """
    classified = con.execute(bridge_sql).fetchdf()

    by_cohort = classified.groupby("cohort").agg(
        n=("eid", "count"), aum=("fund_aum", "sum")
    ).reset_index()
    print("cohort split:")
    for _, row in by_cohort.iterrows():
        print(f"  {row['cohort']:>22s}: n={row['n']:>5,}  aum=${row['aum']/1e12:>6,.2f}T")
    print()

    # --- (d) top-20 AUTHOR_NEW_BRIDGE by fund AUM ---
    con.register("classified_df", classified)
    top20_sql = """
    WITH ec_uniq AS (
        SELECT entity_id, ANY_VALUE(display_name) AS display_name,
               ANY_VALUE(entity_type) AS entity_type
        FROM entity_current GROUP BY entity_id
    )
    SELECT
        c.eid,
        c.fund_aum,
        ec.display_name,
        ec.entity_type,
        (SELECT identifier_value
           FROM entity_identifiers ei
          WHERE ei.entity_id = c.eid
            AND ei.identifier_type = 'cik'
            AND (ei.valid_to IS NULL OR ei.valid_to >= CURRENT_DATE)
          ORDER BY ei.valid_from DESC
          LIMIT 1) AS cik
    FROM classified_df c
    LEFT JOIN ec_uniq ec ON ec.entity_id = c.eid
    WHERE c.cohort = 'AUTHOR_NEW_BRIDGE'
    ORDER BY c.fund_aum DESC
    LIMIT 20
    """
    top20 = con.execute(top20_sql).fetchdf()
    print("=== Top-20 AUTHOR_NEW_BRIDGE by fund AUM ===")
    print(top20.to_string())

    # write CSV for Phase 2 consumption
    out_path = Path("data/working/cp-4b-top20-input.csv")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    top20.to_csv(out_path, index=False)
    print(f"\nwrote {out_path}")

    # cohort summary CSV
    summary_path = Path("data/working/cp-4b-cohort-summary.csv")
    by_cohort.to_csv(summary_path, index=False)
    print(f"wrote {summary_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
