# Backlog-collapse closure memo — 2026-04-25

- **Date:** 2026-04-25
- **Session:** backlog-collapse
- **HEAD at start of session:** `eab5f64` (main, post repo-cleanup + decisions list commit)
- **Source memo:** [docs/findings/2026-04-24-consolidated-backlog.md](2026-04-24-consolidated-backlog.md) — full triage of 86 items across the open trackers
- **Decisions file:** [docs/findings/2026-04-25-backlog-collapse-decisions.md](2026-04-25-backlog-collapse-decisions.md) — authoritative bucketing applied in this session

## Summary counts

| Bucket | Count |
|---|---|
| KILL (removed from all primary trackers) | 23 |
| DEFER-WITH-TRIGGER (in `ROADMAP.md` "Deferred") | 36 entries from the decisions file |
| COMMIT (in `ROADMAP.md` "Current backlog") | 17 (P0=2, P1=4, P2=5, P3=7 — 18 rows; off-by-one between the bucket-count line and the section bodies in the decisions file, reconciled to 18 rows here) |
| SCHEDULED | 1 (`finra-default-flip` — 2026-07-23) |
| AMBIENT (moved to `MAINTENANCE.md`) | 2 (INF27, INF2) |
| DECIDE-NOW resolved | 1 (`ui-audit-01` short_interest — KEEP LIVE; 130ms warm acceptable) |
| SPLIT actions | 2 (DM15 parent → children; registry-gap-sweep parent → P3 + DEFER) |

## KILL list — 23 items with rationales

Verbatim rationales from `docs/findings/2026-04-25-backlog-collapse-decisions.md` § KILL.

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

## SPLIT actions executed

- **DM15 umbrella-trusts audit parent row** — DELETED. Children handled individually: DM15d → COMMIT P2 (N-CEN-resolvable trusts), DM15e → DEFER (prospectus-blocked umbrella trusts).
- **registry-gap-sweep parent** — SPLIT: `cusip_classifications` → COMMIT P3, `admin_sessions` → DEFER on data-store-spec.

## DECIDE-NOW resolved

- **ui-audit-01 short_interest precompute** — KEEP LIVE (130ms warm acceptable). Not committing to precompute unless traffic shifts. Removed from open list; no ROADMAP entry.

## Tracker collapse summary

Files archived to `archive/docs/` with closure header:

- `docs/REMEDIATION_PLAN.md` → `archive/docs/REMEDIATION_PLAN.md`
- `docs/DEFERRED_FOLLOWUPS.md` → `archive/docs/DEFERRED_FOLLOWUPS.md`

Files rewritten:

- `ROADMAP.md` — header + Current backlog (P0–P3) + Scheduled + Deferred + Ambient + preserved Closed log (verbatim from prior `## COMPLETED` section).
- `docs/NEXT_SESSION_CONTEXT.md` — reset to single-session-handoff form (Last completed / Up next / Reminders).
- `docs/SESSION_GUIDELINES.md §5` — replaced "Tracker source-of-truth" with the ROADMAP-only model. §3 reconciled to remove archived trackers from the active list.

Files updated:

- `MAINTENANCE.md` — added §Standing curation (INF27) and updated §Monthly maintenance (INF2 + `diff_staging.py` step). Removed DM14/DM15 Layer 1 rows from "Pending Audit Work"; reconciled DM13 row to "~390 suspicious rows after BlueCove cluster closed" with pointer to `ROADMAP.md` "Current backlog" P2.
- `archive/docs/README.md` — added "## 2026-04-25 backlog-collapse session" entries listing the two archivals with rationale.

## Forward state

`ROADMAP.md` is the single source of truth for forward work. The cross-tracker discipline is enforced by `scripts/hygiene/audit_tracker_staleness.py` (P1: wire to pre-commit + CI as `audit-tracker-staleness-ci`).
