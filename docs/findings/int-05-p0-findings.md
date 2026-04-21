# int-05-p0 Phase 0 Findings — BLOCK-TICKER-BACKFILL retroactive Pass C sweep

**Item:** int-05 — retroactive `enrich_holdings.py` sweep across all historical quarters after int-01 (securities fix) and int-04 (securities fix) shipped.
**Scope:** Phase 0. Read-only investigation. No code or data changes.
**Recommendation:** **CLOSE AS NO-OP.** The sweep has already been run; no additional rows can be recovered under the current securities universe.

---

## 1. Pass C / enrichment invocation documentation

Source: [scripts/enrich_holdings.py](scripts/enrich_holdings.py).

### Naming correction

The int-05 task description says "Pass C backfills ticker on **holdings_v2 and fund_holdings_v2**". That is imprecise. Inside the script the passes are:

| Pass | Target table | Column(s) | Gate | Apply fn |
|---|---|---|---|---|
| A | `holdings_v2` | ticker / sti / mvl / pof (NULL cleanup) | `cusip NOT IN cusip_classifications` | [_pass_a_apply:231](scripts/enrich_holdings.py:231) |
| B | `holdings_v2` | ticker / sti / mvl / pct_of_so / pct_of_so_source | `cusip_classifications.is_equity = TRUE` | [_pass_b_apply:345](scripts/enrich_holdings.py:345) |
| C | `fund_holdings_v2` | ticker only | `securities.is_priceable = TRUE` | [_pass_c_apply:441](scripts/enrich_holdings.py:441) |

So "retroactive Pass C sweep" in the int-05 description covers **both** the holdings_v2 ticker backfill (actually Pass B) and the fund_holdings_v2 ticker backfill (actually Pass C). This finding covers both.

### CLI surface

```
scripts/enrich_holdings.py [--staging] [--dry-run] [--quarter YYYYQN] [--fund-holdings]
```

| Flag | Effect |
|---|---|
| `--staging` | Route writes to `data/13f_staging.duckdb` (via `db.set_staging_mode(True)`). Default is prod. |
| `--dry-run` | Open read-only; emit projections only; no writes. |
| `--quarter YYYYQN` | Scope Pass A/B/C to one quarter. Default is ALL quarters (full refresh). |
| `--fund-holdings` | Also run Pass C against `fund_holdings_v2.ticker`. Default is OFF. |

### Writes performed when all passes run (no `--quarter`, `--fund-holdings`)

- Pass A: `UPDATE holdings_v2 SET ticker/sti/mvl/pof/pof_source = NULL WHERE cusip NOT IN cusip_classifications`.
- Pass B: `UPDATE holdings_v2 SET ticker, security_type_inferred, market_value_live, pct_of_so, pct_of_so_source` using ASOF join against `cusip_classifications` + `securities` + `market_data` + `shares_outstanding_history`.
- Pass C: `UPDATE fund_holdings_v2 SET ticker = s.ticker FROM securities s WHERE s.cusip = fh.cusip AND s.ticker IS NOT NULL AND s.is_priceable = TRUE`. **Populate-only — does NOT clear stale tickers** ([_pass_c_apply:441](scripts/enrich_holdings.py:441) comment at line 402).
- Final: `db.record_freshness('holdings_v2_enrichment', …)` and `db.record_freshness('holdings_v2', …)`.

### Idempotency

- Pass A: idempotent (UPDATE to NULL).
- Pass B: idempotent (deterministic UPDATE over the same CTE).
- Pass C: idempotent and **non-destructive** — populates only where `s.is_priceable = TRUE` and `s.ticker IS NOT NULL`. Does not null or overwrite rows outside that match. Safe to re-run.

---

## 2. Current data state (prod `data/13f.duckdb`, 2026-04-21)

### 2.1 `holdings_v2` ticker coverage

| Metric | Rows |
|---|---|
| Total | 12,270,984 |
| `ticker IS NOT NULL` | 10,394,757 (84.71%) |
| `ticker IS NULL` | 1,876,227 (15.29%) |

Per-quarter NULL ticker distribution (the quarter column is stable across 2025):

| Quarter | Rows | NULL ticker | NULL % |
|---|---|---|---|
| 2025Q1 | 2,993,162 | 463,464 | 15.48% |
| 2025Q2 | 3,047,474 | 470,462 | 15.44% |
| 2025Q3 | 3,024,698 | 459,221 | 15.18% |
| 2025Q4 | 3,205,650 | 483,080 | 15.07% |

