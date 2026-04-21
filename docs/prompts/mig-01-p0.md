# mig-01-p0 — Phase 0 investigation: atomic promotes + manifest mirror helper

## Context

Foundation work under the remediation program (`docs/REMEDIATION_PLAN.md` Theme 3; `docs/REMEDIATION_CHECKLIST.md` Batch 3-A). Audit item BLOCK-2: `promote_nport.py` and `promote_13dg.py` perform DELETE+INSERT sequences without transaction wrapping. A crash mid-promote leaves the target table in a partial state. Additionally, the `_mirror_manifest_and_impacts` helper is duplicated across both promote scripts rather than extracted to `pipeline/manifest.py`.

obs-03-p1 (id_allocator + reserve_ids) already modified both promote scripts' mirror paths to use `reserve_ids` instead of staging-PK copy. This investigation builds on that state.

Phase 0 is investigation only. **No code writes, no DB writes.**

## Branch

`remediation/mig-01-p0` off main HEAD.

## Files this session will touch

Read-only / investigation:
- `scripts/promote_nport.py` — DELETE+INSERT promote pattern, mirror helper, transaction handling
- `scripts/promote_13dg.py` — same pattern
- `scripts/pipeline/manifest.py` — existing helpers, candidate location for extracted mirror helper
- `scripts/pipeline/id_allocator.py` — `reserve_ids` integration (obs-03-p1 output)
- `scripts/promote_staging.py` — orchestrator that calls promote scripts
- `data/13f.duckdb` (read-only) — check current table states if needed

Write:
- `docs/findings/mig-01-p0-findings.md` — new findings doc

**If the worker touches any file not in this list, it must stop and escalate rather than proceed.**

## Scope

1. **Trace the promote flow for both scripts:**
   - What tables does each promote? What is the DELETE+INSERT sequence?
   - Is there any transaction wrapping (BEGIN/COMMIT) today?
   - What happens on a crash mid-promote? Which tables are left inconsistent?
   - How does the manifest/impacts mirror work post-obs-03-p1?

2. **Identify the duplicated code:**
   - What code is shared between `promote_nport.py` and `promote_13dg.py`?
   - What is the natural extraction boundary for a `_mirror_manifest_and_impacts` helper?
   - Where should it live — `pipeline/manifest.py` or a new `pipeline/promote.py`?

3. **Assess DuckDB transaction semantics:**
   - Does DuckDB support multi-statement transactions with rollback?
   - What is the correct pattern for atomic DELETE+INSERT on DuckDB?
   - Are there any gotchas (auto-commit, CHECKPOINT interaction)?

4. **Cross-item awareness:**
   - obs-03-p1 (reserve_ids) — already modified the mirror paths. New code must not regress.
   - mig-02 (fetch_adv.py atomicity) — same class of problem (DROP+CREATE without transaction). Serial with obs-02 on fetch_adv.py.
   - mig-04 (stamp backfill) — merged. Promote scripts should stamp if they don't already.
   - sec-04 (validators) — `promote_staging.py` calls `validate_entities.py` during promote. The sec-04-p1 changes (RO default) must be compatible.

5. **Phase 1 scope:**
   - Transaction wrapping for both promote scripts.
   - Extracted mirror helper.
   - Test plan.

## Out of scope

- Code writes. DB writes. mig-02 (separate). obs-03/obs-04 changes.

## Deliverable

`docs/findings/mig-01-p0-findings.md` with promote flow trace, duplication inventory, transaction design.

## Hard stop

Do NOT merge. Open PR with title `remediation/mig-01-p0: Phase 0 findings — atomic promotes + manifest mirror helper`. Report PR URL + CI status.
