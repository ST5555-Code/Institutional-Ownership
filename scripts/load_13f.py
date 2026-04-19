#!/usr/bin/env python3
"""
load_13f.py — Load SUBMISSION, INFOTABLE, COVERPAGE, and OTHERMANAGER2
              TSVs from quarterly SEC EDGAR bulk data into DuckDB; build
              filings, filings_deduped, and other_managers.

Usage:
    python3 scripts/load_13f.py              # full reload (all quarters)
    python3 scripts/load_13f.py --quarter 2025Q4   # incremental: reload one quarter only
    python3 scripts/load_13f.py --staging    # write to staging DB
    python3 scripts/load_13f.py --dry-run    # project writes; no DB mutations
"""

import argparse
import os

import duckdb

from config import QUARTERS, LATEST_QUARTER
from db import get_db_path, set_staging_mode, is_staging_mode, record_freshness

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
    om2_path = os.path.join(qdir, "OTHERMANAGER2.tsv")

    for p in [sub_path, info_path, cover_path, om2_path]:
        if not os.path.exists(p):
            msg = f"Missing required 13F TSV for {quarter}: {p}"
            print(f"  ERROR: {msg}", flush=True)
            raise FileNotFoundError(msg)

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

    # Load OTHERMANAGER2 (co-filing manager references; SEQUENCENUMBER-keyed)
    con.execute(f"""
        INSERT INTO other_managers
        SELECT
            ACCESSION_NUMBER,
            SEQUENCENUMBER,
            CIK,
            FORM13FFILENUMBER,
            CRDNUMBER,
            SECFILENUMBER,
            NAME,
            '{quarter}' as quarter
        FROM read_csv_auto('{om2_path}', delim='\t', header=true,
                           all_varchar=true, ignore_errors=true)
    """)
    om2_count = con.execute(f"""
        SELECT COUNT(*) FROM other_managers WHERE quarter = '{quarter}'
    """).fetchone()[0]

    print(f"  {quarter}: {sub_count:,} submissions, {info_count:,} holdings, "
          f"{cover_count:,} cover pages, {om2_count:,} other managers",
          flush=True)
    return sub_count, info_count


def create_staging_tables(con):
    """Create staging tables for raw data."""
    con.execute("DROP TABLE IF EXISTS raw_submissions")
    con.execute("DROP TABLE IF EXISTS raw_infotable")
    con.execute("DROP TABLE IF EXISTS raw_coverpage")
    con.execute("DROP TABLE IF EXISTS other_managers")

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

    # Schema matches prod other_managers (8 cols) — see findings doc §9.5.
    con.execute("""
        CREATE TABLE other_managers (
            accession_number VARCHAR,
            sequence_number VARCHAR,
            other_cik VARCHAR,
            form13f_file_number VARCHAR,
            crd_number VARCHAR,
            sec_file_number VARCHAR,
            name VARCHAR,
            quarter VARCHAR
        )
    """)


def prepare_incremental(con, quarter):
    """For incremental mode: preserve existing staging tables, delete target quarter only."""
    # Ensure staging tables exist
    for tbl in ['raw_submissions', 'raw_infotable', 'raw_coverpage', 'other_managers']:
        try:
            con.execute(f"SELECT 1 FROM {tbl} LIMIT 0")
        except Exception:
            # Table doesn't exist — need full create
            create_staging_tables(con)
            return

    # Delete only the target quarter's data from staging tables
    print(f"  Removing existing {quarter} data from staging tables...", flush=True)
    for tbl in ['raw_submissions', 'raw_infotable', 'raw_coverpage', 'other_managers']:
        deleted = con.execute(f"DELETE FROM {tbl} WHERE quarter = '{quarter}'").fetchone()
        if deleted:
            print(f"    {tbl}: removed {deleted[0]:,} rows", flush=True)


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
    print(f"  filings: {count:,} total, {deduped:,} after dedup (latest per CIK per quarter)",
          flush=True)
    return deduped


def print_summary(con):
    """Print summary statistics."""
    print("\n--- Table Row Counts ---", flush=True)
    tables = ["raw_submissions", "raw_infotable", "raw_coverpage",
              "filings", "filings_deduped", "other_managers"]
    for t in tables:
        try:
            count = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            print(f"  {t}: {count:,}", flush=True)
        except Exception:
            print(f"  {t}: (not found)", flush=True)

    print("\n--- Filings by Quarter ---", flush=True)
    qcounts = con.execute("""
        SELECT quarter,
               COUNT(*) as filings,
               COUNT(DISTINCT cik) as filers
        FROM filings_deduped
        GROUP BY quarter ORDER BY quarter
    """).fetchdf()
    print(qcounts.to_string(index=False), flush=True)


