# int-07-p0 Phase 0 Findings — BLOCK-TICKER-BACKFILL Phase 2 benchmark_weights gate

**Item:** int-07 — three-part validation gate on `benchmark_weights` after the ticker-backfill retroactive sweep (int-05) and forward-looking hooks (int-06).
**Scope:** Phase 0. Read-only investigation. No code or data changes.
**Recommendation:** **CLOSE AS PASS.** All three gates pass against prod `data/13f.duckdb`. int-08 (conditional sector refetch) **not needed**. int-09 (DENORM-RETIREMENT) is unblocked.

---

## 1. Gate definition — source

Source: [docs/findings/2026-04-18-block-ticker-backfill.md §8](2026-04-18-block-ticker-backfill.md) — *Phase 2 gate — post-Phase 1 validation*.

Three-part gate on the `benchmark_weights` table (written by [scripts/build_benchmark_weights.py](../../scripts/build_benchmark_weights.py) from Vanguard Total Stock Market series `S000002848`):

| # | Gate | Criterion | Blocking |
|---|---|---|---|
| 1 | Row count | Exactly 44 `US_MKT` rows — 11 GICS sectors × 4 quarters (2025-03-31, 2025-06-30, 2025-09-30, 2025-12-31) | Yes |
| 2 | Weight sum | For each of the 4 `as_of_date` groups, `SUM(weight_pct) ∈ [99.0, 100.01]` | Yes |
| 3 | Drift | Per `(sector, as_of_date)` drift vs `data/backups/13f_backup_20260417_172152/benchmark_weights.parquet` ≤ ±2.0 pp | **Informational only** (§8: "log but do not block the gate") |

§8 escalation ladder (not triggered here, recorded for completeness):
- If (1) or (2) fails with only Phase 1a applied → call `refetch_missing_sectors.py` on the 227 tickers from §4 and re-run the builder. *(This is int-08.)*
- If still failing → Phase 2b: OpenFIGI retry on the 165 needs-external CUSIPs for `S000002848` 2025-09 only.

---

## 2. Preconditions

- **int-05** (retroactive Pass C sweep): closed as NO-OP. Sweep already run against prod; the `is_priceable=TRUE` join ceiling caps `fund_holdings_v2.ticker` at 17,412 distinct securities. See [int-05-p0-findings.md](int-05-p0-findings.md).
- **int-06** (forward-looking hooks): closed as NO-OP. Subprocess hooks present in both [build_cusip.py:442-453](../../scripts/build_cusip.py:442) and [normalize_securities.py:143-154](../../scripts/normalize_securities.py:143) on `main`. See [int-06-p0-findings.md](int-06-p0-findings.md).
- Prod `benchmark_weights` reflects the post-sweep state of `fund_holdings_v2`.

---

## 3. Gate 1 — Row count

Query:

```sql
SELECT COUNT(*) FROM benchmark_weights WHERE index_name='US_MKT';
```

Result:

| Metric | Value | Expected |
|---|---:|---:|
| `US_MKT` rows | **44** | 44 |

Per-quarter breakdown:

| `as_of_date` | Sector rows |
|---|---:|
| 2025-03-31 | 11 |
| 2025-06-30 | 11 |
| 2025-09-30 | 11 |
| 2025-12-31 | 11 |

**Verdict: PASS.**

---

## 4. Gate 2 — Weight sum per quarter

Query:

```sql
SELECT as_of_date, COUNT(*) AS n_sectors, ROUND(SUM(weight_pct), 2) AS sum_wt
  FROM benchmark_weights WHERE index_name='US_MKT'
 GROUP BY as_of_date ORDER BY as_of_date;
```

Result:

| `as_of_date` | `SUM(weight_pct)` | In [99.0, 100.01]? |
|---|---:|---|
| 2025-03-31 | 100.00% | PASS |
| 2025-06-30 | 100.01% | PASS |
| 2025-09-30 | 100.01% | PASS |
| 2025-12-31 | 99.99% | PASS |

All four quarters within the gate window. The 0.01% residual on two quarters is standard rounding noise from `ROUND(val/total*100, 2)` in [build_benchmark_weights.py:135](../../scripts/build_benchmark_weights.py:135).

**Verdict: PASS.**

---

## 5. Gate 3 — Drift vs baseline parquet (informational)

Query (merge prod `benchmark_weights` against `data/backups/13f_backup_20260417_172152/benchmark_weights.parquet`, compute `current - baseline` per `(sector, as_of_date)`):

