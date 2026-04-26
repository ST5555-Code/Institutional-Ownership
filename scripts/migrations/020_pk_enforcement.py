#!/usr/bin/env python3
# pylint: disable=invalid-name  # migration files follow NNN_description.py convention
"""Migration 020 — declare PRIMARY KEY on 21 L3/L4 tables.

DuckDB has no syntax for adding a PRIMARY KEY clause to an existing table's
canonical DDL. ``ALTER TABLE ... ADD PRIMARY KEY`` exists but the constraint
ends up bolted onto a stored DDL that does not reflect it, and the ALTER
fails outright if any index already exists on the table (duckdb#17348; see
migration 011's preamble for the full background). This migration takes the
stronger path: rebuild each target with the PRIMARY KEY declared inline in
its CREATE TABLE statement so the constraint becomes part of the schema as
captured by ``duckdb_tables().sql``.

Per table the migration:

  1. CREATE TABLE <table>_pk_tmp AS SELECT * FROM <table>  (data snapshot)
  2. DROP every index on the original
  3. DROP TABLE <table>
  4. Re-execute the captured CREATE TABLE DDL with ``, PRIMARY KEY (cols)``
     injected before the closing paren — this preserves all defaults and
     NOT NULL constraints exactly as they were
  5. INSERT INTO <table> SELECT * FROM <table>_pk_tmp
  6. Recreate every dropped index
  7. DROP TABLE <table>_pk_tmp

The whole per-table block is wrapped in a transaction so a mid-table crash
leaves the original table either untouched or fully replaced.

Pre-cleanup (run before the snapshot of the affected table):

  - cik_crd_links: keep the higher-match_score row of the
    (cik='0001132708', crd_number='107138') duplicate pair; drop its
    lower-score sibling.

Out of scope:

  - other_managers: the proposed PK includes ``other_cik``, which carries
    5,518 NULL values in prod. DuckDB rejects NULL in PRIMARY KEY columns,
    and the original "19 duplicate rows" cleanup count maps to grouping
    on (accession_number, sequence_number) rather than the proposed
    triple. Decision deferred; this migration leaves the table untouched.
  - ncen_adviser_map: design call pending on its 34 NULL adviser_crd rows.

Idempotency: the per-table block short-circuits on tables that already
carry a PRIMARY KEY constraint. The migration is also recovery-safe — if
a prior half-run left a ``<table>_pk_tmp`` behind, the per-table block
drops it before retrying.

View handling: ``entity_current`` is the only user-defined view in prod
and references entities, entity_aliases, entity_classification_history,
and entity_rollup_history. The view is dropped once at the top of the
run and recreated once at the end so the four dependent tables can be
processed in any order without inter-table sequencing.

v2 sequence safety (verified pre-flight 2026-04-26):

    table                       MAX(row_id)   seq.last_value
    holdings_v2                  98,564,908     101,770,777
    fund_holdings_v2             79,134,430      79,134,431
    beneficial_ownership_v2         220,996         220,997

All three sequences are ahead of MAX, so the recreated table's inline
``DEFAULT(nextval('<table>_row_id_seq'))`` continues issuing
non-colliding ids after the rebuild.

Usage::

    python3 scripts/migrations/020_pk_enforcement.py --dry-run
    python3 scripts/migrations/020_pk_enforcement.py
    python3 scripts/migrations/020_pk_enforcement.py --path /custom/13f.duckdb
"""
from __future__ import annotations

import argparse
import os
import time
from typing import Optional

import duckdb


VERSION = "020_pk_enforcement"
NOTES = "declare PRIMARY KEY on 21 L3/L4 tables (excludes other_managers)"


