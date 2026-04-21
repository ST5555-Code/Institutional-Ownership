# sec-05-p0 — Phase 0 findings: hardcoded-prod builders bypass staging

_Prepared: 2026-04-21 — branch `sec-05-p0` off main HEAD `fa01c7e`._

_Tracker: `docs/REMEDIATION_PLAN.md` Theme 4-C row `sec-05` (MAJOR-2 C-04, Batch 4-C). Also closes the `build_fund_classes` + `build_benchmark_weights` portion of `mig-13` (pipeline-violations REWRITE tail). Scope boundary with `mig-14` is clarified in §5. No overlap with int-14 (`merge_staging.py` NULL-only semantics) — this item does not touch `merge_staging.py`._

Phase 0 is investigation only. No code writes and no DB writes were performed. Deliverable: this document + Phase 1 fix recommendation.

---

## §1. Scope and method

**Scope.** `scripts/build_fund_classes.py`, `scripts/build_benchmark_weights.py`, `scripts/build_managers.py`, `scripts/db.py`, `scripts/promote_staging.py`, `scripts/merge_staging.py`. Read-only inspection only.

**Method.** Full-file reads of the three builder scripts plus `db.py`. Targeted greps for `STAGING_DB`, `set_staging_mode`, `CANONICAL_TABLES`, `PROMOTE_KIND`, `PK_COLUMNS`, `seed_staging`, `fund_classes`, `lei_reference`, `benchmark_weights` across `scripts/`. Git log on `scripts/build_managers.py` after commit `1719320` to verify the current shipped state. No runtime probing.

---

## §2. Per-script inventory

### 2.1 `scripts/build_fund_classes.py`

**DB connection.** [build_fund_classes.py:85](scripts/build_fund_classes.py:85) — `con = duckdb.connect(get_db_path())`. Routes through the centralized write target in [db.py:40-46](scripts/db.py:40). `--staging` CLI flag shipped ([build_fund_classes.py:203-205](scripts/build_fund_classes.py:203)) calls `set_staging_mode(True)` in `__main__` ([:210-211](scripts/build_fund_classes.py:210)).

**Tables written.**

| Table | Pattern | Line(s) | Notes |
|---|---|---|---|
| `fund_classes` | `CREATE TABLE IF NOT EXISTS` + per-row `INSERT` | [:30-40](scripts/build_fund_classes.py:30), [:119-123](scripts/build_fund_classes.py:119) | Append-only; dedupes against in-memory `existing` set keyed on `(series_id, class_id)`. No DROP. Per-row INSERTs in a tight loop with `CHECKPOINT` every 5,000 XMLs. |
| `lei_reference` | `CREATE TABLE IF NOT EXISTS` + `INSERT OR REPLACE` | [:41-50](scripts/build_fund_classes.py:41), [:130-133](scripts/build_fund_classes.py:130) | Keyed on `lei` (PK). Guarded `try/except` around each insert to swallow PK collisions. |
| `fund_holdings_v2` | `ALTER TABLE … ADD COLUMN lei` + cross-table `UPDATE … FROM lei_reference` | [:145](scripts/build_fund_classes.py:145), [:151-157](scripts/build_fund_classes.py:151) | Enrichment-style update on a large table (~9.3M rows per [project_session_apr15_dera_promote.md]). ALTER wrapped in try/except for idempotency. |

**Reads.** `fund_classes` [:95](scripts/build_fund_classes.py:95) (prior-state check), and the closing summary queries [:163-165](scripts/build_fund_classes.py:163), [:176-181](scripts/build_fund_classes.py:176). Implicit read of `fund_holdings_v2` via the UPDATE at [:151-157](scripts/build_fund_classes.py:151) (self-read during JOIN to `lei_reference`).

**Manifest / freshness / impacts.**
- **Manifest/impacts**: none. Not registered with `ingestion_manifest` / `ingestion_impacts`.
- **Freshness**: `record_freshness(con, "fund_classes")` at [:189](scripts/build_fund_classes.py:189), guarded try/except. `lei_reference` and `fund_holdings_v2` are NOT stamped.

**Staging-safety gap.** The `--staging` flag sets the connection target, but:
1. `db.seed_staging()` is **not called** — staging DB will be missing the reference tables the script reads from (`fund_holdings_v2`).
2. `fund_holdings_v2` is **not in `REFERENCE_TABLES`** in [db.py:82-85](scripts/db.py:82) — even if `seed_staging()` were invoked, the table wouldn't be copied.
3. The cross-table `UPDATE fund_holdings_v2 … FROM lei_reference` at [:151-157](scripts/build_fund_classes.py:151) would fail on a fresh staging DB (table missing), and is anyway the wrong pattern — it mutates a 9.3M-row prod surface from a builder whose primary output is `fund_classes` / `lei_reference`.

