#!/usr/bin/env python3
"""
build_summaries.py — Precompute summary tables for fast Flask queries.

Creates:
  - summary_by_ticker: (quarter, ticker) → inst holdings, holder count, active/passive split
  - summary_by_parent: (quarter, inst_parent_name) → AUM, ticker count, top positions

Run: python3 scripts/build_summaries.py              # incremental (latest quarter only)
     python3 scripts/build_summaries.py --rebuild     # full rebuild all quarters
"""

import argparse
import os

import duckdb

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from db import set_staging_mode, get_db_path

try:
    from config import QUARTERS, LATEST_QUARTER
except ImportError:
    QUARTERS = ["2025Q1", "2025Q2", "2025Q3", "2025Q4"]
    LATEST_QUARTER = QUARTERS[-1]


def build_summary_by_ticker(con, quarters=None):
    """Build summary_by_ticker table."""
    if quarters is None:
        quarters = [LATEST_QUARTER]

    con.execute("""
        CREATE TABLE IF NOT EXISTS summary_by_ticker (
            quarter VARCHAR,
            ticker VARCHAR,
            company_name VARCHAR,
            total_value DOUBLE,
            total_shares BIGINT,
            holder_count INTEGER,
            active_value DOUBLE,
            passive_value DOUBLE,
            active_pct DOUBLE,
            pct_of_float DOUBLE,
            top10_holders VARCHAR,
            updated_at TIMESTAMP,
            PRIMARY KEY (quarter, ticker)
        )
    """)

    for q in quarters:
        print(f"  summary_by_ticker: {q}...", flush=True)
        con.execute("DELETE FROM summary_by_ticker WHERE quarter = ?", [q])
        con.execute(f"""
            INSERT INTO summary_by_ticker
            SELECT
                '{q}' as quarter,
                h.ticker,
                MODE(h.issuer_name) as company_name,
                SUM(h.market_value_live) as total_value,
                SUM(h.shares) as total_shares,
                COUNT(DISTINCT h.cik) as holder_count,
                SUM(CASE WHEN h.manager_type IN ('active','hedge_fund','quantitative','activist')
                    THEN h.market_value_live ELSE 0 END) as active_value,
                SUM(CASE WHEN h.manager_type = 'passive' THEN h.market_value_live ELSE 0 END) as passive_value,
                CASE WHEN SUM(h.market_value_live) > 0
                    THEN ROUND(SUM(CASE WHEN h.manager_type IN ('active','hedge_fund','quantitative','activist')
                        THEN h.market_value_live ELSE 0 END) * 100.0 / SUM(h.market_value_live), 1)
                    ELSE NULL END as active_pct,
                SUM(h.pct_of_float) as pct_of_float,
                NULL as top10_holders,
                CURRENT_TIMESTAMP as updated_at
            FROM holdings h
            WHERE h.quarter = '{q}'
              AND h.ticker IS NOT NULL AND h.ticker != ''
            GROUP BY h.ticker
        """)

    count = con.execute("SELECT COUNT(*) FROM summary_by_ticker").fetchone()[0]
    print(f"  summary_by_ticker: {count:,} rows total")


def build_summary_by_parent(con, quarters=None):
    """Build summary_by_parent table."""
    if quarters is None:
        quarters = [LATEST_QUARTER]

    con.execute("""
        CREATE TABLE IF NOT EXISTS summary_by_parent (
            quarter VARCHAR,
            inst_parent_name VARCHAR,
            total_aum DOUBLE,
            ticker_count INTEGER,
            total_shares BIGINT,
            manager_type VARCHAR,
            is_passive BOOLEAN,
            top10_tickers VARCHAR,
            updated_at TIMESTAMP,
            PRIMARY KEY (quarter, inst_parent_name)
        )
    """)

    for q in quarters:
        print(f"  summary_by_parent: {q}...", flush=True)
        con.execute("DELETE FROM summary_by_parent WHERE quarter = ?", [q])
        con.execute(f"""
            INSERT INTO summary_by_parent
            SELECT
                '{q}' as quarter,
                COALESCE(h.inst_parent_name, h.manager_name) as inst_parent_name,
                SUM(h.market_value_live) as total_aum,
                COUNT(DISTINCT h.ticker) as ticker_count,
                SUM(h.shares) as total_shares,
                MAX(h.manager_type) as manager_type,
                BOOL_OR(h.is_passive) as is_passive,
                NULL as top10_tickers,
                CURRENT_TIMESTAMP as updated_at
            FROM holdings h
            WHERE h.quarter = '{q}'
            GROUP BY COALESCE(h.inst_parent_name, h.manager_name)
        """)

    count = con.execute("SELECT COUNT(*) FROM summary_by_parent").fetchone()[0]
    print(f"  summary_by_parent: {count:,} rows total")


def main():
    parser = argparse.ArgumentParser(description="Build materialized summary tables")
    parser.add_argument("--rebuild", action="store_true", help="Rebuild all quarters")
    parser.add_argument("--staging", action="store_true", help="Write to staging DB")
    args = parser.parse_args()

    if hasattr(args, 'staging') and args.staging:
        set_staging_mode(True)

    con = duckdb.connect(get_db_path())

    quarters = QUARTERS if args.rebuild else [LATEST_QUARTER]
    print(f"Building summaries for: {quarters}")

    build_summary_by_ticker(con, quarters)
    build_summary_by_parent(con, quarters)
    con.execute("CHECKPOINT")

    con.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
