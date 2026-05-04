# CP-5 Discovery — Institutional Rollup Read Layer Scoping

**Date:** 2026-05-04
**Branch:** `cp-5-discovery`
**HEAD baseline:** `9d9c606` (PR #275 conv-28-doc-sync)
**Refs:**
- [docs/findings/institution_scoping.md](institution_scoping.md) (prior CP-5-adjacent work)
- [docs/decisions/inst_eid_bridge_decisions.md](../decisions/inst_eid_bridge_decisions.md) (BLOCKER 2 + cp-4b carve-out addendum)
- [docs/findings/cp-4b-discovery.md](cp-4b-discovery.md) (the 19 LOW cohort)
- [docs/findings/cp-4b-blocker2-corroboration-probe.md](cp-4b-blocker2-corroboration-probe.md) (Bucket A-D + carve-out)
- [docs/decisions/d4-classification-precedence.md](../decisions/d4-classification-precedence.md) (D4 rule)
- [ROADMAP.md](../../ROADMAP.md) (CP-5 entry, cp-4c-manual-sourcing absorbed)

**Methodology:** read-only investigation. Zero DB writes. All probes empirically computed against prod DuckDB at session time, pinned to `quarter='2025Q4'` for point-in-time consistency.

---

## 1. Top-parent inventory (Phase 1)

### 1a. Top-parent enumeration

A "top parent" is an institution-typed entity with no incoming `entity_relationships` open row of `control_type IN ('control', 'mutual', 'merge')` from another institution.

| metric | value |
| --- | ---: |
| total institution-typed entities | 14,038 |
| top-parent institutions | **13,687** |
| institutions with an inst-inst rollup parent | 351 |
| total open `entity_relationships` rows | 16,324 |

**Schema-level finding:** The plan-original `control_type IN ('control', 'beneficial')` predicate does not match this schema — `'beneficial'` does not exist. Actual open-row distribution:

| control_type | open rows | inst→inst | inst→fund | fund→fund | fund→inst |
| --- | ---: | ---: | ---: | ---: | ---: |
| advisory | 15,925 | 499 | 15,400 | 26 | 0 |
| control | 374 | 370 | 0 | 0 | 4 |
| mutual | 23 | 23 | 0 | 0 | 0 |
| merge | 2 | 2 | 0 | 0 | 0 |

For institution → top-parent climb, CP-5 should use `control_type IN ('control', 'mutual', 'merge')` (395 candidate edges). `'advisory'` represents IA-to-fund relationships and is not a parent-child structural edge for institutions.

### 1b. Multi-hop traversal

Iterative climb across 14,038 seed institutions converged at hop=20 (max bound). Hop distribution:

| hop_count | n |
| ---: | ---: |
| 0 | 13,687 |
| 1 | 338 |
| 2 | 9 |
| 3 | 3 |
| 20 (cycle) | 1 |

Standalone institutions (no parent, no children): 13,440. The rollup graph is **shallow and thin** — only 351 institutions have any institutional parent at all, and 9 institutions have a 2-hop or deeper chain. **One cycle detected** — eid pair sharing mutual ownership. CP-5 implementation must include cycle protection.

### 1c. Fund → top-parent

| metric | value |
| --- | ---: |
| open fund→institution rollup rows (`entity_rollup_history`) | 26,442 |
| funds without a resolved top-parent | 469 |

Top-50 top-parents by fund count are dominated by Fidelity/FMR (1,147 funds), BlackRock/iShares (1,024), Invesco (704), First Trust (626), ProShares (525). Full output: see Phase 1 console log.

### 1d. Form coverage matrix (point-in-time, 2025Q4)

`is_latest=TRUE` is **multi-period** in both source tables (holdings_v2: 4Q rolling; fund_holdings_v2: 6Q rolling with bulk in 2024Q4–2026Q1). For accurate point-in-time AUM, the coverage matrix is pinned to `quarter='2025Q4'` and `asset_category='EC'` on the fund-tier side.

| coverage_class | n top-parents | 13F AUM ($B) | fund-tier EC AUM ($B) | combined ($B) |
| --- | ---: | ---: | ---: | ---: |
| 13F_only | 8,051 | 36,221.9 | 0.0 | 36,221.8 |
| both | 407 | 31,045.0 | 37,454.2 | 68,499.2 |
| fund_only | 315 | 0.0 | 22,682.7 | 22,682.7 |
| neither | 4,914 | 0.0 | 0.0 | 0.0 |

Top-20 by combined AUM: Vanguard $23.3T, Fidelity/FMR $10.1T, BlackRock Inc $6.8T, BlackRock/iShares $5.8T (fund_only — the cp-4b brand-vs-filer split visible at the top), Capital Group/American Funds $5.6T (fund_only), State Street/SSGA $4.6T, etc. Full output: [data/working/cp-5-top-parent-coverage-matrix.csv](../../data/working/cp-5-top-parent-coverage-matrix.csv) (top-100 by combined AUM).

**Critical caveat — the AUM totals are not directly comparable across forms.** 13F covers only Section 13(f)-reportable equity positions; N-PORT EC covers all registered-fund equity holdings (including ETFs, mutual funds, and other 1940 Act vehicles). The Vanguard 13F filer reports $6.9T but Vanguard's funds collectively report $16.4T equity on N-PORT — this is not a contradiction but a statement that the 13F filer entity captures a smaller subset of the firm's overall equity exposure than its fund-side filings.

---

## 2. Empirical 13F vs N-PORT overlap probe (Phase 2)

### Cohort

Top-20 'both'-coverage top-parents by combined AUM × 3 sample tickers (AAPL large-cap, NEE mid-cap, AVDX small-cap) = 60 (top_parent, ticker) pairs.

### Results

| classification | n pairs | meaning |
| --- | ---: | --- |
| neither | 20 | AVDX universally absent — not a top-100 institutional holding |
| 13F_dominant (B/A < 0.85) | 17 | 13F captures more than fund-tier (BlackRock, MS, GEODE, Northern Trust, Franklin, UBS, AB, Schwab) |
| fund_extends_13F (B/A > 1.15) | 15 | fund-tier exceeds 13F (Vanguard, Fidelity, DFA, T.Rowe, First Trust, Victory, Manulife, Principal) |
| 13F_covers_fund (0.85 ≤ B/A ≤ 1.15) | 4 | near-equal (Wellington AAPL, Ameriprise AAPL+NEE, Manulife NEE) |
| 13F_only | 4 | fund-tier returned $0 despite known footprint (Schwab, Dodge & Cox — likely fund-chain rollup gap) |

Aggregate ratio summary (excluding neither / one-side-only): median B/A = 0.883, p10 = 0.017, p90 = 3.867. **The distribution is bimodal**, not centered — 47% of pairs are 13F-dominant, 42% are fund-extending.

### Anomalies

- **T. Rowe Price**: ratio = 1,022× for AAPL, 915× for NEE. Filer eid 3616 reports almost nothing; T. Rowe funds collectively hold the equity. Confirms cp-4b finding — 13F filer entity ≠ brand-level reach. The cp-4b carve-out bridge (relationship_id=20820) is structurally necessary for any reader that wants T. Rowe's true footprint.
- **Schwab + Dodge & Cox** (13F_only despite known footprint): fund-chain rollup is broken for these top-parents in the current schema. Surface as Phase 6 follow-up.
- **AVDX universally zero**: small-cap is not held meaningfully by these mega-firms. Not a data bug — empirical signal.

Full output: [data/working/cp-5-overlap-probe.csv](../../data/working/cp-5-overlap-probe.csv) (60 rows).

### Recommended deduplication rule — R5

Plan-original options R1–R4 each fail this empirical distribution:

- **R1 (13F primary, fund-tier residual)**: fails for the 15 fund_extends pairs — adding fund-tier residual to 13F double-counts the underlying positions, since each form independently aggregates the same fund's holdings. Adding them produces inflated totals.
- **R2 (combined union, larger-of)**: closer, but underspecified — does not address fund-of-fund cross-holdings.
- **R3 (13F when present, fund-tier when not)**: fails for 15 fund_extends cases where 13F is present but materially smaller than fund-tier.
- **R4 (source-form-aware per coverage_class)**: too coarse — the choice between forms is per (top_parent, ticker, cusip), not per top_parent.

**Proposed R5**: per `(top_parent_entity_id, ticker, cusip)` triple,

```
aum_dedup = GREATEST(
    COALESCE(13F_aggregated_to_top_parent, 0),
    COALESCE(fund_tier_aggregated_to_top_parent_ASSET_CATEGORY_EC, 0)
)
source_winner = CASE WHEN 13F_aggregated >= fund_tier THEN '13F_wins'
                     ELSE 'fund_wins'
               END
```

Each form independently aggregates the same underlying positions; `MAX` captures the higher-confidence number without double-counting. The `source_winner` tag preserves transparency for callers (Register tab can show "via 13F" or "via N-PORT" alongside the AUM).

**Limitations of R5 surfaced by the Phase 4 probe — must be addressed before R5 is production-ready:**

1. **Fund-of-fund cross-holdings** (e.g., Vanguard's top R5 positions include VSMPX/VGTSX/VTBIX = Vanguard's own funds held by other Vanguard funds, $1.5T inflated). R5 must filter positions where the held security is itself a fund issued by the same top-parent.
2. **N-PORT CUSIP gaps** (Vanguard's #1 R5 position is `ticker=NULL / cusip='N/A'` worth $1.75T from N-PORT rows where issuer maps to nothing). R5 must either drop these or surface them in a separate "unmapped" bucket.
3. **Schwab / Dodge & Cox 13F_only anomaly** — the fund-chain rollup is incomplete for these firms; R5 will silently undercount until fund-chain integrity is restored.

---

## 3. Affected reads inventory (Phase 3)

27 reader sites mapped across 11 distinct tabs/features. Full data: [data/working/cp-5-affected-readers.csv](../../data/working/cp-5-affected-readers.csv).

### Tab counts (some sites span multiple tabs)

| tab/feature | reader sites |
| --- | ---: |
| Register | 7 |
| Flows / Conviction | 4 |
| Cross-Ownership | 3 |
| Entity Drilldown | 3 |
| Crowding (Top Holders / Sector / Smart Money / Trend) | 4 (overlapping) |
| Conviction Fund Portfolio | 1 |
| Trend | 1 |
| All tabs (NPORT bridge / common helpers) | 3 |

### Traversal depth distribution

| traversal_depth | n |
| --- | ---: |
| name-coalesce-only | 21 |
| single-hop ER | 4 |
| multi-hop recursive CTE | 1 |
| single-hop per ER read | 1 |

**78% of sites do `COALESCE(rollup_name, inst_parent_name, manager_name)` — no entity-keyed rollup at all.** The de facto rollup pattern is denormalized strings on `holdings_v2`. CP-5 either needs to re-denormalize these columns to top-parent values, or refactor readers to JOIN against an entity-keyed top-parent map.

### Cross-form integration

**Only 3 readers touch fund_holdings_v2 directly**: cross.py:330-360, trend.py:170-205, common.py:488-820. Of those:
- cross.py is name-keyed (parallel to its 13F sibling, no integration);
- trend.py uses `parent_fund_map` (the only entity-keyed fund-tier reader — useful template);
- common.py is **REGEX NAME MATCH** (`match_nport_family` patterns table) — the fragile bridge that retires when CP-5 lands an entity-keyed unified read.

`summary_by_parent` is **NAME-KEYED** and used by Register N-PORT coverage display. CP-5 needs an entity-keyed rebuild of this cache table.

---

## 4. Architecture recommendation (Phase 4)

### Performance benchmarks — R5 inline view

Three reader use cases benchmarked against the full R5 CTE definition (no precomputed materialization):

| use case | cold (ms) | warm (ms) |
| --- | ---: | ---: |
| (a) Top-25 holders for AAPL | 201.8 | **35.3** |
| (b) Top-50 by combined AUM | 279.3 | **340.2** |
| (c) All Vanguard (eid=4375) positions | 72.6 | **45.1** |

Max warm runtime: 340 ms — well under the 500 ms threshold for "view is fine" decision.

### Sizing for precomputed alternative

| metric | value |
| --- | ---: |
| holdings_v2 rows (is_latest=TRUE, 4Q rolling) | 12,270,984 |
| fund_holdings_v2 EC rows (is_latest=TRUE, 6Q rolling) | 7,624,870 |
| unified rows per quarter (R5 dedup) | ~2,625,205 |
| 4Q rolling unified table | ~10,500,820 |
| 6Q rolling unified table | ~15,751,230 |

### Recommendation

**Inline VIEW, not precomputed table.** Warm runtimes are 35–340 ms across all three reader patterns, comfortably within budget. A precomputed table adds refresh complexity (per-quarter rebuild on every N-PORT/13F load) for marginal speedup. If a future reader pattern degrades past 1s warm, revisit with that specific query as the test case.

Output: [data/working/cp-5-arch-bench.csv](../../data/working/cp-5-arch-bench.csv).

---

## 5. View 2 (fund-tier / PM-level) assessment (Phase 5)

### Current fund universe coverage

| metric | value |
| --- | ---: |
| fund-typed entities | 13,221 |
| distinct fund_ciks filing N-PORT (2025Q4) | 1,954 |
| 13F filers without N-PORT counterpart (estimate) | ~9,000+ |

### N-PORT coverage by fund_strategy_at_filing (2025Q4 EC)

| fund_strategy_at_filing | n funds | EC AUM ($B) |
| --- | ---: | ---: |
| passive | 199 | 15,349.4 |
| active | 868 | 11,375.4 |
| excluded | 218 | 3,409.9 |
| balanced | 314 | 1,148.6 |
| multi_asset | 154 | 202.3 |
| bond_or_other | 563 | 99.4 |

### 13F-filer-only universe (no N-PORT decomposition possible)

| manager_type | filers | 13F AUM ($B, 2025Q4) |
| --- | ---: | ---: |
| hedge_fund | 987 | 2,446.0 |
| wealth_management | 363 | 3,004.1 |
| pension_insurance | 133 | 1,877.5 |
| private_equity | 102 | 333.9 |
| endowment_foundation | 60 | 185.9 |
| SWF | 13 | 142.8 |
| activist | 19 | 90.6 |
| family_office | 47 | 20.1 |
| **subtotal (no N-PORT path)** | **~1,724** | **~$8,100** |

### Recommendation

View 2 is structurally limited by data availability — ~$8T of 13F AUM is held by entities (hedge funds, SMAs, pensions, insurance, SWFs) that do not file N-PORT. The current Fund Portfolio tab already serves the registered-fund-side decomposition. View 2 scope:

- **Tier 1 (already exists)**: N-PORT-filing registered funds — 1,954 funds, $31.6T EC. Covered by existing Fund Portfolio readers.
- **Tier 2 (incremental)**: 13D/G partial data for >5% positions on non-N-PORT filers (already partially ingested per memory).
- **Tier 3 (gap)**: Hedge fund / SMA / pension full portfolios — no public source. View 2 cannot recover these without Form PF (private SEC data, not public) or commercial data feeds.

CP-5 should not over-scope View 2. Treat it as the existing Fund Portfolio tab + entity-keyed integration with the new top-parent rollup, plus an explicit "no decomposition available" surface for Tier 3 holders.

---

## 6. cp-4c brand re-categorization (Phase 6)

Per chat decision 2026-05-04, cp-4c-manual-sourcing absorbs into CP-5. The 19 LOW cohort brands from cp-4b discovery + 4 already-bridged brands re-categorize as follows:

| category | n | total fund AUM ($B) | treatment |
| :-: | ---: | ---: | --- |
| A — already bridged via cp-4b carve-out | 4 | 2,055.4 | No CP-5 action; existing relationship_ids 20820–20823 (T.Rowe, First Trust, FMR, SSGA) sufficient |
| B — clean 13F counterparty, needs bridge | 13 | 8,040.8 | CP-5.5 — 1-2 sub-PRs grouped by source-tier |
| C — no 13F counterparty by design | 3 | 2,444.8 | CP-5 read layer reaches fund_holdings_v2 directly via rollup graph (no bridge needed) |

Full data: [data/working/cp-5-brand-categorization.csv](../../data/working/cp-5-brand-categorization.csv).

### Category B prioritized (top-3 by AUM)

| brand_eid | brand | fund AUM $B | candidate filer |
| ---: | --- | ---: | --- |
| 18073 | J.P. Morgan Investment Management Inc. | 2,714.5 | JPMorgan Chase & Co (eid 4433) |
| 9904 | TEACHERS ADVISORS, LLC | 1,571.1 | Nuveen / TIAA |
| 1355 | FRANKLIN ADVISERS INC | 1,162.8 | Franklin Resources |

### Category C

PIMCO ($2.04T) is the largest by fund AUM — fixed-income house with no meaningful 13F counterparty. WisdomTree ($262B) and Macquarie ($138B) have ETF-primary or multi-jurisdictional structures. All three reach via `fund_holdings_v2` directly under R5; no bridge work blocks read-layer rollout.

---

## 7. Recommended PR sequence

| PR | description | depends on |
| --- | --- | --- |
| (chat) | Schema/architecture decision lock — R5 dedup rule including fund-of-fund filter + null-cusip handling, inline-view choice, two-view scope | this discovery |
| **CP-5.1 — read-layer-foundation** | New helper `build_top_parent_join()` in `queries_helpers.py`; entity-keyed inst→top_parent map (materialized as a small lookup table or DuckDB macro); cycle-safe traversal; tests | chat decision |
| **CP-5.2 — unified-holdings-view** | R5 inline view as a CTE/macro consumable by all readers; fund-of-fund filter + null-cusip exclusion; tests covering all 4 classification buckets from Phase 2 | CP-5.1 |
| **CP-5.3 — register-tab-migration** | Migrate 7 Register reader sites from name-coalesce to entity-keyed R5; rebuild `summary_by_parent` keyed on top_parent_entity_id | CP-5.2 |
| **CP-5.4a — cross-ownership-migration** | Migrate 3 Cross-Ownership sites (and trend.py readers Crowding/Smart Money/Trend share) | CP-5.2 |
| **CP-5.4b — flows-conviction-migration** | Migrate flows.py 4 sites + portfolio_context | CP-5.2 |
| **CP-5.5 — bridge-cohort-cleanup** | 13 Category B bridges, grouped by parent (e.g., Franklin Resources covers FRANKLIN ADVISERS + PUTNAM = 2 brands; FMR LLC bridge covers brand 11 + brand 2400 = 2 brands) | CP-5.2 (independent of order) |
| **CP-5.6 — view-2-integration** | Hedge-fund / SMA "no decomposition available" surface; 13D/G integration where partial data exists | CP-5.4 |
| **conv-29-doc-sync** | Capture all CP-5 sub-decisions in ROADMAP / inst_eid_bridge_decisions / NEXT_SESSION_CONTEXT | last |

---

## 8. Open questions for chat decision

These are architecturally material decisions that should lock in chat before any execution PR is authored.

1. **R5 fund-of-fund filter — definition.** Phase 4 surfaced VSMPX/VGTSX/VTBIX in Vanguard's top R5 positions ($1.5T inflated). The filter needs to exclude positions where the held security is a fund issued by the same top-parent. Implementation requires either: (a) a `fund_issuer_top_parent` lookup column on the security side, or (b) a self-join filtering CUSIPs that resolve to a fund whose rollup chain reaches the same top-parent. Which path?

2. **R5 null-cusip handling.** Vanguard's #1 R5 position is `ticker=NULL / cusip='N/A'` worth $1.75T from N-PORT. Drop these from R5 entirely, or surface them in a separate "unmapped" bucket with a totals-line caveat?

3. **`is_latest=TRUE` semantics.** Both source tables hold multi-period rows under this flag. Should CP-5 readers always pin to a `quarter` parameter (current convention), or should the unified view itself materialize per-quarter and let callers pick?

4. **Top-parent definition control_type set.** CP-5 climb uses `('control', 'mutual', 'merge')`. The 499 inst→inst `'advisory'` rows are excluded — are any of these structurally parent-child (e.g., a parent firm advising its own subsidiaries)? If so, include or partition?

5. **summary_by_parent rebuild scope.** Today this is name-keyed. Under CP-5, rebuild keyed on top_parent_entity_id — does the Register N-PORT coverage UI need backwards compatibility (the column it surfaces is `nport_coverage_pct`), or is a clean cutover acceptable?

6. **Schwab / Dodge & Cox fund-chain anomaly.** Phase 2 surfaced these as 13F_only despite known fund footprints. Investigate as part of CP-5.1 (data-quality fix) or defer to a separate workstream?

7. **Category C brand-side roll-up.** PIMCO ($2.04T), WisdomTree, Macquarie reach fund_holdings_v2 directly. Should the inst→top_parent map include explicit no-13F flag for these brands so readers can present "fund-tier only" labels, or infer from the coverage_class column?

8. **Entity Drilldown alignment.** entities.py:120-170 already does multi-hop ER traversal but excludes `sub_adviser` edges and uses a different control_type filter than CP-5's recommended set. Align both, or keep them deliberately separate (drilldown wants more relationship types than rollup)?

9. **Performance margins.** Use case (b) at 340 ms warm is comfortably under threshold. But it's measured on a single-user DuckDB connection — what's the concurrency budget? If 10 simultaneous users hit /smart_money, does 340 ms become 3.4 s? If yes, revisit precomputed table.

10. **Migration safety net.** The 21 name-coalesce reader sites carry the existing rollup_name denormalization. Cutover order: replace rollup_name population (re-denormalize to top_parent), or migrate readers one-at-a-time? Big-bang vs. incremental?
