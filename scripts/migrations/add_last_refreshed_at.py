#!/usr/bin/env python3
"""Migration — add last_refreshed_at to entity_relationships.

Problem this solves
-------------------
`entity_relationships.valid_from` is a uniform `DATE '2000-01-01'` sentinel
across every row. `valid_to` uses `DATE '9999-12-31'` for open rows. Neither
records when a relationship was most recently confirmed by an upstream
source (N-CEN / ADV / parent_bridge).

Without a "last refreshed" timestamp we cannot tell:
  * whether an ADV-sourced relationship is still current or has drifted
  * which open rows need re-validation after an N-CEN refresh cycle
  * which relationships are stale enough to warrant a suppress_relationship
    override vs a fresh confirmation

This migration adds a nullable `last_refreshed_at TIMESTAMP` column. New
inserts via `entity_sync.insert_relationship_idempotent` will stamp it at
`NOW()`. A confirmation/refresh (re-insert that hits the ON CONFLICT path,
or a deferred primary that was re-observed by N-CEN/ADV) will bump it —
without closing the existing row.

Existing rows are best-effort backfilled to `created_at` so the column is
never NULL on historical data.

Rollout
-------
This migration is written but **not yet run**. It executes in the next
entity-work session after the staging DB write lock releases. The change
order is:
  1. Apply to `data/13f_staging.duckdb` first.
  2. Re-run `validate_entities.py --staging` — gates are all SELECT, but
     confirm they still pass.
  3. Apply to `data/13f.duckdb` (prod).
  4. Deploy the updated `entity_sync.insert_relationship_idempotent` that
     writes/updates `last_refreshed_at`.

Usage
-----
  python3 scripts/migrations/add_last_refreshed_at.py --staging --dry-run
  python3 scripts/migrations/add_last_refreshed_at.py --staging
  python3 scripts/migrations/add_last_refreshed_at.py --prod --dry-run
  python3 scripts/migrations/add_last_refreshed_at.py --prod
  python3 scripts/migrations/add_last_refreshed_at.py --path path/to/db
"""
from __future__ import annotations

import argparse
import os

import duckdb


VERSION = "add_last_refreshed_at"
NOTES = "entity_relationships.last_refreshed_at column + backfill"


def _already_stamped(con, version: str) -> bool:
    """True if `schema_versions` has a row for `version`. False if the
    table is missing (pre-003 DB) or the row is absent."""
    row = con.execute(
        "SELECT 1 FROM duckdb_tables() WHERE table_name = 'schema_versions'"
    ).fetchone()
    if not row:
        return False
    row = con.execute(
        "SELECT 1 FROM schema_versions WHERE version = ?", [version]
    ).fetchone()
    return row is not None


def run_migration(db_path: str, dry_run: bool = False) -> None:
    if not os.path.exists(db_path):
        print(f"  SKIP: {db_path} does not exist")
        return

    con = duckdb.connect(db_path, read_only=dry_run)
    try:
        cols_before = con.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'entity_relationships'
              AND column_name = 'last_refreshed_at'
        """).fetchall()

        if cols_before:
            if not _already_stamped(con, VERSION):
                if dry_run:
                    print(f"  {db_path}: last_refreshed_at already present, "
                          f"schema_versions stamp missing")
                    print(f"    WILL INSERT schema_versions: {VERSION}")
                    print("  DRY-RUN — no writes.")
                else:
                    con.execute(
                        "INSERT OR IGNORE INTO schema_versions "
                        "(version, notes) VALUES (?, ?)",
                        [VERSION, NOTES],
                    )
                    con.execute("CHECKPOINT")
                    print(f"  {db_path}: last_refreshed_at already present — "
                          f"backfilled schema_versions stamp")
            else:
                print(f"  {db_path}: last_refreshed_at already present — no-op")
            return

        n_total = con.execute(
            "SELECT COUNT(*) FROM entity_relationships"
        ).fetchone()[0]
        n_with_created = con.execute(
            "SELECT COUNT(*) FROM entity_relationships "
            "WHERE created_at IS NOT NULL"
        ).fetchone()[0]
        stamped = _already_stamped(con, VERSION)
        print(f"  {db_path}: dry_run={dry_run}")
        print(f"    rows total              : {n_total:,}")
        print(f"    rows with created_at    : {n_with_created:,}")
        print(f"    rows without created_at : {n_total - n_with_created:,}")
        print(f"    schema_versions stamped : {stamped}")
        print("  WILL ADD: last_refreshed_at TIMESTAMP")
        print("  WILL BACKFILL: last_refreshed_at = created_at "
              "WHERE created_at IS NOT NULL")
        if not stamped:
            print(f"  WILL INSERT schema_versions: {VERSION}")

        if dry_run:
            print("  DRY-RUN — no writes.")
            return

        con.execute(
            "ALTER TABLE entity_relationships "
            "ADD COLUMN last_refreshed_at TIMESTAMP"
        )

        # Best-effort backfill: use created_at as the "last known refresh".
        # Rows written before created_at existed will remain NULL, which
        # is the desired "unknown" signal. Future N-CEN / ADV runs bump
        # the column at the call site.
        con.execute("""
            UPDATE entity_relationships
            SET last_refreshed_at = created_at
            WHERE last_refreshed_at IS NULL
              AND created_at IS NOT NULL
        """)
        if not _already_stamped(con, VERSION):
            con.execute(
                "INSERT OR IGNORE INTO schema_versions "
                "(version, notes) VALUES (?, ?)",
                [VERSION, NOTES],
            )
        con.execute("CHECKPOINT")

        n_backfilled = con.execute(
            "SELECT COUNT(*) FROM entity_relationships "
            "WHERE last_refreshed_at IS NOT NULL"
        ).fetchone()[0]
        print(f"  AFTER: backfilled {n_backfilled:,} / {n_total:,}  "
              f"NULL (no created_at): {n_total - n_backfilled:,}")
    finally:
        con.close()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    target = p.add_mutually_exclusive_group()
    target.add_argument("--staging", action="store_true",
                        help="apply to data/13f_staging.duckdb")
    target.add_argument("--prod", action="store_true",
                        help="apply to data/13f.duckdb")
    p.add_argument("--path", default=None,
                   help="explicit DB path (overrides --staging / --prod)")
    p.add_argument("--dry-run", action="store_true",
                   help="report actions; no writes")
    args = p.parse_args()

    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if args.path:
        db_path = args.path
    elif args.staging:
        db_path = os.path.join(here, "data", "13f_staging.duckdb")
    else:  # default / --prod
        db_path = os.path.join(here, "data", "13f.duckdb")

    run_migration(db_path, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
