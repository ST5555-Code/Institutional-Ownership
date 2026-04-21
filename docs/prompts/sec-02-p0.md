# sec-02-p0 — Phase 0 investigation: admin `/run_script` TOCTOU race

## Context

Foundation work under the remediation program (`docs/REMEDIATION_PLAN.md` Theme 4; `docs/REMEDIATION_CHECKLIST.md` Batch 4-A). Audit item MAJOR-10 (C-11, CODEX §3e): the admin `/api/admin/run_script` endpoint uses `pgrep` to check if a script is already running, then launches it via `subprocess.Popen`. Between the check and the spawn, a second request can pass the same check and double-launch the same script. DuckDB's per-file write lock makes the second instance fail loudly (not silently corrupt), but the TOCTOU is still an availability bug and a confusing operator experience.

sec-01-p1 (server-side session auth) is now merged. sec-02 was serialized behind sec-01 because both touch `admin_bp.py`. The session auth changes are now in place — this investigation builds on top of them.

Phase 0 is investigation only: trace the race window, inventory all admin write endpoints, design the fix. **No code writes, no DB writes.**

## Branch

`remediation/sec-02-p0` off main HEAD.

## Files this session will touch

Read-only / investigation:
- `scripts/admin_bp.py` — the `/run_script` endpoint, `pgrep` guard, `subprocess.Popen` launch, all admin write endpoints
- `scripts/app.py` — router wiring
- `web/templates/admin.html` — client-side invocation of `/run_script`
- `docs/findings/sec-01-p0-findings.md` — cross-reference session auth changes
- `docs/CODEX_REVIEW_2026_04_17.md` — §3e TOCTOU description
- `docs/SYSTEM_AUDIT_2026_04_17.md` — MAJOR-10 C-11

Write:
- `docs/findings/sec-02-p0-findings.md` — new findings doc

**If the worker touches any file not in this list, it must stop and escalate rather than proceed.**

## Scope

1. **Trace the TOCTOU race window:**
   - Locate the `pgrep` check in `admin_bp.py` (expected around lines 260-285 pre-sec-01-p1, line numbers may have shifted).
   - Identify the exact code path: `pgrep -f <script_name>` → check returncode → `subprocess.Popen(...)`.
   - Measure the race window: how many lines / operations between the check and the spawn?
   - What happens if two requests hit `/run_script` with the same script name within the race window? Trace both paths to their terminal state (DuckDB lock failure, zombie process, etc.).

2. **Inventory the admin write surface:**
   - List every admin endpoint that performs a write (to DB, filesystem, or subprocess).
   - For each: what guard (if any) prevents concurrent invocation?
   - This feeds sec-03 (write-surface audit) — capture the inventory now.

3. **Evaluate fix options:**
   - **Option A: `fcntl.flock` on a per-script lock file** (e.g. `data/.run_<script_name>.lock`). The script process itself holds the lock; the admin endpoint checks the lock before spawning.
   - **Option B: PID file written by the admin endpoint** before `Popen`, checked before spawn, cleaned up on process exit. Requires a reaper or `atexit`.
   - **Option C: In-process lock (threading.Lock or asyncio.Lock)** guarding the check-and-spawn as an atomic operation. Only works within a single uvicorn worker; breaks under multi-worker deployment.
   - **Option D: Manifest-based CAS** — write a "running" row to `ingestion_manifest` before spawn, check for it before spawn, clear on exit. Reuses existing infrastructure.
   - For each option: assess complexity, failure modes, multi-worker safety, cleanup-on-crash behavior.

4. **Cross-item awareness:**
   - sec-01-p1 changed the auth dependency on the admin router. Confirm the `/run_script` endpoint now uses `require_admin_session` (cookie-based), not the old header auth.
   - sec-03 (write-surface audit) consumes this investigation's endpoint inventory.
   - obs-03 `id_allocator.py` uses `fcntl.flock` for a different purpose (PK allocation). If sec-02 also uses `fcntl.flock`, document the two lock files and their non-overlapping scope.

5. **Design the Phase 1 fix:**
   - Recommend one option with justification.
   - Scope the implementation: which files change, what the diff outline looks like.
   - Test plan: concurrent curl requests to `/run_script` with the same script name — only one should launch.
   - Rollback path.

## Out of scope

- Code writes.
- DB writes.
- sec-03 write-surface audit (consumes this output).
- sec-04 validators writing to prod.
- Any changes to the session auth system (sec-01-p1, already merged).

## Deliverable

`docs/findings/sec-02-p0-findings.md` structured like `sec-01-p0-findings.md`. Cite file:line. Include the endpoint inventory table, the race window trace, and a recommendation with trade-off analysis for each fix option.

## Hard stop

Do NOT merge. Open a PR via `gh pr create` with title `remediation/sec-02-p0: Phase 0 findings — admin run_script TOCTOU race`. Report PR URL + CI status.
