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
            shutil.copy2(DB_PATH, DB_SNAPSHOT_PATH)
            print(f'  Snapshot ready: {DB_SNAPSHOT_PATH}')
            return DB_SNAPSHOT_PATH
        except Exception as e2:
            raise RuntimeError(
                f'Cannot open database (locked) and cannot create snapshot: {e2}'
            )


# Resolved once at import/startup; updated if needed
_active_db_path = None
_switchback_running = False
_available_tables = set()


def _start_switchback_monitor():
    """Background thread: check every 60s if primary DB is available again."""
    import threading
    global _switchback_running
    if _switchback_running:
        return
    _switchback_running = True

    def _monitor():
        global _active_db_path, _switchback_running
        import time as _time
        while True:
            _time.sleep(60)
            if _active_db_path == DB_PATH:
                _switchback_running = False
                return
            try:
                con = duckdb.connect(DB_PATH, read_only=True)
                con.close()
                _active_db_path = DB_PATH
                _refresh_table_list()
                app.logger.info("[switchback] Primary DB available — switched back from snapshot")
                _switchback_running = False
                return
            except Exception:
                pass

    t = threading.Thread(target=_monitor, daemon=True)
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
    if _active_db_path is None:
        _active_db_path = _resolve_db_path()
        _refresh_table_list()
        if _active_db_path != DB_PATH:
            _start_switchback_monitor()
    try:
        return duckdb.connect(_active_db_path, read_only=True)
    except Exception as e:
        app.logger.warning(f"[get_db] Connection stale, re-resolving: {e}")
        _active_db_path = _resolve_db_path()
        _refresh_table_list()
        if _active_db_path != DB_PATH:
            _start_switchback_monitor()
        return duckdb.connect(_active_db_path, read_only=True)


# Initialize queries module with DB access functions
queries._setup(get_db, has_table)





# ---------------------------------------------------------------------------
# Summary endpoint
# ---------------------------------------------------------------------------

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
