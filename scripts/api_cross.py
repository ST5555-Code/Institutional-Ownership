"""Cross-ownership, overlap, and peer-group endpoints.

Routes:
  /api/v1/cross_ownership
  /api/v1/cross_ownership_top
  /api/v1/two_company_overlap
  /api/v1/two_company_subject
  /api/v1/peer_groups
  /api/v1/peer_groups/<group_id>
"""
from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from api_common import _get_rollup_type
from app_db import get_db, has_table
import queries
from queries import _cross_ownership_query, clean_for_json, df_to_records

cross_bp = Blueprint('api_cross', __name__, url_prefix='/api/v1')


@cross_bp.route('/cross_ownership')
def api_cross_ownership():
    """View 1: top holders of anchor company with cross-holdings in other tickers."""
    tickers_raw = request.args.get('tickers', '').upper().strip()
    anchor = request.args.get('anchor', '').upper().strip()
    active_only = request.args.get('active_only', 'false').lower() == 'true'
    limit = int(request.args.get('limit', 25))
    rt = _get_rollup_type(request)
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
                                              active_only=active_only, limit=limit,
                                              rollup_type=rt))
    finally:
        con.close()


@cross_bp.route('/cross_ownership_top')
def api_cross_ownership_top():
    """View 2: top investors by total exposure across all selected tickers."""
    tickers_raw = request.args.get('tickers', '').upper().strip()
    active_only = request.args.get('active_only', 'false').lower() == 'true'
    limit = int(request.args.get('limit', 25))
    rt = _get_rollup_type(request)
    if not tickers_raw:
        return jsonify({'error': 'Missing tickers parameter'}), 400
    tickers = [t.strip() for t in tickers_raw.split(',') if t.strip()][:10]
    try:
        con = get_db()
    except Exception as e:
        return jsonify({'error': f'Database unavailable: {e}'}), 503
    try:
        return jsonify(_cross_ownership_query(con, tickers, anchor=None,
                                              active_only=active_only, limit=limit,
                                              rollup_type=rt))
    finally:
        con.close()


@cross_bp.route('/two_company_overlap')
def api_two_company_overlap():
    """Two Companies Overlap tab — institutional and fund-level holder comparison."""
    from config import QUARTERS as _QUARTERS, LATEST_QUARTER
    subject = request.args.get('subject', '').upper().strip()
    second = request.args.get('second', '').upper().strip()
    quarter = request.args.get('quarter', '').strip() or LATEST_QUARTER
    if quarter not in _QUARTERS:
        quarter = LATEST_QUARTER
    if not subject or not second:
        return jsonify({'error': 'Missing subject or second ticker'}), 400
    try:
        con = get_db()
    except Exception as e:
        return jsonify({'error': f'Database unavailable: {e}'}), 503
    try:
        result = queries.get_two_company_overlap(subject, second, quarter, con)
        return jsonify(clean_for_json(result))
    except Exception as e:
        current_app.logger.error("two_company_overlap error: %s", e, exc_info=True)
        return jsonify({'error': str(e)}), 500
    finally:
        con.close()


@cross_bp.route('/two_company_subject')
def api_two_company_subject():
    """Return top 50 holders for subject ticker only — used for immediate
    tab load before the user selects a second company. Same payload shape
    as /api/v1/two_company_overlap with all sec_* fields set to None."""
    from config import QUARTERS as _QUARTERS, LATEST_QUARTER
    subject = request.args.get('subject', '').upper().strip()
    quarter = request.args.get('quarter', '').strip() or LATEST_QUARTER
    if quarter not in _QUARTERS:
        quarter = LATEST_QUARTER
    if not subject:
        return jsonify({'error': 'Missing subject ticker'}), 400
    try:
        con = get_db()
    except Exception as e:
        return jsonify({'error': f'Database unavailable: {e}'}), 503
    try:
        result = queries.get_two_company_subject(subject, quarter, con)
        return jsonify(clean_for_json(result))
    except Exception as e:
        current_app.logger.error("two_company_subject error: %s", e, exc_info=True)
        return jsonify({'error': str(e)}), 500
    finally:
        con.close()


@cross_bp.route('/peer_groups')
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


@cross_bp.route('/peer_groups/<group_id>')
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
