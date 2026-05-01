# Classification Display Fix — Results (PR-1d)

**Branch:** `classification-display-fix`
**HEAD at start:** `4fe72dc` (PR-1c classification-display-audit)
**Scope:** Fund-level display reads only. Parent-level reads deferred to a new P2 roadmap item, `parent-level-display-canonical-reads`.

This PR closes the loop opened by PR-1a (canonical `fund_strategy` populated) and PR-1c (display read-site audit). After PR-1d the API/queries display layer reads `fund_universe.fund_strategy` directly, applies a single shared label utility, and the legacy name-keyword sweep `_classify_fund_type` is removed from the codebase.

---

## 1. Summary of changes

### New utility — single source of truth

`scripts/queries/common.py` adds `_fund_type_label(fund_strategy)`:

```python
def _fund_type_label(fund_strategy):
    if fund_strategy in ('equity', 'balanced', 'multi_asset'):
        return 'active'
    if fund_strategy == 'index':
        return 'passive'
    if fund_strategy == 'bond_or_other':
        return 'bond'
    if fund_strategy in ('excluded', 'final_filing'):
        return 'excluded'
    return 'unknown'
```

Output domain: `{active, passive, bond, excluded, unknown}`.

### Deleted

- `_classify_fund_type(fund_name)` (the name-keyword sweep) removed from `common.py`.
- Re-export from `scripts/queries/__init__.py` removed.
- Stale docstring reference in `scripts/fix_fund_classification.py` updated.

### Read sites migrated (12 sites across 5 files)

| File | Site | Before | After |
|---|---|---|---|
| `register.py:164` | query1 N-PORT children | `_classify_fund_type(institution)` | `_fund_type_label(k['fund_strategy'])` |
| `register.py:1230` | query16 fund-level register row | `_classify_fund_type(fund_name)` | `_fund_type_label(r['fund_strategy'])` |
| `register.py:1271` | query16 type_totals aggregator | `_classify_fund_type(trow['fund_name'])` | `_fund_type_label(trow['fund_strategy'])` |
| `cross.py:214` | `_cross_ownership_fund_query` | `'type': row['family_name'] or 'fund'` (family-name overload — UI-visible bug) | `_fund_type_label(row['fund_strategy'])`; `family_name` dropped from SELECT and response |
| `cross.py:290` | `get_cross_ownership_fund_detail` | `is_active` boolean → 3-bucket label map | `_fund_type_label(f['fund_strategy'])` |
| `cross.py:548` | `get_overlap_institution_detail` | `is_active` boolean → 3-bucket label map | `_fund_type_label(fund_strategy)` |
| `fund.py:278` | Conviction top-25 fund branch | `'active' if h_row.get('is_active') else 'passive'` (silently maps None → 'passive') | `_fund_type_label(h_row.get('fund_strategy'))` |
| `fund.py:366` | Conviction N-PORT child (no metrics) | `'active' if fund_is_active else 'passive'` | `_fund_type_label(fund_strategy_map.get(fund_name))` |
| `fund.py:386` | Conviction N-PORT child (with metrics) | `'active' if fund_is_active else 'passive'` | `_fund_type_label(fund_strategy_map.get(fund_name))` |
| `trend.py:84` | Holder Momentum top-25 fund branch | `_classify_fund_type(fn)` | `_fund_type_label(frow['fund_strategy'])` |
| `trend.py:303` | Holder Momentum parent-mode N-PORT children (D6) | `'type': None` (hardcoded — UI blank) | `_fund_type_label(child['fund_strategy'])` |
| `market.py:667` | `short_analysis.nport_detail` (D7) | `is_active` field + `_classify_fund_type` for type | `_fund_type_label(r['fund_strategy'])`; `is_active` field dropped |
| `market.py:692` | `short_analysis.nport_by_fund` (D7) | same | same |
| `market.py:827` | `short_analysis.short_only_funds` (D7) | same | same |

(13 logical sites, counted as 12 in the PR plan because the two `register.py:1229,1241` originally identified collapsed into a single edit at `register.py:1230` after the SQL change.)

### Helper functions extended

`get_nport_children_batch` and `get_nport_children` in `common.py` now SELECT `MAX(fu.fund_strategy)` and propagate it to the returned child-dict shape (`'fund_strategy': r.get('fund_strategy')`). This unblocks every endpoint that consumes the helper — including `register.py:164` (query1 N-PORT children) and any future fund-level child consumer — without re-querying `fund_universe`.

