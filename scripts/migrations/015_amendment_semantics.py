#!/usr/bin/env python3
# pylint: disable=invalid-name  # migration files follow NNN_description.py convention
"""Migration 015 — amendment-semantics columns on L3 v2 fact tables.

Phase 2 / p2-02. Adds the columns required for pure-APPEND amendment
handling across the three amendable fact tables. After this migration
every row carries ``is_latest`` (current vs superseded), ``loaded_at``
(when ingested), ``backfill_quality`` (provenance), and
``accession_number`` (filing identifier, where not already present).

See ``docs/admin_refresh_system_design.md`` §5 for the design.

Per-table column adds:

  - holdings_v2:            is_latest, loaded_at, backfill_quality
  - fund_holdings_v2:       accession_number, is_latest, backfill_quality
  - beneficial_ownership_v2: is_latest, backfill_quality

Backfill strategy (per table):

  - beneficial_ownership_v2 — partition-based. The table already has
    ``accession_number`` on every row. Within each
    ``(filer_cik, subject_cusip)`` group the newest row by
    ``filing_date`` keeps ``is_latest=TRUE``; all older rows are
    flipped to FALSE. (``prior_accession`` is unpopulated on prod as
    of 2026-04-22, so a chain-based update would be a no-op.) All rows
    are quality ``direct`` because the accession is intrinsic to the
    row. 100% direct expected; inferred > 0 → ABORT.

  - fund_holdings_v2 — sentinel. No per-series accession is recoverable
    from ``ingestion_manifest`` (NPORT manifest is per-DERA-ZIP, one
    accession covers thousands of fund-month pairs). Every row gets
    ``accession_number='BACKFILL_MIG015_' || series_id || '_' ||
    report_month`` and ``backfill_quality='inferred'``. WARN expected
    (~100% inferred) — this is a pre-control-plane data gap, not a
    fault. New pipeline writes carry real accessions.

  - holdings_v2 — join-based. Joins ``filings_deduped`` on
    ``(cik, quarter)`` with ``filing_type IN ('13F-HR','13F-HR/A')``.
    Single-match → ``direct``; multi-match → ``inferred`` (newest
    ``filed_date`` wins). Rows with no match get sentinel loaded_at +
    inferred quality. ABORT if direct < 98%.

Idempotent — each column add is guarded by a presence probe, so the
migration can be re-run and will short-circuit on already-applied
tables. Stamps ``schema_versions`` once at the end.

Usage::

    python3 scripts/migrations/015_amendment_semantics.py --staging --dry-run
    python3 scripts/migrations/015_amendment_semantics.py --staging
    python3 scripts/migrations/015_amendment_semantics.py --dry-run
    python3 scripts/migrations/015_amendment_semantics.py
    python3 scripts/migrations/015_amendment_semantics.py --table holdings_v2
"""
from __future__ import annotations

import argparse
import os
import time
from typing import Callable

import duckdb


VERSION = "015_amendment_semantics"
NOTES = (
    "is_latest + loaded_at + backfill_quality on holdings_v2, "
    "fund_holdings_v2, beneficial_ownership_v2 (p2-02)"
)

ALL_TABLES = (
    "beneficial_ownership_v2",  # simplest first
    "fund_holdings_v2",
    "holdings_v2",
)

# holdings_v2 direct-backfill acceptance threshold.
HOLDINGS_DIRECT_MIN_RATIO = 0.98


# ---------------------------------------------------------------------------
# schema probes
# ---------------------------------------------------------------------------

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


def _row_count(con, table: str) -> int:
    return con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]  # nosec B608


def _already_stamped(con, version: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM schema_versions WHERE version = ?", [version]
    ).fetchone()
    return row is not None


# ---------------------------------------------------------------------------
# per-table migrators
# ---------------------------------------------------------------------------

def _add_col_if_missing(con, table: str, column: str, type_sql: str,
                       default_sql: str | None, dry_run: bool) -> bool:
    """Add column if missing. Returns True if action taken (or would be)."""
    if _has_column(con, table, column):
        print(f"    {table}.{column}: already present — skip")
        return False
    default_clause = f" DEFAULT {default_sql}" if default_sql else ""
    stmt = f"ALTER TABLE {table} ADD COLUMN {column} {type_sql}{default_clause}"
    if dry_run:
        print(f"    DRY: {stmt}")
    else:
        con.execute(stmt)
        print(f"    {table}.{column}: added ({type_sql}{default_clause})")
    return True


