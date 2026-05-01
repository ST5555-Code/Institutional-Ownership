# Fund Orphan Investigation

**Date:** 2026-05-01
**Branch:** `fund-orphan-audit`
**Mode:** Read-only audit. No DB writes.
**Scope:** Rows in `fund_holdings_v2` whose `series_id` has no matching row in
`fund_universe`. Surfaced as a follow-up by PR #242 (§1b, §1h).

## Executive summary

302 distinct N-PORT fund series are present in `fund_holdings_v2.is_latest = TRUE`
but have **no matching row** in `fund_universe`, contributing 160,934 holding
rows and **$658.5B of holding value** (1.10% of latest rows, 0.41% of latest
AUM). The cohort splits cleanly: **301 series carry real SEC `S` series_ids**
(157,750 rows, $648.5B), and **1 series carries the literal token `UNKNOWN`**
(3,184 rows, $10.0B — a single Calamos Global Total Return Fund filer that
landed before DERA Session 2). Zero `SYN_*` orphans confirms PR #199 holds.
The cohort is overwhelmingly recent: it appears in volume from **2025Q3
onward** (24K rows in 2025Q3, 101K in 2025Q4), so this is a fund-universe
*backfill miss* against newly-filed series, not legacy debt. Public-facing
display impact today is muted — `cross.py` already 3-way-CASEs `is_active` to
`NULL` for these rows and the React badge labels them `mixed`, but the
"Active only" toggle in `OverlapAnalysisTab` keeps `is_active !== false`,
which still admits `NULL` orphans into the active bucket. The recommended
fix is **BACKFILL_FUND_UNIVERSE** for the S9-digit cohort (snapshot-majority
strategy from `fund_strategy_at_filing`, derived per series), and
**REWRITE_NULL_ARM** to default `'unknown'` (with `_fund_type_label` →
`'unknown'`) for any residual NULL after backfill — so the "active only"
filter no longer admits unclassified rows.

## Methodology

All numbers below come from the helper script
[scripts/oneoff/audit_orphan_inventory.py](scripts/oneoff/audit_orphan_inventory.py),
run against `data/13f.duckdb` in read-only mode. Pre-commit grep for
`INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE` returned zero matches.

The reusable `orphan` CTE is:

```sql
WITH orphan AS (
    SELECT fh.*
    FROM fund_holdings_v2 fh
    LEFT JOIN fund_universe fu USING (series_id)
    WHERE fu.series_id IS NULL
)
```

Note on `holding_value` vs `market_value_usd`: the plan refers generically to
"holding value"; the actual column on `fund_holdings_v2` is
`market_value_usd`, which the [cross.py](scripts/queries/cross.py) builders
also alias as `holding_value`. AUM totals below sum `market_value_usd` over
`is_latest = TRUE` rows.

## Phase 1 — Inventory

### Totals

```sql
SELECT COUNT(DISTINCT series_id), COUNT(*), SUM(market_value_usd)
FROM orphan
WHERE is_latest = TRUE;
-- and again with no is_latest filter (full history)
```

| Scope                         | Distinct series | Rows        | AUM ($)            |
|-------------------------------|-----------------|-------------|--------------------|
| `is_latest = TRUE`            | 302             | 160,934     | 658,486,891,872    |
| All history                   | 302             | 160,934     | 658,486,891,872    |
| % of total `fund_holdings_v2` | —               | 1.10%       | 0.41%              |

The two scopes are identical, which by itself is a strong signal: **every
orphan row is a current latest-snapshot row**. There is no historical orphan
debt — the cohort is built entirely from filings that landed since the most
recent snapshot pivot.

### Per-quarter breakdown (`is_latest = TRUE`)

```sql
SELECT quarter, COUNT(DISTINCT series_id), COUNT(*), SUM(market_value_usd)
FROM orphan WHERE is_latest = TRUE GROUP BY quarter ORDER BY quarter;
```

| Quarter | Distinct series | Rows    | AUM ($)            |
|---------|-----------------|---------|--------------------|
| 2024Q4  | 1               | 109     | 975,241,379        |
| 2025Q1  | 1               | 302     | 4,074,195,920      |
| 2025Q2  | 1               | 733     | 899,629,832        |
| 2025Q3  | 83              | 23,565  | 50,800,678,483     |
| 2025Q4  | 296             | 100,925 | 455,225,160,238    |
| 2026Q1  | 104             | 35,300  | 146,511,986,021    |

