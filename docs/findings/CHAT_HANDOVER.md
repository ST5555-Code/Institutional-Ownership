# Chat Handover — 2026-04-27

## State

HEAD: `15b2da6` (post-PR #174, conv-13 close)
Migrations: 001–020 applied
Open PRs: #107 only (ui-audit-walkthrough — intentional, needs live session)
P0: empty
P2: **empty** (perf-P1 rotated up to P1)
Worktrees: clean (main only after this conv-13-doc-sync PR merges)

## Session 2026-04-26/27 (conv-13) — what landed

PRs #168 → #174 (7 PRs, DM13 sweep close + DM15d no-op + DM15f/g hard-delete + pct-rename-sweep + this doc-sync):

- **PR #168 — DM13-A** — 131 self-referential `ADV_SCHEDULE_A` edges suppressed. Override IDs 258–388. `scripts/oneoff/dm13a_apply.py`. Promote snapshot `20260426_134015`.
- **PR #169 — DM13-B/C** — 107 non-operating / redundant rollup edges suppressed. Override IDs 389–495. `scripts/oneoff/dm13bc_apply.py`. Promote snapshot `20260426_171207`.
- **PR #170 — DM15f / DM15g** — 2 ADV Schedule A false-positive `wholly_owned` edges hard-`DELETE`d (StoneX→StepStone rel 14408; Pacer→Mercer rel 12022) along with their B/C suppression overrides (override_ids 425, 488). Promote snapshot `20260426_174146`.
- **PR #171 — pct-rename-sweep** — doc/naming-only cleanup. 283 substitutions across 32 files retiring legacy `pct_of_float` / `pct-of-float` / `PCT-OF-FLOAT` references in favor of `pct_of_so` form. Migration 008 filename + 39 rename-narrative lines preserved. Zero application / schema / migration logic touched.
- **PR #173 — DM13-D/E** — 559 dormant / residual `ADV_SCHEDULE_A` rollup edges suppressed. Override IDs 496–1054. `scripts/oneoff/dm13de_apply.py`. Promote snapshot `20260427_045843`. **DM13 sweep fully closed.**
- **PR #174 — DM15d closed as no-op** — 0 re-routes. The 3 N-CEN-coverable trusts (Sterling Capital / NEOS / Segall Bryant) are all single-adviser trusts; the 52 candidate `ncen_adviser_map` rows are all `role='adviser'`, zero `role='subadviser'`. DM15b/Layer 2 retarget pattern is not applicable; current DM rollup already correct. No staging writes, no apply script.
- **(this PR) conv-13: doc sync post-DM13 wave** — refresh `docs/NEXT_SESSION_CONTEXT.md` + `ENTITY_ARCHITECTURE.md` header + `MAINTENANCE.md` + this `CHAT_HANDOVER.md`.

## DM13 grand total

**797 relationships suppressed + 2 hard-deleted across 4 PRs:**

| PR | Category | Count | Override IDs |
|---|---|---|---|
| #168 | A — self-referential edges | 131 | 258–388 |
| #169 | B+C — non-operating / redundant | 107 (now 105 in DB after #170 deletes) | 389–495 |
| #170 | DM15f/g — hard-DELETE (subset of B/C false-positives) | 2 | (425, 488 deleted) |
| #173 | D+E — dormant / residual | 559 | 496–1054 |
| **Total** | | **797 suppressed + 2 deleted** | |

## Prod entity-layer state

Read-only `data/13f.duckdb`:

| Metric | Value |
|---|---|
| `entities` | **26,602** |
| `entity_overrides_persistent` rows | **1,052** |
| `MAX(override_id)` | **1,054** (gap at 425, 488 from #170 hard-deletes) |
| `entity_rollup_history` open `economic_control_v1` | 26,602 |
| `entity_rollup_history` open `decision_maker_v1` | 26,602 (DM1 parity holds) |
| `entity_relationships` total / active | 18,363 / 16,318 |
| `ncen_adviser_map` | 11,209 |

Validate baseline preserved through all conv-13 promotes: **8 PASS / 1 FAIL (`wellington_sub_advisory`) / 7 MANUAL**. The single FAIL is the long-standing non-structural baseline; no auto-rollback fired.

## P0 / P1 / P2 status

- **P0:** empty.
- **P1:** `ui-audit-walkthrough` (live walkthrough, not a Code session); `perf-P0` (shipped PRs #158/#159 — verify no regressions); `audit-tracker-staleness-ci` (shipped PR #155 — verify no regressions); `43b-security` (shipped PR #156 — verify no regressions).
- **P2:** **empty.**
- **P3 quick wins:** React-1, React-2, dead-endpoints, INF28, **INF48** (NEOS dedup), **INF49** (Segall Bryant dedup), `other_managers` PK shape decision, `ncen_adviser_map` NULLs.

## Rules carried forward

- **Do NOT run `build_classifications.py --reset`.** eqt-classify-codefix (PR #162) landed; `security_type_inferred` column still exists in schema. A `--reset` would re-seed from a column the classifier no longer reads.
- **Stage 5 cleanup** (legacy-table DROP for `holdings` / `fund_holdings` / `beneficial_ownership`) authorized **on or after 2026-05-09**. Do not drop earlier.
- **Approach first, prompt second** — present approach and wait for confirmation before writing code.
- **Git ops:** Code pushes branches and opens PRs. Serge merges from Terminal. No exceptions.
- **Staging workflow mandatory** for all entity changes (`sync_staging.py` → `diff_staging.py` → `promote_staging.py --approved`).
- **`ROADMAP.md` is the single source of truth** for all items.
- **Ticket numbers retired forever** once assigned (codified in `REVIEW_CHECKLIST.md` / `audit_ticket_numbers.py` per PR #149 hygiene-ticket-numbering session).

## Newly surfaced — INF48 / INF49 entity-merge candidates

DM15d discovery surfaced two adviser-entity duplicates that should be cleaned up under the standard INF entity-merge pattern:

- **INF48 — NEOS Investment Management dedup.** eid=10825 *NEOS Investment Management LLC* (no comma) vs eid=20105 *NEOS Investment Management, LLC* (comma). All 17 NEOS ETF Trust funds currently roll to eid=20105 under DM; eid=10825 holds 0 DM children. Pick canonical eid, transfer identifiers / relationships, close the duplicate. ~30 min.
- **INF49 — Segall Bryant & Hamill dedup.** eid=254 *SEGALL BRYANT & HAMILL, LLC* (uppercase, ADV-style) vs eid=18157 *Segall Bryant and Hamill LLC* (mixed-case). All 16 Segall Bryant & Hamill Trust funds currently roll to eid=18157 under DM; eid=254 holds 0 DM children. ~30 min.

Both are P3 / quick-win items in `ROADMAP.md` "Current backlog".

## Known imperfection — Leonard Green → Mariner

The Leonard Green → Mariner edge in `entity_relationships` is a known imperfection carried forward from earlier DM13 triage. Not material to the rollup (Leonard Green is a PE firm and not a rollup target under the Operating Asset Manager Rule), but worth flagging so a future curator doesn't reopen it as a new finding. No action required this cycle.

## Recommended next steps (priority order)

A. **INF48 / INF49 entity-merge** — quick-win pair, ~1 hr combined. Standard INF entity-merge pattern; can be one session.
B. **`other_managers` PK shape decision** — 5,518 NULL `other_cik` rows + 19-row dedupe; finalize before stamping a PK enforcement migration.
C. **React-1 / React-2 / dead-endpoints** — small UI cleanups bundled together. Can be one session.
D. **DM15e** — deferred behind DM6 / DM3 parser work. Do not slot until parsers ship.

## Note: this doc-sync PR

`NEXT_SESSION_CONTEXT.md` was stale (last refreshed at HEAD `a7e040a`, pre-DM13 wave). This conv-13-doc-sync PR refreshes it along with the `ENTITY_ARCHITECTURE.md` header, `MAINTENANCE.md` pending-vs-completed audit work, and this handover. No staleness-warning carried forward — docs are aligned to HEAD `15b2da6` after merge.
