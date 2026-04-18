"""
Build benchmark_weights table from Vanguard Total Stock Market Index Fund.

Computes US equity market sector weights per quarter from N-PORT holdings
of Vanguard Total Stock Market (series S000002848, ~3,200 positions).

Weights are stored per-quarter end date so historical analysis uses
period-appropriate benchmarks. Auto-updates with each new quarter.

Run as part of the quarterly pipeline after fetch_nport.py and market_data.
"""
import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import duckdb  # noqa: E402
from db import get_db_path, set_staging_mode  # noqa: E402
from config import QUARTERS  # noqa: E402

# Vanguard Total Stock Market Index Fund — broadest US equity coverage
BENCHMARK_SERIES_ID = 'S000002848'
BENCHMARK_INDEX_NAME = 'US_MKT'

# Yahoo → GICS sector mapping (matches queries._YF_TO_GICS)
YF_TO_GICS = {
    'Technology': ('Information Technology', 'TEC'),
    'Financial Services': ('Financials', 'FIN'),
    'Healthcare': ('Health Care', 'HCR'),
    'Industrials': ('Industrials', 'IND'),
    'Consumer Cyclical': ('Consumer Discretionary', 'CND'),
    'Consumer Defensive': ('Consumer Staples', 'CNS'),
    'Energy': ('Energy', 'ENE'),
    'Basic Materials': ('Materials', 'MAT'),
    'Communication Services': ('Communication Services', 'COM'),
    'Utilities': ('Utilities', 'UTL'),
    'Real Estate': ('Real Estate', 'REA'),
}

QUARTER_END_DATES = {
    '2025Q1': '2025-03-31',
    '2025Q2': '2025-06-30',
    '2025Q3': '2025-09-30',
    '2025Q4': '2025-12-31',
}


def _map_to_gics(yf_sector, yf_industry):
    """Yahoo sector/industry → GICS. REITs under Financial Services moved to Real Estate."""
    if not yf_sector:
        return None
    if yf_sector == 'Financial Services' and yf_industry and 'REIT' in yf_industry.upper():
        return ('Real Estate', 'REA')
    return YF_TO_GICS.get(yf_sector)


def build():
    con = duckdb.connect(get_db_path())

    # Ensure table exists
    con.execute("""
        CREATE TABLE IF NOT EXISTS benchmark_weights (
            index_name VARCHAR,
            gics_sector VARCHAR,
            gics_code VARCHAR,
            weight_pct DOUBLE,
            as_of_date DATE,
            source VARCHAR,
            PRIMARY KEY (index_name, gics_sector, as_of_date)
        )
    """)

    for q in QUARTERS:
        as_of = QUARTER_END_DATES.get(q)
        if not as_of:
            print(f'Skipping {q} — no date mapping')
            continue

        # Check if benchmark fund has data for this quarter.
        # `fund_holdings_v2` is per (series_id, report_month) — same
        # series × quarter shows up as 1–3 rows per holding, once per
        # filed month. The `> 0` check is unaffected by that.
        cnt = con.execute(
            "SELECT COUNT(*) FROM fund_holdings_v2 "
            "WHERE series_id = ? AND quarter = ?",
            [BENCHMARK_SERIES_ID, q]
        ).fetchone()[0]
        if cnt == 0:
            print(f'Skipping {q} — no benchmark fund data')
            continue

        # Aggregate the quarter-end month only — scope `fund_holdings_v2`
        # to the MAX(report_month) for this (series, quarter) so a series
        # that filed all three monthly snapshots isn't triple-counted.
        # Matches the `latest_per_series` convention used in
        # build_summaries.py.
        rows = con.execute("""
            WITH latest_rm AS (
                SELECT MAX(report_month) AS rm
                  FROM fund_holdings_v2
                 WHERE series_id = ? AND quarter = ?
            )
            SELECT COALESCE(m.sector, 'Unknown') as yf_sector,
                   COALESCE(m.industry, '') as yf_industry,
                   SUM(fh.market_value_usd) as val
              FROM fund_holdings_v2 fh
              JOIN latest_rm lrm ON fh.report_month = lrm.rm
              LEFT JOIN market_data m ON fh.ticker = m.ticker
             WHERE fh.series_id = ? AND fh.quarter = ?
               AND fh.market_value_usd > 0
             GROUP BY m.sector, m.industry
        """, [BENCHMARK_SERIES_ID, q, BENCHMARK_SERIES_ID, q]).fetchall()

        gics_totals = {}
        total = 0.0
        for yf_sec, yf_ind, val in rows:
            gics = _map_to_gics(yf_sec, yf_ind)
            if not gics:
                continue  # skip Unknown / unmapped
            gics_totals[gics] = gics_totals.get(gics, 0.0) + float(val or 0)
            total += float(val or 0)

        if total == 0:
            print(f'{q}: no classified holdings, skipping')
            continue

        # Delete existing entries for this index/date
        con.execute(
            "DELETE FROM benchmark_weights WHERE index_name = ? AND as_of_date = ?",
            [BENCHMARK_INDEX_NAME, as_of]
        )

        print(f'\n{q} ({as_of}):')
        for (sec, code), val in sorted(gics_totals.items(), key=lambda x: x[1], reverse=True):
            pct = round(val / total * 100, 2)
            print(f'  {sec:25s} {code} {pct:5.1f}%')
            con.execute(
                "INSERT INTO benchmark_weights VALUES (?, ?, ?, ?, ?, ?)",
                [BENCHMARK_INDEX_NAME, sec, code, pct, as_of,
                 f'Vanguard Total Stock Market {BENCHMARK_SERIES_ID}']
            )

    con.close()
    print('\nDone.')


def _parse_args() -> argparse.Namespace:
    """CLI parser — `--staging` redirects the write target to the staging DB."""
    parser = argparse.ArgumentParser(
        description="Build benchmark_weights from Vanguard Total Stock Market.",
    )
    parser.add_argument("--staging", action="store_true",
                        help="Write to staging DB instead of prod.")
    return parser.parse_args()


if __name__ == '__main__':
    _args = _parse_args()
    if _args.staging:
        set_staging_mode(True)
    build()
