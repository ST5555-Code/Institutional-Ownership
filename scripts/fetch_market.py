#!/usr/bin/env python3
"""
fetch_market.py — Pull market data from yfinance for all unique tickers in holdings.
                  Save to market_data table. Update holdings with pct_of_float and market_value_live.

Optimizations:
  - Persistent cache: skip tickers with fetch_date within 7 days
  - Batch yf.download() instead of per-ticker tkr.info calls
  - Never drops market_data table — upsert only

Run: python3 scripts/fetch_market.py
"""

import os
import time
import pandas as pd
import duckdb
import yfinance as yf
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from db import get_db_path, crash_handler
from config import QUARTER_SNAPSHOT_DATES as SNAPSHOT_DATES, LATEST_QUARTER


def get_tickers(con):
    """Get unique tickers from holdings."""
    df = con.execute("""
        SELECT DISTINCT ticker FROM holdings
        WHERE ticker IS NOT NULL AND ticker != ''
        ORDER BY ticker
    """).fetchdf()
    return df["ticker"].tolist()


def get_stale_tickers(con, all_tickers, max_age_days=7):
    """Return tickers missing from market_data or with stale fetch_date."""
    try:
        fresh = con.execute(f"""
            SELECT ticker FROM market_data
            WHERE fetch_date >= CURRENT_DATE - INTERVAL '{max_age_days}' DAY
        """).fetchdf()["ticker"].tolist()
        stale = [t for t in all_tickers if t not in set(fresh)]
        return stale
    except Exception:
        return all_tickers


def fetch_batch_prices(tickers):
    """Batch download current prices via yf.download(). Returns dict of ticker → price."""
    if not tickers:
        return {}
    print(f"  Batch downloading prices for {len(tickers):,} tickers...", flush=True)
    try:
        df = yf.download(tickers, period="1d", progress=False, threads=True)
        if df.empty:
            return {}
        # yf.download returns MultiIndex columns for multiple tickers
        if isinstance(df.columns, pd.MultiIndex):
            prices = {}
            if 'Close' in df.columns.get_level_values(0):
                close = df['Close']
                for t in close.columns:
                    val = close[t].dropna()
                    if len(val) > 0:
                        prices[t] = float(val.iloc[-1])
            return prices
        else:
            # Single ticker
            if 'Close' in df.columns and len(df) > 0:
                return {tickers[0]: float(df['Close'].iloc[-1])}
            return {}
    except Exception as e:
        print(f"  Batch download error: {e}")
        return {}


def fetch_ticker_info(tickers):
    """Fetch detailed info (market cap, float, sector) per ticker in batches."""
    records = []
    failed = []
    batch_size = 50
    today = datetime.now().strftime("%Y-%m-%d")

    for i in range(0, len(tickers), batch_size):
        batch = tickers[i:i + batch_size]
        try:
            data = yf.Tickers(" ".join(batch))
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
                        "fetch_date": today,
                    }
                    # Quarterly snapshot prices — skip if not needed on incremental
                    for q in SNAPSHOT_DATES:
                        record[f"price_{q}"] = None
                    records.append(record)
                except Exception:
                    failed.append(tkr_str)
        except Exception as e:
            print(f"    Batch error at {i}: {e}")
            failed.extend(batch)

        if (i + batch_size) % 200 == 0:
            print(f"    [{min(i + batch_size, len(tickers)):,}/{len(tickers):,}] "
                  f"{len(records):,} ok, {len(failed):,} failed", flush=True)
        time.sleep(0.2)

    print(f"  Fetched: {len(records):,}, Failed: {len(failed):,}")
    return pd.DataFrame(records), failed


