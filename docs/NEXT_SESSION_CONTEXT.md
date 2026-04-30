# Next session context

> This file is single-session handoff only. It is overwritten at the start of each session and reset at the end. Multi-session work lives in `ROADMAP.md`.

## Last completed

`conv-22` — Cross-Ownership tab redesign (peer-driven dropdown, expandable rows with per-fund drill-down, fund-level toggle fixed) plus fix-up pass (sticky gold Group Total, fund-level 500 fix, per-ticker fund positions across the full peer group). Two PRs landed (`#228`–`#229`):

- **PR #228 `cross-ownership-polish`** — Cross-Ownership tab polish. Peer Group dropdown driven by the loaded ticker's classification (new `GET /api/v1/peer_tickers`); inline ticker input always visible; expandable investor rows with per-anchor fund drill-down (new `GET /api/v1/cross_ownership_fund_detail`); fund-level toggle now actually changes data (`/cross_ownership` + `/cross_ownership_top` accept `level=parent|fund`); Group Total footer restyled gold; page title appends current quarter via shared `fmtQuarter`. Squash `f46c88c`.
- **PR #229 `cross-ownership-fix`** — Cross-Ownership tab fix-ups on top of #228. Fund-level 500 fixed (pivot reference bug in `_cross_ownership_fund_query`); `has_fund_detail` flag added to `/cross_ownership` parent rollup so the `▶` expand triangle only renders for investors that actually have N-PORT fund detail; `/cross_ownership_fund_detail` rewritten for per-peer-ticker positions (top 5 funds by total value across the peer group); sticky gold Group Total + % of Portfolio summary block at the top of the table; expanded child rows mirror the parent column structure (per-ticker columns populated from `positions[ticker].value`). Squash `f2194b8`.

Current HEAD: **`7203539`** on `main`.

This sync (direct to `main`):

- **`ROADMAP.md`** — header bumped to conv-22; new Known Issue (`fund_strategy classification drift`).
- **`docs/NEXT_SESSION_CONTEXT.md`** — this file rewritten.
- **`docs/findings/CHAT_HANDOVER.md`** — new conv-22 section at top.
- **`MAINTENANCE.md`** — last-updated bumped to conv-22.

## Up next

- See `ROADMAP.md` "Current backlog" + "Known issues".

### Priority order for next session

1. **fund_strategy classification drift fix** — surfaced this session and logged as a Known Issue. `classify_fund()` recomputes per quarter, so 6,195 of ~14,000 funds in `fund_holdings_v2` carry 2+ distinct `fund_strategy` values across their history. **Scope both legs together:** **(pipeline)** lock `fund_universe.fund_strategy` on the first classification — once a series_id has a non-null value, do not overwrite on later quarters unless an analyst forces a reclassification. **(query)** for `active_only` / passive filters, JOIN `fund_universe` to read the locked strategy instead of reading `fund_holdings_v2.fund_strategy` (per-row, drifts per quarter). Both changes need to land in the same PR so the lock and the join cut over together.
2. **13F-as-fund coverage gap** — fund view of Sector Rotation (and other fund-keyed tabs) excludes hedge funds, family offices, and other 13F-only filers that lack N-PORT filings. Decide whether to surface them via a separate "13F filer" track (pure 13F holdings, no monthly cadence) or document the omission as expected behavior.
3. **Index benchmark validation pipeline** — start Phase 1 (build `benchmark_portfolios` reference table). Roadmap entry under P2; coverage in `docs/findings/index_benchmark_coverage.md`.
4. **Stage 5 cleanup DROP** — authorized on or after **2026-05-09** per `MAINTENANCE.md`.

### Backlog

- **P1:** `ui-audit-walkthrough` (PR #107) — live Serge+Claude session, not a Code session.
- **P3 (2 items):**
  - `D10 Admin UI for entity_identifiers_staging` — surface the 280-row staging backlog before Q1 2026 cycle (~2026-05-15).
  - `Tier 4 unmatched classifications (427)` — keyword sweep left 427 `bootstrap_tier4` entities at `classification='unknown'`. NAV exposure bounded at ~$370B.

## Next external events

| Date | Event |
|---|---|
| **2026-05-09** | Stage 5 cleanup DROP window opens (legacy-table snapshot cleanup gate per `MAINTENANCE.md`). |
| **~2026-05-15** | Q1 2026 13F cycle (filings for period ending 2026-03-31; 45-day reporting window). |
| **~late May 2026** | Q1 2026 N-PORT DERA bulk — first live exercise of INF50 + INF52 fixes (PR #185); first live exercise of `compute_parent_fund_map.py` quarterly rebuild (PR #191); re-run `dera_synthetic_stabilize.py --phase 3 --confirm` against the new period to absorb any net-new Tier-4-shape registrants. First N-PORT cycle under the corrected calendar quarter mapping. |
| **2026-07-23** | finra-default-flip — delete deprecation-warning path in `scripts/fetch_finra_short.py`. |
| **~mid-Aug 2026** | B3 calendar gate — post-Q1+Q2 2026 cycles, retire V1 + drop denorm columns. |

## Reminders

- **HEAD on main is `7203539`** after PRs #228 + #229 squash-merged and the #229 commit-hash doc tweak.
- **Git ops** (rule from conv-18, reaffirmed each session). Code merges PRs autonomously after CI passes: pushes branch, opens PR, waits for CI green, then `gh pr merge --squash --delete-branch` and pulls main. Reflected in `docs/PROCESS_RULES.md` §11.
- **Branch naming.** Always use a short descriptive slug (e.g. `cross-ownership-polish`, `cross-ownership-fix`). Claude must propose the short name before writing any prompt for Code. **Every Code prompt must start with the session/branch name on the first line.**
- **Dark UI is production styling.** `docs/plans/DarkStyle.md` is the spec. Token palette + Hanken Grotesk / Inter / JetBrains Mono live in `web/react-app/src/styles/globals.css`.
- **Quarter formatting.** All quarter labels in the React app go through `fmtQuarter` from `web/react-app/src/components/common/formatters.ts`. `QuarterSelector` defaults to it. Oldest-left → newest-right ordering for quarter button arrays.
- **App is started from `data/13f_readonly.duckdb`** (last refreshed in PR #200, 2026-04-28 ~15:09).
- **N-PORT current to 2026-03 (partial — 3,379 rows).** 2026-02 mostly complete (476,173 rows); 2026-01 full (1,321,367 rows). Quarter labels reflect calendar convention (PR #213).
- **fund_strategy drift (conv-22).** `fund_holdings_v2.fund_strategy` is per-row / per-quarter and drifts (6,195 funds carry 2+ distinct values). Until the fix lands, prefer reading the strategy via `fund_universe` JOIN for any active/passive filter.
- **Cross-Ownership tab (conv-22).** Peer dropdown reads `/api/v1/peer_tickers` (sector + industry from `market_data`). Investor row expand fires `/api/v1/cross_ownership_fund_detail?tickers=…&institution=…&anchor=…&quarter=…` and is gated by `has_fund_detail` on the parent rollup. Fund-level toggle pulls from `fund_holdings_v2` (pivot now references the outer `fund_pos` aggregation, not `fh.ticker` / `fh.holding_value`).
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