Interpretation: the 2024Q4–2025Q2 single-series tail is **the `UNKNOWN`
literal** (Calamos). The 2025Q3 jump is when DERA Session 2 began ingesting
real `S`-prefixed series_ids. The 2025Q4 peak (296 series, $455B) is the
universe-loader miss against the latest filing wave; 2026Q1 is partial-quarter
data so the apparent dip is timing, not coverage recovery.

### Top 25 orphan series by row count (top 12 shown)

```sql
SELECT series_id, ANY_VALUE(fund_name), ANY_VALUE(fund_cik),
       COUNT(*), SUM(market_value_usd)
FROM orphan WHERE is_latest = TRUE
GROUP BY series_id ORDER BY 4 DESC LIMIT 25;
```

| Series ID    | Fund                                                | CIK         | Rows   | AUM ($)             |
|--------------|-----------------------------------------------------|-------------|--------|---------------------|
| S000009238   | Tax Exempt Bond Fund of America                     | 0000050142  | 10,606 | 48,164,858,424      |
| S000009229   | American High-Income Municipal Bond Fund            | 0000925950  | 7,418  | 26,592,802,562      |
| S000045538   | Blackstone Alternative Multi-Strategy Fund          | 0001557794  | 7,152  | 2,540,851,766       |
| S000009231   | Bond Fund of America                                | 0000013075  | 5,801  | 101,149,751,897     |
| S000008396   | VOYA INTERMEDIATE BOND FUND                         | 0001066602  | 5,016  | 21,316,654,174      |
| S000029560   | AB Municipal Income Shares                          | 0001274676  | 4,654  | 34,589,457,487      |
| S000002536   | MFS Municipal Income Fund                           | 0000751656  | 4,384  | 12,649,956,485      |
| S000062381   | Advantage CoreAlpha Bond Master Portfolio           | 0001738077  | 4,152  | 1,570,873,540       |
| S000008760   | VOYA INTERMEDIATE BOND PORTFOLIO                    | 0000002646  | 3,905  | 1,845,505,997       |
| S000009237   | Limited Term Tax Exempt Bond Fund of America        | 0000909427  | 3,843  | 11,891,700,569      |
| S000047257   | FlexShares Credit-Scored US Corporate Bond Index    | 0001491978  | 3,500  | 1,536,018,830       |
| UNKNOWN      | Asa Gold & Precious Metals Ltd (legacy `UNKNOWN`)   | 0001230869  | 3,184  | 10,024,654,106      |

Heavy bond/municipal-fund concentration in row counts — these are
high-line-item portfolios with thousands of CUSIPs each, so even one
missing-from-universe series adds tens of thousands of holdings to the cohort.

### Top 25 orphan series by AUM (top 7 shown)

| Series ID    | Fund                                       | CIK         | Rows   | AUM ($)             |
|--------------|--------------------------------------------|-------------|--------|---------------------|
| S000009231   | Bond Fund of America                       | 0000013075  | 5,801  | 101,149,751,897     |
| S000009238   | Tax Exempt Bond Fund of America            | 0000050142  | 10,606 | 48,164,858,424      |
| S000029560   | AB Municipal Income Shares                 | 0001274676  | 4,654  | 34,589,457,487      |
| S000001147   | TCW METWEST TOTAL RETURN BOND FUND         | 0001028621  | 1,552  | 33,663,672,207      |
| S000009236   | Intermediate Bond Fund of America          | 0000826813  | 2,849  | 28,536,743,012      |
| S000009229   | American High-Income Municipal Bond Fund   | 0000925950  | 7,418  | 26,592,802,562      |
| S000009230   | American High Income Trust                 | 0000823620  | 1,027  | 26,300,655,376      |

Same theme — large bond/credit funds dominate AUM. The single notable
non-credit name in the top 25 by AUM is **ARK Innovation ETF (S000042977,
$15.1B)**, which `fund_strategy_at_filing` will misclassify (see Phase 3
notes) and is an example of why snapshot-majority strategy carries
exception risk.

