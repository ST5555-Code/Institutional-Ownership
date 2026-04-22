#!/usr/bin/env python3
"""
merge_staging.py — Merge data from staging DB into production DB.

All fetch scripts write to data/13f_staging.duckdb. This script merges
staging → production using INSERT OR REPLACE keyed on each table's
primary key. Production DB is only locked during the merge (seconds).

IMPORTANT — prefer --tables over --all. `--all` merges every table
present in the staging DB, including reference tables seeded by
`db.seed_staging()` (holdings_v2, managers, fund_holdings_v2,
market_data, adv_managers, filings, securities, parent_bridge) and
any entity tables left over from a prior `sync_staging.py` run. For
tables not in `TABLE_KEYS`, the merge path does a full DROP + CREATE
TABLE AS SELECT, which would silently revert any concurrent prod
writes or promote in-progress entity staging edits bypassing the INF1
staging workflow. `--all` now requires an explicit
`--i-really-mean-all` acknowledgement (INF10, 2026-04-10).

Run: python3 scripts/merge_staging.py --tables beneficial_ownership_v2,short_interest
     python3 scripts/merge_staging.py --tables X --dry-run
     python3 scripts/merge_staging.py --tables X --drop-staging
     python3 scripts/merge_staging.py --all --i-really-mean-all    # destructive, see above
"""

import argparse
import os
import sys
from datetime import datetime

import duckdb

from db import PROD_DB, STAGING_DB
from pipeline.registry import merge_table_keys

# Table definitions: name → primary key column(s)
#
# Semantics:
#   pk_cols = [col, ...]  → DELETE+INSERT by PK (upsert). Safe, idempotent.
#   pk_cols = None        → DROP TABLE + CREATE TABLE AS SELECT (full replace).
#                           Use only for rebuilt / derived tables where the
#                           staging copy is authoritative for the whole table.
#
# Warning: `None` means FULL REPLACEMENT, not "append." Any comment that
# says otherwise is wrong — see the merge_table() else-branch below.
#
# The registry is the source of truth — see `pipeline.registry.merge_table_keys()`
# at `scripts/pipeline/registry.py:355`. Only overrides below are the two
# persistent OpenFIGI / yfinance caches which live outside the registry.
TABLE_KEYS = merge_table_keys()
# Persistent lookup caches — not in the dataset registry because they are
# infrastructure, not datasets. Upsert by primary key so accumulated cache
# entries survive cross-DB merges.
TABLE_KEYS["_cache_openfigi"] = ["cusip"]
TABLE_KEYS["_cache_yfinance"] = ["ticker"]


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
    # production are NULL'd on every replaced row — the PK-keyed path is
    # DELETE+INSERT, not UPDATE, so a prod-only column loses its value on any
    # row whose PK is present in staging. Use --mode null-only for column-
    # scoped monotone enrichment that preserves prod drift on other columns.
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
        except Exception as e:
            print(f"    WARNING: DROP TABLE {table} failed ({e}); continuing")
        prod_con.execute(f"""
            CREATE TABLE {table} AS
            SELECT {select_cols} FROM staging_db.{table}
        """)
        return staging_count, 0, 0


