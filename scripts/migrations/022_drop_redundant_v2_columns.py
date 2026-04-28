#!/usr/bin/env python3
# pylint: disable=invalid-name  # migration files follow NNN_description.py convention
"""Migration 022 — drop redundant columns from holdings_v2 / fund_holdings_v2.

ROADMAP 43g. The perf-P1 rewrites (PRs #180/#181) shifted the hot query
paths to JOIN against entity / security / manager tables instead of
reading denormalized columns on the v2 holdings tables. A reference scan
across ``scripts/``, ``web/``, and ``tests/`` (excluding migration files
and retired code) found three columns with zero live READs — they are
written by the load pipelines but never selected, grouped on, or
filtered by anything outside the writer itself:

* ``holdings_v2.crd_number``        — adviser CRD lookups go through ``managers`` / ``adv_managers``
* ``holdings_v2.security_type``     — security typing is sourced from ``securities`` / ``cusip_classifications``
* ``fund_holdings_v2.best_index``   — N-PORT index reference lives on ``fund_universe.best_index``

Why a rebuild and not three ``ALTER TABLE … DROP COLUMN`` calls: DuckDB
1.4 refuses to drop a column when any index or PRIMARY KEY references a
column at a later ordinal position (``CatalogException: Cannot drop this
column: an index depends on a column after it!``), and
``ALTER TABLE … DROP CONSTRAINT`` is not yet supported. Both v2 tables
carry a ``row_id`` PRIMARY KEY at a later position than every column we
want to drop, plus six user indexes whose key columns sit downstream of
the drops. The robust workaround is the standard column-drop dance:
drop the user indexes, rebuild the table without the dead columns
(preserving the existing ``nextval('<table>_row_id_seq')`` default and
the ``row_id`` PRIMARY KEY), then recreate the indexes.

Idempotent: the migration short-circuits when none of the target
columns are present and the ``schema_versions`` row is already stamped.
On a partially-applied DB it picks up where it left off — only the
tables still carrying a doomed column are rebuilt.

Forward-only — reverting the code is the rollback path; restoring the
columns would require an add-and-backfill that no downstream needs. The
matching writer cleanups land in the same PR:

* ``scripts/load_13f_v2.py`` — drops ``crd_number`` and ``security_type``
  from the ``holdings_v2`` staging DDL, the column-tuple, the INSERT
  column list, and the SELECT from ``stg_13f_filings_deduped`` /
  ``stg_13f_infotable``.
* ``scripts/pipeline/load_nport.py`` — drops ``best_index`` from
  ``_TARGET_TABLE_COLUMNS`` (which seeds both the staging DDL and the
  test-fixture DDL via ``test_load_nport.py``) and from the INSERT /
  SELECT against ``stg_nport_holdings``.
* ``tests/pipeline/test_load_13f_v2.py`` — drops ``crd_number`` and
  ``security_type`` from the inline ``DDL_HOLDINGS_V2`` fixture.

Protected — the int-23 downgrade-refusal guard
(``scripts/pipeline/base.py:_DOWNGRADE_SENSITIVE_COLUMNS``) reads
``ticker``, ``entity_id``, ``rollup_entity_id``; none of those are
touched. ``is_latest`` is also preserved.

Usage::

    python3 scripts/migrations/022_drop_redundant_v2_columns.py --staging --dry-run
    python3 scripts/migrations/022_drop_redundant_v2_columns.py --staging
    python3 scripts/migrations/022_drop_redundant_v2_columns.py --prod --dry-run
    python3 scripts/migrations/022_drop_redundant_v2_columns.py --prod
"""
from __future__ import annotations

import argparse
import os

import duckdb


VERSION = "022_drop_redundant_v2_columns"
NOTES = (
    "drop redundant write-only columns from holdings_v2 / fund_holdings_v2 "
    "(crd_number, security_type, best_index) — ROADMAP 43g"
)

# (table, column-to-drop) pairs.
TARGETS: tuple[tuple[str, str], ...] = (
    ("holdings_v2", "crd_number"),
    ("holdings_v2", "security_type"),
    ("fund_holdings_v2", "best_index"),
)


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


def _already_stamped(con, version: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM schema_versions WHERE version = ?", [version]
    ).fetchone()
    return row is not None


def _columns(con, table: str) -> list[tuple[str, str, str | None, bool]]:
    """Return (name, data_type, default, not_null) for ``table`` in
    ordinal order."""
    rows = con.execute(
        """
        SELECT column_name, data_type, column_default, is_nullable
          FROM duckdb_columns()
         WHERE table_name = ?
         ORDER BY column_index
        """,
        [table],
    ).fetchall()
    return [(r[0], r[1], r[2], not r[3]) for r in rows]


def _pk_columns(con, table: str) -> list[str]:
    """Return the PRIMARY KEY column list for ``table`` (ordered)."""
    rows = con.execute(
        """
        SELECT constraint_column_names
          FROM duckdb_constraints()
         WHERE table_name = ? AND constraint_type = 'PRIMARY KEY'
        """,
        [table],
    ).fetchone()
    if not rows:
        return []
    return list(rows[0])


def _user_indexes(con, table: str) -> list[tuple[str, str]]:
    """Return (index_name, sql) for user indexes on ``table``."""
    rows = con.execute(
        """
        SELECT index_name, sql
          FROM duckdb_indexes()
         WHERE table_name = ?
        """,
        [table],
    ).fetchall()
    return [(r[0], r[1]) for r in rows if r[1]]