## Phase 2 — Cohort partition

```sql
WITH classed AS (
    SELECT *,
           CASE
             WHEN series_id LIKE 'SYN_%'                   THEN 'SYN_prefix'
             WHEN regexp_matches(series_id, '^S[0-9]{9}$') THEN 'S9digit'
             WHEN series_id = 'UNKNOWN'                    THEN 'UNKNOWN_literal'
             ELSE 'Other'
           END AS cohort
    FROM orphan
)
SELECT cohort, COUNT(DISTINCT series_id), COUNT(*), SUM(market_value_usd)
FROM classed WHERE is_latest = TRUE GROUP BY cohort ORDER BY 3 DESC;
```

| Cohort            | Distinct series | Rows    | AUM ($)            |
|-------------------|-----------------|---------|--------------------|
| `S9digit`         | 301             | 157,750 | 648,462,237,766    |
| `UNKNOWN_literal` | 1               | 3,184   | 10,024,654,106     |
| `SYN_prefix`      | 0               | 0       | 0                  |
| `Other`           | 0               | 0       | 0                  |

Clean partition. **Zero `SYN_*` rows** confirms PR #199 (DERA Tier 4
stabilizer family) still holds — no regression. **Zero "Other"** means every
orphan series_id in production today is either a real SEC S-series or the
single literal token `UNKNOWN`.

## Phase 3 — Root-cause trace

### 3a. `fund_strategy_at_filing` distribution per cohort

```sql
-- same `classed` CTE
SELECT cohort, COALESCE(fund_strategy_at_filing, '<null>') AS strategy,
       COUNT(*), SUM(market_value_usd)
FROM classed WHERE is_latest = TRUE GROUP BY cohort, strategy
ORDER BY cohort, 3 DESC;
```

| Cohort            | Snapshot strategy   | Rows     | AUM ($)            |
|-------------------|---------------------|----------|--------------------|
| `S9digit`         | `bond_or_other`     | 126,853  | 561,226,665,896    |
| `S9digit`         | `excluded`          | 17,619   | 66,911,675,806     |
| `S9digit`         | `passive`           | 13,047   | 20,297,205,366     |
| `S9digit`         | `active`            | 231      | 26,690,698         |
| `UNKNOWN_literal` | `active`            | 3,184    | 10,024,654,106     |

Two important reads:

- For the **S9digit cohort**, the `fund_strategy_at_filing` snapshot is
  **highly informative**: 80.4% bond, 11.2% excluded, 8.3% passive, 0.1%
  active. Snapshot-majority would correctly route the bulk of these series
  to the non-active buckets — exactly the opposite of what the current NULL
  arm does in the active-only filter.
- For the **UNKNOWN literal cohort**, the snapshot says `active` — but the
  underlying fund (Calamos Global Total Return) is a balanced fund. The
  snapshot label is **unreliable** for this cohort because it was set by
  the pre-DERA-Session-2 8-CIK fallback loader before the classifier had
  enough context. Snapshot-majority is therefore not safe here.

### 3b. CIK fan-out for S9digit cohort (top 10 CIKs)

```sql
SELECT fund_cik, COUNT(DISTINCT series_id), COUNT(*), SUM(market_value_usd)
FROM orphan WHERE is_latest = TRUE
  AND regexp_matches(series_id, '^S[0-9]{9}$')
GROUP BY fund_cik ORDER BY 3 DESC LIMIT 10;
```

| CIK         | Distinct series | Rows   | AUM ($)             |
|-------------|-----------------|--------|---------------------|
| 0000050142  | 1               | 10,606 | 48,164,858,424      |
| 0001491978  | 9               | 10,312 | 14,811,837,561      |
| 0000751656  | 14              | 10,070 | 19,047,381,605      |
| 0000925950  | 1               | 7,418  | 26,592,802,562      |
| 0001557794  | 1               | 7,152  | 2,540,851,766       |
| 0001066602  | 3               | 6,810  | 24,556,377,126      |
| 0001274676  | 4               | 6,294  | 37,141,221,994      |
| 0000013075  | 1               | 5,801  | 101,149,751,897     |
| 0001738077  | 1               | 4,152  | 1,570,873,540       |
| 0000002646  | 1               | 3,905  | 1,845,505,997       |

