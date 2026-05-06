#!/usr/bin/env python3
"""enrich_13dg.py — 13D/G Group 2 full-refresh for beneficial_ownership_v2.

Owns the on-demand, post-promote enrichment pass for:
  - beneficial_ownership_v2.entity_id
  - beneficial_ownership_v2.rollup_entity_id
  - beneficial_ownership_v2.rollup_name

(``dm_rollup_entity_id`` / ``dm_rollup_name`` were dropped in PR #297 /
migration 026 — DM rollup is read-time via Method A.)

Then rebuilds `beneficial_ownership_current` so the L4 view inherits the
refreshed entity columns.

Option C complement: `promote_13dg.py` enriches only the filer CIKs
touched by a given run (cheap, scoped). `enrich_13dg.py` does a full
refresh across every filer_cik — use this after entity merges, CRD
backfills, or rollup changes to repair drift on historical rows.

Single atomic UPDATE at 51,905 row scale — restart-safe by virtue of
being one statement. No partial state. Idempotent.

CLI:
  --staging              write to staging DB instead of prod
  --dry-run              projection only — no writes; show predicted deltas
  --filer-cik CIK        scope to a single filer (for debugging)

Examples:
  python3 scripts/enrich_13dg.py --dry-run
  python3 scripts/enrich_13dg.py --staging --dry-run
  python3 scripts/enrich_13dg.py --filer-cik 0001018963 --dry-run
  python3 scripts/enrich_13dg.py                       # prod full refresh
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

import duckdb

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

from db import PROD_DB, STAGING_DB  # noqa: E402
from pipeline.shared import (  # noqa: E402
    bulk_enrich_bo_filers,
    rebuild_beneficial_ownership_current,
    refresh_snapshot,
    stamp_freshness,
)


def _coverage(con) -> dict:
    """Report current entity-column coverage on beneficial_ownership_v2."""
    row = con.execute(
        """
        SELECT COUNT(*)                     AS total,
               COUNT(entity_id)             AS with_entity_id,
               COUNT(rollup_entity_id)      AS with_rollup,
               COUNT(rollup_name)           AS with_rollup_name,
               COUNT(DISTINCT filer_cik)    AS distinct_filers
        FROM beneficial_ownership_v2
        """
    ).fetchone()
    return {
        "total": row[0],
        "with_entity_id": row[1],
        "with_rollup": row[2],
        "with_rollup_name": row[3],
        "distinct_filers": row[4],
    }


def _print_coverage(label: str, cov: dict) -> None:
    total = cov["total"] or 1
    print(f"  {label}:")
    print(f"    rows                : {cov['total']:,}")
    print(f"    distinct filer_cik  : {cov['distinct_filers']:,}")
    print(f"    entity_id           : {cov['with_entity_id']:,}  "
          f"({100 * cov['with_entity_id'] / total:.2f}%)")
    print(f"    rollup_entity_id    : {cov['with_rollup']:,}  "
          f"({100 * cov['with_rollup'] / total:.2f}%)")
    print(f"    rollup_name         : {cov['with_rollup_name']:,}  "
          f"({100 * cov['with_rollup_name'] / total:.2f}%)")


def _predict_deltas(con, filer_ciks: set[str] | None) -> dict:
    """Compute what the UPDATE *would* change without writing.

    Counts rows whose (entity_id, rollup_entity_id, rollup_name) would
    differ from the resolved MDM values post-join.
    """
    scope_filter = ""
    params: list = []
    if filer_ciks:
        placeholders = ",".join("?" * len(filer_ciks))
        scope_filter = f" AND b.filer_cik IN ({placeholders})"
        params = list(filer_ciks)

    row = con.execute(
        f"""
        WITH resolved AS (
            SELECT ei.identifier_value    AS filer_cik,
                   ei.entity_id           AS entity_id,
                   ec.rollup_entity_id    AS ec_rollup_entity_id,
                   ea_ec.alias_name       AS ec_rollup_name
              FROM entity_identifiers ei
              LEFT JOIN entity_rollup_history ec
                     ON ec.entity_id = ei.entity_id
                    AND ec.rollup_type = 'economic_control_v1'
                    AND ec.valid_to = DATE '9999-12-31'
              LEFT JOIN entity_aliases ea_ec
                     ON ea_ec.entity_id = ec.rollup_entity_id
                    AND ea_ec.is_preferred = TRUE
                    AND ea_ec.valid_to = DATE '9999-12-31'
             WHERE ei.identifier_type = 'cik'
               AND ei.valid_to = DATE '9999-12-31'
        )
        SELECT
            COUNT(*) FILTER (WHERE r.filer_cik IS NOT NULL) AS matched_rows,
            COUNT(*) FILTER (WHERE r.filer_cik IS NULL) AS unmatched_rows,
            COUNT(*) FILTER (WHERE
                b.entity_id IS DISTINCT FROM r.entity_id
            ) AS eid_delta,
            COUNT(*) FILTER (WHERE
                b.rollup_entity_id IS DISTINCT FROM r.ec_rollup_entity_id
            ) AS rollup_delta,
            COUNT(*) FILTER (WHERE
                b.rollup_name IS DISTINCT FROM r.ec_rollup_name
            ) AS rollup_name_delta
        FROM beneficial_ownership_v2 b
        LEFT JOIN resolved r ON r.filer_cik = b.filer_cik
        WHERE 1=1
        {scope_filter}
        """,
        params,
    ).fetchone()
    return {
        "matched_rows": row[0],
        "unmatched_rows": row[1],
        "eid_delta": row[2],
        "rollup_delta": row[3],
        "rollup_name_delta": row[4],
    }


def _print_deltas(deltas: dict) -> None:
    print("  predicted deltas (DRY-RUN):")
    print(f"    rows matching a filer in MDM : {deltas['matched_rows']:,}")
    print(f"    rows with no MDM filer match : {deltas['unmatched_rows']:,}")
    print(f"    entity_id           would change : {deltas['eid_delta']:,}")
    print(f"    rollup_entity_id    would change : {deltas['rollup_delta']:,}")
    print(f"    rollup_name         would change : {deltas['rollup_name_delta']:,}")


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staging", action="store_true",
                        help="Write to staging DB instead of prod.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report predicted deltas; no writes.")
    parser.add_argument("--filer-cik", default=None,
                        help="Scope to a single filer_cik "
                             "(zero-padded 10-digit).")
    args = parser.parse_args()

    db_path = STAGING_DB if args.staging else PROD_DB
    if not os.path.exists(db_path):
        raise SystemExit(f"DB does not exist: {db_path}")

    filer_ciks: set[str] | None = None
    if args.filer_cik:
        filer_ciks = {args.filer_cik.strip().zfill(10)}

    t0 = datetime.now(timezone.utc)
    print(f"enrich_13dg.py  started_at={t0.isoformat(timespec='seconds')}  "
          f"db={db_path}  dry_run={args.dry_run}  "
          f"scope={'full' if filer_ciks is None else sorted(filer_ciks)}")

    con = duckdb.connect(db_path, read_only=args.dry_run)
    try:
        # Tables absent on staging today — SKIP cleanly.
        present = con.execute(
            "SELECT 1 FROM duckdb_tables() "
            "WHERE table_name = 'beneficial_ownership_v2'"
        ).fetchone()
        if not present:
            print("  SKIP: beneficial_ownership_v2 does not exist on this DB")
            return

        cov_before = _coverage(con)
        _print_coverage("BEFORE", cov_before)

        deltas = _predict_deltas(con, filer_ciks)
        _print_deltas(deltas)

        if args.dry_run:
            print("  DRY-RUN — no writes. Re-run without --dry-run to apply.")
            return

        enriched = bulk_enrich_bo_filers(con, filer_ciks=filer_ciks)
        con.execute("CHECKPOINT")
        print(f"  bulk_enrich_bo_filers: {enriched:+,} entity_id delta")

        cur_rows = rebuild_beneficial_ownership_current(con)
        con.execute("CHECKPOINT")
        print(f"  beneficial_ownership_current rebuilt: {cur_rows:,} rows")

        cov_after = _coverage(con)
        # beneficial_ownership_v2_enrichment is a logical label, not a
        # table — pass an explicit row_count (rows with resolved entity)
        # so record_freshness does not try to COUNT(*) a missing table.
        stamp_freshness(
            con,
            "beneficial_ownership_v2_enrichment",
            row_count=cov_after["with_entity_id"],
        )
        stamp_freshness(con, "beneficial_ownership_current")

        _print_coverage("AFTER", cov_after)
    finally:
        con.close()

    if not args.dry_run and not args.staging:
        refresh_snapshot()

    t1 = datetime.now(timezone.utc)
    print(f"DONE  enrich_13dg  elapsed={(t1 - t0).total_seconds():.1f}s")


if __name__ == "__main__":
    main()
