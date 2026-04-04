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
    query11, query12, query13, query14, query15, query16,
    ownership_trend_summary, cohort_analysis, flow_analysis,
    get_summary, _cross_ownership_query,
)

QUERY_FUNCTIONS = {
    1: query1, 2: query2, 3: query3, 4: query4, 5: query5,
    6: query6, 7: query7, 8: query8, 9: query9, 10: query10,
    11: query11, 12: query12, 13: query13, 14: query14, 15: query15,
    16: query16,
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


_conn_local = _threading.local()


def get_db():
    """Get a read-only DuckDB connection. Uses thread-local cache to avoid
    reopening on every request. Caller should NOT close it."""
    global _active_db_path
    with _db_path_lock:
        if _active_db_path is None:
            _active_db_path = _resolve_db_path()
            _refresh_table_list()
            if _active_db_path != DB_PATH:
                _start_switchback_monitor()
        path = _active_db_path

    # Thread-local connection cache
    cached = getattr(_conn_local, 'con', None)
    cached_path = getattr(_conn_local, 'path', None)
    if cached and cached_path == path:
        try:
            cached.execute("SELECT 1")  # verify alive
            return cached
        except Exception:
            pass  # stale — reopen

    try:
        con = duckdb.connect(path, read_only=True)
        _conn_local.con = con
        _conn_local.path = path
        return con
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


@app.route('/api/admin/run_script', methods=['POST'])
def api_admin_run_script():
    """Run a pipeline script in the background. Returns immediately."""
    import subprocess
    data = request.json or {}
    script = data.get('script', '')
    flags = data.get('flags', [])

    # Whitelist of allowed scripts
    allowed = {
        'fetch_13dg.py', 'fetch_nport.py', 'fetch_market.py',
        'fetch_finra_short.py', 'fetch_ncen.py', 'compute_flows.py',
        'build_cusip.py', 'build_summaries.py', 'unify_positions.py',
        'run_pipeline.sh', 'merge_staging.py', 'refresh_snapshot.sh',
    }
    if script not in allowed:
        return jsonify({'error': f'Script not allowed: {script}'}), 400

    # Check if already running
    try:
        ps = subprocess.run(['pgrep', '-f', script], capture_output=True, text=True)
        if ps.returncode == 0:
            return jsonify({'error': f'{script} is already running'}), 409
    except Exception:
        pass

    # Build command
    script_path = os.path.join(BASE_DIR, 'scripts', script)
    if script.endswith('.sh'):
        cmd = ['bash', script_path] + flags
    else:
        cmd = ['python3', '-u', script_path] + flags

    # Run in background
    log_name = script.replace('.py', '').replace('.sh', '')
    log_path = os.path.join(BASE_DIR, 'logs', f'{log_name}_run.log')
    with open(log_path, 'w') as log_file:
        proc = subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT, cwd=BASE_DIR)

    return jsonify({
        'status': 'started',
        'script': script,
        'flags': flags,
        'pid': proc.pid,
        'log': log_path,
    })


@app.route('/api/admin/manager_changes')
def api_admin_manager_changes():
    """D2: Detect manager changes across quarters — new, disappeared, name changes."""
    con = get_db()
    try:
        from config import LATEST_QUARTER, PREV_QUARTER
        # New managers (in latest quarter but not previous)
        new_mgrs = con.execute(f"""
            SELECT DISTINCT cik, manager_name, manager_type
            FROM holdings WHERE quarter = '{LATEST_QUARTER}'
              AND cik NOT IN (SELECT DISTINCT cik FROM holdings WHERE quarter = '{PREV_QUARTER}')
            ORDER BY manager_name LIMIT 50
        """).fetchdf()
        # Disappeared managers
        gone_mgrs = con.execute(f"""
            SELECT DISTINCT cik, manager_name, manager_type
            FROM holdings WHERE quarter = '{PREV_QUARTER}'
              AND cik NOT IN (SELECT DISTINCT cik FROM holdings WHERE quarter = '{LATEST_QUARTER}')
            ORDER BY manager_name LIMIT 50
        """).fetchdf()
        return jsonify(clean_for_json({
            'new_managers': df_to_records(new_mgrs),
            'disappeared_managers': df_to_records(gone_mgrs),
            'latest_quarter': LATEST_QUARTER,
            'prev_quarter': PREV_QUARTER,
        }))
    finally:
        con.close()


