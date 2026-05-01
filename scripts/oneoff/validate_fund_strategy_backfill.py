#!/usr/bin/env python3
"""validate_fund_strategy_backfill.py — post-backfill validator.

Confirms the post-conditions of `backfill_fund_strategy.py`:

  fund_universe:
    - 0 rows with fund_strategy IN ('active','passive','mixed')
    - 0 rows with fund_strategy IS NULL or ''
    - 0 rows with fund_strategy != fund_category
    - 0 rows with is_actively_managed IS NULL

  fund_holdings_v2:
    - 0 rows with fund_strategy IN ('active','passive','mixed')
      (subject to --allow-orphans, which permits residuals on
       series_id='UNKNOWN' or other rows with no fund_universe join)
    - 0 rows with fund_strategy outside the canonical set, ignoring
      legacy and NULL/empty values
    - 0 rows with fund_strategy IS NULL/empty among is_latest=TRUE

  Cross-Ownership SYN leak (cross.py:159):
    - 658 SYN funds previously NULL → now populated
    - 0 fund_universe rows with is_actively_managed IS NULL

Usage:
  python3 scripts/oneoff/validate_fund_strategy_backfill.py            # prod
  python3 scripts/oneoff/validate_fund_strategy_backfill.py --staging  # staging
  python3 scripts/oneoff/validate_fund_strategy_backfill.py --allow-orphans
"""
from __future__ import annotations

import argparse
import os
import sys

import duckdb

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

from db import PROD_DB, STAGING_DB  # noqa: E402

CANONICAL = ("equity", "balanced", "multi_asset", "bond_or_other",
             "index", "excluded", "final_filing")
LEGACY = ("active", "passive", "mixed")


def _check(label: str, sql: str, con, expected: int = 0) -> bool:
    actual = con.execute(sql).fetchone()[0]
    ok = actual == expected
    marker = "PASS" if ok else "FAIL"
    print(f"  [{marker}] {label}: {actual} (expected {expected})")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    grp = parser.add_mutually_exclusive_group()
    grp.add_argument("--prod", action="store_true")
    grp.add_argument("--staging", action="store_true")
    grp.add_argument("--db-path", help="Explicit DB path (overrides --prod/--staging).")
    parser.add_argument(
        "--allow-orphans",
        action="store_true",
        help="Permit fund_holdings_v2 legacy residuals on rows with no fund_universe match.",
    )
    args = parser.parse_args()

    if args.db_path:
        db_path = args.db_path
    else:
        db_path = STAGING_DB if args.staging else PROD_DB
    print(f"Validating: {db_path}")
    print(f"allow-orphans: {args.allow_orphans}")
    print()

    con = duckdb.connect(db_path, read_only=True)
    all_pass = True

    print("=== fund_universe ===")
    all_pass &= _check(
        "no legacy fund_strategy values",
        "SELECT COUNT(*) FROM fund_universe WHERE fund_strategy IN ('active','passive','mixed')",
        con,
    )
    all_pass &= _check(
        "no NULL/empty fund_strategy",
        "SELECT COUNT(*) FROM fund_universe WHERE fund_strategy IS NULL OR fund_strategy = ''",
        con,
    )
    all_pass &= _check(
        "fund_strategy = fund_category",
        "SELECT COUNT(*) FROM fund_universe WHERE COALESCE(fund_strategy,'') != COALESCE(fund_category,'')",
        con,
    )
    all_pass &= _check(
        "no NULL is_actively_managed",
        "SELECT COUNT(*) FROM fund_universe WHERE is_actively_managed IS NULL",
        con,
    )

    print()
    print("=== fund_holdings_v2 ===")
    legacy_sql_base = (
        "SELECT COUNT(*) FROM fund_holdings_v2 WHERE fund_strategy IN ('active','passive','mixed')"
    )
    if args.allow_orphans:
        legacy_sql = (
            "SELECT COUNT(*) FROM fund_holdings_v2 fh "
            "LEFT JOIN fund_universe fu USING (series_id) "
            "WHERE fh.fund_strategy IN ('active','passive','mixed') "
            "AND fu.series_id IS NOT NULL"
        )
        all_pass &= _check("no legacy values (excluding orphans)", legacy_sql, con)
        # Also report orphan residual for visibility.
        orphan = con.execute(
            "SELECT COUNT(*) FROM fund_holdings_v2 fh "
            "LEFT JOIN fund_universe fu USING (series_id) "
            "WHERE fh.fund_strategy IN ('active','passive','mixed') "
            "AND fu.series_id IS NULL"
        ).fetchone()[0]
        print(f"  [INFO] orphan legacy rows (no fund_universe match): {orphan}")
    else:
        all_pass &= _check("no legacy values anywhere", legacy_sql_base, con)

    canonical_tup = "(" + ",".join(f"'{v}'" for v in CANONICAL + LEGACY) + ")"
    all_pass &= _check(
        "no values outside canonical+legacy set",
        (
            f"SELECT COUNT(*) FROM fund_holdings_v2 "
            f"WHERE fund_strategy NOT IN {canonical_tup} "
            f"AND fund_strategy IS NOT NULL AND fund_strategy != ''"
        ),
        con,
    )
    all_pass &= _check(
        "is_latest=TRUE rows have non-null fund_strategy",
        "SELECT COUNT(*) FROM fund_holdings_v2 WHERE is_latest = TRUE AND (fund_strategy IS NULL OR fund_strategy = '')",
        con,
    )

    print()
    print("=== cross-page SYN leak baseline ===")
    syn_null = con.execute(
        "SELECT COUNT(*) FROM fund_universe WHERE is_actively_managed IS NULL"
    ).fetchone()[0]
    print(f"  [INFO] fund_universe rows with is_actively_managed IS NULL: {syn_null}")
    if syn_null != 0:
        all_pass = False

    print()
    print("ALL PASS" if all_pass else "FAILURES — see [FAIL] lines above.")
    con.close()
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
