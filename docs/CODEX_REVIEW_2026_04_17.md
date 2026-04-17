# Codex Review — 2026-04-17

**Active issue at review time:** prod `fund_holdings_v2` is still materially degraded, not just misdocumented: current read-only SQL shows 40.09% `entity_id` coverage overall and 0.18% for `report_month='2025-11'`. I did not find evidence of an app outage during this pass, but I did find live analytical drift.

## Meta
- HEAD at review: `da418a1e8cf766db8089026c2d50ef981ae41ae1`
- Atlas consumed: `.claude/worktrees/competent-meitner-ac5cdf/docs/SYSTEM_ATLAS_2026_04_17.md` (54,581 bytes, 675 lines)
- Docs consumed: `ROADMAP.md`, `ARCHITECTURE_REVIEW.md`, `ENTITY_ARCHITECTURE.md`, `MAINTENANCE.md`, `REACT_MIGRATION.md`, `Plans/admin_refresh_system_design.md`, `docs/PROCESS_RULES.md`, `docs/pipeline_inventory.md`, `docs/pipeline_violations.md`, `docs/data_layers.md`, `docs/CLASSIFICATION_METHODOLOGY.md`, `docs/NEXT_SESSION_CONTEXT.md`, `docs/endpoint_classification.md`, remaining `docs/*.md`; note that the prompt's `docs/admin_refresh_system_design.md` and `docs/data_sources.md` currently resolve to `Plans/admin_refresh_system_design.md` and `Plans/data_sources.md` instead (`Plans/admin_refresh_system_design.md:31`, read-only repo check)
- Code surface covered: 115 scripts, 44,650 lines under `scripts/` (read-only repo scan)
- Total findings: 39 (AGREE-WITH-ATLAS: 27, DISAGREE-WITH-ATLAS: 5, NEW: 7)

## 1. Five Original Contradictions — Status

| Item | Status | Evidence | Contradiction mechanism |
|---|---|---|---|
| 1. Snapshot mechanism conflict | **CONFIRMED** | Design introduces per-run backup snapshots at `data/backups/{pipeline}_{run_id}.duckdb` as a new framework step [`Plans/admin_refresh_system_design.md:76`, `:758-760`]. Existing code already has two snapshot mechanisms: entity-table rollback snapshots inside prod DB [`scripts/promote_staging.py:8-15`, `:67-101`, `:359-360`, `:440-451`] and the read-only app snapshot refresh path [`scripts/promote_nport.py:27`, `:502`; `scripts/promote_13dg.py:17`, `:311`; `scripts/app_db.py:41-57`]. | The design treats "snapshot" as a missing capability, but the repo already uses "snapshot" to mean two different things: rollback artifacts and app-read replica refresh. The proposal would add a third safety layer without reconciling ownership, retention, or naming. |
| 2. Validate-writes-prod carveout | **CONFIRMED** | Design says validation is read-only while also queueing unresolved identifiers to prod [`Plans/admin_refresh_system_design.md:72`]. Current validator opens prod RW and inserts into `pending_entity_resolution` [`scripts/validate_nport_subset.py:67`, `:182-197`]. Shared entity gate helper does the same write on unresolved identifiers [`scripts/pipeline/shared.py:364-379`]. | "Read-only validation" is false in both the design and the implementation. The carveout is real and already live. |
| 3. Already-populated columns proposed as new | **PARTIAL** | I did not find a clean literal duplicate-column proposal. I did find a stronger schema contradiction: the design writes against fictional `ingestion_manifest` columns `pipeline_name`, `status`, `completed_at`, `row_counts_json` [`Plans/admin_refresh_system_design.md:68-70`, `:83-85`, `:509-514`, `:712-716`], while the actual schema uses `source_type`, `fetch_status`, `fetch_completed_at` and has no `row_counts_json` [`scripts/migrations/001_pipeline_control_plane.py:53-81`]. For `ingestion_impacts`, the design assumes columns like `run_id`, `action`, `rowkey`, `prior_accession` [`Plans/admin_refresh_system_design.md:83`, `:421-423`], but the live table does not have them [`scripts/migrations/001_pipeline_control_plane.py:89-109`]. | I could not confirm "column already exists but doc proposes adding it" as written. What exists instead is schema fiction: the design ignores real control-plane columns and writes against non-existent ones. |
| 4. Framework replacing rather than extending existing protocol | **CONFIRMED** | Design presents a new `SourcePipeline` base class and shared orchestration framework [`Plans/admin_refresh_system_design.md:354-418`]. Repo already has `SourcePipeline`, `DirectWritePipeline`, and `DerivedPipeline` protocols with manifest/impact/freshness contracts [`scripts/pipeline/protocol.py:117-234`, `:240-276`] plus centralized manifest helpers [`scripts/pipeline/manifest.py:1-7`, `:58-193`]. | The proposed framework is not greenfield. It overlaps the existing protocol layer and would replace terminology and contracts instead of extending them. |
| 5. Concurrency check with TOCTOU race | **CONFIRMED** | Design requires "Same pipeline cannot run twice simultaneously. 409 Conflict returned." [`Plans/admin_refresh_system_design.md:779-780`]. Current admin implementation checks `pgrep` first and then separately launches the process via `subprocess.Popen` [`scripts/admin_bp.py:267-283`]. | This is classic time-of-check/time-of-use. Two requests can both pass the check before either child process appears in the process table. |

