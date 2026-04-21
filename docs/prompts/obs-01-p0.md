# obs-01-p0 — Phase 0 investigation: N-CEN + ADV manifest registration

## Context

Foundation work under the remediation program (`docs/REMEDIATION_PLAN.md` Theme 2; `docs/REMEDIATION_CHECKLIST.md` Batch 2-A). Audit item MAJOR-9 (D-07/P-05): `fetch_ncen.py` and `fetch_adv.py` do not register their runs in `ingestion_manifest` / `ingestion_impacts` / `data_freshness`. They are the only active fetchers outside the control plane. This means the admin dashboard's freshness cards show no N-CEN or ADV data, and there is no manifest-based audit trail for those pipelines.

obs-03-p1 (centralized `id_allocator.py`) is merged. Any new manifest/impact writes from obs-01 must use `write_impact` from `pipeline/manifest.py` — not direct INSERT or `shared.write_impact_row` (deleted in obs-03-p1).

Phase 0 is investigation only. **No code writes, no DB writes.**

## Branch

`remediation/obs-01-p0` off main HEAD.

## Files this session will touch

Read-only / investigation:
- `scripts/fetch_ncen.py` — current N-CEN fetch flow, any existing freshness stamps
- `scripts/fetch_adv.py` — current ADV fetch flow, any existing freshness stamps
- `scripts/pipeline/manifest.py` — `write_manifest`, `write_impact`, `stamp_freshness` APIs
- `scripts/pipeline/id_allocator.py` — `allocate_id` API (obs-03-p1 output)
- `scripts/migrations/001_pipeline_control_plane.py` — existing `source_type` enum values, DDL for manifest/impacts/freshness
- `scripts/fetch_market.py` — reference implementation of a fetcher that uses the control plane correctly
- `scripts/fetch_nport_v2.py` — reference implementation
- `scripts/fetch_13dg_v2.py` — reference implementation
- `data/13f.duckdb` (read-only) — check current `ingestion_manifest` source_type values, `data_freshness` entries

Write:
- `docs/findings/obs-01-p0-findings.md` — new findings doc

**If the worker touches any file not in this list, it must stop and escalate rather than proceed.**

## Scope

1. **Inventory current fetch_ncen.py and fetch_adv.py flows:**
   - What do they fetch? From where? How often?
   - What tables do they write to? What is the write pattern (DELETE+INSERT, UPSERT, append)?
   - Do they have any existing freshness stamps (`data_freshness`, `last_refreshed_at`, log entries)?
   - What is the natural "unit of work" for manifest/impact registration? (per-file? per-adviser? per-run?)

2. **Review the control plane API:**
   - `write_manifest(con, source_type, object_key, ...)` — what fields are required?
   - `write_impact(con, manifest_id, ...)` — what fields are required?
   - `stamp_freshness(con, table_name, ...)` — what fields are required?
   - What `source_type` values exist today? What should N-CEN and ADV use?
   - Does `migrations/001` need a schema change to accept new source types, or is `source_type` a free-text VARCHAR?

3. **Compare against reference implementations:**
   - How does `fetch_market.py` register its runs? (manifest per batch, impact per ticker)
   - How does `fetch_nport_v2.py` register? (manifest per quarter, impact per series)
   - What is the right grain for N-CEN and ADV?

4. **Cross-item awareness:**
   - obs-02 (ADV freshness + log) — overlaps on `fetch_adv.py`. Serial with obs-01 per plan.
   - obs-03 (id_allocator) — merged. obs-01 must use `write_impact` which internally uses `allocate_id`. No direct `_next_id` or `DEFAULT nextval`.
   - obs-04 (13D/G impacts backfill) — uses `reserve_ids` from obs-03. No conflict with obs-01.
   - mig-02 (fetch_adv.py atomicity) — touches same file. Serial with obs-01 per plan.

5. **Design the Phase 1 integration:**
   - What changes to `fetch_ncen.py` and `fetch_adv.py`?
   - Does `migrations/001` need updates?
   - Test plan.
   - Acceptance criteria (admin dashboard shows N-CEN/ADV freshness).

## Out of scope

- Code writes.
- DB writes.
- obs-02 (ADV freshness — serial after obs-01).
- obs-04 (13D/G backfill).
- mig-02 (fetch_adv.py atomicity — serial after obs-01).

## Deliverable

`docs/findings/obs-01-p0-findings.md` structured like prior findings docs. Cite file:line.

## Hard stop

Do NOT merge. Open a PR via `gh pr create` with title `remediation/obs-01-p0: Phase 0 findings — N-CEN + ADV manifest registration`. Report PR URL + CI status.