Most rows concentrate at filer-CIK level — many of these CIKs are large
fund families (American Funds at CIKs 50142/925950/13075/823620/826813/909427,
MFS at 751656, Voya at 1066602/2646, AllianceBernstein at 1274676), which
suggests the universe loader missed the classifier output for the most
recent N-PORT filing wave from these issuers.

### 3c. Coarse name-match candidates (S9digit cohort)

```sql
WITH s9 AS (...)  -- distinct (series_id, fund_cik, lower(trim(fund_name)))
SELECT
    COUNT(*) FILTER (WHERE EXISTS_at_same_cik)             AS same_cik_in_fu,
    COUNT(*) FILTER (WHERE EXISTS_with_exact_norm_name)    AS name_exact_match,
    COUNT(*) FILTER (WHERE NEITHER)                        AS no_obvious_match,
    COUNT(*) AS total
FROM s9;
```

| Metric                           | Series count |
|----------------------------------|--------------|
| Same CIK already in `fund_universe`         | 61          |
| Exact `lower(trim(fund_name))` already in FU| 3           |
| No obvious match (new series)               | 241         |
| **Total S9digit orphan series**             | 304*        |

*Counts 304 because the `s9` CTE de-dupes on `(series_id, fund_cik,
norm_name)`; a few series carry both an upper-case and a mixed-case
`fund_name` snapshot across reports. Distinct-on-`series_id` is still 301
(matches Phase 2).

Interpretation:
- **241 / 304 series have no FU match** at all — these are net-new SEC
  series the universe builder hasn't ingested. Most likely root cause:
  N-PORT filings landed in `stg_nport_fund_universe` after the most recent
  `_upsert_fund_universe` run, and the next run's `COALESCE` on locked
  `fund_strategy` did not add the row because the loader's UPSERT predicate
  filters by some other condition. Worth confirming against the next live
  pipeline run.
- **61 series share a CIK with FU rows** — likely the same fund family
  added a new share class / sub-series the universe loader missed.
- **3 series have an exact normalized-name match** — possible
  rename/merge candidates worth manual review before backfill.

### 3d. Spot checks (four named cases)

#### Tax Exempt Bond Fund of America (10,606 rows)

| Side          | series_id  | fund_name                                        | CIK         | first–last       | Rows / AUM           |
|---------------|------------|--------------------------------------------------|-------------|------------------|----------------------|
| Orphan        | S000009238 | Tax Exempt Bond Fund of America                  | 0000050142  | 2025-10 → 2026-01| 10,606 / $48.2B      |
| Orphan        | S000009237 | Limited Term Tax Exempt Bond Fund of America     | 0000909427  | 2025-10 → 2026-01| 3,843 / $11.9B       |
| `fund_universe` | (no rows) | —                                              | —           | —                | —                    |

Snapshot label: `bond_or_other`. Universe row absent at *both* CIKs. This is
a clean **BACKFILL_FUND_UNIVERSE** target — derive `fund_strategy =
'bond_or_other'` from the snapshot.

#### Blackstone Alternative Multi-Strategy Fund (7,152 rows)

| Side          | series_id  | fund_name                                  | CIK         | first–last       | Rows / AUM           |
|---------------|------------|--------------------------------------------|-------------|------------------|----------------------|
| Orphan        | S000045538 | Blackstone Alternative Multi-Strategy Fund | 0001557794  | 2025-12 → 2025-12| 7,152 / $2.54B       |
| `fund_universe` | (no rows) | —                                        | —           | —                | —                    |

Snapshot: `bond_or_other` (the cohort majority). This is **misclassified
at filing time** — Blackstone Alternative Multi-Strategy is by name a
multi-asset alternative-strategies fund. Recommended action:
`INVESTIGATE_FURTHER` before backfilling — snapshot is wrong, classifier
needs a rerun for this CIK before the universe row is added.

#### VOYA INTERMEDIATE BOND FUND (5,016 rows)

