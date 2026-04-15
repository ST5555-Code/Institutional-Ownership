#!/usr/bin/env python3
"""check_freshness.py — status/gate helper for the quarterly pipeline.

Two modes:
  * default         — prints status table and exits 1 if any tracked table
                      is stale beyond its threshold, missing from
                      data_freshness, or untracked. Used by `make freshness`
                      as a CI-style gate.
  * --status-only   — prints the same table but always exits 0. Used by
                      `make status` for an informational snapshot.

Opens the production DB read-only; safe to run while staging is write-locked.
"""

import argparse
import os
import sys
from datetime import datetime

import duckdb

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "data", "13f.duckdb")

# Staleness thresholds (days). Match the SLAs documented in
# ARCHITECTURE_REVIEW.md §3-A and the operational cadence of each
# upstream refresh.
THRESHOLDS = {
    "holdings_v2":                  95,
    "fund_holdings_v2":             95,
    "investor_flows":               95,
    "ticker_flow_stats":            14,
    "market_data":                  7,
    "summary_by_parent":            95,
    "beneficial_ownership_current": 95,
}


def fetch_freshness(con):
    try:
        rows = con.execute(
            "SELECT table_name, last_computed_at, row_count FROM data_freshness"
        ).fetchall()
    except duckdb.CatalogException:
        print("ERROR — data_freshness table does not exist in this DB.",
              file=sys.stderr)
        sys.exit(2)
    return {r[0]: (r[1], r[2]) for r in rows}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--status-only", action="store_true",
                    help="print status table and exit 0 regardless of freshness")
    args = ap.parse_args()

    con = duckdb.connect(DB_PATH, read_only=True)
    tracked = fetch_freshness(con)
    con.close()

    now = datetime.utcnow()
    any_stale = False

    print(f"{'Table':<34} {'Last Updated':<22} {'Rows':>12} {'Age':>6}  Status")
    print("-" * 86)

    for table, max_days in THRESHOLDS.items():
        if table not in tracked:
            print(f"{table:<34} {'NOT IN data_freshness':<22} "
                  f"{'--':>12} {'--':>6}  MISSING")
            any_stale = True
            continue
        last, row_count = tracked[table]
        # last_computed_at is a datetime per DuckDB TIMESTAMP → timedelta math works.
        age_days = (now - last).days
        stale = age_days > max_days
        if stale:
            any_stale = True
        status = "STALE" if stale else "OK"
        rc = f"{row_count:,}" if row_count is not None else "--"
        print(f"{table:<34} {str(last)[:19]:<22} {rc:>12} "
              f"{age_days:>5}d  {status}")

    # Surface any other tables that the pipeline happened to stamp but
    # that we aren't gating on — useful for seeing spot checks without
    # editing THRESHOLDS.
    extras = sorted(set(tracked) - set(THRESHOLDS))
    if extras:
        print()
        print("Other tables present in data_freshness (not gated):")
        for t in extras:
            last, rc = tracked[t]
            rc_fmt = f"{rc:,}" if rc is not None else "--"
            print(f"  {t:<32} {str(last)[:19]:<22} {rc_fmt:>12}")

    print()
    if any_stale:
        print("FAIL — one or more critical tables are stale or untracked.")
        if args.status_only:
            print("(--status-only: exit 0 regardless)")
            sys.exit(0)
        sys.exit(1)
    print("PASS — all critical tables are fresh.")
    sys.exit(0)


if __name__ == "__main__":
    main()
