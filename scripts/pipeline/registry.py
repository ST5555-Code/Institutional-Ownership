"""DATASET_REGISTRY — one DatasetSpec per prod DB table.

This is the single source of truth for every table in the DB. It is
consumed by:
  * scripts/db.REFERENCE_TABLES (via seed_staging fixtures)
  * scripts/merge_staging.TABLE_KEYS (via merge_table dispatch)
  * the orchestrator (Step 18) to plan the DAG of source/derived builds
  * the migration framework (D8) to scope schema changes

Adding a new table means adding a row here first. Nothing else is allowed
to define datasets outside this module.

The registry covers every table listed in `SHOW TABLES` on prod
(2026-04-13) except the auto-managed `_snapshot_*` rollback artifacts,
which are listed at the bottom with `staging_only=True` treatment and a
catch-all pattern.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class DatasetSpec:
    """Declarative description of one DB table."""
    layer: int                              # 0..4
    owner: str                              # script name (or 'migration' / 'manual')
    staging_only: bool = False              # True = staging-only work table
    promote_strategy: Optional[str] = None  # 'delete_insert' | 'upsert' | 'rebuild' | 'direct_write' | None
    promote_key: tuple[str, ...] = ()       # column names for upsert / delete_insert
    freshness_target_hours: Optional[int] = None  # SLA; None = n/a
    downstream: tuple[str, ...] = ()        # tables that depend on this one
    rebuild_from: tuple[str, ...] = ()      # only meaningful for layer=4 rebuilds
    notes: str = ""


# ---------------------------------------------------------------------------
# Control plane (L0)
# ---------------------------------------------------------------------------

DATASET_REGISTRY: dict[str, DatasetSpec] = {
    "ingestion_manifest": DatasetSpec(
        layer=0, owner="scripts/pipeline/manifest.py",
        promote_strategy="direct_write",
        notes="one row per fetched source object",
    ),
    "ingestion_impacts": DatasetSpec(
        layer=0, owner="scripts/pipeline/manifest.py",
        promote_strategy="direct_write",
        notes="one row per (manifest_id, unit_type, unit_key_json)",
    ),
    "pending_entity_resolution": DatasetSpec(
        layer=0, owner="scripts/pipeline/shared.entity_gate_check",
        promote_strategy="direct_write",
        notes="queued unresolved identifiers for human review",
    ),
    "data_freshness": DatasetSpec(
        layer=0, owner="scripts/db.record_freshness",
        promote_strategy="upsert",
        promote_key=("table_name",),
        notes="updated by every pipeline at end-of-run",
    ),
    "cusip_retry_queue": DatasetSpec(
        layer=0, owner="scripts/build_classifications.py",
        promote_strategy="direct_write",
        promote_key=("cusip",),
        notes="Queue state for OpenFIGI ticker-resolution retry pipeline. "
              "Seeded by build_classifications.py during CUSIP classification build; "
              "drained and status-updated by run_openfigi_retry.py "
              "(status: pending | resolved | unmappable). Operational queue — "
              "same L0 bucket as pending_entity_resolution. Distinct from "
              "cusip_classifications (L3 authoritative output); split is "
              "operational (queue) vs deliverable (output). Migration 003.",
    ),

    # -----------------------------------------------------------------
    # Raw (L1)
    # -----------------------------------------------------------------
    "raw_submissions": DatasetSpec(
        layer=1, owner="scripts/load_13f.py",
        promote_strategy="rebuild",
        downstream=("filings", "filings_deduped"),
    ),
    "raw_infotable": DatasetSpec(
        layer=1, owner="scripts/load_13f.py",
        promote_strategy="rebuild",
        downstream=("holdings_v2",),
    ),
    "raw_coverpage": DatasetSpec(
        layer=1, owner="scripts/load_13f.py",
        promote_strategy="rebuild",
        downstream=("filings",),
    ),

    # -----------------------------------------------------------------
    # Canonical (L3)
    # -----------------------------------------------------------------
    "holdings_v2": DatasetSpec(
        layer=3, owner="scripts/promote_13f.py (proposed)",
        promote_strategy="delete_insert",
        promote_key=("quarter", "accession_number", "cusip"),
        freshness_target_hours=24 * 90,     # quarterly + grace
        downstream=("investor_flows", "ticker_flow_stats",
                    "summary_by_parent", "summary_by_ticker", "managers",
                    "shares_outstanding_history"),
        notes="Group 3 columns enriched post-promote via enrich_holdings.py",
    ),
    "fund_holdings_v2": DatasetSpec(
        layer=3, owner="scripts/promote_nport.py (proposed)",
        promote_strategy="delete_insert",
        promote_key=("fund_cik", "report_date", "cusip"),
        freshness_target_hours=24 * 120,
        downstream=("summary_by_parent", "fund_best_index",
                    "fund_index_scores", "benchmark_weights"),
    ),
    "beneficial_ownership_v2": DatasetSpec(
        layer=3, owner="scripts/promote_13dg.py (proposed)",
        promote_strategy="upsert",
        promote_key=("accession_number",),
        freshness_target_hours=48,
        downstream=("beneficial_ownership_current",),
    ),
    "filings": DatasetSpec(
        layer=3, owner="scripts/load_13f_v2.py",
        promote_strategy="rebuild",
        downstream=("filings_deduped", "managers"),
    ),
    "filings_deduped": DatasetSpec(
        layer=3, owner="scripts/load_13f_v2.py",
        promote_strategy="rebuild",
        rebuild_from=("filings",),
    ),
    "securities": DatasetSpec(
        layer=3, owner="scripts/build_cusip.py",
        promote_strategy="rebuild",
        downstream=("holdings_v2",),
        notes="CTAS-based; DDL tracks DataFrame shape",
    ),
    "_cache_openfigi": DatasetSpec(
        layer=3, owner="scripts/build_cusip.py",
        promote_strategy="upsert",
        promote_key=("cusip",),
        notes="OpenFIGI v3 response cache (cusip, figi, ticker, exchange, "
              "security_type, market_sector, cached_at). Non-authoritative, "
              "rebuildable from source — survives re-runs. Written by "
              "build_cusip.py + run_openfigi_retry.py (migration 003). "
              "Registered at L3 to align REGISTRY with existing de-facto "
              "classification in docs/data_layers.md §2 ('L3 reference cache') "
              "and scripts/pipeline/validate_schema_parity.py L3_TABLES. "
              "A distinct 'cache' layer tag is deferred — see ROADMAP "
              "multi-db-datasetspec / future layer-vocab extension.",
    ),
    "cusip_classifications": DatasetSpec(
        layer=3, owner="scripts/build_classifications.py",
        promote_strategy="upsert",
        promote_key=("cusip",),
        downstream=("securities",),
        notes="canonical CUSIP type classification. Feeds normalize_securities.py → securities. Migration 003.",
    ),
    "market_data": DatasetSpec(
        layer=3, owner="scripts/fetch_market.py",
        promote_strategy="upsert",
        promote_key=("ticker",),
        freshness_target_hours=24 * 7,
    ),
    "short_interest": DatasetSpec(
        layer=3, owner="scripts/fetch_finra_short.py",
        promote_strategy="upsert",
        promote_key=("ticker", "report_date"),
        freshness_target_hours=48,
        notes="app reads directly at api_market.py:191 — L3 not L4",
    ),
    "fund_universe": DatasetSpec(
        layer=3, owner="scripts/fetch_nport_v2.py",
        promote_strategy="upsert",
        promote_key=("series_id",),
        downstream=("fund_holdings_v2",),
    ),
    "adv_managers": DatasetSpec(
        layer=3, owner="scripts/pipeline/load_adv.py",
        promote_strategy="rebuild",
        downstream=("entities", "cik_crd_direct", "managers"),
    ),
    "ncen_adviser_map": DatasetSpec(
        layer=3, owner="scripts/fetch_ncen.py",
        promote_strategy="rebuild",
        downstream=("entity_rollup_history",),
    ),
    "shares_outstanding_history": DatasetSpec(
        layer=3, owner="scripts/build_shares_history.py",
        promote_strategy="upsert",
        promote_key=("ticker", "as_of_date"),
    ),
    "cik_crd_direct": DatasetSpec(
        layer=3, owner="scripts/fetch_adv.py",
        promote_strategy="rebuild",
    ),
    "cik_crd_links": DatasetSpec(
        layer=3, owner="scripts/resolve_long_tail.py",
        promote_strategy="rebuild",
    ),
    "lei_reference": DatasetSpec(
        layer=3, owner="scripts/fetch_adv.py",
        promote_strategy="rebuild",
    ),
    "other_managers": DatasetSpec(
        layer=3, owner="scripts/load_13f_v2.py",
        promote_strategy="rebuild",
    ),
    "parent_bridge": DatasetSpec(
        layer=3, owner="scripts/build_entities.py (legacy evidence)",
        promote_strategy="rebuild",
        notes="retained as evidence source; do not retire",
    ),
    "fetched_tickers_13dg": DatasetSpec(
        layer=3, owner="scripts/fetch_13dg.py",
        promote_strategy="upsert",
        promote_key=("ticker",),
    ),
    "listed_filings_13dg": DatasetSpec(
        layer=3, owner="scripts/fetch_13dg.py",
        promote_strategy="upsert",
        promote_key=("accession_number",),
    ),

    # Entity MDM (L3)
    "entities": DatasetSpec(
        layer=3, owner="scripts/build_entities.py",
        promote_strategy="rebuild",
    ),
    "entity_identifiers": DatasetSpec(
        layer=3, owner="scripts/entity_sync.py + build_entities.py",
        promote_strategy="rebuild",  # SCD Type 2, rebuilt via staging workflow
    ),
    "entity_relationships": DatasetSpec(
        layer=3, owner="scripts/entity_sync.py + build_entities.py",
        promote_strategy="rebuild",
    ),
    "entity_aliases": DatasetSpec(
        layer=3, owner="scripts/entity_sync.py + build_entities.py",
        promote_strategy="rebuild",
    ),
    "entity_classification_history": DatasetSpec(
        layer=3, owner="scripts/entity_sync.py + build_entities.py",
        promote_strategy="rebuild",
    ),
    "entity_rollup_history": DatasetSpec(
        layer=3, owner="scripts/build_entities.py",
        promote_strategy="rebuild",
    ),
    "entity_overrides_persistent": DatasetSpec(
        layer=3, owner="manual CSV + scripts/entity_sync.py",
        promote_strategy="rebuild",
        notes="replayed on build_entities.py --reset",
    ),
    "entity_identifiers_staging": DatasetSpec(
        layer=3, owner="scripts/entity_sync.py",
        staging_only=True,
        promote_strategy=None,
        notes="soft-landing conflict queue",
    ),
    "entity_relationships_staging": DatasetSpec(
        layer=3, owner="scripts/entity_sync.py",
        staging_only=True,
        promote_strategy=None,
    ),

    # -----------------------------------------------------------------
    # Derived (L4)
    # -----------------------------------------------------------------
    "entity_current": DatasetSpec(
        layer=4, owner="scripts/entity_schema.sql (VIEW)",
        promote_strategy="rebuild",
        rebuild_from=(
            "entity_identifiers", "entity_relationships",
            "entity_rollup_history", "entity_classification_history",
            "entity_aliases",
        ),
        notes="user-defined VIEW — must be recreated after fixture rebuilds",
    ),
    "beneficial_ownership_current": DatasetSpec(
        layer=4, owner="scripts/fetch_13dg.py step 7",
        promote_strategy="rebuild",
        rebuild_from=("beneficial_ownership_v2",),
    ),
    "investor_flows": DatasetSpec(
        layer=4, owner="scripts/compute_flows.py",
        promote_strategy="rebuild",
        rebuild_from=("holdings_v2",),
        freshness_target_hours=24,
    ),
    "peer_rotation_flows": DatasetSpec(
        layer=4, owner="scripts/pipeline/compute_peer_rotation.py",
        promote_strategy="rebuild",
        rebuild_from=("holdings_v2", "fund_holdings_v2", "market_data"),
        notes="Precomputed entity×ticker active flows per sector. Migration 019.",
    ),
    "ticker_flow_stats": DatasetSpec(
        layer=4, owner="scripts/compute_flows.py",
        promote_strategy="rebuild",
        rebuild_from=("investor_flows",),
        freshness_target_hours=24,
    ),
    "summary_by_parent": DatasetSpec(
        layer=4, owner="scripts/build_summaries.py",
        promote_strategy="rebuild",
        rebuild_from=("holdings_v2", "fund_holdings_v2", "entity_current"),
        freshness_target_hours=24 * 37,
        notes="DDL drift vs prod — see docs/canonical_ddl.md",
    ),
    "summary_by_ticker": DatasetSpec(
        layer=4, owner="scripts/build_summaries.py",
        promote_strategy="rebuild",
        rebuild_from=("holdings_v2",),
        freshness_target_hours=24 * 37,
    ),
    "managers": DatasetSpec(
        layer=4, owner="scripts/build_managers.py",
        promote_strategy="rebuild",
        rebuild_from=("entity_current", "adv_managers", "filings_deduped"),
    ),
    "benchmark_weights": DatasetSpec(
        layer=4, owner="scripts/build_benchmark_weights.py",
        promote_strategy="rebuild",
        rebuild_from=("fund_holdings_v2", "market_data"),
    ),
    "fund_classes": DatasetSpec(
        layer=4, owner="scripts/build_fund_classes.py",
        promote_strategy="rebuild",
        rebuild_from=("fund_universe",),
    ),
    "fund_family_patterns": DatasetSpec(
        layer=4, owner="manual seed",
        promote_strategy="upsert",
        promote_key=("pattern",),
        notes="seeded once, manually edited thereafter",
    ),
    "fund_best_index": DatasetSpec(
        layer=4, owner="scripts/build_fund_classes.py",
        promote_strategy="rebuild",
    ),
    "fund_index_scores": DatasetSpec(
        layer=4, owner="scripts/build_fund_classes.py",
        promote_strategy="rebuild",
    ),
    "fund_name_map": DatasetSpec(
        layer=4, owner="scripts/build_fund_classes.py",
        promote_strategy="rebuild",
    ),
    "index_proxies": DatasetSpec(
        layer=4, owner="scripts/build_fund_classes.py",
        promote_strategy="rebuild",
    ),
    "peer_groups": DatasetSpec(
        layer=4, owner="manual seed",
        promote_strategy="rebuild",
    ),

    # -----------------------------------------------------------------
    # Retire-pending
    # -----------------------------------------------------------------
    "positions": DatasetSpec(
        layer=3, owner="scripts/unify_positions.py (RETIRE)",
        promote_strategy=None,
        notes="Decision D2 — delete. No app reads confirmed. Retire pending sweep.",
    ),
    "fund_classification": DatasetSpec(
        layer=4, owner="scripts/fix_fund_classification.py (RETIRE)",
        promote_strategy=None,
        notes="superseded by fund_best_index + fund_universe.best_index",
    ),
}


# ---------------------------------------------------------------------------
# Derived helpers — used by db.py + merge_staging.py
# ---------------------------------------------------------------------------

def reference_tables() -> list[str]:
    """Table list for db.seed_staging() — reference L3 tables only.

    Staging needs read-access copies of L3 tables that are not
    `staging_only`. The legacy REFERENCE_TABLES list in db.py hardcodes
    `holdings` and `fund_holdings` (dropped Stage 5) — callers should
    migrate to this helper.
    """
    return sorted(
        name for name, spec in DATASET_REGISTRY.items()
        if spec.layer == 3 and not spec.staging_only
    )


def merge_table_keys() -> dict[str, Optional[list[str]]]:
    """merge_staging.py TABLE_KEYS equivalent derived from the registry.

    None → DROP+CTAS full replace (rebuild).
    list → upsert by those PK columns.
    """
    out: dict[str, Optional[list[str]]] = {}
    for name, spec in DATASET_REGISTRY.items():
        if spec.staging_only:
            continue
        if spec.promote_strategy in ("upsert", "delete_insert"):
            out[name] = list(spec.promote_key) if spec.promote_key else None
        elif spec.promote_strategy == "rebuild":
            out[name] = None
        elif spec.promote_strategy == "direct_write":
            # direct-write reference tables (market_data, short_interest) use upsert
            out[name] = list(spec.promote_key) if spec.promote_key else None
        # retire-pending: omit entirely
    return out


def downstream_of(table: str) -> list[str]:
    """Return the L4 tables that rebuild from `table`."""
    out: list[str] = []
    for name, spec in DATASET_REGISTRY.items():
        if table in spec.rebuild_from:
            out.append(name)
    return out


def unclassified_tables(db_tables: list[str]) -> list[str]:
    """Given a `SHOW TABLES` result, return any table missing from the registry.

    Entity snapshot tables (`{name}_snapshot_YYYYMMDD_HHMMSS`) are
    excluded from the "missing" set because they are auto-generated
    rollback artifacts, not first-class datasets.
    """
    ignore_patterns = ("_snapshot_",)
    return sorted(
        t for t in db_tables
        if t not in DATASET_REGISTRY
        and not any(p in t for p in ignore_patterns)
    )
