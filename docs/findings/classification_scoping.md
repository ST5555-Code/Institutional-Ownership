# Classification Field Scoping — Read-Only Audit

**DB:** `/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership/data/13f.duckdb`  
**Mode:** read-only  
**Generated:** 2026-04-30

## SECTION A — Institution Level: `entity_classification_history`

### A1. Distinct `classification` values (open rows: `valid_to = DATE '9999-12-31'`)

> Spec asked for `closed_at IS NULL`; that column does not exist. Schema has `valid_from`/`valid_to`; open rows use the SCD sentinel `9999-12-31`.

```sql
SELECT classification, COUNT(*) AS cnt
FROM entity_classification_history
WHERE valid_to = DATE '9999-12-31'
GROUP BY classification
ORDER BY cnt DESC
```

| classification       |   cnt |
|:---------------------|------:|
| active               | 11470 |
| passive              |  5846 |
| unknown              |  3852 |
| wealth_management    |  1678 |
| hedge_fund           |  1484 |
| strategic            |  1163 |
| mixed                |  1032 |
| pension_insurance    |   152 |
| private_equity       |   137 |
| venture_capital      |   128 |
| quantitative         |    73 |
| endowment_foundation |    65 |
| activist             |    34 |
| market_maker         |    23 |
| SWF                  |    15 |


## SECTION B — Institution Level: `holdings_v2.entity_type`

### B1. Population rate

```sql
SELECT
  COUNT(*) AS total_rows,
  COUNT(entity_type) AS non_null,
  COUNT(*) - COUNT(entity_type) AS null_count,
  ROUND(COUNT(entity_type) * 100.0 / COUNT(*), 1) AS pct_populated
FROM holdings_v2
```

|   total_rows |   non_null |   null_count |   pct_populated |
|-------------:|-----------:|-------------:|----------------:|
|   1.2271e+07 | 1.2271e+07 |            0 |             100 |

### B2. Distinct entity_type values

```sql
SELECT entity_type, COUNT(*) AS cnt
FROM holdings_v2
GROUP BY entity_type
ORDER BY cnt DESC
```

| entity_type          |     cnt |
|:---------------------|--------:|
| active               | 4172727 |
| mixed                | 2893109 |
| wealth_management    | 2663260 |
| hedge_fund           | 1160104 |
| passive              |  672523 |
| pension_insurance    |  327501 |
| quantitative         |  297001 |
| strategic            |   40341 |
| SWF                  |   21698 |
| endowment_foundation |   10258 |
| private_equity       |    6655 |
| venture_capital      |    4774 |
| activist             |    1033 |

### B3. Per-quarter population rate

```sql
SELECT quarter,
  COUNT(*) AS total,
  COUNT(entity_type) AS populated,
  ROUND(COUNT(entity_type) * 100.0 / COUNT(*), 1) AS pct
FROM holdings_v2
GROUP BY quarter
ORDER BY quarter
```

| quarter   |   total |   populated |   pct |
|:----------|--------:|------------:|------:|
| 2025Q1    | 2993162 |     2993162 |   100 |
| 2025Q2    | 3047474 |     3047474 |   100 |
| 2025Q3    | 3024698 |     3024698 |   100 |
| 2025Q4    | 3205650 |     3205650 |   100 |


## SECTION C — Institution Level: `holdings_v2.manager_type`

### C1. Distinct manager_type values

```sql
SELECT manager_type, COUNT(*) AS cnt
FROM holdings_v2
GROUP BY manager_type
ORDER BY cnt DESC
```

| manager_type         |     cnt |
|:---------------------|--------:|
| active               | 4538931 |
| mixed                | 4031814 |
| wealth_management    | 1306253 |
| passive              |  751525 |
| quantitative         |  605493 |
| hedge_fund           |  550373 |
| pension_insurance    |  289545 |
| private_equity       |   75214 |
| strategic            |   53878 |
| family_office        |   36950 |
| SWF                  |   16915 |
| endowment_foundation |   10430 |
| activist             |    2143 |
| venture_capital      |     967 |
| multi_strategy       |     553 |

### C2. Cross-tab entity_type vs manager_type (top 40)

```sql
SELECT entity_type, manager_type, COUNT(*) AS cnt
FROM holdings_v2
WHERE entity_type IS NOT NULL AND manager_type IS NOT NULL
GROUP BY entity_type, manager_type
ORDER BY cnt DESC
LIMIT 40
```

