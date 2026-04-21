#!/usr/bin/env python3
"""
fetch_finra_short.py — Download FINRA daily short sale volume data.

Downloads consolidated (CNMS) short sale volume files from FINRA's CDN,
loads into DuckDB short_interest table, and joins to market_data for
gross short value.

Source: https://cdn.finra.org/equity/regsho/daily/CNMSshvol{YYYYMMDD}.txt
Data: daily short sale volume by ticker (not outstanding short interest)

Run: python3 scripts/fetch_finra_short.py                     # Last 30 trading days
     python3 scripts/fetch_finra_short.py --days 90           # Last 90 trading days
     python3 scripts/fetch_finra_short.py --update            # Only days since last loaded
     python3 scripts/fetch_finra_short.py --test              # Last 5 trading days
"""

import argparse
import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, date, timedelta

import duckdb
import requests
from tqdm import tqdm

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from db import set_staging_mode, get_db_path, set_test_mode, crash_handler, record_freshness
from config import FINRA_HEADERS

FINRA_BASE = "https://cdn.finra.org/equity/regsho/daily"
MAX_WORKERS = 8

_thread_local = threading.local()
_db_lock = threading.Lock()


def _get_session():
    if not hasattr(_thread_local, "session"):
        s = requests.Session()
        s.headers.update(FINRA_HEADERS)
        _thread_local.session = s
    return _thread_local.session


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

def trading_days(start, end):
    """Generate business days (Mon-Fri) between start and end inclusive."""
    d = start
    while d <= end:
        if d.weekday() < 5:  # Mon=0 .. Fri=4
            yield d
        d += timedelta(days=1)


def fetch_day(dt):
    """Download one day's CNMS short sale volume file. Returns list of row tuples or None."""
    date_str = dt.strftime("%Y%m%d")
    url = f"{FINRA_BASE}/CNMSshvol{date_str}.txt"
    session = _get_session()

    for attempt in range(3):
        try:
            resp = session.get(url, timeout=15)
            if resp.status_code == 200:
                break
            if resp.status_code in (403, 404):
                return None  # holiday or weekend
            if resp.status_code == 429:
                time.sleep(min(10 * (2 ** attempt), 60))
                continue
        except requests.RequestException:
            time.sleep(2)
    else:
        return None

    rows = []
    report_date = dt.isoformat()
    report_month = dt.strftime("%Y-%m")

    for line in resp.text.strip().split("\n")[1:]:  # skip header
        parts = line.split("|")
        if len(parts) < 5:
            continue
        ticker = parts[1].strip()
        if not ticker or len(ticker) > 10:
            continue
        try:
            short_vol = int(float(parts[2]))
            exempt_vol = int(float(parts[3]))
            total_vol = int(float(parts[4]))
        except (ValueError, IndexError):
            continue

        rows.append((
            ticker,
            short_vol,
            exempt_vol,
            total_vol,
            report_date,
            report_month,
        ))

    return rows


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def create_tables(con):
    con.execute("""
        CREATE TABLE IF NOT EXISTS short_interest (
            ticker VARCHAR,
            short_volume BIGINT,
            short_exempt_volume BIGINT,
            total_volume BIGINT,
            report_date DATE,
            report_month VARCHAR,
            short_pct DOUBLE,
            loaded_at TIMESTAMP,
            PRIMARY KEY (ticker, report_date)
        )
    """)


def get_loaded_dates(con):
    try:
        rows = con.execute(
            "SELECT DISTINCT report_date FROM short_interest"
        ).fetchall()
        return {str(r[0]) for r in rows}
    except Exception:
        return set()


