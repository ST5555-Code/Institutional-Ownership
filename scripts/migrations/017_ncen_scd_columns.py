#!/usr/bin/env python3
# pylint: disable=invalid-name  # migration files follow NNN_description.py convention
"""Migration 017 — add SCD Type 2 columns to ncen_adviser_map.

w2-04. The N-CEN adviser-to-series mapping is being migrated to the
``SourcePipeline`` framework with ``amendment_strategy = scd_type2``.
Base-class promote uses ``valid_to = DATE '9999-12-31'`` as the open-row
sentinel and flips the prior row's ``valid_to = CURRENT_TIMESTAMP``
before inserting the new row.

Pre-migration ``ncen_adviser_map`` has no validity interval columns —
every row is treated as current. This migration adds ``valid_from`` and
``valid_to`` and backfills every existing row as an open interval:

  * ``valid_from = loaded_at`` (fallback: ``2020-01-01`` for 3 rows
    with NULL/empty series_id) — preserves the historical "when we
    learned this" moment.
  * ``valid_to = DATE '9999-12-31'`` (open-row sentinel).

With the chosen amendment_key = (series_id, adviser_crd, role) the
current prod row population has zero duplicate open-row conflicts —
verified during planning. No row closure is needed at migration time.

Idempotent — column adds are guarded; schema_versions stamp prevents
re-application. Stamps on the same connection as the DDL.

Usage::

    python3 scripts/migrations/017_ncen_scd_columns.py --staging --dry-run
    python3 scripts/migrations/017_ncen_scd_columns.py --staging
    python3 scripts/migrations/017_ncen_scd_columns.py --dry-run
    python3 scripts/migrations/017_ncen_scd_columns.py
"""
from __future__ import annotations

import argparse
import os
import time

import duckdb


VERSION = "017_ncen_scd_columns"
NOTES = (
    "valid_from + valid_to on ncen_adviser_map for SCD Type 2 promote (w2-04)"
)

TABLE = "ncen_adviser_map"


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


def _has_index(con, name: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM duckdb_indexes() WHERE index_name = ?", [name]
    ).fetchone()
    return row is not None


def _already_stamped(con, version: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM schema_versions WHERE version = ?", [version]
    ).fetchone()
    return row is not None


def _add_col_if_missing(
    con, column: str, type_sql: str, default_sql: str | None, dry_run: bool,
) -> bool:
    if _has_column(con, TABLE, column):
        print(f"    {TABLE}.{column}: already present — skip")
        return False
    default_clause = f" DEFAULT {default_sql}" if default_sql else ""
    stmt = f"ALTER TABLE {TABLE} ADD COLUMN {column} {type_sql}{default_clause}"
    if dry_run:
        print(f"    DRY: {stmt}")
    else:
        con.execute(stmt)
        print(f"    {TABLE}.{column}: added ({type_sql}{default_clause})")
    return True


def run_migration(db_path: str, dry_run: bool) -> None:
    if not os.path.exists(db_path):
        print(f"  SKIP: {db_path} does not exist")
        return

    con = duckdb.connect(db_path, read_only=dry_run)
    try:
        print(f"  DB: {db_path}")
        print(f"  dry_run: {dry_run}")

        if not _has_table(con, TABLE):
            raise SystemExit(f"  ABORT: required table missing: {TABLE}")

        stamped = _already_stamped(con, VERSION)
        print(f"  schema_versions stamped: {stamped}")
        if stamped and not dry_run:
            print("  already applied — nothing to do")
            return

        rows = con.execute(f'SELECT COUNT(*) FROM "{TABLE}"').fetchone()[0]
        print(f"  {TABLE} rows: {rows:,}")

        t0 = time.time()

        # Step 1: add the two columns. valid_to is defaulted to the open
        # sentinel so future INSERTs that forget to set it get sane values;
        # valid_from has no default (NOT NULL enforced at the ABC layer).
        if dry_run:
            _add_col_if_missing(con, "valid_from", "TIMESTAMP", None, True)
            _add_col_if_missing(
                con, "valid_to", "DATE", "DATE '9999-12-31'", True,
            )
            print(
                f"    DRY: would backfill valid_from=loaded_at "
                f"(fallback '2020-01-01') + valid_to='9999-12-31' "
                f"on {rows:,} rows"
            )
            return

        con.execute("BEGIN TRANSACTION")
        try:
            _add_col_if_missing(con, "valid_from", "TIMESTAMP", None, False)
            _add_col_if_missing(
                con, "valid_to", "DATE", "DATE '9999-12-31'", False,
            )

            # Step 2: backfill valid_from. loaded_at is populated on every
            # row written by the legacy fetch_ncen.py, so the COALESCE
            # fallback is defensive (expected to never fire, but safer
            # than leaving NULLs).
            con.execute(
                f"""
                UPDATE {TABLE}
                   SET valid_from = COALESCE(loaded_at, TIMESTAMP '2020-01-01 00:00:00')
                 WHERE valid_from IS NULL
                """  # nosec B608
            )
            # Step 3: stamp open sentinel on every row. The column default
            # covers rows inserted AFTER the ALTER, but DuckDB does not
            # apply DEFAULT retroactively to pre-existing rows.
            con.execute(
                f"UPDATE {TABLE} SET valid_to = DATE '9999-12-31' "  # nosec B608
                f"WHERE valid_to IS NULL"
            )
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        con.execute("CHECKPOINT")

        # Quality report.
        null_vf = con.execute(
            f"SELECT COUNT(*) FROM {TABLE} WHERE valid_from IS NULL"
        ).fetchone()[0]
        null_vt = con.execute(
            f"SELECT COUNT(*) FROM {TABLE} WHERE valid_to IS NULL"
        ).fetchone()[0]
        open_rows = con.execute(
            f"SELECT COUNT(*) FROM {TABLE} "
            f"WHERE valid_to = DATE '9999-12-31'"
        ).fetchone()[0]
        print(f"  null valid_from: {null_vf}")
        print(f"  null valid_to:   {null_vt}")
        print(f"  open rows:       {open_rows:,} / {rows:,}")
        if null_vf or null_vt:
            raise SystemExit("  ABORT: NULL valid_from/valid_to after backfill")

        # Supporting index for the hot SCD UPDATE in promote() — the
        # base-class _promote_scd_type2 filter is
        # (series_id, adviser_crd, role, valid_to = '9999-12-31').
        idx_name = "idx_ncen_adviser_map_scd_key"
        if not _has_index(con, idx_name):
            con.execute(
                f"CREATE INDEX {idx_name} ON {TABLE}"
                f"(series_id, adviser_crd, role, valid_to)"
            )
            print(f"  index {idx_name}: created")
        else:
            print(f"  index {idx_name}: already present")

        con.execute(
            "INSERT INTO schema_versions (version, notes) VALUES (?, ?)",
            [VERSION, NOTES],
        )
        con.execute("CHECKPOINT")
        print(f"  stamped schema_versions: {VERSION}")
        print(f"  total wall: {time.time()-t0:.2f}s")
    finally:
        con.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--path", default=None,
        help="DB path. Defaults to data/13f.duckdb (prod).",
    )
    parser.add_argument(
        "--staging", action="store_true",
        help="Shortcut for --path data/13f_staging.duckdb",
    )
    parser.add_argument(
        "--prod", action="store_true",
        help="Explicit prod target; equivalent to default.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Report actions; no writes.",
    )
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
