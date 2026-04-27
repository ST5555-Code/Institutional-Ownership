# Next session context

> This file is single-session handoff only. It is overwritten at the start of each session and reset at the end. Multi-session work lives in `ROADMAP.md`.

## Last completed

This session — `conv-14-doc-sync` (branch `conv-14-doc-sync`, no DB writes, no schema changes):

- End-of-sprint doc sync after the 13-PR wave (#169–#181) that landed today + 2026-04-26. Refreshes `docs/NEXT_SESSION_CONTEXT.md`, `ENTITY_ARCHITECTURE.md` header, `MAINTENANCE.md` (last-updated + perf-P1 precompute pointer), `docs/findings/CHAT_HANDOVER.md` (full rewrite), and `ROADMAP.md` (deferred-item audit + verify the 13 PRs are in COMPLETED).
- Deferred-item audit: 5 candidates checked against the wave; **1 trigger fired** — `43g drop redundant type columns` ("first session touching holdings_v2 query patterns") — perf-P1 (#180 + #181) rewrote `queries.py` paths reading `holdings_v2` / `fund_holdings_v2` without bundling the column drop. Item moved Deferred → P3. Other 4 (P2-FU-01, perf-P2, DM14c residual, categorized-funds-csv-relocate) stay Deferred.

Wave summary (HEAD `da10422`, 13 PRs, 12 merged + 1 open):

- **DM13-A** (PR #168 — preceding wave) — out of scope for this audit (already documented in conv-13).
- **DM13-B/C** (PR #169) — 107 non-operating / redundant `ADV_SCHEDULE_A` rollup edges suppressed. Override IDs **389–495**. `scripts/oneoff/dm13bc_apply.py`. Promote snapshot `20260426_171207`.
- **DM15f / DM15g** (PR #170) — 2 ADV Schedule A false-positive `wholly_owned` edges hard-`DELETE`d (StoneX→StepStone rel 14408; Pacer→Mercer rel 12022) along with their B/C suppression overrides (override_ids 425, 488). Net effect: B+C override range 389–495 now holds 105 rows, not 107. Promote snapshot `20260426_174146`.
- **pct-rename-sweep** (PR #171) — doc/naming-only cleanup. 283 substitutions across 32 files (`pct_of_float`/`pct-of-float`/`PCT-OF-FLOAT` → `pct_of_so` form). Migration 008 filename + the 39 rename-narrative lines preserved.
- **dm13-de-discovery** (PR #172, **OPEN**) — triage CSV for residual ADV_SCHEDULE_A edges. Carried into this wave by counting; the apply landed in #173. Will close once #173 is reconciled with the discovery doc.
- **DM13-D/E** (PR #173) — 559 dormant / residual `ADV_SCHEDULE_A` rollup edges suppressed. Override IDs **496–1054**. `scripts/oneoff/dm13de_apply.py`. Promote snapshot `20260427_045843`. **DM13 sweep fully closed across 4 PRs (#168/#169/#170/#173): 797 suppressed + 2 hard-deleted.**
- **DM15d** (PR #174) — closed as **no-op**. The 52 `ncen_adviser_map` rows for Sterling Capital / NEOS / Segall Bryant are all `role='adviser'`, zero `role='subadviser'`. DM15b/Layer 2 retarget pattern not applicable; current rollup already correct. Surfaced 2 entity-merge candidates → INF48 / INF49.
- **conv-13: doc sync** (PR #175) — refreshed `NEXT_SESSION_CONTEXT.md` / `ENTITY_ARCHITECTURE.md` header / `MAINTENANCE.md` / `CHAT_HANDOVER.md` post-DM13 wave. Pure doc; HEAD then was `15b2da6`.
- **INF48 / INF49** (PR #176) — NEOS + Segall Bryant adviser entity dedup. INF48: dup eid=10825 → canonical eid=20105 (NEOS). INF49: dup eid=254 → canonical eid=18157 (SBH); suspect CRD `001006378` excluded from transfer per user direction (numerically identical to its own CIK). Override IDs **1055** (NEOS) + **1056** (SBH). 26-change promote snapshot `20260427_064049`. EC + DM active row counts both 26,602 (parity preserved).
- **react-cleanup-inf28** (PR #177) — three disjoint cleanup items in one branch. React-1: shared `useTickers.ts` module-cached hook (3 fetches → 1). React-2: extracted `fetchEntitySearch(q)` helper at module scope in `EntityGraphTab.tsx`. INF28: `promote_staging.VALIDATOR_MAP['securities']` flipped from `None` to `schema_pk` (formal registration of the migration-011 PK as engine-level validator).
- **dead-endpoints** (PR #178) — 11 of 15 router-defined uncalled `/api/v1/*` routes deleted (`config/quarters`, `amendments`, `manager_profile`, `fund_rollup_context`, `fund_behavioral_profile`, `nport_shorts`, `entity_resolve`, `sector_flow_detail`, `short_long`, `short_volume`, `heatmap`); 4 kept (`export/query{qnum}`, `crowding`, `smart_money`, `peer_groups/{group_id}`). 2 query helpers deleted (`get_sector_flow_detail`, `get_short_long_comparison`). 3 entries removed from `tests/test_app_ticker_validation.py::CURRENT_ROUTES`. Open follow-up: `web/react-app/src/types/api-generated.ts` regenerated only when the React types pipeline runs again (per `ARCH-4C-followup`).
- **perf-p1-discovery** (PR #179) — scoping doc `docs/findings/perf-p1-scoping.md` for sector flows / movers / cohort precomputes.
- **perf-P1 part 1** (PR #180) — new `sector_flows_rollup` precompute table (321 rows, migration 021, PK `(quarter_from, quarter_to, level, rollup_type, active_only, gics_sector)`). New `scripts/pipeline/compute_sector_flows.py` `SourcePipeline` subclass (~2.1s rebuild). `queries.get_sector_flows` rewritten to read precomputed; `get_sector_flow_movers` `level='parent'` rewritten to read from `peer_rotation_flows` (perf-P0). Latency: parent **1242ms → 4ms** (310×); fund **1119ms → 5ms** (224×); movers parent **335-405ms → 22-36ms** (~12×).
- **perf-P1 part 2** (PR #181) — `cohort_analysis` 60s TTL cache (full precompute would have been ~2.3M rows; cache wins on repeat clicks instead). New `CACHE_KEY_COHORT` template + `CACHE_TTL_COHORT=60` in `scripts/cache.py`; `cached()` extended to accept `ttl=`. Latency: cold 777-934ms → warm **0.01-0.05ms** (>10,000× on a hit). **Closes perf-P1.**

Prod entity-layer state at end of wave (read-only `data/13f.duckdb`, HEAD `da10422`):

| Metric | Value |
|---|---|
| `entities` | **26,602** |
| `entity_overrides_persistent` | **1,054 rows** (MAX `override_id` = **1,056**; missing IDs 425/488 deleted by PR #170) |
| `entity_rollup_history` open `economic_control_v1` | 26,602 |
| `entity_rollup_history` open `decision_maker_v1` | 26,602 |
| `entity_relationships` total / active (`valid_to=9999-12-31`) | **18,363 / 16,316** (−2 active vs. conv-13: rel_ids 15179 + 15231 closed by INF48/INF49) |
| `entity_aliases` | 26,943 |
| `entity_identifiers` | 35,516 |
| `ncen_adviser_map` | 11,209 |
| `sector_flows_rollup` (NEW, migration 021) | **321 rows** |

Validate baseline preserved across all promotes in the wave: **8 PASS / 1 FAIL (`wellington_sub_advisory`) / 7 MANUAL** (non-structural baseline FAIL, no auto-rollback).

## Up next

- See `ROADMAP.md` "Current backlog". **P0 / P2 / P3 empty after the audit moved 43g into P3.** Wait — 43g moved Deferred → P3 (see audit), so P3 has one item.
- **P1:** `ui-audit-walkthrough` only (live Serge+Claude walkthrough — not a Code session).
- **P3:** `43g drop redundant type columns` (trigger fired during perf-P1; bundling opportunity passed — schedule a dedicated migration session).
- Next external event: **Q1 2026 13F cycle, ~2026-05-15** (filings for period ending 2026-03-31, 45-day reporting window).

## Reminders

- **Do not run `build_classifications.py --reset`.** eqt-classify-codefix (PR #162) landed but `security_type_inferred` column still in schema. A `--reset` would re-seed from a column the classifier no longer reads.
- **Stage 5 cleanup** (legacy-table DROP window for `holdings` / `fund_holdings` / `beneficial_ownership`) authorized **on or after 2026-05-09** per `MAINTENANCE.md`. Do not drop earlier.
- **No `--reset` runs anywhere** without explicit user authorization.
- `other_managers` PK still pending — proposed `(accession_number, sequence_number, other_cik)` blocked by 5,518 NULL `other_cik` rows; pick a PK shape (likely `(accession_number, sequence_number)` with 19-row dedupe) before scheduling.
- **finra-default-flip:** scheduled 2026-07-23.
- **B3 calendar gate:** post-Q1+Q2 2026 cycles, ~mid-Aug 2026.
- **DM15e** (7 prospectus-blocked umbrella trusts: Gotham / Mairs & Power / Brandes / Crawford / Bridges / Champlain / FPA) remains deferred behind DM6 (N-1A parser) or DM3 (N-PORT metadata extension).
- **DM14c Voya residual** still deferred — DM14b edge-completion has not landed in this wave.
- **PR #172 still open** — dm13-de-discovery triage CSV; close after reconciling with PR #173 outcome.
