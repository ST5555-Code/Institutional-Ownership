# int-23 Design — Loader Idempotency Fix

_Generated: 2026-04-22. Option (a) locked: promote-step refuses flip on NULL downgrade. Base class only._

_Branch: `int-23-design`. Design-only — no code changes in this PR. Implementation lands in a follow-on `int-23-impl` session after Serge answers §7 open questions._

_Filename note: `docs/findings/int-23-p0-findings.md` already exists for a **different** `int-23` label (BLOCK-SEC-AUD-5 universe expansion, closed as already-done). This file uses a distinct filename (`int-23-design.md`). The shared label is a bookkeeping collision; the work is unrelated._

---

## 1. Root cause summary

On 2026-04-22 at 16:08:54, `scripts/load_13f_v2.py` re-ran against `quarter='2025Q4'` (run_id `13f_holdings_quarter=2025Q4_20260422_200854`, manifest_id `78902`). The loader pulled the SEC bulk 13F TSV, which does not carry a `ticker` column, and inserted every row with `NULL AS ticker` ([`scripts/load_13f_v2.py:515`](../../scripts/load_13f_v2.py)). Ticker is populated by a separate downstream enrichment step that joins `securities` on CUSIP — not by the loader.

The `append_is_latest` promote path in [`scripts/pipeline/base.py:436-501`](../../scripts/pipeline/base.py) executed its standard contract for each `(cik, quarter)` amendment key: `UPDATE ... SET is_latest = FALSE WHERE is_latest = TRUE`, then bulk `INSERT` of the new rows with `is_latest = TRUE`. Both sides recorded `flip_is_latest` + `insert` impacts (8,636 of each). Ticker enrichment was not re-run against the new population.

Result: 3.2M tickerless rows were stamped `is_latest=TRUE`; the displaced 3.2M ticker-enriched rows were stamped `is_latest=FALSE`. Every query filtering `is_latest=TRUE AND quarter='2025Q4'` returned only the tickerless population — `/api/v1/tickers` returned 0 rows, `query1('AAPL')` crashed on a downstream `None.lower()`.

**The invariant violated**: the `append_is_latest` strategy assumes the new population supersedes the displaced population in every material sense. That holds only when the new rows carry column coverage equal to or better than the displaced rows on every column a downstream consumer reads. In this incident, the new rows were a strict coverage downgrade on `ticker`, and the flip silently inverted the `is_latest` semantics of the table. The strategy's contract was correct per its own definition; the missing guard is a base-class invariant that should apply to every `append_is_latest` pipeline.

---

## 2. Design principle

For the `append_is_latest` strategy, the promote step must not mark a new row `is_latest=TRUE` if doing so would downgrade the coverage on any column the displaced row had populated. Concretely:

> For each `(key)` the loader is about to flip, and for each column in the downgrade-sensitive set, if the displaced population (prior `is_latest=TRUE` rows matching the key) has any non-NULL value on that column and the new staged population (rows matching the key) is all-NULL on that column, the promote step must abort the flip for the entire run and surface the refusal with enough evidence to diagnose. The run transitions to `failed` rather than completing silently.

Two supporting invariants fall out of this:

- **First-load safety.** If prod has no prior `is_latest=TRUE` rows for a key, there is nothing to downgrade, so the check passes. New pipelines against empty tables behave identically to today.
- **Strategy scope.** `scd_type2` and `direct_write` are unaffected. Each has its own semantics for supersession; neither exhibits the `is_latest` inversion failure mode.

**Why fail-fast rather than per-key skip.** A partial-load that silently skips some keys leaves the manifest in a misleading state — callers see `fetch_status='complete'` but a subset of keys retains the old `is_latest=TRUE` rows while others have been replaced. Freshness stamps, diff UI row counts, and downstream re-runs all assume "complete" means "all scope keys updated." Failing the entire run keeps the semantics binary: either the flip is clean or the manifest is `failed` and the run is reversible by re-running after the underlying cause (missing enrichment) is fixed.

---

## 3. Current implementation analysis

Target: [`scripts/pipeline/base.py:436-501`](../../scripts/pipeline/base.py) (`_promote_append_is_latest`).