| entity_type          | manager_type         |     cnt |
|:---------------------|:---------------------|--------:|
| active               | active               | 3704489 |
| mixed                | mixed                | 2871211 |
| wealth_management    | wealth_management    | 1157581 |
| wealth_management    | mixed                |  785790 |
| passive              | passive              |  663165 |
| wealth_management    | active               |  600070 |
| hedge_fund           | hedge_fund           |  508585 |
| hedge_fund           | quantitative         |  359772 |
| pension_insurance    | pension_insurance    |  289512 |
| active               | mixed                |  284883 |
| quantitative         | quantitative         |  231143 |
| hedge_fund           | active               |  208043 |
| active               | wealth_management    |  110415 |
| hedge_fund           | mixed                |   73790 |
| wealth_management    | private_equity       |   64572 |
| quantitative         | passive              |   54963 |
| strategic            | strategic            |   39558 |
| wealth_management    | family_office        |   31639 |
| active               | hedge_fund           |   27937 |
| active               | passive              |   20718 |
| pension_insurance    | wealth_management    |   15380 |
| pension_insurance    | SWF                  |   14309 |
| active               | quantitative         |   13900 |
| wealth_management    | hedge_fund           |   13669 |
| mixed                | active               |   12938 |
| SWF                  | mixed                |   12084 |
| quantitative         | wealth_management    |   10895 |
| endowment_foundation | endowment_foundation |    9402 |
| hedge_fund           | wealth_management    |    7854 |
| passive              | active               |    7089 |
| SWF                  | passive              |    7008 |
| active               | strategic            |    6913 |
| private_equity       | private_equity       |    5909 |
| wealth_management    | passive              |    5478 |
| mixed                | family_office        |    4816 |
| pension_insurance    | active               |    4169 |
| mixed                | strategic            |    4144 |
| pension_insurance    | mixed                |    4056 |
| active               | private_equity       |    3269 |
| SWF                  | SWF                  |    2606 |


## SECTION D — Institution Level: `holdings_v2.is_passive` and `holdings_v2.is_activist`

### D1. NULL counts

```sql
SELECT
  COUNT(is_passive) AS is_passive_non_null,
  COUNT(*) - COUNT(is_passive) AS is_passive_null,
  COUNT(is_activist) AS is_activist_non_null,
  COUNT(*) - COUNT(is_activist) AS is_activist_null
FROM holdings_v2
```

|   is_passive_non_null |   is_passive_null |   is_activist_non_null |   is_activist_null |
|----------------------:|------------------:|-----------------------:|-------------------:|
|            1.2271e+07 |                 0 |             1.2271e+07 |                  0 |

### D2a. is_passive distribution

```sql
SELECT is_passive, COUNT(*) AS cnt FROM holdings_v2 GROUP BY is_passive ORDER BY cnt DESC
```

| is_passive   |      cnt |
|:-------------|---------:|
| False        | 11532638 |
| True         |   738346 |

### D2b. is_activist distribution

```sql
SELECT is_activist, COUNT(*) AS cnt FROM holdings_v2 GROUP BY is_activist ORDER BY cnt DESC
```

| is_activist   |      cnt |
|:--------------|---------:|
| False         | 12269137 |
| True          |     1847 |

### D3. entity_type vs is_passive

```sql
SELECT entity_type, is_passive, COUNT(*) AS cnt
FROM holdings_v2
WHERE entity_type IS NOT NULL
GROUP BY entity_type, is_passive
ORDER BY entity_type, is_passive
```

| entity_type          | is_passive   |     cnt |
|:---------------------|:-------------|--------:|
| SWF                  | False        |   14690 |
| SWF                  | True         |    7008 |
| active               | False        | 4161360 |
| active               | True         |   11367 |
| activist             | False        |    1033 |
| endowment_foundation | False        |   10258 |
| hedge_fund           | False        | 1159911 |
| hedge_fund           | True         |     193 |
| mixed                | False        | 2893109 |
| passive              | False        |   13186 |
| passive              | True         |  659337 |
| pension_insurance    | False        |  327501 |
| private_equity       | False        |    6655 |
| quantitative         | False        |  242038 |
| quantitative         | True         |   54963 |
| strategic            | False        |   40341 |
| venture_capital      | False        |    4774 |
| wealth_management    | False        | 2657782 |
| wealth_management    | True         |    5478 |


## SECTION E — Fund Level: `fund_universe.fund_strategy`

### E1. fund_strategy distribution

```sql
SELECT fund_strategy, COUNT(*) AS cnt
FROM fund_universe
GROUP BY fund_strategy
ORDER BY cnt DESC
```

| fund_strategy   |   cnt |
|:----------------|------:|
| equity          |  4591 |
| excluded        |  3673 |
| bond_or_other   |  2330 |
| index           |  1256 |
|                 |   658 |
| balanced        |   552 |
| active          |   310 |
| multi_asset     |   188 |
| final_filing    |    42 |
| passive         |    18 |
| mixed           |     5 |

### E2. fund_category distribution

```sql
SELECT fund_category, COUNT(*) AS cnt
FROM fund_universe
GROUP BY fund_category
ORDER BY cnt DESC
```