# (table, [pk cols]) — covers 21 of the 22 originally-scoped tables.
# other_managers is intentionally absent (see module docstring).
PK_SPEC: list[tuple[str, list[str]]] = [
    # Group 1 — quick wins (no cleanup).
    ("market_data",                   ["ticker"]),
    ("adv_managers",                  ["crd_number"]),
    ("filings",                       ["accession_number"]),
    ("filings_deduped",               ["accession_number"]),
    ("cik_crd_direct",                ["cik", "crd_number"]),
    ("parent_bridge",                 ["cik"]),
    ("entities",                      ["entity_id"]),
    ("entity_identifiers",            ["identifier_type", "identifier_value", "valid_from"]),
    ("entity_relationships",          ["relationship_id"]),
    ("entity_aliases",                ["entity_id", "alias_name", "alias_type", "valid_from"]),
    ("entity_classification_history", ["entity_id", "valid_from"]),
    ("entity_overrides_persistent",   ["override_id"]),
    ("entity_identifiers_staging",    ["staging_id"]),
    ("entity_relationships_staging",  ["id"]),
    ("investor_flows",                ["ticker", "period", "rollup_type", "rollup_entity_id"]),
    ("ticker_flow_stats",             ["ticker", "quarter_from", "quarter_to", "rollup_type"]),
    # Group 2 — surrogate row_id (sequence ahead of MAX confirmed pre-flight).
    ("holdings_v2",                   ["row_id"]),
    ("fund_holdings_v2",              ["row_id"]),
    ("beneficial_ownership_v2",       ["row_id"]),
    # Group 3 — light cleanup then PK.
    ("cik_crd_links",                 ["cik", "crd_number"]),
    ("entity_rollup_history",         ["entity_id", "rollup_type", "valid_from", "valid_to"]),
]


# Views that must be dropped before any of these tables can be rebuilt.
# Currently only entity_current references the target set.
DEPENDENT_VIEWS = ("entity_current",)


def _has_table(con, name: str) -> bool:
    return con.execute(
        "SELECT 1 FROM duckdb_tables() WHERE table_name = ?", [name]
    ).fetchone() is not None


def _has_pk(con, table: str) -> bool:
    return con.execute(
        "SELECT 1 FROM duckdb_constraints() "
        "WHERE table_name = ? AND constraint_type = 'PRIMARY KEY'",
        [table],
    ).fetchone() is not None


def _row_count(con, table: str) -> int:
    return con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]  # nosec B608


def _captured_ddl(con, table: str) -> str:
    row = con.execute(
        "SELECT sql FROM duckdb_tables() WHERE table_name = ?", [table]
    ).fetchone()
    if row is None or row[0] is None:
        raise RuntimeError(f"DDL for {table} not found in duckdb_tables()")
    return row[0]


def _captured_indexes(con, table: str) -> list[tuple[str, str]]:
    return [
        (r[0], r[1])
        for r in con.execute(
            "SELECT index_name, sql FROM duckdb_indexes() "
            "WHERE table_name = ? AND sql IS NOT NULL",
            [table],
        ).fetchall()
    ]


def _captured_view(con, view: str) -> Optional[str]:
    row = con.execute(
        "SELECT sql FROM duckdb_views() WHERE view_name = ? AND NOT internal",
        [view],
    ).fetchone()
    return row[0] if row else None


def _inject_pk(ddl: str, pk_cols: list[str]) -> str:
    """Insert ``, PRIMARY KEY (cols)`` before the outer closing ``)``.

    The captured DDL is shaped ``CREATE TABLE name(col1 ..., col2 ...);``
    where the last character before the optional terminator is the column
    list's outer closing paren. Stripping that paren, appending the PK
    clause, and re-adding the paren produces a valid recreate statement
    that preserves every column, type, default and NOT NULL exactly.
    """
    body = ddl.rstrip().rstrip(";").rstrip()
    if not body.endswith(")"):
        raise RuntimeError(f"unexpected DDL shape (no trailing ')'): {ddl!r}")
    cols = ", ".join(f'"{c}"' for c in pk_cols)
    return body[:-1] + f", PRIMARY KEY ({cols}))"


def _already_stamped(con, version: str) -> bool:
    return con.execute(
        "SELECT 1 FROM schema_versions WHERE version = ?", [version]
    ).fetchone() is not None


