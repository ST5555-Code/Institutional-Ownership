#!/usr/bin/env python3
# pylint: disable=invalid-name  # migration files follow NNN_description.py convention
"""Migration 024 — drop denormalized rollup columns from ``fund_holdings_v2``.

Gap 2 from cp-5-bundle-c-discovery §7.5 (PR #289). Removes two columns
that were populated as a denormalized cache of the DM rollup at load time:

* ``fund_holdings_v2.dm_rollup_entity_id``
* ``fund_holdings_v2.dm_rollup_name``

Rationale: chat decision 2026-05-05 chose Path 1 (drop). Method A
read-time ``entity_rollup_history`` JOIN is canonical per PR #280. As of
the recon (PR #288) 188K rows / 1.30% carried drift; 63% confirmed STALE.
Dropping eliminates drift permanently.

Additional: ``dm_rollup_name`` had a semantic defect (writer joined
``entity_aliases`` on the EC rollup entity instead of the DM rollup
entity); this defect retires with the column at no extra cost.

All 6 production reader sites have been migrated to Method A inline JOIN
in this PR (scripts/queries/cross.py, scripts/build_summaries.py,
scripts/build_fixture.py). Writer sites (load_nport.py,
enrich_fund_holdings_v2.py) have had the SET clauses removed.

DDL applied::

    ALTER TABLE fund_holdings_v2 DROP COLUMN dm_rollup_entity_id;
    ALTER TABLE fund_holdings_v2 DROP COLUMN dm_rollup_name;

Idempotent: each column is checked before dropping. Re-run on an
already-migrated DB is a no-op.

Rollback path: re-add columns + run
``python3 scripts/enrich_fund_holdings_v2.py --apply`` (idempotent,
~minutes for full table). Not expected; forward-only per standard policy.

Usage::

    python3 scripts/migrations/024_drop_fh2_dm_rollup_denorm.py --dry-run
    python3 scripts/migrations/024_drop_fh2_dm_rollup_denorm.py --prod
    python3 scripts/migrations/024_drop_fh2_dm_rollup_denorm.py --staging
"""
from __future__ import annotations

import argparse
import os

import duckdb


VERSION = "024_drop_fh2_dm_rollup_denorm"
NOTES = (
    "drop fund_holdings_v2.dm_rollup_entity_id and dm_rollup_name "
    "(denormalized DM rollup cache — replaced by Method A ERH JOIN, "
    "CP-5 Gap 2, PR #289)"
)

TARGETS = (
    ("fund_holdings_v2", "dm_rollup_entity_id"),
    ("fund_holdings_v2", "dm_rollup_name"),
)

# DuckDB DROP COLUMN fails if any index exists on a column positioned
# after the one being dropped.  Drop all fhv2 indexes, drop the columns,
# then recreate.  The CREATE INDEX statements below restore the full
# index set exactly.
_DROP_INDEXES = [
    "DROP INDEX IF EXISTS idx_fhv2_entity",
    "DROP INDEX IF EXISTS idx_fhv2_rollup",
    "DROP INDEX IF EXISTS idx_fhv2_series",
    "DROP INDEX IF EXISTS idx_fh_v2_accession",
    "DROP INDEX IF EXISTS idx_fh_v2_latest",
    "DROP INDEX IF EXISTS idx_fund_holdings_v2_row_id",
]

_RECREATE_INDEXES = [
    "CREATE INDEX idx_fhv2_entity ON fund_holdings_v2(entity_id)",
    "CREATE INDEX idx_fhv2_rollup ON fund_holdings_v2(rollup_entity_id, \"quarter\")",
    "CREATE INDEX idx_fhv2_series ON fund_holdings_v2(series_id, \"quarter\")",
    "CREATE INDEX idx_fh_v2_accession ON fund_holdings_v2(accession_number)",
    "CREATE INDEX idx_fh_v2_latest ON fund_holdings_v2(is_latest, report_month)",
    "CREATE UNIQUE INDEX idx_fund_holdings_v2_row_id ON fund_holdings_v2(row_id)",
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
    """Apply migration 024 to `db_path`. --dry-run reports only."""
    if not os.path.exists(db_path):
        print(f"  SKIP: {db_path} does not exist")
        return

    con = duckdb.connect(db_path, read_only=dry_run)
    try:
        print(f"  DB: {db_path}")
        print(f"  dry_run: {dry_run}")

        if not _has_table(con, "fund_holdings_v2"):
            raise SystemExit(
                "  MIGRATION FAILED: fund_holdings_v2 missing in "
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
            "SELECT COUNT(*) FROM fund_holdings_v2"
        ).fetchone()[0]
        print(f"  fund_holdings_v2 row count: {row_count:,}")
        print(f"  schema_versions stamped: {stamped}")

        if not present and stamped:
            print("  ALREADY APPLIED: no action")
            return

        if dry_run:
            print("  Would execute:")
            for stmt in _DROP_INDEXES:
                print(f"    {stmt}")
            for t, c in present:
                print(f"    ALTER TABLE {t} DROP COLUMN {c}")
            for stmt in _RECREATE_INDEXES:
                print(f"    {stmt}")
            if not stamped:
                print(f"    INSERT schema_versions: {VERSION}")
            print("  DRY-RUN: no writes performed")
            return

        print("  Dropping indexes before column removal …")
        for stmt in _DROP_INDEXES:
            con.execute(stmt)
            print(f"    {stmt}")

        dropped = 0
        for t, c in present:
            con.execute(f"ALTER TABLE {t} DROP COLUMN {c}")  # nosec B608
            print(f"    DROP COLUMN {t}.{c}")
            dropped += 1

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
            "SELECT COUNT(*) FROM fund_holdings_v2"
        ).fetchone()[0]
        print(f"  fund_holdings_v2 row count after: {post_count:,}")
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
