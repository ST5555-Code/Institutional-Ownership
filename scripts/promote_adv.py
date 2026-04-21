#!/usr/bin/env python3
# CHECKPOINT GRANULARITY POLICY
# promote_adv.py unit: one run_id (one ADV bulk ZIP parse).
# The whole write sequence is wrapped in one explicit BEGIN TRANSACTION /
# COMMIT / ROLLBACK boundary. Manifest + impacts mirror, adv_managers
# DELETE+INSERT, and the impacts UPDATE all roll back together on any
# failure. A single CHECKPOINT runs after COMMIT (DuckDB rejects
# CHECKPOINT inside a transaction).
"""promote_adv.py — staging → prod for SEC bulk ADV data.

Runs after fetch_adv.py stages to data/13f_staging.duckdb. ADV is a
whole-table refresh — there is no incremental path — so the promote
replaces prod adv_managers with the staged universe in one transaction.

Usage:
  python3 scripts/promote_adv.py --run-id <adv_YYYYmmdd_HHMMSS_xxxxxx>
"""
from __future__ import annotations

import argparse
import os
import sys

import duckdb

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

from db import PROD_DB, STAGING_DB, record_freshness  # noqa: E402
from pipeline.manifest import mirror_manifest_and_impacts  # noqa: E402
from pipeline.shared import refresh_snapshot  # noqa: E402


def _update_impacts(prod_con, run_id: str) -> int:
    prod_con.execute(
        """
        UPDATE ingestion_impacts
           SET promote_status = 'promoted',
               rows_promoted  = rows_staged,
               promoted_at    = CURRENT_TIMESTAMP
         FROM ingestion_manifest m
         WHERE ingestion_impacts.manifest_id = m.manifest_id
           AND m.run_id = ?
           AND m.source_type = 'ADV'
           AND ingestion_impacts.promote_status = 'pending'
        """,
        [run_id],
    )
    return prod_con.execute(
        """
        SELECT COUNT(*) FROM ingestion_impacts i
         JOIN ingestion_manifest m ON m.manifest_id = i.manifest_id
         WHERE m.run_id = ? AND i.promote_status = 'promoted'
        """,
        [run_id],
    ).fetchone()[0]


def main() -> None:
    parser = argparse.ArgumentParser(description="Promote ADV staging → prod")
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()

    staging_con = duckdb.connect(STAGING_DB, read_only=True)
    prod_con = duckdb.connect(PROD_DB)
    try:
        # Migration 001 must have run on prod (same guard as 13dg/nport).
        try:
            prod_con.execute("SELECT 1 FROM ingestion_manifest LIMIT 1")
        except duckdb.CatalogException as exc:
            raise SystemExit(
                "ingestion_manifest not present in prod — run migration 001 first"
            ) from exc

        # Verify staging has rows for this run_id before touching prod.
        staged_count = staging_con.execute(
            "SELECT COUNT(*) FROM adv_managers"
        ).fetchone()[0]
        if staged_count == 0:
            raise SystemExit(
                f"staging adv_managers is empty — aborting promote for {args.run_id}"
            )

        manifest_rows = staging_con.execute(
            "SELECT COUNT(*) FROM ingestion_manifest "
            "WHERE run_id = ? AND source_type = 'ADV'",
            [args.run_id],
        ).fetchone()[0]
        if manifest_rows == 0:
            raise SystemExit(
                f"No staging manifest row for run_id={args.run_id} "
                "(source_type=ADV) — did fetch_adv.py complete?"
            )

        prod_con.execute("BEGIN TRANSACTION")
        try:
            manifest_ids, impacts_inserted = mirror_manifest_and_impacts(
                prod_con, staging_con, args.run_id, "ADV",
            )
            print(
                f"  manifest mirrored: {len(manifest_ids)} manifest rows, "
                f"{impacts_inserted} impact rows inserted"
            )

            # Whole-table replace. ADV has no partitioning grain — one run
            # re-parses the full SEC bulk ZIP, so the correct semantics is
            # "replace the prior universe". ATTACH avoids a pandas
            # round-trip for the ~16.6K row copy.
            prod_con.execute(f"ATTACH '{STAGING_DB}' AS stg (READ_ONLY)")
            try:
                deleted = prod_con.execute(
                    "SELECT COUNT(*) FROM adv_managers"
                ).fetchone()[0]
                prod_con.execute("DELETE FROM adv_managers")
                prod_con.execute(
                    "INSERT INTO adv_managers SELECT * FROM stg.adv_managers"
                )
                inserted = prod_con.execute(
                    "SELECT COUNT(*) FROM adv_managers"
                ).fetchone()[0]
            finally:
                prod_con.execute("DETACH stg")

            print(f"  adv_managers: -{deleted} +{inserted}")

            promoted = _update_impacts(prod_con, args.run_id)
            print(f"  ingestion_impacts promoted: {promoted}")

            prod_con.execute("COMMIT")
        except Exception:
            prod_con.execute("ROLLBACK")
            raise

        # Freshness + CHECKPOINT run outside the transaction. DuckDB
        # rejects CHECKPOINT inside one; record_freshness is recoverable
        # metadata. Guarded try/except matches obs-02's pattern.
        try:
            record_freshness(prod_con, "adv_managers", row_count=inserted)
        except Exception as e:
            print(f"  [warn] record_freshness(adv_managers) failed: {e}", flush=True)
        prod_con.execute("CHECKPOINT")

        print(f"DONE  adv_managers -{deleted} +{inserted}")
    finally:
        staging_con.close()
        prod_con.close()

    refresh_snapshot()
    print("DONE  promote_adv")


if __name__ == "__main__":
    main()
