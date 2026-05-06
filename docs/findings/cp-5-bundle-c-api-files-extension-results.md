# cp-5-bundle-c-api-files-extension — results

Read-only inventory hygiene PR. Extends Bundle C reader inventory to
enumerate `scripts/api_*.py` reader sites that the original Bundle C
§7.4 scope (`scripts/queries/*` only) missed.

Drives chat decision Q3 from PR #302 (CP-5.4 recon): future CP-5.5
and CP-5.6 recons reference the extended Bundle C inventory as
canonical and skip re-discovering the api layer.

No DB writes. No reader migrations. No behavior changes.

## 1. Phase 1 enumeration

### 1.1 `api_*.py` reader sites surfaced

Greps run:

```
grep -rn "rollup_name|inst_parent_name|rollup_entity_id|dm_rollup|dm_entity_id"
  scripts/api_*.py
grep -rn "top_parent_canonical_name_sql|top_parent_holdings_join"
  scripts/api_*.py
grep -rn "holdings_v2|fund_holdings_v2|entity_current|summary_by_parent|shares_history|manager_aum|entity_relationships"
  scripts/api_*.py
grep -rn "COALESCE|rollup_name|manager_name"
  scripts/api_*.py
```

Primary grep hits (rollup-pattern tokens):
- `scripts/api_entities.py:40` — docstring of `api_entity_search` (mentions `entity_id = rollup_entity_id`; the function delegates to `queries.search_entity_parents`, no inline rollup SQL).
- `scripts/api_fund.py:44` — `MAX({tpn}) as inst_parent_name` inside FPM1 endpoint; `tpn` is the migrated helper.

Helper-usage grep hits (already-migrated sites):
- `scripts/api_fund.py:18,38` — `top_parent_canonical_name_sql` import + use in FPM1.
- `scripts/api_market.py:25,198` — same import + use in `api_crowding` (C2).

Final defensive grep `COALESCE | rollup_name | manager_name` against
`scripts/api_*.py` returns **zero hits** — the pre-helper rollup-COALESCE
pattern is fully eliminated from the api layer. Both legacy callsites
were migrated in PR #303 (CP-5.4 ship list).

### 1.2 Per-feature breakdown (api-layer only)

37 api-layer rows total in the extended inventory. Status distribution:

| migration_status | n rows |
| --- | ---: |
| MIGRATED | 2 |
| N/A_NO_ROLLUP_PATTERN | 6 |
| DELEGATING_WRAPPER | 26 |
| DISPATCH_UTILITY | 3 |

Per-feature:

