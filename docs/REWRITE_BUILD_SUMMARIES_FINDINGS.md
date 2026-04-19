# REWRITE build_summaries.py — Phase 0 Findings

_Branch: `rewrite-build-summaries`, off main d7ba1c2. Phase 0 is read-only._

## Headline

**The REWRITE for `scripts/build_summaries.py` already landed** at commit
`87ee955` (2026-04-16, "feat: Batch 3 close — compute_flows +
build_summaries rewrites + migration 004"), which is an ancestor of
current HEAD `d7ba1c2`. Every retrofit in the Batch 3 rewrite checklist
(holdings → holdings_v2 repoint, `--dry-run`, per-batch CHECKPOINT,
`data_freshness` hook, DDL parity, error propagation) is already in
place and running in prod.

`docs/pipeline_violations.md:237` (REWRITE block) was prepared
2026-04-13 and partially revised 2026-04-15; its build_summaries
entry is stale and should be retired or moved to a CLEARED section.

No Phase 1 implementation commits are required for the originally
scoped work. Two adjacent observations surfaced during this audit are
recorded under *Follow-ups* below — neither is a blocker for closing
this REWRITE entry.

---

## Scope

Audit `scripts/build_summaries.py` against the Batch 3 rewrite
checklist:
1. Legacy-read retirement: `holdings` → `holdings_v2`.
2. Write preservation: `summary_by_ticker`, `summary_by_parent`,
   `data_freshness`.
3. Retrofits: per-batch `CHECKPOINT`, `--dry-run`, `data_freshness`
   write hook, `flush=True`, error propagation.
4. DDL parity vs prod for both output tables (per
   `docs/canonical_ddl.md` §4–§5).
5. Downstream readers still resolve correctly after the rewrite.
6. Data integrity: prod row counts and freshness timestamps.

## Current State

### 0.1 — Code structure (`scripts/build_summaries.py`, 428 lines)

**Entry points**

- `main()` — `:390`. Parses args, chooses quarters, opens `_Tee` log,
  opens connection, dispatches to `_run_dry` or `_run_write`, closes
  connection in `finally`. Error propagation via try/finally at
  `:411–420`.
- `_parse_args()` — `:366`. Flags: `--staging`, `--dry-run`,
  `--rebuild`.
- `_open_connection()` — `:381`. Returns read-only handle for
  `--dry-run`, otherwise `db.connect_write()`.

**Read operations (all against `holdings_v2` / `fund_holdings_v2`)**

- `:156` `_project_summary_by_ticker` — `COUNT(DISTINCT ticker)` from
  `holdings_v2` WHERE `quarter = ?` AND `ticker IS NOT NULL AND ticker
  != ''`.
- `:191` `_build_summary_by_ticker` — `FROM holdings_v2 h` WHERE
  `quarter = ?` AND non-empty `ticker`; GROUP BY `h.ticker`.
  Aggregations documented in §0.1 *Aggregation semantics* below.
- `:209` `_project_summary_by_parent` — `COUNT(DISTINCT {rid_col})`
  from `holdings_v2` WHERE `quarter = ?`.
- `:237–265` `_build_summary_by_parent` — three-CTE query:
  - `latest_per_series` picks `MAX(report_month)` per `series_id` in
    `fund_holdings_v2` for the quarter.
  - `nport_per_rollup` JOINs `fund_holdings_v2` to that latest
    snapshot and aggregates `SUM(market_value_usd)` by the
    rollup-specific rid column.
  - `parent_13f` aggregates `holdings_v2` by the 13F rid column
    (`rollup_entity_id` for EC, `dm_rollup_entity_id` for DM).
  - Final SELECT LEFT JOINs the two on `rid`, computes
    `nport_coverage_pct = LEAST(100, nport/total_aum * 100)`.

Zero references to legacy `holdings` anywhere in the file
(verified by rg; the only match on `"holdings"` is the `holdings_v2`
name itself).

**Write operations**

- `summary_by_ticker`: `DELETE WHERE quarter=?` + full `INSERT` per
  quarter (`:164–195`). CHECKPOINT at `:333`.
- `summary_by_parent`: `DELETE WHERE quarter=? AND rollup_type=?` +
  full `INSERT` per (quarter × worldview) (`:224–287`). CHECKPOINT at
  `:344`. Two worldviews per quarter: `economic_control_v1`,
  `decision_maker_v1` (see `_ROLLUP_SPECS` at `:60`).
- `data_freshness`: `db.record_freshness(con, "summary_by_ticker",
  total_t)` and `…"summary_by_parent", total_p)` at `:355–356`.

**Aggregation semantics (the rewrite contract)**

- `summary_by_ticker` — one row per `(quarter, ticker)`:
  - `total_value` = `SUM(COALESCE(market_value_live,
    market_value_usd))` (correct pre- and post-`enrich_holdings`).
  - `total_shares` = `SUM(shares)`.
  - `holder_count` = `COUNT(DISTINCT cik)` — filer-level.
  - `active_value` / `passive_value` split by `manager_type IN
    ('active','hedge_fund','quantitative','activist')` vs
    `manager_type = 'passive'`.
  - `active_pct` = `active_value / total_value * 100` rounded to 1 dp,
    NULL when `total_value <= 0`.
  - `pct_of_float` = `SUM(pct_of_float)` (ticker-level stacked
    ownership).
  - `top10_holders` currently NULL — placeholder column.

- `summary_by_parent` — one row per `(quarter, rollup_type,
  rollup_entity_id)`:
  - `total_aum` = `SUM(market_value_usd)` on `holdings_v2` — Group 1,
    filing-date semantics, 100% complete.
  - `total_nport_aum` = `SUM(market_value_usd)` on `fund_holdings_v2`,
    latest `report_month` per `series_id` within the quarter (avoids
    triple-counting monthly snapshots).
  - `nport_coverage_pct` = `LEAST(100, total_nport_aum / total_aum *
    100)`.
  - `ticker_count`, `total_shares`, `manager_type` (MAX),
    `is_passive` (BOOL_OR).
  - `inst_parent_name` = `rollup_name` (back-compat column so
    `queries.py` keeps working — see Follow-up 1).
  - `top10_tickers` currently NULL — placeholder column.

**Error handling**

- `main()` uses try/finally on the DB connection (`:411–420`). Any
  `con.execute` failure raises and `finally` closes the handle —
  no silent swallowing.
- `_Tee.__enter__/__exit__` opens/closes the log file
  (`:82–89`) with `buffering=1` (line-buffered) and explicit
  `sys.stdout.flush()` after every `line()` (`:94`). Equivalent to
  `flush=True` per line.
- `os.makedirs(..., exist_ok=True)` at `:78` is the only
  exception-absorbing call and is the correct idiom.
- No `try: … except: pass` anywhere in the file (rg verified).

**Flag semantics**

| Flag        | Line | Behaviour                                                 |
|-------------|------|-----------------------------------------------------------|
| `--staging` | 372  | `db.set_staging_mode(True)` → writes to `13f_staging.duckdb` |
| `--dry-run` | 374  | Read-only connection; `_run_dry` projects row counts       |
| `--rebuild` | 376  | All quarters; default is `LATEST_QUARTER` only             |

No flags missing for the rewrite checklist. `--staging` + `--dry-run`
is the standard per-script pattern (same as `build_shares_history`).

**DDL drift — none**

`CREATE TABLE IF NOT EXISTS` at `:110–145` matches prod column-for-
column for both tables (verified via `DESCRIBE` on
`data/13f.duckdb`):

| Table               | Script DDL cols | Prod cols | Match |
|---------------------|-----------------|-----------|-------|
| `summary_by_ticker` | 12              | 12        | ✓     |
| `summary_by_parent` | 14              | 14        | ✓     |

PK on `summary_by_parent` is `(quarter, rollup_type, rollup_entity_id)`
per migration 004 in both script and prod.

`docs/canonical_ddl.md:23-28` already marks both tables as ALIGNED; §4
and §5 explicitly note the post-Batch-1 and post-migration-004
resolution.

### 0.2 — Downstream readers survey

`rg -n "summary_by_ticker|summary_by_parent"` across the repo — 90
hits across 14 files (markdown excluded via glob):

| File                                                  | Hits | Type          |
|-------------------------------------------------------|-----:|---------------|
| scripts/build_summaries.py                            | 40   | WRITE (owner) |
| scripts/migrations/004_summary_by_parent_rollup_type.py | 22 | SCHEMA         |
| scripts/queries.py                                    |  6   | READ          |
| scripts/build_fixture.py                              |  5   | SCHEMA/SEED   |
| scripts/pipeline/registry.py                          |  4   | SCHEMA        |
| scripts/merge_staging.py                              |  2   | SCHEMA        |
| scripts/check_freshness.py                            |  1   | READ          |
| Makefile                                              |  2   | TARGET        |
| web/react-app/src/components/common/FreshnessBadge.tsx|  3   | READ (freshness) |
| web/react-app/src/components/tabs/RegisterTab.tsx     |  1   | READ (freshness) |
| web/react-app/src/components/tabs/ConvictionTab.tsx   |  1   | READ (freshness) |
| web/react-app/src/components/tabs/CrossOwnershipTab.tsx|  1  | READ (freshness) |
| web/react-app/src/components/tabs/OverlapAnalysisTab.tsx|  1 | READ (freshness) |
| web/react-app/src/components/tabs/EntityGraphTab.tsx  |  1   | READ (freshness) |

**Python READ consumers**

- `scripts/queries.py:744,1406,4262` — three places SELECT
  `nport_coverage_pct` FROM `summary_by_parent` WHERE
  `inst_parent_name IN (…)` AND `quarter = …`. No `rollup_type`
  filter. See Follow-up 1.
- `scripts/check_freshness.py:34` — `summary_by_parent` listed in the
  freshness-budget map at 95h amber. `summary_by_ticker` not listed
  (matches the frontend's behaviour of badging only
  `summary_by_parent`).

**React READ consumers (freshness-only)**

- 5 tabs render `<FreshnessBadge tableName="summary_by_parent"
  label="register" />` (Register, Conviction, CrossOwnership,
  OverlapAnalysis, EntityGraph).
- `FreshnessBadge.tsx:31-32` sets amber/red thresholds for both
  summary tables. No tab reads `summary_by_ticker` freshness badge
  directly.
- No React component queries summary rows as data — the UI reads
  flows, holdings, and register tables; only the freshness timestamp
  is surfaced.

### 0.3 — Data quantification (prod `data/13f.duckdb`, read-only)

**`summary_by_ticker`** — 47,642 rows across 4 quarters:

| Quarter | Rows   | Distinct tickers |
|---------|-------:|-----------------:|
| 2025Q1  | 11,534 | 11,534           |
| 2025Q2  | 11,464 | 11,464           |
| 2025Q3  | 12,074 | 12,074           |
| 2025Q4  | 12,570 | 12,570           |

Rows = distinct tickers per quarter → PK holds, no duplicates.

**`summary_by_parent`** — 63,916 rows across 4 quarters × 2
worldviews:

| Quarter | rollup_type          | Rows  | Distinct rollup_entity_ids |
|---------|----------------------|------:|---------------------------:|
| 2025Q1  | economic_control_v1  | 7,813 | 7,813                      |
| 2025Q1  | decision_maker_v1    | 7,813 | 7,813                      |
| 2025Q2  | economic_control_v1  | 7,864 | 7,864                      |
| 2025Q2  | decision_maker_v1    | 7,864 | 7,864                      |
| 2025Q3  | economic_control_v1  | 7,843 | 7,843                      |
| 2025Q3  | decision_maker_v1    | 7,843 | 7,843                      |
| 2025Q4  | economic_control_v1  | 8,438 | 8,438                      |
| 2025Q4  | decision_maker_v1    | 8,438 | 8,438                      |

EC and DM rollup counts are identical per quarter, consistent with
every holdings_v2 row carrying both rollup ids.

**`data_freshness` state for summary tables:**

| table_name          | last_computed_at              | row_count |
|---------------------|-------------------------------|----------:|
| `summary_by_parent` | 2026-04-17 20:46:39.596026    | 63,916    |
| `summary_by_ticker` | 2026-04-17 20:46:39.580838    | 47,642    |

Row counts match the live tables exactly. Last refresh was
~37 hours before this audit (2026-04-19 early AM). Under the 95h
amber threshold in `check_freshness.py:34`. Confirms the script has
run successfully end-to-end at least once post-87ee955 and that the
`record_freshness` hook fires.

**`holdings_v2` columns required by the rewrite — all present:**
`quarter`, `ticker`, `issuer_name`, `cik`, `market_value_usd`,
`market_value_live`, `shares`, `manager_type`, `pct_of_float`,
`rollup_entity_id`, `rollup_name`, `dm_rollup_entity_id`,
`dm_rollup_name`, `is_passive`. No missing columns.

**`fund_holdings_v2` columns required — all present:**
`quarter`, `series_id`, `report_month`, `market_value_usd`,
`rollup_entity_id`, `dm_rollup_entity_id`. No missing columns.

## Proposed Rewrite

**None required.** The rewrite shipped at `87ee955`. No Phase 1, Phase
2, Phase 3, or Phase 4 work is warranted for the originally scoped
retrofits.

Recommended actions instead:

1. Edit `docs/pipeline_violations.md:237–244` to move the
   `build_summaries.py (REWRITE)` block to the CLEARED section with a
   citation of `87ee955` and this findings doc.
2. Flip `docs/pipeline_inventory.md` entry for `build_summaries.py` to
   its post-rewrite state (if not already — not read in this phase).

## Baseline Capture + Test Plan

Not applicable — no rewrite run is required, so there is no pre-/
post-rewrite comparison to stage.

The next scheduled run of `make build-summaries` (next quarter close)
will produce fresh rollups against the already-rewritten code path.
`data_freshness` will re-stamp, and the React badges will pick up the
new timestamp automatically.

## Follow-ups (not in scope for this REWRITE entry)

1. **`queries.py` lookups are not `rollup_type`-qualified** —
   `:744,:1406,:4262` SELECT `nport_coverage_pct` FROM
   `summary_by_parent` WHERE `inst_parent_name IN (…) AND quarter =
   …` with no `rollup_type` filter. Because `inst_parent_name =
   rollup_name` per worldview, a name that exists identically in both
   EC and DM rollups would return two rows, and `fetchdf()` /
   `fetchone()` would either pick one arbitrarily or duplicate
   records depending on the calling code. Spot-check of EC vs DM
   `rollup_name` distributions would quantify the overlap. Track as a
   separate audit item — NOT part of this REWRITE closeout because the
   rewrite preserved `inst_parent_name` specifically as a back-compat
   column for these queries (`87ee955` commit message calls this out
   explicitly).
2. **Inline f-string interpolation of `quarter`** at `:157, :168,
   :192, :208, :240, :250, :263, :267`. Not exploitable (quarter
   comes from `config.QUARTERS` / `LATEST_QUARTER`, never user
   input), but should be parameterised on a future refactor pass for
   consistency with the `?` placeholder style used in DELETEs on the
   same lines.
3. **`top10_holders` / `top10_tickers` are written as NULL** (`:189`,
   `:283`). Either populate them or drop the columns. Placeholder
   state is preserved from pre-rewrite; decide separately.

## Sequencing and Dependencies

- Blocks on BLOCK-3 (legacy `holdings` retirement): **satisfied** —
  `87ee955` delivered Batch 3 close alongside this rewrite.
- Nothing downstream waits on this. No action needed.
- No new blockers identified for adjacent REWRITE targets.

## Out of Scope

- Recomputing summary rollups against new data.
- Changing aggregation semantics (ticker/parent contracts as defined
  by `87ee955` are preserved).
- Addressing Follow-ups 1–3 above — each gets its own ticket / BLOCK
  entry.
- Any schema migration (migration 004 already shipped with `87ee955`).

---

*Audit performed 2026-04-19. Prod DB: `data/13f.duckdb` (13.5 GB,
mtime 2026-04-19 06:03). HEAD: d7ba1c2.*