| fund_category   |   cnt |
|:----------------|------:|
| equity          |  4861 |
| excluded        |  3673 |
| bond_or_other   |  2330 |
| index           |  1256 |
|                 |   658 |
| balanced        |   599 |
| multi_asset     |   204 |
| final_filing    |    42 |

### E3. strategy vs category agreement

```sql
SELECT
  CASE WHEN fund_strategy = fund_category THEN 'match'
       WHEN fund_strategy IS NULL AND fund_category IS NULL THEN 'both_null'
       ELSE 'mismatch' END AS status,
  COUNT(*) AS cnt
FROM fund_universe
GROUP BY status
ORDER BY cnt DESC
```

| status    |   cnt |
|:----------|------:|
| match     | 12632 |
| both_null |   658 |
| mismatch  |   333 |

### E4. mismatched (strategy, category) pairs (top 20)

```sql
SELECT fund_strategy, fund_category, COUNT(*) AS cnt
FROM fund_universe
WHERE fund_strategy IS DISTINCT FROM fund_category
GROUP BY fund_strategy, fund_category
ORDER BY cnt DESC
LIMIT 20
```

| fund_strategy   | fund_category   |   cnt |
|:----------------|:----------------|------:|
| active          | equity          |   250 |
| active          | balanced        |    45 |
| active          | multi_asset     |    15 |
| passive         | equity          |    15 |
| mixed           | equity          |     5 |
| passive         | balanced        |     2 |
| passive         | multi_asset     |     1 |


## SECTION F — Fund Level: `is_actively_managed` vs `fund_strategy`

### F1. Cross-tab

```sql
SELECT fund_strategy, is_actively_managed, COUNT(*) AS cnt
FROM fund_universe
GROUP BY fund_strategy, is_actively_managed
ORDER BY fund_strategy, is_actively_managed
```

```
fund_strategy  is_actively_managed  cnt
       active                 True  310
     balanced                 True  552
bond_or_other                False 2330
       equity                 True 4591
     excluded                False 3673
 final_filing                False   42
        index                False 1256
        mixed                 True    5
  multi_asset                 True  188
      passive                False   18
         None                 <NA>  658
```

### F2. is_actively_managed = TRUE but strategy looks passive

```sql
SELECT fund_strategy, COUNT(*) AS cnt
FROM fund_universe
WHERE is_actively_managed = TRUE
  AND fund_strategy IN ('index', 'excluded', 'bond_or_other', 'final_filing', 'empty')
GROUP BY fund_strategy
ORDER BY cnt DESC
```

_(0 rows)_

### F3. is_actively_managed = FALSE but strategy looks active

```sql
SELECT fund_strategy, COUNT(*) AS cnt
FROM fund_universe
WHERE is_actively_managed = FALSE
  AND fund_strategy IN ('active', 'equity', 'mixed', 'balanced', 'multi_asset')
GROUP BY fund_strategy
ORDER BY cnt DESC
```

_(0 rows)_


## SECTION G — Fund Strategy Drift (the 6,195 issue)

### G1. Drifting funds count

```sql
SELECT COUNT(*) AS drifting_funds
FROM (
  SELECT series_id, COUNT(DISTINCT fund_strategy) AS n_strategies
  FROM fund_holdings_v2
  WHERE fund_strategy IS NOT NULL
  GROUP BY series_id
  HAVING COUNT(DISTINCT fund_strategy) > 1
)
```

|   drifting_funds |
|-----------------:|
|             6363 |

### G2. Strategy values appearing within drifters

```sql
WITH per_series AS (
  SELECT series_id, fund_strategy
  FROM fund_holdings_v2
  WHERE fund_strategy IS NOT NULL
  GROUP BY series_id, fund_strategy
),
drifters AS (
  SELECT series_id FROM per_series GROUP BY series_id HAVING COUNT(*) > 1
)
SELECT ps.fund_strategy, COUNT(DISTINCT ps.series_id) AS n_funds
FROM per_series ps JOIN drifters d ON ps.series_id = d.series_id
GROUP BY ps.fund_strategy
ORDER BY n_funds DESC
```

| fund_strategy   |   n_funds |
|:----------------|----------:|
| active          |      4965 |
| equity          |      4636 |
| passive         |      1006 |
| index           |       738 |
| balanced        |       615 |
| mixed           |       352 |
| excluded        |       227 |
| multi_asset     |       224 |
| bond_or_other   |        81 |
| final_filing    |        50 |

### G3. Top drift pairs

```sql
WITH vals AS (
  SELECT series_id, fund_strategy
  FROM fund_holdings_v2
  WHERE fund_strategy IS NOT NULL
  GROUP BY series_id, fund_strategy
),
drifters AS (
  SELECT series_id FROM vals GROUP BY series_id HAVING COUNT(*) > 1
),
pairs AS (
  SELECT a.series_id,
         a.fund_strategy AS strat_a,
         b.fund_strategy AS strat_b
  FROM vals a
  JOIN vals b ON a.series_id = b.series_id AND a.fund_strategy < b.fund_strategy
  WHERE a.series_id IN (SELECT series_id FROM drifters)
)
SELECT strat_a, strat_b, COUNT(*) AS n_funds
FROM pairs
GROUP BY strat_a, strat_b
ORDER BY n_funds DESC
LIMIT 15
```

