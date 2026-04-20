# sec-01-p0 — Phase 0 findings: admin token `localStorage` → server-side session

_Prepared: 2026-04-20 — branch `remediation/sec-01-p0` off main HEAD `46c2a25`._

_Tracker: `docs/REMEDIATION_PLAN.md` Theme 4 row `sec-01`; `docs/REMEDIATION_CHECKLIST.md` Batch 4-A. Audit refs: `docs/SYSTEM_AUDIT_2026_04_17.md` §11.1 D-11; `docs/SYSTEM_PASS2_2026_04_17.md` §7.4; `docs/CODEX_REVIEW_2026_04_17.md` §§3f/7.4._

Phase 0 is investigation only. No code writes and no DB writes were performed. Deliverables: this document + Phase 1 plan + open questions.

---

## §1. Current authentication flow (traced)

### §1.1 Server-side token source

`ADMIN_TOKEN` is an environment variable. It is read on every request by a FastAPI dependency — there is no in-process cache, no rotation hook, and no server-side token state:

- [scripts/admin_bp.py:56-67](scripts/admin_bp.py:56) — `require_admin_token(x_admin_token: str = Header(None, alias='X-Admin-Token'))`:
  - If `ENABLE_ADMIN != '1'` OR `ADMIN_TOKEN` unset → `503 {'error': 'Admin disabled'}`.
  - Timing-safe comparison via `hmac.compare_digest(provided, expected)` — good.
  - Returns `403 {'error': 'Forbidden'}` on mismatch.

- [scripts/admin_bp.py:70-74](scripts/admin_bp.py:70) — the dependency is wired at router scope: `admin_router = APIRouter(prefix='/api/admin', dependencies=[Depends(require_admin_token)])`. Every route under `/api/admin/*` inherits it.

- [scripts/app.py:73-77](scripts/app.py:73) — `app.include_router(admin_router)` is called first, before the non-admin routers, so no downstream router can accidentally shadow the path.

### §1.2 Client-side token acquisition & attachment

There is a single client surface. The React SPA does not touch the admin endpoints.

- [web/templates/admin.html:180-205](web/templates/admin.html:180):
  - `getAdminToken()` — reads `localStorage.getItem('admin_token')`. If unset, prompts the operator via `window.prompt()` and persists the result in `localStorage`.
  - `adminFetch(url, opts)` — wraps `fetch()`, forcibly injects `X-Admin-Token: <token>` header.
  - On `403`: `localStorage.removeItem('admin_token')`, throws "refresh to re-enter".
  - On `503`: throws "Admin disabled" message, but does **not** clear the token (so a disabled→re-enabled cycle reuses the old token silently).

- [scripts/app.py:90-92](scripts/app.py:90) — `/admin` serves `admin.html` through Jinja. The page is opt-in and never linked from the React app; only operators who know the URL hit it.

- Static HTML inspection: `admin.html` has **zero** Jinja `{{ … }}` or `{% … %}` interpolation (`grep -n "{{|{%" web/templates/admin.html` returns no hits). The template is effectively static HTML and the only context dict passed is `{'request': request}` ([scripts/app.py:92](scripts/app.py:92)). Rendering this page does not re-introduce user content into HTML.

### §1.3 Rate limiting, CSRF middleware, cookie middleware

None present.

- `grep -n "SessionMiddleware|CSRFMiddleware|CORSMiddleware|add_middleware"` across `scripts/*.py` returns **no hits**.
- `grep -n "rate_limit|RateLimit|slowapi"` across `scripts/` returns nothing server-side (the only `session` matches in Python sources are `requests.Session()` HTTP clients for edgartools/yfinance/etc., unrelated to web sessions).
- `requirements.txt` — no `itsdangerous`, no `python-jose`, no `slowapi`. Starlette `SessionMiddleware` cannot be enabled without adding `itsdangerous`.

### §1.4 Existing session infrastructure

None. `grep -rn "admin_sessions|user_sessions|session_id"` returns only hits in `docs/prompts/sec-01-p0.md` itself. The migration directory contains nothing session-shaped:

- `scripts/migrations/001_pipeline_control_plane.py` ... `008_rename_pct_of_float_to_pct_of_so.py`
- `scripts/migrations/add_last_refreshed_at.py`

Phase 1 will add `009_admin_sessions.py` (see §6.2).

---

## §2. XSS exposure analysis

**Goal of the storage-site question.** If any same-origin page can inject JS, that JS reads `localStorage.getItem('admin_token')` and the token is compromised. "Same-origin" here means the entire app (FastAPI) — cookies and `localStorage` are origin-scoped, not path-scoped for JS reads.

