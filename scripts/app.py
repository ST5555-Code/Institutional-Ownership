"""
Flask web application for 13F institutional ownership research.
Replaces Jupyter notebook for day-to-day browser-based research.
"""

import argparse
import os
import re
import threading as _threading
from datetime import datetime

import duckdb
from flask import Flask, jsonify, request, send_file
from pydantic import ValidationError

from admin_bp import admin_bp, init_admin_bp
from config import LATEST_QUARTER, FIRST_QUARTER, PREV_QUARTER
from export import build_excel
from schemas import (
    iso_now,
    ConvictionEnvelope,
    EntityGraphEnvelope,
    FlowAnalysisEnvelope,
    OwnershipTrendEnvelope,
    RegisterEnvelope,
    TickersEnvelope,
)
import queries
from queries import (
    clean_for_json, df_to_records,
    query1, query2, query3, query4, query5,
    query6, query7, query8, query9, query10,
    query11, query12, query14, query15, query16,
    ownership_trend_summary, cohort_analysis, flow_analysis, holder_momentum,
    short_interest_analysis, portfolio_context,
    get_summary, _cross_ownership_query,
    VALID_ROLLUP_TYPES,
)


# Input-guard regexes — Batch 1-A (ARCH-1A). Ticker regex accepts BRK.B, BF.B,
# ADRs. Spec in ARCHITECTURE_REVIEW.md literally reads `^[A-Z]{1,6}[.A-Z]?$`;
# that pattern only matches one of {trailing dot, trailing letter}, not both,
# and so would reject BRK.B which the spec comment explicitly says it should
# accept. Using the corrected form `^[A-Z]{1,6}(\.[A-Z])?$` to match the
# stated intent. Transitional — Pydantic validation in Batch 4-C (FastAPI)
# replaces these route-layer guards.
_TICKER_RE = re.compile(r'^[A-Z]{1,6}(\.[A-Z])?$')
_QUARTER_RE = re.compile(r'^20\d{2}Q[1-4]$')


def _get_rollup_type(req):
    """Extract rollup_type query parameter, validated against VALID_ROLLUP_TYPES.
    Default: 'economic_control_v1' (fund sponsor / voting view).
    """
    rt = req.args.get('rollup_type', 'economic_control_v1').strip()
    if rt not in VALID_ROLLUP_TYPES:
        rt = 'economic_control_v1'
    return rt

# Quarter constants used in SQL queries — imported from config.py.
# To roll forward: edit ONLY scripts/config.py. These vars propagate everywhere.
LQ = LATEST_QUARTER   # latest quarter for all queries (e.g. '{LQ}')
FQ = FIRST_QUARTER    # first quarter for comparisons (e.g. '{FQ}')
PQ = PREV_QUARTER     # previous quarter (e.g. '{PQ}')

QUERY_FUNCTIONS = {
    1: query1, 2: query2, 3: query3, 4: query4, 5: query5,
    6: query6, 7: query7, 8: query8, 9: query9, 10: query10,
    11: query11, 12: query12, 14: query14, 15: query15,
    16: query16,
}

# Queries that accept rollup_type. Shared by api_query and api_export so the
# Excel export mirrors on-screen semantics (Batch 1-B1 export parity). Keep
# in sync with the signatures in queries.py — every function in this set
# must declare `rollup_type='economic_control_v1'`.
_RT_AWARE_QUERIES = frozenset({1, 2, 3, 5, 12, 14})

QUERY_NAMES = {
    1: 'Register', 2: 'Holder Changes', 3: 'Conviction',
    6: 'Activist', 7: 'Fund Portfolio', 8: 'Cross-Ownership',
    9: 'Sector Rotation', 10: 'New Positions', 11: 'Exits',
    14: 'AUM vs Position', 15: 'DB Statistics',
}

# ---------------------------------------------------------------------------
# Flask app setup
# ---------------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# DB_PATH_OVERRIDE env var swaps in an alternate DB path (Phase 0-B2 smoke
# tests point this at the committed CI fixture). Undefined in normal use.
DB_PATH = os.environ.get('DB_PATH_OVERRIDE') or os.path.join(BASE_DIR, 'data', '13f.duckdb')
DB_SNAPSHOT_PATH = os.path.join(BASE_DIR, 'data', '13f_readonly.duckdb')

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, 'web', 'templates'),
    static_folder=os.path.join(BASE_DIR, 'web', 'react-app', 'dist', 'assets'),
    static_url_path='/assets',
)

# INF12: app binds 0.0.0.0 for Render. All mutating/admin endpoints live on
# admin_bp (scripts/admin_bp.py) and require ENABLE_ADMIN=1 + ADMIN_TOKEN in
# env, plus an X-Admin-Token header on every request. Without both env vars
# set, admin_bp returns 503 "Admin disabled". Blueprint registration happens
# after get_db / has_table are defined below (see end of this module's setup).
# Public quarter config lives at /api/v1/config/quarters on the main app —
# no auth needed, loaded by React on every page load.


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def _resolve_db_path():
    """Return the best available database path.

    Try the main database first (read_only=True). If it is locked by a writer
    (e.g. fetch_nport.py), fall back to a pre-existing snapshot so the web
    app can still serve data while the pipeline runs.

    INF13 (2026-04-10): The hot-path snapshot creation via `shutil.copy2`
    has been removed. A byte-level copy of a live DuckDB file can capture
    torn pages / an inconsistent WAL section — DuckDB uses a single-file
    format where writers append to the WAL portion, so a file-level copy
    taken during concurrent writes is not guaranteed consistent.

    Snapshot creation is now exclusively the job of `scripts/refresh_snapshot.sh`,
    which uses DuckDB's own `COPY FROM DATABASE` command (MVCC-safe, reads
    through a consistent view). `run_pipeline.sh` already calls
    `refresh_snapshot.sh` after every pipeline run, so in steady state a
    valid snapshot always exists. On a fresh deployment with no snapshot
    yet, run `scripts/refresh_snapshot.sh` once manually.
    """
    try:
        con = duckdb.connect(DB_PATH, read_only=True)
        con.close()
        return DB_PATH
    except Exception as e:
        app.logger.warning("[_resolve_db_path] Main DB locked: %s", e)
        if os.path.exists(DB_SNAPSHOT_PATH):
            return DB_SNAPSHOT_PATH
        raise RuntimeError(
            f"Cannot open {DB_PATH} (locked: {e}) and no snapshot found at "
            f"{DB_SNAPSHOT_PATH}. Run `scripts/refresh_snapshot.sh` to create "
            f"one. INF13: the app no longer creates snapshots in the hot path "
            f"because a byte-level copy of a live DuckDB file can capture "
            f"torn pages."
        ) from e


# Resolved once at import/startup; updated if needed
_db_path_lock = _threading.Lock()
_active_db_path = None
_switchback_running = False
_available_tables = set()


def _start_switchback_monitor():
    """Background thread: check every 60s if primary DB is available again."""
    global _switchback_running  # pylint: disable=global-statement
    if _switchback_running:
        return
    _switchback_running = True

    def _monitor():
        global _active_db_path, _switchback_running  # pylint: disable=global-statement
        import time as _time
        while True:
            _time.sleep(60)
            with _db_path_lock:
                if _active_db_path == DB_PATH:
                    _switchback_running = False
                    return
            try:
                con = duckdb.connect(DB_PATH, read_only=True)
                con.close()
                with _db_path_lock:
                    _active_db_path = DB_PATH
                _refresh_table_list()
                app.logger.info("[switchback] Primary DB available — switched back from snapshot")
                _switchback_running = False
                return
            except Exception as e:
                app.logger.debug("Suppressed: %s", e)

    t = _threading.Thread(target=_monitor, daemon=True)
    t.start()


