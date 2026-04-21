# mig-01-p0 — Phase 0 findings: atomic promotes + manifest mirror helper

_Prepared: 2026-04-21 — branch `remediation/mig-01-p0` off main HEAD `9878a3a`._

_Tracker: `docs/REMEDIATION_PLAN.md` Theme 3 row `mig-01` (BLOCK-2, §4.1 C-01); `docs/REMEDIATION_CHECKLIST.md` Batch 3-A. Upstream: obs-03-p1 (id_allocator, merged) — the mirror paths already call `reserve_ids`. Downstream: mig-02 (fetch_adv.py same class of problem)._

Phase 0 is investigation only. No code writes and no DB writes were performed. Deliverable: this document + Phase 1 fix recommendation.

---

## §1. Scope and method

**Scope.** `scripts/promote_nport.py`, `scripts/promote_13dg.py`, `scripts/pipeline/manifest.py`, `scripts/pipeline/id_allocator.py`, `scripts/promote_staging.py`. Read-only inspection only.

**Method.** Full-file reads of the five scripts above, plus grep across `scripts/` for `BEGIN TRANSACTION`/`COMMIT`/`ROLLBACK` to inventory the project's existing transaction idioms, plus targeted reads of `scripts/pipeline/shared.py` for `stamp_freshness`/`refresh_snapshot`/`bulk_enrich_bo_filers`/`rebuild_beneficial_ownership_current` (all called from the promote scripts). DuckDB version on this host: **1.4.4** (matches the version used in CI and prod).

No runtime probing — the prompt forbids any write.

---

## §2. Current state — neither promote script is transactional

Neither `promote_nport.py` nor `promote_13dg.py` opens an explicit transaction around its staging→prod writes. Both scripts simply issue a sequence of DELETEs, INSERTs, UPDATEs and intermediate `CHECKPOINT` statements against `prod_con`, relying on DuckDB's implicit auto-commit to persist each statement individually. A crash between two statements in the sequence leaves prod in whatever partial state the preceding statements reached.

For contrast, the adjacent `promote_staging.py` — the entity-layer promoter — **does** wrap its diff-apply phase in `BEGIN TRANSACTION` / `COMMIT` / `ROLLBACK` ([scripts/promote_staging.py:603-616](scripts/promote_staging.py:603)) and does the same for its snapshot restore path ([scripts/promote_staging.py:693-699](scripts/promote_staging.py:693)). The same pattern is used in `build_entities.py` (eleven BEGIN/COMMIT/ROLLBACK blocks), `dm15_layer2_apply.py`, `build_cusip.py`, `normalize_securities.py`, and `build_classifications.py`. The promote-fact-tables path is the outlier.

### 2.1 `promote_nport.py` write sequence ([scripts/promote_nport.py:434-523](scripts/promote_nport.py:434))

Executed in order, each on `prod_con` with no transaction:

1. **Manifest mirror.** `DELETE` from `ingestion_manifest` by `manifest_id` IN (...); `DELETE` from `ingestion_manifest` by `object_key` IN (...); `INSERT INTO ingestion_manifest SELECT * FROM mf` (staging frame) ([promote_nport.py:103-113](scripts/promote_nport.py:103)).
2. **Impacts mirror.** `DELETE FROM ingestion_impacts WHERE manifest_id IN (...) AND promote_status <> 'promoted'`; anti-join in pandas; `reserve_ids()` for `impact_id`; `INSERT INTO ingestion_impacts` ([promote_nport.py:125-166](scripts/promote_nport.py:125)).
3. **Promote scope TEMP table.** `CREATE TEMP TABLE _promote_scope`; `INSERT` the (series_id, report_month) tuples ([promote_nport.py:296-307](scripts/promote_nport.py:296)).
4. **Bulk DELETE + INSERT.** `DELETE FROM fund_holdings_v2 WHERE (series_id, report_month) IN (SELECT ... FROM _promote_scope)`; `INSERT INTO fund_holdings_v2` from staging frame ([promote_nport.py:317-353](scripts/promote_nport.py:317)).
5. **Drop TEMP table.** `DROP TABLE IF EXISTS _promote_scope` ([promote_nport.py:355](scripts/promote_nport.py:355)).
6. **`CHECKPOINT`** ([promote_nport.py:457](scripts/promote_nport.py:457)).
7. **Group 2 enrichment.** One `UPDATE fund_holdings_v2 … FROM (JOIN entity_identifiers …)` scoped to touched `series_id`s ([promote_nport.py:203-238](scripts/promote_nport.py:203)).
8. **Fund-universe upsert.** `DELETE FROM fund_universe WHERE series_id IN (...)`; `INSERT INTO fund_universe` ([promote_nport.py:380-400](scripts/promote_nport.py:380)).
9. **Impacts UPDATE.** `UPDATE ingestion_impacts SET promote_status = 'promoted', rows_promoted = rows_staged, promoted_at = CURRENT_TIMESTAMP WHERE …` ([promote_nport.py:485-510](scripts/promote_nport.py:485)).
10. **`CHECKPOINT`** ([promote_nport.py:511](scripts/promote_nport.py:511)).
11. **`stamp_freshness(prod_con, "fund_holdings_v2")`** and **`stamp_freshness(prod_con, "fund_universe")`** — each issues a `DELETE … INSERT INTO data_freshness` via `db.record_freshness` ([promote_nport.py:513-514](scripts/promote_nport.py:513)).
12. **`CHECKPOINT`** ([promote_nport.py:515](scripts/promote_nport.py:515)).

