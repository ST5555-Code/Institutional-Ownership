#!/usr/bin/env python3
"""
fetch_market.py — Pull market data from yfinance for all unique tickers in holdings.
                  Save to market_data table. Update holdings with pct_of_float and market_value_live.

Run: python3 scripts/fetch_market.py
     (Requires load_13f.py and build_cusip.py to have run first)
"""

import os
import sys
import time
import pandas as pd
import duckdb
import yfinance as yf
from datetime import datetime, timedelta

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from db import get_db_path, crash_handler

from config import QUARTER_SNAPSHOT_DATES as SNAPSHOT_DATES


def get_tickers(con):
    """Get unique tickers from holdings."""
    df = con.execute("""
        SELECT DISTINCT ticker
        FROM holdings
        WHERE ticker IS NOT NULL AND ticker != ''
        ORDER BY ticker
    """).fetchdf()
    tickers = df["ticker"].tolist()
    print(f"  Unique tickers to fetch: {len(tickers):,}")
    return tickers


def fetch_market_data(tickers):
    """Fetch market data from yfinance for all tickers."""
    print("\nFetching market data from yfinance...")

    records = []
    failed = []
    batch_size = 50

    for i in range(0, len(tickers), batch_size):
        batch = tickers[i:i + batch_size]
        batch_str = " ".join(batch)

        try:
            # Get current data via Tickers
            data = yf.Tickers(batch_str)

            for tkr_str in batch:
                try:
                    tkr = data.tickers.get(tkr_str)
                    if tkr is None:
                        failed.append(tkr_str)
                        continue

                    info = tkr.info
                    if not info or not info.get("regularMarketPrice"):
                        failed.append(tkr_str)
                        continue

                    record = {
                        "ticker": tkr_str,
                        "price_live": info.get("regularMarketPrice") or info.get("currentPrice"),
                        "market_cap": info.get("marketCap"),
                        "float_shares": info.get("floatShares"),
                        "shares_outstanding": info.get("sharesOutstanding"),
                        "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
                        "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
                        "avg_volume_30d": info.get("averageVolume"),
                        "sector": info.get("sector"),
                        "industry": info.get("industry"),
                        "exchange": info.get("exchange"),
                        "fetch_date": datetime.now().strftime("%Y-%m-%d"),
                    }

                    # Get historical prices for quarterly snapshots
                    try:
                        hist = tkr.history(start="2025-05-01", end="2026-01-05")
                        if len(hist) > 0:
                            for q, date_str in SNAPSHOT_DATES.items():
                                target = pd.Timestamp(date_str)
                                # Find closest trading day on or before target
                                mask = hist.index <= target
                                if mask.any():
                                    closest = hist[mask].iloc[-1]
                                    record[f"price_{q}"] = closest["Close"]
                                else:
                                    record[f"price_{q}"] = None
                        else:
                            for q in SNAPSHOT_DATES:
                                record[f"price_{q}"] = None
                    except Exception:
                        for q in SNAPSHOT_DATES:
                            record[f"price_{q}"] = None

                    records.append(record)

                except Exception as e:
                    failed.append(tkr_str)

        except Exception as e:
            print(f"    Batch error at {i}: {e}")
            failed.extend(batch)

        if (i + batch_size) % 200 == 0:
            print(f"    Processed {min(i + batch_size, len(tickers)):,}/{len(tickers):,} "
                  f"({len(records):,} success, {len(failed):,} failed)")

        # Small delay to avoid rate limiting
        time.sleep(0.2)

    print(f"\n  Successfully fetched: {len(records):,}")
    print(f"  Failed/skipped: {len(failed):,}")

    # Log some failures
    if failed:
        print(f"  Sample failures: {failed[:20]}")

    return pd.DataFrame(records), failed


def save_market_data(con, df_market):
    """Upsert market_data table — insert new, update existing."""
    print("\nSaving market_data table...")

    try:
        con.execute("SELECT 1 FROM market_data LIMIT 1")
        table_exists = True
    except Exception:
        table_exists = False

    if not table_exists:
        con.execute("CREATE TABLE market_data AS SELECT * FROM df_market")
    else:
        # Delete existing rows for tickers we're updating, then insert
        tickers = df_market["ticker"].tolist()
        if tickers:
            con.execute("DELETE FROM market_data WHERE ticker IN (SELECT ticker FROM df_market)")
            con.execute("INSERT INTO market_data SELECT * FROM df_market")

    count = con.execute("SELECT COUNT(*) FROM market_data").fetchone()[0]
    print(f"  market_data: {count:,} rows")
    return count


