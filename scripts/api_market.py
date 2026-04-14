"""Market-wide analytics endpoints (FastAPI).

Routes:
  /api/v1/sector_flows
  /api/v1/sector_flow_movers
  /api/v1/sector_flow_detail
  /api/v1/short_analysis
  /api/v1/short_long
  /api/v1/short_volume
  /api/v1/crowding
  /api/v1/smart_money
  /api/v1/heatmap
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from api_common import LQ, get_rollup_type, validate_query_params_dep
from app_db import get_db, has_table
from queries import clean_for_json, df_to_records, short_interest_analysis

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


@market_router.get('/sector_flow_detail')
def api_sector_flow_detail(request: Request):
    """Full cross-quarter detail for one sector: inflow/outflow/net + top movers."""
    try:
        from queries import get_sector_flow_detail
        sector = (request.query_params.get('sector') or '').strip()
        active_only = request.query_params.get('active_only', '0') == '1'
        level = (request.query_params.get('level') or 'parent').strip()
        if not sector:
            return JSONResponse(status_code=400, content={'error': 'Missing sector param'})
        rank_by = (request.query_params.get('rank_by') or 'total').strip()
        rt = get_rollup_type(request)
        return get_sector_flow_detail(
            sector, active_only=active_only, level=level, rank_by=rank_by,
            rollup_type=rt)
    except Exception as e:
        log.error("sector_flow_detail error: %s", e)
        return JSONResponse(status_code=500, content={'error': str(e)})


@market_router.get('/short_analysis')
def api_short_analysis(request: Request):
    """Short Interest Analysis — N-PORT shorts, FINRA volume, long/short cross-ref."""
    ticker = (request.query_params.get('ticker') or '').upper().strip()
    if not ticker:
        return JSONResponse(status_code=400, content={'error': 'Missing ticker parameter'})
    try:
        rt = get_rollup_type(request)
        return short_interest_analysis(ticker, rollup_type=rt)
    except Exception as e:
        return JSONResponse(status_code=500, content={'error': str(e)})


@market_router.get('/short_long')
def api_short_long(request: Request):
    """Short vs Long comparison: managers long via 13F and short via N-PORT."""
    ticker = (request.query_params.get('ticker') or '').upper().strip()
    if not ticker:
        return JSONResponse(status_code=400, content={'error': 'Missing ticker parameter'})
    try:
        from queries import get_short_long_comparison
        rt = get_rollup_type(request)
        return get_short_long_comparison(ticker, rollup_type=rt)
    except Exception as e:
        log.error("short_long error for %s: %s", ticker, e)
        return JSONResponse(status_code=500, content={'error': str(e)})


@market_router.get('/short_volume')
def api_short_volume(ticker: str = ''):
    """FINRA daily short sale volume for a ticker."""
    ticker = (ticker or '').upper().strip()
    if not ticker:
        return JSONResponse(status_code=400, content={'error': 'Missing ticker parameter'})
    con = get_db()
    try:
        if not has_table('short_interest'):
            return JSONResponse(
                status_code=404,
                content={'error': 'short_interest table not loaded — run fetch_finra_short.py'},
            )
        df = con.execute("""
            SELECT report_date, short_volume, total_volume, short_pct
            FROM short_interest
            WHERE ticker = ?
            ORDER BY report_date DESC
            LIMIT 60
        """, [ticker]).fetchdf()
        return df_to_records(df)
    finally:
        con.close()


@market_router.get('/crowding')
def api_crowding(ticker: str = ''):
    """Crowding analysis: institutional concentration + short interest overlay."""
    ticker = (ticker or '').upper().strip()
    if not ticker:
        return JSONResponse(status_code=400, content={'error': 'Missing ticker parameter'})
    con = get_db()
    try:
        holders = con.execute(
            f""  # nosec B608
            f"""
            SELECT COALESCE(rollup_name, inst_parent_name, manager_name) as holder,
                   manager_type, SUM(pct_of_float) as pct_float,
                   SUM(market_value_live) as value
            FROM holdings_v2 WHERE ticker = ? AND quarter = '{LQ}'
            GROUP BY holder, manager_type
            ORDER BY pct_float DESC NULLS LAST LIMIT 20
            """, [ticker]
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


@market_router.get('/smart_money')
def api_smart_money(ticker: str = ''):
    """Smart Money: net exposure view — long 13F vs short FINRA per manager type."""
    ticker = (ticker or '').upper().strip()
    if not ticker:
        return JSONResponse(status_code=400, content={'error': 'Missing ticker parameter'})
    con = get_db()
    try:
        longs = con.execute(
            f""  # nosec B608
            f"""
            SELECT manager_type, COUNT(DISTINCT cik) as holders,
                   SUM(shares) as long_shares, SUM(market_value_live) as long_value
            FROM holdings_v2 WHERE ticker = ? AND quarter = '{LQ}'
            GROUP BY manager_type ORDER BY long_value DESC NULLS LAST
            """, [ticker]
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
                ORDER BY market_value_usd ASC LIMIT 10
            """, [ticker]).fetchdf()
            result['nport_shorts'] = df_to_records(nport_shorts)
        return clean_for_json(result)
    finally:
        con.close()


