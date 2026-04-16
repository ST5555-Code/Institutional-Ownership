# Pipeline Inventory — DB-Writing Script Audit

_Prepared: 2026-04-13 — pipeline framework foundation (v1.2)_
_Revised 2026-04-16 (part 2 — end of session): ETF residual Tier A+B shipped (commit `d330d8f`). New `scripts/bootstrap_residual_advisers.py` (OK, idempotent one-off — 6 new institution entities: Stone Ridge / Bitwise / Volatility Shares / Dupree & Company / Baron Capital / Grayscale; Abacus FCF reused at existing eid=3375). `scripts/resolve_pending_series.py` gained 32 SUPPLEMENTARY_BRANDS entries (25 Tier A + 7 Tier B) — 279 pending N-PORT series resolved this session. `scripts/promote_nport.py` gained `--exclude-file` flag (unions with `--exclude` via union; needed when exclude list exceeds macOS 128K ARG_MAX). Migration `add_last_refreshed_at.py` ran on staging + prod — `entity_relationships.last_refreshed_at TIMESTAMP` live, 13,685 / 17,826 rows (76.77%) backfilled from `created_at`; probe-gated stamping in `entity_sync.insert_relationship_idempotent` now active. March 2026 N-PORT top-up ran (commit `bac4448`) — 2 Jan 2026 amendments, fund_holdings_v2 11,670,962 → 11,670,962 → 13,943,029 (+2,272,067 from ETF Tier A+B re-promote). Known caveat: `ingestion_impacts.promoted_at` for run `nport_20260415_060422_352131` was reconstructed via SQL reconciliation after a killed promote — timestamps are `MAX(loaded_at)` proxies, not original promote timestamps. See `Known data caveats` in `docs/NEXT_SESSION_CONTEXT.md`._
_Revised 2026-04-16 (later): 13D/G entity linkage shipped (commit `e231633`). New script `scripts/enrich_13dg.py` — standalone Group 2 full-refresh for `beneficial_ownership_v2`. `promote_13dg.py` gained a scoped `bulk_enrich_bo_filers` call between `_promote` and `_rebuild_current`, plus stamps `data_freshness('beneficial_ownership_v2_enrichment')`. `rebuild_beneficial_ownership_current` lifted into `pipeline/shared.py` so both entry points share one rebuild SQL. Migration 005 added 4 rollup columns to BO v2 (`entity_id` was already present); schema_versions stamped. First prod full-refresh: 40,009 / 51,905 rows enriched (77.08%); 66-row drift repaired._
_Revised 2026-04-16: Batch 3 closed. Three more REWRITE items cleared this session: `enrich_holdings.py` shipped as a new OK entry (Group 3 enrichment for `holdings_v2` + `fund_holdings_v2.ticker`, commit `559058d`); `compute_flows.py` rewritten to read `holdings_v2` with EC + DM worldview support (commit `87ee955`); `build_summaries.py` rewritten to read `holdings_v2` + `fund_holdings_v2` with rollup_type doubled writes (commit `87ee955`). New migration `004_summary_by_parent_rollup_type.py` shipped + applied prod (PK now `(quarter, rollup_type, rollup_entity_id)`). Entity MDM expansion (commits `e4e6468`, `7770f87`, `08e2400`) added `resolve_pending_series.py` (4-tier T1/T2/T3/S1 resolver), `backfill_pending_context.py` (one-off `context_json` backfill), `bootstrap_etf_advisers.py` (idempotent ETF adviser seeding) — 4,141 N-PORT pending series wired to entity MDM. Earlier 2026-04-15 work also live: six v2 rewrites (fetch_nport_v2 + fetch_dera_nport + promote_nport; fetch_13dg_v2 + promote_13dg; fetch_market v2; build_cusip v2); CUSIP v1.4 vertical (build_classifications, run_openfigi_retry, normalize_securities, validate_classifications); N-PORT v2 validators (validate_nport, validate_nport_subset). Parallel 2026-04-14 no-DB workstream (commit 831e5b4) added `Makefile` + `scripts/check_freshness.py` + `record_freshness` hooks on 8 scripts + `validate_entities.py --read-only` + `scripts/migrations/add_last_refreshed_at.py` (drafted, still NOT RUN)._

## 2026-04-14 freshness-wiring status

