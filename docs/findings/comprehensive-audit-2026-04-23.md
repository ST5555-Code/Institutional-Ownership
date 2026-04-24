# Comprehensive Audit — 2026-04-23

**Session:** `comprehensive-audit` · **Branch:** `comprehensive-audit` · **Base:** `main @ aab73d2` · **Mode:** Investigation + report, read-only across repo, DB, trackers · **Scope:** Single-doc deliverable; no code changes, no tracker edits, no file moves.

**Purpose.** Ground-truth baseline of project state across four dimensions (documentation, filesystem/scripts, prod DB, trackers) to feed Phase B (filesystem reorg) and Phase C (doc consolidation). This session reads; it does not fix.

**Top-line counts (see §9 for detail).**
- 138 docs · 162 scripts (18 retired) · 57 DB tables + 2 views + 292 snapshot tables · 14 open tracker items.
- 5 tracker drift candidates (3 mechanical flips + 2 ticket-number reuse violations).
- 15 DB tables flagged orphan (incl. 13.6M-row `raw_*` trio); 1 writer-retired table (`fund_holdings`) contradicting two reference docs.
- 20 schema-doc divergences (canonical_ddl.md, data_layers.md, pipeline_inventory.md).
- 0 archive candidates this cycle (earliest archive window ≈ 2026-05-20).

**Top 5 highest-impact findings.**
1. **raw_* orphan trio** (13,540,608 + 43,358 + 43,358 rows written by legacy `scripts/load_13f.py`, zero readers) — 13.6M rows of potentially dead data. §3.b, §7.c, §8.Q2.
2. **REMEDIATION_CHECKLIST drift** — 3 stale `[ ]` checkboxes at L39 (int-18/INF37), L98 (mig-05), L101 (mig-12), all for items closed elsewhere. §4, §7.d.
3. **`fund_holdings` tri-way inconsistency** — table present with 22,030 rows and last write 2026-04-14, but `canonical_ddl.md:144,153` and `data_layers.md:141` both claim it was dropped. §6.a, §6.b, §8.Q1.
4. **Pass 2's 77 "retire candidates" count is inflated** — 48 are false positives (migrations, one-offs, CLI-only tools, dotted-path imports including `audit_ticket_numbers.py` / `audit_tracker_staleness.py` which ran in this very session). Real candidate count ≈ 10–25. §7.b, §8.Q9.
5. **INF40 / DM3 / DM6 ticket-number reuse** — three violations of PR #131 retire-forever hygiene rule. INF40 reused across two unrelated closures; DM3 and DM6 have duplicate headings inside `docs/findings/dm-open-surface-2026-04-22.md`. §4.b, §8.Q5.

**Status:** findings only. No actions taken. Phase B and Phase C sessions will act on §7 + §8.

---

# §1 Documentation Inventory
**Total markdown files:** 138
**Archive candidates:** 0

## §1.1 All Documentation Files

