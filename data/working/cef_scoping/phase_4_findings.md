# Phase 4 Findings — CEF Scoping: Schema Fit & Form Cadence

**Worktree:** `naughty-bell-727cea`
**Date:** 2026-05-02
**Status:** READ-ONLY research. No code or DB changes.

---

## 0. Headline Finding (REFRAMES THE WORKSTREAM)

**CEFs ARE subject to Form N-PORT.** Rule 30b1-9 under the Investment Company Act of 1940 requires "registered management investment companies and ETFs organized as UITs" to file N-PORT monthly. Closed-end management investment companies are registered management investment companies — they are in scope. The SEC explicitly addressed and rejected a CEF carve-out in the 2016 Reporting Modernization release: although some CEFs strike NAV less frequently, the rule applies because CEFs already maintain monthly NAV under 30b1-9's recordkeeping leg.

**Implication:** A CEF holdings pipeline does NOT need a separate N-CSR-only path for the modern era (2019+). It can ride the existing N-PORT loader (`fetch_nport_v2.py`, `load_13f_v2.py`) with minimal schema changes. N-CSR becomes a **historical backfill** path (pre-N-PORT, e.g. 2004–2018) and a **supplemental** path for derivative/contract detail not fully captured in N-PORT Part C.

This is a meaningful descope vs. the original ROADMAP framing (which implied NSAR/N-CSR as primary).

---

## 1. Filing Cadence Table

| Form | Frequency | Public Disclosure Lag | Applies to CEFs | Citation |
|---|---|---|---|---|
| **N-PORT** | Monthly file (3 reports per fiscal quarter) | Currently: third-month report public 60 days after quarter-end (months 1 & 2 remain non-public until amendments take effect). Under 2024 amendments (compliance Nov 2027 large / May 2028 small): all 12 monthly reports public 60 days after each month-end. 2026 SEC re-proposal would shift filing to 45 days after month-end. | **YES** | Rule 30b1-9; SEC Release IC-35308 (2024); IC-35538 (2025); proposed amendments (Feb 2026) |
| **N-CSR** | Semiannual (annual + semiannual shareholder report) | Shareholder report transmitted within 60 days of fiscal period-end; N-CSR filed within 10 days after transmission (i.e., ~70 days after period-end) | **YES** (and historically the primary CEF holdings disclosure pre-2019) | Rule 30b2-1; Section 30(b)(2) of 1940 Act |
| **N-CEN** | Annual | Filed within 75 days of fiscal year-end | YES | Rule 30a-1; SEC Release IC-32314 (2016) |
| **NSAR-A / NSAR-B** | RETIRED 2018-06-01 | n/a | n/a (historical only) | Replaced by N-CEN (census) + N-PORT (holdings) |

### NSAR clarification (important — ROADMAP wording is misleading)

NSAR was an **operational/census** form (fund operations, expense ratios, advisor info, accountant). It was **NOT a holdings disclosure form** in any meaningful sense. NSAR-A = semiannual (mid-year) submission; NSAR-B = annual submission. Pre-2019 portfolio holdings for CEFs lived in **N-CSR / N-CSRS**, not NSAR. Any future ROADMAP item naming NSAR as a holdings source should be corrected to N-CSR.

### Quarterly-aggregation impact

Because CEFs file N-PORT monthly (same as open-end funds), quarterly aggregation in `flow_analysis` and `conviction` tabs works **identically** for CEFs. No carry-forward logic, no empty Q1/Q3 — the existing quarterly grouping on `report_date` continues to work. Only edge case: pre-2019 CEF history sourced from N-CSR will be semiannual, so `flow_analysis` time series prior to ~2019 will have 2 points/year per CEF instead of 4.

---

## 2. Structured XML Availability

| Form | Structured XML? | edgartools holdings extraction |
|---|---|---|
| **N-PORT** | Yes — full XML (Items A-C, including Part C schedule of investments) since 2019 | YES — fully parsed into DataFrames; this is the path we already use |
| **N-CSR (post-2019)** | Partial — N-CSR exhibits include the schedule of investments but it is **not required to be structured XML**. Filings are typically Inline-XBRL-tagged for financial statements (post-2024 tailored shareholder report rule); the schedule of investments inside N-CSR is generally HTML tables embedded in the report. | **PARTIAL/UNCERTAIN** — README lists "N-CSR/N-CEN fund reports" as supported but does not document a `holdings()` accessor. Realistically `Filing.obj()` likely returns metadata + raw text/HTML. Holdings extraction would require custom HTML table parsing. |
| **N-CSR (pre-2019)** | No — embedded HTML/PDF tables in the periodic report; format varies by filer/printer | NO structured extraction; OCR / table scraping required |
| **N-CEN** | Yes — XML format mandated | Census/operational only — no holdings |

**Recommendation:** For a CEF holdings build, **rely on N-PORT for 2019+**. Only invest in N-CSR HTML scraping if pre-2019 CEF history is a stated requirement.

---

## 3. Field-Level Delta — `fund_universe`

