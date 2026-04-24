# sec-02-p0 — Phase 0 findings: admin `/run_script` TOCTOU race

_Prepared: 2026-04-20 — branch `remediation/sec-02-p0` off main HEAD `4724a1b` (after `7004bbc` + docs commit)._

_Tracker: `docs/REMEDIATION_PLAN.md` Theme 4 row `sec-02`; `docs/REMEDIATION_CHECKLIST.md` Batch 4-A. Audit refs: `docs/SYSTEM_AUDIT_2026_04_17.md` §11.1 C-11; `docs/findings/2026-04-17-codex-review.md` §§1 row 5 and 3c; Pass-2 cross-check row 5._

Phase 0 is investigation only. No code writes and no DB writes were performed. Deliverables: this document + Phase 1 fix recommendation.

sec-01-p1 (server-side session auth) was merged prior to this session. `/api/admin/run_script` is now protected by `require_admin_session` at router scope — verified below.

---

## §1. The race (traced)

### §1.1 Check-and-spawn code path

`/api/admin/run_script` is registered at [scripts/admin_bp.py:533](scripts/admin_bp.py:533) and its body spans lines 534–575. The unsafe window sits entirely in the `try`/post-`try` block:

| Step | Line | Operation |
|---|---|---|
| 1 | [scripts/admin_bp.py:552](scripts/admin_bp.py:552) | `subprocess.run(['pgrep','-f', script], …)` |
| 2 | [scripts/admin_bp.py:553-554](scripts/admin_bp.py:553) | `if ps.returncode == 0: return 409` |
| 3 | [scripts/admin_bp.py:555-556](scripts/admin_bp.py:555) | `except … log.debug(...)` — any pgrep error is swallowed; fall-through |
| 4 | [scripts/admin_bp.py:558-562](scripts/admin_bp.py:558) | Build `script_path` and `cmd` list (pure Python, no syscalls aside from `os.path.join`) |
| 5 | [scripts/admin_bp.py:564-565](scripts/admin_bp.py:564) | Compute `log_name` / `log_path` |
| 6 | [scripts/admin_bp.py:566](scripts/admin_bp.py:566) | `with open(log_path, 'w', encoding='utf-8') as log_file:` — opens and **truncates** the per-script log |
| 7 | [scripts/admin_bp.py:567](scripts/admin_bp.py:567) | `proc = subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT, cwd=BASE_DIR)` |

**Race window length:** 15 executable lines / ~5 syscall-grade operations between the check (step 1) and the `Popen` fork (step 7). In wall time the window is dominated by `pgrep`'s ~5–15 ms exec + the `open('w')` in step 6. On a loaded box this easily exceeds the inter-arrival time of two admin clicks.

### §1.2 What happens on a concurrent second request

Let `T1` be the first `/run_script` with `script='fetch_13dg.py'` and `T2` an identical request arriving while `T1` is between its `pgrep` and `Popen`.

