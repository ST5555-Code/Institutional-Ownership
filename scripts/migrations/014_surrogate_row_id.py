#!/usr/bin/env python3
# pylint: disable=invalid-name  # migration files follow NNN_description.py convention
"""Migration 014 — add surrogate ``row_id`` BIGINT to L3 v2 fact tables.

mig-06 Phase 1 (INF40). Adds a stable per-table surrogate row identifier
to the three L3 canonical fact tables so point-in-time rollback snapshots
can join on a non-volatile handle (DuckDB ``rowid`` is not stable across
full-table UPDATE + CHECKPOINT + index rebuild — see REWRITE_PCT_OF_SO
§14.5 for the precedent).

For each target table, the migration:

  1. ``CREATE SEQUENCE <table>_row_id_seq START 1``
  2. ``ALTER TABLE <table> ADD COLUMN row_id BIGINT
         DEFAULT nextval('<table>_row_id_seq')`` — the default fires once
     per existing row during ALTER, materializing a dense 1..N
     assignment; subsequent INSERTs that omit ``row_id`` in their column
     list continue to pick up the next value automatically.
  3. ``CREATE UNIQUE INDEX idx_<table>_row_id ON <table>(row_id)`` —
     uniqueness is enforced by a UNIQUE INDEX rather than a PRIMARY KEY
     to avoid the full-table rebuild cost that a PK add-after-creation
     would impose (migration 011 / securities precedent).

All three tables are processed in a single transaction so a mid-migration
crash leaves the DB either fully stamped or fully untouched. A final
``CHECKPOINT`` flushes the ALTERed columns and new indexes to disk.

Idempotent — re-runs short-circuit on the first target's column probe
(once ``holdings_v2.row_id`` exists the migration is considered applied).

Zero owner-script change is required: both active writers
(``promote_nport.py``, ``promote_13dg.py``) already use explicit column
lists that omit ``row_id``, so the DEFAULT fires on every INSERT.

Usage::

    python3 scripts/migrations/014_surrogate_row_id.py --staging --dry-run
    python3 scripts/migrations/014_surrogate_row_id.py --staging
    python3 scripts/migrations/014_surrogate_row_id.py --prod --dry-run
    python3 scripts/migrations/014_surrogate_row_id.py --prod
"""
from __future__ import annotations

import argparse
import os
import time

import duckdb


VERSION = "014_surrogate_row_id"
NOTES = (
    "add row_id BIGINT DEFAULT nextval on holdings_v2, fund_holdings_v2, "
    "beneficial_ownership_v2 (mig-06 / INF40)"
)

TABLES = (
    "holdings_v2",
    "fund_holdings_v2",
    "beneficial_ownership_v2",
)


def _seq_name(table: str) -> str:
    return f"{table}_row_id_seq"


def _index_name(table: str) -> str:
    return f"idx_{table}_row_id"


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


def _row_count(con, table: str) -> int:
    return con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]  # nosec B608


def _already_stamped(con, version: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM schema_versions WHERE version = ?", [version]
    ).fetchone()
    return row is not None


def run_migration(db_path: str, dry_run: bool) -> None:
    """Apply migration 014 to `db_path`. --dry-run reports only."""
    if not os.path.exists(db_path):
        print(f"  SKIP: {db_path} does not exist")
        return

    con = duckdb.connect(db_path, read_only=dry_run)
    try:
        print(f"  DB: {db_path}")
        print(f"  dry_run: {dry_run}")

        # Pre-check: all three tables must exist.
        for t in TABLES:
            if not _has_table(con, t):
                raise SystemExit(
                    f"  ABORT: required table missing: {t}"
                )

        # Idempotency trigger: row_id presence on holdings_v2.
        first_has_col = _has_column(con, TABLES[0], "row_id")
        stamped = _already_stamped(con, VERSION)
        print(f"  {TABLES[0]}.row_id present: {first_has_col}")
        print(f"  schema_versions stamped: {stamped}")

        if first_has_col and stamped:
            print("  ALREADY APPLIED: no action")
            return

        # Per-table pre-state (row counts for the confirmation line +
        # per-table has_col to support a partial-state recovery).
        state: list[tuple[str, int, bool]] = []
        for t in TABLES:
            state.append((t, _row_count(con, t), _has_column(con, t, "row_id")))
            print(
                f"  {t}: rows={state[-1][1]:,} "
                f"row_id_present={state[-1][2]}"
            )

        if dry_run:
            for t, _, has_col in state:
                if has_col:
                    print(f"    {t}: row_id already present — would skip")
                    continue
                print(f"    CREATE SEQUENCE {_seq_name(t)} START 1")
                print(
                    f"    ALTER TABLE {t} ADD COLUMN row_id BIGINT "
                    f"DEFAULT nextval('{_seq_name(t)}')"
                )
                print(
                    f"    CREATE UNIQUE INDEX {_index_name(t)} "
                    f"ON {t}(row_id)"
                )
            if not stamped:
                print(f"    INSERT schema_versions: {VERSION}")
            print("  DRY-RUN: no writes performed")
            return

        t_total = time.time()
        timings: list[tuple[str, float]] = []

        con.execute("BEGIN TRANSACTION")
        try:
            for t, _, has_col in state:
                if has_col:
                    print(f"    {t}: row_id already present — skip")
                    timings.append((t, 0.0))
                    continue

                t0 = time.time()
                con.execute(
                    f"CREATE SEQUENCE IF NOT EXISTS {_seq_name(t)} START 1"
                )
                con.execute(
                    f"ALTER TABLE {t} ADD COLUMN row_id BIGINT "
                    f"DEFAULT nextval('{_seq_name(t)}')"
                )
                con.execute(
                    f"CREATE UNIQUE INDEX {_index_name(t)} ON {t}(row_id)"
                )
                elapsed = time.time() - t0
                timings.append((t, elapsed))
                print(f"    {t}: row_id added + unique index built ({elapsed:.3f}s)")

            if not stamped:
                con.execute(
                    "INSERT INTO schema_versions (version, notes) "
                    "VALUES (?, ?)",
                    [VERSION, NOTES],
                )
                print(f"  stamped schema_versions: {VERSION}")
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise

        con.execute("CHECKPOINT")

        # Post-condition verification.
        for t in TABLES:
            if not _has_column(con, t, "row_id"):
                raise SystemExit(
                    f"  MIGRATION FAILED: {t}.row_id not created"
                )
            distinct_n, min_id, max_id, total_n = con.execute(
                f'SELECT COUNT(DISTINCT row_id), MIN(row_id), '
                f'MAX(row_id), COUNT(*) FROM "{t}"'  # nosec B608
            ).fetchone()
            if distinct_n != total_n:
                raise SystemExit(
                    f"  MIGRATION FAILED: {t}.row_id has duplicates "
                    f"(distinct={distinct_n}, rows={total_n})"
                )
            print(
                f"  AFTER {t}: rows={total_n:,} "
                f"row_id range=[{min_id}, {max_id}] distinct={distinct_n:,}"
            )

        for t, secs in timings:
            print(f"  timing {t}: {secs:.3f}s")
        print(f"  total wall: {time.time()-t_total:.2f}s")
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
