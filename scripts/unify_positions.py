#!/usr/bin/env python3
"""
unify_positions.py — Merge holdings (13F) and fund_holdings (N-PORT) into a
single positions table for unified queries.

The positions table is a materialized view rebuilt from scratch each run.
Original holdings and fund_holdings tables are preserved.

Run: python3 scripts/unify_positions.py
"""

import os
import sys
import time
from datetime import datetime

import duckdb

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "data", "13f.duckdb")


def run():
    con = duckdb.connect(DB_PATH)

    # Check if ncen_adviser_map exists for adviser CIK linking
    tables = [t[0] for t in con.execute("SHOW TABLES").fetchall()]
    has_ncen = "ncen_adviser_map" in tables

    print("Building unified positions table...")
    con.execute("DROP TABLE IF EXISTS positions")

    # Build the table with both sources
    print("  Inserting 13F holdings...")
    con.execute("""
        CREATE TABLE positions AS
        SELECT
            '13F' as source_form,
            h.cik as reporting_cik,
            CAST(NULL AS VARCHAR) as series_id,
            h.accession_number,
            h.cusip,
            h.ticker,
            h.issuer_name,
            COALESCE(h.security_type_inferred, h.security_type) as asset_category,
            h.security_type,
            CAST(h.shares AS DOUBLE) as shares_held,
            CAST(h.market_value_usd AS DOUBLE) as market_value_usd,
            h.pct_of_portfolio as pct_of_portfolio,
            h.cik as manager_cik,
            COALESCE(h.fund_name, h.manager_name) as manager_name,
            h.inst_parent_name,
            h.manager_type,
            h.is_passive,
            h.quarter,
            CAST(NULL AS VARCHAR) as report_month,
            TRY_CAST(h.report_date AS DATE) as report_date,
            CURRENT_TIMESTAMP as loaded_at
        FROM holdings h
    """)

    count_13f = con.execute(
        "SELECT COUNT(*) FROM positions WHERE source_form = '13F'"
    ).fetchone()[0]
    print(f"    {count_13f:,} 13F rows")

    print("  Inserting N-PORT fund holdings...")
    ncen_join = ""
    ncen_select = "fh.fund_cik"
    if has_ncen:
        ncen_select = "COALESCE(nam.adviser_crd, fh.fund_cik)"
        ncen_join = "LEFT JOIN ncen_adviser_map nam ON fh.series_id = nam.series_id"

    con.execute(f"""
        INSERT INTO positions
        SELECT
            'N-PORT' as source_form,
            fh.fund_cik as reporting_cik,
            fh.series_id,
            CAST(NULL AS VARCHAR) as accession_number,
            fh.cusip,
            fh.ticker,
            fh.issuer_name,
            fh.asset_category,
            'equity' as security_type,
            fh.shares_or_principal as shares_held,
            fh.market_value_usd,
            fh.pct_of_nav as pct_of_portfolio,
            {ncen_select} as manager_cik,
            fh.fund_name as manager_name,
            fh.family_name as inst_parent_name,
            'active' as manager_type,
            FALSE as is_passive,
            fh.quarter,
            fh.report_month,
            fh.report_date,
            CURRENT_TIMESTAMP as loaded_at
        FROM fund_holdings fh
        {ncen_join}
    """)

    count_nport = con.execute(
        "SELECT COUNT(*) FROM positions WHERE source_form = 'N-PORT'"
    ).fetchone()[0]
    total = con.execute("SELECT COUNT(*) FROM positions").fetchone()[0]
    print(f"    {count_nport:,} N-PORT rows")
    print(f"    {total:,} total positions")

    # Summary stats
    print("\n  Position counts by source and quarter:")
    stats = con.execute("""
        SELECT source_form, quarter, COUNT(*) as cnt
        FROM positions
        GROUP BY source_form, quarter
        ORDER BY source_form, quarter
    """).fetchall()
    for s in stats:
        print(f"    {s[0]:8s} {s[1]:8s} {s[2]:>12,}")

    # Deduplication stats (same security+manager+quarter in both sources)
    if count_nport > 0:
        dupes = con.execute("""
            SELECT COUNT(*) FROM (
                SELECT ticker, manager_cik, quarter
                FROM positions
                WHERE source_form = '13F' AND ticker IS NOT NULL
                INTERSECT
                SELECT ticker, manager_cik, quarter
                FROM positions
                WHERE source_form = 'N-PORT' AND ticker IS NOT NULL
            )
        """).fetchone()[0]
        print(f"\n  Overlapping (same ticker+manager+quarter): {dupes:,}")

    # Test: AR Q4 2025 top 10
    print("\n  AR Q4 2025 top 10 by value:")
    ar = con.execute("""
        SELECT source_form, manager_name, shares_held, market_value_usd, pct_of_portfolio
        FROM positions
        WHERE ticker = 'AR' AND quarter = '2025Q4'
        ORDER BY market_value_usd DESC NULLS LAST
        LIMIT 10
    """).fetchall()
    for r in ar:
        val = f"${r[3]:,.0f}" if r[3] else "N/A"
        print(f"    {r[0]:6s} {r[1]:40s} shares={r[2]:>12,.0f} val={val}")

    con.execute("CHECKPOINT")
    con.close()
    print("\nDone.")


if __name__ == "__main__":
    run()
