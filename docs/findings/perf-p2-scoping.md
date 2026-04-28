# perf-P2 — precompute scoping for `flow_analysis`, `market_summary`, `holder_momentum`

_Prepared: 2026-04-28 — branch `claude/quizzical-saha-ee5658` off `main` HEAD `66b6e7c`._

_Tracker: [ROADMAP.md:21](ROADMAP.md:21) — perf-P2 follows perf-P0 (`peer_rotation_flows`, [PR #158](https://github.com/sergetismen/13f-ownership/pull/158) / [#159](https://github.com/sergetismen/13f-ownership/pull/159)) and perf-P1 (`sector_flows_rollup` + cohort cache, [PR #180](https://github.com/sergetismen/13f-ownership/pull/180) / [#181](https://github.com/sergetismen/13f-ownership/pull/181))._

_Read-only investigation. No code, no migrations, no precompute tables created. Latency measured against prod DB at `data/13f.duckdb` (24.0 GB), 4 parent quarters (`2025Q1`–`2025Q4`), 16 fund quarters (`2022Q3`–`2026Q2`), 12,000 parent tickers, 73,398 fund tickers, 2,339 fund families, 15,039 fund names._

---

## §1. TL;DR

| Target | Median ms (AAPL / EQT) | Recommendation | Why |
|---|---|---|---|
| `flow_analysis` | 181 / 117 (parent) ; 272 / 161 (fund) | **Flag — already largely precomputed; partial precompute only if needed** | Reads `investor_flows` + `ticker_flow_stats` for parent path. Live cost concentrated in (a) the `qoq_charts` block (3 SQLs, ~80–130 ms) and (b) the `level=fund` live path (uses `_compute_flows_live`). All variants under 300 ms; parent-level matches the perf-P0 target. New precompute returns marginal gains. |
| `get_market_summary` | 126 / 165 (limit=25 / 50) | **Precompute (small materialized table, ~800 rows)** | Output is tiny; latency tax is the per-row enrichment loop (1 + 4×N SQLs). A flat denormalized table closes that out. ROI is modest in absolute ms (≤170 ms today) but scales well — top-N ranking + entity-graph counts + nport_coverage in one read. |
| `holder_momentum` | **800 / 745 (parent)** ; 51 / 48 (fund) | **Precompute (parent path) — narrow scope OR cache the helper map** | Parent-path bottleneck is `_get_fund_children` (728 ms of 800 ms — confirmed): 25 ILIKE family-name matches against `fund_holdings_v2` per call. Fund path already <60 ms — leave alone. Two options for the parent path detailed in §4.6. |

The three are **not** equivalent: `holder_momentum` parent is the only target with a real latency problem (~10× slower than the others); `get_market_summary` is a low-risk warm-up; `flow_analysis` is already covered by perf-P0-era precomputes (`investor_flows` + `ticker_flow_stats`) and likely doesn't earn a new table.

---

## §2. Target 1 — `flow_analysis`

### §2.1 Source function

`flow_analysis(ticker, period='1Q', peers=None, level='parent', active_only=False, rollup_type='economic_control_v1', quarter=LQ)` — [scripts/queries.py:3042](scripts/queries.py:3042).

The function already short-circuits to existing precompute tables when `level='parent'`:

- Reads `investor_flows` directly ([scripts/queries.py:3091](scripts/queries.py:3091)) — keyed on `(ticker, quarter_from, rollup_type)` — and slices to top-25 buyers / sellers / new entries / exits in Python.
- Reads `ticker_flow_stats` for chart series ([scripts/queries.py:3151](scripts/queries.py:3151), [3168](scripts/queries.py:3168)).
- Falls back to `_compute_flows_live()` ([scripts/queries.py:2906](scripts/queries.py:2906)) when `level='fund'` (no fund-level precompute today) or when no rows are stamped for `(ticker, quarter_from, rollup_type)`.

After the precompute reads it runs a separate **live** block that *re-aggregates* `holdings_v2` for each consecutive quarter pair to populate `qoq_charts` ([scripts/queries.py:3185–3237](scripts/queries.py:3185)) — 3 SQLs per call, GROUP BY rollup × manager_type for the subject ticker only.

### §2.2 Latency

Median of 3 runs:

| Variant | Run 1 | Run 2 | Run 3 | **Median** |
|---|--:|--:|--:|--:|
| AAPL · `period=1Q` · `level=parent` | 344 ms | 181 ms | 176 ms | **181 ms** |
| EQT · `period=1Q` · `level=parent` | 117 ms | 121 ms | 117 ms | **117 ms** |
| AAPL · `period=1Q` · `level=fund` | 335 ms | 272 ms | 249 ms | **272 ms** |
| EQT · `period=1Q` · `level=fund` | 161 ms | 155 ms | 208 ms | **161 ms** |
| AAPL · `period=4Q` · `level=parent` | 373 ms | 237 ms | 233 ms | **237 ms** |

Hot-path verification (separate timing): the 3 `qoq_charts` SQLs alone cost **127 ms (AAPL)** / **80 ms (EQT)** — i.e. ~50–70 % of the parent-path total. The remainder is the precompute read + Python row-shaping.

### §2.3 Input dimensions

- `ticker` — 12,000 parent / 73,398 fund.
- `period` ∈ {`1Q`, `2Q`, `4Q`} → mapped to `quarter_from` ∈ {`PQ`, `QUARTERS[1]`, `FQ`}.
- `peers` — comma-separated tickers; only affects the `chart_data` lookup in `ticker_flow_stats` (already keyed by ticker).
- `level` ∈ {`parent`, `fund`}.
- `active_only` ∈ {`True`, `False`} — only meaningful on the live fund path; the parent path slices the precompute output without re-filtering.
- `rollup_type` ∈ {`economic_control_v1`, `decision_maker_v1`}.
- `quarter` (the "to" side) — defaults to `LQ`. `period` resolves to a `quarter_from` independent of `quarter`.

### §2.4 Precompute footprint (current and hypothetical)

**Existing — already in production:**

| Table | Rows | Distinct (ticker, qf, rt) | Notes |
|---|--:|--:|---|
| `investor_flows` | 19,224,688 | 69,142 | 3 `quarter_from` values (`2025Q1`/`Q2`/`Q3`); avg 278 entity-rows per (ticker, qf, rt) cell |
| `ticker_flow_stats` | 69,142 | 11,934 tickers × 3 quarter-pairs × 2 rollup_types | Backs `flow_intensity`, `churn` charts |

**Hypothetical additions (if perf-P2 expanded the precompute):**

| Component | Rows |
|---|--:|
| `qoq_charts` per (ticker, quarter_pair, manager_type, rollup_type) | 12 K × 3 × ~6 manager_types × 2 = **~432 K** |
| Fund-level `investor_flows` extension (+`level` column) | 73 K × 15 fund pairs × ~50 funds avg ≈ **~55 M** |
| Fund-level `ticker_flow_stats` extension | 73 K × 15 × 2 = **~2.2 M** |

The fund-level extension is the only one with material headroom — but median fund-level latency is already 161–272 ms, so the win is small.

### §2.5 Source tables and rebuild trigger

- **Reads (current parent path):** `investor_flows` (L4), `ticker_flow_stats` (L4), `holdings_v2` (L3 — for implied prices + `qoq_charts`), `market_data` (L3 — market cap).
- **Reads (current fund path):** `fund_holdings_v2` (L3) directly; `fund_universe` (L3) for `is_actively_managed`.
- **Existing rebuild trigger** for `investor_flows`/`ticker_flow_stats`: `scripts/compute_flows.py`, `freshness_target_hours=24` ([registry.py:287](scripts/pipeline/registry.py:287)). Wired to `holdings_v2`. Rebuild runs after each quarterly 13F load.

### §2.6 perf-P0 / P1 reusable patterns

- `peer_rotation_flows` ([scripts/pipeline/compute_peer_rotation.py](scripts/pipeline/compute_peer_rotation.py), 17.5 M rows) **does not** preserve `manager_type` per-row in a way that matches `flow_analysis`'s `qoq_charts` requirements (`peer_rotation_flows.entity_type` is filterable but `qoq_charts` needs the bucket sums per `manager_type` for ALL entity_types simultaneously to compute `flow_intensity_passive`/`active`/`total`). Reuse would require either widening the table or grouping at read-time across all 20 entity_type values.
- `sector_flows_rollup` ([scripts/pipeline/compute_sector_flows.py](scripts/pipeline/compute_sector_flows.py), 321 rows) is sector-level, not ticker-level — not reusable here.
- The `SourcePipeline` subclass + migration template established in P0/P1 (described in [perf-p1-scoping.md §5](docs/findings/perf-p1-scoping.md)) is reusable verbatim if a `qoq_chart_stats` precompute is pursued.

### §2.7 Verdict — flag

**Likely skip new precompute.** Reasons:

1. Parent-path latency (117–237 ms) is already in the perf-P0 target zone. The bottleneck (`qoq_charts`) is structural, not unbounded — only 3 SQLs, scoped to the subject ticker.
2. Fund-path latency (161–272 ms) is borderline; a fund-level extension of `investor_flows` would cost ~55 M new rows for a ~150 ms latency gain.
3. The hot-path SQLs (`qoq_charts`) are *already* much smaller than perf-P0/P1 wins — there is no 5-second baseline to amortize against.

If a precompute is pursued anyway, the cheapest scope is:

- **Option A** — precompute `qoq_charts` per `(ticker, quarter_from, quarter_to, manager_type, rollup_type)` only, ~432 K rows. Target: ~80–130 ms → <20 ms (parent path improvement only).
- **Option B** — extend `investor_flows`/`ticker_flow_stats` schema with a `level` column and run `compute_flows.py` on `fund_holdings_v2` too. ~55 M new rows. Target: 272 ms → <100 ms (fund path).

Neither is high-ROI relative to the work; recommend **deferring P2's `flow_analysis` slice** unless production telemetry shows specific complaints.

---

## §3. Target 2 — `get_market_summary`

### §3.1 Source function

`get_market_summary(limit=25, quarter=LQ, rollup_type='economic_control_v1')` — [scripts/queries.py:4171](scripts/queries.py:4171).

Single primary query against `holdings_v2` that ranks the top-N institutions by `SUM(market_value_usd)` ([scripts/queries.py:4184–4199](scripts/queries.py:4184)). Then for *each* of the N rows, runs **four enrichment SQLs**:

1. `entity_aliases` lookup → `entity_id`
2. `entity_relationships` + `entity_identifiers` join → `filer_count`
3. `entity_relationships` `relationship_type='fund_sponsor'` → `fund_count`
4. `summary_by_parent` lookup → `nport_coverage_pct`

Self-CIK fallback inside step 2 is one more SQL. Net: **1 + 5×N round-trips per call** (101 SQLs at `limit=25`, 251 at `limit=50`).

### §3.2 Latency

Median of 3 runs:

| Variant | Run 1 | Run 2 | Run 3 | **Median** |
|---|--:|--:|--:|--:|
| `limit=25` | 146 ms | 126 ms | 124 ms | **126 ms** |
| `limit=50` | 168 ms | 165 ms | 163 ms | **165 ms** |

Latency scales linearly in `limit` (~1 ms per N). Already under 200 ms — DuckDB is fast even at 100+ round-trips.

### §3.3 Input dimensions

- `quarter` ∈ `QUARTERS` (4 parent quarters today).
- `rollup_type` ∈ {`economic_control_v1`, `decision_maker_v1`}.
- `limit` — caller-controlled int, in practice ≤100.

`limit` is a **slice** of a stable ranking, not a filter — a precompute can store the top-N for some N=cap (say 100) and slice at read time.

### §3.4 Precompute size

| Dim | Cardinality |
|---|--:|
| Quarter | 4 |
| `rollup_type` | 2 |
| Top-N cap | 100 (proposed) |

- **Total: 4 × 2 × 100 = 800 rows.** Trivial.
- Per-row payload: `institution`, `total_aum`, `num_holdings`, `num_ciks`, `manager_type`, `entity_id`, `filer_count`, `fund_count`, `nport_coverage_pct`, `rank`. ~10 columns.
- Total table size: <100 KB.

### §3.5 Source tables and rebuild trigger

- **Reads:** `holdings_v2` (L3), `entity_aliases` (L3), `entity_relationships` (L3), `entity_identifiers` (L3), `summary_by_parent` (L4).
- **Layer:** would be L4 (precompute / derived).
- **Rebuild trigger:** quarterly 13F load (when `holdings_v2` gains a new quarter); also when entity layer is reshuffled (`entity_relationships` / `entity_aliases` updates from the `entity_overrides` admin workflow). Already a pipeline pattern in `summary_by_parent`. Cost: trivial — a small ranked aggregate.
- **Note:** `summary_by_parent` is an existing L4 dependency. Precompute ordering matters — `market_summary_top` would need to land *after* `summary_by_parent` in the rebuild graph.

### §3.6 perf-P0 / P1 reuse

- `peer_rotation_flows` and `sector_flows_rollup` are flow-shaped, not AUM-shaped. Not reusable.
- `summary_by_parent` already supplies `nport_coverage_pct` per (parent, quarter, rollup_type) — the precompute should keep reading it at materialization time rather than re-compute.
- `SourcePipeline` template + migration template (perf-P0/P1) directly applicable: ~150-line `SourcePipeline` subclass, ~150-line migration. The promote step doesn't need the per-PK DELETE override (800 rows, base ABC suffices).

### §3.7 Verdict

**Precompute (small materialized table, ~800 rows).** ROI is modest in absolute ms (126 → ~20 ms target, ~110 ms saved per call), but:

- Tiny output — no concerns about table bloat or rebuild time.
- Eliminates an N+1 query pattern that scales linearly with `limit`.
- Validates the perf-P0 template on an entity-layer-aware precompute (filer/fund counts).

Conservative estimate: ~1 day of work — migration + `SourcePipeline` subclass + `get_market_summary` rewrite + parity test. No new index design needed (PK fits naturally on `(quarter, rollup_type, rank)`).

---

## §4. Target 3 — `holder_momentum`

### §4.1 Source function

`holder_momentum(ticker, level='parent', active_only=False, rollup_type='economic_control_v1', quarter=LQ)` — [scripts/queries.py:1204](scripts/queries.py:1204).

Two branches with very different shapes:

- **`level='fund'`** ([scripts/queries.py:1217–1274](scripts/queries.py:1217)) — top-25 funds by latest-quarter market value, plus their share series across all 16 fund quarters. **2 SQLs total.** Returns a flat list of 25.
- **`level='parent'`** ([scripts/queries.py:1276–1417](scripts/queries.py:1276)) — top-25 parents by latest-quarter market value (1 SQL), per-quarter parent shares (1 SQL), then **for each of the 25 parents** an `ILIKE`-pattern fund-children lookup against `fund_holdings_v2` via `match_nport_family()` ([scripts/queries.py:329](scripts/queries.py:329)) and `_build_excl_clause()` ([scripts/queries.py:441](scripts/queries.py:441)) — **27 SQLs total** (2 + 25), each child query scanning `fund_holdings_v2` with `family_name ILIKE ?` predicates.

The parent path returns a hierarchical `[parent, child, child, parent, child, ...]` list with `level=0` / `level=1` rows interleaved.

### §4.2 Latency

Median of 3 runs:

| Variant | Run 1 | Run 2 | Run 3 | **Median** |
|---|--:|--:|--:|--:|
| AAPL · `level=parent` | 831 ms | 800 ms | 799 ms | **800 ms** |
| EQT · `level=parent` | 736 ms | 745 ms | 745 ms | **745 ms** |
| AAPL · `level=fund` | 51 ms | 50 ms | 51 ms | **51 ms** |
| EQT · `level=fund` | 50 ms | 48 ms | 47 ms | **48 ms** |

Hot-path verification:

| Sub-step | AAPL ms |
|---|--:|
| Top-25 parents query | 24 |
| Parent shares-by-quarter query | 79 |
| `_get_fund_children` loop (25 parents × ILIKE family match) | **728** |

**~91 % of parent-path latency lives in the per-parent N-PORT children loop**, not in the top-25 selection or share aggregation. Each iteration does a `family_name ILIKE` against `fund_holdings_v2` (14.6 M rows), filtered to a single ticker. The per-call work is largely independent of `ticker` — the 25 parents are mostly the same large institutions across tickers (BlackRock, Vanguard, Fidelity, etc.), so the same 25 ILIKE patterns run repeatedly.

### §4.3 Input dimensions

- `ticker` — 12,000 parent / 73,398 fund.
- `level` ∈ {`parent`, `fund`}.
- `active_only` ∈ {`True`, `False`} — fund path only (uses `fund_universe.is_actively_managed`); parent path **ignores** it (no SQL filter applied).
- `rollup_type` ∈ {`economic_control_v1`, `decision_maker_v1`} — parent path only (selects `rollup_name` vs `dm_rollup_name` via `_rollup_col`).
- `quarter` — used as the "latest" anchor; defaults to `LQ`. The function reads all `QUARTERS` for the share series.

### §4.4 Precompute size

Two materialization shapes are plausible:

**(a) Full result materialization:**

| Dim | Cardinality | Subtotal |
|---|--:|--:|
| Parent path: ticker × rollup_type × top-25 entities | 12 K × 2 × 25 | 600 K parent rows |
| Parent path: + up to ~10 fund-children per parent | 600 K × 10 | ~6.0 M child rows |
| Fund path: ticker × active_only × top-25 funds | 73 K × 2 × 25 | ~3.65 M fund rows |
| **Grand total** | | **~10 M rows** |

(Note: parent path ignores `active_only` today, so the dimension drops out.)

**(b) Helper-map only (recommended):**

Precompute the slow part — the parent-name → fund-name mapping — as a small lookup table:

| Component | Rows |
|---|--:|
| `parent_to_fund_map` (`inst_parent_name`, `series_id`, `fund_name`, `family_name`) over all 12 K parents × 10–50 fund children avg | **~200 K–600 K rows** |

This is what `_get_fund_children` builds on the fly via `match_nport_family()` + ILIKE — caching it eliminates the 25 ILIKE round-trips per call.

The fund-name<>family-name relationships only change when N-PORT loads new families (rare; fund families are stable on multi-quarter cadence).

### §4.5 Source tables and rebuild trigger

- **Reads:** `holdings_v2` (L3), `fund_holdings_v2` (L3), `fund_universe` (L3 — for active filter on fund path), `securities` (L3 — for cusip lookup via `get_cusip`).
- **Layer:** would be L4 (precompute / derived).
- **Rebuild trigger:** quarterly 13F load (parent path top-25 selection + share trends) and quarterly N-PORT load (fund path top-25, parent→fund map). The parent→fund family map can lag the N-PORT load by hours — N-PORT fund families are slowly changing (15 K fund_names today).

### §4.6 perf-P0 / P1 reuse

- `peer_rotation_flows` keys on `(quarter_from, quarter_to, sector, entity, ticker)` — no per-quarter share value, only `active_flow` deltas. Not reusable for `holder_momentum`'s 4-quarter share *level* series.
- `sector_flows_rollup` is sector-aggregated. Not reusable.
- The closest existing precompute is `summary_by_parent` (entity × ticker × quarter × rollup_type) — it captures top-level inst metrics but not share trends.
- `SourcePipeline` template applies directly. The interesting twist for option (b) is that the rebuild source for `parent_to_fund_map` includes `match_nport_family()` Python logic, not pure SQL — same shape as `compute_flows.py` rather than `compute_peer_rotation.py`.

### §4.7 Verdict

**Precompute the parent path. Two viable scopes — recommend option (b).**

- **Option (a)** — full result materialization (~10 M rows). Direct read at runtime, ~50 ms target. But 10 M-row table for an endpoint that is essentially a tiny per-ticker leaderboard feels heavy, and the rebuild has to re-run the 12 K × 25 = 300 K-iteration ILIKE work every quarter.
- **Option (b)** — small `parent_to_fund_map` precompute (~200–600 K rows), plus rewriting `_get_fund_children` to read it. Closes the 728 ms bottleneck without materializing every (ticker, parent) leaderboard. Latency target: 800 ms → ~150 ms.

The fund-level path needs no work — already 50 ms. Both `level='fund'` and `level='parent'` are user-facing today; both should ship in the same PR if option (b) is pursued (so the parent path actually uses the new map).

A side benefit of option (b): `match_nport_family()` is also called from `query2`, `cohort_analysis`'s `_get_nport_children`, and other helpers — a shared cache benefits multiple tabs.

Conservative estimate: ~2 days for option (b) — migration + `SourcePipeline` subclass that runs `match_nport_family()` over the parent universe + queries.py rewrite (touching `holder_momentum`, `_get_nport_children`, and any other family-match callers) + parity tests. Option (a) is closer to 3 days due to the larger table + index design.

---

## §5. Summary

| Target | Function | Median ms | Precompute rows | Source tables | Rebuild trigger | Recommendation |
|---|---|---|--:|---|---|---|
| `flow_analysis` | `flow_analysis` ([queries.py:3042](scripts/queries.py:3042)) | 181 (AAPL parent) / 117 (EQT parent) / 272 (AAPL fund) / 161 (EQT fund) | already covered (19.2 M `investor_flows` + 69 K `ticker_flow_stats`); hypothetical adds: 432 K (qoq) or 55 M (fund extension) | `investor_flows` + `ticker_flow_stats` (L4), `holdings_v2` + `fund_holdings_v2` + `market_data` (L3) | quarterly 13F + N-PORT load (existing pipeline) | **Flag — defer; already <300 ms** |
| `get_market_summary` | `get_market_summary` ([queries.py:4171](scripts/queries.py:4171)) | 126 (limit=25) / 165 (limit=50) | **~800** | `holdings_v2` + `entity_aliases` + `entity_relationships` + `entity_identifiers` + `summary_by_parent` (L3/L4) | quarterly 13F load + entity-layer reshuffle | **Precompute (small materialized table)** |
| `holder_momentum` | `holder_momentum` ([queries.py:1204](scripts/queries.py:1204)) | **800 (AAPL parent) / 745 (EQT parent)** ; 51 / 48 (fund) | option (a) ~10 M; **option (b) ~200–600 K (recommended)** | `holdings_v2`, `fund_holdings_v2`, `fund_universe`, `securities` (all L3) | quarterly 13F + N-PORT load | **Precompute parent path — option (b) `parent_to_fund_map` helper** |

### §5.1 Sequencing suggestion

1. Ship `holder_momentum` first via option (b) — biggest absolute latency win (~10× on parent path), and the helper map benefits other family-match callers (`query2`, cohort, etc.).
2. Ship `get_market_summary` second — small, well-bounded table; validates the perf-P0/P1 template on an entity-layer-aware precompute.
3. Defer `flow_analysis` until production telemetry shows specific complaints. If forced, scope to the qoq-charts precompute (option A in §2.7) — 432 K rows for ~110 ms saved on the parent path.

### §5.2 Flagged targets

- **`flow_analysis`** — already heavily precomputed; remaining live work (`qoq_charts`, fund path) costs <200 ms. New precompute likely fails an ROI bar.

### §5.3 Open questions

- For `holder_momentum` option (b): should `parent_to_fund_map` live alongside `entity_relationships` (true ownership relationships) or as a query-helper cache (relaxed semantics, ILIKE-derived)? The two are semantically different — `entity_relationships` says "entity X owns entity Y," `match_nport_family()` says "fund-name ILIKE family-pattern" and is therefore noisy. Recommend the latter — it's a query helper, not authoritative entity data.
- For `get_market_summary`: the `nport_coverage_pct` per row sources from `summary_by_parent`. The precompute should bake the coverage in at materialization time so a single read returns the full row, but that couples the precompute's freshness to `summary_by_parent`'s rebuild cadence (`freshness_target_hours=24*37`). Confirm the staleness window is acceptable, or leave coverage as a runtime lookup.
- For `flow_analysis`: `qoq_charts` aggregates by `manager_type` for *all* entity types (passive, active, hedge_fund, etc.). If a fund-level precompute is added, it should preserve manager_type granularity rather than collapsing — `peer_rotation_flows` did the latter and would not satisfy this consumer.
