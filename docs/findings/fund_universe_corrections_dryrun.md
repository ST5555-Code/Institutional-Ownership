# fund-universe-value-corrections — Phase 2 dry-run

_Generated: 2026-05-02T12:14:52Z_

## Block A — Rareview reclassify

- `series_id`: `S000090077`
- `fund_name`: Rareview 2x Bull Cryptocurrency & Precious Metals ETF
- Current `fund_strategy`: **excluded** (`strategy_source`=orphan_backfill_2026Q2)
- Proposed `fund_strategy`: **passive** (`strategy_source`=unknown_cleanup_2026Q2)

Rationale: classifier order matched leveraged-name regex (`\dx`) before the ETF/passive pattern, tagging the fund `excluded`. Per PR #246 audit, this is a leveraged passive ETF, not excluded. Manual override.

## Block B — total_net_assets backfill (301 rows)

- Cohort: `strategy_source='orphan_backfill_2026Q2'`
- Re-validated inventory: 301 rows, 0 with `total_net_assets`, 301 NULL.

Canonical derivation: `NAV = MEDIAN(market_value_usd * 100.0 / pct_of_nav)` over most-recent-quarter `is_latest=TRUE` rows. `pct_of_nav` is stored on the percent scale (0–100). Method validated against 10 funds with existing `total_net_assets` (ratio = 1.000000…).

Fallback: `NAV = SUM(market_value_usd)` for series with no usable `pct_of_nav` rows; `strategy_source` suffixed `|aum_summed_fallback`.

### Block B summary

| Source | Series | Total NAV (USD) |
|---|---:|---:|
| canonical_nport | 301 | $450,128,735,009.51 |
| aum_summed_fallback | 0 | $0.00 |
| null_residual | 0 | — |
| **TOTAL** | **301** | **$450,128,735,009.51** |

_No NULL-residual series — full coverage._

## Full manifest (sorted by block, source, series_id)

