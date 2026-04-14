#!/usr/bin/env python3
"""Migration 002 — fund_universe strategy narrative columns.

Adds three nullable columns to fund_universe that Session 2+ will populate
from N-1A / N-CSR narrative text (separate enrichment pipeline not yet
built). All three columns NULL on existing rows; no backfill.

- strategy_narrative  — investment objective text (free-form)
- strategy_source     — 'n1a' | 'ncsr' | 'manual' | NULL
- strategy_fetched_at — when strategy_narrative was last populated

Idempotent: DuckDB's ALTER TABLE ... ADD COLUMN IF NOT EXISTS no-ops when
the column exists.

Usage:
  python3 scripts/migrations/002_fund_universe_strategy.py        # prod
  python3 scripts/migrations/002_fund_universe_strategy.py --path data/13f.duckdb
"""
from __future__ import annotations

import argparse
import os

import duckdb


MIGRATION_SQL = [
    # Three nullable columns. DuckDB supports single-column ADD COLUMN
    # per ALTER statement, so one statement each.
    "ALTER TABLE fund_universe ADD COLUMN IF NOT EXISTS strategy_narrative VARCHAR",
    "ALTER TABLE fund_universe ADD COLUMN IF NOT EXISTS strategy_source VARCHAR",
    "ALTER TABLE fund_universe ADD COLUMN IF NOT EXISTS strategy_fetched_at TIMESTAMP",
]


def run_migration(db_path: str) -> None:
    if not os.path.exists(db_path):
        print(f"  SKIP: {db_path} does not exist")
        return
    con = duckdb.connect(db_path)
    try:
        ddl_before = con.execute(
            "SELECT sql FROM duckdb_tables() WHERE table_name='fund_universe'"
        ).fetchone()
        print(f"  DB: {db_path}")
        print("  BEFORE:")
        print(f"    {ddl_before[0] if ddl_before else '(fund_universe missing)'}")
        for stmt in MIGRATION_SQL:
            con.execute(stmt)
        con.execute("CHECKPOINT")
        ddl_after = con.execute(
            "SELECT sql FROM duckdb_tables() WHERE table_name='fund_universe'"
        ).fetchone()
        print("  AFTER:")
        print(f"    {ddl_after[0] if ddl_after else '(fund_universe missing)'}")
    finally:
        con.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", default=None,
                        help="DB path. Defaults to data/13f.duckdb (prod).")
    args = parser.parse_args()
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    db_path = args.path or os.path.join(here, "data", "13f.duckdb")
    run_migration(db_path)


if __name__ == "__main__":
    main()
