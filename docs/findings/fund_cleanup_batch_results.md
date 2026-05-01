# Fund-Cleanup Batch — Results

**Branch:** `fund-cleanup-batch`
**HEAD at start:** `7fa92ff` (conv-23-doc-sync)
**Backup:** `data/backups/13f_backup_20260501_103837` (3.2 GB, PR-4 backup)
**Scope:** Combined cleanup session covering 4 fund-level items (3 read-only audits + 1 targeted reclassification). Not part of the formal PR-N sequence; closes 4 items surfaced during the PR-1a → PR-4 fund-level consolidation.

Items closed:

1. `canonical-value-coverage-audit` — quantify NULL/orphan/drift across the canonical layer
2. `verify-blackrock-muni-trust-status` — verify 12 BlackRock muni trusts (active vs. liquidated)
3. `verify-proshares-short-classification` — verify ~51 ProShares short funds taxonomy
4. `review-active-bucket` — audit 3,184 UNKNOWN orphans + 8 named CEFs; reclassify 2 confirmed credit funds

---

## 1. Canonical Value Coverage Audit (Phase 1)

Eight read-only queries against prod (`data/13f.duckdb`, 2026-05-01 pre-Phase-4c).

### 1a. NULL `fund_strategy` in `fund_universe`

| metric | value | status |
|---|---:|---|
| NULL fund_strategy rows | 0 | PASS — invariant from PR-1a holds |

### 1b. Orphan series — `fund_holdings_v2` rows with no `fund_universe` row — **NEW UNANTICIPATED FINDING**

| metric | value |
|---|---:|
| orphan_holdings_rows | **160,934** |
| orphan_series_count | **302** |

The plan anticipated only the 3,184 `UNKNOWN`-sentinel rows (PR-1a §3.4). The audit found **301 additional series_ids** with real-looking IDs (e.g. `S000009238`) that have `fund_holdings_v2` rows but no matching `fund_universe` entry. Top 10:

| series_id | sample fund_name | rows |
|---|---|---:|
| S000009238 | Tax Exempt Bond Fund of America | 10,606 |
| S000009229 | American High-Income Municipal Bond Fund | 7,418 |
| S000045538 | Blackstone Alternative Multi-Strategy Fund | 7,152 |
| S000009231 | Bond Fund of America | 5,801 |
| S000008396 | VOYA INTERMEDIATE BOND FUND | 5,016 |
| S000029560 | AB Municipal Income Shares | 4,654 |
| S000002536 | MFS Municipal Income Fund | 4,384 |
| S000062381 | Advantage CoreAlpha Bond Master Portfolio | 4,152 |
| S000008760 | VOYA INTERMEDIATE BOND PORTFOLIO | 3,905 |
| S000009237 | Limited Term Tax Exempt Bond Fund of America | 3,843 |

These rows currently flow into the **NULL arm of the `cross.py` 3-way `CASE`** (1h confirms 160,934 NULL-arm rows on latest holdings — the count matches 1b exactly). Front-end logic treats `NULL → None → "active"`, so all 160,934 holdings rows on these 301 valid-looking series are silently included in active-only views.

Captured as new P2 roadmap item `fund-holdings-orphan-investigation`.

### 1c. UNKNOWN orphan rows by snapshot strategy

| fund_strategy_at_filing | rows |
|---|---:|
| active | 3,184 |

All 3,184 currently `active` — consistent with PR-1a §3.4 orphan-policy `equity → active` mapping (post-PR-4 rename).

### 1d. SYN funds — canonical vs. snapshot drift on latest holdings

| metric | value |
|---|---:|
| total SYN latest-holding rows | 2,169,501 |
| disagreement rows | 9,405 |
| disagreement series | 32 |

Matches the 32 SYN drifters documented in PR-1a §2.3 verbatim. The drift is harmless at runtime — `compute_peer_rotation.py` reads canonical via the PR-4 LEFT JOIN; the snapshot column preserves the at-filing classifier output by design.

