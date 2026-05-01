# Fund-Strategy Rename — Results (PR-4)

**Branch:** `fund-strategy-rename`
**HEAD at start:** `928e7ab` (PR-3 fund-strategy-consolidate)
**Scope:**

1. Rename value `'equity'` → `'active'` across `fund_universe`,
   `fund_holdings_v2`, `peer_rotation_flows`, classifier, constants, tests.
2. Rename column `fund_holdings_v2.fund_strategy` →
   `fund_strategy_at_filing` to make snapshot semantics explicit.
3. Architectural fix: `compute_peer_rotation.py` JOINs
   `fund_universe.fund_strategy` instead of reading point-in-time
   `fund_holdings_v2.fund_strategy`.

After PR-4 the fund-level consolidation sequence closes.

---

## 1. Phase 1 — Audit

### 1a. Code grep — value `'equity'` in active code

| File | Line(s) | Category | Action |
|---|---|---|---|
| `scripts/queries/common.py` | 301 | CONSTANT | Phase 5 — `ACTIVE_FUND_STRATEGIES` tuple |
| `scripts/queries/trend.py` | 431 | LEGACY-COMPAT | Phase 4 — `_ACTIVE_FUND_TYPES` tuple includes legacy `equity`/`mixed`; clean to canonical (`active`,`balanced`,`multi_asset`) |
| `scripts/pipeline/nport_parsers.py` | 195 | VALUE WRITE | Phase 3 — `category = "equity"` → `"active"`; 167 already mentions PR-1e rename |
| `scripts/pipeline/nport_parsers.py` | 44 | DOC | Phase 3 — comment update |
| `scripts/build_entities.py` | 245 | VALUE READ | Phase 3 — CASE expression checks `fund_strategy IN ('equity','balanced','multi_asset')` |
| `tests/test_queries_common.py` | 17, 30 | TEST | Phase 5 — assert new tuple |
| `tests/pipeline/test_load_nport.py` | 944, 947, 975, 980, 1004, 1008, 1011, 1049, 1052, 1097, 1100, 1127, 1139 | TEST | Phase 6 — fixtures + assertions |

Other `'equity'` matches across the repo refer to a **different domain** —
`security_type_inferred` / `security_type_override` / yahoo `classify_ticker`
in `scripts/auto_resolve.py`, `scripts/build_classifications.py`,
`scripts/pipeline/cusip_classifier.py`, `scripts/queries/register.py`,
`scripts/approve_overrides.py`, `scripts/retired/*` — all unrelated to
fund-level `fund_strategy` and **explicitly out of scope**.

`scripts/oneoff/*` and `scripts/retired/*` historical scripts
(validate_fund_strategy_backfill.py, validate_classifier_patterns.py,
validate_peer_rotation_rebuild.py, reclassify_with_new_patterns.py,
backfill_fund_strategy.py, validate_fund_strategy_consolidate.py) retain
`'equity'` references — these are historical artefacts (already executed
once) and per PR-3 plan are left as-is. Same precedent as PR-3 §1.

STOP gate (write site outside `nport_parsers.py`/`load_nport.py`): not
triggered.

### 1b. Code grep — `fund_holdings_v2.fund_strategy` in active code

```bash
grep -rn "fund_holdings_v2\.fund_strategy\|\bfh\.fund_strategy\|\bfh2\.fund_strategy" \
  --include="*.py" scripts/ tests/ | grep -v scripts/oneoff | grep -v scripts/retired
```

| File | Line | Category | Action |
|---|---|---|---|
| `scripts/pipeline/load_nport.py` | 1059 | DOC (docstring) | Phase 11 — rename to `fund_strategy_at_filing` |
| `scripts/migrations/019_peer_rotation_flows.py` | 18 | DOC (comment) | Phase 11 — historical migration, comment update |
| `scripts/pipeline/compute_peer_rotation.py` | 430, 547, 565 | READ — to fix in Phase 7 |

`compute_peer_rotation.py` is the only **functional** reader of
`fund_holdings_v2.fund_strategy` outside the write path. Per PR-1c audit
(`docs/findings/nport_classification_scoping.md`) this is the
peer-rotation drift channel that PR-4 Phase 7 closes via JOIN to
`fund_universe`.

