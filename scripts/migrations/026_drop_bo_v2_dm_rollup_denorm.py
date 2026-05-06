#!/usr/bin/env python3
# pylint: disable=invalid-name  # migration files follow NNN_description.py convention
"""Migration 026 — drop denormalized rollup columns from ``beneficial_ownership_v2``.

Sister-table follow-on to migrations 024 (PR #289 fh2 drop) and 025
(PR #296 holdings_v2 drop). Removes two denormalized cache columns:

* ``beneficial_ownership_v2.dm_rollup_entity_id``
* ``beneficial_ownership_v2.dm_rollup_name``

Rationale: per PR #295 sister-table investigation, ``bo_v2`` carries
zero production readers of these columns (no hits across
``scripts/api_*.py``, ``scripts/queries/``, ``scripts/queries_helpers.py``,
``scripts/app.py``, ``web/``). The columns existed only as a denormalized
cache populated by the 13D/G enrichment loop. Dropping eliminates a
silent drift surface that contributes nothing to read paths.

Writers retired in this PR:

* ``scripts/pipeline/load_13dg.py`` — DDL + INSERT column list trimmed.
* ``scripts/pipeline/shared.py`` — ``bulk_enrich_bo_filers`` UPDATE
  column list trimmed (both full-refresh and scoped variants).
* ``scripts/enrich_13dg.py`` — coverage report + delta detection
  trimmed to ec rollup only.

Mechanism: ``ALTER TABLE ... DROP COLUMN`` cannot be used here because
``beneficial_ownership_v2`` carries a ``PRIMARY KEY`` constraint on
``row_id`` — DuckDB rejects DROP COLUMN when any index (including the
implicit PK index) sits on a column positioned after the dropped column,
and DuckDB does not support ``ALTER TABLE DROP CONSTRAINT``. Same
mechanic as PR #296 / migration 025.

The migration rebuilds the table via ``CREATE TABLE ... AS SELECT *
EXCLUDE (...)``, atomically swaps it in, and re-applies the PRIMARY KEY
constraint plus all observed indexes. Row count is asserted identical
pre/post.

Idempotent: each column is checked before dropping. Re-run on an
already-migrated DB is a no-op. Forward-only per standard policy.

Usage::

    python3 scripts/migrations/026_drop_bo_v2_dm_rollup_denorm.py --dry-run
    python3 scripts/migrations/026_drop_bo_v2_dm_rollup_denorm.py --prod
    python3 scripts/migrations/026_drop_bo_v2_dm_rollup_denorm.py --staging
"""
from __future__ import annotations

import argparse
import os

import duckdb


VERSION = "026_drop_bo_v2_dm_rollup_denorm"
NOTES = (
    "drop beneficial_ownership_v2.dm_rollup_entity_id and dm_rollup_name "
    "(denormalized DM rollup cache — zero production readers per PR #295, "
    "CP-5 sister-table follow-on, conv-30-doc-sync)"
)

TARGETS = (
    ("beneficial_ownership_v2", "dm_rollup_entity_id"),
    ("beneficial_ownership_v2", "dm_rollup_name"),
)

# Pre-migration index inventory (PRAGMA-confirmed 2026-05-06):
#   idx_beneficial_ownership_v2_row_id  UNIQUE  ON (row_id)
#   idx_bov2_entity                              ON (entity_id)
#   idx_bo_v2_latest                             ON (is_latest, filer_cik)
# Plus implicit PRIMARY KEY index on row_id.
_DROP_INDEXES = [
    "DROP INDEX IF EXISTS idx_beneficial_ownership_v2_row_id",
    "DROP INDEX IF EXISTS idx_bov2_entity",
    "DROP INDEX IF EXISTS idx_bo_v2_latest",
]

_ADD_CONSTRAINT = (
    "ALTER TABLE beneficial_ownership_v2 ADD CONSTRAINT "
    "beneficial_ownership_v2_row_id_pkey PRIMARY KEY (row_id)"
)

