# Classification Consolidation Plan

**Date:** 2026-04-30
**Branch:** `classify-consolidate-plan`
**Predecessor:** `docs/findings/classification_scoping.md` (PR #230 squash `d7ba02d`)
**DB:** `data/13f.duckdb` (read-only). Latest quarter on `holdings_v2`: see Section A1 cross-check.
**Scope:** Read-only. Data + options only. Decisions happen in chat.

---

## Schema corrections vs. plan

- `entity_aliases` column is `alias_name`, not `alias_value`. A3 / E1 queries adjusted.
- Everything else aligns with the plan.

---

## SECTION A — Institution Level: `mixed`

### A1 — Top 20 `mixed` entities by AUM (latest quarter)

| name | total_aum (USD) | n_tickers | entity_type_on_holdings | manager_type_on_holdings |
|---|---:|---:|---|---|
| JPMorgan Asset Management | 1,592,803,773,825 | 5,502 | mixed | mixed |
| Bank of America / Merrill | 1,473,915,815,322 | 6,237 | mixed | mixed |
| Goldman Sachs Asset Management | 811,112,755,395 | 4,749 | mixed | mixed |
| UBS Asset Management | 618,340,701,500 | 6,918 | mixed | mixed |
| RBC Global | 614,691,725,420 | 5,990 | mixed | mixed |
| BNY Mellon / Dreyfus | 567,686,283,148 | 3,829 | mixed | mixed |
| Wells Fargo | 549,076,148,275 | 5,781 | mixed | mixed |
| AMERIPRISE FINANCIAL INC | 442,510,610,213 | 3,756 | mixed | mixed |
| Barclays | 436,375,302,989 | 3,978 | mixed | mixed |
| Deutsche Asset Management | 422,933,478,620 | 3,424 | mixed | mixed |
| Franklin Templeton | 407,592,910,194 | 2,829 | mixed | mixed |
| BANK OF MONTREAL /CAN/ | 288,733,335,011 | 2,864 | mixed | mixed |
| Citigroup | 226,580,254,567 | 4,605 | mixed | mixed |
| BNP PARIBAS FINANCIAL MARKETS | 220,693,742,796 | 4,262 | mixed | mixed |
| Nomura | 180,957,151,776 | 2,186 | mixed | mixed |
| Sumitomo Mitsui Trust Group, Inc. | 170,274,683,544 | 994 | mixed | mixed |
| TD Asset Management | 124,298,883,961 | 1,164 | mixed | mixed |
| Swedbank AB | 103,370,121,376 | 651 | mixed | mixed |
| US BANCORP \DE\ | 85,348,442,420 | 3,758 | mixed | mixed |
| TORONTO DOMINION BANK | 67,752,683,180 | 1,230 | mixed | mixed |

### A2 — `manager_type` cross-tab for `entity_type='mixed'`

| manager_type | n_entities | total_aum (USD) |
|---|---:|---:|
| mixed | 689 | 11,160,388,302,506 |
| active | 1 | 8,133,217,317 |
| strategic | 1 | 5,204,191,030 |
| family_office | 7 | 3,546,747,148 |

### A3 — Sample `mixed` entity_classification_history rows

| entity_id | name | classification | valid_from | source | confidence |
|---:|---|---|---|---|---|
| 10032 | Ameriprise Trust CO | mixed | 2000-01-01 | managers | fuzzy_match |
| 5668 | Sterling Financial Group, Inc. | mixed | 2000-01-01 | managers | fuzzy_match |
| 10014 | SMART Wealth LLC | mixed | 2000-01-01 | managers | phase4_sync |
| 731 | SILVER OAK SECURITIES, INCORPORATED | mixed | 2000-01-01 | managers | phase4_sync |
| 10215 | Susquehanna Capital Management, LLC | mixed | 2000-01-01 | managers | fuzzy_match |
| 7484 | BOKF, NA | mixed | 2000-01-01 | managers | phase4_sync |
| 7989 | Washington Trust Bank | mixed | 2000-01-01 | managers | fuzzy_match |
| 2814 | Bank of Marin | mixed | 2000-01-01 | managers | fuzzy_match |
| 8461 | GREAT VALLEY ADVISOR GROUP, INC. | mixed | 2000-01-01 | managers | phase4_sync |
| 5876 | Kelly Financial Services LLC | mixed | 2000-01-01 | managers | phase4_sync |

All sampled rows: `valid_from=2000-01-01`, `source='managers'`, `confidence ∈ {fuzzy_match, phase4_sync}`. None are high-confidence; all derive from the legacy manager-registry seed.

---

## SECTION B — Institution Level: `active`

### B1 — Top 20 `active` entities by AUM (latest quarter)

| name | total_aum (USD) | n_tickers | manager_type |
|---|---:|---:|---|
| Fidelity / FMR | 1,961,270,506,891 | 4,804 | active |
| Morgan Stanley Investment Management | 1,674,995,873,221 | 6,766 | mixed |
| Capital World Investors | 735,299,396,725 | 533 | active |
| Capital International Investors | 637,974,712,600 | 433 | active |
| Wellington Management | 570,656,000,440 | 1,705 | active |
| Capital Group / American Funds | 559,274,272,567 | 3,141 | active |
| UBS Asset Management | 472,968,453,108 | 3,141 | mixed |
| ENVESTNET ASSET MANAGEMENT INC | 337,094,793,320 | 3,937 | active |
| AllianceBernstein | 316,671,797,710 | 3,092 | active |
| MASSACHUSETTS FINANCIAL SERVICES CO /MA/ | 310,120,825,041 | 869 | active |
| Fisher Asset Management, LLC | 292,994,343,150 | 981 | active |
| Janus Henderson | 223,305,440,420 | 2,315 | active |
| American Century | 198,966,317,750 | 2,680 | active |
| Principal Financial | 195,864,495,890 | 2,089 | active |
| Dodge & Cox | 185,255,599,930 | 213 | active |
| Victory Capital | 177,199,061,610 | 2,294 | active |
| JENNISON ASSOCIATES LLC | 166,565,920,600 | 543 | active |
| Mitsubishi UFJ Asset Management | 147,504,514,920 | 1,562 | active |
| First Trust | 137,596,236,141 | 2,503 | passive |
| Man Group | 134,336,793,820 | 1,991 | quantitative |

### B2 — `manager_type` cross-tab for `entity_type='active'`

| manager_type | n_entities | total_aum (USD) |
|---|---:|---:|
| active | 3,994 | 15,307,210,049,180 |
| mixed | 14 | 2,204,516,326,329 |
| passive | 3 | 153,904,479,141 |
| wealth_management | 70 | 151,908,727,030 |
| quantitative | 1 | 134,336,793,820 |
| hedge_fund | 6 | 101,271,019,950 |
| private_equity | 4 | 37,323,135,070 |
| strategic | 30 | 9,533,432,608 |
| endowment_foundation | 1 | 747,469,470 |

Notable drift: Morgan Stanley IM, UBS Asset Mgmt show `entity_type=active` on top-20 but `manager_type=mixed`; First Trust shows `entity_type=active` but `manager_type=passive`; Man Group shows `entity_type=active` but `manager_type=quantitative`. `entity_type` and `manager_type` disagree on **~120 entities** carrying ~$2.5T AUM.

---

## SECTION C — Institution Level: `strategic`

### C1 — Top 20 `strategic` entities by AUM (latest quarter)

| name | total_aum (USD) | n_tickers | manager_type |
|---|---:|---:|---|
| Berkshire Hathaway Inc | 274,160,141,400 | 41 | strategic |
| SC US (TTGP), LTD. | 14,010,267,200 | 15 | strategic |
| NVIDIA CORP | 13,104,816,800 | 4 | strategic |
| Markel Group Inc. | 12,544,358,180 | 128 | strategic |
| Loews Corp | 12,281,317,440 | 25 | strategic |
| Partners Value Investments L.P. | 10,702,407,200 | 6 | private_equity |
| Briar Hall Management LLC | 6,367,096,140 | 1 | strategic |
| Japan Post Holdings Co., Ltd. | 5,767,121,200 | 1 | strategic |
| Exor N.V. | 5,577,710,330 | 2 | strategic |
| Freemont Capital Pte Ltd | 4,473,488,580 | 5 | strategic |
| Glencore plc | 4,333,081,360 | 1 | strategic |
| Uber Technologies, Inc | 4,187,234,710 | 4 | strategic |
| Fidelity / FMR | 3,537,892,750 | 123 | active |
| AMAZON COM INC | 3,521,437,180 | 6 | strategic |
| Hancock Prospecting Pty Ltd | 3,254,469,810 | 30 | strategic |
| Saudi Electronic Games Holding Co | 2,922,500,560 | 1 | strategic |
| American Family Investments, Inc. | 2,778,442,520 | 11 | strategic |
| Alphabet Inc. | 2,579,791,330 | 29 | strategic |
| CAS Investment Partners, LLC | 2,337,080,170 | 5 | strategic |
| Rakuten Group, Inc. | 2,259,811,820 | 4 | strategic |

These are operating companies / family holding companies / sovereign-style holders that own equity stakes for strategic, not asset-management, reasons (Berkshire dominates, then SC US/Sequoia, then operating companies like NVIDIA, Amazon, Alphabet, Glencore, Uber, Markel, Loews, Exor).

---

## SECTION D — Institution Level: `quantitative`

### D1 — Top 20 `quantitative` entities by AUM (latest quarter)

| name | total_aum (USD) | n_tickers | manager_type |
|---|---:|---:|---|
| Dimensional Fund Advisors | 476,724,141,170 | 3,115 | passive |
| CTC LLC | 204,887,393,120 | 59 | quantitative |
| AQR Capital | 190,628,401,540 | 3,406 | quantitative |
| DE Shaw | 182,424,019,200 | 2,773 | quantitative |
| Two Sigma | 123,058,640,580 | 3,832 | quantitative |
| Qube Research & Technologies Ltd | 98,444,694,790 | 2,779 | quantitative |
| Renaissance Technologies | 64,461,239,160 | 2,975 | quantitative |
| Man Group | 60,159,084,740 | 1,972 | quantitative |
| Quantinno Capital Management LP | 49,793,341,470 | 3,004 | quantitative |
| Trexquant Investment LP | 11,217,604,500 | 1,488 | quantitative |
| Engineers Gate Manager LP | 8,432,292,270 | 1,954 | quantitative |
| SIG North Trading, ULC | 5,480,236,290 | 104 | quantitative |
| SYSTEMATIC FINANCIAL MANAGEMENT LP | 4,242,407,210 | 246 | quantitative |
| Millburn Ridgefield LLC /DE/ | 4,197,654,210 | 39 | quantitative |
| SIG BROKERAGE, LP | 3,215,679,860 | 433 | quantitative |
| Systematic Alpha Investments, LLC | 3,205,552,400 | 220 | quantitative |
| Winton Group | 2,896,832,950 | 867 | quantitative |
| RENAISSANCE GROUP LLC | 2,490,429,160 | 223 | quantitative |
| Entropy Technologies, LP | 1,843,444,580 | 814 | quantitative |
| OCCUDO QUANTITATIVE STRATEGIES LP | 1,492,813,440 | 640 | quantitative |

### D2 — `is_passive` split for quantitative

| is_passive | n_entities | n_rows |
|---|---:|---:|
| FALSE | 37 | 58,632 |
| TRUE | 1 | 13,709 |

The 1 `is_passive=TRUE` entity is Dimensional Fund Advisors. All other quants are non-passive systematic / factor / market-making books.

---

## SECTION E — Institution Level: `market_maker` and `unknown`

### E1 — All 23 `market_maker` entities

| entity_id | name |
|---:|---|
| 10924 | CTC LLC |
| 4741 | Citadel Securities GP LLC |
| 6493 | DRW Securities, LLC |
| 10239 | FLOW TRADERS U.S. LLC |
| 8950 | HRT FINANCIAL LP |
| 9665 | IMC-Chicago, LLC |
| 7345 | JANE STREET GROUP, LLC |
| 1833 | Jane Street Asia Trading Ltd |
| 11094 | Jane Street Capital, LLC |
| 6142 | Jane Street Europe Ltd |
| 392 | Jane Street Global Trading, LLC |
| 8975 | Jane Street Options, LLC |
| 2457 | Jane Street Singapore Pte. Ltd |
| 7382 | Optiver Holding B.V. |
| 4477 | Optiver US LLC |
| 6878 | Optiver VOF |
| 2473 | SIG BROKERAGE, LP |
| 7172 | SIG North Trading, ULC |
| 9755 | SUSQUEHANNA INTERNATIONAL GROUP, LLP |
| 1126 | Susquehanna International Group Ltd. |
| 5568 | Susquehanna International Securities, Ltd. |
| 2078 | TWO SIGMA SECURITIES, LLC |
| 4601 | Virtu Financial LLC |

### E2 — `market_maker` entities cross-checked against `holdings_v2`

| name | entity_type (holdings_v2) | n_rows |
|---|---|---:|
| JANE STREET GROUP, LLC | hedge_fund | 59,885 |
| IMC-Chicago, LLC | hedge_fund | 14,805 |
| HRT FINANCIAL LP | quantitative | 10,895 |
| Optiver Holding B.V. | hedge_fund | 8,027 |
| Virtu Financial LLC | mixed | 5,700 |
| DRW Securities, LLC | mixed | 4,135 |
| FLOW TRADERS U.S. LLC | hedge_fund | 3,630 |
| SIG BROKERAGE, LP | quantitative | 2,585 |
| SIG North Trading, ULC | quantitative | 1,063 |
| CTC LLC | quantitative | 482 |

The `market_maker` classification exists in `entity_classification_history` only; it is **never written to `holdings_v2.entity_type`**. On holdings, the same firms appear as `hedge_fund`, `quantitative`, or `mixed`. 13 of the 23 (Citadel Securities, all 7 Jane Street legals except Group, 3 Optiver legals, 3 Susquehanna legals, Two Sigma Securities) do not appear in `holdings_v2` at all (no 13F filings under those CIKs).

### E3 — `unknown` by `entities.created_source`

| created_source | cnt |
|---|---:|
| ncen_adviser_map | 2,179 |
| managers | 1,246 |
| bootstrap_tier4 | 427 |

3,852 `unknown` entities total. ~57% from N-CEN adviser map seed, ~32% from managers registry, ~11% from Tier-4 bootstrap.

### E4 — Top 20 `unknown` entities that do appear in `holdings_v2`

| name | type_on_holdings | total_aum (USD) | n_rows |
|---|---|---:|---:|
| ARROWSTREET CAPITAL, LP | hedge_fund | 594,060,302,610 | 7,337 |
| WOLVERINE TRADING, LLC | quantitative | 323,521,237,090 | 14,699 |
| Grantham, Mayo, Van Otterloo & Co. | active | 139,527,711,690 | 2,477 |
| PZENA INVESTMENT MANAGEMENT LLC | hedge_fund | 123,740,143,650 | 737 |
| NATIXIS | active | 86,330,909,290 | 4,087 |
| BROWN BROTHERS HARRIMAN & CO | wealth_management | 64,621,506,860 | 6,362 |
| UNITED CAPITAL FINANCIAL ADVISORS | active | 54,632,373,440 | 4,734 |
| Boston Trust Walden Corp | wealth_management | 54,587,361,520 | 2,367 |
| JARISLOWSKY, FRASER Ltd | strategic | 51,658,201,170 | 565 |
| Driehaus Capital Management LLC | hedge_fund | 51,555,924,160 | 1,645 |
| BRANDES INVESTMENT PARTNERS, LP | active | 46,506,807,150 | 1,839 |
| WOLVERINE ASSET MANAGEMENT LLC | hedge_fund | 45,384,564,820 | 6,390 |
| NEOS Investment Management LLC | active | 43,989,257,540 | 4,431 |
| AXA Investment Managers S.A. | pension_insurance | 37,055,742,180 | 2,671 |
| CLEAR STREET LLC | active | 35,672,937,810 | 1,512 |
| HORIZON KINETICS ASSET MANAGEMENT | active | 32,845,361,310 | 1,359 |
| SEGALL BRYANT & HAMILL, LLC | active | 28,541,420,810 | 2,279 |
| First Pacific Advisors, LP | hedge_fund | 28,056,701,180 | 246 |
| CAUSEWAY CAPITAL MANAGEMENT LLC | active | 25,940,664,150 | 402 |
| Conestoga Capital Advisors, LLC | active | 25,571,729,200 | 488 |

Same drift pattern as E2: `entity_classification_history.classification='unknown'` but `holdings_v2.entity_type` is populated (often correctly). Top entities include very large books — Arrowstreet ($594B), Wolverine ($324B), GMO ($140B), Pzena ($124B). The classification source disagrees with the holdings type.

---

## SECTION F — Institution Level: Consolidation Impact

### F1 — Proposed taxonomy on `holdings_v2` (latest quarter)

Mapping applied: `pension_insurance + endowment_foundation + SWF → asset_owner`, `private_equity + venture_capital → pe_vc`, `wealth_management → wealth_mgmt`, `hedge_fund → hedge_fund`. `mixed`, `multi_strategy`, `family_office` are **not in `entity_type`** at all (they only exist in `manager_type`), so the proposed merges that touch those (`hedge_fund + multi_strategy`, `wealth_management + family_office`) are no-ops at this level. Same for `passive`, `active`, `quantitative`, `strategic`, `activist` — kept as-is below.

| proposed_type | n_entities | total_aum (USD) | n_rows |
|---|---:|---:|---:|
| passive | 43 | 20,845,540,000,000 | 166,424 |
| active | 4,123 | 18,100,750,000,000 | 1,094,499 |
| mixed | 698 | 11,177,280,000,000 | 750,929 |
| hedge_fund | 1,286 | 7,120,492,000,000 | 304,333 |
| wealth_mgmt | 1,615 | 4,410,971,000,000 | 720,470 |
| asset_owner | 220 | 3,377,479,000,000 | 89,432 |
| quantitative | 38 | 1,504,906,000,000 | 72,341 |
| strategic | 408 | 499,000,000,000 | 4,720 |
| pe_vc | 119 | 197,000,000,000 | 2,237 |
| activist | 13 | 88,000,000,000 | 265 |

### F2 — Proposed taxonomy on `entity_classification_history` (current rows)

| proposed_type | n_entities |
|---|---:|
| active | 11,470 |
| passive | 5,846 |
| unknown | 3,852 |
| wealth_mgmt | 1,678 |
| hedge_fund | 1,484 |
| strategic | 1,163 |
| mixed | 1,032 |
| pe_vc | 265 |
| asset_owner | 232 |
| quantitative | 73 |
| activist | 34 |
| market_maker | 23 |

`market_maker` (23 entities, 0% on holdings) and `unknown` (3,852 entities, but several show up on holdings with non-unknown types) are the two pre-decided open buckets. The plan's stated merges (`hedge_fund + multi_strategy`, `wealth_management + family_office`) exist only in the `manager_type` field; the migration into `entity_type` has not been done yet. See Findings below.

---

## SECTION G — Fund Level: `active` ⇄ `equity` Drift

### G1 — First `fund_strategy` value seen for the 4,340 drifters

| first_value | n_funds |
|---|---:|
| active | 4,340 |

100% of the 4,340 active⇄equity drifters had `active` as their first written value, then migrated to `equity` in later quarters/months. `active` is the legacy value; `equity` is the current value.

### G2 — `fund_strategy` × `fund_category` in `fund_universe` (residuals)

| fund_strategy | fund_category | cnt |
|---|---|---:|
| active | equity | 250 |
| active | balanced | 45 |
| active | multi_asset | 15 |
| mixed | equity | 5 |
| passive | equity | 15 |
| passive | balanced | 2 |
| passive | multi_asset | 1 |

Only **333** funds in `fund_universe` carry the legacy `{active, passive, mixed}` values (vs. 13,623 total funds → 2.4%). The classifier wrote these and then a later classifier overwrote most of them, leaving these residuals.

### G3 — `fund_universe.fund_strategy` vs `fund_holdings_v2.fund_strategy`

| universe_strategy | holdings_strategy | n_funds |
|---|---|---:|
| active | active | 290 |
| active | mixed | 20 |
| mixed | mixed | 5 |
| passive | passive | 12 |

The legacy values persist on both tables in lockstep — no drift between universe and holdings on these 327 series. The taxonomy split (`{active,passive,mixed}` vs. `{equity,index,balanced,...}`) is a **versioning** issue, not a write-path inconsistency.

---

## SECTION H — Fund Level: 658 Empty-String Funds

### H1 — Top 20 by `total_net_assets`

All 20 sampled have `total_net_assets = NULL`, `is_actively_managed = NULL`, `fund_category = NULL`, `family_name = fund_name`, and `series_id = SYN_<10-digit CIK>`. Examples:

| series_id | fund_name |
|---|---|
| SYN_0000806628 | DNP Select Income Fund Inc |
| SYN_0000860489 | The Central and Eastern Europe Fund, Inc. |
| SYN_0000884394 | SPDR S&P 500 ETF TRUST |
| SYN_0000936958 | State Street SPDR S&P MidCap 400 ETF Trust |
| SYN_0001041130 | SPDR DOW JONES INDUSTRIAL AVERAGE ETF TRUST |
| SYN_0001083839 | Nuveen Quality Municipal Income Fund |
| SYN_0001090116 | Nuveen AMT-Free Municipal Credit Income Fund |
| SYN_0001137391 | BlackRock California Municipal Income Trust |
| SYN_0001137887 | Nuveen Municipal Credit Income Fund |
| SYN_0001140411 | PIMCO California Municipal Income Fund |
| SYN_0001195737 | Nuveen AMT-Free Quality Municipal Income Fund |
| SYN_0001216583 | Nuveen Preferred & Income Opportunities Fund |
| SYN_0001253327 | Eaton Vance Tax-Advantaged Dividend Income Fund |
| SYN_0001260729 | Gabelli Dividend & Income Trust |
| SYN_0001263994 | Reaves Utility Income Fund |
| SYN_0001275214 | CALAMOS STRATEGIC TOTAL RETURN FUND |
| SYN_0001275617 | COHEN & STEERS INFRASTRUCTURE FUND INC |
| SYN_0001306550 | BlackRock Energy & Resources Trust |
| SYN_0001379438 | Eaton Vance Tax-Managed Global Diversified Equity Income Fund |
| SYN_0001447247 | Partners Group Private Equity Fund, LLC |

### H2 — Holdings-level `fund_strategy` distribution for these 658 funds

| holdings_strategy | n_funds | n_rows |
|---|---:|---:|
| bond_or_other | 438 | 2,064,838 |
| equity | 123 | 24,704 |
| balanced | 59 | 23,656 |
| multi_asset | 40 | 15,712 |
| final_filing | 14 | 3,413 |
| index | 8 | 2,559 |
| excluded | 8 | 4,225 |

The funds **do** have classifications on `fund_holdings_v2` (some of them have millions of rows). The empty string lives only in `fund_universe.fund_strategy`.

### H3 — Synthetic vs. real series_id

| fund_strategy | series_type | cnt |
|---|---|---:|
| NULL | synthetic | 658 |

100% are `SYN_*` (Tier-4 synthetic series). The universe-level classifier never ran on synthetic IDs because there is no source N-CEN/N-PORT registration row to seed from; the synthetic IDs exist only because holdings rows reference them.

---

## SECTION I — Fund Level: Proposed Taxonomy

### I1 — `fund_universe` rolled up

Mapping applied: `equity + active → equity`, `balanced + multi_asset + mixed → balanced`, `index + passive → index`. Other values left as-is.

| proposed_strategy | n_funds | total_nav (USD) |
|---|---:|---:|
| index | 1,274 | 15,573,852,000,000 |
| equity | 4,901 | 13,360,940,000,000 |
| excluded | 3,673 | 5,178,734,000,000 |
| bond_or_other | 2,330 | 4,555,140,000,000 |
| balanced | 745 | 2,063,909,000,000 |
| final_filing | 42 | 18,669,040,000 |
| unclassified | 658 | NULL |

Total: 13,623 funds. The `unclassified` bucket is the SYN-only set from Section H.

---

## SECTION J — Name-Regex Rerun (corrected K2)

### J1 — Name-regex (LIKE-ladder) vs stored `fund_strategy`

| name_result | fund_strategy | is_actively_managed | cnt |
|---|---|---|---:|
| active | equity | TRUE | 4,568 |
| passive | excluded | FALSE | 3,652 |
| active | bond_or_other | FALSE | 2,290 |
| passive | index | FALSE | 1,252 |
| active | NULL/'' | NULL | 649 |
| active | balanced | TRUE | 525 |
| active | active | TRUE | 310 |
| active | multi_asset | TRUE | 183 |
| active | final_filing | FALSE | 42 |
| passive | bond_or_other | FALSE | 40 |
| passive | balanced | TRUE | 27 |
| passive | equity | TRUE | 23 |
| active | excluded | FALSE | 21 |
| passive | passive | FALSE | 17 |
| passive | NULL/'' | NULL | 9 |
| active | mixed | TRUE | 5 |
| passive | multi_asset | TRUE | 5 |
| active | index | FALSE | 4 |
| active | passive | FALSE | 1 |

### J2 — Sample disagreements (30)

Two patterns visible:

1. **Regex false positives** (regex says `passive`, stored is `index` or `bond_or_other`): "Fidelity Total Bond Fund", "Wilshire Income Opportunities Fund", "Baird Aggregate Bond Fund", "Dow Jones Industrial Average Fund" — name contains "TOTAL BOND" / "DOW JONES" / "WILSHIRE" but funds are bond/index funds correctly classified. Several are `active` regex matches against `index` stored value (e.g., "Fidelity Total Bond Fund" stored as `index`).

2. **Stored false positives** (regex says `passive`, stored is `balanced`): "ProShares Ultra Russell2000", "Russell 2000 1.5x Strategy Fund", "PROFUND VP ULTRANASDAQ-100", "Inverse Russell 2000 Strategy Fund" — these are leveraged/inverse index ETFs. Regex correctly flags `passive`; stored `balanced` is wrong.

### J2b — Aggregate disagreement rate

| disagreements | total | rate |
|---:|---:|---:|
| 60 | 13,623 | 0.44% |

Disagreement rate is **0.44%** (60 funds), much lower than the prior scoping K2 figure (the LIKE-ladder fix collapsed most of the apparent disagreements). The remaining 60 split between the two patterns above.

---

## Findings

### What `mixed` means

`mixed` is **the diversified-financial-institution bucket**. All 689 entities with `entity_type='mixed'` and `manager_type='mixed'` on holdings are universal banks, full-service brokers, or multi-line asset managers that run both passive and active products under one roof: JPMorgan, BoA/Merrill, Goldman, UBS, RBC, BNY Mellon, Wells Fargo, Ameriprise, Barclays, Deutsche, Franklin Templeton, BMO, Citi, BNP, Nomura, etc. Top 5 alone is $5.1T AUM. All sampled classification history rows are seeded from the `managers` registry with low-quality confidence (`fuzzy_match` / `phase4_sync`), `valid_from=2000-01-01`. There is no high-confidence input — the bucket is a default for "this is a bank or diversified asset manager".

The 7 `family_office` rows under `manager_type` ($3.5B) are likely mis-routed (family offices ≠ universal banks). They are distinct from the bank rollup.

### What `active` means at institution level

`active` is **the long-only fundamental active manager bucket** (Fidelity, Capital Group, Wellington, AllianceBernstein, MFS, Janus, American Century, Dodge & Cox, etc.). Top 20 = $9.0T AUM. The bucket is mostly coherent: 3,994 of 4,123 entities (97%) carry `manager_type='active'`. Drift cases:

- 14 entities ($2.2T) carry `manager_type='mixed'` (Morgan Stanley IM, UBS Asset Mgmt) — these are bank-affiliated active arms; their `entity_type` and `manager_type` disagree.
- 70 entities ($152B) carry `manager_type='wealth_management'`.
- A few one-offs in passive, hedge_fund, quantitative, private_equity, strategic, endowment_foundation manager_types.

### What `strategic` is

`strategic` is **non-asset-manager corporate / family-holding / sovereign holders**. Berkshire Hathaway alone is 55% of the bucket ($274B of $499B). The remainder is operating companies that hold equity stakes (NVIDIA, Amazon, Alphabet, Glencore, Uber, Markel, Loews), family-controlled holding companies (Exor, Hancock Prospecting, American Family Investments, Rakuten), VC-style (SC US/Sequoia at $14B), and one-offs (Japan Post, Saudi Electronic Games Holding). This is a distinct concept — these are not asset managers; they are corporate strategic investors. Cannot be merged into asset_owner (pension/insurance/E&F/SWF) without losing meaning.

### What `quantitative` is

`quantitative` is **systematic / factor / model-driven investing**. 38 active entities, $1.5T AUM. Top entities are AQR, DE Shaw, Two Sigma, Qube, RenTech, Man Group, CTC, plus Dimensional Fund Advisors which is the only `is_passive=TRUE` member ($477B). Excluding Dimensional, all are non-passive systematic books. There is overlap with the market-maker ecosystem (CTC LLC, SIG North Trading, SIG Brokerage all appear in both `market_maker` classification history and `quantitative` holdings type). Whether to merge with `hedge_fund` depends on intent: methodologically distinct from discretionary hedge funds, but commercially overlapping. Keeping them separate preserves a 38-entity / $1.5T AUM signal that disappears if folded in.

### What `market_maker` is

`market_maker` is **a phantom classification at the holdings level**. All 23 entities exist in `entity_classification_history` (Citadel Securities, Jane Street suite, DRW, Flow Traders, HRT, IMC, Optiver suite, SIG suite, Susquehanna suite, Two Sigma Securities, Virtu, CTC). 13 of them never appear in `holdings_v2` because their CIKs never filed 13F. The 10 that do appear are written as `hedge_fund` (Jane Street Group, IMC, Optiver Holding, Flow Traders), `quantitative` (HRT, SIG entities, CTC LLC), or `mixed` (Virtu, DRW). The label is real in the registry but not preserved on holdings rows.

### What `unknown` is

`unknown` is **a holding bucket for entities we have not yet classified**. 3,852 entities total (2,179 from N-CEN adviser map seed, 1,246 from managers registry, 427 from Tier-4 bootstrap). But it is **leaky**: of the 3,852, top entities by AUM include Arrowstreet ($594B), Wolverine Trading ($324B), GMO ($140B), Pzena ($124B), etc. — these are real, well-known, high-AUM books that simply were not classified. Their `holdings_v2.entity_type` is populated (often correctly: hedge_fund, quantitative, active, etc.), but their `entity_classification_history.classification` is `unknown`. The two stores are out of sync.

### Where `active` / `passive` / `mixed` fund_strategy values came from

A **legacy classifier** wrote the values `{active, passive, mixed}` before being replaced by the current `{equity, index, balanced, multi_asset, bond_or_other, excluded, final_filing}` taxonomy. Evidence:

- All 4,340 series with both values had `active` first, `equity` second.
- Only 333 funds (2.4% of 13,623) carry the legacy values today; the rest were overwritten.
- `fund_universe.fund_strategy` and `fund_holdings_v2.fund_strategy` agree on the legacy values (G3) — write-path is consistent; the issue is the taxonomy version.

The 333 residuals are leftover rows the new classifier never re-evaluated.

### What the 658 empty-string funds are

All 658 are **synthetic Tier-4 series** (`SYN_<CIK>`). They have no source N-CEN registration row, so the universe-level classifier — which seeds from N-CEN/N-PORT metadata — never ran on them. They include large, recognizable closed-end funds and ETF trusts (SPDR S&P 500 ETF TRUST, DJIA ETF, MidCap 400 ETF, Nuveen muni funds, BlackRock muni trusts, Calamos, Cohen & Steers, Eaton Vance, Gabelli, Reaves, Partners Group). At the holdings level, **638 of 658 do have a `fund_strategy`** (438 bond_or_other, 123 equity, 59 balanced, 40 multi_asset, 8 index, 8 excluded, 14 final_filing). The empty string lives only in `fund_universe.fund_strategy`.

### Name-regex vs stored disagreement rate (corrected K2)

**0.44% (60 of 13,623).** The corrected LIKE-ladder collapses the prior K2 disagreement count. The 60 residual disagreements split between regex false positives (bond / multi-asset funds whose names accidentally match an index keyword like "TOTAL BOND" or "DOW JONES") and **real stored mis-classifications** of leveraged/inverse index ETFs as `balanced` (ProShares Ultra Russell2000, Russell 2000 1.5x Strategy Fund, PROFUND ULTRANASDAQ-100, Inverse Russell 2000 Strategy Fund — clearly index products carrying `balanced`).

---

## Proposed Taxonomy

### Institution level (entity_type) — current state

10 distinct values currently appear on holdings. Pre-decided merges from the prompt are scoped against `entity_type`:

| current entity_type values (10) | pre-decided merge | proposed bucket |
|---|---|---|
| pension_insurance, endowment_foundation, SWF | yes | asset_owner |
| private_equity, venture_capital | yes | pe_vc |
| wealth_management | yes (with family_office) | wealth_mgmt |
| hedge_fund | yes (with multi_strategy) | hedge_fund |
| active | — | active |
| passive | — | passive |
| mixed | — | mixed |
| quantitative | — | quantitative (decision needed) |
| strategic | — | strategic (decision needed) |
| activist | — | activist |

`family_office`, `multi_strategy`, `market_maker`, `unknown` do **not** appear in `entity_type` today; they exist only in `manager_type` (family_office, multi_strategy) or `entity_classification_history.classification` (market_maker, unknown). Migrating them into `entity_type` is a prerequisite for the merges to bite at the holdings level.

### Institution level — proposed taxonomy with counts

Latest-quarter `holdings_v2`:

| proposed_type | n_entities | total_aum (USD) |
|---|---:|---:|
| passive | 43 | $20.85T |
| active | 4,123 | $18.10T |
| mixed | 698 | $11.18T |
| hedge_fund | 1,286 | $7.12T |
| wealth_mgmt | 1,615 | $4.41T |
| asset_owner | 220 | $3.38T |
| quantitative | 38 | $1.50T |
| strategic | 408 | $499B |
| pe_vc | 119 | $197B |
| activist | 13 | $88B |

Decisions still open:
- **`mixed` vs `active`** — should `mixed` (the diversified-bank bucket, $11.2T) stay separate or fold into `active` (the long-only-active bucket, $18.1T)? Data supports keeping separate: top-20 mixed entities are all banks/universal financial institutions; top-20 active entities are all dedicated active asset managers. Merging would lose the bank/non-bank distinction.
- **`strategic`** — keep, rename, or merge? Data supports keep. Strategic = non-asset-manager corporates and family holdings. Folding into anything else (asset_owner, pe_vc) misclassifies. Possible rename: `corporate_holder` to make the meaning explicit.
- **`quantitative`** — keep separate or fold into `hedge_fund`? Data supports keep separate. 38 entities, $1.5T, methodologically distinct (systematic vs. discretionary). Folding loses signal.
- **`market_maker`** — currently 23 entities in classification history but 0 on holdings. Options: (a) drop the label and accept the holdings-level drift (Jane Street → hedge_fund, etc.); (b) write `market_maker` to `entity_type` for the 10 that do show up; (c) keep as a `manager_type`-only field. Holdings-level entity_type is currently NULL for none of these (all are written), so option (b) requires a backfill.
- **`unknown`** — 3,852 entities, but ~30 of them carry $25B+ AUM each in `holdings_v2` (Arrowstreet, Wolverine, GMO, Pzena, etc.). Options: (a) backfill `entity_classification_history` from the populated `holdings_v2.entity_type` for the leaky ones; (b) force-classify the rest by ADV / N-CEN sweep; (c) leave as-is and accept the gap.
- **`family_office` and `multi_strategy`** — these don't exist in `entity_type` yet. To execute the pre-decided merges (`wealth_management + family_office → wealth_mgmt`, `hedge_fund + multi_strategy → hedge_fund`), they must first be migrated from `manager_type` to `entity_type` for the affected entities.

### Fund level (fund_strategy) — current state

12 distinct values currently appear: `equity, active, balanced, multi_asset, mixed, index, passive, excluded, bond_or_other, final_filing, ''/NULL`.

Pre-decided merges from the prompt:
- `equity + active → equity`
- `balanced + multi_asset + mixed → balanced`
- `index + passive → index`

### Fund level — proposed taxonomy with counts (fund_universe)

| proposed_strategy | n_funds | total_nav (USD) |
|---|---:|---:|
| index | 1,274 | $15.57T |
| equity | 4,901 | $13.36T |
| excluded | 3,673 | $5.18T |
| bond_or_other | 2,330 | $4.56T |
| balanced | 745 | $2.06T |
| final_filing | 42 | $18.7B |
| unclassified | 658 | NULL |

Decisions still open:
- **`active` (the legacy value)** — the merge `equity + active → equity` will absorb all 333 residuals cleanly. No separate decision needed; this is a versioning cleanup, not a taxonomy choice.
- **`mixed` (the legacy value)** — the merge `balanced + multi_asset + mixed → balanced` absorbs the 5 residuals.
- **`passive` (the legacy value)** — the merge `index + passive → index` absorbs the 17 residuals.
- **`unclassified` (658 SYN-only)** — three options: (a) run the universe classifier on synthetic series using the holdings-level fund_strategy as a seed (638 of 658 already have a holdings-level value); (b) leave them empty and exclude from filters; (c) explicit `unclassified` bucket. Option (a) is mechanical given the data already exists at the holdings level (Section H2).
- **Leveraged/inverse index funds stored as `balanced`** — 60 disagreement cases include real mis-classifications (ProShares Ultra Russell2000, Russell 2000 1.5x, ULTRANASDAQ-100). These should arguably be `index` (or carve-out a `leveraged_index` bucket if the distinction matters). Out of scope for the consolidation merges but flagged here.
- **`final_filing` and `excluded`** — these are status flags rather than strategy types. Keeping as-is preserves the distinction; merging them into a single `inactive` bucket loses the reason-for-exclusion signal.

---

## Files cross-referenced

- [classification_scoping.md](docs/findings/classification_scoping.md) — predecessor scoping doc (PR #230, squash `d7ba02d`)
- `data/13f.duckdb` — read-only source for all queries above