`load_nport.py` writes the column at line 752 (per PR-1c §6.1) — this is
the sole live write path; it reads `s.fund_strategy` from
`stg_nport_holdings`. After Phase 10 the prod column is renamed to
`fund_strategy_at_filing`; the write-path needs the column-name update.

### 1c. Schema audit

| Table | `fund_strategy` | `fund_strategy_at_filing` |
|---|:-:|:-:|
| `fund_universe` | ✓ | — |
| `fund_holdings_v2` | ✓ | — |
| `stg_nport_fund_universe` | (in `13f_staging.duckdb`, not prod) | — |
| `stg_nport_holdings` | (in `13f_staging.duckdb`, not prod) | — |

`fund_strategy_at_filing` does not exist anywhere in prod. STOP gate not
triggered.

The two staging tables live in `data/13f_staging.duckdb`, not in the
prod `data/13f.duckdb`. Per PR-3 §9 ("Out of scope: Cleaning up staging
schemas"), staging cleanup is deferred. Phase 10's optional staging
rename is therefore **skipped**.

`fund_holdings_v2` has 29 columns; `fund_strategy` is index 19.
Indexes on the table:

| Index | Columns | Type |
|---|---|---|
| `idx_fhv2_entity` | `entity_id` | secondary |
| `idx_fhv2_rollup` | `rollup_entity_id, quarter` | secondary |
| `idx_fhv2_series` | `series_id, quarter` | secondary |
| `idx_fh_v2_accession` | `accession_number` | secondary |
| `idx_fh_v2_latest` | `is_latest, report_month` | secondary |
| `idx_fund_holdings_v2_row_id` | `row_id` | UNIQUE |

All six must be recreated after the Phase 10 rebuild.

### 1d. peer_rotation_flows source audit

`scripts/pipeline/compute_peer_rotation.py`:

- **Line 430** — `_materialize_fund_agg`: `MAX(fund_strategy) AS fund_strategy`
  reading from `fund_holdings_v2`. This is the entry point and the only
  place the column is *read* from `fund_holdings_v2`.
- **Line 547** — `_insert_fund_flows` current-quarter side:
  `c.fund_strategy AS entity_type`, where `c` is the `f_agg_pair` temp
  table from line 430.
- **Line 565** — `_insert_fund_flows` prior-quarter side: `p.fund_strategy
  AS entity_type`, same temp table.

Phase 7 fix: replace line 430's read of `fund_holdings_v2.fund_strategy`
with a JOIN to `fund_universe.fund_strategy`. Lines 547/565 keep their
shape because they read from the temp `f_agg_pair` table.

### 1e. Pre-state distributions (live `data/13f.duckdb`, 2026-05-01)

**`fund_universe.fund_strategy`** (13,623 rows, no NULLs):

| value | rows | active? |
|---|---:|:---:|
| equity | 4,832 | ✓ |
| excluded | 3,681 | |
| bond_or_other | 2,751 | |
| passive | 1,517 | |
| balanced | 567 | ✓ |
| multi_asset | 221 | ✓ |
| final_filing | 54 | |
| **total** | **13,623** | |

Active total: 5,620. Passive total: 8,003. Sum 13,623, no gap, no overlap.

**`fund_holdings_v2.fund_strategy`** (14,568,775 rows, no NULLs):

| value | rows |
|---|---:|
| bond_or_other | 4,264,287 |
| equity | 3,555,766 |
| passive | 3,242,518 |
| excluded | 1,809,797 |
| balanced | 998,831 |
| multi_asset | 683,196 |
| final_filing | 14,380 |
| **total** | **14,568,775** |

**`peer_rotation_flows` fund-level** (5,065,200 rows):

| entity_type | rows |
|---|---:|
| equity | 2,159,208 |
| passive | 1,658,866 |
| excluded | 614,942 |
| balanced | 379,560 |
| multi_asset | 157,737 |
| bond_or_other | 90,316 |
| final_filing | 4,571 |
| **total** | **5,065,200** |

`peer_rotation_flows` parent-level kept for reference only — out of scope
(institution-level taxonomy, separate sequence).

STOP conditions for Phase 1:
- (a) No unexpected category in 1a/1b — **PASS**
- (b) `fund_strategy_at_filing` does not exist — **PASS**
- (c) `compute_peer_rotation.py` references match documented 3 lines —
  **PASS**
- (d) All values in 1e canonical (no `'active'`/`'mixed'`/`'index'` legacy
  residue) — **PASS**

Audit OK. Proceeding to Phase 2.

---

## 2. Phase 2 — Value rename in data tables

`UPDATE fund_universe SET fund_strategy='active' WHERE fund_strategy='equity'`
and the same on `fund_holdings_v2`, in a single transaction.

| Table | rows updated | residual `equity` | post-update `active` |
|---|---:|---:|---:|
| `fund_universe` | 4,832 | 0 | 4,832 |
| `fund_holdings_v2` | 3,555,766 | 0 | 3,555,766 |

Totals preserved: `fund_universe` 13,623; `fund_holdings_v2` 14,568,775.
COMMIT.

---

## 3. Phase 3 — Classifier write path

[scripts/pipeline/nport_parsers.py:195](scripts/pipeline/nport_parsers.py:195)
— `category = "equity"` → `"active"`. Module docstring + a stale comment
in the INDEX_PATTERNS block updated for consistency. The 3-tuple return
signature is unchanged (`is_active_equity, fund_category,
is_actively_managed`); only the second element's string value flips.

---

## 4. Phase 4 + Phase 5 — Constants, label utility, supporting reads

| File | Change |
|---|---|
| [scripts/queries/common.py:301](scripts/queries/common.py:301) | `ACTIVE_FUND_STRATEGIES = ('active','balanced','multi_asset')` |
| [scripts/queries/trend.py:431](scripts/queries/trend.py:431) | `_ACTIVE_FUND_TYPES` cleaned to canonical only `('active','balanced','multi_asset')`; legacy `'equity'` and `'mixed'` dropped |
| [scripts/build_entities.py:245](scripts/build_entities.py:245) | inline CASE updated to `fund_strategy IN ('active','balanced','multi_asset')` |
| [tests/test_queries_common.py](tests/test_queries_common.py) | constant tuple + canonical 7-set asserts updated |

`_fund_type_label` already routes the active arm through
`ACTIVE_FUND_STRATEGIES` and needed no body change.

---

## 5. Phase 6 — Lock-code tests

[tests/pipeline/test_load_nport.py](tests/pipeline/test_load_nport.py) —
fixture seed values for the 3 PR-2 lock branch tests (A new series /
B existing locked / C NULL backfill) updated from `'equity'` to
`'active'` (15 occurrences across `_seed_staging` rows,
`_seed_universe_row(fund_strategy=...)`, and assertion tuples). The lock
behaviour tests are value-agnostic; the test fixtures only need to be
canonical post-PR-4.

`scripts/pipeline/load_nport.py` lock helpers
(`_apply_fund_strategy_lock`, `_upsert_fund_universe`) carry no string
literal references to `'equity'` — the lock is value-passthrough so no
code update was required for the value rename portion.

---

## 6. Phase 7 — JOIN architectural fix

[scripts/pipeline/compute_peer_rotation.py:421-449](scripts/pipeline/compute_peer_rotation.py:421)
— `_materialize_fund_agg` rewritten to JOIN `fund_universe.fund_strategy`
(canonical, locked) instead of reading the per-row, per-quarter
`fund_holdings_v2.fund_strategy` snapshot:

```sql
-- before
SELECT series_id, MAX(fund_name), MAX(fund_strategy), ticker, quarter, ...
  FROM fund_holdings_v2

-- after
SELECT fh.series_id, MAX(fh.fund_name), MAX(fu.fund_strategy), fh.ticker, ...
  FROM fund_holdings_v2 fh
  LEFT JOIN fund_universe fu ON fh.series_id = fu.series_id
```

Lines 547 / 565 (consumer of `f_agg_pair`) are unchanged: they still read
`c.fund_strategy / p.fund_strategy AS entity_type` from the temp table,
but the temp table value now sources from `fund_universe`.

`LEFT JOIN` semantics preserve the prior behaviour for series_ids absent
from `fund_universe` (null fallback). The orphan-series cohort is
covered by the new `canonical-value-coverage-audit` follow-up logged in
ROADMAP (Out of scope §11).

---

## 7. Phase 8 — Test suite gate (pre-rebuild)

```
$ python3 -m pytest tests/ -x --no-header -q
...
373 passed, 1 warning in 56.46s
```

All 373 tests green against the (post-Phase-2) DB after Phase 3-7 code
changes. No regressions. Proceeding to rebuild.

---

## 8. Phase 9 — peer_rotation_flows rebuild

```
$ python3 -u scripts/pipeline/compute_peer_rotation.py
...
parse complete: 17,490,106 total rows in 61.9s
validate: level=fund rollup=economic_control_v1 rows=5,065,200
validate: level=parent rollup=decision_maker_v1 rows=6,212,453
validate: level=parent rollup=economic_control_v1 rows=6,212,453
run() complete: run_id=peer_rotation_empty_20260501_144941 (64.7s)
snapshot created: data/backups/peer_rotation_peer_rotation_empty_20260501_144941.duckdb
promoted: rows_upserted=17,490,106 (212.6s)
```

Total runtime ~4.6 min. Auto-snapshot at
`data/backups/peer_rotation_peer_rotation_empty_20260501_144941.duckdb`.

### Post-rebuild fund-level distribution

| entity_type | pre-PR-4 rows | post-PR-4 rows | Δ |
|---|---:|---:|---:|
| equity | 2,159,208 | 0 | -2,159,208 |
| **active** (new value) | — | **2,156,100** | +2,156,100 |
| passive | 1,658,866 | 1,658,866 | 0 |
| excluded | 614,942 | 614,942 | 0 |
| balanced | 379,560 | **382,668** | **+3,108** |
| multi_asset | 157,737 | 157,737 | 0 |
| bond_or_other | 90,316 | 90,316 | 0 |
| final_filing | 4,571 | 4,571 | 0 |
| **fund total** | **5,065,200** | **5,065,200** | **0** |

Net: 3,108 fund-level rows reclassified `active → balanced`. This is the
JOIN architectural-fix payload — for those 3,108 rows the holdings-layer
point-in-time snapshot disagreed with the canonical `fund_universe`
value, and the JOIN now serves canonical (`balanced`). Total row count
preserved (5,065,200); parent-level distribution unchanged
(12,424,906); overall total 17,490,106.

`peer_rotation_flows` legacy `equity` rows: 0 (the original drift class
is now structurally impossible — the rebuild reads from a locked source
and the old value no longer exists at any layer).

---

## 9. Phase 10 — Schema migration on `fund_holdings_v2`

DuckDB column rename via the rebuild pattern (`CREATE TABLE _new AS
SELECT ... fund_strategy AS fund_strategy_at_filing` → `DROP` →
`ALTER ... RENAME`):

```
pre-rebuild row count: 14,568,775
post-CTAS row count: 14,568,775
COMMIT (6.9s)

idx_fhv2_entity: 2.2s
idx_fhv2_rollup: 2.0s
idx_fhv2_series: 2.0s
idx_fh_v2_accession: 2.1s
idx_fh_v2_latest: 2.2s
idx_fund_holdings_v2_row_id: 1.0s (UNIQUE)
```

Row count preserved 14,568,775 ↔ 14,568,775. All 6 indexes restored
(post-state matches pre-state inventory). Total elapsed ~19s.

Staging schema cleanup (`stg_nport_holdings`,
`stg_nport_fund_universe`) intentionally **skipped** — those tables
live in `data/13f_staging.duckdb`, retain `fund_strategy` by design per
PR-3 §9, and are not propagated to prod. Carried forward as a deferred
cleanup item.

---

## 10. Phase 11 — Read-site updates after column rename

| File | Change |
|---|---|
| [scripts/pipeline/load_nport.py:125](scripts/pipeline/load_nport.py:125) | `_TARGET_TABLE_COLUMNS` — `("fund_strategy_at_filing","VARCHAR")` (drives both staging DDL and prod write contract) |
| [scripts/pipeline/load_nport.py:771-782](scripts/pipeline/load_nport.py:771) | INSERT INTO `fund_holdings_v2` target column + `s.fund_strategy AS fund_strategy_at_filing` (source kept on staging schema) |
| [scripts/pipeline/load_nport.py:1110](scripts/pipeline/load_nport.py:1110) | Lock UPDATE — `SET fund_strategy_at_filing = m.fund_strategy` (source still `m.fund_strategy` because the lock map carries prod's `fund_universe.fund_strategy`) |
| [scripts/pipeline/load_nport.py:1059](scripts/pipeline/load_nport.py:1059) | Docstring updated to reference `fund_strategy_at_filing` |
| [scripts/migrations/019_peer_rotation_flows.py:18](scripts/migrations/019_peer_rotation_flows.py:18) | Schema comment updated to reflect post-PR-4 source (`fund_universe.fund_strategy`) |
| [tests/pipeline/test_load_nport.py](tests/pipeline/test_load_nport.py) | 2 staging assertions updated to `SELECT DISTINCT fund_strategy_at_filing FROM fund_holdings_v2` |

Test fixture DDL (`DDL_FUND_HOLDINGS_V2`) derives from
`_TARGET_TABLE_COLUMNS` and updates automatically.

`scripts/oneoff/*` and `scripts/retired/*` historical scripts retain old
column references — out of scope per the PR-3 precedent.

---

## 11. Phase 12 — Final validation

```
$ python3 -m pytest tests/ -x --no-header -q
...
373 passed, 1 warning in 56.89s
```

All 373 tests pass after Phases 9-11 changes.

`scripts/oneoff/validate_fund_strategy_rename.py` — combined validator
covering value rename, column rename, constants, lock pytest, JOIN fix,
source grep, and Flask smoke. Output:

```
=== value rename — equity → active ===
  [PASS] fund_universe.fund_strategy='equity' — observed=0
  [PASS] fund_universe.fund_strategy='active' (>0) — observed=4832
  [PASS] fund_holdings_v2.fund_strategy_at_filing='equity' — observed=0
  [PASS] fund_holdings_v2.fund_strategy_at_filing='active' (>0) — observed=3555766
  [PASS] peer_rotation_flows fund equity — observed=0
  [PASS] peer_rotation_flows fund active (>0) — observed=2156100

=== column rename — fund_strategy → fund_strategy_at_filing ===
  [PASS] fund_strategy column dropped
  [PASS] fund_strategy_at_filing column present
  [PASS] row count preserved — 14,568,775
  [PASS] peer_rotation_flows total preserved — 17,490,106

=== constants — ACTIVE_FUND_STRATEGIES ===
  [PASS] ACTIVE_FUND_STRATEGIES == ('active', 'balanced', 'multi_asset')
  [PASS] active ∪ passive covers all 7 canonical values

=== pipeline lock — unit tests ===
  [PASS] 31 passed, 1 warning in 0.84s

=== JOIN architectural fix — compute_peer_rotation.py ===
  [PASS] _materialize_fund_agg JOINs fund_universe
  [PASS] no MAX(fund_strategy) read from holdings layer

=== source grep — legacy strings ===
  [PASS] no active code references to legacy 'equity' value
  [PASS] no active code references to fund_holdings_v2.fund_strategy

=== smoke test — affected endpoints ===
  [PASS] /api/v1/portfolio_context?ticker=AAPL&level=fund status=200 bytes=10582
  [PASS] /api/v1/cross_ownership?tickers=AAPL&level=fund status=200 bytes=3917
  [PASS] /api/v1/holder_momentum?ticker=AAPL&level=fund status=200 bytes=5754
  [PASS] /api/v1/cohort_analysis?ticker=AAPL&active_only=true status=200 bytes=7381
  [PASS] /api/v1/ownership_trend_summary?ticker=AAPL status=200 bytes=1593
  [PASS] /api/v1/peer_rotation?ticker=AAPL&level=fund status=200 bytes=13192
  [PASS] /api/v1/short_analysis?ticker=AAPL status=200 bytes=9909

=== summary ===
  overall        : PASS
```

Spot-check (`fund_universe`, post-rebuild):

| fund_name | series_id | fund_strategy |
|---|---|---|
| Invesco QQQ Trust, Series 1 | S000101292 | passive |
| Fidelity Contrafund | S000006037 | active |
| Fidelity Contrafund K6 | S000057289 | active |
| ProShares UltraPro QQQ | S000024908 | passive |
| ProShares Ultra QQQ | S000006827 | passive |
| ProShares UltraPro Short QQQ | S000024909 | bond_or_other |
| ProShares Short QQQ | S000006831 | bond_or_other |

Index/passive funds remain `passive` (PR-2 lock); the canonical active
funds now display the new `active` value end-to-end.

---

## 12. Files changed

| File | Change |
|---|---|
| `scripts/queries/common.py` | `ACTIVE_FUND_STRATEGIES = ('active','balanced','multi_asset')` + comment |
| `scripts/queries/trend.py` | `_ACTIVE_FUND_TYPES` cleaned to canonical-only |
| `scripts/build_entities.py` | inline CASE constant updated `equity → active` |
| `scripts/pipeline/nport_parsers.py` | classifier emits `'active'`; module docstring + comment update |
| `scripts/pipeline/load_nport.py` | column-name updates: `_TARGET_TABLE_COLUMNS`, fund_holdings_v2 INSERT (target), lock UPDATE target; lock docstring |
| `scripts/pipeline/compute_peer_rotation.py` | `_materialize_fund_agg` LEFT JOINs `fund_universe.fund_strategy` |
| `scripts/migrations/019_peer_rotation_flows.py` | schema comment updated |
| `tests/test_queries_common.py` | constant + canonical-set assertions updated |
| `tests/pipeline/test_load_nport.py` | 15 fixture/assertion updates for value rename + 2 column-name updates |
| `scripts/oneoff/validate_fund_strategy_rename.py` | NEW — PR-4 validator |
| `docs/findings/fund_strategy_rename_results.md` | this file |
| `ROADMAP.md` | header bump + PR-4 COMPLETED entry + new `canonical-value-coverage-audit` follow-up |

Schema changes:

- `fund_universe.fund_strategy` value rename (`equity → active`); 4,832 rows.
- `fund_holdings_v2.fund_strategy` value rename (`equity → active`); 3,555,766 rows.
- `fund_holdings_v2.fund_strategy` column rename to
  `fund_strategy_at_filing`; full table rebuild (14,568,775 rows
  preserved); all 6 indexes restored.
- `peer_rotation_flows` rebuilt — fund level 5,065,200 → 5,065,200;
  total 17,490,106 → 17,490,106; 3,108 rows reclassified active →
  balanced via the JOIN fix.

---

## 13. Out of scope (per plan)

- Parent-level value renames (institution-level taxonomy work) — separate
  sequence.
- Stage B turnover detection — separate roadmap initiative.
- Vanguard Primecap / Windsor II / Equity Income Stage B candidates —
  on roadmap.
- Retiring `scripts/fix_fund_classification.py` — its `is_actively_managed`
  backfill purpose was killed by PR-3; deferred cleanup PR.
- Cleaning `stg_nport_fund_universe` and `stg_nport_holdings` schemas —
  staging classifier writes still emit `fund_strategy`/`fund_category`
  but they no longer propagate to prod (effectively dead-write); cleanup
  deferred to keep blast radius bounded.
- **canonical-value-coverage-audit** — added to ROADMAP by PR-4, executed
  in a future PR. Scope: NULL `fund_strategy` audit on `fund_universe`,
  orphan series in `fund_holdings_v2` (no `fund_universe` row), the
  `series_id='UNKNOWN'` cohort, the SYN funds and BlackRock muni trusts
  edge sets, the 3-way `CASE` NULL semantics in `cross.py`, and rows
  where `fund_holdings_v2.fund_strategy_at_filing` differs from
  `fund_universe.fund_strategy` (i.e. quantify the historical drift the
  JOIN fix now papers over).

---

## 14. Sequence

| PR | Status |
|---|---|
| PR-1a fund-strategy-backfill | done (2026-04-30) |
| PR-1b peer-rotation-rebuild | done (2026-04-30) |
| PR-1c classification-display-audit | done (2026-04-30) |
| PR-1d classification-display-fix | done (2026-05-01) |
| PR-1e index-to-passive | done (2026-05-01) |
| PR-2 classifier-name-patterns | done (2026-05-01) |
| PR-3 fund-strategy-consolidate | done (2026-05-01) |
| **PR-4 fund-strategy-rename (this)** | **done (2026-05-01)** |

Fund-level consolidation sequence closed.
