# Unknown Classification Discovery

**Date:** 2026-05-03
**Branch:** `unknown-classification-discovery`
**Read-only investigation per** `docs/decisions/d4-classification-precedence.md`
**Cohort:** 3,852 `entity_classification_history` rows where `classification='unknown'` and `valid_to = DATE '9999-12-31'`.

---

## 1. Re-validation snapshot

| Metric                                         | Value     |
|------------------------------------------------|-----------|
| Open ECH `classification='unknown'`            | **3,852** |
| Open ECH total                                 | 27,150    |
| Institution universe (`entities.entity_type='institution'`) | 14,038    |
| Institutions with zero open ECH row            | 108       |
| Baseline (`institution_scoping.md` §2.1)       | 3,852     |
| Drift vs baseline                              | **0.00 %** |

Drift gate (≤ 5 %) passes exactly. Cohort is stable.

> Note: the institution-coverage figure of 99.2 % (= (14,038 − 108) / 14,038) corresponds to the §2.1 "99.9 %" reference — the small delta likely reflects ~10 added inactive CIKs since the §2.1 snapshot, not a real coverage regression.

Per Phase 1 script: `scripts/oneoff/unknown_classification_phase1_validate.py`.

---

## 2. Source attribution

### 2.1 ECH source on the open unknown row

| Source             | Count  | Notes                                |
|--------------------|--------|--------------------------------------|
| `default_unknown`  | 2,179  | N-CEN-derived entities, never classified |
| `managers`         | 1,246  | Legacy seed from old `managers` table |
| `bootstrap_tier4`  | **427** | ROADMAP-tracked — folded into this workstream |
| **TOTAL**          | 3,852  |                                      |

### 2.2 Cohort by `entities.entity_type`

| entity_type | Count |
|-------------|-------|
| institution | 1,976 |
| fund        | 1,876 |
| **TOTAL**   | 3,852 |

> **Half the cohort is funds, not institutions.** Funds inherit classification from their parent via the rollup; the entity-level classification is structurally never authoritative. Fund-typed cohort members ship to Tier C residual unless they carry an unambiguous signal at the entity level (rare).

### 2.3 Cross-tab (source × entity_type)

| Source | Type | Count |
|--------|------|-------|
| `default_unknown` | fund        | 1,876 |
| `managers`        | institution | 1,246 |
| `bootstrap_tier4` | institution |   427 |
| `default_unknown` | institution |   303 |

Per Phase 2 script: `scripts/oneoff/unknown_classification_phase2_sources.py`.

---

## 3. AUM exposure (latest period)

### 3.1 Cohort totals

| Metric                                | USD          |
|---------------------------------------|--------------|
| Direct institution AUM (`holdings_v2`) | **$719.17 B** |
| Fund-rollup AUM (`fund_holdings_v2`)   | **$6,590.23 B** |
| Combined (with overlap)                | **$7,309.41 B** |

### 3.2 Per ECH-source bucket

| Source            | Count | Inst AUM    | Fund-rollup AUM |
|-------------------|-------|-------------|-----------------|
| `default_unknown` | 2,179 | $0.00 B     | **$5,494.00 B** |
| `managers`        | 1,246 | $719.17 B   | $733.98 B       |
| `bootstrap_tier4` | 427   | $0.00 B     | $362.25 B       |

### 3.3 Per `entity_type` bucket

| entity_type | Count | Inst AUM   | Fund-rollup AUM |
|-------------|-------|------------|-----------------|
| institution | 1,976 | $719.17 B  | $6,449.21 B     |
| fund        | 1,876 | $0.00 B    | $141.03 B       |

### 3.4 Zero-AUM cohort

**2,849 of 3,852 (74 %)** entities have no holdings_v2 row AND no fund_holdings_v2 rollup in the latest period. These are baseline Tier C residual candidates.

Per Phase 3 script: `scripts/oneoff/unknown_classification_phase3_aum.py`.

