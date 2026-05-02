# fund-orphan-backfill — Phase 2 dry-run manifest

_Generated: 2026-05-01T23:48:44Z_

## Inventory re-validation

- Distinct orphan series (`is_latest=TRUE`): **302**
- Orphan rows: **160,934**
- Orphan AUM: **$658,486,891,871.78**

Expected per PR #244 audit: 302 / 160,934 / $658,486,891,871.78. Drift within ±5%.

## Group totals by derived_strategy (INSERT scope)

| Strategy | Series | Rows | AUM (USD) |
|---|---:|---:|---:|
| bond_or_other | 133 | 119,701 | $558,685,814,130.34 |
| excluded | 136 | 17,619 | $66,911,675,805.61 |
| passive | 25 | 13,047 | $20,297,205,366.04 |
| multi_asset | 1 | 7,152 | $2,540,851,766.07 |
| active | 6 | 231 | $26,690,698.17 |
| **TOTAL (INSERTs)** | **301** | **157,750** | **$648,462,237,766.23** |

## SKIP list (per-fund-deferred-decisions P3)

_No S9-digit orphan series matched the SKIP-name patterns._ Calamos Global Total Return Fund and Eaton Vance Tax-Advantaged Dividend Income Fund both currently funnel into `series_id='UNKNOWN'` (UNKNOWN_literal cohort), which is orphan by design and out of scope for this PR.

## Manifest (sorted by row_count DESC)