def _cleanup_cik_crd_links(con, dry_run: bool) -> int:
    """Drop the 88.88-match_score sibling of the lone (cik, crd_number) dup.

    Pre-flight (2026-04-26) confirms exactly one duplicate group:
        ('0001132708', '107138', 2)
    where the two rows differ on filing_name and match_score. Keep the
    higher-score row (94.91) so the surviving record is the better-attested
    name match. Returns rows deleted (always 0 or 1)."""
    dups = con.execute(
        "SELECT cik, crd_number, COUNT(*) FROM cik_crd_links "
        "GROUP BY 1, 2 HAVING COUNT(*) > 1"
    ).fetchall()
    if not dups:
        print("    cik_crd_links: no dups to clean (already deduped?)")
        return 0
    if dups != [("0001132708", "107138", 2)]:
        raise RuntimeError(
            f"cik_crd_links cleanup precheck mismatch — unexpected dup set: {dups}"
        )
    if dry_run:
        print("    cik_crd_links: would delete 1 row (cik=0001132708, "
              "crd=107138, match_score < 90)")
        return 1

    pre = _row_count(con, "cik_crd_links")
    con.execute(
        "DELETE FROM cik_crd_links "
        "WHERE cik = '0001132708' AND crd_number = '107138' "
        "AND match_score < 90"
    )
    post = _row_count(con, "cik_crd_links")
    deleted = pre - post
    if deleted != 1:
        raise RuntimeError(
            f"cik_crd_links cleanup deleted {deleted} row(s); expected 1"
        )
    survivors = con.execute(
        "SELECT COUNT(*) FROM cik_crd_links "
        "WHERE cik = '0001132708' AND crd_number = '107138'"
    ).fetchone()[0]
    if survivors != 1:
        raise RuntimeError(
            f"cik_crd_links cleanup left {survivors} matching row(s); expected 1"
        )
    print(f"    cik_crd_links: deleted 1 dup row (rows {pre} -> {post})")
    return 1


def _process_table(
    con, table: str, pk_cols: list[str], dry_run: bool
) -> tuple[bool, int, int]:
    """Rebuild `table` with the PK declared inline. Idempotent.

    Returns (applied, rows_before, rows_after). `applied=False` means the
    table already had a PK and was skipped."""
    if _has_pk(con, table):
        n = _row_count(con, table)
        print(f"  {table}: PK already present, skip (rows={n:,})")
        return False, n, n

    ddl = _captured_ddl(con, table)
    indexes = _captured_indexes(con, table)
    pk_ddl = _inject_pk(ddl, pk_cols)
    pre = _row_count(con, table)
    tmp = f"{table}_pk_tmp"

    if dry_run:
        print(f"  {table}: would rebuild with PK ({', '.join(pk_cols)}) "
              f"[rows={pre:,}, indexes={len(indexes)}]")
        return True, pre, pre

    # Defensive: a prior half-run may have left the snapshot table behind.
    con.execute(f'DROP TABLE IF EXISTS "{tmp}"')

    t0 = time.time()
    con.execute("BEGIN TRANSACTION")
    try:
        con.execute(f'CREATE TABLE "{tmp}" AS SELECT * FROM "{table}"')
        for idx_name, _ in indexes:
            con.execute(f'DROP INDEX "{idx_name}"')
        con.execute(f'DROP TABLE "{table}"')
        con.execute(pk_ddl)
        con.execute(f'INSERT INTO "{table}" SELECT * FROM "{tmp}"')
        for _, idx_sql in indexes:
            con.execute(idx_sql)
        con.execute(f'DROP TABLE "{tmp}"')
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        # Best-effort: drop the snapshot if it survived rollback. If even
        # this DROP errors (e.g. catalog still half-locked), surface it on
        # stderr but let the original exception propagate as the cause.
        try:
            con.execute(f'DROP TABLE IF EXISTS "{tmp}"')
        except duckdb.Error as drop_exc:
            print(f"    {table}: snapshot {tmp} cleanup failed: {drop_exc}")
        raise

    post = _row_count(con, table)
    if post != pre:
        raise RuntimeError(
            f"{table}: row count drift {pre:,} -> {post:,}"
        )
    if not _has_pk(con, table):
        raise RuntimeError(f"{table}: PK not present after rebuild")
    elapsed = time.time() - t0
    print(f"  {table}: PK enforced ({pre:,} rows preserved, "
          f"{len(indexes)} index(es) rebuilt, {elapsed:.2f}s)")
    return True, pre, post