def _refresh_table_list():
    """Cache available table names."""
    global _available_tables  # pylint: disable=global-statement
    try:
        path = _active_db_path or _resolve_db_path()
        con = duckdb.connect(path, read_only=True)
        _available_tables = {t[0] for t in con.execute("SHOW TABLES").fetchall()}
        con.close()
    except Exception as e:
        app.logger.debug("Suppressed: %s", e)


def has_table(name):
    """Check if a table exists (cached, no per-request query)."""
    if not _available_tables:
        _refresh_table_list()
    return name in _available_tables


def _init_db_path():
    """Resolve the database path at startup."""
    global _active_db_path  # pylint: disable=global-statement
    _active_db_path = _resolve_db_path()
    _refresh_table_list()
    if _active_db_path != DB_PATH:
        _start_switchback_monitor()


_conn_local = _threading.local()


def get_db():
    """Get a read-only DuckDB connection. Uses thread-local cache to avoid
    reopening on every request. Caller should NOT close it."""
    global _active_db_path  # pylint: disable=global-statement
    with _db_path_lock:
        if _active_db_path is None:
            _active_db_path = _resolve_db_path()
            _refresh_table_list()
            if _active_db_path != DB_PATH:
                _start_switchback_monitor()
        path = _active_db_path

    # Thread-local connection cache
    cached = getattr(_conn_local, 'con', None)
    cached_path = getattr(_conn_local, 'path', None)
    if cached and cached_path == path:
        try:
            cached.execute("SELECT 1")  # verify alive
            return cached
        except Exception as e:
            app.logger.debug("Error: %s", e)
            # stale — reopen below

    try:
        con = duckdb.connect(path, read_only=True)
        _conn_local.con = con
        _conn_local.path = path
        return con
    except Exception as e:
        app.logger.warning("[get_db] Connection stale, re-resolving: %s", e)
        with _db_path_lock:
            _active_db_path = _resolve_db_path()
            path = _active_db_path
        _refresh_table_list()
        if path != DB_PATH:
            _start_switchback_monitor()
        return duckdb.connect(_active_db_path, read_only=True)


# Initialize queries module with DB access functions
queries._setup(get_db, has_table)  # pylint: disable=protected-access

# INF12: wire DB helpers into admin_bp, then register the Blueprint. Must
# happen after get_db / has_table are defined above.
init_admin_bp(get_db, has_table)
app.register_blueprint(admin_bp)


# ---------------------------------------------------------------------------
# Phase 1-B2 — response envelope helper
# ---------------------------------------------------------------------------
# `respond()` wraps payloads in the `{data, error, meta}` envelope introduced
# by ARCHITECTURE_REVIEW.md Batch 1-B2. Applied opt-in per endpoint during
# the Phase 1-B2 rollout — handlers that have NOT been migrated continue to
# call `jsonify()` directly and return bare payloads.
#
# schema is the per-endpoint Pydantic payload model (e.g. TickersPayload).
# If data is a list/dict, schema validates the envelope[data] shape on the
# way out. A schema failure returns a 500 with the standard error envelope
# rather than silently serving a malformed response.
# ---------------------------------------------------------------------------

def _build_meta() -> dict:
    return {
        "quarter": request.args.get("quarter"),
        "rollup_type": request.args.get("rollup_type"),
        "generated_at": iso_now(),
    }


def respond(data=None, *, schema=None, error=None, status=200):
    """Return a Flask JSON response wrapped in the Phase 1-B2 envelope.

    Args:
        data: payload. Can be list/dict. `None` when `error` is set.
        schema: optional Pydantic type used to validate `{data, meta, error}`
                on the way out. Use parameterized generics like
                `Envelope[list[TickerRow]]`. Skipped if None.
        error: optional ErrorShape-compatible dict or pydantic model.
        status: HTTP status code (default 200; use 4xx/5xx with error).
    """
    err_payload = None
    if error is not None:
        err_payload = error if isinstance(error, dict) else error.model_dump()

    envelope = {"data": data, "error": err_payload, "meta": _build_meta()}

    if schema is not None:
        try:
            schema.model_validate(envelope)
        except ValidationError as e:
            app.logger.error("[respond] envelope schema validation failed: %s", e)
            return jsonify({
                "data": None,
                "error": {
                    "code": "schema_validation_error",
                    "message": "Response failed server-side validation",
                    "detail": {"errors": e.errors()[:5]},
                },
                "meta": _build_meta(),
            }), 500

    return jsonify(envelope), status


# ---------------------------------------------------------------------------
# Input guards (ARCH-1A) — validate shape of ticker / quarter / rollup_type
# before handlers see them. Applies to /api/v1/* public routes only.
# /api/admin/* lives on admin_bp, which runs its own before_request for
# token auth + param validation. Empty/missing params pass through so
# handlers can still enforce required-param presence themselves.
# ---------------------------------------------------------------------------

@app.before_request
def _validate_query_params():
    path = request.path
    if not path.startswith('/api/v1/'):
        return None
    ticker = request.args.get('ticker')
    if ticker:
        if not _TICKER_RE.match(ticker.upper().strip()):
            return jsonify({'error': f'Invalid ticker format: {ticker!r}'}), 400
    quarter = request.args.get('quarter')
    if quarter and not _QUARTER_RE.match(quarter.strip()):
        return jsonify({'error': f'Invalid quarter format: {quarter!r}'}), 400
    rollup = request.args.get('rollup_type')
    if rollup and rollup.strip() not in VALID_ROLLUP_TYPES:
        return jsonify({'error': f'Invalid rollup_type: {rollup!r}'}), 400
    return None


# ---------------------------------------------------------------------------
# Admin page (HTML shell only — API endpoints live on admin_bp)
# ---------------------------------------------------------------------------

@app.route('/admin')
def admin_page():
    from flask import render_template  # pylint: disable=import-outside-toplevel
    return render_template('admin.html')


def _quarter_config_payload():
    from config import QUARTERS, QUARTER_URLS, QUARTER_REPORT_DATES, QUARTER_SNAPSHOT_DATES
    return jsonify({
        'quarters': QUARTERS,
        'urls': QUARTER_URLS,
        'report_dates': QUARTER_REPORT_DATES,
        'snapshot_dates': QUARTER_SNAPSHOT_DATES,
        'config_file': os.path.join(BASE_DIR, 'scripts', 'config.py'),
    })


@app.route('/api/v1/config/quarters')
def api_config_quarters():
    """Quarter configuration (ARCH-1A rename from legacy /api/admin/quarter_config,
    which was removed 2026-04-13 with the vanilla-JS retirement).
    Public endpoint — no auth, loaded by UI on every page."""
    return _quarter_config_payload()


