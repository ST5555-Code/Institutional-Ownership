# sec-03-p0 — Phase 0 investigation: admin endpoint write-surface audit

## Context

Foundation work under the remediation program (`docs/REMEDIATION_PLAN.md` Theme 4; `docs/REMEDIATION_CHECKLIST.md` Batch 4-B). Audit item MAJOR-5 (C-09): the admin endpoint surface has grown to 17+ routes with 5 write paths, but no systematic inventory exists of what each endpoint can modify, what guards it, and what the blast radius is on failure.

sec-01-p1 (session auth) and sec-02-p1 (TOCTOU fix) are both merged. sec-02-p0 findings §2 produced a preliminary write-surface inventory table — this investigation extends it into a complete audit covering every admin route plus any non-admin write paths reachable from the admin UI.

Phase 0 is investigation only. **No code writes, no DB writes.**

## Branch

`remediation/sec-03-p0` off main HEAD.

## Files this session will touch

Read-only / investigation:
- `scripts/admin_bp.py` — all admin endpoints, guards, write targets
- `scripts/app.py` — router wiring, non-admin routes
- `scripts/api_register.py`, `scripts/api_flow.py`, `scripts/api_conviction.py`, `scripts/api_crowding.py`, `scripts/api_smart_money.py`, `scripts/api_fund.py`, `scripts/api_cross.py`, `scripts/api_peer.py`, `scripts/api_sector.py`, `scripts/api_new_exits.py`, `scripts/api_aum.py` — non-admin API routes (confirm read-only)
- `web/templates/admin.html` — client-side invocations
- `docs/findings/sec-02-p0-findings.md` — §2 preliminary inventory to extend
- `docs/findings/sec-01-p0-findings.md` — session auth design reference

Write:
- `docs/findings/sec-03-p0-findings.md` — new findings doc

**If the worker touches any file not in this list, it must stop and escalate rather than proceed.**

## Scope

1. **Complete endpoint inventory.** For every route under `admin_router` and `login_router` (or however the routers are structured post-sec-01-p1):
   - Method + path
   - Write target (DB table, file, subprocess, external API)
   - Guard (auth dep, flock, pgrep, none)
   - Idempotency (safe to call twice?)
   - Blast radius on failure (data corruption? log stomping? quota burn? loud crash?)

2. **Non-admin write paths reachable from admin UI.** The admin HTML page may call non-admin endpoints (e.g. `/api/tickers`). Inventory any that perform writes.

3. **Classify each write endpoint:**
   - **GUARDED** — has a concurrency/auth guard that prevents the identified failure mode
   - **UNGUARDED** — no guard, susceptible to concurrent invocation issues
   - **PARTIALLY GUARDED** — has a guard but with known gaps

4. **Flag items for sec-04 and beyond:**
   - `/add_ticker` was flagged in sec-02-p0 §2 as unguarded. Confirm and detail the risk.
   - Any endpoint that writes to prod DB directly (bypassing staging) — flag for sec-05/sec-06.
   - Any endpoint missing input validation — flag.

5. **Cross-item awareness:**
   - sec-04 (validators writing to prod) — overlaps with any endpoint that calls `validate_*.py`.
   - Phase 2 admin refresh — will add 9+ new endpoints. This audit establishes the baseline before that expansion.

6. **Deliverable structure:**
   - Full endpoint table (extends sec-02-p0 §2 format)
   - Per-endpoint risk assessment (1 paragraph each for write endpoints)
   - Prioritized remediation recommendations
   - Phase 1 scope if any immediate fixes are warranted

## Out of scope

- Code writes.
- DB writes.
- sec-04 implementation (validators → prod fix).
- sec-05/sec-06 (hardcoded-prod builders, direct-to-prod writers).
- Phase 2 admin refresh endpoints (not yet built).

## Deliverable

`docs/findings/sec-03-p0-findings.md` structured like prior findings docs. Full endpoint inventory table + risk assessment + recommendations.

## Hard stop

Do NOT merge. Open a PR via `gh pr create` with title `remediation/sec-03-p0: Phase 0 findings — admin endpoint write-surface audit`. Report PR URL + CI status.
