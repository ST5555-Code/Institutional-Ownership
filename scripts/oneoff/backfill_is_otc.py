#!/usr/bin/env python3
"""backfill_is_otc.py — int-13 one-off backfill for INF29 is_otc flag.

Applies Rule A (SEC ticker reference exchange='OTC') and Rule B
(OpenFIGI exchange IN ('OTC US','NOT LISTED')) against existing
``securities`` and ``cusip_classifications`` rows, setting ``is_otc=TRUE``
where either rule matches. Per findings §2, Rules A and B are disjoint at
current population (union = 850 priceable CUSIPs). Rule C
(canonical_type='OTHER') is intentionally **not** applied here — deferred
per findings §6 open-question #1.

Safety:
  - --dry-run is the DEFAULT. Writes require --confirm.
  - No DROP, DELETE, or TRUNCATE. Only targeted UPDATE is_otc=TRUE on
    rows matching Rule A or Rule B. is_otc=FALSE rows are not touched.
  - Idempotent: re-running after success updates 0 rows (the column is
    already TRUE for the target set).

Usage:
    python3 scripts/oneoff/backfill_is_otc.py                       # staging dry-run
    python3 scripts/oneoff/backfill_is_otc.py --prod                # prod dry-run
    python3 scripts/oneoff/backfill_is_otc.py --staging --confirm   # staging write
    python3 scripts/oneoff/backfill_is_otc.py --prod --confirm      # prod write
"""
from __future__ import annotations

import argparse
import csv
import os
import sys

import duckdb

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

from db import PROD_DB, STAGING_DB  # noqa: E402

SEC_TICKERS_CSV = os.path.join(BASE_DIR, "data", "reference", "sec_company_tickers.csv")

_OTC_EXCHANGE_CODES = ("OTC US", "NOT LISTED")


