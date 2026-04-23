#!/usr/bin/env python3
"""
sync_staging.py — copy entity tables from production → staging.

Run at the start of every entity-edit session. Overwrites staging
entity tables completely so the editor starts from a known-clean
mirror of production. Reference data tables (holdings, securities,
market_data, etc.) are NOT touched — they're managed separately by
db.seed_staging() and merge_staging.py.

Usage:
  python3 scripts/sync_staging.py                       # full sync
  python3 scripts/sync_staging.py --dry-run             # report row counts only
  python3 scripts/sync_staging.py --tables entities,entity_relationships
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import db  # noqa: E402

LOG_PATH = ROOT / "logs" / "staging_sync.log"


def _ensure_log_dir() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)


def _log(msg: str) -> None:
    _ensure_log_dir()
    ts = datetime.now().isoformat(timespec="seconds")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _ensure_staging_schema(con) -> None:
    """Make sure entity tables exist in staging by running entity_schema.sql."""
    schema_path = ROOT / "scripts" / "entity_schema.sql"
    if not schema_path.exists():
        raise RuntimeError(f"entity_schema.sql not found at {schema_path}")
    sql = schema_path.read_text()
    con.execute(sql)


def _row_count(con, qualified: str) -> int:
    try:
        return con.execute(f"SELECT COUNT(*) FROM {qualified}").fetchone()[0]
    except Exception:
        return -1


# Column-default pattern inside a prod DDL emitted by duckdb_tables().sql:
#   `override_id BIGINT DEFAULT(nextval('override_id_seq')) NOT NULL,`
# Capture group 1 = column name, group 2 = sequence name. Used to prime
# staging sequences to MAX(col)+1 from prod BEFORE recreating the table,
# because once the table exists its DEFAULT clause creates a dependency
# that blocks DROP / CREATE OR REPLACE on the referenced sequence.
_SEQ_DEFAULT_RE = re.compile(
    r"\b([A-Za-z_][A-Za-z0-9_]*)\s+[A-Za-z_][A-Za-z0-9_]*"
    r"\s+DEFAULT\(nextval\('([A-Za-z_][A-Za-z0-9_]*)'\)\)"
)


def _prod_table_ddl(con, table: str) -> str | None:
    """Return the DDL DuckDB records for `table` in the attached prod DB.

    None if the table is not present in prod. The returned statement is a
    bare `CREATE TABLE name(...)` — unqualified, so executing it against
    the staging connection creates the table in staging's default schema.
    """
    row = con.execute(
        "SELECT sql FROM duckdb_tables() "
        "WHERE database_name = 'prod' AND table_name = ?",
        [table],
    ).fetchone()
    return row[0] if row else None


def _plan_sequence_starts(con, ddls: dict[str, str]) -> dict[str, int]:
    """Compute MAX(col)+1 from prod for every sequence about to be used.

    Two sources of (sequence, table, column) tuples:
      1. DEFAULT(nextval('x')) clauses inside each rebuilt table's prod DDL.
      2. db.ENTITY_SEQUENCES for tables being rebuilt — catches sequences
         app code uses without a DEFAULT (e.g. identifier_staging_id_seq
         lives in the DDL of entity_relationships_staging but is also
         populated by build_entities.py for entity_identifiers_staging).
    For each sequence, take the MAX across all referenced (table, col)
    pairs so the new start value is safe no matter which table is
    inserted into next.
    """
    plan: dict[str, int] = {}

    def bump(seq: str, candidate: int) -> None:
        if seq not in plan or candidate > plan[seq]:
            plan[seq] = candidate

    for table, ddl in ddls.items():
        if ddl is None:
            continue
        for col, seq in _SEQ_DEFAULT_RE.findall(ddl):
            row = con.execute(
                f"SELECT COALESCE(MAX({col}), 0) + 1 FROM prod.{table}"
            ).fetchone()
            bump(seq, int(row[0]) if row and row[0] is not None else 1)

    for seq, tgt_table, col in db.ENTITY_SEQUENCES:
        if tgt_table not in ddls:
            continue
        row = con.execute(
            f"SELECT COALESCE(MAX({col}), 0) + 1 FROM prod.{tgt_table}"
        ).fetchone()
        bump(seq, int(row[0]) if row and row[0] is not None else 1)

    return plan


def sync(tables: list[str], dry_run: bool) -> dict:
    import duckdb

    if not os.path.exists(db.PROD_DB):
        raise RuntimeError(f"Production DB not found: {db.PROD_DB}")

    os.makedirs(os.path.dirname(db.STAGING_DB), exist_ok=True)

    # Open staging RW; ATTACH prod read-only as 'prod' so we can copy
    # via SQL without round-tripping data through Python.
    #
    # We do NOT apply entity_schema.sql to either side:
    #   - Prod has a legacy degraded schema (constraint-free entities table)
    #     so re-running CREATE TABLE statements would fail FK validation
    #     against the constraint-free parent.
    #   - Staging inherits prod's exact schema via the per-table DDL copy
    #     below, so applying entity_schema.sql on top would clash with
    #     whatever constraints prod does or does not have.
    # Staging gets each entity table by fetching prod's recorded DDL from
    # duckdb_tables(), executing it on staging, then INSERT-SELECTing rows
    # from prod. This preserves DEFAULT clauses and NOT NULL constraints
    # that CTAS silently drops (INF40, 2026-04-23).
    stg = duckdb.connect(db.STAGING_DB)
    stg.execute(f"ATTACH '{db.PROD_DB}' AS prod (READ_ONLY)")

    try:

        # Drop tables from the sync list that don't exist in prod —
        # they'll stay empty in staging (still present, just zero rows).
        # entity_overrides_persistent is the canonical example: declared
        # in entity_schema.sql but never created in prod.
        # DuckDB does replacement-scan on bare identifiers that match local
        # Python names — filter duckdb_tables() by database_name to query
        # the attached prod DB without naming the bare 'tables' identifier.
        prod_tables = {
            r[0] for r in stg.execute(
                "SELECT table_name FROM duckdb_tables() WHERE database_name = 'prod'"
            ).fetchall()
        }
        skipped = [t for t in tables if t not in prod_tables]
        if skipped:
            for t in skipped:
                _log(f"  SKIP {t}: not present in prod (staging copy left empty)")
            tables = [t for t in tables if t in prod_tables]

        report = {"tables": {}, "started_at": datetime.now().isoformat(timespec="seconds")}

        if dry_run:
            for table in tables:
                prod_n = _row_count(stg, f"prod.{table}")
                stg_n = _row_count(stg, table)
                report["tables"][table] = {
                    "prod_rows": prod_n,
                    "staging_rows_before": stg_n,
                    "would_copy": prod_n,
                }
                _log(f"  [DRY-RUN] {table}: prod={prod_n} staging={stg_n}")
        else:
            # DDL-first strategy (INF40, 2026-04-23): for each entity
            # table, fetch prod's recorded DDL via duckdb_tables().sql,
            # apply it to staging, then INSERT rows. The previous CTAS
            # path (`CREATE TABLE x AS SELECT * FROM prod.x`) silently
            # stripped DEFAULT clauses and NOT NULL constraints — see
            # e.g. entity_overrides_persistent.override_id which has
            # `DEFAULT(nextval('override_id_seq')) NOT NULL` on prod but
            # landed as a bare `BIGINT` on staging. That mismatch blocked
            # `build_entities.py --reset` idempotency validation because
            # application code relies on the DEFAULT to assign IDs.
            #
            # INF11 fix (2026-04-10, carried forward): drop only the
            # tables we are about to rebuild, so partial syncs preserve
            # in-progress edits on other entity tables.
            # Fetch all prod DDLs up front so we can compute the
            # sequence plan before touching staging tables.
            ddls = {t: _prod_table_ddl(stg, t) for t in tables}

            stg.execute("DROP VIEW IF EXISTS entity_current")
            for table in reversed(tables):
                stg.execute(f"DROP TABLE IF EXISTS {table}")

            # Prime sequences BEFORE recreating tables: once a table
            # exists with a DEFAULT(nextval('x')) clause, DuckDB refuses
            # to DROP or CREATE OR REPLACE the referenced sequence. At
            # this point all rebuilt tables are dropped, so any sequence
            # whose only dependents were in `tables` is free.
            seq_plan = _plan_sequence_starts(stg, ddls)
            for seq, next_val in seq_plan.items():
                stg.execute(f"CREATE OR REPLACE SEQUENCE {seq} START {next_val}")
                _log(f"  sequence {seq} primed to {next_val}")
            report["sequences"] = dict(seq_plan)

            for table in tables:
                ddl = ddls.get(table)
                if ddl is None:
                    # Shouldn't reach here — tables missing from prod
                    # were filtered out above.
                    _log(f"  ! {table}: missing DDL in prod, skipping")
                    continue
                stg.execute(ddl)
                stg.execute(
                    f"INSERT INTO {table} SELECT * FROM prod.{table}"
                )
                prod_n = _row_count(stg, f"prod.{table}")
                stg_n = _row_count(stg, table)
                report["tables"][table] = {
                    "prod_rows": prod_n,
                    "staging_rows_after": stg_n,
                    "match": stg_n == prod_n,
                }
                marker = "✓" if stg_n == prod_n else "✗"
                _log(f"  {marker} {table}: copied {stg_n} rows (prod={prod_n})")

        # Sequences were primed inline per-table above — once the DDL
        # creates a DEFAULT(nextval('x')) dependency on a sequence, the
        # sequence cannot be dropped, so the old post-copy DROP+CREATE
        # approach no longer works. Sequences without a DEFAULT reference
        # in any rebuilt table (e.g. a sequence whose table lives outside
        # ENTITY_TABLES) are left untouched — the partial-sync contract
        # says only rebuilt tables should see side effects.
        report["finished_at"] = datetime.now().isoformat(timespec="seconds")
        return report

    finally:
        stg.execute("DETACH prod")
        stg.close()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true",
                   help="report row counts only; do not modify staging")
    p.add_argument("--tables", default=None,
                   help="comma-separated subset of entity tables (default: all)")
    args = p.parse_args()

    if args.tables:
        requested = [t.strip() for t in args.tables.split(",") if t.strip()]
        invalid = [t for t in requested if t not in db.ENTITY_TABLES]
        if invalid:
            print(f"ERROR: unknown entity tables: {invalid}", file=sys.stderr)
            print(f"Known: {db.ENTITY_TABLES}", file=sys.stderr)
            sys.exit(2)
        tables = requested
    else:
        tables = list(db.ENTITY_TABLES)

    mode = "DRY-RUN" if args.dry_run else "SYNC"
    if args.tables and not args.dry_run:
        untouched = [t for t in db.ENTITY_TABLES if t not in tables]
        if untouched:
            _log(
                f"  PARTIAL SYNC — only dropping+re-copying {len(tables)} "
                f"tables: {tables}"
            )
            _log(
                f"  UNTOUCHED (staging edits preserved): {untouched}"
            )
    _log(f"=== {mode} START — tables={len(tables)} ===")
    _log(f"  prod    = {db.PROD_DB}")
    _log(f"  staging = {db.STAGING_DB}")

    try:
        report = sync(tables, args.dry_run)
    except Exception as e:
        _log(f"  FAILED: {e}")
        raise

    mismatches = [
        t for t, r in report["tables"].items()
        if not args.dry_run and not r.get("match", True)
    ]
    if mismatches:
        _log(f"  WARN: row-count mismatch on {mismatches}")
        sys.exit(1)
    _log(f"=== {mode} DONE ===")


if __name__ == "__main__":
    main()
