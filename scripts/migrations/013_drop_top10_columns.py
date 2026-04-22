#!/usr/bin/env python3
# pylint: disable=invalid-name  # migration files follow NNN_description.py convention
"""Migration 013 — drop unused ``top10_*`` placeholder columns.

int-17 (INF36). The summary build (``scripts/build_summaries.py``) has
historically declared two ``VARCHAR`` placeholder columns for top-10
detail strings and inserted ``NULL`` into them on every rebuild:

* ``summary_by_parent.top10_tickers``
* ``summary_by_ticker.top10_holders``

A reader scan across ``scripts/`` and ``web/`` (excluding the writer
itself, retired code, and earlier migrations) found zero callers of
either column. The decision recorded against int-17 is to drop both
columns outright; if a top-10 surface is ever required it will be
materialized as a read-time query or a separate detail table rather than
re-introduced as a denormalized string column.

DDL applied (one statement per column — DuckDB's ``ALTER TABLE`` accepts
a single ``DROP COLUMN`` clause per call)::

    ALTER TABLE summary_by_parent DROP COLUMN top10_tickers;
    ALTER TABLE summary_by_ticker DROP COLUMN top10_holders;

Idempotent: each target is checked against ``duckdb_columns()`` before
the drop, so a re-run on an already-migrated DB is a no-op. The
``schema_versions`` stamp is written once after at least one drop has
been applied or when no drops are needed but the stamp is missing.

Forward-only — reverting the code is the rollback path; restoring the
columns would require a column-add that no downstream needs.

Usage::

    python3 scripts/migrations/013_drop_top10_columns.py --staging --dry-run
    python3 scripts/migrations/013_drop_top10_columns.py --staging
    python3 scripts/migrations/013_drop_top10_columns.py --prod --dry-run
    python3 scripts/migrations/013_drop_top10_columns.py --prod
"""
from __future__ import annotations

import argparse
import os

import duckdb


VERSION = "013_drop_top10_columns"
NOTES = (
    "drop unused top10_* placeholder columns from summary_by_parent "
    "and summary_by_ticker (int-17 / INF36)"
)

TARGETS = (
    ("summary_by_parent", "top10_tickers"),
    ("summary_by_ticker", "top10_holders"),
)


def _has_table(con, name: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM duckdb_tables() WHERE table_name = ?", [name]
    ).fetchone()
    return row is not None


def _has_column(con, table: str, column: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM duckdb_columns() "
        "WHERE table_name = ? AND column_name = ?",
        [table, column],
    ).fetchone()
    return row is not None


def _already_stamped(con, version: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM schema_versions WHERE version = ?", [version]
    ).fetchone()
    return row is not None


def run_migration(db_path: str, dry_run: bool) -> None:
    """Apply migration 013 to `db_path`. --dry-run reports only."""
    if not os.path.exists(db_path):
        print(f"  SKIP: {db_path} does not exist")
        return

    con = duckdb.connect(db_path, read_only=dry_run)
    try:
        print(f"  DB: {db_path}")
        print(f"  dry_run: {dry_run}")

        for table, _col in TARGETS:
            if not _has_table(con, table):
                raise SystemExit(
                    f"  MIGRATION FAILED: {table} missing in {db_path}"
                )

        present = [
            (t, c) for t, c in TARGETS if _has_column(con, t, c)
        ]
        stamped = _already_stamped(con, VERSION)

        for t, c in TARGETS:
            state = "PRESENT" if (t, c) in present else "ABSENT"
            print(f"  {t}.{c} BEFORE: {state}")
        print(f"  schema_versions stamped: {stamped}")

        if not present and stamped:
            print("  ALREADY APPLIED: no action")
            return

        if dry_run:
            for t, c in present:
                print(f"    ALTER TABLE {t} DROP COLUMN {c}")
            if not stamped:
                print(f"    INSERT schema_versions: {VERSION}")
            print("  DRY-RUN: no writes performed")
            return

        dropped = 0
        for t, c in present:
            con.execute(f"ALTER TABLE {t} DROP COLUMN {c}")  # nosec B608
            print(f"    DROP COLUMN {t}.{c}")
            dropped += 1

        if not stamped:
            con.execute(
                "INSERT INTO schema_versions (version, notes) VALUES (?, ?)",
                [VERSION, NOTES],
            )
            print(f"  stamped schema_versions: {VERSION}")
        con.execute("CHECKPOINT")

        for t, c in TARGETS:
            state = "PRESENT" if _has_column(con, t, c) else "ABSENT"
            print(f"  {t}.{c} AFTER:  {state}")
        print(f"  columns dropped: {dropped}")
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
