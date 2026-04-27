"""Fund-lookup endpoints (FastAPI).

Routes:
  /api/v1/fund_portfolio_managers
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from api_common import (
    LQ,
    validate_query_params_dep,
    validate_ticker_current,
)
from app_db import get_db
from queries import df_to_records

fund_router = APIRouter(
    prefix='/api/v1',
    tags=['fund'],
    dependencies=[Depends(validate_query_params_dep)],
)


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
        validate_ticker_current(con, ticker)
        df = con.execute(
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
            """, [ticker]  # nosec B608
        ).fetchdf()
        return df_to_records(df)
    finally:
        con.close()
