#!/usr/bin/env python3
# pylint: disable=invalid-name  # migration files follow NNN_description.py convention
"""Migration 023 — create parent_fund_map precompute table.

Backs the perf-P2 precompute pipeline (``scripts/pipeline/compute_parent_fund_map.py``)
that materializes the per-(rollup_entity_id × series_id × quarter × rollup_type)
parent-to-N-PORT-fund-children mapping previously computed at request time
inside ``queries.holder_momentum._get_fund_children`` via 25 ILIKE patterns
against ``fund_holdings_v2`` per parent.

The bottleneck on the parent path was 728ms / 91% of the 800ms total —
each of 25 top-parents ran ``family_name ILIKE`` against the 14.6M-row
``fund_holdings_v2`` table. Materializing the map collapses that loop to
a single JOIN.

Schema::

    rollup_entity_id  BIGINT  NOT NULL
    rollup_type       VARCHAR NOT NULL    -- 'economic_control_v1' | 'decision_maker_v1'
    series_id         VARCHAR NOT NULL
    quarter           VARCHAR NOT NULL
    fund_name         VARCHAR
    family_name       VARCHAR
    loaded_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    PRIMARY KEY (rollup_entity_id, rollup_type, series_id, quarter)

PK ordering — read path filters on ``(rollup_entity_id, rollup_type)``
first, then JOINs to ``fund_holdings_v2`` on ``(series_id, quarter)``;
PK ordering matches that filter shape.

Idempotent — guarded by ``schema_versions`` stamp and by
``CREATE TABLE IF NOT EXISTS``.

Usage::

    python3 scripts/migrations/023_parent_fund_map.py --dry-run
    python3 scripts/migrations/023_parent_fund_map.py
    python3 scripts/migrations/023_parent_fund_map.py --staging --dry-run
    python3 scripts/migrations/023_parent_fund_map.py --staging
"""
from __future__ import annotations

import argparse
import os

import duckdb


VERSION = "023_parent_fund_map"
NOTES = "create parent_fund_map precompute table for holder_momentum parent path"

TABLE = "parent_fund_map"


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
    rollup_entity_id  BIGINT  NOT NULL,
    rollup_type       VARCHAR NOT NULL,
    series_id         VARCHAR NOT NULL,
    quarter           VARCHAR NOT NULL,
    fund_name         VARCHAR,
    family_name       VARCHAR,
    loaded_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (rollup_entity_id, rollup_type, series_id, quarter)
)
"""


def run_migration(db_path: str, dry_run: bool) -> None:
    """Apply migration 023 to ``db_path``. ``--dry-run`` reports only."""
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
        print(f"Migration 023 applied: {TABLE} ready for compute_parent_fund_map")
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