| block | series_id | fund_name | current_value | proposed_value | source | new_strategy_source |
|---|---|---|---|---:|---|---|
| A | `S000090077` | Rareview 2x Bull Cryptocurrency & Precious Metals ETF | excluded | passive | manual_override | unknown_cleanup_2026Q2 |
| B | `S000000713` | Western Asset Core Bond Fund | — | $1,869,626,399 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000000714` | Western Asset Core Plus Bond Fund | — | $3,952,570,949 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000000715` | Western Asset Inflation Indexed Plus Bond Fund | — | $40,282,134 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000001146` | TCW METWEST LOW DURATION BOND FUND | — | $878,483,371 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000001147` | TCW METWEST TOTAL RETURN BOND FUND | — | $31,064,468,922 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000001149` | TCW METWEST HIGH YIELD BOND FUND | — | $419,552,606 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000001151` | TCW METWEST ULTRA SHORT BOND FUND | — | $40,338,152 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000001152` | TCW METWEST STRATEGIC INCOME FUND | — | $48,703,622 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000001913` | CCM Community Impact Bond Fund | — | $3,839,941,073 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000002521` | MFS Alabama Municipal Bond Fund | — | $69,550,332 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000002522` | MFS New York Municipal Bond Fund | — | $188,260,474 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000002523` | MFS North Carolina Municipal Bond Fund | — | $529,635,468 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000002524` | MFS Pennsylvania Municipal Bond Fund | — | $186,221,090 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000002525` | MFS South Carolina Municipal Bond Fund | — | $224,195,607 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000002527` | MFS Virginia Municipal Bond Fund | — | $349,475,705 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000002528` | MFS West Virginia Municipal Bond Fund | — | $85,602,524 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000002529` | MFS Arkansas Municipal Bond Fund | — | $140,176,538 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000002530` | MFS California Municipal Bond Fund | — | $747,698,468 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000002532` | MFS Georgia Municipal Bond Fund | — | $117,505,653 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000002533` | MFS Maryland Municipal Bond Fund | — | $155,248,398 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000002534` | MFS Massachusetts Municipal Bond Fund | — | $401,013,443 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000002535` | MFS Mississippi Municipal Bond Fund | — | $63,199,951 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000002536` | MFS Municipal Income Fund | — | $6,646,707,089 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000002663` | Series M | — | $325,475,842 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000003467` | Sit Tax-Free Income Fund | — | $126,555,913 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000003468` | Sit Minnesota Tax-Free Income Fund | — | $377,473,440 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000003821` | Viking Tax-Free Fund for Montana | — | $52,504,390 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000005235` | HIGH INCOME OPPORTUNITIES PORTFOLIO | — | $1,787,449,538 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000005237` | Core Bond Portfolio | — | $758,978,659 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000005247` | Global Macro Portfolio | — | $3,455,023,263 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000005797` | Hawaii Municipal Bond Fund | — | $170,512,713 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000006430` | SHORT DURATION MUNICIPAL FUND | — | $751,652,131 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000006431` | PENNSYLVANIA MUNICIPAL BOND FUND | — | $135,511,166 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000006432` | MASSACHUSETTS MUNICIPAL BOND FUND | — | $61,350,387 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000006434` | NEW YORK MUNICIPAL BOND FUND | — | $111,082,426 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000006435` | NEW JERSEY MUNICIPAL BOND FUND | — | $92,422,514 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000006436` | CALIFORNIA MUNICIPAL BOND FUND | — | $229,020,645 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000006439` | INTERMEDIATE-TERM MUNICIPAL FUND | — | $1,552,305,921 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000008266` | SDIT Ultra Short Duration Bond Fund | — | $193,259,997 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000008267` | SDIT Short Duration Government Fund | — | $592,863,612 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000008269` | SDIT GNMA FUND | — | $11,170,337 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000008394` | VOYA GNMA INCOME FUND | — | $1,071,888,177 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000008395` | Voya High Yield Bond Fund | — | $215,349,771 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000008396` | VOYA INTERMEDIATE BOND FUND | — | $9,887,176,416 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000008754` | Templeton Global Bond Fund | — | $3,007,992,558 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000008760` | VOYA INTERMEDIATE BOND PORTFOLIO | — | $918,997,739 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000009040` | Federated Hermes Government Income Fund | — | $150,115,639 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000009041` | Federated Hermes Short-Intermediate Government Fund | — | $97,833,271 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000009068` | Federated Hermes Sustainable High Yield Bond Fund, Inc. | — | $499,223,248 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000009070` | Federated Hermes Municipal Bond Fund, Inc. | — | $213,912,960 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000009085` | Federated Hermes Short-Intermediate Municipal Fund | — | $388,930,339 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000009108` | Hawaiian Tax-Free Trust | — | $374,790,376 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000009127` | Mortgage Core Fund | — | $4,732,244,434 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000009129` | High Yield Bond Core Fund | — | $1,058,205,532 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000009229` | American High-Income Municipal Bond Fund | — | $13,868,777,726 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000009230` | American High Income Trust | — | $26,560,590,500 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000009231` | Bond Fund of America | — | $98,590,260,931 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000009236` | Intermediate Bond Fund of America | — | $27,417,977,015 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000009237` | Limited Term Tax Exempt Bond Fund of America | — | $6,044,718,584 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000009238` | Tax Exempt Bond Fund of America | — | $24,356,812,816 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000009240` | Capital World Bond Fund | — | $9,852,458,428 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000009768` | AFL CIO Housing Investment Trust | — | $7,302,528,949 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000009981` | AB HIGH INCOME FUND INC | — | $3,139,473,237 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000010055` | Series P (High Yield Series) | — | $28,099,690 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000010066` | Series E (Total Return Bond Series) | — | $190,224,946 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000010128` | AB GLOBAL BOND FUND, INC. | — | $6,599,351,269 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000010534` | CM ADVISORS FIXED INCOME FUND | — | $28,170,658 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000010876` | AB Corporate Income Shares | — | $173,560,748 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000010934` | Federated Hermes Institutional High Yield Bond Fund | — | $5,368,437,114 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000011063` | Bernstein Intermediate Duration Institutional Portfolio | — | $853,418,010 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000011440` | NORTHEAST INVESTORS TRUST | — | $128,210,225 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000011654` | Sit U S Government Securities Fund Inc | — | $200,935,959 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000011830` | ELFUN TAX EXEMPT INCOME FUND | — | $812,291,643 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000011831` | ELFUN INCOME FUND | — | $118,688,487 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000012064` | Colorado BondShares A Tax Exempt Fund | — | $1,948,524,338 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000013585` | Short-Term Bond Fund of America | — | $12,452,710,620 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000017994` | Emerging Markets Local Income Portfolio | — | $1,760,387,723 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000017995` | International Income Portfolio | — | $211,898,949 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000020099` | Miller Convertible Bond Fund | — | $481,728,936 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000022423` | Senior Debt Portfolio | — | $5,089,783,893 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000023539` | Templeton Global Total Return Fund | — | $209,199,749 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000023593` | Project and Trade Finance Core Fund | — | $1,400,034,011 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000025338` | AZL Balanced Index Strategy Fund | — | $321,308,473 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000027417` | Global Opportunities Portfolio | — | $11,289,167,800 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000028884` | Cohen & Steers Preferred Securities & Income Fund, Inc. | — | $7,221,886,730 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000029560` | AB Municipal Income Shares | — | $17,667,131,462 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000029761` | Global Macro Absolute Return Advantage Portfolio | — | $6,902,275,035 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000029838` | AB Taxable Multi-Sector Income Shares | — | $491,682,128 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000030275` | Bank Loan Core Fund | — | $630,452,063 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000033316` | FlexShares iBoxx 3-Year Target Duration TIPS Index Fund | — | $2,517,238,140 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000034352` | FlexShares iBoxx 5-Year Target Duration TIPS Index Fund | — | $970,796,312 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000035081` | AZL MVP Balanced Index Strategy Fund | — | $681,298,831 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000035082` | AZL MVP Growth Index Strategy Fund | — | $1,697,876,834 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000035083` | AZL MVP Global Balanced Index Strategy Fund | — | $414,348,017 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000035084` | AZL MVP Moderate Index Strategy Fund | — | $305,091,448 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000035596` | FlexShares Ultra-Short Income Fund | — | $1,397,469,150 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000035751` | Arrow Dow Jones Global Yield ETF | — | $26,742,592 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000036290` | Aspiriant Risk-Managed Equity Allocation Fund | — | $1,298,016,845 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000039473` | Sit Quality Income Fund | — | $135,385,748 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000040303` | Templeton Sustainable Emerging Markets Bond Fund | — | $25,267,275 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000040553` | Series F (Floating Rate Strategies Series) | — | $47,111,913 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000041784` | Renaissance IPO ETF | — | $139,223,300 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000042975` | ARK Genomic Revolution ETF | — | $1,272,728,586 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000042976` | ARK Autonomous Technology & Robotics ETF | — | $2,049,567,760 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000042977` | ARK Innovation ETF | — | $6,676,811,932 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000042978` | ARK Next Generation Internet ETF | — | $1,833,877,701 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000044181` | WBI BullBear Value 3000 ETF | — | $24,388,036 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000044182` | WBI BullBear Yield 3000 ETF | — | $29,297,991 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000044183` | WBI BullBear Quality 3000 ETF | — | $29,485,306 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000045418` | InfraCap MLP ETF | — | $405,139,337 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000045496` | Guggenheim Strategy Fund II | — | $127,239,042 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000045497` | Guggenheim Strategy Fund III | — | $128,761,532 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000045498` | Guggenheim Variable Insurance Strategy Fund III | — | $31,115,458 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000045538` | Blackstone Alternative Multi-Strategy Fund | — | $3,766,023,292 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000045948` | EUBEL BRADY & SUTTMAN INCOME AND APPRECIATION FUND | — | $153,500,528 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000045949` | EUBEL BRADY & SUTTMAN INCOME FUND | — | $430,921,432 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000046193` | FlexShares Disciplined Duration MBS Index Fund | — | $91,640,789 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000046813` | Miller Intermediate Bond Fund | — | $175,143,977 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000046875` | Renaissance International IPO ETF | — | $5,099,196 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000047257` | FlexShares Credit-Scored US Corporate Bond Index Fund | — | $654,587,955 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000047353` | Virtus LifeSci Biotech Clinical Trials ETF | — | $36,751,983 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000047354` | Virtus LifeSci Biotech Products ETF | — | $44,873,076 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000047494` | InfraCap REIT Preferred ETF | — | $107,184,857 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000048107` | VY BrandyWineGLOBAL - Bond Portfolio | — | $231,895,668 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000048895` | Virtus Newfleet Multi-Sector Bond ETF | — | $373,962,679 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000049397` | Virtus Reaves Utilities ETF | — | $1,408,421,389 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000049584` | Aspiriant Risk-Managed Municipal Bond Fund | — | $1,228,568,012 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000050613` | FlexShares Credit-Scored US Long Corporate Bond Index Fund | — | $36,225,527 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000051233` | COMMUNITY DEVELOPMENT FUND | — | $326,439,999 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000051603` | Aspiriant Defensive Allocation Fund | — | $998,312,070 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000051713` | Cohen & Steers Low Duration Preferred and Income Fund, Inc. | — | $1,904,263,149 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000052298` | The 3D Printing ETF | — | $68,325,307 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000052299` | ARK Israel Innovative Technology ETF | — | $141,434,239 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000054054` | Emerging Markets Core Fund | — | $774,629,181 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000055298` | Destra Flaherty & Crumrine Preferred and Income Fund | — | $228,689,025 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000055342` | Davis Select U.S. Equity ETF | — | $1,035,154,065 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000055343` | Davis Select Financial ETF | — | $465,784,681 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000055344` | Davis Select Worldwide ETF | — | $528,040,525 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000055516` | FlexShares Core Select Bond Fund | — | $150,123,182 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000055583` | WBI Power Factor High Dividend ETF | — | $55,680,658 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000056192` | abrdn Bloomberg All Commodity Strategy K-1 Free ETF | — | $1,769,104,928 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000056193` | abrdn Bloomberg All Commodity Longer Dated Strategy K-1 Free ETF | — | $290,830,565 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000056657` | Saba Closed-End Funds ETF | — | $348,362,980 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000057345` | UVA Unconstrained Medium-Term Fixed Income ETF | — | $51,949,381 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000058304` | Virtus WMC International Dividend ETF | — | $12,970,349 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000058704` | AB Impact Municipal Income Shares | — | $623,709,488 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000059080` | Virtus InfraCap U.S. Preferred Stock ETF | — | $2,174,057,401 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000059404` | Aspiriant Risk-Managed Taxable Bond Fund | — | $374,305,525 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000059719` | Strategy Shares NASDAQ 7HANDL Index ETF | — | $641,761,828 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000061340` | Davis Select International ETF | — | $275,844,243 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000061584` | Procure Space ETF | — | $366,888,084 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000062125` | FlexShares High Yield Value - Scored Bond Index Fund | — | $1,181,071,271 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000062381` | Advantage CoreAlpha Bond Master Portfolio | — | $722,536,294 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000064727` | Virtus Private Credit Strategy ETF | — | $44,211,905 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000064728` | Virtus Real Asset Income ETF | — | $16,141,619 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000064752` | ARK Fintech Innovation ETF | — | $963,409,300 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000064832` | Preferred Securities and Income SMA Shares | — | $433,239,744 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000065272` | Leader Capital Short Term High Yield Bond Fund | — | $181,506,964 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000065273` | Leader Capital High Quality Income Fund | — | $1,240,536,399 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000065357` | QRAFT AI-Enhanced U.S. Large Cap ETF | — | $17,344,255 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000065358` | QRAFT AI-Enhanced U.S. Large Cap Momentum ETF | — | $26,640,949 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000065469` | Intermediate Bond Fund | — | $142,234,071 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000066772` | Day Hagan Smart Sector ETF | — | $565,000,238 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000066847` | Strategy Shares Newfound/Resolve Robust Momentum ETF | — | $26,348,971 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000067196` | AltShares Merger Arbitrage ETF | — | $98,248,323 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000068387` | ETC Cabana Target Beta ETF | — | $55,062,305 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000068388` | ETC Cabana Target Drawdown 10 ETF | — | $116,203,144 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000068960` | Natixis Vaughan Nelson Select ETF | — | $13,457,371 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000069718` | Siren DIVCON Leaders Dividend ETF | — | $69,939,245 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000069719` | Siren NexGen Economy ETF | — | $36,957,637 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000069798` | Rareview Dynamic Fixed Income ETF | — | $63,098,063 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000069799` | Rareview Tax Advantaged Income ETF | — | $17,991,144 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000069946` | Humankind U.S. Stock ETF | — | $162,717,558 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000070059` | The E-Valuator Aggressive Growth (85%-99%) RMS Fund | — | $231,992,770 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000070060` | The E-Valuator Conservative (15%-30%) RMS Fund | — | $49,466,235 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000070061` | The E-Valuator Conservative/Moderate (30%-50%) RMS Fund | — | $32,968,336 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000070062` | The E-Valuator Growth (70%-85%) RMS Fund | — | $269,724,723 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000070063` | The E-Valuator Moderate (50%-70%) RMS Fund | — | $153,566,332 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000070064` | The E-Valuator Very Conservative (0%-15%) RMS Fund | — | $21,448,758 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000070261` | The SPAC and New Issue ETF | — | $7,620,185 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000070448` | Strategy Shares Gold Enhanced Yield ETF | — | $172,863,205 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000071318` | ARK Space Exploration & Innovation ETF | — | $821,020,815 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000072148` | ETC Cabana Target Leading Sector Moderate ETF | — | $104,025,703 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000072683` | abrdn Bloomberg Industrial Metals Strategy K-1 Free ETF | — | $23,214,433 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000072757` | AltShares Event-Driven ETF | — | $8,958,132 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000072763` | MassMutual Global Credit Income Opportunities Fund | — | $131,915,286 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000072765` | MassMutual Global Floating Rate Fund | — | $128,122,014 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000072878` | Adaptive Core ETF | — | $12,022,708 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000072879` | Mindful Conservative ETF | — | $8,148,668 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000072935` | Atlas U.S. Tactical Income Fund | — | $77,593,279 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000073362` | FlexShares ESG & Climate Investment Grade Corporate Core Index Fund | — | $39,357,701 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000073631` | Day Hagan Smart Sector Fixed Income ETF | — | $30,287,366 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000073730` | Goose Hollow Tactical Allocation ETF | — | $41,065,756 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000073803` | Miller Market Neutral Income Fund | — | $141,155,173 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000074058` | Valkyrie Bitcoin and Ether Strategy ETF | — | $24,549,973 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000074070` | IDX Risk-Managed Digital Assets Strategy Fund | — | $4,327,322 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000074173` | Federated Hermes Short Duration Corporate ETF | — | $64,680,565 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000074231` | Build Bond Innovation ETF | — | $11,355,658 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000074333` | Short Term Investment Fund for Puerto Rico Residents, Inc. | — | $70,025,377 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000074338` | Popular High Grade Fixed-Income Fund Inc. | — | $34,393,728 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000074344` | Popular Income Plus Fund Inc. | — | $16,969,533 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000074345` | Large Cap Value Portfolio I | — | $6,511,106 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000074346` | Large Cap Core Portfolio I | — | $7,611,704 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000074347` | Large Cap Growth Portfolio I | — | $9,678,056 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000074348` | Mid Cap Core Portfolio I | — | $4,690,480 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000074349` | Small Cap Core Portfolio I | — | $2,445,646 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000074350` | International Portfolio I | — | $2,247,143 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000074352` | U.S. Monthly Income Fund for Puerto Rico Residents, Inc. | — | $61,983,509 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000075052` | Valkyrie Bitcoin Miners ETF | — | $228,424,699 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000075093` | Rareview Systematic Equity ETF | — | $58,996,262 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000075551` | X-Square Municipal Income ETF | — | $4,571,858 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000076645` | Day Hagan Smart Sector International ETF | — | $36,227,037 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000077078` | Short Duration Inflation-Protected Income Portfolio | — | $420,456,043 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000077552` | FundX ETF | — | $172,741,655 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000077553` | FundX Aggressive ETF | — | $27,423,026 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000078169` | Federated Hermes U.S. Strategic Dividend ETF | — | $592,272,232 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000079330` | IDX Adaptive Opportunities Fund | — | $31,191,605 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000079362` | Mohr Sector Nav ETF | — | $24,449,934 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000079831` | Cyber Hornet S&P 500 and Bitcoin 75/25 Strategy ETF | — | $8,098,431 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000080449` | Fundamentals First ETF | — | $5,705,120 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000080680` | TEXAS CAPITAL TEXAS EQUITY INDEX ETF | — | $31,407,434 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000081094` | Madison Covered Call ETF | — | $36,006,184 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000081095` | Madison Short-Term Strategic Income ETF | — | $62,570,434 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000081096` | Madison Dividend Value ETF | — | $61,239,180 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000081097` | Madison Aggregate Bond ETF | — | $64,118,235 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000081280` | Valkyrie Bitcoin Futures Leveraged Strategy ETF | — | $15,100,667 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000081302` | American Beacon AHL Trend ETF | — | $50,049,993 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000081361` | CCM Affordable Housing MBS ETF | — | $112,570,855 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000082812` | FundX Flexible ETF | — | $27,573,056 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000082813` | FundX Conservative ETF | — | $50,077,392 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000082910` | Langar Global Health Tech ETF | — | $3,994,552 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000082989` | LG QRAFT AI-Powered U.S. Large Cap Core ETF | — | $1,994,327 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000082992` | GMO U.S. Quality ETF | — | $3,029,370,034 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000083030` | Federated Hermes Total Return Bond ETF | — | $355,560,477 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000083143` | Natixis Gateway Quality Income ETF | — | $222,033,101 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000083162` | Mohr Company NAV ETF | — | $34,876,922 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000083459` | Bancreek U.S. Large Cap ETF | — | $96,610,001 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000083461` | TEXAS CAPITAL TEXAS OIL INDEX ETF | — | $10,000,012 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000083462` | TEXAS CAPITAL TEXAS SMALL CAP EQUITY INDEX ETF | — | $10,642,169 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000083896` | American Beacon GLG Natural Resources ETF | — | $487,537,858 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000083940` | MassMutual Clinton Municipal Credit Opportunities Fund | — | $55,665,608 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000083941` | MassMutual Clinton Municipal Fund | — | $63,228,158 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000083942` | MassMutual Clinton Limited Term Municipal Fund | — | $58,923,669 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000084270` | Bancreek International Large Cap ETF | — | $73,347,684 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000084308` | North Shore Equity Rotation ETF | — | $52,367,942 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000084370` | DailyDelta Q100 Downside Option Strategy ETF | — | $85,829 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000084371` | DailyDelta Q100 Upside Option Strategy ETF | — | $392,344 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000084449` | Obra Opportunistic Structured Products ETF | — | $37,011,764 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000084450` | Obra High Grade Structured Products ETF | — | $29,505,003 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000084713` | Anydrus Advantage ETF | — | $57,168,180 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000084822` | Stratified LargeCap Hedged ETF | — | $23,203,381 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000084823` | Stratified LargeCap Index ETF | — | $115,765,462 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000084932` | Genter Capital Taxable Quality Intermediate ETF | — | $80,811,343 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000084933` | Genter Capital Municipal Quality Intermediate ETF | — | $19,601,308 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000085069` | Palmer Square Credit Opportunities ETF | — | $118,306,282 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000085236` | Rareview Total Return Bond ETF | — | $52,992,574 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000085351` | FundX Future Fund Opportunities ETF | — | $183,269,603 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000085894` | Long Pond Real Estate Select ETF | — | $92,025,761 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000086506` | TEXAS CAPITAL GOVERNMENT MONEY MARKET ETF | — | $70,149,218 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000086524` | Palmer Square CLO Senior Debt ETF | — | $71,682,401 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000086526` | Eventide High Dividend ETF | — | $161,375,258 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000087726` | Select STOXX Europe Aerospace & Defense ETF | — | $1,113,911,338 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000088547` | GMO Beyond China ETF | — | $12,211,031 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000088548` | GMO International Quality ETF | — | $252,431,203 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000088549` | GMO International Value ETF | — | $231,324,039 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000088550` | GMO Systematic Investment Grade Credit ETF | — | $19,242,467 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000088551` | GMO U.S. Value ETF | — | $67,035,118 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000088672` | Indexperts Gorilla Aggressive Growth ETF | — | $41,869,842 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000088673` | Indexperts Quality Earnings Focused ETF | — | $37,325,767 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000088674` | Indexperts Yield Focused Fixed Income ETF | — | $22,811,887 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000089262` | Day Hagan Smart Buffer ETF | — | $41,391,160 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000089355` | Eventide US Market ETF | — | $138,081,963 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000089384` | Obra Defensive High Yield ETF | — | $5,135,575 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000089482` | PLUS Korea Defense Industry Index ETF | — | $57,349,456 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000089486` | Genter Capital Dividend Income ETF | — | $8,838,884 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000089487` | Genter Capital International Dividend ETF | — | $3,853,835 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000090015` | Nomura National High-Yield Municipal Bond ETF | — | $32,170,924 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000090077` | Rareview 2x Bull Cryptocurrency & Precious Metals ETF | — | $4,555,216 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000090213` | American Beacon Ionic Inflation Protection ETF | — | $10,451,167 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000090721` | E*TRADE No Fee Municipal Bond Index Fund | — | $27,607,521 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000090723` | E*TRADE No Fee U.S. Bond Index Fund | — | $28,663,731 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000091576` | CoinShares Altcoins ETF | — | $1,751,637 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000091902` | Dan IVES Wedbush AI Revolution ETF | — | $1,034,487,644 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000092393` | Monopoly ETF | — | $12,704,861 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000093092` | Rayliant-ChinaAMC Transformative China Tech ETF | — | $13,983,955 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000093217` | Crossmark Large Cap Growth ETF | — | $23,056,794 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000093218` | Crossmark Large Cap Value ETF | — | $13,090,704 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000093420` | First Eagle High Yield Municipal Completion Fund | — | $15,253,088 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000094339` | WarCap Unconstrained Equity ETF | — | $60,672,552 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000094624` | Federated Hermes Enhanced Income ETF | — | $14,090,835 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000094625` | Federated Hermes MDT Market Neutral ETF | — | $26,682,628 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000094663` | Prospera Income ETF | — | $2,154,444 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000094773` | Nelson Select ETF | — | $41,690,150 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000094780` | GMO Domestic Resilience ETF | — | $29,394,414 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000094781` | GMO Dynamic Allocation ETF | — | $18,701,033 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000094783` | GMO Ultra-Short Income ETF | — | $7,494,035 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000094833` | Man Active High Yield ETF | — | $19,877,493 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000094834` | Man Active Income ETF | — | $21,374,874 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000095116` | AMG GW&K Muni Income ETF | — | $10,471,486 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000095343` | ARK DIET Q1 Buffer ETF | — | $1,467,734 | canonical_nport | orphan_backfill_2026Q2 |
| B | `S000095346` | ARK DIET Q4 Buffer ETF | — | $2,768,353 | canonical_nport | orphan_backfill_2026Q2 |
