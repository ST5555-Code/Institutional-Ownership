# sec-01-p1 — Phase 1 implementation: admin token localStorage → server-side session

## Context

Foundation work under the remediation program (`docs/REMEDIATION_PLAN.md` Theme 4; `docs/REMEDIATION_CHECKLIST.md` Batch 4-A). Audit item MAJOR-11 (D-11, Pass 2 §7.4): admin token persisted in browser `localStorage` — XSS-readable, no expiry, no server-side revocation.

Phase 0 investigation complete (`docs/findings/sec-01-p0-findings.md`, PR #5). This Phase 1 prompt implements the migration designed in that findings doc.

## Design decisions (confirmed by user 2026-04-20)

| # | Decision |
|---|---|
| 1 | Idle timeout: 30 min. Absolute timeout: 8 h. |
| 2 | Login brute-force rate limiting: **deferred** to sec-02/sec-03. |
| 3 | Multi-session policy: allow concurrent sessions (phone + laptop). |
| 4 | Cookie `Path`: `/api/admin`. |
| 5 | Old `X-Admin-Token` header auth: **remove entirely**. No break-glass env flag. |
| 6 | `admin_sessions` table created on both staging and prod DBs for schema parity. |

## Branch

`remediation/sec-01-p1` off main HEAD (after PR #5 and PR #6 are merged).

## Files this session will touch

Write:
- `scripts/migrations/009_admin_sessions.py` (new) — DDL per findings §6.1 + §6.2
- `scripts/admin_bp.py` — replace `require_admin_token` with `require_admin_session`; add `/login`, `/logout`, `/logout_all` endpoints; remove header-auth path
- `web/templates/admin.html` — drop `localStorage` token flow; switch to cookie-based `adminFetch` per findings §6.5

Read (verification only):
- `docs/findings/sec-01-p0-findings.md` — the design spec
- `scripts/app.py` — confirm router wiring unchanged
- `data/13f.duckdb`, `data/13f_staging.duckdb` — apply migration, verify DDL

**If the worker touches any file not in this list, it must stop and escalate rather than proceed.** This list matches Appendix D of `docs/REMEDIATION_PLAN.md`.

## Scope

### 1. Migration 009 — `admin_sessions` table

Create `scripts/migrations/009_admin_sessions.py`, structured like `008_rename_pct_of_float_to_pct_of_so.py`:

```sql
CREATE TABLE IF NOT EXISTS admin_sessions (
    session_id     VARCHAR PRIMARY KEY,
    issued_at      TIMESTAMP NOT NULL,
    expires_at     TIMESTAMP NOT NULL,
    last_used_at   TIMESTAMP NOT NULL,
    ip             VARCHAR,
    user_agent     VARCHAR,
    revoked_at     TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_admin_sessions_expires ON admin_sessions(expires_at);
```

- Idempotent (`IF NOT EXISTS`).
- Forward-only (no `down()`).
- Apply to both `13f.duckdb` and `13f_staging.duckdb`.
- Verify applied: `SELECT column_name FROM information_schema.columns WHERE table_name='admin_sessions'` returns 7 columns.

### 2. `admin_bp.py` — session dependency swap

**Remove:**
- `require_admin_token()` function and its `X-Admin-Token` header parameter.

**Add:**
- `import uuid, datetime` (if not already present).
- Constants: `SESSION_IDLE_TIMEOUT = 1800` (30 min), `SESSION_ABSOLUTE_TIMEOUT = 28800` (8 h).
- `require_admin_session(request: Request)` dependency:
  - `503` if `ENABLE_ADMIN != '1'` or `ADMIN_TOKEN` unset (unchanged gate).
  - Read `admin_session` cookie from `request.cookies.get('admin_session')`.
  - If missing → `401`.
  - Query: `SELECT * FROM admin_sessions WHERE session_id = ? AND revoked_at IS NULL` (parameterized, not f-string).
  - Reject if: row missing, `expires_at < now()`, `now() - last_used_at > 30 min`.
  - On success: `UPDATE admin_sessions SET last_used_at = now() WHERE session_id = ?`.
  - Opportunistic sweep (1-in-100 random): `DELETE FROM admin_sessions WHERE expires_at < now() OR (revoked_at IS NOT NULL AND revoked_at < now() - INTERVAL 7 DAY)`.
- Router dep: `admin_router = APIRouter(prefix='/api/admin', dependencies=[Depends(require_admin_session)])`.

**New endpoints (exempt from router-level dep — use a separate router or explicit override):**

- `POST /api/admin/login`:
  - Body: `{"token": "<string>"}`.
  - `503` if admin disabled / token unset.
  - `hmac.compare_digest(body.token, os.environ['ADMIN_TOKEN'])` — preserve timing-safe compare.
  - On match: generate `uuid.uuid4()`, INSERT row, set cookie:
    ```
    admin_session=<uuid>; HttpOnly; SameSite=Strict; Max-Age=28800; Path=/api/admin
    ```
    Add `Secure` flag if `request.url.scheme == 'https'`.
  - On mismatch: `403`.
  - **This endpoint must NOT inherit the `require_admin_session` dep** (chicken-and-egg). Implement via a separate `login_router = APIRouter(prefix='/api/admin')` without the session dep, or use `@app.post` directly on the main app. Either way, the login endpoint must still check `ENABLE_ADMIN` / `ADMIN_TOKEN` env presence.

- `POST /api/admin/logout`:
  - Read cookie, `UPDATE admin_sessions SET revoked_at = now() WHERE session_id = ?`.
  - Clear cookie: `Set-Cookie: admin_session=; Max-Age=0; Path=/api/admin; HttpOnly; SameSite=Strict`.
  - `200` always (idempotent).
  - This endpoint lives on the dep-protected router (requires valid session to logout).

- `POST /api/admin/logout_all`:
  - `UPDATE admin_sessions SET revoked_at = now() WHERE revoked_at IS NULL`.
  - Clear the calling session's cookie.
  - `200` with count of revoked rows.
  - This endpoint lives on the dep-protected router.

**Important implementation notes:**
- All DuckDB queries for session ops must use parameterized queries (`con.execute("... WHERE session_id = ?", [sid])`), never f-strings.
- Do NOT log the `Cookie` header or session_id values in any access log or error handler.
- The `B608 nosec` annotation rule applies: if using `con.execute(f"""...""")` anywhere (which you should NOT for session queries), the `# nosec B608` goes on the closing `""")` line, not the opening line.

### 3. `admin.html` — cookie-based auth

Per findings §6.5 diff outline:

- **Remove:** `getAdminToken()` function, `localStorage.getItem/setItem/removeItem('admin_token')` calls, `X-Admin-Token` header injection in `adminFetch()`.
- **Add:** `adminLogin()` function that `POST`s to `/api/admin/login` with `credentials: 'same-origin'`.
- **Rewrite:** `adminFetch(url, opts)` to:
  - Use `credentials: 'same-origin'` (explicit).
  - On `401` or `403`: call `adminLogin()`, retry once on success.
  - On `503`: throw admin-disabled error.
- **Add:** logout button in the UI header that `POST`s to `/api/admin/logout`.
- **On page load:** attempt a lightweight authenticated request (e.g. `GET /api/admin/stats`). If `401`, trigger `adminLogin()`. This replaces the old "prompt on first load" behavior.

### 4. Verification

Run the full test plan from findings §9 (11 server-side tests + 7 browser tests + 1 CSRF probe). Document results in the PR description.

Key checks:
- `pytest` or manual `curl` covering all 11 server-side cases.
- Browser manual walkthrough: login → refresh → close/reopen → logout → re-login → DevTools cookie inspection.
- Confirm `document.cookie` does not expose `admin_session` (HttpOnly).
- Confirm `localStorage` has no `admin_token` key post-migration.
- Pre-commit (ruff + pylint + bandit) clean on all modified files.
- Smoke tests pass (`make smoke` or equivalent).

## Out of scope

- Login brute-force rate limiting (deferred to sec-02/sec-03).
- CSRF double-submit token (SameSite=Strict sufficient for single-origin).
- React SPA changes (no admin auth in React).
- CSP headers.
- sec-02 TOCTOU fix (serial after this merges).
- sec-03 write-surface audit (consumes this output).
- Doc updates to REMEDIATION_CHECKLIST / ROADMAP / SESSION_LOG (batched per doc-update discipline).

## Rollback

Revert the commit. `admin_sessions` table stays in place (unused, harmless). The revert restores `require_admin_token` + header auth + localStorage flow. No data loss — session table is pure ephemeral state.

## Hard stop

Do NOT merge. Push to `origin/remediation/sec-01-p1` after each logical commit. Open a PR via `gh pr create` with title `remediation/sec-01-p1: admin token localStorage → server-side session`. Wait for CI green. Report PR URL + CI status. Do NOT merge.