### 2.2 `fund_holdings_v2` ticker coverage

| Metric | Rows |
|---|---|
| Total | 14,090,397 |
| `ticker IS NOT NULL` | 5,154,223 (36.58%) |
| `ticker IS NULL` | 8,936,174 (63.42%) |

Per-quarter NULL ticker distribution (largest quarters only; pre-2025 are tiny slivers and dominated by NULL):

| Quarter | Rows | NULL ticker | NULL % |
|---|---|---|---|
| 2025Q1 | 1,092,595 | 368,751 | 33.75% |
| 2025Q2 | 1,602,817 | 637,591 | 39.78% |
| 2025Q3 | 1,715,123 | 756,777 | 44.12% |
| 2025Q4 | 2,535,241 | 1,535,950 | 60.58% |
| 2026Q1 | 5,821,610 | 4,632,897 | 79.58% |
| 2026Q2 | 1,322,509 | 1,004,068 | 75.92% |

### 2.3 `securities` universe (the populate ceiling)

| Metric | Rows |
|---|---|
| Total | 430,149 |
| `ticker IS NOT NULL` | 21,142 |
| `is_priceable = TRUE` | 40,878 |
| `ticker IS NOT NULL AND is_priceable = TRUE` | **17,412** |

This is the effective lookup universe for Pass C. Only 17,412 securities can contribute a ticker to `fund_holdings_v2` under the current gate.

---

## 3. Projected recovery if the sweep is re-run NOW

Projections run against prod read-only, replicating the exact `_pass_b_project` / `_pass_c_project` logic.

### 3.1 Pass B projection (`holdings_v2`)

| Metric | Rows |
|---|---|
| Rows in scope (equity-classifiable cusip) | 12,270,984 |
| `will_populate` (NULL → ticker) | **0** |
| `will_change` (ticker → different ticker) | **0** |

Diagnosis of the 1,876,227 remaining NULLs:

| Bucket | Rows |
|---|---|
| No `cusip_classifications` row | 0 |
| `is_equity = FALSE` (legitimately not backfillable) | 1,607,575 |
| `is_equity = TRUE` but `securities.ticker IS NULL` (universe gap) | 268,652 |
| `is_equity = TRUE` AND `securities.ticker IS NOT NULL` (recoverable) | **0** |

### 3.2 Pass C projection (`fund_holdings_v2`)

| Metric | Rows |
|---|---|
| Rows in scope | 14,090,397 |
| `will_populate` (NULL → ticker) | **0** |
| `will_change` (ticker → different ticker) | **0** |

Diagnosis of the 8,936,174 remaining NULLs:

| Bucket | Rows |
|---|---|
| No matching `securities` row | 3,131,576 |
| `securities.ticker IS NULL` | 5,658,313 |
| `securities.is_priceable = FALSE` (gate-excluded) | 146,285 |
| `is_priceable = TRUE` AND `ticker IS NOT NULL` (recoverable) | **0** |

### 3.3 Why recovery is 0

Evidence that the sweep was already run since the upstream fixes shipped:

- `data_freshness('holdings_v2_enrichment')` last stamped **2026-04-19 13:32:08**, row_count = 10,394,757 (matches current populated count exactly).
- `data_freshness('fund_holdings_v2_enrichment')` last stamped **2026-04-17 20:46:18**, row_count = 6,205,976.
- Latest `enrich_holdings.py` log (`logs/enrich_holdings_20260421_141707.log`, staging) reports `ticker_changes = 0` across all passes.
- CUSIP v1.4 prod promotion happened **2026-04-15** (commit 8a41c48). The 2026-04-19 enrichment run captured the full post-promotion securities universe.

The "~1.4M row recovery" in the int-05 description no longer exists because a full-refresh enrichment already ran after int-01 / int-04 / CUSIP v1.4 closed. The remaining NULLs are legitimate universe gaps (non-equity classifications, securities with no ticker, non-priceable securities).

---

## 4. Decision — code changes vs. data-only op

**Neither is needed.** int-05 as scoped ("retroactive Pass C sweep") has already been executed by routine post-ingestion enrichment. No outstanding work.

### Optional confirmation command (Serge to run)

```
python3 scripts/enrich_holdings.py --dry-run --fund-holdings
```

Expected output: `ticker_changes = 0` on Pass B, `will_populate = 0` and `will_change = 0` on Pass C. Runtime ~15–30s (read-only projection only).