### 2.2 `promote_13dg.py` write sequence ([scripts/promote_13dg.py:186-334](scripts/promote_13dg.py:186))

Same class of problem, inlined into `main()`:

1. **Manifest mirror.** Inline: `DELETE … WHERE manifest_id IN (...)` + `DELETE … WHERE object_key IN (...)` + `INSERT INTO ingestion_manifest SELECT * FROM mf` ([promote_13dg.py:207-233](scripts/promote_13dg.py:207)).
2. **Impacts mirror.** Inline: `DELETE FROM ingestion_impacts … AND promote_status <> 'promoted'`; pandas anti-join; `reserve_ids()`; `INSERT INTO ingestion_impacts` ([promote_13dg.py:241-294](scripts/promote_13dg.py:241)).
3. **`_promote()`.** `DELETE FROM beneficial_ownership_v2 WHERE accession_number IN (…)`; `INSERT INTO beneficial_ownership_v2 …` ([promote_13dg.py:91-134](scripts/promote_13dg.py:91)).
4. **`CHECKPOINT`** ([promote_13dg.py:298](scripts/promote_13dg.py:298)).
5. **`bulk_enrich_bo_filers`.** Bulk `UPDATE beneficial_ownership_v2 …` for Group 2 entity columns ([promote_13dg.py:306](scripts/promote_13dg.py:306) → [pipeline/shared.py:434](scripts/pipeline/shared.py:434)).
6. **`CHECKPOINT`** ([promote_13dg.py:307](scripts/promote_13dg.py:307)).
7. **`rebuild_beneficial_ownership_current`** — DELETE+INSERT rebuild of `beneficial_ownership_current` ([promote_13dg.py:311](scripts/promote_13dg.py:311) → [pipeline/shared.py:562](scripts/pipeline/shared.py:562)).
8. **`CHECKPOINT`** ([promote_13dg.py:312](scripts/promote_13dg.py:312)).
9. **Three `stamp_freshness` calls** for `beneficial_ownership_v2`, `beneficial_ownership_current`, `beneficial_ownership_v2_enrichment` ([promote_13dg.py:315-327](scripts/promote_13dg.py:315)).
10. **`_update_impacts`** — `UPDATE ingestion_impacts SET promote_status = 'promoted' …` ([promote_13dg.py:148-171](scripts/promote_13dg.py:148)).
11. **`CHECKPOINT`** ([promote_13dg.py:330](scripts/promote_13dg.py:330)).

### 2.3 The in-file docstring claim is aspirational, not enforced

`promote_nport.py`'s CHECKPOINT-granularity header comment claims: _"Partial promotion is no longer a thing — either the whole run commits or nothing does (prod connection closes on error)."_ ([promote_nport.py:2-8](scripts/promote_nport.py:2)). This is **not true as written**. Closing the DuckDB connection on error does not roll back statements that already committed under auto-commit. Every DELETE, INSERT, UPDATE and CHECKPOINT above has independently persisted by the time any later statement raises. The only way "whole run or nothing" holds is an explicit `BEGIN`/`COMMIT` boundary — which is absent.

