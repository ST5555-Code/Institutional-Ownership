"""CP-5 comprehensive discovery — Bundle A, Probe 2: N-PORT data completeness.

Read-only investigation. Sizes and characterizes five N-PORT data-quality
gaps that affect fund-tier AUM correctness:
  2.1 — orphan funds (4 layers: missing fund_universe, missing entity,
        NULL rollup_entity_id, NULL fund_strategy)
  2.2 — historical drift (multi-accession per (series_id, report_month))
  2.3 — non-equity coverage (asset_category beyond EC)
  2.4 — NULL fund_strategy cohort (fund_universe + fund_holdings_v2 facets)
  2.5 — monthly N-PORT scope (report_month coverage)

Outputs:
  data/working/cp-5-bundle-a-orphan-cohort.csv
  data/working/cp-5-bundle-a-historical-drift.csv
  data/working/cp-5-bundle-a-null-fund-strategy.csv

Refs ROADMAP fund-holdings-orphan-investigation, historical-drift-audit,
fund-classification-by-composition.
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


def probe_2_1_orphans(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Probe 2.1 — orphan funds across 4 layers."""
    print("\n" + "=" * 72)
    print("PROBE 2.1 — orphan funds (4 layers)")
    print("=" * 72)

    rows: list[dict] = []

    # Layer A — fund-typed entities without a fund_universe row
    print("\n  Layer A — fund-typed entities without fund_universe row")
    a_sql = f"""
    WITH orphans AS (
      SELECT e.entity_id, e.canonical_name
      FROM entities e
      WHERE e.entity_type = 'fund'
        AND NOT EXISTS (
          SELECT 1 FROM fund_universe fu
          JOIN entity_identifiers ei ON ei.entity_id = e.entity_id
          WHERE ei.identifier_type = 'series_id'
            AND ei.identifier_value = fu.series_id
            AND ei.valid_to = {SENTINEL}
        )
    )
    SELECT COUNT(*) AS n,
           (SELECT LIST(canonical_name ORDER BY canonical_name)[1:20]
            FROM orphans) AS samples
    FROM orphans
    """
    a = con.execute(a_sql).fetchdf()
    print(f"    n={a['n'].iloc[0]:,}; sample names: {a['samples'].iloc[0][:5]}")
    rows.append({"layer": "A_no_fund_universe_row", "n_rows": int(a["n"].iloc[0]),
                 "aum_b": None})

    # Layer B — fund_holdings_v2.entity_id with no matching entities row
    print("\n  Layer B — fund_holdings_v2.entity_id has no entities row")
    b = con.execute(f"""
    SELECT COUNT(*) AS n_rows, COUNT(DISTINCT fh.entity_id) AS n_distinct,
           SUM(fh.market_value_usd) / 1e9 AS aum_b
    FROM fund_holdings_v2 fh
    WHERE fh.is_latest AND fh.entity_id IS NOT NULL
      AND NOT EXISTS (SELECT 1 FROM entities e WHERE e.entity_id = fh.entity_id)
    """).fetchdf()
    print(f"    n_rows={int(b['n_rows'].iloc[0]):,}; "
          f"distinct_eids={int(b['n_distinct'].iloc[0]):,}")
    rows.append({"layer": "B_orphan_entity_id", "n_rows": int(b["n_rows"].iloc[0]),
                 "aum_b": float(b["aum_b"].iloc[0] or 0.0)})

    # Layer C — NULL rollup_entity_id or dm_rollup_entity_id
    print("\n  Layer C — NULL rollup_entity_id or dm_rollup_entity_id")
    c = con.execute(f"""
    SELECT COUNT(*) AS n_rows,
           SUM(market_value_usd) / 1e9 AS aum_b,
           COUNT(DISTINCT fund_cik) AS n_funds,
           COUNT(DISTINCT series_id) AS n_series
    FROM fund_holdings_v2
    WHERE is_latest AND (rollup_entity_id IS NULL OR dm_rollup_entity_id IS NULL)
    """).fetchdf()
    print(f"    n_rows={int(c['n_rows'].iloc[0]):,}; "
          f"aum_b={float(c['aum_b'].iloc[0]):.2f}; "
          f"distinct funds={int(c['n_funds'].iloc[0])}, "
          f"series={int(c['n_series'].iloc[0])}")
    rows.append({"layer": "C_null_rollup", "n_rows": int(c["n_rows"].iloc[0]),
                 "aum_b": float(c["aum_b"].iloc[0])})

    # Layer C cause sample — series_id breakdown
    c_cause = con.execute(f"""
    SELECT
      CASE
        WHEN series_id IS NULL THEN 'series_NULL'
        WHEN series_id = '' THEN 'series_empty'
        WHEN series_id LIKE 'SYN_%' THEN 'series_synthetic'
        WHEN series_id LIKE 'S0%' THEN 'series_normal'
        ELSE 'series_other'
      END AS series_bucket,
      COUNT(*) AS n_rows,
      SUM(market_value_usd) / 1e9 AS aum_b,
      COUNT(DISTINCT fund_cik) AS n_funds
    FROM fund_holdings_v2
    WHERE is_latest AND (rollup_entity_id IS NULL OR dm_rollup_entity_id IS NULL)
    GROUP BY 1 ORDER BY n_rows DESC
    """).fetchdf()
    print(f"\n    Layer C cause breakdown:")
    print(c_cause.to_string(index=False))

    # Layer D — fund_universe NULL fund_strategy (cross-ref to 2.4)
    print("\n  Layer D — fund_universe NULL fund_strategy (cross-ref Probe 2.4)")
    d = con.execute("""
    SELECT
      COUNT(*) AS n_total,
      SUM(CASE WHEN fund_strategy IS NULL THEN 1 ELSE 0 END) AS n_null,
      SUM(CASE WHEN fund_strategy = 'unknown' THEN 1 ELSE 0 END) AS n_unknown
    FROM fund_universe
    """).fetchdf()
    print(f"    fund_universe: total={int(d['n_total'].iloc[0]):,}, "
          f"null={int(d['n_null'].iloc[0])}, unknown={int(d['n_unknown'].iloc[0])}")
    rows.append({"layer": "D_null_fund_strategy",
                 "n_rows": int(d["n_null"].iloc[0]) + int(d["n_unknown"].iloc[0]),
                 "aum_b": 0.0})

    summary = pd.DataFrame(rows)
    summary.to_csv(WORKDIR / "cp-5-bundle-a-orphan-cohort.csv", index=False)
    print(f"\n  Wrote cp-5-bundle-a-orphan-cohort.csv")

    return summary