Current flow, step by step:

1. **Line 439 — load staged rows.** `self._read_staged_rows()` returns a pandas DataFrame from the per-pipeline staging table. Empty → return empty `PromoteResult`.
2. **Line 443 — resolve `manifest_id`** from `run_id` for impact writes.
3. **Line 444 — read `key_cols`** from `self.amendment_key` (tuple, e.g. `("cik", "quarter")` for 13F).
4. **Lines 447-449 — stamp `is_latest=True`** on the in-memory DataFrame. Ensures staged rows are inserted with `is_latest=TRUE` regardless of upstream default.
5. **Line 453 — `BEGIN TRANSACTION`.** Single prod transaction covers flip + insert.
6. **Lines 455-473 — per-key flip loop.** For each unique `key_cols` combination in the staged rows:
   - Build `WHERE` clause.
   - Execute `UPDATE {target_table} SET is_latest = FALSE WHERE {key} AND is_latest = TRUE RETURNING 1`.
   - Count flipped rows.
   - `record_impact(action="flip_is_latest", rowkey=key)`.
7. **Lines 475-483 — bulk insert staged rows.** Registers the DataFrame as `staged_rows`, executes a single `INSERT ... SELECT`, unregisters.
8. **Lines 485-490 — insert-impact loop.** For each unique key, `record_impact(action="insert", rowkey=key)`.
9. **Line 492 — `COMMIT`.** On any exception, `ROLLBACK` via the `except` block at line 493-495.

**Exact injection point for the downgrade-refusal guard**: between line 459 (`for key in unique_keys:`) and line 462 (first `UPDATE` statement). A pre-flight pass runs *before* any flip or insert executes. The pre-flight reads from `prod_con` with the `BEGIN TRANSACTION` already open (safe — pure SELECTs against a write transaction are consistent). If any key fails the check, the pre-flight raises a new `DowngradeRefusalError`, the outer `except` catches it, `ROLLBACK` unwinds, and the error propagates to `approve_and_promote()` which marks the manifest `failed` via the existing `_transition_open_best_effort` path.

Alternative injection — a single batched pre-flight pass *before* the per-key flip loop starts (before line 455) — is cleaner. The check then lives at one location and processes all keys in one SQL round-trip per sensitive column. Recommended in §4.

Note on column coverage — line 451 builds `col_list` from `rows.columns` (the staged DataFrame columns). The staged column set is the authority for what's in the new population; the downgrade check compares that column set against prod's displaced population on the sensitive columns only. No need to diff full schemas.

---

## 4. Proposed implementation

### 4.1 Downgrade-sensitive column set

**Locked recommendation**: hard-coded in `SourcePipeline` as a single class-level constant, with a per-row existence guard against the target table schema. Proposed constant:

```python
_DOWNGRADE_SENSITIVE_COLUMNS: tuple[str, ...] = (
    "ticker",
    "entity_id",
    "rollup_entity_id",
)
```

**Justification for the three columns**:
- `ticker` — the column that actually broke int-22. Stamped at load time on `holdings_v2` via downstream enrichment. Every public API (`/api/v1/tickers`, `query1`, `portfolio_context`) filters or groups by it. A tickerless row surfaces as a hole in every consumer.
- `entity_id` — stamped MDM foreign key. Rollups, DM worldview, entity-scoped queries depend on it. A loader that inserts `entity_id=NULL` rows (which an early-pipeline run before entity resolution could plausibly do) would silently detach the quarter from the entity graph.
- `rollup_entity_id` — stamped rollup pointer. Similar exposure as `entity_id`; the `COALESCE(rollup_name, dm_rollup_name, inst_parent_name, manager_name)` chain in Tier 4 queries degrades to the raw filer name when `rollup_entity_id` is NULL.

**Justification for the guard mechanism** (existence check via `PRAGMA table_info` or `information_schema.columns`): int-09 Step 4 is actively retiring some or all of these stamped columns from `holdings_v2` in favor of runtime joins (see `docs/proposals/tier-4-join-pattern-proposal.md`). A column that does not exist on the target table is skipped silently by the guard. This means the fix does not block Step 4 migration; columns drop out of the check naturally as they are retired.

