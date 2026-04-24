# sec-02-p1 — Phase 1 implementation: admin `/run_script` TOCTOU race fix

## Context

Foundation work under the remediation program (`docs/REMEDIATION_PLAN.md` Theme 4; `docs/REMEDIATION_CHECKLIST.md` Batch 4-A). Audit item MAJOR-10 (C-11, CODEX §3e): the admin `/api/admin/run_script` endpoint uses `pgrep` to check if a script is already running, then launches via `subprocess.Popen`. A 15-line race window between check and spawn allows double-launch on concurrent requests.

Phase 0 investigation complete (`docs/findings/sec-02-p0-findings.md`, PR #11). Recommendation: Option A — per-script `fcntl.flock` with fd inheritance to the child process.

## Design decisions (confirmed by user 2026-04-21)

| # | Decision |
|---|---|
| 1 | Per-script lock (one lock file per allowlisted script). Allows parallel runs of different scripts. |
| 2 | `/api/admin/running` stays on pgrep for now. Lsof migration deferred to follow-up. |
| 3 | No lock timeout. Script runtime limits are the script's own concern. |

## Branch

`remediation/sec-02-p1` off main HEAD.

## Files this session will touch

Write:
- `scripts/admin_bp.py` — replace pgrep check-then-spawn with fcntl.flock acquire-then-spawn at `/run_script` endpoint
- `tests/test_admin_run_script.py` (new) — TOCTOU concurrency test

Read (verification only):
- `docs/findings/sec-02-p0-findings.md` — the design spec (§4 Option A, §5 diff outline)
- `scripts/app.py` — confirm router wiring unchanged
- `web/templates/admin.html` — confirm client handles 409 unchanged

**If the worker touches any file not in this list, it must stop and escalate rather than proceed.**

## Scope

### 1. `admin_bp.py` — flock-based script launch guard

Replace the pgrep check-and-spawn pattern (findings §1.1, lines ~551-567) with:

```python
import fcntl

# Inside /run_script handler, after allowlist validation:
lock_path = os.path.join(BASE_DIR, 'data', f'.run_{script}.lock')
fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
try:
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    os.close(fd)
    return JSONResponse(status_code=409, content={'error': f'{script} is already running'})

# Proceed with log file open + Popen
log_file = open(log_path, 'w', encoding='utf-8')
proc = subprocess.Popen(
    cmd, stdout=log_file, stderr=subprocess.STDOUT,
    cwd=BASE_DIR, pass_fds=(fd,), close_fds=True
)
os.close(fd)  # Parent releases its fd; child inherits a dup — lock holds until child exits
log_file.close()
```

Key implementation points:
- `fcntl.LOCK_NB` makes the lock non-blocking — immediate 409 on contention, no hang.
- `pass_fds=(fd,)` passes the lock fd to the child. The kernel refcounts the open file description; the lock persists until ALL fds (parent + child) are closed. Parent closes its fd immediately after spawn; child holds it until exit.
- `close_fds=True` is the Popen default but make it explicit — it closes all fds EXCEPT those in `pass_fds`.
- Lock files live at `data/.run_<script_name>.lock`. Leading dot keeps them out of normal `ls`. One file per allowlisted script (~8 files). Never need deletion — empty sentinels, ~0 bytes each.
- The existing allowlist check BEFORE the lock acquire stays unchanged — defense in depth.
- Remove the old `pgrep` check-then-act block entirely. Do NOT keep pgrep as a secondary check — it is the vulnerability being remediated.
- The 409 response shape `{'error': '...already running'}` matches what `admin.html` already handles.

### 2. Test: `tests/test_admin_run_script.py`

Concurrency test using FastAPI TestClient:

```python
# Test 1: Two concurrent /run_script requests for the same script
# - Mock subprocess.Popen to spawn a sleep(2) instead of the real script
# - Fire two requests via TestClient (or threading)
# - Assert exactly one returns 200, the other returns 409
# - Assert only one child process exists

# Test 2: After the child exits, a new request succeeds
# - Wait for the mocked child to finish (or kill it)
# - Fire another /run_script request
# - Assert 200

# Test 3: Two concurrent requests for DIFFERENT scripts both succeed
# - Fire /run_script for script_a and script_b simultaneously
# - Assert both return 200
```

Use `unittest.mock.patch` for `subprocess.Popen`. The test must work in CI where the actual pipeline scripts are not available.

Important: the test needs to set `ENABLE_ADMIN=1` and `ADMIN_TOKEN=test` in the environment, and authenticate via `/api/admin/login` before calling `/run_script`.

### 3. Verification

- Pre-commit (ruff + pylint + bandit) clean on all modified files.
- All existing tests pass (`pytest tests/`).
- New concurrency tests pass.
- `make smoke` or equivalent passes.
- Manual curl test (if app is running):
  ```bash
  # Two parallel requests — one should 409
  curl -s --cookie c.jar -X POST http://localhost:8001/api/admin/run_script \
       -H 'Content-Type: application/json' \
       -d '{"script":"compute_flows.py","flags":["--test"]}' &
  curl -s --cookie c.jar -X POST http://localhost:8001/api/admin/run_script \
       -H 'Content-Type: application/json' \
       -d '{"script":"compute_flows.py","flags":["--test"]}' &
  wait
  ```

## Out of scope

- `/add_ticker` concurrency guard (sec-03 scope).
- `/api/admin/running` pgrep-to-lsof migration (follow-up).
- Lock timeout / max script runtime (script's own concern).
- Doc updates to REMEDIATION_CHECKLIST / ROADMAP / SESSION_LOG (batched per doc discipline).

## Rollback

Revert the commit. Lock files under `data/.run_*.lock` are empty sentinels — deleting them is harmless. No migration, no schema change, no session state to clear.

## Hard stop

Do NOT merge. Push to `origin/remediation/sec-02-p1` after each logical commit. Open a PR via `gh pr create` with title `remediation/sec-02-p1: fcntl.flock guard for /run_script TOCTOU race`. Wait for CI green. Report PR URL + CI status. Do NOT merge.
