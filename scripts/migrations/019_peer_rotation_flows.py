#!/usr/bin/env python3
# pylint: disable=invalid-name  # migration files follow NNN_description.py convention
"""Migration 019 — create peer_rotation_flows precompute table.

Backs the perf-p0-s1 precompute pipeline (``scripts/pipeline/compute_peer_rotation.py``)
that materializes the per-(quarter pair × sector × entity × ticker) net
active flow used by ``queries.get_peer_rotation``. Moves the ad-hoc CTE
out of the request path; Session 2 will rewire ``queries.py`` to read
from this table.

Schema::

    quarter_from   VARCHAR NOT NULL
    quarter_to     VARCHAR NOT NULL
    sector         VARCHAR NOT NULL
    entity         VARCHAR NOT NULL
    entity_type    VARCHAR              -- holdings_v2.entity_type (parent)
                                          or fund_universe.fund_strategy (fund, JOIN'd in PR-4)
    ticker         VARCHAR NOT NULL
    active_flow    DOUBLE
    level          VARCHAR NOT NULL     -- 'parent' | 'fund'
    rollup_type    VARCHAR NOT NULL     -- 'economic_control_v1' | 'decision_maker_v1'
    loaded_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    PRIMARY KEY (quarter_from, quarter_to, sector, entity, ticker, level, rollup_type)

Idempotent — guarded by ``schema_versions`` stamp and by
``CREATE TABLE IF NOT EXISTS``.

Usage::

    python3 scripts/migrations/019_peer_rotation_flows.py --dry-run
    python3 scripts/migrations/019_peer_rotation_flows.py
    python3 scripts/migrations/019_peer_rotation_flows.py --staging --dry-run
    python3 scripts/migrations/019_peer_rotation_flows.py --staging
"""
from __future__ import annotations

import argparse
import os

import duckdb


VERSION = "019_peer_rotation_flows"
NOTES = "create peer_rotation_flows precompute table for get_peer_rotation"

TABLE = "peer_rotation_flows"


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
    quarter_from   VARCHAR NOT NULL,
    quarter_to     VARCHAR NOT NULL,
    sector         VARCHAR NOT NULL,
    entity         VARCHAR NOT NULL,
    entity_type    VARCHAR,
    ticker         VARCHAR NOT NULL,
    active_flow    DOUBLE,
    level          VARCHAR NOT NULL,
    rollup_type    VARCHAR NOT NULL,
    loaded_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (quarter_from, quarter_to, sector, entity, ticker, level, rollup_type)
)
"""


def run_migration(db_path: str, dry_run: bool) -> None:
    """Apply migration 019 to ``db_path``. ``--dry-run`` reports only."""
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
        print(f"Migration 019 applied: {TABLE} ready for compute_peer_rotation")
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
