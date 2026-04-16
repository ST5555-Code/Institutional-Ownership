#!/usr/bin/env python3
# pylint: disable=invalid-name  # migration files follow NNN_description.py convention
"""Migration 004 — summary_by_parent rollup_type column + compound PK.

Adds a `rollup_type VARCHAR` column to `summary_by_parent` and changes the
primary key from `(quarter, rollup_entity_id)` to
`(quarter, rollup_type, rollup_entity_id)` so both worldviews can coexist.

Existing rows are stamped `rollup_type='economic_control_v1'` (they were
populated from the EC rollup in the pre-rewrite pipeline).

DuckDB can't drop/alter PRIMARY KEY via ALTER, so this script:
  1. Renames existing `summary_by_parent` -> `summary_by_parent_old`.
  2. Creates new `summary_by_parent` with the expanded PK.
  3. INSERTs all rows from _old with `rollup_type='economic_control_v1'`.
  4. DROPs `summary_by_parent_old`.
  5. CHECKPOINTs.

Idempotent: probes for the `rollup_type` column. If present, no-op.

Usage:
  python3 scripts/migrations/004_summary_by_parent_rollup_type.py --path data/13f_staging.duckdb
  python3 scripts/migrations/004_summary_by_parent_rollup_type.py                 # prod default
"""
from __future__ import annotations

import argparse
import os

import duckdb


def _has_rollup_type(con) -> bool:
    """Probe for the `rollup_type` column on summary_by_parent."""
    cols = con.execute(
        "SELECT column_name FROM duckdb_columns() "
        "WHERE table_name = 'summary_by_parent'"
    ).fetchall()
    return any(c[0] == "rollup_type" for c in cols)


def _has_table(con, name: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM duckdb_tables() WHERE table_name = ?",
        [name],
    ).fetchone()
    return row is not None


def run_migration(db_path: str) -> None:
    """Apply the migration to `db_path` if not already applied."""
    if not os.path.exists(db_path):
        print(f"  SKIP: {db_path} does not exist")
        return

    con = duckdb.connect(db_path)
    try:
        if not _has_table(con, "summary_by_parent"):
            print(f"  SKIP ({db_path}): summary_by_parent does not exist")
            return

        if _has_rollup_type(con):
            row_count = con.execute(
                "SELECT COUNT(*) FROM summary_by_parent"
            ).fetchone()[0]
            print(f"  ALREADY APPLIED ({db_path}): rollup_type present, "
                  f"{row_count:,} rows")
            return

        ddl_before = con.execute(
            "SELECT sql FROM duckdb_tables() "
            "WHERE table_name='summary_by_parent'"
        ).fetchone()[0]
        rows_before = con.execute(
            "SELECT COUNT(*) FROM summary_by_parent"
        ).fetchone()[0]
        print(f"  DB: {db_path}")
        print("  BEFORE:")
        print(f"    {ddl_before}")
        print(f"    rows: {rows_before:,}")

        # Clean up any lingering _old from a failed prior attempt so this
        # pass can proceed.
        con.execute("DROP TABLE IF EXISTS summary_by_parent_old")

        con.execute(
            "ALTER TABLE summary_by_parent RENAME TO summary_by_parent_old"
        )
        con.execute("""
            CREATE TABLE summary_by_parent (
                quarter VARCHAR,
                rollup_type VARCHAR,
                rollup_entity_id BIGINT,
                inst_parent_name VARCHAR,
                rollup_name VARCHAR,
                total_aum DOUBLE,
                total_nport_aum DOUBLE,
                nport_coverage_pct DOUBLE,
                ticker_count INTEGER,
                total_shares BIGINT,
                manager_type VARCHAR,
                is_passive BOOLEAN,
                top10_tickers VARCHAR,
                updated_at TIMESTAMP,
                PRIMARY KEY (quarter, rollup_type, rollup_entity_id)
            )
        """)
        con.execute("""
            INSERT INTO summary_by_parent (
                quarter, rollup_type, rollup_entity_id, inst_parent_name,
                rollup_name, total_aum, total_nport_aum, nport_coverage_pct,
                ticker_count, total_shares, manager_type, is_passive,
                top10_tickers, updated_at
            )
            SELECT
                quarter,
                'economic_control_v1' AS rollup_type,
                rollup_entity_id,
                inst_parent_name,
                rollup_name,
                total_aum,
                total_nport_aum,
                nport_coverage_pct,
                ticker_count,
                total_shares,
                manager_type,
                is_passive,
                top10_tickers,
                updated_at
            FROM summary_by_parent_old
        """)
        con.execute("DROP TABLE summary_by_parent_old")
        con.execute("CHECKPOINT")

        rows_after = con.execute(
            "SELECT COUNT(*) FROM summary_by_parent"
        ).fetchone()[0]
        ddl_after = con.execute(
            "SELECT sql FROM duckdb_tables() "
            "WHERE table_name='summary_by_parent'"
        ).fetchone()[0]
        print("  AFTER:")
        print(f"    {ddl_after}")
        print(f"    rows: {rows_after:,} (stamped rollup_type='economic_control_v1')")

        if rows_before != rows_after:
            raise SystemExit(
                f"  MIGRATION FAILED: row count mismatch "
                f"({rows_before} before, {rows_after} after)"
            )
    finally:
        con.close()


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", default=None,
                        help="DB path. Defaults to data/13f.duckdb (prod).")
    args = parser.parse_args()
    here = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    db_path = args.path or os.path.join(here, "data", "13f.duckdb")
    run_migration(db_path)


if __name__ == "__main__":
    main()