@app.route('/api/v1/freshness')
def api_freshness():
    """Data freshness snapshot (ARCH-3A Batch 3-A).

    Returns one row per precomputed table: {table_name, last_computed_at,
    row_count}. Pipeline scripts write to `data_freshness` after each
    successful rebuild; the React footer consumes this to surface
    staleness per `ARCHITECTURE_REVIEW.md` Batch 3-A SLA table.

    The table exists but is empty until the pipelines wire in their
    write hooks — this endpoint returns `{"data": []}` in that case.
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
        # Table does not exist on this DB (pre-migration fallback).
        app.logger.warning("[api_freshness] data_freshness unavailable: %s", e)
        return jsonify({'data': []})
    return jsonify({'data': df_to_records(df)})


# ---------------------------------------------------------------------------
# Endpoint classification (Phase 1 Batch 1-B1 + vanilla-JS retirement) — freeze artifact
# ---------------------------------------------------------------------------
# Every /api/v1/* route on this app, categorized by:
#   Quarter: latest-only (no `quarter` param, always LATEST_QUARTER) vs
#            quarter-aware (reads `quarter`, validates, passes through).
#   Rollup:  rollup-agnostic vs rollup-aware (reads `rollup_type`).
#
# Phase 4 Blueprint split (Batch 4-A) consumes this table — routes sharing a
# category cluster naturally into the same domain module. Do not change a
# row's category without updating this comment AND the downstream consumer.
#
# /api/admin/* lives on admin_bp (scripts/admin_bp.py), token-auth gated.
# The legacy /api/* public mount was removed 2026-04-13 after the vanilla-JS
# frontend was retired — everything public is now /api/v1/* only.
#
# Path                                Quarter         Rollup
# ----------------------------------- --------------- ----------------
# /api/v1/config/quarters             n/a (config)    n/a
# /api/v1/freshness                   n/a (meta)      n/a  (data_freshness snapshot — ARCH-3A)
# /api/v1/tickers                     latest-only     rollup-agnostic
# /api/v1/summary                     latest-only     rollup-agnostic
# /api/v1/fund_rollup_context         latest-only     rollup-agnostic  (returns BOTH rollup names by design)
# /api/v1/fund_portfolio_managers     latest-only     rollup-agnostic
# /api/v1/fund_behavioral_profile     latest-only     rollup-agnostic
# /api/v1/nport_shorts                latest-only     rollup-agnostic
# /api/v1/short_volume                latest-only     rollup-agnostic
# /api/v1/smart_money                 latest-only     rollup-agnostic
# /api/v1/crowding                    latest-only     rollup-agnostic
# /api/v1/sector_flows                latest-only     rollup-agnostic
# /api/v1/heatmap                     latest-only     rollup-agnostic
# /api/v1/manager_profile             latest-only     rollup-agnostic
# /api/v1/amendments                  latest-only     rollup-agnostic
# /api/v1/peer_groups                 latest-only     rollup-agnostic
# /api/v1/peer_groups/<group_id>      latest-only     rollup-agnostic
# /api/v1/entity_search               latest-only     rollup-agnostic
# /api/v1/entity_resolve              latest-only     rollup-agnostic
# /api/v1/entity_market_summary       latest-only     rollup-agnostic
# /api/v1/short_analysis              latest-only     rollup-aware  (threaded in Batch 1-A)
# /api/v1/short_long                  latest-only     rollup-aware  (threaded in Batch 1-A; 500 pre-existing, BL-9)
# /api/v1/ownership_trend_summary     latest-only     rollup-aware
# /api/v1/cohort_analysis             latest-only     rollup-aware
# /api/v1/holder_momentum             latest-only     rollup-aware
# /api/v1/flow_analysis               latest-only     rollup-aware
# /api/v1/cross_ownership             latest-only     rollup-aware
# /api/v1/cross_ownership_top         latest-only     rollup-aware
# /api/v1/peer_rotation               latest-only     rollup-aware
# /api/v1/peer_rotation_detail        latest-only     rollup-aware
# /api/v1/portfolio_context           latest-only     rollup-aware
# /api/v1/sector_flow_movers          latest-only     rollup-aware
# /api/v1/sector_flow_detail          latest-only     rollup-aware
# /api/v1/entity_children             quarter-aware   rollup-agnostic  (graph layer sits below rollup)
# /api/v1/entity_graph                quarter-aware   rollup-agnostic
# /api/v1/two_company_overlap         quarter-aware   rollup-agnostic
# /api/v1/two_company_subject         quarter-aware   rollup-agnostic
# /api/v1/query<int:qnum>             quarter-aware   rollup-aware  (for qnum in _RT_AWARE_QUERIES = {1,2,3,5,12,14})
# /api/v1/export/query<int:qnum>      quarter-aware   rollup-aware  (mirrors /api/v1/query — fixed Batch 1-B1)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Flask routes
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    return send_file(os.path.join(
        BASE_DIR, 'web', 'react-app', 'dist', 'index.html'
    ))


# SMOKE TEST: always include /api/v1/tickers in post-commit curl checks — it is
# the autocomplete root and a silent 500 here breaks the entire UI ticker search.
@app.route('/api/v1/tickers')
def api_tickers():
    try:
        con = get_db()
    except Exception as e:
        return respond(
            error={'code': 'db_unavailable', 'message': f'Database unavailable: {e}'},
            schema=TickersEnvelope,
            status=503,
        )
    try:
        df = con.execute(
            f""  # nosec B608
            f"""
            SELECT ticker, MODE(issuer_name) as name
            FROM holdings_v2
            WHERE ticker IS NOT NULL AND ticker != '' AND quarter = '{LQ}'
            GROUP BY ticker
            ORDER BY ticker
            """
        ).fetchdf()
        return respond(data=df_to_records(df), schema=TickersEnvelope)
    finally:
        con.close()


@app.route('/api/v1/fund_rollup_context')
def api_fund_rollup_context():
    """Return economic and decision-maker rollup names for a given CIK or series_id.
    Used by L4 Fund Portfolio tab to show rollup context panel above holdings table.
    """
    cik = request.args.get('cik', '').strip()
    series_id = request.args.get('series_id', '').strip()
    if not cik and not series_id:
        return jsonify({'error': 'Missing cik or series_id parameter'}), 400
    try:
        con = get_db()
    except Exception as e:
        return jsonify({'error': f'Database unavailable: {e}'}), 503
    try:
        # Resolve entity_id from cik or series_id
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
            return jsonify({'error': 'Entity not found', 'cik': cik, 'series_id': series_id}), 404

        entity_id = row[0]

        # Get economic_control_v1 rollup
        ec = con.execute("""
            SELECT ea.alias_name FROM entity_rollup_history erh
            LEFT JOIN entity_aliases ea ON erh.rollup_entity_id = ea.entity_id
                AND ea.is_preferred = TRUE AND ea.valid_to = '9999-12-31'
            WHERE erh.entity_id = ? AND erh.rollup_type = 'economic_control_v1'
              AND erh.valid_to = '9999-12-31'
        """, [entity_id]).fetchone()

        # Get decision_maker_v1 rollup
        dm = con.execute("""
            SELECT ea.alias_name FROM entity_rollup_history erh
            LEFT JOIN entity_aliases ea ON erh.rollup_entity_id = ea.entity_id
                AND ea.is_preferred = TRUE AND ea.valid_to = '9999-12-31'
            WHERE erh.entity_id = ? AND erh.rollup_type = 'decision_maker_v1'
              AND erh.valid_to = '9999-12-31'
        """, [entity_id]).fetchone()

        ec_name = ec[0] if ec else None
        dm_name = dm[0] if dm else None

        return jsonify({
            'entity_id': entity_id,
            'economic_sponsor': ec_name,
            'decision_maker': dm_name,
            'same': ec_name == dm_name,
        })
    finally:
        con.close()


@app.route('/api/v1/fund_portfolio_managers')
def api_fund_portfolio_managers():
    ticker = request.args.get('ticker', '').upper().strip()
    if not ticker:
        return jsonify({'error': 'Missing ticker parameter'}), 400
    try:
        con = get_db()
    except Exception as e:
        return jsonify({'error': f'Database unavailable: {e}'}), 503
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
            GROUP BY cik, fund_name
            ORDER BY position_value DESC NULLS LAST
            LIMIT 50
            """, [ticker]
        ).fetchdf()
        return jsonify(df_to_records(df))
    finally:
        con.close()