### Schema notes

- No DB writes. No schema changes. All changes are read-side display logic.
- `fund_universe.is_actively_managed` and `fund_universe.fund_category` remain in place. Predicates that still read `is_actively_managed` (the `active_only` filters in `cross.py:158`, `fund.py:91`, `flows.py:219/326`, `trend.py:43/335/341/343`, `market.py`) are intentionally untouched — those columns are scheduled to drop in PR-3.
- `fh.family_name` remains in `fund_holdings_v2` schema as metadata used by entity matching; only the response-layer overload at `cross.py:215` is removed.

### Decisions applied (from PR-1c §7)

| Decision | Choice | Where applied |
|---|---|---|
| D1 | (A) Read `fund_universe.fund_strategy` directly | every site above |
| D2 | New 5-bucket label map `{active, passive, bond, excluded, unknown}` | `_fund_type_label` |
| D3 | Delete `_classify_fund_type` entirely | `common.py:309-...` removed |
| D4 | NOT applied in this PR — parent-level reads unchanged | new roadmap item created |
| D5 | (A) Drop `family_name` overload, emit canonical label | `cross.py:214` |
| D6 | (A) Look up canonical label for Holder Momentum N-PORT children | `trend.py:303` |
| D7 | (A) Drop `is_active`, keep only canonical `type` | `market.py:667/692/827` |
| D8 | (B) Do NOT add `is_active` / `fund_strategy` to Conviction response | response shape unchanged |

---

## 2. Sample API responses (post-fix, fixture DB)

All samples taken against the committed CI fixture DB via FastAPI TestClient. Quarter is whatever the fixture's latest is.

### `/api/v1/cross_ownership?tickers=AAPL&level=fund`

Pre-fix bug at `cross.py:215`: `'type': row['family_name'] or 'fund'` — UI rendered `Vanguard` / `BlackRock` etc. in the type column.

```json
{
  "investor": "VANGUARD TOTAL STOCK MARKET INDEX FUND",
  "type": "passive",
  "holdings": { "AAPL": 118946768892.86 },
  "total_across": 118946768892.86,
  "pct_of_portfolio": 31.6591
}
{
  "investor": "Vanguard 500 Index Fund",
  "type": "passive",
  "holdings": { "AAPL": 93231735609.6 },
  "total_across": 93231735609.6,
  "pct_of_portfolio": 30.9346
}
```

### `/api/v1/portfolio_context?ticker=AAPL&level=fund` (Conviction)

Pre-fix bug at `fund.py:277`: `'active' if h_row.get('is_active') else 'passive'` — every fund without a `fund_universe` row collapsed to `passive`.

```json
{ "rank": 1, "institution": "VANGUARD TOTAL STOCK MARKET INDEX FUND",
  "type": "passive", "value": 118946768892.86, "level": 0 }
{ "rank": 2, "institution": "Vanguard 500 Index Fund",
  "type": "passive", "value": 93231735609.6, "level": 0 }
```

`type=passive` here is now derived from `fund_strategy='index'` rather than name truthiness.

### `/api/v1/cross_ownership_fund_detail?tickers=AAPL&institution=Vanguard+Group&anchor=AAPL`

```json
{ "fund_name": "VANGUARD TOTAL STOCK MARKET INDEX FUND",
  "series_id": "S000002848", "type": "passive" }
{ "fund_name": "Vanguard 500 Index Fund",
  "series_id": "S000002839", "type": "passive" }
```

`is_active` is no longer surfaced in the response (was carried internally at `cross.py:274` pre-fix; now replaced with `fund_strategy` internally and dropped from the public surface).

### `/api/v1/holder_momentum?ticker=AAPL&level=parent`

Pre-fix bug at `trend.py:295`: child rows carried `'type': None` — UI showed a blank column under expanded parents.

```json
parent: { "rank": 1, "institution": "Vanguard Group",
          "type": "passive", "is_parent": true, "child_count": 5, "level": 0 }
child:  { "institution": "VANGUARD TOTAL STOCK MARKET INDEX FUND",
          "type": "passive", "level": 1 }
```

### `/api/v1/short_analysis?ticker=AAPL` — `nport_detail`

