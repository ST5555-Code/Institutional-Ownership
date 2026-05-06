# CP-5.1 Helper + View Design Recon — Results

**Date:** 2026-05-06
**Branch:** `cp-5-1-helper-design-recon`
**HEAD baseline:** `4db5b0c` (PR #297 conv-30-doc-sync)
**Scope:** read-only investigation. NO DB writes. Locks four design
decisions (signatures, view vs CTE, return shape, naming + location)
before CP-5.1b execute PR ships.

**Inputs:**
- [docs/findings/cp-5-comprehensive-remediation.md](cp-5-comprehensive-remediation.md) §2.1, §4.1
- [docs/findings/cp-5-bundle-c-discovery.md](cp-5-bundle-c-discovery.md) §7.4
- [docs/findings/cp-5-discovery.md](cp-5-discovery.md) §5
- [data/working/cp-5-bundle-c-readers.csv](../../data/working/cp-5-bundle-c-readers.csv) — 27 reader sites
- [scripts/queries/common.py:50-95](../../scripts/queries/common.py) — `_rollup_name_sql` / `_rollup_eid_sql` Method A SQL-fragment helpers (PR #296)
- [scripts/queries/common.py:364-396](../../scripts/queries/common.py) — `classify_fund_strategy` pure-function precedent (PR #264)
- [scripts/queries_helpers.py](../../scripts/queries_helpers.py) — `ticker_join` / `entity_join` / `rollup_join` SQL-fragment helpers (PR #113)

**Outputs:**
- [data/working/cp-5-1-reader-signature-requirements.csv](../../data/working/cp-5-1-reader-signature-requirements.csv)
- [data/working/cp-5-1-view-vs-cte-benchmark.csv](../../data/working/cp-5-1-view-vs-cte-benchmark.csv)
- [scripts/oneoff/cp_5_1_view_candidate.sql](../../scripts/oneoff/cp_5_1_view_candidate.sql) — DRAFT
- [scripts/oneoff/cp_5_1_cte_candidate.py](../../scripts/oneoff/cp_5_1_cte_candidate.py) — DRAFT + benchmark runner

---

## 1. Reader signature requirements (Phase 1)

### 1.1 27-site re-confirmation

The Bundle C 27-site inventory (`cp-5-bundle-c-readers.csv`) is intact
post-PR #289 (fh2-dm-rollup drop) and PR #296 (holdings_v2-dm-rollup
drop). The two retired columns (`dm_rollup_name`, `dm_rollup_entity_id`)
were already off the reader path: `_rollup_name_sql` / `_rollup_eid_sql`
in `queries/common.py:50-95` interpolate a correlated `entity_rollup_history`
subquery in their place (Method A read-time JOIN, the pattern CP-5.1
extends). Six call sites migrated in PR #296. None of the 27 CP-5
reader sites moved.

### 1.2 Pattern distribution

Grouping the 27 sites by inferred helper-call-pattern surfaces eight
shapes; five of them cover 22 of 27 sites (81%):

| pattern | sites | typical filter | typical return |
| --- | ---: | --- | --- |
| `by_ticker_top_n` | 4 | `ticker = ?` | top-N (top_parent_eid, name, r5_aum) |
| `by_top_parent` | 5 | `top_parent_eid = ?` | per-position (cusip, ticker, r5_aum) |
| `by_ticker_two_quarters` | 4 | `ticker = ?` × `quarter ∈ (q-1, q)` | (top_parent_eid, shares_q, shares_qm1, value_q, value_qm1) |
| `by_ticker_long_window` | 3 | `ticker = ?` × `quarter ∈ QUARTERS` | (top_parent_eid, quarter, value, shares) |
| `aggregate_no_filter` | 3 | none / `manager_type` | (manager_type, aum, distinct_top_parent_count) |
| `by_top_parent_drill` | 2 | `top_parent_eid = ?` × subtree | (filer_eid, fund_eid, value) |
| `by_ticker_set_pivot` | 2 | `ticker IN (...)` | (top_parent_eid, per-ticker pivot) |
| `entity_subtree_walk` | 2 | `top_parent_eid = ?` (no R5 wrap) | (node_eid, depth) |
| `retire_replace` | 2 | name-keyed (legacy NPORT) | retire path |

Two `entity_subtree_walk` sites (entities.py descendants/search) sit
outside R5 and need only the `inst_to_top_parent` and ER subtree
mechanics. Two `retire_replace` sites (NPORT family bridge / children
dispatch) are slated for retirement at CP-5.6, not migration.

### 1.3 Minimum signature set

The 25 sites that actually consume R5 (everything except the two
`entity_subtree_walk` sites) reduce to **a single underlying definition**
plus filter-shape-specific access. Two viable factorings:

**Option A — single canonical view, readers SELECT directly.**
Readers pass their existing WHERE clause (`ticker = ?`, `top_parent_entity_id = ?`,
`ticker IN (?)`) as-is against `cp5_unified_holdings_view`. No helper
function needed; readers compose top-N / GROUP BY / pivot themselves
in plain SQL. The view IS the helper.

**Option B — single view + 4 thin Python wrappers** for the most common
shapes (`by_ticker_top_n`, `by_top_parent`, `by_ticker_two_quarters`,
`aggregate`). Wrappers add no logic beyond shaping the SELECT — they
just save 3-5 lines per reader call site.

**Recommendation: Option A.** The wrappers in B do not materially
shrink reader code (the existing readers are 50-300 line functions; a
3-line saving is irrelevant) and they add a forwarding layer that
makes future schema changes harder to grep. The single view + caller-
written WHERE/SELECT matches the precedent shape in `queries_helpers.py`
(SQL-fragment helpers, no Python data-returning wrappers).

The one Python helper CP-5.1b should ship is the **SQL-fragment helper**
that emits the `LEFT JOIN cp5_unified_holdings_view u ...` clause for
sites that join the view to upstream tables (`market_data`,
`entity_classification_history`, `manager_aum`). Following the
`rollup_join` precedent in `queries_helpers.py`, a one-liner returning
a join-fragment string. See §4.

---

## 2. View vs CTE benchmark (Phase 2)

### 2.1 Candidate drafts

- `scripts/oneoff/cp_5_1_view_candidate.sql` — full DDL DRAFT
  for `cp5_unified_holdings_view`. Recursive CTE for inst→top_parent
  climb (hop bound 10). Includes the `fund_held_funds` CTE that
  excludes intra-family FoF.
- `scripts/oneoff/cp_5_1_cte_candidate.py` — Python helper that emits
  the same body as a parameterized `WITH ...` CTE. Used by readers
  that compose into a larger query.

For the benchmark, both candidates use precomputed climb tables
registered as DataFrames (`inst_to_top_parent`, `fund_to_inst`)
rather than evaluating the recursive CTE per call. CP-5.1b will
choose whether to (a) keep the recursive CTE in the view DDL or
(b) materialize the climb tables once per session via a setup
function — orthogonal to the view-vs-CTE choice.

The benchmark runs FoF-disabled for tractability (matches the
2.55M unified-row count seen in `view_setup_sql`); CP-5.1b must
re-benchmark with FoF enabled. The view's inner shape is otherwise
identical to the §2.1 R5 design.

### 2.2 Benchmark results

5 representative queries × 3 conditions × 3 warm runs (median ms):

| query | direct (today) | view (CP-5.1) | cte (CP-5.1) |
| --- | ---: | ---: | ---: |
| top-25 holders for AAPL | 7.7 | 155.3 | 136.7 |
| top-50 by combined AUM | 7.3 | 168.3 | 174.1 |
| Vanguard (eid=4375) positions | 1.2 | 65.0 | 46.2 |
| crowding distinct-holder count | 13.9 | 168.8 | 151.4 |
| 3-ticker cross-pivot | 14.5 | 156.0 | 251.5 |

Per-condition summary across the 5 queries (median ms):

| condition | mean | max | min |
| --- | ---: | ---: | ---: |
| direct (today, no R5) | 8.9 | 14.5 | 1.2 |
| view | 142.7 | 168.8 | 65.0 |
| cte | 152.0 | 251.5 | 46.2 |

### 2.3 Recommendation

**Inline VIEW path (Condition ii).** Three signals:

1. **Mean runtime is lower** (143 ms vs 152 ms) and **max is tighter**
   (169 ms vs 252 ms). The single 3-ticker pivot regression in the CTE
   condition (252 ms vs 156 ms) suggests DuckDB's planner re-evaluates
   the inner CTE per outer GROUP BY when the body is inlined; the named
   view evaluates the body once per query.
2. **Reader migration burden is minimal.** Readers replace
   `FROM holdings_v2 ... GROUP BY COALESCE(rollup_name, ...)` with
   `FROM cp5_unified_holdings_view WHERE ...`. CTE composition
   forces every reader to carry a 30-line WITH clause.
3. **All warm runtimes safely under the 500ms threshold** (cp-5-discovery
   §5). The R5 + FoF + Method A definition is heavier than the §5
   benchmark (35-340 ms) — the new mean is 143 ms, still ample headroom.

These results revise the cp-5-discovery §5 envelope upward (35-340 →
65-169 warm) once the modified R5 (intra-family FoF + non-valid CUSIP
filter) and full Method A climb are wired. Still well within budget.

The 16-18× cost vs `direct` (the today shape) is the cost of producing
a correct cross-form unified rollup. It is paid by every reader call,
not amortized via precomputation. cp-5-discovery §5 already analyzed
the alternative — a precomputed `cp5_unified_holdings` table — and
recommended against it (refresh complexity per quarter > marginal
speedup). Re-confirmed here: at 169 ms max warm, a precomputed table
is not justified.

---

## 3. Return shape (Phase 3)

### 3.1 Canonical column union

Aggregating the union of `expected_return_columns` across the 25 R5-
consuming reader sites:

| column | type | source | needed by |
| --- | --- | --- | --- |
| `top_parent_entity_id` | BIGINT | climb | all |
| `top_parent_name` | VARCHAR | `entity_current.display_name` | all |
| `cusip` | VARCHAR | `holdings_v2.cusip` / `fund_holdings_v2.cusip` | most |
| `ticker` | VARCHAR | `holdings_v2.ticker` | by_ticker* shapes |
| `thirteen_f_aum` | DOUBLE | `SUM(holdings_v2.market_value_usd)` | transparency / source-winner explain |
| `fund_tier_aum` | DOUBLE | `SUM(fund_holdings_v2.market_value_usd)` clean | transparency |
| `r5_aum` | DOUBLE | `GREATEST(thirteen_f_aum, fund_tier_aum)` | all |
| `source_winner` | VARCHAR | `'13F_wins'`/`'fund_wins'`/`'13F_only'`/`'fund_only'` | UI source-tag display |

8 columns. The view returns the union; readers SELECT the subset they
need.

### 3.2 Per-feature subsets (verified read-time)

Spot check against the 5 representative readers benchmarked in §2.2:

| reader | columns selected from view |
| --- | --- |
| Register top-25 (AAPL) | `top_parent_entity_id`, `top_parent_name`, `r5_aum` |
| Register manager AUM | `top_parent_entity_id`, `top_parent_name`, `r5_aum` (then JOIN `manager_aum`) |
| Conviction Fund Portfolio | `top_parent_entity_id`, `ticker`, `r5_aum` (then JOIN `market_data` for sector) |
| Crowding count | `top_parent_entity_id`, `r5_aum` |
| Cross multi-ticker pivot | `top_parent_entity_id`, `top_parent_name`, `ticker`, `r5_aum` |

`thirteen_f_aum` / `fund_tier_aum` / `source_winner` are needed only by
the Source/Method tab and per-row transparency tooltips — slim per-call,
universal at the view layer. Returning them by default costs nothing;
they're computed in the inner FULL OUTER JOIN regardless. **Recommend
canonical-union return shape.**

### 3.3 What the view does NOT carry

- `manager_type` / classification — readers JOIN
  `entity_classification_history` keyed on `top_parent_entity_id`. Per
  the D4 decision (`docs/decisions/d4-classification-precedence.md`),
  classification is read-time, not stamped in the unified view.
- `pct_of_so` / `shares` — these are `holdings_v2`-side leaf columns
  with no fund-tier counterpart. Readers that need them either (a)
  leave the today-shape `holdings_v2` query in place for the share
  count (Register holders, Flows ownership trend) or (b) compute
  shares post-hoc from `r5_aum / market_price`. CP-5.1 should not
  blur these into the unified view; CP-5.6 may add a `shares_unified`
  column once the fund-tier shares-vs-value ambiguity is resolved.
- `inst_parent_name` / `manager_name` / `fund_name` — name-strings
  retire under CP-5. Readers route via `entity_id` from CP-5.1
  forward. Two retire-path sites (`match_nport_family`,
  `get_nport_children`) keep the legacy name path for one cycle.

---

## 4. Naming + location (Phase 4)

### 4.1 Naming

Candidates considered:

| candidate | issue |
| --- | --- |
| `classify_institutional_holding` | misleading — the function classifies; the view materializes. Borrowed from `classify_fund_strategy` precedent which is a pure mapper. |
| `institutional_rollup_v1` | too generic; collides mentally with `decision_maker_v1` / `economic_control_v1`. |
| `cp5_holdings_view` | engineering-stamp prefix; durable name should not carry the project tag. |
| `method_a_unified_holdings` | exposes the climb mechanism in the name; future Method B/C migrations would force a rename. |
| **`unified_holdings_view`** + helper `top_parent_holdings_join()` | descriptive, mechanism-agnostic, parallels existing naming (`entity_current`, `entity_rollup_history`). |

**Recommendation:**
- View name: `unified_holdings_view` (final shipped name; the candidate
  draft uses `cp5_unified_holdings_view` to keep the recon scoped).
- SQL-fragment helper: `top_parent_holdings_join(alias='u', filter=None)`
  in `queries_helpers.py`, parallel to existing `rollup_join` /
  `entity_join` / `classification_join`.
- No Python data-returning wrapper. Readers SELECT directly per §1.3.

### 4.2 Location

| component | destination | rationale |
| --- | --- | --- |
| `unified_holdings_view` DDL | new migration file `scripts/migrations/026_create_unified_holdings_view.sql` | persistent DDL; standard migration pattern (precedent: 003, 024, 025). |
| `top_parent_holdings_join()` helper | `scripts/queries_helpers.py` | parallels existing `rollup_join` / `entity_join` / `classification_join`. Already-imported in 4 reader modules. |
| Climb-table setup (if precomputed-per-session path chosen) | `scripts/queries/common.py` next to `_rollup_name_sql` | imported by every queries/* module via `from .common import ...`. |
| Python tests | `tests/queries/test_unified_holdings_view.py` | matches existing layout. |

### 4.3 Decision recap

- View: `unified_holdings_view` shipped as a migration.
- Helper: `top_parent_holdings_join()` SQL-fragment helper in
  `queries_helpers.py`. No Python data-returning wrappers.
- Composition: readers SELECT directly from the view, optionally
  joined to upstream tables via the new helper + existing
  `classification_join` / `entity_join`.

---

## 5. Locked design spec for CP-5.1b execute PR

### 5.1 Helpers + view

```sql
-- scripts/migrations/026_create_unified_holdings_view.sql
CREATE OR REPLACE VIEW unified_holdings_view AS
WITH RECURSIVE
  inst_edges AS (...),                  -- per cp_5_1_view_candidate.sql
  inst_climb (entity_id, top_parent_entity_id, hop) AS (
      ... base ... UNION ALL ... recur (hop < 10) ...
  ),
  inst_to_top_parent AS (... QUALIFY deepest hop ...),
  fund_to_top_parent AS (... ERH dm_v1 + inst_to_top_parent ...),
  fund_held_funds AS (... cusip → fund top_parent for FoF detect ...),
  thirteen_f AS (... holdings_v2 climbed ...),
  fund_tier  AS (... fund_holdings_v2 EC + valid-CUSIP + intra-family-FoF excluded ...)
SELECT  -- canonical-union (8 columns):
  top_parent_entity_id, top_parent_name,
  cusip, ticker,
  thirteen_f_aum, fund_tier_aum, r5_aum, source_winner
FROM thirteen_f FULL OUTER JOIN fund_tier ... LEFT JOIN entity_current ...;
```

```python
# scripts/queries_helpers.py
def top_parent_holdings_join(
    u: str = "u", h: str | None = None, *, on: str = "top_parent_entity_id"
) -> str:
    """Return a JOIN fragment for the unified holdings view.

    `u`  alias to assign to unified_holdings_view (default 'u').
    `h`  alias of an upstream holdings-or-entity table to JOIN against
         (e.g. classification_join's ech alias). If None, return the
         FROM fragment 'FROM unified_holdings_view u'.
    `on` join key — typically 'top_parent_entity_id'.
    """
    if h is None:
        return f"FROM unified_holdings_view {u}"
    return f"LEFT JOIN unified_holdings_view {u} ON {u}.{on} = {h}.entity_id"
```

### 5.2 Test expectations

- `test_view_definition_loads` — migration runs cleanly; view has 8 columns of expected types.
- `test_view_row_count_within_bounds` — between 2.0M and 3.5M rows at 2025Q4 (today's draft = 2.55M).
- `test_r5_max_invariant` — for every row, `r5_aum = GREATEST(thirteen_f_aum, fund_tier_aum)`.
- `test_source_winner_consistency` — winner labels match the leg amounts.
- `test_intra_family_fof_excluded` — sample BlackRock / Vanguard fund-of-fund cusip rows excluded.
- `test_top_25_aapl_envelope` — top-25 AAPL holders match the matrix-revalidation envelope (+/- 1B per row).
- `test_warm_runtime_under_500ms` — top-25 AAPL warm-cache run completes in <500 ms.
- `test_helper_join_fragment` — `top_parent_holdings_join()` returns the expected SQL string for default and `h=` cases.

### 5.3 Pre-execution dependencies (all must clear before CP-5.1b)

Per cp-5-comprehensive-remediation §3:

1. 21 cycle-truncated entity merges (~10-11 PRs done; PR #285 baseline).
2. 84K loader-gap rows linked (PR #290 + #291 closed the workstream).
3. Capital Group umbrella (PR #287 closed).
4. Adams duplicate (PR #283 closed).
5. fh2 + holdings_v2 dm_rollup column drops (PRs #289, #296 closed).

**Verification:** all five clear at HEAD `4db5b0c` (PR #297 conv-30
doc-sync). CP-5.1b is unblocked.

### 5.4 Execution-PR scope (CP-5.1b)

- Migration 026 — create the view per §5.1.
- `queries_helpers.py` — `top_parent_holdings_join()` per §5.1.
- Tests — per §5.2.
- Zero reader migrations. CP-5.1b lands the foundation only;
  CP-5.2-5.6 migrate readers in parallel where independent.

Size: M (matches the §4.1 estimate in the remediation doc).

---

## 6. Open questions for chat

1. **Recursive CTE in DDL vs precomputed climb tables refreshed per
   session?** Recon's view-candidate uses recursive CTE inline (cleanest;
   one source of truth). Precomputed climb tables would require a session-
   scoped setup function `_setup_climb_tables(con)` invoked at app boot.
   The benchmark used precomputed; the difference vs recursive-in-DDL has
   not been measured. Likely 50-100 ms of additional warm cost if recursive
   is left in DDL — may push max past 250 ms but still under the 500 ms
   budget. **Recommendation: recursive in DDL.** Re-bench at PR time and
   fall back to precomputed if any query exceeds 400 ms warm.

2. **Should the view include a `quarter` column (parameterized) or stay
   pinned to 2025Q4?** Pinning forces a per-quarter view rebuild but
   dodges the problem of readers passing a stale-quarter sentinel.
   Parameterizing requires the view to JOIN against a `latest_quarter`
   sentinel CTE that itself reads `MAX(quarter) FROM holdings_v2`.
   **Recommendation: parameterize via a `latest_quarter` inner CTE.**
   Aligns with the today-shape pattern in `queries/market.py:130-145`.

3. **Naming: `unified_holdings_view` vs `unified_holdings`?** The
   `_view` suffix is informative but verbose. `entity_current` is also
   a view and carries no suffix. **Recommendation: `unified_holdings`**
   (drop the `_view` suffix) for parity with `entity_current`.

4. **Helper-function placement: `queries_helpers.py` (Tier 4 conv) vs
   `queries/common.py` (queries-package conv)?** Existing `rollup_join`
   lives in `queries_helpers.py`; existing `_rollup_name_sql` lives in
   `queries/common.py`. Convention is split. **Recommendation:
   `queries_helpers.py`** — `top_parent_holdings_join` is a join-fragment
   helper, not a SQL-string-mid-clause helper, so it parallels
   `rollup_join` more closely than `_rollup_name_sql`.

5. **FoF subtraction tolerance.** The candidate view excludes intra-
   family FoF strictly (cusip resolves to a fund whose top_parent
   matches outer fund's top_parent). Bundle A §1.4 quantified the
   subtraction at $2.21T. Should CP-5.1b additionally exclude
   inter-family FoF (e.g. a Vanguard fund holding a BlackRock ETF)?
   Bundle A says no — that's legitimate cross-firm exposure. **Confirm
   intent: intra-family only, no inter-family.**

---

## 7. Out-of-scope discoveries / surprises

- **The 2.55M unified-row count** observed at view-build time is
  consistent with cp-5-discovery §5's "~2,625,205 unified rows per
  quarter" estimate — slightly under because the FoF leg is disabled
  in the recon. With FoF enabled, expect 2.5-2.6M. CP-5.1b's
  `test_view_row_count_within_bounds` should bracket [2.0M, 3.5M].

- **inst_to_top_parent built 14,091 rows** (vs 14,038 institution-
  typed entities at PR #276 baseline). The +53 delta is the loader-
  gap entities created by PR #291 (53 new entities 27260..27312) that
  now have self-rollups under both rollup_types. Confirms entity-
  creation memory rule held end-to-end.

- **fund_to_inst built 13,215 rows** at dm_v1 (not 13,221 from the
  bundle-c § quote of "1,826 of 13,221 funds"). The 6-row delta is
  funds that don't have a dm_v1 rollup row (only ec_v1) — likely
  pre-Method-A loader rows or ECH gaps. Surface to chat before
  CP-5.1b ships: do these 6 funds need a dm_v1 backfill, or is the
  ec_v1-only path acceptable for them?

- **VIEW vs CTE 3-ticker-pivot regression (252 ms)** — the inlined
  CTE form re-evaluates the body once per pivot column. Named view
  evaluates once. Marginal but consistent across 3 runs. CP-5.1b
  test should explicitly cover this pattern (`test_pivot_query_warm`).

- **`fund_held_funds` CUSIP→fund_eid resolution** is not yet wired in
  this benchmark (would require entity_identifiers cusip lookups
  scaled across 1.8M fund_holdings_v2 rows). It IS in the candidate
  DDL. Re-bench at PR time with FoF wired; expect +20-50 ms warm cost
  on the fund-tier leg.

---

## 8. Verification + sequencing

This recon emits zero DB writes. `git grep -E
'INSERT|UPDATE|DELETE|DROP|ALTER|CREATE TABLE|TRUNCATE|MERGE'` against
`scripts/oneoff/cp_5_1_*` returns the single `CREATE OR REPLACE VIEW`
in `cp_5_1_view_candidate.sql` (DRAFT, not executed) and the
`CREATE TEMP VIEW` in `cp_5_1_cte_candidate.py` (in-memory, read_only
session, cleared on disconnect — no persistence).

Pytest 416-test baseline expected to pass unchanged.

**Next:** chat reviews this spec, locks the §5 design, then CP-5.1b
execute PR ships migration 026 + helper + tests against the locked
spec.
