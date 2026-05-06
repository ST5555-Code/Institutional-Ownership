"""Market-wide analytics endpoints (FastAPI).

Routes:
  /api/v1/sector_flows
  /api/v1/sector_flow_movers
  /api/v1/short_analysis
  /api/v1/crowding
  /api/v1/smart_money
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from api_common import (
    LQ,
    get_rollup_type,
    validate_query_params_dep,
    validate_ticker_current,
)
from app_db import get_db, has_table
from queries import clean_for_json, df_to_records, short_interest_analysis
from queries.common import top_parent_canonical_name_sql

log = logging.getLogger(__name__)

market_router = APIRouter(
    prefix='/api/v1',
    tags=['market'],
    dependencies=[Depends(validate_query_params_dep)],
)


@market_router.get('/sector_flows')
def api_sector_flows(request: Request):
    """Multi-quarter institutional money flows by GICS sector."""
    try:
        from queries import get_sector_flows
        active_only = request.query_params.get('active_only', '0') == '1'
        level = (request.query_params.get('level') or 'parent').strip()
        return get_sector_flows(active_only=active_only, level=level)
    except Exception as e:
        log.error("sector_flows error: %s", e)
        return JSONResponse(status_code=500, content={'error': str(e)})


@market_router.get('/sector_summary')
def api_sector_summary():
    """Market-wide totals for the latest quarter (KPI row)."""
    try:
        from queries import get_sector_summary
        return get_sector_summary()
    except Exception as e:
        log.error("sector_summary error: %s", e)
        return JSONResponse(status_code=500, content={'error': str(e)})


@market_router.get('/fund_quarter_completeness')
def api_fund_quarter_completeness():
    """Per-quarter monthly filing completeness for fund_holdings_v2."""
    try:
        from queries import get_fund_quarter_completeness
        return get_fund_quarter_completeness()
    except Exception as e:
        log.error("fund_quarter_completeness error: %s", e)
        return JSONResponse(status_code=500, content={'error': str(e)})


@market_router.get('/sector_monthly_flows')
def api_sector_monthly_flows(request: Request):
    """Monthly net active flows for one (sector, quarter) at fund level."""
    try:
        from queries import get_sector_monthly_flows
        sector = (request.query_params.get('sector') or '').strip()
        quarter = (request.query_params.get('quarter') or '').strip()
        if not sector or not quarter:
            return JSONResponse(status_code=400, content={'error': 'Missing required params: sector, quarter'})
        return get_sector_monthly_flows(sector, quarter)
    except Exception as e:
        log.error("sector_monthly_flows error: %s", e)
        return JSONResponse(status_code=500, content={'error': str(e)})


@market_router.get('/sector_flow_movers')
def api_sector_flow_movers(request: Request):
    """Top buyers/sellers for one sector in one quarter transition."""
    try:
        from queries import get_sector_flow_movers
        q_from = (request.query_params.get('from') or '').strip()
        q_to = (request.query_params.get('to') or '').strip()
        sector = (request.query_params.get('sector') or '').strip()
        active_only = request.query_params.get('active_only', '0') == '1'
        level = (request.query_params.get('level') or 'parent').strip()
        if not q_from or not q_to or not sector:
            return JSONResponse(status_code=400, content={'error': 'Missing required params: from, to, sector'})
        rt = get_rollup_type(request)
        return get_sector_flow_movers(q_from, q_to, sector,
                                      active_only=active_only, level=level,
                                      rollup_type=rt)
    except Exception as e:
        log.error("sector_flow_movers error: %s", e)
        return JSONResponse(status_code=500, content={'error': str(e)})


@market_router.get('/sector_flow_mover_detail')
def api_sector_flow_mover_detail(request: Request):
    """Top 5 individual ticker moves making up one institution's net flow
    inside a sector for one quarter transition. Drill-down for the
    Sector Rotation movers panel.
    """
    try:
        from queries import get_sector_flow_mover_detail
        q_from = (request.query_params.get('from') or '').strip()
        q_to = (request.query_params.get('to') or '').strip()
        sector = (request.query_params.get('sector') or '').strip()
        institution = (request.query_params.get('institution') or '').strip()
        active_only = request.query_params.get('active_only', '0') == '1'
        level = (request.query_params.get('level') or 'parent').strip()
        if not q_from or not q_to or not sector or not institution:
            return JSONResponse(status_code=400, content={'error': 'Missing required params: from, to, sector, institution'})
        rt = get_rollup_type(request)
        return get_sector_flow_mover_detail(q_from, q_to, sector, institution,
                                            active_only=active_only, level=level,
                                            rollup_type=rt)
    except Exception as e:
        log.error("sector_flow_mover_detail error: %s", e)
        return JSONResponse(status_code=500, content={'error': str(e)})


@market_router.get('/short_analysis')
def api_short_analysis(request: Request):
    """Short Interest Analysis — N-PORT shorts, FINRA volume, long/short cross-ref."""
    ticker = (request.query_params.get('ticker') or '').upper().strip()
    if not ticker:
        return JSONResponse(status_code=400, content={'error': 'Missing ticker parameter'})
    con = get_db()
    try:
        validate_ticker_current(con, ticker)
    finally:
        con.close()
    try:
        rt = get_rollup_type(request)
        return short_interest_analysis(ticker, rollup_type=rt)
    except Exception as e:
        return JSONResponse(status_code=500, content={'error': str(e)})


@market_router.get('/short_position_pct')
def api_short_position_pct(request: Request):
    """Quarterly fund-level short positions as % of shares outstanding,
    with sector and industry averages for overlay."""
    ticker = (request.query_params.get('ticker') or '').upper().strip()
    if not ticker:
        return JSONResponse(status_code=400, content={'error': 'Missing ticker parameter'})
    con = get_db()
    try:
        validate_ticker_current(con, ticker)
    finally:
        con.close()
    try:
        from queries import get_short_position_pct
        return get_short_position_pct(ticker)
    except Exception as e:
        log.error("short_position_pct error: %s", e)
        return JSONResponse(status_code=500, content={'error': str(e)})


@market_router.get('/short_volume_comparison')
def api_short_volume_comparison(request: Request):
    """Daily FINRA short volume % for a ticker plus sector and industry medians."""
    ticker = (request.query_params.get('ticker') or '').upper().strip()
    if not ticker:
        return JSONResponse(status_code=400, content={'error': 'Missing ticker parameter'})
    con = get_db()
    try:
        validate_ticker_current(con, ticker)
    finally:
        con.close()
    try:
        from queries import get_short_volume_comparison
        return get_short_volume_comparison(ticker)
    except Exception as e:
        log.error("short_volume_comparison error: %s", e)
        return JSONResponse(status_code=500, content={'error': str(e)})


@market_router.get('/crowding')
def api_crowding(ticker: str = ''):
    """Crowding analysis: institutional concentration + short interest overlay."""
    ticker = (ticker or '').upper().strip()
    if not ticker:
        return JSONResponse(status_code=400, content={'error': 'Missing ticker parameter'})
    con = get_db()
    try:
        validate_ticker_current(con, ticker)
        tpn = top_parent_canonical_name_sql('h')
        holders = con.execute(
            f"""
            SELECT {tpn} as holder,
                   h.manager_type, SUM(h.pct_of_so) as pct_so,
                   SUM(h.market_value_live) as value
            FROM holdings_v2 h WHERE h.ticker = ? AND h.quarter = '{LQ}' AND h.is_latest = TRUE
            GROUP BY holder, h.manager_type
            ORDER BY pct_so DESC NULLS LAST LIMIT 20
            """, [ticker]  # nosec B608
        ).fetchdf()
        result = {'holders': df_to_records(holders)}
        if has_table('short_interest'):
            si = con.execute("""
                SELECT report_date, short_volume, total_volume, short_pct
                FROM short_interest WHERE ticker = ?
                ORDER BY report_date DESC LIMIT 20
            """, [ticker]).fetchdf()
            result['short_history'] = df_to_records(si)
        return clean_for_json(result)
    finally:
        con.close()


@market_router.get('/peer_tickers')
def api_peer_tickers(request: Request):
    """Return tickers sharing the same sector / industry as the given ticker.

    Used by the Cross-Ownership tab to dynamically populate peer-group
    options based on market_data classifications.
    """
    ticker = (request.query_params.get('ticker') or '').upper().strip()
    if not ticker:
        return JSONResponse(status_code=400, content={'error': 'Missing ticker parameter'})
    con = get_db()
    try:
        if not has_table('market_data'):
            return {'ticker': ticker, 'sector': None, 'industry': None,
                    'sector_peers': [], 'industry_peers': []}
        row = con.execute(
            "SELECT sector, industry FROM market_data WHERE ticker = ?",
            [ticker],
        ).fetchone()
        if not row:
            return {'ticker': ticker, 'sector': None, 'industry': None,
                    'sector_peers': [], 'industry_peers': []}
        sector, industry = row[0], row[1]
        sector_peers: list[str] = []
        industry_peers: list[str] = []
        if sector:
            df = con.execute(
                "SELECT ticker FROM market_data WHERE sector = ? AND ticker != ? "
                "ORDER BY ticker",
                [sector, ticker],
            ).fetchdf()
            sector_peers = [t for t in df['ticker'].tolist() if t]
        if industry:
            df = con.execute(
                "SELECT ticker FROM market_data WHERE industry = ? AND ticker != ? "
                "ORDER BY ticker",
                [industry, ticker],
            ).fetchdf()
            industry_peers = [t for t in df['ticker'].tolist() if t]
        return {
            'ticker': ticker,
            'sector': sector,
            'industry': industry,
            'sector_peers': sector_peers,
            'industry_peers': industry_peers,
        }
    finally:
        con.close()


@market_router.get('/smart_money')
def api_smart_money(ticker: str = ''):
    """Smart Money: net exposure view — long 13F vs short FINRA per manager type."""
    ticker = (ticker or '').upper().strip()
    if not ticker:
        return JSONResponse(status_code=400, content={'error': 'Missing ticker parameter'})
    con = get_db()
    try:
        validate_ticker_current(con, ticker)
        longs = con.execute(
            f"""
            SELECT manager_type, COUNT(DISTINCT cik) as holders,
                   SUM(shares) as long_shares, SUM(market_value_live) as long_value
            FROM holdings_v2 WHERE ticker = ? AND quarter = '{LQ}' AND is_latest = TRUE
            GROUP BY manager_type ORDER BY long_value DESC NULLS LAST
            """, [ticker]  # nosec B608
        ).fetchdf()
        result = {'long_by_type': df_to_records(longs)}
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
        if has_table('fund_holdings_v2'):
            nport_shorts = con.execute("""
                SELECT fund_name, shares_or_principal as shares_short,
                       market_value_usd as short_value, quarter
                FROM fund_holdings_v2
                WHERE ticker = ? AND shares_or_principal < 0
                  AND asset_category IN ('EC', 'EP')
                  AND is_latest = TRUE
                ORDER BY market_value_usd ASC LIMIT 10
            """, [ticker]).fetchdf()
            result['nport_shorts'] = df_to_records(nport_shorts)
        return clean_for_json(result)
    finally:
        con.close()


