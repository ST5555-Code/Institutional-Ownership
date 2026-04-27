# Next session context

> This file is single-session handoff only. It is overwritten at the start of each session and reset at the end. Multi-session work lives in `ROADMAP.md`.

## Last completed

This session — `dead-endpoints` (branch `dead-endpoints`, no DB writes, no schema changes):

- Triaged the 15 router-defined uncalled `/api/v1/*` routes pre-identified in `docs/findings/2026-04-24-consolidated-backlog.md` row 86. Discovery cross-checked React `fetch` sites, `tests/`, and Python callers — confirmed exactly 15 dead.
- **Deleted 11 routes + handlers:** `config/quarters` (api_config.py); `amendments` + `manager_profile` (api_register.py); `fund_rollup_context` + `fund_behavioral_profile` + `nport_shorts` (api_fund.py — only `fund_portfolio_managers` survives); `entity_resolve` (api_entities.py); `sector_flow_detail` + `short_long` + `short_volume` + `heatmap` (api_market.py).
- **Deleted 2 query helpers** in `scripts/queries.py`: `get_sector_flow_detail` and `get_short_long_comparison` (no other callers). `get_entity_by_id` retained — three other queries.py functions still call it.
- **Kept 4** per triage: `/api/v1/export/query{qnum}`, `/api/v1/crowding`, `/api/v1/smart_money`, `/api/v1/peer_groups/{group_id}` (modal-only / planned-feature / low-cost).
- Removed 3 dead routes (`amendments`, `short_long`, `short_volume`) from `CURRENT_ROUTES` in `tests/test_app_ticker_validation.py`. `crowding` + `smart_money` remain in the list (KEEP).
- Cleaned unused imports: `HTTPException` from api_register.py + api_market.py; `clean_for_json` + `logging` + `log` from api_register.py; `validate_ticker_historical` + `clean_for_json` from api_fund.py.
- Updated `docs/endpoint_classification.md` (route table, Phase 4 Batch 4-A Blueprint mapping, footnote pointing to this work). Marked `docs/findings/2026-04-24-consolidated-backlog.md` row 86 + the §Backlog detail row CLOSED.
- Verification: `npm run build` passes (1.74s). `pre-commit run --files <touched>` passes (ruff + pylint + bandit + tracker-staleness). `pytest tests/test_app_ticker_validation.py` 38/38 pass. `pytest tests/smoke/` 8/8 pass. Smoke-imported all 7 routers — clean.

**Open follow-up:** `web/react-app/src/types/api-generated.ts` is regenerated via `npx openapi-typescript http://localhost:8001/openapi.json` against the running server; not refreshed in this PR. Stale entries for the 11 deleted routes will linger until the React types pipeline runs again (per the `ARCH-4C-followup` deferred item in ROADMAP).

