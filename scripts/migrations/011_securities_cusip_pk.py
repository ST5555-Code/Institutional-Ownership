#!/usr/bin/env python3
# pylint: disable=invalid-name  # migration files follow NNN_description.py convention
"""Migration 011 — add PRIMARY KEY (cusip) to securities (INF28 / int-12 Phase 1).

int-12 Phase 1 (see ``docs/findings/int-12-p0-findings.md``). Promotes
``securities.cusip`` from an implicit single-source-of-truth key to a
formal DuckDB PRIMARY KEY, enforcing uniqueness and NOT NULL at the
constraint layer so any future writer that attempts to insert a
duplicate or NULL CUSIP fails at apply-time rather than silently
corrupting the reference table.

Data readiness (findings §2): prod and staging both report 430,149
rows, 430,149 distinct CUSIPs, and zero NULL CUSIPs as of 2026-04-22.
No cleanup is required before the PK is added. The migration
nevertheless re-runs the duplicate/NULL probes before ALTER as a
defensive gate — surfacing a clear failure if the data drifts between
Phase 0 and Phase 1.

DuckDB PK syntax (findings §6, DuckDB 1.4.4): use the **unnamed**
``ALTER TABLE securities ADD PRIMARY KEY (cusip)`` form. The named
``ADD CONSTRAINT ... PRIMARY KEY`` variant collides with the auto-
generated ``PRIMARY_<table>_<col>`` index that DuckDB creates to back
the constraint.

DuckDB index gotcha (findings §3, cf. migration 010): ``ALTER TABLE
... ADD PRIMARY KEY`` fails with ``DependencyException`` when any
existing index is present on the table (duckdb#17348, duckdb#15399).
Both prod and staging currently carry **zero** indexes on
``securities`` (findings §3), so this migration does not need the
drop/recreate dance that 010 paid. The migration still inspects
``duckdb_indexes()`` defensively and drops/recreates if any appear
before apply time — cheap insurance against a parallel PR adding an
index between Phase 0 and Phase 1.

Idempotency — two-tier detection (findings §7.1):
  1. query ``duckdb_constraints()`` for a PRIMARY KEY on ``securities``
  2. check ``schema_versions`` for ``011_securities_cusip_pk``
If both conditions are met the run is a full no-op. If only the stamp
is present (e.g. someone manually dropped the PK) the constraint is
re-applied.

Staging schema_versions reconciliation note (findings §4, §8.1):
Phase 0 noted staging does **not** appear to have
``010_drop_nextval_defaults`` stamped in its top-5 ``schema_versions``
rows, while prod does. That gap is out of int-12 scope and must be
reconciled separately as a data operation; this migration does NOT
auto-stamp the missing 010 row. Operator should confirm staging's
migration floor matches prod before applying 011 to staging, otherwise
011 applies on top of an inconsistent baseline.

Applied to both prod (``13f.duckdb``) and staging
(``13f_staging.duckdb``) for schema parity — the L3 parity validator
(``scripts/pipeline/validate_schema_parity.py``) already covers
``securities`` via the L3_TABLES list, and will flag any constraint
divergence between the two DBs once 011 lands on one and not the
other.

Usage::

    python3 scripts/migrations/011_securities_cusip_pk.py --staging --dry-run
    python3 scripts/migrations/011_securities_cusip_pk.py --staging
    python3 scripts/migrations/011_securities_cusip_pk.py --prod --dry-run
    python3 scripts/migrations/011_securities_cusip_pk.py --prod
"""
from __future__ import annotations

import argparse
import os

import duckdb


VERSION = "011_securities_cusip_pk"
NOTES = "add PRIMARY KEY (cusip) to securities (INF28 / int-12 Phase 1)"

TABLE = "securities"
PK_COLUMN = "cusip"


def _has_table(con, name: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM duckdb_tables() WHERE table_name = ?", [name]
    ).fetchone()
    return row is not None


def _has_pk(con, table: str) -> bool:
    """True iff `table` already carries a PRIMARY KEY constraint."""
    row = con.execute(
        "SELECT 1 FROM duckdb_constraints() "
        "WHERE table_name = ? AND constraint_type = 'PRIMARY KEY'",
        [table],
    ).fetchone()
    return row is not None


def _indexes_on(con, table: str):
    """Return [(index_name, create_sql), ...] for indexes on `table`.

    DuckDB refuses ``ALTER TABLE ... ADD PRIMARY KEY`` while any index
    exists on the table (duckdb#17348). Defensive — zero indexes on
    ``securities`` today, but may change before apply.
    """
    rows = con.execute(
        "SELECT index_name, sql FROM duckdb_indexes() "
        "WHERE table_name = ? AND sql IS NOT NULL",
        [table],
    ).fetchall()
    return [(r[0], r[1]) for r in rows]


