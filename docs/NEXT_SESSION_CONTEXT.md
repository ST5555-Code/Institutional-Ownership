# Next session context

> This file is single-session handoff only. It is overwritten at the start of each session and reset at the end. Multi-session work lives in `ROADMAP.md`.

## Last completed

`conv-21` — SI table polish, overlap tab redesign + column stats, global quarter label standardization. Five PRs landed (`#223`–`#227`):

- **PR #223 `si-table-quarter-polish`** — Fixed-width `colgroup` across the 4 SI tables for consistent Type column alignment; quarter labels formatted to `Q4 '25` style.
- **PR #224 `overlap-tab-redesign`** — Overlap Analysis tab redesigned to a vertical stack of two tables (institutional + fund); expandable rows drill to per-fund detail; cross-ownership stat boxes; per-table Active Only toggles. New `GET /api/v1/overlap_institution_detail` endpoint.
- **PR #225 `overlap-column-stats`** — Grouped column headers (`% of Outstanding` / `Value ($MM)`); 8 KPI stat tiles above tables; row-expand returns 3 sections (Overlapping / `{TICKER_A}` Only / `{TICKER_B}` Only); totals footer rows. Endpoint shape change on `/api/v1/overlap_institution_detail`.
- **PR #226 `quarter-label-global`** — Shared `fmtQuarter` in `web/react-app/src/components/common/formatters.ts`; `QuarterSelector` defaults to `Q3 '25` format; quarter button arrays reordered oldest-left → newest-right; 7 tab-local copies removed.
- **PR #227 `conv-21-doc-sync`** — This sync: ROADMAP, NEXT_SESSION_CONTEXT, CHAT_HANDOVER, MAINTENANCE, PROCESS_RULES.

Current HEAD: **`5c06e32`** on `main`.

This sync (direct to `main`):

- **`ROADMAP.md`** — header bumped to conv-21; new COMPLETED rows for `#223`, `#224`, `#227`.
- **`docs/NEXT_SESSION_CONTEXT.md`** — this file rewritten.
- **`docs/findings/CHAT_HANDOVER.md`** — new conv-21 section at top.
- **`MAINTENANCE.md`** — last-updated bumped to conv-21.
- **`docs/PROCESS_RULES.md`** — verified Code session/branch and autonomous-merge rules.

## Session totals (conv-15 through conv-21)

