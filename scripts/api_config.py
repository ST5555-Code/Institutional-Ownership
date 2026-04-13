"""Config + meta endpoints.

/api/v1/config/quarters  — quarter list / URLs / report dates (public, no auth)
/api/v1/freshness        — data_freshness snapshot (ARCH-3A)
"""
from __future__ import annotations

import logging
import os

from flask import Blueprint, current_app, jsonify

from app_db import BASE_DIR, get_db
from queries import df_to_records

log = logging.getLogger(__name__)

config_bp = Blueprint('api_config', __name__, url_prefix='/api/v1')


def _quarter_config_payload():
    from config import QUARTERS, QUARTER_URLS, QUARTER_REPORT_DATES, QUARTER_SNAPSHOT_DATES
    return jsonify({
        'quarters': QUARTERS,
        'urls': QUARTER_URLS,
        'report_dates': QUARTER_REPORT_DATES,
        'snapshot_dates': QUARTER_SNAPSHOT_DATES,
        'config_file': os.path.join(BASE_DIR, 'scripts', 'config.py'),
    })


@config_bp.route('/config/quarters')
def api_config_quarters():
    """Quarter configuration. ARCH-1A rename from legacy /api/admin/quarter_config
    (removed 2026-04-13 with the vanilla-JS retirement). Public — no auth,
    loaded by React on every page."""
    return _quarter_config_payload()


@config_bp.route('/freshness')
def api_freshness():
    """Data freshness snapshot (ARCH-3A Batch 3-A).

    Returns one row per precomputed table: {table_name, last_computed_at,
    row_count}. Pipeline scripts write to `data_freshness` after each
    successful rebuild; the React footer consumes this to surface staleness
    per ARCHITECTURE_REVIEW.md Batch 3-A SLA table.

    Returns `{"data": []}` if the table is missing (pre-migration DB).
    """
    try:
        con = get_db()
    except Exception as e:
        return jsonify({'error': f'Database unavailable: {e}'}), 503
    try:
        df = con.execute("""
            SELECT table_name, last_computed_at, row_count
            FROM data_freshness
            ORDER BY table_name
        """).fetchdf()
    except Exception as e:
        current_app.logger.warning("[api_freshness] data_freshness unavailable: %s", e)
        return jsonify({'data': []})
    return jsonify({'data': df_to_records(df)})
