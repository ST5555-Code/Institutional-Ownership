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

---

## Tracker consistency

**Scope.** Any PR that changes the status of a tracked item (closes
it, reopens it, marks it deferred/standing/superseded, re-scopes it).

**Hard rule.** For any PR that closes or changes status on an item,
verify the same item is updated in **every tracker doc that
references it** — not just the one the author happened to edit.
Tracker docs: `ROADMAP.md`, `docs/REMEDIATION_PLAN.md`,
`docs/REMEDIATION_CHECKLIST.md`, `docs/DEFERRED_FOLLOWUPS.md`,
`docs/NEXT_SESSION_CONTEXT.md`.

**Check.** Run `python3 scripts/audit_tracker_staleness.py` against
the branch head. The script prints any ID whose status disagrees
across docs and exits non-zero on drift. If the branch leaves drift
in place, the PR should either resolve it or document why the drift
is intentional (partial closure, scope exemption).

**Rationale.** Closing a tracker doc lags the real fix by one
session when different trackers drift independently. The cost of
catching drift at review time is a grep; the cost of missing it is
a full investigation session for whoever opens the item next.

**References.**
- Rule wording: `docs/SESSION_GUIDELINES.md § Cross-tracker update rule`.
- Audit script: `scripts/audit_tracker_staleness.py`.
- Precedent incident: `phantom-other-managers-decision` (PR #125) —
  a 4-day staleness that cost a full session to reconstruct.
