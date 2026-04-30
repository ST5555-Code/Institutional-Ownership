# Next session context

> This file is single-session handoff only. It is overwritten at the start of each session and reset at the end. Multi-session work lives in `ROADMAP.md`.

## Last completed

`conv-18` — UI wave covering 9 squash-merged PRs (#204–#212) plus prior conv-17 (#202–#203):

- **Dark UI restyle** (PR #202, conv-17) and **CI stale-test fix** (PR #203, conv-17) — landed before this session.
- **Full-width header** (PR #204) — header now spans above sidebar and content; two-line "SHAREHOLDER INTELLIGENCE" wordmark.
- **Sector Rotation redesign** (PRs #205 → #209) — five-PR arc landing the new `/api/v1/sector_summary` + `/api/v1/sector_flow_mover_detail` + `type_breakdown` endpoints, KPI cards row, ranked heatmap table replacing the bar chart, side-by-side movers panel with drill-down popup, broken-axis charts, sector totals row, fund-view movers fix.
- **Investor Detail tab** (PRs #210, #211) — Entity Graph renamed; new 3-level hierarchy (institution → filer → fund) on a new `/api/v1/institution_hierarchy` endpoint; quarter selector and market-wide static view added; filer/fund queries deduped via `GROUP BY`.
- **Compact density** (PR #212) — tighter padding across all 12 tabs; expand triangle now in a dedicated first column; gold left border on leftmost edge only; child-row connectors.

Current HEAD: `922ef6a` on `main`.

This sync (this commit, direct to main):

- **`ROADMAP.md`** — header date refreshed to `2026-04-29 (conv-18-doc-sync)`; new "Known issues" section added (N-PORT quarter bucketing off by one); 9 new COMPLETED rows for #204–#212. PRs #202/#203 already present from conv-17 — not duplicated.
- **`docs/NEXT_SESSION_CONTEXT.md`** — this file rewritten.
- **`docs/findings/CHAT_HANDOVER.md`** — new conv-18 section prepended.
- **`MAINTENANCE.md`** — last-updated stamp refreshed.
- **`docs/PROCESS_RULES.md`** — git-ops section updated to capture Code's PR/merge workflow.
- **`docs/SESSION_NAMING.md`** — short-descriptive-slug branch-naming rule documented.

## Up next

- See `ROADMAP.md` "Current backlog".
- **P0:** empty.
- **P1:** `ui-audit-walkthrough` (PR #107) only — live Serge+Claude session, not a Code session.
- **P2:** empty.
- **P3 (2 items):**
  - `D10 Admin UI for entity_identifiers_staging` — surface the 280-row staging backlog before Q1 2026 cycle (~2026-05-15).
  - `Tier 4 unmatched classifications (427)` — keyword sweep left 427 `bootstrap_tier4` entities at `classification='unknown'`. NAV exposure bounded at ~$370B.

### Priority order for next session

1. **N-PORT quarter bucketing fix (pipeline)** — off-by-one mapping; 2026Q1 contains Oct–Dec 2025, 2026Q2 contains Jan–Mar 2026. Locate period→quarter assignment in N-PORT load path; shift by one; re-bucket downstream.
2. **Sector Rotation fund view follow-ups** — partial-quarter filter, monthly hover tooltip, year group headers in the heatmap.
3. **Doc sync conv-18** — done in this commit.
4. **Stale worktree branches cleanup** — sweep merged-PR worktrees that were not torn down.

## Next external events

| Date | Event |
|---|---|
| **2026-05-09** | Stage 5 cleanup DROP window opens (legacy-table snapshot cleanup gate per `MAINTENANCE.md`). |
| **~2026-05-15** | Q1 2026 13F cycle (filings for period ending 2026-03-31; 45-day reporting window). |
| **~late May 2026** | Q1 2026 N-PORT DERA bulk — first live exercise of INF50 + INF52 fixes (PR #185); first live exercise of `compute_parent_fund_map.py` quarterly rebuild (PR #191); re-run `dera_synthetic_stabilize.py --phase 3 --confirm` against the new period to absorb any net-new Tier-4-shape registrants (script is idempotent). |
| **2026-07-23** | finra-default-flip — delete deprecation-warning path in `scripts/fetch_finra_short.py`. |
| **~mid-Aug 2026** | B3 calendar gate — post-Q1+Q2 2026 cycles, retire V1 + drop denorm columns. |

## Reminders

- **HEAD on main is `922ef6a`** after PRs #204–#212 squash-merges. Branches deleted.
- **Git ops change.** Code now pushes the branch, opens the PR, waits for CI green, then merges via `gh pr merge --squash --delete-branch` and pulls main — previously the operator did the merge step from Terminal. Reflected in `docs/PROCESS_RULES.md`.
- **Branch naming.** Always use a short descriptive slug (e.g. `sector-rotation-redesign`, `dark-ui-restyle`). Claude must propose the short name before writing any prompt for Code.
- **Dark UI is production styling.** `docs/plans/DarkStyle.md` is the spec. Token palette + Hanken Grotesk / Inter / JetBrains Mono live in `web/react-app/src/styles/globals.css`.
- **App is started from `data/13f_readonly.duckdb`** (last refreshed in PR #200, 2026-04-28 ~15:09).
- **N-PORT current to 2026-03 (partial — 3,379 rows).** 2026-02 mostly complete (476,173 rows); 2026-01 full (1,321,367 rows). Note: see Known issues — quarter bucketing for these periods is currently off by one in the UI.
- **Do not run `build_classifications.py --reset`.** Same as previous sessions.
- **No `--reset` runs anywhere** without explicit user authorization.
- **Stage 5 cleanup** (legacy-table DROP window) authorized **on or after 2026-05-09** per `MAINTENANCE.md`.
- `other_managers` PK still pending — proposed `(accession_number, sequence_number, other_cik)` blocked by 5,518 NULL `other_cik` rows.
- **finra-default-flip:** scheduled 2026-07-23.
- **B3 calendar gate:** post-Q1+Q2 2026 cycles, ~mid-Aug 2026.
- **DM15e** (7 prospectus-blocked umbrella trusts) remains deferred behind DM6 / DM3.
- **PR #172** (`dm13-de-discovery`) remains intentionally OPEN — paired-with-#173 triage CSV; close after reconciling.