## 2. Atlas Cross-Check

### 2a. DRIFT-CONFIRMED findings — corroborate / reject / extend

| Code | Codex status | Notes |
|---|---|---|
| D-01 | **CONFIRMED** | Atlas is right on the live drift. Current prod still shows 40.09% `entity_id` coverage overall and 8,441,797 NULLs (read-only SQL; atlas §1.2/§1.8). The second-order risk is query skew: any downstream logic that assumes entity-backed N-PORT rows silently becomes "recent months missing" rather than "no holdings". |
| D-02 | **CONFIRMED** | Atlas's month-localized collapse still holds: 2025-11 0.18%, 2025-12 0.61%, 2026-01 5.88% (read-only SQL; atlas §1.4). This pattern is too structured to be random decay and points to a pipeline boundary, not one-off bad rows. |
| D-03 | **CONFIRMED** | The 31.48% orphan-CUSIP rate remains live (read-only SQL; atlas §1.3). Second-order risk: `build_summaries.py` reads `fund_holdings_v2` for N-PORT coverage math [`scripts/build_summaries.py:237-287`], so stale `securities` coverage bleeds into attribution, not just metadata. |
| D-04 | **CONFIRMED** | 15.87% of rows still miss `series_id` resolution (read-only SQL; atlas §1.3). This aligns with the entity-gate design that queues unresolved series instead of repairing them in-line [`scripts/pipeline/shared.py:364-379`]. |
| D-05 | **CONFIRMED** | Legacy `fund_holdings` still exists in prod and still has fresh rows (read-only SQL). This directly contradicts Stage 5 cleanup being "complete" [`ENTITY_ARCHITECTURE.md:291`; `docs/data_layers.md:140-150`]. |
| D-07 | **CONFIRMED** | Manifest coverage is still only `MARKET`, `NPORT`, `13DG` in prod (read-only SQL; atlas §1.6). N-CEN and ADV are outside the control-plane tables even though docs now frame the manifest as the unified audit plane [`scripts/migrations/001_pipeline_control_plane.py:55`; `docs/pipeline_inventory.md:100-104`]. |
| C-02 | **CONFIRMED** | Validator prod-write mode is live [`scripts/validate_nport_subset.py:67`, `:182-197`]. This is not just a lock concern; it mutates a control-plane table during "validation". |
| C-04 | **CONFIRMED** | `build_managers.py`, `build_fund_classes.py`, and `build_benchmark_weights.py` still bypass staging and/or hardcode prod per atlas and inventory [`docs/pipeline_inventory.md:77-83`]. |
| C-05 | **CONFIRMED** | The five direct prod writers are real and are still missing from `docs/pipeline_violations.md` [`scripts/resolve_agent_names.py:135`, `:196-245`; `scripts/resolve_bo_agents.py:260`, `:297-301`, `:360-363`; `scripts/resolve_names.py:229`, `:140-219`; `scripts/backfill_manager_types.py:153-155`, `:77-95`; `scripts/enrich_tickers.py:419`, `:373-410`]. |
| C-06 | **CONFIRMED** | `fix_fund_classification.py` remains a no-CHECKPOINT direct writer as atlas states; inventory and violations docs still mark it that way [`docs/pipeline_inventory.md:96`; `docs/pipeline_violations.md:353-356`]. |
| C-07 | **CONFIRMED** | `refetch_missing_sectors.py` still depends on a hardcoded `/tmp` input path and no checkpoint discipline [`docs/pipeline_violations.md:195-202`]. |
| P-01 | **CONFIRMED** | 13F still has no owning freshness writer. `holdings_v2` freshness is currently supplied by enrichment, not the 13F loader itself (atlas §3.1; `docs/pipeline_inventory.md:91`, `:132-139`). |
| P-04 | **CONFIRMED, with narrower mechanism** | The crash log does show a duplicate `impact_id` on 2026-04-16 [`logs/fetch_market_crash.log:35-49`]. The current code now allocates IDs via `_next_id` [`scripts/pipeline/manifest.py:27-51`, `:157-193`], so the remaining risk is not "sequence drift still active"; it is "MAX+1 allocation is only safe if the one-writer invariant actually holds end-to-end". |
| P-05 | **CONFIRMED** | N-CEN and ADV are still outside `ingestion_manifest` despite control-plane rhetoric [`scripts/migrations/001_pipeline_control_plane.py:55`; read-only SQL; atlas §1.6]. |
| R-02 | **CONFIRMED** | Atlas is right that Roadmap/session prose says 4 NULL-CIK overrides while prod has 5 in IDs 205-221 (read-only SQL; `ROADMAP.md:3`, `:393-394`). |
| DOC-01 | **CONFIRMED** | README still promotes retired entry points [`README.md:23-38`, `:107-122`]. |
| DOC-02 | **CONFIRMED** | README tree still omits the current API/router/pipeline/migrations layout [`README.md:109-140`; `scripts/app.py:6-20`]. |
| DOC-03 | **CONFIRMED** | `PHASE3_PROMPT.md` still instructs use of retired `fetch_nport.py` (atlas §5.2.2). |
| DOC-04 | **CONFIRMED** | `ARCHITECTURE_REVIEW.md` still says React Phase 4 cutover is pending [`ARCHITECTURE_REVIEW.md:51-52`] while `REACT_MIGRATION.md` says cutover completed on 2026-04-13 [`REACT_MIGRATION.md:120`]. |
| DOC-05 | **CONFIRMED** | Deploy doc still lacks the React build prerequisite [`README_deploy.md:46-47`; `REACT_MIGRATION.md:120-121`]. |
| DOC-06 | **CONFIRMED** | `docs/write_path_risk_map.md` is stale relative to shipped rewrites/retirements (atlas §5.2.5). |
| DOC-10 | **CONFIRMED** | Prompt/history docs are still orphaned or untracked as atlas notes (atlas §5.1/§5.5). |
| DOC-11 | **CONFIRMED** | `docs/data_layers.md` still claims 84.47% `fund_holdings_v2.entity_id` coverage [`docs/data_layers.md:92`] while prod is 40.09% now (read-only SQL). |
| O-10 | **CONFIRMED** | There is still no visible log-rotation policy, and logs are accumulating by simple append/archive behavior (atlas §6.3). |

