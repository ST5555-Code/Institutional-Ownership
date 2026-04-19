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
Confirmed via `REWRITE_BUILD_SHARES_HISTORY_FINDINGS.md §3.2.1` and
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
