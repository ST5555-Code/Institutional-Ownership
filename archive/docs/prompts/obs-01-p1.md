# obs-01-p1 — Phase 1 implementation: N-CEN + ADV manifest registration

## Context

Foundation work under the remediation program (`docs/REMEDIATION_PLAN.md` Theme 2; `docs/REMEDIATION_CHECKLIST.md` Batch 2-A). Audit item MAJOR-9 (D-07/P-05). Phase 0 (`docs/findings/obs-01-p0-findings.md`, PR #20) confirmed both fetchers write zero rows to `ingestion_manifest` / `ingestion_impacts`. No DDL or id_allocator changes needed — `source_type` is free-text VARCHAR and both tables are already on the allocator allow-list.

Phase 1 scope: wire `fetch_ncen.py` and `fetch_adv.py` into the manifest framework via `pipeline.manifest` helpers.

## Design decisions (confirmed by user 2026-04-21)

| # | Decision |
|---|---|
| 1 | N-CEN `report_date`: use `filing_date` as fallback when `reportPeriodDate` missing. |
| 2 | ADV snapshot cadence: new ZIP URL → new `object_key` → new manifest row. Desired behavior, no change needed. |
| 3 | Entity-sync: verify `manifest_id` is NOT passed to `entity_sync.sync_from_ncen_row`. No manifest-FK work. |
| 4 | `parser_version` / `schema_version`: leave NULL (match `fetch_market.py` pattern). Address in obs-09 if needed. |

## Branch

`remediation/obs-01-p1` off main HEAD.

## Files this session will touch

Write:
- `scripts/fetch_ncen.py` — add manifest row per accession, impact row per (registrant_cik, report_date), idempotency check
- `scripts/fetch_adv.py` — add manifest row per ZIP, impact row per bulk_load

Read (verification only):
- `docs/findings/obs-01-p0-findings.md` — the design spec (§5.1, §5.2, §5.5, §5.6)
- `scripts/pipeline/manifest.py` — `get_or_create_manifest_row`, `update_manifest_status`, `write_impact` APIs
- `scripts/pipeline/id_allocator.py` — confirm allow-list covers both tables
- `scripts/fetch_market.py` — reference implementation for direct-write fetcher manifest pattern
- `scripts/fetch_nport_v2.py` — reference implementation for staged fetcher manifest pattern
- `data/13f.duckdb` (read-only) — verify pre-state (0 NCEN/ADV manifest rows)

**If the worker touches any file not in this list, it must stop and escalate rather than proceed.**

## Scope

### 1. `fetch_ncen.py` — manifest + impact registration

Per findings §5.1:

1. Add `run_id = f"ncen_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"` in the run function.
2. In the inner loop after `find_ncen_filing(cik)` succeeds:
   - Call `get_or_create_manifest_row(con, source_type="NCEN", object_type="XML", source_url=..., accession_number=filing["accession"], run_id=run_id, object_key=filing["accession"], fetch_status="fetching", ...)`.
   - Skip fetch if existing manifest row has `fetch_status='complete'` for this accession (idempotency).
3. After successful download + parse:
   - Call `write_impact(con, manifest_id=manifest_id, target_table="ncen_adviser_map", unit_type="registrant", unit_key_json=json.dumps({"registrant_cik": cik, "report_date": report_date}), ...)`.
   - Update manifest status to `complete`.
4. On failure: update manifest status to `failed` with `error_message`.
5. `report_date`: use `filing["filing_date"]` as fallback when `reportPeriodDate` is missing per decision #1.
6. Verify `manifest_id` is NOT passed to `entity_sync.sync_from_ncen_row` per decision #3.

### 2. `fetch_adv.py` — manifest + impact registration

Per findings §5.2:

1. Add `run_id = f"adv_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"` in `main()`.
2. Before `download_adv_zip()`:
   - Call `get_or_create_manifest_row(con, source_type="ADV", object_type="ZIP", source_url=ADV_ZIP_URL, accession_number=None, run_id=run_id, object_key=f"ADV_BULK:{os.path.basename(ADV_ZIP_URL)}", fetch_status="fetching", ...)`.
3. After `save_to_duckdb` + `record_freshness`:
   - Call `write_impact(con, manifest_id=manifest_id, target_table="adv_managers", unit_type="bulk_load", unit_key_json=json.dumps({"filename": os.path.basename(ADV_ZIP_URL)}), report_date=today, rows_staged=row_count, load_status="loaded", promote_status="promoted", rows_promoted=row_count, promoted_at=now())`.
   - Update manifest status to `complete`.
4. ADV is a direct-write (no staging/promote split) — same pattern as `fetch_market.py`.

### 3. Verification

Per findings §5.5:

1. **Schema check:** `SELECT COUNT(*) FROM ingestion_manifest WHERE source_type IN ('NCEN','ADV')` — must be 0 before, non-zero after a test run.
2. **Idempotency (N-CEN):** run `fetch_ncen.py --test` twice on the same CIKs. Second run must short-circuit without re-downloading. Row count unchanged.
3. **Idempotency (ADV):** run `fetch_adv.py` twice. Second run updates same manifest row, no duplicate.
4. Pre-commit clean. All existing tests pass.
5. `make smoke` passes.

### 4. Acceptance criteria

Per findings §5.6:
- After N-CEN run: `ingestion_manifest` has ≥1 row per CIK touched with `source_type='NCEN'`. Matching `ingestion_impacts` rows exist.
- After ADV run: exactly 1 manifest row with `source_type='ADV'` for current ZIP. Exactly 1 impact row.
- Neither fetcher writes manifest/impacts via anything other than `pipeline.manifest` helpers (grep audit).

## Out of scope

- ADV freshness log (obs-02).
- ADV atomicity / DROP+CREATE fix (mig-02).
- N-CEN amendment handling.
- `parser_version` / `schema_version` population (decision #4 — leave NULL).
- Admin dashboard UI wiring (Phase 2).
- Doc updates (batched).

## Rollback

Revert the commit. Manifest/impact rows written during test runs are harmless ephemeral data.

## Hard stop

Do NOT merge. Push to `origin/remediation/obs-01-p1`. Open PR with title `remediation/obs-01-p1: N-CEN + ADV manifest registration`. Wait for CI green. Do NOT merge.