### 2b. DRIFT-SUSPECTED findings — promote / downgrade

| Code | Codex disposition | Evidence / reason |
|---|---|---|
| D-06 | **PROMOTE to CONFIRMED** | The live control-plane schema supports per-unit 13D/G impacts [`scripts/migrations/001_pipeline_control_plane.py:85-109`], but prod has only 3 promoted 13DG impacts for 51,905 BO rows (read-only SQL; atlas §1.6). This is real history/control-plane under-mirroring, not just a theoretical grain mismatch. |
| D-08 | **DOWNGRADE to CLEAN** | Atlas overstates this. `data_freshness` having only 13 rows is true, but "all SCD tables and all reference tables unstamped" is not necessarily drift; many are intentionally not freshness-owned [`docs/data_layers.md:132-139`]. The narrower real issue is ADV observability, which I keep separately under P-02. |
| D-09 | **DOWNGRADE to CLEAN** | `fund_cik` is trust-level, while fund identity is keyed primarily by `series_id`; the high unresolved `fund_cik` distinct count is not, by itself, a data defect [`docs/data_layers.md:95`, `:110`; atlas §1.3]. |
| D-10 | **PROMOTE to CONFIRMED** | Atlas framed this as doc staleness; that is exactly what it is. Current prod has 29,531 impacts while `docs/data_layers.md` still says 21,245 [`docs/data_layers.md:133-134`; read-only SQL]. |
| C-01 | **PROMOTE to CONFIRMED** | `promote_nport.py` and `promote_13dg.py` still run multi-statement prod mutation sequences without an explicit transaction wrapper [`scripts/promote_nport.py:421-494`; `scripts/promote_13dg.py:273-305`]. A crash between delete and insert is a real partial-write window. |
| C-03 | **DOWNGRADE to CLEAN** | `validate_classifications.py` only reopens RW when the target is staging so it can `ATTACH` prod read-only [`scripts/validate_classifications.py:145-154`]. This is staging-write mode, not prod-write behavior. |
| C-08 | **PROMOTE to CONFIRMED** | `compute_flows.py` is still destructive and non-atomic: it drops both output tables before rebuilding them [`scripts/compute_flows.py:82-131`]. This is a real outage window for downstream readers if interrupted. |
| C-09 | **PROMOTE to CONFIRMED** | `admin_bp.py` is a live write surface over prod, not a hypothetical one. It mutates quarter config, launches scripts, and writes entity overrides via request handlers [`scripts/admin_bp.py:86-90`, `:268-283`, `:597-771`]. |
| C-10 | **PROMOTE to CONFIRMED** | Legacy `fetch_nport.py` is still runnable and still documented enough to be accidentally used [`docs/pipeline_violations.md:65-90`]. |
| C-11 | **DOWNGRADE to CLEAN** | I did not find evidence that the bare `duckdb.connect()` calls without context managers are causing active drift. This is style/robustness debt, not a confirmed current defect. |
| P-02 | **PROMOTE to CONFIRMED** | `fetch_adv.py` now contains a freshness hook [`scripts/fetch_adv.py:247-269`], but prod still has no `data_freshness('adv_managers')` row and no recent dedicated ADV log (read-only SQL; atlas §3.1). The operational observability gap is real. |
| P-03 | **DOWNGRADE to CLEAN** | The low 13DG manifest/impact history is mostly explained by the current scoped vertical and by pre-v2 history not being retro-mirrored. That is a coverage limitation, not evidence that the fetch pipeline is currently stalled [`scripts/fetch_13dg_v2.py:12-15`, `:229-324`; `scripts/promote_13dg.py:203-269`]. |
| P-06 | **DOWNGRADE to CLEAN** | Missing a dedicated log file for the 2026-04-17 promote is weak evidence. The data freshness and impacts timestamps do show the run completed; stdout-routing is plausible and consistent with current tooling. |
| R-01 | **PROMOTE to CONFIRMED** | Small drift, but real: Roadmap says 928 exclusions while prod currently has 931 (`ROADMAP.md:3`; read-only SQL). |
| DOC-07 | **DOWNGRADE to CLEAN** | Atlas misses that `fetch_13dg_v2.py` still imports `_clean_text` and `_extract_fields` from `fetch_13dg.py` [`scripts/fetch_13dg_v2.py:60`, `:214-215`]. So `PROCESS_RULES.md` naming `fetch_13dg.py` in parser-sync guidance is stale in form but still functionally relevant [`docs/PROCESS_RULES.md:93-99`]. |
| DOC-08 | **DOWNGRADE to CLEAN** | `REACT_MIGRATION.md:121` accurately says `web/templates/index.html` was deleted; it does not claim `admin.html` was deleted. The atlas over-read that line. |
| DOC-09 | **PROMOTE to CONFIRMED** | `docs/CLASSIFICATION_METHODOLOGY.md` still references 20,205 entities [`docs/CLASSIFICATION_METHODOLOGY.md:11-13`, `:29-30`] while prod is at 26,535 now (read-only SQL). |
| DOC-12 | **PROMOTE to CONFIRMED** | There is still no architecture doc for the split API router surface beyond the endpoint inventory [`docs/endpoint_classification.md:65-75`; `scripts/app.py:6-20`, `:73-77`]. |
| O-01 | **DOWNGRADE to CLEAN** | `Plans/` being untracked is a repo hygiene choice, not an operational defect by itself. |
| O-02 | **DOWNGRADE to PARTIAL/CLEAN** | Atlas is stale on Flask. The live app is FastAPI, not Flask [`scripts/app.py:1-4`, `:28`, `:51-57`], and there are no non-doc Flask imports in the repo (read-only grep). `requirements.txt` is still missing `edgar` and `pdfplumber`, though [`requirements.txt:1-14`; `scripts/admin_bp.py:149-150`; `scripts/fetch_nport_v2.py:423-424`; `scripts/entity_sync.py:751`]. |
| O-03 | **DOWNGRADE to CLEAN** | For the same reason, smoke CI not installing Flask is no longer a runtime defect. `smoke.yml` installs the FastAPI stack that `scripts/app.py` actually imports [`scripts/app.py:28-31`; `.github/workflows/smoke.yml:24-39`]. |
| O-04 | **DOWNGRADE to CLEAN** | `13f_readonly.duckdb` duplicating prod size is intentional app architecture, not drift [`scripts/app_db.py:41-57`; `ARCHITECTURE_REVIEW.md:81-83`]. |
| O-05 | **PROMOTE to CONFIRMED** | The backup-size gap is real and worth reconciling; I did not find code-level explanation for the smaller Apr 14 backups. |
| O-06 | **DOWNGRADE to CLEAN** | Stale worktrees are cleanup debt, but not a system defect. |
| O-07 | **DOWNGRADE to CLEAN** | Same for orphan branches. |
| O-08 | **PROMOTE to CONFIRMED** | UA / identity drift is real. SEC identity strings are duplicated and inconsistent across scripts [`scripts/fetch_adv.py:26`; `scripts/fetch_nport_v2.py:89`; `scripts/admin_bp.py:149-150`; `scripts/sec_shares_client.py:14`, `:57`]. |