Prior wave (HEAD `983db36`, PRs #168–#177 — DM13 sweep close + DM15d no-op + DM15f/g hard-delete + pct-rename-sweep + INF48/INF49 entity dedup + react-cleanup-inf28):

- **DM13-A** (PR #168) — 131 self-referential `ADV_SCHEDULE_A` edges suppressed. Override IDs **258–388**. `scripts/oneoff/dm13a_apply.py`. Promote snapshot `20260426_134015`.
- **DM13-B/C** (PR #169) — 107 non-operating / redundant rollup edges suppressed (Cat B AUM-inversion + Cat C non-operating parent / graph noise). Override IDs **389–495**. `scripts/oneoff/dm13bc_apply.py`. Promote snapshot `20260426_171207`.
- **DM15f / DM15g** (PR #170) — 2 ADV Schedule A false-positive `wholly_owned` edges hard-`DELETE`d (StoneX→StepStone rel 14408; Pacer→Mercer rel 12022) along with their DM13-B/C suppression overrides (override_ids 425, 488). Net effect: B+C override range 389–495 now holds 105 rows, not 107. Promote snapshot `20260426_174146`.
- **pct-rename-sweep** (PR #171) — doc/naming-only cleanup. 283 substitutions across 32 files (`pct_of_float`/`pct-of-float`/`PCT-OF-FLOAT` → `pct_of_so` form). Migration 008 filename + the 39 rename-narrative lines preserved. `data_layers.md` audit-column entry added; `pipeline_violations.md` closure stamped. Zero application / schema / migration logic touched.
- **DM13-D/E** (PR #173) — 559 dormant / residual `ADV_SCHEDULE_A` rollup edges suppressed (Cat D both-zero-AUM + Cat E residual non-operating parents that escaped B/C). Override IDs **496–1054**. `scripts/oneoff/dm13de_apply.py`. Promote snapshot `20260427_045843`. **DM13 sweep fully closed across 4 PRs (#168/#169/#170/#173): 797 suppressed + 2 hard-deleted.**
- **DM15d** (PR #174) — closed as **no-op**. Discovery against `ncen_adviser_map` (read-only, prod + staging) confirmed 52 series across Sterling Capital / NEOS / Segall Bryant are all `role='adviser'` with **zero `role='subadviser'` rows**. The DM15b/Layer 2 retarget pattern requires subadviser rows; without them there is no source of truth for an alternative DM target. Each series already rolls to the registrant's namesake adviser (Sterling → eid 4367; NEOS → eid 20105; Segall Bryant → eid 18157). 0 re-routes, 0 override writes, no apply script. Two entity-merge candidates surfaced as side-observations: **INF48** (NEOS dupe eids 10825 vs 20105) and **INF49** (Segall Bryant dupe eids 254 vs 18157).

Prod entity-layer state at end of wave (read-only `data/13f.duckdb`):

| Metric | Value |
|---|---|
| `entities` | **26,602** |
| `entity_overrides_persistent` | **1,054 rows** (MAX `override_id` = **1,056**; missing IDs 425/488 deleted by PR #170) |
| `entity_rollup_history` open `economic_control_v1` | 26,602 |
| `entity_rollup_history` open `decision_maker_v1` | 26,602 |
| `entity_relationships` active (`valid_to=9999-12-31`) | 16,316 (of 18,363 total) |
| `ncen_adviser_map` | 11,209 |

## Up next

- See `ROADMAP.md` "Current backlog". **P0 empty. P2 empty.**
- **P1:** `ui-audit-walkthrough` (live Serge+Claude walkthrough — not a Code session); `perf-P0` (shipped PRs #158/#159 — peer_rotation precompute, verify no regressions); `audit-tracker-staleness-ci` (shipped PR #155 — verify no regressions); `43b-security` (shipped PR #156 — verify no regressions).
- **P3 quick wins:** `other_managers` PK shape decision, `ncen_adviser_map` NULLs. (React-1, React-2, dead-endpoints, INF28 all closed in PRs #177 and this branch.)

## Reminders

- **Do not run `build_classifications.py --reset`.** eqt-classify-codefix (PR #162) landed but `security_type_inferred` column still in schema. A `--reset` would re-seed from a column the classifier no longer reads.
- **Stage 5 cleanup** (legacy-table DROP window for `holdings` / `fund_holdings` / `beneficial_ownership`) authorized **on or after 2026-05-09** per `MAINTENANCE.md`. Do not drop earlier.
- `other_managers` PK still pending — proposed `(accession_number, sequence_number, other_cik)` blocked by 5,518 NULL `other_cik` rows; pick a PK shape (likely `(accession_number, sequence_number)` with 19-row dedupe) before scheduling.
- finra-default-flip: scheduled 2026-07-23.
- B3 calendar gate: post-Q1+Q2 2026 cycles, ~mid-Aug 2026.
- DM15e (7 prospectus-blocked umbrella trusts: Gotham / Mairs & Power / Brandes / Crawford / Bridges / Champlain / FPA) remains deferred behind DM6 (N-1A parser) or DM3 (N-PORT metadata extension).