@market_router.get('/heatmap')
def api_heatmap(request: Request):
    """Ownership concentration heatmap: top managers × tickers by pct_of_float."""
    ticker = (request.query_params.get('ticker') or '').upper().strip()
    peers = (request.query_params.get('peers') or '').upper().strip()
    con = get_db()
    try:
        tickers = [ticker] if ticker else []
        if peers:
            tickers += [t.strip() for t in peers.split(',') if t.strip()]
        if not tickers:
            top = con.execute(
                f""  # nosec B608
                f"""
                SELECT ticker, SUM(market_value_usd) as val
                FROM holdings_v2 WHERE quarter = '{LQ}' AND ticker IS NOT NULL
                GROUP BY ticker ORDER BY val DESC LIMIT 10
                """
            ).fetchall()
            tickers = [r[0] for r in top]

        ticker_ph = ','.join(['?'] * len(tickers))
        managers = con.execute(
            f""  # nosec B608
            f"""
            SELECT COALESCE(rollup_name, inst_parent_name) as inst_parent_name, SUM(market_value_usd) as total_val
            FROM holdings_v2
            WHERE quarter = '{LQ}' AND ticker IN ({ticker_ph})
              AND COALESCE(rollup_name, inst_parent_name) IS NOT NULL
            GROUP BY COALESCE(rollup_name, inst_parent_name)
            ORDER BY total_val DESC LIMIT 15
            """, tickers
        ).fetchall()
        manager_names = [r[0] for r in managers]

        if not manager_names:
            return {'tickers': tickers, 'managers': [], 'cells': []}

        mgr_ph = ','.join(['?'] * len(manager_names))
        cells = con.execute(
            f""  # nosec B608
            f"""
            SELECT COALESCE(rollup_name, inst_parent_name) as manager, ticker,
                   SUM(pct_of_float) as pct_float,
                   SUM(shares) as shares,
                   SUM(market_value_usd) as value
            FROM holdings_v2
            WHERE quarter = '{LQ}'
              AND ticker IN ({ticker_ph})
              AND COALESCE(rollup_name, inst_parent_name) IN ({mgr_ph})
            GROUP BY COALESCE(rollup_name, inst_parent_name), ticker
            """, tickers + manager_names
        ).fetchdf()

        return clean_for_json({
            'tickers': tickers,
            'managers': manager_names,
            'cells': df_to_records(cells),
        })
    except Exception as e:
        log.error("heatmap error: %s", e)
        return JSONResponse(status_code=500, content={'error': str(e)})
    finally:
        con.close()
