# Next session context

> This file is single-session handoff only. It is overwritten at the start of each session and reset at the end. Multi-session work lives in `ROADMAP.md`.

## Last completed

**Fund-level classification consolidation arc — closed 2026-05-01 across 8 PRs (PR-1a → PR-1b → PR-1c → PR-1d → PR-1e → PR-2 → PR-3 → PR-4).** All fund-level data, pipeline, query, and display layers now read a single canonical taxonomy: `active`, `balanced`, `multi_asset`, `passive`, `bond_or_other`, `excluded`, `final_filing`. The 8 PRs in order:

| PR | Branch | Headline |
| --- | --- | --- |
| #233 | `fund-strategy-backfill` (PR-1a) | Reconciled legacy data; `fund_strategy = fund_category` everywhere; `is_actively_managed` never NULL. |
| #235 | `peer-rotation-rebuild` (PR-1b) | Rebuilt `peer_rotation_flows` against canonical fund-level taxonomy (17,490,106 rows). |
| #236 | `classification-display-audit` (PR-1c) | Read-only audit of every classification-emitting endpoint. Surfaced 6 confirmed display bugs. |
| #237 | `classification-display-fix` (PR-1d) | Wired 12 fund-level read sites across 5 query files to canonical `fund_universe.fund_strategy` via `_fund_type_label()`. |
| #238 | `index-to-passive` (PR-1e) | Renamed value `'index'` → `'passive'` end-to-end (1,264 series + 3,055,575 holdings rows). |
| #239 | `classifier-name-patterns` (PR-2) | Extended `INDEX_PATTERNS` (8 new alternations); added pipeline write-path lock; reclassified 253 series + 186,943 holdings rows. |
| #240 | `fund-strategy-consolidate` (PR-3) | Dropped redundant `fund_universe.fund_category` and `fund_universe.is_actively_managed`; canonical constants `ACTIVE_FUND_STRATEGIES` / `PASSIVE_FUND_STRATEGIES`. |
| #241 | `fund-strategy-rename` (PR-4) | Value rename `'equity'` → `'active'`; column rename `fund_holdings_v2.fund_strategy` → `fund_strategy_at_filing`; `compute_peer_rotation._materialize_fund_agg` JOINs `fund_universe` instead of reading the per-quarter snapshot. |

**Net architectural state:** the per-quarter classification drift class is structurally impossible — pipeline lock prevents `fund_universe` overwrite; `peer_rotation_flows` rebuild reads canonical via JOIN; the snapshot at filing moment is preserved (intentional) in `fund_holdings_v2.fund_strategy_at_filing`. Display layer always reads canonical via `_fund_type_label()`.

Branch HEAD on `main`: **`414b824`** (PR-4 merged).

This sync (`conv-23-doc-sync`, direct to `main`):

- **`ROADMAP.md`** — header bumped to conv-23; closing summary added at top of COMPLETED.
- **`docs/NEXT_SESSION_CONTEXT.md`** — this file rewritten.
- **`docs/findings/CHAT_HANDOVER.md`** — new conv-23 section at top.
- **`MAINTENANCE.md`** — last-updated bumped to conv-23.

## Up next

**Primary:** institution-level consolidation scoping. Decisions partially made in prior chat session but not executed.

### Priority order for next session

1. **Institution-level consolidation scoping** — design + sequence the institution-level work that mirrors what the fund-level arc just closed. The fund-level arc established the four-stage pattern: (1) backfill / reconcile data; (2) rebuild downstream tables; (3) audit display layer; (4) fix display + rename + lock. Institution-level needs the same shape but with different surface area:
   - **Taxonomy decisions partially captured (prior chat session, not yet executed):** `pension`, `endowment`, `sovereign_wealth_fund` kept separate; `private_equity` + `venture_capital` merged to `pe_vc`; `wealth_management` + `family_office` merged to `wealth_mgmt`; `hedge_fund` + `multi_strategy` merged to `hedge_fund`. `mixed` and `unknown` still need review.
   - **Data state to confront:** 1.4M+ parent-level rows in `holdings_v2.entity_type` carry legacy values (`active` / `passive` / `mixed` from old taxonomy). Canonical reads should hit `entity_classification_history.classification` / `entity_current.classification` instead.
   - **Prerequisites:** `family_office` and `multi_strategy` migration from `manager_type` to `entity_classification_history` is a precondition for some merges.
   - **Roadmap entry that captures the display half:** `parent-level-display-canonical-reads` (P2) — 18 read sites currently on `manager_type` / `entity_type` need migration; includes the `query4` silent-drop bug at [register.py:746-750](scripts/queries/register.py:746).

