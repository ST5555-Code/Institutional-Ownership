"""inst-eid-bridge Phase 1 — Full inventory of brand-vs-filer mismatches.

Read-only. No DB writes.

Builds three CSVs:
  data/working/inst_eid_bridge/mode_a_brand_no_filer.csv
  data/working/inst_eid_bridge/mode_b_eid_mismatch.csv
  data/working/inst_eid_bridge/mode_c_filer_no_brand.csv

Plus a JSON summary at docs/findings/_inst_eid_bridge_phase1.json.

Mode definitions (per inst-eid-bridge plan):
  Mode A: cik appears in fund-tier rows but NOT in holdings_v2 at all.
          (the brand-eid receives fund rolls but no 13F filer CIK matches)
  Mode B: cik appears in BOTH fund-tier and holdings_v2, but
          fund-tier dm_rollup_entity_id != holdings_v2.entity_id
          (eid duplication — same CIK, two different eids).
  Mode C: cik appears in holdings_v2 but NOT in fund-tier
          (filer-with-no-brand — most filers are not fund families).

Key insight: fund_holdings_v2.fund_cik is the N-PORT trust CIK; the brand_eid is
fund_holdings_v2.dm_rollup_entity_id. holdings_v2.cik is the 13F filer adviser CIK.
A CIK match between fund_cik and filer cik means the SAME SEC registration files
both N-PORT and 13F (rare but real — e.g., closed-end funds, BDCs).

We also build an eid-level Mode B' using entity_identifiers as a bridge:
  For each brand_eid (dm_rollup target), enumerate its CIKs via entity_identifiers
  and find filer eids (holdings_v2.entity_id) for those CIKs.
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb

ROOT = Path("/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership")
DB = ROOT / "data" / "13f.duckdb"
WORKING = Path(__file__).resolve().parents[2] / "data" / "working" / "inst_eid_bridge"
WORKING.mkdir(parents=True, exist_ok=True)
OUT_JSON = Path(__file__).resolve().parents[2] / "docs" / "findings" / "_inst_eid_bridge_phase1.json"


def main():
    con = duckdb.connect(str(DB), read_only=True)
    out: dict = {}

    # -------- Build per-CIK aggregates --------
    print("[1/5] Building fund-tier per-CIK aggregate...")
    con.execute(
        """
        CREATE OR REPLACE TEMP VIEW v_fund_per_cik AS
        SELECT
          fund_cik AS cik,
          COUNT(*) AS rows,
          SUM(market_value_usd) AS aum,
          COUNT(DISTINCT dm_rollup_entity_id) AS distinct_brand_eids,
          MIN(dm_rollup_entity_id) AS sample_brand_eid,
          ANY_VALUE(dm_rollup_name) AS sample_brand_name
        FROM fund_holdings_v2
        WHERE is_latest=TRUE AND fund_cik IS NOT NULL
        GROUP BY fund_cik
        """
    )

    print("[2/5] Building holdings-tier per-CIK aggregate...")
    con.execute(
        """
        CREATE OR REPLACE TEMP VIEW v_hv2_per_cik AS
        SELECT
          cik,
          COUNT(*) AS rows,
          SUM(market_value_usd) AS aum,
          COUNT(DISTINCT entity_id) AS distinct_filer_eids,
          MIN(entity_id) AS sample_filer_eid,
          ANY_VALUE(manager_name) AS sample_filer_name
        FROM holdings_v2
        WHERE is_latest=TRUE AND cik IS NOT NULL
        GROUP BY cik
        """
    )

    # -------- Mode A: fund-tier CIK absent from holdings_v2 --------
    print("[3/5] Identifying Mode A (brand-with-no-filer at CIK level)...")
    con.execute(
        """
        CREATE OR REPLACE TEMP VIEW v_mode_a AS
        SELECT
          f.cik,
          f.rows AS fund_rows,
          f.aum AS fund_aum,
          f.distinct_brand_eids,
          f.sample_brand_eid AS brand_eid,
          f.sample_brand_name AS brand_name,
          e.canonical_name AS brand_canonical_name,
          e.entity_type AS brand_entity_type
        FROM v_fund_per_cik f
        LEFT JOIN v_hv2_per_cik h ON h.cik = f.cik
        LEFT JOIN entities e ON e.entity_id = f.sample_brand_eid
        WHERE h.cik IS NULL
        """
    )

    mode_a_summary = con.execute(
        "SELECT COUNT(*) AS cik_ct, SUM(fund_rows) AS rows, SUM(fund_aum) AS aum FROM v_mode_a"
    ).fetchone()
    out["mode_a"] = {
        "cik_count": mode_a_summary[0],
        "fund_rows": mode_a_summary[1],
        "fund_aum_usd": float(mode_a_summary[2]) if mode_a_summary[2] else 0.0,
    }
    out["mode_a_distinct_brand_eids"] = con.execute(
        "SELECT COUNT(DISTINCT brand_eid) FROM v_mode_a"
    ).fetchone()[0]

    con.execute(
        f"""
        COPY (
          SELECT * FROM v_mode_a ORDER BY fund_aum DESC NULLS LAST
        ) TO '{WORKING / "mode_a_brand_no_filer.csv"}' (FORMAT CSV, HEADER)
        """
    )

    # -------- Mode B: same CIK, different eids --------
    print("[4/5] Identifying Mode B (eid mismatch at same CIK)...")
    # For Mode B, we need the *full* set of brand eids and filer eids per CIK.
    # Use exact eid sets and check for any mismatch.
    con.execute(
        """
        CREATE OR REPLACE TEMP VIEW v_fund_eids_per_cik AS
        SELECT fund_cik AS cik, dm_rollup_entity_id AS brand_eid,
               COUNT(*) AS rows, SUM(market_value_usd) AS aum
        FROM fund_holdings_v2
        WHERE is_latest=TRUE AND fund_cik IS NOT NULL AND dm_rollup_entity_id IS NOT NULL
        GROUP BY fund_cik, dm_rollup_entity_id
        """
    )

    con.execute(
        """
        CREATE OR REPLACE TEMP VIEW v_hv2_eids_per_cik AS
        SELECT cik, entity_id AS filer_eid,
               COUNT(*) AS rows, SUM(market_value_usd) AS aum,
               ANY_VALUE(manager_name) AS filer_name
        FROM holdings_v2
        WHERE is_latest=TRUE AND cik IS NOT NULL AND entity_id IS NOT NULL
        GROUP BY cik, entity_id
        """
    )

    con.execute(
        """
        CREATE OR REPLACE TEMP VIEW v_mode_b AS
        SELECT
          f.cik,
          f.brand_eid,
          h.filer_eid,
          eb.canonical_name AS brand_name,
          eb.entity_type   AS brand_entity_type,
          ef.canonical_name AS filer_name,
          ef.entity_type    AS filer_entity_type,
          f.rows AS fund_rows,
          f.aum  AS fund_aum,
          h.rows AS filer_rows,
          h.aum  AS filer_aum
        FROM v_fund_eids_per_cik f
        JOIN v_hv2_eids_per_cik h ON h.cik = f.cik
        LEFT JOIN entities eb ON eb.entity_id = f.brand_eid
        LEFT JOIN entities ef ON ef.entity_id = h.filer_eid
        WHERE f.brand_eid <> h.filer_eid
        """
    )

    mode_b_summary = con.execute(
        """
        SELECT COUNT(DISTINCT cik) AS ciks,
               COUNT(DISTINCT brand_eid) AS brand_eids,
               COUNT(DISTINCT filer_eid) AS filer_eids,
               COUNT(DISTINCT (brand_eid, filer_eid)) AS pair_count,
               SUM(fund_rows) AS rows,
               SUM(fund_aum) AS aum
        FROM v_mode_b
        """
    ).fetchone()
    out["mode_b"] = {
        "distinct_ciks": mode_b_summary[0],
        "distinct_brand_eids": mode_b_summary[1],
        "distinct_filer_eids": mode_b_summary[2],
        "distinct_eid_pairs": mode_b_summary[3],
        "fund_rows": mode_b_summary[4],
        "fund_aum_usd": float(mode_b_summary[5]) if mode_b_summary[5] else 0.0,
    }

    con.execute(
        f"""
        COPY (
          SELECT * FROM v_mode_b ORDER BY fund_aum DESC NULLS LAST
        ) TO '{WORKING / "mode_b_eid_mismatch.csv"}' (FORMAT CSV, HEADER)
        """
    )

    # -------- Mode C: filer with no brand (informational) --------
    print("[5/5] Identifying Mode C (filer-with-no-brand)...")
    con.execute(
        """
        CREATE OR REPLACE TEMP VIEW v_mode_c AS
        SELECT
          h.cik, h.rows AS filer_rows, h.aum AS filer_aum,
          h.distinct_filer_eids, h.sample_filer_eid AS filer_eid,
          h.sample_filer_name AS filer_name,
          ef.canonical_name AS filer_canonical_name,
          ef.entity_type AS filer_entity_type
        FROM v_hv2_per_cik h
        LEFT JOIN v_fund_per_cik f ON f.cik = h.cik
        LEFT JOIN entities ef ON ef.entity_id = h.sample_filer_eid
        WHERE f.cik IS NULL
        """
    )
    mode_c_summary = con.execute(
        "SELECT COUNT(*) AS cik_ct, SUM(filer_rows) AS rows, SUM(filer_aum) AS aum FROM v_mode_c"
    ).fetchone()
    out["mode_c"] = {
        "cik_count": mode_c_summary[0],
        "filer_rows": mode_c_summary[1],
        "filer_aum_usd": float(mode_c_summary[2]) if mode_c_summary[2] else 0.0,
    }
    con.execute(
        f"""
        COPY (
          SELECT * FROM v_mode_c ORDER BY filer_aum DESC NULLS LAST
        ) TO '{WORKING / "mode_c_filer_no_brand.csv"}' (FORMAT CSV, HEADER)
        """
    )

    # -------- Mode B' (eid-level): brand_eid -> filer_eid pairs via entity_identifiers --------
    # Per the plan §1.2: per-institution eid pair via shared CIK in entity_identifiers
    print("[6/6] Building eid-level Mode B' via entity_identifiers...")
    con.execute(
        """
        CREATE OR REPLACE TEMP VIEW v_eid_pairs_via_ei AS
        WITH brand_set AS (
          SELECT DISTINCT dm_rollup_entity_id AS brand_eid
          FROM fund_holdings_v2 WHERE is_latest=TRUE AND dm_rollup_entity_id IS NOT NULL
        ),
        filer_set AS (
          SELECT DISTINCT entity_id AS filer_eid FROM holdings_v2 WHERE is_latest=TRUE
        ),
        ei_brand AS (
          SELECT b.brand_eid, ei.identifier_value AS cik
          FROM brand_set b
          JOIN entity_identifiers ei
            ON ei.entity_id = b.brand_eid
           AND ei.identifier_type = 'cik'
           AND ei.valid_to = DATE '9999-12-31'
        ),
        ei_filer AS (
          SELECT f.filer_eid, ei.identifier_value AS cik
          FROM filer_set f
          JOIN entity_identifiers ei
            ON ei.entity_id = f.filer_eid
           AND ei.identifier_type = 'cik'
           AND ei.valid_to = DATE '9999-12-31'
        )
        SELECT b.brand_eid, f.filer_eid, b.cik AS shared_cik
        FROM ei_brand b JOIN ei_filer f
          ON b.cik = f.cik AND b.brand_eid <> f.filer_eid
        """
    )
    eidpair_summary = con.execute(
        """
        SELECT COUNT(DISTINCT (brand_eid, filer_eid)) AS pairs,
               COUNT(DISTINCT brand_eid) AS brands,
               COUNT(DISTINCT filer_eid) AS filers,
               COUNT(DISTINCT shared_cik) AS shared_ciks
        FROM v_eid_pairs_via_ei
        """
    ).fetchone()
    out["mode_b_prime_via_entity_identifiers"] = {
        "distinct_eid_pairs": eidpair_summary[0],
        "distinct_brand_eids": eidpair_summary[1],
        "distinct_filer_eids": eidpair_summary[2],
        "shared_ciks": eidpair_summary[3],
    }

    con.execute(
        f"""
        COPY (
          SELECT v.*, eb.canonical_name AS brand_name, ef.canonical_name AS filer_name
          FROM v_eid_pairs_via_ei v
          LEFT JOIN entities eb ON eb.entity_id = v.brand_eid
          LEFT JOIN entities ef ON ef.entity_id = v.filer_eid
        ) TO '{WORKING / "mode_b_prime_eid_pairs.csv"}' (FORMAT CSV, HEADER)
        """
    )

    OUT_JSON.write_text(json.dumps(out, indent=2, default=str))
    print(f"\nwrote {OUT_JSON}")
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
