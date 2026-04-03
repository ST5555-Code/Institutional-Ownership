"""
Flask web application for 13F institutional ownership research.
Replaces Jupyter notebook for day-to-day browser-based research.
"""

import argparse
import io
import os
import shutil
from datetime import datetime

import duckdb
import pandas as pd
from flask import Flask, jsonify, request, send_file
from config import QUARTERS, LATEST_QUARTER, FIRST_QUARTER, PREV_QUARTER

# Quarter constants used in SQL queries — imported from config.py.
# To roll forward: edit ONLY scripts/config.py. These vars propagate everywhere.
LQ = LATEST_QUARTER   # latest quarter for all queries (e.g. '{LQ}')
FQ = FIRST_QUARTER    # first quarter for comparisons (e.g. '{FQ}')
PQ = PREV_QUARTER     # previous quarter (e.g. '{PQ}')
from export import build_excel

import queries
from queries import (
    get_cusip, clean_for_json, df_to_records,
    query1, query2, query3, query4, query5,
    query6, query7, query8, query9, query10,
    query11, query12, query13, query14, query15,
    ownership_trend_summary, cohort_analysis, flow_analysis,
    get_summary, _cross_ownership_query,
)

QUERY_FUNCTIONS = {
    1: query1, 2: query2, 3: query3, 4: query4, 5: query5,
    6: query6, 7: query7, 8: query8, 9: query9, 10: query10,
    11: query11, 12: query12, 13: query13, 14: query14, 15: query15,
}

QUERY_NAMES = {
    1: 'Register', 2: 'Holder Changes', 3: 'Conviction',
    6: 'Activist', 7: 'Fund Portfolio', 8: 'Cross-Ownership',
    9: 'Sector Rotation', 10: 'New Positions', 11: 'Exits',
    14: 'AUM vs Position', 15: 'DB Statistics',
}

# ---------------------------------------------------------------------------
# Flask app setup
# ---------------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, 'data', '13f.duckdb')
DB_SNAPSHOT_PATH = os.path.join(BASE_DIR, 'data', '13f_readonly.duckdb')

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, 'web', 'templates'),
    static_folder=os.path.join(BASE_DIR, 'web', 'static'),
)


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def _resolve_db_path():
    """Return the best available database path.

    Try the main database first (read_only=True). If it is locked by a writer
    (e.g. fetch_nport.py), fall back to a snapshot copy so the web app can
    still serve data while the pipeline runs.
    """
    try:
        con = duckdb.connect(DB_PATH, read_only=True)
        con.close()
        return DB_PATH
    except Exception as e:
        app.logger.warning(f"[_resolve_db_path] Main DB locked: {e}")
        # Main DB is locked — use or create a snapshot
        if os.path.exists(DB_SNAPSHOT_PATH):
            return DB_SNAPSHOT_PATH
        # Create snapshot from the main DB
        try:
            print(f'  Database locked — creating read-only snapshot...')
            # Atomic copy: write to temp file, then rename (prevents corrupt snapshot)
            tmp_path = DB_SNAPSHOT_PATH + '.tmp'
            shutil.copy2(DB_PATH, tmp_path)
            os.replace(tmp_path, DB_SNAPSHOT_PATH)
            print(f'  Snapshot ready: {DB_SNAPSHOT_PATH}')
            return DB_SNAPSHOT_PATH
        except Exception as e2:
            raise RuntimeError(
                f'Cannot open database (locked) and cannot create snapshot: {e2}'
            )


# Resolved once at import/startup; updated if needed
import threading as _threading
_db_path_lock = _threading.Lock()
_active_db_path = None
_switchback_running = False
_available_tables = set()


def _start_switchback_monitor():
    """Background thread: check every 60s if primary DB is available again."""
    global _switchback_running
    if _switchback_running:
        return
    _switchback_running = True

    def _monitor():
        global _active_db_path, _switchback_running
        import time as _time
        while True:
            _time.sleep(60)
            with _db_path_lock:
                if _active_db_path == DB_PATH:
                    _switchback_running = False
                    return
            try:
                con = duckdb.connect(DB_PATH, read_only=True)
                con.close()
                with _db_path_lock:
                    _active_db_path = DB_PATH
                _refresh_table_list()
                app.logger.info("[switchback] Primary DB available — switched back from snapshot")
                _switchback_running = False
                return
            except Exception:
                pass

    t = _threading.Thread(target=_monitor, daemon=True)
    t.start()


