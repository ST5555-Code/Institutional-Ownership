#!/usr/bin/env python3
# pylint: disable=invalid-name  # migration files follow NNN_description.py convention
"""Migration 010 — drop DEFAULT nextval on pipeline control-plane PKs.

obs-03 Phase 1 (docs/findings/obs-03-p0-findings.md §5,
archive/docs/prompts/obs-03-p1.md §4). Retires the DuckDB sequence-driven default
on ``ingestion_impacts.impact_id`` and ``ingestion_manifest.manifest_id``
in favour of the centralized allocator in
``scripts/pipeline/id_allocator.py``.

Root cause recap (see findings §3, §4): the mirror paths in
``promote_nport.py`` / ``promote_13dg.py`` copy staging PKs into prod
without advancing prod's sequence, so ``impact_id_seq.last_value`` has
drifted ~40,653 rows behind ``MAX(impact_id)``. Any caller that ever
triggers the DEFAULT path produces an immediate PK collision. Phase 1
removes that footgun outright — no caller needs ``DEFAULT nextval`` once
``allocate_id`` / ``reserve_ids`` are in place.

Per Phase 1 decision #3 we retain the sequence objects themselves for
one release cycle as diagnostic state; a follow-up migration drops them
after a clean cycle confirms no caller ever referenced them.

DDL applied::

    ALTER TABLE ingestion_impacts  ALTER COLUMN impact_id   DROP DEFAULT;
    ALTER TABLE ingestion_manifest ALTER COLUMN manifest_id DROP DEFAULT;

DuckDB quirk: ``ALTER TABLE ... ALTER COLUMN ... DROP DEFAULT`` fails
with ``DependencyException`` if *any* index exists on the table — even
indexes that do not touch the altered column (see duckdb#17348,
duckdb#15399). Both control-plane tables have indexes in prod. The
migration therefore drops every index on each target table before the
ALTER and recreates them from the stored ``duckdb_indexes().sql`` after.

Idempotent: the migration inspects ``duckdb_columns().column_default``
before issuing each ``DROP DEFAULT`` so re-running against an already
migrated DB is a no-op. The drop/recreate of indexes is skipped when
no DROP DEFAULT is required. Forward-only — reverting the code is the
rollback path; restoring the default would require a column-rebuild
that no downstream needs.

Applied to both prod (``13f.duckdb``) and staging
(``13f_staging.duckdb``) for schema parity.

Usage::

    python3 scripts/migrations/010_drop_nextval_defaults.py --staging --dry-run
    python3 scripts/migrations/010_drop_nextval_defaults.py --staging
    python3 scripts/migrations/010_drop_nextval_defaults.py --prod --dry-run
    python3 scripts/migrations/010_drop_nextval_defaults.py --prod
"""
from __future__ import annotations

import argparse
import os

import duckdb


VERSION = "010_drop_nextval_defaults"
NOTES = "drop DEFAULT nextval on ingestion_impacts.impact_id and ingestion_manifest.manifest_id (obs-03 Phase 1)"

TARGETS = (
    ("ingestion_impacts", "impact_id"),
    ("ingestion_manifest", "manifest_id"),
)


def _column_default(con, table: str, column: str):
    row = con.execute(
        "SELECT column_default FROM duckdb_columns() "
        "WHERE table_name = ? AND column_name = ?",
        [table, column],
    ).fetchone()
    if not row:
        return None
    return row[0]


def _has_table(con, name: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM duckdb_tables() WHERE table_name = ?", [name]
    ).fetchone()
    return row is not None


def _indexes_on(con, table: str):
    """Return [(index_name, create_sql), ...] for all indexes on `table`.

    DuckDB refuses ``ALTER COLUMN DROP DEFAULT`` while any index exists
    on the table (duckdb#17348). We drop them, ALTER, then recreate
    from the stored CREATE INDEX text.
    """
    rows = con.execute(
        "SELECT index_name, sql FROM duckdb_indexes() "
        "WHERE table_name = ? AND sql IS NOT NULL",
        [table],
    ).fetchall()
    return [(r[0], r[1]) for r in rows]


def _already_stamped(con, version: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM schema_versions WHERE version = ?", [version]
    ).fetchone()
    return row is not None


def run_migration(db_path: str, dry_run: bool) -> None:
    """Apply migration 010 to `db_path`. --dry-run reports only."""
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

        before = {
            (t, c): _column_default(con, t, c) for t, c in TARGETS
        }
        stamped = _already_stamped(con, VERSION)
        for (t, c), d in before.items():
            print(f"  {t}.{c} default BEFORE: {d!r}")
        print(f"  schema_versions stamped: {stamped}")

        needs_drop = [(t, c) for (t, c), d in before.items() if d]
        if not needs_drop and stamped:
            print("  ALREADY APPLIED: no action")
            return

        affected_tables = sorted({t for t, _ in needs_drop})
        indexes_by_table = {
            t: _indexes_on(con, t) for t in affected_tables
        }
        for t, idxs in indexes_by_table.items():
            print(f"  {t} has {len(idxs)} index(es) to drop+recreate")

        if dry_run:
            for t in affected_tables:
                for idx_name, _ in indexes_by_table[t]:
                    print(f"    DROP INDEX {idx_name}")
            for t, c in needs_drop:
                print(f"    ALTER TABLE {t} ALTER COLUMN {c} DROP DEFAULT")
            for t in affected_tables:
                for idx_name, _ in indexes_by_table[t]:
                    print(f"    RECREATE INDEX {idx_name}")
            if not stamped:
                print(f"    INSERT schema_versions: {VERSION}")
            print("  DRY-RUN: no writes performed")
            return

        for t in affected_tables:
            for idx_name, _ in indexes_by_table[t]:
                con.execute(f"DROP INDEX {idx_name}")  # nosec B608
                print(f"    DROP INDEX {idx_name}")

        for t, c in needs_drop:
            con.execute(
                f"ALTER TABLE {t} ALTER COLUMN {c} DROP DEFAULT"  # nosec B608
            )
            print(f"    DROP DEFAULT on {t}.{c}")

        for t in affected_tables:
            for idx_name, idx_sql in indexes_by_table[t]:
                con.execute(idx_sql)
                print(f"    RECREATE INDEX {idx_name}")

        if not stamped:
            con.execute(
                "INSERT INTO schema_versions (version, notes) VALUES (?, ?)",
                [VERSION, NOTES],
            )
            print(f"  stamped schema_versions: {VERSION}")
        con.execute("CHECKPOINT")

        after = {
            (t, c): _column_default(con, t, c) for t, c in TARGETS
        }
        for (t, c), d in after.items():
            print(f"  {t}.{c} default AFTER:  {d!r}")
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
