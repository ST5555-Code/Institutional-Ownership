#!/usr/bin/env python3
"""
fix_permanent_pending.py — one-off sweep for INF26 permanent-pending rows.

Background: before int-10, ``run_openfigi_retry.py::_update_error()`` bumped
``cusip_retry_queue.attempt_count`` on HTTP errors without transitioning
``status`` to a terminal state. Rows that exhausted ``MAX_ATTEMPTS=3`` via
HTTP errors landed at ``status='pending' AND attempt_count >= 3`` — silently
skipped by the retry selector forever.

Phase 0 findings (docs/findings/int-10-p0-findings.md §3):
  * prod:    0 such rows (bug latent, sweep is a no-op / drift check)
  * staging: 81 such rows (all at attempt_count=3)

This script flips those rows to ``status='unmappable'`` and annotates
``notes`` for forensics. Idempotent: re-running after the sweep affects
zero rows.

Usage:
    python3 scripts/oneoff/fix_permanent_pending.py                    # prod, DRY RUN
    python3 scripts/oneoff/fix_permanent_pending.py --staging          # staging, DRY RUN
    python3 scripts/oneoff/fix_permanent_pending.py --staging --confirm  # WRITE
"""
from __future__ import annotations

import argparse
import os
import sys

import duckdb

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

from db import PROD_DB, STAGING_DB  # noqa: E402
from pipeline.cusip_classifier import MAX_ATTEMPTS  # noqa: E402


FIND_SQL = f"""
    SELECT COUNT(*)
    FROM cusip_retry_queue
    WHERE status = 'pending'
      AND attempt_count >= {MAX_ATTEMPTS}
"""

SWEEP_SQL = f"""
    UPDATE cusip_retry_queue
    SET status     = 'unmappable',
        updated_at = NOW(),
        notes      = COALESCE(notes || ' | ', '') ||
                     'int-10 sweep: http-error exhausted MAX_ATTEMPTS'
    WHERE status = 'pending'
      AND attempt_count >= {MAX_ATTEMPTS}
"""


def main() -> None:
    p = argparse.ArgumentParser(
        description="Flip INF26 permanent-pending rows to 'unmappable'"
    )
    p.add_argument("--staging", action="store_true",
                   help="Target staging DB (default: prod)")
    p.add_argument("--confirm", action="store_true",
                   help="Execute the UPDATE (default: DRY RUN)")
    args = p.parse_args()

    db = STAGING_DB if args.staging else PROD_DB
    mode = "WRITE" if args.confirm else "DRY RUN"

    print("fix_permanent_pending.py — INF26 one-off sweep")
    print("=" * 60)
    print(f"  DB:   {db}")
    print(f"  mode: {mode}")
    print()

    con = duckdb.connect(db, read_only=not args.confirm)
    try:
        try:
            con.execute("SELECT 1 FROM cusip_retry_queue LIMIT 1")
        except Exception as exc:
            print(f"ERROR: cusip_retry_queue missing from {db}. ({exc})")
            sys.exit(1)

        found = con.execute(FIND_SQL).fetchone()[0]
        print(f"Rows matching status='pending' AND attempt_count >= "
              f"{MAX_ATTEMPTS}: {found}")

        if not args.confirm:
            print("\nDRY RUN — no writes. Re-run with --confirm to apply.")
            print(f"Summary: found={found} updated=0")
            return

        if found == 0:
            print("\nNothing to do (0 rows match). Clean exit.")
            print("Summary: found=0 updated=0")
            return

        con.execute(SWEEP_SQL)
        con.execute("CHECKPOINT")
    finally:
        con.close()

    print(f"\nSummary: found={found} updated={found}")


if __name__ == "__main__":
    main()
