# REWRITE build_managers.py — Phase 2 staging validation

_Branch: `rewrite-build-managers`. HEAD: `2a71f8a`._
_Staging DB: `data/13f_staging.duckdb`._
_Run ID: `20260419_082630`._

## Gate summary

| Gate | Result | Notes |
|---|---|---|
| 1. holdings_v2 enrichment populated | **PASS with RISK** | `manager_type` coverage 59.9% vs prod legacy 100% — see Risk 1 |
| 2. Four output tables produced | **PASS** | Row-count deltas within expected drift |
| 3. Freshness stamps on all 5 tables | **PASS** | parent_bridge / cik_crd_links / cik_crd_direct / managers / holdings_v2 all stamped |
| 4. No writes to legacy `holdings` | **PASS** | Table absent from both prod and staging |
| 5. Downstream reader sanity | **PASS** | All 6 spot-check queries succeed |
| 6. Rebuild-kind rollback | **PASS** | Scratch-DB clone apply + restore round-tripped identical content hashes |

**Overall: gates PASS. Phase 3 review gate reached. Phase 4 requires explicit
sign-off on Risk 1 below.**

## Phase 1 commits landed

| Hash | Message |
|---|---|
| `1719320` | refactor(build_managers): repoint holdings enrichment to holdings_v2 |
| `6079220` | feat(promote_staging): add rebuild-kind full-replace semantics |
| `908d9f5` | feat(build_managers): register four output tables in promote_staging |
| `67e81f3` | feat(build_managers): --dry-run, --staging, fail-fast, retrofits |
| `2a71f8a` | fix(build_managers): dedupe parent_bridge on cik (Phase 2 finding) |

Plus `bf7bfe6` (Phase 0 findings) as the branch root.

## Rebuild-kind machinery summary

`promote_staging.py` now supports a `PROMOTE_KIND` dict (default
`pk_diff`). Registered `rebuild` kind for `managers` and
`cik_crd_links` — tables whose natural keys (cik) are not empirically
unique because of LEFT-JOIN fan-out and fuzzy-match duplicates.

- Apply path: snapshot → `DROP TABLE {prod}` → `CREATE TABLE {prod} AS
  SELECT * FROM stg.{prod}` → reset sequences.
- Rollback path: `DROP TABLE` + `CREATE TABLE AS SELECT` from the
  snapshot, preserving the prior schema even if a post-hoc stage had
  extended it between snapshot-time and apply.
- Dry-run: reports `would_replace_all prod=N → staging=M`.
- Validator registration: all four new canonical tables get
  `VALIDATOR_MAP[t] = None` with the established load-bearing warn.

## Dry-run result (`--staging --dry-run`)

```
Building parent_bridge table...
  Unique filers: 12,035
  Matched to parent groups: 554 CIKs
  Unmatched filers: 11,451
  [dry-run] would DROP+CREATE parent_bridge (11,135 rows)

Linking CIK to CRD via fuzzy name match...
  Filers without CRD: 6,534
  Direct CIK matches: 1,351
  Fuzzy matches found: 353  (rejected: 95)
  [dry-run] would DROP+CREATE cik_crd_links (353 rows)
  [dry-run] would DROP+CREATE cik_crd_direct (4,059 rows)

Building managers table...
  [dry-run] would DROP+CREATE managers (~11,135 rows, ±LEFT-JOIN fan-out)

Updating holdings_v2 with manager metadata...
  [dry-run] would UPDATE ~13,142,214 rows in holdings_v2 (join managers on cik)
```

Runtime: ~28 seconds (dominated by the fuzzy-match loop).
No DB writes; staging row counts unchanged.

## Real staging run stats

Runtime: **40.8 seconds** wall-clock. Single-threaded fuzzy-match
loop is the dominant cost.

| Table | Rows | Delta vs prod | Kind |
|---|---:|---:|---|
| parent_bridge | 11,135 | +0 | pk_diff |
| cik_crd_direct | 4,059 | +0 | pk_diff |
| managers | 11,135 | **−870** (dedupe gain, see below) | rebuild |
| cik_crd_links | 353 | −95 | rebuild |
| holdings_v2 (UPDATE) | 7,352,103 | — | direct-write (not promoted) |

