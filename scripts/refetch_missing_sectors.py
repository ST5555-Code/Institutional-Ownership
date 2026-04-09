"""
Re-fetch sector/industry for tickers missing sector in staging.

Reads ticker list from /tmp/refetch_tickers.txt, fetches sector+industry via
scripts/yahoo_client.py (direct Yahoo JSON API), writes results back to
staging market_data.

Safe to re-run — only updates rows where sector is still NULL.
Does NOT touch production DB.

NOTE: This script is now largely subsumed by `fetch_market.py --staging
--metadata-only`, which handles the same use case end-to-end with the full
incremental update protocol. Kept for targeted manual fixes from an explicit
ticker list.

Usage:
    python3 scripts/refetch_missing_sectors.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import duckdb  # noqa: E402
from yahoo_client import YahooClient  # noqa: E402

STAGING_DB = 'data/13f_staging.duckdb'
TICKER_FILE = '/tmp/refetch_tickers.txt'


def fetch_sector(client, ticker):
    """Return (sector, industry) via YahooClient or (None, None) on failure."""
    m = client.fetch_metadata(ticker)
    if not m:
        return (None, None)
    sector = m.get('sector') or None
    industry = m.get('industry') or None
    return (sector, industry)


def main():
    with open(TICKER_FILE) as f:
        tickers = [line.strip() for line in f if line.strip()]
    print(f'Loaded {len(tickers)} tickers to refetch')

    client = YahooClient()
    con = duckdb.connect(STAGING_DB, read_only=False)
    fixed = 0
    still_missing = 0

    for i, tk in enumerate(tickers, 1):
        sector, industry = fetch_sector(client, tk)
        if sector:
            con.execute(
                "UPDATE market_data SET sector = ?, industry = ? WHERE ticker = ? AND sector IS NULL",
                [sector, industry, tk]
            )
            fixed += 1
        else:
            still_missing += 1
        if i % 25 == 0 or i == len(tickers):
            print(f'  {i}/{len(tickers)}  fixed={fixed} still_missing={still_missing}')

    con.close()
    print(f'\nDone. Fixed {fixed}, still missing {still_missing}')


if __name__ == '__main__':
    main()
