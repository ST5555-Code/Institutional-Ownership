# Next session context

> This file is single-session handoff only. It is overwritten at the start of each session and reset at the end. Multi-session work lives in `ROADMAP.md`.

## Last completed

**Fund-level cleanup arc closed 2026-05-01.** Three commits on top of the 8-PR consolidation arc, bringing the consolidation+cleanup sequence to 11 PRs total:

| Commit / PR | Branch | Headline |
| --- | --- | --- |
| #242 (`5af96e1`) | `fund-cleanup-batch` | 4 fund-level follow-ups (canonical-coverage audit + 12 BlackRock muni verification + 51 ProShares mechanics review + active-bucket audit) + 2 reclassifications (AMG Pantheon Credit Solutions + AIP Alternative Lending Fund P → `bond_or_other`). |
| `594a273` (chore) | `branch-cleanup` | Direct-to-main chore. Local branch sprawl 80 → 4. 76 branches deleted (5 traditional-merge + 71 squash-merged). 2 closed-PR branches retained, both flagged DELETE in chat. |
| #243 (`f256e5e`) | `saba-proshares-reclassify` | 1 Saba sibling aligned (`multi_asset` → `balanced`) + 39 ProShares short / inverse / leveraged-short funds promoted to `passive`. Closes `proshares-short-reclassify-execute`. |

**Reclassifications applied:**

- AMG Pantheon Credit Solutions (`balanced` → `bond_or_other`) — credit fund.
- AIP Alternative Lending Fund P (`active` → `bond_or_other`) — sibling of Fund A which was already `bond_or_other`.
- Saba Capital Income & Opportunities Fund II (`multi_asset` → `balanced`) — sibling pair now both `balanced`.
- 39 ProShares short / inverse / leveraged-short funds (`bond_or_other` / `excluded` → `passive`) — track named indexes per prospectus; classifier already lists `proshares` in `INDEX_PATTERNS` post-PR-2.

**Verifications confirmed (no UPDATE warranted):**

- 12 BlackRock muni trusts on `final_filing` — all terminated via merger Feb 2026 (Form 25-NSE wave 2026-02-09 + BusinessWire merger-completion press releases 2026-02-23). Post-merger residual NPORT-P / N-CSRS filings are administrative.
- 51 ProShares short / inverse / leveraged-short funds — all 51 (the 39 reclassified + 12 already `passive`) confirmed `passive` post-#243.

**This sync (`conv-24-doc-sync`, direct to `main`):**

- **`ROADMAP.md`** — header bumped to `conv-24-doc-sync`; `stage-b-turnover-deferred-funds` demoted P2 → P3; `canonical-value-coverage-audit` added back to P2 with note that PR #242 covered the data-pull portion; new P3 `per-fund-deferred-decisions` (Eaton Vance Tax-Advantaged variants × 3, Calamos Global Total Return Fund loader gap, N/A-cohort 96 rows); `unmerged-branch-decisions` updated to flag both DELETE per chat; new closing summary added at top of COMPLETED.
- **`docs/NEXT_SESSION_CONTEXT.md`** — this file rewritten.
- **`docs/findings/CHAT_HANDOVER.md`** — new conv-24 section at top.
- **`MAINTENANCE.md`** — last-updated bumped to conv-24.