@app.route('/api/v1/nport_shorts')
def api_nport_shorts():
    """N-PORT negative balance positions — fund short positions from filings."""
    ticker = request.args.get('ticker', '').upper().strip()
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
            ORDER BY fh.market_value_usd ASC
            LIMIT 200
            """, params
        ).fetchdf()
        return jsonify(df_to_records(df))
    finally:
        con.close()


@app.route('/api/v1/short_volume')
def api_short_volume():
    """FINRA daily short sale volume for a ticker."""
    ticker = request.args.get('ticker', '').upper().strip()
    if not ticker:
        return jsonify({'error': 'Missing ticker parameter'}), 400
    con = get_db()
    try:
        if not has_table('short_interest'):
            return jsonify({'error': 'short_interest table not loaded — run fetch_finra_short.py'}), 404
        df = con.execute("""
            SELECT report_date, short_volume, total_volume, short_pct
            FROM short_interest
            WHERE ticker = ?
            ORDER BY report_date DESC
            LIMIT 60
        """, [ticker]).fetchdf()
        return jsonify(df_to_records(df))
    finally:
        con.close()


@app.route('/api/v1/fund_behavioral_profile')
def api_fund_behavioral_profile():
    """Behavioral profile for a fund by LEI or series_id — analyzes historical positions."""
    lei = request.args.get('lei', '').strip()
    series_id = request.args.get('series_id', '').strip()
    if not lei and not series_id:
        return jsonify({'error': 'Missing lei or series_id parameter'}), 400

    con = get_db()
    try:
        # Find matching fund
        if lei:
            where = "lei = ?"
            param = lei
        else:
            where = "series_id = ?"
            param = series_id

        # Fund identity
        fund_info = con.execute(
            f""  # nosec B608
            f"""
            SELECT fund_name, series_id, lei, family_name, COUNT(DISTINCT quarter) as quarters
            FROM fund_holdings_v2 WHERE {where}
            GROUP BY fund_name, series_id, lei, family_name
            LIMIT 1
            """, [param]
        ).fetchone()
        if not fund_info:
            return jsonify({'error': 'Fund not found'}), 404

        fund_name, sid, fund_lei, family, quarters = fund_info

        # Position size distribution (avg % of NAV)
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
            WHERE {where} AND pct_of_nav IS NOT NULL AND pct_of_nav > 0
            """, [param]
        ).fetchone()

        # Sector concentration
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
            GROUP BY s.sector
            ORDER BY sector_value DESC
            LIMIT 10
            """, [param]
        ).fetchdf()

        # Top holdings
        top = con.execute(
            f""  # nosec B608
            f"""
            SELECT ticker, issuer_name, market_value_usd, pct_of_nav, shares_or_principal
            FROM fund_holdings_v2
            WHERE {where} AND quarter = '{LQ}'
            ORDER BY market_value_usd DESC NULLS LAST
            LIMIT 10
            """, [param]
        ).fetchdf()

        return jsonify(clean_for_json({
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
        }))
    finally:
        con.close()


@app.route('/api/v1/ownership_trend_summary')
def api_ownership_trend_summary():
    ticker = request.args.get('ticker', '').upper().strip()
    level = request.args.get('level', 'parent').strip()
    ao = request.args.get('active_only', '').strip() == 'true'
    rt = _get_rollup_type(request)
    if not ticker:
        return respond(
            error={'code': 'missing_param', 'message': 'Missing ticker parameter'},
            schema=OwnershipTrendEnvelope,
            status=400,
        )
    try:
        result = ownership_trend_summary(ticker, level=level, active_only=ao, rollup_type=rt)
        return respond(data=clean_for_json(result), schema=OwnershipTrendEnvelope)
    except Exception as e:
        return respond(
            error={'code': 'internal_error', 'message': str(e)},
            schema=OwnershipTrendEnvelope,
            status=500,
        )


@app.route('/api/v1/cohort_analysis')
def api_cohort_analysis():
    ticker = request.args.get('ticker', '').upper().strip()
    from_q = request.args.get('from', '').strip() or None
    level = request.args.get('level', 'parent').strip()
    active_only = request.args.get('active_only', '').strip() == 'true'
    rt = _get_rollup_type(request)
    if not ticker:
        return jsonify({'error': 'Missing ticker parameter'}), 400
    try:
        result = cohort_analysis(ticker, from_quarter=from_q, level=level, active_only=active_only, rollup_type=rt)
        return jsonify(clean_for_json(result))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/v1/holder_momentum')
def api_holder_momentum():
    ticker = request.args.get('ticker', '').upper().strip()
    level = request.args.get('level', 'parent').strip()
    ao = request.args.get('active_only', '').strip() == 'true'
    rt = _get_rollup_type(request)
    if not ticker:
        return jsonify({'error': 'Missing ticker parameter'}), 400
    try:
        result = holder_momentum(ticker, level=level, active_only=ao, rollup_type=rt)
        return jsonify(clean_for_json(result))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/v1/flow_analysis')
def api_flow_analysis():
    ticker = request.args.get('ticker', '').upper().strip()
    period = request.args.get('period', '1Q').upper().strip()
    peers = request.args.get('peers', '').upper().strip() or None
    level = request.args.get('level', 'parent').strip()
    ao = request.args.get('active_only', '').strip() == 'true'
    rt = _get_rollup_type(request)
    if not ticker:
        return respond(
            error={'code': 'missing_param', 'message': 'Missing ticker parameter'},
            schema=FlowAnalysisEnvelope,
            status=400,
        )
    try:
        result = flow_analysis(ticker, period=period, peers=peers, level=level, active_only=ao, rollup_type=rt)
        return respond(data=clean_for_json(result), schema=FlowAnalysisEnvelope)
    except Exception as e:
        return respond(
            error={'code': 'internal_error', 'message': str(e)},
            schema=FlowAnalysisEnvelope,
            status=500,
        )


@app.route('/api/v1/cross_ownership')
def api_cross_ownership():
    """View 1: top holders of anchor company with cross-holdings in other tickers."""
    tickers_raw = request.args.get('tickers', '').upper().strip()
    anchor = request.args.get('anchor', '').upper().strip()
    active_only = request.args.get('active_only', 'false').lower() == 'true'
    limit = int(request.args.get('limit', 25))
    rt = _get_rollup_type(request)
    if not tickers_raw:
        return jsonify({'error': 'Missing tickers parameter'}), 400
    tickers = [t.strip() for t in tickers_raw.split(',') if t.strip()][:10]
    if not anchor:
        anchor = tickers[0]
    try:
        con = get_db()
    except Exception as e:
        return jsonify({'error': f'Database unavailable: {e}'}), 503
    try:
        return jsonify(_cross_ownership_query(con, tickers, anchor=anchor,
                                              active_only=active_only, limit=limit,
                                              rollup_type=rt))
    finally:
        con.close()


@app.route('/api/v1/cross_ownership_top')
def api_cross_ownership_top():
    """View 2: top investors by total exposure across all selected tickers."""
    tickers_raw = request.args.get('tickers', '').upper().strip()
    active_only = request.args.get('active_only', 'false').lower() == 'true'
    limit = int(request.args.get('limit', 25))
    rt = _get_rollup_type(request)
    if not tickers_raw:
        return jsonify({'error': 'Missing tickers parameter'}), 400
    tickers = [t.strip() for t in tickers_raw.split(',') if t.strip()][:10]
    try:
        con = get_db()
    except Exception as e:
        return jsonify({'error': f'Database unavailable: {e}'}), 503
    try:
        return jsonify(_cross_ownership_query(con, tickers, anchor=None,
                                              active_only=active_only, limit=limit,
                                              rollup_type=rt))
    finally:
        con.close()


@app.route('/api/v1/peer_groups')
def api_peer_groups():
    """Return all peer groups."""
    con = get_db()
    try:
        if not has_table('peer_groups'):
            return jsonify([])
        df = con.execute("""
            SELECT group_id, group_name, ticker, company_name, is_primary
            FROM peer_groups
            ORDER BY group_name, is_primary DESC, ticker
        """).fetchdf()
        # Group by group_id
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
        return jsonify(list(groups.values()))
    finally:
        con.close()


@app.route('/api/v1/peer_groups/<group_id>')
def api_peer_group_detail(group_id):
    """Return tickers in a specific peer group."""
    con = get_db()
    try:
        df = con.execute("""
            SELECT ticker, company_name, is_primary
            FROM peer_groups
            WHERE group_id = ?
            ORDER BY is_primary DESC, ticker
        """, [group_id]).fetchdf()
        return jsonify(df_to_records(df))
    finally:
        con.close()


@app.route('/api/v1/crowding')
def api_crowding():
    """Crowding analysis: institutional concentration + short interest overlay."""
    ticker = request.args.get('ticker', '').upper().strip()
    if not ticker:
        return jsonify({'error': 'Missing ticker parameter'}), 400
    con = get_db()
    try:
        # Top holders by % of float
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
        # Short interest overlay
        if has_table('short_interest'):
            si = con.execute("""
                SELECT report_date, short_volume, total_volume, short_pct
                FROM short_interest WHERE ticker = ?
                ORDER BY report_date DESC LIMIT 20
            """, [ticker]).fetchdf()
            result['short_history'] = df_to_records(si)
        return jsonify(clean_for_json(result))
    finally:
        con.close()


@app.route('/api/v1/portfolio_context')
def api_portfolio_context():
    """Conviction tab — portfolio concentration context."""
    ticker = request.args.get('ticker', '').upper().strip()
    level = request.args.get('level', 'parent').strip()
    ao = request.args.get('active_only', '').strip() == 'true'
    if not ticker:
        return respond(
            error={'code': 'missing_param', 'message': 'Missing ticker parameter'},
            schema=ConvictionEnvelope,
            status=400,
        )
    try:
        rt = _get_rollup_type(request)
        result = portfolio_context(ticker, level=level, active_only=ao, rollup_type=rt)
        return respond(data=clean_for_json(result), schema=ConvictionEnvelope)
    except Exception as e:
        return respond(
            error={'code': 'internal_error', 'message': str(e)},
            schema=ConvictionEnvelope,
            status=500,
        )


@app.route('/api/v1/short_analysis')
def api_short_analysis():
    """Short Interest Analysis — N-PORT shorts, FINRA volume, long/short cross-ref."""
    ticker = request.args.get('ticker', '').upper().strip()
    if not ticker:
        return jsonify({'error': 'Missing ticker parameter'}), 400
    try:
        rt = _get_rollup_type(request)
        result = short_interest_analysis(ticker, rollup_type=rt)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/v1/smart_money')
def api_smart_money():
    """Smart Money: net exposure view — long 13F vs short FINRA per manager type."""
    ticker = request.args.get('ticker', '').upper().strip()
    if not ticker:
        return jsonify({'error': 'Missing ticker parameter'}), 400
    con = get_db()
    try:
        # Long positions by manager type
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
        # Latest short volume
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
        # N-PORT short positions for this ticker
        if has_table('fund_holdings'):
            nport_shorts = con.execute("""
                SELECT fund_name, shares_or_principal as shares_short,
                       market_value_usd as short_value, quarter
                FROM fund_holdings_v2
                WHERE ticker = ? AND shares_or_principal < 0
                  AND asset_category IN ('EC', 'EP')
                ORDER BY market_value_usd ASC LIMIT 10
            """, [ticker]).fetchdf()
            result['nport_shorts'] = df_to_records(nport_shorts)
        return jsonify(clean_for_json(result))
    finally:
        con.close()


@app.route('/api/v1/short_long')
def api_short_long():
    """Short vs Long comparison: managers long via 13F and short via N-PORT."""
    ticker = request.args.get('ticker', '').upper().strip()
    if not ticker:
        return jsonify({'error': 'Missing ticker parameter'}), 400
    try:
        from queries import get_short_long_comparison
        rt = _get_rollup_type(request)
        result = get_short_long_comparison(ticker, rollup_type=rt)
        return jsonify(result)
    except Exception as e:
        app.logger.error("short_long error for %s: %s", ticker, e)
        return jsonify({'error': str(e)}), 500


@app.route('/api/v1/sector_flows')
def api_sector_flows():
    """Multi-quarter institutional money flows by GICS sector."""
    try:
        from queries import get_sector_flows
        active_only = request.args.get('active_only', '0') == '1'
        level = request.args.get('level', 'parent').strip()
        result = get_sector_flows(active_only=active_only, level=level)
        return jsonify(result)
    except Exception as e:
        app.logger.error("sector_flows error: %s", e)
        return jsonify({'error': str(e)}), 500


@app.route('/api/v1/sector_flow_movers')
def api_sector_flow_movers():
    """Top buyers/sellers for one sector in one quarter transition."""
    try:
        from queries import get_sector_flow_movers
        q_from = request.args.get('from', '').strip()
        q_to = request.args.get('to', '').strip()
        sector = request.args.get('sector', '').strip()
        active_only = request.args.get('active_only', '0') == '1'
        level = request.args.get('level', 'parent').strip()
        if not q_from or not q_to or not sector:
            return jsonify({'error': 'Missing required params: from, to, sector'}), 400
        rt = _get_rollup_type(request)
        result = get_sector_flow_movers(q_from, q_to, sector,
                                        active_only=active_only, level=level,
                                        rollup_type=rt)
        return jsonify(result)
    except Exception as e:
        app.logger.error("sector_flow_movers error: %s", e)
        return jsonify({'error': str(e)}), 500


@app.route('/api/v1/sector_flow_detail')
def api_sector_flow_detail():
    """Full cross-quarter detail for one sector: inflow/outflow/net + top movers."""
    try:
        from queries import get_sector_flow_detail
        sector = request.args.get('sector', '').strip()
        active_only = request.args.get('active_only', '0') == '1'
        level = request.args.get('level', 'parent').strip()
        if not sector:
            return jsonify({'error': 'Missing sector param'}), 400
        rank_by = request.args.get('rank_by', 'total').strip()
        rt = _get_rollup_type(request)
        result = get_sector_flow_detail(
            sector, active_only=active_only, level=level, rank_by=rank_by,
            rollup_type=rt)
        return jsonify(result)
    except Exception as e:
        app.logger.error("sector_flow_detail error: %s", e)
        return jsonify({'error': str(e)}), 500


@app.route('/api/v1/heatmap')
def api_heatmap():
    """Ownership concentration heatmap: top managers × tickers by pct_of_float."""
    ticker = request.args.get('ticker', '').upper().strip()
    peers = request.args.get('peers', '').upper().strip()
    con = get_db()
    try:
        # Build ticker list: current ticker + peers (comma-separated)
        tickers = [ticker] if ticker else []
        if peers:
            tickers += [t.strip() for t in peers.split(',') if t.strip()]
        if not tickers:
            # Default: top 10 tickers by institutional value
            top = con.execute(
                f""  # nosec B608
                f"""
                SELECT ticker, SUM(market_value_usd) as val
                FROM holdings_v2 WHERE quarter = '{LQ}' AND ticker IS NOT NULL
                GROUP BY ticker ORDER BY val DESC LIMIT 10
                """
            ).fetchall()
            tickers = [r[0] for r in top]

        # Top 15 managers by total value across these tickers
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
            return jsonify({'tickers': tickers, 'managers': [], 'cells': []})

        # Build the matrix: pct_of_float for each manager × ticker
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

        return jsonify(clean_for_json({
            'tickers': tickers,
            'managers': manager_names,
            'cells': df_to_records(cells),
        }))
    except Exception as e:
        app.logger.error("heatmap error: %s", e)
        return jsonify({'error': str(e)}), 500
    finally:
        con.close()


@app.route('/api/v1/manager_profile')
def api_manager_profile():
    """Manager profile: all holdings, sector allocation, top positions."""
    manager = request.args.get('manager', '').strip()
    if not manager:
        return jsonify({'error': 'Missing manager parameter'}), 400
    con = get_db()
    try:
        # Top holdings
        top_holdings_df = con.execute(
            f""  # nosec B608
            f"""
            SELECT ticker, issuer_name, shares, market_value_usd, market_value_live,
                   pct_of_portfolio, pct_of_float
            FROM holdings_v2
            WHERE quarter = '{LQ}' AND COALESCE(rollup_name, inst_parent_name) ILIKE ?
            ORDER BY market_value_usd DESC LIMIT 50
            """, [f'%{manager}%']
        ).fetchdf()

        # Sector allocation
        sectors = con.execute(
            f""  # nosec B608
            f"""
            SELECT m.sector, COUNT(DISTINCT h.ticker) as tickers,
                   SUM(h.market_value_usd) as value
            FROM holdings_v2 h
            LEFT JOIN market_data m ON h.ticker = m.ticker
            WHERE h.quarter = '{LQ}' AND COALESCE(h.rollup_name, h.inst_parent_name) ILIKE ?
              AND m.sector IS NOT NULL
            GROUP BY m.sector ORDER BY value DESC
            """, [f'%{manager}%']
        ).fetchdf()

        # Summary stats
        stats = con.execute(
            f""  # nosec B608
            f"""
            SELECT COUNT(DISTINCT ticker) as num_positions,
                   SUM(market_value_usd) as total_value,
                   COUNT(DISTINCT cik) as num_ciks,
                   MAX(manager_type) as manager_type
            FROM holdings_v2
            WHERE quarter = '{LQ}' AND COALESCE(rollup_name, inst_parent_name) ILIKE ?
            """, [f'%{manager}%']
        ).fetchone()

        # Quarter-over-quarter change
        qoq = con.execute("""
            SELECT quarter, COUNT(DISTINCT ticker) as positions,
                   SUM(market_value_usd) as total_value
            FROM holdings_v2 WHERE COALESCE(rollup_name, inst_parent_name) ILIKE ?
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
        return jsonify(clean_for_json(result))
    except Exception as e:
        app.logger.error("manager_profile error: %s", e)
        return jsonify({'error': str(e)}), 500
    finally:
        con.close()