### 2c. Disagreements with atlas

1. Atlas O-02 and O-03 are stale after the FastAPI cutover. The current app does not import Flask, and smoke CI is correctly aligned to the FastAPI runtime [`scripts/app.py:28-31`; `.github/workflows/smoke.yml:24-39`].
2. Atlas DOC-07 overstates `PROCESS_RULES.md` drift. `fetch_13dg.py` is retired as a writer, but it is still the parser-helper source imported by v2 [`scripts/fetch_13dg_v2.py:60`, `:214-215`].
3. Atlas DOC-08 overstates the `REACT_MIGRATION.md` error. The doc says `web/templates/index.html` was deleted, which is true; `admin.html` surviving is not a contradiction on that line [`REACT_MIGRATION.md:121`; repo file check].
4. Atlas C-03 is not prod-write drift. `validate_classifications.py` reopens RW only on staging to attach prod read-only [`scripts/validate_classifications.py:145-154`].
5. Atlas P-03 mistakes a scoped-history/control-plane limitation for a live fetch failure. The sparse 13DG manifest history is real, but it is not strong evidence that the current fetcher is failing [`scripts/fetch_13dg_v2.py:12-15`].

## 3. Adversarial Code Review

### 3a. Transaction boundaries

- `promote_nport.py` is not atomic at prod scope. It performs mirror updates, scoped deletes/inserts, `fund_universe` upserts, impact updates, freshness stamps, and snapshot refresh as separate auto-committed steps [`scripts/promote_nport.py:81-146`, `:421-494`, `:502`]. A kill after delete and before insert leaves missing prod rows.
- `promote_13dg.py` has the same pattern: delete/insert on `beneficial_ownership_v2`, rebuild `beneficial_ownership_current`, mirror impact state, and refresh snapshot with no single enclosing transaction [`scripts/promote_13dg.py:90-133`, `:203-305`, `:311`].
- `compute_flows.py` drops both output tables before rebuilding them [`scripts/compute_flows.py:85-131`]. This is idempotent on rerun, but not availability-safe mid-run.
- `build_summaries.py` uses per-scope delete/insert windows rather than atomic swap tables [`scripts/build_summaries.py:162-199`, `:223-292`]. It is safer than `compute_flows.py` because scope is narrower, but still exposes readers to partial refresh slices.
- `promote_staging.py` is the best transaction discipline in the repo: it snapshots first, then wraps the promote in `BEGIN TRANSACTION` / `COMMIT` / `ROLLBACK`, and can auto-restore on validation failure [`scripts/promote_staging.py:359-396`, `:440-472`]. The contrast with the source promotes is stark.

