"""Cross-ownership, overlap, and peer-group endpoints (FastAPI).

Routes:
  /api/v1/cross_ownership
  /api/v1/cross_ownership_top
  /api/v1/two_company_overlap
  /api/v1/two_company_subject
  /api/v1/peer_groups
  /api/v1/peer_groups/{group_id}
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from api_common import (
    get_rollup_type,
    validate_query_params_dep,
    validate_ticker_current,
    validate_ticker_historical,
)
from app_db import get_db, has_table
import queries
from queries import _cross_ownership_query, clean_for_json, df_to_records

log = logging.getLogger(__name__)

cross_router = APIRouter(
    prefix='/api/v1',
    tags=['cross'],
    dependencies=[Depends(validate_query_params_dep)],
)


@cross_router.get('/cross_ownership')
def api_cross_ownership(request: Request):
    """View 1: top holders of anchor company with cross-holdings in other tickers."""
    tickers_raw = (request.query_params.get('tickers') or '').upper().strip()
    anchor = (request.query_params.get('anchor') or '').upper().strip()
    active_only = request.query_params.get('active_only', 'false').lower() == 'true'
    limit = int(request.query_params.get('limit', 25))
    level = (request.query_params.get('level') or 'parent').strip().lower()
    if level not in ('parent', 'fund'):
        level = 'parent'
    rt = get_rollup_type(request)
    if not tickers_raw:
        return JSONResponse(status_code=400, content={'error': 'Missing tickers parameter'})
    tickers = [t.strip() for t in tickers_raw.split(',') if t.strip()][:10]
    if not anchor:
        anchor = tickers[0]
    try:
        con = get_db()
    except Exception as e:
        return JSONResponse(status_code=503, content={'error': f'Database unavailable: {e}'})
    try:
        for t in tickers:
            validate_ticker_current(con, t)
        return _cross_ownership_query(con, tickers, anchor=anchor,
                                      active_only=active_only, limit=limit,
                                      rollup_type=rt, level=level)
    finally:
        con.close()


@cross_router.get('/cross_ownership_top')
def api_cross_ownership_top(request: Request):
    """View 2: top investors by total exposure across all selected tickers."""
    tickers_raw = (request.query_params.get('tickers') or '').upper().strip()
    active_only = request.query_params.get('active_only', 'false').lower() == 'true'
    limit = int(request.query_params.get('limit', 25))
    level = (request.query_params.get('level') or 'parent').strip().lower()
    if level not in ('parent', 'fund'):
        level = 'parent'
    rt = get_rollup_type(request)
    if not tickers_raw:
        return JSONResponse(status_code=400, content={'error': 'Missing tickers parameter'})
    tickers = [t.strip() for t in tickers_raw.split(',') if t.strip()][:10]
    try:
        con = get_db()
    except Exception as e:
        return JSONResponse(status_code=503, content={'error': f'Database unavailable: {e}'})
    try:
        for t in tickers:
            validate_ticker_current(con, t)
        return _cross_ownership_query(con, tickers, anchor=None,
                                      active_only=active_only, limit=limit,
                                      rollup_type=rt, level=level)
    finally:
        con.close()


@cross_router.get('/cross_ownership_fund_detail')
def api_cross_ownership_fund_detail(request: Request):
    """Drill-down: top 5 funds under an institution holding the anchor ticker."""
    from config import QUARTERS as _QUARTERS, LATEST_QUARTER
    tickers_raw = (request.query_params.get('tickers') or '').upper().strip()
    institution = (request.query_params.get('institution') or '').strip()
    anchor = (request.query_params.get('anchor') or '').upper().strip()
    quarter = (request.query_params.get('quarter') or '').strip() or LATEST_QUARTER
    if quarter not in _QUARTERS:
        quarter = LATEST_QUARTER
    if not institution or not anchor:
        return JSONResponse(status_code=400, content={'error': 'Missing institution or anchor'})
    tickers = [t.strip() for t in tickers_raw.split(',') if t.strip()][:10]
    try:
        con = get_db()
    except Exception as e:
        return JSONResponse(status_code=503, content={'error': f'Database unavailable: {e}'})
    try:
        result = queries.get_cross_ownership_fund_detail(tickers, institution, anchor, quarter, con)
        return result
    except HTTPException:
        raise
    except Exception as e:
        log.error("cross_ownership_fund_detail error: %s", e, exc_info=True)
        return JSONResponse(status_code=500, content={'error': str(e)})
    finally:
        con.close()


@cross_router.get('/two_company_overlap')
def api_two_company_overlap(request: Request):
    """Two Companies Overlap tab — institutional and fund-level holder comparison."""
    from config import QUARTERS as _QUARTERS, LATEST_QUARTER
    subject = (request.query_params.get('subject') or '').upper().strip()
    second = (request.query_params.get('second') or '').upper().strip()
    quarter = (request.query_params.get('quarter') or '').strip() or LATEST_QUARTER
    if quarter not in _QUARTERS:
        quarter = LATEST_QUARTER
    if not subject or not second:
        return JSONResponse(status_code=400, content={'error': 'Missing subject or second ticker'})
    try:
        con = get_db()
    except Exception as e:
        return JSONResponse(status_code=503, content={'error': f'Database unavailable: {e}'})
    try:
        validate_ticker_historical(con, subject)
        validate_ticker_historical(con, second)
        result = queries.get_two_company_overlap(subject, second, quarter, con)
        return clean_for_json(result)
    except HTTPException:
        raise
    except Exception as e:
        log.error("two_company_overlap error: %s", e, exc_info=True)
        return JSONResponse(status_code=500, content={'error': str(e)})
    finally:
        con.close()


@cross_router.get('/two_company_subject')
def api_two_company_subject(request: Request):
    """Return top 50 holders for subject ticker only — used for immediate
    tab load before the user selects a second company."""
    from config import QUARTERS as _QUARTERS, LATEST_QUARTER
    subject = (request.query_params.get('subject') or '').upper().strip()
    quarter = (request.query_params.get('quarter') or '').strip() or LATEST_QUARTER
    if quarter not in _QUARTERS:
        quarter = LATEST_QUARTER
    if not subject:
        return JSONResponse(status_code=400, content={'error': 'Missing subject ticker'})
    try:
        con = get_db()
    except Exception as e:
        return JSONResponse(status_code=503, content={'error': f'Database unavailable: {e}'})
    try:
        validate_ticker_historical(con, subject)
        result = queries.get_two_company_subject(subject, quarter, con)
        return clean_for_json(result)
    except HTTPException:
        raise
    except Exception as e:
        log.error("two_company_subject error: %s", e, exc_info=True)
        return JSONResponse(status_code=500, content={'error': str(e)})
    finally:
        con.close()


@cross_router.get('/overlap_institution_detail')
def api_overlap_institution_detail(request: Request):
    """Drill-down: funds under an institution holding subject/second tickers."""
    from config import QUARTERS as _QUARTERS, LATEST_QUARTER
    subject = (request.query_params.get('subject') or '').upper().strip()
    second = (request.query_params.get('second') or '').upper().strip()
    institution = (request.query_params.get('institution') or '').strip()
    quarter = (request.query_params.get('quarter') or '').strip() or LATEST_QUARTER
    if quarter not in _QUARTERS:
        quarter = LATEST_QUARTER
    if not subject or not second or not institution:
        return JSONResponse(status_code=400, content={'error': 'Missing subject, second, or institution'})
    try:
        con = get_db()
    except Exception as e:
        return JSONResponse(status_code=503, content={'error': f'Database unavailable: {e}'})
    try:
        validate_ticker_historical(con, subject)
        validate_ticker_historical(con, second)
        result = queries.get_overlap_institution_detail(subject, second, institution, quarter, con)
        return clean_for_json(result)
    except HTTPException:
        raise
    except Exception as e:
        log.error("overlap_institution_detail error: %s", e, exc_info=True)
        return JSONResponse(status_code=500, content={'error': str(e)})
    finally:
        con.close()


@cross_router.get('/peer_groups')
def api_peer_groups():
    """Return all peer groups."""
    con = get_db()
    try:
        if not has_table('peer_groups'):
            return []
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
        return list(groups.values())
    finally:
        con.close()


@cross_router.get('/peer_groups/{group_id}')
def api_peer_group_detail(group_id: str):
    """Return tickers in a specific peer group."""
    con = get_db()
    try:
        df = con.execute("""
            SELECT ticker, company_name, is_primary
            FROM peer_groups
            WHERE group_id = ?
            ORDER BY is_primary DESC, ticker
        """, [group_id]).fetchdf()
        return df_to_records(df)
    finally:
        con.close()