2. **canonical-value-coverage-audit** (P2, surfaced 2026-05-01 PR-4 follow-up) — comprehensive audit of NULL `fund_strategy`, orphan series, edge cohorts (UNKNOWN orphans / SYN drifters / BlackRock muni trusts), 3-way `CASE` NULL semantics in `cross.py`, and rows where `fund_holdings_v2.fund_strategy_at_filing` differs from `fund_universe.fund_strategy` (quantify the historical drift the PR-4 JOIN fix now papers over). Output a per-bucket count + AUM exposure + recommended treatment table.

3. **review-active-bucket** (P2, renamed from `review-equity-bucket`) — review `fund_strategy='active'` (renamed from `'equity'` in PR-4) bucket comprehensively, including the 3,184 `series_id='UNKNOWN'` orphan rows. Some entries need `bond_or_other` or `balanced` reclassification (AMG Pantheon Credit Solutions, AIP Alternative Lending, ASA Gold, NXG Cushing Midstream).

4. **fund-strategy-taxonomy-finalization** (P2, surfaced 2026-05-01 PR-4 follow-up) — review and finalize the five edge categories in the canonical taxonomy (`balanced` / `multi_asset` / `bond_or_other` / `excluded` / `final_filing`). Trigger: after `canonical-value-coverage-audit`.

5. **verify-proshares-short-classification** (P2, surfaced 2026-05-01 PR-4 spot-check) — ProShares Ultra/UltraPro Short QQQ etc. currently classified `bond_or_other`; may belong in a new `inverse_or_short` bucket or be flipped to `passive`.

6. **verify-blackrock-muni-trust-status** (P2) — verify whether 12 BlackRock muni trusts are actually liquidating (correct `final_filing`) or still trading (needs reclassification to `bond_or_other`).

7. **stage-b-turnover-deferred-funds** (P2, position-turnover detection design) — Vanguard Primecap / Windsor II / Equity Income (~$203B AUM) and Bridgeway Ultra-Small Company Market are passive in behavior but won't match systemic INDEX_PATTERNS rules. Trigger: Stage B turnover detection design.

8. **branch-cleanup** — separate session; sweep stale `claude/*` and `fund-strategy-*` branches now that the arc is closed.

9. **Stage 5 cleanup DROP** — authorized on or after **2026-05-09** per `MAINTENANCE.md`.

### Backlog

