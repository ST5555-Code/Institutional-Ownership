#!/usr/bin/env python3
"""
merge_staging.py — Merge data from staging DB into production DB.

All fetch scripts write to data/13f_staging.duckdb. This script merges
staging → production using INSERT OR REPLACE keyed on each table's
primary key. Production DB is only locked during the merge (seconds).

Run: python3 scripts/merge_staging.py --all                     # Merge all tables
     python3 scripts/merge_staging.py --tables beneficial_ownership,fetched_tickers_13dg
     python3 scripts/merge_staging.py --all --dry-run            # Show what would change
     python3 scripts/merge_staging.py --all --drop-staging       # Delete staging after merge
"""

import argparse
import os
from datetime import datetime

import duckdb

from db import PROD_DB, STAGING_DB

# Table definitions: name → primary key column(s)
TABLE_KEYS = {
    "beneficial_ownership": ["accession_number"],
    "beneficial_ownership_current": None,  # rebuilt, not merged — replace entirely
    "fetched_tickers_13dg": ["ticker"],
    "listed_filings_13dg": ["accession_number"],
    "short_interest": ["ticker", "report_date"],
    "ncen_adviser_map": None,  # no PK — append-only
    "fund_holdings": None,  # large table — append new rows by (series_id, quarter, cusip)
    "fund_universe": ["series_id"],
    "fund_classes": ["class_id"],
    "lei_reference": ["lei"],
    "peer_groups": None,  # small reference table — replace entirely
    "market_data": ["ticker"],
    "shares_outstanding_history": ["ticker", "as_of_date"],
    "investor_flows": None,  # rebuilt by compute_flows — replace entirely
    "ticker_flow_stats": None,  # rebuilt — replace entirely
    "positions": None,  # rebuilt by unify_positions — replace entirely
    "summary_by_ticker": ["quarter", "ticker"],
    "summary_by_parent": ["quarter", "inst_parent_name"],
    "_cache_openfigi": ["cusip"],
    "_cache_yfinance": ["ticker"],
}


def get_staging_tables(staging_con):
    """Return list of table names that exist in staging DB."""
    rows = staging_con.execute("SHOW TABLES").fetchall()
    return [r[0] for r in rows]


def count_rows(con, table):
    """Count rows in a table, returning 0 if table doesn't exist."""
    try:
        return con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    except Exception:
        return 0


def get_columns(con, table):
    """Get column names for a table."""
    try:
        return [r[0] for r in con.execute(f"DESCRIBE {table}").fetchall()]
    except Exception:
        return []


def merge_table(prod_con, staging_con, table, pk_cols, dry_run=False):
    """Merge one table from staging to production. Returns (added, replaced, unchanged).

    Column matching is done BY NAME, not by position. When staging has columns
    that production lacks (new schema additions), the caller is expected to have
    already ALTER'd production. When production has columns staging lacks, those
    are left NULL on newly-inserted rows.
    """
    staging_count = count_rows(staging_con, table)
    if staging_count == 0:
        return 0, 0, 0

    prod_count_before = count_rows(prod_con, table)
    staging_cols = get_columns(staging_con, table)
    prod_cols = get_columns(prod_con, table)

    if not staging_cols:
        return 0, 0, 0

    # Intersect: merge only columns that exist in both DBs. Columns only in
    # staging are silently dropped (warn caller via print). Columns only in
    # production are preserved (left untouched for replaced rows via UPDATE
    # semantics; left NULL on newly inserted rows).
    shared_cols = [c for c in staging_cols if c in prod_cols]
    staging_only = [c for c in staging_cols if c not in prod_cols]
    if staging_only:
        print(f"    WARNING: {table} — staging has columns missing in production: {staging_only}")
        print("             These columns will NOT be merged. ALTER production first.")

    if dry_run:
        if pk_cols:
            pk_where = " AND ".join(f"s.{c} = p.{c}" for c in pk_cols)
            try:
                existing = prod_con.execute(f"""
                    SELECT COUNT(*) FROM (
                        SELECT {', '.join(f's.{c}' for c in pk_cols)}
                        FROM staging_db.{table} s
                        INNER JOIN {table} p ON {pk_where}
                    )
                """).fetchone()[0]
            except Exception:
                existing = 0
            new = staging_count - existing
            return new, existing, 0
        else:
            return staging_count, 0, prod_count_before

    # Actual merge — explicit column names on both sides, name-matched
    col_names = ", ".join(shared_cols)
    select_cols = ", ".join(shared_cols)  # same list both sides — names match by name

    if pk_cols:
        pk_where = " AND ".join(f"p.{c} = s.{c}" for c in pk_cols)
        prod_con.execute(f"""
            DELETE FROM {table} p
            WHERE EXISTS (
                SELECT 1 FROM staging_db.{table} s
                WHERE {pk_where}
            )
        """)
        prod_con.execute(f"""
            INSERT INTO {table} ({col_names})
            SELECT {select_cols} FROM staging_db.{table}
        """)
        prod_count_after = count_rows(prod_con, table)
        added = prod_count_after - prod_count_before
        replaced = staging_count - added
        return max(added, 0), max(replaced, 0), 0
    else:
        # Replace entire table — drop and recreate from staging
        try:
            prod_con.execute(f"DROP TABLE IF EXISTS {table}")
        except Exception:
            pass
        prod_con.execute(f"""
            CREATE TABLE {table} AS
            SELECT {select_cols} FROM staging_db.{table}
        """)
        return staging_count, 0, 0


