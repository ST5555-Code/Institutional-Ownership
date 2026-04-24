# mig-04-p0 — Phase 0 investigation: schema_versions stamp hole

## Context

Foundation work under the remediation program (`docs/REMEDIATION_PLAN.md` Theme 3; `docs/REMEDIATION_CHECKLIST.md` Batch 3-A). Audit item MAJOR-16 (S-02): `scripts/migrations/add_last_refreshed_at.py` does not stamp `schema_versions` after applying its DDL change, breaking the `verify_migration_applied()` invariant. Phase 2's migration 010 relies on `verify_migration_applied()` giving the right answer.

Phase 0 is investigation only. **No code writes, no DB writes.**

## Branch

`remediation/mig-04-p0` off main HEAD.

## Files this session will touch

Read-only / investigation:
- `scripts/migrations/add_last_refreshed_at.py` — the migration missing the stamp
- `scripts/migrations/001_pipeline_control_plane.py` through `010_drop_nextval_defaults.py` — reference implementations; check which ones stamp and which do not
- `scripts/db.py` — `verify_migration_applied()` function if it exists
- `data/13f.duckdb` (read-only) — check current `schema_versions` table contents
- `data/13f_staging.duckdb` (read-only) — check parity

Write:
- `docs/findings/mig-04-p0-findings.md` — new findings doc

**If the worker touches any file not in this list, it must stop and escalate rather than proceed.**

## Scope

1. **Inventory every migration script:**
   - List each, what DDL it applies, whether it stamps `schema_versions`.
   - Identify any others besides `add_last_refreshed_at.py` that are missing the stamp.

2. **Check current `schema_versions` state:**
   - `SELECT * FROM schema_versions` on both prod and staging.
   - Which migrations are stamped? Which are missing?
   - Is there a parity gap between prod and staging?

3. **Trace `verify_migration_applied()`:**
   - Where is it defined? What does it check?
   - What breaks if a migration is unstamped?

4. **Cross-item awareness:**
   - mig-01 (atomic promotes) — Batch 3-A parallel-eligible with mig-04.
   - Phase 2 migration 010 — depends on stamp integrity.
   - obs-03-p1 landed migration 010 (`drop_nextval_defaults`) — confirm it stamps correctly.

5. **Phase 1 scope:**
   - Fix the stamp hole in `add_last_refreshed_at.py`.
   - Backfill any other missing stamps.
   - Test plan.

## Out of scope

- Code writes. DB writes. mig-01 (separate item). mig-02 (separate item).

## Deliverable

`docs/findings/mig-04-p0-findings.md` with migration inventory table + stamp status. Cite file:line.

## Hard stop

Do NOT merge. Open PR with title `remediation/mig-04-p0: Phase 0 findings — schema_versions stamp hole`. Report PR URL + CI status.
