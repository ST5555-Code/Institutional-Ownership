# REWRITE build_shares_history.py — Phase 0 Findings

- Branch: `rewrite-build-shares-history`
- Base commit: `bcf1e60` (main)
- Date: 2026-04-19
- Scope: read-only audit of `scripts/build_shares_history.py`. No writes.

---

## TL;DR

`build_shares_history.py` is a two-halves script:

1. **`build()`** populates `shares_outstanding_history` from the SEC XBRL
   companyfacts cache. This half is **healthy, canonical, and should stay.**
   The table is keyed by `(ticker, as_of_date)`, holds 317,049 rows across
   4,450 distinct tickers spanning 1997 → 2033 (forward-dated), and has no
   competing writer.
2. **`update_holdings_pct_of_so()`** recomputes period-accurate
   `pct_of_so` on the `holdings` table via DuckDB `ASOF JOIN`.
   **This half is dead code.** The `holdings` table was dropped at Stage 5
   (BLOCK-3 context); a fresh `SELECT COUNT(*) FROM holdings` against prod
   today returns `CatalogException: Table with name holdings does not
   exist!`. Invoking `build_shares_history.py --update-holdings` would
   crash on the first read.

The REWRITE therefore splits into two questions:
- Retire the dead `update_holdings_pct_of_so()` entirely? Or
- Repoint it to `holdings_v2` and re-establish period-accurate
  `pct_of_so` (which `enrich_holdings.py` currently computes using
  **latest** `market_data.float_shares`, reintroducing the exact latent
  accuracy bug the original script was written to fix)?

Plus the §1 / §5 / §9 retrofits shared with every Batch-3 REWRITE.

**No blockers.** `holdings_v2.pct_of_so` already exists (7.79M / 12.27M
rows populated, ~63.4% across 2025Q1–2025Q4). The SEC XBRL cache is
intact (5,074 files). `market_data` is fresh through 2026-04-16.

---

## 1. Code structure review (0.1)

### 1.1 Entry points

`main()` at `scripts/build_shares_history.py:209-232`:

```
parser.add_argument("--staging", action="store_true")          # :211
parser.add_argument("--update-holdings", action="store_true")  # :212
...
if args.staging: set_staging_mode(True)                        # :216-217
con = duckdb.connect(get_db_path())                            # :224
build(con, client)                                             # :226
if args.update_holdings:                                       # :228
    update_holdings_pct_of_so(con)                          # :229
```

Two functions. `build()` is called unconditionally; `update_holdings_pct_of_so()` is gated by `--update-holdings`.

Helpers:
- `_upsert_batch(con, batch)` at `:123-135` — `ON CONFLICT (ticker, as_of_date) DO UPDATE`, called via `executemany`.

### 1.2 Read operations — `holdings`

Only `update_holdings_pct_of_so()` reads `holdings`. Two sites:

| file:line | Query | Purpose |
|---|---|---|
| `build_shares_history.py:161-164` | `FROM holdings WHERE ticker IS NOT NULL AND report_date IS NOT NULL` (DISTINCT ticker, report_date) | ASOF-JOIN source: all (ticker, report_date) pairs to match against SOH |
| `build_shares_history.py:201` | `SELECT COUNT(*) FROM holdings` | Denominator for post-update coverage report |
| `build_shares_history.py:202` | `SELECT COUNT(*) FROM holdings WHERE pct_of_so IS NOT NULL` | Numerator for post-update coverage report |

`holdings.report_date` is stored as VARCHAR in `DD-MON-YYYY` format
(e.g. `"31-MAR-2025"`) per the inline comment at `:155-156`. Conversion
via `strptime(report_date, '%d-%b-%Y')::DATE` at `:162`.

`holdings_v2.report_date` is also VARCHAR in the same format — verified
via `PRAGMA table_info(holdings_v2)`: column type `VARCHAR`. A repoint
from `holdings` → `holdings_v2` would require the same `strptime` cast
(same format already used).

`build()` itself reads only `market_data` (`:60-63`), **not** `holdings`.
That read is clean:

```sql
SELECT DISTINCT ticker FROM market_data
WHERE (unfetchable IS NULL OR unfetchable = FALSE)
```

### 1.3 Write operations

Three write surfaces:

| file:line | Target | Shape | Idempotency |
|---|---|---|---|
| `:125-135` (`_upsert_batch`) | `shares_outstanding_history` | 7-col INSERT ... ON CONFLICT DO UPDATE (PK `(ticker, as_of_date)`) | **YES** — upsert keyed on PK |
| `:177-184` | `holdings.pct_of_so` (dropped) | `UPDATE holdings h SET pct_of_so = ROUND(h.shares*100/ps.period_shares, 4) FROM _period_shares ps WHERE ...` | **N/A — table gone** |
| `:190-199` | `holdings.pct_of_so` (dropped) | Fallback `UPDATE holdings h SET pct_of_so = ... FROM market_data m, _period_shares ps WHERE ps.period_shares IS NULL` | **N/A — table gone** |

`shares_outstanding_history` write is upsert-clean. The two `holdings`
UPDATEs are the violations called out in `docs/pipeline_violations.md:299-300`.

### 1.4 External dependencies

- `SECSharesClient` at `scripts/sec_shares_client.py`.
  - Cache dir: `data/cache/sec_companyfacts/` (5,074 JSON files today).
  - Ticker → CIK map: `data/reference/sec_company_tickers.csv`.
  - Override CSV: `data/reference/shares_overrides.csv`.
  - User-Agent: `"13f-ownership-research serge.tismen@gmail.com"` (matches CLAUDE.md EDGAR identity).
  - Rate limit: `RATE_LIMIT_SLEEP = 0.11` (~9 req/sec, under SEC's 10/sec cap).
  - `fetch_history(ticker)` at `sec_shares_client.py:226-281` returns
    list of dicts: `{ticker, cik, as_of_date, shares, form, filed, source_tag}`,
    sorted ascending by `as_of_date`, deduplicated by end date with tag
    priority `dei:ESO > us-gaap:CSO > us-gaap:ESO > us-gaap:WANOSO`.
- No database reads from this path — XBRL is filesystem JSON only.
- No API fetches on default path; SEC API only called on cache miss
  (> 90 days old or missing) — `CACHE_MAX_AGE_DAYS = 90` at `sec_shares_client.py:48`.

### 1.5 Error handling (silent continue sites)

| file:line | Pattern | Impact |
|---|---|---|
| `:78-81` | `if not history: if client.get_cik(tkr) is None: no_cik += 1; continue` | Missing XBRL data silently counted, continue. No unresolved-% gate at run end. |
| `:78` | `if not history:` — treats empty *and* exception-returned-empty the same. `SECSharesClient.fetch_history` swallows parse errors internally via the sorted/dedup pattern. | Parse anomalies never surface. |
| `:148-150` | `if is_staging_mode(): print("...skipping"); return` | Staging-mode skip of pct_of_so is fine, but no error is raised if that condition is somehow mis-detected. |
| `:197-198` | Fallback UPDATE silently ignores rows with no `shares_outstanding` and no `float_shares`. No count of skipped. | Coverage-loss invisible. |

Per `docs/pipeline_violations.md:295`: **§5 silent — empty `history` → continue.**

### 1.6 Flag semantics

| Flag | Site | Behavior |
|---|---|---|
| `--staging` | `:211`, `:216-217` | Routes `get_db_path()` to `STAGING_DB`. Cross-DB reads remain on prod via `connect_read()` at `:59`. In staging mode, `update_holdings_pct_of_so` is a no-op (`:148-150`). |
| `--update-holdings` | `:212`, `:228-229` | Gates the (currently-dead) `update_holdings_pct_of_so()` call. Default OFF. |

**Missing:** `--dry-run`. The script writes to prod by default — 317K
rows get upserted into `shares_outstanding_history` with no preview.
Per `docs/pipeline_violations.md:296-298`: **§9 VIOLATION.**

Retrofits shared with Batch-3 peers (`fetch_finra_short.py` minor,
`fetch_ncen.py` minor, `build_summaries.py` rewritten):

- §1: only two CHECKPOINTs total (`:117`, `:206`). Per-batch CHECKPOINT
  inside `_upsert_batch` is the fix.
- §5: silent continue at `:78`; should log tickers with no history to a
  CSV or print at end with an unresolved-% gate.
- §9: no `--dry-run` observe-only flag; `--apply` gate to make writes
  explicit.

---

## 2. Data quantification (0.2)

All queries read-only against prod (`data/13f.duckdb`, 13.5 GB, 2026-04-18 20:30).

### 2.1 `shares_outstanding_history`

| metric | value |
|---|---:|
| total rows | **317,049** |
| distinct tickers | **4,450** |
| distinct CIKs | **4,294** |
| `as_of_date` min | 1997-12-31 |
| `as_of_date` max | 2033-09-12 (forward-dated forecast filings; benign) |
| data_freshness stamp | **NONE** (no row for `shares_outstanding_history` in `data_freshness`) |

Source tag breakdown (what XBRL fact each row came from):

| source_tag | rows |
|---|---:|
| `dei:EntityCommonStockSharesOutstanding` | 152,541 |
| `us-gaap:CommonStockSharesOutstanding` | 114,560 |
| `us-gaap:WeightedAverageNumberOfSharesOutstandingBasic` | 49,948 |

Form breakdown (top 5):

| form | rows |
|---|---:|
| 10-Q | 228,106 |
| 10-K | 79,969 |
| 20-F | 3,859 |
| 10-Q/A | 1,569 |
| 6-K | 1,157 |

Rows by `as_of_date` year, 2015 onward:

| year | rows |
|---|---:|
| 2015 | 16,583 |
| 2020 | 21,832 |
| 2024 | 27,548 |
| 2025 | 27,691 |
| 2026 | 3,502 |
| 2029..2033 | 3 total (forward-dated, harmless) |

### 2.2 `holdings` (legacy)

```sql
SELECT COUNT(*) FROM holdings;
-- CatalogException: Catalog Error: Table with name holdings does not exist!
```

**Table is GONE.** Dropped at Stage 5. The `holdings.pct_of_so`
write target does not exist. Both UPDATE statements in
`update_holdings_pct_of_so()` would crash if the function were called.
The sole reason the script does not crash on `--update-holdings` today
is that nobody passes the flag.

### 2.3 `holdings_v2` schema and `pct_of_so` coverage

`holdings_v2` columns include both `pct_of_so DOUBLE` and
`report_date VARCHAR` (verified via `PRAGMA table_info(holdings_v2)`).

| metric | value |
|---|---:|
| `holdings_v2` rows | **12,270,984** |
| `pct_of_so` non-null | **7,786,239** (63.5%) |
| `report_date` format | `DD-MON-YYYY` (same as legacy `holdings`) |

Coverage by quarter (most recent):

| quarter | rows | pct_of_so populated | pct |
|---|---:|---:|---:|
| 2025Q4 | 3,205,650 | 2,031,842 | 63.4% |
| 2025Q3 | 3,024,698 | 1,935,040 | 64.0% |
| 2025Q2 | 3,047,474 | 1,930,019 | 63.3% |
| 2025Q1 | 2,993,162 | 1,889,338 | 63.1% |

**Writer:** `scripts/enrich_holdings.py:234-237` (Pass B) — computes
`pct_of_so = h.shares * 100.0 / lookup.float_shares` where
`lookup.float_shares = market_data.float_shares` (latest, not
period-accurate). The `_LOOKUP_SQL` at `enrich_holdings.py:68-74`
confirms this:

```sql
SELECT c.cusip,
       s.security_type_inferred,
       c.is_equity,
       CASE WHEN c.is_equity THEN s.ticker END AS new_ticker,
       md.price_live,
       md.float_shares          -- latest, period-agnostic
  FROM cusip_classifications c
  LEFT JOIN securities s ...
  LEFT JOIN market_data md ON md.ticker = ...
```

**This reintroduces the exact latent accuracy bug** that
`build_shares_history.py` was originally designed to fix (per the
module docstring at `build_shares_history.py:13-16`):

> This is the fix for a latent accuracy bug where `holdings.pct_of_so`
> used `market_data.shares_outstanding` (latest) as the denominator for
> all historical quarters, inflating or deflating ratios for companies
> with splits, buybacks, or offerings between the holding's report_date
> and today.

The fix was built against `holdings`, then the `holdings` table was
dropped in Stage 5, `holdings_v2.pct_of_so` ownership moved to
`enrich_holdings.py`, and the period-accurate logic was not ported.
The bug the original docstring describes is now back on `holdings_v2`.

### 2.4 `market_data` shares/float coverage

```
 total  shares_populated  float_populated
 10064              5251             4969
```

- 52.2% populated for `shares_outstanding`
- 49.4% populated for `float_shares`
- 96.9% of rows are fetchable (`unfetchable` NULL or FALSE)
- Last stamp: `2026-04-16 23:27:35` (per `data_freshness.table_name = 'market_data'`)

Sanity — 3,783 of 14,165 distinct `holdings_v2.ticker` values have
**any** SOH coverage (26.7%). The remaining 10,382 are mostly
non-SEC-registrant CUSIPs (ETFs, foreign issuers without US XBRL,
preferreds, recent IPOs without 90-day cache rotation yet) and
N-PORT-only tickers that were never in `market_data`'s SEC-resolved
population when the last SOH build ran.

### 2.5 SEC XBRL cache

- Path: `data/cache/sec_companyfacts/`
- Files: 5,074 JSON blobs
- Reference CSVs present: `sec_company_tickers.csv`, `shares_overrides.csv`
- Cache → `market_data` link: `fetch_market.py` v2 writes
  `market_data.shares_outstanding` from SEC, which feeds the
  `build_shares_history.py` tickers loop via the `market_data` read
  at `:60-63`. Link intact (Batch 2A/2B rewrite per
  `docs/pipeline_inventory.md:56`).

---

## 3. Proposed rewrite (0.3)

### 3.1 Read-path changes

Status quo `build()`:

```sql
SELECT DISTINCT ticker FROM market_data
WHERE (unfetchable IS NULL OR unfetchable = FALSE)
```

No change needed. `market_data` is the right universe (CUSIP-anchored
via `securities.canonical_type` post-BLOCK-2A/2B).

Status quo `update_holdings_pct_of_so()`:

```sql
FROM holdings WHERE ticker IS NOT NULL AND report_date IS NOT NULL   -- :163
```

**Retire this read entirely** if the function is removed (Option A
below). Repoint to `holdings_v2` if the function is kept (Option B).

### 3.2 Write-path changes

`shares_outstanding_history` — **unchanged.** Canonical, healthy,
upsert-clean. The rewrite retains the `build()` side verbatim in
semantic terms (subject to retrofits below).

`holdings.pct_of_so` writes — **retire.** The target table is gone.

Decision on what, if anything, replaces the period-accurate
`pct_of_so` ASOF JOIN:

| option | description | pros | cons |
|---|---|---|---|
| **A — retire** | Delete `update_holdings_pct_of_so()` entirely. `enrich_holdings.py` Pass B remains sole writer of `holdings_v2.pct_of_so` using latest `market_data.float_shares`. | Minimal blast radius. Keeps `build_shares_history.py` scope literal to its filename. Matches BLOCK-3 peers which retired legacy update paths. | Re-accepts the latent period-accuracy bug the original script was written to fix. |
| **B — repoint to `holdings_v2`** | Port the two UPDATEs to target `holdings_v2`, using the same `latest_rm`/`strptime` pattern. Keep the staging-mode skip. | Restores period-accurate `pct_of_so` on ~7.79M currently-populated rows + potentially fills some of the ~4.48M NULL rows where SOH has coverage that `market_data.float_shares` lacks. | Two writers on `holdings_v2.pct_of_so` (`enrich_holdings.py` Pass B and this) — write-order discipline becomes a new gotcha. Scope creep: a "build history" script now also owns enrichment. |
| **C — move ASOF into `enrich_holdings.py`** | Extend Pass B's `_LOOKUP_SQL` to prefer SOH's period-accurate shares over `market_data.float_shares` when both are available. `build_shares_history.py` becomes purely a history builder; `enrich_holdings.py` owns all `pct_of_so` writes. | Separation of concerns (each script does one thing). No dual writer. Fixes the latent bug at the right layer. | Pass B is currently cusip-keyed (via `cusip_classifications`). SOH is ticker-keyed. Requires a cusip→ticker bridge (`securities.ticker` already used) plus ASOF on `report_date`. Moderate complexity increase inside an already-working script. |

**Recommendation: A for Phase 1 (retire), with a follow-up block
C-BLOCK-PCT-OF-SO-PERIOD-ACCURACY for C (move ASOF into
`enrich_holdings.py`).** Rationale:

- The dead-code symptom (script crashes on `--update-holdings`) is the
  immediate REWRITE concern. Fix that cleanly.
- Re-introducing period-accurate `pct_of_so` deserves its own
  design pass: which ticker → cusip canonicalization, how to handle
  ticker-changes mid-quarter, how to cap SOH's forward-dated rows, how
  to gate `is_equity` for ADRs with Frankfurt SOH listings (BLOCK-
  SECURITIES-DATA-AUDIT context). Bundling it into `build_shares_history.py`
  rewrite would widen the blast radius here.
- Option C is clearly better than B if period-accuracy is wanted.
  Choosing B now forecloses C and leaves two writers.

User to confirm A (preferred) or B (if period-accuracy restoration
cannot wait for the follow-up block) before Phase 1.

## 3.2.1 — Downstream readers survey

**Follow-up status: DONE 2026-04-19.** The period-accurate
`pct_of_so` follow-up flagged in §3.2 (Option C deferred to its own
design pass) was addressed by the **pct-of-so workstream**
(merged `8925347`, follow-on `12e172b`). Forward-link:
[`docs/findings/2026-04-19-rewrite-pct-of-so-period-accuracy.md`](2026-04-19-rewrite-pct-of-so-period-accuracy.md)
— see that doc's §4 (three-tier denominator design) and §14.10
(terminology rename `pct_of_float → pct_of_so` + `pct_of_so_source`
audit column). Migration 008 (`ea4ae99` amended) landed the rename +
audit column; `enrich_holdings.py` Pass B now runs SOH ASOF with the
three-tier fallback (`soh_period_accurate` → `market_data_so_latest`
→ `market_data_float_latest`). True float-adjusted denominator
(public-float-based, distinct from shares-outstanding) remains deferred
as **INF38 / BLOCK-FLOAT-HISTORY** per `docs/DEFERRED_FOLLOWUPS.md`.

Amendment 2026-04-19 — read-only grep pass for every consumer of
`holdings.pct_of_so` and `holdings_v2.pct_of_so`.

### Grep commands run

```
rg -n "pct_of_so" scripts/
rg -n "pct_of_so" scripts/api_market.py scripts/api_register.py scripts/admin_bp.py scripts/build_summaries.py
rg -n "pct_of_so" web/react-app/src/
rg -n "pct_of_so" web/datasette_config.yaml
rg -n "pct_of_so" docs/ --glob '!*FINDINGS.md'
rg -n "pct_of_so" notebooks/research.ipynb ROADMAP.md
```

Directories `sql/`, `migrations/`, `reports/` do not exist in the repo
(checked). No hits outside the surfaces listed above.

### Hit counts by classification

| classification | count | scope |
|---|---:|---|
| **READ (live, `holdings_v2` or `summary_by_parent`)** | **~30** | Flask/API/TSX consumers, see table below |
| **WRITE (live, `holdings_v2`)** | **2** | `enrich_holdings.py` Pass A + Pass B (sole live writer) |
| **WRITE (dead, `holdings` dropped)** | **10** | spread across 5 scripts, all RETIRE/REWRITE |
| **SCHEMA** | **2** | `summary_by_parent` DDL + React `api.ts` TypeScript type |
| **DOC** | **~30** | prose references in `docs/*`, ROADMAP, module docstrings |
| **COMMENT** | **5** | inline comments or Python docstrings |
| **BROKEN (references dropped `holdings`)** | **~18** | `notebooks/research.ipynb` (17), `web/datasette_config.yaml` (1 YAML block with 3 queries) |

### Live READ consumers (holdings_v2 / summary_by_parent)

| file:line | endpoint / purpose | user-facing impact |
|---|---|---|
| `scripts/queries.py:574` | `holder_aggregation` by quarter | feeds Holders tab — displayed to user |
| `scripts/queries.py:693-705` | parent rollups by child | Parent Detail — displayed |
| `scripts/queries.py:763` | rollup SUM by entity | Register tab — displayed |
| `scripts/queries.py:865` | ownership by manager_type | Market tab — displayed |
| `scripts/queries.py:1308-1346` | top-holders CTE + output | Ticker Detail — displayed |
| `scripts/queries.py:1587` | total_pct_float aggregate | Ticker summary card — displayed |
| `scripts/queries.py:1691` | per-holding row list | Fund Portfolio — displayed |
| `scripts/queries.py:1763-1765` | per-holding rollup with market_cap | Ticker Detail (peers) — displayed |
| `scripts/queries.py:1876` | q4 snapshot SELECT | Quarter Compare — displayed |
| `scripts/queries.py:1918-1924` | ownership concentration top-20 | Concentration widget — displayed + `WHERE pct_of_so IS NOT NULL` filter |
| `scripts/queries.py:2355-2357` | peer matrix rollup | Peers tab — displayed |
| `scripts/queries.py:2401-2403` | data-quality COUNT | Admin/QC — count only, NULL-tolerant |
| `scripts/queries.py:2894-2903` | quarter-over-quarter by entity | Flows / Change Detail — displayed |
| `scripts/queries.py:2919` | `_get_pf` Python helper | safe extractor w/ compute-fallback |
| `scripts/queries.py:3992-3994` | total_pct_float summary | Summary card — displayed |
| `scripts/api_market.py:153` | `/api/top-holders` | top-10 holders JSON → React Market tab |
| `scripts/api_market.py:259` | `/api/heatmap` | ownership concentration heatmap (top 15 managers × tickers) → React |
| `scripts/api_register.py:293` | `/api/register/holdings` | Register tab holdings grid → React |
| `scripts/admin_bp.py:500` | admin data-quality counter | `COUNT(pct_of_so)` — coverage metric only |
| `scripts/build_summaries.py:188` | reads `holdings_v2`, writes `summary_by_parent.pct_of_so` | precomputed summary table feeding many queries.py endpoints |
| `scripts/enrich_holdings.py:125,184,355` | self-QC projection / baseline / final | internal run-metrics only |
| `web/react-app/src/components/tabs/FundPortfolioTab.tsx:119` | CSV export column | end-user downloads |
| `web/react-app/src/components/tabs/FundPortfolioTab.tsx:243` | `<td>` rendering | displayed as `fmtPct2(p.pct_of_so)` |

### Live WRITE site

- `scripts/enrich_holdings.py:151` — Pass A: `SET pct_of_so = NULL`
  for cusips not in `cusip_classifications`.
- `scripts/enrich_holdings.py:234-237` — Pass B: `SET pct_of_so = h.shares * 100.0 / lookup.float_shares`
  where `lookup.float_shares = market_data.float_shares` (**latest**, period-agnostic).
- Sole writer. No other live script touches `holdings_v2.pct_of_so`.

### Dead / legacy WRITE sites (all targeting the dropped `holdings` table)

| file:line | action | status |
|---|---|---|
| `scripts/build_shares_history.py:177-184, :190-199` | UPDATE holdings SET pct_of_so | dead — this rewrite's target |
| `scripts/approve_overrides.py:159-164` | UPDATE holdings SET pct_of_so | dead — script is on RETIRE list (`pipeline_inventory.md:108`) |
| `scripts/auto_resolve.py:536-540` | UPDATE holdings SET pct_of_so | dead — script is on RETIRE list |
| `scripts/enrich_tickers.py:385-408` | UPDATE holdings SET pct_of_so | dead — script is on RETIRE list |
| `scripts/load_13f.py:273` | `NULL::DOUBLE as pct_of_so` in `CREATE TABLE holdings AS SELECT` | dead — script is REWRITE target (future `load_13f_v2.py`) |

All five above are documented as RETIRE or REWRITE in `docs/pipeline_inventory.md`
and are not part of the live pipeline. None would be affected by retiring
`build_shares_history.py`'s `update_holdings_pct_of_so()`.

### Broken / stale references (documented, not live)

- `notebooks/research.ipynb` — 17 hits, all querying `FROM holdings`. The
  notebook is stale since Stage 5 dropped `holdings`. Not a live consumer.
  Any attempt to run would throw CatalogException. Separate cleanup,
  not this block.
- `web/datasette_config.yaml:11-93` — 3 canned queries reference
  `FROM holdings h WHERE h.quarter = '2025Q4'` and expose `pct_of_so`.
  Datasette is local-only tooling; the config is broken today
  (any query would error). Flag only.

### Assessment — retire impact (Option A)

**Retiring `update_holdings_pct_of_so()` creates ZERO NULL
regressions in the live read surface.** Mechanical check:

1. All 30 live READ sites query `holdings_v2.pct_of_so` or
   `summary_by_parent.pct_of_so`.
2. `holdings_v2.pct_of_so` is written exclusively by
   `scripts/enrich_holdings.py` Pass B.
3. `summary_by_parent.pct_of_so` is written by
   `scripts/build_summaries.py:188` which reads `holdings_v2.pct_of_so`.
4. `build_shares_history.py`'s `update_holdings_pct_of_so()` does
   **not** write `holdings_v2` or `summary_by_parent`. It writes the
   dropped `holdings` table and fails on any invocation.
5. Removing it changes no data in any live consumer surface.

**The broader accuracy concern persists unchanged**: all 30 live READ
sites return `pct_of_so` computed against **latest**
`market_data.float_shares`, not the historical `shares_outstanding_history`
facts. That is the latent period-accuracy bug the original script was
built to fix. Option A does **not** fix it. It simply clears dead code.

**Consumers most sensitive to the latent bug** (where period
accuracy matters most — pre/post-split, pre/post-buyback, pre/post-
secondary-offering quarters):
- `queries.py:1918-1924` — ownership concentration top-20 per ticker:
  ranking is affected; a manager with correct shares at report_date
  can look artificially large/small today.
- `api_market.py:259` — heatmap: colors are tied to latest-float, not
  period-float. Visual distortion for split/buyback tickers.
- Quarter-over-quarter views (`queries.py:2894-2903`): the same position
  shown for two consecutive quarters uses the *same* current float,
  masking a split that happened between them.

Magnitude was documented at cut-over time
(`docs/NEXT_SESSION_CONTEXT.md:922`):
> GOOGL 2020 pct_of_so corrected from 0.4% to 7.3% (20:1 split).

That order-of-magnitude correction is exactly what's missing today.

### Unknown-blast-radius check

No grep hits outside the surfaces enumerated above. No external
dashboards, vendor integrations, or third-party consumers found in
the repo. All consumers are internal (Python/TSX/SQL/docs).

### Updated recommendation

**Still Option A for Phase 1 — evidence-strengthened.** The
downstream-readers survey shows retirement is a pure dead-code
removal: no NULL regressions, no consumer-visible change in values,
no data refresh cadence change.

**Elevate the follow-up block.** The 30-site live read surface —
including user-facing React tabs (Register, Market, Ticker Detail,
Fund Portfolio, Holders, Peers), CSV exports, and the heatmap /
concentration widgets — is materially sensitive to the period-
accuracy bug. Option C (move ASOF into `enrich_holdings.py`) is
higher-priority than the original Phase 0 doc suggested.
Recommend creating `BLOCK-PCT-OF-SO-PERIOD-ACCURACY` as the
immediate next block after `rewrite-build-shares-history` merges.

### 3.3 Retrofit violations

Uniform with `fetch_finra_short.py` / `fetch_ncen.py` retrofits (per
`docs/pipeline_inventory.md:57-58`) and Batch-3 peers:

| # | Violation | Fix |
|---|---|---|
| §1 | Only 2 CHECKPOINTs (`:117`, `:206`) | Move CHECKPOINT inside `_upsert_batch` after each `executemany` (or every N batches). Current BATCH=1000 stays; CHECKPOINT cadence = every 10 batches (10K rows) matches `fetch_finra_short.py` tuning. |
| §5 | Silent continue on empty `history` (`:78`) | Collect `(ticker, reason)` tuples for no_cik / empty_history / fetch_error; print summary at end-of-run; optional `--strict` flag to non-zero exit if unresolved-% > threshold (e.g. 50% for well-known tickers). |
| §9 | No `--dry-run` | Add `--dry-run` (reports planned action counts, no writes, no SEC fetches — purely local cache reads); keep `--staging` as the write-target gate; default run writes staging, `--apply` promotes to prod. Matches `fetch_ncen.py` proposed convention. |
| §6 | Progress line at `:101` lacks `flush=True` | Add `flush=True` (or rely on `python3 -u` convention, matching `fetch_ncen.py`). |
| Freshness | No `data_freshness` row for `shares_outstanding_history` | Add `record_freshness(con, 'shares_outstanding_history')` at end-of-run, matching the 8 scripts retrofitted in commit `831e5b4` (per `docs/pipeline_inventory.md:22-29`). |

### 3.4 Test plan

Phase 2 (staging):

1. **Baseline on prod** (already captured in §2.1): 317,049 rows, 4,450
   tickers, 4,294 CIKs.
2. **Mirror to staging** via `scripts/sync_staging.py` (or whichever
   seed path carries `shares_outstanding_history`; verify
   `db.REFERENCE_TABLES` or `scripts/pipeline/registry.reference_tables()`
   lists SOH; if missing, flag).
3. **Re-run `build_shares_history.py --staging`**.
4. **Row-count delta vs prod backup**: Δ ≤ ±1% (acceptable from cache
   rotation between runs; any larger drift is a regression).
5. **Distinct-ticker delta**: Δ ≤ ±5 tickers. Larger Δ investigates
   `market_data.unfetchable` drift or SEC ticker-CIK map rotation.
6. **Spot-check 10 CUSIPs** (mix: AAPL / MSFT / NVDA / BRK-B / XOM /
   TLSA / JPM / WMT / UNH / GOOG) against SEC EDGAR `data.sec.gov/api/xbrl`
   — latest `as_of_date` and `shares` should match within ±0.01% of
   what the companyfacts JSON reports.
7. **Forward-dated rows** (2027+): count should be ≤ 10 (current: 3).
   If SEC-reported forward-dated facts grow, capped at ≤ 50 before
   flagging.
8. **`--dry-run` smoke**: run `--dry-run` on staging, confirm output
   matches actual `--staging` run's planned-row count ±0.

Phase 3 (prod promotion):

- Standard INF1 sync→diff→promote is **not** the pattern for SOH —
  this table is not in `db.ENTITY_TABLES` and staging→promote does
  not carry it. SOH is a direct-write table. Promotion is just running
  `build_shares_history.py` (no flag) in prod with sign-off.
- Gate: staging test plan §1–§7 pass, including the 10-CUSIP spot-check
  against live EDGAR.
- Post-run: `make freshness` still passes (new `shares_outstanding_history`
  row in `data_freshness` should show OK).

### 3.5 Sequencing and dependencies

**Depends on:**
- BLOCK-3 merged state (commit `bcf1e60`) — **satisfied**. Needed for
  `holdings_v2` full schema (`pct_of_so`, `report_date`) and for
  `enrich_holdings.py` as the single current `pct_of_so` writer.
- SEC XBRL cache fresh (5,074 files, 2026-04-19) — **satisfied**.
- `market_data` fresh (`2026-04-16 23:27:35`) — **satisfied**.

**Blocks (if any):**
- Nothing on the critical path. The `build()` side works today; the
  `update_holdings_pct_of_so()` side is dead but harmless (gated).
- Potential downstream unblock: if Option C is pursued in the follow-up,
  `enrich_holdings.py` regains period-accurate `pct_of_so`, which
  improves the quality of `compute_flows.py` and `build_summaries.py`
  outputs. Not a blocker.

**Does not block:** the remaining four Batch-3 REWRITE targets
(`build_summaries.py` is already done per `docs/pipeline_inventory.md:78`
— double-check the block prompt; per inventory, Batch 3 is closed
except `load_13f.py`, `build_managers.py`, `build_shares_history.py`,
`build_fund_classes.py`, `build_benchmark_weights.py`). Each is
self-contained.

---

## 4. Out of scope

- **Option C implementation** (period-accurate `pct_of_so` via SOH ASOF
  inside `enrich_holdings.py`). Deferred to a follow-up block
  (`BLOCK-PCT-OF-SO-PERIOD-ACCURACY` or similar) if user decides the
  latent accuracy bug is worth re-fixing.
- **SOH universe expansion.** Current universe is 4,450 tickers from
  `market_data`. Extending to `holdings_v2.ticker` universe (14,165 distinct)
  would add coverage for non-`market_data` tickers, but requires
  ticker→CIK resolution outside the current SEC map (which is registrant-
  only). Out of scope.
- **Override CSV audit** (`data/reference/shares_overrides.csv`). Parallel
  workstream to BLOCK-SECURITIES-DATA-AUDIT's `ticker_overrides.csv`
  triage. Not this block.
- **Forward-dated row policy.** Currently 3 rows with `as_of_date` >
  2026-12-31. If SEC starts publishing more forecast filings via XBRL,
  needs a cap. Not this block — flag only.
- **`data_freshness` hook for SOH.** Retrofit §9 above already includes
  this; noting here that it is technically BLOCK-FRESHNESS territory,
  not REWRITE — but cheap to bundle.
- **Retirement of `scripts/build_shares_history.py` itself** in favor
  of the framework `SourcePipeline.fetch()` protocol. The framework
  doesn't yet host XBRL-cache pipelines; this block keeps
  `build_shares_history.py` as a standalone script with retrofits.

---

## 5. Guardrails respected

- Read-only code inspection and prod queries only. No writes.
- Phase 0 commit is docs only.
- No branch merges. No staging or prod writes.
- `holdings_v2.pct_of_so` exists (confirmed); no "rewrite target column
  missing" blocker.
- SEC XBRL cache path and link to `market_data.shares_outstanding` intact
  post-Audit (confirmed).
- No new external dependencies. SEC XBRL + `requests` + `duckdb` —
  already present.

Safe to proceed to Phase 1 after Option A/B/C sign-off on §3.2.
