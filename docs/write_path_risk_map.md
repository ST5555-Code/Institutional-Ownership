# Write-Path Risk Map

_Originally created 2026-04-13 as ARCH-2A.3. Refreshed 2026-04-21 under
remediation ops-06 to reflect the current pipeline state (Stage 5
SourcePipeline + id_allocator + atomic promote groundwork + flock
guards on admin endpoints)._

## Scope

Every non-entity pipeline script under `scripts/` that writes to
`data/13f.duckdb`, classified by transactional risk.

The entity MDM stack (`build_entities.py`, `sync_staging.py`,
`diff_staging.py`, `promote_staging.py`, `merge_staging.py`,
`entity_sync.py`, `validate_entities.py`, `rollback_promotion.py`, the
`resolve_*.py` family, `approve_overrides.py`, `auto_resolve.py`,
`validate_phase4.py`) is out of scope — the INF1 staging workflow
(2026-04-10) already meets the target pattern, and non-entity writers
converge on that shape as they migrate to `SourcePipeline`.

Application and support modules (`app.py`, `app_db.py`, `admin_bp.py`,
`queries.py`, `export.py`, `config.py`, `db.py`, the `api_*.py` router
modules, `yahoo_client.py`, `sec_shares_client.py`, `benchmark.py`)
are read-only or service-layer and are excluded from the write-path
audit. The `admin_bp.py` admin surface writes via `/run_script` +
`/add_ticker` + `/entity_override`, all of which now sit behind
`fcntl.flock` concurrency guards (sec-02-p1 / sec-03-p1) and dispatch
to the same pipeline scripts audited below — no separate DB writes.

## Baseline invariant

**DuckDB autocommits each statement.** Single-statement mutations are
atomic. Multi-step paths (DROP → CREATE → INSERT, DELETE → INSERT,
streaming INSERT loops) have a window where prod state is partially
applied unless the path explicitly wraps in BEGIN / COMMIT or routes
through staging.

## Current architectural pattern (Stage 5)

Three pipeline `Protocol`s, defined in
`scripts/pipeline/protocol.py`, now drive new writers and rewrites:

- **`SourcePipeline`** — EDGAR source pipelines (13F, N-PORT, 13D/G,
  ADV, N-CEN). Shape: `discover() → fetch() → parse() → load() →
  validate() → promote()`. Writes land first in
  `data/13f_staging.duckdb`; `promote_*.py` mirrors validated rows
  into `data/13f.duckdb`.
- **`DirectWritePipeline`** — market / FINRA upserts directly to
  canonical reference tables (`market_data`, `short_interest`). No
  staging DB, no entity gate (reference-only data).
- **`DerivedPipeline`** — L4 compute scripts (`compute_flows`,
  `build_summaries`, `build_managers`). Read L3 → rebuild L4 table. No
  fetch.

All three end with `stamp_freshness()` to update `data_freshness` for
the FreshnessBadge in the React app.

Two supporting modules landed alongside the Protocol pattern:

- **`scripts/pipeline/id_allocator.py`** (obs-03-p1) — centralized PK
  allocator for `ingestion_manifest` / `ingestion_impacts`, guarded by
  `fcntl.flock` on `data/.ingestion_lock` to prevent cross-writer
  races. Replaces the inline `_next_id` in `manifest.py` and the
  deleted bypass in `shared.py`.
- **`scripts/pipeline/manifest.py`** — shared `record_freshness`,
  `get_or_create_manifest_row`, and `write_impact` helpers consumed by
  both `SourcePipeline` writers and the legacy DROP/CREATE scripts.

## Risk tiers

### T1 — Atomic by construction (very low risk)

Single `CREATE OR REPLACE TABLE AS SELECT …` replaces the table in one
DuckDB statement. On failure, the prior table is untouched.

| Script | Tables | Status |
|---|---|---|
| `backfill_manager_types.py` | `managers` | Prior state retained on failure. Re-run safe. |

### T2 — Drop-and-recreate without a transaction (medium risk)

Pattern: `DROP TABLE IF EXISTS x` → `CREATE TABLE x (…)` → `INSERT
INTO x SELECT …`. Three separate statements. If the process dies
between DROP and the last INSERT, the table either doesn't exist
(read side sees an error) or exists with a partial row set.

Most of the original T2 set has now cleared — see `docs/pipeline_violations.md`:

| Script | Tables | Current status |
|---|---|---|
| `load_13f.py` | `holdings`, `filings` | **CLEARED** 2026-04-19 (Rewrite4, `7e68cf9` / prod apply `a58c107`). Now DELETE+INSERT via staging workflow. Dead `holdings` DROP+CTAS retired. |
| `build_managers.py` | `managers`, `cik_crd_links` | **CLEARED** 2026-04-19 (Rewrite5, `223b4d9` / prod apply `7747af2`). `PROMOTE_KIND='rebuild'` machinery in `promote_staging.py`. |
| `build_cusip.py` | `cusip_map`, `securities`, `cusip_classifications` | **CLEARED** 2026-04-14 (CUSIP v1.4). Legacy retired to `scripts/retired/build_cusip_legacy.py`. |
| `build_summaries.py` | `summary_by_ticker`, `summary_by_parent` | **CLEARED** 2026-04-19 (Batch 3 close, `87ee955`). Reads `holdings_v2`. |
| `compute_flows.py` | `investor_flows`, `ticker_flow_stats` | **CLEARED** 2026-04-19 (Batch 3 close, `87ee955`). |
| `build_shares_history.py` | `shares_history_v2` | **CLEARED** 2026-04-19 (Rewrite1, `d7ba1c2` / prod apply `443e37a`). |
| `fetch_adv.py` | `adv_managers` | **OPEN** — DROP-before-CREATE still leaves table absent on interrupt. Tracked as mig-02 (Theme 3). |
| `build_benchmark_weights.py` | `benchmark_weights` | **OPEN** — grouped-quarter DELETE+INSERT loop (see T4). |
| `build_fund_classes.py` | `fund_classes` | **OPEN** — CREATE+INSERT+UPDATE sequence. |

### T3 — Per-chunk atomicity by design (low risk)

Streaming ingesters. Each single INSERT is atomic; a crash leaves a
prefix of rows committed. Checkpoint/resume re-starts from the last
committed row. Matches `docs/PROCESS_RULES.md` — partial apply is the
**feature**.

| Script | Source | Status |
|---|---|---|
| `fetch_nport_v2.py` | SEC N-PORT (XML + DERA ZIP) | **SourcePipeline.** Writes to staging DB; `promote_nport.py` mirrors to prod. Superseded `fetch_nport.py` (retained only for parser helpers). |
| `fetch_13dg_v2.py` | SEC 13D/G | **SourcePipeline.** Validation + promote via `validate_13dg.py` + `promote_13dg.py`. Superseded `fetch_13dg.py` (retained only for parser helpers). |
| `fetch_dera_nport.py` | DERA N-PORT bulk ZIPs | **SourcePipeline.** Feeds `fetch_nport_v2.py` load step. |
| `fetch_ncen.py` | SEC N-CEN | Per-filing; `ncen_adviser_map` PK prevents dup insertion. |
| `fetch_market.py` | Yahoo + SEC | **CLEARED** 2026-04-13 (Batch 2A/2B). Per-ticker `market_data` upsert-on-ticker. |
| `fetch_finra_short.py` | FINRA | Per-report-date; `short_interest` keyed by (ticker, report_date). |
| `enrich_tickers.py` | Yahoo sector | Per-ticker UPDATE; idempotent. |

### T4 — Per-group atomicity, not cross-group (low risk)

Loop over groups (typically quarters); each group does
`DELETE WHERE quarter = ?` followed by `INSERT … WHERE quarter = ?`.
Within one group the window is tiny. Across groups, if the loop dies
midway, some quarters are rebuilt and others are still at the prior
version.

| Script | Groups | Tables |
|---|---|---|
| `build_benchmark_weights.py` | Benchmark / quarter | `benchmark_weights` |

`build_summaries.py` previously sat here; cleared 2026-04-19 via
staging workflow migration.

### T5 — Idempotent UPDATE utilities (very low risk)

One-shot or periodic UPDATE scripts that converge to the same final
state regardless of interruption.

| Script | Purpose |
|---|---|
| `fix_fund_classification.py` | Targeted classification corrections. |
| `refetch_missing_sectors.py` | Back-fill `market_data.sector` where NULL. |
| `reparse_13d.py` | Reparse `beneficial_ownership` for stale rows. |
| `reparse_all_nulls.py` | Back-fill nullable columns. |
| `update.py` | Orchestrator — invokes other pipelines. Pending retirement (references retired `fetch_nport.py` + missing `unify_positions.py`; tracked as ops doc item). |

