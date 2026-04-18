# BLOCK-TICKER-BACKFILL — Findings & Fix Plan

_Branch: `block-ticker-backfill` off main (`5b501fc`)._
_Findings date: 2026-04-18._

Formalizes the Phase 0 investigation conducted during BLOCK-TICKER-BACKFILL
design review (2026-04-18). No new investigation; this doc is the frozen record.

---

## 1. Writers of `fund_holdings_v2.ticker`

Complete set, verified by `rg "UPDATE fund_holdings_v2|INSERT INTO fund_holdings_v2"`:

| Writer | File:Line | Semantics |
|---|---|---|
| Promote-time insert | [`scripts/promote_nport.py:328`](../scripts/promote_nport.py) | `INSERT INTO fund_holdings_v2 ({_STAGED_COLS})` — `ticker` comes in from the staged N-PORT XML tuple (`<ticker value="…" />`). **Frequently NULL** because many N-PORT filings omit or empty the tag. |
| Enrichment Pass C (bulk populate from `securities`) | [`scripts/enrich_holdings.py:299-321`](../scripts/enrich_holdings.py) | `UPDATE fund_holdings_v2 SET ticker = s.ticker FROM securities s WHERE s.cusip = fh.cusip AND s.ticker IS NOT NULL` — with optional `AND fh.quarter = ?` scope. **Populate, not refresh** (only NULL→ticker transitions; see docstring at [`:256-262`](../scripts/enrich_holdings.py)). |

**`fetch_market.py` is NOT a writer.** It only reads `fund_holdings_v2.ticker` to compute the `market_data` coverage universe (`scripts/fetch_market.py:532`, `:839-841`, `:847-849`, `:985`, `:1008`). Previously mis-listed as a suspect in the BLOCK-TICKER-BACKFILL design draft.

Other write surfaces touching v2 that **do NOT touch `ticker`**:
- [`scripts/build_fund_classes.py:150-155`](../scripts/build_fund_classes.py) — sets `lei` only.
- [`scripts/enrich_fund_holdings_v2.py:330`](../scripts/enrich_fund_holdings_v2.py) — sets `entity_id`, `rollup_entity_id`, `dm_*` only (BLOCK-2 backfill).

---

## 2. NULL-ticker gap quantification

Query (read-only, run against prod 2026-04-18):

```sql
SELECT fh.report_month AS month,
       COUNT(*) FILTER (WHERE fh.ticker IS NULL OR fh.ticker = '') AS null_ticker_rows,
       COUNT(*) FILTER (WHERE (fh.ticker IS NULL OR fh.ticker = '')
                         AND s.ticker IS NOT NULL AND s.ticker <> '')
                                                                 AS recoverable_via_db_only,
       COUNT(*) FILTER (WHERE (fh.ticker IS NULL OR fh.ticker = '')
                         AND (s.ticker IS NULL OR s.ticker = ''))
                                                                 AS needs_external_fetch,
       COUNT(*) FILTER (WHERE (fh.ticker IS NULL OR fh.ticker = '')
                         AND s.cusip IS NULL)                    AS cusip_not_in_securities,
       COUNT(*)                                                  AS total_rows
  FROM fund_holdings_v2 fh
  LEFT JOIN securities s USING (cusip)
 GROUP BY 1 ORDER BY 1;
```

Full per-month breakdown (all report_months with non-trivial row counts; earlier months with <100 rows are sentinel tails and elided for brevity):

