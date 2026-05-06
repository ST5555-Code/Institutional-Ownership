#!/usr/bin/env python3
# pylint: disable=invalid-name  # migration files follow NNN_description.py convention
"""Migration 025 — drop denormalized rollup columns from ``holdings_v2``.

Sister-table follow-on to migration 024 (PR #289 fh2 drop). Removes two
columns that were populated as a denormalized cache of the DM rollup at
historical backfill time:

* ``holdings_v2.dm_rollup_entity_id``
* ``holdings_v2.dm_rollup_name``

Rationale: chat decision 2026-05-05 chose Path 1 (drop). Method A
read-time ``entity_rollup_history`` JOIN is canonical per PR #280. As of
PR #295 sister-table recon, 147,500 rows / 1.20% carried drift; absolute
top-parent AUM drift summed to ~$8.16T across 42 parents. Live loader
inserts NULL for both columns (``scripts/load_13f_v2.py``); no live
UPDATE writer was identified — the columns drift monotonically with each
new entity merge. Dropping eliminates drift permanently.

All 16 production reader sites in ``scripts/queries/`` plus 5 pipeline
recomputers (``scripts/compute_flows.py``,
``scripts/build_summaries.py``, ``scripts/pipeline/compute_peer_rotation.py``,
``scripts/pipeline/compute_parent_fund_map.py``, and the
``scripts/build_fixture.py`` seed UNION) have been migrated to Method A
inline JOIN in this PR. Writer sites (``scripts/load_13f_v2.py`` DDL +
INSERT column list + NULL SELECT) have been retired.

Mechanism: ``ALTER TABLE ... DROP COLUMN`` cannot be used here because
``holdings_v2`` carries a ``PRIMARY KEY`` constraint on ``row_id`` (col
33) — DuckDB rejects DROP COLUMN when any index (including the implicit
PK index) sits on a column positioned after the dropped column, and
DuckDB does not support ``ALTER TABLE DROP CONSTRAINT``.

Instead the migration rebuilds the table via ``CREATE TABLE ... AS
SELECT * EXCLUDE (...)``, atomically swaps it in, and re-applies the
PRIMARY KEY constraint plus all six indexes. Row count is asserted
identical pre/post.

Idempotent: each column is checked before dropping. Re-run on an
already-migrated DB is a no-op. Forward-only per standard policy.

Usage::

    python3 scripts/migrations/025_drop_holdings_v2_dm_rollup_denorm.py --dry-run
    python3 scripts/migrations/025_drop_holdings_v2_dm_rollup_denorm.py --prod
    python3 scripts/migrations/025_drop_holdings_v2_dm_rollup_denorm.py --staging
"""
from __future__ import annotations

import argparse
import os

import duckdb


VERSION = "025_drop_holdings_v2_dm_rollup_denorm"
NOTES = (
    "drop holdings_v2.dm_rollup_entity_id and dm_rollup_name "
    "(denormalized DM rollup cache — replaced by Method A ERH JOIN, "
    "CP-5 sister-table follow-on, PR #295 drop PR)"
)

TARGETS = (
    ("holdings_v2", "dm_rollup_entity_id"),
    ("holdings_v2", "dm_rollup_name"),
)

# DuckDB DROP COLUMN fails if any index exists on a column positioned
# after the one being dropped. Drop all hv2 indexes, drop the columns,
# then recreate. ``holdings_v2`` also carries a PRIMARY KEY on
# ``row_id`` — the implicit PK index causes the same error, so the
# constraint is dropped and rebuilt as well.  The CREATE INDEX +
# ALTER TABLE ADD CONSTRAINT statements below restore the full
# index/constraint set exactly as observed pre-migration.
_DROP_INDEXES = [
    "DROP INDEX IF EXISTS idx_holdings_v2_latest",
    "DROP INDEX IF EXISTS idx_holdings_v2_row_id",
    "DROP INDEX IF EXISTS idx_hv2_cik_quarter",
    "DROP INDEX IF EXISTS idx_hv2_entity_id",
    "DROP INDEX IF EXISTS idx_hv2_rollup",
    "DROP INDEX IF EXISTS idx_hv2_ticker_quarter",
]

_ADD_CONSTRAINT = (
    "ALTER TABLE holdings_v2 ADD CONSTRAINT holdings_v2_row_id_pkey "
    "PRIMARY KEY (row_id)"
)

_RECREATE_INDEXES = [
    "CREATE INDEX idx_holdings_v2_latest ON holdings_v2(is_latest, \"quarter\")",
    "CREATE UNIQUE INDEX idx_holdings_v2_row_id ON holdings_v2(row_id)",
    "CREATE INDEX idx_hv2_cik_quarter ON holdings_v2(cik, \"quarter\")",
    "CREATE INDEX idx_hv2_entity_id ON holdings_v2(entity_id)",
    "CREATE INDEX idx_hv2_rollup ON holdings_v2(rollup_entity_id, \"quarter\")",
    "CREATE INDEX idx_hv2_ticker_quarter ON holdings_v2(ticker, \"quarter\")",
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
    """Apply migration 025 to `db_path`. --dry-run reports only."""
    if not os.path.exists(db_path):
        print(f"  SKIP: {db_path} does not exist")
        return

    con = duckdb.connect(db_path, read_only=dry_run)
    try:
        print(f"  DB: {db_path}")
        print(f"  dry_run: {dry_run}")

        if not _has_table(con, "holdings_v2"):
            raise SystemExit(
                "  MIGRATION FAILED: holdings_v2 missing in "
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
            "SELECT COUNT(*) FROM holdings_v2"
        ).fetchone()[0]
        print(f"  holdings_v2 row count: {row_count:,}")
        print(f"  schema_versions stamped: {stamped}")

        if not present and stamped:
            print("  ALREADY APPLIED: no action")
            return

        # CTAS-and-swap: build holdings_v2_new from SELECT * EXCLUDE,
        # then DROP old + RENAME new + restore PK + indexes.
        ctas_sql = (
            "CREATE TABLE holdings_v2_new AS "
            "SELECT * EXCLUDE (dm_rollup_entity_id, dm_rollup_name) "
            "FROM holdings_v2"
        )

        if dry_run:
            print("  Would execute:")
            for stmt in _DROP_INDEXES:
                print(f"    {stmt}")
            print(f"    {ctas_sql}")
            print("    DROP TABLE holdings_v2")
            print("    ALTER TABLE holdings_v2_new RENAME TO holdings_v2")
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

        print("  Cleaning up any prior holdings_v2_new …")
        con.execute("DROP TABLE IF EXISTS holdings_v2_new")

        print("  Building holdings_v2_new (SELECT * EXCLUDE …) …")
        con.execute(ctas_sql)
        new_count = con.execute(
            "SELECT COUNT(*) FROM holdings_v2_new"
        ).fetchone()[0]
        print(f"    holdings_v2_new row count: {new_count:,}")
        if new_count != row_count:
            raise SystemExit(
                "  CTAS COUNT MISMATCH: "
                f"{row_count:,} → {new_count:,}"
            )

        print("  Swapping tables …")
        con.execute("DROP TABLE holdings_v2")
        con.execute("ALTER TABLE holdings_v2_new RENAME TO holdings_v2")

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
            "SELECT COUNT(*) FROM holdings_v2"
        ).fetchone()[0]
        print(f"  holdings_v2 row count after: {post_count:,}")
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