Pre-fix `market.py:642+668` emitted both `is_active` (boolean from `is_actively_managed`) and `type` (from `_classify_fund_type` name keywords). The two could disagree silently.

```json
{ "fund_name": "Calamos Phineus Long/Short Fund",
  "family_name": "Calamos Investment Trust /IL/",
  "type": "active",
  "short_shares": 93000.0, "short_value": 19304010.0, "pct_of_nav": 1.68 }
{ "fund_name": "Otter Creek Long/Short Opportunity Fund",
  "family_name": "Professionally Managed Portfolios",
  "type": "unknown",
  "short_shares": 18500.0, "short_value": 3840045.0, "pct_of_nav": 3.077 }
```

`is_active` field is no longer present. The `unknown` value is a faithful expression of the canonical state — Otter Creek's `series_id` resolves to a `fund_strategy` value outside the canonical bucket set (or no `fund_universe` row), and the label honours that rather than guessing from the name.

### `/api/v1/query1?ticker=AAPL` — Register N-PORT child

```json
{ "institution": "VANGUARD TOTAL STOCK MARKET INDEX FUND",
  "type": "passive", "level": 1, "source": "N-PORT" }
```

Pre-fix the same row carried `type='passive'` only because the fund name contains `INDEX` (name-sweep happened to be right); now it carries `type='passive'` because the canonical `fund_strategy='index'`. The two agree here, but the label is now derived deterministically from the DB rather than the fund name.

---

## 3. Validation

### `scripts/oneoff/validate_classification_display_fix.py`

New self-contained validator. Runs against `tests/fixtures/13f_fixture.duckdb` via FastAPI's `TestClient`. Hits 8 endpoint variants and asserts:

1. Every fund row carries a `type` field with value in `{active, passive, bond, excluded, unknown}`.
2. Cross-Ownership level=fund rows do NOT carry a fund family name (Vanguard, BlackRock, iShares, Fidelity, State Street, etc.) in the `type` column — regression guard for the pre-PR-1d `cross.py:215` bug.
3. `short_analysis` fund payloads (`nport_detail`, `nport_by_fund`, `short_only_funds`) do NOT include an `is_active` field — D7 contract collapse.
4. No response surfaces raw `fund_strategy` values to the public API contract (D8).

Parent-level rows (where `level == 0` and `is_parent` is true) are skipped on the canonical-types check because they carry the institution-level `manager_type` taxonomy — out of scope for PR-1d.

```
======================================================================
PR-1d classification display fix — endpoint contract validation
======================================================================

* portfolio_context fund
  GET /api/v1/portfolio_context?ticker=AAPL&level=fund
  [PASS] portfolio_context fund: all type values canonical
  [PASS] portfolio_context fund: no is_active field on fund rows
  [PASS] portfolio_context fund: no raw fund_strategy in response

* portfolio_context parent (N-PORT children)
  GET /api/v1/portfolio_context?ticker=AAPL&level=parent
  [PASS] all type values canonical
  [PASS] no is_active field on fund rows
  [PASS] no raw fund_strategy in response

* cross_ownership fund
  GET /api/v1/cross_ownership?tickers=AAPL&level=fund
  [PASS] all type values canonical
  [PASS] no fund family names in type column
  [PASS] no is_active field on fund rows
  [PASS] no raw fund_strategy in response

* cross_ownership_fund_detail
  GET /api/v1/cross_ownership_fund_detail?tickers=AAPL&institution=Vanguard Group&anchor=AAPL
  [PASS] all type values canonical
  [PASS] no is_active field on fund rows
  [PASS] no raw fund_strategy in response

* holder_momentum fund
  GET /api/v1/holder_momentum?ticker=AAPL&level=fund
  [PASS] all type values canonical
  [PASS] no is_active field on fund rows
  [PASS] no raw fund_strategy in response

* holder_momentum parent (children)
  GET /api/v1/holder_momentum?ticker=AAPL&level=parent
  [PASS] all type values canonical
  [PASS] no is_active field on fund rows
  [PASS] no raw fund_strategy in response

* short_analysis (nport_detail / by_fund / short_only)
  GET /api/v1/short_analysis?ticker=AAPL
  [PASS] all type values canonical
  [PASS] no is_active field on fund rows
  [PASS] no raw fund_strategy in response

* query1 register (N-PORT children)
  GET /api/v1/query1?ticker=AAPL
  [PASS] all type values canonical
  [PASS] no is_active field on fund rows
  [PASS] no raw fund_strategy in response

======================================================================
RESULT: PASS
======================================================================
```

