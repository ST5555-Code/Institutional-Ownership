"""FastAPI web application entry point for 13F institutional ownership research.

Phase 4+ Batch 4-C (2026-04-13) swapped Flask for FastAPI. The pre-FastAPI
Flask entry was deleted once this module proved stable — see ROADMAP.

Layout:
  - app_db.py               DB helpers (get_db, has_table, init_db_path, ...)
  - api_common.py           respond helpers (envelope_success/envelope_error),
                            validate_query_params_dep, regex constants,
                            _RT_AWARE_QUERIES, QUERY_FUNCTIONS
  - api_config.py           config_router
  - api_register.py         register_router
  - api_fund.py             fund_router
  - api_flows.py            flows_router
  - api_entities.py         entities_router
  - api_market.py           market_router
  - api_cross.py            cross_router
  - admin_bp.py             admin_router (retains old filename for git history)

See docs/endpoint_classification.md for the full route classification table.
"""
from __future__ import annotations

import argparse
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from admin_bp import admin_router, init_admin_bp
from api_config import config_router
from api_cross import cross_router
from api_entities import entities_router
from api_flows import flows_router
from api_fund import fund_router
from api_market import market_router
from api_register import register_router
from app_db import DB_PATH, BASE_DIR, get_db, has_table, init_db_path
import queries

@asynccontextmanager
async def _lifespan(_app: FastAPI):
    """Startup: resolve DB path + warm the switchback monitor."""
    init_db_path()
    yield


app = FastAPI(
    title='13F Ownership Research',
    version='1.0',
    docs_url='/docs',
    redoc_url='/redoc',
    lifespan=_lifespan,
)

# Wire DB helpers into queries + admin router.
queries._setup(get_db, has_table)  # pylint: disable=protected-access
init_admin_bp(get_db, has_table)

# Mount the React build static assets (matches Flask's static_url_path='/assets').
# Existence check keeps the app importable when dist/ hasn't been built yet
# (e.g. fresh clone, smoke tests on a CI runner without `npm run build`).
_dist_assets = os.path.join(BASE_DIR, 'web', 'react-app', 'dist', 'assets')
if os.path.isdir(_dist_assets):
    app.mount('/assets', StaticFiles(directory=_dist_assets), name='assets')

# Jinja for /admin page (admin_bp API endpoints use pure JSON).
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, 'web', 'templates'))

# Register domain routers — admin first (its auth dependency is per-router).
app.include_router(admin_router)
for router in (config_router, register_router, fund_router, flows_router,
               entities_router, market_router, cross_router):
    app.include_router(router)


# ── Top-level pages ───────────────────────────────────────────────────────


@app.get('/', include_in_schema=False)
def index():
    return FileResponse(os.path.join(
        BASE_DIR, 'web', 'react-app', 'dist', 'index.html'
    ))


@app.get('/admin', include_in_schema=False)
def admin_page(request: Request):
    return templates.TemplateResponse('admin.html', {'request': request})


if __name__ == '__main__':
    import uvicorn

    parser = argparse.ArgumentParser(description='13F Ownership Research Web App')
    parser.add_argument('--port', type=int, default=8001, help='Port (default: 8001)')
    args = parser.parse_args()

    port = int(os.environ.get('PORT', args.port))

    # Resolve DB path eagerly so the startup banner shows the active path.
    # FastAPI's @on_event('startup') will not have run yet at this point —
    # we call init_db_path() explicitly so both this banner and the
    # subsequent server import see the same resolved path.
    init_db_path()
    from app_db import _active_db_path  # pylint: disable=protected-access

    print()
    print('  13F Ownership Research')
    print(f'  Database: {_active_db_path}')
    if _active_db_path != DB_PATH:
        print('  (main DB locked — serving from snapshot)')
    print(f'  Running at: http://localhost:{port}')
    print('  API docs:   http://localhost:{port}/docs'.format(port=port))
    print()

    uvicorn.run(
        'app:app',
        host='0.0.0.0',  # nosec B104 — dev/Render server bind
        port=port,
        log_level='info',
        reload=False,
    )
