# Pipeline Inventory — DB-Writing Script Audit

_Revised 2026-04-22 (conv-12 — **PHASE 2 + WAVE 2 COMPLETE**). HEAD `b0baebe`. **All six ingest pipelines now run as `SourcePipeline` subclasses** and register in `scripts/pipeline/pipelines.py` → `PIPELINE_REGISTRY`. Admin dashboard live at `/admin/dashboard`. Wave 2 script-level deltas:_

- _**New subclass modules in `scripts/pipeline/`:** `load_13dg.py` (w2-01, `append_is_latest`), `load_market.py` (w2-02, `direct_write`), `load_nport.py` (w2-03, `append_is_latest`), `load_ncen.py` (w2-04, `scd_type2`), `load_adv.py` (w2-05, `direct_write`). Plus `base.py` (concrete `SourcePipeline` ABC with eight-step flow + atomic promote + explicit column list per p2-10-fix) and `cadence.py` (`PIPELINE_CADENCE` + probe_fns + `expected_delta`)._
- _**New in `scripts/`:** `load_13f_v2.py` (p2-05 first full subclass exercise, `Load13FPipeline`, `append_is_latest`)._
- _**Retired to `scripts/retired/` during Wave 2:** `fetch_13dg.py`, `fetch_13dg_v2.py`, `validate_13dg.py`, `promote_13dg.py`, `fetch_market.py`, `fetch_nport.py`, `fetch_nport_v2.py`, `validate_nport.py`, `validate_nport_subset.py`, `promote_nport.py`, `fetch_ncen.py`, `fetch_adv.py`, `promote_adv.py`. All functionality absorbed into the corresponding `load_*.py` subclass; retired copies kept for regression comparison._
- _**Kept in `scripts/`:** `fetch_dera_nport.py` (DERA ZIP transport helper imported by `pipeline/load_nport.py` on the staging connection); `scripts/pipeline/nport_parsers.py` (shared XML parsing library)._
- _**Migrations 015–017 applied prod + staging:** 015 amendment-semantics columns (`is_latest`, `loaded_at`, `backfill_quality`) on the three amendable fact tables + `accession_number` on `fund_holdings_v2`; 016 `admin_preferences` control-plane table; 017 `valid_from` / `valid_to` on `ncen_adviser_map` for SCD Type 2._
- _**Legacy `run_script` allowlist** in `scripts/admin_bp.py` still references retired paths — tracked as P2-FU-01 in `ROADMAP.md` "Deferred" (trigger: Q1 2026 cycle clean on V2). `scheduler.py`, `update.py`, `benchmark.py` stale-reference audit absorbed by the same item._