| report_month | total rows | null_ticker_rows | recoverable_via_db_only | needs_external_fetch | cusip_not_in_securities | current cov% |
|---|---:|---:|---:|---:|---:|---:|
| 2024-10 | 3,701 | 2,659 | 0 | 2,659 | 334 | 28.2% |
| 2024-11 | 240,635 | 93,091 | 51 | 93,040 | 18,668 | 61.3% |
| 2024-12 | 848,259 | 273,120 | 1 | 273,119 | 62,189 | 67.8% |
| 2025-01 | 519,460 | 276,550 | 0 | 276,550 | 91,474 | 46.8% |
| 2025-02 | 240,252 | 92,494 | 50 | 92,444 | 18,759 | 61.5% |
| 2025-03 | 843,105 | 268,771 | 2 | 268,769 | 60,978 | 68.1% |
| 2025-04 | 512,911 | 272,659 | 0 | 272,659 | 89,873 | 46.8% |
| 2025-05 | 239,110 | 92,171 | 52 | 92,119 | 18,201 | 61.5% |
| 2025-06 | 963,102 | 392,425 | 288 | 392,137 | 184,908 | 59.3% |
| 2025-07 | 510,807 | 275,186 | 918 | 274,268 | 92,986 | 46.1% |
| 2025-08 | 604,021 | 479,920 | **40,413** | 439,507 | 283,963 | 20.5% |
| 2025-09 | 1,419,322 | 975,049 | **176,665** | 798,384 | 265,517 | 31.3% |
| 2025-10 | 1,306,425 | 1,222,422 | **260,935** | 961,487 | 405,451 | 6.4% |
| 2025-11 | 2,001,782 | 1,927,404 | **178,909** | 1,748,495 | 1,274,491 | 3.7% |
| 2025-12 | 2,514,494 | 2,274,572 | **442,399** | 1,832,173 | 902,921 | 9.5% |
| 2026-01 | 1,321,332 | 1,234,840 | **257,337** | 977,503 | 439,116 | 6.5% |
| 2026-02 | 1,113 | 552 | 322 | 230 | 209 | 50.4% |
| 2026-03 | 64 | 63 | 0 | 63 | 63 | 1.6% |

**Aggregate reality check:**
- Total NULL-ticker rows (non-sentinel months): ~10.5M
- Table-wide DB-only recoverable: ~1.4M (13.3%)
- Table-wide needs-external-fetch: ~6.8M needs_ext, of which ~4.2M are `cusip_not_in_securities`

This block closes only the DB-only portion. Out-of-scope portions are deferred:
- `cusip_not_in_securities` (~4.2M rows) → BLOCK-CUSIP-COVERAGE
- `securities.ticker IS NULL` (~2.6M rows) → BLOCK-CUSIP-COVERAGE (same upstream)
- `market_data.sector IS NULL` side-gap → BLOCK-SECTOR-COVERAGE-BACKGROUND (parallel)

---

## 3. Regression-path specifics (BLOCK-3 Phase 2 stop-condition)

The BLOCK-3 Phase 2 dry-run surfaced missing 2025Q4 rows in `benchmark_weights`
because `build_benchmark_weights.py` picks `MAX(report_month) WHERE quarter='2025Q4'`
for the benchmark series (S000002848, Vanguard Total Stock Market). That latest
report_month is `2025-09`.

Scoped ticker-gap for the regression driver:

| scope | rows | NULL | db_only_recoverable | needs_external |
|---|---:|---:|---:|---:|
| **S000002848, report_month 2025-09** | **3,560** | **3,556** | **3,391 (95.4%)** | **165 (4.6%)** |
| Full 2025Q4, all series (latest_rm) | 2,533,450 | 1,729,512 | 217,996 (12.6%) | 1,511,516 (87.4%) |

The benchmark builder's specific regression is **95.4% closable by DB-only Pass C**.
The 165 needs-external CUSIPs are the Phase 2b escalation target if the gate fails
after DB-only + sector refetch.

---

## 4. `market_data.sector` gap on the regression path

Post-Pass-C projection for series S000002848 at report_month 2025-09:

| outcome bucket | rows |
|---|---:|
| `db_only_recoverable` (gains a ticker from `securities`) | 3,391 |
| of which GICS-mappable via `market_data.sector` → `YF_TO_GICS` | **3,139** |
| of which `market_data` row exists but `sector IS NULL` | **227** |
| of which `ticker` is not present in `market_data` at all | **58** |
| `needs_external_fetch` (CUSIP not resolvable against securities) | 165 |

Phase 2 should call `refetch_missing_sectors.py` on the **~227 tickers** whose
`market_data` rows exist with `sector IS NULL`. That closes the secondary gap
for this block's scope; the table-wide `market_data.sector` NULL rate (35.3% of
10,064 rows) is deferred to BLOCK-SECTOR-COVERAGE-BACKGROUND.

The 58 tickers not in `market_data` are not in scope for this block — adding
them is a `fetch_market.py` extension that would expand scope into the broader
coverage workstream.

---

## 5. Structural root cause

**Pass C is manually invoked.** No hook fires when upstream learns a new
CUSIP→ticker mapping. The chain is:

```
OpenFIGI API
  → cusip_classifications.ticker  (run_openfigi_retry.py :107-113)
    → securities.ticker            (build_cusip.py SECURITIES_UPDATE_SQL :307-322)
      → fund_holdings_v2.ticker    (enrich_holdings.py Pass C :299-321)  ← NO AUTO-TRIGGER
```

