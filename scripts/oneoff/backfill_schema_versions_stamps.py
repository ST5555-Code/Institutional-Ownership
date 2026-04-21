#!/usr/bin/env python3
"""Backfill missing `schema_versions` stamps across prod + staging DuckDBs.

Phase 1 of remediation item mig-04 (MAJOR-16 / S-02). Phase 0 findings:
`docs/findings/mig-04-p0-findings.md`.

Four migrations never stamped `schema_versions`:
  * 001 pipeline control plane  (pre-003 — excused, but still unstamped)
  * 002 fund_universe strategy  (pre-003 — excused, but still unstamped)
  * 004 summary_by_parent rollup_type  (bug — ran after 003)
  * add_last_refreshed_at  (bug — ran after 003)

One additional cross-DB drift:
  * 005 beneficial_ownership_entity_rollups  — stamped on prod, not staging

For each migration this script:
  1. Probes the DB for DDL that proves the migration ran.
  2. Checks whether `schema_versions` already has the stamp.
  3. If DDL present AND stamp missing, inserts the stamp.
  4. If DDL missing, leaves the stamp alone (the migration has not run).

Idempotent: re-running after the first pass is a no-op.

Usage::

    python3 scripts/oneoff/backfill_schema_versions_stamps.py --prod --dry-run
    python3 scripts/oneoff/backfill_schema_versions_stamps.py --staging --dry-run
    python3 scripts/oneoff/backfill_schema_versions_stamps.py --prod
    python3 scripts/oneoff/backfill_schema_versions_stamps.py --staging
    python3 scripts/oneoff/backfill_schema_versions_stamps.py --both
    python3 scripts/oneoff/backfill_schema_versions_stamps.py --path /abs/path.duckdb
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Callable

import duckdb


BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROD_DB = os.path.join(BASE_DIR, "data", "13f.duckdb")
STAGING_DB = os.path.join(BASE_DIR, "data", "13f_staging.duckdb")


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


Probe = Callable[[duckdb.DuckDBPyConnection], bool]


def _probe_001(con) -> bool:
    return _has_table(con, "ingestion_manifest") and _has_table(con, "ingestion_impacts")


def _probe_002(con) -> bool:
    return _has_column(con, "fund_universe", "strategy_narrative")


def _probe_003(con) -> bool:
    return _has_table(con, "cusip_classifications")


def _probe_004(con) -> bool:
    return _has_column(con, "summary_by_parent", "rollup_type")


def _probe_005(con) -> bool:
    return _has_column(con, "beneficial_ownership_v2", "rollup_entity_id")


def _probe_006(con) -> bool:
    # override_id_seq is a sequence, not a table
    row = con.execute(
        "SELECT 1 FROM duckdb_sequences() WHERE sequence_name = 'override_id_seq'"
    ).fetchone()
    return row is not None


def _probe_007(con) -> bool:
    # NOT NULL on entity_overrides_persistent.new_value was dropped.
    row = con.execute(
        "SELECT is_nullable FROM duckdb_columns() "
        "WHERE table_name = 'entity_overrides_persistent' "
        "AND column_name = 'new_value'"
    ).fetchone()
    return bool(row) and bool(row[0])


def _probe_008(con) -> bool:
    # pct_of_float renamed to pct_of_so on holdings_v2
    return _has_column(con, "holdings_v2", "pct_of_so")


def _probe_009(con) -> bool:
    return _has_table(con, "admin_sessions")


def _probe_010(con) -> bool:
    # DEFAULT nextval dropped on ingestion_impacts.impact_id
    row = con.execute(
        "SELECT column_default FROM duckdb_columns() "
        "WHERE table_name = 'ingestion_impacts' "
        "AND column_name = 'impact_id'"
    ).fetchone()
    if not row:
        return False
    return row[0] is None or "nextval" not in str(row[0]).lower()


def _probe_add_last_refreshed_at(con) -> bool:
    return _has_column(con, "entity_relationships", "last_refreshed_at")


# Ordered list: (version, probe, notes). The notes string mirrors the
# self-stamp NOTES used by the migration script itself, with a
# "(backfill)" suffix for migrations whose script never stamped.
MIGRATIONS: list[tuple[str, Probe, str]] = [
    ("001_pipeline_control_plane",
     _probe_001,
     "L0 pipeline control plane (backfill)"),
    ("002_fund_universe_strategy",
     _probe_002,
     "fund_universe strategy narrative columns (backfill)"),
    ("003_cusip_classifications",
     _probe_003,
     "CUSIP & ticker classification layer"),
    ("004_summary_by_parent_rollup_type",
     _probe_004,
     "summary_by_parent rollup_type column + compound PK (backfill)"),
    ("005_beneficial_ownership_entity_rollups",
     _probe_005,
     "13D/G entity rollup columns on beneficial_ownership_v2"),
    ("006_override_id_sequence",
     _probe_006,
     "override_id sequence + DEFAULT nextval + NOT NULL constraint"),
    ("007_override_new_value_nullable",
     _probe_007,
     "drop NOT NULL on entity_overrides_persistent.new_value"),
    ("008_rename_pct_of_float_to_pct_of_so",
     _probe_008,
     "holdings_v2 pct_of_float -> pct_of_so rename + pct_of_so_source audit column"),
    ("009_admin_sessions",
     _probe_009,
     "admin_sessions table (sec-01 Phase 1 server-side session storage)"),
    ("010_drop_nextval_defaults",
     _probe_010,
     "drop DEFAULT nextval on ingestion_impacts.impact_id and "
     "ingestion_manifest.manifest_id (obs-03 Phase 1)"),
    ("add_last_refreshed_at",
     _probe_add_last_refreshed_at,
     "entity_relationships.last_refreshed_at column + backfill (backfill)"),
]


def _is_stamped(con, version: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM schema_versions WHERE version = ?", [version]
    ).fetchone()
    return row is not None


def backfill(db_path: str, label: str, dry_run: bool) -> int:
    """Backfill missing stamps on one DB. Returns count of stamps inserted
    (or that would be inserted under --dry-run)."""
    if not os.path.exists(db_path):
        print(f"[{label}] SKIP: {db_path} does not exist")
        return 0

    con = duckdb.connect(db_path, read_only=dry_run)
    try:
        print(f"[{label}] DB: {db_path}  dry_run={dry_run}")
        if not _has_table(con, "schema_versions"):
            print(f"[{label}] SKIP: schema_versions table missing "
                  "(pre-003 DB). Run migration 003 first.")
            return 0

        rows_before = con.execute(
            "SELECT COUNT(*) FROM schema_versions"
        ).fetchone()[0]
        print(f"[{label}] schema_versions rows before: {rows_before}")

        inserts: list[tuple[str, str]] = []
        for version, probe, notes in MIGRATIONS:
            stamped = _is_stamped(con, version)
            ddl_present = probe(con)
            if stamped:
                status = "stamped"
            elif not ddl_present:
                status = "DDL absent — not applied, skipping"
            else:
                status = "MISSING — will insert"
                inserts.append((version, notes))
            print(f"[{label}]   {version:<50s}  {status}")

        if not inserts:
            print(f"[{label}] nothing to backfill — DB is clean")
            return 0

        if dry_run:
            print(f"[{label}] DRY-RUN: would insert {len(inserts)} stamp(s):")
            for v, n in inserts:
                print(f"[{label}]   + {v}  :: {n}")
            return len(inserts)

        con.execute("BEGIN")
        try:
            for v, n in inserts:
                con.execute(
                    "INSERT OR IGNORE INTO schema_versions (version, notes) "
                    "VALUES (?, ?)",
                    [v, n],
                )
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        con.execute("CHECKPOINT")

        rows_after = con.execute(
            "SELECT COUNT(*) FROM schema_versions"
        ).fetchone()[0]
        print(f"[{label}] schema_versions rows after:  {rows_after} "
              f"(+{rows_after - rows_before})")
        for v, n in inserts:
            print(f"[{label}]   + {v}  :: {n}")
        return len(inserts)
    finally:
        con.close()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    target = p.add_mutually_exclusive_group()
    target.add_argument("--prod", action="store_true",
                        help="apply to data/13f.duckdb")
    target.add_argument("--staging", action="store_true",
                        help="apply to data/13f_staging.duckdb")
    target.add_argument("--both", action="store_true",
                        help="apply to both prod and staging")
    target.add_argument("--path", default=None,
                        help="explicit DB path")
    p.add_argument("--dry-run", action="store_true",
                   help="report actions; no writes")
    args = p.parse_args()

    if not (args.prod or args.staging or args.both or args.path):
        p.error("specify one of --prod / --staging / --both / --path")

    total = 0
    if args.path:
        total += backfill(args.path, "custom", args.dry_run)
    if args.prod or args.both:
        total += backfill(PROD_DB, "prod", args.dry_run)
    if args.staging or args.both:
        total += backfill(STAGING_DB, "staging", args.dry_run)

    verb = "would insert" if args.dry_run else "inserted"
    print(f"\nTOTAL: {verb} {total} stamp(s)")
    sys.exit(0)


if __name__ == "__main__":
    main()