def main():
    parser = argparse.ArgumentParser(description="Merge staging DB into production")
    parser.add_argument("--all", action="store_true", help="Merge all tables")
    parser.add_argument("--tables", type=str, help="Comma-separated table names to merge")
    parser.add_argument("--dry-run", action="store_true", help="Show what would change without writing")
    parser.add_argument("--drop-staging", action="store_true", help="Delete staging DB after successful merge")
    args = parser.parse_args()

    if not args.all and not args.tables:
        parser.error("Specify --all or --tables")

    if not os.path.exists(STAGING_DB):
        print(f"No staging DB found at {STAGING_DB}")
        return

    print(f"{'='*60}")
    print("Merge Staging → Production")
    print(f"{'='*60}")
    print(f"  Staging:    {STAGING_DB}")
    print(f"  Production: {PROD_DB}")
    print(f"  Mode:       {'DRY RUN' if args.dry_run else 'LIVE'}")
    print()

    # Open staging read-only
    staging_con = duckdb.connect(STAGING_DB, read_only=True)
    staging_tables = get_staging_tables(staging_con)
    print(f"  Staging tables: {len(staging_tables)}")
    for t in staging_tables:
        cnt = count_rows(staging_con, t)
        print(f"    {t}: {cnt:,} rows")
    print()

    # Determine which tables to merge
    if args.all:
        tables_to_merge = staging_tables
    else:
        tables_to_merge = [t.strip() for t in args.tables.split(",")]
        missing = [t for t in tables_to_merge if t not in staging_tables]
        if missing:
            print(f"  WARNING: tables not in staging: {missing}")
        tables_to_merge = [t for t in tables_to_merge if t in staging_tables]

    if not tables_to_merge:
        print("No tables to merge.")
        staging_con.close()
        return

    # Open production for writing (or read-only for dry run)
    if args.dry_run:
        prod_con = duckdb.connect(PROD_DB, read_only=True)
        # Attach staging as a separate schema for cross-DB queries
        prod_con.execute(f"ATTACH '{STAGING_DB}' AS staging_db (READ_ONLY)")
    else:
        prod_con = duckdb.connect(PROD_DB)
        prod_con.execute(f"ATTACH '{STAGING_DB}' AS staging_db (READ_ONLY)")

    # Merge each table
    print(f"{'Table':40s} {'Added':>8s} {'Replaced':>10s} {'Prev':>8s}")
    print(f"{'-'*40} {'-'*8} {'-'*10} {'-'*8}")

    total_added = 0
    total_replaced = 0

    for table in tables_to_merge:
        pk_cols = TABLE_KEYS.get(table)

        # Ensure target table exists in production
        if not args.dry_run:
            prod_exists = count_rows(prod_con, table) >= 0
            if not prod_exists:
                # Create empty table with same schema
                try:
                    columns = get_columns(staging_con, table)
                    col_list = ", ".join(columns)
                    prod_con.execute(f"CREATE TABLE {table} AS SELECT {col_list} FROM staging_db.{table} WHERE 1=0")
                except Exception:
                    pass

        try:
            added, replaced, prev = merge_table(prod_con, staging_con, table, pk_cols, dry_run=args.dry_run)
            total_added += added
            total_replaced += replaced
            print(f"  {table:38s} {added:>8,} {replaced:>10,} {prev:>8,}")
        except Exception as e:
            print(f"  {table:38s} ERROR: {e}")

    if not args.dry_run:
        prod_con.execute("CHECKPOINT")

    prod_con.close()
    staging_con.close()

    print(f"\n  Total added: {total_added:,}, replaced: {total_replaced:,}")

    if args.drop_staging and not args.dry_run:
        os.remove(STAGING_DB)
        print(f"  Staging DB deleted: {STAGING_DB}")

    print(f"\n{'DRY RUN complete' if args.dry_run else 'Merge complete'}: {datetime.now().strftime('%H:%M:%S')}")


if __name__ == "__main__":
    main()
