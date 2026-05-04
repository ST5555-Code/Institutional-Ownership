"""CP-5 Bundle C — Probe 6: share class + sub-adviser layer.

Read-only investigation. Confirms (a) fund_universe / fund_holdings_v2 carry no
share-class detail (structural to N-PORT-P), and (b) inventories the sub-adviser
layer (T6 from Bundle B) including the GEODE Capital case study and a top-20
survey by fund AUM under management.

Outputs:
  data/working/cp-5-bundle-c-subadviser-cohort.csv
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import pandas as pd

DB_PATH = "/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership/data/13f.duckdb"
SENTINEL = "DATE '9999-12-31'"
COVERAGE_QUARTER = "2025Q4"
WORKDIR = Path("data/working")


def main() -> int:
    con = duckdb.connect(DB_PATH, read_only=True)
    WORKDIR.mkdir(parents=True, exist_ok=True)

    # === 6.1 Share class data availability ===
    print("=" * 78)
    print("PHASE 6.1 — share class data availability")
    print("=" * 78)

    n_series_active = con.execute(
        f"SELECT COUNT(DISTINCT series_id) FROM fund_universe "
        f"WHERE last_updated IS NOT NULL"
    ).fetchone()[0]
    print(f"  Active series in fund_universe: {n_series_active:,}")

    fu_cols = [r[1] for r in con.execute("PRAGMA table_info(fund_universe)").fetchall()]
    fhv2_cols = [r[1] for r in con.execute("PRAGMA table_info(fund_holdings_v2)").fetchall()]
    class_cols_fu = [c for c in fu_cols if "class" in c.lower()]
    class_cols_fhv2 = [c for c in fhv2_cols if "class" in c.lower()]
    print(f"  fund_universe class-related cols: {class_cols_fu or '(none)'}")
    print(f"  fund_holdings_v2 class-related cols: {class_cols_fhv2 or '(none)'}")

    print("\n  N-PORT XML parser (scripts/pipeline/nport_parsers.py:76-150) extracts")
    print("  series-level metadata only — regCik / seriesId / seriesName. No classId,")
    print("  className, or class_ticker is parsed because N-PORT-P discloses holdings")
    print("  at the SERIES level (each filing covers a series_id, not a class). Share")
    print("  class identity lives in N-CEN annual filings (Item C.20) and N-MFP3 monthly")
    print("  for money-market funds. Conclusion (c): structural — N-PORT-P does NOT")
    print("  carry share-class detail. Recovery requires N-CEN class extension or")
    print("  fund_classes (existing scripts/build_fund_classes.py) cross-reference.")
    print()
    print("  fund_classes existence + row count:")
    try:
        fc = con.execute("SELECT COUNT(*), COUNT(DISTINCT series_id), "
                         "COUNT(DISTINCT class_id) FROM fund_classes").fetchone()
        print(f"    fund_classes rows: {fc[0]:,}; distinct series: {fc[1]:,}; "
              f"distinct classes: {fc[2]:,}")
        sample = con.execute("SELECT * FROM fund_classes LIMIT 3").fetchdf()
        print(f"    columns: {list(sample.columns)}")
    except duckdb.CatalogException:
        print("    table not present in prod DuckDB")

    # === 6.2 Sub-adviser layer + GEODE case study ===
    print()
    print("=" * 78)
    print("PHASE 6.2 — sub-adviser layer (T6) + GEODE case study + top-20 survey")
    print("=" * 78)

    # Schema of ncen_adviser_map
    cols = [r[1] for r in con.execute("PRAGMA table_info(ncen_adviser_map)").fetchall()]
    print(f"  ncen_adviser_map cols: {cols}")

    # Distinct sub-adviser CRDs (T6a) — current state, valid_to sentinel
    has_valid_to = "valid_to" in cols
    pred = f"WHERE valid_to = {SENTINEL}" if has_valid_to else ""
    role_dist = con.execute(
        f"SELECT role, COUNT(*) AS n FROM ncen_adviser_map {pred} GROUP BY 1 ORDER BY 2 DESC"
    ).fetchdf()
    print("\n  ncen_adviser_map role distribution (open rows):")
    print(role_dist.to_string(index=False))

    # 6.2a — top sub-advisers by fund AUM under management
    # Sub-adviser layer: ncen_adviser_map.role='subadviser' joined to entity_identifiers
    # to resolve adviser_crd → entity_id, then to fund_universe for AUM.
    print("\n  Top 50 sub-adviser firms by fund AUM under sub-advisement (current snapshot):")
    subadv = con.execute(f"""
        WITH sa AS (
            SELECT DISTINCT nm.registrant_cik, nm.series_id, nm.adviser_crd
            FROM ncen_adviser_map nm
            {pred} {'AND' if pred else 'WHERE'} nm.role = 'subadviser'
        ),
        sa_resolved AS (
            SELECT sa.registrant_cik, sa.series_id, sa.adviser_crd,
                   ei.entity_id AS sub_eid
            FROM sa
            LEFT JOIN entity_identifiers ei
              ON ei.identifier_type = 'crd' AND ei.identifier_value =sa.adviser_crd
        ),
        fund_aum AS (
            SELECT series_id, SUM(total_net_assets) AS aum_under_subadvise
            FROM fund_universe
            GROUP BY 1
        )
        SELECT sub_eid,
               (SELECT display_name FROM entity_current ec WHERE ec.entity_id=sa_resolved.sub_eid LIMIT 1) AS sub_name,
               COUNT(DISTINCT sa_resolved.series_id) AS n_series,
               COUNT(DISTINCT sa_resolved.adviser_crd) AS n_crds,
               SUM(fund_aum.aum_under_subadvise) / 1e9 AS aum_under_subadvise_b
        FROM sa_resolved
        LEFT JOIN fund_aum ON fund_aum.series_id = sa_resolved.series_id
        GROUP BY 1
        ORDER BY aum_under_subadvise_b DESC NULLS LAST
        LIMIT 50
    """).fetchdf()
    pd.set_option("display.width", 220)
    pd.set_option("display.max_colwidth", 60)
    print(subadv.head(50).to_string(index=False))

    # 6.2b — GEODE case study
    print()
    print("  GEODE Capital case study:")
    geode = con.execute("""
        SELECT entity_id, display_name, entity_type
        FROM entity_current
        WHERE display_name ILIKE '%GEODE%'
    """).fetchdf()
    print(f"    entity matches: {len(geode)}")
    print(geode.to_string(index=False))

    geode_eid = None
    # Iterate every GEODE eid; report each one's footprint and roles
    for _, grow in geode.iterrows():
        geid = int(grow["entity_id"])
        gname = grow["display_name"]
        h13f = con.execute(f"""
            SELECT COUNT(*), SUM(market_value_usd)/1e9 FROM holdings_v2
            WHERE entity_id = {geid} AND is_latest AND quarter = '{COVERAGE_QUARTER}'
        """).fetchone()
        fhv = con.execute(f"""
            SELECT COUNT(*), SUM(market_value_usd)/1e9 FROM fund_holdings_v2
            WHERE rollup_entity_id = {geid} AND is_latest
              AND quarter = '{COVERAGE_QUARTER}' AND asset_category = 'EC'
        """).fetchone()
        nrole = con.execute(f"""
            SELECT nm.role, COUNT(DISTINCT nm.series_id) AS n
            FROM ncen_adviser_map nm
            JOIN entity_identifiers ei
              ON ei.identifier_type = 'crd' AND ei.identifier_value = nm.adviser_crd
            WHERE ei.entity_id = {geid}
              {'AND nm.valid_to = ' + SENTINEL if has_valid_to else ''}
            GROUP BY 1
        """).fetchdf()
        print(f"\n    eid {geid} ({gname}):")
        print(f"      13F 2025Q4: {h13f[0]:,} rows / ${h13f[1] or 0:.1f}B")
        print(f"      fund-tier rollup_entity_id 2025Q4 EC: {fhv[0]:,} rows / ${fhv[1] or 0:.1f}B")
        print(f"      ncen roles: {nrole.to_dict('records') if len(nrole) else '(none)'}")

    if len(geode):
        # Pick the highest-impact GEODE eid for the funds drilldown
        geode_eid = 7859  # GEODE CAPITAL MANAGEMENT, LLC (the active sub-adviser)
        # Funds where GEODE is sub-adviser
        geode_funds = con.execute(f"""
            SELECT nm.registrant_cik, nm.series_id, fu.fund_name, fu.family_name,
                   fu.total_net_assets / 1e9 AS aum_b,
                   nm.role
            FROM ncen_adviser_map nm
            JOIN entity_identifiers ei
              ON ei.identifier_type = 'crd' AND ei.identifier_value =nm.adviser_crd
            JOIN fund_universe fu ON fu.series_id = nm.series_id
            WHERE ei.entity_id = {geode_eid}
              {'AND nm.valid_to = ' + SENTINEL if has_valid_to else ''}
            ORDER BY fu.total_net_assets DESC NULLS LAST
            LIMIT 25
        """).fetchdf()
        print(f"\n    Funds where GEODE is named adviser/subadviser (top 25 by AUM):")
        print(geode_funds.to_string(index=False))

        # GEODE rollup attribution probe — when GEODE sub-advises Fidelity index
        # funds, where does fund_holdings_v2.rollup_entity_id land?
        adviser_rollup = con.execute(f"""
            SELECT fh.rollup_entity_id,
                   ec.display_name AS rollup_name,
                   COUNT(*) AS n_rows, SUM(fh.market_value_usd)/1e9 AS aum_b
            FROM fund_holdings_v2 fh
            JOIN ncen_adviser_map nm ON nm.series_id = fh.series_id
            JOIN entity_identifiers ei
              ON ei.identifier_type = 'crd' AND ei.identifier_value = nm.adviser_crd
            LEFT JOIN entity_current ec ON ec.entity_id = fh.rollup_entity_id
            WHERE ei.entity_id = {geode_eid}
              AND nm.role = 'subadviser'
              {'AND nm.valid_to = ' + SENTINEL if has_valid_to else ''}
              AND fh.is_latest AND fh.quarter = '{COVERAGE_QUARTER}'
              AND fh.asset_category = 'EC'
            GROUP BY 1, 2 ORDER BY n_rows DESC
        """).fetchdf()
        print(f"\n    Where do GEODE-subadvised funds rollup attribute? (top dest eids):")
        print(adviser_rollup.head(10).to_string(index=False))

    # 6.2c — sub-adviser pattern survey (top 20)
    out = subadv[["sub_eid", "sub_name", "n_series", "n_crds", "aum_under_subadvise_b"]].head(20)
    out.to_csv(WORKDIR / "cp-5-bundle-c-subadviser-cohort.csv", index=False)
    print(f"\n  Wrote {WORKDIR / 'cp-5-bundle-c-subadviser-cohort.csv'} (top 20)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