**Complexity rating.** **Medium.** Two small append-only tables (`fund_classes`, `lei_reference`) are candidates for a standard staging → promote split. The `fund_holdings_v2.lei` enrichment is a different animal — it belongs in an `--enrichment-only` post-promote step, parallel to `build_managers.py`'s pattern ([build_managers.py:625-684](scripts/build_managers.py:625)).

---

### 2.2 `scripts/build_benchmark_weights.py`

**DB connection.** [build_benchmark_weights.py:58](scripts/build_benchmark_weights.py:58) — `con = duckdb.connect(get_db_path())`. `--staging` CLI flag shipped ([:152-154](scripts/build_benchmark_weights.py:152)) calls `set_staging_mode(True)` in `__main__` ([:158-160](scripts/build_benchmark_weights.py:158)).

**Tables written.**

| Table | Pattern | Line(s) | Notes |
|---|---|---|---|
| `benchmark_weights` | `CREATE TABLE IF NOT EXISTS` + per-quarter `DELETE` + per-row `INSERT` | [:61-71](scripts/build_benchmark_weights.py:61), [:128-131](scripts/build_benchmark_weights.py:128), [:137-141](scripts/build_benchmark_weights.py:137) | Upsert-by-delete-then-insert, keyed on `(index_name, as_of_date)` per quarter. PK `(index_name, gics_sector, as_of_date)`. Single writer; no cross-table mutation. |

**Reads.** `fund_holdings_v2` [:83-87, :97-112](scripts/build_benchmark_weights.py:83) (benchmark fund holdings), `market_data` [:108](scripts/build_benchmark_weights.py:108) (sector mapping via LEFT JOIN on `ticker`).

**Manifest / freshness / impacts.**
- **Manifest/impacts**: none.
- **Freshness**: **none.** No `record_freshness` call at all — this is a ROADMAP gap independent of the staging conversion.

**Staging-safety gap.** Same two gaps as §2.1:
1. `db.seed_staging()` is **not called**.
2. `fund_holdings_v2` is **not in `REFERENCE_TABLES`**. `market_data` IS in `REFERENCE_TABLES` ([db.py:82-85](scripts/db.py:82)). Running `--staging` against a fresh staging DB would fail at [:83-87](scripts/build_benchmark_weights.py:83) (missing `fund_holdings_v2`).

**Complexity rating.** **Simple.** Single-table writer, no cross-DB fan-out. The cleanest candidate for conversion to staging → promote: small table (≈50 rows per quarter × 11 GICS sectors), atomic `CREATE OR REPLACE` against staging + pk_diff promote is sufficient.

---

### 2.3 `scripts/build_managers.py` — current shipped state

**Git history after commit `1719320` (the partial staging mentioned in the prompt).** Three follow-up commits landed on this file:

| Commit | Change | Date |
|---|---|---|
| `67e81f3` | `feat(build_managers): --dry-run, --staging, fail-fast, retrofits` | Apr 19 2026 |
| `2a71f8a` | `fix(build_managers): dedupe parent_bridge on cik` | Apr 19 2026 |
| `4e64473` | `feat(build_managers): COALESCE on holdings_v2 enrichment — preserve legacy` | Apr 19 2026 |

**What's already shipped (as of HEAD `fa01c7e`).**

1. **Routing**: `--staging` flag calls `db.set_staging_mode(True)` then `db.seed_staging()` ([build_managers.py:769-770, :784-785](scripts/build_managers.py:769)). Seeds reference tables from prod → staging before the build runs. `--test` flag also wired.
2. **Dry-run**: `--dry-run` flag prints projected row counts without DB writes. Every step has a dry-run branch — `build_parent_bridge` ([:323-329](scripts/build_managers.py:323)), `link_cik_to_crd` ([:466-479](scripts/build_managers.py:466)), `build_managers_table` ([:510-528](scripts/build_managers.py:510)), `enrich_holdings_v2` ([:654-664](scripts/build_managers.py:654)).
3. **Fail-fast input guard**: `_assert_inputs_present(con)` at [:233-249](scripts/build_managers.py:233) raises on missing/empty `filings_deduped` or `adv_managers`.
4. **Split enrichment**: `--enrichment-only` flag ([:740-747](scripts/build_managers.py:740)) runs only the `UPDATE holdings_v2` step ([:625-684](scripts/build_managers.py:625)) — the Phase 4 three-step flow (staging build → promote → enrichment against prod).
5. **`data_freshness` stamps**: `parent_bridge`, `cik_crd_links`, `cik_crd_direct`, `managers`, `holdings_v2` all stamped via `record_freshness` ([:336](scripts/build_managers.py:336), [:487](scripts/build_managers.py:487), [:497](scripts/build_managers.py:497), [:619](scripts/build_managers.py:619), [:681](scripts/build_managers.py:681)).
6. **Promote-staging integration**: `parent_bridge`, `cik_crd_direct` promoted via `pk_diff` (both in [db.py:121-128](scripts/db.py:121) `CANONICAL_TABLES`, PKs in [promote_staging.py:49-65](scripts/promote_staging.py:49)). `managers`, `cik_crd_links` promoted via new `rebuild` kind ([promote_staging.py:116-125](scripts/promote_staging.py:116), [:304-319](scripts/promote_staging.py:304)).

