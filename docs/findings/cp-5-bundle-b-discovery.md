# CP-5 Comprehensive Discovery — Bundle B: Entity Graph Mapping

**Date:** 2026-05-04
**Branch:** `cp-5-comprehensive-discovery-bundle-b`
**HEAD baseline:** `9602376` (PR #277 cp-5-bundle-a)
**Methodology:** read-only; probes pinned to `quarter='2025Q4'` (point-in-time validation) and 2025Q1-Q4 (per-quarter resolution stability).

**Refs:**
- [docs/findings/cp-5-bundle-a-discovery.md](cp-5-bundle-a-discovery.md) (R5 defects + N-PORT completeness; locks the modified-R5 rule §1.4)
- [docs/findings/cp-5-discovery.md](cp-5-discovery.md) (the original CP-5 scoping)
- [docs/decisions/inst_eid_bridge_decisions.md](../decisions/inst_eid_bridge_decisions.md)
- [docs/decisions/d4-classification-precedence.md](../decisions/d4-classification-precedence.md)
- Probe scripts: [scripts/oneoff/cp_5_bundle_b_phase0_r5_validation.py](../../scripts/oneoff/cp_5_bundle_b_phase0_r5_validation.py), [phase1_tier_inventory.py](../../scripts/oneoff/cp_5_bundle_b_phase1_tier_inventory.py), [phase2_rollup_graph.py](../../scripts/oneoff/cp_5_bundle_b_phase2_rollup_graph.py), [phase3_identifiers.py](../../scripts/oneoff/cp_5_bundle_b_phase3_identifiers.py), [phase4_temporal.py](../../scripts/oneoff/cp_5_bundle_b_phase4_temporal.py), [common.py](../../scripts/oneoff/cp_5_bundle_b_common.py)

---

## 0. Phase 0.5 — Modified R5 validation (STOP gate)

**Result:** STOP-gate PASS. Modified R5 lands within the structural envelope `[max(SUM_13F, SUM_fund_adj), SUM_13F + SUM_fund_adj]` for every top-25 firm. Continuing to Phase 1.

### 0.1 Top-25 result snapshot

| top_parent | name | coverage_class | 13F $B | fund_raw $B | fund_adj $B | naive_R5 $B | **modified_R5 $B** |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: |
| 4375 | Vanguard Group | both | 6,897.7 | 8,210.2 | 6,416.6 | 9,421.2 | **7,630.0** |
| 3241 | BlackRock, Inc. | both | 5,916.3 | 484.2 | 459.0 | 6,124.3 | **6,099.1** |
| 7984 | State Street / SSGA | both | 2,980.9 | 807.8 | 762.9 | 3,185.6 | **3,144.3** |
| 10443 | Fidelity / FMR | both | 1,961.3 | 3,961.9 | 2,709.6 | 4,302.5 | **3,054.0** |
| 2 | BlackRock / iShares | fund_only | 0.0 | 2,924.1 | 2,679.0 | 2,924.1 | **2,679.0** |
| 12 | Capital Group / American Funds | fund_only | 0.0 | 2,820.6 | 2,234.0 | 2,820.6 | **2,234.0** |
| 2920 | Morgan Stanley IM | both | 1,675.0 | 86.2 | 80.3 | 1,726.9 | **1,721.1** |
| 7859 | GEODE | both | 1,620.4 | 19.1 | 17.4 | 1,624.5 | **1,622.7** |
| 4433 | JPMorgan Chase | 13F_only | 1,592.8 | 0.0 | 0.0 | 1,592.8 | **1,592.8** |
| 8424 | Bank of America Corp | 13F_only | 1,473.9 | 0.0 | 0.0 | 1,473.9 | **1,473.9** |
| (15 more) | … | … | … | … | … | … | … |

Full table: [data/working/cp-5-bundle-b-r5-validation.csv](../../data/working/cp-5-bundle-b-r5-validation.csv).

### 0.2 Plausibility flags fired

After tightening the plausibility check (see 0.3 below), **0 firms** have any flag. The four hard structural flags evaluated were:
- `modified_GT_naive` — subtraction direction wrong → 0 firms
- `13F_only_zero_R5` / `fund_only_zero_R5` — rule fails to produce a result → 0 firms
- `R5_below_max_envelope` — modified_R5 < max(13F, fund_adj) → 0 firms
- `R5_above_sum_envelope` — modified_R5 > 13F + fund_adj → 0 firms

### 0.3 **Material finding — cp-5-top-parent-coverage-matrix.csv has a 2× double-count on fund-tier**

In [scripts/oneoff/cp_5_discovery_phase1_inventory.py:158-165](../../scripts/oneoff/cp_5_discovery_phase1_inventory.py), the fund_chain SQL omits the `rollup_type` filter:

```sql
SELECT erh.entity_id AS fund_entity_id, erh.rollup_entity_id AS institution_entity_id
FROM entity_rollup_history erh
JOIN entity_current ec_f ON ec_f.entity_id = erh.entity_id
WHERE erh.valid_to = '9999-12-31'
  AND ec_f.entity_type = 'fund'
-- NB: no AND rollup_type='decision_maker_v1' — joins BOTH open rollup_types
```

Every fund has 2 open rollup_history rows (one for `decision_maker_v1`, one for `economic_control_v1`), so each fund's market_value contributes twice to per-top_parent fund-tier sums. **Every `fund_tier_aum_billions` figure in cp-5-top-parent-coverage-matrix.csv is 2× reality.**

Empirical verification: Vanguard 4375 fund-tier raw EC AUM
- Matrix value: $16,420B
- With `rollup_type='decision_maker_v1'` filter: $8,210B
- With `rollup_type='economic_control_v1'` filter: $8,210B
- Both rollup_types currently point to the SAME `rollup_entity_id` for every fund.

The matrix's `coverage_class` derivation is unaffected (binary thresholds still classify correctly), but every published fund-tier and combined number is doubled. cp-5-discovery §1d's claim "Vanguard $23.3T combined" is actually **$15.1T combined** ($6.9T 13F + $8.2T fund_tier_corrected). Bundle A §1.1's intra-family FoF AUM of $2,207B was computed by Bundle A's own probe (which used the correct filter), so Bundle A's numbers are NOT affected.

**Recommended remediation:** chat decides whether to re-publish the matrix with the filter, or annotate cp-5-discovery §1d with a "fund-tier values shown are 2x" footnote. Bundle B Phase 1 here uses corrected numbers.

---

## 1. Entity tier inventory (Phase 1)

### 1.1 Tier taxonomy (canonical labels)

| tier | label |
| :-: | --- |
| **T1** | top parent (institution, no inst→inst control parent) |
| **T2** | mid-level holding company (institution, has parent AND children) |
| **T3** | operating IA — reporting (institution, ≥100 holdings_v2 latest rows) |
| **T4** | operating IA — non-reporting (institution, 0 holdings_v2 rows, fund-tier rollup AUM > $0 as top_parent) |
| **T5** | brand (institution, exists in `entity_aliases` with `alias_type='brand'`) |
| **T6** | sub-adviser (in `ncen_adviser_map` with `role='subadviser'`) |
| **T7** | fund series (`entity_type='fund'`) |
| **T8** | share class (not currently broken out — placeholder) |
| **T9** | holdings rows (CUSIP × fund × period leaf) |

### 1.2 Per-tier counts

| tier | label | n | AUM-exposure context |
| :-: | --- | ---: | --- |
| T1 | top parent | 13,687 | (matches Bundle A baseline) |
| T2 | mid-level holding | 32 | 32 institutions sit in the middle of the graph (have parent + children) |
| T3 | operating IA reporting (≥100 rows) | 6,947 | $238,228B (4Q rolling) |
| T4 | operating IA non-reporting (0 rows, fund-tier > 0 as TP) | 373 | $12,176B fund-tier exposure |
| T5 | brand (alias_type='brand', 0 holdings_v2 rows) | 3,103 | — |
| T6a | sub-adviser distinct adviser_crd | 429 | — |
| T6b | sub-adviser resolved to entity (via crd) | 358 | 83% link rate from ncen_adviser_map → `entity_identifiers` |
| T7 | fund series | 13,221 | (matches Bundle A) |
| T8 | share class | 0 | not currently broken out |
| T9a | holdings_v2 latest rows | 12,270,984 | 4Q rolling |
| T9b | fund_holdings_v2 latest rows | 14,565,870 | 6Q rolling, all asset categories |

Output: [data/working/cp-5-bundle-b-tier-inventory.csv](../../data/working/cp-5-bundle-b-tier-inventory.csv).

**Take:** the entity tier population skews heavily toward T1 (13,687 standalone top-parents, 99% of inst nodes) — the "thin shallow graph" pattern that cp-5-discovery already surfaced. T2 (32) and T4 (373) are tiny by count but T4 carries $12T fund-tier AUM — these are the brand-vs-filer / non-reporting-operating-AM cohort that CP-5 read layer must reach via `fund_holdings_v2`. T5 brands (3,103) are 23% of all institutions; CP-5.5's bridging work targets a small fraction of these (cp-5-discovery's 13 Cat B brands).