def merge_table_null_only(prod_con, staging_con, table, pk_cols, columns, dry_run=False):
    """Column-scoped NULL-only merge. Returns list of per-column stats dicts.

    Monotone semantics: for each (pk, col), writes staging.col into prod.col
    only when prod.col IS NULL AND staging.col IS NOT NULL. Never overwrites
    a non-NULL prod value; never reverts a value to NULL. Idempotent — a
    second run writes zero rows.

    Each stats dict has keys: column, prod_null_rows, would_write,
    unchanged_prod_nonnull, written (0 in dry-run).

    Validation: pk_cols must be a list (full-replace tables have no row
    identity); every column in `columns` must exist in both staging and prod.
    """
    if not pk_cols:
        raise ValueError(
            f"{table}: --mode null-only requires a PK-keyed table "
            "(TABLE_KEYS[t] is None — full-replace tables have no row identity)"
        )

    staging_cols = get_columns(staging_con, table)
    prod_cols = get_columns(prod_con, table)
    missing_staging = [c for c in columns if c not in staging_cols]
    missing_prod = [c for c in columns if c not in prod_cols]
    if missing_staging or missing_prod:
        details = []
        if missing_staging:
            details.append(f"missing in staging: {missing_staging}")
        if missing_prod:
            details.append(f"missing in prod: {missing_prod}")
        raise ValueError(f"{table}: column(s) not present in both DBs — {'; '.join(details)}")

    missing_pk_staging = [c for c in pk_cols if c not in staging_cols]
    missing_pk_prod = [c for c in pk_cols if c not in prod_cols]
    if missing_pk_staging or missing_pk_prod:
        raise ValueError(
            f"{table}: PK column(s) missing — staging missing {missing_pk_staging}, "
            f"prod missing {missing_pk_prod}"
        )

    pk_join = " AND ".join(f'p."{c}" = s."{c}"' for c in pk_cols)

    results = []
    for col in columns:
        breakdown_sql = f"""
            SELECT
              SUM(CASE WHEN p."{col}" IS NULL                              THEN 1 ELSE 0 END) AS prod_null_rows,
              SUM(CASE WHEN p."{col}" IS NULL AND s."{col}" IS NOT NULL    THEN 1 ELSE 0 END) AS would_write,
              SUM(CASE WHEN p."{col}" IS NOT NULL                          THEN 1 ELSE 0 END) AS unchanged_prod_nonnull
            FROM "{table}" p
            JOIN staging_db."{table}" s ON {pk_join}
        """
        row = prod_con.execute(breakdown_sql).fetchone()
        prod_null_rows = row[0] or 0
        would_write = row[1] or 0
        unchanged_prod_nonnull = row[2] or 0

        written = 0
        if not dry_run and would_write:
            prod_con.execute(f"""
                UPDATE "{table}" AS p
                SET "{col}" = s."{col}"
                FROM staging_db."{table}" AS s
                WHERE {pk_join}
                  AND p."{col}" IS NULL
                  AND s."{col}" IS NOT NULL
            """)
            written = would_write

        results.append({
            "column": col,
            "prod_null_rows": prod_null_rows,
            "would_write": would_write,
            "unchanged_prod_nonnull": unchanged_prod_nonnull,
            "written": written,
        })

    return results


