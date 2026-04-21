"""
sec-01: Admin router for /api/admin/* endpoints (FastAPI).

All routes on this router require ENABLE_ADMIN=1 and ADMIN_TOKEN set in
env. Authentication is cookie-based via `admin_session` — a server-side
row in `admin_sessions` addressed by a UUID4. The login endpoint
verifies the env ADMIN_TOKEN with hmac.compare_digest, issues a session
row, and sets the cookie.

Idle timeout: 30 min. Absolute timeout: 8 h. Cookie attributes:
HttpOnly, SameSite=Strict, Path=/api/admin, Max-Age=28800s, Secure iff
the request is over HTTPS.

When ENABLE_ADMIN or ADMIN_TOKEN is unset, every route returns 503
"Admin disabled". When the session cookie is missing, expired, revoked,
or idle past 30 min, returns 401. When a wrong token is presented to
/api/admin/login, returns 403.

See docs/findings/sec-01-p0-findings.md for the full design. Migration
009_admin_sessions.py originally created the backing table in PROD_DB;
the sec-01-p1 hotfix moved it into its own file (data/admin.duckdb),
attached READ_WRITE to the app's existing connection — see the block
comment on ADMIN_DB below for the "why".

Name retained as `admin_bp.py` for git history continuity even though
the exported symbol is now an APIRouter (`admin_router`).
"""
from __future__ import annotations

import csv as _csv
import fcntl
import hmac
import io as _io
import logging
import os
import re
import secrets as _secrets
import subprocess  # nosec B404
import uuid
from datetime import datetime, timedelta

import duckdb
from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from config import LATEST_QUARTER, PREV_QUARTER
from db import PROD_DB
from queries import clean_for_json, df_to_records

log = logging.getLogger(__name__)

LQ = LATEST_QUARTER
PQ = PREV_QUARTER

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# Module-level refs set by init_admin_bp() from app.py. Avoids circular import
# (app.py imports this module at load time; get_db / has_table are defined in
# app_db.py but this router can be registered before _setup runs).
_get_db = None
_has_table = None


def init_admin_bp(get_db_fn, has_table_fn):
    """Wire app_db's DB helpers into the router.
    Must be called from app.py before `app.include_router(admin_router)`.
    """
    global _get_db, _has_table  # pylint: disable=global-statement
    _get_db = get_db_fn
    _has_table = has_table_fn


# Session lifetimes (seconds).
SESSION_IDLE_TIMEOUT = 1800        # 30 min idle cap
SESSION_ABSOLUTE_TIMEOUT = 28800   # 8 h absolute cap
SESSION_COOKIE_NAME = 'admin_session'
SESSION_COOKIE_PATH = '/api/admin'
_LOGIN_PATH = '/api/admin/login'
_UA_MAX_LEN = 512


def _env_admin_enabled() -> bool:
    return (
        os.environ.get('ENABLE_ADMIN') == '1'
        and bool(os.environ.get('ADMIN_TOKEN'))
    )


def _client_ip(request: Request) -> str | None:
    fwd = request.headers.get('x-forwarded-for')
    if fwd:
        # First hop; strip whitespace. We do not log or expose this beyond
        # the audit row in admin_sessions.
        return fwd.split(',')[0].strip() or None
    client = request.client
    return client.host if client else None


# sec-01-p1 hotfix: previously this opened a fresh read-write connection to
# PROD_DB on every admin request. Because app_db.get_db() keeps a read-only
# handle cached per request thread, a second open in a different mode hits
# DuckDB's "Can't open a connection to same database file with a different
# configuration" error, and concurrent admin requests race to lose. The fix:
#
#   1. Move admin_sessions out of PROD_DB into its own file (ADMIN_DB below).
#   2. Per-request, ATTACH that file READ_WRITE to the app's existing RO
#      connection — DuckDB allows per-attach modes independent of the main
#      database's mode, so no cross-configuration conflict can arise.
#   3. Bootstrap the attached schema once on module init.
#
# Existing sessions in PROD_DB.admin_sessions (created by migration 009)
# are dropped on the floor: one forced re-login is the cost of the fix.
ADMIN_DB = os.path.join(BASE_DIR, 'data', 'admin.duckdb')
_ADMIN_SCHEMA_NAME = 'adm'
_ADMIN_BOOTSTRAPPED = False

_ADMIN_SESSIONS_DDL = """
CREATE TABLE IF NOT EXISTS admin_sessions (
    session_id   VARCHAR PRIMARY KEY,
    issued_at    TIMESTAMP NOT NULL,
    expires_at   TIMESTAMP NOT NULL,
    last_used_at TIMESTAMP NOT NULL,
    ip           VARCHAR,
    user_agent   VARCHAR,
    revoked_at   TIMESTAMP
)
"""
_ADMIN_SESSIONS_INDEX_DDL = (
    "CREATE INDEX IF NOT EXISTS idx_admin_sessions_expires "
    "ON admin_sessions(expires_at)"
)


