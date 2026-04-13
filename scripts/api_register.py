"""Register + query dispatch endpoints.

Routes:
  /api/v1/tickers                 (enveloped, Phase 1-B2)
  /api/v1/summary
  /api/v1/query1                  (enveloped, Phase 1-B2)
  /api/v1/query<int:qnum>         (bare, queries 2–16)
  /api/v1/export/query<int:qnum>
  /api/v1/amendments
  /api/v1/manager_profile

Fund-lookup endpoints (fund_rollup_context, fund_portfolio_managers,
fund_behavioral_profile, nport_shorts) live in api_fund.py.
"""
from __future__ import annotations

from datetime import datetime

from flask import Blueprint, current_app, jsonify, request, send_file

from api_common import (
    LQ,
    QUERY_FUNCTIONS,
    _RT_AWARE_QUERIES,
    _get_rollup_type,
    respond,
)
from app_db import get_db
from export import build_excel
from queries import clean_for_json, df_to_records, get_summary
from schemas import RegisterEnvelope, TickersEnvelope

register_bp = Blueprint('api_register', __name__, url_prefix='/api/v1')


QUERY_NAMES = {
    1: 'Register', 2: 'Holder Changes', 3: 'Conviction',
    6: 'Activist', 7: 'Fund Portfolio', 8: 'Cross-Ownership',
    9: 'Sector Rotation', 10: 'New Positions', 11: 'Exits',
    14: 'AUM vs Position', 15: 'DB Statistics',
}


# SMOKE TEST: /api/v1/tickers is the autocomplete root — a silent 500 here
# breaks the entire UI ticker search. Always include in post-commit curl.
@register_bp.route('/tickers')
def api_tickers():
    try:
        con = get_db()
    except Exception as e:
        return respond(
            error={'code': 'db_unavailable', 'message': f'Database unavailable: {e}'},
            schema=TickersEnvelope,
            status=503,
        )
    try:
        df = con.execute(
            f""  # nosec B608
            f"""
            SELECT ticker, MODE(issuer_name) as name
            FROM holdings_v2
            WHERE ticker IS NOT NULL AND ticker != '' AND quarter = '{LQ}'
            GROUP BY ticker
            ORDER BY ticker
            """
        ).fetchdf()
        return respond(data=df_to_records(df), schema=TickersEnvelope)
    finally:
        con.close()


@register_bp.route('/summary')
def api_summary():
    ticker = request.args.get('ticker', '').upper().strip()
    if not ticker:
        return jsonify({'error': 'Missing ticker parameter'}), 400
    result = get_summary(ticker)
    if not result:
        return jsonify({'error': f'No data found for ticker {ticker}'}), 404
    return jsonify(result)


def _execute_query(qnum):
    """Run query-N dispatch. Returns (data, error_dict, status).

    Shared by the generic /api/v1/query<N> handler AND the dedicated
    /api/v1/query1 envelope handler. Error shape is ErrorShape-compatible
    so callers can wrap in respond() or jsonify() as needed.
    """
    if qnum not in QUERY_FUNCTIONS:
        return None, {'code': 'invalid_query', 'message': f'Invalid query number: {qnum}'}, 400
    ticker = request.args.get('ticker', '').upper().strip()
    cik = request.args.get('cik', '').strip()
    quarter = request.args.get('quarter', LQ)
    rt = _get_rollup_type(request)

    if qnum not in (15,) and not ticker:
        return None, {'code': 'missing_param', 'message': 'Missing ticker parameter'}, 400

    try:
        fn = QUERY_FUNCTIONS[qnum]
        if qnum == 7:
            fund_name = request.args.get('fund_name', '').strip() or None
            data = fn(ticker, cik=cik or None, fund_name=fund_name, quarter=quarter)
            if not data.get('positions'):
                return None, {'code': 'not_found', 'message': f'No holdings found for CIK {cik}'}, 404
            return data, None, 200
        elif qnum == 15:
            data = fn(ticker or None, quarter=quarter)
        elif qnum in _RT_AWARE_QUERIES:
            data = fn(ticker, rollup_type=rt, quarter=quarter)
        else:
            data = fn(ticker, quarter=quarter)

        if isinstance(data, list):
            is_empty = not data
        elif isinstance(data, dict) and 'rows' in data:
            is_empty = not data.get('rows')
        else:
            is_empty = False
        if is_empty:
            return None, {'code': 'not_found', 'message': f'No data found for ticker {ticker}'}, 404
        return data, None, 200
    except Exception as e:
        return None, {'code': 'internal_error', 'message': str(e)}, 500


@register_bp.route('/query1')
def api_query1():
    """Register tab — enveloped per Phase 1-B2. Queries 2–16 stay bare."""
    data, err, status = _execute_query(1)
    if err is not None:
        return respond(error=err, schema=RegisterEnvelope, status=status)
    return respond(data=data, schema=RegisterEnvelope, status=status)


@register_bp.route('/query<int:qnum>')
def api_query(qnum):
    if qnum == 1:
        # More-specific /query1 route wins in Flask; defend in depth.
        return api_query1()
    data, err, status = _execute_query(qnum)
    if err is not None:
        return jsonify({'error': err['message']}), status
    return jsonify(data)


