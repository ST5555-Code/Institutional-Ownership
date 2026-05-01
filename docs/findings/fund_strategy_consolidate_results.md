# Fund-Strategy Consolidate — Results (PR-3)

**Branch:** `fund-strategy-consolidate`
**HEAD at start:** `dc23328` (PR-2 classifier-name-patterns)
**Scope:** Drop the redundant `fund_universe.fund_category` and
`fund_universe.is_actively_managed` columns, add a single canonical
constants module for the active/passive split, rewrite every fund-level
filter / projection site to use `fund_strategy`, and clean up the PR-2
write-path lock so it tracks only the canonical column.

After this PR `fund_strategy` is the sole truth-bearing fund-level
classification column. Both derived columns are gone. Active-only
filters across queries reference `ACTIVE_FUND_STRATEGIES` /
`PASSIVE_FUND_STRATEGIES` from `scripts/queries/common.py`. The pipeline
lock continues to protect canonical values from drift.

---

## 1. Phase 1 — Audit

### 1a. Code grep (categorised)

| File | Line(s) | Category | Action |
|---|---|---|---|
| `scripts/queries/cross.py` | 158 (filter) | FILTER | rewrite |
| `scripts/queries/cross.py` | 423 (SELECT projection) | READ | rewrite |
| `scripts/queries/cross.py` | 664 (SELECT projection) | READ | rewrite |
| `scripts/queries/fund.py` | 91 (filter) | FILTER | rewrite |
| `scripts/queries/flows.py` | 219, 326 (filters) | FILTER | rewrite |
| `scripts/queries/trend.py` | 43, 343 (filters) | FILTER | rewrite |
| `scripts/queries/trend.py` | 349, 351 (aggregate split) | FILTER | rewrite |
| `scripts/build_entities.py` | 241 (SELECT projection) | READ | rewrite to derive from `fund_strategy` |
| `scripts/pipeline/load_nport.py` | 1084, 1119–1120, 1180, 1217–1218 | WRITE | strip `fund_category` / `is_actively_managed` from prod write path |
| `tests/pipeline/test_load_nport.py` | 131–132, 759–1131 | TEST | strip both columns from fixture DDL + assertions |
| `scripts/queries/cross.py` (lines 158–160, 451–453) | comment only | DOC | comment update |
| `scripts/queries/trend.py:349`, `scripts/queries/common.py` | comment only | DOC | comment update |
| `scripts/oneoff/*` (validators, backfill, reclassify, dera-stabilize) | various | HISTORICAL | left as-is — historical scripts already executed |
| `scripts/retired/*` (promote_nport, fetch_nport_v2, fetch_nport) | various | RETIRED | left as-is |
| `scripts/fix_fund_classification.py` | 64–127 | LEGACY | left as-is — purpose-killed by PR-3 (deletion deferred) |
| `scripts/resolve_pending_series.py` | 251, 354, 360, 376, 683, 685 | STAGING | reads `stg_nport_fund_universe.is_actively_managed` (staging schema retained) |
| `scripts/fetch_dera_nport.py` | 134, 685, 789, 797 | STAGING | writes to staging only — staging schema retained |
| `scripts/pipeline/nport_parsers.py` | 154–198 | LOCAL VAR | classifier still returns `(is_active_equity, fund_category, is_actively_managed)` tuple — staging consumers unchanged |
| `scripts/pipeline/load_nport.py` (other) | 443, 474, 503, 511, 513, 631, 650–651, 682–683, 706, 732, 739, 741 | STAGING | writes to staging tables only |

The plan listed 6 fund-level filter sites; the audit found three additional
sites (cross.py:423/664 SELECT projections + build_entities.py:241 SELECT
projection of `is_actively_managed`). All three have been migrated to derive
the boolean from `fund_strategy IN ACTIVE_FUND_STRATEGIES`. The plan's STOP
condition (unexpected WRITE site outside `load_nport.py` /
`fix_fund_classification.py`) was not triggered.

