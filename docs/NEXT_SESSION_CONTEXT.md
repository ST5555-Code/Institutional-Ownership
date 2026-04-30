# Next session context

> This file is single-session handoff only. It is overwritten at the start of each session and reset at the end. Multi-session work lives in `ROADMAP.md`.

## Last completed

`conv-20` — Short Interest redesign, sector rotation polish, export bar alignment, controls panel borders. Eight PRs landed (`#215`–`#222`):

- **PR #215 `sr-fund-quarter-filter`** — Sector Rotation Fund view: partial-quarter filter + monthly hover tooltip. New endpoints `/api/v1/fund_quarter_completeness` and `/api/v1/sector_monthly_flows`.
- **PR #216 `si-tab-redesign`** — Short Interest full redesign with sector/industry overlays. Two new endpoints (`/api/v1/short_position_pct`, `/api/v1/short_volume_comparison`), 5 KPI tiles.
- **PR #217 `si-restore-tables`** — Restored 3 tables dropped in #216: CrossRef, ShortOnly, NportByFund.
- **PR #218 `sr-polish-v2` (on-main rebuild)** — Net flows heatmap table, sector totals row, movers beside heatmap, compact KPI labels.
- **PR #219 `si-layout-fix`** — Short Interest layout: full-width stacked tables, axis line removal, named legends (Ticker/Sector/Industry), FINRA footnote.
- **PR #220 `si-chart-table-align`** — Ticker bar chart converted to line chart with dots; column widths normalized across the 4 SI tables.
- **PR #221 `export-bar-align`** — `ExportBar` + `FreshnessBadge` moved to the top-right header row on all 12 tabs.
- **PR #222 `controls-panel-border`** — Bordered control panel applied to the 10 tabs that have controls bars.

Current HEAD: **`3a5e2a1`** on `main`.

This sync (direct to `main`, post-merge):

- **`ROADMAP.md`** — header updated to conv-20 reference; 7 new COMPLETED rows for `#216`–`#222`.
- **`docs/NEXT_SESSION_CONTEXT.md`** — this file refreshed.
- **`docs/findings/CHAT_HANDOVER.md`** — new conv-20 section at top.
- **`MAINTENANCE.md`** — last-updated bumped.

## Up next

- See `ROADMAP.md` "Current backlog".
- **P0:** empty.
- **P1:** `ui-audit-walkthrough` (PR #107) only — live Serge+Claude session, not a Code session.
- **P2:** empty.
- **P3 (2 items):**
  - `D10 Admin UI for entity_identifiers_staging` — surface the 280-row staging backlog before Q1 2026 cycle (~2026-05-15).
  - `Tier 4 unmatched classifications (427)` — keyword sweep left 427 `bootstrap_tier4` entities at `classification='unknown'`. NAV exposure bounded at ~$370B.

### Priority order for next session

1. **13F-as-fund coverage gap** — fund view of Sector Rotation excludes hedge funds, family offices, and other 13F-only filers that lack N-PORT filings. Decide whether to surface them via a separate "13F filer" track (pure 13F holdings, no monthly cadence) or document the omission as expected behavior.
2. **Stale worktree cleanup** — sweep merged-PR worktrees that were not torn down. Quick `git worktree list` audit, then prune anything whose branch is gone from `origin`.
3. **Stage 5 cleanup DROP** — authorized on or after **2026-05-09** per `MAINTENANCE.md`.

## Next external events

| Date | Event |
|---|---|
| **2026-05-09** | Stage 5 cleanup DROP window opens (legacy-table snapshot cleanup gate per `MAINTENANCE.md`). |
| **~2026-05-15** | Q1 2026 13F cycle (filings for period ending 2026-03-31; 45-day reporting window). |
| **~late May 2026** | Q1 2026 N-PORT DERA bulk — first live exercise of INF50 + INF52 fixes (PR #185); first live exercise of `compute_parent_fund_map.py` quarterly rebuild (PR #191); re-run `dera_synthetic_stabilize.py --phase 3 --confirm` against the new period to absorb any net-new Tier-4-shape registrants (script is idempotent). First N-PORT cycle under the corrected calendar quarter mapping. |
| **2026-07-23** | finra-default-flip — delete deprecation-warning path in `scripts/fetch_finra_short.py`. |
| **~mid-Aug 2026** | B3 calendar gate — post-Q1+Q2 2026 cycles, retire V1 + drop denorm columns. |

## Reminders

- **HEAD on main is `3a5e2a1`** after PR #222 squash-merge. Branches deleted.
- **Git ops** (rule change from conv-18, reaffirmed in conv-20). Code now merges PRs autonomously after CI passes: pushes branch, opens PR, waits for CI green, then `gh pr merge --squash --delete-branch` and pulls main. Reflected in `docs/PROCESS_RULES.md`.
- **Branch naming.** Always use a short descriptive slug (e.g. `si-tab-redesign`, `controls-panel-border`). Claude must propose the short name before writing any prompt for Code.
- **Dark UI is production styling.** `docs/plans/DarkStyle.md` is the spec. Token palette + Hanken Grotesk / Inter / JetBrains Mono live in `web/react-app/src/styles/globals.css`.
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
