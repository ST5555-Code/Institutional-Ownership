#!/usr/bin/env python3
# pylint: disable=invalid-name  # migration files follow NNN_description.py convention
"""Migration 018 — create snapshot_registry sidecar metadata table.

Introduces ``snapshot_registry`` — a governance sidecar for the
``%_snapshot_%`` tables created by ``scripts/promote_staging.py`` and
(historically) one-off remediation scripts. The registry decouples
retention policy from naming conventions: each row records the
snapshot's creator, purpose, expiration, and approver so the
enforcement script (``scripts/hygiene/snapshot_retention.py``) can
drop expired snapshots and preserve declared carve-outs without
parsing table names.

Schema::

    snapshot_table_name  TEXT PRIMARY KEY
    base_table           TEXT NOT NULL
    created_at           TIMESTAMP NOT NULL
    created_by           TEXT NOT NULL
    purpose              TEXT NOT NULL
    expiration           DATE                -- NULL = 14-day default from created_at
    approver             TEXT                -- required for carve-outs
    applied_policy       TEXT NOT NULL       -- 'default_14d' | 'carve_out' | 'retain_indefinite'
    notes                TEXT
    registered_at        TIMESTAMP NOT NULL DEFAULT NOW()

Policy (see docs/findings/2026-04-24-snapshot-inventory.md + the
``snapshot-policy`` session memo):
  * Default retention: 14 days from ``created_at``.
  * Carve-out: ``applied_policy='carve_out'`` requires ``approver`` +
    explicit ``expiration`` date.
  * No registry row = 14-day default auto-applied by the enforcement
    script (treated as if ``created_by='unknown'`` with
    ``applied_policy='default_14d'``).

Idempotent — guarded by ``schema_versions`` stamp and by
``CREATE TABLE IF NOT EXISTS``.

Usage::

    python3 scripts/migrations/018_snapshot_registry.py --dry-run
    python3 scripts/migrations/018_snapshot_registry.py
    python3 scripts/migrations/018_snapshot_registry.py --staging --dry-run
    python3 scripts/migrations/018_snapshot_registry.py --staging
"""
from __future__ import annotations

import argparse
import os

import duckdb


VERSION = "018_snapshot_registry"
NOTES = "create snapshot_registry sidecar for snapshot retention policy"

TABLE = "snapshot_registry"


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


CREATE_SQL = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    snapshot_table_name TEXT PRIMARY KEY,
    base_table          TEXT NOT NULL,
    created_at          TIMESTAMP NOT NULL,
    created_by          TEXT NOT NULL,
    purpose             TEXT NOT NULL,
    expiration          DATE,
    approver            TEXT,
    applied_policy      TEXT NOT NULL,
    notes               TEXT,
    registered_at       TIMESTAMP NOT NULL DEFAULT NOW()
)
"""


def run_migration(db_path: str, dry_run: bool) -> None:
    """Apply migration 018 to ``db_path``. ``--dry-run`` reports only."""
    if not os.path.exists(db_path):
        print(f"  SKIP: {db_path} does not exist")
        return

    con = duckdb.connect(db_path, read_only=dry_run)
    try:
        print(f"  DB: {db_path}")
        print(f"  dry_run: {dry_run}")

        table_present = _has_table(con, TABLE)
        stamped = _already_stamped(con, VERSION)
        print(f"  {TABLE} present BEFORE:     {table_present}")
        print(f"  schema_versions stamped:  {stamped}")

        if table_present and stamped:
            print("  ALREADY APPLIED: no action")
            return

        if dry_run:
            print(f"    CREATE TABLE {TABLE} ...")
            if not stamped:
                print(f"    INSERT schema_versions: {VERSION}")
            print("  DRY-RUN: no writes performed")
            return

        con.execute(CREATE_SQL)
        print(f"    created table {TABLE}")

        if not stamped:
            con.execute(
                "INSERT INTO schema_versions (version, notes) VALUES (?, ?)",
                [VERSION, NOTES],
            )
            print(f"  stamped schema_versions: {VERSION}")
        con.execute("CHECKPOINT")

        table_after = _has_table(con, TABLE)
        print(f"  {TABLE} present AFTER:      {table_after}")
        print(f"Migration 018 applied: {TABLE} ready for backfill")
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
