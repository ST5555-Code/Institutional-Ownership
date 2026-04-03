#!/usr/bin/env python3
"""
load_13f.py — Load SUBMISSION, INFOTABLE, and COVERPAGE TSVs from quarterly
              SEC EDGAR bulk data into DuckDB. Create filings and holdings tables.

Usage:
    python3 scripts/load_13f.py              # full reload (all quarters)
    python3 scripts/load_13f.py --quarter 2025Q4   # incremental: reload one quarter only
    python3 scripts/load_13f.py --staging    # write to staging DB
"""

import argparse
import os
import time

import duckdb

from config import QUARTERS, LATEST_QUARTER
from db import get_db_path, set_staging_mode

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXTRACT_DIR = os.path.join(BASE_DIR, "data", "extracted")


def load_quarter(con, quarter):
    """Load a single quarter's TSV files into staging tables."""
    qdir = os.path.join(EXTRACT_DIR, quarter)
    sub_path = os.path.join(qdir, "SUBMISSION.tsv")
    info_path = os.path.join(qdir, "INFOTABLE.tsv")
    cover_path = os.path.join(qdir, "COVERPAGE.tsv")

    for p in [sub_path, info_path, cover_path]:
        if not os.path.exists(p):
            print(f"  WARNING: Missing {p}")
            return 0, 0

    # Load SUBMISSION
    con.execute(f"""
        INSERT INTO raw_submissions
        SELECT
            ACCESSION_NUMBER,
            FILING_DATE,
            SUBMISSIONTYPE,
            CAST(CIK AS VARCHAR) as CIK,
            PERIODOFREPORT,
            '{quarter}' as quarter
        FROM read_csv_auto('{sub_path}', delim='\t', header=true,
                           all_varchar=true, ignore_errors=true)
    """)
    sub_count = con.execute(f"""
        SELECT COUNT(*) FROM raw_submissions WHERE quarter = '{quarter}'
    """).fetchone()[0]

    # Load INFOTABLE
    con.execute(f"""
        INSERT INTO raw_infotable
        SELECT
            ACCESSION_NUMBER,
            NAMEOFISSUER,
            TITLEOFCLASS,
            CUSIP,
            FIGI,
            CAST(VALUE AS BIGINT) as VALUE,
            CAST(SSHPRNAMT AS BIGINT) as SSHPRNAMT,
            SSHPRNAMTTYPE,
            PUTCALL,
            INVESTMENTDISCRETION,
            OTHERMANAGER,
            CAST(VOTING_AUTH_SOLE AS BIGINT) as VOTING_AUTH_SOLE,
            CAST(VOTING_AUTH_SHARED AS BIGINT) as VOTING_AUTH_SHARED,
            CAST(VOTING_AUTH_NONE AS BIGINT) as VOTING_AUTH_NONE,
            '{quarter}' as quarter
        FROM read_csv_auto('{info_path}', delim='\t', header=true,
                           all_varchar=true, ignore_errors=true)
    """)
    info_count = con.execute(f"""
        SELECT COUNT(*) FROM raw_infotable WHERE quarter = '{quarter}'
    """).fetchone()[0]

    # Load COVERPAGE
    con.execute(f"""
        INSERT INTO raw_coverpage
        SELECT
            ACCESSION_NUMBER,
            REPORTCALENDARORQUARTER,
            ISAMENDMENT,
            AMENDMENTNO,
            FILINGMANAGER_NAME,
            FILINGMANAGER_CITY,
            FILINGMANAGER_STATEORCOUNTRY,
            CRDNUMBER,
            SECFILENUMBER,
            '{quarter}' as quarter
        FROM read_csv_auto('{cover_path}', delim='\t', header=true,
                           all_varchar=true, ignore_errors=true)
    """)
    cover_count = con.execute(f"""
        SELECT COUNT(*) FROM raw_coverpage WHERE quarter = '{quarter}'
    """).fetchone()[0]

    print(f"  {quarter}: {sub_count:,} submissions, {info_count:,} holdings, {cover_count:,} cover pages")
    return sub_count, info_count