@app.route('/api/admin/ticker_changes')
def api_admin_ticker_changes():
    """D3: Detect ticker changes — new tickers, disappeared tickers."""
    con = get_db()
    try:
        from config import LATEST_QUARTER, PREV_QUARTER
        new_tickers = con.execute(f"""
            SELECT DISTINCT ticker, MAX(issuer_name) as company
            FROM holdings WHERE quarter = '{LATEST_QUARTER}' AND ticker IS NOT NULL
              AND ticker NOT IN (SELECT DISTINCT ticker FROM holdings WHERE quarter = '{PREV_QUARTER}' AND ticker IS NOT NULL)
            GROUP BY ticker ORDER BY ticker LIMIT 100
        """).fetchdf()
        gone_tickers = con.execute(f"""
            SELECT DISTINCT ticker, MAX(issuer_name) as company
            FROM holdings WHERE quarter = '{PREV_QUARTER}' AND ticker IS NOT NULL
              AND ticker NOT IN (SELECT DISTINCT ticker FROM holdings WHERE quarter = '{LATEST_QUARTER}' AND ticker IS NOT NULL)
            GROUP BY ticker ORDER BY ticker LIMIT 100
        """).fetchdf()
        return jsonify(clean_for_json({
            'new_tickers': df_to_records(new_tickers),
            'disappeared_tickers': df_to_records(gone_tickers),
        }))
    finally:
        con.close()


@app.route('/api/admin/parent_mapping_health')
def api_admin_parent_health():
    """D4: Check parent mapping health — orphaned CIKs, unmatched managers."""
    con = get_db()
    try:
        # Managers without parent assignment
        orphaned = con.execute(f"""
            SELECT cik, manager_name, manager_type,
                   SUM(market_value_live) as total_value
            FROM holdings
            WHERE quarter = '{LQ}' AND inst_parent_name IS NULL
            GROUP BY cik, manager_name, manager_type
            ORDER BY total_value DESC NULLS LAST
            LIMIT 20
        """).fetchdf()
        # Top parents by value
        top_parents = con.execute(f"""
            SELECT inst_parent_name, COUNT(DISTINCT cik) as child_ciks,
                   SUM(market_value_live) as total_value
            FROM holdings WHERE quarter = '{LQ}' AND inst_parent_name IS NOT NULL
            GROUP BY inst_parent_name
            ORDER BY total_value DESC NULLS LAST LIMIT 20
        """).fetchdf()
        return jsonify(clean_for_json({
            'orphaned_managers': df_to_records(orphaned),
            'top_parents': df_to_records(top_parents),
        }))
    finally:
        con.close()


@app.route('/api/admin/stale_data')
def api_admin_stale_data():
    """D5: Flag stale data — old market data, inactive managers."""
    con = get_db()
    try:
        result = {}
        # Tickers with old market data
        try:
            stale_market = con.execute("""
                SELECT ticker, fetch_date, price_live
                FROM market_data
                WHERE fetch_date < CURRENT_DATE - INTERVAL '30' DAY
                ORDER BY fetch_date ASC LIMIT 20
            """).fetchdf()
            result['stale_market_data'] = df_to_records(stale_market)
        except Exception:
            result['stale_market_data'] = []
        # Managers only in old quarters
        try:
            inactive = con.execute(f"""
                SELECT cik, manager_name, MAX(quarter) as last_quarter
                FROM holdings
                GROUP BY cik, manager_name
                HAVING MAX(quarter) < '{PQ}'
                ORDER BY last_quarter DESC LIMIT 20
            """).fetchdf()
            result['inactive_managers'] = df_to_records(inactive)
        except Exception:
            result['inactive_managers'] = []
        return jsonify(clean_for_json(result))
    finally:
        con.close()


