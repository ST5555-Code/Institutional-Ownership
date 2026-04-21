"""Centralized PK allocator for ingestion_manifest / ingestion_impacts.

obs-03 Phase 1 (docs/findings/obs-03-p0-findings.md §5, docs/prompts/obs-03-p1.md).
Single source of truth for allocating integer primary keys on the two
pipeline control-plane tables. Replaces the inline `_next_id` in
`manifest.py` and the deleted bypass in `shared.py`.

Public API
----------
``allocate_id(con, table, pk_col) -> int``
    Allocate one id. Used by write-once paths (`write_impact`,
    `get_or_create_manifest_row`).

``reserve_ids(con, table, pk_col, n) -> range``
    Reserve a contiguous run of `n` ids. Used by mirror paths in
    `promote_nport.py` / `promote_13dg.py` that rewrite frame PKs
    before bulk INSERT.

Both enter via an exclusive `fcntl.flock` on ``data/.ingestion_lock``
so that no two writers (even across DB files on the same host) can race
on MAX+1. The lock is advisory — DuckDB's own single-writer file lock
is the primary guarantee — but the advisory layer prevents torn
allocations in the staging→prod mirror where a single Python process
holds open two DuckDB connections at once.

Design rationale
----------------
Root cause this compensates for: DuckDB sequences do not auto-advance
when rows are INSERTed with explicit PK values. Mirror paths copy
staging-assigned PKs into prod without advancing prod's sequence, so
``nextval`` drifts arbitrarily far behind ``MAX`` until the next
DEFAULT-driven INSERT collides (findings §3, §4). MAX+1 under a lock
sidesteps sequences entirely.

Allow-list (`_ID_TABLES`) guards against typos — a wrong table name
becomes a ValueError instead of malformed SQL against the wrong table.

Logging: every allocation emits an INFO line with table, id (or range),
and PID so a post-incident grep can reconstruct exactly which process
assigned which id. Per decision #5 in the Phase 1 prompt, we intentionally
do **not** add a separate audit table yet — logging is sufficient and the
table can be bolted on later if concurrency incidents warrant it.
"""
from __future__ import annotations

import fcntl
import logging
import os
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)


# Allow-list of (table, pk_col) pairs that may be id-computed via MAX+1.
# Extending this list requires also verifying that the table's PK is a
# monotonically increasing integer with no gaps that must be preserved.
_ID_TABLES = frozenset({
    ("ingestion_manifest", "manifest_id"),
    ("ingestion_impacts", "impact_id"),
})


def _resolve_lock_path(con: Any) -> Path:
    """Return the path to the advisory lock file alongside the DB file.

    DuckDB exposes the backing file path via ``duckdb_databases()``. We
    co-locate the lock with the DB so that any host that can write to
    the DB can also write to the lock (same filesystem). In practice
    both prod (``data/13f.duckdb``) and staging (``data/13f_staging.duckdb``)
    resolve to the same ``data/.ingestion_lock`` — intentional: this
    serializes the one code path that holds both connections open at
    once (the mirror in `promote_nport.py` / `promote_13dg.py`).
    """
    row = con.execute(
        "SELECT path FROM duckdb_databases() "
        "WHERE database_name = current_database()"
    ).fetchone()
    if not row or not row[0]:
        # Fallback: pinned to repo-relative data/. This path is only
        # exercised if DuckDB ever stops exposing the DB path (hasn't
        # happened in observed versions). Keeps allocation safe rather
        # than raising.
        repo_root = Path(__file__).resolve().parents[2]
        return repo_root / "data" / ".ingestion_lock"
    return Path(row[0]).resolve().parent / ".ingestion_lock"


def _assert_allowlisted(table: str, pk_col: str) -> None:
    if (table, pk_col) not in _ID_TABLES:
        raise ValueError(
            f"id_allocator: ({table!r}, {pk_col!r}) not in allow-list; "
            f"extend _ID_TABLES if this is intentional."
        )


def _current_max_plus_one(con: Any, table: str, pk_col: str) -> int:
    row = con.execute(
        f"SELECT COALESCE(MAX({pk_col}), 0) + 1 FROM {table}"  # nosec B608
    ).fetchone()
    return int(row[0])


def allocate_id(con: Any, table: str, pk_col: str) -> int:
    """Return the next id for (table, pk_col). Caller INSERTs immediately.

    The id is ``MAX(pk_col) + 1`` on the given connection, computed under
    an exclusive file lock. The caller is expected to issue the
    corresponding ``INSERT`` on the same connection before releasing
    control; the lock is released when this function returns, so holding
    an allocated id across unrelated work is unsafe.
    """
    _assert_allowlisted(table, pk_col)
    lock_path = _resolve_lock_path(con)
    lock_fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        new_id = _current_max_plus_one(con, table, pk_col)
        logger.info(
            "id_allocator: %s.%s allocated %d (pid=%d)",
            table, pk_col, new_id, os.getpid(),
        )
        return new_id
    finally:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally:
            os.close(lock_fd)


def reserve_ids(con: Any, table: str, pk_col: str, n: int) -> range:
    """Reserve a contiguous range of `n` ids for bulk INSERT.

    Returns ``range(start, start + n)`` where ``start = MAX + 1`` at the
    moment the lock is held. Caller is responsible for rewriting the
    frame's PK column to this range before INSERT. `n=0` returns an
    empty range and performs no allocation.
    """
    _assert_allowlisted(table, pk_col)
    if n < 0:
        raise ValueError(f"id_allocator: reserve_ids n={n} must be >= 0")
    if n == 0:
        return range(0, 0)
    lock_path = _resolve_lock_path(con)
    lock_fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        start = _current_max_plus_one(con, table, pk_col)
        end = start + n
        logger.info(
            "id_allocator: %s.%s reserved %d..%d (pid=%d)",
            table, pk_col, start, end - 1, os.getpid(),
        )
        return range(start, end)
    finally:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally:
            os.close(lock_fd)