### 3b. Idempotency

- `fetch_nport_v2.py` is intentionally idempotent at quarter/accession scope: it anti-joins completed DERA ZIPs in the manifest and falls back to delete/insert replacement in staging [`scripts/fetch_nport_v2.py:127-152`, `:155-209`, `:321-334`].
- `resolve_13dg_filers.py` is strongly idempotent in both passes because it dedupes by CIK, checks for existing identifiers, and wraps each pass in a transaction [`scripts/resolve_13dg_filers.py:80-106`, `:235-245`, `:483-533`].
- DM override replay is not fully idempotent in the "reset and rebuild" sense. Migration 007 explicitly documents that `new_value=NULL` rows still apply live but are skipped by replay logic during `build_entities.py --reset` [`scripts/migrations/007_override_new_value_nullable.py:8-12`, `:18-25`]. Current prod still has five NULL-target rows in override IDs 205-221 (read-only SQL).
- `fetch_adv.py` is only idempotent after full completion. Mid-run failure between `DROP TABLE IF EXISTS adv_managers` and the replacement `CREATE TABLE` can leave the table absent or partially unavailable [`scripts/fetch_adv.py:247-249`].

### 3c. Concurrency

- The admin pipeline runner has a TOCTOU race between "is it already running?" and "spawn it" [`scripts/admin_bp.py:267-283`].
- `_next_id()` in `scripts/pipeline/manifest.py` is only safe as long as the DuckDB single-writer invariant truly holds for every caller path [`scripts/pipeline/manifest.py:27-51`]. The duplicate `impact_id` crash proves that the system has already violated that assumption at least once in production operation [`logs/fetch_market_crash.log:35-49`].
- `fetch_nport_v2.py` already documents lock contention against staging and falls back in some cases when it cannot get a read handle [`scripts/fetch_nport_v2.py:235-245`, `:321-333`]. This is a good operational adaptation, but it also proves same-DB concurrency is a live concern, not a hypothetical one.
- Schema migrations are not protected from concurrent writers. None of the migration files I reviewed takes a repo-wide maintenance lock; most just connect and execute DDL directly [`scripts/migrations/004_summary_by_parent_rollup_type.py:56-152`; `scripts/migrations/006_override_id_sequence.py:84-174`; `scripts/migrations/add_last_refreshed_at.py:59-114`].

