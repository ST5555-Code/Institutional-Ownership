#!/usr/bin/env python3
# pylint: disable=invalid-name  # migration files follow NNN_description.py convention
"""Migration 009 — admin_sessions table for server-side admin auth.

sec-01 Phase 1 (docs/findings/sec-01-p0-findings.md §6.1/§6.2). Replaces the
localStorage-persisted admin token with an HttpOnly cookie backed by a
server-side session row. This migration only adds the table; the auth
code change lives in scripts/admin_bp.py in the same branch.

Schema:

  CREATE TABLE admin_sessions (
    session_id   VARCHAR PRIMARY KEY,   -- uuid4 string
    issued_at    TIMESTAMP NOT NULL,
    expires_at   TIMESTAMP NOT NULL,
    last_used_at TIMESTAMP NOT NULL,
    ip           VARCHAR,
    user_agent   VARCHAR,
    revoked_at   TIMESTAMP
  );
  CREATE INDEX idx_admin_sessions_expires ON admin_sessions(expires_at);

Design notes (from findings §6.1):
  - session_id stored as VARCHAR (uuid4 string) — avoids DuckDB UUID type
    drift across staging/prod.
  - expires_at is the absolute 8h cap; last_used_at drives the 30m idle
    timeout. Both enforced in the auth dep.
  - revoked_at is NULL while active; logout / logout_all set it.
  - ip / user_agent recorded for audit; not pinned (mobile/NAT churn).
  - Index on expires_at used by the opportunistic sweep inside the auth
    dep.

Idempotent: CREATE TABLE / CREATE INDEX use IF NOT EXISTS. Forward-only
(no down()) — the table is pure ephemeral session state and can be
dropped manually if an operator ever needs to rebuild.

Applied to both prod (13f.duckdb) and staging (13f_staging.duckdb) for
schema parity per docs/findings/2026-04-19-block-schema-diff.md conventions (see
§10.6 of findings).

Usage:
  python3 scripts/migrations/009_admin_sessions.py --staging --dry-run
  python3 scripts/migrations/009_admin_sessions.py --staging
  python3 scripts/migrations/009_admin_sessions.py --prod --dry-run
  python3 scripts/migrations/009_admin_sessions.py --prod
"""
from __future__ import annotations

import argparse
import os

import duckdb


VERSION = "009_admin_sessions"
NOTES = "admin_sessions table (sec-01 Phase 1 server-side session storage)"
TABLE = "admin_sessions"
INDEX_NAME = "idx_admin_sessions_expires"

DDL_TABLE = """
    CREATE TABLE IF NOT EXISTS admin_sessions (
        session_id     VARCHAR PRIMARY KEY,
        issued_at      TIMESTAMP NOT NULL,
        expires_at     TIMESTAMP NOT NULL,
        last_used_at   TIMESTAMP NOT NULL,
        ip             VARCHAR,
        user_agent     VARCHAR,
        revoked_at     TIMESTAMP
    )
"""

DDL_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_admin_sessions_expires "
    "ON admin_sessions(expires_at)"
)

EXPECTED_COLUMNS = {
    'session_id', 'issued_at', 'expires_at', 'last_used_at',
    'ip', 'user_agent', 'revoked_at',
}


def _has_table(con, name: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM duckdb_tables() WHERE table_name = ?", [name]
    ).fetchone()
    return row is not None


def _has_index(con, name: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM duckdb_indexes() WHERE index_name = ?", [name]
    ).fetchone()
    return row is not None


def _already_stamped(con, version: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM schema_versions WHERE version = ?", [version]
    ).fetchone()
    return row is not None


def run_migration(db_path: str, dry_run: bool) -> None:
    """Apply migration 009 to `db_path`. --dry-run reports only."""
    if not os.path.exists(db_path):
        print(f"  SKIP: {db_path} does not exist")
        return

    con = duckdb.connect(db_path, read_only=dry_run)
    try:
        print(f"  DB: {db_path}")
        print(f"  dry_run: {dry_run}")

        has_table = _has_table(con, TABLE)
        has_index = _has_index(con, INDEX_NAME)
        stamped = _already_stamped(con, VERSION)
        print(f"  has {TABLE}: {has_table}")
        print(f"  has {INDEX_NAME}: {has_index}")
        print(f"  schema_versions stamped: {stamped}")

        if has_table and has_index and stamped:
            print("  ALREADY APPLIED: no action")
            return

        if dry_run:
            if not has_table:
                print(f"    CREATE TABLE {TABLE} (...)")
            if not has_index:
                print(f"    CREATE INDEX {INDEX_NAME} ON {TABLE}(expires_at)")
            if not stamped:
                print(f"    INSERT schema_versions: {VERSION}")
            print("  DRY-RUN: no writes performed")
            return

        if not has_table:
            con.execute(DDL_TABLE)
            print(f"    CREATE TABLE {TABLE}")
        if not has_index:
            con.execute(DDL_INDEX)
            print(f"    CREATE INDEX {INDEX_NAME}")

        # Verify column set (catches schema drift if an operator built the
        # table manually with a different shape before this migration ran).
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
            f"  AFTER: table={_has_table(con, TABLE)} "
            f"index={_has_index(con, INDEX_NAME)} "
            f"columns={len(cols)}"
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
