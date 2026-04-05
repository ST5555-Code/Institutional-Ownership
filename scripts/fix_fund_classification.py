"""
Backfill fund_universe.is_actively_managed using name-based classification.

The existing fetch_nport.py classify_fund() has a bug: it returns
is_actively_managed=True for every fund that passes the index filter,
regardless of whether the fund is actually passive. When the data
was loaded with --include-index, all 6,671 funds were tagged as active.

This script applies the same keyword-based classification used in
queries._classify_fund_type() to update fund_universe in place.

Usage:
    python3 scripts/fix_fund_classification.py                # staging
    python3 scripts/fix_fund_classification.py --production   # prod (after verification)
"""
import argparse
import re
import sys
from pathlib import Path

import duckdb

PASSIVE_KEYWORDS = [
    'INDEX', 'ETF', 'EXCHANGE-TRADED', 'EXCHANGE TRADED',
    'MSCI', 'FTSE', 'STOXX', 'NIKKEI',
    'TOTAL STOCK', 'TOTAL MARKET', 'TOTAL BOND', 'TOTAL INTERNATIONAL',
    'BROAD MARKET', 'TRACKER', 'NASDAQ', 'DOW JONES', 'WILSHIRE',
    'BARCLAYS AGGREGATE', 'BLOOMBERG AGGREGATE',
    'SPDR', 'ISHARES', 'PROSHARES',
    'SECTOR SELECT', 'SELECT SECTOR', 'SELECT SPDR',
]

INDEX_COMBOS = [
    ('S&P', '500'), ('S&P', '400'), ('S&P', '600'), ('S&P', '100'),
    ('RUSSELL', '1000'), ('RUSSELL', '2000'), ('RUSSELL', '3000'),
    ('BLOOMBERG', '500'), ('BLOOMBERG', 'AGGREGATE'),
]


def classify(fund_name):
    """Return 'active' or 'passive' based on name keywords."""
    if not fund_name:
        return 'active'
    name_upper = fund_name.upper()
    if any(kw in name_upper for kw in PASSIVE_KEYWORDS):
        return 'passive'
    for prefix, suffix in INDEX_COMBOS:
        if prefix in name_upper and suffix in name_upper:
            return 'passive'
    return 'active'


def run(db_path):
    print(f'Opening {db_path}...')
    con = duckdb.connect(db_path, read_only=False)

    # Snapshot current state
    before = con.execute("""
        SELECT
            COUNT(*) as total,
            COUNT(CASE WHEN is_actively_managed = true THEN 1 END) as active,
            COUNT(CASE WHEN is_actively_managed = false THEN 1 END) as passive,
            COUNT(CASE WHEN is_actively_managed IS NULL THEN 1 END) as null_count
        FROM fund_universe
    """).fetchone()
    print(f'BEFORE: total={before[0]}, active={before[1]}, passive={before[2]}, null={before[3]}')

    # Fetch all funds
    df = con.execute("SELECT series_id, fund_name FROM fund_universe").fetchdf()
    print(f'Classifying {len(df)} funds...')

    updates = []  # (new_value, series_id)
    passive_count = 0
    active_count = 0
    for _, row in df.iterrows():
        fund_type = classify(row['fund_name'])
        new_flag = (fund_type == 'active')
        updates.append((new_flag, row['series_id']))
        if fund_type == 'passive':
            passive_count += 1
        else:
            active_count += 1

    print(f'Classification result: {active_count} active, {passive_count} passive')

    # Apply updates in batches
    print('Applying updates...')
    con.executemany(
        "UPDATE fund_universe SET is_actively_managed = ? WHERE series_id = ?",
        updates
    )

    # Verify
    after = con.execute("""
        SELECT
            COUNT(*) as total,
            COUNT(CASE WHEN is_actively_managed = true THEN 1 END) as active,
            COUNT(CASE WHEN is_actively_managed = false THEN 1 END) as passive,
            COUNT(CASE WHEN is_actively_managed IS NULL THEN 1 END) as null_count
        FROM fund_universe
    """).fetchone()
    print(f'AFTER:  total={after[0]}, active={after[1]}, passive={after[2]}, null={after[3]}')

    # Spot-check known funds
    print('\nSpot-check known funds:')
    samples = [
        'Vanguard 500 Index Fund',
        'Vanguard Total Stock Market Index Fund',
        'Fidelity Contrafund',
        'Vanguard Wellington Fund',
        'iShares Core S&P 500 ETF',
        'T. Rowe Price Growth Stock Fund',
        'Vanguard Growth Index Fund',
        'Fidelity Growth Fund',
        'SPDR S&P 500 ETF Trust',
        'American Funds Growth Fund of America',
    ]
    for s in samples:
        r = con.execute(
            "SELECT fund_name, is_actively_managed FROM fund_universe WHERE fund_name ILIKE ? LIMIT 1",
            [f'%{s}%']
        ).fetchone()
        if r:
            flag = 'ACTIVE' if r[1] else 'PASSIVE'
            print(f'  {flag:8s} {r[0][:55]}')

    con.close()
    print('\nDone.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--production', action='store_true',
                        help='Target production DB (default: staging)')
    args = parser.parse_args()

    base = Path(__file__).parent.parent
    if args.production:
        db = base / 'data' / '13f.duckdb'
        print('WARNING: Running against PRODUCTION database')
    else:
        db = base / 'data' / '13f_staging.duckdb'
        print('Target: staging database')

    if not db.exists():
        print(f'Database not found: {db}')
        sys.exit(1)

    run(str(db))


if __name__ == '__main__':
    main()