@app.route('/api/v1/amendments')
def api_amendments():
    """13F-HR amendment reconciliation: show amended vs original filings per quarter."""
    ticker = request.args.get('ticker', '').upper().strip()
    if not ticker:
        return jsonify({'error': 'Missing ticker parameter'}), 400
    con = get_db()
    try:
        # Find managers who filed amendments for this ticker
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
                WHERE ticker = ? AND quarter = '{LQ}'
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

        return jsonify(clean_for_json({
            'ticker': ticker,
            'amendments': df_to_records(amendments),
        }))
    except Exception as e:
        app.logger.error("amendments error: %s", e)
        return jsonify({'error': str(e)}), 500
    finally:
        con.close()


@app.route('/api/v1/summary')
def api_summary():
    ticker = request.args.get('ticker', '').upper().strip()
    if not ticker:
        return jsonify({'error': 'Missing ticker parameter'}), 400
    result = get_summary(ticker)
    if not result:
        return jsonify({'error': f'No data found for ticker {ticker}'}), 404
    return jsonify(result)


def _execute_query(qnum):
    """Run query-N dispatch. Returns (data, error_dict, status).

    Shared core used by the generic `/api/v1/query<N>` handler AND the
    dedicated `/api/v1/query1` envelope handler below. Error shape follows
    ErrorShape (code/message) so callers can wrap in respond() or jsonify()
    as needed.
    """
    if qnum not in QUERY_FUNCTIONS:
        return None, {'code': 'invalid_query', 'message': f'Invalid query number: {qnum}'}, 400
    ticker = request.args.get('ticker', '').upper().strip()
    cik = request.args.get('cik', '').strip()
    quarter = request.args.get('quarter', LQ)
    rt = _get_rollup_type(request)

    if qnum not in (15,) and not ticker:
        return None, {'code': 'missing_param', 'message': 'Missing ticker parameter'}, 400

    try:
        fn = QUERY_FUNCTIONS[qnum]
        if qnum == 7:
            fund_name = request.args.get('fund_name', '').strip() or None
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