| strat_a       | strat_b       |   n_funds |
|:--------------|:--------------|----------:|
| active        | equity        |      4340 |
| index         | passive       |       736 |
| active        | balanced      |       510 |
| equity        | mixed         |       259 |
| excluded      | passive       |       223 |
| active        | multi_asset   |       172 |
| balanced      | equity        |       100 |
| balanced      | mixed         |        69 |
| active        | bond_or_other |        50 |
| balanced      | multi_asset   |        45 |
| active        | final_filing  |        35 |
| mixed         | multi_asset   |        34 |
| equity        | passive       |        29 |
| balanced      | passive       |        25 |
| bond_or_other | multi_asset   |        17 |

### G4. First-seen value vs current fund_universe — would change?

```sql
WITH first_val AS (
  SELECT series_id, fund_strategy AS first_strategy,
         ROW_NUMBER() OVER (PARTITION BY series_id ORDER BY quarter, report_month) AS rn
  FROM fund_holdings_v2
  WHERE fund_strategy IS NOT NULL
),
first_only AS (
  SELECT series_id, first_strategy FROM first_val WHERE rn = 1
)
SELECT
  CASE WHEN fu.fund_strategy = fo.first_strategy THEN 'match'
       ELSE 'would_change' END AS status,
  COUNT(*) AS cnt
FROM fund_universe fu
JOIN first_only fo ON fu.series_id = fo.series_id
GROUP BY status
ORDER BY cnt DESC
```

| status       |   cnt |
|:-------------|------:|
| would_change |  7009 |
| match        |  6608 |


## SECTION H — `fund_holdings_v2.fund_strategy` vs `fund_universe.fund_strategy`

### H1. Latest-period agreement

```sql
SELECT
  CASE WHEN fh.fund_strategy = fu.fund_strategy THEN 'match'
       WHEN fh.fund_strategy IS NULL OR fu.fund_strategy IS NULL THEN 'one_null'
       ELSE 'mismatch' END AS status,
  COUNT(*) AS cnt
FROM fund_holdings_v2 fh
JOIN fund_universe fu ON fh.series_id = fu.series_id
WHERE fh.is_latest = TRUE
GROUP BY status
ORDER BY cnt DESC
```

| status   |     cnt |
|:---------|--------:|
| match    | 6838786 |
| mismatch | 5429877 |
| one_null | 2139107 |


## SECTION I — `peer_rotation_flows.entity_type`

### I1. Distinct values by level

```sql
SELECT level, entity_type, COUNT(*) AS cnt
FROM peer_rotation_flows
GROUP BY level, entity_type
ORDER BY level, cnt DESC
```

| level   | entity_type          |     cnt |
|:--------|:---------------------|--------:|
| fund    | active               | 1439311 |
| fund    | passive              | 1085567 |
| fund    | equity               |  777098 |
| fund    | index                |  610033 |
| fund    | excluded             |  454718 |
| fund    | mixed                |  370557 |
| fund    | balanced             |  172092 |
| fund    | bond_or_other        |   85001 |
| fund    | multi_asset          |   69437 |
| fund    | final_filing         |    1386 |
| parent  | active               | 5116516 |
| parent  | wealth_management    | 2965442 |
| parent  | mixed                | 1979668 |
| parent  | hedge_fund           | 1254746 |
| parent  | pension_insurance    |  455358 |
| parent  | passive              |  268988 |
| parent  | quantitative         |  255876 |
| parent  | strategic            |   65194 |
| parent  | SWF                  |   31564 |
| parent  | endowment_foundation |   12296 |
| parent  | private_equity       |   10906 |
| parent  | venture_capital      |    6658 |
| parent  | activist             |    1694 |

### I2. Values appearing in multiple levels

```sql
SELECT entity_type
FROM peer_rotation_flows
GROUP BY entity_type
HAVING COUNT(DISTINCT level) > 1
```

| entity_type   |
|:--------------|
| mixed         |
| active        |
| passive       |


## SECTION J — Impact Analysis: hardcoded filter variants

### J0. Most-populated ticker (test target)

| ticker   |   n_holders |
|:---------|------------:|
| MSFT     |        6558 |
| AAPL     |        6382 |
| AMZN     |        6331 |
| NVDA     |        6069 |
| GOOGL    |        5891 |


**Test target ticker:** `MSFT`

## SECTION J (cont.) — Filter variants for `MSFT`

### J1. Institution-level filter counts for `MSFT`

