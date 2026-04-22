# Remediation Program — Checklist

_Flat, grep-friendly. Grouped by theme → batch. See `docs/REMEDIATION_PLAN.md` for full context per item. Session names map to `docs/SESSION_NAMING.md`._

## Theme 1 — Data integrity foundation

### Batch 1-A (parallel-eligible within batch: NO — all items share securities/CUSIP/ticker path)
- [x] int-01 BLOCK-SEC-AUD-1 RC1: OpenFIGI foreign-exchange ticker filter (build_cusip.py, run_openfigi_retry.py) — PRs #13, #15 (data sweep complete; 216 residual = legitimate foreign-only)
- [x] int-04 BLOCK-SEC-AUD-4 RC4: issuer_name propagation scope guard (normalize_securities.py) — PRs #18, #22
- [x] int-05 BLOCK-TICKER-BACKFILL Phase 1a retroactive Pass C sweep (enrich_holdings.py invocation) — PR #46 (closed as NO-OP; retroactive sweep already executed)
- [x] int-10 INF26 OpenFIGI `_update_error()` permanent-pending bug (run_openfigi_retry.py) — PRs #42, #44 (code fix shipped; staging sweep pending `--confirm`)
- [ ] int-23 BLOCK-SEC-AUD-5 universe expansion 132K→430K acceptance (cusip_classifier.py decision)