@app.route('/api/v1/query1')
def api_query1():
    """Register tab — enveloped per Phase 1-B2. Queries 2–16 stay bare."""
    data, err, status = _execute_query(1)
    if err is not None:
        return respond(error=err, schema=RegisterEnvelope, status=status)
    return respond(data=data, schema=RegisterEnvelope, status=status)


@app.route('/api/v1/query<int:qnum>')
def api_query(qnum):
    if qnum == 1:
        # Flask should dispatch /api/v1/query1 to api_query1 (more specific
        # route wins), but defend in depth in case routing order changes.
        return api_query1()
    data, err, status = _execute_query(qnum)
    if err is not None:
        return jsonify({'error': err['message']}), status
    return jsonify(data)


@app.route('/api/v1/export/query<int:qnum>')
def api_export(qnum):
    if qnum not in QUERY_FUNCTIONS:
        return jsonify({'error': f'Invalid query number: {qnum}'}), 400
    ticker = request.args.get('ticker', '').upper().strip()
    cik = request.args.get('cik', '').strip()
    quarter = request.args.get('quarter', LQ)
    rt = _get_rollup_type(request)

    if qnum not in (15,) and not ticker:
        return jsonify({'error': 'Missing ticker parameter'}), 400

    try:
        fn = QUERY_FUNCTIONS[qnum]
        if qnum == 7:
            fund_name = request.args.get('fund_name', '').strip() or None
            data = fn(ticker, cik=cik or None, fund_name=fund_name, quarter=quarter)
        elif qnum == 15:
            data = fn(ticker or None, quarter=quarter)
        elif qnum in _RT_AWARE_QUERIES:
            data = fn(ticker, rollup_type=rt, quarter=quarter)
        else:
            data = fn(ticker, quarter=quarter)

        if not data:
            return jsonify({'error': f'No data found for ticker {ticker}'}), 404

        # Extract the tabular portion from structured responses:
        #   q7         → {stats, positions}              export `positions`
        #   q1, q16    → {rows, all_totals, type_totals} export `rows`
        # Other multi-table shapes (q6 activist / q10 new_positions /
        # q11 exits / q15 db_stats) are pre-existing data-shape failures in
        # this extractor; tracked as BL-10 in Architecture Backlog. Out of
        # Batch 1-B1 scope, which is rollup + quarter parity.
        if isinstance(data, dict):
            if 'positions' in data:
                export_data = data['positions']
            elif 'rows' in data:
                export_data = data['rows']
            else:
                export_data = data
        else:
            export_data = data
        qname = QUERY_NAMES.get(qnum, f'Query{qnum}')
        sheet_name = f"{qname} - {ticker or 'ALL'}"
        buf = build_excel(export_data, sheet_name=sheet_name)

        filename = f"query{qnum}_{ticker or 'ALL'}_{datetime.now().strftime('%Y%m%d')}.xlsx"
        return send_file(
            buf,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=filename,
        )
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ---------------------------------------------------------------------------
# Entity Graph tab (Institution → Filer → Fund visualization)
# ---------------------------------------------------------------------------
# All three routes follow the existing pattern: get_db() → query → jsonify().
# `quarter` is required by /api/entity_children and /api/entity_graph and is
# always taken from the client (Quarter selector). Defaults to LATEST_QUARTER
# only if the client omits it. No raw SQL lives here — see queries.py.


