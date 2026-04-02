"""
Compute institutional flow analytics: investor_flows and ticker_flow_stats.

Processes all tickers with Q4 holdings. For each ticker, computes:
- Per-investor flow metrics for 3 periods (Q1→Q4, Q2→Q4, Q3→Q4)
- Momentum signals (always based on 4Q comparison)
- Aggregate stats (flow intensity, churn)

Usage:
    python3 scripts/compute_flows.py
"""

import sys
import time
from datetime import datetime

import duckdb
import pandas as pd

from db import get_db_path
from config import QUARTERS, LATEST_QUARTER, FIRST_QUARTER, PREV_QUARTER, FLOW_PERIODS

PERIODS = FLOW_PERIODS
LATEST_Q = LATEST_QUARTER


def create_tables(con):
    con.execute("DROP TABLE IF EXISTS investor_flows")
    con.execute("""
        CREATE TABLE investor_flows (
            ticker VARCHAR,
            period VARCHAR,
            quarter_from VARCHAR,
            quarter_to VARCHAR,
            inst_parent_name VARCHAR,
            manager_type VARCHAR,
            from_shares DOUBLE,
            to_shares DOUBLE,
            net_shares DOUBLE,
            pct_change DOUBLE,
            from_value DOUBLE,
            to_value DOUBLE,
            from_price DOUBLE,
            price_adj_flow DOUBLE,
            raw_flow DOUBLE,
            price_effect DOUBLE,
            is_new_entry BOOLEAN,
            is_exit BOOLEAN,
            flow_4q DOUBLE,
            flow_2q DOUBLE,
            momentum_ratio DOUBLE,
            momentum_signal VARCHAR
        )
    """)
    con.execute("DROP TABLE IF EXISTS ticker_flow_stats")
    con.execute("""
        CREATE TABLE ticker_flow_stats (
            ticker VARCHAR,
            quarter_from VARCHAR,
            quarter_to VARCHAR,
            flow_intensity_total DOUBLE,
            flow_intensity_active DOUBLE,
            flow_intensity_passive DOUBLE,
            churn_nonpassive DOUBLE,
            churn_active DOUBLE,
            computed_at TIMESTAMP
        )
    """)


