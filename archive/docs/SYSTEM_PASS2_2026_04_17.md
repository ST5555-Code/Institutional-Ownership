# System Pass 2 — 2026-04-17

Reviewer 3 (Claude Opus 4.7 1M, ultrathink). Surgical follow-up to Pass 1 (atlas) and Reviewer 2 (Codex). Read-only, no writes.

## Meta

- **HEAD at audit start:** `da418a1e8cf766db8089026c2d50ef981ae41ae1` (`da418a1`, `main`). Re-verified via `git rev-parse HEAD`.
- **Atlas consumed:** `docs/SYSTEM_ATLAS_2026_04_17.md` (675 lines, 60 findings). Lives in sibling worktree `competent-meitner-ac5cdf`.
- **Codex consumed:** `docs/CODEX_REVIEW_2026_04_17.md` (202 lines, 39 findings). Main-repo copy.
- **Primary DB:** `/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership/data/13f.duckdb` (11 GB). Queried via `duckdb.connect(read_only=True)` — no `duckdb` CLI present, used Python driver instead.
- **Worktree:** `gallant-noyce-cc6140` at `da418a1`. Atlas + Codex pinned to same HEAD.
- **Five adopted corrections from Codex:** Flask→FastAPI (O-02/O-03), PROCESS_RULES naming of `fetch_13dg.py` (DOC-07), REACT_MIGRATION.md:121 accuracy (DOC-08), validate_classifications staging-only (C-03), 13D/G fetch not stalled (P-03). Not re-litigated here.
- **Session count:** 1.
- **Completeness:** COMPLETE. All six tasks + four BLOCK verifications delivered.

---

## 0. Production-Critical Surprises

One surprise surfaced beyond the six tasks. Flagging up-front:

**S-01 [MAJOR]** `scripts/admin_bp.py:258-265` whitelists the retired `fetch_nport.py` as a user-runnable script. This is the exact trigger that recreated the legacy `fund_holdings` table on 2026-04-14 21:22 (see §2). Until `fetch_nport.py` is either surgically modified or removed from the allowlist, any admin clicking "refresh N-PORT" silently re-resurrects the legacy fact table. The allowlist also carries `unify_positions.py`, which is already under `scripts/retired/` per the atlas.

**S-02 [MAJOR]** `add_last_refreshed_at.py` ran on prod — the column is populated on 14,181 of 18,500 `entity_relationships` rows (76.8%) — but the migration **never stamped `schema_versions`**. Live state disagrees with the migration-tracking table. Any audit that reads `schema_versions` to decide "was this applied?" gets the wrong answer. Either the script is incomplete or the call is missing a `INSERT INTO schema_versions` line.

---

## 1. Entity-Enrichment Collapse — Root Cause

**Verdict: dual failure mode. Primary driver is an *enrichment-backfill gap*, not just input collapse as implied by the atlas / Codex framing.**

### The data the atlas didn't have

For every `report_month`, I split NULL-entity_id rows into two populations: rows whose `series_id` **is** in `entity_identifiers` today (would resolve on re-enrichment), versus rows whose `series_id` is still unresolvable.

| report_month | rows | entity_id NULL | NULL-but-resolvable | NULL-unresolvable | resolvable-share-of-NULL |
|---|---:|---:|---:|---:|---:|
| 2025-09 | 1,419,322 | 932,164 | 809,291 | 122,873 | **86.8%** |
| 2025-10 | 1,306,425 | 1,234,552 | 1,164,448 | 70,104 | **94.3%** |
| 2025-11 | 2,001,782 | 1,998,226 | 955,273 | 1,042,953 | **47.8%** |
| 2025-12 | 2,514,494 | 2,499,277 | 1,912,229 | 587,048 | **76.5%** |
| 2026-01 | 1,321,332 | 1,243,631 | 1,173,382 | 70,249 | **94.4%** |

(Query: `LEFT JOIN entity_identifiers ei ON fh.series_id = ei.identifier_value WHERE ei.identifier_type='series_id' AND ei.valid_to = DATE '9999-12-31'`, run 2026-04-17.)

Read this table: the dominant failure mode is not "incoming series_ids can't be resolved." It is **"enrichment never re-ran against rows that would resolve now."**

### The code boundary

[scripts/promote_nport.py:153-218](scripts/promote_nport.py:153) — `_bulk_enrich_run(prod_con, series_touched)`:

```python
WHERE ei.identifier_type = 'series_id'
  AND ei.valid_to = DATE '9999-12-31'
  AND ei.identifier_value IN ({placeholders})  # <- bound from series_touched
...
WHERE fh.series_id = e.series_id
  AND fh.series_id IN ({placeholders})         # <- same scope
```

`series_touched` is computed from `_staged_tuples()` and contains only series promoted in *this* run ([scripts/promote_nport.py:225-237](scripts/promote_nport.py:225), [:428-441](scripts/promote_nport.py:428)). Rows previously promoted whose `series_id` *later* became resolvable in `entity_identifiers` are never revisited. The enrichment is run-scoped, not table-scoped.

### Why the collapse tracks recent months