def _eg_quarter(req):
    """Validate the `quarter` query param against config.QUARTERS, falling back
    to LATEST_QUARTER if missing or unrecognized."""
    # QUARTERS and LATEST_QUARTER are imported at module level (line 15) — no
    # local reimport needed.
    q = (req.args.get('quarter') or '').strip()  # nosec B113 — Flask request, not requests lib
    from config import QUARTERS as _QUARTERS  # local alias keeps lookup explicit
    return q if q in _QUARTERS else LATEST_QUARTER


@app.route('/api/v1/entity_search')
def api_entity_search():
    """Type-ahead search for the Institution dropdown. Searches rollup parents
    only (entity_id = rollup_entity_id). Requires q ≥ 2 chars."""
    q = (request.args.get('q') or '').strip()
    if len(q) < 2:
        return jsonify([])
    try:
        con = get_db()
    except Exception as e:
        return jsonify({'error': f'Database unavailable: {e}'}), 503
    try:
        results = queries.search_entity_parents(q, con)
        return jsonify(queries.clean_for_json(results))
    except Exception as e:
        app.logger.error("entity_search error: %s", e, exc_info=True)
        return jsonify({'error': str(e)}), 500
    finally:
        con.close()


@app.route('/api/v1/entity_children')
def api_entity_children():
    """Cascading dropdown population. `level` is 'filer' or 'fund'.
    Filer level returns CIK-bearing descendants (tree walk, fallback to self).
    Fund level returns series_id-bearing children with NAV from fund_universe.
    """
    entity_id = (request.args.get('entity_id') or '').strip()
    level = (request.args.get('level') or 'filer').strip()
    if not entity_id:
        return jsonify({'error': 'Missing entity_id parameter'}), 400
    try:
        eid = int(entity_id)
    except ValueError:
        return jsonify({'error': f'Invalid entity_id: {entity_id}'}), 400

    quarter = _eg_quarter(request)

    try:
        con = get_db()
    except Exception as e:
        return jsonify({'error': f'Database unavailable: {e}'}), 503
    try:
        if level == 'filer':
            data = queries.get_entity_filer_children(eid, quarter, con)
            return jsonify(queries.clean_for_json(data))
        elif level == 'fund':
            try:
                top_n = int(request.args.get('top_n', '0'))
            except ValueError:
                top_n = 0
            # top_n = 0 means "all" — use a high cap to avoid runaway payloads.
            if top_n <= 0:
                top_n = 10000
            data = queries.get_entity_fund_children(eid, top_n, con)
            return jsonify(queries.clean_for_json(data))
        else:
            return jsonify({'error': f'Invalid level: {level}'}), 400
    except Exception as e:
        app.logger.error("entity_children error: %s", e, exc_info=True)
        return jsonify({'error': str(e)}), 500
    finally:
        con.close()


@app.route('/api/v1/entity_graph')
def api_entity_graph():
    """Main graph data endpoint — returns {nodes, edges, metadata} for vis.js.

    The selected entity is resolved to its institution root (via rollup_entity_id),
    filer children are walked from there, fund children come from the institution
    root (funds attach at the institution level in this data model), and
    sub-advisers are pulled per fund when include_sub_advisers=true.
    """
    entity_id = (request.args.get('entity_id') or '').strip()
    if not entity_id:
        return respond(
            error={'code': 'missing_param', 'message': 'Missing entity_id parameter'},
            schema=EntityGraphEnvelope,
            status=400,
        )
    try:
        eid = int(entity_id)
    except ValueError:
        return respond(
            error={'code': 'invalid_param', 'message': f'Invalid entity_id: {entity_id}'},
            schema=EntityGraphEnvelope,
            status=400,
        )

    quarter = _eg_quarter(request)
    try:
        depth = int(request.args.get('depth', '2'))
    except ValueError:
        depth = 2
    include_sub = (request.args.get('include_sub_advisers', 'true').lower() != 'false')
    try:
        top_n_funds = int(request.args.get('top_n_funds', '20'))
    except ValueError:
        top_n_funds = 20
    if top_n_funds <= 0:
        top_n_funds = 20

    try:
        con = get_db()
    except Exception as e:
        return respond(
            error={'code': 'db_unavailable', 'message': f'Database unavailable: {e}'},
            schema=EntityGraphEnvelope,
            status=503,
        )
    try:
        data = queries.build_entity_graph(eid, quarter, depth, include_sub, top_n_funds, con)
        if isinstance(data, dict) and data.get('error'):
            return respond(
                error={'code': 'not_found', 'message': str(data['error'])},
                schema=EntityGraphEnvelope,
                status=404,
            )
        return respond(data=queries.clean_for_json(data), schema=EntityGraphEnvelope)
    except Exception as e:
        app.logger.error("entity_graph error: %s", e, exc_info=True)
        return respond(
            error={'code': 'internal_error', 'message': str(e)},
            schema=EntityGraphEnvelope,
            status=500,
        )
    finally:
        con.close()


