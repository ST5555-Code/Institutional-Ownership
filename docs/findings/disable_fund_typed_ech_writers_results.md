# disable-fund-typed-ech-writers — gate 6 producers + queue filter

**HEAD at start:** `fd2a9f2` (fund-typed-ech-audit: writer + reader scoping, #262).
**PR scope:** PR-W1..W4 + Q4 long-tail SQL filter, bundled per chat decision
2026-05-03. Code-only change. No DB writes. Existing 13,220 fund-typed
ECH rows untouched — closed in PR-C after PR-R lands.

Refs: [docs/decisions/d4-classification-precedence.md](../decisions/d4-classification-precedence.md),
[docs/findings/fund-typed-ech-audit.md](fund-typed-ech-audit.md).

---

## 1. Re-validation snapshot

Cohort sanity (read-only, against production DB):

| metric | value | audit value | drift |
|---|---|---|---|
| open fund-typed ECH rows | 13,220 | 13,220 | 0 |

All six writer sites and the long-tail queue selector verified present
at HEAD before applying gates. Line numbers had not shifted materially
since the audit was written; functions/blocks intact.

---

## 2. Per-gate summary

| # | file | function / block | change type | rationale |
|---|---|---|---|---|
| 1 | scripts/build_entities.py | `_insert_cls` helper (step 6) | early-return guard on `entity_type='fund'` | choke point — single guard prevents fund-typed rows regardless of caller |
| 2 | scripts/build_entities.py | step 6 `fund_rows` loop | body replaced with no-op + comment | active producer (6,671 rows / source `fund_universe`) |
| 3 | scripts/build_entities.py | step 6 'remaining' query | `AND e.entity_type != 'fund'` filter | active producer (1,876 rows / source `default_unknown`) |
| 4 | scripts/build_entities.py | `replay_persistent_overrides` reclassify branch | entity_type lookup + skip with logged warning | theoretical producer — keeps close PR durable against future overrides |
| 5 | scripts/resolve_pending_series.py | `wire_fund_entity` ECH INSERT block | block removed entirely; entity/identifier/alias/relationship/rollup writes preserved | active producer (4,673 rows / source `stg_nport_fund_universe`) |
| 6 | scripts/admin_bp.py | `_validate_no_fund_reclassify_targets` helper + call from `/entity_override` reclassify branch | new helper + per-row HTTP 400 reject | theoretical producer — operator CSV import path |
| 7 | scripts/entity_sync.py | `update_classification_from_sic` | early-return guard on `entity_type='fund'` | theoretical producer — SIC-based classification flow |
| 8 | scripts/resolve_long_tail.py | `get_unresolved_ciks` query | `AND e.entity_type != 'fund'` filter | Q4 preventive — keeps fund eids out of long-tail worker queue |

All gates reference D4 precedence inline so future readers can trace the
"why" without leaving the file.

---

## 3. Test coverage summary

New test file: [tests/test_disable_fund_typed_ech_writers.py](../../tests/test_disable_fund_typed_ech_writers.py)

| test class | gate | assertion |
|---|---|---|
| `TestInsertClsFundGuard` | 1 | `_insert_cls` writes zero ECH rows when entity_type='fund' |
| `TestStep6FundRowsLoopIsNoop` | 2 | step 6 fund_rows loop produces zero `fund_universe` rows |
| `TestStep6RemainingLoopExcludesFunds` | 3 | 'remaining' loop skips funds, still classifies institutions |
| `TestReplayPersistentOverridesSkipsFunds` | 4 | reclassify override against fund eid writes no ECH |
| `TestWireFundEntitySkipsECH` | 5 | wire_fund_entity creates entity + alias + relationship + rollup but zero ECH |
| `TestAdminCsvRejectsFundEids` (×2) | 6 | helper flags fund eids; institution-only input passes through |
| `TestUpdateClassificationFromSicGuardsFunds` | 7 | SIC 6211 → 'active' is short-circuited for fund-typed entities |
| `TestGetUnresolvedCiksFiltersFunds` | 8 | fund-typed CIKs excluded from long-tail queue, institution-typed preserved |

Each test was written as a failing case (RED) against pre-gate code,
watched fail for the expected reason, then went GREEN once the gate
landed.

Test counts:
- baseline (main): 373 passing
- after this PR: **382 passing** (373 + 9; admin gate split into two
  cases — positive flag-fund-eid and negative no-false-positive)
- regressions: 0

---

## 4. Pre/post grep evidence

`grep -rn "INSERT INTO entity_classification_history" scripts/` after
the gates land:

```
scripts/admin_bp.py:1089                  # gated by _validate_no_fund_reclassify_targets
scripts/admin_bp.py:1104                  # gated by _validate_no_fund_reclassify_targets
scripts/resolve_13dg_filers.py:359        # institution-only writer per audit §2.3
scripts/bootstrap_residual_advisers.py:222    # institution-only writer per audit §2.3
scripts/bootstrap_etf_advisers.py:188     # institution-only writer per audit §2.3
scripts/bootstrap_tier_c_advisers.py:188  # institution-only writer per audit §2.3
scripts/entity_sync.py:696                # gated by update_classification_from_sic entry guard
scripts/build_entities.py:602             # _insert_cls choke point — gated
scripts/build_entities.py:832             # replay_persistent_overrides reclassify branch — gated
scripts/oneoff/*                          # one-off scripts, institution-only per audit §2.3
```

Notable disappearance: `scripts/resolve_pending_series.py:694` — the
INSERT block was removed entirely (Gate 5).

Every remaining live INSERT is either gated or institution-only by
construction. The audit's 18-writer surface is now safe.

---

## 5. Open follow-up

Per the audit §7 sequence, the next two PRs land in order:

- **PR-R** — migrate `get_entity_by_id` (and optionally
  `search_entity_parents`) to resolve fund classification through
  `entity_identifiers.identifier_value (series_id) → fund_universe.fund_strategy`.
  Adds `classify_fund_strategy(strategy: str) -> str` helper in
  `scripts/queries/common.py` to retire the duplicated mapping in
  `build_entities.step2_create_fund_entities`.
- **PR-C** — close all 13,220 open fund-typed ECH rows in a single
  transaction. Pre-flight refuses to run unless PR-W (this PR) and PR-R
  are both merged. Post-flight asserts `entity_current` returns
  `classification = NULL` for representative fund eids and
  `get_entity_by_id` returns the migrated classification.

After PR-C lands, the long-tail worker queue size drops by the count of
fund-typed CIKs that were sitting in `unknown` ECH (≈1,876). Gate 8's
SQL filter ensures this drop is durable rather than dependent on the
INNER JOIN drop-out.

---

*Results captured 2026-05-03 by disable-fund-typed-ech-writers branch.*
