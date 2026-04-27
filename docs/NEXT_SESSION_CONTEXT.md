# Next session context

> This file is single-session handoff only. It is overwritten at the start of each session and reset at the end. Multi-session work lives in `ROADMAP.md`.

## Last completed

This session — INF48 + INF49 entity dedup (branch `inf48-49-entity-dedup`, snapshot `20260427_064049`):

- **INF48 / INF49** — duplicate adviser entities merged into their canonicals using a new `scripts/oneoff/inf48_49_apply.py`. **NEOS:** dup eid=10825 (no comma, cik=`0002001019`) merged into canonical eid=20105 (with comma, crd=`000321256`). **Segall Bryant:** dup eid=254 (uppercase ADV-style; cik=`0001006378`, crd=`001006378`, crd=`106505`) merged into canonical eid=18157 (mixed case, crd=`000106505`). New script mirrors INF23 mechanics with one addition — per-entity identifier transfer (INSERT on survivor BEFORE close on dup, never break total_aum gate). Per-merge: transfer identifiers, add dup's preferred name as `alias_type='legal_name'` secondary alias on survivor, close inverted survivor→dup `wholly_owned/orphan_scan` edges (rel_id 15179 NEOS / rel_id 15231 SBH — closed not re-pointed to avoid self-edges), close dup's aliases / classification / rollups, insert `merged_into` rollup rows (one EC, one DM) on dup, write `entity_overrides_persistent` row keyed on dup CIK with `action='merge'`. Override IDs **1055** (NEOS) and **1056** (SBH). **Suspect-CRD exclusion (INF49):** dup's crd=`001006378` (`source=cik_crd_direct`) was numerically identical to its own CIK — excluded from transfer per user direction before promote (added to `TRANSFER_EXCLUSIONS` set in script and surgically dropped from survivor row before promote). Verify post-promote: dups hold zero active aliases / classifications / identifiers / non-`merged_into` rollups and zero active relationships in either direction; survivor 18157 ends with one CIK + 2 CRDs (`000106505` padded original + transferred unpadded `106505`); EC and DM open row counts both 26602 (parity preserved). `total_aum` PASS confirms identifier transfer didn't break the ~$166B INF4c gate.

Prior wave (HEAD `15b2da6`, PRs #168–#174 — DM13 sweep close + DM15d no-op + DM15f/g hard-delete + pct-rename-sweep):

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
- **P3 quick wins:** React-1, React-2, dead-endpoints, INF28, `other_managers` PK shape decision, `ncen_adviser_map` NULLs.

## Reminders

- **Do not run `build_classifications.py --reset`.** eqt-classify-codefix (PR #162) landed but `security_type_inferred` column still in schema. A `--reset` would re-seed from a column the classifier no longer reads.
- **Stage 5 cleanup** (legacy-table DROP window for `holdings` / `fund_holdings` / `beneficial_ownership`) authorized **on or after 2026-05-09** per `MAINTENANCE.md`. Do not drop earlier.
- `other_managers` PK still pending — proposed `(accession_number, sequence_number, other_cik)` blocked by 5,518 NULL `other_cik` rows; pick a PK shape (likely `(accession_number, sequence_number)` with 19-row dedupe) before scheduling.
- finra-default-flip: scheduled 2026-07-23.
- B3 calendar gate: post-Q1+Q2 2026 cycles, ~mid-Aug 2026.
- DM15e (7 prospectus-blocked umbrella trusts: Gotham / Mairs & Power / Brandes / Crawford / Bridges / Champlain / FPA) remains deferred behind DM6 (N-1A parser) or DM3 (N-PORT metadata extension).