@app.route('/api/v1/two_company_overlap')
def api_two_company_overlap():
    """Two Companies Overlap tab — institutional and fund-level holder comparison."""
    # QUARTERS lives in config; aliased locally to avoid a reimport warning
    # against the LATEST_QUARTER import at module top.
    from config import QUARTERS as _QUARTERS
    subject = request.args.get('subject', '').upper().strip()
    second = request.args.get('second', '').upper().strip()
    quarter = request.args.get('quarter', '').strip() or LATEST_QUARTER
    if quarter not in _QUARTERS:
        quarter = LATEST_QUARTER
    if not subject or not second:
        return jsonify({'error': 'Missing subject or second ticker'}), 400
    try:
        con = get_db()
    except Exception as e:
        return jsonify({'error': f'Database unavailable: {e}'}), 503
    try:
        result = queries.get_two_company_overlap(subject, second, quarter, con)
        return jsonify(clean_for_json(result))
    except Exception as e:
        app.logger.error("two_company_overlap error: %s", e, exc_info=True)
        return jsonify({'error': str(e)}), 500
    finally:
        con.close()


@app.route('/api/v1/two_company_subject')
def api_two_company_subject():
    """Return top 50 holders for subject ticker only — used for immediate
    tab load before the user selects a second company. Same payload shape
    as /api/two_company_overlap with all sec_* fields set to None."""
    from config import QUARTERS as _QUARTERS
    subject = request.args.get('subject', '').upper().strip()
    quarter = request.args.get('quarter', '').strip() or LATEST_QUARTER
    if quarter not in _QUARTERS:
        quarter = LATEST_QUARTER
    if not subject:
        return jsonify({'error': 'Missing subject ticker'}), 400
    try:
        con = get_db()
    except Exception as e:
        return jsonify({'error': f'Database unavailable: {e}'}), 503
    try:
        result = queries.get_two_company_subject(subject, quarter, con)
        return jsonify(clean_for_json(result))
    except Exception as e:
        app.logger.error("two_company_subject error: %s", e, exc_info=True)
        return jsonify({'error': str(e)}), 500
    finally:
        con.close()


@app.route('/api/v1/entity_resolve')
def api_entity_resolve():
    """Resolve any entity_id to its canonical institution root.

    Thin wrapper around the rollup_entity_id walk already used by
    build_entity_graph(). Lets external tooling resolve a descendant entity
    (a filer subsidiary, a fund series) to its top-level institution without
    pulling the full graph payload. Returns the canonical root plus the
    selected entity for round-tripping.
    """
    entity_id = (request.args.get('entity_id') or '').strip()
    if not entity_id:
        return jsonify({'error': 'Missing entity_id parameter'}), 400
    try:
        eid = int(entity_id)
    except ValueError:
        return jsonify({'error': f'Invalid entity_id: {entity_id}'}), 400

    try:
        con = get_db()
    except Exception as e:
        return jsonify({'error': f'Database unavailable: {e}'}), 503
    try:
        ent = queries.get_entity_by_id(eid, con)
        if not ent:
            return jsonify({'error': f'entity_id {eid} not found'}), 404

        # Same rollup walk as build_entity_graph(): if rollup_entity_id is set
        # and points elsewhere, fetch the canonical parent. Fall back to self
        # if the parent row can't be loaded for any reason.
        root_id = ent['rollup_entity_id'] if ent['rollup_entity_id'] else ent['entity_id']
        root = ent if root_id == ent['entity_id'] else queries.get_entity_by_id(root_id, con)
        if not root:
            root = ent
            root_id = ent['entity_id']

        return jsonify(queries.clean_for_json({
            'selected_entity_id': eid,
            'selected_display_name': ent['display_name'],
            'root_entity_id': root_id,
            'root_display_name': root['display_name'],
            'entity_type': root.get('entity_type'),
            'classification': root.get('classification'),
            'is_self_root': root_id == ent['entity_id'],
        }))
    except Exception as e:
        app.logger.error("entity_resolve error: %s", e, exc_info=True)
        return jsonify({'error': str(e)}), 500
    finally:
        con.close()


@app.route('/api/v1/entity_market_summary')
def api_entity_market_summary():
    """Market-wide: top institutions by 13F book value with filer + fund counts."""
    try:
        limit = int(request.args.get('limit', 25))
    except ValueError:
        limit = 25
    try:
        from queries import get_market_summary
        result = get_market_summary(limit=limit)
        return jsonify(result)
    except Exception as e:
        app.logger.error("entity_market_summary error: %s", e, exc_info=True)
        return jsonify({'error': str(e)}), 500


# ---------------------------------------------------------------------------
# Main
@app.route('/api/v1/peer_rotation')
def api_peer_rotation():
    """Peer rotation analysis: subject vs sector/industry peer substitutions."""
    try:
        from queries import get_peer_rotation
        ticker = request.args.get('ticker', '').upper().strip()
        if not ticker:
            return jsonify({'error': 'Missing ticker param'}), 400
        active_only = request.args.get('active_only', '0') == '1'
        level = request.args.get('level', 'parent').strip()
        rt = _get_rollup_type(request)
        result = get_peer_rotation(ticker, active_only=active_only, level=level, rollup_type=rt)
        return jsonify(result)
    except Exception as e:
        app.logger.error("peer_rotation error: %s", e)
        return jsonify({'error': str(e)}), 500


@app.route('/api/v1/peer_rotation_detail')
def api_peer_rotation_detail():
    """Entity-level breakdown for a subject+peer substitution pair."""
    try:
        from queries import get_peer_rotation_detail
        ticker = request.args.get('ticker', '').upper().strip()
        peer = request.args.get('peer', '').upper().strip()
        if not ticker or not peer:
            return jsonify({'error': 'Missing ticker or peer param'}), 400
        active_only = request.args.get('active_only', '0') == '1'
        level = request.args.get('level', 'parent').strip()
        rt = _get_rollup_type(request)
        result = get_peer_rotation_detail(
            ticker, peer, active_only=active_only, level=level, rollup_type=rt)
        return jsonify(result)
    except Exception as e:
        app.logger.error("peer_rotation_detail error: %s", e)
        return jsonify({'error': str(e)}), 500


# ---------------------------------------------------------------------------
# API v1 dual-mount (ARCH-1A) — register every public /api/<name> route
# under /api/v1/<name> as well. Legacy /api/* stays live for vanilla-JS
# frontend until retirement window 2026-04-20. After retirement, replace
# with a url_prefix Blueprint and drop the legacy mount.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='13F Ownership Research Web App')
    parser.add_argument('--port', type=int, default=8001, help='Port to run on (default: 8001)')
    args = parser.parse_args()

    # Check PORT env var (for Render deployment)
    port = int(os.environ.get('PORT', args.port))

    # Resolve database path at startup (creates snapshot if main DB is locked)
    _init_db_path()
    queries._setup(get_db, has_table)  # pylint: disable=protected-access

    print()
    print('  13F Ownership Research')
    print(f'  Database: {_active_db_path}')
    if _active_db_path != DB_PATH:
        print('  (main DB locked — serving from snapshot)')
    print(f'  Running at: http://localhost:{port}')
    print()

    app.run(host='0.0.0.0', port=port, debug=False)  # nosec B104 — dev/Render server bind