| Path | Lines | Last Modified | Last Commit | Category | Purpose | Refs IN |
|------|-------|---------------|-------------|----------|---------|----------|
| `ARCHITECTURE_REVIEW.md` | 767 | 2026-04-22 | ee0755a phase2-prep: refresh all docs for Phase 2 readines | architecture | 13F Institutional Ownership — Architecture & Upgrade Plan | 20 |
| `ENTITY_ARCHITECTURE.md` | 561 | 2026-04-22 | 25a0263 int-09 + ops-13 + ops-14: formalize DENORM-RETIREM | architecture | Entity Master Data Management (MDM) Architecture | 21 |
| `MAINTENANCE.md` | 336 | 2026-04-23 | c2e6efd doc-hygiene-w1: clear 10 stale sections across 5 d | tracker | 13F Ownership Database — Maintenance Guide | 16 |
| `PHASE3_PROMPT.md` | 92 | 2026-04-20 | 0bfa7fd remediation/ops-batch-5A-p0: doc hygiene sweep | prompt | Next Session Prompt — 13F Ownership | 8 |
| `PHASE4_PROMPT.md` | 332 | 2026-04-20 | 0bfa7fd remediation/ops-batch-5A-p0: doc hygiene sweep | prompt | > **STATUS: SUPERSEDED — retained for history only (2026-04-20).** | 6 |
| `PHASE4_STATE.md` | 134 | 2026-04-10 | 950ec7e Add staging workflow framework: sync, diff, promot | prompt | Phase 4 State — Facts Only | 3 |
| `archive/docs/REACT_MIGRATION.md` | 151 | 2026-04-13 | 71269cb feat: retire vanilla-JS frontend — web/react-src/, | unknown | React Migration Plan | 14 |
| `README.md` | 201 | 2026-04-20 | 0bfa7fd remediation/ops-batch-5A-p0: doc hygiene sweep | tracker | 13-F Institutional Ownership Database | 13 |
| `docs/deployment.md` | 81 | 2026-04-20 | 0bfa7fd remediation/ops-batch-5A-p0: doc hygiene sweep | tracker | Deploying 13F Ownership Research to Render.com | 13 |
| `ROADMAP.md` | 1166 | 2026-04-23 | aab73d2 hygiene-ticket-numbering: codify retire-forever ru | plan | 13F Institutional Ownership Database — Roadmap | 33 |
| `data/reference/PRE_PHASE4_STATUS.md` | 106 | 2026-04-09 | ee5e7cb Pre-Phase 4 complete: Items 2-9 done, all validati | prompt | Pre-Phase 4 Item Status | 1 |
| `data/reference/ROLLUP_COVERAGE_REPORT.md` | 148 | 2026-04-08 | 9d34d34 Update ROADMAP + ROLLUP_COVERAGE_REPORT with final | unknown | Entity Rollup Coverage Report | 0 |
| `docs/findings/2026-04-16-13dg-entity-linkage.md` | 183 | 2026-04-16 | f40ffa2 docs: 13D/G entity linkage — new 13DG_ENTITY_LINKA | unknown | 13D/G Entity Linkage | 4 |
| `docs/findings/2026-04-19-block-market-data-writer-audit.md` | 166 | 2026-04-19 | eb9cf2d docs(audit): market_data writer audit — phase 0 fi | findings | BLOCK-MARKET-DATA-WRITER-AUDIT — Phase 0 Findings | 3 |
| `docs/findings/2026-04-19-block-schema-diff.md` | 905 | 2026-04-19 | 4ec0862 schema-diff Phase 1c: restore entity_identifiers_s | findings | BLOCK-STAGING-PROD-SCHEMA-DIVERGENCE (INF39) — Phase 0 Findings | 9 |
| `docs/findings/2026-04-18-block-securities-data-audit.md` | 467 | 2026-04-18 | f583524 docs(block-securities-data-audit): addendum — 430K | findings | BLOCK-SECURITIES-DATA-AUDIT — Phase 0 Findings | 11 |
| `docs/findings/2026-04-18-block-ticker-backfill.md` | 358 | 2026-04-18 | 168927e docs(block-ticker-backfill): addendum — cusip step | findings | BLOCK-TICKER-BACKFILL — Findings & Fix Plan | 7 |
| `docs/findings/2026-04-19-ci-smoke-failure-diagnosis.md` | 124 | 2026-04-19 | 74df368 docs(ci): smoke workflow failure diagnosis — snaps | unknown | CI smoke workflow failure — diagnosis (2026-04-19) | 1 |
| `docs/CLASSIFICATION_METHODOLOGY.md` | 59 | 2026-04-20 | 0bfa7fd remediation/ops-batch-5A-p0: doc hygiene sweep | unknown | Data Classification Methodology | 9 |
| `docs/findings/2026-04-17-codex-review.md` | 201 | 2026-04-17 | 838a1b3 docs: system audit 2026-04-17 — atlas + codex revi | unknown | Codex Review — 2026-04-17 | 9 |
| `docs/DEFERRED_FOLLOWUPS.md` | 82 | 2026-04-23 | 12af4be int-23-impl: downgrade-refusal invariant on _promo | unknown | Deferred Followups — Tracking Index | 13 |
| `docs/NEXT_SESSION_CONTEXT.md` | 261 | 2026-04-23 | f3c7183 inf40-fix: preserve constraints in sync_staging.py | session-guide | 13F Ownership — Next Session Context | 17 |
| `docs/POST_MERGE_REGRESSIONS_DIAGNOSTIC.md` | 250 | 2026-04-19 | 08f9a32 diag/post-merge-regressions: three-issue diagnosti | unknown | Post-merge regressions — diagnostic findings | 0 |
| `docs/findings/2026-04-19-precheck-load-13f-liveness.md` | 140 | 2026-04-19 | cdf2cae docs(precheck): load_13f.py liveness audit — LIVE | unknown | Precheck2 — `load_13f.py` liveness audit | 4 |
| `docs/PROCESS_RULES.md` | 124 | 2026-04-09 | ee5e7cb Pre-Phase 4 complete: Items 2-9 done, all validati | tracker | Process Rules — Large-Data Scripts | 13 |
| `docs/REMEDIATION_CHECKLIST.md` | 156 | 2026-04-22 | 7c49471 conv-11: REMEDIATION PROGRAM COMPLETE — 104 PRs, ~ | tracker | Remediation Program — Checklist | 50 |
| `docs/REMEDIATION_PLAN.md` | 614 | 2026-04-23 | fec20d4 hygiene-file-leak-fix: mitigate file-leak-to-main  | plan | Remediation Program — Master Plan | 69 |
| `docs/REMEDIATION_SESSION_LOG.md` | 1845 | 2026-04-22 | 7c49471 conv-11: REMEDIATION PROGRAM COMPLETE — 104 PRs, ~ | session-guide | Remediation Program — Session Log | 1 |
| `docs/REVIEW_CHECKLIST.md` | 139 | 2026-04-23 | aab73d2 hygiene-ticket-numbering: codify retire-forever ru | tracker | PR Review Checklist | 4 |
| `docs/findings/2026-04-19-rewrite-build-managers.md` | 541 | 2026-04-19 | bf7bfe6 docs(rewrite): build_managers — phase 0 findings a | findings | REWRITE build_managers.py — Phase 0 Findings | 6 |
| `docs/findings/2026-04-19-rewrite-build-shares-history.md` | 636 | 2026-04-19 | 42f5d6e doc-sync: 2026-04-19-rewrite-build-shares-history.md | findings | REWRITE build_shares_history.py — Phase 0 Findings | 3 |
| `docs/findings/2026-04-19-rewrite-build-summaries.md` | 330 | 2026-04-19 | 6a88816 docs(rewrite): build_summaries — phase 0 findings  | findings | REWRITE build_summaries.py — Phase 0 Findings | 2 |
| `docs/findings/2026-04-19-rewrite-load-13f.md` | 554 | 2026-04-19 | 0a7ae35 docs(rewrite): load_13f phase 0 addendum — other_m | findings | REWRITE load_13f.py — Phase 0 Findings | 4 |
| `docs/findings/2026-04-19-rewrite-pct-of-so-period-accuracy.md` | 2210 | 2026-04-19 | dc2e670 schema-diff Phase 1: Phase 2 pre-flight wrapper +  | findings | BLOCK-PCT-OF-FLOAT-PERIOD-ACCURACY — Phase 0 Findings | 6 |
| `docs/SCHEMA_DIFF_PHASE_1_REBUILD_LOG.md` | 444 | 2026-04-19 | 4aea6d1 schema-diff Phase 1: post-rebuild verification — b | prompt | INF39 Phase 1 — Staging Rebuild Execution Log | 3 |
| `docs/SESSION_GUIDELINES.md` | 135 | 2026-04-23 | 28d588f hygiene-tracker-sync: codify cross-tracker update  | session-guide | Session Guidelines — Worktree Hygiene | 2 |
| `docs/SESSION_NAMING.md` | 99 | 2026-04-23 | de5b3fd hygiene-roadmap-conflict-fix: per-session closure  | session-guide | Session Naming Convention | 3 |
| `docs/SYSTEM_ATLAS_2026_04_17.md` | 675 | 2026-04-17 | 838a1b3 docs: system audit 2026-04-17 — atlas + codex revi | unknown | System Atlas — 2026-04-17 | 8 |
| `docs/SYSTEM_AUDIT_2026_04_17.md` | 413 | 2026-04-17 | 838a1b3 docs: system audit 2026-04-17 — atlas + codex revi | unknown | System Audit — 2026-04-17 | 17 |
| `docs/SYSTEM_PASS2_2026_04_17.md` | 398 | 2026-04-17 | 838a1b3 docs: system audit 2026-04-17 — atlas + codex revi | unknown | System Pass 2 — 2026-04-17 | 4 |
| `docs/admin_refresh_system_design.md` | 990 | 2026-04-22 | 4d9ee08 p2fu-04: document ADV ownership boundary + close P | unknown | Admin Refresh System — Design Document | 15 |
| `docs/api_architecture.md` | 150 | 2026-04-21 | 1a47a0e remediation/ops-batch-5B: write_path_risk_map + ap | architecture | API Architecture | 6 |
| `docs/canonical_ddl.md` | 485 | 2026-04-22 | 60d4c30 mig-06: migration 014 — surrogate row_id on v2 fac | unknown | Canonical DDL Audit — L3 Drift Report | 20 |
| `docs/ci_fixture_design.md` | 210 | 2026-04-13 | 7f62b7d docs: Phase 0-B1 — CI fixture DB design decision | unknown | CI Fixture DB Design (Phase 0-B1) | 6 |
| `archive/docs/closed/DOC_UPDATE_PROPOSAL_20260418_RESOLVED.md` | 551 | 2026-04-23 | c2e6efd doc-hygiene-w1: clear 10 stale sections across 5 d | closure | Doc Update Proposal — 2026-04-18 — **RESOLVED** | 0 |
| `docs/closures/README.md` | 65 | 2026-04-23 | de5b3fd hygiene-roadmap-conflict-fix: per-session closure  | closure | Per-session closure entries | 14 |
| `docs/data_layers.md` | 963 | 2026-04-22 | 4d9ee08 p2fu-04: document ADV ownership boundary + close P | unknown | Data Layers — Table Classification | 27 |
| `docs/data_sources.md` | 204 | 2026-04-23 | c2e6efd doc-hygiene-w1: clear 10 stale sections across 5 d | unknown | Data Sources | 7 |
| `docs/endpoint_classification.md` | 75 | 2026-04-13 | 746a798 feat: Phase 4 Batch 4-A — Blueprint split of scrip | unknown | API Endpoint Classification | 8 |
| `docs/findings/dm-open-surface-2026-04-22.md` | 182 | 2026-04-23 | 3f28d64 dm-scoping: DM worldview open surface audit for Ti | findings | DM Worldview Open Surface — 2026-04-22 | 0 |
| `docs/findings/entity-curation-w1-log.md` | 197 | 2026-04-23 | 6c14c35 entity-curation-w1: close INF37 + int-21 SELF-fall | findings | entity-curation-w1 — session log | 2 |
| `docs/findings/inf9-closure.md` | 161 | 2026-04-23 | 579c9a3 inf9f-agincourt: close INF9f Agincourt CRD-only re | findings | INF9 closure — 2026-04-10 Route A overrides persistence | 2 |
| `docs/findings/int-01-p0-findings.md` | 282 | 2026-04-21 | 82a39e5 remediation/int-01-p0: Phase 0 findings — RC1 Open | findings | int-01-p0 — Phase 0 findings: RC1 OpenFIGI foreign-exchange ticker filter | 6 |
| `docs/findings/int-02-p0-findings.md` | 151 | 2026-04-21 | 269fec5 int-02-p0: RC2 mode aggregator already shipped — P | findings | int-02-p0 Phase 0 Findings — BLOCK-SEC-AUD-2 RC2: MAX(issuer_name_sample) → MODE | 1 |
| `docs/findings/int-04-p0-findings.md` | 242 | 2026-04-21 | 88406d4 remediation/int-04-p0: Phase 0 findings — RC4 issu | findings | int-04-p0 — Phase 0 findings: RC4 issuer_name propagation scope guard | 5 |
| `docs/findings/int-05-p0-findings.md` | 233 | 2026-04-21 | 98dc28e int-05-p0: retroactive Pass C sweep already comple | findings | int-05-p0 Phase 0 Findings — BLOCK-TICKER-BACKFILL retroactive Pass C sweep | 3 |
| `docs/findings/int-06-p0-findings.md` | 202 | 2026-04-22 | 50de780 int-06-p0: forward-looking hooks already shipped — | findings | int-06-p0 Phase 0 Findings — BLOCK-TICKER-BACKFILL Phase 1b forward-looking hook | 2 |
| `docs/findings/int-07-p0-findings.md` | 168 | 2026-04-22 | f5a0cd3 int-07-p0: benchmark_weights gate PASSES — finding | findings | int-07-p0 Phase 0 Findings — BLOCK-TICKER-BACKFILL Phase 2 benchmark_weights gat | 1 |
| `docs/findings/int-09-p0-findings.md` | 110 | 2026-04-22 | f2dfe2f int-09-p0: INF25 Step 4 defer to Phase 2 — Phase 0 | findings | int-09-p0 Phase 0 Findings — INF25 BLOCK-DENORM-RETIREMENT sequencing | 9 |
| `docs/findings/int-10-p0-findings.md` | 204 | 2026-04-21 | 4072d9e int-10-p0: Phase 0 findings — INF26 _update_error( | findings | int-10-p0 — Phase 0 findings: INF26 OpenFIGI `_update_error()` permanent-pending | 2 |
| `docs/findings/int-12-p0-findings.md` | 198 | 2026-04-22 | 36ac7ff int-12-p0: Phase 0 findings — INF28 securities.cus | findings | int-12 Phase 0 findings — INF28: formal PK on `securities.cusip` + validator cov | 3 |
| `docs/findings/int-13-p0-findings.md` | 249 | 2026-04-22 | 11b65ec int-13-p0: Phase 0 findings — INF29 OTC grey-marke | findings | int-13 — INF29 OTC grey-market `is_otc` classifier — Phase 0 findings | 2 |
| `docs/findings/int-14-p0-findings.md` | 282 | 2026-04-22 | 789a0f8 int-14-p0: Phase 0 findings — INF30 NULL-only merg | findings | int-14-p0 — Phase 0 findings: INF30 BLOCK-MERGE-UPSERT-MODE NULL-only merge | 0 |
| `docs/findings/int-15-p0-findings.md` | 173 | 2026-04-22 | 8357793 int-15-p0: Phase 0 findings — INF31 market_data wr | findings | int-15 — INF31 `market_data` writer `fetch_date` discipline — Phase 0 findings | 1 |
| `docs/findings/int-20-p0-findings.md` | 264 | 2026-04-22 | 828d323 int-20-p0: Phase 0 findings — MAJOR-6 D-03 orphan- | findings | int-20-p0 — Phase 0 findings: MAJOR-6 D-03 orphan-CUSIP secondary driver in buil | 1 |
| `docs/findings/int-22-p0-findings.md` | 254 | 2026-04-22 | 2f3fed5 int-22: prod is_latest inversion — rollback wrappe | findings | int-22 Phase 0 Findings — prod `is_latest` inversion | 1 |
| `docs/findings/int-23-design.md` | 285 | 2026-04-23 | 05ac372 int-23-design: loader idempotency fix — Option (a) | findings | int-23 Design — Loader Idempotency Fix | 4 |
| `docs/findings/int-23-p0-findings.md` | 138 | 2026-04-22 | 568b6dd int-23-p0: Phase 0 findings — BLOCK-SEC-AUD-5 univ | findings | int-23-p0 — Phase 0 findings: BLOCK-SEC-AUD-5 universe expansion 132K → 430K | 2 |
| `docs/findings/mig-01-p0-findings.md` | 233 | 2026-04-21 | dd03780 remediation/mig-01-p0: Phase 0 findings — atomic p | findings | mig-01-p0 — Phase 0 findings: atomic promotes + manifest mirror helper | 3 |
| `docs/findings/mig-02-p0-findings.md` | 335 | 2026-04-21 | 9b48635 remediation/mig-02-p0: Phase 0 findings for fetch_ | findings | mig-02-p0 — Phase 0 findings: fetch_adv.py staging → promote_adv.py conversion | 3 |
| `docs/findings/mig-03-p0-findings.md` | 303 | 2026-04-21 | 94de1c4 mig-03-p0: Phase 0 findings on migration 004 atomi | findings | mig-03-p0 — Phase 0 findings: migration 004 RENAME→CREATE→INSERT→DROP atomicity | 1 |
| `docs/findings/mig-04-p0-findings.md` | 195 | 2026-04-21 | 5997345 remediation/mig-04-p0: Phase 0 findings — schema_v | findings | mig-04-p0 — Phase 0 findings: schema_versions stamp hole | 5 |
| `docs/findings/mig-06-p0-findings.md` | 314 | 2026-04-22 | b9f3a2a mig-06-p0: Phase 0 findings — INF40 L3 surrogate r | findings | mig-06-p0 — Phase 0 findings: INF40 L3 surrogate row-ID for rollback | 1 |
| `docs/findings/mig-08-p0-findings.md` | 216 | 2026-04-22 | 3d840af mig-08-p0: Phase 0 findings — INF42 derived-artifa | findings | mig-08-p0 — Phase 0 findings: INF42 derived-artifact hygiene | 1 |
| `docs/findings/mig-09-p0-findings.md` | 192 | 2026-04-22 | f79d437 mig-09-p0: Phase 0 findings — INF45 L4 schema-pari | findings | mig-09-p0 — Phase 0 findings: INF45 schema-parity L4 extension | 2 |
| `docs/findings/mig-11-p0-findings.md` | 214 | 2026-04-22 | 72780f4 mig-11-p0: Phase 0 findings — INF47 schema-parity  | findings | mig-11-p0 — Phase 0 findings: INF47 schema-parity CI wiring | 1 |
| `docs/findings/mig-13-p0-findings.md` | 152 | 2026-04-21 | 2c779df mig-13-p0: pipeline-violations REWRITE tail — scop | findings | mig-13-p0 — Phase 0 findings: pipeline-violations REWRITE tail (scope verificati | 1 |
| `docs/findings/mig-14-p0-findings.md` | 131 | 2026-04-22 | 0b97247 mig-14-p0: Phase 0 findings — REWRITE_BUILD_MANAGE | findings | mig-14-p0 — Phase 0 findings: REWRITE_BUILD_MANAGERS remaining scope verificatio | 2 |
| `docs/findings/obs-01-p0-findings.md` | 208 | 2026-04-21 | 9eb230d docs(obs-01): Phase 0 findings — N-CEN + ADV manif | findings | obs-01-p0 — Phase 0 findings: N-CEN + ADV manifest registration | 3 |
| `docs/findings/obs-02-p0-findings.md` | 144 | 2026-04-21 | c8320e1 remediation/obs-02-p0: Phase 0 findings — ADV fres | findings | obs-02-p0 — Phase 0 findings: ADV freshness + log discipline | 4 |
| `docs/findings/obs-03-p0-findings.md` | 219 | 2026-04-20 | 57f04ff remediation/obs-03-p0: Phase 0 findings — market i | findings | obs-03-p0 — Phase 0 findings: market `impact_id` allocation hardening | 7 |
| `docs/findings/obs-04-p0-findings.md` | 375 | 2026-04-21 | cb91ef2 obs-04-p0: 13D/G ingestion_impacts backfill — Phas | findings | obs-04-p0 — Phase 0 findings: 13D/G `ingestion_impacts` backfill | 2 |
| `docs/findings/obs-07-p0-findings.md` | 229 | 2026-04-21 | cfd3515 obs-07-p0: N-PORT report_month future-leakage gate | findings | obs-07-p0 — Phase 0 findings: N-PORT `report_month` future-leakage gate | 1 |
| `docs/findings/obs-08-p1-findings.md` | 239 | 2026-04-21 | c3590d0 obs-08: document backup state + wire backup-db tar | findings | obs-08-p1 — MINOR-16 O-05 backup-gap investigation | 5 |
| `docs/findings/obs-13-verify-findings.md` | 91 | 2026-04-21 | 0edb9b8 obs-13: verify dist bundle post-ff1ff71 (#65) | findings | obs-13: DIAG-23 Register %FLOAT Dist Bundle Verification | 2 |
| `docs/findings/ops-17-p1-findings.md` | 24 | 2026-04-21 | a06729e ops-17: verify/close update.py retired-script refe | findings | ops-17-p1 Findings — update.py retired-script references | 0 |
| `docs/findings/ops-batch-5A-p0-findings.md` | 261 | 2026-04-20 | 0bfa7fd remediation/ops-batch-5A-p0: doc hygiene sweep | findings | ops-batch-5A-p0 — Findings | 2 |
| `docs/findings/ops-batch-5B-findings.md` | 108 | 2026-04-21 | 1a47a0e remediation/ops-batch-5B: write_path_risk_map + ap | findings | ops-batch-5B — Findings (doc-only batch) | 2 |
| `docs/findings/phantom-other-managers-decision.md` | 205 | 2026-04-23 | 5e0078c phantom-other-managers-decision: resolve REWRITE_L | findings | Phantom `other_managers` table — decision | 1 |
| `docs/findings/sec-01-p0-findings.md` | 390 | 2026-04-20 | 6a98153 remediation/sec-01-p0: Phase 0 findings — admin to | findings | sec-01-p0 — Phase 0 findings: admin token `localStorage` → server-side session | 7 |
| `docs/findings/sec-02-p0-findings.md` | 251 | 2026-04-20 | a72e1ab remediation/sec-02-p0: Phase 0 findings — admin ru | findings | sec-02-p0 — Phase 0 findings: admin `/run_script` TOCTOU race | 6 |
| `docs/findings/sec-03-p0-findings.md` | 272 | 2026-04-21 | 0aa442d remediation/sec-03-p0: Phase 0 findings — admin en | findings | sec-03-p0 — Phase 0 findings: admin endpoint write-surface audit | 6 |
| `docs/findings/sec-04-p0-findings.md` | 176 | 2026-04-21 | 88341fb remediation/sec-04-p0: Phase 0 findings — validato | findings | sec-04-p0 — Phase 0 findings: validators writing to prod | 3 |
| `docs/findings/sec-05-p0-findings.md` | 199 | 2026-04-21 | 8951117 sec-05-p0: hardcoded-prod builders bypass staging  | findings | sec-05-p0 — Phase 0 findings: hardcoded-prod builders bypass staging | 8 |
| `docs/findings/sec-06-p0-findings.md` | 326 | 2026-04-21 | 507f30c sec-06-p0: 5 direct-to-prod writers inventory — Ph | findings | sec-06-p0 — Phase 0 findings: 5 direct-to-prod writers missing inventory | 2 |
| `docs/findings/sec-08-p0-findings.md` | 256 | 2026-04-21 | 47266ad sec-08-p0: central EDGAR identity config — Phase 0 | findings | sec-08-p0 — Phase 0 findings: central EDGAR identity config | 1 |
| `docs/pipeline_inventory.md` | 234 | 2026-04-23 | 94e3350 build-fund-classes-rewrite: retrofit §1/§5/§9 + fu | unknown | Pipeline Inventory — DB-Writing Script Audit | 17 |
| `docs/pipeline_violations.md` | 625 | 2026-04-23 | 94e3350 build-fund-classes-rewrite: retrofit §1/§5/§9 + fu | unknown | Pipeline Violations — Per-Script PROCESS_RULES Detail | 21 |
| `archive/docs/plans/20260412_architecture_review_revision.md` | 262 | 2026-04-12 | 657c885 docs: ARCHITECTURE_REVIEW.md — revision pass after | architecture | ARCHITECTURE_REVIEW.md — revision pass | 1 |
| `archive/docs/prompts/int-01-p0.md` | 64 | 2026-04-20 | 1da7527 prog-00: remediation program consolidation — maste | unknown | int-01-p0 — Phase 0 investigation: RC1 OpenFIGI foreign-exchange ticker filter | 1 |
| `archive/docs/prompts/int-01-p1.md` | 171 | 2026-04-21 | f0d5a8c docs(int-01): add Phase 1 implementation prompt fo | unknown | int-01-p1 — Phase 1 implementation: RC1 whitelist patch + residual CUSIP re-queu | 0 |
| `archive/docs/prompts/int-04-p0.md` | 70 | 2026-04-21 | 8a7afb2 docs(int-04): add Phase 0 investigation prompt for | unknown | int-04-p0 — Phase 0 investigation: RC4 issuer_name propagation scope guard | 0 |
| `archive/docs/prompts/int-04-p1.md` | 57 | 2026-04-21 | 271d63e docs(int-04): add Phase 1 implementation prompt fo | unknown | int-04-p1 — Phase 1 implementation: RC4 issuer_name propagation in build_cusip.p | 1 |
| `archive/docs/prompts/mig-01-p0.md` | 69 | 2026-04-21 | 9878a3a docs(mig-01): add Phase 0 investigation prompt for | unknown | mig-01-p0 — Phase 0 investigation: atomic promotes + manifest mirror helper | 0 |
| `archive/docs/prompts/mig-01-p1.md` | 96 | 2026-04-21 | 60c8713 docs(mig-01): add Phase 1 implementation prompt fo | unknown | mig-01-p1 — Phase 1 implementation: atomic promotes + manifest mirror extraction | 1 |
| `archive/docs/prompts/mig-04-p0.md` | 62 | 2026-04-21 | 79aba16 docs(mig-04): add Phase 0 investigation prompt for | unknown | mig-04-p0 — Phase 0 investigation: schema_versions stamp hole | 1 |
| `archive/docs/prompts/mig-04-p1.md` | 78 | 2026-04-21 | dc14194 docs(mig-04): add Phase 1 implementation prompt fo | unknown | mig-04-p1 — Phase 1 implementation: schema_versions stamp backfill | 0 |
| `archive/docs/prompts/obs-01-p0.md` | 79 | 2026-04-21 | 9812ef5 docs(obs-01): add Phase 0 investigation prompt for | unknown | obs-01-p0 — Phase 0 investigation: N-CEN + ADV manifest registration | 0 |
| `archive/docs/prompts/obs-01-p1.md` | 99 | 2026-04-21 | 1b2e7ac docs(obs-01): add Phase 1 implementation prompt fo | unknown | obs-01-p1 — Phase 1 implementation: N-CEN + ADV manifest registration | 1 |
| `archive/docs/prompts/obs-02-p0.md` | 54 | 2026-04-21 | 9712a0e docs(obs-02): add Phase 0 investigation prompt for | unknown | obs-02-p0 — Phase 0 investigation: ADV freshness + log discipline | 0 |
| `archive/docs/prompts/obs-02-p1.md` | 52 | 2026-04-21 | 8de6085 docs(obs-02): add Phase 1 implementation prompt fo | unknown | obs-02-p1 — Phase 1 implementation: ADV freshness + code smell fixes | 0 |
| `archive/docs/prompts/obs-03-p0.md` | 60 | 2026-04-20 | 1da7527 prog-00: remediation program consolidation — maste | unknown | obs-03-p0 — Phase 0 investigation: market `impact_id` allocation hardening | 1 |
| `archive/docs/prompts/obs-03-p1.md` | 152 | 2026-04-20 | 7004bbc docs(obs-03): add Phase 1 implementation prompt wi | unknown | obs-03-p1 — Phase 1 implementation: centralized impact_id allocator | 2 |
| `archive/docs/prompts/ops-batch-5A-p0.md` | 90 | 2026-04-20 | 1da7527 prog-00: remediation program consolidation — maste | unknown | ops-batch-5A-p0 — Phase 0 investigation: doc-hygiene sweep (Batch 5-A subset) | 1 |
| `archive/docs/prompts/ops-batch-5B.md` | 72 | 2026-04-21 | 2893f21 docs(ops): add Batch 5-B prompt for doc updates | unknown | ops-batch-5B — Batch 5-B doc updates: write_path_risk_map + api_architecture + M | 1 |
| `archive/docs/prompts/sec-01-p0.md` | 63 | 2026-04-20 | 1da7527 prog-00: remediation program consolidation — maste | unknown | sec-01-p0 — Phase 0 investigation: admin token localStorage → server-side sessio | 2 |
| `archive/docs/prompts/sec-01-p1.md` | 152 | 2026-04-20 | 4dd676b docs(sec-01): add Phase 1 implementation prompt wi | unknown | sec-01-p1 — Phase 1 implementation: admin token localStorage → server-side sessi | 0 |
| `archive/docs/prompts/sec-02-p0.md` | 75 | 2026-04-20 | 4724a1b docs(sec-02): add Phase 0 investigation prompt for | unknown | sec-02-p0 — Phase 0 investigation: admin `/run_script` TOCTOU race | 0 |
| `archive/docs/prompts/sec-02-p1.md` | 127 | 2026-04-21 | 020c517 docs(sec-02): add Phase 1 implementation prompt fo | unknown | sec-02-p1 — Phase 1 implementation: admin `/run_script` TOCTOU race fix | 0 |
| `archive/docs/prompts/sec-03-p0.md` | 75 | 2026-04-21 | c8cee2f docs(sec-03): add Phase 0 investigation prompt for | unknown | sec-03-p0 — Phase 0 investigation: admin endpoint write-surface audit | 0 |
| `archive/docs/prompts/sec-03-p1.md` | 107 | 2026-04-21 | 13dd111 docs(sec-03): add Phase 1 implementation prompt fo | unknown | sec-03-p1 — Phase 1 implementation: /add_ticker guard + /entity_override IOExcep | 0 |
| `archive/docs/prompts/sec-04-p0.md` | 72 | 2026-04-21 | d0fba1c docs(sec-04): add Phase 0 investigation prompt for | unknown | sec-04-p0 — Phase 0 investigation: validators writing to prod | 0 |
| `archive/docs/prompts/sec-04-p1.md` | 69 | 2026-04-21 | f6447ee docs(sec-04): add Phase 1 implementation prompt fo | unknown | sec-04-p1 — Phase 1 implementation: validator read-only fixes | 0 |
| `archive/docs/proposals/tier-4-join-pattern-proposal.md` | 413 | 2026-04-23 | e1b11e1 tier-4-join-pattern-proposal: design doc for int-0 | proposal | Tier 4 Join Pattern Proposal | 6 |
| `archive/docs/reports/block3_phase2_rerun_20260418_193735.md` | 183 | 2026-04-18 | a643b65 chore(block-3): phase 2 rerun against post-Audit + | report | BLOCK-3 Phase 2 Rerun — Report | 1 |
| `archive/docs/reports/block3_phase4_prod_apply_20260418_201319.md` | 120 | 2026-04-18 | 2405df1 chore(block-3): phase 4 prod apply — enrich_holdin | report | BLOCK-3 Phase 4 Prod Apply — Report | 1 |
| `archive/docs/reports/block_sector_coverage_closeout_20260419_052804.md` | 277 | 2026-04-19 | ccd9274 docs(block-sector-coverage): closeout + upsert-mod | report | BLOCK-SECTOR-COVERAGE-BACKGROUND — closeout | 3 |
| `archive/docs/reports/block_securities_audit_phase2_20260418_105033.md` | 344 | 2026-04-18 | 82dadb7 chore(block-securities-data-audit): phase 2 re-see | report | BLOCK-SECURITIES-DATA-AUDIT — Phase 2 Re-Seed Report | 1 |
| `archive/docs/reports/block_securities_audit_phase2b_20260418_155554.md` | 299 | 2026-04-18 | 8742c0c chore(block-securities-data-audit): phase 2b Path  | report | BLOCK-SECURITIES-DATA-AUDIT — Phase 2b Path A + Drain Report | 1 |
| `archive/docs/reports/block_ticker_backfill_closeout_20260418_205753.md` | 141 | 2026-04-18 | 0bb56d3 docs(block-ticker-backfill): closeout report — hoo | report | BLOCK-TICKER-BACKFILL — Close-out Report | 1 |
| `archive/docs/reports/rewrite_build_managers_phase2_20260419_082630.md` | 459 | 2026-04-19 | b50868a docs(rewrite): build_managers Risk 1 pre-Phase-4 i | report | REWRITE build_managers.py — Phase 2 staging validation | 1 |
| `archive/docs/reports/rewrite_build_shares_history_phase2_20260419_054947.md` | 214 | 2026-04-19 | db7de66 chore(rewrite): build_shares_history phase 2 stagi | report | REWRITE build_shares_history.py — Phase 2 Staging Validation Report | 1 |
| `archive/docs/reports/rewrite_load_13f_phase2_20260419_071500.md` | 185 | 2026-04-19 | dd1d382 chore(rewrite): load_13f phase 2 staging validatio | report | REWRITE load_13f.py — Phase 2 staging validation | 1 |
| `archive/docs/superpowers/plans/2026-04-01-flask-web-app.md` | 148 | 2026-04-01 | 35cbe01 Flask web app UI fixes - company name, autocomplet | unknown | Flask Web Application — Implementation Plan | 0 |
| `archive/docs/superpowers/specs/2026-04-06-peer-rotation-plan.md` | 244 | 2026-04-13 | baaf443 docs: add superpowers design specs (peer-rotation  | plan | Peer Rotation Tab — Implementation Plan | 0 |
| `archive/docs/superpowers/specs/2026-04-06-sector-rotation-redesign.md` | 220 | 2026-04-13 | baaf443 docs: add superpowers design specs (peer-rotation  | unknown | Sector Rotation Tab — Redesign Spec | 0 |
| `docs/write_path_risk_map.md` | 236 | 2026-04-21 | 1a47a0e remediation/ops-batch-5B: write_path_risk_map + ap | unknown | Write-Path Risk Map | 11 |
| `web/README_deploy.md` | 119 | 2026-04-01 | 4105689 N-PORT pipeline built and tested, queries 1-3 prod | tracker | Deploying 13-F Ownership Research to Render.com | 13 |


## §1.a Archive Candidates

Files with no internal references and last modified >60 days ago: 0

*(No archive candidates)*
# §2 Script Inventory

**Summary:** 162 scripts total:
- 67 actively called or manually invoked
- 18 retired
- 77 unused (candidates for retirement)

## §2.a Active Scripts (Actively Called + Manually Invoked)

| Path | LOC | Last modified | Last commit | Invocation |
|------|-----|---|---|---|
| scripts/admin_bp.py | 1734 | 2026-04-22 | 07412d3: p2-07: 9 admin refresh endpoints + admin_preferences migrati | actively called |
| scripts/api_common.py | 200 | 2026-04-23 | 0411388: bl7-ticker-validation: route-layer ticker validation against | actively called |
| scripts/api_config.py | 93 | 2026-04-22 | 8fb7340: p2-08: Data Source tab — markdown content + API route | actively called |
| scripts/api_cross.py | 189 | 2026-04-23 | 0411388: bl7-ticker-validation: route-layer ticker validation against | actively called |
| scripts/api_entities.py | 206 | 2026-04-19 | 62ad0eb: post-merge-fixes: Flow Analysis dup — INF34 full sweep of in | actively called |
| scripts/api_flows.py | 228 | 2026-04-23 | 0411388: bl7-ticker-validation: route-layer ticker validation against | actively called |
| scripts/api_fund.py | 253 | 2026-04-23 | 0411388: bl7-ticker-validation: route-layer ticker validation against | actively called |
| scripts/api_market.py | 306 | 2026-04-23 | 0411388: bl7-ticker-validation: route-layer ticker validation against | actively called |
| scripts/api_register.py | 396 | 2026-04-23 | 0411388: bl7-ticker-validation: route-layer ticker validation against | actively called |
| scripts/app.py | 134 | 2026-04-22 | ae112db: p2-09: Admin dashboard — auth-protected React route at /admi | actively called |
| scripts/app_db.py | 173 | 2026-04-13 | 746a798: feat: Phase 4 Batch 4-A — Blueprint split of scripts/app.py | actively called |
| scripts/approve_overrides.py | 275 | 2026-04-09 | ee5e7cb: Pre-Phase 4 complete: Items 2-9 done, all validation gates p | actively called |
| scripts/auto_resolve.py | 626 | 2026-04-21 | fa01c7e: sec-08: centralize EDGAR identity in config.py, normalize 21 | actively called |
| scripts/backfill_manager_types.py | 235 | 2026-04-21 | b716cf4: sec-06: retire 3 dead resolver scripts, harden backfill_mana | manually invoked |
| scripts/benchmark.py | 117 | 2026-04-22 | 433e217: p2fu-02: repoint scheduler/update/benchmark to SourcePipelin | actively called |
| scripts/build_benchmark_weights.py | 162 | 2026-04-21 | 742d504: sec-05: fix --staging path for build_fund_classes + build_be | actively called |
| scripts/build_classifications.py | 460 | 2026-04-22 | bc47092: int-13: migration 012 + is_otc classifier + backfill script  | actively called |
| scripts/build_cusip.py | 457 | 2026-04-21 | f2ce10d: remediation/int-04-p1: add issuer_name to build_cusip.py pro | actively called |
| scripts/build_entities.py | 1033 | 2026-04-21 | a410c1a: mig-13: CHECKPOINT build_entities + clean merge_staging stal | actively called |
| scripts/build_fund_classes.py | 355 | 2026-04-23 | 94e3350: build-fund-classes-rewrite: retrofit §1/§5/§9 + fund_holding | actively called |
| scripts/build_managers.py | 822 | 2026-04-22 | e39764f: w2-05: ADV pipeline migrated to SourcePipeline subclass | actively called |
| scripts/build_summaries.py | 425 | 2026-04-22 | 41a3c66: p2-04: extend is_latest sweep to background builders + admin | actively called |
| scripts/cache.py | 43 | 2026-04-13 | 125d86d: refactor: Phase 4 Batch 4-B — queries.py service layer split | actively called |
| scripts/compute_flows.py | 515 | 2026-04-22 | 41a3c66: p2-04: extend is_latest sweep to background builders + admin | actively called |
| scripts/config.py | 81 | 2026-04-21 | fa01c7e: sec-08: centralize EDGAR identity in config.py, normalize 21 | actively called |
| scripts/db.py | 219 | 2026-04-21 | 742d504: sec-05: fix --staging path for build_fund_classes + build_be | actively called |
| scripts/enrich_fund_holdings_v2.py | 465 | 2026-04-17 | 488401a: feat(enrich): BLOCK-2 fund_holdings_v2 entity_id backfill jo | actively called |
| scripts/enrich_holdings.py | 734 | 2026-04-19 | 90514c6: pct-of-so Phase 1c: Pass B tier split + tier_distribution co | actively called |
| scripts/entity_sync.py | 1473 | 2026-04-21 | fa01c7e: sec-08: centralize EDGAR identity in config.py, normalize 21 | actively called |
| scripts/export.py | 134 | 2026-04-13 | 9ea3557: fix: BL-10 — 4 broken Excel exports (q6/q10/q11/q15) | actively called |
| scripts/fetch_13f.py | 125 | 2026-04-21 | fa01c7e: sec-08: centralize EDGAR identity in config.py, normalize 21 | actively called |
| scripts/fetch_dera_nport.py | 1279 | 2026-04-21 | fa01c7e: sec-08: centralize EDGAR identity in config.py, normalize 21 | actively called |
| scripts/fetch_finra_short.py | 271 | 2026-04-21 | fa01c7e: sec-08: centralize EDGAR identity in config.py, normalize 21 | actively called |
| scripts/fix_fund_classification.py | 153 | 2026-04-22 | b98472b: int-22: add CHECKPOINT to fix_fund_classification.py (#76) | manually invoked |
| scripts/load_13f.py | 422 | 2026-04-19 | 14a5152: feat(load_13f): add OTHERMANAGER2 loader, materialize other_ | actively called |
| scripts/merge_staging.py | 441 | 2026-04-22 | 9c104c2: int-14: add NULL-only merge mode to merge_staging.py (#85) | actively called |
| scripts/migrations/001_pipeline_control_plane.py | 236 | 2026-04-13 | 3816577: feat: pipeline framework foundation — v1.2 docs + control pl | actively called |
| scripts/migrations/009_admin_sessions.py | 204 | 2026-04-20 | e68dc94: remediation/sec-01-p1: admin token localStorage → server-sid | actively called |
| scripts/normalize_names.py | 242 | 2026-04-03 | dabe5d1: Name standardization, Short Squeeze tab, Long/Short in Smart | manually invoked |
| scripts/pipeline/__init__.py | 6 | 2026-04-13 | 3816577: feat: pipeline framework foundation — v1.2 docs + control pl | actively called |
| scripts/pipeline/base.py | 1073 | 2026-04-23 | 12af4be: int-23-impl: downgrade-refusal invariant on _promote_append_ | actively called |
| scripts/pipeline/cadence.py | 500 | 2026-04-22 | 9111ce6: p2-06: PIPELINE_CADENCE config + probe functions + staleness | actively called |
| scripts/pipeline/cusip_classifier.py | 692 | 2026-04-22 | bc47092: int-13: migration 012 + is_otc classifier + backfill script  | actively called |
| scripts/pipeline/discover.py | 527 | 2026-04-21 | fa01c7e: sec-08: centralize EDGAR identity in config.py, normalize 21 | actively called |
| scripts/pipeline/load_13dg.py | 872 | 2026-04-22 | b0f88c5: w2-01: 13D/G pipeline migrated to SourcePipeline subclass | actively called |
| scripts/pipeline/load_adv.py | 550 | 2026-04-22 | e39764f: w2-05: ADV pipeline migrated to SourcePipeline subclass | actively called |
| scripts/pipeline/load_market.py | 545 | 2026-04-22 | 3001a47: w2-02: market data pipeline migrated to SourcePipeline subcl | actively called |
| scripts/pipeline/load_ncen.py | 842 | 2026-04-22 | a64f794: w2-04: N-CEN pipeline migrated to SourcePipeline subclass | actively called |
| scripts/pipeline/load_nport.py | 1115 | 2026-04-22 | e25f0ff: w2-03: N-PORT pipeline migrated to SourcePipeline subclass | actively called |
| scripts/pipeline/manifest.py | 343 | 2026-04-21 | 56dcfcb: remediation/mig-01-p1: atomic promotes + manifest mirror ext | actively called |
| scripts/pipeline/nport_parsers.py | 181 | 2026-04-17 | 22278b8: refactor(nport): BLOCK-3 Phase 1 — extract N-PORT parsers +  | actively called |
| scripts/pipeline/pipelines.py | 96 | 2026-04-22 | b0baebe: w2-05: ADV pipeline migrated to SourcePipeline subclass | actively called |
| scripts/pipeline/protocol.py | 276 | 2026-04-13 | 3816577: feat: pipeline framework foundation — v1.2 docs + control pl | actively called |
| scripts/pipeline/shared.py | 651 | 2026-04-20 | 18a6e2a: remediation/obs-03-p1: centralized id_allocator + DROP DEFAU | actively called |
| scripts/promote_staging.py | 812 | 2026-04-21 | 742d504: sec-05: fix --staging path for build_fund_classes + build_be | actively called |
| scripts/queries.py | 5741 | 2026-04-23 | 62a36e6: query1-guard: null-safety on institution field in query1() ( | actively called |
| scripts/queue_nport_excluded.py | 118 | 2026-04-21 | af66013: remediation/sec-04-p1: validators default read-only + split  | actively called |
| scripts/refetch_missing_sectors.py | 281 | 2026-04-22 | c3d84b7: int-15: stamp fetch_date + metadata_date on sector refetch U | manually invoked |
| scripts/refresh_snapshot.sh | 74 | 2026-04-10 | d0677b1: INF13 (part 1): refresh_snapshot.sh uses DuckDB COPY FROM DA | actively called |
| scripts/run_pipeline.sh | 78 | 2026-04-10 | c2fb215: INF10: gate merge_staging --all; name 13D/G tables explicitl | actively called |
| scripts/schemas.py | 124 | 2026-04-13 | 6572a46: feat: Phase 1-B2 rollout — envelope + schemas on 6 priority  | actively called |
| scripts/sec_shares_client.py | 332 | 2026-04-21 | fa01c7e: sec-08: centralize EDGAR identity in config.py, normalize 21 | actively called |
| scripts/serializers.py | 211 | 2026-04-13 | 125d86d: refactor: Phase 4 Batch 4-B — queries.py service layer split | actively called |
| scripts/update.py | 120 | 2026-04-22 | 433e217: p2fu-02: repoint scheduler/update/benchmark to SourcePipelin | actively called |
| scripts/validate_entities.py | 916 | 2026-04-21 | af66013: remediation/sec-04-p1: validators default read-only + split  | actively called |
| scripts/validate_phase4.py | 216 | 2026-04-09 | 2946f27: Stage 3: Add validate_phase4.py — all 8 parity gates pass | manually invoked |
| scripts/yahoo_client.py | 197 | 2026-04-16 | d59b6fb: chore: BL-8 — fix W0621 redefined-outer-name (6 occurrences) | actively called |

## §2.b Retired Scripts

| Path | LOC | Last modified |
|------|-----|---|
| scripts/retired/build_cusip_legacy.py | 394 | 2026-04-17 |
| scripts/retired/fetch_13dg.py | 925 | 2026-04-22 |
| scripts/retired/fetch_13dg_v2.py | 654 | 2026-04-22 |
| scripts/retired/fetch_adv.py | 389 | 2026-04-22 |
| scripts/retired/fetch_market.py | 1147 | 2026-04-22 |
| scripts/retired/fetch_ncen.py | 656 | 2026-04-22 |
| scripts/retired/fetch_nport.py | 767 | 2026-04-18 |
| scripts/retired/fetch_nport_v2.py | 995 | 2026-04-22 |
| scripts/retired/promote_13dg.py | 275 | 2026-04-22 |
| scripts/retired/promote_adv.py | 153 | 2026-04-22 |
| scripts/retired/promote_nport.py | 501 | 2026-04-22 |
| scripts/retired/resolve_agent_names.py | 282 | 2026-04-21 |
| scripts/retired/resolve_bo_agents.py | 398 | 2026-04-21 |
| scripts/retired/resolve_names.py | 340 | 2026-04-21 |
| scripts/retired/unify_positions.py | 159 | 2026-04-13 |
| scripts/retired/validate_13dg.py | 280 | 2026-04-22 |
| scripts/retired/validate_nport.py | 721 | 2026-04-22 |
| scripts/retired/validate_nport_subset.py | 267 | 2026-04-22 |

## §2.c Retire Candidates (Unused Scripts)

| Path | LOC | Last modified | Last known usage |
|------|-----|---|---|
| scripts/audit_read_sites.py | 385 | 2026-04-22 | never called in current tree |
| scripts/audit_ticket_numbers.py | 378 | 2026-04-23 | never called in current tree |
| scripts/audit_tracker_staleness.py | 328 | 2026-04-23 | never called in current tree |
| scripts/backfill_pending_context.py | 171 | 2026-04-15 | never called in current tree |
| scripts/backup_db.py | 143 | 2026-04-10 | never called in current tree |
| scripts/bootstrap_etf_advisers.py | 234 | 2026-04-15 | never called in current tree |
| scripts/bootstrap_residual_advisers.py | 268 | 2026-04-16 | never called in current tree |
| scripts/bootstrap_tier_c_advisers.py | 233 | 2026-04-17 | never called in current tree |
| scripts/bootstrap_tier_c_wave2.py | 211 | 2026-04-17 | never called in current tree |
| scripts/bootstrap_worktree.sh | 101 | 2026-04-23 | never called in current tree |
| scripts/build_fixture.py | 370 | 2026-04-22 | never called in current tree |
| scripts/build_shares_history.py | 222 | 2026-04-19 | never called in current tree |
| scripts/check_freshness.py | 108 | 2026-04-15 | never called in current tree |
| scripts/cleanup_merged_worktree.sh | 104 | 2026-04-23 | never called in current tree |
| scripts/concat_closed_log.py | 69 | 2026-04-23 | never called in current tree |
| scripts/diff_staging.py | 556 | 2026-04-12 | never called in current tree |
| scripts/dm14_layer1_apply.py | 174 | 2026-04-16 | never called in current tree |
| scripts/dm14b_apply.py | 247 | 2026-04-17 | never called in current tree |
| scripts/dm14c_voya_amundi_apply.py | 274 | 2026-04-17 | never called in current tree |
| scripts/dm15_layer1_apply.py | 205 | 2026-04-17 | never called in current tree |
| scripts/dm15_layer2_apply.py | 216 | 2026-04-17 | never called in current tree |
| scripts/dm15c_amundi_sa_apply.py | 309 | 2026-04-17 | never called in current tree |
| scripts/enrich_13dg.py | 263 | 2026-04-16 | never called in current tree |
| scripts/enrich_tickers.py | 436 | 2026-04-21 | never called in current tree |
| scripts/entity_schema.sql | 319 | 2026-04-12 | never called in current tree |
| scripts/inf23_apply.py | 306 | 2026-04-17 | never called in current tree |
| scripts/inf39_rebuild_staging.py | 394 | 2026-04-22 | never called in current tree |
| scripts/load_13f_v2.py | 819 | 2026-04-22 | never called in current tree |
| scripts/migrate_batch_3a.py | 105 | 2026-04-13 | never called in current tree |
| scripts/migrations/002_fund_universe_strategy.py | 71 | 2026-04-14 | never called in current tree |
| scripts/migrations/003_cusip_classifications.py | 299 | 2026-04-14 | never called in current tree |
| scripts/migrations/004_summary_by_parent_rollup_type.py | 247 | 2026-04-21 | never called in current tree |
| scripts/migrations/005_beneficial_ownership_entity_rollups.py | 157 | 2026-04-16 | never called in current tree |
| scripts/migrations/006_override_id_sequence.py | 204 | 2026-04-17 | never called in current tree |
| scripts/migrations/007_override_new_value_nullable.py | 185 | 2026-04-20 | never called in current tree |
| scripts/migrations/008_rename_pct_of_float_to_pct_of_so.py | 340 | 2026-04-19 | never called in current tree |
| scripts/migrations/010_drop_nextval_defaults.py | 220 | 2026-04-20 | never called in current tree |
| scripts/migrations/011_securities_cusip_pk.py | 262 | 2026-04-22 | never called in current tree |
| scripts/migrations/012_securities_is_otc.py | 173 | 2026-04-22 | never called in current tree |
| scripts/migrations/013_drop_top10_columns.py | 171 | 2026-04-22 | never called in current tree |
| scripts/migrations/014_surrogate_row_id.py | 250 | 2026-04-22 | never called in current tree |
| scripts/migrations/015_amendment_semantics.py | 483 | 2026-04-22 | never called in current tree |
| scripts/migrations/016_admin_preferences.py | 159 | 2026-04-22 | never called in current tree |
| scripts/migrations/017_ncen_scd_columns.py | 242 | 2026-04-22 | never called in current tree |
| scripts/migrations/add_last_refreshed_at.py | 186 | 2026-04-21 | never called in current tree |
| scripts/normalize_securities.py | 159 | 2026-04-22 | never called in current tree |
| scripts/oneoff/apply_series_triage.py | 733 | 2026-04-22 | never called in current tree |
| scripts/oneoff/apply_ticker_override_triage.py | 156 | 2026-04-22 | never called in current tree |
| scripts/oneoff/backfill_13dg_impacts.py | 256 | 2026-04-21 | never called in current tree |
| scripts/oneoff/backfill_is_otc.py | 240 | 2026-04-22 | never called in current tree |
| scripts/oneoff/backfill_schema_versions_stamps.py | 279 | 2026-04-21 | never called in current tree |
| scripts/oneoff/export_new_entity_worksheet.py | 337 | 2026-04-22 | never called in current tree |
| scripts/oneoff/export_ticker_override_triage.py | 249 | 2026-04-22 | never called in current tree |
| scripts/oneoff/export_unresolved_series.py | 179 | 2026-04-22 | never called in current tree |
| scripts/oneoff/fix_permanent_pending.py | 107 | 2026-04-21 | never called in current tree |
| scripts/oneoff/int_01_requeue.py | 146 | 2026-04-21 | never called in current tree |
| scripts/pipeline/id_allocator.py | 160 | 2026-04-20 | never called in current tree |
| scripts/pipeline/registry.py | 397 | 2026-04-22 | never called in current tree |
| scripts/pipeline/validate_schema_parity.py | 1005 | 2026-04-22 | never called in current tree |
| scripts/queries_helpers.py | 198 | 2026-04-23 | never called in current tree |
| scripts/reparse_13d.py | 315 | 2026-04-21 | never called in current tree |
| scripts/reparse_all_nulls.py | 289 | 2026-04-21 | never called in current tree |
| scripts/resolve_13dg_filers.py | 538 | 2026-04-17 | never called in current tree |
| scripts/resolve_adv_ownership.py | 1105 | 2026-04-21 | never called in current tree |
| scripts/resolve_long_tail.py | 269 | 2026-04-21 | never called in current tree |
| scripts/resolve_pending_series.py | 978 | 2026-04-17 | never called in current tree |
| scripts/rollback_promotion.py | 50 | 2026-04-17 | never called in current tree |
| scripts/rollback_run.py | 298 | 2026-04-22 | never called in current tree |
| scripts/rotate_logs.sh | 80 | 2026-04-21 | never called in current tree |
| scripts/run_openfigi_retry.py | 351 | 2026-04-21 | never called in current tree |
| scripts/scheduler.py | 156 | 2026-04-22 | never called in current tree |
| scripts/smoke_yahoo_client.py | 167 | 2026-04-09 | never called in current tree |
| scripts/snapshot_manager_type_legacy.py | 101 | 2026-04-19 | never called in current tree |
| scripts/start_app.sh | 11 | 2026-04-23 | never called in current tree |
| scripts/sync_staging.py | 306 | 2026-04-23 | never called in current tree |
| scripts/validate_classifications.py | 246 | 2026-04-14 | never called in current tree |
| scripts/verify_migration_stamps.py | 146 | 2026-04-21 | never called in current tree |# §3 Prod Database Audit

**DB file:** `data/13f.duckdb` (opened read-only from `/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership/data/13f.duckdb`; worktree has no local copy).

**Summary:** 57 tables, 2 views. Active 41 / orphan 15 / writer-retired 1.
_Additionally_ 292 historic `*_snapshot_YYYYMMDD_HHMMSS` tables are present (excluded from the master table — they are point-in-time audit copies of 12 base tables). Master-table `last write` = max of `loaded_at | updated_at | refreshed_at | created_at | valid_from` where the column exists; blank means the table has no such column.

## §3.a Master table

| Table | Rows | Cols | Last write | Writers | Readers | Flag |
|---|---:|---:|---|---|---|---|
| `_cache_openfigi` | 15,807 | 7 | — | scripts/build_cusip.py, scripts/migrations/003_cusip_classifications.py, scripts/retired/build_cusip_legacy.py, scripts/run_openfigi_retry.py | scripts/oneoff/export_ticker_override_triage.py | active |
| `admin_preferences` | 0 | 4 | — | scripts/migrations/016_admin_preferences.py | — | orphan |
| `admin_sessions` | 9 | 7 | — | scripts/admin_bp.py, scripts/migrations/009_admin_sessions.py | — | orphan |
| `adv_managers` | 16,606 | 18 | — | scripts/pipeline/load_adv.py, scripts/retired/fetch_adv.py, scripts/retired/promote_adv.py, tests/pipeline/test_load_adv.py, tests/pipeline/test_load_ncen.py | scripts/bootstrap_etf_advisers.py, scripts/bootstrap_residual_advisers.py, scripts/build_managers.py, scripts/entity_sync.py, scripts/pipeline/load_ncen.py (+2 more) | active |
| `benchmark_weights` | 55 | 6 | — | scripts/build_benchmark_weights.py | scripts/queries.py | active |
| `beneficial_ownership_current` | 24,756 | 21 | — | scripts/pipeline/shared.py, scripts/retired/fetch_13dg.py, scripts/retired/resolve_agent_names.py, scripts/retired/resolve_bo_agents.py, scripts/retired/resolve_names.py | scripts/queries.py | active |
| `beneficial_ownership_v2` | 51,905 | 28 | 2026-04-14 04:02:45.603706 | scripts/pipeline/load_13dg.py, scripts/pipeline/shared.py, scripts/retired/promote_13dg.py, tests/pipeline/test_load_13dg.py | scripts/admin_bp.py, scripts/enrich_13dg.py, scripts/oneoff/backfill_13dg_impacts.py, scripts/pipeline/cusip_classifier.py, scripts/pipeline/discover.py (+2 more) | active |
| `cik_crd_direct` | 4,059 | 3 | — | scripts/build_managers.py | scripts/build_entities.py | active |
| `cik_crd_links` | 353 | 5 | — | scripts/build_managers.py | scripts/build_entities.py | active |
| `cusip_classifications` | 430,149 | 33 | 2026-04-18 17:20:50.642046 | scripts/build_classifications.py, scripts/build_cusip.py, scripts/migrations/003_cusip_classifications.py, scripts/run_openfigi_retry.py, tests/pipeline/test_issuer_propagation.py | scripts/enrich_holdings.py, scripts/normalize_securities.py, scripts/oneoff/backfill_is_otc.py, scripts/oneoff/export_ticker_override_triage.py, scripts/oneoff/int_01_requeue.py (+2 more) | active |
| `cusip_retry_queue` | 37,929 | 13 | 2026-04-21 06:59:15.662070 | scripts/build_classifications.py, scripts/build_cusip.py, scripts/migrations/003_cusip_classifications.py, scripts/oneoff/fix_permanent_pending.py, scripts/oneoff/int_01_requeue.py (+1 more) | scripts/validate_classifications.py | active |
| `data_freshness` | 26 | 3 | — | scripts/db.py, scripts/migrate_batch_3a.py, scripts/migrations/001_pipeline_control_plane.py, scripts/pipeline/protocol.py, tests/pipeline/test_base.py (+5 more) | scripts/api_config.py, scripts/check_freshness.py, scripts/pipeline/cadence.py, scripts/pipeline/shared.py | active |
| `entities` | 26,602 | 6 | 2026-04-08 14:01:44.425362 | scripts/bootstrap_etf_advisers.py, scripts/bootstrap_residual_advisers.py, scripts/bootstrap_tier_c_advisers.py, scripts/bootstrap_tier_c_wave2.py, scripts/build_entities.py (+6 more) | scripts/admin_bp.py, scripts/build_fixture.py, scripts/inf23_apply.py, scripts/resolve_long_tail.py, scripts/resolve_pending_series.py (+2 more) | active |
| `entity_aliases` | 26,941 | 10 | 2026-04-17 | scripts/admin_bp.py, scripts/bootstrap_etf_advisers.py, scripts/bootstrap_residual_advisers.py, scripts/bootstrap_tier_c_advisers.py, scripts/bootstrap_tier_c_wave2.py (+10 more) | scripts/api_fund.py, scripts/build_fixture.py, scripts/enrich_13dg.py, scripts/enrich_fund_holdings_v2.py, scripts/entity_sync.py (+7 more) | active |
| `entity_classification_history` | 26,662 | 9 | 2026-04-17 | scripts/admin_bp.py, scripts/bootstrap_etf_advisers.py, scripts/bootstrap_residual_advisers.py, scripts/bootstrap_tier_c_advisers.py, scripts/bootstrap_tier_c_wave2.py (+8 more) | scripts/build_fixture.py, scripts/pipeline/shared.py, scripts/queries_helpers.py, scripts/resolve_long_tail.py, tests/test_queries_helpers.py | active |
| `entity_identifiers` | 35,512 | 9 | 2026-04-23 08:45:30.488136 | scripts/bootstrap_etf_advisers.py, scripts/bootstrap_residual_advisers.py, scripts/bootstrap_tier_c_advisers.py, scripts/bootstrap_tier_c_wave2.py, scripts/build_entities.py (+7 more) | scripts/admin_bp.py, scripts/api_fund.py, scripts/dm14b_apply.py, scripts/enrich_13dg.py, scripts/enrich_fund_holdings_v2.py (+16 more) | active |
| `entity_identifiers_staging` | 3,503 | 13 | 2026-04-08 06:38:04.144669 | scripts/entity_sync.py | scripts/resolve_adv_ownership.py, scripts/retired/fetch_ncen.py | active |
| `entity_overrides_persistent` | 257 | 15 | 2026-04-23 08:45:30.491397 | scripts/admin_bp.py, scripts/dm14_layer1_apply.py, scripts/dm14b_apply.py, scripts/dm14c_voya_amundi_apply.py, scripts/dm15_layer1_apply.py (+7 more) | scripts/build_entities.py, scripts/pipeline/shared.py | active |
| `entity_relationships` | 18,365 | 14 | 2026-04-17 06:37:50.309606 | scripts/build_entities.py, scripts/dm14b_apply.py, scripts/dm14c_voya_amundi_apply.py, scripts/entity_sync.py, scripts/inf23_apply.py (+1 more) | scripts/queries.py, scripts/retired/fetch_ncen.py, scripts/validate_entities.py | active |
| `entity_relationships_staging` | 0 | 14 | — | scripts/entity_sync.py | — | orphan |
| `entity_rollup_history` | 59,938 | 11 | 2026-04-17 | scripts/admin_bp.py, scripts/bootstrap_etf_advisers.py, scripts/bootstrap_residual_advisers.py, scripts/bootstrap_tier_c_advisers.py, scripts/bootstrap_tier_c_wave2.py (+15 more) | scripts/api_fund.py, scripts/build_fixture.py, scripts/enrich_13dg.py, scripts/enrich_fund_holdings_v2.py, scripts/pipeline/load_ncen.py (+10 more) | active |
| `fetched_tickers_13dg` | 6,075 | 2 | — | scripts/pipeline/load_13dg.py, scripts/retired/fetch_13dg.py, tests/pipeline/test_load_13dg.py | — | orphan |
| `filings` | 43,358 | 9 | — | scripts/load_13f.py, scripts/load_13f_v2.py, tests/pipeline/test_load_13f_v2.py | scripts/api_fund.py, scripts/api_register.py, scripts/queries.py, scripts/retired/fetch_nport_v2.py | active |
| `filings_deduped` | 40,140 | 9 | — | scripts/load_13f.py, scripts/load_13f_v2.py | scripts/build_managers.py, scripts/migrations/015_amendment_semantics.py, scripts/retired/fetch_13dg_v2.py, tests/pipeline/test_load_13f_v2.py | active |
| `fund_best_index` | 6,151 | 8 | — | — | — | orphan |
| `fund_classes` | 31,056 | 7 | 2026-04-02 08:21:59.489149 | scripts/build_fund_classes.py | — | orphan |
| `fund_classification` | 5,717 | 12 | — | — | — | orphan |
| `fund_family_patterns` | 83 | 2 | — | scripts/migrate_batch_3a.py | scripts/queries.py | active |
| `fund_holdings` | 22,030 | 19 | 2026-04-14 21:22:13.920485 | scripts/retired/fetch_nport.py | scripts/queries.py, scripts/retired/unify_positions.py | writer-retired |
| `fund_holdings_v2` | 14,090,397 | 30 | 2026-04-16 08:33:14.216606 | scripts/build_fund_classes.py, scripts/enrich_fund_holdings_v2.py, scripts/enrich_holdings.py, scripts/pipeline/load_nport.py, scripts/retired/promote_nport.py (+2 more) | scripts/api_fund.py, scripts/api_market.py, scripts/build_benchmark_weights.py, scripts/build_fixture.py, scripts/build_summaries.py (+9 more) | active |
| `fund_index_scores` | 80,271 | 8 | — | — | — | orphan |
| `fund_name_map` | 6,229,495 | 5 | — | — | — | orphan |
| `fund_universe` | 12,870 | 16 | — | scripts/fix_fund_classification.py, scripts/pipeline/load_nport.py, scripts/retired/fetch_nport.py, scripts/retired/promote_nport.py, tests/pipeline/test_load_ncen.py (+1 more) | scripts/backfill_pending_context.py, scripts/build_entities.py, scripts/dm14b_apply.py, scripts/oneoff/export_unresolved_series.py, scripts/pipeline/load_ncen.py (+3 more) | active |
| `holdings_v2` | 12,270,984 | 38 | 2026-02-27 00:00:00 | scripts/backfill_manager_types.py, scripts/build_managers.py, scripts/enrich_holdings.py, scripts/load_13f_v2.py, tests/pipeline/test_load_13f_v2.py (+1 more) | scripts/admin_bp.py, scripts/api_common.py, scripts/api_fund.py, scripts/api_market.py, scripts/api_register.py (+12 more) | active |
| `index_proxies` | 13,641 | 3 | — | — | — | orphan |
| `ingestion_impacts` | 98,706 | 17 | 2026-04-22 16:09:26.285637 | scripts/fetch_dera_nport.py, scripts/migrations/001_pipeline_control_plane.py, scripts/oneoff/backfill_13dg_impacts.py, scripts/pipeline/manifest.py, scripts/retired/fetch_adv.py (+15 more) | scripts/admin_bp.py, scripts/pipeline/base.py, scripts/retired/validate_nport.py, scripts/retired/validate_nport_subset.py, scripts/rollback_run.py | active |
| `ingestion_manifest` | 73,244 | 26 | 2026-04-22 16:08:54.051558 | scripts/migrations/001_pipeline_control_plane.py, scripts/oneoff/backfill_13dg_impacts.py, scripts/pipeline/manifest.py, scripts/pipeline/shared.py, tests/pipeline/test_base.py (+9 more) | scripts/admin_bp.py, scripts/fetch_dera_nport.py, scripts/pipeline/base.py, scripts/pipeline/cadence.py, scripts/pipeline/discover.py (+11 more) | active |
| `investor_flows` | 17,396,524 | 25 | — | scripts/compute_flows.py | scripts/queries.py | active |
| `lei_reference` | 13,143 | 6 | 2026-04-02 08:21:59.489149 | scripts/build_fund_classes.py | — | orphan |
| `listed_filings_13dg` | 60,247 | 8 | — | scripts/pipeline/load_13dg.py, scripts/retired/fetch_13dg.py, tests/pipeline/test_load_13dg.py | scripts/reparse_13d.py, scripts/reparse_all_nulls.py, scripts/retired/resolve_agent_names.py, scripts/retired/resolve_bo_agents.py | active |
| `managers` | 11,135 | 15 | — | scripts/backfill_manager_types.py, scripts/build_managers.py, scripts/pipeline/load_ncen.py, scripts/retired/fetch_13dg.py, scripts/retired/fetch_ncen.py | scripts/build_entities.py, scripts/oneoff/export_new_entity_worksheet.py, scripts/oneoff/export_unresolved_series.py, scripts/queries.py, scripts/validate_entities.py | active |
| `market_data` | 10,064 | 26 | — | scripts/admin_bp.py, scripts/approve_overrides.py, scripts/auto_resolve.py, scripts/enrich_tickers.py, scripts/pipeline/load_market.py (+3 more) | scripts/api_register.py, scripts/build_benchmark_weights.py, scripts/build_shares_history.py, scripts/compute_flows.py, scripts/enrich_holdings.py (+3 more) | active |
| `ncen_adviser_map` | 11,209 | 14 | 2026-04-17 13:12:29.228676 | scripts/pipeline/load_ncen.py, scripts/retired/fetch_ncen.py, tests/pipeline/test_load_ncen.py | scripts/build_entities.py, scripts/queries.py, scripts/resolve_pending_series.py, scripts/retired/unify_positions.py, scripts/validate_entities.py | active |
| `other_managers` | 15,405 | 8 | — | scripts/load_13f.py, scripts/load_13f_v2.py, tests/pipeline/test_load_13f_v2.py | — | orphan |
| `parent_bridge` | 11,135 | 7 | — | scripts/build_managers.py | scripts/validate_entities.py | active |
| `peer_groups` | 27 | 8 | — | — | scripts/api_cross.py | active |
| `pending_entity_resolution` | 6,874 | 13 | 2026-04-17 12:24:55.039202 | scripts/backfill_pending_context.py, scripts/migrations/001_pipeline_control_plane.py, scripts/oneoff/apply_series_triage.py, scripts/pipeline/shared.py, scripts/queue_nport_excluded.py (+6 more) | scripts/oneoff/export_unresolved_series.py | active |
| `raw_coverpage` | 43,358 | 10 | — | scripts/load_13f.py | — | orphan |
| `raw_infotable` | 13,540,608 | 15 | — | scripts/load_13f.py | — | orphan |
| `raw_submissions` | 43,358 | 6 | — | scripts/load_13f.py | — | orphan |
| `schema_versions` | 18 | 3 | — | scripts/migrations/003_cusip_classifications.py, scripts/migrations/005_beneficial_ownership_entity_rollups.py, scripts/migrations/006_override_id_sequence.py, scripts/migrations/007_override_new_value_nullable.py, scripts/migrations/008_rename_pct_of_float_to_pct_of_so.py (+9 more) | scripts/migrations/004_summary_by_parent_rollup_type.py, scripts/migrations/add_last_refreshed_at.py, scripts/oneoff/backfill_schema_versions_stamps.py, scripts/verify_migration_stamps.py | active |
| `securities` | 430,149 | 22 | — | scripts/approve_overrides.py, scripts/auto_resolve.py, scripts/build_cusip.py, scripts/enrich_tickers.py, scripts/normalize_securities.py (+3 more) | scripts/api_fund.py, scripts/enrich_holdings.py, scripts/oneoff/backfill_is_otc.py, scripts/oneoff/export_ticker_override_triage.py, scripts/pipeline/cusip_classifier.py (+9 more) | active |
| `shares_outstanding_history` | 338,053 | 7 | — | scripts/build_shares_history.py | scripts/enrich_holdings.py, scripts/queries.py | active |
| `short_interest` | 328,595 | 8 | 2026-04-03 16:49:36.459667 | scripts/fetch_finra_short.py | scripts/admin_bp.py, scripts/api_market.py, scripts/queries.py | active |
| `summary_by_parent` | 63,916 | 13 | 2026-04-23 08:23:26.353384 | scripts/build_summaries.py, scripts/migrations/004_summary_by_parent_rollup_type.py, tests/pipeline/test_validate_schema_parity.py | scripts/migrations/013_drop_top10_columns.py, scripts/queries.py, tests/test_audit_read_sites.py | active |
| `summary_by_ticker` | 47,732 | 11 | 2026-04-23 08:23:21.870507 | scripts/build_summaries.py | scripts/api_common.py, tests/test_app_ticker_validation.py | active |
| `ticker_flow_stats` | 80,322 | 10 | — | scripts/compute_flows.py | scripts/queries.py | active |

## §3.b Orphans (zero readers)

Tables with no `FROM|JOIN` references in scripts/web/tests after excluding their own writers.

| Table | Rows | Writers (evidence) | Note |
|---|---:|---|---|
| `admin_preferences` | 0 | scripts/migrations/016_admin_preferences.py | admin UI table; may be queried via ORM string not matching regex |
| `admin_sessions` | 9 | scripts/admin_bp.py, scripts/migrations/009_admin_sessions.py | admin UI table; may be queried via ORM string not matching regex |
| `entity_relationships_staging` | 0 | scripts/entity_sync.py | empty staging twin; safe |
| `fetched_tickers_13dg` | 6,075 | scripts/pipeline/load_13dg.py, scripts/retired/fetch_13dg.py, tests/pipeline/test_load_13dg.py | 13D/G fetcher checkpoint |
| `fund_best_index` | 6,151 | — | index match table; no reader found |
| `fund_classes` | 31,056 | scripts/build_fund_classes.py | fund share-class roster |
| `fund_classification` | 5,717 | — | fund classification output |
| `fund_index_scores` | 80,271 | — | fund→index similarity scores |
| `fund_name_map` | 6,229,495 | — | 6.2M-row fund name dictionary |
| `index_proxies` | 13,641 | — | index proxy lookup |
| `lei_reference` | 13,143 | scripts/build_fund_classes.py | LEI→adviser mapping |
| `other_managers` | 15,405 | scripts/load_13f.py, scripts/load_13f_v2.py, tests/pipeline/test_load_13f_v2.py | Item 3 other-managers raw store |
| `raw_coverpage` | 43,358 | scripts/load_13f.py | staging-era raw coverpage |
| `raw_infotable` | 13,540,608 | scripts/load_13f.py | staging-era raw infotable (13.5M rows) |
| `raw_submissions` | 43,358 | scripts/load_13f.py | staging-era raw submissions |

## §3.c Writer-retired tables

Tables whose only writers live under `scripts/retired/` but which still hold rows.

| Table | Rows | Retired writers |
|---|---:|---|
| `fund_holdings` | 22,030 | scripts/retired/fetch_nport.py |

## §3.d Missing tables (referenced in scripts but absent from DB)

Names found in `CREATE TABLE` statements across scripts/** but not present in the prod DB (after filtering obvious SQL/regex noise). Most are transient pipeline staging tables (`stg_*`) that are built and dropped within a single pipeline run — their absence is expected. Others flagged for review.

| Name | Files that create it |
|---|---|
| `_cache_yfinance` | scripts/retired/build_cusip_legacy.py |
| `_fixture_metadata` | scripts/build_fixture.py |
| `beneficial_ownership` | scripts/retired/fetch_13dg.py |
| `positions` | scripts/retired/unify_positions.py |
| `stg_13dg_fetched_tickers` | scripts/pipeline/load_13dg.py |
| `stg_13dg_filings` | scripts/retired/fetch_13dg_v2.py |
| `stg_13dg_listed` | scripts/pipeline/load_13dg.py |
| `stg_13dg_raw` | scripts/pipeline/load_13dg.py |
| `stg_13f_coverpage` | scripts/load_13f_v2.py |
| `stg_13f_filings` | scripts/load_13f_v2.py |
| `stg_13f_filings_deduped` | scripts/load_13f_v2.py |
| `stg_13f_infotable` | scripts/load_13f_v2.py |
| `stg_13f_other_managers` | scripts/load_13f_v2.py |
| `stg_13f_othermanager` | scripts/load_13f_v2.py |
| `stg_13f_submissions` | scripts/load_13f_v2.py |
| `stg_adv_raw` | scripts/pipeline/load_adv.py |
| `stg_market_sec_raw` | scripts/pipeline/load_market.py |
| `stg_market_tickers` | scripts/pipeline/load_market.py |
| `stg_market_yahoo_raw` | scripts/pipeline/load_market.py |
| `stg_ncen_raw` | scripts/pipeline/load_ncen.py |
| `stg_nport_fund_universe` | scripts/fetch_dera_nport.py, tests/pipeline/test_load_nport.py |
| `stg_nport_holdings` | scripts/fetch_dera_nport.py, tests/pipeline/test_load_nport.py |
| `summary_by_parent_new` | scripts/migrations/004_summary_by_parent_rollup_type.py |

## §3.e Views

- `entity_current`
- `ingestion_manifest_current`
# §4 Tracker Reconciliation

Open items enumerated: 14. Drift candidates: 5.

_(Open-item count = sum of truly-open ROADMAP rows + checklist unchecked + DEFERRED_FOLLOWUPS "Open" table rows, deduped by item-ID. Drift candidates = IDs whose status disagrees across trackers, per audit script + manual reconciliation below.)_

## Per-tracker open-item tally

| Tracker | File size (lines) | Open count | Notes |
|---|---|---|---|
| ROADMAP.md | 1,166 | 8 | `### Open items` block at L571–589 |
| docs/REMEDIATION_PLAN.md | 614 | 3 | Items with explicit status ∉ {CLOSED, SKIPPED, SUPERSEDED}: int-18 STANDING, int-19 DEFERRED, ops-18 BLOCKED |
| docs/REMEDIATION_CHECKLIST.md | 156 | 5 | Unchecked `- [ ]` lines at L39, 42, 98, 101, 156 |
| docs/DEFERRED_FOLLOWUPS.md | 82 | 5 | "Open items" table rows at L13–18 (INF25, INF27, INF37, INF38, P2-FU-01, P2-FU-03) — 6 data rows minus P2-FU-01 which is tactical; using 5 unique carry-forwards |
| docs/NEXT_SESSION_CONTEXT.md | 261 | 6 | "Post-Phase 2 carry-forward (open)" block at L65–73 plus "Next items" at L17–19 |

---

## §4 Master Drift Table

Compact status legend: R=ROADMAP, P=Plan, C=Checklist, D=DeferredFollowups, N=NextSession. `o`=open/standing/deferred/blocked, `c`=closed, `—`=not mentioned.

| Item ID / desc | Mentioned in | Status per tracker | Ground truth | Drift? | Recommended action |
|---|---|---|---|---|---|
| **int-18 / INF37** (backfill_manager_types residual 9 entities) | R, P, C, D, N | R=c (ROADMAP.md:580) · P=o STANDING (L54) · C=o (L39) · D=o (L15) · N=c (L8) | **CLOSED 2026-04-23** (commit `6c14c35` entity-curation-w1; see `docs/findings/entity-curation-w1-log.md`) | **Y** | Close in C (L39 checkbox → `[x]`) and in D (L15 move to "Closed during Remediation Program"). Confirmed by staleness script §1. |
| **mig-12** (load_13f_v2 rewrite) | R, P, C, D, N | R=c (ROADMAP.md:866) · P=c (L131) · C=o (L101) · D=c indirect · N=c (L73) | **CLOSED 2026-04-22** (absorbed by p2-05; `scripts/load_13f_v2.py` shipped) | **Y** | Close checkbox at `docs/REMEDIATION_CHECKLIST.md:101`. Confirmed by staleness script §2. |
| **int-09 Step 4 / INF25** (BLOCK-DENORM-RETIREMENT — ticker/entity_id/rollup_entity_id/lei drops) | R, D, N | R=o UNBLOCKED (L575) · D=o UNBLOCKED (L13) · N=o (L67) | **OPEN — unblocked post-Phase-2**. Requires dual-graph resolution decision. No closure record. | N | Leave open; consistent across trackers. |
| **int-19 / INF38** (BLOCK-FLOAT-HISTORY — true float-adjusted pct_of_float) | R, P, C, D, N | R=o (L578) · P=o DEFERRED (L55) · C=o (L42) · D=o (L16) · N=o (L68) | **OPEN / DEFERRED**. Needs float-history data source. | N | Leave open. Status consistent. |
| **mig-05** (admin refresh pre-restart rework) | P, C | P=SUPERSEDED (L445) · C=o BLOCKED (L98) | **SUPERSEDED by Phase 2** per `docs/admin_refresh_system_design.md`; checklist text still says "BLOCKED — upstream design doc missing" which is **stale** (design doc recovered `03db9ad`). | **Y** | Close checkbox at `docs/REMEDIATION_CHECKLIST.md:98` with note "SUPERSEDED by Phase 2 (p2-01..p2-10)". |
| **ops-18** (restore rotating_audit_schedule.md) | P, C | P=BLOCKED AMBIGUOUS (L208, L446) · C=o BLOCKED (L156) | **BLOCKED** — referenced file not found in branch. Status consistent. | N | Leave open or **ask Serge**: is this still needed, or retire as ambiguous? |
| **INF27** (CUSIP residual-coverage tracking tier) | R, D | R=o STANDING (L581) · D=o STANDING (L14) | **STANDING curation** — handled automatically by pipeline. | N | Leave. Status consistent. |
| **INF37** (duplicate of int-18 above) | — | — | See int-18 row. | — | — |
| **INF2** (monthly maintenance checklist) | R | R=o Recurring (L583) | **RECURRING** — monthly ops task, not a closeable ticket. | N | Leave. |
| **INF16** (recompute managers.aum_total for 2 Soros CIKs) | R | R=o Low (L582) | **OPEN — low priority**. No closure record found in `docs/closures/`, `docs/findings/`, or git log. | N | Leave open. |
| **43e** (family_office classification) | R, N | R=o RE-SCOPED (L584) · N=o (L10, L17) | **RE-SCOPED 2026-04-23** as dedicated taxonomy-refactor follow-on (entity-curation-w1). | N | Leave; status consistent. |
| **43g** (drop redundant type columns — is_actively_managed, manager_type) | R | R=o Medium (L585) | **OPEN**. No closure record. | N | Leave open. |
| **43b** (app.py remaining hardening — B110/B603/B607/B104) | R | R=o Low (L586) | **OPEN**. No closure record. | N | Leave open. |
| **48** (Phase 3.5 deferred items — D2/D4/D5/D10/D11/D12/D13) | R | R=o Partially done (L587) | **OPEN — partially done**. D1 + D7 closed; D2/D4/D5/D10/D11/D12/D13 open. | N | Leave open. |
| **56** (Decision maker and voting rollup worldviews — DM1..DM7) | R | R=o Not started (L588) | **OPEN — Not started**. DM## ticket-number reuse collision flagged by §4.b below. | N(status) / **Y**(ID hygiene) | Leave status open; raise DM-series ID hygiene with Serge — see §4.b. |
| **P2-FU-01** (legacy run_script allowlist references retired scripts) | D, N | D=o NEW (L17) · N=o (L69) | **OPEN — new conv-12 follow-up**. Prune after one clean quarterly cycle. | N | Leave. |
| **P2-FU-03** (ADV SCD Type 2 conversion) | D, N | D=o NEW (L18) · N=o (L71) | **OPEN — deferred**. | N | Leave. |
| **INF40 (entity-CTAS)** (sync_staging.py DDL-first rewrite) | R, N | R=c (L600) · N=c (L22) | **CLOSED 2026-04-23** (commit `c154dcb` inf40-fix). Note: **ticket-number collision** with prior-closed `INF40 (L3 surrogate row-ID)`. | N(status) / **Y**(ID reuse, violates hygiene-ticket-numbering) | Flag to Serge: retire-forever rule in `docs/REVIEW_CHECKLIST.md` was violated by reusing INF40. Consider re-issuing under fresh ID per `aab73d2` policy. |
| **INF9f** (Agincourt CRD-only residual) | R, N | R=c (L599) · N=c (L21) | **CLOSED 2026-04-23** (`inf9f-agincourt`). | N | Leave. |
| **INF9** (persist 2026-04-10 overrides) | R, N | R=c (L601) · N=c (L20) | **CLOSED 2026-04-23** (PR #120). | N | Leave. |
| **int-22** (prod is_latest inversion rollback) | D, N | D=c (L19) · N=c (L14) | **CLOSED 2026-04-22** (int-22-prod-execute-and-verify). | N | Leave. |
| **int-23** (load_13f_v2 idempotency) | D | D=c (L20) | **CLOSED 2026-04-23** (PR #119 int-23-impl). | N | Leave. |

### Drift summary

Five drift candidates (all in `docs/REMEDIATION_CHECKLIST.md` carrying stale unchecked `- [ ]` for items already closed elsewhere):

1. **int-18 / INF37** — R/N closed, C still unchecked at L39.
2. **mig-12** — R/P/N closed, C still unchecked at L101.
3. **mig-05** — P=SUPERSEDED, C still unchecked at L98 with stale "BLOCKED" rationale.
4. **INF40 reuse** — ticket-number reuse collision (R has both INF40 closures, neither is a status drift but violates ticket hygiene).
5. **DM-series** — ID reuse (DM3, DM6 per §4.b below) inside `docs/findings/dm-open-surface-2026-04-22.md`.

---

## §4.a Staleness audit — `scripts/audit_tracker_staleness.py`

**Exit status:** 1 (non-zero because drift was detected; the script intentionally exits non-zero on findings).

**Raw output (full, 32 lines):**

```
scanned 5 tracker docs
found 148 unique IDs
detected 2 IDs with cross-doc status drift

--- INF37 ---
  ROADMAP.md: closed
  docs/DEFERRED_FOLLOWUPS.md: neutral
  docs/NEXT_SESSION_CONTEXT.md: closed
  docs/REMEDIATION_CHECKLIST.md: open
  docs/REMEDIATION_PLAN.md: neutral
    ROADMAP.md:580 [closed] | INF37 | `backfill_manager_types` residual — 9 entities / 14,368 rows | **CLEARED 2026-04-23 (`entity-curation-w1`).**
    docs/REMEDIATION_CHECKLIST.md:39 [open] - [ ] int-18 INF37 backfill_manager_types residual 9 entities (no closure expected)
    docs/NEXT_SESSION_CONTEXT.md:8 [closed] - **INF37 CLEARED** — 9 entities / 14,368 rows flipped from NULL/unknown

--- mig-12 ---
  ROADMAP.md: closed
  docs/DEFERRED_FOLLOWUPS.md: closed
  docs/NEXT_SESSION_CONTEXT.md: closed
  docs/REMEDIATION_CHECKLIST.md: open
  docs/REMEDIATION_PLAN.md: closed, neutral, reference
    ROADMAP.md:866 [closed] | 2026-04-22 | **Phase 2 + Wave 2 close (summary)**
    docs/REMEDIATION_PLAN.md:131 [closed] | mig-12 | load_13f_v2 rewrite | **CLOSED 2026-04-22 (conv-12)**
    docs/REMEDIATION_CHECKLIST.md:101 [open] - [ ] mig-12 load_13f_v2 rewrite
    docs/NEXT_SESSION_CONTEXT.md:73 [closed] - **mig-12** — **CLOSED (absorbed by p2-05 `load_13f_v2.py`).**
```

**Summary.** Script scans the 5 tracker docs and flags exactly 2 cross-doc status drifts: `INF37` and `mig-12`. Both share the same failure mode — the item is closed in ROADMAP + NextSession + Plan, but the `- [ ]` checkbox in `docs/REMEDIATION_CHECKLIST.md` was never flipped (`int-18 / INF37` at L39; `mig-12` at L101). Zero false positives: both flags reflect real stale checkboxes. Also: **mig-05** is not flagged because the script's status heuristic treats "BLOCKED" and "SUPERSEDED" differently; a manual pass caught the C-vs-P disagreement (logged in the master table above). Recommend Serge flip the two checkboxes and retire the mig-05 checkbox with a SUPERSEDED note.

---

## §4.b Ticket number audit — `scripts/audit_ticket_numbers.py`

**Exit status:** 0 (script always exits 0; findings surfaced as prose).

**Raw excerpt (prefix usage + top collisions, first 28 lines of 494):**

```
=== Ticket Number Audit ===
Scanned 135 markdown files
Distinct ticket numbers with definitions: 123

--- Prefix usage + gaps ---
  DM      count=  8  range=[2..15]  gaps: [4, 5, 7, 9, 10, 11]
  INF     count= 21  range=[1..47]  gaps: [2, 5, 6, 7, 8, 10, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 24, 27, 32, 33, 34, 35, 36, 43, 44]
  conv-   count= 11  range=[1..11]
  int-    count= 22  range=[1..23]  gaps: [18]
  mig-    count= 14  range=[1..14]
  obs-    count= 11  range=[1..13]  gaps: [5, 11]
  ops-    count= 17  range=[1..18]  gaps: [14]
  sec-    count=  8  range=[1..8]

--- Candidate number reuse (≥2 distinct titles) ---
DM3  — 2 distinct titles (both in docs/findings/dm-open-surface-2026-04-22.md)
DM6  — 2 distinct titles (both in docs/findings/dm-open-surface-2026-04-22.md)
INF25  — 2 distinct titles (int-09 findings + REMEDIATION_SESSION_LOG header)
INF39  — 3 distinct titles (bullet ref + 2 headings in BLOCK_SCHEMA_DIFF_FINDINGS / PHASE_1 log)
INF40  — 2 distinct titles (surrogate row-ID plan ref + L3 finding header)
INF41  — 2 distinct titles (stub + process-hardening — both in same REWRITE findings doc)
INF45  — 3 distinct titles (extend parity heading + Phase 0 log + mig-09 finding)
INF47  — 2 distinct titles (CI wiring heading + Phase 0 log)
int-01, sec-01..sec-06, sec-08 — all ≥2 titles across Phase-0/Phase-1/prompt/log variants
```

**Summary.** Script scanned 135 markdown files and found 123 distinct ticket numbers. Two categories of findings:

- **True ID reuse (violates retire-forever rule, `aab73d2`):** `DM3` and `DM6` have two entirely different titles in `docs/findings/dm-open-surface-2026-04-22.md` (L152–153). Needs triage by Serge — likely a copy-paste artifact in a scratch findings doc. The recently-closed session reused `INF40` for two unrelated tickets (L3 surrogate row-ID closed 2026-04-22; sync_staging CTAS closed 2026-04-23) — the ROADMAP's closed-items-log disambiguates via `INF40 (entity-CTAS)` label but this still violates the hygiene rule codified in PR #131.
- **Benign phase-variant collisions (not true reuse):** `INF25`, `INF39`, `INF41`, `INF45`, `INF47`, `int-01`, `sec-01`..`sec-08` all show ≥2 "distinct titles" because the same ticket has a Phase 0 finding, a Phase 1 prompt, and a session-log entry with slightly different heading text. These are expected by the Phase-0/Phase-1 workflow and not drift.
- **Gap discipline:** INF gaps at `2,5,6,7,8,10,12,13,14,15,16,17,18,19,20,21,22,24,27,32,33,34,35,36,43,44` is extensive — many are closed items now only referenced in the frozen `### Closed items (log)` section and are intentionally reserved per the allocation-policy note at ROADMAP.md L563–569.

Recommend raising `DM3`/`DM6` duplicate-title case with Serge; the INF40 re-issue is a policy gap that PR #131 now forbids going forward.

---

## Citations index (for drift claims)

- ROADMAP.md L575 (INF25), L580 (INF37 closed), L584 (43e), L588 (item 56), L599 (INF9f), L600 (INF40 entity-CTAS), L601 (INF9), L866 (Phase 2 + Wave 2 close)
- docs/REMEDIATION_PLAN.md L54 (int-18 STANDING), L55 (int-19 DEFERRED), L131 (mig-12 CLOSED), L208 (ops-18 BLOCKED), L445 (mig-05 SUPERSEDED), L446 (ops-18 AMBIGUOUS)
- docs/REMEDIATION_CHECKLIST.md L39 (int-18 `[ ]`), L42 (int-19 `[ ]`), L98 (mig-05 `[ ]`), L101 (mig-12 `[ ]`), L156 (ops-18 `[ ]`)
- docs/DEFERRED_FOLLOWUPS.md L13–20 (Open items table)
- docs/NEXT_SESSION_CONTEXT.md L8 (INF37 cleared), L17–22 (next items + recent closures), L65–73 (Post-Phase 2 carry-forward)
- Commits: `6c14c35` (entity-curation-w1 → INF37), `c154dcb` (inf40-fix), `5c41f7e` (inf9f-agincourt), PR #120 (inf9-persist), PR #119 (int-23-impl), `b0baebe` (Phase 2 + Wave 2 close per ROADMAP last-updated banner)
- Closure files: `docs/findings/entity-curation-w1-log.md`, `docs/findings/inf9-closure.md`, `docs/findings/int-23-design.md`, `docs/findings/int-22-p0-findings.md`
# §5 Session-Log Cross-Check

46 findings docs, 1 closures doc (README only — `docs/closures/` has the README scaffold, no per-session entries yet), 1 closed/resolved proposal, 9 reports; 0 archive candidates, 2 tracker-drift, 1 orphan follow-ups.

_Cross-cutting notes:_
- Today is 2026-04-23. No finding or report is older than 5 days — **zero "stale >30 days" candidates**.
- `docs/closures/README.md` is a scaffold documenting the per-session closure convention (Pattern B landed 2026-04-23 in PR #129 `de5b3fd`); the directory currently contains no per-session entries, so there is no closure-vs-finding redundancy to report.
- `archive/docs/closed/DOC_UPDATE_PROPOSAL_20260418_RESOLVED.md` is a formal retroactive resolution of the Phase 0 doc-update proposal; status `closed-and-tracker-updated` (verified via §4).

---

## §5 Master findings table

Legend: `C+T` = closed-and-tracker-updated · `C−T` = closed-no-tracker-update · `AI` = active investigation · `I` = informational · `O` = obsolete. `N/A-scaffold` = directory scaffold, not a finding.

| Path | Date | Subject | Purpose (1 line) | Status | Matches tracker? |
|---|---|---|---|---|---|
| docs/findings/dm-open-surface-2026-04-22.md | 2026-04-22 | DM1..DM15 worldview surface | Read-only re-audit of DM worldview state against prod for Tier-2 scoping | I | Mostly: DM1..DM14 all Done. **Orphan follow-up — introduces DM3/DM6 reuse flag** (§5.b) |
| docs/findings/entity-curation-w1-log.md | 2026-04-23 | INF37 + int-21 SELF + 43e | Session log batch-closing INF37 (+int-21 SELF-fallback, +43e de-scope) | C+T (for INF37 + int-21) | **Partial drift — §5.a** (REMEDIATION_CHECKLIST:39 still `[ ]` for int-18/INF37; `43e` RE-SCOPED not yet reflected in ROADMAP 43e row) |
| docs/findings/inf9-closure.md | 2026-04-23 | INF9 Route A overrides | Verify + persist 2026-04-10 Route A overrides to entity_overrides_persistent | C+T | ✓ (PR #120, ROADMAP.md:601) |
| docs/findings/int-01-p0-findings.md | 2026-04-21 | int-01 / RC1 OpenFIGI | Phase 0 Findings: RC1 foreign-exchange ticker filter — code landed in bcc5867, sweep required | C+T | ✓ (PLAN:37 CLOSED, CHECKLIST:8 `[x]`) |
| docs/findings/int-02-p0-findings.md | 2026-04-21 | int-02 / RC2 mode aggregator | Phase 0: RC2 mode aggregator shipped in fc2bbbc; Option A accept 8,178-row MAX-era residual | C+T | ✓ (PLAN:38, CHECKLIST:15) |
| docs/findings/int-04-p0-findings.md | 2026-04-21 | int-04 / RC4 issuer_name | Phase 0: RC4 half-shipped (normalize_securities fixed; build_cusip parallel SECURITIES_UPDATE_SQL not) | C+T | ✓ (CHECKLIST:9 `[x]`, PRs #18/#22) |
| docs/findings/int-05-p0-findings.md | 2026-04-21 | int-05 / Pass C sweep | Phase 0: retroactive sweep already run — close as NO-OP | C+T | ✓ (CHECKLIST:10 `[x]`) |
| docs/findings/int-06-p0-findings.md | 2026-04-22 | int-06 / hooks | Phase 0: forward-looking hooks shipped via BLOCK-TICKER-BACKFILL 3299a9f — close as NO-OP | C+T | ✓ (CHECKLIST:16 `[x]`) |
| docs/findings/int-07-p0-findings.md | 2026-04-22 | int-07 / benchmark_weights gate | Phase 0: all 3 gates PASS on benchmark_weights — close int-07, unblock int-09 | C+T | ✓ (CHECKLIST:20 `[x]`) |
| docs/findings/int-09-p0-findings.md | 2026-04-22 | int-09 / INF25 Step 4 | Phase 0: defer Step 4 BLOCK-DENORM-RETIREMENT to Phase 2 (docs-only Phase 1) | C+T (deferred) | ✓ (INF25 unblocked per ROADMAP:575; CHECKLIST:27 `[x]`) |
| docs/findings/int-10-p0-findings.md | 2026-04-21 | int-10 / INF26 | Phase 0: `_update_error()` permanent-pending bug; 81-row staging sweep needed | C+T | ✓ (PRs #42/#44; CHECKLIST:11 `[x]`) |
| docs/findings/int-12-p0-findings.md | 2026-04-22 | int-12 / INF28 PK | Phase 0: data ready; slot 011 free; proceed with 011_securities_cusip_pk.py | C+T | ✓ (CHECKLIST:28 `[x]`, PRs #92/#95) |
| docs/findings/int-13-p0-findings.md | 2026-04-22 | int-13 / INF29 is_otc | Phase 0: 850-CUSIP `is_otc` candidate set, Rule A∪B design | C+T | ✓ (CHECKLIST:34 `[x]`, PRs #94/#97) |
| docs/findings/int-14-p0-findings.md | 2026-04-22 | int-14 / INF30 NULL-only merge | Phase 0: merge_staging supports only 2 semantics; design for --mode null-only | C+T | ✓ (CHECKLIST:21 `[x]`, PRs #81/#85) |
| docs/findings/int-15-p0-findings.md | 2026-04-22 | int-15 / INF31 fetch_date | Phase 0: one SUSPECT writer (refetch_missing_sectors.py) — propose fetch_date/metadata_date stamp fix | C+T | ✓ (CHECKLIST:22 `[x]`, PRs #88/#90) |
| docs/findings/int-20-p0-findings.md | 2026-04-22 | int-20 / D-03 orphans | Phase 0: auto-resolved for build_summaries read-path — close | C+T | ✓ (CHECKLIST:30 `[x]`) |
| docs/findings/int-22-p0-findings.md | 2026-04-22 | int-22 / prod is_latest inversion | Phase 0: diagnose + staging proof + rollback wrapper design | C+T | ✓ (NEXT_SESSION_CONTEXT:14 closed; §4 master table confirms) |
| docs/findings/int-23-design.md | 2026-04-23 | int-23 loader idempotency | Design-only doc for Option (a): promote-step refuses flip on NULL downgrade | C+T | ✓ (DEFERRED_FOLLOWUPS L20 closed; PR #119) |
| docs/findings/int-23-p0-findings.md | 2026-04-22 | int-23-p0 universe expansion | Phase 0: 430K universe already live — close as already-done | C+T | ✓ (CHECKLIST:12 `[x]`) |
| docs/findings/mig-01-p0-findings.md | 2026-04-21 | mig-01 / BLOCK-2 | Phase 0: atomic promotes + `mirror_manifest_and_impacts` helper design | C+T | ✓ (CHECKLIST:78 `[x]`, PRs #31/#33) |
| docs/findings/mig-02-p0-findings.md | 2026-04-21 | mig-02 / MAJOR-14 | Phase 0: fetch_adv.py staging split → new promote_adv.py module | C+T | ✓ (CHECKLIST:79 `[x]`, PRs #35/#37) |
| docs/findings/mig-03-p0-findings.md | 2026-04-21 | mig-03 / MAJOR-15 | Phase 0: migration 004 atomicity retrofit (BEGIN/COMMIT + shadow) | C+T | ✓ (CHECKLIST:83 `[x]`, PRs #60/#62) |
| docs/findings/mig-04-p0-findings.md | 2026-04-21 | mig-04 / S-02 schema_versions | Phase 0: stamp-hole across 10 migrations; propose VERSION constant + stamp | C+T | ✓ (CHECKLIST:80 `[x]`, PRs #26/#29) |
| docs/findings/mig-06-p0-findings.md | 2026-04-22 | mig-06 / INF40 L3 surrogate | Phase 0: IDENTITY probe + runtime benchmark; recommend migration 014 | C+T | ✓ (CHECKLIST:88 `[x]`, PRs #103/#104). **Note: INF40 ticket-number reuse flagged in §4.b** |
| docs/findings/mig-08-p0-findings.md | 2026-04-22 | mig-08 / INF42 hygiene | Phase 0: .gitignore + fixture + dist rebuild enforcement proposal | C+T | ✓ (CHECKLIST:94 `[x]`, PRs #84/#86) |
| docs/findings/mig-09-p0-findings.md | 2026-04-22 | mig-09 / INF45 L4 parity | Phase 0: L4_TABLES extension design for schema-parity validator | C+T | ✓ (CHECKLIST:89 `[x]`, PRs #72/#74) |
| docs/findings/mig-11-p0-findings.md | 2026-04-22 | mig-11 / INF47 CI wiring | Phase 0: smoke.yml pytest scope widening + pyyaml pin | C+T | ✓ (CHECKLIST:95 `[x]`, PR #80) |
| docs/findings/mig-13-p0-findings.md | 2026-04-21 | mig-13 REWRITE tail | Phase 0: pipeline-violations tail — build_entities + merge_staging only | C+T | ✓ (CHECKLIST:84 `[x]`, PRs #61/#63) |
| docs/findings/mig-14-p0-findings.md | 2026-04-22 | mig-14 / build_managers | Phase 0: already-satisfied — close with no code change | C+T | ✓ (CHECKLIST:85 `[x]`, PR #68) |
| docs/findings/obs-01-p0-findings.md | 2026-04-21 | obs-01 / D-07 P-05 | Phase 0: N-CEN + ADV manifest registration design | C+T | ✓ (CHECKLIST:49 `[x]`, PRs #20/#25) |
| docs/findings/obs-02-p0-findings.md | 2026-04-21 | obs-02 / P-02 | Phase 0: ADV freshness + log discipline — process gap not code | C+T | ✓ (CHECKLIST:53 `[x]`, PRs #28/#30) |
| docs/findings/obs-03-p0-findings.md | 2026-04-20 | obs-03 / P-04 | Phase 0: market impact_id allocator hardening (2 call sites) | C+T | ✓ (CHECKLIST:50 `[x]`, PRs #8/#12) |
| docs/findings/obs-04-p0-findings.md | 2026-04-21 | obs-04 / D-06 13DG backfill | Phase 0: grain reframed to coverage; 51,902-row backfill needed | C+T | ✓ (CHECKLIST:54 `[x]`, PRs #36/#38) |
| docs/findings/obs-07-p0-findings.md | 2026-04-21 | obs-07 / P-07 leak gate | Phase 0: future-dated report_month gate — no contamination, preemptive | C+T | ✓ (CHECKLIST:58 `[x]`, PRs #51/#53) |
| docs/findings/obs-08-p1-findings.md | 2026-04-21 | obs-08 / O-05 backup | Phase 1: backup infra fully in place — no gap, wording/retention fixes only | C+T | ✓ (CHECKLIST:62 `[x]`, PR #58) |
| docs/findings/obs-13-verify-findings.md | 2026-04-21 | obs-13 / DIAG-23 | Verify dist bundle post-ff1ff71 clean of pct_of_float — PASS | C+T | ✓ (CHECKLIST:71 `[x]`, PR #65) |
| docs/findings/ops-17-p1-findings.md | 2026-04-21 | ops-17 | Single-session verify: already-satisfied by obs-10 (b5c04aa) | C+T | ✓ (CHECKLIST:155 `[x]`, PR #55) |
| docs/findings/ops-batch-5A-p0-findings.md | 2026-04-20 | ops-batch-5A | Doc-hygiene sweep (DOC-0x + R-0x) — ops-02..ops-12 fact-checks | C+T | ✓ (CHECKLIST:131–140 all `[x]`, PR #6) |
| docs/findings/ops-batch-5B-findings.md | 2026-04-21 | ops-batch-5B | Doc updates for ops-06/ops-09/ops-15 | C+T | ✓ (CHECKLIST:143–145 all `[x]`, PR #32) |
| docs/findings/phantom-other-managers-decision.md | 2026-04-23 | REWRITE_LOAD_13F §6.4 / other_managers | Retroactive Option A decision record; writer already present at HEAD | C+T | ✓ (PR #125 5e0078c; REMEDIATION_PLAN:403 stale entry cleaned) |
| docs/findings/sec-01-p0-findings.md | 2026-04-20 | sec-01 / D-11 | Phase 0: admin token localStorage → server-side session | C+T | ✓ (CHECKLIST:108 `[x]`) |
| docs/findings/sec-02-p0-findings.md | 2026-04-20 | sec-02 / C-11 | Phase 0: admin `/run_script` TOCTOU race analysis | C+T | ✓ (CHECKLIST:109 `[x]`) |
| docs/findings/sec-03-p0-findings.md | 2026-04-21 | sec-03 / C-09 | Phase 0: admin endpoint write-surface audit | C+T | ✓ (CHECKLIST:112 `[x]`) |
| docs/findings/sec-04-p0-findings.md | 2026-04-21 | sec-04 / C-02 | Phase 0: validators writing to prod — scope + fix plan | C+T | ✓ (CHECKLIST:113 `[x]`) |
| docs/findings/sec-05-p0-findings.md | 2026-04-21 | sec-05 / C-04 | Phase 0: hardcoded-prod builders bypass staging (build_fund_classes, build_benchmark_weights) | C+T | ✓ (CHECKLIST:116 `[x]`) |
| docs/findings/sec-06-p0-findings.md | 2026-04-21 | sec-06 / C-05 | Phase 0: 5 direct-to-prod writers inventory (resolve_*, backfill_*) | C+T | ✓ (CHECKLIST:117 `[x]`) |
| docs/findings/sec-08-p0-findings.md | 2026-04-21 | sec-08 / O-08 | Phase 0: central EDGAR identity config across 19 scripts | C+T | ✓ (CHECKLIST:121 `[x]`) |
| archive/docs/closed/DOC_UPDATE_PROPOSAL_20260418_RESOLVED.md | 2026-04-23 | doc-update proposal (7 items) | Retroactive resolution log for BLOCK-SECURITIES/BLOCK-TICKER/BLOCK-3 doc updates | C+T | ✓ (all 7 sub-items tracked in ROADMAP INF25–INF29 + MAINTENANCE.md) |
| docs/closures/README.md | 2026-04-23 | Pattern B scaffold | Convention doc for per-session closure files (Pattern B, PR #129) | I (scaffold) | N/A — scaffold |
| archive/docs/reports/block3_phase2_rerun_20260418_193735.md | 2026-04-18 | BLOCK-3 Phase 2 rerun | Staging rerun post-is_priceable; all 3 gates PASS | C+T | ✓ (BLOCK-3 closed, prod applied 2026-04-18) |
| archive/docs/reports/block3_phase4_prod_apply_20260418_201319.md | 2026-04-18 | BLOCK-3 Phase 4 prod | Prod apply report; all gates PASS on prod | C+T | ✓ |
| archive/docs/reports/block_sector_coverage_closeout_20260419_052804.md | 2026-04-19 | block_sector_coverage | Closeout: 3,287-ticker sweep; flags upsert-mode gap (→ INF30/int-14) + silent writer (→ INF31/int-15) | C+T | ✓ (findings escalated to int-14 + int-15, both closed) |
| archive/docs/reports/block_securities_audit_phase2_20260418_105033.md | 2026-04-18 | BLOCK-SECURITIES-AUDIT Phase 2 | Gate-mixed: RC2 works but raw counts fail → drives Phase 2b | C+T | ✓ (superseded by Phase 2b + int-01..int-04 closures) |
| archive/docs/reports/block_securities_audit_phase2b_20260418_155554.md | 2026-04-18 | BLOCK-SECURITIES-AUDIT Phase 2b | Path A + drain: gates still mixed; 216 residual accepted | C+T | ✓ |
| archive/docs/reports/block_ticker_backfill_closeout_20260418_205753.md | 2026-04-18 | BLOCK-TICKER-BACKFILL | Closeout: forward-looking hooks shipped; retroactive backfill absorbed into BLOCK-3 | C+T | ✓ |
| archive/docs/reports/rewrite_build_managers_phase2_20260419_082630.md | 2026-04-19 | build_managers rewrite | Phase 2 staging validation; Risk 1 = 59.9% manager_type coverage → downstream INF37 | C+T | ✓ (Risk 1 → INF37, now closed by entity-curation-w1 2026-04-23) |
| archive/docs/reports/rewrite_build_shares_history_phase2_20260419_054947.md | 2026-04-19 | build_shares_history rewrite | Phase 2 staging validation; gates PASS | C+T | ✓ |
| archive/docs/reports/rewrite_load_13f_phase2_20260419_071500.md | 2026-04-19 | load_13f rewrite | Phase 2 staging validation; gates PASS; OTHERMANAGER2 loader materializes other_managers | C+T | ✓ (phantom-other-managers-decision 2026-04-23 confirms) |

---

## §5.a Closure/tracker drift — findings say closed, tracker says open

Two drift rows (both also surfaced in §4 master table and by `scripts/audit_tracker_staleness.py`). All findings in this audit post-date 2026-04-18 so none exceed the 30-day window; the drift is purely tracker-hygiene lag.

| Finding / closure evidence | Tracker row still open | Gap | Recommended |
|---|---|---|---|
| `docs/findings/entity-curation-w1-log.md` (2026-04-23, commit `6c14c35`) declares INF37 APPLIED to prod with 0 residuals; ROADMAP.md:580 also marks CLEARED 2026-04-23 | `docs/REMEDIATION_CHECKLIST.md:39` still carries `- [ ] int-18 INF37 backfill_manager_types residual 9 entities (no closure expected)` | Stale checkbox | Flip `[ ]` → `[x]` + note "CLEARED 2026-04-23 (entity-curation-w1)" |
| Section §4 identifies `mig-12` closed in ROADMAP.md:866 + PLAN:131 + NEXT_SESSION_CONTEXT.md:73 (**no dedicated findings doc — absorbed into p2-05 `load_13f_v2.py`**) | `docs/REMEDIATION_CHECKLIST.md:101` still `- [ ] mig-12 load_13f_v2 rewrite (fetch_13f.py + promote_13f.py + build_managers reader)` | Stale checkbox | Flip `[ ]` → `[x]` + note "absorbed by p2-05" |

Additional (from §4, not findings-driven): `docs/REMEDIATION_CHECKLIST.md:98` `- [ ] mig-05 BLOCK-4 admin refresh pre-restart rework (BLOCKED — upstream design doc missing)` is stale — PLAN:445 marks it SUPERSEDED and the referenced design doc was recovered at `03db9ad`. No findings file exists for mig-05; this drift is tracker-internal only.

---

## §5.b Findings with orphan follow-ups (introduces a tracked item not yet in any tracker)

One clear case. (Note: "orphan follow-up" here means the finding references an ID or action that has not been captured in ROADMAP / PLAN / CHECKLIST / DEFERRED_FOLLOWUPS / NEXT_SESSION_CONTEXT.)

| Finding | New follow-up | Tracker status |
|---|---|---|
| `docs/findings/dm-open-surface-2026-04-22.md` — the "Residual DM open surface" section lists fresh scoping items for the DM track, and §4.b flagged two distinct titles inside this file sharing the labels `DM3` and `DM6` (duplicate headings at L152–153) | The **duplicate-title collision on DM3 / DM6** inside the same file is not yet tracked anywhere — there is no ROADMAP row, plan row, checklist row, or next-session-context row capturing "retire duplicate DM3/DM6 labels per retire-forever rule (`aab73d2` hygiene-ticket-numbering)" | **Orphan** — not visible in any tracker. Recommend: add a one-line NEXT_SESSION_CONTEXT row or open a fresh `dm-taxonomy-hygiene` ticket. |

Borderline candidates that are **not** orphans (already landed in the right place):
- `entity-curation-w1-log.md` "43e de-scoped": surfaced as a **DE-SCOPE** row in ROADMAP.md:584 (`43e RE-SCOPED`) and NEXT_SESSION_CONTEXT.md:17 — tracked.
- `phantom-other-managers-decision.md` cleanup note for `REMEDIATION_PLAN.md:403` — already cleaned in PR #125 per doc text.
- `mig-06-p0-findings.md` INF40 reuse — identified in §4.b but is a *meta-hygiene* finding, not a new tracked item; the hygiene-ticket-numbering rule (PR #131) is the standing mechanism.

---

## §5.c Archive candidates (findings stale >30 days AND subject is closed in trackers)

**None.** The oldest finding in scope (`obs-03-p0-findings.md`, 2026-04-20) is 3 days old as of 2026-04-23. No archive action required this cycle.

| Threshold | Count |
|---|---|
| Findings older than 30 days | 0 |
| Findings older than 14 days | 0 |
| Findings older than 7 days | 0 |
| Newest finding (2026-04-23) | 4 (entity-curation-w1-log, inf9-closure, int-23-design, phantom-other-managers-decision) |

Re-run this section after the next quarterly program cycle (earliest archive candidates would fall out around 2026-05-20).

---

## Citations index (for drift claims in §5.a / §5.b)

- `docs/findings/entity-curation-w1-log.md` lines 32–42 (INF37 APPLIED / 14,368 → 0 residuals) — commit `6c14c35`
- `docs/REMEDIATION_CHECKLIST.md:39` (stale `- [ ]` for int-18/INF37)
- `docs/REMEDIATION_CHECKLIST.md:101` (stale `- [ ]` for mig-12)
- `docs/REMEDIATION_CHECKLIST.md:98` (stale `- [ ]` for mig-05 — non-finding-driven, see §4)
- `docs/findings/dm-open-surface-2026-04-22.md` lines 152–153 (DM3 / DM6 duplicate-title headings) — per §4.b audit_ticket_numbers.py output
- `ROADMAP.md:580` (INF37 CLEARED 2026-04-23), `:601` (INF9), `:599` (INF9f), `:866` (Phase 2 close), `:584` (43e RE-SCOPED)
- `docs/NEXT_SESSION_CONTEXT.md:8` (INF37 cleared), `:14` (int-22 closed), `:17` (43e re-scoped)
- `docs/REMEDIATION_PLAN.md:131` (mig-12 CLOSED), `:445` (mig-05 SUPERSEDED)

---

Wrote section5_sessions.md, archive=0 drift=2 orphan=1
# §6 Architectural / Schema Consistency

Cross-checks: (A) `docs/canonical_ddl.md` vs prod DB schema; (B)
`docs/data_layers.md` vs prod; (C) `docs/pipeline_inventory.md` vs
`scripts/pipeline/` framework; (D) sampled violations still live.

Sources:
- DB tables: `/tmp/audit_sections/_db_active.json` (57 active tables, 2 views)
- Docs: `docs/canonical_ddl.md` (485 ln), `docs/data_layers.md` (963 ln),
  `docs/pipeline_inventory.md` (234 ln), `docs/pipeline_violations.md` (625 ln)

---

## §6.a Canonical DDL divergence (`docs/canonical_ddl.md`)

The doc enumerates 42 tables in its summary table (lines 22–54). All 42
are present in DB (overlap = 42; doc_only = 0). **15 active prod tables
are not mentioned in `canonical_ddl.md`** (doc is explicitly scoped to
"L3 canonical" + the L0 control plane + CUSIP vertical, so L4 derived
tables are out-of-scope by design — flag below as doc-scope gap, not
drift).

| Table | Direction | Detail |
|-------|-----------|--------|
| `fund_holdings` | DB-only | Doc (`canonical_ddl.md:144`, `:153`) states fetch_nport writes to "dropped `fund_holdings`" — but DB still has `fund_holdings` (22,030 rows, last write 2026-04-14). Stage-5 drop claim is stale. |
| `beneficial_ownership_current` | DB-only | L4 derived; not in L3 DDL doc scope, but doc could flag as sibling. |
| `admin_sessions` | DB-only | No DDL doc entry. Not in `canonical_ddl.md` migration history. |
| `admin_preferences` | DB-only | Mentioned in `data_layers.md:140` (migration 016) but not in `canonical_ddl.md` summary table — doc stops at migration 014. |
| `fund_classes`, `fund_best_index`, `fund_index_scores`, `fund_name_map`, `index_proxies`, `fund_family_patterns`, `benchmark_weights`, `peer_groups` (8 L4 tables) | DB-only | Out of `canonical_ddl.md` declared scope (L3/L0 only). Doc never states this carve-out explicitly. |
| `fund_classification` | DB-only | `data_layers.md:142` flags RETIRE; `canonical_ddl.md` silent. |
| `entity_identifiers_staging`, `entity_relationships_staging` | DB-only | Staging-only; not in `canonical_ddl.md`. |
| `holdings_v2`, `fund_holdings_v2`, `beneficial_ownership_v2` | Column drift | Doc says 33/26/22 cols respectively; DB reports 30/30/28 (`_db_active.json`). Counts don't match because doc reflects pre-migration-015 shape (`canonical_ddl.md:76-79, :123-131, :170-178` show the schemas without migration-015 `is_latest`/`loaded_at`/`backfill_quality` + migration-014 `row_id`). `data_layers.md:91-93` acknowledges migration 015 but `canonical_ddl.md` body text is not updated. |
| `holdings_v2.pct_of_float` vs `pct_of_so` | Renamed | Migration 008 live (canonical_ddl.md:439); doc body still has dual references (`:82`, `:102`, `:259`). |

---

## §6.b `docs/data_layers.md` divergence

`data_layers.md` Section 2 inventory (lines 86–151) lists 57 rows
(inclusive of the `positions`/`fund_classification` RETIRE rows +
`entity_current` VIEW). Cross-check:

| Item | Direction | Detail |
|------|-----------|--------|
| `positions` | Doc-only | `data_layers.md:141` lists as RETIRE / 18.68M rows; **not present in prod** (`_db_active.json`). Delete already happened; doc not updated. |
| `admin_sessions` | DB-only | 9 rows in DB; absent from `data_layers.md` inventory. |
| `fund_holdings` (legacy) | DB-only | 22,030 rows in DB, last_write 2026-04-14; `data_layers.md` omits it (treated as dropped). Consistent with `canonical_ddl.md` stale claim — layer still live. |
| `_snapshot_*` tables | Doc scope | `data_layers.md:143-151` lists snapshot groupings but doesn't enumerate; `_db_active.json` "active" scope excludes snapshots so no row-level divergence visible. |
| v2 tables | Match | `holdings_v2` 12.27M (`:91`), `fund_holdings_v2` 14.09M (`:92`), `beneficial_ownership_v2` 51,905 (`:93`) all match DB. |

---

## §6.c `docs/pipeline_inventory.md` divergence (`scripts/pipeline/`)

Doc claims Wave 2 shipped 5 new `SourcePipeline` subclasses
(`pipeline_inventory.md:4-8`) + `base.py` + `cadence.py`. All present.
Also lists retired scripts under `scripts/retired/`; all present.

| Item | Direction | Detail |
|------|-----------|--------|
| `scripts/pipeline/protocol.py` | Pipeline dir, not doc | Exists; not mentioned in `pipeline_inventory.md`. |
| `scripts/pipeline/discover.py` | Pipeline dir, not doc | Exists; no row in the inventory table. |
| `scripts/pipeline/id_allocator.py` | Pipeline dir, not doc | Exists; not documented. |
| `scripts/pipeline/cusip_classifier.py` | Pipeline dir, not doc | Exists; not in inventory. |
| `scripts/retired/build_cusip_legacy.py` | Retired, not retired-section | Exists at `scripts/retired/`; referenced narratively (e.g., `pipeline_inventory.md:93`) but no retired-block row. |
| `scripts/retired/unify_positions.py` | Retired, partial mention | `pipeline_inventory.md:140` lists `unify_positions.py` under RETIRE but retired copy is in `scripts/retired/`; no "moved" annotation. |
| `validate_nport.py` / `validate_nport_subset.py` / `promote_nport.py` / `promote_13dg.py` / `validate_13dg.py` rows (`pipeline_inventory.md:98-101`) | Stale row vs retired | Inventory table still has active-script rows (OK) for scripts that now live **only** in `scripts/retired/`. Rows not marked RETIRED. |
| `load_13f.py` (top-level, legacy) | Still-at-toplevel | `pipeline_inventory.md:89` flags SUPERSEDED; file still at `scripts/load_13f.py` (not moved to `scripts/retired/`). Matches doc plan but dead code still ships. |

Top-level `scripts/` retains many scripts outside the SourcePipeline
framework (`dm14_layer1_apply.py`, `inf23_apply.py`, etc.) — doc
`§Cross-cutting findings` covers these; no divergence.

---

## §6.d Pipeline-violations sampling (top 3 from `pipeline_violations.md`)

| Doc claim | File:line in doc | Current state (grep-confirmed) |
|-----------|------------------|--------------------------------|
| `fetch_nport.py` §1/§2/§9 violations | `pipeline_violations.md:65-90` | **CLEARED** — file now at `scripts/retired/fetch_nport.py`; doc header (`:65`) already says SUPERSEDED. |
| `fetch_13dg.py` §1/§4/§5b/§9 + legacy `beneficial_ownership` refs | `:94-118` | **CLEARED** — file now at `scripts/retired/fetch_13dg.py`; `fetch_13dg.py` grep match confirms legacy refs survive only in the retired copy. |
| `fetch_adv.py` §1/§5/§9 | `:122-133` | **CLEARED** — file at `scripts/retired/fetch_adv.py`; replaced by `scripts/pipeline/load_adv.py` (w2-05). |
| `fetch_finra_short.py` §9 (`--dry-run` missing) | `:159-160` | **STILL LIVE** — grep on `scripts/fetch_finra_short.py` returns 0 hits for `--dry-run` / `--apply` / `dry_run`. `--test` still writes. |
| `build_shares_history.py` §1/§9 + `holdings` ALTER/UPDATE | `inventory:114` | **CLEARED** — file rewritten, `--dry-run` flag + `CHECKPOINT_EVERY_N_BATCHES=10` present (`build_shares_history.py:24`, `:91-128`); 0 grep hits on `ALTER holdings`/`UPDATE holdings`. |

---

## One-line summary

divergences-canonical=**10** (1 stale "dropped" `fund_holdings`, 8 L4 tables out of doc scope, 3 v2 column-count mismatches post-migration-015), divergences-layers=**3** (`positions` ghost doc row, `admin_sessions` missing, `fund_holdings` stale), divergences-pipelines=**7** (4 undocumented `scripts/pipeline/*` modules + 3 retired/stale-row markers).
# §7 Stale / Orphan Candidate Lists (Synthesis)

Input for Phase B (filesystem reorg) and Phase C (doc consolidation). **Candidates only** — no action taken in this session.

---

## §7.a Docs candidate for archive

**0 candidates under the strict criterion** (not touched in 60+ days AND zero inbound references). The repo-wide doc churn is recent (heaviest commits 2026-04-17 → 2026-04-23); every doc older than 60 days has already been pruned.

**Softer criterion — zero inbound references** (may still be useful or may be candidate depending on purpose):

| Path | Last modified | Refs IN | Evidence |
|---|---|---:|---|
| `data/reference/ROLLUP_COVERAGE_REPORT.md` | 2026-04-08 | 0 | §1 row 20 — historical phase-4 status snapshot |
| `docs/POST_MERGE_REGRESSIONS_DIAGNOSTIC.md` | 2026-04-19 | 0 | §1 row 31 — post-merge diag; issues resolved per ROADMAP |

**Recommendation:** Leave for now; re-run this pass after the next quarterly cycle (earliest true archive date ≈ 2026-05-20 per §5.c).

---

## §7.b Scripts candidate for retirement

**⚠️ Pass 2's "77 unused" count is inflated.** The agent classified a script as unused if no other file imports it or invokes it via `subprocess`. That misses three legitimate categories:

| False-positive category | Count in "77" | Why not a retire candidate |
|---|---:|---|
| `scripts/migrations/*.py` | 15 | Applied-once schema migrations; must stay for history + replayability |
| `scripts/oneoff/*.py` | 10 | Historical one-shot ops scripts; kept as audit trail (prior hygiene decisions archived rather than deleted) |
| CLI-only tools invoked as `python3 scripts/X.py` | ~12 | e.g. `audit_ticket_numbers.py`, `audit_tracker_staleness.py` (both ran in this session), `sync_staging.py` (staging workflow per project memory), `scheduler.py`, `concat_closed_log.py`, `cleanup_merged_worktree.sh`, `bootstrap_worktree.sh`, `start_app.sh`, `rotate_logs.sh`, `backup_db.py`, `check_freshness.py`, `rollback_run.py` |
| `scripts/pipeline/registry.py`, `id_allocator.py`, `validate_schema_parity.py` | 3 | Pipeline framework; imported with dotted package paths the agent's heuristic didn't catch |
| DM-apply + INF-apply one-offs (dm14*, dm15*, inf23_apply, inf39_rebuild_staging) | 8 | Historical apply scripts for specific tickets |

**Narrowed real retire candidates (≈ Pass 2 count − above 48 false positives ≈ 29):** the remaining set centres on legacy resolver/reparse scripts and scripts whose logic has been absorbed by pipeline framework. Needs a second pass in Phase B with a per-file CLI-invocation check before any deletion.

High-confidence retire candidates (manual spot-check, all in §2.c):

| Path | Last mod | Evidence |
|---|---|---|
| `scripts/retired/*` (18 files) | 2026-04-22 | Already in `scripts/retired/`; keep one release cycle then consider archive/ |
| `scripts/snapshot_manager_type_legacy.py` | 2026-04-19 | Name literally contains "legacy" |
| `scripts/smoke_yahoo_client.py` | 2026-04-09 | Pre-pipeline smoke script; `pipeline/load_market.py` supersedes |
| `scripts/build_shares_history.py` | 2026-04-19 | `§6.d` notes rewrite landed; pipeline version may fully supersede — verify in Phase B |
| `scripts/load_13f_v2.py` | 2026-04-22 | Opposite — appears in retire list BUT is the active v2 loader per §3 writers (`holdings_v2`, `filings`). **Do NOT retire.** |

**Recommendation for Phase B:** re-run the Pass-2 classifier with (a) migrations/oneoff globbed out, (b) Makefile + docs/MAINTENANCE.md + shell-script bodies treated as callers, (c) dotted-path imports (`from scripts.pipeline.registry`) resolved. Expected residual ≈ 10–25 genuine candidates.

---

## §7.c Tables candidate for drop

From §3.b (orphans, no readers). Ordered by row-count impact.

| Table | Rows | Risk of drop | Reason |
|---|---:|---|---|
| `raw_infotable` | 13,540,608 | **HIGH** | Pre-v2 raw landing zone written by `scripts/load_13f.py`. May still be feeding `filings` / `holdings_v2` via a build step the grep missed, or may be dead since v2 loader landed. **Ask Serge** (§8.Q2). |
| `fund_name_map` | 6,229,495 | Medium | 6.2M rows, zero writers + zero readers. Stranded from an earlier build. |
| `raw_coverpage` | 43,358 | HIGH | Same story as `raw_infotable` — paired with `load_13f.py` raw pipeline. |
| `raw_submissions` | 43,358 | HIGH | Same as above. |
| `fund_classes` | 31,056 | Low | Written by `build_fund_classes.py`; no readers in current code. `data_layers.md:142` flags RETIRE. |
| `fund_index_scores` | 80,271 | Medium | No writers, no readers. Earlier fund→index similarity output. |
| `index_proxies` | 13,641 | Low | Lookup table, no readers. |
| `lei_reference` | 13,143 | Low | Written by `build_fund_classes.py`; no readers. |
| `fund_best_index` | 6,151 | Medium | Zero writers + zero readers. |
| `fund_classification` | 5,717 | Low | `data_layers.md:142` flags RETIRE. |
| `fetched_tickers_13dg` | 6,075 | Low | 13DG fetcher checkpoint; readers never found (may be pipeline-internal). |
| `other_managers` | 15,405 | Low | Written by both `load_13f.py` + `load_13f_v2.py`. No readers. Per `phantom-other-managers-decision.md` already confirmed retained for Option A. |
| `admin_sessions` | 9 | Very low | Active admin DB (writer = `admin_bp.py`). Reader likely hidden behind ORM string. **Do NOT drop.** |
| `admin_preferences` | 0 | Very low | Empty admin table, migration 016 created. Same caveat. |
| `entity_relationships_staging` | 0 | Very low | Empty staging twin. Safe to drop. |

Also flag: `fund_holdings` (22,030 rows) is **writer-retired**: only writer = `scripts/retired/fetch_nport.py`, reader = `scripts/queries.py` + `scripts/retired/unify_positions.py`. Docs (`canonical_ddl.md:144,153`, `data_layers.md:141`) already claim it's dropped — but prod has the table. **One of the two is wrong. Ask Serge (§8.Q1).**

Also: **292 `_snapshot_YYYYMMDD_HHMMSS` tables** (12 base tables × up to 33 copies). Not orphans in the strict sense but not documented anywhere. Phase B cleanup candidate.

---

## §7.d Tracker items candidate for close (shipped but not marked closed)

From §4 and §5.a. All three are stale unchecked `[ ]` in `REMEDIATION_CHECKLIST.md`.

| Item | Evidence | Recommended action |
|---|---|---|
| `int-18 / INF37` | `REMEDIATION_CHECKLIST.md:39` still `[ ]`; closed by `entity-curation-w1` (`6c14c35`, ROADMAP.md:580, NEXT_SESSION_CONTEXT.md:8) | Flip `[ ]` → `[x]` + note "CLEARED 2026-04-23" |
| `mig-12` | `REMEDIATION_CHECKLIST.md:101` still `[ ]`; closed in PLAN:131, ROADMAP.md:866, NEXT_SESSION_CONTEXT.md:73 (absorbed by p2-05) | Flip `[ ]` → `[x]` + note "absorbed by p2-05" |
| `mig-05` | `REMEDIATION_CHECKLIST.md:98` still `[ ]` with stale "BLOCKED — upstream design doc missing"; PLAN:445 marks SUPERSEDED, design doc recovered at `03db9ad` | Flip `[ ]` → `[x]` + note "SUPERSEDED by Phase 2" |

---

## §7.e Tracker items candidate for cleanup (closed but surfaced open)

Same 3 items as §7.d — the drift is always in `REMEDIATION_CHECKLIST.md`. No other tracker has closed-but-still-open rows.

Also: **INF40 ticket-number reuse** (see §4.b and §8.Q5). Both instances are closed in ROADMAP.md:600, but the reuse itself violates the `aab73d2` retire-forever hygiene rule and should be flagged for post-hoc disambiguation.

---

## §7.f Findings docs candidate for archive

**0 candidates this cycle.** All findings in scope post-date 2026-04-20 (3 days old). Per §5.c, earliest archive window opens ≈ 2026-05-20 (30-day threshold). Re-run this pass then.

---

## §7.g Documentation consolidation candidates (Phase C input)

Surfaced during Pass 1 / Pass 6 cross-reads; these are doc-level consolidation opportunities, not deletions:

| Proposal | Evidence | Tradeoff |
|---|---|---|
| Merge `docs/REMEDIATION_PLAN.md` (614 ln) + `docs/REMEDIATION_CHECKLIST.md` (156 ln) | 50 + 69 refs between them; item IDs overlap fully; drift always originates in CHECKLIST | Checklist is good for sprint-view; plan is good for narrative-view. Consolidating loses one lens. Ask Serge (§8.Q3). |
| Merge `docs/canonical_ddl.md` (485 ln) into `docs/data_layers.md` (963 ln) | `data_layers.md` is already the canonical reference per project memory; `canonical_ddl.md` lags post-migration-015 (§6.a) | Ask Serge (§8.Q4). |
| Retire `PHASE3_PROMPT.md` (8 refs) + `PHASE4_PROMPT.md` (6 refs, already marked SUPERSEDED) + `PHASE4_STATE.md` (3 refs) | Phase 3/4 closed months ago | Low-risk archive candidates; mentioned here for Phase C. |
| `docs/SYSTEM_ATLAS_2026_04_17.md` + `docs/SYSTEM_AUDIT_2026_04_17.md` + `docs/SYSTEM_PASS2_2026_04_17.md` (3 docs, same date, 1486 ln total) | Snapshot audit set from 2026-04-17 | Consolidate into single historical snapshot? (Phase C) |
# §8 Questions for Serge Decision

Each question surfaces a judgement call the audit cannot answer mechanically. Numbered for reference in subsequent sessions.

---

### Q1. `fund_holdings` table — drop or retain?

**Context.** §3.c flags `fund_holdings` as writer-retired: 22,030 rows, last write 2026-04-14, only writer = `scripts/retired/fetch_nport.py`, readers = `scripts/queries.py` (prod) + `scripts/retired/unify_positions.py`. Both `docs/canonical_ddl.md:144, :153` and `docs/data_layers.md:141` claim the table was dropped. DB says otherwise.

**Recommendation.** Confirm `scripts/queries.py` reader is dead; drop the table; update `canonical_ddl.md` and `data_layers.md` to reflect the actual state. **Phase B work.**

**Tradeoff.** Dropping is irreversible for the 22K rows; keeping is a lingering lie in two reference docs.

---

### Q2. `raw_infotable` + `raw_coverpage` + `raw_submissions` — still live or orphaned?

**Context.** §3.b flags 13,540,608 + 43,358 + 43,358 rows orphaned (zero readers). All three are written only by `scripts/load_13f.py`. The v2 loader `scripts/load_13f_v2.py` writes to `filings` / `holdings_v2` instead. If v2 is canonical and v1 is retired, these raw_* tables are ~13.6M dead rows and the legacy `load_13f.py` is a Phase B archive candidate.

**Recommendation.** Either (a) confirm v1 raw pipeline is the staging step for a downstream build that grep missed, and document it, or (b) retire `load_13f.py` and drop the raw_* trio in Phase B.

**Tradeoff.** Dropping 13.5M rows is irreversible; cost of keeping is DB size + analyst confusion.

---

### Q3. Merge `REMEDIATION_PLAN.md` + `REMEDIATION_CHECKLIST.md`?

**Context.** Plan = 614 lines, Checklist = 156 lines. IDs overlap fully; all 5 drift candidates surfaced in §4 live in CHECKLIST (nowhere else). The two docs track the same items in two different formats.

**Recommendation.** Option A: keep both, accept the drift, lean on the `audit_tracker_staleness.py` script to catch it. Option B: collapse into one doc with two views (table + checkbox column) and retire the other. Option C: retire CHECKLIST entirely now that the Remediation Program is marked COMPLETE (`7c49471`).

**Tradeoff.** Checklist is useful for sprint-view; Plan is narrative-view. Consolidating loses one lens; keeping both preserves drift risk.

---

### Q4. Merge `docs/canonical_ddl.md` into `docs/data_layers.md`?

**Context.** §6.a found `canonical_ddl.md` stale post-migration-015 (v2 column counts wrong) and scoped to L3+L0 only (L4 tables not covered). `data_layers.md` already covers all layers and is treated as canonical per project memory. Two docs, overlapping claims, one stale.

**Recommendation.** Fold `canonical_ddl.md` migration-history appendix into `data_layers.md` appendix; retire `canonical_ddl.md`.

**Tradeoff.** `canonical_ddl.md` has full CREATE-TABLE statements in one place; those are easier to diff against `information_schema`. Folding risks losing the single-place lookup.

---

### Q5. `INF40` and `DM3` / `DM6` ticket-number reuse — re-issue or annotate?

**Context.** §4.b flagged three ticket-number reuses that violate the `aab73d2` (PR #131) retire-forever hygiene rule:
- `INF40` (L3 surrogate row-ID, closed 2026-04-22) + `INF40 (entity-CTAS)` (sync_staging.py DDL rewrite, closed 2026-04-23) — both closed, disambiguated by parenthetical label.
- `DM3` and `DM6` have two distinct titles each inside `docs/findings/dm-open-surface-2026-04-22.md` L152–153.

**Recommendation.** Option A: re-issue the offending tickets under fresh IDs (strict hygiene). Option B: keep the parenthetical disambiguation for INF40 (already-closed, low cost) and re-issue only DM3/DM6 since they're in active surface. Option C: accept the debt and document as a known historic exception.

**Tradeoff.** Re-issuing rewrites ROADMAP and loses git-log-to-ticket correspondence; accepting the debt weakens the rule going forward.

---

### Q6. `fetch_finra_short.py --dry-run` gap — fix or accept?

**Context.** §6.d confirms the only live violation from `pipeline_violations.md` is `fetch_finra_short.py` missing `--dry-run` / `--apply` flags. All other top violations are cleared (files moved to `scripts/retired/`). Script still writes to `short_interest` (328,595 rows).

**Recommendation.** File a small ticket to add the `--dry-run` flag; closes the last P-gate.

**Tradeoff.** Small effort, closes the last open pipeline-violations doc item.

---

### Q7. 292 `_snapshot_YYYYMMDD_HHMMSS` tables — retain or roll off?

**Context.** §3 notes 292 historic snapshot tables (12 base tables × up to 33 copies). Not in any doc. Represent point-in-time audit copies of `entities`, `holdings_v2`, etc.

**Recommendation.** Define a retention policy (e.g., keep last N, roll off older). Phase B candidate.

**Tradeoff.** They are dead storage; they may also be the last safety net for rollback scenarios. Needs policy decision, not a one-off drop.

---

### Q8. `pipeline_inventory.md` — reflect 4 undocumented modules?

**Context.** §6.c lists `scripts/pipeline/protocol.py`, `discover.py`, `id_allocator.py`, `cusip_classifier.py` as present but not in the inventory. Small doc-maintenance item.

**Recommendation.** Add rows in Phase C doc sweep.

---

### Q9. Pass 2's 77-candidate inflation — re-run classifier with tighter rules?

**Context.** §7.b documents 48 false positives in Pass 2 (migrations, one-offs, CLI-only tools, dotted-path imports). True retire count is likely 10–25.

**Recommendation.** In Phase B, re-run a narrower classifier (exclude migrations/oneoff; add MAINTENANCE.md, docs/, .github/**, Makefile as callers; resolve dotted imports). Only then act on the residual.

---

### Q10. `data/reference/ROLLUP_COVERAGE_REPORT.md` + `POST_MERGE_REGRESSIONS_DIAGNOSTIC.md` — archive?

**Context.** §7.a found these as the only zero-inbound-ref docs outside the 60-day window. `ROLLUP_COVERAGE_REPORT.md` is a pre-Phase-4 status snapshot; `POST_MERGE_REGRESSIONS_DIAGNOSTIC.md` is a resolved-issue diagnostic.

**Recommendation.** Move to `archive/docs/closed/` or an archive/ subtree in Phase C.
# §9 Summary Counts

All figures are as-of HEAD `aab73d2` on branch `comprehensive-audit`, audit date 2026-04-23.

| Dimension | Total | Active | Candidate (retire/archive) | Already retired |
|---|---:|---:|---:|---:|
| Markdown docs | 138 | 136 | 2 (soft) / 0 (strict 60-day) | — |
| Scripts | 162 | 67 | ~10–25 (after Pass-2 false-positive filter) | 18 |
| DB tables | 57 | 41 | 15 (orphans) + 1 (writer-retired) | — |
| DB views | 2 | 2 | 0 | — |
| DB snapshot tables | 292 | — | policy decision pending (§8.Q7) | — |
| Tracker items (open) | 14 | 14 | — | — |
| Tracker items (drift) | 5 | — | 3 mechanical flip + 2 ID-hygiene | — |
| Findings / closures / reports docs | 57 | 57 | 0 this cycle | — |

## Drilldowns

**Drift candidates (5 total).** §4 master table.
- 3 mechanical flips in `docs/REMEDIATION_CHECKLIST.md`: int-18/INF37 (L39), mig-05 (L98), mig-12 (L101).
- 2 ticket-number reuse violations (PR #131 hygiene rule): INF40 (both closed), DM3/DM6 (in active surface doc).

**ID collisions surfaced by `audit_ticket_numbers.py`.** 9 rows:
- True reuse (3): DM3, DM6, INF40.
- Benign phase-variant collisions (6): INF25, INF39, INF41, INF45, INF47, int-01/sec-0x.

**Confirmed-open tracker items (no drift, carry into Phase B/C/next cycle).** 9 rows.
- `int-09 Step 4 / INF25`, `int-19 / INF38`, `ops-18`, `INF27`, `INF2` (recurring), `INF16`, `43g`, `43b`, `48` (partially done), `56`, `P2-FU-01`, `P2-FU-03`.

**Schema divergences (§6).** 20 total.
- 10 canonical_ddl.md drift (1 hard: stale `fund_holdings` "dropped" claim; 3 v2 column-count lags; 8 L4 tables out of declared scope but carve-out undocumented + renames).
- 3 data_layers.md drift (`positions` ghost row, `admin_sessions` missing, legacy `fund_holdings`).
- 7 pipeline_inventory.md drift (4 undocumented pipeline modules + 3 retired-row annotations).

**Highest-impact findings.**
1. **raw_* orphan trio** — 13.6M rows written by legacy `load_13f.py`, zero readers in code (§7.c, §8.Q2).
2. **REMEDIATION_CHECKLIST drift** — 3 stale `[ ]` for items closed in other trackers (§4, §7.d).
3. **`fund_holdings` tri-way inconsistency** — table present with 22K rows but both canonical_ddl.md and data_layers.md claim it was dropped (§6.a, §6.b, §8.Q1).
4. **Pass 2's 77 "retire candidates" is inflated** — real count ≈ 10–25 after filtering migrations, one-offs, CLI tools (§7.b, §8.Q9).
5. **INF40 / DM3 / DM6 ticket-number reuse** — violates PR #131 retire-forever hygiene rule (§4.b, §8.Q5).
