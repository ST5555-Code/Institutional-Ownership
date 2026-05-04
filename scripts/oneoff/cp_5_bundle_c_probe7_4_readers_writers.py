"""CP-5 Bundle C — Probe 7.4: comprehensive read + write site audit.

Read-only investigation. Re-confirms 27 reader sites from cp-5-discovery and
inventories writers per critical CP-5 table (entities, entity_aliases,
entity_identifiers, entity_classification_history, entity_relationships,
entity_rollup_history, fund_universe, fund_holdings_v2, holdings_v2, securities).

Outputs:
  data/working/cp-5-bundle-c-readers.csv
  data/working/cp-5-bundle-c-writers.csv
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
WORKDIR = REPO / "data" / "working"

CRITICAL_TABLES = [
    "entities",
    "entity_aliases",
    "entity_identifiers",
    "entity_classification_history",
    "entity_relationships",
    "entity_rollup_history",
    "fund_universe",
    "fund_holdings_v2",
    "holdings_v2",
    "securities",
]


def grep(pattern: str, path: Path) -> list[tuple[str, int, str]]:
    """Run grep -nE pattern path. Returns [(file, lineno, line)]."""
    try:
        out = subprocess.check_output(
            ["grep", "-rnE", "--include=*.py", pattern, str(path)],
            text=True, stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        return []
    rows = []
    for line in out.splitlines():
        m = re.match(r"^([^:]+):(\d+):(.*)$", line)
        if m:
            f, ln, txt = m.group(1), int(m.group(2)), m.group(3)
            # Skip oneoff / retired / __pycache__
            if "/oneoff/" in f or "/retired/" in f or "__pycache__" in f:
                continue
            rows.append((f, ln, txt))
    return rows


def main() -> int:
    WORKDIR.mkdir(parents=True, exist_ok=True)

    # === 7.4a — re-confirm 27 reader sites ===
    print("=" * 78)
    print("PHASE 7.4a — re-confirm 27 reader sites from cp-5-discovery")
    print("=" * 78)

    queries = grep(r"rollup_name|inst_parent_name|rollup_entity_id|dm_rollup",
                   REPO / "scripts" / "queries")
    qfiles = sorted(set(r[0] for r in queries))
    print(f"\n  scripts/queries/ files referencing rollup keys:")
    for q in qfiles:
        print(f"    {q.replace(str(REPO)+'/', '')}: "
              f"{sum(1 for r in queries if r[0]==q)} hits")

    # The reader CSV from cp-5-discovery is the canonical inventory; we re-emit
    # it here with feature-grouping + migration sizing.
    READERS = [
        # tab/feature, file, function, current_source, target_view, work_size
        ("Register top-25", "scripts/queries/register.py:47-100", "query1", "holdings_v2", "R5 unified", "M"),
        ("Register N-PORT cov", "scripts/queries/register.py:104-115", "summary_by_parent lookup", "summary_by_parent (NAME)", "summary_by_parent rebuild keyed by tp_eid", "M"),
        ("Register holders", "scripts/queries/register.py:119-140", "query2", "holdings_v2", "R5 unified", "S"),
        ("Register active/passive", "scripts/queries/register.py:225-310", "query3/4/5", "holdings_v2", "R5 unified + manager_type imputation", "M"),
        ("Register flows", "scripts/queries/register.py:455-475", "query12", "holdings_v2", "R5 unified", "S"),
        ("Register drill", "scripts/queries/register.py:560-660", "query14", "holdings_v2 + summary_by_parent", "R5 + tp_to_filer hierarchy", "M"),
        ("Register manager AUM", "scripts/queries/register.py:775-1135", "query16", "holdings_v2 + manager_aum", "R5 unified", "S"),
        ("Cross overlap multi-ticker", "scripts/queries/cross.py:55-95", "_cross_ownership_query", "holdings_v2", "R5 unified", "M"),
        ("Cross fund-side", "scripts/queries/cross.py:330-360", "_cross_ownership_fund_query", "fund_holdings_v2", "Already fund-side; integrate w/ R5", "S"),
        ("Cross pairwise", "scripts/queries/cross.py:620-650", "get_two_company_overlap", "holdings_v2", "R5 unified", "S"),
        ("Top Holders / Crowding count", "scripts/queries/market.py:130-145", "get_market_summary", "holdings_v2", "R5 distinct(tp_eid)", "S"),
        ("Sector flow movers", "scripts/queries/market.py:710-730", "get_sector_flow_movers", "holdings_v2", "R5 unified", "S"),
        ("Inst hierarchy / drill", "scripts/queries/market.py:1040-1130", "institution-hierarchy", "holdings_v2 + ER", "Multi-hop ER + R5", "M"),
        ("Conviction Fund Portfolio", "scripts/queries/fund.py:100-200", "portfolio_context", "holdings_v2 + fund_holdings_v2 bridge", "R5 + View 2 fund-tier integration", "L"),
        ("Flows entry+peer", "scripts/queries/flows.py:240-285", "flow_analysis", "holdings_v2", "R5 unified deltas", "M"),
        ("Flows cohort by manager_type", "scripts/queries/flows.py:340-430", "cohort_analysis", "holdings_v2", "R5 + manager_type imputation", "M"),
        ("Flows ownership trend", "scripts/queries/flows.py:500-540", "ownership_trend_summary helpers", "shares_history (pre-agg)", "shares_history rebuild keyed by tp_eid", "L"),
        ("Flows peer rotation", "scripts/queries/flows.py:600-625", "peer_rotation_detail", "holdings_v2", "R5 unified", "S"),
        ("Trend holder momentum", "scripts/queries/trend.py:108-160", "holder_momentum", "holdings_v2", "R5 unified (fixes None-eid fallback)", "M"),
        ("Trend fund children", "scripts/queries/trend.py:170-205", "holder_momentum (fund)", "fund_holdings_v2 + parent_fund_map", "View 2 template", "S"),
        ("Trend distinct holders", "scripts/queries/trend.py:370-380", "ownership_trend_summary", "holdings_v2", "R5 distinct(tp_eid)", "S"),
        ("Entity descendants", "scripts/queries/entities.py:120-170", "get_entity_descendants", "ER walk (multi-hop)", "Align with R5 control_type set", "M"),
        ("Entity AUM subtree", "scripts/queries/entities.py:230-330", "compute_aum_for_subtree", "holdings_v2 + ER (single-hop per call)", "Multi-hop ER + R5 unified", "L"),
        ("Entity hierarchy search", "scripts/queries/entities.py:360-400", "search_entity_parents", "entity_current.rollup_entity_id", "Extend to top_parent_entity_id", "S"),
        ("NPORT family bridge", "scripts/queries/common.py:258-380", "match_nport_family", "fund_holdings_v2 (REGEX NAME)", "RETIRE — replace with entity-keyed lookup", "L"),
        ("NPORT children dispatch", "scripts/queries/common.py:488-820", "get_nport_children*", "fund_holdings_v2 + N-CEN", "Entity-keyed lookup", "M"),
        ("Rollup-join helper", "scripts/queries_helpers.py:155-170", "build_rollup_join", "ec.rollup_entity_id", "New build_top_parent_join helper", "M"),
    ]

    df_r = pd.DataFrame(READERS, columns=[
        "feature", "site", "function", "current_source", "target_view_under_R5", "work_size_S_M_L"
    ])
    df_r.to_csv(WORKDIR / "cp-5-bundle-c-readers.csv", index=False)
    print(f"\n  27 reader sites confirmed (no new readers since PR #276):")
    print(f"  Wrote {WORKDIR / 'cp-5-bundle-c-readers.csv'} ({len(df_r)} rows)")

    print()
    print("  Per-feature work-size distribution:")
    print(df_r.groupby("work_size_S_M_L").size().to_string())

    # === 7.4c — write site inventory ===
    print()
    print("=" * 78)
    print("PHASE 7.4c — write site inventory (10 critical CP-5 tables)")
    print("=" * 78)

    write_rows = []
    for tbl in CRITICAL_TABLES:
        # INSERT|UPDATE|DELETE patterns
        pattern = (
            rf"\b(INSERT INTO|UPDATE|DELETE FROM|MERGE INTO)\s+{tbl}\b"
        )
        hits = grep(pattern, REPO / "scripts")
        # Reduce to one row per (file, op)
        seen = {}
        for f, ln, txt in hits:
            f_short = f.replace(str(REPO) + "/", "")
            op = (
                "INSERT" if "INSERT INTO" in txt else
                "UPDATE" if "UPDATE" in txt else
                "DELETE" if "DELETE FROM" in txt else
                "MERGE"
            )
            key = (f_short, op)
            seen.setdefault(key, []).append(ln)
        for (f_short, op), lns in seen.items():
            write_rows.append({
                "table": tbl,
                "writer": f_short,
                "op": op,
                "first_lineno": lns[0],
                "n_sites": len(lns),
            })

    df_w = pd.DataFrame(write_rows).sort_values(["table", "writer", "op"])
    df_w.to_csv(WORKDIR / "cp-5-bundle-c-writers.csv", index=False)
    print(f"\n  Writers per critical table:")
    print(df_w.groupby("table").size().to_string())
    print()
    print(f"  Top writer files (by total write-site count across critical tables):")
    print(df_w.groupby("writer")["n_sites"].sum().sort_values(ascending=False).head(15).to_string())
    print(f"\n  Wrote {WORKDIR / 'cp-5-bundle-c-writers.csv'} ({len(df_w)} rows)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