- **P1:** `ui-audit-walkthrough` (PR #107) — live Serge+Claude session, not a Code session.
- **P3 (2 items):**
  - `D10 Admin UI for entity_identifiers_staging` — surface the 280-row staging backlog before Q1 2026 cycle (~2026-05-15).
  - `Tier 4 unmatched classifications (427)` — keyword sweep left 427 `bootstrap_tier4` entities at `classification='unknown'`. NAV exposure bounded at ~$370B.

## Critical context for next session

**The fund-level work established patterns the institution-level work will follow** — audit → backfill → display fix → rename + lock, with a canonical constants module (`ACTIVE_FUND_STRATEGIES` / `PASSIVE_FUND_STRATEGIES` in `scripts/queries/common.py`) and a single display-label utility (`_fund_type_label`). Institution-level should mirror this: a single canonical column on `entity_classification_history` / `entity_current`, a constants module, a shared label utility, and a JOIN-based query layer.

**Snapshot vs canonical semantics established by PR-4:** the per-row, per-quarter classification at filing moment lives in `fund_holdings_v2.fund_strategy_at_filing` (snapshot, frozen, intentional). The canonical (locked, never-overwritten-without-analyst-approval) value lives in `fund_universe.fund_strategy`. Anything that filters or buckets by active/passive **always JOINs `fund_universe`** — never reads `_at_filing`. Institution-level should follow the same separation.

## Next external events

| Date | Event |
|---|---|
| **2026-05-09** | Stage 5 cleanup DROP window opens (legacy-table snapshot cleanup gate per `MAINTENANCE.md`). |
| **~2026-05-15** | Q1 2026 13F cycle (filings for period ending 2026-03-31; 45-day reporting window). First live exercise of the locked `fund_universe` write path under a real cycle. |
| **~late May 2026** | Q1 2026 N-PORT DERA bulk — first live exercise of INF50 + INF52 fixes (PR #185); first live exercise of `compute_parent_fund_map.py` quarterly rebuild (PR #191); re-run `dera_synthetic_stabilize.py --phase 3 --confirm` against the new period to absorb any net-new Tier-4-shape registrants. |
| **2026-07-23** | finra-default-flip — delete deprecation-warning path in `scripts/fetch_finra_short.py`. |
| **~mid-Aug 2026** | B3 calendar gate — post-Q1+Q2 2026 cycles, retire V1 + drop denorm columns. |

## Reminders

- **HEAD on main is `414b824`** (PR-4 fund-strategy-rename, #241) after the fund-level arc closed.
- **Canonical fund taxonomy values:** `{active, balanced, multi_asset, passive, bond_or_other, excluded, final_filing}`. `active` is the dominant value (was `equity` pre-2026-05-01). Display label utility `_fund_type_label()` in `scripts/queries/common.py` collapses to 5 values `{active, passive, bond, excluded, unknown}`.
- **Column rename (PR-4):** the prod column is `fund_holdings_v2.fund_strategy_at_filing` (was `fund_strategy` pre-2026-05-01). Staging schema (`stg_nport_holdings.fund_strategy`) intentionally retains the old name — the prod write path renames at INSERT time (`s.fund_strategy AS fund_strategy_at_filing`). Anything reading the prod column must use the new name.
- **JOIN rule (PR-4):** for any active/passive filter, **always JOIN `fund_universe`** — the canonical, locked column. The per-row, per-quarter snapshot in `fund_strategy_at_filing` is preserved intentionally for snapshot semantics but is NOT the source of truth for filters.
- **Pipeline lock (PR-2):** `_apply_fund_strategy_lock` + `_upsert_fund_universe` COALESCE in `scripts/pipeline/load_nport.py` together prevent any `fund_universe.fund_strategy` overwrite once a series carries a non-NULL value. Three-branch semantics: new series → write classifier output; existing with non-null → preserve; existing with NULL → write classifier output (backfill case).
- **Constants module (PR-3):** `ACTIVE_FUND_STRATEGIES = ('active','balanced','multi_asset')` and `PASSIVE_FUND_STRATEGIES = ('passive','bond_or_other','excluded','final_filing')` adjacent to `_fund_type_label` in [scripts/queries/common.py:291](scripts/queries/common.py:291).
- **Display layer (PR-1d):** `_fund_type_label(fund_strategy)` is the single fund-level type emitter. Map: `active|balanced|multi_asset → 'active'`, `passive → 'passive'`, `bond_or_other → 'bond'`, `excluded|final_filing → 'excluded'`, NULL/unknown → `'unknown'`. `unknown` is now an honest expression of "no `fund_universe` row or value outside the canonical set" — earlier display layers silently rendered these as `passive` (Conviction) or `active` (name-sweep default).
- **PR-1d gotcha:** `get_nport_children_batch` and `get_nport_children` in `scripts/queries/common.py` SELECT and propagate `fund_strategy` in their child-dict shape. Any new consumer of those helpers can read `child['fund_strategy']` without re-querying.
- **PR-1d gotcha:** `cross.py` `_cross_ownership_fund_query` no longer carries `family_name` in its response (`type` overload removed). The column stays in `fund_holdings_v2` for entity matching.
- **Cross-Ownership tab (conv-22).** Peer dropdown reads `/api/v1/peer_tickers` (sector + industry from `market_data`). Investor row expand fires `/api/v1/cross_ownership_fund_detail?tickers=…&institution=…&anchor=…&quarter=…` and is gated by `has_fund_detail` on the parent rollup. Fund-level toggle pulls from `fund_holdings_v2` (pivot now references the outer `fund_pos` aggregation, not `fh.ticker` / `fh.holding_value`).
- **Git ops** (rule from conv-18, reaffirmed each session). Code merges PRs autonomously after CI passes: pushes branch, opens PR, waits for CI green, then `gh pr merge --squash --delete-branch` and pulls main. Reflected in `docs/PROCESS_RULES.md` §11.
- **Branch naming.** Always use a short descriptive slug. Claude must propose the short name before writing any prompt for Code. **Every Code prompt must start with the session/branch name on the first line.**
- **Doc-only commits (`conv-*`)** push directly to `main` — no PR needed.
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