def _build_create_sql(
    table_new: str,
    cols: list[tuple[str, str, str | None, bool]],
    drop_set: set[str],
    pk_cols: list[str],
) -> str:
    """Return a CREATE TABLE statement for ``table_new`` mirroring
    ``cols`` minus ``drop_set``, with the original PRIMARY KEY clause."""
    survivors = [c for c in cols if c[0] not in drop_set]
    parts: list[str] = []
    for name, dtype, default, not_null in survivors:
        line = f'    "{name}" {dtype}'
        if default is not None:
            line += f" DEFAULT {default}"
        if not_null:
            line += " NOT NULL"
        parts.append(line)
    if pk_cols:
        pk_list = ", ".join(f'"{c}"' for c in pk_cols)
        parts.append(f"    PRIMARY KEY ({pk_list})")
    body = ",\n".join(parts)
    return f"CREATE TABLE {table_new} (\n{body}\n)"


def _rebuild_table(
    con, table: str, drop_set: set[str], dry_run: bool,
) -> bool:
    """Rebuild ``table`` without ``drop_set``. Returns True if a
    rebuild was performed (False if nothing to drop)."""
    cols = _columns(con, table)
    drop_present = [c[0] for c in cols if c[0] in drop_set]
    if not drop_present:
        print(f"  {table}: no targeted columns present — skip rebuild")
        return False

    pk_cols = _pk_columns(con, table)
    indexes = _user_indexes(con, table)
    survivors = [c[0] for c in cols if c[0] not in drop_set]
    select_list = ", ".join(f'"{c}"' for c in survivors)

    table_new = f"{table}_mig022_new"

    if dry_run:
        print(f"  {table}: rebuild plan")
        for name, _ in indexes:
            print(f"    DROP INDEX {name}")
        print(f"    CREATE TABLE {table_new} (... {len(survivors)} cols ...)")
        print(f"    INSERT INTO {table_new} ({select_list[:80]}…) "
              f"SELECT … FROM {table}")
        print(f"    DROP TABLE {table}")
        print(f"    ALTER TABLE {table_new} RENAME TO {table}")
        for name, sql in indexes:
            print(f"    {sql}")
        return True

    create_sql = _build_create_sql(table_new, cols, drop_set, pk_cols)

    # Drop user indexes (PK index is implicit; new table re-declares it).
    for name, _ in indexes:
        con.execute(f'DROP INDEX "{name}"')
        print(f"    DROPPED INDEX {name}")

    con.execute(f'DROP TABLE IF EXISTS "{table_new}"')
    con.execute(create_sql)
    print(f"    CREATED {table_new}")

    # Bulk copy. ``row_id`` is preserved as-is (the new table re-declares
    # the same ``nextval(…)`` default but we are inserting explicit
    # row_id values from the source so the sequence is not advanced for
    # the historical rows).
    con.execute(
        f'INSERT INTO "{table_new}" ({select_list}) '
        f"SELECT {select_list} FROM {table}"
    )
    new_rows = con.execute(f'SELECT COUNT(*) FROM "{table_new}"').fetchone()[0]
    old_rows = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    if new_rows != old_rows:
        raise SystemExit(
            f"  MIGRATION FAILED: row count mismatch on {table}: "
            f"old={old_rows}, new={new_rows}"
        )
    print(f"    COPIED {new_rows:,} rows into {table_new}")

    con.execute(f"DROP TABLE {table}")
    con.execute(f'ALTER TABLE "{table_new}" RENAME TO "{table}"')
    print(f"    RENAMED {table_new} -> {table}")

    for name, sql in indexes:
        con.execute(sql)
        print(f"    RECREATED INDEX {name}")

    return True


def run_migration(db_path: str, dry_run: bool) -> None:
    """Apply migration 022 to ``db_path``. ``--dry-run`` reports only."""
    if not os.path.exists(db_path):
        print(f"  SKIP: {db_path} does not exist")
        return

    con = duckdb.connect(db_path, read_only=dry_run)
    try:
        print(f"  DB: {db_path}")
        print(f"  dry_run: {dry_run}")

        for table, _col in TARGETS:
            if not _has_table(con, table):
                raise SystemExit(
                    f"  MIGRATION FAILED: {table} missing in {db_path}"
                )

        present = [
            (t, c) for t, c in TARGETS if _has_column(con, t, c)
        ]
        stamped = _already_stamped(con, VERSION)

        for t, c in TARGETS:
            state = "PRESENT" if (t, c) in present else "ABSENT"
            print(f"  {t}.{c} BEFORE: {state}")
        print(f"  schema_versions stamped: {stamped}")

        if not present and stamped:
            print("  ALREADY APPLIED: no action")
            return

        # Group target columns by table.
        by_table: dict[str, set[str]] = {}
        for t, c in present:
            by_table.setdefault(t, set()).add(c)

        if dry_run:
            for table, drop_set in by_table.items():
                _rebuild_table(con, table, drop_set, dry_run=True)
            if not stamped:
                print(f"    INSERT schema_versions: {VERSION}")
            print("  DRY-RUN: no writes performed")
            return

        for table, drop_set in by_table.items():
            print(f"  rebuilding {table} without {sorted(drop_set)}")
            _rebuild_table(con, table, drop_set, dry_run=False)

        if not stamped:
            con.execute(
                "INSERT INTO schema_versions (version, notes) VALUES (?, ?)",
                [VERSION, NOTES],
            )
            print(f"  stamped schema_versions: {VERSION}")
        con.execute("CHECKPOINT")

        for t, c in TARGETS:
            state = "PRESENT" if _has_column(con, t, c) else "ABSENT"
            print(f"  {t}.{c} AFTER:  {state}")
        for t in sorted(by_table):
            n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            print(f"  {t} row count AFTER: {n:,}")
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