### 1e. 12 BlackRock muni trusts on `final_filing`

All 12 confirmed:

| series_id | fund_name | latest_quarter |
|---|---|---|
| SYN_0001137391 | BlackRock California Municipal Income Trust | 2026Q1 |
| SYN_0000894242 | BlackRock Investment Quality Municipal Trust, Inc. | 2026Q1 |
| SYN_0001343793 | BlackRock Long-Term Municipal Advantage Trust | 2026Q1 |
| SYN_0001038186 | BlackRock MuniHoldings New York Quality Fund, Inc. | 2026Q1 |
| SYN_0001071899 | BlackRock MuniHoldings Quality Fund II, Inc. | 2026Q1 |
| SYN_0000897269 | BlackRock MuniVest Fund II, Inc. | 2026Q1 |
| SYN_0000835948 | BlackRock MuniVest Fund, Inc. | 2026Q1 |
| SYN_0000879361 | BlackRock MuniYield Fund, Inc. | 2026Q1 |
| SYN_0000887394 | BlackRock MuniYield Quality Fund II, Inc. | 2026Q1 |
| SYN_0001137393 | BlackRock Municipal Income Trust | 2026Q1 |
| SYN_0001176194 | BlackRock Municipal Income Trust II | 2026Q1 |
| SYN_0001137390 | BlackRock New York Municipal Income Trust | 2026Q1 |

### 1f. ProShares short / inverse / bear funds

51 funds returned (full list in `/tmp/phase1_audit.log`). Split four ways:

| current fund_strategy | n_funds |
|---|---:|
| bond_or_other | ~24 |
| passive | ~14 |
| excluded | ~13 |
| **total** | **51** |

### 1g. Holdings-layer drift — canonical vs. snapshot — STOP gate triggered

| metric | value |
|---|---:|
| total holdings rows (joined) | 14,407,841 |
| divergent rows (any) | 40,843 |
| divergent rows (`is_latest=TRUE`) | **40,843** |

Plan threshold: 5,000. Observed: 40,843 (~8x). After chat review:

- 9,405 of the 40,843 are the documented 32 SYN drifters from §1d.
- ~31,400 remaining are non-SYN holdings rows — same shape (snapshot disagreeing with canonical) but for series that classified into `fund_universe` cleanly.
- Drift is harmless at runtime: PR-4's JOIN architectural fix in `compute_peer_rotation.py:421-449` makes `_materialize_fund_agg` LEFT JOIN `fund_universe.fund_strategy`; the snapshot column is preserved by design as `fund_strategy_at_filing` (snapshot semantics, intentional).

Captured as new P3 roadmap item `historical-fund-holdings-drift-audit`.

### 1h. `cross.py` 3-way CASE branch coverage on latest holdings

| arm | rows |
|---|---:|
| total latest holdings | 14,568,704 |
| NULL arm (`fund_strategy IS NULL`) | 160,934 |
| active arm (`active`/`balanced`/`multi_asset`) | 5,236,150 |
| passive arm (`passive`/`bond_or_other`/`excluded`/`final_filing`) | 9,171,620 |

**NULL arm rows (160,934) match 1b orphan-row count exactly.** The 3-way `CASE` returns `NULL` for those rows; the front-end maps `None → "active"`. This is the code path through which 1b's 301-series cohort silently surfaces in active-only views.

### 1 — Conclusions

- 1g (40,843 drift latest-only) is **harmless at runtime** because PR-4's JOIN serves canonical; the holdings-layer snapshot column is intentionally preserved as `fund_strategy_at_filing` (snapshot semantics). The original 5,000 threshold was set conservatively assuming SYN drift only; observed pattern matches expected pre-lock historical writes.
- 1b (302 orphan series, 160,934 holdings rows) is a **new finding not anticipated** by the plan. These are real-looking series_ids that lack `fund_universe` rows; their holdings flow into the NULL arm of `cross.py`'s 3-way CASE and are treated as "active" by front-end logic. Captured as P2 follow-up.
- All other Phase 1 checks (1a, 1c, 1d, 1e, 1f, 1h) match expectation.