def _refresh_table_list():
    """Cache available table names."""
    global _available_tables
    try:
        path = _active_db_path or _resolve_db_path()
        con = duckdb.connect(path, read_only=True)
        _available_tables = {t[0] for t in con.execute("SHOW TABLES").fetchall()}
        con.close()
    except Exception:
        pass


def has_table(name):
    """Check if a table exists (cached, no per-request query)."""
    if not _available_tables:
        _refresh_table_list()
    return name in _available_tables


def _init_db_path():
    """Resolve the database path at startup."""
    global _active_db_path
    _active_db_path = _resolve_db_path()
    _refresh_table_list()
    if _active_db_path != DB_PATH:
        _start_switchback_monitor()


def get_db():
    """Open a read-only DuckDB connection. Caller must close it."""
    global _active_db_path
    with _db_path_lock:
        if _active_db_path is None:
            _active_db_path = _resolve_db_path()
            _refresh_table_list()
            if _active_db_path != DB_PATH:
                _start_switchback_monitor()
        path = _active_db_path
    try:
        return duckdb.connect(path, read_only=True)
    except Exception as e:
        app.logger.warning(f"[get_db] Connection stale, re-resolving: {e}")
        with _db_path_lock:
            _active_db_path = _resolve_db_path()
            path = _active_db_path
        _refresh_table_list()
        if path != DB_PATH:
            _start_switchback_monitor()
        return duckdb.connect(_active_db_path, read_only=True)


# Initialize queries module with DB access functions
queries._setup(get_db, has_table)





# ---------------------------------------------------------------------------
# On-demand ticker add
# ---------------------------------------------------------------------------

