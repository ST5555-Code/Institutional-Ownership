# Pipeline Inventory — DB-Writing Script Audit

_Prepared: 2026-04-13 — pipeline framework foundation (v1.2)_
_Revised 2026-04-15: six REWRITE items cleared by v2 rewrites shipped this week (fetch_nport_v2 + fetch_dera_nport + promote_nport; fetch_13dg_v2 + promote_13dg; fetch_market v2; build_cusip v2). CUSIP v1.4 vertical (build_classifications, run_openfigi_retry, normalize_securities, validate_classifications) and N-PORT v2 validators (validate_nport, validate_nport_subset) added as new SOURCE-tier rows. Legacy scripts retained in `scripts/` but marked **SUPERSEDED** — retirement gated on second clean v2 run per follow-up tracker._

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
| `promote_nport.py` | staging, prod | `fund_holdings_v2`, `fund_universe`, `ingestion_manifest`, `ingestion_impacts`, `data_freshness`, snapshot | — | — | **OK** (read validation report for Promote-ready: YES; atomic per (series_id, report_month); Group 2 entity enrichment via `entity_current`) |
| `validate_13dg.py` / `promote_13dg.py` | staging, prod | `beneficial_ownership_v2`, `beneficial_ownership_current`, impacts, snapshot | — | — | **OK** (Batch 2B reference vertical) |
| `build_managers.py` | `filings_deduped`, `adv_managers`, `cik_crd_*`, `managers` | `parent_bridge`, `cik_crd_links`, `cik_crd_direct`, `managers` (all DROP+CTAS), **`holdings` ALTER+UPDATE (dropped!)** | `:513-532` ALTER+UPDATE `holdings`; `:534` COUNT `holdings` | §1 no CHECKPOINT; §5 `try/except pass` at `:515-521` hides schema failures; §9 hardcoded prod path at `:22`, no `--staging` | **REWRITE** |
| `build_summaries.py` | **`holdings` (dropped!)** | `summary_by_ticker`, `summary_by_parent`, `data_freshness` | `:73` `FROM holdings h`; `:118` `FROM holdings h` | §9 no `--dry-run`; DDL drift vs prod (see `canonical_ddl.md` §4) | **REWRITE** |
| `build_fund_classes.py` | local N-PORT XML cache, `fund_classes` | `fund_classes`, `lei_reference`, **`fund_holdings` ALTER+UPDATE (dropped!)** | `:139` ALTER `fund_holdings`; `:146-151` UPDATE; `:152` COUNT | §1 CHECKPOINT every 5000 only; §5 silent `pass`; §9 hardcoded prod path at `:19`, no `--dry-run` | **REWRITE** |
| `build_entities.py` | `managers`, `adv_managers`, `fund_universe`, `ncen_adviser_map`, etc. | entity MDM tables (staging only) | none | §1 no per-step CHECKPOINT; §9 staging-only gate is the safety rail | **RETROFIT** |
| `build_benchmark_weights.py` | **`fund_holdings` (dropped!)**, `market_data` | `benchmark_weights` | `:79,:90` `FROM fund_holdings` | **BROKEN IMPORT** `get_connection` did not exist in db.py — fixed this session (D11); §1 no CHECKPOINT; §9 no `--dry-run` | **REWRITE** |
| `build_shares_history.py` | `market_data`, **`holdings` (dropped!)**, SEC XBRL cache | `shares_outstanding_history`, **`holdings.pct_of_float` UPDATE (dropped!)** | `:161-164,:201-203` reads; `:177-184,:190-199` UPDATE `holdings` | §1 CHECKPOINT at end only; §9 no `--dry-run` | **REWRITE** |
| `build_fixture.py` | prod DB (ATTACH READ_ONLY) | fixture DB file only | none (uses `_v2` throughout) | §9 `--dry-run` + `--force` + `--yes` gates; otherwise clean | **OK** |
| `compute_flows.py` | **`holdings` (dropped!)**, `market_data` | `investor_flows`, `ticker_flow_stats`, `data_freshness` | `:69,:78` `FROM holdings WHERE quarter=...` | §9 no `--dry-run` (`--staging` exists) | **REWRITE** |
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

1. **Legacy-table writers CLEARED by v2 rewrites (2026-04-13 → 2026-04-15).**
   Original list had 8 writers + 3 readers touching Stage-5-dropped
   `holdings` / `fund_holdings` / `beneficial_ownership`. Status as of
   2026-04-15:
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
   - Still REWRITE: `load_13f.py` (`holdings` DROP+CTAS — replacing
     with `load_13f_v2.py` in Batch 3), `build_managers.py`,
     `build_fund_classes.py`, `build_shares_history.py`,
     `build_summaries.py`, `build_benchmark_weights.py`,
     `compute_flows.py`. These are the remaining Batch 3 targets; CUSIP
     v1.4 now unblocks the enrichment pattern they all need.

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
