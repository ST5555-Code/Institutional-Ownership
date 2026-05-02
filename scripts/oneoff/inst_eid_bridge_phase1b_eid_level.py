"""inst-eid-bridge Phase 1b — Eid-level inventory (the real audit).

Read-only. No DB writes.

Phase 1 (CIK-keyed) found near-zero Mode B because fund_cik (N-PORT trust CIKs)
and holdings_v2.cik (13F filer adviser CIKs) are mutually exclusive populations
in this DB. The brand-vs-filer mismatch lives at the entity_id level, not the
CIK level.

This script reframes the audit per the PR #252 finding:
  - Mode A' (eid-level): brand_eid in fund_holdings_v2 absent from holdings_v2
                         (any join: entity_id, rollup_entity_id, dm_rollup_entity_id)
                         — these are "invisible institutions"
  - For each Mode A' brand_eid, find candidate filer_eid(s) via:
      (a) entity_aliases name overlap (canonical_name token matching)
      (b) entity_relationships parent-child link
      (c) entity_identifiers CIK overlap
  - Flag classes:
      BRAND_HAS_RELATIONSHIP: explicit entity_relationships row → bridge already encoded
      BRAND_HAS_NAME_MATCH:   filer eid found via aliases/canonical_name
      BRAND_HAS_CIK_MATCH:    same CIK in entity_identifiers between brand and filer
      BRAND_ORPHAN:           none of the above (truly missing)

Outputs:
  data/working/inst_eid_bridge/eid_inventory.csv (per brand_eid row)
  docs/findings/_inst_eid_bridge_phase1b.json    (summary)
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb

ROOT = Path("/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership")
DB = ROOT / "data" / "13f.duckdb"
WORKING = Path(__file__).resolve().parents[2] / "data" / "working" / "inst_eid_bridge"
WORKING.mkdir(parents=True, exist_ok=True)
OUT_JSON = Path(__file__).resolve().parents[2] / "docs" / "findings" / "_inst_eid_bridge_phase1b.json"


def main():
    con = duckdb.connect(str(DB), read_only=True)
    out: dict = {}

    # ---- 1. brand eids and their fund-side AUM ----
    print("[1/8] Brand eids in fund_holdings_v2.dm_rollup_entity_id (is_latest)...")
    con.execute(
        """
        CREATE OR REPLACE TEMP VIEW v_brand_aum AS
        SELECT
          dm_rollup_entity_id AS brand_eid,
          COUNT(*) AS fund_rows,
          SUM(market_value_usd) AS fund_aum
        FROM fund_holdings_v2
        WHERE is_latest=TRUE AND dm_rollup_entity_id IS NOT NULL
        GROUP BY dm_rollup_entity_id
        """
    )

    n_brand = con.execute("SELECT COUNT(*) FROM v_brand_aum").fetchone()[0]
    out["brand_eid_count"] = n_brand
    print(f"  brand_eid_count = {n_brand}")

    # ---- 2. filer eids in holdings_v2 (is_latest) ----
    print("[2/8] Filer eids in holdings_v2.entity_id (is_latest)...")
    con.execute(
        """
        CREATE OR REPLACE TEMP VIEW v_filer_aum AS
        SELECT
          entity_id AS filer_eid,
          COUNT(*) AS filer_rows,
          SUM(market_value_usd) AS filer_aum
        FROM holdings_v2
        WHERE is_latest=TRUE AND entity_id IS NOT NULL
        GROUP BY entity_id
        """
    )

    n_filer = con.execute("SELECT COUNT(*) FROM v_filer_aum").fetchone()[0]
    out["filer_eid_count"] = n_filer
    print(f"  filer_eid_count = {n_filer}")

    # ---- 3. Mode A' ("invisible") brand eids: brand_eid not in any holdings_v2 join key ----
    print("[3/8] Mode A' invisible brand eids (any join key)...")
    con.execute(
        """
        CREATE OR REPLACE TEMP VIEW v_holdings_eids AS
        SELECT DISTINCT entity_id AS eid FROM holdings_v2 WHERE is_latest=TRUE
        UNION
        SELECT DISTINCT rollup_entity_id AS eid FROM holdings_v2
          WHERE is_latest=TRUE AND rollup_entity_id IS NOT NULL
        UNION
        SELECT DISTINCT dm_rollup_entity_id AS eid FROM holdings_v2
          WHERE is_latest=TRUE AND dm_rollup_entity_id IS NOT NULL
        """
    )

    con.execute(
        """
        CREATE OR REPLACE TEMP VIEW v_invisible_brand AS
        SELECT b.brand_eid, b.fund_rows, b.fund_aum,
               e.canonical_name AS brand_name,
               e.entity_type AS brand_entity_type,
               e.is_inferred AS brand_is_inferred,
               e.created_source AS brand_created_source
        FROM v_brand_aum b
        LEFT JOIN v_holdings_eids h ON h.eid = b.brand_eid
        LEFT JOIN entities e ON e.entity_id = b.brand_eid
        WHERE h.eid IS NULL
        """
    )
    inv = con.execute(
        "SELECT COUNT(*), SUM(fund_rows), SUM(fund_aum) FROM v_invisible_brand"
    ).fetchone()
    out["invisible_brand_count"] = inv[0]
    out["invisible_brand_rows"] = inv[1]
    out["invisible_brand_aum_usd"] = float(inv[2]) if inv[2] else 0.0
    print(f"  invisible_brand_count = {inv[0]}, AUM = ${(inv[2] or 0)/1e9:.2f}B")

    # ---- 4. Visible-but-mismatched brand eids: brand_eid in holdings_v2 but
    #         possibly with sibling filer eids that should be merged.  ----
    # We surface "name-match neighborhoods": brand canonical_name appears as
    # multiple distinct eids in entities table.
    print("[4/8] Name-collision sets in entities table...")
    con.execute(
        """
        CREATE OR REPLACE TEMP VIEW v_name_collisions AS
        SELECT
          UPPER(REGEXP_REPLACE(TRIM(canonical_name), '[^A-Z0-9]+', ' ')) AS norm_name,
          COUNT(*) AS eid_ct,
          LIST(entity_id) AS eids,
          LIST(canonical_name) AS names,
          LIST(entity_type) AS types
        FROM entities
        WHERE canonical_name IS NOT NULL
        GROUP BY UPPER(REGEXP_REPLACE(TRIM(canonical_name), '[^A-Z0-9]+', ' '))
        HAVING COUNT(*) > 1
        """
    )
    out["name_collision_norm_name_count"] = con.execute(
        "SELECT COUNT(*) FROM v_name_collisions"
    ).fetchone()[0]

    # ---- 5. For each invisible brand_eid, look for "candidate filer eids" ----
    # Strategy A: entity_relationships (parent_entity_id = brand_eid OR child_entity_id = brand_eid)
    # Strategy B: entity_aliases (alias_value matches another entity's canonical_name token)
    # Strategy C: entity_identifiers shared CIK with any filer eid
    print("[5/8] Strategy A: entity_relationships coverage of invisible brand eids...")
    rel_cov = con.execute(
        """
        WITH inv AS (SELECT brand_eid FROM v_invisible_brand),
        rel AS (
          SELECT DISTINCT
            COALESCE(r.parent_entity_id, r.child_entity_id) AS one_eid,
            r.parent_entity_id, r.child_entity_id, r.relationship_type, r.valid_to
          FROM entity_relationships r
          WHERE r.valid_to = DATE '9999-12-31'
        )
        SELECT
          (SELECT COUNT(*) FROM inv) AS total_invisible,
          (SELECT COUNT(*) FROM inv i WHERE EXISTS (
             SELECT 1 FROM rel r
             WHERE r.parent_entity_id = i.brand_eid
                OR r.child_entity_id = i.brand_eid)) AS with_open_relationship
        """
    ).fetchone()
    out["invisible_with_open_relationship"] = rel_cov[1]
    print(f"  invisible-with-relationship = {rel_cov[1]} / {rel_cov[0]}")

    # Strategy B: name overlap (normalize, look up against filer eids)
    print("[6/8] Strategy B: name-match candidate filer eids per invisible brand...")
    con.execute(
        """
        CREATE OR REPLACE TEMP VIEW v_norm_filer AS
        SELECT
          fl.filer_eid,
          UPPER(REGEXP_REPLACE(TRIM(e.canonical_name), '[^A-Z0-9]+', ' ')) AS norm_name,
          e.canonical_name AS filer_name
        FROM v_filer_aum fl
        JOIN entities e ON e.entity_id = fl.filer_eid
        WHERE e.canonical_name IS NOT NULL
        """
    )

    con.execute(
        """
        CREATE OR REPLACE TEMP VIEW v_norm_brand AS
        SELECT
          ib.brand_eid, ib.brand_name, ib.fund_aum, ib.fund_rows,
          ib.brand_entity_type,
          UPPER(REGEXP_REPLACE(TRIM(ib.brand_name), '[^A-Z0-9]+', ' ')) AS norm_name
        FROM v_invisible_brand ib
        WHERE ib.brand_name IS NOT NULL
        """
    )

    name_match_summary = con.execute(
        """
        SELECT
          (SELECT COUNT(*) FROM v_norm_brand) AS brands_named,
          (SELECT COUNT(DISTINCT b.brand_eid)
             FROM v_norm_brand b
             JOIN v_norm_filer f ON f.norm_name = b.norm_name) AS exact_norm_match,
          (SELECT COUNT(DISTINCT b.brand_eid)
             FROM v_norm_brand b
             JOIN v_norm_filer f ON f.norm_name LIKE b.norm_name || '%'
            WHERE b.norm_name <> '') AS prefix_match
        """
    ).fetchone()
    out["name_match_summary"] = {
        "brands_named": name_match_summary[0],
        "exact_norm_match_brand_count": name_match_summary[1],
        "prefix_norm_match_brand_count": name_match_summary[2],
    }

    # Strategy C: shared CIK in entity_identifiers
    print("[7/8] Strategy C: shared CIK in entity_identifiers...")
    con.execute(
        """
        CREATE OR REPLACE TEMP VIEW v_brand_ciks AS
        SELECT ib.brand_eid, ei.identifier_value AS cik
        FROM v_invisible_brand ib
        JOIN entity_identifiers ei
          ON ei.entity_id = ib.brand_eid
         AND ei.identifier_type = 'cik'
         AND ei.valid_to = DATE '9999-12-31'
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP VIEW v_filer_ciks AS
        SELECT fl.filer_eid, ei.identifier_value AS cik
        FROM v_filer_aum fl
        JOIN entity_identifiers ei
          ON ei.entity_id = fl.filer_eid
         AND ei.identifier_type = 'cik'
         AND ei.valid_to = DATE '9999-12-31'
        """
    )
    cik_match_summary = con.execute(
        """
        SELECT
          (SELECT COUNT(DISTINCT brand_eid) FROM v_brand_ciks) AS brands_with_cik,
          (SELECT COUNT(DISTINCT bc.brand_eid)
             FROM v_brand_ciks bc
             JOIN v_filer_ciks fc ON fc.cik = bc.cik) AS brands_with_cik_match
        """
    ).fetchone()
    out["cik_match_summary"] = {
        "invisible_brands_with_any_cik": cik_match_summary[0],
        "invisible_brands_with_cik_match_to_filer": cik_match_summary[1],
    }

    # ---- 8. Build the per-brand inventory CSV ----
    print("[8/8] Writing per-brand inventory CSV...")
    con.execute(
        """
        CREATE OR REPLACE TEMP VIEW v_brand_inventory AS
        WITH rel_covered AS (
          SELECT DISTINCT i.brand_eid,
                 ANY_VALUE(r.relationship_type) AS rel_type,
                 ANY_VALUE(CASE WHEN r.parent_entity_id = i.brand_eid
                                 THEN r.child_entity_id ELSE r.parent_entity_id END) AS rel_other_eid
          FROM v_invisible_brand i
          JOIN entity_relationships r
            ON (r.parent_entity_id = i.brand_eid OR r.child_entity_id = i.brand_eid)
           AND r.valid_to = DATE '9999-12-31'
          GROUP BY i.brand_eid
        ),
        name_match AS (
          SELECT b.brand_eid,
                 ANY_VALUE(f.filer_eid) AS name_match_filer_eid,
                 ANY_VALUE(f.filer_name) AS name_match_filer_name,
                 COUNT(DISTINCT f.filer_eid) AS name_match_count
          FROM v_norm_brand b
          JOIN v_norm_filer f ON f.norm_name = b.norm_name
          WHERE b.norm_name <> ''
          GROUP BY b.brand_eid
        ),
        cik_match AS (
          SELECT bc.brand_eid,
                 ANY_VALUE(fc.filer_eid) AS cik_match_filer_eid,
                 COUNT(DISTINCT fc.filer_eid) AS cik_match_count,
                 ANY_VALUE(bc.cik) AS shared_cik
          FROM v_brand_ciks bc
          JOIN v_filer_ciks fc ON fc.cik = bc.cik
          GROUP BY bc.brand_eid
        ),
        ech_open AS (
          SELECT entity_id AS brand_eid,
                 classification AS ech_classification,
                 is_activist AS ech_is_activist,
                 source AS ech_source
          FROM entity_classification_history
          WHERE valid_to = DATE '9999-12-31'
        )
        SELECT
          ib.brand_eid,
          ib.brand_name,
          ib.brand_entity_type,
          ib.brand_is_inferred,
          ib.brand_created_source,
          ib.fund_rows,
          ib.fund_aum,
          rc.rel_type,
          rc.rel_other_eid,
          nm.name_match_filer_eid,
          nm.name_match_filer_name,
          nm.name_match_count,
          cm.cik_match_filer_eid,
          cm.cik_match_count,
          cm.shared_cik,
          ec.ech_classification,
          ec.ech_is_activist,
          ec.ech_source,
          CASE
            WHEN rc.rel_type IS NOT NULL THEN 'BRAND_HAS_RELATIONSHIP'
            WHEN cm.cik_match_filer_eid IS NOT NULL THEN 'BRAND_HAS_CIK_MATCH'
            WHEN nm.name_match_filer_eid IS NOT NULL THEN 'BRAND_HAS_NAME_MATCH'
            ELSE 'BRAND_ORPHAN'
          END AS bridge_class,
          CASE
            WHEN rc.rel_type IS NOT NULL THEN 'BRIDGE'
            WHEN cm.cik_match_filer_eid IS NOT NULL THEN 'FILER_TO_BRAND'
            WHEN nm.name_match_filer_eid IS NOT NULL THEN 'FILER_TO_BRAND'
            ELSE 'INVESTIGATE_FURTHER'
          END AS recommended_action,
          CASE
            WHEN rc.rel_type IS NOT NULL THEN 'HIGH'
            WHEN cm.cik_match_filer_eid IS NOT NULL THEN 'HIGH'
            WHEN nm.name_match_count = 1 THEN 'MEDIUM'
            WHEN nm.name_match_count > 1 THEN 'LOW'
            ELSE 'LOW'
          END AS confidence
        FROM v_invisible_brand ib
        LEFT JOIN rel_covered rc ON rc.brand_eid = ib.brand_eid
        LEFT JOIN name_match nm   ON nm.brand_eid = ib.brand_eid
        LEFT JOIN cik_match cm    ON cm.brand_eid = ib.brand_eid
        LEFT JOIN ech_open ec     ON ec.brand_eid = ib.brand_eid
        ORDER BY ib.fund_aum DESC NULLS LAST
        """
    )

    con.execute(
        f"""
        COPY (SELECT * FROM v_brand_inventory)
        TO '{WORKING / "eid_inventory.csv"}' (FORMAT CSV, HEADER)
        """
    )

    # Action / class breakdowns
    breakdown = con.execute(
        """
        SELECT bridge_class, recommended_action, confidence,
               COUNT(*) AS brand_count,
               SUM(fund_aum) AS aum,
               SUM(fund_rows) AS rows
        FROM v_brand_inventory
        GROUP BY 1,2,3 ORDER BY aum DESC NULLS LAST
        """
    ).fetchall()
    out["bridge_class_breakdown"] = [
        {
            "bridge_class": r[0],
            "recommended_action": r[1],
            "confidence": r[2],
            "brand_count": r[3],
            "fund_aum_usd": float(r[4]) if r[4] else 0.0,
            "fund_rows": r[5],
        }
        for r in breakdown
    ]

    OUT_JSON.write_text(json.dumps(out, indent=2, default=str))
    print(f"\nwrote {OUT_JSON}")
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