---

## §3. Partial-state hazards on crash

### 3.1 N-PORT failure modes

| Crash after step (§2.1) | Observable prod state |
|---|---|
| 1 (manifest mirror) | New manifest rows present; `ingestion_impacts` still stale/pending; no holdings replaced. Re-run will re-DELETE+INSERT the same manifest rows — idempotent. |
| 2 (impacts mirror) | Manifest + impacts rows mirrored with `promote_status='pending'`; holdings untouched. Same class as (1). |
| 4 (bulk DELETE+INSERT) partway | **Data loss window.** The DELETE commits before the INSERT. If the INSERT raises, prod has the DELETEd rows removed and no replacements. `fund_holdings_v2` for the in-flight (series, month) tuples is empty. |
| 6 (CHECKPOINT) | Holdings replaced; Group 2 columns still NULL. Dashboards reading `entity_id`/`rollup_entity_id` see NULLs for this run's rows until next enrichment. |
| 7 (enrichment) | `fund_universe` stale for touched series; universe-driven analyses diverge from holdings. |
| 8 (universe upsert) | `ingestion_impacts` still `promote_status='pending'` for already-promoted tuples — the impact-report UI will show this run as unpromoted. Re-running the whole promote is required to flip them, which will re-execute steps 1-8 unnecessarily. |
| 9 (impacts UPDATE) | Stamps missing → `data_freshness` says old `last_computed_at`. Freshness badge (obs-01-p1) will mis-report. |
| 11 (stamps) | Everything committed but CHECKPOINT not called. WAL may still be pending; next crash replays it cleanly, but `refresh_snapshot()` (run after the `try/finally`) copies the WAL-backed file, which may race with a recovering DuckDB. |

The **data-loss window at step 4** is the sharpest edge: a DELETE of up to several hundred thousand holdings rows, followed by an INSERT that can fail on constraint violations, disk-full, or OOM — with no way back.

### 3.2 13D/G failure modes

Same class. The sharp edges:

- **Step 3** (`_promote()`): DELETE of BO v2 rows by accession commits before INSERT. A failed INSERT leaves `beneficial_ownership_v2` missing accessions.
- **Step 7** (`rebuild_beneficial_ownership_current`): full DELETE of `beneficial_ownership_current` followed by INSERT FROM SELECT. A mid-rebuild crash leaves the "current" view empty or half-populated — the dashboard view depended on by the UI becomes incoherent.
- **Step 10** (`_update_impacts`): impacts still `pending` even though prod has the rows; validator and impact-report UI will disagree.

### 3.3 `reserve_ids` under a transaction — no hazard

`reserve_ids` ([pipeline/id_allocator.py:132-160](scripts/pipeline/id_allocator.py:132)) takes an exclusive `fcntl.flock` on `data/.ingestion_lock`, reads `MAX(impact_id) + 1` from the **live prod connection**, and returns a `range` object. It does **not** write anything. If the caller's transaction rolls back after the reserve, no prod state has been allocated or committed — the next caller re-reads `MAX+1` correctly. Wrapping the mirror path in a transaction is safe w.r.t. `reserve_ids`. The advisory lock is released when `reserve_ids` returns, which is appropriate: the lock serializes allocation, not the INSERT that follows.

---

## §4. Duplicated mirror code

### 4.1 Inventory

`_mirror_manifest_and_impacts` lives as a private function in `promote_nport.py` ([promote_nport.py:82-167](scripts/promote_nport.py:82)) and is duplicated inline in `promote_13dg.py:main()` ([promote_13dg.py:207-294](scripts/promote_13dg.py:207)). Line-by-line the two paths diverge only in three places:

1. **Source-type filter.** N-PORT filters manifest rows by `source_type = 'NPORT'`; 13D/G does not filter by `source_type` but instead picks up manifest rows by the set of `manifest_id`s present in the staged BO rows ([promote_13dg.py:207-212](scripts/promote_13dg.py:207)).
2. **Manifest-selection entry point.** N-PORT enters via `(run_id, source_type='NPORT')`; 13D/G enters via `manifest_ids from rows["manifest_id"]`.
3. **Return signature.** N-PORT returns `(mf_ids, im_rows)`; 13D/G discards both (just runs the mirror as a side-effect).

