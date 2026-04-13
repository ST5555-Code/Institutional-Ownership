"""Flow / trend / rotation / conviction endpoints (FastAPI).

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

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from api_common import (
    envelope_error,
    envelope_success,
    get_rollup_type,
    validate_query_params_dep,
)
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

log = logging.getLogger(__name__)

flows_router = APIRouter(
    prefix='/api/v1',
    tags=['flows'],
    dependencies=[Depends(validate_query_params_dep)],
)


@flows_router.get('/flow_analysis', response_model=FlowAnalysisEnvelope)
def api_flow_analysis(request: Request):
    ticker = (request.query_params.get('ticker') or '').upper().strip()
    period = (request.query_params.get('period') or '1Q').upper().strip()
    peers = (request.query_params.get('peers') or '').upper().strip() or None
    level = (request.query_params.get('level') or 'parent').strip()
    ao = (request.query_params.get('active_only') or '').strip() == 'true'
    rt = get_rollup_type(request)
    if not ticker:
        return envelope_error(
            'missing_param', 'Missing ticker parameter',
            request, schema=FlowAnalysisEnvelope, status=400,
        )
    try:
        result = flow_analysis(ticker, period=period, peers=peers, level=level,
                               active_only=ao, rollup_type=rt)
        return envelope_success(clean_for_json(result), request, schema=FlowAnalysisEnvelope)
    except Exception as e:
        return envelope_error(
            'internal_error', str(e),
            request, schema=FlowAnalysisEnvelope, status=500,
        )


@flows_router.get('/ownership_trend_summary', response_model=OwnershipTrendEnvelope)
def api_ownership_trend_summary(request: Request):
    ticker = (request.query_params.get('ticker') or '').upper().strip()
    level = (request.query_params.get('level') or 'parent').strip()
    ao = (request.query_params.get('active_only') or '').strip() == 'true'
    rt = get_rollup_type(request)
    if not ticker:
        return envelope_error(
            'missing_param', 'Missing ticker parameter',
            request, schema=OwnershipTrendEnvelope, status=400,
        )
    try:
        result = ownership_trend_summary(ticker, level=level, active_only=ao, rollup_type=rt)
        return envelope_success(clean_for_json(result), request, schema=OwnershipTrendEnvelope)
    except Exception as e:
        return envelope_error(
            'internal_error', str(e),
            request, schema=OwnershipTrendEnvelope, status=500,
        )


@flows_router.get('/cohort_analysis')
def api_cohort_analysis(request: Request):
    ticker = (request.query_params.get('ticker') or '').upper().strip()
    from_q = (request.query_params.get('from') or '').strip() or None
    level = (request.query_params.get('level') or 'parent').strip()
    active_only = (request.query_params.get('active_only') or '').strip() == 'true'
    rt = get_rollup_type(request)
    if not ticker:
        return JSONResponse(status_code=400, content={'error': 'Missing ticker parameter'})
    try:
        result = cohort_analysis(ticker, from_quarter=from_q, level=level,
                                 active_only=active_only, rollup_type=rt)
        return clean_for_json(result)
    except Exception as e:
        return JSONResponse(status_code=500, content={'error': str(e)})


@flows_router.get('/holder_momentum')
def api_holder_momentum(request: Request):
    ticker = (request.query_params.get('ticker') or '').upper().strip()
    level = (request.query_params.get('level') or 'parent').strip()
    ao = (request.query_params.get('active_only') or '').strip() == 'true'
    rt = get_rollup_type(request)
    if not ticker:
        return JSONResponse(status_code=400, content={'error': 'Missing ticker parameter'})
    try:
        result = holder_momentum(ticker, level=level, active_only=ao, rollup_type=rt)
        return clean_for_json(result)
    except Exception as e:
        return JSONResponse(status_code=500, content={'error': str(e)})


@flows_router.get('/peer_rotation')
def api_peer_rotation(request: Request):
    """Peer rotation analysis: subject vs sector/industry peer substitutions."""
    try:
        from queries import get_peer_rotation
        ticker = (request.query_params.get('ticker') or '').upper().strip()
        if not ticker:
            return JSONResponse(status_code=400, content={'error': 'Missing ticker param'})
        active_only = request.query_params.get('active_only', '0') == '1'
        level = (request.query_params.get('level') or 'parent').strip()
        rt = get_rollup_type(request)
        result = get_peer_rotation(ticker, active_only=active_only, level=level, rollup_type=rt)
        return result
    except Exception as e:
        log.error("peer_rotation error: %s", e)
        return JSONResponse(status_code=500, content={'error': str(e)})


@flows_router.get('/peer_rotation_detail')
def api_peer_rotation_detail(request: Request):
    """Entity-level breakdown for a subject+peer substitution pair."""
    try:
        from queries import get_peer_rotation_detail
        ticker = (request.query_params.get('ticker') or '').upper().strip()
        peer = (request.query_params.get('peer') or '').upper().strip()
        if not ticker or not peer:
            return JSONResponse(status_code=400, content={'error': 'Missing ticker or peer param'})
        active_only = request.query_params.get('active_only', '0') == '1'
        level = (request.query_params.get('level') or 'parent').strip()
        rt = get_rollup_type(request)
        result = get_peer_rotation_detail(
            ticker, peer, active_only=active_only, level=level, rollup_type=rt)
        return result
    except Exception as e:
        log.error("peer_rotation_detail error: %s", e)
        return JSONResponse(status_code=500, content={'error': str(e)})


@flows_router.get('/portfolio_context', response_model=ConvictionEnvelope)
def api_portfolio_context(request: Request):
    """Conviction tab — portfolio concentration context."""
    ticker = (request.query_params.get('ticker') or '').upper().strip()
    level = (request.query_params.get('level') or 'parent').strip()
    ao = (request.query_params.get('active_only') or '').strip() == 'true'
    if not ticker:
        return envelope_error(
            'missing_param', 'Missing ticker parameter',
            request, schema=ConvictionEnvelope, status=400,
        )
    try:
        rt = get_rollup_type(request)
        result = portfolio_context(ticker, level=level, active_only=ao, rollup_type=rt)
        return envelope_success(clean_for_json(result), request, schema=ConvictionEnvelope)
    except Exception as e:
        return envelope_error(
            'internal_error', str(e),
            request, schema=ConvictionEnvelope, status=500,
        )
