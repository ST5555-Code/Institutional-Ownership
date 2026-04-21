#!/usr/bin/env python3
"""obs-04 Phase 1 — backfill ingestion_manifest + ingestion_impacts for the
51,902 BO v2 accessions loaded before fetch_13dg_v2.py existed.

The three existing ingestion_impacts rows (impact_id 191/192/193, manifest_id
8/9/10) are at the correct filer_subject_accession grain and stay in place.
This one-off closes MAJOR-8 D-06 by inserting parent ingestion_manifest rows
plus per-accession ingestion_impacts rows for every beneficial_ownership_v2
row that currently has no lineage.

Design: docs/findings/obs-04-p0-findings.md (branch obs-04-p0, §5 pseudocode).

Single-shot, idempotent by design — the orphan query uses an anti-join on
ingestion_manifest.object_key, so a re-run after success writes zero rows.
All inserts are inside a single BEGIN/COMMIT transaction.

Usage:
    python3 scripts/oneoff/backfill_13dg_impacts.py --dry-run     # preview
    python3 scripts/oneoff/backfill_13dg_impacts.py --confirm     # write prod
    python3 scripts/oneoff/backfill_13dg_impacts.py --staging --confirm

Explicit --confirm is required to write. Invoking with no flags prints the
orphan count and exits without touching the DB.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import duckdb

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

from db import PROD_DB, STAGING_DB  # noqa: E402
from pipeline.id_allocator import reserve_ids  # noqa: E402

RUN_ID = "13dg_backfill_obs04_20260421"


ORPHAN_SQL = """
    SELECT DISTINCT bo.accession_number,
                    bo.filer_cik,
                    bo.subject_cusip,
                    bo.filing_date,
                    bo.loaded_at,
                    bo.is_amendment,
                    bo.prior_accession,
                    bo.report_date
      FROM beneficial_ownership_v2 bo
      LEFT JOIN ingestion_manifest m
        ON m.source_type = '13DG'
       AND m.object_key = bo.accession_number
     WHERE m.manifest_id IS NULL