def _migrate_beneficial_ownership(con, dry_run: bool) -> None:
    """BO: add is_latest + backfill_quality, partition-based amendment detection."""
    table = "beneficial_ownership_v2"
    print(f"\n  === {table} ===")
    rows = _row_count(con, table)
    print(f"    rows: {rows:,}")

    _add_col_if_missing(con, table, "is_latest", "BOOLEAN", "TRUE", dry_run)
    _add_col_if_missing(con, table, "backfill_quality", "VARCHAR", None, dry_run)

    if dry_run:
        groups = con.execute(f"""
            SELECT COUNT(*) FROM (
                SELECT filer_cik, subject_cusip FROM {table}
                GROUP BY 1,2 HAVING COUNT(*) > 1
            )
        """).fetchone()[0]
        print(f"    DRY: would mark ~{groups:,} superseded groups via partition UPDATE")
        print(f"    DRY: would set backfill_quality='direct' for all {rows:,} rows")
        return

    # Step 1: default TRUE (idempotent — DEFAULT already filled new rows)
    con.execute(f"UPDATE {table} SET is_latest = TRUE")
    # Step 2: partition by (filer_cik, subject_cusip), newest by filing_date wins
    con.execute(f"""
        UPDATE {table} SET is_latest = FALSE
        WHERE accession_number NOT IN (
            SELECT accession_number FROM (
                SELECT accession_number,
                       ROW_NUMBER() OVER (
                           PARTITION BY filer_cik, subject_cusip
                           ORDER BY filing_date DESC
                       ) AS rn
                FROM {table}
            ) t WHERE rn = 1
        )
    """)
    # Step 3: all direct
    con.execute(f"UPDATE {table} SET backfill_quality = 'direct'")


def _migrate_fund_holdings(con, dry_run: bool) -> None:
    """fund_holdings_v2: add accession_number + is_latest + backfill_quality (sentinel)."""
    table = "fund_holdings_v2"
    print(f"\n  === {table} ===")
    rows = _row_count(con, table)
    print(f"    rows: {rows:,}")

    _add_col_if_missing(con, table, "accession_number", "VARCHAR", None, dry_run)
    _add_col_if_missing(con, table, "is_latest", "BOOLEAN", "TRUE", dry_run)
    _add_col_if_missing(con, table, "backfill_quality", "VARCHAR", None, dry_run)

    if dry_run:
        print(f"    DRY: would sentinel-backfill accession_number on {rows:,} rows")
        print(f"    DRY: would set is_latest=TRUE + backfill_quality='inferred'")
        return

    con.execute(f"UPDATE {table} SET is_latest = TRUE")
    con.execute(f"""
        UPDATE {table}
        SET accession_number = 'BACKFILL_MIG015_' || series_id || '_' || report_month,
            backfill_quality = 'inferred'
    """)


def _migrate_holdings(con, dry_run: bool) -> None:
    """holdings_v2: add is_latest + loaded_at + backfill_quality, join-based backfill."""
    table = "holdings_v2"
    print(f"\n  === {table} ===")
    rows = _row_count(con, table)
    print(f"    rows: {rows:,}")

    # loaded_at default now() fires at ALTER; backfill overwrites.
    _add_col_if_missing(con, table, "is_latest", "BOOLEAN", "TRUE", dry_run)
    _add_col_if_missing(con, table, "loaded_at", "TIMESTAMP", "now()", dry_run)
    _add_col_if_missing(con, table, "backfill_quality", "VARCHAR", None, dry_run)

    if dry_run:
        print(f"    DRY: would join filings_deduped on (cik, quarter) "
              f"and backfill loaded_at + backfill_quality for {rows:,} rows")
        return

    # Step 1: Join holdings_v2 to filings_deduped. Single-match → direct;
    # multi-match → newest filed_date wins + inferred.
    con.execute(f"""
        UPDATE {table} AS h
        SET loaded_at = latest.filed_date_ts,
            is_latest = TRUE,
            backfill_quality = CASE WHEN latest.match_count = 1
                                    THEN 'direct' ELSE 'inferred' END
        FROM (
            SELECT cik, quarter, accession_number,
                   strptime(filed_date, '%d-%b-%Y') AS filed_date_ts,
                   COUNT(*) OVER (PARTITION BY cik, quarter) AS match_count,
                   ROW_NUMBER() OVER (PARTITION BY cik, quarter
                                      ORDER BY filed_date DESC) AS rn
            FROM filings_deduped
            WHERE filing_type IN ('13F-HR', '13F-HR/A')
        ) latest
        WHERE h.cik = latest.cik AND h.quarter = latest.quarter
          AND latest.rn = 1
    """)
    # Step 2: Rows without a matching accession → sentinel.
    con.execute(f"""
        UPDATE {table}
        SET is_latest = TRUE,
            backfill_quality = 'inferred',
            loaded_at = '2026-01-01'::TIMESTAMP
        WHERE backfill_quality IS NULL
    """)

    # Abort if direct < threshold.
    direct = con.execute(
        f"SELECT COUNT(*) FROM {table} WHERE backfill_quality='direct'"
    ).fetchone()[0]
    ratio = direct / rows if rows else 0.0
    if ratio < HOLDINGS_DIRECT_MIN_RATIO:
        bad = con.execute(f"""
            SELECT cik, quarter, COUNT(*) AS n
            FROM {table}
            WHERE backfill_quality='inferred'
            GROUP BY 1,2 ORDER BY n DESC LIMIT 20
        """).fetchall()
        print(f"  ABORT: holdings_v2 direct ratio {ratio:.3%} < "
              f"{HOLDINGS_DIRECT_MIN_RATIO:.0%}. Failing pairs (top 20):")
        for cik, quarter, n in bad:
            print(f"    cik={cik} quarter={quarter} rows={n:,}")
        raise SystemExit(1)


