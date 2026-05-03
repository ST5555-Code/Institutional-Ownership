# migrate-fund-typed-ech-readers — helper + 2 reader migrations

**HEAD at start:** `f3ebe9f` (disable-fund-typed-ech-writers: gate 6
producers + queue filter, #263).
**PR scope:** PR-R1 per audit §7 + chat decisions Q1 (cover both readers)
and Q2 (factor a shared helper). Code-only change. No DB writes.

Refs: [docs/decisions/d4-classification-precedence.md](../decisions/d4-classification-precedence.md),
[docs/findings/fund-typed-ech-audit.md](fund-typed-ech-audit.md),
[docs/findings/disable_fund_typed_ech_writers_results.md](disable_fund_typed_ech_writers_results.md).

---

## 1. Phase 1 reconciliation table — canonical fund_strategy mapping

The classify_fund_strategy() helper locks the fund-side classification
mapping for all consumers. Three pre-existing sources had to be
reconciled before defining the helper:

- **Source A** — `scripts/build_entities.py:243-253` (pre-PR) inline
  CASE returning a tri-state `is_active` boolean
  (TRUE | FALSE | NULL).
- **Source B** — `scripts/queries/common.py:304-305`
  `ACTIVE_FUND_STRATEGIES = ('active','balanced','multi_asset')` and
  `PASSIVE_FUND_STRATEGIES = ('passive','bond_or_other','excluded',
  'final_filing')`. PR-3 single-source-of-truth tuples.
- **Source C** — `scripts/queries/common.py:308-322`
  `_fund_type_label()` display-layer mapping returning
  `'active' | 'passive' | 'bond' | 'excluded' | 'unknown'`.

| `fund_strategy` | A `is_active` | B membership | C label   | classify_fund_strategy() |
|-----------------|--------------|--------------|-----------|--------------------------|
| `active`        | TRUE         | ACTIVE       | active    | `'active'`               |
| `balanced`      | TRUE         | ACTIVE       | active    | `'active'`               |
| `multi_asset`   | TRUE         | ACTIVE       | active    | `'active'`               |
| `passive`       | FALSE        | PASSIVE      | passive   | `'passive'`              |
| `bond_or_other` | FALSE        | PASSIVE      | bond      | `'passive'`              |
| `excluded`      | FALSE        | PASSIVE      | excluded  | `'passive'`              |
| `final_filing`  | FALSE        | PASSIVE      | excluded  | `'passive'`              |
| NULL / `''`     | NULL         | n/a          | unknown   | `'unknown'`              |

A, B, C agree on the active/passive partition. C uses a finer display
vocabulary (`bond`, `excluded`) but those reduce cleanly to `'passive'`
in the ECH-shape. No drift detected — STOP gate cleared.

`classify_fund_strategy(strategy)` raises `ValueError` on any value
outside the canonical set, surfacing upstream pipeline drift early.

---

## 2. classify_fund_strategy() helper — signature + cross-references

Defined in [scripts/queries/common.py](../../scripts/queries/common.py)
alongside the `ACTIVE_FUND_STRATEGIES` / `PASSIVE_FUND_STRATEGIES`
constants and `_fund_type_label()` so the canonical fund-strategy logic
lives in one module.

```python
def classify_fund_strategy(strategy):
    """Returns 'active' | 'passive' | 'unknown'.

    None / '' → 'unknown'. Non-canonical → ValueError.
    """
```

Three consumers post-PR:

1. `scripts/queries/entities.get_entity_by_id` (Phase 4)
2. `scripts/queries/entities.search_entity_parents` (Phase 5)
3. `scripts/build_entities.step2_create_fund_entities` (Phase 3)

All three previously hard-coded the mapping (or read directly from ECH).
Centralizing here prevents drift across reader paths and the
entity-build classification field.

---

## 3. build_entities.py inline-mapping replacement

`step2_create_fund_entities` previously selected
`CASE WHEN fund_strategy IN ('active','balanced','multi_asset') THEN
TRUE ... END AS is_active` and stored the boolean in the 5th column of
`fund_entity_rows`. That boolean was no longer consumed downstream:
`step5_populate_aliases` destructured it as `_active` (unused) and
`step6_populate_classifications` iterated `fund_rows` with a no-op body
(per PR #263 D4 precedence — fund-typed entities do not get ECH).

Post-PR, the SELECT returns `fund_strategy` directly and Python applies
`classify_fund_strategy(fund_strategy)` per row. The 5th column of
`fund_entity_rows` now carries the canonical
`'active'|'passive'|'unknown'` string, matching what the readers
surface. Net effect: the third consumer of the helper, single source of
truth for fund-side classification across writes (entity-build) and
reads (queries.entities). No behavior drift downstream — `_active` was
unused.

---

## 4. get_entity_by_id migration — pre/post + edge cases

[scripts/queries/entities.get_entity_by_id](../../scripts/queries/entities.py)
added a fund-typed branch around the base `entity_current` row.

**Pre-PR:** classification read straight from `entity_current.classification`
(the open ECH row). For fund entities this returned the legacy ECH
value, which after PR #263 is no longer being written and after PR-C
(next) will be closed entirely.

**Post-PR:**
- `entity_type = 'institution'` (or anything non-fund) — classification
  stays the ECH value (unchanged).
- `entity_type = 'fund'` — classification is resolved via
  `_resolve_fund_classification()` which joins
  `entity_identifiers (series_id, valid_to=open) → fund_universe`,
  returns the first `fund_strategy` row, then applies
  `classify_fund_strategy()`.

Edge cases (each pinned by a test in
[tests/test_fund_typed_ech_readers.py](../../tests/test_fund_typed_ech_readers.py)):

- Fund with no open `series_id` identifier → `'unknown'`.
- Fund with `series_id` but no `fund_universe` row → `'unknown'`.
- Fund with `fund_universe` row but `NULL fund_strategy` → `'unknown'`.
- Fund with a closed `series_id` identifier (`valid_to` not 9999-12-31)
  → treated as no-identifier, `'unknown'`.
- Fund with a stale legacy ECH row (e.g. ECH says `'passive'`,
  fund_strategy says `'active'`) → `'active'`. Reader explicitly ignores
  the legacy ECH for fund-typed entities.

All four "no-data" gap states are valid current-DB states (orphan funds,
Workstream 2 pickup) and resolve consistently to `'unknown'`.

---

## 5. search_entity_parents migration outcome

The audit §3.3 flagged this function as low-blast but in scope per Q1.
Re-reading at HEAD `f3ebe9f` confirmed it does surface
`classification` (lines 14, 26 of `scripts/queries/entities.py`
pre-PR).

**Result:** migrated. Same fund-typed branch as `get_entity_by_id`,
applied per row in the result list. Institution rows still surface
the ECH classification verbatim.

This was not a no-op — the alternative would have been a stale-data bug
where the institution dropdown showed funds with their pre-PR-C ECH
values while the rest of the app surfaced fund_universe-derived values.

---

## 6. Test coverage summary

Added 34 passing tests; total suite now `416 passed` (baseline 382).

| file | new tests | scope |
|---|---:|---|
| [tests/test_queries_common.py](../../tests/test_queries_common.py) | 6 | helper unit tests — ACTIVE/PASSIVE sets, None/'', invalid raises, full canonical coverage |
| [tests/test_fund_typed_ech_readers.py](../../tests/test_fund_typed_ech_readers.py) | 28 | end-to-end DuckDB-backed migration tests |

Per the 28-test breakdown:

- 3 — `get_entity_by_id` institution baseline (active/passive/unknown
  unchanged).
- 7 — `get_entity_by_id` fund-typed parametrized over every canonical
  fund_strategy.
- 5 — `get_entity_by_id` fund edge cases (legacy ECH ignored,
  no series_id, no fund_universe row, NULL fund_strategy, closed
  series_id).
- 4 — `search_entity_parents` institution + fund + active + legacy-ignored.
- 9 — `step2_create_fund_entities` carries helper output (8 parametrized
  + 1 contract-pin test).

`pre-commit run` (ruff + pylint + bandit) passes on all touched files.

---

## 7. Open follow-up

**PR-C — close the 13,220 legacy fund-typed ECH rows.** Runs next.
Phase 1 of PR-C will re-validate that:

- All 8 writer gates from PR #263 are still in place at HEAD.
- All reader paths migrated by this PR are present and dispatching to
  `_resolve_fund_classification` for fund-typed entities.

Only after PR-C does the entity_current.classification column become
NULL for fund-typed rows. The migrated readers already handle that
state correctly (fund_universe is the source either way).

The unknown-classification workstream closes with PR-C. Next milestones
return to `cp-4b-author-trowe` and
`cp-4b-blocker2-corroboration-probe`.
