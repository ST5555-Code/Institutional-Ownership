"""Database connection helpers for the Flask web app.

Split out of scripts/app.py in Phase 4 Batch 4-A. This module has no Flask
dependency — Blueprint handlers import `get_db` and `has_table` from here.

Covers:
  - DB_PATH resolution with snapshot fallback (INF13 fail-fast)
  - Read-only connection caching via thread-local storage
  - Switchback monitor thread that restores primary DB when it frees up
  - Cached table-name set for has_table() without per-request queries

Distinct from scripts/db.py — that file is the PIPELINE/STAGING write-path
utility. This file is web-layer read-only concerns only. Do not merge.
"""
from __future__ import annotations

import logging
import os
import threading as _threading
import time as _time

import duckdb

log = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# DB_PATH_OVERRIDE env var swaps in an alternate DB path (Phase 0-B2 smoke
# tests point this at the committed CI fixture). Undefined in normal use.
DB_PATH = os.environ.get('DB_PATH_OVERRIDE') or os.path.join(BASE_DIR, 'data', '13f.duckdb')
DB_SNAPSHOT_PATH = os.path.join(BASE_DIR, 'data', '13f_readonly.duckdb')

# Module-level state — guarded by _db_path_lock.
_db_path_lock = _threading.Lock()
_active_db_path: str | None = None
_switchback_running = False
_available_tables: set[str] = set()
_conn_local = _threading.local()


def _resolve_db_path() -> str:
    """Return the best available database path.

    Try the main database first (read_only=True). If it is locked by a writer
    (e.g. fetch_nport.py), fall back to a pre-existing snapshot so the web
    app can still serve data while the pipeline runs.

    INF13 (2026-04-10): The hot-path snapshot creation via `shutil.copy2`
    has been removed. A byte-level copy of a live DuckDB file can capture
    torn pages / an inconsistent WAL section — DuckDB uses a single-file
    format where writers append to the WAL portion, so a file-level copy
    taken during concurrent writes is not guaranteed consistent.

    Snapshot creation is now exclusively the job of scripts/refresh_snapshot.sh,
    which uses DuckDB's own COPY FROM DATABASE command (MVCC-safe). On a fresh
    deployment with no snapshot yet, run `scripts/refresh_snapshot.sh` once.
    """
    try:
        con = duckdb.connect(DB_PATH, read_only=True)
        con.close()
        return DB_PATH
    except Exception as e:
        log.warning("[_resolve_db_path] Main DB locked: %s", e)
        if os.path.exists(DB_SNAPSHOT_PATH):
            return DB_SNAPSHOT_PATH
        raise RuntimeError(
            f"Cannot open {DB_PATH} (locked: {e}) and no snapshot found at "
            f"{DB_SNAPSHOT_PATH}. Run `scripts/refresh_snapshot.sh` to create "
            f"one. INF13: the app no longer creates snapshots in the hot path "
            f"because a byte-level copy of a live DuckDB file can capture "
            f"torn pages."
        ) from e


def _start_switchback_monitor() -> None:
    """Background thread: check every 60s if primary DB is available again."""
    global _switchback_running  # pylint: disable=global-statement
    if _switchback_running:
        return
    _switchback_running = True

    def _monitor():
        global _active_db_path, _switchback_running  # pylint: disable=global-statement
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
                log.info("[switchback] Primary DB available — switched back from snapshot")
                _switchback_running = False
                return
            except Exception as e:
                log.debug("switchback suppress: %s", e)

    t = _threading.Thread(target=_monitor, daemon=True)
    t.start()


def _refresh_table_list() -> None:
    """Cache available table names."""
    global _available_tables  # pylint: disable=global-statement
    try:
        path = _active_db_path or _resolve_db_path()
        con = duckdb.connect(path, read_only=True)
        _available_tables = {t[0] for t in con.execute("SHOW TABLES").fetchall()}
        con.close()
    except Exception as e:
        log.debug("refresh_table_list suppress: %s", e)


def has_table(name: str) -> bool:
    """Check if a table exists (cached, no per-request query)."""
    if not _available_tables:
        _refresh_table_list()
    return name in _available_tables


def init_db_path() -> None:
    """Resolve the database path at startup.

    Call once from the app bootstrap after `app = Flask(...)`. Populates
    _active_db_path and _available_tables, and starts the switchback
    monitor if we had to fall back to the snapshot.
    """
    global _active_db_path  # pylint: disable=global-statement
    _active_db_path = _resolve_db_path()
    _refresh_table_list()
    if _active_db_path != DB_PATH:
        _start_switchback_monitor()


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

    cached = getattr(_conn_local, 'con', None)
    cached_path = getattr(_conn_local, 'path', None)
    if cached and cached_path == path:
        try:
            cached.execute("SELECT 1")
            return cached
        except Exception as e:
            log.debug("get_db cached-stale: %s", e)

    try:
        con = duckdb.connect(path, read_only=True)
        _conn_local.con = con
        _conn_local.path = path
        return con
    except Exception as e:
        log.warning("[get_db] Connection stale, re-resolving: %s", e)
        with _db_path_lock:
            _active_db_path = _resolve_db_path()
            path = _active_db_path
        _refresh_table_list()
        if path != DB_PATH:
            _start_switchback_monitor()
        return duckdb.connect(_active_db_path, read_only=True)