24/24 contract checks pass.

### Full pytest suite

```
============================= 364 passed, 1 warning in 52.51s ==============================
```

No existing tests reference `_classify_fund_type` or `_fund_type_label`, and the changes do not alter any committed snapshot.

---

## 4. Bug-by-bug reconciliation

The PR-1c audit listed five concrete bugs to fix in PR-1d. Status:

| Bug | Pre-fix behaviour | Post-fix |
|---|---|---|
| `fund.py:277` collapses `None → 'passive'` for Conviction at level=fund | Funds with no `fund_universe` row silently displayed `passive` | Now reads `fund_strategy` directly; missing rows display `unknown` per `_fund_type_label` |
| `cross.py:215` overloads Cross-Ownership level=fund `type` with `family_name` | UI rendered fund family names (`Vanguard`, `BlackRock`, ...) in the type column | Now displays canonical label (`active` / `passive` / `bond` / `excluded` / `unknown`); `family_name` removed from response |
| `trend.py:295` hardcodes `type=None` for Holder Momentum N-PORT children | UI showed blank column under expanded parents | Now displays canonical label, looked up via JOIN to `fund_universe` propagated through `_get_fund_children` |
| `market.py:642/679/795 + 668/691/826` two-signal contract on `short_analysis` | Both `is_active` and `type` emitted; could disagree | `is_active` dropped; single `type` field derived from `fund_strategy` |
| Three independent fund-level label maps + two parent-level paths with no shared schema test | Inconsistent rendering across tabs | All fund-level paths now go through `_fund_type_label`; parent-level paths unchanged in this PR (queued as separate item) |

Bug 4 from the PR-1c audit (`query4` active/passive bucketing mixes `entity_type` and `manager_type` and silently drops disagreeing rows to "Other/Unknown") is parent-level and remains open; tracked as part of `parent-level-display-canonical-reads`.

---

## 5. Out of scope

Per the PR-1d plan, deferred to later PRs:

- All 18 parent-level display reads (`manager_type` / `entity_type`) — new P2 roadmap item `parent-level-display-canonical-reads`.
- Renaming `index` → `passive` value in DB — PR-1e.
- Renaming `equity` → `active` value in DB — PR-4.
- Dropping `is_actively_managed` and `fund_category` columns — PR-3.
- Extending `INDEX_PATTERNS` (in the deleted `_classify_fund_type` keyword sweep) — superseded by canonical reads; if name-based fallback is ever needed again it would be PR-2.
- `get_two_company_overlap` and `get_two_company_subject` — these emit a separate `is_active` boolean field (not the `type` label) for the two-company tabs; deliberately not migrated here per the plan's file-list scoping.
- Position turnover detection — Stage B roadmap.

---

## 6. Migration story (canonical-source coverage)

After PR-1a, PR-1b, PR-1c, PR-1d:

| Layer | Pre-PR-1a | Post-PR-1d |
|---|---|---|
| Canonical column populated | `fund_strategy` partial; many rows legacy `{active,passive,mixed}` | `fund_universe.fund_strategy` ∈ canonical 7-value set for every row; `fund_holdings_v2.fund_strategy` matches |
| `peer_rotation_flows.entity_type` (fund) | legacy `{active,passive,mixed}` | canonical fund taxonomy |
| Display reads — fund | `is_actively_managed` (12 sites) + `_classify_fund_type` (6 sites) — never canonical | `fund_universe.fund_strategy` via `_fund_type_label` (12 sites) — fully canonical |
| Display reads — parent | `manager_type` / `entity_type` (legacy) | unchanged in PR-1d (queued as `parent-level-display-canonical-reads`) |
| `_classify_fund_type` name sweep | active read path | deleted |
| `family_name` rendered as type (cross-ownership level=fund) | bug — frontend showed `Vanguard` / `BlackRock` | fixed |
| Holder Momentum child blank type | bug — `None` hardcoded | fixed |

The fund-level half of the consolidation sequence is now closed end-to-end: write path canonical (PR-1a/PR-1b), audit complete (PR-1c), display reads canonical (PR-1d). The institution-level half is the next planned workstream.
