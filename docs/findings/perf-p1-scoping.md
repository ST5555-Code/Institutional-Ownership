# perf-P1 — precompute scoping for `sector_flows_rollup`, `sector_flow_movers_by_quarter_sector`, `cohort_by_ticker_from`

_Prepared: 2026-04-27 — branch `claude/friendly-lamarr-eaf0bb` off `main` HEAD `3a02b37`._

_Tracker: [ROADMAP.md:21](ROADMAP.md:21) — perf-P1 is the follow-on to perf-P0 (`peer_rotation_flows`, [PR #158](https://github.com/sergetismen/13f-ownership/pull/158) / [#159](https://github.com/sergetismen/13f-ownership/pull/159))._

_Read-only investigation. No code, no migrations, no precompute tables created. Latency measured against prod DB at `data/13f.duckdb` (25.5 GB), 4 parent quarters (`2025Q1`–`2025Q4`), 16 fund quarters (`2022Q3`–`2026Q2`), 13 GICS sectors, 12,000 parent tickers, 71,374 fund tickers._

---

## §1. TL;DR

| Target | Recommendation | Why |
|---|---|---|
| `sector_flows_rollup` | **Precompute (small materialized table, ~351 rows)** | Live query is ~960 ms parent / ~930 ms fund; output is tiny so a thin precompute trivially drops latency to <50 ms. Highest ROI of the three. |
| `sector_flow_movers_by_quarter_sector` | **Precompute via aggregation, but reuse `peer_rotation_flows` for `level=parent` instead of materializing a new L4 table** | Parent path already has the right entity grouping in `peer_rotation_flows`. Only `level=fund` (which here means manager-name within 13F, not N-PORT funds) needs a separate path. ~760 K rows if fully materialized, but most of it duplicates P0. |
| `cohort_by_ticker_from` | **Flag — narrow scope before precompute** | Live latency 270–620 ms, already under 1 s. Full dimension space is 144 K rows (parent) up to 2.3 M rows (with fund-level + all from-quarters). Recommend either (a) precompute the **default** invocation only (PQ→LQ, parent, defaults — ~12 K rows) or (b) skip precompute and add a result cache. Materializing all from-quarters is overkill given current latencies. |

The three targets bundled as "perf-P1" in the roadmap are not equivalent — `sector_flows_rollup` is a clear win, `cohort_by_ticker_from` likely is not, and `sector_flow_movers` is a half-win that should fold into the P0 footprint.

---

## §2. Target 1 — `sector_flows_rollup`

### §2.1 Source function

`get_sector_flows(active_only=False, level="parent")` — [scripts/queries.py:2089](scripts/queries.py:2089).

Two SQL paths share the same shape:
- `level="parent"` reads `holdings_v2`. Aggregates per `(cik, manager_type, ticker, quarter)` into a CTE `h_agg`, then joins `h_agg c LEFT JOIN h_agg p` on `(cik, ticker)` across the two quarters of each consecutive pair. Adds an `UNION ALL` for exits (rows present in `q_from` but not `q_to`). Joins `market_data` on ticker, groups by `md.sector`, returns `{sector, net, inflow, outflow, new_positions, exits, managers}` per pair.
- `level="fund"` reads `fund_holdings_v2` with the analogous shape (`series_id` instead of `cik`). Active-only filter is ignored on the fund path.

The function returns multi-pair output: it discovers `SELECT DISTINCT quarter FROM holdings_v2/fund_holdings_v2`, builds consecutive pairs, runs the SQL once per pair, and stitches results into `{periods: [...], sectors: [{sector, flows: {pk: {...}}, total_net, latest_net}]}`. Three SQL round-trips for parent (4 quarters → 3 pairs); 15 round-trips for fund.

### §2.2 Latency

Median of 3 runs:

| Variant | Run 1 | Run 2 | Run 3 | **Median** |
|---|--:|--:|--:|--:|
| `level=parent` | 1,137 ms | 959 ms | 912 ms | **959 ms** |
| `level=fund` | 929 ms | 948 ms | 916 ms | **929 ms** |

`active_only` filter has no effect on the function's wall-clock cost (it's a predicate, not a structural change).

### §2.3 Input dimensions

The query depends on:

- `level` ∈ {`parent`, `fund`} — different source table.
- `active_only` ∈ {`True`, `False`} — filters `entity_type IN ('active','hedge_fund','activist')` (parent only; ignored for fund).
- Implicit: all consecutive `(quarter_from, quarter_to)` pairs from the source table.

Note that `rollup_type` is **not** an input — `get_sector_flows` is rollup-agnostic at the function signature level. Internally it groups by `cik`/`series_id`, not by rollup name, so the "managers" count is rollup-independent. Precompute can therefore be rollup-agnostic as well.

### §2.4 Precompute size

| Dim | Cardinality |
|---|--:|
| Parent quarter pairs | 3 |
| Fund quarter pairs | 15 |
| Sectors | 13 |
| Levels | 2 |
| `active_only` flavors | 2 (parent only — fund ignores it) |

- Parent: `2 active × 3 pairs × 13 sectors = 78` rows.
- Fund: `1 × 15 pairs × 13 sectors = 195` rows.
- **Total ~273–351 rows.** Trivial.

Each row payload: `{net, inflow, outflow, new_positions, exits, managers}` — six numeric fields. Total table size <50 KB.

### §2.5 Source tables and rebuild trigger

- **Reads:** `holdings_v2` (L3), `fund_holdings_v2` (L3), `market_data` (L3).
- **Layer:** would be L4 (precompute / derived).
- **Rebuild trigger:** quarterly 13F load (when `holdings_v2` gains a new quarter) and quarterly N-PORT load (when `fund_holdings_v2` gains a new quarter). Rebuild cost: trivial — 18 SQL aggregations the size of the live function but written once and stored.

### §2.6 Verdict

**Precompute. Highest ROI in the bundle.** Tiny output, ~960 ms → <50 ms is a ~20× win without any reuse complexity. Conservative estimate: 1 day of work — migration + `SourcePipeline` subclass + queries rewrite + tests.

---

## §3. Target 2 — `sector_flow_movers_by_quarter_sector`

### §3.1 Source function

`get_sector_flow_movers(q_from, q_to, sector, active_only=False, level="parent", rollup_type='economic_control_v1')` — [scripts/queries.py:2228](scripts/queries.py:2228).

Single SQL: builds `h_agg` over `holdings_v2` filtered to the two quarters, LEFT-JOINs across the pair on `cik+ticker`, joins `market_data` filtered to the requested sector, UNION-ALL adds exits. Groups by `institution` (different expression depending on `level`/`rollup_type`):

- `level=parent`: `COALESCE(c.{rn}, c.inst_parent_name, c.manager_name)` where `rn ∈ {rollup_name, dm_rollup_name}` per `rollup_type`.
- `level=fund`: `c.cik || '|' || c.manager_name`. **Important:** this path still reads `holdings_v2`, not `fund_holdings_v2`. "Fund" here means *manager-name granularity within 13F*, not N-PORT fund series.

Returns top-5 buyers + top-5 sellers + summary (totals over all institutions in scope). The full ranking is computed in DuckDB; only the slice is returned.

### §3.2 Latency

Median of 3 runs at pair `2025Q3 → 2025Q4`, `level=parent`:

| Ticker / Sector | Run 1 | Run 2 | Run 3 | **Median** |
|---|--:|--:|--:|--:|
| AAPL → Technology | 476 ms | 512 ms | 425 ms | **476 ms** |
| EQT → Energy | 495 ms | 373 ms | 490 ms | **490 ms** |

Already under 500 ms. Tradeoff is borderline.

### §3.3 Input dimensions

- `q_from`, `q_to` — must be a consecutive pair (3 pairs in current parent data).
- `sector` — 13 values.
- `active_only` ∈ {True, False}.
- `level` ∈ {parent, fund}.
- `rollup_type` ∈ {`economic_control_v1`, `decision_maker_v1`} (parent only).

### §3.4 Precompute size

Distinct entity counts per `(pair × sector × level × rollup_type)` for the latest pair:

| Sector | parent_econ | parent_dm | fund_mgr |
|---|--:|--:|--:|
| Technology | 7,677 | 7,677 | 7,896 |
| Consumer Cyclical | 7,442 | 7,442 | 7,653 |
| Financial Services | 7,403 | 7,403 | 7,609 |
| Healthcare | 7,140 | 7,140 | 7,346 |
| Communication Services | 7,097 | 7,097 | 7,303 |
| Industrials | 7,090 | 7,090 | 7,289 |
| ETF | 6,877 | 6,877 | 7,064 |
| Consumer Defensive | 6,439 | 6,439 | 6,622 |
| Energy | 6,159 | 6,159 | 6,337 |
| Basic Materials | 5,452 | 5,452 | 5,602 |
| Utilities | 5,199 | 5,199 | 5,344 |
| Real Estate | 5,114 | 5,114 | 5,260 |
| Derivative | 4,550 | 4,550 | 4,665 |

- Per-pair total (parent_econ + parent_dm + fund_mgr): **253,268 rows**.
- × 3 quarter pairs ≈ **760 K rows** for a fully materialized movers precompute.

### §3.5 Reuse opportunity — `peer_rotation_flows`

`peer_rotation_flows` (perf-P0, 17.5 M rows) has columns `(quarter_from, quarter_to, sector, entity, entity_type, ticker, active_flow, level, rollup_type, loaded_at)`. For `level='parent'` the `entity` column is **already** `COALESCE({rn_col}, inst_parent_name, manager_name)` — exactly what `get_sector_flow_movers level=parent` groups by. Aggregation in the API path:

```sql
SELECT entity AS institution,
       SUM(active_flow) AS net_flow,
       COUNT(DISTINCT ticker) AS positions_changed,
       SUM(CASE WHEN active_flow > 0 THEN active_flow ELSE 0 END) AS buying,
       SUM(CASE WHEN active_flow < 0 THEN active_flow ELSE 0 END) AS selling
  FROM peer_rotation_flows
 WHERE quarter_from = ? AND quarter_to = ? AND sector = ?
   AND level = 'parent' AND rollup_type = ?
   [AND entity_type IN (...)]   -- active_only
 GROUP BY entity
HAVING ABS(SUM(active_flow)) > 0
 ORDER BY net_flow DESC
 LIMIT 5
```

This is the same pattern `get_peer_rotation` already uses ([scripts/queries.py:4280](scripts/queries.py:4280)). Latency impact: should match the perf-P0 detail-path numbers (~46 ms), maybe slightly higher due to `GROUP BY entity` over more rows (sector-wide vs single-ticker).

The `level='fund'` path of `get_sector_flow_movers` has no equivalent in `peer_rotation_flows` — P0's `level='fund'` reads `fund_holdings_v2`, while the movers' `level='fund'` reads `holdings_v2` at manager granularity. Two options:

1. **Add a `level='manager'` rollup to `peer_rotation_flows`** and migrate the get_sector_flow_movers fund path to read it. Adds ~5 M rows to `peer_rotation_flows`. Cleanest semantically.
2. **Keep movers `level='fund'` as live SQL** — accept ~500 ms there; precompute only the `level='parent'` cases via P0 reuse. Cheapest.

### §3.6 Verdict

**Reuse `peer_rotation_flows` for `level='parent'` (no new table). For `level='fund'` defer or extend P0.** Skip a dedicated `sector_flow_movers_by_quarter_sector` materialized table — would shadow ~750 K rows of P0 data. Ships faster than option 1, no schema thrash. Expected latency: 476 ms → <100 ms for the parent case (matching P0 detail), unchanged for the fund case.

---

## §4. Target 3 — `cohort_by_ticker_from`

### §4.1 Source function

`cohort_analysis(ticker, from_quarter=None, level='parent', active_only=False, rollup_type='economic_control_v1', quarter=LQ)` — [scripts/queries.py:2760](scripts/queries.py:2760).

Two SQLs (one per side of the comparison) build per-investor `{shares, value}` maps for `q_from` and `q_to`. Then a Python helper `_build_cohort` ([scripts/queries.py:2601](scripts/queries.py:2601)) computes the seven cohort buckets (Retained, Increased, Decreased, Unchanged, New Entries, Exits, Total), top-5 entities per bucket by delta, share-weighted economic retention (capped 100 % per investor), and a top-10 holders cohort breakdown.

After that it runs **6 more SQLs** (3 transitions × 2 quarters) to compute an `econ_retention_trend` over the last 3 QoQ pairs. That's 8 SQL round-trips per call.

### §4.2 Latency

| Ticker | Run 1 | Run 2 | Run 3 | **Median** |
|---|--:|--:|--:|--:|
| AAPL | 607 ms | 623 ms | 895 ms | **623 ms** |
| EQT | 268 ms | 272 ms | 261 ms | **268 ms** |

Latency scales with holder count: AAPL has ~5,989 unique entities (max in the parent table); EQT is closer to the 187-entity average. The Python `_build_cohort` runs 5 nested loops over the retained/new/exit sets — per-investor cost is non-trivial for the long tail.

### §4.3 Input dimensions

- `ticker` — 12,000 parent / 71,374 fund.
- `from_quarter` — user-specified, can be any of `QUARTERS` (4 parent / 16 fund) plus the default `PQ`.
- `level` ∈ {parent, fund}.
- `active_only` ∈ {True, False}.
- `rollup_type` ∈ {`economic_control_v1`, `decision_maker_v1`} (parent only — fund uses `fund_universe.is_actively_managed`).
- `quarter` (the "to" side) — defaults to `LQ`. Almost always LQ at request time.

### §4.4 Precompute size

| Scope | Rows |
|---|--:|
| Default only (`from_q=PQ`, `to_q=LQ`, `level=parent`, `active_only=False`, `rollup=economic_control_v1`) | **12,000** |
| All parent scopes (3 from_q × 2 rollup × 2 active × 12 K tickers) | 144,000 |
| All fund scopes (15 from_q × 2 active × 71 K tickers) | 2,141,220 |
| Grand total all-scopes | **~2.29 M** |

Per-row payload is the cohort detail blob: 7 buckets × `{holders, shares, value, avg_position, pct_so_moved, delta_shares, delta_value}` + top-5 children per bucket × the same fields. Roughly 1–3 KB per row JSON-encoded → 2–7 GB at full materialization. Plus the `econ_retention_trend` rebuild per row.

### §4.5 Source tables and rebuild trigger

- **Reads:** `holdings_v2` (L3), `fund_holdings_v2` (L3), `fund_universe` (L3 — for active filter on fund path). No `market_data` dependency.
- **Rebuild trigger:** quarterly 13F load + quarterly N-PORT load. The `econ_retention_trend` calculation depends on the most recent 3 transitions — rebuild also fires when a new quarter ages out.

### §4.6 Verdict — flag

**Probably skip a full precompute.** Reasons:

- Both measured tickers run in <1 s already; AAPL's 623 ms is acceptable for a non-default cohort exploration UI.
- The dimension space is dominated by the user-controlled `from_quarter` parameter. Fully materializing 2.3 M cohort blobs + 6 retention-trend SQLs each is heavier than the win.
- Most of the latency on AAPL is Python (`_build_cohort` over 5,989 holders), not SQL. Precompute moves the SQL cost offline but the Python cost has to run *somewhere* — either at materialization (slow rebuild) or at request (no win) or by storing a deeper denormalization (large table).

Two cheaper alternatives, in order of preference:

1. **Result cache** — same hash key as the `_get_summary_impl` cache ([scripts/queries.py:3923](scripts/queries.py:3923)). 60-second TTL would absorb the dashboard reload pattern without the rebuild infra. No new pipeline.
2. **Default-scope-only precompute** (~12 K rows) — bake the `(ticker, level=parent, from=PQ, to=LQ, active=False, rollup=econ)` cohort into a thin precompute table, leave non-default queries on the live path. Hits the 90 % case at ~1 % of the row count.

If a precompute path is chosen anyway, scope it to option 2 — do not materialize all from-quarters and rollup variants.

---

## §5. perf-P0 reusable patterns

PR #158 (pipeline) + #159 (queries rewrite) for `peer_rotation_flows` left a usable template. Each component below is reusable for `sector_flows_rollup` (and a manager-rollup extension if pursued for movers `level='fund'`).

### §5.1 `SourcePipeline` subclass

[scripts/pipeline/compute_peer_rotation.py](scripts/pipeline/compute_peer_rotation.py) (780 lines) — concrete pattern:

- `name`, `target_table`, `amendment_strategy="direct_write"`, `amendment_key=(scope columns)`.
- `target_table_spec()` returns columns + PK + indexes.
- `fetch()` is a no-op for internal-source precomputes (drops + recreates the staging table). No HTTP fetch, no manifest of raw files.
- `parse()` does the actual aggregation. Pattern: ATTACH prod read-only inside staging connection (`_attach_prod`), materialize per-pair temps (`h_agg_pair`), loop sectors/rollups inserting into the staging target. Avoids the "26-redundant-full-table-scan" anti-pattern.
- `validate()` blocks on zero rows and flags ≥20 % swing vs prior prod count.
- `promote()` is **overridden** to do coarse-scope DELETE-then-bulk-INSERT (per scope tuple) instead of the base ABC's per-PK DELETE — millions of per-row deletes thrash. For `sector_flows_rollup` (~351 rows) the base behavior is fine and `promote()` doesn't need an override.
- `_project_dry_run(prod_db_path)` — read-only row-count projection per scope. Standalone CLI helper.
- CLI: `--dry-run`, `--staging` flags. `_resolve_db_paths()` falls back when `db.py` is unimportable.

### §5.2 Migration template

[scripts/migrations/019_peer_rotation_flows.py](scripts/migrations/019_peer_rotation_flows.py) (154 lines):

- `VERSION` + `NOTES` constants.
- `_has_table` + `_already_stamped` guards.
- `CREATE TABLE IF NOT EXISTS` with explicit PK.
- Idempotent: bails if `(table_present AND stamped)`.
- Stamps `schema_versions` after creation. `CHECKPOINT` before close.
- CLI: `--dry-run`, `--staging`, `--prod`, `--path`. Same pattern across migrations 015–020.

### §5.3 `DATASET_REGISTRY` entry

[scripts/pipeline/registry.py:293](scripts/pipeline/registry.py:293):

```python
"peer_rotation_flows": DatasetSpec(
    layer=4, owner="scripts/pipeline/compute_peer_rotation.py",
    promote_strategy="rebuild",
    rebuild_from=("holdings_v2", "fund_holdings_v2", "market_data"),
    notes="Precomputed entity×ticker active flows per sector. Migration 019.",
),
```

For `sector_flows_rollup` the entry would be:

```python
"sector_flows_rollup": DatasetSpec(
    layer=4, owner="scripts/pipeline/compute_sector_flows_rollup.py",
    promote_strategy="rebuild",
    rebuild_from=("holdings_v2", "fund_holdings_v2", "market_data"),
    notes="Sector-level rollup of active flows per quarter pair. Migration 0NN.",
),
```

### §5.4 `queries.py` rewrite pattern

[scripts/queries.py:4244](scripts/queries.py:4244) `get_peer_rotation`:

- Read directly from the precompute table.
- Apply `active_only` as an `entity_type IN (...)` predicate at read time, not by re-aggregating live holdings — this is what keeps the precompute rollup-/active-agnostic and small.
- Compute downstream-shape (`subj_flows_by_pk`, `sector_flows_by_pk`, etc.) in Python from the rows the table returns.
- Empty-result envelope short-circuit when `peer_rotation_flows` returns no rows for the scope.

### §5.5 Latency benchmark

ROADMAP records P0 numbers ([ROADMAP.md:104](ROADMAP.md:104)):
- `get_peer_rotation`: 11.4 s → 540 ms (21×, parent path).
- `get_peer_rotation_detail`: 46 ms.
- Full rebuild of `peer_rotation_flows` (16.2 M rows at ship): 59 s.

P1 absolute wins are smaller — the live queries are already <1 s — but proportional wins should be similar (target <50 ms post-rewrite for `sector_flows_rollup`).

---

## §6. Summary

| Target | Function | Median ms | Precompute rows | Source tables | Rebuild trigger | Recommendation |
|---|---|--:|--:|---|---|---|
| `sector_flows_rollup` | `get_sector_flows` ([queries.py:2089](scripts/queries.py:2089)) | 959 (parent) / 929 (fund) | **~351** | `holdings_v2`, `fund_holdings_v2`, `market_data` (all L3) | quarterly 13F + N-PORT load | **Precompute (small materialized table)** |
| `sector_flow_movers_by_quarter_sector` | `get_sector_flow_movers` ([queries.py:2228](scripts/queries.py:2228)) | 476 (AAPL/Tech) / 490 (EQT/Energy) | ~760 K if standalone; **0 new for `level=parent`** if reusing `peer_rotation_flows` | `holdings_v2`, `market_data` (all L3); reuse `peer_rotation_flows` (L4, P0) | quarterly 13F load (already covered by P0) | **Reuse `peer_rotation_flows` for `level=parent`; defer or extend P0 for `level=fund`** |
| `cohort_by_ticker_from` | `cohort_analysis` ([queries.py:2760](scripts/queries.py:2760)) | 623 (AAPL) / 268 (EQT) | 12 K (default-only) / 144 K (parent all-scopes) / 2.29 M (full) | `holdings_v2`, `fund_holdings_v2`, `fund_universe` (all L3) | quarterly 13F + N-PORT load | **Flag — narrow to default-only (~12 K rows) or skip in favor of result cache** |

### §6.1 Sequencing suggestion

1. Ship `sector_flows_rollup` first — clear win, smallest scope, validates the P0 template on a non-`peer_rotation` precompute.
2. Refactor `get_sector_flow_movers` `level='parent'` to read from `peer_rotation_flows`. No new pipeline; small queries.py change. Holds `level='fund'` on live SQL.
3. Decide on `cohort_by_ticker_from` separately — likely a result cache (1 day) rather than a precompute (3 days). If precompute is chosen anyway, scope to default-only (~12 K rows).

The ROADMAP "~3 days combined" estimate for perf-P1 holds if (1) and (2) are done as above and (3) lands as a result cache. A full materialization of all three at the dimensions originally implied by the names (especially "by_ticker_from" suggesting per-ticker × per-from-quarter rows) would run substantially longer and produce a 2 M+ row L4 table that may not earn its keep.

### §6.2 Open questions

- Should `peer_rotation_flows` gain a `level='manager'` rollup (manager-name within 13F) to absorb `get_sector_flow_movers level='fund'`? Adds ~5 M rows to a 17.5 M table — answer depends on whether that movers variant has real users.
- `cohort_by_ticker_from` — confirm with PM whether non-default `from_quarter` values are exercised at meaningful rate in production. If 95 % of traffic is the default cohort, default-only precompute or a 60 s result cache covers it.
- `get_sector_flows` returns "managers" count via `COUNT(DISTINCT cik)`. Precompute should preserve this — derivable directly during materialization, but worth confirming the precompute schema captures the count rather than re-deriving from peer_rotation_flows (which lost `cik`).