Staging schemas (`stg_nport_fund_universe`, `stg_nport_holdings`) keep the
two columns by design — the classifier still emits them and the staging
table accepts them, but the prod upsert no longer reads them. This was
the smallest cleanup that produces a single canonical fund-level column
without blast-radius into the DERA + N-PORT classifier write paths.

### 1b. Data identity hard gate — `fund_strategy = fund_category`

```sql
SELECT
  COUNT(*) AS total_rows,
  COUNT(CASE WHEN fund_strategy = fund_category THEN 1 END) AS identical,
  COUNT(CASE WHEN fund_strategy != fund_category THEN 1 END) AS divergent,
  COUNT(CASE WHEN fund_strategy IS NULL OR fund_category IS NULL THEN 1 END) AS null_either
FROM fund_universe;
```

| total_rows | identical | divergent | null_either |
|---:|---:|---:|---:|
| 13,623 | 13,623 | 0 | 0 |

PASS — `fund_category` is verified perfectly redundant with `fund_strategy`.

### 1c. Data identity hard gate — `is_actively_managed` derivation

```sql
WITH expected AS (
  SELECT series_id,
         CASE WHEN fund_strategy IN ('equity','balanced','multi_asset')
              THEN TRUE ELSE FALSE END AS expected_active
  FROM fund_universe
)
SELECT
  COUNT(*) AS total_rows,
  COUNT(CASE WHEN fu.is_actively_managed = e.expected_active THEN 1 END) AS matching,
  COUNT(CASE WHEN fu.is_actively_managed != e.expected_active THEN 1 END) AS mismatched,
  COUNT(CASE WHEN fu.is_actively_managed IS NULL THEN 1 END) AS null_flag
FROM fund_universe fu JOIN expected e ON fu.series_id = e.series_id;
```

| total_rows | matching | mismatched | null_flag |
|---:|---:|---:|---:|
| 13,623 | 13,623 | 0 | 0 |

PASS — `is_actively_managed` is verified a perfect projection of
`fund_strategy IN ACTIVE_FUND_STRATEGIES`.

### 1d. fund_strategy distribution (pre-migration)

| `fund_strategy` | Rows | Active? |
|---|---:|:---:|
| `equity` | 4,832 | ✓ |
| `excluded` | 3,681 | |
| `bond_or_other` | 2,751 | |
| `passive` | 1,517 | |
| `balanced` | 567 | ✓ |
| `multi_asset` | 221 | ✓ |
| `final_filing` | 54 | |
| **Total** | **13,623** | |

Active total: 5,620. Passive total: 8,003. Sum = 13,623. No gap, no overlap.

---

## 2. Phase 2 — Canonical constants

[scripts/queries/common.py](scripts/queries/common.py:291-301) — added two
tuples adjacent to the existing `_fund_type_label` helper:

```python
ACTIVE_FUND_STRATEGIES = ('equity', 'balanced', 'multi_asset')
PASSIVE_FUND_STRATEGIES = (
    'passive', 'bond_or_other', 'excluded', 'final_filing'
)
```

`_fund_type_label` was updated in lock-step to derive its `'active'` label
from `ACTIVE_FUND_STRATEGIES` directly (eliminates the previously-inlined
3-string list).

New unit tests in [tests/test_queries_common.py](tests/test_queries_common.py)
(4 tests, all green):

- `test_active_fund_strategies_value` — pins the tuple.
- `test_passive_fund_strategies_value` — pins the tuple.
- `test_partitions_cover_all_canonical_values_with_no_overlap` — asserts
  `active ∪ passive == 7 canonical values` and `active ∩ passive == ∅`.
- `test_fund_type_label_uses_active_partition` — confirms the helper now
  routes through the constants.

---

## 3. Phase 3 — Query rewrites + parity

Six filter / aggregate sites rewritten to use `fund_strategy IN (...)`.
Three additional read sites surfaced during the audit and rewritten the
same way.