_RECREATE_INDEXES = [
    "CREATE UNIQUE INDEX idx_beneficial_ownership_v2_row_id "
    "ON beneficial_ownership_v2(row_id)",
    "CREATE INDEX idx_bov2_entity ON beneficial_ownership_v2(entity_id)",
    "CREATE INDEX idx_bo_v2_latest "
    "ON beneficial_ownership_v2(is_latest, filer_cik)",
]


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
    """Apply migration 026 to `db_path`. --dry-run reports only."""
    if not os.path.exists(db_path):
        print(f"  SKIP: {db_path} does not exist")
        return

    con = duckdb.connect(db_path, read_only=dry_run)
    try:
        print(f"  DB: {db_path}")
        print(f"  dry_run: {dry_run}")

        if not _has_table(con, "beneficial_ownership_v2"):
            raise SystemExit(
                "  MIGRATION FAILED: beneficial_ownership_v2 missing in "
                f"{db_path}"
            )

        present = [
            (t, c) for t, c in TARGETS if _has_column(con, t, c)
        ]
        stamped = _already_stamped(con, VERSION)

        for t, c in TARGETS:
            state = "PRESENT" if (t, c) in present else "ABSENT"
            print(f"  {t}.{c} BEFORE: {state}")

        row_count = con.execute(
            "SELECT COUNT(*) FROM beneficial_ownership_v2"
        ).fetchone()[0]
        print(f"  beneficial_ownership_v2 row count: {row_count:,}")
        print(f"  schema_versions stamped: {stamped}")

        if not present and stamped:
            print("  ALREADY APPLIED: no action")
            return

        ctas_sql = (
            "CREATE TABLE beneficial_ownership_v2_new AS "
            "SELECT * EXCLUDE (dm_rollup_entity_id, dm_rollup_name) "
            "FROM beneficial_ownership_v2"
        )

        if dry_run:
            print("  Would execute:")
            for stmt in _DROP_INDEXES:
                print(f"    {stmt}")
            print(f"    {ctas_sql}")
            print("    DROP TABLE beneficial_ownership_v2")
            print(
                "    ALTER TABLE beneficial_ownership_v2_new "
                "RENAME TO beneficial_ownership_v2"
            )
            print(f"    {_ADD_CONSTRAINT}")
            for stmt in _RECREATE_INDEXES:
                print(f"    {stmt}")
            if not stamped:
                print(f"    INSERT schema_versions: {VERSION}")
            print("  DRY-RUN: no writes performed")
            return

        print("  Dropping indexes …")
        for stmt in _DROP_INDEXES:
            con.execute(stmt)
            print(f"    {stmt}")

        print("  Cleaning up any prior beneficial_ownership_v2_new …")
        con.execute("DROP TABLE IF EXISTS beneficial_ownership_v2_new")

        print(
            "  Building beneficial_ownership_v2_new "
            "(SELECT * EXCLUDE …) …"
        )
        con.execute(ctas_sql)
        new_count = con.execute(
            "SELECT COUNT(*) FROM beneficial_ownership_v2_new"
        ).fetchone()[0]
        print(f"    beneficial_ownership_v2_new row count: {new_count:,}")
        if new_count != row_count:
            raise SystemExit(
                "  CTAS COUNT MISMATCH: "
                f"{row_count:,} → {new_count:,}"
            )

        print("  Swapping tables …")
        con.execute("DROP TABLE beneficial_ownership_v2")
        con.execute(
            "ALTER TABLE beneficial_ownership_v2_new "
            "RENAME TO beneficial_ownership_v2"
        )

        dropped = len(present)
        for t, c in present:
            print(f"    DROP COLUMN {t}.{c}")

        print("  Restoring PRIMARY KEY constraint …")
        con.execute(_ADD_CONSTRAINT)
        print(f"    {_ADD_CONSTRAINT}")

        print("  Recreating indexes …")
        for stmt in _RECREATE_INDEXES:
            con.execute(stmt)
            print(f"    {stmt}")

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

        post_count = con.execute(
            "SELECT COUNT(*) FROM beneficial_ownership_v2"
        ).fetchone()[0]
        print(f"  beneficial_ownership_v2 row count after: {post_count:,}")
        if post_count != row_count:
            raise SystemExit(
                f"  ROW COUNT CHANGED: {row_count:,} → {post_count:,}"
            )
        print("  row count unchanged: OK")
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
