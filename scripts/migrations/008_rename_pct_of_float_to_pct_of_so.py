#!/usr/bin/env python3
# pylint: disable=invalid-name  # migration files follow NNN_description.py convention
"""Migration 008 — rename holdings_v2.pct_of_float → pct_of_so + add audit column.

BLOCK-PCT-OF-SO-PERIOD-ACCURACY Phase 1b, B1.

Phase 0 found no `float_shares` history exists in the DB; the only period-
indexed share count is `shares_outstanding_history.shares` (shares
outstanding, not float). Option A locked: migrate denominator semantics
to shares_outstanding via hard rename of the column plus an audit column
recording the fallback tier each row used.

Schema changes (holdings_v2 only — fund_holdings_v2 and
beneficial_ownership_v2 do not carry pct_of_float, verified Phase 1a §8.5):

  1. RENAME COLUMN pct_of_float TO pct_of_so
  2. ADD COLUMN   pct_of_so_source VARCHAR

Values for pct_of_so_source are written by enrich_holdings.py Pass B.
Three-tier fallback cascade, each surfaced as a distinct audit value
(Phase 1c, 2026-04-19 — widened from two values to three so tier 3
rows are no longer silently labeled "market_data_latest"):
  - 'soh_period_accurate'     : tier 1 — denominator from
                                shares_outstanding_history ASOF at or
                                before quarter_end (period-accurate)
  - 'market_data_so_latest'   : tier 2 — fallback to latest
                                market_data.shares_outstanding (not
                                period-accurate, still SO semantics)
  - 'market_data_float_latest': tier 3 — fallback to latest
                                market_data.float_shares (pct_of_float
                                stored in pct_of_so column; semantic
                                mixing made transparent via this flag)
  - NULL                      : no denominator available; pct_of_so
                                is NULL (not equity, or no SOH / md
                                coverage)

Idempotent: probes the current schema before each step. Re-running after
success is a no-op.

Scope in Phase 1: --staging only. Prod apply is Phase 4.

Usage:
  python3 scripts/migrations/008_rename_pct_of_float_to_pct_of_so.py --staging --dry-run
  python3 scripts/migrations/008_rename_pct_of_float_to_pct_of_so.py --staging
  python3 scripts/migrations/008_rename_pct_of_float_to_pct_of_so.py --prod --dry-run   # Phase 4 preview
  python3 scripts/migrations/008_rename_pct_of_float_to_pct_of_so.py --prod             # Phase 4 apply
"""
from __future__ import annotations

import argparse
import os

import duckdb


VERSION = "008_rename_pct_of_float_to_pct_of_so"
NOTES = "holdings_v2 pct_of_float → pct_of_so rename + pct_of_so_source audit column"
TABLE = "holdings_v2"
OLD_COLUMN = "pct_of_float"
NEW_COLUMN = "pct_of_so"
AUDIT_COLUMN = "pct_of_so_source"


def _has_table(con, name: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM duckdb_tables() WHERE table_name = ?", [name]
    ).fetchone()
    return row is not None


def _has_column(con, table: str, column: str) -> bool:
    row = con.execute(
        """
        SELECT 1 FROM duckdb_columns()
        WHERE table_name = ? AND column_name = ?
        """,
        [table, column],
    ).fetchone()
    return row is not None


def _already_stamped(con, version: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM schema_versions WHERE version = ?", [version]
    ).fetchone()
    return row is not None


def run_migration(db_path: str, dry_run: bool) -> None:
    """Apply migration 008 to `db_path`. --dry-run reports only."""
    if not os.path.exists(db_path):
        print(f"  SKIP: {db_path} does not exist")
        return

    con = duckdb.connect(db_path, read_only=dry_run)
    try:
        if not _has_table(con, TABLE):
            print(f"  SKIP ({db_path}): {TABLE} does not exist")
            return

        print(f"  DB: {db_path}")
        print(f"  dry_run: {dry_run}")

        has_old = _has_column(con, TABLE, OLD_COLUMN)
        has_new = _has_column(con, TABLE, NEW_COLUMN)
        has_audit = _has_column(con, TABLE, AUDIT_COLUMN)
        stamped = _already_stamped(con, VERSION)

        print(f"  has {OLD_COLUMN}: {has_old}")
        print(f"  has {NEW_COLUMN}: {has_new}")
        print(f"  has {AUDIT_COLUMN}: {has_audit}")
        print(f"  schema_versions stamped: {stamped}")

        if has_new and has_audit and not has_old and stamped:
            print("  ALREADY APPLIED: no action")
            return

        if has_old and has_new:
            raise SystemExit(
                f"  ABORT: both {OLD_COLUMN} and {NEW_COLUMN} exist on "
                f"{TABLE}; manual resolution required"
            )

        # Step 1: rename pct_of_float → pct_of_so (if needed)
        if has_old and not has_new:
            stmt = (
                f"ALTER TABLE {TABLE} RENAME COLUMN {OLD_COLUMN} TO {NEW_COLUMN}"
            )
            print(f"    {stmt}")
            if not dry_run:
                con.execute(stmt)

        # Step 2: add pct_of_so_source audit column (if needed)
        if not has_audit:
            stmt = f"ALTER TABLE {TABLE} ADD COLUMN {AUDIT_COLUMN} VARCHAR"
            print(f"    {stmt}")
            if not dry_run:
                con.execute(stmt)

        # Stamp + checkpoint
        if not dry_run:
            if not stamped:
                con.execute(
                    "INSERT INTO schema_versions (version, notes) VALUES (?, ?)",
                    [VERSION, NOTES],
                )
                print(f"  stamped schema_versions: {VERSION}")
            con.execute("CHECKPOINT")

            # Post-condition verification
            after_old = _has_column(con, TABLE, OLD_COLUMN)
            after_new = _has_column(con, TABLE, NEW_COLUMN)
            after_audit = _has_column(con, TABLE, AUDIT_COLUMN)
            if after_old:
                raise SystemExit(
                    f"  MIGRATION FAILED: {OLD_COLUMN} still present on {TABLE}"
                )
            if not after_new:
                raise SystemExit(
                    f"  MIGRATION FAILED: {NEW_COLUMN} not created on {TABLE}"
                )
            if not after_audit:
                raise SystemExit(
                    f"  MIGRATION FAILED: {AUDIT_COLUMN} not created on {TABLE}"
                )
            print(
                f"  AFTER: {OLD_COLUMN}={after_old} {NEW_COLUMN}={after_new} "
                f"{AUDIT_COLUMN}={after_audit}"
            )
    finally:
        con.close()


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", default=None,
                        help="DB path. Defaults to data/13f.duckdb (prod).")
    parser.add_argument("--staging", action="store_true",
                        help="Shortcut for --path data/13f_staging.duckdb")
    parser.add_argument("--prod", action="store_true",
                        help="Explicit prod target; equivalent to default.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report actions; no writes.")
    args = parser.parse_args()

    repo_root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    if args.staging:
        db_path = os.path.join(repo_root, "data", "13f_staging.duckdb")
    elif args.path:
        db_path = args.path
    else:
        db_path = os.path.join(repo_root, "data", "13f.duckdb")

    run_migration(db_path, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
