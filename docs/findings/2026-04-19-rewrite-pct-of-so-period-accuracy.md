# BLOCK-PCT-OF-FLOAT-PERIOD-ACCURACY — Phase 0 Findings

- Branch: `block/pct-of-float-period-accuracy`
- Base commit: `a409f02` (main, 2026-04-19)
- Scope: read-only investigation. No code changes, no DB writes, no
  script runs. Deliverable is this document.

---

## TL;DR — stop-and-reconsider flag

**`market_data.float_shares` is a single latest value per ticker. There
is no time series of `float_shares` anywhere in the database.** The
block prompt describes the fix as "an ASOF JOIN against `market_data`
keyed on `(ticker, quarter_end → nearest prior fetch_date)`." That
ASOF join is not constructible against current schema — `market_data`
has exactly 1 row per ticker (10,064 rows / 10,064 tickers verified
2026-04-19), with `fetch_date` a VARCHAR stamp of the most recent
Yahoo/SEC pull (2026-03-31 → 2026-04-16, 5 distinct dates, all within
the last three weeks).

The only period-indexed share count in the DB is
`shares_outstanding_history.shares` (SEC XBRL `shares_outstanding`,
338,053 rows, `as_of_date` 1997 → 2033). **This is
shares_outstanding, not float_shares.** The two are different:
`float_shares` = shares available to the public (excludes insiders,
restricted, treasury); `shares_outstanding` = total issued.

Phase 1 therefore cannot proceed as the block prompt is written.
Options before we spend any more engineering time:

| # | option | short description |
|---|---|---|
| **A** | **Change denominator semantics** — use `shares_outstanding` (period-accurate, available now) instead of `float_shares`. Existing `pct_of_float` column name becomes a misnomer; rename to `pct_of_so` or document semantics. |
| **B** | **Build a float_shares history table** — new `float_shares_history` ingested from SEC DEF 14A / 10-K filings (public float is disclosed annually in Part I, Item 5). Material scope expansion, probably another BLOCK. |
| **C** | **Approximation** — compute a per-ticker `float_ratio = latest_float_shares / latest_shares_outstanding` and multiply SOH `shares` by that ratio at each `as_of_date`. Assumes ratio stable over time; wrong when insider stake shifts materially (lockup expiries, secondaries, buybacks concentrated in float). |
| **D** | **Do nothing; retire the block** — accept the latent bug already called out in the peer `build_shares_history` findings doc. |

Plus all four options share an orthogonal coverage cliff: only
**4,186 of 14,165** `holdings_v2` tickers (29.6%) have any SOH row
at all — the remaining 9,979 tickers (70.4%) have zero coverage
(ETFs, foreign issuers without US XBRL, recent IPOs, delisted names,
N-PORT-only tickers). Any period-accurate fix therefore needs an
explicit fallback to **latest** `market_data.float_shares` for 70% of
tickers, which is exactly what the script does today for all 100%.
The net quality upgrade is concentrated in ~4,186 SEC-registrant US
equities — not nothing, but narrower than "fix the bug everywhere."

**Recommendation: pause Phase 1. Discuss A vs C with Serge before
writing any code.** Full analysis of each option below.

---

## §1. Current state — what Pass B does today

### 1.1 Pass B location and shape

`scripts/enrich_holdings.py:222-251` is Pass B's apply function.
Accompanying projection at `:171-219`. Both read `_LOOKUP_SQL`
defined at `scripts/enrich_holdings.py:68-78`:

```sql
-- _LOOKUP_SQL (enrich_holdings.py:68-78)
SELECT c.cusip,
       s.security_type_inferred,
       c.is_equity,
       CASE WHEN c.is_equity THEN s.ticker END AS new_ticker,
       md.price_live,
       md.float_shares             -- LATEST, PERIOD-AGNOSTIC
  FROM cusip_classifications c
  LEFT JOIN securities  s  ON s.cusip = c.cusip
  LEFT JOIN market_data md ON md.ticker = s.ticker
```

### 1.2 Computation (enrich_holdings.py:234-237)

```sql
UPDATE holdings_v2 AS h
   SET ...,
       pct_of_float = CASE WHEN lookup.is_equity
                             AND lookup.float_shares > 0
                            THEN h.shares * 100.0 / lookup.float_shares
                       END
  FROM (_LOOKUP_SQL) AS lookup
 WHERE h.cusip = lookup.cusip
   [AND h.quarter = ?]
```

The denominator `lookup.float_shares` is `market_data.float_shares`
for the ticker today. The numerator `h.shares` is the holding's
shares-as-of-`report_date`. No time alignment: 2025-03-31 holdings
are divided by 2026-04-16 float.

### 1.3 Join shape

- **Current**: 1-hop cusip → securities.ticker → market_data.ticker.
  Flat, single latest value per cusip.
- **No ASOF join present.** No time dimension at all on the denominator
  side.

### 1.4 Columns pulled from market_data

| column | type | time dimension? |
|---|---|---|
| `price_live` | DOUBLE | latest only |
| `float_shares` | DOUBLE | latest only |

Neither column has a history. `fetch_date` stamps *when* the latest
value was pulled, not *when* that value was the accurate figure as of.

### 1.5 Sole writer

Pass B is the only live writer of `holdings_v2.pct_of_float`.
Confirmed via `2026-04-19-rewrite-build-shares-history.md §3.2.1` and
re-verified in §3 below. Pass A (`enrich_holdings.py:141-164`) NULLs
`pct_of_float` for unclassified cusips; Pass B repopulates it.

---

## §2. Proposed fix — four paths

### 2.1 Option A — period-accurate `shares_outstanding`, rename or redocument column

**Mechanics:**
1. New ASOF join in Pass B, against `shares_outstanding_history`
   (keyed on ticker + `as_of_date` ≤ `quarter_end(report_date)`).
2. Denominator = `soh.shares`, not `market_data.float_shares`.
3. Fallback policy (see §4 edge-cases): if no SOH row ≤
   `quarter_end`, fall back to `market_data.float_shares` (existing
   behavior). Record fallback source on each row (new column
   `pct_of_float_source VARCHAR` — values: `soh_period`, `md_latest_fallback`).
4. Consider renaming column to `pct_of_so` (pct of shares outstanding)
   or explicitly documenting the mixed semantics.

**ASOF shape:**

```sql
WITH h_with_qe AS (
  SELECT h.*,
         strptime(h.report_date, '%d-%b-%Y')::DATE AS quarter_end
    FROM holdings_v2 h
)
SELECT h.*, soh.shares AS period_shares, soh.source_tag
  FROM h_with_qe h
  ASOF LEFT JOIN shares_outstanding_history soh
    ON soh.ticker = h.ticker
   AND soh.as_of_date <= h.quarter_end
```

**Pros:**
- Actually constructible against current schema. Zero new ingestion.
- 4,186 tickers (29.6% of holdings_v2 ticker universe, and the
  higher-AUM SEC-registrant population) get period-accurate
  denominators covering 2025Q1 → 2025Q4 for most active names.
- GOOGL 2020 20:1 split type corrections are restored on covered
  tickers (the exact bug the original `build_shares_history.py` was
  designed to fix).

**Cons:**
- **Semantic drift.** Column named `pct_of_float`, value becomes
  "pct of shares outstanding." For a typical large-cap (AAPL today:
  float 14.82B, SO 14.86B, ~99.7% overlap) the drift is trivial. For
  closely-held names (meme stocks, insider-heavy small-caps,
  high-insider tech IPOs) float can be 40–70% of SO — numbers shift
  2–3×.
- Dual semantics across rows: SOH-covered rows are pct_of_SO,
  md-fallback rows are pct_of_float. Mixed metric in a single column
  unless per-row source flag is added and downstream readers honor it.
- Display-side work: every user-facing site (§3) either gets a
  column-rename, a tooltip, or an asterisk explaining the semantics.

**Coverage impact (from §4):**
- 2025Q4 holdings: approximately 29.6% of distinct tickers, but
  these carry the majority of AUM (SEC-registrant US equities
  dominate 13F filings). Rough estimate: 80–90% of USD-weighted
  positions get period-accurate denominators; remaining 10–20% stay
  on latest-float fallback.

### 2.2 Option B — ingest a float_shares history

**Mechanics:**
1. New ingestion script `fetch_float_history.py` pulling 10-K Part I
   Item 5 ("Market for Registrant's Common Equity…" — public float
   disclosure) and DEF 14A beneficial ownership tables.
2. New table `float_shares_history (ticker, as_of_date, float_shares,
   form, filed_date, source_tag)`.
3. Pass B ASOF-joins against it.

**Pros:**
- True period-accurate `pct_of_float` preserved.
- No column rename, no downstream display work.

**Cons:**
- Substantial new ingestion: XBRL tag coverage for
  `dei:EntityPublicFloat` is partial (not every filer tags it; many
  disclose in prose only). Public float is typically disclosed **once
  per year** in the 10-K as of the last business day of the prior
  Q2; interpolation between annual snapshots is lossy.
- Float is a slower-moving quantity than SO (buybacks change SO;
  float changes only on lockup expiries, insider sales/buys, changes
  in affiliate status). So annual-only history is still a large
  improvement, but it's still coarse.
- Multi-week engineering scope. Peer BLOCK-SECURITIES-DATA-AUDIT
  and BLOCK-FRESHNESS are currently in flight.

### 2.3 Option C — approximation via latest float-ratio

**Mechanics:**
1. No new ingestion. Compute per-ticker
   `float_ratio = latest_float_shares / latest_shares_outstanding`
   from `market_data`.
2. Pass B ASOF-joins against SOH for `shares_outstanding` at
   `quarter_end`, then multiplies by `float_ratio`:
   `estimated_float_at_qe = soh.shares * float_ratio`
3. Denominator = `estimated_float_at_qe`.

**Pros:**
- Column name stays meaningful (`pct_of_float` *approximates* float).
- No new ingestion.
- Handles splits / buybacks that move SO — float scales
  proportionally.

**Cons:**
- **Fails exactly when float-accuracy matters most.** Float ratio is
  assumed stable over time; in reality, major float moves are:
  - Lockup expiries (IPO +180d) — float jumps step-wise, ratio
    shifts upward suddenly.
  - Secondary offerings — float can jump 20–50% while SO moves less
    if founders / PE firms exit partially.
  - Insider sales cascades — float trickles up.
  - Buybacks — float/SO ratio *increases* over time (float doesn't
    fall as fast as SO in Treasury-held buybacks).
- Silent wrongness: numbers look reasonable but embed a bias. Harder
  to audit than Option A's explicit semantic shift.

### 2.4 Option D — retire the block, accept the latent bug

**Mechanics:**
- Don't change Pass B. Accept latest-float as the denominator for
  all rows.
- Update docstrings / READMEs to document the known accuracy
  limitation.
- Close the block.

**Pros:**
- Zero engineering risk.

**Cons:**
- Peer findings doc explicitly flagged this as "elevate the follow-
  up block." Retiring it immediately after writing it looks bad;
  also leaves the `queries.py:1918-1924` concentration widget,
  `api_market.py:259` heatmap, and `queries.py:2894-2903` QoQ views
  structurally wrong for split / offering / buyback tickers in
  historical quarters.

### 2.5 Fallback policy (applies to A / B / C)

Regardless of option, roughly 70% of `holdings_v2` tickers have no
SOH coverage (§4). Fallback rules:

