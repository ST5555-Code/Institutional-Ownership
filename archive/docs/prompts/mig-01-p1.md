# mig-01-p1 — Phase 1 implementation: atomic promotes + manifest mirror extraction

## Context

Foundation work under the remediation program (`docs/REMEDIATION_PLAN.md` Theme 3; `docs/REMEDIATION_CHECKLIST.md` Batch 3-A). Audit item BLOCK-2. Phase 0 (`docs/findings/mig-01-p0-findings.md`, PR #31) confirmed: neither promote script wraps its writes in a transaction. DELETE+INSERT on `fund_holdings_v2` / `beneficial_ownership_v2` has a data-loss window on mid-sequence crash. The manifest mirror helper is duplicated across both scripts.

## Branch

`remediation/mig-01-p1` off main HEAD.

## Files this session will touch

Write:
- `scripts/pipeline/manifest.py` — add extracted `mirror_manifest_and_impacts(prod_con, staging_con, run_id, source_type)` helper
- `scripts/promote_nport.py` — replace inline mirror with import; wrap write sequence in BEGIN TRANSACTION / COMMIT; collapse CHECKPOINTs to one post-COMMIT
- `scripts/promote_13dg.py` — same treatment

Read (verification only):
- `docs/findings/mig-01-p0-findings.md` — the design spec (§2, §4, §5)
- `scripts/pipeline/id_allocator.py` — confirm `reserve_ids` is transaction-safe (per findings §3.3)
- `scripts/pipeline/shared.py` — `stamp_freshness`, `bulk_enrich_bo_filers`, `rebuild_beneficial_ownership_current` called from promote scripts
- `scripts/promote_staging.py` — reference for BEGIN/COMMIT pattern already in use

**If the worker touches any file not in this list, it must stop and escalate rather than proceed.**

## Scope

### 1. Extract mirror helper to `pipeline/manifest.py`

Per findings §4.2, add:

```python
def mirror_manifest_and_impacts(prod_con, staging_con, run_id, source_type):
    """Mirror staging manifest + impacts rows into prod with prod-side PKs.
    
    Returns (manifest_ids, impact_count) for downstream scope filtering.
    """
```

- Filter manifest rows by `source_type` (unifies both call sites per findings §4.2).
- DELETE-by-id + DELETE-by-object_key double-delete pattern.
- Anti-join on `(manifest_id, unit_type, unit_key_json)` for impacts.
- `reserve_ids` for impact_id allocation.
- Return manifest_ids for downstream use.

### 2. Transaction wrapping for `promote_nport.py`

Wrap the entire write sequence (findings §2.1 steps 1-12) in:

```python
prod_con.execute("BEGIN TRANSACTION")
try:
    # Steps 1-9: mirror, DELETE+INSERT holdings, enrichment, universe, impacts UPDATE
    prod_con.execute("COMMIT")
except Exception:
    prod_con.execute("ROLLBACK")
    raise
# Steps 10-12: stamp_freshness + single CHECKPOINT (outside transaction)
```

Key points:
- `CHECKPOINT` cannot run inside a transaction (DuckDB constraint per findings). Move all CHECKPOINTs to one call after COMMIT.
- `stamp_freshness` can run outside the transaction — it is metadata, not the critical data path. A crash after COMMIT but before freshness stamp is recoverable (re-run stamps correctly).
- The TEMP table (`_promote_scope`) works inside a transaction in DuckDB.
- `reserve_ids` advisory lock releases before the transaction commits — this is correct per findings §3.3.

### 3. Transaction wrapping for `promote_13dg.py`

Same pattern. Wrap steps 1-10 (findings §2.2) in BEGIN/COMMIT/ROLLBACK. Single CHECKPOINT after COMMIT. Freshness stamps after CHECKPOINT.

### 4. Replace inline mirror code

- `promote_nport.py`: replace lines ~82-167 with `from scripts.pipeline.manifest import mirror_manifest_and_impacts` (or relative import per convention).
- `promote_13dg.py`: replace lines ~207-294 with one call to the extracted helper.

### 5. Verification

- Pre-commit clean. All existing tests pass. `make smoke` passes.
- Grep: no remaining inline `DELETE FROM ingestion_manifest` / `DELETE FROM ingestion_impacts` in promote scripts (all routed through helper).
- Grep: `BEGIN TRANSACTION` present in both promote scripts.
- Grep: at most one `CHECKPOINT` per promote script (post-COMMIT).
- Manual review: the `promote_staging.py:603-616` reference pattern matches what we implemented.

## Out of scope

- mig-02 (fetch_adv.py atomicity — separate item).
- Changes to `pipeline/shared.py` (stamp_freshness, bulk_enrich, rebuild_bo_current stay as-is).
- Doc updates (batched).

## Rollback

Revert the commit. Restores auto-commit behavior. The extracted helper in manifest.py is harmless to leave in place.

## Hard stop

Do NOT merge. Push to `origin/remediation/mig-01-p1`. Open PR with title `remediation/mig-01-p1: atomic promotes + manifest mirror extraction`. Wait for CI green. Do NOT merge.