The last hop is operational: someone has to run `enrich_holdings.py --fund-holdings`
after `build_cusip.py` updates `securities`. In practice this happens
per-quarter at best, so historical rows (2025-10 through 2026-01 especially)
never get re-stamped when later OpenFIGI batches learn the CUSIP→ticker mapping.

This is the same structural pattern as BLOCK-2 for `entity_id`: run-scoped
enrichment that never revisits the existing table. The fix is the same shape:
one retroactive full-table sweep + one forward-looking hook.

---

## 6. Fix shape

### Phase 1a — Retroactive invocation (zero code)

`enrich_holdings.py` already has a `--staging` flag, a `--fund-holdings` flag,
and full-table scope when `--quarter` is omitted. The retroactive fix is:

```sh
python3 scripts/enrich_holdings.py --fund-holdings --staging
```

No new code. One Pass-C sweep across all ~14M `fund_holdings_v2` rows.
Idempotent — only NULL→ticker transitions, so re-running is safe.

Expected outcome (from §2 table, staging seeded from prod):
- Rows updated: ~1.4M (the full `db_only_recoverable` column sum)
- Residual NULL: ~6.8M (the `needs_external_fetch` column sum) — unchanged; out of scope.

### Phase 1b — Forward-looking hook (small code)

Add a subprocess call at the end of [`scripts/build_cusip.py`](../scripts/build_cusip.py)'s
main flow, after `securities` write completes. Subprocess pattern (not inline
import) is resilient to `build_cusip.py` REWRITE refactors: if the script is
split or renamed later, the child command `python3 scripts/enrich_holdings.py
--fund-holdings` is version-independent.

Shape (~10-20 LOC):

```python
import subprocess
try:
    subprocess.run(
        [sys.executable, "scripts/enrich_holdings.py", "--fund-holdings"],
        cwd=BASE_DIR, check=False, timeout=1800,
    )
except Exception as e:
    print(f"  [warn] post-build ticker backfill hook failed: {e}", flush=True)
```

Wrapped in try/except so an enrichment failure does not propagate into
`build_cusip.py`'s exit status. The hook fires in staging or prod depending on
which DB `build_cusip.py` writes to — `enrich_holdings.py` respects the same
staging-mode conventions.

---

## 7. Out of scope — strict

- Stale-ticker refresh (ticker_A → ticker_B). Pass C is populate-only; this block
  preserves that semantic.
- `cusip_not_in_securities` coverage (~4.2M rows across all months) → separate
  block (BLOCK-CUSIP-COVERAGE).
- `securities.ticker IS NULL` coverage (~2.6M rows) → same upstream as above.
- Table-wide `market_data.sector` refetch → BLOCK-SECTOR-COVERAGE-BACKGROUND
  (parallel workstream).
- Join-at-read-time rewrite → BLOCK-DENORM-RETIREMENT (later).
- `entity_id`, `lei`, or any other denormalized column.
- `DROP TABLE` anywhere.

---

## 8. Phase 2 gate — post-Phase 1 validation

Three-part gate on `build_benchmark_weights.py --staging` output:

1. **Row count**: exactly 44 `US_MKT` rows — 11 GICS sectors × 4 quarters
   (2025-03-31, 2025-06-30, 2025-09-30, 2025-12-31).
2. **Weight sum**: for each of the 4 `as_of_date` groups, `SUM(weight_pct) ∈ [99.0, 100.01]`.
3. **Drift**: per-(sector, as_of_date) `weight_pct` drift vs
   `data/backups/13f_backup_20260417_172152/benchmark_weights.parquet`
   ≤ ±2.0 pp (informational — log but do not block the gate).

If (1) or (2) fails with only Phase 1a applied → call
`refetch_missing_sectors.py` on the 227 tickers from §4 and re-run the builder.
If still failing → Phase 2b escalation (OpenFIGI retry on the 165 needs-external
CUSIPs for S000002848 2025-09 only; scope strictly bounded by §3).

---

## 9. Unblocking BLOCK-3 (post-Phase 4)

After BLOCK-TICKER-BACKFILL lands in prod, the BLOCK-3 Phase 2 dry-run report at
`logs/reports/block3_dryrun_20260417_2230.md` becomes invalid: its 2025Q4
missing-rows stop-condition will no longer hold. BLOCK-3 Phase 4 cannot proceed
until a fresh Phase 2 dry-run re-runs against the repaired `fund_holdings_v2`
state. This block's Phase 4 stop message records that dependency explicitly.