def create_staging_tables(con):
    """Create staging tables for raw data."""
    con.execute("DROP TABLE IF EXISTS raw_submissions")
    con.execute("DROP TABLE IF EXISTS raw_infotable")
    con.execute("DROP TABLE IF EXISTS raw_coverpage")

    con.execute("""
        CREATE TABLE raw_submissions (
            accession_number VARCHAR,
            filing_date VARCHAR,
            submission_type VARCHAR,
            cik VARCHAR,
            period_of_report VARCHAR,
            quarter VARCHAR
        )
    """)

    con.execute("""
        CREATE TABLE raw_infotable (
            accession_number VARCHAR,
            issuer_name VARCHAR,
            title_of_class VARCHAR,
            cusip VARCHAR,
            figi VARCHAR,
            value BIGINT,
            shares BIGINT,
            shares_type VARCHAR,
            put_call VARCHAR,
            discretion VARCHAR,
            other_manager VARCHAR,
            vote_sole BIGINT,
            vote_shared BIGINT,
            vote_none BIGINT,
            quarter VARCHAR
        )
    """)

    con.execute("""
        CREATE TABLE raw_coverpage (
            accession_number VARCHAR,
            report_calendar VARCHAR,
            is_amendment VARCHAR,
            amendment_no VARCHAR,
            filing_manager_name VARCHAR,
            filing_manager_city VARCHAR,
            filing_manager_state VARCHAR,
            crd_number VARCHAR,
            sec_file_number VARCHAR,
            quarter VARCHAR
        )
    """)


def prepare_incremental(con, quarter):
    """For incremental mode: preserve existing staging tables, delete target quarter only."""
    # Ensure staging tables exist
    for tbl in ['raw_submissions', 'raw_infotable', 'raw_coverpage']:
        try:
            con.execute(f"SELECT 1 FROM {tbl} LIMIT 0")
        except Exception:
            # Table doesn't exist — need full create
            create_staging_tables(con)
            return

    # Delete only the target quarter's data from staging tables
    print(f"  Removing existing {quarter} data from staging tables...")
    for tbl in ['raw_submissions', 'raw_infotable', 'raw_coverpage']:
        deleted = con.execute(f"DELETE FROM {tbl} WHERE quarter = '{quarter}'").fetchone()
        if deleted:
            print(f"    {tbl}: removed {deleted[0]:,} rows")


def build_filings(con):
    """Build the filings table from submissions + coverpage."""
    con.execute("DROP TABLE IF EXISTS filings")
    con.execute("""
        CREATE TABLE filings AS
        SELECT
            s.accession_number,
            LPAD(s.cik, 10, '0') as cik,
            c.filing_manager_name as manager_name,
            c.crd_number,
            s.quarter,
            s.period_of_report as report_date,
            s.submission_type as filing_type,
            CASE WHEN s.submission_type LIKE '%/A' THEN true ELSE false END as amended,
            s.filing_date as filed_date
        FROM raw_submissions s
        LEFT JOIN raw_coverpage c ON s.accession_number = c.accession_number
    """)

    # For amended filings, keep only the latest amendment per CIK per quarter
    con.execute("DROP TABLE IF EXISTS filings_deduped")
    con.execute("""
        CREATE TABLE filings_deduped AS
        WITH ranked AS (
            SELECT *,
                ROW_NUMBER() OVER (
                    PARTITION BY cik, quarter
                    ORDER BY amended DESC, filed_date DESC
                ) as rn
            FROM filings
        )
        SELECT * EXCLUDE(rn) FROM ranked WHERE rn = 1
    """)

    count = con.execute("SELECT COUNT(*) FROM filings").fetchone()[0]
    deduped = con.execute("SELECT COUNT(*) FROM filings_deduped").fetchone()[0]
    print(f"  filings: {count:,} total, {deduped:,} after dedup (latest per CIK per quarter)")
    return deduped