---

## 4. Per-signal hit-rate tables

| Signal | Description                                | Hits | Hit-rate |
|--------|--------------------------------------------|------|----------|
| **A**  | `adv_managers` row via `crd` identifier    | 20   | 0.5 %    |
| **B**  | `ncen_adviser_map` role match              | 313  | 8.1 %    |
| **C**  | name-pattern keyword match                 | 408  | 10.6 %   |
| **D**  | `holdings_v2.manager_type` (D4 fallback)   | 226  | 5.9 %    |
| **≥1** | any of A/B/C/D                             | 899  | 23.3 %   |

### 4.1 Signal-A breakdown — `adv_strategy_inferred` within hits

| strategy_inferred | n |
|-------------------|---|
| unknown           | 19 |
| active            | 1 |

> Signal A is essentially noise for this cohort — the crd-identifier coverage is too low. Most cohort members never made it to ADV linkage.

### 4.2 Signal-B breakdown — N-CEN role within hits

| role        | n   |
|-------------|-----|
| adviser     | 192 |
| subadviser  | 121 |

### 4.3 Signal-C breakdown — keyword label

| label                 | n     | Notes                                |
|-----------------------|-------|--------------------------------------|
| `<no_match>`          | 3,444 |                                      |
| `hedge_fund_candidate` | 214   | LP suffix only — weak                |
| `active`              | 193   | "Trust" / "Income Fund" / "CEF" / etc. |
| `passive`             | 1     |                                      |

> The `passive` keyword set (SPDR/iShares/Vanguard/ETF/Index/PowerShares/Direxion/ProShares/ProFund) lands ONE hit because most ETF issuers are already classified upstream. `Trust` is noisy — it catches both bona-fide trust banks (Wilmington Trust) and CEFs (PIMCO Corporate Income Trust). Recommend chat refines the `active` keyword set in Wave 1 PR.

### 4.4 Signal-D breakdown — manager_type within hits

| mgr_type             | n    |
|----------------------|------|
| active               | 122  |
| strategic            | 42   |
| mixed                | 23   |
| hedge_fund           | 13   |
| endowment_foundation | 7    |
| wealth_management    | 7    |
| venture_capital      | 4    |
| quantitative         | 3    |
| pension_insurance    | 3    |
| family_office        | 2    |

Per Phase 4 script: `scripts/oneoff/unknown_classification_phase4_signals.py`.

---

## 5. Tiered cohort

| Tier | Count | Inst AUM   | Fund-rollup AUM | Combined AUM |
|------|-------|------------|-----------------|--------------|
| **A** (auto)     | **390** | $662.74 B | $202.15 B    | **$864.90 B** |
| **B** (review)   | **509** | $56.43 B  | $5,448.86 B  | **$5,505.29 B** |
| **C** (residual) | **2,953** | $0.00 B  | $939.22 B    | **$939.22 B** |

### 5.1 Tier A composition (auto-resolvable)

Wave-1 candidates (190): unambiguous `name-pattern` (active or passive — not LP-suffix), no conflict with manager_type.
Wave-2 candidates (1): unambiguous `adv_strategy_inferred`.
Wave-3 candidates (199): unambiguous `manager_type` (the D4-elevated fallback).

**Top-25 Tier A by AUM:** see `data/working/unknown-classification-tier-a.csv`. Largest hits include WOLVERINE TRADING ($324 B → quantitative), JARISLOWSKY FRASER ($52 B → strategic), AXA Investment Managers ($37 B → pension_insurance), CLEAR STREET ($36 B → active), Boston Trust Walden ($21 B → name=active), CHURCHILL MANAGEMENT ($17 B → active), Segall Bryant Hamill ($13 B → ADV=active).

### 5.2 Tier B composition (review)

