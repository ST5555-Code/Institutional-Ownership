# sec-03-p0 — Phase 0 findings: admin endpoint write-surface audit

_Prepared: 2026-04-21 — branch `remediation/sec-03-p0` off main HEAD `c8cee2f`._

_Tracker: `docs/REMEDIATION_PLAN.md` Theme 4 row `sec-03`; `docs/REMEDIATION_CHECKLIST.md` Batch 4-B. Audit refs: `docs/SYSTEM_AUDIT_2026_04_17.md` §11 MAJOR-5 (C-09); `docs/findings/2026-04-17-codex-review.md` §§1 row 6. Upstream: sec-02-p0 §2 preliminary inventory._

Phase 0 is investigation only. No code writes and no DB writes were performed. Deliverables: this document + Phase 1 fix recommendation.

Prerequisites already merged: sec-01-p1 (server-side session auth on `admin_router`), sec-01-p1-hotfix (admin_sessions moved to `data/admin.duckdb`), sec-02-p1 (`fcntl.flock` guard on `/run_script`). This audit assumes those protections are live — verified in §1.

---

## §1. Scope and method

**Scope.** Every route mounted on `admin_router` (`scripts/admin_bp.py`), plus every route mounted on the non-admin routers wired into `app.py` that is reachable from `web/templates/admin.html`. For each route: method, path, write targets, guards, idempotency, blast radius.

**Method.** Source-of-truth walk of:

- `scripts/app.py` — router wiring ([app.py:74-77](scripts/app.py:74)).
- `scripts/admin_bp.py` — full file (1102 lines).
- `scripts/api_*.py` — every `@*_router.<verb>` decorator.
- `web/templates/admin.html` — every `/api/...` invocation.

No runtime probing (the prompt forbids it).

**Router wiring inventory.** `app.py` includes eight routers:

| Router | Module | Prefix | Auth dep |
|---|---|---|---|
| `admin_router` | `admin_bp.py` | `/api/admin` | `require_admin_session` ([admin_bp.py:255-259](scripts/admin_bp.py:255)) |
| `config_router` | `api_config.py` | (root) | none |
| `register_router` | `api_register.py` | (root) | none |
| `fund_router` | `api_fund.py` | (root) | none |
| `flows_router` | `api_flows.py` | (root) | none |
| `entities_router` | `api_entities.py` | (root) | none |
| `market_router` | `api_market.py` | (root) | none |
| `cross_router` | `api_cross.py` | (root) | none |

**Prompt note (stale file list).** The Phase 0 prompt lists `api_flow.py`, `api_conviction.py`, `api_crowding.py`, `api_smart_money.py`, `api_peer.py`, `api_sector.py`, `api_new_exits.py`, `api_aum.py`. None of those modules exist at `c8cee2f`; the functions have been consolidated into `api_flows.py`, `api_fund.py`, `api_market.py`, and `api_cross.py` (the React migration — see `project_react_migration_status` memory). This audit inventories the actual modules. No file outside the prompt's write list was written.

**Verification of upstream guards.**

- sec-01-p1 router-scope dep — confirmed at [admin_bp.py:255-259](scripts/admin_bp.py:255): `admin_router = APIRouter(prefix='/api/admin', …, dependencies=[Depends(require_admin_session)])`. Every non-`/login` admin route runs `require_admin_session` ([admin_bp.py:192-252](scripts/admin_bp.py:192)) before its handler — cookie + env gate + idle/absolute timeouts.
- sec-02-p1 flock guard on `/run_script` — confirmed at [admin_bp.py:552-565](scripts/admin_bp.py:552) and [admin_bp.py:577-589](scripts/admin_bp.py:577): `fcntl.flock(lock_fd, LOCK_EX|LOCK_NB)` before `Popen`, `pass_fds=(lock_fd,)` into the child, parent `os.close(lock_fd)` in `finally`. Matches the sec-02-p0 §4 Option A recommendation exactly.

---

## §2. Complete endpoint inventory

Table extends the sec-02-p0 §2 schema. **All `admin_router` routes** (18 in total); non-admin routers tabulated separately in §3. Every admin route except `/login` is session-cookie-gated via the router-scope dependency.

