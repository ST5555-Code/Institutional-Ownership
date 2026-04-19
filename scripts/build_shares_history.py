#!/usr/bin/env python3
"""
build_shares_history.py — Populate `shares_outstanding_history` table from SEC XBRL.

For every ticker with a CIK mapping, pulls ALL historical
EntityCommonStockSharesOutstanding / CommonStockSharesOutstanding facts from
the local SEC companyfacts cache (refresh via fetch_market.py --sec-only).

The resulting table is the canonical period-accurate share-count source.
Consumers matching a holding's `report_date` to the most recent XBRL fact
on-or-before that date (e.g. via DuckDB ASOF JOIN) get a denominator that
respects splits, buybacks, and offerings between report_date and today.

Writer discipline note: this script is the sole writer of
`shares_outstanding_history`. The historical `update_holdings_pct_of_float`
path that wrote `holdings.pct_of_float` via ASOF JOIN was retired in the
2026-04-19 rewrite after the `holdings` table was dropped at Stage 5.
Period-accurate `pct_of_float` restoration is tracked separately under
BLOCK-PCT-OF-FLOAT-PERIOD-ACCURACY (move ASOF into `enrich_holdings.py`).

Usage:
    python3 scripts/build_shares_history.py [--staging]

Flags:
    --staging            Write to staging DB instead of production
"""

import argparse
import os
import sys
import time
# from datetime import datetime  # unused

import duckdb

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

from db import set_staging_mode, is_staging_mode, get_db_path, connect_read  # noqa: E402
from sec_shares_client import SECSharesClient  # noqa: E402


SCHEMA = """
CREATE TABLE IF NOT EXISTS shares_outstanding_history (
    ticker      VARCHAR NOT NULL,
    cik         VARCHAR,
    as_of_date  DATE NOT NULL,
    shares      BIGINT NOT NULL,
    form        VARCHAR,
    filed_date  DATE,
    source_tag  VARCHAR,
    PRIMARY KEY (ticker, as_of_date)
)
"""


def build(con, client: SECSharesClient):
    # Source of tickers: everything in market_data that has either a CIK (SEC
    # resolved) or could potentially resolve. Read from prod when in staging
    # mode so holdings stays the source of truth.
    read_con = connect_read() if is_staging_mode() else con
    tickers = read_con.execute("""
        SELECT DISTINCT ticker FROM market_data
        WHERE (unfetchable IS NULL OR unfetchable = FALSE)
    """).fetchdf()["ticker"].tolist()
    print(f"  Candidate tickers: {len(tickers):,}")

    con.execute(SCHEMA)

    total_rows = 0
    with_history = 0
    no_cik = 0
    t0 = time.time()

    batch = []
    BATCH = 1000

    for i, tkr in enumerate(tickers, 1):
        history = client.fetch_history(tkr)
        if not history:
            if client.get_cik(tkr) is None:
                no_cik += 1
            continue
        with_history += 1
        for row in history:
            filed = row.get("filed")
            batch.append((
                row["ticker"],
                row.get("cik"),
                row["as_of_date"],
                row["shares"],
                row.get("form"),
                filed,
                row.get("source_tag"),
            ))
        total_rows += len(history)

        if len(batch) >= BATCH:
            _upsert_batch(con, batch)
            batch.clear()

        if i % 500 == 0:
            print(f"    [{i:,}/{len(tickers):,}] with_history={with_history:,} total_rows={total_rows:,}")

    if batch:
        _upsert_batch(con, batch)

    dt = time.time() - t0
    print(f"\n  Built in {dt:.1f}s")
    print(f"    tickers with history: {with_history:,}")
    print(f"    tickers without CIK:  {no_cik:,}")
    print(f"    total history rows:   {total_rows:,}")

    # Index
    con.execute("""
        CREATE INDEX IF NOT EXISTS idx_soh_ticker_date
        ON shares_outstanding_history(ticker, as_of_date)
    """)
    con.execute("CHECKPOINT")

    if is_staging_mode() and read_con is not con:
        read_con.close()


def _upsert_batch(con, batch):
    """INSERT OR REPLACE batch of rows via executemany."""
    con.executemany("""
        INSERT INTO shares_outstanding_history
            (ticker, cik, as_of_date, shares, form, filed_date, source_tag)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (ticker, as_of_date) DO UPDATE SET
            cik        = excluded.cik,
            shares     = excluded.shares,
            form       = excluded.form,
            filed_date = excluded.filed_date,
            source_tag = excluded.source_tag
    """, batch)


def main():
    parser = argparse.ArgumentParser(description="Build shares_outstanding_history from SEC XBRL")
    parser.add_argument("--staging", action="store_true")
    args = parser.parse_args()

    if args.staging:
        set_staging_mode(True)

    print("=" * 60)
    print("build_shares_history.py — SEC XBRL period-accurate shares")
    print(f"  staging={is_staging_mode()}")
    print("=" * 60)

    con = duckdb.connect(get_db_path())
    client = SECSharesClient()
    build(con, client)

    con.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
