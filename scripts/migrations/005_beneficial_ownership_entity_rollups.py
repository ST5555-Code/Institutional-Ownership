#!/usr/bin/env python3
# pylint: disable=invalid-name  # migration files follow NNN_description.py convention
"""Migration 005 — beneficial_ownership_v2 entity rollup columns.

Adds four columns to `beneficial_ownership_v2` so 13D/G rows can carry
the same entity MDM context as `holdings_v2` Group 2:
  - rollup_entity_id    BIGINT   (economic_control_v1 rollup target)
  - rollup_name         VARCHAR  (preferred alias of rollup_entity_id)
  - dm_rollup_entity_id BIGINT   (decision_maker_v1 rollup target)
  - dm_rollup_name      VARCHAR  (preferred alias of dm_rollup_entity_id)

`entity_id BIGINT` is already present (populated ~77% by a legacy pass);
this migration leaves it alone. Population of the new columns is owned
by `bulk_enrich_bo_filers()` in `scripts/pipeline/shared.py`, called
from `promote_13dg.py` at promote time and from `scripts/enrich_13dg.py`
on-demand.

`beneficial_ownership_current` is rebuilt DROP+CREATE from v2 by
`promote_13dg.py`, so it picks up the new columns natively on next
rebuild — no ALTER here.

Idempotent: probes each column before ALTER; skips if present.
Skips entirely when the target table is absent (e.g. staging DB).

Usage:
  python3 scripts/migrations/005_beneficial_ownership_entity_rollups.py --staging --dry-run
  python3 scripts/migrations/005_beneficial_ownership_entity_rollups.py --staging
  python3 scripts/migrations/005_beneficial_ownership_entity_rollups.py --dry-run
  python3 scripts/migrations/005_beneficial_ownership_entity_rollups.py
"""
from __future__ import annotations

import argparse
import os

import duckdb


VERSION = "005_beneficial_ownership_entity_rollups"
NOTES = "13D/G entity rollup columns on beneficial_ownership_v2"
TABLE = "beneficial_ownership_v2"
NEW_COLUMNS = [
    ("rollup_entity_id", "BIGINT"),
    ("rollup_name", "VARCHAR"),
    ("dm_rollup_entity_id", "BIGINT"),
    ("dm_rollup_name", "VARCHAR"),
]


def _has_table(con, name: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM duckdb_tables() WHERE table_name = ?", [name]
    ).fetchone()
    return row is not None


def _existing_columns(con, table: str) -> set[str]:
    rows = con.execute(
        "SELECT column_name FROM duckdb_columns() WHERE table_name = ?",
        [table],
    ).fetchall()
    return {r[0] for r in rows}


def _already_stamped(con, version: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM schema_versions WHERE version = ?", [version]
    ).fetchone()
    return row is not None


def run_migration(db_path: str, dry_run: bool) -> None:
    """Apply migration 005 to `db_path`. --dry-run prints actions only."""
    if not os.path.exists(db_path):
        print(f"  SKIP: {db_path} does not exist")
        return

    con = duckdb.connect(db_path, read_only=dry_run)
    try:
        if not _has_table(con, TABLE):
            print(f"  SKIP ({db_path}): {TABLE} does not exist")
            return

        existing = _existing_columns(con, TABLE)
        pending = [(name, dtype) for name, dtype in NEW_COLUMNS
                   if name not in existing]

        print(f"  DB: {db_path}")
        print(f"  dry_run: {dry_run}")
        print(f"  existing {TABLE} columns: {len(existing)}")
        rows = con.execute(f"SELECT COUNT(*) FROM {TABLE}").fetchone()[0]
        print(f"  rows: {rows:,}")

        if not pending:
            print("  ALREADY APPLIED: all four rollup columns present")
            if not _already_stamped(con, VERSION) and not dry_run:
                con.execute(
                    "INSERT INTO schema_versions (version, notes) VALUES (?, ?)",
                    [VERSION, NOTES],
                )
                con.execute("CHECKPOINT")
                print(f"  stamped schema_versions: {VERSION}")
            return

        print(f"  WILL ADD: {len(pending)} columns")
        for name, dtype in pending:
            stmt = f"ALTER TABLE {TABLE} ADD COLUMN {name} {dtype}"
            print(f"    {stmt}")
            if not dry_run:
                con.execute(stmt)

        if not dry_run:
            if not _already_stamped(con, VERSION):
                con.execute(
                    "INSERT INTO schema_versions (version, notes) VALUES (?, ?)",
                    [VERSION, NOTES],
                )
                print(f"  stamped schema_versions: {VERSION}")
            con.execute("CHECKPOINT")

            after_cols = _existing_columns(con, TABLE)
            missing = [n for n, _ in NEW_COLUMNS if n not in after_cols]
            if missing:
                raise SystemExit(
                    f"  MIGRATION FAILED: columns still missing: {missing}"
                )
            print(f"  AFTER: {len(after_cols)} columns on {TABLE}")
    finally:
        con.close()


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", default=None,
                        help="DB path. Defaults to data/13f.duckdb (prod).")
    parser.add_argument("--staging", action="store_true",
                        help="Shortcut for --path data/13f_staging.duckdb")
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