### T6 — Mixed multi-step (medium-low risk)

Scripts that mix T1 atomicity (CREATE OR REPLACE) with later in-place
UPDATE/INSERT. The CREATE OR REPLACE half is safe; the downstream
UPDATE/INSERT reintroduces a partial-apply window.

| Script | Status |
|---|---|
| `build_shares_history.py` | **CLEARED** (see T2). |
| `build_fund_classes.py` | **OPEN** — CREATE + INSERT + UPDATE sequence. |

## Promote-path atomicity (mig-01)

`promote_nport.py` and `promote_13dg.py` — the staging → prod mirror
scripts — currently run a multi-statement DELETE + INSERT + CHECKPOINT
sequence **without** an explicit transaction wrap. Kill between the
DELETE and the INSERT loses rows that were committed to staging.

- **mig-01-p0** (merged, commit `dd03780`) — Phase 0 findings +
  mirror-helper scaffolding.
- **mig-01-p1** (open, prompt `60c8713` docs/prompts/mig-01-p1.md) —
  atomic wrap + extract `_mirror_manifest_and_impacts` helper into
  `pipeline/manifest.py`. Critical Batch 3-A item; landing this closes
  the last structural window on the source-pipeline promote path.

Until mig-01-p1 merges, the audit treats `promote_*.py` as a T2-shape
risk even though the CHECKPOINT discipline (post-rewrite 2026-04-17)
bounds the window to a single DELETE+INSERT pair per run.

## Admin write-surface concurrency (sec-02 / sec-03)

`admin_bp.py` has three endpoints that dispatch mutating operations:

- `/api/admin/run_script` — runs any pipeline script; guarded by
  `fcntl.flock` on `data/.run_script_lock` (sec-02-p1).
- `/api/admin/add_ticker` — enriches market data for a new ticker;
  guarded by `fcntl.flock` on `data/.add_ticker_lock` (sec-03-p1).
- `/api/admin/entity_override` — writes entity override rows; 409 on
  concurrent write (sec-03-p1).

Concurrent requests return 409 rather than interleaving. No admin
endpoint writes to `data/13f.duckdb` without going through one of the
audited pipeline scripts.

## Validator read-only defaults (sec-04)

`validate_entities.py` and the `validate_*` family of scripts now
default to read-only (`sec-04-p1`, commit `af66013`). Queue population
is split from validation; validators can no longer accidentally
promote rows.

## `summary_by_parent` request-path audit (retained)

The three consumers in `scripts/queries.py` (lines 775, 1442, 4304)
are all `SELECT ... FROM summary_by_parent WHERE ...`. No INSERT /
UPDATE / DELETE / CREATE on any request path. Writes happen only in
`scripts/build_summaries.py`.

**Conclusion:** `summary_by_parent` is read-only on every request
path. No on-demand recompute exists.

## Retired scripts

Retained on disk for parser helpers or historical reference, but no
longer part of the write path:

| Script | Status | Successor |
|---|---|---|
| `fetch_nport.py` | Superseded 2026-04-15. Parser helpers only. | `fetch_nport_v2.py` + `fetch_dera_nport.py` |
| `fetch_13dg.py` | Superseded 2026-04-15. Parser helpers only. | `fetch_13dg_v2.py` + `validate_13dg.py` + `promote_13dg.py` |
| `scripts/retired/build_cusip_legacy.py` | Retired 2026-04-14. | `build_cusip.py` (CUSIP v1.4). |

## Follow-on work

- **mig-01-p1** — atomic promotes + shared mirror helper. **Critical**.
- **mig-02** (fetch_adv.py) — close the DROP-before-CREATE window on
  `adv_managers`.
- **build_benchmark_weights.py** — wrap the per-quarter loop in a
  single transaction (volume small enough that this is trivial).
- **build_fund_classes.py** — consolidate CREATE + INSERT + UPDATE
  into a staging-workflow-style promote.
- **`update.py` retirement** — orchestrator references retired
  scripts; replace with `run_pipeline.sh` or drop entirely.

## Out of scope for this audit

- Fixing anything in T2-open. Implementation work is tracked as the
  corresponding `mig-##` rows in `docs/REMEDIATION_PLAN.md` Theme 3.
- Throughput / performance regressions from wrapping in a transaction
  — separately measured at implementation time.
- Entity MDM stack (already mitigated by the INF1 staging workflow).