```sql
WITH base AS (
  SELECT DISTINCT COALESCE(inst_parent_name, manager_name) AS holder, entity_type
  FROM holdings_v2
  WHERE ticker = 'MSFT'
    AND is_latest = TRUE
    AND quarter = (SELECT MAX(quarter) FROM holdings_v2)
)
SELECT
  COUNT(*) AS total_holders,
  COUNT(CASE WHEN entity_type IN ('active','hedge_fund','activist') THEN 1 END) AS filter_trend_market,
  COUNT(CASE WHEN entity_type IN ('active','hedge_fund','activist','quantitative') THEN 1 END) AS filter_register_472,
  COUNT(CASE WHEN entity_type IN ('active','hedge_fund') THEN 1 END) AS filter_register_1018,
  COUNT(CASE WHEN entity_type IS NULL OR entity_type NOT IN ('passive') THEN 1 END) AS filter_not_passive,
  COUNT(CASE WHEN entity_type IS NOT NULL AND entity_type NOT IN ('passive','unknown') THEN 1 END) AS filter_not_passive_unknown
FROM base
```

|   total_holders |   filter_trend_market |   filter_register_472 |   filter_register_1018 |   filter_not_passive |   filter_not_passive_unknown |
|----------------:|----------------------:|----------------------:|-----------------------:|---------------------:|-----------------------------:|
|            6070 |                  3706 |                  3733 |                   3704 |                 6039 |                         6039 |

### J2. Fund-level filter counts for `MSFT`

```sql
WITH base AS (
  SELECT DISTINCT fh.series_id, fu.fund_strategy, fu.is_actively_managed
  FROM fund_holdings_v2 fh
  JOIN fund_universe fu ON fh.series_id = fu.series_id
  WHERE fh.ticker = 'MSFT' AND fh.is_latest = TRUE
)
SELECT
  COUNT(*) AS total_funds,
  COUNT(CASE WHEN is_actively_managed = TRUE THEN 1 END) AS filter_is_actively_managed,
  COUNT(CASE WHEN fund_strategy IN ('active','equity','mixed','balanced','multi_asset') THEN 1 END) AS filter_active_fund_types,
  COUNT(CASE WHEN fund_strategy NOT IN ('passive','index','bond_or_other','excluded','final_filing','empty','unknown')
              OR fund_strategy IS NULL THEN 1 END) AS filter_proposed_exclude
FROM base
```

|   total_funds |   filter_is_actively_managed |   filter_active_fund_types |   filter_proposed_exclude |
|--------------:|-----------------------------:|---------------------------:|--------------------------:|
|          2613 |                         1601 |                       1601 |                      1680 |


## SECTION K — `_classify_fund_type()` (name regex) vs stored fields

### K1. 20-fund sample (random) — equity/balanced/multi_asset only

```sql
SELECT fu.fund_name, fu.fund_strategy, fu.is_actively_managed,
  CASE
    WHEN UPPER(fu.fund_name) LIKE '%INDEX%' THEN 'passive'
    WHEN UPPER(fu.fund_name) LIKE '%ETF%' THEN 'passive'
    WHEN UPPER(fu.fund_name) LIKE '%MSCI%' THEN 'passive'
    WHEN UPPER(fu.fund_name) LIKE '%FTSE%' THEN 'passive'
    WHEN UPPER(fu.fund_name) LIKE '%TOTAL STOCK%' THEN 'passive'
    WHEN UPPER(fu.fund_name) LIKE '%TOTAL MARKET%' THEN 'passive'
    WHEN UPPER(fu.fund_name) LIKE '%NASDAQ%' THEN 'passive'
    WHEN UPPER(fu.fund_name) LIKE '%S&P%500%' THEN 'passive'
    WHEN UPPER(fu.fund_name) LIKE '%RUSSELL%1000%' THEN 'passive'
    WHEN UPPER(fu.fund_name) LIKE '%RUSSELL%2000%' THEN 'passive'
    ELSE 'active'
  END AS name_regex_result
FROM fund_universe fu
WHERE fu.fund_strategy IN ('equity','balanced','multi_asset')
ORDER BY RANDOM()
LIMIT 20
```