"""


def backfill(con: duckdb.DuckDBPyConnection, dry_run: bool) -> dict:
    pre_impacts = con.execute(
        """
        SELECT COUNT(*) FROM ingestion_impacts ii
          JOIN ingestion_manifest m ON m.manifest_id = ii.manifest_id
         WHERE m.source_type = '13DG'
        """
    ).fetchone()[0]
    bo_total = con.execute(
        "SELECT COUNT(*) FROM beneficial_ownership_v2"
    ).fetchone()[0]

    orphans = con.execute(ORPHAN_SQL).fetchdf()
    n = len(orphans)
    print(f"  beneficial_ownership_v2 rows:        {bo_total:,}")
    print(f"  ingestion_impacts 13DG (pre):        {pre_impacts:,}")
    print(f"  orphan accessions to backfill:       {n:,}")

    if n == 0:
        print("Nothing to backfill.")
        return {
            "orphans": 0,
            "manifest_inserted": 0,
            "impacts_inserted": 0,
            "pre_impacts": pre_impacts,
            "post_impacts": pre_impacts,
        }

    if dry_run:
        print("DRY RUN — no writes performed.")
        return {
            "orphans": n,
            "manifest_inserted": 0,
            "impacts_inserted": 0,
            "pre_impacts": pre_impacts,
            "post_impacts": pre_impacts,
        }

    con.execute("BEGIN TRANSACTION")
    try:
        # Re-run the orphan query inside the transaction in case a concurrent
        # fetch landed a new manifest row between the read above and now.
        orphans = con.execute(ORPHAN_SQL).fetchdf()
        n = len(orphans)
        if n == 0:
            con.execute("ROLLBACK")
            print("Nothing to backfill (post-BEGIN re-check).")
            return {
                "orphans": 0,
                "manifest_inserted": 0,
                "impacts_inserted": 0,
                "pre_impacts": pre_impacts,
                "post_impacts": pre_impacts,
            }

        mf_ids = list(reserve_ids(con, "ingestion_manifest", "manifest_id", n))
        mf = orphans[[
            "accession_number", "filing_date", "loaded_at",
            "is_amendment", "prior_accession",
        ]].copy()
        mf["manifest_id"] = mf_ids
        mf["source_type"] = "13DG"
        mf["object_type"] = "TXT"
        mf["object_key"] = mf["accession_number"]
        mf["source_url"] = None
        mf["run_id"] = RUN_ID
        mf["fetch_status"] = "complete"
        mf["fetch_completed_at"] = mf["loaded_at"]
        mf["accepted_at"] = mf["loaded_at"]
        mf["retry_count"] = 0

        con.register("mf_df", mf)
        con.execute(
            """
            INSERT INTO ingestion_manifest
                (manifest_id, source_type, object_type, object_key,
                 source_url, accession_number, filing_date,
                 accepted_at, run_id, fetch_completed_at,
                 fetch_status, is_amendment, prior_accession,
                 retry_count)
            SELECT manifest_id, source_type, object_type, object_key,
                   source_url, accession_number, filing_date,
                   accepted_at, run_id, fetch_completed_at,
                   fetch_status, is_amendment, prior_accession,
                   retry_count
              FROM mf_df
            """
        )
        con.unregister("mf_df")

        ii_ids = list(reserve_ids(con, "ingestion_impacts", "impact_id", n))
        ii = orphans.copy()
        ii["impact_id"] = ii_ids
        ii["manifest_id"] = mf_ids  # aligned order — same row index
        ii["target_table"] = "beneficial_ownership_v2"
        ii["unit_type"] = "filer_subject_accession"
        ii["unit_key_json"] = ii.apply(
            lambda r: json.dumps({
                "filer_cik": r["filer_cik"],
                "subject_cusip": r["subject_cusip"],
                "accession_number": r["accession_number"],
            }),
            axis=1,
        )
        ii["rows_staged"] = 1
        ii["rows_promoted"] = 1
        ii["load_status"] = "loaded"
        ii["promote_status"] = "promoted"
        ii["promoted_at"] = ii["loaded_at"]

        con.register("ii_df", ii)
        con.execute(
            """
            INSERT INTO ingestion_impacts
                (impact_id, manifest_id, target_table, unit_type,
                 unit_key_json, report_date, rows_staged,
                 rows_promoted, load_status, promote_status,
                 promoted_at)
            SELECT impact_id, manifest_id, target_table, unit_type,
                   unit_key_json, report_date, rows_staged,
                   rows_promoted, load_status, promote_status,
                   promoted_at
              FROM ii_df
            """
        )
        con.unregister("ii_df")

        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise

    con.execute("CHECKPOINT")

    post_impacts = con.execute(
        """
        SELECT COUNT(*) FROM ingestion_impacts ii
          JOIN ingestion_manifest m ON m.manifest_id = ii.manifest_id
         WHERE m.source_type = '13DG'
        """
    ).fetchone()[0]

    return {
        "orphans": n,
        "manifest_inserted": n,
        "impacts_inserted": n,
        "pre_impacts": pre_impacts,
        "post_impacts": post_impacts,
    }


def main() -> None:
    p = argparse.ArgumentParser(
        description="obs-04 Phase 1 — backfill 13D/G manifest + impact rows",
    )
    p.add_argument("--staging", action="store_true",
                   help="Use staging DB (default: prod)")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true",
                      help="Report counts without writing (default if --confirm absent)")
    mode.add_argument("--confirm", action="store_true",
                      help="Required to actually write to the DB")
    args = p.parse_args()

    # Require explicit invocation: with no flags, behave like --dry-run.
    dry_run = args.dry_run or not args.confirm

    db = STAGING_DB if args.staging else PROD_DB
    print("backfill_13dg_impacts.py — obs-04 Phase 1")
    print("=" * 60)
    print(f"  DB:        {db}")
    print(f"  run_id:    {RUN_ID}")
    print(f"  mode:      {'DRY RUN' if dry_run else 'WRITE'}")
    print()

    con = duckdb.connect(db, read_only=dry_run)
    try:
        summary = backfill(con, dry_run=dry_run)
    finally:
        con.close()

    print()
    print("Summary")
    print("-" * 60)
    print(f"  orphans identified:     {summary['orphans']:,}")
    print(f"  manifest rows inserted: {summary['manifest_inserted']:,}")
    print(f"  impact rows inserted:   {summary['impacts_inserted']:,}")
    print(f"  ingestion_impacts 13DG: {summary['pre_impacts']:,} -> {summary['post_impacts']:,}")
    if not dry_run and summary["orphans"] > 0:
        delta = summary["post_impacts"] - summary["pre_impacts"]
        assert delta == summary["impacts_inserted"], (
            f"post-delta {delta} != inserted {summary['impacts_inserted']}"
        )


if __name__ == "__main__":
    main()