Everything else is character-for-character identical: the DELETE-manifest-by-id + DELETE-manifest-by-object_key double-delete pattern, the `INSERT INTO ingestion_manifest SELECT * FROM mf` register/unregister dance, the `DELETE … WHERE promote_status <> 'promoted'` audit-preservation carve-out, the pandas anti-join on `(manifest_id, unit_type, unit_key_json)`, the `reserve_ids` call, and the `INSERT INTO ingestion_impacts SELECT * FROM im` tail.

### 4.2 Proposed extraction

**Destination:** `scripts/pipeline/manifest.py`. That module is already the single source of truth for `ingestion_manifest`/`ingestion_impacts` access (its docstring: _"Direct INSERTs into either table outside this module are a design violation"_ — [pipeline/manifest.py:1-7](scripts/pipeline/manifest.py:1)). A new `promote.py` module is unnecessary — the mirror is definitionally a manifest-layer operation.

**Signature:**

```python
def mirror_manifest_and_impacts(
    prod_con: Any,
    staging_con: Any,
    run_id: str,
    source_type: str,  # 'NPORT' | '13DG' | future source types
) -> tuple[list[int], int]:
    """Mirror this run's manifest + impacts rows staging → prod.

    Returns (manifest_ids, impacts_inserted). Caller uses manifest_ids to
    scope subsequent fact-table writes; impacts_inserted is logged.

    Audit-preservation: prod impacts already `promote_status='promoted'`
    are left untouched. See the 2026-04-17 bugfix in promote_nport.py.

    obs-03 Phase 1: impact_ids are reserved via the central allocator; the
    staging-origin PK never lands in prod.
    """
```

Filtering manifest rows by `source_type` unifies both call-sites: N-PORT passes `'NPORT'`, 13D/G passes `'13DG'` — 13D/G's current `manifest_ids from rows` pattern is equivalent because staging only ever carries one source_type at a time per run.

**Caller migration.**

- `promote_nport.py`: replace lines 82-167 with `from pipeline.manifest import mirror_manifest_and_impacts` and one call site at line 442 (drop the unused `_impact_rows`).
- `promote_13dg.py`: replace lines 207-294 with one call. The `manifest_ids` return value drives the `_promote()` scope that follows.

### 4.3 Risk: `reserve_ids` is inside the helper, the helper is inside the transaction

Keep the `reserve_ids` call inside the extracted helper. The only wrinkle is that `reserve_ids` opens its advisory lock on a path derived from `current_database()` ([id_allocator.py:76-79](scripts/pipeline/id_allocator.py:76)) — which at the moment of the call is prod — so concurrent promotes (not a documented case, but possible in operator error) serialize on the same lock file. This is the intended behaviour; Phase 1 changes nothing here.

---

## §5. DuckDB transaction semantics — what Phase 1 can rely on

DuckDB 1.4.4 (host-confirmed) supports explicit multi-statement transactions with full rollback across both DML and DDL. The project already depends on this: `promote_staging.py`, `build_entities.py` (×11), `dm15_layer2_apply.py`, `build_cusip.py`, `normalize_securities.py`, and `build_classifications.py` all use `BEGIN TRANSACTION` / `COMMIT` / `ROLLBACK`. No new library feature or version bump is required.

**Gotchas.**

