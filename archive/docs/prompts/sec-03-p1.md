# sec-03-p1 — Phase 1 implementation: /add_ticker guard + /entity_override IOException→409

## Context

Foundation work under the remediation program (`docs/REMEDIATION_PLAN.md` Theme 4; `docs/REMEDIATION_CHECKLIST.md` Batch 4-B). Audit item MAJOR-5 (C-09). Phase 0 (`docs/findings/sec-03-p0-findings.md`, PR #16) completed the full write-surface audit. Phase 1 bundles the three highest-priority fixes: P0-1 + P0-2 on `/add_ticker` and P1-1 on `/entity_override`.

## Branch

`remediation/sec-03-p1` off main HEAD.

## Files this session will touch

Write:
- `scripts/admin_bp.py` — three changes: flock on `/add_ticker`, ticker regex, IOException catch on `/entity_override`
- `tests/test_admin_add_ticker.py` (new) — concurrency + validation tests

Read (verification only):
- `docs/findings/sec-03-p0-findings.md` — the design spec (§7.1, §7.2, §7.3)

**If the worker touches any file not in this list, it must stop and escalate rather than proceed.**

## Scope

### 1. `/add_ticker` — flock guard (P0-1)

Add `fcntl.flock` serialization to the `/add_ticker` handler, same pattern as sec-02-p1's `/run_script` guard but simpler (no child process, no `pass_fds`).

- Lock file: `data/.add_ticker.lock` (single global lock, not per-ticker — per findings §7.1 rationale).
- `fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)` — non-blocking, immediate 409 on contention.
- Parent holds the lock for the full duration of the handler (external API calls + DB write).
- Release in `finally`: `fcntl.flock(fd, fcntl.LOCK_UN)` then `os.close(fd)`.
- 409 response: `{'error': 'another add_ticker is in flight'}`.

### 2. `/add_ticker` — ticker format validation (P0-2)

Add input validation before any external API call or DB write:

```python
import re
TICKER_RE = re.compile(r'^[A-Z0-9.\-]{1,10}$')
```

After `ticker = (body.get('ticker') or '').upper().strip()`:
```python
if not TICKER_RE.match(ticker):
    return JSONResponse(status_code=400, content={'error': 'invalid ticker format'})
```

This prevents quota-burning garbage from reaching OpenFIGI/Yahoo/SEC and closes the path-traversal concern on any future per-ticker lock file scheme.

### 3. `/entity_override` — IOException→409 (P1-1)

Wrap the `duckdb.connect(staging_path, read_only=False)` call in a try/except:

```python
try:
    con = duckdb.connect(staging_path, read_only=False)
except (duckdb.IOException, duckdb.BinderException) as e:
    return JSONResponse(status_code=409,
                        content={'error': 'staging DB is busy; retry shortly'})
```

Catch both `IOException` (file lock contention) and `BinderException` (same-file different-config conflict, seen in sec-01-p1-hotfix). Upgrades a raw 500 stacktrace to a caller-actionable 409.

### 4. Tests — `tests/test_admin_add_ticker.py`

```python
# Test 1: Two concurrent /add_ticker for the same ticker
# - Mock the external API calls (OpenFIGI, Yahoo, SEC, EDGAR) to sleep(1)
# - Fire two requests via threading
# - Assert exactly one 200, one 409

# Test 2: Invalid ticker format → 400
# - ticker = '../../etc/passwd' → 400
# - ticker = '' → 400
# - ticker = 'AAAAAAAAAAA' (11 chars) → 400
# - ticker = 'AAPL' → passes validation (200 or mocked response)

# Test 3: Valid ticker passes regex
# - ticker = 'BRK.B' → passes (dot allowed)
# - ticker = 'BF-A' → passes (hyphen allowed)
```

Use `unittest.mock.patch` for external API calls. Tests need `ENABLE_ADMIN=1` and `ADMIN_TOKEN=test` in env, and authenticate via `/api/admin/login` before calling `/add_ticker`.

### 5. Verification

- Pre-commit (ruff + pylint + bandit) clean on all modified files.
- All existing tests pass (`pytest tests/`).
- New tests pass.
- `make smoke` or equivalent passes.

## Out of scope

- Per-script flag allowlist (P1-2) — needs sec-04 coordination.
- `/entity_override` row cap (P2-1) — low priority.
- Log rotation for `/run_script` (P2-2) — cosmetic.
- Endpoint classification living doc (P2-3) — process step.
- Doc updates to REMEDIATION_CHECKLIST / ROADMAP / SESSION_LOG (batched).

## Rollback

Revert the commit. `data/.add_ticker.lock` is an empty sentinel — safe to delete. No migration, no schema change.

## Hard stop

Do NOT merge. Push to `origin/remediation/sec-03-p1` after each logical commit. Open a PR via `gh pr create` with title `remediation/sec-03-p1: /add_ticker flock + validation + /entity_override 409`. Wait for CI green. Report PR URL + CI status. Do NOT merge.