def probe_2_2_drift(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Probe 2.2 — historical drift audit (multi-accession per series_month)."""
    print("\n" + "=" * 72)
    print("PROBE 2.2 — historical drift audit")
    print("=" * 72)

    drift = con.execute("""
    WITH per_series_month AS (
      SELECT series_id, quarter, report_month,
             COUNT(DISTINCT accession_number) AS n_acc,
             COUNT(*) AS n_rows
      FROM fund_holdings_v2
      WHERE is_latest
        AND series_id IS NOT NULL
        AND series_id NOT IN ('UNKNOWN', '')
        AND series_id NOT LIKE 'SYN_%'
      GROUP BY 1, 2, 3
    )
    SELECT
      MAX(n_rows) AS max_rows_per_bucket,
      COUNT(*) FILTER (WHERE n_acc > 1) AS n_multi_accession_buckets,
      COUNT(*) AS n_buckets_total,
      AVG(n_acc) AS mean_acc_per_bucket
    FROM per_series_month
    """).fetchdf()
    print(f"  Buckets total (real series_id, is_latest): "
          f"{int(drift['n_buckets_total'].iloc[0]):,}")
    print(f"  Buckets with >1 accession: "
          f"{int(drift['n_multi_accession_buckets'].iloc[0]):,}")
    print(f"  Mean accessions per bucket: "
          f"{float(drift['mean_acc_per_bucket'].iloc[0]):.4f}")

    # Drill into the actual drift cohort
    drift_rows = con.execute("""
    WITH per_series_month AS (
      SELECT series_id, quarter, report_month,
             COUNT(DISTINCT accession_number) AS n_acc,
             COUNT(*) AS n_rows,
             SUM(market_value_usd) / 1e9 AS aum_b
      FROM fund_holdings_v2
      WHERE is_latest
        AND series_id IS NOT NULL
        AND series_id NOT IN ('UNKNOWN', '')
        AND series_id NOT LIKE 'SYN_%'
      GROUP BY 1, 2, 3
    )
    SELECT *
    FROM per_series_month
    WHERE n_acc > 1
    ORDER BY n_acc DESC, aum_b DESC
    LIMIT 50
    """).fetchdf()
    print(f"\n  Top drift buckets (multi-accession) — top 30:")
    print(drift_rows.head(30).to_string(index=False))

    # SYN_ synthetics — how many is_latest rows do they hold?
    syn = con.execute("""
    SELECT
      COUNT(*) AS n_rows,
      SUM(market_value_usd) / 1e9 AS aum_b,
      COUNT(DISTINCT series_id) AS n_synthetic_series
    FROM fund_holdings_v2
    WHERE is_latest AND series_id LIKE 'SYN_%'
    """).fetchdf()
    print(f"\n  Synthetic series (SYN_*): "
          f"{int(syn['n_rows'].iloc[0]):,} rows / "
          f"${float(syn['aum_b'].iloc[0]):.1f}B / "
          f"{int(syn['n_synthetic_series'].iloc[0])} synthetic series")

    drift_rows.to_csv(WORKDIR / "cp-5-bundle-a-historical-drift.csv", index=False)
    print(f"\n  Wrote cp-5-bundle-a-historical-drift.csv")
    return drift_rows


def probe_2_3_non_equity(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Probe 2.3 — non-equity coverage assessment."""
    print("\n" + "=" * 72)
    print("PROBE 2.3 — non-equity coverage")
    print("=" * 72)

    cov = con.execute(f"""
    SELECT asset_category,
           COUNT(*) AS n_rows,
           SUM(market_value_usd) / 1e9 AS aum_b
    FROM fund_holdings_v2
    WHERE is_latest AND quarter = '{COVERAGE_QUARTER}'
    GROUP BY 1
    ORDER BY 3 DESC NULLS LAST
    """).fetchdf()
    print(f"\n  fund_holdings_v2 asset_category — 2025Q4 is_latest:")
    print(cov.to_string(index=False))

    total_aum = float(cov["aum_b"].sum())
    ec_aum = float(cov[cov["asset_category"] == "EC"]["aum_b"].iloc[0])
    print(f"\n  EC share of total: {ec_aum:.1f} / {total_aum:.1f} = "
          f"{100 * ec_aum / total_aum:.1f}%")
    return cov


def probe_2_4_null_strategy(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Probe 2.4 — NULL fund_strategy cohort."""
    print("\n" + "=" * 72)
    print("PROBE 2.4 — NULL fund_strategy cohort")
    print("=" * 72)

    universe = con.execute("""
    SELECT
      COUNT(*) AS n_total,
      SUM(CASE WHEN fund_strategy IS NULL THEN 1 ELSE 0 END) AS n_null,
      SUM(CASE WHEN fund_strategy = 'unknown' THEN 1 ELSE 0 END) AS n_unknown,
      SUM(CASE WHEN fund_strategy = 'final_filing' THEN 1 ELSE 0 END) AS n_final_filing
    FROM fund_universe
    """).fetchdf()
    print(f"\n  fund_universe (all 13,924 rows):")
    print(universe.to_string(index=False))

    holdings = con.execute(f"""
    SELECT
      COUNT(*) AS n_rows,
      SUM(CASE WHEN fund_strategy_at_filing IS NULL THEN 1 ELSE 0 END) AS n_null_at_filing,
      SUM(CASE WHEN fund_strategy_at_filing = 'final_filing' THEN 1 ELSE 0 END) AS n_final_filing,
      SUM(market_value_usd) / 1e9 AS aum_b_total,
      SUM(CASE WHEN fund_strategy_at_filing = 'final_filing'
               THEN market_value_usd ELSE 0 END) / 1e9 AS aum_b_final_filing
    FROM fund_holdings_v2
    WHERE is_latest AND quarter = '{COVERAGE_QUARTER}' AND asset_category = 'EC'
    """).fetchdf()
    print(f"\n  fund_holdings_v2 (2025Q4 EC):")
    print(holdings.to_string(index=False))

    by_top_parent: pd.DataFrame
    if int(holdings["n_final_filing"].iloc[0]) > 0:
        by_top_parent = con.execute(f"""
        SELECT dm_rollup_entity_id, dm_rollup_name,
               COUNT(*) AS n_rows,
               SUM(market_value_usd) / 1e9 AS aum_b
        FROM fund_holdings_v2
        WHERE is_latest AND quarter = '{COVERAGE_QUARTER}' AND asset_category = 'EC'
          AND fund_strategy_at_filing = 'final_filing'
        GROUP BY 1, 2 ORDER BY aum_b DESC LIMIT 20
        """).fetchdf()
        print(f"\n  final_filing rows by dm_rollup top-20:")
        print(by_top_parent.to_string(index=False))
    else:
        by_top_parent = pd.DataFrame()
        print("\n  No final_filing rows in 2025Q4 EC.")

    # Save the per-strategy fund_universe pivot for reference
    pivot = con.execute("""
    SELECT fund_strategy, COUNT(*) AS n,
           SUM(total_net_assets) / 1e9 AS aum_b
    FROM fund_universe
    GROUP BY 1 ORDER BY 2 DESC NULLS LAST
    """).fetchdf()
    print(f"\n  fund_universe by strategy (current state):")
    print(pivot.to_string(index=False))
    pivot.to_csv(WORKDIR / "cp-5-bundle-a-null-fund-strategy.csv", index=False)
    print(f"\n  Wrote cp-5-bundle-a-null-fund-strategy.csv")
    return pivot


def probe_2_5_monthly(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Probe 2.5 — monthly N-PORT scope (report_month coverage)."""
    print("\n" + "=" * 72)
    print("PROBE 2.5 — monthly N-PORT scope")
    print("=" * 72)

    months = con.execute("""
    SELECT report_month,
           COUNT(*) AS n_rows,
           COUNT(DISTINCT series_id) AS n_series,
           SUM(market_value_usd) / 1e9 AS aum_b
    FROM fund_holdings_v2
    WHERE is_latest AND report_month BETWEEN '2025-01' AND '2026-12'
    GROUP BY 1 ORDER BY 1
    """).fetchdf()
    print(f"\n  Monthly report_month coverage (is_latest, 2025-2026):")
    print(months.to_string(index=False))

    # Quarter-end vs non-quarter-end split
    months["is_quarter_end"] = months["report_month"].str.endswith(
        ("-03", "-06", "-09", "-12")
    )
    qe = months[months["is_quarter_end"]]
    nq = months[~months["is_quarter_end"]]
    print(f"\n  Quarter-end months — n={len(qe)}, "
          f"avg series/month={qe['n_series'].mean():.0f}")
    print(f"  Non-quarter-end months — n={len(nq)}, "
          f"avg series/month={nq['n_series'].mean():.0f}")

    # NPORT-MP awareness check: every fund publicly files at quarter-end of
    # ITS fiscal year. Funds with non-Dec fiscal years have non-Dec quarter-
    # end filings. Series counts in non-cal-quarter months reflect those
    # off-cycle fund filings, NOT monthly NPORT-MP private filings.
    print(
        "\n  Note: monthly NPORT-MP (private intra-quarter) is NOT loaded; "
        "non-cal-quarter months above reflect funds with non-December "
        "fiscal years filing public NPORT-P at their fiscal quarter-ends."
    )
    return months


def main() -> int:
    con = duckdb.connect(DB_PATH, read_only=True)
    WORKDIR.mkdir(parents=True, exist_ok=True)

    probe_2_1_orphans(con)
    probe_2_2_drift(con)
    probe_2_3_non_equity(con)
    probe_2_4_null_strategy(con)
    probe_2_5_monthly(con)

    print("\n" + "=" * 72)
    print("Probe 2 complete.")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