def build_holdings(con):
    """Build the denormalized holdings table."""
    con.execute("DROP TABLE IF EXISTS holdings")
    con.execute("""
        CREATE TABLE holdings AS
        WITH base AS (
            SELECT
                i.accession_number,
                f.cik,
                f.manager_name,
                f.crd_number,
                f.quarter,
                f.report_date,
                i.cusip,
                NULL as ticker,
                i.issuer_name,
                i.title_of_class as security_type,
                i.value * 1000 as market_value_usd,
                i.shares,
                i.discretion,
                i.vote_sole,
                i.vote_shared,
                i.vote_none,
                i.put_call
            FROM raw_infotable i
            INNER JOIN filings_deduped f ON i.accession_number = f.accession_number
        ),
        with_pct AS (
            SELECT
                b.*,
                CASE
                    WHEN SUM(b.market_value_usd) OVER (PARTITION BY b.accession_number) > 0
                    THEN ROUND(b.market_value_usd * 100.0 /
                         SUM(b.market_value_usd) OVER (PARTITION BY b.accession_number), 4)
                    ELSE 0
                END as pct_of_portfolio
            FROM base b
        )
        SELECT
            accession_number,
            cik,
            manager_name,
            crd_number,
            NULL as inst_parent_name,
            quarter,
            report_date,
            cusip,
            ticker,
            issuer_name,
            security_type,
            market_value_usd,
            shares,
            pct_of_portfolio,
            NULL::DOUBLE as pct_of_float,
            NULL as manager_type,
            NULL::BOOLEAN as is_passive,
            NULL::BOOLEAN as is_activist,
            discretion,
            vote_sole,
            vote_shared,
            vote_none,
            put_call,
            NULL::DOUBLE as market_value_live
        FROM with_pct
    """)

    count = con.execute("SELECT COUNT(*) FROM holdings").fetchone()[0]
    return count


def print_summary(con):
    """Print summary statistics."""
    print("\n--- Table Row Counts ---")
    tables = ["raw_submissions", "raw_infotable", "raw_coverpage",
              "filings", "filings_deduped", "holdings"]
    for t in tables:
        try:
            count = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            print(f"  {t}: {count:,}")
        except Exception:
            print(f"  {t}: (not found)")

    print("\n--- Holdings by Quarter ---")
    qcounts = con.execute("""
        SELECT quarter, COUNT(*) as holdings, COUNT(DISTINCT cik) as filers
        FROM holdings
        GROUP BY quarter ORDER BY quarter
    """).fetchdf()
    print(qcounts.to_string(index=False))


def main():
    print("=" * 60)
    print("SCRIPT 4 — load_13f.py")
    print("=" * 60)

    print(f"\nDatabase: {get_db_path()}")
    con = duckdb.connect(get_db_path())

    if args.quarter:
        # Incremental mode: reload only the specified quarter
        quarter = args.quarter
        if quarter not in QUARTERS:
            print(f"WARNING: {quarter} not in QUARTERS list {QUARTERS}. Proceeding anyway.")
        print(f"\nIncremental mode: reloading {quarter} only")

        # Preserve other quarters, delete+reload target quarter
        prepare_incremental(con, quarter)

        # Load only the target quarter
        print(f"\nLoading {quarter}...")
        s, i = load_quarter(con, quarter)
        print(f"  Loaded: {s:,} submissions, {i:,} info table rows")
    else:
        # Full mode: drop and recreate everything
        print("\nFull reload: all quarters")
        print("\nCreating staging tables...")
        create_staging_tables(con)

        print("\nLoading quarterly data...")
        total_subs = 0
        total_info = 0
        for quarter in QUARTERS:
            s, i = load_quarter(con, quarter)
            total_subs += s
            total_info += i
        print(f"\n  Total: {total_subs:,} submissions, {total_info:,} info table rows")

    # Rebuild filings + holdings from all raw data (all quarters present)
    print("\nBuilding filings table...")
    build_filings(con)

    print("\nBuilding holdings table...")
    t0 = time.time()
    holdings_count = build_holdings(con)
    elapsed = time.time() - t0
    print(f"  holdings: {holdings_count:,} rows (built in {elapsed:.1f}s)")

    # Summary
    print_summary(con)

    con.close()
    print("\nDone.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load 13F data from SEC bulk TSVs")
    parser.add_argument("--quarter", type=str, help=f"Load only this quarter (e.g. {LATEST_QUARTER})")
    parser.add_argument("--staging", action="store_true", help="Write to staging DB")
    args = parser.parse_args()
    if args.staging:
        set_staging_mode(True)
    from db import crash_handler
    crash_handler("load_13f")(main)
