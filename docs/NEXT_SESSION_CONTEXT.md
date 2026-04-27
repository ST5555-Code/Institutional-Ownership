# Next session context

> This file is single-session handoff only. It is overwritten at the start of each session and reset at the end. Multi-session work lives in `ROADMAP.md`.

## Last completed

Today's wave (HEAD `15b2da6`, PRs #168–#174 — DM13 sweep close + DM15d no-op + DM15f/g hard-delete + pct-rename-sweep):

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
| `entity_overrides_persistent` | **1,052 rows** (MAX `override_id` = **1,054**; the 2 missing IDs are 425/488 deleted by PR #170) |
| `entity_rollup_history` open `economic_control_v1` | 26,602 |
| `entity_rollup_history` open `decision_maker_v1` | 26,602 |
| `entity_relationships` active (`valid_to=9999-12-31`) | 16,318 (of 18,363 total) |
| `ncen_adviser_map` | 11,209 |

## Up next

- See `ROADMAP.md` "Current backlog". **P0 empty. P2 empty.**
- **P1:** `ui-audit-walkthrough` (live Serge+Claude walkthrough — not a Code session); `perf-P0` (shipped PRs #158/#159 — peer_rotation precompute, verify no regressions); `audit-tracker-staleness-ci` (shipped PR #155 — verify no regressions); `43b-security` (shipped PR #156 — verify no regressions).
- **P3 quick wins:** React-1, React-2, dead-endpoints, INF28, INF48 (NEOS dedup), INF49 (Segall Bryant dedup), `other_managers` PK shape decision, `ncen_adviser_map` NULLs.

## Reminders

- **Do not run `build_classifications.py --reset`.** eqt-classify-codefix (PR #162) landed but `security_type_inferred` column still in schema. A `--reset` would re-seed from a column the classifier no longer reads.
- **Stage 5 cleanup** (legacy-table DROP window for `holdings` / `fund_holdings` / `beneficial_ownership`) authorized **on or after 2026-05-09** per `MAINTENANCE.md`. Do not drop earlier.
- `other_managers` PK still pending — proposed `(accession_number, sequence_number, other_cik)` blocked by 5,518 NULL `other_cik` rows; pick a PK shape (likely `(accession_number, sequence_number)` with 19-row dedupe) before scheduling.
- finra-default-flip: scheduled 2026-07-23.
- B3 calendar gate: post-Q1+Q2 2026 cycles, ~mid-Aug 2026.
- DM15e (7 prospectus-blocked umbrella trusts: Gotham / Mairs & Power / Brandes / Crawford / Bridges / Champlain / FPA) remains deferred behind DM6 (N-1A parser) or DM3 (N-PORT metadata extension).
