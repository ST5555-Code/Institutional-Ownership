# sec-04-p0 — Phase 0 investigation: validators writing to prod

## Context

Foundation work under the remediation program (`docs/REMEDIATION_PLAN.md` Theme 4; `docs/REMEDIATION_CHECKLIST.md` Batch 4-B). Audit item MAJOR-1 (C-02): validation scripts that should be read-only are opening the production database in read-write mode and/or writing side effects during validation runs. This violates the staging-first discipline.

sec-03 (write-surface audit) is merged and produced the endpoint inventory. This investigation focuses on the validation scripts themselves (not admin endpoints).

Phase 0 is investigation only. **No code writes, no DB writes.**

## Branch

`remediation/sec-04-p0` off main HEAD.

## Files this session will touch

Read-only / investigation:
- `scripts/validate_nport_subset.py` — flagged in audit as writing to prod during validation
- `scripts/validate_entities.py` — check for prod write paths
- `scripts/validate_13dg.py` — check for prod write paths
- `scripts/pipeline/shared.py` — shared utilities that validators import; check for write-mode connections
- `scripts/pipeline/manifest.py` — check if validators call write helpers
- `scripts/db.py` — `get_db()` and connection helpers; check default read-only vs read-write
- `data/13f.duckdb` (read-only) — verify current state if needed

Write:
- `docs/findings/sec-04-p0-findings.md` — new findings doc

**If the worker touches any file not in this list, it must stop and escalate rather than proceed.**

## Scope

1. **Inventory every validate_*.py script:**
   - List each one, its purpose, and how it is invoked (standalone, from admin UI, from Makefile).
   - For each: does it open the DB in read-write mode? Where? (file:line)
   - Does it write to any table? Which tables? What kind of writes (INSERT, UPDATE, DELETE)?
   - Is the write intentional (e.g. stamping validation results) or accidental (e.g. importing a helper that opens RW)?

2. **Trace the connection path:**
   - How does each validator get its DB connection? Via `db.get_db()`? Direct `duckdb.connect()`?
   - Does `db.get_db()` default to read-only or read-write?
   - Does `pipeline/shared.py` provide any connection helpers that default to read-write?

3. **Classify each write:**
   - **INTENTIONAL** — the validator is designed to write (e.g. stamping `pending_entity_resolution`). Document whether this is appropriate or should be moved to a separate non-validation script.
   - **ACCIDENTAL** — the validator opens RW because a shared helper defaults to it, but does not actually write. Fix: switch to read-only.
   - **SIDE-EFFECT** — the validator writes as a side effect of importing/calling a helper designed for fetchers. Fix: refactor the helper or the call.

4. **Cross-item awareness:**
   - sec-03 (write-surface audit) — established the admin endpoint baseline. sec-04 extends to non-endpoint scripts.
   - sec-05/sec-06 (hardcoded-prod builders, direct-to-prod writers) — may share some of the same connection-path findings.
   - int-21 (MAJOR-7 unresolved series_id) — both touch `pipeline/shared.py`. Serial per plan.
   - obs-03 (id_allocator) — `shared.py` was modified (dead `write_impact_row` removed). Confirm no validator called it.

5. **Phase 1 scope:**
   - For each validator: what changes to make it read-only (or explicitly separate the write step)?
   - Test plan.

## Out of scope

- Code writes.
- DB writes.
- sec-05/sec-06 (separate items).
- int-21 (serial dependency).

## Deliverable

`docs/findings/sec-04-p0-findings.md` structured like prior findings docs. Cite file:line. Include a table of every validator with its write classification.

## Hard stop

Do NOT merge. Open a PR via `gh pr create` with title `remediation/sec-04-p0: Phase 0 findings — validators writing to prod`. Report PR URL + CI status.
