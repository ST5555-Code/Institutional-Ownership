# PR Review Checklist

_Pre-merge review rules that reviewers (including Serge) apply before approving a PR._

This file collects durable review gates that cannot be enforced by CI today.
Each section specifies WHEN the rule applies and WHAT the reviewer checks.
Additions go below; keep each section self-contained so reviewers can grep to
the rule that matches the PR in hand.

---

## Tier 4 Join-Pattern Rule

**Scope.** Any PR that adds or modifies a function in `scripts/queries.py`
that reads from `holdings_v2` or `fund_holdings_v2`.

**Hard rule — new functions.** A new function MUST use the join pattern for
`ticker`, `entity_id`, and `rollup_entity_id`. Import the helpers from
`scripts/queries_helpers.py` (`ticker_join`, `entity_join`, `rollup_join`,
`classification_join`). Stamped-column reads on those three fields in a net-new
function are rejected on review.

**Soft rule — modifications to existing stamp-column functions.** If the
function already reads the stamped columns, the PR MAY leave them in place.
These functions are bundled into the int-09 Step 4 rewrite (now unblocked
post-Phase-2 per `docs/DEFERRED_FOLLOWUPS.md` INF25; schedulable any time).

Do not mix patterns inside a single function. If a modification touches an
existing stamp-column function, either leave every stamped read in place
OR convert the whole function to the join pattern in this PR. Partial
conversion leaves the function inconsistent and makes the int-09 Step 4
sweep harder to reason about.

**Worldview correctness.** If the function filters or groups by rollup,
verify the `worldview` argument passed to `rollup_join(...)` is explicit.
`rollup_join(worldview='economic_control_v1')` and
`rollup_join(worldview='decision_maker_v1')` have different semantics — the
`entity_current` VIEW hardcodes `rollup_type='economic_control_v1'`, so any
DM-worldview path MUST go through `rollup_join`, not the view. See
[tier-4-join-pattern-proposal.md §6.3](proposals/tier-4-join-pattern-proposal.md)
for the reliability analysis.

**Exemption marker.** If a specific PR needs exemption (e.g. urgent bug fix
on a function scheduled for imminent int-09 Step 4 retirement), annotate the
function with `# tier4-exempt: <reason>` on the line above the `def`. Reviewer
confirms the exemption reason is legitimate and tracked.

**References.**
- Proposal + performance + reliability evidence: `docs/proposals/tier-4-join-pattern-proposal.md`
- Helper library: `scripts/queries_helpers.py`
- Retirement tracker: `docs/DEFERRED_FOLLOWUPS.md` (INF25)
- Principle + sequencing: `docs/data_layers.md §7`