**Why hard-coded, not per-pipeline.** The task's scope lock confines changes to `scripts/pipeline/base.py`. A per-pipeline `downgrade_sensitive_columns` class attribute would require touching `load_13f_v2.py`, which collides with parallel U8 name-casing work. The hard-coded list with existence guard is functionally equivalent for the pipelines we ship today (`load_13f_v2` is the only `append_is_latest` caller that loads from a feed missing enrichment columns). Per-pipeline configuration is flagged as an open question in §7 for Serge to upgrade the design if another `append_is_latest` pipeline needs a different set later.

### 4.2 Check mechanism — SQL pre-flight, once per column

Run *before* the per-key flip loop. Pseudocode:

```python
# Resolve which of the sensitive columns exist on target_table.
target_cols = set of column names for self.target_table (read via PRAGMA table_info)
sensitive_cols = [c for c in SourcePipeline._DOWNGRADE_SENSITIVE_COLUMNS if c in target_cols]
if not sensitive_cols:
    # nothing to check — behave as today
    ...

# For each sensitive column: find keys where staged is all-NULL but prod has non-NULL
refusals: list[tuple[dict, str, int]] = []  # (key, column, displaced_nonnull_count)
for col in sensitive_cols:
    # Keys where staged rows carry no non-NULL value for this column.
    staged_null_keys = rows.groupby(key_cols)[col].apply(
        lambda s: s.notna().sum() == 0
    )
    null_only_keys = [k for k, is_null in staged_null_keys.items() if is_null]
    if not null_only_keys:
        continue
    for key in null_only_keys:
        where_sql = " AND ".join(f"{c} = ?" for c in key_cols)
        params = [key[c] for c in key_cols] if isinstance(key, dict) else list(key)
        count = prod_con.execute(
            f"SELECT COUNT(*) FROM {target_table} "
            f"WHERE {where_sql} AND is_latest = TRUE AND {col} IS NOT NULL",
            params,
        ).fetchone()[0]
        if count > 0:
            refusals.append((key, col, count))

if refusals:
    raise DowngradeRefusalError(
        target_table=self.target_table,
        refusals=refusals,
    )
```

Complexity: `O(sensitive_cols × offending_keys)` SELECT-COUNT queries against prod. In the int-22 scenario this is `1 column × 8,636 keys = 8,636` indexed point queries — a few seconds on `holdings_v2` with the existing `(cik, quarter)` PK. Optimization (if profiling shows overhead): batch offending keys per column into a single SQL with a derived table of keys + `JOIN` to `target_table`. Not needed for the 13F scope; flagged for post-implementation tuning only.

### 4.3 Abort behavior — fail the run

The pre-flight raises `DowngradeRefusalError` (new exception type in `base.py`). The surrounding `try/except` at lines 453-495 catches it and calls `ROLLBACK`. No impacts are persisted (the transaction unwinds them). The exception propagates to `approve_and_promote()` at line 355 (`result = self.promote(...)`). That call is not wrapped in a `try/except` today, so the exception bubbles to the caller of `approve_and_promote()`. `update_manifest_status(manifest_id, "failed")` is **not** currently called on this path — this is a gap in today's promote error handling, not a new one.

**Minor base-class change required**: wrap `self.promote(...)` in `approve_and_promote()` so a promote failure transitions the manifest to `failed` with `error_message` populated, rather than leaving it at `promoting`. This is a small, justified cleanup inside `base.py` scope.

### 4.4 Surface behavior

`DowngradeRefusalError` carries structured evidence: `target_table`, list of `(key, column, displaced_nonnull_count)` tuples, and a rendered summary string. On the failure path, `update_manifest_status(..., error_message=...)` writes a JSON-encoded payload into `ingestion_manifest.error_message`. Proposed shape:

```json
{
  "kind": "downgrade_refusal",
  "target_table": "holdings_v2",
  "refused_keys": [
    {"key": {"cik": "0000320193", "quarter": "2025Q4"}, "column": "ticker", "displaced_nonnull": 8981},
    ...
  ],
  "total_refused_keys": 8636,
  "column_breakdown": {"ticker": 8636}
}
```