| # | Method | Path | Writes / effects | Concurrency guard | Input validation | Idempotent | Blast radius on failure |
|---|---|---|---|---|---|---|---|
| 1 | POST | `/api/admin/login` | INSERT `adm.admin_sessions` ([admin_bp.py:317-325](scripts/admin_bp.py:317)); sets `admin_session` cookie ([admin_bp.py:327](scripts/admin_bp.py:327)) | Per-session UUID4 PK; env gate; `hmac.compare_digest` | `body.token` non-empty; no format regex — constant-time compared | No (each call creates a new row) | None — PKs distinct; failure returns 403/503; loud. |
| 2 | POST | `/api/admin/logout` | UPDATE `adm.admin_sessions SET revoked_at=NOW() WHERE session_id=?` ([admin_bp.py:336-345](scripts/admin_bp.py:336)); clears cookie | `WHERE session_id=?` is single-row | Cookie presence only | Yes (targets own session) | None — UPDATE converges. |
| 3 | POST | `/api/admin/logout_all` | UPDATE all un-revoked `adm.admin_sessions` ([admin_bp.py:356-359](scripts/admin_bp.py:356)); clears cookie | Last-writer wins on `revoked_at`; NULL→NOW() is monotone | None beyond auth dep | Yes (rerun is no-op) | Forced re-login for all operators; benign. |
| 4 | POST | `/api/admin/add_ticker` | **External HTTP** to OpenFIGI ([admin_bp.py:382-386](scripts/admin_bp.py:382)), Yahoo ([admin_bp.py:404](scripts/admin_bp.py:404)), SEC XBRL ([admin_bp.py:407](scripts/admin_bp.py:407)), EDGAR ([admin_bp.py:432-442](scripts/admin_bp.py:432)); **INSERT OR REPLACE** on PROD_DB `market_data` ([admin_bp.py:410-420](scripts/admin_bp.py:410)); `CHECKPOINT` ([admin_bp.py:419](scripts/admin_bp.py:419)) | **None** | Ticker: `.upper().strip()`, non-empty check only; no regex, no length cap | `INSERT OR REPLACE` is logically idempotent per ticker, but external quota is not | See §4.4. |
| 5 | POST | `/api/admin/run_script` | `subprocess.Popen` against allowlisted script ([admin_bp.py:577-584](scripts/admin_bp.py:577)); truncates `logs/<script>_run.log` ([admin_bp.py:576](scripts/admin_bp.py:576)) | **`fcntl.flock`** on `data/.run_<script>.lock`, non-blocking, fd passed to child ([admin_bp.py:559-589](scripts/admin_bp.py:559)) — **sec-02-p1** | Script allowlist check ([admin_bp.py:543-550](scripts/admin_bp.py:543)); flags list pass-through, no per-flag validation | Safe to call twice — second returns 409 | Per sec-02-p0 §1; now mitigated — loud 409 instead of stomped log. |
| 6 | GET | `/api/admin/stats` | Read-only; `con.close()` on a thread-local handle | n/a | None | n/a | n/a |
| 7 | GET | `/api/admin/progress` | Read-only; reads `logs/phase2_progress.txt`; `pgrep` subprocess ([admin_bp.py:495](scripts/admin_bp.py:495)) | n/a | None | n/a | n/a |
| 8 | GET | `/api/admin/errors` | Read-only; reads `logs/fetch_13dg_errors.csv` | n/a | None | n/a | n/a |
| 9 | GET | `/api/admin/manager_changes` | Read-only | n/a | None | n/a | n/a (latest/prev quarter are module constants, not user input) |
| 10 | GET | `/api/admin/ticker_changes` | Read-only | n/a | None | n/a | n/a |
| 11 | GET | `/api/admin/parent_mapping_health` | Read-only | n/a | None | n/a | n/a |
| 12 | GET | `/api/admin/stale_data` | Read-only | n/a | None | n/a | n/a |
| 13 | GET | `/api/admin/merger_signals` | Read-only | n/a | None | n/a | n/a |
| 14 | GET | `/api/admin/new_companies` | Read-only | n/a | None | n/a | n/a |
| 15 | GET | `/api/admin/data_quality` | Read-only; reads `logs/fetch_13dg_errors.csv` | n/a | None | n/a | n/a |
| 16 | GET | `/api/admin/staging_preview` | Subprocess foreground `merge_staging.py --all --dry-run`, 30 s timeout ([admin_bp.py:865-868](scripts/admin_bp.py:865)); no DB writes from the foreground call | Timeout is the only guard; `--dry-run` prevents any committed write | None — no body | Multiple parallel dry-runs are harmless (read-only DB + external subprocess) | Benign. |
| 17 | GET | `/api/admin/running` | Read-only; `pgrep` subprocess ([admin_bp.py:887](scripts/admin_bp.py:887)) per hardcoded script name | n/a | None | n/a | n/a (false-positives when a dev's shell matches a `pgrep -f` pattern — cosmetic). |
| 18 | POST | `/api/admin/entity_override` | On `data/13f_staging.duckdb`: UPDATE `entity_classification_history.valid_to`, INSERT new row ([admin_bp.py:967-981](scripts/admin_bp.py:967)); INSERT `entity_aliases` ([admin_bp.py:1006-1014](scripts/admin_bp.py:1006)); UPDATE/INSERT `entity_rollup_history` ([admin_bp.py:1027-1041](scripts/admin_bp.py:1027)); INSERT `entity_overrides_persistent` ([admin_bp.py:1070-1077](scripts/admin_bp.py:1070)); appends `logs/entity_overrides.log` ([admin_bp.py:1082](scripts/admin_bp.py:1082)) | **Prod hard-blocked** ([admin_bp.py:903-911](scripts/admin_bp.py:903)); DuckDB single-writer lock on staging file | CSV column schema ([admin_bp.py:929-937](scripts/admin_bp.py:929)); per-row `int()`/`.lower()`; parameterized SQL; but **no CSV row-count cap** | Per-row BEGIN/COMMIT on reclassify+merge; partial on error | See §4.6. |

**Summary counts.** 18 admin routes total. 6 write, 12 read-only. Of the write routes: 5 have an explicit guard (login/logout/logout_all by auth dep + SQL idempotence; run_script by flock); 1 (`/add_ticker`) is ungated; 1 (`/entity_override`) is partially gated.

---

## §3. Non-admin write paths reachable from admin UI

**Audit.** `grep -n '@\w*_router\.\(post\|put\|patch\|delete\)'` over `scripts/api_*.py` at `c8cee2f` returns **zero matches**. Every non-admin route is `GET`. Secondary check: `grep` for `INSERT`, `UPDATE`, `DELETE`, `subprocess.(run|Popen)`, `open(..., 'w')`, `open(..., 'a')`, `.commit`, `CHECKPOINT` across the same files returns no hits. Every handler is pure read via `con.execute(...).fetchdf()/fetchone()/fetchall()`.

**UI cross-check.** `web/templates/admin.html` contains exactly 14 fetch callsites, all pointing at `/api/admin/*`:

```
/api/admin/login, /api/admin/logout, /api/admin/stats, /api/admin/progress,
/api/admin/errors, /api/admin/add_ticker, /api/admin/run_script,
/api/admin/running, /api/admin/data_quality, /api/admin/manager_changes,
/api/admin/ticker_changes, /api/admin/merger_signals, /api/admin/new_companies
```

Five admin-router endpoints are **not** invoked from admin.html — `/logout_all`, `/parent_mapping_health`, `/stale_data`, `/staging_preview`, `/entity_override`. These are operator-invoked via `curl`/automation; they remain gated by `require_admin_session` at the router level, but their absence from the UI means they receive less day-to-day exercise and less visibility if something regresses.

**Conclusion for §3.** The admin UI does not reach any non-admin write path because no non-admin write paths exist. The write surface is fully contained within `admin_router`.

---

## §4. Per-endpoint risk assessment (write routes)

Read-only routes are elided. Six write routes are analyzed in detail; assessments lead with the dominant failure mode and end with a fix disposition.

### §4.1 `/api/admin/login` — GUARDED

Issues a new server-side session on token match. The token check is `hmac.compare_digest` (constant-time), env-gated by `_env_admin_enabled()`. Each call generates a fresh UUID4 PK so concurrent logins cannot collide on the `session_id` column. No rate-limit on login attempts — an attacker who can already bypass the network perimeter gets unbounded guesses against the constant-time compare, but `ADMIN_TOKEN` is a pre-shared secret, not a password, so lockout has low marginal value. The one residual concern is that `INSERT` onto `admin_sessions` runs without an upper row cap: an adversary with a valid token could spam logins and grow the table unboundedly. The opportunistic sweep at [admin_bp.py:248-252](scripts/admin_bp.py:248) removes expired rows at a ~1% sample rate; adequate for legitimate traffic, but a dedicated attacker could still grow the table faster than the sweep clears it. **Fix disposition:** monitor table row count in `/stats`; add a hard cap + 429 in a future hardening pass. Not Phase 1.

### §4.2 `/api/admin/logout` — GUARDED

Single-row UPDATE by PK, idempotent by construction (`WHERE revoked_at IS NULL`). No risk. **Fix disposition:** none.

### §4.3 `/api/admin/logout_all` — GUARDED

Table-scan UPDATE setting `revoked_at = NOW()` on all non-revoked rows. Concurrent callers converge (NULL → NOW() is monotone). Side effect of forcing every operator to re-login is the intended behavior. **Fix disposition:** none.

### §4.4 `/api/admin/add_ticker` — UNGUARDED **(P0 carried from sec-02-p0 §2)**

Confirmed unguarded. Three distinct concerns:

1. **No concurrency guard.** Two simultaneous `POST /api/admin/add_ticker {"ticker":"AAPL"}` calls both hit OpenFIGI, Yahoo, SEC XBRL, and EDGAR end-to-end before racing for the DuckDB write handle. The second call's `duckdb.connect(PROD_DB)` at [admin_bp.py:410](scripts/admin_bp.py:410) attempts a fresh RW connection while the app's request-thread connection is already open — this is exactly the pre-sec-01-p1-hotfix failure class (different-mode cross-configuration error). Even under single-writer semantics, the loser raises `duckdb.IOException: Could not set lock on file` and the `INSERT OR REPLACE` for that ticker is lost. In practice the winner's write is correct, but the operator sees a 500 stacktrace for the loser with no clear signal that the ticker actually landed.
2. **External-quota burn.** The three external services are called before any DuckDB contention happens. A double-click costs at minimum 2× the quota (OpenFIGI free tier is 25 req/6s, Yahoo is unmetered but rate-limits via 429, EDGAR is identity-gated and slow). Benign for ad-hoc use, problematic if an operator wires retry-on-timeout into a script.
3. **Input validation.** `ticker = body.get('ticker', '').upper().strip()` is the only validation. No length cap, no regex (`^[A-Z0-9.\-]{1,10}$` would be natural). A ticker like `'AAPL' * 1000` gets sent to OpenFIGI verbatim and wastes the rate-limit slot. Parameterized SQL keeps this off the SQLi path, but it's a defense-in-depth gap.

**Fix disposition:** candidate for Phase 1 fix under sec-03. Smallest correct patch is the same `fcntl.flock` pattern sec-02-p1 uses, keyed per ticker (`data/.add_ticker_<ticker>.lock`) — except tickers are short enough and the set small enough that a single global lock `data/.add_ticker.lock` is simpler and acceptable. Plus an input regex at the top. See §6.1.

### §4.5 `/api/admin/run_script` — GUARDED (sec-02-p1)

Full TOCTOU analysis lives in `docs/findings/sec-02-p0-findings.md` §1 and the fix diff is `scripts/admin_bp.py:552-589` at HEAD. Three residual concerns specific to this audit:

1. **Flags pass-through.** `cmd = ['python3', '-u', script_path] + flags` ([admin_bp.py:572](scripts/admin_bp.py:572)) concatenates caller-supplied flags onto the command list. The list form avoids shell metacharacter injection (there is no `shell=True`), but an operator can pass `--database=/tmp/anything` or `--reset` to a script that happens to accept those flags. This is an **argument injection** surface that relies on the scripts' own argument validation, not on the router. Presently only `--staging`, `--update`, `--test` are surfaced in the UI dropdown ([admin.html:361-363](web/templates/admin.html:361)), but the endpoint accepts any list. **Fix disposition:** add a per-script flag allowlist to mirror the script allowlist. Candidate for sec-03 Phase 1 or a later follow-up.
2. **Log truncation.** The single per-script log file at `logs/<script>_run.log` is opened in `'w'` mode on every run ([admin_bp.py:576](scripts/admin_bp.py:576)). The flock ensures only one run at a time, so the legitimate race identified in sec-02-p0 §1.2 is closed, but the log is still wiped on every invocation — operators investigating a crash have only the last run's output. **Fix disposition:** rotate (`_run.log.N`) rather than truncate. Low priority; not P0/P1.
3. **Allowlist drift.** The allowlist at [admin_bp.py:543-548](scripts/admin_bp.py:543) is a hard-coded set. New scripts added to `scripts/` are not auto-registered, which is the correct default. But removed scripts (e.g. `fetch_nport.py` per the BLOCK-1 comment) must be remembered to be de-listed, and there is no test asserting the set matches what the UI offers. **Fix disposition:** cheap unit test — invariant `set(admin.html dropdown) ⊆ admin_bp.py allowed`. Defer to sec-03 Phase 1 if we do one.

### §4.6 `/api/admin/entity_override` — PARTIALLY GUARDED

The prod-target hard block ([admin_bp.py:903-911](scripts/admin_bp.py:903)) is good — returns 403 unless `target=staging`. Inside the staging path:

1. **DuckDB single-writer lock on staging.** `duckdb.connect(staging_path, read_only=False)` ([admin_bp.py:945](scripts/admin_bp.py:945)) raises `IOException` if the staging file is already held elsewhere (a concurrent `/entity_override` call, a `merge_staging.py` run, or a running `unify_positions.py --staging`). The request fails loudly; no data corruption. This is a *working* guard, but it is passive — the caller sees a 500 with a raw DuckDB traceback rather than a helpful 409. **Fix disposition:** catch the `IOException` and return a structured 409 like `/run_script`. Cheap.
2. **No CSV row-count cap.** `_csv.DictReader` streams rows with no upper bound. A 10 MB CSV of overrides holds the staging file lock for potentially minutes. The `iterative BEGIN/COMMIT per row` pattern limits blast radius of a crash mid-run (only the in-progress row is lost), but the lock itself is held for the whole request. **Fix disposition:** a request-scoped row cap (e.g. 10,000) plus optional `max_rows` query param. Sizing matches historical override volumes (47 rows on the largest single push per `project_session_apr11_12_data_qc` memory — so 10k is comfortable).
3. **`override_id` MAX+1 race.** [admin_bp.py:1066-1069](scripts/admin_bp.py:1066) does `SELECT COALESCE(MAX(override_id),0)+1` then `INSERT`. Comment at line 1065 asserts "race-safe under DuckDB single-writer" — this is true *within a single connection's single writer*, because DuckDB's file lock serializes any concurrent RW connection. Two simultaneous `/entity_override` calls would both be racing for the staging file lock (concern 1 above), so by the time one acquires the lock the other has failed; the MAX+1 within a single held connection is safe. Disposition: no fix needed given the file lock dominates.
4. **Input validation.** CSV required-column check ([admin_bp.py:929-937](scripts/admin_bp.py:929)), `int()` coercion per row, `.strip().lower()` on text fields. SQL is fully parameterized. Fine.

**Overall disposition for `/entity_override`:** upgrade the DuckDB IOException handler to return 409, and add a row cap. Both are small. Neither is urgent; defer to a dedicated ticket or bundle into sec-03 Phase 1.

---

## §5. Cross-item awareness

- **sec-01-p1** (session auth) — confirmed all write routes sit behind the router-scope dependency. No route bypasses it. If sec-03 Phase 1 adds any new fixes, they must not introduce a new exempt path.
- **sec-02-p1** (flock on `/run_script`) — already in place. Any sec-03 write-surface guard should reuse the same `data/.run_*.lock` / `data/.add_ticker.lock` naming convention under `data/` for operator familiarity.
- **sec-04** (validators writing to prod, per `docs/REMEDIATION_PLAN.md`) — `/api/admin/run_script` is the invocation surface for the `build_cusip.py` / `build_summaries.py` / `unify_positions.py` scripts that sec-04 targets. This audit does not re-scope sec-04; it confirms the entry point guard is tight. The argument-injection concern in §4.5.1 matters for sec-04 because `--staging` vs prod target selection lives in script flags — sec-04's Phase 0 should treat flag validation as a direct dependency.
- **sec-05/sec-06** (hardcoded-prod builders, direct-to-prod writers, per `docs/REMEDIATION_PLAN.md` Theme 4-C) — `/api/admin/add_ticker` is the only admin route that writes directly to PROD_DB without going through staging. This is a legacy path from the on-demand-ticker feature. Any sec-05 review of "who writes to prod" must include this endpoint — flagged for carry-over.
- **Phase 2 admin refresh** — per the prompt, the Phase 2 frontend refresh is expected to add 9+ new admin endpoints. This audit establishes the **baseline** (18 admin routes, 6 writes) that future net-new endpoints should register against. A living inventory in a checked-in doc (not just this findings file) would prevent drift. Suggest: follow-up ticket "track write surface in `docs/endpoint_classification.md`".
- **obs-03-p1** (`id_allocator.py` flock) — merged. Its lock files live at `data/.manifest_id_seq.lock` etc. Disjoint namespace from `data/.run_*.lock` (sec-02) and any future `data/.add_ticker.lock` (proposed here). No collision risk.
- **DuckDB single-writer invariant** — the current design leans on this for `/entity_override` safety (§4.6.3). Acceptable today; `/entity_override` should not be the template for any Phase 4 prod-write path, because prod will eventually have to accept concurrent writers more gracefully than "one wins, the other sees a raw IOException traceback".

---

## §6. Prioritized remediation recommendations

Ranked by severity × ease-of-fix. Severity scale: **P0** (user-visible failure, external cost, or silent data loss), **P1** (confusing failure mode but no data loss), **P2** (cosmetic / defense-in-depth).

### P0-1 — Guard `/api/admin/add_ticker` against same-ticker races

Same-class problem as sec-02-p1 (`/run_script`). Same fix primitive: `fcntl.flock` on a per-ticker sentinel. ~15 LOC. External-quota burn is the most user-visible impact today; the DuckDB loser-raise is loud but recoverable. See §7.1 for diff sketch.

### P0-2 — Add ticker format regex to `/api/admin/add_ticker`

Two-line change: `if not re.match(r'^[A-Z0-9.\-]{1,10}$', ticker): return 400`. Closes the quota-abuse vector and stops garbage from reaching external APIs. Pairs naturally with P0-1 — bundle into one commit.

### P1-1 — Catch `IOException` in `/api/admin/entity_override` and return 409

Replace `duckdb.connect(staging_path, read_only=False)` with a try/except that returns `JSONResponse(409, {'error': 'staging DB is busy; retry in a moment'})` on lock contention. ~5 LOC. Upgrades an ugly 500 into a caller-actionable 409.

### P1-2 — Per-script flag allowlist for `/api/admin/run_script`

Turns argument-injection from a possible footgun into an impossible one. Scope: a dict `{'fetch_13dg.py': {'--staging','--update','--test'}, ...}` and a check before building `cmd`. ~20 LOC. Not required for any current exploit — defense in depth. Needs coordination with sec-04 which will add `--target=prod`-like flags.

### P2-1 — Row cap on `/api/admin/entity_override` CSV

Request-scoped `MAX_OVERRIDE_ROWS = 10_000` + early 413 response if exceeded. Low priority — current caller practice (hand-authored CSVs) stays well under.

### P2-2 — Log rotation instead of truncation for `/run_script`

Replace `open(log_path, 'w')` with `open(log_path + '.new', 'w')` + rename on completion, or a numbered-rotation scheme. Operator ergonomics only.

### P2-3 — Admin-surface living inventory

Create/maintain `docs/endpoint_classification.md` so future routes (Phase 2 refresh, sec-04 Phase 2) register against it. Not strictly a fix — a process/hygiene step.

### Not-fixes (documented and deferred)

- **Login rate-limit** (§4.1). `ADMIN_TOKEN` is a pre-shared secret; brute-force protection has low marginal value. Revisit if `ADMIN_TOKEN` ever rotates less than weekly.
- **Admin-sessions row growth** (§4.1). Sweep at 1% handles legitimate traffic; add a cap only if `/stats` ever reports anomalous counts.

---

## §7. Phase 1 scope recommendation

The P0-1 + P0-2 fix to `/api/admin/add_ticker` is the right target for sec-03-p1. Small enough for one PR, fully isolated from the Phase 2 refresh, and closes the last known-unguarded write surface on `admin_router`. P1-1 (the `/entity_override` 409 upgrade) is cheap enough to bundle into the same PR without ballooning scope — both changes touch `scripts/admin_bp.py` only, both are <50 LOC net.

**Recommended Phase 1 scope for sec-03-p1:**
- P0-1 + P0-2 on `/add_ticker` (guard + validation).
- P1-1 on `/entity_override` (IOException → 409).

**Defer to sec-03-p2 or separate tickets:**
- P1-2 (flag allowlist) — needs sec-04 coordination.
- P2-1, P2-2, P2-3 — ergonomics/hygiene, not hazards.

### §7.1 Diff sketch for P0-1 + P0-2 (illustrative, not Phase 1 code)

```python
TICKER_RE = re.compile(r'^[A-Z0-9.\-]{1,10}$')

@admin_router.post('/add_ticker')
def api_add_ticker(body: dict = Body(default={})):
    ticker = (body.get('ticker') or '').upper().strip()
    if not TICKER_RE.match(ticker):
        return JSONResponse(status_code=400,
                            content={'error': 'invalid ticker format'})

    lock_path = os.path.join(BASE_DIR, 'data', '.add_ticker.lock')
    lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(lock_fd)
        return JSONResponse(status_code=409,
                            content={'error': 'another add_ticker is in flight'})
    try:
        ...  # existing body unchanged
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)
```

Notes:
- No `pass_fds` needed — `/add_ticker` runs the external calls and DB write in the **parent** process, so the parent holds the lock for the full duration.
- Single global lock (`data/.add_ticker.lock`, not per-ticker) because the bottleneck is external quota + DB lock, both of which are global. Simpler than per-ticker locks, still serializes the hazard.
- If future work wants parallel same-ticker de-dup without serializing distinct tickers, switch to per-ticker and validate the lock-file name against `TICKER_RE` to prevent path traversal.

### §7.2 Diff sketch for P1-1 (illustrative, not Phase 1 code)

```python
try:
    con = duckdb.connect(staging_path, read_only=False)
except duckdb.IOException as e:
    return JSONResponse(status_code=409,
                        content={'error': 'staging DB is busy; retry shortly',
                                 'detail': str(e)})
```

### §7.3 Test plan (Phase 1)

- Unit: pytest + FastAPI `TestClient` — two concurrent `/add_ticker` for the same ticker; assert exactly one `200`, one `409`.
- Unit: `/add_ticker` with `ticker='../../etc/passwd'` → `400`.
- Unit: `/add_ticker` with `ticker='AAAAAAAAAAA'` (11 chars) → `400`.
- Integration (manual): hold the staging DB open in a separate process; `POST /entity_override` should return `409` with structured JSON, not a 500 stacktrace.

### §7.4 Rollback

Single commit revert. `data/.add_ticker.lock` is an empty sentinel; deleting it has no data-loss impact.

---

## §8. Open questions

1. **Should `/add_ticker` move to a background-job queue rather than synchronous?** External calls to OpenFIGI + Yahoo + SEC + EDGAR are slow (~5–15 s). Keeping the request synchronous is fine for occasional operator use; under higher volume a background job would be more humane. Out of scope for sec-03; flag if Phase 2 refresh changes the invocation pattern.
2. **Should `/entity_override` eventually accept prod target after sec-04 completes?** Current hard block is correct today. sec-04's Phase 4 gate determines this; sec-03 should not unlock prod writes.
3. **Do we want a structured audit log for every admin write?** `/entity_override` writes `logs/entity_overrides.log`; `/add_ticker` does not. `/run_script` writes `logs/<script>_run.log` but that's script output, not an admin-action audit. Cross-item with obs-*.

---

## §9. Change log

- 2026-04-21: initial write-up. Branch `remediation/sec-03-p0` off main `c8cee2f`. No code or DB writes.