@app.route('/api/admin/merger_signals')
def api_admin_merger_signals():
    """D6: Detect potential mergers — CIK disappears + another CIK's holdings jump."""
    con = get_db()
    try:
        from config import LATEST_QUARTER, PREV_QUARTER
        # CIKs that disappeared AND had large holdings
        signals = con.execute(f"""
            WITH gone AS (
                SELECT cik, manager_name, SUM(market_value_usd) as prev_value
                FROM holdings WHERE quarter = '{PREV_QUARTER}'
                  AND cik NOT IN (SELECT DISTINCT cik FROM holdings WHERE quarter = '{LATEST_QUARTER}')
                GROUP BY cik, manager_name
                HAVING SUM(market_value_usd) > 1000000
            )
            SELECT * FROM gone ORDER BY prev_value DESC LIMIT 20
        """).fetchdf()
        return jsonify(clean_for_json({
            'potential_mergers': df_to_records(signals),
        }))
    finally:
        con.close()


@app.route('/api/admin/new_companies')
def api_admin_new_companies():
    """D7: New companies with institutional interest — recent entries."""
    con = get_db()
    try:
        from config import LATEST_QUARTER, PREV_QUARTER
        # Tickers that appeared in latest quarter with significant institutional value
        new_cos = con.execute(f"""
            SELECT h.ticker, MAX(h.issuer_name) as company,
                   COUNT(DISTINCT h.cik) as holder_count,
                   SUM(h.market_value_live) as total_value,
                   MAX(m.sector) as sector
            FROM holdings h
            LEFT JOIN market_data m ON h.ticker = m.ticker
            WHERE h.quarter = '{LATEST_QUARTER}' AND h.ticker IS NOT NULL
              AND h.ticker NOT IN (
                  SELECT DISTINCT ticker FROM holdings
                  WHERE quarter = '{PREV_QUARTER}' AND ticker IS NOT NULL
              )
            GROUP BY h.ticker
            HAVING SUM(h.market_value_live) > 10000000
            ORDER BY total_value DESC LIMIT 30
        """).fetchdf()
        return jsonify(clean_for_json({
            'new_companies': df_to_records(new_cos),
        }))
    finally:
        con.close()


