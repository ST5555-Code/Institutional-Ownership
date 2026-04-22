"""Config + meta endpoints (FastAPI).

/api/v1/config/quarters  — quarter list / URLs / report dates (public, no auth)
/api/v1/freshness        — data_freshness snapshot (ARCH-3A)
/api/v1/data-sources     — docs/data_sources.md content (p2-08 Data Source tab)
"""
from __future__ import annotations

import datetime as _dt
import logging
import os

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from api_common import validate_query_params_dep
from app_db import BASE_DIR, get_db
from queries import df_to_records

log = logging.getLogger(__name__)

config_router = APIRouter(
    prefix='/api/v1',
    tags=['config'],
    dependencies=[Depends(validate_query_params_dep)],
)


def _quarter_config_payload() -> dict:
    from config import QUARTERS, QUARTER_URLS, QUARTER_REPORT_DATES, QUARTER_SNAPSHOT_DATES
    return {
        'quarters': QUARTERS,
        'urls': QUARTER_URLS,
        'report_dates': QUARTER_REPORT_DATES,
        'snapshot_dates': QUARTER_SNAPSHOT_DATES,
        'config_file': os.path.join(BASE_DIR, 'scripts', 'config.py'),
    }


@config_router.get('/config/quarters')
def api_config_quarters():
    """Quarter configuration. ARCH-1A rename from legacy /api/admin/quarter_config
    (removed 2026-04-13 with the vanilla-JS retirement). Public — no auth,
    loaded by React on every page."""
    return _quarter_config_payload()


@config_router.get('/freshness')
def api_freshness():
    """Data freshness snapshot (ARCH-3A Batch 3-A).

    Returns one row per precomputed table: {table_name, last_computed_at,
    row_count}. Returns `{"data": []}` if the table is missing
    (pre-migration DB).
    """
    try:
        con = get_db()
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={'error': f'Database unavailable: {e}'},
        )
    try:
        df = con.execute("""
            SELECT table_name, last_computed_at, row_count
            FROM data_freshness
            ORDER BY table_name
        """).fetchdf()
    except Exception as e:
        log.warning("[api_freshness] data_freshness unavailable: %s", e)
        return {'data': []}
    return {'data': df_to_records(df)}


@config_router.get('/data-sources')
def api_data_sources():
    """Serve docs/data_sources.md as markdown string for the Data Source tab.

    Design doc: admin_refresh_system_design.md §9 + §12 phase 12 (p2-08).
    File is small (~13KB) — read from disk on each request; no caching.
    """
    path = os.path.join(BASE_DIR, 'docs', 'data_sources.md')
    if not os.path.isfile(path):
        return JSONResponse(
            status_code=404,
            content={'error': 'data_sources.md not found'},
        )
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    last_modified = _dt.datetime.fromtimestamp(
        os.path.getmtime(path), tz=_dt.timezone.utc
    ).isoformat()
    return {'content': content, 'last_modified': last_modified}