| series_id | fund_name | derived_strategy | support_pct | rows | AUM (USD) | source |
|---|---|---|---:|---:|---:|---|
| `S000009238` | Tax Exempt Bond Fund of America | bond_or_other | 100.0% | 10,606 | $48,164,858,423.52 | majority |
| `S000009229` | American High-Income Municipal Bond Fund | bond_or_other | 100.0% | 7,418 | $26,592,802,561.94 | majority |
| `S000045538` | Blackstone Alternative Multi-Strategy Fund | multi_asset | 100.0% | 7,152 | $2,540,851,766.07 | override |
| `S000009231` | Bond Fund of America | bond_or_other | 100.0% | 5,801 | $101,149,751,896.57 | majority |
| `S000008396` | VOYA INTERMEDIATE BOND FUND | bond_or_other | 100.0% | 5,016 | $21,316,654,174.20 | majority |
| `S000029560` | AB Municipal Income Shares | bond_or_other | 100.0% | 4,654 | $34,589,457,486.90 | majority |
| `S000002536` | MFS Municipal Income Fund | bond_or_other | 100.0% | 4,384 | $12,649,956,485.44 | majority |
| `S000062381` | Advantage CoreAlpha Bond Master Portfolio | bond_or_other | 100.0% | 4,152 | $1,570,873,539.85 | majority |
| `S000008760` | VOYA INTERMEDIATE BOND PORTFOLIO | bond_or_other | 100.0% | 3,905 | $1,845,505,996.60 | majority |
| `S000009237` | Limited Term Tax Exempt Bond Fund of America | bond_or_other | 100.0% | 3,843 | $11,891,700,568.97 | majority |
| `S000047257` | FlexShares Credit-Scored US Corporate Bond Index Fund | passive | 100.0% | 3,500 | $1,536,018,829.54 | majority |
| `S000027417` | Global Opportunities Portfolio | bond_or_other | 100.0% | 2,964 | $24,585,991,300.34 | majority |
| `S000009236` | Intermediate Bond Fund of America | bond_or_other | 100.0% | 2,849 | $28,536,743,012.33 | majority |
| `S000009240` | Capital World Bond Fund | bond_or_other | 100.0% | 2,574 | $9,864,997,061.99 | majority |
| `S000001913` | CCM Community Impact Bond Fund | bond_or_other | 100.0% | 2,574 | $3,839,409,901.08 | majority |
| `S000029761` | Global Macro Absolute Return Advantage Portfolio | bond_or_other | 100.0% | 2,484 | $11,643,930,914.34 | majority |
| `S000005247` | Global Macro Portfolio | bond_or_other | 100.0% | 2,461 | $6,137,825,234.57 | majority |
| `S000062125` | FlexShares High Yield Value - Scored Bond Index Fund | passive | 100.0% | 2,146 | $2,917,334,705.43 | majority |
| `S000009981` | AB HIGH INCOME FUND INC | bond_or_other | 100.0% | 2,135 | $6,245,251,554.77 | majority |
| `S000017994` | Emerging Markets Local Income Portfolio | bond_or_other | 100.0% | 2,067 | $3,002,834,052.54 | majority |
| `S000010128` | AB GLOBAL BOND FUND, INC. | bond_or_other | 100.0% | 1,788 | $7,406,895,027.37 | majority |
| `S000048895` | Virtus Newfleet Multi-Sector Bond ETF | excluded | 100.0% | 1,765 | $690,965,825.68 | majority |
| `S000008394` | VOYA GNMA INCOME FUND | bond_or_other | 100.0% | 1,609 | $2,772,632,410.93 | majority |
| `S000050613` | FlexShares Credit-Scored US Long Corporate Bond Index Fund | passive | 100.0% | 1,600 | $82,525,446.61 | majority |
| `S000001147` | TCW METWEST TOTAL RETURN BOND FUND | bond_or_other | 100.0% | 1,552 | $33,663,672,206.91 | majority |
| `S000073362` | FlexShares ESG & Climate Investment Grade Corporate Core Index Fund | passive | 100.0% | 1,474 | $77,555,072.92 | majority |
| `S000013585` | Short-Term Bond Fund of America | bond_or_other | 100.0% | 1,432 | $12,596,046,447.45 | majority |
| `S000010066` | Series E (Total Return Bond Series) | bond_or_other | 100.0% | 1,422 | $454,328,089.71 | majority |
| `S000022423` | Senior Debt Portfolio | bond_or_other | 100.0% | 1,349 | $13,746,830,859.42 | majority |
| `S000000714` | Western Asset Core Plus Bond Fund | bond_or_other | 100.0% | 1,296 | $4,214,251,155.53 | majority |
| `S000072763` | MassMutual Global Credit Income Opportunities Fund | bond_or_other | 100.0% | 1,078 | $281,507,133.40 | majority |
| `S000011831` | ELFUN INCOME FUND | bond_or_other | 100.0% | 1,059 | $134,664,651.84 | majority |
| `S000009230` | American High Income Trust | bond_or_other | 100.0% | 1,027 | $26,300,655,375.68 | majority |
| `S000084823` | Stratified LargeCap Index ETF | passive | 100.0% | 1,012 | $242,113,018.28 | majority |
| `S000000713` | Western Asset Core Bond Fund | bond_or_other | 100.0% | 1,010 | $1,947,342,244.06 | majority |
| `S000069946` | Humankind U.S. Stock ETF | excluded | 100.0% | 998 | $162,510,100.38 | majority |
| `S000010934` | Federated Hermes Institutional High Yield Bond Fund | bond_or_other | 100.0% | 986 | $11,700,322,704.11 | majority |
| `S000049584` | Aspiriant Risk-Managed Municipal Bond Fund | bond_or_other | 100.0% | 976 | $1,215,171,243.75 | majority |
| `S000011830` | ELFUN TAX EXEMPT INCOME FUND | bond_or_other | 100.0% | 964 | $1,643,298,075.97 | majority |
| `S000005235` | HIGH INCOME OPPORTUNITIES PORTFOLIO | bond_or_other | 100.0% | 962 | $3,471,339,785.82 | majority |
| `S000054054` | Emerging Markets Core Fund | bond_or_other | 100.0% | 945 | $1,505,857,274.82 | majority |
| `S000046193` | FlexShares Disciplined Duration MBS Index Fund | passive | 100.0% | 942 | $177,083,819.08 | majority |
| `S000008266` | SDIT Ultra Short Duration Bond Fund | bond_or_other | 100.0% | 922 | $395,161,419.09 | majority |
| `S000009768` | AFL CIO Housing Investment Trust | bond_or_other | 100.0% | 874 | $7,388,534,378.77 | majority |
| `S000006439` | INTERMEDIATE-TERM MUNICIPAL FUND | bond_or_other | 100.0% | 839 | $1,532,878,329.25 | majority |
| `S000008267` | SDIT Short Duration Government Fund | bond_or_other | 100.0% | 825 | $1,347,232,063.33 | majority |
| `S000002530` | MFS California Municipal Bond Fund | bond_or_other | 100.0% | 804 | $1,459,856,944.95 | majority |
| `S000005237` | Core Bond Portfolio | bond_or_other | 100.0% | 765 | $1,712,108,688.75 | majority |
| `S000017995` | International Income Portfolio | bond_or_other | 100.0% | 710 | $245,867,511.85 | majority |
| `S000012064` | Colorado BondShares A Tax Exempt Fund | bond_or_other | 100.0% | 652 | $2,761,676,242.56 | majority |
| `S000085069` | Palmer Square Credit Opportunities ETF | excluded | 100.0% | 619 | $214,418,731.98 | majority |
| `S000003467` | Sit Tax-Free Income Fund | bond_or_other | 100.0% | 616 | $245,559,625.76 | majority |
| `S000065357` | QRAFT AI-Enhanced U.S. Large Cap ETF | excluded | 100.0% | 603 | $32,953,196.03 | majority |
| `S000065273` | Leader Capital High Quality Income Fund | bond_or_other | 100.0% | 601 | $3,751,193,731.12 | majority |
| `S000011063` | Bernstein Intermediate Duration Institutional Portfolio | bond_or_other | 100.0% | 598 | $943,728,853.89 | majority |
| `S000010055` | Series P (High Yield Series) | bond_or_other | 100.0% | 581 | $56,729,462.82 | majority |
| `S000028884` | Cohen & Steers Preferred Securities & Income Fund, Inc. | bond_or_other | 100.0% | 581 | $14,830,779,543.74 | majority |
| `S000058704` | AB Impact Municipal Income Shares | bond_or_other | 100.0% | 571 | $1,247,595,663.20 | majority |
| `S000010876` | AB Corporate Income Shares | bond_or_other | 100.0% | 569 | $348,747,065.31 | majority |
| `S000002523` | MFS North Carolina Municipal Bond Fund | bond_or_other | 100.0% | 567 | $1,040,376,676.80 | majority |
| `S000002534` | MFS Massachusetts Municipal Bond Fund | bond_or_other | 100.0% | 539 | $785,911,578.83 | majority |
| `S000040553` | Series F (Floating Rate Strategies Series) | bond_or_other | 100.0% | 537 | $97,310,047.95 | majority |
| `S000008269` | SDIT GNMA FUND | bond_or_other | 100.0% | 532 | $21,718,479.24 | majority |
| `S000035596` | FlexShares Ultra-Short Income Fund | bond_or_other | 100.0% | 524 | $2,793,161,867.16 | majority |
| `S000006430` | SHORT DURATION MUNICIPAL FUND | bond_or_other | 100.0% | 510 | $746,439,529.12 | majority |
| `S000001146` | TCW METWEST LOW DURATION BOND FUND | bond_or_other | 100.0% | 508 | $1,029,781,127.66 | majority |
| `S000079831` | Cyber Hornet S&P 500 and Bitcoin 75/25 Strategy ETF | passive | 100.0% | 505 | $6,088,753.80 | majority |
| `S000029838` | AB Taxable Multi-Sector Income Shares | bond_or_other | 100.0% | 500 | $955,421,778.93 | majority |
| `S000051713` | Cohen & Steers Low Duration Preferred and Income Fund, Inc. | bond_or_other | 100.0% | 500 | $3,671,495,441.89 | majority |
| `S000081361` | CCM Affordable Housing MBS ETF | excluded | 100.0% | 496 | $221,172,209.63 | majority |
| `S000064832` | Preferred Securities and Income SMA Shares | bond_or_other | 100.0% | 492 | $869,788,587.16 | majority |
| `S000001151` | TCW METWEST ULTRA SHORT BOND FUND | bond_or_other | 100.0% | 483 | $96,580,961.81 | majority |
| `S000001152` | TCW METWEST STRATEGIC INCOME FUND | bond_or_other | 100.0% | 479 | $53,466,689.51 | majority |
| `S000002524` | MFS Pennsylvania Municipal Bond Fund | bond_or_other | 100.0% | 468 | $364,125,402.16 | majority |
| `S000002527` | MFS Virginia Municipal Bond Fund | bond_or_other | 100.0% | 468 | $701,558,601.26 | majority |
| `S000009129` | High Yield Bond Core Fund | bond_or_other | 100.0% | 463 | $1,046,920,104.31 | majority |
| `S000083030` | Federated Hermes Total Return Bond ETF | excluded | 100.0% | 454 | $355,271,689.46 | majority |
| `S000002533` | MFS Maryland Municipal Bond Fund | bond_or_other | 100.0% | 454 | $303,928,922.70 | majority |
| `S000080680` | TEXAS CAPITAL TEXAS EQUITY INDEX ETF | passive | 100.0% | 436 | $65,999,811.77 | majority |
| `S000009127` | Mortgage Core Fund | bond_or_other | 100.0% | 430 | $5,558,675,471.15 | majority |
| `S000055298` | Destra Flaherty & Crumrine Preferred and Income Fund | bond_or_other | 100.0% | 429 | $448,787,495.91 | majority |
| `S000005797` | Hawaii Municipal Bond Fund | bond_or_other | 100.0% | 428 | $339,078,972.02 | majority |
| `S000081302` | American Beacon AHL Trend ETF | excluded | 100.0% | 428 | $91,193,521.47 | majority |
| `S000002525` | MFS South Carolina Municipal Bond Fund | bond_or_other | 100.0% | 426 | $439,857,888.60 | majority |
| `S000009068` | Federated Hermes Sustainable High Yield Bond Fund, Inc. | bond_or_other | 100.0% | 400 | $491,744,551.83 | majority |
| `S000094625` | Federated Hermes MDT Market Neutral ETF | excluded | 100.0% | 397 | $26,707,352.29 | majority |
| `S000051233` | COMMUNITY DEVELOPMENT FUND | bond_or_other | 100.0% | 390 | $607,913,213.62 | majority |
| `S000059080` | Virtus InfraCap U.S. Preferred Stock ETF | excluded | 100.0% | 379 | $5,036,993,133.11 | majority |
| `S000002532` | MFS Georgia Municipal Bond Fund | bond_or_other | 100.0% | 375 | $225,035,532.25 | majority |
| `S000002529` | MFS Arkansas Municipal Bond Fund | bond_or_other | 100.0% | 374 | $284,027,421.70 | majority |
| `S000002522` | MFS New York Municipal Bond Fund | bond_or_other | 100.0% | 363 | $360,778,338.91 | majority |
| `S000089355` | Eventide US Market ETF | excluded | 100.0% | 349 | $264,261,583.60 | majority |
| `S000088672` | Indexperts Gorilla Aggressive Growth ETF | excluded | 100.0% | 344 | $84,670,598.24 | majority |
| `S000011654` | Sit U S Government Securities Fund Inc | bond_or_other | 100.0% | 329 | $404,323,018.92 | majority |
| `S000001149` | TCW METWEST HIGH YIELD BOND FUND | bond_or_other | 100.0% | 322 | $409,448,473.71 | majority |
| `S000045497` | Guggenheim Strategy Fund III | bond_or_other | 100.0% | 318 | $252,847,752.40 | majority |
| `S000074173` | Federated Hermes Short Duration Corporate ETF | excluded | 100.0% | 317 | $126,613,378.42 | majority |
| `S000002521` | MFS Alabama Municipal Bond Fund | bond_or_other | 100.0% | 310 | $136,032,557.69 | majority |
| `S000072765` | MassMutual Global Floating Rate Fund | bond_or_other | 100.0% | 303 | $124,770,445.01 | majority |
| `S000009070` | Federated Hermes Municipal Bond Fund, Inc. | bond_or_other | 100.0% | 302 | $428,491,018.78 | majority |
| `S000085236` | Rareview Total Return Bond ETF | excluded | 100.0% | 301 | $92,479,784.95 | majority |
| `S000035751` | Arrow Dow Jones Global Yield ETF | passive | 100.0% | 289 | $54,136,782.03 | majority |
| `S000058304` | Virtus WMC International Dividend ETF | excluded | 100.0% | 287 | $26,157,800.21 | majority |
| `S000045496` | Guggenheim Strategy Fund II | bond_or_other | 100.0% | 282 | $249,030,559.73 | majority |
| `S000002528` | MFS West Virginia Municipal Bond Fund | bond_or_other | 100.0% | 274 | $170,461,040.34 | majority |
| `S000088673` | Indexperts Quality Earnings Focused ETF | excluded | 100.0% | 268 | $72,032,911.43 | majority |
| `S000002535` | MFS Mississippi Municipal Bond Fund | bond_or_other | 100.0% | 264 | $125,474,213.03 | majority |
| `S000065469` | Intermediate Bond Fund | bond_or_other | 100.0% | 254 | $141,678,911.14 | majority |
| `S000003468` | Sit Minnesota Tax-Free Income Fund | bond_or_other | 100.0% | 250 | $369,773,478.76 | majority |
| `S000090015` | Nomura National High-Yield Municipal Bond ETF | excluded | 100.0% | 247 | $60,205,968.46 | majority |
| `S000047353` | Virtus LifeSci Biotech Clinical Trials ETF | excluded | 100.0% | 238 | $61,133,577.31 | majority |
| `S000030275` | Bank Loan Core Fund | bond_or_other | 100.0% | 235 | $718,086,550.68 | majority |
| `S000073803` | Miller Market Neutral Income Fund | bond_or_other | 100.0% | 234 | $260,352,164.71 | majority |
| `S000090721` | E*TRADE No Fee Municipal Bond Index Fund | passive | 100.0% | 225 | $50,551,252.06 | majority |
| `S000047494` | InfraCap REIT Preferred ETF | excluded | 100.0% | 222 | $213,938,395.88 | majority |
| `S000057345` | UVA Unconstrained Medium-Term Fixed Income ETF | excluded | 100.0% | 221 | $83,816,477.84 | majority |
| `S000074231` | Build Bond Innovation ETF | excluded | 100.0% | 221 | $21,889,862.24 | majority |
| `S000065272` | Leader Capital Short Term High Yield Bond Fund | bond_or_other | 100.0% | 215 | $497,222,880.51 | majority |
| `S000072757` | AltShares Event-Driven ETF | excluded | 100.0% | 213 | $15,261,745.68 | majority |
| `S000081097` | Madison Aggregate Bond ETF | passive | 100.0% | 206 | $63,625,637.26 | majority |
| `S000082989` | LG QRAFT AI-Powered U.S. Large Cap Core ETF | excluded | 100.0% | 203 | $8,973,164.88 | majority |
| `S000084450` | Obra High Grade Structured Products ETF | excluded | 100.0% | 203 | $59,502,264.44 | majority |
| `S000093092` | Rayliant-ChinaAMC Transformative China Tech ETF | excluded | 100.0% | 201 | $20,340,716.60 | majority |
| `S000084449` | Obra Opportunistic Structured Products ETF | excluded | 100.0% | 199 | $74,666,591.03 | majority |
| `S000092393` | Monopoly ETF | excluded | 100.0% | 198 | $23,814,506.00 | majority |
| `S000009085` | Federated Hermes Short-Intermediate Municipal Fund | bond_or_other | 100.0% | 197 | $386,063,439.23 | majority |
| `S000045418` | InfraCap MLP ETF | excluded | 100.0% | 187 | $972,064,628.04 | majority |
| `S000083462` | TEXAS CAPITAL TEXAS SMALL CAP EQUITY INDEX ETF | passive | 100.0% | 186 | $10,644,063.52 | majority |
| `S000008395` | Voya High Yield Bond Fund | bond_or_other | 100.0% | 185 | $467,090,541.38 | majority |
| `S000009040` | Federated Hermes Government Income Fund | bond_or_other | 100.0% | 183 | $381,302,198.54 | majority |
| `S000064728` | Virtus Real Asset Income ETF | excluded | 100.0% | 182 | $32,149,674.23 | majority |
| `S000044182` | WBI BullBear Yield 3000 ETF | excluded | 100.0% | 181 | $72,683,752.10 | majority |
| `S000045498` | Guggenheim Variable Insurance Strategy Fund III | bond_or_other | 100.0% | 180 | $60,362,827.72 | majority |
| `S000090723` | E*TRADE No Fee U.S. Bond Index Fund | passive | 100.0% | 173 | $48,857,146.28 | majority |
| `S000088551` | GMO U.S. Value ETF | excluded | 100.0% | 167 | $66,975,435.69 | majority |
| `S000039473` | Sit Quality Income Fund | bond_or_other | 100.0% | 166 | $129,989,127.66 | majority |
| `S000003821` | Viking Tax-Free Fund for Montana | bond_or_other | 100.0% | 165 | $104,769,944.05 | majority |
| `S000088549` | GMO International Value ETF | excluded | 100.0% | 164 | $231,124,964.16 | majority |
| `S000084933` | Genter Capital Municipal Quality Intermediate ETF | excluded | 100.0% | 160 | $37,203,491.92 | majority |
| `S000088674` | Indexperts Yield Focused Fixed Income ETF | excluded | 100.0% | 158 | $43,610,590.05 | majority |
| `S000044181` | WBI BullBear Value 3000 ETF | excluded | 100.0% | 157 | $58,059,677.45 | majority |
| `S000044183` | WBI BullBear Quality 3000 ETF | excluded | 100.0% | 148 | $65,773,152.20 | majority |
| `S000067196` | AltShares Merger Arbitrage ETF | excluded | 100.0% | 144 | $94,035,925.46 | majority |
| `S000089384` | Obra Defensive High Yield ETF | excluded | 100.0% | 141 | $5,082,416.83 | majority |
| `S000093420` | First Eagle High Yield Municipal Completion Fund | bond_or_other | 100.0% | 140 | $32,320,092.51 | majority |
| `S000006436` | CALIFORNIA MUNICIPAL BOND FUND | bond_or_other | 100.0% | 137 | $226,969,846.64 | majority |
| `S000036290` | Aspiriant Risk-Managed Equity Allocation Fund | bond_or_other | 100.0% | 132 | $1,316,259,643.01 | majority |
| `S000088550` | GMO Systematic Investment Grade Credit ETF | excluded | 100.0% | 131 | $18,985,253.06 | majority |
| `S000023593` | Project and Trade Finance Core Fund | bond_or_other | 100.0% | 129 | $1,353,934,394.72 | majority |
| `S000056193` | abrdn Bloomberg All Commodity Longer Dated Strategy K-1 Free ETF | excluded | 100.0% | 129 | $574,603,187.43 | majority |
| `S000052299` | ARK Israel Innovative Technology ETF | excluded | 100.0% | 124 | $264,114,814.29 | majority |
| `S000047354` | Virtus LifeSci Biotech Products ETF | excluded | 100.0% | 123 | $76,461,535.24 | majority |
| `S000023539` | Templeton Global Total Return Fund | bond_or_other | 100.0% | 122 | $202,496,821.43 | majority |
| `S000064727` | Virtus Private Credit Strategy ETF | excluded | 100.0% | 121 | $114,012,944.04 | majority |
| `S000084713` | Anydrus Advantage ETF | excluded | 100.0% | 118 | $56,253,492.63 | majority |
| `S000074338` | Popular High Grade Fixed-Income Fund Inc. | bond_or_other | 100.0% | 115 | $34,157,831.76 | majority |
| `S000020099` | Miller Convertible Bond Fund | bond_or_other | 100.0% | 114 | $1,022,154,086.36 | majority |
| `S000006431` | PENNSYLVANIA MUNICIPAL BOND FUND | bond_or_other | 100.0% | 112 | $133,981,766.40 | majority |
| `S000069718` | Siren DIVCON Leaders Dividend ETF | excluded | 100.0% | 112 | $132,735,150.53 | majority |
| `S000008754` | Templeton Global Bond Fund | bond_or_other | 100.0% | 109 | $2,916,479,542.58 | majority |
| `S000084932` | Genter Capital Taxable Quality Intermediate ETF | excluded | 100.0% | 108 | $140,444,202.49 | majority |
| `S000046813` | Miller Intermediate Bond Fund | bond_or_other | 100.0% | 107 | $357,429,258.97 | majority |
| `S000094624` | Federated Hermes Enhanced Income ETF | excluded | 100.0% | 106 | $20,231,949.82 | majority |
| `S000093218` | Crossmark Large Cap Value ETF | excluded | 100.0% | 103 | $22,221,628.99 | majority |
| `S000045949` | EUBEL BRADY & SUTTMAN INCOME FUND | bond_or_other | 100.0% | 103 | $840,632,033.39 | majority |
| `S000065358` | QRAFT AI-Enhanced U.S. Large Cap Momentum ETF | excluded | 100.0% | 102 | $59,526,540.84 | majority |
| `S000056192` | abrdn Bloomberg All Commodity Strategy K-1 Free ETF | excluded | 100.0% | 101 | $3,406,140,051.75 | majority |
| `S000094833` | Man Active High Yield ETF | excluded | 100.0% | 101 | $18,407,488.37 | majority |
| `S000083896` | American Beacon GLG Natural Resources ETF | excluded | 100.0% | 101 | $754,143,361.61 | majority |
| `S000042978` | ARK Next Generation Internet ETF | excluded | 100.0% | 99 | $4,340,873,064.58 | majority |
| `S000078169` | Federated Hermes U.S. Strategic Dividend ETF | excluded | 100.0% | 99 | $1,058,268,025.40 | majority |
| `S000061584` | Procure Space ETF | excluded | 100.0% | 99 | $566,385,978.92 | majority |
| `S000081095` | Madison Short-Term Strategic Income ETF | excluded | 100.0% | 98 | $61,925,647.98 | majority |
| `S000040303` | Templeton Sustainable Emerging Markets Bond Fund | bond_or_other | 100.0% | 97 | $24,498,160.32 | majority |
| `S000083143` | Natixis Gateway Quality Income ETF | excluded | 100.0% | 97 | $222,176,163.59 | majority |
| `S000009108` | Hawaiian Tax-Free Trust | bond_or_other | 100.0% | 96 | $368,508,462.48 | majority |
| `S000086526` | Eventide High Dividend ETF | excluded | 100.0% | 95 | $309,367,000.07 | majority |
| `S000042977` | ARK Innovation ETF | excluded | 100.0% | 95 | $15,073,032,926.78 | majority |
| `S000088547` | GMO Beyond China ETF | excluded | 100.0% | 94 | $12,287,487.45 | majority |
| `S000052298` | The 3D Printing ETF | excluded | 100.0% | 94 | $143,848,983.24 | majority |
| `S000080449` | Fundamentals First ETF | excluded | 100.0% | 93 | $5,703,688.02 | majority |
| `S000064752` | ARK Fintech Innovation ETF | excluded | 100.0% | 91 | $2,256,874,017.88 | majority |
| `S000048107` | VY BrandyWineGLOBAL - Bond Portfolio | bond_or_other | 100.0% | 89 | $457,712,026.96 | majority |
| `S000009041` | Federated Hermes Short-Intermediate Government Fund | bond_or_other | 100.0% | 89 | $200,972,263.61 | majority |
| `S000011440` | NORTHEAST INVESTORS TRUST | bond_or_other | 100.0% | 89 | $256,314,409.78 | majority |
| `S000085351` | FundX Future Fund Opportunities ETF | excluded | 100.0% | 85 | $186,851,100.06 | majority |
| `S000077078` | Short Duration Inflation-Protected Income Portfolio | bond_or_other | 100.0% | 84 | $856,666,537.89 | majority |
| `S000006435` | NEW JERSEY MUNICIPAL BOND FUND | bond_or_other | 100.0% | 83 | $91,134,735.75 | majority |
| `S000010534` | CM ADVISORS FIXED INCOME FUND | bond_or_other | 100.0% | 82 | $27,809,060.31 | majority |
| `S000055344` | Davis Select Worldwide ETF | excluded | 100.0% | 80 | $1,009,073,112.75 | majority |
| `S000072935` | Atlas U.S. Tactical Income Fund | bond_or_other | 100.0% | 78 | $75,304,977.95 | majority |
| `S000056657` | Saba Closed-End Funds ETF | excluded | 100.0% | 78 | $319,449,223.09 | majority |
| `S000006434` | NEW YORK MUNICIPAL BOND FUND | bond_or_other | 100.0% | 77 | $110,774,427.12 | majority |
| `S000083942` | MassMutual Clinton Limited Term Municipal Fund | bond_or_other | 100.0% | 77 | $113,364,166.89 | majority |
| `S000086524` | Palmer Square CLO Senior Debt ETF | excluded | 100.0% | 75 | $71,736,129.94 | majority |
| `S000042976` | ARK Autonomous Technology & Robotics ETF | excluded | 100.0% | 75 | $3,876,402,869.73 | majority |
| `S000046875` | Renaissance International IPO ETF | excluded | 100.0% | 74 | $10,396,360.31 | majority |
| `S000070448` | Strategy Shares Gold Enhanced Yield ETF | excluded | 100.0% | 73 | $293,269,180.99 | majority |
| `S000070063` | The E-Valuator Moderate (50%-70%) RMS Fund | bond_or_other | 100.0% | 73 | $153,545,651.42 | majority |
| `S000070060` | The E-Valuator Conservative (15%-30%) RMS Fund | bond_or_other | 100.0% | 73 | $49,668,895.23 | majority |
| `S000070061` | The E-Valuator Conservative/Moderate (30%-50%) RMS Fund | bond_or_other | 100.0% | 73 | $32,938,294.78 | majority |
| `S000089486` | Genter Capital Dividend Income ETF | excluded | 100.0% | 72 | $11,599,624.76 | majority |
| `S000006432` | MASSACHUSETTS MUNICIPAL BOND FUND | bond_or_other | 100.0% | 72 | $62,334,777.07 | majority |
| `S000089487` | Genter Capital International Dividend ETF | excluded | 100.0% | 72 | $5,838,843.07 | majority |
| `S000042975` | ARK Genomic Revolution ETF | excluded | 100.0% | 72 | $2,577,469,882.76 | majority |
| `S000002663` | Series M | bond_or_other | 100.0% | 71 | $322,362,731.79 | majority |
| `S000070062` | The E-Valuator Growth (70%-85%) RMS Fund | bond_or_other | 100.0% | 71 | $269,747,917.51 | majority |
| `S000070064` | The E-Valuator Very Conservative (0%-15%) RMS Fund | bond_or_other | 100.0% | 71 | $21,425,602.96 | majority |
| `S000072878` | Adaptive Core ETF | excluded | 100.0% | 70 | $23,697,423.48 | majority |
| `S000083940` | MassMutual Clinton Municipal Credit Opportunities Fund | bond_or_other | 100.0% | 69 | $103,911,038.26 | majority |
| `S000071318` | ARK Space Exploration & Innovation ETF | excluded | 100.0% | 68 | $1,355,219,585.04 | majority |
| `S000094834` | Man Active Income ETF | excluded | 100.0% | 68 | $21,209,460.10 | majority |
| `S000045948` | EUBEL BRADY & SUTTMAN INCOME AND APPRECIATION FUND | bond_or_other | 100.0% | 67 | $300,498,313.41 | majority |
| `S000081094` | Madison Covered Call ETF | excluded | 100.0% | 66 | $35,963,795.31 | majority |
| `S000055343` | Davis Select Financial ETF | excluded | 100.0% | 66 | $767,729,568.62 | majority |
| `S000086506` | TEXAS CAPITAL GOVERNMENT MONEY MARKET ETF | excluded | 100.0% | 66 | $127,663,935.21 | majority |
| `S000070059` | The E-Valuator Aggressive Growth (85%-99%) RMS Fund | bond_or_other | 100.0% | 64 | $231,835,510.53 | majority |
| `S000091902` | Dan IVES Wedbush AI Revolution ETF | excluded | 100.0% | 62 | $2,061,388,427.97 | majority |
| `S000074352` | U.S. Monthly Income Fund for Puerto Rico Residents, Inc. | bond_or_other | 100.0% | 62 | $69,546,083.02 | majority |
| `S000094773` | Nelson Select ETF | excluded | 100.0% | 62 | $41,284,759.94 | majority |
| `S000061340` | Davis Select International ETF | excluded | 100.0% | 61 | $535,678,120.27 | majority |
| `S000093217` | Crossmark Large Cap Growth ETF | excluded | 100.0% | 60 | $42,975,666.88 | majority |
| `S000079330` | IDX Adaptive Opportunities Fund | passive | 100.0% | 59 | $49,217,035.36 | majority |
| `S000069719` | Siren NexGen Economy ETF | excluded | 100.0% | 59 | $44,369,889.12 | majority |
| `S000083461` | TEXAS CAPITAL TEXAS OIL INDEX ETF | passive | 100.0% | 57 | $21,076,627.58 | majority |
| `S000055342` | Davis Select U.S. Equity ETF | excluded | 100.0% | 56 | $1,891,069,204.28 | majority |
| `S000055583` | WBI Power Factor High Dividend ETF | excluded | 100.0% | 52 | $62,635,442.79 | majority |
| `S000095116` | AMG GW&K Muni Income ETF | excluded | 100.0% | 51 | $10,390,098.61 | majority |
| `S000059719` | Strategy Shares NASDAQ 7HANDL Index ETF | passive | 100.0% | 49 | $1,276,437,303.32 | majority |
| `S000000715` | Western Asset Inflation Indexed Plus Bond Fund | bond_or_other | 100.0% | 48 | $39,752,130.85 | majority |
| `S000094339` | WarCap Unconstrained Equity ETF | excluded | 100.0% | 47 | $114,256,948.63 | majority |
| `S000033316` | FlexShares iBoxx 3-Year Target Duration TIPS Index Fund | passive | 100.0% | 47 | $5,040,930,527.63 | majority |
| `S000074350` | International Portfolio I | active | 100.0% | 46 | $1,740,328.74 | majority |
| `S000075052` | Valkyrie Bitcoin Miners ETF | excluded | 100.0% | 45 | $498,185,016.40 | majority |
| `S000094783` | GMO Ultra-Short Income ETF | excluded | 100.0% | 45 | $7,422,789.64 | majority |
| `S000070261` | The SPAC and New Issue ETF | excluded | 100.0% | 43 | $7,499,420.56 | majority |
| `S000083941` | MassMutual Clinton Municipal Fund | bond_or_other | 100.0% | 43 | $62,531,083.77 | majority |
| `S000069798` | Rareview Dynamic Fixed Income ETF | excluded | 100.0% | 42 | $60,913,200.47 | majority |
| `S000074346` | Large Cap Core Portfolio I | active | 100.0% | 41 | $6,124,572.27 | majority |
| `S000082813` | FundX Conservative ETF | excluded | 100.0% | 41 | $103,506,280.96 | majority |
| `S000041784` | Renaissance IPO ETF | excluded | 100.0% | 41 | $139,617,592.70 | majority |
| `S000074349` | Small Cap Core Portfolio I | active | 100.0% | 41 | $1,718,925.13 | majority |
| `S000083162` | Mohr Company NAV ETF | excluded | 100.0% | 40 | $34,034,862.73 | majority |
| `S000074347` | Large Cap Growth Portfolio I | active | 100.0% | 40 | $8,009,410.49 | majority |
| `S000084308` | North Shore Equity Rotation ETF | excluded | 100.0% | 40 | $52,392,565.60 | majority |
| `S000034352` | FlexShares iBoxx 5-Year Target Duration TIPS Index Fund | passive | 100.0% | 40 | $1,858,894,517.41 | majority |
| `S000055516` | FlexShares Core Select Bond Fund | bond_or_other | 100.0% | 39 | $328,332,774.89 | majority |
| `S000081096` | Madison Dividend Value ETF | excluded | 100.0% | 38 | $61,223,856.38 | majority |
| `S000074344` | Popular Income Plus Fund Inc. | bond_or_other | 100.0% | 38 | $16,875,647.56 | majority |
| `S000094780` | GMO Domestic Resilience ETF | excluded | 100.0% | 38 | $29,393,749.05 | majority |
| `S000082992` | GMO U.S. Quality ETF | excluded | 100.0% | 37 | $3,028,249,851.66 | majority |
| `S000073730` | Goose Hollow Tactical Allocation ETF | excluded | 100.0% | 37 | $37,692,902.72 | majority |
| `S000049397` | Virtus Reaves Utilities ETF | excluded | 100.0% | 35 | $2,654,417,390.32 | majority |
| `S000074348` | Mid Cap Core Portfolio I | active | 100.0% | 34 | $3,841,832.19 | majority |
| `S000088548` | GMO International Quality ETF | excluded | 100.0% | 34 | $252,496,682.15 | majority |
| `S000094663` | Prospera Income ETF | excluded | 100.0% | 33 | $2,130,163.25 | majority |
| `S000066772` | Day Hagan Smart Sector ETF | excluded | 100.0% | 32 | $1,113,771,279.99 | majority |
| `S000084270` | Bancreek International Large Cap ETF | excluded | 100.0% | 31 | $73,258,983.01 | majority |
| `S000090213` | American Beacon Ionic Inflation Protection ETF | excluded | 100.0% | 31 | $20,901,194.43 | majority |
| `S000082910` | Langar Global Health Tech ETF | excluded | 100.0% | 31 | $3,997,073.88 | majority |
| `S000083459` | Bancreek U.S. Large Cap ETF | excluded | 100.0% | 31 | $96,587,066.21 | majority |
| `S000072683` | abrdn Bloomberg Industrial Metals Strategy K-1 Free ETF | excluded | 100.0% | 29 | $22,735,279.18 | majority |
| `S000074345` | Large Cap Value Portfolio I | active | 100.0% | 29 | $5,255,629.35 | majority |
| `S000087726` | Select STOXX Europe Aerospace & Defense ETF | excluded | 100.0% | 28 | $2,147,350,143.21 | majority |
| `S000068960` | Natixis Vaughan Nelson Select ETF | excluded | 100.0% | 28 | $13,549,807.13 | majority |
| `S000085894` | Long Pond Real Estate Select ETF | excluded | 100.0% | 27 | $92,050,385.92 | majority |
| `S000076645` | Day Hagan Smart Sector International ETF | excluded | 100.0% | 27 | $72,456,453.46 | majority |
| `S000074333` | Short Term Investment Fund for Puerto Rico Residents, Inc. | bond_or_other | 100.0% | 27 | $135,519,630.09 | majority |
| `S000089482` | PLUS Korea Defense Industry Index ETF | passive | 100.0% | 25 | $57,370,744.70 | majority |
| `S000068387` | ETC Cabana Target Beta ETF | excluded | 100.0% | 24 | $116,511,295.29 | majority |
| `S000068388` | ETC Cabana Target Drawdown 10 ETF | excluded | 100.0% | 23 | $242,474,619.05 | majority |
| `S000091576` | CoinShares Altcoins ETF | excluded | 100.0% | 22 | $1,613,307.05 | majority |
| `S000077553` | FundX Aggressive ETF | excluded | 100.0% | 21 | $27,585,960.00 | majority |
| `S000035083` | AZL MVP Global Balanced Index Strategy Fund | passive | 100.0% | 20 | $802,653,371.00 | majority |
| `S000072879` | Mindful Conservative ETF | excluded | 100.0% | 17 | $8,067,031.13 | majority |
| `S000094781` | GMO Dynamic Allocation ETF | excluded | 100.0% | 17 | $18,703,767.47 | majority |
| `S000073631` | Day Hagan Smart Sector Fixed Income ETF | excluded | 100.0% | 17 | $65,348,142.81 | majority |
| `S000035081` | AZL MVP Balanced Index Strategy Fund | passive | 100.0% | 14 | $1,319,750,274.22 | majority |
| `S000035084` | AZL MVP Moderate Index Strategy Fund | passive | 100.0% | 14 | $590,469,698.49 | majority |
| `S000075551` | X-Square Municipal Income ETF | excluded | 100.0% | 14 | $4,478,841.69 | majority |
| `S000035082` | AZL MVP Growth Index Strategy Fund | passive | 100.0% | 14 | $3,277,699,369.07 | majority |
| `S000069799` | Rareview Tax Advantaged Income ETF | excluded | 100.0% | 14 | $17,667,998.94 | majority |
| `S000072148` | ETC Cabana Target Leading Sector Moderate ETF | excluded | 100.0% | 14 | $216,810,769.40 | majority |
| `S000059404` | Aspiriant Risk-Managed Taxable Bond Fund | bond_or_other | 100.0% | 11 | $373,128,529.97 | majority |
| `S000077552` | FundX ETF | excluded | 100.0% | 11 | $173,490,363.98 | majority |
| `S000074058` | Valkyrie Bitcoin and Ether Strategy ETF | excluded | 100.0% | 11 | $40,692,351.05 | majority |
| `S000051603` | Aspiriant Defensive Allocation Fund | bond_or_other | 100.0% | 11 | $989,520,766.82 | majority |
| `S000025338` | AZL Balanced Index Strategy Fund | passive | 100.0% | 10 | $648,738,498.81 | majority |
| `S000082812` | FundX Flexible ETF | excluded | 100.0% | 10 | $32,324,512.90 | majority |
| `S000095346` | ARK DIET Q4 Buffer ETF | excluded | 100.0% | 9 | $6,865,378.61 | majority |
| `S000066847` | Strategy Shares Newfound/Resolve Robust Momentum ETF | excluded | 100.0% | 9 | $55,658,320.92 | majority |
| `S000089262` | Day Hagan Smart Buffer ETF | excluded | 100.0% | 8 | $81,874,786.00 | majority |
| `S000079362` | Mohr Sector Nav ETF | excluded | 100.0% | 7 | $23,784,640.91 | majority |
| `S000075093` | Rareview Systematic Equity ETF | excluded | 100.0% | 6 | $96,832,389.82 | majority |
| `S000095343` | ARK DIET Q1 Buffer ETF | excluded | 100.0% | 5 | $1,467,721.55 | majority |
| `S000074070` | IDX Risk-Managed Digital Assets Strategy Fund | passive | 100.0% | 4 | $21,433,059.87 | majority |
| `S000084822` | Stratified LargeCap Hedged ETF | excluded | 100.0% | 4 | $23,511,733.39 | majority |
| `S000090077` | Rareview 2x Bull Cryptocurrency & Precious Metals ETF | excluded | 100.0% | 4 | $-280,829.84 | majority |
| `S000081280` | Valkyrie Bitcoin Futures Leveraged Strategy ETF | excluded | 100.0% | 2 | $2,969,399.97 | majority |
| `S000084371` | DailyDelta Q100 Upside Option Strategy ETF | excluded | 100.0% | 1 | $9,912.99 | majority |
| `S000084370` | DailyDelta Q100 Downside Option Strategy ETF | excluded | 100.0% | 1 | $27,365.44 | majority |
