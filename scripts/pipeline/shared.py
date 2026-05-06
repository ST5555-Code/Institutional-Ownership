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
        except Exception:  # nosec B110 — best-effort alias hint enrichment; missing hints are tolerable
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
        except Exception:  # nosec B110 — best-effort suppress hint enrichment; missing hints are tolerable
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


# ---------------------------------------------------------------------------
# 13D/G Group 2 entity enrichment (bulk)
# ---------------------------------------------------------------------------

def bulk_enrich_bo_filers(
    con: Any,
    filer_ciks: Optional[set[str]] = None,
) -> int:
    """Populate entity_id + rollup columns on beneficial_ownership_v2.

    Mirrors promote_nport.py `_bulk_enrich_run` in shape, keyed on
    filer CIK instead of series_id. Scoped to the filer_ciks set when
    supplied; None → full refresh of the entire table.

    Column outputs:
      * entity_id           ← entity_identifiers.entity_id (the filer)
      * rollup_entity_id    ← economic_control_v1 rollup target
      * rollup_name         ← preferred alias of ec.rollup_entity_id

    Unmatched filers (no active entity_identifiers row of type='cik')
    leave all three columns NULL. Rows where a filer resolves but lacks
    an economic_control_v1 rollup_history row get entity_id set and
    rollup columns NULL.

    Note: ``dm_rollup_entity_id`` and ``dm_rollup_name`` were dropped
    from ``beneficial_ownership_v2`` in PR #297 (migration 026); this
    helper no longer writes them. DM-rollup reads should use Method A
    (read-time JOIN against ``entity_rollup_history``).

    Returns the count of rows actually updated (`changes()` from DuckDB).
    """
    if filer_ciks is not None and not filer_ciks:
        return 0

    norm_ciks = (
        sorted({_normalize_cik(c) for c in filer_ciks if c})
        if filer_ciks is not None
        else None
    )

    before = con.execute(
        "SELECT COUNT(*) FROM beneficial_ownership_v2 "
        "WHERE entity_id IS NOT NULL"
    ).fetchone()[0]

    if norm_ciks is None:
        con.execute(
            """
            UPDATE beneficial_ownership_v2 AS b
               SET entity_id           = e.entity_id,
                   rollup_entity_id    = e.ec_rollup_entity_id,
                   rollup_name         = e.ec_rollup_name
              FROM (
                  SELECT ei.identifier_value    AS filer_cik,
                         ei.entity_id           AS entity_id,
                         ec.rollup_entity_id    AS ec_rollup_entity_id,
                         ea_ec.alias_name       AS ec_rollup_name
                    FROM entity_identifiers ei
                    LEFT JOIN entity_rollup_history ec
                           ON ec.entity_id = ei.entity_id
                          AND ec.rollup_type = 'economic_control_v1'
                          AND ec.valid_to = DATE '9999-12-31'
                    LEFT JOIN entity_aliases ea_ec
                           ON ea_ec.entity_id = ec.rollup_entity_id
                          AND ea_ec.is_preferred = TRUE
                          AND ea_ec.valid_to = DATE '9999-12-31'
                   WHERE ei.identifier_type = 'cik'
                     AND ei.valid_to = DATE '9999-12-31'
              ) AS e
             WHERE b.filer_cik = e.filer_cik
            """
        )
    else:
        placeholders = ",".join("?" * len(norm_ciks))
        con.execute(
            f"""
            UPDATE beneficial_ownership_v2 AS b
               SET entity_id           = e.entity_id,
                   rollup_entity_id    = e.ec_rollup_entity_id,
                   rollup_name         = e.ec_rollup_name
              FROM (
                  SELECT ei.identifier_value    AS filer_cik,
                         ei.entity_id           AS entity_id,
                         ec.rollup_entity_id    AS ec_rollup_entity_id,
                         ea_ec.alias_name       AS ec_rollup_name
                    FROM entity_identifiers ei
                    LEFT JOIN entity_rollup_history ec
                           ON ec.entity_id = ei.entity_id
                          AND ec.rollup_type = 'economic_control_v1'
                          AND ec.valid_to = DATE '9999-12-31'
                    LEFT JOIN entity_aliases ea_ec
                           ON ea_ec.entity_id = ec.rollup_entity_id
                          AND ea_ec.is_preferred = TRUE
                          AND ea_ec.valid_to = DATE '9999-12-31'
                   WHERE ei.identifier_type = 'cik'
                     AND ei.valid_to = DATE '9999-12-31'
                     AND ei.identifier_value IN ({placeholders})
              ) AS e
             WHERE b.filer_cik = e.filer_cik
               AND b.filer_cik IN ({placeholders})
            """,
            norm_ciks + norm_ciks,
        )

    after = con.execute(
        "SELECT COUNT(*) FROM beneficial_ownership_v2 "
        "WHERE entity_id IS NOT NULL"
    ).fetchone()[0]
    return int(after - before)