def update_holdings(con):
    """Update holdings with pct_of_float and market_value_live."""
    print("\nUpdating holdings with market data...")

    # Update market_value_live = shares × today's live price
    con.execute("""
        UPDATE holdings h
        SET market_value_live = h.shares * m.price_live
        FROM market_data m
        WHERE h.ticker = m.ticker AND m.price_live IS NOT NULL
    """)

    # Update pct_of_float
    con.execute("""
        UPDATE holdings h
        SET pct_of_float = ROUND(h.shares * 100.0 / m.float_shares, 4)
        FROM market_data m
        WHERE h.ticker = m.ticker
          AND m.float_shares IS NOT NULL
          AND m.float_shares > 0
    """)

    live_count = con.execute("SELECT COUNT(*) FROM holdings WHERE market_value_live IS NOT NULL").fetchone()[0]
    float_count = con.execute("SELECT COUNT(*) FROM holdings WHERE pct_of_float IS NOT NULL").fetchone()[0]
    total = con.execute("SELECT COUNT(*) FROM holdings").fetchone()[0]

    print(f"  Holdings with live value: {live_count:,} / {total:,} ({live_count / total * 100:.1f}%)")
    print(f"  Holdings with float %: {float_count:,} / {total:,} ({float_count / total * 100:.1f}%)")


def print_summary(con):
    """Print summary of market data."""
    print("\n--- Market Data Summary ---")

    print("\nTop 10 by market cap:")
    top = con.execute("""
        SELECT ticker, price_live, market_cap / 1e9 as mktcap_bn,
               float_shares / 1e6 as float_mm, sector
        FROM market_data
        WHERE market_cap IS NOT NULL
        ORDER BY market_cap DESC
        LIMIT 10
    """).fetchdf()
    print(top.to_string(index=False))

    print("\nAR (Antero Resources) market data:")
    ar = con.execute("""
        SELECT * FROM market_data WHERE ticker = 'AR'
    """).fetchdf()
    if len(ar) > 0:
        for col in ar.columns:
            val = ar[col].iloc[0]
            print(f"  {col}: {val}")
    else:
        print("  AR not found in market_data")

    print("\nAR top holders with live values (Q4 2025):")
    ar_holders = con.execute("""
        SELECT manager_name, inst_parent_name, shares,
               market_value_live / 1e6 as live_value_mm,
               pct_of_float, manager_type
        FROM holdings
        WHERE ticker = 'AR' AND quarter = '2025Q4'
        ORDER BY market_value_live DESC NULLS LAST
        LIMIT 10
    """).fetchdf()
    print(ar_holders.to_string(index=False))


def get_stale_tickers(con, all_tickers, max_age_days=7):
    """Return tickers missing from market_data or fetched more than max_age_days ago."""
    try:
        cols = [c[0] for c in con.execute("DESCRIBE market_data").fetchall()]
        if "fetch_date" not in cols:
            return all_tickers  # no timestamp column — fetch all
        fresh = con.execute(f"""
            SELECT ticker FROM market_data
            WHERE fetch_date >= CURRENT_DATE - INTERVAL '{max_age_days}' DAY
        """).fetchdf()["ticker"].tolist()
        fresh_set = set(fresh)
        stale = [t for t in all_tickers if t not in fresh_set]
        return stale
    except Exception:
        return all_tickers  # table doesn't exist — fetch all


def main():
    print("=" * 60)
    print("SCRIPT 5 — fetch_market.py")
    print("=" * 60)

    con = duckdb.connect(get_db_path())

    # Step 1: Get tickers
    print("\nGetting tickers from holdings...")
    all_tickers = get_tickers(con)

    # Step 1b: Skip tickers already fetched within 7 days
    tickers = get_stale_tickers(con, all_tickers)
    skipped = len(all_tickers) - len(tickers)
    if skipped > 0:
        print(f"  Skipping {skipped:,} tickers fetched within 7 days")
    print(f"  Fetching: {len(tickers):,} tickers")

    if not tickers:
        print("No tickers found. Run build_cusip.py first.")
        con.close()
        return

    # Step 2: Fetch market data
    df_market, failed = fetch_market_data(tickers)

    if len(df_market) == 0:
        print("No market data fetched. Check network/API.")
        con.close()
        return

    # Step 3: Save to DuckDB
    save_market_data(con, df_market)

    # Step 4: Update holdings
    update_holdings(con)

    # Step 5: Summary
    print_summary(con)

    con.close()
    print("\nDone.")


if __name__ == "__main__":
    crash_handler("fetch_market")(main)
