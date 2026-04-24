# Snapshot Inventory — 2026-04-24

**Session:** snapshot-discovery
**HEAD:** dd9b388 (fetch-finra-short-dry-run)
**DB as-of:** `data/13f.duckdb` (15.1 GiB, opened read-only)
**Scope:** Read-only inventory of every `%_snapshot_%` table in `main` schema. No writes. No retention policy. No deletions.
**Out of scope:** Retention policy, snapshot deletion, any DB write. Those are separate sessions.

## 1. Counts

- **Total snapshots:** 292
- **Base tables covered:** 17
- **Total rows across all snapshots:** 30,471,250
- **Total on-disk bytes:** NOT RELIABLY QUERYABLE. DuckDB's `duckdb_tables.estimated_size` is a row-count estimate, not bytes, and the storage engine does not expose per-table on-disk size. The 19.1 GiB file contains 15.1 GiB of live pages; snapshot contribution to that total is not separable without `COPY TO PARQUET` or equivalent per-table dump, which is out of scope for a read-only inventory.

**Delta vs plan V8:** Plan V8 claimed 292 snapshots across 15 tables. Confirmed **292 snapshots, 17 base tables (+2 delta)**. The +2 are the one-off holdings_v2 pre-apply snapshots (`holdings_v2_manager_type_legacy`, `holdings_v2_pct_of_so_pre_apply`) created on 2026-04-19 outside the `promote_staging.py` framework. See §2 and §5 for details.

## 2. Per-base-table breakdown

| Base table | Snapshots | Oldest | Newest | Total rows | Creating mechanism |
|---|---:|---|---|---:|---|
| `cik_crd_direct` | 1 | 2026-04-19 | 2026-04-19 | 4,059 | promote_staging.py (SESSION / TOOL-AUTO) |
| `cik_crd_links` | 1 | 2026-04-19 | 2026-04-19 | 448 | promote_staging.py (SESSION / TOOL-AUTO) |
| `cusip_classifications` | 1 | 2026-04-18 | 2026-04-18 | 132,618 | promote_staging.py (SESSION / TOOL-AUTO) |
| `entities` | 33 | 2026-04-11 | 2026-04-23 | 751,066 | promote_staging.py (SESSION / TOOL-AUTO) |
| `entity_aliases` | 33 | 2026-04-11 | 2026-04-23 | 761,365 | promote_staging.py (SESSION / TOOL-AUTO) |
| `entity_classification_history` | 33 | 2026-04-11 | 2026-04-23 | 752,662 | promote_staging.py (SESSION / TOOL-AUTO) |
| `entity_identifiers` | 33 | 2026-04-11 | 2026-04-23 | 1,044,317 | promote_staging.py (SESSION / TOOL-AUTO) |
| `entity_identifiers_staging` | 32 | 2026-04-11 | 2026-04-23 | 112,096 | promote_staging.py (SESSION / TOOL-AUTO) |
| `entity_overrides_persistent` | 23 | 2026-04-12 | 2026-04-23 | 2,469 | promote_staging.py (SESSION / TOOL-AUTO) |
| `entity_relationships` | 32 | 2026-04-11 | 2026-04-23 | 509,089 | promote_staging.py (SESSION / TOOL-AUTO) |
| `entity_relationships_staging` | 32 | 2026-04-11 | 2026-04-23 | 0 | promote_staging.py (SESSION / TOOL-AUTO) |
| `entity_rollup_history` | 33 | 2026-04-11 | 2026-04-23 | 1,703,335 | promote_staging.py (SESSION / TOOL-AUTO) |
| `holdings_v2_manager_type_legacy` | 1 | 2026-04-19 | 2026-04-19 | 12,270,984 | one-off remediation script |
| `holdings_v2_pct_of_so_pre_apply` | 1 | 2026-04-19 | 2026-04-19 | 12,270,984 | one-off remediation script |
| `managers` | 1 | 2026-04-19 | 2026-04-19 | 12,005 | promote_staging.py (SESSION / TOOL-AUTO) |
| `parent_bridge` | 1 | 2026-04-19 | 2026-04-19 | 11,135 | promote_staging.py (SESSION / TOOL-AUTO) |
| `securities` | 1 | 2026-04-18 | 2026-04-18 | 132,618 | promote_staging.py (SESSION / TOOL-AUTO) |
| **TOTAL** | **292** | 2026-04-11 | 2026-04-23 | **30,471,250** | — |

**Notes on the 17 base tables:**

- 9 are `ENTITY_TABLES` (see `scripts/db.py:92-102`): `entities`, `entity_identifiers`, `entity_relationships`, `entity_aliases`, `entity_classification_history`, `entity_rollup_history`, `entity_identifiers_staging`, `entity_relationships_staging`, `entity_overrides_persistent`. These accumulated 23-33 snapshots each via the entity staging/promote workflow (`sync_staging → diff_staging → promote_staging`).
- 6 are `CANONICAL_TABLES` that have been through at least one promotion: `cusip_classifications`, `securities` (both 2026-04-18, BLOCK-SECURITIES-DATA-AUDIT Phase 3), `parent_bridge`, `cik_crd_direct`, `managers`, `cik_crd_links` (all 2026-04-19, REWRITE_BUILD_MANAGERS Batch 3 close). 3 additional CANONICAL_TABLES (`fund_classes`, `lei_reference`, `benchmark_weights` — added 2026-04-21 for sec-05) have **no snapshots yet** because they have not been promoted.
- 2 are ad-hoc one-offs outside the promote workflow: `holdings_v2_manager_type_legacy` (created by the retired `scripts/retired/snapshot_manager_type_legacy.py`, commit `c2c2bac`, "pre-phase-4 snapshot table for holdings_v2.manager_type") and `holdings_v2_pct_of_so_pre_apply` (created during pct-of-so Phase 4b, commit `5cea20c`, "pct-of-so Phase 4b: prod apply findings"). Both contain full 12.27M-row copies of the then-current holdings_v2 state, tagged by the remediation they preceded.

**Snapshot naming pattern (all 292 parse cleanly):** `<base>_snapshot_<YYYYMMDD>[_<HHMMSS>]`. 290 have the full timestamp suffix (promote_staging.py emits `%Y%m%d_%H%M%S`); 2 have date-only suffix (the one-off holdings_v2 scripts use `%Y%m%d`).

## 3. Classification matrix

Creators × intents, cell counts:

| Creator \ Intent | ROLLBACK | REFERENCE | DEBUG | UNKNOWN | **Total** |
|---|---:|---:|---:|---:|---:|
| MIGRATION (scripts/migrations/NNN) | 0 | 0 | 0 | 0 | **0** |
| SESSION / TOOL-AUTO (promote_staging.py) | 290 | 0 | 0 | 0 | **290** |
| SESSION / AD-HOC (one-off scripts) | 0 | 2 | 0 | 0 | **2** |
| AD-HOC (no traceable creator) | 0 | 0 | 0 | 0 | **0** |
| UNKNOWN | 0 | 0 | 0 | 0 | **0** |
| **Total** | **290** | **2** | **0** | **0** | **292** |

**How each row was classified:**

