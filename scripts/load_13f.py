#!/usr/bin/env python3
"""
load_13f.py — Load SUBMISSION, INFOTABLE, and COVERPAGE TSVs from all four quarters
              into DuckDB. Create filings and holdings tables.

Run: python3 scripts/load_13f.py
"""

import os
import duckdb
import time

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXTRACT_DIR = os.path.join(BASE_DIR, "data", "extracted")
DB_PATH = os.path.join(BASE_DIR, "data", "13f.duckdb")

from config import QUARTERS


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
    sub_count = con.execute(f"""
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
    """).fetchone()[0] if False else None

    # Use INSERT INTO ... SELECT for count
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

    print("\n--- Top 10 Filers by Position Count (Q4 2025) ---")
    top = con.execute("""
        SELECT manager_name, cik, COUNT(*) as positions,
               SUM(market_value_usd) / 1e9 as total_value_bn
        FROM holdings
        WHERE quarter = '2025Q4'
        GROUP BY manager_name, cik
        ORDER BY total_value_bn DESC
        LIMIT 10
    """).fetchdf()
    print(top.to_string(index=False))

    print("\n--- Sample Holdings for AR (Antero Resources) ---")
    ar = con.execute("""
        SELECT manager_name, quarter, shares, market_value_usd / 1e6 as value_mm,
               pct_of_portfolio
        FROM holdings
        WHERE cusip = '00130H105' AND quarter = '2025Q4'
        ORDER BY market_value_usd DESC
        LIMIT 10
    """).fetchdf()
    if len(ar) > 0:
        print(ar.to_string(index=False))
    else:
        print("  No AR holdings found (CUSIP 00130H105)")


def main():
    print("=" * 60)
    print("SCRIPT 4 — load_13f.py")
    print("=" * 60)

    con = duckdb.connect(DB_PATH)

    # Step 1: Create staging tables
    print("\nCreating staging tables...")
    create_staging_tables(con)

    # Step 2: Load all quarters
    print("\nLoading quarterly data...")
    total_subs = 0
    total_info = 0
    for quarter in QUARTERS:
        s, i = load_quarter(con, quarter)
        total_subs += s
        total_info += i
    print(f"\n  Total: {total_subs:,} submissions, {total_info:,} info table rows")

    # Step 3: Build filings
    print("\nBuilding filings table...")
    build_filings(con)

    # Step 4: Build holdings
    print("\nBuilding holdings table...")
    t0 = time.time()
    holdings_count = build_holdings(con)
    elapsed = time.time() - t0
    print(f"  holdings: {holdings_count:,} rows (built in {elapsed:.1f}s)")

    # Step 5: Summary
    print_summary(con)

    con.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