Admin-dashboard surface (future int-admin-24 or similar, out of scope for int-23-impl): the admin UI parses this payload and renders the refused keys with their offending columns. No new `ingestion_impacts` row is written — impacts are per-successful-action; a run that fails pre-flight writes nothing.

**Truncation**: if `refused_keys` exceeds ~100 entries, store the first 100 + `total_refused_keys` count. `error_message` is a `VARCHAR` on `ingestion_manifest` and long payloads are truncated to 500 chars by `_transition_open_best_effort` today (see base.py:321 `str(e)[:500]`). A dedicated `DowngradeRefusalError.to_manifest_payload()` method returns the truncated-JSON form explicitly, bypassing the blunt 500-char cut.

### 4.5 Backward compatibility

- **Strategies other than `append_is_latest`.** `scd_type2` (`_promote_scd_type2`) and `direct_write` (`_promote_direct_write`) are untouched. `load_market.py` (direct_write) continues to `DELETE` + `INSERT` without any NULL-downgrade guard — correct, because `direct_write` has no `is_latest` inversion failure mode.
- **First-load safety.** A key with zero prior `is_latest=TRUE` rows in prod passes the check trivially (all `COUNT(*) = 0`). First loads of new `append_is_latest` pipelines behave exactly as today.
- **Legitimate NULL columns on fresh inserts.** Because the check is *only* triggered when the displaced population has a non-NULL value on that column, a pipeline that has always inserted NULL on a column (so prod carries NULL everywhere) is not affected. The rule is strictly "no downgrade from the current state," not "every column must be populated."
- **Existing pipelines — `load_13f_v2`.** Today's only `append_is_latest` caller. Post-fix, a clean run against a fresh quarter behaves identically (first load passes). A re-run against an already-loaded quarter fails with the refusal error rather than silently inverting `is_latest` — this is the intended behavior change.
- **Future `append_is_latest` pipelines.** Any new subclass inherits the check automatically. If a new pipeline legitimately needs to load NULL-heavy rows against a non-NULL displaced population (unusual — effectively an enrichment removal), the pipeline author must either (i) argue for a per-pipeline override, (ii) enrich before promote, or (iii) switch strategies. Flagged in §7.

---

## 5. Test plan

All tests target `tests/pipeline/test_base_downgrade_refusal.py` (new file). Each uses an in-memory DuckDB populated via `pytest` fixture — no I/O to `data/13f.duckdb` or `data/13f_staging.duckdb`.

### 5.1 Test 1 — Replay the int-22 failure scenario

**Purpose**: verify the fix blocks the exact incident that happened on 2026-04-22.

**Setup**: fixture DuckDB with `holdings_v2` containing 10 rows for `(cik='0000320193', quarter='2025Q4')`, all `is_latest=TRUE` and `ticker='AAPL'`. Populate a staging table with 12 new rows for the same key, all `is_latest=TRUE` (set by the promote path) and `ticker=NULL`. Instantiate a minimal `TestPipeline(SourcePipeline)` with `amendment_strategy='append_is_latest'`, `amendment_key=('cik','quarter')`, `target_table='holdings_v2'`.

**Act**: `pipeline.approve_and_promote(run_id)`.

**Assert**:
- Raises `DowngradeRefusalError`.
- `e.refusals == [({'cik': '0000320193', 'quarter': '2025Q4'}, 'ticker', 10)]`.
- Post-state: `SELECT COUNT(*) FROM holdings_v2 WHERE quarter='2025Q4' AND is_latest=TRUE` == 10 (displaced rows untouched).
- Post-state: no rows in `holdings_v2` with `ticker IS NULL` (new rows never inserted — transaction rolled back).
- `ingestion_manifest.fetch_status` transitions to `'failed'`.
- `ingestion_manifest.error_message` contains `"kind": "downgrade_refusal"` JSON.

### 5.2 Test 2 — Clean first load with legitimate NULL columns

**Purpose**: verify fresh pipelines are not blocked by the check.

**Setup**: fixture DuckDB with an empty `holdings_v2` (0 prior rows). Staged rows contain 100 entries for `(cik='0000000001', quarter='2026Q1')`, every row has `ticker=NULL` (e.g. a future loader that runs before enrichment) and `is_latest=TRUE`.

