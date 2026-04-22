#!/usr/bin/env python3
"""
normalize_securities.py — port cusip_classifications → securities.

Populates 7 new ``securities`` columns from ``cusip_classifications``:
    canonical_type, canonical_type_source,
    is_equity, is_priceable, ticker_expected, is_active, figi

Also refreshes ``securities.ticker`` / ``exchange`` / ``market_sector``
with COALESCE(cc.*, s.*) so new OpenFIGI data lands without clobbering
existing manual overrides.

Rows in ``cusip_classifications`` that aren't yet in ``securities`` (13D/G-
only CUSIPs are the main source) get inserted with the minimal column
set. This script is safe to re-run — uses UPDATE + LEFT-JOIN INSERT, no
DROP+CREATE.

Usage:
    python3 scripts/normalize_securities.py               # prod
    python3 scripts/normalize_securities.py --staging
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

import duckdb

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

from db import PROD_DB, STAGING_DB  # noqa: E402


UPDATE_SQL = """
UPDATE securities s
SET
    canonical_type        = cc.canonical_type,
    canonical_type_source = cc.canonical_type_source,
    is_equity             = cc.is_equity,
    is_priceable          = cc.is_priceable,
    is_otc                = cc.is_otc,
    ticker_expected       = cc.ticker_expected,
    is_active             = cc.is_active,
    figi                  = COALESCE(cc.figi, s.figi),
    ticker                = COALESCE(cc.ticker, s.ticker),
    exchange              = COALESCE(cc.exchange, s.exchange),
    market_sector         = COALESCE(cc.market_sector, s.market_sector),
    issuer_name           = COALESCE(cc.issuer_name, s.issuer_name)
FROM cusip_classifications cc
WHERE s.cusip = cc.cusip
"""

INSERT_MISSING_SQL = """
INSERT INTO securities (
    cusip, issuer_name, ticker, security_type, exchange, market_sector,
    canonical_type, canonical_type_source,
    is_equity, is_priceable, is_otc, ticker_expected, is_active, figi,
    holdings_count, total_value, is_energy, is_media
)
SELECT
    cc.cusip, cc.issuer_name, cc.ticker, cc.raw_type_mode,
    cc.exchange, cc.market_sector,
    cc.canonical_type, cc.canonical_type_source,
    cc.is_equity, cc.is_priceable, cc.is_otc, cc.ticker_expected, cc.is_active,
    cc.figi,
    0, 0, FALSE, FALSE
FROM cusip_classifications cc
LEFT JOIN securities s ON cc.cusip = s.cusip
WHERE s.cusip IS NULL
"""


def normalize(con) -> dict:
    before = con.execute("SELECT COUNT(*) FROM securities").fetchone()[0]

    con.execute("BEGIN")
    try:
        con.execute(UPDATE_SQL)
        con.execute(INSERT_MISSING_SQL)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    con.execute("CHECKPOINT")

    after = con.execute("SELECT COUNT(*) FROM securities").fetchone()[0]

    coverage = con.execute(
        """
        SELECT
            COUNT(*)                       AS total,
            COUNT(canonical_type)          AS has_canonical,
            COUNT(is_equity)               AS has_equity,
            COUNT(figi)                    AS has_figi,
            ROUND(COUNT(canonical_type)*100.0/NULLIF(COUNT(*),0), 2) AS pct_canonical,
            ROUND(COUNT(figi)*100.0/NULLIF(COUNT(*),0),            2) AS pct_figi
        FROM securities
        """
    ).fetchdf()

    # Sanity: any securities row still missing canonical_type?
    orphans = con.execute(
        "SELECT COUNT(*) FROM securities WHERE canonical_type IS NULL"
    ).fetchone()[0]

    print(f"securities rows: {before:,} → {after:,} (+{after - before:,})")
    print(coverage.to_string(index=False))
    print(f"Rows missing canonical_type: {orphans:,}")
    return {
        'before': before,
        'after': after,
        'orphans_missing_canonical': orphans,
        'coverage': coverage.to_dict('records')[0],
    }


def main() -> None:
    p = argparse.ArgumentParser(description="Port classifications → securities")
    p.add_argument("--staging", action="store_true",
                   help="Write to staging DB")
    args = p.parse_args()

    db = STAGING_DB if args.staging else PROD_DB
    print("normalize_securities.py")
    print("=" * 60)
    print(f"  DB: {db}")
    print()

    con = duckdb.connect(db)
    try:
        try:
            con.execute("SELECT 1 FROM cusip_classifications LIMIT 1")
        except Exception as exc:
            print(f"ERROR: cusip_classifications missing from {db}. "
                  f"Run Migration 003 first. ({exc})")
            sys.exit(1)
        normalize(con)
    finally:
        con.close()

    # BLOCK-TICKER-BACKFILL: re-stamp historical fund_holdings_v2.ticker on
    # securities mapping changes. Pass C in enrich_holdings.py is
    # is_priceable-gated (commit db27cbd). Subprocess pattern (not inline
    # import) is resilient to future REWRITE refactors of enrich_holdings.py.
    cmd = [sys.executable, "scripts/enrich_holdings.py", "--fund-holdings"]
    if args.staging:
        cmd.append("--staging")
    try:
        subprocess.run(cmd, cwd=BASE_DIR, check=False, timeout=1800)
        print("  [hook] post-build ticker backfill triggered", flush=True)
    except Exception as e:
        print(f"  [warn] post-build ticker backfill hook failed: {e}", flush=True)


if __name__ == "__main__":
    main()