- **Creator = SESSION / TOOL-AUTO:** Matched via `git log -S "<base>_snapshot"` to commit `3816577` (pipeline framework foundation, INF1 staging workflow, 2026-04-13) or to CANONICAL_TABLES onboarding commits. These snapshots are emitted automatically by `scripts/promote_staging.py:144 _snapshot_name()` on every `promote_staging.py` invocation, so the "session" is whichever entity-curation / canonical-promotion session ran the tool. See `ROADMAP.md` and the per-session memos (Apr 11-12 QC marathon, Apr 15 CUSIP v1.4, Apr 18 securities audit, Apr 19 Batch 3 close).
- **Creator = SESSION / AD-HOC:** The 2 holdings_v2 snapshots traced via git log directly to a specific remediation commit (`c2c2bac`, `5cea20c`) with a one-off Python script, not the standard promote workflow.
- **Intent = ROLLBACK:** Documented explicitly at `scripts/rollback_promotion.py:6` — snapshots are "`{table}_snapshot_{YYYYMMDD_HHMMSS}` sibling tables in the production DB" consumed by the rollback tool to restore pre-promotion state.
- **Intent = REFERENCE:** The 2 holdings_v2 snapshots are named explicitly as pre-operation references (`*_legacy`, `*_pre_apply`) and their commit messages frame them as point-in-time records for the remediation, not as rollback safety.
- **Intent = DEBUG / UNKNOWN = 0:** No snapshots bear debug-style naming. All 292 have a clear creator and intent from the commit history and naming convention.

## 4. Active-reference summary

| Bucket | Count | Notes |
|---|---:|---|
| LIVE REFERENCE (read by non-archive runtime code) | **0** | No snapshot name appears in `scripts/app.py`, `web/`, or any runtime query path. |
| TEST REFERENCE (read by `tests/` only) | **0** | `tests/pipeline/test_base.py:339` references the `_snapshot_` pattern generically — it does not read any specific snapshot by name. |
| DOC REFERENCE (mentioned only in `docs/`) | **0** | `ROADMAP.md`, `MAINTENANCE.md`, `data_layers.md`, `pipeline_violations.md`, Phase B/C plan, `ENTITY_ARCHITECTURE.md`, findings docs, and `archive/docs/SYSTEM_PASS2_2026_04_17.md` describe the pattern but do not name specific snapshots. |
| NO REFERENCE | **292** | All snapshots. |

**Full LIVE list:** (empty)

**Full TEST list:** (empty — `tests/pipeline/test_base.py` verifies snapshot creation inside `promote_staging.py` on synthetic test data; it does not depend on any existing production snapshot.)

**Operationally load-bearing tools (pattern-based, not name-based):**

- `scripts/rollback_promotion.py:45` — calls `promote_staging.rollback(args.restore, list(db.ENTITY_TABLES))`. An operator passes the `snapshot_id` (timestamp suffix) at the command line. The tool discovers matching snapshot tables via `information_schema.tables LIKE '%_snapshot_%'`. It does not hard-code any specific snapshot name. Any snapshot matching the requested `snapshot_id` is a valid restore target.
- `scripts/promote_staging.py` (lines 143-178, 227-241) — creates, lists, and purges snapshots via the same LIKE pattern. Also name-free.
- `scripts/pipeline/registry.py:414-418` — documents snapshot tables as auto-managed and excludes them from DATASET_REGISTRY governance (pattern `_snapshot_` in `ignore_patterns`).

**Implication:** No snapshot is referenced by name anywhere in code. Operational dependency is entirely on the naming pattern + the newest snapshot per base table (as the rollback anchor for the most recent promotion).

### 4.1 Validation against dynamic-naming patterns (2026-04-24)

The 0 / 0 / 0 / 292 classification was validated against dynamic name-construction patterns, not just literal snapshot names:

```
grep -rn '"_snapshot_"\|f"{[^}]*}_snapshot_\|_snapshot_{[^}]*}"\|"snapshot"' scripts/ web/ tests/
grep -rn 'snapshot_table\|snapshot_name\|create_snapshot\|make_snapshot\|SNAPSHOT' scripts/ web/ tests/
grep -rn "rollback_promotion\|promote_staging\|_snapshot_suffix\|latest_snapshot" scripts/ web/
```

**Dynamic constructors found — all already accounted for:**

- `scripts/promote_staging.py:143-144` — `_snapshot_name(table, sid)` helper returning `f"{table}_snapshot_{sid}"`. Consumed by the snapshot/rollback/restore methods at lines 150/165/178 with `sid` supplied from the `--rollback SNAPSHOT_ID` CLI argument or from the snapshot-creation path. Pattern-based, operator-supplied — not a hard-coded specific-name reference.
- `scripts/promote_staging.py:238,241` — parses `snapshot_id` out of discovered table names when `--list-snapshots` is invoked. Listing, not name-based reading.
- `scripts/rollback_promotion.py:39,44-46` — calls `promote_staging.list_snapshots()` and `promote_staging.rollback(args.restore, list(db.ENTITY_TABLES))`. `args.restore` is a CLI-supplied snapshot_id; not a hard-coded name.
- `scripts/pipeline/registry.py:418` — `ignore_patterns = ("_snapshot_",)` — this *excludes* snapshot tables from DATASET_REGISTRY governance. Pattern-exclusion, not a consumer.
- `scripts/retired/snapshot_manager_type_legacy.py:31,41-42` — the retired ad-hoc script that originally created `holdings_v2_manager_type_legacy_snapshot_20260419`. Creator, not reader. Script is in `scripts/retired/`.

**Namespace-collision false positives (checked and dismissed):**

- `scripts/config.py:31 QUARTER_SNAPSHOT_DATES` + `scripts/api_config.py:30,35` — 13F quarter-end calendar dates, unrelated to DB snapshot tables.
- `scripts/app_db.py:31 DB_SNAPSHOT_PATH` — file path of `13f_readonly.duckdb` (a snapshot *of the whole DB file* served to the Flask app). Different concept; not a reference to any `%_snapshot_%` table.
- `tests/smoke/test_smoke_endpoints.py:24,73 SNAPSHOT_DIR` — JSON response-fixture directory for HTTP smoke tests (Jest-style response snapshots). Unrelated to DB snapshots.
- `scripts/rollback_promotion.py:30` + `scripts/promote_staging.py:747` — CLI `metavar="SNAPSHOT_ID"` help strings. Not references.

**Result: no dynamic consumer references any specific `%_snapshot_%` table by name.** The 0 LIVE / 0 TEST / 0 DOC / 292 NO REFERENCE classification holds. Operational coupling is 100% pattern-based via the rollback/promote tool pair, which discovers snapshots at runtime from `information_schema.tables LIKE '%_snapshot_%'` and acts on whichever `snapshot_id` the operator supplies.

## 5. Timing flags

### 5.1 `raw_*` snapshots (B3 drop coordination)

**Count: 0.** No snapshot has a base table starting with `raw_`. Policy session has no coordination required with B3 raw-table drops.

### 5.2 Cutover-path snapshots (holdings / holdings_v2 / filings / filings_deduped)

**Count: 2.** Both on `holdings_v2_*` (pre-apply state), both 2026-04-19, both 12,270,984 rows (full copy of holdings_v2 at that timestamp).

| Snapshot | Base | Date | Rows | Creating session |
|---|---|---|---:|---|
| `holdings_v2_manager_type_legacy_snapshot_20260419` | `holdings_v2_manager_type_legacy` | 2026-04-19 | 12,270,984 | commit c2c2bac (rewrite-build-managers, pre-phase-4) |
| `holdings_v2_pct_of_so_pre_apply_snapshot_20260419` | `holdings_v2_pct_of_so_pre_apply` | 2026-04-19 | 12,270,984 | commit 5cea20c (pct-of-so Phase 4b, prod apply) |