@app.route('/api/add_ticker', methods=['POST'])
def api_add_ticker():
    """Add a single ticker on-demand: fetch CUSIP, market data, 13D/G filings."""
    ticker = request.json.get('ticker', '').upper().strip() if request.json else ''
    if not ticker:
        return jsonify({'error': 'Missing ticker'}), 400

    from db import PROD_DB
    results = {'ticker': ticker, 'steps': []}

    try:
        # Step 1: Resolve CUSIP via OpenFIGI
        import requests as req
        figi_resp = req.post(
            "https://api.openfigi.com/v3/mapping",
            json=[{"idType": "TICKER", "idValue": ticker}],
            timeout=10,
        )
        cusip = None
        if figi_resp.status_code == 200:
            data = figi_resp.json()
            if data and data[0].get('data'):
                cusip = data[0]['data'][0].get('figi')
                results['cusip'] = cusip
                results['steps'].append('OpenFIGI: resolved')
            else:
                results['steps'].append('OpenFIGI: no match')
        else:
            results['steps'].append(f'OpenFIGI: HTTP {figi_resp.status_code}')

        # Step 2: Fetch market data via yfinance
        import yfinance as yf
        tkr = yf.Ticker(ticker)
        info = tkr.info or {}
        if info.get('regularMarketPrice'):
            con = duckdb.connect(PROD_DB)
            from datetime import datetime
            now = datetime.now().strftime('%Y-%m-%d')
            con.execute("""
                INSERT OR REPLACE INTO market_data (ticker, price_live, market_cap,
                    float_shares, shares_outstanding, sector, industry, exchange, fetch_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [ticker, info.get('regularMarketPrice'), info.get('marketCap'),
                  info.get('floatShares'), info.get('sharesOutstanding'),
                  info.get('sector'), info.get('industry'), info.get('exchange'), now])
            con.execute("CHECKPOINT")
            con.close()
            results['market_cap'] = info.get('marketCap')
            results['price'] = info.get('regularMarketPrice')
            results['sector'] = info.get('sector')
            results['steps'].append('Market data: added')
        else:
            results['steps'].append('Market data: yfinance returned no price')

        # Step 3: Fetch 13D/G filings
        try:
            import edgar
            edgar.set_identity("serge.tismen@gmail.com")
            company = edgar.Company(ticker)
            filing_count = 0
            for form in ['SC 13D', 'SC 13G']:
                filings = company.get_filings(form=form)
                if filings:
                    for f in filings:
                        if str(f.filing_date) >= '2022-01-01':
                            filing_count += 1
            results['filings_found'] = filing_count
            results['steps'].append(f'13D/G: {filing_count} filings found (not parsed — run Phase 2)')
        except Exception as e:
            results['steps'].append(f'13D/G: {e}')

        results['status'] = 'ok'
        return jsonify(results)

    except Exception as e:
        results['status'] = 'error'
        results['error'] = str(e)
        return jsonify(results), 500


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------

@app.route('/admin')
def admin_page():
    from flask import render_template
    return render_template('admin.html')


@app.route('/api/admin/stats')
def api_admin_stats():
    """Database row counts for admin dashboard."""
    con = get_db()
    try:
        stats = {}
        for table, key in [('holdings', 'holdings'), ('managers', 'managers'),
                           ('beneficial_ownership', 'beneficial_ownership'),
                           ('fund_holdings', 'fund_holdings')]:
            try:
                stats[key] = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            except Exception:
                stats[key] = 0
        try:
            stats['tickers'] = con.execute("SELECT COUNT(DISTINCT ticker) FROM holdings WHERE ticker IS NOT NULL").fetchone()[0]
        except Exception:
            stats['tickers'] = 0
        try:
            stats['short_interest_days'] = con.execute("SELECT COUNT(DISTINCT report_date) FROM short_interest").fetchone()[0]
        except Exception:
            stats['short_interest_days'] = 0
        return jsonify(stats)
    finally:
        con.close()


@app.route('/api/admin/progress')
def api_admin_progress():
    """Check if a pipeline is running and return progress."""
    import subprocess
    result = {'running': False}

    # Check for running fetch_13dg process
    try:
        ps = subprocess.run(['pgrep', '-f', 'fetch_13dg.py'], capture_output=True, text=True)
        if ps.returncode == 0:
            result['running'] = True
    except Exception:
        pass

    # Read progress file
    progress_file = os.path.join(BASE_DIR, 'logs', 'phase2_progress.txt')
    try:
        with open(progress_file) as f:
            lines = f.read().strip().split('\n')
            if lines:
                result['progress_line'] = lines[0].strip()
                # Parse [N/M] pattern
                import re
                m = re.search(r'\[(\d+)/(\d+)\]', lines[0])
                if m:
                    done, total = int(m.group(1)), int(m.group(2))
                    result['pct'] = round(done / total * 100, 1) if total > 0 else 0
                    result['done'] = done
                    result['total'] = total
                if len(lines) > 1:
                    result['last_update'] = lines[1].strip()
    except FileNotFoundError:
        pass

    return jsonify(result)


@app.route('/api/admin/errors')
def api_admin_errors():
    """Return recent errors from fetch_13dg_errors.csv."""
    error_file = os.path.join(BASE_DIR, 'logs', 'fetch_13dg_errors.csv')
    try:
        with open(error_file) as f:
            lines = f.readlines()
        # Return last 20 lines
        recent = ''.join(lines[-20:]) if len(lines) > 20 else ''.join(lines)
        return jsonify({'errors': recent, 'count': len(lines) - 1})  # -1 for header
    except FileNotFoundError:
        return jsonify({'errors': 'No error log found', 'count': 0})


# ---------------------------------------------------------------------------
# Flask routes
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    from flask import render_template
    return render_template('index.html')


@app.route('/api/tickers')
def api_tickers():
    try:
        con = get_db()
    except Exception as e:
        return jsonify({'error': f'Database unavailable: {e}'}), 503
    try:
        df = con.execute(f"""
            SELECT ticker, MODE(issuer_name) as name
            FROM holdings
            WHERE ticker IS NOT NULL AND ticker != '' AND quarter = '{LQ}'
            GROUP BY ticker
            ORDER BY ticker
        """).fetchdf()
        return jsonify(df_to_records(df))
    finally:
        con.close()


@app.route('/api/fund_portfolio_managers')
def api_fund_portfolio_managers():
    ticker = request.args.get('ticker', '').upper().strip()
    if not ticker:
        return jsonify({'error': 'Missing ticker parameter'}), 400
    try:
        con = get_db()
    except Exception as e:
        return jsonify({'error': f'Database unavailable: {e}'}), 503
    try:
        df = con.execute(f"""
            SELECT
                cik,
                fund_name,
                MAX(COALESCE(inst_parent_name, manager_name)) as inst_parent_name,
                SUM(market_value_live) as position_value,
                MAX(manager_type) as manager_type
            FROM holdings
            WHERE ticker = ? AND quarter = '{LQ}'
              AND manager_type NOT IN ('passive')
            GROUP BY cik, fund_name
            ORDER BY position_value DESC NULLS LAST
            LIMIT 50
        """, [ticker]).fetchdf()
        return jsonify(df_to_records(df))
    finally:
        con.close()


@app.route('/api/nport_shorts')
def api_nport_shorts():
    """N-PORT negative balance positions — fund short positions from filings."""
    ticker = request.args.get('ticker', '').upper().strip()
    con = get_db()
    try:
        where = "AND fh.ticker = ?" if ticker else ""
        params = [ticker] if ticker else []
        df = con.execute(f"""
            SELECT
                fh.fund_name,
                fh.ticker,
                fh.issuer_name,
                fh.shares_or_principal AS shares_short,
                fh.market_value_usd AS short_value,
                fh.pct_of_nav,
                fh.quarter,
                fh.family_name
            FROM fund_holdings fh
            WHERE fh.shares_or_principal < 0
              AND fh.asset_category IN ('EC', 'EP')
              {where}
            ORDER BY fh.market_value_usd ASC
            LIMIT 200
        """, params).fetchdf()
        return jsonify(df_to_records(df))
    finally:
        con.close()


@app.route('/api/short_volume')
def api_short_volume():
    """FINRA daily short sale volume for a ticker."""
    ticker = request.args.get('ticker', '').upper().strip()
    if not ticker:
        return jsonify({'error': 'Missing ticker parameter'}), 400
    con = get_db()
    try:
        if not has_table('short_interest'):
            return jsonify({'error': 'short_interest table not loaded — run fetch_finra_short.py'}), 404
        df = con.execute("""
            SELECT report_date, short_volume, total_volume, short_pct
            FROM short_interest
            WHERE ticker = ?
            ORDER BY report_date DESC
            LIMIT 60
        """, [ticker]).fetchdf()
        return jsonify(df_to_records(df))
    finally:
        con.close()


@app.route('/api/fund_behavioral_profile')
def api_fund_behavioral_profile():
    """Behavioral profile for a fund by LEI or series_id — analyzes historical positions."""
    lei = request.args.get('lei', '').strip()
    series_id = request.args.get('series_id', '').strip()
    if not lei and not series_id:
        return jsonify({'error': 'Missing lei or series_id parameter'}), 400

    con = get_db()
    try:
        # Find matching fund
        if lei:
            where = "lei = ?"
            param = lei
        else:
            where = "series_id = ?"
            param = series_id

        # Fund identity
        fund_info = con.execute(f"""
            SELECT fund_name, series_id, lei, family_name, COUNT(DISTINCT quarter) as quarters
            FROM fund_holdings WHERE {where}
            GROUP BY fund_name, series_id, lei, family_name
            LIMIT 1
        """, [param]).fetchone()
        if not fund_info:
            return jsonify({'error': 'Fund not found'}), 404

        fund_name, sid, fund_lei, family, quarters = fund_info

        # Position size distribution (avg % of NAV)
        size_stats = con.execute(f"""
            SELECT
                AVG(pct_of_nav) as avg_pct_nav,
                MEDIAN(pct_of_nav) as median_pct_nav,
                MAX(pct_of_nav) as max_pct_nav,
                COUNT(DISTINCT ticker) as unique_holdings,
                COUNT(DISTINCT quarter) as quarters_held
            FROM fund_holdings
            WHERE {where} AND pct_of_nav IS NOT NULL AND pct_of_nav > 0
        """, [param]).fetchone()

        # Sector concentration
        sector_where = f"fh.lei = ?" if lei else f"fh.series_id = ?"
        sectors = con.execute(f"""
            SELECT s.sector, SUM(fh.market_value_usd) as sector_value
            FROM fund_holdings fh
            JOIN securities s ON fh.cusip = s.cusip
            WHERE {sector_where}
              AND fh.quarter = '{LQ}'
              AND s.sector IS NOT NULL AND s.sector != ''
            GROUP BY s.sector
            ORDER BY sector_value DESC
            LIMIT 10
        """, [param]).fetchdf()

        # Top holdings
        top = con.execute(f"""
            SELECT ticker, issuer_name, market_value_usd, pct_of_nav, shares_or_principal
            FROM fund_holdings
            WHERE {where} AND quarter = '{LQ}'
            ORDER BY market_value_usd DESC NULLS LAST
            LIMIT 10
        """, [param]).fetchdf()

        return jsonify(clean_for_json({
            'fund_name': fund_name,
            'series_id': sid,
            'lei': fund_lei,
            'family': family,
            'quarters_covered': quarters,
            'stats': {
                'avg_position_pct': size_stats[0] if size_stats else None,
                'median_position_pct': size_stats[1] if size_stats else None,
                'max_position_pct': size_stats[2] if size_stats else None,
                'unique_holdings': size_stats[3] if size_stats else 0,
            },
            'sector_breakdown': df_to_records(sectors),
            'top_holdings': df_to_records(top),
        }))
    finally:
        con.close()


@app.route('/api/ownership_trend_summary')
def api_ownership_trend_summary():
    ticker = request.args.get('ticker', '').upper().strip()
    if not ticker:
        return jsonify({'error': 'Missing ticker parameter'}), 400
    try:
        result = ownership_trend_summary(ticker)
        return jsonify(clean_for_json(result))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/cohort_analysis')
def api_cohort_analysis():
    ticker = request.args.get('ticker', '').upper().strip()
    if not ticker:
        return jsonify({'error': 'Missing ticker parameter'}), 400
    try:
        result = cohort_analysis(ticker)
        return jsonify(clean_for_json(result))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/flow_analysis')
def api_flow_analysis():
    ticker = request.args.get('ticker', '').upper().strip()
    period = request.args.get('period', '4Q').upper().strip()
    peers = request.args.get('peers', '').upper().strip() or None
    if not ticker:
        return jsonify({'error': 'Missing ticker parameter'}), 400
    try:
        result = flow_analysis(ticker, period=period, peers=peers)
        return jsonify(clean_for_json(result))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def api_cross_ownership():
    """View 1: top holders of anchor company with cross-holdings in other tickers."""
    tickers_raw = request.args.get('tickers', '').upper().strip()
    anchor = request.args.get('anchor', '').upper().strip()
    active_only = request.args.get('active_only', 'false').lower() == 'true'
    limit = int(request.args.get('limit', 25))
    if not tickers_raw:
        return jsonify({'error': 'Missing tickers parameter'}), 400
    tickers = [t.strip() for t in tickers_raw.split(',') if t.strip()][:10]
    if not anchor:
        anchor = tickers[0]
    try:
        con = get_db()
    except Exception as e:
        return jsonify({'error': f'Database unavailable: {e}'}), 503
    try:
        return jsonify(_cross_ownership_query(con, tickers, anchor=anchor,
                                              active_only=active_only, limit=limit))
    finally:
        con.close()


@app.route('/api/cross_ownership_top')
def api_cross_ownership_top():
    """View 2: top investors by total exposure across all selected tickers."""
    tickers_raw = request.args.get('tickers', '').upper().strip()
    active_only = request.args.get('active_only', 'false').lower() == 'true'
    limit = int(request.args.get('limit', 25))
    if not tickers_raw:
        return jsonify({'error': 'Missing tickers parameter'}), 400
    tickers = [t.strip() for t in tickers_raw.split(',') if t.strip()][:10]
    try:
        con = get_db()
    except Exception as e:
        return jsonify({'error': f'Database unavailable: {e}'}), 503
    try:
        return jsonify(_cross_ownership_query(con, tickers, anchor=None,
                                              active_only=active_only, limit=limit))
    finally:
        con.close()


@app.route('/api/peer_groups')
def api_peer_groups():
    """Return all peer groups."""
    con = get_db()
    try:
        if not has_table('peer_groups'):
            return jsonify([])
        df = con.execute("""
            SELECT group_id, group_name, ticker, company_name, is_primary
            FROM peer_groups
            ORDER BY group_name, is_primary DESC, ticker
        """).fetchdf()
        # Group by group_id
        groups = {}
        for _, row in df.iterrows():
            gid = row['group_id']
            if gid not in groups:
                groups[gid] = {
                    'group_id': gid,
                    'group_name': row['group_name'],
                    'tickers': [],
                }
            groups[gid]['tickers'].append({
                'ticker': row['ticker'],
                'company_name': row['company_name'],
                'is_primary': bool(row['is_primary']),
            })
        return jsonify(list(groups.values()))
    finally:
        con.close()


@app.route('/api/peer_groups/<group_id>')
def api_peer_group_detail(group_id):
    """Return tickers in a specific peer group."""
    con = get_db()
    try:
        df = con.execute("""
            SELECT ticker, company_name, is_primary
            FROM peer_groups
            WHERE group_id = ?
            ORDER BY is_primary DESC, ticker
        """, [group_id]).fetchdf()
        return jsonify(df_to_records(df))
    finally:
        con.close()


@app.route('/api/crowding')
def api_crowding():
    """Crowding analysis: institutional concentration + short interest overlay."""
    ticker = request.args.get('ticker', '').upper().strip()
    if not ticker:
        return jsonify({'error': 'Missing ticker parameter'}), 400
    con = get_db()
    try:
        # Top holders by % of float
        holders = con.execute(f"""
            SELECT COALESCE(inst_parent_name, manager_name) as holder,
                   manager_type, SUM(pct_of_float) as pct_float,
                   SUM(market_value_live) as value
            FROM holdings WHERE ticker = ? AND quarter = '2025Q4'
            GROUP BY holder, manager_type
            ORDER BY pct_float DESC NULLS LAST LIMIT 20
        """, [ticker]).fetchdf()
        result = {'holders': df_to_records(holders)}
        # Short interest overlay
        if has_table('short_interest'):
            si = con.execute("""
                SELECT report_date, short_volume, total_volume, short_pct
                FROM short_interest WHERE ticker = ?
                ORDER BY report_date DESC LIMIT 20
            """, [ticker]).fetchdf()
            result['short_history'] = df_to_records(si)
        return jsonify(clean_for_json(result))
    finally:
        con.close()


@app.route('/api/smart_money')
def api_smart_money():
    """Smart Money: net exposure view — long 13F vs short FINRA per manager type."""
    ticker = request.args.get('ticker', '').upper().strip()
    if not ticker:
        return jsonify({'error': 'Missing ticker parameter'}), 400
    con = get_db()
    try:
        # Long positions by manager type
        longs = con.execute(f"""
            SELECT manager_type, COUNT(DISTINCT cik) as holders,
                   SUM(shares) as long_shares, SUM(market_value_live) as long_value
            FROM holdings WHERE ticker = ? AND quarter = '2025Q4'
            GROUP BY manager_type ORDER BY long_value DESC NULLS LAST
        """, [ticker]).fetchdf()
        result = {'long_by_type': df_to_records(longs)}
        # Latest short volume
        if has_table('short_interest'):
            si = con.execute("""
                SELECT short_volume, total_volume, short_pct, report_date
                FROM short_interest WHERE ticker = ?
                ORDER BY report_date DESC LIMIT 1
            """, [ticker]).fetchone()
            if si:
                result['short_volume'] = si[0]
                result['short_pct'] = si[2]
                result['short_date'] = str(si[3])
        # N-PORT short positions for this ticker
        if has_table('fund_holdings'):
            nport_shorts = con.execute("""
                SELECT fund_name, shares_or_principal as shares_short,
                       market_value_usd as short_value, quarter
                FROM fund_holdings
                WHERE ticker = ? AND shares_or_principal < 0
                  AND asset_category IN ('EC', 'EP')
                ORDER BY market_value_usd ASC LIMIT 10
            """, [ticker]).fetchdf()
            result['nport_shorts'] = df_to_records(nport_shorts)
        return jsonify(clean_for_json(result))
    finally:
        con.close()


@app.route('/api/summary')
def api_summary():
    ticker = request.args.get('ticker', '').upper().strip()
    if not ticker:
        return jsonify({'error': 'Missing ticker parameter'}), 400
    result = get_summary(ticker)
    if not result:
        return jsonify({'error': f'No data found for ticker {ticker}'}), 404
    return jsonify(result)


@app.route('/api/query<int:qnum>')
def api_query(qnum):
    if qnum not in QUERY_FUNCTIONS:
        return jsonify({'error': f'Invalid query number: {qnum}'}), 400
    ticker = request.args.get('ticker', '').upper().strip()
    cik = request.args.get('cik', '').strip()

    # Queries 13 and 15 do not require a ticker
    if qnum not in (13, 15) and not ticker:
        return jsonify({'error': 'Missing ticker parameter'}), 400

    try:
        fn = QUERY_FUNCTIONS[qnum]
        if qnum == 7:
            fund_name = request.args.get('fund_name', '').strip() or None
            data = fn(ticker, cik=cik or None, fund_name=fund_name)
            # query7 returns {stats, positions} dict
            if not data.get('positions'):
                return jsonify({'error': f'No holdings found for CIK {cik}'}), 404
            return jsonify(data)
        elif qnum in (13, 15):
            data = fn(ticker or None)
        else:
            data = fn(ticker)

        if not data:
            return jsonify({'error': f'No data found for ticker {ticker}'}), 404
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/export/query<int:qnum>')
def api_export(qnum):
    if qnum not in QUERY_FUNCTIONS:
        return jsonify({'error': f'Invalid query number: {qnum}'}), 400
    ticker = request.args.get('ticker', '').upper().strip()
    cik = request.args.get('cik', '').strip()

    if qnum not in (13, 15) and not ticker:
        return jsonify({'error': 'Missing ticker parameter'}), 400

    try:
        fn = QUERY_FUNCTIONS[qnum]
        if qnum == 7:
            fund_name = request.args.get('fund_name', '').strip() or None
            data = fn(ticker, cik=cik or None, fund_name=fund_name)
        elif qnum in (13, 15):
            data = fn(ticker or None)
        else:
            data = fn(ticker)

        if not data:
            return jsonify({'error': f'No data found for ticker {ticker}'}), 404

        # Q7 returns {stats, positions} — export the positions list
        export_data = data.get('positions', data) if isinstance(data, dict) and 'positions' in data else data
        qname = QUERY_NAMES.get(qnum, f'Query{qnum}')
        sheet_name = f"{qname} - {ticker or 'ALL'}"
        buf = build_excel(export_data, sheet_name=sheet_name)

        filename = f"query{qnum}_{ticker or 'ALL'}_{datetime.now().strftime('%Y%m%d')}.xlsx"
        return send_file(
            buf,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=filename,
        )
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='13F Ownership Research Web App')
    parser.add_argument('--port', type=int, default=8001, help='Port to run on (default: 8001)')
    args = parser.parse_args()

    # Check PORT env var (for Render deployment)
    port = int(os.environ.get('PORT', args.port))

    # Resolve database path at startup (creates snapshot if main DB is locked)
    _init_db_path()
    queries._setup(get_db, has_table)

    print()
    print('  13F Ownership Research')
    print(f'  Database: {_active_db_path}')
    if _active_db_path != DB_PATH:
        print(f'  (main DB locked — serving from snapshot)')
    print(f'  Running at: http://localhost:{port}')
    print()

    app.run(host='0.0.0.0', port=port, debug=False)
