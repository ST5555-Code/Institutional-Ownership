# int-14-p0 — Phase 0 findings: INF30 BLOCK-MERGE-UPSERT-MODE NULL-only merge

_Prepared: 2026-04-22 — branch `int-14-p0` off `main` HEAD `4ced172`._

_Tracker: [docs/REMEDIATION_PLAN.md](../REMEDIATION_PLAN.md) row `int-14` (INF30 BLOCK-MERGE-UPSERT-MODE). Upstream motivation: [docs/reports/block_sector_coverage_closeout_20260419_052804.md §7](../reports/block_sector_coverage_closeout_20260419_052804.md). Roadmap: [ROADMAP.md:570](../../ROADMAP.md) `INF30`. Companion to INF11 `PROMOTE_KIND` split already shipped as `b13d5f8`._

Phase 0 is investigation only. No code changes. Output is this document.

---

## §1. Headline

`scripts/merge_staging.py` at HEAD supports exactly two merge semantics — PK-keyed upsert (`DELETE`+`INSERT`) and full-table replace (`DROP`+`CTAS`). Both overwrite prod cells indiscriminately within their scope. There is no mode that preserves existing prod values and writes only where the prod cell is NULL. The `UPDATE`-semantics claim at [scripts/merge_staging.py:101-102](../../scripts/merge_staging.py:101) is a documentation bug — the actual SQL is DELETE-then-INSERT, so prod-only columns are NULL'd on matched rows rather than preserved. INF30 asks for a third mode: **NULL-only column-scoped merge**, needed by enrichment workflows (sector/industry backfills, ticker backfills, security-ref augmentation) that must not revert prod drift on columns outside the enrichment scope.

The design fits cleanly as an additive `--mode null-only` path in `merge_staging.py`. `promote_staging.py` is a separate code path and is **not** the natural home — it operates only on the entity MDM + canonical `PROMOTABLE_TABLES` allowlist, whereas the sector-coverage use case targets `market_data`, which routes through `merge_staging.py`.

Recommendation: proceed to Phase 1 with the scoped design in §4.

---

## §2. Current merge modes in `merge_staging.py`

File: [scripts/merge_staging.py](../../scripts/merge_staging.py). HEAD commit post-mig-13 (`4ced172`), post-PR #63 cleanup.

### 2.1 Mode dispatch

Single entry point [`merge_table()` at :80](../../scripts/merge_staging.py:80) switches on `pk_cols`:

| `pk_cols` | Mode | SQL pattern | Lines |
|---|---|---|---|
| `list[str]` | PK upsert | `DELETE FROM t WHERE EXISTS (...staging PK match); INSERT INTO t SELECT shared_cols FROM staging` | [:131-147](../../scripts/merge_staging.py:131) |
| `None` | Full replace | `DROP TABLE t; CREATE TABLE t AS SELECT shared_cols FROM staging` | [:148-158](../../scripts/merge_staging.py:148) |

`pk_cols` is looked up from `TABLE_KEYS[table]` at [:252](../../scripts/merge_staging.py:252). `TABLE_KEYS` is loaded from the registry via [`merge_table_keys()` at scripts/pipeline/registry.py:355](../../scripts/pipeline/registry.py:355) with two overrides ([:54-55](../../scripts/merge_staging.py:54)) for the `_cache_openfigi` + `_cache_yfinance` infrastructure caches.

### 2.2 Column intersection semantics

[:103-107](../../scripts/merge_staging.py:103): columns are matched by **name**. `shared_cols = staging_cols ∩ prod_cols`. Staging-only columns warn + are dropped. Prod-only columns:

- **Claimed behaviour** (comment at [:101-102](../../scripts/merge_staging.py:101)): *"preserved (left untouched for replaced rows via UPDATE semantics; left NULL on newly inserted rows)."*
- **Actual behaviour**: DELETE removes the row entirely at [:133-139](../../scripts/merge_staging.py:133), then INSERT at [:140-143](../../scripts/merge_staging.py:140) supplies only `shared_cols`. Prod-only columns default to NULL on all replaced rows, not just newly-inserted ones. **The code does not use UPDATE semantics.** This is a latent documentation bug worth correcting in Phase 1 (out of scope for the INF30 fix itself but should ride along).

### 2.3 CLI interface

[:162-178](../../scripts/merge_staging.py:162):

| Flag | Purpose |
|---|---|
| `--all` | Merge every staging table. Destructive — full-replaces tables not in `TABLE_KEYS`. |
| `--i-really-mean-all` | Required guard for `--all` (INF10, 2026-04-10). |
| `--tables T1,T2,...` | Explicit table list (preferred). |
| `--dry-run` | Read-only preview; attaches both DBs read-only at [:235-238](../../scripts/merge_staging.py:235). |
| `--drop-staging` | Delete staging DB after successful merge, retained on errors ([:285-289](../../scripts/merge_staging.py:285)). |