**Flag:** B2.5 V2 cutover completed 2026-04-23 (PR #141, commit `ad4b8f7`). The policy session must consider whether these 2 pre-apply holdings_v2 snapshots — which predate both the pct-of-so apply and the B2.5 cutover — are still needed as revert references during the 2-cycle gate (Q1 + Q2 cycle, closing ~Aug 2026). No `holdings` or `filings` or `filings_deduped` snapshots exist; only `holdings_v2_*`. Zero snapshots exist for the V1 holdings/filings path, so there is no V1 rollback artifact to coordinate.

### 5.3 Recent snapshots (≤ 14 days old)

**Count: 292 of 292 (100%).**

The snapshot mechanism was introduced on 2026-04-11 (the INF1 staging workflow went live per `project_staging_workflow_live.md`). All 292 snapshots therefore fall within the 14-day window by construction — there is no pre-2026-04-11 snapshot history.

Age distribution:

| Age (days) | Count |
|---:|---:|
| 1 | 18 |
| 2 | 5 |
| 5 | 6 |
| 6 | 2 |
| 7 | 81 |
| 8 | 36 |
| 9 | 18 |
| 12 | 102 |
| 13 | 24 |

**Implication:** The plan's "recent-snapshots-may-still-serve-as-active-rollback" heuristic applies to the entire inventory. Any policy must be explicit about which of these are genuinely load-bearing rollback anchors (likely the newest-per-base-table) vs superseded intermediate snapshots from the entity-QC marathon.

**Newest-per-base rollback anchors (17 snapshots, one per base table):**

| Base table | Newest snapshot | Date |
|---|---|---|
| `cik_crd_direct` | `cik_crd_direct_snapshot_20260419_091455` | 2026-04-19 09:14:55 |
| `cik_crd_links` | `cik_crd_links_snapshot_20260419_091455` | 2026-04-19 09:14:55 |
| `cusip_classifications` | `cusip_classifications_snapshot_20260418_172203` | 2026-04-18 17:22:03 |
| `entities` | `entities_snapshot_20260423_084622` | 2026-04-23 08:46:22 |
| `entity_aliases` | `entity_aliases_snapshot_20260423_084622` | 2026-04-23 08:46:22 |
| `entity_classification_history` | `entity_classification_history_snapshot_20260423_084622` | 2026-04-23 08:46:22 |
| `entity_identifiers` | `entity_identifiers_snapshot_20260423_084622` | 2026-04-23 08:46:22 |
| `entity_identifiers_staging` | `entity_identifiers_staging_snapshot_20260423_084622` | 2026-04-23 08:46:22 |
| `entity_overrides_persistent` | `entity_overrides_persistent_snapshot_20260423_084622` | 2026-04-23 08:46:22 |
| `entity_relationships` | `entity_relationships_snapshot_20260423_084622` | 2026-04-23 08:46:22 |
| `entity_relationships_staging` | `entity_relationships_staging_snapshot_20260423_084622` | 2026-04-23 08:46:22 |
| `entity_rollup_history` | `entity_rollup_history_snapshot_20260423_084622` | 2026-04-23 08:46:22 |
| `holdings_v2_manager_type_legacy` | `holdings_v2_manager_type_legacy_snapshot_20260419` | 2026-04-19 |
| `holdings_v2_pct_of_so_pre_apply` | `holdings_v2_pct_of_so_pre_apply_snapshot_20260419` | 2026-04-19 |
| `managers` | `managers_snapshot_20260419_091455` | 2026-04-19 09:14:55 |
| `parent_bridge` | `parent_bridge_snapshot_20260419_091455` | 2026-04-19 09:14:55 |
| `securities` | `securities_snapshot_20260418_172203` | 2026-04-18 17:22:03 |

## 6. Recommendations — Open questions for the policy session

This memo does **not** propose a retention policy. The following questions surfaced during discovery and need answers before a policy is drafted:

1. **Are the 275 intermediate entity/canonical snapshots disposable?** If the newest snapshot per base table (17 of 292) is retained as the current rollback anchor, the remaining 275 intermediate snapshots from the Apr 11-17 entity-QC marathon are arguably superseded. Does the team need point-in-time query capability against the intermediate states, or is the per-session memo record (`project_session_apr11_12_data_qc.md` et al.) sufficient?
2. **Retention of the 2 holdings_v2 pre-apply snapshots.** Both are 12.27M-row full copies taken immediately before large data remediations (manager_type legacy audit, pct_of_so apply). Are they still needed as revert references during the B2.5 / B3 / Q1-Q2 gate window, or has their role been superseded by `docs/REWRITE_PCT_OF_SO_PERIOD_ACCURACY_FINDINGS.md` + migration history in `data_layers.md` Appendix A? These 2 snapshots account for ~80% of total snapshot rows (24.5M of 30.47M).
3. **B2.5 / Q1-Q2 cutover window.** B2.5 completed 2026-04-23 (PR #141). Per `project_session_apr23_phase_b2_5.md`, V1 break-glass stays until Q1 cycle closes (~Aug 2026). Should pre-B2.5 snapshots (specifically the 2026-04-22 and earlier entity-cluster snapshots) be preserved until the 2-cycle gate closes, even though B2.5 did not re-snapshot holdings/filings itself?
4. **B3 coordination.** No `raw_*` snapshots exist, so B3 drops require no snapshot-side coordination. Confirm: this is correct and B3 can proceed without reviewing snapshot retention.
5. **Pending CANONICAL_TABLES.** `fund_classes`, `lei_reference`, `benchmark_weights` were added to CANONICAL_TABLES on 2026-04-21 (sec-05) but have not been promoted and so have no snapshots. Should policy cover "first snapshot will appear when these tables first promote" as a forward-looking clause, or treat as out-of-scope until observed?
6. **Zero-row `entity_relationships_staging` snapshots (32 of them).** Every snapshot of this table has 0 rows because it is the write buffer; `promote_staging.py` snapshots it for FK ordering consistency but the data itself is never the rollback target. Should policy explicitly exempt always-empty staging buffers from retention accounting?
7. **Rollback tool invariant.** `rollback_promotion.py` requires *all* ENTITY_TABLES snapshots for a given `snapshot_id` to exist (it does batch restore). If policy deletes one snapshot of a given cohort (e.g. drops `entities_snapshot_20260412_074237` but keeps the rest), the cohort becomes unrollbackable. Policy must operate on whole cohorts, not individual snapshot tables.

## 7. Appendix — Full snapshot list

All 292 snapshots, sorted by base table then timestamp. Columns: name, base table, creation date-time, age (days, as of 2026-04-24), row count, creator, intent, active references.

| Snapshot | Base | Date | Age (d) | Rows | Creator | Intent | Refs |
|---|---|---|---:|---:|---|---|---|
| `cik_crd_direct_snapshot_20260419_091455` | `cik_crd_direct` | 2026-04-19 09:14:55 | 5 | 4,059 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `cik_crd_links_snapshot_20260419_091455` | `cik_crd_links` | 2026-04-19 09:14:55 | 5 | 448 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `cusip_classifications_snapshot_20260418_172203` | `cusip_classifications` | 2026-04-18 17:22:03 | 6 | 132,618 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entities_snapshot_20260411_180047` | `entities` | 2026-04-11 18:00:47 | 13 | 20,205 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entities_snapshot_20260411_214440` | `entities` | 2026-04-11 21:44:40 | 13 | 20,205 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entities_snapshot_20260411_221854` | `entities` | 2026-04-11 22:18:54 | 13 | 20,205 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entities_snapshot_20260412_061258` | `entities` | 2026-04-12 06:12:58 | 12 | 20,205 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entities_snapshot_20260412_063446` | `entities` | 2026-04-12 06:34:46 | 12 | 20,205 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entities_snapshot_20260412_064353` | `entities` | 2026-04-12 06:43:53 | 12 | 20,205 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entities_snapshot_20260412_074237` | `entities` | 2026-04-12 07:42:37 | 12 | 20,205 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entities_snapshot_20260412_075814` | `entities` | 2026-04-12 07:58:14 | 12 | 20,205 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entities_snapshot_20260412_085048` | `entities` | 2026-04-12 08:50:48 | 12 | 20,205 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entities_snapshot_20260412_092411` | `entities` | 2026-04-12 09:24:11 | 12 | 20,205 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entities_snapshot_20260412_103422` | `entities` | 2026-04-12 10:34:22 | 12 | 20,205 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entities_snapshot_20260412_110029` | `entities` | 2026-04-12 11:00:29 | 12 | 20,205 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entities_snapshot_20260412_112331` | `entities` | 2026-04-12 11:23:31 | 12 | 20,205 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entities_snapshot_20260412_113613` | `entities` | 2026-04-12 11:36:13 | 12 | 20,205 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entities_snapshot_20260412_114749` | `entities` | 2026-04-12 11:47:49 | 12 | 20,205 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entities_snapshot_20260415_174526` | `entities` | 2026-04-15 17:45:26 | 9 | 20,205 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entities_snapshot_20260415_205820` | `entities` | 2026-04-15 20:58:20 | 9 | 23,818 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entities_snapshot_20260416_091539` | `entities` | 2026-04-16 09:15:39 | 8 | 24,347 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entities_snapshot_20260416_161732` | `entities` | 2026-04-16 16:17:32 | 8 | 24,632 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entities_snapshot_20260416_212813` | `entities` | 2026-04-16 21:28:13 | 8 | 24,632 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entities_snapshot_20260416_212955` | `entities` | 2026-04-16 21:29:55 | 8 | 24,632 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entities_snapshot_20260417_055021` | `entities` | 2026-04-17 05:50:21 | 7 | 24,632 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entities_snapshot_20260417_055520` | `entities` | 2026-04-17 05:55:20 | 7 | 24,632 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entities_snapshot_20260417_062514` | `entities` | 2026-04-17 06:25:14 | 7 | 24,632 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entities_snapshot_20260417_072148` | `entities` | 2026-04-17 07:21:48 | 7 | 24,632 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entities_snapshot_20260417_083134` | `entities` | 2026-04-17 08:31:34 | 7 | 24,632 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entities_snapshot_20260417_114536` | `entities` | 2026-04-17 11:45:36 | 7 | 24,861 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entities_snapshot_20260417_122408` | `entities` | 2026-04-17 12:24:08 | 7 | 24,895 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entities_snapshot_20260417_132206` | `entities` | 2026-04-17 13:22:06 | 7 | 26,535 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entities_snapshot_20260417_133018` | `entities` | 2026-04-17 13:30:18 | 7 | 26,535 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entities_snapshot_20260422_090348` | `entities` | 2026-04-22 09:03:48 | 2 | 26,535 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entities_snapshot_20260423_080406` | `entities` | 2026-04-23 08:04:06 | 1 | 26,602 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entities_snapshot_20260423_084622` | `entities` | 2026-04-23 08:46:22 | 1 | 26,602 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_aliases_snapshot_20260411_180047` | `entity_aliases` | 2026-04-11 18:00:47 | 13 | 20,439 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_aliases_snapshot_20260411_214440` | `entity_aliases` | 2026-04-11 21:44:40 | 13 | 20,439 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_aliases_snapshot_20260411_221854` | `entity_aliases` | 2026-04-11 22:18:54 | 13 | 20,439 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_aliases_snapshot_20260412_061258` | `entity_aliases` | 2026-04-12 06:12:58 | 12 | 20,440 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_aliases_snapshot_20260412_063446` | `entity_aliases` | 2026-04-12 06:34:46 | 12 | 20,440 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_aliases_snapshot_20260412_064353` | `entity_aliases` | 2026-04-12 06:43:53 | 12 | 20,441 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_aliases_snapshot_20260412_074237` | `entity_aliases` | 2026-04-12 07:42:37 | 12 | 20,443 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_aliases_snapshot_20260412_075814` | `entity_aliases` | 2026-04-12 07:58:14 | 12 | 20,444 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_aliases_snapshot_20260412_085048` | `entity_aliases` | 2026-04-12 08:50:48 | 12 | 20,540 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_aliases_snapshot_20260412_092411` | `entity_aliases` | 2026-04-12 09:24:11 | 12 | 20,540 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_aliases_snapshot_20260412_103422` | `entity_aliases` | 2026-04-12 10:34:22 | 12 | 20,540 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_aliases_snapshot_20260412_110029` | `entity_aliases` | 2026-04-12 11:00:29 | 12 | 20,540 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_aliases_snapshot_20260412_112331` | `entity_aliases` | 2026-04-12 11:23:31 | 12 | 20,540 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_aliases_snapshot_20260412_113613` | `entity_aliases` | 2026-04-12 11:36:13 | 12 | 20,540 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_aliases_snapshot_20260412_114749` | `entity_aliases` | 2026-04-12 11:47:49 | 12 | 20,540 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_aliases_snapshot_20260415_174526` | `entity_aliases` | 2026-04-15 17:45:26 | 9 | 20,541 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_aliases_snapshot_20260415_205820` | `entity_aliases` | 2026-04-15 20:58:20 | 9 | 24,154 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_aliases_snapshot_20260416_091539` | `entity_aliases` | 2026-04-16 09:15:39 | 8 | 24,683 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_aliases_snapshot_20260416_161732` | `entity_aliases` | 2026-04-16 16:17:32 | 8 | 24,968 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_aliases_snapshot_20260416_212813` | `entity_aliases` | 2026-04-16 21:28:13 | 8 | 24,968 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_aliases_snapshot_20260416_212955` | `entity_aliases` | 2026-04-16 21:29:55 | 8 | 24,968 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_aliases_snapshot_20260417_055021` | `entity_aliases` | 2026-04-17 05:50:21 | 7 | 24,968 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_aliases_snapshot_20260417_055520` | `entity_aliases` | 2026-04-17 05:55:20 | 7 | 24,968 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_aliases_snapshot_20260417_062514` | `entity_aliases` | 2026-04-17 06:25:14 | 7 | 24,968 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_aliases_snapshot_20260417_072148` | `entity_aliases` | 2026-04-17 07:21:48 | 7 | 24,970 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_aliases_snapshot_20260417_083134` | `entity_aliases` | 2026-04-17 08:31:34 | 7 | 24,970 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_aliases_snapshot_20260417_114536` | `entity_aliases` | 2026-04-17 11:45:36 | 7 | 25,199 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_aliases_snapshot_20260417_122408` | `entity_aliases` | 2026-04-17 12:24:08 | 7 | 25,233 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_aliases_snapshot_20260417_132206` | `entity_aliases` | 2026-04-17 13:22:06 | 7 | 26,873 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_aliases_snapshot_20260417_133018` | `entity_aliases` | 2026-04-17 13:30:18 | 7 | 26,873 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_aliases_snapshot_20260422_090348` | `entity_aliases` | 2026-04-22 09:03:48 | 2 | 26,874 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_aliases_snapshot_20260423_080406` | `entity_aliases` | 2026-04-23 08:04:06 | 1 | 26,941 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_aliases_snapshot_20260423_084622` | `entity_aliases` | 2026-04-23 08:46:22 | 1 | 26,941 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_classification_history_snapshot_20260411_180047` | `entity_classification_history` | 2026-04-11 18:00:47 | 13 | 20,242 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_classification_history_snapshot_20260411_214440` | `entity_classification_history` | 2026-04-11 21:44:40 | 13 | 20,242 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_classification_history_snapshot_20260411_221854` | `entity_classification_history` | 2026-04-11 22:18:54 | 13 | 20,242 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_classification_history_snapshot_20260412_061258` | `entity_classification_history` | 2026-04-12 06:12:58 | 12 | 20,242 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_classification_history_snapshot_20260412_063446` | `entity_classification_history` | 2026-04-12 06:34:46 | 12 | 20,245 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_classification_history_snapshot_20260412_064353` | `entity_classification_history` | 2026-04-12 06:43:53 | 12 | 20,245 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_classification_history_snapshot_20260412_074237` | `entity_classification_history` | 2026-04-12 07:42:37 | 12 | 20,245 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_classification_history_snapshot_20260412_075814` | `entity_classification_history` | 2026-04-12 07:58:14 | 12 | 20,245 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_classification_history_snapshot_20260412_085048` | `entity_classification_history` | 2026-04-12 08:50:48 | 12 | 20,245 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_classification_history_snapshot_20260412_092411` | `entity_classification_history` | 2026-04-12 09:24:11 | 12 | 20,248 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_classification_history_snapshot_20260412_103422` | `entity_classification_history` | 2026-04-12 10:34:22 | 12 | 20,248 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_classification_history_snapshot_20260412_110029` | `entity_classification_history` | 2026-04-12 11:00:29 | 12 | 20,248 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_classification_history_snapshot_20260412_112331` | `entity_classification_history` | 2026-04-12 11:23:31 | 12 | 20,248 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_classification_history_snapshot_20260412_113613` | `entity_classification_history` | 2026-04-12 11:36:13 | 12 | 20,248 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_classification_history_snapshot_20260412_114749` | `entity_classification_history` | 2026-04-12 11:47:49 | 12 | 20,248 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_classification_history_snapshot_20260415_174526` | `entity_classification_history` | 2026-04-15 17:45:26 | 9 | 20,248 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_classification_history_snapshot_20260415_205820` | `entity_classification_history` | 2026-04-15 20:58:20 | 9 | 23,861 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_classification_history_snapshot_20260416_091539` | `entity_classification_history` | 2026-04-16 09:15:39 | 8 | 24,390 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_classification_history_snapshot_20260416_161732` | `entity_classification_history` | 2026-04-16 16:17:32 | 8 | 24,675 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_classification_history_snapshot_20260416_212813` | `entity_classification_history` | 2026-04-16 21:28:13 | 8 | 24,690 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_classification_history_snapshot_20260416_212955` | `entity_classification_history` | 2026-04-16 21:29:55 | 8 | 24,690 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_classification_history_snapshot_20260417_055021` | `entity_classification_history` | 2026-04-17 05:50:21 | 7 | 24,690 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_classification_history_snapshot_20260417_055520` | `entity_classification_history` | 2026-04-17 05:55:20 | 7 | 24,690 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_classification_history_snapshot_20260417_062514` | `entity_classification_history` | 2026-04-17 06:25:14 | 7 | 24,690 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_classification_history_snapshot_20260417_072148` | `entity_classification_history` | 2026-04-17 07:21:48 | 7 | 24,690 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_classification_history_snapshot_20260417_083134` | `entity_classification_history` | 2026-04-17 08:31:34 | 7 | 24,690 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_classification_history_snapshot_20260417_114536` | `entity_classification_history` | 2026-04-17 11:45:36 | 7 | 24,919 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_classification_history_snapshot_20260417_122408` | `entity_classification_history` | 2026-04-17 12:24:08 | 7 | 24,953 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_classification_history_snapshot_20260417_132206` | `entity_classification_history` | 2026-04-17 13:22:06 | 7 | 26,593 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_classification_history_snapshot_20260417_133018` | `entity_classification_history` | 2026-04-17 13:30:18 | 7 | 26,593 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_classification_history_snapshot_20260422_090348` | `entity_classification_history` | 2026-04-22 09:03:48 | 2 | 26,595 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_classification_history_snapshot_20260423_080406` | `entity_classification_history` | 2026-04-23 08:04:06 | 1 | 26,662 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_classification_history_snapshot_20260423_084622` | `entity_classification_history` | 2026-04-23 08:46:22 | 1 | 26,662 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_identifiers_snapshot_20260411_180047` | `entity_identifiers` | 2026-04-11 18:00:47 | 13 | 29,074 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_identifiers_snapshot_20260411_214440` | `entity_identifiers` | 2026-04-11 21:44:40 | 13 | 29,074 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_identifiers_snapshot_20260411_221854` | `entity_identifiers` | 2026-04-11 22:18:54 | 13 | 29,074 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_identifiers_snapshot_20260412_061258` | `entity_identifiers` | 2026-04-12 06:12:58 | 12 | 29,074 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_identifiers_snapshot_20260412_063446` | `entity_identifiers` | 2026-04-12 06:34:46 | 12 | 29,074 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_identifiers_snapshot_20260412_064353` | `entity_identifiers` | 2026-04-12 06:43:53 | 12 | 29,074 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_identifiers_snapshot_20260412_074237` | `entity_identifiers` | 2026-04-12 07:42:37 | 12 | 29,077 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_identifiers_snapshot_20260412_075814` | `entity_identifiers` | 2026-04-12 07:58:14 | 12 | 29,077 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_identifiers_snapshot_20260412_085048` | `entity_identifiers` | 2026-04-12 08:50:48 | 12 | 29,091 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_identifiers_snapshot_20260412_092411` | `entity_identifiers` | 2026-04-12 09:24:11 | 12 | 29,091 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_identifiers_snapshot_20260412_103422` | `entity_identifiers` | 2026-04-12 10:34:22 | 12 | 29,091 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_identifiers_snapshot_20260412_110029` | `entity_identifiers` | 2026-04-12 11:00:29 | 12 | 29,091 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_identifiers_snapshot_20260412_112331` | `entity_identifiers` | 2026-04-12 11:23:31 | 12 | 29,091 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_identifiers_snapshot_20260412_113613` | `entity_identifiers` | 2026-04-12 11:36:13 | 12 | 29,091 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_identifiers_snapshot_20260412_114749` | `entity_identifiers` | 2026-04-12 11:47:49 | 12 | 29,091 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_identifiers_snapshot_20260415_174526` | `entity_identifiers` | 2026-04-15 17:45:26 | 9 | 29,092 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_identifiers_snapshot_20260415_205820` | `entity_identifiers` | 2026-04-15 20:58:20 | 9 | 32,705 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_identifiers_snapshot_20260416_091539` | `entity_identifiers` | 2026-04-16 09:15:39 | 8 | 33,234 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_identifiers_snapshot_20260416_161732` | `entity_identifiers` | 2026-04-16 16:17:32 | 8 | 33,521 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_identifiers_snapshot_20260416_212813` | `entity_identifiers` | 2026-04-16 21:28:13 | 8 | 33,521 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_identifiers_snapshot_20260416_212955` | `entity_identifiers` | 2026-04-16 21:29:55 | 8 | 33,521 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_identifiers_snapshot_20260417_055021` | `entity_identifiers` | 2026-04-17 05:50:21 | 7 | 33,521 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_identifiers_snapshot_20260417_055520` | `entity_identifiers` | 2026-04-17 05:55:20 | 7 | 33,521 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_identifiers_snapshot_20260417_062514` | `entity_identifiers` | 2026-04-17 06:25:14 | 7 | 33,521 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_identifiers_snapshot_20260417_072148` | `entity_identifiers` | 2026-04-17 07:21:48 | 7 | 33,522 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_identifiers_snapshot_20260417_083134` | `entity_identifiers` | 2026-04-17 08:31:34 | 7 | 33,522 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_identifiers_snapshot_20260417_114536` | `entity_identifiers` | 2026-04-17 11:45:36 | 7 | 33,746 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_identifiers_snapshot_20260417_122408` | `entity_identifiers` | 2026-04-17 12:24:08 | 7 | 33,781 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_identifiers_snapshot_20260417_132206` | `entity_identifiers` | 2026-04-17 13:22:06 | 7 | 35,444 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_identifiers_snapshot_20260417_133018` | `entity_identifiers` | 2026-04-17 13:30:18 | 7 | 35,444 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_identifiers_snapshot_20260422_090348` | `entity_identifiers` | 2026-04-22 09:03:48 | 2 | 35,444 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_identifiers_snapshot_20260423_080406` | `entity_identifiers` | 2026-04-23 08:04:06 | 1 | 35,511 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_identifiers_snapshot_20260423_084622` | `entity_identifiers` | 2026-04-23 08:46:22 | 1 | 35,511 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_identifiers_staging_snapshot_20260411_180047` | `entity_identifiers_staging` | 2026-04-11 18:00:47 | 13 | 3,503 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_identifiers_staging_snapshot_20260411_214440` | `entity_identifiers_staging` | 2026-04-11 21:44:40 | 13 | 3,503 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_identifiers_staging_snapshot_20260411_221854` | `entity_identifiers_staging` | 2026-04-11 22:18:54 | 13 | 3,503 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_identifiers_staging_snapshot_20260412_061258` | `entity_identifiers_staging` | 2026-04-12 06:12:58 | 12 | 3,503 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_identifiers_staging_snapshot_20260412_063446` | `entity_identifiers_staging` | 2026-04-12 06:34:46 | 12 | 3,503 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_identifiers_staging_snapshot_20260412_064353` | `entity_identifiers_staging` | 2026-04-12 06:43:53 | 12 | 3,503 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_identifiers_staging_snapshot_20260412_074237` | `entity_identifiers_staging` | 2026-04-12 07:42:37 | 12 | 3,503 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_identifiers_staging_snapshot_20260412_075814` | `entity_identifiers_staging` | 2026-04-12 07:58:14 | 12 | 3,503 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_identifiers_staging_snapshot_20260412_085048` | `entity_identifiers_staging` | 2026-04-12 08:50:48 | 12 | 3,503 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_identifiers_staging_snapshot_20260412_092411` | `entity_identifiers_staging` | 2026-04-12 09:24:11 | 12 | 3,503 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_identifiers_staging_snapshot_20260412_103422` | `entity_identifiers_staging` | 2026-04-12 10:34:22 | 12 | 3,503 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_identifiers_staging_snapshot_20260412_110029` | `entity_identifiers_staging` | 2026-04-12 11:00:29 | 12 | 3,503 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_identifiers_staging_snapshot_20260412_112331` | `entity_identifiers_staging` | 2026-04-12 11:23:31 | 12 | 3,503 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_identifiers_staging_snapshot_20260412_113613` | `entity_identifiers_staging` | 2026-04-12 11:36:13 | 12 | 3,503 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_identifiers_staging_snapshot_20260412_114749` | `entity_identifiers_staging` | 2026-04-12 11:47:49 | 12 | 3,503 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_identifiers_staging_snapshot_20260415_174526` | `entity_identifiers_staging` | 2026-04-15 17:45:26 | 9 | 3,503 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_identifiers_staging_snapshot_20260415_205820` | `entity_identifiers_staging` | 2026-04-15 20:58:20 | 9 | 3,503 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_identifiers_staging_snapshot_20260416_091539` | `entity_identifiers_staging` | 2026-04-16 09:15:39 | 8 | 3,503 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_identifiers_staging_snapshot_20260416_161732` | `entity_identifiers_staging` | 2026-04-16 16:17:32 | 8 | 3,503 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_identifiers_staging_snapshot_20260416_212813` | `entity_identifiers_staging` | 2026-04-16 21:28:13 | 8 | 3,503 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_identifiers_staging_snapshot_20260416_212955` | `entity_identifiers_staging` | 2026-04-16 21:29:55 | 8 | 3,503 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_identifiers_staging_snapshot_20260417_055021` | `entity_identifiers_staging` | 2026-04-17 05:50:21 | 7 | 3,503 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_identifiers_staging_snapshot_20260417_055520` | `entity_identifiers_staging` | 2026-04-17 05:55:20 | 7 | 3,503 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_identifiers_staging_snapshot_20260417_062514` | `entity_identifiers_staging` | 2026-04-17 06:25:14 | 7 | 3,503 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_identifiers_staging_snapshot_20260417_072148` | `entity_identifiers_staging` | 2026-04-17 07:21:48 | 7 | 3,503 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_identifiers_staging_snapshot_20260417_083134` | `entity_identifiers_staging` | 2026-04-17 08:31:34 | 7 | 3,503 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_identifiers_staging_snapshot_20260417_114536` | `entity_identifiers_staging` | 2026-04-17 11:45:36 | 7 | 3,503 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_identifiers_staging_snapshot_20260417_122408` | `entity_identifiers_staging` | 2026-04-17 12:24:08 | 7 | 3,503 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_identifiers_staging_snapshot_20260417_132206` | `entity_identifiers_staging` | 2026-04-17 13:22:06 | 7 | 3,503 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_identifiers_staging_snapshot_20260417_133018` | `entity_identifiers_staging` | 2026-04-17 13:30:18 | 7 | 3,503 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_identifiers_staging_snapshot_20260423_080406` | `entity_identifiers_staging` | 2026-04-23 08:04:06 | 1 | 3,503 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_identifiers_staging_snapshot_20260423_084622` | `entity_identifiers_staging` | 2026-04-23 08:46:22 | 1 | 3,503 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_overrides_persistent_snapshot_20260412_092411` | `entity_overrides_persistent` | 2026-04-12 09:24:11 | 12 | 0 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_overrides_persistent_snapshot_20260412_103422` | `entity_overrides_persistent` | 2026-04-12 10:34:22 | 12 | 35 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_overrides_persistent_snapshot_20260412_110029` | `entity_overrides_persistent` | 2026-04-12 11:00:29 | 12 | 35 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_overrides_persistent_snapshot_20260412_112331` | `entity_overrides_persistent` | 2026-04-12 11:23:31 | 12 | 41 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_overrides_persistent_snapshot_20260412_113613` | `entity_overrides_persistent` | 2026-04-12 11:36:13 | 12 | 41 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_overrides_persistent_snapshot_20260412_114749` | `entity_overrides_persistent` | 2026-04-12 11:47:49 | 12 | 47 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_overrides_persistent_snapshot_20260415_174526` | `entity_overrides_persistent` | 2026-04-15 17:45:26 | 9 | 47 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_overrides_persistent_snapshot_20260415_205820` | `entity_overrides_persistent` | 2026-04-15 20:58:20 | 9 | 47 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_overrides_persistent_snapshot_20260416_091539` | `entity_overrides_persistent` | 2026-04-16 09:15:39 | 8 | 47 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_overrides_persistent_snapshot_20260416_161732` | `entity_overrides_persistent` | 2026-04-16 16:17:32 | 8 | 47 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_overrides_persistent_snapshot_20260416_212813` | `entity_overrides_persistent` | 2026-04-16 21:28:13 | 8 | 82 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_overrides_persistent_snapshot_20260416_212955` | `entity_overrides_persistent` | 2026-04-16 21:29:55 | 8 | 82 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_overrides_persistent_snapshot_20260417_055021` | `entity_overrides_persistent` | 2026-04-17 05:50:21 | 7 | 90 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_overrides_persistent_snapshot_20260417_055520` | `entity_overrides_persistent` | 2026-04-17 05:55:20 | 7 | 90 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_overrides_persistent_snapshot_20260417_062514` | `entity_overrides_persistent` | 2026-04-17 06:25:14 | 7 | 105 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_overrides_persistent_snapshot_20260417_072148` | `entity_overrides_persistent` | 2026-04-17 07:21:48 | 7 | 107 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_overrides_persistent_snapshot_20260417_083134` | `entity_overrides_persistent` | 2026-04-17 08:31:34 | 7 | 198 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_overrides_persistent_snapshot_20260417_114536` | `entity_overrides_persistent` | 2026-04-17 11:45:36 | 7 | 198 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_overrides_persistent_snapshot_20260417_122408` | `entity_overrides_persistent` | 2026-04-17 12:24:08 | 7 | 204 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_overrides_persistent_snapshot_20260417_132206` | `entity_overrides_persistent` | 2026-04-17 13:22:06 | 7 | 204 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_overrides_persistent_snapshot_20260417_133018` | `entity_overrides_persistent` | 2026-04-17 13:30:18 | 7 | 221 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_overrides_persistent_snapshot_20260423_080406` | `entity_overrides_persistent` | 2026-04-23 08:04:06 | 1 | 245 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_overrides_persistent_snapshot_20260423_084622` | `entity_overrides_persistent` | 2026-04-23 08:46:22 | 1 | 256 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_relationships_snapshot_20260411_180047` | `entity_relationships` | 2026-04-11 18:00:47 | 13 | 13,685 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_relationships_snapshot_20260411_214440` | `entity_relationships` | 2026-04-11 21:44:40 | 13 | 13,685 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_relationships_snapshot_20260411_221854` | `entity_relationships` | 2026-04-11 22:18:54 | 13 | 13,685 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_relationships_snapshot_20260412_061258` | `entity_relationships` | 2026-04-12 06:12:58 | 12 | 13,685 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_relationships_snapshot_20260412_063446` | `entity_relationships` | 2026-04-12 06:34:46 | 12 | 13,685 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_relationships_snapshot_20260412_064353` | `entity_relationships` | 2026-04-12 06:43:53 | 12 | 13,685 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_relationships_snapshot_20260412_074237` | `entity_relationships` | 2026-04-12 07:42:37 | 12 | 13,685 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_relationships_snapshot_20260412_075814` | `entity_relationships` | 2026-04-12 07:58:14 | 12 | 13,685 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_relationships_snapshot_20260412_085048` | `entity_relationships` | 2026-04-12 08:50:48 | 12 | 13,685 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_relationships_snapshot_20260412_092411` | `entity_relationships` | 2026-04-12 09:24:11 | 12 | 13,685 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_relationships_snapshot_20260412_103422` | `entity_relationships` | 2026-04-12 10:34:22 | 12 | 13,685 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_relationships_snapshot_20260412_110029` | `entity_relationships` | 2026-04-12 11:00:29 | 12 | 13,685 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_relationships_snapshot_20260412_112331` | `entity_relationships` | 2026-04-12 11:23:31 | 12 | 13,685 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_relationships_snapshot_20260412_113613` | `entity_relationships` | 2026-04-12 11:36:13 | 12 | 13,685 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_relationships_snapshot_20260412_114749` | `entity_relationships` | 2026-04-12 11:47:49 | 12 | 13,685 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_relationships_snapshot_20260415_174526` | `entity_relationships` | 2026-04-15 17:45:26 | 9 | 13,685 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_relationships_snapshot_20260415_205820` | `entity_relationships` | 2026-04-15 20:58:20 | 9 | 17,298 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_relationships_snapshot_20260416_091539` | `entity_relationships` | 2026-04-16 09:15:39 | 8 | 17,826 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_relationships_snapshot_20260416_161732` | `entity_relationships` | 2026-04-16 16:17:32 | 8 | 18,105 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_relationships_snapshot_20260416_212813` | `entity_relationships` | 2026-04-16 21:28:13 | 8 | 18,105 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_relationships_snapshot_20260416_212955` | `entity_relationships` | 2026-04-16 21:29:55 | 8 | 18,105 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_relationships_snapshot_20260417_055021` | `entity_relationships` | 2026-04-17 05:50:21 | 7 | 18,105 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_relationships_snapshot_20260417_055520` | `entity_relationships` | 2026-04-17 05:55:20 | 7 | 18,105 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_relationships_snapshot_20260417_062514` | `entity_relationships` | 2026-04-17 06:25:14 | 7 | 18,105 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_relationships_snapshot_20260417_072148` | `entity_relationships` | 2026-04-17 07:21:48 | 7 | 18,105 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_relationships_snapshot_20260417_083134` | `entity_relationships` | 2026-04-17 08:31:34 | 7 | 18,111 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_relationships_snapshot_20260417_114536` | `entity_relationships` | 2026-04-17 11:45:36 | 7 | 18,334 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_relationships_snapshot_20260417_122408` | `entity_relationships` | 2026-04-17 12:24:08 | 7 | 18,365 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_relationships_snapshot_20260417_132206` | `entity_relationships` | 2026-04-17 13:22:06 | 7 | 18,365 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_relationships_snapshot_20260417_133018` | `entity_relationships` | 2026-04-17 13:30:18 | 7 | 18,365 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_relationships_snapshot_20260423_080406` | `entity_relationships` | 2026-04-23 08:04:06 | 1 | 18,365 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_relationships_snapshot_20260423_084622` | `entity_relationships` | 2026-04-23 08:46:22 | 1 | 18,365 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_relationships_staging_snapshot_20260411_180047` | `entity_relationships_staging` | 2026-04-11 18:00:47 | 13 | 0 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_relationships_staging_snapshot_20260411_214440` | `entity_relationships_staging` | 2026-04-11 21:44:40 | 13 | 0 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_relationships_staging_snapshot_20260411_221854` | `entity_relationships_staging` | 2026-04-11 22:18:54 | 13 | 0 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_relationships_staging_snapshot_20260412_061258` | `entity_relationships_staging` | 2026-04-12 06:12:58 | 12 | 0 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_relationships_staging_snapshot_20260412_063446` | `entity_relationships_staging` | 2026-04-12 06:34:46 | 12 | 0 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_relationships_staging_snapshot_20260412_064353` | `entity_relationships_staging` | 2026-04-12 06:43:53 | 12 | 0 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_relationships_staging_snapshot_20260412_074237` | `entity_relationships_staging` | 2026-04-12 07:42:37 | 12 | 0 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_relationships_staging_snapshot_20260412_075814` | `entity_relationships_staging` | 2026-04-12 07:58:14 | 12 | 0 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_relationships_staging_snapshot_20260412_085048` | `entity_relationships_staging` | 2026-04-12 08:50:48 | 12 | 0 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_relationships_staging_snapshot_20260412_092411` | `entity_relationships_staging` | 2026-04-12 09:24:11 | 12 | 0 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_relationships_staging_snapshot_20260412_103422` | `entity_relationships_staging` | 2026-04-12 10:34:22 | 12 | 0 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_relationships_staging_snapshot_20260412_110029` | `entity_relationships_staging` | 2026-04-12 11:00:29 | 12 | 0 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_relationships_staging_snapshot_20260412_112331` | `entity_relationships_staging` | 2026-04-12 11:23:31 | 12 | 0 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_relationships_staging_snapshot_20260412_113613` | `entity_relationships_staging` | 2026-04-12 11:36:13 | 12 | 0 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_relationships_staging_snapshot_20260412_114749` | `entity_relationships_staging` | 2026-04-12 11:47:49 | 12 | 0 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_relationships_staging_snapshot_20260415_174526` | `entity_relationships_staging` | 2026-04-15 17:45:26 | 9 | 0 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_relationships_staging_snapshot_20260415_205820` | `entity_relationships_staging` | 2026-04-15 20:58:20 | 9 | 0 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_relationships_staging_snapshot_20260416_091539` | `entity_relationships_staging` | 2026-04-16 09:15:39 | 8 | 0 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_relationships_staging_snapshot_20260416_161732` | `entity_relationships_staging` | 2026-04-16 16:17:32 | 8 | 0 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_relationships_staging_snapshot_20260416_212813` | `entity_relationships_staging` | 2026-04-16 21:28:13 | 8 | 0 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_relationships_staging_snapshot_20260416_212955` | `entity_relationships_staging` | 2026-04-16 21:29:55 | 8 | 0 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_relationships_staging_snapshot_20260417_055021` | `entity_relationships_staging` | 2026-04-17 05:50:21 | 7 | 0 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_relationships_staging_snapshot_20260417_055520` | `entity_relationships_staging` | 2026-04-17 05:55:20 | 7 | 0 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_relationships_staging_snapshot_20260417_062514` | `entity_relationships_staging` | 2026-04-17 06:25:14 | 7 | 0 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_relationships_staging_snapshot_20260417_072148` | `entity_relationships_staging` | 2026-04-17 07:21:48 | 7 | 0 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_relationships_staging_snapshot_20260417_083134` | `entity_relationships_staging` | 2026-04-17 08:31:34 | 7 | 0 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_relationships_staging_snapshot_20260417_114536` | `entity_relationships_staging` | 2026-04-17 11:45:36 | 7 | 0 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_relationships_staging_snapshot_20260417_122408` | `entity_relationships_staging` | 2026-04-17 12:24:08 | 7 | 0 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_relationships_staging_snapshot_20260417_132206` | `entity_relationships_staging` | 2026-04-17 13:22:06 | 7 | 0 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_relationships_staging_snapshot_20260417_133018` | `entity_relationships_staging` | 2026-04-17 13:30:18 | 7 | 0 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_relationships_staging_snapshot_20260423_080406` | `entity_relationships_staging` | 2026-04-23 08:04:06 | 1 | 0 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_relationships_staging_snapshot_20260423_084622` | `entity_relationships_staging` | 2026-04-23 08:46:22 | 1 | 0 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_rollup_history_snapshot_20260411_180047` | `entity_rollup_history` | 2026-04-11 18:00:47 | 13 | 45,137 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_rollup_history_snapshot_20260411_214440` | `entity_rollup_history` | 2026-04-11 21:44:40 | 13 | 45,141 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_rollup_history_snapshot_20260411_221854` | `entity_rollup_history` | 2026-04-11 22:18:54 | 13 | 45,151 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_rollup_history_snapshot_20260412_061258` | `entity_rollup_history` | 2026-04-12 06:12:58 | 12 | 45,179 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_rollup_history_snapshot_20260412_063446` | `entity_rollup_history` | 2026-04-12 06:34:46 | 12 | 45,179 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_rollup_history_snapshot_20260412_064353` | `entity_rollup_history` | 2026-04-12 06:43:53 | 12 | 45,181 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_rollup_history_snapshot_20260412_074237` | `entity_rollup_history` | 2026-04-12 07:42:37 | 12 | 45,185 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_rollup_history_snapshot_20260412_075814` | `entity_rollup_history` | 2026-04-12 07:58:14 | 12 | 45,207 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_rollup_history_snapshot_20260412_085048` | `entity_rollup_history` | 2026-04-12 08:50:48 | 12 | 46,844 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_rollup_history_snapshot_20260412_092411` | `entity_rollup_history` | 2026-04-12 09:24:11 | 12 | 46,844 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_rollup_history_snapshot_20260412_103422` | `entity_rollup_history` | 2026-04-12 10:34:22 | 12 | 46,844 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_rollup_history_snapshot_20260412_110029` | `entity_rollup_history` | 2026-04-12 11:00:29 | 12 | 46,848 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_rollup_history_snapshot_20260412_112331` | `entity_rollup_history` | 2026-04-12 11:23:31 | 12 | 46,848 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_rollup_history_snapshot_20260412_113613` | `entity_rollup_history` | 2026-04-12 11:36:13 | 12 | 46,850 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_rollup_history_snapshot_20260412_114749` | `entity_rollup_history` | 2026-04-12 11:47:49 | 12 | 46,851 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_rollup_history_snapshot_20260415_174526` | `entity_rollup_history` | 2026-04-15 17:45:26 | 9 | 46,854 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_rollup_history_snapshot_20260415_205820` | `entity_rollup_history` | 2026-04-15 20:58:20 | 9 | 54,080 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_rollup_history_snapshot_20260416_091539` | `entity_rollup_history` | 2026-04-16 09:15:39 | 8 | 55,138 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_rollup_history_snapshot_20260416_161732` | `entity_rollup_history` | 2026-04-16 16:17:32 | 8 | 55,708 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_rollup_history_snapshot_20260416_212813` | `entity_rollup_history` | 2026-04-16 21:28:13 | 8 | 55,725 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_rollup_history_snapshot_20260416_212955` | `entity_rollup_history` | 2026-04-16 21:29:55 | 8 | 55,725 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_rollup_history_snapshot_20260417_055021` | `entity_rollup_history` | 2026-04-17 05:50:21 | 7 | 55,733 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_rollup_history_snapshot_20260417_055520` | `entity_rollup_history` | 2026-04-17 05:55:20 | 7 | 55,733 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_rollup_history_snapshot_20260417_062514` | `entity_rollup_history` | 2026-04-17 06:25:14 | 7 | 55,748 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_rollup_history_snapshot_20260417_072148` | `entity_rollup_history` | 2026-04-17 07:21:48 | 7 | 55,752 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_rollup_history_snapshot_20260417_083134` | `entity_rollup_history` | 2026-04-17 08:31:34 | 7 | 55,843 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_rollup_history_snapshot_20260417_114536` | `entity_rollup_history` | 2026-04-17 11:45:36 | 7 | 56,301 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_rollup_history_snapshot_20260417_122408` | `entity_rollup_history` | 2026-04-17 12:24:08 | 7 | 56,483 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_rollup_history_snapshot_20260417_132206` | `entity_rollup_history` | 2026-04-17 13:22:06 | 7 | 59,763 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_rollup_history_snapshot_20260417_133018` | `entity_rollup_history` | 2026-04-17 13:30:18 | 7 | 59,780 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_rollup_history_snapshot_20260422_090348` | `entity_rollup_history` | 2026-04-22 09:03:48 | 2 | 59,804 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_rollup_history_snapshot_20260423_080406` | `entity_rollup_history` | 2026-04-23 08:04:06 | 1 | 59,938 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `entity_rollup_history_snapshot_20260423_084622` | `entity_rollup_history` | 2026-04-23 08:46:22 | 1 | 59,938 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `holdings_v2_manager_type_legacy_snapshot_20260419` | `holdings_v2_manager_type_legacy` | 2026-04-19 | 5 | 12,270,984 | SESSION (one-off script) | REFERENCE | NONE |
| `holdings_v2_pct_of_so_pre_apply_snapshot_20260419` | `holdings_v2_pct_of_so_pre_apply` | 2026-04-19 | 5 | 12,270,984 | SESSION (one-off script) | REFERENCE | NONE |
| `managers_snapshot_20260419_091455` | `managers` | 2026-04-19 09:14:55 | 5 | 12,005 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `parent_bridge_snapshot_20260419_091455` | `parent_bridge` | 2026-04-19 09:14:55 | 5 | 11,135 | SESSION (promote_staging.py) | ROLLBACK | NONE |
| `securities_snapshot_20260418_172203` | `securities` | 2026-04-18 17:22:03 | 6 | 132,618 | SESSION (promote_staging.py) | ROLLBACK | NONE |

## 8. Closure note — snapshot-policy session (2026-04-24)

Policy applied 2026-04-24 in session **snapshot-policy** (migration `018_snapshot_registry` + `scripts/hygiene/backfill_snapshot_registry.py` + `scripts/hygiene/snapshot_retention.py`). The sidecar `snapshot_registry` table records per-snapshot creator / purpose / expiration / approver. 292 snapshots backfilled: 290 under `default_14d` with `expiration = created_at + 14 days`, 2 `holdings_v2_*` under `carve_out` through 2026-05-31 (V2 cutover insurance, approved by Serge). **0 snapshots deleted on apply** — every default_14d row remained within its 14-day window as of 2026-04-24 (oldest cohort expires 2026-04-25). The enforcement script is live under `--dry-run` default / `--apply` opt-in; cadence wiring is tracked as `snapshot-retention-cadence` in `ROADMAP.md § Current backlog`. Creation-site tagging is in place: `scripts/promote_staging.py::_take_snapshot` now writes a registry row on every snapshot it mints.