### §2.1 Pages served from the app origin

Two non-API responses:

1. [scripts/app.py:83-87](scripts/app.py:83) — `/` → `FileResponse(…/web/react-app/dist/index.html)`. Static file. The React runtime executes under this origin.
2. [scripts/app.py:90-92](scripts/app.py:90) — `/admin` → `templates.TemplateResponse('admin.html', {'request': request})`. Static-equivalent (no interpolation).

Both pages run under the same origin as `/api/admin/*`, so both have `localStorage` read access to the token.

### §2.2 XSS sources to audit

The template path is clean. The React bundle is not in scope for this investigation (sec-03 is the write-surface audit; a dedicated XSS pass for the SPA is not yet scheduled). The threat remains:

- **React bundle** uses same-origin `fetch` and reads from `/api/*` JSON endpoints. Any `dangerouslySetInnerHTML` or unescaped rendering of backend strings would be an XSS sink that reads the admin token.
- **Third-party CDN / script tags** in `index.html` (not inspected here) could also read `localStorage`.

**Upshot for Phase 1:** we must assume at least one XSS path exists or will exist, and harden accordingly. HttpOnly cookies remove the token from JS reach even if an XSS is found later.

### §2.3 Operational XSS-equivalents already visible

- **Browser extensions** read `localStorage` of any visited page; the admin operator's browser is a large trust surface.
- **Shared machines**: token persists across sessions until an explicit 403. A laptop left open leaks the token to anyone with the URL.
- **Browser devtools screenshots**: incident reports that include a screenshot of DevTools → Application → Local Storage leak the token into Jira/Slack.

Moving to HttpOnly cookies with an 8-hour absolute timeout addresses all three vectors as a side effect.

---

## §3. Browser storage inventory

Inventory of every place the admin token touches the browser:

| Store | Key | Set at | Read at | Cleared at | Notes |
|---|---|---|---|---|---|
| `localStorage` | `admin_token` | admin.html:188 | admin.html:185, 194 | admin.html:198 (on 403) | Persists across browser restart. JS-readable. |
| `sessionStorage` | — | — | — | — | Not used. |
| `document.cookie` | — | — | — | — | Not used. |
| `IndexedDB` | — | — | — | — | Not used. |
| HTTP `X-Admin-Token` header | `X-Admin-Token: <token>` | admin.html:194 (`adminFetch`) | admin_bp.py:56-67 | — | Per-request; never persisted. |

No other code in the repo references `localStorage`, `sessionStorage`, or `document.cookie`:

- `grep -rn "localStorage|sessionStorage|document\.cookie"` across the worktree returns:
  - `docs/**` — documentation mentions only.
  - `web/templates/admin.html` — the four lines above.

This one-file surface makes the migration mechanically simple: drop `getAdminToken()`, rewrite `adminFetch()` to rely on the session cookie (`credentials: 'same-origin'` is implicit for same-origin), add a login modal.

---

## §4. Threat model (post-migration)

### §4.1 XSS

**Pre-migration.** Any same-origin XSS reads the token and can call `/api/admin/*` for the session lifetime (indefinite, bounded only by `ADMIN_TOKEN` env rotation).

**Post-migration (HttpOnly cookie).** JS cannot read the cookie. XSS can still call `/api/admin/*` via same-origin `fetch()` because the browser attaches the cookie automatically — but:
- Damage is bounded to the current session (max 8h absolute, 30m idle — see §6.1).
- The server can revoke all sessions instantly via `/api/admin/logout_all`.
- The token itself is not exfiltrated to an attacker, so the attacker's capability is tied to the ongoing XSS payload, not a permanent credential.

Net: XSS is not *eliminated* (Phase 2+ would need CSP + SPA audit), but the blast radius is reduced from "permanent credential theft" to "in-session abuse".

### §4.2 CSRF

**Pre-migration.** The `X-Admin-Token` header is an *explicit* header, which browsers do not attach on cross-origin requests, so the API is incidentally CSRF-safe. Header-based auth is CSRF-immune because simple-request cross-origin form POSTs cannot set `X-Admin-Token`.

**Post-migration (cookie).** Cookies are attached automatically on cross-origin requests unless constrained. Two controls:

1. `SameSite=Strict` — browser will not send the cookie on any cross-site request. This is sufficient for a single-origin admin dashboard. Strict (not Lax) because Lax still sends on top-level GET navigations, and several admin endpoints (including `/api/admin/add_ticker`, `/api/admin/run_script`, `/api/admin/entity_override`) are side-effectful on methods that Lax permits (notably GETs to `/api/admin/running`, etc.). Strict closes the door entirely.
2. **Double-submit token** — deferred. Not needed under `SameSite=Strict` for a single-origin surface. Revisit if we ever add a CORS allowance (e.g. moving admin to a separate subdomain).

### §4.3 Session fixation

Pre-issuance fixation is not possible because there is no anonymous session cookie; the cookie is only issued post-login. We do not need to "rotate session ID on privilege escalation" because there is no privilege escalation path — the only way to get a session row is to present the env `ADMIN_TOKEN` via login.

### §4.4 Token leakage in logs / referer

Cookies are not logged by default in uvicorn access logs (it logs method/path/status), but custom middleware could. Phase 1 plan (§6.3) explicitly forbids logging the `Cookie` header. The old `X-Admin-Token` header path is also removed end-to-end, so log-scrapers cannot fall back to a header grep to find tokens.

### §4.5 Replay / theft of a session_id

A stolen `session_id` is usable until it is revoked or expires. Mitigations:

- Short idle timeout (30 min).
- Short absolute timeout (8 h).
- Admin revoke-all endpoint.
- `last_used_at` + `ip` + `user_agent` columns in `admin_sessions` — we can alarm on UA changes mid-session, but we do **not** hard-pin IP (NAT + mobile tethering produce false positives). Pinning is a Phase 2 option if abuse is observed.

---

## §5. Constraint space for the design

Decisions below were made against these constraints:

| Constraint | Implication |
|---|---|
| DuckDB is the only persistent store the app speaks. No Redis/Memcached. | Session state lives in DuckDB, not a sidecar. |
| DuckDB has single-writer semantics. | Session INSERT/UPDATE on every admin request competes with pipeline writers. This is already true for `admin_bp.py` endpoints like `/entity_override` — so no new contention class. Expected admin traffic is ≤ a few requests/sec; single-writer is fine. |
| `ADMIN_TOKEN` env still the root of trust. | Login endpoint verifies the env token with `hmac.compare_digest` (preserving the existing timing-safe check). Session_id derives from the post-login state. |
| No existing middleware stack. | Prefer an explicit `Depends(require_admin_session)` dependency over Starlette `SessionMiddleware` — less surface, no new dep (`itsdangerous`). |
| Single operator, single browser is the realistic shape. | Multi-device concurrent sessions are allowed (row per device) but not required. |
| The app is served over localhost in dev and over TLS (or plain-text LAN) in prod. | `Secure` flag conditional: `Secure` if `request.url.scheme == 'https'`, else omit. Document this. |
| There is no CSRF middleware today. | `SameSite=Strict` is the only CSRF lever initially. |
| The admin page has one operator; session fixation / SSO are out of scope. | Keep design minimal. |

---

## §6. Design: server-side session table + cookie

### §6.1 DDL

```sql
CREATE TABLE IF NOT EXISTS admin_sessions (
    session_id     VARCHAR PRIMARY KEY,          -- UUID4 string, generated server-side (uuid.uuid4())
    issued_at      TIMESTAMP NOT NULL,
    expires_at     TIMESTAMP NOT NULL,           -- issued_at + 8h (absolute cap)
    last_used_at   TIMESTAMP NOT NULL,           -- updated on every authenticated call
    ip             VARCHAR,                      -- X-Forwarded-For first hop, else request.client.host
    user_agent     VARCHAR,                      -- truncated to 512 chars
    revoked_at     TIMESTAMP                     -- NULL while active; set on logout / logout-all
);
CREATE INDEX IF NOT EXISTS idx_admin_sessions_expires ON admin_sessions(expires_at);
```

Design rationale per column:

- **`session_id VARCHAR PRIMARY KEY`** — UUID4 stringified. Python `uuid.uuid4()` gives ~122 bits of entropy; storing as string avoids DuckDB `UUID` type drift across staging/prod (see `docs/BLOCK_SCHEMA_DIFF_FINDINGS.md`). Not sequential, not guessable.
- **`issued_at` + `expires_at`**. Absolute cap of 8h to limit damage from a stolen cookie. Separate from `last_used_at` so idle-timeout and absolute-timeout are both enforceable.
- **`last_used_at`** — updated on every authenticated request; 30-minute idle timeout means rows with `now - last_used_at > 30 min` are rejected even if `expires_at` is in the future.
- **`ip`, `user_agent`** — recorded for audit, **not** pinned. Mobile networks and NAT change IPs legitimately; strict pinning causes churn.
- **`revoked_at`** — explicit revocation marker. A row with `revoked_at IS NOT NULL` is rejected by the dep. Logout sets this; a sweep job can `DELETE FROM admin_sessions WHERE revoked_at IS NOT NULL OR expires_at < now()`.
- **Index on `expires_at`** — used by the sweep query; the PK covers the per-request lookup.