def _bootstrap_admin_db() -> None:
    """Create ADMIN_DB + admin_sessions if they don't already exist.

    Runs once per process. Uses a fresh RW connection to the dedicated admin
    file (which no other process/thread touches), so it cannot conflict with
    app_db's PROD_DB handle.
    """
    global _ADMIN_BOOTSTRAPPED  # pylint: disable=global-statement
    if _ADMIN_BOOTSTRAPPED:
        return
    con = duckdb.connect(ADMIN_DB, read_only=False)
    try:
        con.execute(_ADMIN_SESSIONS_DDL)
        con.execute(_ADMIN_SESSIONS_INDEX_DDL)
    finally:
        con.close()
    _ADMIN_BOOTSTRAPPED = True


def _session_db() -> duckdb.DuckDBPyConnection:
    """Return the app's shared connection with admin_sessions accessible.

    Reuses app_db.get_db() — which is the single shared handle the rest of
    the app already talks through — and ATTACHes ADMIN_DB as 'adm' in
    READ_WRITE mode on first use per connection. The fully-qualified name
    `adm.admin_sessions` is used by every caller.
    """
    _bootstrap_admin_db()
    con = _get_db()
    try:
        con.execute(
            f"ATTACH '{ADMIN_DB}' AS {_ADMIN_SCHEMA_NAME} (READ_WRITE)"
        )
    except duckdb.BinderException:
        # Already attached on this connection — the common path after the
        # first request on a given thread. DuckDB raises BinderException
        # ("database X is already attached") which we can safely ignore.
        pass
    return con


def _sweep_expired(con: duckdb.DuckDBPyConnection) -> None:
    """Opportunistic cleanup — delete expired rows and long-revoked rows.

    Called at ~1% sample rate from require_admin_session. Kept cheap: the
    index on expires_at covers the first predicate; the revoked_at filter
    is a table-scan tail but applies to a narrow set in practice.
    """
    con.execute(
        """
        DELETE FROM adm.admin_sessions
         WHERE expires_at < NOW()
            OR (revoked_at IS NOT NULL AND revoked_at < NOW() - INTERVAL 7 DAY)
        """
    )


def require_admin_session(request: Request) -> None:
    """sec-01: Session-cookie dependency for every admin endpoint.

    503 if ENABLE_ADMIN or ADMIN_TOKEN unset.
    401 on missing / expired / revoked / idle-timeout session cookie.

    The /api/admin/login path is exempt from the session check so that
    unauthenticated clients can obtain a session. Login still enforces
    the env gate and performs its own hmac.compare_digest against the
    presented token.
    """
    if not _env_admin_enabled():
        raise HTTPException(status_code=503, detail={'error': 'Admin disabled'})

    if request.url.path == _LOGIN_PATH:
        return

    sid = request.cookies.get(SESSION_COOKIE_NAME)
    if not sid:
        raise HTTPException(status_code=401, detail={'error': 'No admin session'})

    con = _session_db()
    row = con.execute(
        """
        SELECT issued_at, expires_at, last_used_at, revoked_at
          FROM adm.admin_sessions
         WHERE session_id = ?
           AND revoked_at IS NULL
        """,
        [sid],
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=401, detail={'error': 'Invalid session'})
    _issued_at, expires_at, last_used_at, _revoked_at = row

    now = datetime.now()
    if expires_at < now:
        raise HTTPException(status_code=401, detail={'error': 'Session expired'})
    if now - last_used_at > timedelta(seconds=SESSION_IDLE_TIMEOUT):
        raise HTTPException(status_code=401, detail={'error': 'Session idle'})

    # sec-01-p1 hotfix: the admin dashboard fires 6+ parallel requests on
    # load, each of which touches this same row. get_db() is thread-local,
    # so concurrent requests UPDATE from distinct connections and MVCC raises
    # TransactionException on the losers. A stale last_used_at is harmless:
    # the expiry check above uses the previously-committed value, and the
    # next non-contending request will push it forward — so swallow and move on.
    try:
        con.execute(
            "UPDATE adm.admin_sessions SET last_used_at = NOW() WHERE session_id = ?",
            [sid],
        )
    except duckdb.TransactionException as e:
        log.debug("last_used_at contention: %s", e)

    # ~1% opportunistic sweep.
    if _secrets.randbelow(100) == 0:
        try:
            _sweep_expired(con)
        except Exception as e:  # pylint: disable=broad-except
            log.debug("session sweep: %s", e)


admin_router = APIRouter(
    prefix='/api/admin',
    tags=['admin'],
    dependencies=[Depends(require_admin_session)],
)

# Backwards-compat alias: app.py used to import `admin_bp` + `init_admin_bp`.
# Keep the name exported so old imports don't break mid-migration.
admin_bp = admin_router


# ---------------------------------------------------------------------------
# sec-01: Session lifecycle — login / logout / logout_all
# ---------------------------------------------------------------------------


def _set_session_cookie(response: Response, session_id: str, *, secure: bool) -> None:
    """Attach the admin_session cookie — HttpOnly, SameSite=Strict, path-scoped."""
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_id,
        max_age=SESSION_ABSOLUTE_TIMEOUT,
        path=SESSION_COOKIE_PATH,
        httponly=True,
        secure=secure,
        samesite='strict',
    )


def _clear_session_cookie(response: Response) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value='',
        max_age=0,
        path=SESSION_COOKIE_PATH,
        httponly=True,
        secure=False,
        samesite='strict',
    )


