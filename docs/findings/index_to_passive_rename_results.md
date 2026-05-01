# Index → Passive Rename — Results (PR-1e)

**Branch:** `index-to-passive`
**HEAD at start:** `f0e6c17` (PR-1d classification-display-fix)
**Scope:** Rename `fund_strategy` value `'index'` → `'passive'` across `fund_universe`, `fund_holdings_v2`, `peer_rotation_flows`, the classifier write path, and the display label utility. After this PR `'index'` is no longer used as a `fund_strategy` value anywhere in the system.

This closes the rename gap that PR-1d papered over with a display-time map (`fund_strategy='index'` → label `'passive'`). The data layer now stores the canonical name directly; the display layer is now an identity map for this case.

---

## 1. Pre-state (Phase 1 audit, baseline)

Baseline captured against prod `data/13f.duckdb` immediately after `f0e6c17`, before any UPDATEs.

| Table | Filter | Rows |
|---|---|---:|
| `fund_universe` | `fund_strategy='index'` | 1,264 |
| `fund_universe` | `fund_strategy='passive'` | 0 |
| `fund_holdings_v2` | `fund_strategy='index'` | 3,055,575 |
| `fund_holdings_v2` | `fund_strategy='passive'` | 0 |
| `peer_rotation_flows` | `level='fund' AND entity_type='index'` | 1,499,478 |
| `peer_rotation_flows` | `level='fund' AND entity_type='passive'` | 0 |
| `peer_rotation_flows` | `level='parent' AND entity_type='passive'` | 268,988 |

Total row counts (control totals):

| Table | Rows |
|---|---:|
| `fund_universe` | 13,623 |
| `fund_holdings_v2` | 14,568,775 |
| `peer_rotation_flows` | 17,490,106 (post-rebuild — see §5) |

`fund_universe` consistency:

| Check | Count |
|---|---:|
| `fund_strategy != fund_category` | 0 |
| `fund_strategy='index' AND is_actively_managed=TRUE` | 0 |
| `fund_strategy='passive' AND is_actively_managed=TRUE` | 0 (0 rows in `passive` pre-rename) |

**STOP condition not triggered.** Zero `'passive'` rows in either fund-level table; the only pre-existing `'passive'` rows are at the `peer_rotation_flows` parent level, which is the institution taxonomy and explicitly out of scope.

The plan estimated `~1,500` rows in `fund_universe` and `~1.5M` rows in `fund_holdings_v2`. Actual counts: 1,264 / 3,055,575. The `fund_holdings_v2` count is roughly 2× the plan estimate — note for downstream sequencing.

Backup verified at `data/backups/13f_backup_20260430_185107` (carried over from PR-1a). No new backup created per plan instruction.

---

## 2. Phase 2 — fund_universe + fund_holdings_v2 UPDATEs

Flask was not running. DuckDB had no other readers. UPDATEs executed in two transactions against `data/13f.duckdb`.

```sql
UPDATE fund_universe
SET fund_strategy = 'passive',
    fund_category = 'passive'
WHERE fund_strategy = 'index';

UPDATE fund_holdings_v2
SET fund_strategy = 'passive'
WHERE fund_strategy = 'index';
```

Runtime:

| Statement | Wall clock |
|---|---:|
| `fund_universe` UPDATE | 0.00 s |
| `fund_holdings_v2` UPDATE | 0.55 s |

Plan estimated 2-5 minutes for `fund_holdings_v2`; actual was sub-second on M-series local DuckDB.

`is_actively_managed` was deliberately not touched. PR-1a's invariant (`index → is_actively_managed=FALSE`, `passive → is_actively_managed=FALSE`) makes the boolean identical across the rename — confirmed post-UPDATE: 0 rows of `fund_strategy='passive' AND is_actively_managed=TRUE`.

Post-UPDATE row counts (totals unchanged):

| Table | Total pre | Total post | Delta |
|---|---:|---:|---:|
| `fund_universe` | 13,623 | 13,623 | 0 |
| `fund_holdings_v2` | 14,568,775 | 14,568,775 | 0 |

Value migration (lossless):

| Table | `'index'` post | `'passive'` post |
|---|---:|---:|
| `fund_universe` | 0 | 1,264 |
| `fund_holdings_v2` | 0 | 3,055,575 |

`fund_universe` consistency post-UPDATE:

| Check | Count |
|---|---:|
| `fund_strategy != fund_category` | 0 |
| `fund_strategy='passive' AND is_actively_managed=TRUE` | 0 |

---

## 3. Phase 3 — Classifier write path

[scripts/pipeline/nport_parsers.py:148](scripts/pipeline/nport_parsers.py:148): in `classify_fund()` the early-return for `INDEX_PATTERNS` matches now returns `'passive'` instead of `'index'`. Inline comment notes the rename for future readers.

```diff
     # Exclusions (skip index AND ETF filters when --include-index is active)
+    # Note: 'index' was renamed to 'passive' in PR-1e (May 2026). The string 'index' is no longer used as a fund_strategy value.
     if not _include_index and INDEX_PATTERNS.search(series_name):
-        return False, "index", False
+        return False, "passive", False
```

Subsequent N-PORT classification runs will write `'passive'` as the canonical value; the data layer no longer accepts `'index'` from the pipeline.

`INDEX_PATTERNS` (the regex constant) is intentionally kept — it is the *detection* heuristic, not a value name. It identifies funds whose names look like passive index trackers.

---

## 4. Phase 4 — Display label utility

[scripts/queries/common.py:300](scripts/queries/common.py:300): `_fund_type_label()` is now an identity map for `'passive'`.

