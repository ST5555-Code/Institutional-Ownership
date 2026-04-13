# Write-Path Risk Map (ARCH-2A.3)

_Created: 2026-04-13. Audit artifact only — **no code changes in this
document**. Produced as part of Batch 2-A per `ARCHITECTURE_REVIEW.md`._

## Scope

Every non-entity pipeline script under `scripts/` that writes to
`data/13f.duckdb`, classified by transactional risk. The entity MDM stack
(`build_entities.py`, `sync_staging.py`, `diff_staging.py`,
`promote_staging.py`, `merge_staging.py`, `entity_sync.py`,
`validate_entities.py`, `rollback_promotion.py`, the `resolve_*.py`
family, `approve_overrides.py`, `auto_resolve.py`, `validate_phase4.py`)
is out of scope — it already has a staging → diff → validate → promote →
snapshot workflow (INF1, 2026-04-10) which is the model non-entity write
paths should eventually follow (BL-3).

Application and support modules (`app.py`, `admin_bp.py`, `queries.py`,
`export.py`, `config.py`, `db.py`, `yahoo_client.py`,
`sec_shares_client.py`, `smoke_yahoo_client.py`, `benchmark.py`) are
read-only or service-layer and are excluded.

## Baseline invariant

**No audited script uses explicit `BEGIN TRANSACTION` / `COMMIT` /
`ROLLBACK` or `con.begin()` / `con.commit()` / `con.rollback()`.**

DuckDB autocommits each statement, so single-statement mutations are
atomic. Anything multi-step (DROP → CREATE → INSERT, DELETE → INSERT,
streaming INSERT loops) has a window where prod state is partially
applied. This is the structural risk the audit quantifies.

## Risk tiers

### T1 — Atomic by construction (very low risk)

Single `CREATE OR REPLACE TABLE AS SELECT …` replaces the table in one
DuckDB statement. On failure, the prior table is untouched.

| Script | Tables affected | Failure mode |
|---|---|---|
| `backfill_manager_types.py` | `managers` | Prior `managers` state retained on failure. Re-run safe. |

### T2 — Drop-and-recreate without a transaction (medium risk)

Pattern: `DROP TABLE IF EXISTS x` → `CREATE TABLE x (…)` → `INSERT INTO
x SELECT …`. Three separate statements. If the process dies between
DROP and the last INSERT, the table either doesn't exist (read side sees
an error) or exists with a partial row set. Readers on the read-only
snapshot are unaffected if the pipeline ran against staging first, but
today most of these scripts write straight to prod.

| Script | Tables | Risk notes |
|---|---|---|
| `build_cusip.py` | `cusip_map` (or equivalent) | DROP → CREATE → UPDATE sequence. |
| `build_managers.py` | `managers`, `cik_crd_links` | Mass-replaces the managers reference. Window of inconsistency during rebuild. |
| `load_13f.py` | `holdings`, `filings` | DROP + DELETE + CREATE + INSERT. Full-rebuild path. Window visible. |
| `unify_positions.py` | `holdings_v2` | DROP → CREATE → INSERT from source tables. |
| `compute_flows.py` | `investor_flows`, `ticker_flow_stats` | Drops and rebuilds both analytics tables per run. |
| `fetch_adv.py` | `adv_managers` | DROP + CREATE. ADV ingest replaces the entire table. |
| `fetch_13dg.py` | `beneficial_ownership`, `listed_filings_13dg`, `fetched_tickers_13dg` | Mixed DROP + UPDATE. |

**Mitigation ideas (tracked as BL-3):**
- Wrap the DROP/CREATE/INSERT in an explicit transaction where the
  underlying driver/DuckDB version supports DDL+DML transactions. DuckDB
  as of 0.10+ supports this.
- Or build-into-temp-then-swap: `CREATE TABLE x_new AS …; BEGIN; DROP
  TABLE x; ALTER TABLE x_new RENAME TO x; COMMIT;`
- Or route through the staging workflow (preferred end state — parallel
  to entity MDM).

### T3 — Per-chunk atomicity by design (low risk)

Streaming ingesters that INSERT rows as they arrive from an upstream
source (SEC EDGAR, FINRA, market-data vendor). Each single INSERT is
atomic in DuckDB, so the file written so far is consistent; a crash
leaves a prefix of rows committed. A checkpoint/resume mechanism
re-starts from the last committed row.