@admin_router.post('/login')
def api_admin_login(request: Request, response: Response, body: dict = Body(default={})):
    """Verify ADMIN_TOKEN and issue an admin_session cookie.

    Exempt from require_admin_session (the dep short-circuits on this
    path). The env gate is still enforced here explicitly.
    """
    if not _env_admin_enabled():
        raise HTTPException(status_code=503, detail={'error': 'Admin disabled'})

    provided = (body or {}).get('token') or ''
    expected = os.environ['ADMIN_TOKEN']
    if not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=403, detail={'error': 'Forbidden'})

    sid = str(uuid.uuid4())
    now = datetime.now()
    expires_at = now + timedelta(seconds=SESSION_ABSOLUTE_TIMEOUT)
    ua = (request.headers.get('user-agent') or '')[:_UA_MAX_LEN]
    ip = _client_ip(request)

    con = _session_db()
    con.execute(
        """
        INSERT INTO adm.admin_sessions
          (session_id, issued_at, expires_at, last_used_at, ip, user_agent, revoked_at)
        VALUES (?, ?, ?, ?, ?, ?, NULL)
        """,
        [sid, now, expires_at, now, ip, ua],
    )

    _set_session_cookie(response, sid, secure=(request.url.scheme == 'https'))
    return {'status': 'ok'}


@admin_router.post('/logout')
def api_admin_logout(request: Request, response: Response):
    """Revoke the caller's session. Idempotent."""
    sid = request.cookies.get(SESSION_COOKIE_NAME)
    if sid:
        con = _session_db()
        con.execute(
            """
            UPDATE adm.admin_sessions
               SET revoked_at = NOW()
             WHERE session_id = ?
               AND revoked_at IS NULL
            """,
            [sid],
        )
    _clear_session_cookie(response)
    return {'status': 'ok'}


@admin_router.post('/logout_all')
def api_admin_logout_all(response: Response):
    """Revoke every active admin session. Clears the caller's cookie."""
    con = _session_db()
    pre = con.execute(
        "SELECT COUNT(*) FROM adm.admin_sessions WHERE revoked_at IS NULL"
    ).fetchone()
    con.execute(
        "UPDATE adm.admin_sessions SET revoked_at = NOW() WHERE revoked_at IS NULL"
    )
    _clear_session_cookie(response)
    count = int(pre[0]) if pre and pre[0] is not None else 0
    return {'status': 'ok', 'revoked': count}


# ---------------------------------------------------------------------------
# On-demand ticker add (moved from /api/add_ticker per INF12)
# ---------------------------------------------------------------------------