Eight scripts got `record_freshness(con, target_table)` hooks at end-of-run in commit `831e5b4` — the v2 SourcePipelines manage freshness through their own promote paths and are intentionally skipped here:

| Hook added (commit 831e5b4) | Rationale |
|---|---|
| `fetch_adv.py` | freshness on `adv_managers`, `cik_crd_direct`, `lei_reference` |
| `fetch_ncen.py` | freshness on `ncen_adviser_map` |
| `fetch_finra_short.py` | freshness on `short_interest` |
| `fetch_13dg.py` phase 3 | stamps on `beneficial_ownership_current` (v2 path has its own) |
| `build_entities.py` | freshness on each entity SCD table |
| `build_managers.py` | freshness on `managers` |
| `build_fund_classes.py` | freshness on `fund_classes`, `fund_best_index`, `fund_index_scores`, `fund_name_map`, `index_proxies` |
| `build_cusip.py` | freshness on `securities` |

| Hook deliberately skipped | Rationale |
|---|---|
| `fetch_13f.py` | filesystem-only, no DB writes |
| `fetch_nport_v2.py` / `fetch_dera_nport.py` | promote_nport.py stamps `fund_holdings_v2` + `fund_universe` |
| `fetch_13dg_v2.py` | promote_13dg.py stamps `beneficial_ownership_v2` + `beneficial_ownership_current` |
| `fetch_market.py` (v2) | stamps inline via the DirectWritePipeline protocol |

Gate tooling: `scripts/check_freshness.py` (exit-1 on stale/missing rows; prod read-only; `--status-only` for info). Wired into `make freshness` in `Makefile`.

---


Every `.py` file in `scripts/` that writes to the prod DB, plus the
utilities the orchestrator needs to know about. Scripts flagged for
RETIRE are listed separately at the bottom and are intentionally not
audited for PROCESS_RULES violations.

