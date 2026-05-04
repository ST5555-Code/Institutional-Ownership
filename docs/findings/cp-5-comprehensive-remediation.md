# CP-5 Comprehensive Remediation Plan

**Synthesized:** 2026-05-04
**Branch:** `cp-5-comprehensive-discovery-bundle-d`
**HEAD baseline:** `002b72e` (PR #280 cp-5-comprehensive-discovery-bundle-c)
**Inputs:**
- [docs/findings/cp-5-discovery.md](cp-5-discovery.md) — PR #276 original scoping (27 reader inventory, R5 v0)
- [docs/findings/cp-5-bundle-a-discovery.md](cp-5-bundle-a-discovery.md) — PR #277 R5 defects + N-PORT completeness
- [docs/findings/cp-5-bundle-b-discovery.md](cp-5-bundle-b-discovery.md) — PR #278 entity tier inventory + 21 cycle truncations + Option C
- [docs/findings/cp-5-coverage-matrix-revalidation-results.md](cp-5-coverage-matrix-revalidation-results.md) — PR #279 R5 LOCKED Verdict A (2× double-count fix)
- [docs/findings/cp-5-bundle-c-discovery.md](cp-5-bundle-c-discovery.md) — PR #280 Method A + decision_maker_v1 canonical, GEODE pattern, 64 writer sites

**Cross-references:**
- [docs/decisions/d4-classification-precedence.md](../decisions/d4-classification-precedence.md)
- [docs/decisions/inst_eid_bridge_decisions.md](../decisions/inst_eid_bridge_decisions.md) (BLOCKER 2 + cp-4b carve-out addendum)
- [ROADMAP.md](../../ROADMAP.md)

**Status:** Bundles A, B, C and the matrix revalidation are read-only investigations with all open questions resolved. This document synthesizes the four into a single design contract, pre-execution work list, CP-5 execution sequence, post-CP-5 backlog, risk register, and dependency graph. All figures pinned to `quarter='2025Q4'`, `is_latest=TRUE`, EC asset_category for fund-tier rollup.

---

## 1. Executive Summary

CP-5 is a read-layer rebuild that introduces a unified institutional-ownership view spanning 13F (`holdings_v2`) and N-PORT (`fund_holdings_v2`). It replaces the de facto `COALESCE(rollup_name, inst_parent_name, manager_name)` pattern (78% of 27 reader sites) with an entity-keyed top-parent rollup deduplicated under R5: per `(top_parent_entity_id, ticker, cusip)` triple, take `MAX(13F-aggregated, fund-tier-adjusted)`.

**Design contract — locked across the four bundles:**

| decision | source |
| --- | --- |
| R5 dedup rule (modified): `MAX(13F, fund_adj)` with intra-family FoF subtraction (~$2.21T) and non-valid-CUSIP filter (~$5.17T) | Bundle A §1.4; revalidated Bundle B §0.5 + PR #279 Verdict A |
| Method A canonical for fund→top-parent climb (read-time `entity_rollup_history` JOIN, not denormalized `dm_rollup_entity_id`) | Bundle C §7.1 |
| `decision_maker_v1` canonical for institutional rollup (View 1); `economic_control_v1` retained for parallel sponsor-view queries | Bundle C §7.2 |
| Time-versioning Option C (hybrid): time-invariant default + explicit M&A overrides when historical data loads | Bundle B §4.4 |
| Two-canonical-classifications: institution → `entity_classification_history`; fund → `fund_universe.fund_strategy` | locked 2026-05-03 (NEXT_SESSION_CONTEXT) |
| Operating-AM rollup policy: terminate at operating asset manager; never at bank/insurance/holding-co parent | memory + Bundle B §2.5 |
| View 2 scope: full PM decomposition for N-PORT funds; 13F-D where partial; Tier-3 "no decomposition" sentinel for $4.9T hedge/SMA/pension/family/SWF cohort | Bundle C §8.3 |
| BLOCKER 2 carve-out (cp-4b) | locked 2026-05-03 per inst_eid_bridge_decisions.md (PR #269 addendum) |

**Pre-execution work — 6-9 PRs before CP-5.1:**

| item | source | AUM exposure |
| --- | --- | ---: |
| 21 cycle-truncated entity merges (~10-11 pairs) | Bundle B §2.2 | not AUM-priced; correctness unblock |
| 84K loader-gap rows (entity_id IS NULL) | Bundle B §2.4 | $418.5B fund-tier |
| Capital Group umbrella decision (3 filer arms) | Bundle B §1.3 | $7,153B 13F (4Q rolling) |
| Adams Asset Advisors duplicate (eids 4909+19509) | Bundle B §3.3 | XS |
| Pipeline contract gaps (writer-gate hardening) | Bundle C §7.5 | per-pipeline |

**CP-5 execution work — 6-8 PRs:**

| stage | scope | size |
| --- | --- | :-: |
| CP-5.1 — read-layer foundation | R5 helper + Method A view | M |
| CP-5.2 — Register tab | 7 reader sites + summary_by_parent rebuild | M |
| CP-5.3 — Cross-Ownership / Top Investors / Top Holders | 3 reader sites + sub-shares | M |
| CP-5.4 — Crowding / Conviction / Smart Money | 4 reader sites (Conviction is L) | M-L |
| CP-5.5 — Sector Rotation / New-Exits / AUM / Activist | 4-6 reader sites | S |
| CP-5.6 — View 2 Tier-3 sentinel + UI | $4.9T no-decomposition surfacing | M |

**Post-CP-5 backlog — 9 items:** securities canonical_type loader fix, Pipelines 4/5/7, cp-4c brand bridges (13 brands ~$8T), Workstream 3 fund-to-parent residuals, N-PORT data-drift confirm-closure, fund-classification-by-composition confirm-closure, Adams residual.

**Aggregate AUM exposure of pre-execution + CP-5 work:** the pre-execution corrections move ~$420B of currently-unrouted fund-tier rows into rollup, plus structural correction of $7.15T Capital Group footprint and ~$3T from cycle-merge consolidation. The CP-5 read-layer rebuild governs ~$75T of corrected-matrix combined coverage (top-100, post-double-count fix).

---

## 2. Design Contract (Locked)

### 2.1 R5 Dedup Rule

For each `(top_parent_entity_id, ticker, cusip)` triple in 2025Q4:

```
fund_tier_adjusted = SUM(fund_holdings_v2.market_value_usd) for top_parent
                     via Method A climb,
                     EXCLUDING:
                       - rows where cusip is non-valid (NA_lit, zeros_or_nines, NULL)
                       - rows where asset_category != 'EC'
                       - intra-family FoF (held cusip resolves to a fund whose
                         top_parent matches the outer fund's top_parent)

thirteen_f          = SUM(holdings_v2.market_value_usd) for top_parent
                     via inst_to_top_parent climb

result        = GREATEST(COALESCE(thirteen_f, 0), COALESCE(fund_tier_adjusted, 0))
source_winner = '13F_wins' if thirteen_f >= fund_tier_adjusted else 'fund_wins'
```

For `13F_only` top-parents: `thirteen_f` only, with reason tag (`genuine_hedge_or_pension`, `foreign_domiciled`, `wealth_aggregator`, `brand_vs_filer_pending_bridge`).

For `fund_only` top-parents (Capital Group, BlackRock/iShares, Schwab, JPM IM): `fund_tier_adjusted` only.

**Inflation adjustments quantified:** intra-family FoF subtraction −$2,207B; non-valid CUSIP filter (EC only) −$5,172B; non-EC asset_category drop already excluded by predicate. Adjusted fund-tier at 2025Q4 reduces from $31.6T raw to ~$24.2T clean.

**Source:** Bundle A §1.4; revalidated PR #279 Verdict A (envelope flags 0/25 across top-25).

### 2.2 Method A canonical (climb mechanism)

`JOIN entity_rollup_history erh ON erh.entity_id = fh.entity_id AND erh.rollup_type = 'decision_maker_v1' AND erh.valid_to = '9999-12-31'`, then climb `inst_to_top_parent` from `erh.rollup_entity_id`.

Method B (`fund_holdings_v2.dm_rollup_entity_id` denormalized at load time) is **not** canonical — it goes stale after every ERH rebuild. The SSGA cp-4b brand-bridge (PR #271) created the live evidence: Method A reports SSGA fund-tier $807.8B; Method B reports $1,586.0B (a $778.2B drift from a stale denormalization). Method B's residual role is as a cache-invalidation signal: rows where `dm_rollup_entity_id ≠ Method A` flag the loader denormalization for backfill.

**Source:** Bundle C §7.1 (Open Q1 RESOLVED).

### 2.3 decision_maker_v1 canonical for institutional view (View 1)

`entity_rollup_history.rollup_type = 'decision_maker_v1'` is canonical for R5's institutional rollup. `economic_control_v1` is retained as a parallel role keyed by sponsor / fund-family / registrant umbrella ("who runs this product family").

Empirical: 1,826 of 13,221 funds (13.8%) have `decision_maker_v1.rollup_entity_id ≠ economic_control_v1.rollup_entity_id`; for BlackRock Inc., the choice swings fund-tier AUM by 27%. Choosing dm aligns the fund-tier rollup with the 13F filer (sub-adviser when discretion-bearing, named adviser otherwise), so R5 dedups within firm cleanly. Choosing ec would put fund-tier and 13F on different top_parents and cross-firm-double-count under R5.

**Source:** Bundle C §7.2 (Open Q2 RESOLVED).

### 2.4 Time-versioning Option C (hybrid)

`entity_relationships` schema already supports SCD via `valid_from` / `valid_to`. Today's graph is **time-invariant** (378 of 395 inst→inst control rows have default `valid_from = 2000-01-01`). For the 2025Q1+ data we currently load this is correct. When historical (pre-2025) data is loaded, capture 20–30 known M&A events as explicit `valid_from` overrides per the existing SCD schema; modify the rollup builder + readers to honor `valid_from <= holdings.report_date < valid_to`.

**Not a CP-5 execution dependency.** Defer the M&A event register to Pipeline 4+ scope.

**Source:** Bundle B §4.4.

### 2.5 Two-canonical-classifications

- **Institution** classification → `entity_classification_history` (read via `decision_maker_v1` rollup).
- **Fund** classification → `fund_universe.fund_strategy` (six-class taxonomy; populated 100% per Bundle A §2.4).
- Reads route by `entity_type` of the queried entity.

**Source:** locked 2026-05-03 in `docs/NEXT_SESSION_CONTEXT.md`; reaffirmed by Bundle A §2.4 (zero NULL fund_strategy in fund_universe; Workstream 2 root closeable).

### 2.6 Operating-AM rollup policy

The rollup must terminate at the operating asset manager. It does not climb into bank / insurance / holding-company parents. Active candidate violations (Bundle B §2.5):

| top_parent | name | 13F $B | fund-tier $B | corrected verdict |
| ---: | --- | ---: | ---: | --- |
| 8424 | Bank of America Corp /DE/ | 1,473.9 | 0.0 | flag — should roll to BoA Wealth / Merrill operating AM |
| 7440 | Royal Bank of Canada | 614.7 | 0.0 | flag — should roll to RBC Wealth / RBC GAM |
| 1401 | Bank of New York Mellon Corp | 567.7 | 0.0 | flag — should roll to BNY Investments / BNY Wealth |
| 8994 | Manulife Financial Corp | 121.7 | 148.1 (corrected) | flag — should roll to Manulife IM |
| 91 | Norges Bank | 934.8 | 0.0 | valid — Norges Bank IM IS the manager (sovereign wealth) |

3-4 candidate violations covering ~$2.78T 13F. Address via separate ER `control` edges from operating AM to bank/insurance parent. Display issue, not query correctness — defer to post-CP-5.

**Source:** memory rule + Bundle B §2.5.

### 2.7 View 2 scope

| tier | cohort | size | treatment |
| :-: | --- | ---: | --- |
| Tier 1 | N-PORT-filing registered funds | 1,954 funds / $31.6T EC | full PM-level decomposition via existing Fund Portfolio + `parent_fund_map`; integrate with new entity-keyed rollup at CP-5.6 |
| Tier 2 | 13D/G partial (>5% positions, non-N-PORT filers) | partial | already partially loaded by Pipeline P1; surface as "PM partial" with caveat |
| Tier 3 | hedge fund / SMA / pension / family / SWF / VC / activist / endowment | $4.9T 13F | display as institutional-tier with explicit "no fund decomposition available" sentinel flag |

**Total non-decomposable cohort (Tier 3):** $4.9T across 1,367 filers (Bundle C §8.1).

**Source:** Bundle C §8.3 (extends cp-5-discovery §5).

### 2.8 BLOCKER 2 carve-out (reference)

cp-4b BLOCKER 2 carve-out locked 2026-05-03 per PR #269 addendum (4 brands: T. Rowe / First Trust / FMR / SSGA, ~$2,055.4B), with 15 brands ($10.27T) deferred under documented normalization-collapse FP mode.

**Source:** [docs/decisions/inst_eid_bridge_decisions.md](../decisions/inst_eid_bridge_decisions.md). Reference only — already in effect.

---

## 3. Pre-Execution Work (Must ship BEFORE CP-5.1)

### 3.1 Cycle-truncated entity merges

**Scope:** 21 entities forming ~10-11 mutually-cycling pairs whose top-parent climb is broken by a self-cycle. cp-4a-style MERGE op shape per PR #256 precedent.

| pair | example |
| --- | --- |
| Goldman Sachs Asset Management | eid 22 ↔ eid 17941 |
| Lazard Asset Management | eid 58 ↔ eid 18070 |
| Lord, Abbett & Co. LLC | eid 893 ↔ eid 17916 |
| Ariel Investments | eid 70 ↔ eid 18357 |
| Sarofim Trust Co | eid 858 ↔ eid 18029 |
| Thornburg Investment Management | eid 2925 ↔ eid 18537 |
| (4-5 more: Lewell, Equitable, Stonebridge, Financial Partners, etc.) | |

**Source:** Bundle B §2.2.

**AUM exposure:** correctness unblock — `build_top_parent_join()` in CP-5.1 will misroute holdings under the duplicate eid until merged.

**Sequencing:** **before CP-5.1.** Recommended 2-3 batched merge PRs by sector or AUM grouping. Always transfer CIK on survivor before closing source per memory rule (~$166B INF4c lesson).

### 3.2 84K loader-gap row remediation

**Scope:** 84,363 rows / $418.5B / 76 fund_ciks / 104 series with `entity_id IS NULL` on `fund_holdings_v2`. 100% of the cohort fails ingestion-time entity linking (recharacterized from Bundle A §2.1's "rollup builder gap" to a loader gap in Bundle B §2.4).

| recovery class | top-50 share | path |
| --- | ---: | --- |
| linkable to existing `entity_identifiers` | 23 (46%) | UPDATE `fund_holdings_v2.entity_id` from JOIN on (cik, series_id) |
| requires new fund-typed entity | 27 (54%) | insert via existing fund-creation pattern |

Top contributors: American Funds Bond Fund $101.1B, Tax Exempt Bond Fund $48.2B, Intermediate Bond Fund $28.5B, American High-Income Municipal Bond $26.6B, American High Income Trust $26.3B, Global Opportunities Portfolio $24.6B.

**Source:** Bundle B §2.4.

**Sequencing:** before CP-5.1 for material AUM coverage; can also slip to CP-5.5 if execution-time tradeoff favors it. Recommend 1 loader-fix PR + 1 entity-creation PR + 1 rollup-rebuild PR (3 sub-PRs), or combined as 1 larger PR if op-shapes align. Chat decides at execution time (open item §9.2).

### 3.3 Capital Group umbrella decision

**Scope:** 3 sibling filer arms. Anomalous shape — no other firm in the surveyed top tier uses an umbrella pattern. Capital Group (eid 12) currently has 0 13F + 0 fund-tier; the 3 arms each file their own 13F:

| eid | name | 13F $B (4Q rolling) |
| ---: | --- | ---: |
| 6657 | Capital World Investors | 2,772.49 |
| 7136 | Capital International Investors | 2,346.46 |
| 7125 | Capital Research Global Investors | 2,034.06 |

Total Capital Group footprint: $7,153B (4Q rolling, ~$1.79T per quarter).

**Two paths:**

| path | description |
| --- | --- |
| A — three independent BRIDGE PRs | 3 separate `control` ER rows: Capital World → eid 12, Capital International → eid 12, Capital Research Global → eid 12 (cp-4b precedent shape — 4 PRs each authored a separate `control` row). |
| B — umbrella entity creation + 3 sibling relationships | New synthetic Capital Group AMC parent; all 4 eids point to it via `control`. |

**Source:** Bundle B §1.3.

**Sequencing:** before CP-5.1 (matches cp-4b precedent that completed for T. Rowe / First Trust / FMR / SSGA). Either path is structurally workable; chat decides at execution time (open item §9.1).

### 3.4 Adams Asset Advisors duplicate

**Scope:** 1 likely entity merge — eid 4909 (has CIK) + eid 19509 (no CIK), same display_name "Adams Asset Advisors, LLC". (Bundle A's "120 cohort" was universe-wide; Adams-specific is just this one merge, not 6.)

**Source:** Bundle B §3.3.

**Sequencing:** trivial; bundle with 3.1 cycle-merge cohort.

### 3.5 Pipeline contract gaps

Per Bundle C §7.5, seven contract-hardening gaps surfaced. Each is a writer-gate hardening or backlog item similar to PR #263:

| # | gap | size | sequencing |
| - | --- | :-: | --- |
| a | `fund_holdings_v2` entity_id load-time linking gap (the 84K rows) | M | before CP-5.1 (= 3.2 above; this is the loader-side fix) |
| b | `fund_holdings_v2.dm_rollup_entity_id` denormalization staleness | S | post-CP-5 OK (Method A is canonical → drift is invisible to readers); decide drop-or-backfill |
| c | `securities.canonical_type` mis-classification on fund share classes | S | post-CP-5 (zero user-facing reader blast today) |
| d | `bootstrap_*_advisers.py` (3 scripts, 18 write sites) one-shot scripts in production code | S | post-CP-5 (retire / gate / leave-as-is) |
| e | M&A event capture in `entity_relationships.valid_from` | L | post-CP-5; only relevant when 10+ year load is scoped |
| f | LEI ingestion (Pipeline P7) — 0% coverage | M | post-CP-5 backlog |
| g | `entity_relationships.is_inferred` flag underused | XS | post-CP-5 audit hygiene |

Only gap (a) is pre-execution; the rest are post-CP-5 backlog. Listed here for completeness.

**Source:** Bundle C §7.5.

### Pre-execution PR estimate

**6-9 PRs total** (3 cycle-merge batches + 3 loader-gap sub-PRs + 1 Capital Group + 1 Adams merge bundled into cycle batch). **Pre-execution AUM exposure:** $418.5B (loader-gap) directly + structural Capital Group resolution.

---

## 4. CP-5 Execution Work

Sequencing: pre-execution ships first; CP-5.1 lands the foundation; CP-5.2-5.6 ship in parallel where readers don't share files.

### 4.1 CP-5.1 — R5 helper + Method A view definition

**Scope:** single PR. Implements:
- `classify_institutional_holding(top_parent_eid, ticker, cusip)` helper following the `classify_fund_strategy` (queries/common.py) precedent.
- R5 view definition per cp-5-discovery §5 architecture recommendation. Inline view (35-340ms warm benchmarks across three reader patterns) is sufficient; precomputed table not needed unless concurrency budget tests fail later.
- Method A climb (read-time `entity_rollup_history` JOIN) on `decision_maker_v1`.
- Cycle-safe traversal with hop bound ≤ 10 (Bundle B §2.1 max actual hop count = 3).
- Tests covering all 4 classification buckets from Phase 2 (13F_dominant, fund_extends_13F, 13F_covers_fund, 13F_only).
- Foundation that all subsequent reader migrations consume.

**Size:** M.

**Dependencies:** all pre-execution work clears (cycle-merges, loader-gap rows, Capital Group umbrella).

**Chat decision needed at PR time:** in-line view vs precomputed table (re-confirm view per cp-5-discovery §5; open item §9.4).

### 4.2 CP-5.2 — Register tab reader migration

**Scope:** migrate 7 Register reader sites from name-coalesce to entity-keyed R5; rebuild `summary_by_parent` keyed on `top_parent_entity_id`.

**Size:** M.

**Dependencies:** CP-5.1.

**Chat decision needed:** `summary_by_parent` rebuild approach — new entity-keyed table alongside legacy NAME-keyed (cutover later) vs in-place rebuild with downtime window? Bundle C open Q7.

### 4.3 CP-5.3 — Cross-Ownership / Top Investors / Top Holders

**Scope:** migrate 3 Cross-Ownership reader sites. Coordinate to keep readers consistent across "Top Investors Across Group" and "Top Holders by Company".

**Size:** M.

**Dependencies:** CP-5.1.

### 4.4 CP-5.4 — Crowding / Conviction / Smart Money

**Scope:** 4 reader sites (Conviction sized as L because it joins R5 + View 2 + manager_aum + manager_type imputation; Crowding / Smart Money share readers).

**Size:** M-L.

**Dependencies:** CP-5.1, CP-5.3 (shares trend.py readers).

### 4.5 CP-5.5 — Sector Rotation / New-Exits / AUM / Activist

**Scope:** smaller readers — Sector Rotation (1 site), New/Exits Flows (2 sites), AUM (in Register query16), Activist (in Flows + Register).

**Size:** S.

**Dependencies:** CP-5.1; safe to ship in parallel with CP-5.3/5.4.

### 4.6 CP-5.6 — View 2 Tier-3 sentinel + UI handling

**Scope:** surface "no decomposition available" flag for $4.9T non-decomposable cohort (hedge / SMA / pension / family / SWF / VC / activist / endowment). UI work + entity-keyed integration with the new top-parent rollup. Includes Tier 2 13D/G "PM partial" surfacing and Entity Drilldown alignment.

**Size:** M.

**Dependencies:** CP-5.1, CP-5.4 (Conviction shares portfolio_context).

### CP-5 PR estimate

**6-8 PRs total** in CP-5.1 + CP-5.2 + CP-5.3 + CP-5.4 (possibly split into 2) + CP-5.5 + CP-5.6.

---

## 5. Post-CP-5 Backlog

Items that ship after CP-5 closes. Not blocking the rebuild.

### 5.1 Securities canonical_type loader fix

`pipeline/cusip_classifier.py` mis-classifies institutional fund share classes as `'COM'` instead of `MUTUAL_FUND` / `ETF` / `CEF`. ~$2.7T AUM / 1,613 cusips affected (VSMPX, VGTSX, VTBIX, VTSMX, VTBLX, VTILX, FXAIX, FCFMX, FSGEX, etc.). Loader fix consults `securityType2` / `securityType` alongside `marketSector`; one-shot backfill of existing `securities` rows. Zero user-facing reader blast today (no readers filter on `canonical_type`); defect is invisible to CP-5.

**Source:** Bundle C §7.3.

### 5.2 Pipeline 4 — monthly N-PORT (NPORT-MP)

Private monthly N-PORT data, not loaded today (by design — data is non-public for institutional ownership rollup; quarterly granularity sufficient since 13F is quarter-end). Backlog.

**Source:** Bundle A §2.5; memory.

### 5.3 Pipeline 5 — share class

`fund_classes` table exists from N-CEN (31,056 rows / 13,197 series) but carries no per-class holdings or AUM. Per-class portfolio decomposition is not recoverable (all classes within a series share the portfolio). Affects fund-tier display, not institutional rollup.

**Source:** Bundle C §6.1.

### 5.4 Pipeline 7 — LEI standardization

0% LEI coverage today across all entity tiers. GLEIF-side ingestion would improve cross-jurisdiction reconciliation. Pipeline-side gap.

**Source:** Bundle B §3.1 + memory.

### 5.5 cp-4c brand bridges (Category B residual)

13 brands ~$8.04T need bridges to existing 13F counterparties. Top-3 by AUM:

| brand_eid | brand | fund AUM $B | candidate filer |
| ---: | --- | ---: | --- |
| 18073 | J.P. Morgan Investment Management Inc. | 2,714.5 | JPMorgan Chase & Co (eid 4433) |
| 9904 | TEACHERS ADVISORS, LLC | 1,571.1 | Nuveen / TIAA |
| 1355 | FRANKLIN ADVISERS INC | 1,162.8 | Franklin Resources |

Plus 3 Category C brands ($2.44T — PIMCO, WisdomTree, Macquarie) with no 13F counterparty by design; CP-5 read layer reaches `fund_holdings_v2` directly, no bridge needed.

**Source:** cp-5-discovery §6 + Bundle A §1.3 (Capital Group already split into pre-execution work §3.3).

### 5.6 Workstream 3 — fund-to-parent linkage residuals

After 84K loader-gap PR ships, residual fund-tier rollup edge cases (post-merge cleanup, brand-vs-filer long tail beyond Category B). Backlog.

### 5.7 N-PORT data drift cleanup (CONFIRMED CLOSED)

Bundle A §2.2 reported 0 multi-accession buckets on the `historical-drift-audit` cohort. The 31K-row historical reference predated cef-residual-cleanup + INF9 series triage cascade. ROADMAP entry can close — confirm in conv-29-doc-sync.

**Source:** Bundle A §2.2.

### 5.8 fund-classification-by-composition — Workstream 2 root (CONFIRMED CLOSED)

Bundle A §2.4 reported 0 NULL `fund_strategy` in `fund_universe`. Workstream 2 input is empty. ROADMAP entry can close — confirm in conv-29-doc-sync. (Orphan-fund classification residual remains but reframed under §3.2 84K loader-gap path.)

**Source:** Bundle A §2.4.

### 5.9 Adams duplicate handling residual

Post-merge cleanup if any duplicates surface beyond §3.4. The Adams-specific cohort is small (1 likely merge); the universe-wide 120-Layer-A cohort is distributed across many families — backlog per family.

**Source:** Bundle B §3.3.

---

## 6. Risk Register and Known Limitations

### 6.1 GEODE-pattern sub-adviser cross-firm double-count

R5 dedups within a single `top_parent`. When a sub-adviser files its own 13F because it crosses the threshold (GEODE eid 7859 = $1.62T, sub-advising 23 Fidelity index series), the same equity slice attributes to both GEODE and Fidelity (eid 10443) under separate top-parents. R5 does not catch this cross-firm overlap.

**Affected pattern:** ~5-10 cross-firm sub-adviser pairs (BlueCove $277.5B, Wellington $189.0B as sub-adviser, DFA Ltd $356.6B, T. Rowe Price as sub-adviser $237.8B, FIAM $149.8B, etc.).

**Treatment:** Document as known limitation; build a "watch list" query for the cross-firm overlap cohort. A separate cross-firm dedup pass at the (cusip, ticker) level distorts firm-level attribution and is out of CP-5 scope.

**Source:** Bundle C §6.2.

### 6.2 $4.9T View 2 non-decomposable cohort

Hedge funds, SMAs, pensions, insurance, family offices, SWFs, VCs, activist managers, endowments — these structurally lack fund-tier decomposition (no N-PORT counterparty by design). View 2 surfaces the "no decomposition available" sentinel flag at CP-5.6.

**Source:** Bundle C §8.1.

### 6.3 Hedge-fund 13F-D coverage gaps

`holdings_v2` has no `filing_type` column — 13F-HR vs 13F-D is not distinguishable in current loader. Hedge fund partial decomposition via 13F-D is a Pipeline P1 backlog item, not part of CP-5.

**Source:** Bundle C §8.2.

### 6.4 Share-class decomposition unavailable in N-PORT-P

N-PORT-P discloses holdings at the **series** level. Share classes within a series share the same portfolio and the same disclosure. Per-class portfolio decomposition is not recoverable.

**Source:** Bundle C §6.1.

### 6.5 Securities canonical_type mis-classification (until §5.1 fix)

~$2.7T of fund share classes mis-tagged `'COM'`. Bundle A's FoF Pass A misses these but Pass B (name-match) recovers them, so modified-R5 FoF subtraction is correct in spite of the defect. Forward-compat risk only.

**Source:** Bundle C §7.3.

### 6.6 Method B denormalization staleness

`fund_holdings_v2.dm_rollup_entity_id` becomes stale after every ERH rebuild. Method A reads live entity-graph state at query time — invisible to readers. Surface as cache-invalidation signal: rows where `dm_rollup_entity_id ≠ Method A` flag for backfill.

**Source:** Bundle C §7.1.

---

## 7. Dependency Graph

```
PRE-EXECUTION (must clear before CP-5.1)
├── 3.1 Cycle-merge batch A    ┐
├── 3.1 Cycle-merge batch B    │— parallel; 2-3 PRs
├── 3.1 Cycle-merge batch C    ┘
├── 3.4 Adams merge (bundled with 3.1)
├── 3.3 Capital Group umbrella (independent; chat decides path A or B)
└── 3.2 84K loader-gap
    ├── loader-fix PR
    ├── entity-creation PR
    └── rollup-rebuild PR
            │
            ▼
CP-5 EXECUTION (foundation first, then parallel reader migrations)
└── CP-5.1 — R5 helper + Method A view (FOUNDATION)
        │
        ├──▶ CP-5.2 — Register tab + summary_by_parent rebuild
        │
        ├──▶ CP-5.3 — Cross-Ownership / Top Investors / Top Holders
        │       │
        │       └──▶ CP-5.4 — Crowding / Conviction / Smart Money
        │               │
        │               └──▶ CP-5.6 — View 2 Tier-3 sentinel + UI
        │
        └──▶ CP-5.5 — Sector Rotation / New-Exits / AUM / Activist (parallel)
                │
                ▼
POST-CP-5 BACKLOG (independent; lower priority)
├── 5.1 securities canonical_type loader fix
├── 5.2 Pipeline 4 (NPORT-MP)
├── 5.3 Pipeline 5 (share class)
├── 5.4 Pipeline 7 (LEI)
├── 5.5 cp-4c brand bridges (13 Cat-B brands)
├── 5.6 Workstream 3 (fund-to-parent residuals)
├── 5.7 N-PORT data-drift confirm-closure (in conv-29)
├── 5.8 fund-classification-by-composition confirm-closure (in conv-29)
└── 5.9 Adams residual + 120-Layer-A long tail
```

Companion data: [data/working/cp-5-execution-plan.csv](../../data/working/cp-5-execution-plan.csv) — per-PR seq_order, size, AUM impact, dependencies, chat decisions.

---

## 8. Closures from Bundle Discovery (Confirmed)

These items can close in conv-29-doc-sync. Each is empirically confirmed by the four bundles.

| item | source | evidence |
| --- | --- | --- |
| `historical-drift-audit` | Bundle A §2.2 | 0 multi-accession buckets on real series_id. The "31K rows" referenced in ROADMAP predated cef-residual-cleanup + INF9 series triage. |
| `fund-classification-by-composition` Workstream 2 root | Bundle A §2.4 | 0 NULL `fund_strategy` in `fund_universe`. Workstream 2 input is empty. (Orphan-fund classification residual remains but reframed via §3.2 path.) |
| Schwab/Dodge & Cox 13F_only anomaly | Bundle A §1.3, Bundle B §1.3 | Eid 5 (Schwab) is pure `fund_only` $1,345B; eid 15 (D&C) is `both`-coverage with normal 13F+fund-tier. Anomaly was sampling artifact, not structural. |
| Original cp-4c-manual-sourcing scope | chat 2026-05-04, cp-5-discovery §6 | Folded into CP-5: 4 brands done via cp-4b ($2,055.4B), 13 Cat-B brands queued as §5.5 backlog ($8.04T), 3 Cat-C brands reach via R5 directly. |

---

## 9. Open Items for Chat at Execution Time

Decisions deferred to execution PRs. Not blockers — but each PR will need a chat-side call.

### 9.1 Capital Group umbrella path

§3.3 lists path A (3 separate `control` ER rows, cp-4b precedent) and path B (umbrella entity creation). Chat decides at execution time.

**Recommendation lean (Bundle B §1.3):** path A — matches cp-4b precedent for T. Rowe / FMR / SSGA / First Trust; no new schema artifact.

### 9.2 84K loader-gap PR shape

§3.2 lists single PR vs three sub-PRs (loader-fix + entity-creation + rollup-rebuild). Concentration: most AUM is in the top 30 CIKs (American Funds bond family).

**Recommendation lean:** three sub-PRs to keep op-shapes clean.

### 9.3 21 cycle-truncated merge batching

§3.1 lists 2-3 batched merge PRs. Possible groupings: by sector (alts vs traditional), by AUM (large first), or alphabetical for review predictability.

**Recommendation lean:** by AUM (large pairs first) so any merge gate failures surface early.

### 9.4 In-line view vs precomputed table for CP-5.1

cp-5-discovery §5 benchmarks: 35-340ms warm runtimes across three reader patterns. Recommendation in cp-5-discovery is in-line view; reconfirm at CP-5.1 prompt time.

**Recommendation lean:** in-line view; revisit only if a future reader pattern degrades past 1s warm.

### 9.5 Method B disposition

After CP-5.1 lands and Method A is canonical, decide whether to (a) backfill `fund_holdings_v2.dm_rollup_entity_id` after every ERH rebuild as a loader contract, (b) keep as cache-invalidation signal only, or (c) drop the column entirely.

**Recommendation lean (Bundle C §7.5b):** (b) cache-invalidation signal — preserves a low-cost data-quality check without a refresh contract.

### 9.6 Sub-adviser handling — Option A vs B vs C

Bundle C §6.2d lists three options. Recommendation Option C (hybrid: named adviser primary via `decision_maker_v1`; sub-adviser secondary view via separate query). Reconfirm at CP-5.4 / CP-5.6 PR time.

### 9.7 summary_by_parent rebuild approach

§4.2 / Bundle C open Q7. New entity-keyed table alongside legacy NAME-keyed (cutover later) vs in-place rebuild with downtime window.

**Recommendation lean:** new alongside legacy → cutover. Avoids downtime window and gives reader migrations a backwards-compat safety net.

### 9.8 bootstrap_*_advisers.py disposition

Bundle C §7.5d. Retire / gate behind feature flag / leave-as-is. 3 scripts, 18 write sites. Post-CP-5 cleanup.

**Recommendation lean:** gate behind a feature flag (one shared `--bootstrap-mode` arg); avoids breaking a future bootstrap need.

---

## 10. Status

- **All open architectural questions across Bundles A, B, C, and revalidation are resolved.** Bundle C resolved Open Q1 (Method A) and Open Q2 (decision_maker_v1); revalidation locked R5 LOCKED Verdict A; Bundle B locked Option C time-versioning.
- **conv-29-doc-sync (next, separate PR)** updates ROADMAP + NEXT_SESSION_CONTEXT to reflect closures (§8) and the new CP-5 execution sequence + architectural locks (§2).
- **CP-5 pre-execution work begins after conv-29:** 3.1 cycle-truncated merges, 3.3 Capital Group umbrella, 3.2 84K loader-gap, 3.4 Adams.
- **CP-5.1 read-layer-foundation** ships once pre-execution clears; CP-5.2-5.6 follow per §7 graph.