### 3d. Failure modes

- Kill mid-promote on N-PORT or 13D/G: partial prod scope deletion is possible because there is no enclosing transaction [`scripts/promote_nport.py:421-494`; `scripts/promote_13dg.py:273-305`].
- Kill mid-ADV refresh: `adv_managers` can be dropped before recreation [`scripts/fetch_adv.py:247-249`].
- Kill mid-derived rebuild: `investor_flows` and `ticker_flow_stats` can both be absent after `_create_tables()` but before repopulation [`scripts/compute_flows.py:85-131`].
- Stale snapshot read is an accepted app behavior. If prod is locked, the app falls back to `13f_readonly.duckdb` until the switchback monitor returns to primary [`scripts/app_db.py:41-57`, `:75-103`]. That is availability-friendly, but it means frontend correctness is explicitly eventually consistent during long writes.

### 3e. Hidden coupling

- `build_summaries.py` depends on the latest `fund_holdings_v2.report_month` per `series_id` for N-PORT coverage math [`scripts/build_summaries.py:237-287`]. Any partial or degraded N-PORT promote silently changes L4 output quality.
- `enrich_holdings.py` owns the user-visible freshness of `holdings_v2`, even though `load_13f.py` owns the base table contents. This decouples freshness from source ingestion success and masks 13F observability gaps [`docs/pipeline_inventory.md:91`, `:132-139`].
- The `_mirror_manifest_and_impacts` bug was fixed in the current promote callsites, but the root cause remains duplication of mirror logic instead of one canonical implementation [`scripts/promote_nport.py:81-146`; `scripts/promote_13dg.py:203-269`]. That means the bug is fixed locally, not structurally.

### 3f. Authorization

- Admin auth is real, not decorative: all `/api/admin/*` routes require `ENABLE_ADMIN=1`, `ADMIN_TOKEN`, and timing-safe token comparison [`scripts/admin_bp.py:4-9`, `:56-74`].
- The security model is still weak for a browser surface: the token is stored in `localStorage` and replayed on every request from JS [`web/templates/admin.html:180-199`]. That expands exposure to XSS/browser persistence and leaves no server-side session invalidation path.
- I found no actual secret-rotation mechanism beyond changing the environment variable and forcing clients to re-prompt. There is no rotation endpoint, no token versioning, and no scoped admin roles [`scripts/admin_bp.py:62-67`; `Plans/admin_refresh_system_design.md:776-790`].

## 4. Cross-Doc Contradictions

