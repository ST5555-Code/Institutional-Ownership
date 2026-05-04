"""CP-5 Bundle C — Probe 8: View 2 fund-tier coverage breakdown.

Read-only investigation. Confirms Bundle A's $8T-with-no-N-PORT-path cohort and
classifies it by manager type (hedge, SMA, pension, family office, sovereign,
other) for View 2 scope recommendation.

Outputs:
  data/working/cp-5-bundle-c-view2-coverage.csv
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import pandas as pd

DB_PATH = "/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership/data/13f.duckdb"
COVERAGE_QUARTER = "2025Q4"
WORKDIR = Path("data/working")


def main() -> int:
    con = duckdb.connect(DB_PATH, read_only=True)
    WORKDIR.mkdir(parents=True, exist_ok=True)

    print("=" * 78)
    print("PHASE 8.1 — non-N-PORT cohort breakdown")
    print("=" * 78)
    # Use cp-5-discovery §5 baseline: top-parents with 13F AUM but no fund-tier path.
    # cp-5-discovery's CSV already keys by manager_type from holdings_v2.

    # Inspect manager_type values in holdings_v2 (latest quarter)
    mt = con.execute(f"""
        SELECT manager_type, COUNT(DISTINCT entity_id) AS n_filers,
               SUM(market_value_usd)/1e9 AS aum_b
        FROM holdings_v2
        WHERE is_latest AND quarter = '{COVERAGE_QUARTER}'
        GROUP BY 1 ORDER BY aum_b DESC
    """).fetchdf()
    pd.set_option("display.width", 220)
    print("  All-filer breakdown by manager_type (2025Q4):")
    print(mt.to_string(index=False))

    # Restrict to top-parents in '13F_only' coverage_class with no fund-tier
    cov = pd.read_csv("data/working/cp-5-coverage-matrix-corrected.csv")
    f13_only = cov[cov["coverage_class"] == "13F_only"]
    eids = ",".join(str(int(e)) for e in f13_only["top_parent_entity_id"])

    if not eids:
        print("  no 13F_only top-parents in corrected matrix top-100")
        return 0

    cohort = con.execute(f"""
        WITH per_filer AS (
          SELECT h.entity_id, ANY_VALUE(h.manager_type) AS manager_type,
                 SUM(h.market_value_usd)/1e9 AS aum_b
          FROM holdings_v2 h
          WHERE h.is_latest AND h.quarter='{COVERAGE_QUARTER}'
            AND h.entity_id IN ({eids})
          GROUP BY 1
        )
        SELECT manager_type,
               COUNT(*) AS n_top_parents,
               SUM(aum_b) AS aum_b
        FROM per_filer
        GROUP BY 1 ORDER BY 3 DESC
    """).fetchdf()
    print(f"\n  13F_only top-parents (within corrected top-100) by manager_type:")
    print(cohort.to_string(index=False))

    # Total non-N-PORT footprint across full universe
    full = con.execute(f"""
        WITH inst_filers AS (
          SELECT entity_id, ANY_VALUE(manager_type) AS manager_type,
                 SUM(market_value_usd)/1e9 AS aum_b
          FROM holdings_v2 WHERE is_latest AND quarter='{COVERAGE_QUARTER}'
          GROUP BY 1
        ),
        with_fund AS (
          SELECT DISTINCT rollup_entity_id
          FROM fund_holdings_v2
          WHERE is_latest AND quarter='{COVERAGE_QUARTER}' AND asset_category='EC'
            AND rollup_entity_id IS NOT NULL
        )
        SELECT inst_filers.manager_type,
               COUNT(*) AS n_filers,
               SUM(inst_filers.aum_b) AS aum_b
        FROM inst_filers
        LEFT JOIN with_fund ON with_fund.rollup_entity_id = inst_filers.entity_id
        WHERE with_fund.rollup_entity_id IS NULL
        GROUP BY 1 ORDER BY 3 DESC
    """).fetchdf()
    print(f"\n  ALL 13F filers WITH NO fund-tier rollup link, by manager_type:")
    print(full.to_string(index=False))
    full.to_csv(WORKDIR / "cp-5-bundle-c-view2-coverage.csv", index=False)
    print(f"\n  Wrote {WORKDIR / 'cp-5-bundle-c-view2-coverage.csv'}")

    # Phase 8.2 — alt source assessment
    print()
    print("=" * 78)
    print("PHASE 8.2 — alternative source assessment")
    print("=" * 78)
    print("""
  A. Hedge funds — 13F-D (hedged disclosure) provides PM-level decomposition
     where filed. Inspect 13F-D coverage in `holdings_v2`:""")
    print("    holdings_v2 has no filing_type column — 13F-HR vs 13F-D not")
    print("    distinguishable in the current loader. Distinct 13F-D ingest is")
    print("    a Pipeline-1 (13D/G) backlog item; not part of CP-5.")

    print("""
  B. SMAs — Form ADV Schedule D provides SMA aggregate AUM, no positions.
  C. Pensions — public pensions file 13F directly; PM data in policy reports.
  D. Family offices — typically file 13F under one entity; PM rare.
""")

    # Phase 8.3 — recommendation
    print("=" * 78)
    print("PHASE 8.3 — View 2 design recommendation")
    print("=" * 78)
    print("""
  View 2 SCOPE (recommendation for chat lock):

  Tier 1 (already exists): N-PORT-filing registered funds — 1,954 funds /
    $31.6T EC AUM. Existing Fund Portfolio + portfolio_context readers.

  Tier 2 (incremental): 13D/G partial holdings for >5% positions on non-N-PORT
    filers. Pipeline P1 already partially ingests (memory note). Surface as
    "PM partial" with explicit coverage caveat.

  Tier 3 (structural gap): hedge fund / SMA / pension / family office /
    sovereign 13F-only. NO public PM-level decomposition.
    Display as institutional-tier with "no fund decomposition" flag.
    Document. Do NOT scope as a CP-5 deliverable.

  cp-5-discovery §5 already locks this scope; Bundle C confirms the
  cohort sizing and recommends MINIMAL incremental work for View 2 (just
  the entity-keyed integration with the new top-parent rollup, plus the
  Tier 3 surfacing).
""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
