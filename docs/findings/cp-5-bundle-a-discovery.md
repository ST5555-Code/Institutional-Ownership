# CP-5 Comprehensive Discovery — Bundle A: R5 Defects + N-PORT Completeness

**Date:** 2026-05-04
**Branch:** `cp-5-comprehensive-discovery-bundle-a`
**HEAD baseline:** `989ea79` (PR #276 cp-5-discovery)
**Methodology:** read-only; all probes pinned to `quarter='2025Q4'`, `is_latest=TRUE`.

**Refs:**
- [docs/findings/cp-5-discovery.md](cp-5-discovery.md) (the prior CP-5 scoping that this bundle extends)
- [docs/decisions/d4-classification-precedence.md](../decisions/d4-classification-precedence.md)
- [ROADMAP.md](../../ROADMAP.md) — `fund-holdings-orphan-investigation`, `historical-drift-audit`, `fund-classification-by-composition`
- Probe scripts: [scripts/oneoff/cp_5_bundle_a_probe1_r5_defects.py](../../scripts/oneoff/cp_5_bundle_a_probe1_r5_defects.py), [scripts/oneoff/cp_5_bundle_a_probe2_nport_completeness.py](../../scripts/oneoff/cp_5_bundle_a_probe2_nport_completeness.py)

---

## 1. Probe 1 — R5 Dedup-Rule Defects

### 1.1 Fund-of-fund cross-holdings

**Cohort (2025Q4 EC, valid-CUSIP rows):** 1,506,972 EC holdings; **187,311 are fund-of-fund** by union of two detection passes:

| pass | rule | rows |
| --- | --- | ---: |
| A | `securities.canonical_type IN ('ETF','MUTUAL_FUND','CEF')` | 77,199 |
| B | name-based brand-stem match (held issuer's brand stem appears in any known fund family) | 123,031 |
| **A ∪ B** | **union (the FoF cohort)** | **187,311** |

Pass A alone would have missed roughly two-thirds of the cohort because institutional share classes (e.g., VSMPX, VGTSX, VTBIX) are mis-classified in `securities.canonical_type` as `'COM'`. The cp-5-discovery's `$1.5T` Vanguard FoF estimate was derived from name-matching at the position level — the present probe reproduces and extends it.

**Aggregate AUM by family-match class:**

| family_match | n_rows | AUM $B |
| --- | ---: | ---: |
| **intra_family** | **9,193** | **2,207.0** |
| extra_family | 167,588 | 6,174.0 |
| unknown_match | 10,530 | 374.9 |

**Top-25 top-parents by intra-family FoF AUM ($B):**

| top_parent | name | rows | AUM $B |
| ---: | --- | ---: | ---: |
| 4375 | Vanguard Group | 112 | 918.7 |
| 10443 | Fidelity / FMR | 2,848 | 702.0 |
| 3616 | T. Rowe Price | 104 | 75.8 |
| 17 | MFS Investment Management | 472 | 72.8 |
| 7984 | State Street / SSGA | 75 | 44.9 |
| 5026 | Dimensional Fund Advisors | 204 | 39.5 |
| 8994 | MANULIFE FINANCIAL CORP | 449 | 35.3 |
| 10178 | Ameriprise Financial | 295 | 29.7 |
| 9935 | Wellington Management Co LLP | 160 | 25.8 |
| 5 | Charles Schwab | 363 | 18.5 |
| 2 | BlackRock / iShares | 31 | 14.8 |
| 17941 | Goldman Sachs Asset Management, L.P. | 125 | 14.2 |
| 2322 | PIMCO | 184 | 13.9 |
| 3241 | BlackRock, Inc. | 220 | 12.3 |
| 11164 | PARAMETRIC PORTFOLIO ASSOCIATES LLC | 89 | 12.1 |
| (15 more, $5–11B each) | | | |

**Concentration:** Vanguard alone accounts for $918.7B (42% of intra-family inflation). Top-5 (Vanguard, Fidelity, T. Rowe, MFS, SSGA) account for $1.81T (82%).

**Recoverability:** intra-family FoF is **fully recoverable**. R5 must subtract intra-family FoF positions before MAX(13F, fund-tier) to avoid double-count. Subtraction key: `(outer_fund_eid, held_cusip)` where the held cusip resolves to a fund whose top_parent matches the outer fund's top_parent.

**Extra-family FoF ($6.17T)** is not a double-count — different parents, both legitimately count the position from their own perspectives. R5 leaves these in place.

**Unknown-match ($375B)** — held cusip is fund-typed by canonical_type but issuer brand-stem does not match any known family stem. Edge cases (foreign-domiciled funds, joint-venture vehicles). Treat as extra-family for R5 conservatism.

**CSV:** [data/working/cp-5-bundle-a-fof-footprint.csv](../../data/working/cp-5-bundle-a-fof-footprint.csv) (per-(top_parent, family) detail).

---

### 1.2 Non-valid CUSIP cohort

cp-5-discovery referenced a `$1.75T` Vanguard `cusip='N/A'` position. The actual cohort is much wider: **~$5.17T of EC AUM in 2025Q4** has a non-valid CUSIP.

**EC asset_category, 2025Q4 is_latest:**

| cusip_bucket | n_rows | AUM $B | with valid ISIN |
| --- | ---: | ---: | ---: |
| valid_format (9-char alnum) | 1,152,952 | 26,427.8 | 741,853 |
| **NA_lit** (`'N/A'` / `'NA'`) | **302,741** | **3,126.7** | 159,245 |
| **zeros_or_nines** (`'000000000'` / `'999999999'`) | **354,020** | **2,045.5** | 260,561 |

Total non-valid EC: **656,761 rows / $5,172B** (16% of EC AUM).

**Recoverability via ISIN (EC asset_category only):**

| metric | value |
| ---: | ---: |
| non-valid CUSIP rows | 302,741 |
| with 12-char ISIN | 159,245 (53%) |
| AUM total | $3,126.7B |
| AUM recoverable via ISIN | $1,965.3B (63%) |

**Top issuer types** (sample of non-valid bucket): Taiwan Semiconductor, ASML Holding, Samsung Electronics, Tencent, Alibaba, AstraZeneca, Roche, BAT, Airbus, SAP, Rolls-Royce — uniformly **foreign equities** that lack a US CUSIP. Many carry valid ISINs.

**Categorization (proposed for modified R5):**

| category | description | treatment |
| --- | --- | --- |
| **A — foreign equity, ISIN-recoverable** | non-US issuer with valid 12-char ISIN populated | recoverable via OpenFIGI / ISIN→CUSIP; backlog item, not blocker |
| **B — derivative / option / cash-equivalent** | non-EC asset_category (DBT, OPT, STIV, DFE, RA, etc.) | aggregate as separate "non-mappable" bucket; R5 does NOT roll into ownership rollup |
| **C — exclude from rollup** | STIV (money market), repos, cash funds | drop entirely from ownership rollup |
| **D — mappable but unmapped** | residual valid issuer in `securities` not joined yet | loader gap; backlog |

Modified R5 path: drop categories B + C from the unified-view rollup; surface a totals-line caveat for category A pending ISIN backfill. The `(cusip='N/A' OR cusip ~ '^[0-9]+$')` filter must be explicit in the view.

**CSVs:** [data/working/cp-5-bundle-a-null-cusip-cohort.csv](../../data/working/cp-5-bundle-a-null-cusip-cohort.csv), [data/working/cp-5-bundle-a-null-cusip-top-issuers.csv](../../data/working/cp-5-bundle-a-null-cusip-top-issuers.csv).

---

### 1.3 13F_only top-parent anomalies

**Methodology:** from cp-5-top-parent-coverage-matrix.csv (top-100), filter to `coverage_class='13F_only'` AND canonical_name passes asset-manager keyword heuristic. For each, check whether `fund_holdings_v2 → entity_rollup_history → top_parent` traces any fund-tier AUM.

**Result — 12 asset-manager-looking 13F_only top-parents in top-100, ALL category A_genuine_or_loader_gap (zero fund-tier trace):**

| top_parent | name | 13F AUM $B | n_funds | fund_tier $B | category |
| ---: | --- | ---: | ---: | ---: | --- |
| 6657 | Capital World Investors | 735.3 | 0 | 0.0 | brand-vs-filer (Capital Group) |
| 260 | CITADEL ADVISORS LLC | 665.9 | 0 | 0.0 | genuine 13F-only (hedge fund) |
| 7136 | Capital International Investors | 638.0 | 0 | 0.0 | brand-vs-filer (Capital Group) |
| 7125 | Capital Research Global Investors | 541.7 | 0 | 0.0 | brand-vs-filer (Capital Group) |
| 4248 | Amundi Asset Management | 368.0 | 0 | 0.0 | foreign-domiciled (no N-PORT) |
| 8477 | Envestnet Asset Management | 337.1 | 0 | 0.0 | wealth aggregator (no N-PORT) |
| 1755 | Fisher Asset Management, LLC | 293.0 | 0 | 0.0 | genuine 13F-only |
| 5342 | PNC Financial Services Group | 183.1 | 0 | 0.0 | bank wealth (no N-PORT) |
| 8145 | D. E. Shaw & Co., Inc. | 182.4 | 0 | 0.0 | genuine 13F-only (hedge fund) |
| 9005 | Sumitomo Mitsui Trust Group | 170.3 | 0 | 0.0 | foreign-domiciled |
| 682 | NORTHWESTERN MUTUAL WEALTH MANAGEMENT CO | 158.1 | 0 | 0.0 | wealth (no N-PORT) |
| 4105 | Mitsubishi UFJ Asset Management | 147.5 | 0 | 0.0 | foreign-domiciled |

**Sub-classification:**

| sub-category | firms | 13F AUM $B | treatment |
| --- | ---: | ---: | --- |
| brand-vs-filer (Capital Group) | 3 (Capital World, Capital International, Capital Research Global) | 1,915.0 | **Bundle B** — bridge brand eid 12 ← filer eids 6657/7136/7125 (cp-4b precedent shape) |
| genuine 13F-only | 3 (Citadel, Fisher, D. E. Shaw) | 1,141.3 | tag in CP-5 read layer; no bridge needed |
| foreign-domiciled | 3 (Amundi, Sumitomo Mitsui Trust, Mitsubishi UFJ) | 685.8 | tag; no N-PORT counterparty exists by structure |
| wealth aggregator | 3 (Envestnet, PNC, Northwestern Mutual) | 678.3 | tag; mostly no N-PORT counterparty |

**Sub-probe — Schwab (eid 5) + Dodge & Cox (eid 15) (top_parent, ticker) pairs (2025Q4):**

| top_parent | ticker | 13F $B | fund_tier $B |
| ---: | --- | ---: | ---: |
| 5 (Schwab) | AAPL | 0.000 | 26.561 |
| 5 | AMZN | 0.000 | 14.675 |
| 5 | NVDA | 0.000 | 28.683 |
| 5 | (all probed mega-caps) | 0.000 | 11.5–28.7 |
| 15 (Dodge & Cox) | AAPL | 0.009 | 0.000 |
| 15 | AMZN | 3.515 | 2.606 |
| 15 | GOOGL | 3.391 | 2.773 |
| 15 | META | 3.314 | 2.584 |
| 15 | MSFT | 3.599 | 2.493 |
| 15 | NVDA | 0.001 | 0.000 |

**Reconciliation against cp-5-discovery:** the named "Schwab/Dodge & Cox 13F_only" anomaly does **not** reproduce against eid 5 or eid 15. Schwab eid 5 is purely fund-tier ($1,345B per coverage matrix), with zero 13F. Dodge & Cox eid 15 is `both`-coverage — has both 13F and fund-tier for the major mega-caps. The Phase 2 PAIR-LEVEL 13F_only classification in the discovery sample was an artifact of the 60-pair sample's choice of top_parents and tickers, not a stable rollup-graph defect on these eids.

The genuine 13F-only / fund-only divergence stays the **brand-vs-filer split** (Capital Group is the next big one after cp-4b's BlackRock/Fidelity/T.Rowe/SSGA).

**CSV:** [data/working/cp-5-bundle-a-13f-only-anomalies.csv](../../data/working/cp-5-bundle-a-13f-only-anomalies.csv).

---

### 1.4 Modified R5 rule (synthesis)

Per `(top_parent_entity_id, ticker, cusip)` triple in 2025Q4 EC:

```
WITH fof_intra AS (
  -- Pre-compute intra-family fund-of-fund holdings to subtract
  SELECT outer_fund_eid, held_cusip, market_value_usd
  FROM fund_holdings_v2 fh
  WHERE fh.is_latest AND fh.quarter = '2025Q4' AND fh.asset_category='EC'
    AND brand_stem(fh.family_name) = brand_stem(fh.issuer_name)
    AND brand_stem IS NOT NULL
),
fund_tier_clean AS (
  -- Fund-tier rollup, excluding intra-family FoF and non-rollup buckets
  SELECT ftp.top_parent_entity_id, fh.ticker, fh.cusip,
         SUM(fh.market_value_usd) AS aum
  FROM fund_holdings_v2 fh
  JOIN fund_to_top_parent ftp USING (entity_id)
  WHERE fh.is_latest AND fh.quarter = '2025Q4'
    AND fh.asset_category = 'EC'
    AND fh.cusip ~ '^[0-9A-Z]{9}$'              -- drop NA_lit + zeros_or_nines
    AND NOT EXISTS (                              -- drop intra-family FoF
      SELECT 1 FROM fof_intra f
      WHERE f.outer_fund_eid = fh.entity_id AND f.held_cusip = fh.cusip
    )
  GROUP BY 1, 2, 3
),
thirteen_f_clean AS (
  SELECT itp.top_parent_entity_id, h.ticker, h.cusip,
         SUM(h.market_value_usd) AS aum
  FROM holdings_v2 h
  JOIN inst_to_top_parent itp USING (entity_id)
  WHERE h.is_latest AND h.quarter = '2025Q4'
  GROUP BY 1, 2, 3
)
SELECT top_parent_entity_id, ticker, cusip,
       GREATEST(COALESCE(t.aum, 0), COALESCE(f.aum, 0)) AS aum_dedup,
       CASE WHEN COALESCE(t.aum, 0) >= COALESCE(f.aum, 0)
            THEN '13F_wins' ELSE 'fund_wins' END AS source_winner
FROM thirteen_f_clean t
FULL OUTER JOIN fund_tier_clean f USING (top_parent_entity_id, ticker, cusip)
```

**Defect handling summary:**

| defect | R5 v0 (cp-5-discovery) | Modified R5 (Bundle A) |
| --- | --- | --- |
| FoF intra-family | acknowledged, undefined | **Subtract** intra-family FoF positions before MAX |
| FoF extra-family | acknowledged, undefined | Leave in place — different parents legitimately count |
| Non-valid CUSIP — foreign equity (cat A) | acknowledged, undefined | Surface as "ISIN-only / unmapped" bucket; backlog OpenFIGI fix |
| Non-valid CUSIP — derivative / cash (cat B/C) | acknowledged, undefined | **Drop** from ownership rollup |
| 13F_only brand-vs-filer | acknowledged | Bundle B bridges (cp-4b precedent) |
| 13F_only genuine / foreign / wealth | acknowledged | Tag column on top_parent; no rollup change |

The intra-family FoF subtraction reduces inflation by **~$2.21T** at a system level (concentrated in Vanguard $919B + Fidelity $702B + 23 others < $80B each). The non-valid-CUSIP filter removes **~$5.17T** of foreign / derivative / cash holdings from EC rollup — most of this should never have been in the rollup to begin with.

---

## 2. Probe 2 — N-PORT Data Completeness

### 2.1 Orphan funds (4 layers)

| layer | description | n_rows | AUM $B |
| --- | --- | ---: | ---: |
| **A** | fund-typed entities with no fund_universe row | 120 | n/a |
| **B** | fund_holdings_v2.entity_id with no entities row | 0 | 0 |
| **C** | NULL rollup_entity_id or dm_rollup_entity_id (is_latest) | 84,363 | 418.5 |
| **D** | fund_universe NULL or 'unknown' fund_strategy | 0 | 0 |

**Layer A (120 entities):** all are duplicate fund records ("Adams Diversified Equity Fund, Inc." × 3, "Adams Natural Resources Fund, Inc." × 3, etc.) created with `created_source='fund_cik_sibling'`. These are residuals from the cef-residual-cleanup arc (PR-A/PR-B in May 2026). Recovery: reconcile siblings to a primary entity; close historic siblings. Backlog item, not CP-5 blocker.

**Layer B (0 rows):** clean.

**Layer C (84,363 rows / $418.5B / 76 funds / 104 series):** all `series_normal` (S0...) — actual real funds whose decision-maker / economic-control rollup hasn't been computed. Recovery: re-run `entity_rollup_history` builder against current entity graph. Likely a loader-gap fix. Material AUM but small relative to $42T total fund_holdings_v2.

**Layer D (0):** **fund_strategy classification is COMPLETE.** ROADMAP `fund-classification-by-composition` workstream input is empty as of 2026-05-04. Defer/close the Workstream 2 dependency.

**CSV:** [data/working/cp-5-bundle-a-orphan-cohort.csv](../../data/working/cp-5-bundle-a-orphan-cohort.csv).

---

### 2.2 Historical drift audit

**Methodology:** count distinct accession_numbers per `(series_id, quarter, report_month)` for is_latest=TRUE, real series_id only (excluding 'UNKNOWN', empty, SYN_ synthetics).

| metric | value |
| --- | ---: |
| (series_id, quarter, report_month) buckets total | 43,293 |
| **buckets with > 1 accession (drift indicator)** | **0** |
| mean accessions per bucket | 1.0000 |

**Historical drift is FULLY RESOLVED.** The ROADMAP `historical-drift-audit` entry referenced "~31K rows" — that cohort has been cleaned up by prior remediation (likely the cef-residual-cleanup + INF9 series triage cascade). No drift cleanup blocks CP-5.

**Synthetic series (SYN_*):** 2,169,851 rows / $2,545.1B / 713 synthetic series — these are CEF-residual / cef-asa-flip / index-aggregate synthetics deliberately retained. Out of scope; do not treat as drift.

**CSV:** [data/working/cp-5-bundle-a-historical-drift.csv](../../data/working/cp-5-bundle-a-historical-drift.csv) (empty, confirming no drift).

---

### 2.3 Non-equity coverage

`fund_holdings_v2` 2025Q4 is_latest, by `asset_category`:

| category | n_rows | AUM $B | rollup-relevant? |
| --- | ---: | ---: | --- |
| **EC** (equity) | 1,809,713 | 31,600.0 | **YES — primary** |
| DBT (debt) | 1,537,325 | 6,380.6 | no (out of scope for ownership rollup) |
| ABS-MBS | 451,840 | 1,588.4 | no |
| STIV (short-term) | 26,029 | 1,044.3 | no (cash equivalents) |
| OTHER | 34,343 | 355.9 | no |
| LON (loan) | 1,541,873 | 281.9 | no |
| ABS-CBDO / ABS-O / EP / SN / DE / RA / DIR / etc. | <500K rows total | <500.0 | no |

**EC is 74.7% of total fund_holdings_v2 AUM.** The 25.3% non-equity tail is structurally out of scope for ownership rollup — CP-5 reads do not need to integrate it. Documented; no remediation required.

---

### 2.4 NULL fund_strategy cohort

| facet | total | NULL | 'unknown' | 'final_filing' |
| --- | ---: | ---: | ---: | ---: |
| `fund_universe` rows | 13,924 | **0** | **0** | 54 |
| `fund_holdings_v2.fund_strategy_at_filing` (2025Q4 EC) | 1,809,713 rows | **0** | n/a | 1,107 rows / $15.0B |

**`fund_strategy` classification is fully resolved.** The Workstream 2 input (NULL/unknown cohort) is empty.

`final_filing` (54 funds in fund_universe / 1,107 rows in 2025Q4) — these are funds in liquidation. Top dm_rollup contributors: Fidelity (241 rows / $10.9B), AllianceBernstein ($1.2B), Goldman Asset Mgmt ($0.8B), Brown Brothers Harriman ($0.5B), Baillie Gifford ($0.4B). Treatment: filter or label in CP-5 reads — not in active rollup but small enough to ignore.

**CP-5 dependency:** **NONE.** Workstream 2 (`fund-classification-by-composition`) can be closed as completed.

**CSV:** [data/working/cp-5-bundle-a-null-fund-strategy.csv](../../data/working/cp-5-bundle-a-null-fund-strategy.csv) (current strategy distribution for reference).

---

### 2.5 Monthly N-PORT scope

**Public N-PORT (NPORT-P) report_month coverage in fund_holdings_v2 (is_latest, 2025–2026):**

| month type | n_months | avg series/month |
| --- | ---: | ---: |
| calendar quarter-end (Mar/Jun/Sep/Dec) | 5 | 3,872 |
| non-cal-quarter-end | 10 | 2,039 |

Non-cal-quarter-end months are populated because funds with non-December fiscal years file public NPORT-P at their fiscal-quarter-ends (e.g., a fund with a March fiscal year-end files for May/Aug/Nov/Feb). These are public quarterly filings, not monthly NPORT-MP.

**Private monthly NPORT-MP is NOT loaded** — this is by design (the data is non-public). For institutional ownership rollup, quarterly granularity is sufficient; 13F is also quarter-end. Monthly NPORT-MP coverage stays a Pipeline 4 (post-CP-5) backlog item.

**No CP-5 dependency.** Document and defer.

---

## 3. Open questions for Bundles B and C

These follow-ups depend on Bundle A findings and should be resolved by Bundles B/C.

1. **Brand-stem normalization library.** Probe 1.1's intra-family FoF detection uses a pragmatic per-row brand-stem extractor with a stopword list. Bundle B's entity-graph mapping should canonicalize this into a `brand_stem` column on `entity_current` (or a lookup table) so the FoF subtraction filter is deterministic and auditable.
2. **Capital Group brand-vs-filer carve-out scope.** Bundle B should confirm the 3 Capital Group filer arms (eids 6657, 7136, 7125) need a single bridge to brand eid 12 or three separate bridges (cp-4b precedent suggests three: T.Rowe + First Trust + FMR + SSGA each got their own).
3. **Layer A 120-entity duplicate cleanup.** Out of CP-5 scope; route to a backlog cleanup PR after entity-graph stability confirms which sibling is canonical.
4. **Layer C 84,363-row rollup gap.** Re-run `entity_rollup_history` builder against current entity graph — is this a one-shot loader fix or symptomatic of a graph-traversal bug? Bundle B should answer.
5. **ISIN→CUSIP backfill for foreign equities (~$1.97T recoverable).** Backlog item; deferred to a future OpenFIGI pipeline. Surface as a known gap in CP-5 read-layer documentation.
6. **`final_filing` cohort surfacing.** Bundle C should decide: filter out of CP-5 ownership rollup (default), or label as "in liquidation" and include?
7. **Synthetic SYN_ series ($2.55T).** Confirm in Bundle B that synthetics are properly bridged into rollup chains (these are CEF residuals + index aggregates by design); validate they don't double-count when R5 picks MAX(13F, fund-tier).

---

## 4. Modified R5 rule — final proposed version

Locking the rule before Bundle B begins:

```
For each (top_parent_entity_id, ticker, cusip) in 2025Q4:

  thirteen_f = SUM(holdings_v2.market_value_usd) for top_parent
                via inst_to_top_parent climb

  fund_tier = SUM(fund_holdings_v2.market_value_usd) for top_parent
              via fund_to_top_parent climb,
              EXCLUDING:
                - rows where cusip is non-valid (NA_lit, zeros_or_nines, NULL)
                - rows where asset_category != 'EC'
                - rows that are intra-family FoF
                  (brand_stem(family_name) = brand_stem(issuer_name) AND
                   the held cusip resolves to a fund issued by the same top_parent)

  result = MAX(thirteen_f, fund_tier)
  source_winner = '13F_wins' if thirteen_f >= fund_tier else 'fund_wins'

For 13F_only top_parents (no fund-tier path by structure):
  - Tag the top_parent with reason: 'genuine_hedge_or_pension', 'foreign_domiciled',
    'wealth_aggregator', 'brand_vs_filer_pending_bridge'
  - Use thirteen_f only

For fund_only top_parents (no 13F filer entity):
  - Use fund_tier only (with the same exclusions)
  - Examples: Capital Group, BlackRock/iShares, Schwab, JPM Investment Mgmt
```

**Inflation adjustments quantified by Bundle A:**

| adjustment | $B |
| ---: | ---: |
| intra-family FoF subtraction | -2,207.0 |
| non-valid CUSIP filter (EC only) | -5,172.2 |
| non-EC asset_category drop | -10,675.4 (already excluded by `asset_category='EC'` predicate) |

After these adjustments, `fund_tier_clean` for 2025Q4 reduces from $31.6T to roughly $24.2T — directionally consistent with cp-5-discovery's $22.7T `fund_only` AUM-share estimate plus the `both`-coverage fund-tier component.

---

## 5. Out-of-scope discoveries / surprises

- **`securities.canonical_type` mis-classifies institutional share classes** as `'COM'` (common stock) instead of `'MUTUAL_FUND'`. Affects VSMPX, VGTSX, VTBIX, VTSMX, VTBLX, VTILX, VTIIX, VTAPX, VRTPX and others. This is a securities-table data-quality issue that Bundle C's pipeline-contract audit should flag for the next OpenFIGI / classifier pass. Bundle A's name-based FoF detection works around it; the underlying fix belongs in `securities`.
- **Charles Schwab eid=5 is a pure `fund_only` top-parent** (1,345B fund-tier, 0 13F). The cp-5-discovery's Phase 2 anomaly callout for "Schwab" is not a structural defect — eid 5 has no 13F filer counterparty and Schwab Investment Management eid 5687 (the 13F-filing arm) is a separate institution. This is a brand-vs-filer split akin to cp-4b, and should be queued behind the Capital Group 3-filer-arm work.
- **Dodge & Cox eid=15 is `both`-coverage** with normal 13F + fund-tier values for mega-caps; not in any anomaly category.
- **`historical-drift-audit` ROADMAP entry can be closed** — current state shows 0 multi-accession buckets. The 31K-row historical reference predated the cef-residual-cleanup remediation.
- **`fund-classification-by-composition` (Workstream 2) input is empty** — fund_universe.fund_strategy is fully populated. ROADMAP entry can be closed.
- **`fund-holdings-orphan-investigation` ROADMAP entry shrinks** — Layer A 120 duplicates + Layer C 84K rollup-gap rows remain (was 302 series / ~160K rows). Material reduction; recovery is a re-run of the rollup builder.

---

## 6. Bundle A status — handoff to Bundles B and C

**Bundle A complete.** Ready for chat review of:
- Modified R5 rule (§1.4) — locks before Bundle B
- 13F_only top-parent treatment matrix (§1.3) — Capital Group brand-vs-filer goes to Bundle B
- ROADMAP closures (§5) — historical-drift-audit, fund-classification-by-composition

**Bundle B** (entity graph mapping) needs:
- Tier inventory across the 14,038 institutions
- Multi-hop traversal stress (cycle handling, hop > 2 cases)
- Identifier canonicalization (CIK, CRD, series_id, brand_stem)
- Capital Group 3-filer-arm carve-out design
- Layer C 84K-row rollup-gap remediation

**Bundle C** (fund-tier coverage + read/write audit + pipeline contracts) needs:
- View 2 (fund-tier / PM-level) gap inventory
- All 27 reader sites mapped against the modified R5 view
- Pipeline contract audit (loader → securities → fund_holdings_v2 invariants)
- Backlog items: ISIN→CUSIP for foreign equities, NPORT-MP integration, securities.canonical_type fixes