| feature | sites | dominant status |
| --- | ---: | --- |
| Crowding | 1 | MIGRATED (#303) |
| Smart Money | 2 | N/A — no rollup pattern (CP-5.4 §1.3 verified) |
| Fund Portfolio Managers | 1 | MIGRATED (#303) — was Q-1 in CP-5.4 §1.4 |
| Register Tickers autocomplete | 1 | N/A — pure ticker enumerator |
| Cross-Ownership | 5 | DELEGATING_WRAPPER → cross.py (CP-5.3 #301) |
| Flows / Trend / Conviction | 7 | DELEGATING_WRAPPER → flows.py / trend.py / fund.py |
| Sector Rotation | 6 | DELEGATING_WRAPPER → market.py (PENDING_CP5_5) |
| Entity graph / hierarchy | 5 | DELEGATING_WRAPPER → entities.py / market.py (PENDING_CP5_6) |
| Other (short interest, completeness, peer_tickers, dispatcher) | 10 | DELEGATING_WRAPPER + N/A + DISPATCH_UTILITY mix |

The 26 DELEGATING_WRAPPER rows do not introduce new reader migration
sites. Each one inherits status from its upstream `scripts/queries/*`
row — when the queries-layer site migrates, the api wrapper picks up
the new behaviour transitively.

## 2. Phase 2 doc updates

### 2.1 cp-5-bundle-c-discovery.md §7.4-api added

Edited [docs/findings/cp-5-bundle-c-discovery.md §7.4](cp-5-bundle-c-discovery.md):

- Added a scope note at the top of §7.4 explaining the original 27-row
  enumeration scoped `scripts/queries/*` only and pointing readers to
  the extended csv as canonical.
- Inserted a new sub-section §7.4-api between §7.4b and §7.4c. The
  sub-section enumerates the 37 api-layer rows by status and feature,
  and explains the bottom-line: 2 MIGRATED rows capture the entire
  api-layer rollup-pattern surface; everything else is wrapper or
  no-rollup.

### 2.2 Cross-reference to extended csv

Canonical inventory file (referenced from both §7.4 scope note and
§7.4-api sub-section):

```
data/working/cp-5-bundle-c-readers-extended.csv
```

Schema: `file, line, function, feature, query_shape, migration_class,
migration_status, routes_to`.

64 rows total (27 from the original `scripts/queries/*` inventory +
37 new `scripts/api_*.py` rows).

## 3. Phase 3 verification

- Re-ran the Phase 1a/1b/1c greps post-doc-edit. Every hit appears in
  the extended csv.
- Confirmed already-migrated sites (PR #300 / #301 / #303) are present
  in the extended csv with `migration_status=MIGRATED` and the
  appropriate `routes_to` pointer.
- Confirmed `COALESCE | rollup_name | manager_name` returns zero hits
  in `scripts/api_*.py` — i.e. the api layer is rollup-pattern-clean
  post-CP-5.4.
- `pytest tests/` → 444 passed, 6 skipped, 1 warning (no behaviour
  change vs. baseline at HEAD `7121c41`).

## 4. Bundle C inventory now canonical for CP-5.5 + CP-5.6 recons

Per chat decision Q3 from PR #302 recon, future Bundle-C-derived
recons (CP-5.5 = Sector Rotation / New-Exits / AUM / Activist /
Flows; CP-5.6 = View 2 / Tier-3 sentinel) should reference
`data/working/cp-5-bundle-c-readers-extended.csv` as canonical and
skip the api-layer re-enumeration step. Each candidate site there
already carries:

- `migration_status` (MIGRATED / PENDING_CP5_<n> / N/A / wrapper)
- `routes_to` (which CP-5.x PR or post-CP-5 cohort owns the work)
- `query_shape` (verified via re-grep)

The pre-execution discovery checklist in CP-5.5 + CP-5.6 recons
collapses to "filter the extended csv by `migration_status`
`PENDING_CP5_5` (or `PENDING_CP5_6`) and confirm the queries-layer
shape hasn't drifted since 2026-05-06" — no fresh Phase 1 grep
required.

## 5. Out-of-scope discoveries / surprises

- **Zero pre-helper COALESCE rollup-pattern hits in `scripts/api_*.py`.**
  Defensive `grep COALESCE | rollup_name | manager_name` returned no
  matches. Confirms the api layer is clean post-PR #303 — no
  unmigrated rollup-pattern sites are hiding in the api files. The
  extension PR's final grep is the canonical record of that fact.
- `api_entities.py:40` mentions `rollup_entity_id` in a docstring
  only; the function delegates to `queries.search_entity_parents`
  and adds no api-layer reader complexity.
- `api_register.py:78` (the `/api/v1/tickers` autocomplete) is the
  only api-layer endpoint with a top-level inline `holdings_v2` SELECT
  outside the helper-using cohort. It's a pure ticker enumerator
  (`SELECT ticker, MODE(issuer_name) FROM holdings_v2 WHERE quarter=LQ`)
  and carries no parent-display rollup. Tagged `N/A_NO_ROLLUP_PATTERN`.
- The 26 DELEGATING_WRAPPER rows — `api_cross.py`, `api_flows.py`,
  most of `api_market.py`, `api_entities.py` — were enumerated for
  completeness so the next CP-5.x recon doesn't have to. They are
  not migration sites in their own right.
- `api_register.py` `_execute_query` / `api_query` / `api_export` are
  generic dispatchers over `QUERY_FUNCTIONS`; tagged
  `DISPATCH_UTILITY`. Per-query migration is tracked at the
  `scripts/queries/*` layer.
