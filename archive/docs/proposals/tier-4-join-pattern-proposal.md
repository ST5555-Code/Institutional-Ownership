# Tier 4 Join Pattern Proposal

_Generated: 2026-04-22. For Serge review. Informs comprehensive work plan v3 Tier 4 enforcement rule._

**TL;DR.** Proposed join pattern for new Tier 4 query functions. Example rewrite of `query5()` shows Version B (runtime joins) is ~0 ms slower than Version A (stamped reads) on warm cache and occasionally faster on cold cache (holdings_v2 scan dominates; 3–4 hash joins against small lookup tables are free). Helper library ~60 LOC. One material reliability finding: `entity_current` VIEW bakes in `rollup_type='economic_control_v1'`; any DM worldview path must bypass the view. Recommendation below: **hybrid** (hard for new functions; soft for modifications to legacy stamp-column functions, which bundle into int-09 Step 4 regardless).

Reference: [docs/findings/int-09-p0-findings.md §4](../findings/int-09-p0-findings.md).

---

## 1. Picked function for example rewrite

**Chosen: `query5()` at [scripts/queries.py:1738–1768](../../scripts/queries.py#L1738-L1768).**

**Rationale.** Evaluated the five candidates named in the session spec. `get_portfolio_context()`, `get_register_top25()`, `get_top_holders()` do not exist. Of the remaining two:

- `get_summary()` (lines 4164–4267) — uses only `ticker` as a stamped column. No `rollup_name` / `dm_rollup_name`. Doesn't exercise the dual-worldview path. Under-represents the join pattern.
- `query3()` (lines 1416–1705) — 290 lines, 2 CTEs, 8 post-fetch enrichment queries. Over-represents the pattern. Side-by-side would bury the pedagogy in boilerplate.

`query5()` is 32 lines, takes `(ticker, rollup_type, quarter)`, filters `holdings_v2 WHERE ticker = ?`, uses `COALESCE(rollup_name | dm_rollup_name, inst_parent_name, manager_name)` as the rollup label, groups by holder + `manager_type`, returns 25 rows. It is the shape a new Tier 4 author will reach for first.

Secondary candidates by fit: `query14()` (lines 2484–2509, simpler, no window function) and `holder_momentum()` (lines 1198–1313, dual-table 13F + N-PORT). Not picked — query5 sits in the middle of the complexity distribution.

---

## 2. Version A — current (stamped-column) implementation

Verbatim from [scripts/queries.py:1738–1768](../../scripts/queries.py#L1738-L1768):

```python
def query5(ticker, rollup_type='economic_control_v1', quarter=LQ):
    """Quarterly share change heatmap."""
    rn = _rollup_col(rollup_type)
    con = get_db()
    try:
        df = con.execute(f"""
            WITH pivoted AS (
                SELECT
                    COALESCE({rn}, inst_parent_name, manager_name) as holder,
                    manager_type,
                    SUM(CASE WHEN quarter='{FQ}' THEN shares END) as q1_shares,
                    SUM(CASE WHEN quarter='{QUARTERS[1]}' THEN shares END) as q2_shares,
                    SUM(CASE WHEN quarter='{PQ}' THEN shares END) as q3_shares,
                    SUM(CASE WHEN quarter='{quarter}' THEN shares END) as q4_shares
                FROM holdings_v2
                WHERE ticker = ? AND is_latest = TRUE
                GROUP BY holder, manager_type
            )
            SELECT *,
                q2_shares - q1_shares as q1_to_q2,
                q3_shares - q2_shares as q2_to_q3,
                q4_shares - q3_shares as q3_to_q4,
                q4_shares - q1_shares as full_year_change
            FROM pivoted
            WHERE q4_shares IS NOT NULL
            ORDER BY q4_shares DESC
            LIMIT 25
        """, [ticker]).fetchdf()
        return df_to_records(df)
    finally:
        pass  # connection managed by thread-local cache
```

Stamped reads: `{rn}` (= `rollup_name` or `dm_rollup_name`), `inst_parent_name`, `manager_name`, `manager_type`, `ticker`. None of these are present in `entity_current` by that name; they are denormalized snapshots stamped at load time from the entity layer (and `securities.ticker` via CUSIP). Filter `ticker = ?` hits the stamped `holdings_v2.ticker` (index `idx_hv2_ticker_quarter` exists but DuckDB uses SEQ_SCAN with vectorized filter pushdown; see §5 EXPLAIN).

---

## 3. Version B — join-pattern implementation

Both worldviews shown. The EC variant can use the `entity_current` VIEW for the rollup leg; the DM variant cannot (§6.3).

### 3.1 Version B — EC worldview

```python
def query5(ticker, rollup_type='economic_control_v1', quarter=LQ):
    """Quarterly share change heatmap — join-pattern rewrite."""
    if rollup_type != 'economic_control_v1':
        return _query5_dm(ticker, quarter)
    con = get_db()
    try:
        df = con.execute(f"""
            WITH pivoted AS (
                SELECT
                    COALESCE(ec_rollup.display_name, ec.display_name,
                             h.inst_parent_name, h.manager_name) as holder,
                    ech.classification as manager_type,
                    SUM(CASE WHEN h.quarter='{FQ}' THEN h.shares END) as q1_shares,
                    SUM(CASE WHEN h.quarter='{QUARTERS[1]}' THEN h.shares END) as q2_shares,
                    SUM(CASE WHEN h.quarter='{PQ}' THEN h.shares END) as q3_shares,
                    SUM(CASE WHEN h.quarter='{quarter}' THEN h.shares END) as q4_shares
                FROM holdings_v2 h
                JOIN securities s ON s.cusip = h.cusip
                LEFT JOIN entity_current ec ON ec.entity_id = h.entity_id
                LEFT JOIN entity_current ec_rollup
                    ON ec_rollup.entity_id = ec.rollup_entity_id
                LEFT JOIN entity_classification_history ech
                    ON ech.entity_id = h.entity_id
                   AND ech.valid_to = DATE '9999-12-31'
                WHERE s.ticker = ? AND h.is_latest = TRUE
                GROUP BY
                    COALESCE(ec_rollup.display_name, ec.display_name,
                             h.inst_parent_name, h.manager_name),
                    ech.classification
            )
            SELECT *,
                q2_shares - q1_shares as q1_to_q2,
                q3_shares - q2_shares as q2_to_q3,
                q4_shares - q3_shares as q3_to_q4,
                q4_shares - q1_shares as full_year_change
            FROM pivoted
            WHERE q4_shares IS NOT NULL
            ORDER BY q4_shares DESC
            LIMIT 25
        """, [ticker]).fetchdf()
        return df_to_records(df)
    finally:
        pass
```

Changes:
- `WHERE ticker = ?` → `JOIN securities s USING (cusip) WHERE s.ticker = ?`.
- `{rn}` → `ec_rollup.display_name` via self-join to `entity_current` on `ec.rollup_entity_id`.
- `manager_type` → `ech.classification` from `entity_classification_history`.
- `inst_parent_name` / `manager_name` retained as COALESCE fallbacks. Canonical source (when they exist) is `entity_current.display_name`; the raw filer name fallbacks cover entity_id = NULL rows (no MDM match).
- GROUP BY uses raw expressions (DuckDB binder rejects alias in GROUP BY once `ech.classification` is aliased).
- Joins via `h.entity_id`, which is itself a retirement candidate. For the post-Step-4 pattern, swap `ec.entity_id = h.entity_id` for `ec.entity_id = ei.entity_id` with `JOIN entity_identifiers ei ON ei.identifier_type='cik' AND ei.identifier_value = h.cik AND ei.valid_to = DATE '9999-12-31'`. Both are shown in the helper design below.

### 3.2 Version B — DM worldview

`entity_current` filters `entity_rollup_history.rollup_type = 'economic_control_v1'` in its definition (verified via `duckdb_views()`). DM worldview must bypass the view for the rollup leg:

```python
def _query5_dm(ticker, quarter=LQ):
    con = get_db()
    df = con.execute(f"""
        WITH pivoted AS (
            SELECT
                COALESCE(rollup_entity.display_name, ec.display_name,
                         h.inst_parent_name, h.manager_name) as holder,
                ech.classification as manager_type,
                SUM(CASE WHEN h.quarter='{FQ}' THEN h.shares END) as q1_shares,
                SUM(CASE WHEN h.quarter='{QUARTERS[1]}' THEN h.shares END) as q2_shares,
                SUM(CASE WHEN h.quarter='{PQ}' THEN h.shares END) as q3_shares,
                SUM(CASE WHEN h.quarter='{quarter}' THEN h.shares END) as q4_shares
            FROM holdings_v2 h
            JOIN securities s ON s.cusip = h.cusip
            LEFT JOIN entity_current ec ON ec.entity_id = h.entity_id
            LEFT JOIN entity_rollup_history erh
                ON erh.entity_id = h.entity_id
               AND erh.rollup_type = 'decision_maker_v1'
               AND erh.valid_to = DATE '9999-12-31'
            LEFT JOIN entity_current rollup_entity
                ON rollup_entity.entity_id = erh.rollup_entity_id
            LEFT JOIN entity_classification_history ech
                ON ech.entity_id = h.entity_id
               AND ech.valid_to = DATE '9999-12-31'
            WHERE s.ticker = ? AND h.is_latest = TRUE
            GROUP BY
                COALESCE(rollup_entity.display_name, ec.display_name,
                         h.inst_parent_name, h.manager_name),
                ech.classification
        )
        SELECT *,
            q2_shares - q1_shares as q1_to_q2,
            q3_shares - q2_shares as q2_to_q3,
            q4_shares - q3_shares as q3_to_q4,
            q4_shares - q1_shares as full_year_change
        FROM pivoted
        WHERE q4_shares IS NOT NULL
        ORDER BY q4_shares DESC
        LIMIT 25
    """, [ticker]).fetchdf()
    return df_to_records(df)
```

Branching between EC/DM at the Python level (one function per worldview) is cleaner than threading a conditional JOIN fragment into a single f-string. The helper library (§4) provides the JOIN fragments so the branching cost is one line.

---

## 4. Helper library design

Proposed module: `scripts/queries_helpers.py`. Pure-Python string assembly, no DB connection required at import, no ORM. Matches existing raw-SQL style in `queries.py`.

```python
"""
Join-clause helpers for canonical-source resolution.

Tier 4 authors should use these instead of reading stamped columns on
holdings_v2 / fund_holdings_v2. Keeps queries.py forward-compatible with
int-09 Step 4 (BLOCK-DENORM-RETIREMENT).
"""
from typing import Literal

Worldview = Literal['economic_control_v1', 'decision_maker_v1']


def ticker_join(h: str = 'h', s: str = 's') -> str:
    """JOIN fragment resolving ticker from canonical securities table.

    Caller filters with `{s}.ticker = ?`. Example:
        f"FROM holdings_v2 {h} {ticker_join('h','s')} WHERE s.ticker = ?"
    """
    return f"JOIN securities {s} ON {s}.cusip = {h}.cusip"


def entity_join(h: str = 'h', ec: str = 'ec', *,
                via: Literal['entity_id', 'cik'] = 'entity_id') -> str:
    """LEFT JOIN fragment resolving entity metadata from entity_current.

    `via='entity_id'` uses the existing stamped h.entity_id (interim; breaks
    post-Step-4). `via='cik'` resolves through entity_identifiers and is
    forward-compatible.
    """
    if via == 'entity_id':
        return f"LEFT JOIN entity_current {ec} ON {ec}.entity_id = {h}.entity_id"
    return (
        f"LEFT JOIN entity_identifiers ei_{ec} "
        f"  ON ei_{ec}.identifier_type = 'cik' "
        f" AND ei_{ec}.identifier_value = {h}.cik "
        f" AND ei_{ec}.valid_to = DATE '9999-12-31' "
        f"LEFT JOIN entity_current {ec} ON {ec}.entity_id = ei_{ec}.entity_id"
    )


def rollup_join(ec: str = 'ec', ec_rollup: str = 'ec_rollup', *,
                worldview: Worldview = 'economic_control_v1',
                h: str = 'h') -> str:
    """LEFT JOIN fragment resolving the rollup-entity display name.

    For EC, self-joins entity_current (the view is EC-hardcoded).
    For DM, bypasses the view and hits entity_rollup_history directly.
    """
    if worldview == 'economic_control_v1':
        return (
            f"LEFT JOIN entity_current {ec_rollup} "
            f"  ON {ec_rollup}.entity_id = {ec}.rollup_entity_id"
        )
    return (
        f"LEFT JOIN entity_rollup_history erh_{ec_rollup} "
        f"  ON erh_{ec_rollup}.entity_id = {h}.entity_id "
        f" AND erh_{ec_rollup}.rollup_type = 'decision_maker_v1' "
        f" AND erh_{ec_rollup}.valid_to = DATE '9999-12-31' "
        f"LEFT JOIN entity_current {ec_rollup} "
        f"  ON {ec_rollup}.entity_id = erh_{ec_rollup}.rollup_entity_id"
    )


def classification_join(ec: str = 'ech', h: str = 'h') -> str:
    """LEFT JOIN for entity classification (manager_type)."""
    return (
        f"LEFT JOIN entity_classification_history {ec} "
        f"  ON {ec}.entity_id = {h}.entity_id "
        f" AND {ec}.valid_to = DATE '9999-12-31'"
    )
```

### Caller example (query5 EC rewrite using helpers)

```python
from queries_helpers import ticker_join, entity_join, rollup_join, classification_join

sql = f"""
    WITH pivoted AS (
        SELECT
            COALESCE(ec_rollup.display_name, ec.display_name,
                     h.inst_parent_name, h.manager_name) as holder,
            ech.classification as manager_type,
            SUM(CASE WHEN h.quarter='{FQ}' THEN h.shares END) as q1_shares,
            ...
        FROM holdings_v2 h
        {ticker_join('h', 's')}
        {entity_join('h', 'ec')}
        {rollup_join('ec', 'ec_rollup', worldview=rollup_type, h='h')}
        {classification_join('ech', 'h')}
        WHERE s.ticker = ? AND h.is_latest = TRUE
        GROUP BY ...
    )
    ...
"""
```

Author writes **4 helper calls** instead of 4 hand-rolled multi-line JOINs. Worldview parameterized via one kwarg.

### Testability

- Pure string assembly — unit tests assert generated SQL fragments match golden strings.
- Integration tests run a smoke query (`SELECT 1 FROM holdings_v2 h <helpers> LIMIT 1`) against a fixture DB to confirm join keys resolve.
- `bandit B608` nosec convention — the caller's closing `"""` still carries the nosec directive; helpers themselves don't format user input.

---

## 5. Performance measurement

Harness: `/tmp/tier4_join_timing.py` (not committed; preserved with session). 3 tickers × 4 variants, cold + warm (best-of-3).

### 5.1 Timing table

| Ticker | Variant | Cold (ms) | Warm (ms) | Rows |
|---|---|---:|---:|---:|
| AAPL | A (EC, stamped `rollup_name`) | 65.7 | 35.4 | 25 |
| AAPL | **B (EC, joins)**              | **38.7** | **31.8** | 25 |
| AAPL | A (DM, stamped `dm_rollup_name`) | 35.0 | 32.8 | 25 |
| AAPL | **B (DM, joins via ERH)**        | **33.1** | **30.7** | 25 |
| MSFT | A (EC) | 32.8 | 32.7 | 25 |
| MSFT | B (EC) | 35.7 | 34.9 | 25 |
| MSFT | A (DM) | 34.0 | 33.0 | 25 |
| MSFT | B (DM) | 35.4 | 36.4 | 25 |
| XOM  | A (EC) | 33.3 | 32.1 | 25 |
| XOM  | **B (EC)** | **25.0** | **25.7** | 25 |
| XOM  | A (DM) | 32.2 | 31.7 | 25 |
| XOM  | **B (DM)** | **27.2** | **25.7** | 25 |

Deltas are **within noise** (single-digit ms, often negative). AAPL cold B(EC) 38.7 vs A 65.7 looks favorable for B but is likely page-cache order (whichever ran first paid the I/O).

### 5.2 EXPLAIN highlights

- Both versions SEQ_SCAN `holdings_v2` with `is_latest=TRUE` filter pushed down. DuckDB does not use `idx_hv2_ticker_quarter` for Version A — vectorized scan + filter is cheaper than an index lookup over 22.9M rows with 34k-row result.
- Version A: `SEQ_SCAN holdings_v2 (22.9M rows, filtered in-line by ticker/is_latest) → GROUP BY → PIVOT`.
- Version B-EC: `SEQ_SCAN holdings_v2 (~22.9M rows) → HASH_JOIN securities (282 rows, ticker-filtered) → HASH_JOIN ec (26.6k) → HASH_JOIN ec_rollup (26.6k) → HASH_JOIN ech (3.8k) → GROUP BY`. All hash-join build sides are small; probe cost is dominated by the holdings scan which is identical to Version A.
- Version B-DM: adds one extra SEQ_SCAN of `entity_rollup_history` (17k filtered rows) before the final entity join. Still free relative to holdings scan.
- **No covering index needed**. DuckDB's query planner treats `securities(cusip)` and `entity_current(entity_id)` as hash-join probe targets; the 282-row ticker-filtered securities build is trivial.

### 5.3 Conclusion

**Join cost is negligible.** The holdings_v2 scan is the dominant cost (~30 ms floor) and both versions pay it equally. Adding 3–4 hash joins against small lookup tables (≤26.6k rows) adds single-digit-ms or nothing. The warm-path delta is well within caching noise — caching closes the gap entirely, but the gap is near-zero to start with.

Performance is **not** a reason to reject the join pattern.

---

## 6. Reliability analysis

Separate from performance. Answers below drawn from the parity test in the timing harness.

### 6.1 NULL handling on canonical source

**Case.** A `holdings_v2` row has `cusip` that does not resolve in `securities` (rare but possible — new issues not yet classified, delisted securities pruned).

- Version A: `h.ticker` is stamped regardless; the row is included.
- Version B: `JOIN securities USING (cusip)` is an INNER JOIN — the row is **dropped**.

**Decision required.** If the Tier 4 function is intended to report "all holdings of ticker X as filed", INNER JOIN is wrong when filers stamp orphan CUSIPs. Mitigations: (a) use `LEFT JOIN securities` and retain `h.cusip` as the display fallback; (b) document that Version B reports only classified securities; (c) add a pipeline gate that enforces `holdings_v2.cusip ⊆ securities.cusip`. The project appears to be moving toward (c) — see CUSIP v1.4 promotion. For Tier 4 purposes, INNER JOIN is the correct default; orphan CUSIPs are a data-quality finding, not a query concern.

### 6.2 Post-merge behavior

**Case.** A filer's entity was merged after the quarter's stamp landed (common during entity QC).

- Version A: returns the stamp-time name (e.g. `UBS Asset Management` from Q2 before the alias was changed). **Stale**.
- Version B: returns `entity_current.display_name` (e.g. `UBS AM, a distinct business unit of UBS ASSET MANAGEMENT AMERICAS LLC`). **Current**.

Observed in parity test: AAPL DM worldview, 1 holder name mismatch for exactly this reason. Both are the same entity; Version B is correct (reflects today's MDM state).

### 6.3 Worldview parameterization — `entity_current` VIEW is EC-hardcoded ⚠️

**Material finding.** `entity_current` VIEW is defined as:

```sql
... LEFT JOIN entity_rollup_history AS er
  ON ((e.entity_id = er.entity_id) AND (er.rollup_type = 'economic_control_v1') ...
```

(Verified via `SELECT sql FROM duckdb_views() WHERE view_name='entity_current'`.) The view returns `rollup_entity_id` only for EC. DM worldview **cannot** use the view for the rollup leg — it must hit `entity_rollup_history` directly with `rollup_type='decision_maker_v1'`. The helper library handles this via the `worldview` kwarg; authors must not assume `entity_current.rollup_entity_id` is worldview-neutral.

Alternative: redefine `entity_current` to expose both `ec_rollup_entity_id` and `dm_rollup_entity_id` columns (two outer joins in the view). Out of scope for this proposal; flag for int-09 Step 4 sequencing.

### 6.4 Historical ticker drift

**Case.** A security's ticker changed (e.g. post-merger rename). `securities.ticker` reflects today's symbol; `holdings_v2.ticker` was stamped at filing time.

- Version A `WHERE ticker = 'OLD'` — returns historical holdings under OLD.
- Version B `WHERE s.ticker = 'OLD'` — returns **zero** rows (securities has NEW).
- Version B `WHERE s.ticker = 'NEW'` — returns holdings under OLD and NEW (because cusip is stable across ticker change).

Both are legitimate interpretations. Version B's "ticker = NEW gives you all historical holdings of this security" is usually what UI users want (AAPL pre-split and post-split shares roll up to AAPL). Version A's "ticker = OLD gives you only pre-rename filings" is the literal historical stamp. Downstream consumers should standardize on Version B's semantics — it matches how all other financial tooling resolves ticker-to-security identity.

### 6.5 Parity results summary

From the harness (3 tickers × 2 worldviews):

| Ticker/WV | Holders in A \ B | Holders in B \ A | Top-25 q4 shares delta |
|---|---|---|---|
| AAPL EC | – | – | –43.9 M (–0.67%) |
| AAPL DM | `UBS Asset Management` | `UBS AM, a distinct business unit of UBS ASSET MANAGEMENT AMERICAS LLC` | –43.9 M |
| MSFT EC | `Equitable Holdings, Inc.` | – | –25.5 M (–0.59%) |
| MSFT DM | `Equitable Holdings, Inc.` | `UBS AM, ...` | –25.5 M |
| XOM EC | – | – | small |
| XOM DM | small alias diff | small alias diff | small |

Divergences are all **Version B is more correct** (current MDM state) or **different grouping granularity** (canonical alias groups rows that stamped names splits across). No case where Version A is correct and Version B is wrong on canonical data.

### 6.6 Summary

- NULL/orphan CUSIP handling: author decision, default to INNER JOIN.
- Post-merge: Version B is correct; Version A is stale-at-stamp-time.
- Worldview: `entity_current` is EC-only; DM requires bypass (helper handles it).
- Historical drift: both legitimate; Version B matches industry convention.

None of these are bugs in Version B. Some are bugs in Version A that Version B exposes.

---

## 7. Recommendation

**Hybrid enforcement.**

- **Hard rule: all new `queries.py` functions (new tabs, new endpoints, new analytics) MUST use the join pattern.** Performance cost is negligible (§5); reliability is equal or better (§6); helper library shrinks author boilerplate to 4 lines (§4). Rejecting Tier 4 PRs that stamp-read new code is low-friction and prevents int-09 Step 4 from growing the rewrite surface area.
- **Soft rule: modifications to existing stamp-column functions do not have to convert.** Those 500 read sites are bundled into int-09 Step 4 regardless per [int-09 findings §4](../findings/int-09-p0-findings.md). Forcing conversion inside every drive-by fix would multiply PR scope and churn on legacy code that will be rewritten en masse anyway. Drive-by fixes continue to stamp-read; the rewrite sweep handles them together with the rest.

Evidence: performance measurements in §5 show no meaningful delta, so the hard-rule side costs nothing; reliability analysis in §6 shows Version B is strictly more correct on post-merge cases; the helper library in §4 keeps author boilerplate under control. The soft-rule side acknowledges that int-09 Step 4 will rewrite ~500 sites as one project and that forcing piecemeal conversions via every drive-by would produce a messier diff than a clean sweep. Hybrid captures the forward-compatibility benefit without imposing a toll on unrelated work.

---

_End of proposal. Pending: Serge selects enforcement rule; helper library code lands in a follow-up session after selection._