---

## 2. BlackRock Muni Trust Verification (Phase 2)

All 12 BlackRock muni trusts verified via SEC EDGAR Form 25-NSE delistings (wave 1) and BusinessWire merger-completion press releases (wave 2). Verification approach: pulled EDGAR submissions API for all 12 CIKs and cross-referenced surviving acquirer funds in the BlackRock press releases.

| # | fund_name | ticker | merger_close | survivor | recommendation |
|---|---|---|---|---|---|
| 1 | BlackRock California Municipal Income Trust | BFZ | 2026-02-09 | MUC | keep `final_filing` |
| 2 | BlackRock Investment Quality Municipal Trust | BKN | 2026-02-23 | MQY | keep `final_filing` |
| 3 | BlackRock Long-Term Municipal Advantage Trust | BTA | 2026-02-23 | MUA | keep `final_filing` |
| 4 | BlackRock MuniHoldings New York Quality Fund | MHN | 2026-02-09 | MYN | keep `final_filing` |
| 5 | BlackRock MuniHoldings Quality Fund II | MUE | 2026-02-23 | MHD | keep `final_filing` |
| 6 | BlackRock MuniVest Fund II | MVT | 2026-02-23 | MYI | keep `final_filing` |
| 7 | BlackRock MuniVest Fund | MVF | 2026-02-23 | MYI | keep `final_filing` |
| 8 | BlackRock MuniYield Fund | MYD | 2026-02-23 | MQY | keep `final_filing` |
| 9 | BlackRock MuniYield Quality Fund II | MQT | 2026-02-23 | MQY | keep `final_filing` |
| 10 | BlackRock Municipal Income Trust | BFK | 2026-02-23 | MHD | keep `final_filing` |
| 11 | BlackRock Municipal Income Trust II | BLE | 2026-02-23 | MHD | keep `final_filing` |
| 12 | BlackRock New York Municipal Income Trust | BNY | 2026-02-09 | MYN | keep `final_filing` |

**Verdict:** all 12 funds confirmed terminated via merger; `final_filing` classification is correct for all 12. **No reclassifications warranted.** STOP gate not triggered.

NPORT-P (2026-03-26) and N-CSRS (2026-04-07) on the merged CIKs are post-merger residual administrative filings (final-period reports), consistent with terminated-trust wind-down — not signs of ongoing operations.

