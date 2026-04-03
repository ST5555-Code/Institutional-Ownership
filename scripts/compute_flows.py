#!/usr/bin/env python3
"""
compute_flows.py — Compute institutional investor flow analytics.

Set-based SQL approach: bulk INSERT per period using window functions.
No per-ticker loop — all tickers processed in a single pass per period.

Usage: python3 scripts/compute_flows.py
"""

import sys
import time
from datetime import datetime

import duckdb
import pandas as pd

from db import set_staging_mode, get_db_path
from config import QUARTERS, LATEST_QUARTER, FIRST_QUARTER, PREV_QUARTER, FLOW_PERIODS

PERIODS = FLOW_PERIODS
LATEST_Q = LATEST_QUARTER


def create_tables(con):
    con.execute("DROP TABLE IF EXISTS investor_flows")
    con.execute("""
        CREATE TABLE investor_flows (
            ticker VARCHAR, period VARCHAR, quarter_from VARCHAR, quarter_to VARCHAR,
            inst_parent_name VARCHAR, manager_type VARCHAR,
            from_shares DOUBLE, to_shares DOUBLE, net_shares DOUBLE, pct_change DOUBLE,
            from_value DOUBLE, to_value DOUBLE, from_price DOUBLE,
            price_adj_flow DOUBLE, raw_flow DOUBLE, price_effect DOUBLE,
            is_new_entry BOOLEAN, is_exit BOOLEAN,
            flow_4q DOUBLE, flow_2q DOUBLE, momentum_ratio DOUBLE, momentum_signal VARCHAR
        )
    """)
    con.execute("DROP TABLE IF EXISTS ticker_flow_stats")
    con.execute("""
        CREATE TABLE ticker_flow_stats (
            ticker VARCHAR, quarter_from VARCHAR, quarter_to VARCHAR,
            flow_intensity_total DOUBLE, flow_intensity_active DOUBLE,
            flow_intensity_passive DOUBLE,
            churn_nonpassive DOUBLE, churn_active DOUBLE, computed_at TIMESTAMP
        )
    """)


def compute_period_flows(con, period_label, q_from, q_to):
    """Compute all investor flows for a single period using set-based SQL."""
    print(f"  Computing {period_label} ({q_from} → {q_to})...", flush=True)
    t0 = time.time()

    con.execute(f"""
        INSERT INTO investor_flows (
            ticker, period, quarter_from, quarter_to,
            inst_parent_name, manager_type,
            from_shares, to_shares, net_shares, pct_change,
            from_value, to_value, from_price,
            price_adj_flow, raw_flow, price_effect,
            is_new_entry, is_exit,
            flow_4q, flow_2q, momentum_ratio, momentum_signal
        )
        WITH q_from AS (
            SELECT ticker,
                   COALESCE(inst_parent_name, manager_name) as investor,
                   MAX(manager_type) as manager_type,
                   SUM(shares) as shares,
                   SUM(market_value_usd) as value
            FROM holdings WHERE quarter = '{q_from}'
            GROUP BY ticker, investor
        ),
        q_to AS (
            SELECT ticker,
                   COALESCE(inst_parent_name, manager_name) as investor,
                   MAX(manager_type) as manager_type,
                   SUM(shares) as shares,
                   SUM(market_value_usd) as value
            FROM holdings WHERE quarter = '{q_to}'
            GROUP BY ticker, investor
        ),
        combined AS (
            SELECT
                COALESCE(t.ticker, f.ticker) as ticker,
                COALESCE(t.investor, f.investor) as investor,
                COALESCE(t.manager_type, f.manager_type) as manager_type,
                COALESCE(f.shares, 0) as from_shares,
                COALESCE(t.shares, 0) as to_shares,
                COALESCE(f.value, 0) as from_value,
                COALESCE(t.value, 0) as to_value
            FROM q_to t
            FULL OUTER JOIN q_from f ON t.ticker = f.ticker AND t.investor = f.investor
        ),
        flows AS (
            SELECT *,
                to_shares - from_shares as net_shares,
                CASE WHEN from_shares > 0 THEN (to_shares - from_shares) / from_shares ELSE NULL END as pct_change,
                from_shares = 0 AND to_shares > 0 as is_new_entry,
                from_shares > 0 AND to_shares = 0 as is_exit,
                CASE WHEN from_shares > 0 AND from_value > 0 THEN from_value / from_shares ELSE NULL END as from_price,
                CASE WHEN from_shares > 0 AND from_value > 0
                    THEN (to_shares - from_shares) * (from_value / from_shares)
                    ELSE NULL END as price_adj_flow,
                to_value - from_value as raw_flow,
                CASE WHEN from_shares > 0 AND from_value > 0
                    THEN (to_value - from_value) - ((to_shares - from_shares) * (from_value / from_shares))
                    ELSE NULL END as price_effect
            FROM combined
            WHERE from_shares > 0 OR to_shares > 0
        )
        SELECT
            ticker, '{period_label}', '{q_from}', '{q_to}',
            investor, manager_type,
            CASE WHEN from_shares > 0 THEN from_shares ELSE NULL END,
            CASE WHEN to_shares > 0 THEN to_shares ELSE NULL END,
            CASE WHEN net_shares != 0 THEN net_shares ELSE NULL END,
            pct_change,
            CASE WHEN from_value > 0 THEN from_value ELSE NULL END,
            CASE WHEN to_value > 0 THEN to_value ELSE NULL END,
            from_price, price_adj_flow,
            CASE WHEN raw_flow != 0 THEN raw_flow ELSE NULL END,
            price_effect,
            is_new_entry, is_exit,
            NULL, NULL, NULL, NULL  -- momentum fields filled in next pass
        FROM flows
    """)

    count = con.execute(f"""
        SELECT COUNT(*) FROM investor_flows WHERE period = '{period_label}'
    """).fetchone()[0]
    elapsed = time.time() - t0
    print(f"    {count:,} flow rows in {elapsed:.1f}s", flush=True)