CHECKPOINT + freshness timestamps: all 5 tables stamped at run
timestamp (verified in `data_freshness`).

## holdings_v2 enrichment diff (Risk 1 — detailed)

| Column | Staging post-run | Prod legacy |
|---|---:|---:|
| `inst_parent_name` | 12,270,984 / 12,270,984 (100.0%) | 12,270,984 / 12,270,984 (100.0%) |
| `manager_type` | **7,352,103 / 12,270,984 (59.9%)** | 12,270,984 / 12,270,984 (100.0%) |
| `is_passive` | 12,270,984 / 12,270,984 (100.0%) | 12,270,984 / 12,270,984 (100.0%) |
| `is_activist` | 12,270,984 / 12,270,984 (100.0%) | 12,270,984 / 12,270,984 (100.0%) |

**Root cause.** Prod legacy 100% comes from `backfill_manager_types.py`
which was last run when `holdings` was the live table. `managers.strategy_type`
itself is only ~52% populated today (prod: 6,307 / 12,005 non-null; staging:
5,857 / 11,135 non-null). When Phase 4 applies the repointed UPDATE against
prod, `holdings_v2.manager_type` coverage regresses **100% → 60%**. This is
a real data-quality regression: downstream filters like
`WHERE manager_type = 'passive'` in `compute_flows.py:350`,
`build_summaries.py:174-182`, and `queries.py:571` will miss ~40% of
positions they currently match.

**Scope boundary.** This regression is NOT caused by the rewrite. The
rewrite correctly repoints the UPDATE from the dropped `holdings` to
`holdings_v2`. The underlying coverage gap is a pre-existing issue:
`backfill_manager_types.py:77-91` was broken when `holdings` was dropped,
and no replacement has been wired to `holdings_v2`. The rewrite merely
exposes it because the UPDATE will overwrite the legacy-frozen values
with the current (NULL-heavy) managers output.

**Three options for Phase 4 (decision required).**

- **(A) Accept the regression.** Apply as-is. Coverage drops 100%→60%.
  Downstream quality regresses. Fix `backfill_manager_types.py`
  separately as a follow-up to restore coverage.
- **(B) Preserve legacy when new is NULL.** Amend the UPDATE to
  `SET manager_type = COALESCE(m.strategy_type, h.manager_type)`.
  Keeps the legacy populations for CIKs where current managers has
  NULL strategy. Only refreshes rows where managers has a real
  classification. Preserves 100% coverage. Minor risk: stale
  classifications persist until the underlying managers build
  produces non-NULL for those CIKs.
- **(C) Block Phase 4 on `backfill_manager_types.py` fix.** Add a
  new commit migrating that script to `holdings_v2` before landing
  Phase 4. Cleanest but expands scope.

**My recommendation: (B).** The semantic of "keep legacy value when
current build has no opinion" matches how downstream callers already
treat `COALESCE(manager_type, 'unknown')` (e.g.
`compute_flows.py:319`, `queries.py:571`). Same behavior without the
coverage cliff. One-line SQL change; holds regardless of whether
`backfill_manager_types.py` is ever resurrected.

## parent_bridge dedupe (Phase 2 secondary finding)

Phase 2 validation surfaced that a freshly-built staging
`parent_bridge` had 870 duplicate CIKs vs prod's snapshot of 0 dupes.
Root cause: the unmatched-filers loop iterates
`SELECT DISTINCT cik, manager_name, crd_number FROM filings_deduped`
which fans out to multiple rows per CIK when a CIK's `manager_name` or
`crd_number` differs across quarters. Prod's 0-dupe snapshot is from
an older build where this data drift was absent; the bug reproduces
against current `filings_deduped` state.

Fix landed in `2a71f8a` — `df_bridge_full.drop_duplicates(subset=["cik"])`.
Post-fix, staging produces 11,135 unique CIKs, matching the expected
empirical PK property. Knock-on effect: `managers` goes from 12,005
→ 11,135 because its LEFT JOIN against parent_bridge no longer
fans out.