def run_migration(db_path: str, dry_run: bool) -> None:
    """Apply migration 020 to `db_path`. --dry-run reports only."""
    if not os.path.exists(db_path):
        print(f"  SKIP: {db_path} does not exist")
        return

    con = duckdb.connect(db_path, read_only=dry_run)
    try:
        print(f"  DB: {db_path}")
        print(f"  dry_run: {dry_run}")

        # Pre-flight: targets must exist.
        missing = [t for t, _ in PK_SPEC if not _has_table(con, t)]
        if missing:
            raise SystemExit(f"  ABORT: missing target tables: {missing}")

        stamped = _already_stamped(con, VERSION)
        already_pk = sum(1 for t, _ in PK_SPEC if _has_pk(con, t))
        print(f"  schema_versions stamped: {stamped}")
        print(f"  tables with PK already present: {already_pk}/{len(PK_SPEC)}")

        if stamped and already_pk == len(PK_SPEC):
            print("  ALREADY APPLIED: no action")
            return

        # Capture dependent view DDLs before we drop the view.
        view_ddls: dict[str, str] = {}
        for v in DEPENDENT_VIEWS:
            ddl = _captured_view(con, v)
            if ddl is not None:
                view_ddls[v] = ddl
        if view_ddls:
            print(f"  dependent views captured: {list(view_ddls)}")

        if dry_run:
            print("\n  --- planned actions (dry-run) ---")
            print(f"    DELETE 1 row from cik_crd_links (dup cleanup)")
            for v in view_ddls:
                print(f"    DROP VIEW {v}")
            for table, pk_cols in PK_SPEC:
                _process_table(con, table, pk_cols, dry_run=True)
            for v in view_ddls:
                print(f"    RECREATE VIEW {v}")
            if not stamped:
                print(f"    INSERT schema_versions: {VERSION}")
            print("  DRY-RUN: no writes performed")
            return

        # Cleanup pass — must run before the cik_crd_links snapshot.
        print("\n  --- cleanup pass ---")
        _cleanup_cik_crd_links(con, dry_run=False)

        # Drop dependent views so the underlying tables can be rebuilt.
        if view_ddls:
            print("\n  --- drop dependent views ---")
            for v in view_ddls:
                con.execute(f"DROP VIEW IF EXISTS {v}")
                print(f"    DROP VIEW {v}")

        # Per-table rebuild.
        print("\n  --- rebuild tables ---")
        t_total = time.time()
        applied_count = 0
        for table, pk_cols in PK_SPEC:
            applied, _, _ = _process_table(con, table, pk_cols, dry_run=False)
            if applied:
                applied_count += 1

        # Recreate dependent views.
        if view_ddls:
            print("\n  --- recreate dependent views ---")
            for v, ddl in view_ddls.items():
                con.execute(ddl)
                print(f"    RECREATE VIEW {v}")

        # Stamp + flush.
        if not stamped:
            con.execute(
                "INSERT INTO schema_versions (version, notes) VALUES (?, ?)",
                [VERSION, NOTES],
            )
            print(f"\n  stamped schema_versions: {VERSION}")
        con.execute("CHECKPOINT")

        # Post-condition verification: every target now carries a PK.
        still_missing = [t for t, _ in PK_SPEC if not _has_pk(con, t)]
        if still_missing:
            raise SystemExit(
                f"  MIGRATION FAILED: PK still absent on: {still_missing}"
            )

        print(f"\nMigration 020 applied: "
              f"{applied_count} table(s) rebuilt, "
              f"{len(PK_SPEC) - applied_count} already-PK skipped, "
              f"total wall {time.time() - t_total:.2f}s")
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