```diff
-    if fund_strategy == 'index':
-        return 'passive'
+    if fund_strategy == 'passive':
+        return 'passive'
```

Cross-codebase scan confirms no remaining `'index'` literal as a `fund_strategy` value across `scripts/queries/` or `scripts/pipeline/`. The two surviving matches are the new explanatory comment in `nport_parsers.py` and unrelated identifiers (`INDEX_PATTERNS`, `index_score`, etc.) which are filtered out by the validator code-check.

---

## 5. Phase 5 — peer_rotation_flows rebuild

```
python3 scripts/pipeline/compute_peer_rotation.py
```

Runtime breakdown (from log):

| Stage | Wall clock |
|---|---:|
| parse | 53.8 s |
| validate + snapshot | ~3 s |
| promote | 172.4 s |
| **total** | ~3.8 min |

- Run ID: `peer_rotation_empty_20260501_101345`
- Inserts: `17,490,106`
- Auto-snapshot: `data/backups/peer_rotation_peer_rotation_empty_20260501_101345.duckdb`
- Validate gates: PASS (0% row swing)

Post-rebuild fund-level distribution:

| `entity_type` | rows |
|---|---:|
| `equity` | 2,195,291 |
| `passive` | 1,499,478 |
| `excluded` | 614,942 |
| `balanced` | 474,067 |
| `multi_asset` | 186,532 |
| `bond_or_other` | 90,319 |
| `final_filing` | 4,571 |

Fund-level `index` rows after rebuild: **0**.
Fund-level `passive` rows: **1,499,478** — exactly matches the pre-rename `index` row count, as expected.

Parent-level (institution taxonomy) untouched — `passive=268,988` matches the pre-state baseline exactly.

---

## 6. Validation

`scripts/oneoff/validate_index_to_passive_rename.py` runs DB checks, source-tree code checks, and an optional Flask smoke test. Output:

```
=== fund_universe ===
  [PASS] no 'index' rows — observed=0
  [PASS] passive count matches pre-state index count — observed=1264 expected=1264
  [PASS] passive funds never flagged actively managed — observed=0
  [PASS] fund_strategy == fund_category for all rows — observed=0

=== fund_holdings_v2 ===
  [PASS] no 'index' rows — observed=0
  [PASS] passive count matches pre-state index count — observed=3055575 expected=3055575

=== peer_rotation_flows ===
  [PASS] no fund-level 'index' rows — observed=0
  [PASS] fund-level 'passive' rows > 0 — observed=1499478
  [PASS] parent-level 'passive' rows untouched — observed=268988 expected=268988

=== source — no 'index' fund_strategy literal in queries/pipeline ===
  [PASS] no fund_strategy='index' literal in scripts/queries or scripts/pipeline

=== smoke test (optional Flask endpoints) ===
  [PASS] GET /api/v1/portfolio_context?ticker=AAPL&level=fund — 10574 bytes
  [PASS] GET /api/v1/cross_ownership?tickers=AAPL&level=fund — 3910 bytes
  [PASS] GET /api/v1/holder_momentum?ticker=AAPL&level=parent — 32168 bytes
  [PASS] fund-level response carries type='passive'

=== summary ===
  db_checks    : PASS
  code_checks  : PASS
  smoke_test   : PASS
  overall      : PASS
```

Smoke test sample (top row of `/api/v1/portfolio_context?ticker=AAPL&level=fund`):

```
{
  "rank": 1,
  "institution": "VANGUARD TOTAL STOCK MARKET INDEX FUND",
  "type": "passive",
  ...
}
```

The `type='passive'` label now flows from a literal `fund_strategy='passive'` row through `_fund_type_label`'s identity arm — no rename gap.

---

## 7. Files changed

| File | Change |
|---|---|
| `scripts/pipeline/nport_parsers.py` | Classifier writes `'passive'` instead of `'index'` (+ rename comment) |
| `scripts/queries/common.py` | `_fund_type_label` reads canonical `'passive'` (was `'index'` → `'passive'` map) |
| `scripts/oneoff/validate_index_to_passive_rename.py` | New — DB + code + Flask smoke validator |
| `docs/findings/index_to_passive_rename_results.md` | This file |
| `ROADMAP.md` | PR-1e moved to COMPLETED, header bump |

---

## 8. Out of scope (per plan)

- Extending `INDEX_PATTERNS` for hidden index trackers (QQQ, Target Retirement, Primecap, leveraged ETFs) — PR-2.
- Dropping `fund_category` / `is_actively_managed` columns — PR-3.
- Renaming `equity` → `active`, `fund_holdings_v2.fund_strategy` → `fund_strategy_at_filing` — PR-4.
- Position turnover detection — Stage B.
- Parent-level display reads (`manager_type` / `entity_type`) — separate P2 item `parent-level-display-canonical-reads`.
- Per-quarter `fund_strategy` recompute drift (6,195 funds with multiple historical values across `fund_holdings_v2`) — separate Known Issue (pipeline lock + query JOIN).

---

## 9. Sequence

| PR | Status |
|---|---|
| PR-1a fund-strategy-backfill | done (2026-04-30) |
| PR-1b peer-rotation-rebuild | done (2026-04-30) |
| PR-1c classification-display-audit | done (2026-04-30) |
| PR-1d classification-display-fix | done (2026-05-01) |
| **PR-1e index-to-passive (this)** | **done (2026-05-01)** |
| PR-2 extend INDEX_PATTERNS | next |
| PR-3 drop fund_category / is_actively_managed | queued |
| PR-4 column rename + JOIN switch | queued |
