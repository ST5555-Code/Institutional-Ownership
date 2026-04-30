# Next session context

> This file is single-session handoff only. It is overwritten at the start of each session and reset at the end. Multi-session work lives in `ROADMAP.md`.

## Last completed

`sr-fund-quarter-filter` (PR #215) — Two enhancements to the Sector Rotation tab's Fund view:

- **Partial-quarter filter.** New `GET /api/v1/fund_quarter_completeness` returns per-quarter `months_available` + `complete` flag (true iff 3 monthly N-PORT report-months filed) from `fund_holdings_v2`. Fetched once on tab mount; when `level='fund'`, periods whose destination quarter is incomplete are filtered out of the sector heatmap. Institution view + the static Net Flows heatmap unaffected.
- **Monthly hover tooltip.** New `GET /api/v1/sector_monthly_flows?sector=&quarter=` computes monthly net flows from paired filers (funds present in both current and prior month). **Months are derived from the data, not the quarter label** — N-PORT report-months trail the filing quarter by one period (`quarter='2026Q1'` → report_months `2025-10/11/12`). Funds present in only one of the two months are excluded — most filers report only at quarter-end, so missing-month ≠ exit; treating it as exit produced spurious trillion-dollar swings. Heatmap tooltip lazy-fetches per `(sector, quarter)`, caches in component state (`monthlyByKey`), shows "Loading monthly detail…" while in-flight, renders abbreviated month labels in JetBrains Mono with green/red semantic colors per `docs/plans/DarkStyle.md`.

Earlier in `conv-19`:

- **PR #213** — N-PORT quarter bucketing fix + 14.6M-row migration + downstream rebuild. Backup at `data/13f_pre_quarter_fix.duckdb`. Closes the N-PORT quarter bucketing Known Issue.
- **PR #214** — Shared `PageHeader` rollout to all 12 tabs.

Current HEAD: post-`#215` squash on `main`.

Gotcha to remember: `fund_holdings_v2.report_month` trails `quarter` by one period (filing-quarter convention). Anything that wants per-month detail for a filing quarter must look up the actual `report_month` values from the data — do not derive months from the quarter label.

This sync (direct to main, post-merge):

- **`ROADMAP.md`** — new COMPLETED row for #215 (still under conv-19 sync header).
- **`docs/NEXT_SESSION_CONTEXT.md`** — this file refreshed.

## Up next

- See `ROADMAP.md` "Current backlog".
- **P0:** empty.
- **P1:** `ui-audit-walkthrough` (PR #107) only — live Serge+Claude session, not a Code session.
- **P2:** empty.
- **P3 (2 items):**
  - `D10 Admin UI for entity_identifiers_staging` — surface the 280-row staging backlog before Q1 2026 cycle (~2026-05-15).
  - `Tier 4 unmatched classifications (427)` — keyword sweep left 427 `bootstrap_tier4` entities at `classification='unknown'`. NAV exposure bounded at ~$370B.

### Priority order for next session

1. **Sector Rotation fund view follow-ups** — partial-quarter filter, monthly hover tooltip.
2. **Stale worktree branches cleanup** — sweep merged-PR worktrees that were not torn down.
3. **Stage 5 cleanup DROP** — authorized on or after 2026-05-09 per `MAINTENANCE.md`.

## Next external events

| Date | Event |
|---|---|
| **2026-05-09** | Stage 5 cleanup DROP window opens (legacy-table snapshot cleanup gate per `MAINTENANCE.md`). |
| **~2026-05-15** | Q1 2026 13F cycle (filings for period ending 2026-03-31; 45-day reporting window). |
| **~late May 2026** | Q1 2026 N-PORT DERA bulk — first live exercise of INF50 + INF52 fixes (PR #185); first live exercise of `compute_parent_fund_map.py` quarterly rebuild (PR #191); re-run `dera_synthetic_stabilize.py --phase 3 --confirm` against the new period to absorb any net-new Tier-4-shape registrants (script is idempotent). First N-PORT cycle under the corrected calendar quarter mapping. |
| **2026-07-23** | finra-default-flip — delete deprecation-warning path in `scripts/fetch_finra_short.py`. |
| **~mid-Aug 2026** | B3 calendar gate — post-Q1+Q2 2026 cycles, retire V1 + drop denorm columns. |

## Reminders

- **HEAD on main is `e090ab7`** after PR #214 squash-merge. Branches deleted.
- **N-PORT quarter bucketing is now correct** (calendar convention). Pre-fix snapshot preserved at `data/13f_pre_quarter_fix.duckdb` if rollback needed.
- **Git ops change** (from conv-18). Code pushes the branch, opens the PR, waits for CI green, then merges via `gh pr merge --squash --delete-branch` and pulls main. Reflected in `docs/PROCESS_RULES.md`.
- **Branch naming.** Always use a short descriptive slug (e.g. `nport-quarter-fix`, `tab-page-headers`). Claude must propose the short name before writing any prompt for Code.
- **Dark UI is production styling.** `docs/plans/DarkStyle.md` is the spec. Token palette + Hanken Grotesk / Inter / JetBrains Mono live in `web/react-app/src/styles/globals.css`.
- **App is started from `data/13f_readonly.duckdb`** (last refreshed in PR #200, 2026-04-28 ~15:09).
- **N-PORT current to 2026-03 (partial — 3,379 rows).** 2026-02 mostly complete (476,173 rows); 2026-01 full (1,321,367 rows). Quarter labels now reflect calendar convention.
- **Do not run `build_classifications.py --reset`.** Same as previous sessions.
- **No `--reset` runs anywhere** without explicit user authorization.
- **Stage 5 cleanup** (legacy-table DROP window) authorized **on or after 2026-05-09** per `MAINTENANCE.md`.
- `other_managers` PK still pending — proposed `(accession_number, sequence_number, other_cik)` blocked by 5,518 NULL `other_cik` rows.
- **finra-default-flip:** scheduled 2026-07-23.
- **B3 calendar gate:** post-Q1+Q2 2026 cycles, ~mid-Aug 2026.
- **DM15e** (7 prospectus-blocked umbrella trusts) remains deferred behind DM6 / DM3.
- **PR #172** (`dm13-de-discovery`) remains intentionally OPEN — paired-with-#173 triage CSV; close after reconciling.