### If int-05 is RE-SCOPED to "recover the remaining 1.88M + 8.94M NULLs"

Those are **universe** problems, not sweep problems. Possible follow-ups (out of scope for int-05 Phase 0):

| Remaining NULL bucket | Potential recovery path | New workstream |
|---|---|---|
| holdings_v2 268,652 equity cusips with no `securities.ticker` | Enrich `securities.ticker` via OpenFIGI retry sweep (already queued — see int-05 related items + CUSIP v1.4 Session 2 memory) | Separate: OpenFIGI ticker coverage |
| fund_holdings_v2 3,131,576 cusips with no `securities` row | Extend securities ingestion to N-PORT-only cusips | Separate: securities universe expansion |
| fund_holdings_v2 5,658,313 securities rows with NULL ticker | OpenFIGI / CUSIP Session 2 (same as above) | Same as above |
| fund_holdings_v2 146,285 `is_priceable = FALSE` rows | Re-evaluate `is_priceable` gate tuning — tradeoff noted in [enrich_holdings.py:395](scripts/enrich_holdings.py:395) comment ("without this gate, Pass C would stamp ~517K functionally-wrong tickers") | Separate: Pass C gate policy |

Each of these would be a new workstream with its own risk/benefit analysis. None are what int-05 originally scoped (re-running existing code); they all require new logic or upstream data work.

---

## 5. Recommended execution plan

**Close int-05 as NO-OP** with the evidence above. Record the closure in ROADMAP.md (move to COMPLETED with date 2026-04-21 and a one-line note citing data_freshness stamps).

No staging sweep required. No prod write required.

If Serge wants evidence-in-hand before closing, run the optional dry-run (§4). Expected runtime ~30s; zero writes. A follow-up Phase 1 would only make sense if the dry-run unexpectedly shows > 0 populates (which would indicate data_freshness is stale).

---

## 6. Risk notes

- **Risk: securities.ticker regresses.** If a future securities-table rebuild drops tickers, Pass B / Pass C could need to re-run, but they are idempotent and non-destructive on the populate path. Running as part of post-ingestion is the standard guard. Not an int-05 concern.
- **Risk: stale tickers in `fund_holdings_v2`.** Pass C does not null-sweep stale rows. If a CUSIP's ticker changes in `securities` (merger, ticker change), Pass C will overwrite the new value over the old on any subsequent run — which is correct behavior. Not a staleness risk in the sense that would warrant a sweep. The code-comment caveat "does NOT clear stale tickers" refers specifically to the case where a cusip's `securities.ticker` becomes NULL — Pass C would leave the old stale value in place. Count of rows in that state is unknown; out of scope here.
- **Risk: 146K `is_priceable = FALSE` rows blocked by gate.** Intentional per [_pass_c_apply:395](scripts/enrich_holdings.py:395) comment. Re-evaluating the gate is a separate policy discussion; not a sweep issue.
- **No write risk from closing this item** — zero rows would change.

---

## Appendix — verification queries

```sql
-- Prod baseline (matches this report)
SELECT COUNT(*) total,
       COUNT(*) FILTER (WHERE ticker IS NULL) null_ticker
FROM holdings_v2;

SELECT COUNT(*) total,
       COUNT(*) FILTER (WHERE ticker IS NULL) null_ticker
FROM fund_holdings_v2;

SELECT COUNT(*) total,
       COUNT(*) FILTER (WHERE ticker IS NOT NULL) with_ticker,
       COUNT(*) FILTER (WHERE is_priceable = TRUE) priceable,
       COUNT(*) FILTER (WHERE ticker IS NOT NULL AND is_priceable = TRUE) priceable_with_ticker
FROM securities;

-- Recovery candidates (both should be 0 per this report)
SELECT COUNT(*) FROM fund_holdings_v2 fh
LEFT JOIN securities s ON s.cusip = fh.cusip AND s.is_priceable = TRUE
WHERE fh.ticker IS NULL AND s.ticker IS NOT NULL;

SELECT COUNT(*) FROM holdings_v2 h
LEFT JOIN cusip_classifications c ON c.cusip = h.cusip
LEFT JOIN securities s ON s.cusip = h.cusip
WHERE h.ticker IS NULL AND c.is_equity = TRUE AND s.ticker IS NOT NULL;

-- Last enrichment stamp
SELECT * FROM data_freshness
WHERE table_name IN ('holdings_v2_enrichment', 'fund_holdings_v2_enrichment')
ORDER BY last_computed_at DESC;
```