@app.route('/api/admin/data_quality')
def api_admin_data_quality():
    """F6: Data quality metrics — coverage, parse rates, gaps."""
    con = get_db()
    try:
        result = {}
        # Holdings coverage
        try:
            r = con.execute(f"""
                SELECT
                    COUNT(*) as total,
                    COUNT(ticker) as with_ticker,
                    COUNT(market_value_live) as with_live_value,
                    COUNT(pct_of_float) as with_float_pct
                FROM holdings WHERE quarter = '{LQ}'
            """).fetchone()
            result['holdings'] = {
                'total': r[0], 'with_ticker': r[1],
                'with_live_value': r[2], 'with_float_pct': r[3],
                'ticker_pct': round(r[1] / r[0] * 100, 1) if r[0] else 0,
                'live_value_pct': round(r[2] / r[0] * 100, 1) if r[0] else 0,
            }
        except Exception:
            result['holdings'] = {}
        # 13D/G parse quality
        try:
            r = con.execute("""
                SELECT COUNT(*) as total,
                    COUNT(pct_owned) as with_pct,
                    COUNT(shares_owned) as with_shares,
                    COUNT(CASE WHEN filer_name IS NULL OR filer_name = ''
                               OR regexp_matches(filer_name, '^\\d{7,10}$') THEN 1 END) as unknown_filers
                FROM beneficial_ownership
            """).fetchone()
            bo_stats = {
                'total': r[0], 'with_pct': r[1], 'with_shares': r[2],
                'unknown_filers': r[3],
                'pct_coverage': round(r[1] / r[0] * 100, 1) if r[0] else 0,
            }
            # Name resolution stats if column exists
            try:
                nr = con.execute("""
                    SELECT COUNT(CASE WHEN name_resolved THEN 1 END) as resolved,
                           COUNT(CASE WHEN NOT name_resolved OR name_resolved IS NULL THEN 1 END) as unresolved
                    FROM beneficial_ownership
                """).fetchone()
                bo_stats['name_resolved'] = nr[0]
                bo_stats['name_unresolved'] = nr[1]
                bo_stats['name_resolution_pct'] = round(nr[0] / (nr[0] + nr[1]) * 100, 1) if (nr[0] + nr[1]) else 0
            except Exception:
                pass
            result['beneficial_ownership'] = bo_stats
        except Exception:
            result['beneficial_ownership'] = {}
        # Error log stats
        error_file = os.path.join(BASE_DIR, 'logs', 'fetch_13dg_errors.csv')
        try:
            with open(error_file) as f:
                error_count = sum(1 for _ in f) - 1
            result['fetch_errors'] = error_count
        except FileNotFoundError:
            result['fetch_errors'] = 0
        return jsonify(result)
    finally:
        con.close()


@app.route('/api/admin/quarter_config')
def api_admin_quarter_config():
    """F7: Show current quarter configuration."""
    from config import QUARTERS, QUARTER_URLS, QUARTER_REPORT_DATES, QUARTER_SNAPSHOT_DATES
    return jsonify({
        'quarters': QUARTERS,
        'urls': QUARTER_URLS,
        'report_dates': QUARTER_REPORT_DATES,
        'snapshot_dates': QUARTER_SNAPSHOT_DATES,
        'config_file': os.path.join(BASE_DIR, 'scripts', 'config.py'),
    })


@app.route('/api/admin/staging_preview')
def api_admin_staging_preview():
    """F5: Preview what merge_staging would do (dry-run)."""
    import subprocess
    script_path = os.path.join(BASE_DIR, 'scripts', 'merge_staging.py')
    try:
        result = subprocess.run(
            ['python3', script_path, '--all', '--dry-run'],
            capture_output=True, text=True, timeout=30, cwd=BASE_DIR,
        )
        return jsonify({
            'output': result.stdout,
            'error': result.stderr if result.returncode != 0 else None,
            'returncode': result.returncode,
        })
    except subprocess.TimeoutExpired:
        return jsonify({'error': 'Preview timed out after 30s'}), 504
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/running')
def api_admin_running():
    """List currently running pipeline scripts."""
    import subprocess
    running = []
    for script in ['fetch_13dg.py', 'fetch_nport.py', 'fetch_market.py',
                    'fetch_finra_short.py', 'compute_flows.py', 'merge_staging.py']:
        try:
            ps = subprocess.run(['pgrep', '-f', script], capture_output=True, text=True)
            if ps.returncode == 0:
                pids = ps.stdout.strip().split('\n')
                running.append({'script': script, 'pids': pids})
        except Exception:
            pass
    return jsonify({'running': running})


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
    from_q = request.args.get('from', '').strip() or None
    level = request.args.get('level', 'parent').strip()
    active_only = request.args.get('active_only', '').strip() == 'true'
    if not ticker:
        return jsonify({'error': 'Missing ticker parameter'}), 400
    try:
        result = cohort_analysis(ticker, from_quarter=from_q, level=level, active_only=active_only)
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


@app.route('/api/cross_ownership')
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
            FROM holdings WHERE ticker = ? AND quarter = '{LQ}'
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
            FROM holdings WHERE ticker = ? AND quarter = '{LQ}'
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