@admin_router.post('/add_ticker')
def api_add_ticker(body: dict = Body(default={})):
    """Add a single ticker on-demand: fetch CUSIP, market data, 13D/G filings."""
    ticker = (body.get('ticker') or '').upper().strip()
    if not ticker:
        return JSONResponse(status_code=400, content={'error': 'Missing ticker'})

    results = {'ticker': ticker, 'steps': []}

    try:
        # Step 1: Resolve CUSIP via OpenFIGI
        import requests as req  # pylint: disable=import-outside-toplevel
        figi_resp = req.post(
            "https://api.openfigi.com/v3/mapping",
            json=[{"idType": "TICKER", "idValue": ticker}],
            timeout=10,
        )
        cusip = None
        if figi_resp.status_code == 200:
            data = figi_resp.json()
            if data and data[0].get('data'):
                cusip = data[0]['data'][0].get('figi')
                results['cusip'] = cusip
                results['steps'].append('OpenFIGI: resolved')
            else:
                results['steps'].append('OpenFIGI: no match')
        else:
            results['steps'].append(f'OpenFIGI: HTTP {figi_resp.status_code}')

        # Step 2: Fetch market data via YahooClient + SEC XBRL
        from yahoo_client import YahooClient  # pylint: disable=import-outside-toplevel
        from sec_shares_client import SECSharesClient  # pylint: disable=import-outside-toplevel
        yc = YahooClient()
        sc = SECSharesClient()
        m = yc.fetch_metadata(ticker) or {}
        price = m.get('price')
        if price:
            sec = sc.fetch(ticker) or {}
            shares_out = sec.get('shares_outstanding')
            market_cap = (shares_out * price) if (shares_out and price) else None
            con = duckdb.connect(PROD_DB)
            now = datetime.now().strftime('%Y-%m-%d')
            con.execute("""
                INSERT OR REPLACE INTO market_data (ticker, price_live, market_cap,
                    float_shares, shares_outstanding, sector, industry, exchange, fetch_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [ticker, price, market_cap,
                  m.get('float_shares'), shares_out,
                  m.get('sector'), m.get('industry'), m.get('exchange'), now])
            con.execute("CHECKPOINT")
            con.close()
            results['market_cap'] = market_cap
            results['price'] = price
            results['sector'] = m.get('sector')
            results['shares_source'] = 'SEC' if shares_out else None
            results['steps'].append(
                f'Market data: added (market_cap {"computed from SEC shares × price" if market_cap else "NULL — no SEC shares"})')
        else:
            results['steps'].append('Market data: Yahoo returned no price')

        # Step 3: Fetch 13D/G filings
        try:
            import edgar  # pylint: disable=import-error,import-outside-toplevel
            edgar.set_identity("serge.tismen@gmail.com")
            company = edgar.Company(ticker)
            filing_count = 0
            for form in ['SC 13D', 'SC 13G']:
                filings = company.get_filings(form=form)
                if filings:
                    for f in filings:
                        if str(f.filing_date) >= '2022-01-01':
                            filing_count += 1
            results['filings_found'] = filing_count
            results['steps'].append(f'13D/G: {filing_count} filings found (not parsed — run Phase 2)')
        except Exception as e:  # pylint: disable=broad-except
            results['steps'].append(f'13D/G: {e}')

        results['status'] = 'ok'
        return results

    except Exception as e:  # pylint: disable=broad-except
        results['status'] = 'error'
        results['error'] = str(e)
        return JSONResponse(status_code=500, content=results)


# ---------------------------------------------------------------------------
# Admin stats / monitoring / data-quality (read-only — gated per INF12)
# ---------------------------------------------------------------------------


@admin_router.get('/stats')
def api_admin_stats():
    """Database row counts for admin dashboard."""
    con = _get_db()
    try:
        stats = {}
        for table, key in [('holdings_v2', 'holdings'), ('managers', 'managers'),
                           ('beneficial_ownership_v2', 'beneficial_ownership'),
                           ('fund_holdings_v2', 'fund_holdings')]:
            try:
                stats[key] = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # nosec B608
            except Exception as e:  # pylint: disable=broad-except
                log.debug("stats error: %s", e)
                stats[key] = 0
        try:
            stats['tickers'] = con.execute("SELECT COUNT(DISTINCT ticker) FROM holdings_v2 WHERE ticker IS NOT NULL").fetchone()[0]
        except Exception as e:  # pylint: disable=broad-except
            log.debug("tickers error: %s", e)
            stats['tickers'] = 0
        try:
            stats['short_interest_days'] = con.execute("SELECT COUNT(DISTINCT report_date) FROM short_interest").fetchone()[0]
        except Exception as e:  # pylint: disable=broad-except
            log.debug("si error: %s", e)
            stats['short_interest_days'] = 0
        return stats
    finally:
        con.close()


@admin_router.get('/progress')
def api_admin_progress():
    """Check if a pipeline is running and return progress."""
    result = {'running': False}
    try:
        ps = subprocess.run(['pgrep', '-f', 'fetch_13dg.py'], capture_output=True, text=True, check=False)  # nosec  # bandit B607 + B603
        if ps.returncode == 0:
            result['running'] = True
    except Exception as e:  # pylint: disable=broad-except
        log.debug("progress pgrep: %s", e)

    progress_file = os.path.join(BASE_DIR, 'logs', 'phase2_progress.txt')
    try:
        with open(progress_file, encoding='utf-8') as f:
            lines = f.read().strip().split('\n')
            if lines:
                result['progress_line'] = lines[0].strip()
                m = re.search(r'\[(\d+)/(\d+)\]', lines[0])
                if m:
                    done, total = int(m.group(1)), int(m.group(2))
                    result['pct'] = round(done / total * 100, 1) if total > 0 else 0
                    result['done'] = done
                    result['total'] = total
                if len(lines) > 1:
                    result['last_update'] = lines[1].strip()
    except FileNotFoundError:
        pass

    return result


@admin_router.get('/errors')
def api_admin_errors():
    """Return recent errors from fetch_13dg_errors.csv."""
    error_file = os.path.join(BASE_DIR, 'logs', 'fetch_13dg_errors.csv')
    try:
        with open(error_file, encoding='utf-8') as f:
            lines = f.readlines()
        recent = ''.join(lines[-20:]) if len(lines) > 20 else ''.join(lines)
        return {'errors': recent, 'count': len(lines) - 1}
    except FileNotFoundError:
        return {'errors': 'No error log found', 'count': 0}


@admin_router.post('/run_script')
def api_admin_run_script(body: dict = Body(default={})):
    """Run a pipeline script in the background. Returns immediately."""
    script = body.get('script', '')
    flags = body.get('flags', [])

    # INF12: run_pipeline.sh and merge_staging.py removed — never web-triggerable.
    # BLOCK-1 (2026-04-17 audit): fetch_nport.py retired; removed from allowlist
    # to prevent resurrection of legacy fund_holdings.
    allowed = {
        'fetch_13dg.py', 'fetch_market.py',
        'fetch_finra_short.py', 'fetch_ncen.py', 'compute_flows.py',
        'build_cusip.py', 'build_summaries.py', 'unify_positions.py',
        'refresh_snapshot.sh',
    }
    if script not in allowed:
        return JSONResponse(status_code=400, content={'error': f'Script not allowed: {script}'})

    # sec-02-p1: flock-based concurrency guard. Kernel-level advisory lock on a
    # per-script sentinel file, acquired non-blocking before spawn. The fd is
    # passed to the child via `pass_fds`; the kernel keeps the lock alive as
    # long as any fd pointing at the open file description remains, so the
    # child holds the lock until it exits (regardless of how it exits — SIGKILL,
    # OOM, segfault all release it). Parent closes its own fd immediately.
    # See docs/findings/sec-02-p0-findings.md §4 Option A.
    lock_path = os.path.join(BASE_DIR, 'data', f'.run_{script}.lock')
    lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(lock_fd)
        return JSONResponse(status_code=409, content={'error': f'{script} is already running'})

    try:
        script_path = os.path.join(BASE_DIR, 'scripts', script)
        if script.endswith('.sh'):
            cmd = ['bash', script_path] + flags
        else:
            cmd = ['python3', '-u', script_path] + flags

        log_name = script.replace('.py', '').replace('.sh', '')
        log_path = os.path.join(BASE_DIR, 'logs', f'{log_name}_run.log')
        with open(log_path, 'w', encoding='utf-8') as log_file:
            proc = subprocess.Popen(  # nosec B603
                cmd,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                cwd=BASE_DIR,
                pass_fds=(lock_fd,),
                close_fds=True,
            )
    finally:
        # Parent releases its fd unconditionally. On the success path the
        # child has already inherited a dup and holds the lock; on a Popen
        # failure the lock must drop so the next request isn't 409-wedged.
        os.close(lock_fd)

    return {
        'status': 'started',
        'script': script,
        'flags': flags,
        'pid': proc.pid,
        'log': log_path,
    }


@admin_router.get('/manager_changes')
def api_admin_manager_changes():
    """D2: Detect manager changes across quarters — new, disappeared, name changes."""
    con = _get_db()
    try:
        new_mgrs = con.execute(
            f""  # nosec B608
            f"""
            SELECT DISTINCT cik, manager_name, manager_type
            FROM holdings_v2 WHERE quarter = '{LATEST_QUARTER}'
              AND cik NOT IN (SELECT DISTINCT cik FROM holdings_v2 WHERE quarter = '{PREV_QUARTER}')
            ORDER BY manager_name LIMIT 50
            """
        ).fetchdf()
        gone_mgrs = con.execute(
            f""  # nosec B608
            f"""
            SELECT DISTINCT cik, manager_name, manager_type
            FROM holdings_v2 WHERE quarter = '{PREV_QUARTER}'
              AND cik NOT IN (SELECT DISTINCT cik FROM holdings_v2 WHERE quarter = '{LATEST_QUARTER}')
            ORDER BY manager_name LIMIT 50
            """
        ).fetchdf()
        return clean_for_json({
            'new_managers': df_to_records(new_mgrs),
            'disappeared_managers': df_to_records(gone_mgrs),
            'latest_quarter': LATEST_QUARTER,
            'prev_quarter': PREV_QUARTER,
        })
    finally:
        con.close()


@admin_router.get('/ticker_changes')
def api_admin_ticker_changes():
    """D3: Detect ticker changes — new tickers, disappeared tickers."""
    con = _get_db()
    try:
        new_tickers = con.execute(
            f""  # nosec B608
            f"""
            SELECT DISTINCT ticker, MAX(issuer_name) as company
            FROM holdings_v2 WHERE quarter = '{LATEST_QUARTER}' AND ticker IS NOT NULL
              AND ticker NOT IN (SELECT DISTINCT ticker FROM holdings_v2 WHERE quarter = '{PREV_QUARTER}' AND ticker IS NOT NULL)
            GROUP BY ticker ORDER BY ticker LIMIT 100
            """
        ).fetchdf()
        gone_tickers = con.execute(
            f""  # nosec B608
            f"""
            SELECT DISTINCT ticker, MAX(issuer_name) as company
            FROM holdings_v2 WHERE quarter = '{PREV_QUARTER}' AND ticker IS NOT NULL
              AND ticker NOT IN (SELECT DISTINCT ticker FROM holdings_v2 WHERE quarter = '{LATEST_QUARTER}' AND ticker IS NOT NULL)
            GROUP BY ticker ORDER BY ticker LIMIT 100
            """
        ).fetchdf()
        return clean_for_json({
            'new_tickers': df_to_records(new_tickers),
            'disappeared_tickers': df_to_records(gone_tickers),
        })
    finally:
        con.close()


@admin_router.get('/parent_mapping_health')
def api_admin_parent_health():
    """D4: Check parent mapping health — orphaned CIKs, unmatched managers."""
    con = _get_db()
    try:
        orphaned = con.execute(
            f""  # nosec B608
            f"""
            SELECT cik, manager_name, manager_type,
                   SUM(market_value_live) as total_value
            FROM holdings_v2
            WHERE quarter = '{LQ}' AND inst_parent_name IS NULL
            GROUP BY cik, manager_name, manager_type
            ORDER BY total_value DESC NULLS LAST
            LIMIT 20
            """
        ).fetchdf()
        top_parents = con.execute(
            f""  # nosec B608
            f"""
            SELECT COALESCE(rollup_name, inst_parent_name) as inst_parent_name, COUNT(DISTINCT cik) as child_ciks,
                   SUM(market_value_live) as total_value
            FROM holdings_v2 WHERE quarter = '{LQ}' AND COALESCE(rollup_name, inst_parent_name) IS NOT NULL
            GROUP BY COALESCE(rollup_name, inst_parent_name)
            ORDER BY total_value DESC NULLS LAST LIMIT 20
            """
        ).fetchdf()
        return clean_for_json({
            'orphaned_managers': df_to_records(orphaned),
            'top_parents': df_to_records(top_parents),
        })
    finally:
        con.close()


@admin_router.get('/stale_data')
def api_admin_stale_data():
    """D5: Flag stale data — old market data, inactive managers."""
    con = _get_db()
    try:
        result = {}
        try:
            stale_market = con.execute("""
                SELECT ticker, fetch_date, price_live
                FROM market_data
                WHERE fetch_date < CURRENT_DATE - INTERVAL '30' DAY
                ORDER BY fetch_date ASC LIMIT 20
            """).fetchdf()
            result['stale_market_data'] = df_to_records(stale_market)
        except Exception as e:  # pylint: disable=broad-except
            log.debug("stale_market: %s", e)
            result['stale_market_data'] = []
        try:
            inactive = con.execute(
                f""  # nosec B608
                f"""
                SELECT cik, manager_name, MAX(quarter) as last_quarter
                FROM holdings_v2
                GROUP BY cik, manager_name
                HAVING MAX(quarter) < '{PQ}'
                ORDER BY last_quarter DESC LIMIT 20
                """
            ).fetchdf()
            result['inactive_managers'] = df_to_records(inactive)
        except Exception as e:  # pylint: disable=broad-except
            log.debug("inactive_mgrs: %s", e)
            result['inactive_managers'] = []
        return clean_for_json(result)
    finally:
        con.close()


@admin_router.get('/merger_signals')
def api_admin_merger_signals():
    """D6: Detect potential mergers — CIK disappears + another CIK's holdings jump."""
    con = _get_db()
    try:
        signals = con.execute(
            f""  # nosec B608
            f"""
            WITH gone AS (
                SELECT cik, manager_name, SUM(market_value_usd) as prev_value
                FROM holdings_v2 WHERE quarter = '{PREV_QUARTER}'
                  AND cik NOT IN (SELECT DISTINCT cik FROM holdings_v2 WHERE quarter = '{LATEST_QUARTER}')
                GROUP BY cik, manager_name
                HAVING SUM(market_value_usd) > 1000000
            )
            SELECT * FROM gone ORDER BY prev_value DESC LIMIT 20
            """
        ).fetchdf()
        return clean_for_json({
            'potential_mergers': df_to_records(signals),
        })
    finally:
        con.close()


@admin_router.get('/new_companies')
def api_admin_new_companies():
    """D7: New companies with institutional interest — recent entries."""
    con = _get_db()
    try:
        new_cos = con.execute(
            f""  # nosec B608
            f"""
            SELECT h.ticker, MAX(h.issuer_name) as company,
                   COUNT(DISTINCT h.cik) as holder_count,
                   SUM(h.market_value_live) as total_value,
                   MAX(m.sector) as sector
            FROM holdings_v2 h
            LEFT JOIN market_data m ON h.ticker = m.ticker
            WHERE h.quarter = '{LATEST_QUARTER}' AND h.ticker IS NOT NULL
              AND h.ticker NOT IN (
                  SELECT DISTINCT ticker FROM holdings_v2
                  WHERE quarter = '{PREV_QUARTER}' AND ticker IS NOT NULL
              )
            GROUP BY h.ticker
            HAVING SUM(h.market_value_live) > 10000000
            ORDER BY total_value DESC LIMIT 30
            """
        ).fetchdf()
        return clean_for_json({
            'new_companies': df_to_records(new_cos),
        })
    finally:
        con.close()


@admin_router.get('/data_quality')
def api_admin_data_quality():
    """F6: Data quality metrics — coverage, parse rates, gaps."""
    con = _get_db()
    try:
        result = {}
        try:
            r = con.execute(
                f""  # nosec B608
                f"""
                SELECT
                    COUNT(*) as total,
                    COUNT(ticker) as with_ticker,
                    COUNT(market_value_live) as with_live_value,
                    COUNT(pct_of_so) as with_so_pct
                FROM holdings_v2 WHERE quarter = '{LQ}'
                """
            ).fetchone()
            result['holdings'] = {
                'total': r[0], 'with_ticker': r[1],
                'with_live_value': r[2], 'with_so_pct': r[3],
                'ticker_pct': round(r[1] / r[0] * 100, 1) if r[0] else 0,
                'live_value_pct': round(r[2] / r[0] * 100, 1) if r[0] else 0,
            }
        except Exception as e:  # pylint: disable=broad-except
            log.debug("dq_holdings: %s", e)
            result['holdings'] = {}
        try:
            r = con.execute("""
                SELECT COUNT(*) as total,
                    COUNT(pct_owned) as with_pct,
                    COUNT(shares_owned) as with_shares,
                    COUNT(CASE WHEN filer_name IS NULL OR filer_name = ''
                               OR regexp_matches(filer_name, '^\\d{7,10}$') THEN 1 END) as unknown_filers
                FROM beneficial_ownership_v2
            """).fetchone()
            bo_stats = {
                'total': r[0], 'with_pct': r[1], 'with_shares': r[2],
                'unknown_filers': r[3],
                'pct_coverage': round(r[1] / r[0] * 100, 1) if r[0] else 0,
            }
            try:
                nr = con.execute("""
                    SELECT COUNT(CASE WHEN name_resolved THEN 1 END) as resolved,
                           COUNT(CASE WHEN NOT name_resolved OR name_resolved IS NULL THEN 1 END) as unresolved
                    FROM beneficial_ownership_v2
                """).fetchone()
                bo_stats['name_resolved'] = nr[0]
                bo_stats['name_unresolved'] = nr[1]
                bo_stats['name_resolution_pct'] = round(nr[0] / (nr[0] + nr[1]) * 100, 1) if (nr[0] + nr[1]) else 0
            except Exception as e:  # pylint: disable=broad-except
                log.debug("dq_bo_name: %s", e)
            result['beneficial_ownership'] = bo_stats
        except Exception as e:  # pylint: disable=broad-except
            log.debug("dq_bo: %s", e)
            result['beneficial_ownership'] = {}
        error_file = os.path.join(BASE_DIR, 'logs', 'fetch_13dg_errors.csv')
        try:
            with open(error_file, encoding='utf-8') as f:
                error_count = sum(1 for _ in f) - 1
            result['fetch_errors'] = error_count
        except FileNotFoundError:
            result['fetch_errors'] = 0
        return result
    finally:
        con.close()


@admin_router.get('/staging_preview')
def api_admin_staging_preview():
    """F5: Preview what merge_staging would do (dry-run)."""
    script_path = os.path.join(BASE_DIR, 'scripts', 'merge_staging.py')
    try:
        result = subprocess.run(  # nosec  # bandit B607 + B603
            ['python3', script_path, '--all', '--dry-run'],
            capture_output=True, text=True, timeout=30, cwd=BASE_DIR, check=False,
        )
        return {
            'output': result.stdout,
            'error': result.stderr if result.returncode != 0 else None,
            'returncode': result.returncode,
        }
    except subprocess.TimeoutExpired:
        return JSONResponse(status_code=504, content={'error': 'Preview timed out after 30s'})
    except Exception as e:  # pylint: disable=broad-except
        return JSONResponse(status_code=500, content={'error': str(e)})


@admin_router.get('/running')
def api_admin_running():
    """List currently running pipeline scripts."""
    running = []
    for script in ['fetch_13dg.py', 'fetch_nport.py', 'fetch_market.py',
                   'fetch_finra_short.py', 'compute_flows.py', 'merge_staging.py']:
        try:
            ps = subprocess.run(['pgrep', '-f', script], capture_output=True, text=True, check=False)  # nosec  # bandit B607 + B603
            if ps.returncode == 0:
                pids = ps.stdout.strip().split('\n')
                running.append({'script': script, 'pids': pids})
        except Exception as e:  # pylint: disable=broad-except
            log.debug("running pgrep: %s", e)
    return {'running': running}


# ---------------------------------------------------------------------------
# Entity MDM — Priority 6 manual override endpoint (Phase 1)
# ---------------------------------------------------------------------------


@admin_router.post('/entity_override')
def api_admin_entity_override(request: Request, body: bytes = Body(default=b''), target: str = 'staging'):  # pylint: disable=too-many-locals,too-many-branches,too-many-statements
    target = (target or 'staging').lower()
    if target != 'staging':
        return JSONResponse(
            status_code=403,
            content={
                'error': 'entity_override against production is blocked until Phase 4 authorization',
                'target': target,
            },
        )

    # Accept either raw CSV body (text/csv) or JSON {"csv": "..."}
    content_type = request.headers.get('content-type', '')
    if 'application/json' in content_type:
        try:
            import json as _json  # pylint: disable=import-outside-toplevel
            parsed = _json.loads(body or b'{}')
            csv_text = parsed.get('csv', '') if isinstance(parsed, dict) else ''
        except Exception:  # pylint: disable=broad-except
            csv_text = ''
    else:
        csv_text = (body or b'').decode('utf-8', errors='replace')

    if not csv_text.strip():
        return JSONResponse(status_code=400, content={'error': 'empty CSV body'})

    reader = _csv.DictReader(_io.StringIO(csv_text))
    required = {'entity_id', 'action', 'field', 'old_value', 'new_value', 'reason', 'analyst'}
    if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
        return JSONResponse(
            status_code=400,
            content={
                'error': 'CSV must contain columns: ' + ','.join(sorted(required)),
                'received': reader.fieldnames,
            },
        )

    staging_path = os.path.join(BASE_DIR, 'data', '13f_staging.duckdb')
    if not os.path.exists(staging_path):
        return JSONResponse(status_code=500, content={'error': f'staging DB not found: {staging_path}'})

    log_path = os.path.join(BASE_DIR, 'logs', 'entity_overrides.log')
    applied, skipped = [], []
    con = duckdb.connect(staging_path, read_only=False)
    try:
        for row_num, row in enumerate(reader, start=2):  # row 1 is header
            try:
                entity_id = int(row['entity_id'])
                action = (row['action'] or '').strip().lower()
                field = (row['field'] or '').strip().lower()
                old_value = row['old_value']
                new_value = row['new_value']
                reason = row['reason'] or ''
                analyst = row['analyst'] or ''

                exists = con.execute(
                    "SELECT 1 FROM entities WHERE entity_id = ?", [entity_id]
                ).fetchone()
                if not exists:
                    skipped.append({'row': row_num, 'reason': f'entity_id {entity_id} not found'})
                    continue

                if action == 'reclassify':
                    con.execute("BEGIN TRANSACTION")
                    try:
                        con.execute(
                            """UPDATE entity_classification_history
                               SET valid_to = CURRENT_DATE
                               WHERE entity_id = ? AND valid_to = DATE '9999-12-31'""",
                            [entity_id],
                        )
                        if field == 'classification':
                            con.execute(
                                """INSERT INTO entity_classification_history
                                   (entity_id, classification, is_activist, confidence, source,
                                    is_inferred, valid_from, valid_to)
                                   VALUES (?, ?, FALSE, 'exact', 'manual', FALSE,
                                           CURRENT_DATE, DATE '9999-12-31')""",
                                [entity_id, new_value],
                            )
                        elif field == 'is_activist':
                            prior = con.execute(
                                """SELECT classification FROM entity_classification_history
                                   WHERE entity_id = ? ORDER BY valid_from DESC LIMIT 1""",
                                [entity_id],
                            ).fetchone()
                            cls = (prior[0] if prior else 'unknown')
                            con.execute(
                                """INSERT INTO entity_classification_history
                                   (entity_id, classification, is_activist, confidence, source,
                                    is_inferred, valid_from, valid_to)
                                   VALUES (?, ?, ?, 'exact', 'manual', FALSE,
                                           CURRENT_DATE, DATE '9999-12-31')""",
                                [entity_id, cls, new_value.strip().lower() in ('true', '1', 'yes')],
                            )
                        else:
                            raise ValueError(f"unsupported field for reclassify: {field}")
                        con.execute("COMMIT")
                    except Exception as e:
                        log.debug("reclassify: %s", e)
                        con.execute("ROLLBACK")
                        raise

                elif action == 'alias_add':
                    con.execute(
                        """INSERT INTO entity_aliases
                           (entity_id, alias_name, alias_type, is_preferred, preferred_key,
                            source_table, is_inferred, valid_from, valid_to)
                           VALUES (?, ?, 'brand', FALSE, NULL, 'manual', FALSE,
                                   CURRENT_DATE, DATE '9999-12-31')
                           ON CONFLICT DO NOTHING""",
                        [entity_id, new_value],
                    )

                elif action == 'merge':
                    parent_id = int(new_value)
                    parent_exists = con.execute(
                        "SELECT 1 FROM entities WHERE entity_id = ?", [parent_id]
                    ).fetchone()
                    if not parent_exists:
                        skipped.append({'row': row_num, 'reason': f'parent entity_id {parent_id} not found'})
                        continue
                    con.execute("BEGIN TRANSACTION")
                    try:
                        con.execute(
                            """UPDATE entity_rollup_history
                               SET valid_to = CURRENT_DATE
                               WHERE entity_id = ?
                                 AND rollup_type = 'economic_control_v1'
                                 AND valid_to = DATE '9999-12-31'""",
                            [entity_id],
                        )
                        con.execute(
                            """INSERT INTO entity_rollup_history
                               (entity_id, rollup_entity_id, rollup_type, rule_applied,
                                confidence, valid_from, valid_to)
                               VALUES (?, ?, 'economic_control_v1', 'manual_override',
                                       'exact', CURRENT_DATE, DATE '9999-12-31')""",
                            [entity_id, parent_id],
                        )
                        con.execute("COMMIT")
                    except Exception as e:
                        log.debug("merge: %s", e)
                        con.execute("ROLLBACK")
                        raise

                else:
                    skipped.append({'row': row_num, 'reason': f'unsupported action: {action}'})
                    continue

                # Persist override for replay after --reset rebuilds
                cik_row = con.execute(
                    """SELECT identifier_value FROM entity_identifiers
                       WHERE entity_id = ? AND identifier_type = 'cik'
                         AND valid_to = DATE '9999-12-31' LIMIT 1""",
                    [entity_id],
                ).fetchone()
                entity_cik = cik_row[0] if cik_row else str(entity_id)
                try:
                    # Assign override_id explicitly as MAX+1. Prod schema
                    # has no DEFAULT / sequence on override_id, so omitting
                    # it leaves the column NULL and the row becomes
                    # unpromotable via promote_staging's PK-based diff.
                    # Self-healing; race-safe under DuckDB single-writer.
                    new_override_id = con.execute(
                        "SELECT COALESCE(MAX(override_id), 0) + 1 "
                        "FROM entity_overrides_persistent"
                    ).fetchone()[0]
                    con.execute(
                        """INSERT INTO entity_overrides_persistent
                           (override_id, entity_cik, action, field, old_value,
                            new_value, reason, analyst)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        [new_override_id, entity_cik, action, field, old_value,
                         new_value, reason, analyst],
                    )
                except Exception as e:  # pylint: disable=broad-except
                    log.debug("persistent: %s", e)

                # Audit log append
                with open(log_path, 'a', encoding='utf-8') as f:
                    f.write(
                        f"{datetime.now().isoformat()}\tentity_id={entity_id}\taction={action}"
                        f"\tfield={field}\told={old_value}\tnew={new_value}"
                        f"\tanalyst={analyst}\treason={reason}\n"
                    )
                applied.append({'row': row_num, 'entity_id': entity_id, 'action': action})

            except Exception as e:  # pylint: disable=broad-except
                skipped.append({'row': row_num, 'reason': str(e)[:200]})
    finally:
        con.close()

    return {
        'target': target,
        'applied': applied,
        'skipped': skipped,
        'applied_count': len(applied),
        'skipped_count': len(skipped),
        'log': log_path,
    }
