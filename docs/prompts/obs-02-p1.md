# obs-02-p1 — Phase 1 implementation: ADV freshness + code smell fixes

## Context

Foundation work under the remediation program (`docs/REMEDIATION_PLAN.md` Theme 2; `docs/REMEDIATION_CHECKLIST.md` Batch 2-B). Audit item MAJOR-12 (P-02). Phase 0 (`docs/findings/obs-02-p0-findings.md`, PR #28) found: the freshness gap is process (script not re-run), not code. Two minor code smells flagged: unguarded `record_freshness` call and `CHECKPOINT` ordered before freshness write.

This Phase 1 fixes the code smells only. The actual freshness gap closes when you authorize a prod re-run of `fetch_adv.py` — that is a data operation, not a code change.

## Branch

`remediation/obs-02-p1` off main HEAD.

## Files this session will touch

Write:
- `scripts/fetch_adv.py` — fix CHECKPOINT ordering (freshness stamp before CHECKPOINT, not after) + wrap `record_freshness` in try/except so a freshness failure does not crash the whole fetch

Read (verification only):
- `docs/findings/obs-02-p0-findings.md` — the design spec
- `scripts/fetch_market.py` — reference for CHECKPOINT + freshness ordering

**If the worker touches any file not in this list, it must stop and escalate rather than proceed.**

## Scope

### 1. CHECKPOINT ordering

Per findings: `CHECKPOINT` currently fires before `record_freshness`. If the process crashes between CHECKPOINT and freshness write, the data is committed but freshness is not stamped — the admin dashboard shows stale even though data is current. Fix: move `record_freshness` call before `CHECKPOINT`, or (simpler) wrap both in a sequence where freshness is stamped first.

### 2. Guard `record_freshness`

Wrap the `record_freshness` call in try/except so a failure (e.g. schema drift on `data_freshness` table) does not crash the entire fetch. Log the error but allow the fetch to complete — data landing is more important than the freshness stamp.

### 3. Verification

- Pre-commit clean. All existing tests pass. `make smoke` passes.
- Read the final `fetch_adv.py` to confirm ordering: data write → manifest write → freshness stamp → CHECKPOINT.

## Out of scope

- Structured logging migration (no fetcher uses Python `logging` — this is a repo-wide decision, not obs-02).
- Prod re-run of `fetch_adv.py` (requires separate authorization).
- mig-02 (DROP+CREATE atomicity — separate item, serial with obs-02).
- Doc updates (batched).

## Rollback

Revert the commit. Restores original CHECKPOINT + freshness ordering.

## Hard stop

Do NOT merge. Push to `origin/remediation/obs-02-p1`. Open PR with title `remediation/obs-02-p1: ADV freshness ordering + guard`. Wait for CI green. Do NOT merge.
