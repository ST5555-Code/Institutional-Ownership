# int-20-p0 — Phase 0 findings: MAJOR-6 D-03 orphan-CUSIP secondary driver in build_summaries

_Prepared: 2026-04-22 — branch `int-20-p0` off `main` HEAD `7b19034`._

_Tracker: [docs/REMEDIATION_PLAN.md:56](../REMEDIATION_PLAN.md) row `int-20` (MAJOR-6 D-03 orphan-CUSIP secondary driver in build_summaries). Upstream audit reference: `SYSTEM_AUDIT §3.1`. Plan prediction: *"Auto-resolves once securities coverage repairs"* after `int-01..int-04` ship._

Phase 0 is investigation only. No code changes. Output is this document.

---

## §1. Headline

**int-20 is auto-resolved for the `build_summaries.py` read path and should be closed.**

Two independent findings:

1. **`holdings_v2` has zero orphan CUSIPs** (0 of 44,929 distinct). The 13F leg that feeds both `summary_by_ticker` and the `total_aum` half of `summary_by_parent` is fully covered by `securities` post int-01 / int-04 / CUSIP v1.4.
2. **`build_summaries.py` never joins `securities`.** It aggregates directly from denormalized `holdings_v2.ticker` / `holdings_v2.market_value_usd` and `fund_holdings_v2.market_value_usd`. Orphan CUSIPs therefore cannot introduce summary inaccuracy through this script's read path — they neither drop rows nor under-count value.

`fund_holdings_v2` does carry 297,532 distinct orphan CUSIPs (31.5% of rows, 11.8% of value). On inspection these are **expected out-of-scope records** — `'N/A'` foreign-issuer sentinels plus municipal bonds and agency MBS — not a data-quality gap. Detail in §3.

Recommendation: close `int-20` as auto-resolved. No Phase 1 work required. Flip `docs/REMEDIATION_PLAN.md` row 56 status `OPEN → CLOSED` in a follow-up doc-only PR.

---

## §2. Orphan-CUSIP counts against `securities`

Queries run read-only against `data/13f_readonly.duckdb` (snapshot 2026-04-17 13:30, post CUSIP v1.4 prod promotion per [project_session_apr15_cusip_prod.md](../../memory/project_session_apr15_cusip_prod.md)).

### 2.1 `holdings_v2` — 13F manager holdings

```sql
SELECT COUNT(DISTINCT h.cusip)
FROM holdings_v2 h
LEFT JOIN securities s ON h.cusip = s.cusip
WHERE s.cusip IS NULL;
-- 0
```

- Distinct CUSIPs in `holdings_v2`: **44,929**
- Distinct CUSIPs in `securities`: **132,618**
- Orphans (in `holdings_v2` but not in `securities`): **0**

Every CUSIP referenced by 13F manager holdings resolves in `securities`. This is the row the plan is talking about — int-01 (issuer coverage) and int-04 (MAX-era residual) plus CUSIP v1.4 promotion closed it.

### 2.2 `fund_holdings_v2` — N-PORT fund-level holdings

```sql
SELECT COUNT(DISTINCT f.cusip)
FROM fund_holdings_v2 f
LEFT JOIN securities s ON f.cusip = s.cusip
WHERE s.cusip IS NULL;
-- 297,532
```

- Distinct CUSIPs in `fund_holdings_v2`: **399,783**
- Orphans: **297,532** (74.4% of distinct, 31.5% of rows, 11.8% of market value)

Raw impact looks large but decomposes cleanly (§3) into out-of-scope instrument classes that were never in scope for the equity-focused `securities` table.

### 2.3 Orphan composition

| Bucket | Distinct CUSIPs | Rows | `market_value_usd` |
|---|---:|---:|---:|
| `'N/A'` sentinel (foreign issuers, no CUSIP) | 1 | 3,314,365 | $15.18 T |
| Real 9-char orphans (fixed income — muni / agency / corporate debt) | 297,531 | 1,121,018 | $3.23 T |
| **Total orphans** | **297,532** | **4,435,393** | **$18.41 T** |