Branch HEAD on `main`: **`f256e5e`** (PR #243 merged).

## Up next

Three threads available; the user picks which to drive next session.

### 1. Highest data-integrity impact — `fund-holdings-orphan-investigation`

302 series_ids in `fund_holdings_v2` are not in `fund_universe` (160,934 holdings rows). Includes Tax Exempt Bond Fund of America (10,606 rows), American High-Income Municipal Bond Fund (7,418), Blackstone Alternative Multi-Strategy Fund (7,152), Bond Fund of America (5,801), VOYA INTERMEDIATE BOND FUND (5,016), and 296 more. Currently flow into the NULL arm of `cross.py` 3-way `CASE` and are treated as `active` by the front-end (None → "active"). Real data integrity exposure: ~160K holdings rows showing up in active-only views today.

Required outputs: root cause (pipeline gap vs PR-1a backfill miss vs series_id renames), per-cohort breakdown (NULL `series_id` UNKNOWN sentinel vs real-looking ids), and decision on whether to backfill `fund_universe` or rewrite `cross.py` NULL semantics. See `docs/findings/fund_cleanup_batch_results.md` §1b + §1h.

### 2. Architectural — `fund-strategy-taxonomy-finalization`

Review and finalize the five edge categories in the canonical `fund_strategy` taxonomy: `balanced` (60-90% equity, vague label, arbitrary boundary), `multi_asset` (30-60% equity, arbitrary boundaries on both sides), `bond_or_other` (heterogeneous bucket; the largest miscategorisation cohort — 39 ProShares short funds — was moved out by #243), `excluded` (combines money markets / fund-of-funds / ETF wrappers — should split into specific reasons), `final_filing` (status flag, not a strategy — decide whether it belongs in `fund_strategy` at all or should become a separate `is_terminating` boolean).

Output: findings doc with row counts per category, decisions list, recommended target taxonomy. Trigger satisfied: orphan/NULL data is now on the table; the `canonical-value-coverage-audit` data-pull (PR #242 §1a–§1h) feeds this directly.

### 3. Major sequence — institution-level consolidation scoping

Mirrors the four-stage pattern the fund-level arc established: backfill → rebuild → audit → fix + rename + lock. Different surface area though:

- **Taxonomy decisions partially captured** (prior chat session, not yet executed): keep `pension`, `endowment`, `sovereign_wealth_fund` separate; merge `private_equity` + `venture_capital` → `pe_vc`; merge `wealth_management` + `family_office` → `wealth_mgmt`; merge `hedge_fund` + `multi_strategy` → `hedge_fund`. `mixed` and `unknown` still need review.
- **Data state to confront:** 1.4M+ parent-level rows in `holdings_v2.entity_type` carry legacy values (`active` / `passive` / `mixed` from old fund-level taxonomy). Canonical reads should hit `entity_classification_history.classification` / `entity_current.classification` instead.
- **Prerequisites:** `family_office` and `multi_strategy` migration from `manager_type` to `entity_classification_history` is a precondition for some merges.
- **Roadmap entry:** `parent-level-display-canonical-reads` (P2) — 18 read sites currently on `manager_type` / `entity_type` need migration; includes the `query4` silent-drop bug at [register.py:746-750](scripts/queries/register.py:746).

This thread gates the Admin Refresh System (the original project goal).

### Smaller items still open

- **per-fund-deferred-decisions** (P3) — Eaton Vance Tax-Advantaged Dividend Income + 2 NEW global variants (all `balanced`); Calamos Global Total Return Fund (loader gap, 1,412 orphan holdings rows, no `fund_universe` row); 96-row N/A cohort (loader gap).
- **unmerged-branch-decisions** (P3, both DELETE per chat) — `claude/reverent-kirch-c1fcdf` (PR #172 CLOSED, work shipped via #173) + `ui-audit-01` (PR #107 CLOSED, triage doc already on main).
- **stage-b-turnover-deferred-funds** (P3) — Vanguard Primecap / Windsor II / Equity Income (~$203B AUM) + Bridgeway Ultra-Small Company Market. Trigger: Stage B turnover detection design.
- **historical-fund-holdings-drift-audit** (P3) — 31,400 non-SYN drift rows. Snapshot semantics intentional; characterise the cohort for completeness.
- **canonical-value-coverage-audit** (P2, partially done in #242) — structured per-bucket count + AUM exposure + recommended treatment table is the still-open deliverable.
- **review-active-bucket** (CLOSED by #242 + #243) — confirmed addressed; 8 remaining named CEFs in the `active` bucket reviewed and reclassified where warranted (AMG Pantheon, AIP Lending P) or surfaced for chat (Eaton Vance variants).
- **Stage 5 cleanup DROP** — authorized on or after **2026-05-09** per `MAINTENANCE.md`.
- **Q1 2026 13F cycle** — first live cycle expected ~2026-05-15 (45-day reporting window for period ending 2026-03-31). First live exercise of the locked `fund_universe` write path under a real cycle.

## Critical context for next session

**Fund-level data architecture is solid and locked.** Single canonical column (`fund_universe.fund_strategy`); PR-2 pipeline lock (`_apply_fund_strategy_lock` + `_upsert_fund_universe` COALESCE); PR-4 JOIN-based query layer (`compute_peer_rotation._materialize_fund_agg` reads `fund_universe`, not the per-row snapshot). Display layer reads canonical via `_fund_type_label()` in `scripts/queries/common.py`. 11 PRs validated end-to-end.

**Snapshot vs canonical semantics are intentional.** Per-row, per-quarter classification at filing moment lives in `fund_holdings_v2.fund_strategy_at_filing` (snapshot, frozen by design). Canonical (locked, never-overwritten-without-analyst-approval) lives in `fund_universe.fund_strategy`. Anything that filters or buckets by active/passive **always JOINs `fund_universe`** — never reads `_at_filing`. Saba Fund I retains pre-existing snapshot drift in `fund_holdings_v2` (1,091 `active` + 1,094 `balanced`) which is intentionally preserved (canonical is correct as `balanced`; snapshot at filing moment frozen by design).

**The 301-series orphan finding from PR #242 is the most consequential open item for data integrity.** 160,934 holdings rows currently treated as active by the front-end NULL-arm fallback. Real production exposure on the active-only views.

**Institution-level should follow the same architectural pattern.** Canonical column on `entity_classification_history` / `entity_current`, constants module, shared label utility, JOIN-based query layer. The four-stage pattern (backfill → rebuild → audit → fix+rename+lock) is the template.

## Next external events

| Date | Event |
|---|---|
| **2026-05-09** | Stage 5 cleanup DROP window opens (legacy-table snapshot cleanup gate per `MAINTENANCE.md`). |
| **~2026-05-15** | Q1 2026 13F cycle (filings for period ending 2026-03-31; 45-day reporting window). First live exercise of the locked `fund_universe` write path under a real cycle. |
| **~late May 2026** | Q1 2026 N-PORT DERA bulk — first live exercise of INF50 + INF52 fixes (PR #185); first live exercise of `compute_parent_fund_map.py` quarterly rebuild (PR #191); re-run `dera_synthetic_stabilize.py --phase 3 --confirm` against the new period to absorb any net-new Tier-4-shape registrants. |
| **2026-07-23** | finra-default-flip — delete deprecation-warning path in `scripts/fetch_finra_short.py`. |
| **~mid-Aug 2026** | B3 calendar gate — post-Q1+Q2 2026 cycles, retire V1 + drop denorm columns. |

## Reminders

- **HEAD on main is `f256e5e`** (PR #243 saba-proshares-reclassify) after the fund-level cleanup arc closed.
- **Canonical fund taxonomy values:** `{active, balanced, multi_asset, passive, bond_or_other, excluded, final_filing}`. `active` is dominant (was `equity` pre-PR-4). Display label utility `_fund_type_label()` in `scripts/queries/common.py` collapses to 5 values `{active, passive, bond, excluded, unknown}`.
- **Column rename (PR-4):** prod column is `fund_holdings_v2.fund_strategy_at_filing` (was `fund_strategy` pre-2026-05-01). Staging schema (`stg_nport_holdings.fund_strategy`) intentionally retains the old name — prod write path renames at INSERT time (`s.fund_strategy AS fund_strategy_at_filing`).
- **JOIN rule (PR-4):** for any active/passive filter, **always JOIN `fund_universe`** — the canonical, locked column. The per-row, per-quarter snapshot in `fund_strategy_at_filing` is preserved intentionally for snapshot semantics but is NOT the source of truth for filters.
- **Pipeline lock (PR-2):** `_apply_fund_strategy_lock` + `_upsert_fund_universe` COALESCE in `scripts/pipeline/load_nport.py` together prevent any `fund_universe.fund_strategy` overwrite once a series carries a non-NULL value. Three-branch semantics: new series → write classifier output; existing with non-null → preserve; existing with NULL → write classifier output (backfill case).
- **Constants module (PR-3):** `ACTIVE_FUND_STRATEGIES = ('active','balanced','multi_asset')` and `PASSIVE_FUND_STRATEGIES = ('passive','bond_or_other','excluded','final_filing')` adjacent to `_fund_type_label` in [scripts/queries/common.py:291](scripts/queries/common.py:291).
- **Display layer (PR-1d):** `_fund_type_label(fund_strategy)` is the single fund-level type emitter. Map: `active|balanced|multi_asset → 'active'`, `passive → 'passive'`, `bond_or_other → 'bond'`, `excluded|final_filing → 'excluded'`, NULL/unknown → `'unknown'`.
- **PR-1d gotcha:** `get_nport_children_batch` and `get_nport_children` in `scripts/queries/common.py` SELECT and propagate `fund_strategy` in their child-dict shape. Any new consumer can read `child['fund_strategy']` without re-querying.
- **PR-1d gotcha:** `cross.py` `_cross_ownership_fund_query` no longer carries `family_name` in its response (`type` overload removed). The column stays in `fund_holdings_v2` for entity matching.
- **#243 ProShares mechanics:** all 51 ProShares short / inverse / bear ETFs now `passive` end-to-end. The N-PORT holdings shape is uniformly swap notionals + cash/T-bill collateral (across both equity-tracking inverse like SQQQ/SH and treasury-tracking inverse like TBF). Morningstar classifies all three as "passively managed Trading-Inverse" ETFs.
- **#242 12 BlackRock muni trusts:** all confirmed merged Feb 2026 via Form 25-NSE delistings + BusinessWire merger-completion press releases. Post-merger NPORT-P (2026-03-26) and N-CSRS (2026-04-07) filings are residual administrative; trusts correctly carry `final_filing`.
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
- **PR #172** (`dm13-de-discovery`) PR CLOSED; branch flagged DELETE in `conv-24-doc-sync`.
- **Sector Rotation fund-view caveat** (from PR #215): `fund_holdings_v2.report_month` trails `quarter` by one period (filing-quarter convention). Anything that wants per-month detail for a filing quarter must look up the actual `report_month` values — do not derive months from the quarter label.
- **Overlap endpoint shape** (from PR #225): `/api/v1/overlap_institution_detail` returns `{overlapping, ticker_a_only, ticker_b_only}` (was `non_overlapping`). Each section capped at top 5 by value.