@app.route('/api/short_long')
def api_short_long():
    """Short vs Long comparison: managers long via 13F and short via N-PORT."""
    ticker = request.args.get('ticker', '').upper().strip()
    if not ticker:
        return jsonify({'error': 'Missing ticker parameter'}), 400
    try:
        from queries import get_short_long_comparison
        result = get_short_long_comparison(ticker)
        return jsonify(result)
    except Exception as e:
        app.logger.error(f"short_long error for {ticker}: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/short_squeeze')
def api_short_squeeze():
    """Short squeeze candidates: high crowding + high short interest."""
    try:
        from queries import get_short_squeeze_candidates
        result = get_short_squeeze_candidates()
        return jsonify({'candidates': result})
    except Exception as e:
        app.logger.error(f"short_squeeze error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/heatmap')
def api_heatmap():
    """Ownership concentration heatmap: top managers × tickers by pct_of_float."""
    ticker = request.args.get('ticker', '').upper().strip()
    peers = request.args.get('peers', '').upper().strip()
    con = get_db()
    try:
        # Build ticker list: current ticker + peers (comma-separated)
        tickers = [ticker] if ticker else []
        if peers:
            tickers += [t.strip() for t in peers.split(',') if t.strip()]
        if not tickers:
            # Default: top 10 tickers by institutional value
            top = con.execute(f"""
                SELECT ticker, SUM(market_value_usd) as val
                FROM holdings WHERE quarter = '{LQ}' AND ticker IS NOT NULL
                GROUP BY ticker ORDER BY val DESC LIMIT 10
            """).fetchall()
            tickers = [r[0] for r in top]

        # Top 15 managers by total value across these tickers
        ticker_ph = ','.join(['?'] * len(tickers))
        managers = con.execute(f"""
            SELECT inst_parent_name, SUM(market_value_usd) as total_val
            FROM holdings
            WHERE quarter = '{LQ}' AND ticker IN ({ticker_ph})
              AND inst_parent_name IS NOT NULL
            GROUP BY inst_parent_name
            ORDER BY total_val DESC LIMIT 15
        """, tickers).fetchall()
        manager_names = [r[0] for r in managers]

        if not manager_names:
            return jsonify({'tickers': tickers, 'managers': [], 'cells': []})

        # Build the matrix: pct_of_float for each manager × ticker
        mgr_ph = ','.join(['?'] * len(manager_names))
        cells = con.execute(f"""
            SELECT inst_parent_name as manager, ticker,
                   SUM(pct_of_float) as pct_float,
                   SUM(shares) as shares,
                   SUM(market_value_usd) as value
            FROM holdings
            WHERE quarter = '{LQ}'
              AND ticker IN ({ticker_ph})
              AND inst_parent_name IN ({mgr_ph})
            GROUP BY inst_parent_name, ticker
        """, tickers + manager_names).fetchdf()

        return jsonify(clean_for_json({
            'tickers': tickers,
            'managers': manager_names,
            'cells': df_to_records(cells),
        }))
    except Exception as e:
        app.logger.error(f"heatmap error: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        con.close()


@app.route('/api/manager_profile')
def api_manager_profile():
    """Manager profile: all holdings, sector allocation, top positions."""
    manager = request.args.get('manager', '').strip()
    if not manager:
        return jsonify({'error': 'Missing manager parameter'}), 400
    con = get_db()
    try:
        # Top holdings
        holdings = con.execute(f"""
            SELECT ticker, issuer_name, shares, market_value_usd, market_value_live,
                   pct_of_portfolio, pct_of_float
            FROM holdings
            WHERE quarter = '{LQ}' AND inst_parent_name ILIKE ?
            ORDER BY market_value_usd DESC LIMIT 50
        """, [f'%{manager}%']).fetchdf()

        # Sector allocation
        sectors = con.execute(f"""
            SELECT m.sector, COUNT(DISTINCT h.ticker) as tickers,
                   SUM(h.market_value_usd) as value
            FROM holdings h
            LEFT JOIN market_data m ON h.ticker = m.ticker
            WHERE h.quarter = '{LQ}' AND h.inst_parent_name ILIKE ?
              AND m.sector IS NOT NULL
            GROUP BY m.sector ORDER BY value DESC
        """, [f'%{manager}%']).fetchdf()

        # Summary stats
        stats = con.execute(f"""
            SELECT COUNT(DISTINCT ticker) as num_positions,
                   SUM(market_value_usd) as total_value,
                   COUNT(DISTINCT cik) as num_ciks,
                   MAX(manager_type) as manager_type
            FROM holdings
            WHERE quarter = '{LQ}' AND inst_parent_name ILIKE ?
        """, [f'%{manager}%']).fetchone()

        # Quarter-over-quarter change
        qoq = con.execute(f"""
            SELECT quarter, COUNT(DISTINCT ticker) as positions,
                   SUM(market_value_usd) as total_value
            FROM holdings WHERE inst_parent_name ILIKE ?
            GROUP BY quarter ORDER BY quarter
        """, [f'%{manager}%']).fetchdf()

        result = {
            'manager': manager,
            'num_positions': stats[0] if stats else 0,
            'total_value': stats[1] if stats else 0,
            'num_ciks': stats[2] if stats else 0,
            'manager_type': stats[3] if stats else None,
            'top_holdings': df_to_records(holdings),
            'sector_allocation': df_to_records(sectors),
            'quarterly_trend': df_to_records(qoq),
        }
        return jsonify(clean_for_json(result))
    except Exception as e:
        app.logger.error(f"manager_profile error: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        con.close()


@app.route('/api/amendments')
def api_amendments():
    """13F-HR amendment reconciliation: show amended vs original filings per quarter."""
    ticker = request.args.get('ticker', '').upper().strip()
    if not ticker:
        return jsonify({'error': 'Missing ticker parameter'}), 400
    con = get_db()
    try:
        # Find managers who filed amendments for this ticker
        amendments = con.execute(f"""
            WITH all_filings AS (
                SELECT cik, manager_name, inst_parent_name, quarter,
                       accession_number, shares, market_value_usd,
                       CASE WHEN accession_number IN (
                           SELECT accession_number FROM filings WHERE amended = true
                       ) THEN true ELSE false END as is_amended
                FROM holdings
                WHERE ticker = ? AND quarter = '{LQ}'
            ),
            amended_managers AS (
                SELECT DISTINCT cik FROM filings
                WHERE amended = true AND quarter = '{LQ}'
            )
            SELECT a.inst_parent_name as manager, a.shares, a.market_value_usd,
                   CASE WHEN a.cik IN (SELECT cik FROM amended_managers)
                        THEN 'Amended' ELSE 'Original' END as filing_status
            FROM all_filings a
            WHERE a.cik IN (SELECT cik FROM amended_managers)
            ORDER BY a.market_value_usd DESC LIMIT 30
        """, [ticker]).fetchdf()

        return jsonify(clean_for_json({
            'ticker': ticker,
            'amendments': df_to_records(amendments),
        }))
    except Exception as e:
        app.logger.error(f"amendments error: {e}")
        return jsonify({'error': str(e)}), 500
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
        elif qnum == 13:
            sector = request.args.get('sector', '').strip() or None
            data = fn(ticker or None, sector=sector)
        elif qnum == 15:
            data = fn(ticker or None)
        else:
            data = fn(ticker)

        # query1 returns dict {rows, all_totals, type_totals}; others return list
        is_empty = (isinstance(data, dict) and not data.get('rows')) or (isinstance(data, list) and not data)
        if is_empty:
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
        elif qnum == 13:
            sector = request.args.get('sector', '').strip() or None
            data = fn(ticker or None, sector=sector)
        elif qnum == 15:
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
