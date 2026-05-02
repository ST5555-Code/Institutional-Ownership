"""inst-eid-bridge Phase 4 — Vanguard / PIMCO / BlackRock deep-dives.

Read-only. No DB writes.

For each named brand family, enumerate:
  - All entities matching the family name (canonical_name LIKE 'Vanguard%' etc)
  - For each, fund-side AUM (dm_rollup_entity_id) and filer-side AUM (entity_id)
  - Open ECH classification
  - Open entity_relationships rows (parent and child positions)
  - entity_identifiers CIKs

This produces the worked examples for the findings doc.

Output: data/working/inst_eid_bridge/deepdive_<family>.csv per family,
        docs/findings/_inst_eid_bridge_phase4.json (summary)
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb

ROOT = Path("/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership")
DB = ROOT / "data" / "13f.duckdb"
WORKING = Path(__file__).resolve().parents[2] / "data" / "working" / "inst_eid_bridge"
WORKING.mkdir(parents=True, exist_ok=True)
OUT_JSON = Path(__file__).resolve().parents[2] / "docs" / "findings" / "_inst_eid_bridge_phase4.json"

FAMILIES = {
    "Vanguard": "VANGUARD",
    "PIMCO": "PIMCO",
    "BlackRock": "BLACKROCK",
    "Pacific_Investment_Management": "PACIFIC INVESTMENT MANAGEMENT",
}


def main():
    con = duckdb.connect(str(DB), read_only=True)
    out: dict = {"families": {}}

    for fam_label, name_pattern in FAMILIES.items():
        print(f"=== {fam_label} (canonical_name LIKE '%{name_pattern}%') ===")
        rows = con.execute(
            f"""
            WITH fam AS (
              SELECT entity_id, canonical_name, entity_type, is_inferred, created_source
              FROM entities
              WHERE UPPER(canonical_name) LIKE '%{name_pattern}%'
            ),
            fund_side AS (
              SELECT dm_rollup_entity_id AS eid,
                     COUNT(*) AS rows, SUM(market_value_usd) AS aum
              FROM fund_holdings_v2 WHERE is_latest=TRUE
              GROUP BY dm_rollup_entity_id
            ),
            filer_side AS (
              SELECT entity_id AS eid,
                     COUNT(*) AS rows, SUM(market_value_usd) AS aum
              FROM holdings_v2 WHERE is_latest=TRUE
              GROUP BY entity_id
            ),
            ech AS (
              SELECT entity_id AS eid, classification, is_activist, source
              FROM entity_classification_history
              WHERE valid_to = DATE '9999-12-31'
            ),
            ei_ciks AS (
              SELECT entity_id AS eid,
                     LIST(identifier_value) AS ciks
              FROM entity_identifiers
              WHERE identifier_type='cik' AND valid_to = DATE '9999-12-31'
              GROUP BY entity_id
            )
            SELECT fam.entity_id, fam.canonical_name, fam.entity_type, fam.is_inferred,
                   fam.created_source,
                   fs.rows AS fund_rows, fs.aum AS fund_aum,
                   fl.rows AS filer_rows, fl.aum AS filer_aum,
                   ec.classification AS ech_class, ec.is_activist AS ech_is_activist,
                   ec.source AS ech_source,
                   eic.ciks
            FROM fam
            LEFT JOIN fund_side fs ON fs.eid = fam.entity_id
            LEFT JOIN filer_side fl ON fl.eid = fam.entity_id
            LEFT JOIN ech ec ON ec.eid = fam.entity_id
            LEFT JOIN ei_ciks eic ON eic.eid = fam.entity_id
            ORDER BY COALESCE(fs.aum,0) + COALESCE(fl.aum,0) DESC
            """
        ).fetchall()

        records = []
        for r in rows:
            records.append(
                {
                    "eid": r[0],
                    "canonical_name": r[1],
                    "entity_type": r[2],
                    "is_inferred": r[3],
                    "created_source": r[4],
                    "fund_rows": r[5],
                    "fund_aum_usd": float(r[6]) if r[6] else 0.0,
                    "filer_rows": r[7],
                    "filer_aum_usd": float(r[8]) if r[8] else 0.0,
                    "ech_class": r[9],
                    "ech_is_activist": r[10],
                    "ech_source": r[11],
                    "ciks": r[12],
                }
            )

        # Get any open relationships for this family
        rel_rows = con.execute(
            f"""
            WITH fam AS (
              SELECT entity_id FROM entities
              WHERE UPPER(canonical_name) LIKE '%{name_pattern}%'
            )
            SELECT
              r.parent_entity_id, ep.canonical_name AS parent_name,
              r.child_entity_id,  ec.canonical_name AS child_name,
              r.relationship_type, r.control_type, r.source
            FROM entity_relationships r
            LEFT JOIN entities ep ON ep.entity_id = r.parent_entity_id
            LEFT JOIN entities ec ON ec.entity_id = r.child_entity_id
            WHERE r.valid_to = DATE '9999-12-31'
              AND (r.parent_entity_id IN (SELECT entity_id FROM fam)
                   OR r.child_entity_id IN (SELECT entity_id FROM fam))
            """
        ).fetchall()

        rel_records = [
            {
                "parent_eid": r[0], "parent_name": r[1],
                "child_eid": r[2], "child_name": r[3],
                "relationship_type": r[4], "control_type": r[5], "source": r[6],
            }
            for r in rel_rows
        ]

        out["families"][fam_label] = {
            "entities": records,
            "relationships_open": rel_records,
            "entity_count": len(records),
            "fund_side_total_aum_usd": sum(r["fund_aum_usd"] for r in records),
            "filer_side_total_aum_usd": sum(r["filer_aum_usd"] for r in records),
            "fund_side_eids": [r["eid"] for r in records if r["fund_rows"]],
            "filer_side_eids": [r["eid"] for r in records if r["filer_rows"]],
            "both_side_eids": [
                r["eid"] for r in records if r["fund_rows"] and r["filer_rows"]
            ],
            "fund_only_eids": [
                r["eid"] for r in records if r["fund_rows"] and not r["filer_rows"]
            ],
            "filer_only_eids": [
                r["eid"] for r in records if r["filer_rows"] and not r["fund_rows"]
            ],
        }

        print(f"  {len(records)} entities; "
              f"fund_side_eids={len(out['families'][fam_label]['fund_side_eids'])}, "
              f"filer_side_eids={len(out['families'][fam_label]['filer_side_eids'])}, "
              f"both={len(out['families'][fam_label]['both_side_eids'])}, "
              f"fund_only={len(out['families'][fam_label]['fund_only_eids'])}, "
              f"filer_only={len(out['families'][fam_label]['filer_only_eids'])}")

        # Write CSV
        import csv
        csv_path = WORKING / f"deepdive_{fam_label}.csv"
        with open(csv_path, "w", newline="") as f:
            if records:
                w = csv.DictWriter(f, fieldnames=list(records[0].keys()))
                w.writeheader()
                for r in records:
                    r2 = dict(r)
                    if isinstance(r2.get("ciks"), list):
                        r2["ciks"] = "|".join(str(x) for x in r2["ciks"])
                    w.writerow(r2)

    OUT_JSON.write_text(json.dumps(out, indent=2, default=str))
    print(f"\nwrote {OUT_JSON}")


if __name__ == "__main__":
    main()