def project_dry_run(quarters):
    """Dry-run: verify every TSV exists and project per-quarter row counts.

    Uses an in-memory DuckDB to call `read_csv_auto` without touching
    the target DB. Raises FileNotFoundError on any missing TSV — same
    fail-fast behavior as a real run so the projection doubles as a
    pre-flight check.
    """
    print("\n[dry-run] Projecting row counts (no DB mutations)...", flush=True)
    scratch = duckdb.connect(":memory:")
    totals = {"sub": 0, "info": 0, "cover": 0, "om2": 0}
    for q in quarters:
        qdir = os.path.join(EXTRACT_DIR, q)
        paths = {
            "sub":   os.path.join(qdir, "SUBMISSION.tsv"),
            "info":  os.path.join(qdir, "INFOTABLE.tsv"),
            "cover": os.path.join(qdir, "COVERPAGE.tsv"),
            "om2":   os.path.join(qdir, "OTHERMANAGER2.tsv"),
        }
        for key, p in paths.items():
            if not os.path.exists(p):
                msg = f"Missing required 13F TSV for {q}: {p}"
                print(f"  ERROR: {msg}", flush=True)
                raise FileNotFoundError(msg)
        counts = {}
        for key, p in paths.items():
            counts[key] = scratch.execute(
                f"SELECT COUNT(*) FROM read_csv_auto('{p}', delim='\t', "
                "header=true, all_varchar=true, ignore_errors=true)"
            ).fetchone()[0]
            totals[key] += counts[key]
        print(
            f"  {q}: {counts['sub']:,} submissions, {counts['info']:,} infotable, "
            f"{counts['cover']:,} coverpage, {counts['om2']:,} othermgr2",
            flush=True,
        )
    scratch.close()
    print(
        f"\n[dry-run] Totals: {totals['sub']:,} submissions, "
        f"{totals['info']:,} infotable, {totals['cover']:,} coverpage, "
        f"{totals['om2']:,} other_managers",
        flush=True,
    )
    print(
        "[dry-run] Would DROP+CTAS filings and filings_deduped from raw_submissions + raw_coverpage.",
        flush=True,
    )
    print("[dry-run] No DB mutations performed.", flush=True)


def _stamp(con, tables):
    """Write data_freshness rows for each table. Non-fatal on failure."""
    for t in tables:
        try:
            record_freshness(con, t)
        except Exception as e:  # pylint: disable=broad-except
            print(f"  [warn] record_freshness({t}) failed: {e}", flush=True)


def main():
    print("=" * 60, flush=True)
    print("SCRIPT 4 — load_13f.py", flush=True)
    print("=" * 60, flush=True)

    print(f"\nDatabase: {get_db_path()}", flush=True)
    print(f"  staging={is_staging_mode()}  dry_run={args.dry_run}", flush=True)

    quarters_to_load = [args.quarter] if args.quarter else list(QUARTERS)

    if args.dry_run:
        project_dry_run(quarters_to_load)
        print("\nDone.", flush=True)
        return

    con = duckdb.connect(get_db_path())

    if args.quarter:
        # Incremental mode: reload only the specified quarter
        quarter = args.quarter
        if quarter not in QUARTERS:
            print(f"WARNING: {quarter} not in QUARTERS list {QUARTERS}. Proceeding anyway.",
                  flush=True)
        print(f"\nIncremental mode: reloading {quarter} only", flush=True)

        # Preserve other quarters, delete+reload target quarter
        prepare_incremental(con, quarter)

        # Load only the target quarter
        print(f"\nLoading {quarter}...", flush=True)
        s, i = load_quarter(con, quarter)
        print(f"  Loaded: {s:,} submissions, {i:,} info table rows", flush=True)
        con.execute("CHECKPOINT")
    else:
        # Full mode: drop and recreate everything
        print("\nFull reload: all quarters", flush=True)
        print("\nCreating staging tables...", flush=True)
        create_staging_tables(con)

        print("\nLoading quarterly data...", flush=True)
        total_subs = 0
        total_info = 0
        for quarter in QUARTERS:
            s, i = load_quarter(con, quarter)
            total_subs += s
            total_info += i
            con.execute("CHECKPOINT")
        print(f"\n  Total: {total_subs:,} submissions, {total_info:,} info table rows",
              flush=True)

    # Stamp raw-table freshness after all quarters are loaded.
    _stamp(con, ["raw_submissions", "raw_infotable", "raw_coverpage",
                 "other_managers"])

    # Rebuild filings from all raw data (all quarters present)
    print("\nBuilding filings table...", flush=True)
    build_filings(con)
    con.execute("CHECKPOINT")
    _stamp(con, ["filings", "filings_deduped"])

    # Summary
    print_summary(con)

    con.execute("CHECKPOINT")
    con.close()
    print("\nDone.", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load 13F data from SEC bulk TSVs")
    parser.add_argument("--quarter", type=str,
                        help=f"Load only this quarter (e.g. {LATEST_QUARTER})")
    parser.add_argument("--staging", action="store_true",
                        help="Write to staging DB")
    parser.add_argument("--dry-run", action="store_true",
                        help="Project what would be written; no DB mutations")
    args = parser.parse_args()
    if args.staging:
        set_staging_mode(True)
    from db import crash_handler
    crash_handler("load_13f")(main)
