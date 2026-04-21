# mig-04-p1 — Phase 1 implementation: schema_versions stamp backfill

## Context

Foundation work under the remediation program (`docs/REMEDIATION_PLAN.md` Theme 3; `docs/REMEDIATION_CHECKLIST.md` Batch 3-A). Audit item MAJOR-16 (S-02). Phase 0 (`docs/findings/mig-04-p0-findings.md`, PR #26) found 4 migrations missing `schema_versions` stamps (001, 002 predate the table; 004 and add_last_refreshed_at are real bugs). Prod has 7 stamps, staging has 6. Both need backfill to reach 11.

## Branch

`remediation/mig-04-p1` off main HEAD.

## Files this session will touch

Write:
- `scripts/migrations/add_last_refreshed_at.py` — add `_already_stamped()` check + stamp at end
- `scripts/migrations/004_schema_versions_stamp.py` — add stamp (if not already present; check findings for exact state)
- `scripts/oneoff/backfill_schema_versions_stamps.py` (new) — one-shot script to backfill all missing stamps on both prod and staging
- `scripts/verify_migration_stamps.py` (new) — mechanized check that all migrations are stamped; exits non-zero on gaps

Read (verification only):
- `docs/findings/mig-04-p0-findings.md` — the design spec
- `scripts/migrations/001_pipeline_control_plane.py` through `010_drop_nextval_defaults.py` — reference for stamp patterns
- `data/13f.duckdb` (read-only) — check current stamp state
- `data/13f_staging.duckdb` (read-only) — check parity

**If the worker touches any file not in this list, it must stop and escalate rather than proceed.**

## Scope

### 1. Fix the stamp holes

Add `_already_stamped()` + `INSERT INTO schema_versions` to:
- `scripts/migrations/add_last_refreshed_at.py`
- `scripts/migrations/004_schema_versions_stamp.py` (check findings — 004 may be `004_nullable_columns.py` or similar; use the actual filename)

Follow the pattern from migrations 005-010 (the `_already_stamped` inline helper).

### 2. Backfill script

`scripts/oneoff/backfill_schema_versions_stamps.py`:
- Accepts `--prod`, `--staging`, or both.
- For each migration (001 through 010 + add_last_refreshed_at): check if stamped, insert if not.
- `--dry-run` flag.
- Idempotent (INSERT ... ON CONFLICT DO NOTHING or check-before-insert).
- Print summary: which stamps were added.

### 3. Verify script

`scripts/verify_migration_stamps.py`:
- Reads `schema_versions` from the target DB.
- Compares against expected set (all migration scripts in `scripts/migrations/`).
- Exits 0 if all stamped, non-zero with a list of gaps.
- Can be wired into CI or `make validate` later.

### 4. Run the backfill

After the scripts are written and tested:
- `python3 scripts/oneoff/backfill_schema_versions_stamps.py --prod --dry-run`
- `python3 scripts/oneoff/backfill_schema_versions_stamps.py --staging --dry-run`
- If counts look right, run without `--dry-run` on both.
- Run `python3 scripts/verify_migration_stamps.py --prod` and `--staging` — both should exit 0.

### 5. Verification

- Pre-commit clean. All existing tests pass. `make smoke` passes.
- `SELECT * FROM schema_versions` on both DBs shows all migrations stamped.
- Verify script exits 0 on both.

## Out of scope

- mig-01 (atomic promotes). mig-02 (fetch_adv atomicity). Doc updates (batched).

## Rollback

Revert the commit. Stamps are additive metadata — leaving them in place is harmless.

## Hard stop

Do NOT merge. Push to `origin/remediation/mig-04-p1`. Open PR with title `remediation/mig-04-p1: schema_versions stamp backfill + verify script`. Wait for CI green. Do NOT merge.
