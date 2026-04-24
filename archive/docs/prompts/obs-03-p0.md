# obs-03-p0 — Phase 0 investigation: market `impact_id` allocation hardening

## Context

Foundation work under the remediation program (`docs/REMEDIATION_PLAN.md` Theme 2; `docs/REMEDIATION_CHECKLIST.md` Batch 2-A). Audit item MAJOR-13 (P-04): the `market_data` `impact_id` duplicate-PK crash recurred 2026-04-16 **post-fix**, which means `_next_id` is only safe under the true one-writer invariant. Every direct `INSERT INTO ingestion_impacts` that bypasses `manifest._next_id()` is a potential foot-gun.

Phase 0 is investigation only: inventory every ingestion_impacts writer; identify bypasses; quantify the one-writer invariant's fragility; draft a centralization proposal. **No code writes, no DB writes.**

## Branch

`remediation/obs-03-p0` off main HEAD.

## Files this session will touch

Read-only / investigation:
- `scripts/pipeline/manifest.py` — `_next_id()` implementation at `:27-51, :157-193`
- `scripts/fetch_market.py` — recurred-crash site; reference log `logs/fetch_market_crash.log:35-49`
- `scripts/fetch_nport_v2.py` — likely impact_id consumer via manifest
- `scripts/fetch_13dg_v2.py` — likely impact_id consumer via manifest
- `scripts/promote_nport.py`, `scripts/promote_13dg.py` — impact mirror operations (read-only for this Phase 0)
- `logs/fetch_market_crash.log` if still present
- `data/13f.duckdb` (read-only) — query `ingestion_impacts` for recent duplicate-PK or gap patterns

Write:
- `docs/findings/obs-03-p0-findings.md` — new findings doc

**If the worker touches any file not in this list, it must stop and escalate rather than proceed.** This list matches Appendix D of `docs/REMEDIATION_PLAN.md`.

## Scope

1. Inventory every `INSERT INTO ingestion_impacts` call across the repo (grep for exact string).
2. For each: does it go through `manifest._next_id()`? If not, record the file:line and the allocation pattern (local counter, max+1, random, etc.).
3. Reproduce the 2026-04-16 crash condition:
   - What concurrent-writer scenario triggered it?
   - Is there a single parent process or are two processes racing on the same `ingestion_impacts` table?
   - Can the current `_next_id()` serialize two concurrent calls from two OS processes?
4. Quantify current `ingestion_impacts` state:
   - Row count per source (market / nport / 13dg / ncen / adv — if present).
   - Any PK gaps? Any duplicate-PK attempts in logs over the last 30 days?
5. Cross-item awareness:
   - obs-01 will add N-CEN + ADV to `ingestion_manifest` (and therefore `ingestion_impacts`) — the centralized allocator must accommodate new sources.
   - obs-04 will retro-mirror pre-v2 13D/G history — needs allocator support for bulk inserts.
6. Draft the Phase 1 centralization proposal:
   - Single allocator in `pipeline/manifest.py` with file-lock or manifest-backed check-and-set.
   - Migration path for any current direct-INSERT callers.
   - Test plan — simulated concurrent writers.

## Out of scope

- Code writes.
- DB writes (including recovery from current state).
- obs-01 (N-CEN/ADV manifest registration) or obs-04 (13D/G backfill) work.

## Deliverable

`docs/findings/obs-03-p0-findings.md` structured like prior BLOCK Phase 0 findings (e.g., `docs/BLOCK_MARKET_DATA_WRITER_AUDIT_FINDINGS.md`). Cite file:line + commit SHAs.

## Hard stop

Do NOT merge. Open a PR via `gh pr create` with title `remediation/obs-03-p0: Phase 0 findings — market impact_id allocation hardening`. Report PR URL + CI status.
