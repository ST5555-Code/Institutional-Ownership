#!/usr/bin/env python3
"""validate_peer_rotation_rebuild.py — post-rebuild validator (PR-1b).

Confirms the post-conditions of `compute_peer_rotation.py` after the
fund_strategy reconciliation done in PR-1a (#233):

  fund-level (level='fund'):
    - 0 rows with entity_type IN ('active','passive','mixed')
    - 0 rows with entity_type outside canonical fund taxonomy
      (equity, balanced, multi_asset, bond_or_other, index, excluded,
       final_filing) — NULLs ignored
    - row count non-zero

  parent-level (level='parent'):
    - 0 rows with entity_type IN ('equity','balanced','multi_asset',
      'bond_or_other') — these are fund-taxonomy values that must not
      appear at parent level (which carries institution taxonomy +
      legacy active/passive/mixed for entities with no entity_type).
    - row count non-zero

  whole table:
    - row count non-zero (sanity)
    - quarter pairs are consecutive (each quarter_to immediately follows
      quarter_from in the source DISTINCT quarter ordering)

Usage:
  python3 scripts/oneoff/validate_peer_rotation_rebuild.py            # prod
  python3 scripts/oneoff/validate_peer_rotation_rebuild.py --staging  # staging
"""
from __future__ import annotations

import argparse
import os
import sys

import duckdb

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

from db import PROD_DB, STAGING_DB  # noqa: E402

CANONICAL_FUND = (
    "equity", "balanced", "multi_asset", "bond_or_other",
    "index", "excluded", "final_filing",
)
LEGACY = ("active", "passive", "mixed")
FUND_TAXONOMY_AT_PARENT = ("equity", "balanced", "multi_asset", "bond_or_other")


def _check(label: str, sql: str, con, expected: int = 0) -> bool:
    actual = con.execute(sql).fetchone()[0]
    ok = actual == expected
    marker = "PASS" if ok else "FAIL"
    print(f"  [{marker}] {label}: {actual} (expected {expected})")
    return ok


def _check_nonzero(label: str, sql: str, con) -> bool:
    actual = con.execute(sql).fetchone()[0]
    ok = actual > 0
    marker = "PASS" if ok else "FAIL"
    print(f"  [{marker}] {label}: {actual:,}")
    return ok