def main():
    parser = argparse.ArgumentParser(description="Merge staging DB into production")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Merge every table in staging. DESTRUCTIVE — requires --i-really-mean-all.",
    )
    parser.add_argument(
        "--i-really-mean-all",
        action="store_true",
        dest="confirm_all",
        help="Acknowledge that --all merges every staging table including reference "
             "tables and can overwrite prod with staging state. Required with --all.",
    )
    parser.add_argument("--tables", type=str, help="Comma-separated table names to merge")
    parser.add_argument("--dry-run", action="store_true", help="Show what would change without writing")
    parser.add_argument("--drop-staging", action="store_true", help="Delete staging DB after successful merge")
    parser.add_argument(
        "--mode",
        choices=["upsert", "replace", "null-only"],
        default="upsert",
        help="Merge mode. 'upsert' (default) and 'replace' preserve existing "
             "behavior (PK-keyed DELETE+INSERT or DROP+CTAS dispatched by the "
             "registry). 'null-only' is a column-scoped monotone merge that "
             "writes staging values into prod only where the prod cell IS NULL; "
             "requires --columns and PK-keyed tables.",
    )
    parser.add_argument(
        "--columns",
        type=str,
        help="Comma-separated column list. Required with --mode null-only; "
             "rejected with other modes.",
    )
    args = parser.parse_args()

    if not args.all and not args.tables:
        parser.error("Specify --all or --tables")

    if args.mode == "null-only":
        if not args.columns:
            parser.error("--mode null-only requires --columns c1,c2,...")
        if args.all:
            parser.error("--mode null-only is incompatible with --all; use --tables")
        if not args.tables:
            parser.error("--mode null-only requires --tables")
    else:
        if args.columns:
            parser.error("--columns is only valid with --mode null-only")

    # INF10 guardrail (2026-04-10): `--all` used to be the default call
    # from run_pipeline.sh, and would silently full-replace every table
    # in staging — including reference tables like holdings_v2, managers,
    # fund_holdings_v2, market_data (tables not in TABLE_KEYS hit the
    # drop+recreate branch of merge_table()). The pipeline now names
    # tables explicitly; anyone still reaching for --all must opt in
    # explicitly to make the scope visible at the call site.
    if args.all and not args.confirm_all and not args.dry_run:
        parser.error(
            "--all is destructive: it full-replaces every non-PK staging table "
            "(holdings, managers, entities, ...). Pass --i-really-mean-all to "
            "acknowledge, or use --tables <name,...> for a targeted merge. "
            "--dry-run bypasses this check for inspection."
        )

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

    null_only_columns = (
        [c.strip() for c in args.columns.split(",") if c.strip()]
        if args.mode == "null-only"
        else []
    )

    # Merge each table
    if args.mode == "null-only":
        print(f"{'Table':30s} {'Column':24s} {'ProdNULL':>10s} {'WouldWrite':>12s} {'PreservedNonNULL':>18s}")
        print(f"{'-'*30} {'-'*24} {'-'*10} {'-'*12} {'-'*18}")
    else:
        print(f"{'Table':40s} {'Added':>8s} {'Replaced':>10s} {'Prev':>8s}")
        print(f"{'-'*40} {'-'*8} {'-'*10} {'-'*8}")

    total_added = 0
    total_replaced = 0
    total_would_write = 0
    total_written = 0
    errors: list[tuple[str, str]] = []

    for table in tables_to_merge:
        pk_cols = TABLE_KEYS.get(table)

        # Ensure target table exists in production
        if not args.dry_run and args.mode != "null-only":
            prod_exists = count_rows(prod_con, table) >= 0
            if not prod_exists:
                # Create empty table with same schema
                try:
                    columns = get_columns(staging_con, table)
                    col_list = ", ".join(columns)
                    prod_con.execute(f"CREATE TABLE {table} AS SELECT {col_list} FROM staging_db.{table} WHERE 1=0")
                except Exception as e:
                    print(f"    WARNING: pre-create of empty {table} failed ({e}); continuing")

        try:
            if args.mode == "null-only":
                stats = merge_table_null_only(
                    prod_con, staging_con, table, pk_cols, null_only_columns, dry_run=args.dry_run
                )
                for s in stats:
                    total_would_write += s["would_write"]
                    total_written += s["written"]
                    print(
                        f"  {table:28s} {s['column']:24s} {s['prod_null_rows']:>10,} "
                        f"{s['would_write']:>12,} {s['unchanged_prod_nonnull']:>18,}"
                    )
            else:
                added, replaced, prev = merge_table(prod_con, staging_con, table, pk_cols, dry_run=args.dry_run)
                total_added += added
                total_replaced += replaced
                print(f"  {table:38s} {added:>8,} {replaced:>10,} {prev:>8,}")
        except Exception as e:
            # Collect per-table errors and fail the run non-zero at the end.
            # Dry-run keeps errors as warnings only (preserve inspection contract).
            errors.append((table, str(e)))
            print(f"  {table:38s} ERROR: {e}")

    if not args.dry_run:
        prod_con.execute("CHECKPOINT")

    prod_con.close()
    staging_con.close()

    if args.mode == "null-only":
        if args.dry_run:
            print(f"\n  Total would_write: {total_would_write:,}")
        else:
            print(f"\n  Total written: {total_written:,}")
    else:
        print(f"\n  Total added: {total_added:,}, replaced: {total_replaced:,}")

    if args.drop_staging and not args.dry_run and not errors:
        os.remove(STAGING_DB)
        print(f"  Staging DB deleted: {STAGING_DB}")
    elif args.drop_staging and errors:
        print("  Staging DB retained for investigation (merge had errors).")

    print(f"\n{'DRY RUN complete' if args.dry_run else 'Merge complete'}: {datetime.now().strftime('%H:%M:%S')}")

    if errors:
        print(f"\n  {len(errors)} table(s) failed to merge:")
        for tbl, msg in errors:
            print(f"    - {tbl}: {msg}")
        if not args.dry_run:
            sys.exit(1)


if __name__ == "__main__":
    main()
