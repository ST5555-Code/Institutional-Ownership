# Consolidated Backlog Memo — 2026-04-24

- **Session**: `backlog-consolidation` (read-only discovery; no edits to trackers, scripts, or DB)
- **HEAD**: `e3acfe3` (origin/main, post `doc-sync` PR #149)
- **Base branch**: `backlog-consolidation` off `origin/main`
- **Scope**: catalog every open / in-progress / deferred / scheduled backlog item across every tracker, findings file, plan, architecture doc, operational doc, and code TODO marker. Surface drift but do **not** reconcile. Do **not** propose new work.

## Source inventory

| Source category | Files scanned |
|---|---|
| Primary trackers | 4 — `ROADMAP.md`, `docs/REMEDIATION_PLAN.md`, `docs/DEFERRED_FOLLOWUPS.md`, `docs/NEXT_SESSION_CONTEXT.md` |
| Plans | 2 — `archive/docs/plans/2026-04-23-phase-b-c-execution-plan.md`, `archive/docs/plans/20260412_architecture_review_revision.md` |
| Findings | 55 (incl. 1 index README) |
| Closures | 1 (README only) |
| Architecture | 5 — `ARCHITECTURE_REVIEW.md`, `ENTITY_ARCHITECTURE.md`, `docs/admin_refresh_system_design.md`, `docs/data_layers.md` (body), `docs/pipeline_inventory.md` |
| Operational | 2 — `MAINTENANCE.md`, `docs/PROCESS_RULES.md` + `docs/SESSION_GUIDELINES.md` |
| Code TODO/FIXME/XXX/HACK | 5 hits across `scripts/` + `web/react-app/` (archive/snapshot excluded) |
| UI-specific | 0 README/TODO files under `web/react-app/`; 1 in-component TODO |
| UI audit (unmerged branch) | 1 — `docs/ui-audit-01-triage.md` (599 lines) on branch `ui-audit-01` / [PR #107](https://github.com/ST5555-Code/Institutional-Ownership/pull/107) OPEN. Added after initial Phase 2 enumeration missed it — see [Meta-findings](#meta-findings). |

---

## Table of contents

1. [Executive summary](#executive-summary)
2. [PIPELINE](#pipeline)
3. [DATA_QUALITY](#data_quality)
4. [UI](#ui)
5. [INFRA](#infra)
6. [ARCHITECTURE](#architecture)
7. [DOCS](#docs)
8. [OPS](#ops)
9. [SECURITY](#security)
10. [Cross-tracker drift](#cross-tracker-drift)
11. [DATA_QUALITY deep dive](#data_quality-deep-dive)
12. [UI deep dive](#ui-deep-dive)
13. [Meta-findings](#meta-findings)
14. [Appendix — flat item list](#appendix--flat-item-list)

---

## Executive summary

- **Total distinct items catalogued**: 86 (deduplicated; matches the [Appendix](#appendix--flat-item-list) row count after ui-audit-01 re-scope)
- **Total raw hits before dedup**: ~158 across all Phase 2 sources (ROADMAP ~36, REMEDIATION_PLAN + plans ~22, findings/closures ~31, code/ops-doc TODOs ~6, architecture/operational docs ~47, ui-audit-01 triage file ~16). Dedup rate ~46% — heavy cross-tracker overlap, consistent with INF / DM / P2-FU items appearing in 3–4 sources each.

### By category

| Category | Count | Δ from v1 |
|---|---:|---:|
| DATA_QUALITY | 20 | +1 (ui-audit bug-1) |
| ARCHITECTURE | 19 | +1 (ui-audit dead-endpoints) |
| UI | 11 | +3 (ui-audit React-1/React-2/walkthrough) |
| DOCS | 11 | — |
| PIPELINE | 10 | +5 (ui-audit bug-2 + 3 precompute rows + 1 open-q) |
| OPS | 8 | — |
| INFRA | 6 | — |
| SECURITY | 1 | — |
| **Total** | **86** | **+10** |

(Two items span two categories; counted once under primary.)

### By timing

| Timing bucket | Count |
|---|---:|
| BACKGROUND (standing / recurring) | 5 |
| GATED (blocked on named condition) | 14 |
| IMMEDIATE (dispatchable now) | 22 |
| PARKED (intentionally paused) | 10 |
| SCHEDULED (fixed date) | 3 |
| TIMED (date-dependent) | 2 |
| UNSCOPED (no session) | 22 |

### Highlighted gaps (surface-only; see Meta-findings for detail)

- **DATA_QUALITY is the largest single category** (20 items). 8 items have sat > 60 days. DM13 ADV audit (~390 suspicious rows), L4 classification audit (13 categories), L5 parents 201–720 batches, and the 1,187 DERA NULL series all carry forward without an active session slot.
- **UI is better-catalogued than initially reported — but on an unmerged branch, not in any primary tracker on `main`.** Initial Phase 2 sweep of `docs/findings/` missed `docs/ui-audit-01-triage.md` (lives at `docs/`, not `docs/findings/`, and only on branch `ui-audit-01` / [PR #107](https://github.com/ST5555-Code/Institutional-Ownership/pull/107)). That file carries 11 UI-category items + 8 precompute targets + 24 per-tab "Bugs (visual)" / "Completeness gaps" placeholder rows left BLANK pending Serge's walkthrough. None of those 11+ items are replicated into ROADMAP.md / DEFERRED_FOLLOWUPS.md / NEXT_SESSION_CONTEXT.md. NEXT_SESSION_CONTEXT.md:41 merely references "PR #107 ui-audit walkthrough — separate track, still open" without scope. Direct UI-facing tracker presence remains low: `web/react-app/` still has no `README.md` / `TODO.md` / `CHANGELOG.md`, and `web/react-app/src/` has only 1 in-component TODO.
- **Drift between `docs/REMEDIATION_PLAN.md` body and its own Changelog**. The body (`:291`, `:375`, `:377`, `:380`, `:427`, `:457`, `:458`, `:459`) still flags mig-01, INF40, INF41, INF42, mig-06/07/08/09/10/11, and 5 Phase-2-native scaffold items as OPEN / PENDING; `:577,584,585` Changelog (conv-11 + conv-12) closed all of them. The body was never updated.
- **DM14 + DM15 Layer 1** show as PARKED in `docs/data_layers.md §11` and `MAINTENANCE.md §Open audits` but ROADMAP records them as DONE (2026-04-15 to 2026-04-17).
- **INF37 entity curation** shows as `STANDING` in ROADMAP and `DEFERRED_FOLLOWUPS`, but `docs/findings/entity-curation-w1-log.md` reports it CLEARED 2026-04-23 with zero residuals.
- **int-23 design questions Q7.1 and Q7.2** remain in `docs/findings/int-23-design.md`; the impl shipped 2026-04-23 per `DEFERRED_FOLLOWUPS` — questions probably resolved by the impl, but design file was never annotated.

---

## PIPELINE

| ID | Title | State | Timing | Source | Age | Notes |
|---|---|---|---|---|---|---|
| P2-FU-01 | Prune legacy `run_script` allowlist in `scripts/admin_bp.py` | OPEN | GATED | `docs/DEFERRED_FOLLOWUPS.md:17`; `ROADMAP.md:587`; `archive/docs/plans/2026-04-23-phase-b-c-execution-plan.md §9` | ~2 days (conv-12) | Gate: 1 clean quarterly cycle on V2 framework to surface stale Makefile/scheduler paths first. |
| P2-FU-03 | ADV SCD Type 2 conversion (currently `direct_write`) | OPEN | UNSCOPED | `docs/DEFERRED_FOLLOWUPS.md:18`; `ROADMAP.md:588`; `docs/plans/…-phase-b-c…md §9` | ~2 days | Design question: which columns carry history. No downstream consumer asking yet. |
| — | V-Q3 co-land cleanups for B3 denorm drops: `scripts/db.py` REFERENCE_TABLES + `scripts/pipeline/registry.py` L1 entries + `notebooks/research.ipynb` dead-branch probe | OPEN | GATED | `docs/findings/refinement-validation-2026-04-23.md:146–237` | 1 day | Co-lands with B3 (~Aug 2026). |
| — | Cross-process rate limiter (currently in-process `threading.Lock`) | OPEN | UNSCOPED | `scripts/pipeline/shared.py:9,39` (code TODO) | — | Triggers when orchestrator moves to parallel subprocess dispatch. |
| int-23 Q7.1 | Hard-coded vs per-pipeline sensitive columns for `_promote_append_is_latest` downgrade refusal | OPEN-QUESTION | UNSCOPED | `docs/findings/int-23-design.md:263–265` | 1 day | Design file post-dates int-23 impl; see [Drift](#cross-tracker-drift). |
| int-23 Q7.2 | Fail-whole-run vs per-key partial on downgrade refusal | OPEN-QUESTION | UNSCOPED | `docs/findings/int-23-design.md:265–267` | 1 day | Same caveat as Q7.1. |
| ui-audit-01 bug-2 | `query1()` NoneType crash at `queries.py:933` — Register + Entity Graph "ticker holders" panel 500 | OPEN BLOCKER | UNSCOPED | `docs/ui-audit-01-triage.md` §Technical anomalies #2 @ branch `ui-audit-01` | 2 days | One-line null guard `c['institution'].lower() for c in nport_kids if c.get('institution')`. Routed to int-09 Step 4 bundle per triage §Work item routing. |
| ui-audit-01 perf-P0 | `peer_rotation_by_ticker` + `peer_rotation_detail_by_pair` precomputed tables (cures 11.4s cold/warm) | OPEN | UNSCOPED | `docs/ui-audit-01-triage.md` §Precompute build plan P0 | 2 days | New `compute_peer_rotation.py` + `SourcePipeline` subclass. 2–3 day effort; highest single-path cost in the audit. |
| ui-audit-01 perf-P1 | `sector_flows_rollup` + `sector_flow_movers_by_quarter_sector` + `cohort_by_ticker_from` precomputed tables | OPEN | UNSCOPED | `docs/ui-audit-01-triage.md` §Precompute build plan P1 | 2 days | Sector Rotation + Ownership Trend tabs. Combined ~3 day effort per triage. |
| ui-audit-01 perf-P2 | `flow_analysis_by_ticker_period` + `market_summary_top25` + `holder_momentum_by_ticker` precomputed tables | OPEN | UNSCOPED | `docs/ui-audit-01-triage.md` §Precompute build plan P2 | 2 days | Flow Analysis + Entity Graph + Ownership Trend. Combined ~2 day effort. |
| ui-audit-01 open-q | `short_interest_analysis()` precompute vs keep live (~130 ms warm) — traffic-dependent decision | OPEN-QUESTION | UNSCOPED | `docs/ui-audit-01-triage.md` §Short Interest precompute | 2 days | Serge confirmation needed. |

---

## DATA_QUALITY

| ID | Title | State | Timing | Source | Age | Notes |
|---|---|---|---|---|---|---|
| INF25 | BLOCK-DENORM-RETIREMENT Step 4 — drop denorm columns from v2 fact tables | OPEN | GATED | `ROADMAP.md:577,602`; `docs/DEFERRED_FOLLOWUPS.md:13`; `docs/plans/…-phase-b-c…md §9`; `docs/findings/int-09-p0-findings.md §4` | ~12 days | Unblocked post-Phase-2; waits on dual-graph resolution decision for `rollup_entity_id`. |
| INF27 | CUSIP residual-coverage tracking tier | BACKGROUND | BACKGROUND | `ROADMAP.md:580,605`; `docs/DEFERRED_FOLLOWUPS.md:14`; `docs/data_layers.md:136` | ≥60 days | Standing curation. Revisit trigger: net-increase in `pending` rows across two consecutive runs. |
| INF37 | `backfill_manager_types` residual — 9 entities / 14,368 rows | STANDING per trackers; CLEARED per findings | — | `ROADMAP.md:…`; `docs/DEFERRED_FOLLOWUPS.md:15`; `docs/findings/entity-curation-w1-log.md` | 1 day | See [Drift](#cross-tracker-drift). |
| INF38 / int-19 | BLOCK-FLOAT-HISTORY — true float-adjusted `pct_of_float` denominator | OPEN | UNSCOPED | `ROADMAP.md:578,602`; `docs/DEFERRED_FOLLOWUPS.md:16`; `docs/plans/…-phase-b-c…md §9`; `ARCHITECTURE_REVIEW.md:10`; `docs/NEXT_SESSION_CONTEXT.md:95` | ~30 days | Blocked on a new float-history data source (10-K / 13D / Forms 3-5 ingestion). |
| INF16 | Recompute `managers.aum_total` for two Soros CIKs | OPEN | UNSCOPED | `ROADMAP.md:582,606`; `docs/plans/…-phase-b-c…md §9` | ≥60 days | CIK 0001029160 ($977M) + 0001748240 ($257M). May be subsumed by INF17. |
| 43e | Family-office classification (+ `multi_strategy` + `SWF` bucket ambiguity) | RESCOPED / OPEN | UNSCOPED | `ROADMAP.md:608`; `docs/findings/entity-curation-w1-log.md`; `docs/NEXT_SESSION_CONTEXT.md:40` | 1 day | Taxonomy refactor touching `build_summaries.py:173,181` + `queries.py:1724` closed-list checks + React `typeConfig.ts`. |
| 43g | Drop redundant type columns — migrate queries | OPEN | UNSCOPED | `ROADMAP.md:583,609`; `docs/plans/…-phase-b-c…md §9` | ~14 days | `fund_universe.is_actively_managed`→`fund_strategy` (14 refs); `holdings_v2.manager_type`→`entity_type` (65 refs). |
| DM2 | ADV Schedule 7.B re-parse | DEFERRED | GATED | `docs/findings/dm-open-surface-2026-04-22.md:25`; `ROADMAP.md` DM sequence | ~2 days | Blocked on D12 ADV Section 7.B re-parse. Post-3.5b. |
| DM3 | N-PORT metadata extension | DEFERRED | GATED | `docs/findings/dm-open-surface-2026-04-22.md:26` | ~2 days | Blocked on D13 `fetch_nport.py` metadata extension. Post-3.5b. |
| DM6 | N-1A prospectus / SAI parser | DEFERRED | UNSCOPED | `docs/findings/dm-open-surface-2026-04-22.md:28`; `ROADMAP.md:865` | ~2 days | 7 of 10 umbrella trusts (DM15e) blocked behind this. Low priority. |
| DM13 | ADV_SCHEDULE_A residual sweep — ~390 suspicious rows (BlueCove closed, remainder open) | OPEN | UNSCOPED | `docs/findings/dm-open-surface-2026-04-22.md:149`; `MAINTENANCE.md:393` | ~2 days | Explicitly called out as a 13D/G + ADV data-quality tail; no session slot. |
| DM14c | Voya residual — $21.81B / 49 funds | OPEN | GATED | `docs/findings/dm-open-surface-2026-04-22.md:150` | ~2 days | Blocked on DM14b edge-completion (Voya edge missing). |
| DM15 umbrella-trusts audit | ~132 series / ~$105B across 10 umbrella trusts | DEFERRED | UNSCOPED | `ROADMAP.md:879` | ~10 days | Split into DM15d (N-CEN-resolvable) + DM15e (prospectus-blocked). |
| DM15d | N-CEN-resolvable umbrella trusts (Sterling / NEOS / Segall Bryant) | OPEN | UNSCOPED | `docs/findings/dm-open-surface-2026-04-22.md:151` | ~2 days | Extend DM15b/Layer 2 pattern via `ncen_adviser_map`. |
| DM15e | Prospectus-blocked umbrella trusts (7 — Gotham / Mairs / Brandes / Crawford / Bridges / Champlain / FPA) | DEFERRED | GATED | `docs/findings/dm-open-surface-2026-04-22.md:152`; `ROADMAP.md:879` | ~2 days | Blocked on DM6 (N-1A parser) or DM3 (N-PORT metadata). |
| 48 (D2–D13 remainder) | Phase 3.5 deferred — D2 (pymupdf recall), D4 (match quality), D5 (IAPD), D12 (ADV 7.B), D13 (N-PORT XML) | PARTIAL | UNSCOPED | `ROADMAP.md:585,611` | ≥90 days | D1, D7 done. D10, D11 tracked under UI. |
| 56 | Decision-maker & voting rollup worldviews (DM1–DM7 series completion) | NOT-STARTED | UNSCOPED | `ROADMAP.md:586,612` | ≥30 days | UI toggle for `rollup_type` on 6+ tabs; phased: N-CEN (Phase 1), ADV (3.5b), N-PORT (3.5c). Spans DATA_QUALITY + UI. |
| — | DERA fund_universe NULL-series synthetics — 1,187 rows | PARKED | UNSCOPED | `docs/data_layers.md:92` | ≥60 days | Resolution tracked in audit §10.1. |
| — | Rule A / Rule B OTC classification tracking note | PARTIAL | UNSCOPED | `docs/data_layers.md:96` §6 S1 | ≥30 days | Substantive closure via int-13 / migration 012; tracking note in body never struck. |
| ui-audit-01 bug-1 | `is_latest=TRUE` inversion on prod DB `data/13f.duckdb` for `quarter='2025Q4'` — every `is_latest=TRUE` row has `ticker IS NULL`; every ticker-bearing row is `is_latest=FALSE` | OPEN at 2026-04-22; verify vs post-dated int-22 rollback | UNSCOPED | `docs/ui-audit-01-triage.md` §Technical anomalies #1 @ branch `ui-audit-01` | 2 days | Breaks `/api/v1/tickers`, `/api/v1/fund_portfolio_managers`, `/api/v1/portfolio_context`, most 2025Q4-filtering queries. Fix: backfill or migration on prod DB. Int-22 rollback (2026-04-22) may have addressed; confirm before action. |

---

## UI

| ID | Title | State | Timing | Source | Age | Notes |
|---|---|---|---|---|---|---|
| BL-5 | Zustand scope enforcement — global store doc | OPEN | UNSCOPED | `ROADMAP.md:805` | ~14 days | Document store scope = ticker/quarter/rollupType/company only. |
| BL-6 | Loading state standardization across 11 React tabs | OPEN | UNSCOPED | `ROADMAP.md:806` | ~14 days | Shared skeleton + empty state component. |
| D10 | Admin UI for `entity_identifiers_staging` review (~280-row backlog) | PARTIAL | UNSCOPED | `docs/findings/dm-open-surface-2026-04-22.md:154`; `ROADMAP.md:611 (part of #48)` | ≥30 days | General admin UI (p2-07) shipped; does not surface this table. |
| D11 | Confidence-threshold auto-approve reader | PARTIAL | UNSCOPED | `docs/findings/dm-open-surface-2026-04-22.md:155`; `ROADMAP.md:611` | ≥30 days | Schema + `--auto-approve` flag shipped; conditional-logic reader not implemented. |
| ARCH-4C-followup | React type-migration `api.ts` → `api-generated.ts` | OPEN | GATED | `ROADMAP.md:810` | ~14 days | Prereq: expand `scripts/schemas.py` for ~55 response types (4-6h). Skipping step 1 trades ~900 typed fields for `unknown`. |
| — | Rollback UI button (admin tab v2) | PARKED | UNSCOPED | `docs/admin_refresh_system_design.md:922` | ~30 days | Rollback endpoint already exists; UI button ships in v2 of the admin tab. |
| — | `DataSourceTab.tsx` cadence timeline SVG (p2-06 TODO) | OPEN | UNSCOPED | `web/react-app/src/components/tabs/DataSourceTab.tsx:99` | — | In-component TODO; wire timeline from `PIPELINE_CADENCE` constant. |
| — | Type-badge `family_office` color addition | OPEN | GATED | `docs/NEXT_SESSION_CONTEXT.md:40`; `common/typeConfig.ts` | 1 day | Part of 43e taxonomy refactor; React leg. |
| ui-audit-01 React-1 | Consolidate `/api/v1/tickers` into single shared hook (TickerInput, CrossOwnershipTab, OverlapAnalysisTab) | OPEN | UNSCOPED | `docs/ui-audit-01-triage.md` §Work item routing @ branch `ui-audit-01` / PR #107 | 2 days | P3 priority; <0.5d effort per triage. Fetched 3× per session today. |
| ui-audit-01 React-2 | Collapse duplicate `/api/v1/entity_search` call in EntityGraphTab.tsx (L125 + L230) | OPEN | UNSCOPED | `docs/ui-audit-01-triage.md` §Work item routing | 2 days | P3 priority; request-scoped memo. |
| ui-audit-01 walkthrough | 24 per-tab "Bugs (visual)" + "Completeness gaps" placeholder rows (12 tabs × 2) | OPEN | GATED | `docs/ui-audit-01-triage.md` §per-tab sections (BLANK) | 2 days | Gate: Serge walks the live app and fills each row (PR #107 test-plan item 1). |

Cross-reference — **PR #107 ui-audit walkthrough** per `docs/NEXT_SESSION_CONTEXT.md:41`: the triage file at `docs/ui-audit-01-triage.md` on branch `ui-audit-01` feeds the three `ui-audit-01 …` rows above plus additional non-UI items (see PIPELINE, DATA_QUALITY, ARCHITECTURE). None of the triage items are filed in any primary tracker on `main`.

---

## INFRA

| ID | Title | State | Timing | Source | Age | Notes |
|---|---|---|---|---|---|---|
| snapshot-retention-cadence | Wire `scripts/hygiene/snapshot_retention.py --apply` onto a recurring surface | OPEN | UNSCOPED | `docs/NEXT_SESSION_CONTEXT.md:34`; `ROADMAP.md §Current backlog` | 0 days | Mechanism + backfill shipped PR #148. Surface choice (cron / Makefile / scheduler) open. `--dry-run` safe as nightly CI probe today. |
| — | `audit_tracker_staleness.py` not wired to pre-commit / CI | PARTIAL | UNSCOPED | `docs/SESSION_GUIDELINES.md:156`; `scripts/hygiene/audit_tracker_staleness.py` | — | Script exists; enforcement remains manual. |
| G10 | GitHub Actions smoke CI (Phase 0-B2 pending at time of ARCHITECTURE_REVIEW; state drifted since) | PARTIAL | UNSCOPED | `ARCHITECTURE_REVIEW.md:180` | ~40 days | Auto-memory `project_session_apr13_phase0b2.md` reports 0-B2 merged 2026-04-13 → likely CLOSED; see [Drift](#cross-tracker-drift). |
| — | `scripts/pipeline/shared.py` cross-process rate limiter | OPEN | UNSCOPED | `scripts/pipeline/shared.py:9,39` | — | Also appears under PIPELINE; primary category INFRA (shared infra concern). |
| — | PROCESS_RULES Rule 9 (`--dry-run` default) not uniformly applied | PARTIAL | UNSCOPED | `docs/PROCESS_RULES.md:101–105` | ≥60 days | FINRA short script explicitly listed (`finra-default-flip` 2026-07-23 addresses it). Others uninventoried. |
| — | PROCESS_RULES Rule 3 (dual-source failover) — 13F single-source | PARTIAL | UNSCOPED | `docs/PROCESS_RULES.md:29–36` | ≥60 days | N-PORT and 13D/G are dual-source; 13F has no fallback documented. |

---

## ARCHITECTURE

| ID | Title | State | Timing | Source | Age | Notes |
|---|---|---|---|---|---|---|
| phase-b3 | Retire V1 loader + drop denorm columns | OPEN | GATED | `docs/NEXT_SESSION_CONTEXT.md:33`; `docs/plans/…-phase-b-c…md §7` | 0 days | Gate: 2 clean 13F cycles on V2 (Q1 2026 ~May 15, Q2 2026 ~Aug 14). Plan §7 frozen. |
| multi-db-datasetspec | Add `db_file` field to `DatasetSpec` + update `unclassified_tables()` callers | OPEN | GATED | `docs/NEXT_SESSION_CONTEXT.md:36`; `ROADMAP.md:591` | 0 days | Prereq for registering `admin_sessions` + `admin_preferences` in `data/admin.duckdb`. |
| admin_preferences | Register or retire 0-row stub from migration 016 | OPEN | GATED | `docs/NEXT_SESSION_CONTEXT.md:37`; `ROADMAP.md:590` | 0 days | Blocked on `multi-db-datasetspec`. |
| registry-gap-sweep | Remaining 2 of 4 tables: `admin_sessions` + `cusip_classifications` | PARTIAL | GATED | `ROADMAP.md:589`; `docs/plans/…-phase-b-c…md §8.4` | 0 days | `_cache_openfigi` + `cusip_retry_queue` registered PR #144. `admin_sessions` blocked on multi-DB; `cusip_classifications` out-of-scope per PR. |
| int-09 Step 4 / INF25 | Denorm retirement architectural design | UNBLOCKED | GATED | `ROADMAP.md §Open items`; `docs/NEXT_SESSION_CONTEXT.md:94`; `ARCHITECTURE_REVIEW.md:10` | ~12 days | Primary DATA_QUALITY item; architectural leg tracked here. |
| G1 | Untyped API contract (no OpenAPI-driven types; hand-written `api.ts`) | OPEN | UNSCOPED | `ARCHITECTURE_REVIEW.md:113–132` | ≥40 days | Called out as highest-value gap before tool is shared. Cross-ref ARCH-4C-followup. |
| G2 | No standardised error contract across endpoints | OPEN | UNSCOPED | `ARCHITECTURE_REVIEW.md:133` | ≥40 days | React tabs lack consistent error boundary. |
| G6 | `scripts/app.py` monolith (~1,400 lines, 50+ routes) | PARTIAL | UNSCOPED | `ARCHITECTURE_REVIEW.md:153` | ≥40 days | Blueprint split Batch 4-A complete per ARCHITECTURE_REVIEW annotation. |
| G7 | `scripts/queries.py` monolith (~5,500 lines) | PARTIAL | UNSCOPED | `ARCHITECTURE_REVIEW.md:158`; `archive/docs/plans/20260412_architecture_review_revision.md §A2` | ≥40 days | Batch 4-B split underway; per-domain split deferred to "Phase 6". |
| BL-2 | Pipeline dependency enforcement — Makefile / DAG to prevent out-of-order runs | OPEN | UNSCOPED | `ROADMAP.md:802` | ~30 days | |
| BL-3 | Write-path consistency (non-entity) — extend staging/validation to flow recompute + market-data upsert | OPEN | UNSCOPED | `ROADMAP.md:803` | ~30 days | |
| BL-4 | Three snapshot roles (serving / rollback / archive) documented | OPEN | UNSCOPED | `ROADMAP.md:804` | ~30 days | |
| BL-7 | DB-universe ticker validation at route layer | OPEN | UNSCOPED | `ARCHITECTURE_REVIEW.md:715`; `archive/docs/plans/20260412_architecture_review_revision.md §C3b` | ≥30 days | Deferred from 1-A to avoid DB coupling at route layer. |
| — | `portfolio_context` precompute — re-trigger when latency regresses | PARKED | UNSCOPED | `ARCHITECTURE_REVIEW.md:467–476` | ~12 days | Current 730ms acceptable. |
| INF28 | `securities.cusip` VALIDATOR_MAP registration | OPEN | UNSCOPED | `docs/data_layers.md:96,136` | ≥30 days | PK constraint empirical-only; formal VALIDATOR_MAP row pending. |
| P2-FU-04 | ADV ownership boundary documentation cross-ref | OPEN (annotation) | UNSCOPED | `docs/data_layers.md:47` | ~2 days | `DEFERRED_FOLLOWUPS.md` marks P2-FU-04 CLOSED 2026-04-22; cross-ref note in body never struck. See [Drift](#cross-tracker-drift). |
| §14 Q2 | Admin diff-presentation tier boundaries (1K, 100K) | OPEN | UNSCOPED | `docs/admin_refresh_system_design.md:980` | ≥30 days | Reviewer question pending. |
| §14 Q7 | `PIPELINE_CADENCE` correctness vs SEC rules | OPEN | UNSCOPED | `docs/admin_refresh_system_design.md:987` | ≥30 days | Reviewer question pending. |
| §14 Q8 | Probe rate-limit safety vs PROCESS_RULES §4 | OPEN | UNSCOPED | `docs/admin_refresh_system_design.md:988` | ≥30 days | Reviewer question pending. |
| ui-audit-01 dead-endpoints | 15 routes defined in routers but not called from any tab (candidates for triage: delete vs modal-only keep) | OPEN | UNSCOPED | `docs/ui-audit-01-triage.md` §Technical anomalies #5 @ branch `ui-audit-01` | 2 days | Triage out of scope for the audit itself; explicit follow-up ask. Routes: `/api/v1/config/quarters`, `/api/v1/amendments`, `/api/v1/manager_profile`, `/api/v1/fund_rollup_context`, `/api/v1/fund_behavioral_profile`, `/api/v1/nport_shorts`, `/api/v1/entity_resolve`, `/api/v1/sector_flow_detail`, `/api/v1/short_long`, `/api/v1/short_volume`, `/api/v1/crowding`, `/api/v1/smart_money`, `/api/v1/heatmap`, `/api/v1/peer_groups/{group_id}`, `/api/v1/export/query{qnum}`. |

---

## DOCS

| ID | Title | State | Timing | Source | Age | Notes |
|---|---|---|---|---|---|---|
| maintenance-audit-design | Re-author `rotating_audit_schedule.md` from 6-surface scope + May–October cadence | OPEN | UNSCOPED | `docs/NEXT_SESSION_CONTEXT.md:38`; `docs/findings/2026-04-23-ops-18-investigation.md`; `ROADMAP.md:579` | 1 day | Was ops-18; PARTIAL outcome per C2. |
| — | `docs/TESTING_STRATEGY.md` | TODO | UNSCOPED | `ARCHITECTURE_REVIEW.md:197` | ≥40 days | Pointer exists; doc never created. |
| — | `docs/OBSERVABILITY_PLAN.md` | TODO | UNSCOPED | `ARCHITECTURE_REVIEW.md:199` | ≥40 days | Pointer exists; doc never created. |
| — | `docs/SCHEMA_MIGRATIONS.md` | TODO | UNSCOPED | `archive/docs/plans/20260412_architecture_review_revision.md` R2 | ~12 days | Pointer introduced by the revision plan; doc never created. |
| — | Rename `block/pct-of-float-period-accuracy` → `block/pct-of-so-period-accuracy` across findings docs | OPEN | UNSCOPED | `docs/DEFERRED_FOLLOWUPS.md:56` | ~30 days | "Next batched doc-update". |
| — | `pct_of_float` → `pct_of_so` terminology retirement project-wide | OPEN | UNSCOPED | `docs/DEFERRED_FOLLOWUPS.md:57` | ~30 days | "Next batched doc-update". |
| — | `docs/data_layers.md §7`: add `pct_of_so_source` as Class B audit column | OPEN | UNSCOPED | `docs/DEFERRED_FOLLOWUPS.md:58` | ~30 days | "Next batched doc-update". |
| — | `docs/pipeline_violations.md`: close `pct_of_float` violation entries with Phase 1b/1c/4b citations | OPEN | UNSCOPED | `docs/DEFERRED_FOLLOWUPS.md:59` | ~30 days | "Next batched doc-update". |
| v3.3 | Incorporate reviewer feedback into `admin_refresh_system_design.md` v3.3 | PENDING | UNSCOPED | `docs/admin_refresh_system_design.md:990` | ≥30 days | "After review, incorporate feedback into v3.3, then write Claude Code prompts phase-by-phase" — prompts have been written (p2-01 … p2-10-fix shipped), so v3.3 may be moot. |
| §14 Q1 | Migration 008 exec order decision | OPEN | UNSCOPED | `docs/admin_refresh_system_design.md:964–972` | ≥40 days | Reviewer question; migration 008 has shipped — likely moot. |
| — | SESSION_GUIDELINES §5 enforcement automation | PARTIAL | UNSCOPED | `docs/SESSION_GUIDELINES.md:144–156` | ~2 days | Rule exists but enforcement is manual; CI gate not built. |

---

## OPS

| ID | Title | State | Timing | Source | Age | Notes |
|---|---|---|---|---|---|---|
| finra-default-flip | Delete deprecation-warning path in `scripts/fetch_finra_short.py` + require mutex | SCHEDULED | **2026-07-23** | `docs/NEXT_SESSION_CONTEXT.md:35`; `ROADMAP.md §Current backlog`; `MAINTENANCE.md:183`; `docs/pipeline_inventory.md:86,183` | 0 days | Callers already pass `--apply` explicitly. |
| INF2 | Monthly maintenance checklist (1st of each month) | BACKGROUND | BACKGROUND | `ROADMAP.md:581,607`; `docs/DEFERRED_FOLLOWUPS.md` | ≥90 days | `validate_entities.py`, `manual_routing_review` gate, `diff_staging.py`. |
| L4 audit | Classification categories (13 categories) | PARKED | UNSCOPED | `MAINTENANCE.md:397`; auto-memory `project_session_apr9_phase4.md` | ≥90 days | 11/13 categories complete per auto-memory; mixed + active remaining. |
| L5 audit | Parents 201–720 (batches of 100) | PARKED | UNSCOPED | `MAINTENANCE.md:396` | ≥30 days | No explicit closure docs linked. |
| DM14 / DM15 Layer 1 | External sub-adviser + intra-firm sub-adviser audits | PARKED per MAINTENANCE.md; DONE per ROADMAP | — | `MAINTENANCE.md:394,395`; `docs/data_layers.md:393,394` | ≥14 days | See [Drift](#cross-tracker-drift). |
| — | Auto-refresh scheduler (cron) | PARKED | UNSCOPED | `docs/admin_refresh_system_design.md:922` | ≥30 days | "Optional auto-refresh is future work." |
| — | Prometheus metrics | PARKED | UNSCOPED | `docs/admin_refresh_system_design.md:922` | ≥30 days | Deferred. |
| — | Multi-user roles on admin | PARKED | UNSCOPED | `docs/admin_refresh_system_design.md:922` | ≥30 days | Explicitly out of scope. |

---

## SECURITY

| ID | Title | State | Timing | Source | Age | Notes |
|---|---|---|---|---|---|---|
| 43b | `scripts/app.py` remaining hardening | OPEN | UNSCOPED | `ROADMAP.md:584,610`; `docs/plans/…-phase-b-c…md §9` | ≥30 days | B110 (8 exception swallows), B603/B607 (subprocess allowlist), B104 (Flask `0.0.0.0`→`localhost`). |

---

## Cross-tracker drift

Items that surface in 2+ sources (with file:line citations for both) and disagree on state, scope, or terminology. Recorded only; **not reconciled** in this session.

| # | Item | Source A (with line) | Source B (with line) | Disagreement |
|---:|---|---|---|---|
| 1 | `docs/REMEDIATION_PLAN.md` body vs Changelog | Body: `docs/REMEDIATION_PLAN.md:291,375,377,380,427,457,458,459` lists mig-01, INF40, INF41, INF42, mig-06/07/08/09/10/11 + 5 Phase-2-native scaffold items as OPEN / PENDING | `docs/REMEDIATION_PLAN.md:577,584,585` Changelog — `(conv-11)` + `(conv-12)` close all of them | Body was never updated after closures; same file's Changelog contradicts its body. |
| 2 | INF37 `backfill_manager_types` residual | `docs/DEFERRED_FOLLOWUPS.md:15`: STANDING; `ROADMAP.md:604`: standing curation | `docs/findings/entity-curation-w1-log.md:11,16,23`: "APPLIED to prod. … 14,368 → 0 (zero residuals)" | Findings reports closure 2026-04-23; primary trackers still say STANDING. |
| 3 | int-23 design questions | `docs/findings/int-23-design.md:263–267` Q7.1 / Q7.2 OPEN | `docs/DEFERRED_FOLLOWUPS.md:20`: int-23 CLOSED 2026-04-23 (int-23-impl Option (a)) | Impl presumably resolves Q7.1/Q7.2 but design file was never annotated. |
| 4 | DM14 / DM15 Layer 1 status | `ROADMAP.md:114` (DM15 Layer 1 in `entity_rollup_history` row count); auto-memory records DM14 Layer 1 / DM15 Layer 1 DONE 2026-04-15–17 | `MAINTENANCE.md:394,395`: both listed under "Open audits"; `docs/data_layers.md:393,394`: same two items listed as PARKED | Follow-on rows exist but phrasing leaves DONE / OPEN coexisting. |
| 5 | ops-18 rotating audit label | `ROADMAP.md:579`: "ops-18 … PARTIAL" | `docs/NEXT_SESSION_CONTEXT.md:38`: relabelled `maintenance-audit-design`; `archive/docs/plans/2026-04-23-phase-b-c-execution-plan.md:36,46,874,876,896`: "Phase C2 investigation" | Three labels for one item. |
| 6 | P2-FU-04 ADV ownership boundary | `docs/DEFERRED_FOLLOWUPS.md:44`: CLOSED 2026-04-22 (p2fu-04) | `docs/data_layers.md:47`: "see … P2-FU-04" cross-ref note without status | Body note not updated to reflect closure. |
| 7 | V2 loader cycle-entry point | `docs/NEXT_SESSION_CONTEXT.md:10,82,83`: "V2 cutover complete" / Makefile invokes V2 | `docs/findings/refinement-validation-2026-04-23.md:25–125` V-Q1 PARTIAL: "Makefile:110–111 still invokes V1" | Findings file pre-dates PR #141 V2 cutover (2026-04-23); drift is temporal — finding was never annotated post-merge. |
| 8 | 43e family-office classification | `ROADMAP.md:608,666` lists as open follow-on for taxonomy refactor | `docs/findings/entity-curation-w1-log.md:13,158,181`: "DE-SCOPED … Item C remains open in ROADMAP §Open items, re-filed as a dedicated taxonomy refactor follow-on" | Intent agrees; state label differs (OPEN follow-on vs DE-SCOPED). |
| 9 | DM13 row count | `docs/findings/dm-open-surface-2026-04-22.md:149`: ~390 remaining (after BlueCove cluster closed) | `MAINTENANCE.md:393`: "~410 suspicious relationships" | MAINTENANCE.md cites pre-BlueCove number. |
| 10 | ui-audit-01 triage items unfiled on `main` | `docs/ui-audit-01-triage.md` (branch `ui-audit-01`, commit `8a50a51`): 3 blockers, 8 precompute targets, 2 React-only items, 15 dead endpoints, 1 open question, 24 blank per-tab rows | `docs/NEXT_SESSION_CONTEXT.md:41` on `main`: single-line mention "PR #107 ui-audit walkthrough — separate track, still open" without scope; ROADMAP.md / DEFERRED_FOLLOWUPS.md carry no rows for any triage item | Comprehensive audit exists but is invisible from `main` tracker scans. A reader not aware of PR #107 would not discover the scope. |

**Drift count: 10.**

_Removed from prior 11-entry list: (a) int-21 SELF-fallback — no second-source citation; not actual drift. (b) Phase 0-B2 smoke CI (ARCHITECTURE_REVIEW.md G10) — second source was auto-memory, which is not a Phase 2 enumerated source; out of scope for this cross-tracker check._

---

## DATA_QUALITY deep dive

### 7.1 Age distribution of DATA_QUALITY items

Age is measured from the most recent modification to the line where the item was captured (git blame) or the creation date of the source document, whichever is older. Bucket midpoints; individual items may be a few days either side.

| Age band | Count | Items |
|---|---:|---|
| **≤ 7 days** | 4 | 43e (rescoped 2026-04-23), INF37 (cleared per findings 2026-04-23), DM13 (active surface 2026-04-22), DM14c / DM15d / DM15e (active surface 2026-04-22) |
| **7–30 days** | 4 | INF25 (re-dispatched after int-09 closure 2026-04-22), 43g, 56 (DM worldviews), DM15 umbrella-trusts audit parent |
| **30–60 days** | 5 | DM6, D10, D11, 48 D-series remainder, Rule A/B OTC tracking note |
| **60–90 days** | 3 | DERA 1,187 NULL-series synthetics, INF16 Soros AUM, INF27 (Standing — continuously refreshed but entry itself older) |
| **> 90 days** | 3 | INF38 / int-19 float history (open since original pct-of-so audit), INF2 monthly maintenance (Standing since beginning), 48 Phase 3.5 parent entry (D-series first filed conv-04 era) |

### 7.2 Known specifics — status citations

| Requested item | Current state | Source |
|---|---|---|
| **DM13** — 410 ADV suspicious relationships | OPEN — ~390 remaining after BlueCove cluster closed (`ef3f302`) | `docs/findings/dm-open-surface-2026-04-22.md:149`; `MAINTENANCE.md:393` (cites pre-BlueCove 410) |
| **DM14** | Layer 1 DONE per ROADMAP closed items (2026-04-15 to 2026-04-17); Layer 2 / `DM14c` Voya residual OPEN | `ROADMAP.md`; `docs/findings/dm-open-surface-2026-04-22.md:150` |
| **L4-1** | "L4 classification audit (13 categories)" PARKED — auto-memory `project_session_apr9_phase4.md` reports 11/13 complete, mixed + active remaining | `MAINTENANCE.md:397`; auto-memory |
| **L4-2** | Not a distinct ID in current trackers. Closest: 43g "drop redundant type columns" OPEN; or 48 D-series. | — |
| **N-PORT refresh** | Pipeline operational per `docs/NEXT_SESSION_CONTEXT.md §Pipeline framework`; no active refresh backlog item. DM3 "N-PORT metadata extension" deferred (blocked on D13). | `docs/NEXT_SESSION_CONTEXT.md`; `docs/findings/dm-open-surface-2026-04-22.md:26` |
| **INF27** — CUSIP residual-coverage | STANDING — pipeline handles automatically via `build_classifications.py` + `run_openfigi_retry.py`. Revisit trigger: net-increase in `pending` across two consecutive runs. | `docs/DEFERRED_FOLLOWUPS.md:14`; `ROADMAP.md:580,605` |
| **INF2** — monthly maintenance | STANDING (1st of each month). Not explicitly "run" anywhere in the open trackers. | `ROADMAP.md:581,607` |

### 7.3 DATA_QUALITY items with DM-family identifiers

- **Active surface (as of 2026-04-22)**: DM2, DM3, DM6, DM13, DM14c, DM15d, DM15e, DM15 umbrella-trusts parent entry.
- **Closed / collapsed**: DM1, DM4, DM5, DM7, DM8, DM9, DM10, DM11, DM12, DM13 (BlueCove pass only), DM14 (Layer 1), DM14b, DM15 (L5 audit), DM15b, DM15 Layer 2, DM15c.

---

## UI deep dive

### 7.3 UI item enumeration

| Item | Source | Notes |
|---|---|---|
| BL-5 Zustand scope enforcement | `ROADMAP.md:805` | — |
| BL-6 Loading state standardization | `ROADMAP.md:806` | — |
| D10 Admin UI for `entity_identifiers_staging` | `docs/findings/dm-open-surface-2026-04-22.md:154` | — |
| D11 Confidence-threshold auto-approve reader | `docs/findings/dm-open-surface-2026-04-22.md:155` | — |
| ARCH-4C-followup api.ts → api-generated.ts | `ROADMAP.md:810` | — |
| Rollback UI button (admin tab v2) | `docs/admin_refresh_system_design.md:922` | Design-doc item — not in a primary tracker. |
| `DataSourceTab.tsx` cadence timeline SVG | `web/react-app/src/components/tabs/DataSourceTab.tsx:99` | In-component TODO — not in a primary tracker. |
| Type-badge `family_office` color | `docs/NEXT_SESSION_CONTEXT.md:40`; `common/typeConfig.ts` | React leg of 43e. |

**UI item count: 8.**

### 7.4 UI specifics requested

| Requested check | Result |
|---|---|
| **Entity Graph LR rendering** (flagged in user memories) | Not found in any primary tracker as an open item in this branch. `web/react-app/src/components/tabs/EntityGraphTab.tsx` exists and is referenced by tests (`tabs.spec.ts`) per code-TODO agent. No React-side TODO flagging LR rendering specifically. **Not currently tracked in any primary source**. |
| **Expand trigger behavior verification** | Not found in any primary tracker or findings file in this branch. No TODO marker in React sources. **Not currently tracked in any primary source**. |
| **Admin dashboard React — recent issues** | None found in findings/closures. Design doc lists rollback-button-v2 + v3.3 reviewer-feedback-pending as the only admin-dashboard open items. |
| **Design-language drift from Oxford Blue `#002147`** | No drift flagged in any source. Reinforced in `docs/NEXT_SESSION_CONTEXT.md:265` ("primary color for all surfaces/decks") + `common/typeConfig.ts`. Code-TODO agent reports Oxford Blue "defined and used consistently across multiple tabs and components". |

### 7.5 Under-tracking assessment

UI item count (8) is conspicuously low given:

- `web/react-app/src/` has ~11 tab components + admin pages, none of which carry a TODO backlog file.
- `web/react-app/` has no `README.md`, `TODO.md`, `CHANGELOG.md`, or `backlog` file.
- Only **1** in-component TODO across all React sources.
- 3 of the 8 UI items live outside primary trackers (design doc, in-component TODO, in-brief NEXT_SESSION note).
- User memory flags "Entity Graph LR rendering" and "expand trigger behavior" as concerns; **neither appears in any primary or secondary tracker in this branch**.

**Meta-finding: UI is under-tracked.** Items likely exist in the team's working memory / user memory but are not written down in any doc that a future session would discover. See [Meta-findings](#meta-findings) for aggregation.

---

## Meta-findings

1. **`docs/REMEDIATION_PLAN.md` body is the largest single source of drift.** The document's own Changelog closes ~15 items that the body still describes as OPEN / PENDING. A doc-hygiene pass would either archive the body prose or annotate each closed section in-line.

2. **UI is better-catalogued than the first pass of this memo showed — but the catalog lives on an unmerged branch.** Initial Phase 2 swept `docs/findings/` and `docs/closures/` on `main`, which missed `docs/ui-audit-01-triage.md` (file lives at `docs/`, only on branch `ui-audit-01` / PR #107 OPEN, dated 2026-04-22). That 599-line triage captures 12 tabs, 26 endpoints, 21 `queries.py` functions + 4 inline-SQL blocks; surfaces 3 blockers (`is_latest=TRUE` inversion, `query1()` NoneType crash, `get_peer_rotation()` 11.4 s) + an 8-row prioritised precompute build plan + 2 React-only consolidations + 15 dead-endpoint candidates + 1 open traffic-dependent decision. **None of those items are filed in any primary tracker on `main`.** `NEXT_SESSION_CONTEXT.md:41` merely references "PR #107 ui-audit walkthrough — separate track, still open". 24 per-tab "Bugs (visual)" / "Completeness gaps" placeholder rows remain BLANK awaiting Serge's live-app walkthrough. Net: UI work pending is **well-documented on one branch and invisible from `main`**; the earlier "UI under-tracked" claim was right in spirit (nothing on `main` tracks it) but wrong in letter (rich documentation exists, just parked). Meta-lesson for Phase 2 of future backlog sweeps: enumerate open PR branches alongside `main` sources.

3. **DATA_QUALITY carry-forward is concentrated in the DM family.** 7 of 19 DATA_QUALITY items are DM-prefixed. DM13 / DM14c / DM15d / DM15e all surface on `dm-open-surface-2026-04-22.md`; DM2 / DM3 / DM6 are gated on pipeline work (D12 / D13 / N-1A parser). Without those pipeline items scheduled, the DM tail will continue to age.

4. **Plan-review findings from 2026-04-23 (`plan-review-2026-04-23.md`, `plan-review-v3-2026-04-23.md`) are internal to the plan document's own review cycle.** Items R1, R2, Q1, Q3, C1v3 were addressed in plan v3 or subsequent PRs; they are not backlog items to act on, but they do not carry explicit "closed" annotations. Catalogued in the appendix for completeness, not in the main category sections.

5. **`refinement-validation-2026-04-23.md` V-Q1 / V-Q3 / V-Q4** are PARTIAL verdicts whose actionable residuals (Makefile V2 invocation, three co-land cleanups) resolved via PR #141 (V-Q1) or remain pending with B3 (V-Q3). V-Q4 recommendation (move `migrate_batch_3a.py` → `scripts/oneoff/`) is not filed as a tracked backlog item anywhere else.

6. **`admin_refresh_system_design.md` §14 reviewer questions (Q1–Q8)** are stale — prompts p2-01 … p2-10-fix have all shipped, so several reviewer questions are functionally answered. The §14 block remains as-written, producing a false signal of open architectural questions. Items are catalogued here but flagged PROBABLY-MOOT.

7. **Four DOCS items trace back to a single 2026-04-22 `DEFERRED_FOLLOWUPS` batched-update entry** (`pct_of_float` → `pct_of_so` terminology + related). They are trivial individually but have sat "next batched doc-update" for ~30 days.

8. **Three architectural TODO pointers have no destination doc**: `docs/TESTING_STRATEGY.md`, `docs/OBSERVABILITY_PLAN.md`, `docs/SCHEMA_MIGRATIONS.md`. Each is referenced as a separate-doc TODO in `ARCHITECTURE_REVIEW.md` or the 2026-04-12 architecture-review-revision plan. None exists.

9. **Under-tracked documents**: `docs/closures/` holds only a `README.md` — no closure records have been filed there despite the `docs/findings/` index growing to 54 files + an index. If the intent was closure-paired-with-findings, the convention never took hold.

10. **Cross-tracker terminology is inconsistent for one item** (ops-18 / maintenance-audit-design / "rotate-audit-schedule" / "Phase C2 investigation" / "rotating_audit_schedule.md re-author"). Five labels for one item. A future session should pick one and update the others.

---

## Appendix — flat item list

One row per distinct item, sorted by category then by ID or title. `age` column is a rough band. `timing` per Phase 5.

| # | id | title | category | state | timing | source | age |
|---:|---|---|---|---|---|---|---|
| 1 | P2-FU-01 | Prune legacy `run_script` allowlist in `scripts/admin_bp.py` | PIPELINE | OPEN | GATED | `docs/DEFERRED_FOLLOWUPS.md:17`; `ROADMAP.md:587` | ~2d |
| 2 | P2-FU-03 | ADV SCD Type 2 conversion | PIPELINE | OPEN | UNSCOPED | `docs/DEFERRED_FOLLOWUPS.md:18`; `ROADMAP.md:588` | ~2d |
| 3 | — | V-Q3 co-land cleanups for B3 denorm drops | PIPELINE | OPEN | GATED | `docs/findings/refinement-validation-2026-04-23.md:146–237` | 1d |
| 4 | — | Cross-process rate limiter in `scripts/pipeline/shared.py` | PIPELINE | OPEN | UNSCOPED | `scripts/pipeline/shared.py:9,39` | — |
| 5 | int-23 Q7.1 | Hard-coded vs per-pipeline sensitive columns | PIPELINE | OPEN-QUESTION | UNSCOPED | `docs/findings/int-23-design.md:263–265` | 1d |
| 6 | int-23 Q7.2 | Fail-whole-run vs per-key partial | PIPELINE | OPEN-QUESTION | UNSCOPED | `docs/findings/int-23-design.md:265–267` | 1d |
| 7 | INF25 | BLOCK-DENORM-RETIREMENT Step 4 | DATA_QUALITY | OPEN | GATED | `ROADMAP.md:577,602`; `docs/DEFERRED_FOLLOWUPS.md:13` | ~12d |
| 8 | INF27 | CUSIP residual-coverage tracking | DATA_QUALITY | BACKGROUND | BACKGROUND | `ROADMAP.md:580,605`; `docs/DEFERRED_FOLLOWUPS.md:14` | ≥60d |
| 9 | INF37 | `backfill_manager_types` residual | DATA_QUALITY | STANDING (tracker) / CLEARED (findings) | — | `ROADMAP.md`; `docs/DEFERRED_FOLLOWUPS.md:15`; `docs/findings/entity-curation-w1-log.md` | 1d |
| 10 | INF38 / int-19 | BLOCK-FLOAT-HISTORY | DATA_QUALITY | OPEN | UNSCOPED | `ROADMAP.md:578,602`; `docs/DEFERRED_FOLLOWUPS.md:16` | ~30d |
| 11 | INF16 | Recompute Soros `aum_total` | DATA_QUALITY | OPEN | UNSCOPED | `ROADMAP.md:582,606` | ≥60d |
| 12 | 43e | Family-office classification + taxonomy refactor | DATA_QUALITY | RESCOPED | UNSCOPED | `ROADMAP.md:608`; `docs/findings/entity-curation-w1-log.md` | 1d |
| 13 | 43g | Drop redundant type columns | DATA_QUALITY | OPEN | UNSCOPED | `ROADMAP.md:583,609` | ~14d |
| 14 | DM2 | ADV Schedule 7.B re-parse | DATA_QUALITY | DEFERRED | GATED | `docs/findings/dm-open-surface-2026-04-22.md:25` | ~2d |
| 15 | DM3 | N-PORT metadata extension | DATA_QUALITY | DEFERRED | GATED | `docs/findings/dm-open-surface-2026-04-22.md:26` | ~2d |
| 16 | DM6 | N-1A prospectus / SAI parser | DATA_QUALITY | DEFERRED | UNSCOPED | `docs/findings/dm-open-surface-2026-04-22.md:28`; `ROADMAP.md:865` | ~2d |
| 17 | DM13 | ADV_SCHEDULE_A residual sweep (~390 rows) | DATA_QUALITY | OPEN | UNSCOPED | `docs/findings/dm-open-surface-2026-04-22.md:149`; `MAINTENANCE.md:393` | ~2d |
| 18 | DM14c | Voya residual ($21.81B / 49 funds) | DATA_QUALITY | OPEN | GATED | `docs/findings/dm-open-surface-2026-04-22.md:150` | ~2d |
| 19 | DM15 | Umbrella-trusts audit parent (~132 series, ~$105B) | DATA_QUALITY | DEFERRED | UNSCOPED | `ROADMAP.md:879` | ~10d |
| 20 | DM15d | N-CEN-resolvable umbrella trusts (3) | DATA_QUALITY | OPEN | UNSCOPED | `docs/findings/dm-open-surface-2026-04-22.md:151` | ~2d |
| 21 | DM15e | Prospectus-blocked umbrella trusts (7) | DATA_QUALITY | DEFERRED | GATED | `docs/findings/dm-open-surface-2026-04-22.md:152`; `ROADMAP.md:879` | ~2d |
| 22 | 48 | Phase 3.5 deferred (D2/D4/D5/D12/D13) | DATA_QUALITY | PARTIAL | UNSCOPED | `ROADMAP.md:585,611` | ≥90d |
| 23 | 56 | DM & voting rollup worldviews (DM1–DM7) | DATA_QUALITY | NOT-STARTED | UNSCOPED | `ROADMAP.md:586,612` | ≥30d |
| 24 | — | DERA 1,187 NULL-series synthetics | DATA_QUALITY | PARKED | UNSCOPED | `docs/data_layers.md:92` | ≥60d |
| 25 | — | Rule A/B OTC classification tracking note | DATA_QUALITY | PARTIAL | UNSCOPED | `docs/data_layers.md:96` §6 S1 | ≥30d |
| 26 | BL-5 | Zustand scope enforcement | UI | OPEN | UNSCOPED | `ROADMAP.md:805` | ~14d |
| 27 | BL-6 | Loading state standardization | UI | OPEN | UNSCOPED | `ROADMAP.md:806` | ~14d |
| 28 | D10 | Admin UI for `entity_identifiers_staging` review | UI | PARTIAL | UNSCOPED | `docs/findings/dm-open-surface-2026-04-22.md:154` | ≥30d |
| 29 | D11 | Confidence-threshold auto-approve reader | UI | PARTIAL | UNSCOPED | `docs/findings/dm-open-surface-2026-04-22.md:155` | ≥30d |
| 30 | ARCH-4C-followup | React api.ts → api-generated.ts | UI | OPEN | GATED | `ROADMAP.md:810` | ~14d |
| 31 | — | Rollback UI button (admin tab v2) | UI | PARKED | UNSCOPED | `docs/admin_refresh_system_design.md:922` | ~30d |
| 32 | — | `DataSourceTab.tsx` cadence timeline SVG (p2-06) | UI | OPEN | UNSCOPED | `web/react-app/src/components/tabs/DataSourceTab.tsx:99` | — |
| 33 | — | Type-badge `family_office` color | UI | OPEN | GATED | `docs/NEXT_SESSION_CONTEXT.md:40`; `common/typeConfig.ts` | 1d |
| 34 | snapshot-retention-cadence | Wire `snapshot_retention.py --apply` onto a recurring surface | INFRA | OPEN | UNSCOPED | `docs/NEXT_SESSION_CONTEXT.md:34` | 0d |
| 35 | — | `audit_tracker_staleness.py` not wired to pre-commit | INFRA | PARTIAL | UNSCOPED | `docs/SESSION_GUIDELINES.md:156` | — |
| 36 | G10 | GitHub Actions smoke CI (ARCHITECTURE_REVIEW snapshot) | INFRA | PARTIAL (likely stale) | UNSCOPED | `ARCHITECTURE_REVIEW.md:180` | ~40d |
| 37 | — | PROCESS_RULES Rule 9 dry-run default uniformity | INFRA | PARTIAL | UNSCOPED | `docs/PROCESS_RULES.md:101–105` | ≥60d |
| 38 | — | PROCESS_RULES Rule 3 — 13F single-source | INFRA | PARTIAL | UNSCOPED | `docs/PROCESS_RULES.md:29–36` | ≥60d |
| 39 | phase-b3 | Retire V1 loader + drop denorm columns | ARCHITECTURE | OPEN | GATED | `docs/NEXT_SESSION_CONTEXT.md:33` | 0d |
| 40 | multi-db-datasetspec | `DatasetSpec.db_file` field + caller updates | ARCHITECTURE | OPEN | GATED | `docs/NEXT_SESSION_CONTEXT.md:36`; `ROADMAP.md:591` | 0d |
| 41 | admin_preferences | Register or retire migration-016 stub | ARCHITECTURE | OPEN | GATED | `docs/NEXT_SESSION_CONTEXT.md:37`; `ROADMAP.md:590` | 0d |
| 42 | registry-gap-sweep | Remaining 2 tables (`admin_sessions`, `cusip_classifications`) | ARCHITECTURE | PARTIAL | GATED | `ROADMAP.md:589`; `docs/plans/…-phase-b-c…md §8.4` | 0d |
| 43 | G1 | Untyped API contract | ARCHITECTURE | OPEN | UNSCOPED | `ARCHITECTURE_REVIEW.md:113–132` | ≥40d |
| 44 | G2 | No standardised error contract | ARCHITECTURE | OPEN | UNSCOPED | `ARCHITECTURE_REVIEW.md:133` | ≥40d |
| 45 | G6 | `scripts/app.py` monolith | ARCHITECTURE | PARTIAL | UNSCOPED | `ARCHITECTURE_REVIEW.md:153` | ≥40d |
| 46 | G7 | `scripts/queries.py` monolith | ARCHITECTURE | PARTIAL | UNSCOPED | `ARCHITECTURE_REVIEW.md:158` | ≥40d |
| 47 | BL-2 | Pipeline dependency enforcement | ARCHITECTURE | OPEN | UNSCOPED | `ROADMAP.md:802` | ~30d |
| 48 | BL-3 | Write-path consistency (non-entity) | ARCHITECTURE | OPEN | UNSCOPED | `ROADMAP.md:803` | ~30d |
| 49 | BL-4 | Three snapshot roles documented | ARCHITECTURE | OPEN | UNSCOPED | `ROADMAP.md:804` | ~30d |
| 50 | BL-7 | DB-universe ticker validation at route layer | ARCHITECTURE | OPEN | UNSCOPED | `ARCHITECTURE_REVIEW.md:715` | ≥30d |
| 51 | — | `portfolio_context` precompute re-trigger | ARCHITECTURE | PARKED | UNSCOPED | `ARCHITECTURE_REVIEW.md:467–476` | ~12d |
| 52 | INF28 | `securities.cusip` VALIDATOR_MAP registration | ARCHITECTURE | OPEN | UNSCOPED | `docs/data_layers.md:96,136` | ≥30d |
| 53 | P2-FU-04 | ADV ownership boundary cross-ref (closed — note stale) | ARCHITECTURE | OPEN (annotation) | UNSCOPED | `docs/data_layers.md:47` | ~2d |
| 54 | §14 Q2 | Admin diff-presentation tier boundaries | ARCHITECTURE | OPEN | UNSCOPED | `docs/admin_refresh_system_design.md:980` | ≥30d |
| 55 | §14 Q7 | `PIPELINE_CADENCE` vs SEC rules | ARCHITECTURE | OPEN | UNSCOPED | `docs/admin_refresh_system_design.md:987` | ≥30d |
| 56 | §14 Q8 | Probe rate-limit safety | ARCHITECTURE | OPEN | UNSCOPED | `docs/admin_refresh_system_design.md:988` | ≥30d |
| 57 | maintenance-audit-design | Re-author `rotating_audit_schedule.md` | DOCS | OPEN | UNSCOPED | `docs/NEXT_SESSION_CONTEXT.md:38`; `ROADMAP.md:579` | 1d |
| 58 | — | `docs/TESTING_STRATEGY.md` | DOCS | TODO | UNSCOPED | `ARCHITECTURE_REVIEW.md:197` | ≥40d |
| 59 | — | `docs/OBSERVABILITY_PLAN.md` | DOCS | TODO | UNSCOPED | `ARCHITECTURE_REVIEW.md:199` | ≥40d |
| 60 | — | `docs/SCHEMA_MIGRATIONS.md` | DOCS | TODO | UNSCOPED | `archive/docs/plans/20260412_architecture_review_revision.md` R2 | ~12d |
| 61 | — | Rename `block/pct-of-float…` → `block/pct-of-so…` across findings docs | DOCS | OPEN | UNSCOPED | `docs/DEFERRED_FOLLOWUPS.md:56` | ~30d |
| 62 | — | `pct_of_float` → `pct_of_so` terminology retirement | DOCS | OPEN | UNSCOPED | `docs/DEFERRED_FOLLOWUPS.md:57` | ~30d |
| 63 | — | `docs/data_layers.md §7` — add `pct_of_so_source` audit column | DOCS | OPEN | UNSCOPED | `docs/DEFERRED_FOLLOWUPS.md:58` | ~30d |
| 64 | — | `docs/pipeline_violations.md` — close `pct_of_float` violation entries | DOCS | OPEN | UNSCOPED | `docs/DEFERRED_FOLLOWUPS.md:59` | ~30d |
| 65 | v3.3 | Incorporate reviewer feedback into admin-refresh v3.3 | DOCS | PENDING (likely moot) | UNSCOPED | `docs/admin_refresh_system_design.md:990` | ≥30d |
| 66 | §14 Q1 | Migration 008 exec-order decision | DOCS | OPEN (likely moot) | UNSCOPED | `docs/admin_refresh_system_design.md:964–972` | ≥40d |
| 67 | — | SESSION_GUIDELINES §5 enforcement automation | DOCS | PARTIAL | UNSCOPED | `docs/SESSION_GUIDELINES.md:144–156` | ~2d |
| 68 | finra-default-flip | Delete deprecation path + require mutex | OPS | SCHEDULED | 2026-07-23 | `docs/NEXT_SESSION_CONTEXT.md:35`; `MAINTENANCE.md:183` | 0d |
| 69 | INF2 | Monthly maintenance checklist | OPS | BACKGROUND | BACKGROUND | `ROADMAP.md:581,607` | ≥90d |
| 70 | L4 audit | Classification categories (13) | OPS | PARKED | UNSCOPED | `MAINTENANCE.md:397` | ≥90d |
| 71 | L5 audit | Parents 201–720 (batches of 100) | OPS | PARKED | UNSCOPED | `MAINTENANCE.md:396` | ≥30d |
| 72 | DM14 / DM15 L1 | External sub-adviser + intra-firm sub-adviser audits | OPS | MIXED (tracker drift) | — | `MAINTENANCE.md:394,395`; `docs/data_layers.md:393,394` | ≥14d |
| 73 | — | Auto-refresh scheduler (cron) | OPS | PARKED | UNSCOPED | `docs/admin_refresh_system_design.md:922` | ≥30d |
| 74 | — | Prometheus metrics | OPS | PARKED | UNSCOPED | `docs/admin_refresh_system_design.md:922` | ≥30d |
| 75 | — | Multi-user roles on admin | OPS | PARKED (out-of-scope) | UNSCOPED | `docs/admin_refresh_system_design.md:922` | ≥30d |
| 76 | 43b | `scripts/app.py` hardening (B110, B603/B607, B104) | SECURITY | OPEN | UNSCOPED | `ROADMAP.md:584,610` | ≥30d |
| 77 | ui-audit-01 bug-1 | `is_latest=TRUE` inversion on prod DB for 2025Q4 | DATA_QUALITY | OPEN (verify vs int-22 post-date) | UNSCOPED | `docs/ui-audit-01-triage.md` §Technical anomalies #1 (branch `ui-audit-01`) | 2d |
| 78 | ui-audit-01 bug-2 | `query1()` NoneType crash at `queries.py:933` | PIPELINE | OPEN BLOCKER | UNSCOPED | `docs/ui-audit-01-triage.md` §Technical anomalies #2 | 2d |
| 79 | ui-audit-01 perf-P0 | `peer_rotation_by_ticker` + `peer_rotation_detail_by_pair` precomputed tables | PIPELINE | OPEN | UNSCOPED | `docs/ui-audit-01-triage.md` §Precompute build plan P0 | 2d |
| 80 | ui-audit-01 perf-P1 | `sector_flows_rollup` + `sector_flow_movers` + `cohort_by_ticker_from` precomputed tables | PIPELINE | OPEN | UNSCOPED | `docs/ui-audit-01-triage.md` §Precompute build plan P1 | 2d |
| 81 | ui-audit-01 perf-P2 | `flow_analysis_by_ticker_period` + `market_summary_top25` + `holder_momentum_by_ticker` precomputed tables | PIPELINE | OPEN | UNSCOPED | `docs/ui-audit-01-triage.md` §Precompute build plan P2 | 2d |
| 82 | ui-audit-01 open-q | `short_interest_analysis()` precompute-vs-live decision | PIPELINE | OPEN-QUESTION | UNSCOPED | `docs/ui-audit-01-triage.md` §Short Interest | 2d |
| 83 | ui-audit-01 React-1 | Consolidate `/api/v1/tickers` into shared hook | UI | OPEN | UNSCOPED | `docs/ui-audit-01-triage.md` §Work item routing | 2d |
| 84 | ui-audit-01 React-2 | Collapse duplicate `/api/v1/entity_search` in EntityGraphTab | UI | OPEN | UNSCOPED | `docs/ui-audit-01-triage.md` §Work item routing | 2d |
| 85 | ui-audit-01 walkthrough | 24 blank per-tab "Bugs (visual)" + "Completeness gaps" rows | UI | OPEN | GATED | `docs/ui-audit-01-triage.md` §per-tab sections | 2d |
| 86 | ui-audit-01 dead-endpoints | 15 router-defined but tab-uncalled routes — triage (delete vs keep) | ARCHITECTURE | OPEN | UNSCOPED | `docs/ui-audit-01-triage.md` §Technical anomalies #5 | 2d |

---

_End of memo. No edits to any tracker, script, or DB occurred in this session. 10 drift items surfaced (§Cross-tracker drift) — reconciliation out of scope. Memo revised 2026-04-24 to incorporate the `ui-audit-01` branch triage file (missed in initial Phase 2 sweep; now catalogued)._
