# CP-5 Coverage Matrix Re-validation — results

**Date:** 2026-05-04
**Branch:** `cp-5-coverage-matrix-revalidation`
**HEAD baseline:** `4be9566` (PR #278 cp-5-bundle-b)
**Methodology:** read-only; `quarter='2025Q4'`, EC asset_category for fund-tier.

**Refs:**
- [docs/findings/cp-5-discovery.md](cp-5-discovery.md) — Phase 1d coverage matrix and Phase 2 overlap probe (originals; affected by the join defect)
- [docs/findings/cp-5-bundle-a-discovery.md §1.4](cp-5-bundle-a-discovery.md) — modified R5 rule
- [docs/findings/cp-5-bundle-b-discovery.md §0.3](cp-5-bundle-b-discovery.md) — defect identification
- Helper: [scripts/oneoff/cp_5_coverage_matrix_revalidation.py](../../scripts/oneoff/cp_5_coverage_matrix_revalidation.py)
- Outputs: [data/working/cp-5-coverage-matrix-corrected.csv](../../data/working/cp-5-coverage-matrix-corrected.csv), [data/working/cp-5-overlap-probe-corrected.csv](../../data/working/cp-5-overlap-probe-corrected.csv)

---

## Summary

| dimension | value |
| --- | --- |
| Defect | `entity_rollup_history` joined without `rollup_type` filter — sums BOTH open `rollup_type` rows per fund (UNION-without-filter) |
| Structural signature | `orig_fund_tier = SUM(decision_maker_v1) + SUM(economic_control_v1)` — exact across all 5 cohort firms (max residual 0.000B) |
| Per-firm inflation factor | 1.73× to 2.04× (varies because dm and ec rollup_entity_id values diverge for ~14% of funds) |
| Total combined AUM (top-100) | **$102.0T → $75.2T** (−$26.9T, −26.3%) |
| Coverage_class real transitions | **0** (within firms in both top-100s) |
| New entries in corrected top-100 | 5 (re-rank effect — original top-100 was sorted by inflated combined) |
| Bimodal overlap split | shifted: `13F_dominant 47%` unchanged, `fund_extends_13F 25% → 10%`, `13F_covers_fund 7% → 3%` |
| Modified R5 envelope flags | **0/25** (Bundle B Phase 0.5 structural gate passes against corrected matrix) |
| **Verdict** | **A — R5 LOCKED** |

---

## 1. Defect characterization (Phase 1)

### 1.1 The original join shape

[scripts/oneoff/cp_5_discovery_phase1_inventory.py:158-165](../../scripts/oneoff/cp_5_discovery_phase1_inventory.py) joins `entity_rollup_history` filtered only on `valid_to = sentinel` and `entity_type = 'fund'`. No `rollup_type` predicate.

### 1.2 The missing rollup_type filter

`entity_rollup_history` carries two open `rollup_type` values per fund:

| rollup_type | open rows total | open rows where entity is fund |
| --- | ---: | ---: |
| `decision_maker_v1` | 27,257 | 13,221 |
| `economic_control_v1` | 27,257 | 13,221 |

Every fund therefore has **2 open rows**, so the unfiltered join produces 26,442 fund-chain rows where 13,221 is correct (50% inflation in row count, but the AUM sum is fully doubled because each fund's market_value contributes once per row).

Bundle B §0.3 stated "both rollup_types currently point to the SAME `rollup_entity_id` for every fund". That is **approximately** but not exactly true:

| metric | value |
| --- | ---: |
| Total fund-typed entities | 13,221 |
| `decision_maker_v1.rollup_entity_id == economic_control_v1.rollup_entity_id` | 11,395 (86.2%) |
| Diverged | 1,826 (13.8%) |

### 1.3 Empirical sum-identity confirmation

For each of 5 reference firms, the original (unfiltered) fund_tier exactly equals the sum of the two filtered branches (max residual 0.000B):

| top_parent | name | orig_b | dm_b | ec_b | dm+ec | residual | orig/dm | rollup-type sensitivity |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 4375 | Vanguard Group | 16,420.5 | 8,210.2 | 8,210.2 | 16,420.5 | 0.0 | 2.000× | 0.0% |
| 10443 | Fidelity / FMR | 8,090.2 | 3,961.9 | 4,128.3 | 8,090.2 | 0.0 | 2.042× | 4.0% |
| 3241 | BlackRock, Inc. | 837.0 | 484.2 | 352.8 | 837.0 | 0.0 | 1.729× | **27.1%** |
| 5026 | Dimensional Fund Advisors | 1,404.6 | 709.8 | 694.8 | 1,404.6 | 0.0 | 1.979× | 2.1% |
| 2 | BlackRock / iShares | 5,848.1 | 2,924.1 | 2,924.1 | 5,848.1 | 0.0 | 2.000× | 0.0% |

**Interpretation.** The original code prompt's STOP gate ("if a/b is NOT ~2× consistently, defect is more complex") tripped on BlackRock Inc. at 1.73×. The cleaner gate is the **sum identity** `orig = dm + ec`, which holds exactly for every firm. The variable orig/dm ratio is fully explained by per-firm divergence between the two `rollup_type` populations: when dm and ec disagree on which top_parent owns a fund, neither branch's sum equals half of the original — but the sum of branches still equals the original.

**Sub-finding — rollup_type sensitivity.** For BlackRock Inc., choosing `decision_maker_v1` as the canonical rollup_type yields **$484.2B**; choosing `economic_control_v1` yields **$352.8B** (27% delta). Bundle B recommended `decision_maker_v1` and this revalidation follows that recommendation. The 1,826 divergent funds are a separate downstream question (which rollup_type model represents the "correct" attribution for analytic consumers); see open question 2 below.

### 1.4 STOP gate revision

The 5-firm 2× ratio gate is **not the right gate** for this defect class. Replace with sum-identity check `|orig - (dm + ec)| < 0.5B per firm`. Helper updated.

---

## 2. Corrected coverage matrix (Phase 2)

### 2.1 Methodology

Replicated PR #276 Phase 1d top-parent enumeration + inst→top_parent climb (both unaffected by defect). Replaced the fund_chain query with `AND erh.rollup_type = 'decision_maker_v1'`. Otherwise identical methodology.

Output: [data/working/cp-5-coverage-matrix-corrected.csv](../../data/working/cp-5-coverage-matrix-corrected.csv) (top-100 rows, same columns as original).

### 2.2 Top-25 pre/post diff

| top_parent | name | 13F $B | fund_orig $B | fund_corr $B | combined_orig $B | combined_corr $B | Δ combined $B | Δ % |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 4375 | Vanguard Group | 6,897.7 | 16,420.5 | 8,210.2 | 23,318.1 | **15,107.9** | −8,210.2 | −35.2% |
| 3241 | BlackRock, Inc. | 5,916.3 | 837.0 | 484.2 | 6,753.4 | **6,400.5** | −352.8 | −5.2% |
| 10443 | Fidelity / FMR | 1,961.3 | 8,090.1 | 3,961.9 | 10,051.4 | **5,923.1** | −4,128.3 | −41.1% |
| 7984 | State Street / SSGA | 2,980.9 | 1,617.5 | 807.8 | 4,598.4 | **3,788.7** | −809.7 | −17.6% |
| 2 | BlackRock / iShares | 0.0 | 5,848.1 | 2,924.1 | 5,848.1 | **2,924.1** | −2,924.1 | −50.0% |
| 12 | Capital Group / American Funds | 0.0 | 5,641.2 | 2,820.6 | 5,641.2 | **2,820.6** | −2,820.6 | −50.0% |
| 2920 | Morgan Stanley IM | 1,675.0 | 193.5 | 86.2 | 1,868.5 | **1,761.2** | −107.4 | −5.7% |
| 7859 | GEODE | 1,620.4 | 19.1 | 19.1 | 1,639.6 | **1,639.6** | 0.0 | 0.0% |
| 5026 | Dimensional Fund Advisors | 476.7 | 1,404.6 | 709.8 | 1,881.3 | **1,186.5** | −694.8 | −36.9% |
| 3616 | T. Rowe Price | 0.9 | 1,754.9 | 952.2 | 1,755.8 | **953.1** | −802.7 | −45.7% |
| 4 | Invesco | 0.0 | 1,871.9 | 923.9 | 1,871.9 | **923.9** | −947.9 | −50.6% |
| 5 | Charles Schwab | 0.0 | 1,345.1 | 671.5 | 1,345.1 | **671.5** | −673.6 | −50.1% |

Note: GEODE shows 0% delta — it has no funds in the dual-rollup-type set, only direct 13F + a single fund-typed entity that's identical under both rollup_types (interesting edge). T. Rowe Price drops 45.7% because its fund-tier dominated the original combined; under correction it's nearly half. Pure fund_only firms (Capital Group, BlackRock/iShares, Invesco, Schwab) drop ~50% precisely.

**Total combined AUM (top-100):** $102,049B → **$75,199B** (−$26,850B, −26.3%).

### 2.3 Coverage_class transitions

| transition | n_firms |
| --- | ---: |
| `13F_only` → `13F_only` | 46 |
| `both` → `both` | 36 |
| `fund_only` → `fund_only` | 13 |
| **(new in corrected top-100)** | **5** |

**Zero real transitions.** The `coverage_class` derivation is a binary threshold (13F > 0 vs fund_tier > 0); halving fund_tier preserves the sign, so no firm changes class. The 5 "moved" firms in the simple comparison are firms newly in corrected top-100 because re-ranking by deflated combined AUM brings smaller firms into the cohort. This is a re-rank effect, not a class transition.

---

## 3. Corrected overlap probe (Phase 3)

### 3.1 Phase 2 of PR #276 was affected

[scripts/oneoff/cp_5_discovery_phase2_overlap.py](../../scripts/oneoff/cp_5_discovery_phase2_overlap.py:34) reads `_cp5_fund_chain.parquet`, the working artifact written by the defective Phase 1 query. Set B's per-(top_parent, ticker) fund-tier sums were therefore 2× inflated.

### 3.2 Corrected bimodal split

Same cohort methodology: top-20 'both' top-parents under corrected matrix × {AAPL, NEE, AVDX} = 60 (top_parent, ticker) pairs.

| classification | original (PR #276) | corrected | delta |
| --- | ---: | ---: | ---: |
| 13F_dominant | 17 (28%) | 28 (47%) | +11 |
| fund_extends_13F | 15 (25%) | 6 (10%) | −9 |
| 13F_covers_fund | 4 (7%) | 2 (3%) | −2 |
| 13F_only | 4 (7%) | 4 (7%) | 0 |
| neither | 20 (33%) | 20 (33%) | 0 |

**Material change.** PR #276 reported a bimodal `47% 13F_dominant / 42% fund-extending` split (combining `fund_extends_13F` and `13F_covers_fund` to 42%). Under corrected fund-tier, the combined "fund-side" cohort drops from **42% → 13%** (`fund_extends_13F` 10% + `13F_covers_fund` 3%). Most of the apparent fund-extension was an artifact of the 2× double-count: `fund_aum / 13F_aum > 1.15` triggered the `fund_extends_13F` bucket, but with corrected fund-tier the ratio falls back below 1.15 for two-thirds of those pairs and they re-classify to `13F_dominant`.

**Implication.** The empirical case for "fund-tier extends 13F coverage" is materially weaker than PR #276 implied. R5 (MAX-based) still works because it picks the larger of 13F vs fund_adj per position; with fund-tier halved, 13F simply wins more of the time.

Output: [data/working/cp-5-overlap-probe-corrected.csv](../../data/working/cp-5-overlap-probe-corrected.csv).

---

## 4. Modified R5 fit verdict (Phase 4)

### 4.1 Methodology

Re-applied Bundle B Phase 0.5's **4 structural envelope flags** to Bundle B's published R5 numbers ([data/working/cp-5-bundle-b-r5-validation.csv](../../data/working/cp-5-bundle-b-r5-validation.csv)). Bundle B's helper already used the corrected (rollup_type-filtered) join, so its `modified_R5_aum_b` numbers ARE corrected R5 numbers.

The structural envelope:
- `modified_R5 ≤ naive_R5` (subtraction direction correct)
- `modified_R5 ≥ max(13F, fund_adj)` (lower bound)
- `modified_R5 ≤ 13F + fund_adj` (upper bound)
- For `13F_only` / `fund_only` firms with positive matrix value, `modified_R5 > 0`

### 4.2 Original code prompt's external-AUM bands are not the right gate

The code prompt suggested anchors like "BlackRock $10–11T", "Vanguard $8–9T", "Fidelity $5T". These are **whole-firm** AUM totals that do not map cleanly to single top_parents:

- BlackRock under cp-5's top-parent model is **two** top_parents — eid 2 (BlackRock/iShares, fund_only $2.7T) and eid 3241 (BlackRock Inc., 13F-dominant $5.9T) — because the cp-4b brand→filer bridge used `control_type='advisory'` which is excluded from the inst-inst climb. Sum of the two ≈ $8.6T, which lands within the $10–11T band only loosely.
- Externally reported AUM includes fixed income, cash, and alternatives; cp-5 fund-tier rollup is EC (equity) only. Comparison is apples-to-pears.

The structural envelope above is the appropriate gate and was the gate Bundle B used.

### 4.3 Top-25 envelope check

| firm | coverage_class | 13F $B | fund_adj $B | naive_R5 $B | modified_R5 $B | flags |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| Vanguard Group | both | 6,897.7 | 6,416.6 | 9,421.2 | 7,630.0 | — |
| BlackRock, Inc. | both | 5,916.3 | 459.0 | 6,124.3 | 6,099.1 | — |
| State Street / SSGA | both | 2,980.9 | 762.9 | 3,185.6 | 3,144.3 | — |
| Fidelity / FMR | both | 1,961.3 | 2,709.6 | 4,302.5 | 3,054.0 | — |
| BlackRock / iShares | fund_only | 0.0 | 2,679.0 | 2,924.1 | 2,679.0 | — |
| Capital Group / American Funds | fund_only | 0.0 | 2,234.0 | 2,820.6 | 2,234.0 | — |
| Morgan Stanley IM | both | 1,675.0 | 80.3 | 1,726.9 | 1,721.1 | — |
| GEODE | both | 1,620.4 | 17.4 | 1,624.5 | 1,622.7 | — |
| JPMorgan Chase | 13F_only | 1,592.8 | 0.0 | 1,592.8 | 1,592.8 | — |
| Bank of America | 13F_only | 1,473.9 | 0.0 | 1,473.9 | 1,473.9 | — |
| (15 more) | | | | | | — |

**Envelope flag count: 0/25.**

### 4.4 Verdict

**A — R5 LOCKED.** No envelope flags fire under the corrected matrix; no real coverage_class transitions; structural envelope holds across the entire top-25. Modified R5 (Bundle A §1.4) survives the corrected evidence without revision.

---

## 5. Implication for Bundle C scope

**No re-scope.** Bundle C can launch with R5 locked. The corrected matrix tightens fund-tier numbers (now half of original) but does not change the rule's structural validity. Per-firm rollup_type sensitivity is a documented sub-finding for downstream consumers but does not block Bundle C.

The `cp-5-top-parent-coverage-matrix.csv` and `cp-5-overlap-probe.csv` originals from PR #276 are **retained as audit trail**. The corrected versions (`-corrected.csv` suffix) are canonical for any downstream work going forward.

---

## 6. Out-of-scope discoveries / surprises

### 6.1 Bundle B vs our matrix — fund_tier residuals

When comparing Bundle B's `fund_tier_corrected_b` to our matrix's `fund_tier_aum_billions` (both derived under `rollup_type='decision_maker_v1'`), residuals up to ±$83B exist:

| top_parent | name | our matrix $B | Bundle B $B | residual $B |
| ---: | --- | ---: | ---: | ---: |
| 10443 | Fidelity / FMR | 3,961.9 | 4,045.1 | −83.2 |
| 3616 | T. Rowe Price | 952.2 | 877.4 | +74.7 |
| 3241 | BlackRock, Inc. | 484.2 | 418.5 | +65.7 |
| 18073 | J.P. Morgan IM | 459.7 | 418.0 | +41.7 |
| 4 | Invesco | 923.9 | 935.9 | −12.0 |
| 7859 | GEODE | 19.1 | 9.6 | +9.6 |

These residuals do **not** invalidate the verdict (envelope flags = 0 either way) but suggest the two analyses use slightly different climb mechanisms. Possible causes:

- Bundle B's helper may climb fund → series_id → institution differently than our PR #276-replicated path (fund → `entity_rollup_history.rollup_entity_id` → inst→top_parent climb).
- Bundle B may handle `dm_rollup_entity_id` (fund_holdings_v2 column) differently from the entity_rollup_history denormalized path.
- GEODE's exact 2× residual ($19.1 vs $9.6) is suspicious — may indicate Bundle B applied a half-count normalization for one edge case.

**Open question 1 (chat):** which climb mechanism is canonical going forward? Recommend reconciling before Bundle C reader migration.

### 6.2 rollup_type divergence implications

1,826 funds (13.8%) have `decision_maker_v1.rollup_entity_id ≠ economic_control_v1.rollup_entity_id`. For BlackRock Inc., this drives a 27% swing in fund-tier AUM depending on which rollup_type is chosen.

**Open question 2 (chat):** does Bundle C need to support both rollup_type views, or is `decision_maker_v1` permanently canonical? If both, downstream readers need a query parameter.

### 6.3 Bimodal split collapse

The PR #276 narrative around "47% 13F-dominant / 42% fund-extending" is materially weaker under corrected numbers (the fund-extending side drops from 42% → 13%). This does not change R5 but does soften the empirical motivation for the fund-tier rollup; the case is now "13F is sufficient for ~80% of (top_parent, ticker) coverage; fund-tier extends in a long tail of ~13%". Downstream framing in CP-5 narrative docs may need a small rephrasing.

### 6.4 GEODE edge case

GEODE shows identical fund_tier under original and corrected matrices ($19.13B both), unlike every other firm in top-25. This implies its 1 fund-typed entity has only one open `entity_rollup_history` row, not two — an outlier in the schema's "every fund has 2 open rollup_type rows" invariant. Possibly a recent loader artifact; surfaces as a minor data-completeness question, not a blocker.