# ---------------------------------------------------------------------------
# orchestration
# ---------------------------------------------------------------------------

MIGRATORS: dict[str, Callable] = {
    "beneficial_ownership_v2": _migrate_beneficial_ownership,
    "fund_holdings_v2": _migrate_fund_holdings,
    "holdings_v2": _migrate_holdings,
}

# Post-transaction index creation. DuckDB disallows CREATE INDEX in the
# same transaction as UPDATEs ("Cannot create index with outstanding
# updates"), so indexes are built after each migrator's COMMIT +
# CHECKPOINT.
INDEXES: dict[str, tuple[tuple[str, str], ...]] = {
    "beneficial_ownership_v2": (
        ("idx_bo_v2_latest", "is_latest, filer_cik"),
    ),
    "fund_holdings_v2": (
        ("idx_fh_v2_accession", "accession_number"),
        ("idx_fh_v2_latest", "is_latest, report_month"),
    ),
    "holdings_v2": (
        ("idx_holdings_v2_latest", "is_latest, quarter"),
    ),
}


def _build_indexes(con, table: str, dry_run: bool) -> None:
    for idx_name, cols in INDEXES.get(table, ()):
        if _has_index(con, idx_name):
            print(f"    {idx_name}: already present")
            continue
        stmt = f"CREATE INDEX {idx_name} ON {table}({cols})"
        if dry_run:
            print(f"    DRY: {stmt}")
        else:
            con.execute(stmt)
            print(f"    {idx_name}: created ({cols})")


def _quality_report(con, targets: tuple[str, ...]) -> dict:
    """Collect per-table is_latest + backfill_quality distributions."""
    report = {}
    for t in targets:
        total = _row_count(con, t)
        latest = dict(con.execute(
            f"SELECT is_latest, COUNT(*) FROM {t} GROUP BY is_latest"
        ).fetchall())
        quality = dict(con.execute(
            f"SELECT backfill_quality, COUNT(*) FROM {t} GROUP BY backfill_quality"
        ).fetchall())
        null_accession = con.execute(
            f"SELECT COUNT(*) FROM {t} WHERE accession_number IS NULL"
        ).fetchone()[0]
        null_latest = con.execute(
            f"SELECT COUNT(*) FROM {t} WHERE is_latest IS NULL"
        ).fetchone()[0]
        null_quality = con.execute(
            f"SELECT COUNT(*) FROM {t} WHERE backfill_quality IS NULL"
        ).fetchone()[0]
        report[t] = {
            "total": total,
            "is_latest": latest,
            "quality": quality,
            "null_accession": null_accession,
            "null_latest": null_latest,
            "null_quality": null_quality,
        }
    return report