def compute_ticker_flows(con, ticker, market_cap):
    """Compute all flow metrics for a single ticker."""
    # Get parent-level holdings for each quarter
    quarters = QUARTERS
    qdata = {}
    for q in quarters:
        df = con.execute("""
            SELECT
                COALESCE(inst_parent_name, manager_name) as investor,
                MAX(manager_type) as manager_type,
                SUM(shares) as shares,
                SUM(market_value_usd) / 1000.0 as value
            FROM holdings
            WHERE ticker = ? AND quarter = ?
            GROUP BY investor
        """, [ticker, q]).fetchdf()
        qdata[q] = {row['investor']: row for _, row in df.iterrows()}

    # Compute implied prices per quarter (aggregate)
    implied_prices = {}
    for q in quarters:
        total_shares = sum(r['shares'] for r in qdata[q].values() if r['shares'] and r['shares'] > 0)
        total_value = sum(r['value'] for r in qdata[q].values() if r['value'])
        implied_prices[q] = total_value / total_shares if total_shares > 0 else None

    # Compute flows for each period
    all_rows = []
    momentum_cache = {}  # investor -> {flow_4q, flow_2q}

    for period_label, q_from, q_to in PERIODS:
        from_map = qdata.get(q_from, {})
        to_map = qdata.get(q_to, {})
        all_investors = set(from_map.keys()) | set(to_map.keys())
        from_price = implied_prices.get(q_from)

        for inv in all_investors:
            fr = from_map.get(inv)
            to = to_map.get(inv)
            from_shares = float(fr['shares']) if fr is not None and pd.notna(fr['shares']) else 0
            to_shares = float(to['shares']) if to is not None and pd.notna(to['shares']) else 0
            from_val = float(fr['value']) if fr is not None and pd.notna(fr['value']) else 0
            to_val = float(to['value']) if to is not None and pd.notna(to['value']) else 0
            mtype = (to['manager_type'] if to is not None else fr['manager_type']) if fr is not None or to is not None else None

            net = to_shares - from_shares
            pct_change = net / from_shares if from_shares > 0 else None
            is_new = from_shares == 0 and to_shares > 0
            is_exit = from_shares > 0 and to_shares == 0

            # Use investor's own implied price for price-adj flow
            inv_from_price = from_val / from_shares if from_shares > 0 and from_val > 0 else from_price
            paf = net * inv_from_price if inv_from_price and not is_new else None
            raw = to_val - from_val
            pe = (raw - paf) if paf is not None else None

            row = {
                'ticker': ticker, 'period': period_label,
                'quarter_from': q_from, 'quarter_to': q_to,
                'inst_parent_name': inv, 'manager_type': mtype,
                'from_shares': from_shares if from_shares > 0 else None,
                'to_shares': to_shares if to_shares > 0 else None,
                'net_shares': net if net != 0 else None,
                'pct_change': pct_change,
                'from_value': from_val if from_val > 0 else None,
                'to_value': to_val if to_val > 0 else None,
                'from_price': inv_from_price,
                'price_adj_flow': paf, 'raw_flow': raw if raw != 0 else None,
                'price_effect': pe,
                'is_new_entry': is_new, 'is_exit': is_exit,
            }
            all_rows.append(row)

            # Cache 4Q and 1Q flows for momentum
            if period_label == '4Q':
                momentum_cache.setdefault(inv, {})['flow_4q'] = paf
            elif period_label == '1Q':
                momentum_cache.setdefault(inv, {})['flow_2q'] = paf

    # Compute momentum and apply to all rows
    for row in all_rows:
        inv = row['inst_parent_name']
        mc = momentum_cache.get(inv, {})
        f4q = mc.get('flow_4q')
        f2q = mc.get('flow_2q')
        row['flow_4q'] = f4q
        row['flow_2q'] = f2q

        if f4q and f4q != 0 and f2q is not None:
            ratio = f2q / f4q
        else:
            ratio = None
        row['momentum_ratio'] = ratio

        # Signal
        mtype = row.get('manager_type')
        if mtype == 'passive':
            row['momentum_signal'] = None
        elif row['is_new_entry']:
            row['momentum_signal'] = 'NEW'
        elif row['is_exit']:
            row['momentum_signal'] = 'EXIT'
        elif ratio is not None:
            if ratio > 0.65:
                row['momentum_signal'] = 'ACCEL'
            elif ratio >= 0.35:
                row['momentum_signal'] = 'STEADY'
            elif ratio >= 0.10:
                row['momentum_signal'] = 'FADING'
            elif ratio >= 0:
                row['momentum_signal'] = 'MINIMAL'
            else:
                row['momentum_signal'] = 'REVERSING'
        else:
            row['momentum_signal'] = None

    # Insert flow rows
    if all_rows:
        df = pd.DataFrame(all_rows)
        con.execute("INSERT INTO investor_flows SELECT * FROM df")

    # Compute ticker-level stats
    for period_label, q_from, q_to in PERIODS:
        period_rows = [r for r in all_rows if r['period'] == period_label]
        # Flow intensity
        existing = [r for r in period_rows if not r['is_new_entry'] and not r['is_exit']]
        total_paf = sum(r['price_adj_flow'] or 0 for r in existing)
        active_paf = sum(r['price_adj_flow'] or 0 for r in existing if r['manager_type'] != 'passive')
        passive_paf = sum(r['price_adj_flow'] or 0 for r in existing if r['manager_type'] == 'passive')

        fi_total = total_paf / market_cap if market_cap and market_cap > 0 else None
        fi_active = active_paf / market_cap if market_cap and market_cap > 0 else None
        fi_passive = passive_paf / market_cap if market_cap and market_cap > 0 else None

        # Value-weighted churn — non-passive managers only
        def _value_churn(rows, type_filter):
            """Value-weighted churn: (value of entries + exits) / avg(from_value, to_value)."""
            filtered = [r for r in rows if type_filter(r.get('manager_type'))]
            q1_val = sum(r.get('from_value') or 0 for r in filtered if not r.get('is_new_entry'))
            q4_val = sum(r.get('to_value') or 0 for r in filtered if not r.get('is_exit'))
            ne_val = sum(r.get('to_value') or 0 for r in filtered if r.get('is_new_entry'))
            ex_val = sum(r.get('from_value') or 0 for r in filtered if r.get('is_exit'))
            avg_val = (q1_val + q4_val) / 2 if (q1_val + q4_val) > 0 else 1
            return (ne_val + ex_val) / avg_val

        is_nonpassive = lambda t: t != 'passive'
        is_active_only = lambda t: t in ('active',)

        churn_np = _value_churn(period_rows, is_nonpassive)
        churn_act = _value_churn(period_rows, is_active_only)

        con.execute("""
            INSERT INTO ticker_flow_stats VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [ticker, q_from, q_to, fi_total, fi_active, fi_passive,
              churn_np, churn_act, datetime.now()])


def main():
    con = duckdb.connect(get_db_path())
    print(f"Database: {get_db_path()}")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    create_tables(con)

    # Get all tickers with Q4 holdings + market cap
    tickers = con.execute(f"""
        SELECT DISTINCT h.ticker, m.market_cap
        FROM holdings h
        LEFT JOIN market_data m ON h.ticker = m.ticker
        WHERE h.quarter = '{LATEST_Q}' AND h.ticker IS NOT NULL AND h.ticker != ''
    """).fetchdf()

    total = len(tickers)
    print(f"Tickers to process: {total}")

    t0 = time.time()
    failed_tickers = []
    for i, (_, row) in enumerate(tickers.iterrows()):
        ticker = row['ticker']
        mktcap = float(row['market_cap']) if pd.notna(row['market_cap']) else None
        try:
            compute_ticker_flows(con, ticker, mktcap)
        except Exception as e:
            failed_tickers.append((ticker, str(e)))
            print(f"ERROR {ticker}: {e}")

        if (i + 1) % 500 == 0:
            elapsed = time.time() - t0
            rate = (i + 1) / elapsed
            eta = (total - i - 1) / rate / 60
            print(f"  [{i+1}/{total}] {elapsed:.0f}s elapsed, {rate:.1f} tickers/s, ETA {eta:.1f}m")

    elapsed = time.time() - t0
    print(f"\nCompleted: {total} tickers in {elapsed:.0f}s ({total/elapsed:.1f} tickers/s)")

    # Verify
    cnt = con.execute("SELECT COUNT(*) FROM investor_flows").fetchone()[0]
    cnt2 = con.execute("SELECT COUNT(*) FROM ticker_flow_stats").fetchone()[0]
    print(f"investor_flows: {cnt:,} rows")
    print(f"ticker_flow_stats: {cnt2:,} rows")

    if failed_tickers:
        print(f"\nFAILED TICKERS ({len(failed_tickers)}):")
        for tk, err in failed_tickers[:20]:
            print(f"  {tk}: {err}")
        if len(failed_tickers) > 20:
            print(f"  ... and {len(failed_tickers) - 20} more")

    con.close()

    if failed_tickers:
        sys.exit(1)


if __name__ == '__main__':
    main()