**Act**: `pipeline.approve_and_promote(run_id)`.

**Assert**:
- Returns `PromoteResult(rows_inserted=100, rows_flipped=0)`.
- `holdings_v2` has 100 rows post-promote, all `is_latest=TRUE`.
- `ingestion_manifest.fetch_status == 'complete'`.
- `ingestion_impacts` has 1 `insert` row for the key, 0 `flip_is_latest` rows.

### 5.3 Test 3 — Partial downgrade across multiple keys

**Purpose**: verify the check catches all offending keys, not just the first one, and surfaces structured evidence.

**Setup**: prod has prior `is_latest=TRUE` rows for three keys — key A (`ticker='AAPL'`), key B (`ticker='MSFT'`), key C (`ticker=NULL`). Staged rows for all three keys are all `ticker=NULL`.

**Act**: `pipeline.approve_and_promote(run_id)`.

**Assert**:
- Raises `DowngradeRefusalError`.
- `e.refusals` contains entries for keys A and B (2 entries), not for key C (no downgrade — prod was already NULL there).
- `e.total_refused_keys == 2`.
- Manifest `error_message` JSON `refused_keys` list length == 2.

### 5.4 Test 4 — Rollback of a completed run after the fix ships

**Purpose**: verify that if a pre-fix run completed silently (hypothetical old state) and is rolled back post-fix, the rollback path does not regress. This tests that the new code does not interfere with `pipeline.rollback()` at all — impacts-driven reversal continues to work.

**Setup**: fixture DuckDB with a manifest row in `'complete'` status (simulating a pre-fix run that inverted `is_latest`), with matching `flip_is_latest` + `insert` impacts. Seed `holdings_v2` with the inverted state (new tickerless rows `is_latest=TRUE`, old ticker-enriched rows `is_latest=FALSE`).

**Act**: `pipeline.rollback(run_id)`.

**Assert**:
- `fetch_status` transitions `'complete'` → `'rolled_back'`.
- Post-state matches the expected rollback outcome (tickerless rows deleted, ticker-enriched rows back to `is_latest=TRUE`).
- No interaction with the new `DowngradeRefusalError` path (rollback is a distinct code path and should be unaware of the check).

---

## 6. Implementation PR scope

### 6.1 Files the `int-23-impl` session MAY change

| Path | Scope |
|---|---|
| `scripts/pipeline/base.py` | Add `DowngradeRefusalError` exception, `_DOWNGRADE_SENSITIVE_COLUMNS` constant, `_check_no_downgrade_refusal()` helper, call site in `_promote_append_is_latest`, wrap `promote()` call in `approve_and_promote()` to mark manifest `failed` on refusal. |
| `tests/pipeline/test_base_downgrade_refusal.py` | New test file covering the four tests in §5. |
| `tests/pipeline/conftest.py` (if exists) | Only if a shared fixture needs augmentation for DuckDB-backed `SourcePipeline` tests. |

### 6.2 Files the `int-23-impl` session MUST NOT change

| Path | Why |
|---|---|
| `scripts/load_13f_v2.py` | Collides with parallel U8 name-casing work. The fix is base-class-only by scope lock. |
| `scripts/pipeline/load_*.py` | Any per-pipeline subclass. Not touched in this PR. |
| `scripts/queries.py` | Read path. Unrelated to the loader idempotency gap. |
| Any migration file under `scripts/migrations/` | No schema change required. |
| `scripts/rollback_run.py` | Rollback path is already correct (int-22 closed on this). |
| Any file under `data/` | No prod or staging DB writes in the implementation PR. Tests use in-memory DuckDB. |

### 6.3 Enforcement

Pre-commit / CI check: the implementation PR CI should fail if any path outside the allowlist shows a diff. Two options:

- **Simple**: the implementation session opens a PR with a title prefix `int-23-impl:`, and the PR review confirms the diff is confined to `scripts/pipeline/base.py` + `tests/`. Manual check.
- **Stricter**: add a one-liner CI check (`git diff --name-only main | grep -v -E '^(scripts/pipeline/base\.py|tests/)'` → fail if any output). Adds CI plumbing; likely overkill for a single PR.