def _already_stamped(con, version: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM schema_versions WHERE version = ?", [version]
    ).fetchone()
    return row is not None


def _precheck_data(con) -> None:
    """Raise if `securities` has duplicate or NULL CUSIPs.

    DuckDB rejects ``ADD PRIMARY KEY`` on a column containing
    duplicates or NULLs, but its error message lists neither the
    duplicate values nor the row counts. Running the probes here gives
    the operator an actionable diagnosis instead.
    """
    dupes = con.execute(
        "SELECT cusip, COUNT(*) AS cnt "
        f"FROM {TABLE} "  # nosec B608 — table name is a module constant
        f"GROUP BY {PK_COLUMN} HAVING COUNT(*) > 1"
    ).fetchall()
    if dupes:
        preview = ", ".join(f"{c}×{n}" for c, n in dupes[:10])
        more = "" if len(dupes) <= 10 else f" (+{len(dupes) - 10} more)"
        raise RuntimeError(
            f"MIGRATION 011 precheck failed: {len(dupes)} duplicate "
            f"CUSIP group(s) in {TABLE}: {preview}{more}. Clean before retry."
        )

    null_count = con.execute(
        f"SELECT COUNT(*) FROM {TABLE} "  # nosec B608
        f"WHERE {PK_COLUMN} IS NULL"
    ).fetchone()[0]
    if null_count:
        raise RuntimeError(
            f"MIGRATION 011 precheck failed: {null_count} NULL "
            f"{PK_COLUMN} row(s) in {TABLE}. Clean before retry."
        )


def run_migration(db_path: str, dry_run: bool) -> None:
    """Apply migration 011 to `db_path`. --dry-run reports only."""
    if not os.path.exists(db_path):
        print(f"  SKIP: {db_path} does not exist")
        return

    con = duckdb.connect(db_path, read_only=dry_run)
    try:
        print(f"  DB: {db_path}")
        print(f"  dry_run: {dry_run}")

        if not _has_table(con, TABLE):
            raise SystemExit(
                f"  MIGRATION FAILED: {TABLE} missing in {db_path}"
            )

        pk_present = _has_pk(con, TABLE)
        stamped = _already_stamped(con, VERSION)
        print(f"  {TABLE} PK present BEFORE: {pk_present}")
        print(f"  schema_versions stamped:  {stamped}")

        if pk_present and stamped:
            print("  ALREADY APPLIED: no action")
            return

        if pk_present and not stamped:
            # PK already on the column (maybe applied manually) — just stamp.
            if dry_run:
                print(f"    INSERT schema_versions: {VERSION}")
                print("  DRY-RUN: no writes performed")
                return
            con.execute(
                "INSERT INTO schema_versions (version, notes) VALUES (?, ?)",
                [VERSION, NOTES],
            )
            con.execute("CHECKPOINT")
            print(f"  stamped schema_versions: {VERSION}")
            print("Migration 011 applied: securities.cusip PK constraint added")
            return

        _precheck_data(con)

        indexes = _indexes_on(con, TABLE)
        print(f"  {TABLE} has {len(indexes)} index(es) to drop+recreate")

        if dry_run:
            for idx_name, _ in indexes:
                print(f"    DROP INDEX {idx_name}")
            print(f"    ALTER TABLE {TABLE} ADD PRIMARY KEY ({PK_COLUMN})")
            for idx_name, _ in indexes:
                print(f"    RECREATE INDEX {idx_name}")
            if not stamped:
                print(f"    INSERT schema_versions: {VERSION}")
            print("  DRY-RUN: no writes performed")
            return

        for idx_name, _ in indexes:
            con.execute(f"DROP INDEX {idx_name}")  # nosec B608
            print(f"    DROP INDEX {idx_name}")

        con.execute(
            f"ALTER TABLE {TABLE} ADD PRIMARY KEY ({PK_COLUMN})"  # nosec B608
        )
        print(f"    ADD PRIMARY KEY on {TABLE}({PK_COLUMN})")

        for idx_name, idx_sql in indexes:
            con.execute(idx_sql)
            print(f"    RECREATE INDEX {idx_name}")

        if not stamped:
            con.execute(
                "INSERT INTO schema_versions (version, notes) VALUES (?, ?)",
                [VERSION, NOTES],
            )
            print(f"  stamped schema_versions: {VERSION}")
        con.execute("CHECKPOINT")

        pk_after = _has_pk(con, TABLE)
        print(f"  {TABLE} PK present AFTER:  {pk_after}")
        print("Migration 011 applied: securities.cusip PK constraint added")
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