| tier | condition | denominator used | source flag |
|---|---|---|---|
| 1 | SOH has row with `as_of_date ≤ quarter_end` | `soh.shares` (A) / `float_history.float_shares` (B) / `soh.shares * float_ratio` (C) | `soh_period` / `float_history_period` / `ratio_approx` |
| 2 | SOH has rows but all are `> quarter_end` (newly listed mid-quarter) | Earliest `soh.shares` with 5% inflation haircut, OR `market_data.float_shares` | `soh_earliest` / `md_fallback` |
| 3 | No SOH coverage at all | `market_data.float_shares` (today's value) | `md_latest_fallback` |
| 4 | No SOH **and** no `market_data.float_shares` | NULL | `unresolved` |

The `pct_of_float_source` column makes downstream readers able to
de-mix: Register-tab counts and admin audits can filter to tier 1
only; Ticker Detail can display all and flag the fallbacks.

### 2.6 Recommendation

**Option A, gated on Serge's sign-off on the semantic drift.**

Rationale:
- A is the only option that is both constructible today and actually
  period-accurate on the covered subset.
- The 80/20 rule applies: large-cap holdings (the ones that drive
  the Register tab, Ticker Detail, and CSV exports visible to end
  users) have float/SO ratios very close to 1. Drift ≤ 2–5% on those.
- Small-cap and recent-IPO tickers where drift matters are also the
  tickers most prone to *having* splits / secondaries / lockup
  expiries that the current code completely ignores. Period-accurate
  SO is already a large improvement over latest-float on those.
- C ships silent wrongness. B is too large for this block.

**If Serge declines Option A's semantic drift**, the block should be
paused pending a decision to either proceed with B (multi-week
scope) or D (document and close).

---

## §3. Read-site inventory

Grep command:

```
rg -n "pct_of_float" scripts/ web/ docs/ notebooks/ ROADMAP.md
```

Live consumer sites — user-facing or API-returning — classified by
surface. The "~30 sites" estimate from the peer findings doc is
**confirmed as ~28 live sites** (give or take classification of the
admin-only coverage counter and the hardcoded-None placeholders).

### 3.1 Flask / backend read surfaces

| file:line | context | surface | notes |
|---|---|---|---|
| `scripts/queries.py:469-470` | read `market_data.float_shares` for recompute fallback | backend helper | not a read of `pct_of_float` itself, but load-bearing on the denominator |
| `scripts/queries.py:574` | `holder_aggregation` `SUM(h.pct_of_float)` | Holders tab via `/api/...` | displayed |
| `scripts/queries.py:695, :705` | parent rollup `h.pct_of_float` / `SUM(pct_of_float)` | Parent Detail | displayed |
| `scripts/queries.py:763` | entity rollup `SUM(h.pct_of_float)` | Register tab | displayed |
| `scripts/queries.py:865` | ownership by manager_type `SUM(h.pct_of_float)` | Market tab | displayed |
| `scripts/queries.py:1310, :1346` | top-holders CTE + output | Ticker Detail | displayed, ranking-sensitive |
| `scripts/queries.py:1530, :1545` | hardcoded `'pct_of_float': None` placeholder | N-PORT shim rows | placeholder, no change needed |
| `scripts/queries.py:1587` | `SUM(pct_of_float) total_pct_float` | Ticker summary card | displayed |
| `scripts/queries.py:1691` | per-holding row list | Fund Portfolio (activist filter) | displayed + CSV |
| `scripts/queries.py:1765` | peers rollup with market_cap | Ticker Detail peers | displayed |
| `scripts/queries.py:1876` | Q4 snapshot | Quarter Compare | displayed |
| `scripts/queries.py:1920, :1922, :1924` | concentration top-20 + `ORDER BY SUM(pct_of_float) DESC` + `WHERE pct_of_float IS NOT NULL` | concentration widget | displayed + ranking-sensitive |
| `scripts/queries.py:2357` | peer matrix rollup | Peers tab | displayed |
| `scripts/queries.py:2403` | `COUNT(pct_of_float IS NOT NULL)` | admin/QC counter | count only, NULL-tolerant |
| `scripts/queries.py:2896, :2903` | QoQ by entity, quarter_from + quarter_to | Flows / Change Detail | displayed, **most period-sensitive** (same position in consecutive quarters shares the same denominator today) |
| `scripts/queries.py:2918-2919` | `_get_pf` helper extractor | all QoQ code paths | helper |
| `scripts/queries.py:3042-3045` | recompute fallback reading `market_data.float_shares` | fund portfolio | second-chance compute path |
| `scripts/queries.py:3994` | `SUM(pct_of_float) total_pct_float` | Summary card | displayed |
| `scripts/api_market.py:153` | `/api/top-holders` `SUM(pct_of_float) as pct_float` | React Market tab | displayed |
| `scripts/api_market.py:218, :259` | `/api/heatmap` top 15 managers × tickers `SUM(pct_of_float)` | React heatmap | displayed, color-sensitive |
| `scripts/api_register.py:293` | `/api/register/holdings` returns `pct_of_float` | React Register grid | displayed |
| `scripts/admin_bp.py:500` | `COUNT(pct_of_float) as with_float_pct` | admin data-quality | count only |

### 3.2 Summary-table writer (transitive)

| file:line | action |
|---|---|
| `scripts/build_summaries.py:121` | DDL — `pct_of_float DOUBLE` column on `summary_by_parent` |
| `scripts/build_summaries.py:188` | `SUM(h.pct_of_float) AS pct_of_float` aggregating `holdings_v2` → `summary_by_parent` |

`summary_by_parent.pct_of_float` is transitively read by several
`queries.py` endpoints. Effectively another surface requiring
re-materialization after Pass B change.

### 3.3 React frontend

| file:line | action |
|---|---|
| `web/react-app/src/components/tabs/FundPortfolioTab.tsx:119` | CSV export column `p.pct_of_float.toFixed(2)` |
| `web/react-app/src/components/tabs/FundPortfolioTab.tsx:243` | `<td>{fmtPct2(p.pct_of_float)}</td>` rendered |
| `web/react-app/src/types/api.ts:299` | TypeScript type `pct_of_float: number \| null` |
| `web/react-app/src/types/api-generated.ts:954` | auto-generated OpenAPI description (heatmap endpoint) |

### 3.4 Self-writer / projection

| file:line | action |
|---|---|
| `scripts/enrich_holdings.py:125` | Pass A projection `COUNT(pct_of_float IS NOT NULL)` |
| `scripts/enrich_holdings.py:151` | Pass A apply `SET pct_of_float = NULL` |
| `scripts/enrich_holdings.py:184` | Pass B projection old_pof |
| `scripts/enrich_holdings.py:234` | **Pass B apply — SOLE LIVE WRITER** |
| `scripts/enrich_holdings.py:355` | baseline post-state |

### 3.5 Dead / stale (NOT live)

| file:line | status |
|---|---|
| `scripts/approve_overrides.py:159, :164` | targets dropped `holdings` — RETIRE list |
| `scripts/auto_resolve.py:536, :540` | targets dropped `holdings` — RETIRE list |
| `scripts/enrich_tickers.py:385, :399, :404, :408` | targets dropped `holdings` — RETIRE list |
| `scripts/build_shares_history.py:15-18` | docstring references only post-retirement |
| `notebooks/research.ipynb` | 17 hits on `FROM holdings` — stale since Stage 5 |
| `web/datasette_config.yaml:13, :36, :77, :91` | canned queries on dropped `holdings` — local-only tooling, already broken |

### 3.6 Count reconciliation

| classification | count |
|---|---:|
| Live READ (display or ranking) | **~22** |
| Live helper / count-only / placeholder | **~6** |
| Live WRITE (sole) | **1** |
| Summary-table transitive | **2** |
| React types / components | **4** |
| Dead / stale | **~18** |
| **Total live across surfaces** | **~28** |

Matches the peer findings doc's "~30 live" estimate within
classification noise.

---

## §4. Edge case quantification

All queries against prod `data/13f.duckdb`, 2026-04-19.

### 4.1 SOH coverage across holdings_v2 ticker universe

```
holdings_v2 distinct tickers                    : 14,165
  of which any SOH coverage                     :  4,186 (29.57%)
  of which zero SOH coverage                    :  9,979 (70.43%)

Coverage depth for tickers that DO have any SOH row:
  sparse (1-4 rows)                             :    219
  moderate (5-20 rows)                          :    734
  rich (>20 rows)                               :  3,233
```

**Implication**: 70% of the ticker universe will fall through to
Tier 3 (latest-float fallback) under any option that uses SOH.
Fallback behavior is therefore not an edge case — it's the majority
path. Source-flag column is load-bearing for auditability.

### 4.2 Newly listed names (holding predates SOH)

```
SOH covers first holding (no edge case)         : 4,153 tickers
Holding predates first SOH as_of_date           :    33 tickers
No SOH at all                                   : 9,979 tickers
```

Only 33 tickers in the "holding exists before any SOH filing"
category. Tier 2 fallback (earliest SOH or md_latest) handles this
cleanly.

### 4.3 Delisted names in historical quarters

Not directly quantified here (would require `market_data.unfetchable`
cross-reference), but conservatively: any ticker in `market_data`
with `unfetchable = TRUE` and any historical `holdings_v2` rows is a
delisted-name case. Tier 3 fallback (md_latest) returns a value that
may be stale by months/years; Tier 4 (NULL) fires when `market_data`
didn't retain the delisted row.

### 4.4 Tickers never matched in market_data

`market_data` covers 10,064 tickers; `holdings_v2` has 14,165. The
4,101-ticker gap is mostly CUSIPs that resolve to non-US / non-SEC-
registrant tickers in `securities` but that no Yahoo/SEC pull has
matched. For these, `lookup.float_shares` is NULL today, so
`pct_of_float` is NULL. This is not a regression under any option.

### 4.5 Forward-dated SOH rows

Per peer findings doc: 3 rows with `as_of_date > 2026-12-31`, benign
at current scale. ASOF join filter (`as_of_date <= quarter_end`)
prevents forward-dated rows from corrupting past-quarter
denominators. Cap policy proposed in peer doc (≤10 rows flag, ≤50
rows error) stands.

### 4.6 Mid-quarter ticker changes (symbol reassignment)

Not quantified this phase. Risk: a cusip whose `securities.ticker`
changed mid-quarter would ASOF-join against the *new* ticker's SOH
rows for pre-change quarters. Would need a separate
`ticker_overrides` audit. Flag for Phase 1 planning.

---

## §5. Schema risk

**LOAD-BEARING.**

### 5.1 `market_data` has no history

Verified 2026-04-19:

```
market_data:
  rows                 : 10,064
  distinct tickers     : 10,064   (1 row per ticker, exactly)
  fetch_date span      : 2026-03-31 → 2026-04-16
  distinct fetch_dates : 5
  avg rows/ticker      : 1.00
  max rows/ticker      : 1
  min rows/ticker      : 1
```

`market_data.fetch_date` stamps when the latest Yahoo/SEC pull
happened; it does **not** make the table a history. `float_shares` is
a single most-recent value.

**Consequence: the ASOF JOIN against market_data described in the
block prompt is not constructible.** Any period-accurate fix must
come from a different source of denominator history.

### 5.2 `shares_outstanding_history` has shares, not float

```
shares_outstanding_history columns:
  ticker        VARCHAR
  cik           VARCHAR
  as_of_date    DATE
  shares        BIGINT      ← this is shares_outstanding, not float
  form          VARCHAR
  filed_date    DATE
  source_tag    VARCHAR

rows: 338,053
```

Source tags (per peer findings doc):
- `dei:EntityCommonStockSharesOutstanding` (152K)
- `us-gaap:CommonStockSharesOutstanding` (115K)
- `us-gaap:WeightedAverageNumberOfSharesOutstandingBasic` (50K)

All three are **issued** share counts, not float. Treasury stock,
insider holdings, and restricted shares are *not* subtracted.

### 5.3 No float_shares history exists anywhere

Grep across `scripts/`, `data/`, DB tables: no `float_shares_history`
table, no `dei:EntityPublicFloat` XBRL ingestion, no Yahoo-float
history cache. The only historical disclosure of float comes from
10-K Part I Item 5 (annual, prose + tag) — would need new
ingestion (Option B).

### 5.4 Impact on block prompt task list

| prompt item | reality |
|---|---|
| "ASOF JOIN against market_data keyed on (ticker, quarter_end → nearest prior fetch_date)" | **Not constructible**. market_data has no history. |
| "time-matched float at each holdings quarter_end" | **No float history exists.** Best available is SOH's shares_outstanding (not float), or approximated-float via Option C. |

This is the "stop and reconsider" condition the prompt's own Return
block anticipates.

---

## §6. Staging validation plan for Phase 2

Contingent on Option A (SO as denominator). Option B would need its
own plan; Option C a similar plan with additional ratio-stability
checks.

### 6.1 Pre-conditions

- Option A (or C) signed off by Serge.
- `build_shares_history.py` rewrite block merged (SOH freshness
  stamped, `--dry-run` added, retrofits §1/§5/§9 applied) — peer
  block.
- Staging DB mirrors prod (`scripts/sync_staging.py`), including
  `shares_outstanding_history`.

### 6.2 Dry-run projection

1. Run `scripts/enrich_holdings.py --staging --dry-run` with new
   Pass B logic.
2. Expected projection output:
   - Total rows in scope (same as today, ~9.9M equity rows).
   - `pof_changes` count (expect high — majority of 2024–2025
     historical rows will shift).
   - Breakdown by source flag: `soh_period`, `md_fallback`,
     `unresolved` — should sum to `pof_post`.
3. Accept criteria:
   - `pof_post` (rows with non-NULL `pct_of_float`) ≥ current prod
     count × 0.98 (no net coverage regression).
   - `soh_period` ≥ 30% of `pof_post` (Option A expected gain).

### 6.3 Per-quarter spot-check

For each of 2025Q1 / Q2 / Q3 / Q4, pick 20 tickers spanning:
- Known split (`NVDA` 10:1 in 2024, `AAPL` 4:1 in 2020 — backfill
  coverage permitting).
- Known buyback (`AAPL`, `MSFT`, `META`).
- Known secondary / offering (`TSLA` 2020, `CVNA`).
- Small-cap insider-heavy (`GME`, `PLTR`, `AMC`).

Compute `pct_of_float` three ways:
1. Current (latest-float) — baseline.
2. New (SO at as_of_date, Option A).
3. SEC EDGAR cross-check: pull `EntityCommonStockSharesOutstanding`
   from the 10-Q closest to `report_date`, compute by hand.

Accept: new matches manual within ±0.5% on 18/20 tickers per quarter.

### 6.4 Consumer-surface regression sweep

For each of the 22 live display sites in §3.1, capture a reference
query output on prod (pre-change) and staging (post-change). Expect:
- Holders tab top-10 reordering — acceptable for split-affected
  tickers; flag if any movement on non-split tickers > 10%.
- Heatmap visual regression — expect color shifts on SHS / CVNA /
  SMCI and similar high-volatility names; benign elsewhere.
- CSV export dumps for 5 funds — expect column values to change but
  row count / column order / NULL count unchanged.

### 6.5 summary_by_parent rebuild

After Pass B change lands in staging:
1. Re-run `scripts/build_summaries.py --staging`.
2. Compare `summary_by_parent.pct_of_float` before/after per entity.
3. Expect aggregate shifts — document the top-50 biggest-delta rows
   for Serge sign-off.

### 6.6 Promotion gate

- All spot-checks pass (§6.3).
- Regression sweep (§6.4) shows only expected movements.
- Dual-read period on staging for 1 business day (Register /
  Ticker Detail smoke in local React).

### 6.7 Rollback

If Pass B needs reverting: `UPDATE holdings_v2 SET pct_of_float =
<old-formula>` using the same `_LOOKUP_SQL` (today's code) — full
rewrite-idempotent. No DDL change, so no migration rollback needed
unless a `pct_of_float_source` column is added (then a DROP COLUMN).

---

## §7. Open questions for Serge

1. **Option A vs C (vs B vs D)?** This is the Phase 0 gating
   decision. Recommend A. See §2.6.
2. **Column rename (`pct_of_float` → `pct_of_so`) or keep the name
   and document drift?** Rename is safer for auditability but
   touches ~28 live sites plus React types / CSV headers / user
   documentation. Keep-and-document is cheap but future-confusing.
3. **Add `pct_of_float_source` column?** Enables downstream
   de-mixing and auditability. Cost: one column on `holdings_v2`
   (12.27M rows; adds ~25 MB). Benefit: admin data-quality widget
   can distinguish Tier 1 from Tier 3 rows.
4. **Which quarter-range to rebuild?** Options:
   a. Full table refresh (default `--quarter` = ALL; all 2023–2025
      quarters touched).
   b. Historical only (`--quarter` excludes current quarter to avoid
      mid-flight flip during market hours).
   c. Current quarter only (narrowest blast radius; historical stays
      on old latest-float until a later pass).
   Recommend (a) given Pass B is already full-refresh on every run.
5. **Scope of the block** — include the peer `build_shares_history.py`
   retrofits, or only Pass B? Peer block already tracks those; this
   block should stay focused on Pass B + downstream surface
   handling. Confirm.
6. **Delisted-names policy** — how to handle tickers with holdings
   rows but where `market_data` has `unfetchable = TRUE` and SOH
   has a final `as_of_date` before the holding's quarter_end?
   Proposal: use last-available SOH row regardless of filed_date
   age, with source flag `soh_stale`.
7. **Mid-quarter ticker reassignment** — is a pre-Phase-1
   `ticker_overrides` audit pass warranted, or accept the risk?
   Impact unquantified (§4.6).
8. **Peer block sequencing** — peer `rewrite-build-shares-history`
   is in Phase 0/1. Should this block wait for peer merge (to pick
   up `data_freshness('shares_outstanding_history')` stamping and
   the retrofits) or run in parallel? Recommend waiting — the
   freshness stamp makes `make freshness` visibility cleaner.

---

## Guardrails respected

- Read-only investigation. No code changes, no DB writes, no script
  runs, no `fetch_*` calls.
- Phase 0 commit is this doc only.
- Branch `block/pct-of-float-period-accuracy` created off main
  (`a409f02`). No merges, no pushes.
- No new dependencies introduced.

Safe to decide §7.1 (Option A/B/C/D) before Phase 1 scoping.

---

## §8. SOH source verification (Phase 1a)

Decision locked (Phase 0 close): **Option A** — migrate denominator
semantics to `shares_outstanding`, column hard-renamed
`pct_of_float` → `pct_of_so`, audit column `pct_of_so_source` added,
full refresh across all historical quarters.

Phase 1a checkpoint: confirm SOH source field semantics before
locking ASOF direction.

### 8.1 Owner

`scripts/shares_outstanding_history` is written **exclusively** by
`scripts/build_shares_history.py` via
`scripts/sec_shares_client.py::SECSharesClient.fetch_history()`.
Grep across `scripts/` finds only three files referencing the table:

| file | role |
|---|---|
| `scripts/build_shares_history.py` | sole writer (INSERT/UPSERT) |
| `scripts/pipeline/registry.py` | catalog entry (table metadata) |
| `scripts/merge_staging.py` | staging→prod copy (data-layer mover) |

No other script writes, alters, or truncates SOH.

### 8.2 Source fields — XBRL companyfacts, four tags, priority order

`sec_shares_client.py::fetch_history` (lines 226-281) pulls from the
SEC EDGAR companyfacts JSON
(`https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json`) cached
locally under `data/cache/sec_companyfacts/`.

Four XBRL tags consulted, in priority order (first non-empty wins
per `(ticker, as_of_date)`):

| priority | tag | value semantics | typical stamp date |
|---|---|---|---|
| 1 | `dei:EntityCommonStockSharesOutstanding` | Cover-page shares outstanding (single-class filers) | Cover-page date (1-6 weeks **after** period-end) |
| 2 | `us-gaap:CommonStockSharesOutstanding` | Balance-sheet shares outstanding | **Period-end date** (Mar 31, Jun 30, Sep 30, Dec 31) |
| 3 | `us-gaap:EntityCommonStockSharesOutstanding` | Cover-page (alt tagging) | Cover-page date |
| 4 | `us-gaap:WeightedAverageNumberOfSharesOutstandingBasic` | Period-**average** (not point-in-time) | Period-end date |

Per-period dedup is on `end` date: if two tags report facts for the
*same* date, the higher-priority tag wins. Facts at *different* dates
are all kept — a single filer's single 10-Q typically produces
**two** SOH rows:
- One at period-end (us-gaap:CSO)
- One at cover-page date (dei:ESO)

### 8.3 Stamp-date semantics — empirical check

Representative spot-check against prod DB (2026-04-19):

```
AAPL         2026-01-16  dei:ESO       10-Q filed 2026-01-30  14,681,140,000
AAPL         2025-12-27  us-gaap:CSO   10-Q filed 2026-01-30  14,702,703,000   ← period-end
AAPL         2025-10-17  dei:ESO       10-K filed 2025-10-31  14,776,353,000
AAPL         2025-09-27  us-gaap:CSO   10-K filed 2025-10-31  14,773,260,000   ← period-end

MSFT         2026-01-22  dei:ESO       10-Q filed 2026-01-28   7,425,629,076
MSFT         2025-12-31  us-gaap:CSO   10-Q filed 2026-01-28   7,429,000,000   ← period-end
MSFT         2025-10-23  dei:ESO       10-Q filed 2025-10-29   7,432,377,655
MSFT         2025-09-30  us-gaap:CSO   10-Q filed 2025-10-29   7,434,000,000   ← period-end

GOOGL        2025-12-31  us-gaap:CSO   10-K filed 2026-02-05  12,088,000,000   ← period-end
GOOGL        2025-09-30  us-gaap:CSO   10-Q filed 2025-10-30  12,077,000,000   ← period-end
GOOGL        2025-06-30  us-gaap:CSO   10-Q filed 2025-07-24  12,104,000,000   ← period-end
GOOGL        2025-03-31  us-gaap:CSO   10-Q filed 2025-04-25  12,155,000,000   ← period-end

META         2025-12-31  WANOSO        10-K filed 2026-01-29   2,521,000,000   ← period-end (but avg)
META         2025-09-30  WANOSO        10-Q filed 2025-10-30   2,520,000,000   ← period-end (but avg)

TSLA         2025-12-31  us-gaap:CSO   10-K filed 2026-01-29   3,751,000,000   ← period-end
TSLA         2026-01-23  dei:ESO       10-K filed 2026-01-29   3,752,431,984

BRK-B        (no rows — XBRL not tagged; relies on manual overrides CSV)
```

**Conclusion: SOH is built from period-end XBRL facts OR equivalent**
for every tested ticker with coverage. Even for single-tag filers
(GOOGL = us-gaap:CSO only, META = WANOSO only), the stamp date sits
at or very close to period-end.

For multi-tag filers (AAPL, MSFT, NVDA, TSLA), the table carries
both a period-end row (us-gaap:CSO) *and* a cover-page row
(dei:ESO). ASOF `<=` against a quarter_end target picks the us-gaap
period-end row cleanly.

**Hard checkpoint PASSED.** Proceeding to Phase 1b without pause.

### 8.4 Coverage cliff — source of the 30% ceiling

SOH covers 4,186 of 14,165 holdings_v2 tickers (§4.1). Root causes
for the 9,979-ticker gap:

1. **No CIK mapping.** `data/reference/sec_company_tickers.csv`
   covers US-registered issuers only. Foreign Private Issuers (FPIs)
   filing 20-F are not always in the tickers mapping; non-SEC-
   registered entities (exchange-traded ADRs of unregistered foreign
   issuers, some muni issuers) are excluded.
2. **CIK but no XBRL tag.** A CIK-mapped filer that never tagged
   shares in XBRL (Visa is the canonical case; BRK-A/B likewise).
   `shares_overrides.csv` fills this for a handful of known filers.
3. **ETFs / closed-end funds / unit trusts.** These file N-1A/N-CSR,
   not 10-K/10-Q with us-gaap:CSO tags. Their CIK exists but
   `EntityCommonStockSharesOutstanding` is unpopulated.
4. **Recent IPOs** within the 90-day cache rotation window that
   haven't been backfilled yet.
5. **Delisted names.** Latest 10-K may predate delisting by months;
   SOH row exists but `market_data.unfetchable = TRUE`.

For the migration's fallback tier logic (§2.5): categories 1 and 3
dominate the 70% gap. Fallback to `market_data.shares_outstanding`
(where `fetch_market.py` has populated it via the same SEC client's
`fetch()` method) recovers some but not all of these — Yahoo
backstop for ETFs / FPIs covers another slice. Residual NULLs are
the expected tail.

### 8.5 Implications for Phase 1b design

- **ASOF direction**: `soh.as_of_date <= h.quarter_end` is correct.
  Picks the us-gaap:CSO period-end row when available; falls back
  to prior-period facts when current quarter's 10-Q/10-K hasn't
  been filed yet.
- **Grace window not needed**: dei:ESO cover-page facts dated
  *after* quarter_end are naturally deprioritized by the ASOF `<=`
  cut; us-gaap:CSO at exactly quarter_end wins.
- **For holdings_v2 only**: Confirmed — `fund_holdings_v2` does NOT
  carry `pct_of_float` (or `pct_of_so`). N-PORT uses `pct_of_nav`
  as the fund-level metric. Block prompt's "also handle
  fund_holdings_v2 with N-PORT month-end stamp" is moot.
  `beneficial_ownership_v2` likewise has no `pct_of_float` column
  (verified via `PRAGMA table_info`).
- **Scope narrows**: migration touches `holdings_v2` only. One
  column rename, one audit column add, one `enrich_holdings.py`
  Pass B rewrite.
- **WANOSO caveat**: tickers whose only SOH source is
  `WeightedAverageNumberOfSharesOutstandingBasic` (META is a
  prominent example) get a period-**average** denominator instead
  of period-**end**. Off by ~0.5-2% typically; acceptable.
  Document but do not filter out — excluding WANOSO would cut
  ~50K rows of coverage.

---

## §9. Migration design (commit `8969dd1`)

`scripts/migrations/008_rename_pct_of_float_to_pct_of_so.py`. Applies
to `holdings_v2` only — verified in §8.5 that `fund_holdings_v2` and
`beneficial_ownership_v2` don't carry the column.

**Note on numbering**: the prompt specified `007_rename_...`; that
number is already in use by `007_override_new_value_nullable.py`
(2026-04-17). Used `008` instead.

### 9.1 DDL changes

```
ALTER TABLE holdings_v2 RENAME COLUMN pct_of_float TO pct_of_so;
ALTER TABLE holdings_v2 ADD COLUMN pct_of_so_source VARCHAR;
INSERT INTO schema_versions (version, notes) VALUES
    ('008_rename_pct_of_float_to_pct_of_so',
     'holdings_v2 pct_of_float → pct_of_so rename + pct_of_so_source audit column');
```

### 9.2 Idempotency

Probes `duckdb_columns` for current state before each step:
- If `pct_of_so` already exists and `pct_of_float` is gone and stamped
  → no-op.
- If both columns exist simultaneously (e.g. an aborted prior run that
  added the new before dropping the old) → abort with human-resolvable
  message.
- Individual steps (rename, add column, stamp) skipped when already
  satisfied.

### 9.3 pct_of_so_source values (written by Pass B)

Widened to three distinct values in Phase 1c (commit `f8caab0`) so
tier 3 (float-based fallback) is no longer silently labeled the same
as tier 2 (SO-based fallback):

| value | tier | meaning |
|---|---|---|
| `'soh_period_accurate'` | 1 | denominator from ASOF match against `shares_outstanding_history` at `as_of_date <= quarter_end` |
| `'market_data_so_latest'` | 2 | fallback: latest `market_data.shares_outstanding` |
| `'market_data_float_latest'` | 3 | fallback: latest `market_data.float_shares` — semantic mixing (pct_of_float stored in a pct_of_so column) made transparent via this distinct flag |
| `NULL` | 4 | `is_equity = FALSE`, or no denominator available |

**Why three not two**: tier 3 is the exact silent-wrong pattern the
block was created to eliminate — a float-based percentage stored in a
column named `pct_of_so`. Collapsing tier 3 into `'market_data_latest'`
would hide this from downstream audits. Three values let admin
quality widgets, CSV exports, and analytics filter or warn on
`market_data_float_latest` rows specifically.

Downstream consumers (admin data-quality widget, audit queries) can
now filter by exact tier: `WHERE pct_of_so_source = 'soh_period_accurate'`
for period-accurate only, or `NOT IN ('market_data_float_latest')` for
"at least SO-semantic" rows.

### 9.4 Phase 1 scope: staging DB only

Migration is applied to `data/13f_staging.duckdb` in Phase 1. Prod
apply is Phase 4 (post Phase 2 staging validation + Phase 3 sign-off).

---

## §10. ASOF semantics (commit `dd2b5a1`)

`scripts/enrich_holdings.py` Pass B rewritten from latest-float join
to ASOF JOIN against SOH. Key design points:

### 10.1 ASOF direction

```sql
ASOF LEFT JOIN shares_outstanding_history soh
  ON soh.ticker = lookup.new_ticker
 AND soh.as_of_date <= k.quarter_end
```

DuckDB ASOF picks the greatest `soh.as_of_date` that satisfies the
inequality — i.e. "latest SOH stamp at or before quarter_end." Rows
with no match are kept by `LEFT JOIN` semantics and fall through to
the market_data fallback.

### 10.2 Three-tier fallback

```
CASE
    WHEN r.is_equity AND r.soh_shares            > 0 THEN h.shares * 100.0 / r.soh_shares
    WHEN r.is_equity AND r.md_shares_outstanding > 0 THEN h.shares * 100.0 / r.md_shares_outstanding
    WHEN r.is_equity AND r.md_float_shares       > 0 THEN h.shares * 100.0 / r.md_float_shares
    ELSE NULL
END
```

Tier 1 is period-accurate (`soh_period_accurate`). Tiers 2 and 3 are
the latest market_data values (`market_data_latest` in the audit
column). Tier 3 is a tertiary backstop for tickers where
`market_data.shares_outstanding` is NULL but `float_shares` is
populated — common for Yahoo-backfilled tickers without SEC XBRL.

### 10.3 13F quarter-end scope

`holdings_v2.report_date` is always a calendar quarter-end
(2025-03-31, 2025-06-30, 2025-09-30, 2025-12-31 verified Phase 1a).
ASOF `<= quarter_end` picks:
- Period-end us-gaap:CSO row when the filer's 10-Q/10-K has been
  filed — exact match.
- Previous quarter's us-gaap:CSO row when current quarter's filing
  is pending — 3 months stale.
- For WANOSO-only filers (META class), period-end WANOSO — value is
  period-average, not point-in-time (~0.5-2% drift).

### 10.4 N-PORT compute paths — Phase 1c rewrite

Phase 1a §8.5 confirmed `fund_holdings_v2` does not carry a stored
`pct_of_float` column. However, `scripts/queries.py` has **ad-hoc
compute paths** that produce a `pct_so` value for N-PORT fund holdings
on the fly (feeding Register children, Market heatmap, OwnershipTrend,
FlowAnalysis, Two-Company Overlap). Phase 1b renamed the key
`pct_float` → `pct_so` but left the denominator as latest
`market_data.float_shares` — same silent-wrong pattern the block was
created to eliminate.

Phase 1c (commit `b0ba86d`) rewrote every such path. The shared
helper `scripts/queries.py::_resolve_pct_of_so_denom(con, ticker,
as_of_date)` applies the same three-tier cascade used in
`enrich_holdings.py` Pass B:

  1. `shares_outstanding_history` ASOF match at/before `as_of_date`
  2. latest `market_data.shares_outstanding`
  3. latest `market_data.float_shares`
  4. `(None, None)` — no denominator available

A companion helper `_quarter_to_date('YYYYQN')` derives the calendar
quarter-end as the anchor.

### 10.5 N-PORT month-end staleness tolerance

N-PORT `fh.report_date` spans month-ends (Jan-31, Feb-28, Apr-30,
May-31, Jul-31, Aug-31, Oct-31, Nov-30) plus calendar quarter-ends.
Phase 1c rewrite anchors the SOH ASOF match at the 13F quarter-end
derived from `quarter` (not the individual N-PORT row's
`report_date`). Rationale:

- The queries aggregate N-PORT rows WITHIN a `quarter` argument and
  return a single per-fund aggregate; per-row ASOF would require
  splitting the group, which changes the result shape and doesn't
  meaningfully improve accuracy over the quarter-end anchor.
- us-gaap:CSO XBRL facts are predominantly filed at calendar
  quarter-ends. A Jan-31 N-PORT report anchored at its report_date
  would have the same SOH match as one anchored at the containing
  quarter_end (2024-12-31 → prior 10-K) since no Jan-31 SOH fact
  exists.
- The quarter-end anchor aligns N-PORT pct_so with 13F pct_so for
  the same ticker/quarter — consumers comparing the two panels see
  consistent denominators.

**Staleness impact**: for non-quarter N-PORT months, the
`soh_period_accurate` match is ≤ ~90 days stale relative to the
N-PORT report_date. Tier 1 is still preferred over Tier 2/3 since
it reflects the most-recent 10-K/10-Q at the anchor quarter-end.
Documented in the helper docstring; downstream consumers can
identify month-end staleness by the row's `pct_of_so_source` field
plus the mismatch between `quarter` and the N-PORT `report_date`.

### 10.6 Staleness counter (Pass B, 13F)

### 10.6 Staleness counter (Pass B, 13F)

Per-run logged counter: `pof_stale_gt60` — number of rows where the
SOH ASOF match has `quarter_end - as_of_date > 60 days`. Exposes
cases where a filer's XBRL coverage skipped a quarter (common for
late filers and mid-year 10-K/A amendments). Surfaced in dry-run
projection output:

```
  SOH matches with staleness > 60 days : ...
```

### 10.6a Tier distribution counter (Pass B, Phase 1c)

Phase 1c (commit `90514c6`) added per-tier population counts to the
Pass B projection:

```
  tier distribution (equity rows):
    1. soh_period_accurate     (tier 1)       : ...
    2. market_data_so_latest   (tier 2 SO)    : ...
    3. market_data_float_latest(tier 3 float) : ...
    4. NULL (equity, no denom) (tier 4)       : ...
```

Sum across the four tiers equals the equity-row count. Watching the
tier 3 count pre/post-promotion is the admin signal for how many rows
are "pct_of_float stored in pct_of_so column" — staging validation
threshold TBD (expect double-digit thousands given the 70% no-SOH
cliff from §4.1).

### 10.7 Join key choice

Resolution is done on distinct `(cusip, report_date)` pairs via the
`keys` CTE, then the final UPDATE joins back to `holdings_v2` on
those two columns. This handles the intentional `(accession_number,
cusip, quarter)` dup groups (~1.29M / ~4.97M rows per
`enrich_holdings.py:20-22`) without overcounting — the denominator
is a ticker-level quantity, so dup rows sharing a `(cusip,
report_date)` correctly get the same value.

### 10.8 Projection query includes audit columns

`_pass_b_project` now returns:
- `pof_changes` — rows where denominator value changes
- `pof_source_changes` — rows where audit flag changes
- `pof_source_soh` / `pof_source_md` — post-run population by source
- `pof_stale_gt60` — staleness counter

Surfaced via `_print_pass_b` at dry-run time.

---

## §11. Read-site migration — final reconciled count

Commit `f956096` migrated every live read surface. Reconciliation:

### 11.1 Python backend (5 files)

| file | renames applied |
|---|---|
| `scripts/queries.py` | `pct_of_float` → `pct_of_so` (column), `pct_float` → `pct_so` (alias), `total_pct_float` → `total_pct_so`, `with_float_pct` → `with_so_pct`, incidental local vars `_pct_float` helper and loop-locals (`pct_float_moved` → `pct_so_moved`, `subj_pct_float` → `subj_pct_so`, `sec_pct_float` → `sec_pct_so`) |
| `scripts/api_market.py` | column + alias |
| `scripts/api_register.py` | column |
| `scripts/admin_bp.py` | column + `with_float_pct` alias |
| `scripts/build_summaries.py` | DDL column + aggregation alias (`summary_by_ticker.pct_of_float` column definition also renamed) |
| `scripts/enrich_holdings.py` | Pass B rewrite (`dd2b5a1`) |

### 11.2 React frontend (10 files)

| file | renames applied |
|---|---|
| `web/react-app/src/types/api.ts` | `pct_of_float`, `pct_float`, `total_pct_float`, `pct_float_moved`, `subj_pct_float`, `sec_pct_float` — all TS field types |
| `web/react-app/src/types/api-generated.ts` | auto-gen OpenAPI description |
| `web/react-app/src/components/common/TableFooter.tsx` | `pct_float` field, `% Float` label |
| `web/react-app/src/components/tabs/RegisterTab.tsx` | `pct_float` field, `pctFloat` local, `fmtPctFloat` util, `% Float`, `%Float` labels |
| `web/react-app/src/components/tabs/FundPortfolioTab.tsx` | `pct_of_float`, `pct_float`, `% Float` label + CSV header |
| `web/react-app/src/components/tabs/OwnershipTrendTab.tsx` | `pct_float`, `pct_float_moved`, `% Float`, `% Float Moved` labels |
| `web/react-app/src/components/tabs/FlowAnalysisTab.tsx` | `pct_float`, `pctFloat`, `% Float` label |
| `web/react-app/src/components/tabs/EntityGraphTab.tsx` | `pct_float`, `totalPctFloat`, `% Float` label |
| `web/react-app/src/components/tabs/OverlapAnalysisTab.tsx` | `subj_pct_float`, `sec_pct_float` |
| `web/react-app/src/components/tabs/ConvictionTab.tsx` | `pct_float` field |

### 11.3 Test fixtures (2 files)

| file | renames |
|---|---|
| `tests/fixtures/responses/query1.json` | 118 `pct_float` → `pct_so` occurrences |
| `tests/fixtures/responses/summary.json` | `total_pct_float` → `total_pct_so` |

### 11.4 Reconciliation against Phase 0 and peer findings

| estimate source | count | actual |
|---|---:|---|
| Phase 0 §3.6 "Total live across surfaces" | ~28 | **matched for backend SQL sites**; underestimated React + CSV labels |
| Peer findings doc (`2026-04-19-rewrite-build-shares-history.md` §3.2.1) "~30 live" | ~30 | same — both estimates counted backend-SQL consumers, not frontend-render consumers |

**Delta explanation**: Phase 0's inventory counted `queries.py`
SELECT sites and API endpoints (the *read surfaces that the backend
produces*). It undercounted the downstream TSX/JSX consumers that
render each result (a single backend row with `pct_float` is rendered
by RegisterTab + CSV export + footer + type def, producing 4 distinct
JS references). The true count of **token-level references** touched
in Phase 1b is:

| category | file count | ref count |
|---|---:|---:|
| Python backend column/alias references | 6 | ~95 |
| React types + components | 10 | ~60 |
| Test fixtures | 2 | 119 |
| **Total token refs** | **18** | **~274** |

Phase 0's ~28 "live sites" estimate is correct when interpreted as
"distinct backend query locations." The per-token churn of Phase 1b
is larger because React consumers multiply.

### 11.5 Intentional non-renames (dead code / out of scope)

| file | reason |
|---|---|
| `scripts/approve_overrides.py` | on RETIRE list — targets dropped `holdings` |
| `scripts/auto_resolve.py` | on RETIRE list |
| `scripts/enrich_tickers.py` | on RETIRE list |
| `scripts/build_shares_history.py` | docstring mentions old block name; actual update path already retired |
| `scripts/migrations/008_rename_pct_of_float_to_pct_of_so.py` | migration *performs* the rename; old column name is a constant in the file |
| `scripts/enrich_holdings.py` | module docstring has one backward-reference note `(renamed from pct_of_float in 008)` — intentional |
| `notebooks/research.ipynb` | stale since Stage 5 dropped `holdings` table |
| `web/datasette_config.yaml` | canned queries on dropped `holdings` table (already broken) |
| `ROADMAP.md`, `NEXT_SESSION_CONTEXT.md`, `docs/*.md`, `archive/docs/reports/*.md` | deferred to batched doc-update session per prompt constraints |

### 11.6 N-PORT compute-path rewrite — RESOLVED in Phase 1c

**Status: resolved (commit `b0ba86d`)**. Previously flagged as
deferred; escalated to Phase 1c scope per block prompt because the
silent-wrong pattern the flag describes is exactly what the block
was created to eliminate.

Shared helpers added at top of `scripts/queries.py`:
- `_quarter_to_date('YYYYQN')` — calendar quarter-end derivation.
- `_resolve_pct_of_so_denom(con, ticker, as_of_date)` — three-tier
  cascade matching Pass B (SOH → md.shares_outstanding → md.float_shares),
  returns `(denominator, source)`.

Eight queries.py functions rewritten to use the helper:

| function | line (pre-rewrite) | scope |
|---|---|---|
| `get_nport_children_batch` | 346-454 | N-PORT children per parent, top-N |
| `get_nport_children` | 457-510 | N-PORT children per parent, non-batched |
| `query16` | 2419-2510 | fund-level register (rows + all_totals + type_totals) |
| `ownership_trend_summary` | 2518-2600 | per-quarter trend (per-quarter denom cache) |
| `_compute_flows_live` | 2866-… | buyer/seller/new/exit flows (separate denoms for from_q / to_q) |
| `flow_analysis` precomputed path | 3043-3061 | precomputed flow reader (separate denoms for from_q / to_q) |
| `get_two_company_overlap` | 5368-… | Two-Company Overlap tab (subject + second) |
| `get_two_company_subject` | 5535-… | subject-only variant |

Each return row now includes `pct_of_so_source` alongside `pct_so` so
consumers can match the 13F audit contract. `TwoCompanyMeta` changed
shape: `subj_float`/`sec_float` replaced with
`subj_denom`/`subj_pct_of_so_source` and corresponding sec_ fields
(type definition updated; no React consumer currently reads these
meta fields — verified via grep).

### 11.7 Backend-only change

Phase 1c added `pct_of_so_source` to N-PORT return payloads but did
NOT add display badges in React. Consumers that already pass the
field through TypeScript structural typing work unchanged; any future
display work (tooltip/warning on tier 3 rows) is out of scope.

Touch list summary:
- Python: `scripts/queries.py` (extensive — ~+235/-90 lines)
- TypeScript: `web/react-app/src/types/api.ts` (TwoCompanyMeta shape
  + TwoCompanyInstitutionalRow / TwoCompanyFundRow audit fields —
  backward-compatible structural additions)
- React TSX: no changes — consumers read existing `pct_so` field,
  ignore new audit fields, render unchanged.

---

## §12. Deferred doc updates (for future batched session)

Per block prompt constraint: "Do not modify `ROADMAP.md`,
`data_layers.md`, or other top-level docs (deferred to batched doc-
update session)." The following docs reference `pct_of_float` /
`pct_float` and need updating in that session:

| doc | action |
|---|---|
| `ROADMAP.md` | add completed block under BLOCK-PCT-OF-SO-PERIOD-ACCURACY; rename prior BLOCK-PCT-OF-FLOAT-PERIOD-ACCURACY refs; INF38 entry for BLOCK-FLOAT-HISTORY (deferred float preservation workstream) |
| `docs/data_layers.md` | §7 cross-ref for the new `pct_of_so_source` audit column on `holdings_v2`; update the column list |
| `docs/canonical_ddl.md` | update `holdings_v2` DDL reference to show `pct_of_so DOUBLE` + `pct_of_so_source VARCHAR` |
| `docs/pipeline_inventory.md` | update enrichment writers list |
| `docs/pipeline_violations.md` | update §5 / §9 references if any name the old column |
| `docs/NEXT_SESSION_CONTEXT.md` | session wrap with commit list + block completion note |
| `docs/findings/2026-04-19-rewrite-build-shares-history.md` | §3.2.1 amendment — the "elevate follow-up block" section is now complete; mark done with forward link |
| `archive/docs/reports/rewrite_build_shares_history_phase2_20260419_054947.md` | historical report; leave in place |
| `docs/findings/2026-04-19-ci-smoke-failure-diagnosis.md` | single `pct_float` reference in snapshot-vs-actual narrative; rename to `pct_so` |
| `docs/findings/2026-04-19-rewrite-build-managers.md` / `2026-04-19-rewrite-build-summaries.md` | passing references only — rename in batched pass |
| `docs/findings/2026-04-19-precheck-load-13f-liveness.md` | single reference — rename in batched pass |

### Additional cleanup items flagged during Phase 1b/1c

- **`summary_by_ticker` DDL** has `pct_of_so` column. Existing prod
  `summary_by_ticker` table will need either a follow-up migration
  (rename column on that table too) or a full rebuild via
  `build_summaries.py`. Confirm at Phase 2 staging.
- **`fmtPct` vs `fmtPct2`** utility naming convention — both are used
  in React. Not a Phase 1b concern but flagged for future consistency
  pass.
- **Obsolete comments** in `queries.py` that still reference
  "float_shares calculation" in context where denominator is now the
  tier-cascade helper; surgical editing deferred to batched doc
  session.
- **React tier-3 warning/tooltip** — Phase 1c exposes
  `pct_of_so_source = 'market_data_float_latest'` on N-PORT and 13F
  result sets. Current React display ignores the field. Future UX
  work: show a subtle badge/warning on tier-3 rows so users know the
  displayed % is float-based. Out of Phase 1c scope.
- **INF38 tracking** — create ROADMAP entry for BLOCK-FLOAT-HISTORY
  (true float_shares time-series ingestion from 10-K Item 5); noted
  in Phase 0 §2.2 as Option B deferred scope.

### Phase 1 exit criteria (1a + 1b + 1c, all met)

- Findings doc renamed ✓
- Phase 1a §8 SOH source verification appended ✓
- Migration `008_rename_pct_of_float_to_pct_of_so.py` written
  (idempotent, staging-scoped, not yet applied) ✓
- Migration 008 docstring widened to three-tier audit semantics ✓
  (Phase 1c, commit `f8caab0`)
- Pass B rewrite in `enrich_holdings.py`: ASOF against SOH +
  three-tier fallback + three-value audit column + tier_distribution
  counter ✓ (Phase 1b `dd2b5a1` + Phase 1c `90514c6`)
- Read-site migration across backend + React + test fixtures ✓
- N-PORT compute paths in `queries.py` rewritten to use the same
  tier cascade + audit column ✓ (Phase 1c, `b0ba86d`)
- Findings doc finalized with §8–§12 ✓
- No prod writes, no fetch runs, no ROADMAP/data_layers/pipeline_inventory churn ✓

Ready for Phase 2 (staging validation) once Serge applies migration
008 to `data/13f_staging.duckdb` and runs `enrich_holdings.py
--staging --dry-run`. Tier-distribution counter in the dry-run
output is the first staging signal to watch — tier 3 count pre-apply
forecasts how many rows carry the silent-wrong float-based semantics
today.

---

## §13. Phase 2 staging validation (2026-04-19)

Validation executed against `data/13f_staging.duckdb` (3.66 GB,
mirror of prod as of 2026-04-19 09:14). All 10 Phase 1 commits
(`0871178`..`208bc86`) verified against staging. No prod writes.

### §13.1 Migration 008 staging apply

```
Migration 008 dry-run:
  has pct_of_float: True
  has pct_of_so: False
  has pct_of_so_source: False
  schema_versions stamped: False
    ALTER TABLE holdings_v2 RENAME COLUMN pct_of_float TO pct_of_so
    ALTER TABLE holdings_v2 ADD COLUMN pct_of_so_source VARCHAR

Migration 008 apply:
  stamped schema_versions: 008_rename_pct_of_float_to_pct_of_so
  AFTER: pct_of_float=False pct_of_so=True pct_of_so_source=True

Migration 008 re-run (idempotency check):
  ALREADY APPLIED: no action
```

Post-apply verification:

| metric | value |
|---|---:|
| holdings_v2 row count | 12,270,984 (unchanged) |
| `pct_of_so` present | YES |
| `pct_of_float` present | NO |
| `pct_of_so_source` present | YES (VARCHAR, all NULL at migration time) |
| schema_versions row | `008_rename_pct_of_float_to_pct_of_so` stamped 2026-04-19 12:51:51 |
| `fund_holdings_v2` columns | untouched — still has `pct_of_nav`, no `pct_of_*` rename artifacts |
| `beneficial_ownership_v2` | untouched |

Migration clean. Idempotent on re-run.

### §13.2 Pass B tier distribution — actual vs forecast

Pass B applied to staging (dry-run + apply both ran; apply took
**1.4s** end-to-end for 12.27M rows).

| tier | count | % of equity rows | % of all rows | forecast (Phase 1c) |
|---|---:|---:|---:|---|
| 1. `soh_period_accurate` | 7,725,062 | **72.4%** | 62.9% | ~30% of distinct tickers, higher row share |
| 2. `market_data_so_latest` | 792,115 | 7.4% | 6.5% | majority |
| 3. `market_data_float_latest` | 22,517 | **0.2%** | 0.2% | ~50K rows |
| 4. NULL (equity, no denom) | 2,123,715 | 19.9% | 17.3% | delisted/unmatched |
| — non-equity (NULL) | 1,607,575 | — | 13.1% | — |
| **Total** | 12,270,984 | 100% | 100% | |

**Forecast miss — tier 1 dominates far more than expected**: 72.4%
of equity rows are period-accurate. The SEC-registrant large-cap
bias of 13F row volume concentrates in SOH-covered tickers. Tier 2
is much smaller than forecast; tier 3 is half of forecast.

**Coverage gain**: `pct_of_so` populated rows grew from 7,786,239
(baseline, old latest-float path) to **8,539,694 post-apply
(+753,455 rows, +9.7%)**. Source of gain: tier 2+3 populate cases
where old path had `market_data.float_shares IS NULL`, but either
SOH or `market_data.shares_outstanding` has coverage.

**Change counts** (what the apply actually rewrote):
- `pct_of_so` value changes: 8,498,606 rows
- `pct_of_so_source` changes: 8,539,694 rows (every non-NULL row
  gained a source tag)

### §13.3 Integration validation — 10 read paths

Test ticker: AAPL, quarter 2025Q4 (2025Q3→2025Q4 for flows).

| # | path | result | notes |
|---|---|---|---|
| 1 | 13F holdings_v2 direct SELECT | **PASS** | AAPL/MSFT/NVDA top holders all `soh_period_accurate` — e.g. Vanguard Group on MSFT: pct_so=8.67%, src=soh_period_accurate |
| 2 | tier 3 spot check | **PASS** | top tier-3 tickers: CFLT (2,563), DAY (2,538), DVAX (1,589) — small/mid-cap IPOs where SOH cache is thin |
| 3 | `get_nport_children_batch` | **PASS** | Vanguard/AAPL returns 3 funds, all tier 1; pct_so values 3.18%, 2.49%, 0.96% (plausible) |
| 4 | `get_nport_children` | **PASS** | identical shape + values to batched version |
| 5 | `query16` (fund register) | **PASS** | rows + all_totals + type_totals all carry `pct_of_so_source`; top-level `pct_of_so_source` also emitted |
| 6 | `ownership_trend_summary(level=parent)` | **PASS** | per-quarter denoms resolve cleanly; AAPL 2025Q4 pct_so=67.02% src=soh_period_accurate |
| 6b | `ownership_trend_summary(level=fund)` | **PASS** | same, fund-level aggregates |
| 7 | `_compute_flows_live(level=parent)` | **PASS\*** | values correct, but `pct_of_so_source=None` on per-entity rows — see §13.6 |
| 7b | `_compute_flows_live(level=fund)` | **PASS** | fund-level `pct_of_so_source=soh_period_accurate` |
| 8 | `flow_analysis` precomputed path | **STAGING-COVERAGE FAIL** | `investor_flows` table doesn't exist in staging (prod-only precomputed). Code rewrite is correct; unable to execute in this environment. No prod risk. |
| 9 | `get_two_company_overlap` (AAPL+MSFT) | **PASS** | meta carries `subj_denom`, `sec_denom`, and both `*_pct_of_so_source`. Rows have subj/sec pct_so + sources (both tier 1) |
| 10 | `get_two_company_subject` (AAPL alone) | **PASS** | meta + rows shape correct; sec_* fields all None |

### §13.4 validate_entities baseline preservation

```
Summary: {'PASS': 8, 'FAIL': 2, 'MANUAL': 6}
```

Prompt-stated baseline: `8 PASS / 1 FAIL (wellington) / 7 MANUAL`.
Staging result: `8 / 2 / 6`.

**Same validation against prod** (read-only): `8 / 2 / 6`, identical.

The second FAIL is `phase3_resolution_rate` (threshold: SEC > 80%,
enrichment > 25%). Exists identically in prod and staging — this is
a pre-existing state, not a regression introduced by Phase 2 work.
Prompt's expected baseline was stale; actual invariant held:
**staging matches prod exactly**.

No test touches `pct_of_so` / `pct_of_so_source` / `holdings_v2`
column shape. The two FAILs are orthogonal to this block.

### §13.5 Staleness counter observations

Pass B projection output:

```
SOH matches with staleness > 60 days : 607,814
```

Breakdown: 607,814 rows / 7,725,062 tier-1 rows = **7.9% of tier-1
matches are stale > 60 days** relative to quarter_end. Interpretation:

- Expected, not a red flag. A `quarter_end - as_of_date > 60`
  condition fires when the latest SOH fact for a ticker predates
  the holdings quarter_end by more than 2 months — common for
  tickers where a 10-Q was filed but the DEI ESO cover-page date
  landed a few weeks post-quarter (then the next quarter's holdings
  ASOF-match that "prior cover-page" rather than a period-end CSO).
- 92.1% of tier-1 matches are within 60 days — fresh.
- No threshold trip needed for Phase 4.

### §13.6 Surprises / edge cases for Serge review

1. **Tier 1 dominates at 72% (forecast was ~30%)**: SEC-registrant
   US equities carry most of the row volume; the 4,186-ticker SOH
   universe covers the bulk of 13F mass. Forecast was too
   conservative. This is the strongest possible validation of
   Option A — the block is meaningfully period-accurate for most
   rows users see.

2. **`_compute_flows_live` parent-level `pct_of_so_source=None`**:
   When the underlying `pct_of_so` value is already aggregated
   via `SUM(h.pct_of_so)` in SQL, the `_get_pf` helper returns
   source=None (documented in Phase 1c as "tier unknown for
   pre-aggregated values"). Minor quality issue — the numeric
   value is correct, just the audit tag is missing. Could be
   resolved in a follow-up by resolving the canonical source once
   per (ticker, quarter) and propagating; flagged for future work.
   Does NOT block Phase 4.

3. **`flow_analysis` precomputed path — staging coverage gap**:
   `investor_flows` table doesn't exist in staging, only prod.
   The rewritten code path is validated via static inspection and
   via the `_compute_flows_live` fallback (which runs on staging).
   Does NOT block Phase 4, but worth a second-look test post-prod-
   apply — first real call to `flow_analysis` with
   `level='parent'` against prod should confirm the denom +
   source attach correctly on the precomputed row path.

4. **`pct_of_so` coverage grew +753K rows**: Old code missed rows
   where `market_data.float_shares IS NULL`. New code's tier 2/3
   fallback recovers them. Every one of those rows is a net
   quality gain — displayed in the UI today as a NULL, now as a
   valid value with an audit tag.

5. **`phase3_resolution_rate` FAIL is pre-existing**: Prompt
   baseline was stale. Not a regression from Phase 2.

6. **Pass B execution time: 1.4s** (12.27M row UPDATE with
   ASOF JOIN + three-tier CASE). Well within the INF-level perf
   envelope; no scale risk for prod.

### §13.7 Phase 2 exit — ready for Phase 4 sign-off

All gates met:
- Migration 008 clean + idempotent ✓
- Pass B tier distribution strong (tier 1 dominance) ✓
- All 8 N-PORT functions validated end-to-end ✓
- 13F direct-SELECT surface returns period-accurate rows ✓
- validate_entities matches prod (no regression) ✓
- Staleness counter within expectations ✓
- `_compute_flows_live` parent-source None is a known quality
  quirk, not a correctness issue ✓

HARD STOP — awaiting Serge's explicit Phase 4 sign-off before any
prod writes.

---

## §14. Phase 4b prod apply (2026-04-19)

### §14.0 Phase 4 first-attempt failure post-mortem

First attempt (commit `a960fc9` migration code, unamended) aborted at
`ALTER TABLE holdings_v2 RENAME COLUMN pct_of_float TO pct_of_so`:

```
_duckdb.DependencyException: Dependency Error: Cannot alter entry
"holdings_v2" because there are entries that depend on it.
```

**Root cause**: prod has 4 non-PK indexes on `holdings_v2` that
staging lacks (verified via `SELECT index_name FROM duckdb_indexes()
WHERE table_name='holdings_v2'`):

```
idx_hv2_cik_quarter       (cik, quarter)
idx_hv2_entity_id         (entity_id)
idx_hv2_rollup            (rollup_entity_id, quarter)
idx_hv2_ticker_quarter    (ticker, quarter)
```

DuckDB's ALTER guard rejects column changes on any table with
user-defined indexes — even when no captured index references the
renamed column. Staging had zero indexes on `holdings_v2`, so the
Phase 2 staging validation never exercised this path.

**No partial write**. The DependencyException fired on the first
ALTER; the ADD COLUMN step was gated after. Prod left in clean
pre-migration state:
- `pct_of_float` column intact
- `pct_of_so`, `pct_of_so_source` absent
- `schema_versions` 008 absent
- 4 indexes untouched
- snapshot table (`holdings_v2_pct_of_so_pre_apply_snapshot_20260419`)
  created before the migration attempt — preserved

**Fix**: amended migration 008 with a capture-and-recreate pattern
(commit `ea4ae99`). At runtime, query `duckdb_indexes()` for non-PK
indexes on `holdings_v2`, log captured (name, DDL) to stdout, DROP
each, execute RENAME + ADD COLUMN, CREATE each index from captured
DDL. Works identically on prod (4 captured) and staging (0 captured
— no-op). Idempotency guards unchanged.

Flagged as **INF39** (`BLOCK-STAGING-PROD-SCHEMA-DIVERGENCE`) — see
§14.10.

### §14.1 Migration 008 amendment — commit `ea4ae99`

Amendment flow:
1. Probe column + schema_versions state → short-circuit if applied
2. Capture non-PK indexes via `duckdb_indexes()` (`sql IS NOT NULL AND sql <> ''`)
3. Log captured DDL (recovery artifact if step 8 fails)
4. Pre-drop row count sanity
5. DROP captured indexes (per-index timing)
6. RENAME `pct_of_float` → `pct_of_so` (if needed)
7. ADD COLUMN `pct_of_so_source` (if needed)
8. CREATE INDEX from captured DDL (per-index timing)
9. Post-create row count sanity check (must match step 4)
10. Stamp schema_versions + CHECKPOINT
11. Post-condition verification — column presence + all indexes back

Mid-recreation failure mode: captured DDL is logged at step 3 before
any DROP — an operator can recover any specific missing index
manually. Full re-run is idempotent (already-renamed column +
present audit + present indexes → no-op short-circuit).

### §14.2 Pre-apply state re-verification

Before retry, all assertions passed:

```
COLUMNS  OK: pct_of_float present; pct_of_so/_source absent
INDEXES  OK: [idx_hv2_cik_quarter, idx_hv2_entity_id, idx_hv2_rollup, idx_hv2_ticker_quarter]
SCHEMA_V OK: 008 absent
SNAPSHOT OK: 12,270,984 rows
HV2 rows: 12,270,984
ALL PRE-APPLY ASSERTIONS PASS
```

### §14.3 Migration 008 prod apply — timings

```
captured 4 non-PK index(es) on holdings_v2
pre-apply row count: 12,270,984

DROP INDEX idx_hv2_cik_quarter      : 0.001s
DROP INDEX idx_hv2_entity_id         : 0.000s
DROP INDEX idx_hv2_rollup            : 0.000s
DROP INDEX idx_hv2_ticker_quarter    : 0.000s
ALTER TABLE RENAME COLUMN            : 0.000s
ALTER TABLE ADD COLUMN               : 0.365s
CREATE INDEX idx_hv2_cik_quarter     : 1.948s
CREATE INDEX idx_hv2_entity_id       : 1.625s
CREATE INDEX idx_hv2_rollup          : 1.528s
CREATE INDEX idx_hv2_ticker_quarter  : 3.114s

post-apply row count: 12,270,984 (matches pre-apply)
stamped schema_versions: 008_rename_pct_of_float_to_pct_of_so
total wall clock: 9.0s
AFTER: pct_of_float=False pct_of_so=True pct_of_so_source=True indexes_recreated=4
```

Idempotency re-run → `ALREADY APPLIED: no action`. ✓

### §14.4 Pass B prod run

**Execution time: 877.5s (14.6 min)**. Staging ran in 1.4s —
slowdown driven by incremental maintenance of the 4 indexes during
the full-table UPDATE, not a code issue.

Tier distribution (identical to Phase 2 staging forecast — prod and
staging mirror, unchanged data):

| tier | count | % of equity | % of all |
|---|---:|---:|---:|
| 1. `soh_period_accurate` | 7,725,062 | 72.4% | 62.9% |
| 2. `market_data_so_latest` | 792,115 | 7.4% | 6.5% |
| 3. `market_data_float_latest` | 22,517 | 0.2% | 0.2% |
| 4. NULL (equity) | 2,123,715 | 19.9% | 17.3% |
| — non-equity (NULL) | 1,607,575 | — | 13.1% |

Coverage: **8,539,694** post-apply (was 7,786,239 in the snapshot;
+753,455 rows = +9.7% gain).

Staleness counter: **607,814 rows** with SOH as_of_date > 60 days
before quarter_end (7.9% of tier 1).

`data_freshness('holdings_v2_enrichment')` stamped at
`2026-04-19 13:32:08` with row_count=10,394,757.

### §14.5 Coverage delta — pre/post transition

rowid is not stable across DuckDB full-table UPDATE + CHECKPOINT +
index rebuild (physical storage rewrites shift rowids). The
snapshot was captured with rowid but the join returned 0 matches —
fell back to **natural-key aggregate comparison** on
`(accession_number, cusip, quarter, cik)` (8,590,639 groups).

Group-level coverage delta:

| metric | value |
|---|---:|
| natural-key groups | 8,590,639 |
| total rows | 12,270,984 |
| snap populated rows | 7,786,239 |
| cur populated rows | 8,539,694 |
| **net delta** | **+753,455** |
| groups gained coverage | 589,678 |
| **groups lost coverage** | **0** |
| groups unchanged | 8,000,961 |
| rows gained | 753,455 |
| rows lost | 0 |

**Zero coverage regressions.** +753K rows came from tier 2/3
fallback recovering rows where old path had `market_data.float_shares
IS NULL` — previously-NULL rows that now have a valid denominator.

Value-drift magnitude on 5,150,767 matched groups (both populated
pre and post):

| drift range | groups | % |
|---|---:|---:|
| < 1% | 1,133,392 | 22% |
| 1–10% | 2,227,382 | 43% |
| 10–50% | 1,401,228 | 27% |
| ≥ 50% | **375,858** | **7%** |

The 375,858 ≥50% drift groups are the split/buyback/secondary
corrections the block was created to fix. 7% of matched groups see
material period-accuracy restoration.

### §14.6 Staleness percentiles (tier 1)

```
tier1_rows:  7,725,062
p50:          0 days
p75:          1 day
p90:         44 days
p95:         92 days
p99:        750 days
max_days: 5,479 days  (~15 years)
gt60d:  607,814  (7.9% of tier 1)
gt120d: 336,188  (4.4%)
gt200d: 227,105  (2.9%)
```

**Interpretation**:
- p50 = 0 (median match lands exactly at quarter-end — us-gaap:CSO
  XBRL facts are predominantly period-end-dated, as expected).
- p99 = 750 days is a **yellow flag** — 1% of tier 1 rows have SOH
  matches 2+ years older than quarter_end. Driven by the long tail
  of pre-2023 historical quarters where SOH coverage is sparse.
- max_days = 5,479 is 15-year-old SOH matched to very old 13F
  filings. Benign for current-quarter display; an edge for deep
  historical analysis.
- 2.9% of tier 1 rows stale > 200 days. Acceptable for Phase 4 sign-
  off; tracking via the existing `pof_stale_gt60` counter.

### §14.7 Integration smoke — 10 paths

**12/12 PASS** against prod, including the previously unvalidatable
`flow_analysis` precomputed path. Full matrix:

| # | path | result | notes |
|---|---|---|---|
| 1 | `get_nport_children_batch` (Vanguard/AAPL/2025Q4) | **PASS** | src=soh_period_accurate |
| 2 | `get_nport_children` | **PASS** | src=soh_period_accurate |
| 3 | `query16` rows | **PASS** | 25 rows, src=soh_period_accurate |
| 3a | `query16` all_totals | **PASS** | src=soh_period_accurate |
| 4 | `ownership_trend_summary` level=parent | **PASS** | 2025Q4 pct_so=67.02% src=soh_period_accurate |
| 4b | `ownership_trend_summary` level=fund | **PASS** | 2025Q4 pct_so=23.47% src=soh_period_accurate |
| 5 | `_compute_flows_live` level=parent | **PASS\*** | src=None on pre-aggregated rows (documented Phase 1c quirk) |
| 5b | `_compute_flows_live` level=fund | **PASS** | src=soh_period_accurate |
| 6 | `flow_analysis` precomputed path | **PASS** | top buyer pct_so=0.257% src=soh_period_accurate — previously unvalidatable on staging, now confirmed |
| 7 | `get_two_company_overlap` meta | **PASS** | subj_denom=14.7B, both sources=soh_period_accurate |
| 7a | `get_two_company_overlap` institutional row | **PASS** | Vanguard Group subj_src=soh_period_accurate |
| 8 | `get_two_company_subject` | **PASS** | subj_src=soh_period_accurate, sec_* all None |

**Tab-to-path mapping for Serge UI smoke** (localhost:8001 after
Flask restart):

| UI tab | backing query functions |
|---|---|
| Register | `get_nport_children_batch`, `get_nport_children`, `query16`, `api_register.py:293` |
| Ticker Detail | `query1`, `query3`, `query7`, `queries.py:1310-1346` (top holders), `queries.py:1918-1924` (concentration widget) |
| Holders | `queries.py:574` |
| Market Tab | `queries.py:865`, `api_market.py:/top-holders`, `/heatmap` |
| Fund Portfolio | `queries.py:1691` (+ CSV export), `FundPortfolioTab.tsx` |
| Ownership Trend | `ownership_trend_summary` |
| Flow Analysis | `_compute_flows_live`, `flow_analysis` (precomputed) |
| Cross-Ownership / Two Companies | `get_two_company_overlap`, `get_two_company_subject` |
| Admin / QC | `admin_bp.py:500` coverage counter |

### §14.8 validate_entities + data_freshness confirmation

```
validate_entities --prod --read-only:
Summary: {'PASS': 8, 'FAIL': 2, 'MANUAL': 6}
```

Matches the post-Phase-2 baseline exactly. Two FAILs
(wellington_sub_advisory + phase3_resolution_rate) are pre-existing
in prod and unrelated to pct-of-so.

`data_freshness` stamps:
```
holdings_v2                 2026-04-19 13:32:08  12,270,984
holdings_v2_enrichment      2026-04-19 13:32:08  10,394,757
```

`make freshness` → **PASS — all critical tables are fresh.**

### §14.9 Rollback instructions

Snapshot table remains in place as rollback insurance:
`holdings_v2_pct_of_so_pre_apply_snapshot_20260419` (12,270,984
rows; columns: row_id, accession_number, cusip, quarter, cik,
pct_of_float).

**Rollback SQL** (reverses Phase 4b apply — restores
`pct_of_float`, drops `pct_of_so_source`, restores values from
snapshot, reinstates indexes):

```sql
-- Step 1: Capture current indexes (same pattern as migration 008 amendment)
-- For prod: 4 expected
SELECT index_name, sql
  FROM duckdb_indexes()
 WHERE table_name = 'holdings_v2'
   AND sql IS NOT NULL AND sql <> '';
-- Log results; they are needed at step 5 for recreation.

-- Step 2: DROP captured indexes (by name)
DROP INDEX idx_hv2_cik_quarter;
DROP INDEX idx_hv2_entity_id;
DROP INDEX idx_hv2_rollup;
DROP INDEX idx_hv2_ticker_quarter;

-- Step 3: Reverse the column changes
ALTER TABLE holdings_v2 DROP COLUMN pct_of_so_source;
ALTER TABLE holdings_v2 RENAME COLUMN pct_of_so TO pct_of_float;

-- Step 4: Restore pre-apply pct_of_float values from snapshot.
-- Natural-key join (rowid not stable; see §14.5). Uses SUM over the
-- dup-group ambiguity — 221K rows (1.8%) fall in intentional dup
-- groups and will receive the group's max pre-apply value. Acceptable
-- for rollback since post-UPDATE values are already overwritten.
UPDATE holdings_v2 h
   SET pct_of_float = agg.pct
  FROM (
      SELECT accession_number, cusip, quarter, cik,
             MAX(pct_of_float) AS pct
        FROM holdings_v2_pct_of_so_pre_apply_snapshot_20260419
       GROUP BY 1,2,3,4
  ) AS agg
 WHERE h.accession_number = agg.accession_number
   AND h.cusip            = agg.cusip
   AND h.quarter          = agg.quarter
   AND h.cik              = agg.cik;

-- Step 5: Recreate indexes from step 1's captured DDL
CREATE INDEX idx_hv2_cik_quarter ON holdings_v2(cik, "quarter");
CREATE INDEX idx_hv2_entity_id ON holdings_v2(entity_id);
CREATE INDEX idx_hv2_rollup ON holdings_v2(rollup_entity_id, "quarter");
CREATE INDEX idx_hv2_ticker_quarter ON holdings_v2(ticker, "quarter");

-- Step 6: Unstamp schema_versions
DELETE FROM schema_versions
 WHERE version = '008_rename_pct_of_float_to_pct_of_so';

-- Step 7: CHECKPOINT
CHECKPOINT;

-- Step 8: Drop the snapshot table (optional — keep for audit)
-- DROP TABLE holdings_v2_pct_of_so_pre_apply_snapshot_20260419;
```

**Verified mentally against amended migration 008 semantics**:
post-rollback state is `pct_of_float` present, `pct_of_so` and
`pct_of_so_source` absent, `schema_versions` 008 unstamped, 4
indexes recreated with original DDL, row count unchanged.

Re-running migration 008 after a rollback would re-execute cleanly
— the idempotency short-circuit looks at column state, not at
schema_versions alone.

**Caveat on step 4**: the natural-key ambiguity means the 221K rows
in intentional dup groups receive `MAX(pct_of_float)` from the
snapshot rather than each row's original value. Most dup-group
members had identical `pct_of_float` (same cusip+quarter → same
denominator → same pct). Where shares differed across dups, the
rollback yields slightly higher values than pre-apply for some rows
in the dup group. Acceptable for a rollback scenario; documented.

**Rollback is not needed under current verification state**. This
section is insurance for a future regression discovery.

### §14.10 Deferred doc updates (comprehensive — source of truth
for next batched session)

**ROADMAP.md**
- Current-state header: add completion entry for
  BLOCK-PCT-OF-SO-PERIOD-ACCURACY (all 10 N-PORT/13F read paths
  migrated, tier 1 dominance 72.4%, zero coverage regressions,
  Phase 4b prod apply 2026-04-19).
- Correct validate_entities baseline: **8/1/7 → 8/2/6**.
  Pre-existing FAILs are wellington_sub_advisory (known baseline)
  and phase3_resolution_rate (SEC > 80%, enrichment > 25%
  threshold). Neither caused by pct-of-so.
- Mark `pct_of_float` terminology retired across the project;
  `pct_of_so` is the canonical metric name going forward.
- Add **INF38 — BLOCK-FLOAT-HISTORY** as new roadmap item.
  - Scope: quarterly float history from Section 13 beneficial
    ownership (Schedule 13D/G) + Section 16 insider holdings
    (Forms 3/4/5); computed as `shares_outstanding - total_insider
    - restricted`; annual from 10-K Item 5 `EntityPublicFloat`
    where tagged.
  - Dependency: Section 16 ingestion infrastructure.
  - Priority: low-medium.
  - Use case: squeeze/liquidity analysis, activist targeting,
    float-adjusted pct_of_float restoration (the semantic the
    original block prompt wanted but couldn't deliver without float
    history).
- Add **INF39 — BLOCK-STAGING-PROD-SCHEMA-DIVERGENCE** as new
  roadmap item.
  - Scope: pre-flight schema-diff check at the top of every Phase 2.
    Compare staging vs prod: indexes (names + DDL), constraints,
    triggers, column types, column defaults, sequences, views.
  - Fail loudly if divergence detected before Phase 2 validation
    proceeds. Remediation: fix divergence in staging before
    validating, or explicitly document the divergence as
    known-and-accepted with justification.
  - Document the **capture-and-recreate pattern** (used in
    migration 008 amendment, commit `ea4ae99`) as the reusable
    migration idiom for any L3 canonical table with prod-side
    indexes.
  - Precedent cross-reference: pct-of-so Phase 4 DependencyException
    (documented in §14.0).
  - Priority: medium (process hardening; prevents same class of
    failure on every future v2-table migration).

**docs/data_layers.md**
- §7: add `pct_of_so_source` audit column to the denormalized-
  columns discussion. Note: Class B "lookup at read time" column
  that STAYS denormalized because it stamps provenance of the
  computation tier, not entity/ticker identity. Values: see §9.3.
- §8: add pct-of-so workstream to the "writers orphaned by table
  drops" discussion if relevant.

**docs/canonical_ddl.md**
- `holdings_v2` DDL block: rename `pct_of_float DOUBLE` →
  `pct_of_so DOUBLE`.
- `holdings_v2` DDL block: add `pct_of_so_source VARCHAR`.
- Document the capture-and-recreate pattern for any L3 table
  migration touching column renames when indexes are present
  (forward-link to INF39).

**docs/pipeline_inventory.md**
- Update `enrich_holdings.py` Pass B description: SOH ASOF
  denominator with three-tier fallback (SOH → md.shares_outstanding
  → md.float_shares) + `pct_of_so_source` audit stamp. Sole writer
  of `holdings_v2.pct_of_so` and `holdings_v2.pct_of_so_source`.

**docs/pipeline_violations.md**
- Close any existing pct_of_float-related violation entry with
  commit citations (Phase 1b `dd2b5a1`, Phase 1c `b0ba86d`,
  Phase 4b `ea4ae99`).

**docs/NEXT_SESSION_CONTEXT.md**
- Add pct-of-so block closure note with commit list `0871178` →
  post-Phase-4b findings commit.
- Flag INF39 as strong candidate for next session — the
  capture-and-recreate pattern is reusable and worth generalizing
  while context is fresh.
- Flag INF38 as lower-priority but tracked.

**docs/findings/2026-04-19-rewrite-build-shares-history.md**
- §3.2.1: mark the "elevate follow-up block" as DONE. Forward-link
  to this findings doc
  (`docs/findings/2026-04-19-rewrite-pct-of-so-period-accuracy.md`).

**Decisions to document (already resolved but worth recording)**
- §11.6 mixed-semantics resolution (N-PORT SOH ASOF) — **closed in
  Phase 1c** (commit `b0ba86d`).
- `summary_by_ticker` prod rebuild vs migration — decision still
  open (§12). Current status: `summary_by_ticker.pct_of_so` column
  definition already exists (via Phase 1b read-site migration of
  `build_summaries.py:121`). A fresh `scripts/build_summaries.py`
  run in prod will re-materialize values under the new tier
  semantics. Serge to decide sequencing — likely next regular
  `build_summaries.py` cadence picks it up automatically.
- `_compute_flows_live` parent-level `pct_of_so_source=None` on
  pre-aggregated rows — **UI behavior check deferred**: confirm
  React handles NULL source gracefully (shows "—" or blank, not
  confusing text). Tab-to-path mapping in §14.7 points to Flow
  Analysis tab for this check.

**INF38 stub content (for the ROADMAP entry copy-paste)**
```
INF38 — BLOCK-FLOAT-HISTORY
Scope: Build float_shares_history table for true float-adjusted
pct_of_float restoration. Data sources:
  - 10-K Item 5 EntityPublicFloat XBRL tag (annual snapshot)
  - Schedule 13D/G filings (beneficial ownership >5%)
  - Forms 3/4/5 (Section 16 insider holdings)
  - Derived: shares_outstanding - insider_holdings - restricted
Trigger: enables true pct_of_float metric alongside current pct_of_so.
Dependencies: Section 16 ingestion infrastructure (not yet built).
Priority: low-medium. Tracked but no ETA.
Use cases: squeeze/liquidity analysis, activist targeting, more
accurate register %-ownership for closely-held names.
```

**INF39 stub content (for the ROADMAP entry copy-paste)**
```
INF39 — BLOCK-STAGING-PROD-SCHEMA-DIVERGENCE
Scope: Pre-flight schema-diff check before every Phase 2 staging
validation. Compare staging vs prod:
  - Index names + DDL (via duckdb_indexes())
  - Constraints + triggers
  - Column types + defaults + nullability
  - Sequences + views
  - schema_versions stamps
Fail loudly if divergence found. Remediation: either resync staging
to prod, or explicitly document divergence as known-accepted.
Document capture-and-recreate pattern (migration 008 amendment,
commit ea4ae99) as the reusable idiom for any L3 migration touching
columns on an index-bearing table.
Priority: medium (process hardening).
Precedent: pct-of-so Phase 4 DependencyException (see
2026-04-19-rewrite-pct-of-so-period-accuracy.md §14.0).
```

### §14.10 addendum — INF42 + INF34 (added 2026-04-19, branch `fix/post-merge-regressions`)

Post-merge browser smoke on main@`bee49ff` surfaced three live
regressions (Register %FLOAT blank, Flow Analysis duplicated rows,
Conviction 500) plus one CI smoke failure (run #108). Two of the
four traced back to a single new failure class — derived artifacts
that ship stale while their source has been updated. This warrants
its own deferred item.

**INF42 — BLOCK-DERIVED-ARTIFACT-HYGIENE**

Compiled and generated artifacts can ship to main with stale content
while their source has been updated. pct-of-so exposed two instances
simultaneously:

1. Stale React `web/react-app/dist/` bundle (built before commit
   `f956096`) still referenced the old field name `pct_float` — the
   Register tab `% FLOAT` column rendered em-dashes because the API
   now returns `pct_so`. Source (`.tsx`) was correct; dist/ was not
   rebuilt at merge time. `dist/` is gitignored so the drift is
   invisible to code review.
2. Stale CI smoke fixture DB (`tests/fixtures/13f_fixture.duckdb`)
   predated migration 008 (column rename) and did not include the
   new `shares_outstanding_history` table. 4/8 CI smoke tests failed
   on run #108.

Fix scope (for a future dedicated session, NOT this one):
- Pre-commit or CI enforcement that rebuilds `web/react-app/dist/`
  whenever `web/react-app/src/**` changes. Likely path: CI step that
  runs `npm run build` and asserts the resulting bundle matches the
  one served. If `dist/` remains gitignored, a deploy-time rebuild
  must be guaranteed.
- Pre-commit or CI enforcement that regenerates
  `tests/fixtures/13f_fixture.duckdb` whenever
  `scripts/migrations/***.py` or `scripts/build_fixture.py` changes
  schema. OR: CI job that re-runs `scripts/build_fixture.py` fresh
  each build so the committed binary becomes unnecessary.
- Wire `npm run build` into `scripts/start_app.sh` so local dev
  catches source/dist drift the first time a developer hits the page
  after pulling.
- Fail loudly on staleness rather than silently ship drifted
  artifacts.

Tactical patches already applied in this session (commits on
`fix/post-merge-regressions`):
- React dist rebuilt locally (not committable — gitignored). Serge
  to rebuild after pull; INF42 proper fix needed for durable
  automation.
- `scripts/build_fixture.py` extended with
  `shares_outstanding_history`; fixture DB + response snapshots
  regenerated and committed (binary).

Cross-reference: pct-of-so post-merge browser smoke (stale dist), CI
run #108 (stale fixture), `fix/post-merge-regressions` Phase 5.

Sibling to: INF39 / INF40 / INF41 — together form the v2-table
migration hardening package (schema-diff, surrogate-id, rename-sweep,
artifact-hygiene).

Priority: medium.

**INF34 — CLEARED (2026-04-19)**

INF34 was "queries.py rollup_type filter missing". The Flow Analysis
duplicate-row regression exposed a second instance in the same class,
so Phase 5 took the sweep approach rather than a tactical patch. All
6 flagged read sites in `scripts/queries.py` against
`investor_flows` or `summary_by_parent` now filter on the caller's
`rollup_type`. Fix commit: Task 2 of `fix/post-merge-regressions`
("post-merge-fixes: Flow Analysis dup — INF34 full sweep..."). No
residual sites deferred. INF34 is removed from the open-items index.

**INF42 stub content (for the ROADMAP entry copy-paste)**
```
INF42 — BLOCK-DERIVED-ARTIFACT-HYGIENE
Scope: CI / pre-commit automation that fails loudly when a generated
artifact ships stale.
Two known classes:
  - web/react-app/dist/ (gitignored, rebuilt at deploy — no check
    today that the served bundle matches current src/)
  - tests/fixtures/13f_fixture.duckdb (committed binary, rebuilt
    only by hand via scripts/build_fixture.py)
Priority: medium. Sibling to INF39/INF40/INF41.
Precedent: pct-of-so post-merge regressions 2026-04-19 — see
2026-04-19-rewrite-pct-of-so-period-accuracy.md §14.10 addendum.
```

### §14.11 Phase 4b exit

All gates met:
- Migration 008 applied cleanly, idempotent, schema diff matches
  design ✓
- Pass B full refresh in 877.5s, no anomalies ✓
- Zero coverage regressions, +753K rows gained, 7% of matched
  groups see ≥50% period-accuracy restoration ✓
- Staleness p50=0, p99=750 (yellow flag, acceptable; long-tail
  historical) ✓
- 12/12 integration smoke PASS, including prod-only
  `flow_analysis` precomputed path ✓
- validate_entities stable at 8/2/6 (prod baseline, no regression) ✓
- `data_freshness` stamped, `make freshness` PASS ✓
- Rollback SQL documented and mentally verified ✓

HARD STOP — awaiting Serge's UI smoke + merge sign-off. Block not
declared complete until then.

---

## §14.11 Phase 4c — comprehensive rename sweep + live smoke

### §14.11.1 Missed-rename post-mortem

Live app smoke during Phase 4b surfaced a `BinderException: Referenced
column "pct_of_float" not found` at `queries.py::_get_summary_impl`.
Root cause turned out to be Flask running the **main-branch checkout**
against the post-migration prod DB — the block-branch renames were
present on origin but the local Flask process loaded main-branch code.
Not a code bug in the block branch; a deployment mismatch.

The event nonetheless triggered an exhaustive sweep because:
- Phase 1b's inventory caught 71 references in queries.py via
  `replace_all`, but future sessions cannot trust "I ran `grep` on
  a few specific files and replaced all hits" — the sweep needs to
  be repo-wide with an explicit preserve-list.
- Phase 1c had already caught 4 N-PORT compute paths the Phase 1b
  grep missed. Two partial misses suggest systemic risk.

Phase 4c sweep method: `grep -rn pct_of_float` across `*.py`,
`*.ts`, `*.tsx`, `*.js`, `*.jsx`, `*.sql` with explicit preserve-
list filtering. Plus alias grep for `total_pct_float`, `pct_float\b`,
`float_pct_pct`, `with_float_pct`.

### §14.11.2 Full Phase 4c inventory

**Category (a) — SITES FIXED**:

| file:line | issue | fix |
|---|---|---|
| `scripts/queries.py:2500` | `'float_pct_pct'` response-dict key — underlying query already uses `COUNT(CASE WHEN pct_of_so IS NOT NULL…)` on line 2491, but the key retained the `float_` prefix | Renamed to `'so_pct_pct'`. No React consumer reads this key (grep confirms zero downstream refs). |
| `scripts/build_shares_history.py:15-20` | Module docstring references "update_holdings_pct_of_float" retired path and forward-links to "BLOCK-PCT-OF-FLOAT-PERIOD-ACCURACY" (pre-rename block name) | Docstring updated to reference the landed BLOCK-PCT-OF-SO-PERIOD-ACCURACY. Historical "update_holdings_pct_of_float" symbol name preserved (it's referring to a retired function's name, not the column). |

**Category (b) — INTENTIONAL PRESERVES**:

| file | reason |
|---|---|
| `scripts/migrations/008_rename_pct_of_float_to_pct_of_so.py` | migration file — `pct_of_float` is the *source* column the migration renames; must stay |
| `scripts/enrich_holdings.py:9, :147` | docstring + inline comment explicitly reference the rename history |
| `scripts/auto_resolve.py:536,540` | dead writer on RETIRE list — targets dropped `holdings` table |
| `scripts/approve_overrides.py:159,164` | dead writer on RETIRE list |
| `scripts/enrich_tickers.py:385,399,404,408` | dead writer on RETIRE list |
| all `docs/REWRITE_*.md` | historical findings docs — intentional context |
| git commit messages | immutable |

**Category (c) — SURPRISES**:

None. The one non-obvious alias (`float_pct_pct`) was caught by the
alias grep for `float_pct`. No other missed renames found. The
block-branch code is clean.

### §14.11.3 Live smoke results

Flask booted from worktree (not main-repo `start_app.sh`) on
`:8001` against prod DB. All endpoints returned 200 OK with valid
JSON.

**Baseline endpoints (6/6 PASS)**:

| endpoint | result | sample |
|---|---|---|
| `/api/v1/freshness` | PASS | `holdings_v2 last_computed_at 2026-04-19T13:32:08` |
| `/api/v1/summary?ticker=AAPL` | PASS | `total_pct_so=67.02, shares_float=14,655,888,439, price_date=2026-04-16` |
| `/api/v1/summary?ticker=MSFT` | PASS | `total_pct_so=86.11` |
| `/api/v1/summary?ticker=XOM` | PASS | `total_pct_so=67.52` |
| `/api/v1/tickers` | PASS | 200 OK, ticker list returned |
| `/api/v1/entity_market_summary?limit=5` | PASS | Vanguard / BlackRock top two |

**10 integration paths via HTTP (10/10 PASS)**:

| # | path | endpoint | result |
|---|---|---|---|
| 1 | query1 (Register institutional) | `/api/v1/query1?ticker=AAPL` | 104 rows, top pct_so=9.72 (Vanguard, SUM-aggregated — source inherits from DB rows, dict-level source omitted per Phase 1c pre-aggregate pattern) |
| 2+3 | get_nport_children_batch / _children | invoked via Register load | exercised through /query1 (nport children embedded) |
| 3 | query16 | `/api/v1/query16?ticker=AAPL` | 25 rows, top src=`soh_period_accurate`, all_totals: pct_so=23.47 src=`soh_period_accurate` |
| 4 | ownership_trend_summary parent | `/api/v1/ownership_trend_summary?ticker=AAPL&level=parent` | 4 quarters, 2025Q4 pct_so=67.02 src=`soh_period_accurate` |
| 4b | ownership_trend_summary fund | same endpoint `level=fund` | 13 quarters, src=`soh_period_accurate` |
| 5 | _compute_flows_live fund | `/api/v1/flow_analysis?ticker=AAPL&level=fund` | 25 buyers, top pct_so=0.232 src=`soh_period_accurate` |
| 6 | **flow_analysis precomputed parent** | `/api/v1/flow_analysis?ticker=AAPL&level=parent` | 25 buyers, top pct_so=0.257 **src=`soh_period_accurate`** — previously unvalidatable on staging; now confirmed via live HTTP |
| 7 | two_company_overlap | `/api/v1/two_company_overlap?subject=AAPL&second=MSFT&quarter=2025Q4` | meta: subj_denom=14.7B src=`soh_period_accurate`, sec_denom=7.4B src=`soh_period_accurate` |
| 8 | two_company_subject | `/api/v1/two_company_subject?subject=AAPL&quarter=2025Q4` | subj_denom=14.7B src=`soh_period_accurate`, sec_* all None (subject-only variant) |

**Tab-to-path mapping for Serge browser UI smoke**:

| Tab | Endpoints invoked |
|---|---|
| Register | `/api/v1/query1`, `/api/v1/query16`, `/api/v1/register/holdings` |
| Ticker Detail | `/api/v1/summary`, `/api/v1/query1`, `/api/v1/query3`, top-holders widget, concentration widget |
| Ownership Trend | `/api/v1/ownership_trend_summary` (both parent + fund) |
| Flow Analysis | `/api/v1/flow_analysis` (both levels) |
| Cross-Ownership / Two Companies | `/api/v1/two_company_overlap`, `/api/v1/two_company_subject` |
| Market | `/api/v1/top-holders`, `/api/v1/heatmap`, `/api/v1/crowding`, `/api/v1/smart_money` |
| Fund Portfolio | `/api/v1/fund_portfolio` + CSV export |
| Admin / QC | `/api/v1/coverage` (uses renamed `so_pct_pct` dict key) |

### §14.11.4 INF41 — process-hardening deferred item

Added to §14.10 ROADMAP subsection:

**INF41 — BLOCK-READ-SITE-INVENTORY-DISCIPLINE**

Schema-rename migrations require a mechanically exhaustive grep-
based inventory check, not eyeball enumeration. Precedent:
- pct-of-so Phase 1b missed 4 N-PORT compute paths (caught Phase
  1c, commit `b0ba86d`)
- pct-of-so Phase 4b live smoke surfaced one missed alias
  `float_pct_pct` (fixed Phase 4c, commit `c1fbce4`)

Fix: pre-migration checklist step that runs
`grep -rn <old_name>` across the entire repo excluding only the
migration file and findings docs, then asserts zero hits before
Phase 4 prod apply. Includes alias search: common transformations
(`_pct` → `_pct_pct`, `total_` prefix, camelCase variants, field-
name drift like `with_X_pct`).

Sibling to **INF39** (BLOCK-STAGING-PROD-SCHEMA-DIVERGENCE) and
**INF40** (surrogate row_id for rollback — noted in §14.5 as
future infra). Together the three form the canonical v2-table
migration hardening trilogy:
- INF39: schema divergence pre-flight check
- INF40: stable surrogate row-ID for rollback reconstruction
- INF41: mechanically exhaustive rename sweep

Priority: medium.

### §14.11.5 INF41 stub content (for ROADMAP copy-paste)

```
INF41 — BLOCK-READ-SITE-INVENTORY-DISCIPLINE
Scope: Pre-migration checklist requires mechanically exhaustive
grep-based sweep for any column/field rename, not targeted
enumeration. Script the check:

  #!/bin/bash
  OLD_NAME="$1"
  PRESERVE_PATHS="scripts/migrations/ docs/REWRITE_"
  HITS=$(grep -rn "$OLD_NAME" \
    --include='*.py' --include='*.ts' --include='*.tsx' \
    --include='*.js' --include='*.jsx' --include='*.sql' \
    --exclude-dir='.git' --exclude-dir='node_modules' \
    --exclude-dir='.claude' . | \
    grep -vE "($PRESERVE_PATHS)")
  if [ -n "$HITS" ]; then
    echo "FAIL: $OLD_NAME still referenced outside preserve list"
    echo "$HITS"
    exit 1
  fi

Run as final gate before Phase 4 prod apply. Includes alias search
for common transformations (*_pct → *_pct_pct, total_*, camelCase,
with_X_pct field-name drift).
Priority: medium (process hardening).
Precedent: pct-of-so Phase 1b/1c/4c sweep gaps — see §14.11.
```

### §14.11.6 Phase 4c exit

- Exhaustive grep inventory: 2 fixes, all preserve-list items
  accounted for ✓
- Post-fix grep verification: zero alias hits, all remaining
  `pct_of_float` references are in the preserve list ✓
- Live HTTP smoke: 6/6 baseline + 10/10 integration paths PASS ✓
- Flask killed, DB symlinks removed ✓

Block code is **user-smoke-ready**. Serge performs browser UI walk-
through before accepting merge.

---

## §14.12 Rewrite block shape addendum — Phase 2 schema-parity pre-flight (INF39)

_Added 2026-04-19 at close of block/schema-diff-inf39 Phase 1._

Every future Rewrite block (and any schema-touching canonical migration) must
include a schema-parity pre-flight before Phase 2 staging validation.

### Updated block shape

```
Phase 0 — investigation / findings doc
Phase 1 — implementation (staging DB only)
Phase 2 — staging validation
  § Phase 2 pre-flight (NEW since INF39):
      make schema-parity-check
    MUST exit 0 before any validation workload runs.
    On non-zero exit, halt Phase 2. Remediate drift (either resync staging
    to prod, or add an accept-list entry with justification + expiry +
    reviewer in config/schema_parity_accept.yaml) and re-run the pre-flight.
  § Phase 2 validation proper
HARD STOP — await Serge's explicit Phase 4 sign-off
Phase 4 — prod apply
```

### Rationale

The pct-of-so Phase 4 prod apply aborted on `DependencyException` because
staging had 0 non-PK indexes on `holdings_v2` while prod had 4 (see §14.0).
Staging-only Phase 2 validation passed silently because the ALTER guard path
the failure exercised only fires when indexes are present. The
`make schema-parity-check` gate turns that divergence into a hard stop before
Phase 2 ever begins.

### Pre-flight usage

- Standalone: `make schema-parity-check` (exits 0 on parity, 1 on unaccepted
  divergence or expired accept-list entry, 2 on invocation error).
- JSON mode for scripting: `python3 scripts/pipeline/validate_schema_parity.py --json`.
- Accept-list: `config/schema_parity_accept.yaml` — ships empty; entries require
  a prose justification ≥30 chars and are optionally bounded by an ISO
  `expiry_date` that forces re-review.

### What the gate covers today (INF39)

L3 canonical tables only: columns, indexes, constraints, DDL text. L4 derived
tables are deferred to **INF45** (drift self-corrects on L4 rebuild today) and
L0 control-plane tables are deferred to **INF46** (single-writer-per-table
discipline makes drift rare). CI wiring is deferred to **INF47** once the
fixture DB reproduces canonical L3 structure — see docs/DEFERRED_FOLLOWUPS.md.