Error handling [:249, :271-275, :293-298](../../scripts/merge_staging.py:249) collects per-table failures and exits non-zero at the end (mig-13 PR #63 fix).

---

## §3. `promote_staging.py` is a separate code path

File: [scripts/promote_staging.py](../../scripts/promote_staging.py).

### 3.1 No call into `merge_staging.py`

`promote_staging.py` does not import or invoke `merge_staging.py`. It opens its own DuckDB connection ([:545](../../scripts/promote_staging.py:545)), ATTACHes staging as `stg` ([:546](../../scripts/promote_staging.py:546)), and implements its own diff/apply via [`_apply_table()` at :326](../../scripts/promote_staging.py:326) and [`_apply_table_rebuild()` at :310](../../scripts/promote_staging.py:310).

### 3.2 `PROMOTE_KIND` dispatch (INF11, shipped `b13d5f8`)

[:122-126](../../scripts/promote_staging.py:122):

```python
PROMOTE_KIND = {
    "managers": "rebuild",
    "cik_crd_links": "rebuild",
}
```

Default is `"pk_diff"` (see `_kind_for()` at [:129-131](../../scripts/promote_staging.py:129)). Two strategies today:

- `pk_diff` — PK-keyed DELETE-modified / INSERT-new via EXCEPT queries ([:326-417](../../scripts/promote_staging.py:326)).
- `rebuild` — DROP + CTAS from staging ([:310-323](../../scripts/promote_staging.py:310)).

Both operate on full-row content. Neither preserves prod drift on unshared columns.

### 3.3 Why NULL-only belongs in `merge_staging.py`, not `promote_staging.py`

`promote_staging.py`'s scope is the `PROMOTABLE_TABLES` allowlist ([scripts/db.py:141](../../scripts/db.py:141)) — entity MDM + canonical reference tables (`cusip_classifications`, `securities`, `parent_bridge`, `cik_crd_direct`, `managers`, `cik_crd_links`, `fund_classes`, `lei_reference`, `benchmark_weights`). The INF30 motivating case is **`market_data`** enrichment (see §1 closeout reference), which is not in `PROMOTABLE_TABLES` and routes through `merge_staging.py`.

- `market_data` is registry-resident with `promote_strategy = "direct_write"` per [scripts/pipeline/registry.py:369-371](../../scripts/pipeline/registry.py:369); `merge_table_keys()` returns its PK.
- Future enrichment blocks flagged in the closeout (`BLOCK-TICKER-BACKFILL`, future sector refreshes) all target data-layer tables that `merge_staging.py` owns.

Fitting NULL-only into `promote_staging.py` as a new `PROMOTE_KIND` would require first extending `PROMOTABLE_TABLES` to cover `market_data` — that is a larger architectural change (widening the entity-grade snapshot + validator workflow to data tables) and should not ride on INF30. **Phase 1 scope is `merge_staging.py` only.** A follow-on could add a `"null_only"` kind to `PROMOTE_KIND` for symmetry if a future promotion case needs it.

---

## §4. Design — NULL-only mode

### 4.1 SQL pattern

For each `(pk, col)` tuple, the write is:

```sql
UPDATE "{table}" AS p
SET "{col}" = s."{col}"
FROM staging_db."{table}" AS s
WHERE {pk_join}                          -- p.pk1 = s.pk1 AND p.pk2 = s.pk2 …
  AND p."{col}" IS NULL
  AND s."{col}" IS NOT NULL
```

Properties:
- **Preserves prod drift** on every column except the target set.
- **Monotone** — NULL → value; never reverts value → NULL, never overwrites value → value.
- **Idempotent** — a second run writes zero rows because all target cells are now non-NULL.
- **PK-required** — target table must have `TABLE_KEYS[t] != None` (a list). Full-replace tables (`pk_cols = None`) cannot participate; they would require a different row-identity concept.

One UPDATE per column keeps the SQL trivially composable and the row-count attribution per column clean for the summary output.

### 4.2 CLI surface (proposed)

```
python3 scripts/merge_staging.py \
  --tables market_data \
  --mode null-only \
  --columns sector,industry \
  [--dry-run] [--drop-staging]
```

| Flag | Required? | Notes |
|---|---|---|
| `--mode {pk_upsert,null_only}` | optional, default `pk_upsert` | `pk_upsert` is the current path; `null_only` opts into the new path. Using the `--mode` name avoids boolean-flag sprawl and leaves room for a future `update_only` or `append_only` mode. |
| `--columns col1,col2,...` | **required with `--mode null-only`** | Explicit column allowlist. No implicit "all columns" default — the INF30 motivation is narrow enrichment, and an all-column default invites the same blast-radius problem the mode is designed to avoid. |
| `--tables` | **required with `--mode null-only`** | `--all` is rejected with `--mode null-only` (cross-table column lists don't compose). |
| `--dry-run` | supported | See §4.3. |
| `--drop-staging` | supported | Same semantics. |

Validation at parse time:
- `--columns` not permitted with `--mode pk_upsert` (current path).
- `--columns` required with `--mode null-only`; error if missing.
- `--all` rejected with `--mode null-only`.
- `--mode null-only` rejected if any named table has `TABLE_KEYS[t] is None` (full-replace tables).
- Every column in `--columns` must exist in both staging and prod for every named table (hard fail with a clear message listing the offending (`table`, `col`) pairs).

### 4.3 Dry-run behaviour

`--dry-run --mode null-only` should print, per `(table, column)`:

| Column | Count |
|---|---:|
| `prod_null_rows` | prod rows where col IS NULL with a matching staging PK |
| `staging_nonnull_rows` | of those, staging provides a non-NULL value |
| `would_write` | `staging_nonnull_rows` — the actual UPDATE count |
| `unchanged_prod_nonnull` | prod rows where col IS NOT NULL (preserved) |

Query shape:

```sql
SELECT
  SUM(CASE WHEN p.{col} IS NULL                             THEN 1 ELSE 0 END) AS prod_null_rows,
  SUM(CASE WHEN p.{col} IS NULL AND s.{col} IS NOT NULL     THEN 1 ELSE 0 END) AS would_write,
  SUM(CASE WHEN p.{col} IS NOT NULL                         THEN 1 ELSE 0 END) AS unchanged_prod_nonnull
FROM {table} p
JOIN staging_db.{table} s ON {pk_join}
```

Read-only; both DBs attached with `READ_ONLY` per existing `--dry-run` at [:235-238](../../scripts/merge_staging.py:235).

### 4.4 Interaction with existing modes

- **Orthogonal dispatch.** `--mode null-only` short-circuits `merge_table()` at entry and takes a dedicated `merge_table_null_only()` path. The PK-upsert path at [:131-147](../../scripts/merge_staging.py:131) and full-replace path at [:148-158](../../scripts/merge_staging.py:148) are untouched.
- **Same column-intersection guard.** Staging-only columns still warn and drop (irrelevant to null-only, but keeps the surface consistent).
- **Error aggregation.** Reuse the per-table error list + non-zero exit at [:271-298](../../scripts/merge_staging.py:271).
- **No registry change required** for Phase 1 — the mode is a per-invocation flag, not a per-table policy. If a future block wants a table's pipeline to default to NULL-only, the registry would need a `merge_strategy` extension; that is out of scope here.

### 4.5 Not in scope for Phase 1

- Extending `promote_staging.py`'s `PROMOTE_KIND` with `"null_only"` (possible follow-on, not needed for INF30's motivating use case — see §3.3).
- Per-row predicate modes (`WHERE cond` beyond `col IS NULL`). The closeout [§7](../reports/block_sector_coverage_closeout_20260419_052804.md) explicitly scopes the narrow variant first: *"The narrower variant (column-scoped upsert with NULL-only guard) covers every data-enrichment block ... The broader variant (arbitrary predicate) can come later."*
- Fixing the doc-vs-behaviour lie at [:101-102](../../scripts/merge_staging.py:101) about UPDATE semantics — flagged for a ride-along comment correction during Phase 1 but not the reason the change is being made.
- Schema-parity interaction with INF39 (already shipped as `make schema-parity-check` pre-flight). NULL-only mode still wants the parity gate to be green beforehand, but that is the caller's concern, not a new coupling.

---

## §5. Existing logic survey

Grep over `merge_staging.py` for `NULL|null_only|column_scoped|COALESCE`:

- [:86](../../scripts/merge_staging.py:86), [:102](../../scripts/merge_staging.py:102) — comments about prod-only column NULL behaviour. No code.
- No `COALESCE`, no `null_only`, no `column_scoped`. **No pre-existing NULL-only or column-scoped logic exists.** Phase 1 is greenfield.

No prior-art implementation in `promote_staging.py` either (grep confirms — no COALESCE-driven path; `_apply_table()` and `_apply_table_rebuild()` are full-row content operators).

---

## §6. Resolution path

Recommend proceeding to Phase 1 with the design in §4. Phase 1 work:

1. Add `merge_table_null_only()` implementation in `scripts/merge_staging.py`.
2. Extend argparse with `--mode`, `--columns`, and the four validation rules in §4.2.
3. Extend dry-run output formatting with the four-column per-(table, col) breakdown in §4.3.
4. Fix the latent UPDATE-semantics comment lie at [:101-102](../../scripts/merge_staging.py:101) as a ride-along.
5. Test coverage: unit tests on a scratch DuckDB with (a) baseline prod-NULL + staging-non-NULL → writes, (b) prod-non-NULL + staging-non-NULL → preserved, (c) prod-NULL + staging-NULL → noop, (d) PK-mismatch → untouched, (e) idempotency (second run writes zero).
6. Callsite: no immediate `run_pipeline.sh` change — the mode is opt-in. The motivating sector-coverage path currently runs ad-hoc; wiring it into a documented enrichment target is a follow-on (possibly INF30 Phase 2, or scope-separated as "sector-refresh runbook").

### Phase 1 risk assessment

- **Blast radius:** zero by construction — the new path is monotone (never overwrites a non-NULL), idempotent, and gated behind opt-in flags. It cannot be invoked by existing callsites.
- **Backwards-compatibility:** none broken. The default remains PK upsert; `--mode null-only` is additive.
- **Rollback:** trivial — revert the PR. No data migration, no schema change.

### Scope boundary with neighbouring items

- **INF11 `PROMOTE_KIND` (shipped `b13d5f8`)** — `promote_staging.py` layer. Orthogonal; no code overlap.
- **mig-14 `build_managers` INF1 routing** — touches `promote_staging.py` / `PROMOTE_KIND` only. No collision — see [docs/findings/mig-14-p0-findings.md §3](./mig-14-p0-findings.md).
- **sec-05 Phase 1 fund_classes + benchmark_weights staging** — explicitly routed through `promote_staging.py` to avoid int-14 collision — see [docs/findings/sec-05-p0-findings.md §3](./sec-05-p0-findings.md).
- **int-15 `market_data.fetch_date` discipline** — different semantic question (when `fetch_date` should change on touchless updates); can share a runbook with int-14 once both ship but no shared code.

---

## §7. Verification artefacts (reproducible)

Confirm no existing NULL-only logic:

```bash
rg -n 'NULL|null_only|column_scoped|COALESCE' scripts/merge_staging.py
# Expected: only comments at lines 86 and 102, no code.
```

Confirm current mode dispatch:

```bash
rg -n 'if pk_cols' scripts/merge_staging.py
# Expected: matches at :110 (dry-run branch) and :131 (write branch).
```

Confirm `promote_staging.py` does not call `merge_staging.py`:

```bash
rg -n 'merge_staging' scripts/promote_staging.py
# Expected: no matches.
```

Confirm `PROMOTE_KIND` current shape:

```bash
rg -n 'PROMOTE_KIND\s*=' scripts/promote_staging.py
# Expected: single match at :122; contents {"managers": "rebuild", "cik_crd_links": "rebuild"}.
```

Confirm `market_data` routes via `merge_staging.py` (not `promote_staging.py`):

```bash
python3 -c "
from scripts.pipeline.registry import merge_table_keys
mtk = merge_table_keys()
print('market_data in merge_table_keys:', 'market_data' in mtk, mtk.get('market_data'))
"
# Expected: True, ['ticker', 'as_of'] (or similar PK list).

python3 -c "
import sys; sys.path.insert(0, 'scripts')
import db
print('market_data in PROMOTABLE_TABLES:', 'market_data' in db.PROMOTABLE_TABLES)
"
# Expected: False.
```

---

## §8. Summary

| Question | Answer |
|---|---|
| Current modes in `merge_staging.py`? | Two: PK upsert (`DELETE`+`INSERT`), full replace (`DROP`+`CTAS`). |
| Any pre-existing NULL-only / column-scoped logic? | None. Greenfield. |
| Does `promote_staging.py` share code with `merge_staging.py`? | No. Separate code paths. |
| Natural home for NULL-only mode? | `merge_staging.py`. `market_data` (motivating case) is not in `PROMOTABLE_TABLES`. |
| Recommended CLI surface? | `--mode null-only --columns c1,c2 --tables t` with hard-fail validation. |
| Dry-run design? | Per-`(table, col)` four-column breakdown: prod_null, would_write, unchanged_prod_nonnull, (derived) noop. |
| Blast radius? | Zero — monotone, idempotent, opt-in, PK-keyed. |
| Blockers? | None. Proceed to Phase 1. |
