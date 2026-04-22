# mig-13-p0 — Phase 0 findings: pipeline-violations REWRITE tail (scope verification)

_Prepared: 2026-04-21 — branch `mig-13-p0` off main HEAD `c3590d0`._

_Tracker: `docs/REMEDIATION_PLAN.md` Theme 3 row `mig-13` (Batch 3-B). Already-narrowed scope at PLAN:132 to `build_entities`, `merge_staging`. This Phase 0 verifies that narrowing against HEAD and recommends Phase 1 shape._

Phase 0 is investigation only. No code writes, no DB writes. READ-ONLY inspection + one read-only DuckDB probe against `data/13f.duckdb`.

---

## §1. Scope and method

**Scope.** The 5 scripts originally listed under `mig-13` in `docs/pipeline_violations.md`: `fetch_adv.py`, `build_fund_classes.py`, `build_benchmark_weights.py`, `build_entities.py`, `merge_staging.py`.

**Method.** Read-only inspection of each script at HEAD; cross-reference with `docs/pipeline_violations.md`, `docs/REMEDIATION_PLAN.md`, and the sibling findings docs `docs/findings/mig-02-p0-findings.md` (PR #37) and `docs/findings/sec-05-p0-findings.md` (PR #45). Confirmed closure commits via `git log --oneline`. One read-only DuckDB probe of `information_schema.tables` to confirm legacy-table presence/absence.

No runtime writes. No pipeline runs.

---

## §2. Per-script status at HEAD

| Script | Original mig-13 scope | Closure vehicle | Current status | Remaining violations |
|---|---|---|---|---|
| `fetch_adv.py` | REWRITE §1/§2/§5/§9 | **mig-02 (PR #37, commit `db1fdb8`)** | CLOSED | None. Staging→promote adopted; see §2.1. |
| `build_fund_classes.py` | REWRITE §1/§5/§9 + legacy refs | **sec-05 (PR #45, commit `742d504`)** | CLOSED | None material to mig-13; see §2.2. |
| `build_benchmark_weights.py` | REWRITE §1/§5/§9 + legacy refs + BROKEN IMPORT | **sec-05 (PR #45, commit `742d504`)** | CLOSED | None material to mig-13; see §2.3. |
| `build_entities.py` | RETROFIT §1/§9-partial | — | **OPEN** | §1 only: no per-step CHECKPOINT. See §2.4. |
| `merge_staging.py` | RETROFIT §5 + legacy refs | partial (`c2fb215` INF10 gate) | **OPEN** | §5 masked errors + stale `TABLE_KEYS` entries. See §2.5. |

### 2.1 `fetch_adv.py` — CLOSED

Verified at HEAD: imports `STAGING_DB` from `db` ([scripts/fetch_adv.py:36](scripts/fetch_adv.py:36)); the write site is a single `CREATE OR REPLACE TABLE adv_managers AS SELECT * FROM df_out` against staging ([scripts/fetch_adv.py:259-260](scripts/fetch_adv.py:259)); staging CHECKPOINT at :280; three short-lived manifest/impact connections also route to `STAGING_DB` ([:295](scripts/fetch_adv.py:295), [:341](scripts/fetch_adv.py:341), [:356](scripts/fetch_adv.py:356)). Prod promote lives in `promote_adv.py`. The four original §-violations from `pipeline_violations.md:122-134` are resolved.

### 2.2 `build_fund_classes.py` — CLOSED

PR #45 (commit `742d504`) added:
- `db.seed_staging()` invocation when `--staging`
- `fund_holdings_v2` added to `REFERENCE_TABLES`
- `fund_classes`, `lei_reference` added to `CANONICAL_TABLES` with pk_diff promote kind
- `--enrichment-only` mode that isolates the `fund_holdings_v2.lei` ALTER+UPDATE from the staging-safe path
- Freshness stamp deferred out of the staging call site

Remaining from `pipeline_violations.md:324-334`:
- §1 (incremental save — "weak CHECKPOINT every 5000 XMLs") — unchanged. Pre-existing, not a mig-13 RETROFIT item. The 5000-row cadence is acceptable for N-PORT XML volume given the staging safety rail.
- §5 (silent parse failures at `:53`/`:133`) — unchanged, tracked as parser hygiene, not a staging-first blocker.

Net effect: the "no `--staging` plumbing" and "legacy `fund_holdings` ALTER+UPDATE on prod surface" concerns that put this script into `mig-13` are gone.

### 2.3 `build_benchmark_weights.py` — CLOSED

PR #45 also added `db.seed_staging()` invocation when `--staging` and registered `benchmark_weights` in `CANONICAL_TABLES` with pk_diff promote kind on `(index_name, gics_sector, as_of_date)`. The "BROKEN IMPORT" note in `pipeline_violations.md:353-356` was already cleared in an earlier session (D11) via a local `get_connection()` wrapper.

Remaining from `pipeline_violations.md:351-362`:
- §5 (minimal error handling on empty benchmark fund data) — unchanged; low-risk given staging gate.
- §1 (no CHECKPOINT) — the benchmark_weights table is ≈50 rows per quarter × 11 GICS sectors; end-of-run CHECKPOINT is sufficient given the volume.

Net effect: the staging-routing concern that put this script into `mig-13` is gone.

### 2.4 `build_entities.py` — OPEN (narrowed)

Inspected at HEAD. Current state:
- `--reset` flag at [scripts/build_entities.py:964](scripts/build_entities.py:964); `--refresh-reference-tables` flag at [:965-968](scripts/build_entities.py:965).
- `db.set_staging_mode(True)` unconditional at [:971](scripts/build_entities.py:971) — staging-only safety rail.
- Single CHECKPOINT + `record_freshness("entity_rollup_history")` at [:1015-1016](scripts/build_entities.py:1015), at end of all 7 build steps, guarded by try/except.
- Per-step try/except to `CONFLICT_LOG` — idempotent.

Remaining violation from `pipeline_violations.md:338-348`:
- **§1 (incremental save)**: no CHECKPOINT inside any of the 7 build steps (`step2_seed_parents`, `step2_create_manager_entities`, `step2_create_fund_entities`, `step3_populate_identifiers`, `step4_populate_relationships`, `step5_populate_aliases`, `step6_populate_classifications`, `step7_compute_rollups`, plus `replay_persistent_overrides`). Large INSERT chains flush only at close.

§9 is partial but acceptable: staging-only via `set_staging_mode(True)` is the safety rail; promotion to prod always goes through `promote_staging.py`, which is gated. No `--dry-run` is warranted because the script cannot touch prod.

**Complexity rating.** **Trivial.** Drop an `con.execute("CHECKPOINT")` at the end of each step function (or have `main()` call it after each `stepN_*` invocation). No DDL, no semantic change. Single-session.

### 2.5 `merge_staging.py` — OPEN (narrowed)

Inspected at HEAD. Current state:
- `--dry-run` at [scripts/merge_staging.py:195](scripts/merge_staging.py:195) — live.
- `--all --i-really-mean-all` gate at [:183-215](scripts/merge_staging.py:183) — shipped INF10 (commit `c2fb215`).
- CHECKPOINT after merge at [:293](scripts/merge_staging.py:293).
- Per-table try/except at [:284-290](scripts/merge_staging.py:284) — prints `ERROR: {e}` and continues to the next table.

Remaining violations from `pipeline_violations.md:452-463`:

1. **§5 (error handling)**: the per-table try/except at `:289` swallows exceptions, prints the error, and continues. A failed merge of `beneficial_ownership` (or any other table) does not halt the script or set a non-zero exit code. Can mask real failures during automated pipeline runs.

2. **Legacy / stale `TABLE_KEYS` entries**:
    - [`:45`](scripts/merge_staging.py:45) `"beneficial_ownership": ["accession_number"]` — `beneficial_ownership` was dropped Stage 5. Read-only `information_schema.tables` probe 2026-04-21 against prod `data/13f.duckdb` confirms only `beneficial_ownership_v2` exists. If anyone passes `--tables beneficial_ownership`, the DELETE+INSERT at `:152-162` would target a non-existent table and fall into the try/except at `:284-290` — silent failure per §5 above.
    - [`:51`](scripts/merge_staging.py:51) `"fund_holdings": None` — `fund_holdings` still exists alongside `fund_holdings_v2` in prod. The `None` value routes through the DROP+CTAS branch at `:168-177`, which would full-replace prod `fund_holdings` from staging — a destructive path for a table the v2 pipeline owns. Not currently invoked by `run_pipeline.sh` (per INF10 context) but the entry remains a landmine.

3. **Recommended Phase 1 fix from `pipeline_violations.md:462-463`**: derive `TABLE_KEYS` from `scripts/pipeline/registry.merge_table_keys()`. Registry function exists at [scripts/pipeline/registry.py:355](scripts/pipeline/registry.py:355) and is already named as the dispatch source in the module header (`:6`). Ship the swap + drop the hand-maintained dict.

**Complexity rating.** **Trivial.** Two changes:
- Replace `TABLE_KEYS = {...}` with `from pipeline.registry import merge_table_keys; TABLE_KEYS = merge_table_keys()`.
- Convert the per-table try/except at `:284-290` into either (a) raise-with-summary-at-end, or (b) collect errors and exit non-zero if any. Preserve the dry-run contract (errors stay warnings in `--dry-run`). Single-session.

---

## §3. Revised mig-13 scope

### 3.1 Items to drop from scope (already closed)

| Script | Closure reference |
|---|---|
| `fetch_adv.py` | mig-02 / PR #37 / commit `db1fdb8` |
| `build_fund_classes.py` | sec-05 / PR #45 / commit `742d504` |
| `build_benchmark_weights.py` | sec-05 / PR #45 / commit `742d504` |

These are already acknowledged as closed in `docs/REMEDIATION_PLAN.md:132` — this finding confirms that narrowing is still accurate at HEAD.

### 3.2 Items still in scope

| Script | Remaining work | Est. effort |
|---|---|---|
| `build_entities.py` | Add per-step CHECKPOINT in `main()` (or inside each `stepN_*`) for §1 compliance. | Trivial, 1 session |
| `merge_staging.py` | (a) Derive `TABLE_KEYS` from `pipeline.registry.merge_table_keys()`; (b) halt/exit-nonzero on per-table errors instead of swallowing. | Trivial, 1 session |

### 3.3 Recommendation

**Keep `mig-13` OPEN with the already-narrowed scope at `REMEDIATION_PLAN.md:132`.** Both remaining items are trivial (each single-session), disjoint from each other, and disjoint from all other open items in Theme 3. They can ship in a single combined Phase 1 PR under `mig-13` or split as two tiny PRs at the author's discretion.

**Do not close `mig-13` as already-satisfied.** Neither remaining violation would be addressed by any other open item:
- `build_entities.py` CHECKPOINT is not touched by `mig-14` (which concerns `build_managers.py` staging routing).
- `merge_staging.py` `TABLE_KEYS` drift + swallowed errors are not touched by `int-14` (which concerns NULL-only merge semantics, a different code path) or by `sec-06` (which retired 3 resolver scripts but left `merge_staging.py` alone).

### 3.4 Phase 1 file list

```
scripts/build_entities.py        # add per-step CHECKPOINT
scripts/merge_staging.py         # import TABLE_KEYS from registry + fail-fast error handling
docs/pipeline_violations.md      # mark build_entities §1 CLEARED; merge_staging §5 + legacy-refs CLEARED; drop stale fetch_adv/build_fund_classes/build_benchmark_weights entries (or annotate with closure PRs — consistent with existing CLEARED markers at :36-62)
```

### 3.5 Phase 1 estimated sessions

- **1 session** if both scripts ship together.
- **2 sessions** if split into `mig-13a` (build_entities CHECKPOINT) and `mig-13b` (merge_staging registry + fail-fast).

Recommend combined. No shared code, no merge conflicts, no review-scope concerns.

---

## §4. Sources consulted

- `docs/pipeline_violations.md` (HEAD) — per-script violation ledger
- `docs/REMEDIATION_PLAN.md:115-133` — Theme 3 table with mig-13 already narrowed at :132
- `docs/findings/mig-02-p0-findings.md` — fetch_adv.py closure rationale
- `docs/findings/sec-05-p0-findings.md` — build_fund_classes + build_benchmark_weights closure rationale
- `scripts/fetch_adv.py`, `scripts/build_fund_classes.py`, `scripts/build_benchmark_weights.py`, `scripts/build_entities.py`, `scripts/merge_staging.py` at HEAD
- `scripts/pipeline/registry.py:355` — `merge_table_keys()` helper that the Phase 1 fix should consume
- `git log --oneline -30` — commits `db1fdb8` (mig-02 PR #37) and `742d504` (sec-05 PR #45) confirmed as landed ancestors of HEAD `c3590d0`
- One read-only DuckDB probe of `data/13f.duckdb` `information_schema.tables` confirming `beneficial_ownership_v2` (not `beneficial_ownership`) and `fund_holdings` co-exists with `fund_holdings_v2`
