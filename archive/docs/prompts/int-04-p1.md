# int-04-p1 — Phase 1 implementation: RC4 issuer_name propagation in build_cusip.py

## Context

Foundation work under the remediation program (`docs/REMEDIATION_PLAN.md` Theme 1; `docs/REMEDIATION_CHECKLIST.md` Batch 1-A). Phase 0 (`docs/findings/int-04-p0-findings.md`, PR #18) found RC4 is half-shipped: `normalize_securities.py:50` was fixed in `889e4e1`, but `build_cusip.py:313-327` (the `update_securities_from_classifications` inline block wired into `make build-cusip`) still omits `issuer_name` from the column update set. Prod divergence is currently 0 because `normalize_securities.py` ran post-fix, but the `build_cusip.py` path would re-introduce drift on the next run.

Phase 1 scope: add `issuer_name` to the update set in `build_cusip.py` + regression test.

## Branch

`remediation/int-04-p1` off main HEAD.

## Files this session will touch

Write:
- `scripts/build_cusip.py` — add `issuer_name` to the `UPDATE securities SET ...` block at lines ~313-327
- `tests/pipeline/test_issuer_propagation.py` (new) — regression test confirming issuer_name propagates

Read (verification only):
- `docs/findings/int-04-p0-findings.md` — the design spec
- `scripts/normalize_securities.py` — reference for the already-fixed path (confirm column list)
- `data/13f.duckdb` (read-only) — verify 0 divergence pre and post

**If the worker touches any file not in this list, it must stop and escalate rather than proceed.**

## Scope

### 1. `build_cusip.py` — add issuer_name to update set

Locate the `UPDATE securities SET ...` block (lines ~313-327 per findings). Add `issuer_name = cc.issuer_name` to the SET clause. The UPDATE should already join on `cusip` — just add the column.

Check the findings doc for the exact line reference and current column list. The fix is literally adding one column to an existing UPDATE statement.

### 2. Regression test

A test that creates a minimal DuckDB with `securities` and `cusip_classifications` tables, runs the update function, and asserts `securities.issuer_name` matches `cusip_classifications.issuer_name` afterward. No network, no external deps.

### 3. Verification

- Pre-commit clean.
- All existing tests pass.
- New test passes.
- Read-only check: `SELECT COUNT(*) FROM securities s JOIN cusip_classifications cc ON s.cusip = cc.cusip WHERE COALESCE(s.issuer_name,'') != COALESCE(cc.issuer_name,'')` returns 0 (should already be 0, confirming no regression).

## Out of scope

- int-05 (Pass C sweep).
- int-06 (forward hooks).
- normalize_securities.py changes (already fixed).

## Rollback

Revert the commit. One column removed from an UPDATE SET clause.

## Hard stop

Do NOT merge. Push to `origin/remediation/int-04-p1`, open PR with title `remediation/int-04-p1: add issuer_name to build_cusip.py propagation`. Wait for CI green. Do NOT merge.