### 1.3 Capital Group umbrella + similar-firm survey

**Capital Group is the only "umbrella" pattern in the surveyed top tier.** The 4 Capital Group eids (12 / 6657 / 7136 / 7125) are all SELF top-parents — none has an inst→inst edge to any sibling or to the umbrella eid 12. Each filer arm aggregates its own 13F.

| eid | display_name | top_parent_self | n_inst_children | h13f_rows (4Q) | h13f_aum_b | alias_summary |
| ---: | --- | :-: | ---: | ---: | ---: | --- |
| 12 | Capital Group / American Funds | yes | 0 | 0 | 0.00 | brand:1; filing:3 |
| 6657 | Capital World Investors | yes | 0 | 2,274 | 2,772.49 | brand:1 |
| 7125 | Capital Research Global Investors | yes | 0 | 1,754 | 2,034.06 | brand:1 |
| 7136 | Capital International Investors | yes | 0 | 1,786 | 2,346.46 | brand:1 |

Total Capital Group 13F footprint: $7,153B (4Q rolling, ~$1.79T per quarter — consistent with Bundle A's per-quarter $1.92T snapshot).

**Six other large families surveyed — all use the "single primary filer + brand satellites" pattern, not the umbrella shape:**

| family | active filer eid (≥100 rows) | filer 13F $B | n satellite/brand-only eids | umbrella shape? |
| --- | ---: | ---: | ---: | :-: |
| Wellington Management | 11220 | 1,693.1 | 1 (eid 9935 brand-only) | no — 1 filer + brand |
| Janus Henderson | 1399 (PLC) | 828.8 | 3 (eids 51, 9192 brand; 11231 child of 1399) | no — has a real inst-inst child |
| Invesco | 569 (Invesco Ltd.) | 2,402.8 | 2 (eids 4, 9297 brand) | no — 1 filer + brand |
| Federated Hermes | 4635 | 215.96 | 1 (UK arm brand) | no |
| AllianceBernstein | 8497 (rolled up to 18762 Holding LP) | 1,217.2 | 3 (eids 57, 17917, 18762 brand-or-holding) | partial — has an ER edge |
| Eaton Vance | (none active — absorbed) | — | 4 (eids 19, 17940 children of MS eid 2920; eid 8459 brand-only) | no — fully absorbed |

**Implication:** the Capital Group 3-filer-arm shape is **anomalous, not a recurring pattern**. Recommendation: do NOT introduce a new schema relationship_type for "umbrella". Instead, treat Capital Group as a one-off carve-out per the cp-4b precedent (relationship_id 20820-20823 shape) — a single brand→filer bridge for each of the 3 arms (eid 12 ← {6657, 7125, 7136} via 3 separate `control` ER rows), or one bridge from each filer arm to a synthetic Capital-Group-AMC parent. Bundle A §1.3 / cp-5-discovery §6 already classified this as Bundle B work and reserved scope for it; this finding confirms the design.

Output: [data/working/cp-5-bundle-b-umbrella-cohort.csv](../../data/working/cp-5-bundle-b-umbrella-cohort.csv).

### 1.4 Coverage gaps per tier

| tier | gap signal |
| :-: | --- |
| T1 | 13,687 top-parents → ~$8,100B of 13F AUM is in T1 hedge-fund / SMA / pension entities with no fund-tier path (cp-5-discovery §5). Not a remediation target — these structurally lack fund-side decomposition. |
| T2 | 32 mid-level — small enough to inspect manually if a CP-5.5 PR needs it. |
| T3 | 6,947 active filers; coverage is good (Phase 3.1 shows 99.9% CIK and 71% CRD on this tier). |
| T4 | 373 non-reporting IAs are **the brand-vs-filer cohort** plus genuine non-13F operating arms. |
| T5 | 3,103 brand entities — only 13 are slated for Cat B bridges per cp-5-discovery §6. The other 3,090 are international branches / DBA names that don't need bridging. |
| T6 | 429 distinct sub-adviser CRDs in N-CEN; 358 (83%) are linkable to entities via CRD. The 71 unlinkable ones suggest sub-advisers that exist in N-CEN but not in `entities` — a Phase 0/loader gap. |
| T7 | 13,221 fund-typed entities. Bundle A §2.1 Layer A surfaced 120 duplicate sibling residuals; Bundle B Phase 3.3 found 6 of these in the Adams cohort specifically. |
| T8 | not broken out — share-class-level rollup is not in scope for CP-5. |
| T9 | 84,363 fund_holdings_v2 rows are the rollup-gap cohort — see Phase 2.3 for a re-characterization. |

---

## 2. Rollup graph correctness (Phase 2)

### 2.1 Multi-hop traversal

| hop_count | n |
| ---: | ---: |
| 0 (self top-parent) | 13,687 |
| 1 | 338 |
| 2 | 10 |
| 3 | 3 |

**Max hop count = 3** — well under the 10-hop STOP threshold. The rollup graph is shallow and traversable.

### 2.2 Cycle-truncated entities — 21 found (was 1 in cp-5-discovery)

| pattern | example pair | resolution |
| --- | --- | --- |
| duplicate eids that mutually parent each other | Goldman Sachs Asset Management eid 22 ↔ eid 17941 | entity merge (cp-4a precedent) |
| | Lazard Asset Management eid 58 ↔ eid 18070 | merge |
| | Lord, Abbett & Co. LLC eid 893 ↔ eid 17916 | merge |
| | Ariel Investments eid 70 ↔ eid 18357 | merge |
| | Sarofim Trust Co eid 858 ↔ eid 18029 | merge |
| | Thornburg Investment Management eid 2925 ↔ eid 18537 | merge |
| | Lewell, Equitable, Stonebridge, Financial Partners pairs | merge |

Full list: 21 entities → 10-11 merge candidate pairs (each pair is mutually-cycling, so two entities map to one merge operation).

cp-5-discovery counted "1 cycle" because its hop-by-hop trace converged at hop=20; my probe terminates earlier when a cycle is detected and tags both entities. The 21 number reflects the actual count of entities whose top_parent climb is broken by a cycle, not the number of cycles. **These 21 should merge into ~10-11 canonical eids per the cp-4a entity-merge playbook before CP-5.1 ships.**

### 2.3 Quarter-by-quarter rollup resolution

| quarter | h13f_total | h13f_resolved % | fund_ec_total | fund_ec_resolved % |
| --- | ---: | ---: | ---: | ---: |
| 2025Q1 | 2,993,162 | 100.0% | 1,360,380 | 97.97% |
| 2025Q2 | 3,047,474 | 100.0% | 1,352,579 | 98.00% |
| 2025Q3 | 3,024,698 | 100.0% | 1,435,020 | 97.29% |
| 2025Q4 | 3,205,650 | 100.0% | 1,809,713 | 94.96% |

13F resolution is perfect (every entity_id maps to an inst_to_tp). Fund EC resolution drops from 98.0% in Q2 to 94.96% in Q4 — the absolute unresolved row count grows from ~27K (Q1-Q2) to ~91K in Q4. **Q4 carries most of the rollup-gap rows.**

Distinct fund_entity_ids active in 2025Q1-Q4: 10,123 — of which 9,533 (94.2%) are resolved to a top_parent, 590 are unresolved. These 590 are the entity-graph-side gap; the 84K row gap below is the loader-side gap.

### 2.4 **84K rollup-builder-gap row analysis — recharacterization**

Bundle A §2.1 Layer C reported 84,363 fund_holdings_v2 rows / $418.5B / 76 funds / 104 series with NULL `rollup_entity_id` or `dm_rollup_entity_id`, and characterized this as a "rollup builder gap, likely a loader-gap fix."

**Re-characterization: it's a loader gap, not a rollup-builder gap.**

100% of the 84,363 rows have **`entity_id IS NULL`**. The rollup builder cannot resolve a NULL entity_id to anything; the gap is upstream — at fund_holdings_v2 ingestion time, the loader didn't assign an entity_id to these rows.

| metric | value |
| --- | ---: |
| rows | 84,363 |
| AUM | $418.5B |
| entity_id IS NULL | 84,363 (100%) |
| rollup_entity_id IS NULL | 84,363 |
| dm_rollup_entity_id IS NULL | 84,363 |
| n_distinct_funds (entity-level) | 0 |
| n_distinct_fund_ciks | 76 |
| n_distinct_series_id | 104 |

**Top contributors are American Funds bond funds + a tail of bond/credit funds:**

| fund_cik | family_name | aum_b |
| ---: | --- | ---: |
| 0000013075 | Bond Fund of America | 101.1 |
| 0000050142 | Tax Exempt Bond Fund of America | 48.2 |
| 0000826813 | Intermediate Bond Fund of America | 28.5 |
| 0000925950 | American High-Income Municipal Bond Fund | 26.6 |
| 0000823620 | American High Income Trust | 26.3 |
| 0001475712 | Global Opportunities Portfolio | 24.6 |
| (others — smaller bond / credit funds) | | |

**Recoverability:** of the top-50 gap CIKs, 23 (46%) are already in `entity_identifiers` (loader simply missed the link); the other 27 are unknown to the entity layer (require new fund-typed entity creation).

**Remediation path:**
1. **Phase 1 — link existing CIKs (23 of top 50):** UPDATE `fund_holdings_v2.entity_id` from `entity_identifiers` JOIN on (cik, series_id). Backlog item; no schema change.
2. **Phase 2 — create new fund entities (27 of top 50 + tail):** insert into `entities` per the existing fund-creation pattern; route via Phase 0 fund creation pipeline.
3. **Phase 3 — re-run rollup builder:** once entity_ids are populated, the existing rollup builder will resolve them.

Output: [data/working/cp-5-bundle-b-rollup-gap-cohort.csv](../../data/working/cp-5-bundle-b-rollup-gap-cohort.csv).

### 2.5 Operating-AM rollup policy enforcement audit

5 top-50 top-parents trip the bank/insurance/holding-co keyword heuristic:

| top_parent | name | 13F $B | fund_tier $B (matrix doubled) | coverage_class | verdict |
| ---: | --- | ---: | ---: | --- | --- |
| 8424 | BANK OF AMERICA CORP /DE/ | 1,473.9 | 0.0 | 13F_only | **flag** — should roll up to BoA Wealth/Merrill operating AM eid |
| 91 | Norges Bank | 934.8 | 0.0 | 13F_only | **valid** — Norges Bank Investment Management IS the manager (sovereign wealth fund) |
| 7440 | Royal Bank of Canada | 614.7 | 0.0 | 13F_only | **flag** — should roll up to RBC Wealth Management / RBC Global Asset Management |
| 1401 | Bank of New York Mellon Corp | 567.7 | 0.0 | 13F_only | **flag** — should roll up to BNY Investments / BNY Wealth |
| 8994 | Manulife Financial Corp | 121.7 | 296.3 (148.1 corrected) | both | **flag** — should roll up to Manulife Investment Management |

3-4 candidate violations; 1 valid (Norges Bank). Each flagged top-parent is a candidate to be re-rolled to its operating-AM eid via a new `control` edge in `entity_relationships`. **Recommendation: route to a `cp-5-bank-op-am-cleanup` follow-up PR** alongside the cycle-merge work — the policy stipulates rollup must terminate at operating AM, not bank/insurance parent.

Output: [data/working/cp-5-bundle-b-rollup-policy-audit.csv](../../data/working/cp-5-bundle-b-rollup-policy-audit.csv).

---

## 3. Identifier completeness + cross-period CIK (Phase 3)

### 3.1 Per-tier identifier coverage

| tier | n | CIK % | CRD % | LEI % | FIGI % | series_id % |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| T7 fund | 13,221 | 0.0 | 0.0 | 0.0 | 0.0 | **100.0** |
| T1+T3 top-active | 6,780 | **99.9** | 71.0 | 0.0 | 0.0 | 0.0 |
| T1+T5 top-brand | 2,961 | 87.3 | 26.7 | 0.0 | 0.0 | 0.0 |
| T1 top-low-filer (<100 rows) | 2,142 | 100.0 | 54.2 | 0.0 | 0.0 | 0.0 |
| T1 top-quiet (no holdings, no brand) | 1,804 | 94.6 | 0.0 | 0.0 | 0.0 | 0.0 |
| T3 active subsidiary | 157 | 99.4 | 86.6 | 0.0 | 0.0 | 0.0 |
| T5 brand subsidiary | 123 | 69.9 | 82.9 | 0.0 | 0.0 | 0.0 |
| T2 mid (parent + children) | 32 | **56.2** | 81.2 | 0.0 | 0.0 | 0.0 |
| T4 op_AM_or_quiet_sub | 10 | **0.0** | 0.0 | 0.0 | 0.0 | 0.0 |

**Findings:**
- **LEI: 0% across the board.** No LEIs are ingested. Adding LEI → entity link would help with cross-jurisdiction reconciliation but is a backlog item — no CP-5 dependency.
- **FIGI: 0%.** FIGI is only relevant on the security side, not the entity side. Expected; not a gap.
- **T2 mid-level (32 entities): only 56.2% have CIK.** Mid-level holding companies sometimes don't file SEC paperwork directly; the gap is structural for ~14 of them. Verify on case-by-case basis.
- **T4 op_AM_or_quiet_sub (10 entities): 0% on every identifier.** These 10 zero-everywhere entities deserve manual triage — they may be incomplete entity records.
- T1+T3 top-active 99.9% CIK is healthy; the 0.1% gap (~7 entities) is the cohort that needs the most attention since they are active 13F filers without traceable CIK.

Output: [data/working/cp-5-bundle-b-identifier-coverage.csv](../../data/working/cp-5-bundle-b-identifier-coverage.csv).

### 3.2 Cross-period CIK reconciliation

**Series-level:** 0 series have multiple distinct fund_ciks across quarters. **Series → CIK assignment is stable.**

**Institution-level same-name-different-CIK pairs: 23.** Top examples (full list in CSV):

| normalized name | n eids | n ciks | eids | sample display_name |
| --- | ---: | ---: | --- | --- |
| WELLINGTONMANAGEMENT | 2 | 3 | 11220, 14 | Wellington Management |
| FIDELITYFMR | 2 | 2 | 10443, 11 | Fidelity / FMR (known brand-vs-filer) |
| VANGUARDGROUP | 2 | 2 | 4375, 1 | Vanguard Group (post-cp-4a-merge SCD vestigial) |
| HEARTLANDADVISORSINC | 2 | 2 | 25168, 5486 | HEARTLAND ADVISORS INC |
| EAGLECAPITALMANAGEMENTLLC | 2 | 2 | 9119, 7002 | EAGLE CAPITAL MANAGEMENT LLC |
| MIZUHOSECURITIESUSALLC | 2 | 2 | 5617, 7988 | MIZUHO SECURITIES USA LLC |
| BNPPARIBAS | 2 | 2 | 5936, 10027 | BNP Paribas |
| (16 more, mostly mid-tier) | | | | |

**Causes (sampled):**
- 4 are known brand-vs-filer splits already documented (Fidelity/FMR, Vanguard, State Street).
- ~10 are likely same-firm-different-CIK genuine duplicates (Heartland, Eagle Capital, Wellington's 3rd CIK, etc.) — candidates for entity merge per cp-4a precedent.
- ~9 require manual triage (BNP Paribas may be legitimate US-vs-global subsidiary; Mizuho Securities USA likewise).

**Recommendation:** route the 23 to a `cp-5-cross-period-cik-cleanup` backlog PR after cycle merges land. Don't block CP-5.1 read-layer on this — modified R5 still produces the correct answer because both eids contribute to one or the other side of the union.

Output: [data/working/cp-5-bundle-b-cross-period-cik.csv](../../data/working/cp-5-bundle-b-cross-period-cik.csv).

### 3.3 Adams duplicate cohort

Bundle A §2.1 Layer A reported 120 duplicate fund-typed entities across all families ("Adams Diversified Equity Fund × 3, Adams Natural Resources Fund × 3, etc."). Probing **Adams specifically: only 14 entities total**, of which 6 are duplicate-name groups. The 120 number was the universe-wide count, not Adams-only.

**Adams entities (14):**

| eid | type | display_name | cik | series_id | n_aliases | n_relationships |
| ---: | --- | --- | --- | --- | ---: | ---: |
| 2961 | institution | ADAMS DIVERSIFIED EQUITY FUND, INC. | 0000002230 | (none) | 1 | 3 |
| 6471 | institution | ADAMS NATURAL RESOURCES FUND, INC. | 0000216851 | (none) | 1 | 3 |
| 824 | institution | ADAMS STREET PARTNERS LLC | 0001193586 | (none) | 1 | 0 |
| 27097 | institution | ADAMS STREET PRIVATE EQUITY NAVIGATOR FUND LLC | 0001862281 | (none) | 1 | 0 |
| 1571 | institution | ADAMSBROWN WEALTH CONSULTANTS LLC | 0001911244 | (none) | 1 | 0 |
| 4909 | institution | Adams Asset Advisors, LLC | 0001386929 | (none) | 1 | 1 |
| 19509 | institution | Adams Asset Advisors, LLC | (none) | (none) | 1 | 2 |
| 11012 | institution | Adams Wealth Management | 0001803084 | (none) | 1 | 0 |
| 20210-20212 | fund | Adams Natural Resources Fund, Inc. | (none) | 216851_… (× 3) | 1 | 1 |
| 20213-20215 | fund | Adams Diversified Equity Fund, Inc. | (none) | 2230_… (× 3) | 1 | 1 |

**Duplication classification:**

| group | entities | classification | action |
| --- | ---: | --- | --- |
| ADAMS DIVERSIFIED EQUITY FUND (institution) + 3 fund-typed siblings | 4 | **legitimate** — institution carries the active 13F (291 rows / $8.83B), fund-typed eids (20213/14/15) are series-id-keyed snapshots (one per filing cycle) | no action |
| ADAMS NATURAL RESOURCES FUND (institution) + 3 fund-typed siblings | 4 | **legitimate** — institution active filer (175 rows / $1.97B), 3 fund-typed series snapshots | no action |
| Adams Asset Advisors, LLC (eids 4909 + 19509) | 2 | **likely duplicate** — same name, eid 4909 has CIK, eid 19509 doesn't | **merge candidate** (cp-4a) |
| Adams Street Partners (eids 824, 27097) | 2 | distinct firms — Partners is the parent, "Private Equity Navigator Fund" is a subsidiary fund | maybe link via `control` edge |

**Take:** The Adams-specific duplication is small (1 likely merge: 4909+19509). Bundle A's "120 cohort" remains a roadmap item but is not concentrated in Adams — it's distributed across many families.

Output: [data/working/cp-5-bundle-b-adams-cohort.csv](../../data/working/cp-5-bundle-b-adams-cohort.csv).

---

## 4. Entity graph temporal stability (Phase 4)

### 4.1 Schema state

`entity_relationships` already has SCD columns:
- 18,374 total rows (16,324 open, 2,050 closed)
- `valid_from` ranges 2000-01-01 → 2026-05-03
- Closed rows: 2026-04-07 → 2026-05-02 (recent ADV Schedule A re-derivation maintenance)

**The schema supports time-versioned relationships.** What it does NOT support: per-relationship M&A event capture. `valid_from` is universally `2000-01-01` for inferred / synthetic edges (378 of the 395 open inst→inst control rows; only 17 have a real recent valid_from).

### 4.2 'merge' control_type cohort

Only 2 rows total — both 2026-05-02 entries from CP-4a's eid-bridge fix:
- 4375 → 1 (Vanguard / Vanguard self-merge)
- 2322 → 30 (PIMCO / PIMCO self-merge)

These are entity-eid consolidation artifacts, **not** real M&A event records.

### 4.3 M&A event coverage probe — current graph

Probed 5 known 2017-2024 events for coverage:

| event | matching ER rows | open rows | partial close indicates |
| --- | ---: | ---: | --- |
| Janus Henderson 2017 merger | 7 | 6 | ER rows present; one Janus Henderson Investors UK closed 2026-04-08 + replaced |
| Franklin / Legg Mason 2020 | 0 | 0 | **not captured** — Franklin Templeton + Legg Mason brands have no ER edge in current graph |
| BlackRock acquired Aperio 2021 | 2 | 0 | ER rows existed but were closed 2026-04-26 — Aperio currently has NO inst-inst parent |
| Morgan Stanley acquired Eaton Vance 2021 | 4 | 2 | partial — eids 19, 17940 still rolled up to MS 2920; eids 8459, 2257 closed 2026-04-27 |
| Affiliated Managers Group affiliates | 10 | 5 | mixed — half open, half closed in recent maintenance |

### 4.4 **Architectural recommendation: Option C (hybrid)**

Three options:

| option | description | pros | cons |
| --- | --- | --- | --- |
| **A** time-invariant | use today's graph for all historical quarters | simplest; matches current de facto state | **wrong attribution at M&A boundaries** when historical quarters predate the merger |
| **B** full time-versioned | every relationship has real valid_from / valid_to capturing M&A dates | most correct | requires capturing M&A history per entity (data-collection burden) |
| **C** hybrid (recommended) | time-invariant default + explicit valid_from / valid_to overrides for known M&A events | low burden; correct for the events that matter | requires curating the M&A event list |

**Why Option C:**

1. **Schema already supports it.** The `valid_from` / `valid_to` columns and the SCD pattern are already in `entity_relationships`. We don't need a migration — we need data.
2. **Concentration of impact.** A handful of large M&A events (Franklin/Legg Mason, MS/Eaton Vance, BlackRock/BGI, Janus/Henderson) account for the majority of historically wrong attributions. Capturing 20-30 events covers >95% of impact.
3. **Today's graph is a reasonable default** for the 2025Q1+ data we currently load. Time-versioning becomes important only when historical (pre-2025) data is loaded.
4. **Defers data-collection work.** Option B requires backfilling all 395 inst-inst control edges with real `valid_from`. Option C only requires capturing the dates we actually care about.

**Implementation plan when historical loads happen (post-CP-5):**
- Author a `data/decisions/ma_event_register.md` listing 20-30 events with valid_from / valid_to and entity ids.
- For each event, author a small migration that closes the existing default-2000 row and inserts the historical-correct rows with proper valid_from.
- Modify the rollup builder + reader queries to honor `valid_from <= holdings.report_date < valid_to` instead of just `valid_to = '9999-12-31'`.

**No CP-5 execution dependency.** Today's data is 2025Q1-Q4 only; time-invariance is correct for today's working set. Address Option C when 10+ year data load is scoped (Pipeline 4+).

---

## 5. Open questions for Bundle C

These follow-ups depend on Bundle B's findings.

1. **Matrix double-count remediation.** Re-publish `cp-5-top-parent-coverage-matrix.csv` with the `rollup_type='decision_maker_v1'` filter, or annotate cp-5-discovery §1d with a "fund-tier shown is 2x" footnote? Bundle C should do one of these before any reader migration consumes the matrix.

2. **Cycle-merge cohort sequencing.** The 21 cycle-truncated entities → ~10-11 merge candidates (Goldman 22+17941, Lazard 58+18070, Lord Abbett 893+17916, etc.). Land before or after CP-5.1 read-layer-foundation? Recommendation: **before** — CP-5.1's `build_top_parent_join()` helper will misroute holdings under the duplicate eid until merged.

3. **84K loader-gap cohort priority.** Recoverability: 23 of top-50 CIKs are linkable, 27 require new entity creation. Single PR or split? Most of the AUM is concentrated in the top 30 CIKs (American Funds bond family).

4. **Operating-AM policy violations.** 4 candidate violations (BoA, RBC, BNY, Manulife) carry $2.78T 13F AUM. Each requires identifying the operating-AM eid and creating a `control` edge from operating AM up to the bank/insurance parent. Single PR cohort or per-firm?

5. **23 same-name-different-CIK pairs — manual triage list.** Some are known brand-vs-filer; others may be genuine duplicates. Bundle C should review the 16 non-obvious pairs (excluding Vanguard, Fidelity, State Street already-known cases).

6. **T4 zero-identifier cohort (10 entities).** Manual review.

7. **LEI ingestion as a backlog item.** Today: 0% coverage. Adding LEI from GLEIF would improve cross-jurisdiction reconciliation. Pipeline-side gap; not blocking CP-5.

---

## 6. Out-of-scope discoveries / surprises

- **`entity_rollup_history.rollup_type` has exactly 2 values** (`decision_maker_v1`, `economic_control_v1`), each with 13,221 fund rows. Both currently point to the SAME `rollup_entity_id` for every fund. The dual-rollup-type design is in place but the two types are functionally identical today. If Bundle C plans to differentiate them, the data-side work has not started.

- **`entity_relationships.is_inferred` exists** but only 1 of the 2 'merge' rows uses it (both `False`). Most synthetic edges (the 378 default-2000 rows) are not flagged inferred — meaning the field is reserved but underused. Bundle C audit should clarify the semantics.

- **`ncen_adviser_map.role` has 2 values** ('adviser': 7,745 open; 'subadviser': 3,464 open). 'adviser' (registrant adviser) outnumbers 'subadviser' 2:1. The T6a cohort sized at 429 distinct subadviser CRDs is a small slice of the 3,464 subadviser rows because most subadvisers serve multiple registrants → many rows, fewer distinct CRDs.

- **Wellington has THREE distinct CIKs.** eid 11220 (active filer, 22,707 holdings rows / $1.69T) plus eid 14 (brand-only) — but the 3 CIKs span both eids. May indicate one missed merge or a legitimately complex registration history. Worth a Bundle C drilldown.

- **Eaton Vance is fully absorbed into Morgan Stanley IM (eid 2920).** All 4 Eaton Vance eids (19, 17940, 8459, 5282) are children of eid 2920 (2 open via `control`, 2 closed 2026-04-27). This is the cleanest M&A capture in the current graph and a useful template for Option C migrations.

---

## 7. Bundle B status — handoff to Bundles C and D

**Bundle B complete.** Material findings for chat review:

- **Phase 0.5:** Modified R5 validates cleanly; coverage-matrix double-count is a 2× fund-tier inflation defect (see §0.3).
- **Phase 1:** Tier inventory established. Capital Group is uniquely an umbrella; other firms use single-filer + brand-satellite shape.
- **Phase 2:** 21 cycle-truncated entity pairs surfaced (~10 merge candidates). 84K rollup gap is a **loader gap, not a rollup-builder gap** — entity_id IS NULL on every row. 4-5 operating-AM policy candidates (BoA, RBC, BNY, Manulife).
- **Phase 3:** Identifier coverage by tier mapped (LEI is 0% everywhere). 23 same-name-different-CIK pairs identified for follow-up. Adams cohort ≠ 120-row Layer A — only 1 likely Adams merge.
- **Phase 4:** Schema supports time-versioning; today's graph is time-invariant. Recommend Option C (hybrid: today + explicit M&A overrides) when historical data loads.

**Bundle C** (read/write audit + pipeline contracts + View 2 + securities canonical_type defect) needs:
- All 27 reader sites mapped against the modified R5 view (CP-5.2 prep)
- Pipeline contract audit (loader → securities → fund_holdings_v2 invariants)
- The 84K loader-gap fix sequencing (CIK relink + new entity creation)
- securities.canonical_type fix scope (institutional share classes mis-tagged COM — Bundle A §5)

**Bundle D** (synthesis) integrates A + B + C into the canonical CP-5 remediation plan.

---