26 PRs merged across the dark-UI restyle + sector rotation redesign + investor detail + N-PORT quarter fix + short interest redesign + overlap analysis redesign + global UI consistency arc: PRs `#202`–`#227`. Highlights: dark UI restyle, sector rotation redesign + polish, investor detail tab, N-PORT calendar-quarter fix (PR #213), short interest redesign + restore + chart polish, overlap tab full redesign, ExportBar / FreshnessBadge / controls panel / page header / quarter label global consistency.

## Up next

- See `ROADMAP.md` "Current backlog".
- **P0:** empty.
- **P1:** `ui-audit-walkthrough` (PR #107) — live Serge+Claude session, not a Code session.
- **P2:** `index-benchmark-validation` — fund-to-index classification pipeline (Phase 1 reference table → Phase 2 correlation scoring → Phase 3 unmatched fund classification → Phase 4 sector fund integration). Coverage findings: `docs/findings/index_benchmark_coverage.md`.
- **P3 (2 items):**
  - `D10 Admin UI for entity_identifiers_staging` — surface the 280-row staging backlog before Q1 2026 cycle (~2026-05-15).
  - `Tier 4 unmatched classifications (427)` — keyword sweep left 427 `bootstrap_tier4` entities at `classification='unknown'`. NAV exposure bounded at ~$370B.

### Priority order for next session

1. **13F-as-fund coverage gap** — fund view of Sector Rotation (and other fund-keyed tabs) excludes hedge funds, family offices, and other 13F-only filers that lack N-PORT filings. Decide whether to surface them via a separate "13F filer" track (pure 13F holdings, no monthly cadence) or document the omission as expected behavior.
2. **Index benchmark validation pipeline** — start Phase 1 (build `benchmark_portfolios` reference table). Roadmap entry under P2; coverage in `docs/findings/index_benchmark_coverage.md`.
3. **Stage 5 cleanup DROP** — authorized on or after **2026-05-09** per `MAINTENANCE.md`.

## Next external events

| Date | Event |
|---|---|
| **2026-05-09** | Stage 5 cleanup DROP window opens (legacy-table snapshot cleanup gate per `MAINTENANCE.md`). |
| **~2026-05-15** | Q1 2026 13F cycle (filings for period ending 2026-03-31; 45-day reporting window). |
| **~late May 2026** | Q1 2026 N-PORT DERA bulk — first live exercise of INF50 + INF52 fixes (PR #185); first live exercise of `compute_parent_fund_map.py` quarterly rebuild (PR #191); re-run `dera_synthetic_stabilize.py --phase 3 --confirm` against the new period to absorb any net-new Tier-4-shape registrants. First N-PORT cycle under the corrected calendar quarter mapping. |
| **2026-07-23** | finra-default-flip — delete deprecation-warning path in `scripts/fetch_finra_short.py`. |
| **~mid-Aug 2026** | B3 calendar gate — post-Q1+Q2 2026 cycles, retire V1 + drop denorm columns. |

## Reminders

- **HEAD on main is `5c06e32`** after PR #226 squash-merge + #227 doc-sync commit.
- **Git ops** (rule from conv-18, reaffirmed each session). Code merges PRs autonomously after CI passes: pushes branch, opens PR, waits for CI green, then `gh pr merge --squash --delete-branch` and pulls main. Reflected in `docs/PROCESS_RULES.md` §11.
- **Branch naming.** Always use a short descriptive slug (e.g. `overlap-tab-redesign`, `quarter-label-global`). Claude must propose the short name before writing any prompt for Code. **Every Code prompt must start with the session/branch name on the first line.**
- **Dark UI is production styling.** `docs/plans/DarkStyle.md` is the spec. Token palette + Hanken Grotesk / Inter / JetBrains Mono live in `web/react-app/src/styles/globals.css`.
- **Quarter formatting.** All quarter labels in the React app go through `fmtQuarter` from `web/react-app/src/components/common/formatters.ts`. `QuarterSelector` defaults to it. Oldest-left → newest-right ordering for quarter button arrays.
- **App is started from `data/13f_readonly.duckdb`** (last refreshed in PR #200, 2026-04-28 ~15:09).
- **N-PORT current to 2026-03 (partial — 3,379 rows).** 2026-02 mostly complete (476,173 rows); 2026-01 full (1,321,367 rows). Quarter labels reflect calendar convention (PR #213).
- **Do not run `build_classifications.py --reset`.** Same as previous sessions.
- **No `--reset` runs anywhere** without explicit user authorization.
- **Stage 5 cleanup** (legacy-table DROP window) authorized **on or after 2026-05-09** per `MAINTENANCE.md`.
- `other_managers` PK still pending — proposed `(accession_number, sequence_number, other_cik)` blocked by 5,518 NULL `other_cik` rows.
- **finra-default-flip:** scheduled 2026-07-23.
- **B3 calendar gate:** post-Q1+Q2 2026 cycles, ~mid-Aug 2026.
- **DM15e** (7 prospectus-blocked umbrella trusts) remains deferred behind DM6 / DM3.
- **PR #172** (`dm13-de-discovery`) remains intentionally OPEN — paired-with-#173 triage CSV; close after reconciling.
- **Sector Rotation fund-view caveat** (from PR #215): `fund_holdings_v2.report_month` trails `quarter` by one period (filing-quarter convention). Anything that wants per-month detail for a filing quarter must look up the actual `report_month` values from the data — do not derive months from the quarter label.
- **Overlap endpoint shape** (from PR #225): `/api/v1/overlap_institution_detail` returns `{overlapping, ticker_a_only, ticker_b_only}` (was `non_overlapping`). Each section capped at top 5 by value.