This matches `docs/PROCESS_RULES.md` — partial apply is the **feature**,
not the bug. `--test` flag caps scope; `python3 -u` gives flush-on-write
output for live tailing.

| Script | Source | Checkpoint mechanism |
|---|---|---|
| `fetch_nport.py` | SEC N-PORT | Per-filing; re-checks `fund_holdings_v2` for rows already written |
| `fetch_ncen.py` | SEC N-CEN | Per-filing; `ncen_adviser_map` primary key prevents dup insertion |
| `fetch_market.py` | Yahoo + SEC | Per-ticker; `market_data` upsert-on-ticker |
| `fetch_finra_short.py` | FINRA | Per-report-date; `short_interest` keyed by (ticker, report_date) |
| `enrich_tickers.py` | Yahoo sector | Per-ticker UPDATE; idempotent |

**No action required.** Mitigation is already in place via the key-based
dedup + resume pattern.

### T4 — Per-group atomicity, not cross-group (low risk)

Loop over groups (typically quarters); each group does a
`DELETE WHERE quarter = ?` followed by `INSERT … SELECT … WHERE
quarter = ?`. Within one group the window of inconsistency is tiny. Across
groups, if the loop dies midway, some quarters are rebuilt and others
are still at the prior version.

| Script | Groups | Tables |
|---|---|---|
| `build_summaries.py` | Quarter | `summary_by_ticker`, `summary_by_parent` |
| `build_benchmark_weights.py` | Benchmark / quarter | `benchmark_weights` |

**Mitigation idea:** run the loop inside a single transaction. Current
volume is small enough that this is trivially feasible.

### T5 — Idempotent UPDATE utilities (very low risk)

One-shot or periodic UPDATE scripts that converge to the same final
state regardless of interruption. Running twice is safe; running half
and re-running is also safe.

| Script | Purpose |
|---|---|
| `fix_fund_classification.py` | Targeted classification corrections |
| `refetch_missing_sectors.py` | Back-fill `market_data.sector` where NULL |
| `reparse_13d.py` | Reparse `beneficial_ownership` for stale rows |
| `reparse_all_nulls.py` | Back-fill nullable columns |
| `update.py` | Orchestrator — invokes other pipelines |

**No action required.**

### T6 — Mixed multi-step (medium-low risk)

Scripts that mix T1 atomicity (CREATE OR REPLACE) with later in-place
UPDATE/INSERT. The CREATE OR REPLACE half is safe; the downstream
UPDATE/INSERT reintroduces a partial-apply window.

| Script | Notes |
|---|---|
| `build_shares_history.py` | OR_REPLACE + DROP + INSERT + UPDATE sequence |
| `build_fund_classes.py` | CREATE + INSERT + UPDATE |

Lower priority than T2 — the dominant statement is already atomic; the
UPDATE phase is smaller and typically idempotent.

## summary_by_parent request-path audit (ARCH-2A.2)

The three consumers in `scripts/queries.py` (lines 775, 1442, 4304)
are all `SELECT ... FROM summary_by_parent WHERE ...`. No INSERT /
UPDATE / DELETE / CREATE on any request path. Writes happen only in
`scripts/build_summaries.py` (T4 — per-quarter atomic).

**Conclusion:** `summary_by_parent` is read-only on every request path.
No on-demand recompute exists. No code change required.

## Follow-on work

- **BL-3 (already on the backlog)**: implement T2 mitigation. Either
  wrap DROP/CREATE/INSERT in a transaction, use the build-into-temp-
  then-swap pattern, or route through the staging workflow (preferred).
- Investigate whether DuckDB's transactional DDL covers the full T2 set
  in the current DuckDB version pinned by the project (`pyproject.toml`
  / `requirements.txt`). If yes, BL-3 becomes a simple wrap-in-BEGIN-
  COMMIT pass.
- Consider extending `merge_staging.py` to cover selected T2 tables
  (compute_flows outputs are the highest-value candidates — user-facing
  analytics tables).

## Out of scope for this audit

- Fixing anything in T2. This is the implementation work tracked as
  BL-3. The audit only quantifies where the risk sits.
- Throughput / performance regressions from wrapping in a transaction —
  separately measured at BL-3 time.
- Entity MDM stack (already mitigated by the INF1 staging workflow).
