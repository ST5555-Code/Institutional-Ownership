# int-15 — INF31 `market_data` writer `fetch_date` discipline — Phase 0 findings

**Date:** 2026-04-22
**Branch:** `int-15-p0`
**Base:** `main` @ `7b19034`
**Scope:** Read-only survey of every writer to `market_data`. Confirms the standing hazard flagged in `docs/findings/2026-04-19-block-market-data-writer-audit.md` §6 is unchanged on `main` and extends the enumeration to cover all non-`sector` writers. No code changes.

---

## 1. TL;DR

- **One standing SUSPECT writer** remains: [scripts/refetch_missing_sectors.py:253-257](../../scripts/refetch_missing_sectors.py#L253-L257). It writes `sector` + `industry` with no `fetch_date` (or `metadata_date` / `sec_date`) bump. A ticker that was price-stale before the write is still price-stale after — so `discover_market` re-picks it on every subsequent run.
- **Seven other writer code paths** across five scripts all stamp `fetch_date` (or the correct bucket date) on every write that mutates ownership-relevant columns. No regressions since the 2026-04-19 audit.
- **`last_write_ts` column does not exist.** It is referenced only in the prior audit's recommendation (Option 1, §6) as a proposal. No schema, no writer, no reader uses it today.
- **Convention to adopt (Phase 1 candidate):** every `UPDATE market_data` that mutates an ownership/attribute column must bump `fetch_date` on the same operation, unless the column belongs to a bucket with a dedicated date (`sec_date` for SEC-owned cols, `metadata_date` for Yahoo metadata). `recompute_market_cap` is the one correct exception — it's a pure derived-value recompute, not a refresh.
- **One-line fix candidate** for `refetch_missing_sectors.py:253-257`: add `fetch_date = CURRENT_DATE, metadata_date = CURRENT_DATE` to the SET clause. Scope for Phase 1, not this document.

---

## 2. How `fetch_date` is consumed (why discipline matters)

### 2.1 `discover_market` staleness logic — [scripts/pipeline/discover.py:367-527](../../scripts/pipeline/discover.py#L367-L527)

Freshness thresholds ([discover.py:344-348](../../scripts/pipeline/discover.py#L344-L348)):

```python
_MARKET_FRESHNESS_DAYS = {
    "price":    7,
    "metadata": 30,
    "shares":   90,
}
```

Staleness check ([discover.py:484-495](../../scripts/pipeline/discover.py#L484-L495)):

```python
for _, row in merged.iterrows():
    if row.get("unfetchable") is True:
        continue
    if (
        _stale(row.get("fetch_date"),    cutoffs["price"])
        or _stale(row.get("metadata_date"), cutoffs["metadata"])
        or _stale(row.get("sec_date"),      cutoffs["shares"])
    ):
        stale_tickers.append(row["ticker"])
```

A ticker is stale if **any** of the three date buckets is past its cutoff. `fetch_date = NULL` counts as stale (`_stale` returns `True` on `None`/`NaN`).

### 2.2 `validate_post_write` sentinel gate — [scripts/fetch_market.py:874-880](../../scripts/fetch_market.py#L874-L880)

```sql
SELECT COUNT(*) FROM market_data
WHERE unfetchable IS NOT TRUE
  AND (fetch_date IS NULL
       OR CAST(fetch_date AS DATE)
            < CURRENT_DATE - INTERVAL '7' DAY)
```

Anything with a stale `fetch_date` (or NULL) after a fetch run counts as a `stale_price_rows` WARN.

### 2.3 Implication for silent writers

A writer that populates `sector` (or any other attribute) **without** bumping `fetch_date` leaves the ticker visible to `discover_market` as price-stale. `discover_market` hands the ticker back to `fetch_market.py`, which makes a fresh Yahoo call on the next run even though the attribute under repair is already populated. Cost: needless Yahoo round-trips plus the structural silent-writer hazard: diff-based audits keyed on `fetch_date` miss these writes.

---

## 3. Writer enumeration (9 code paths across 5 scripts)

Ordered by impact. Line citations against `main` @ `7b19034` (today).

| # | File | Line | Shape | Touches `sector`? | Stamps `fetch_date`? | Other date bumped? | Class |
|---|---|---|---|---|---|---|---|
| 1 | [scripts/fetch_market.py:361](../../scripts/fetch_market.py#L361) — `_ensure_rows_exist` | 359–364 | `INSERT ... (ticker, fetch_date) ON CONFLICT DO NOTHING` | No | **Yes** | — | STANDARD |
| 2 | [scripts/fetch_market.py:378](../../scripts/fetch_market.py#L378) — `upsert_yahoo` | 378–390 | `UPDATE ... SET sector = COALESCE(d.sector, m.sector), ..., fetch_date = d.fetch_date, metadata_date = COALESCE(d.metadata_date, m.metadata_date)` | Yes | **Yes** (L387) | `metadata_date` (L388) | STANDARD |
| 3 | [scripts/fetch_market.py:407](../../scripts/fetch_market.py#L407) — `upsert_sec` | 406–417 | `UPDATE ... SET shares_outstanding = ..., sec_date = d.sec_date` | No | No | `sec_date` (L415) | STANDARD — SEC-owned bucket uses `sec_date` |
| 4 | [scripts/fetch_market.py:427](../../scripts/fetch_market.py#L427) — `recompute_market_cap` | 426–432 | `UPDATE ... SET market_cap = CASE WHEN shares_outstanding IS NOT NULL ... THEN shares × price_live ELSE NULL END` | No | No | No | STANDARD-DERIVED — pure recompute of a derived column, no fetch involved; correct to exclude |
| 5 | [scripts/fetch_market.py:476-484](../../scripts/fetch_market.py#L476-L484) — `_stamp_batch_attempt` | 435–484 | `INSERT ... (ticker, fetch_date, [metadata_date], [sec_date]) VALUES ... ON CONFLICT (ticker) DO UPDATE SET fetch_date = excluded.fetch_date, ...` | No | **Yes** | conditionally `metadata_date`, `sec_date` | STANDARD — explicitly handles the empty-fetch case so zero-data tickers don't look perpetually stale |
| 6 | [scripts/approve_overrides.py:142](../../scripts/approve_overrides.py#L142) | 123–142 | `INSERT INTO market_data (...) SELECT ... FROM df_new` with record dict including `fetch_date = today` (L135) | Yes | **Yes** (L135) | — | STANDARD |
| 7 | [scripts/enrich_tickers.py:356](../../scripts/enrich_tickers.py#L356) | 329–356 | `INSERT INTO market_data (...) SELECT ... FROM df_new` with record dict including `fetch_date = today` (L341) | Yes | **Yes** (L341) | — | STANDARD |
| 8 | [scripts/auto_resolve.py:523](../../scripts/auto_resolve.py#L523) | 506–523 | `INSERT INTO market_data (...) SELECT ... FROM df_new` with record dict including `fetch_date = today` (L518) | Yes | **Yes** (L518) | — | STANDARD |
| 9 | [scripts/admin_bp.py:448](../../scripts/admin_bp.py#L448) | 445–454 | `INSERT OR REPLACE INTO market_data (..., sector, industry, ..., fetch_date) VALUES (...)` | Yes | **Yes** | — | STANDARD |
| **10** | **[scripts/refetch_missing_sectors.py:253-257](../../scripts/refetch_missing_sectors.py#L253-L257)** | **252–257** | `UPDATE market_data SET sector = ?, industry = ? WHERE ticker = ? AND sector IS NULL` | **Yes** | **No** | **No** | **SUSPECT** |

(Note: the line cited in the 2026-04-19 audit for `admin_bp.py` was `:130`. That line number is now occupied by the `admin_sessions` DDL added by sec-01-p1. The actual `market_data` INSERT has moved to `:448` but the behaviour — full record with `fetch_date` — is unchanged. No other audit-referenced line has shifted.)

---

## 4. The standing hazard

[scripts/refetch_missing_sectors.py:252-257](../../scripts/refetch_missing_sectors.py#L252-L257):

```python
if sector:
    con.execute(
        "UPDATE market_data SET sector = ?, industry = ? "
        "WHERE ticker = ? AND sector IS NULL",
        [sector, industry, tk]
    )
```

Every other column-mutating writer on `market_data` stamps its own bucket date in the same statement. This writer is the sole outlier.

Current fix status: **unpatched** on `main` @ `7b19034`. `git log -- scripts/refetch_missing_sectors.py` shows the last two commits are `3738179` (throttle fix, 2026-04-18) and `c0262ed` (`--staging` flag + resume support). Neither touches the UPDATE statement.

The prior audit (2026-04-19) explicitly deferred the fix: "No fix commits on this audit branch. Audit deliverable is this document only." The recommendation section left two options on the table — adding a new `last_write_ts` column, or requiring `fetch_date` bumps on every UPDATE. int-15 is the block where that decision gets made.

### 4.1 Is there a `last_write_ts` column?

No. `grep -rn last_write_ts` returns three hits:

- `docs/findings/2026-04-19-block-market-data-writer-audit.md` — the proposal itself
- `archive/docs/reports/block_sector_coverage_closeout_20260419_052804.md` — references the audit
- `ROADMAP.md` — INF31 mention

No DDL, no migration, no writer, no reader. If Phase 1 goes with Option 1 it is a net-new column; if Option 2 it's an in-place behaviour change on one UPDATE statement.

### 4.2 Secondary risk surface

Outside the enumerated writers, searches for ad-hoc `market_data` writes (the audit's §2.1 `rg` queries re-run today) return **zero** additional matches. The ephemeral staging→prod sector mirror helper cited in the audit (commit `2405df1`) is not in the repo — it was a one-off `UPDATE` script that ran once and was discarded. Any future ad-hoc helper in the same shape would reintroduce the hazard; a CI-enforced convention (Phase 1) is the only durable fix.

---

## 5. Recommendation for Phase 1 (out of scope for this doc)

**Preferred: Option 2 — require `UPDATE market_data` to bump the correct bucket date in the same statement.**

Reasoning:

1. **Single writer to change.** Only `refetch_missing_sectors.py:253-257` violates the convention today. A two-line diff closes the gap:

   ```python
   con.execute(
       "UPDATE market_data SET sector = ?, industry = ?, "
       "fetch_date = ?, metadata_date = ? "
       "WHERE ticker = ? AND sector IS NULL",
       [sector, industry, today, today, tk]
   )
   ```

2. **No schema churn.** Option 1 (`last_write_ts`) requires a DuckDB migration, touches every reader that currently uses `fetch_date` for freshness, and extends the INF39 schema-parity matrix. Option 2 ships in one commit with zero migration.

3. **Semantic alignment with `_stamp_batch_attempt`.** `fetch_market.py:435-484` already took this position: it stamps attempt-dates on empty fetches precisely so downstream readers treat "we tried, got nothing" as a freshness signal. A manual sector refetch that succeeded is a stronger signal than an empty attempt — it should also bump.

4. **CI enforcement is tractable.** A lint-grade rule can catch any future `UPDATE market_data` whose SET clause omits a date column. Scoped to one table, few callers, no false-positive surface.

Tradeoff vs. Option 1 ("last_write_ts retains a separate audit trail"): rejected. `manifest_id` + `ingestion_impacts.manifest_id → manifest` already provide the audit trail for every *standard* write. Manual writers like `refetch_missing_sectors.py` are the gap, but their frequency is low enough (manual invocation only) that logging to `stdout` + the progress JSON is sufficient audit, and requiring them to bump `fetch_date` is not a semantic overload — it correctly records "this ticker's attribute layer was refreshed today."

**Non-recommendation:** do not attempt to retrofit `recompute_market_cap` with a date stamp. It is a pure arithmetic recompute of a derived column; stamping a date would falsely imply a data refresh.

---

## 6. Exit state

- Writers enumerated: **10 code paths across 5 scripts** (unchanged from 2026-04-19 audit). All line numbers re-verified against `main` @ `7b19034`.
- Sector-touching writers: 6 — 5 STANDARD, 1 SUSPECT.
- Non-sector `market_data` writers: 4, all in `fetch_market.py`.
- Standing hazard: **[scripts/refetch_missing_sectors.py:253-257](../../scripts/refetch_missing_sectors.py#L253-L257)** — unpatched.
- `last_write_ts` column: **does not exist** on disk or in any writer/reader.
- Phase 1 recommendation: Option 2 (bump `fetch_date` + `metadata_date` on the UPDATE). Decision belongs to the int-15 Phase 1 prompt.
- No code authored. Deliverable is this document.

---

## 7. Citations

- Prior audit: [docs/findings/2026-04-19-block-market-data-writer-audit.md](2026-04-19-block-market-data-writer-audit.md) — 2026-04-19, base `d7ba1c2`
- Remediation plan entry: [docs/REMEDIATION_PLAN.md:51](../REMEDIATION_PLAN.md#L51) (int-15 row)
- Roadmap entry: `ROADMAP.md` INF31 row
- `discover_market` logic: [scripts/pipeline/discover.py:367-527](../../scripts/pipeline/discover.py#L367-L527)
- Freshness thresholds: [scripts/pipeline/discover.py:344-348](../../scripts/pipeline/discover.py#L344-L348)
- Sentinel gate: [scripts/fetch_market.py:874-880](../../scripts/fetch_market.py#L874-L880)
- Empty-fetch attempt stamping: [scripts/fetch_market.py:435-484](../../scripts/fetch_market.py#L435-L484)
