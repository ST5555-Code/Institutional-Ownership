#!/usr/bin/env python3
"""
snapshot_manager_type_legacy.py — materialize the legacy
holdings_v2.manager_type snapshot as a separate table inside the
target DB.

Purpose. Phase 4 of the build_managers.py REWRITE switches the
holdings_v2 enrichment UPDATE to `COALESCE(m.strategy_type, h.manager_type)`
to preserve 4,163 CIKs / ~5.33M rows of hand-curated values from
backfill_manager_types.py + categorized_institutions_funds_v2.csv
(see archive/docs/reports/rewrite_build_managers_phase2_20260419_082630.md §Risk 1).

Before COALESCE lands in prod, capture the current state as an
immutable reference so operators can audit what was preserved and
diff against future refreshes. The table is quarter-keyed so
downstream work can attribute coverage drops by reporting period.

Usage:
  python3 scripts/snapshot_manager_type_legacy.py --target-db data/13f.duckdb

Idempotency: refuses to overwrite an existing snapshot table with the
same name unless --force is passed. Safe to run repeatedly.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date


SNAPSHOT_TABLE = f"holdings_v2_manager_type_legacy_snapshot_{date.today().strftime('%Y%m%d')}"


def _parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--target-db", required=True,
        help="Path to the DuckDB file to snapshot (usually data/13f.duckdb).",
    )
    p.add_argument(
        "--table-name", default=SNAPSHOT_TABLE,
        help=f"Override snapshot table name (default: {SNAPSHOT_TABLE}).",
    )
    p.add_argument(
        "--force", action="store_true",
        help="Drop any pre-existing snapshot table with the same name.",
    )
    return p.parse_args()


def main():
    import duckdb

    args = _parse_args()
    con = duckdb.connect(args.target_db)

    exists = con.execute(
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = ?",
        [args.table_name],
    ).fetchone()[0]

    if exists and not args.force:
        n_existing = con.execute(
            f"SELECT COUNT(*) FROM {args.table_name}"
        ).fetchone()[0]
        print(
            f"[refuse] snapshot table `{args.table_name}` already exists "
            f"({n_existing:,} rows). Use --force to overwrite.",
            flush=True,
        )
        con.close()
        sys.exit(2)

    if exists and args.force:
        print(f"[force] dropping existing `{args.table_name}` ...", flush=True)
        con.execute(f"DROP TABLE {args.table_name}")

    print(f"[snapshot] creating `{args.table_name}` from holdings_v2 ...", flush=True)
    con.execute(f"""
        CREATE TABLE {args.table_name} AS
        SELECT cik, quarter, manager_type
        FROM holdings_v2
        WHERE manager_type IS NOT NULL
    """)
    n = con.execute(f"SELECT COUNT(*) FROM {args.table_name}").fetchone()[0]
    n_cik = con.execute(
        f"SELECT COUNT(DISTINCT cik) FROM {args.table_name}"
    ).fetchone()[0]
    n_types = con.execute(
        f"SELECT COUNT(DISTINCT manager_type) FROM {args.table_name}"
    ).fetchone()[0]
    print(f"[ok] {args.table_name}: {n:,} rows, {n_cik:,} distinct CIKs, "
          f"{n_types} distinct manager_type values",
          flush=True)

    con.execute("CHECKPOINT")
    con.close()


if __name__ == "__main__":
    main()