def batch_insert(con, all_rows):
    """Insert rows, skipping duplicates."""
    now = datetime.now().isoformat()
    prepared = []
    for r in all_rows:
        short_pct = (r[1] / r[3] * 100) if r[3] > 0 else 0
        prepared.append((*r, short_pct, now))

    with _db_lock:
        con.executemany("""
            INSERT OR IGNORE INTO short_interest
            (ticker, short_volume, short_exempt_volume, total_volume,
             report_date, report_month, short_pct, loaded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, prepared)
        con.execute("CHECKPOINT")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(days=30, update_mode=False, test_mode=False):
    con = duckdb.connect(get_db_path())
    create_tables(con)

    loaded_dates = get_loaded_dates(con)
    print(f"Already loaded: {len(loaded_dates)} dates")

    today = date.today()

    if test_mode:
        days = 5
    elif update_mode:
        try:
            row = con.execute("SELECT MAX(report_date) FROM short_interest").fetchone()
            last = row[0] if row and row[0] else None
        except Exception:
            last = None
        if last:
            delta = (today - last).days
            days = max(delta + 1, 1)
            print(f"Update mode: last date = {last}, fetching {days} days")
        else:
            print("No existing data — fetching last 30 days")
            days = 30

    start = today - timedelta(days=days + 10)  # extra buffer for weekends
    target_dates = [d for d in trading_days(start, today)
                    if d.isoformat() not in loaded_dates]
    # Limit to requested window
    target_dates = target_dates[-days * 2:]  # generous — will skip holidays

    print(f"Target dates to fetch: {len(target_dates)}")
    print(f"Workers: {MAX_WORKERS}")

    all_rows = []

    pbar = tqdm(total=len(target_dates), desc="  Fetching", unit="day",
                bar_format="  {desc}: {bar} {n_fmt}/{total_fmt} [{elapsed}<{remaining}]")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(fetch_day, dt): dt for dt in target_dates}
        for fut in as_completed(futures):
            result = fut.result()
            if result:
                all_rows.extend(result)
            pbar.update(1)

    pbar.close()

    if all_rows:
        print(f"\n  Inserting {len(all_rows):,} rows...")
        # Insert in chunks
        chunk = 50_000
        for i in range(0, len(all_rows), chunk):
            batch_insert(con, all_rows[i:i + chunk])
        print("  Done.")
    else:
        print("\n  No new data to insert.")

    # Summary
    total = con.execute("SELECT COUNT(*) FROM short_interest").fetchone()[0]
    dates = con.execute("SELECT COUNT(DISTINCT report_date) FROM short_interest").fetchone()[0]
    tickers = con.execute("SELECT COUNT(DISTINCT ticker) FROM short_interest").fetchone()[0]

    print(f"\n{'='*50}")
    print(f"short_interest: {total:,} rows, {dates} dates, {tickers:,} tickers")

    # Test tickers
    if test_mode:
        print("\nTest tickers:")
        for t in ["AR", "AM", "DVN", "WBD", "CVX"]:
            row = con.execute("""
                SELECT report_date, short_volume, total_volume, short_pct
                FROM short_interest
                WHERE ticker = ?
                ORDER BY report_date DESC
                LIMIT 1
            """, [t]).fetchone()
            if row:
                print(f"  {t}: date={row[0]} short_vol={row[1]:,} total_vol={row[2]:,} short%={row[3]:.1f}")
            else:
                print(f"  {t}: no data")

    try:
        con.execute("CHECKPOINT")
        record_freshness(con, "short_interest")
    except Exception as e:
        print(f"  [warn] record_freshness(short_interest) failed: {e}", flush=True)
    con.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch FINRA short sale volume data")
    parser.add_argument("--days", type=int, default=30, help="Number of trading days to fetch")
    parser.add_argument("--update", action="store_true", help="Only fetch since last loaded date")
    parser.add_argument("--test", action="store_true", help="Test mode (5 days)")
    parser.add_argument("--staging", action="store_true", help="Write to staging DB")
    args = parser.parse_args()

    if hasattr(args, 'staging') and args.staging:
        set_staging_mode(True)
    if args.test:
        set_test_mode(True)
    crash_handler("fetch_finra_short")(
        lambda: run(days=args.days, update_mode=args.update, test_mode=args.test))