def _load_sec_otc_tickers() -> list[str]:
    """Uppercase tickers from sec_company_tickers.csv where exchange='OTC'."""
    if not os.path.exists(SEC_TICKERS_CSV):
        raise SystemExit(f"ERROR: missing reference file {SEC_TICKERS_CSV}")
    out: set[str] = set()
    with open(SEC_TICKERS_CSV, newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            exch = (row.get('exchange') or '').strip()
            tkr = (row.get('ticker') or '').strip()
            if exch.upper() == 'OTC' and tkr:
                out.add(tkr.upper())
    return sorted(out)


def _has_column(con, table: str, column: str) -> bool:
    row = con.execute(
        """
        SELECT 1 FROM duckdb_columns()
        WHERE table_name = ? AND column_name = ?
        """,
        [table, column],
    ).fetchone()
    return row is not None


def _count_rule_a(con, table: str, ticker_col: str, tickers: list[str]) -> int:
    if not tickers:
        return 0
    return con.execute(
        f"""
        SELECT COUNT(*)
          FROM {table}
         WHERE UPPER({ticker_col}) IN (SELECT UNNEST(?))
           AND COALESCE(is_otc, FALSE) = FALSE
        """,
        [tickers],
    ).fetchone()[0]


def _count_rule_b(con, table: str, exchange_col: str) -> int:
    return con.execute(
        f"""
        SELECT COUNT(*)
          FROM {table}
         WHERE {exchange_col} IN (?, ?)
           AND COALESCE(is_otc, FALSE) = FALSE
        """,
        list(_OTC_EXCHANGE_CODES),
    ).fetchone()[0]


def _apply_rule_a(con, table: str, ticker_col: str, tickers: list[str]) -> int:
    if not tickers:
        return 0
    return _count_changes(
        con,
        f"""
        UPDATE {table}
           SET is_otc = TRUE
         WHERE UPPER({ticker_col}) IN (SELECT UNNEST(?))
           AND COALESCE(is_otc, FALSE) = FALSE
        """,
        [tickers],
    )


def _apply_rule_b(con, table: str, exchange_col: str) -> int:
    return _count_changes(
        con,
        f"""
        UPDATE {table}
           SET is_otc = TRUE
         WHERE {exchange_col} IN (?, ?)
           AND COALESCE(is_otc, FALSE) = FALSE
        """,
        list(_OTC_EXCHANGE_CODES),
    )


def _count_changes(con, sql: str, params: list) -> int:
    """Execute a DuckDB UPDATE and return the number of rows changed.

    DuckDB's cursor.rowcount is unreliable for UPDATE; use a COUNT(*) of
    the predicate before executing, then run the UPDATE, and return the
    pre-count as the number of rows that just flipped.
    """
    # Derive a COUNT query from the UPDATE by replacing the leading
    # UPDATE ... SET ... with SELECT COUNT(*) FROM — fragile in general,
    # but our UPDATEs here have a stable shape.
    select_sql = _update_to_count_select(sql)
    n = con.execute(select_sql, params).fetchone()[0]
    con.execute(sql, params)
    return n


def _update_to_count_select(update_sql: str) -> str:
    """Convert an ``UPDATE <tbl> SET ... WHERE <pred>`` into
    ``SELECT COUNT(*) FROM <tbl> WHERE <pred>``. Assumes the input follows
    the exact shape used in _apply_rule_a / _apply_rule_b above.
    """
    # Normalize whitespace to make the split deterministic.
    s = " ".join(update_sql.split())
    assert s.upper().startswith("UPDATE "), s
    after_update = s[len("UPDATE "):]
    table_name = after_update.split(" ", 1)[0]
    where_idx = s.upper().index(" WHERE ")
    where_clause = s[where_idx:]  # includes " WHERE ..."
    return f"SELECT COUNT(*) FROM {table_name} {where_clause.strip()}"


def run(db_path: str, confirm: bool) -> None:
    if not os.path.exists(db_path):
        raise SystemExit(f"ERROR: DB does not exist: {db_path}")

    tickers = _load_sec_otc_tickers()
    print(f"  SEC reference OTC tickers loaded: {len(tickers):,}")

    con = duckdb.connect(db_path, read_only=not confirm)
    try:
        print(f"  DB: {db_path}")
        print(f"  confirm: {confirm}  (default is dry-run)")

        # Pre-flight: is_otc must exist (migration 012).
        for table in ("securities", "cusip_classifications"):
            if not _has_column(con, table, "is_otc"):
                raise SystemExit(
                    f"ERROR: {table}.is_otc missing — run migration 012 first"
                )

        print()
        print("  Pre-apply counts (rows that would flip FALSE→TRUE):")
        sec_a = _count_rule_a(con, "securities", "ticker", tickers)
        sec_b = _count_rule_b(con, "securities", "exchange")
        cc_a = _count_rule_a(con, "cusip_classifications", "ticker", tickers)
        cc_b = _count_rule_b(con, "cusip_classifications", "exchange")
        print(f"    securities            : Rule A={sec_a:,}   Rule B={sec_b:,}")
        print(f"    cusip_classifications : Rule A={cc_a:,}   Rule B={cc_b:,}")

        if not confirm:
            print()
            print("  DRY-RUN: no writes performed. Re-run with --confirm to apply.")
            return

        print()
        print("  Applying updates...")
        sec_a_n = _apply_rule_a(con, "securities", "ticker", tickers)
        sec_b_n = _apply_rule_b(con, "securities", "exchange")
        cc_a_n = _apply_rule_a(con, "cusip_classifications", "ticker", tickers)
        cc_b_n = _apply_rule_b(con, "cusip_classifications", "exchange")
        con.execute("CHECKPOINT")

        print(f"    securities            : Rule A +{sec_a_n:,}   Rule B +{sec_b_n:,}")
        print(f"    cusip_classifications : Rule A +{cc_a_n:,}   Rule B +{cc_b_n:,}")

        # Post-apply summary.
        total_sec = con.execute(
            "SELECT COUNT(*) FROM securities WHERE is_otc = TRUE"
        ).fetchone()[0]
        total_cc = con.execute(
            "SELECT COUNT(*) FROM cusip_classifications WHERE is_otc = TRUE"
        ).fetchone()[0]
        print()
        print("  Post-apply totals (is_otc=TRUE):")
        print(f"    securities            : {total_sec:,}")
        print(f"    cusip_classifications : {total_cc:,}")
    finally:
        con.close()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    target = p.add_mutually_exclusive_group()
    target.add_argument("--staging", action="store_true",
                        help="Operate on staging DB (default).")
    target.add_argument("--prod", action="store_true",
                        help="Operate on prod DB.")
    p.add_argument("--path", default=None,
                   help="Explicit DB path; overrides --staging/--prod.")
    p.add_argument("--confirm", action="store_true",
                   help="Write changes. Default is dry-run.")
    args = p.parse_args()

    if args.path:
        db = args.path
    elif args.prod:
        db = PROD_DB
    else:
        db = STAGING_DB

    print("backfill_is_otc.py")
    print("=" * 60)
    run(db, confirm=args.confirm)


if __name__ == "__main__":
    main()