1. **`CHECKPOINT` cannot run inside an explicit transaction.** DuckDB raises `TransactionContext Error: Cannot CHECKPOINT in the middle of a transaction`. Every CHECKPOINT the promote scripts currently sprinkle between phases (§2.1 steps 6/10/12; §2.2 steps 4/6/8/11) must move to **after** `COMMIT`, or be removed entirely. A single CHECKPOINT at the end of a successful promote is equivalent in durability terms and matches what `promote_staging.py` already does (no CHECKPOINTs inside its transaction block).
2. **TEMP table DDL is fine inside a transaction.** The `_promote_scope` TEMP table in `promote_nport.py` stays where it is. DuckDB transactional DDL handles this cleanly.
3. **`reserve_ids` uses an external file lock.** As covered in §3.3 — the lock is released before the transaction commits/rolls back, and no prod state is allocated until the subsequent INSERT runs inside the transaction. Safe.
4. **`CURRENT_TIMESTAMP` / `NOW()` inside a transaction.** Both return the transaction's start time, not statement time. The current scripts use `CURRENT_TIMESTAMP` in the impacts UPDATE ([promote_nport.py:489](scripts/promote_nport.py:489), [promote_13dg.py:153](scripts/promote_13dg.py:153)); values will still be monotonically later than anything stamped outside the transaction. No behaviour change that matters for audit.
5. **`stamp_freshness` / `record_freshness` inside the transaction.** These are plain DELETE+INSERT on `data_freshness` — transactional. Fine to include.
6. **`refresh_snapshot()` must stay outside the transaction.** It does `shutil.copy2(PROD_DB, readonly_path)` ([pipeline/shared.py:194-211](scripts/pipeline/shared.py:194)) — a filesystem copy of the DB file. Must run **after** the DuckDB connection is closed (or at minimum after COMMIT + CHECKPOINT) to avoid copying a WAL-inconsistent snapshot. Current scripts already call it in the `finally`-adjacent path; no change.

---

## §6. Cross-item awareness

- **obs-03-p1 (merged).** The `reserve_ids` call is on the critical path inside the mirror. Phase 1 must not regress it — keep the call, keep it inside the extracted helper, keep it inside the transaction. §3.3 confirms this is safe.
- **mig-02 (fetch_adv.py DROP+CREATE).** Same class of problem — DROP before CREATE with no transaction. Not a shared file with mig-01; serial only because it is adjacent in the same theme. **No coordination required beyond "apply the same transaction pattern" guidance in Phase 1.**
- **mig-04 (schema_versions stamp backfill — merged).** The promote scripts do not write to `schema_versions`; stamping is a migration-level concern. **No action in this Phase 1.**
- **sec-04-p1 (validators RO default).** `promote_staging.py` is the caller of `validate_entities.py`; these promote scripts are not. **No interaction.**
- **obs-04 (ADV impacts — OPEN).** Adds ADV as a source_type in the manifest layer. The new `mirror_manifest_and_impacts(source_type=…)` signature accommodates this cleanly — when obs-04 lands, it passes `source_type='ADV'` to the same helper. Phase 1 should document that signature as the stable extension point.
- **obs-07 (OPEN, promote_nport.py — per REMEDIATION_PLAN file ownership matrix).** Touches the same file. Serial; not shared-file with any other Phase 1 work in Batch 3-A.

---

## §7. Phase 1 scope

### 7.1 Deliverables

1. **Extract** `_mirror_manifest_and_impacts` → `pipeline/manifest.py::mirror_manifest_and_impacts(prod_con, staging_con, run_id, source_type)` with the signature in §4.2. Docstring carries the audit-preservation rationale and the `reserve_ids` rationale forward.
2. **Wrap `promote_nport.py` main body in BEGIN/COMMIT/ROLLBACK.** Transaction boundary: start immediately after the `ingestion_manifest` presence probe ([promote_nport.py:436](scripts/promote_nport.py:436)); end immediately before `refresh_snapshot()`. Remove the three in-body `CHECKPOINT`s; issue one `CHECKPOINT` after COMMIT.
3. **Wrap `promote_13dg.py` main body in BEGIN/COMMIT/ROLLBACK.** Transaction boundary: start immediately after the `ingestion_manifest` presence probe ([promote_13dg.py:198-202](scripts/promote_13dg.py:198)); end immediately before `refresh_snapshot()`. Remove the four in-body `CHECKPOINT`s; issue one `CHECKPOINT` after COMMIT.
4. **Replace inline mirror** in both scripts with a call to the extracted helper.
5. **Preserve return values.** `promote_nport.py` needs `manifest_ids` for the impacts UPDATE scope; `promote_13dg.py` needs `manifest_ids` for the `_update_impacts` scope. The helper returns them.

All five changes must ship in **one commit** — per the REMEDIATION_PLAN note ([docs/REMEDIATION_PLAN.md:120](docs/REMEDIATION_PLAN.md:120)): _"both promotes + helper must ship as one commit."_

### 7.2 Out of scope for Phase 1

- mig-02 (fetch_adv.py atomicity) — separate item.
- Any changes to `promote_staging.py` — already transactional.
- Any changes to `reserve_ids` / `allocate_id` / the allocator's lock file semantics — obs-03-p1 output, no regression.
- New validators, new tables, new columns.