| Column | N-PORT source | N-CSR source | Mappable for CEFs? |
|---|---|---|---|
| `fund_cik` | Header | Header | YES |
| `fund_name` | Item A.1 | Cover page | YES |
| `series_id` | Item A.1 | Cover page (often absent for CEFs — many CEFs are single-series) | PARTIAL — series_id frequently null/equals fund for CEFs |
| `family_name` | Header / EDGAR | Header / EDGAR | YES |
| `total_net_assets` | Item B.1 (NAV) | Statement of Assets & Liabilities | YES — see §5 callout (use NAV, not market cap) |
| `total_holdings_count` | Derived from Part C count | Derived from SoI count | YES |
| `equity_pct` | Derived from Part C asset_category | Derived from SoI category | YES (post-2019); partial pre-2019 |
| `top10_concentration` | Derived from Part C | Derived from SoI | YES |
| `last_updated` | loader timestamp | loader timestamp | YES |
| `fund_strategy` | Strategy classifier (external) | Strategy classifier (external) | YES — see §6 |
| `best_index` | external | external | YES |
| `strategy_narrative` | external | external | YES |
| `strategy_source` | external | external | YES |
| `strategy_fetched_at` | external | external | YES |

**Verdict:** `fund_universe` schema is **fully reusable** for CEFs. Zero new columns required for the N-PORT-era CEF universe.

---

## 4. Field-Level Delta — `fund_holdings_v2`

| Column | N-PORT source | N-CSR source | Mappable for CEFs? |
|---|---|---|---|
| `fund_cik` | Header | Header | YES |
| `fund_name` | Item A.1 | Cover | YES |
| `family_name` | EDGAR | EDGAR | YES |
| `series_id` | Item A.1 | Cover (often null) | PARTIAL — many CEFs lack series_id; loader needs a fallback (e.g., synthesize from CIK or use 'CEF' literal, mirror to `unknown` pattern from int-21) |
| `quarter` | Derived | Derived | YES |
| `report_month` | Header period-of-report | Header period-of-report | YES |
| `report_date` | Header period-of-report | Header period-of-report | YES |
| `cusip` | Part C Item C.1 | SoI table | YES |
| `isin` | Part C Item C.1 | SoI table (less common) | YES post-2019; PARTIAL pre |
| `issuer_name` | Part C Item C.1 | SoI | YES |
| `ticker` | Part C Item C.1 | SoI (often missing) | PARTIAL |
| `asset_category` | Part C Item C.4 | SoI category header | YES |
| `shares_or_principal` | Part C Item C.5 | SoI shares/principal column | YES |
| `market_value_usd` | Part C Item C.6 | SoI fair-value column | YES |
| `pct_of_nav` | Part C Item C.7 | SoI % of net assets | YES |
| `fair_value_level` | Part C Item C.8 | Footnote (less consistently tagged) | YES post-2019; PARTIAL pre |
| `is_restricted` | Part C Item C.9 | SoI footnote/asterisk | YES post-2019; PARTIAL pre |
| `payoff_profile` | Part C Item C.10 | Not consistently disclosed | YES post-2019; NO pre |
| `loaded_at` | loader | loader | YES |
| `fund_strategy_at_filing` | Snapshot from `fund_universe` | same | YES |
| `entity_id` / `rollup_entity_id` / `dm_*` | MDM enrichment | MDM enrichment | YES (CEF issuers map through the same entity layer) |
| `row_id` | Loader sequence | Loader sequence | YES |
| `accession_number` | Header | Header | YES |
| `is_latest` | Loader logic | Loader logic | YES |
| `backfill_quality` | Loader tag | Loader tag | YES |

**Verdict:** `fund_holdings_v2` schema is **fully reusable** for CEFs from N-PORT. Zero new columns required for the N-PORT path. Two soft issues:

- `series_id` will frequently be null for CEFs — loader convention needed (likely: synthesize or accept null and rely on `fund_cik` as the join key).
- Pre-2019 N-CSR backfill, if pursued, will produce records with `fair_value_level`, `is_restricted`, `payoff_profile` null and `backfill_quality = 'ncsr_html'` (or similar tag).

---

## 5. CEF-Specific Fields NOT Captured by Current Schema

Closed-end funds have features that the N-PORT-shaped schema does not represent:

| CEF feature | Where reported | Currently in schema? | Recommendation |
|---|---|---|---|
| **NAV per share** | N-PORT Item B.5; N-CSR financial highlights | NO (only `total_net_assets` aggregate) | Optional — can add `nav_per_share` if conviction/flow analytics need premium/discount |
| **Market price per share** | Not in N-PORT; from market data feed (yfinance) | NO | Out of scope for filings pipeline; bring in via separate market data join |
| **Premium/discount to NAV** | Derived (market_price / NAV − 1) | NO | Derive at query time if needed; do NOT store |
| **Leverage ratio (1940 Act)** | N-PORT Item B.3; N-CSR financial highlights | NO | Optional — relevant for CEF risk profile |
| **Distribution rate / managed distribution policy** | N-CSR; press releases | NO | Out of scope |
| **Share class structure** | Cover page | Implicit (single class for most CEFs) | No action — most CEFs are single-class |
| **Board composition** | N-CSR; proxy | NO | Out of scope |
| **Expense ratio detail** | N-CEN; N-CSR | NO | N-CEN is separate; out of scope for holdings pipeline |
| **Securities lending detail** | N-PORT Item B.4 | NO | Optional — relevant for some CEFs |
| **Derivatives detail (notional, counterparty)** | N-PORT Part C.11 (sub-items) | Partially captured via `payoff_profile` | Existing column is adequate for first pass |