### Batch 1-B (parallel-eligible within batch: NO)
- [x] int-02 BLOCK-SEC-AUD-2 RC2: MAX(issuer_name_sample) mode aggregator — CODE-COMPLETE in `fc2bbbc` (2026-04-18). Phase 0 (PR #50) confirmed aggregator shipped; 8,178-row re-seed gap accepted under **Option A (no re-seed now)**. Closed 2026-04-21.
- [ ] int-06 BLOCK-TICKER-BACKFILL Phase 1b forward-looking hooks (build_cusip.py end, normalize_securities.py end)

### Batch 1-C (parallel-eligible within batch: NO)
- [ ] int-03 BLOCK-SEC-AUD-3 RC3 ticker_overrides.csv manual triage
- [ ] int-07 BLOCK-TICKER-BACKFILL Phase 2 benchmark_weights gate
- [ ] int-14 INF30 BLOCK-MERGE-UPSERT-MODE NULL-only merge (merge_staging.py, promote_staging.py)
- [ ] int-15 INF31 market_data writer fetch_date discipline (fetch_market.py, refetch_missing_sectors.py)
- [ ] int-21 MAJOR-7 D-04 15.87% unresolved series_id tail (pipeline/shared.py)

### Batch 1-D (parallel-eligible within batch: NO)
- [ ] int-08 BLOCK-TICKER-BACKFILL Phase 2b 227-ticker sector refetch (CONDITIONAL)
- [ ] int-09 INF25 BLOCK-DENORM-RETIREMENT sequencing (DDL + docs)
- [ ] int-12 INF28 securities.cusip formal PK + VALIDATOR_MAP
- [ ] int-17 INF36 top10_* NULL placeholders (summary_by_parent DDL)
- [ ] int-20 MAJOR-6 D-03 orphan-CUSIP secondary driver (build_summaries.py read-path)

### Batch 1-E (parallel-eligible within batch: NO — shared docs)
- [ ] int-11 INF27 CUSIP residual-coverage tracking (doc only)
- [ ] int-13 INF29 OTC grey-market is_priceable refinement
- [ ] int-16 INF35 f-string interpolation cosmetic
- [ ] int-22 MINOR-5 C-06 fix_fund_classification no-CHECKPOINT retrofit

### Standing
- [ ] int-18 INF37 backfill_manager_types residual 9 entities (no closure expected)

### Phase 2
- [ ] int-19 INF38 BLOCK-FLOAT-HISTORY true pct_of_float (deferred)

---

## Theme 2 — Observability + audit trail

### Batch 2-A (parallel-eligible within batch: YES — obs-01 ∥ obs-03, disjoint files)
- [x] obs-01 MAJOR-9 D-07/P-05 N-CEN + ADV into ingestion_manifest (fetch_ncen.py, fetch_adv.py, migrations/001) — PRs #20, #25
- [x] obs-03 MAJOR-13 P-04 market impact_id allocation hardening (pipeline/manifest.py, fetch_market.py) — PRs #8, #12

### Batch 2-B (parallel-eligible within batch: NO — both touch fetch_adv.py / promote_13dg.py)
- [x] obs-02 MAJOR-12 P-02 ADV freshness + log (fetch_adv.py) — PRs #28, #30
- [x] obs-04 MAJOR-8 D-06 13D/G ingestion_impacts grain backfill (pipeline/manifest.py, promote_13dg.py) — PRs #36, #38 (one-off backfill script shipped; data op pending `--confirm`)

### Batch 2-C (parallel-eligible within batch: YES — disjoint files)
- [x] obs-06 MINOR-3 P-01 13F loader freshness (load_13f.py) — closed as already-satisfied; `record_freshness('filings')` + `record_freshness('filings_deduped')` shipped in `8e7d5cb` (`load_13f.py` rewrite) prior to this program window; no PR in conv-04
- [x] obs-07 MINOR-4 P-07 N-PORT report_month future-leakage gate (promote_nport.py) — PRs #51, #53
- [x] obs-10 INF32 quarterly-update Makefile 13F-load step (Makefile) — PR #52 (also pruned retired `update.py` refs)

### Batch 2-D (parallel-eligible within batch: YES — off-code ops + CI disjoint)
- [x] obs-08 MINOR-16 O-05 backup-gap investigation (ops) — explained, no infra gap; MAINTENANCE.md wording fix + retention note; see `docs/findings/obs-08-p1-findings.md`
- [ ] obs-09 MINOR-18 O-10 log-rotation policy (ops + scripts)
- [ ] obs-12 INF33 BLOCK-CI-ACTIONS-NODE20-DEPRECATION (.github/workflows)

### Batch 2-E (parallel-eligible within batch: NO — shared data_layers.md)
- [ ] obs-05 MAJOR-17 DOC-11 data_layers.md coverage headline refresh
- [ ] obs-11 Pass 2 §6.4 flow_intensity_total formula docstring

### Verify
- [ ] obs-13 DIAG-23 Register %FLOAT stale dist bundle — verify served bundle post-ff1ff71

---

## Theme 3 — Migration + schema discipline

### Batch 3-A (parallel-eligible within batch: YES — mig-01 ∥ mig-04 disjoint files)
- [x] mig-01 BLOCK-2 atomic promotes + extract `_mirror_manifest_and_impacts` helper (promote_nport.py, promote_13dg.py, pipeline/manifest.py) — PRs #31, #33
- [x] mig-02 MAJOR-14 fetch_adv.py DROP→CREATE atomic fix (fetch_adv.py) — PRs #35, #37 (also closes fetch_adv portion of mig-13)
- [x] mig-04 MAJOR-16 S-02 schema_versions stamp hole (migrations/add_last_refreshed_at.py) — PRs #26, #29

### Batch 3-B (parallel-eligible within batch: NO — some share migration files)
- [ ] mig-03 MAJOR-15 migration 004 staging/rename pattern retrofit (migrations/004)
- [ ] mig-13 pipeline-violations REWRITE tail — residual scope: build_entities, merge_staging (fetch_adv closed via mig-02 PR #37; build_fund_classes + build_benchmark_weights closed via sec-05 PR #45)
- [ ] mig-14 REWRITE_BUILD_MANAGERS INF1 routing + --dry-run + data_freshness (build_managers.py, db.py, promote_staging.py)

### Batch 3-C (parallel-eligible within batch: YES — mig-06 ∥ mig-09 ∥ mig-10 disjoint)
- [ ] mig-06 INF40 L3 surrogate row-ID for rollback
- [ ] mig-09 INF45 schema-parity L4 extension (validate_schema_parity.py, accept.yaml)
- [ ] mig-10 INF46 schema-parity L0 extension (validate_schema_parity.py, accept.yaml)

### Batch 3-D (parallel-eligible within batch: NO — share CI/wiring files)
- [ ] mig-07 INF41 read-site inventory discipline (new scripted audit tool)
- [ ] mig-08 INF42 derived-artifact hygiene (.gitignore, fixture + dist rebuild enforcement)
- [ ] mig-11 INF47 schema-parity CI wiring (.github/workflows/smoke.yml)

### Phase 2 / BLOCKED
- [ ] mig-05 BLOCK-4 admin refresh pre-restart rework (BLOCKED — upstream design doc missing)

### Phase 3
- [ ] mig-12 load_13f_v2 rewrite (fetch_13f.py + promote_13f.py + build_managers reader)

---

## Theme 4 — Security hardening

### Batch 4-A (parallel-eligible within batch: NO — both touch admin_bp.py)
- [x] sec-01 MAJOR-11 D-11 admin token localStorage → server-side session (admin.html, admin_bp.py) — PRs #5, #7, #9, #10, #21
- [x] sec-02 MAJOR-10 C-11 admin `/run_script` TOCTOU race (admin_bp.py) — PRs #11, #14, #19

### Batch 4-B (parallel-eligible within batch: NO — sec-04 shares pipeline/shared.py with Theme 1)
- [x] sec-03 MAJOR-5 C-09 admin endpoint write-surface audit (admin_bp.py) — PRs #16, #17
- [x] sec-04 MAJOR-1 C-02 validators writing to prod (validate_nport_subset.py, pipeline/shared.py) — PRs #24, #27

### Batch 4-C (parallel-eligible within batch: NO — sec-05 overlaps mig-14; sec-06 touches many scripts)
- [x] sec-05 MAJOR-2 C-04 hardcoded-prod builders bypass staging (build_fund_classes.py, build_benchmark_weights.py) — PRs #43, #45 (build_managers.py confirmed already staged; fund_classes + benchmark_weights --staging path fixed)
- [x] sec-06 MAJOR-3 C-05 5 direct-to-prod writers inventory (resolve_*, backfill_manager_types, enrich_tickers + pipeline_violations.md) — PRs #47, #48 (3 resolvers retired to scripts/retired/; backfill_manager_types + enrich_tickers hardened)

### Batch 4-D (parallel-eligible within batch: YES — sec-07 ∥ sec-08 disjoint)
- [x] sec-07 MINOR-15 O-02 pin edgartools + pdfplumber (requirements.txt) — PR #39
- [x] sec-08 MINOR-17 O-08 central EDGAR identity config (new config.py, 22+ scripts) — PRs #40, #41 (21 scripts normalized)

### Tracked elsewhere
- [x] sec-09 Pass 2 §7.3 fetch_adv.py DROP-before-CREATE — scheduled as **mig-02** (Theme 3)

---

## Theme 5 — Operational surface

### Batch 5-A (parallel-eligible within batch: SELECTIVE — ops-01 ∥ ops-05 ∥ ops-07 ∥ ops-04 disjoint; ops-10 ∥ ops-11 serial on ROADMAP.md)
- [x] ops-01 MINOR-6 DOC-01 README retired update.py references (README.md) — PR #6
- [x] ops-02 MINOR-7 DOC-02 README project tree refresh (README.md — serial with ops-01) — PR #6
- [x] ops-03 MINOR-8 DOC-03 PHASE3_PROMPT retired fetch_nport (PHASE3_PROMPT.md) — PR #6
- [x] ops-04 MINOR-9 DOC-04 ARCH_REVIEW vs REACT_MIGRATION Phase 4 contradiction (ARCHITECTURE_REVIEW.md, REACT_MIGRATION.md) — PR #6
- [x] ops-05 MINOR-10 DOC-05 README_deploy React build prereq (README_deploy.md) — PR #6
- [x] ops-07 MINOR-12 DOC-09 CLASSIFICATION_METHODOLOGY entity count (CLASSIFICATION_METHODOLOGY.md) — PR #6
- [x] ops-08 MINOR-13 DOC-10 PHASE1/3/4 prompts housekeeping — PR #6
- [x] ops-10 MINOR-1 R-01 ROADMAP 13DG exclusion count 928 vs 931 (ROADMAP.md) — PR #6
- [x] ops-11 MINOR-2 R-02 ROADMAP NULL-CIK count 4 vs 5 (ROADMAP.md — serial with ops-10) — PR #6
- [x] ops-12 Pass 2 §8.2 migration 007 NULL-target doc note — PR #6

### Batch 5-B (parallel-eligible within batch: YES — disjoint)
- [x] ops-06 MINOR-11 DOC-06 write_path_risk_map stale — PR #32
- [x] ops-09 MINOR-14 DOC-12 api_*.py Blueprint split architecture doc (new docs/) — PR #32
- [x] ops-15 DOC_UPDATE_PROPOSAL item 7 — MAINTENANCE.md §Refetch Pattern (MAINTENANCE.md) — PR #32

### Batch 5-C (parallel-eligible within batch: NO — shared data_layers.md + ROADMAP.md)
- [ ] ops-13 DOC_UPDATE_PROPOSAL item 1 — denorm drift doc (data_layers.md §7, ENTITY_ARCHITECTURE.md)
- [ ] ops-14 DOC_UPDATE_PROPOSAL items 2-5 INF26-29 ROADMAP rows + notes

### Batch 5-D
- [ ] ops-16 DOC_UPDATE_PROPOSAL item 6 — admin_bp.py:108 revisit flag (placement decision first)

### Phase 2 / BLOCKED
- [ ] ops-17 PRECHECK tertiary — retire or repair scripts/update.py (Phase 2)
- [ ] ops-18 Restore missing rotating_audit_schedule.md (BLOCKED — doc not found)