Two vectors compound:

1. **Session #11 added 1,640 new entities** on 2026-04-16/17 (atlas §4.2 claim #2). Many of those rollups now cover series_ids that were ingested in 2025-10/11/12 promotes — before their MDM rows existed. Without a backfill pass, those rows stay NULL.
2. **DERA ZIP Session 2** (2026-04-15 `e868772`, atlas memory ref) landed 2.9M new rows for 2025-11 and 2025-12 report_months in a single burst. Those series largely resolve now — but weren't in `entity_identifiers` at promote time, and `_bulk_enrich_run` never revisits them.

### Secondary driver (real but smaller)

The 1,042,953 unresolvable rows for 2025-11 (52.2% of that month's NULLs) and 587,048 for 2025-12 (23.5%) are true input collapse — series that do not yet exist in `entity_identifiers` at all. Codex's framing applies to *these* rows. Task-1 agent observed `pending_entity_resolution` carries ~1,523 series_id rows including ~1,186 synthetic `{cik}_{accession}` fallbacks — those will never resolve automatically.

### Proposed structural fix (do not apply)

Decouple enrichment from promote:

1. Add `scripts/enrich_fund_holdings_v2.py` or extend `enrich_holdings.py` with a `fund_holdings_v2` branch — a standalone, idempotent job that runs `_bulk_enrich_run` over the entire set of series_ids with NULL entity_id (not `series_touched`). Run after every entity MDM change (promote_staging completion hook) and as a nightly sweep.
2. In `promote_nport.py`, leave `_bulk_enrich_run` in place as the per-run fast path, but drop its role as the only enrichment surface.
3. For the truly-unresolvable tail, the entity gate at `scripts/pipeline/shared.py:237-385` already routes to `pending_entity_resolution`. No change needed there — just visibility (an admin tab that flags series queued > N days).

Expected recovery: 2025-10/2026-01 back to ≥94% coverage on first backfill run; 2025-11/12 to ≥48%/76% pending further MDM work on the unresolvable tail.

---

## 2. Legacy `fund_holdings` Writer — Identified

### Writer

Single active writer: **[scripts/fetch_nport.py:467-480](scripts/fetch_nport.py:467)** (INSERT via `executemany`) and **[scripts/fetch_nport.py:546-555](scripts/fetch_nport.py:546)** (UPDATE enrichment). The script also re-creates the table via `CREATE TABLE IF NOT EXISTS` at [scripts/fetch_nport.py:377-398](scripts/fetch_nport.py:377), which is why the 2026-04-13 DROP did not stick.

Secondary UPDATE writer: **[scripts/build_fund_classes.py:149-155](scripts/build_fund_classes.py:149)** — updates `fund_holdings.lei` column. Runs only if the table exists, so its blast radius is contingent on #1.

### Trigger

[scripts/admin_bp.py:258-265](scripts/admin_bp.py:258) — `/api/admin/run_script` whitelist includes `'fetch_nport.py'`. Admin UI call spawns `python3 -u scripts/fetch_nport.py` via [scripts/admin_bp.py:278-283](scripts/admin_bp.py:278). The 2026-04-14 21:22 write batch (22,030 rows across 13 funds, 6-second window) is consistent with a single admin click.

No cron / scheduler triggers `fetch_nport.py`. No CI path runs it.

### Blast radius — readers

- **[scripts/build_benchmark_weights.py:79-95](scripts/build_benchmark_weights.py:79)** — reads `fund_holdings` for one hardcoded series (`S000002848`, Vanguard Total Stock Market) as a coverage probe.
- **[scripts/fetch_nport.py](scripts/fetch_nport.py) self-reads** — count checks at lines 414-430, 558, 668, 778, 872. All internal; no external dependency.
- **No `/api/v1/*`, `/api/admin/*`, or `web/react-app/` reads** of `fund_holdings` (verified by grep).
- **No SQL view, materialized aggregate, or downstream derived-table dependency** (verified).

### Doc reconciliation

- `ENTITY_ARCHITECTURE.md:287-293` says the table was dropped on 2026-04-13. **Stale** — it was dropped, then resurrected 2026-04-14 21:22 by `fetch_nport.py`.
- `MAINTENANCE.md:120-123` authorizes the drop on/after 2026-05-09. **Still accurate as a forward-looking date.**

### Recommended removal sequence

1. Remove `'fetch_nport.py'` from the admin allowlist at [scripts/admin_bp.py:258-265](scripts/admin_bp.py:258). This is the one-line fix that stops the bleeding — does not break v2.
2. Repoint [scripts/build_benchmark_weights.py:79-95](scripts/build_benchmark_weights.py:79) at `fund_holdings_v2` for the Vanguard-TSM coverage probe.
3. Remove the `fund_holdings.lei` UPDATE at [scripts/build_fund_classes.py:149-155](scripts/build_fund_classes.py:149) (or repoint to v2).
4. Move `scripts/fetch_nport.py` to `scripts/retired/` alongside the other superseded loaders.
5. On or after 2026-05-09 per MAINTENANCE.md, `DROP TABLE fund_holdings`.

---

## 3. `_mirror_manifest_and_impacts` — Structural Fix

### Call-site inventory (exhaustive)

Two active implementations — the atlas and Codex had both, but framed them as two sites of one pattern. They are in fact **two independent implementations that have already drifted from each other**.

| Site | File | Lines | Form | Preserve-promoted fix applied? |
|---|---|---|---|---|
| 1 | `scripts/promote_nport.py` | [81-146](scripts/promote_nport.py:81) | Named function `_mirror_manifest_and_impacts` | Yes (2026-04-17 bugfix) |
| 2 | `scripts/promote_13dg.py` | [203-269](scripts/promote_13dg.py:203) | Inline in `main()`, no function | Yes (same bugfix window) |

Related manifest/impacts touchpoints that are **not** mirrors (verified — checked and classified):

| File | Lines | Purpose | Classification |
|---|---|---|---|
| `scripts/pipeline/manifest.py` | [58-193](scripts/pipeline/manifest.py:58) | `get_or_create_manifest_row`, `write_impact`, `update_impact_status` | Canonical single-DB writer. Not a mirror. |
| `scripts/pipeline/shared.py` | [422, 450](scripts/pipeline/shared.py:422) | `INSERT INTO ingestion_manifest/impacts` for L3/MDM direct writes | Direct-write path. Does not cross staging↔prod. |
| `scripts/fetch_market.py` | [746](scripts/fetch_market.py:746) | `UPDATE ingestion_impacts` to mark promoted | Single-DB; fetch_market writes prod directly (no staging). |
| `scripts/fetch_dera_nport.py` | [813](scripts/fetch_dera_nport.py:813) | Same — per-manifest impact-status update, staging-side | Single-DB; not a mirror. |
| `scripts/fetch_nport_v2.py` | [789](scripts/fetch_nport_v2.py:789) | `UPDATE ingestion_impacts` on staging during promote setup | Single-DB. |

Result: exactly two mirror sites. Both are in promote scripts. Both still duplicate logic.

### Regression surface

- **Admin refresh framework (paused)** — `Plans/admin_refresh_system_design.md:68-85` proposes a new `SourcePipeline.run()` orchestrator that will handle staging→prod manifest mirroring itself. Without a canonical helper, the framework's base-class implementation will be a third reimplementation.
- **Future `load_13f_v2.py`** (planned per roadmap, May 16 window) — any new fetch/promote pair that carries its own mirror will be a fourth.
- **Migration 008 backfill** (proposed in admin-refresh design) — proposes `is_latest` plus append-only semantics that will require its own manifest rewrite.

The pattern has already duplicated twice without being factored out. Absent intervention, it will duplicate at least twice more.

### Proposed structural fix (do not apply)

Add one function to `scripts/pipeline/manifest.py`:

```python
def mirror_manifest_and_impacts(
    *,
    prod_con: Any,
    staging_con: Any,
    run_id: str,
    source_type: str,
    preserve_promoted: bool = True,
) -> tuple[list[int], int]:
    """Canonical staging→prod mirror of ingestion_manifest + ingestion_impacts
    for one (source_type, run_id). Returns (manifest_ids, impact_rows_copied).

    - Replace manifest rows wholesale (no promote state on manifest).
    - Preserve prod impacts already `promote_status='promoted'` unless
      caller passes preserve_promoted=False (for rollback paths).
    - Single code path; two promote scripts and the future admin-refresh
      framework all delegate here.
    """
```

Then:
- [scripts/promote_nport.py:81-146](scripts/promote_nport.py:81) collapses to one call; delete the local function.
- [scripts/promote_13dg.py:203-269](scripts/promote_13dg.py:203) collapses to one call; delete the inline block.
- Admin-refresh `SourcePipeline.run()` calls the same helper.

Deprecation note: both local implementations can be left stubbed to the helper for one release cycle, then removed.

Critical second fix: the helper should run inside an enclosing `BEGIN TRANSACTION` / `COMMIT` paired with the promote DELETE+INSERT (see §7). That is the atomicity gap, and it is best fixed at the same time the helper lands — otherwise extracting the function is a lift-and-shift that preserves the existing non-atomic semantics.

---

## 4. Admin Refresh Schema Reconciliation

### 4a. `ingestion_manifest` column delta

Live DDL: [scripts/migrations/001_pipeline_control_plane.py:53-82](scripts/migrations/001_pipeline_control_plane.py:53).

Design references (`Plans/admin_refresh_system_design.md`):

| Design column | Live column | Classification | Design ref |
|---|---|---|---|
| `pipeline_name` | `source_type` | **RENAMED-FROM** | `admin_refresh_system_design.md:68-70`, `:83-85`, `:509-514` (Codex cites) |
| `status` (values: `fetching`, `parsing`, `validating`, `pending_approval`, `approved`, `promoting`, `verifying`, `complete`, `failed`, `rejected`, `expired`) | `fetch_status` (values: `pending`, `fetching`, `complete`, `failed`, `skipped`) | **RENAMED-FROM + enum incompatible** | `admin_refresh_system_design.md:230-244` |
| `completed_at` | `fetch_completed_at` | **RENAMED-FROM** | `admin_refresh_system_design.md:68-70` |
| `row_counts_json` | — | **FICTIONAL** | `admin_refresh_system_design.md:712-716` (per Codex) |
| `run_id` | `run_id` | EXISTS | — |
| `accession_number` | `accession_number` | EXISTS | — |
| `object_key` | `object_key` (UNIQUE) | EXISTS | — |
| `source_url` | `source_url` | EXISTS | — |
| `fetch_started_at` | `fetch_started_at` | EXISTS | — |
| `is_amendment` | `is_amendment` | EXISTS | — |
| `superseded_by_manifest_id` | `superseded_by_manifest_id` | EXISTS | — |

### 4b. `ingestion_impacts` column delta

Live DDL: [scripts/migrations/001_pipeline_control_plane.py:88-110](scripts/migrations/001_pipeline_control_plane.py:88).

| Design column | Live column | Classification | Design ref |
|---|---|---|---|
| `run_id` | — (must `JOIN ingestion_manifest USING(manifest_id)`) | **FICTIONAL on this table** | `admin_refresh_system_design.md:83` |
| `action` (values: `insert`, `flip_is_latest`, `scd_supersede`) | — (has `load_status`, `promote_status`) | **FICTIONAL — different state model** | `admin_refresh_system_design.md:44`, `:83` |
| `rowkey` | `unit_key_json` | **SEMANTICALLY-CLOSE** (same role, different encoding) | `admin_refresh_system_design.md:83` |
| `prior_accession` | — on this table (exists on `ingestion_manifest`) | **FICTIONAL on this table** | `admin_refresh_system_design.md:421-423` |
| `unit_type` | `unit_type` | EXISTS | — |
| `target_table` | `target_table` | EXISTS | — |
| `validation_tier` | `validation_tier` | EXISTS | — |

### 4c. Protocol contract delta

Live contract: [scripts/pipeline/protocol.py:117-187](scripts/pipeline/protocol.py:117) (`SourcePipeline`, structural `typing.Protocol` with `@runtime_checkable`). Design: `Plans/admin_refresh_system_design.md:354-418` (`SourcePipeline` as `abc.ABC`).

| Design method | Live Protocol method | Overlap | Genuine new surface |
|---|---|---|---|
| `fetch(scope, staging_con)` | `fetch(target, run_id) -> FetchResult` | Same intent, different signature. Design takes a `scope` dict (quarter, month); existing takes a `DownloadTarget` — the scope is pre-resolved by `discover()`. Existing is tighter. | No |
| `parse(staging_con)` | `parse(fetch_result) -> ParseResult` | **Incompatible.** Existing `parse()` is a *pure function* (no DB). Design `parse()` writes to staging. Breaks the existing testability invariant. | No — existing is better |
| `target_table_spec()` | — | — | **Yes** |
| `run(scope)` | — (orchestration is per-script `main()` today) | — | **Yes** (this is the real new surface) |
| `validate()` | `validate(run_id, staging_db_path) -> ValidationReport` | Existing has a concrete return type; design is parameterless. Existing is more explicit. | No |
| `promote(run_id)` | `promote(run_id, report, prod_db_path, staging_db_path)` | Existing passes paths explicitly; design hides them in the base class. Both work. | No |
| `rollback(run_id)` | — | — | **Yes** (absent from current protocol) |
| `record_impact(...)` | — (exists as module fn: `scripts/pipeline/manifest.py::write_impact`) | Design moves existing module helper onto class. | Already shared — no net new |
| `entity_gate_check(staged_rows)` | — (exists: `scripts/pipeline/shared.py::entity_gate_check`) | Same — existing helper moved onto class. | Already shared |
| `snapshot_before_promote()` | — (exists: `scripts/pipeline/shared.py::refresh_snapshot`) | Close, not identical — design proposes per-table pre-promote snapshots to `data/backups/{pipeline}_{run_id}.duckdb`; existing snapshot is prod→`13f_readonly.duckdb` app replica. These are *two different things with overlapping names*. | **Yes** — genuinely new (but conflicts with existing snapshot terminology) |
| `stamp_freshness(con)` | — (exists: `scripts/pipeline/shared.py::stamp_freshness`) | Design moves module helper onto class. | Already shared |
| `prune_old_snapshots()` | — | — | **Yes** |

### 4d. Classification

**The design cannot extend existing surfaces as-written. Material rework required before restart.**

Specific blockers:

1. **Schema fiction** — at least four columns the design uses do not exist (`row_counts_json`, impact `run_id`, impact `action`, impact `prior_accession`), and three more require renames (`pipeline_name`, `status`, `completed_at`). Needs either a migration 008 that adds/renames, or design edits that use current names.
2. **State-machine incompatibility** — design's lifecycle (11 states including `pending_approval`, `approved`, `rejected`, `expired`) cannot be represented in the current `fetch_status` enum (5 states) or `promote_status` enum (4 states). Needs either a new column (`run_status`) or enum expansion.
3. **Protocol-vs-ABC tension** — current code uses `typing.Protocol` (duck-typed, structural). Design uses `abc.ABC` (nominal, inheritance-based). Choice has knock-on effects on test doubles and existing `@runtime_checkable` dispatch.
4. **`parse()` purity inversion** — current `parse()` is pure (no DB); design's `parse()` writes staging. Six existing pipelines would need `parse()` refactored. Worth a deliberate decision before restart.
5. **Snapshot-terminology collision** — design introduces a third meaning for "snapshot" (per-promote backup file) while two are already live (`entity_snapshot_*` rollback tables in prod, `13f_readonly.duckdb` app replica). Needs rename or explicit ownership doc.

Minimum pre-restart work: one schema migration (either add fictional columns or adopt current names), one doc edit to reconcile the 11-state machine, one decision on Protocol-vs-ABC, one decision on parse() purity. Roughly a focused session of refactor before the base class can be written against reality.

---

## 5. Migration Surface — Deep Audit

Per-migration matrix. Live state verified via `schema_versions` and per-artifact probes.

| Migration | Idempotent re-run | Interruption-safe | Reversible | Live state |
|---|---|---|---|---|
| 001 `pipeline_control_plane` | YES — all CREATEs use `IF NOT EXISTS` ([:42-45, :52-110, :156-165](scripts/migrations/001_pipeline_control_plane.py:42)) | PARTIAL — `CREATE SEQUENCE IF NOT EXISTS` OK; DDL is one-shot, crash in mid-execution leaves some objects created and others not (no enclosing transaction). Re-run recovers. | NO — no documented rollback | LIVE — 4 tables + 3 sequences + 1 view present; not stamped in `schema_versions` (predates versioning) |
| 002 `fund_universe_strategy` | YES — `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` | YES — single ALTER per column | NO — no rollback documented | LIVE — 3 columns present; not stamped |
| 003 `cusip_classifications` | YES — `IF NOT EXISTS` + `INSERT OR IGNORE` on `schema_versions` | YES — wrapped in `BEGIN/COMMIT/ROLLBACK` block | YES — idempotent re-run; manual DROP possible | LIVE — 4 tables + 7 added columns; stamped 2026-04-15 |
| 004 `summary_by_parent_rollup_type` | YES — probes `rollup_type` column and returns silently if present ([:33-68](scripts/migrations/004_summary_by_parent_rollup_type.py:33)) | **NO — critical gap** — `RENAME → CREATE → INSERT → DROP` at [:82-145](scripts/migrations/004_summary_by_parent_rollup_type.py:82) has no transaction. SIGKILL between `RENAME` (line 87) and `CREATE` (line 90) leaves the canonical table name absent. | NO — `summary_by_parent_old` is dropped unconditionally at line 132. No data backup. | LIVE — `rollup_type` column + composite PK present; 63,916 rows all stamped `economic_control_v1`; stamped |
| 005 `beneficial_ownership_entity_rollups` | YES — per-column probe; `INSERT OR IGNORE` | YES — additive ALTERs only | YES — nullable columns; safe to drop | LIVE — 4 columns present on BO v2; stamped 2026-04-16 |
| 006 `override_id_sequence` | YES — probes sequence, default, nullable; returns "ALREADY APPLIED" if all three satisfied ([:122-124](scripts/migrations/006_override_id_sequence.py:122)) | YES — three independent ALTERs; NULL-guard aborts early if data is broken | YES — idempotent re-run; manual rollback possible | LIVE — seq `override_id_seq` + default + NOT NULL; 245 rows; stamped 2026-04-17 |
| 007 `override_new_value_nullable` | YES — probes `is_nullable` | YES — single ALTER | YES — re-apply NOT NULL possible after clearing NULLs (currently 8) | LIVE — nullable; 8 NULLs; stamped 2026-04-17 |
| `add_last_refreshed_at` (unnumbered) | YES — probes column pre-migration | YES — ADD COLUMN + UPDATE wrapped in CHECKPOINT | YES — additive | **LIVE but UNSTAMPED.** Column populated (14,181 / 18,500 = 76.8% — see §0 S-02). Migration never `INSERT INTO schema_versions`. Docstring [:26-36](scripts/migrations/add_last_refreshed_at.py:26) says "written but not yet run" — stale. |

### Rollback procedures (per class)

| Scenario | Procedure |
|---|---|
| Revert 001 / 002 | Not scripted. Manual `DROP SEQUENCE`, `ALTER TABLE DROP COLUMN`. Data loss if any rows exist. |
| Revert 003 | Manual `DROP TABLE cusip_classifications, cusip_retry_queue, _cache_openfigi` + remove 7 securities columns. Re-run of 003 is idempotent. |
| Revert 004 | **No clean path.** DuckDB does not support `DROP PRIMARY KEY` without full table rebuild. Requires: `ALTER TABLE RENAME TO _bad` → `CREATE TABLE ... PRIMARY KEY(quarter, rollup_entity_id)` → `INSERT INTO ... SELECT` → `DROP TABLE _bad`. Must take a backup first. |
| Revert 005 | `ALTER TABLE beneficial_ownership_v2 DROP COLUMN rollup_entity_id, ...` (4 columns). Safe. |
| Revert 006 | `ALTER TABLE entity_overrides_persistent ALTER COLUMN override_id DROP DEFAULT` + `DROP SEQUENCE override_id_seq`. Manual. |
| Revert 007 | `ALTER TABLE ... ALTER COLUMN new_value SET NOT NULL` — fails if any NULL remains (8 rows currently). Clear NULLs first. |
| Revert `add_last_refreshed_at` | `ALTER TABLE entity_relationships DROP COLUMN last_refreshed_at`. Safe (backfilled from `created_at`). |

### Drift flags

- **Migration 004 interruption risk is real** — wrap lines 82-145 in `BEGIN TRANSACTION`/`COMMIT` before the next DERA-scale refresh. Currently the canonical name can disappear mid-run.
- **`add_last_refreshed_at` is a tracking lie** — stamp retroactively (`INSERT INTO schema_versions ('add_last_refreshed_at', CURRENT_TIMESTAMP)`) or fix the migration to match docstring.
- **No migration 008 on disk yet** — admin-refresh design references it heavily but the file does not exist. Expected given the paused workstream; flagging for completeness.
- **Rollback path is universally weak** — scripted rollback exists for none of the 8 migrations. Recovery is operationally "restore backup," not "run down()."

---

## 6. Cross-Table Reconciliation Math

All queries run 2026-04-17 against prod DB read-only.

| # | Pair | Grain | Result | Magnitude |
|---|---|---|---|---|
| 6.1 | `investor_flows` (EC rollup, 2025Q3→Q4) vs distinct (ticker, rollup_entity_id) union from `holdings_v2` Q3+Q4 | ticker × rollup | **PARTIAL** | flows = 2,083,116 vs union = 2,093,225; delta = **−10,109 (0.48% under)** |
| 6.2 | `summary_by_ticker` (2025Q4) vs `holdings_v2` aggregation for AAPL/MSFT/NVDA/TSLA | (ticker, quarter) | **PASS** | Δ holder_count = 0 / 0 / 0 / 0; Δ total_shares = 0 / 0 / 0 / 0 (exact match across all four) |
| 6.3 | `summary_by_parent` (2025Q4 EC) `SUM(total_aum)` vs `holdings_v2` `SUM(market_value_usd)` | quarter | **PASS** | Both = 67,321,197,046,577. Exact. (Against `market_value_live`, ratio 0.9499 — expected; sbp uses filings-basis.) |
| 6.4 | `ticker_flow_stats` `flow_intensity_total` vs naive `SUM(ABS(raw_flow)) / SUM(GREATEST(to_value,0))` from `investor_flows` | (ticker, quarter_from, quarter_to) | **PARTIAL — formula mismatch** | AAPL stored=0.00808 vs naive=0.10911; MSFT 0.00845 vs 0.11891; NVDA 0.01162 vs 0.08925; TSLA 0.00340 vs 0.13368. Stored is ~8–40× smaller than naive derivation — implies a different normalizer (likely `SUM(to_value) across all holders` or parent-level rollup, not per-ticker). **Not a reconciliation failure; a formula undocumentation.** |
| 6.5 | `beneficial_ownership_current` vs `beneficial_ownership_v2` latest-accession rollup | (filer_cik, subject_ticker) | **PASS** | Both = 24,756. Exact match. (Note: the natural rollup key is `(filer_cik, subject_ticker)`, not `(filer_cik, subject_cusip)` — the cusip-keyed rollup is 7,390 because one cusip can carry multiple tickers.) |

### Failure mechanisms

- **6.1** — 10,109-row under-coverage is explained by `NULL rollup_entity_id` rows in `holdings_v2` (Group-2 enrichment miss in `compute_flows.py`). `investor_flows` is filtered to `rollup_entity_id IS NOT NULL`; the union query counts them. Not a defect — a coverage symptom that feeds back into the Task-1 entity-enrichment gap.
- **6.4** — the formula `flow_intensity_total` stores is not documented in code comments on `compute_flows.py` nor in `docs/data_layers.md`. Without it, a reader cannot reproduce the stored number. Worth a docstring addition but not a reconciliation failure.

Headline: **3 PASS, 2 PARTIAL, 0 FAIL.** No material data-corruption signal in the fact-table layer. The derived-table formulas reconcile where they're documented; where they don't reconcile, the gap is formula opacity, not wrong data.

---

## 7. Codex BLOCK-Claims — Verification

Four Codex claims drive the final BLOCK recommendation. Verified independently by reading the cited line ranges.

### 7.1 Non-atomic prod promotes — **CONFIRMED**

- **`promote_nport.py:421-494`** — read. No `BEGIN TRANSACTION`. The sequence is: `_mirror_manifest_and_impacts` (multi-DELETE+INSERT, [:103-145](scripts/promote_nport.py:103)) → `_promote_batch` (DELETE+INSERT on `fund_holdings_v2`, [:288-335](scripts/promote_nport.py:288)) → `CHECKPOINT` → `_bulk_enrich_run` UPDATE → `_upsert_universe` (DELETE+INSERT) → `UPDATE ingestion_impacts` → `CHECKPOINT` → `stamp_freshness` ×2 → `CHECKPOINT`. Any process kill between the `DELETE FROM fund_holdings_v2` at [:298-302](scripts/promote_nport.py:298) and the subsequent INSERT at [:328](scripts/promote_nport.py:328) leaves prod rows missing for the scope tuples. Comment at [:1-8](scripts/promote_nport.py:1) claims "either the whole run commits or nothing does" — this is **not true**; without an enclosing transaction, DuckDB auto-commits each statement.
- **`promote_13dg.py:273-305`** — read at [:272-306](scripts/promote_13dg.py:272). Same pattern: `_promote` (DELETE+INSERT on `beneficial_ownership_v2`, [:104-130](scripts/promote_13dg.py:104)) → `CHECKPOINT` → `bulk_enrich_bo_filers` → `CHECKPOINT` → `_rebuild_current` → `CHECKPOINT` → `stamp_freshness` ×3 → `_update_impacts` → `CHECKPOINT`. No `BEGIN/COMMIT` wrap. Confirmed.

**Codex correct. Both scripts have a real partial-write window during promote.**

### 7.2 Admin `/run_script` TOCTOU race — **CONFIRMED**

- **`admin_bp.py:267-283`** — read. At [:268](scripts/admin_bp.py:268) the code runs `subprocess.run(['pgrep', '-f', script], ...)`. At [:283](scripts/admin_bp.py:283) — 15 lines and multiple IO operations later — it runs `subprocess.Popen(cmd, stdout=log_file, ...)`. These are two independent OS calls with no serialization primitive between them. Two concurrent HTTP requests for the same `script` value can both pass the `pgrep` check before either child process appears in the process table. Classic TOCTOU.

**Codex correct. Mitigation is either a `fcntl.flock()` on the log file before `pgrep`, or a manifest-backed `fetch_status='fetching'` check-and-set done inside a transaction.**

### 7.3 `fetch_adv.py` DROP-before-CREATE window — **CONFIRMED**

- **`fetch_adv.py:247-249`** — read:
  ```python
  con = duckdb.connect(DB_PATH)
  con.execute("DROP TABLE IF EXISTS adv_managers")
  con.execute("CREATE TABLE adv_managers AS SELECT * FROM df_out")
  ```
  Two separate auto-committed statements. SIGKILL / OOM / crash between them leaves `adv_managers` absent until the next full re-run. Any in-flight query hitting `adv_managers` during that window fails with `CatalogException: Table ... does not exist`.

**Codex correct. This is the same failure pattern that fetch_ncen.py just fixed (`ef7fb13` guard against dropped managers table) — fetch_adv.py has it too.**

### 7.4 Admin token in `localStorage` — **CONFIRMED**

- **`web/templates/admin.html:180-202`** — read. Lines 181, 185, 187-188, 194, 198 show: token stored in `localStorage.setItem('admin_token', t)`, retrieved with `localStorage.getItem('admin_token')`, cleared on HTTP 401 response. No `SameSite` cookie, no `HttpOnly`, no session timeout, no rotation.

**Codex correct. XSS on any served page reads the token; persistence survives browser restart; no server-side invalidation path other than rotating `ADMIN_TOKEN` env var and forcing all clients to re-prompt.**

---

## 8. Disagreements with Codex

Two disagreements on framing; no disagreements on facts.

**8.1 Codex §2a D-01/D-02 — framing of the entity-enrichment collapse.** Codex calls this "live drift" (correct) and implicitly attributes it to the entity-gate queuing unresolved identifiers. My §1 shows that for 2025-10, 2025-12, 2026-01, **76–94% of the NULL-entity_id rows carry series_ids that *are* resolvable in `entity_identifiers` today**. The dominant mechanism is therefore *missing backfill enrichment*, not *unresolvable input*. The fix is a backfill job, not a gate-relaxation. Codex's proposed structural frame (relax the gate) addresses a secondary driver; the primary driver needs a new enrichment path. Both are true but prioritization matters.

**8.2 Codex §5.2 — DM override NULL replay gap severity.** Codex flags it as a correctness blocker for `--reset`. I read migration 007's acceptance of NULL-target rows ([:8-12](scripts/migrations/007_override_new_value_nullable.py:8)) as an intentional decision, not a gap. The 5 NULL-CIK overrides apply live and the replay path simply skips them — this is how merge-overrides are supposed to work (the merge is already persisted in entity_rollup_history; the override row is ledger-only). Not a BLOCK; worth a MINOR note for doc clarity.

---

## 9. Final BLOCK / MAJOR / MINOR Recommendation

Consolidated from atlas (60 findings), Codex (39 findings), and this Pass 2. Ordered by severity, grouped by theme. Fix sequence reflects production-impact priority, not alphabetical order.

### BLOCK — fix before next large promote

1. **[Task 1]** `fund_holdings_v2.entity_id` 40.09% coverage overall, collapsing to 0.18% in 2025-11. Dominant driver: `_bulk_enrich_run` in [scripts/promote_nport.py:153-218](scripts/promote_nport.py:153) is run-scoped, not table-scoped. **Fix: decouple enrichment from promote; add idempotent full-scope backfill job.** Estimated recovery: 2025-10/2026-01 to ≥94% on first run.
2. **[Task 3 + Codex §3a]** Non-atomic prod promotes in [scripts/promote_nport.py:421-494](scripts/promote_nport.py:421) and [scripts/promote_13dg.py:272-306](scripts/promote_13dg.py:272). **Fix: wrap each promote in `BEGIN TRANSACTION` / `COMMIT` with rollback on any failure, simultaneously with extracting the canonical `mirror_manifest_and_impacts` helper.** Comment at promote_nport.py:1-8 claims atomicity that the code does not deliver.
3. **[Task 2 + §0 S-01]** Legacy `fund_holdings` writer live via admin allowlist. **Fix: remove `'fetch_nport.py'` from [scripts/admin_bp.py:258-265](scripts/admin_bp.py:258) as the one-line stop-the-bleeding change.** Follow with full retirement sequence (§2).
4. **[Codex §1 / §3f]** Admin refresh design writes against fictional control-plane columns + 11-state lifecycle incompatible with current enums. **Fix: pre-restart material rework — migration for schema, decision on Protocol-vs-ABC, decision on parse() purity.** Design cannot extend existing surfaces as-written.

### MAJOR — fix before next session-close

5. **[Codex §1 / §7.2]** Admin `/run_script` TOCTOU race at [scripts/admin_bp.py:267-283](scripts/admin_bp.py:267). **Fix: file-lock or manifest-backed check-and-set.**
6. **[Codex §3b / §7.3]** `fetch_adv.py:247-249` DROP-before-CREATE. **Fix: `CREATE OR REPLACE TABLE adv_managers AS SELECT ...` single-statement, or stage→rename.**
7. **[Codex §3f / §7.4]** Admin token in `localStorage` ([web/templates/admin.html:180-202](web/templates/admin.html:180)). **Fix: HttpOnly session cookie, server-side session table, rotation endpoint.**
8. **[Task 5]** Migration 004 interruption risk at [scripts/migrations/004_summary_by_parent_rollup_type.py:82-145](scripts/migrations/004_summary_by_parent_rollup_type.py:82). **Fix: wrap in `BEGIN/COMMIT`.**
9. **[§0 S-02]** `add_last_refreshed_at.py` live but not stamped in `schema_versions`. **Fix: add the INSERT (or re-run the migration as designed).**
10. **[Atlas C-05]** Five unlisted direct-to-prod writers missing from `docs/pipeline_violations.md` (`resolve_agent_names`, `resolve_bo_agents`, `resolve_names`, `backfill_manager_types`, `enrich_tickers`). **Fix: list them; decide staging-or-exception per-script.**
11. **[Atlas D-07, P-05]** N-CEN and ADV outside `ingestion_manifest` despite control-plane rhetoric. **Fix: add source_type rows + per-run manifest inserts in `fetch_ncen.py` and `fetch_adv.py`.**
12. **[Atlas P-04]** Market `impact_id` duplicate-PK crash recurred 2026-04-16 post-fix. **Fix: audit every call path that bypasses `manifest._next_id` (search for direct `INSERT INTO ingestion_impacts` without the helper).**
13. **[Atlas D-05 / Task 2]** Cross-doc contradiction: `ENTITY_ARCHITECTURE.md:287-293` says legacy tables dropped 2026-04-13; `MAINTENANCE.md:120-123` authorizes drop on/after 2026-05-09; legacy `fund_holdings` still live. **Fix: align both docs, pick one date.**

### MINOR — housekeeping

14. **[Atlas R-01 / R-02]** Roadmap says 928 13DG exclusions / 4 NULL-CIK; prod has 931 / 5. **Fix: reconcile numbers.**
15. **[Atlas O-02 / O-03]** Flask / edgartools / pdfplumber not pinned; smoke CI doesn't install them. **Fix: pin in `requirements.txt`.** (Codex accepted Flask is gone, so this reduces to edgartools + pdfplumber.)
16. **[Atlas DOC-01/02/03/04/05/06/07]** Root-level README + PHASE prompts + `README_deploy.md` + `write_path_risk_map.md` all predate FastAPI/React/retired-script cleanups. **Fix: one docs pass covers all seven.**
17. **[Atlas DOC-11]** `docs/data_layers.md:92` headline `entity_id 84.47%` is wrong; actual 40.09%. **Fix automatically follows BLOCK #1 — refresh the doc after backfill.**
18. **[Atlas O-08]** Divergent UA strings + bare-email scripts. **Fix: central `scripts/config.py` constant.**
19. **[Task 6.4]** `flow_intensity_total` formula undocumented. **Fix: docstring in `compute_flows.py` + mention in `docs/data_layers.md`.**
20. **[§8.2]** Migration 007 intentional NULL-target handling is not a defect; worth a doc note so future readers don't re-flag it.

---

*End of Pass 2. No commits. No code changes. No pipeline runs.*
