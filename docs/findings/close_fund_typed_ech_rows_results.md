# close-fund-typed-ech-rows — execution results

Final PR in the **fund-typed-ech-cleanup** workstream. Closes every
open `entity_classification_history` row whose entity is typed
`fund` in a single transaction. After this PR, ECH carries zero
fund-typed open rows. Fund classification reads route entirely
through `fund_universe.fund_strategy` via `classify_fund_strategy()`
(PR #264). Writer paths are gated against fund-typed targets in
PR #263.

- Apply script: `scripts/oneoff/close_fund_typed_ech_apply.py`
- Rollback manifest: `data/working/close-fund-typed-ech-manifest.csv`
- HEAD at session start: `b24975c` (PR #264)
- Pre-flight backup: `data/backups/13f_backup_20260503_121103` (3.2 GB EXPORT DATABASE)
- Execution date: 2026-05-03

---

## 1. Pre-execution snapshot

### Cohort by classification

| classification | open ECH rows |
|---|---:|
| passive | 5,681 |
| active  | 5,663 |
| unknown | 1,876 |
| **total** | **13,220** |

Zero drift versus the PR #262 audit baseline (~13,220 expected).

### Classification source mix
The manifest CSV captures `confidence` and `source` per row for full
audit trace. Sample sources: `fund_universe` (per-fund mappings),
`PARENT_SEEDS` (legacy seed assignments), `default_unknown` (legacy
unclassified residual), `managers` (legacy fuzzy match).

### Institution-side baseline

Open ECH rows for `entity_type='institution'`: **13,930**.
This number must be invariant across the close.

---

## 2. Writer gate re-validation (PR #263)

All eight writer paths confirmed gated against fund-typed targets:

| # | location | gate |
|---|---|---|
| a | `scripts/build_entities.py` `_insert_cls` (586-601) | early-return when `entities.entity_type='fund'` |
| b | `scripts/build_entities.py` step 6 fund_rows loop (640-641) | no-op `for _ in fund_rows: pass` |
| c | `scripts/build_entities.py` step 6 remaining loop (646-654) | `WHERE e.entity_type != 'fund'` |
| d | `scripts/build_entities.py` `replay_persistent_overrides` (817-821) | reclassify branch refuses fund-typed targets |
| e | `scripts/resolve_pending_series.py` `wire_fund_entity` (632, 685) | ECH stamping removed; classification flows from `queries/common.py` |
| f | `scripts/admin_bp.py` CSV reclassify import (966-981, 1063) | `_validate_no_fund_reclassify_targets` rejects fund-typed eids |
| g | `scripts/entity_sync.py` `update_classification_from_sic` (664-669) | early-return when target is fund-typed |
| h | `scripts/resolve_long_tail.py` `get_unresolved_ciks` (84) | `WHERE e.entity_type != 'fund'` |

No new fund-typed ECH rows can land via any production code path.

---

## 3. Reader path re-validation (PR #264)

Four migrated reader paths confirmed routing to
`classify_fund_strategy(fund_universe.fund_strategy)`:

| # | location | path |
|---|---|---|
| a | `scripts/queries/common.py:325` | `classify_fund_strategy()` helper definition |
| b | `scripts/queries/entities.py` `get_entity_by_id` (67) | imports + calls `classify_fund_strategy` |
| c | `scripts/queries/entities.py` `search_entity_parents` (33) | imports + calls `classify_fund_strategy` |
| d | `scripts/build_entities.py` (41, 267) | helper import + call replacing prior inline mapping |

Fund classification is sourced from `fund_universe.fund_strategy`
at read time, not from ECH.

---

## 4. Manifest summary

- File: `data/working/close-fund-typed-ech-manifest.csv`
- Row count: 13,220 (header + 13,220 = 13,221 lines)
- Columns: `entity_id, canonical_name, entity_type, classification, is_activist, confidence, source, is_inferred, valid_from, valid_to`
- Invariants asserted before write:
  - every row has `entity_type='fund'`
  - every row has `valid_to=DATE '9999-12-31'` (open)
  - every row has `classification ∈ {active, passive, unknown}`

This file is the rollback artifact. Restoring requires reopening each
row's `valid_to` to `'9999-12-31'` keyed by `(entity_id, valid_from,
classification)`.

---

## 5. Transaction execution

Single `BEGIN ... COMMIT` block in `close_fund_typed_ech_apply.py
--confirm`:

```sql
UPDATE entity_classification_history
   SET valid_to = CURRENT_DATE
 WHERE entity_id IN (
     SELECT entity_id FROM entities WHERE entity_type = 'fund'
   )
   AND valid_to = DATE '9999-12-31';
```

### Pre-/post- guard checks

| guard | expected | observed | result |
|---|---:|---:|---|
| pre: live fund-typed open == manifest | 13,220 | 13,220 | PASS |
| pre: institution-typed open == baseline | 13,930 | 13,930 | PASS |
| post: fund-typed open == 0 | 0 | 0 | PASS |
| post: institution-typed open unchanged | 13,930 | 13,930 | PASS |
| post: fund-typed rows closed today == manifest | 13,220 | 13,220 | PASS |

`COMMIT` issued after all five guards passed. No `ROLLBACK`.

---

## 6. Post-execution validation

### entity_current view check (5 random fund eids)

| entity_id | entity_type | classification (entity_current) |
|---:|---|---|
| 20247 | fund | NULL |
| 22738 | fund | NULL |
| 14787 | fund | NULL |
| 16583 | fund | NULL |
| 16057 | fund | NULL |

Expected: `NULL` from the LEFT JOIN once the fund-typed open ECH row
is closed. View no longer projects a stale ECH classification for
fund-typed entities — fund classification must come from the
migrated reader, not the view.

### Migrated reader spot-check (`get_entity_by_id`)

| entity_id | classify_fund_strategy result |
|---:|---|
| 20247 | passive |
| 22738 | passive |
| 14787 | active |
| 16583 | active |
| 16057 | active |

All five fund eids return populated, non-NULL classifications via
the migrated reader path, sourced from
`fund_universe.fund_strategy`. PR #264 reader path is fully
functional with the close in place.

### Institution-side untouched check (5 random institution eids)

Sample: `(27105, 'unknown')`, `(5430, 'mixed')`,
`(2582, 'wealth_management')`, `(5001, 'active')`,
`(3071, 'active')`. Open ECH count for institutions remains
**13,930**, byte-for-byte unchanged versus the Phase 1b baseline.

### Test suite

- `pytest tests/` → **416 passed**, 0 failures, 1 unrelated urllib3 warning
- `cd web/react-app && npm run build` → **built successfully**, 0 TypeScript errors

No test changes required for this PR.

---

## 7. Workstream closure

The **fund-typed-ech-cleanup** arc is complete:

| PR | scope | merged |
|---|---|---|
| #262 | fund-typed-ech-audit (writer + reader scoping) | yes |
| #263 | disable-fund-typed-ech-writers (8 producers gated, queue filter) | yes |
| #264 | migrate-fund-typed-ech-readers (`classify_fund_strategy` helper + 2 reader migrations) | yes |
| this | close-fund-typed-ech-rows (13,220-row SCD close) | this PR |

The rule **ECH carries no fund-typed rows** is now structurally
enforced:

- Writers cannot stamp new fund-typed ECH rows (PR #263 gates).
- Readers do not consult ECH for fund-typed entities (PR #264 helper).
- Residual ECH rows for fund-typed entities are closed (this PR).

D4 classification precedence is honored: fund classification flows
from `fund_universe.fund_strategy` via `classify_fund_strategy()`.

---

## 8. Operational notes

### Diff-staging signal

The next staging cycle's `scripts/diff_staging.py` will report
**~13,220 deleted ECH rows** (fund-typed open rows whose `valid_to`
flipped from `9999-12-31` to today). This is intended. The staging
diff is a downstream consumer of ECH SCD state and is expected to
flag the close.

### Rollback

If the close needs to be reverted, the manifest at
`data/working/close-fund-typed-ech-manifest.csv` carries the full
prior row state. A rollback script would reopen each row's
`valid_to` to `'9999-12-31'` keyed by
`(entity_id, classification, valid_from, source)`. Backup directory
`data/backups/13f_backup_20260503_121103` (3.2 GB EXPORT) provides
the belt-and-suspenders restore path.

### Open follow-up

The fund-typed-ech-cleanup arc is closed. The chat returns to the
parked queue:

- **cp-4b-author-trowe** — single-brand bridge, $1.11T (T. Rowe Price authored brand work).
- **cp-4b-blocker2-corroboration-probe** — read-only investigation of LOW cohort corroboration signals.

Workstream 2 (`fund-classification-by-composition`, also tagged
**orphan-fund classification**) remains parked until orphan fund
classification work resumes.

---

*Refs: `docs/decisions/d4-classification-precedence.md`,
`docs/findings/fund-typed-ech-audit.md`.*
