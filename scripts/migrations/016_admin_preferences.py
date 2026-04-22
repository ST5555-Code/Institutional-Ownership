#!/usr/bin/env python3
# pylint: disable=invalid-name  # migration files follow NNN_description.py convention
"""Migration 016 — admin_preferences table for per-pipeline auto-approve.

p2-07. Adds the admin_preferences table consumed by the admin refresh
endpoints to store per-(user, pipeline) auto-approval preferences and
conditions.

Schema:

  CREATE TABLE admin_preferences (
    user_id                  VARCHAR,
    pipeline_name            VARCHAR,
    auto_approve_enabled     BOOLEAN DEFAULT FALSE,
    auto_approve_conditions  JSON,
    PRIMARY KEY (user_id, pipeline_name)
  );

Idempotent: CREATE TABLE uses IF NOT EXISTS. Forward-only.

Applied to both prod (13f.duckdb) and staging (13f_staging.duckdb) for
schema parity.

Usage:
  python3 scripts/migrations/016_admin_preferences.py --staging --dry-run
  python3 scripts/migrations/016_admin_preferences.py --staging
  python3 scripts/migrations/016_admin_preferences.py --dry-run
  python3 scripts/migrations/016_admin_preferences.py
"""
from __future__ import annotations

import argparse
import os

import duckdb


VERSION = "016_admin_preferences"
NOTES = "admin_preferences table for per-pipeline auto-approve (p2-07)"
TABLE = "admin_preferences"

DDL_TABLE = """
    CREATE TABLE IF NOT EXISTS admin_preferences (
        user_id                  VARCHAR,
        pipeline_name            VARCHAR,
        auto_approve_enabled     BOOLEAN DEFAULT FALSE,
        auto_approve_conditions  JSON,
        PRIMARY KEY (user_id, pipeline_name)
    )
"""

EXPECTED_COLUMNS = {
    'user_id', 'pipeline_name', 'auto_approve_enabled',
    'auto_approve_conditions',
}


def _has_table(con, name: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM duckdb_tables() WHERE table_name = ?", [name]
    ).fetchone()
    return row is not None


def _already_stamped(con, version: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM schema_versions WHERE version = ?", [version]
    ).fetchone()
    return row is not None


def run_migration(db_path: str, dry_run: bool) -> None:
    if not os.path.exists(db_path):
        print(f"  SKIP: {db_path} does not exist")
        return

    con = duckdb.connect(db_path, read_only=dry_run)
    try:
        print(f"  DB: {db_path}")
        print(f"  dry_run: {dry_run}")

        has_table = _has_table(con, TABLE)
        stamped = _already_stamped(con, VERSION)
        print(f"  has {TABLE}: {has_table}")
        print(f"  schema_versions stamped: {stamped}")

        if has_table and stamped:
            print("  ALREADY APPLIED: no action")
            return

        if dry_run:
            if not has_table:
                print(f"    CREATE TABLE {TABLE} (...)")
            if not stamped:
                print(f"    INSERT schema_versions: {VERSION}")
            print("  DRY-RUN: no writes performed")
            return

        if not has_table:
            con.execute(DDL_TABLE)
            print(f"    CREATE TABLE {TABLE}")

        cols = {
            r[0] for r in con.execute(
                "SELECT column_name FROM duckdb_columns() WHERE table_name = ?",
                [TABLE],
            ).fetchall()
        }
        missing = EXPECTED_COLUMNS - cols
        extra = cols - EXPECTED_COLUMNS
        if missing:
            raise SystemExit(
                f"  MIGRATION FAILED: {TABLE} missing columns: {sorted(missing)}"
            )
        if extra:
            print(f"  WARNING: {TABLE} has unexpected extra columns: {sorted(extra)}")

        if not stamped:
            con.execute(
                "INSERT INTO schema_versions (version, notes) VALUES (?, ?)",
                [VERSION, NOTES],
            )
            print(f"  stamped schema_versions: {VERSION}")
        con.execute("CHECKPOINT")

        print(
            f"  AFTER: table={_has_table(con, TABLE)} columns={len(cols)}"
        )
    finally:
        con.close()


def main() -> None:
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