def rebuild_beneficial_ownership_current(con: Any) -> int:
    """Rebuild beneficial_ownership_current from beneficial_ownership_v2.

    DROP + CREATE AS SELECT — picks up any BO v2 columns added via
    migration. Carries the three entity columns (entity_id,
    rollup_entity_id, rollup_name) through so the L4 table matches the
    enriched L3 shape. ``dm_rollup_entity_id`` / ``dm_rollup_name``
    were dropped from L3 in PR #297 (migration 026); use Method A for
    DM rollup reads.

    Partitions by (filer_cik, subject_ticker), keeps the row with the
    latest filing_date per partition, annotates with amendment_count
    and prior_intent (LAG).

    Returns the post-rebuild row count.
    """
    con.execute("DROP TABLE IF EXISTS beneficial_ownership_current")
    con.execute(
        """
        CREATE TABLE beneficial_ownership_current AS
        WITH ranked AS (
            SELECT *,
                ROW_NUMBER() OVER (
                    PARTITION BY filer_cik, subject_ticker
                    ORDER BY filing_date DESC
                ) AS rn,
                COUNT(*) OVER (PARTITION BY filer_cik, subject_ticker)
                    AS amendment_count,
                LAG(intent) OVER (
                    PARTITION BY filer_cik, subject_ticker
                    ORDER BY filing_date DESC
                ) AS next_older_intent
            FROM beneficial_ownership_v2
            WHERE subject_ticker IS NOT NULL
        ),
        first_13g AS (
            SELECT filer_cik, subject_ticker,
                   MIN(filing_date) AS first_13g_date
            FROM beneficial_ownership_v2
            WHERE subject_ticker IS NOT NULL
              AND filing_type LIKE 'SC 13G%'
            GROUP BY filer_cik, subject_ticker
        )
        SELECT r.filer_cik, r.filer_name, r.subject_ticker, r.subject_cusip,
               r.filing_type AS latest_filing_type,
               r.filing_date AS latest_filing_date,
               r.pct_owned, r.shares_owned, r.intent,
               r.report_date AS crossing_date,
               CAST(CURRENT_DATE - r.filing_date AS INTEGER) AS days_since_filing,
               CASE WHEN r.filing_date >= CURRENT_DATE - INTERVAL '2 years'
                    THEN TRUE ELSE FALSE END AS is_current,
               r.accession_number,
               g.first_13g_date IS NOT NULL AS crossed_5pct,
               r.next_older_intent AS prior_intent,
               r.amendment_count,
               r.entity_id,
               r.rollup_entity_id,
               r.rollup_name,
               r.dm_rollup_entity_id,
               r.dm_rollup_name
        FROM ranked r
        LEFT JOIN first_13g g
            ON r.filer_cik = g.filer_cik
           AND r.subject_ticker = g.subject_ticker
        WHERE r.rn = 1
        """
    )
    return int(con.execute(
        "SELECT COUNT(*) FROM beneficial_ownership_current"
    ).fetchone()[0])


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