| fund_name                                                  | fund_strategy   | is_actively_managed   | name_regex_result   |
|:-----------------------------------------------------------|:----------------|:----------------------|:--------------------|
| Janus Henderson Triton Fund                                | equity          | True                  | active              |
| SA American Funds Growth Portfolio                         | equity          | True                  | active              |
| VIP Freedom Lifetime Income III Portfolio                  | equity          | True                  | active              |
| International Strategic Equities Portfolio                 | equity          | True                  | active              |
| Applied Finance Explorer Fund                              | equity          | True                  | active              |
| Nomura Growth and Income Fund                              | equity          | True                  | active              |
| NVIT Fidelity Institutional AM Worldwide Fund              | equity          | True                  | active              |
| Guinness Atkinson Alternative Energy Fund                  | equity          | True                  | active              |
| Transamerica Balanced II                                   | multi_asset     | True                  | active              |
| T. Rowe Price Emerging Europe Fund                         | equity          | True                  | active              |
| Select Insurance Portfolio                                 | equity          | True                  | active              |
| Transamerica US Growth                                     | equity          | True                  | active              |
| Allspring Spectrum Moderate Growth Fund                    | equity          | True                  | active              |
| Cullen High Dividend Equity Fund                           | equity          | True                  | active              |
| Pacific Dynamix - Moderate Growth Portfolio                | equity          | True                  | active              |
| NICHOLAS PARTNERS SMALL CAP GROWTH FUND                    | equity          | True                  | active              |
| THRIVENT LARGE CAP VALUE PORTFOLIO                         | equity          | True                  | active              |
| Columbia Variable Portfolio - Select Large Cap Equity Fund | equity          | True                  | active              |
| JNL/RAFI Fundamental U.S. Small Cap Fund                   | equity          | True                  | active              |
| WisdomTree Japan Opportunities Fund                        | equity          | True                  | active              |

### K2. Disagreement at scale

```sql
SELECT
  CASE
    WHEN UPPER(fu.fund_name) SIMILAR TO '%(INDEX|ETF|MSCI|FTSE|TOTAL STOCK|TOTAL MARKET|NASDAQ|EXCHANGE.TRADED|BROAD MARKET|TRACKER|DOW JONES|WILSHIRE|STOXX|NIKKEI)%' THEN 'passive'
    WHEN UPPER(fu.fund_name) SIMILAR TO '%(S&P.*500|RUSSELL.*1000|RUSSELL.*2000|RUSSELL.*3000|BLOOMBERG.*AGGREGATE)%' THEN 'passive'
    ELSE 'active'
  END AS name_result,
  fund_strategy,
  is_actively_managed,
  COUNT(*) AS cnt
FROM fund_universe fu
GROUP BY name_result, fund_strategy, is_actively_managed
ORDER BY cnt DESC
LIMIT 60
```

| name_result   | fund_strategy   | is_actively_managed   |   cnt |
|:--------------|:----------------|:----------------------|------:|
| active        | equity          | True                  |  4591 |
| active        | excluded        | False                 |  3673 |
| active        | bond_or_other   | False                 |  2330 |
| active        | index           | False                 |  1256 |
| active        |                 | <NA>                  |   658 |
| active        | balanced        | True                  |   552 |
| active        | active          | True                  |   310 |
| active        | multi_asset     | True                  |   188 |
| active        | final_filing    | False                 |    42 |
| active        | passive         | False                 |    18 |
| active        | mixed           | True                  |     5 |


## SECTION L — Managers table cross-check

### L1. managers.strategy_type distribution

> Spec asked for `managers.manager_type`; managers table actually exposes `strategy_type`. Using that as the equivalent column.

```sql
SELECT strategy_type, COUNT(*) AS cnt
FROM managers
GROUP BY strategy_type
ORDER BY cnt DESC
```

| strategy_type        |   cnt |
|:---------------------|------:|
| active               |  5500 |
| _(empty string)_     |  1293 |
| mixed                |  1277 |
| strategic            |   911 |
| wealth_management    |   803 |
| hedge_fund           |   573 |
| pension_insurance    |   195 |
| passive              |   130 |
| endowment_foundation |   121 |
| private_equity       |   111 |
| quantitative         |    77 |
| venture_capital      |    57 |
| family_office        |    51 |
| activist             |    26 |
| SWF                  |     7 |
| multi_strategy       |     2 |
| unknown              |     1 |

### L2. holdings_v2.manager_type vs managers.strategy_type (latest only)

```sql
SELECT
  CASE WHEN h.manager_type = m.strategy_type THEN 'match'
       WHEN h.manager_type IS NULL THEN 'holdings_null'
       WHEN m.strategy_type IS NULL THEN 'managers_null'
       ELSE 'mismatch' END AS status,
  COUNT(*) AS cnt
FROM holdings_v2 h
LEFT JOIN managers m ON CAST(h.cik AS VARCHAR) = CAST(m.cik AS VARCHAR)
WHERE h.is_latest = TRUE
GROUP BY status
ORDER BY cnt DESC
```

| status        |     cnt |
|:--------------|--------:|
| match         | 8739449 |
| mismatch      | 2336475 |
| managers_null | 1195060 |

(`holdings_null` returns 0 — `holdings_v2.manager_type` is non-null on every latest row.)



## Summary — Confirmed Facts and Open Questions

### Confirmed facts

**Institution-level (`holdings_v2`)**

