# Next session context

> This file is single-session handoff only. It is overwritten at the start of each session and reset at the end. Multi-session work lives in `ROADMAP.md`.

## Last completed

This session — `dm14c-voya` (worktree `beautiful-shaw-b808a4`, branch `claude/beautiful-shaw-b808a4`):

- **Three-task session:** end-of-leg doc sync (Task 0), ROADMAP priority moves activating 7 Deferred items (Task 1), and DM14c Voya residual entity-seed + DM re-route (Task 2). One PR opened off branch `claude/beautiful-shaw-b808a4`.
- **HEAD at session start:** `771e79f` (perf-P2 holder_momentum, PR #191). This sync closes the conv-15 → dm14c-voya leg of the longer arc that began with the DM13 sweep at PR #168.
- **22-PR session arc (#169–#191) now closed.** PRs #169–#181 closed by conv-14 (`#182`); PRs #183–#187 closed by conv-15 (`#188`); PRs #189, #190, #191 added in the post-conv-15 trio (BL-3/INF53, perf-P2 scoping, perf-P2 holder_momentum). This session's PR adds DM14c Voya residual on top of that arc.

## This session — Tasks 0/1/2

| Task | Slug | Notes |
|---|---|---|
| 0 | doc sync | Full rewrite of `docs/NEXT_SESSION_CONTEXT.md` + `docs/findings/CHAT_HANDOVER.md`; `MAINTENANCE.md` last-updated date refreshed and `compute_parent_fund_map.py` added to the L4 precompute table; `ENTITY_ARCHITECTURE.md` header updated for the override-count delta from Task 2. |
| 1 | roadmap-priority-moves | 7 items moved Deferred → active backlog. **P2:** `DM14c Voya residual` (this session's Task 2). **P3:** `categorized-funds-csv-relocate`, `DERA 1,187 NULL-series synthetics`, `43e family-office taxonomy`, `PROCESS_RULES Rule 9 dry-run uniformity`, `G7 scripts/queries.py monolith split`, `maintenance-audit-design`. All 7 had self-referential triggers (e.g. "next session touching X" where X is the work itself); activated to surface them as actionable items rather than perpetually deferred. |
| 2 | dm14c-voya | **49 actively-managed Voya-Voya intra-firm series ($21.74B AUM)** re-targeted on `decision_maker_v1` from holding co `eid=2489` (Voya Financial, Inc.) to operating sub-adviser `eid=17915` (Voya Investment Management Co. LLC, CRD 106494). Scope: `adviser_crd='000111091'` (Voya Investments LLC, eid=4071) AND `subadviser_crd='000106494'` AND `fund_universe.is_actively_managed=TRUE`. **No new entity created** — eid=2489 seed already existed. **No new edges** — wholly_owned 2489→{17915, 4071, 1591} already present from prior dm14c oneoff (commit `8136434`). Per-series flow: SCD-close DM rollup row at 2489, SCD-open new row at 17915 (`rule_applied='manual_override'`, `confidence='exact'`, `routing_confidence='high'`), insert one `entity_overrides_persistent` row per series (`action='merge'`, `rollup_type='decision_maker_v1'`, `identifier_type='series_id'`, `new_value='17915'`). **Override IDs 1057–1105 (+49).** Promote snapshot `20260428_081209`. `economic_control_v1` UNTOUCHED (all 49 still at eid=4071 VOYA INVESTMENTS, LLC via fund_sponsor — correct). Script: `scripts/oneoff/dm14c_voya_apply.py`. The 32 passive Voya-Voya series at eid=2489 intentionally NOT retargeted in this session — passive funds should mirror EC, but that's a separate cleanup pass tracked under DM14c follow-up if it surfaces. |

## Up next

- See `ROADMAP.md` "Current backlog".
- **P0:** empty.
- **P1:** `ui-audit-walkthrough` only (live Serge+Claude session — not a Code session).
- **P2:** _empty_ (this session's `DM14c Voya residual` will move to COMPLETED after PR merge).
- **P3:** `D10 Admin UI for entity_identifiers_staging`, `INF53 BACKFILL_MIG015 multi-row investigation`, plus the 6 freshly-activated items from Task 1 (`categorized-funds-csv-relocate`, `DERA 1,187 NULL-series synthetics`, `43e family-office taxonomy`, `PROCESS_RULES Rule 9 dry-run uniformity`, `G7 queries.py monolith split`, `maintenance-audit-design`).
- **Next external events:**
  - **Stage 5 cleanup DROP window opens 2026-05-09** (legacy `holdings` / `fund_holdings` / `beneficial_ownership` already retired 2026-04-13; this is the gate to drop their snapshots / final cleanup pass per `MAINTENANCE.md`).
  - **Q1 2026 13F cycle, ~2026-05-15** (filings for period ending 2026-03-31, 45-day reporting window).
  - **Q1 2026 N-PORT DERA bulk, ~late May 2026** — first live exercise of INF50 + INF52 fixes (`scripts/pipeline/load_nport.py` `_cleanup_staging` hard-fail + `_enrich_staging_entities` pre-promote enrich).

## Reminders

- **DM14c Voya residual is closed for the active subset only.** 49 active series re-routed 2489 → 17915. The 32 passive Voya-Voya series at eid=2489 (still routed to the holding co under `manual_override`) remain a known follow-up — per architecture they should mirror EC (eid=4071), but the passive cleanup is a separate scoping decision and was not included in this session.
- **EC never moves on these 49.** All still at eid=4071 (VOYA INVESTMENTS, LLC) via `fund_sponsor`. DM-only retarget by design — don't touch EC on a Voya-Voya re-routing pass.
- **INF50 + INF52 fixes are still code-only and have not been exercised against prod yet.** Next monthly N-PORT topup that touches amendments (or the Q1 2026 DERA bulk) is the live test. If the post-cleanup `CatalogException` assertion ever fires, capture the full `RuntimeError` — that is the actual root cause of the prior silent failure, finally visible.
- **`fund_holdings_v2` is at 14,568,775 rows** post-INF51 dedup; 5,587,231 value-divergent rows across 55,924 groups remain as **INF53** P3 follow-up (BL-3/INF53 closed in PR #189: by-design N-PORT multi-row pattern, not a migration bug; recommendation is annotative, no fix planned).
- **Migration 023 (`parent_fund_map`)** is live; 109,723 rows. `holder_momentum` parent path now reads from it (5.6× speedup; PR #191). Quarterly rebuild via `python3 scripts/pipeline/compute_parent_fund_map.py` (~115s end-to-end) — trigger after the new-period 13F + N-PORT promotes, same cadence as `compute_peer_rotation.py` and `compute_sector_flows.py`.
- **`fund_holdings_v2_enrichment` not rebuilt this session** — last computed 2026-04-17. Separate cadence; next refresh is on a different trigger.
- **N-PORT current to 2026-03 (partial — 3,379 rows).** 2026-02 mostly complete (476,173 rows); 2026-01 full (1,321,367 rows).
- **Do not run `build_classifications.py --reset`.** eqt-classify-codefix (PR #162) landed but `security_type_inferred` column still in schema.
- **Stage 5 cleanup** (legacy-table DROP window) authorized **on or after 2026-05-09** per `MAINTENANCE.md`.
- **No `--reset` runs anywhere** without explicit user authorization.
- `other_managers` PK still pending — proposed `(accession_number, sequence_number, other_cik)` blocked by 5,518 NULL `other_cik` rows.
- **finra-default-flip:** scheduled 2026-07-23.
- **B3 calendar gate:** post-Q1+Q2 2026 cycles, ~mid-Aug 2026.
- **DM15e** (7 prospectus-blocked umbrella trusts) remains deferred behind DM6 / DM3.
- **PR #172 still open** — dm13-de-discovery triage CSV; close after reconciling with PR #173 outcome.