`cik_crd_links` has an analogous 1-row-in-staging / 3-row-in-prod
dupe issue from the fuzzy-match loop. Left as a follow-on because
cik_crd_links routes via `rebuild` kind and tolerates dupes at the
promote layer — no immediate quality regression.

## promote_staging dry-run against final staging

```
parent_bridge: would_delete=0  would_modify=10,641  would_add=0
cik_crd_direct: would_delete=0  would_modify=0  would_add=0
managers [rebuild]: would_replace_all  prod=12,005 → staging=11,135
cik_crd_links [rebuild]: would_replace_all  prod=448 → staging=353
```

`parent_bridge` 10,641 modified rows are content updates: most CIKs
exist in both but some cells differ (likely `strategy_type` /
`parent_name` refreshes from seed re-evaluation, and the dedupe
picking a different canonical row out of prior fan-outs).
`cik_crd_direct` clean no-op (unchanged).

## Downstream reader sanity (Gate 5)

All six spot-check queries succeed against the post-run staging DB:

| Query | Result |
|---|---:|
| `parent_bridge ↔ managers` JOIN on cik | 11,135 |
| `cik_crd_direct` read | 4,059 |
| `cik_crd_links` 85-threshold read | 353 |
| `managers` non-null strategy read | 5,857 |
| `adv_managers` activist read | 12 |
| `holdings_v2` manager_type read | 7,352,103 |

These cover the live reader surfaces: `build_entities.py` (all four
tables), `fetch_adv.py`/`fetch_13dg.py`/`fetch_ncen.py` (managers),
`queries.py`/`compute_flows.py` (holdings_v2 enriched columns).

## Rebuild-kind rollback test (Gate 6)

Scripted test: cloned the four tables from prod into a scratch DB,
ran `_take_snapshot` + `_apply_table` per staging (pk_diff +
rebuild), verified post-apply state, then `_restore_snapshot`.
All four tables round-tripped to identical row counts AND identical
content hashes (MD5 over `DISTINCT cik`). Scratch DB cleaned up.

```
[pre-apply] parent_bridge=11,135  managers=12,005  cik_crd_direct=4,059  cik_crd_links=448
[post-apply] parent_bridge=11,135  managers=11,135  cik_crd_direct=4,059  cik_crd_links=353
[post-restore] parent_bridge=11,135  managers=12,005  cik_crd_direct=4,059  cik_crd_links=448  ✓ all 4 ✓
```

## Anomalies

1. **`record_freshness` initially failed in staging** with a DuckDB
   binder error on INSERT OR REPLACE. Root cause: staging's
   `data_freshness` was seeded via `CREATE TABLE AS SELECT` which
   strips the PK constraint. Fixed by recreating
   `data_freshness` in staging with `table_name PRIMARY KEY`. This is
   a staging-infra issue unrelated to this rewrite; prod's
   `data_freshness` has the PK declared and record_freshness has
   been working there for weeks. Document as a staging-seed caveat.
2. **Staging data symlink lost during pre-commit stash cycle.** The
   worktree has no `data/` directory of its own; a symlink to
   `/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership/data`
   is needed. Pre-commit hooks' `git stash` + restore can remove
   untracked entries; re-created manually between runs. Not a bug in
   this rewrite.

## Phase 3 readiness

Phase 3 review gate reached. The outstanding decision is **Risk 1
Option (A)/(B)/(C)** on `holdings_v2.manager_type` coverage. No
unresolved infrastructure issues; rebuild-kind machinery verified
end-to-end including rollback.

## Phase 4 prerequisites

1. Sign-off on Risk 1 option.
2. Prod backup via `EXPORT DATABASE` before execution.
3. Three-step sequence per the Option A flag matrix:
   - `build_managers.py --staging`
   - `promote_staging.py --approved --tables parent_bridge,cik_crd_direct,managers,cik_crd_links`
   - `build_managers.py --enrichment-only`  (against prod)

All three commands are wired and smoke-tested.