- `entity_type` is 100% populated (12.27M / 12.27M rows, all four 2025 quarters at 100%). 13 distinct values: `active, mixed, wealth_management, hedge_fund, passive, pension_insurance, quantitative, strategic, SWF, endowment_foundation, private_equity, venture_capital, activist`. **No `unknown` category.**
- `manager_type` is also fully populated (no NULL latest rows in §L2). 15 distinct values — superset of `entity_type` plus `family_office` (36,950) and `multi_strategy` (553). Does **not** contain `endowment_foundation` ordering or `venture_capital` separately the same way; close but not identical taxonomies.
- `entity_type` and `manager_type` disagree often. Examples (top mismatches): `wealth_management/mixed` 785,790, `wealth_management/active` 600,070, `hedge_fund/quantitative` 359,772, `active/mixed` 284,883, `hedge_fund/active` 208,043. They are **not redundant** — they encode different views.
- `is_passive` and `is_activist` are 100% populated (boolean defaults). `is_passive=TRUE`: 738,346 rows (~6%). `is_activist=TRUE`: 1,847 rows (~0.015%).
- `is_passive` does **not** equal `entity_type='passive'`:
  - 13,186 rows have `entity_type='passive'` but `is_passive=FALSE`
  - 11,367 rows have `entity_type='active'` but `is_passive=TRUE`
  - 54,963 rows have `entity_type='quantitative'` but `is_passive=TRUE`
  - 7,008 rows have `entity_type='SWF'` but `is_passive=TRUE`
  - Aggregate: at least 88,524 rows where the two booleans diverge from the categorical.
- `is_activist=TRUE` (1,847) is larger than `entity_type='activist'` (1,033). They reference overlapping but distinct populations.

**Institution-level (`entity_classification_history`)**

- 27,152 open rows (`valid_to = '9999-12-31'`). 15 categories, **including `unknown` (3,852)** and `market_maker` (23) which are absent from `holdings_v2.entity_type`. So the per-row `holdings_v2.entity_type` is sourced from a different mapping (or has post-processing collapsing `unknown` and `market_maker`).

**Fund-level (`fund_universe`)**

- `fund_strategy` has 11 distinct values: `equity, excluded, bond_or_other, index, '' (empty string, 658 rows), balanced, active, multi_asset, final_filing, passive, mixed`. **Note: `''` (empty string) is the value, not the literal token `'empty'`** — the spec used `'empty'` in filter SQL; that filter never matches anything.
- `fund_category` has 8 distinct values; missing `active`, `passive`, `mixed` from strategy. So strategy is **finer-grained** than category.
- 333 rows have `fund_strategy ≠ fund_category` (out of 13,623 total). Top mismatches: `active/equity` 250, `active/balanced` 45, `active/multi_asset` 15, `passive/equity` 15. So `category` collapses {active, passive, mixed} into their underlying asset class.
- `is_actively_managed` is a **deterministic derivative of `fund_strategy`** at the row level:
  - TRUE for `{active, balanced, equity, mixed, multi_asset}`
  - FALSE for `{bond_or_other, excluded, final_filing, index, passive}`
  - NULL for `''`
  - 0 rows of inversion in either direction (F2/F3 both empty).
  - **`is_actively_managed` is redundant with `fund_strategy`**: any logic on one can be expressed on the other.

**Fund-strategy drift (`fund_holdings_v2`)**

- 6,363 series_ids show >1 distinct `fund_strategy` over their history (current value, not 6,195 from prior session — likely changed with newer quarters).
- Top drift pair by far: `active ↔ equity` (4,340 funds), then `index ↔ passive` (736), `active ↔ balanced` (510), `equity ↔ mixed` (259), `excluded ↔ passive` (223). Most drift is between siblings under the same `fund_category`, not between active/passive.
- A "lock on first-seen value" rule would change **7,009 / 13,617 (51.5%)** funds in `fund_universe`; 6,608 (48.5%) would match the current value. So even though strategy drifts on a minority of series, the `fund_universe` snapshot has drifted away from the original on >half of joinable series.

**Fund-strategy storage divergence (§H)**

- For latest-period rows joined fund_holdings_v2 → fund_universe (14.4M rows): `match` 6.84M (47.5%), `mismatch` 5.43M (37.7%), `one_null` 2.14M (14.9%). The two storage locations of `fund_strategy` **disagree on more than 1/3 of latest rows**. This is the load-bearing classification finding.

**Mixed-taxonomy column (§I)**

- `peer_rotation_flows.entity_type` carries fund-level values (`equity, index, balanced, multi_asset, bond_or_other`) and parent-level values (`wealth_management, hedge_fund, pension_insurance, …`) in the **same column**, partitioned only by `level`. Three values appear at both levels: `mixed`, `active`, `passive`.

**Filter-variant impact (§J, target=`MSFT`, 6,070 institution-level holders, 2,613 latest-period funds)**

