# CP-5 Comprehensive Discovery — Bundle C: Read/Write Audit + Pipeline Contracts + View 2

**Date:** 2026-05-04
**Branch:** `cp-5-comprehensive-discovery-bundle-c`
**HEAD baseline:** `f8e1b4a` (PR #279 cp-5-coverage-matrix-revalidation)
**Methodology:** read-only; all probes pinned to `quarter='2025Q4'`, EC asset_category for fund-tier rollup.

**Refs:**
- [docs/findings/cp-5-bundle-a-discovery.md](cp-5-bundle-a-discovery.md) (R5 defects + N-PORT completeness; locks modified-R5 §1.4)
- [docs/findings/cp-5-bundle-b-discovery.md](cp-5-bundle-b-discovery.md) (entity tier inventory, 21 cycle truncations, rollup_type Open Q2)
- [docs/findings/cp-5-coverage-matrix-revalidation-results.md](cp-5-coverage-matrix-revalidation-results.md) (R5 LOCKED Verdict A; Open Q1 ±$83B; Open Q2 13.8% diverged)
- [docs/findings/cp-5-discovery.md](cp-5-discovery.md) (the original CP-5 scoping + 27 reader inventory)
- [docs/decisions/d4-classification-precedence.md](../decisions/d4-classification-precedence.md)
- Probe scripts: [scripts/oneoff/cp_5_bundle_c_probe6_subadviser.py](../../scripts/oneoff/cp_5_bundle_c_probe6_subadviser.py), [probe7_climb_and_rollup_type.py](../../scripts/oneoff/cp_5_bundle_c_probe7_climb_and_rollup_type.py), [probe7_3_canonical_type.py](../../scripts/oneoff/cp_5_bundle_c_probe7_3_canonical_type.py), [probe7_4_readers_writers.py](../../scripts/oneoff/cp_5_bundle_c_probe7_4_readers_writers.py), [probe8_view2_coverage.py](../../scripts/oneoff/cp_5_bundle_c_probe8_view2_coverage.py)

---

## 1. Probe 6 — Share class + sub-adviser

### 6.1 Share class data availability

**Conclusion: structural. N-PORT-P does NOT carry share-class detail.**

- `fund_universe` schema has 14 columns: `fund_cik`, `fund_name`, `series_id`, `family_name`, `total_net_assets`, `total_holdings_count`, `equity_pct`, `top10_concentration`, `last_updated`, `fund_strategy`, `best_index`, `strategy_narrative`, `strategy_source`, `strategy_fetched_at`. **No** `class_id` / `class_name` / `class_ticker` / `class_cusip` columns.
- `fund_holdings_v2` likewise has no class-level columns. Series-level (`series_id`) is the smallest grain.
- `scripts/pipeline/nport_parsers.py:76-150` extracts `regCik` / `seriesId` / `seriesName` only — N-PORT-P discloses holdings at the **series** level (each filing covers one `series_id`, not a class). Share classes within a series share the same portfolio and the same disclosure.
- `fund_classes` table exists (31,056 rows / 13,197 distinct series / 31,056 distinct classes) sourced from N-CEN — that's where class identity lives. It carries `series_id, class_id, fund_cik, fund_name, report_date, quarter, loaded_at`. **No holdings**, no AUM. Class identity is recoverable; per-class portfolio decomposition is not (because all classes share the series portfolio).

**Implication for CP-5:** share-class decomposition affects **fund-tier display** (View 2) only — institutional rollup graph (View 1) terminates at `series_id`. Share-class work is a separate workstream that does NOT block CP-5 read-layer execution. Recommend documenting in conv-29 and deferring.

### 6.2 Sub-adviser layer + GEODE case study

#### 6.2a Top sub-advisers by AUM under sub-advisement

Output: [data/working/cp-5-bundle-c-subadviser-cohort.csv](../../data/working/cp-5-bundle-c-subadviser-cohort.csv).

Top-20 sub-advisers by series-weighted AUM under sub-advisement (current snapshot, 3,464 open `subadviser` rows in `ncen_adviser_map` link to 358 entities via CRD):

| sub_eid | sub_name | n_series | aum_under_subadvise_b |
| ---: | --- | ---: | ---: |
| 7069 | Fidelity Management & Research (Hong Kong) Ltd | 111 | 1,091.3 |
| 10549 | FMR Investment Management (UK) Ltd | 95 | 585.5 |
| 18098 | Dimensional Fund Advisors Ltd. | 60 | 356.6 |
| 18338 | BlueCove Limited | 20 | 277.5 |
| **7859** | **GEODE CAPITAL MANAGEMENT, LLC** | **23** | **253.4** |
| 9937 | Fidelity Management & Research (Japan) Ltd | 63 | 243.8 |
| 17924 | T. Rowe Price Associates | 75 | 237.8 |
| 18097 | DFA Australia Limited | 58 | 218.5 |
| 9935 | Wellington Management Co LLP | 109 | 189.0 |
| 9910 | FIAM LLC | 24 | 149.8 |
| 3050 | MELLON INVESTMENTS Corp | 77 | 139.6 |
| 17970 | BlackRock Investment Management, LLC | 102 | 134.9 |
| 17978 | T. Rowe Price Investment Management, Inc. | 19 | 134.1 |
| 18073 | J.P. Morgan Investment Management Inc. | 76 | 122.0 |
| 1589 | PGIM, Inc. | 25 | 118.7 |
| (5 more $90-110B; remainder $25-90B) | | | |

Sub-adviser total cohort exposure: roughly $5.6T of fund AUM has at least one sub-adviser arrangement. 16 of the top-20 are **regional / sub-adviser arms of major fund families** (Fidelity HK/UK/Japan, DFA Ltd/Australia, BlackRock IM/Singapore, T. Rowe Price Investment Mgmt, FMR Investment Mgmt UK).

#### 6.2b GEODE Capital case study

Four GEODE entities exist: eid 89 (Geode Capital Management, dormant), **eid 7859** (GEODE CAPITAL MANAGEMENT, LLC — active), eid 8685 (Trust Co — dormant), eid 9840 (Holdings — dormant).

| metric | eid 7859 (active) |
| --- | ---: |
| 13F 2025Q4 footprint | **8,528 rows / $1,620.4B** |
| fund-tier rollup_entity_id 2025Q4 EC | 0 rows / $0.0B |
| ncen role | subadviser (23 series) |

GEODE sub-advises 23 Fidelity index series (top: Total Market Index $124.7B, ZERO Total Market $33.5B, Nasdaq Composite $22.6B, ZERO Large Cap $16.5B, SAI Canada $12.4B, etc.).

**Where do GEODE-subadvised series fund-tier-attribute?**

| rollup_entity_id | rollup_name | n_rows | aum_b |
| ---: | --- | ---: | ---: |
| 10443 | Fidelity / FMR | 16,618 | 239.0 |
| 14391 | (small Pacific Select sub-fund) | 1,225 | 0.1 |
| 18022 | Constellation Investments Inc | 936 | 0.6 |
| 14397 | (Pacific Select sub-fund) | 381 | 1.1 |

**Finding (architectural).** GEODE files **its own 13F** for $1.62T because as sub-adviser it has investment discretion over Fidelity index portfolios (and crosses the $100M reporting threshold many times over). N-PORT routes the **same $239B equity slice** to Fidelity (eid 10443) because the **series_id registrant is Fidelity**. Two parallel attributions across **separate top_parents** for the same underlying $.

R5 MAX picks `MAX(GEODE 13F, Fidelity fund-tier)` per (top_parent, ticker, cusip). But these attributions don't sit on the same top_parent — Fidelity (10443) has its own 13F too ($1,961B), and GEODE (7859) is a separate top_parent. So under R5:
- Fidelity 10443 → MAX(1,961B 13F, 3,961B fund-tier) = $3,961B
- GEODE 7859 → MAX(1,620B 13F, 0B fund-tier) = $1,620B
- Combined cross-firm exposure adds the ~$240B shared slice **TWICE** to system totals.

This is a structural cross-firm double-count not addressed by R5 (which only dedups within a single top_parent). The Sub-Adviser Handling Recommendation (6.2d) addresses it.

#### 6.2c Sub-adviser pattern survey

Beyond GEODE the top-20 cohort is dominated by **same-family regional arms** (Fidelity HK, Fidelity UK, Fidelity Japan, FMR UK, DFA Ltd, DFA Australia, BlackRock IM, BlackRock Singapore, T. Rowe IM, T. Rowe Intl). For these, the sub-adviser eid IS within the same top_parent control chain (typically a fully-owned subsidiary), so any 13F filed by the subsidiary already rolls up to the same top_parent — no cross-firm double-count.

Genuine **cross-firm sub-adviser** patterns surface in the 13.8% rollup_type-divergent cohort (Phase 7.2): Strategic Advisers Fidelity Intl sub-advised by T. Rowe Price ($60B), Goldman Sachs GQG Partners sub-advised by GQG ($52B), Bridge Builder Large Cap Growth sub-advised by JPM IM ($28B), Six Circles funds sub-advised by PIMCO/BlackRock IM/PGIM ($60B+ across series). These are the cases where sub-adviser ≠ named adviser ≠ sponsor.

#### 6.2d Sub-adviser handling recommendation for CP-5 read layer

Three options:

| option | description | trade-off |
| --- | --- | --- |
| **A** | Roll into named adviser (current default; matches `economic_control_v1`). Sub-adviser invisible at institutional tier; visible only at fund tier as a `parent_fund_map` annotation. | Default; matches D4 sponsor-precedence. Structural cross-firm double-count when both sub-adviser and named adviser file 13F (GEODE pattern). |
| **B** | Parallel attribution — sub-adviser shows up as institutional-tier holder alongside named adviser. | Inflates aggregate AUM; double-counts at the (sub, named) firm pair. |
| **C** (recommended) | **Hybrid**: primary attribution to named adviser via `economic_control_v1`; sub-adviser exposure surfaced via separate "who manages your money" query/tab keyed off `decision_maker_v1`. | Matches CP-5 two-view model: View 1 institutional ownership (named adviser); separate sub-adviser drill via dm-keyed view. Avoids double-count by NOT summing both in the headline rollup. |

The GEODE 13F vs Fidelity N-PORT cross-firm double-count remains under Option C — it's a separately-files-13F problem, not a sub-adviser-attribution problem. R5 read layer should **document** this (and similar cases for Wellington / DFA / TRP / BlueCove cross-firm subs) as a known cross-firm overlap. A separate dedup pass at the (cusip, ticker) level across top_parents is out of scope for CP-5 (would distort firm-level attribution); the right surface is a "watch list" of known cross-firm overlaps.

---

## 2. Probe 7 — Read/write audit + pipeline contracts

### 7.1 Open Q1 — canonical climb mechanism (RESOLVED)

**Two real candidates exist** (the prior characterization in PR #279 §6.1 hypothesized two but didn't enumerate them):

- **Method A — `entity_rollup_history` JOIN at read time.** `JOIN entity_rollup_history erh ON erh.entity_id = fh.entity_id AND erh.rollup_type='decision_maker_v1' AND erh.valid_to=sentinel`, then climb `inst_to_top_parent` from `erh.rollup_entity_id`. Bundle B ([cp_5_bundle_b_common.py:116-134](../../scripts/oneoff/cp_5_bundle_b_common.py)) and the matrix re-validation helper ([cp_5_coverage_matrix_revalidation.py:138-149](../../scripts/oneoff/cp_5_coverage_matrix_revalidation.py)) both use this.
- **Method B — `fund_holdings_v2.dm_rollup_entity_id` denormalized column read at row time.** Loader populates this column from `entity_rollup_history` snapshot at ingest time; reads bypass the JOIN.

**Empirical reconciliation (top-25, 2025Q4 EC, fund_tier $B):**

| top_parent | name | Method A $B | Method B $B | delta $B |
| ---: | --- | ---: | ---: | ---: |
| 4375 | Vanguard Group | 8,210.2 | 8,210.2 | 0.0 |
| 3241 | BlackRock, Inc. | 484.2 | 484.2 | 0.0 |
| 10443 | Fidelity / FMR | 3,961.9 | 3,961.9 | 0.0 |
| **7984** | **State Street / SSGA** | **807.8** | **1,586.0** | **−778.2** |
| 2 | BlackRock / iShares | 2,924.1 | 2,924.4 | −0.4 |
| 12 | Capital Group / American Funds | 2,820.6 | 2,820.6 | 0.0 |
| 2920 | Morgan Stanley IM | 86.2 | 91.1 | −4.9 |
| (others ≤$5B residual) | | | | |

**Per-fund alignment:** 9,330 / 9,824 (95.0%) active 2025Q4 funds align between methods; **494 (5.0%) diverge.** SSGA carries the bulk of the divergence.

**Root cause.** `fund_holdings_v2.dm_rollup_entity_id` is a **load-time snapshot** from `entity_rollup_history`. After SSGA's recent `entity_rollup_history` re-derivation (likely the cp-4b-author-ssga PR #271 brand-bridge work, 2026-05-03), the live ERH points eid 3 → eid 7984 chain via `decision_maker_v1`. The denormalized column on existing fund_holdings_v2 rows still carries pre-bridge values. **Method A reflects current entity-graph state; Method B becomes stale when ERH is rebuilt without a backfill.**

**The PR #279 §6.1 ±$83B residual is unrelated.** That residual was Bundle B's `r5-validation.csv` `fund_tier_corrected_b` column, which was computed as **`matrix_value / 2`** — an approximation. Since dm and ec rollup_entity_id values diverge for 13.8% of funds (Open Q2), `(sum_dm + sum_ec)/2 ≠ sum_dm`. The Fidelity residual ($83B) ≈ `(sum_ec − sum_dm)/2 = (4,128.3 − 3,961.9)/2 = $83.2B` ✓. So the `±$83B` is a measurement artifact of the /2 approximation, not a climb-mechanism difference.

**Canonical pick — Method A.** Reads the live entity-graph state at query time. Method B is fast but acquires drift after every ERH rebuild. Lock Method A (entity_rollup_history JOIN) as canonical for CP-5.1. Method B has a separate role as a cache invalidation signal: if `dm_rollup_entity_id ≠ Method A result for a row`, the loader's denormalization is stale and the row needs a backfill — surface as a data-quality gate.

### 7.2 Open Q2 — rollup_type divergence handling (RESOLVED)

**Confirmed:** 1,826 of 13,221 funds (13.8%) have `decision_maker_v1.rollup_entity_id ≠ economic_control_v1.rollup_entity_id`. Output: [data/working/cp-5-bundle-c-rollup-type-divergence.csv](../../data/working/cp-5-bundle-c-rollup-type-divergence.csv) (top-50).

**Pattern from inspection of top-20 by AUM:**

| pattern | example (fund — dm — ec) | $B |
| --- | --- | ---: |
| Sub-advised mainstream fund | Strategic Advisers Fidelity Intl — TRP — Fidelity | 60.4 |
| Sub-advised affiliated boutique | Goldman Sachs GQG Partners Intl Opp — GQG — Goldman | 52.4 |
| Multi-manager wrap | Six Circles US Unconstrained — PIMCO — JPM Private Inv | 31.8 |
| Sponsor fund-of-managers | Bridge Builder Large Cap Growth — JPM IM — Olive Street | 28.4 |
| Boutique-affiliated | Old Westbury Large Cap — Sands Capital — Bessemer | 26.2 |

**Semantic interpretation.**

- `decision_maker_v1` = the actual investment decision-maker (sub-adviser when one exists; named adviser otherwise).
- `economic_control_v1` = the fund family / sponsor / registrant umbrella (who owns the fund product).

For ~86% of funds (no sub-adviser, named adviser is the operating AM), dm = ec. For the 14% with sub-advisory arrangements, dm and ec point to different top_parents.

**Canonical rule — recommendation.**

| candidate | meaning | trade-off |
| --- | --- | --- |
| **R7.2a** Always prefer ec | "who owns the fund family" | Aligns with sponsor-name display; mis-attributes investment skill |
| **R7.2b** Always prefer dm | "who makes investment decisions" | Aligns with 13F filer (sub-adviser files 13F when discretion-bearing); MOST consistent with R5 cross-form MAX |
| R7.2c Hybrid | dm where present, ec fallback | Likely current behavior, but ambiguous semantics |

**Recommend R7.2b — `decision_maker_v1` canonical for the institutional rollup view (View 1).**

Reasoning:
1. **R5 self-consistency.** 13F is filed by the *decision-maker* (sub-adviser when discretion-bearing). If fund-tier rolls by dm, 13F and fund-tier point to the same top_parent → R5 MAX dedups within firm cleanly. If fund-tier rolled by ec, fund-tier and 13F would be on different top_parents, R5 wouldn't dedup, and aggregate exposure gets double-counted across firms.
2. **Bundle B already locked dm.** Bundle B's r5-validation, the matrix re-validation, and Bundle A all standardized on `decision_maker_v1`. No code path computes ec for the headline rollup today.
3. **ec retains a separate analytical purpose.** Sponsor-keyed view ("who runs this product family") is a useful drill that should live as a separate view consumable by Fund Portfolio / Conviction tabs. Surface as `View 1b — sponsor view` if/when needed; out of CP-5.1 scope.

### 7.3 securities.canonical_type defect

#### Defect scope

`securities.canonical_type` distribution (totals across all rows):

| canonical_type | rows |
| --- | ---: |
| BOND | 359,287 |
| **COM** | **32,678** |
| OPTION | 20,450 |
| CASH | 6,128 |
| ETF | 5,580 |
| PREF | 1,450 |
| FOREIGN | 1,150 |
| OTHER | 1,097 |
| MUTUAL_FUND | 627 |
| (10 more, ≤610 each) | |

**Inspection of known fund tickers (Bundle A §5 list):** 12 of 21 known fund tickers carry `canonical_type='COM'` instead of MUTUAL_FUND/ETF/CEF. Examples: VSMPX (Vanguard Total Stock Market Inst+, $344B), VGTSX ($254B), VTBIX ($164B), VTSMX ($24B), VTIAX, VTIIX, VTILX, VRTPX, FXAIX (Fidelity 500 Index), FXNAX, FCFMX, FSGEX. Sources are mixed: half are `canonical_type_source='inferred'` (security_type_inferred='equity'), half are `'asset_category'` (whatever derivation that source represents).

**Aggregate blast radius.** At 2025Q4 EC level, fund_holdings_v2 rows joined to `securities.canonical_type='COM' AND issuer_name like %FUND/TRUST/ETF/INDEX/PORTFOLIO%`:

| metric | value |
| --- | ---: |
| n rows | 15,090 |
| distinct cusips | 1,613 |
| AUM $B | **$2,722.2** |

Top mis-classified by AUM: VSMPX $344B, VGTSX $254B, VTBIX $164B, FCFMX $90B, FSGEX $61B, VTILX $61B, FCIPL $44B, TEQWX $33B, RWIGX $33B, etc.

Output: [data/working/cp-5-bundle-c-canonical-type-defect.csv](../../data/working/cp-5-bundle-c-canonical-type-defect.csv).

#### Writers

Authoritative writers (grep `INSERT INTO securities | UPDATE securities` for canonical_type):
- [scripts/normalize_securities.py](../../scripts/normalize_securities.py) — primary classifier (`canonical_type_source='normalize_securities'` / `'inferred'` / `'asset_category'`)
- [scripts/build_cusip.py](../../scripts/build_cusip.py) — initial CUSIP/OpenFIGI ingestion
- [scripts/pipeline/cusip_classifier.py](../../scripts/pipeline/cusip_classifier.py) — runtime classifier helper used by both
- [scripts/migrations/003_cusip_classifications.py](../../scripts/migrations/003_cusip_classifications.py) — initial backfill (one-shot)

**Hypothesis (likely root cause).** OpenFIGI returns `marketSector='Equity'` for fund share classes whose primary asset class is equity (VSMPX, VTSMX, FXAIX). The classifier in `pipeline/cusip_classifier.py` likely keys on `marketSector` only and maps to `'COM'`. The discriminator that would correctly classify them as fund-typed is `securityType2='Mutual Fund'` (or similar), which the classifier doesn't currently consult.

#### Read-side blast radius

Output: [data/working/cp-5-bundle-c-canonical-type-readers.csv](../../data/working/cp-5-bundle-c-canonical-type-readers.csv).

**Read-side blast radius for CP-5: zero user-facing readers.** `grep -rln 'canonical_type\|is_equity\|is_priceable' scripts/api_*.py scripts/queries/ scripts/queries_helpers.py` returns no hits. All consumers are pipeline / classification / validation scripts (`enrich_holdings.py`, `validate_classifications.py`, `build_classifications.py`).

**Where the defect DOES bite:**
1. **Bundle A FoF Pass A** (`canonical_type IN ('ETF','MUTUAL_FUND','CEF')`) misses ~$2.7T of fund share classes at the cusip level — **Bundle A §1.1 Pass B name-match recovers them** (the union covers 187K rows). So the modified-R5 FoF subtraction filter correctly subtracts them via Pass B, even with the defect in place.
2. **Future readers that filter on `canonical_type='COM'` to scope "common stock"** would silently include institutional fund share classes. None exist today; documenting as a forward-compat risk.

#### Remediation recommendation

Loader fix in `pipeline/cusip_classifier.py` (consult `securityType2` / `securityType` alongside `marketSector`) + one-shot backfill of existing `securities` rows. Sized as a **small follow-up PR** (≤200 LOC + 1-day backfill). Not a CP-5 read-layer dependency.

### 7.4 Comprehensive read site audit

> **Scope note (added 2026-05-06 by `cp-5-bundle-c-api-files-extension` PR):** the original §7.4 enumeration scoped `scripts/queries/*` only and did not enumerate `scripts/api_*.py` reader sites. PR #302 (CP-5.4 recon §1.4) and PR #303 (CP-5.4 execute, FPM1 ship list) surfaced this as a real accounting gap. The canonical inventory is now [data/working/cp-5-bundle-c-readers-extended.csv](../../data/working/cp-5-bundle-c-readers-extended.csv) which spans both layers. §7.4a (the original 27 rows) and §7.4-api (the new api_*.py rows) summarise the two halves.

#### 7.4a — 27 reader sites re-confirmed

[Output: data/working/cp-5-bundle-c-readers.csv](../../data/working/cp-5-bundle-c-readers.csv).

Re-grep against `scripts/queries/` (8 files) for `rollup_name | inst_parent_name | rollup_entity_id | dm_rollup` returns 100 hits across the same 8 files (register 27, common 27, trend 13, flows 11, cross 9, entities 6, market 4, fund 3). **No new reader files have landed since cp-5-discovery PR #276.** The 27-row inventory is complete.

#### 7.4b — Per-feature migration scope

Aggregating the 27 sites into the 11 features from cp-5-discovery and sizing per Bundle B / matrix-revalidation findings:

| feature | n sites | current source | target view under R5 | size (S/M/L) |
| --- | ---: | --- | --- | :-: |
| Register top-25 | 7 | holdings_v2 (name-coalesce) | R5 unified + summary_by_parent rebuild | M |
| Cross-Ownership "Top Investors Across Group" | 3 | holdings_v2 + fund_holdings_v2 | R5 unified | M |
| Cross-Ownership "Top Holders by Company" | (in above) | (in above) | R5 unified | S |
| Crowding | 4 | holdings_v2 + ER | R5 distinct(tp_eid) + multi-hop ER | M |
| Smart Money | (shares Crowding readers) | (shares) | (shares) | (shares) |
| Sector Rotation | 1 | holdings_v2 | R5 unified | S |
| New / Exits (Flows entry+peer cohorts) | 2 | holdings_v2 | R5 deltas | M |
| Conviction (portfolio_context + flows) | 4 | holdings_v2 + fund_holdings_v2 + manager_aum | R5 + View 2 + manager_type imputation | L |
| Trend | 3 | holdings_v2 + parent_fund_map + shares_history | R5 + View 2 template + shares_history rebuild | M-L |
| AUM (manager_aum joins) | (in Register query16) | manager_aum + holdings_v2 | R5 unified | S |
| Activist (cross-cutting; flows + register) | (in Flows + Register) | holdings_v2 | R5 unified | S |
| Entity Drilldown | 3 | ER walk + holdings_v2 | Multi-hop ER + R5 unified | M-L |
| NPORT bridge / common helpers | 3 | fund_holdings_v2 (REGEX NAME) + ER | RETIRE; replace w/ entity-keyed lookup | L |

Distribution: **L 4, M 12, S 11.** No feature is sized as XL — the rebuild is large but bounded.

#### 7.4-api — `scripts/api_*.py` reader sites

> Added 2026-05-06 by `cp-5-bundle-c-api-files-extension` PR. The original 27-row §7.4a enumeration scoped `scripts/queries/*` only. This sub-section enumerates the api-layer sites that PR #302 (CP-5.4 recon §1.4) and PR #303 (CP-5.4 execute) surfaced as missed.

Canonical inventory: [data/working/cp-5-bundle-c-readers-extended.csv](../../data/working/cp-5-bundle-c-readers-extended.csv) (rows where `file` starts with `scripts/api_`).

Greps run:

```
grep -rn "rollup_name|inst_parent_name|rollup_entity_id|dm_rollup|dm_entity_id"
  scripts/api_*.py
grep -rn "top_parent_canonical_name_sql|top_parent_holdings_join"
  scripts/api_*.py
grep -rn "holdings_v2|fund_holdings_v2|entity_current|summary_by_parent|shares_history|manager_aum|entity_relationships"
  scripts/api_*.py
grep -rn "COALESCE|rollup_name|manager_name"
  scripts/api_*.py    # zero hits — verifies migrated state
```

Result: **37 api-layer rows** across 8 files, classified as:

| migration_status | n rows | meaning |
| --- | ---: | --- |
| MIGRATED | 2 | `api_fund_portfolio_managers` (FPM1, #303), `api_crowding` (C2, #303). Both call `top_parent_canonical_name_sql('h')`. |
| N/A_NO_ROLLUP_PATTERN | 6 | Endpoints that read `holdings_v2` / `fund_holdings_v2` / `market_data` without a parent-display COALESCE: `api_tickers` autocomplete, `api_smart_money` longs (SM1) + nport_shorts (SM2), `validate_ticker_current` sentinel, `api_peer_tickers` (market_data only), `api_fund_quarter_completeness`. |
| DELEGATING_WRAPPER | 26 | Thin endpoint wrappers that delegate to `queries.*` functions (`api_cross.py`, `api_flows.py`, most of `api_market.py`, `api_entities.py`). These inherit migration status from their upstream `scripts/queries/*` row — no separate api-layer migration site. |
| DISPATCH_UTILITY | 3 | `api_register.py` `_execute_query` / `api_query` / `api_export` — generic dispatchers over `QUERY_FUNCTIONS`; not a reader path. |

Per-feature breakdown (api-layer only):

| feature | sites | notes |
| --- | ---: | --- |
| Crowding | 1 (MIGRATED) | `api_market.py` `api_crowding` — uses `top_parent_canonical_name_sql('h')`. |
| Smart Money | 2 (N/A) | `api_market.py` longs + N-PORT shorts — neither carries the rollup pattern (CP-5.4 §1.3 verified). |
| Fund Portfolio Managers | 1 (MIGRATED) | `api_fund.py` `api_fund_portfolio_managers` — FPM1 from CP-5.4 §1.4, originally adjacent-out-of-Bundle-C-scope. |
| Register Tickers autocomplete | 1 (N/A) | `api_register.py` `api_tickers` — pure ticker enumerator, no parent display. |
| Cross-Ownership | 5 (DELEGATING_WRAPPER) | All `api_cross.py` endpoints inherit from `scripts/queries/cross.py` (CP-5.3 #301 ship list). |
| Flows / Trend / Conviction | 7 (DELEGATING_WRAPPER) | `api_flows.py` endpoints inherit from `scripts/queries/{flows,trend,fund}.py`. |
| Sector Rotation / Sector flows | 6 (DELEGATING_WRAPPER) | `api_market.py` sector_* endpoints inherit from `scripts/queries/market.py` (PENDING_CP5_5). |
| Entity graph / hierarchy | 5 (DELEGATING_WRAPPER) | `api_entities.py` endpoints inherit from `scripts/queries/entities.py` and `queries/market.py:1040-1130` (PENDING_CP5_6). |
| Short Interest / FINRA / completeness / peer_tickers / dispatch | 10 (DELEGATING_WRAPPER + N/A + DISPATCH_UTILITY mix) | Utility / Crowding-adjacent / dispatcher rows; no separate migration target. |

**Bottom line:** The 2 MIGRATED rows (FPM1, /crowding) capture the entire api-layer rollup-pattern surface; both shipped in PR #303. The 26 DELEGATING_WRAPPER rows do not introduce new reader sites — they will pick up parent-display migration transitively as their upstream `scripts/queries/*` row migrates. CP-5.5 + CP-5.6 recons should reference the extended inventory as canonical and skip re-discovering the api layer.

#### 7.4c — Comprehensive write site inventory

Output: [data/working/cp-5-bundle-c-writers.csv](../../data/working/cp-5-bundle-c-writers.csv) (64 writer rows across 10 critical CP-5 tables).

**Writer counts per critical table (production code only; oneoffs excluded):**

| table | n writer×op rows |
| --- | ---: |
| `entity_rollup_history` | 11 |
| `entity_classification_history` | 10 |
| `entity_aliases` | 8 |
| `securities` | 7 |
| `entities` | 6 |
| `entity_identifiers` | 6 |
| `fund_holdings_v2` | 5 |
| `entity_relationships` | 4 |
| `holdings_v2` | 4 |
| `fund_universe` | 3 |

**Top writer files** (total write-site count across the 10 critical tables):

| writer | n write sites |
| --- | ---: |
| `scripts/build_entities.py` | 15 |
| `scripts/entity_sync.py` | 13 |
| `scripts/admin_bp.py` | 6 |
| `scripts/resolve_13dg_filers.py` | 6 |
| `scripts/pipeline/load_nport.py` | 6 |
| `scripts/bootstrap_etf_advisers.py` | 6 |
| `scripts/bootstrap_residual_advisers.py` | 6 |
| `scripts/bootstrap_tier_c_advisers.py` | 6 |
| `scripts/build_managers.py` | 4 |
| `scripts/enrich_holdings.py` | 3 |
| `scripts/normalize_securities.py` | 2 |
| `scripts/enrich_tickers.py` | 2 |
| `scripts/build_fund_classes.py` | 2 |
| `scripts/approve_overrides.py` | 2 |
| `scripts/resolve_pending_series.py` | 2 |

**Notable patterns:**
- `build_entities.py` is the canonical entity-graph builder; owns the largest share of writes across `entities`, `entity_aliases`, `entity_identifiers`, `entity_relationships`, `entity_classification_history`, `entity_rollup_history`.
- `entity_sync.py` owns the staging→prod sync layer. Per memory, this is the **standard workflow since Apr 10** for entity changes.
- Three `bootstrap_*_advisers.py` scripts each write to ECH + ERH for separate adviser cohorts (ETF, residual, Tier C). They are one-shot bootstrap scripts but still ship in production code; check whether they should retire post-bootstrap.
- `admin_bp.py` writes ECH + ERH from the UI override flow. Path is gated by `approve_overrides.py` per memory's INF1 workflow.
- `pipeline/load_nport.py` writes to `fund_universe` + `fund_holdings_v2` + `entity_rollup_history` via load.
- **`fund_holdings_v2.entity_id` is populated by load_nport.py at ingest** — this is the upstream of Bundle B Phase 2.4's 84,363-row gap (entity_id IS NULL at load-time → rollup builder can't resolve). Recovery requires (a) post-load entity-link enrichment for known CIKs, (b) new fund-typed entity creation for unknown CIKs.

### 7.5 Pipeline source-of-truth contracts

Pipelines per memory [project_session_apr15_dera_promote.md](../../memory) + repo inspection:

| pipeline | code | owns (writes) | consumes (reads) | frozen-by-default? |
| --- | --- | --- | --- | --- |
| **P0** 13F ingestion (legacy v1) | `scripts/load_13f.py` (RETIRED post Apr 23 cutover) | n/a (cutover) | — | n/a |
| **P0v2** 13F ingestion (active) | `scripts/load_13f_v2.py` | `holdings_v2` (rows + manager_type), `securities` (cusip backfill) | `entities`, `entity_identifiers` for filer resolve | YES — does not overwrite ECH/ERH for existing entities |
| **P1** 13D/G beneficial ownership | `scripts/load_13dg.py` + `enrich_13dg.py` + `resolve_13dg_filers.py` + `reparse_13d.py` | `holdings_13dg` (table), `entities` (filer create), `entity_identifiers`, `entity_rollup_history` | securities, name-norm | YES with explicit override paths |
| **P2** N-CEN identity join | `scripts/pipeline/load_ncen.py` | `ncen_adviser_map`, `fund_classes` | `entities`, `entity_identifiers` | YES — append-only SCD on ncen_adviser_map |
| **P3** Unified position table | n/a yet | (CP-5.2 will own this — R5 view) | `holdings_v2`, `fund_holdings_v2`, `entity_rollup_history` | YES (read-only) |
| **P4** Monthly N-PORT | `scripts/pipeline/load_nport.py` (NPORT-P only) | `fund_holdings_v2`, `fund_universe`, `entity_rollup_history` (per-series rollups) | `entities`, `ncen_adviser_map`, `securities` | PARTIAL — overwrites `fund_strategy` on bare-NULL only; preserves prior classifier when set (per code comments at `:1063-1073`) |
| **P5** Share class | not built; fund_classes table exists from N-CEN (P2) | (would need fund_classes drilldown) | fund_classes, fund_universe | n/a |
| **P6** Peer group table | `scripts/compute_peer_rotation.py` | `peer_rotation_*` tables | holdings_v2, entity_rollup_history | YES |
| **P7** LEI standardization | not built (Bundle B §3.1: 0% LEI coverage) | — | — | n/a |
| **Admin Refresh System** | `scripts/scheduler.py` + `scripts/admin_bp.py` | scheduling state + override edits to ECH/ERH | all | hooks via approve_overrides.py |
| **Entity merge / brand-bridge** | `scripts/build_entities.py` + `scripts/oneoff/cp_4b_*` | `entity_relationships` (control_type='control'/'merge'/'advisory'), aliases, identifiers, rollups | full entity graph | YES with explicit author rows + closure |
| **Bootstrap residual advisers** | `bootstrap_etf_advisers.py` + `bootstrap_residual_advisers.py` + `bootstrap_tier_c_advisers.py` | `entities` (residual creation) + ECH/ERH | securities/cusip seeds | one-shot per cohort |
| **Securities normalization** | `normalize_securities.py` + `build_cusip.py` + `pipeline/cusip_classifier.py` | `securities` (canonical_type / sector / industry) | OpenFIGI / asset_category | per-CUSIP append; **defect 7.3 lives here** |
| **Holdings enrichment** | `enrich_holdings.py` + `enrich_fund_holdings_v2.py` | per-row sector/industry/manager_type backfill on holdings_v2 / fund_holdings_v2 | securities | post-load enrichment |

#### Contract-hardening gaps

1. **fund_holdings_v2 entity_id load-time linking gap (84K rows / $418B; Bundle B §2.4).** P4 writes `entity_id IS NULL` for ~76 fund_ciks where the registrant CIK lacks an entity in the entity layer. Two recovery paths: (a) post-load CIK→entity linker + Phase-3 rollup re-run for 23/50 already-linkable; (b) new fund entity creation pass for 27/50 unknowns + Phase-3.
2. **`fund_holdings_v2.dm_rollup_entity_id` denormalization staleness (Phase 7.1).** SSGA-class drift after each ERH rebuild. Either (a) backfill the denorm column after every ERH rebuild (loader contract), or (b) drop the column and rely on Method-A JOIN (read-side cost).
3. **`securities.canonical_type` mis-classification on fund share classes (Phase 7.3).** Loader fix + one-shot backfill — ~$2.7T affected by name; zero user-facing reader blast today; harmful only to Bundle A FoF Pass A which is already covered by Pass B.
4. **`bootstrap_*_advisers.py` (3 scripts) ship in production code but are one-shot bootstrap.** Either (a) retire post-bootstrap; (b) gate behind a feature flag; (c) document as deprecated. Currently 18 write sites across the 3 add to write-surface count without active use.
5. **No M&A event capture in `entity_relationships.valid_from`** (Bundle B §4.3, §4.4). 378 of 395 control rows have default `valid_from=2000-01-01`. Option C (hybrid) recommended; not blocking CP-5 (today's data is 2025Q1+).
6. **LEI ingestion absent (Bundle B §3.1).** 0% LEI coverage. Pipeline P7 stub. Pipeline-side gap; not blocking CP-5.
7. **`entity_relationships.is_inferred` flag underused.** Reserved column on the table; only 1 of 2 'merge' rows uses it. Schema is in place; populate convention not enforced. Adds noise to inferred-vs-authored audit.

---

## 3. Probe 8 — View 2 fund-tier coverage

### 8.1 Non-N-PORT cohort breakdown

[Output: data/working/cp-5-bundle-c-view2-coverage.csv](../../data/working/cp-5-bundle-c-view2-coverage.csv).

**ALL 13F filers WITHOUT a fund-tier rollup link** (2025Q4 is_latest, joined to fund_holdings_v2 on `rollup_entity_id` and selecting where no link exists):

| manager_type | n_filers | aum_b |
| --- | ---: | ---: |
| mixed | 1,519 | 12,272.8 |
| active | 4,594 | 11,867.0 |
| passive | 42 | 10,473.5 |
| quantitative | 70 | 4,106.2 |
| hedge_fund | 970 | 2,302.6 |
| wealth_management | 347 | 2,259.2 |
| pension_insurance | 131 | 1,755.3 |
| strategic | 457 | 510.2 |
| private_equity | 101 | 320.3 |
| endowment_foundation | 60 | 185.9 |
| SWF | 13 | 142.8 |
| activist | 19 | 90.6 |
| family_office | 47 | 20.1 |
| venture_capital | 26 | 8.0 |

Total: $46.3T 13F AUM with no fund-tier link. (Larger than Bundle A's $8T figure because this counts ALL 13F filers without a rollup_entity_id link, including major top-parents like JPM Chase 4433, BoA 8424, etc., that genuinely have no fund-tier counterparty by structure.)

**Sub-cohort restricted to "no PM decomposition possible by structure"** (hedge_fund + SMA-style + pension_insurance + family_office + endowment_foundation + SWF + activist + venture_capital): **$4.9T 13F AUM / 1,367 filers.** This matches the Bundle A §5 estimate ($8T was a Phase 5 estimate including an over-counted manager_type cohort; Bundle C corrects to $4.9T using the corrected matrix and the actual link gap).

The `mixed`, `active`, `passive`, `quantitative`, `wealth_management`, `private_equity`, `strategic` buckets are not all "structurally non-decomposable" — many of these ARE registered fund advisers whose fund-tier rollup hasn't yet been linked (Bundle B §2.4 84K-row gap, plus the broader long tail of unbridged cohorts).

### 8.2 Alternative source assessment

| cohort | source | status |
| --- | --- | --- |
| Hedge funds (970 filers / $2.30T) | 13F-D (hedged) when filed | `holdings_v2` has no `filing_type` column — 13F-HR vs 13F-D not distinguishable in current loader. Pipeline-1 (13D/G) backlog item, not part of CP-5. |
| SMAs | Form ADV Schedule D (aggregate AUM only) | Not position-level. Out of scope. |
| Pensions ($1.76T) | Public pension policy reports / meeting minutes | Manual sourcing, out of scope. |
| Family offices ($20M) | 13F single-entity | Already in 13F. No further decomposition. |
| Sovereign wealth ($143B) | 13F single-entity | Already in 13F. No further decomposition. |

### 8.3 View 2 design recommendation

**Lock the following View 2 scope in conv-29 before any execution PR:**

- **Tier 1 (already exists)** — N-PORT-filing registered funds: 1,954 funds / $31.6T EC. Existing Fund Portfolio + portfolio_context readers, with entity-keyed integration to the new top-parent rollup (CP-5.6).
- **Tier 2 (incremental)** — 13D/G partial holdings for >5% positions on non-N-PORT filers. Pipeline P1 already partially loads. Surface as "PM partial" with explicit coverage caveat. Out of CP-5.1 scope; can ride CP-5.6.
- **Tier 3 (structural gap)** — hedge / SMA / pension / family / SWF: $4.9T no-decomposition cohort. Display as institutional-tier with explicit "no fund decomposition available" flag. **Document; do NOT scope as a CP-5 deliverable.**

cp-5-discovery §5 already locked this scope; Bundle C confirms cohort sizing and recommends MINIMAL incremental work for View 2 — the entity-keyed integration with the new top-parent rollup, plus the Tier 3 surfacing.

---

## 4. Pre-execution dependency consolidation (handoff to Bundle D)

These items should land **before** CP-5.1 read-layer-foundation ships. Each is independently scoped.

| # | item | source | size | sequencing |
| - | --- | --- | --- | --- |
| 4.1 | 21 cycle-truncated entity merges (~10-11 merge candidates: Goldman 22+17941, Lazard 58+18070, Lord Abbett 893+17916, Ariel 70+18357, Sarofim 858+18029, Thornburg 2925+18537, Lewell, Equitable, Stonebridge, Financial Partners, etc.) | Bundle B §2.2 | M (one PR cohort) | **before CP-5.1** — `build_top_parent_join()` will misroute holdings under duplicate eid until merged |
| 4.2 | 84K loader-gap rows: 23 linkable + 27 new entities | Bundle B §2.4 | M (split into 2 sub-PRs by recovery type) | **before CP-5.1** for material AUM coverage; can also slip to CP-5.5 |
| 4.3 | Capital Group umbrella decision (3-filer-arm carve-out vs synthetic AMC parent) | Bundle B §1.3 | S (1 PR with 3 ER rows) | before CP-5.1 (matches cp-4b precedent) |
| 4.4 | Adams Asset Advisors duplicates (eid 4909+19509 merge candidate) | Bundle B §3.3 | XS (1 merge PR) | trivial; bundle with 4.1 cohort |
| 4.5 | securities.canonical_type fix on fund share classes | Bundle C §7.3 | S (loader patch + one-shot backfill) | **post CP-5** OK — zero user-facing reader blast today; ride alongside CP-5.6 |
| 4.6 | Operating-AM rollup policy violations (BoA 8424, RBC 7440, BNY 1401, Manulife 8994: $2.78T 13F + $148B fund-tier) | Bundle B §2.5 | M (per-firm OR cohort PR) | post CP-5 — affects display, not query correctness |
| 4.7 | Cross-period CIK reconciliation (16 non-obvious pairs) | Bundle B §3.2 | S (per-pair triage) | post CP-5 |
| 4.8 | M&A event register (Option C valid_from overrides) | Bundle B §4.4 | L (data-collection + migrations) | post CP-5; only relevant when 10+ year load is scoped |
| 4.9 | LEI ingestion (0% coverage today) | Bundle B §3.1 | M (pipeline P7) | backlog; not blocking |

---

## 5. Open questions for Bundle D synthesis

1. **R7.2 canonical rollup_type lock.** Recommend `decision_maker_v1`; chat to confirm before CP-5.1 helper authoring.
2. **Method A vs Method B for fund-tier climb (Phase 7.1).** Recommend Method A (read-time ERH JOIN) canonical. Decide whether to retain `fh.dm_rollup_entity_id` denormalized column as a (a) cache w/ refresh contract, (b) cache invalidation signal only, (c) drop entirely.
3. **Sub-adviser handling Option C lock.** Recommend hybrid (named adviser primary via ec; sub-adviser secondary view via dm). Confirm.
4. **GEODE-pattern cross-firm 13F/N-PORT double-count surfacing.** Document as known limitation in CP-5 read layer? Build a watch-list query? Out-of-scope for R5 fix?
5. **Capital Group carve-out shape.** 3 separate `control` ER rows from each filer arm to brand eid 12, OR single synthetic AMC parent that all 4 eids point to? cp-4b precedent (T.Rowe / FMR / SSGA / First Trust) used per-arm separate rows; recommend same.
6. **`canonical_type` defect remediation timing.** Pre- or post-CP-5? Recommend post (no user-facing read filters on it today).
7. **summary_by_parent rebuild approach.** New entity-keyed table alongside the legacy NAME-keyed one (cutover later), or in-place rebuild with downtime window?
8. **bootstrap_*_advisers.py disposition.** Retire / gate / leave-as-is?

---

## 6. Out-of-scope discoveries / surprises

- **`fund_holdings_v2.dm_rollup_entity_id` is a load-time-frozen denormalization** that drifts after each ERH rebuild. The 5% per-fund divergence between Method A and Method B isn't a uniform 5% error — it concentrates on entities with recent ERH rebuilds (SSGA after PR #271 brand-bridge work; ~$778B fund-tier gap on a single firm). Surface as a cache-invalidation signal: rows where `dm_rollup_entity_id ≠ Method A` need a backfill.
- **No user-facing reader filters on `securities.canonical_type` / `is_equity` / `is_priceable`.** The 1,613-cusip / $2.7T mis-classification defect is invisible to the read layer today. Forward-compat risk only.
- **GEODE eid 7859 carries $1.62T 13F as a sub-adviser** because as discretion-bearing sub-adviser of Fidelity index funds, it crosses the 13F threshold and files its own 13F. Same equity slice routes to Fidelity (eid 10443) at the N-PORT side. Cross-firm 13F/N-PORT exposure for the shared slice is **not handled by R5** (which only dedups within a single top_parent). This pattern exists for ~5-10 cross-firm sub-adviser pairs (BlueCove / Wellington / DFA Ltd / TRP / FIAM / etc.).
- **`fund_classes` table exists** (31,056 rows from N-CEN) but carries no per-class holdings or AUM. Share-class identity is recoverable; per-class portfolio decomposition is not. Documents share-class scope as out-of-CP-5.
- **`scripts/queries/common.py` carries 27 hits on rollup keys** — the largest concentration after register.py. The NPORT family-bridge regex pattern in common.py:258-380 is the highest-leverage retirement target under R5 (replaces the most fragile bridging logic).
- **`bootstrap_*_advisers.py` (3 scripts) hold 18 write sites total but are one-shot bootstrap.** Adds noise to the writer audit; recommend retire-or-gate.

---

## 7. Bundle C status — handoff to Bundle D synthesis

**Bundle C complete.** Read-only investigation only; zero DB writes.

**Material findings:**
- **Phase 6.1:** share-class decomposition is structural (N-PORT-P series-level only); not a CP-5 dependency.
- **Phase 6.2:** GEODE pattern surfaced — sub-adviser cross-firm 13F/N-PORT double-count not handled by R5; document as known limitation. Top-20 sub-adviser cohort is mostly affiliated regional arms.
- **Phase 7.1:** Open Q1 RESOLVED. Method A (read-time ERH JOIN) canonical. Method B (denormalized column) becomes stale after ERH rebuilds; SSGA $778B gap is the live evidence.
- **Phase 7.2:** Open Q2 RESOLVED. `decision_maker_v1` canonical for R5 self-consistency with 13F filer attribution. ec retains separate sponsor-view role.
- **Phase 7.3:** securities.canonical_type defect quantified ($2.7T / 1,613 cusips). Zero user-facing reader blast — defect lives in classification pipeline.
- **Phase 7.4:** 27 reader sites re-confirmed; 64 writer sites mapped across 10 critical CP-5 tables. Top writer files: build_entities.py, entity_sync.py, admin_bp.py, 4 bootstrap scripts.
- **Phase 7.5:** Pipeline contracts mapped (P0v2-P7 + admin/merge/bootstrap). 7 contract-hardening gaps surfaced — most are post-CP-5 follow-ups.
- **Phase 8:** View 2 cohort sized at $4.9T structurally non-decomposable + larger long tail of un-linked rollups; recommend Tier-3 "no decomposition" surfacing only.

**Bundle D synthesis input is complete.** Bundle D should integrate Bundles A + B + C + revalidation into the canonical CP-5 remediation plan with pre-execution work (4.1-4.4 above), design contracts, PR sequence, and dependency graph. Then conv-29-doc-sync captures all CP-5 sub-decisions before any execution PR runs.
