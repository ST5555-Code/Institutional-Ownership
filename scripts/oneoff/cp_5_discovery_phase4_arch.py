"""CP-5 discovery — Phase 4: architecture probe (view vs precomputed table).

Read-only. Benchmarks the inline-view R5 query for three reader use cases:
  (a) Top-25 holders of a single ticker (Register query1 shape)
  (b) Top-50 holders by combined AUM (Conviction shape)
  (c) All positions for a single top-parent (Fund Portfolio shape)

Then estimates row count for a precomputed unified holdings table.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import duckdb
import pandas as pd

DB_PATH = "/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership/data/13f.duckdb"
QUARTER = "2025Q4"


def _time_query(con, sql, params=()):
    t0 = time.perf_counter()
    df = con.execute(sql, params).fetchdf()
    dt = time.perf_counter() - t0
    return df, dt


def main() -> int:
    con = duckdb.connect(DB_PATH, read_only=True)

    inst_to_tp = pd.read_parquet("scripts/oneoff/_cp5_inst_to_topparent.parquet")
    fund_chain = pd.read_parquet("scripts/oneoff/_cp5_fund_chain.parquet")
    con.register("inst_to_tp_df", inst_to_tp)
    con.register("fund_chain_df", fund_chain)

    # === R5 inline view as a CTE template ===
    # MAX(13F_aggregated, fund_tier_aggregated) per (top_parent, ticker, cusip)
    R5_VIEW_SQL = f"""
    WITH thirteen_f AS (
        SELECT itp.top_parent_entity_id AS tp_id,
               h.ticker, h.cusip,
               SUM(h.market_value_usd) AS aum_13f
        FROM holdings_v2 h
        JOIN inst_to_tp_df itp ON itp.entity_id = h.entity_id
        WHERE h.is_latest = TRUE AND h.quarter = '{QUARTER}'
        GROUP BY 1,2,3
    ),
    fund_tier AS (
        SELECT fc.top_parent_entity_id AS tp_id,
               fh.ticker, fh.cusip,
               SUM(fh.market_value_usd) AS aum_fund
        FROM fund_holdings_v2 fh
        JOIN fund_chain_df fc ON fc.fund_entity_id = fh.entity_id
        WHERE fh.is_latest = TRUE AND fh.quarter = '{QUARTER}'
          AND fh.asset_category = 'EC'
        GROUP BY 1,2,3
    ),
    unified AS (
        SELECT COALESCE(t.tp_id, f.tp_id) AS top_parent_entity_id,
               COALESCE(t.ticker, f.ticker) AS ticker,
               COALESCE(t.cusip, f.cusip) AS cusip,
               COALESCE(t.aum_13f, 0) AS aum_13f,
               COALESCE(f.aum_fund, 0) AS aum_fund,
               GREATEST(COALESCE(t.aum_13f, 0), COALESCE(f.aum_fund, 0)) AS aum_dedup_max,
               CASE
                 WHEN t.aum_13f IS NULL THEN 'fund_only'
                 WHEN f.aum_fund IS NULL THEN '13F_only'
                 WHEN t.aum_13f >= f.aum_fund THEN '13F_wins'
                 ELSE 'fund_wins'
               END AS source_winner
        FROM thirteen_f t
        FULL OUTER JOIN fund_tier f
          ON t.tp_id = f.tp_id AND t.ticker = f.ticker AND t.cusip = f.cusip
    )
    """

    # === Use case (a) — Top-25 holders for AAPL ===
    sql_a = R5_VIEW_SQL + """
    SELECT u.top_parent_entity_id, ec.display_name AS holder, u.aum_dedup_max, u.source_winner
    FROM unified u
    LEFT JOIN entity_current ec ON ec.entity_id = u.top_parent_entity_id
    WHERE u.ticker = 'AAPL'
    ORDER BY u.aum_dedup_max DESC
    LIMIT 25
    """
    runs_a = []
    df_a, dt = _time_query(con, sql_a)
    runs_a.append(dt)
    df_a, dt = _time_query(con, sql_a)  # warm
    runs_a.append(dt)
    print(f"=== Use case (a) — Top-25 holders of AAPL ===")
    print(f"  cold: {runs_a[0]*1000:.1f} ms   warm: {runs_a[1]*1000:.1f} ms")
    print(df_a.head(15).to_string(index=False))

    # === Use case (b) — Top-50 holders by combined AUM ===
    sql_b = R5_VIEW_SQL + """
    , agg AS (
        SELECT top_parent_entity_id, SUM(aum_dedup_max) AS combined_aum
        FROM unified
        GROUP BY 1
    )
    SELECT a.top_parent_entity_id, ec.display_name AS holder, a.combined_aum / 1e9 AS combined_aum_b
    FROM agg a
    LEFT JOIN entity_current ec ON ec.entity_id = a.top_parent_entity_id
    ORDER BY a.combined_aum DESC
    LIMIT 50
    """
    runs_b = []
    df_b, dt = _time_query(con, sql_b)
    runs_b.append(dt)
    df_b, dt = _time_query(con, sql_b)
    runs_b.append(dt)
    print(f"\n=== Use case (b) — Top-50 holders by combined AUM ===")
    print(f"  cold: {runs_b[0]*1000:.1f} ms   warm: {runs_b[1]*1000:.1f} ms")
    print(df_b.head(10).to_string(index=False))

    # === Use case (c) — All positions for Vanguard top-parent (4375) ===
    sql_c = R5_VIEW_SQL + """
    SELECT u.ticker, u.cusip, u.aum_dedup_max, u.source_winner, u.aum_13f, u.aum_fund
    FROM unified u
    WHERE u.top_parent_entity_id = 4375
    ORDER BY u.aum_dedup_max DESC
    """
    runs_c = []
    df_c, dt = _time_query(con, sql_c)
    runs_c.append(dt)
    df_c, dt = _time_query(con, sql_c)
    runs_c.append(dt)
    print(f"\n=== Use case (c) — All Vanguard (eid=4375) positions, R5 dedup ===")
    print(f"  cold: {runs_c[0]*1000:.1f} ms   warm: {runs_c[1]*1000:.1f} ms")
    print(f"  rows: {len(df_c)}")
    print(df_c.head(10).to_string(index=False))

    # === Precomputed table sizing ===
    print(f"\n=== Precomputed-table sizing ===")
    h13f_n = con.execute('SELECT COUNT(*) FROM holdings_v2 WHERE is_latest=TRUE').fetchone()[0]
    fh_n = con.execute("SELECT COUNT(*) FROM fund_holdings_v2 WHERE is_latest=TRUE AND asset_category='EC'").fetchone()[0]
    print(f"  current holdings_v2 (is_latest=TRUE, all 4Q): {h13f_n:,}")
    print(f"  current fund_holdings_v2 (is_latest=TRUE, all 6Q, EC only): {fh_n:,}")
    # Precomputed unified row estimate per quarter
    n_rows_per_q_sql = R5_VIEW_SQL + " SELECT COUNT(*) FROM unified"
    n_unified, _ = _time_query(con, n_rows_per_q_sql)
    print(f"  unified rows per quarter (R5 dedup): {int(n_unified.iloc[0,0]):,}")
    print(f"  estimated 4Q rolling unified table: ~{int(n_unified.iloc[0,0]) * 4:,}")
    print(f"  estimated 6Q rolling unified table: ~{int(n_unified.iloc[0,0]) * 6:,}")

    # Recommendation
    max_warm_ms = max(runs_a[1], runs_b[1], runs_c[1]) * 1000
    print(f"\n=== Recommendation ===")
    print(f"  max warm runtime across 3 use cases: {max_warm_ms:.1f} ms")
    if max_warm_ms < 500:
        rec = "INLINE VIEW — runtime is well under 500ms; precomputed table not warranted."
    elif max_warm_ms < 3000:
        rec = "EITHER — within range; prefer view for simplicity unless caller requires sub-100ms."
    else:
        rec = "PRECOMPUTED TABLE — runtime exceeds 3s; build refresh on N-PORT/13F ingestion (per-quarter)."
    print(f"  → {rec}")

    # Write a small summary CSV
    bench = pd.DataFrame([
        {"use_case": "(a) Top-25 holders for AAPL", "cold_ms": runs_a[0]*1000, "warm_ms": runs_a[1]*1000},
        {"use_case": "(b) Top-50 by combined AUM", "cold_ms": runs_b[0]*1000, "warm_ms": runs_b[1]*1000},
        {"use_case": "(c) All Vanguard positions",  "cold_ms": runs_c[0]*1000, "warm_ms": runs_c[1]*1000},
    ])
    out_path = Path("data/working/cp-5-arch-bench.csv")
    bench.to_csv(out_path, index=False)
    print(f"\nwrote {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