### §6.2 Migration script shape

`scripts/migrations/009_admin_sessions.py`, structured like `008_rename_pct_of_float_to_pct_of_so.py`:

- Idempotent `CREATE TABLE IF NOT EXISTS`.
- `CREATE INDEX IF NOT EXISTS` for `expires_at`.
- No seeding.
- Forward-only (no `down()`); if rollback is ever needed, the table can be dropped manually — it is pure session state and safe to recreate.
- Applied to **both** `13f.duckdb` (prod) and `13f_staging.duckdb` (staging) for parity per `docs/BLOCK_SCHEMA_DIFF_FINDINGS.md` conventions.

### §6.3 Cookie attributes

Cookie name: `admin_session`. Attributes:

| Attribute | Value | Justification |
|---|---|---|
| `HttpOnly` | yes | Blocks `document.cookie` read from JS — the core XSS defense. |
| `Secure` | conditional on `request.url.scheme == 'https'` | Dev runs over HTTP (localhost); prod should be behind TLS. Document in release notes that `Secure` only engages under TLS. |
| `SameSite` | `Strict` | CSRF defense; see §4.2. |
| `Path` | `/api/admin` | Reduces attack surface — the cookie is not attached to non-admin API calls. (`/admin` serves the HTML page; login/logout live under `/api/admin/*`, so `Path=/api/admin` covers both the auth endpoints and every protected endpoint.) |
| `Max-Age` | 8h absolute | Matches `expires_at`; browser drops the cookie on absolute timeout without needing a server round-trip. |
| `Domain` | not set | Host-only cookie — safest default. |

### §6.4 Endpoint additions

- **`POST /api/admin/login`** — body: `{"token": "<ADMIN_TOKEN>"}`. Behavior:
  1. Preflight: same `ENABLE_ADMIN` / `ADMIN_TOKEN` env check currently in `require_admin_token` — returns `503` if not configured.
  2. `hmac.compare_digest(body.token, os.environ['ADMIN_TOKEN'])` — **retained** as the single timing-safe compare in the codebase.
  3. On match: `INSERT INTO admin_sessions (…)`, set cookie, return `200 {"status": "ok"}`.
  4. On mismatch: `403`. Do not leak which of "disabled" / "wrong token" is the reason beyond the existing 503/403 split.
  5. Rate-limit consideration: a brute-forcer can POST without a prior session, so add a per-IP sliding window in Phase 1 (e.g. 5 failed attempts → 60s cooloff). Tracked as an open sub-item under §9; if we defer, document the risk.

- **`POST /api/admin/logout`** — reads cookie, sets `revoked_at = now()`, clears the cookie via `Set-Cookie: admin_session=; Max-Age=0`. Idempotent.

- **`POST /api/admin/logout_all`** — `UPDATE admin_sessions SET revoked_at = now() WHERE revoked_at IS NULL`. Operator-initiated mass revocation (equivalent in intent to rotating `ADMIN_TOKEN` today, but much faster).

- **Dependency rename.** `require_admin_token` is replaced by `require_admin_session`:
  - Reads `admin_session` cookie.
  - `503` if `ENABLE_ADMIN != '1'` or `ADMIN_TOKEN` unset (unchanged).
  - `SELECT … FROM admin_sessions WHERE session_id = ? AND revoked_at IS NULL`.
  - Rejects on: row missing, `expires_at < now()`, `now() - last_used_at > 30 min`.
  - On success: `UPDATE admin_sessions SET last_used_at = now() WHERE session_id = ?`.
  - The router-level `dependencies=[Depends(require_admin_session)]` wire at [scripts/admin_bp.py:70-74](scripts/admin_bp.py:70) stays — only the dep function changes.
  - **Important:** `/api/admin/login` must **not** inherit this dep (chicken-and-egg). Move it off the router dep, or declare it under a secondary router without the dep.

### §6.5 Client changes (`admin.html`)

Diff outline:

```diff
- function getAdminToken() {
-     let t = localStorage.getItem('admin_token');
-     if (!t) {
-         t = prompt('Admin token (X-Admin-Token) — …');
-         if (t) localStorage.setItem('admin_token', t);
-     }
-     return t || '';
- }
- async function adminFetch(url, opts = {}) {
-     const headers = Object.assign({}, opts.headers || {}, {
-         'X-Admin-Token': getAdminToken(),
-     });
-     const res = await fetch(url, Object.assign({}, opts, { headers }));
-     if (res.status === 403) {
-         localStorage.removeItem('admin_token');
-         throw new Error('Admin token rejected (403) — refresh to re-enter');
-     }
-     …
+ async function adminLogin() {
+     const t = prompt('Admin token — enter ADMIN_TOKEN env value:');
+     if (!t) return false;
+     const res = await fetch('/api/admin/login', {
+         method: 'POST',
+         headers: {'Content-Type': 'application/json'},
+         credentials: 'same-origin',
+         body: JSON.stringify({token: t}),
+     });
+     return res.ok;
+ }
+ async function adminFetch(url, opts = {}) {
+     const res = await fetch(url, Object.assign({credentials: 'same-origin'}, opts));
+     if (res.status === 401 || res.status === 403) {
+         if (await adminLogin()) return fetch(url, Object.assign({credentials: 'same-origin'}, opts));
+         throw new Error('Admin auth failed — refresh to retry');
+     }
+     if (res.status === 503) throw new Error('Admin disabled on server (503)');
+     return res;
+ }
```

Notes:
- `credentials: 'same-origin'` is the default for `fetch` under same-origin requests, but making it explicit is cheap insurance against future origin changes.
- The `prompt()` UX survives. A fuller login modal is deferred.
- `localStorage.removeItem('admin_token')` disappears — one-time cleanup of any lingering pre-migration entries is optional; document in release notes ("run `localStorage.removeItem('admin_token')` in DevTools once post-deploy" is enough, given single-operator ops).

### §6.6 Rotation / revocation summary

| Action | Mechanism | Surface |
|---|---|---|
| Single-session logout | `POST /api/admin/logout` | Button added to `admin.html` (Phase 1 scope). |
| All-sessions revoke | `POST /api/admin/logout_all` | CLI: `curl` with a valid cookie, or operator UI button. |
| Token rotation | `ADMIN_TOKEN` env change → restart | Existing sessions remain valid until `expires_at`; rotate env *and* call `logout_all` to cut fully. |
| Expired sweep | `DELETE FROM admin_sessions WHERE expires_at < now() OR revoked_at < now() - INTERVAL 7 DAY` | Phase 1: opportunistic sweep inside `require_admin_session` on a 1-in-100 basis. Phase 2: move to cron. |

---

## §7. Cross-item awareness

- **sec-02 (TOCTOU in `/api/admin/run_script`)** — adjacent. Both touch `scripts/admin_bp.py`. `docs/REMEDIATION_PLAN.md:169` declares `sec-01 ∥ sec-02` **serial**. Plan to complete sec-01 Phase 1 and merge before sec-02 Phase 0, or share a Phase 1 branch that lands both together if scheduling makes that cleaner.
- **sec-03 (write-surface audit)** — consumes this output. Once the session table exists, sec-03 inventories every `/api/admin/*` route under the new dep and tags write vs. read surfaces. No conflict.
- **obs-03 / int-01** — unrelated; different themes.

---

## §8. Phase 1 implementation plan

Scope is constrained to this item — no drift into sec-02 or sec-03.

**Files to touch in Phase 1:**
- `scripts/migrations/009_admin_sessions.py` (new).
- `scripts/admin_bp.py` — add `_session_issue`, `_session_revoke`, rename `require_admin_token → require_admin_session`, re-wire router dep, add `/login` `/logout` `/logout_all` endpoints, drop the env-header compare path.
- `web/templates/admin.html:180-205` — diff per §6.5.
- `requirements.txt` — no changes expected.
- `docs/pipeline_violations.md` — no changes (this is not a pipeline write).
- `docs/REMEDIATION_CHECKLIST.md` — flip `sec-01` row once Phase 3 lands.
- `ROADMAP.md` — log completion post-merge.

**Files out of scope for Phase 1:** React SPA, auth middleware for non-admin routes, CSP headers, CORS changes.