### 7.3 Test plan

**Unit** (offline, no DB):

- `pipeline/manifest.py::mirror_manifest_and_impacts` — exists, signature matches §4.2.

**Integration** (against `data/13f_staging.duckdb` + an ephemeral prod DB in a tmpdir — do **not** touch `data/13f.duckdb`):

1. **Happy path — N-PORT.** Stage a small N-PORT run (1 series, 1 month, ~50 rows). Call `promote_nport.py --run-id R --test`. Assert: `ingestion_manifest` + `ingestion_impacts` + `fund_holdings_v2` + `fund_universe` + `data_freshness` all updated; impacts `promote_status='promoted'`; one post-COMMIT `CHECKPOINT`.
2. **Happy path — 13D/G.** Same shape against `promote_13dg.py`.
3. **Crash mid-promote — N-PORT.** Monkey-patch `_bulk_enrich_run` to raise after the DELETE+INSERT but before the enrichment UPDATE. Assert: `fund_holdings_v2` row count unchanged from pre-promote; `ingestion_impacts.promote_status='pending'` for every unit in the run; exception propagates; connection closed cleanly.
4. **Crash mid-promote — 13D/G.** Monkey-patch `rebuild_beneficial_ownership_current` to raise. Assert: `beneficial_ownership_v2` row count unchanged; `beneficial_ownership_current` unchanged (no rebuild half-performed); impacts still `pending`.
5. **Reserve-ids integrity.** Before and after the crash test, `SELECT MAX(impact_id) FROM ingestion_impacts` matches. A subsequent successful promote allocates from `MAX+1` without gaps caused by the failed run (gaps from `reserve_ids` reservation are irrelevant — MAX-based allocation is correct).
6. **Mirror helper parity.** Run the extracted helper directly from a unit test against a staged `NPORT` run and a `13DG` run; assert the inserted manifest row counts and impact row counts match the pre-extraction behaviour captured from `main` HEAD on the same staged fixtures.

**Validator / regression sweep:**

- `python3 scripts/validate_entities.py --prod` — must pass unchanged (no entity-layer touch).
- Existing test suite — must pass unchanged.

### 7.4 Risks

- **`CHECKPOINT` removal changes WAL-flush cadence.** Under the current code, long N-PORT runs checkpoint three times; under Phase 1, once at the end. If a run takes > 1 h (DERA-scale), the WAL grows larger than before. The batch rewrite already collapses the workload into seconds for typical runs — the DERA scenario is the only one where this matters. **Mitigation:** flag the risk in the Phase 1 PR description; monitor the first DERA-scale run post-merge.
- **Transaction scope is long.** Holding a write transaction across DELETE/INSERT of hundreds of thousands of holdings + enrichment UPDATE + universe upsert + impacts UPDATE + stamps is several minutes of wall-clock. DuckDB's single-writer model means no concurrent writer is possible anyway; there is no reader lock. **No mitigation needed.**
- **`reserve_ids` advisory lock held only during the helper, not the whole transaction.** Consistent with current behaviour; no change.

---

## §8. Summary

| Finding | Evidence | Phase 1 action |
|---|---|---|
| Neither promote script wraps writes in a transaction | §2.1, §2.2 | BEGIN/COMMIT/ROLLBACK around the main body in both scripts |
| Docstring claim of atomicity is false | §2.3 | Corrected by the wrapping above; update docstring |
| DELETE-before-INSERT opens a data-loss window mid-promote | §3.1 step 4; §3.2 step 3 | Transaction closes the window |
| `_mirror_manifest_and_impacts` duplicated across two scripts | §4.1 | Extract to `pipeline/manifest.py::mirror_manifest_and_impacts` |
| CHECKPOINT cannot run inside a transaction | §5 gotcha 1 | Move to single post-COMMIT CHECKPOINT |
| `reserve_ids` safe inside a transaction | §3.3 | No change — keep as-is |
| No cross-item file conflicts in Batch 3-A | §6 | mig-01 and mig-02 share theme but not files; proceed |

Phase 1 ships as one commit on branch `remediation/mig-01-p1` covering the five deliverables in §7.1 plus the test additions in §7.3.