def fetch_snapshot_prices(con, tickers):
    """Batch download historical prices for quarterly snapshots. Updates market_data in place."""
    if not tickers:
        return
    # Find earliest snapshot date
    dates = sorted(SNAPSHOT_DATES.values())
    if not dates:
        return
    start = dates[0]
    end_date = (datetime.now().strftime("%Y-%m-%d"))

    print(f"  Downloading historical prices ({start} to {end_date})...", flush=True)
    batch_size = 100
    for i in range(0, len(tickers), batch_size):
        batch = tickers[i:i + batch_size]
        try:
            hist = yf.download(batch, start=start, end=end_date, progress=False, threads=True)
            if hist.empty:
                continue
            if isinstance(hist.columns, pd.MultiIndex):
                close = hist['Close'] if 'Close' in hist.columns.get_level_values(0) else None
            else:
                close = hist[['Close']].rename(columns={'Close': batch[0]}) if len(batch) == 1 else None

            if close is not None:
                for q, date_str in SNAPSHOT_DATES.items():
                    target = pd.Timestamp(date_str)
                    mask = close.index <= target
                    if not mask.any():
                        continue
                    row = close[mask].iloc[-1]
                    for t in (close.columns if hasattr(close, 'columns') else [batch[0]]):
                        val = row[t] if hasattr(row, '__getitem__') else row
                        if pd.notna(val):
                            con.execute(f"UPDATE market_data SET price_{q} = ? WHERE ticker = ?",
                                        [float(val), str(t)])
        except Exception as e:
            print(f"    Snapshot batch error at {i}: {e}")
        if (i + batch_size) % 500 == 0:
            print(f"    [{min(i + batch_size, len(tickers)):,}/{len(tickers):,}] snapshots", flush=True)


def save_market_data(con, df_market):
    """Upsert market_data table — never drops existing data."""
    print("\nSaving market_data table...")
    try:
        con.execute("SELECT 1 FROM market_data LIMIT 1")
        table_exists = True
    except Exception:
        table_exists = False

    if not table_exists:
        con.execute("CREATE TABLE market_data AS SELECT * FROM df_market")
        con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_market_ticker ON market_data(ticker)")
    else:
        if len(df_market) > 0:
            con.execute("DELETE FROM market_data WHERE ticker IN (SELECT ticker FROM df_market)")
            con.execute("INSERT INTO market_data SELECT * FROM df_market")

    count = con.execute("SELECT COUNT(*) FROM market_data").fetchone()[0]
    print(f"  market_data: {count:,} rows")


def update_holdings(con):
    """Update holdings with pct_of_float and market_value_live."""
    print("\nUpdating holdings with market data...")
    con.execute("""
        UPDATE holdings h SET market_value_live = h.shares * m.price_live
        FROM market_data m WHERE h.ticker = m.ticker AND m.price_live IS NOT NULL
    """)
    con.execute("""
        UPDATE holdings h SET pct_of_float = ROUND(h.shares * 100.0 / m.float_shares, 4)
        FROM market_data m WHERE h.ticker = m.ticker AND m.float_shares IS NOT NULL AND m.float_shares > 0
    """)
    total = con.execute("SELECT COUNT(*) FROM holdings").fetchone()[0]
    live = con.execute("SELECT COUNT(*) FROM holdings WHERE market_value_live IS NOT NULL").fetchone()[0]
    print(f"  Holdings with live value: {live:,} / {total:,} ({live / total * 100:.1f}%)")


def main():
    print("=" * 60)
    print("fetch_market.py — Market Data")
    print("=" * 60)

    con = duckdb.connect(get_db_path())

    all_tickers = get_tickers(con)
    print(f"  Total tickers: {len(all_tickers):,}")

    tickers = get_stale_tickers(con, all_tickers)
    skipped = len(all_tickers) - len(tickers)
    if skipped:
        print(f"  Skipping {skipped:,} tickers fetched within 7 days")
    print(f"  Fetching: {len(tickers):,}")

    if not tickers:
        print("All tickers fresh. Nothing to fetch.")
        con.close()
        return

    # Fetch detailed info
    df_market, failed = fetch_ticker_info(tickers)
    if len(df_market) == 0:
        print("No data fetched.")
        con.close()
        return

    # Save
    save_market_data(con, df_market)

    # Historical snapshot prices
    fetched_tickers = df_market["ticker"].tolist()
    fetch_snapshot_prices(con, fetched_tickers)
    con.execute("CHECKPOINT")

    # Update holdings
    update_holdings(con)
    con.close()
    print("\nDone.")


if __name__ == "__main__":
    crash_handler("fetch_market")(main)
