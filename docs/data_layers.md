# Data Layers — Table Classification

_Revised: 2026-04-17 (session #10) — Marathon session close. **`fund_holdings_v2` at 14,090,397 rows** (147K net added during 2026-04-17 Tier C re-promote; unchanged by session #10 entity-only work). **`promote_nport.py` + `promote_13dg.py` batch rewrite shipped (`6f4fdfc`)** — per-tuple DELETE/INSERT/CHECKPOINT loop replaced with single batch operations. Pre-rewrite DERA-scale promote ran 2+ hours per run; batch path now completes in seconds. **`_mirror_manifest_and_impacts` audit-trail wipe bug fixed** at the same time — staging impact mirrors no longer overwrite prod's `promote_status='promoted'` rows, and the post-promote UPDATE's broken `unit_key_json` IN-clause (passed Python tuples where JSON strings expected) is now correctly keyed via a TEMP dataframe. Future N-PORT re-promotes no longer need the SQL audit-trail reconciliation workaround documented in §Known data caveats. `investor_flows` 17,396,524 / `ticker_flow_stats` 80,322 / `summary_by_ticker` 47,642 / `summary_by_parent` 63,916 — all data_freshness-stamped post-promote. `make freshness` ALL PASS._

_Prepared: 2026-04-13 — pipeline framework foundation (v1.2)_
_Revised: 2026-04-17 (session #11 close) — 13D/G filer resolution (commit `5efae66`): 2,591 unmatched BO v2 filer CIKs processed via `scripts/resolve_13dg_filers.py` + `data/reference/13dg_filer_research_v2.csv`. 23 MERGE + 1,640 NEW_ENTITY + 928 prod-direct exclusions. BO v2 entity coverage 77.08% → **94.52%**; BO current 73.64% → **94.51%**. `entities` 24,895 → **26,535**; `entity_identifiers` 33,392 → **35,315** open; `entity_overrides_persistent` 204 → **245**; `ncen_adviser_map` 11,106 → **11,209** (+103 from DM15b scoped fetch `9ce5b17`). Prior revision header preserved below._

_Revised: 2026-04-16 (later) — 13D/G entity linkage shipped. Migration 005 + `bulk_enrich_bo_filers()` in `pipeline/shared.py` + `scripts/enrich_13dg.py` (commit `e231633`). `beneficial_ownership_v2` now carries `rollup_entity_id` / `rollup_name` / `dm_rollup_entity_id` / `dm_rollup_name` alongside the pre-existing `entity_id`; `beneficial_ownership_current` rebuilt with all 5 entity columns. First prod full-refresh: 40,009 / 51,905 rows enriched (77.08%); 66-row drift repaired; `data_freshness('beneficial_ownership_v2_enrichment')` stamped. Remaining 11,896 rows (2,591 filer CIKs) are 13D/G long-tail individuals/corporations outside the MDM — resolution via a follow-up `resolve_13dg_filers.py`._
_Revised: 2026-04-16 — Batch 3 closed. Three deliveries this week brought all L4 tables back into a clean rebuilt state:_
_  - `enrich_holdings.py` shipped (commit `559058d`) — `holdings_v2` Group 3 fully populated (ticker / sti / mvl / pof); `fund_holdings_v2.ticker` + 1.45M; `data_freshness('holdings_v2_enrichment')` stamped._
_  - `compute_flows.py` rewrite + `build_summaries.py` rewrite + migration 004 shipped (commit `87ee955`) — both scripts now `holdings_v2`-sourced and write rollup-aware tables (EC + DM worldviews); `summary_by_parent` PK is now `(quarter, rollup_type, rollup_entity_id)`._
_  - Entity MDM expansion (commits `e4e6468`, `7770f87`, `08e2400`) — 4,141 N-PORT pending series resolved; `fund_holdings_v2` 9.32M → 11.67M; entity layer at 24,347 entities / 33,234 identifiers / 55,138 rollup rows._
_  - All 4 L4 output tables stamped fresh on `data_freshness`: `holdings_v2_enrichment`, `investor_flows`, `ticker_flow_stats`, `summary_by_parent`, `summary_by_ticker`._
_Earlier 2026-04-15 work also live: CUSIP v1.4 layer (4 new tables + 7 new `securities` columns); N-PORT DERA backfill; control-plane tables; migration 002 (`fund_universe.strategy_*`)._
_Parallel 2026-04-14 workstream (commit 831e5b4) wired `record_freshness` on 8 non-v2 scripts and drafted `scripts/migrations/add_last_refreshed_at.py` (still pending on `entity_relationships`)._

This document is the single source of truth for how every table in the
prod DB is classified across the four-layer model. Each owning script
must stay within its assigned layer. A promote script for a table whose
DDL drifts from its owner-script INSERT is blocked until the drift is
resolved (see Appendix A below).

---

## 1. Layer definitions

**L0 — Control plane.** Pipeline machinery. Records what was fetched,
what passed validation, what got promoted, what is waiting on entity
resolution, and which migrations have been applied. Small, operational,
wall-clock-timestamped. Never contains analytical data.
_Tables: `ingestion_manifest`, `ingestion_impacts`,
`pending_entity_resolution`, `data_freshness`, `cusip_retry_queue`,
`schema_versions`, `admin_preferences` (migration 016 — per-(user, pipeline) auto-approve config for the admin refresh system)._
_Pipeline writes here at every stage boundary._

**L1 — Raw.** Byte-level mirror of external source data — SEC filing
XML, FINRA CSV, Yahoo JSON — parsed into columns but otherwise
unmodified. Re-fetch is idempotent; a full re-parse must reproduce this
layer exactly. No joins, no enrichment.
_Tables: `raw_submissions`, `raw_infotable`, `raw_coverpage`, `filings`,
`filings_deduped`._

**L2 — Normalized.** Light shaping on top of raw: deduplicated, typed,
column-renamed. No cross-source joins, no entity resolution. A file that
passes L1 → L2 must be fully replayable from L1 without network access.
In practice this layer is narrow — most source pipelines skip it and
write directly to L3 staging because L2 and L3 for an accession share
keys 1:1.

**L3 — Canonical.** The authoritative fact tables the application reads.
Every row carries `entity_id` (and `rollup_entity_id` where applicable)
resolved through the entity MDM. Promote writes here are gate-protected
(see `scripts/pipeline/shared.entity_gate_check`) and go through
`staging_db → prod_db` via `sync → diff → promote`. L3 DDL changes
require a migration script; no ALTER TABLE at runtime.
_Tables: `holdings_v2`, `fund_holdings_v2`, `beneficial_ownership_v2`,
`securities`, `market_data`, `short_interest`, `fund_universe`,
`shares_outstanding_history`, `adv_managers`, `ncen_adviser_map`,
`filings`, `filings_deduped`, `cusip_classifications`, `_cache_openfigi`,
and the full entity MDM (`entities`, `entity_identifiers`,
`entity_relationships`, `entity_aliases`,
`entity_classification_history`, `entity_rollup_history`,
`entity_overrides_persistent`)._

**L4 — Derived.** Rebuilt from L3 by deterministic compute scripts. No
external fetch. Fully regenerable. Missing an L4 table never blocks a
pipeline run — it blocks only the downstream app tab.
_Tables: `beneficial_ownership_current`, `summary_by_parent`,
`summary_by_ticker`, `investor_flows`, `ticker_flow_stats`,
`managers`, `benchmark_weights`, `fund_best_index`,
`fund_index_scores`, `fund_name_map`, `index_proxies`,
`fund_classes`, `peer_groups`, `fund_family_patterns`,
`entity_current` (VIEW)._

---

## 2. Complete table inventory

Every table returned by `SHOW TABLES` on prod (counts below as of
2026-04-16) is classified. Entity `_snapshot_*` rollback artifacts from
`promote_staging.py` and `entity_*_staging` tables are grouped at the
bottom.

| Table | Layer | Owner script | Promote strategy | Notes |
|-------|-------|--------------|------------------|-------|
| `raw_submissions` | L1 | `load_13f.py` | direct_write | 13F SUBMISSION.tsv mirror; 43,358 rows |
| `raw_infotable` | L1 | `load_13f.py` | direct_write | 13F INFOTABLE.tsv mirror; 13.5M rows |
| `raw_coverpage` | L1 | `load_13f.py` | direct_write | 13F COVERPAGE.tsv mirror; 43,358 rows |
| `filings` | L3 | `fetch_13dg.py` + `load_13f.py` | upsert on accession_number | 43,358 rows; mixed 13F + 13D/G accession metadata |
| `filings_deduped` | L3 | derived from `filings` | rebuild | 40,140 rows; dedup-on-accession view materialized as table |
| `holdings_v2` | L3 | `load_13f_v2.py` (`SourcePipeline`) → `enrich_holdings.py` | append_is_latest (migration 015 added `is_latest`, `loaded_at`, `backfill_quality`) | **12,270,984 rows** (2026-04-16); canonical 13F fact table; Group 3 fully enriched (ticker 91.49% / sti 100% / mvl 77.64% / pof 61.83%) |
| `fund_holdings_v2` | L3 | `scripts/pipeline/load_nport.py` (`SourcePipeline`, w2-03; imports `fetch_dera_nport.py` + `pipeline/nport_parsers.py`) → `enrich_holdings.py --fund-holdings` | append_is_latest (migration 015 added `accession_number`, `is_latest`, `backfill_quality`) | **14,090,397 rows** (verified 2026-04-21 post-BLOCK-2 + CUSIP v1.4); 14,060 distinct series; newest `report_date` 2026-02-28 (Mar 2026 not yet on EDGAR); DERA bulk path is primary; `entity_id` coverage **84.13%** (11,854,576 / 14,090,397 non-NULL; verified 2026-04-21 SQL against prod — stable post-BLOCK-2 backfill 2026-04-17 and CUSIP v1.4 classifications promote 2026-04-15; 1,187 NULL series remain as deferred synthetics, resolution tracked in audit §10.1); maintained by `scripts/enrich_fund_holdings_v2.py` |
| `beneficial_ownership_v2` | L3 | `scripts/pipeline/load_13dg.py` (`SourcePipeline`, w2-01) → `enrich_13dg.py` (design: `docs/findings/2026-04-16-13dg-entity-linkage.md`) | append_is_latest (migration 015 added `is_latest`, `backfill_quality`) | 51,905 rows; canonical 13D/G fact table. Group 2 entity columns (`entity_id`, `rollup_entity_id`, `rollup_name`, `dm_rollup_entity_id`, `dm_rollup_name`) enriched at **94.52%** (49,059 rows; was 77.08% pre-session #11). Coverage jump from 2026-04-17 13D/G filer resolution (commit `5efae66`, +1,640 new institution entities + 23 CIK-merges to existing entities; `scripts/resolve_13dg_filers.py` + `data/reference/13dg_filer_research_v2.csv`) |
| `beneficial_ownership_current` | L4 | `promote_13dg.py` + `scripts/pipeline/shared.rebuild_beneficial_ownership_current` | rebuild | 24,756 rows; latest-per-(filer_cik, subject_ticker) with amendment logic; now carries all 5 entity columns from BO v2 (18,229 rows / 73.64% enriched) |
| `fund_universe` | L3 | `fetch_nport_v2.py` → `promote_nport.py` | upsert on series_id | **12,835 rows** (2026-04-16 part 2, +235 from Tier A+B re-promote); now includes bond / index / MM funds via DERA path. Has `strategy_narrative`, `strategy_source`, `strategy_fetched_at` (migration 002; not yet populated) |
| `securities` | L3 | `build_cusip.py` + `normalize_securities.py` | upsert on cusip | **132,618 rows** (2026-04-15); 8 CUSIP-classification columns populated (`canonical_type`, `canonical_type_source`, `is_equity`, `is_priceable`, `is_otc`, `ticker_expected`, `is_active`, `figi`). `is_otc` identifies OTC grey-market rows (Rule A ∪ Rule B, 850 priceable CUSIPs — see §6 **S1**, resolved int-13 / migration 012). Liquid-only queries compose `WHERE is_priceable AND NOT is_otc`. Formal PRIMARY KEY on `cusip` declared via migration 011 (INF28 / int-12, 2026-04-22); registered in `promote_staging.VALIDATOR_MAP` as kind `schema_pk` (engine-level enforcement). |
| `market_data` | L3 | `scripts/pipeline/load_market.py` (`SourcePipeline`, w2-02) | direct_write UPSERT on ticker | **10,064 rows** (2026-04-17, refreshed overnight 2026-04-16; stamped 2026-04-16 23:27 UTC); `make freshness` PASS post-refresh. `enrich_holdings.py --fund-holdings` re-run against fresh prices lifted `holdings_v2.market_value_live` +445K, `pct_of_so` +127K, `fund_holdings_v2.ticker` +488K. |
| `short_interest` | L3 | `fetch_finra_short.py` | upsert on (ticker, report_date) | 328,595 rows; daily FINRA short vol (app reads directly at `api_market.py:191`) |
| `shares_outstanding_history` | L3 | `build_shares_history.py` | upsert on (ticker, as_of_date) | 317,049 rows; SEC XBRL-sourced outstanding shares history |
| `adv_managers` | L3 | `scripts/pipeline/load_adv.py` (`SourcePipeline`, w2-05) | direct_write on crd (SCD Type 2 conversion deferred as follow-up) | 16,606 rows; ADV Part 1 metadata per CRD |
| `ncen_adviser_map` | L3 | `scripts/pipeline/load_ncen.py` (`SourcePipeline`, w2-04, first `scd_type2` subclass) | scd_type2 (migration 017 added `valid_from`, `valid_to`; open-row sentinel `DATE '9999-12-31'`; amendment_key `(series_id, adviser_crd, role)`) | **11,209 rows** baseline (scd_type2 now writes open-row supersede + insert instead of rebuild); series → primary/sub adviser CRD from N-CEN |
| `cik_crd_direct` | L3 | `fetch_adv.py` | rebuild | 4,059 rows; direct CIK↔CRD pairs from ADV filings |
| `cik_crd_links` | L3 | `resolve_long_tail.py` | rebuild | 448 rows; inferred CIK↔CRD links via SEC company search |
| `lei_reference` | L3 | `fetch_adv.py` | rebuild | 13,143 rows; GLEIF LEI → legal name reference |
| `other_managers` | L3 | `load_13f.py` | rebuild | 15,405 rows; other-manager references from 13F coverpage |
| `parent_bridge` | L3 | `build_entities.py` legacy | rebuild | 11,135 rows; legacy keyword-match parent bridge — retained as evidence source, superseded by ADV/N-CEN |
| `fetched_tickers_13dg` | L3 | `fetch_13dg.py` | upsert on ticker | 6,075 rows; ticker-level fetch progress marker |
| `listed_filings_13dg` | L3 | `fetch_13dg.py` | upsert on accession | 60,247 rows; EDGAR 13D/G accession index |
| `entities` | L3 | `build_entities.py` | staging→promote | **24,632 rows** (2026-04-16 part 2, +285 = 279 fund + 6 institution via Tier A+B resolver); entity MDM root |
| `entity_identifiers` | L3 | `build_entities.py` + `entity_sync.py` | staging→promote (SCD) | **35,315 active rows** (2026-04-17 session #11 close; +1,663 from 13D/G filer resolution — 1,640 new CIK identifiers on NEW_ENTITY creates + 23 CIK merges to existing entities). `entities` table count: **26,535** (+1,640 NEW_ENTITY institutions from 13D/G research; was 24,895). CIK/CRD/SERIES_ID bridge |
| `entity_relationships` | L3 | `build_entities.py` + `entity_sync.py` | staging→promote (SCD) | **18,111 rows** (2026-04-17, +6 name_inference `wholly_owned`/`parent_brand` edges via DM14b — Manulife/FIAM/Principal/Davis/PGIM/Cohen & Steers); graph with `is_primary` parent flag; `last_refreshed_at TIMESTAMP` column live since 2026-04-16 (migration `add_last_refreshed_at.py`, 13,685 / 17,826 = 76.77% backfilled from `created_at`; remaining NULLs fill organically on next N-CEN / ADV refresh) |
| `entity_aliases` | L3 | `build_entities.py` + `entity_sync.py` | staging→promote (SCD) | **24,968 rows** (2026-04-16 part 2, +285); name variants with type + preferred |
| `entity_classification_history` | L3 | `build_entities.py` + `entity_sync.py` | staging→promote (SCD) | **24,675 rows** (2026-04-16 part 2, +285) |
| `entity_rollup_history` | L3 | `build_entities.py` step 7 | staging→promote (SCD) | **55,930 rows** (2026-04-17; DM14b added 91 new `manual_override` rows on top of 91 SCD-closed rows; INF23 added 4 `merged_into` + 4 source SCD closes; DM15 Layer 1 added 15 new rows on top of 15 closed); both rollup_type worldviews × ~24.6K entities ≈ 49.3K active, plus closed history rows |
| `entity_overrides_persistent` | L3 | manual via CSV / `entity_sync.py` | staging→promote | **245 rows** (2026-04-17 session #11 close). Cumulative trail: 47 → 198 (DM13/14/14b/15 L1 + INF23) → 204 (DM14c + Amundi/Victory session #10) → 221 (+17 DM15 Layer 2, IDs 205-221) → 245 (+24 DM15c Amundi SA geo reroutes, IDs 222-245, all cik-keyed). Schema hardened by migrations **006** (`override_id_seq` + DEFAULT `nextval` + NOT NULL) and **007** (`new_value` DROP NOT NULL — unblocks overrides targeting CIK-less entities, INF9d precedent). Replayed on `build_entities.py --reset`. |
| `entity_identifiers_staging` | L3 (staging-only) | `entity_sync.py` | staging_only | 3,503 rows; conflict soft-landing queue |
| `entity_relationships_staging` | L3 (staging-only) | `entity_sync.py` | staging_only | 0 rows (INF1 framework live) |
| `entity_current` | L4 (VIEW) | `entity_schema.sql` | rebuild (view) | VIEW over entity_identifiers JOIN entity_relationships JOIN entity_rollup_history — open rows only |
| `summary_by_parent` | L4 | `build_summaries.py` (rewritten 2026-04-16, commit `87ee955`) | rebuild per (quarter, rollup_type) | **63,916 rows** (2026-04-16, last_run 06:41:31 UTC); 4 quarters × 2 worldviews × ~8K rollups; PK now `(quarter, rollup_type, rollup_entity_id)` per migration 004 |
| `summary_by_ticker` | L4 | `build_summaries.py` (rewritten 2026-04-16, commit `87ee955`) | rebuild per quarter | **47,642 rows** (2026-04-16, last_run 06:41:31 UTC); 4 quarters × ~12K distinct tickers; rollup-agnostic |
| `investor_flows` | L4 | `compute_flows.py` (rewritten 2026-04-16, commit `87ee955`) | rebuild per (period, rollup_type) | **17,396,524 rows** (2026-04-16, last_run 06:21:29 UTC); 4 periods × 2 worldviews; 8.70M EC + 8.70M DM (identical because for 13F filings the rollups coincide for ~all entities) |
| `ticker_flow_stats` | L4 | `compute_flows.py` (rewritten 2026-04-16, commit `87ee955`) | rebuild per (period, rollup_type) | **80,322 rows** (2026-04-16, last_run 06:21:29 UTC); 40,161 × 2 worldviews |
| `managers` | L4 | `build_managers.py` | rebuild | 12,005 rows; rebuilt from `entity_current` + `adv_managers` (decision D1 — keep, do not retire yet) |
| `fund_classes` | L4 | `build_fund_classes.py` | rebuild | 31,056 rows; fund class → series mapping |
| `fund_family_patterns` | L4 | `migrate_batch_3a.py` | seeded once, manual edits | 83 rows; N-PORT fund-family regex patterns (ARCH-3A) |
| `fund_best_index` | L4 | `build_fund_classes.py` step 2 | rebuild | 6,151 rows; best-fit index per series |
| `fund_index_scores` | L4 | `build_fund_classes.py` step 1 | rebuild | 80,271 rows; index correlation scores |
| `fund_name_map` | L4 | `build_fund_classes.py` | rebuild | 6.23M rows; fund-name → entity_id lookup (large because includes every N-PORT row) |
| `index_proxies` | L4 | `build_fund_classes.py` | rebuild | 13,641 rows |
| `benchmark_weights` | L4 | `build_benchmark_weights.py` | rebuild | 55 rows; per-quarter US-equity sector weights from Vanguard Total Stock Market |
| `peer_groups` | L4 | manual seed | rebuild | 27 rows; sector peer-group reference |
| `data_freshness` | L0 | every pipeline at end-of-run via `db.record_freshness()` — 8 non-v2 scripts wired in commit 831e5b4 (2026-04-14); v2 SourcePipelines stamp through their promote paths; Batch 3 outputs (`enrich_holdings.py`, `compute_flows.py`, `build_summaries.py`) stamp on completion | upsert on table_name | **9 rows** on prod (2026-04-16) — includes `holdings_v2_enrichment`, `investor_flows`, `ticker_flow_stats`, `summary_by_parent`, `summary_by_ticker`, `fund_holdings_v2`, `fund_universe`, `beneficial_ownership_v2`, `beneficial_ownership_current`; `scripts/check_freshness.py` is the gate + `make freshness` reads it |
| `ingestion_manifest` | L0 | `scripts/pipeline/manifest.py` | direct_write | **21,253 rows** (2026-04-16) — live since migration 001 (Batch 1). DERA_ZIP and per-accession keys for N-PORT |
| `ingestion_impacts` | L0 | `scripts/pipeline/manifest.py` | direct_write | **21,245 rows** (2026-04-16) — one per promoted `(series_id, report_month)` tuple plus per-quarter DERA ZIP impacts |
| `pending_entity_resolution` | L0 | `scripts/pipeline/shared.entity_gate_check()` + `validate_nport_subset.py` + `resolve_pending_series.py` + `resolve_13dg_filers.py --prod-exclusions` | direct_write | **6,874 rows** (2026-04-17 session #11 close). Breakdown: `13DG` source_type — 921 `excluded_individual` + 2 `excluded_law_firm` + 5 `excluded_other` + 3 legacy `pending` (from session #2); `NPORT` source_type — 4,420 `resolved` / 1,523 `pending`. 13D/G exclusions landed via new `resolve_13dg_filers.py --prod-exclusions` flag (commit `5efae66`, prod-direct because table is not in `db.ENTITY_TABLES` scope). Separate from the 2,591 13D/G-only filer CIKs that were resolved via MERGE/NEW_ENTITY into the MDM |
| `cusip_classifications` | L3 | `build_classifications.py` + `run_openfigi_retry.py` | upsert on cusip | **132,618 rows** (migration 003, prod promoted 2026-04-15) — canonical_type, is_equity, is_priceable, `is_otc` (migration 012, int-13 / INF29), ticker_expected, OpenFIGI metadata. Feeds `normalize_securities.py`. Residual coverage gap: ~81 malformed CUSIPs from upstream ingest + legitimately-new CUSIPs in future ingestion — see ROADMAP **INF27** and `2026-04-18-block-ticker-backfill.md §10.1`. VALIDATOR_MAP registration pending — see ROADMAP **INF28**. |
| `cusip_retry_queue` | L0 | `build_classifications.py` + `run_openfigi_retry.py` | direct_write | **37,925 rows** — 15,807 resolved via OpenFIGI, 22,118 unmappable (private / delisted / exotic); status = pending \| resolved \| unmappable |
| `_cache_openfigi` | L3 (reference cache) | `run_openfigi_retry.py` | upsert on cusip | **15,807 rows** — full v3 response per CUSIP (figi, ticker, exchange, security_type, market_sector). Durable cache; survives re-runs |
| `schema_versions` | L0 | migration scripts (001–017) | direct_write | Stamps through migration 017. Newly stamped under Phase 2 + Wave 2: **015** `amendment_semantics` (is_latest / loaded_at / backfill_quality on 3 amendable tables); **016** `admin_preferences`; **017** `ncen_scd_columns` (valid_from / valid_to on `ncen_adviser_map`). |
| `admin_preferences` | L0 | admin refresh endpoints in `scripts/admin_bp.py` | direct_write | Migration 016. `(user_id, pipeline_name) PK`; `auto_approve_enabled BOOLEAN DEFAULT FALSE`; `auto_approve_conditions JSON` (e.g., `{"max_anomalies":0,"within_expected_range":true}`). Consumed at diff-review time to decide whether to transition `validating → approved` without human click. |
| `positions` | **RETIRE** | `unify_positions.py` (RETIRE) | — | 18.68M rows; legacy combined-positions table. Decision D2: delete. No app reads confirmed (only `unify_positions.py` self-reads). Not retired this session — documented only. |
| `fund_classification` | **RETIRE** | `fix_fund_classification.py` (RETIRE) | — | 5,717 rows; superseded by `fund_best_index` + `fund_universe.best_index`. Decision: fold into `fund_universe`; only one script reads it — `fix_fund_classification.py` (itself RETIRE). |
| `entities_snapshot_*` (16 tables) | L3 rollback artifact | `promote_staging.py` | auto-created | Intra-DB promotion snapshots. Retention policy is **D7 (open decision)**. |
| `entity_aliases_snapshot_*` (16) | L3 rollback artifact | `promote_staging.py` | — | — |
| `entity_classification_history_snapshot_*` (16) | L3 rollback artifact | `promote_staging.py` | — | — |
| `entity_identifiers_snapshot_*` (16) | L3 rollback artifact | `promote_staging.py` | — | — |
| `entity_identifiers_staging_snapshot_*` (16) | L3 rollback artifact | `promote_staging.py` | — | — |
| `entity_overrides_persistent_snapshot_*` (6) | L3 rollback artifact | `promote_staging.py` | — | — |
| `entity_relationships_snapshot_*` (16) | L3 rollback artifact | `promote_staging.py` | — | — |
| `entity_relationships_staging_snapshot_*` (16) | L3 rollback artifact | `promote_staging.py` | — | — |
| `entity_rollup_history_snapshot_*` (16) | L3 rollback artifact | `promote_staging.py` | — | — |

**Unclassified — none.** Every prod table is assigned a layer.

### ADV managers

> **Ownership boundary (P2-FU-04).** `scripts/pipeline/load_adv.py` (`LoadADVPipeline`) owns `adv_managers` only — writes via `direct_write` on `(crd,)` natural key. It does **not** manage `cik_crd_direct` or `lei_reference`. Those two reference tables stay under `scripts/build_managers.py`. Rationale: `cik_crd_direct` and `lei_reference` are identity-resolution artifacts built from multiple sources (ADV is one input among several), and their lifecycle is driven by the entity build pipeline rather than the ADV fetch cadence. Revisit if a downstream consumer needs ADV-cadence freshness on either table.

---

## 3. Column ownership — `holdings_v2`

Prod DDL (2026-04-13):

```sql
CREATE TABLE holdings_v2(
    accession_number VARCHAR, cik VARCHAR, manager_name VARCHAR,
    crd_number VARCHAR, inst_parent_name VARCHAR, "quarter" VARCHAR,
    report_date VARCHAR, cusip VARCHAR, ticker VARCHAR, issuer_name VARCHAR,
    security_type VARCHAR, market_value_usd BIGINT, shares BIGINT,
    pct_of_portfolio DOUBLE, pct_of_so DOUBLE, manager_type VARCHAR,
    is_passive BOOLEAN, is_activist BOOLEAN, discretion VARCHAR,
    vote_sole BIGINT, vote_shared BIGINT, vote_none BIGINT,
    put_call VARCHAR, market_value_live DOUBLE,
    security_type_inferred VARCHAR, fund_name VARCHAR,
    classification_source VARCHAR, entity_id BIGINT,
    rollup_entity_id BIGINT, rollup_name VARCHAR, entity_type VARCHAR,
    dm_rollup_entity_id BIGINT, dm_rollup_name VARCHAR
);
```

### Group 1 — Core 13F facts (owner: `promote_13f.py` [proposed], NOT NULL)

Written at promote time, sourced directly from the SEC filing. These are
the irreducible facts that define a 13F holding.

- `accession_number` — SEC accession (PK component with cusip)
- `cik` — filer CIK (zero-padded 10-digit)
- `manager_name` — coverpage-reported manager name
- `crd_number` — filer CRD if resolvable at promote time
- `inst_parent_name` — pre-rollup parent label (legacy; kept for app compatibility)
- `quarter` — `YYYYQN`
- `report_date` — filing report period
- `cusip` — CUSIP9
- `issuer_name` — infotable NAMEOFISSUER
- `security_type` — SSHPRNAMTTYPE
- `shares` — SSHPRNAMT
- `market_value_usd` — VALUE × 1000 (13F amounts are in thousands)
- `pct_of_portfolio` — `market_value_usd / SUM(market_value_usd) PARTITION BY accession_number`
- `discretion` — INVESTMENTDISCRETION
- `vote_sole`, `vote_shared`, `vote_none` — voting authority counts
- `put_call` — PUTCALL (if option)
- `fund_name` — parsed from coverpage where present

### Group 2 — Entity enrichment (owner: `promote_13f.py` [proposed], reads `entity_current`, NOT NULL)

Resolved at promote time from the entity MDM. Promote is blocked if any
required `cik` is not present in `entity_identifiers` with an active row
— see `entity_gate_check()`.

- `entity_id` — resolved filer entity_id
- `rollup_entity_id` — economic_control_v1 rollup target
- `rollup_name` — display name of rollup target
- `dm_rollup_entity_id` — decision_maker_v1 rollup target (for sub-adviser-aware views)
- `dm_rollup_name` — display name of dm rollup target
- `entity_type` — classification from `entity_classification_history` active row
- `manager_type` — derived from `entity_type` plus activist override; canonical app-facing type column
- `is_passive`, `is_activist` — booleans derived from classification + `entity_classification_history.is_activist`
- `classification_source` — provenance of the classification (ADV, N-CEN, SIC, manual_l4, etc.)

### Group 3 — Market/reference enrichment (owner: `enrich_holdings.py`, **LIVE** since 2026-04-16, NULLABLE)

Enrichment pass that runs **after** promote — NOT at promote time
(Decision D4). Nullability guarantee: queries.py must handle every
column in this group as potentially NULL. The shipped script
(`scripts/enrich_holdings.py`, commit `559058d`) uses a cusip-keyed
lookup pattern (NOT `(accession_number, cusip)` as originally
proposed — that key is non-unique on `holdings_v2` with 1.29M dup
groups; cusip-keyed lookup is verified 1:1 across
`cusip_classifications` / `securities` / `market_data`).

D6 **resolved** (option b): full refresh every run. Per-row `mvl` /
`pof` use the OUTER row's `shares`. Run with `--quarter YYYYQN` to
scope to one quarter.

- `ticker` — resolved from `securities` by cusip when `cusip_classifications.is_equity=TRUE`. Null when CUSIP is non-equity (OPTION/BOND/CASH/WARRANT/...).
- `security_type_inferred` — pulled from `securities.security_type_inferred` (legacy domain `equity/etf/derivative/money_market`); **not** from `cusip_classifications.canonical_type` (which uses BOND/COM/OPTION/... — different domain the app's read paths don't speak).
- `market_value_live` — `shares × market_data.price_live`. Null for delisted / foreign / non-equity / missing market_data.
- `pct_of_so` — `shares × 100.0 / market_data.float_shares`. Null when float is missing (~30% of `market_data` rows lack `float_shares`).
- `pct_of_so_source` — Class B audit stamp recording which denominator tier produced `pct_of_so`: `soh_period_accurate` (ASOF on `shares_outstanding_history`), `market_data_so_latest` (fallback to latest `market_data.shares_outstanding`), or `market_data_float_latest` (last-resort fallback to latest `market_data.float_shares`). Added by migration 008 (`ea4ae99` amended) alongside the `pct_of_float` → `pct_of_so` rename; written by `enrich_holdings.py` Pass B.

Live coverage on prod (2026-04-16, post first run): ticker 91.49% (10,395,053 / 12,270,984); sti 100.00%; mvl 77.64% (9,527,773); pof 61.83% (7,587,332).

---

## 4. Column ownership — `fund_holdings_v2`

Prod DDL (2026-04-13):

```sql
CREATE TABLE fund_holdings_v2(
    fund_cik VARCHAR, fund_name VARCHAR, family_name VARCHAR,
    series_id VARCHAR, "quarter" VARCHAR, report_month VARCHAR,
    report_date DATE, cusip VARCHAR, isin VARCHAR, issuer_name VARCHAR,
    ticker VARCHAR, asset_category VARCHAR, shares_or_principal DOUBLE,
    market_value_usd DOUBLE, pct_of_nav DOUBLE, fair_value_level VARCHAR,
    is_restricted BOOLEAN, payoff_profile VARCHAR, loaded_at TIMESTAMP,
    fund_strategy VARCHAR, best_index VARCHAR, entity_id BIGINT,
    rollup_entity_id BIGINT, dm_entity_id BIGINT,
    dm_rollup_entity_id BIGINT, dm_rollup_name VARCHAR
);
```

### Group 1 — Core N-PORT facts (owner: `promote_nport.py` [proposed], NOT NULL where indicated)

- `fund_cik` — N-PORT filer CIK
- `fund_name` — N-PORT filer name
- `family_name` — funds-family label parsed from N-PORT header
- `series_id` — SEC SERIES_ID (`S000######`)
- `quarter` — `YYYYQN` — quarter the report rolls up into
- `report_month` — monthly grain the N-PORT was filed for (e.g. `2025-09`)
- `report_date` — exact period-of-report date
- `cusip` — investment CUSIP
- `isin` — investment ISIN where present
- `issuer_name` — investment NAMEOFISSUER
- `asset_category` — N-PORT assetCat
- `shares_or_principal` — balance
- `market_value_usd` — valUSD
- `pct_of_nav` — PCT of NAV
- `fair_value_level` — 1/2/3
- `is_restricted` — restricted boolean
- `payoff_profile` — derivatives payoff profile
- `loaded_at` — pipeline-set timestamp

### Group 2 — Entity + fund-strategy enrichment (owner: `promote_nport.py`, reads `entity_current` + `fund_universe`, NOT NULL for entity columns)

- `entity_id` — resolved fund filer entity_id via fund_cik
- `rollup_entity_id` — economic_control_v1 rollup target (fund sponsor)
- `dm_entity_id` — decision_maker_v1 entity per `ncen_adviser_map` sub-adviser
- `dm_rollup_entity_id` — decision_maker_v1 rollup target
- `dm_rollup_name` — display name
- `fund_strategy` — copied from `fund_universe.fund_strategy` at promote time
- `best_index` — copied from `fund_universe.best_index`

### Group 3 — Reference enrichment (owner: `enrich_holdings.py` [proposed], NULLABLE)

Same post-promote pass as `holdings_v2`.

- `ticker` — resolved from `securities` by cusip. Null for bonds, illiquid, or unlisted.

---

## 4b. Column ownership — `beneficial_ownership_v2`

Prod DDL (2026-04-16, post migration 005):

```sql
CREATE TABLE beneficial_ownership_v2(
    accession_number VARCHAR, filer_cik VARCHAR, filer_name VARCHAR,
    subject_cusip VARCHAR, subject_ticker VARCHAR, subject_name VARCHAR,
    filing_type VARCHAR, filing_date DATE, report_date DATE,
    pct_owned DOUBLE, shares_owned BIGINT, aggregate_value DOUBLE,
    intent VARCHAR, is_amendment BOOLEAN, prior_accession VARCHAR,
    purpose_text VARCHAR, group_members VARCHAR, manager_cik VARCHAR,
    loaded_at TIMESTAMP, name_resolved BOOLEAN,
    entity_id BIGINT, rollup_entity_id BIGINT, rollup_name VARCHAR,
    dm_rollup_entity_id BIGINT, dm_rollup_name VARCHAR
);
```

### Group 1 — Core 13D/G facts (owner: `fetch_13dg_v2.py` + `promote_13dg.py`, mostly NOT NULL)

Filing facts sourced from the EDGAR Schedule 13D/G filing.

- `accession_number` — SEC accession (PK)
- `filer_cik` — reporting person CIK (zero-padded 10-digit)
- `filer_name` — reporting person name
- `subject_cusip` — subject company CUSIP9
- `subject_ticker` — subject company ticker (resolved at parse time
  via `securities` lookup)
- `subject_name` — subject company name
- `filing_type` — `SC 13D`, `SC 13D/A`, `SC 13G`, `SC 13G/A`
- `filing_date`, `report_date` — filing + event dates
- `pct_owned`, `shares_owned`, `aggregate_value` — reported position
- `intent` — categorical parse (activist / passive / arbitrage / etc.)
- `is_amendment`, `prior_accession` — amendment chain
- `purpose_text` — free-text Item 4 purpose
- `group_members` — co-filer list (joint filing)
- `manager_cik` — optional manager on whose behalf the filer reports
- `loaded_at` — pipeline timestamp
- `name_resolved` — flag for downstream name resolution

### Group 2 — Entity enrichment (owner: `bulk_enrich_bo_filers` in `scripts/pipeline/shared.py`, NULLABLE for unmatched filers)

Populated at promote time (scoped to the run's filer CIKs) and
refreshable via `scripts/enrich_13dg.py` (full refresh). Resolved
through the entity MDM via `filer_cik → entity_identifiers(type='cik')`.

- `entity_id` — resolved filer `entity_id`. Legacy-populated at ~77%;
  overwritten idempotently by each enrichment pass.
- `rollup_entity_id` — `economic_control_v1` rollup target.
- `rollup_name` — preferred alias of `rollup_entity_id`.
- `dm_rollup_entity_id` — `decision_maker_v1` rollup target.
- `dm_rollup_name` — preferred alias of `dm_rollup_entity_id`.

Nullability: unmatched filers (no active `entity_identifiers` row of
type `'cik'`) leave all five columns NULL. As of 2026-04-16, 40,009 /
51,905 rows (77.08%) are enriched. The 11,896 unmatched rows span
2,591 filer CIKs — 13D/G long-tail individuals, small corporations,
and activist investors not in the 13F-centric MDM. Follow-up:
`resolve_13dg_filers.py` for placeholder entity creation.

Unlike `holdings_v2`, BO v2 does **not** carry `manager_type`,
`is_passive`, `is_activist`, `entity_type`, or `classification_source`
— Schedule 13D/G disclosures are not manager classifications.

## 5. Option B split contract

**Option B** refers to splitting the promote vs enrichment responsibilities
so the pipeline can produce a valid L3 row *without* market data being
available. Group 3 columns are the split boundary.

**Split boundary columns:**
- `holdings_v2.{ticker, security_type_inferred, market_value_live, pct_of_so}`
- `fund_holdings_v2.ticker`

**Nullability guarantee:** these columns are allowed to be NULL in
production. `queries.py` must treat them as nullable in every read path.
Grep of prod `scripts/queries.py` confirms existing code already uses
`NULLS LAST`, `SUM(... market_value_live)` which naturally tolerates
NULL, and `COUNT(CASE WHEN market_value_live IS NOT NULL ...)` probes —
so the query layer is already Option-B-compatible.

**What must be true before Option B can be safely enabled:**

1. `promote_13f.py` sets `ticker`, `market_value_live`, `pct_of_so`,
   `security_type_inferred` to NULL on insert — never joins `securities`
   or `market_data` at promote time.
2. `enrich_holdings.py` runs as a separate step, owns an UPDATE that
   rewrites these four columns in place using a join to `securities` and
   `market_data`. Idempotent; safe to re-run.
3. Every query function that reads these columns continues to work when
   the value is NULL. Current grep shows ~40 references across
   `queries.py` — none dereference `.market_value_live` without a
   SUM/NULL-tolerant aggregate, and `pct_of_so` is always SUMed or
   compared with `IS NOT NULL`. Confirmed safe.
4. `enrich_holdings.py` writes to `data_freshness` with
   `table_name='holdings_v2_enrichment'` so the FreshnessBadge can
   surface enrichment-lag separately from ingest-lag.
5. The app still works when enrichment has not yet run against a
   freshly-promoted quarter — i.e., a just-promoted quarter shows
   Register / Conviction rows with null ticker/market_value_live and the
   tab handles that cleanly (degrades gracefully, doesn't 500). Covered
   today by the app's existing `NULLS LAST` + NULL-tolerant aggregates.

**Grep evidence (market_value_live + pct_of_so in queries.py):**
~40 occurrences, all inside `SUM(...)` aggregates, `NULLS LAST` ORDER
BY, or `WHERE ... IS NOT NULL` guards. No bare-deref reads in
record-shaping code. Option B is compatible today.

---

## 6. Open decisions D5–D8, S1

These cannot be resolved without operational data from the first few
framework pipeline runs. Recorded here so the orchestrator decision at
Step 18 has a concrete list.

**ID prefix convention.** `D#` is the pre-existing open-decision
namespace (D5–D8 below) and is aligned with
`ENTITY_ARCHITECTURE.md`'s entity-MDM D## deferred-items series.
**`S#` is a new prefix introduced 2026-04-18 for securities-layer
open decisions** (columns on `securities` / `cusip_classifications` /
`market_data`), to avoid cross-scope collision with entity-MDM D##
items. New entries pick the prefix that matches their scope.

### D5 — Entity retro-enrichment when merges change historical `rollup_entity_id`

**Decision needed:** When an entity merge (e.g. NorthStar eid=6693→7693)
changes the rollup target, do we retro-stamp `rollup_entity_id` in
historical `holdings_v2` rows, or carry the mapping in `entity_current`
only and let the app resolve at read time?

**Options:** (a) batch-rebuild affected historical rows at promote time
with a JOIN to the new `entity_rollup_history` open row; (b) keep
historical rollup as written, look up via view; (c) hybrid — retro-stamp
the last 4 quarters at promote, accept drift beyond.

**Why unresolved:** We need two or three promote cycles to measure
retro-stamp cost at 12.27M row scale. Current `build_entities.py --reset`
rewrite takes minutes; on-promote retro would need to be measured.

### D6 — `market_value_live` refresh cadence for historical rows

**Decision needed:** Does `enrich_holdings.py` refresh every historical
row on every run, or only freshly-promoted rows? Historical
`market_value_live` is a snapshot at enrichment time, not point-in-time.

**Options:** (a) freshly-promoted only — historical values frozen at
first enrichment; (b) full refresh every run — current behavior implied
by `build_summaries.py` design; (c) refresh latest quarter only, freeze
rest.

**Why unresolved:** Depends on app semantics. If "market value live"
means "what is the position worth today" the app expects (b). If it
means "what was it worth at quarter-end" the app expects freeze-after-
first-enrichment. Worth an explicit product decision, not a pipeline
decision.

### D7 — Snapshot table retention policy

**Decision needed:** `{entity_table}_snapshot_{ts}` tables accumulate in
prod — 16 snapshots of each of 9 entity tables = 144 tables pending.
Retention: 7 days, 30 days, keep 3, keep until next validation run?

**Options:** (a) drop any snapshot older than 7 days when
`promote_staging.py` runs; (b) keep last 3 snapshots per table, drop the
rest; (c) keep indefinitely until manual sweep.

**Why unresolved:** Current prod has 16 snapshots × 9 entity tables
= 144. At ~20k rows each that's ~2.88M snapshot rows — negligible for
DuckDB. But count will grow with every promote. Sweep script can be
added to `promote_staging.py` once we see natural cadence over 2–4
weeks of pipeline runs.

### D8 — L3 canonical DDL migration framework

**Decision needed:** How do we add / alter columns on L3 canonical
tables going forward? `ALTER TABLE` at runtime is not acceptable. The
options are: (a) numbered migration scripts similar to this session's
`001_pipeline_control_plane.py`; (b) full CREATE-TABLE-AS with rename
swap; (c) rely on owner-script DDL with `CREATE TABLE IF NOT EXISTS`
plus column-diff additions in migrations.

**Why unresolved:** Need one real schema change to validate the chosen
approach. The `summary_by_parent` DDL drift (see Appendix A below)
is the obvious first candidate — the right fix is a migration script
that adds `rollup_entity_id`, `total_nport_aum`, `nport_coverage_pct`
columns to `build_summaries.py`'s `CREATE TABLE IF NOT EXISTS`, then a
rebuild. Once that ships, the pattern is proven.

### S1 — `is_priceable` semantic refinement for OTC grey-market rows — **DECIDED (Option C: separate `is_otc` column)**

**Resolution (int-13, migration 012):** added `is_otc BOOLEAN DEFAULT FALSE`
to both `securities` and `cusip_classifications`. `is_priceable` retains
its OpenFIGI-response-mirror semantics; OTC grey-market identity lives in
`is_otc`. Liquid-only downstream queries compose
`WHERE is_priceable AND NOT is_otc`. "All OTC regardless of priceability"
is just `WHERE is_otc`.

**Classification rules (A ∪ B; disjoint at current population):**
- **Rule A** — `UPPER(ticker)` appears in `data/reference/sec_company_tickers.csv`
  with `exchange='OTC'` (561 priceable rows, catches foreign-ADR F-suffix
  tickers whose OpenFIGI primary listing is the foreign venue — e.g.,
  RSMDF/ResMed, TCKRF/Teck, CNDIF/AngloGold).
- **Rule B** — `exchange IN ('OTC US', 'NOT LISTED')` from OpenFIGI
  (289 priceable rows, catches domestic OTC preferreds + unlisted notes).

Union: 850 priceable CUSIPs / 28,563 `holdings_v2` rows / ~$226.7 B 13-F AUM
(findings §3.4).

**Deferred (findings §6 open-questions):**
- Rule C (`canonical_type='OTHER'`, 1,097 non-priceable rows) — not applied
  in backfill; defaults to `FALSE`. Revisit if a downstream query needs
  a complete "OTC universe" tag.
- Source-of-truth: OTC ticker list is embedded as a module-level constant
  loaded from the reference CSV in `cusip_classifier.py`. Promotion to a
  `reference_otc_tickers` table deferred until a second rule needs the
  same list.

**Implementation surface:**
- Classifier: `cusip_classifier.classify_cusip()` emits `is_otc` per rule A ∪ B.
- Persistence: `build_classifications.py` writes `is_otc` into
  `cusip_classifications`; `normalize_securities.py` propagates it to
  `securities` via `SET is_otc = cc.is_otc`.
- One-shot backfill for existing rows: `scripts/oneoff/backfill_is_otc.py`
  (dry-run default, `--confirm` to write; idempotent).

---

## 7. Denormalized enrichment columns — drift risk and planned retirement

Some L3 v2 tables carry denormalized enrichment columns that answer
two very different questions. The columns look alike, but they are
semantically distinct — and only one class is safe to leave denormalized.

**Class A — filing-time facts.** Columns that answer "what did this
filer report on this date." The filing is immutable history; the
column is a stamp and should stay denormalized. Examples:
`holdings_v2.cusip`, `holdings_v2.shares`, `holdings_v2.market_value_usd`,
`fund_holdings_v2.report_date`, `fund_holdings_v2.cusip`. These never
drift.

**Class B — current-mapping lookups.** Columns that answer "what is
the current mapping for this key." The canonical source (a `securities`
row, an `entity_current` row, a GLEIF LEI record) can update after the
filing is stamped. The stamp then drifts. Examples:
`holdings_v2.ticker`, `holdings_v2.entity_id`, `holdings_v2.rollup_entity_id`,
`fund_holdings_v2.ticker`, `fund_holdings_v2.entity_id`, and (if ever
added) `lei`. These are the problem columns.

**Class B — audit-stamp variant.** A handful of Class B columns stamp
not a current mapping but the *provenance* of an adjacent column. They
still sit in the drift-risk class because the provenance is only
meaningful while the adjacent derived value was computed — a
re-enrichment can change both simultaneously. `holdings_v2.pct_of_so_source`
is the canonical example: three-tier audit over the `pct_of_so`
denominator resolution — `soh_period_accurate` (SOH ASOF lookup hit),
`market_data_so_latest` (fallback to latest `shares_outstanding`), or
`market_data_float_latest` (last-resort fallback to latest
`float_shares`). Added 2026-04-19 via migration 008 (`ea4ae99` amended)
alongside the `pct_of_float → pct_of_so` rename; written by
`enrich_holdings.py` Pass B. Carrying table: `holdings_v2`. Retirement
path: follows the `pct_of_so` column itself — if `pct_of_so` ever becomes
a read-time join, the source stamp comes along.

**Principle.** Class B columns should be joins, not stamps — resolved
at read time against the current canonical source. Class A columns stay
denormalized.

**Observed drift — now bounded by forward hooks.** The two drift
incidents below were the forcing function for this section. Both are
historical: the one-time backfills closed the gap and the forward
hooks (int-06 ticker re-stamp subprocess hooks at the end of
`build_cusip.py` and `normalize_securities.py`; the entity_id
refresh path in the staging + `enrich_holdings.py` flow) hold coverage
steady on every subsequent `securities` / `entity_current` write. No
active drift incidents since the backfills merged.
- **BLOCK-2 entity_id backfill.** `fund_holdings_v2.entity_id` coverage
  moved from 40.09% to 84.13% after a one-time backfill pass against
  `entity_current`. The gap wasn't a bug — rows were stamped against
  the entity table as it looked at promote time; later entity merges
  and NEW_ENTITY creates left historical rows pointing at entity_ids
  that no longer represent the current mapping.
- **BLOCK-TICKER-BACKFILL ticker drift.** `fund_holdings_v2.ticker`
  was ~59% populated at 2025-06 and had decayed to ~3.7% at 2025-11
  before the backfill. Same mechanism: ticker stamped against
  `securities` at promote; subsequent ticker corrections in
  `securities` never propagated back. Post-backfill coverage:
  3,935,959 → 5,154,223 rows on prod apply (`3299a9f`).

**Planned retirement sequence.** Incremental — do not retire Class B
columns in one pass. Each step narrows the exposure before the next.
Steps 1–3 are **done**; Step 4 is **deferred to Phase 2** per int-09
Phase 0 decision (2026-04-22) — see
[`docs/findings/int-09-p0-findings.md`](findings/int-09-p0-findings.md).

1. **BLOCK-TICKER-BACKFILL** *(DONE — `3299a9f`)*. One-time full
   backfill of `fund_holdings_v2.ticker`; forward-looking subprocess
   hooks at the end of `build_cusip.py` and `normalize_securities.py`
   so future `securities` updates trigger a ticker re-stamp. Keeps
   drift bounded, does not remove the column.
2. **BLOCK-3** *(DONE — `0dc0d5d`)*. Legacy `fetch_nport.py` retired;
   `build_benchmark_weights` + `build_fund_classes` repointed to
   `fund_holdings_v2`. Removes readers that would have been broken by
   a Class B column retirement.
3. **Batch 3 REWRITE queue** *(DONE — closed 2026-04-19)*. All five
   target scripts shipped and stamped their `pipeline_violations.md`
   entries clear: `build_shares_history.py` (`d7ba1c2`, prod apply
   `443e37a`), `build_summaries.py` (`3234c8a`, work already at
   `87ee955`), `compute_flows.py` (`34710d1`, work already at
   `87ee955`), `load_13f.py` Rewrite4 (`7e68cf9`, prod apply
   `a58c107`), `build_managers.py` + `backfill_manager_types.py`
   Rewrite5 (`223b4d9`, prod apply `7747af2`).
4. **BLOCK-DENORM-RETIREMENT** *(DEFERRED TO PHASE 2 — int-09
   2026-04-22)*. Drop the stamped Class B columns from v2 fact
   tables; rely on read-time joins. Tracked in ROADMAP as **INF25**.
   Deferred because the read-site footprint in `scripts/queries.py`
   (405 `ticker` + 69 `entity_id` + 6 `rollup_entity_id` references)
   is too large to rewrite as a remediation-window task, and
   `rollup_entity_id` retirement requires a dual-graph resolution
   decision (`economic_control_v1` vs `decision_maker_v1`) that is
   itself a Phase 2 design item. Drift is stabilized by the int-06
   forward hooks, so the urgency case is gone.

   **Exit criteria — Step 4 may execute when all are true:**

   1. **mig-12 complete.** `load_13f_v2` / `promote_13f.py` rewrite
      shipped and stable; all 13F writers go through the new promote
      path so no writer emits stamps into columns slated for drop.
   2. **Read-site audit tool exists** (mig-07 / INF41). Scripted
      audit that enumerates every read site of a target column across
      `queries.py`, `api_*.py`, `web/react-app/src/**/*.tsx`, and
      fixture responses.
   3. **Read-time join helpers proven.** At least one representative
      `queries.py` endpoint converted to the join pattern with parity
      tests against the legacy stamped read.
   4. **Dual-graph resolution strategy chosen** for `rollup_entity_id`
      — either (a) explicit graph selector in the API layer,
      (b) materialized column populated by a view over
      `entity_current`, or (c) a hybrid. INF25 cannot drop the column
      without picking one.
   5. **Drift gate stable for ≥2 consecutive quarters.** Forward
      hooks hold `ticker` / `entity_id` coverage steady without
      manual backfills.
   6. **INF41 rename-sweep discipline applied.** Any column removal
      goes through the same exhaustiveness tooling slated for
      renames; no ad-hoc grep-and-delete.

   Full decision record and counter-evidence review in
   [`docs/findings/int-09-p0-findings.md`](findings/int-09-p0-findings.md).

**Not in scope.** Class A columns stay as stamps. `cusip` and `shares`
on `holdings_v2` are the filing-time record and do not join anywhere.

### COALESCE preservation pattern for source-side coverage regression

When a writer is repointed from one source to another and the new
source has lower coverage than the old, COALESCE preserves historical
values while letting new-source values win where populated:

```sql
UPDATE holdings_v2 t
SET manager_type = COALESCE(src.manager_type, t.manager_type),
    inst_parent_name = COALESCE(src.inst_parent_name, t.inst_parent_name),
    is_passive = COALESCE(src.is_passive, t.is_passive),
    is_activist = COALESCE(src.is_activist, t.is_activist)
FROM (<new source>) src
WHERE t.<join key> = src.<join key>;
```

**Precedent.** Rewrite5 Phase 4 (commit `7747af2`) applied this
pattern on all four `build_managers` enrichment columns
(`manager_type`, `inst_parent_name`, `is_passive`, `is_activist`).
The new source (`managers.strategy_type` populated by
`fetch_adv.py` + hand-curated
`data/reference/categorized_institutions_funds_v2.csv`) covers only
~60% of CIKs against legacy's 100%; the 40% gap is structural
(non-ADV filers, $25T+ AUM). COALESCE preserved legacy values in
that gap, including the 14-category hand-curated taxonomy that ADV
alone cannot supply.

**Auxiliary pattern: pre-rewrite snapshot as audit artifact.** Before
the COALESCE-repoint pass writes, snapshot the legacy column set into
a dated table — e.g. `holdings_v2_manager_type_legacy_snapshot_20260419`
(Rewrite5; 12,270,984 rows, 9,121 CIKs, 13 types). The snapshot is a
full point-in-time reference and supports:

- Rollback to pre-rewrite state without data loss if the new source
  turns out to be broken.
- Diff validation after the repoint — "how many rows changed, where
  did they land, and were the changes expected."
- Long-tail audit against future ADV enrichments — compare a fresh
  pull to the snapshot to see coverage drift direction.

**When to use.**
- Source-side coverage regression is known (the legacy source had
  more rows populated than the new source will).
- Legacy provenance is defensible — the legacy data was populated by
  a trusted process, even if that process has been retired.
- Taxonomies are strictly compatible: legacy is a superset of new, or
  the merge is semantically safe (e.g., new source refines legacy
  values rather than contradicting them).

**When not to use.**
- Taxonomies conflict — same column name, different meanings (e.g.,
  `status='active'` meaning "activist investor" in legacy vs.
  "actively-managed fund" in new). COALESCE would silently produce a
  meaningless mix.
- Legacy data is of unknown provenance — prefer a full-replace repoint
  so the column carries a single, auditable source of truth.

**Subsection cross-references.** `ENTITY_ARCHITECTURE.md → Design
Decision Log` carries the dated rationale entry (2026-04-19);
`docs/findings/2026-04-19-rewrite-build-managers.md` documents the Rewrite5
application of this pattern.

**Cross-references.**
- `ENTITY_ARCHITECTURE.md → Known Limitations` carries a pointer to
  this section from the entity side.
- `ENTITY_ARCHITECTURE.md → Design Decision Log` carries the dated
  rationale entry (2026-04-18).
- ROADMAP → INFRASTRUCTURE → Open items → INF25 carries the
  sequencing row.

---

## 8. Writers orphaned by Stage 5 holdings drop — observed pattern

Stage 5 (2026-04-13, BLOCK-3 preparatory work) dropped the legacy
`holdings` table. Three writers continued to target `holdings` for
writes after the drop, producing silent no-ops in prod. The pattern
is worth documenting: when a table is retired, downstream readers
break loudly, but downstream *writers* — especially those running
`DROP TABLE IF EXISTS` + `CREATE TABLE AS SELECT` — can fail silently
because the create succeeds and the write succeeds against a table
no other reader consults.

**Three documented instances.**

1. **`OTHERMANAGER2` / `other_managers`.** The registry declared
   `load_13f.py` as the owner of the `other_managers` write path, but
   the actual loader had never been implemented — parsed
   `OTHERMANAGER2` rows were dropped on the floor. Because no
   downstream reader joined `other_managers`, the gap went unnoticed
   until Rewrite4 Phase 0 addendum (commit `0a7ae35`) surveyed the
   registry vs. actual writes. **15,405 rows** were recovered from
   ghost data and materialized once the loader was implemented in
   Rewrite4 (commit `14a5152`).

2. **`build_managers.py` holdings ALTER+UPDATE (`:513-532`).** The
   manager enrichment pass ran `ALTER TABLE holdings ADD COLUMN ...` +
   `UPDATE holdings SET ...` after the core manager-table build. After
   Stage 5 dropped `holdings`, these statements targeted the legacy
   table name and ran silently every quarter with no observable
   effect. **100% of the legacy 14-category `manager_type` data was
   unpopulated on new data loads** between Stage 5 and Rewrite5
   detection. Fix: repoint to `holdings_v2` at commit `1719320`.

3. **`backfill_manager_types.py`.** A hand-curated backfill of manager
   types from `data/reference/categorized_institutions_funds_v2.csv`
   targeted the dropped `holdings` table. **5,782 curated rows** were
   silently not applied on each cycle between Stage 5 and Rewrite5.
   Fix: repoint to `holdings_v2` at commit `7b8a2b7`.

**Detection characteristics.** The pattern is silent at runtime:
`DROP TABLE IF EXISTS holdings; CREATE TABLE holdings AS SELECT ...`
succeeds (table name is usable again); subsequent `INSERT / UPDATE /
ALTER` against the recreated table succeeds; no reader joins it, so
the write has no observable effect. `data_freshness` stamps, when
present, go against the dropped table name and are themselves
orphaned. The only observable symptom is data-coverage regression,
typically caught by a smoke test or a manual audit, often weeks later.

**Mitigation going forward.** When retiring a table, audit all writers
named in `scripts/pipeline/registry.py` / Appendix A below, not
just downstream readers. The `pipeline_violations.md` doc already lists
`Legacy refs:` for each script — a table-retirement audit should treat
those lines as a kill-list: every `Legacy refs:` entry against the
retired table is a writer that needs repointing or deletion, not just
a reader that needs rewriting.

**Cross-references.**
- `docs/findings/2026-04-19-rewrite-load-13f.md` — Rewrite4 Phase 0 addendum
  documents the OTHERMANAGER2 recovery.
- `docs/findings/2026-04-19-rewrite-build-managers.md` — Rewrite5 documents the
  `build_managers.py` + `backfill_manager_types.py` repoints.
- `docs/pipeline_violations.md` — each affected script carries a
  CLEARED note with commit citations (2026-04-19).

---

## 9. `promote_staging.py` promote-kind machinery

`promote_staging.py` carries two distinct promotion contracts,
selected per-table via the `PROMOTE_KIND` dict:

**`pk_diff` (existing behavior, default).** Diff staging against prod
by PK, produce `INSERT` / `UPDATE` / `DELETE` statements, apply inside
one transaction with validate_entities gates. Safe when the producer
script writes individually-keyed rows with a stable PK — every
staging row corresponds to a prod row (present, absent, or updated)
determined by the PK alone. This is the contract used by all entity
tables (`entity_current`, `entity_aliases`, `entity_identifiers`,
`entity_relationships`, `entity_rollup_history`,
`entity_classification_history`, `entity_overrides_persistent`).
Preserves row-level history and supports precise rollback by replaying
the inverse diff.

**`rebuild` (new kind, added Rewrite5 Phase 0, commit `6079220`).**
Full-replace semantics: snapshot prod to a dated table, `DROP TABLE`
prod, `CREATE TABLE AS SELECT` from staging, stamp `data_freshness`.
Safe for `DROP+CTAS` producer patterns where PK-diff is not viable
because staging row sets are not PK-keyed (fan-out from upstream
joins, dedup semantics that would treat perfectly-valid duplicate
keys as mutual deletions, or derived tables that are fully regenerated
every cycle and carry no historical state in prod).

**Registration.** Table-keyed `PROMOTE_KIND` dict in
`promote_staging.py`. Default is implicit `pk_diff` for backward
compatibility; tables that require `rebuild` are listed explicitly.

**When to use which.**

| Case | Kind |
|---|---|
| Staging row set has stable PK, diff semantics preserve history | `pk_diff` |
| Producer uses `DROP+CTAS`; every cycle fully regenerates prod | `rebuild` |
| Producer fans out via join + dedupe, dupes-on-PK are expected from the join | `rebuild` |
| Historical state must survive across promotes | `pk_diff` |
| Derived / materialized aggregates with no independent history | `rebuild` |

**Rewrite5 registrations.**
- `parent_bridge` → `pk_diff` (existing behavior preserved — history matters).
- `cik_crd_direct` → `pk_diff` (existing — history matters).
- `managers` → **`rebuild`** (new — DROP+CTAS producer, dupes-on-CIK expected from ADV joins).
- `cik_crd_links` → **`rebuild`** (new — derived materialization, no independent history).

**Snapshot retention.** `rebuild` snapshots land as
`{table}_legacy_snapshot_{YYYYMMDD}` dated tables and are retained as
audit artifacts. Precedent: `holdings_v2_manager_type_legacy_snapshot_20260419`
preserved the pre-Rewrite5 state of the `manager_type` column.
Retention policy open (see ROADMAP D7 — snapshot table retention
policy).

**Cross-references.**
- `ARCHITECTURE_REVIEW.md §Batch 3-A` carries the sibling note on
  `fund_family_patterns` + `data_freshness` table additions.
- `docs/findings/2026-04-19-rewrite-build-managers.md` documents the first use of
  `rebuild` kind.
- ROADMAP → INFRASTRUCTURE → Open items → `INF30` is the
  `merge_staging.py` analogue (NULL-only / column-scoped merge mode)
  for the seed-time reference-table layer.

---

## 10. Flow metrics — `ticker_flow_stats` formulas

`ticker_flow_stats` is an L4-derived table rebuilt by
`scripts/compute_flows.py` (`_compute_ticker_stats`). It carries
per-(ticker × period × rollup_type) aggregates derived from
`investor_flows`.

**`flow_intensity_total`.** Sum of `price_adj_flow` across continuing
holders only (rows where NOT `is_new_entry` AND NOT `is_exit`), divided
by the ticker's `market_cap`:

```
flow_intensity_total
    = SUM(price_adj_flow) / market_cap
    where price_adj_flow = net_shares * from_price
    and rows with is_new_entry OR is_exit are excluded
```

`price_adj_flow` pins share-count change at filing-date price, so the
numerator isolates the $-value of share-count change without price
movement. The result is a unitless ratio — net institutional $-flow
as a fraction of market cap for the (quarter_from → quarter_to)
window. Positive = net accumulation by continuing holders; negative
= net trimming.

**`flow_intensity_active` / `flow_intensity_passive`.** Same formula,
scoped to `manager_type != 'passive'` and `manager_type = 'passive'`
respectively. Separates active-manager conviction from index-fund
mechanical flows.

**`churn_nonpassive` / `churn_active`.** Exits + new entries as a
fraction of the average of continuing-holder flow — turnover proxy
scoped to non-passive (resp. active) managers.

**Cross-references.**
- `scripts/compute_flows.py:_compute_ticker_stats` — canonical SQL.
- `scripts/compute_flows.py:_insert_period_flows` — upstream
  `price_adj_flow` / `is_new_entry` / `is_exit` definitions.

---

## 11. CUSIP residual-coverage tracking tier

The CUSIP classification universe is closed against any *fixed* snapshot
of filings but is open-ended in time — every new 13F and N-PORT ingest
introduces CUSIPs that have never been classified. This section
documents the standing tracking tier: what is resolved today, what the
residual gap looks like, and how new CUSIPs flow through the pipeline.

**Current universe.** `cusip_classifications` carries **430,149 CUSIPs**
on prod as of BLOCK-SECURITIES-DATA-AUDIT Phase 3 close (2026-04-18;
see `docs/findings/2026-04-18-block-securities-data-audit.md`). `securities` mirrors
the same 430,149 row population via `normalize_securities.py`. The
§2 table-inventory row for `cusip_classifications` still cites the
pre-Phase-3 132,618 baseline — this section is the authoritative
up-to-date figure; the table-inventory row will be refreshed on the
next doc-sync pass.

**Residual gap — two components.**

1. **~81 malformed CUSIPs — upstream ingest artifacts.** A small
   residual set of CUSIP-like strings survive the current normalization
   pass but fail downstream classifier contracts (length/checksum/
   character-set violations that slipped past the upstream source
   files). These are upstream data-quality issues, not classifier bugs;
   they do not respond to OpenFIGI retry. Triaged as `unmappable` in
   `cusip_retry_queue` or left unresolved in `cusip_classifications`.
   Population is stable and small; no downstream AUM or entity impact.

2. **Legitimately-new CUSIPs in future ingestion.** Every quarterly
   13F promote + monthly N-PORT promote introduces CUSIPs that were
   not present in prior periods (new issues, new listings, new filer
   holdings). These land in `cusip_retry_queue` at ingest time and
   flow through the standard classification pipeline on the next
   `build_classifications.py` + `run_openfigi_retry.py` cycle. This is
   the steady-state population.

**Mitigation — pipeline handles automatically.**
`scripts/build_classifications.py` seeds any unclassified CUSIPs from
`holdings_v2` / `fund_holdings_v2` / `beneficial_ownership_v2` into
`cusip_retry_queue` with `status='pending'`. `scripts/run_openfigi_retry.py`
then works the queue, promoting resolved rows into
`cusip_classifications` + `_cache_openfigi` and flipping hard-unmappable
rows to `status='unmappable'` (subject to **INF26** `_update_error()`
hygiene — hard errors today can stick in `pending` instead of flipping;
small cosmetic fix, does not affect the resolved path). No manual
intervention is required to close the gap introduced by each new
ingest cycle.

**Monitoring.** The `cusip_retry_queue` status distribution is the
single authoritative view of resolution progress. As of 2026-04-15
prod close: 15,807 `resolved` / 22,118 `unmappable` / balance `pending`
across 37,925 rows (see §2 table-inventory row for `cusip_retry_queue`).
A net-increase in `pending` rows across two consecutive pipeline runs
indicates the retry path is not keeping up with ingest and is the
trigger condition for revisiting tier cadence.

**Cross-references.**
- ROADMAP → `INF27` carries the standing-tracking row.
- ROADMAP → `INF26` — `_update_error()` hygiene fix for permanent-pending
  rows on hard errors.
- `docs/findings/2026-04-18-block-ticker-backfill.md §10.1` — the 2025-08+
  `cusip_not_in_securities` step-change that originally surfaced the
  residual-gap concern.
- `docs/findings/2026-04-18-block-securities-data-audit.md` — Phase 3 close that
  brought the universe from 132,618 → 430,149.
- §6 **S1** — `is_priceable` semantics for grey-market rows is a
  sibling classifier-semantics concern, tracked separately.

---

## Appendix A: Canonical DDL

This appendix was folded in from `docs/canonical_ddl.md` on 2026-04-23. DDL regenerated from prod `information_schema` at time of fold. Table enumeration from `DATASET_REGISTRY` (`scripts/pipeline/registry.py`) cross-checked against `information_schema.tables` in `data/13f.duckdb`. For updates, re-run the Phase C1 queries against live prod.

### Reconciliation summary

- **REGISTRY ∩ prod:** 51 tables/views (primary scope)
- **REGISTRY only:** 1 (positions)
- **prod only:** 8 (_cache_openfigi, admin_preferences, admin_sessions, cusip_classifications, cusip_retry_queue, fund_holdings, ingestion_manifest_current, schema_versions)

Total: 60 tables/views (+ snapshot tables excluded). REGISTRY contains 52 entries; prod contains 59 base-tables + views (excluding `*_snapshot_*`).

### `adv_managers`

- **Source bucket:** REGISTRY ∩ prod
- **Object type:** BASE TABLE
- **Row count:** 16,606 (as of 2026-04-23)
- **Columns:** 18

**DDL:**

```sql
CREATE TABLE adv_managers (
    "crd_number" VARCHAR,
    "sec_file_number" VARCHAR,
    "cik" VARCHAR,
    "firm_name" VARCHAR,
    "legal_name" VARCHAR,
    "city" VARCHAR,
    "state" VARCHAR,
    "address" VARCHAR,
    "adv_5f_raum" DOUBLE,
    "adv_5f_raum_discrtnry" DOUBLE,
    "adv_5f_raum_non_discrtnry" DOUBLE,
    "adv_5f_num_accts" BIGINT,
    "pct_discretionary" DOUBLE,
    "strategy_inferred" VARCHAR,
    "is_activist" BOOLEAN,
    "has_hedge_funds" VARCHAR,
    "has_pe_funds" VARCHAR,
    "has_vc_funds" VARCHAR
);
```

### `benchmark_weights`

- **Source bucket:** REGISTRY ∩ prod
- **Object type:** BASE TABLE
- **Row count:** 55 (as of 2026-04-23)
- **Columns:** 6
- **Primary key:** `(index_name, gics_sector, as_of_date)`

**DDL:**

```sql
CREATE TABLE benchmark_weights (
    "index_name" VARCHAR NOT NULL,
    "gics_sector" VARCHAR NOT NULL,
    "gics_code" VARCHAR,
    "weight_pct" DOUBLE,
    "as_of_date" DATE NOT NULL,
    "source" VARCHAR,
    PRIMARY KEY ("index_name", "gics_sector", "as_of_date")
);
```

### `beneficial_ownership_current`

- **Source bucket:** REGISTRY ∩ prod
- **Object type:** BASE TABLE
- **Row count:** 24,756 (as of 2026-04-23)
- **Columns:** 21

**DDL:**

```sql
CREATE TABLE beneficial_ownership_current (
    "filer_cik" VARCHAR,
    "filer_name" VARCHAR,
    "subject_ticker" VARCHAR,
    "subject_cusip" VARCHAR,
    "latest_filing_type" VARCHAR,
    "latest_filing_date" DATE,
    "pct_owned" DOUBLE,
    "shares_owned" BIGINT,
    "intent" VARCHAR,
    "crossing_date" DATE,
    "days_since_filing" INTEGER,
    "is_current" BOOLEAN,
    "accession_number" VARCHAR,
    "crossed_5pct" BOOLEAN,
    "prior_intent" VARCHAR,
    "amendment_count" BIGINT,
    "entity_id" BIGINT,
    "rollup_entity_id" BIGINT,
    "rollup_name" VARCHAR,
    "dm_rollup_entity_id" BIGINT,
    "dm_rollup_name" VARCHAR
);
```

### `beneficial_ownership_v2`

- **Source bucket:** REGISTRY ∩ prod
- **Object type:** BASE TABLE
- **Row count:** 51,905 (as of 2026-04-23)
- **Columns:** 28

**DDL:**

```sql
CREATE TABLE beneficial_ownership_v2 (
    "accession_number" VARCHAR,
    "filer_cik" VARCHAR,
    "filer_name" VARCHAR,
    "subject_cusip" VARCHAR,
    "subject_ticker" VARCHAR,
    "subject_name" VARCHAR,
    "filing_type" VARCHAR,
    "filing_date" DATE,
    "report_date" DATE,
    "pct_owned" DOUBLE,
    "shares_owned" BIGINT,
    "aggregate_value" DOUBLE,
    "intent" VARCHAR,
    "is_amendment" BOOLEAN,
    "prior_accession" VARCHAR,
    "purpose_text" VARCHAR,
    "group_members" VARCHAR,
    "manager_cik" VARCHAR,
    "loaded_at" TIMESTAMP,
    "name_resolved" BOOLEAN,
    "entity_id" BIGINT,
    "rollup_entity_id" BIGINT,
    "rollup_name" VARCHAR,
    "dm_rollup_entity_id" BIGINT,
    "dm_rollup_name" VARCHAR,
    "row_id" BIGINT DEFAULT nextval('beneficial_ownership_v2_row_id_seq'),
    "is_latest" BOOLEAN DEFAULT CAST('t' AS BOOLEAN),
    "backfill_quality" VARCHAR
);
```

### `cik_crd_direct`

- **Source bucket:** REGISTRY ∩ prod
- **Object type:** BASE TABLE
- **Row count:** 4,059 (as of 2026-04-23)
- **Columns:** 3

**DDL:**

```sql
CREATE TABLE cik_crd_direct (
    "cik" VARCHAR,
    "crd_number" VARCHAR,
    "match_type" VARCHAR
);
```

### `cik_crd_links`

- **Source bucket:** REGISTRY ∩ prod
- **Object type:** BASE TABLE
- **Row count:** 353 (as of 2026-04-23)
- **Columns:** 5

**DDL:**

```sql
CREATE TABLE cik_crd_links (
    "cik" VARCHAR,
    "crd_number" VARCHAR,
    "filing_name" VARCHAR,
    "adv_name" VARCHAR,
    "match_score" DOUBLE
);
```

### `data_freshness`

- **Source bucket:** REGISTRY ∩ prod
- **Object type:** BASE TABLE
- **Row count:** 26 (as of 2026-04-23)
- **Columns:** 3
- **Primary key:** `(table_name)`

**DDL:**

```sql
CREATE TABLE data_freshness (
    "table_name" VARCHAR NOT NULL,
    "last_computed_at" TIMESTAMP,
    "row_count" BIGINT,
    PRIMARY KEY ("table_name")
);
```

### `entities`

- **Source bucket:** REGISTRY ∩ prod
- **Object type:** BASE TABLE
- **Row count:** 26,602 (as of 2026-04-23)
- **Columns:** 6

**DDL:**

```sql
CREATE TABLE entities (
    "entity_id" BIGINT,
    "entity_type" VARCHAR,
    "canonical_name" VARCHAR,
    "created_source" VARCHAR,
    "is_inferred" BOOLEAN,
    "created_at" TIMESTAMP
);
```

### `entity_aliases`

- **Source bucket:** REGISTRY ∩ prod
- **Object type:** BASE TABLE
- **Row count:** 26,941 (as of 2026-04-23)
- **Columns:** 10

**DDL:**

```sql
CREATE TABLE entity_aliases (
    "entity_id" BIGINT,
    "alias_name" VARCHAR,
    "alias_type" VARCHAR,
    "is_preferred" BOOLEAN,
    "preferred_key" BIGINT,
    "source_table" VARCHAR,
    "is_inferred" BOOLEAN,
    "valid_from" DATE,
    "valid_to" DATE,
    "created_at" TIMESTAMP
);
```

### `entity_classification_history`

- **Source bucket:** REGISTRY ∩ prod
- **Object type:** BASE TABLE
- **Row count:** 26,662 (as of 2026-04-23)
- **Columns:** 9

**DDL:**

```sql
CREATE TABLE entity_classification_history (
    "entity_id" BIGINT,
    "classification" VARCHAR,
    "is_activist" BOOLEAN,
    "confidence" VARCHAR,
    "source" VARCHAR,
    "is_inferred" BOOLEAN,
    "valid_from" DATE,
    "valid_to" DATE,
    "created_at" TIMESTAMP
);
```

### `entity_current`

- **Source bucket:** REGISTRY ∩ prod
- **Object type:** VIEW
- **Row count:** 26,602 (as of 2026-04-23)
- **Columns:** 9

**View definition:**

```sql
CREATE VIEW entity_current AS SELECT e.entity_id, e.entity_type, e.created_at, COALESCE(ea.alias_name, e.canonical_name) AS display_name, ech.classification, ech.is_activist, ech.confidence AS classification_confidence, er.rollup_entity_id, er.rollup_type FROM entities AS e LEFT JOIN (SELECT entity_id, alias_name FROM entity_aliases WHERE ((is_preferred = CAST('t' AS BOOLEAN)) AND (valid_to = CAST('9999-12-31' AS DATE)))) AS ea ON ((e.entity_id = ea.entity_id)) LEFT JOIN entity_classification_history AS ech ON (((e.entity_id = ech.entity_id) AND (ech.valid_to = CAST('9999-12-31' AS DATE)))) LEFT JOIN entity_rollup_history AS er ON (((e.entity_id = er.entity_id) AND (er.rollup_type = 'economic_control_v1') AND (er.valid_to = CAST('9999-12-31' AS DATE))));
```

### `entity_identifiers`

- **Source bucket:** REGISTRY ∩ prod
- **Object type:** BASE TABLE
- **Row count:** 35,512 (as of 2026-04-23)
- **Columns:** 9

**DDL:**

```sql
CREATE TABLE entity_identifiers (
    "entity_id" BIGINT,
    "identifier_type" VARCHAR,
    "identifier_value" VARCHAR,
    "confidence" VARCHAR,
    "source" VARCHAR,
    "is_inferred" BOOLEAN,
    "valid_from" DATE,
    "valid_to" DATE,
    "created_at" TIMESTAMP
);
```

### `entity_identifiers_staging`

- **Source bucket:** REGISTRY ∩ prod
- **Object type:** BASE TABLE
- **Row count:** 3,503 (as of 2026-04-23)
- **Columns:** 13

**DDL:**

```sql
CREATE TABLE entity_identifiers_staging (
    "staging_id" BIGINT,
    "entity_id" BIGINT,
    "identifier_type" VARCHAR,
    "identifier_value" VARCHAR,
    "confidence" VARCHAR,
    "source" VARCHAR,
    "conflict_reason" VARCHAR,
    "existing_entity_id" BIGINT,
    "review_status" VARCHAR,
    "reviewed_by" VARCHAR,
    "reviewed_at" TIMESTAMP,
    "notes" VARCHAR,
    "created_at" TIMESTAMP
);
```

### `entity_overrides_persistent`

- **Source bucket:** REGISTRY ∩ prod
- **Object type:** BASE TABLE
- **Row count:** 257 (as of 2026-04-23)
- **Columns:** 15

**DDL:**

```sql
CREATE TABLE entity_overrides_persistent (
    "override_id" BIGINT DEFAULT nextval('override_id_seq') NOT NULL,
    "entity_cik" VARCHAR,
    "action" VARCHAR NOT NULL,
    "field" VARCHAR,
    "old_value" VARCHAR,
    "new_value" VARCHAR,
    "reason" VARCHAR,
    "analyst" VARCHAR,
    "still_valid" BOOLEAN DEFAULT CAST('t' AS BOOLEAN) NOT NULL,
    "applied_at" TIMESTAMP DEFAULT now(),
    "created_at" TIMESTAMP DEFAULT now(),
    "identifier_type" VARCHAR DEFAULT 'cik',
    "identifier_value" VARCHAR,
    "rollup_type" VARCHAR DEFAULT 'economic_control_v1',
    "relationship_context" VARCHAR
);
```

### `entity_relationships`

- **Source bucket:** REGISTRY ∩ prod
- **Object type:** BASE TABLE
- **Row count:** 18,365 (as of 2026-04-23)
- **Columns:** 14

**DDL:**

```sql
CREATE TABLE entity_relationships (
    "relationship_id" BIGINT,
    "parent_entity_id" BIGINT,
    "child_entity_id" BIGINT,
    "relationship_type" VARCHAR,
    "control_type" VARCHAR,
    "is_primary" BOOLEAN,
    "primary_parent_key" BIGINT,
    "confidence" VARCHAR,
    "source" VARCHAR,
    "is_inferred" BOOLEAN,
    "valid_from" DATE,
    "valid_to" DATE,
    "created_at" TIMESTAMP,
    "last_refreshed_at" TIMESTAMP
);
```

### `entity_relationships_staging`

- **Source bucket:** REGISTRY ∩ prod
- **Object type:** BASE TABLE
- **Row count:** 0 (as of 2026-04-23)
- **Columns:** 14

**DDL:**

```sql
CREATE TABLE entity_relationships_staging (
    "id" BIGINT DEFAULT nextval('identifier_staging_id_seq'),
    "child_entity_id" BIGINT NOT NULL,
    "parent_entity_id" BIGINT,
    "owner_name" VARCHAR NOT NULL,
    "relationship_type" VARCHAR,
    "ownership_pct" FLOAT,
    "source" VARCHAR,
    "confidence" VARCHAR,
    "conflict_reason" VARCHAR,
    "review_status" VARCHAR DEFAULT 'pending',
    "created_at" TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    "reviewer" VARCHAR,
    "reviewed_at" TIMESTAMP,
    "resolution" VARCHAR
);
```

### `entity_rollup_history`

- **Source bucket:** REGISTRY ∩ prod
- **Object type:** BASE TABLE
- **Row count:** 59,938 (as of 2026-04-23)
- **Columns:** 11

**DDL:**

```sql
CREATE TABLE entity_rollup_history (
    "entity_id" BIGINT,
    "rollup_entity_id" BIGINT,
    "rollup_type" VARCHAR,
    "rule_applied" VARCHAR,
    "confidence" VARCHAR,
    "valid_from" DATE,
    "valid_to" DATE,
    "computed_at" TIMESTAMP,
    "source" VARCHAR,
    "routing_confidence" VARCHAR DEFAULT 'high',
    "review_due_date" DATE
);
```

### `fetched_tickers_13dg`

- **Source bucket:** REGISTRY ∩ prod
- **Object type:** BASE TABLE
- **Row count:** 6,075 (as of 2026-04-23)
- **Columns:** 2
- **Primary key:** `(ticker)`

**DDL:**

```sql
CREATE TABLE fetched_tickers_13dg (
    "ticker" VARCHAR NOT NULL,
    "fetched_at" TIMESTAMP,
    PRIMARY KEY ("ticker")
);
```

### `filings`

- **Source bucket:** REGISTRY ∩ prod
- **Object type:** BASE TABLE
- **Row count:** 43,358 (as of 2026-04-23)
- **Columns:** 9

**DDL:**

```sql
CREATE TABLE filings (
    "accession_number" VARCHAR,
    "cik" VARCHAR,
    "manager_name" VARCHAR,
    "crd_number" VARCHAR,
    "quarter" VARCHAR,
    "report_date" VARCHAR,
    "filing_type" VARCHAR,
    "amended" BOOLEAN,
    "filed_date" VARCHAR
);
```

### `filings_deduped`

- **Source bucket:** REGISTRY ∩ prod
- **Object type:** BASE TABLE
- **Row count:** 40,140 (as of 2026-04-23)
- **Columns:** 9

**DDL:**

```sql
CREATE TABLE filings_deduped (
    "accession_number" VARCHAR,
    "cik" VARCHAR,
    "manager_name" VARCHAR,
    "crd_number" VARCHAR,
    "quarter" VARCHAR,
    "report_date" VARCHAR,
    "filing_type" VARCHAR,
    "amended" BOOLEAN,
    "filed_date" VARCHAR
);
```

### `fund_best_index`

- **Source bucket:** REGISTRY ∩ prod
- **Object type:** BASE TABLE
- **Row count:** 6,151 (as of 2026-04-23)
- **Columns:** 8

**DDL:**

```sql
CREATE TABLE fund_best_index (
    "series_id" VARCHAR,
    "fund_name" VARCHAR,
    "best_index" VARCHAR,
    "best_coverage" DOUBLE,
    "best_weight" DOUBLE,
    "best_score" DOUBLE,
    "total_tickers" BIGINT,
    "fund_aum_m" DOUBLE
);
```

### `fund_classes`

- **Source bucket:** REGISTRY ∩ prod
- **Object type:** BASE TABLE
- **Row count:** 31,056 (as of 2026-04-23)
- **Columns:** 7

**DDL:**

```sql
CREATE TABLE fund_classes (
    "series_id" VARCHAR,
    "class_id" VARCHAR,
    "fund_cik" VARCHAR,
    "fund_name" VARCHAR,
    "report_date" DATE,
    "quarter" VARCHAR,
    "loaded_at" TIMESTAMP
);
```

### `fund_classification`

- **Source bucket:** REGISTRY ∩ prod
- **Object type:** BASE TABLE
- **Row count:** 5,717 (as of 2026-04-23)
- **Columns:** 12

**DDL:**

```sql
CREATE TABLE fund_classification (
    "series_id" VARCHAR,
    "fund_name" VARCHAR,
    "total_tickers" BIGINT,
    "sp500_coverage_pct" DOUBLE,
    "sp500_weight_pct" DOUBLE,
    "sp500_matches" BIGINT,
    "fund_aum_m" DOUBLE,
    "sp500_strategy" VARCHAR,
    "classification_method" VARCHAR,
    "best_index" VARCHAR,
    "best_index_coverage" DOUBLE,
    "best_index_weight" DOUBLE
);
```

### `fund_family_patterns`

- **Source bucket:** REGISTRY ∩ prod
- **Object type:** BASE TABLE
- **Row count:** 83 (as of 2026-04-23)
- **Columns:** 2
- **Primary key:** `(inst_parent_name, pattern)`

**DDL:**

```sql
CREATE TABLE fund_family_patterns (
    "pattern" VARCHAR NOT NULL,
    "inst_parent_name" VARCHAR NOT NULL,
    PRIMARY KEY ("inst_parent_name", "pattern")
);
```

### `fund_holdings_v2`

- **Source bucket:** REGISTRY ∩ prod
- **Object type:** BASE TABLE
- **Row count:** 14,090,397 (as of 2026-04-23)
- **Columns:** 30

**DDL:**

```sql
CREATE TABLE fund_holdings_v2 (
    "fund_cik" VARCHAR,
    "fund_name" VARCHAR,
    "family_name" VARCHAR,
    "series_id" VARCHAR,
    "quarter" VARCHAR,
    "report_month" VARCHAR,
    "report_date" DATE,
    "cusip" VARCHAR,
    "isin" VARCHAR,
    "issuer_name" VARCHAR,
    "ticker" VARCHAR,
    "asset_category" VARCHAR,
    "shares_or_principal" DOUBLE,
    "market_value_usd" DOUBLE,
    "pct_of_nav" DOUBLE,
    "fair_value_level" VARCHAR,
    "is_restricted" BOOLEAN,
    "payoff_profile" VARCHAR,
    "loaded_at" TIMESTAMP,
    "fund_strategy" VARCHAR,
    "best_index" VARCHAR,
    "entity_id" BIGINT,
    "rollup_entity_id" BIGINT,
    "dm_entity_id" BIGINT,
    "dm_rollup_entity_id" BIGINT,
    "dm_rollup_name" VARCHAR,
    "row_id" BIGINT DEFAULT nextval('fund_holdings_v2_row_id_seq'),
    "accession_number" VARCHAR,
    "is_latest" BOOLEAN DEFAULT CAST('t' AS BOOLEAN),
    "backfill_quality" VARCHAR
);
```

### `fund_index_scores`

- **Source bucket:** REGISTRY ∩ prod
- **Object type:** BASE TABLE
- **Row count:** 80,271 (as of 2026-04-23)
- **Columns:** 8

**DDL:**

```sql
CREATE TABLE fund_index_scores (
    "series_id" VARCHAR,
    "fund_name" VARCHAR,
    "index_name" VARCHAR,
    "total_tickers" BIGINT,
    "coverage_pct" DOUBLE,
    "weight_pct" DOUBLE,
    "idx_matches" BIGINT,
    "fund_aum_m" DOUBLE
);
```

### `fund_name_map`

- **Source bucket:** REGISTRY ∩ prod
- **Object type:** BASE TABLE
- **Row count:** 6,229,495 (as of 2026-04-23)
- **Columns:** 5

**DDL:**

```sql
CREATE TABLE fund_name_map (
    "accession_number" VARCHAR,
    "cusip" VARCHAR,
    "shares" BIGINT,
    "discretion" VARCHAR,
    "fund_name" VARCHAR
);
```

### `fund_universe`

- **Source bucket:** REGISTRY ∩ prod
- **Object type:** BASE TABLE
- **Row count:** 12,870 (as of 2026-04-23)
- **Columns:** 16
- **Primary key:** `(series_id)`

**DDL:**

```sql
CREATE TABLE fund_universe (
    "fund_cik" VARCHAR,
    "fund_name" VARCHAR,
    "series_id" VARCHAR NOT NULL,
    "family_name" VARCHAR,
    "total_net_assets" DOUBLE,
    "fund_category" VARCHAR,
    "is_actively_managed" BOOLEAN,
    "total_holdings_count" INTEGER,
    "equity_pct" DOUBLE,
    "top10_concentration" DOUBLE,
    "last_updated" TIMESTAMP,
    "fund_strategy" VARCHAR,
    "best_index" VARCHAR,
    "strategy_narrative" VARCHAR,
    "strategy_source" VARCHAR,
    "strategy_fetched_at" TIMESTAMP,
    PRIMARY KEY ("series_id")
);
```

### `holdings_v2`

- **Source bucket:** REGISTRY ∩ prod
- **Object type:** BASE TABLE
- **Row count:** 12,270,984 (as of 2026-04-23)
- **Columns:** 38

**DDL:**

```sql
CREATE TABLE holdings_v2 (
    "accession_number" VARCHAR,
    "cik" VARCHAR,
    "manager_name" VARCHAR,
    "crd_number" VARCHAR,
    "inst_parent_name" VARCHAR,
    "quarter" VARCHAR,
    "report_date" VARCHAR,
    "cusip" VARCHAR,
    "ticker" VARCHAR,
    "issuer_name" VARCHAR,
    "security_type" VARCHAR,
    "market_value_usd" BIGINT,
    "shares" BIGINT,
    "pct_of_portfolio" DOUBLE,
    "pct_of_so" DOUBLE,
    "manager_type" VARCHAR,
    "is_passive" BOOLEAN,
    "is_activist" BOOLEAN,
    "discretion" VARCHAR,
    "vote_sole" BIGINT,
    "vote_shared" BIGINT,
    "vote_none" BIGINT,
    "put_call" VARCHAR,
    "market_value_live" DOUBLE,
    "security_type_inferred" VARCHAR,
    "fund_name" VARCHAR,
    "classification_source" VARCHAR,
    "entity_id" BIGINT,
    "rollup_entity_id" BIGINT,
    "rollup_name" VARCHAR,
    "entity_type" VARCHAR,
    "dm_rollup_entity_id" BIGINT,
    "dm_rollup_name" VARCHAR,
    "pct_of_so_source" VARCHAR,
    "row_id" BIGINT DEFAULT nextval('holdings_v2_row_id_seq'),
    "is_latest" BOOLEAN DEFAULT CAST('t' AS BOOLEAN),
    "loaded_at" TIMESTAMP DEFAULT now(),
    "backfill_quality" VARCHAR
);
```

### `index_proxies`

- **Source bucket:** REGISTRY ∩ prod
- **Object type:** BASE TABLE
- **Row count:** 13,641 (as of 2026-04-23)
- **Columns:** 3

**DDL:**

```sql
CREATE TABLE index_proxies (
    "index_name" VARCHAR,
    "ticker" VARCHAR,
    "weight" DOUBLE
);
```

### `ingestion_impacts`

- **Source bucket:** REGISTRY ∩ prod
- **Object type:** BASE TABLE
- **Row count:** 98,706 (as of 2026-04-23)
- **Columns:** 17
- **Primary key:** `(impact_id)`

**DDL:**

```sql
CREATE TABLE ingestion_impacts (
    "impact_id" BIGINT NOT NULL,
    "manifest_id" BIGINT NOT NULL,
    "target_table" VARCHAR NOT NULL,
    "unit_type" VARCHAR NOT NULL,
    "unit_key_json" VARCHAR NOT NULL,
    "report_date" DATE,
    "rows_staged" INTEGER DEFAULT 0 NOT NULL,
    "rows_promoted" INTEGER DEFAULT 0 NOT NULL,
    "load_status" VARCHAR DEFAULT 'pending' NOT NULL,
    "validation_tier" VARCHAR,
    "validation_report" VARCHAR,
    "promote_status" VARCHAR DEFAULT 'pending' NOT NULL,
    "promote_duration_ms" BIGINT,
    "validate_duration_ms" BIGINT,
    "promoted_at" TIMESTAMP,
    "error_message" VARCHAR,
    "created_at" TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY ("impact_id")
);
```

### `ingestion_manifest`

- **Source bucket:** REGISTRY ∩ prod
- **Object type:** BASE TABLE
- **Row count:** 73,244 (as of 2026-04-23)
- **Columns:** 26
- **Primary key:** `(manifest_id)`

**DDL:**

```sql
CREATE TABLE ingestion_manifest (
    "manifest_id" BIGINT NOT NULL,
    "source_type" VARCHAR NOT NULL,
    "object_type" VARCHAR NOT NULL,
    "object_key" VARCHAR NOT NULL,
    "source_url" VARCHAR,
    "accession_number" VARCHAR,
    "report_period" DATE,
    "filing_date" DATE,
    "accepted_at" TIMESTAMP,
    "run_id" VARCHAR NOT NULL,
    "discovered_at" TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    "fetch_started_at" TIMESTAMP,
    "fetch_completed_at" TIMESTAMP,
    "fetch_status" VARCHAR DEFAULT 'pending' NOT NULL,
    "http_code" INTEGER,
    "source_bytes" BIGINT,
    "source_checksum" VARCHAR,
    "local_path" VARCHAR,
    "retry_count" INTEGER DEFAULT 0 NOT NULL,
    "error_message" VARCHAR,
    "parser_version" VARCHAR,
    "schema_version" VARCHAR,
    "is_amendment" BOOLEAN DEFAULT CAST('f' AS BOOLEAN) NOT NULL,
    "prior_accession" VARCHAR,
    "superseded_by_manifest_id" BIGINT,
    "created_at" TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY ("manifest_id")
);
```

### `investor_flows`

- **Source bucket:** REGISTRY ∩ prod
- **Object type:** BASE TABLE
- **Row count:** 17,396,524 (as of 2026-04-23)
- **Columns:** 25

**DDL:**

```sql
CREATE TABLE investor_flows (
    "ticker" VARCHAR,
    "period" VARCHAR,
    "quarter_from" VARCHAR,
    "quarter_to" VARCHAR,
    "rollup_type" VARCHAR,
    "rollup_entity_id" BIGINT,
    "rollup_name" VARCHAR,
    "inst_parent_name" VARCHAR,
    "manager_type" VARCHAR,
    "from_shares" DOUBLE,
    "to_shares" DOUBLE,
    "net_shares" DOUBLE,
    "pct_change" DOUBLE,
    "from_value" DOUBLE,
    "to_value" DOUBLE,
    "from_price" DOUBLE,
    "price_adj_flow" DOUBLE,
    "raw_flow" DOUBLE,
    "price_effect" DOUBLE,
    "is_new_entry" BOOLEAN,
    "is_exit" BOOLEAN,
    "flow_4q" DOUBLE,
    "flow_2q" DOUBLE,
    "momentum_ratio" DOUBLE,
    "momentum_signal" VARCHAR
);
```

### `lei_reference`

- **Source bucket:** REGISTRY ∩ prod
- **Object type:** BASE TABLE
- **Row count:** 13,143 (as of 2026-04-23)
- **Columns:** 6
- **Primary key:** `(lei)`

**DDL:**

```sql
CREATE TABLE lei_reference (
    "lei" VARCHAR NOT NULL,
    "entity_name" VARCHAR,
    "entity_type" VARCHAR,
    "series_id" VARCHAR,
    "fund_cik" VARCHAR,
    "updated_at" TIMESTAMP,
    PRIMARY KEY ("lei")
);
```

### `listed_filings_13dg`

- **Source bucket:** REGISTRY ∩ prod
- **Object type:** BASE TABLE
- **Row count:** 60,247 (as of 2026-04-23)
- **Columns:** 8
- **Primary key:** `(accession_number)`

**DDL:**

```sql
CREATE TABLE listed_filings_13dg (
    "accession_number" VARCHAR NOT NULL,
    "ticker" VARCHAR,
    "form" VARCHAR,
    "filing_date" VARCHAR,
    "filer_cik" VARCHAR,
    "subject_name" VARCHAR,
    "subject_cik" VARCHAR,
    "listed_at" TIMESTAMP,
    PRIMARY KEY ("accession_number")
);
```

### `managers`

- **Source bucket:** REGISTRY ∩ prod
- **Object type:** BASE TABLE
- **Row count:** 11,135 (as of 2026-04-23)
- **Columns:** 15

**DDL:**

```sql
CREATE TABLE managers (
    "cik" VARCHAR,
    "manager_name" VARCHAR,
    "crd_number" VARCHAR,
    "parent_name" VARCHAR,
    "strategy_type" VARCHAR,
    "is_activist" BOOLEAN,
    "is_passive" BOOLEAN,
    "aum_total" DOUBLE,
    "aum_discretionary" DOUBLE,
    "pct_discretionary" DOUBLE,
    "adv_city" VARCHAR,
    "adv_state" VARCHAR,
    "manually_verified" BOOLEAN,
    "num_filings" BIGINT,
    "total_positions" BIGINT
);
```

### `market_data`

- **Source bucket:** REGISTRY ∩ prod
- **Object type:** BASE TABLE
- **Row count:** 10,064 (as of 2026-04-23)
- **Columns:** 26

**DDL:**

```sql
CREATE TABLE market_data (
    "ticker" VARCHAR,
    "price_live" DOUBLE,
    "market_cap" DOUBLE,
    "float_shares" DOUBLE,
    "shares_outstanding" DOUBLE,
    "fifty_two_week_high" DOUBLE,
    "fifty_two_week_low" DOUBLE,
    "avg_volume_30d" DOUBLE,
    "sector" VARCHAR,
    "industry" VARCHAR,
    "exchange" VARCHAR,
    "fetch_date" VARCHAR,
    "price_2025Q1" INTEGER,
    "price_2025Q2" INTEGER,
    "price_2025Q3" INTEGER,
    "price_2025Q4" INTEGER,
    "unfetchable" BOOLEAN,
    "unfetchable_reason" VARCHAR,
    "metadata_date" VARCHAR,
    "sec_date" VARCHAR,
    "public_float_usd" DOUBLE,
    "shares_as_of" VARCHAR,
    "shares_form" VARCHAR,
    "shares_filed" VARCHAR,
    "shares_source_tag" VARCHAR,
    "cik" VARCHAR
);
```

### `ncen_adviser_map`

- **Source bucket:** REGISTRY ∩ prod
- **Object type:** BASE TABLE
- **Row count:** 11,209 (as of 2026-04-23)
- **Columns:** 14

**DDL:**

```sql
CREATE TABLE ncen_adviser_map (
    "registrant_cik" VARCHAR,
    "registrant_name" VARCHAR,
    "adviser_name" VARCHAR,
    "adviser_sec_file" VARCHAR,
    "adviser_crd" VARCHAR,
    "adviser_lei" VARCHAR,
    "role" VARCHAR,
    "series_id" VARCHAR,
    "series_name" VARCHAR,
    "report_date" DATE,
    "filing_date" DATE,
    "loaded_at" TIMESTAMP,
    "valid_from" TIMESTAMP,
    "valid_to" DATE DEFAULT CAST('9999-12-31' AS DATE)
);
```

### `other_managers`

- **Source bucket:** REGISTRY ∩ prod
- **Object type:** BASE TABLE
- **Row count:** 15,405 (as of 2026-04-23)
- **Columns:** 8

**DDL:**

```sql
CREATE TABLE other_managers (
    "accession_number" VARCHAR,
    "sequence_number" VARCHAR,
    "other_cik" VARCHAR,
    "form13f_file_number" VARCHAR,
    "crd_number" VARCHAR,
    "sec_file_number" VARCHAR,
    "name" VARCHAR,
    "quarter" VARCHAR
);
```

### `parent_bridge`

- **Source bucket:** REGISTRY ∩ prod
- **Object type:** BASE TABLE
- **Row count:** 11,135 (as of 2026-04-23)
- **Columns:** 7

**DDL:**

```sql
CREATE TABLE parent_bridge (
    "cik" VARCHAR,
    "manager_name" VARCHAR,
    "crd_number" VARCHAR,
    "parent_name" VARCHAR,
    "strategy_type" VARCHAR,
    "is_activist" BOOLEAN,
    "manually_verified" BOOLEAN
);
```

### `peer_groups`

- **Source bucket:** REGISTRY ∩ prod
- **Object type:** BASE TABLE
- **Row count:** 27 (as of 2026-04-23)
- **Columns:** 8

**DDL:**

```sql
CREATE TABLE peer_groups (
    "group_id" VARCHAR,
    "group_name" VARCHAR,
    "ticker" VARCHAR,
    "company_name" VARCHAR,
    "is_primary" BOOLEAN,
    "added_date" DATE,
    "added_by" VARCHAR,
    "notes" VARCHAR
);
```

### `pending_entity_resolution`

- **Source bucket:** REGISTRY ∩ prod
- **Object type:** BASE TABLE
- **Row count:** 6,874 (as of 2026-04-23)
- **Columns:** 13
- **Primary key:** `(resolution_id)`

**DDL:**

```sql
CREATE TABLE pending_entity_resolution (
    "resolution_id" BIGINT DEFAULT nextval('resolution_id_seq') NOT NULL,
    "manifest_id" BIGINT,
    "source_type" VARCHAR NOT NULL,
    "identifier_type" VARCHAR NOT NULL,
    "identifier_value" VARCHAR NOT NULL,
    "context_json" VARCHAR,
    "resolution_status" VARCHAR DEFAULT 'pending' NOT NULL,
    "pending_key" VARCHAR,
    "resolved_entity_id" BIGINT,
    "resolved_by" VARCHAR,
    "resolved_at" TIMESTAMP,
    "resolution_notes" VARCHAR,
    "created_at" TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY ("resolution_id")
);
```

### `raw_coverpage`

- **Source bucket:** REGISTRY ∩ prod
- **Object type:** BASE TABLE
- **Row count:** 43,358 (as of 2026-04-23)
- **Columns:** 10

**DDL:**

```sql
CREATE TABLE raw_coverpage (
    "accession_number" VARCHAR,
    "report_calendar" VARCHAR,
    "is_amendment" VARCHAR,
    "amendment_no" VARCHAR,
    "filing_manager_name" VARCHAR,
    "filing_manager_city" VARCHAR,
    "filing_manager_state" VARCHAR,
    "crd_number" VARCHAR,
    "sec_file_number" VARCHAR,
    "quarter" VARCHAR
);
```

### `raw_infotable`

- **Source bucket:** REGISTRY ∩ prod
- **Object type:** BASE TABLE
- **Row count:** 13,540,608 (as of 2026-04-23)
- **Columns:** 15

**DDL:**

```sql
CREATE TABLE raw_infotable (
    "accession_number" VARCHAR,
    "issuer_name" VARCHAR,
    "title_of_class" VARCHAR,
    "cusip" VARCHAR,
    "figi" VARCHAR,
    "value" BIGINT,
    "shares" BIGINT,
    "shares_type" VARCHAR,
    "put_call" VARCHAR,
    "discretion" VARCHAR,
    "other_manager" VARCHAR,
    "vote_sole" BIGINT,
    "vote_shared" BIGINT,
    "vote_none" BIGINT,
    "quarter" VARCHAR
);
```

### `raw_submissions`

- **Source bucket:** REGISTRY ∩ prod
- **Object type:** BASE TABLE
- **Row count:** 43,358 (as of 2026-04-23)
- **Columns:** 6

**DDL:**

```sql
CREATE TABLE raw_submissions (
    "accession_number" VARCHAR,
    "filing_date" VARCHAR,
    "submission_type" VARCHAR,
    "cik" VARCHAR,
    "period_of_report" VARCHAR,
    "quarter" VARCHAR
);
```

### `securities`

- **Source bucket:** REGISTRY ∩ prod
- **Object type:** BASE TABLE
- **Row count:** 430,149 (as of 2026-04-23)
- **Columns:** 22
- **Primary key:** `(cusip)`

**DDL:**

```sql
CREATE TABLE securities (
    "cusip" VARCHAR NOT NULL,
    "issuer_name" VARCHAR,
    "ticker" VARCHAR,
    "security_type" VARCHAR,
    "exchange" VARCHAR,
    "market_sector" VARCHAR,
    "sector" VARCHAR,
    "industry" VARCHAR,
    "sic_code" INTEGER,
    "is_energy" BOOLEAN,
    "is_media" BOOLEAN,
    "holdings_count" BIGINT,
    "total_value" DOUBLE,
    "security_type_inferred" VARCHAR,
    "canonical_type" VARCHAR,
    "canonical_type_source" VARCHAR,
    "is_equity" BOOLEAN,
    "is_priceable" BOOLEAN,
    "ticker_expected" BOOLEAN,
    "is_active" BOOLEAN DEFAULT CAST('t' AS BOOLEAN),
    "figi" VARCHAR,
    "is_otc" BOOLEAN DEFAULT CAST('f' AS BOOLEAN),
    PRIMARY KEY ("cusip")
);
```

### `shares_outstanding_history`

- **Source bucket:** REGISTRY ∩ prod
- **Object type:** BASE TABLE
- **Row count:** 338,053 (as of 2026-04-23)
- **Columns:** 7
- **Primary key:** `(ticker, as_of_date)`

**DDL:**

```sql
CREATE TABLE shares_outstanding_history (
    "ticker" VARCHAR NOT NULL,
    "cik" VARCHAR,
    "as_of_date" DATE NOT NULL,
    "shares" BIGINT NOT NULL,
    "form" VARCHAR,
    "filed_date" DATE,
    "source_tag" VARCHAR,
    PRIMARY KEY ("ticker", "as_of_date")
);
```

### `short_interest`

- **Source bucket:** REGISTRY ∩ prod
- **Object type:** BASE TABLE
- **Row count:** 328,595 (as of 2026-04-23)
- **Columns:** 8
- **Primary key:** `(ticker, report_date)`

**DDL:**

```sql
CREATE TABLE short_interest (
    "ticker" VARCHAR NOT NULL,
    "short_volume" BIGINT,
    "short_exempt_volume" BIGINT,
    "total_volume" BIGINT,
    "report_date" DATE NOT NULL,
    "report_month" VARCHAR,
    "short_pct" DOUBLE,
    "loaded_at" TIMESTAMP,
    PRIMARY KEY ("ticker", "report_date")
);
```

### `summary_by_parent`

- **Source bucket:** REGISTRY ∩ prod
- **Object type:** BASE TABLE
- **Row count:** 63,916 (as of 2026-04-23)
- **Columns:** 13
- **Primary key:** `(quarter, rollup_type, rollup_entity_id)`

**DDL:**

```sql
CREATE TABLE summary_by_parent (
    "quarter" VARCHAR NOT NULL,
    "rollup_type" VARCHAR NOT NULL,
    "rollup_entity_id" BIGINT NOT NULL,
    "inst_parent_name" VARCHAR,
    "rollup_name" VARCHAR,
    "total_aum" DOUBLE,
    "total_nport_aum" DOUBLE,
    "nport_coverage_pct" DOUBLE,
    "ticker_count" INTEGER,
    "total_shares" BIGINT,
    "manager_type" VARCHAR,
    "is_passive" BOOLEAN,
    "updated_at" TIMESTAMP,
    PRIMARY KEY ("quarter", "rollup_type", "rollup_entity_id")
);
```

### `summary_by_ticker`

- **Source bucket:** REGISTRY ∩ prod
- **Object type:** BASE TABLE
- **Row count:** 47,732 (as of 2026-04-23)
- **Columns:** 11
- **Primary key:** `(quarter, ticker)`

**DDL:**

```sql
CREATE TABLE summary_by_ticker (
    "quarter" VARCHAR NOT NULL,
    "ticker" VARCHAR NOT NULL,
    "company_name" VARCHAR,
    "total_value" DOUBLE,
    "total_shares" BIGINT,
    "holder_count" INTEGER,
    "active_value" DOUBLE,
    "passive_value" DOUBLE,
    "active_pct" DOUBLE,
    "pct_of_so" DOUBLE,
    "updated_at" TIMESTAMP,
    PRIMARY KEY ("quarter", "ticker")
);
```

### `ticker_flow_stats`

- **Source bucket:** REGISTRY ∩ prod
- **Object type:** BASE TABLE
- **Row count:** 80,322 (as of 2026-04-23)
- **Columns:** 10

**DDL:**

```sql
CREATE TABLE ticker_flow_stats (
    "ticker" VARCHAR,
    "quarter_from" VARCHAR,
    "quarter_to" VARCHAR,
    "rollup_type" VARCHAR,
    "flow_intensity_total" DOUBLE,
    "flow_intensity_active" DOUBLE,
    "flow_intensity_passive" DOUBLE,
    "churn_nonpassive" DOUBLE,
    "churn_active" DOUBLE,
    "computed_at" TIMESTAMP
);
```

---

### Registry-only tables

### `positions`

- **Source bucket:** REGISTRY only — retire candidate — DATASET_REGISTRY notes "Decision D2 — delete. No app reads confirmed. Retire pending sweep." Owner: scripts/unify_positions.py (RETIRE).
- **Object type:** MISSING
- **Columns:** 0

**DDL:** _not yet created in prod_
- **Registry owner:** `scripts/unify_positions.py (RETIRE)`
- **Registry notes:** Decision D2 — delete. No app reads confirmed. Retire pending sweep.

---

### Prod-only tables (registry gaps)

### `_cache_openfigi`

- **Source bucket:** Registered 2026-04-24 (`registry-gap-sweep`). Layer: 3 (upsert on `cusip`). Writers: `scripts/build_cusip.py` (primary) + `scripts/run_openfigi_retry.py`. Aligned with de-facto L3 classification in §2 and `scripts/pipeline/validate_schema_parity.py` `L3_TABLES`.
- **Object type:** BASE TABLE
- **Row count:** 15,807 (as of 2026-04-23)
- **Columns:** 7
- **Primary key:** `(cusip)`

**DDL:**

```sql
CREATE TABLE _cache_openfigi (
    "cusip" VARCHAR NOT NULL,
    "figi" VARCHAR,
    "ticker" VARCHAR,
    "exchange" VARCHAR,
    "security_type" VARCHAR,
    "market_sector" VARCHAR,
    "cached_at" TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY ("cusip")
);
```

### `admin_preferences`

- **Source bucket:** Deliberately unregistered 2026-04-24 (`registry-gap-sweep`) — 0-row stub from migration 016; no writer/reader found. Tracked in ROADMAP Current backlog (`admin_preferences`). Re-evaluate when admin feature set is next revisited. Also blocked on `multi-db-datasetspec` if retained in `data/admin.duckdb`.
- **Object type:** BASE TABLE
- **Row count:** 0 (as of 2026-04-23)
- **Columns:** 4
- **Primary key:** `(user_id, pipeline_name)`

**DDL:**

```sql
CREATE TABLE admin_preferences (
    "user_id" VARCHAR NOT NULL,
    "pipeline_name" VARCHAR NOT NULL,
    "auto_approve_enabled" BOOLEAN DEFAULT CAST('f' AS BOOLEAN),
    "auto_approve_conditions" JSON,
    PRIMARY KEY ("user_id", "pipeline_name")
);
```

### `admin_sessions`

- **Source bucket:** Deliberately unregistered 2026-04-24 (`registry-gap-sweep`) — lives in `data/admin.duckdb` (per `scripts/admin_bp.py:116`, `scripts/pipeline/validate_schema_parity.py:117`), outside the single-DB scope of `DATASET_REGISTRY`. Registering would corrupt `unclassified_tables()` invariant (registry assumes prod `13f.duckdb` per `scripts/pipeline/registry.py:13-14`). Tracked via `multi-db-datasetspec` ROADMAP backlog entry.
- **Object type:** BASE TABLE
- **Row count:** 9 (as of 2026-04-23)
- **Columns:** 7
- **Primary key:** `(session_id)`

**DDL:**

```sql
CREATE TABLE admin_sessions (
    "session_id" VARCHAR NOT NULL,
    "issued_at" TIMESTAMP NOT NULL,
    "expires_at" TIMESTAMP NOT NULL,
    "last_used_at" TIMESTAMP NOT NULL,
    "ip" VARCHAR,
    "user_agent" VARCHAR,
    "revoked_at" TIMESTAMP,
    PRIMARY KEY ("session_id")
);
```

### `cusip_classifications`

- **Source bucket:** prod only — Active writer outside REGISTRY — CUSIP/ticker classification pipeline. Read by `enrich_holdings`. Registration pending.
- **Object type:** BASE TABLE
- **Row count:** 430,149 (as of 2026-04-23)
- **Columns:** 33
- **Primary key:** `(cusip)`

**DDL:**

```sql
CREATE TABLE cusip_classifications (
    "cusip" VARCHAR NOT NULL,
    "canonical_type" VARCHAR NOT NULL,
    "canonical_type_source" VARCHAR NOT NULL,
    "raw_type_mode" VARCHAR,
    "raw_type_count" INTEGER,
    "security_type_inferred" VARCHAR,
    "asset_category_seed" VARCHAR,
    "market_sector" VARCHAR,
    "issuer_name" VARCHAR,
    "ticker" VARCHAR,
    "figi" VARCHAR,
    "exchange" VARCHAR,
    "country_code" VARCHAR,
    "is_equity" BOOLEAN DEFAULT CAST('f' AS BOOLEAN) NOT NULL,
    "ticker_expected" BOOLEAN DEFAULT CAST('f' AS BOOLEAN) NOT NULL,
    "is_priceable" BOOLEAN DEFAULT CAST('f' AS BOOLEAN) NOT NULL,
    "is_permanent" BOOLEAN DEFAULT CAST('f' AS BOOLEAN) NOT NULL,
    "is_active" BOOLEAN DEFAULT CAST('t' AS BOOLEAN) NOT NULL,
    "classification_source" VARCHAR NOT NULL,
    "ticker_source" VARCHAR,
    "confidence" VARCHAR NOT NULL,
    "openfigi_attempts" INTEGER DEFAULT 0 NOT NULL,
    "last_openfigi_attempt" TIMESTAMP,
    "openfigi_status" VARCHAR,
    "last_priceable_check" TIMESTAMP,
    "first_seen_date" DATE NOT NULL,
    "last_confirmed_date" DATE,
    "inactive_since" DATE,
    "inactive_reason" VARCHAR,
    "notes" VARCHAR,
    "created_at" TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    "is_otc" BOOLEAN DEFAULT CAST('f' AS BOOLEAN),
    PRIMARY KEY ("cusip")
);
```

### `cusip_retry_queue`

- **Source bucket:** Registered 2026-04-24 (`registry-gap-sweep`). Layer: 0 (direct_write, key `cusip`). Seeded by `scripts/build_classifications.py`; drained + status-updated by `scripts/run_openfigi_retry.py`. Same L0 bucket as `pending_entity_resolution` (queue precedent). Distinct from `cusip_classifications` (L3 authoritative output) — split is operational (queue) vs deliverable (output).
- **Object type:** BASE TABLE
- **Row count:** 37,929 (as of 2026-04-23)
- **Columns:** 13
- **Primary key:** `(cusip)`

**DDL:**

```sql
CREATE TABLE cusip_retry_queue (
    "cusip" VARCHAR NOT NULL,
    "issuer_name" VARCHAR,
    "canonical_type" VARCHAR,
    "attempt_count" INTEGER DEFAULT 0 NOT NULL,
    "first_attempted" TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "last_attempted" TIMESTAMP,
    "last_error" VARCHAR,
    "status" VARCHAR DEFAULT 'pending' NOT NULL,
    "resolved_ticker" VARCHAR,
    "resolved_figi" VARCHAR,
    "notes" VARCHAR,
    "created_at" TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY ("cusip")
);
```

### `fund_holdings`

- **Source bucket:** prod only — Legacy Stage 5 table. Only retired writers/readers remain (`scripts/retired/`). Retire candidate — B3 2-cycle gate scope.
- **Object type:** BASE TABLE
- **Row count:** 22,030 (as of 2026-04-23)
- **Columns:** 19

**DDL:**

```sql
CREATE TABLE fund_holdings (
    "fund_cik" VARCHAR,
    "fund_name" VARCHAR,
    "family_name" VARCHAR,
    "series_id" VARCHAR,
    "quarter" VARCHAR,
    "report_month" VARCHAR,
    "report_date" DATE,
    "cusip" VARCHAR,
    "isin" VARCHAR,
    "issuer_name" VARCHAR,
    "ticker" VARCHAR,
    "asset_category" VARCHAR,
    "shares_or_principal" DOUBLE,
    "market_value_usd" DOUBLE,
    "pct_of_nav" DOUBLE,
    "fair_value_level" VARCHAR,
    "is_restricted" BOOLEAN,
    "payoff_profile" VARCHAR,
    "loaded_at" TIMESTAMP
);
```

### `ingestion_manifest_current`

- **Source bucket:** prod only — DB-native view over `ingestion_manifest` (created by migration 001). Views intentionally excluded from REGISTRY.
- **Object type:** VIEW
- **Row count:** 73,244 (as of 2026-04-23)
- **Columns:** 26

**View definition:**

```sql
CREATE VIEW ingestion_manifest_current AS SELECT m.* FROM ingestion_manifest AS m WHERE (m.superseded_by_manifest_id IS NULL);
```

### `schema_versions`

- **Source bucket:** prod only — DB-native migration metadata. Written by every migration. Intentionally excluded from REGISTRY.
- **Object type:** BASE TABLE
- **Row count:** 18 (as of 2026-04-23)
- **Columns:** 3
- **Primary key:** `(version)`

**DDL:**

```sql
CREATE TABLE schema_versions (
    "version" VARCHAR NOT NULL,
    "applied_at" TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "notes" VARCHAR,
    PRIMARY KEY ("version")
);
```

---

## Appendix A.2: Migration History

Migration metadata is maintained in `schema_versions` in prod and `scripts/migrations/<version>.py` on disk. The 18 rows in `schema_versions` correspond 1:1 to the 18 files in `scripts/migrations/` — no gaps or unrecorded files at fold time.

| Version | Applied at (UTC) | File | Description |
|---------|------------------|------|-------------|
| `001_pipeline_control_plane` | 2026-04-21 08:50:33 | `scripts/migrations/001_pipeline_control_plane.py` | L0 pipeline control plane (backfill) |
| `002_fund_universe_strategy` | 2026-04-21 08:50:33 | `scripts/migrations/002_fund_universe_strategy.py` | fund_universe strategy narrative columns (backfill) |
| `003_cusip_classifications` | 2026-04-15 09:17:46 | `scripts/migrations/003_cusip_classifications.py` | CUSIP & ticker classification layer |
| `004_summary_by_parent_rollup_type` | 2026-04-21 08:50:33 | `scripts/migrations/004_summary_by_parent_rollup_type.py` | summary_by_parent rollup_type column + compound PK (backfill) |
| `005_beneficial_ownership_entity_rollups` | 2026-04-16 07:56:14 | `scripts/migrations/005_beneficial_ownership_entity_rollups.py` | 13D/G entity rollup columns on beneficial_ownership_v2 |
| `006_override_id_sequence` | 2026-04-17 05:00:39 | `scripts/migrations/006_override_id_sequence.py` | override_id sequence + DEFAULT nextval + NOT NULL constraint |
| `007_override_new_value_nullable` | 2026-04-17 05:55:16 | `scripts/migrations/007_override_new_value_nullable.py` | drop NOT NULL on entity_overrides_persistent.new_value |
| `008_rename_pct_of_float_to_pct_of_so` | 2026-04-19 13:17:12 | `scripts/migrations/008_rename_pct_of_float_to_pct_of_so.py` | holdings_v2 pct_of_float → pct_of_so rename + pct_of_so_source audit column |
| `009_admin_sessions` | 2026-04-20 12:39:01 | `scripts/migrations/009_admin_sessions.py` | admin_sessions table (sec-01 Phase 1 server-side session storage) |
| `010_drop_nextval_defaults` | 2026-04-21 04:58:38 | `scripts/migrations/010_drop_nextval_defaults.py` | drop DEFAULT nextval on ingestion_impacts.impact_id and ingestion_manifest.manifest_id (obs-03 Phase 1) |
| `011_securities_cusip_pk` | 2026-04-22 08:52:47 | `scripts/migrations/011_securities_cusip_pk.py` | add PRIMARY KEY (cusip) to securities (INF28 / int-12 Phase 1) |
| `012_securities_is_otc` | 2026-04-22 08:52:59 | `scripts/migrations/012_securities_is_otc.py` | add is_otc BOOLEAN DEFAULT FALSE to securities + cusip_classifications (INF29) |
| `013_drop_top10_columns` | 2026-04-22 08:55:40 | `scripts/migrations/013_drop_top10_columns.py` | drop unused top10_* placeholder columns from summary_by_parent and summary_by_ticker (int-17 / INF36) |
| `014_surrogate_row_id` | 2026-04-22 09:44:34 | `scripts/migrations/014_surrogate_row_id.py` | add row_id BIGINT DEFAULT nextval on holdings_v2, fund_holdings_v2, beneficial_ownership_v2 (mig-06 / INF40) |
| `015_amendment_semantics` | 2026-04-22 11:46:54 | `scripts/migrations/015_amendment_semantics.py` | is_latest + loaded_at + backfill_quality on holdings_v2, fund_holdings_v2, beneficial_ownership_v2 (p2-02) |
| `016_admin_preferences` | 2026-04-22 14:44:06 | `scripts/migrations/016_admin_preferences.py` | admin_preferences table for per-pipeline auto-approve (p2-07) |
| `017_ncen_scd_columns` | 2026-04-22 17:27:17 | `scripts/migrations/017_ncen_scd_columns.py` | valid_from + valid_to on ncen_adviser_map for SCD Type 2 promote (w2-04) |
| `add_last_refreshed_at` | 2026-04-21 08:50:33 | `scripts/migrations/add_last_refreshed_at.py` | entity_relationships.last_refreshed_at column + backfill (backfill) |

**File ↔ version mapping:** all 18 `schema_versions` rows have a corresponding file under `scripts/migrations/` with the same prefix. The non-numbered `add_last_refreshed_at` row corresponds to `scripts/migrations/add_last_refreshed_at.py` (originally drafted in commit `831e5b4`, applied during a later backfill).

### Verdict semantics (preserved from canonical_ddl.md)

The retired drift report used three verdicts to compare prod DDL against owner-script INSERT/UPDATE column lists:

- `ALIGNED` — prod DDL and owner-script column list match. No action needed.
- `OWNER_BEHIND` — prod DDL is complete; the **owner script** lags (writes to a dropped table and/or its CREATE DDL is missing columns prod has). Fixable only by rewriting the owner script — not by schema migration on prod.
- `BROKEN` — formerly used as a catch-all; replaced by `OWNER_BEHIND` after the 2026-04-13 Batch 1 reclassification.

At fold time the only outstanding `OWNER_BEHIND` table was `holdings_v2` (`load_13f.py` still materialized the pre-Stage-5 `holdings` table); the v2 cutover scheduled in phase-b2-5 (`ad4b8f7`, 2026-04-23) swapped scheduled execution to `load_13f_v2.py`, closing the loop.

### Migration patterns — index-preserving RENAME (capture-and-recreate)

**Problem:** DuckDB's `ALTER TABLE ... RENAME COLUMN` does not preserve indexes that reference the renamed column — the index silently drops and downstream queries regress on first read. Any RENAME on an index-bearing L3 table must therefore snapshot the index set, drop, rename, and rebuild.

**Idiom:**

```sql
-- 1. Snapshot the index DDL for the target table
SELECT index_name, sql
FROM duckdb_indexes()
WHERE table_name = 'holdings_v2';

-- 2. Drop each index (preserve the captured DDL strings)
DROP INDEX IF EXISTS idx_holdings_v2_foo;
-- ... repeat for every index ...

-- 3. RENAME the column (or run the column-bearing ALTER)
ALTER TABLE holdings_v2 RENAME COLUMN pct_of_float TO pct_of_so;
ALTER TABLE holdings_v2 ADD COLUMN pct_of_so_source VARCHAR;

-- 4. Recreate each index from the captured DDL
CREATE INDEX idx_holdings_v2_foo ON holdings_v2(...);
-- ... repeat ...
```

**When to apply:** any DDL mutation that touches an indexed column on an L3 canonical table. Forgetting step 4 is a silent read-path regression; forgetting step 1 is unrecoverable without `information_schema` archaeology.

**Precedents:** `ea4ae99` (migration 008 amended — `pct_of_float → pct_of_so` + `pct_of_so_source`); `d0e5f45` (INF39 staging rebuild — verifies index inventory parity post-capture-and-recreate via `scripts/pipeline/validate_schema_parity.py`).

**Related:** INF40 (stable L3 surrogate row-ID, shipped in migration 014) enables a replay-based migration mode as an alternative to capture-and-recreate; for now capture-and-recreate remains the standard. See `archive/docs/DEFERRED_FOLLOWUPS.md` (archived 2026-04-25).
