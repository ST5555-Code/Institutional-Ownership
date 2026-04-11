"""
INF12: Admin Blueprint for /api/admin/* endpoints.

All routes on this blueprint require ENABLE_ADMIN=1 and ADMIN_TOKEN set in
env, plus an `X-Admin-Token` header matching ADMIN_TOKEN on every request.

When ENABLE_ADMIN or ADMIN_TOKEN is unset, every route returns 503
"Admin disabled". When the header is missing or wrong, returns 403.
Token comparison uses hmac.compare_digest for timing-safe checking.

EXCEPTION: /api/admin/quarter_config stays on the main app (scripts/app.py).
It is loaded by the public main UI (app.js QuarterSelector) on every page and
cannot be gated without breaking the public site.
"""

import csv as _csv
import hmac
import io as _io
import os
import re
import subprocess  # nosec B404
from datetime import datetime

import duckdb
from flask import Blueprint, current_app, jsonify, request

from config import LATEST_QUARTER, PREV_QUARTER
from queries import clean_for_json, df_to_records

LQ = LATEST_QUARTER
PQ = PREV_QUARTER

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

admin_bp = Blueprint('admin', __name__, url_prefix='/api/admin')

# Module-level refs set by init_admin_bp() from app.py. Avoids circular import
# (app.py imports this module at load time; get_db / has_table are defined in
# app.py after DB bootstrap). Routes access these lazily at request time, by
# which point init_admin_bp() has run.
_get_db = None
_has_table = None


def init_admin_bp(get_db_fn, has_table_fn):
    """Wire app.py's DB helpers into the Blueprint.
    Must be called from app.py before app.register_blueprint(admin_bp).
    """
    global _get_db, _has_table  # pylint: disable=global-statement
    _get_db = get_db_fn
    _has_table = has_table_fn


@admin_bp.before_request
def _require_admin_token():
    """INF12: Token-gate every admin endpoint.
    503 if ENABLE_ADMIN or ADMIN_TOKEN unset. 403 on bad/missing header.
    """
    if os.environ.get('ENABLE_ADMIN') != '1' or not os.environ.get('ADMIN_TOKEN'):
        return jsonify({'error': 'Admin disabled'}), 503
    provided = request.headers.get('X-Admin-Token', '')
    expected = os.environ['ADMIN_TOKEN']
    if not hmac.compare_digest(provided, expected):
        return jsonify({'error': 'Forbidden'}), 403
    return None


# ---------------------------------------------------------------------------
# On-demand ticker add (moved from /api/add_ticker per INF12)
# ---------------------------------------------------------------------------