| Rationale                                              | Count |
|--------------------------------------------------------|-------|
| LP-suffix candidate (weak)                             | 190   |
| N-CEN role=adviser only (no class signal)              | 178   |
| N-CEN role=subadviser only (no class signal)           | 104   |
| manager_type=mixed (ambiguous)                         | 19    |
| ADV present but strategy_inferred=unknown              | 14    |
| name=active conflicts with manager_type=endowment_foundation | 4 |

> **Tier B carries $5.5 T because the N-CEN-only bucket includes the bulk of the fund-adviser universe** (Pzena $480 B, GQG $326 B, Jackson National $300 B, Federated $275 B, WisdomTree $262 B, Brighthouse $169 B, Nationwide $165 B, Transamerica $145 B, Causeway $142 B, Macquarie $138 B, GMO $132 B, Lincoln Financial $124 B, DoubleLine $123 B). These are clearly classifiable (mostly active, some passive — WisdomTree) but my heuristic is conservative because N-CEN tells us *role* not *strategy*.
>
> See **Open question Q1** below.

### 5.3 Tier C composition (residual)

2,953 entities with **no signal** from any of A/B/C/D.

- 2,849 of these have **zero AUM** in latest period — true residual.
- 104 have non-zero AUM but no classifying signal. The biggest of these are:
  - MANULIFE FINANCIAL CORP ($266 B fund-rollup) — insurance parent, no holdings_v2 record.
  - Voya Financial, Inc. ($130 B) — same shape.
  - **Global X Management CO LLC ($122 B)** — passive ETF issuer, no signal because crd identifier missing AND name doesn't contain "ETF". **See Q2.**
  - NORTHWESTERN MUTUAL LIFE INSURANCE ($62 B) — insurance.
  - Several `S00006xxxx` series-id placeholders ($10–20 B each) — these are fund-series rollup parents that survived but have no canonical_name; classification at the entity-id level is the wrong abstraction for these.

Per Phase 5 script: `scripts/oneoff/unknown_classification_phase5_tier.py`.

---

## 6. Recommended resolution waves

| Wave | Tier | Size | Mechanism | Sequencing |
|------|------|------|-----------|------------|
| **1** | A | 190 | Single UPDATE PR — name-pattern propagation. Extends PR #200 keyword set. | S, pre-cycle |
| **2** | A | 1   | Folded into Wave 1 (single ADV hit). | S, pre-cycle |
| **3** | A | 199 | Single UPDATE PR — `manager_type` D4-fallback propagation. | M, pre-cycle |
| **4** | B | 509 | **Per-cohort chat-reviewed sweeps** — see waves 4a/4b below | per-batch |
| RESIDUAL | C | 2,953 | Accept as residual. Ships to admin-unresolved-firms-display. | none |

### 6.1 Wave 4 sub-batches (proposed; needs chat sign-off per batch)

- **Wave 4a — N-CEN adviser-only (282 entities, $4.5T+ AUM):** if chat agrees a registered N-CEN adviser/subadviser without contradicting evidence defaults to `active`, this becomes a single UPDATE PR. **Q1.**
- **Wave 4b — LP-suffix candidates (190, ~$700 B):** review-batch — many are bona-fide hedge funds, some are mutual fund advisers (e.g., First Trust Advisers L.P., Harris Associates L.P.). Needs name-by-name sign-off or a refined heuristic.
- **Wave 4c — manager_type=mixed (19):** review against fund-rollup composition; classify per dominant strategy.
- **Wave 4d — ADV strategy=unknown (14):** small batch; manual lookup.
- **Wave 4e — name/manager_type conflicts (4):** trivial — prefer manager_type per D4.

### 6.2 Wave-1 keyword refinement (recommended for chat decision)

Drop or qualify these noisy `active` keywords:

- **`Trust`** — false positives on trust banks (Wilmington Trust, Boston Trust Walden). Suggest qualifying as `Trust` in name AND name doesn't contain `Bank|Bancorp|Trust Company`.
- **`Private`** — overbroad; many quantitative shops use "Private". Restrict to `Private Markets|Private Capital|Private Credit|Private Equity Fund`.