def _check_consecutive_pairs(con) -> bool:
    """Each (quarter_from, quarter_to) actually present in peer_rotation_flows
    must be a consecutive pair in the ordered set of distinct quarters from
    the source tables. The pipeline derives pairs as
    ``zip(quarters[:-1], quarters[1:])``; any pair NOT in that set means a
    stale row survived a partial run.

    Missing pairs (in expected but not actual) are reported as INFO, not a
    failure, because the pipeline legitimately produces 0 rows when the
    source quarters carry no ticker/sector-overlapping holdings (e.g. the
    sentinel `2022Q2` row in `fund_holdings_v2` has 1 ticker with no
    `market_data` sector match)."""
    parent_qs = [
        r[0] for r in con.execute(
            "SELECT DISTINCT quarter FROM holdings_v2 "
            "WHERE quarter IS NOT NULL ORDER BY quarter"
        ).fetchall()
    ]
    fund_qs = [
        r[0] for r in con.execute(
            "SELECT DISTINCT quarter FROM fund_holdings_v2 "
            "WHERE quarter IS NOT NULL ORDER BY quarter"
        ).fetchall()
    ]
    parent_pairs_expected = set(zip(parent_qs[:-1], parent_qs[1:]))
    fund_pairs_expected = set(zip(fund_qs[:-1], fund_qs[1:]))

    parent_pairs_actual = set(
        con.execute(
            "SELECT DISTINCT quarter_from, quarter_to FROM peer_rotation_flows "
            "WHERE level = 'parent'"
        ).fetchall()
    )
    fund_pairs_actual = set(
        con.execute(
            "SELECT DISTINCT quarter_from, quarter_to FROM peer_rotation_flows "
            "WHERE level = 'fund'"
        ).fetchall()
    )

    parent_unexpected = parent_pairs_actual - parent_pairs_expected
    fund_unexpected = fund_pairs_actual - fund_pairs_expected
    parent_missing = parent_pairs_expected - parent_pairs_actual
    fund_missing = fund_pairs_expected - fund_pairs_actual

    ok = not (parent_unexpected or fund_unexpected)
    marker = "PASS" if ok else "FAIL"
    print(f"  [{marker}] no unexpected (non-consecutive) quarter pairs")
    print(f"         parent expected={len(parent_pairs_expected)} "
          f"actual={len(parent_pairs_actual)} "
          f"unexpected={sorted(parent_unexpected)}")
    print(f"         fund   expected={len(fund_pairs_expected)} "
          f"actual={len(fund_pairs_actual)} "
          f"unexpected={sorted(fund_unexpected)}")
    if parent_missing or fund_missing:
        print(f"  [INFO] missing pairs (legitimate when source has no "
              f"ticker/sector-overlapping holdings):")
        if parent_missing:
            print(f"         parent missing={sorted(parent_missing)}")
        if fund_missing:
            print(f"         fund   missing={sorted(fund_missing)}")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    grp = parser.add_mutually_exclusive_group()
    grp.add_argument("--prod", action="store_true")
    grp.add_argument("--staging", action="store_true")
    grp.add_argument("--db-path", help="Explicit DB path (overrides --prod/--staging).")
    args = parser.parse_args()

    if args.db_path:
        db_path = args.db_path
    else:
        db_path = STAGING_DB if args.staging else PROD_DB
    print(f"Validating: {db_path}")
    print()

    con = duckdb.connect(db_path, read_only=True)
    all_pass = True

    print("=== peer_rotation_flows (level='fund') ===")
    all_pass &= _check(
        "no legacy active/passive/mixed",
        "SELECT COUNT(*) FROM peer_rotation_flows "
        "WHERE level = 'fund' AND entity_type IN ('active','passive','mixed')",
        con,
    )
    canonical_tup = "(" + ",".join(f"'{v}'" for v in CANONICAL_FUND) + ")"
    all_pass &= _check(
        "values are subset of canonical fund taxonomy (NULLs ignored)",
        f"SELECT COUNT(*) FROM peer_rotation_flows "
        f"WHERE level = 'fund' "
        f"AND entity_type IS NOT NULL "
        f"AND entity_type NOT IN {canonical_tup}",
        con,
    )
    all_pass &= _check_nonzero(
        "fund-level row count is non-zero",
        "SELECT COUNT(*) FROM peer_rotation_flows WHERE level = 'fund'",
        con,
    )

    print()
    print("=== peer_rotation_flows (level='parent') ===")
    fund_tax_tup = "(" + ",".join(f"'{v}'" for v in FUND_TAXONOMY_AT_PARENT) + ")"
    all_pass &= _check(
        "no fund-taxonomy values bleeding into parent",
        f"SELECT COUNT(*) FROM peer_rotation_flows "
        f"WHERE level = 'parent' "
        f"AND entity_type IN {fund_tax_tup}",
        con,
    )
    all_pass &= _check_nonzero(
        "parent-level row count is non-zero",
        "SELECT COUNT(*) FROM peer_rotation_flows WHERE level = 'parent'",
        con,
    )

    print()
    print("=== peer_rotation_flows (whole table) ===")
    total = con.execute(
        "SELECT COUNT(*) FROM peer_rotation_flows"
    ).fetchone()[0]
    print(f"  [INFO] total rows: {total:,}")
    if total == 0:
        all_pass = False
        print("  [FAIL] total row count is zero")

    all_pass &= _check_consecutive_pairs(con)

    print()
    print("=== entity_type distribution at fund level ===")
    for row in con.execute(
        "SELECT entity_type, COUNT(*) AS n "
        "FROM peer_rotation_flows WHERE level = 'fund' "
        "GROUP BY entity_type ORDER BY n DESC"
    ).fetchall():
        print(f"  {row[0] or '<NULL>':20s} {row[1]:>12,}")

    print()
    print("ALL PASS" if all_pass else "FAILURES — see [FAIL] lines above.")
    con.close()
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