1. `T1` runs `pgrep -f fetch_13dg.py` → returncode 1 (not running) → continues.
2. `T2` runs `pgrep -f fetch_13dg.py` → returncode 1 (still not running; `T1` has not `fork()`ed yet) → continues.
3. `T1` opens `logs/fetch_13dg_run.log` in `'w'` mode → truncates → fork/exec.
4. `T2` opens the **same** `logs/fetch_13dg_run.log` in `'w'` mode → truncates (wipes `T1`'s header lines if any) → fork/exec.

Both children now race for the DuckDB write handle. Terminal states:

- **Winner (usually `T1`):** acquires `data/13f_staging.duckdb` (or `data/13f_research.duckdb` depending on `--staging`) via DuckDB's file-level write lock. Proceeds normally.
- **Loser (`T2`):** DuckDB raises `IOException: Could not set lock on file` on first `duckdb.connect(..., read_only=False)`. Python exits with a stacktrace written to the (now stomped) log file. Exit code non-zero. No DB corruption — DuckDB's single-writer invariant holds here precisely because sec-01-p1 moved `admin_sessions` to a separate DB, so the two children do not cross-lock anything the web app itself depends on.

**Secondary damage:**
1. The single shared log file at `logs/<script>_run.log` is truncated twice and then written concurrently by two processes. Operators investigating a failure see interleaved stdout/stderr and the winner's early banner lines erased by the loser's truncate.
2. The `/api/admin/running` endpoint at [scripts/admin_bp.py:858-871](scripts/admin_bp.py:858) briefly shows both PIDs in its `pgrep` list — visible confusion.
3. `ingestion_manifest` is unaffected at the PK level (manifest rows keyed on `object_key`, not script-name), but any `retry_count` / `error_message` updates performed by the loser before crash may be committed independently of the winner.

**Process-table observation:** `pgrep -f fetch_13dg.py` over the course of the race transitions `no match → two matches` without visiting `one match`. Once the loser crashes, pgrep returns to `one match`. The system recovers on its own; it just presents a noisy operator experience and a momentarily inconsistent log.

### §1.3 Auth gate over `/run_script`

sec-01-p1 landed a router-scope dependency that protects every admin route except `/login`:

- [scripts/admin_bp.py:254-258](scripts/admin_bp.py:254) — `admin_router = APIRouter(prefix='/api/admin', dependencies=[Depends(require_admin_session)])`.
- [scripts/admin_bp.py:191-251](scripts/admin_bp.py:191) — `require_admin_session` enforces env gate + cookie + idle/absolute timeouts, backed by `data/admin.duckdb` (sec-01-p1 hotfix).

`/api/admin/run_script` therefore requires a valid session cookie. There is no header-auth backdoor. Unauthenticated traffic cannot exercise the race; the TOCTOU surface is only reachable to logged-in operators.

The practical threat model is therefore **accidental double-click** or **automation that retries on transient network errors**, not external attack. The availability impact is still real (confused operators, stomped logs, spurious 500s) and the fix is cheap.

---

## §2. Admin write-surface inventory

All routes under `admin_router` share the same auth dependency. Concurrency guard analysis below. (Read-only routes elided except where noted for completeness.)

| Method | Path | Writes | Concurrency guard | Race behaviour |
|---|---|---|---|---|
| POST | `/login` | `adm.admin_sessions` INSERT ([admin_bp.py:317-324](scripts/admin_bp.py:317)) | Per-session UUIDv4 PK | Distinct PKs; no conflict. |
| POST | `/logout` | `adm.admin_sessions` UPDATE ([admin_bp.py:333-344](scripts/admin_bp.py:333)) | `WHERE session_id=?` | Idempotent per session. |
| POST | `/logout_all` | `adm.admin_sessions` UPDATE all ([admin_bp.py:356-358](scripts/admin_bp.py:356)) | Last-writer wins on `revoked_at` | Benign — all NULLs become NOW(); concurrent callers converge. |
| POST | `/add_ticker` | External HTTP + `market_data` INSERT OR REPLACE ([admin_bp.py:411-418](scripts/admin_bp.py:411)) + `CHECKPOINT` | **None** | Two concurrent calls with same ticker: both hit OpenFIGI + Yahoo + SEC (wasted quota), then race for PROD_DB write handle. Loser sees DuckDB `Could not set lock` since this path calls `duckdb.connect(PROD_DB)` while the app's own connection is open. Note: this is a pre-existing hazard independent of sec-02 and is a candidate for sec-03 write-surface audit. |
| POST | **`/run_script`** | Spawns child process ([admin_bp.py:567](scripts/admin_bp.py:567)) | `pgrep` check-then-spawn (TOCTOU — see §1) | See §1.2. |
| POST | `/entity_override` | `entity_classification_history` UPDATE/INSERT, `entities` UPDATE, `entity_aliases` INSERT on `13f_staging.duckdb` ([admin_bp.py:943-…](scripts/admin_bp.py:943)) | Prod target hard-blocked ([admin_bp.py:882-889](scripts/admin_bp.py:882)); staging opened with `read_only=False`. | Two concurrent calls: second's `duckdb.connect(staging_path, read_only=False)` fails at file-lock acquire if staging is open elsewhere (e.g. `merge_staging.py` running, or the other override request). Loud failure; staging integrity preserved. |
| GET | `/staging_preview` | Subprocess foreground, `--dry-run` ([admin_bp.py:843-846](scripts/admin_bp.py:843)) | 30s timeout; no DB writes from parent | Multiple parallel dry-runs are harmless (read-only). |
| GET | `/stats`, `/progress`, `/errors`, `/manager_changes`, `/ticker_changes`, `/parent_mapping_health`, `/stale_data`, `/merger_signals`, `/new_companies`, `/data_quality`, `/running` | Read-only | n/a | n/a |

**Write surfaces needing a guard (feeds sec-03):**

1. `/run_script` — this ticket.
2. `/add_ticker` — no guard of any kind; same-ticker race wastes external API quota and can corrupt a market_data row mid-upsert. Not in sec-02 scope but documented here.
3. `/entity_override` — relies on DuckDB file lock. Acceptable for staging; sec-04 will need a stronger guard when Phase 4 authorizes prod writes.

---

## §3. Cross-item awareness

- **sec-01-p1:** confirmed above that `/run_script` sits behind `require_admin_session`. Any fix must remain compatible with the cookie-based auth flow — no special-case bypass.
- **sec-03 (write-surface audit):** the inventory in §2 is the seed. sec-03 will expand beyond admin routes (promote scripts, merge_staging, fetch_* direct writers) and will evaluate each against the guarding primitive chosen here.
- **obs-03 (`id_allocator.py` `fcntl.flock`):** per `docs/REMEDIATION_PLAN.md` and `docs/findings/obs-03-p0-findings.md`, obs-03 plans to wrap PK allocation in an advisory lock at `data/.manifest_id_seq.lock`. That file does not exist yet — obs-03 is Phase 0/1 and the module has not been committed (verified: `scripts/id_allocator.py` absent from HEAD `4724a1b`). If sec-02 also adopts `fcntl.flock`, lock files should use **disjoint namespaces** to prevent accidental collision:
  - obs-03 lock files: `data/.manifest_id_seq.lock`, `data/.impact_id_seq.lock`, etc. (one per sequence).
  - sec-02 lock files: `data/.run_<script_name>.lock` (one per allowlisted script).
  Both sit under `data/` with the leading-dot prefix. No overlap by construction.
- **DuckDB single-writer invariant:** DuckDB's per-file lock is what makes the current TOCTOU failure loud rather than silent. The fix should **not** rely on DuckDB to catch the race — we want the 409 returned *before* Popen, not after a child process crashes on lock acquire.

---

## §4. Fix option analysis

Four candidates were evaluated. Criteria: complexity, crash-safety, multi-worker safety, operator experience.

### Option A — `fcntl.flock` with fd inheritance

**Mechanism.**
```python
import fcntl, os
lock_path = os.path.join(BASE_DIR, 'data', f'.run_{script}.lock')
fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
try:
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    os.close(fd)
    return JSONResponse(409, {'error': f'{script} is already running'})

proc = subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT,
                        cwd=BASE_DIR, pass_fds=[fd], close_fds=True)
os.close(fd)   # child inherits a duplicate fd; lock persists until ALL fds close
```

- **Complexity:** ~15 lines. No schema changes. Pure stdlib.
- **Crash safety:** Kernel releases `flock` on process exit regardless of cause (SIGKILL, OOM, segfault). No stale state.
- **Multi-worker safety:** `flock` is OS-level, so correct under `uvicorn --workers N`. Current deployment is single-worker ([scripts/app.py:120-126](scripts/app.py:120), no `workers=` kwarg), but flock keeps us correct if that changes.
- **Failure modes:** The only pitfall is *forgetting to pass the fd to the child*. If parent releases its own fd before child inherits, lock drops instantly and a second request wins. The code above handles this via `pass_fds=[fd]` followed by `os.close(fd)` — kernel refcounts the open file description; child keeps the lock until it exits.
- **Observability:** `lsof data/.run_fetch_13dg.py.lock` shows the holder PID; maps 1:1 to the script's own process.

### Option B — PID file

Write PID to `data/.run_<script>.pid` before spawn; check file existence + `kill(pid, 0)` on subsequent requests; clean up via `atexit` or an orphan-reaper sweeper.

- **Complexity:** Moderate. Needs a sweeper (crashed children leave stale PIDs forever otherwise).
- **Crash safety:** **Poor.** `atexit` does not run on SIGKILL / OOM / `kill -9`. Stale PID files are a known chronic operator pain point.
- **Reaper:** Would need to run periodically, check `kill(pid, 0)`, remove dead entries. More moving parts than flock.
- **Multi-worker safety:** OK if writes are atomic (tempfile + rename), but every worker needs the reaper.
- **Verdict:** strictly worse than A. Rejected.

### Option C — In-process `threading.Lock` / `asyncio.Lock`

A module-level `dict[str, threading.Lock]` keyed by script name, acquired non-blocking around the check-and-spawn.

- **Complexity:** Trivial. ~5 lines.
- **Crash safety:** Full — lock dies with the process.
- **Multi-worker safety:** **Broken.** Under `uvicorn --workers 2`, each worker has its own `dict`; two workers can each pass the check and spawn. Current deployment is single-worker, but the fix must not silently depend on that.
- **Verdict:** Correct *today* but a latent footgun. Rejected as the primary mechanism; could be used as a fast-path alongside A in a multi-worker future, but that is premature.

### Option D — Manifest-backed CAS

Write a row to `ingestion_manifest` (or a new `admin_script_runs` table) with `fetch_status='fetching'` before spawn; check for such a row before spawn; clear on child exit.

- **Complexity:** High. The existing `ingestion_manifest` is keyed on `object_key` (per-accession, e.g. an SEC accession number — [migrations/001_pipeline_control_plane.py:57](scripts/migrations/001_pipeline_control_plane.py:57)). A "script is running" row has no natural `object_key` — we'd need a sentinel, e.g. `f"script:{script_name}"`, which muddies the semantic. Alternatively a new `admin_script_runs` table, which is schema work.
- **Crash safety:** Needs a reaper to clear stale `fetching` rows left by killed children. Same class of problem as Option B.
- **Multi-worker safety:** OK — DuckDB's write lock + `INSERT ... WHERE NOT EXISTS` gives atomic CAS.
- **Positive:** Gives historical visibility (who ran what, when). But that belongs in a *logging* table, not a *locking* table — conflating the two creates the stale-row reaper problem.
- **Verdict:** Real upside (audit trail) but solves the wrong problem at the wrong level. Rejected for TOCTOU; the audit-trail angle is worth a separate prompt under the observability theme.

### Summary matrix

| Option | LOC | Crash-safe | Multi-worker safe | Schema change | Recommendation |
|---|---|---|---|---|---|
| A — `fcntl.flock` + fd inheritance | ~15 | ✅ (kernel-released) | ✅ | No | **Recommended** |
| B — PID file + reaper | ~60 + reaper | ⚠️ (stale on SIGKILL) | ✅ | No | Reject |
| C — `threading.Lock` | ~5 | ✅ | ❌ | No | Reject (latent bug) |
| D — manifest CAS | ~50 + reaper | ⚠️ (stale on SIGKILL) | ✅ | Yes | Reject for this use |

---

## §5. Phase 1 recommendation

**Adopt Option A: per-script `fcntl.flock` acquired by the admin endpoint and passed to the child via `pass_fds`.** The kernel releases the lock on child exit regardless of how the child dies, and the approach does not touch the DB schema.

### §5.1 Diff outline

Single-file change. `scripts/admin_bp.py`:

1. Add `import fcntl` at the top alongside the existing `os` / `subprocess` imports.
2. Replace the pgrep check at [scripts/admin_bp.py:551-556](scripts/admin_bp.py:551) and the Popen launch at [scripts/admin_bp.py:566-567](scripts/admin_bp.py:566) with the flock-acquire-then-spawn pattern from §4 Option A.
3. Keep the allowlist check at [scripts/admin_bp.py:542-549](scripts/admin_bp.py:542) **unchanged** — it is a defense-in-depth layer independent of the race.
4. Update the `/api/admin/running` route at [scripts/admin_bp.py:858-871](scripts/admin_bp.py:858) to **optionally** read the flock holders rather than relying on `pgrep` (not required for this fix; leave as follow-up).

No changes to:
- `scripts/app.py` (router wiring unchanged).
- `web/templates/admin.html` (client flow unchanged — same 409 response shape; the UI already surfaces `{'error': '…already running'}`).
- migrations (no schema work).

Estimated change: ~20 lines modified, ~5 added.

### §5.2 Lock-file location & naming

- Directory: `data/` (alongside `13f_research.duckdb` and the staging DBs).
- Filename: `.run_<script_name>.lock` (leading dot keeps it out of normal `ls`).
- Mode: `0o600`.
- One file per allowlisted script; files never need to be deleted (empty, ~0 bytes each, ~8 entries total).
- Namespace is disjoint from obs-03's planned `.manifest_id_seq.lock` etc. (§3).

### §5.3 Test plan (Phase 1)

Integration test (shell-driven; does not need pytest):

```bash
# Bring up a logged-in session — reuse the cookie from an authenticated curl --cookie-jar.
# Fire two /run_script requests in parallel for the same script.
curl -s --cookie ./c.jar -X POST /api/admin/run_script \
     -H 'Content-Type: application/json' \
     -d '{"script":"compute_flows.py","flags":["--test"]}' &
PID1=$!
curl -s --cookie ./c.jar -X POST /api/admin/run_script \
     -H 'Content-Type: application/json' \
     -d '{"script":"compute_flows.py","flags":["--test"]}' &
PID2=$!
wait $PID1 $PID2
# Expected: exactly one 2xx with status='started'; the other returns 409.
# Assert: pgrep -cf compute_flows.py returns 1 (not 2).
```

Cleanup test:

```bash
# Kill the winning child, then immediately retry — should succeed (lock released).
pkill -9 -f compute_flows.py
curl -s --cookie ./c.jar -X POST /api/admin/run_script \
     -d '{"script":"compute_flows.py","flags":["--test"]}'
# Expected: 2xx status='started'.
```

Unit test (pytest, `tests/test_admin_run_script.py`): mock `subprocess.Popen` to a sleep(2), fire two requests via FastAPI's `TestClient`, assert exactly one succeeds within the window and the second returns 409. This isolates the TOCTOU fix from any CI host's ability to actually run the pipeline scripts.

### §5.4 Rollback

Single commit revert. Lock files under `data/.run_*.lock` are empty sentinel files; deleting them has no data-loss impact. No migration to undo. No session-state to clear.

### §5.5 Out of scope for Phase 1

- `/add_ticker` concurrency (noted §2; belongs to sec-03).
- Replacing `pgrep` in `/api/admin/running` (cosmetic cleanup; not blocking).
- Audit trail of who ran what / when (worth a separate prompt under `obs-*`).
- Multi-worker deployment migration (flock handles it correctly if/when we get there).

---

## §6. Open questions

1. **Should the lock protect *any concurrent script* or only the same script?** Current recommendation: per-script (matches the existing `pgrep -f <script>` semantics and allows two different scripts to run in parallel). No evidence in the codebase that cross-script mutual exclusion is required — the DuckDB file lock handles same-DB contention at a lower level.
2. **Should `/api/admin/running` migrate from `pgrep` to `lsof` on lock files?** More robust (doesn't false-positive on a developer's own `grep fetch_13dg.py` shell). Recommend: follow-up ticket, not Phase 1 scope.
3. **Do we want a timeout on the lock itself (max runtime)?** Out of scope here. The right place is the script's own orchestration, not the admin endpoint.

---

## §7. Change log

- 2026-04-20: initial write-up. Branch `remediation/sec-02-p0` off main `4724a1b`.