1. **BLOCK:** `ENTITY_ARCHITECTURE.md` says Stage 5 dropped legacy `holdings`, `fund_holdings`, and `beneficial_ownership` on 2026-04-13 [`ENTITY_ARCHITECTURE.md:287-293`], while `MAINTENANCE.md` says the drop is only authorized on or after 2026-05-09 [`MAINTENANCE.md:120-123`], and prod still contains `fund_holdings` with fresh rows (read-only SQL).
2. **BLOCK:** `ARCHITECTURE_REVIEW.md` still describes a Flask monolith with React Phase 4 pending [`ARCHITECTURE_REVIEW.md:43-52`], but `scripts/app.py` is now a FastAPI entry point with split routers [`scripts/app.py:1-20`, `:73-77`] and `REACT_MIGRATION.md` says Phase 4 completed on 2026-04-13 [`REACT_MIGRATION.md:120-121`].
3. **MAJOR:** `docs/data_layers.md` still reports 84.47% `fund_holdings_v2` entity coverage and 9 `data_freshness` rows [`docs/data_layers.md:92`, `:132-135`], while current prod is 40.09% coverage and 13 freshness rows (read-only SQL).
4. **MAJOR:** `Plans/admin_refresh_system_design.md` references `docs/data_sources.md` [`Plans/admin_refresh_system_design.md:31`, `:737`, `:799`], but the file currently exists as `Plans/data_sources.md`, not under `docs/` (repo file check). The design docs already disagree with repo layout.
5. **MAJOR:** `README_deploy.md` still describes a pure Python deploy path [`README_deploy.md:46-47`] while `REACT_MIGRATION.md` makes the React build a prerequisite [`REACT_MIGRATION.md:120-121`].
6. **MINOR:** `CLASSIFICATION_METHODOLOGY.md` still frames classification coverage around 20,205 entities [`docs/CLASSIFICATION_METHODOLOGY.md:11-13`, `:29-30`] while prod MDM is now 26,535 entities (read-only SQL).

## 5. Extensions Beyond Atlas

### 5.1 Migrations

- Migration 004 is idempotent, but not interruption-safe. It renames `summary_by_parent`, recreates it, copies rows, then drops the old table [`scripts/migrations/004_summary_by_parent_rollup_type.py:82-145`]. A crash after rename leaves the canonical table name absent.
- Migration 006 is much stronger: it probes current state, aborts on NULL PKs, stamps `schema_versions`, and checkpoints [`scripts/migrations/006_override_id_sequence.py:93-172`]. This is the best migration in the set I reviewed.
- `add_last_refreshed_at.py` is internally contradictory. Its docstring still says "written but not yet run" [`scripts/migrations/add_last_refreshed_at.py:26-36`], while `docs/data_layers.md` already treats `last_refreshed_at` as live on prod [`docs/data_layers.md:111`]. This is doc/code drift inside the migration surface itself.
- Rollback path is generally weak. Most migrations are additive or one-way DDL; there is no systematic "down" path, and rollback is operationally "restore backup" rather than scripted reversal.

### 5.2 DM override system

- Migration 006 fixed the NULL-PK/sequence problem at schema level [`scripts/migrations/006_override_id_sequence.py:3-18`], but `admin_bp.py` still carries stale commentary and redundant MAX+1 logic that assumes prod has no default/sequence [`scripts/admin_bp.py:755-763`].
- Replay correctness is still incomplete for CIK-less target overrides. Migration 007 explicitly accepts that such overrides apply live but are skipped during replay [`scripts/migrations/007_override_new_value_nullable.py:8-12`]. That means "reset and rebuild from persistent overrides" is not a full correctness proof yet.
- `_heal_override_ids()` in `promote_staging.py` is a necessary backstop, but it reconstructs the whole override table via temp-table delete+insert [`scripts/promote_staging.py:161-217`]. Safe enough under its current controlled use, but still a full-table rewrite.

### 5.3 `_mirror_manifest_and_impacts` reset bug

- Root cause: staging copies carry `pending`/pre-promote states, and the old mirror strategy copied them into prod wholesale before trying to repair just the promoted scope afterward. That made out-of-scope history regress to pending on re-promote.
- Current state: both `promote_nport.py` and `promote_13dg.py` now selectively preserve already-promoted rows [`scripts/promote_nport.py:81-146`; `scripts/promote_13dg.py:203-269`].
- My assessment: the bug is fixed in the two known callsites, but not centrally fixed. Because the mirror logic is duplicated, the same class of regression can recur the next time a new promote path reimplements it.

### 5.4 Secrets handling

- EDGAR identity is inlined in many scripts instead of centralized [`scripts/fetch_adv.py:26`; `scripts/fetch_nport_v2.py:89`; `scripts/pipeline/discover.py:170-172`; `scripts/sec_shares_client.py:57`].
- OpenFIGI is handled better: `run_openfigi_retry.py` reads `OPENFIGI_API_KEY` from the environment and degrades gracefully when absent [`scripts/run_openfigi_retry.py:62-64`].
- Admin token handling is the weakest secret surface: browser-persisted in `localStorage`, env-only on server, no rotation workflow, no scoping [`web/templates/admin.html:180-199`; `scripts/admin_bp.py:56-67`].

