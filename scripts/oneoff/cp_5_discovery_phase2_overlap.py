"""CP-5 discovery — Phase 2: empirical 13F vs N-PORT position-level overlap.

Read-only. For top-20 'both' cohort top-parents from Phase 1, samples 3 tickers
(AAPL large-cap, NEE mid-cap energy, AVDX small-cap) and compares position-level
AUM disclosed in 13F vs in fund_holdings_v2 (asset_category='EC' only).

Output:
  data/working/cp-5-overlap-probe.csv
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import pandas as pd

DB_PATH = "/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership/data/13f.duckdb"
QUARTER = "2025Q4"
SAMPLE_TICKERS = ["AAPL", "NEE", "AVDX"]


def main() -> int:
    con = duckdb.connect(DB_PATH, read_only=True)

    cov = pd.read_csv("data/working/cp-5-top-parent-coverage-matrix.csv")
    both = cov[cov["coverage_class"] == "both"].copy()
    cohort = both.head(20).reset_index(drop=True)
    print(f"=== cohort (top-20 'both' by combined AUM, {QUARTER}) ===")
    print(cohort[["top_parent_entity_id", "top_parent_canonical_name",
                  "thirteen_f_aum_billions", "fund_tier_aum_billions",
                  "combined_aum_billions"]].to_string(index=False))

    inst_to_tp = pd.read_parquet("scripts/oneoff/_cp5_inst_to_topparent.parquet")
    fund_chain = pd.read_parquet("scripts/oneoff/_cp5_fund_chain.parquet")
    con.register("inst_to_tp_df", inst_to_tp)
    con.register("fund_chain_df", fund_chain)

    rows = []
    for _, c in cohort.iterrows():
        tp_id = int(c["top_parent_entity_id"])
        tp_name = c["top_parent_canonical_name"]

        for ticker in SAMPLE_TICKERS:
            # Set A: 13F position aggregated up to top-parent
            set_a = con.execute(f"""
                SELECT
                    SUM(h.market_value_usd) / 1e9 AS aum_b,
                    COUNT(*) AS n_filers,
                    COUNT(DISTINCT h.entity_id) AS n_entities
                FROM holdings_v2 h
                JOIN inst_to_tp_df itp ON itp.entity_id = h.entity_id
                WHERE h.is_latest = TRUE
                  AND h.quarter = '{QUARTER}'
                  AND h.ticker = '{ticker}'
                  AND itp.top_parent_entity_id = {tp_id}
            """).fetchone()
            a_aum = float(set_a[0] or 0)
            a_filers = int(set_a[1] or 0)

            # Set B: fund-tier (N-PORT EC) aggregated up to top-parent
            set_b = con.execute(f"""
                SELECT
                    SUM(fh.market_value_usd) / 1e9 AS aum_b,
                    COUNT(*) AS n_funds,
                    COUNT(DISTINCT fh.fund_cik) AS n_fund_ciks
                FROM fund_holdings_v2 fh
                JOIN fund_chain_df fc ON fc.fund_entity_id = fh.entity_id
                WHERE fh.is_latest = TRUE
                  AND fh.quarter = '{QUARTER}'
                  AND fh.asset_category = 'EC'
                  AND fh.ticker = '{ticker}'
                  AND fc.top_parent_entity_id = {tp_id}
            """).fetchone()
            b_aum = float(set_b[0] or 0)
            b_funds = int(set_b[1] or 0)

            # Classification
            if a_aum == 0 and b_aum == 0:
                cls = "neither"
                ratio = None
            elif a_aum == 0:
                cls = "fund_only"
                ratio = float("inf")
            elif b_aum == 0:
                cls = "13F_only"
                ratio = 0.0
            else:
                ratio = b_aum / a_aum
                if 0.85 <= ratio <= 1.15:
                    cls = "13F_covers_fund"  # near-equal
                elif ratio > 1.15:
                    cls = "fund_extends_13F"
                else:
                    cls = "13F_dominant"

            rows.append({
                "top_parent_entity_id": tp_id,
                "top_parent_canonical_name": tp_name,
                "ticker": ticker,
                "set_A_13F_aum_b": round(a_aum, 4),
                "set_A_filers": a_filers,
                "set_B_fund_aum_b": round(b_aum, 4),
                "set_B_funds": b_funds,
                "ratio_B_over_A": round(ratio, 3) if ratio is not None and ratio != float("inf") else ratio,
                "classification": cls,
            })

    out = pd.DataFrame(rows)
    out_path = Path("data/working/cp-5-overlap-probe.csv")
    out.to_csv(out_path, index=False)
    print(f"\nwrote {out_path} ({len(out)} rows)")
    print()
    print("=== full probe results ===")
    pd.set_option("display.max_rows", 100)
    pd.set_option("display.width", 240)
    print(out.to_string(index=False))

    print()
    print("=== classification distribution ===")
    print(out["classification"].value_counts().to_string())

    print()
    print("=== aggregate ratio summary (excluding neither / fund_only / 13F_only) ===")
    o = out[out["classification"].isin(["13F_covers_fund", "fund_extends_13F", "13F_dominant"])]
    if len(o):
        print(f"  pairs: {len(o)}")
        print(f"  median ratio B/A: {o['ratio_B_over_A'].median():.3f}")
        print(f"  mean ratio B/A:   {o['ratio_B_over_A'].mean():.3f}")
        print(f"  p10/p90:          {o['ratio_B_over_A'].quantile(0.1):.3f} / {o['ratio_B_over_A'].quantile(0.9):.3f}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
