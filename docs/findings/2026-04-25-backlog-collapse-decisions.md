# Backlog-collapse decisions — 2026-04-25

> Authoritative decision list from triage of 86 items in `docs/findings/2026-04-24-consolidated-backlog.md`.
> Used as input for the `backlog-collapse` Code session.
> Do NOT alter; if the session finds a real conflict between this list and main state, STOP and surface.

## Bucket counts

- KILL: 23
- DEFER-WITH-TRIGGER: 36 entries below — dedupe cross-category duplicates to one entry per distinct item when writing ROADMAP. Expect ~30 distinct entries after dedup.
- COMMIT: 17 across P0/P1/P2/P3
- SCHEDULED: 1 (finra-default-flip — 2026-07-23)
- AMBIENT: 2 (move to MAINTENANCE.md)
- DECIDE NOW resolved: 1 (ui-audit-01 short_interest = keep live)
- SPLIT actions: 2 (DM15 parent, registry-gap parent)

---

## KILL — 23 items (remove from all primary trackers)

For each KILL: remove rows in ROADMAP, DEFERRED_FOLLOWUPS (before that file is archived), MAINTENANCE.md, and any other primary tracker. Findings files referencing the item stay as-is (point-in-time records). Add a one-line rationale to `docs/findings/2026-04-25-backlog-collapse.md` (the closure-rationale memo created in this session).

1. **P2-FU-03 ADV SCD Type 2 conversion** — No downstream consumer asking. Speculative.
2. **Cross-process rate limiter** (`scripts/pipeline/shared.py` code TODO) — Triggers a future move (parallel subprocess dispatch) that isn't planned. YAGNI.
3. **int-23 Q7.1** (hard-coded vs per-pipeline sensitive columns) — Design question made moot by shipped impl.
4. **int-23 Q7.2** (fail-whole-run vs per-key partial) — Same as Q7.1.
5. **INF37 backfill_manager_types residual** — Cleared 2026-04-23 per `docs/findings/entity-curation-w1-log.md`. Pure tracker drift.
6. **Rule A/B OTC classification tracking note** — Substantive work shipped via int-13/migration 012; tracking note in `docs/data_layers.md` body just unstruck.
7. **G10 GitHub Actions smoke CI** — Likely CLOSED per auto-memory; tracker drift.
8. **P2-FU-04 ADV ownership boundary cross-ref annotation** — CLOSED per DEFERRED_FOLLOWUPS; body annotation never struck.
9. **v3.3 admin_refresh_system_design reviewer feedback** — Implementation prompts shipped (p2-01 through p2-10-fix). Feedback addressed in shipping.
10. **§14 Q1 Migration 008 exec order decision** — Migration 008 has shipped. Question moot.
11. **§14 Q2 Admin diff-presentation tier boundaries** — Reviewer question on shipped system. If wrong, would have surfaced.
12. **§14 Q8 Probe rate-limit safety** — Same — probes have been running without issue.
13. **G6 scripts/app.py monolith** — Blueprint split Batch 4-A complete. No named next split. Remaining concern absorbed by completed work.
14. **BL-2 Pipeline dependency enforcement (Makefile/DAG)** — SourcePipeline + `expected_delta` + `PIPELINE_CADENCE` probes effectively absorb this.
15. **D11 Confidence-threshold auto-approve reader** — Flag-based auto-approve shipped and works. Reader is feature-creep without a use case.
16. **Rollback UI button (admin tab v2)** — Rollback endpoint works via API. UI polish on admin-only feature used infrequently.
17. **docs/TESTING_STRATEGY.md** ghost doc — Pointer in ARCHITECTURE_REVIEW; doc never written. 40+ days. Write directly when needed.
18. **docs/OBSERVABILITY_PLAN.md** ghost doc — Same pattern.
19. **docs/SCHEMA_MIGRATIONS.md** ghost doc — Same pattern.
20. **Prometheus metrics** — Speculative observability for single-operator local app.
21. **Multi-user roles on admin** — Tied to hosted/multi-user world. Reopen via data-store-spec if/when that arrives.
22. **DM14/DM15 Layer 1 entries in MAINTENANCE.md "Open audits"** — DONE per ROADMAP/auto-memory; MAINTENANCE.md is stale.
23. **Item 48 D-series parent + D2/D4/D5 children** — D2 (pymupdf recall), D4 (match quality), D5 (IAPD). No defense offered for the children; parent is meta-work.

