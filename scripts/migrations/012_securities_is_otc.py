#!/usr/bin/env python3
# pylint: disable=invalid-name  # migration files follow NNN_description.py convention
"""Migration 012 — add is_otc BOOLEAN to securities and cusip_classifications.

int-13 Phase 1, INF29. Adds a dedicated OTC-grey-market flag alongside
(not replacing) is_priceable. Liquid-only downstream queries compose
``WHERE is_priceable AND NOT is_otc``. Backfill is a separate one-off
(scripts/oneoff/backfill_is_otc.py); this migration is pure schema.

Schema changes:
  1. ALTER TABLE securities              ADD COLUMN is_otc BOOLEAN DEFAULT FALSE
  2. ALTER TABLE cusip_classifications   ADD COLUMN is_otc BOOLEAN DEFAULT FALSE

Idempotent — probes each column via duckdb_columns() and skips if already
present. Re-running after success is a no-op. Stamps schema_versions.

Usage:
  python3 scripts/migrations/012_securities_is_otc.py --staging --dry-run
  python3 scripts/migrations/012_securities_is_otc.py --staging
  python3 scripts/migrations/012_securities_is_otc.py --prod --dry-run
  python3 scripts/migrations/012_securities_is_otc.py --prod
"""
from __future__ import annotations

import argparse
import os
import time

import duckdb


VERSION = "012_securities_is_otc"
NOTES = "add is_otc BOOLEAN DEFAULT FALSE to securities + cusip_classifications (INF29)"
TARGETS = [
    ("securities",            "is_otc"),
    ("cusip_classifications", "is_otc"),
]


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
    """Apply migration 012 to `db_path`. --dry-run reports only."""
    if not os.path.exists(db_path):
        print(f"  SKIP: {db_path} does not exist")
        return

    con = duckdb.connect(db_path, read_only=dry_run)
    try:
        print(f"  DB: {db_path}")
        print(f"  dry_run: {dry_run}")

        # Probe each target table + column.
        state: list[tuple[str, str, bool, bool]] = []
        for table, column in TARGETS:
            has_tbl = _has_table(con, table)
            has_col = has_tbl and _has_column(con, table, column)
            state.append((table, column, has_tbl, has_col))
            print(f"  {table}.{column}: table={has_tbl} column={has_col}")

        stamped = _already_stamped(con, VERSION)
        print(f"  schema_versions stamped: {stamped}")

        missing_tables = [t for t, _, has_tbl, _ in state if not has_tbl]
        if missing_tables:
            raise SystemExit(
                f"  ABORT: required tables missing: {missing_tables}"
            )

        all_cols_present = all(has_col for _, _, _, has_col in state)
        if all_cols_present and stamped:
            print("  ALREADY APPLIED: no action")
            return

        if dry_run:
            for table, column, _, has_col in state:
                if not has_col:
                    print(
                        f"    ALTER TABLE {table} "
                        f"ADD COLUMN {column} BOOLEAN DEFAULT FALSE"
                    )
            if not stamped:
                print(f"    INSERT schema_versions: {VERSION}")
            print("  DRY-RUN: no writes performed")
            return

        t_total = time.time()
        for table, column, _, has_col in state:
            if has_col:
                print(f"    {table}.{column}: already present — skip")
                continue
            stmt = (
                f"ALTER TABLE {table} "
                f"ADD COLUMN {column} BOOLEAN DEFAULT FALSE"
            )
            t0 = time.time()
            con.execute(stmt)
            print(f"    {stmt}  ({time.time()-t0:.3f}s)")

        if not stamped:
            con.execute(
                "INSERT INTO schema_versions (version, notes) VALUES (?, ?)",
                [VERSION, NOTES],
            )
            print(f"  stamped schema_versions: {VERSION}")
        con.execute("CHECKPOINT")

        # Post-condition verification.
        for table, column in TARGETS:
            if not _has_column(con, table, column):
                raise SystemExit(
                    f"  MIGRATION FAILED: {table}.{column} not created"
                )
        after_cols = ", ".join(f"{t}.{c}=present" for t, c in TARGETS)
        print(
            f"  AFTER: {after_cols}  "
            f"(total wall: {time.time()-t_total:.2f}s)"
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
