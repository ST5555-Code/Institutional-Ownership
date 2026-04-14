"""Pipeline protocols + supporting dataclasses (v1.2).

Three structural Protocols define the contract every pipeline script
implements. They are structural (`typing.Protocol`) rather than ABCs —
implementations do not need to inherit, only to match the method
signatures. Orchestrator dispatch is by `isinstance(obj, SourcePipeline)`
with `@runtime_checkable`.

Pipeline families:
  * SourcePipeline     — EDGAR source pipelines (13F, N-PORT, 13D/G, ADV, N-CEN).
                         Full discover → fetch → parse → load → validate → promote.
  * DirectWritePipeline — Market/FINRA pipelines that upsert directly to
                         canonical reference tables (market_data, short_interest).
                         No staging DB, no entity gate (reference-only data).
  * DerivedPipeline    — L4 compute scripts (compute_flows, build_summaries,
                         build_managers). Read L3 → rebuild L4 table. No fetch.

All three end with stamp_freshness() to update data_freshness for the
FreshnessBadge in the React app.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Optional, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Supporting dataclasses
# ---------------------------------------------------------------------------

@dataclass
class DownloadTarget:
    """One thing a discover() returns — the unit of fetch-level work.

    For 13F: one quarterly bulk ZIP.
    For N-PORT: one accession_number.
    For 13D/G: one accession_number.
    For market data: a batched ticker list (object_key = sha256 of sorted
    tickers + run_id); accession_number is None.
    """
    source_type: str            # '13F' | 'NPORT' | '13DG' | 'ADV' | 'NCEN' | 'MARKET' | 'FINRA_SHORT'
    object_type: str            # 'ZIP' | 'XML' | 'PDF' | 'HTML' | 'CSV' | 'JSON'
    source_url: str
    accession_number: Optional[str] = None
    report_period: Optional[date] = None
    filing_date: Optional[date] = None
    accepted_at: Optional[datetime] = None
    is_amendment: bool = False
    prior_accession: Optional[str] = None
    # Freeform per-source bag — CIK, series_id, ticker batch, etc. Not
    # persisted; used by parse() / load_to_staging() at the next step.
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass
class FetchResult:
    """Outcome of a single fetch() call. One row in ingestion_manifest."""
    target: DownloadTarget
    manifest_id: int
    local_path: Optional[str]
    http_code: Optional[int]
    source_bytes: Optional[int]
    source_checksum: Optional[str]
    success: bool
    error_message: Optional[str] = None
    retry_count: int = 0


@dataclass
class QCFailure:
    """One parsed-row QC violation (§5b in PROCESS_RULES)."""
    field: str
    value: Any
    rule: str                   # 'pct_over_100' | 'shares_tiny' | 'shares_negative' | ...
    severity: str               # 'BLOCK' | 'FLAG' | 'WARN'


@dataclass
class ParseResult:
    """Outcome of a parse() call. Feeds load_to_staging()."""
    fetch_result: FetchResult
    rows: list[dict[str, Any]]              # parsed rows, canonical column shape
    parse_status: str                       # 'complete' | 'partial' | 'failed'
    parser_version: str
    schema_version: str
    qc_failures: list[QCFailure] = field(default_factory=list)


@dataclass
class ValidationReport:
    """Aggregate of all validation checks run against staging for one run_id."""
    run_id: str
    source_type: str
    block_count: int                        # hard blockers — promote refused
    flag_count: int                         # loud but not blocking
    warn_count: int
    pass_count: int
    report_path: Optional[str]              # logs/{run_id}/validation.json
    blocks: list[dict[str, Any]] = field(default_factory=list)
    flags: list[dict[str, Any]] = field(default_factory=list)
    warns: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class GateResult:
    """Outcome of entity_gate_check(). Passed to promote()."""
    promotable: list[str]                   # identifier_values that passed all 3 hard checks
    blocked: list[dict[str, Any]]           # [{identifier_value, reason}, ...]
    new_entities_pending: list[str]         # identifier_values queued into pending_entity_resolution


# ---------------------------------------------------------------------------
# SourcePipeline
# ---------------------------------------------------------------------------

@runtime_checkable
class SourcePipeline(Protocol):
    """EDGAR source pipeline — full discover → fetch → parse → load_to_staging
    → validate → promote cycle. Implementations: fetch_13f (rewrite as
    promote_13f), fetch_nport, fetch_13dg, fetch_adv, fetch_ncen."""

    source_type: str                        # class attribute — '13F' | 'NPORT' | ...

    def discover(self, run_id: str) -> list[DownloadTarget]:
        """Enumerate source objects not yet in ingestion_manifest.

        Reads: ingestion_manifest (anti-join to avoid refetch).
        Writes: nothing (pure read).
        Must NOT: hardcode URLs that SEC rotates yearly; bypass the
        manifest anti-join; return duplicates.
        """

    def fetch(self, target: DownloadTarget, run_id: str) -> FetchResult:
        """Download one target, write to local cache, record manifest row.

        Reads: external URL (via sec_fetch / rate_limit).
        Writes: ingestion_manifest (one new row with fetch_status='fetching'
                then 'complete'/'failed'); disk (local_path).
        Must NOT: ever retry in a tight loop on 429; batch writes in
        memory without stamping manifest per object.
        """

    def parse(self, fetch_result: FetchResult) -> ParseResult:
        """Parse one fetched artifact into row dicts; run §5b QC gates.

        Reads: local_path from disk.
        Writes: nothing (pure transform).
        Must NOT: perform cross-source joins; resolve entities; touch the DB.
        """

    def load_to_staging(self, parse_result: ParseResult,
                        staging_db_path: str, run_id: str) -> int:
        """Write parsed rows to staging DB, append ingestion_impacts row.

        Reads: parse_result.rows.
        Writes: staging DB canonical table (_v2 shape); ingestion_impacts
                (one row per (accession, unit) with load_status='loaded').
        Must NOT: write to prod DB; skip §1 per-row checkpointing at scale.

        Returns: rows written.
        """

    def validate(self, run_id: str, staging_db_path: str) -> ValidationReport:
        """Run validation suite against staged rows for this run_id.

        Reads: staging DB (freshly loaded rows for run_id).
        Writes: logs/{run_id}/validation.json; updates
                ingestion_impacts.validation_tier + validation_report.
        Must NOT: promote on WARN/FLAG alone; promote on BLOCK ever.
        """

    def promote(self, run_id: str, report: ValidationReport,
                prod_db_path: str, staging_db_path: str) -> None:
        """Move validated rows from staging to prod via entity gate check.

        Reads: ingestion_impacts WHERE run_id=? AND validation_tier IN
               ('PASS','WARN') AND promote_status='pending'; staging
               rows for those impacts; entity_current in prod.
        Writes: prod canonical table (delete_insert or upsert per
                DatasetSpec); ingestion_impacts.promote_status='promoted';
                data_freshness; pending_entity_resolution for unresolved
                identifiers.
        Must NOT: write to prod if entity_gate_check returns any hard
                block; skip the sync → diff → promote ritual for entity
                changes.
        """


# ---------------------------------------------------------------------------
# DirectWritePipeline
# ---------------------------------------------------------------------------

@runtime_checkable
class DirectWritePipeline(Protocol):
    """Market/FINRA pipelines. No staging DB — canonical reference tables
    are small and volatile (daily / weekly refresh). Implementations:
    fetch_market, fetch_finra_short."""

    source_type: str

    def discover(self, run_id: str) -> list[DownloadTarget]:
        """Enumerate stale rows (§market_data: price>7d, metadata>30d,
        shares>90d) or missing date ranges (short_interest).

        Reads: canonical target table; ingestion_manifest.
        Writes: nothing.
        """

    def fetch(self, target: DownloadTarget, run_id: str) -> FetchResult:
        """Download from Yahoo / FINRA / SEC XBRL. Write one manifest row.
        Same contract as SourcePipeline.fetch."""

    def write_to_canonical(self, fetch_result: FetchResult,
                           prod_db_path: str, run_id: str) -> int:
        """UPSERT into canonical L3 reference table directly.

        Reads: fetch_result.local_path (parsed in place — small artifacts).
        Writes: prod canonical reference (market_data, short_interest);
                ingestion_impacts (promote_status='promoted' immediately
                since there is no staging step).
        Must NOT: touch any entity table; write to market_data /
                short_interest without PK semantics (upsert per §db.py).
        """

    def validate_post_write(self, run_id: str, prod_db_path: str) -> ValidationReport:
        """Lightweight sanity checks: row count change in expected range,
        PK uniqueness, NULL rates within tolerance. Purely observational —
        no rollback (the write already happened). Severe failures log
        alerts but do not revert data."""

    def stamp_freshness(self, run_id: str, prod_db_path: str) -> None:
        """Upsert data_freshness row for the canonical table just written."""


# ---------------------------------------------------------------------------
# DerivedPipeline
# ---------------------------------------------------------------------------

@runtime_checkable
class DerivedPipeline(Protocol):
    """L4 compute pipelines. No fetch. Rebuild from L3. Implementations:
    compute_flows, build_summaries, build_managers, build_fund_classes,
    build_benchmark_weights, build_shares_history."""

    target_table: str                       # class attribute — 'investor_flows' | ...

    def check_inputs(self, prod_db_path: str) -> bool:
        """Confirm all upstream L3 inputs are present and fresh enough.

        Reads: data_freshness for input tables; row counts on L3 sources.
        Writes: nothing.
        Returns: True if safe to rebuild; False to skip.
        Must NOT: silently proceed when inputs are stale (§5 error handling).
        """

    def rebuild(self, prod_db_path: str, run_id: str) -> int:
        """Rebuild the L4 target table. Set-based SQL (§7 — one rebuild
        at end, not row-by-row).

        Reads: L3 canonical tables listed in DatasetSpec.rebuild_from.
        Writes: L4 target_table (DROP + CREATE AS for full rebuilds,
                or DELETE + INSERT per quarter for partial).
        Returns: row count written.
        Must NOT: read any L0/L1 table; read a table not listed in
                DatasetSpec.rebuild_from.
        """

    def smoke_test(self, prod_db_path: str) -> bool:
        """Run 1-2 quick sanity queries against the freshly-built table.
        E.g. `SELECT COUNT(*) > 0`, `SUM(market_value) > 0` for last quarter.
        Returns: True if smoke test passes."""

    def stamp_freshness(self, run_id: str, prod_db_path: str) -> None:
        """Upsert data_freshness row. Same contract as
        DirectWritePipeline.stamp_freshness."""
