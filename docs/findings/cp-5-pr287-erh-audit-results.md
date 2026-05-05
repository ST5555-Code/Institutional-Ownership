# cp-5-pr287-erh-audit — results

**Branch:** `cp-5-pr287-erh-audit`
**Type:** Read-only audit, no DB writes
**Date:** 2026-05-05

## 1. Audit scope

PR #291 (cp-5-loader-gap-remediation-sub2) surfaced the rule that every
new entity needs `entity_rollup_history` self-rollup rows in **both**
`decision_maker_v1` AND `economic_control_v1`. The `entity_current` view
sources from `economic_control_v1`, so a missing row leaves the entity
invisible to that view.

The PR #287 (cp-5-capital-group-umbrella) prompt only specified
`decision_maker_v1` self-rollup. This audit verifies the umbrella entity
carries both rollup types, and spot-checks 5 sample loader-gap entities
as belt-and-suspenders.

## 2. PR #287 umbrella state — eid 12

PR #287 followed Path A (use existing eid 12 "Capital Group / American
Funds"); no new entity was created. Per `entity_rollup_history`, eid 12
carries open rows for both rollup types:

| rollup_type          | rollup_entity_id | rule_applied | valid_from | valid_to   |
|----------------------|------------------|--------------|------------|------------|
| decision_maker_v1    | 12               | self         | 2000-01-01 | 9999-12-31 |
| economic_control_v1  | 12               | self         | 2000-01-01 | 9999-12-31 |

Both `valid_from` dates are `2000-01-01`, confirming the rows predate
the cp-5 arc — eid 12 is a long-standing entity that already had full
rollup coverage when PR #287 attached the 3 wholly_owned/control bridges.
PR #287 was complete despite the prompt's narrower wording.

**Result:** umbrella has both rollup types. No fix needed.

## 3. Loader-gap sample — eid 27260, 27270, 27280, 27290, 27312

All 5 sampled entities (out of the 53 created in PR #291,
eid 27260..27312) carry both rollup types as self-rollup rows:

| entity_id | decision_maker_v1 | economic_control_v1 |
|-----------|-------------------|---------------------|
| 27260     | ✓ (self)          | ✓ (self)            |
| 27270     | ✓ (self)          | ✓ (self)            |
| 27280     | ✓ (self)          | ✓ (self)            |
| 27290     | ✓ (self)          | ✓ (self)            |
| 27312     | ✓ (self)          | ✓ (self)            |

PR #291's in-flight refinement (Op E2 — `economic_control_v1` self-rollup
added during execution) is confirmed to have landed correctly across the
cohort.

## 4. Recommendation

**No-op.** Both audit targets pass:
- Umbrella eid 12 was already complete (Path A, pre-existing entity).
- Loader-gap cohort (PR #291) has both rollup types per the in-flight fix.

The both-rollup-types rule is now codified in memory
(`feedback_entity_creation_both_rollup_types.md`); future entity-creation
PRs must INSERT both self-rollup rows. No corrective work required from
this audit.