Recommend: **manual review gate**. The scope is small and the reviewer (Serge) will read the diff anyway.

---

## 7. Open questions for Serge

1. **Hard-coded vs per-pipeline sensitive column set.** The locked design hard-codes `("ticker", "entity_id", "rollup_entity_id")` with an existence guard, because the scope lock forbids touching `load_13f_v2.py`. A per-pipeline class attribute (`downgrade_sensitive_columns: tuple[str, ...] = ()`) is cleaner long-term but requires a one-line change to every `append_is_latest` subclass. **Question**: accept the hard-coded approach for int-23-impl, and file a follow-up to migrate to per-pipeline after U8 name-casing lands? Or expand scope now to permit a one-line class-attr add to `load_13f_v2.py`?

2. **Failure mode granularity — fail the whole run, or per-key partial-complete?** The locked design fails the entire run on any refusal. A per-key partial mode (skip offending keys, promote the rest, record `promote_refused` impacts for skipped keys) is more permissive but complicates semantics — "complete" no longer means "all scope updated." **Question**: confirm fail-the-run is correct, or is there a use case where partial completion is operationally preferable?

3. **Truncation policy for `error_message` JSON.** If a refusal spans thousands of keys (int-22 had 8,636), the full JSON payload exceeds the 500-char manifest truncation. Proposed: first 100 refused keys + `total_refused_keys` count. **Question**: is 100 the right cap, or should the payload be written to a side table (`ingestion_promote_refusals`) instead of crammed into `error_message`? The latter is a schema change (out of scope for base-class-only), but is the right long-term shape.

4. **Admin dashboard surface.** Int-23-impl ends at the manifest `error_message` payload. Surfacing the refusal in the admin UI is a separate follow-up. **Question**: file now as `int-admin-24` or defer until after int-23-impl ships and the payload format is settled?

5. **`entity_id` / `rollup_entity_id` in the sensitive set.** These are strong candidates per §4.1, but int-09 Step 4 is actively retiring them (see `docs/proposals/tier-4-join-pattern-proposal.md`). The existence guard handles this gracefully — columns auto-drop out when retired. **Question**: include them now (defensive until Step 4 ships) or ship with just `ticker` (minimal surface, matches the exact int-22 failure mode)?

---

## 8. Forward-compatibility note

Int-09 Step 4 retires a set of stamped columns on `holdings_v2` in favor of runtime joins (`docs/proposals/tier-4-join-pattern-proposal.md`). The columns flagged for retirement overlap with the proposed downgrade-sensitive set — specifically `ticker`, `entity_id`, `rollup_entity_id`, and potentially the `*_name` columns. The existence guard in §4.2 handles this: any sensitive column that is not present on `target_table` is skipped silently by the check, so the fix does not block Step 4 migration.

**Dependency at retirement time**: when Step 4 drops `ticker` from `holdings_v2`, the downgrade check for `ticker` becomes a no-op on 13F. At that point, the loader + enrichment sequencing problem that drove int-22 dissolves — there is no stamped `ticker` column to downgrade. The risk shifts instead to `entity_id` (if kept) and `rollup_entity_id` (if kept), and to any new stamped columns Step 4 introduces during the transition. The int-09 Step 4 author should audit the proposed schema against `_DOWNGRADE_SENSITIVE_COLUMNS` and update the constant if new stamped columns carry similar exposure.

**Secondary dependency**: Step 4 may introduce a period where `entity_id` reads transition from stamped column to runtime join. During that period, the loader may stop populating `entity_id` even before the column is dropped from the table. The existence guard does not catch that state — the column still exists, but is NULL across the board. Recommendation: when Step 4 begins its transition, either (i) drop the column before Step 4 consumers switch, or (ii) remove `entity_id` from `_DOWNGRADE_SENSITIVE_COLUMNS` for the duration of the transition. This is a coordination point, not a technical blocker.

No other forward-compat dependencies identified. Migration 015 (amendment semantics, 2026-04-22) is settled. The rollback path (`_rollback_insert`, `_rollback_flip`) is unaffected by the fix and continues to work on any pre-fix complete runs.