| Summary | Value |
|---|---:|
| Baseline rows | 44 |
| Current rows | 44 |
| Row alignment | 44/44 — all keys match |
| Max `abs(drift)` | **1.66 pp** |
| Rows exceeding ±2.0 pp threshold | **0** |

Top drift rows (all within threshold):

| `as_of_date` | sector | baseline | current | drift |
|---|---|---:|---:|---:|
| 2025-12-31 | Information Technology | 33.53 | 35.19 | +1.66 |
| 2025-12-31 | Financials | 13.34 | 11.99 | −1.35 |
| 2025-12-31 | Communication Services | 9.52 | 10.35 | +0.83 |
| 2025-06-30 | Financials | 14.57 | 13.97 | −0.60 |
| 2025-09-30 | Financials | 13.99 | 13.47 | −0.52 |
| 2025-03-31 | Financials | 13.52 | 13.02 | −0.50 |
| 2025-06-30 | Communication Services | 8.32 | 8.80 | +0.48 |

Observations (not blocking):
- The largest drift concentrates in 2025-12-31 Information Technology (+1.66 pp) and Financials (−1.35 pp). Consistent with the post-sweep ticker recovery re-classifying previously-Unknown holdings into their true GICS buckets.
- Financials drifts negative across all four quarters (−0.50 to −1.35 pp) while Info Tech and Communication Services drift positive — consistent with the known REIT-reclassification rule in [build_benchmark_weights.py:49-54](../../scripts/build_benchmark_weights.py:49) and with Pass-C ticker fills landing mostly in tech/communications names.
- All 44 rows within the ±2.0 pp informational threshold. No quarter needs Phase 2b escalation.

**Verdict: PASS (informational).**

---

## 6. Verdict & downstream impact

| Gate | Result |
|---|---|
| Gate 1 — Row count (44 exact) | **PASS** |
| Gate 2 — Weight sum per quarter ∈ [99.0, 100.01] | **PASS** |
| Gate 3 — Drift ≤ ±2.0 pp (informational) | **PASS** |

**int-07 closes as PASS.** All three gates satisfied against prod `data/13f.duckdb` (HEAD = `c7f5605`, queries dated 2026-04-22).

Downstream:
- **int-08 skipped.** int-08 is the CONDITIONAL sector-refetch item that only fires if Gates 1 or 2 fail with Phase 1a alone. Gates 1 + 2 both passed → the 227 `market_data.sector IS NULL` tickers from §4 of the findings doc do not need refetching to close the Phase 2 gate. (The broader table-wide `market_data.sector` NULL population remains BLOCK-SECTOR-COVERAGE-BACKGROUND scope, unchanged.)
- **int-09 unblocks.** BLOCK-DENORM-RETIREMENT (join-at-read-time rewrite of the `fund_holdings_v2.ticker` denormalization) was gated on int-07 closing. int-09 is now free to proceed.
- **int-10** (BLOCK-3 Phase 2 dry-run re-run): unchanged — still required before BLOCK-3 Phase 4 resumes. The 2025Q4-missing-rows stop-condition from `logs/reports/block3_dryrun_20260417_2230.md` is invalidated by the BLOCK-TICKER-BACKFILL landing, per §9 of the findings doc; int-10 re-runs Phase 2 against the repaired state.

---

## 7. Queries — reproducibility

All queries executed against `data/13f.duckdb` in read-only mode on 2026-04-22.

```python
import duckdb
con = duckdb.connect('data/13f.duckdb', read_only=True)

# Gate 1
con.execute("SELECT COUNT(*) FROM benchmark_weights WHERE index_name='US_MKT'").fetchone()

# Gate 2
con.execute("""
  SELECT as_of_date, COUNT(*) AS n_sectors, ROUND(SUM(weight_pct), 2) AS sum_wt
    FROM benchmark_weights WHERE index_name='US_MKT'
   GROUP BY as_of_date ORDER BY as_of_date
""").fetchall()

# Gate 3 (drift)
con.execute("""
  SELECT gics_sector, as_of_date, weight_pct FROM benchmark_weights
   WHERE index_name='US_MKT' ORDER BY as_of_date, gics_sector
""").fetchall()

duckdb.connect(':memory:').execute("""
  SELECT gics_sector, as_of_date, weight_pct
    FROM read_parquet('data/backups/13f_backup_20260417_172152/benchmark_weights.parquet')
   WHERE index_name='US_MKT' ORDER BY as_of_date, gics_sector
""").fetchall()
```

No writes. No mutations. Prod state unchanged.
