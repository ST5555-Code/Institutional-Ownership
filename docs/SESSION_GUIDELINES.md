# Session Guidelines

_Durable rules about how a session opens, runs, and closes. Session-level
hygiene that is not a coding convention (see `docs/REVIEW_CHECKLIST.md`
for PR-review gates and `docs/PROCESS_RULES.md` for large-data script
rules)._

---

## Cross-tracker update rule

**Closing a tracked item requires updating every tracker that references
it, in the same PR.**

Tracker docs:

- `ROADMAP.md`
- `docs/REMEDIATION_PLAN.md`
- `docs/REMEDIATION_CHECKLIST.md`
- `docs/DEFERRED_FOLLOWUPS.md`
- `docs/NEXT_SESSION_CONTEXT.md`

Before opening a PR that closes an item, grep for the item ID / name
across all five trackers. If more than one mentions it, update all of
them in this PR — do not leave the stale mentions for a future
doc-sync session. The historical cost of a stale tracker is a full
investigation session to reconstruct state that was already known
(see `phantom-other-managers-decision`, PR #125 — the phantom
`other_managers` item flagged open in `REMEDIATION_PLAN.md` had
already been resolved four days earlier, but that was only confirmed
after a full session re-reading the code).

**Why:** trackers drift independently. A session that ships a fix
naturally updates whichever tracker the author was looking at,
not the other four. The next session investigating the item reads
a stale tracker, treats it as authoritative, and wastes a session
rediscovering what already shipped.

**How to apply:**

1. When preparing a PR that closes an item, run
   `python3 scripts/audit_tracker_staleness.py` against your branch.
   The script prints any ID whose status disagrees across docs and
   exits non-zero if drift exists.
2. If the audit flags your item, update every tracker it names
   before pushing. Use the same closure note (commit SHA, PR
   number, date) in each.
3. For items whose closure is partial (`Steps 1-3 done; Step 4
   deferred`), spell out the partial state in every tracker — do
   not rely on one tracker to carry the nuance.
4. Reviewers check tracker consistency per the
   `docs/REVIEW_CHECKLIST.md` tracker-consistency gate.

**Scope exemption.** A PR that deliberately only touches one
tracker (a typo fix, a link repair, a header refresh) does not need
to update the others. The rule kicks in when the PR changes the
**status** of an item, not when it changes prose around the item.

---

## Related

- `docs/SESSION_NAMING.md` — session / branch naming convention.
- `docs/REVIEW_CHECKLIST.md` — PR-review gates applied at merge time.
- `docs/PROCESS_RULES.md` — rules for large-data pipeline scripts.