| Script | Reads from | Writes to | Legacy refs (file:line) | PROCESS_RULES violations | Action |
|---|---|---|---|---|---|
| `fetch_13f.py` | (none) | filesystem only (`data/raw`, `data/extracted`) | none | none (no DB writes) | **OK** |
| `fetch_nport_v2.py` | EDGAR, DERA ZIPs via `fetch_dera_nport` | `stg_nport_holdings`, `stg_nport_fund_universe`, `ingestion_manifest`, `ingestion_impacts` | — | — | **OK** (SourcePipeline; 4 modes: DERA bulk / `--monthly-topup` XML / `--test` / `--dry-run`) |
| `fetch_dera_nport.py` | SEC DERA ZIPs (`{YYYY}q{N}_nport.zip`) | staging tables (via `fetch_nport_v2`) | — | — | **OK** (transport + parity harness; `--zip` flag for local ZIPs; cross-ZIP amendment dedup live 2026-04-15) |
| `fetch_nport.py` (legacy) | EDGAR index, cached XMLs, `fund_universe`, `fund_holdings` (dropped) | N/A — pipeline superseded | `:377,:420,:427,:468,:477` legacy refs | **SUPERSEDED by `fetch_nport_v2.py`** — retained for the XML `parse_nport_xml` + `classify_fund` helpers imported by v2. Retire after second clean v2 amendment-chain run. | **SUPERSEDED** |
| `fetch_13dg_v2.py` | EDGAR efts, `listed_filings_13dg`, `beneficial_ownership_v2` | `beneficial_ownership_v2`, `fetched_tickers_13dg`, `listed_filings_13dg`, `ingestion_manifest`, `ingestion_impacts` | — | — | **OK** (SourcePipeline; scoped reference vertical) |
| `fetch_13dg.py` (legacy) | EDGAR, curl | N/A — pipeline superseded | legacy-table refs | **SUPERSEDED by `fetch_13dg_v2.py`**. Retire after second clean v2 run. | **SUPERSEDED** |
| `fetch_adv.py` | SEC ADV ZIP (HTTP) | `adv_managers` (DROP+CTAS) | none | §1 whole CSV loaded to pandas, single DROP+CTAS at end; §5 silent continue on missing columns (`:134-141`); §9 no `--dry-run` | **REWRITE** |
| `fetch_market.py` (v2) | `market_data`, `securities`, `holdings_v2`, `fund_holdings_v2`, `cusip_classifications` | `market_data`, `ingestion_manifest`, `ingestion_impacts`, `data_freshness` | — | — | **OK** (DirectWritePipeline rewrite, Batch 2A/2B; CUSIP-anchored universe via `securities.canonical_type`) |
| `fetch_finra_short.py` | `short_interest` | `short_interest` | none | §9 `--test` still writes to prod; otherwise clean (CHECKPOINT per 50k, restart-safe via loaded_dates, 429 backoff) | **RETROFIT** |
| `fetch_ncen.py` | `fund_universe`, `managers`, entity tables (staging), `ncen_adviser_map` | `ncen_adviser_map`, `managers.adviser_cik`, entity staging tables | none | §6 progress line lacks `flush=True` (relies on `-u`); §9 no `--dry-run`/`--apply`; otherwise clean | **RETROFIT** |
| `load_13f.py` | TSV files | `raw_submissions`, `raw_infotable`, `raw_coverpage`, `filings`, `filings_deduped`, **`holdings` DROP+CTAS (dropped!)** | `:222-224` `CREATE TABLE holdings`; `:286,:294,:304-305` reads | §1 full DROP+CTAS on every run; §5 silent continue on missing TSV (`:37`); §9 no `--dry-run` | **REWRITE** |
| `refetch_missing_sectors.py` | `/tmp/refetch_tickers.txt`, Yahoo | `market_data.sector/industry` (staging only) | none | §1 no CHECKPOINT; §4 no sleep between calls; §9 no flag, hardcoded `/tmp` | **RETROFIT** |
| `sec_shares_client.py` | SEC XBRL cache + API | filesystem cache only | none | N/A (library) | **OK** |
| `build_cusip.py` (v2) | `cusip_retry_queue`, `_cache_openfigi`, `securities`, `holdings_v2`, `fund_holdings_v2`, `beneficial_ownership_v2` | `securities` (UPSERT-only), `_cache_openfigi`, `logs/unfetchable_orphans.csv` | — | — | **OK** (UPSERT-only; OpenFIGI v3; asset_category seed; legacy at `scripts/retired/build_cusip_legacy.py`) |
| `build_classifications.py` | 3-source universe (`holdings_v2`, `fund_holdings_v2`, `beneficial_ownership_v2`), `securities`, fund asset_category | `cusip_classifications`, `cusip_retry_queue` | — | — | **OK** (rule-based classifier; no OpenFIGI; feeds `run_openfigi_retry.py`) |
| `run_openfigi_retry.py` | `cusip_retry_queue`, OpenFIGI v3 API | `_cache_openfigi`, `cusip_classifications`, `cusip_retry_queue` | — | — | **OK** (250 req/min, resume-safe, `--limit N`; FOREIGN→priceable flip inline for US composite) |
| `normalize_securities.py` | `cusip_classifications` | `securities` (UPDATE 7 new cols + INSERT missing CUSIPs) | — | — | **OK** (UPDATE + LEFT-JOIN INSERT; COALESCE-safe for ticker/exchange/market_sector; safe to re-run) |
| `validate_classifications.py` | `cusip_classifications`, `securities`, `cusip_retry_queue` | report (stdout) | — | — | **OK** (7 BLOCK + 3 BLOCK_POST + 2 WARN + 2 INFO; post-OpenFIGI-aware) |
| `validate_nport.py` | `stg_nport_holdings`, `stg_nport_fund_universe`, `ingestion_manifest`, `ingestion_impacts`, entity MDM (read-only) | `logs/reports/nport_{run_id}.md`, `pending_entity_resolution` | — | — | **OK** (set-based SQL rewrite 2026-04-15; 66s on 14K series) |
| `validate_nport_subset.py` | same + `--resolved-file` / `--excluded-file` | `logs/reports/nport_{run_id}.md`, `pending_entity_resolution` | — | — | **OK** (fast BLOCK+entity-gate-only for large subset promotes) |
| `promote_nport.py` | staging, prod | `fund_holdings_v2`, `fund_universe`, `ingestion_manifest`, `ingestion_impacts`, `data_freshness`, snapshot | — | — | **OK** (read validation report for Promote-ready: YES; atomic per (series_id, report_month); Group 2 entity enrichment via `entity_current`; `--exclude-file FILE` added 2026-04-16 part 2 for large exclude lists that exceed argv limit) |
| `validate_13dg.py` / `promote_13dg.py` | staging, prod, entity MDM (read-only) | `beneficial_ownership_v2`, `beneficial_ownership_current`, impacts, `data_freshness` (including `beneficial_ownership_v2_enrichment`), snapshot | — | — | **OK** (Batch 2B reference vertical; Group 2 entity enrichment at promote time via `bulk_enrich_bo_filers` — 2026-04-16, commit `e231633`; rebuild delegated to `pipeline/shared.rebuild_beneficial_ownership_current`) |
| `enrich_13dg.py` | `beneficial_ownership_v2`, entity MDM | `beneficial_ownership_v2.{entity_id, rollup_entity_id, rollup_name, dm_rollup_entity_id, dm_rollup_name}`, `beneficial_ownership_current` (rebuild), `data_freshness('beneficial_ownership_v2_enrichment')`, snapshot | — | — | **OK** (new 2026-04-16, commit `e231633`; standalone full-refresh / drift repair; `--staging --dry-run --filer-cik`; single atomic UPDATE per run) |
| `bootstrap_residual_advisers.py` | prod entity tables (for idempotency lookups) | staging entity MDM tables only | — | — | **OK** (one-off 2026-04-16, commit `d330d8f`; idempotent check-or-create by CRD / CIK / canonical_name; created 6 new institution entities — Stone Ridge 24348, Bitwise 24349, Volatility Shares 24350, Dupree & Company 24351, Baron Capital 24352, Grayscale 24353; Abacus FCF reused at existing eid=3375; mirrors `bootstrap_etf_advisers.py` pattern) |
| `build_managers.py` | `filings_deduped`, `adv_managers`, `cik_crd_*`, `managers` | `parent_bridge`, `cik_crd_links`, `cik_crd_direct`, `managers` (all DROP+CTAS), **`holdings` ALTER+UPDATE (dropped!)** | `:513-532` ALTER+UPDATE `holdings`; `:534` COUNT `holdings` | §1 no CHECKPOINT; §5 `try/except pass` at `:515-521` hides schema failures; §9 hardcoded prod path at `:22`, no `--staging` | **REWRITE** |
| `build_summaries.py` (v2) | `holdings_v2`, `fund_holdings_v2` | `summary_by_ticker`, `summary_by_parent`, `data_freshness` | — | — | **OK** (rewritten 2026-04-16, commit `87ee955`; rollup_type doubled INSERT for `summary_by_parent`; `total_value` uses `COALESCE(market_value_live, market_value_usd)` for graceful pre/post-enrich behavior; N-PORT side scoped to latest report_month per series_id; `--staging --dry-run --rebuild`; per-quarter × per-worldview CHECKPOINT) |
| `enrich_holdings.py` | `holdings_v2`, `fund_holdings_v2`, `cusip_classifications`, `securities`, `market_data` | `holdings_v2.{ticker, security_type_inferred, market_value_live, pct_of_float}`, `fund_holdings_v2.ticker`, `data_freshness('holdings_v2_enrichment')` | — | — | **OK** (new 2026-04-16, commit `559058d`; cusip-keyed lookup `UPDATE...FROM`; Pass A NULL cleanup + Pass B main + Pass C fund_holdings_v2 ticker; `--staging --dry-run --quarter --fund-holdings`; per-pass CHECKPOINT) |
| `build_fund_classes.py` | local N-PORT XML cache, `fund_classes` | `fund_classes`, `lei_reference`, **`fund_holdings` ALTER+UPDATE (dropped!)** | `:139` ALTER `fund_holdings`; `:146-151` UPDATE; `:152` COUNT | §1 CHECKPOINT every 5000 only; §5 silent `pass`; §9 hardcoded prod path at `:19`, no `--dry-run` | **REWRITE** |
| `build_entities.py` | `managers`, `adv_managers`, `fund_universe`, `ncen_adviser_map`, etc. | entity MDM tables (staging only) | none | §1 no per-step CHECKPOINT; §9 staging-only gate is the safety rail | **RETROFIT** |
| `build_benchmark_weights.py` | **`fund_holdings` (dropped!)**, `market_data` | `benchmark_weights` | `:79,:90` `FROM fund_holdings` | **BROKEN IMPORT** `get_connection` did not exist in db.py — fixed this session (D11); §1 no CHECKPOINT; §9 no `--dry-run` | **REWRITE** |
| `build_shares_history.py` | `market_data`, **`holdings` (dropped!)**, SEC XBRL cache | `shares_outstanding_history`, **`holdings.pct_of_float` UPDATE (dropped!)** | `:161-164,:201-203` reads; `:177-184,:190-199` UPDATE `holdings` | §1 CHECKPOINT at end only; §9 no `--dry-run` | **REWRITE** |
| `build_fixture.py` | prod DB (ATTACH READ_ONLY) | fixture DB file only | none (uses `_v2` throughout) | §9 `--dry-run` + `--force` + `--yes` gates; otherwise clean | **OK** |
| `compute_flows.py` (v2) | `holdings_v2`, `market_data` | `investor_flows`, `ticker_flow_stats`, `data_freshness` | — | — | **OK** (rewritten 2026-04-16, commit `87ee955`; investor key = `rollup_entity_id` + `rollup_name`; `inst_parent_name` retained for back-compat = `rollup_name` for active worldview; per-period × per-worldview INSERT — EC + DM both written; value column = `market_value_usd` Group 1 not `market_value_live`; `WHERE ticker IS NOT NULL AND ticker != ''` filter; `--staging --dry-run`) |
| `entity_sync.py` | entity tables | entity tables + staging | none | N/A (library) | **OK** |
| `sync_staging.py` | prod (ATTACH READ_ONLY) | staging CTAS | none | §9 `--dry-run` OK; clean | **OK** |
| `diff_staging.py` | prod + staging (READ_ONLY) | log file only | none | read-only | **OK** |
| `promote_staging.py` | staging + prod entity tables | prod entity tables, snapshot tables | none | §9 `--approved` gate; atomic + rollback; clean | **OK** |
| `merge_staging.py` | staging + prod | prod (upsert by PK or DROP+CTAS) | `:45` `"beneficial_ownership": [...]`; `:51` `"fund_holdings": None`; `:154-160,:204-205,:273` docstrings | §5 per-table try/except prints error but continues (`:289`) | **RETROFIT** (derive TABLE_KEYS from `scripts/pipeline/registry.merge_table_keys()`) |
| `migrate_batch_3a.py` | in-code pattern dict | `fund_family_patterns`, `data_freshness` | none | §9 `--dry-run` + `--prod` gates | **OK** |
| `rollback_promotion.py` | prod snapshot tables | prod (via promote_staging) | none | thin wrapper | **OK** |
| `validate_entities.py` | all entity tables | log file | none | read-only validator; keep (used by `promote_staging.py` auto-gate) | **OK** |
| `resolve_long_tail.py` | entity staging, SEC EDGAR | entity staging tables, CSVs | none | §1 no per-500 CHECKPOINT in loop (`:147-229`); otherwise clean | **RETROFIT** |
| `resolve_adv_ownership.py` | `adv_managers`, entity staging, local PDFs | entity staging, CSVs | none | §1 file-checkpoint only, no DB CHECKPOINT inside `run_match`; otherwise clean | **RETROFIT** |
| `fix_fund_classification.py` | `fund_universe` | `fund_universe.is_actively_managed` | none | §1 `executemany` all rows at once, no CHECKPOINT; §9 no `--dry-run` | **RETROFIT** |
| `benchmark.py` | (none) | (none) | none | orchestrator-only | **OK** |
| `scheduler.py` | `data/schedule.json` | `data/schedule.json` + subprocesses | none | orchestrator-only | **OK** |

