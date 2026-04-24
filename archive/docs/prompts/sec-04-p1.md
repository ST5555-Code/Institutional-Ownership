# sec-04-p1 — Phase 1 implementation: validator read-only fixes

## Context

Foundation work under the remediation program (`docs/REMEDIATION_PLAN.md` Theme 4; `docs/REMEDIATION_CHECKLIST.md` Batch 4-B). Audit item MAJOR-1 (C-02). Phase 0 (`docs/findings/sec-04-p0-findings.md`, PR #24) found 2 validators opening prod RW: `validate_entities.py` (accidental) and `validate_nport_subset.py` (intentional but misplaced).

This Phase 1 covers findings §5.1 and §5.2 only. §5.3 (`entity_gate_check write_pending` kwarg in `pipeline/shared.py`) is deferred — it must serialize with int-21 per the remediation plan.

## Branch

`remediation/sec-04-p1` off main HEAD.

## Files this session will touch

Write:
- `scripts/validate_entities.py` — flip `--read-only` default so validators default RO, add `--write` escape hatch
- `scripts/validate_nport_subset.py` — extract INSERT + CHECKPOINT into a new `scripts/queue_nport_excluded.py`; validator becomes read-only
- `scripts/queue_nport_excluded.py` (new) — the extracted write step
- `Makefile` — update `make validate` invocation if needed (likely no-op since --read-only becomes default)
- `scripts/promote_staging.py` — update subprocess call if needed (likely no-op)

Read (verification only):
- `docs/findings/sec-04-p0-findings.md` — the design spec (§5.1, §5.2)

**If the worker touches any file not in this list, it must stop and escalate rather than proceed.**

## Scope

### 1. `validate_entities.py` — flip default to read-only (§5.1)

- Change the `--read-only` flag (lines ~832-835) so it defaults to True. Add `--write` / `--rw` flag for explicit opt-in to RW mode.
- When `--read-only` (now default): use `db.connect_read()` or `duckdb.connect(path, read_only=True)`.
- When `--write`: use current `db.connect_write()` path.
- Update `Makefile:126` and `promote_staging.py:668` if they need a new flag (likely no change needed since read-only is now default and all 16 gates are pure SELECT).
- Zero functional change — all gates are SELECT-only.

### 2. `validate_nport_subset.py` — split validate from queue (§5.2)

- Extract the `INSERT INTO pending_entity_resolution` block (lines ~188-196) and `CHECKPOINT` (line ~268) into a new `scripts/queue_nport_excluded.py`.
- `validate_nport_subset.py` opens prod RO, produces the report, exits. No writes.
- `queue_nport_excluded.py` reads the validator's output (excluded series list) and performs the INSERT + CHECKPOINT against prod RW.
- Update docstring recipes in `fetch_nport_v2.py:388-389` and `fetch_dera_nport.py:1216` to show the two-command sequence.
- The new script should support `--dry-run`.

### 3. NOT in scope — `pipeline/shared.py entity_gate_check`

§5.3 is deferred. Do NOT touch `pipeline/shared.py`. It must serialize with int-21.

### 4. Verification

- `python scripts/validate_entities.py --prod` exits 0, identical report to pre-change.
- `python scripts/validate_nport_subset.py` produces report without writing `pending_entity_resolution`.
- `python scripts/queue_nport_excluded.py --dry-run` shows what would be queued.
- Pre-commit clean. All existing tests pass. `make smoke` passes.
- `make validate` still works (if it exists in Makefile).

## Out of scope

- `pipeline/shared.py` changes (deferred to post-int-21).
- sec-05/sec-06 (separate items).
- Doc updates (batched).

## Rollback

Revert the commit. Restore validator RW defaults.

## Hard stop

Do NOT merge. Push to `origin/remediation/sec-04-p1`. Open PR with title `remediation/sec-04-p1: validators default read-only + split validate from queue`. Wait for CI green. Do NOT merge.