_Prior revision header (phase2-prep — REMEDIATION PROGRAM COMPLETE). Remediation Program closed (105 PRs #5–#105, ~66 items; `archive/docs/REMEDIATION_PLAN.md §Changelog`, archived 2026-04-25). Script-level deltas reflected below in-row:_
- _`fetch_adv.py` — **STAGING→PROMOTE** split (mig-02, PR #37). Writes to staging; new `promote_adv.py` handles prod atomicity._
- _`promote_adv.py` — **NEW** (mig-02). Atomic promote for ADV data._
- _`resolve_agent_names.py` / `resolve_bo_agents.py` / `resolve_names.py` — **RETIRED** to `scripts/retired/` (sec-06, PR #48). Target tables dropped._
- _`backfill_manager_types.py` — **HARDENED** (sec-06, PR #48): `--dry-run` + CHECKPOINT discipline._
- _`enrich_tickers.py` — **HARDENED** (sec-06, PR #48): dead holdings writes removed; `--dry-run` + CHECKPOINT._
- _`build_fund_classes.py` — **REWRITE CLOSED** (batch-3-tail, 2026-04-23): retrofit bar reached — `--dry-run` + explicit `parse_error` / `lei_error` counters (§5 silent-pass killed) + CHECKPOINT every 2,000 XMLs (§1). Prior sec-05 retrofit (`--staging`, `seed_staging`, `--enrichment-only`) retained._
- _`build_benchmark_weights.py` — **RETROFIT CLOSED** (sec-05, PR #45): `--staging` fixed + `seed_staging`._
- _`build_entities.py` — **RETROFIT CLOSED** (mig-13, PR #63): 9 per-step CHECKPOINTs added._
- _`merge_staging.py` — **RETROFIT CLOSED** (mig-13 PR #63 + int-14 PR #85): `TABLE_KEYS` sourced from `scripts/pipeline/registry.merge_table_keys()`; NULL-only merge mode shipped; error handling fixed._
- _`audit_read_sites.py` — **NEW** (mig-07, PR #101): codebase read-site scanner for mechanical rename-sweep discipline._
- _`build_fixture.py` — **UPDATED** (mig-08, PR #86): writes `_fixture_metadata` provenance table; CI staleness gate active._
- _`fix_fund_classification.py` — **RETROFIT CLOSED** (int-22, PR #76): CHECKPOINT added._
- _`refetch_missing_sectors.py` — **RETROFIT CLOSED** (int-15, PR #90): `fetch_date` + `metadata_date` stamped on UPDATE._

_Revised 2026-04-17 (session #11 close): **DM15 fully closed + 13D/G filer resolution + N-CEN hardening.** **New script — `scripts/resolve_13dg_filers.py`** (commit `5efae66`, status **OK**): two-pass resolver for the 2,591 unmatched `beneficial_ownership_v2` filer CIKs. Staging pass: 23 MERGE (CIK identifier adds to existing entities via AUM-tiebreaker name match + manual overrides) + 1,640 NEW_ENTITY (full 5-artifact creates: entity + alias + identifier + classification + self-rollup both worldviews). Prod-direct pass (`--prod-exclusions` flag, mutually exclusive with `--staging`): 928 exclusions to `pending_entity_resolution` (source_type='13DG'; resolution_status='excluded_individual'/'excluded_law_firm'/'excluded_other'). Split because `pending_entity_resolution` is not in `db.ENTITY_TABLES` so staging→promote doesn't carry it. CIK 10-digit zero-padding on read; per-CIK dedupe on filing_count tiebreak; word-boundary ILIKE guard for short target names (mirrors `resolve_pending_series.py:526-534`); AUM-tiebreaker via prod read-only connection (holdings_v2 not mirrored to staging); Credit Suisse → UBS special case; MANUAL_TARGET_OVERRIDES dict (GIC → NEW_ENTITY/SWF, Insight Partners → 4505, Apollo Global Management → 9576). Reads `data/reference/13dg_filer_research_v2.csv` (2,776 rows, human-reviewed). **fetch_ncen.py updates** (status: OK, still flagged RETROFIT per §cross-cutting): (1) `--ciks <comma-list>` CLI flag (commit `9ce5b17`) — scoped fetch for caller-supplied registrant CIK list, bypasses fund_universe + processed filter, zero-pads to 10. Used to close DM15b coverage gap on 10 silent-fetch-failure trusts (+103 adviser-series rows, 0 errors). (2) Managers-table guard (commit `ef7fb13`) — `update_managers_adviser_cik` now probes for the table before running (Stage 5 dropped the legacy `managers` table). (3) ncen_adviser_map dedupe + idempotent insert guard (commit `8323838`) — prevents duplicate rows on re-runs. **New apply scripts:** `scripts/dm15_layer2_apply.py` (`938e435`, 17 retargets / $8.95B, override IDs 205-221); `scripts/dm15c_amundi_sa_apply.py` (`9160030`, 12 Amundi geo reroutes + eid=2214 rename/reclassify + eid=752 reclassify, override IDs 222-245). Prior session #10 header preserved below._

_Revised 2026-04-17 (session #10 close): **`promote_nport.py` + `promote_13dg.py` batch rewrite shipped (`6f4fdfc`).** Per-(series_id, report_month) DELETE+INSERT+CHECKPOINT loop in `promote_nport.py` replaced with single batch `DELETE FROM fund_holdings_v2 WHERE (series_id, report_month) IN (_promote_scope)` + single `INSERT ... FROM` staged pull + single CHECKPOINT. DERA-scale promote runtime: 2+ hours → seconds. `promote_13dg.py` was already batch-oriented at the BO v2 row level (single DELETE + INSERT keyed on `accession_number`) — no perf rewrite needed there; the same audit-preservation fix (see below) was applied to its inline manifest/impacts mirror block. **`_mirror_manifest_and_impacts` audit-wipe bug fixed** in both scripts: previously the staging mirror wiped all prod `ingestion_impacts` rows for the run before copying staging versions (which always have `promote_status='pending'` because staging never marks impacts promoted). The post-promote UPDATE then only restored status for the currently-scoped tuples — every re-promote silently lost audit history for impacts outside scope. Fix: DELETE only impacts not already `promoted`, INSERT only impacts not already present. Additionally the batch impact UPDATE's `unit_key_json IN (...)` clause was previously passing Python `(sid, rm)` tuples where JSON-serialized strings were expected, so the match never fired — now uses a TEMP dataframe of pre-serialized `unit_key_json` strings and `IN (SELECT ...)`. SQL audit-trail reconciliation workaround documented in prior caveats (sessions #8 and #9) is no longer needed going forward. **Other session #10 scripts (new):** `scripts/bootstrap_tier_c_wave2.py` (Palmer Square 24862, Rayliant 24863, Victory Capital Holdings 24864); `scripts/dm14c_voya_amundi_apply.py` (Voya DM14c 108-series retarget + Amundi US → Victory Capital merger encoding). `scripts/resolve_pending_series.py` gained a longest-match tiebreaker in `try_brand_substring` (fixes Exchange Listed Funds Trust T2_ambiguous) and 4 new SUPPLEMENTARY_BRANDS entries (EXCHANGE LISTED FUNDS TRUST→3738, TEMA ETF→7238, PALMER SQUARE FUNDS→24862, RAYLIANT FUNDS→24863)._

_Prepared: 2026-04-13 — pipeline framework foundation (v1.2)_
_Revised 2026-04-17 (session #6 close): **Migration 006 shipped** (`ffccb92`) — `scripts/migrations/006_override_id_sequence.py` (new, ~200 lines) creates `override_id_seq` starting from `MAX(override_id)+1`, adds `DEFAULT nextval('override_id_seq')` + `NOT NULL` on `entity_overrides_persistent.override_id`. Ran idempotently on staging + prod. Combined with the 2026-04-16 DM14 promote side-effect (58 NULL rows → 25-82), `entity_overrides_persistent` now has full sequence + NOT NULL PK and is fully keyed (90 rows, 0 NULL). Runtime MAX+1 helpers in `scripts/promote_staging.py` (`_heal_override_ids`), `scripts/admin_bp.py` (`api_admin_entity_override`), and `scripts/dm14_layer1_apply.py` are now redundant backstops — left in place, harmless. **Applied migrations:** 001 (baseline) → 002 (DERA ZIP extensions on `ingestion_impacts`) → 003 (CUSIP v1.4: `cusip_classifications` + `cusip_retry_queue` + `_cache_openfigi` + `schema_versions` + 7 new `securities` columns) → 004 (`summary_by_parent` PK with `rollup_type`) → 005 (`beneficial_ownership_v2` rollup columns) → 006 (`override_id` sequence + NOT NULL). `scripts/migrations/add_last_refreshed_at.py` also live (`entity_relationships.last_refreshed_at`, 2026-04-16, no numbered migration file). **Market refresh operational close** — `fetch_market.py` (PID 78767) completed overnight 2026-04-16; `market_data` 10,064 rows stamped 23:27 UTC. `enrich_holdings.py --fund-holdings` re-run delivered mvl +445K, pof +127K, fund ticker +488K. `build_summaries.py --rebuild` re-ran with fresh mvl. `make freshness` now **PASS** — all 7 critical tables OK._
_Revised 2026-04-16 (extended — session close): DM13 BlueCove sweep complete (`ef3f302`). `scripts/pipeline/manifest.py` gained `_next_id(con, table, pk_col)` helper (`11a35e9`) — computes MAX+1 inline for `ingestion_manifest.manifest_id` and `ingestion_impacts.impact_id`, bypassing broken DuckDB sequences that don't auto-advance on explicit-PK INSERTs from promote mirror paths. `get_or_create_manifest_row` + `write_impact` now use `_next_id` instead of DEFAULT nextval. `scripts/promote_staging.py` gained `_heal_override_ids()` (`bb444d7`) — CTAS rebuild assigns deterministic sequential IDs to NULL `entity_overrides_persistent.override_id` rows before diff; runs against both prod and staging connections. `scripts/admin_bp.py` INSERT computes override_id via MAX+1. BL-8: `.pre-commit-config.yaml` ruff ignore list reduced to `E501,E402,E701,F841` (F541 removed after 9 violations fixed); pylint disable list reduced — W0621 + W0622 removed (W0621 6 violations fixed inline; W0622 4 intentional shadows have permanent inline `# pylint: disable=redefined-builtin` comment)._
_Revised 2026-04-16 (final — session close): freshness gate fully wired (commit `54bfaad`). `enrich_holdings.py` now stamps `holdings_v2` alongside `holdings_v2_enrichment` — the L3 canonical 13F table previously had no owning freshness writer because Stage 5 dropped the legacy `holdings` table and a v2 loader isn't built yet; enrichment is the only regular-cadence script against the full table. `market_data` retro-stamped with actual `fetch_date=2026-04-05` so `make freshness` correctly reports STALE 11d rather than MISSING; `fetch_market.py:944-950` stamping hook was already wired, just awaiting a real run. 6 of 7 gated tables now OK (`holdings_v2`, `fund_holdings_v2`, `investor_flows`, `ticker_flow_stats`, `summary_by_parent`, `beneficial_ownership_current`); `market_data` remains STALE until `fetch_market.py` runs. **BL-8 suppression inventory complete.** 245 inline suppressions documented (87 `# noqa` — mostly E402 on legacy `sys.path.insert`; 73 `# pylint: disable` — mostly broad-except in pipeline code; 85 `# nosec` — mostly B608 on known-safe dynamic SQL). 5 pre-commit rules re-enabled as independently revertible commits (`61f028c`..`4af2071`): ruff E702, ruff E731, pylint W0611, W0702, E0611. E0401 attempted + reverted — pylint hook's `additional_dependencies` lacks `pydantic` / `curl_cffi`. Deferred: category (b) small-fix candidates (9-violation F541 + 1-9 violations on ~15 other rules) and category (c) bulk cleanups (E501 908, W0718 163, B608 239)._
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

**Post-Wave-2 update (2026-04-22, conv-12).** `fetch_ncen.py` (and `fetch_13dg.py`, `fetch_adv.py`, `fetch_market.py`, `fetch_nport.py`) retired to `scripts/retired/`. Freshness stamping on their respective target tables is now owned by the `SourcePipeline` subclasses in `scripts/pipeline/` — `load_ncen.py` owns `ncen_adviser_map` stamping (via scd_type2 promote path); `load_13dg.py` owns `beneficial_ownership_v2` + `beneficial_ownership_current`; `load_adv.py` owns `adv_managers`; `load_market.py` owns `market_data`; `load_nport.py` owns `fund_holdings_v2` + `fund_universe`. The retired scripts are kept at `scripts/retired/` as frozen reference copies and are **not** imported as library helpers — `load_ncen.py` reimplements the EDGAR fetch/parse helpers inline (see `scripts/pipeline/load_ncen.py:163` and `:232`). The `RETROFIT` cross-cutting flag previously carried on `fetch_ncen.py` (cited in the session #11 narrative above) is cleared by retirement.

---


Every `.py` file in `scripts/` that writes to the prod DB, plus the
utilities the orchestrator needs to know about. Scripts flagged for
RETIRE are listed separately at the bottom and are intentionally not
audited for PROCESS_RULES violations.

| Script | Reads from | Writes to | Legacy refs (file:line) | PROCESS_RULES violations | Action |
|---|---|---|---|---|---|
| `fetch_13f.py` | (none) | filesystem only (`data/raw`, `data/extracted`) | none | none (no DB writes) | **OK** |
| `scripts/pipeline/load_nport.py` | EDGAR, DERA ZIPs via `fetch_dera_nport` | `stg_nport_holdings`, `stg_nport_fund_universe`, `fund_holdings_v2` (is_latest append), `fund_universe`, `ingestion_manifest`, `ingestion_impacts`, `data_freshness` | — | — | **OK** (w2-03 `SourcePipeline` subclass `LoadNPortPipeline`, `append_is_latest`; absorbs retired `fetch_nport_v2.py` + `validate_nport*.py` + `promote_nport.py`; scope shapes: `{"quarter":"YYYYQN"}` DERA bulk, `{"monthly_topup":True}` XML topup, `{"month":"YYYY-MM"}`, `{"zip_path":"..."}`, `{"exclude_file":"..."}`) |
| `scripts/retired/fetch_nport_v2.py` | — | — | — | — | **RETIRED** (w2-03, absorbed by `pipeline/load_nport.py`) |
| `fetch_dera_nport.py` | SEC DERA ZIPs (`{YYYY}q{N}_nport.zip`) | staging tables (via `fetch_nport_v2`) | — | — | **OK** (transport + parity harness; `--zip` flag for local ZIPs; cross-ZIP amendment dedup live 2026-04-15) |
| `scripts/retired/fetch_nport.py` (retired) | (not in active pipeline) | N/A — retired | n/a (moved out of `scripts/`) | **RETIRED 2026-04-18 (BLOCK-3 Phase 4)** — helpers (`parse_nport_xml`, `classify_fund`) live at `scripts/pipeline/nport_parsers.py`. File kept functional in `scripts/retired/` for regression comparison against the 2026-04-17 pre-audit backup. | **RETIRED** |
| `scripts/pipeline/load_13dg.py` | EDGAR efts, `listed_filings_13dg`, `beneficial_ownership_v2` | `beneficial_ownership_v2` (is_latest append), `beneficial_ownership_current`, `fetched_tickers_13dg`, `listed_filings_13dg`, `ingestion_manifest`, `ingestion_impacts`, `data_freshness` | — | — | **OK** (w2-01 `SourcePipeline` subclass `Load13DGPipeline`, `append_is_latest`; absorbs retired `fetch_13dg_v2.py` + `validate_13dg.py` + `promote_13dg.py`; Group 2 entity enrichment via `bulk_enrich_bo_filers` runs at promote time) |
| `scripts/retired/fetch_13dg_v2.py`, `scripts/retired/fetch_13dg.py`, `scripts/retired/validate_13dg.py`, `scripts/retired/promote_13dg.py` | — | — | — | — | **RETIRED** (w2-01, absorbed by `pipeline/load_13dg.py`) |
| `scripts/pipeline/load_adv.py` | SEC ADV ZIP (HTTP) | `adv_managers` (direct_write UPSERT on crd), `ingestion_manifest`, `ingestion_impacts`, `data_freshness` | none | — | **OK** (w2-05 `SourcePipeline` subclass `LoadADVPipeline`, `direct_write`; absorbs retired `fetch_adv.py` + `promote_adv.py`; ADV SCD conversion deferred — `adv_managers` carries no `valid_from`/`valid_to` today; `cik_crd_direct` + `lei_reference` stay under `build_managers.py`) |
| `scripts/retired/fetch_adv.py`, `scripts/retired/promote_adv.py` | — | — | — | — | **RETIRED** (w2-05, absorbed by `pipeline/load_adv.py`) |
| `scripts/pipeline/load_market.py` | `market_data`, `securities`, `holdings_v2`, `fund_holdings_v2`, `cusip_classifications` | `market_data` (direct_write UPSERT on ticker), `ingestion_manifest`, `ingestion_impacts`, `data_freshness` | — | — | **OK** (w2-02 `SourcePipeline` subclass `LoadMarketPipeline`, `direct_write`; absorbs retired `fetch_market.py`; scope shapes: `{}` → `discover_market` stale universe, `{"tickers":[...]}`, `{"stale_days":N}`; `parse()` ATTACHes prod RO and COALESCEs against it so promote preserves untouched columns) |
| `scripts/retired/fetch_market.py` | — | — | — | — | **RETIRED** (w2-02, absorbed by `pipeline/load_market.py`) |
| `fetch_finra_short.py` | `short_interest` | `short_interest` | none | §9 `--test` still writes to prod; otherwise clean (CHECKPOINT per 50k, restart-safe via loaded_dates, 429 backoff) | **RETROFIT** |
| `scripts/pipeline/load_ncen.py` | `fund_universe`, `managers`, entity tables (staging), `ncen_adviser_map` | `ncen_adviser_map` (scd_type2 with `valid_from`/`valid_to` per migration 017), `managers.adviser_cik`, `ingestion_manifest`, `ingestion_impacts`, `data_freshness` | — | — | **OK** (w2-04 `SourcePipeline` subclass `LoadNCENPipeline`, `scd_type2` — first SCD Type 2 subclass; absorbs retired `fetch_ncen.py`; amendment_key `(series_id, adviser_crd, role)`; open-row sentinel `DATE '9999-12-31'`) |
| `scripts/retired/fetch_ncen.py` | — | — | — | — | **RETIRED** (w2-04, absorbed by `pipeline/load_ncen.py`) |
| `load_13f.py` (legacy, break-glass) | TSV files | N/A — out of scheduled paths | — | — | **OUT OF SCHEDULED PATHS** (V2 cutover phase-b2-5, 2026-04-23). Retained on disk as break-glass fallback until phase B3 (2-cycle gate, ~Aug 2026). Still owns `raw_submissions`/`raw_infotable`/`raw_coverpage` writes per `scripts/pipeline/registry.py:69,74,79` — V2 does not write raw_*. |
| `load_13f_v2.py` | TSV files | `filings`, `filings_deduped`, `other_managers`, `holdings_v2` (is_latest append), `ingestion_manifest`, `ingestion_impacts`, `data_freshness` | — | — | **OK — primary 13F loader** (p2-05 `SourcePipeline` subclass `Load13FPipeline`, `append_is_latest`; cut over phase-b2-5, 2026-04-23). Does NOT write `raw_*` (V1 still owns those until B3). |
| `refetch_missing_sectors.py` | `/tmp/refetch_tickers.txt`, Yahoo | `market_data.sector/industry` (staging only) | none | — | **OK** (retrofit closed int-15 PR #90: `fetch_date` + `metadata_date` stamped on UPDATE) |
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
| `dm14_layer1_apply.py` | staging entity MDM | `entity_rollup_history`, `entity_overrides_persistent` (staging only) | — | — | **OK** (one-off 2026-04-16, commit `d684e4e`; hardcoded 8-row CANDIDATES list; idempotent via `(series_id, target_cik)` override dedup; SCD close + new manual_override row per fund; still_valid=TRUE explicit to survive sync_staging CTAS column-default drop) |
| `dm14b_apply.py` | staging entity MDM | `entity_relationships` (+6), `entity_rollup_history` (91 retargets), `entity_overrides_persistent` (+91) | — | — | **OK** (one-off 2026-04-17, commit `3c99365`; single-transaction handler for 3 steps — edge insert / chain-walk retarget / override insert; verifies scope from prod before apply; idempotent via rel uniqueness + override dedup; does not extend `dm14_layer1_apply.py`) |
| `dm15_layer1_apply.py` | staging entity MDM | `entity_rollup_history` (15 retargets), `entity_overrides_persistent` (+15) | — | — | **OK** (one-off 2026-04-17, commit `7bb68f5`; mirrors DM14 Layer 1 pattern; hardcoded 15-row CANDIDATES list for N-CEN-driven external sub-adviser coverage; 2 rows carry NULL `new_value` for CIK-less Smith Capital targets — unblocked by migration 007) |
| `inf23_apply.py` | staging entity MDM | `entity_identifiers` (+1 Milliman CIK), `entity_relationships` (171 re-pointed), `entity_rollup_history` (43 retargets + 4 `merged_into` + 4 source closes), `entity_aliases` (+2 / −2), `entity_classification_history` (−2), `entity_overrides_persistent` (+2 CRD→CIK merges + 6 updates) | — | — | **OK** (one-off 2026-04-17, commit `53d6e7b`; single-transaction handler for 4 items — Milliman CIK backfill / Morningstar merge 19596→10513 / DFA merge 18096→5026 / DM15 NULL-CIK backfill; INF4/INF6/INF8 merge pattern) |
| `build_managers.py` | `filings_deduped`, `adv_managers`, `cik_crd_*`, `managers` | `parent_bridge`, `cik_crd_links`, `cik_crd_direct`, `managers` (all DROP+CTAS), **`holdings` ALTER+UPDATE (dropped!)** | `:513-532` ALTER+UPDATE `holdings`; `:534` COUNT `holdings` | §1 no CHECKPOINT; §5 `try/except pass` at `:515-521` hides schema failures; §9 hardcoded prod path at `:22`, no `--staging` | **REWRITE** |
| `build_summaries.py` (v2) | `holdings_v2`, `fund_holdings_v2` | `summary_by_ticker`, `summary_by_parent`, `data_freshness` | — | — | **OK** (rewritten 2026-04-16, commit `87ee955`; rollup_type doubled INSERT for `summary_by_parent`; `total_value` uses `COALESCE(market_value_live, market_value_usd)` for graceful pre/post-enrich behavior; N-PORT side scoped to latest report_month per series_id; `--staging --dry-run --rebuild`; per-quarter × per-worldview CHECKPOINT) |
| `enrich_holdings.py` | `holdings_v2`, `fund_holdings_v2`, `cusip_classifications`, `securities`, `market_data`, `shares_outstanding_history` | `holdings_v2.{ticker, security_type_inferred, market_value_live, pct_of_so, pct_of_so_source}`, `fund_holdings_v2.ticker`, `data_freshness('holdings_v2_enrichment')` | — | — | **OK** (new 2026-04-16, commit `559058d`; pct-of-so workstream shipped 2026-04-19, merge `8925347` + follow-on `12e172b`; cusip-keyed lookup `UPDATE...FROM`; Pass A NULL cleanup + Pass B main enrichment + Pass C fund_holdings_v2 ticker; `--staging --dry-run --quarter --fund-holdings`; per-pass CHECKPOINT. **Pass B SOH ASOF three-tier denominator**: computes `pct_of_so` via period-accurate ASOF lookup on `shares_outstanding_history` keyed by `(ticker, as_of_date ≤ report_date)`; three-tier fallback hierarchy resolves per row — (1) `soh_period_accurate` when the SOH ASOF match is present, (2) `market_data_so_latest` when SOH has no row ≤ `report_date` (fallback to latest `market_data.shares_outstanding`), (3) `market_data_float_latest` when `shares_outstanding` is NULL (last-resort fallback to latest `market_data.float_shares`). Audit stamp: `pct_of_so_source` column populated per row with the resolved tier. Migration 008 (`ea4ae99` amended) renamed `pct_of_float → pct_of_so` and added `pct_of_so_source VARCHAR` in the same transaction using the capture-and-recreate idiom; see `docs/data_layers.md` Appendix A.2 § Migration patterns — index-preserving RENAME.) |
| `build_fund_classes.py` | local N-PORT XML cache, `fund_classes`, `fund_holdings_v2` | `fund_classes`, `lei_reference`, `fund_holdings_v2.lei` (ALTER+UPDATE) | — | — | **OK** (REWRITE closed 2026-04-23, `build-fund-classes-rewrite`: `--dry-run` + read-only conn; `parse_error` / `lei_error` counters with >1% WARN gate; `_get_existing_classes` scoped to `CatalogException` only; `enrich_fund_holdings_v2` probes `information_schema` instead of try/except/ALTER; CHECKPOINT every 2,000 XMLs. Prior sec-05 PR #45 retrofit preserved.) |
| `build_entities.py` | `managers`, `adv_managers`, `fund_universe`, `ncen_adviser_map`, etc. | entity MDM tables (staging only) | none | — | **OK** (retrofit closed mig-13 PR #63: 9 per-step CHECKPOINTs added) |
| `build_benchmark_weights.py` | `fund_holdings_v2`, `market_data` | `benchmark_weights` | — | — | **OK** (retrofit closed sec-05 PR #45: `--staging` fixed + `seed_staging`) |
| `build_shares_history.py` | `market_data`, **`holdings` (dropped!)**, SEC XBRL cache | `shares_outstanding_history`, **`holdings.pct_of_float` UPDATE (dropped!)** | `:161-164,:201-203` reads; `:177-184,:190-199` UPDATE `holdings` | §1 CHECKPOINT at end only; §9 no `--dry-run` | **REWRITE** |
| `build_fixture.py` | prod DB (ATTACH READ_ONLY) | fixture DB file only (writes `_fixture_metadata` provenance row) | none | — | **OK** (mig-08 PR #86: `_fixture_metadata` provenance + CI staleness gate) |
| `audit_read_sites.py` | filesystem (codebase) | none — stdout report | none | — | **OK** (NEW 2026-04-22, mig-07 PR #101: read-site scanner for mechanical rename-sweep discipline) |
| `compute_flows.py` (v2) | `holdings_v2`, `market_data` | `investor_flows`, `ticker_flow_stats`, `data_freshness` | — | — | **OK** (rewritten 2026-04-16, commit `87ee955`; investor key = `rollup_entity_id` + `rollup_name`; `inst_parent_name` retained for back-compat = `rollup_name` for active worldview; per-period × per-worldview INSERT — EC + DM both written; value column = `market_value_usd` Group 1 not `market_value_live`; `WHERE ticker IS NOT NULL AND ticker != ''` filter; `--staging --dry-run`) |
| `scripts/pipeline/protocol.py` | (none) | (none) | none | N/A (library) | **OK** (v1.2 framework — three structural `typing.Protocol` contracts: `SourcePipeline` (EDGAR full discover→fetch→parse→load→validate→promote), `DirectWritePipeline` (market/FINRA reference upsert), `DerivedPipeline` (L4 compute); all end with `stamp_freshness()`; `@runtime_checkable` for orchestrator dispatch) |
| `scripts/pipeline/discover.py` | EDGAR/SEC indices, `ingestion_manifest` (anti-join) | (none — read-only) | none | N/A (library) | **OK** (v1.2 framework — per-source `discover_*` functions return `list[DownloadTarget]`; `PIPELINE_CADENCE` probes feed orchestrator scheduling; manifest anti-join keeps discovery cheap + idempotent across runs; 13D/G scoped via `SCOPED_13DG_TEST_TICKERS` until proven) |
| `scripts/pipeline/id_allocator.py` | `ingestion_manifest`, `ingestion_impacts` | (none — pure allocator) | none | N/A (library) | **OK** (obs-03 Phase 1 — centralized PK allocator: `allocate_id(con, table, pk_col)` + `reserve_ids(con, table, pk_col, n)`; advisory `fcntl.flock` on `data/.ingestion_lock` prevents torn MAX+1 allocations in staging→prod mirror; replaces inline `_next_id` in `manifest.py` + deleted bypass in `shared.py`) |
| `scripts/pipeline/cusip_classifier.py` | (caller-passed row dict) | (none — pure logic) | none | N/A (library) | **OK** (CUSIP v1.4 — pure classification rules: `classify_cusip()` STEP 0 normalize → STEP 1 derivative pre-check → STEP 2 market_sector map → STEP 3 combined seed → STEP 4 `CANONICAL_TYPE_RULES`; no DB writes — callers `build_classifications.py` + rewritten `build_cusip.py` own persistence) |
| `entity_sync.py` | entity tables | entity tables + staging | none | N/A (library) | **OK** |
| `sync_staging.py` | prod (ATTACH READ_ONLY) | staging CTAS | none | §9 `--dry-run` OK; clean | **OK** |
| `diff_staging.py` | prod + staging (READ_ONLY) | log file only | none | read-only | **OK** |
| `promote_staging.py` | staging + prod entity tables | prod entity tables, snapshot tables | none | §9 `--approved` gate; atomic + rollback; clean | **OK** |
| `merge_staging.py` | staging + prod | prod (upsert by PK, NULL-only, or DROP+CTAS) | — | — | **OK** (retrofit closed mig-13 PR #63 + int-14 PR #85: `TABLE_KEYS` sourced from `scripts/pipeline/registry.merge_table_keys()`; NULL-only merge mode; error handling fixed) |
| `migrate_batch_3a.py` | in-code pattern dict | `fund_family_patterns`, `data_freshness` | none | §9 `--dry-run` + `--prod` gates | **OK** |
| `rollback_promotion.py` | prod snapshot tables | prod (via promote_staging) | none | thin wrapper | **OK** |
| `validate_entities.py` | all entity tables | log file | none | read-only validator; keep (used by `promote_staging.py` auto-gate) | **OK** |
| `resolve_long_tail.py` | entity staging, SEC EDGAR | entity staging tables, CSVs | none | §1 no per-500 CHECKPOINT in loop (`:147-229`); otherwise clean | **RETROFIT** |
| `resolve_adv_ownership.py` | `adv_managers`, entity staging, local PDFs | entity staging, CSVs | none | §1 file-checkpoint only, no DB CHECKPOINT inside `run_match`; otherwise clean | **RETROFIT** |
| `fix_fund_classification.py` | `fund_universe` | `fund_universe.is_actively_managed` | none | — | **OK** (retrofit closed int-22 PR #76: CHECKPOINT added) |
| `benchmark.py` | (none) | (none) | none | orchestrator-only | **OK** |
| `scheduler.py` | `data/schedule.json` | `data/schedule.json` + subprocesses | none | orchestrator-only | **OK** |

---

## RETIRE (do not audit; documented for visibility)

These scripts are scheduled for deletion. They are not covered by the
pipeline framework rewrite and do not participate in the orchestrator.

- `update.py`
- `unify_positions.py`
- `auto_resolve.py`
- `enrich_tickers.py` — **HARDENED 2026-04-22** (sec-06, PR #48): dead holdings writes removed; `--dry-run` + CHECKPOINT added. Scheduled for deletion but safe to run in the interim.
- `approve_overrides.py`
- `backfill_manager_types.py` — **HARDENED 2026-04-22** (sec-06, PR #48): `--dry-run` + CHECKPOINT added. Standing curation tool per INF37; scheduled for deletion when curation workflow retires.
- `normalize_names.py`
- `reparse_13d.py`
- `reparse_all_nulls.py`
- `resolve_agent_names.py` — **RETIRED 2026-04-22** (sec-06, PR #48) to `scripts/retired/`. Target table dropped.
- `resolve_bo_agents.py` — **RETIRED 2026-04-22** (sec-06, PR #48) to `scripts/retired/`. Target table dropped.
- `resolve_names.py` — **RETIRED 2026-04-22** (sec-06, PR #48) to `scripts/retired/`. Target table dropped.
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
   - Still REWRITE: `build_managers.py`,
     `build_fund_classes.py`, `build_shares_history.py`,
     `build_benchmark_weights.py`. The Batch 3 trio is now closed;
     the remaining REWRITEs are scoped for future framework work but
     no longer block any analytical workflow.

2. **`--dry-run` coverage — SOLVED at framework level (Phase 2).** Every `SourcePipeline` subclass gets `--dry-run` for free via the base-class eight-step orchestrator: steps 1–4 run staging writes + validation + diff, step 5+ gated on user approval through `/admin/runs/{id}/approve`. The six migrated pipelines (13F, 13D/G, N-PORT, market, N-CEN, ADV) now have uniform dry-run semantics. Standalone scripts still needing coverage: `merge_staging.py` ✓, `sync_staging.py` ✓, `promote_staging.py` ✓, `migrate_batch_3a.py` ✓, `build_fixture.py` ✓, `resolve_long_tail.py` ✓, `fetch_finra_short.py`, `resolve_adv_ownership.py`.

3. **CHECKPOINT discipline — SOLVED at framework level (Phase 2).** `SourcePipeline.promote()` wraps every mutation in a single BEGIN/COMMIT + explicit CHECKPOINT. Per-batch CHECKPOINT lives inside `_promote_append_is_latest`, `_promote_scd_type2`, `_promote_direct_write`. Remaining per-loop CHECKPOINT cases are on reference / L4 writers (`fetch_finra_short.py`, `build_entities.py` step-level, `build_summaries.py` per-worldview) — all already wired per their retrofit closeouts.

4. **`§3 multi-source failover` is rare.** `fetch_13dg.py` has primary
   (edgar) + curl fallback for the filing body only. `fetch_market.py`
   uses Yahoo + SEC as *complementary* sources (authoritative per-field
   split), not as failover. `resolve_adv_ownership.py` has pymupdf →
   pdfplumber fallback per-file which is compliant. Framework
   `SourcePipeline.fetch()` retrofit should supply multi-source by
   default.

5. **Hardcoded prod DB paths:** `build_managers.py:22` (CLEARED
   Rewrite5 `223b4d9`), `build_fund_classes.py:19` (CLEARED sec-05
   PR #45 — uses `db.get_db_path()`). Framework rewrites now
   standardize on `db.get_db_path()` so `--staging` works uniformly.

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

9. **BL-8 lint campaign (2026-04-16/17).** Category (a) and (b) closed:
   `E702`, `E731`, `W0611`, `W0702`, `E0611`, `F541`, `W0621`, `W0622`,
   `W0212`, `W0603`, `W0613` all re-enabled in pylint / ruff with
   codebase-wide fixes (commits `61f028c`, `869c4c2`, `5f2e898`,
   `73a40d8`, `4af2071`, `4590887`, `d59b6fb`, `ad9775b`, `d629639`,
   `a7ca962`, `67e10ba`, `f886efd`, `7c51a21`). `E0401` reverted
   (`7eb74e3`, `1441d2b`) — pre-commit's isolated env lacks `pydantic`
   / `curl_cffi` so suppression warranted until hook deps expand.
   Current pylint global disable list: `C, R, W0108, W0612, W0640,
   W0718, W1309, W1510, W1514, I1101, E0401, E0606`. **Category (c)
   remaining** for future bulk fix: E501 (908), E402 (21), W0718
   (163), B608 (239 — blocked on `queries.py` SQL restructure).