---

## RETIRE (do not audit; documented for visibility)

These scripts are scheduled for deletion. They are not covered by the
pipeline framework rewrite and do not participate in the orchestrator.

- `update.py`
- `unify_positions.py`
- `auto_resolve.py`
- `enrich_tickers.py`
- `approve_overrides.py`
- `backfill_manager_types.py`
- `normalize_names.py`
- `reparse_13d.py`
- `reparse_all_nulls.py`
- `resolve_agent_names.py`
- `resolve_bo_agents.py`
- `resolve_names.py`
- `validate_phase4.py` (kept functioning but superseded by
  `validate_entities.py`; delete after Phase 4 migration confirmed
  stable)

---

## Cross-cutting findings

1. **Legacy-table writers CLEARED by v2 rewrites (2026-04-13 → 2026-04-16).**
   Original list had 8 writers + 3 readers touching Stage-5-dropped
   `holdings` / `fund_holdings` / `beneficial_ownership`. Status as of
   2026-04-16:
   - `fetch_nport.py` → SUPERSEDED by `fetch_nport_v2.py` +
     `fetch_dera_nport.py` + `promote_nport.py`. Writes
     `fund_holdings_v2` + `fund_universe` directly. ✓
   - `fetch_13dg.py` → SUPERSEDED by `fetch_13dg_v2.py` +
     `promote_13dg.py`. Writes `beneficial_ownership_v2`. ✓
   - `fetch_market.py` → rewritten (Batch 2A/2B); no longer touches
     `holdings`. CUSIP-anchored universe via `canonical_type`. ✓
   - `build_cusip.py` → rewritten (UPSERT-only; legacy at
     `scripts/retired/build_cusip_legacy.py`). No longer UPDATEs
     `holdings.ticker`. ✓
   - `compute_flows.py` → rewritten (Batch 3-2, commit `87ee955`); reads
     `holdings_v2`; rollup_type doubled writes. ✓
   - `build_summaries.py` → rewritten (Batch 3-3, commit `87ee955`); reads
     `holdings_v2` + `fund_holdings_v2`; rollup_type doubled writes. ✓
   - `enrich_holdings.py` → new (Batch 3-1, commit `559058d`); enriches
     `holdings_v2` Group 3 + `fund_holdings_v2.ticker`. ✓
   - `enrich_13dg.py` → new (2026-04-16, commit `e231633`); full-refresh
     Group 2 enrichment for `beneficial_ownership_v2` +
     `beneficial_ownership_current`. Scoped enrichment also wired into
     `promote_13dg.py`. ✓
   - Still REWRITE: `load_13f.py` (`holdings` DROP+CTAS — replacing
     with `load_13f_v2.py` post-Batch-3), `build_managers.py`,
     `build_fund_classes.py`, `build_shares_history.py`,
     `build_benchmark_weights.py`. The Batch 3 trio is now closed;
     the remaining REWRITEs are scoped for future framework work but
     no longer block any analytical workflow.