---

## DEFER-WITH-TRIGGER

When writing the ROADMAP "Deferred backlog" table, dedupe cross-category duplicates to one entry per distinct item. Triggers below are authoritative.

| Item | Trigger |
|---|---|
| P2-FU-01 (run_script allowlist prune) | Q1 2026 cycle runs clean on V2 |
| V-Q3 co-land cleanups for B3 denorm drops | B3 dispatch |
| ui-audit-01 perf-P2 (flow_analysis + market_summary + holder_momentum precompute) | perf-P0 + perf-P1 shipped AND latency complaints persist |
| INF25 Step 4 / int-09 architectural leg (denorm retirement) | B3 dispatch |
| INF38 / int-19 BLOCK-FLOAT-HISTORY | Float-history data source acquired (10-K / 13D / Forms 3-5 ingestion) |
| 43e family-office taxonomy | Next classification taxonomy work |
| 43g — drop redundant type columns | B3 OR first session touching holdings_v2 query patterns |
| DM2 ADV 7.B re-parse | D12 Phase 3.5b ADV Section 7.B re-parse |
| DM3 N-PORT metadata extension | D13 Phase 3.5c fetch_nport.py metadata extension |
| DM6 N-1A prospectus parser | Activist defense workflow OR specific N-1A use case emerges |
| DM14c Voya residual | DM14b edge-completion (Voya edge missing) |
| DM15e prospectus-blocked umbrella trusts (7) | Ad-hoc manual override session when any of the 7 trusts becomes analytically important |
| DERA 1,187 NULL-series synthetics | Next N-PORT data quality sweep |
| Item 56 DM & voting rollup worldviews | Voting-vs-economic gap becomes analytically important (activist defense or proxy contest) |
| BL-5 Zustand scope enforcement | Next substantial React refactor session |
| BL-6 Loading state standardization | Next substantial React refactor session |
| D10 Admin UI for entity_identifiers_staging | Next admin UI iteration |
| ARCH-4C-followup React api.ts → api-generated.ts | scripts/schemas.py expanded for ~55 response types |
| DataSourceTab.tsx cadence timeline SVG | ui-audit-01 walkthrough surfaces this as user-visible pain |
| Type-badge family_office color | Bundled with 43e taxonomy refactor |
| phase-b3 (retire V1 + drop denorm columns) | Q1+Q2 2026 cycles run clean on V2 (~mid-Aug 2026) |
| data-store-spec (replaces multi-db-datasetspec) | Post-B3; broader design for hosted/Postgres migration |
| admin_sessions registration | data-store-spec implementation |
| admin_preferences register-or-retire | data-store-spec implementation OR admin feature set next revisited |
| G1 Untyped API contract | ARCH-4C-followup session |
| G2 No standardised error contract | ARCH-4C-followup session |
| G7 scripts/queries.py monolith | queries.py touches become painful (merge conflicts, load-time regressions) |
| BL-3 Write-path consistency (non-entity) | Non-entity write-path bug surfaces in prod |
| BL-7 DB-universe ticker validation at route layer | Actual ticker-not-found error surfaces for a valid ticker |
| portfolio_context precompute re-trigger | Latency exceeds ~1s consistently (currently 730ms) |
| §14 Q7 PIPELINE_CADENCE correctness vs SEC rules | SEC rule change OR cycle surfaces timing mismatch |
| maintenance-audit-design (rotating audit re-author) | Audit surfaces ready to be implemented as runnable programs |
| categorized-funds-csv-relocate | Next session touching scripts/backfill_manager_types.py:39 (already on ROADMAP from PR #151) |
| PROCESS_RULES Rule 9 dry-run uniformity | Next session touching a non-finra pipeline script's CLI |
| PROCESS_RULES Rule 3 13F single-source failover | EDGAR outage causes a missed cycle |
| Auto-refresh scheduler (cron) | First time auto-refresh would have prevented an issue |

---

## COMMIT — 17 items (move to ROADMAP "Current backlog" P0/P1/P2/P3)

### P0 — Production blockers

- **bug-1 (ui-audit-01)** — `is_latest=TRUE` inversion on 2025Q4 prod DB. Breaks `/api/v1/tickers`, `/api/v1/fund_portfolio_managers`, `/api/v1/portfolio_context`, most 2025Q4-filtering queries. **First action: verify vs int-22 rollback (2026-04-22) — if rollback addressed it, close immediately. Otherwise jumps ahead of all other work.** Source: `docs/ui-audit-01-triage.md` (PR #107).
- **bug-2 (ui-audit-01)** — `query1()` NoneType crash at `queries.py:933`. One-line null guard. Source: `docs/ui-audit-01-triage.md`.

### P1 — Active commitments

- **ui-audit-walkthrough** — 24 per-tab "Bugs (visual)" + "Completeness gaps" blank rows in `docs/ui-audit-01-triage.md` need Serge+Claude live walkthrough. 1-2 hr; not a Code session.
- **perf-P0** — `peer_rotation_by_ticker` + `peer_rotation_detail_by_pair` precomputed tables. Cures 11.4s cold/warm. New `compute_peer_rotation.py` + `SourcePipeline` subclass. ~2-3 days.
- **audit-tracker-staleness-ci** — Wire `scripts/hygiene/audit_tracker_staleness.py` to pre-commit + CI. Discipline anchor for ROADMAP-only model. Pairs with SESSION_GUIDELINES §5 update.
- **43b SECURITY hardening** — `scripts/app.py`: B110 (8 exception swallows), B603/B607 (subprocess allowlist), B104 (`0.0.0.0` → `localhost`). 1-2 hr session.

### P2 — Next sprint

- **perf-P1** — `sector_flows_rollup` + `sector_flow_movers_by_quarter_sector` + `cohort_by_ticker_from` precompute. Ships after perf-P0. ~3 days combined.
- **DM13** — ADV Schedule A residual sweep (~390 suspicious rows after BlueCove cluster closed). Staging workflow.
- **DM15d** — N-CEN-resolvable umbrella trusts (Sterling, NEOS, Segall Bryant). Extend DM15b/Layer 2 pattern via `ncen_adviser_map`.
- **snapshot-retention-cadence** — Wire `scripts/hygiene/snapshot_retention.py --apply` to recurring surface (cron / Makefile / scheduler). 30-min design + impl.
- **pct-rename-sweep** — Bundle 4 DEFERRED_FOLLOWUPS items as one session: rename `block/pct-of-float-period-accuracy` → `block/pct-of-so-period-accuracy` across findings; `pct_of_float` → `pct_of_so` terminology retirement project-wide; `data_layers.md §7` add `pct_of_so_source` as Class B audit column; `pipeline_violations.md` close `pct_of_so` violation entries with Phase 1b/1c/4b citations.

### P3 — Quick wins / low priority

- **INF16** — Recompute `managers.aum_total` for two Soros CIKs (CIK 0001029160, 0001748240). 30 min staging workflow.
- **React-1 (ui-audit-01)** — Consolidate `/api/v1/tickers` into shared hook (TickerInput, CrossOwnershipTab, OverlapAnalysisTab). <0.5 day.
- **React-2 (ui-audit-01)** — Collapse duplicate `/api/v1/entity_search` call in `EntityGraphTab.tsx` (L125 + L230).
- **dead-endpoints (ui-audit-01)** — Triage 15 router-defined uncalled routes (delete vs modal-only keep). ~1 hr.
- **BL-4** — Document three snapshot roles (serving / rollback / archive). 30-min doc session.
- **cusip-classifications-registry** — Add `cusip_classifications` to `DATASET_REGISTRY` (single DatasetSpec, no multi-DB).
- **INF28** — `securities.cusip` VALIDATOR_MAP formal registration. ~15 min.

---

## SCHEDULED

- **finra-default-flip** — 2026-07-23. Delete deprecation-warning path in `scripts/fetch_finra_short.py` + require explicit `--apply`/`--dry-run`. ROADMAP entry retained in its own SCHEDULED section; no action until date.

---

## AMBIENT — move to MAINTENANCE.md (NOT backlog)

- **INF27 CUSIP residual-coverage** → MAINTENANCE.md §Standing curation. Pipeline handles automatically via `build_classifications.py` + `run_openfigi_retry.py`. Revisit trigger: net-increase in `pending` rows across two consecutive runs.
- **INF2 monthly maintenance** → MAINTENANCE.md §Monthly maintenance. 1st of each month: `validate_entities.py`, `manual_routing_review` gate, `diff_staging.py`.

---

## DECIDE NOW (resolved)

- **ui-audit-01 short_interest precompute** — KEEP LIVE (130ms warm acceptable). Not committing to precompute unless traffic shifts. Document decision in collapse memo; remove from open list.

---

## SPLIT actions

- **DM15 umbrella-trusts audit parent row** — DELETE the parent. Children DM15d (COMMIT P2) and DM15e (DEFER) handled individually.
- **registry-gap-sweep parent** — SPLIT: `cusip_classifications` → COMMIT P3; `admin_sessions` → DEFER on data-store-spec.

---

## Tracker collapse actions (file-level)

1. **Archive** `docs/REMEDIATION_PLAN.md` → `archive/docs/REMEDIATION_PLAN.md` with closure header.
2. **Archive** `docs/DEFERRED_FOLLOWUPS.md` → `archive/docs/DEFERRED_FOLLOWUPS.md` with closure header.
3. **Rewrite** `ROADMAP.md` per the structure in the kickoff prompt — preserve any existing Closed log section verbatim.
4. **Rewrite** `docs/NEXT_SESSION_CONTEXT.md` to single-session-handoff form per the kickoff prompt.
5. **Update** `docs/SESSION_GUIDELINES.md` §5 per the kickoff prompt.
6. **Update** `MAINTENANCE.md` — add §Standing curation (INF27) and §Monthly maintenance (INF2); remove DM14/DM15 Layer 1 entries from "Open audits"; reconcile DM13 row to "~390 suspicious rows after BlueCove cluster closed" or remove.
7. **Update** `archive/docs/README.md` — add 2026-04-25 backlog-collapse section.
8. **Create** `docs/findings/2026-04-25-backlog-collapse.md` — closure-rationale memo with KILL list rationales (use the rationales from KILL section above).
9. **Inbound reference sweep** — `git grep -n "REMEDIATION_PLAN\|DEFERRED_FOLLOWUPS"` excluding `archive/` and the two collapse memos; update active references to point at `archive/docs/<filename>` with note "(archived 2026-04-25)". Historical references inside `docs/findings/` files left as-is.

## Closure header text (for archived docs)

Insert at the top of each archived doc immediately after archival, in a quote block:

```
> # ARCHIVED 2026-04-25
>
> This document was retired during backlog-collapse (PR #N). Forward work lives in ROADMAP.md. This file remains as historical narrative of the remediation program (closed 2026-04-22) and follow-up tracking through 2026-04-24.
>
> Do NOT add new entries here. ROADMAP.md is the only forward-work tracker.
```
