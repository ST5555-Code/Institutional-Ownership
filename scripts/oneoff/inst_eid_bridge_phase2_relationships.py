"""inst-eid-bridge Phase 2/3 — Relationship-type analysis + ECH coverage.

Read-only. No DB writes.

For the 498 invisible brand eids that DO have entity_relationships rows:
  - What relationship_type values are present?
  - How many distinct (brand, filer) pairs?
  - How many of those pairs have BOTH endpoints classified in ECH?

For the 723 orphans:
  - Top 25 by fund AUM (concentrated tail?)
  - Brand entity_type distribution
  - is_inferred / created_source distribution

ECH coverage on invisible brand eids:
  - How many of 1,225 have an open ECH classification row?
  - Distribution of classifications.

Outputs:
  data/working/inst_eid_bridge/relationship_types.csv
  data/working/inst_eid_bridge/orphan_top25.csv
  data/working/inst_eid_bridge/ech_coverage_breakdown.csv
  docs/findings/_inst_eid_bridge_phase2.json
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb

ROOT = Path("/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership")
DB = ROOT / "data" / "13f.duckdb"
WORKING = Path(__file__).resolve().parents[2] / "data" / "working" / "inst_eid_bridge"
WORKING.mkdir(parents=True, exist_ok=True)
OUT_JSON = Path(__file__).resolve().parents[2] / "docs" / "findings" / "_inst_eid_bridge_phase2.json"


def main():
    con = duckdb.connect(str(DB), read_only=True)
    out: dict = {}

    # Re-derive invisible brand eids inline.
    con.execute(
        """
        CREATE OR REPLACE TEMP VIEW v_brand_aum AS
        SELECT dm_rollup_entity_id AS brand_eid,
               COUNT(*) AS fund_rows, SUM(market_value_usd) AS fund_aum
        FROM fund_holdings_v2
        WHERE is_latest=TRUE AND dm_rollup_entity_id IS NOT NULL
        GROUP BY dm_rollup_entity_id
        """
    )
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

    # ---------- Relationship-type analysis ----------
    print("[1/5] Relationship-type breakdown for invisible brand eids...")
    rt = con.execute(
        """
        SELECT
          r.relationship_type,
          r.control_type,
          COUNT(DISTINCT i.brand_eid) AS distinct_brands,
          COUNT(*) AS row_count,
          SUM(i.fund_aum) AS aum
        FROM v_invisible_brand i
        JOIN entity_relationships r
          ON (r.parent_entity_id = i.brand_eid OR r.child_entity_id = i.brand_eid)
         AND r.valid_to = DATE '9999-12-31'
        GROUP BY r.relationship_type, r.control_type
        ORDER BY aum DESC NULLS LAST
        """
    ).fetchall()
    out["relationship_type_breakdown"] = [
        {
            "relationship_type": r[0],
            "control_type": r[1],
            "distinct_brands": r[2],
            "row_count": r[3],
            "fund_aum_usd": float(r[4]) if r[4] else 0.0,
        }
        for r in rt
    ]
    print(json.dumps(out["relationship_type_breakdown"], indent=2, default=str))

    # Position of brand_eid in the relationship: parent vs child
    pos = con.execute(
        """
        SELECT
          CASE
            WHEN r.parent_entity_id = i.brand_eid AND r.child_entity_id = i.brand_eid THEN 'self'
            WHEN r.parent_entity_id = i.brand_eid THEN 'parent'
            WHEN r.child_entity_id = i.brand_eid THEN 'child'
          END AS brand_position,
          r.relationship_type,
          COUNT(DISTINCT i.brand_eid) AS brands,
          SUM(i.fund_aum) AS aum
        FROM v_invisible_brand i
        JOIN entity_relationships r
          ON (r.parent_entity_id = i.brand_eid OR r.child_entity_id = i.brand_eid)
         AND r.valid_to = DATE '9999-12-31'
        GROUP BY 1, 2
        ORDER BY aum DESC NULLS LAST
        """
    ).fetchall()
    out["brand_position_breakdown"] = [
        {
            "brand_position": r[0],
            "relationship_type": r[1],
            "distinct_brands": r[2],
            "fund_aum_usd": float(r[3]) if r[3] else 0.0,
        }
        for r in pos
    ]

    # CSV: per-brand relationship rows
    con.execute(
        f"""
        COPY (
          SELECT
            i.brand_eid,
            i.brand_name,
            i.fund_aum,
            i.fund_rows,
            r.relationship_type,
            r.control_type,
            CASE WHEN r.parent_entity_id = i.brand_eid THEN 'parent' ELSE 'child' END AS brand_position,
            CASE WHEN r.parent_entity_id = i.brand_eid THEN r.child_entity_id
                 ELSE r.parent_entity_id END AS counterparty_eid,
            ec.canonical_name AS counterparty_name,
            ec.entity_type AS counterparty_entity_type,
            (ec.entity_id IN (SELECT entity_id FROM holdings_v2 WHERE is_latest=TRUE)) AS counterparty_in_hv2
          FROM v_invisible_brand i
          JOIN entity_relationships r
            ON (r.parent_entity_id = i.brand_eid OR r.child_entity_id = i.brand_eid)
           AND r.valid_to = DATE '9999-12-31'
          LEFT JOIN entities ec ON ec.entity_id =
            CASE WHEN r.parent_entity_id = i.brand_eid THEN r.child_entity_id
                 ELSE r.parent_entity_id END
          ORDER BY i.fund_aum DESC NULLS LAST
        ) TO '{WORKING / "relationship_types.csv"}' (FORMAT CSV, HEADER)
        """
    )

    # Counterparty resolution rate: do the bridge endpoints actually appear in holdings_v2?
    print("[2/5] Counterparty hv2 presence...")
    cp_hv2 = con.execute(
        """
        WITH cp AS (
          SELECT DISTINCT i.brand_eid,
                 CASE WHEN r.parent_entity_id = i.brand_eid THEN r.child_entity_id
                      ELSE r.parent_entity_id END AS counterparty_eid
          FROM v_invisible_brand i
          JOIN entity_relationships r
            ON (r.parent_entity_id = i.brand_eid OR r.child_entity_id = i.brand_eid)
           AND r.valid_to = DATE '9999-12-31'
        ),
        h_eids AS (SELECT DISTINCT entity_id AS eid FROM holdings_v2 WHERE is_latest=TRUE)
        SELECT
          COUNT(DISTINCT cp.brand_eid) AS brands_with_relationship,
          COUNT(DISTINCT CASE WHEN h.eid IS NOT NULL THEN cp.brand_eid END) AS brands_with_counterparty_in_hv2,
          COUNT(*) AS pair_count,
          SUM(CASE WHEN h.eid IS NOT NULL THEN 1 ELSE 0 END) AS pairs_with_counterparty_in_hv2
        FROM cp
        LEFT JOIN h_eids h ON h.eid = cp.counterparty_eid
        """
    ).fetchone()
    out["counterparty_hv2_resolution"] = {
        "brands_with_relationship": cp_hv2[0],
        "brands_with_counterparty_in_hv2": cp_hv2[1],
        "pair_count": cp_hv2[2],
        "pairs_with_counterparty_in_hv2": cp_hv2[3],
    }
    print(json.dumps(out["counterparty_hv2_resolution"], indent=2))

    # ---------- ECH coverage of invisible brands ----------
    print("[3/5] ECH coverage of invisible brand eids...")
    ech = con.execute(
        """
        SELECT
          COUNT(DISTINCT i.brand_eid) AS total_invisible,
          COUNT(DISTINCT CASE WHEN ec.entity_id IS NOT NULL THEN i.brand_eid END) AS with_open_ech,
          SUM(i.fund_aum) AS total_aum,
          SUM(CASE WHEN ec.entity_id IS NOT NULL THEN i.fund_aum ELSE 0 END) AS aum_with_ech
        FROM v_invisible_brand i
        LEFT JOIN entity_classification_history ec
          ON ec.entity_id = i.brand_eid AND ec.valid_to = DATE '9999-12-31'
        """
    ).fetchone()
    out["ech_coverage"] = {
        "total_invisible_brands": ech[0],
        "brands_with_open_ech": ech[1],
        "total_aum_usd": float(ech[2]) if ech[2] else 0.0,
        "aum_with_ech_usd": float(ech[3]) if ech[3] else 0.0,
    }

    ech_dist = con.execute(
        """
        SELECT
          ec.classification,
          COUNT(DISTINCT i.brand_eid) AS brands,
          SUM(i.fund_aum) AS aum
        FROM v_invisible_brand i
        JOIN entity_classification_history ec
          ON ec.entity_id = i.brand_eid AND ec.valid_to = DATE '9999-12-31'
        GROUP BY ec.classification
        ORDER BY aum DESC NULLS LAST
        """
    ).fetchall()
    out["ech_classification_distribution"] = [
        {
            "classification": r[0],
            "distinct_brands": r[1],
            "fund_aum_usd": float(r[2]) if r[2] else 0.0,
        }
        for r in ech_dist
    ]

    # ---------- Orphan cohort analysis ----------
    print("[4/5] Orphan (BRAND_ORPHAN) cohort analysis...")
    con.execute(
        """
        CREATE OR REPLACE TEMP VIEW v_orphan AS
        SELECT i.*
        FROM v_invisible_brand i
        WHERE NOT EXISTS (
          SELECT 1 FROM entity_relationships r
          WHERE (r.parent_entity_id = i.brand_eid OR r.child_entity_id = i.brand_eid)
            AND r.valid_to = DATE '9999-12-31'
        )
        AND NOT EXISTS (
          SELECT 1
          FROM entity_identifiers eb
          JOIN holdings_v2 hv ON hv.cik = eb.identifier_value AND hv.is_latest=TRUE
          WHERE eb.entity_id = i.brand_eid
            AND eb.identifier_type = 'cik'
            AND eb.valid_to = DATE '9999-12-31'
        )
        AND NOT EXISTS (
          SELECT 1 FROM entities ef
          WHERE ef.entity_id IN (SELECT DISTINCT entity_id FROM holdings_v2 WHERE is_latest=TRUE)
            AND UPPER(REGEXP_REPLACE(TRIM(ef.canonical_name), '[^A-Z0-9]+', ' '))
              = UPPER(REGEXP_REPLACE(TRIM(i.brand_name), '[^A-Z0-9]+', ' '))
            AND i.brand_name IS NOT NULL
        )
        """
    )

    orphan_summary = con.execute(
        "SELECT COUNT(*), SUM(fund_aum), SUM(fund_rows) FROM v_orphan"
    ).fetchone()
    out["orphan_summary"] = {
        "count": orphan_summary[0],
        "fund_aum_usd": float(orphan_summary[1]) if orphan_summary[1] else 0.0,
        "fund_rows": orphan_summary[2],
    }

    orphan_type_dist = con.execute(
        """
        SELECT brand_entity_type, COUNT(*) AS brands, SUM(fund_aum) AS aum
        FROM v_orphan
        GROUP BY brand_entity_type
        ORDER BY aum DESC NULLS LAST
        """
    ).fetchall()
    out["orphan_entity_type_distribution"] = [
        {
            "brand_entity_type": r[0],
            "brand_count": r[1],
            "fund_aum_usd": float(r[2]) if r[2] else 0.0,
        }
        for r in orphan_type_dist
    ]

    orphan_source_dist = con.execute(
        """
        SELECT brand_created_source, brand_is_inferred,
               COUNT(*) AS brands, SUM(fund_aum) AS aum
        FROM v_orphan
        GROUP BY brand_created_source, brand_is_inferred
        ORDER BY aum DESC NULLS LAST
        """
    ).fetchall()
    out["orphan_created_source_distribution"] = [
        {
            "created_source": r[0],
            "is_inferred": r[1],
            "brand_count": r[2],
            "fund_aum_usd": float(r[3]) if r[3] else 0.0,
        }
        for r in orphan_source_dist
    ]

    con.execute(
        f"""
        COPY (
          SELECT * FROM v_orphan
          ORDER BY fund_aum DESC NULLS LAST
          LIMIT 50
        ) TO '{WORKING / "orphan_top50.csv"}' (FORMAT CSV, HEADER)
        """
    )

    # ---------- Top-25 invisible by AUM (any class) ----------
    print("[5/5] Top-25 invisible brand eids by AUM...")
    top25 = con.execute(
        """
        WITH br AS (
          SELECT i.*,
            (SELECT r.relationship_type FROM entity_relationships r
              WHERE (r.parent_entity_id = i.brand_eid OR r.child_entity_id = i.brand_eid)
                AND r.valid_to = DATE '9999-12-31' LIMIT 1) AS rel_type,
            (SELECT CASE WHEN r.parent_entity_id = i.brand_eid THEN r.child_entity_id
                          ELSE r.parent_entity_id END
                FROM entity_relationships r
              WHERE (r.parent_entity_id = i.brand_eid OR r.child_entity_id = i.brand_eid)
                AND r.valid_to = DATE '9999-12-31' LIMIT 1) AS counterparty_eid,
            (SELECT classification FROM entity_classification_history
              WHERE entity_id = i.brand_eid AND valid_to = DATE '9999-12-31' LIMIT 1) AS ech_class
          FROM v_invisible_brand i
        )
        SELECT br.*, ec.canonical_name AS counterparty_name,
               (br.counterparty_eid IN (SELECT entity_id FROM holdings_v2 WHERE is_latest=TRUE)) AS cp_in_hv2
        FROM br
        LEFT JOIN entities ec ON ec.entity_id = br.counterparty_eid
        ORDER BY br.fund_aum DESC NULLS LAST
        LIMIT 25
        """
    ).fetchall()
    out["top25_invisible"] = [
        {
            "brand_eid": r[0],
            "fund_rows": r[1],
            "fund_aum_usd": float(r[2]) if r[2] else 0.0,
            "brand_name": r[3],
            "brand_entity_type": r[4],
            "rel_type": r[7],
            "counterparty_eid": r[8],
            "ech_class": r[9],
            "counterparty_name": r[10],
            "cp_in_hv2": r[11],
        }
        for r in top25
    ]

    OUT_JSON.write_text(json.dumps(out, indent=2, default=str))
    print(f"\nwrote {OUT_JSON}")


if __name__ == "__main__":
    main()
