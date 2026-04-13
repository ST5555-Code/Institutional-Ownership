"""Fund-lookup endpoints.

Split out of api_register.py in Phase 4 Batch 4-A to keep register under
the 400-line target. These endpoints share the fund-centric data model
(fund_holdings_v2 + entity_identifiers + series_id) and a distinct
consumer — the Fund Portfolio tab + fund drill-down UIs.

Routes:
  /api/v1/fund_rollup_context
  /api/v1/fund_portfolio_managers
  /api/v1/fund_behavioral_profile
  /api/v1/nport_shorts
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from api_common import LQ
from app_db import get_db
from queries import clean_for_json, df_to_records

fund_bp = Blueprint('api_fund', __name__, url_prefix='/api/v1')


@fund_bp.route('/fund_rollup_context')
def api_fund_rollup_context():
    """Return economic and decision-maker rollup names for a given CIK or series_id.
    Used by L4 Fund Portfolio tab to show rollup context panel above holdings table.
    """
    cik = request.args.get('cik', '').strip()
    series_id = request.args.get('series_id', '').strip()
    if not cik and not series_id:
        return jsonify({'error': 'Missing cik or series_id parameter'}), 400
    try:
        con = get_db()
    except Exception as e:
        return jsonify({'error': f'Database unavailable: {e}'}), 503
    try:
        if cik:
            row = con.execute("""
                SELECT entity_id FROM entity_identifiers
                WHERE identifier_value = ? AND identifier_type = 'cik'
                  AND valid_to = '9999-12-31' LIMIT 1
            """, [cik]).fetchone()
        else:
            row = con.execute("""
                SELECT entity_id FROM entity_identifiers
                WHERE identifier_value = ? AND identifier_type = 'series_id'
                  AND valid_to = '9999-12-31' LIMIT 1
            """, [series_id]).fetchone()

        if not row:
            return jsonify({'error': 'Entity not found', 'cik': cik, 'series_id': series_id}), 404

        entity_id = row[0]

        ec = con.execute("""
            SELECT ea.alias_name FROM entity_rollup_history erh
            LEFT JOIN entity_aliases ea ON erh.rollup_entity_id = ea.entity_id
                AND ea.is_preferred = TRUE AND ea.valid_to = '9999-12-31'
            WHERE erh.entity_id = ? AND erh.rollup_type = 'economic_control_v1'
              AND erh.valid_to = '9999-12-31'
        """, [entity_id]).fetchone()

        dm = con.execute("""
            SELECT ea.alias_name FROM entity_rollup_history erh
            LEFT JOIN entity_aliases ea ON erh.rollup_entity_id = ea.entity_id
                AND ea.is_preferred = TRUE AND ea.valid_to = '9999-12-31'
            WHERE erh.entity_id = ? AND erh.rollup_type = 'decision_maker_v1'
              AND erh.valid_to = '9999-12-31'
        """, [entity_id]).fetchone()

        ec_name = ec[0] if ec else None
        dm_name = dm[0] if dm else None

        return jsonify({
            'entity_id': entity_id,
            'economic_sponsor': ec_name,
            'decision_maker': dm_name,
            'same': ec_name == dm_name,
        })
    finally:
        con.close()


@fund_bp.route('/fund_portfolio_managers')
def api_fund_portfolio_managers():
    ticker = request.args.get('ticker', '').upper().strip()
    if not ticker:
        return jsonify({'error': 'Missing ticker parameter'}), 400
    try:
        con = get_db()
    except Exception as e:
        return jsonify({'error': f'Database unavailable: {e}'}), 503
    try:
        df = con.execute(
            f""  # nosec B608
            f"""
            SELECT
                cik,
                fund_name,
                MAX(COALESCE(rollup_name, inst_parent_name, manager_name)) as inst_parent_name,
                SUM(market_value_live) as position_value,
                MAX(manager_type) as manager_type
            FROM holdings_v2
            WHERE ticker = ? AND quarter = '{LQ}'
              AND entity_type NOT IN ('passive')
            GROUP BY cik, fund_name
            ORDER BY position_value DESC NULLS LAST
            LIMIT 50
            """, [ticker]
        ).fetchdf()
        return jsonify(df_to_records(df))
    finally:
        con.close()


@fund_bp.route('/fund_behavioral_profile')
def api_fund_behavioral_profile():
    """Behavioral profile for a fund by LEI or series_id — historical positions."""
    lei = request.args.get('lei', '').strip()
    series_id = request.args.get('series_id', '').strip()
    if not lei and not series_id:
        return jsonify({'error': 'Missing lei or series_id parameter'}), 400

    con = get_db()
    try:
        if lei:
            where = "lei = ?"
            param = lei
        else:
            where = "series_id = ?"
            param = series_id

        fund_info = con.execute(
            f""  # nosec B608
            f"""
            SELECT fund_name, series_id, lei, family_name, COUNT(DISTINCT quarter) as quarters
            FROM fund_holdings_v2 WHERE {where}
            GROUP BY fund_name, series_id, lei, family_name
            LIMIT 1
            """, [param]
        ).fetchone()
        if not fund_info:
            return jsonify({'error': 'Fund not found'}), 404

        fund_name, sid, fund_lei, family, quarters = fund_info

        size_stats = con.execute(
            f""  # nosec B608
            f"""
            SELECT
                AVG(pct_of_nav) as avg_pct_nav,
                MEDIAN(pct_of_nav) as median_pct_nav,
                MAX(pct_of_nav) as max_pct_nav,
                COUNT(DISTINCT ticker) as unique_holdings,
                COUNT(DISTINCT quarter) as quarters_held
            FROM fund_holdings_v2
            WHERE {where} AND pct_of_nav IS NOT NULL AND pct_of_nav > 0
            """, [param]
        ).fetchone()

        sector_where = "fh.lei = ?" if lei else "fh.series_id = ?"
        sectors = con.execute(
            f""  # nosec B608
            f"""
            SELECT s.sector, SUM(fh.market_value_usd) as sector_value
            FROM fund_holdings_v2 fh
            JOIN securities s ON fh.cusip = s.cusip
            WHERE {sector_where}
              AND fh.quarter = '{LQ}'
              AND s.sector IS NOT NULL AND s.sector != ''
            GROUP BY s.sector
            ORDER BY sector_value DESC
            LIMIT 10
            """, [param]
        ).fetchdf()

        top = con.execute(
            f""  # nosec B608
            f"""
            SELECT ticker, issuer_name, market_value_usd, pct_of_nav, shares_or_principal
            FROM fund_holdings_v2
            WHERE {where} AND quarter = '{LQ}'
            ORDER BY market_value_usd DESC NULLS LAST
            LIMIT 10
            """, [param]
        ).fetchdf()

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


@fund_bp.route('/nport_shorts')
def api_nport_shorts():
    """N-PORT negative balance positions — fund short positions from filings."""
    ticker = request.args.get('ticker', '').upper().strip()
    con = get_db()
    try:
        where = "AND fh.ticker = ?" if ticker else ""
        params = [ticker] if ticker else []
        df = con.execute(
            f""  # nosec B608
            f"""
            SELECT
                fh.fund_name,
                fh.ticker,
                fh.issuer_name,
                fh.shares_or_principal AS shares_short,
                fh.market_value_usd AS short_value,
                fh.pct_of_nav,
                fh.quarter,
                fh.family_name
            FROM fund_holdings_v2 fh
            WHERE fh.shares_or_principal < 0
              AND fh.asset_category IN ('EC', 'EP')
              {where}
            ORDER BY fh.market_value_usd ASC
            LIMIT 200
            """, params
        ).fetchdf()
        return jsonify(df_to_records(df))
    finally:
        con.close()