### Filter parity (live `data/13f.duckdb`, captured 2026-05-01 pre-migration)

| Site | Old expression | Old count | New expression | New count |
|---|---|---:|---|---:|
| cross.py:158 | `COALESCE(fu.is_actively_managed, TRUE) = TRUE` | 5,620 | `fu.fund_strategy IN ('equity','balanced','multi_asset')` | 5,620 |
| fund.py:91 | `fu.is_actively_managed = true` | 5,620 | `fu.fund_strategy IN (active_set)` | 5,620 |
| trend.py:351 (passive arm) | `fu.is_actively_managed = false` | 8,003 | `fu.fund_strategy IN (passive_set)` | 8,003 |
| holdings JOIN active | `fu.is_actively_managed = TRUE` (latest only) | 5,236,150 | `fu.fund_strategy IN (active_set)` (latest only) | 5,236,150 |

All four parities exact (zero delta).

### Aggregate split — `ownership_trend_summary` (trend.py)

```python
SUM(CASE WHEN fu.fund_strategy IN ({active_ph})
         THEN fh.market_value_usd ELSE 0 END) as active_value,
SUM(CASE WHEN fu.fund_strategy IN ({passive_ph})
         THEN fh.market_value_usd ELSE 0 END) as passive_value
```

Live AAPL parity check (last 3 quarters):

| quarter | old active_value | new active_value | diff |
|---|---:|---:|---:|
| 2025Q3 | 219.4766B | 219.4766B | 6.1×10⁻⁵ |
| 2025Q4 | 262.8445B | 262.8445B | 6.1×10⁻⁵ |
| 2026Q1 | 63.05996B | 63.05996B | 6.1×10⁻⁵ |

All deltas sub-cent (floating-point rounding only).

### Cross.py `is_active` projection rewrite

The previous query selected `fu.is_actively_managed AS is_active`. The
rewrite uses a 3-way `CASE` so `NULL` semantics are preserved (the front-end
treats `None` as "active" — included in active-only views — which matters
for series missing from `fund_universe`):

```sql
CASE WHEN fu.fund_strategy IN ({active_ph}) THEN TRUE
     WHEN fu.fund_strategy IS NULL THEN NULL
     ELSE FALSE
END as is_active
```

### build_entities.py — fund classification source

[scripts/build_entities.py:239–254](scripts/build_entities.py:239-254) —
`step2_create_fund_entities` now reads:

```sql
SELECT series_id, fund_name, family_name,
       CASE WHEN fund_strategy IN ('equity','balanced','multi_asset')
            THEN TRUE
            WHEN fund_strategy IS NULL
            THEN NULL
            ELSE FALSE
       END AS is_active
FROM fund_universe
```

The downstream `step6_populate_classifications` uses the boolean to assign
`'active'` / `'passive'` / `'unknown'` to fund entities — semantics match
the pre-migration mapping for every row (data identity gate at §1c).

---

## 4. Phase 4 — Test suite (pre-migration)

```
$ python3 -m pytest tests/ -x --no-header -q
...
373 passed, 1 warning in 52.91s
```

All 373 tests pass against the (pre-migration) DB after the query +
constants changes. No regressions.

---

## 5. Phase 5 — Schema migration

Flask not running. Direct DuckDB rebuild on `data/13f.duckdb`:

```sql
BEGIN TRANSACTION;
CREATE TABLE fund_universe_new AS
SELECT
  fund_cik, fund_name, series_id, family_name,
  total_net_assets,
  total_holdings_count, equity_pct, top10_concentration,
  last_updated, fund_strategy, best_index,
  strategy_narrative, strategy_source, strategy_fetched_at
FROM fund_universe;
-- row count parity check: 13,623 == 13,623
-- null fund_strategy check: 0
DROP TABLE fund_universe;
ALTER TABLE fund_universe_new RENAME TO fund_universe;
CREATE UNIQUE INDEX fund_universe_pk ON fund_universe(series_id);
COMMIT;
```