### 5.5 Frontend / backend contract

- The public contract is now `/api/v1/*` only [`docs/endpoint_classification.md:18-20`], and the smoke suite verifies only four endpoints on a fixture DB [`tests/smoke/test_smoke_endpoints.py:61-82`; `pytest --collect-only -q` => 8 tests].
- `ARCHITECTURE_REVIEW.md` still reasons about a Flask boundary and untyped contract [`ARCHITECTURE_REVIEW.md:43-49`], but the live backend is FastAPI and the frontend has generated API types under `web/react-app/src/types/api-generated.ts` (repo file scan). The migration is more complete than the architecture doc admits.
- The app intentionally serves stale-but-consistent data from `13f_readonly.duckdb` during write locks [`scripts/app_db.py:41-57`]. That contract is stable, but clients are not told when they are reading the snapshot unless the server is started from CLI and the banner prints it [`scripts/app.py:111-117`].

### 5.6 Test coverage reality

- Current automated coverage is extremely thin: 8 smoke tests, all in `tests/smoke/test_smoke_endpoints.py`, against a committed fixture DB [`tests/smoke/conftest.py:18-36`; `pytest --collect-only -q`].
- No tests cover promote atomicity, migration rollback, admin auth behavior, DM override replay, or control-plane mirroring.
- The smoke assertions are shape-level: key match, row-count tolerance, and one sentinel value [`tests/smoke/test_smoke_endpoints.py:88-134`]. They would not catch most of the data-quality drift found in this audit.

## 6. Original Contributions

1. **Security posture is a first-class concern.** Reviewer 1 noted admin drift, but not the browser-side token persistence model. Storing the admin token in `localStorage` makes the auth gate real but operationally brittle and XSS-sensitive [`web/templates/admin.html:180-199`].
2. **Recovery model mismatch:** much of the repo is "rerun to heal" rather than "rollback to prior consistent state". That is acceptable only if partial windows are small and observable; in `promote_nport.py`, `promote_13dg.py`, `fetch_adv.py`, and `compute_flows.py`, they are not.
3. **Audit-process drift itself is now part of the risk surface.** Atlas ops findings about Flask are already stale relative to live code [`scripts/app.py:1-4`, `:28-31`]. This repo now changes quickly enough that doc-only or environment-only audits can misclassify live risk unless they re-read code first.
4. **The paused admin-refresh design is blocked more by schema fiction than by missing code.** The problem is not merely "unfinished framework"; it is that the draft design already diverges from the actual control-plane schema and protocol layer [`Plans/admin_refresh_system_design.md:68-85`, `:354-418`; `scripts/migrations/001_pipeline_control_plane.py:53-109`; `scripts/pipeline/protocol.py:117-234`].

## 7. Severity Summary

- **BLOCK:** `fund_holdings_v2` live entity-enrichment collapse; non-atomic prod promotes in `promote_nport.py` and `promote_13dg.py`; Stage 5 cleanup/documentation contradiction around legacy fact tables; admin refresh design writing against non-existent control-plane schema.
- **MAJOR:** direct prod writers missing from violation tracking; validator prod writes; DM override replay gap for NULL-target overrides; destructive non-atomic rebuilds in `fetch_adv.py` and `compute_flows.py`; admin token stored in browser `localStorage`; migration 004 interruption risk; missing ADV observability.
- **MINOR:** roadmap numeric drift; stale README/deploy docs; inconsistent EDGAR identity strings; absent log-rotation policy; untracked `Plans/` hygiene.

## 8. Flags for Reconciliation

1. Atlas O-02/O-03 vs current code: Flask is no longer a runtime dependency of `scripts/app.py`; only `edgar` and `pdfplumber` remain genuinely unpinned [`scripts/app.py:28-31`; `requirements.txt:1-14`; `scripts/entity_sync.py:751`; `scripts/fetch_nport_v2.py:423-424`].
2. Atlas DOC-07: `PROCESS_RULES.md` naming `fetch_13dg.py` is stale in presentation but not fully wrong because v2 still imports its parser helpers [`docs/PROCESS_RULES.md:93-99`; `scripts/fetch_13dg_v2.py:60`, `:214-215`].
3. Atlas DOC-08: `REACT_MIGRATION.md:121` is accurate about deleting `web/templates/index.html`; the surviving `admin.html` is not a contradiction on that line.
4. The prompt's doc paths (`docs/admin_refresh_system_design.md`, `docs/data_sources.md`) do not match repo reality (`Plans/...`). Human reconciliation is needed before that design work resumes.
