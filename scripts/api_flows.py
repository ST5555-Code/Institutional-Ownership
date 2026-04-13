"""Flow / trend / rotation / conviction endpoints.

Routes:
  /api/v1/flow_analysis            (enveloped, Phase 1-B2)
  /api/v1/ownership_trend_summary  (enveloped, Phase 1-B2)
  /api/v1/cohort_analysis
  /api/v1/holder_momentum
  /api/v1/peer_rotation
  /api/v1/peer_rotation_detail
  /api/v1/portfolio_context        (enveloped, Phase 1-B2)
"""
from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from api_common import _get_rollup_type, respond
from queries import (
    clean_for_json,
    cohort_analysis,
    flow_analysis,
    holder_momentum,
    ownership_trend_summary,
    portfolio_context,
)
from schemas import (
    ConvictionEnvelope,
    FlowAnalysisEnvelope,
    OwnershipTrendEnvelope,
)

flows_bp = Blueprint('api_flows', __name__, url_prefix='/api/v1')


@flows_bp.route('/flow_analysis')
def api_flow_analysis():
    ticker = request.args.get('ticker', '').upper().strip()
    period = request.args.get('period', '1Q').upper().strip()
    peers = request.args.get('peers', '').upper().strip() or None
    level = request.args.get('level', 'parent').strip()
    ao = request.args.get('active_only', '').strip() == 'true'
    rt = _get_rollup_type(request)
    if not ticker:
        return respond(
            error={'code': 'missing_param', 'message': 'Missing ticker parameter'},
            schema=FlowAnalysisEnvelope,
            status=400,
        )
    try:
        result = flow_analysis(ticker, period=period, peers=peers, level=level,
                               active_only=ao, rollup_type=rt)
        return respond(data=clean_for_json(result), schema=FlowAnalysisEnvelope)
    except Exception as e:
        return respond(
            error={'code': 'internal_error', 'message': str(e)},
            schema=FlowAnalysisEnvelope,
            status=500,
        )


@flows_bp.route('/ownership_trend_summary')
def api_ownership_trend_summary():
    ticker = request.args.get('ticker', '').upper().strip()
    level = request.args.get('level', 'parent').strip()
    ao = request.args.get('active_only', '').strip() == 'true'
    rt = _get_rollup_type(request)
    if not ticker:
        return respond(
            error={'code': 'missing_param', 'message': 'Missing ticker parameter'},
            schema=OwnershipTrendEnvelope,
            status=400,
        )
    try:
        result = ownership_trend_summary(ticker, level=level, active_only=ao, rollup_type=rt)
        return respond(data=clean_for_json(result), schema=OwnershipTrendEnvelope)
    except Exception as e:
        return respond(
            error={'code': 'internal_error', 'message': str(e)},
            schema=OwnershipTrendEnvelope,
            status=500,
        )


@flows_bp.route('/cohort_analysis')
def api_cohort_analysis():
    ticker = request.args.get('ticker', '').upper().strip()
    from_q = request.args.get('from', '').strip() or None
    level = request.args.get('level', 'parent').strip()
    active_only = request.args.get('active_only', '').strip() == 'true'
    rt = _get_rollup_type(request)
    if not ticker:
        return jsonify({'error': 'Missing ticker parameter'}), 400
    try:
        result = cohort_analysis(ticker, from_quarter=from_q, level=level,
                                 active_only=active_only, rollup_type=rt)
        return jsonify(clean_for_json(result))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@flows_bp.route('/holder_momentum')
def api_holder_momentum():
    ticker = request.args.get('ticker', '').upper().strip()
    level = request.args.get('level', 'parent').strip()
    ao = request.args.get('active_only', '').strip() == 'true'
    rt = _get_rollup_type(request)
    if not ticker:
        return jsonify({'error': 'Missing ticker parameter'}), 400
    try:
        result = holder_momentum(ticker, level=level, active_only=ao, rollup_type=rt)
        return jsonify(clean_for_json(result))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@flows_bp.route('/peer_rotation')
def api_peer_rotation():
    """Peer rotation analysis: subject vs sector/industry peer substitutions."""
    try:
        from queries import get_peer_rotation
        ticker = request.args.get('ticker', '').upper().strip()
        if not ticker:
            return jsonify({'error': 'Missing ticker param'}), 400
        active_only = request.args.get('active_only', '0') == '1'
        level = request.args.get('level', 'parent').strip()
        rt = _get_rollup_type(request)
        result = get_peer_rotation(ticker, active_only=active_only, level=level, rollup_type=rt)
        return jsonify(result)
    except Exception as e:
        current_app.logger.error("peer_rotation error: %s", e)
        return jsonify({'error': str(e)}), 500


@flows_bp.route('/peer_rotation_detail')
def api_peer_rotation_detail():
    """Entity-level breakdown for a subject+peer substitution pair."""
    try:
        from queries import get_peer_rotation_detail
        ticker = request.args.get('ticker', '').upper().strip()
        peer = request.args.get('peer', '').upper().strip()
        if not ticker or not peer:
            return jsonify({'error': 'Missing ticker or peer param'}), 400
        active_only = request.args.get('active_only', '0') == '1'
        level = request.args.get('level', 'parent').strip()
        rt = _get_rollup_type(request)
        result = get_peer_rotation_detail(
            ticker, peer, active_only=active_only, level=level, rollup_type=rt)
        return jsonify(result)
    except Exception as e:
        current_app.logger.error("peer_rotation_detail error: %s", e)
        return jsonify({'error': str(e)}), 500


@flows_bp.route('/portfolio_context')
def api_portfolio_context():
    """Conviction tab — portfolio concentration context."""
    ticker = request.args.get('ticker', '').upper().strip()
    level = request.args.get('level', 'parent').strip()
    ao = request.args.get('active_only', '').strip() == 'true'
    if not ticker:
        return respond(
            error={'code': 'missing_param', 'message': 'Missing ticker parameter'},
            schema=ConvictionEnvelope,
            status=400,
        )
    try:
        rt = _get_rollup_type(request)
        result = portfolio_context(ticker, level=level, active_only=ao, rollup_type=rt)
        return respond(data=clean_for_json(result), schema=ConvictionEnvelope)
    except Exception as e:
        return respond(
            error={'code': 'internal_error', 'message': str(e)},
            schema=ConvictionEnvelope,
            status=500,
        )
