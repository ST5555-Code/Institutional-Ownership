# Remediation Program — Master Plan

> Remediation Program COMPLETE 2026-04-22 (conv-11). Historical checklist retired to `archive/docs/REMEDIATION_CHECKLIST.md` on 2026-04-23. Sprint-view no longer useful post-program. Forward work → `ROADMAP.md`.

_Generated: 2026-04-20. Last updated: 2026-04-22 (conv-12 — Phase 2 + Wave 2 doc refresh on top of conv-11 PROGRAM COMPLETE)._

## Program overview

This program consolidates the remediation plan surfaced by the 2026-04-17 system audit (§12 of `docs/SYSTEM_AUDIT_2026_04_17.md`) plus everything that has drifted onto the open list between that audit and 2026-04-20 — BLOCK/REWRITE closeouts, INF25-INF47 series, post-merge regressions, schema-parity extensions, pipeline violations, doc-update proposals, and diagnostic follow-ups.

The program is structured for multi-worker parallel execution across **5 architectural themes**. Each theme has a problem statement, acceptance criteria, an ordered item list with file-conflict zones and logical dependencies, and an explicit within-theme parallel-eligibility call. The cross-theme parallel execution map at the end of this doc is the lookup table for scheduling decisions.

**Done means:** every theme has reached its acceptance criteria; `make smoke` green; `validate_entities --prod` at the baseline 8 PASS / 2 FAIL / 6 MANUAL; `make schema-parity-check` reports 0 divergences; no INF-ID in the open set of `docs/DEFERRED_FOLLOWUPS.md` that the program claimed to close.

**Parallel-execution discipline (non-negotiable).** Two items run parallel IFF (a) file-conflict zones are fully disjoint, (b) neither has a logical dependency on the other, (c) neither depends on a third in-flight item, (d) both are listed "parallel-safe" in the cross-theme map. Any failure → serial. Ambiguity → Appendix A → serial until resolved.

---

## Themes (5)

### Theme 1 — Data integrity foundation

**Problem statement.** Denormalized v2 columns drift when canonical sources update (BLOCK-2 entity_id 40% → 84%, BLOCK-TICKER-BACKFILL ticker 59% → 3.7% over five months). OpenFIGI classification has three live root causes (RC1 foreign-exchange default, RC2 MAX-issuer aggregator, RC3 override CSV errors). Ticker coverage has no auto-trigger after CUSIP classifications change. Merge semantics support only PK-replace, not NULL-only fill. Under all of this sits a schema-constraint hygiene gap (`securities.cusip` has no formal PK) and unresolved priceability semantics for OTC grey-market rows.

If these aren't fixed: coverage silently decays, cosmetic deliverables regress to em-dash columns, and every new dataset carries forward the same defects.

**Acceptance criteria.** 
- RC1, RC2, RC4 (issuer_name propagation) fixes shipped; cc-issuer_name drift at 0 rows.
- Pass C auto-triggered end-of-run on `build_cusip.py` and `normalize_securities.py`.
- `merge_staging.py` NULL-only mode available.
- `securities.cusip` formal PK + VALIDATOR_MAP registered.
- `pct_of_float` → `pct_of_so` rename sweep + derived-artifact hygiene at 0 stale references (INF41 + INF42).
- Denormalized-column retirement sequence landed or explicitly deferred to Phase 2 with a tracked exit criteria.

**Items.**

