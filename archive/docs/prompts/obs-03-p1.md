# obs-03-p1 — Phase 1 implementation: centralized impact_id allocator

## Context

Foundation work under the remediation program (`docs/REMEDIATION_PLAN.md` Theme 2; `docs/REMEDIATION_CHECKLIST.md` Batch 2-A). Audit item MAJOR-13 (P-04): `impact_id` allocation via `_next_id` is inline in `manifest.py`, a dead bypass exists in `shared.py` via `DEFAULT nextval`, and DuckDB sequences are 40k+ behind `MAX(impact_id)` — any caller that triggers `nextval` collides immediately.

Phase 0 investigation complete (`docs/findings/obs-03-p0-findings.md`, PR #8). This Phase 1 prompt implements the centralized allocator designed in that findings doc §5.

## Design decisions (confirmed by user 2026-04-20)

| # | Decision |
|---|---|
| 1 | `reserve_ids` takes `n` (integer), not a frame. |
| 2 | Lock file path: `data/.ingestion_lock` (same filesystem as DB). |
| 3 | Drop `DEFAULT nextval` first via migration. Keep sequences one release cycle for diagnostic. Drop sequences in a follow-up. |
| 4 | API-compatible with `write_impact` — load-bearing constraint. obs-01 can land in either order safely. |
| 5 | Allocation audit via standard logging only (no new table). Add table later if needed. |

## Branch

`remediation/obs-03-p1` off main HEAD.

## Files this session will touch

Write:
- `scripts/pipeline/id_allocator.py` (new) — `allocate_id`, `reserve_ids`
- `scripts/pipeline/manifest.py` — replace inline `_next_id` with import from `id_allocator`
- `scripts/pipeline/shared.py` — delete dead `write_impact_row` function (lines ~430-455)
- `scripts/migrations/010_drop_nextval_defaults.py` (new) — `ALTER TABLE ... ALTER COLUMN ... DROP DEFAULT` for `impact_id` and `manifest_id` on both `ingestion_impacts` and `ingestion_manifest`
- `scripts/promote_nport.py` — mirror path (lines ~135-144): replace staging-PK copy with `reserve_ids` + frame rewrite
- `scripts/promote_13dg.py` — mirror path (lines ~259-268): same change

Read (verification only):
- `docs/findings/obs-03-p0-findings.md` — the design spec
- `scripts/fetch_market.py`, `scripts/fetch_nport_v2.py`, `scripts/fetch_13dg_v2.py`, `scripts/fetch_dera_nport.py` — confirm they call `write_impact` (no changes needed, API-compatible)
- `data/13f.duckdb`, `data/13f_staging.duckdb` — apply migration, verify DDL

**If the worker touches any file not in this list, it must stop and escalate rather than proceed.** This list matches Appendix D of `docs/REMEDIATION_PLAN.md`.

## Scope

### 1. New module: `scripts/pipeline/id_allocator.py`

Extract `_next_id` from `scripts/pipeline/manifest.py` (lines 27-51) into a dedicated module. Rename to `allocate_id`.

```python
# scripts/pipeline/id_allocator.py

def allocate_id(con, table: str, pk_col: str) -> int:
    """Single-id allocation with advisory file lock."""
    # 1. Validate table against _ID_TABLES allow-list (carry over from manifest.py)
    # 2. Acquire fcntl.flock on data/.ingestion_lock (LOCK_EX)
    # 3. SELECT COALESCE(MAX(pk_col), 0) + 1 FROM table
    # 4. Return the id (caller INSERTs immediately after on same con)
    # 5. Release lock in finally block

def reserve_ids(con, table: str, pk_col: str, n: int) -> range:
    """Bulk allocation for mirror/retro-mirror paths."""
    # 1. Same lock discipline as allocate_id
    # 2. start = COALESCE(MAX(pk_col), 0) + 1
    # 3. Return range(start, start + n)
    # 4. Caller rewrites frame PKs to this range before INSERT
    # 5. Release lock in finally block
```

Implementation notes:
- `_ID_TABLES` allow-list from `manifest.py` carries over (currently `{'ingestion_impacts', 'ingestion_manifest'}`).
- Lock file path: `Path(con.execute("SELECT current_database()").fetchone()[0]).parent / '.ingestion_lock'` — or hardcode `data/.ingestion_lock` if `current_database()` is unreliable. Use `pathlib.Path`.
- `fcntl.flock(fd, fcntl.LOCK_EX)` — blocking exclusive lock. Release in `finally`. The lock file is created on first use (`open(..., 'a')`).
- Log each allocation: `logger.info(f"id_allocator: {table}.{pk_col} allocated {result} (pid={os.getpid()})")` for single, and `logger.info(f"id_allocator: {table}.{pk_col} reserved {start}..{start+n-1} (pid={os.getpid()})")` for bulk.
- Do NOT import or use DuckDB sequences. The allocator is purely `MAX+1` based.

### 2. `scripts/pipeline/manifest.py` — rewire to `id_allocator`

- Remove the inline `_next_id` function (lines ~27-51).
- Add `from scripts.pipeline.id_allocator import allocate_id` (or relative import per project convention).
- Replace the `_next_id(con, table, pk_col)` call at line ~190 with `allocate_id(con, table, pk_col)`.
- `write_impact(...)` signature and behavior must remain identical. This is the API-compatibility constraint — all existing fetchers (`fetch_market.py`, `fetch_nport_v2.py`, `fetch_13dg_v2.py`, `fetch_dera_nport.py`) call `write_impact` and must not need changes.
- If `manifest.py` also calls `_next_id` for `ingestion_manifest` allocation, rewire that too.

### 3. `scripts/pipeline/shared.py` — delete `write_impact_row`

- Delete the `write_impact_row` function (lines ~430-455). Zero callers exist (verified in findings §1.1).
- Verify with `grep -rn "write_impact_row" scripts/` that no caller appears after deletion.
- If any import statement references `write_impact_row`, remove that too.

### 4. Migration 010 — drop `DEFAULT nextval`

Create `scripts/migrations/010_drop_nextval_defaults.py`:

```sql
ALTER TABLE ingestion_impacts ALTER COLUMN impact_id DROP DEFAULT;
ALTER TABLE ingestion_manifest ALTER COLUMN manifest_id DROP DEFAULT;
```

- Idempotent: check if the default exists before dropping (DuckDB may error on dropping a non-existent default — test this).
- Apply to both `13f.duckdb` and `13f_staging.duckdb`.
- Do NOT drop the sequences themselves yet (one-cycle diagnostic retention per decision #3).
- Forward-only (no `down()`).
- Structured like `009_admin_sessions.py`.

### 5. `scripts/promote_nport.py` — mirror path rewrite

Replace lines ~135-144 (`INSERT INTO ingestion_impacts SELECT im.* FROM im WHERE NOT EXISTS (...)`) with:

1. Count rows to insert: `n = len(new_impacts_frame)` (after the anti-join filter).
2. `id_range = reserve_ids(con, 'ingestion_impacts', 'impact_id', n)`.
3. Rewrite the frame's `impact_id` column: `frame['impact_id'] = list(id_range)`.
4. Then INSERT the rewritten frame.

This closes the sequence-drift root cause — prod never sees a staging-assigned PK again.

**Important:** the anti-join filter (`WHERE NOT EXISTS (SELECT 1 FROM ingestion_impacts WHERE ...)`) must still run to avoid re-inserting already-promoted rows. The only change is the PK source.

### 6. `scripts/promote_13dg.py` — mirror path rewrite

Same pattern as promote_nport (lines ~259-268). Same `reserve_ids` + frame rewrite.

### 7. Verification

**Unit tests (pytest):**
1. `allocate_id` returns `MAX+1`, monotonically increasing across successive calls.
2. `reserve_ids(con, table, pk_col, 1000)` returns a contiguous range of length 1000 starting at `MAX+1`.
3. After `reserve_ids`, the next `allocate_id` returns `start + n` (the range was consumed).
4. `write_impact(...)` still works identically — API compatibility smoke test.

**Integration:**
5. Pre-commit (ruff + pylint + bandit) clean on all modified files.
6. `make smoke` or equivalent passes.
7. Verify no remaining references to `write_impact_row` in the codebase.
8. Verify `DEFAULT nextval` is gone: `SELECT column_name, column_default FROM information_schema.columns WHERE table_name = 'ingestion_impacts' AND column_name = 'impact_id'` — `column_default` should be NULL.
9. Verify sequences still exist (diagnostic retention): `SELECT * FROM duckdb_sequences()` should still show `impact_id_seq` and `manifest_id_seq`.

**Concurrency (manual or scripted):**
10. Two-process test: spawn two Python subprocesses that both try `duckdb.connect(PROD_DB, read_only=False)`. Second should fail with DuckDB lock error, not PK collision.

## Out of scope

- obs-01 N-CEN/ADV manifest registration (separate item, adopts `write_impact` as-is).
- obs-04 retro-mirror (depends on `reserve_ids` from this PR but is a separate item).
- Promote atomicity (CODEX transaction-wrapping concern — separate item).
- Sequence DROP (deferred one cycle per decision #3).
- Allocation audit table (deferred per decision #5; logging only for now).
- Doc updates to REMEDIATION_CHECKLIST / ROADMAP / SESSION_LOG (batched per doc discipline).

## Rollback

Revert the commit. Re-add `_next_id` inline in `manifest.py`, restore `write_impact_row` in `shared.py`, revert promote mirror paths. The migration (DROP DEFAULT) is safe to leave in place — it only removes an unused default that no current code relies on.

## Hard stop

Do NOT merge. Push to `origin/remediation/obs-03-p1` after each logical commit. Open a PR via `gh pr create` with title `remediation/obs-03-p1: centralized id_allocator + sequence retirement`. Wait for CI green. Report PR URL + CI status. Do NOT merge.