**Recommended additions (P3, not blocking):** `nav_per_share` to `fund_universe` if any CEF analytic depends on premium/discount calculation. Otherwise schema is sufficient.

### `total_net_assets` source for CEFs — recommendation

Use **N-PORT Item B.1 net assets (NAV)**. This is the portfolio's true value and is comparable to the open-end fund convention already in use. **Do not** use market cap (price × shares outstanding) for `total_net_assets` — for CEFs these differ materially (CEFs trade at premium/discount, sometimes 10%+). Market cap, if needed, belongs in a separate column populated from a market data source.

---

## 6. `fund_strategy` Taxonomy Recommendation

CEFs span the same broad strategy buckets as open-end funds (equity, fixed income, multi-asset, alternatives, sector-specific). The **current taxonomy values likely fit CEFs without modification**, with one nuance: CEFs disproportionately represent leveraged income strategies (municipal bond CEFs, senior loan CEFs, BDCs adjacent), which the existing taxonomy may classify generically as "fixed_income" or "credit".

**Recommendations:**
1. Do not introduce CEF-specific strategy values (avoid balkanizing the taxonomy).
2. Cross-reference with the open `fund-strategy-taxonomy-finalization` P2 item — ensure that QC pass evaluates a CEF sample to confirm classifier behavior.
3. Consider an **orthogonal** `fund_structure` column on `fund_universe` (`open_end` / `closed_end` / `etf` / `uit`) rather than encoding structure into `fund_strategy`. Structure is a separate dimension from strategy and downstream analytics (premium/discount, leverage) only apply to closed-end.

---

## 7. Quarterly-Aggregation Impact for `flow_analysis` and `conviction`

| Era | CEF data source | Aggregation behavior |
|---|---|---|
| 2019-Q3 onward (N-PORT era) | N-PORT monthly | **Identical to open-end funds** — quarterly groupby on `report_date` works as-is. No carry-forward. No empty quarters. |
| 2004 – 2019-Q2 (pre-N-PORT) | N-CSR semiannual (only if backfilled) | **Two reports per year per CEF**, typically aligned to fund fiscal year (not calendar). Q1/Q3 will be empty for CEFs unless we carry-forward from the prior semiannual report. |
| Pre-2004 | N/A | Out of scope |

**Recommendation for `flow_analysis`:**
- Modern era: no change. Existing logic correct.
- Historical (if backfilled from N-CSR): add a `is_carryforward` flag on synthetic Q1/Q3 rows so the UI can grey them out, OR limit pre-2019 CEF analytics to "as-of latest report" view rather than quarterly time series.

**Recommendation for `conviction`:**
- Add/drop signals for CEFs in the N-PORT era are reliable at monthly granularity (better than quarterly).
- Do NOT compute conviction signals on synthetic carry-forward rows.

---

## Sources

- [SEC Investment Company Reporting Modernization Rules — Small Business Compliance Guide](https://www.sec.gov/resources-small-businesses/small-business-compliance-guides/investment-company-reporting-modernization-rules)
- [Form N-PORT (SEC PDF)](https://www.sec.gov/files/formn-port.pdf)
- [Form N-CSR (SEC PDF)](https://www.sec.gov/files/formn-csr.pdf)
- [Form N-CEN (SEC PDF)](https://www.sec.gov/files/formn-cen.pdf)
- [Form N-SAR (SEC PDF — historical)](https://www.sec.gov/about/forms/formn-sar.pdf)
- [SEC Final Rule IC-35308 (2024 N-PORT amendments)](https://www.sec.gov/files/rules/final/2024/ic-35308.pdf)
- [SEC Final Rule IC-35538 (2025 N-PORT/N-CEN)](https://www.sec.gov/files/rules/final/2025/ic-35538.pdf)
- [Federal Register — Form N-PORT Reporting (Feb 2026 re-proposal)](https://www.federalregister.gov/documents/2026/02/23/2026-03460/form-n-port-reporting)
- [17 CFR 270.30b1-9](https://www.govinfo.gov/link/cfr/17/270?link-type=pdf&sectionnum=30b1-9&year=mostrecent)
- [SEC ICRM FAQ](https://www.sec.gov/about/divisions-offices/division-investment-management/accounting-disclosure-information/investment-company-reporting-modernization-frequently-asked-questions)
- [Radient Analytics — N-CEN vs N-SAR](https://info.radientanalytics.com/blog/what-is-form-n-cen-and-how-is-it-different-from-form-n-sar)
- [edgartools README (GitHub)](https://github.com/dgunning/edgartools/blob/main/README.md)
- [edgartools docs](https://edgartools.readthedocs.io/)