| ID | Title | Audit ref | ROADMAP ref | Findings-doc ref | Status | File-conflict zones | Logical dependencies | Sequencing batch | Notes |
|----|-------|-----------|-------------|------------------|--------|--------------------|----------------------|------------------|-------|
| int-01 | RC1: OpenFIGI foreign-exchange ticker filter | — | — | BLOCK_SECURITIES_DATA_AUDIT_FINDINGS §4.1 | CLOSED (PRs #13, #15) | `scripts/build_cusip.py`, `scripts/run_openfigi_retry.py` | None | 1-A | US-preferred exchange whitelist + CUSIP re-queue; 216-row foreign-only residual accepted. |
| int-02 | RC2: MAX(issuer_name_sample) mode aggregator | — | — | BLOCK_SECURITIES_DATA_AUDIT_FINDINGS §4.2 | CLOSED (Option A, PR #50) | `scripts/pipeline/cusip_classifier.py` | int-01 (high-confidence impact needs RC1 fix first) | 1-B | Code-complete in `fc2bbbc` (2026-04-18); Phase 0 (PR #50) quantified 8,178-row residual MAX-era gap in prod `cusip_classifications`. Option A selected: no re-seed now; organic convergence via future universe expansion (int-23) or routine `--reset` runs. |
| int-03 | RC3: ticker_overrides.csv manual triage | — | — | BLOCK_SECURITIES_DATA_AUDIT_FINDINGS §4.3 | CLOSED (PRs #91, #96) | `data/reference/ticker_overrides.csv`, `scripts/oneoff/` triage export script | int-01 (gold-standard needs US-preferred) | 1-C | Triage export (PR #91) surfaced 568-row inventory for offline review; apply (PR #96) landed 6 ticker fixes + 2 removals. Prior scope estimate of ~20-40 errors was high — actual triaged set was 8 rows. |
| int-04 | RC4: issuer_name propagation scope guard | — | — | BLOCK_SECURITIES_DATA_AUDIT_FINDINGS §4 scope guard | CLOSED (PRs #18, #22) | `scripts/build_cusip.py` (propagation site) | None | 1-A | Phase 0 landed on `build_cusip.py` as single correct injection site; `normalize_securities.py` edit not needed. |
| int-05 | Ticker Backfill Phase 1a — retroactive Pass C sweep | — | — | BLOCK_TICKER_BACKFILL_FINDINGS §6 Phase 1a | CLOSED (NO-OP, PR #46) | `scripts/enrich_holdings.py` (invocation only) | None | 1-A | Closed as NO-OP; retroactive sweep already executed in earlier session. |
| int-06 | Ticker Backfill Phase 1b — forward-looking hooks | — | — | BLOCK_TICKER_BACKFILL_FINDINGS §6/§10.2 | CLOSED (NO-OP, PR #69) | `scripts/build_cusip.py` (end), `scripts/normalize_securities.py` (end) | int-05 (retroactive before forward) | 1-B | Phase 0 verified forward-looking hooks already shipped in prior sessions; no new code required. |
| int-07 | Ticker Backfill Phase 2 — benchmark_weights gate | — | — | BLOCK_TICKER_BACKFILL_FINDINGS §8 | CLOSED (PR #71) | `scripts/build_benchmark_weights.py` (validation only) | int-05, int-06 | 1-C | Phase 0 verified all 3 gates PASS (coverage + no-regression + tier-stability); no Phase 2b escalation required. |
| int-08 | Ticker Backfill Phase 2b — 227-ticker sector refetch | — | — | BLOCK_TICKER_BACKFILL_FINDINGS §8 | SKIPPED (conditional; no PR) | `scripts/refetch_missing_sectors.py` (invocation) | int-07 fails gate 1/2 | 1-D | Conditional on int-07 gate failure; int-07 PASSED — no sector refetch required. |
| int-09 | INF25 BLOCK-DENORM-RETIREMENT sequencing | — | INF25 | DOC_UPDATE_PROPOSAL_20260418 §Item 1 | CLOSED (PRs #73, #75) | `holdings_v2` DDL, `fund_holdings_v2` DDL, `docs/data_layers.md` §7, `ENTITY_ARCHITECTURE.md`, `ROADMAP.md` | int-01..int-08 shipped (drift stabilized); obs-XX freshness hooks live | 1-D | Phase 0 (PR #73) quantified Step 4 retirement scope (~500 read sites + dual-graph `rollup_entity_id`); Phase 1 (PR #75) formalized **deferral to Phase 2** with full exit criteria embedded in `data_layers.md §7`. Steps 1–3 done; int-06 forward hooks bound drift. |
| int-10 | INF26 OpenFIGI `_update_error()` permanent-pending bug | — | INF26 | DOC_UPDATE_PROPOSAL §Item 2 | CLOSED (PRs #42, #44; staging sweep executed data-ops-batch) | `scripts/run_openfigi_retry.py`, `scripts/oneoff/int_10_sweep.py` | None | 1-A | Code fix shipped; staging sweep `--confirm` executed conv-10 window (81 rows). |
| int-11 | INF27 CUSIP residual-coverage tracking | — | INF27 | DOC_UPDATE_PROPOSAL §Item 3 | CLOSED (PR #87) | `docs/data_layers.md`, `ROADMAP.md` | None | 1-E | Doc-only; tracking tier documented in data_layers.md + ROADMAP. |
| int-12 | INF28 `securities.cusip` formal PK + VALIDATOR_MAP | — | INF28 | DOC_UPDATE_PROPOSAL §Item 4 | CLOSED (PRs #92, #95) | `scripts/migrations/011_securities_cusip_pk.py` (applied at slot 011 after renumber), `scripts/db.py`, `docs/canonical_ddl.md` | int-01 shipped (clean issuer state) | 1-D | Phase 0 (PR #92) validated zero-duplicate CUSIP state; Phase 1 (PR #95) shipped migration 011 adding formal PK constraint on `securities.cusip` — applied prod + staging. Slot renumbered 009 → 011 because slots 009 (sec-01 admin session table) and 010 (obs-03 market ID allocation) were already consumed. |
| int-13 | INF29 OTC grey-market `is_priceable` refinement | — | INF29 | DOC_UPDATE_PROPOSAL §Item 5 | CLOSED (PRs #94, #97) | `scripts/fetch_market.py`, `scripts/oneoff/backfill_is_otc.py` (new), migration 012 | None | 1-E | Phase 0 (PR #94) chose option to introduce explicit `is_otc` column rather than overloading `is_priceable`; Phase 1 (PR #97) shipped migration 012 + OTC classifier + backfill script. Prod backfill `--confirm` executed in conv-10 data-ops batch (1,103 rows flagged). |
| int-14 | INF30 BLOCK-MERGE-UPSERT-MODE — NULL-only merge | — | INF30 | ROADMAP §Open | CLOSED (PR #85) | `scripts/merge_staging.py`, `scripts/promote_staging.py` | None | 1-C | NULL-only merge mode shipped (PR #85, Phase 0 scoping PR #81). Companion to INF11 (shipped). |
| int-15 | INF31 market_data writer `fetch_date` discipline | — | INF31 | ROADMAP §Open, BLOCK_MARKET_DATA_WRITER_AUDIT §6 | CLOSED (PRs #88, #90) | `scripts/fetch_market.py`, `scripts/refetch_missing_sectors.py` | None | 1-C | Phase 0 (PR #88) scoped to 2-line fix in `refetch_missing_sectors.py` — `fetch_market.py` already had discipline; Phase 1 (PR #90) stamped `fetch_date` + `metadata_date` on the sector refetch UPDATE path. |
| int-16 | INF35 f-string interpolation cosmetic fix | — | INF35 | REWRITE_BUILD_SUMMARIES | CLOSED (PR #83) | `scripts/build_summaries.py` | None | 1-E | Low-pri cosmetic cleanup shipped. |
| int-17 | INF36 top10_* NULL placeholders | — | INF36 | REWRITE_BUILD_SUMMARIES | CLOSED (PR #99) | `summary_by_parent` DDL, migration 013 | None | 1-D | Drop decision over populate: migration 013 dropped 30 unused `top10_*` columns from `summary_by_parent`. Applied prod + staging in conv-10 data-ops batch. |
| int-18 | INF37 backfill_manager_types residual 9 entities | — | INF37 | ROADMAP §Open | STANDING | `scripts/backfill_manager_types.py` (informational) | None | — | Curation task; no closure expected. |
| int-19 | INF38 BLOCK-FLOAT-HISTORY — true pct_of_float tier | — | INF38 | REWRITE_PCT_OF_SO_PERIOD_ACCURACY §14.10 | DEFERRED | `scripts/fetch_sec_float.py` (new), `scripts/enrich_holdings.py` Pass B | pct-of-so live (done) | Phase 2 | Requires 10-K/13D/Forms 3-5 ingestion. |
| int-20 | MAJOR-6 D-03 orphan-CUSIP secondary driver in build_summaries | §3.1 MAJOR-6 | — | SYSTEM_AUDIT §3.1 | CLOSED (PR #89) | `scripts/build_summaries.py` (read-path only) | int-01..int-04 ship first | 1-D | Phase 0 findings-only (PR #89): orphan-CUSIP driver auto-resolved once securities coverage repairs (int-01/02/04/23 + CUSIP v1.4) landed. No code change required; read-path verifies clean against current prod state. |
| int-21 | MAJOR-7 D-04 15.87% unresolved series_id tail | §3.1 MAJOR-7 | — | SYSTEM_AUDIT §3.1, Pass 2 §1 | CLOSED (PRs #93, #98, #100) | `scripts/oneoff/` triage export + worksheet generators, `scripts/oneoff/apply_series_triage.py` (new) | None | 1-C | Triage export (PR #93) surfaced unresolved series_id set; new-entity worksheet (PR #98) generated 67 distinct CIKs from 100 series for offline review; unified apply (PR #100) promoted 67 new entities + 27 resolve + 3 exclude, linking 100 series and accepting 1,399 remaining unresolved as residual tail. |
| int-22 | MINOR-5 C-06 fix_fund_classification no-CHECKPOINT | §4.1 | — | pipeline_violations.md §4-lines-489 | CLOSED (PR #76) | `scripts/fix_fund_classification.py` | None | 1-E | Retrofit shipped: `con.execute("CHECKPOINT")` inserted after the `executemany` UPDATE on `fund_universe`, durably flushing the write before verification queries. |
| int-23 | BLOCK-SEC-AUD-5 universe expansion 132K→430K acceptance | — | — | BLOCK_SECURITIES_DATA_AUDIT §7 addendum | CLOSED (PR #77, already-done) | `scripts/pipeline/cusip_classifier.py` (accept decision only) | None | 1-A | Phase 0 (PR #77) confirmed already-implemented: prod + staging `cusip_classifications` = `securities` = 430,149 rows; three-source UNION (securities + fund_holdings_v2 + beneficial_ownership_v2) = 430,149 distinct CUSIPs; `get_cusip_universe()` has no gating/cap/flag. Execution was satisfied by the CUSIP v1.4 prod promotion (commit `8a41c48`, 2026-04-15). No code change, no migration, no SSE. |

**Sequencing within theme.** Strict serial across batches 1-A → 1-B → 1-C → 1-D → 1-E. Within a batch, items share hot-zone files (`scripts/build_cusip.py`, `scripts/normalize_securities.py`, `scripts/pipeline/cusip_classifier.py`) and must run serial. Phase 2 items (int-19) gated on foundation close.

**Parallel-eligibility within theme.** **None.** Every data-integrity item touches the securities/CUSIP/ticker path and has transitive dependencies through the Pass B/C sweep. Serial only.

---

### Theme 2 — Observability + audit trail

**Problem statement.** `ingestion_manifest` covers only MARKET/NPORT/13DG; N-CEN and ADV are absent. `ingestion_impacts` has a 13D/G grain mismatch (3 rows vs 51,905 BO rows) — pre-v2 history never retro-mirrored. `fetch_adv.py` has no freshness row, no log, no datable trace. `market_data` `impact_id` duplicate-PK race recurred post-fix — `_next_id` only safe under true one-writer invariant. No log-rotation policy (182 log files accumulated). `data_layers.md` headline 84.47% coverage claim is stale (now 40.09% → 84.13% after BLOCK-2 shipped). 13F loader has no owning freshness writer. Makefile `quarterly-update` is missing the 13F load step.

**Acceptance criteria.**
- `ingestion_manifest` covers all 5 sources (MARKET, NPORT, 13DG, NCEN, ADV).
- Every pipeline script calls `record_freshness(con, '<table>')` on every table it writes.
- `impact_id` allocation centralized in a single writer (manifest `_next_id()`); zero duplicate-PK races in 30 days.
- Log-rotation policy implemented.
- `docs/data_layers.md` headline reflects current prod state.
- `quarterly-update` Makefile includes 13F load step.
- Post-merge regressions (DIAG-23/24/25) all closed.

**Items.**

| ID | Title | Audit ref | ROADMAP ref | Findings-doc ref | Status | File-conflict zones | Logical dependencies | Sequencing batch | Notes |
|----|-------|-----------|-------------|------------------|--------|--------------------|----------------------|------------------|-------|
| obs-01 | MAJOR-9 D-07/P-05 add N-CEN + ADV to ingestion_manifest | §3.1 MAJOR-9 | — | SYSTEM_AUDIT §3.1 | CLOSED (PRs #20, #25) | `scripts/fetch_ncen.py`, `scripts/fetch_adv.py`, `scripts/migrations/001_pipeline_control_plane.py` (declarations) | None | 2-A | Unlocked obs-02, obs-03. |
| obs-02 | MAJOR-12 P-02 ADV freshness + log | §5.1 MAJOR-12 | — | SYSTEM_AUDIT §5 | CLOSED (PRs #28, #30) | `scripts/fetch_adv.py`, `scripts/pipeline/freshness.py` | obs-01 | 2-B | `data_freshness` row + stdout log; CHECKPOINT reordered after freshness write. |
| obs-03 | MAJOR-13 P-04 market impact_id allocation hardening | §5.2 MAJOR-13 | — | SYSTEM_AUDIT §5.2 | CLOSED (PRs #8, #12) | `scripts/pipeline/manifest.py`, `scripts/fetch_market.py` | None | 2-A | Centralized `_next_id()` via new `pipeline/id_allocator.py`; migration 010 dropped nextval DEFAULTs. |
| obs-04 | MAJOR-8 D-06 13D/G ingestion_impacts grain backfill | §3.1 MAJOR-8 | — | SYSTEM_AUDIT §3.1 | CLOSED (PRs #36, #38; data op executed conv-10) | `scripts/oneoff/backfill_13dg_impacts.py` | obs-03 | 2-B | One-off backfill script shipped; data op executed in conv-10 data-ops batch with `--confirm` (51,902 manifest + 51,902 impact rows). Fully closed. |
| obs-05 | MAJOR-17 DOC-11 data_layers.md coverage headline refresh | §7.1 | — | Cross-doc 3 | CLOSED (PR #66) | `docs/data_layers.md:92` | None | 2-E | Headline re-anchored to 14,090,397 rows / 84.13% `entity_id` coverage (prod-verified 2026-04-21); BLOCK-2 (2026-04-17) + CUSIP v1.4 (2026-04-15) cited as stability baseline. |
| obs-06 | MINOR-3 P-01 13F loader freshness | §5.2 MINOR-3 | — | SYSTEM_AUDIT §5.2 | CLOSED (NO-OP, no PR) | `scripts/load_13f.py`, `scripts/pipeline/freshness.py` | None | 2-C | Closed as already-satisfied; `record_freshness('filings')` + `record_freshness('filings_deduped')` shipped in `8e7d5cb` (`load_13f.py` rewrite) prior to this program window. |
| obs-07 | MINOR-4 P-07 N-PORT report_month future-leakage gate | §5.2 MINOR-4 | — | SYSTEM_AUDIT §5.2 | CLOSED (PRs #51, #53) | `scripts/promote_nport.py` (validation) | None | 2-C | Preventive gate: rejects rows with `report_month` in the future; per-row logging on rejection. |
| obs-08 | MINOR-16 O-05 backup-gap investigation | §8.1 | — | SYSTEM_AUDIT §8.1 | CLOSED (PR #58) | `scripts/backup_db.py` + `Makefile` + `MAINTENANCE.md` | None | 2-D | Infra already in place (script + `backup-db` target + `quarterly-update` step 8 + 12 snapshots Apr-10→Apr-19). Apr-14 size drop = `positions` table drop (`d50b602`); 3d gap = dev-only window. MAINTENANCE.md wording fix (manual vs `quarterly-update`) + retention note + `backup-db` Makefile target wired; see `docs/findings/obs-08-p1-findings.md`. |
| obs-09 | MINOR-18 O-10 log-rotation policy | §8.1 | — | SYSTEM_AUDIT §8.1 | CLOSED (PR #56) | `scripts/rotate_logs.py` (new) + `Makefile` | None | 2-D | Log-rotation script + Makefile target shipped; addresses 182-file backlog. |
| obs-10 | INF32 quarterly-update Makefile 13F-load step | — | INF32 | ROADMAP §Open, PRECHECK_LOAD_13F_LIVENESS secondary | CLOSED (PR #52) | `Makefile` | None | 2-C | Wired `load-13f` + `promote-adv` into `quarterly-update`; pruned retired `update.py` references. |
| obs-11 | Pass 2 §6.4 `flow_intensity_total` formula docstring | Pass 2 §6 | — | SYSTEM_PASS2 §6.4 | CLOSED (PR #66) | `scripts/compute_flows.py` (docstring), `docs/data_layers.md` | None | 2-E | 9-line formula docstring added to `_compute_ticker_stats`; new §10 Flow metrics section in data_layers.md documents `flow_intensity_{total,active,passive}` + churn variants. |
| obs-12 | INF33 BLOCK-CI-ACTIONS-NODE20-DEPRECATION | — | INF33 | ROADMAP §Open | CLOSED (PR #57) | `.github/workflows/*.yml` | None | 2-D | Node 20 → Node 24 bump across workflows. |
| obs-13 | DIAG-23 Register %FLOAT stale dist bundle (INF42 hygiene) | — | INF42 | POST_MERGE_REGRESSIONS_DIAGNOSTIC §1 | CLOSED (PR #65) | `web/react-app/dist/` (rebuild artifact), `.gitignore` | None | verify | Verification PASS: React source + rebuilt dist bundle (2026-04-19 15:26 EDT) both free of `pct_of_float`; ff1ff71 touched CI fixtures only. Evidence: `docs/findings/obs-13-verify-findings.md`. INF42 (derived-artifact hygiene CI gate) remains a standing gap. |

**Sequencing within theme.** 2-A manifest/impact_id foundation → 2-B ADV + 13D/G backfill → 2-C freshness + Makefile completeness → 2-D ops (logs, backups, CI) → 2-E docs.

**Parallel-eligibility within theme.** Batch 2-A: **obs-01 ∥ obs-03** is potentially safe — obs-01 touches `fetch_ncen.py`+`fetch_adv.py`+`migrations/001`, obs-03 touches `pipeline/manifest.py`+`fetch_market.py`. **Disjoint files; no code dependency.** Safe to parallelize once both Phase 0 investigations confirm no hidden shared module.

---

### Theme 3 — Migration + schema discipline

**Problem statement.** Prod promotes (`promote_nport.py`, `promote_13dg.py`) perform multi-statement DELETE+INSERT with no transaction wrap — kill-between-statements → data loss. `_mirror_manifest_and_impacts` is duplicated code in both; no shared helper. `fetch_adv.py` DROP-before-CREATE window leaves `adv_managers` absent on interrupt. Migration 004 RENAME→CREATE→INSERT→DROP sequence is non-atomic. `add_last_refreshed_at.py` ran on prod but never stamped `schema_versions` — audit reads get the wrong answer. Admin refresh system design writes against fictional columns and an 11-state lifecycle that doesn't map to the 5-state `fetch_status` enum; pre-restart reconciliation required. INF39 schema-parity gate landed for L3 canonical tables only — L4 derived, L0 control-plane, and CI wiring all deferred. INF40/INF41/INF42 form the migration-hygiene hardening package.

**Acceptance criteria.**
- Promotes atomic (BEGIN/COMMIT); `_mirror_manifest_and_impacts` extracted to `pipeline/manifest.py`.
- `fetch_adv.py` single-statement `CREATE OR REPLACE TABLE`; migration 004 pattern retrofit via staging/rename.
- `schema_versions` stamp hole closed; audit script `verify_migration_applied()` trustworthy.
- INF39 parity extended to L4 + L0 (INF45, INF46) + CI-wired (INF47).
- Admin refresh pre-restart design doc produced (if the work resumes this phase; else formally deferred to Phase 2).
- L3 surrogate row-ID (INF40) + read-site discipline (INF41) + derived-artifact hygiene (INF42) all shipped.

**Items.**

| ID | Title | Audit ref | ROADMAP ref | Findings-doc ref | Status | File-conflict zones | Logical dependencies | Sequencing batch | Notes |
|----|-------|-----------|-------------|------------------|--------|--------------------|----------------------|------------------|-------|
| mig-01 | BLOCK-2 atomic promotes + extract mirror helper | §4.1 BLOCK-2/C-01 | — | SYSTEM_AUDIT §4.1/§10.2 | CLOSED (PRs #31, #33) | `scripts/promote_nport.py`, `scripts/promote_13dg.py`, `scripts/pipeline/manifest.py` | None | 3-A | Atomic BEGIN/COMMIT wraps + `_mirror_manifest_and_impacts` helper extracted to `pipeline/manifest.py`. |
| mig-02 | MAJOR-14 fetch_adv.py DROP→CREATE atomic fix | §11.2 | — | SYSTEM_AUDIT §11.3 | CLOSED (PRs #35, #37) | `scripts/fetch_adv.py`, `scripts/promote_staging.py` | obs-01 decouples manifest registration | 3-A | Converted to staging→promote pattern (supersedes `CREATE OR REPLACE` plan). Also closes fetch_adv portion of mig-13. |
| mig-03 | MAJOR-15 migration 004 staging/rename atomicity pattern | §11.3 | — | SYSTEM_AUDIT §11.3, Pass 2 §5 | CLOSED (PRs #60, #62) | `scripts/migrations/004_summary_by_parent_rollup_type.py` | None | 3-B | Retrofit shipped: single BEGIN/COMMIT wrapping build-new-and-swap shadow (`summary_by_parent_new`); row-count parity check + `schema_versions` stamp moved inside the transaction; pre-transaction recovery probe restores canonical name from `_old` if a pre-fix crash state is detected. Pattern source: migration 003. |
| mig-04 | MAJOR-16 S-02 schema_versions stamp hole | §11.4, Pass 2 §0/§5 | — | SYSTEM_AUDIT §9.3/§11.4 | CLOSED (PRs #26, #29) | `scripts/migrations/add_last_refreshed_at.py`, `schema_versions` table | None | 3-A | Backfill script + `scripts/verify_migration_stamps.py` shipped; candidate for future smoke-CI wiring under mig-11. |
| mig-05 | BLOCK-4 admin refresh pre-restart rework | §10.3, Pass 2 §4 | — | `docs/admin_refresh_system_design.md` (recovered `03db9ad`); SYSTEM_AUDIT §10.3 | SUPERSEDED → Phase 2 | `scripts/migrations/010_pipeline_refresh_control_plane.py` (new; slot 010 because int-12 holds 009), `scripts/pipeline/base.py` (new), `scripts/pipeline/cadence.py` (new), `scripts/pipeline/protocol.py` (ABC reconciliation) | Full Phase 2 workstream — see "Phase 2" section above | Phase 2 | **Subsumed into full Phase 2 scope** per prog-01 (2026-04-20). Item retained as cross-reference anchor; actual work scheduled as Phase 2 kickoff (`prog-02` or equivalent). |
| mig-06 | INF40 L3 surrogate row-ID for rollback | — | INF40 | REWRITE_PCT_OF_SO §14.5/§14.11.4 | CLOSED (PRs #103, #104) | `scripts/migrations/014_v2_fact_row_id.py` (new), L3 canonical DDLs (`holdings_v2`, `fund_holdings_v2`, `beneficial_ownership_v2`) | None | 3-C | Phase 0 (PR #103) scoped surrogate `row_id` BIGINT PK approach across all 3 v2 fact tables; Phase 1 (PR #104) shipped migration 014 adding surrogate row_id + backfill. Applied prod + staging in conv-11 data-ops-batch-2. |
| mig-07 | INF41 read-site inventory discipline (rename sweep) | — | INF41 | REWRITE_PCT_OF_SO §14.11.4 | CLOSED (PR #101) | `scripts/audit_read_sites.py` (new; Mode 1 on-demand terminal) | None | 3-D | Mode 1 read-site audit tool shipped: scans `scripts/queries.py`, `scripts/api_*.py`, `web/react-app/src/**/*.tsx`, `tests/fixtures/responses/*.json` for stale column references against canonical DDL. Read-only; enforces exhaustiveness. |
| mig-08 | INF42 derived-artifact hygiene | — | INF42 | REWRITE_PCT_OF_SO §14.10 addendum, BLOCK_SCHEMA_DIFF | CLOSED (PRs #84, #86) | `.gitignore`, `web/react-app/dist/`, `tests/fixtures/13f_fixture.duckdb`, build scripts | None | 3-D | Phase 0 (PR #84) scoped three-pronged approach; Phase 1 (PR #86) shipped fixture provenance metadata (checksums + generation timestamps), CI staleness gate rejecting stale fixtures, and `.gitignore` hardening for derived artifacts. Closes the INF42 standing gap carried since conv-07 obs-13 close. |
| mig-09 | INF45 schema-parity extension — L4 derived | — | INF45 | BLOCK_SCHEMA_DIFF §9/§14 | CLOSED (PRs #72, #74) | `scripts/pipeline/validate_schema_parity.py`, `config/schema_parity_accept.yaml` | None | 3-C | Phase 0 (PR #72) scoped L4 to 14 derived tables + identified `entity_current` VIEW deferral. Phase 1 (PR #74) shipped `L4_TABLES` inventory + `--layer {l3,l4,l0,all}` CLI flag + missing-table pre-check; 116 tests pass (validator suite 26→72). |
| mig-10 | INF46 schema-parity extension — L0 control-plane | — | INF46 | BLOCK_SCHEMA_DIFF §9/§14 | CLOSED (PR #74) | `scripts/pipeline/validate_schema_parity.py`, config | None | 3-C | Combined with mig-09 per shared constants-block edit zone. `L0_TABLES` covers 6 control-plane tables; `admin_sessions` excluded (lives in `data/admin.duckdb` per sec-01-p1-hotfix). |
| mig-11 | INF47 schema-parity CI wiring | — | INF47 | BLOCK_SCHEMA_DIFF §10 Q5/§14 | CLOSED (PRs #78, #80) | `.github/workflows/smoke.yml`, `requirements.txt` | mig-09 or mig-10 (at least one schema scope extended) | 3-D | Phase 0 (PR #78) mapped gap: fixture covers 21/49 tables, 885-line validator unit suite at `tests/pipeline/test_validate_schema_parity.py` was never executed by CI, and `pyyaml` was a hidden transitive dep. Phase 1 (PR #80) shipped **Option A**: widened `pytest tests/smoke/` → `pytest tests/smoke/ tests/pipeline/` (109 tests total, picks up validator suite + 4 sibling files) and pinned `pyyaml==6.0.3` in `requirements.txt` + smoke-job install step. Options B (self-parity CLI smoke) and C (synthetic staging fixture — candidate `mig-11a`, shares mig-08 fixture tooling) deferred. `tests/test_admin_*.py` held out (pulls `curl_cffi` via `yahoo_client`, out of scope for CI runtime deps). |
| mig-12 | load_13f_v2 rewrite | — | — | PRECHECK_LOAD_13F_LIVENESS | **CLOSED 2026-04-22 (conv-12)** | `scripts/load_13f_v2.py` (new, `SourcePipeline`) | Phase 2 / p2-05 | — | **ABSORBED BY p2-05.** First full `SourcePipeline` subclass exercise; `Load13FPipeline` with `append_is_latest`. Q4 2025 dry-run green at +218 net rows. Legacy `scripts/load_13f.py` now flagged SUPERSEDED; retire after one clean quarterly cycle. |
| mig-13 | pipeline-violations REWRITE tail — residual scope: build_entities, merge_staging | §4.1 | — | pipeline_violations.md:122-485 | CLOSED (PRs #61, #63) | `scripts/build_entities.py`, `scripts/merge_staging.py`, `docs/pipeline_violations.md` | per-item: some depend on obs/int items | 3-B | Scope narrowed and closed: `fetch_adv` closed via mig-02 (PR #37); `build_fund_classes` + `build_benchmark_weights` closed via sec-05 (PR #45); 3 resolver scripts (`resolve_agent_names`, `resolve_bo_agents`, `resolve_names`) retired to `scripts/retired/` via sec-06 (PR #48). mig-13-p1 (PR #63) closed the final two scripts: `build_entities.py` gained 10 per-step CHECKPOINTs (§1 incremental save); `merge_staging.py` now sources `TABLE_KEYS` from `pipeline.registry.merge_table_keys()` (stale `beneficial_ownership` + `fund_holdings` v1 refs removed; `_v2` variants carried forward) and converts per-table try/except from silent swallow to collect-and-fail (live runs exit non-zero with a failure summary; `--drop-staging` suppressed when any table failed). `pipeline_violations.md` stamped CLEARED for both. |
| mig-14 | REWRITE_BUILD_MANAGERS remaining scope (INF1 staging routing + --dry-run + data_freshness) | — | — | REWRITE_BUILD_MANAGERS_FINDINGS | CLOSED (already-satisfied, PR #68) | `scripts/build_managers.py`, `scripts/db.py` (CANONICAL_TABLES), `scripts/promote_staging.py` (PK_COLUMNS + new `rebuild` kind) | INF30 int-14 decision on merge semantics | 3-B | Phase 0 (PR #68) verified every deliverable live at HEAD: `--staging` + `--dry-run` + 5 `data_freshness` stamps + `CANONICAL_TABLES` + `PK_COLUMNS` + new `rebuild` promote kind — shipped across commits `67e81f3`, `2a71f8a`, `4e64473`. Independently confirms sec-05-p0 §2/§5 conclusion. |

**Sequencing within theme.** 3-A atomicity + schema_versions stamp → 3-B small migrations + INF1 routing → 3-C parity extensions → 3-D hygiene/wiring.

**Parallel-eligibility within theme.** mig-01 and mig-04 share promotes-adjacent touch-points but disjoint files (`promote_*.py` vs `migrations/add_last_refreshed_at.py`) — **parallel-safe in Batch 3-A**.

---

### Theme 4 — Security hardening

**Problem statement.** `admin_bp.py` is a live write surface with a TOCTOU race (`pgrep` + `Popen` not serialized), admin token persisted in browser `localStorage` (XSS-readable, survives restart, no server-side invalidation), five hardcoded-prod builders bypass staging (`build_managers`, `build_fund_classes`, `build_benchmark_weights` — partially shipped), five unlisted direct-to-prod writers missing from pipeline_violations.md (`resolve_agent_names`, `resolve_bo_agents`, `resolve_names`, `backfill_manager_types`, `enrich_tickers`), validators write to prod during validation (`validate_nport_subset.py`, `pipeline/shared.py`), unpinned deps (`edgartools`, `pdfplumber`), divergent UA strings across 22+ scripts.

**Acceptance criteria.**
- Admin token migrated to server-side session table with HttpOnly cookie; XSS-readable `localStorage` path removed.
- `/run_script` gate uses `fcntl.flock` or manifest-backed check-and-set.
- Validators moved to staging DB; `validate_nport_subset.py` and `pipeline/shared.py` write-paths against prod eliminated or gated.
- Five unlisted direct-to-prod writers either staged or formally declared as exceptions in `pipeline_violations.md`.
- `requirements.txt` fully pinned (edgartools, pdfplumber).
- Central identity config for EDGAR UA; 22+ scripts converted to consume it.

**Items.**

| ID | Title | Audit ref | ROADMAP ref | Findings-doc ref | Status | File-conflict zones | Logical dependencies | Sequencing batch | Notes |
|----|-------|-----------|-------------|------------------|--------|--------------------|----------------------|------------------|-------|
| sec-01 | MAJOR-11 D-11 admin token localStorage → server-session | §11.1, Pass 2 §7.4 | — | SYSTEM_AUDIT §11.1 | CLOSED (PRs #5, #7, #9, #10, #21) | `web/templates/admin.html`, `scripts/admin_bp.py`, new migration + session table | None | 4-A | Server-side session table (migration 009) + HttpOnly cookie + CSRF + ATTACH adm serialization. |
| sec-02 | MAJOR-10 C-11 admin `/run_script` TOCTOU race | §11.1, Pass 2 §7.2 | — | SYSTEM_AUDIT §11.1 | CLOSED (PRs #11, #14, #19) | `scripts/admin_bp.py:267-283` | None | 4-A | `fcntl.flock` guard over cached script allowlist; regression test harness + isolation fix. |
| sec-03 | MAJOR-5 C-09 admin endpoint write-surface surface-audit | §4.1 | — | SYSTEM_AUDIT §4.1 | CLOSED (PRs #16, #17) | `scripts/admin_bp.py:86-90, :268-283, :597-771` | None | 4-B | `/add_ticker` flock + `/entity_override` 409-on-duplicate; inventory documented. |
| sec-04 | MAJOR-1 C-02 validators writing to prod | §4.1 | — | SYSTEM_AUDIT §4.1 | CLOSED (PRs #24, #27) | `scripts/validate_nport_subset.py`, `scripts/validate_entities.py`, new `scripts/queue_nport_excluded.py` | None | 4-B | Validators RO by default; write path extracted into new `queue_nport_excluded.py`; `pipeline/shared.py` was not touched (cleaner than predicted). |
| sec-05 | MAJOR-2 C-04 hardcoded-prod builders bypass staging | §4.1 | — | SYSTEM_AUDIT §4.1 | CLOSED (PRs #43, #45) | `scripts/build_fund_classes.py`, `scripts/build_benchmark_weights.py` | INF30 int-14 merge semantics | 4-C | Phase 0 confirmed `build_managers.py` already fully staged (plan claim "routing pending" was stale). Phase 1 fixed `--staging` path for the two remaining builders. |
| sec-06 | MAJOR-3 C-05 5 direct-to-prod writers missing inventory | §4.1 | — | SYSTEM_AUDIT §4.1 | CLOSED (PRs #47, #48) | `scripts/retired/resolve_agent_names.py`, `scripts/retired/resolve_bo_agents.py`, `scripts/retired/resolve_names.py`, `scripts/backfill_manager_types.py`, `scripts/enrich_tickers.py`, `docs/pipeline_violations.md` | None | 4-C | 3 dead resolvers retired to `scripts/retired/`; 2 live writers (backfill_manager_types, enrich_tickers) hardened; `pipeline_violations.md` stamped with 6 RETIRED + 11 RETROFIT markers. |
| sec-07 | MINOR-15 O-02 pin edgartools + pdfplumber | §8.1 | — | SYSTEM_AUDIT §8.1 | CLOSED (PR #39) | `requirements.txt` | None | 4-D | Pins landed in single session. |
| sec-08 | MINOR-17 O-08 central EDGAR identity config | §8.1 | — | SYSTEM_AUDIT §8.1 | CLOSED (PRs #40, #41) | `scripts/config.py`, 21 fetcher scripts | None | 4-D | `EDGAR_IDENTITY` helper centralized; 21 scripts normalized (one fewer than originally scoped). |
| sec-09 | Pass 2 §7.3 fetch_adv.py DROP-before-CREATE (sec-adj) | Pass 2 §7.3 | — | SYSTEM_PASS2 §7.3 | CLOSED (via mig-02, PRs #35, #37) | `scripts/fetch_adv.py` | **DUPLICATE of mig-02** — same file, same fix. | — | Closed as tracked-by-mig-02. |

**Sequencing within theme.** 4-A admin auth hardening → 4-B write-surface audit → 4-C staging-routing build-outs → 4-D dep pinning + config centralization.

**Parallel-eligibility within theme.** sec-01 ∥ sec-02 share `admin_bp.py` → **serial**. sec-04 ∥ sec-05 share writers-overlap with Theme 1 → serial with Theme 1 dependencies. sec-07 ∥ sec-08 disjoint — **parallel-safe in 4-D**.

---

### Theme 5 — Operational surface

**Problem statement.** Docs drift: `README.md` promotes retired `update.py`; project tree omits Blueprint/React/pipeline; `PHASE3_PROMPT.md` instructs retired `fetch_nport.py`; `ARCHITECTURE_REVIEW.md` vs `archive/docs/REACT_MIGRATION.md` contradict on Phase 4 status; `docs/deployment.md` missing React build; `write_path_risk_map.md` references retired scripts; `CLASSIFICATION_METHODOLOGY.md` cites 20,205 vs prod 26,535 entities; `PHASE1_PROMPT.md` untracked, `PHASE3/4` orphaned; no architecture doc for `scripts/api_*.py` Blueprint split; `ROADMAP.md` minor count drifts (928 vs 931, 4 vs 5). 7 doc updates deferred during BLOCK closeouts (`DOC_UPDATE_PROPOSAL_20260418.md` items 1-7) including new MAINTENANCE.md §Refetch Pattern for Prod Apply. `scripts/update.py` references retired `fetch_nport.py` + missing `unify_positions.py` — stale script itself.

**Acceptance criteria.**
- README.md + docs/deployment.md reflect FastAPI + React-build reality.
- ARCHITECTURE_REVIEW vs REACT_MIGRATION Phase 4 contradiction resolved.
- CLASSIFICATION_METHODOLOGY.md entity counts refreshed.
- write_path_risk_map.md aligned to Stage 5.
- 7 DOC_UPDATE_PROPOSAL items landed or re-deferred with explicit per-item decision.
- `scripts/update.py` retired or repaired.
- ROADMAP.md numeric drifts corrected.
- New `docs/api_architecture.md` or equivalent Blueprint split doc.

**Items.**

| ID | Title | Audit ref | ROADMAP ref | Findings-doc ref | Status | File-conflict zones | Logical dependencies | Sequencing batch | Notes |
|----|-------|-----------|-------------|------------------|--------|--------------------|----------------------|------------------|-------|
| ops-01 | MINOR-6 DOC-01 README retired update.py references | §7.1 | — | SYSTEM_AUDIT §7.1 | CLOSED (PR #6) | `README.md` | None | 5-A | |
| ops-02 | MINOR-7 DOC-02 README project tree refresh | §7.1 | — | SYSTEM_AUDIT §7.1 | CLOSED (PR #6) | `README.md` | ops-01 (same file) | 5-A | Serial with ops-01. |
| ops-03 | MINOR-8 DOC-03 PHASE3_PROMPT retired fetch_nport | §7.1 | — | SYSTEM_AUDIT §7.1 | CLOSED (PR #6) | `PHASE3_PROMPT.md` | None | 5-A | |
| ops-04 | MINOR-9 DOC-04 ARCH_REVIEW vs REACT_MIGRATION contradiction | §7.1 | — | SYSTEM_AUDIT §7.1 Cross-doc 2 | CLOSED (PR #6) | `ARCHITECTURE_REVIEW.md`, `archive/docs/REACT_MIGRATION.md` | None | 5-A | React Phase 4 status aligned. |
| ops-05 | MINOR-10 DOC-05 README_deploy React build prereq | §7.1 | — | SYSTEM_AUDIT §7.1 | CLOSED (PR #6) | `docs/deployment.md` | None | 5-A | |
| ops-06 | MINOR-11 DOC-06 write_path_risk_map stale | §7.1 | — | SYSTEM_AUDIT §7.1 | CLOSED (PR #32) | `docs/write_path_risk_map.md` | None | 5-B | T-tier classifications refreshed post-Stage 5. |
| ops-07 | MINOR-12 DOC-09 CLASSIFICATION_METHODOLOGY entity count | §7.1 | — | SYSTEM_AUDIT §7.1 Cross-doc 6 | CLOSED (PR #6) | `docs/CLASSIFICATION_METHODOLOGY.md` | None | 5-A | 20,205 → 26,535. |
| ops-08 | MINOR-13 DOC-10 PHASE1/3/4 prompts housekeeping | §7.1 | — | SYSTEM_AUDIT §7.1 | CLOSED (PR #6) | `PHASE1_PROMPT.md`, `PHASE3_PROMPT.md`, `PHASE4_PROMPT.md` | None | 5-A | |
| ops-09 | MINOR-14 DOC-12 api_*.py Blueprint split architecture doc | §7.1 | — | SYSTEM_AUDIT §7.1 | CLOSED (PR #32) | new `docs/api_architecture.md` | None | 5-B | |
| ops-10 | MINOR-1 R-01 ROADMAP 13DG exclusion count (928 vs 931) | §6.1 | — | SYSTEM_AUDIT §6.1 | CLOSED (PR #6) | `ROADMAP.md` | None | 5-A | |
| ops-11 | MINOR-2 R-02 ROADMAP NULL-CIK count (4 vs 5) | §6.1 | — | SYSTEM_AUDIT §6.1 | CLOSED (PR #6) | `ROADMAP.md` | None | 5-A | Same file as ops-10 — serial. |
| ops-12 | Pass 2 §8.2 migration 007 NULL-target doc note | Pass 2 §8.2/§11.4 | — | SYSTEM_PASS2 §8.2 | CLOSED (PR #6) | `scripts/migrations/007_override_new_value_nullable.py` (docstring), `docs/canonical_ddl.md` | None | 5-A | |
| ops-13 | DOC_UPDATE_PROPOSAL item 1 — denorm drift doc (data_layers.md §7) | — | INF25 | DOC_UPDATE_PROPOSAL §Item 1 | CLOSED (PR #75) | `docs/data_layers.md` §7 (new), `ENTITY_ARCHITECTURE.md`, `ROADMAP.md` | int-09 decision | 5-C | Bundled with int-09-p1 + ops-14 per shared doc edit zone. `data_layers.md §7` Steps 1–3 marked DONE with commits; Step 4 DEFERRED TO PHASE 2 with full exit criteria; `ENTITY_ARCHITECTURE.md` Known Limitation #6 + Design Decision Log addendum; "Observed drift" reframed to bounded-by-forward-hooks. |
| ops-14 | DOC_UPDATE_PROPOSAL items 2-5 (INF26-29 ROADMAP rows + notes) | — | INF26-29 | DOC_UPDATE_PROPOSAL §Items 2-5 | CLOSED (PR #75) | `ROADMAP.md`, `docs/data_layers.md`, `docs/canonical_ddl.md` | None | 5-C | Bundled with int-09-p1 + ops-13. `ROADMAP.md` INF25 row status "Sequenced" → "Deferred to Phase 2 (int-09 2026-04-22)"; notes cite commits for Steps 1–3 + link to `docs/findings/int-09-p0-findings.md §4`. |
| ops-15 | DOC_UPDATE_PROPOSAL item 7 — MAINTENANCE.md Refetch Pattern | — | — | DOC_UPDATE_PROPOSAL §Item 7 | CLOSED (PR #32) | `MAINTENANCE.md` | None | 5-B | §Refetch Pattern added. |
| ops-16 | DOC_UPDATE_PROPOSAL item 6 — admin_bp.py:108 revisit flag | — | INF30 | DOC_UPDATE_PROPOSAL §Item 6 | CLOSED (PR #70) | `docs/NEXT_SESSION_CONTEXT.md` or ROADMAP.md | None | 5-D | Refreshed `docs/NEXT_SESSION_CONTEXT.md` to current program state; F1 flag lives in session-context doc. |
| ops-17 | PRECHECK tertiary — retire or repair scripts/update.py | — | — | PRECHECK_LOAD_13F_LIVENESS | CLOSED (PR #55) | `scripts/update.py` | — | Phase 2 | Closed as already-satisfied by obs-10 (PR #52) — zero Makefile references remain; no standalone retire needed. |
| ops-18 | Restore missing `rotating_audit_schedule.md` (or re-source) | — | — | (user-referenced, not found) | BLOCKED | doc search | upstream doc recovery | Phase 2 | **File does not exist in this branch** — see App. D surprises. |

**Sequencing within theme.** 5-A high-speed doc edits (README, ROADMAP minor drifts, prompts) → 5-B write-path doc + MAINTENANCE Refetch Pattern → 5-C DOC_UPDATE_PROPOSAL bundles → 5-D flagged items pending decision.

**Parallel-eligibility within theme.** Docs are a write-hot zone (many items share ROADMAP.md, data_layers.md). Within 5-A, serial is safer than parallel unless items touch disjoint files. ops-01 ∥ ops-05 safe (README.md vs docs/deployment.md). ops-07 ∥ ops-04 safe (different files).

---

## Cross-theme parallel execution map

Conservative rule: any overlap on any touched file (including docs and tests) → serial. Ambiguity → Appendix A → serial-until-resolved.

| Pair | Safety | File-conflict zones (shared) | Logical dependencies | If REQUIRES-ANALYSIS: what to check |
|------|--------|------------------------------|----------------------|--------------------------------------|
| Theme 1 ∥ Theme 2 | REQUIRES-ANALYSIS | int-15 ∩ obs-03: both touch `scripts/fetch_market.py`. int-20 ∩ obs-05: both touch `scripts/build_summaries.py` or `docs/data_layers.md`. | obs items that unlock int-15 (freshness) | Per-item pairs may be safe. Case: **int-01 (build_cusip.py, run_openfigi_retry.py) ∥ obs-01 (fetch_ncen.py, fetch_adv.py, migrations/001)** — **disjoint → parallel-safe**. Case: **int-05 (enrich_holdings.py invocation) ∥ obs-03 (pipeline/manifest.py + fetch_market.py)** — disjoint → parallel-safe. |
| Theme 1 ∥ Theme 3 | REQUIRES-ANALYSIS | int-14 ∩ mig-14: both touch `scripts/promote_staging.py` + `scripts/merge_staging.py`. int-12 ∩ mig-06: both touch migrations + DDL. int-19 ∩ mig-12: both concern large-schema changes. | int-14 may need mig-xx routing decision | Case: **int-01 ∥ mig-01 — different file sets (build_cusip.py vs promote_nport.py + pipeline/manifest.py)** → parallel-safe. Case: **int-14 ∥ mig-14 — share promote_staging.py** → serial. |
| Theme 1 ∥ Theme 4 | REQUIRES-ANALYSIS | int-21 ∩ sec-04: both touch `scripts/pipeline/shared.py`. int-05/06 ∩ sec-06: both touch `scripts/enrich_tickers.py` (sec-06 listed), `scripts/build_cusip.py` (int-06). | int-01 ships before int-21; sec-04 independent | Case: **int-01 ∥ sec-01 (admin.html + admin_bp.py)** → disjoint → parallel-safe. Case: **int-21 ∥ sec-04** → share shared.py → serial. |
| Theme 1 ∥ Theme 5 | REQUIRES-ANALYSIS | int-09 ∩ ops-13: both touch `docs/data_layers.md` + `ENTITY_ARCHITECTURE.md` + `ROADMAP.md`. int-11 ∩ ops-14: both touch ROADMAP.md + data_layers.md. | int-09 decision must land before ops-13 | Code-only Theme 1 items (int-01..int-08) ∥ Theme 5 doc-only items that don't touch ROADMAP.md/data_layers.md are parallel-safe. |
| Theme 2 ∥ Theme 3 | REQUIRES-ANALYSIS | obs-02 ∩ mig-02: both touch `scripts/fetch_adv.py`. obs-04 ∩ mig-01: both touch `scripts/pipeline/manifest.py` + `scripts/promote_13dg.py`. | obs-01 declares ADV in manifest; mig-02 atomicity-fixes same writer | Same file ownership → serial. Exception: obs-03 (manifest.py/_next_id) ∥ mig-02 (fetch_adv.py) — disjoint → parallel-safe. |
| Theme 2 ∥ Theme 4 | **PARALLEL-SAFE** (conditional) | obs-09 ∩ sec-08 log/config crosscut likely disjoint. obs-06 ∩ sec-01 disjoint. | None | Confirm per specific first items; Batch 2-A (obs-01, obs-03) and Batch 4-A (sec-01, sec-02) touch disjoint files: `fetch_ncen/adv.py`+`manifest.py` vs `admin_bp.py`+`admin.html`. |
| Theme 2 ∥ Theme 5 | REQUIRES-ANALYSIS | obs-05 ∩ ops-13: `docs/data_layers.md`. obs-10 ∩ ops-01: Makefile is unique to obs, README unique to ops — disjoint. | None | Batch 2-C (Makefile) ∥ Batch 5-A (README.md) → parallel-safe. Batch 2-E (data_layers.md headline refresh) ∥ 5-C (ops-13 data_layers.md §7) → serial. |
| Theme 3 ∥ Theme 4 | **PARALLEL-SAFE** (conditional) | mig-05 admin refresh design touches admin_bp-adjacent docs; sec-03 admin write-surface audit touches admin_bp.py. | mig-05 blocked (design doc missing). | Batch 3-A (mig-01, mig-04) ∥ Batch 4-A (sec-01, sec-02) — files disjoint: promote*.py + migrations vs admin_bp.py + admin.html → parallel-safe. |
| Theme 3 ∥ Theme 5 | REQUIRES-ANALYSIS | mig-03 touches `scripts/migrations/004`; ops-12 touches `scripts/migrations/007`. Disjoint. mig-06 touches `docs/canonical_ddl.md`; ops-12 touches same. | None | Per-item file-disjoint check required. |
| Theme 4 ∥ Theme 5 | **PARALLEL-SAFE** | sec-* mostly scripts; ops-* mostly docs. sec-06 overlaps with ops-* via pipeline_violations.md. | None | Batch 4-A (admin_bp.py + admin.html) ∥ Batch 5-A (README + ROADMAP) → parallel-safe. |

**Conservative Batch 1 parallel-safe pairs (hard-verified files disjoint, zero logical dep):**

1. **Theme 4 Batch 4-A** (sec-01 + sec-02 admin hardening) — touches `scripts/admin_bp.py`, `web/templates/admin.html`, session-table migration.
2. **Theme 5 Batch 5-A subset** (ops-01 + ops-05 README hygiene; ops-07 classification methodology; ops-10/11 ROADMAP numeric drift) — touches `README.md`, `docs/deployment.md`, `docs/CLASSIFICATION_METHODOLOGY.md`, `ROADMAP.md`.
3. **Theme 2 Batch 2-A obs-03** (market impact_id hardening in `scripts/pipeline/manifest.py`, `scripts/fetch_market.py`) — disjoint from Themes 4 and 5.

These three can run in the **same wall-clock window**. Theme 1 and Theme 3 are deferred into Batch 2 (serial after Batch 1 completes) to eliminate shared-file risk on `scripts/pipeline/shared.py`, `scripts/promote_*.py`, and migration-adjacent paths.

---

## Known risks to parallel execution

Items or pairs flagged here default to **serial** until the ambiguity is resolved by a follow-up investigation. No item here is approved for parallel scheduling.

1. **int-09 (INF25 DENORM-RETIREMENT) ↔ ops-13 (DOC_UPDATE_PROPOSAL item 1)** — share `docs/data_layers.md`, `ENTITY_ARCHITECTURE.md`, `ROADMAP.md`. Ordering decision required.
2. **int-14 (INF30 merge NULL-only) ↔ mig-14 (build_managers INF1 routing)** — share `scripts/promote_staging.py`, `scripts/merge_staging.py`. mig-14 proposes a new `"rebuild"` strategy that may collide with int-14 mode.
3. **int-21 (MAJOR-7 unresolved series_id) ↔ sec-04 (validators→prod)** — both touch `scripts/pipeline/shared.py`. Serial.
4. **obs-02 / obs-04 ↔ mig-02 / mig-01** — fetch_adv.py and promote_13dg.py share file ownership across themes. Serial within those pairs.
5. **sec-05 (hardcoded-prod builders) ↔ mig-14 (build_managers routing)** — same file, different perspectives. Must be merged into one scope.
6. **mig-05 (BLOCK-4 admin refresh pre-restart)** — **UNBLOCKED 2026-04-20 (prog-01).** Design doc recovered at [`docs/admin_refresh_system_design.md`](./admin_refresh_system_design.md) (moved from untracked `Plans/` via commit `03db9ad`). Full Phase 2 scope now captured in the Phase 2 section above. Mig-05 as a Theme 3 item is superseded by the full Phase 2 workstream — treat mig-05's "admin refresh pre-restart rework" as subsumed into Phase 2 kickoff scope. Migration slot renumbered: 008 → 010 (not 009, since int-12 owns 009 for securities.cusip PK).
7. **ops-18 (rotating_audit_schedule.md)** — **BLOCKED: file referenced by user prompt does not exist in this branch.** May be in a separate repo, an unmerged branch, or still unwritten.
8. **obs-13 (DIAG-23 Register %FLOAT)** — likely-closed via `ff1ff71` CI-fixture regeneration and `fcf66f2` post-merge-fixes merge, but live verification on served `web/react-app/dist/` bundle required before marking DONE.
9. **int-15 (INF31 market_data fetch_date discipline)** — convention gap; acceptance criteria fuzzy. Needs scoping session before Phase 1.
10. **mig-06 (INF40 L3 surrogate row-ID)** — affects DDL on many L3 tables; bounds unknown. Phase 0 investigation to scope table-set first.

---

## Milestone: Foundation complete

**Acceptance criteria.**
- Every theme's "Acceptance criteria" section above at checkmark state.
- `make smoke` green.
- `python3 scripts/validate_entities.py --prod` reports 8 PASS / 2 FAIL (pre-existing) / 6 MANUAL.
- `make schema-parity-check` reports 0 divergences.
- `make freshness` reports all critical tables fresh ≤ 7 days.
- No INF-ID claimed-closed by the program still appears in `docs/DEFERRED_FOLLOWUPS.md` open set.
- `REMEDIATION_SESSION_LOG.md` contains one entry per theme's first parallel-safe session with `Parallel-safety validation: YES`.

---

## Phase 2 — Update Functions / Admin Refresh System (post-foundation)

**Spec source.** [`docs/admin_refresh_system_design.md`](./admin_refresh_system_design.md) (v3.2, ~992 lines) is the authoritative Phase 2 scope. Moved from untracked `Plans/` into `docs/` by commit `03db9ad` (2026-04-20). Prog-00 flagged this doc as missing — that was a false negative, now corrected.

**Supporting reference.** [`docs/data_sources.md`](./data_sources.md) (~204 lines) documents the seven data sources feeding the system (13F, N-PORT, 13D, 13G, N-CEN, ADV, market data) — cadence, public-lag, amendment semantics, coverage status, known gaps. Consumed by the Phase 2 Data Source UI tab (design §9). Also a permanent reference for Theme 2 observability work (cadence rules drive `PIPELINE_CADENCE`) and for any session touching a data-source pipeline.

### Scope summary

Phase 2 delivers a user-triggered data refresh system as a **framework**, not a one-off loader. Three user-facing deliverables plus a backend framework.

**User-facing (React):**
- **Admin status dashboard tab** (design §8) — per-pipeline cards with last-run, age, stale flag, new-data-available probe, rows added, refresh button, overdue reminders, run history drilldown.
- **Data Source tab** (design §9) — read-only renderer of `docs/data_sources.md` + runtime-generated cadence timeline SVG from `PIPELINE_CADENCE`.
- **Diff review & approval surface** (design §2b) — tiered presentation (small <1K rows full list, medium 1K-100K paginated + sample, large 100K+ summary + stratified sample), automatic anomaly detection, async approval with 24-hour staging retention, opt-in per-pipeline auto-approval.

**Backend framework (`scripts/pipeline/`):**
- **`base.py`** (PENDING) — concrete `SourcePipeline` ABC with `run()` orchestrator driving the 8-step staging flow (fetch → parse → validate → diff → snapshot → promote → verify → cleanup). Current `protocol.py` ships three structural `typing.Protocol`s; design §4 calls for a single ABC — **reconciliation decision required**.
- **`cadence.py`** (PENDING — file does not exist) — `PIPELINE_CADENCE` dict for 6 pipelines (13F, N-PORT, 13D/G, N-CEN, ADV, market) with `stale_threshold_days`, `next_expected_fn`, `probe_fn`, and `expected_delta` anomaly ranges.
- **`admin_preferences`** control-plane table (new) — per-user per-pipeline auto-approve configuration with JSON conditions.
- **9 admin endpoints** (design §8, §11, §2b): `POST /admin/refresh/{pipeline}`, `GET /admin/run/{run_id}`, `GET /admin/status`, `GET /admin/probe/{pipeline}`, `GET /admin/runs/pending`, `GET /admin/runs/{id}/diff`, `POST /admin/runs/{id}/approve`, `POST /admin/runs/{id}/reject`, `POST /admin/rollback/{run_id}`.
- **`load_13f_v2.py`** — first concrete pipeline on the framework (`append_is_latest` strategy). Current `load_13f.py` is rewritten in place (`8e7d5cb`, `a58c107`) with checkpoint/freshness/dry-run but not yet on base class.
- **Subsequent migrations**: `fetch_nport_v3.py`, `fetch_13dg_v3.py`, `fetch_market_v2.py`, `fetch_ncen_v2.py`, `fetch_adv_v2.py`.
- **`queries.py` sweep** — add `WHERE is_latest=TRUE` across all 13F / N-PORT / 13D/G read paths after migration applies.

**Control-plane integration points (L0):**
- `ingestion_manifest` (DONE — 21,339 rows) — every run writes one row.
- `ingestion_impacts` (DONE — 29,531 rows) — per-tuple `insert`, `flip_is_latest`, `scd_supersede` actions; backs `/admin/rollback/{run_id}`.
- `data_freshness` (DONE — 25 rows) — stamped via `SourcePipeline.stamp_freshness()`.
- `admin_preferences` — NEW, must be created in Phase 2.

### Migration numbering note (contradiction surfaced this session)

Design doc §5 + §12 originally numbered its schema migration as `008`. Slot `008_` is already used by `008_rename_pct_of_float_to_pct_of_so.py` (unrelated). The design doc flags this explicitly and recommends renumbering to `009_`.

**Contradiction with this plan's Appendix D:** slot `009_securities_cusip_pk.py` is already claimed by **int-12 (INF28)**. Phase 2's pipeline-refresh migration must take a different slot — **likely `010_pipeline_refresh_control_plane.py`** assuming int-12 ships first during Batch 1-D.

Resolution at Phase 2 kickoff: confirm int-12 has shipped at slot 009, then assign Phase 2's migration to slot 010. Appendix D is updated to reflect the renumber (see changelog).

### Dependencies on foundation themes

Phase 2 cannot proceed until the following foundation items ship. Each dependency is named with its theme ID and the one-sentence reason it blocks Phase 2.

**Theme 2 (observability) — hard dependencies.**
- **obs-01** (N-CEN + ADV in `ingestion_manifest`) — Phase 2's admin dashboard queries `ingestion_manifest` for every pipeline. ADV and N-CEN refreshes must be manifest-backed before the UI can surface them.
- **obs-02** (ADV freshness row + log) — ADV card on the admin dashboard reads `data_freshness` for the "Last run / Age / Status" fields; ADV currently has no freshness row.
- **obs-03** (market `impact_id` allocation hardening) — Phase 2 amplifies concurrent impact_id inserts (9 new endpoints, per-tuple action logging across all three amendment strategies). The `_next_id` race must be centralized before that load arrives.
- **obs-06** (13F loader `record_freshness`) — admin dashboard's 13F card reads `data_freshness`; load_13f's current stamp path needs verification.
- **obs-10** (`quarterly-update` Makefile 13F-load step) — manual smoke path used by admin UI's first refresh; Makefile completeness is a prerequisite.

**Theme 3 (migration discipline) — hard dependencies.**
- **mig-01** (atomic promotes + extract `_mirror_manifest_and_impacts` helper to `pipeline/manifest.py`) — `SourcePipeline.promote()` delegates to the shared helper; it must exist before the base class can be written.
- **mig-04** (`schema_versions` stamp hole) — Phase 2's migration 010 relies on `verify_migration_applied()` giving the right answer; the stamp-hole fix is upstream.
- **mig-09 / mig-10 / mig-11** (schema-parity extension — L4, L0, CI wiring) — Phase 2 adds a new L0 control-plane table (`admin_preferences`) and column-adds three L3 tables. Parity gate must cover both scopes before the migration promotes.

**Theme 4 (security) — hard dependencies.**
- **sec-01** (admin token → server-side session) — Phase 2 adds 9 new admin endpoints on top of the 15 existing ones. The localStorage-persisted token path is too brittle to expand.
- **sec-02** (`/run_script` TOCTOU race → `fcntl.flock` or manifest CAS) — Phase 2's "same pipeline cannot run twice simultaneously" invariant (design §11 concurrency) depends on a real lock, not `pgrep + Popen`.
- **sec-03** (admin endpoint write-surface audit) — inventory of existing admin routes is a prerequisite to mounting 9 more cleanly.

**Theme 1 (data integrity) — soft dependencies.**
- **int-12** (INF28 securities.cusip formal PK) — blocks Phase 2's migration numbering claim on slot 009 (resolved by Phase 2 taking slot 010, see Migration numbering note above).
- **int-14** (INF30 NULL-only merge mode) — Phase 2's `direct_write` strategy for market data may benefit from NULL-only semantics; coupled but not a hard blocker.

**Theme 5 (ops) — soft dependencies.**
- **ops-15** (MAINTENANCE.md §Refetch Pattern) — user-facing documentation of manual refetch coupled with admin UI refresh surface.

### Phase 2 prerequisite status as of 2026-04-20

**DONE:**
- `ingestion_manifest` / `ingestion_impacts` / `data_freshness` / `pending_entity_resolution` tables live in prod (`731f4a0`, `2892009`, `54bfaad`, `831e5b4`).
- `scripts/pipeline/manifest.py`, `discover.py`, `registry.py`, `shared.py` (`stamp_freshness` wrapper) — shipped.
- `scripts/pipeline/protocol.py` — three structural Protocols shipped (awaiting ABC reconciliation decision).
- `load_13f.py` in-place rewrite — checkpoint + freshness + dry-run + fail-fast (`8e7d5cb`, `14a5152`, `a58c107`).
- `fetch_nport_v2.py` 4-mode orchestrator + DERA ZIP primary (`44bc98e`, `f02cefa`).
- `fetch_ncen.py` freshness stamp (`54bfaad`).
- `enrich_13dg.py` freshness guard (`54bfaad`).
- `Makefile` — `freshness` / `status` / `quarterly-update` + `check_freshness.py` + `schema-parity-check` (`831e5b4`, `c4e802c`, `4ec0862`).
- `docs/data_sources.md` moved from `Plans/` to `docs/` (`03db9ad`) — phase-12 prerequisite clear.
- `FreshnessBadge` on all 11 tabs (`83836ee`, `3526757`).

**IN FLIGHT (tracked as foundation theme items):**
- obs-01, obs-02, obs-03, obs-06, obs-10 (Theme 2).
- mig-01, mig-04, mig-09, mig-10, mig-11 (Theme 3).
- sec-01, sec-02, sec-03 (Theme 4).

**PENDING (Phase 2-native):**
- `scripts/pipeline/base.py` — concrete SourcePipeline ABC with `run()`.
- `scripts/pipeline/cadence.py` — file does not exist.
- Migration 010 — three columns (`accession_number`, `is_latest`, `loaded_at`, `backfill_quality`) on `holdings_v2`, `fund_holdings_v2`, `beneficial_ownership_v2` + backfill with quality stats.
- `queries.py` sweep — `WHERE is_latest=TRUE` on all 13F / N-PORT / 13D/G read sites.
- 9 admin endpoints + `admin_preferences` table.
- `load_13f_v2.py` formal extract to base class.
- React: Admin status dashboard tab + Data Source tab.

### Major Phase 2 components (at a glance)

| Component | Target path | Status |
|---|---|---|
| SourcePipeline ABC + `run()` | `scripts/pipeline/base.py` (new) | PENDING |
| Cadence config + probe fns | `scripts/pipeline/cadence.py` (new) | PENDING |
| Admin preferences table | `scripts/migrations/010_pipeline_refresh_control_plane.py` (new) | PENDING (slot assignment post-int-12) |
| Column-adds + backfill | same migration | PENDING |
| 9 admin endpoints | `scripts/admin_bp.py` (extend) | PENDING |
| Data Source tab | `web/react-app/src/tabs/DataSourceTab.tsx` (new) | PENDING |
| Admin dashboard tab | `web/react-app/src/tabs/AdminRefreshTab.tsx` (new) | PENDING |
| `load_13f_v2.py` | `scripts/load_13f_v2.py` (new) | PENDING |
| queries.py `is_latest` sweep | `scripts/queries.py` | PENDING |

### Open design questions (from design §14 + §15)

- **§14 Migration execution order** — sequential (per-table, three promote cycles) vs single atomic transaction. Recommendation in doc: sequential. Re-confirm at Phase 2 kickoff.
- **§4 Protocol vs ABC decision** — current `protocol.py` has three `typing.Protocol`s (`runtime_checkable`); design §4 calls for a single ABC with `run()` orchestrator. Must reconcile: retrofit existing Protocols to an ABC, or accept divergence. Decision gates the shape of every concrete pipeline refactor.
- **§15 reviewer items 1-9** (9 targets) — staging-flow edge cases (partial fetch, resume-from-checkpoint, multi-scope), diff tier boundaries (1K / 100K), anomaly rule tightness, 24-hour retention window, SourcePipeline contract sufficiency, holdings_v2 "newest accession wins" heuristic on ~0.5% ambiguous rows, PIPELINE_CADENCE correctness, probe rate-limit under multi-session load, rollback guarantee sufficiency.

### Recommended Phase 2 entry criteria

Treat Phase 2 as **formally deferred** until:
1. Every foundation-theme hard dependency above ships.
2. `make smoke` + `validate_entities --prod` + `make schema-parity-check` + `make freshness` all green ("Milestone: Foundation complete" above).
3. Migration slot collision resolved (int-12 at 009, Phase 2 at 010).
4. Serge authorizes Phase 2 kickoff session (`prog-02` or equivalent).

Phase 2 itself is 5-session scope minimum: base class + cadence + migration + admin endpoints + React tabs. Reviewer questions §15 will surface more.

---

## Phase 3 — Medium-term

- **load_13f_v2 rewrite** (mig-12): Full rewrite of `load_13f.py` into `fetch_13f.py` + `promote_13f.py`, applying Batch 3 retrofit bar (CHECKPOINT, data_freshness, --dry-run, --staging, PROCESS_RULES §1-§9 compliance). See `docs/findings/2026-04-19-precheck-load-13f-liveness.md`.
- **INF38 BLOCK-FLOAT-HISTORY** (int-19): True period-accurate `pct_of_float` from 10-K Item 5 + Schedule 13D/G + Forms 3/4/5 insider holdings. Additional tier above `pct_of_so`.
- **INF40 L3 surrogate row-ID** (mig-06) if deferred from foundation.
- **BL-3 transaction-based safety** for T2-tier scripts per `docs/write_path_risk_map.md`.
- **React Phase 4C+** OpenAPI-typed client (8 endpoints pending from `PHASE4_STATE.md`).

---

## Phase 4 — Long-term

- **Rotating audits** — schedule referenced but not found; recover or author from audit §12 cadence (quarterly lite-audits May–October).
- **Next main audit** — October 2026 per audit §12.4 (all BLOCK + MAJOR resolved; MINOR running punch-list).
- **Phase 5/6 ARCHITECTURE_REVIEW Medium-Term items** (MT-1 through MT-6) trigger-based (team expansion, productization).

---

## Appendix A — Cross-reference index

**Legend.** Aliases across audit / ROADMAP / findings docs → single theme/status row. Items marked **AMBIGUOUS** default to SERIAL-ONLY.

| Canonical ID | Audit ref | ROADMAP ref | Findings-doc alias | Theme | Status | Notes |
|--------------|-----------|-------------|--------------------|-------|--------|-------|
| audit-BLOCK-1 entity backfill | §3.1/§10.1 BLOCK-1 D-01/D-02 | — | "BLOCK-2 apply" commit 5b501fc | 1 | **CLOSED 5b501fc** | Audit's BLOCK-1 = commit's BLOCK-2 due to local numbering drift. |
| audit-BLOCK-3 legacy-table writes | §3.1/§9.2 BLOCK-3 D-05 S-01 | — | "BLOCK-1" commit 12e172b | 4/2 | **CLOSED 12e172b** | Audit's BLOCK-3 = commit's BLOCK-1. |
| audit-BLOCK-2 atomic promotes | §4.1 BLOCK-2 C-01 | — | — | 3 | **OPEN** mig-01 | Transaction wrap + helper extraction. |
| audit-BLOCK-4 admin refresh | §10.3 BLOCK-4 | — | `docs/admin_refresh_system_design.md` | Phase 2 | **UNBLOCKED** (2026-04-20) → Phase 2 | Design doc recovered `03db9ad`. Subsumed into full Phase 2 workstream. |
| audit-MAJOR-4 compute_flows atomicity | §4.1 MAJOR-4 C-08 | — | Batch 3 close 87ee955 | — | **LIKELY CLOSED 87ee955** | Violation doc marked CLEARED 7ac96b7; atomicity specifically needs verification. |
| BLOCK-PCT-OF-SO-PERIOD-ACCURACY | — | INF38 ancestor | REWRITE_PCT_OF_SO_PERIOD_ACCURACY | — | **CLOSED** bee49ff + ea4ae99 + multiple | Migration 008 + Pass B rewrite + live smoke shipped. |
| BLOCK-SCHEMA-DIFF | — | INF39 | BLOCK_SCHEMA_DIFF_FINDINGS | — | **CLOSED** f22312e | L3 canonical parity live; L4/L0/CI extensions deferred to mig-09/10/11. |
| INF34 rollup_type filter | — | INF34 | REWRITE_PCT_OF_SO §14.10 | — | **CLOSED** 62ad0eb | Full investor_flows + summary_by_parent sweep. |
| INF23 entity fragmentation | — | INF23 | MAINTENANCE.md DM workstream | — | **CLOSED** 53d6e7b | Morningstar/DFA merge + Milliman CIK backfill. |
| INF1 beneficial ownership workstream | — | INF1 | 2026-04-16-13dg-entity-linkage.md | — | **CLOSED** 5efae66 | 2,591 CIKs resolved; BO v2 94.52%. |
| DIAG-23 Register %FLOAT | — | INF42 ancestor | POST_MERGE_REGRESSIONS §1 | 2 | **LIKELY CLOSED** ff1ff71 | Verify served bundle. |
| DIAG-24 Flow duplicates | — | INF34 | POST_MERGE_REGRESSIONS §2 | — | **CLOSED** 62ad0eb | |
| DIAG-25 Conviction 500 | — | — | POST_MERGE_REGRESSIONS §3 | — | **CLOSED** d0a1e51 | COALESCE is_actively_managed NULL fix. |
| DIAG-26 CI smoke snapshot | — | — | CI_SMOKE_FAILURE_DIAGNOSIS | — | **CLOSED** ff1ff71 | Fixture regenerated. |
| Batch 3 REWRITE queue tail | — | — | pipeline_violations.md §4-5 | 3 | **PARTIALLY CLOSED** 499e120, 7ac96b7, c51ed65 | Doc-close-outs landed; retrofit tail items still open for each REWRITE script. |
| REWRITE_BUILD_MANAGERS | — | — | REWRITE_BUILD_MANAGERS_FINDINGS | 3/4 | **PARTIALLY CLOSED** 1719320, 7747af2 | Holdings retire done; INF1 routing + flags pending → mig-14. |
| REWRITE_BUILD_SHARES_HISTORY | — | — | REWRITE_BUILD_SHARES_HISTORY_FINDINGS | — | **CLOSED** 4fea358 | Dead code retired. |
| REWRITE_LOAD_13F | — | — | REWRITE_LOAD_13F_FINDINGS | 3 | **PARTIALLY CLOSED** 05427c7 | Holdings DROP+CTAS retired; broader rewrite → mig-12 (Phase 3). |
| REWRITE_BUILD_SUMMARIES | — | — | REWRITE_BUILD_SUMMARIES_FINDINGS | — | **CLOSED** 87ee955 | |
| Stage 5 legacy-tables drop | §9.2 | — | data_layers.md §8 | — | **CLOSED** 305739e, 7247689 | 3 legacy tables dropped; writers repointed. |
| React Phase 4 cut over | — | — | archive/docs/REACT_MIGRATION.md | — | **CLOSED** (2026-04-13) | FastAPI + React build prereq live. |
| DIAG-Ambiguous (obs-13) | — | INF42 | post-merge | 2 | **AMBIGUOUS** | Live dist verification pending. |
| mig-05 admin refresh | §10.3 | — | `docs/admin_refresh_system_design.md` | Phase 2 | **SUPERSEDED** by Phase 2 | Design doc recovered `03db9ad` (prog-01); item subsumed into full Phase 2 scope. Renumber migration to slot 010 (int-12 holds 009). |
| ops-18 rotating audit schedule | — | — | — | 5 | **AMBIGUOUS (BLOCKED)** | Referenced file not found. |

---

## Appendix B — Items surfaced post-audit

The original audit (2026-04-17) captured BLOCK items 1-4, MAJOR items 1-17, MINOR items 1-20. Between 2026-04-17 and 2026-04-20, the following items were surfaced in findings docs and merit inclusion in this program:

- **INF39** (CLOSED) — BLOCK-STAGING-PROD-SCHEMA-DIVERGENCE. Surfaced during pct-of-so Phase 4 abort; shipped as standalone schema-parity gate.
- **INF40** (OPEN, mig-06) — BLOCK-L3-SURROGATE-ROW-ID. Surfaced as companion to pct-of-so migration 008 rollback design.
- **INF41** (OPEN, mig-07) — BLOCK-READ-SITE-INVENTORY-DISCIPLINE. Surfaced during pct-of-so Phase 4c rename sweep — proves need for mechanical exhaustiveness.
- **INF42** (OPEN, mig-08) — BLOCK-DERIVED-ARTIFACT-HYGIENE. Surfaced by DIAG-23 (stale `web/react-app/dist/` serving pre-rename bundle).
- **INF45/46/47** (OPEN, mig-09/10/11) — schema-parity extension package (L4, L0, CI wiring). Surfaced in INF39 closeout.
- **Post-merge diagnostic suite** (DIAG-23/24/25/26) — all four surfaced 2026-04-19 post-pct-of-so merge; three shipped fixes, one doc update.
- **BLOCK-TICKER-BACKFILL** — surfaced 2026-04-18 as 5-phase Phase 0 investigation; Phase 1a+1b ready.
- **BLOCK-SECURITIES-DATA-AUDIT** — Phase 3 prod promote shipped 2026-04-18; Phase 1 code fixes (RC1-RC4) still open.
- **DOC_UPDATE_PROPOSAL_20260418** — 7 deferred doc updates from BLOCK closeouts, batched for post-foundation commit.
- **PRECHECK_LOAD_13F_LIVENESS_20260419** — confirmed `load_13f.py` live, cannot retire; rewrite-block scoped.
- **CI_SMOKE_FAILURE_DIAGNOSIS_20260419** — snapshot drift from intentional correctness fix; snapshot regen executed.

All post-audit items are cross-referenced in the theme tables above and in Appendix A.

---

## Appendix C — Closed items log

Items confirmed CLOSED via commit SHA or doc-sync confirmation as of 2026-04-20:

| Item | Commit(s) | Close date | Notes |
|------|-----------|------------|-------|
| audit-BLOCK-1 entity_id backfill (= repo BLOCK-2) | `488401a`, `5b501fc` | 2026-04-17 | 6,205,976 rows; coverage 40.09% → 84.13%. |
| audit-BLOCK-3 legacy-table writes (= repo BLOCK-1) | `12e172b` | 2026-04-19 | Removed `fetch_nport.py` from `/run_script` allowlist. |
| BLOCK-PCT-OF-SO-PERIOD-ACCURACY | `bee49ff`, `ea4ae99`, `0871178..208bc86` | 2026-04-19 | Migration 008 + Pass B rewrite + tier cascade + live smoke. |
| BLOCK-SCHEMA-DIFF (INF39) | `f22312e`, `d0e5f45`, `ef59352`, `4aea6d1` | 2026-04-19 | L3 canonical parity gate live; 0 divergences. |
| INF34 rollup_type filter | `62ad0eb`, `91f7af9` | 2026-04-19 | Full investor_flows + summary_by_parent sweep. |
| INF23 Morningstar/DFA merge | `53d6e7b` | 2026-04-17 | 171 relationships + 43 rollup targets re-pointed. |
| INF1 13D/G filer resolution | `5efae66` | 2026-04-17 | 2,591 CIKs: 23 MERGE + 1,640 NEW + 928 exclusions. |
| DIAG-24 Flow Analysis duplicates | `62ad0eb` | 2026-04-19 | (subsumed by INF34) |
| DIAG-25 Conviction 500 | `d0a1e51` | 2026-04-19 | COALESCE `is_actively_managed`. |
| DIAG-26 CI smoke fixture regen | `ff1ff71` | 2026-04-19 | Snapshot drift from correctness fix. |
| Batch 3 close (compute_flows + build_summaries) | `87ee955` | 2026-04-16 | + migration 004. |
| compute_flows violations cleared | `7ac96b7` | 2026-04-19 | doc close. |
| build_summaries violations cleared | `c51ed65` | 2026-04-19 | doc close. |
| Batch 3 REWRITE queue doc-close | `499e120` | 2026-04-19 | build_shares_history, load_13f, build_managers. |
| Phantom `other_managers` table decision (REWRITE_LOAD_13F §6.4) | `14a5152`, `a58c107` | 2026-04-19 | Option A (add writer) — OTHERMANAGER2 loader; 15,405 rows live; `docs/findings/phantom-other-managers-decision.md`. |
| Stage 5 legacy-table drop | `305739e`, `7247689` | 2026-04-13 / 2026-04-17 | 3 tables dropped; writers repointed. |
| build_managers holdings → holdings_v2 + Phase 4 prod apply | `1719320`, `7747af2` | 2026-04-19 | |
| backfill_manager_types holdings → holdings_v2 | `7b8a2b7` | 2026-04-19 | |
| load_13f dead holdings DROP+CTAS retired | `05427c7` | 2026-04-19 | |
| build_shares_history dead code retired | `4fea358` | 2026-04-19 | |
| React Phase 4 cut over | (multiple) | 2026-04-13 | FastAPI + React build prereq. |
| Phase 0-A lint CI | (multiple) | 2026-04-13 | Ruff + pylint + bandit green. |
| Phase 0-B2 smoke CI | `8cf0d82` | 2026-04-13 | |
| FreshnessBadge rollout | `83836ee` | 2026-04-13 | 11 tabs wired. |
| INF11 PROMOTE_KIND split | `b13d5f8` | 2026-04-13 | Companion to INF30. |
| INF12 admin Blueprint + token auth | `8a41c48` | 2026-04-10 | |
| INF15 circular rollup pair resolution | `8c37bb2` | 2026-04-10 | |
| Full INF1-INF18, INF22-24 closed list | — | — | See ROADMAP.md COMPLETED section. |

---

## Appendix D — File-conflict matrix

Lookup table for parallel-scheduling decisions. Each row is a source file; columns are the items that touch it.

| File | Items that touch it |
|------|---------------------|
| `scripts/admin_bp.py` | sec-01, sec-02, sec-03, ops-16 (via Plans/ refresh) |
| `scripts/build_cusip.py` | int-01 (RC1), int-06 (Pass C hook), int-12 (PK migration prep) |
| `scripts/build_managers.py` | mig-14, sec-05 |
| `scripts/build_summaries.py` | int-16, int-17, int-20, obs-05 |
| `scripts/compute_flows.py` | obs-11 |
| `scripts/enrich_holdings.py` | int-05 (Pass C invoke), int-19 (Pass B tier extension) |
| `scripts/fetch_adv.py` | obs-01, obs-02, mig-02, sec-06 (inline UA fix) |
| `scripts/fetch_market.py` | obs-03, int-15, int-13 |
| `scripts/fetch_ncen.py` | obs-01 (manifest registration) |
| `scripts/fetch_nport_v2.py` | sec-06 (UA), obs-03 (impact_id consumer) |
| `scripts/load_13f.py` | obs-06 (freshness), mig-12 (full rewrite) |
| `scripts/merge_staging.py` | int-14, mig-14 |
| `scripts/migrations/001_pipeline_control_plane.py` | obs-01, obs-04 |
| `scripts/migrations/004_summary_by_parent_rollup_type.py` | mig-03 |
| `scripts/migrations/007_override_new_value_nullable.py` | ops-12 |
| `scripts/migrations/add_last_refreshed_at.py` | mig-04 |
| `scripts/migrations/009_securities_cusip_pk.py` (new) | int-12 |
| `scripts/migrations/010_pipeline_refresh_control_plane.py` (new, Phase 2) | Phase 2 kickoff (was mig-05 at slot 009 — renumbered post-doc-recovery to avoid int-12 collision) |
| `scripts/pipeline/base.py` (new, Phase 2) | Phase 2 kickoff |
| `scripts/pipeline/cadence.py` (new, Phase 2) | Phase 2 kickoff |
| `scripts/normalize_securities.py` | int-04, int-06 |
| `scripts/pipeline/cusip_classifier.py` | int-02, int-23 |
| `scripts/pipeline/manifest.py` | mig-01, obs-03, obs-04 |
| `scripts/pipeline/shared.py` | int-21, sec-04 |
| `scripts/pipeline/validate_schema_parity.py` | mig-09, mig-10, mig-11 |
| `scripts/promote_13dg.py` | mig-01, obs-04 |
| `scripts/promote_nport.py` | mig-01, obs-07 |
| `scripts/promote_staging.py` | int-14, mig-14 |
| `scripts/queries.py` | mig-07 (read-site scripted audit; scan-only unless rename occurs) |
| `scripts/refetch_missing_sectors.py` | int-08, int-15 |
| `scripts/resolve_*.py` (agent_names, bo_agents, names) | sec-06 |
| `scripts/run_openfigi_retry.py` | int-01, int-10 |
| `scripts/validate_nport_subset.py` | sec-04 |
| `scripts/update.py` | ops-17 |
| `Makefile` | obs-10, mig-11 |
| `requirements.txt` | sec-07 |
| `README.md` | ops-01, ops-02 |
| `docs/deployment.md` | ops-05 |
| `ARCHITECTURE_REVIEW.md` | ops-04 |
| `archive/docs/REACT_MIGRATION.md` | ops-04 |
| `ROADMAP.md` | ops-10, ops-11, ops-13, ops-14, ops-16 |
| `MAINTENANCE.md` | ops-15 |
| `ENTITY_ARCHITECTURE.md` | ops-13, int-09 |
| `PHASE1_PROMPT.md`, `PHASE3_PROMPT.md`, `PHASE4_PROMPT.md` | ops-03, ops-08 |
| `docs/data_layers.md` | obs-05, ops-13, ops-14, int-11, int-13 |
| `docs/canonical_ddl.md` | mig-06, ops-12, int-12 |
| `docs/pipeline_inventory.md` | mig-14, obs-01 |
| `docs/pipeline_violations.md` | sec-06, mig-13 |
| `docs/CLASSIFICATION_METHODOLOGY.md` | ops-07 |
| `docs/write_path_risk_map.md` | ops-06 |
| `docs/NEXT_SESSION_CONTEXT.md` | ops-16 |
| `docs/DEFERRED_FOLLOWUPS.md` | tracked by all workers at close |
| `tests/fixtures/13f_fixture.duckdb` | mig-08, mig-11 |
| `tests/fixtures/responses/*.json` | mig-07, mig-08 |
| `.github/workflows/smoke.yml` | obs-12, mig-11 |
| `.github/workflows/lint.yml` | obs-12 |
| `web/react-app/dist/` | mig-08 |
| `web/react-app/src/**/*.tsx` | mig-07 (read-site audit) |
| `web/templates/admin.html` | sec-01 |

---

## Changelog

- **2026-04-23 (hygiene-file-leak-fix)** — Mitigated the "file-leak-to-main" pattern that recurred three times across the 2026-04-23 Group A session batch (`entity-curation-w1`, `build-fund-classes-rewrite`, `bl7-ticker-validation`). Root cause: gitignored DB files (`data/13f.duckdb`, `data/admin.duckdb`, `data/13f_staging.duckdb`) exist only in the primary worktree, so worker sessions in secondary worktrees `cd` into the primary repo path to run DB scripts. Subsequent `Edit`/`Write` calls using absolute paths then land on main's working tree rather than the feature branch. Shipped `scripts/bootstrap_worktree.sh` (idempotent; symlinks the five gitignored DB files from the primary into the current worktree; no-op in the primary) plus `docs/SESSION_GUIDELINES.md` documenting the root cause, the bootstrap workflow, a belt-and-braces absolute-path rule, and a session-start hygiene checklist. Scope deliberately narrow — symlinks only the DB files (not `data/raw` / `data/cache` / `outputs` etc., whose trailing-slash `.gitignore` patterns do not match symlinks and would surface in `git status`). Verified: pre-bootstrap `data/13f.duckdb` missing in worktree → bootstrap creates symlink → DuckDB `connect('data/13f.duckdb')` resolves to primary DB (12,270,984 `holdings_v2` rows) → `git status` clean. No script changes; no migration; no PR-body-side impact on in-flight worktrees (apply by running the bootstrap on them).
- **2026-04-23 (tier4-review-gate)** — Codified the Tier 4 join-pattern review rule in a new top-level checklist at `docs/REVIEW_CHECKLIST.md`. Hybrid enforcement per [tier-4-join-pattern-proposal.md §7](proposals/tier-4-join-pattern-proposal.md) is now the standing pre-merge gate: hard rule for net-new `scripts/queries.py` functions reading from `holdings_v2` / `fund_holdings_v2` (must go through `scripts/queries_helpers.py`); soft rule for modifications to existing stamp-column functions (bundle into the int-09 Step 4 sweep, now unblocked per `DEFERRED_FOLLOWUPS.md` INF25). Worldview-correctness note included — `entity_current` hardcodes EC, so DM paths must use `rollup_join`. Exemption marker convention: `# tier4-exempt: <reason>` on the line above the `def`. Docs-only session; no code paths changed; `scripts/queries_helpers.py` untouched.
- **2026-04-22 (p2fu-cleanup-01)** —
  - **P2-FU-02** closed — scheduler/update/benchmark stale-reference audit. Retired `fetch_*.py` paths repointed to `SourcePipeline` subclasses.
  - **P2-FU-04** closed — ADV ownership boundary for `cik_crd_direct` + `lei_reference` documented in `data_layers.md` + `admin_refresh_system_design.md`.
- **2026-04-22 (conv-12)** — **Phase 2 + Wave 2 complete.** Admin refresh system shipped (p2-01 through p2-10-fix): concrete `SourcePipeline` ABC in `scripts/pipeline/base.py` with eight-step staging flow, atomic promote, explicit column list (p2-10-fix); `scripts/pipeline/cadence.py` with `PIPELINE_CADENCE` + probe_fns + `expected_delta`; migrations 015 (amendment-semantics columns on three amendable fact tables), 016 (`admin_preferences`), 017 (`ncen_adviser_map` SCD columns); `queries.py` sweep added `WHERE is_latest=TRUE` to 149 read sites; 9 admin endpoints on `scripts/admin_bp.py`; `/admin/dashboard` + Data Source tab live. All five Wave 2 pipeline migrations shipped: w2-01 13D/G, w2-02 market, w2-03 N-PORT, w2-04 N-CEN (first `scd_type2`), w2-05 ADV. Registry in `scripts/pipeline/pipelines.py` carries six entries. `mig-12` **CLOSED — absorbed by p2-05** `load_13f_v2.py` (first full `SourcePipeline` subclass exercise; Q4 2025 dry-run +218 net rows). Retired to `scripts/retired/`: `fetch_13dg*.py`, `validate_13dg.py`, `promote_13dg.py`, `fetch_market.py`, `fetch_nport*.py`, `validate_nport*.py`, `promote_nport.py`, `fetch_ncen.py`, `fetch_adv.py`, `promote_adv.py`. Follow-ups: legacy `run_script` allowlist cleanup in `admin_bp.py`, ADV SCD conversion, scheduler/update/benchmark stale-reference audit, int-09 Step 4 denorm retirement (now unblocked).
- **2026-04-22 (conv-11)** — **REMEDIATION PROGRAM COMPLETE.**

  Final tally: 104 PRs (#5-#104), ~66 items closed across 5 themes.
  All data ops executed. Migrations 011-014 applied to prod + staging.
  67 new entities created (int-21). Ticker overrides triaged (int-03).
  1,103 OTC securities flagged (int-13). 51,902 13D/G impact rows backfilled (obs-04).
  Surrogate row_ids on all 3 v2 fact tables (mig-06).
  Read-site audit tool shipped (mig-07).

  Theme completion:
  - Theme 4 Security: 8/8 DONE
  - Theme 2 Observability: 13/13 DONE
  - Theme 5 Ops: 17/18 (ops-18 BLOCKED — external design doc)
  - Theme 3 Migration: 11/14 (mig-05 SUPERSEDED, mig-12 Phase 3, mig-11a deferred)
  - Theme 1 Integrity: 16/~20 (int-18 STANDING, int-19/int-09-Step4 DEFERRED to Phase 2)

  Remaining items are standing, deferred, blocked, or Phase 2/3 scope.
  No actionable remediation items remain.

  Ready for Phase 2 planning. Design doc: docs/admin_refresh_system_design.md.
- **2026-04-22 (conv-10)** — **Final convergence session for the remediation program.** 14 PRs merged since conv-09 (PRs #87 through #100, with PR #100 the program milestone). Items closed in this window: **int-03** BLOCK-SEC-AUD-3 ticker_overrides.csv manual triage (PRs #91, #96 — triage export of 568-row inventory + apply of 6 ticker fixes + 2 removals; original scope estimate of ~20-40 errors was high); **int-11** INF27 CUSIP residual-coverage tracking (PR #87 — doc-only, tracking tier documented in data_layers.md + ROADMAP); **int-12** INF28 securities.cusip formal PK (PRs #92, #95 — Phase 0 validated zero-duplicate CUSIP state, Phase 1 shipped migration 011 applying formal PK constraint; slot renumbered 009→011 because slots 009/010 were consumed by sec-01 + obs-03); **int-13** INF29 OTC grey-market classifier (PRs #94, #97 — introduced explicit `is_otc` column via migration 012 + classifier + backfill script; 1,103-row prod backfill executed); **int-14** INF30 NULL-only merge mode (PR #85 — shipped to `merge_staging.py`/`promote_staging.py`; Phase 0 scoping PR #81); **int-15** INF31 market_data fetch_date discipline (PRs #88, #90 — Phase 0 narrowed to 2-line fix, Phase 1 stamped `fetch_date` + `metadata_date` on sector refetch UPDATE); **int-16** INF35 f-string cosmetic (PR #83); **int-17** INF36 top10_* NULL placeholders (PR #99 — drop decision over populate: migration 013 dropped 30 unused `top10_*` columns from `summary_by_parent`); **int-20** MAJOR-6 orphan-CUSIP secondary driver (PR #89 — findings only: auto-resolved by securities coverage repairs); **int-21** MAJOR-7 15.87% unresolved series_id tail (PRs #93, #98, #100 — triage export + new-entity worksheet + unified apply: 67 new entities + 27 resolve + 3 exclude, 100 series linked, 1,399 accepted unresolved); **mig-08** INF42 derived-artifact hygiene (PRs #84, #86 — fixture provenance metadata + CI staleness gate + `.gitignore` hardening; closes the INF42 standing gap carried since conv-07 obs-13 close). **Data ops executed (no PRs — prod/staging DB writes):** obs-04 `backfill_13dg_impacts.py --confirm` (51,902 manifest + 51,902 impact rows); int-10 staging sweep `--confirm` (81 rows); int-13 `is_otc` backfill `--confirm` (1,103 rows); migrations 011/012/013 applied to prod + staging. **Theme milestones:** **Theme 1 data integrity — 22/23 CLOSED (int-18 standing, int-19 Phase 2 deferral).** **Theme 2 observability — 13/13 CLOSED (complete since conv-07).** **Theme 3 migration — 11/14 CLOSED** (add mig-08; remaining actionable: mig-06 surrogate row-ID, mig-07 read-site audit; plus mig-05 SUPERSEDED and mig-12 Phase 3). **Theme 4 security — 8/8 CLOSED (complete since conv-03).** **Theme 5 operational — 17/18 CLOSED** (ops-18 BLOCKED — `rotating_audit_schedule.md` not in branch). **Program total: 100 PRs merged (#5-#100), ~66 items closed across the checklist, program milestone PR #100 hit.** Remaining actionable items: **mig-06** (L3 surrogate row-ID for rollback), **mig-07** (read-site inventory discipline). Everything else is standing (int-18), deferred (int-19 Phase 2, int-09 Step 4 Phase 2), superseded (mig-05), Phase 3 (mig-12), or blocked (ops-18). **Merge waves:** merge-wave-14 through merge-wave-18 covered PRs #81-#100 sequentially with zero conflicts. CHECKLIST flipped (10 rows: int-03, int-11, int-12, int-13, int-15, int-16, int-17, int-20, int-21, mig-08; int-14 reflected below as additional close but was not in the original conv-10 scope brief). SESSION_LOG updated with entries for int-11-p1, int-15-p0/p1, int-20-p0, int-03-export/apply, int-12-p0/p1, int-21-export/dedup/apply, int-13-p0/p1, int-17-p1, int-16-p1, mig-08-p0/p1, merge-wave-14..18, data-ops-batch, and conv-10. Item-table statuses updated: int-03, int-10 (data op executed), int-11, int-12, int-13, int-14, int-15, int-16, int-17, int-20, int-21, mig-08, obs-04 (data op executed). **Program close recommendation:** the remediation program has reached its stated "Foundation complete" milestone. Two residual actionable items (mig-06 surrogate row-ID + mig-07 read-site audit) are appropriate to schedule as a lite-audit follow-up rather than keep the foundation program open. Phase 2 kickoff (admin refresh framework) is now unblocked on every foundation dependency.
- **2026-04-22 (conv-09)** — Convergence doc update covering 5 PRs merged since conv-08 (PRs #76-#80). Items closed in this window: **int-22** MINOR-5 C-06 fix_fund_classification no-CHECKPOINT retrofit (PR #76 — `con.execute("CHECKPOINT")` inserted after the `executemany` UPDATE on `fund_universe`, durably flushing the write before verification queries run; low-pri Batch 1-E retrofit); **int-23** BLOCK-SEC-AUD-5 universe expansion 132K→430K acceptance (PR #77 — closed as already-implemented: prod + staging `cusip_classifications` = `securities` = 430,149 rows; three-source UNION distinct CUSIPs = 430,149; `get_cusip_universe()` has no gating/cap/flag; universe fully live since CUSIP v1.4 prod promotion `8a41c48` 2026-04-15; no code change, no migration, no SSE); **mig-11** INF47 schema-parity CI wiring (PRs #78, #80 — Phase 0 mapped the gap: fixture covered only 21/49 tables and the 885-line validator suite at `tests/pipeline/test_validate_schema_parity.py` was never executed in CI + `pyyaml` was a hidden transitive dep; Phase 1 shipped **Option A**: widened `pytest tests/smoke/` → `pytest tests/smoke/ tests/pipeline/` picking up 109 tests total across 5 pipeline test files and pinned `pyyaml==6.0.3` in `requirements.txt` + smoke-job install step; Option B self-parity CLI smoke and Option C synthetic-staging fixture both deferred — Option C surfaced as candidate `mig-11a` row sharing mig-08 fixture tooling; `tests/test_admin_*.py` deliberately excluded — imports `yahoo_client` which requires `curl_cffi`, out of scope for CI runtime deps today). **Theme milestones:** **Theme 3 migration advances to 10/14 CLOSED** (add mig-11 to the list). **Theme 1 data integrity advances to 13/23 CLOSED** (add int-22 + int-23). Remaining Theme 3 actionable: mig-06, mig-07, mig-08 (+ mig-05/12 Phase 2/3 deferrals). Remaining Theme 1: int-03, int-11..int-17, int-20, int-21 + standing int-18 + Phase 2 int-19 (10 open). **Merge-wave-13** landed PRs #76-#80 sequentially with zero conflicts; all five PRs touched disjoint file zones (fix_fund_classification.py, three findings docs, and the smoke.yml + requirements.txt pair). **Pending data ops carried forward:** obs-04 `scripts/oneoff/backfill_13dg_impacts.py --confirm` + int-10 staging sweep `--confirm` — both gated behind Serge approval; status unchanged. **Standing gaps carried forward:** `entity_current` VIEW schema-parity micro-follow-up (mig-09-p0 §4 Option A); INF42 derived-artifact hygiene CI gate (mig-08); candidate `mig-11a` synthetic staging fixture (Option C). **Program total: 80 PRs merged (#5-#80), 56 items closed across the checklist, ~14 remaining** — Theme 1 data integrity (10 open: int-03, int-11..int-17, int-20, int-21 + standing int-18 + Phase-2 int-19), Theme 3 migration (3 actionable: mig-06, mig-07, mig-08 + mig-05/12 Phase 2/3 deferrals), Theme 5 operational (1: ops-18 BLOCKED). CHECKLIST flipped (3 rows: int-22, int-23, mig-11). SESSION_LOG updated with 7 new entries (int-22-p1, int-23-p0, mig-11-p0, conv-08 commit/merge-status backfill, mig-11-p1, merge-wave-13, conv-09). Item-table statuses updated for all 3 closed rows.
- **2026-04-22 (conv-08)** — Convergence doc update covering 8 PRs merged since conv-07 (PRs #68-#75). **Theme 5 operational advances to 17/18 CLOSED — only ops-18 BLOCKED remains** (rotating_audit_schedule.md file not found). **Theme 3 migration advances to 9/14 CLOSED** (add mig-09, mig-10, mig-14 to the list). **Theme 1 data integrity advances to 11/23 CLOSED** (add int-06 NO-OP, int-07 gate-PASS, int-08 SKIPPED, int-09 Phase-2-deferred). Items closed in this window: **int-07** benchmark_weights Phase 2 gate PASS (PR #71 — all 3 gates satisfied; coverage + no-regression + tier-stability); **int-08** SKIPPED (no PR; conditional on int-07 gate failure, which did not occur); **int-09** INF25 BLOCK-DENORM-RETIREMENT sequencing formalized as Phase 2 deferral (PRs #73, #75 — Phase 0 quantified Step 4 scope at ~500 `queries.py` read sites + `rollup_entity_id` dual-graph; Phase 1 bundled with ops-13 + ops-14 embeds exit criteria in `data_layers.md §7`); **mig-09** + **mig-10** combined schema-parity extension (PRs #72, #74 — `L4_TABLES` 14 derived + `L0_TABLES` 6 control-plane + `--layer {l3,l4,l0,all}` CLI flag + missing-table pre-check; 116 tests pass, validator suite 26→72); **mig-14** REWRITE_BUILD_MANAGERS closed as already-satisfied (PR #68 — Phase 0 verified every original deliverable live at HEAD `4484137`: `--staging` + `--dry-run` + 5 `data_freshness` stamps + `CANONICAL_TABLES` + `PK_COLUMNS` + new `rebuild` promote kind across commits `67e81f3`/`2a71f8a`/`4e64473`); **int-06** forward-looking Pass C hooks closed as NO-OP (PR #69 — Phase 0 confirmed both end-of-run subprocess hooks in `build_cusip.py` + `normalize_securities.py` already shipped prior to program window); **ops-13** data_layers.md §7 denorm drift doc refreshed (PR #75); **ops-14** ROADMAP INF25 cross-ref + notes (PR #75); **ops-16** NEXT_SESSION_CONTEXT.md refresh (PR #70). Two merge-waves landed: **merge-wave-11** (PRs #68-#71, Phase 0 batch) + **merge-wave-12** (PRs #72-#75, Phase 0 + Phase 1 batch); both clean, zero conflicts. **Pending data ops carried forward:** obs-04 backfill `--confirm` + int-10 staging sweep `--confirm` — both gated behind Serge approval; status unchanged from conv-07. **`entity_current` VIEW schema-parity micro-follow-up** tracked separately per mig-09-p0 §4 Option A. **Program total: 75 PRs merged (#5-#75), 53 items closed across the checklist, ~17 remaining** — Theme 1 data integrity (12 open: int-03, int-11..int-17, int-20..int-23 + standing int-18 + Phase-2 int-19), Theme 3 migration (4 actionable: mig-06, mig-07, mig-08, mig-11 + mig-05/12 Phase 2/3 deferrals), Theme 5 operational (1: ops-18 BLOCKED). CHECKLIST flipped (10 rows: int-06, int-07, int-08 SKIPPED, int-09, mig-09, mig-10, mig-14, ops-13, ops-14, ops-16). SESSION_LOG updated with 11 new entries (mig-14-p0, int-06-p0, ops-16-p1, int-07-p0, mig-09-p0, int-09-p0, mig-09-10-p1, int-09-p1-ops-13-14, merge-wave-11, merge-wave-12, conv-08). Item-table statuses updated for all 10 closed rows.
- **2026-04-20** — Initial consolidation. 47 INF items mapped, 21 INF items retroactively confirmed CLOSED with commit citations. 41 audit items distributed across 5 themes. 5 post-audit items incorporated (INF39-47 + post-merge diagnostic suite + DOC_UPDATE_PROPOSAL + PRECHECK). 2 items BLOCKED pending upstream doc recovery (mig-05, ops-18). Batch 1 parallel-safe seed identified: Themes 2+4+5 subsets. Themes 1 and 3 deferred to Batch 2 to eliminate shared-file risk on `scripts/pipeline/shared.py` and `scripts/promote_*.py`.
- **2026-04-20 (prog-01)** — Phase 2 placeholder replaced with full scope folded from recovered `docs/admin_refresh_system_design.md` v3.2 (moved from `Plans/` by `03db9ad`). Full dependency graph captured: 5 Theme-2 items, 5 Theme-3 items, 3 Theme-4 items as hard Phase 2 prerequisites, plus 2 Theme-1 and 1 Theme-5 soft deps. mig-05 reclassified from BLOCKED to SUPERSEDED-by-Phase-2. Migration slot collision surfaced: Phase 2 migration renumbered 008 → 010 (not 009; int-12 owns 009 for securities.cusip PK). `docs/data_sources.md` referenced from Phase 2 scope (rendered by Data Source UI tab per design §9). Appendix D updated with three new file entries (`base.py`, `cadence.py`, migration 010). No new foundation-theme items surfaced — all Phase 2 prerequisites were already captured in Themes 1-5. Rescan of 72 repo `.md` files found no additional scope-carrying docs; one minor note: `web/README_deploy.md` may be a stale duplicate of root `docs/deployment.md` (ops-05 already tracks root).
- **2026-04-21 (conv-07)** — Convergence doc update covering 3 additional PRs merged since conv-06 (PRs #64 through #66). **Theme 2 observability: ALL 13/13 CLOSED (program milestone).** Items closed in this window: **obs-05** MAJOR-17 data_layers.md coverage headline refresh (PR #66 — headline re-anchored to 14,090,397 rows / 84.13% `entity_id` coverage, prod-verified 2026-04-21; BLOCK-2 2026-04-17 + CUSIP v1.4 2026-04-15 cited as stability baseline); **obs-11** Pass 2 §6.4 `flow_intensity_total` formula docstring (PR #66 — 9-line docstring on `_compute_ticker_stats` + new §10 Flow metrics section in data_layers.md documenting `flow_intensity_{total,active,passive}` + churn variants); **obs-13** DIAG-23 Register %FLOAT stale dist bundle verification (PR #65 — verified PASS: React source + rebuilt dist bundle both free of `pct_of_float`; ff1ff71 touched CI fixtures only, no dist rebuild required; findings in `docs/findings/obs-13-verify-findings.md`; **INF42 derived-artifact hygiene CI gate remains a standing gap**, tracked separately). **obs-06** had already closed as **NO-OP / already-satisfied (no PR)** via `8e7d5cb` (`load_13f.py` rewrite) prior to conv-04 — retroactively confirmed here. **int-05** had already closed as **NO-OP (PR #46)** and **int-10** as **CLOSED (PRs #42, #44, staging sweep pending)** in conv-03 — no status change needed. **Theme milestones:** **Theme 2 observability — 13/13 CLOSED (complete).** **Theme 4 security — 8/8 CLOSED (complete, sustained since conv-03).** Theme 5 operational — 14/18 CLOSED (carried). Theme 3 migration — 5/14 CLOSED (carried from conv-06). Theme 1 data integrity — 5/18 CLOSED (int-01, int-02, int-04, int-05, int-10; carried). **Program total: 66 PRs merged (#5-#66), 46 items closed across the checklist, ~24 remaining across Themes 1, 3, 5** (Theme 1 data integrity + Theme 3 migration Batches 3-C/3-D/mig-14 + Theme 5 ops-13/14/16/18). **Merge-wave-10** covered PRs #64-#66; these had already landed via conv-06 merge command + individual PR merges prior to this convergence session (no separate coordination wave required). **Pending data ops (not code) carried forward:** obs-04 `scripts/oneoff/backfill_13dg_impacts.py --confirm` + int-10 staging sweep `--confirm` — both gated behind Serge approval. CHECKLIST flipped (3 items: obs-05, obs-11, obs-13). SESSION_LOG updated with 4 new entries (conv-07 itself + obs-batch-2E + obs-13-verify + merge-wave-10). Item-table statuses updated: obs-05 (OPEN→CLOSED PR #66), obs-11 (OPEN→CLOSED PR #66), obs-13 (LIKELY-CLOSED→CLOSED PR #65).
- **2026-04-21 (conv-06)** — Convergence doc update covering 4 additional PRs merged since conv-05 (PRs #60 through #63). Both Theme 3 Batch 3-B items that were still OPEN closed in this window. **mig-03** MAJOR-15 migration 004 atomicity retrofit (PRs #60, #62 — Phase 0 findings doc + Phase 1 retrofit wrapping `004_summary_by_parent_rollup_type.py` in single BEGIN/COMMIT using build-new-and-swap shadow pattern; row-count parity check + `schema_versions` stamp moved inside transaction; pre-transaction recovery probe restores canonical name from `_old` if pre-fix crash state detected; pattern source migration 003). **mig-13** pipeline-violations REWRITE tail CLOSED (PRs #61, #63 — Phase 0 verified scope already narrowed to 2 scripts, then Phase 1 closed both: `build_entities.py` gained 10 per-step CHECKPOINTs (§1 incremental save); `merge_staging.py` now sources `TABLE_KEYS` from `pipeline.registry.merge_table_keys()` (stale `beneficial_ownership` + `fund_holdings` v1 refs removed; `_v2` variants carried forward) and converts per-table try/except from silent swallow to collect-and-fail — live runs exit non-zero with a failure summary, `--drop-staging` suppressed when any table failed; `pipeline_violations.md` stamped CLEARED for both scripts). **Theme milestones:** Theme 3 migration advanced to **5/14 CLOSED** (mig-01, mig-02, mig-03, mig-04, mig-13). Remaining open in Theme 3: mig-06/07/08/09/10/11 (Batches 3-C/3-D), mig-14 (Batch 3-B — last B-item), plus mig-05/12 Phase 2/3. **Merge-wave-9** landed PRs #60-#63 sequentially with zero conflicts; parallel-safety held. CHECKLIST flipped (2 items: mig-03, mig-13). SESSION_LOG updated with 6 new entries (conv-06 itself + mig-03-p0 + mig-03-p1 + mig-13-p0 + mig-13-p1 + merge-wave-9). Item-table statuses updated: mig-03 (OPEN→CLOSED PRs #60/#62), mig-13 (OPEN narrowed → CLOSED PRs #61/#63).
- **2026-04-21 (conv-05)** — Convergence doc update covering 4 additional PRs merged since conv-04 (PRs #55 through #58). **obs-08** backup-gap investigation closed (PR #58 — no infra gap; MAINTENANCE.md wording fix + retention note + `backup-db` Makefile target wired; obs-08 CHECKLIST row was self-updated by PR #58, plan-table row corrected from "PR #TBD" to "PR #58"). **obs-09** log-rotation policy shipped (PR #56 — `scripts/rotate_logs.py` + Makefile target address the 182-file `logs/` backlog). **obs-12** CI Node-20 deprecation cleared (PR #57 — GitHub Actions bumped to Node 24 across workflows). **ops-17** `scripts/update.py` retirement closed as **already-satisfied** (PR #55 — obs-10 / PR #52 had already pruned all Makefile references; standalone retire not needed). **Theme milestones:** Theme 5 operational — **14/18 CLOSED** (ops-17 resolved as already-satisfied via obs-10). Theme 2 observability — **10/13 CLOSED** (obs-01/02/03/04/06/07/08/09/10/12 closed; obs-05 data_layers.md headline + obs-11 formula docstring + obs-13 verify-only remain). **Merge-wave-8** landed PRs #55-#58 sequentially with zero conflicts; parallel-safety held. CHECKLIST flipped (3 items: obs-09, obs-12, ops-17; obs-08 was already self-flipped by PR #58). SESSION_LOG updated with 6 new entries (conv-05 itself + obs-08-p1 + obs-09-p1 + obs-12-p1 + ops-17-p1 + merge-wave-8). Item-table statuses updated: obs-08 (PR #TBD→#58), obs-09 / obs-12 / ops-17 (OPEN→CLOSED).
- **2026-04-21 (conv-04)** — Convergence doc update covering 5 additional PRs merged since conv-03 (PRs #49 through #53), plus retroactive coverage of obs-06 close (NO-OP) that conv-03 did not capture. Program-wide total now **53 PRs merged** and **37 items closed** across the checklist. **Theme 4 security: ALL 8/8 CLOSED (program milestone sustained).** Items closed in this window: **int-02** RC2 MAX(issuer_name_sample) mode aggregator (PR #50 — closed under **Option A (no re-seed now)**; code shipped `fc2bbbc` 2026-04-18, prod `cusip_classifications` carries 8,178-row MAX-era residual accepted as informational; re-seed deferred to int-23 / organic refresh); **obs-06** MINOR-3 13F loader freshness (closed as **NO-OP / already-satisfied** — `record_freshness('filings')` + `record_freshness('filings_deduped')` shipped in `8e7d5cb` prior to this program window; no PR); **obs-07** MINOR-4 N-PORT report_month future-leakage gate (PRs #51, #53 — preventive gate in `promote_nport.py` rejects future `report_month` rows with per-row logging); **obs-10** INF32 quarterly-update Makefile 13F-load step (PR #52 — wired `load-13f` + `promote-adv` targets into `quarterly-update`, pruned retired `update.py` references). **Theme milestones:** Theme 2 observability — 8 of 13 items CLOSED (obs-01/02/03/04/06/07/10 + obs-13 likely-closed). Remaining open in Theme 2: obs-05 (data_layers.md headline), obs-08 (backup-gap ops), obs-09 (log-rotation ops), obs-11 (formula docstring), obs-12 (Node 20→22 CI). Theme 3 migration advanced further: 2 of 11 actionable items CLOSED (mig-01, mig-02, mig-04 of pre-Phase-2 scope); mig-13 residual scope narrowed to **build_entities + merge_staging only** (fetch_adv closed via mig-02; build_fund_classes + build_benchmark_weights closed via sec-05; 3 resolvers retired via sec-06). Theme 1 advanced: int-01/02/04/05/10 CLOSED. **Merge-wave-7** landed PRs #49-#53 sequentially with zero conflicts; parallel-safety held. **Pending data ops (not code):** obs-04 backfill `--confirm` execution, int-10 staging sweep `--confirm` execution — both gated behind Serge approval. **3 scripts retired to `scripts/retired/`** convention (from sec-06, carried forward): `resolve_agent_names.py`, `resolve_bo_agents.py`, `resolve_names.py`. **mig-02 converted `fetch_adv.py` to staging→promote**, closing fetch_adv portion of mig-13 and retiring sec-09 (duplicate). **obs-10 wired `load-13f` + `promote-adv`** into Makefile `quarterly-update`; pruned retired `update.py` refs. **obs-07 shipped preventive `report_month` future-leakage gate** in `promote_nport.py`. CHECKLIST flipped (3 items: obs-06, obs-07, obs-10). SESSION_LOG updated with 7 new entries (conv-04 itself + conv-03 + obs-07-p0/p1 + obs-10-p1 + obs-06-p1 + merge-wave-7). Item-table statuses backfilled: int-01/02/04, obs-01/02/03/06/07/10, mig-01/mig-04, sec-01/02/03/04, ops-01..ops-12 + ops-06/09/15 — many of these rows were still showing OPEN in the plan despite being closed in the CHECKLIST during conv-01/conv-02 (stale-marker drift corrected). mig-13 row retitled to "residual scope: build_entities, merge_staging"; sec-05 notes already reflected build_managers already-staged per conv-03.
- **2026-04-21 (conv-03)** — Convergence doc update covering 14 additional PRs merged since conv-02 (PRs #35 through #48), bringing program-wide total to **45 PRs merged** and **~33 items closed** across the checklist. **Theme 4 security fully closed (8/8 items).** Items closed in this window: **mig-02** MAJOR-14 fetch_adv.py DROP→CREATE (PRs #35, #37 — converted to staging→promote pattern, supersedes naive `CREATE OR REPLACE`; also closes fetch_adv portion of mig-13); **obs-04** MAJOR-8 13D/G ingestion_impacts grain backfill (PRs #36, #38 — one-off backfill script shipped, data op pending `--confirm`); **sec-05** MAJOR-2 hardcoded-prod builders (PRs #43, #45 — Phase 0 confirmed `build_managers.py` already fully staged; plan row "routing pending" note was stale and has been updated; Phase 1 fixed `--staging` path for fund_classes + benchmark_weights); **sec-06** MAJOR-3 direct-to-prod writers inventory (PRs #47, #48 — 3 dead resolvers retired to `scripts/retired/` (`resolve_agent_names`, `resolve_bo_agents`, `resolve_names`); 2 live writers (`backfill_manager_types`, `enrich_tickers`) hardened; `pipeline_violations.md` stamped with 6 RETIRED + 11 RETROFIT markers); **sec-07** MINOR-15 dep pinning (PR #39); **sec-08** MINOR-17 central EDGAR identity config (PRs #40, #41 — 21 scripts normalized, one fewer than originally scoped); **int-05** BLOCK-TICKER-BACKFILL Phase 1a closed as **NO-OP** (PR #46 — retroactive Pass C sweep confirmed already executed in an earlier session, no residual work); **int-10** INF26 `_update_error()` permanent-pending bug (PRs #42, #44 — code fix shipped, one-off staging sweep pending `--confirm`). **Theme milestones:** **Theme 4 security fully closed (8/8).** Theme 2 observability has obs-04 closed (with backfill data op pending); obs-06/07/10 + doc items remain. Theme 3 migration advanced: mig-02 closed (plus fetch_adv portion of mig-13); mig-03/mig-13-tail/mig-14 and Batches 3-C/D remain. Theme 1 has int-05 (NO-OP) + int-10 closed; int-02/03/06/07/08/09/11/12/13/14/15/16/17/20/21/22/23 remain. **Parallel execution ran 2–3 workers wide across all themes** over conv-02→conv-03 window; three sequential merge-waves (merge-wave-4: PRs #35-#41; merge-wave-5: PRs #42-#45; merge-wave-6: PRs #46-#48) all landed clean with zero conflicts. One PARTIAL parallel-safety drift logged: sec-08-p1 touched 21 scripts instead of the Appendix D-predicted 22 (one script had out-of-scope UA convention) — direction held, count off by one. **Notable plan correction:** sec-05 row in item table now reflects that `build_managers.py` was already fully staged before this window; the "routing pending" note in the prior plan was stale from before Phase 4 migration stabilization. **3 scripts retired to `scripts/retired/`** as a new convention (sec-06): `resolve_agent_names.py`, `resolve_bo_agents.py`, `resolve_names.py`. CHECKLIST flipped (8 items: mig-02, obs-04, sec-05, sec-06, sec-07, sec-08, int-05, int-10). SESSION_LOG updated with 15 new entries (conv-03 itself + 14 worker/coordination sessions: mig-02-p0/p1 + obs-04-p0/p1 + sec-07-p1 + sec-08-p0/p1 + merge-wave-4 + int-10-p0/p1 + sec-05-p0/p1 + merge-wave-5 + int-05-p0 + sec-06-p0/p1 + merge-wave-6). Item-table statuses for 9 rows updated from OPEN/READY/PARTIAL → CLOSED (including sec-09 closed-via-mig-02).
- **2026-04-21 (conv-02)** — Convergence doc update covering 10 additional PRs merged since conv-01 (PRs #24 through #33), bringing program-wide total to **29 PRs merged** and **24 items closed** across the checklist. Items closed in this window: **sec-04** MAJOR-1 validators writing to prod (PRs #24, #27 — validators now RO by default; write path extracted to new `queue_nport_excluded.py`); **obs-01** MAJOR-9 N-CEN + ADV manifest registration (PRs #20, #25); **obs-02** MAJOR-12 ADV freshness + log discipline (PRs #28, #30); **mig-01** BLOCK-2 atomic promotes + `_mirror_manifest_and_impacts` helper (PRs #31, #33); **mig-04** MAJOR-16 schema_versions stamp backfill + `verify_migration_stamps.py` (PRs #26, #29); **ops-06/09/15** Batch 5-B doc updates — write_path_risk_map refresh + new api_architecture.md + MAINTENANCE §Refetch Pattern (PR #32). **Theme milestones:** Theme 4 security substantially complete (sec-01/02/03/04 all closed; sec-05/06 direct-writer inventory and sec-07/08 pinning + EDGAR-identity remain). Theme 3 migration formally begun (mig-01 + mig-04 closed; mig-02/03/13/14 and Batches 3-C/D remain). Theme 2 observability mostly closed (obs-01/02/03 done; obs-04/06/07/10 + doc items remain). **Parallel execution validated at 2–4 workers wide across all 5 themes** over the conv-01→conv-02 window — notable parallel sets: sec-04-p0 ∥ obs-01-p1 (PRs #24/25); mig-04-p0 ∥ sec-04-p1 (PRs #26/27); obs-02-p0 ∥ mig-04-p1 (PRs #28/29); mig-01-p1 ∥ ops-batch-5B (PRs #33/32). Two PARTIAL parallel-safety drifts logged: (1) sec-04-p1 did NOT touch `pipeline/shared.py` as predicted — extracted write path into new `queue_nport_excluded.py` module, a cleaner outcome than predicted; (2) no overlap surfaced between mig-01-p1 and the earlier obs-03-p1 touch of `pipeline/manifest.py` because merge ordering held. Appendix D predictions remain substantively correct; the new-module extraction pattern should be anticipated for future RO-default refactors. CHECKLIST flipped (8 items), SESSION_LOG updated with 11 new entries (conv-02 itself + sec-04-p0/p1 + obs-01-p1 + obs-02-p0/p1 + mig-01-p0/p1 + mig-04-p0/p1 + ops-batch-5B).
- **2026-04-21 (conv-01)** — Convergence doc update covering 18 PRs merged (PRs #5 through #22). Items closed: **sec-01** MAJOR-11 admin token server-side session (PRs #5, #7, #9, #10, #21); **sec-02** MAJOR-10 /run_script TOCTOU (PRs #11, #14, #19); **sec-03** MAJOR-5 admin write-surface audit (PRs #16, #17); **obs-03** MAJOR-13 market impact_id allocation (PRs #8, #12); **int-01** RC1 OpenFIGI foreign-exchange filter (PRs #13, #15 — data sweep complete, 216 residual CUSIPs confirmed legitimate foreign-only and accepted); **int-04** RC4 issuer_name propagation (PRs #18, #22); **ops-01 through ops-12** Batch 5-A doc hygiene (PR #6). Phase 0 findings doc landed for **obs-01** (PR #20) but obs-01-p1 remains OPEN. Parallel execution validated at **2–4 concurrent workers**: ops-batch-5A ∥ sec-01-p0 ∥ obs-03-p0 (PRs #5/6/8) and later obs-01-p0 ∥ int-04-p0 (PRs #20/18) all merged in the same window with zero file overlap vs Appendix D predictions. One minor drift noted: obs-03-p1 touched `scripts/pipeline/shared.py` in addition to the predicted `manifest.py`, but the touched zone (nextval DEFAULT removal) did not overlap with int-21/sec-04 logic — prediction held in substance. Theme-4 admin_bp.py family (sec-01/02/03) was explicitly serialized (not parallelized); ordering held across all five sec-01 sub-PRs and the sec-02 testfix dependency chain. Notable cross-session interaction: sec-02-p1 test harness exposed a DuckDB 1.4.4 ATTACH-adm catalog race that motivated sec-01-p1-attach-fix (PR #21). CHECKLIST flipped, SESSION_LOG updated with one entry per session.