| Institution filter (entity_type) | Holders (MSFT) |
|:---|---:|
| `IN (active, hedge_fund, activist)` | 3,706 |
| `IN (active, hedge_fund, activist, quantitative)` | 3,733 |
| `IN (active, hedge_fund)` | 3,704 |
| `NOT IN (passive)` (incl. NULL) | 6,039 |
| `NOT IN (passive, unknown)` (excl. NULL) | 6,039 |

  - Spread between narrowest and widest "active" filter: **3,704 → 6,039 (1.63x)**.
  - `not_passive` vs `not_passive_unknown` collapse to identical counts only because `entity_type` is fully populated and never `unknown`.

| Fund filter | Funds (MSFT) |
|:---|---:|
| `is_actively_managed = TRUE` | 1,601 |
| `fund_strategy IN (active, equity, mixed, balanced, multi_asset)` | 1,601 |
| `fund_strategy NOT IN (passive, index, bond_or_other, excluded, final_filing, empty, unknown)` | 1,680 |

  - The "proposed exclude" list returns 79 more funds than the "active types" list — those are the 658 funds with `fund_strategy = ''` (empty string), of which 79 hold MSFT. The token `'empty'` in the spec exclusion list never matches the actual blank-string value.

**Name-regex classifier (`_classify_fund_type`) — §K**

- ⚠ **K2 query is unreliable**: in DuckDB `SIMILAR TO` uses POSIX regex semantics, so `%` is a literal character not a wildcard. The K2 result therefore tagged 0 rows as `passive`. The K1 LIKE-based version (which is correct syntax) produced 20/20 'active' verdicts on equity/balanced/multi_asset funds — consistent with stored `fund_strategy`, since those buckets exclude the obvious passive name-keyword funds.
- A correct rerun of K2 against `fund_universe` is needed before drawing conclusions on regex-vs-stored disagreement.

**Managers cross-check (§L)**

- `managers.strategy_type` (not `manager_type` — spec column name was wrong) has 17 values; superset of `holdings_v2.manager_type` (adds blank string, plus `unknown`, plus `multi_strategy`/`family_office` which are also in holdings).
- At latest-period rows, `holdings_v2.manager_type` vs `managers.strategy_type`: 8.74M match, 2.34M mismatch (~19%), 1.20M no managers row at all. The two surfaces are **not in sync**.

### Open questions / contradictions vs code-level audit

1. **`unknown` category:** present in `entity_classification_history` (3,852 open rows) and in `managers.strategy_type` (1 row), absent from `holdings_v2.entity_type` and `holdings_v2.manager_type`. Where does the collapse happen? Is `unknown` deliberately remapped at load, and to what?
2. **Empty-string vs `'empty'`:** filter SQL across the codebase that uses `'empty'` as a token will silently never match the 658 blank-string rows. Confirm callers and decide canonical sentinel.
3. **`is_passive` / `is_activist` divergence from categorical fields:** 88K+ rows of inconsistency. Is one the source of truth and the other stale, or do they encode different concepts (e.g. is_passive = "this filing is via passive sleeve" vs entity_type = "manager house style")? Need owner of these columns.
4. **`fund_universe` vs `fund_holdings_v2` divergence (5.43M mismatched latest rows):** which is canonical? `fund_universe` is the documented snapshot — but if 38% of latest holdings rows disagree, downstream queries pick different answers based on which table they read.
5. **Strategy drift = noise or signal?** 4,340 of 6,363 drifters bounce between `active` and `equity`, which `fund_category` already collapses. Is that drift coming from a single classifier flipping arbitrarily, or from the underlying N-PORT data legitimately changing description? Worth a per-quarter trace for a sample series.
6. **`peer_rotation_flows.entity_type` mixed taxonomy:** combining fund-level and parent-level values in one column with `level` as a discriminator means any direct GROUP BY on entity_type without `level` is meaningless. Is downstream code aware of this?
7. **Managers-vs-holdings 19% mismatch:** which surface drives UI? The 1.20M `managers_null` rows imply some holdings reference CIKs without a corresponding managers row; that breaks any join-based filtering.
8. **6,363 vs 6,195 drifting funds:** prior session referenced 6,195. Was the earlier number scoped to a fixed quarter range, or has the count grown organically? Worth noting before re-using the older figure.
9. **K2 (regex-vs-stored disagreement count):** unreliable due to `SIMILAR TO`/`%` mismatch. Re-run with `LIKE` ladder or `regexp_matches` before basing any decision on it.

### Schema corrections vs spec

| Spec | Actual |
|:---|:---|
| `entity_classification_history.closed_at IS NULL` | `valid_to = DATE '9999-12-31'` |
| `managers.manager_type` | `managers.strategy_type` |
| `fund_strategy = 'empty'` | `fund_strategy = ''` (empty string, 658 rows) |
| K2 `SIMILAR TO '%(...)%'` | DuckDB `SIMILAR TO` is POSIX regex; `%` is literal; query returns 0 'passive' matches. Need `LIKE` ladder or `regexp_matches`. |