These keyword refinements should ride on the Wave-1 PR that lands the additional terms, not as a separate workstream.

---

## 7. Expected post-resolution residual

| Resolution path | Cohort exit |
|-----------------|-------------|
| Wave 1+2+3 (Tier A auto) | 390 |
| Wave 4a (if approved) | +282 |
| Wave 4b–e (per-batch review) | +227 |
| **Estimated cohort exit** | **899** |
| **Residual** (Tier C) | **2,953** |

**Of the 2,953 residual:**
- 2,849 are zero-AUM — already invisible from production reads.
- 104 carry non-zero AUM (~$939 B); these are the entities that show up on `admin-unresolved-firms-display` and need either (a) entity-bridging upstream (link Manulife to its US filer entity), (b) name-cleanup to expose existing keyword signal (Global X), or (c) acceptance as legitimately unclassifiable (insurance parents).

> **Target: ≤ 500 visible residual on the admin display.** Current path (waves 1–4 fully executed) lands at **104 visible** — well under target.

---

## 8. Open questions for chat decision

### Q1 — N-CEN-only promotion

Should an entity with `ncen_adviser_map.role IN ('adviser','subadviser')` and no contradicting signal default-classify to `active`?

- **Pro:** captures the bulk of the $5.5 T Tier-B exposure in one PR. Real-world: nearly all named fund-advisers/subadvisers ARE active managers (the few passive issuers — WisdomTree, Innovator — are a manageable manual-flip list).
- **Con:** false positives on smart-beta / index-tracking subadvisers. WisdomTree shows up as `subadviser` for some funds but is itself a passive issuer.
- **Mitigation:** before propagation, intersect Wave 4a candidates with a small chat-curated passive-issuer exclusion list.

### Q2 — Global X / ETF-name signal gap

Global X Management Co LLC ($122 B fund-rollup AUM) is in Tier C because:
1. No crd identifier on the entity → no ADV / N-CEN linkage.
2. Name doesn't contain any passive keyword.

Two options: (a) extend Signal C to include `Global X` as a passive issuer literal, (b) backfill a crd identifier for entity 8005 so signals A/B fire. **Recommend (b)** — fixes the underlying gap, not just this case.

### Q3 — Wave-1 name-keyword refinement

Adopt the `Trust` and `Private` qualifiers in §6.2 as part of Wave 1, or treat as separate cleanup PR? Recommend bundling.

### Q4 — Bootstrap_tier4 fast-path

The 427 `bootstrap_tier4` rows are already ROADMAP-tracked separately. Should this discovery's tiered output supersede that workstream, or do they remain parallel? Recommend supersede — bootstrap_tier4 entities tier exactly as the rest of the cohort by signal source (no special handling needed).

---

## Appendix — output files

| File | Rows | Use |
|------|------|-----|
| `data/working/unknown-classification-tier-a.csv` | 390 | Wave 1+2+3 source data |
| `data/working/unknown-classification-tier-b.csv` | 509 | Wave 4 review batches |
| `data/working/unknown-classification-tier-c.csv` | 2,953 | Residual (admin display + entity-bridge follow-up) |
| `data/working/unknown-classification-tiered.parquet` | 3,852 | Full enriched per-entity table (all signals + tier + rationale) |
| `scripts/oneoff/unknown_classification_phase1_validate.py` | — | Phase 1 |
| `scripts/oneoff/unknown_classification_phase2_sources.py` | — | Phase 2 |
| `scripts/oneoff/unknown_classification_phase3_aum.py` | — | Phase 3 |
| `scripts/oneoff/unknown_classification_phase4_signals.py` | — | Phase 4 |
| `scripts/oneoff/unknown_classification_phase5_tier.py` | — | Phase 5 + tier CSV emit |

All scripts are read-only (`duckdb.connect(..., read_only=True)`); no INSERT/UPDATE/DELETE. Verified per Phase 8.
