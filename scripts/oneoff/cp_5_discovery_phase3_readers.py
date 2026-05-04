"""CP-5 discovery — Phase 3: affected reads inventory.

Read-only. Writes data/working/cp-5-affected-readers.csv with one row per major
reader site (function-level granularity) across the 5 tabs that consume the
institutional rollup graph.

Categories captured per reader:
  reader_path        — file with primary line range
  function_name      — entry function (or helper)
  tab_or_feature     — Register / Cross-Ownership / Crowding / Smart Money /
                       Conviction / Top Holders / Sector / Entity Drilldown / Fund
  current_source     — holdings_v2 only / fund_holdings_v2 only / both / ER walk
  traversal_depth    — single-hop / multi-hop / name-coalesce-only
  rollup_key         — rollup_name / rollup_entity_id / inst_parent_name / dm_*
  blast_radius_cp5   — what changes for this reader under R5 dedup + view/table

This file IS the artifact — the CSV is the canonical output.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

# Each row is one reader site. Keep brief; full SQL lives in source files.
ROWS = [
    # === Register tab ===
    ("scripts/queries/register.py:47-100", "query1", "Register",
     "holdings_v2", "name-coalesce-only", "rollup_name|inst_parent_name",
     "Aggregates parents per ticker via COALESCE(rollup_name, inst_parent_name, manager_name). "
     "Under CP-5 R5, replace COALESCE with top_parent_canonical_name + per-(top_parent, ticker) MAX(13F, fund_tier_EC). "
     "High blast: Register Q1 is the canonical 'Top Holders' read."),
    ("scripts/queries/register.py:104-115", "query1 N-PORT coverage", "Register",
     "summary_by_parent (NAME-keyed)", "name-coalesce-only", "inst_parent_name",
     "Looks up nport_coverage_pct keyed by inst_parent_name. Under CP-5, key shifts to top_parent_entity_id; "
     "summary_by_parent table needs entity-keyed rebuild."),
    ("scripts/queries/register.py:119-140", "query2", "Register",
     "holdings_v2", "name-coalesce-only", "rollup_name|inst_parent_name",
     "Holder list with shares/AUM. Same R5 migration as query1."),
    ("scripts/queries/register.py:225-310", "query3/query4/query5", "Register",
     "holdings_v2", "name-coalesce-only", "rollup_name|inst_parent_name",
     "Active/passive splits, crowding-adjacent. Under CP-5 R5, fund-tier residual must be merged "
     "before active/passive can be recomputed (manager_type lives only on holdings_v2)."),
    ("scripts/queries/register.py:455-475", "query12", "Register",
     "holdings_v2", "name-coalesce-only", "rollup_name|inst_parent_name",
     "Cohort flows aggregated by parent name. Under R5, dedup before aggregation."),
    ("scripts/queries/register.py:560-660", "query14 + drill helpers", "Register",
     "holdings_v2 + summary_by_parent", "name-coalesce-only", "inst_parent_name",
     "Filer drill-down. Currently coalesces names; CP-5 needs (top_parent, filer) hierarchy from inst_to_top_parent map."),
    ("scripts/queries/register.py:775-1135", "query16 + active variants", "Register",
     "holdings_v2 + manager_aum", "name-coalesce-only", "rollup_name|inst_parent_name",
     "Manager-level totals + AUM joins. Same migration."),

    # === Cross-Ownership tab ===
    ("scripts/queries/cross.py:55-95", "_cross_ownership_query", "Cross-Ownership",
     "holdings_v2", "name-coalesce-only", "rollup_name|inst_parent_name",
     "Multi-ticker overlap by investor name. Under R5, key shifts to top_parent_entity_id; deduplication "
     "applies per (top_parent, ticker) before pivot."),
    ("scripts/queries/cross.py:330-360", "_cross_ownership_fund_query", "Cross-Ownership",
     "fund_holdings_v2 (DIRECT)", "name-coalesce-only", "rollup_name|inst_parent_name",
     "Fund-side sibling reader. Already uses fund_holdings_v2 — useful template for CP-5 unified read."),
    ("scripts/queries/cross.py:620-650", "get_two_company_overlap", "Cross-Ownership",
     "holdings_v2", "name-coalesce-only", "rollup_name|inst_parent_name",
     "Pairwise overlap. Same migration."),

    # === Crowding (api_market.py /crowding → queries/market.py) ===
    ("scripts/queries/market.py:130-145", "get_market_summary (counter)", "Top Holders / Crowding",
     "holdings_v2", "name-coalesce-only", "rollup_name|inst_parent_name",
     "COUNT(DISTINCT COALESCE(...)) used for total_holders. Under R5, count distinct top_parents post-dedup."),
    ("scripts/queries/market.py:710-730", "get_sector_flow_movers", "Sector / Crowding",
     "holdings_v2", "name-coalesce-only", "rollup_name|inst_parent_name",
     "Movers list. Migrate to top-parent dedup."),
    ("scripts/queries/market.py:1040-1130", "institution-hierarchy via market", "Entity Drilldown / Crowding",
     "holdings_v2 + entity_relationships", "single-hop", "parent_entity_id (open ER row)",
     "ONE of TWO sites that traverses entity_relationships directly. Single-hop only — CP-5 multi-hop "
     "climb required for accurate sub-entity rollup."),

    # === Smart Money (api_market.py /smart_money → queries/market.py) ===
    # The /smart_money endpoint is wired via api_market.py:270 — use the same readers as /crowding.

    # === Conviction (api_flows.py /portfolio_context → queries/fund.py portfolio_context) ===
    ("scripts/queries/fund.py:100-200", "portfolio_context", "Conviction (Fund Portfolio)",
     "holdings_v2 (filtered)", "name-coalesce-only", "rollup_name|inst_parent_name",
     "Fund-portfolio drill for a single holder. Under R5 + View 2, integrate fund-tier decomposition "
     "(series_id-level holdings) when top_parent has fund-tier coverage."),

    # === Flows / Trend / Cohort / Peer Rotation ===
    ("scripts/queries/flows.py:240-285", "flow_analysis (entry+peer cohorts)", "Flows / Conviction",
     "holdings_v2", "name-coalesce-only", "rollup_name|inst_parent_name",
     "Quarter-over-quarter delta by parent. R5 affects baseline; deltas must be computed AFTER dedup."),
    ("scripts/queries/flows.py:340-430", "cohort_analysis", "Flows / Conviction",
     "holdings_v2", "name-coalesce-only", "rollup_name|inst_parent_name",
     "Cohort buckets by manager_type. Manager-type lives on holdings_v2 only — under R5 fund-tier "
     "rows lack manager_type; need imputation strategy from top-parent classification."),
    ("scripts/queries/flows.py:500-540", "ownership_trend_summary helpers", "Flows / Conviction",
     "shares_history", "name-coalesce-only", "inst_parent_name",
     "Pre-aggregated history table. Likely needs rebuild keyed by top_parent_entity_id under R5."),
    ("scripts/queries/flows.py:600-625", "peer_rotation_detail", "Flows / Conviction",
     "holdings_v2", "name-coalesce-only", "rollup_name|inst_parent_name",
     "Same migration."),
    ("scripts/queries/trend.py:108-160", "holder_momentum", "Crowding / Smart Money / Trend",
     "holdings_v2", "name-coalesce-only", "rollup_name|inst_parent_name",
     "Recent quarters momentum. Note: code comment acknowledges 'parents without rollup_entity_id "
     "fall back to inst_parent_name carry eid=None' — CP-5 fixes this gap."),
    ("scripts/queries/trend.py:170-205", "holder_momentum fund children", "Crowding / Trend",
     "fund_holdings_v2 + parent_fund_map", "single-hop", "parent_fund_map.rollup_entity_id",
     "Fund decomposition via parent_fund_map (existing fund-tier read). Useful template for View 2."),
    ("scripts/queries/trend.py:370-380", "ownership_trend_summary", "Trend",
     "holdings_v2", "name-coalesce-only", "rollup_name|inst_parent_name",
     "Distinct-holder counts over time. Migrate to top_parent dedup for stable count series."),

    # === Entity Drilldown (api_entities.py → queries/entities.py) ===
    ("scripts/queries/entities.py:120-170", "get_entity_descendants (build_entity_graph)", "Entity Drilldown",
     "entity_relationships (ER walk)", "multi-hop (recursive CTE)", "parent_entity_id",
     "ONE of TWO sites with multi-hop ER traversal. EXCLUDES sub_adviser edges. CP-5 must align "
     "this with the rollup-graph definition used by R5 (control + mutual + merge)."),
    ("scripts/queries/entities.py:230-330", "compute_aum_for_subtree + filer/sub-adviser children", "Entity Drilldown",
     "holdings_v2 + entity_relationships", "single-hop per ER read", "parent_entity_id",
     "Multiple ER reads per call. Heavy + currently single-hop only."),
    ("scripts/queries/entities.py:360-400", "search_entity_parents / get_institution_hierarchy", "Entity Drilldown",
     "entity_current + ER", "single-hop", "rollup_entity_id (entity_current)",
     "Uses entity_current.rollup_entity_id (the existing materialized rollup). CP-5 may extend to "
     "top_parent_entity_id (a NEW concept) without disturbing this single-hop."),

    # === Fund Portfolio (api_fund.py → queries/fund.py) ===
    # api_fund.py:26 /fund_portfolio_managers endpoint wires to fund decomposition.
    # Already covered by portfolio_context above + fund_holdings_v2 reads in trend.py.

    # === Common helpers (cross-cutting) ===
    ("scripts/queries/common.py:258-380", "match_nport_family + helpers", "All tabs (NPORT bridge)",
     "fund_holdings_v2 (NAME-MATCHED)", "name-coalesce-only", "inst_parent_name → family_name regex",
     "FRAGILE: bridges 13F readers to N-PORT data via REGEX NAME MATCH (db_holdings_to_nport_family). "
     "Under CP-5 R5 + entity-keyed dedup, this whole pattern is OBSOLETED — name-pattern matching "
     "should retire when top_parent_entity_id keys both sources."),
    ("scripts/queries/common.py:488-820", "get_nport_children* + get_children dispatcher", "Register / Conviction (drill)",
     "fund_holdings_v2 + N-CEN", "name-coalesce-only", "inst_parent_name",
     "Drill-down dispatcher. Same migration: replace name-match with entity-keyed lookup."),
    ("scripts/queries_helpers.py:155-170", "build_rollup_join (helper)", "All tabs",
     "entity_current join template", "single-hop", "ec.rollup_entity_id",
     "Centralized rollup-join helper. CP-5 likely introduces a new build_top_parent_join() helper or "
     "reuses this one with a top-parent map view."),
]


def main() -> int:
    df = pd.DataFrame(ROWS, columns=[
        "reader_path",
        "function_name",
        "tab_or_feature",
        "current_source",
        "traversal_depth",
        "rollup_key",
        "blast_radius_cp5",
    ])

    out_path = Path("data/working/cp-5-affected-readers.csv")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)
    print(f"wrote {out_path} ({len(df)} rows)")

    print()
    print("=== readers per tab ===")
    print(df["tab_or_feature"].value_counts().to_string())
    print()
    print("=== traversal depth distribution ===")
    print(df["traversal_depth"].value_counts().to_string())
    print()
    print("=== current_source distribution ===")
    print(df["current_source"].value_counts().to_string())

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
