#!/usr/bin/env python3
# pylint: disable=invalid-name  # migration files follow NNN_description.py convention
"""Migration 006 — entity_overrides_persistent.override_id sequence + NOT NULL.

Fixes schema gaps left after the INF22 heal (commit bb444d7, 2026-04-16):
  1. Backfill landed 58 NULL → sequential IDs via CTAS rebuild in
     promote_staging._heal_override_ids() (staging) and DM14 promote (prod);
     both DBs now have 90 rows, 0 NULLs, MAX(override_id)=90.
  2. BUT the column is still nullable and has no DEFAULT. New inserts rely
     on admin_bp.py computing MAX+1 in Python — race-prone, and direct
     INSERTs (scripts, manual SQL) can still write NULL.

This migration closes the loop:
  - CREATE SEQUENCE override_id_seq START WITH (MAX(override_id) + 1)
  - ALTER COLUMN override_id SET DEFAULT nextval('override_id_seq')
  - ALTER COLUMN override_id SET NOT NULL   (guard: abort if any NULLs)

Idempotent: probes the sequence and column default/nullability before each
step. Skips entirely when entity_overrides_persistent is absent.

Usage:
  python3 scripts/migrations/006_override_id_sequence.py --staging --dry-run
  python3 scripts/migrations/006_override_id_sequence.py --staging
  python3 scripts/migrations/006_override_id_sequence.py --prod --dry-run
  python3 scripts/migrations/006_override_id_sequence.py --prod
"""
from __future__ import annotations

import argparse
import os

import duckdb


VERSION = "006_override_id_sequence"
NOTES = "override_id sequence + DEFAULT nextval + NOT NULL constraint"
TABLE = "entity_overrides_persistent"
COLUMN = "override_id"
SEQUENCE = "override_id_seq"


def _has_table(con, name: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM duckdb_tables() WHERE table_name = ?", [name]
    ).fetchone()
    return row is not None


def _has_sequence(con, name: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM duckdb_sequences() WHERE sequence_name = ?", [name]
    ).fetchone()
    return row is not None


def _column_info(con, table: str, column: str) -> tuple[str | None, bool] | None:
    """Return (column_default, is_nullable) or None if column missing."""
    row = con.execute(
        """
        SELECT column_default, is_nullable
        FROM duckdb_columns()
        WHERE table_name = ? AND column_name = ?
        """,
        [table, column],
    ).fetchone()
    if row is None:
        return None
    return (row[0], bool(row[1]))


def _already_stamped(con, version: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM schema_versions WHERE version = ?", [version]
    ).fetchone()
    return row is not None


def run_migration(db_path: str, dry_run: bool) -> None:
    """Apply migration 006 to `db_path`. --dry-run reports only."""
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

        total = con.execute(f"SELECT COUNT(*) FROM {TABLE}").fetchone()[0]
        nulls = con.execute(
            f"SELECT COUNT(*) FROM {TABLE} WHERE {COLUMN} IS NULL"
        ).fetchone()[0]
        max_id = con.execute(f"SELECT MAX({COLUMN}) FROM {TABLE}").fetchone()[0]
        print(f"  rows: {total:,}  {COLUMN} NULLs: {nulls}  MAX: {max_id}")

        if nulls > 0:
            raise SystemExit(
                f"  ABORT: {nulls} NULL {COLUMN} rows; heal before running 006"
            )

        start_with = (max_id or 0) + 1
        col_info = _column_info(con, TABLE, COLUMN)
        if col_info is None:
            raise SystemExit(f"  ABORT: {TABLE}.{COLUMN} not found")
        current_default, is_nullable = col_info
        desired_default = f"nextval('{SEQUENCE}')"

        seq_exists = _has_sequence(con, SEQUENCE)
        default_ok = current_default == desired_default
        nullable_ok = not is_nullable
        stamped = _already_stamped(con, VERSION)

        print(f"  sequence {SEQUENCE} exists: {seq_exists}")
        print(f"  current default: {current_default!r}  target: {desired_default!r}")
        print(f"  is_nullable: {is_nullable}  target: False")
        print(f"  schema_versions stamped: {stamped}")

        if seq_exists and default_ok and nullable_ok and stamped:
            print("  ALREADY APPLIED: no action")
            return

        if not seq_exists:
            stmt = f"CREATE SEQUENCE {SEQUENCE} START WITH {start_with}"
            print(f"    {stmt}")
            if not dry_run:
                con.execute(stmt)

        if not default_ok:
            stmt = (
                f"ALTER TABLE {TABLE} ALTER COLUMN {COLUMN} "
                f"SET DEFAULT {desired_default}"
            )
            print(f"    {stmt}")
            if not dry_run:
                con.execute(stmt)

        if not nullable_ok:
            stmt = f"ALTER TABLE {TABLE} ALTER COLUMN {COLUMN} SET NOT NULL"
            print(f"    {stmt}")
            if not dry_run:
                con.execute(stmt)

        if not dry_run:
            if not stamped:
                con.execute(
                    "INSERT INTO schema_versions (version, notes) VALUES (?, ?)",
                    [VERSION, NOTES],
                )
                print(f"  stamped schema_versions: {VERSION}")
            con.execute("CHECKPOINT")

            after_default, after_nullable = _column_info(con, TABLE, COLUMN)
            after_seq = _has_sequence(con, SEQUENCE)
            if not after_seq:
                raise SystemExit("  MIGRATION FAILED: sequence not created")
            if after_default != desired_default:
                raise SystemExit(
                    f"  MIGRATION FAILED: default is {after_default!r}, "
                    f"expected {desired_default!r}"
                )
            if after_nullable:
                raise SystemExit(
                    "  MIGRATION FAILED: column still nullable"
                )
            print(
                f"  AFTER: sequence={after_seq} default={after_default!r} "
                f"nullable={after_nullable}"
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
