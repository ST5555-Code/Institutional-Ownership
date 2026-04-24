# Findings — index

Per-session investigation + decision-quality writeups. One file per finding.
Trackers (`ROADMAP.md`, `docs/REMEDIATION_PLAN.md`, `docs/DEFERRED_FOLLOWUPS.md`,
`docs/NEXT_SESSION_CONTEXT.md`) link here for context rather than inlining
the prose — see `docs/SESSION_GUIDELINES.md §5` for the source-of-truth rule.

| Date | File | Topic |
|---|---|---|
| 2026-04-24 | [2026-04-24-snapshot-inventory.md](2026-04-24-snapshot-inventory.md) | 292 `%_snapshot_%` tables inventoried + classified; policy closure note at §8 |
| 2026-04-23 | [2026-04-23-ops-18-investigation.md](2026-04-23-ops-18-investigation.md) | ops-18 prior-knowledge reframe — outcome **PARTIAL** (scope + cadence recovered) |
| 2026-04-23 | [comprehensive-audit-2026-04-23.md](comprehensive-audit-2026-04-23.md) | Phase A audit inputs for the Phase B / C execution plan |
| 2026-04-23 | [pre-phase-b-verification-2026-04-23.md](pre-phase-b-verification-2026-04-23.md) | Live verification of audit claims before Phase B start |
| 2026-04-23 | [plan-review-2026-04-23.md](plan-review-2026-04-23.md) | Plan v2 critique (R1–R5) |
| 2026-04-23 | [plan-review-v3-2026-04-23.md](plan-review-v3-2026-04-23.md) | Plan v3 critique (C1 + M1–M4) |
| 2026-04-23 | [refinement-validation-2026-04-23.md](refinement-validation-2026-04-23.md) | Plan v3 refinement validation |
| 2026-04-23 | [entity-curation-w1-log.md](entity-curation-w1-log.md) | Wave-1 manager-type curation log (INF37 + int-21 SELF + 43e re-scope) |
| 2026-04-23 | [inf9-closure.md](inf9-closure.md) | INF9 Route A overrides persistence closure |
| 2026-04-22 | [dm-open-surface-2026-04-22.md](dm-open-surface-2026-04-22.md) | DM worldview open-surface map |
| 2026-04-22 | [int-22-p0-findings.md](int-22-p0-findings.md) | Prod `is_latest` inversion on `holdings_v2` 2025Q4 |
| 2026-04-22 | [int-23-p0-findings.md](int-23-p0-findings.md) | Loader idempotency gap — Phase 0 |
| 2026-04-22 | [int-23-design.md](int-23-design.md) | Loader idempotency fix — design |
| 2026-04-22 | [phantom-other-managers-decision.md](phantom-other-managers-decision.md) | Phantom `other_managers` decision writeup (PR #125 reference) |
| Remediation program | `int-01-p0-findings.md` … `int-23-p0-findings.md` | Per-ticket Phase 0 findings (Theme 1 data integrity) |
| Remediation program | `mig-01-p0-findings.md` … `mig-14-p0-findings.md` | Per-ticket Phase 0 findings (Theme 3 migration) |
| Remediation program | `obs-01-p0-findings.md` … `obs-13-verify-findings.md` | Per-ticket Phase 0/Phase 1 findings (Theme 2 observability) |
| Remediation program | `ops-17-p1-findings.md`, `ops-batch-5A-p0-findings.md`, `ops-batch-5B-findings.md` | Theme 5 operational findings |
| Remediation program | `sec-01-p0-findings.md` … `sec-08-p0-findings.md` | Theme 4 security findings |

Update this index when adding a new file. New files should lead with the date
(`YYYY-MM-DD-<topic>.md`) so alphabetical sort produces reverse-chronological
by date, then topic.