@admin_bp.route('/add_ticker', methods=['POST'])
def api_add_ticker():
    """Add a single ticker on-demand: fetch CUSIP, market data, 13D/G filings."""
    ticker = request.json.get('ticker', '').upper().strip() if request.json else ''
    if not ticker:
        return jsonify({'error': 'Missing ticker'}), 400

    from db import PROD_DB  # pylint: disable=import-outside-toplevel
    results = {'ticker': ticker, 'steps': []}

    try:
        # Step 1: Resolve CUSIP via OpenFIGI
        import requests as req  # pylint: disable=import-outside-toplevel
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

        # Step 2: Fetch market data via YahooClient + SEC XBRL
        # - Yahoo: price, sector, industry, float, 52w (via direct JSON API)
        # - SEC:   authoritative shares_outstanding from 10-K/10-Q cover page
        # - market_cap: computed as shares_outstanding × price (strict)
        from yahoo_client import YahooClient  # pylint: disable=import-outside-toplevel
        from sec_shares_client import SECSharesClient  # pylint: disable=import-outside-toplevel
        yc = YahooClient()
        sc = SECSharesClient()
        m = yc.fetch_metadata(ticker) or {}
        price = m.get('price')
        if price:
            sec = sc.fetch(ticker) or {}
            shares_out = sec.get('shares_outstanding')
            market_cap = (shares_out * price) if (shares_out and price) else None
            con = duckdb.connect(PROD_DB)
            now = datetime.now().strftime('%Y-%m-%d')
            con.execute("""
                INSERT OR REPLACE INTO market_data (ticker, price_live, market_cap,
                    float_shares, shares_outstanding, sector, industry, exchange, fetch_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [ticker, price, market_cap,
                  m.get('float_shares'), shares_out,
                  m.get('sector'), m.get('industry'), m.get('exchange'), now])
            con.execute("CHECKPOINT")
            con.close()
            results['market_cap'] = market_cap
            results['price'] = price
            results['sector'] = m.get('sector')
            results['shares_source'] = 'SEC' if shares_out else None
            results['steps'].append(
                f'Market data: added (market_cap {"computed from SEC shares × price" if market_cap else "NULL — no SEC shares"})')
        else:
            results['steps'].append('Market data: Yahoo returned no price')

        # Step 3: Fetch 13D/G filings
        try:
            import edgar  # pylint: disable=import-error,import-outside-toplevel
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
        except Exception as e:  # pylint: disable=broad-except
            results['steps'].append(f'13D/G: {e}')

        results['status'] = 'ok'
        return jsonify(results)

    except Exception as e:  # pylint: disable=broad-except
        results['status'] = 'error'
        results['error'] = str(e)
        return jsonify(results), 500


# ---------------------------------------------------------------------------
# Admin stats / monitoring / data-quality (read-only — gated per INF12)
# ---------------------------------------------------------------------------


@admin_bp.route('/stats')
def api_admin_stats():
    """Database row counts for admin dashboard."""
    con = _get_db()
    try:
        stats = {}
        for table, key in [('holdings_v2', 'holdings'), ('managers', 'managers'),
                           ('beneficial_ownership_v2', 'beneficial_ownership'),
                           ('fund_holdings_v2', 'fund_holdings')]:
            try:
                stats[key] = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # nosec B608
            except Exception as e:  # pylint: disable=broad-except
                current_app.logger.debug("Error: %s", e)
                stats[key] = 0
        try:
            stats['tickers'] = con.execute("SELECT COUNT(DISTINCT ticker) FROM holdings_v2 WHERE ticker IS NOT NULL").fetchone()[0]
        except Exception as e:  # pylint: disable=broad-except
            current_app.logger.debug("Error: %s", e)
            stats['tickers'] = 0
        try:
            stats['short_interest_days'] = con.execute("SELECT COUNT(DISTINCT report_date) FROM short_interest").fetchone()[0]
        except Exception as e:  # pylint: disable=broad-except
            current_app.logger.debug("Error: %s", e)
            stats['short_interest_days'] = 0
        return jsonify(stats)
    finally:
        con.close()


@admin_bp.route('/progress')
def api_admin_progress():
    """Check if a pipeline is running and return progress."""
    result = {'running': False}

    # Check for running fetch_13dg process
    try:
        ps = subprocess.run(['pgrep', '-f', 'fetch_13dg.py'], capture_output=True, text=True, check=False)  # nosec  # bandit B607 + B603 — known partial-path subprocess
        if ps.returncode == 0:
            result['running'] = True
    except Exception as e:  # pylint: disable=broad-except
        current_app.logger.debug("Suppressed: %s", e)

    # Read progress file
    progress_file = os.path.join(BASE_DIR, 'logs', 'phase2_progress.txt')
    try:
        with open(progress_file, encoding='utf-8') as f:
            lines = f.read().strip().split('\n')
            if lines:
                result['progress_line'] = lines[0].strip()
                # Parse [N/M] pattern
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


@admin_bp.route('/errors')
def api_admin_errors():
    """Return recent errors from fetch_13dg_errors.csv."""
    error_file = os.path.join(BASE_DIR, 'logs', 'fetch_13dg_errors.csv')
    try:
        with open(error_file, encoding='utf-8') as f:
            lines = f.readlines()
        # Return last 20 lines
        recent = ''.join(lines[-20:]) if len(lines) > 20 else ''.join(lines)
        return jsonify({'errors': recent, 'count': len(lines) - 1})  # -1 for header
    except FileNotFoundError:
        return jsonify({'errors': 'No error log found', 'count': 0})


@admin_bp.route('/run_script', methods=['POST'])
def api_admin_run_script():
    """Run a pipeline script in the background. Returns immediately."""
    data = request.json or {}
    script = data.get('script', '')
    flags = data.get('flags', [])

    # Whitelist of allowed scripts.
    # INF12: run_pipeline.sh and merge_staging.py removed — never web-triggerable,
    # run manually only. Both are destructive/irreversible at the pipeline level
    # and have no business being launched from a browser request.
    allowed = {
        'fetch_13dg.py', 'fetch_nport.py', 'fetch_market.py',
        'fetch_finra_short.py', 'fetch_ncen.py', 'compute_flows.py',
        'build_cusip.py', 'build_summaries.py', 'unify_positions.py',
        'refresh_snapshot.sh',
    }
    if script not in allowed:
        return jsonify({'error': f'Script not allowed: {script}'}), 400

    # Check if already running
    try:
        ps = subprocess.run(['pgrep', '-f', script], capture_output=True, text=True, check=False)  # nosec  # bandit B607 + B603 — known partial-path subprocess
        if ps.returncode == 0:
            return jsonify({'error': f'{script} is already running'}), 409
    except Exception as e:  # pylint: disable=broad-except
        current_app.logger.debug("Suppressed: %s", e)

    # Build command
    script_path = os.path.join(BASE_DIR, 'scripts', script)
    if script.endswith('.sh'):
        cmd = ['bash', script_path] + flags
    else:
        cmd = ['python3', '-u', script_path] + flags

    # Run in background
    log_name = script.replace('.py', '').replace('.sh', '')
    log_path = os.path.join(BASE_DIR, 'logs', f'{log_name}_run.log')
    with open(log_path, 'w', encoding='utf-8') as log_file:
        proc = subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT, cwd=BASE_DIR)  # nosec B603

    return jsonify({
        'status': 'started',
        'script': script,
        'flags': flags,
        'pid': proc.pid,
        'log': log_path,
    })


@admin_bp.route('/manager_changes')
def api_admin_manager_changes():
    """D2: Detect manager changes across quarters — new, disappeared, name changes."""
    con = _get_db()
    try:
        # New managers (in latest quarter but not previous)
        new_mgrs = con.execute(
            f""  # nosec B608
            f"""
            SELECT DISTINCT cik, manager_name, manager_type
            FROM holdings_v2 WHERE quarter = '{LATEST_QUARTER}'
              AND cik NOT IN (SELECT DISTINCT cik FROM holdings_v2 WHERE quarter = '{PREV_QUARTER}')
            ORDER BY manager_name LIMIT 50
            """
        ).fetchdf()
        # Disappeared managers
        gone_mgrs = con.execute(
            f""  # nosec B608
            f"""
            SELECT DISTINCT cik, manager_name, manager_type
            FROM holdings_v2 WHERE quarter = '{PREV_QUARTER}'
              AND cik NOT IN (SELECT DISTINCT cik FROM holdings_v2 WHERE quarter = '{LATEST_QUARTER}')
            ORDER BY manager_name LIMIT 50
            """
        ).fetchdf()
        return jsonify(clean_for_json({
            'new_managers': df_to_records(new_mgrs),
            'disappeared_managers': df_to_records(gone_mgrs),
            'latest_quarter': LATEST_QUARTER,
            'prev_quarter': PREV_QUARTER,
        }))
    finally:
        con.close()


@admin_bp.route('/ticker_changes')
def api_admin_ticker_changes():
    """D3: Detect ticker changes — new tickers, disappeared tickers."""
    con = _get_db()
    try:
        new_tickers = con.execute(
            f""  # nosec B608
            f"""
            SELECT DISTINCT ticker, MAX(issuer_name) as company
            FROM holdings_v2 WHERE quarter = '{LATEST_QUARTER}' AND ticker IS NOT NULL
              AND ticker NOT IN (SELECT DISTINCT ticker FROM holdings_v2 WHERE quarter = '{PREV_QUARTER}' AND ticker IS NOT NULL)
            GROUP BY ticker ORDER BY ticker LIMIT 100
            """
        ).fetchdf()
        gone_tickers = con.execute(
            f""  # nosec B608
            f"""
            SELECT DISTINCT ticker, MAX(issuer_name) as company
            FROM holdings_v2 WHERE quarter = '{PREV_QUARTER}' AND ticker IS NOT NULL
              AND ticker NOT IN (SELECT DISTINCT ticker FROM holdings_v2 WHERE quarter = '{LATEST_QUARTER}' AND ticker IS NOT NULL)
            GROUP BY ticker ORDER BY ticker LIMIT 100
            """
        ).fetchdf()
        return jsonify(clean_for_json({
            'new_tickers': df_to_records(new_tickers),
            'disappeared_tickers': df_to_records(gone_tickers),
        }))
    finally:
        con.close()


@admin_bp.route('/parent_mapping_health')
def api_admin_parent_health():
    """D4: Check parent mapping health — orphaned CIKs, unmatched managers."""
    con = _get_db()
    try:
        # Managers without parent assignment
        orphaned = con.execute(
            f""  # nosec B608
            f"""
            SELECT cik, manager_name, manager_type,
                   SUM(market_value_live) as total_value
            FROM holdings_v2
            WHERE quarter = '{LQ}' AND inst_parent_name IS NULL
            GROUP BY cik, manager_name, manager_type
            ORDER BY total_value DESC NULLS LAST
            LIMIT 20
            """
        ).fetchdf()
        # Top parents by value
        top_parents = con.execute(
            f""  # nosec B608
            f"""
            SELECT COALESCE(rollup_name, inst_parent_name) as inst_parent_name, COUNT(DISTINCT cik) as child_ciks,
                   SUM(market_value_live) as total_value
            FROM holdings_v2 WHERE quarter = '{LQ}' AND COALESCE(rollup_name, inst_parent_name) IS NOT NULL
            GROUP BY COALESCE(rollup_name, inst_parent_name)
            ORDER BY total_value DESC NULLS LAST LIMIT 20
            """
        ).fetchdf()
        return jsonify(clean_for_json({
            'orphaned_managers': df_to_records(orphaned),
            'top_parents': df_to_records(top_parents),
        }))
    finally:
        con.close()


@admin_bp.route('/stale_data')
def api_admin_stale_data():
    """D5: Flag stale data — old market data, inactive managers."""
    con = _get_db()
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
        except Exception as e:  # pylint: disable=broad-except
            current_app.logger.debug("Error: %s", e)
            result['stale_market_data'] = []
        # Managers only in old quarters
        try:
            inactive = con.execute(
                f""  # nosec B608
                f"""
                SELECT cik, manager_name, MAX(quarter) as last_quarter
                FROM holdings_v2
                GROUP BY cik, manager_name
                HAVING MAX(quarter) < '{PQ}'
                ORDER BY last_quarter DESC LIMIT 20
                """
            ).fetchdf()
            result['inactive_managers'] = df_to_records(inactive)
        except Exception as e:  # pylint: disable=broad-except
            current_app.logger.debug("Error: %s", e)
            result['inactive_managers'] = []
        return jsonify(clean_for_json(result))
    finally:
        con.close()


@admin_bp.route('/merger_signals')
def api_admin_merger_signals():
    """D6: Detect potential mergers — CIK disappears + another CIK's holdings jump."""
    con = _get_db()
    try:
        # CIKs that disappeared AND had large holdings
        signals = con.execute(
            f""  # nosec B608
            f"""
            WITH gone AS (
                SELECT cik, manager_name, SUM(market_value_usd) as prev_value
                FROM holdings_v2 WHERE quarter = '{PREV_QUARTER}'
                  AND cik NOT IN (SELECT DISTINCT cik FROM holdings_v2 WHERE quarter = '{LATEST_QUARTER}')
                GROUP BY cik, manager_name
                HAVING SUM(market_value_usd) > 1000000
            )
            SELECT * FROM gone ORDER BY prev_value DESC LIMIT 20
            """
        ).fetchdf()
        return jsonify(clean_for_json({
            'potential_mergers': df_to_records(signals),
        }))
    finally:
        con.close()


@admin_bp.route('/new_companies')
def api_admin_new_companies():
    """D7: New companies with institutional interest — recent entries."""
    con = _get_db()
    try:
        # Tickers that appeared in latest quarter with significant institutional value
        new_cos = con.execute(
            f""  # nosec B608
            f"""
            SELECT h.ticker, MAX(h.issuer_name) as company,
                   COUNT(DISTINCT h.cik) as holder_count,
                   SUM(h.market_value_live) as total_value,
                   MAX(m.sector) as sector
            FROM holdings_v2 h
            LEFT JOIN market_data m ON h.ticker = m.ticker
            WHERE h.quarter = '{LATEST_QUARTER}' AND h.ticker IS NOT NULL
              AND h.ticker NOT IN (
                  SELECT DISTINCT ticker FROM holdings_v2
                  WHERE quarter = '{PREV_QUARTER}' AND ticker IS NOT NULL
              )
            GROUP BY h.ticker
            HAVING SUM(h.market_value_live) > 10000000
            ORDER BY total_value DESC LIMIT 30
            """
        ).fetchdf()
        return jsonify(clean_for_json({
            'new_companies': df_to_records(new_cos),
        }))
    finally:
        con.close()


@admin_bp.route('/data_quality')
def api_admin_data_quality():
    """F6: Data quality metrics — coverage, parse rates, gaps."""
    con = _get_db()
    try:
        result = {}
        # Holdings coverage
        try:
            r = con.execute(
                f""  # nosec B608
                f"""
                SELECT
                    COUNT(*) as total,
                    COUNT(ticker) as with_ticker,
                    COUNT(market_value_live) as with_live_value,
                    COUNT(pct_of_float) as with_float_pct
                FROM holdings_v2 WHERE quarter = '{LQ}'
                """
            ).fetchone()
            result['holdings'] = {
                'total': r[0], 'with_ticker': r[1],
                'with_live_value': r[2], 'with_float_pct': r[3],
                'ticker_pct': round(r[1] / r[0] * 100, 1) if r[0] else 0,
                'live_value_pct': round(r[2] / r[0] * 100, 1) if r[0] else 0,
            }
        except Exception as e:  # pylint: disable=broad-except
            current_app.logger.debug("Error: %s", e)
            result['holdings'] = {}
        # 13D/G parse quality
        try:
            r = con.execute("""
                SELECT COUNT(*) as total,
                    COUNT(pct_owned) as with_pct,
                    COUNT(shares_owned) as with_shares,
                    COUNT(CASE WHEN filer_name IS NULL OR filer_name = ''
                               OR regexp_matches(filer_name, '^\\d{7,10}$') THEN 1 END) as unknown_filers
                FROM beneficial_ownership_v2
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
                    FROM beneficial_ownership_v2
                """).fetchone()
                bo_stats['name_resolved'] = nr[0]
                bo_stats['name_unresolved'] = nr[1]
                bo_stats['name_resolution_pct'] = round(nr[0] / (nr[0] + nr[1]) * 100, 1) if (nr[0] + nr[1]) else 0
            except Exception as e:  # pylint: disable=broad-except
                current_app.logger.debug("Suppressed: %s", e)
            result['beneficial_ownership'] = bo_stats
        except Exception as e:  # pylint: disable=broad-except
            current_app.logger.debug("Error: %s", e)
            result['beneficial_ownership'] = {}
        # Error log stats
        error_file = os.path.join(BASE_DIR, 'logs', 'fetch_13dg_errors.csv')
        try:
            with open(error_file, encoding='utf-8') as f:
                error_count = sum(1 for _ in f) - 1
            result['fetch_errors'] = error_count
        except FileNotFoundError:
            result['fetch_errors'] = 0
        return jsonify(result)
    finally:
        con.close()


@admin_bp.route('/staging_preview')
def api_admin_staging_preview():
    """F5: Preview what merge_staging would do (dry-run)."""
    script_path = os.path.join(BASE_DIR, 'scripts', 'merge_staging.py')
    try:
        result = subprocess.run(  # nosec  # bandit B607 + B603 — known partial-path subprocess
            ['python3', script_path, '--all', '--dry-run'],
            capture_output=True, text=True, timeout=30, cwd=BASE_DIR, check=False,
        )
        return jsonify({
            'output': result.stdout,
            'error': result.stderr if result.returncode != 0 else None,
            'returncode': result.returncode,
        })
    except subprocess.TimeoutExpired:
        return jsonify({'error': 'Preview timed out after 30s'}), 504
    except Exception as e:  # pylint: disable=broad-except
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/running')
def api_admin_running():
    """List currently running pipeline scripts."""
    running = []
    for script in ['fetch_13dg.py', 'fetch_nport.py', 'fetch_market.py',
                   'fetch_finra_short.py', 'compute_flows.py', 'merge_staging.py']:
        try:
            ps = subprocess.run(['pgrep', '-f', script], capture_output=True, text=True, check=False)  # nosec  # bandit B607 + B603 — known partial-path subprocess
            if ps.returncode == 0:
                pids = ps.stdout.strip().split('\n')
                running.append({'script': script, 'pids': pids})
        except Exception as e:  # pylint: disable=broad-except
            current_app.logger.debug("Suppressed: %s", e)
    return jsonify({'running': running})


# ---------------------------------------------------------------------------
# Entity MDM — Priority 6 manual override endpoint (Phase 1)
# ---------------------------------------------------------------------------
# CSV input format (header required):
#   entity_id,action,field,old_value,new_value,reason,analyst
#
# Supported actions:
#   reclassify  — update entity_classification_history (field=classification|is_activist)
#   alias_add   — add a brand alias to entity_aliases (new_value = alias name)
#   merge       — set rollup parent in entity_rollup_history (new_value = parent entity_id)
#
# All writes are applied against the STAGING entity tables with:
#   source='manual', confidence='exact', is_inferred=FALSE
# and logged to logs/entity_overrides.log with timestamp and analyst initials.
#
# Query param ?target=staging|prod — defaults to staging. Prod is blocked until
# Phase 4 authorization (returns 403).
@admin_bp.route('/entity_override', methods=['POST'])
def api_admin_entity_override():  # pylint: disable=too-many-locals,too-many-branches,too-many-statements
    target = (request.args.get('target') or 'staging').lower()
    if target != 'staging':
        return jsonify({
            'error': 'entity_override against production is blocked until Phase 4 authorization',
            'target': target,
        }), 403

    # Accept either raw CSV body (text/csv) or JSON {"csv": "..."}
    if request.content_type and 'application/json' in request.content_type:
        body = (request.json or {}).get('csv', '')
    else:
        body = request.get_data(as_text=True) or ''

    if not body.strip():
        return jsonify({'error': 'empty CSV body'}), 400

    reader = _csv.DictReader(_io.StringIO(body))
    required = {'entity_id', 'action', 'field', 'old_value', 'new_value', 'reason', 'analyst'}
    if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
        return jsonify({
            'error': 'CSV must contain columns: ' + ','.join(sorted(required)),
            'received': reader.fieldnames,
        }), 400

    # Open a staging write connection. Do NOT use the app's read-only get_db().
    staging_path = os.path.join(BASE_DIR, 'data', '13f_staging.duckdb')
    if not os.path.exists(staging_path):
        return jsonify({'error': f'staging DB not found: {staging_path}'}), 500

    log_path = os.path.join(BASE_DIR, 'logs', 'entity_overrides.log')
    applied, skipped = [], []
    con = duckdb.connect(staging_path, read_only=False)
    try:
        for row_num, row in enumerate(reader, start=2):  # row 1 is header
            try:
                entity_id = int(row['entity_id'])
                action = (row['action'] or '').strip().lower()
                field = (row['field'] or '').strip().lower()
                old_value = row['old_value']
                new_value = row['new_value']
                reason = row['reason'] or ''
                analyst = row['analyst'] or ''

                # Verify the entity exists
                exists = con.execute(
                    "SELECT 1 FROM entities WHERE entity_id = ?", [entity_id]
                ).fetchone()
                if not exists:
                    skipped.append({'row': row_num, 'reason': f'entity_id {entity_id} not found'})
                    continue

                if action == 'reclassify':
                    # Close current classification, insert new one
                    con.execute("BEGIN TRANSACTION")
                    try:
                        con.execute(
                            """UPDATE entity_classification_history
                               SET valid_to = CURRENT_DATE
                               WHERE entity_id = ? AND valid_to = DATE '9999-12-31'""",
                            [entity_id],
                        )
                        if field == 'classification':
                            con.execute(
                                """INSERT INTO entity_classification_history
                                   (entity_id, classification, is_activist, confidence, source,
                                    is_inferred, valid_from, valid_to)
                                   VALUES (?, ?, FALSE, 'exact', 'manual', FALSE,
                                           CURRENT_DATE, DATE '9999-12-31')""",
                                [entity_id, new_value],
                            )
                        elif field == 'is_activist':
                            prior = con.execute(
                                """SELECT classification FROM entity_classification_history
                                   WHERE entity_id = ? ORDER BY valid_from DESC LIMIT 1""",
                                [entity_id],
                            ).fetchone()
                            cls = (prior[0] if prior else 'unknown')
                            con.execute(
                                """INSERT INTO entity_classification_history
                                   (entity_id, classification, is_activist, confidence, source,
                                    is_inferred, valid_from, valid_to)
                                   VALUES (?, ?, ?, 'exact', 'manual', FALSE,
                                           CURRENT_DATE, DATE '9999-12-31')""",
                                [entity_id, cls, new_value.strip().lower() in ('true', '1', 'yes')],
                            )
                        else:
                            raise ValueError(f"unsupported field for reclassify: {field}")
                        con.execute("COMMIT")
                    except Exception as e:
                        current_app.logger.debug("Error: %s", e)
                        con.execute("ROLLBACK")
                        raise

                elif action == 'alias_add':
                    con.execute(
                        """INSERT INTO entity_aliases
                           (entity_id, alias_name, alias_type, is_preferred, preferred_key,
                            source_table, is_inferred, valid_from, valid_to)
                           VALUES (?, ?, 'brand', FALSE, NULL, 'manual', FALSE,
                                   CURRENT_DATE, DATE '9999-12-31')
                           ON CONFLICT DO NOTHING""",
                        [entity_id, new_value],
                    )

                elif action == 'merge':
                    # new_value = parent entity_id; close current rollup, insert new
                    parent_id = int(new_value)
                    parent_exists = con.execute(
                        "SELECT 1 FROM entities WHERE entity_id = ?", [parent_id]
                    ).fetchone()
                    if not parent_exists:
                        skipped.append({'row': row_num, 'reason': f'parent entity_id {parent_id} not found'})
                        continue
                    con.execute("BEGIN TRANSACTION")
                    try:
                        con.execute(
                            """UPDATE entity_rollup_history
                               SET valid_to = CURRENT_DATE
                               WHERE entity_id = ?
                                 AND rollup_type = 'economic_control_v1'
                                 AND valid_to = DATE '9999-12-31'""",
                            [entity_id],
                        )
                        con.execute(
                            """INSERT INTO entity_rollup_history
                               (entity_id, rollup_entity_id, rollup_type, rule_applied,
                                confidence, valid_from, valid_to)
                               VALUES (?, ?, 'economic_control_v1', 'manual_override',
                                       'exact', CURRENT_DATE, DATE '9999-12-31')""",
                            [entity_id, parent_id],
                        )
                        con.execute("COMMIT")
                    except Exception as e:
                        current_app.logger.debug("Error: %s", e)
                        con.execute("ROLLBACK")
                        raise

                else:
                    skipped.append({'row': row_num, 'reason': f'unsupported action: {action}'})
                    continue

                # Persist override for replay after --reset rebuilds
                # Look up CIK for this entity (used to re-resolve after rebuild)
                cik_row = con.execute(
                    """SELECT identifier_value FROM entity_identifiers
                       WHERE entity_id = ? AND identifier_type = 'cik'
                         AND valid_to = DATE '9999-12-31' LIMIT 1""",
                    [entity_id],
                ).fetchone()
                entity_cik = cik_row[0] if cik_row else str(entity_id)
                try:
                    con.execute(
                        """INSERT INTO entity_overrides_persistent
                           (entity_cik, action, field, old_value, new_value, reason, analyst)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        [entity_cik, action, field, old_value, new_value, reason, analyst],
                    )
                except Exception as e:  # pylint: disable=broad-except
                    current_app.logger.debug("Error: %s", e)
                    # table might not exist in older staging DBs

                # Audit log append
                with open(log_path, 'a', encoding='utf-8') as f:
                    f.write(
                        f"{datetime.now().isoformat()}\tentity_id={entity_id}\taction={action}"
                        f"\tfield={field}\told={old_value}\tnew={new_value}"
                        f"\tanalyst={analyst}\treason={reason}\n"
                    )
                applied.append({'row': row_num, 'entity_id': entity_id, 'action': action})

            except Exception as e:  # pylint: disable=broad-except
                skipped.append({'row': row_num, 'reason': str(e)[:200]})
    finally:
        con.close()

    return jsonify({
        'target': target,
        'applied': applied,
        'skipped': skipped,
        'applied_count': len(applied),
        'skipped_count': len(skipped),
        'log': log_path,
    })
