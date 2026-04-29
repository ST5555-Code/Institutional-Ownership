# Next session context

> This file is single-session handoff only. It is overwritten at the start of each session and reset at the end. Multi-session work lives in `ROADMAP.md`.

## Last completed

`conv-17-doc-sync` — covers two PRs squash-merged today:

- **PR #202 `dark-ui-restyle`** (squash commit `5f7781f`) — full dark/cinematic UI restyle per `docs/plans/DarkStyle.md`. 33 files: new token palette in `web/react-app/src/styles/globals.css` (20 CSS vars + Hanken Grotesk / Inter / JetBrains Mono via Google Fonts), 5 shell components, 9 common components, 12 tab files, `web/templates/admin.html`. Three commits on the branch (initial restyle, audit pass, final `var(--white)` sweep). Visual-only — no API, data-logic, or component-contract changes. Also closes the prior P3 item "Type-badge `family_office` color" (`family_office` now in `common/typeConfig.ts` mapped to the gold category palette).
- **PR #203 `ci-fix-stale-test`** (squash commit `03914f2`) — replaced hardcoded `fetch_date` strings in `tests/pipeline/test_load_market.py::test_scope_stale_days_queries_prod` with `dt.date.today()`-relative offsets so the test cannot drift stale. The hardcoded `FRESH = '2026-04-21'` had crossed the 7-day staleness boundary on 2026-04-28 and was failing CI for every open PR.

Current HEAD: `5f7781f` on `main`.

This sync (this commit, direct to main):

- **`ROADMAP.md`** — header date refreshed to `2026-04-29 (conv-17-doc-sync)`; P3 item "Type-badge `family_office` color" removed (resolved by #202); two new COMPLETED rows added for #202 (full summary) and #203 (one-line summary).
- **`docs/NEXT_SESSION_CONTEXT.md`** — this file rewritten for the new state.
- **`docs/findings/CHAT_HANDOVER.md`** — new conv-17 section prepended at top.
- **`MAINTENANCE.md`** — last-updated stamp refreshed.

## Up next

- See `ROADMAP.md` "Current backlog".
- **P0:** empty.
- **P1:** `ui-audit-walkthrough` (PR #107) only — live Serge+Claude session, not a Code session.
- **P2:** empty.
- **P3 (2 items, was 3 — `family_office` chip resolved by #202):**
  - `D10 Admin UI for entity_identifiers_staging` — surface the 280-row staging backlog before Q1 2026 cycle (~2026-05-15).
  - `Tier 4 unmatched classifications (427)` — surfaced by PR #200's keyword sweep; remaining 427 `bootstrap_tier4` entities still carry `classification='unknown'`. Trigger: next entity-curation pass willing to expand the keyword set or do per-entity manual sign-off. NAV exposure bounded at ~$370B.

## Next external events

| Date | Event |
|---|---|
| **2026-05-09** | Stage 5 cleanup DROP window opens (legacy-table snapshot cleanup gate per `MAINTENANCE.md`). |
| **~2026-05-15** | Q1 2026 13F cycle (filings for period ending 2026-03-31; 45-day reporting window). |
| **~late May 2026** | Q1 2026 N-PORT DERA bulk — first live exercise of INF50 + INF52 fixes (PR #185); first live exercise of `compute_parent_fund_map.py` quarterly rebuild (PR #191); re-run `dera_synthetic_stabilize.py --phase 3 --confirm` against the new period to absorb any net-new Tier-4-shape registrants (script is idempotent). |
| **2026-07-23** | finra-default-flip — delete deprecation-warning path in `scripts/fetch_finra_short.py`. |
| **~mid-Aug 2026** | B3 calendar gate — post-Q1+Q2 2026 cycles, retire V1 + drop denorm columns. |

## Reminders

- **HEAD on main is `5f7781f`** after PR #202 + PR #203 squash-merges. Both PRs closed and remote branches deleted.
- **Dark UI is now production styling.** Style guide: `docs/plans/DarkStyle.md`. Implementation spec: `docs/plans/dark-ui-restyle-prompt.md`. New token palette in `web/react-app/src/styles/globals.css`; legacy CSS-var aliases (`--shell-bg` / `--sidebar-bg` / `--oxford-blue` / `--card-bg` / `--accent-gold` / etc.) preserved as token aliases for backward compatibility — safe to remove in a future cleanup once no production references remain.
- **App is started from `data/13f_readonly.duckdb`** (last refreshed in PR #200, 2026-04-28 ~15:09). It carries the 657 Tier-4 institution bootstraps + Calamos merge + Tier-4 keyword sweep.
- **`SYN_{cik_padded}` stable-key pattern** is now applied to every entity-mapped synth registrant (713 distinct keys: 55 Phase 2 + 658 Phase 3). The `{cik}_{accession}` minting in `scripts/fetch_dera_nport.py:460` is upstream and only fires when DERA `FUND_REPORTED_INFO.SERIES_ID` is missing in the source XML.
- **Validator FLAG `series_id_synthetic_fallback` (`scripts/pipeline/load_nport.py:437`) can be retired** in the next `load_nport.py` audit pass — there are no remaining Tier 1/3/4 candidates as of PR #200. Future N-PORT filings without SERIES_ID will mint net-new `{raw_cik}_{accession}` keys; re-running `dera_synthetic_stabilize.py --phase 3 --confirm` against the new period absorbs them.
- **`make audit` baseline preserved post Tier-4 + Calamos merge.** `validate_entities --prod` 7 PASS / 1 FAIL (`wellington_sub_advisory`) / 8 MANUAL.
- **657 new Tier-4 institution entities** opened in PR #199 with `classification='unknown'`. PR #200 keyword sweep closed 230 of them (1 passive + 229 active); the next `build_classifications.py` non-`--reset` sweep will reassign based on fund_strategy / SIC / N-PORT signals.
- **N-PORT current to 2026-03 (partial — 3,379 rows).** 2026-02 mostly complete (476,173 rows); 2026-01 full (1,321,367 rows).
- **Do not run `build_classifications.py --reset`.** Same as previous sessions (PR #162 eqt-classify-codefix changed what the classifier reads; a `--reset` would re-seed from a column the classifier no longer reads).
- **No `--reset` runs anywhere** without explicit user authorization.
- **Stage 5 cleanup** (legacy-table DROP window) authorized **on or after 2026-05-09** per `MAINTENANCE.md`.
- `other_managers` PK still pending — proposed `(accession_number, sequence_number, other_cik)` blocked by 5,518 NULL `other_cik` rows.
- **finra-default-flip:** scheduled 2026-07-23.
- **B3 calendar gate:** post-Q1+Q2 2026 cycles, ~mid-Aug 2026.
- **DM15e** (7 prospectus-blocked umbrella trusts) remains deferred behind DM6 / DM3.
- **PR #172** (`dm13-de-discovery`) remains intentionally OPEN — paired-with-#173 triage CSV; close after reconciling.
