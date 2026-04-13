#!/usr/bin/env python3
"""
migrate_batch_3a.py — one-shot DDL migration for ARCH-3A.

Creates two new reference tables:
  1. fund_family_patterns (pattern, inst_parent_name)
     Seeded from the in-code get_nport_family_patterns() dict so
     match_nport_family() can query DB instead of a hardcoded dict.
  2. data_freshness (table_name PK, last_computed_at, row_count)
     Pipeline scripts will write rows here after each rebuild.

Defaults to running against the STAGING DB. Pass --prod to apply to
production (only after merge_staging.py has been run successfully
against staging, OR as a direct apply during the Batch 3-A migration
after the dry-run diff has been reviewed).

Usage:
  python3 scripts/migrate_batch_3a.py              # staging (default)
  python3 scripts/migrate_batch_3a.py --prod       # production
  python3 scripts/migrate_batch_3a.py --dry-run    # report plan only
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from db import PROD_DB, STAGING_DB  # noqa: E402
from queries import get_nport_family_patterns  # noqa: E402


CREATE_FUND_FAMILY_PATTERNS = """
CREATE TABLE IF NOT EXISTS fund_family_patterns (
    pattern VARCHAR NOT NULL,
    inst_parent_name VARCHAR NOT NULL,
    PRIMARY KEY (inst_parent_name, pattern)
)
"""

CREATE_DATA_FRESHNESS = """
CREATE TABLE IF NOT EXISTS data_freshness (
    table_name VARCHAR PRIMARY KEY,
    last_computed_at TIMESTAMP,
    row_count BIGINT
)
"""


def build_seed_rows():
    """Flatten the in-code dict into (pattern, inst_parent_name) rows."""
    patterns_dict = get_nport_family_patterns()
    rows = []
    for key, patterns in patterns_dict.items():
        for p in patterns:
            rows.append((p, key))
    return rows


def apply(db_path: str, dry_run: bool) -> None:
    seed_rows = build_seed_rows()
    print(f"target DB: {db_path}")
    print(f"seed rows for fund_family_patterns: {len(seed_rows)} "
          f"from {len(set(k for _, k in seed_rows))} groups")
    if dry_run:
        print("--dry-run set — no writes")
        return

    con = duckdb.connect(db_path)
    try:
        con.execute(CREATE_FUND_FAMILY_PATTERNS)
        con.execute(CREATE_DATA_FRESHNESS)
        # Idempotent seed: delete everything then insert. Cheap; ~115 rows.
        con.execute("DELETE FROM fund_family_patterns")
        con.executemany(
            "INSERT INTO fund_family_patterns (pattern, inst_parent_name) VALUES (?, ?)",
            seed_rows,
        )
        ffp_count = con.execute("SELECT COUNT(*) FROM fund_family_patterns").fetchone()[0]
        df_count = con.execute("SELECT COUNT(*) FROM data_freshness").fetchone()[0]
        print(f"fund_family_patterns: {ffp_count} rows")
        print(f"data_freshness:       {df_count} rows (pipelines populate)")
    finally:
        con.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch 3-A DDL migration")
    parser.add_argument("--prod", action="store_true",
                        help="Apply to production (default is staging)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report plan, make no writes")
    args = parser.parse_args()

    target = PROD_DB if args.prod else STAGING_DB
    apply(target, args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
