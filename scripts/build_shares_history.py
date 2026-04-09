#!/usr/bin/env python3
"""
build_shares_history.py — Populate `shares_outstanding_history` table from SEC XBRL.

For every ticker with a CIK mapping, pulls ALL historical
EntityCommonStockSharesOutstanding / CommonStockSharesOutstanding facts from
the local SEC companyfacts cache (refresh via fetch_market.py --sec-only).

The resulting table is used to compute period-accurate `pct_of_float` for
13F holdings via DuckDB ASOF JOIN: each holding's `report_date` is matched
to the most recent XBRL fact on-or-before that date.

This is the fix for a latent accuracy bug where `holdings.pct_of_float` used
`market_data.shares_outstanding` (latest) as the denominator for all historical
quarters, inflating or deflating ratios for companies with splits, buybacks, or
offerings between the holding's report_date and today.

Usage:
    python3 scripts/build_shares_history.py [--staging] [--update-holdings]

Flags:
    --staging            Write to staging DB instead of production
    --update-holdings    Recompute holdings.pct_of_float via ASOF JOIN after build
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


def update_holdings_pct_of_float(con):
    """Recompute holdings.pct_of_float using period-accurate SEC shares via
    DuckDB ASOF JOIN.

    For each holding row, find the most recent shares_outstanding fact whose
    `as_of_date <= holdings.report_date`. Fall back to the LATEST
    shares_outstanding in market_data (or float_shares) when no historical
    fact exists — this preserves current coverage for tickers without SEC
    history (ETFs, recent IPOs, override-based entries).
    """
    if is_staging_mode():
        print("\n  Staging mode: skipping holdings update (run after merge)")
        return

    print("\nUpdating holdings.pct_of_float via ASOF JOIN...")

    # Build per-(ticker, report_date) lookup with ASOF JOIN, then update.
    # holdings.report_date is stored as VARCHAR in DD-MON-YYYY format
    # (e.g. "31-MAR-2025"), so parse via strptime before comparing.
    con.execute("""
        CREATE OR REPLACE TEMP TABLE _period_shares AS
        SELECT h.ticker, h.report_date, soh.shares AS period_shares
        FROM (
            SELECT DISTINCT ticker, report_date,
                   strptime(report_date, '%d-%b-%Y')::DATE AS report_date_d
            FROM holdings
            WHERE ticker IS NOT NULL AND report_date IS NOT NULL
        ) h
        ASOF LEFT JOIN shares_outstanding_history soh
          ON h.ticker = soh.ticker
         AND h.report_date_d >= soh.as_of_date
    """)

    matched = con.execute("SELECT COUNT(*) FROM _period_shares WHERE period_shares IS NOT NULL").fetchone()[0]
    total_pairs = con.execute("SELECT COUNT(*) FROM _period_shares").fetchone()[0]
    print(f"  (ticker, report_date) pairs: {total_pairs:,} — matched to SEC history: {matched:,} ({100*matched/max(1,total_pairs):.1f}%)")

    # Primary update: use period-accurate shares
    con.execute("""
        UPDATE holdings h SET pct_of_float = ROUND(
            h.shares * 100.0 / ps.period_shares, 4)
        FROM _period_shares ps
        WHERE h.ticker = ps.ticker
          AND h.report_date = ps.report_date
          AND ps.period_shares IS NOT NULL
          AND ps.period_shares > 0
    """)

    # Fallback: for (ticker, report_date) pairs with no SEC history, use the
    # current market_data value. This preserves coverage where SEC XBRL has no
    # data at all (ETFs, very recent IPOs).
    con.execute("""
        UPDATE holdings h SET pct_of_float = ROUND(
            h.shares * 100.0 / COALESCE(m.shares_outstanding, m.float_shares), 4)
        FROM market_data m, _period_shares ps
        WHERE h.ticker = m.ticker
          AND h.ticker = ps.ticker
          AND h.report_date = ps.report_date
          AND ps.period_shares IS NULL
          AND COALESCE(m.shares_outstanding, m.float_shares) IS NOT NULL
          AND COALESCE(m.shares_outstanding, m.float_shares) > 0
    """)

    total_h = con.execute("SELECT COUNT(*) FROM holdings").fetchone()[0]
    pctf = con.execute("SELECT COUNT(*) FROM holdings WHERE pct_of_float IS NOT NULL").fetchone()[0]
    print(f"  holdings with pct_of_float: {pctf:,}/{total_h:,} ({100*pctf/total_h:.1f}%)")

    con.execute("DROP TABLE _period_shares")
    con.execute("CHECKPOINT")


def main():
    parser = argparse.ArgumentParser(description="Build shares_outstanding_history from SEC XBRL")
    parser.add_argument("--staging", action="store_true")
    parser.add_argument("--update-holdings", action="store_true",
                        help="Recompute holdings.pct_of_float with period-accurate shares")
    args = parser.parse_args()

    if args.staging:
        set_staging_mode(True)

    print("=" * 60)
    print("build_shares_history.py — SEC XBRL period-accurate shares")
    print(f"  staging={is_staging_mode()}  update_holdings={args.update_holdings}")
    print("=" * 60)

    con = duckdb.connect(get_db_path())
    client = SECSharesClient()
    build(con, client)

    if args.update_holdings:
        update_holdings_pct_of_float(con)

    con.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
