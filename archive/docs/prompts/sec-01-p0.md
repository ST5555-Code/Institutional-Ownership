# sec-01-p0 — Phase 0 investigation: admin token localStorage → server-side session

## Context

Foundation work under the remediation program (`docs/REMEDIATION_PLAN.md` Theme 4; `docs/REMEDIATION_CHECKLIST.md` Batch 4-A). Audit item MAJOR-11 (D-11, Pass 2 §7.4): admin token is persisted in browser `localStorage` without `HttpOnly`, `SameSite`, or server-side session table. XSS on any served page reads the token. The token survives browser restart. There is no server-side invalidation path other than rotating `ADMIN_TOKEN`.

Phase 0 is investigation only: confirm current client + server auth flow, inventory all browser storage of the token, draft a server-side session-table design, and scope the Phase 1 migration. **No code writes, no DB writes.**

## Branch

`remediation/sec-01-p0` off main HEAD.

## Files this session will touch

Read-only / investigation:
- `web/templates/admin.html:180-202` — token storage site (client)
- `scripts/admin_bp.py` — token validation flow (server); especially `:86-90`, `:268-283`, `:597-771`
- `web/react-app/src/**/*.tsx` (admin-related components only) — any React admin UI that reads/writes token
- `scripts/migrations/` — inspect for any existing `admin_sessions` / `user_sessions` table
- SEC / cookies / CSRF middleware in FastAPI routers if any exist

Write:
- `docs/findings/sec-01-p0-findings.md` — new findings doc

**If the worker touches any file not in this list, it must stop and escalate rather than proceed.** This list matches Appendix D of `docs/REMEDIATION_PLAN.md`.

## Scope

1. Trace the full auth flow from browser → FastAPI:
   - Where is `ADMIN_TOKEN` set (env var)?
   - How does the client acquire it initially?
   - How does it attach it to requests (header name, cookie, query param)?
   - How does the server validate (constant-time compare, rate limiting, etc.)?
2. Confirm XSS exposure: is there any served page that interpolates user input without escaping?
3. Inventory all browser storage of the token (localStorage, sessionStorage, cookies).
4. Design the server-side session table:
   - DDL: `admin_sessions (session_id UUID PK, issued_at TS, expires_at TS, last_used_at TS, ip, user_agent)`.
   - Cookie attributes: `HttpOnly`, `Secure` (if TLS), `SameSite=Strict`.
   - Rotation / revocation path (logout button, admin expire-all endpoint).
5. Cross-item awareness:
   - sec-02 (TOCTOU) is adjacent: both touch `admin_bp.py`; must run serial with sec-01.
   - sec-03 (write-surface audit) consumes sec-01 results.
6. Draft Phase 1 implementation plan:
   - Migration script shape.
   - `admin_bp.py` diff outline (token → session lookup).
   - `admin.html` diff outline (drop localStorage; rely on HttpOnly cookie).
   - Test plan (browser: login → refresh → logout → re-login; server: expired session rejection).

## Out of scope

- Code writes.
- DB writes.
- sec-02 TOCTOU race fix.
- sec-03 write-surface audit.
- Multi-tenant access control (deferred to Phase 2).

## Deliverable

`docs/findings/sec-01-p0-findings.md` structured like prior BLOCK Phase 0 findings. Cite file:line. Include a threat-model paragraph (XSS, CSRF, session fixation) and a constraints-based justification for each design decision.

## Hard stop

Do NOT merge. Open a PR via `gh pr create` with title `remediation/sec-01-p0: Phase 0 findings — admin token server-side session migration`. Report PR URL + CI status.
