#!/usr/bin/env python3
# pylint: disable=invalid-name  # migration files follow NNN_description.py convention
"""Migration 021 — create sector_flows_rollup precompute table.

Backs the perf-P1 precompute pipeline (``scripts/pipeline/compute_sector_flows.py``)
that materializes the per-(quarter pair × level × rollup_type × active_only ×
sector) flow aggregate previously computed at request time by
``queries.get_sector_flows``. Scope is small (~351 rows on the current
prod corpus); the perf win is in moving an ~1.2s scan of ``holdings_v2`` /
``fund_holdings_v2`` out of the request path. Target post-rewrite latency
for ``get_sector_flows``: <50ms.

Schema::

    quarter_from   VARCHAR NOT NULL
    quarter_to     VARCHAR NOT NULL
    level          VARCHAR NOT NULL    -- 'parent' | 'fund'
    rollup_type    VARCHAR NOT NULL    -- 'economic_control_v1' | 'decision_maker_v1'
    active_only    BOOLEAN NOT NULL    -- entity_type filter applied to parent path
    gics_sector    VARCHAR NOT NULL    -- includes 'Derivative' / 'ETF' / etc.;
                                          read-side filters at query time
    net            DOUBLE
    inflow         DOUBLE
    outflow        DOUBLE
    new_positions  BIGINT
    exits          BIGINT
    managers       BIGINT
    loaded_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    PRIMARY KEY (quarter_from, quarter_to, level, rollup_type, active_only, gics_sector)

PK note — the perf-P1 scoping doc lists the PK as
``(quarter, rollup_type, gics_sector)``. Three columns are insufficient
to disambiguate rows: ``level`` distinguishes parent vs fund, and
``active_only`` distinguishes the two parent variants the API surfaces.
``quarter`` is split into ``(quarter_from, quarter_to)`` to mirror
``peer_rotation_flows`` and keep the join shape uniform across the two
P1 tables. Fund rows always carry ``active_only = FALSE`` (the active
filter is a no-op on the fund path).

Idempotent — guarded by ``schema_versions`` stamp and by
``CREATE TABLE IF NOT EXISTS``.

Usage::

    python3 scripts/migrations/021_sector_flows_rollup.py --dry-run
    python3 scripts/migrations/021_sector_flows_rollup.py
    python3 scripts/migrations/021_sector_flows_rollup.py --staging --dry-run
    python3 scripts/migrations/021_sector_flows_rollup.py --staging
"""
from __future__ import annotations

import argparse
import os

import duckdb


VERSION = "021_sector_flows_rollup"
NOTES = "create sector_flows_rollup precompute table for get_sector_flows"

TABLE = "sector_flows_rollup"


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
    level          VARCHAR NOT NULL,
    rollup_type    VARCHAR NOT NULL,
    active_only    BOOLEAN NOT NULL,
    gics_sector    VARCHAR NOT NULL,
    net            DOUBLE,
    inflow         DOUBLE,
    outflow        DOUBLE,
    new_positions  BIGINT,
    exits          BIGINT,
    managers       BIGINT,
    loaded_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (quarter_from, quarter_to, level, rollup_type, active_only, gics_sector)
)
"""


def run_migration(db_path: str, dry_run: bool) -> None:
    """Apply migration 021 to ``db_path``. ``--dry-run`` reports only."""
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
        print(f"Migration 021 applied: {TABLE} ready for compute_sector_flows")
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