| Check | Result |
|---|---|
| old row count | 13,623 |
| new row count | 13,623 |
| null fund_strategy | 0 |
| Migration | committed |

Post-migration columns (no `fund_category`, no `is_actively_managed`):
`fund_cik, fund_name, series_id, family_name, total_net_assets,
total_holdings_count, equity_pct, top10_concentration, last_updated,
fund_strategy, best_index, strategy_narrative, strategy_source,
strategy_fetched_at` — 14 columns (was 16).

---

## 6. Phase 6 — Lock-code cleanup

[scripts/pipeline/load_nport.py:1050–1233](scripts/pipeline/load_nport.py:1050)

- `_apply_fund_strategy_lock`: prod SELECT now reads only
  `series_id, fund_strategy`; the staging UPDATE on
  `stg_nport_fund_universe` writes only `fund_strategy` (the staging
  schema still has `fund_category` but the lock no longer touches it).
- `_upsert_fund_universe`: staging SELECT now skips `fund_category` and
  `is_actively_managed`. Prior-value SELECT reads only `fund_strategy AS
  prior_fund_strategy`. INSERT writes only `fund_strategy` (with the
  COALESCE safety net).

Three new unit tests updated in
[tests/pipeline/test_load_nport.py](tests/pipeline/test_load_nport.py):
fixture DDL (`DDL_FUND_UNIVERSE`) drops both columns; `_seed_universe_row`
no longer takes `fund_category` and writes `NULL` for both staging-only
columns; the three branch tests (A new series / B existing locked /
C NULL backfill) assert on `fund_strategy` alone. All 27 nport tests pass
(5 lock + 22 unrelated). Full pipeline test suite (227 tests) green.

---

## 7. Phase 7 — Validation

Started Flask on port 8001, ran
`scripts/oneoff/validate_fund_strategy_consolidate.py`:

```
=== schema — fund_universe ===
  [PASS] fund_category column dropped
  [PASS] is_actively_managed column dropped
  [PASS] fund_strategy column present

=== data — fund_universe ===
  [PASS] row count preserved — observed=13623 expected=13623
  [PASS] fund_strategy non-null on every row

=== active-filter parity — fund_universe ===
  [PASS] active count matches pre-migration baseline — observed=5620 expected=5620
  [PASS] passive count matches pre-migration baseline — observed=8003 expected=8003
  [PASS] partitions cover every row (no gap, no overlap) — sum=13623 total=13623

=== active-filter parity — fund_holdings_v2 (is_latest) ===
  [PASS] active holdings count matches pre-migration baseline — observed=5236150 expected=5236150

=== queries.common — constants tests ===
  [PASS] pytest constants tests — 4 passed in 0.23s

=== pipeline lock — unit tests ===
  [PASS] pytest pr2_lock tests — 5 passed, 22 deselected, 1 warning in 0.53s

=== source grep — dropped columns in active code ===
  [PASS] no active read of is_actively_managed
  [PASS] no active read of fund_category

=== smoke test — affected endpoints ===
  [PASS] GET /api/v1/portfolio_context?ticker=AAPL&level=fund — status=200 bytes=10575
  [PASS] GET /api/v1/cross_ownership?tickers=AAPL&level=fund — status=200 bytes=3911
  [PASS] GET /api/v1/holder_momentum?ticker=AAPL&level=fund — status=200 bytes=5747
  [PASS] GET /api/v1/cohort_analysis?ticker=AAPL&active_only=true — status=200 bytes=7381
  [PASS] GET /api/v1/ownership_trend_summary?ticker=AAPL — status=200 bytes=1593

=== summary ===
  db_checks      : PASS
  constants_tests: PASS
  lock_tests     : PASS
  source_grep    : PASS
  smoke_test     : PASS
  overall        : PASS
```