2. **No `--dry-run` across the SOURCE/DERIVED tier.** Only
   `merge_staging.py`, `sync_staging.py`, `promote_staging.py`,
   `migrate_batch_3a.py`, `build_fixture.py`, `resolve_long_tail.py`
   have proper gates. Every `fetch_*` and `build_*` writes prod by
   default. The framework `SourcePipeline.promote()` contract mandates
   explicit opt-in via manifest validation_tier — solving this at the
   framework level, not per-script.

3. **CHECKPOINT discipline is inconsistent.** Only `fetch_13dg.py`,
   `fetch_finra_short.py`, `fetch_ncen.py` checkpoint inside the main
   loop. Most scripts flush at end. `scripts/pipeline/shared.py`'s
   `sec_fetch` callers must wrap per-object CHECKPOINTs into
   `load_to_staging()`.

4. **`§3 multi-source failover` is rare.** `fetch_13dg.py` has primary
   (edgar) + curl fallback for the filing body only. `fetch_market.py`
   uses Yahoo + SEC as *complementary* sources (authoritative per-field
   split), not as failover. `resolve_adv_ownership.py` has pymupdf →
   pdfplumber fallback per-file which is compliant. Framework
   `SourcePipeline.fetch()` retrofit should supply multi-source by
   default.

5. **Hardcoded prod DB paths:** `build_managers.py:22`,
   `build_fund_classes.py:19`. Must be migrated to `db.get_db_path()`
   in the framework rewrite so `--staging` works uniformly.

6. **`db.REFERENCE_TABLES` is stale:** lists `holdings` and
   `fund_holdings` (dropped Stage 5). `seed_staging()` would fail on
   those two tables. The framework's
   `scripts/pipeline/registry.reference_tables()` derives the list
   from `DATASET_REGISTRY` and should be preferred once `db.py` adopts it.

7. **`merge_staging.TABLE_KEYS` drift:** entries for
   `beneficial_ownership` and `fund_holdings` (dropped). Silent no-op
   but misleading. Framework adopts
   `scripts/pipeline/registry.merge_table_keys()` instead.

8. **`build_managers.py` bypasses entity staging workflow.** Writes
   `parent_bridge` / `managers` directly to prod. Contradicts INF1
   staging rule. Framework rewrite must route through sync → diff →
   promote like every other entity mutation.
