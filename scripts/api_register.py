"""Register + query dispatch endpoints (FastAPI).

Routes:
  /api/v1/tickers                 (enveloped, Phase 1-B2)
  /api/v1/summary
  /api/v1/query1                  (enveloped, Phase 1-B2)
  /api/v1/query{qnum}             (bare, queries 2–16)
  /api/v1/export/query{qnum}
  /api/v1/amendments
  /api/v1/manager_profile

Fund-lookup endpoints live in api_fund.py.
"""
from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from api_common import (
    LQ,
    QUERY_FUNCTIONS,
    _RT_AWARE_QUERIES,
    envelope_error,
    envelope_success,
    get_rollup_type,
    validate_query_params_dep,
    validate_ticker_current,
    validate_ticker_historical,
)
from app_db import get_db
from export import build_excel, build_excel_multisheet
from queries import clean_for_json, df_to_records, get_summary
from schemas import RegisterEnvelope, TickersEnvelope

log = logging.getLogger(__name__)

register_router = APIRouter(
    prefix='/api/v1',
    tags=['register'],
    dependencies=[Depends(validate_query_params_dep)],
)


QUERY_NAMES = {
    1: 'Register', 2: 'Holder Changes', 3: 'Conviction',
    6: 'Activist', 7: 'Fund Portfolio', 8: 'Cross-Ownership',
    9: 'Sector Rotation', 10: 'New Positions', 11: 'Exits',
    14: 'AUM vs Position', 15: 'DB Statistics',
}

# BL-7 ticker validation dispatch:
#   HISTORICAL_QUERIES — queries that intentionally span multiple quarters
#     (FQ→LQ, PQ→LQ, quarter heatmaps). A ticker valid historically but
#     absent from LQ must still pass.
#   q7   — fund-portfolio lookup keyed on cik/fund_name; skip ticker
#          validation (existing 404 on empty positions already handles bad
#          inputs).
#   q15  — global DB stats; no ticker required.
#   All others default to current validator. If ?quarter= is explicitly
#   passed AND != LQ, the current-family queries override to historical.
_HISTORICAL_QUERIES = frozenset({2, 5, 9, 10, 11})
_SKIP_TICKER_VALIDATION = frozenset({7, 15})


# SMOKE TEST: /api/v1/tickers is the autocomplete root — a silent 500 here
# breaks the entire UI ticker search. Always include in post-commit curl.
@register_router.get('/tickers', response_model=TickersEnvelope)
def api_tickers(request: Request):
    try:
        con = get_db()
    except Exception as e:
        return envelope_error(
            'db_unavailable', f'Database unavailable: {e}',
            request, schema=TickersEnvelope, status=503,
        )
    try:
        df = con.execute(
            f""  # nosec B608
            f"""
            SELECT ticker, MODE(issuer_name) as name
            FROM holdings_v2
            WHERE ticker IS NOT NULL AND ticker != '' AND quarter = '{LQ}' AND is_latest = TRUE
            GROUP BY ticker
            ORDER BY ticker
            """
        ).fetchdf()
        return envelope_success(df_to_records(df), request, schema=TickersEnvelope)
    finally:
        con.close()


@register_router.get('/summary')
def api_summary(ticker: str = ''):
    ticker = (ticker or '').upper().strip()
    if not ticker:
        return JSONResponse(status_code=400, content={'error': 'Missing ticker parameter'})
    con = get_db()
    try:
        validate_ticker_historical(con, ticker)
    finally:
        con.close()
    result = get_summary(ticker)
    if not result:
        return JSONResponse(
            status_code=404,
            content={'error': f'No data found for ticker {ticker}'},
        )
    return result


def _execute_query(qnum: int, request: Request):
    """Run query-N dispatch. Returns (data, error_dict, status).

    Shared by the generic /api/v1/query{N} handler AND the dedicated
    /api/v1/query1 envelope handler. Error shape is ErrorShape-compatible
    so callers can wrap in envelope_error() or JSONResponse as needed.
    """
    if qnum not in QUERY_FUNCTIONS:
        return None, {'code': 'invalid_query', 'message': f'Invalid query number: {qnum}'}, 400
    ticker = (request.query_params.get('ticker') or '').upper().strip()
    cik = (request.query_params.get('cik') or '').strip()
    quarter_raw = request.query_params.get('quarter')
    quarter = quarter_raw if quarter_raw else LQ
    rt = get_rollup_type(request)

    if qnum not in (15,) and not ticker:
        return None, {'code': 'missing_param', 'message': 'Missing ticker parameter'}, 400

    # BL-7: validate ticker against DB universe before dispatching to query fn.
    if ticker and qnum not in _SKIP_TICKER_VALIDATION:
        con = get_db()
        try:
            if qnum in _HISTORICAL_QUERIES or (quarter_raw and quarter_raw != LQ):
                validate_ticker_historical(con, ticker)
            else:
                validate_ticker_current(con, ticker)
        finally:
            con.close()

    try:
        fn = QUERY_FUNCTIONS[qnum]
        if qnum == 7:
            fund_name = (request.query_params.get('fund_name') or '').strip() or None
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


@register_router.get('/query1', response_model=RegisterEnvelope)
def api_query1(request: Request):
    """Register tab — enveloped per Phase 1-B2. Queries 2–16 stay bare."""
    data, err, status = _execute_query(1, request)
    if err is not None:
        return envelope_error(err['code'], err['message'], request,
                              schema=RegisterEnvelope, status=status)
    return envelope_success(data, request, schema=RegisterEnvelope, status=status)


@register_router.get('/query{qnum}')
def api_query(qnum: int, request: Request):
    if qnum == 1:
        # More-specific /query1 route wins in FastAPI; defend in depth.
        return api_query1(request)
    data, err, status = _execute_query(qnum, request)
    if err is not None:
        return JSONResponse(status_code=status, content={'error': err['message']})
    return data