Sources:
- [BlackRock Completes Muni CEF Reorgs (2026-02-09)](https://www.businesswire.com/news/home/20260209155153/en/)
- [BlackRock Completes Muni CEF Reorgs (2026-02-23)](https://www.businesswire.com/news/home/20260223661532/en/)

---

## 3. ProShares Short Classification Review (Phase 3)

Research dispatched against three representative funds (SQQQ, SH, TBF) covering prospectus mechanics, N-PORT holdings shape, and industry classification.

### 3a. Index-tracking mechanic

All ProShares short / inverse / leveraged-short ETFs **explicitly track named indexes in their prospectuses** (Nasdaq-100, S&P 500, ICE 20+ Year US Treasury, etc.). Holdings are determined mechanically by inverting the published rules-based index — no security-selection discretion. Prospectus "Correlation Risk" language confirms the manager's only role is engineering derivative exposure to mirror the inverse benchmark.

### 3b. N-PORT holdings shape

Inverse exposure is engineered almost entirely via total-return swap agreements (and some futures), collateralized by cash + short-dated U.S. Treasury bills. Equity-tracking inverse funds (SQQQ, SH) hold essentially zero direct equity — line items are swap notionals plus T-bill / cash collateral. Treasury-tracking inverse funds (TBF) are structurally identical: swaps + T-bill collateral, **not long-Treasury exposure** — the Treasuries on the balance sheet are collateral, not the investment thesis.

### 3c. Industry classification

Morningstar classifies all three funds as "passively managed" / "Trading-Inverse" ETFs ([SH](https://www.morningstar.com/etfs/arcx/sh/quote), [SQQQ](https://www.morningstar.com/etfs/xnas/sqqq/portfolio)). ETFdb and ProShares' own product pages corroborate. Industry consensus is unambiguous: ProShares short / leveraged ETFs are index-tracking, passively-managed products.

### 3d. Recommendation

Reclassify all 51 ProShares short funds to `passive`. The current taxonomy (SQQQ → `bond_or_other`, SH → `passive`, TBF → `excluded`, etc.) is an N-PORT line-item artifact, not an economic reality. All 51 share identical mechanics: inverse index tracking via swaps + T-bill collateral.

**Code-side cause:** `scripts/pipeline/nport_parsers.py:54-63` adds `proshares` to `INDEX_PATTERNS`, and the classifier checks `INDEX_PATTERNS` *before* `EXCLUDE_PATTERNS` and the holdings-composition logic. Under the current classifier any name matching `\bproshares\b` resolves to `passive`. The current mixed taxonomy reflects pre-PR-2 classifier output that was never reclassified post-lock.

**No reclassifications executed in this PR** (whitelist binding). Surfaced for chat decision under `verify-proshares-short-classification` (now closed by this audit; queued for a follow-up reclassification PR).

---

## 4. Active Bucket Review (Phase 4)

### 4a. UNKNOWN orphan rows by fund_name

All 3,184 rows currently `active`. Distinct fund names rolled into the `UNKNOWN` sentinel:

| fund_name | rows | first_quarter | last_quarter |
|---|---:|---|---|
| Calamos Global Total Return Fund | 1,412 | 2025Q2 | 2025Q3 |
| Saba Capital Income & Opportunities Fund | 1,091 | 2025Q4 | 2025Q4 |
| Asa Gold & Precious Metals Ltd | 350 | 2024Q4 | 2025Q3 |
| Eaton Vance Tax-Advantaged Dividend Income Fund | 157 | 2025Q1 | 2025Q1 |
| `N/A` | 96 | 2025Q3 | 2025Q3 |
| NXG Cushing Midstream Energy Fund | 43 | 2025Q2 | 2025Q2 |
| AMG Pantheon Credit Solutions Fund | 33 | 2025Q1 | 2025Q1 |
| AIP Alternative Lending Fund P | 2 | 2024Q4 | 2025Q2 |

### 4b. 8 named CEFs in `fund_universe`

Pre-Phase-4c state:

| series_id | fund_name | fund_strategy |
|---|---|---|
| SYN_0001709447 | AIP Alternative Lending Fund A | bond_or_other |
| SYN_0001709406 | AIP Alternative Lending Fund P | active |
| SYN_0001995940 | AMG Pantheon Credit Solutions Fund | balanced |
| SYN_0001230869 | ASA Gold and Precious Metals LTD Fund | active |
| SYN_0001253327 | Eaton Vance Tax-Advantaged Dividend Income Fund | balanced |
| SYN_0001270523 | Eaton Vance Tax-Advantaged Global Dividend Income Fund | balanced |
| SYN_0001281926 | Eaton Vance Tax-Advantaged Global Dividend Opportunities Fund | balanced |
| SYN_0001400897 | NXG Cushing Midstream Energy Fund | active |
| SYN_0000826020 | Saba Capital Income & Opportunities Fund | balanced |
| SYN_0000828803 | Saba Capital Income & Opportunities Fund II | multi_asset |

Notable: Calamos Global Total Return Fund did NOT match any `fund_universe` row — it appears only as an UNKNOWN orphan, never resolved into a SYN entry. Same for the 96-row `N/A` cohort.

### 4c. Pre-execution whitelist match

```
('SYN_0001709406', 'AIP Alternative Lending Fund P', 'active')
('SYN_0001995940', 'AMG Pantheon Credit Solutions Fund', 'balanced')
```

Exactly 2 rows. Pre-execution gate **PASS**.

### 4c. SQL applied

Flask stopped before the UPDATE. Single transaction:

```sql
BEGIN TRANSACTION;
UPDATE fund_universe
SET fund_strategy = 'bond_or_other'
WHERE fund_name IN (
  'AMG Pantheon Credit Solutions Fund',
  'AIP Alternative Lending Fund P'
);
-- post-verify: exactly 2 rows now have target

UPDATE fund_holdings_v2
SET fund_strategy_at_filing = 'bond_or_other'
WHERE series_id IN ('SYN_0001709406', 'SYN_0001995940');
-- post-verify: cascade row count preserved
COMMIT;
```

### 4c. Post-state

| series_id | fund_name | fund_universe.fund_strategy | fund_holdings_v2 rows |
|---|---|---|---:|
| SYN_0001709406 | AIP Alternative Lending Fund P | bond_or_other | 1 |
| SYN_0001995940 | AMG Pantheon Credit Solutions Fund | bond_or_other | 77 |

`fund_universe`: 2 rows updated; `fund_holdings_v2`: 78 rows updated. Both UPDATE STOP gates honored (≤ 2 in `fund_universe`; cascade count preserved).

### 4d. Surfaced Candidates for Future Reclassification (NOT executed)

Captured for chat decision; not part of this PR.

| series_id | fund_name | current strategy | flag | category |
|---|---|---|---|---|
| SYN_0001230869 | ASA Gold and Precious Metals LTD Fund | active | likely correct (gold mining equity) | appears_correctly_classified |
| SYN_0001400897 | NXG Cushing Midstream Energy Fund | active | active equity, midstream energy LPs | appears_correctly_classified |
| SYN_0000826020 | Saba Capital Income & Opportunities Fund | balanced | already aligned via PR-1a tiebreaker | appears_correctly_classified |
| SYN_0000828803 | Saba Capital Income & Opportunities Fund II | multi_asset | NEW — surfaced this session, sibling of above | requires_decision |
| SYN_0001253327 | Eaton Vance Tax-Advantaged Dividend Income Fund | balanced | requires_review (tax-advantaged dividend strategy) | requires_decision |
| SYN_0001270523 | Eaton Vance Tax-Advantaged Global Dividend Income Fund | balanced | NEW — surfaced this session | requires_decision |
| SYN_0001281926 | Eaton Vance Tax-Advantaged Global Dividend Opportunities Fund | balanced | NEW — surfaced this session | requires_decision |
| — | Calamos Global Total Return Fund | (no fund_universe row) | NEW — appears only as UNKNOWN orphan | requires_decision |
| — | `N/A` (96 rows) | (no fund_universe row, no resolvable name) | NEW — loader could not resolve name | confirmed_needs_review |

---

## 5. Validation Results

### 5a. pytest

```
$ python3 -m pytest tests/ -x --no-header -q
...
373 passed, 1 warning in 51.62s
```

### 5b. PR-4 validator (`scripts/oneoff/validate_fund_strategy_rename.py`)

```
=== summary ===
  overall        : PASS
```

All 7 affected endpoints (portfolio_context level=fund, cross_ownership level=fund, holder_momentum level=fund, cohort_analysis active_only=true, ownership_trend_summary, peer_rotation level=fund, short_analysis) return 200.

### 5c. PR-3 validator (`scripts/oneoff/validate_fund_strategy_consolidate.py`)

After updating its baselines + value reference (`equity` → `active` post-PR-4):

```
=== summary ===
  overall        : PASS
```

Baselines bumped to reflect post-Phase-4c state:
- `PRE_ACTIVE_FUND_UNIVERSE`: 5620 → 5618 (-2: AIP P + AMG Pantheon to passive set)
- `PRE_PASSIVE_FUND_UNIVERSE`: 8003 → 8005 (+2)
- `PRE_ACTIVE_HOLDINGS_LATEST`: 5,236,150 → 5,236,072 (-78 cascade rows)

### 5d. Post-Phase-4c distribution

| fund_strategy | rows | active set? |
|---|---:|:-:|
| active | 4,831 | ✓ |
| excluded | 3,681 | |
| bond_or_other | 2,753 | |
| passive | 1,517 | |
| balanced | 566 | ✓ |
| multi_asset | 221 | ✓ |
| final_filing | 54 | |
| **total** | **13,623** | |

Active total 5,618; passive total 8,005; sum 13,623; no gap, no overlap. Δ from PR-4 post-state: -2 active, +2 passive (the 2 reclassified credit funds).

---

## 6. Decisions Pending — items requiring chat-level decisions before execution

1. **ProShares short funds — reclassify 51 to `passive`.** Mechanics + Morningstar + classifier code all converge on `passive`. Execute as a follow-up PR; not part of this batch (whitelist binding).
2. **Eaton Vance Tax-Advantaged variants** (3 funds) and **Saba Capital II** — reclassification candidates, all currently `balanced`/`multi_asset`. Per-fund prospectus review needed.
3. **Calamos Global Total Return Fund** — currently UNKNOWN orphan with 1,412 holdings rows; no `fund_universe` entry. Decide whether to mint a SYN entry (and at what classification) or leave in NULL arm.
4. **`N/A` cohort** (96 holdings rows) — fund-name resolution gap in the loader. Decide whether to backfill, drop, or quarantine.
5. **301-series orphan cohort** — disposition of `fund-holdings-orphan-investigation` P2 follow-up: backfill `fund_universe` entries, or rewrite `cross.py` NULL semantics, or both.

---

## 7. Files

| File | Change |
|---|---|
| `scripts/oneoff/audit_canonical_coverage.py` | NEW — Phase 1 audit (read-only) |
| `scripts/oneoff/audit_active_bucket.py` | NEW — Phase 4a/4b audit (read-only) |
| `scripts/oneoff/reclassify_credit_funds.py` | NEW — Phase 4c executor (whitelist binding, transactional) |
| `scripts/oneoff/validate_fund_strategy_consolidate.py` | Baselines updated (post-Phase-4c), `'equity'` → `'active'` literals |
| `docs/findings/fund_cleanup_batch_results.md` | THIS FILE |
| `ROADMAP.md` | Header bump; 4 items moved to COMPLETED; 2 new follow-ups added |

Schema changes:
- `fund_universe`: 2 rows updated (`SYN_0001709406`, `SYN_0001995940`) — `fund_strategy` → `bond_or_other`.
- `fund_holdings_v2`: 78 rows updated for the same 2 series_ids — `fund_strategy_at_filing` → `bond_or_other`.

---

## 8. Out of scope (per plan)

- `fund-strategy-taxonomy-finalization` — separate session covering balanced / multi_asset / excluded / final_filing edge categories.
- `parent-level-display-canonical-reads` — institution-level sequence.
- `stage-b-turnover-deferred-funds` — Vanguard Primecap / Windsor II / Equity Income, separate Stage B initiative.
- ProShares 51-fund reclassification — surfaced for chat decision, not executed (whitelist binding to AMG Pantheon + AIP P only).
- 6 surfaced candidate funds (Eaton Vance variants, Saba II, ASA Gold, NXG Cushing, Calamos, `N/A` cohort) — surfaced for chat decision, not executed.

---

## 9. STOP gates — disposition

| phase | gate | status |
|---|---|---|
| 1 | 1a returns >0 NULL | PASS (0) |
| 1 | 1g divergent_latest_only > 5,000 | **TRIGGERED (40,843)** — chat-approved continuation; documented as harmless drift |
| 1 | 1f returns 0 ProShares funds | PASS (51) |
| 2 | any BlackRock fund found ACTIVE and trading | PASS (all 12 confirmed merged) |
| 4c | pre-execution whitelist != 2 rows | PASS (exactly 2) |
| 4c | UPDATE touches > 2 fund_universe rows | PASS (2) |