**Sequence:**
1. Migration lands on staging; verify DDL applied idempotently.
2. `require_admin_session` implemented + unit-tested server-side; router dep swapped atomically.
3. `/login` / `/logout` / `/logout_all` endpoints added.
4. `admin.html` ported to cookie flow.
5. Manual acceptance (§9).
6. Migration applied to prod via standard `scripts/migrations/` path.
7. Deploy with env `ENABLE_ADMIN=1` and existing `ADMIN_TOKEN` still in place.

**Rollback:** revert commit. The `admin_sessions` table can stay in place (unused); re-revert restores the session flow without a re-migration. No data loss.

---

## §9. Test plan

**Server-side (pytest or manual `curl`):**

1. `ENABLE_ADMIN` unset → `POST /api/admin/login` → `503`.
2. `ENABLE_ADMIN=1`, `ADMIN_TOKEN=abc`, `POST /api/admin/login {"token":"wrong"}` → `403`; no row in `admin_sessions`.
3. Correct token → `200`; `Set-Cookie: admin_session=<uuid>; HttpOnly; SameSite=Strict; Max-Age=28800; Path=/api/admin`.
4. Protected endpoint without cookie → `401` or `403`.
5. Protected endpoint with valid cookie → `200`; `last_used_at` updated.
6. Idle past 30m → protected endpoint `401`.
7. Absolute expiry past 8h → protected endpoint `401` even if idle clock is fresh.
8. `POST /api/admin/logout` → subsequent request with same cookie → `401`; `revoked_at` set.
9. `POST /api/admin/logout_all` while two sessions exist → both revoked.
10. SQL injection attempt in session_id lookup (parameterized → 0 rows; no 500).
11. Timing of wrong-token path — `hmac.compare_digest` still in use; confirm via code review.

**Browser (manual, single dashboard):**

1. Fresh browser: load `/admin` → login prompt → enter token → dashboard loads.
2. Hard refresh the page → still authenticated (cookie survives refresh).
3. Close and re-open the browser → still authenticated within 8h (cookie persists — note this is a deliberate change from "until localStorage cleared").
4. Logout button → reload → prompts for token again.
5. Open DevTools → Application → Local Storage: `admin_token` absent (post-cleanup).
6. Open DevTools → Application → Cookies: `admin_session` present, HttpOnly=✓, Secure=✓ if TLS, SameSite=Strict.
7. Try reading the cookie from the JS console: `document.cookie` — should not list `admin_session` (HttpOnly).

**CSRF probe (manual):**

1. From a different origin (e.g. `python3 -m http.server` on another port), attempt `fetch('/api/admin/stats', {credentials: 'include'})` → browser does **not** send `admin_session` (SameSite=Strict) → server returns `401`.

---

## §10. Open questions / deferrals

These are judgment calls where a one-line user decision unblocks Phase 1:

1. **Idle vs. absolute timeout values.** Proposed: 30 min idle / 8 h absolute. Confirm or adjust.
2. **Login brute-force rate limiting.** Proposed: in-process sliding window (5 failed attempts per IP per 60s). Confirm in-scope for Phase 1, or defer to sec-02/sec-03 with the other hardening items.
3. **Multi-session policy.** Proposed: allow concurrent rows per operator (useful: phone + laptop). Alternative: single active row, new login revokes the prior. Confirm.
4. **Cookie `Path`**. Proposed: `/api/admin`. Alternative: `/` (simpler, but wider surface). Confirm.
5. **Old `X-Admin-Token` header break-glass.** Proposed: remove entirely. Alternative: keep the header path guarded by `ALLOW_HEADER_AUTH=1` env for CI/scripts. Confirm — I lean toward removal because the whole point is to eliminate long-lived bearer tokens.
6. **`admin_sessions` table on both staging and prod DBs?** Proposed: yes, for parity per BLOCK_SCHEMA_DIFF conventions. Even though staging won't originate admin sessions, schema parity avoids INF39-class drift.

---

## §11. Summary

- One storage site for the token (`localStorage` in `admin.html:180-205`). One server-side compare site (`admin_bp.py:56-67`). No React or other surfaces to untangle.
- No existing session/middleware/CSRF infrastructure; Phase 1 builds minimally on FastAPI dependencies + DuckDB + a single new migration.
- Threat model: HttpOnly + SameSite=Strict + 8h absolute cap + revocation endpoint closes the observed gap; residual XSS risk shrinks from "permanent credential theft" to "in-session abuse".
- No scope creep into sec-02 (TOCTOU), sec-03 (write-surface audit), or SPA XSS hardening.
- Phase 1 touches 3 files (migration + admin_bp.py + admin.html) plus doc updates; breaking UX change is documented (operator re-logs in post-deploy).