@register_bp.route('/export/query<int:qnum>')
def api_export(qnum):
    if qnum not in QUERY_FUNCTIONS:
        return jsonify({'error': f'Invalid query number: {qnum}'}), 400
    ticker = request.args.get('ticker', '').upper().strip()
    cik = request.args.get('cik', '').strip()
    quarter = request.args.get('quarter', LQ)
    rt = _get_rollup_type(request)

    if qnum not in (15,) and not ticker:
        return jsonify({'error': 'Missing ticker parameter'}), 400

    try:
        fn = QUERY_FUNCTIONS[qnum]
        if qnum == 7:
            fund_name = request.args.get('fund_name', '').strip() or None
            data = fn(ticker, cik=cik or None, fund_name=fund_name, quarter=quarter)
        elif qnum == 15:
            data = fn(ticker or None, quarter=quarter)
        elif qnum in _RT_AWARE_QUERIES:
            data = fn(ticker, rollup_type=rt, quarter=quarter)
        else:
            data = fn(ticker, quarter=quarter)

        if not data:
            return jsonify({'error': f'No data found for ticker {ticker}'}), 404

        # Extract the tabular portion from structured responses:
        #   q7         → {stats, positions}              export `positions`
        #   q1, q16    → {rows, all_totals, type_totals} export `rows`
        # q6/q10/q11/q15 are multi-table shapes the extractor doesn't know
        # (BL-10 in Architecture Backlog).
        if isinstance(data, dict):
            if 'positions' in data:
                export_data = data['positions']
            elif 'rows' in data:
                export_data = data['rows']
            else:
                export_data = data
        else:
            export_data = data
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


@register_bp.route('/amendments')
def api_amendments():
    """13F-HR amendment reconciliation: show amended vs original filings per quarter."""
    ticker = request.args.get('ticker', '').upper().strip()
    if not ticker:
        return jsonify({'error': 'Missing ticker parameter'}), 400
    con = get_db()
    try:
        amendments = con.execute(
            f""  # nosec B608
            f"""
            WITH all_filings AS (
                SELECT cik, manager_name, rollup_name, inst_parent_name, quarter,
                       accession_number, shares, market_value_usd,
                       CASE WHEN accession_number IN (
                           SELECT accession_number FROM filings WHERE amended = true
                       ) THEN true ELSE false END as is_amended
                FROM holdings_v2
                WHERE ticker = ? AND quarter = '{LQ}'
            ),
            amended_managers AS (
                SELECT DISTINCT cik FROM filings
                WHERE amended = true AND quarter = '{LQ}'
            )
            SELECT COALESCE(a.rollup_name, a.inst_parent_name) as manager, a.shares, a.market_value_usd,
                   CASE WHEN a.cik IN (SELECT cik FROM amended_managers)
                        THEN 'Amended' ELSE 'Original' END as filing_status
            FROM all_filings a
            WHERE a.cik IN (SELECT cik FROM amended_managers)
            ORDER BY a.market_value_usd DESC LIMIT 30
            """, [ticker]
        ).fetchdf()

        return jsonify(clean_for_json({
            'ticker': ticker,
            'amendments': df_to_records(amendments),
        }))
    except Exception as e:
        current_app.logger.error("amendments error: %s", e)
        return jsonify({'error': str(e)}), 500
    finally:
        con.close()


@register_bp.route('/manager_profile')
def api_manager_profile():
    """Manager profile: all holdings, sector allocation, top positions."""
    manager = request.args.get('manager', '').strip()
    if not manager:
        return jsonify({'error': 'Missing manager parameter'}), 400
    con = get_db()
    try:
        top_holdings_df = con.execute(
            f""  # nosec B608
            f"""
            SELECT ticker, issuer_name, shares, market_value_usd, market_value_live,
                   pct_of_portfolio, pct_of_float
            FROM holdings_v2
            WHERE quarter = '{LQ}' AND COALESCE(rollup_name, inst_parent_name) ILIKE ?
            ORDER BY market_value_usd DESC LIMIT 50
            """, [f'%{manager}%']
        ).fetchdf()

        sectors = con.execute(
            f""  # nosec B608
            f"""
            SELECT m.sector, COUNT(DISTINCT h.ticker) as tickers,
                   SUM(h.market_value_usd) as value
            FROM holdings_v2 h
            LEFT JOIN market_data m ON h.ticker = m.ticker
            WHERE h.quarter = '{LQ}' AND COALESCE(h.rollup_name, h.inst_parent_name) ILIKE ?
              AND m.sector IS NOT NULL AND m.sector != ''
            GROUP BY m.sector
            ORDER BY value DESC LIMIT 10
            """, [f'%{manager}%']
        ).fetchdf()

        stats = con.execute(
            f""  # nosec B608
            f"""
            SELECT COUNT(DISTINCT ticker) as num_positions,
                   SUM(market_value_usd) as total_value,
                   COUNT(DISTINCT cik) as num_ciks,
                   MAX(manager_type) as manager_type
            FROM holdings_v2
            WHERE quarter = '{LQ}' AND COALESCE(rollup_name, inst_parent_name) ILIKE ?
            """, [f'%{manager}%']
        ).fetchone()

        qoq = con.execute("""
            SELECT quarter, COUNT(DISTINCT ticker) as positions,
                   SUM(market_value_usd) as total_value
            FROM holdings_v2 WHERE COALESCE(rollup_name, inst_parent_name) ILIKE ?
            GROUP BY quarter ORDER BY quarter
        """, [f'%{manager}%']).fetchdf()

        result = {
            'manager': manager,
            'num_positions': stats[0] if stats else 0,
            'total_value': stats[1] if stats else 0,
            'num_ciks': stats[2] if stats else 0,
            'manager_type': stats[3] if stats else None,
            'top_holdings': df_to_records(top_holdings_df),
            'sector_allocation': df_to_records(sectors),
            'quarterly_trend': df_to_records(qoq),
        }
        return jsonify(clean_for_json(result))
    except Exception as e:
        current_app.logger.error("manager_profile error: %s", e)
        return jsonify({'error': str(e)}), 500
    finally:
        con.close()