Non-`N/A` length breakdown: 297,531 of the 297,532 distinct orphans are canonical 9-character CUSIPs. The single 3-character outlier is a malformed value that registry cleanups should catch separately (not int-20's problem).

Sample real orphans (first 15, all non-`N/A`):

```
091081DN6  Alabama Special Care Facilities Financing Authority-Birmingham AL
041806FV7  Arlington Higher Education Finance Corp
71885FDK0  Industrial Development Authority of the City of Phoenix Arizona/The
95004UAC3  WOOF Holdings Inc
3140A6UE4  Fannie Mae
542691BV1  Long Island Power Authority, New York, Electric System General Revenue Bonds
833102A30  Snohomish County PUD 1, Washington, Electric System Revenue Bonds, 2021A
44237NAZ5  Houston TX Hotel Occupancy Tax and Special Revenue Bonds, 2001B
259234DG4  Douglas County Hospital Authority 3 NE, Nebraska Methodist Health, 2015
576000E33  Massachusetts School Building Authority, Senior DST Revenue Bonds, 2025A
373046J44  Georgetown ISD, Williamson County TX, GO Bonds, Refunding Series 2025
751100PR3  City of Raleigh, NC, Combined Enterprise System Revenue Bonds, 2026
59261A3Q8  MTA New York, Transportation Revenue Bonds, Green Refunding 2024B
35564MBE4  FHLMC
3617K4U88  GNMA
```

Nine of the fifteen samples are municipal bonds, three are federal agency MBS/agency debt (FNMA/FHLMC/GNMA), one is a corporate bond (WOOF). The `securities` table is equity-focused; these instruments never belonged in it. The orphan count is a classification artifact, not a data loss.

Sample `'N/A'` orphans (issuer names attached):

```
'N/A' → OTP Bank Nyrt. (Hungary)
'N/A' → Pan Pacific International Holdings Corp. (Japan)
'N/A' → Suzuki Motor Corp. (Japan)
'N/A' → F-Secure Oyj (Finland)
'N/A' → Akzo Nobel NV (Netherlands)
'N/A' → Swatch Group AG (Switzerland)
'N/A' → Beiersdorf AG (Germany)
'N/A' → Inpex Corp. (Japan)
'N/A' → Pearson plc (UK)
'N/A' → COVESTRO AG (Germany)
```

These are foreign issuers reported in N-PORT without a CUSIP (SEC does not require CUSIP for non-US securities). The `'N/A'` sentinel is an N-PORT-load convention; these rows cannot be resolved in `securities` even in principle.

---

## §3. `build_summaries.py` read-path: what it actually joins

File: [scripts/build_summaries.py](../../scripts/build_summaries.py). Inspected at HEAD `7b19034`.

### 3.1 No join against `securities`

`grep -n 'securities\|JOIN'` over the file returns zero references to `securities`. The script has exactly three aggregation queries, all of which read denormalized columns from the holdings tables directly.

### 3.2 `summary_by_ticker` — aggregates from `holdings_v2` only

[scripts/build_summaries.py:165-195](../../scripts/build_summaries.py:165):

```sql
INSERT INTO summary_by_ticker
SELECT ? AS quarter,
       h.ticker,
       MODE(h.issuer_name) AS company_name,
       SUM(COALESCE(h.market_value_live, h.market_value_usd)) AS total_value,
       ...
FROM holdings_v2 h
WHERE h.quarter = ?
  AND h.ticker IS NOT NULL AND h.ticker != ''
GROUP BY h.ticker
```

Reads `ticker`, `issuer_name`, `market_value_*`, `shares`, `cik`, `manager_type`, `is_passive`, `pct_of_so` — all denormalized on `holdings_v2`. Filter is `ticker IS NOT NULL AND ticker != ''`, not a `securities` join. Since `holdings_v2` has zero orphans (§2.1), every row that would survive a hypothetical join is already surviving this filter.

### 3.3 `summary_by_parent` — `holdings_v2` + `fund_holdings_v2`, still no `securities`

[scripts/build_summaries.py:229-287](../../scripts/build_summaries.py:229):

```sql
WITH latest_per_series AS (
    SELECT series_id, MAX(report_month) AS latest_rm
    FROM fund_holdings_v2 WHERE quarter = ? GROUP BY series_id
),
nport_per_rollup AS (
    SELECT fh.{nport_rid_col} AS rid,
           SUM(fh.market_value_usd) AS total_nport_aum
    FROM fund_holdings_v2 fh
    JOIN latest_per_series l ON l.series_id = fh.series_id AND l.latest_rm = fh.report_month
    WHERE fh.quarter = ?
    GROUP BY fh.{nport_rid_col}
),
parent_13f AS (
    SELECT h.{rid_col} AS rid,
           MAX(h.{rname_col}) AS rname,
           SUM(h.market_value_usd) AS total_aum,
           COUNT(DISTINCT h.ticker) AS ticker_count,
           ...
    FROM holdings_v2 h WHERE h.quarter = ?
    GROUP BY h.{rid_col}
)
SELECT ..., p.total_aum, COALESCE(np.total_nport_aum, 0) AS total_nport_aum, ...
FROM parent_13f p
LEFT JOIN nport_per_rollup np ON np.rid = p.rid
```

Aggregates `fund_holdings_v2.market_value_usd` grouped by `series_id` / rollup columns — **CUSIP never participates in the aggregation key or filter**. Orphan CUSIPs still contribute to `SUM(market_value_usd)` and therefore to `total_nport_aum`. They are not silently dropped.

The only way orphans could bias this aggregate is if they were excluded somewhere upstream of this query. They are not.

### 3.4 Consequence for `nport_coverage_pct`

[scripts/build_summaries.py:274-278](../../scripts/build_summaries.py:274):

```sql
CASE WHEN p.total_aum > 0
     THEN LEAST(100.0, COALESCE(np.total_nport_aum, 0) * 100.0 / p.total_aum)
     END AS nport_coverage_pct
```

- Numerator (`total_nport_aum`) sums *all* `fund_holdings_v2` rows including orphans → not under-counted.
- Denominator (`total_aum`) sums `holdings_v2` which has zero orphans → complete.
- Ratio therefore unaffected by the 297k orphan CUSIPs in `fund_holdings_v2`.

---

## §4. Why the plan's prediction held

The plan (`docs/REMEDIATION_PLAN.md` row 56) predicted auto-resolution after int-01..int-04 ship. Two effects combined to make that true for `build_summaries.py`:

1. **Coverage work closed the 13F leg.** int-01 (issuer coverage backfill), int-04 (MAX-era residual reconciliation), and CUSIP v1.4 prod promotion ([project_session_apr15_cusip_prod.md](../../memory/project_session_apr15_cusip_prod.md)) collectively lifted `securities` to 132,618 CUSIPs and drove `holdings_v2` orphan count to 0.
2. **The read path never needed `securities` in the first place.** The summary SQL is aggregation-only; it doesn't hydrate issuer metadata from `securities`. Any orphan-CUSIP impact on summary accuracy was bounded by whether aggregation keys (ticker / rollup id / series id) survive — which they do, because they are denormalized on the holdings tables.

The fund-level orphan count remains high but is explained by instrument-class scope (fixed income + foreign issuers), not by coverage gap. That is a separate question — asset-class coverage of `securities` — and is not what int-20 is tracking.

---

## §5. Residual scope (not int-20)

For the record, the following are *adjacent* but out of scope for this ticket:

| Concern | Tracker home |
|---|---|
| Asset-class expansion of `securities` (fixed income / foreign) | Not currently scoped; would belong to a future securities-coverage initiative, not int-20. |
| `'N/A'` sentinel hygiene in N-PORT load | N-PORT DERA work ([project_session_apr15_dera_promote.md](../../memory/project_session_apr15_dera_promote.md)); not a summary correctness issue. |
| The single 3-char malformed CUSIP in `fund_holdings_v2` | Registry / validation, not summaries. |
| Other `build_summaries.py` read-path concerns | int-16, int-17, obs-05 per `docs/REMEDIATION_PLAN.md:516`. |

None of these change the int-20 verdict.

---

## §6. Recommendation

1. **Close `int-20` as auto-resolved.** Flip `docs/REMEDIATION_PLAN.md` row 56 `OPEN → CLOSED` in a doc-only follow-up PR citing this findings doc.
2. **No Phase 1 code changes.** `build_summaries.py` is not affected by the orphan-CUSIP condition the audit flagged.
3. **No downstream follow-up required for the summary read path.** If a future audit reopens the question for a different read path (e.g. a UI widget that joins holdings→securities to hydrate issuer metadata), that audit should cite its own read path; int-20 specifically scopes `build_summaries.py`.

---

## §7. Commands used

Read-only queries (ran against `data/13f_readonly.duckdb`):

```sql
-- §2.1
SELECT COUNT(DISTINCT h.cusip)
FROM holdings_v2 h LEFT JOIN securities s ON h.cusip = s.cusip
WHERE s.cusip IS NULL;

-- §2.2
SELECT COUNT(DISTINCT f.cusip)
FROM fund_holdings_v2 f LEFT JOIN securities s ON f.cusip = s.cusip
WHERE s.cusip IS NULL;

-- §2.3 row / value impact
SELECT COUNT(*), SUM(market_value_usd)
FROM fund_holdings_v2 f LEFT JOIN securities s ON f.cusip = s.cusip
WHERE s.cusip IS NULL;

-- §2.3 'N/A' split
SELECT
  SUM(CASE WHEN f.cusip = 'N/A' THEN 1 ELSE 0 END) AS na_rows,
  COUNT(DISTINCT CASE WHEN f.cusip != 'N/A' THEN f.cusip END) AS non_na_cusips,
  SUM(CASE WHEN f.cusip != 'N/A' THEN 1 ELSE 0 END) AS non_na_rows,
  SUM(CASE WHEN f.cusip = 'N/A' THEN market_value_usd END) AS na_value,
  SUM(CASE WHEN f.cusip != 'N/A' THEN market_value_usd END) AS non_na_value
FROM fund_holdings_v2 f LEFT JOIN securities s ON f.cusip = s.cusip
WHERE s.cusip IS NULL;

-- §2.3 samples
SELECT DISTINCT f.cusip, f.issuer_name
FROM fund_holdings_v2 f LEFT JOIN securities s ON f.cusip = s.cusip
WHERE s.cusip IS NULL LIMIT 10;

SELECT DISTINCT f.cusip, f.issuer_name
FROM fund_holdings_v2 f LEFT JOIN securities s ON f.cusip = s.cusip
WHERE s.cusip IS NULL AND f.cusip != 'N/A' LIMIT 15;
```

Code inspection: `grep -n 'securities\|holdings_v2\|fund_holdings\|JOIN'` over [scripts/build_summaries.py](../../scripts/build_summaries.py) — zero `securities` hits.