def _print_report(report: dict) -> bool:
    """Pretty-print quality report. Returns overall PASS/FAIL bool."""
    print("\n=== Migration 015 — Amendment Semantics Backfill Report ===")
    overall_pass = True
    for table, stats in report.items():
        tot = stats["total"]
        print(f"\n{table}:")
        print(f"  Total rows:      {tot:,}")
        for v, n in sorted(stats["is_latest"].items(), key=lambda x: (x[0] is False, x[0] is None)):
            pct = 100 * n / tot if tot else 0.0
            label = "TRUE" if v is True else ("FALSE" if v is False else "NULL")
            print(f"  is_latest={label}:   {n:,} ({pct:.1f}%)")
        for q, n in sorted(stats["quality"].items(), key=lambda x: (x[0] is None, x[0] or "")):
            pct = 100 * n / tot if tot else 0.0
            label = q if q is not None else "NULL"
            print(f"  backfill_quality='{label}': {n:,} ({pct:.1f}%)")

        table_fail = False
        if stats["null_accession"] > 0:
            print(f"  FAIL: {stats['null_accession']:,} NULL accession_number")
            table_fail = True
        if stats["null_latest"] > 0:
            print(f"  FAIL: {stats['null_latest']:,} NULL is_latest")
            table_fail = True
        if stats["null_quality"] > 0:
            print(f"  FAIL: {stats['null_quality']:,} NULL backfill_quality")
            table_fail = True

        if table == "beneficial_ownership_v2":
            inferred = stats["quality"].get("inferred", 0)
            if inferred > 0:
                print(f"  FAIL: BO inferred={inferred:,} (expected 0)")
                table_fail = True
            else:
                print("  PASS: BO 100% direct")
        elif table == "holdings_v2":
            direct = stats["quality"].get("direct", 0)
            ratio = direct / tot if tot else 0.0
            if ratio < HOLDINGS_DIRECT_MIN_RATIO:
                print(f"  FAIL: holdings direct ratio {ratio:.3%} < "
                      f"{HOLDINGS_DIRECT_MIN_RATIO:.0%}")
                table_fail = True
            else:
                print(f"  PASS: holdings direct {ratio:.1%} >= "
                      f"{HOLDINGS_DIRECT_MIN_RATIO:.0%}")
        elif table == "fund_holdings_v2":
            inferred = stats["quality"].get("inferred", 0)
            pct = 100 * inferred / tot if tot else 0.0
            print(f"  WARN (expected): fund_holdings_v2 inferred "
                  f"{inferred:,} ({pct:.1f}%) — pre-control-plane")

        overall_pass = overall_pass and not table_fail
    print(f"\nOverall: {'PASS' if overall_pass else 'FAIL'}")
    return overall_pass


def run_migration(db_path: str, dry_run: bool,
                  targets: tuple[str, ...]) -> None:
    if not os.path.exists(db_path):
        print(f"  SKIP: {db_path} does not exist")
        return

    con = duckdb.connect(db_path, read_only=dry_run)
    try:
        print(f"  DB: {db_path}")
        print(f"  dry_run: {dry_run}")
        print(f"  targets: {list(targets)}")

        for t in targets:
            if not _has_table(con, t):
                raise SystemExit(f"  ABORT: required table missing: {t}")

        stamped = _already_stamped(con, VERSION)
        print(f"  schema_versions stamped: {stamped}")

        t_total = time.time()
        for t in targets:
            t0 = time.time()
            if dry_run:
                MIGRATORS[t](con, dry_run=True)
                _build_indexes(con, t, dry_run=True)
            else:
                con.execute("BEGIN TRANSACTION")
                try:
                    MIGRATORS[t](con, dry_run=False)
                    con.execute("COMMIT")
                except Exception:
                    con.execute("ROLLBACK")
                    raise
                con.execute("CHECKPOINT")
                _build_indexes(con, t, dry_run=False)
            print(f"    {t}: wall {time.time()-t0:.2f}s")

        if not dry_run:
            report = _quality_report(con, targets)
            ok = _print_report(report)
            if not ok:
                raise SystemExit("  ABORT: quality gates failed")
            if not stamped:
                con.execute(
                    "INSERT INTO schema_versions (version, notes) "
                    "VALUES (?, ?)",
                    [VERSION, NOTES],
                )
                con.execute("CHECKPOINT")
                print(f"\n  stamped schema_versions: {VERSION}")

        print(f"\n  total wall: {time.time()-t_total:.2f}s")
    finally:
        con.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", default=None,
                        help="DB path. Defaults to data/13f.duckdb (prod).")
    parser.add_argument("--staging", action="store_true",
                        help="Shortcut for --path data/13f_staging.duckdb")
    parser.add_argument("--prod", action="store_true",
                        help="Explicit prod target; equivalent to default.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report actions; no writes.")
    parser.add_argument("--table", choices=list(ALL_TABLES), default=None,
                        help="Restrict to a single table (default: all).")
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

    targets = (args.table,) if args.table else ALL_TABLES
    run_migration(db_path, dry_run=args.dry_run, targets=targets)


if __name__ == "__main__":
    main()
