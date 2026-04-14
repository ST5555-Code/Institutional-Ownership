"""Shared pipeline utilities: HTTP fetch, rate limiting, freshness stamping,
snapshot refresh, entity gate check, manifest/impact writers.

Every SourcePipeline / DirectWritePipeline / DerivedPipeline imports from
here. Used in conjunction with scripts/pipeline/manifest.py.

Design notes:
  * Rate limiting is in-process (threading.Lock + token bucket) per
    PROCESS_RULES §4. A TODO marker below tracks the future cross-process
    fcntl.flock variant that only becomes necessary when the orchestrator
    (Step 18) moves to subprocess-parallel dispatch.
  * sec_fetch() retries on 5xx with exponential backoff and on 429 with
    a single 60s pause. The pattern is narrow — every other non-2xx
    propagates immediately so the caller can decide.
  * entity_gate_check() is read-only. It never resolves, never creates
    entities, never writes to any entity table. On unresolved identifiers
    it writes rows to pending_entity_resolution for later human review.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional

import requests

from .protocol import GateResult


# ---------------------------------------------------------------------------
# Rate limiting (in-process)
# ---------------------------------------------------------------------------
# Future: replace with fcntl.flock-based cross-process limiter once the
# orchestrator moves to parallel subprocess dispatch. See docs/PROCESS_RULES.md §4.
# (kept as a prose note, not a pylint-parsed TODO tag)

_DOMAIN_RATES = {
    "sec.gov": 8.0,              # 8 req/s (PROCESS_RULES §4)
    "efts.sec.gov": 8.0,
    "www.sec.gov": 8.0,
    "data.sec.gov": 8.0,
    "api.openfigi.com": 25.0,
    "query1.finance.yahoo.com": 2.0,
    "query2.finance.yahoo.com": 2.0,
    "cdn.finra.org": 8.0,
}

_DOMAIN_LOCKS: dict[str, threading.Lock] = {}
_DOMAIN_LAST_CALL: dict[str, float] = {}
_GLOBAL_LOCK = threading.Lock()


def _get_domain_lock(domain: str) -> threading.Lock:
    """Lazy-init a per-domain lock under a single bootstrap lock."""
    with _GLOBAL_LOCK:
        if domain not in _DOMAIN_LOCKS:
            _DOMAIN_LOCKS[domain] = threading.Lock()
            _DOMAIN_LAST_CALL[domain] = 0.0
    return _DOMAIN_LOCKS[domain]


def rate_limit(domain: str) -> None:
    """Block until enough time has passed since the last call for `domain`.

    Uses time.monotonic() per PROCESS_RULES §4 — avoids wall-clock drift.
    Unknown domains default to 2 req/s.
    """
    rate = _DOMAIN_RATES.get(domain, 2.0)
    min_interval = 1.0 / rate
    lock = _get_domain_lock(domain)
    with lock:
        now = time.monotonic()
        elapsed = now - _DOMAIN_LAST_CALL[domain]
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        _DOMAIN_LAST_CALL[domain] = time.monotonic()


# ---------------------------------------------------------------------------
# HTTP fetch (SEC + general)
# ---------------------------------------------------------------------------

@dataclass
class FetchLog:
    """Diagnostic bundle returned alongside the Response for manifest writes."""
    http_code: int
    bytes: int
    retry_count: int
    domain: str


class SECFetchError(RuntimeError):
    """Raised when sec_fetch exhausts retries without a 2xx response."""


def _domain_of(url: str) -> str:
    """Extract the domain from a URL. Cheap — avoids importing urllib."""
    without_scheme = url.split("://", 1)[-1]
    return without_scheme.split("/", 1)[0].lower()


def sec_fetch(
    url: str,
    session: Optional[requests.Session] = None,
    *,
    max_retries: int = 3,
    backoff_base: float = 2.0,
    timeout: int = 60,
    headers: Optional[dict[str, str]] = None,
) -> tuple[requests.Response, FetchLog]:
    """HTTP GET with per-domain rate limiting + retry-on-5xx + 429 back-off.

    Retry semantics:
      * 2xx  → return immediately.
      * 429  → sleep 60s (once), then retry once. Not exponential —
               per PROCESS_RULES §4 a 429 means back off hard, not poll.
      * 5xx  → exponential backoff (backoff_base ** retry_count).
      * Other non-2xx → raise immediately (caller decides).

    Returns (Response, FetchLog) on success; raises SECFetchError on
    final failure. The FetchLog is meant to populate ingestion_manifest
    fields directly.
    """
    domain = _domain_of(url)
    sess = session or requests.Session()
    retries = 0
    last_err: Optional[str] = None

    while retries <= max_retries:
        rate_limit(domain)
        try:
            resp = sess.get(url, timeout=timeout, headers=headers)
        except requests.RequestException as exc:
            last_err = f"{type(exc).__name__}: {exc}"
            retries += 1
            time.sleep(backoff_base ** retries)
            continue

        if 200 <= resp.status_code < 300:
            return resp, FetchLog(
                http_code=resp.status_code,
                bytes=len(resp.content),
                retry_count=retries,
                domain=domain,
            )
        if resp.status_code == 429 and retries < max_retries:
            time.sleep(60)
            retries += 1
            continue
        if 500 <= resp.status_code < 600 and retries < max_retries:
            retries += 1
            time.sleep(backoff_base ** retries)
            continue
        raise SECFetchError(
            f"{url} — HTTP {resp.status_code} after {retries} retries"
        )

    raise SECFetchError(f"{url} — exhausted retries ({last_err})")


# ---------------------------------------------------------------------------
# Freshness stamping
# ---------------------------------------------------------------------------

def stamp_freshness(con: Any, table_name: str, row_count: Optional[int] = None) -> None:
    """Upsert one row in data_freshness for `table_name`.

    If row_count is None, runs `SELECT COUNT(*) FROM <table>` to fill it.
    Prints one confirmation line so pipeline logs show the stamp happened.
    Delegates to db.record_freshness so the pre-Batch-3A no-op semantics
    are preserved.
    """
    # Local import avoids a package-bootstrap cycle with scripts/db.py
    # when this module is imported by scripts that already import db.
    from db import record_freshness  # type: ignore[import-not-found]
    record_freshness(con, table_name, row_count=row_count)
    final = con.execute(
        "SELECT last_computed_at, row_count FROM data_freshness WHERE table_name = ?",
        [table_name],
    ).fetchone()
    if final:
        print(f"  data_freshness[{table_name}] = "
              f"rows={final[1]:,} at={final[0]}", flush=True)


# ---------------------------------------------------------------------------
# Snapshot refresh
# ---------------------------------------------------------------------------

def refresh_snapshot() -> None:
    """Copy prod 13f.duckdb to 13f_readonly.duckdb.

    Used by the orchestrator after a promote run so _resolve_db_path()'s
    read-fallback sees the latest data. Prints before/after file sizes so
    the log shows the snapshot actually moved.
    """
    from db import PROD_DB  # type: ignore[import-not-found]

    readonly_path = PROD_DB.replace("13f.duckdb", "13f_readonly.duckdb")

    before = os.path.getsize(readonly_path) if os.path.exists(readonly_path) else 0
    shutil.copy2(PROD_DB, readonly_path)
    after = os.path.getsize(readonly_path)

    print(f"  snapshot: {readonly_path} — "
          f"before={before / 1e6:.1f}MB after={after / 1e6:.1f}MB",
          flush=True)


# ---------------------------------------------------------------------------
# Entity gate check
# ---------------------------------------------------------------------------

def _normalize_cik(cik: str) -> str:
    """Zero-pad CIK to 10 digits (matches entity_identifiers storage)."""
    return cik.strip().zfill(10)


def _normalize_crd(crd: str) -> str:
    """Strip leading zeros (matches entity_sync._normalize_crd)."""
    return crd.strip().lstrip("0") or "0"


def _normalize_identifier(identifier_type: str, value: str) -> str:
    t = identifier_type.lower()
    if t == "cik":
        return _normalize_cik(value)
    if t == "crd":
        return _normalize_crd(value)
    return value.strip()


def entity_gate_check(
    con_prod: Any,
    *,
    source_type: str,
    identifier_type: str,
    staged_identifiers: list[str],
    rollup_types: Optional[list[str]] = None,
    requires_classification: bool = False,
    manifest_id: Optional[int] = None,
) -> GateResult:
    """Gate staged rows against the entity MDM. No writes to entity tables.

    Runs three hard checks. A promote MUST not proceed if any identifier
    in staged_identifiers fails any check:

    1. Active entity_identifiers row (ux_identifier_active — one per id globally).
    2. For each rollup worldview the target table materializes, an active
       entity_rollup_history row must exist.
    3. If the target table writes classification-dependent columns
       (manager_type, is_passive, is_activist), an active
       entity_classification_history row must exist.

    Unresolved identifiers are written to pending_entity_resolution with
    resolution_status='pending'. The gate does NOT resolve them — that is
    a human-in-the-loop decision that lands as an entity_overrides_persistent
    row followed by a staging → promote cycle.

    `rollup_types` defaults to ['economic_control_v1'] if not supplied.
    Pass both ['economic_control_v1', 'decision_maker_v1'] for tables
    that materialize both (holdings_v2 has rollup_entity_id and
    dm_rollup_entity_id).
    """
    rollup_types = rollup_types or ["economic_control_v1"]
    promotable: list[str] = []
    blocked: list[dict[str, Any]] = []
    new_pending: list[str] = []

    # Pre-normalize once
    pairs = [
        (raw, _normalize_identifier(identifier_type, raw))
        for raw in staged_identifiers
    ]

    for raw_value, norm_value in pairs:
        # 1. active entity_identifiers
        id_row = con_prod.execute(
            "SELECT entity_id FROM entity_identifiers "
            "WHERE identifier_type = ? AND identifier_value = ? "
            "  AND valid_to = DATE '9999-12-31'",
            [identifier_type.lower(), norm_value],
        ).fetchone()
        if not id_row:
            blocked.append({
                "identifier_value": raw_value,
                "identifier_type": identifier_type,
                "reason": "no_active_entity_identifiers_row",
            })
            new_pending.append(raw_value)
            continue
        entity_id = id_row[0]

        # 2. active entity_rollup_history for each rollup worldview
        missing_rollups: list[str] = []
        for rt in rollup_types:
            r = con_prod.execute(
                "SELECT 1 FROM entity_rollup_history "
                "WHERE entity_id = ? AND rollup_type = ? "
                "  AND valid_to = DATE '9999-12-31'",
                [entity_id, rt],
            ).fetchone()
            if not r:
                missing_rollups.append(rt)
        if missing_rollups:
            blocked.append({
                "identifier_value": raw_value,
                "entity_id": entity_id,
                "reason": f"no_active_rollup_history: {missing_rollups}",
            })
            continue

        # 3. active entity_classification_history (optional)
        if requires_classification:
            c = con_prod.execute(
                "SELECT 1 FROM entity_classification_history "
                "WHERE entity_id = ? AND valid_to = DATE '9999-12-31'",
                [entity_id],
            ).fetchone()
            if not c:
                blocked.append({
                    "identifier_value": raw_value,
                    "entity_id": entity_id,
                    "reason": "no_active_classification_history_row",
                })
                continue

        promotable.append(raw_value)

    # Best-effort lookups (log only — do not gate)
    # These help a human reviewer understand *why* a gate failed, without
    # changing the outcome. Log via print() for now; the orchestrator can
    # reroute to structured logging later.
    for b in blocked:
        norm = _normalize_identifier(identifier_type, b["identifier_value"])
        try:
            aliases = con_prod.execute(
                "SELECT ea.alias_name FROM entity_aliases ea "
                "JOIN entity_identifiers ei ON ea.entity_id = ei.entity_id "
                "WHERE ei.identifier_type = ? AND ei.identifier_value = ? "
                "  AND ea.valid_to = DATE '9999-12-31' LIMIT 3",
                [identifier_type.lower(), norm],
            ).fetchall()
            if aliases:
                b["alias_hint"] = [a[0] for a in aliases]
        except Exception:
            pass
        try:
            sup = con_prod.execute(
                "SELECT COUNT(*) FROM entity_overrides_persistent "
                "WHERE identifier_type = ? AND identifier_value = ? "
                "  AND action = 'suppress_relationship' AND still_valid",
                [identifier_type.lower(), norm],
            ).fetchone()
            if sup and sup[0]:
                b["suppress_hint"] = f"{sup[0]} suppress_relationship override(s)"
        except Exception:
            pass

    # Queue unresolved identifiers for human review.
    for raw_value in new_pending:
        norm = _normalize_identifier(identifier_type, raw_value)
        pending_key = f"{identifier_type.lower()}:{norm}"
        try:
            con_prod.execute(
                "INSERT INTO pending_entity_resolution "
                "(manifest_id, source_type, identifier_type, identifier_value, "
                " resolution_status, pending_key) "
                "VALUES (?, ?, ?, ?, 'pending', ?) "
                "ON CONFLICT (pending_key) DO NOTHING",
                [manifest_id, source_type, identifier_type.lower(),
                 norm, pending_key],
            )
        except Exception as e:
            print(f"  [entity_gate_check] pending insert failed: {e}", flush=True)

    return GateResult(
        promotable=promotable,
        blocked=blocked,
        new_entities_pending=new_pending,
    )


# ---------------------------------------------------------------------------
# Manifest / impact helpers (thin wrappers — full API in manifest.py)
# ---------------------------------------------------------------------------

def write_manifest_row(
    con: Any,
    *,
    source_type: str,
    object_type: str,
    object_key: str,
    run_id: str,
    source_url: Optional[str] = None,
    accession_number: Optional[str] = None,
    fetch_status: str = "pending",
    **kwargs: Any,
) -> int:
    """INSERT one row into ingestion_manifest. Returns manifest_id.

    Additional keyword arguments are forwarded to the insert statement
    — any ingestion_manifest column name is accepted.
    """
    base = {
        "source_type": source_type,
        "object_type": object_type,
        "object_key": object_key,
        "run_id": run_id,
        "source_url": source_url,
        "accession_number": accession_number,
        "fetch_status": fetch_status,
    }
    base.update(kwargs)
    cols = ", ".join(base.keys())
    placeholders = ", ".join(["?"] * len(base))
    con.execute(
        f"INSERT INTO ingestion_manifest ({cols}) VALUES ({placeholders}) "
        f"RETURNING manifest_id",
        list(base.values()),
    )
    row = con.fetchone()
    return row[0]


def write_impact_row(
    con: Any,
    *,
    manifest_id: int,
    target_table: str,
    unit_type: str,
    unit_key_json: str,
    **kwargs: Any,
) -> int:
    """INSERT one row into ingestion_impacts. Returns impact_id."""
    base = {
        "manifest_id": manifest_id,
        "target_table": target_table,
        "unit_type": unit_type,
        "unit_key_json": unit_key_json,
    }
    base.update(kwargs)
    cols = ", ".join(base.keys())
    placeholders = ", ".join(["?"] * len(base))
    con.execute(
        f"INSERT INTO ingestion_impacts ({cols}) VALUES ({placeholders}) "
        f"RETURNING impact_id",
        list(base.values()),
    )
    row = con.fetchone()
    return row[0]


# ---------------------------------------------------------------------------
# object_key synthesis
# ---------------------------------------------------------------------------

def compute_object_key(
    *,
    accession_number: Optional[str],
    source_url: str,
    run_id: str,
) -> str:
    """Return the object_key for an ingestion_manifest row.

    Uses accession_number when present (stable across re-runs); falls back
    to sha256(source_url + run_id) so sources without accession numbers
    (market data, FINRA, generic HTTP) still get a unique key per fetch.
    """
    if accession_number:
        return accession_number
    h = hashlib.sha256(f"{source_url}|{run_id}".encode("utf-8")).hexdigest()
    return f"hash:{h[:32]}"