**What remains.** Nothing, code-wise. The builder is fully routable + dry-runnable + promotable. The only open question is whether `docs/REMEDIATION_CHECKLIST.md` line 85 (`mig-14`) should be flipped to closed — that's a checklist-hygiene task, not a code task.

**Conclusion.** `build_managers.py` is **not in sec-05 scope**. The `REMEDIATION_PLAN.md` line 161 claim "`scripts/build_managers.py` (routing pending)" is **stale** — routing shipped in `67e81f3`. Confirmed by reading the file and git log. See §5 for scope boundary.

---

## §3. Reference pattern — how the `--staging` → `--promote` split should work

**Fetch/build-writes-staging half** (target shape for fund_classes + benchmark_weights):

- **Connection**: `duckdb.connect(get_db_path())` after `set_staging_mode(True)` — same as today. **Add** `db.seed_staging()` in `__main__` when staging is active, so the reference-table copies from prod happen before the build connects.
- **Reference-table gap**: `fund_holdings_v2` must be added to `REFERENCE_TABLES` in [db.py:82-85](scripts/db.py:82). Both builders read from it; both fail on staging today without this.
- **Fact-table writes in staging**: `CREATE OR REPLACE TABLE <t> AS SELECT …` — atomic in DuckDB, closes the DROP→CREATE kill-window at the staging-DB layer.
- **Cross-table enrichment UPDATE on prod surfaces**: extract into `--enrichment-only` post-promote step, same pattern as [build_managers.py:625-684](scripts/build_managers.py:625).
- **Freshness**: do NOT stamp from the builder when `--staging`. Move stamp into `promote_*.py` after the prod commit lands (mirrors the obs-02 / mig-02 decision for `fetch_adv` → `promote_adv`).
- **Manifest/impacts**: both builders lack this today. Not a blocker for sec-05 (the two source surfaces are `nport_raw/*.xml` on disk for fund_classes, and `fund_holdings_v2` + `market_data` for benchmark_weights — neither is a new ingestion). Defer manifest registration to an obs-item follow-up if desired; not required for staging-safety.

**Promote half.** Three options, in order of precedent alignment:

- **Option A — route through `promote_staging.py`** (same as `parent_bridge`, `managers`): add `fund_classes`, `lei_reference`, `benchmark_weights` to [db.py CANONICAL_TABLES](scripts/db.py:121), add PK entries in [promote_staging.py PK_COLUMNS](scripts/promote_staging.py:49) (`fund_classes` → `(series_id, class_id)`, `lei_reference` → `(lei,)`, `benchmark_weights` → `(index_name, gics_sector, as_of_date)`), choose `pk_diff` kind for all three (natural keys are empirically unique). Stamp `data_freshness` inside the promote flow on prod commit.
- **Option B — standalone `promote_fund_classes.py` and `promote_benchmark_weights.py`** (same as mig-02's `promote_adv.py`): cleaner isolation from the int-14 / mig-14 conflict zone, at the cost of two more scripts to maintain.
- **Option C — `merge_staging.py` via the NULL-only path**: `merge_staging.py` already has [keys for fund_classes + lei_reference at :53-54](scripts/merge_staging.py:53). This option is **rejected** for sec-05 because `merge_staging.py`'s NULL-only semantics are the subject of `int-14` — adding more traffic through it widens the int-14 scope and creates a merge-ordering hazard.

**Recommendation**: Option A. Lowest script surface, highest reuse, same shape as the mig-14 `rebuild` / `pk_diff` machinery. The benchmark_weights + fund_classes tables are all small (collectively <100k rows), so atomic snapshot-and-restore in `promote_staging.py` is safe.

---

## §4. Proposed sec-05 Phase 1 scope

**In-scope files.**

| File | Change | Risk |
|---|---|---|
| `scripts/build_fund_classes.py` | Invoke `db.seed_staging()` under `--staging`. Extract `fund_holdings_v2.lei` UPDATE into `--enrichment-only` branch. Move `record_freshness` out of staging path (let promote stamp). | Medium — touches the cross-table UPDATE. |
| `scripts/build_benchmark_weights.py` | Invoke `db.seed_staging()` under `--staging`. Convert write path to `CREATE OR REPLACE TABLE benchmark_weights AS …` (or DELETE+INSERT as today, both atomic against staging). Add `record_freshness` call (retrofit the gap noted in §2.2) — but place it in the promote path, not the builder. | Low — single-table writer. |
| `scripts/db.py` | Add `fund_holdings_v2` to `REFERENCE_TABLES`. Add `fund_classes`, `lei_reference`, `benchmark_weights` to `CANONICAL_TABLES`. | Low — additive. |
| `scripts/promote_staging.py` | Add PK entries for the three new tables in `PK_COLUMNS`. Choose `pk_diff` for all three. Ensure `data_freshness` stamp on prod commit. | Medium — exercises the int-14/mig-14 conflict zone; keep changes additive, no touches to existing PK_COLUMNS or PROMOTE_KIND entries. |

**Out-of-scope (explicitly deferred).**

- `build_managers.py` — already routed; belongs to `mig-14` closeout.
- `merge_staging.py` — int-14 territory.
- Manifest/impacts registration for either builder — defer to obs-follow-up.
- `backfill_manager_types.py`, `resolve_*.py`, `enrich_tickers.py`, validators writing to prod — listed in `sec-06` (separate item).

**Phase 1 file list (for the implementer).**

```
scripts/build_fund_classes.py
scripts/build_benchmark_weights.py
scripts/db.py
scripts/promote_staging.py
docs/REMEDIATION_PLAN.md  (close sec-05 line 161, update mig-14 line 133 to reflect routing shipped)
docs/REMEDIATION_CHECKLIST.md  (flip line 116 on sec-05 Phase 1 ship; line 85 mig-14 is a separate closeout)
ROADMAP.md  (COMPLETED entry)
```

---

## §5. Scope boundaries

### 5.1 sec-05 ↔ mig-14

**Boundary.** sec-05 covers `build_fund_classes.py` and `build_benchmark_weights.py`. mig-14 covers `build_managers.py` — which is **substantially already shipped** (commits `67e81f3`, `2a71f8a`, `4e64473`), so mig-14 reduces to a checklist-hygiene closeout.

**Why this split is correct.**

1. The `REMEDIATION_CHECKLIST.md` line 116 explicitly names only `build_fund_classes.py` and `build_benchmark_weights.py` for sec-05, with `build_managers.py` listed separately on line 85 under mig-14.
2. `build_managers.py` has a routing surface (4 CTAS tables + 1 enrichment UPDATE) that requires the `rebuild` kind in `promote_staging.py` and the `--enrichment-only` flag, both of which are already in place.
3. The two sec-05 scripts are pure builders (fund_classes: append-only + enrichment; benchmark_weights: upsert-by-delete) with no external dependencies on `merge_staging.py` or new `promote_staging.py` kinds. They can ride the existing `pk_diff` path.
4. `REMEDIATION_PLAN.md` line 251 calls out sec-05 ↔ mig-14 as "same file, different perspectives. Must be merged into one scope" — **but this predates the 67e81f3 ship**. Post-67e81f3, the "merge" is already done: mig-14's code work landed under build_managers commits, leaving sec-05 focused on the two still-direct builders.

**Action for mig-14.** Flip `REMEDIATION_CHECKLIST.md` line 85 to closed referencing commits `67e81f3` + `2a71f8a` + `4e64473` (and `1719320` for the holdings-v2 retire). Update `REMEDIATION_PLAN.md` line 133 and line 161 accordingly. This can be a docs-only PR piggybacked on sec-05 Phase 1, or a separate mig-14-closeout PR — the implementer's call.

### 5.2 sec-05 ↔ mig-13

**Boundary.** mig-13 is the "5 pipeline-violations REWRITE tail" catch-all listing `fetch_adv`, `build_fund_classes`, `build_entities`, `build_benchmark_weights`, `merge_staging` ([REMEDIATION_PLAN.md:132](docs/REMEDIATION_PLAN.md:132)). Precedent: `mig-02` closed the `fetch_adv` portion when it shipped `promote_adv.py` ([mig-02-p0-findings.md §2.4](docs/findings/mig-02-p0-findings.md)).

**sec-05 should close the `build_fund_classes` + `build_benchmark_weights` portion of mig-13** on the same model. After sec-05 Phase 1 ships, mig-13 reduces to three remaining items: `build_entities`, `merge_staging`, and the int-14 NULL-only semantics question. Document this closure in the sec-05 commit message and in the REMEDIATION_PLAN update.

### 5.3 sec-05 ↔ sec-06

sec-06 covers the five unlisted direct-to-prod writers (`resolve_agent_names`, `resolve_bo_agents`, `resolve_names`, `backfill_manager_types`, `enrich_tickers`) per [REMEDIATION_PLAN.md:143](docs/REMEDIATION_PLAN.md:143). Disjoint file set from sec-05; no conflict. sec-06 can proceed independently.

### 5.4 sec-05 ↔ int-14

int-14 is the `merge_staging.py` NULL-only merge semantics redesign ([REMEDIATION_PLAN.md:248](docs/REMEDIATION_PLAN.md:248)). sec-05 proposes Option A (route the new tables through `promote_staging.py`, not `merge_staging.py`), which **avoids the int-14 conflict zone entirely.** No serial dependency.

---

## §6. Risks and notes

1. **`fund_holdings_v2` in `REFERENCE_TABLES`.** Adding it will cause `seed_staging()` to copy ~9.3M rows from prod → staging on first staging invocation. Size-check: staging DB is already holding entity tables of comparable size; disk impact is ~1-2GB per staging refresh. Acceptable for infrequent builder invocations. If per-run copy cost is too high, consider a `read_only_reference` ATTACH pattern as a future optimization — not required for Phase 1.
2. **`fund_classes` INSERT-loop performance.** The builder does ~30k single-row INSERTs with `CHECKPOINT` every 5k XMLs ([build_fund_classes.py:105-138](scripts/build_fund_classes.py:105)). Not changed by this item, but worth flagging: a bulk INSERT via pandas/Arrow would be 10-20× faster. Defer to an obs/perf follow-up.
3. **`build_fund_classes.py` ALTER on `fund_holdings_v2`.** The `ADD COLUMN lei` at [:145](scripts/build_fund_classes.py:145) is idempotent (try/except-wrapped), but it's schema-altering. In the new flow, this ALTER should run **only in the prod enrichment step** (not in staging), to avoid a staging schema drift that would then need to be diffed against prod.
4. **`benchmark_weights` has no manifest registration.** Not a sec-05 blocker, but note: compute_flows.py and any downstream analytics rely on this table. A staging promote failure that leaves prod stale would be invisible today (no freshness stamp). Phase 1 should add `record_freshness("benchmark_weights")` to the promote path to close this silently-stale hazard.
5. **sec-05 Phase 1 parallel-safety.** Can run in parallel with sec-06 (disjoint files) and sec-07/sec-08 (pinning + EDGAR identity, already merged). Must serialize after any pending int-14 work on `promote_staging.py`, though §4 keeps sec-05's promote_staging.py edits additive.
6. **No runtime probing was performed.** All assertions above are from static reading of the scripts, db.py, promote_staging.py, and git log. A Phase 1 implementer should run `python3 scripts/build_fund_classes.py --staging --dry-run` first (once Phase 1 lands) to confirm the seed_staging path lights up before attempting a full promote.

---

## §7. Phase 1 acceptance criteria

1. `python3 scripts/build_fund_classes.py --staging` writes `fund_classes` + `lei_reference` to `13f_staging.duckdb` only. No prod writes. No ALTER/UPDATE on prod `fund_holdings_v2`.
2. `python3 scripts/build_fund_classes.py --enrichment-only` runs only the `fund_holdings_v2.lei` ALTER + UPDATE against prod, using the prod-side `lei_reference` from the prior promote.
3. `python3 scripts/build_benchmark_weights.py --staging` writes `benchmark_weights` to staging only.
4. `python3 scripts/promote_staging.py --tables fund_classes,lei_reference,benchmark_weights` executes a `pk_diff` promote, stamps `data_freshness` for each table, and leaves prod row counts equal-to-or-greater-than pre-promote for `fund_classes`/`lei_reference` and equal for `benchmark_weights` (after per-quarter upsert).
5. `REMEDIATION_CHECKLIST.md` sec-05 line 116 flipped to closed. mig-13 build_fund_classes + build_benchmark_weights portion noted as closed. Optional: mig-14 closeout in same PR or a follow-up.
6. CI smoke green.
