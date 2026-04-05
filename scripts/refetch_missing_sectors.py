"""
Re-fetch yfinance sector/industry for tickers missing sector in staging.

Reads ticker list from /tmp/refetch_tickers.txt, fetches sector+industry
from yfinance in batches, writes results back to staging market_data.

Safe to re-run — only updates rows where sector is still NULL.
Does NOT touch production DB.

Usage:
    python3 scripts/refetch_missing_sectors.py
"""
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import duckdb  # noqa: E402

try:
    import yfinance as yf
except ImportError:
    print("yfinance not installed. Run: pip install yfinance")
    sys.exit(1)

STAGING_DB = 'data/13f_staging.duckdb'
TICKER_FILE = '/tmp/refetch_tickers.txt'
BATCH_SIZE = 20  # yfinance rate-limit friendly
SLEEP_BETWEEN = 1.0  # seconds between batches


def fetch_sector(ticker):
    """Return (sector, industry) from yfinance or (None, None) on failure."""
    try:
        t = yf.Ticker(ticker)
        info = t.info
        sector = info.get('sector')
        industry = info.get('industry')
        # Empty strings → None
        if sector == '':
            sector = None
        if industry == '':
            industry = None
        return (sector, industry)
    except Exception as e:
        return (None, None)


def main():
    with open(TICKER_FILE) as f:
        tickers = [line.strip() for line in f if line.strip()]
    print(f'Loaded {len(tickers)} tickers to refetch')

    con = duckdb.connect(STAGING_DB, read_only=False)
    fixed = 0
    still_missing = 0
    failed = 0

    for i in range(0, len(tickers), BATCH_SIZE):
        batch = tickers[i:i + BATCH_SIZE]
        for tk in batch:
            sector, industry = fetch_sector(tk)
            if sector:
                con.execute(
                    "UPDATE market_data SET sector = ?, industry = ? WHERE ticker = ? AND sector IS NULL",
                    [sector, industry, tk]
                )
                fixed += 1
            else:
                still_missing += 1
                if sector is None and industry is None:
                    failed += 1
        print(f'  {i + len(batch)}/{len(tickers)}  fixed={fixed} still_missing={still_missing}')
        time.sleep(SLEEP_BETWEEN)

    con.close()
    print(f'\nDone. Fixed {fixed}, still missing {still_missing}, {failed} failed to fetch')


if __name__ == '__main__':
    main()
