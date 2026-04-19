#!/usr/bin/env python3
# pylint: disable=invalid-name  # migration files follow NNN_description.py convention
"""Migration 008 — rename holdings_v2.pct_of_float → pct_of_so + add audit column.

BLOCK-PCT-OF-SO-PERIOD-ACCURACY Phase 1b, B1.

Phase 0 found no `float_shares` history exists in the DB; the only period-
indexed share count is `shares_outstanding_history.shares` (shares
outstanding, not float). Option A locked: migrate denominator semantics
to shares_outstanding via hard rename of the column plus an audit column
recording the fallback tier each row used.

Schema changes (holdings_v2 only — fund_holdings_v2 and
beneficial_ownership_v2 do not carry pct_of_float, verified Phase 1a §8.5):

  1. RENAME COLUMN pct_of_float TO pct_of_so
  2. ADD COLUMN   pct_of_so_source VARCHAR

Values for pct_of_so_source are written by enrich_holdings.py Pass B.
Three-tier fallback cascade, each surfaced as a distinct audit value
(Phase 1c, 2026-04-19 — widened from two values to three so tier 3
rows are no longer silently labeled "market_data_latest"):
  - 'soh_period_accurate'     : tier 1 — denominator from
                                shares_outstanding_history ASOF at or
                                before quarter_end (period-accurate)
  - 'market_data_so_latest'   : tier 2 — fallback to latest
                                market_data.shares_outstanding (not
                                period-accurate, still SO semantics)
  - 'market_data_float_latest': tier 3 — fallback to latest
                                market_data.float_shares (pct_of_float
                                stored in pct_of_so column; semantic
                                mixing made transparent via this flag)
  - NULL                      : no denominator available; pct_of_so
                                is NULL (not equity, or no SOH / md
                                coverage)

Idempotent: probes the current schema before each step. Re-running after
success is a no-op.

Scope in Phase 1: --staging only. Prod apply is Phase 4.

Phase 4b amendment (2026-04-19): prod has 4 non-PK indexes on
holdings_v2 that staging lacks — `ALTER TABLE RENAME COLUMN` fails
with DuckDB DependencyException. Migration now uses a
capture-and-recreate pattern: enumerate existing non-PK indexes via
`duckdb_indexes()` at runtime, drop them, execute RENAME + ADD
COLUMN, recreate from captured DDL. Works identically on prod
(4 captured) and staging (0 captured — no-op). No hardcoded index
names. Per-index rebuild timings logged to stdout for audit.

Usage:
  python3 scripts/migrations/008_rename_pct_of_float_to_pct_of_so.py --staging --dry-run
  python3 scripts/migrations/008_rename_pct_of_float_to_pct_of_so.py --staging
  python3 scripts/migrations/008_rename_pct_of_float_to_pct_of_so.py --prod --dry-run   # Phase 4 preview
  python3 scripts/migrations/008_rename_pct_of_float_to_pct_of_so.py --prod             # Phase 4 apply
"""
from __future__ import annotations

import argparse
import os
import time

import duckdb


VERSION = "008_rename_pct_of_float_to_pct_of_so"
NOTES = "holdings_v2 pct_of_float → pct_of_so rename + pct_of_so_source audit column"
TABLE = "holdings_v2"
OLD_COLUMN = "pct_of_float"
NEW_COLUMN = "pct_of_so"
AUDIT_COLUMN = "pct_of_so_source"


def _has_table(con, name: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM duckdb_tables() WHERE table_name = ?", [name]
    ).fetchone()
    return row is not None


def _has_column(con, table: str, column: str) -> bool:
    row = con.execute(
        """
        SELECT 1 FROM duckdb_columns()
        WHERE table_name = ? AND column_name = ?
        """,
        [table, column],
    ).fetchone()
    return row is not None


def _already_stamped(con, version: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM schema_versions WHERE version = ?", [version]
    ).fetchone()
    return row is not None


