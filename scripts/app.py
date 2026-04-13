"""Flask web application entry point for 13F institutional ownership research.

Phase 4 Batch 4-A (2026-04-13) split this module into domain Blueprints.
The pre-split `app_legacy.py` snapshot was deleted once the split proved
stable (see COMPLETED section of ROADMAP for dates).

Layout:
  - app_db.py               DB helpers (get_db, has_table, resolve_db_path, ...)
  - api_common.py           shared helpers (respond, _get_rollup_type, regexes,
                            validate_query_params, _RT_AWARE_QUERIES, QUERY_FUNCTIONS)
  - api_config.py           /config/quarters, /freshness
  - api_register.py         /tickers, /summary, /query<N>, /export/query<N>,
                            /amendments, /manager_profile, /fund_* , /nport_shorts
  - api_flows.py            /flow_analysis, /ownership_trend_summary,
                            /cohort_analysis, /holder_momentum, /peer_rotation*,
                            /portfolio_context
  - api_entities.py         /entity_search, /entity_children, /entity_graph,
                            /entity_resolve, /entity_market_summary
  - api_market.py           /sector_flows*, /short_*, /crowding, /smart_money,
                            /heatmap
  - api_cross.py            /cross_ownership*, /two_company_*, /peer_groups*
  - admin_bp.py             /api/admin/* (unchanged)

See docs/endpoint_classification.md for the full route classification table.
"""
from __future__ import annotations

import argparse
import os

from flask import Flask, render_template, send_file

from admin_bp import admin_bp, init_admin_bp
from api_common import validate_query_params
from api_config import config_bp
from api_cross import cross_bp
from api_entities import entities_bp
from api_flows import flows_bp
from api_fund import fund_bp
from api_market import market_bp
from api_register import register_bp
from app_db import DB_PATH, BASE_DIR, get_db, has_table, init_db_path
import queries

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, 'web', 'templates'),
    static_folder=os.path.join(BASE_DIR, 'web', 'react-app', 'dist', 'assets'),
    static_url_path='/assets',
)

# INF12: app binds 0.0.0.0 for Render. All mutating/admin endpoints live on
# admin_bp (scripts/admin_bp.py) and require ENABLE_ADMIN=1 + ADMIN_TOKEN in
# env, plus an X-Admin-Token header on every request. Without both env vars
# set, admin_bp returns 503 "Admin disabled".

# Wire DB helpers into queries + admin_bp.
queries._setup(get_db, has_table)  # pylint: disable=protected-access
init_admin_bp(get_db, has_table)

# Input guards (ARCH-1A) — validates /api/v1/* shape before handlers see it.
app.before_request(validate_query_params)

# Register every Blueprint. admin_bp first (its own before_request for token
# auth must be registered before shared hooks fire on /api/admin/* paths).
app.register_blueprint(admin_bp)
for bp in (config_bp, register_bp, fund_bp, flows_bp, entities_bp, market_bp, cross_bp):
    app.register_blueprint(bp)


# ── Top-level pages ───────────────────────────────────────────────────────


@app.route('/')
def index():
    return send_file(os.path.join(
        BASE_DIR, 'web', 'react-app', 'dist', 'index.html'
    ))


@app.route('/admin')
def admin_page():
    return render_template('admin.html')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='13F Ownership Research Web App')
    parser.add_argument('--port', type=int, default=8001, help='Port to run on (default: 8001)')
    args = parser.parse_args()

    port = int(os.environ.get('PORT', args.port))

    init_db_path()

    from app_db import _active_db_path  # pylint: disable=protected-access
    print()
    print('  13F Ownership Research')
    print(f'  Database: {_active_db_path}')
    if _active_db_path != DB_PATH:
        print('  (main DB locked — serving from snapshot)')
    print(f'  Running at: http://localhost:{port}')
    print()

    app.run(host='0.0.0.0', port=port, debug=False)  # nosec B104 — dev/Render server bind