| Side          | series_id  | fund_name                       | CIK         | first–last       | Rows / AUM           |
|---------------|------------|---------------------------------|-------------|------------------|----------------------|
| Orphan        | S000008396 | VOYA INTERMEDIATE BOND FUND     | 0001066602  | 2025-09 → 2025-12| 5,016 / $21.3B       |
| `fund_universe` | (no rows) | —                             | —           | —                | —                    |

Snapshot: `bond_or_other`. Clean **BACKFILL_FUND_UNIVERSE** target.

#### Calamos Global Total Return Fund (1,412 rows)

| Side          | series_id        | fund_name                          | CIK         | Rows / AUM      |
|---------------|------------------|------------------------------------|-------------|-----------------|
| Orphan        | `UNKNOWN`        | Calamos Global Total Return Fund   | 0001285650  | 1,412 / $325M   |
| `fund_universe` | `SYN_0001285650` | CALAMOS GLOBAL TOTAL RETURN FUND   | 0001285650  | (strategy=balanced) |

This is the diagnostic case for the entire `UNKNOWN_literal` cohort. The
universe row exists under the legacy `SYN_0001285650` series_id (left over
from the pre-DERA-Session-2 8-CIK loader) with `fund_strategy = balanced`,
but the new holdings carry the literal token `UNKNOWN` as series_id. The
LEFT JOIN therefore misses, and the row falls to the orphan bucket.
Recommended action: **REWRITE_NULL_ARM** — leave universe alone (the SYN
row stays as historical context) and have `cross.py` default to
`'unknown'` for `series_id = 'UNKNOWN'` rows. Backfilling a new
`UNKNOWN`-keyed `fund_universe` row would create a name collision against
the SYN entry without semantic gain.

(Note: the audit also surfaced a separate top-10-by-rows row labeled
`UNKNOWN / Asa Gold & Precious Metals Ltd / CIK 0001230869` with 3,184 rows
and $10.0B AUM. This is the same literal-`UNKNOWN` series_id but tied to a
different filer. Treatment is identical — the literal-`UNKNOWN` cohort is
1 series_id covering multiple unrelated filers, all of which need the
`REWRITE_NULL_ARM` path.)

## Display impact today

`scripts/queries/cross.py:431-436` and `:677-682` already 3-way-CASE
`fund_strategy`:

```sql
CASE WHEN fu.fund_strategy IN (active, balanced, multi_asset) THEN TRUE
     WHEN fu.fund_strategy IS NULL                            THEN NULL
     ELSE FALSE
END AS is_active
```

Front-end consumers (`web/react-app/src/components/tabs/OverlapAnalysisTab.tsx`):

| Surface                                  | NULL `is_active` behavior              |
|------------------------------------------|----------------------------------------|
| Badge column (line 817)                  | shown as **`mixed`**                   |
| Active-only toggle (line 194)            | filter `r.is_active !== false` **keeps NULL rows** (orphans pass as active) |
| KPI tile `fundStatsActive` (line 213)    | same — NULL counted as active          |
| CSV export "Type" column (line 227)      | `r.is_active ? 'active' : 'passive'` — NULL → `'passive'` |

So the user-stated "silently labeled active" claim is **partially correct**:
the active-only filter and active KPI tile do admit orphans into the active
bucket; the badge label and CSV both render NULL as `mixed`/`passive`
respectively. The active-bucket leak is the load-bearing display defect.

## Phase 4 — Per-cohort treatment recommendation

