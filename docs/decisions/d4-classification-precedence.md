# D4 — Classification precedence rule (institution-level)

Locks Decision D4 from `docs/findings/institution_scoping.md` §9 G2 + §12 Q4.
Closes the last open BLOCKER for the Admin Refresh System launch.
Resolved 2026-05-03 in chat ahead of CP-5 (`parent-level-display-canonical-reads`).

---

## Context

Every institution in the database needs a classification label
(active / passive / hedge_fund / wealth_management / etc.).
The canonical source is `entity_classification_history` (ECH).
Coverage today: **99.9 %** — 9,111 of 9,121 institutions have an open ECH row.
A non-trivial subset (3,852 entities) carries `classification='unknown'`.

Two questions had to be resolved before CP-5 could ship:

1. Should the Admin Refresh System re-run classification on every cycle?
2. What should reads do for the 10 institutions with no ECH row at all?

---

## Decision 1 — Classification is permanently out-of-band

**Admin Refresh re-pulls SEC data. It does not re-classify.**

Rationale:

- Refresh is a freshness orchestrator. Classification is a separate
  judgment-driven workflow (CEF reclassifications, family-office migrations,
  Tier 4 keyword sweeps).
- Coupling them turns refresh failures into classification staleness, and
  pulls scope into Admin Refresh that belongs in the entity layer.
- Classification cadence is rare (manual, per-cohort sweeps); refresh
  cadence is high (per-pipeline). The mismatch is structural.

This forecloses Option B from `institution_scoping.md` §9 G2.
The Admin Refresh design doc (`docs/admin_refresh_system_design.md`)
records classification as out-of-scope — no in-band pipeline will be
added.

---

## Decision 2 — Read-side precedence rule for the 10 uncovered CIKs

For any read site bucketing institutions into classification labels,
precedence is:

1. **`entity_classification_history.classification`** — open row
   (`valid_to = DATE '9999-12-31'`). Canonical source.
2. **`holdings_v2.manager_type`** — non-NULL fallback. Used only when
   step 1 returns no row.
3. **`'unknown'`** — terminal label when both prior sources are absent.

The 10 ECH-uncovered CIKs are real edge cases, not the steady-state design.
Fallback handles them without forcing in-band classification scope.

CP-5 (`parent-level-display-canonical-reads`) implements this precedence
in the canonical helper (likely
`scripts/queries_helpers.py:171:classification_join`, pending the
`classification-join-utility-resolution` decision).

---

## Workstream implications

The decision unblocks G2 but surfaces two follow-on workstreams that
must complete before Admin Refresh ships its institution-coverage view:

### `unknown-classification-resolution` (P1, NEW)

Resolve the 3,852 ECH `classification='unknown'` cohort down to a
small residual via tiered signal-driven sweeps. 3,852 is too large to
display on Admin; the goal is to make the displayed list small.

- Discovery PR (read-only): `unknown-classification-discovery` —
  enumerates the cohort, AUM exposure, signal sources (ADV, N-CEN,
  name pattern, manager_type), tiered resolution waves.
- Resolution PRs: 2–3 waves keyed on the highest-confidence signals
  surfaced by discovery (likely ADV-driven, N-CEN-driven, name-pattern).
- Includes the 427 Tier 4 unmatched classifications already tracked
  in ROADMAP (PR #200 follow-up) — bundle into the same waves.

Pre-cycle eligible (read-only and per-cohort UPDATEs are independent
of Q1 13F cycle data).

### `admin-unresolved-firms-display` (P2, NEW)

Display-only Admin section listing every institution still
unresolved after `unknown-classification-resolution` lands, plus the
10 ECH-uncovered CIKs.

- Single scrollable section on the Admin page.
- Two groups, one column flag distinguishing them:
  - `no_ech_row` (10 today)
  - `unknown_classification` (residual after resolution waves)
- Display-only: no actions, no batch edits. Surfaces the long tail
  for analyst attention without blocking refresh.

Depends on `unknown-classification-resolution` reaching a small
residual. No point shipping a viewer for thousands of rows when
the goal is to shrink the cohort.

---

## What does not change

- ECH stays the canonical source of truth for classification.
- The CP-5 read sweep adopts the precedence rule above; no schema
  change required (`classification` column is plain VARCHAR).
- The architecturally-correct activist-as-flag shape (`ECH.is_activist`
  orthogonal to `classification`) remains the target — see
  `institution_scoping.md` §8.

---

## Cross-references

- `docs/findings/institution_scoping.md` — full investigation,
  §9 G2 (BLOCKER), §12 Q4 (open question).
- `docs/admin_refresh_system_design.md` — out-of-band annotation
  to be applied during the next admin-design sync.
- `docs/decisions/inst_eid_bridge_decisions.md` — sister decision
  doc covering the brand-vs-filer eid bridge (CP-1 / CP-4 family).
- ROADMAP entries: `unknown-classification-resolution` (P1, new),
  `admin-unresolved-firms-display` (P2, new),
  `parent-level-display-canonical-reads` (CP-5, existing — adopts
  the precedence rule above).
