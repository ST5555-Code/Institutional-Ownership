#!/usr/bin/env python3
"""queue_nport_excluded.py — persist N-PORT excluded series into
``pending_entity_resolution``.

Split out of ``scripts/validate_nport_subset.py`` in sec-04-p1 so the
validator can stay read-only against prod. This script does the INSERT
+ CHECKPOINT against prod.

Reads a plain-text file with one series_id per line (the same
``--excluded-file`` consumed by the subset validator) and upserts each
entry into ``pending_entity_resolution`` with:
  - ``source_type = 'NPORT'``
  - ``identifier_type = 'series_id'``
  - ``identifier_value = <series_id>``
  - ``resolution_status = 'pending'``
  - ``pending_key = 'series_id:' || <series_id>``

``ON CONFLICT (pending_key) DO NOTHING`` keeps the script idempotent
across re-runs — a subsequent queue pass on the same excluded list is a
no-op for already-queued series.

Usage (after running validate_nport_subset.py):
    python3 scripts/queue_nport_excluded.py \\
        --excluded-file logs/nport_excluded_<run_id>.txt

    # Preview only, no writes:
    python3 scripts/queue_nport_excluded.py \\
        --excluded-file logs/nport_excluded_<run_id>.txt --dry-run
"""
from __future__ import annotations

import argparse
import os
import sys

import duckdb

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

from db import PROD_DB  # noqa: E402


def _read_list(path: str) -> list[str]:
    with open(path) as fh:
        return sorted({line.strip() for line in fh if line.strip()})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--excluded-file", required=True,
        help="File with one series_id per line — these get upserted into "
             "pending_entity_resolution.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Report what would be queued (including how many are already "
             "present) without writing.",
    )
    args = parser.parse_args()

    excluded = _read_list(args.excluded_file)
    print(f"excluded series in file: {len(excluded):,}")
    if not excluded:
        print("nothing to queue — empty excluded list")
        return 0

    if args.dry_run:
        con = duckdb.connect(PROD_DB, read_only=True)
    else:
        con = duckdb.connect(PROD_DB)

    try:
        import pandas as pd
        exc_df = pd.DataFrame({"series_id": excluded})
        con.register("excluded_df", exc_df)

        already = con.execute(
            """
            SELECT COUNT(*)
            FROM pending_entity_resolution p
            JOIN excluded_df e
              ON p.pending_key = 'series_id:' || e.series_id
            """
        ).fetchone()[0]
        to_insert = len(excluded) - already
        print(f"already queued:          {already:,}")
        print(f"would insert:            {to_insert:,}")

        if args.dry_run:
            print("dry-run — no writes performed")
            con.unregister("excluded_df")
            return 0

        con.execute(
            """
            INSERT INTO pending_entity_resolution
                (manifest_id, source_type, identifier_type, identifier_value,
                 resolution_status, pending_key)
            SELECT NULL, 'NPORT', 'series_id', e.series_id, 'pending',
                   'series_id:' || e.series_id
            FROM excluded_df e
            ON CONFLICT (pending_key) DO NOTHING
            """
        )
        con.unregister("excluded_df")
        con.execute("CHECKPOINT")
        print(f"queued: {to_insert:,} new series_ids into "
              f"pending_entity_resolution (idempotent via ON CONFLICT)")
    finally:
        con.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