Spot-check: `fund_universe` row for Invesco QQQ Trust still carries
`fund_strategy='passive'` (locked from PR-2). The rewritten queries
correctly classify it as a passive fund through the new
`fund_strategy IN PASSIVE_FUND_STRATEGIES` predicate.

---

## 8. Files changed

| File | Change |
|---|---|
| `scripts/queries/common.py` | New `ACTIVE_FUND_STRATEGIES` / `PASSIVE_FUND_STRATEGIES` tuples; `_fund_type_label` now derives `'active'` arm from `ACTIVE_FUND_STRATEGIES` |
| `scripts/queries/cross.py` | Replaced 1 filter (line 158) and 2 SELECT projections (423, 664) with `fund_strategy IN (...)` predicates; 3-way CASE preserves `NULL → None` semantics for `is_active` |
| `scripts/queries/fund.py` | Replaced 1 filter (line 91) |
| `scripts/queries/flows.py` | Replaced 2 filters (lines 219, 326) |
| `scripts/queries/trend.py` | Replaced 2 filters (43, 343) + 2-arm aggregate split (349, 351) |
| `scripts/build_entities.py` | Step 2.6 now derives the active flag from `fund_strategy IN ('equity','balanced','multi_asset')` (column dropped) |
| `scripts/pipeline/load_nport.py` | `_apply_fund_strategy_lock` writes only `fund_strategy`; `_upsert_fund_universe` reads/writes only `fund_strategy`; docstrings + PR-3 cleanup notes added |
| `tests/test_queries_common.py` | New — 4 tests pinning the constants and partitioning invariants |
| `tests/pipeline/test_load_nport.py` | DDL drops both columns; helper signature simplified; 3 lock branch tests assert only on `fund_strategy` |
| `scripts/oneoff/validate_fund_strategy_consolidate.py` | New — schema + parity + lock-test + source-grep + FastAPI smoke validator |
| `docs/findings/fund_strategy_consolidate_results.md` | This file |
| `ROADMAP.md` | PR-3 moved to COMPLETED, header bump |

Schema change: `fund_universe` rebuilt on prod `data/13f.duckdb` — drops
`fund_category VARCHAR` and `is_actively_managed BOOLEAN`; row count
13,623 preserved; primary key restored on `series_id`.

---

## 9. Out of scope (per plan)

- Renaming `equity` → `active` and `fund_holdings_v2.fund_strategy` →
  `fund_strategy_at_filing` — PR-4.
- Fixing `compute_peer_rotation.py` to JOIN
  `fund_universe.fund_strategy` instead of
  `fund_holdings_v2.fund_strategy` — PR-4.
- Parent-level filter rewrites (12+ sites reading `entity_type` with
  hardcoded lists) — institution-level sequence.
- Position turnover detection (Stage B) — separate roadmap initiative.
- Retiring `scripts/fix_fund_classification.py` (its only purpose, the
  `is_actively_managed` backfill, is gone) — deferred follow-up; the
  script no longer runs end-to-end against prod.
- Cleaning up `fund_category` / `is_actively_managed` from staging
  schemas (`stg_nport_fund_universe`, `stg_nport_holdings`) — staging
  classifier writes still emit those columns; not propagated to prod, so
  effectively dead-write. Cleanup deferred to keep the blast radius
  bounded to prod.

---

## 10. Sequence

| PR | Status |
|---|---|
| PR-1a fund-strategy-backfill | done (2026-04-30) |
| PR-1b peer-rotation-rebuild | done (2026-04-30) |
| PR-1c classification-display-audit | done (2026-04-30) |
| PR-1d classification-display-fix | done (2026-05-01) |
| PR-1e index-to-passive | done (2026-05-01) |
| PR-2 classifier-name-patterns | done (2026-05-01) |
| **PR-3 fund-strategy-consolidate (this)** | **done (2026-05-01)** |
| PR-4 column rename + JOIN switch | next |
