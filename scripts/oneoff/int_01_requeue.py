#!/usr/bin/env python3
"""
int_01_requeue.py — re-queue CUSIPs carrying pre-fix foreign-exchange
selections so they can be re-resolved through the RC1-patched OpenFIGI
selector.

Background: commit bcc5867 added a US-preferred listing selector to the
OpenFIGI match path (`scripts/build_cusip.py`, `scripts/run_openfigi_retry.py`).
CUSIPs resolved before that commit may still carry `exchange` values like
GR/GF/GM/FF/GA/EU/EO/GY/GS even though a US-priceable listing exists in
the OpenFIGI response. Phase 0 findings
(docs/findings/int-01-p0-findings.md) identified ~216 such rows.

This one-shot script identifies affected CUSIPs in
``cusip_classifications`` and re-queues them in ``cusip_retry_queue``:
  * rows already in the queue → reset to ``status='pending'``,
    ``attempt_count=0``, ``last_error=NULL``.
  * rows not yet in the queue → INSERT with ``status='pending'``.

Running this script does NOT call OpenFIGI. The retry itself is executed
by ``scripts/run_openfigi_retry.py`` in a separately-authorized step.

Usage:
    python3 scripts/oneoff/int_01_requeue.py --dry-run        # preview
    python3 scripts/oneoff/int_01_requeue.py                  # prod
    python3 scripts/oneoff/int_01_requeue.py --staging        # staging
"""
from __future__ import annotations

import argparse
import os
import sys

import duckdb

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

from db import PROD_DB, STAGING_DB  # noqa: E402


# exchCodes carried on CUSIPs that pre-date the RC1 US-preferred selector.
# Matches Phase 0 findings (docs/findings/int-01-p0-findings.md §4).
FOREIGN_EXCHANGES = ('GR', 'GF', 'GM', 'FF', 'GA', 'EU', 'EO', 'GY', 'GS')

AFFECTED_SQL = f"""
    SELECT cusip, issuer_name, canonical_type
    FROM cusip_classifications
    WHERE ticker IS NOT NULL
      AND canonical_type IN ('COM','ETF','PFD','ADR')
      AND ticker_source = 'openfigi'
      AND exchange IN {FOREIGN_EXCHANGES}
"""


def requeue(con: duckdb.DuckDBPyConnection, dry_run: bool) -> dict:
    affected = con.execute(AFFECTED_SQL).fetchall()
    affected_cusips = [row[0] for row in affected]
    if not affected_cusips:
        return {"affected": 0, "updated": 0, "inserted": 0}

    existing = {
        row[0]
        for row in con.execute(
            "SELECT cusip FROM cusip_retry_queue WHERE cusip IN ({})".format(
                ",".join("?" * len(affected_cusips))
            ),
            affected_cusips,
        ).fetchall()
    }
    to_update = [c for c in affected_cusips if c in existing]
    to_insert = [row for row in affected if row[0] not in existing]

    if dry_run:
        return {
            "affected": len(affected_cusips),
            "updated": len(to_update),
            "inserted": len(to_insert),
        }

    if to_update:
        con.execute(
            """
            UPDATE cusip_retry_queue
            SET status = 'pending',
                attempt_count = 0,
                last_error = NULL,
                updated_at = NOW()
            WHERE cusip IN ({})
            """.format(",".join("?" * len(to_update))),
            to_update,
        )

    if to_insert:
        con.executemany(
            """
            INSERT INTO cusip_retry_queue
                (cusip, issuer_name, canonical_type, status, attempt_count)
            VALUES (?, ?, ?, 'pending', 0)
            """,
            to_insert,
        )

    return {
        "affected": len(affected_cusips),
        "updated": len(to_update),
        "inserted": len(to_insert),
    }


def main() -> None:
    p = argparse.ArgumentParser(description="Re-queue RC1-affected CUSIPs")
    p.add_argument("--staging", action="store_true",
                   help="Use staging DB (default: prod)")
    p.add_argument("--dry-run", action="store_true",
                   help="Report counts without writing")
    args = p.parse_args()

    db = STAGING_DB if args.staging else PROD_DB
    print("int_01_requeue.py — re-queue RC1-affected CUSIPs")
    print("=" * 60)
    print(f"  DB:        {db}")
    print(f"  mode:      {'DRY RUN' if args.dry_run else 'WRITE'}")
    print()

    con = duckdb.connect(db, read_only=args.dry_run)
    try:
        try:
            con.execute("SELECT 1 FROM cusip_retry_queue LIMIT 1")
        except Exception as exc:
            print(f"ERROR: cusip_retry_queue missing from {db}. ({exc})")
            sys.exit(1)

        summary = requeue(con, dry_run=args.dry_run)
    finally:
        con.close()

    prefix = "Would re-queue" if args.dry_run else "Re-queued"
    print(
        f"{prefix} {summary['affected']} CUSIPs "
        f"({summary['updated']} updated, {summary['inserted']} inserted)"
    )


if __name__ == "__main__":
    main()
