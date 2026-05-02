# Next session context

> This file is single-session handoff only. It is overwritten at the start of each session and reset at the end. Multi-session work lives in `ROADMAP.md`.

## Last completed

**fund-universe-value-corrections ([#248](https://github.com/ST5555-Code/Institutional-Ownership/pull/248), squash `8253713`) — closes the cleanup arc opened by PRs #244 → #245 → #246 → #247.** Two value corrections to `fund_universe` plus a forward-looking guard on the original backfill script. Builds on PR #246's audit findings B1 + B2.

| Phase | Outcome |
| --- | --- |
| 1 — re-validate (read-only) | Rareview `S000090077` confirmed at `fund_strategy='excluded'`. 301 rows tagged `strategy_source='orphan_backfill_2026Q2'` confirmed all NULL on `total_net_assets` (no drift from PR #245). Canonical N-PORT TotalNetAssets is not persisted at series level in prod — reconstructs exactly from `fund_holdings_v2` via `NAV = MEDIAN(market_value_usd * 100.0 / pct_of_nav)` on the most-recent quarter's `is_latest=TRUE` rows. Validated against 10 funds with existing TNA: ratio = 1.000000…. **Key finding:** `pct_of_nav` is stored on the percent scale (0–100), not fraction. |
| 2 — dry-run manifest | New `scripts/oneoff/correct_fund_universe_values.py --dry-run`. Block A (1 row) + Block B (300 rows after de-dup fix) = 301 entries. 300/300 canonical, 0 fallback, 0 NULL-residual. Total Block B NAV = $450.1B. NAV/SUM(mv) median = 1.004; outliers reflect option-strategy ETFs where N-PORT shows only MMF collateral rows (reconstruction correct in spot-checks). |
| 3 — execute | Block A flipped Rareview `excluded → passive`, `strategy_source → 'unknown_cleanup_2026Q2'`, `total_net_assets → $4,555,216`; Block B populated TNA on 300 rows. **Mid-flight bug + correction:** initial `--confirm` had Block A's `strategy_source` re-overwritten by Block B (Block B's manifest filter included Rareview because at dry-run time it was tagged `orphan_backfill_2026Q2` with NULL TNA). Corrected via one-shot UPDATE (1 row, single tx). Script patched so a hypothetical replay would not reproduce the bug: `derive_block_b_manifest` excludes Block A's series_id; new `derive_block_a_nav` lets Block A's UPDATE set TNA in the same statement. |
| 4 — pipeline guard | `scripts/oneoff/backfill_orphan_fund_universe.py` patched to derive `total_net_assets` during manifest construction (canonical-first via `pct_of_nav`, `SUM(mv)` fallback, NULL-residual surfaced) and write it on INSERT. Forward-looking only — existing 301-row cohort already corrected. |
| 5 — validation | `pytest tests/` 373/373 PASS in 58.17s. Final cohort counts: 300 `orphan_backfill_2026Q2` + 1 `unknown_cleanup_2026Q2` = 301, all with TNA, NULL-residual = 0. 5 random spot-checks plausible. `cd web/react-app && npm run build` 0 errors, 2.32s. |

**Architecture / safety:** No `--reset`, no pipeline write-path module modified. Single-transaction Phase 3 with hard guards (Phase 1 drift gate, post-update residual NULL check, ROLLBACK on constraint violation). PR-2 pipeline lock not on critical path; corrections are explicit manual overrides tagged with `strategy_source`.

**Output:** `scripts/oneoff/correct_fund_universe_values.py` (new); `scripts/oneoff/backfill_orphan_fund_universe.py` (forward-looking patch); `data/working/fund_universe_corrections_manifest.csv`; `docs/findings/fund_universe_corrections_dryrun.md`; `docs/findings/fund_universe_corrections_results.md`.

---

**fund-stale-unknown-cleanup ([#247](https://github.com/ST5555-Code/Institutional-Ownership/pull/247), squash `0296107`) — flipped `is_latest=FALSE` on the BRANCH 1 portion of the stale-loader artifact surfaced by PR #246.** Builds on PR #246.

| Phase | Outcome |
| --- | --- |
| 1 — re-validate cohort | 8 (cik, fund_name) pairs / 3,184 rows / $10.025B at `series_id='UNKNOWN' AND is_latest=TRUE`; matches PR #246 audit (drift gate 0%). |
| 2 — dry-run manifest | New `scripts/oneoff/cleanup_stale_unknown.py` per-pair branch classifier. BRANCH 1 (live SYN_ companion → FLIP) = 6 pairs / 2,738 rows / $5.283B; BRANCH 2 (no SYN_ companion → HOLD) = 2 pairs / 446 rows / $4.741B (Adams ADX, ASA Gold ASA); BRANCH 3 = 0. **Calamos shifted from #246's HOLD into FLIP** — the v2 loader has since written `SYN_0001285650` (1,459 is_latest=TRUE rows). Phase 2 dry-run committed in pre-decision SHA `940576c`. Chat decision: BRANCH 1 only; BRANCH 2 deferred to new P2 `cef-attribution-path` workstream. |
| 3 — execute is_latest flip | Single transaction. `--confirm --accept-deferred-holds` (new opt-in flag for the BRANCH 2 deferral). Pre-flip 3,184 → post-flip 446 (Δ -2,738 == expected). All gates honored. |
| 4 — peer_rotation_flows rebuild | Run ID `peer_rotation_empty_20260502_095212` (parse 46.7s + promote 193.1s, ~4 min). Total 17,490,106 → 17,489,751 (Δ -355, 0.002%, well within ±0.5%). Snapshot at `data/backups/peer_rotation_peer_rotation_empty_20260502_095212.duckdb`. |
| 5 — validation | `pytest tests/` 373/373 PASS in 56.46s. `audit_unknown_inventory.py` re-run: residual 1 series / 446 rows / $4.74B (= 2 deferred BRANCH 2 pairs, expected). `audit_orphan_inventory.py` re-run: same 446 / $4.74B. `cd web/react-app && npm run build`: 0 errors, 1.41s. Per-pair `is_latest=TRUE` spot-checks: 6/6 FLIP pairs return SYN_-only; 2/2 HOLD pairs preserved as UNKNOWN. |

**Spot-check semantics (Phase 4):** `peer_rotation_flows.entity` is keyed on `fund_name`, not `series_id`. Same-fund_name pairs (Eaton Vance 242→121 rows, NXG 121→66 rows) cleanly de-duped from prior double-counting; case-different Calamos UNKNOWN-side entity (`'Calamos Global Total Return Fund'`) vanished while SYN_-side entity (`'CALAMOS GLOBAL TOTAL RETURN FUND'`, uppercase) unchanged at 127 rows / $47.6M.

**Architecture / safety:** UPDATE-only on `is_latest` flag. No INSERT, no `fund_universe` touched, no `series_id` rewrite, no synthesized SYN_ rows. PR-2 pipeline lock not on critical path. No write-path module modified. Apr-15 v2 loader bug surfaced in results doc but not patched (out of scope per brief).

**Output:** `scripts/oneoff/cleanup_stale_unknown.py`, `data/working/stale_unknown_cleanup_manifest.csv`, `docs/findings/fund_stale_unknown_cleanup_dryrun.md`, `docs/findings/fund_stale_unknown_cleanup_results.md`. ROADMAP.md adds COMPLETED entry + new P2 `cef-attribution-path` workstream.

---

**fund-unknown-attribution (PR #246, squash `1956ea8`) — read-only audit closing the orphan/unknown thread end-to-end.** Builds on PR #245.

| Layer | Outcome |
| --- | --- |
| 1 — surface map | `_fund_type_label()` at [scripts/queries/common.py:308](scripts/queries/common.py:308) is the sole NULL→'unknown' path; `cross.py` 3-way CASE arms emit NULL for the same gap. Other 'unknown' literals are `manager_type` fallbacks, not fund_strategy. No surprise paths. |
| 1 — master inventory | `fund_universe.fund_strategy IS NULL` count = 0. Display 'unknown' bucket comes entirely from holdings orphans: 1 series (literal `series_id='UNKNOWN'`), 3,184 rows / $10.025B / 8 distinct (cik, fund_name) pairs. Cohorts B/C/D from the brief are empty. |
| 1 — Cohort A reattribution | All 8 pairs map to existing SYN_ series (6 HIGH, 1 MEDIUM, 1 LOW, 0 NONE). Stale-loader root cause: Apr-3 legacy loader wrote `'UNKNOWN'`; Apr-15 v2 loader (e868772) wrote SYN_ companions but did not flip `is_latest=FALSE` on legacy rows. 5 of 8 pairs have BOTH versions live; 3 (Adams 'N/A', Asa Gold, Calamos) have only the stale UNKNOWN version. |
| 2 — three-lens validation | 296/301 PASS_ALL on PR #245 backfill cohort. 3 false positives, 1 known Blackstone override, 1 real reclass candidate: `S000090077` Rareview 2x Bull Cryptocurrency & Precious Metals ETF (currently `excluded`; classifier order says `passive` because `\dx` in INDEX_PATTERNS precedes ETF in EXCLUDE_PATTERNS; ~$0 net AUM). |
| 2 — completeness gap noted | All 301 orphan_backfill `fund_universe` rows have `total_net_assets=NULL`. Backfill flow populated `fund_strategy` only. |

**Output:** `docs/findings/fund_unknown_attribution.md` + `scripts/oneoff/audit_unknown_*.py` (3 helpers, all read-only — verified via grep). pytest tests/ 373/373 PASS unchanged.

**fund-orphan-backfill (PR #245, squash `9392a36`) closed the 302-series orphan exposure surfaced by PR #244.** Single PR, branch `fund-orphan-backfill`, backup carried over from PR-4 (`data/backups/13f_backup_20260501_103837`).

| Phase | Outcome |
| --- | --- |
| 1 — re-validate | 302 series / 160,934 rows / $658.5B against current `data/13f.duckdb` (matches PR #244 audit). S9digit 301 / 157,750 rows / $648.5B; UNKNOWN_literal 1 / 3,184 / $10.0B. |
| 2 — dry-run manifest | 301 entries (300 majority-vote, all 100% support_pct + 1 manual override S000045538 Blackstone Alternative Multi-Strategy Fund → `multi_asset`). 0 SKIP-list matches in S9-digit cohort (Calamos / Eaton Vance both live under `series_id='UNKNOWN'`). Manifest at `data/working/orphan_backfill_manifest.csv`. |
| 3 — backfill | Single transaction. Pre-INSERT collision check passed (0 manifest series_ids existed in `fund_universe`). 301 INSERTs tagged `strategy_source='orphan_backfill_2026Q2'`. `fund_universe` 13,623 → 13,924. |
| 4 — peer_rotation rebuild | Run ID `peer_rotation_empty_20260501_235841` (parse 69.7s + promote 222.9s; ~5 min). Total 17,490,106 → 17,490,106 (Δ +0). Snapshot at `data/backups/peer_rotation_peer_rotation_empty_20260501_235841.duckdb`. |
| 5 — display layer | `cross.py` both 3-way `CASE` blocks now carry comment block tying NULL = unknown to PR #244 + this PR (behavior unchanged at SQL level). `_fund_type_label()` verified (already returns `'unknown'` for unmapped). `OverlapAnalysisTab.tsx` row filter (L194) AND active-KPI subset (L213) tightened to `r.is_active === true`. |
| 6 — validation | `pytest tests/` 373/373 PASS. Audit re-run: residual = 1 series / 3,184 rows / $10.0B (UNKNOWN_literal only, by design). PR-1d display contract validator: PASS. `npm run build`: 0 errors. 5 spot-checks all canonical + tagged. Blackstone override ✓. |

**Insert distribution (Phase 3):** bond_or_other 133 series / 119,701 rows / $558.7B; excluded 136 / 17,619 / $66.9B; passive 25 / 13,047 / $20.3B; multi_asset 1 / 7,152 / $2.5B; active 6 / 231 / $0.03B.

**This sync (direct to `main`):**

- **`ROADMAP.md`** — new 2026-05-02 row for fund-universe-value-corrections (PR #248, squash `8253713`) added above the existing fund-stale-unknown-cleanup row.
- **`docs/NEXT_SESSION_CONTEXT.md`** — this file rewritten with PR #248 added at the top, PR #247 demoted below the divider.

Branch HEAD on `main`: **`8253713`** (PR #248 fund-universe-value-corrections; Rareview reclass + 301-row TNA backfill + pipeline guard). Prior commit `ab376f1` (post-#247 close-out), then `0296107` (PR #247 fund-stale-unknown-cleanup).

## Up next

Two threads still queued; the user picks which to drive next session.

### 1. Architectural — `fund-strategy-taxonomy-finalization`

Review and finalize the five edge categories in the canonical `fund_strategy` taxonomy: `balanced` (60-90% equity, vague label, arbitrary boundary), `multi_asset` (30-60% equity, arbitrary boundaries on both sides), `bond_or_other` (heterogeneous bucket; the largest miscategorisation cohort — 39 ProShares short funds — was moved out by #243), `excluded` (combines money markets / fund-of-funds / ETF wrappers — should split into specific reasons), `final_filing` (status flag, not a strategy — decide whether it belongs in `fund_strategy` at all or should become a separate `is_terminating` boolean).

Output: findings doc with row counts per category, decisions list, recommended target taxonomy. Triggers now satisfied: orphan/NULL data is on the table; `canonical-value-coverage-audit` data-pull (PR #242 §1a–§1h) feeds this directly; orphan cohort backfilled (PR #245); BRANCH 1 of the stale-loader artifact flipped (PR #247) — only the 2-pair / 446-row CEF residual under `cef-attribution-path` remains.

### 2. Major sequence — institution-level consolidation scoping

Mirrors the four-stage pattern the fund-level arc established: backfill → rebuild → audit → fix + rename + lock. Different surface area:

- **Taxonomy decisions partially captured** (prior chat session, not yet executed): keep `pension`, `endowment`, `sovereign_wealth_fund` separate; merge `private_equity` + `venture_capital` → `pe_vc`; merge `wealth_management` + `family_office` → `wealth_mgmt`; merge `hedge_fund` + `multi_strategy` → `hedge_fund`. `mixed` and `unknown` still need review.
- **Data state to confront:** 1.4M+ parent-level rows in `holdings_v2.entity_type` carry legacy values (`active` / `passive` / `mixed` from old fund-level taxonomy). Canonical reads should hit `entity_classification_history.classification` / `entity_current.classification` instead.
- **Prerequisites:** `family_office` and `multi_strategy` migration from `manager_type` to `entity_classification_history` is a precondition for some merges.
- **Roadmap entry:** `parent-level-display-canonical-reads` (P2) — 18 read sites currently on `manager_type` / `entity_type` need migration; includes the `query4` silent-drop bug at [register.py:746-750](scripts/queries/register.py:746).

This thread gates the Admin Refresh System (the original project goal).

### Smaller items still open

- **per-fund-deferred-decisions** (P3) — Eaton Vance Tax-Advantaged Dividend Income + 2 NEW global variants (all `balanced`); Calamos Global Total Return Fund (loader gap, 1,412 holdings rows under `series_id='UNKNOWN'`); 96-row N/A cohort. **Note:** Calamos / Eaton Vance Tax-Advantaged were the SKIP-list patterns in PR #245 — they currently funnel into the literal `series_id='UNKNOWN'` sentinel (UNKNOWN_literal cohort, intentionally left orphan by PR #245). Resolution requires source-side rework (loader gap), not another `fund_universe` backfill.
- **unmerged-branch-decisions** (P3, both DELETE per chat) — `claude/reverent-kirch-c1fcdf` (PR #172 CLOSED, work shipped via #173) + `ui-audit-01` (PR #107 CLOSED, triage doc already on main).
- **stage-b-turnover-deferred-funds** (P3) — Vanguard Primecap / Windsor II / Equity Income (~$203B AUM) + Bridgeway Ultra-Small Company Market. Trigger: Stage B turnover detection design.
- **historical-fund-holdings-drift-audit** (P3) — 31,400 non-SYN drift rows. Snapshot semantics intentional; characterise the cohort for completeness.
- **canonical-value-coverage-audit** (P2, partially done in #242) — structured per-bucket count + AUM exposure + recommended treatment table is the still-open deliverable.
- **Stage 5 cleanup DROP** — authorized on or after **2026-05-09** per `MAINTENANCE.md`.
- **Q1 2026 13F cycle** — first live cycle expected ~2026-05-15 (45-day reporting window for period ending 2026-03-31). First live exercise of the locked `fund_universe` write path under a real cycle.

## Critical context for next session

**Fund-level data architecture is solid, locked, and now orphan-clean.** Single canonical column (`fund_universe.fund_strategy`); PR-2 pipeline lock (`_apply_fund_strategy_lock` + `_upsert_fund_universe` COALESCE); PR-4 JOIN-based query layer. Display layer reads canonical via `_fund_type_label()`. PR #245 backfilled the 302-series orphan cohort surfaced by PR #244; PR #247 flipped `is_latest=FALSE` on 6 of the 8 UNKNOWN-literal stale pairs (2,738 rows / $5.28B); PR #248 closed B1 (Rareview reclass) + B2 (TNA backfill on all 301 orphan_backfill rows). Residual: 1 series / **446 rows / $4.74B** (2 closed-end-fund pairs Adams ADX + ASA Gold ASA, deferred to `cef-attribution-path`). 14 PRs validated end-to-end across the consolidation+cleanup+backfill arc.

**Snapshot vs canonical semantics are intentional.** Per-row, per-quarter classification at filing moment lives in `fund_holdings_v2.fund_strategy_at_filing` (snapshot, frozen by design). Canonical (locked, never-overwritten-without-analyst-approval) lives in `fund_universe.fund_strategy`. Anything that filters or buckets by active/passive **always JOINs `fund_universe`** — never reads `_at_filing`.

**Active-only views now exclude unknowns.** PR #245 tightened `OverlapAnalysisTab.tsx` from `r.is_active !== false` to `r.is_active === true` at both the row filter (L194) and the active-KPI tile (L213). Any fund with `is_active=null` (orphan from `fund_universe`) is excluded from active-only views. After PR #247 the only `is_active=null` source is the 446-row / $4.74B `cef-attribution-path` residual (Adams ADX + ASA Gold ASA).

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

- **HEAD on main is `8253713`** (PR #248 fund-universe-value-corrections — 1 row Rareview reclass + 300 rows TNA backfill via canonical N-PORT derivation + pipeline guard). Prior commit `ab376f1` (post-#247 close-out), then `0296107` (PR #247 fund-stale-unknown-cleanup).
- **PR #248 gotcha — `pct_of_nav` percent-scale convention.** `fund_holdings_v2.pct_of_nav` is stored on the percent scale (0–100), not fraction (0–1). Future code deriving NAV from holdings should use `market_value_usd * 100.0 / pct_of_nav`. Validated against 10 funds with existing `total_net_assets` (ratio = 1.000000…). MEDIAN over the most-recent quarter's `is_latest=TRUE` rows reconstructs N-PORT TotalNetAssets exactly.
- **PR #248 gotcha — `unknown_cleanup_2026Q2` provenance tag.** Rareview `S000090077` carries `strategy_source='unknown_cleanup_2026Q2'` (the only row in this cohort). All other 300 backfilled rows still carry `strategy_source='orphan_backfill_2026Q2'` (PR #245 tag, retained).
- **PR #248 gotcha — manifest overlap pattern.** When a script has multiple correction blocks targeting the same source filter, the second block's UPDATE can silently overwrite the first block's writes if the row qualifies for both filters. The fix is to exclude Block A's keys from Block B's manifest at derivation time. Documented in `docs/findings/fund_universe_corrections_results.md`.
- **Canonical fund taxonomy values:** `{active, balanced, multi_asset, passive, bond_or_other, excluded, final_filing}`. `active` is dominant (was `equity` pre-PR-4). Display label utility `_fund_type_label()` in `scripts/queries/common.py` collapses to 5 values `{active, passive, bond, excluded, unknown}`.
- **Column rename (PR-4):** prod column is `fund_holdings_v2.fund_strategy_at_filing` (was `fund_strategy` pre-2026-05-01). Staging schema (`stg_nport_holdings.fund_strategy`) intentionally retains the old name — prod write path renames at INSERT time (`s.fund_strategy AS fund_strategy_at_filing`).
- **JOIN rule (PR-4):** for any active/passive filter, **always JOIN `fund_universe`** — the canonical, locked column. The per-row, per-quarter snapshot in `fund_strategy_at_filing` is preserved intentionally for snapshot semantics but is NOT the source of truth for filters.
- **Pipeline lock (PR-2):** `_apply_fund_strategy_lock` + `_upsert_fund_universe` COALESCE in `scripts/pipeline/load_nport.py` together prevent any `fund_universe.fund_strategy` overwrite once a series carries a non-NULL value. Three-branch semantics: new series → write classifier output; existing with non-null → preserve; existing with NULL → write classifier output (backfill case).
- **Constants module (PR-3):** `ACTIVE_FUND_STRATEGIES = ('active','balanced','multi_asset')` and `PASSIVE_FUND_STRATEGIES = ('passive','bond_or_other','excluded','final_filing')` adjacent to `_fund_type_label` in [scripts/queries/common.py:291](scripts/queries/common.py:291).
- **Display layer (PR-1d):** `_fund_type_label(fund_strategy)` is the single fund-level type emitter. Map: `active|balanced|multi_asset → 'active'`, `passive → 'passive'`, `bond_or_other → 'bond'`, `excluded|final_filing → 'excluded'`, NULL/unknown → `'unknown'`.
- **PR-1d gotcha:** `get_nport_children_batch` and `get_nport_children` in `scripts/queries/common.py` SELECT and propagate `fund_strategy` in their child-dict shape. Any new consumer can read `child['fund_strategy']` without re-querying.
- **PR-1d gotcha:** `cross.py` `_cross_ownership_fund_query` no longer carries `family_name` in its response (`type` overload removed). The column stays in `fund_holdings_v2` for entity matching.
- **PR #245 gotcha — orphan-backfill stamp:** the 301 backfilled `fund_universe` rows carry `strategy_source='orphan_backfill_2026Q2'`. Any future analysis of `fund_strategy` provenance can filter on this tag to isolate the cohort.
- **PR #245 gotcha — 3-way semantics:** `cross.py` `is_active` is tri-state (TRUE / FALSE / null). Frontend `OverlapAnalysisTab.tsx` now uses strict `=== true` at both L194 (row filter) and L213 (KPI subset). Other fund-level read sites (`get_two_company_subject`, `get_overlap_institution_detail`) that emit `is_active` follow the same convention. Don't reintroduce `!== false` truthy coercion — it silently rolls null into active.
- **PR #245 gotcha — UNKNOWN_literal residual:** `series_id='UNKNOWN'` is the literal sentinel where multiple historic fund_names funnel (Calamos Global Total Return + Eaton Vance Tax-Advantaged + 6 more). 1 series / 3,184 rows / $10.0B. Left orphan by design — resolution requires source-side rework (loader gap), not another `fund_universe` backfill.
- **PR #246 gotcha — UNKNOWN_literal is solvable in-place.** Audit found all 8 (cik, fund_name) pairs map to existing SYN_ series with strategies already set. The orphan state isn't a `fund_universe` gap — it's stale holdings rows that need either (A1) `series_id` rewrite to SYN_ for the 3 stale-only pairs (1,858 rows / $5.07B: Adams 'N/A', Asa Gold, Calamos), or (A2) `is_latest=FALSE` flip for the 5 stale-redundant pairs (1,326 rows / $4.96B: Eaton Vance Tax-Adv, AIP, AMG Pantheon, NXG, Saba). Plus B1 reclass Rareview 2x Bull → 'passive' (1 row, ~$0 AUM) and B2 backfill `total_net_assets`/`equity_pct` for the 301 orphan_backfill funds (NULL across the board today). All 5 actions queued; none in #246.
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