@register_router.get('/export/query{qnum}')
def api_export(qnum: int, request: Request):
    if qnum not in QUERY_FUNCTIONS:
        return JSONResponse(status_code=400, content={'error': f'Invalid query number: {qnum}'})
    ticker = (request.query_params.get('ticker') or '').upper().strip()
    cik = (request.query_params.get('cik') or '').strip()
    quarter_raw = request.query_params.get('quarter')
    quarter = quarter_raw if quarter_raw else LQ
    rt = get_rollup_type(request)

    if qnum not in (15,) and not ticker:
        return JSONResponse(status_code=400, content={'error': 'Missing ticker parameter'})

    # BL-7: mirror _execute_query validation dispatch.
    if ticker and qnum not in _SKIP_TICKER_VALIDATION:
        con = get_db()
        try:
            if qnum in _HISTORICAL_QUERIES or (quarter_raw and quarter_raw != LQ):
                validate_ticker_historical(con, ticker)
            else:
                validate_ticker_current(con, ticker)
        finally:
            con.close()

    try:
        fn = QUERY_FUNCTIONS[qnum]
        if qnum == 7:
            fund_name = (request.query_params.get('fund_name') or '').strip() or None
            data = fn(ticker, cik=cik or None, fund_name=fund_name, quarter=quarter)
        elif qnum == 15:
            data = fn(ticker or None, quarter=quarter)
        elif qnum in _RT_AWARE_QUERIES:
            data = fn(ticker, rollup_type=rt, quarter=quarter)
        else:
            data = fn(ticker, quarter=quarter)

        if not data:
            return JSONResponse(
                status_code=404,
                content={'error': f'No data found for ticker {ticker}'},
            )

        # Extract the tabular portion from structured responses:
        #   q7         → {stats, positions}              export `positions`
        #   q1, q16    → {rows, all_totals, type_totals} export `rows`
        #   q6/q10/q11 → multi-list dict                 → multi-sheet
        #   q15        → [{scalars, quarters[], coverage{}}]  → multi-sheet
        qname = QUERY_NAMES.get(qnum, f'Query{qnum}')
        sheet_name = f"{qname} - {ticker or 'ALL'}"
        multisheet = None
        export_data = data

        if isinstance(data, dict):
            if 'positions' in data:
                export_data = data['positions']
            elif 'rows' in data:
                export_data = data['rows']
            else:
                multisheet = {k: v for k, v in data.items()}
        elif (
            isinstance(data, list)
            and len(data) == 1
            and isinstance(data[0], dict)
            and any(isinstance(v, (list, dict)) for v in data[0].values())
        ):
            row = data[0]
            scalars = {k: v for k, v in row.items() if not isinstance(v, (list, dict))}
            multisheet = {}
            if scalars:
                multisheet['Overview'] = [scalars]
            for k, v in row.items():
                if isinstance(v, (list, dict)):
                    multisheet[k] = v

        if multisheet is not None:
            buf = build_excel_multisheet(multisheet)
        else:
            buf = build_excel(export_data, sheet_name=sheet_name)

        filename = f"query{qnum}_{ticker or 'ALL'}_{datetime.now().strftime('%Y%m%d')}.xlsx"
        return StreamingResponse(
            buf,
            media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            headers={'Content-Disposition': f'attachment; filename="{filename}"'},
        )
    except Exception as e:
        return JSONResponse(status_code=500, content={'error': str(e)})


@register_router.get('/amendments')
def api_amendments(ticker: str = ''):
    """13F-HR amendment reconciliation: show amended vs original filings per quarter."""
    ticker = (ticker or '').upper().strip()
    if not ticker:
        return JSONResponse(status_code=400, content={'error': 'Missing ticker parameter'})
    con = get_db()
    try:
        validate_ticker_current(con, ticker)
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
                WHERE ticker = ? AND quarter = '{LQ}' AND is_latest = TRUE
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

        return clean_for_json({
            'ticker': ticker,
            'amendments': df_to_records(amendments),
        })
    except HTTPException:
        raise
    except Exception as e:
        log.error("amendments error: %s", e)
        return JSONResponse(status_code=500, content={'error': str(e)})
    finally:
        con.close()


@register_router.get('/manager_profile')
def api_manager_profile(manager: str = ''):
    """Manager profile: all holdings, sector allocation, top positions."""
    manager = (manager or '').strip()
    if not manager:
        return JSONResponse(status_code=400, content={'error': 'Missing manager parameter'})
    con = get_db()
    try:
        top_holdings_df = con.execute(
            f""  # nosec B608
            f"""
            SELECT ticker, issuer_name, shares, market_value_usd, market_value_live,
                   pct_of_portfolio, pct_of_so
            FROM holdings_v2
            WHERE quarter = '{LQ}' AND COALESCE(rollup_name, inst_parent_name) ILIKE ? AND is_latest = TRUE
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
              AND h.is_latest = TRUE
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
            WHERE quarter = '{LQ}' AND COALESCE(rollup_name, inst_parent_name) ILIKE ? AND is_latest = TRUE
            """, [f'%{manager}%']
        ).fetchone()

        qoq = con.execute("""
            SELECT quarter, COUNT(DISTINCT ticker) as positions,
                   SUM(market_value_usd) as total_value
            FROM holdings_v2 WHERE COALESCE(rollup_name, inst_parent_name) ILIKE ? AND is_latest = TRUE
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
        return clean_for_json(result)
    except Exception as e:
        log.error("manager_profile error: %s", e)
        return JSONResponse(status_code=500, content={'error': str(e)})
    finally:
        con.close()
