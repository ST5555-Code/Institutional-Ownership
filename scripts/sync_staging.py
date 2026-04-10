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


def _reset_sequences(con) -> dict:
    """Set each entity sequence to MAX(id)+1 of its target table.

    DuckDB does not implement ALTER SEQUENCE ... RESTART WITH N, so we
    DROP and CREATE the sequence at the desired starting value. This is
    safe in staging because CTAS-created tables do not carry the
    `DEFAULT nextval(...)` clauses from the original schema; the
    sequences are only used by application code that calls nextval()
    explicitly.
    """
    out = {}
    for seq, table, col in db.ENTITY_SEQUENCES:
        try:
            row = con.execute(
                f"SELECT COALESCE(MAX({col}), 0) + 1 FROM {table}"
            ).fetchone()
            next_val = int(row[0]) if row and row[0] is not None else 1
            con.execute(f"DROP SEQUENCE IF EXISTS {seq}")
            con.execute(f"CREATE SEQUENCE {seq} START WITH {next_val}")
            out[seq] = next_val
        except Exception as e:
            out[seq] = f"ERROR: {e}"
    return out


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
    #   - Staging will be CTAS'd from prod below, inheriting prod's degraded
    #     schema, so the same FK-validation failure would block any
    #     subsequent _ensure_staging_schema call after the first sync run.
    # Staging gets its tables purely via CREATE TABLE AS SELECT from prod —
    # see the CTAS block below.
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

        # Strategy: DROP + recreate. DuckDB has a quirk where DELETE on a
        # parent table inside a transaction does not see in-transaction
        # child-table deletes when checking FK constraints, so the more
        # natural "DELETE children, DELETE parent, INSERT all" pattern
        # fails on the parent DELETE. DROP TABLE bypasses FK enforcement
        # entirely. We then re-apply entity_schema.sql to recreate every
        # entity table with constraints intact, and INSERT from prod.

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
            # CTAS strategy: drop staging entity tables and re-create them
            # via CREATE TABLE AS SELECT from prod. This makes staging's
            # schema structurally identical to prod's (including degraded
            # constraints), which is the only way to do a lossless mirror
            # given that prod has data violations of the canonical schema:
            #   1. NULLs in NOT-NULL columns (entity_identifiers.confidence)
            #   2. Foreign-key inconsistencies that DuckDB only catches on
            #      parent-table DELETE inside a transaction
            # CTAS sidesteps both: the staging table inherits prod's column
            # types but no constraints, so the INSERT cannot fail. Constraint
            # enforcement is sacrificed in staging in favor of a faithful
            # mirror — staging is for editing, prod's schema migration is
            # tracked separately.
            stg.execute("DROP VIEW IF EXISTS entity_current")
            # INF11 fix (2026-04-10): previously this loop iterated
            # `db.ENTITY_TABLES` unconditionally — every entity table in
            # staging was dropped before rebuilding only the requested
            # subset, silently wiping any in-progress edits on tables the
            # operator did not intend to refresh. Drop only the tables
            # that are about to be re-CTAS'd. FK drop-order is irrelevant
            # here because CTAS-created staging tables have no foreign key
            # constraints (see the strategy comment above).
            for table in reversed(tables):
                stg.execute(f"DROP TABLE IF EXISTS {table}")

            for table in tables:
                stg.execute(
                    f"CREATE TABLE {table} AS SELECT * FROM prod.{table}"
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

            # Recreate empty skipped tables (e.g. entity_overrides_persistent)
            # individually. Cannot re-run the full entity_schema.sql because
            # its FK CREATE statements would fail against the constraint-free
            # CTAS-created entities table.
            if "entity_overrides_persistent" in (db.ENTITY_TABLES) and \
               "entity_overrides_persistent" not in tables:
                stg.execute("""
                    CREATE TABLE IF NOT EXISTS entity_overrides_persistent (
                        override_id    BIGINT,
                        entity_cik     VARCHAR,
                        action         VARCHAR NOT NULL,
                        field          VARCHAR,
                        old_value      VARCHAR,
                        new_value      VARCHAR NOT NULL,
                        reason         VARCHAR,
                        analyst        VARCHAR,
                        still_valid    BOOLEAN NOT NULL DEFAULT TRUE,
                        applied_at     TIMESTAMP DEFAULT NOW(),
                        created_at     TIMESTAMP DEFAULT NOW()
                    )
                """)
                _log("  + entity_overrides_persistent: created empty in staging")

        # Reset sequences after successful copy
        if not dry_run:
            seq_report = _reset_sequences(stg)
            report["sequences"] = seq_report
            for seq, val in seq_report.items():
                _log(f"  sequence {seq} restart with {val}")

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