| Cohort                        | Distinct series | Rows latest | AUM latest ($)     | Root cause (one phrase)                                                  | Recommended action      | Confidence | Blockers / open questions |
|-------------------------------|-----------------|-------------|--------------------|--------------------------------------------------------------------------|-------------------------|------------|---------------------------|
| **S9digit (clean snapshot)**  | ~298 of 301     | ~157.5K     | ~$646B             | `fund_universe` UPSERT missed recent N-PORT classifier output            | `BACKFILL_FUND_UNIVERSE` | HIGH       | Confirm no row-level dedupe contention with PR-2 `_upsert_fund_universe` lock; restrict backfill to series whose `fund_strategy_at_filing` is `bond_or_other`, `excluded`, or `passive` (well-supported by classifier today). Source: snapshot-majority of `fund_strategy_at_filing` per series. |
| **S9digit (`active` snapshot)** | 231 rows (~2 series, incl. ARK Innovation S000042977) | 231         | ~$15.1B incl. ARK | Same UPSERT miss, but snapshot label disagrees with fund's true strategy | `INVESTIGATE_FURTHER`   | MEDIUM     | Snapshot says `active` for ARK Innovation — likely correct, but verify before backfill. Conversely Blackstone Alt Multi-Strategy is mis-snapshotted as `bond_or_other`. Run `_apply_fund_strategy` classifier against a fresh sample for these CIKs before promoting. |
| **UNKNOWN_literal**           | 1 (multi-filer) | 3,184       | $10.0B             | Pre-DERA-Session-2 8-CIK loader fallback predates SEC series_id capture  | `REWRITE_NULL_ARM`      | HIGH       | Set `cross.py` default to `'unknown'`; `_fund_type_label` already returns `'unknown'`. Tighten `OverlapAnalysisTab.tsx:194` to `r.is_active === true` (drop NULL rows from active-only filter). Do **not** synthesize a new `UNKNOWN` row in `fund_universe` (collides with legacy `SYN_<CIK>` entries). |
| **SYN_prefix**                | 0               | 0           | 0                  | n/a — PR #199 holds                                                      | `LEAVE_AS_IS`           | HIGH       | None; treat any future `SYN_*` orphan as a regression alarm.                                  |
| **Other**                     | 0               | 0           | 0                  | n/a — empty bucket today                                                 | `LEAVE_AS_IS`           | HIGH       | None.                                                                                          |

### `BACKFILL_FUND_UNIVERSE` derivation source

Per series, derive `fund_strategy` as the **snapshot-majority** of
`fund_strategy_at_filing` across `is_latest = TRUE` rows for that series.
Restrict the backfill set to series whose snapshot-majority is one of
`bond_or_other`, `excluded`, `passive` (the classifier is well-calibrated
for these today, and the cohort overwhelmingly falls there). Defer the
~2 `active`-snapshot S9digit series to manual review under
`INVESTIGATE_FURTHER`. Do **not** execute the backfill in this PR — that is
a separate, write-bearing change that needs its own gate.

### `REWRITE_NULL_ARM` default

Default value for the CASE: `'unknown'`. Mapped output of
`_fund_type_label`: `'unknown'`. Behavioral consequence: orphan rows
continue to render as `mixed` in the badge column (today's behavior), but
the active-only filter must be tightened to `r.is_active === true` (drop
NULL) so unclassified rows no longer leak into the active bucket. Pair
with a CSV export fix (`r.is_active === true ? 'active' : r.is_active === false ? 'passive' : 'unknown'`).

## Recommendations (ranked by row impact)

1. **BACKFILL_FUND_UNIVERSE (S9digit, snapshot-majority bond/excluded/passive)
   — ~157K rows, ~$646B AUM.** Bulk-promote ~298 series from the snapshot.
   This is the single highest-impact action and resolves the active-bucket
   leak structurally for the dominant cohort.
2. **REWRITE_NULL_ARM (`'unknown'` default + frontend filter tightening) —
   3,184 rows, $10.0B AUM.** Removes the active-bucket leak for any
   residual NULL after backfill (UNKNOWN literal + future first-snapshot
   series before universe catches up). Tiny scope, large defensive value.
3. **INVESTIGATE_FURTHER (S9digit `active`-snapshot subset) — 231 rows,
   ~$15.1B AUM.** Manual classifier rerun on the ~2 series whose
   `fund_strategy_at_filing` says `active`; ARK Innovation likely correct,
   Blackstone Alt Multi-Strategy needs reclassification before any
   backfill. Smallest cohort by rows but largest unit-AUM and the only
   path that risks shipping a wrong label.
4. **LEAVE_AS_IS (SYN_prefix, Other) — 0 rows.** Continue treating any
   reappearance as a regression alarm.

---

*Helper script:* [scripts/oneoff/audit_orphan_inventory.py](scripts/oneoff/audit_orphan_inventory.py)
*Raw audit JSON:* regenerate via `python3 scripts/oneoff/audit_orphan_inventory.py`