def compute_momentum(con):
    """Fill momentum fields using 4Q and 1Q flow data."""
    print("  Computing momentum signals...", flush=True)
    con.execute("""
        UPDATE investor_flows f
        SET flow_4q = m4.price_adj_flow
        FROM investor_flows m4
        WHERE f.ticker = m4.ticker AND f.inst_parent_name = m4.inst_parent_name
          AND m4.period = '4Q'
          AND f.flow_4q IS NULL
    """)
    con.execute("""
        UPDATE investor_flows f
        SET flow_2q = m1.price_adj_flow
        FROM investor_flows m1
        WHERE f.ticker = m1.ticker AND f.inst_parent_name = m1.inst_parent_name
          AND m1.period = '1Q'
          AND f.flow_2q IS NULL
    """)
    con.execute("""
        UPDATE investor_flows
        SET momentum_ratio = CASE WHEN flow_4q != 0 AND flow_2q IS NOT NULL
                                  THEN flow_2q / flow_4q ELSE NULL END
    """)
    con.execute("""
        UPDATE investor_flows
        SET momentum_signal = CASE
            WHEN manager_type = 'passive' THEN NULL
            WHEN is_new_entry THEN 'NEW'
            WHEN is_exit THEN 'EXIT'
            WHEN momentum_ratio IS NULL THEN NULL
            WHEN momentum_ratio > 0.65 THEN 'ACCEL'
            WHEN momentum_ratio >= 0.35 THEN 'STEADY'
            WHEN momentum_ratio >= 0.10 THEN 'FADING'
            WHEN momentum_ratio >= 0 THEN 'MINIMAL'
            ELSE 'REVERSING'
        END
    """)


def compute_ticker_stats(con):
    """Compute aggregate flow intensity and churn per ticker per period."""
    print("  Computing ticker-level stats...", flush=True)
    con.execute(f"""
        INSERT INTO ticker_flow_stats
        SELECT
            f.ticker, quarter_from, quarter_to,
            -- Flow intensity = sum(price_adj_flow) / market_cap (existing holders only)
            SUM(CASE WHEN NOT is_new_entry AND NOT is_exit THEN price_adj_flow ELSE 0 END)
                / NULLIF(MAX(m.market_cap), 0) as fi_total,
            SUM(CASE WHEN NOT is_new_entry AND NOT is_exit AND manager_type != 'passive'
                THEN price_adj_flow ELSE 0 END)
                / NULLIF(MAX(m.market_cap), 0) as fi_active,
            SUM(CASE WHEN NOT is_new_entry AND NOT is_exit AND manager_type = 'passive'
                THEN price_adj_flow ELSE 0 END)
                / NULLIF(MAX(m.market_cap), 0) as fi_passive,
            -- Churn: (entry_value + exit_value) / avg_value for non-passive
            (SUM(CASE WHEN is_new_entry AND manager_type != 'passive' THEN to_value ELSE 0 END)
             + SUM(CASE WHEN is_exit AND manager_type != 'passive' THEN from_value ELSE 0 END))
            / NULLIF((SUM(CASE WHEN NOT is_new_entry AND manager_type != 'passive' THEN from_value ELSE 0 END)
                      + SUM(CASE WHEN NOT is_exit AND manager_type != 'passive' THEN to_value ELSE 0 END)) / 2, 0)
            as churn_np,
            -- Churn active only
            (SUM(CASE WHEN is_new_entry AND manager_type = 'active' THEN to_value ELSE 0 END)
             + SUM(CASE WHEN is_exit AND manager_type = 'active' THEN from_value ELSE 0 END))
            / NULLIF((SUM(CASE WHEN NOT is_new_entry AND manager_type = 'active' THEN from_value ELSE 0 END)
                      + SUM(CASE WHEN NOT is_exit AND manager_type = 'active' THEN to_value ELSE 0 END)) / 2, 0)
            as churn_active,
            CURRENT_TIMESTAMP
        FROM investor_flows f
        LEFT JOIN market_data m ON f.ticker = m.ticker
        GROUP BY f.ticker, quarter_from, quarter_to
    """)
    count = con.execute("SELECT COUNT(*) FROM ticker_flow_stats").fetchone()[0]
    print(f"    {count:,} ticker stats rows")


def main():
    con = duckdb.connect(get_db_path())
    print(f"Database: {get_db_path()}")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    t_start = time.time()

    create_tables(con)

    # Compute flows for each period — single SQL pass per period
    for period_label, q_from, q_to in PERIODS:
        compute_period_flows(con, period_label, q_from, q_to)

    # Momentum signals
    compute_momentum(con)

    # Ticker-level aggregate stats
    compute_ticker_stats(con)

    con.execute("CHECKPOINT")

    # Summary
    total_flows = con.execute("SELECT COUNT(*) FROM investor_flows").fetchone()[0]
    total_stats = con.execute("SELECT COUNT(*) FROM ticker_flow_stats").fetchone()[0]
    elapsed = time.time() - t_start

    print(f"\nCompleted in {elapsed:.0f}s")
    print(f"  investor_flows: {total_flows:,} rows")
    print(f"  ticker_flow_stats: {total_stats:,} rows")

    con.close()

    if total_flows == 0:
        print("\nWARNING: No flows computed — check that holdings table has data.")
        sys.exit(1)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description="Compute investor flow analytics")
    parser.add_argument("--staging", action="store_true", help="Write to staging DB")
    args = parser.parse_args()
    if args.staging:
        set_staging_mode(True)
    from db import crash_handler
    crash_handler("compute_flows")(main)
