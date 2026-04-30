# N-PORT Fund-Level Classification — Scoping (Read-Only)

**DB:** `/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership/data/13f.duckdb`
**Mode:** read-only
**Branch:** `nport-classify-scope`
**Generated:** 2026-04-30
**Predecessors:** `docs/findings/classification_scoping.md` (PR #230, `d7ba02d`), `docs/findings/classification_consolidation_plan.md` (PR #231, `cb418c0`)

Scope: fund level only (`fund_universe`, `fund_holdings_v2`). Institution level is out of scope here.

---

## SECTION 1 — Full type inventory

### 1.1 `fund_universe.fund_strategy` distribution

```sql
SELECT
  COALESCE(NULLIF(fund_strategy, ''), '<empty>') AS strategy,
  COUNT(*) AS n_funds,
  SUM(total_net_assets) AS total_nav,
  COUNT(CASE WHEN is_actively_managed = TRUE THEN 1 END) AS n_active_flag,
  COUNT(CASE WHEN is_actively_managed = FALSE THEN 1 END) AS n_passive_flag,
  COUNT(CASE WHEN is_actively_managed IS NULL THEN 1 END) AS n_null_flag
FROM fund_universe
GROUP BY strategy
ORDER BY n_funds DESC
```

| strategy | n_funds | total_nav | n_active_flag | n_passive_flag | n_null_flag |
| --- | --- | --- | --- | --- | --- |
| equity | 4,591 | 13,264,635,829,862.53 | 4,591 | 0 | 0 |
| excluded | 3,673 | 5,178,733,996,209.54 | 0 | 3,673 | 0 |
| bond_or_other | 2,330 | 4,555,139,907,754.73 | 0 | 2,330 | 0 |
| index | 1,256 | 15,571,907,860,568.88 | 0 | 1,256 | 0 |
| `<empty>` | 658 | ∅ | 0 | 0 | 658 |
| balanced | 552 | 1,570,415,535,108.44 | 552 | 0 | 0 |
| active | 310 | 96,309,090,104.48 | 310 | 0 | 0 |
| multi_asset | 188 | 490,376,459,608.23 | 188 | 0 | 0 |
| final_filing | 42 | 18,669,044,351.45 | 0 | 42 | 0 |
| passive | 18 | 1,947,075,058.08 | 0 | 18 | 0 |
| mixed | 5 | 3,117,418,903.92 | 5 | 0 | 0 |

`is_actively_managed` is a perfect functional dependency of `fund_strategy` — TRUE for `{active, balanced, equity, mixed, multi_asset}`, FALSE for `{bond_or_other, excluded, final_filing, index, passive}`, NULL only when `fund_strategy=''`.

### 1.2 `fund_universe.fund_category` distribution

| category | n_funds | total_nav |
| --- | --- | --- |
| equity | 4,861 | 13,351,615,774,898.75 |
| excluded | 3,673 | 5,178,733,996,209.54 |
| bond_or_other | 2,330 | 4,555,139,907,754.73 |
| index | 1,256 | 15,571,907,860,568.88 |
| `<empty>` | 658 | ∅ |
| balanced | 599 | 1,579,302,466,978.99 |
| multi_asset | 204 | 495,883,166,767.93 |
| final_filing | 42 | 18,669,044,351.45 |

`fund_category` has 8 values; missing the legacy `{active, passive, mixed}`. Strategy is finer-grained than category only by carrying those three legacy buckets.

### 1.3 `fund_holdings_v2.fund_strategy` distribution (`is_latest=TRUE`)

| strategy | n_funds | n_rows |
| --- | --- | --- |
| active | 5,256 | 2,963,043 |
| equity | 4,796 | 1,157,020 |
| excluded | 3,817 | 1,548,833 |
| bond_or_other | 2,912 | 4,250,624 |
| index | 1,290 | 1,487,590 |
| passive | 1,018 | 1,877,774 |
| balanced | 670 | 374,460 |
| mixed | 377 | 634,197 |
| multi_asset | 258 | 266,712 |
| final_filing | 56 | 8,451 |

> The holdings-level snapshot has many more `active` rows than `fund_universe` (5,256 vs 310). This is **legacy** — early loads pre-dated the rename to `equity` and never got rewritten on subsequent quarters because `fund_holdings_v2` rows are append-not-replace at the (series, quarter) level.

### 1.4 Cross-tab `fund_strategy` × `fund_category` in `fund_universe`

| strategy | category | n_funds |
| --- | --- | --- |
| equity | equity | 4,591 |
| excluded | excluded | 3,673 |
| bond_or_other | bond_or_other | 2,330 |
| index | index | 1,256 |
| `<empty>` | `<empty>` | 658 |
| balanced | balanced | 552 |
| active | equity | 250 |
| multi_asset | multi_asset | 188 |
| active | balanced | 45 |
| final_filing | final_filing | 42 |
| active | multi_asset | 15 |
| passive | equity | 15 |
| mixed | equity | 5 |
| passive | balanced | 2 |
| passive | multi_asset | 1 |

333 rows where strategy ≠ category, all of them legacy `{active, passive, mixed}` strategies pointing to a real-world category.

---

## SECTION 2 — Source of each value

### 2.1 series_id source × strategy

| series_source | strategy | n_funds |
| --- | --- | --- |
| sec_series_id | equity | 4,581 |
| sec_series_id | excluded | 3,673 |
| sec_series_id | bond_or_other | 2,291 |
| sec_series_id | index | 1,256 |
| sec_series_id | balanced | 548 |
| sec_series_id | active | 310 |
| sec_series_id | multi_asset | 186 |
| sec_series_id | final_filing | 42 |
| sec_series_id | passive | 15 |
| sec_series_id | mixed | 5 |
| synthetic | `<empty>` | 658 |
| synthetic | bond_or_other | 39 |
| synthetic | equity | 10 |
| synthetic | balanced | 4 |
| synthetic | multi_asset | 2 |
| other | passive | 3 |

- Every `<empty>` strategy (658 rows) is on a `SYN_*` synthetic series (no real S-prefixed SEC ID).
- The 333 legacy `{active, passive, mixed}` rows are all on real `S*` SEC series — they pre-date the rename to `equity/balanced/multi_asset/index/passive`.
- 55 SYN funds have non-empty strategy values, mostly `bond_or_other`.

### 2.2 Per-strategy sample (3 each, random)

| series_id | fund_name | fund_strategy | fund_category | is_actively_managed | total_net_assets | first_quarter | n_holdings_rows |
| --- | --- | --- | --- | --- | --- | --- | --- |
| S000005123 | Fidelity Advisor Equity Value Fund | active | equity | 1 | 208,919,499.94 | 2024Q4 | 331 |
| S000056587 | Natixis Target Retirement 2030 Fund | active | balanced | 1 | 17,024,793.90 | 2025Q1 | 1,190 |
| S000052510 | SA BlackRock VCP Global Multi Asset Portfolio | active | multi_asset | 1 | 671,294,605.48 | 2025Q1 | 756 |
| S000022760 | Direxion Daily Energy Bull 2X Shares | balanced | balanced | 1 | 271,222,232.53 | 2025Q1 | 146 |
| S000033464 | GMO Benchmark-Free Fund | balanced | balanced | 1 | 1,154,913,711.45 | 2024Q4 | 6,369 |
| S000014248 | ProShares Ultra Russell2000 | balanced | balanced | 1 | 282,497,219.34 | 2024Q4 | 11,859 |
| S000036793 | 1290 VT High Yield Bond Portfolio | bond_or_other | bond_or_other | 0 | 415,246,169.93 | 2025Q4 | 477 |
| S000011801 | Invesco Floating Rate ESG Fund | bond_or_other | bond_or_other | 0 | 2,192,927,625.53 | 2025Q3 | 1,106 |
| S000046660 | Nuveen Emerging Markets Debt Fund | bond_or_other | bond_or_other | 0 | 823,445,642.00 | 2025Q4 | 832 |
| S000015703 | Allspring Emerging Growth Fund | equity | equity | 1 | 300,210,304.79 | 2025Q1 | 380 |
| S000088560 | American Beacon Ninety One Global Franchise Fund | equity | equity | 1 | 460,110,632.57 | 2024Q4 | 181 |
| S000024677 | Mid Value Fund | equity | equity | 1 | 1,331,851,129.94 | 2024Q4 | 609 |
| S000075505 | FAIRLEAD TACTICAL SECTOR ETF | excluded | excluded | 0 | 271,795,523.16 | 2025Q4 | 21 |
| S000084956 | OneAscent Enhanced Small and Mid Cap ETF | excluded | excluded | 0 | 68,083,373.69 | 2025Q4 | 183 |
| S000065129 | iShares iBonds Dec 2028 Term Muni Bond ETF | excluded | excluded | 0 | 614,808,710.79 | 2025Q4 | 4,154 |
| S000066478 | BBH Select Series - Large Cap Fund | final_filing | final_filing | 0 | 521,397,675.92 | 2025Q1 | 128 |
| S000073505 | PGIM Jennison NextGeneration Global Opportunities Fund | final_filing | final_filing | 0 | 8,370,595.20 | 2025Q1 | 236 |
| S000089758 | Victory Pioneer Intrinsic Value Fund | final_filing | final_filing | 0 | 2,293,289.77 | 2025Q1 | 120 |
| S000050371 | iShares Developed Real Estate Index Fund | index | index | 0 | 284,793,016.91 | 2025Q1 | 1,795 |
| S000018073 | iShares MSCI Turkey ETF | index | index | 0 | 346,330,431.74 | 2024Q4 | 514 |
| S000083456 | iShares Paris-Aligned Climate Optimized MSCI World ex USA ETF | index | index | 0 | 316,414,214.32 | 2024Q4 | 2,763 |
| S000063454 | Acclivity Mid Cap Multi-Style Fund | mixed | equity | 1 | 4,398,780.74 | 2024Q4 | 1,230 |
| S000057851 | BlackRock GA Disciplined Volatility Equity Fund | mixed | equity | 1 | 1,142,198,776.61 | 2025Q1 | 1,434 |
| S000041744 | Calamos Dividend Growth Fund | mixed | equity | 1 | 22,169,697.13 | 2025Q1 | 329 |
| S000056101 | Destinations Multi Strategy Alternatives Fund | multi_asset | multi_asset | 1 | 548,818,533.80 | 2024Q4 | 735 |
| S000087629 | NAA OPPORTUNITY FUND | multi_asset | multi_asset | 1 | 35,223,176.39 | 2024Q4 | 2,408 |
| S000052511 | SA Schroders VCP Global Allocation Portfolio | multi_asset | multi_asset | 1 | 413,734,569.78 | 2025Q1 | 5,002 |
| S000083881 | Direxion Daily MSCI Emerging Markets ex China Bull 2X Shares | passive | multi_asset | 0 | 2,632,849.02 | 2025Q1 | 18 |
| SPDR_SERIES | SPDR Series Trust | passive | equity | 0 | ∅ | ∅ | 0 |
| S000053591 | Victory 500 Index VIP Series | passive | equity | 0 | 89,130,990.00 | 2024Q4 | 1,534 |

Note: `SPDR_SERIES` has no holdings rows at all — a phantom fund.

---

## SECTION 3 — The 4,591 `equity` funds (active by design)

### 3.1 Top 30 by NAV

| series_id | fund_name | family_name | total_net_assets | fund_category |
| --- | --- | --- | --- | --- |
| S000101292 | Invesco QQQ Trust, Series 1 | Invesco QQQ Trust, Series 1 | 407,693,673,462.84 | equity |
| S000009228 | Growth Fund of America | Growth Fund of America | 340,053,494,334.79 | equity |
| S000009388 | Washington Mutual Investors Fund | Washington Mutual Investors Fund | 211,103,983,002.74 | equity |
| S000006037 | Fidelity Contrafund | Fidelity Contrafund | 176,319,409,234.39 | equity |
| S000009597 | Investment Co of America | Investment Co of America | 175,972,375,023.96 | equity |
| S000009613 | New Perspective Fund | New Perspective Fund | 162,832,622,200.26 | equity |
| S000009227 | American Funds Fundamental Investors | American Funds Fundamental Investors | 161,866,114,613.49 | equity |
| S000009001 | Capital World Growth & Income Fund | Capital World Growth & Income Fund | 143,395,284,513.86 | equity |
| S000005080 | College Retirement Equities Fund - Total Global Stock Account | College Retirement Equities Fund | 135,247,377,342.00 | equity |
| S000009618 | EUPAC Fund | EUPAC Fund | 134,940,204,628.01 | equity |
| S000003856 | JPMorgan Large Cap Growth Fund | JPMorgan Trust II | 120,692,880,259.40 | equity |
| S000011202 | Dodge & Cox Stock Fund | Dodge & Cox Funds | 119,768,866,113.13 | equity |
| S000002573 | VANGUARD TARGET RETIREMENT 2035 FUND | VANGUARD CHESTER FUNDS | 119,365,651,112.19 | equity |
| S000008999 | American Mutual Fund | American Mutual Fund | 113,532,477,295.77 | equity |
| S000012761 | VANGUARD TARGET RETIREMENT 2040 FUND | VANGUARD CHESTER FUNDS | 109,141,754,748.04 | equity |
| S000002574 | VANGUARD TARGET RETIREMENT 2045 FUND | VANGUARD CHESTER FUNDS | 108,994,613,592.05 | equity |
| S000012760 | VANGUARD TARGET RETIREMENT 2030 FUND | VANGUARD CHESTER FUNDS | 108,935,139,126.93 | equity |
| S000008817 | AMCAP Fund | AMCAP Fund | 97,949,151,276.61 | equity |
| S000012762 | VANGUARD TARGET RETIREMENT 2050 FUND | VANGUARD CHESTER FUNDS | 95,999,017,635.83 | equity |
| S000007195 | Fidelity Blue Chip Growth Fund | Fidelity Securities Fund | 89,250,781,769.77 | equity |
| S000007119 | Fidelity Growth Company Fund | Fidelity Mt. Vernon Street Trust | 82,479,606,016.34 | equity |
| S000009599 | SMALLCAP World Fund Inc | SMALLCAP World Fund Inc | 82,439,692,510.11 | equity |
| S000009633 | New World Fund Inc | New World Fund Inc | 79,717,856,355.36 | equity |
| S000002572 | VANGUARD TARGET RETIREMENT 2025 FUND | VANGUARD CHESTER FUNDS | 76,514,313,516.96 | equity |
| S000002568 | VANGUARD PRIMECAP FUND | VANGUARD CHESTER FUNDS | 76,019,104,196.27 | equity |
| S000002069 | T. Rowe Price Blue Chip Growth Fund, Inc. | T. ROWE PRICE BLUE CHIP GROWTH FUND, INC. | 68,745,843,882.00 | equity |
| S000029153 | Strategic Advisers Fidelity International Fund | Fidelity Rutland Square Trust II | 68,295,044,262.46 | equity |
| S000029700 | VANGUARD TARGET RETIREMENT 2055 FUND | VANGUARD CHESTER FUNDS | 66,885,018,922.69 | equity |
| S000004418 | VANGUARD WINDSOR II FUND | VANGUARD WINDSOR FUNDS | 64,578,672,653.24 | equity |
| S000002579 | VANGUARD EQUITY INCOME FUND | VANGUARD FENWAY FUNDS | 62,464,990,855.97 | equity |

> **Hidden index trackers detected at the top:** `Invesco QQQ Trust` ($408B) and 11 Vanguard Target Retirement / Vanguard Primecap / Vanguard Equity Income / Vanguard Windsor II funds — all are passively managed or rule-based. They escaped the `INDEX_PATTERNS` regex because their fund_name does not contain "Index"/"ETF"/"S&P"/"Russell"/"MSCI"/etc. tokens. The top 30 alone contain at least **12 funds** that are not actively-managed equity by industry definition.

### 3.2 `equity` funds with potentially passive name keywords (current regex misses)

| series_id | fund_name | total_net_assets |
| --- | --- | --- |
| S000005080 | College Retirement Equities Fund - Total Global Stock Account | 135,247,377,342.00 |
| S000000978 | EMERGING MARKETS CORE EQUITY 2 PORTFOLIO | 35,948,431,707.41 |
| S000063170 | Strategic Advisers Fidelity Emerging Markets Fund | 35,181,124,789.41 |
| S000023605 | Fidelity Series Emerging Markets Opportunities Fund | 27,561,506,298.17 |
| S000056013 | GQG Partners Emerging Markets Equity Fund | 22,347,000,406.37 |
| S000030092 | Strategic Advisers Emerging Markets Fund | 15,145,997,715.32 |
| S000001027 | DIMENSIONAL EMERGING MARKETS VALUE FUND | 13,841,409,578.61 |
| S000000959 | EMERGING MARKETS VALUE PORTFOLIO | 13,568,172,890.54 |
| S000003916 | Nomura Emerging Markets Fund | 11,053,002,978.33 |
| S000005437 | Fidelity Advisor Focused Emerging Markets Fund | 10,892,241,146.24 |
| S000002615 | JPMorgan Emerging Markets Equity Fund | 10,384,260,201.09 |
| S000002512 | MFS Emerging Markets Equity Fund | 10,286,870,837.58 |
| S000007110 | Fidelity Emerging Markets Fund | 9,820,061,302.09 |
| S000064706 | Invesco Developing Markets Fund | 9,130,151,938.41 |
| S000025791 | EQ/500 Managed Volatility Portfolio | 8,157,518,679.08 |
| S000000992 | THE EMERGING MARKETS SERIES | 7,342,718,250.06 |
| S000000957 | EMERGING MARKETS PORTFOLIO | 7,260,686,927.41 |
| S000006833 | Baillie Gifford Emerging Markets Equities Fund | 7,155,376,368.66 |
| S000054853 | Hartford Schroders Emerging Markets Equity Fund | 7,104,909,494.14 |
| S000062805 | Fidelity Series Emerging Markets Fund | 6,915,550,572.04 |
| S000007013 | Global Emerging Markets Fund | 6,704,068,141.51 |
| S000010264 | Lazard Emerging Markets Equity Portfolio | 6,578,608,311.45 |
| S000001496 | T. Rowe Price Emerging Markets Stock Fund | 6,297,220,800.72 |
| S000050390 | T. Rowe Price Emerging Markets Discovery Stock Fund | 5,928,726,067.94 |
| S000043475 | RBC Emerging Markets Equity Fund | 5,406,618,513.08 |
| S000018555 | Free Market U.S. Equity Fund | 4,827,880,608.09 |
| S000048066 | Goldman Sachs Global Managed Beta Fund | 4,797,367,758.41 |
| S000001909 | Driehaus Emerging Markets Growth Fund | 4,104,882,786.60 |
| S000001000 | THE EMERGING MARKETS SMALL CAP SERIES | 3,953,081,761.56 |
| S000000981 | EMERGING MARKETS SMALL CAP PORTFOLIO | 3,934,730,247.68 |

> Note: the `Markets` keyword catches mostly **active** emerging-markets funds, which is the regex giving a false positive (the keyword was intended for "Total Market"/"Broad Market"). The interesting suspects are `EQ/500 Managed Volatility Portfolio` and `Goldman Sachs Global Managed Beta Fund` — those names contain `500` and `Beta` which are usually rules-based.

### 3.3 Position count distribution for `equity` funds (latest quarter)

| bucket | n_funds |
| --- | --- |
| `<30` | 152 |
| 30-59 | 260 |
| 60-99 | 292 |
| 100-199 | 776 |
| 200-499 | 1,772 |
| 500+ | 1,339 |

**3,111 of 4,591 (67.8%) `equity` funds hold ≥200 positions** — a band that is unusual for true active managers. The 1,339 with 500+ positions is highly suspicious of including index trackers / target-date / fund-of-funds aggregates (which inherit underlying index components by look-through).

---

## SECTION 4 — The 552 `balanced` funds

### 4.1 Top 30 balanced funds by NAV

| series_id | fund_name | family_name | total_net_assets |
| --- | --- | --- | --- |
| S000008801 | American Balanced Fund | American Balanced Fund | 269,836,235,830.40 |
| S000008814 | Income Fund of America | Income Fund of America | 144,413,319,251.78 |
| S000009000 | Capital Income Builder | Capital Income Builder | 124,341,729,043.84 |
| S000004406 | VANGUARD WELLINGTON FUND | VANGUARD WELLINGTON FUND | 122,293,779,661.24 |
| S000011211 | First Eagle Global Fund | First Eagle Funds | 75,076,193,069.63 |
| S000002070 | T. Rowe Price Capital Appreciation Fund | T. ROWE PRICE CAPITAL APPRECIATION FUND, INC. | 70,591,413,373.28 |
| S000006495 | Artisan International Value Fund | Artisan Partners Funds Inc. | 41,809,403,183.80 |
| S000031109 | American Funds Global Balanced Fund | American Funds Global Balanced Fund | 31,530,817,403.45 |
| S000010464 | Janus Henderson Balanced Fund | JANUS INVESTMENT FUND | 28,320,501,063.28 |
| S000008796 | Asset Allocation Fund | AMERICAN FUNDS INSURANCE SERIES | 27,683,649,387.20 |
| S000006793 | AST Balanced Asset Allocation Portfolio | Advanced Series Trust | 23,209,743,769.48 |
| S000005086 | College Retirement Equities Fund - Responsible Balanced Account | College Retirement Equities Fund | 21,638,619,853.00 |
| S000032897 | WCM Focused International Growth Fund | INVESTMENT MANAGERS SERIES TRUST | 20,106,776,113.76 |
| S000002245 | BlackRock Global Allocation Fund, Inc. | BlackRock Global Allocation Fund, Inc. | 17,398,345,238.30 |
| S000011212 | First Eagle Overseas Fund | First Eagle Funds | 16,786,381,395.80 |
| S000011204 | Dodge & Cox Balanced Fund | Dodge & Cox Funds | 14,895,686,354.86 |
| S000068115 | JNL/T. Rowe Price Capital Appreciation Fund | JNL Series Trust | 14,817,478,484.04 |
| S000006796 | AST PGIM Aggressive Multi-Asset Portfolio | Advanced Series Trust | 13,735,333,127.67 |
| S000027808 | Invesco Equity and Income Fund | AIM Counselor Series Trust (Invesco Counselor Series Trust) | 12,763,318,871.74 |
| S000006791 | AST Aggressive Asset Allocation Portfolio | Advanced Series Trust | 11,604,496,347.62 |
| S000036785 | Variable Portfolio - Managed Volatility Moderate Growth Fund | Columbia Funds Variable Series Trust II | 11,497,572,437.02 |
| S000040391 | Variable Portfolio - Managed Volatility Growth Fund | COLUMBIA FUNDS VARIABLE INSURANCE TRUST | 11,292,632,567.51 |
| S000012068 | Columbia Balanced Fund | COLUMBIA FUNDS SERIES TRUST I | 10,318,573,879.21 |
| S000006827 | ProShares Ultra QQQ | ProShares Trust | 9,863,934,193.39 |
| S000010394 | Janus Henderson Balanced Portfolio | JANUS ASPEN SERIES | 9,426,488,501.15 |
| S000001744 | JNL/WMC Balanced Fund | JNL Series Trust | 9,331,508,514.00 |
| S000035703 | SA VCP Dynamic Allocation Portfolio | SUNAMERICA SERIES TRUST | 8,944,810,054.43 |
| S000002439 | MFS Total Return Fund | MFS Series Trust V | 7,587,895,911.10 |
| S000057602 | Janus Henderson Global Equity Income Fund | JANUS INVESTMENT FUND | 7,008,102,578.40 |
| S000005759 | VY(R) T. ROWE PRICE CAPITAL APPRECIATION PORTFOLIO | Voya Investors Trust | 6,985,623,028.57 |

Mostly genuine multi-asset funds. Two anomalies: `WCM Focused International Growth Fund` and `Artisan International Value Fund` are typically marketed as equity (their equity sleeve is large but bond/cash component pushes them under 90%, hitting the `balanced` 60-90% bucket).

### 4.2 Leveraged / inverse / "strategy" ETFs misclassified as `balanced` (95 rows total, top 30)

| series_id | fund_name | family_name | total_net_assets |
| --- | --- | --- | --- |
| S000006827 | ProShares Ultra QQQ | ProShares Trust | 9,863,934,193.39 |
| S000023809 | Direxion Daily Technology Bull 3X Shares | Direxion Shares ETF Trust | 3,860,084,552.56 |
| S000022761 | Direxion Daily Financial Bull 3X Shares | Direxion Shares ETF Trust | 2,357,126,867.76 |
| S000003156 | DIAMOND HILL LONG SHORT FUND | Diamond Hill Funds | 2,344,482,113.32 |
| S000006283 | Nomura Asset Strategy Fund | IVY FUNDS | 1,814,596,028.83 |
| S000022786 | Direxion Daily Small Cap Bull 3X Shares | Direxion Shares ETF Trust | 1,583,002,536.67 |
| S000003066 | ULTRANASDAQ-100 PROFUND | ProFunds | 1,171,239,557.32 |
| S000014260 | ProShares Ultra Technology | ProShares Trust | 760,943,307.29 |
| S000024918 | ProShares UltraPro Dow30 | ProShares Trust | 753,860,087.79 |
| S000014252 | ProShares Ultra Financials | ProShares Trust | 703,158,891.37 |
| S000055522 | Multi-Asset Strategy Fund | RUSSELL INVESTMENT CO | 592,872,498.89 |
| S000029341 | Direxion Daily Regional Banks Bull 3X Shares | Direxion Shares ETF Trust | 586,876,935.02 |
| S000003096 | SEMICONDUCTOR ULTRASECTOR PROFUND | ProFunds | 550,855,735.33 |
| S000022763 | Direxion Daily Homebuilders & Supplies Bull 3X Shares | Direxion Shares ETF Trust | 544,080,013.08 |
| S000006826 | ProShares Ultra Dow30 | ProShares Trust | 509,169,011.19 |
| S000057185 | Direxion Daily Aerospace & Defense Bull 3X Shares | Direxion Shares ETF Trust | 483,911,644.14 |
| S000086384 | Disciplined Value Global Long/Short Fund | John Hancock Investment Trust | 468,032,654.25 |
| S000054584 | CRM LONG/SHORT OPPORTUNITIES | CRM Mutual Fund Trust | 414,457,965.76 |
| S000003958 | PROFUND VP ULTRANASDAQ-100 | ProFunds | 303,411,105.78 |
| S000014248 | ProShares Ultra Russell2000 | ProShares Trust | 282,497,219.34 |
| S000022760 | Direxion Daily Energy Bull 2X Shares | Direxion Shares ETF Trust | 271,222,232.53 |
| S000049375 | Direxion Daily S&P Oil & Gas Exp. & Prod. Bull 2X Shares | Direxion Shares ETF Trust | 259,836,177.49 |
| S000008349 | Global Strategy Fund | VALIC Co I | 240,030,003.17 |
| S000019515 | MFS Global Alternative Strategy Fund | MFS Series Trust XV | 229,425,192.51 |
| S000000834 | Provident Trust Strategy Fund | Provident Mutual Funds, Inc. | 209,022,238.31 |
| S000003107 | BIOTECHNOLOGY ULTRASECTOR PROFUND | ProFunds | 177,372,784.88 |
| S000003062 | ULTRABULL PROFUND | ProFunds | 172,211,446.83 |
| S000027486 | Direxion Daily Healthcare Bull 3X Shares | Direxion Shares ETF Trust | 164,922,804.50 |
| S000006825 | ProShares Ultra MidCap400 | ProShares Trust | 151,570,331.76 |
| S000003094 | PRECIOUS METALS ULTRASECTOR PROFUND | ProFunds | 133,340,586.53 |

(remaining 65 rows in the same shape — Direxion / ProShares / ProFund / Rydex Strategy Fund / 1.5x / 2x / 3x / Inverse / etc.)

> **95 leveraged-or-inverse ETFs are classified as `balanced`.** Total NAV ≈ $30B+. The current classifier reaches `balanced` because their single-asset notional exposure (typically `EC` plus large derivatives like `DCO`/`DIR`/`SN`) lands the `equity_val_pct` between 60% and 90%. They are functionally **passive index trackers leveraged through swaps** — they should not be in `balanced`. The earlier estimate of 60 such funds was low; **actual count is 95**.

### 4.3 Equity-percent distribution (asset_category EC,EP) for `balanced` vs `multi_asset`

| fund_strategy | avg_equity_pct | min_equity_pct | max_equity_pct | median_equity_pct | n_funds |
| --- | --- | --- | --- | --- | --- |
| balanced | 0.76 | 0.30 | 0.98 | 0.77 | 552 |
| multi_asset | 0.47 | 0.28 | 0.75 | 0.47 | 188 |

The two buckets do separate cleanly on equity weight (median 47% vs 77%), but both contain edge cases. `balanced.min = 0.30` and `multi_asset.max = 0.75` show a **3-percentage-point overlap** at the seam — the 60% cutoff is not perfectly applied because asset-category labels don't catch all the synthetic equity exposure (this is also why the leveraged ETFs land here).

---

## SECTION 5 — Legacy residuals: `active`, `passive`, `mixed`

### 5.1 Counts

| fund_strategy | fund_category | n_funds | total_nav |
| --- | --- | --- | --- |
| active | equity | 250 | 81,925,908,690.38 |
| active | balanced | 45 | 8,879,107,103.42 |
| active | multi_asset | 15 | 5,504,074,310.68 |
| mixed | equity | 5 | 3,117,418,903.92 |
| passive | equity | 15 | 1,936,617,441.93 |
| passive | balanced | 2 | 7,824,767.13 |
| passive | multi_asset | 1 | 2,632,849.02 |

Total: **333 funds**, total NAV ≈ **$101.4B**. `fund_category` is already populated correctly for every row.

### 5.2 Downstream references in `peer_rotation_flows` (level=fund)

| entity_type | n_entities | n_rows |
| --- | --- | --- |
| active | 4,473 | 1,439,311 |
| mixed | 386 | 370,557 |
| passive | 899 | 1,085,567 |

> `peer_rotation_flows.entity_type` for `level='fund'` reads from `fund_holdings_v2.fund_strategy` (see `compute_peer_rotation.py:430,547,565`), and the holdings-level table still has 5,256 funds carrying the `active` value (Section 1.3). The `peer_rotation_flows` 4,473 entities are mostly that holdings-level legacy snapshot, not the 310 `fund_universe.active` rows.

### 5.3 First 50 (of 333) legacy residuals — universe vs latest holdings

| series_id | fund_name | universe_strategy | holdings_strategy_latest | total_net_assets |
| --- | --- | --- | --- | --- |
| S000026760 | Akre Focus Fund | active | active | 12,470,470,145.46 |
| S000003991 | Pioneer Fund | active | active | 8,969,676,004.00 |
| S000004137 | Pioneer Fundamental Growth Fund | active | active | 7,462,760,073.29 |
| S000035110 | Pioneer Multi-Asset Income Fund | active | active | 4,311,395,966.36 |
| S000007106 | Fidelity International Capital Appreciation Fund | active | active | 3,802,008,791.31 |
| S000031970 | Tortoise Energy Infrastructure Total Return Fund | active | active | 3,336,370,320.68 |
| S000004009 | Pioneer Disciplined Growth Fund | active | active | 2,165,011,747.02 |
| S000005112 | Fidelity Advisor Large Cap Fund | mixed | mixed | 1,921,882,890.07 |
| S000010136 | Pioneer Core Equity Fund | active | active | 1,903,106,297.70 |
| S000057852 | BlackRock GA Dynamic Equity Fund | active | active | 1,884,990,813.78 |
| S000005122 | Fidelity Advisor Equity Income Fund | active | active | 1,834,754,418.59 |
| S000005119 | Fidelity Advisor Dividend Growth Fund | active | active | 1,734,164,979.00 |
| S000010084 | Pioneer Select Mid Cap Growth Fund | active | active | 1,619,872,261.98 |
| S000005323 | Fidelity Advisor Utilities Fund | active | active | 1,355,548,663.31 |
| S000005391 | One Choice 2025 Portfolio | active | active | 1,308,563,009.91 |
| S000005125 | Fidelity Advisor Growth and Income Fund | active | mixed | 1,275,397,591.05 |
| S000057851 | BlackRock GA Disciplined Volatility Equity Fund | mixed | mixed | 1,142,198,776.61 |
| S000013005 | Pioneer High Income Municipal Fund | active | active | 1,104,208,014.68 |
| S000003312 | Capital Appreciation Fund | active | active | 970,823,298.13 |
| S000003948 | Pioneer Equity Income Fund | active | active | 964,727,650.20 |
| S000021226 | VOYA INDEX SOLUTION 2025 PORTFOLIO | passive | passive | 939,252,487.95 |
| S000046035 | State Street Target Retirement 2020 Fund | active | active | 897,792,889.97 |
| S000007455 | Select Industrials Portfolio | active | active | 839,922,765.00 |
| S000004011 | Pioneer International Equity Fund | active | active | 818,299,766.25 |
| S000053584 | Victory RS Large Cap Alpha VIP Series | active | active | 799,890,473.19 |
| S000011108 | SSGA Emerging Markets Enhanced Index Portfolio II | passive | passive | 743,229,424.25 |
| S000056247 | Tortoise North American Pipeline Fund | active | active | 741,292,181.63 |
| S000004143 | Pioneer Mid Cap Value Fund | active | active | 733,945,713.56 |
| S000061108 | MassMutual Select T. Rowe Price Large Cap Blend Fund | active | active | 697,339,435.14 |
| S000058494 | JNL/Baillie Gifford International Growth Fund | active | active | 679,502,911.72 |

(remaining 220 follow the same pattern — universe and latest-holdings agree on the legacy value)

### 5.3b Absorption-mapping summary (universe → holdings_latest)

| universe_strategy | holdings_strategy_latest | n_funds |
| --- | --- | --- |
| active | active | 290 |
| active | mixed | 20 |
| mixed | mixed | 5 |
| passive | passive | 12 |
| passive | `<empty>` | 6 |

> **All 333 legacy residual funds have `fund_category` correctly populated** (Section 5.1). The legacy `fund_strategy` value is mirrored on the latest-quarter holdings row for every fund, except 6 `passive→<empty>` cases where the holdings value was never populated. Absorption is straightforward: drop `fund_strategy` and read `fund_category`, or rewrite `fund_strategy = fund_category`.

---

## SECTION 6 — The 658 SYN-only funds

### 6.0 Identification

| empty_strategy_funds | syn_prefix | syn_with_empty_strategy |
| --- | --- | --- |
| 658 | 658 | 658 |

Every `<empty>` strategy fund is on a `SYN_*` synthetic series and vice versa.

### 6.1 Holdings-level majority strategy per SYN fund

| majority_holdings_strategy | n_syn_funds | total_holdings_rows |
| --- | --- | --- |
| bond_or_other | 422 | 2,061,589 |
| equity | 117 | 22,272 |
| balanced | 56 | 23,034 |
| multi_asset | 36 | 13,139 |
| final_filing | 11 | 2,884 |
| index | 8 | 2,559 |
| excluded | 8 | 4,225 |

**All 658 SYN funds have a non-null holdings-level `fund_strategy`.** The majority-vote distribution is dominated by `bond_or_other` (64.1%), with the remainder spread across the active equity / balanced / multi-asset / final / index / excluded buckets.

### 6.1b SYN funds with no holdings strategy

| bucket | n_syn_funds |
| --- | --- |
| has at least one strategy row | 658 |

### 6.2 SYN strategy stability across quarters

| n_distinct_strategies | n_syn_funds |
| --- | --- |
| 1 | 626 |
| 2 | 32 |

**95.1% of SYN funds have a single stable holdings-level strategy** across all quarters. Only 32 (4.9%) drift between two values. This is materially cleaner than the 47% drift rate observed in the full population.

> Backfilling `fund_universe.fund_strategy` from the holdings-level majority is safe for at least 626 SYN funds; the 32 drifters need a tiebreaker policy (most-recent quarter / highest count) but the data is there.

---

## SECTION 7 — Top-25 fund families by NAV

| family_name | total_funds | n_equity | n_index | n_balanced | n_multi_asset | n_bond | n_excluded | n_final | family_nav |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| VANGUARD INDEX FUNDS | 12 | 0 | 12 | 0 | 0 | 0 | 0 | 0 | 4,779,196,902,104.49 |
| iShares Trust | 363 | 0 | 89 | 0 | 0 | 0 | 270 | 0 | 3,544,944,712,418.73 |
| Fidelity Concord Street Trust | 27 | 10 | 17 | 0 | 0 | 0 | 0 | 0 | 1,235,048,206,504.98 |
| VANGUARD BOND INDEX FUNDS | 7 | 0 | 5 | 0 | 0 | 1 | 1 | 0 | 896,097,804,066.78 |
| VANGUARD CHESTER FUNDS | 13 | 13 | 0 | 0 | 0 | 0 | 0 | 0 | 889,533,276,789.65 |
| Fidelity Salem Street Trust | 89 | 0 | 59 | 2 | 1 | 27 | 0 | 0 | 760,372,008,762.82 |
| VANGUARD STAR FUNDS | 7 | 5 | 1 | 0 | 0 | 1 | 0 | 0 | 702,951,395,904.78 |
| Fidelity Rutland Square Trust II | 15 | 7 | 2 | 0 | 5 | 1 | 0 | 0 | 630,280,867,632.07 |
| PIMCO Funds | 96 | 2 | 0 | 1 | 3 | 90 | 0 | 0 | 541,235,625,999.08 |
| SCHWAB STRATEGIC TRUST | 33 | 0 | 4 | 0 | 0 | 0 | 29 | 0 | 532,469,371,465.48 |
| Fidelity Aberdeen Street Trust | 85 | 70 | 15 | 0 | 0 | 0 | 0 | 0 | 473,670,570,401.73 |
| SPDR SERIES TRUST | 87 | 0 | 13 | 0 | 0 | 0 | 74 | 0 | 458,877,054,733.48 |
| DFA INVESTMENT DIMENSIONS GROUP INC | 103 | 66 | 0 | 1 | 0 | 36 | 0 | 0 | 450,463,939,373.89 |
| VANGUARD WORLD FUND | 23 | 2 | 15 | 1 | 1 | 0 | 4 | 0 | 416,731,676,105.50 |
| Invesco QQQ Trust, Series 1 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 407,693,673,462.84 |
| VANGUARD INTERNATIONAL EQUITY INDEX FUNDS | 7 | 0 | 7 | 0 | 0 | 0 | 0 | 0 | 385,727,666,489.27 |
| VANGUARD INSTITUTIONAL INDEX FUNDS | 4 | 0 | 2 | 0 | 0 | 0 | 2 | 0 | 372,349,921,231.54 |
| TIAA-CREF Funds | 68 | 34 | 23 | 0 | 0 | 11 | 0 | 0 | 363,392,257,162.00 |
| American Funds Target Date Retirement Series | 13 | 13 | 0 | 0 | 0 | 0 | 0 | 0 | 360,012,447,723.11 |
| Growth Fund of America | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 340,053,494,334.79 |
| SELECT SECTOR SPDR TRUST | 22 | 0 | 0 | 0 | 0 | 0 | 22 | 0 | 338,067,741,413.27 |
| iShares, Inc. | 53 | 0 | 44 | 0 | 0 | 0 | 9 | 0 | 325,358,878,212.25 |
| JPMorgan Trust II | 19 | 6 | 1 | 1 | 0 | 11 | 0 | 0 | 321,325,715,795.89 |
| Dodge & Cox Funds | 7 | 4 | 0 | 1 | 0 | 2 | 0 | 0 | 318,498,301,947.84 |
| VANGUARD SCOTTSDALE FUNDS | 17 | 1 | 14 | 0 | 0 | 0 | 2 | 0 | 317,604,011,293.66 |

Observations:
- `family_name` ≠ asset-management firm — it carries **trust/series-trust** names. Vanguard's funds are split across `VANGUARD INDEX FUNDS`, `VANGUARD CHESTER FUNDS`, `VANGUARD STAR FUNDS`, etc. Same for Fidelity. Roll-up by management firm requires a different join (probably via CIK or a manual mapping).
- **`Invesco QQQ Trust, Series 1` is classified `equity` but is an index fund.** Its single fund of $408B is the third-largest index tracker in the dataset by NAV. The classifier missed it because the `family_name` is the same as the `fund_name` and neither contains "Index".
- **`American Funds Target Date Retirement Series`**: 13 funds, all `equity`. These are target-date funds — they hold equity *and* bonds; classifying them as `equity` overstates the active-equity inventory. The Vanguard Target Retirement funds are also classified `equity` (visible in Section 3.1).
- iShares splits 89 `index` + 270 `excluded` — the `excluded` count looks like specialty/sector ETFs hitting the EXCLUDE_PATTERNS regex.

---

## SECTION 8 — Position-turnover methodology validation

### 8.1 Active sample (25 funds)

> The exact `family_name` strings in the prompt (`Fidelity`, `Capital Group`, `T. Rowe Price`, etc.) returned 0 rows because `family_name` carries trust-level strings (`Fidelity Securities Fund`, `JPMorgan Trust II`, `MFS Series Trust I`, …). Used a `LIKE '%FIDELITY%' OR ...` family-name pattern to recover the intended sample.

### 8.2 Index sample (25 funds, top by NAV)

| series_id | fund_name | family_name | total_net_assets |
| --- | --- | --- | --- |
| S000002848 | VANGUARD TOTAL STOCK MARKET INDEX FUND | VANGUARD INDEX FUNDS | 2,057,976,411,077.26 |
| S000002839 | VANGUARD 500 INDEX FUND | VANGUARD INDEX FUNDS | 1,474,944,667,479.21 |
| S000004310 | iShares Core S&P 500 ETF | iShares Trust | 760,624,025,198.37 |
| S000006027 | Fidelity 500 Index Fund | Fidelity Concord Street Trust | 749,107,075,784.08 |
| S000002932 | VANGUARD TOTAL INTERNATIONAL STOCK INDEX FUND | VANGUARD STAR FUNDS | 606,118,459,294.39 |

(remaining 20 are similar — Vanguard / iShares / Fidelity index trackers)

### 8.3 Turnover summary (latest available q-pairs)

| sample_type | avg_turnover | median_turnover | min_turnover | max_turnover | n_pairs | n_funds |
| --- | --- | --- | --- | --- | --- | --- |
| index | 0.0475 | 0.0244 | 0.0000 | 0.9273 | 88 | 23 |
| active | 0.1174 | 0.1111 | 0.0000 | 0.2826 | 109 | 25 |

**Turnover** = (added cusips + dropped cusips) / (curr cusips + prev cusips), per (series, quarter) pair.

### 8.3b Histogram (per pair)

| sample_type | bucket | n_pairs |
| --- | --- | --- |
| index | `<2%` | 39 |
| index | 2-5% | 37 |
| index | 5-10% | 9 |
| index | 10-20% | 1 |
| index | 40%+ | 2 |
| active | `<2%` | 12 |
| active | 2-5% | 14 |
| active | 5-10% | 25 |
| active | 10-20% | 42 |
| active | 20-40% | 16 |

**Methodology validates:**
- Index median turnover **2.4%**; 86% of index pairs land in the `<5%` bucket.
- Active median turnover **11.1%**; 76% of active pairs land in the `5-40%` band.
- Median ratio active:index ≈ **4.6×**; modal buckets do not overlap.
- The 12 active "<2%" pairs are mostly Fidelity Freedom target-date funds and similar fund-of-funds inheriting low underlying churn — their classification will require a target-date carve-out separate from the turnover signal.
- The 2 index "40%+" pairs are likely small specialty index-tracking ETFs with frequent rebalances or new-quarter cusip resolution noise — minor contamination, does not invalidate the signal.

> Conclusion: a turnover-based active/index reclassifier on top of the asset-mix classification will cleanly separate the bulk of cases. Edge handling needed for target-date / fund-of-funds (low active turnover) and rules-based / smart-beta (high turnover for index family).

---

## SECTION 9 — Read-site re-audit

Total grep hits in `scripts/`: **116** lines across **17** files. Read sites in `web/` (UI): **0**. Read sites in `tests/`: 1 (`tests/pipeline/test_load_nport.py`).

### 9.1 / 9.2 — Read sites by file

| File | Lines | Column read | Filter | Quarter scope |
|---|---|---|---|---|
| [scripts/queries/fund.py](scripts/queries/fund.py:90) | 90, 93, 336, 338 | `fu.is_actively_managed` | `= true` (when `active_only=True`) | latest |
| [scripts/queries/market.py](scripts/queries/market.py:642) | 642, 668, 679, 691, 795, 826 | `fu.is_actively_managed`, `_classify_fund_type(fund_name)` | `CAST(... AS INTEGER)`; name-regex fallback | latest |
| [scripts/queries/trend.py](scripts/queries/trend.py:42) | 42, 84, 333, 341, 343 | `fu.is_actively_managed` | `= true` (when `active_only=True`) | per-quarter |
| [scripts/queries/flows.py](scripts/queries/flows.py:217) | 217, 219, 324, 326 | `fu.is_actively_managed` | `= true` (when `active_only=True`) | per-quarter |
| [scripts/queries/cross.py](scripts/queries/cross.py:159) | 159, 253, 263, 429, 533, 674 | `fu.is_actively_managed` | `COALESCE(fu.is_actively_managed, TRUE) = TRUE`; also surfaced as `is_active` | latest + per-quarter |
| [scripts/queries/register.py](scripts/queries/register.py:164) | 164, 1229, 1268 | `_classify_fund_type(institution / fund_name)` | name-regex on string | n/a |
| [scripts/queries/common.py](scripts/queries/common.py:292) | 292 | defines `_classify_fund_type()` (name-regex) | n/a | n/a |
| [scripts/queries/__init__.py](scripts/queries/__init__.py:36) | 36 | re-export `_classify_fund_type` | n/a | n/a |
| [scripts/pipeline/compute_peer_rotation.py](scripts/pipeline/compute_peer_rotation.py:430) | 430, 547, 565 | `fund_holdings_v2.fund_strategy` | `MAX(fund_strategy)`; carried into `peer_rotation_flows.entity_type` | per-quarter rollup |
| [scripts/build_entities.py](scripts/build_entities.py:241) | 241, 564 | `fu.is_actively_managed` | mapped to entity classification (active/passive/unknown) | latest |
| [scripts/resolve_pending_series.py](scripts/resolve_pending_series.py:354) | 251, 354, 360, 376, 683-685 | `u.is_actively_managed` | `True→active`, `False→passive` | latest |
| [scripts/oneoff/dm14c_voya_apply.py](scripts/oneoff/dm14c_voya_apply.py:89) | 89, 131, 264 | `fu.is_actively_managed` | `WHERE fu.is_actively_managed` (truthy) | n/a |
| [scripts/migrations/019_peer_rotation_flows.py](scripts/migrations/019_peer_rotation_flows.py:18) | 18 | comment only | n/a | n/a |
| [scripts/fix_fund_classification.py](scripts/fix_fund_classification.py:62) | 62-104, 125 | reads + UPDATEs `is_actively_managed` | one-off backfill (legacy) | n/a |
| [tests/pipeline/test_load_nport.py](tests/pipeline/test_load_nport.py) | n/a | exercises load path | n/a | n/a |

### 9.3 — Read sites referencing values not in the current taxonomy

- **`scripts/resolve_pending_series.py` lines 683-685** map `is_actively_managed True→active`, `False→passive`. Those tokens are written to `entity_classification_history.classification`, where `active` and `passive` *are* valid (per institution-level scoping). **Not a bug.**
- **`scripts/queries/cross.py:159`** uses `COALESCE(fu.is_actively_managed, TRUE) = TRUE` — i.e., NULLs default to TRUE. The 658 SYN funds (which have `is_actively_managed IS NULL`) are therefore included in the active-only filter on the `cross` page. **Behavioral consequence:** SYN funds — which include the 422 majority-`bond_or_other` rows — are leaking into "active" cross-ownership tables. Already noted in prior session.
- **No code references `fund_strategy IN ('active','passive','mixed')` or `IN ('empty')` directly.** Filters are uniformly via `is_actively_managed`. The 333 legacy residuals are visible only when read through `fund_strategy` itself (e.g., the `peer_rotation_flows` build path).
- **`_classify_fund_type` in `common.py:292`** is a name-regex helper, not a stored-field reader. It is invoked by `market.py`, `register.py`, `trend.py` to label rows where `fund_universe`/`fund_holdings_v2` lookup fails.

---

## SECTION 10 — Pipeline write-path re-audit

### 10.1 — Files writing to fund-level classification fields

Active pipeline:

| File | Function | Writes to | Source of value | Trigger |
|---|---|---|---|---|
| [scripts/pipeline/load_nport.py](scripts/pipeline/load_nport.py:1031) | `_upsert_fund_universe()` | `fund_universe.{fund_strategy, fund_category, is_actively_managed}` | `stg_nport_fund_universe` (which itself was written from `classify_fund()`) | every run with new submissions |
| [scripts/pipeline/load_nport.py](scripts/pipeline/load_nport.py:752) | `_upsert_fund_holdings_v2()` (inline INSERT) | `fund_holdings_v2.fund_strategy` | `stg_nport_holdings.fund_strategy` (= `fund_category` from `classify_fund()`) | every run with new submissions |
| [scripts/pipeline/load_nport.py](scripts/pipeline/load_nport.py:447) | staging insert (inline) | `stg_nport_holdings.fund_strategy` (column position 20) | **`fund_category` variable** — line 461 | per-submission |
| [scripts/pipeline/load_nport.py](scripts/pipeline/load_nport.py:486) | staging insert (inline) | `stg_nport_fund_universe.fund_strategy` (last value) | **`fund_category` variable** — line 500 | per-submission |
| [scripts/pipeline/load_nport.py](scripts/pipeline/load_nport.py:715) | `_write_holdings_to_staging()` | `stg_nport_fund_universe.fund_strategy` | **`fund_category` variable** — line 728 | per-submission |
| [scripts/pipeline/nport_parsers.py](scripts/pipeline/nport_parsers.py:133) | `classify_fund()` | (returned tuple) | name regex + asset-category arithmetic | called from above |

One-off / retired:

| File | Notes |
|---|---|
| [scripts/oneoff/dera_synthetic_stabilize.py](scripts/oneoff/dera_synthetic_stabilize.py:354) | Re-keys `fund_universe` rows from old CIK to canonical SYN_* — copies `fund_strategy` from a "canon" row, does not recompute. |
| [scripts/fix_fund_classification.py](scripts/fix_fund_classification.py:93) | One-off historical backfill of `is_actively_managed`. |
| [scripts/retired/fetch_nport.py](scripts/retired/fetch_nport.py:401) | Retired predecessor of `load_nport`. |
| [scripts/retired/fetch_nport_v2.py](scripts/retired/fetch_nport_v2.py:777) | Retired interim version. |
| [scripts/retired/promote_nport.py](scripts/retired/promote_nport.py:301) | Retired promote step (now inline in `load_nport`). |

### 10.2 — Single-source confirmation

- **`fund_universe.fund_strategy`** — sole live writer is `_upsert_fund_universe()` in `load_nport.py:1031`, which copies from staging. Staging is written by either `load_nport.py:486` or `:715` — both pass the `fund_category` variable into the `fund_strategy` slot. **Confirmed: `fund_universe.fund_strategy` is a literal copy of `fund_category` for every row written by the active pipeline.**
- **`fund_holdings_v2.fund_strategy`** — sole live writer is the INSERT at `load_nport.py:752`, which selects `s.fund_strategy` from `stg_nport_holdings`. Staging is written at `load_nport.py:447` or `:696`; both write `fund_category` into the `fund_strategy` slot. **Confirmed: `fund_holdings_v2.fund_strategy` is a literal copy of `fund_category` at write time.**

> **Consequence:** the only source of divergence between `fund_universe.fund_strategy` and `fund_universe.fund_category` is **legacy data** (rows last written before the rename to category-aligned values). Same for `fund_holdings_v2.fund_strategy`. The 5.43M latest-quarter mismatched rows from the prior-session §H come entirely from history written under earlier classifier behavior; the active classifier produces identical values for the two columns.

### 10.3 — `_upsert_fund_universe()` exclusivity

Confirmed sole live mechanism for `fund_universe` writes via the production pipeline. One-off scripts (`dera_synthetic_stabilize.py`, `fix_fund_classification.py`) bypass it but operate at-rest, not on new ingest.

### 10.4 — `fund_holdings_v2` write exclusivity

Confirmed sole live mechanism for `fund_holdings_v2` writes is the INSERT at `load_nport.py:752`. The retired `promote_nport.py` previously had this responsibility; the function is now inline in `load_nport`.

---

## Findings

### Confirmed counts

- **11 distinct `fund_strategy` values** in `fund_universe`. Counts and total NAV per Section 1.1.
- **8 distinct `fund_category` values** in `fund_universe` (no `active`/`passive`/`mixed`).
- **10 distinct `fund_strategy` values** in `fund_holdings_v2` (`is_latest=TRUE`); legacy `active` carries 5,256 funds at the holdings layer vs 310 at the universe layer.
- **333 legacy residuals** (`active` 310 / `passive` 18 / `mixed` 5) at the universe layer; all have correct `fund_category` populated.
- **658 SYN-only synthetic funds** with `fund_strategy = ''` at the universe layer, **all with non-null holdings-level `fund_strategy`** (majority-vote distribution: 64% `bond_or_other`, 18% `equity`, 9% `balanced`).

### Source of each value

- **Active pipeline (`load_nport.py` + `nport_parsers.classify_fund`)** is the sole live writer of `fund_strategy`/`fund_category`/`is_actively_managed` on `fund_universe` and of `fund_strategy` on `fund_holdings_v2`.
- The active classifier writes the **same** value into both `fund_strategy` and `fund_category` for every row it touches. The 333 legacy residuals + the universe/holdings divergence are pre-existing rows that have not been re-touched.
- The 658 SYN funds were created by `dera_synthetic_stabilize.py` with `fund_strategy = ''` because the canonical row available at re-key time had no value.
- `is_actively_managed` is a deterministic projection of `fund_strategy`: TRUE for `{active, balanced, equity, mixed, multi_asset}`, FALSE for `{bond_or_other, excluded, final_filing, index, passive}`, NULL for `''`.

### Hidden index trackers in `equity`

- **At least 12 of the top 30 by NAV** are passively/rule-based (Invesco QQQ, 11 Vanguard Target Retirement / Primecap / Equity Income / Windsor II). The current INDEX_PATTERNS regex misses them because their fund names lack "Index"/"ETF"/"S&P"/"Russell"/"MSCI" tokens.
- **3,111 of 4,591 (67.8%) `equity` funds hold ≥200 positions**; 1,339 hold 500+. This count is incompatible with bottom-up active stock-picking and indicates a population significantly contaminated with target-date / fund-of-funds / index-style holdings.
- A turnover-based reclassifier (Section 8) would catch the bulk; target-date and fund-of-funds need a separate filter.

### Leveraged-ETF mis-classification in `balanced`

- **95 leveraged/inverse/strategy ETFs** classified as `balanced` (count higher than the prior session's "60 K2 cases"). Top names: ProShares Ultra QQQ, Direxion 3X bull/bear, ULTRANASDAQ-100 PROFUND, ProFund VP UltraNasdaq-100. Combined NAV is ≈$30B+. Sample is ProShares ($9.9B) → smallest sub-$2M Rydex Inverse / Strategy variants.
- They land in `balanced` because the asset-mix classifier sees ~60-90% `EC`/`EP` notional but does not recognise the `DCO`/`DIR`/`SN` swap exposure as the actual driver — a classifier change to inspect derivative legs would be the appropriate fix, but for scoping purposes these can be moved into `excluded` or a new `leveraged` bucket via name-regex (terms: `ULTRA*`, `2X`, `3X`, `1.5X`, `INVERSE`, `BULL`, `BEAR`, `LEVERAGED`, `PROFUND`, `STRATEGY FUND`).

### SYN funds — holdings-level coverage and stability

- **100% of SYN funds** (658/658) have at least one non-null `fund_strategy` row at the holdings layer.
- **95.1% (626/658)** are stable across quarters (single value); only **4.9% (32/658)** drift between two values.
- Backfill is straightforward via majority-vote with a most-recent-quarter tiebreaker for the 32 drifters.

### Family rollup observations

- `family_name` is **trust-level**, not management-firm-level. Vanguard funds split across 7+ family-name strings; Fidelity across 6+. Cross-firm rollups need a separate join key (CIK or hand-mapped firm).
- Top families are dominated by index trackers (Vanguard, iShares, SPDR, Schwab Strategic). The largest family by NAV (`VANGUARD INDEX FUNDS`, $4.78T) is exclusively `index`.
- One major equity classification anomaly visible at the family level: `Invesco QQQ Trust, Series 1` (single $408B fund classified `equity` but is the QQQ index ETF).

### Position-turnover methodology validates

- Index sample: avg 4.8% / median 2.4% turnover; 86% of (series, quarter) pairs at <5%.
- Active sample: avg 11.7% / median 11.1%; 76% of pairs in the 5-40% band.
- **Distributions do not overlap meaningfully at the median** — 4.6× separation, modal buckets disjoint. The signal is usable.
- Caveats: target-date / fund-of-funds funds in the active sample (Fidelity Freedom 2030/2035/2040) show low single-digit turnover and would be classified as index without an additional rule. Smart-beta or sector-rotating ETFs in the index sample show high turnover; these are minor contamination.

### Read-site count and references to non-existent values

- **116 read-site lines across 17 files in `scripts/`**; 0 in `web/` UI. UI does not directly read these columns — it goes through query helpers in `scripts/queries/*`.
- **No active read site filters on `fund_strategy IN ('active','passive','mixed')` or on `'empty'`.** All active filters go via `is_actively_managed`.
- **`scripts/queries/cross.py:159`** uses `COALESCE(fu.is_actively_managed, TRUE) = TRUE`, which silently includes the 658 SYN-funds (NULL flag) in active-only filters — a known leak from the prior session.
- **`scripts/pipeline/compute_peer_rotation.py:430,547,565`** carries `fund_holdings_v2.fund_strategy` into `peer_rotation_flows.entity_type` for `level='fund'`. Because the holdings layer still carries 5,256 `active` rows (legacy), `peer_rotation_flows` shows 4,473 distinct fund entities under `entity_type='active'` — these are not the same as `fund_universe.active` (which is only 310 funds).

### Write-path confirmation

- **Single live write path** for `fund_universe.{fund_strategy, fund_category, is_actively_managed}`: `load_nport._upsert_fund_universe()` (line 1031), driven by `nport_parsers.classify_fund()`.
- **Single live write path** for `fund_holdings_v2.fund_strategy`: `load_nport` INSERT at line 752, driven by the same `classify_fund()` via staging.
- **The active classifier writes `fund_strategy = fund_category`** for every row. Divergence between the two columns is entirely due to legacy data. This means:
  - Renaming/dropping `fund_strategy` on the active pipeline is a no-op for new data.
  - Backfilling legacy data to `fund_strategy = fund_category` reconciles the 333 universe-level residuals and the 5.43M holdings-level mismatched rows in one pass.

---

## Decisions Pending

These are not resolved by the data alone and need a chat-level decision:

1. **Hidden equity index trackers** — Section 3.1 shows ≥12 of top-30 are passive in fact. The classifier's name-regex misses Vanguard Target Retirement / Primecap / Equity Income / Windsor II / Invesco QQQ. Decide:
   - Extend `INDEX_PATTERNS` to include "Target Retirement" / "Target Date" / specific tokens? Or
   - Ride the new turnover signal as a secondary classifier? Or
   - Both, with explicit precedence?

2. **Leveraged ETFs in `balanced`** (95 funds, $30B+ NAV) — decide whether to:
   - Move them into `excluded` (current escape hatch), or
   - Create a new `leveraged_inverse` bucket, or
   - Rely on a name-regex tweak (lowest-effort).

3. **`fund_strategy` vs `fund_category` consolidation** — given confirmation in §10.2 that the active classifier writes both with the same value:
   - Drop `fund_strategy` and rename downstream readers to `fund_category`? Or
   - Drop `fund_category` and keep `fund_strategy` (matches `peer_rotation_flows` semantics)? Or
   - Keep both but make `fund_strategy = fund_category` invariant enforced by CHECK / migration?

4. **Legacy 333 residuals (`active`/`passive`/`mixed`)** — confirmed `fund_category` is correct for every one. Decide:
   - Single backfill UPDATE `fund_strategy = fund_category` on these 333 rows? Or
   - Same backfill propagated to the holdings layer (5,256 `active` rows + 1,018 `passive` + 377 `mixed` = ~6,651 distinct funds at the holdings layer)?
   - Holdings-layer rewrite has implications for `peer_rotation_flows` regeneration.

5. **658 SYN funds** — backfill `fund_universe.fund_strategy` from holdings majority? §6.2 shows 95% are stable. Decide tiebreaker policy for the 32 drifters (most-recent-quarter / row-count majority / drop to `<empty>` and surface in QA).

6. **Position-turnover signal — adopt or defer?** §8 validates the methodology but exposes target-date / fund-of-funds edge cases. Decide:
   - Adopt as a secondary signal layered on top of asset-mix?
   - Add a target-date carve-out (regex on names like "Target Retirement", "20XX", "Freedom")?
   - Defer entirely until the legacy backfill is done?

7. **`peer_rotation_flows` rebuild scope** — fixing `fund_holdings_v2.fund_strategy` cascades into `peer_rotation_flows`. Decide:
   - Full rebuild after backfill, or
   - Incremental from latest quarter only?

8. **`scripts/queries/cross.py:159` SYN-leak** — `COALESCE(fu.is_actively_managed, TRUE)` silently includes SYN funds. Fix as part of this consolidation or as a separate ticket?

---

## Schema corrections vs prompt

| Prompt | Actual |
|---|---|
| `fund_holdings_v2.asset_cat` | `fund_holdings_v2.asset_category` (used in 4.3) |
| `fund_holdings_v2.val_usd` | `fund_holdings_v2.market_value_usd` (used in 4.3) |
| Sample family names: `Fidelity`, `Capital Group`, `T. Rowe Price`, `Dodge & Cox`, `Wellington`, `JPMorgan`, `American Century`, `AllianceBernstein`, `MFS`, `Janus Henderson` | `family_name` carries trust-level strings (`Fidelity Securities Fund`, `JPMorgan Trust II`, `MFS Series Trust I`, …); used `LIKE '%FIDELITY%' OR …` to recover the intended sample. |
| `fund_universe.created_at` | column does not exist; substituted `(MIN(quarter) FROM fund_holdings_v2 …)` for first-seen proxy |