def _capture_indexes(con, table: str) -> list[tuple[str, str]]:
    """Return [(index_name, create_sql), ...] for non-PK indexes on `table`.

    PK / unique constraint indexes carry NULL or empty `sql` in DuckDB's
    catalog (they're implicit from the constraint), so filtering on
    non-empty sql keeps only user-defined indexes we can safely drop
    and recreate. DuckDB's `duckdb_indexes().sql` is the verbatim
    CREATE INDEX statement the user issued.
    """
    rows = con.execute(
        """
        SELECT index_name, sql
          FROM duckdb_indexes()
         WHERE table_name = ?
           AND sql IS NOT NULL
           AND sql <> ''
        """,
        [table],
    ).fetchall()
    return [(r[0], r[1]) for r in rows]


def run_migration(db_path: str, dry_run: bool) -> None:
    """Apply migration 008 to `db_path`. --dry-run reports only.

    Capture-and-recreate pattern (Phase 4b amendment):
      1. Probe column + schema_versions state
      2. Short-circuit if already applied
      3. Capture non-PK indexes on holdings_v2 (via duckdb_indexes())
      4. Pre-drop row count sanity check
      5. DROP captured indexes (logged per-index)
      6. RENAME pct_of_float -> pct_of_so (if needed)
      7. ADD COLUMN pct_of_so_source (if needed)
      8. CREATE captured indexes with original DDL (logged per-index)
      9. Post-create row count sanity check (must match step 4)
     10. Stamp schema_versions + CHECKPOINT
     11. Post-condition verification

    Failure-mode note: if any index recreation at step 8 fails after
    DROP at step 5 and RENAME/ADD at steps 6-7 have committed, the DB
    is left without that index. The captured DDL is logged to stdout
    at step 3 so an operator can manually recreate from the log.
    """
    if not os.path.exists(db_path):
        print(f"  SKIP: {db_path} does not exist")
        return

    con = duckdb.connect(db_path, read_only=dry_run)
    try:
        if not _has_table(con, TABLE):
            print(f"  SKIP ({db_path}): {TABLE} does not exist")
            return

        print(f"  DB: {db_path}")
        print(f"  dry_run: {dry_run}")

        has_old = _has_column(con, TABLE, OLD_COLUMN)
        has_new = _has_column(con, TABLE, NEW_COLUMN)
        has_audit = _has_column(con, TABLE, AUDIT_COLUMN)
        stamped = _already_stamped(con, VERSION)

        print(f"  has {OLD_COLUMN}: {has_old}")
        print(f"  has {NEW_COLUMN}: {has_new}")
        print(f"  has {AUDIT_COLUMN}: {has_audit}")
        print(f"  schema_versions stamped: {stamped}")

        if has_new and has_audit and not has_old and stamped:
            print("  ALREADY APPLIED: no action")
            return

        if has_old and has_new:
            raise SystemExit(
                f"  ABORT: both {OLD_COLUMN} and {NEW_COLUMN} exist on "
                f"{TABLE}; manual resolution required"
            )

        # Capture non-PK indexes — needed only if the RENAME step will run.
        # If only ADD COLUMN is outstanding, DuckDB allows it without the
        # index dance, so we can skip capture+drop+recreate.
        need_rename = has_old and not has_new
        captured: list[tuple[str, str]] = []
        if need_rename:
            captured = _capture_indexes(con, TABLE)
            print(f"  captured {len(captured)} non-PK index(es) on {TABLE}:")
            for name, sql in captured:
                print(f"    {name}")
                print(f"      DDL: {sql}")

        # Pre-drop row count (sanity — recreation must land same count).
        pre_count = con.execute(
            f"SELECT COUNT(*) FROM {TABLE}"
        ).fetchone()[0]
        print(f"  pre-apply row count: {pre_count:,}")

        if dry_run:
            if need_rename:
                for name, _ in captured:
                    print(f"    DROP INDEX {name}")
                print(f"    ALTER TABLE {TABLE} RENAME COLUMN "
                      f"{OLD_COLUMN} TO {NEW_COLUMN}")
            if not has_audit:
                print(f"    ALTER TABLE {TABLE} "
                      f"ADD COLUMN {AUDIT_COLUMN} VARCHAR")
            if need_rename:
                for name, sql in captured:
                    print(f"    (recreate) {sql}")
            if not stamped:
                print(f"    INSERT schema_versions: {VERSION}")
            print("  DRY-RUN: no writes performed")
            return

        total_t0 = time.time()

        # Step 5: DROP captured indexes (per-index timing)
        drop_timings: dict[str, float] = {}
        for name, _ in captured:
            t0 = time.time()
            con.execute(f'DROP INDEX "{name}"')
            drop_timings[name] = time.time() - t0
            print(f"    DROP INDEX {name}: {drop_timings[name]:.3f}s")

        # Step 6: RENAME column
        if need_rename:
            stmt = (
                f"ALTER TABLE {TABLE} RENAME COLUMN {OLD_COLUMN} TO {NEW_COLUMN}"
            )
            t0 = time.time()
            con.execute(stmt)
            print(f"    {stmt}  ({time.time()-t0:.3f}s)")

        # Step 7: ADD audit column
        if not has_audit:
            stmt = f"ALTER TABLE {TABLE} ADD COLUMN {AUDIT_COLUMN} VARCHAR"
            t0 = time.time()
            con.execute(stmt)
            print(f"    {stmt}  ({time.time()-t0:.3f}s)")

        # Step 8: RECREATE indexes (per-index timing). If a recreation
        # fails, the captured DDL is already logged (step 3) and
        # drop_timings + recreate_timings up to failure are flushed.
        recreate_timings: dict[str, float] = {}
        for name, sql in captured:
            t0 = time.time()
            try:
                con.execute(sql)
            except Exception as exc:  # pylint: disable=broad-except
                print(f"    FAILED to recreate {name}: {exc}")
                print(f"      captured DDL was: {sql}")
                print("    recoverable — re-run migration (idempotent) "
                      "or execute captured DDL manually")
                raise
            recreate_timings[name] = time.time() - t0
            print(f"    CREATE INDEX {name}: {recreate_timings[name]:.3f}s")

        # Step 9: Post-create row count sanity
        post_count = con.execute(
            f"SELECT COUNT(*) FROM {TABLE}"
        ).fetchone()[0]
        if post_count != pre_count:
            raise SystemExit(
                f"  ROW COUNT MISMATCH: pre={pre_count:,} "
                f"post={post_count:,}"
            )
        print(f"  post-apply row count: {post_count:,} "
              f"(matches pre-apply)")

        # Step 10: Stamp schema_versions + checkpoint
        if not stamped:
            con.execute(
                "INSERT INTO schema_versions (version, notes) VALUES (?, ?)",
                [VERSION, NOTES],
            )
            print(f"  stamped schema_versions: {VERSION}")
        con.execute("CHECKPOINT")

        total_dt = time.time() - total_t0
        print(f"  total wall clock: {total_dt:.1f}s")

        # Step 11: Post-condition verification
        after_old = _has_column(con, TABLE, OLD_COLUMN)
        after_new = _has_column(con, TABLE, NEW_COLUMN)
        after_audit = _has_column(con, TABLE, AUDIT_COLUMN)
        if after_old:
            raise SystemExit(
                f"  MIGRATION FAILED: {OLD_COLUMN} still present on {TABLE}"
            )
        if not after_new:
            raise SystemExit(
                f"  MIGRATION FAILED: {NEW_COLUMN} not created on {TABLE}"
            )
        if not after_audit:
            raise SystemExit(
                f"  MIGRATION FAILED: {AUDIT_COLUMN} not created on {TABLE}"
            )
        # Verify all captured indexes are back
        after_indexes = {r[0] for r in con.execute(
            "SELECT index_name FROM duckdb_indexes() WHERE table_name = ?",
            [TABLE],
        ).fetchall()}
        missing = [name for name, _ in captured if name not in after_indexes]
        if missing:
            raise SystemExit(
                f"  MIGRATION FAILED: captured indexes not recreated: "
                f"{missing}"
            )
        print(
            f"  AFTER: {OLD_COLUMN}={after_old} {NEW_COLUMN}={after_new} "
            f"{AUDIT_COLUMN}={after_audit} "
            f"indexes_recreated={len(captured)}"
        )
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
