"""Fund-lookup endpoints (FastAPI).

Routes:
  /api/v1/fund_rollup_context
  /api/v1/fund_portfolio_managers
  /api/v1/fund_behavioral_profile
  /api/v1/nport_shorts
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from api_common import LQ, validate_query_params_dep
from app_db import get_db
from queries import clean_for_json, df_to_records

fund_router = APIRouter(
    prefix='/api/v1',
    tags=['fund'],
    dependencies=[Depends(validate_query_params_dep)],
)


@fund_router.get('/fund_rollup_context')
def api_fund_rollup_context(cik: str = '', series_id: str = ''):
    """Return economic and decision-maker rollup names for a given CIK or series_id.
    Used by L4 Fund Portfolio tab to show rollup context panel above holdings table.
    """
    cik = (cik or '').strip()
    series_id = (series_id or '').strip()
    if not cik and not series_id:
        return JSONResponse(status_code=400, content={'error': 'Missing cik or series_id parameter'})
    try:
        con = get_db()
    except Exception as e:
        return JSONResponse(status_code=503, content={'error': f'Database unavailable: {e}'})
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
            return JSONResponse(
                status_code=404,
                content={'error': 'Entity not found', 'cik': cik, 'series_id': series_id},
            )

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

        return {
            'entity_id': entity_id,
            'economic_sponsor': ec_name,
            'decision_maker': dm_name,
            'same': ec_name == dm_name,
        }
    finally:
        con.close()


@fund_router.get('/fund_portfolio_managers')
def api_fund_portfolio_managers(ticker: str = ''):
    ticker = (ticker or '').upper().strip()
    if not ticker:
        return JSONResponse(status_code=400, content={'error': 'Missing ticker parameter'})
    try:
        con = get_db()
    except Exception as e:
        return JSONResponse(status_code=503, content={'error': f'Database unavailable: {e}'})
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
              AND is_latest = TRUE
            GROUP BY cik, fund_name
            ORDER BY position_value DESC NULLS LAST
            LIMIT 50
            """, [ticker]
        ).fetchdf()
        return df_to_records(df)
    finally:
        con.close()


@fund_router.get('/fund_behavioral_profile')
def api_fund_behavioral_profile(lei: str = '', series_id: str = ''):
    """Behavioral profile for a fund by LEI or series_id — historical positions."""
    lei = (lei or '').strip()
    series_id = (series_id or '').strip()
    if not lei and not series_id:
        return JSONResponse(status_code=400, content={'error': 'Missing lei or series_id parameter'})

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
            FROM fund_holdings_v2 WHERE {where} AND is_latest = TRUE
            GROUP BY fund_name, series_id, lei, family_name
            LIMIT 1
            """, [param]
        ).fetchone()
        if not fund_info:
            return JSONResponse(status_code=404, content={'error': 'Fund not found'})

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
            WHERE {where} AND pct_of_nav IS NOT NULL AND pct_of_nav > 0 AND is_latest = TRUE
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
              AND fh.is_latest = TRUE
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
            WHERE {where} AND quarter = '{LQ}' AND is_latest = TRUE
            ORDER BY market_value_usd DESC NULLS LAST
            LIMIT 10
            """, [param]
        ).fetchdf()

        return clean_for_json({
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
        })
    finally:
        con.close()


@fund_router.get('/nport_shorts')
def api_nport_shorts(ticker: str = ''):
    """N-PORT negative balance positions — fund short positions from filings."""
    ticker = (ticker or '').upper().strip()
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
              AND fh.is_latest = TRUE
            ORDER BY fh.market_value_usd ASC
            LIMIT 200
            """, params
        ).fetchdf()
        return df_to_records(df)
    finally:
        con.close()
