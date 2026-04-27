# Chat Handover — 2026-04-27 (conv-14 close)

## State

HEAD: `da10422` (post-PR #181, perf-P1 part 2 — `cohort_analysis` 60s TTL cache)
Migrations: 001–021 applied (021 = `sector_flows_rollup`, this wave)
Open PRs:
- **#172** — `dm13-de-discovery: triage CSV for residual ADV_SCHEDULE_A edges` (intentional, paired with #173 apply; close after reconciling)
- **#107** — `ui-audit-walkthrough` (intentional; needs live Serge+Claude session, not a Code session)
- **(this PR)** — `conv-14-doc-sync`
P0 / P2: empty.
P1: `ui-audit-walkthrough` only (live walkthrough).
P3: **`43g drop redundant type columns`** — moved Deferred → P3 by audit (trigger fired during perf-P1).
Worktrees: this branch (`conv-14-doc-sync`) only.

## Session 2026-04-26/27 (conv-14) — what landed

**13 PRs in the #169–#181 range (12 merged + 1 open).**

| PR | Slug | Notes |
|---|---|---|
| #169 | DM13-B/C apply | 107 non-operating / redundant `ADV_SCHEDULE_A` rollup edges suppressed. Override IDs 389–495. Promote `20260426_171207`. |
| #170 | DM15f / DM15g hard-delete | StoneX→StepStone (rel 14408) + Pacer→Mercer (rel 12022) `wholly_owned` edges hard-`DELETE`d along with their B/C suppression overrides (425, 488). |
| #171 | pct-rename-sweep | Doc/naming-only. 283 substitutions across 32 files retiring `pct_of_float` / `pct-of-float` / `PCT-OF-FLOAT` references. Migration 008 filename + 39 rename-narrative lines preserved. |
| #172 | dm13-de-discovery | **OPEN.** Triage CSV for residual ADV_SCHEDULE_A edges (consumed by #173 apply). |
| #173 | DM13-D/E apply | 559 dormant / residual `ADV_SCHEDULE_A` rollup edges suppressed. Override IDs 496–1054. Promote `20260427_045843`. **DM13 sweep fully closed.** |
| #174 | DM15d no-op | 0 re-routes. The 3 N-CEN-coverable trusts (Sterling Capital / NEOS / Segall Bryant) are all single-adviser (52 rows all `role='adviser'`, zero `role='subadviser'`); DM rollup already correct. |
| #175 | conv-13 doc sync | Refreshed `NEXT_SESSION_CONTEXT.md` / `ENTITY_ARCHITECTURE.md` header / `MAINTENANCE.md` / `CHAT_HANDOVER.md` post-DM13 wave. HEAD then `15b2da6`. |
| #176 | INF48 / INF49 | NEOS dup eid=10825 → canonical eid=20105; SBH dup eid=254 → canonical eid=18157. Suspect CRD `001006378` excluded from transfer (numerically identical to its CIK). Override IDs 1055 + 1056. Promote `20260427_064049`. EC + DM active row counts both 26,602 (parity preserved). |
| #177 | react-cleanup-inf28 | React-1: shared `useTickers.ts` module-cached hook (3 fetches → 1). React-2: extracted `fetchEntitySearch(q)` helper at module scope in `EntityGraphTab.tsx`. INF28: `promote_staging.VALIDATOR_MAP['securities']` → `schema_pk`. No DB writes. |
| #178 | dead-endpoints | 11 of 15 router-defined uncalled `/api/v1/*` routes deleted; 4 kept (`export/query{qnum}`, `crowding`, `smart_money`, `peer_groups/{group_id}`). 2 query helpers deleted (`get_sector_flow_detail`, `get_short_long_comparison`). Open follow-up: `web/react-app/src/types/api-generated.ts` regen pending the React types pipeline. |
| #179 | perf-p1-discovery | Scoping doc `docs/findings/perf-p1-scoping.md` (sector flows / movers / cohort precompute analysis). |
| #180 | perf-P1 part 1 | New `sector_flows_rollup` precompute (321 rows, migration 021). New `compute_sector_flows.py` `SourcePipeline` subclass (~2.1s rebuild). `queries.get_sector_flows` rewritten to read precomputed; `get_sector_flow_movers` `level='parent'` rewritten to read `peer_rotation_flows`. Latency: parent 1242ms → 4ms (310×); fund 1119ms → 5ms (224×); movers parent 335-405ms → 22-36ms (~12×). |
| #181 | perf-P1 part 2 | `cohort_analysis` 60s TTL cache (full precompute would have been ~2.3M rows). New `CACHE_KEY_COHORT` + `CACHE_TTL_COHORT=60`; `cached()` extended with optional `ttl=`. Cold 777-934ms → warm 0.01-0.05ms (>10,000× on a hit). **Closes perf-P1.** |

## DM13 grand total (unchanged from conv-13 — closed)

**797 relationships suppressed + 2 hard-deleted across 4 PRs:**

| PR | Category | Count | Override IDs |
|---|---|---|---|
| #168 | A — self-referential edges | 131 | 258–388 |
| #169 | B+C — non-operating / redundant | 107 (now 105 in DB after #170 deletes) | 389–495 |
| #170 | DM15f/g — hard-DELETE (subset of B/C false-positives) | 2 | (425, 488 deleted) |
| #173 | D+E — dormant / residual | 559 | 496–1054 |
| **Total** | | **797 suppressed + 2 deleted** | |

## INF48 + INF49 (this wave)

| PR | Item | Dup eid → Survivor eid | New override_id |
|---|---|---|---|
| #176 | INF48 NEOS Investment Management | 10825 → 20105 | **1055** |
| #176 | INF49 Segall Bryant & Hamill | 254 → 18157 | **1056** |

Standard INF entity-merge mechanics: identifier transfer-then-close (INSERT survivor before close on dup), preferred-name preservation as `legal_name` secondary alias, inverted-edge close (rel 15179 NEOS / rel 15231 SBH), `merged_into` rollup rows on dup, `entity_overrides_persistent` row keyed on dup CIK.

## Prod entity-layer state (read-only `data/13f.duckdb`, HEAD `da10422`)

| Metric | Value |
|---|---|
| `entities` | **26,602** |
| `entity_overrides_persistent` rows | **1,054** |
| `MAX(override_id)` | **1,056** (gaps at 425, 488 from #170 hard-deletes) |
| `entity_rollup_history` open `economic_control_v1` | 26,602 |
| `entity_rollup_history` open `decision_maker_v1` | 26,602 (DM1 parity holds) |
| `entity_relationships` total / active | **18,363 / 16,316** (−2 active vs. conv-13: rel_ids 15179 + 15231 closed by INF48/INF49) |
| `entity_aliases` | 26,943 |
| `entity_identifiers` | 35,516 |
| `ncen_adviser_map` | 11,209 |
| `sector_flows_rollup` (NEW migration 021, perf-P1) | **321** |

Validate baseline preserved through every promote in the wave: **8 PASS / 1 FAIL (`wellington_sub_advisory`) / 7 MANUAL**. The single FAIL is the long-standing non-structural baseline; no auto-rollback fired.

## P0 / P1 / P2 / P3 status (post-audit)

- **P0:** empty.
- **P1:** `ui-audit-walkthrough` (live walkthrough — not a Code session).
- **P2:** empty.
- **P3:** **`43g drop redundant type columns`** — moved here from Deferred. Trigger fired during perf-P1: PR #180 + #181 rewrote `queries.py` paths reading `holdings_v2` / `fund_holdings_v2` (sector flows, sector_flow_movers, cohort_analysis). Bundling opportunity passed without bundling the column drop. Schedule a dedicated migration session next.

## Deferred-item audit (PRs #169–#181)

| Item | Trigger | Trigger met (Y/N) | Evidence |
|---|---|---|---|
| **P2-FU-01** (`run_script` allowlist prune) | Q1 2026 cycle runs clean on V2 | **N** | Q1 2026 13F cycle is ~2026-05-15; not yet run. No PR in the wave touched `scripts/admin_bp.py`. |
| **perf-P2** (flow_analysis + market_summary + holder_momentum precompute) | perf-P0 + perf-P1 shipped AND latency complaints persist | **N** | Both perf-P0 (PRs #158/#159, 2026-04-25) and perf-P1 (PRs #179/#180/#181, 2026-04-27) shipped; second condition (latency complaints) not met — perf-P1 landed today, no time for new complaints. |
| **DM14c Voya residual** | DM14b edge-completion (Voya edge missing) | **N** | No PR in the wave touched DM14b or added a Voya edge. |
| **43g drop redundant type columns** | B3 OR first session touching `holdings_v2` query patterns | **Y** | PR #180 rewrote `scripts/queries.py` sector flows + sector_flow_movers paths reading `holdings_v2` / `fund_holdings_v2`; PR #181 rewrote `cohort_analysis` reading same. Bundling opportunity passed without bundling the column drop. → **Moved Deferred → P3.** |
| **categorized-funds-csv-relocate** | Next session touching `scripts/backfill_manager_types.py:39` | **N** | No PR in the wave touched `scripts/backfill_manager_types.py`. |

## Rules carried forward

- **Do NOT run `build_classifications.py --reset`.** eqt-classify-codefix (PR #162) landed; `security_type_inferred` column still exists in schema. A `--reset` would re-seed from a column the classifier no longer reads.
- **No `--reset` runs anywhere** without explicit user authorization.
- **Stage 5 cleanup** (legacy-table DROP for `holdings` / `fund_holdings` / `beneficial_ownership`) authorized **on or after 2026-05-09**. Do not drop earlier.
- **Approach first, prompt second** — present approach and wait for confirmation before writing code.
- **Git ops:** Code pushes branches and opens PRs. Serge merges from Terminal. No exceptions.
- **Staging workflow mandatory** for all entity changes (`sync_staging.py` → `diff_staging.py` → `promote_staging.py --approved`).
- **`ROADMAP.md` is the single source of truth** for all items.
- **Ticket numbers retired forever** once assigned (codified in `REVIEW_CHECKLIST.md` / `audit_ticket_numbers.py` per PR #149 hygiene-ticket-numbering session).

## Next external event

**Q1 2026 13F cycle, ~2026-05-15** (filings for period ending 2026-03-31; 45-day reporting window).

## Recommended next actions (priority order)

A. **`other_managers` PK shape decision** — 5,518 NULL `other_cik` rows + 19-row dedupe; finalize the PK shape (likely `(accession_number, sequence_number)`) before stamping a PK enforcement migration. Carried over from PR #165 deferred decision.
B. **43g drop redundant type columns** — now in P3. Dedicated migration session against `holdings_v2` / `fund_holdings_v2`.
C. **PR #172 close** — reconcile dm13-de-discovery doc with #173 apply outcome and close the PR.
D. **DM15e** — still deferred behind DM6 / DM3 parser work. Do not slot until parsers ship.
E. **perf-P2** — wait for either (i) latency complaints on `flow_analysis` / `market_summary` / `holder_momentum`, or (ii) explicit user request.
