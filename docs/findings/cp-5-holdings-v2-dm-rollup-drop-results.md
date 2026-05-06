# cp-5-holdings-v2-dm-rollup-drop — Migration Results

**Date:** 2026-05-06
**Branch:** `cp-5-holdings-v2-dm-rollup-drop`
**Source plan:** chat decision 2026-05-05 (sister-table follow-on to PR #289).
PR #295's drop PR ships before CP-5.1 to ensure clean ERH-as-canonical
foundation for the read-layer scoping.

**HEAD before migration:** `2e116b1` (PR #295 sister-table investigation).

---

## 1. Phase 1 — re-validation against PR #295

| Check | Result |
|------|--------|
| `holdings_v2.dm_rollup_entity_id` PRESENT | YES |
| `holdings_v2.dm_rollup_name` PRESENT | YES |
| Rows in `holdings_v2` | 12,270,984 |
| `dm_rollup_entity_id` populated | 12,270,984 (100.00%) |
| `dm_rollup_name` populated | 12,270,984 (100.00%) |

**Method A correctness (Phase 1c):** 10 sample drift entities all resolve
to non-null `(rollup_entity_id, canonical_name)` via the read-time
`entity_rollup_history` JOIN. Sample includes UBS AM (entity_id=3583 →
3583), Equitable/AllianceBernstein (8497 → 8497 = ALLIANCEBERNSTEIN
L.P.), Victory Capital (9130 → 9130), Natixis IM/Loomis Sayles (2271 →
2271, 7650 → 7650). All 10 / 10 drift cases produce a non-null
`canonical_name` from the ERH JOIN — Method A is correct on the drift
cohort.

**Reader inventory drift since PR #295:** none in `scripts/queries/`
(re-grep confirms 16 `_rollup_col` sites + 1 direct
`dm_rollup_entity_id` reference in `trend.py:111`, matching PR #295's
"~17 production reader sites"). However, this PR **expands scope**
beyond PR #295's `scripts/queries/` inventory — see §2.

---

## 2. Scope expansion beyond PR #295

PR #295's reader inventory scoped only `scripts/queries/`. A wider
audit (this PR) found 5 additional `holdings_v2.dm_rollup_*` reader
sites in pipeline / fixture code that recompute derived tables on a
schedule. Leaving them unmigrated would break the next pipeline run
once the columns are dropped.

| File | Function | Read pattern |
|------|----------|--------------|
| `scripts/compute_flows.py` | `_insert_period_flows`, `_project_period_flows` | `_ROLLUP_SPECS` 3-tuple drives `{rid_col}` / `{rname_col}` substitution into 4 `FROM holdings_v2` SELECTs |
| `scripts/build_summaries.py` | `_build_summary_by_parent`, `_project_summary_by_parent` | Same `_ROLLUP_SPECS` shape over `summary_by_parent` rebuild |
| `scripts/pipeline/compute_peer_rotation.py` | `_materialize_parent_agg` | `MAX(dm_rollup_name)` materialized into the `h_agg_pair` temp table |
| `scripts/pipeline/compute_parent_fund_map.py` | `_run` (DISTINCT pattern walk), `_project_dry_run` | `_PARENT_ROLLUP_SPECS` 3-tuple plus a dry-run `COUNT(DISTINCT dm_rollup_entity_id)` |
| `scripts/build_fixture.py` | seed UNION | `dm_rollup_entity_id` arm of the entity-closure seed |

All five were migrated to Method A in this PR.

---

## 3. Schema migration

`scripts/migrations/025_drop_holdings_v2_dm_rollup_denorm.py` applied
against `data/13f.duckdb` at 2026-05-06.

**Mechanism — CTAS-and-swap (not `ALTER TABLE DROP COLUMN`):**

`holdings_v2` carries a `PRIMARY KEY` constraint on `row_id` (column
33). DuckDB rejects `DROP COLUMN` when any index — including the
implicit PK index — sits on a column positioned after the dropped one,
and DuckDB does not support `ALTER TABLE DROP CONSTRAINT`. Sequence:

1. `DROP INDEX IF EXISTS` for all six named indexes
   (`idx_holdings_v2_latest`, `idx_holdings_v2_row_id`,
   `idx_hv2_cik_quarter`, `idx_hv2_entity_id`, `idx_hv2_rollup`,
   `idx_hv2_ticker_quarter`).
2. `CREATE TABLE holdings_v2_new AS SELECT * EXCLUDE
   (dm_rollup_entity_id, dm_rollup_name) FROM holdings_v2`.
3. Row-count assertion: 12,270,984 = 12,270,984.
4. `DROP TABLE holdings_v2; ALTER TABLE holdings_v2_new RENAME TO
   holdings_v2`.
5. `ALTER TABLE holdings_v2 ADD CONSTRAINT holdings_v2_row_id_pkey
   PRIMARY KEY (row_id)`.
6. Six `CREATE INDEX` statements restore the index set verbatim.
7. `INSERT schema_versions` stamp + `CHECKPOINT`.

**`schema_versions` stamp:** `025_drop_holdings_v2_dm_rollup_denorm` at
2026-05-06.

---

## 4. Reader migrations (16 in scripts/queries/ + 5 pipeline)

| ID | File | Function / line | Change |
|----|------|-----------------|--------|
| R1 | `scripts/queries/cross.py` | `_cross_ownership_query` (33) | `_rollup_col` → `_rollup_name_sql('h', rollup_type)`; `h.{rn}` → `{rn}` (lines 61, 74) |
| R2 | `scripts/queries/trend.py` | `holder_momentum` (35) | `_rollup_col` → `_rollup_name_sql('', rollup_type)` |
| R3 | `scripts/queries/trend.py` | `holder_momentum` (111) | direct `dm_rollup_entity_id` literal → `_rollup_eid_sql('', rollup_type)` |
| R4 | `scripts/queries/trend.py` | `ownership_trend_summary` (331) | `_rollup_col` → `_rollup_name_sql('', rollup_type)` |
| R5 | `scripts/queries/register.py` | `query1` (42) | `_rollup_name_sql('h', …)` + `h.{rn}` → `{rn}` (4 sites in this fn) |
| R6 | `scripts/queries/register.py` | `query2` (270) | `_rollup_name_sql('', …)` |
| R7 | `scripts/queries/register.py` | `query3` (449) | `_rollup_name_sql('h', …)` + `h.{rn}` → `{rn}` |
| R8 | `scripts/queries/register.py` | `query5` (775) | `_rollup_name_sql('', …)` |
| R9 | `scripts/queries/register.py` | `query12` (1088) | `_rollup_name_sql('', …)` |
| R10 | `scripts/queries/register.py` | `query14` (1119) | `_rollup_name_sql('h', …)` + `h.{rn}` → `{rn}` (2 sites) |
| R11 | `scripts/queries/fund.py` | `concentration` (48) | both aliased + unaliased bindings |
| R12 | `scripts/queries/market.py` | `short_interest_analysis` (585) | `_rollup_name_sql('', …)` |
| R13 | `scripts/queries/flows.py` | `_cohort_analysis_impl` (211) | `_rollup_name_sql('', …)` |
| R14 | `scripts/queries/flows.py` | `_compute_flows_live` (320) | `_rollup_name_sql('', …)` |
| R15 | `scripts/queries/flows.py` | `flow_analysis` (461) | `_rollup_name_sql('', …)` |
| R16 | `scripts/queries/common.py` | `get_13f_children` (758) | `_rollup_name_sql('h', …)` + `h.{rn}` → `{rn}` |
| H1 | `scripts/queries/common.py` | helpers (49–88) | NEW `_rollup_name_sql` + `_rollup_eid_sql`; OLD `_rollup_col` removed |
| H2 | `scripts/queries/__init__.py` | exports (25) | swap `_rollup_col` → `_rollup_name_sql` + `_rollup_eid_sql` |
| P1 | `scripts/compute_flows.py` | `_ROLLUP_SPECS` (47) + 2 SQLs | spec entries change shape to (label, rid SQL expr, rname SQL expr); `h` alias added to FROM clauses |
| P2 | `scripts/build_summaries.py` | `_ROLLUP_SPECS` (60) + 2 SQLs | same shape change as P1; `h.` prefix removed where `{rid_col}` already includes it |
| P3 | `scripts/pipeline/compute_peer_rotation.py` | `_materialize_parent_agg` (397) | `MAX(dm_rollup_name)` → `MAX(dm_e.canonical_name)` via LEFT JOIN ERH + entities |
| P4 | `scripts/pipeline/compute_parent_fund_map.py` | `_PARENT_ROLLUP_SPECS` (95) + DISTINCT walk + dry-run | spec shape change; dry-run DM count rewritten with explicit JOIN to ERH |
| P5 | `scripts/build_fixture.py` | seed_sql UNION (232) | drop the `dm_rollup_entity_id` arm; closure walk reaches DM eids via ERH from EC seed |

Method A (read-time JOIN) is implemented as a correlated scalar
subquery in the `_rollup_name_sql` / `_rollup_eid_sql` helpers, and as
explicit per-call CTEs / LEFT JOINs in the pipeline files where the
rollup expression appears in `GROUP BY` / aggregation contexts.

---

## 5. Writer retirements (1 file, 3 sites)

| ID | File | Function | Change |
|----|------|----------|--------|
| W1 | `scripts/load_13f_v2.py` | `_STG_HOLDINGS_V2_DDL` (150) | Remove `dm_rollup_entity_id BIGINT` and `dm_rollup_name VARCHAR` columns |
| W2 | `scripts/load_13f_v2.py` | `_TARGET_TABLE_COLUMNS` (231) | Remove the two corresponding tuples |
| W3 | `scripts/load_13f_v2.py` | INSERT column list + NULL SELECT (499/537–538) | Remove the two `NULL AS …` projections plus their column-list entries |

No live UPDATE writer was identified in `scripts/pipeline/`,
`scripts/enrich_holdings.py`, `scripts/build_managers.py`, or
`scripts/load_13f_v2.py` (matches PR #295 §1.4). The `scripts/oneoff/`
post-hoc reconcilers that historically wrote to
`holdings_v2.dm_rollup_*` (`inst_eid_bridge_aliases_merge.py`, CP-4b
authors, `dera_synthetic_stabilize.py`) are not modified — they retire
automatically once the columns are absent (any future invocation will
fail loudly with "column not found", which is the desired safety net).

---

## 6. Hard guards (Phase 3)

All seven gates PASS.

| Gate | Check | Result |
|------|-------|--------|
| G1 | `dm_rollup_entity_id` ABSENT from `holdings_v2` | PASS |
| G2 | `dm_rollup_name` ABSENT from `holdings_v2` | PASS |
| G3 | Row count unchanged (12,270,984 → 12,270,984) | PASS |
| G4 | `entity_id IS NOT NULL` rows unchanged (12,270,984) | PASS |
| G5 | All six named indexes present + PK constraint restored | PASS |
| G6 | pytest 416 / 416 | PASS |
| G7 | React build clean (`tsc -b && vite build`) | PASS |

Indexes after migration: `idx_holdings_v2_latest`,
`idx_holdings_v2_row_id`, `idx_hv2_cik_quarter`, `idx_hv2_entity_id`,
`idx_hv2_rollup`, `idx_hv2_ticker_quarter`. PK constraint
`holdings_v2_row_id_pkey` confirmed via `duckdb_constraints()`.

A bug surfaced once during pytest first-run: an `h.{rn}` substitution
in `register.py` (3 sites in `query1` between the two helper calls)
produced `h.h.rollup_name`. Fixed with a `replace_all` Edit; pytest
went from 235 passed / 1 failed → 416 / 416.

---

## 7. App smoke (Phase 5)

Application booted against `data/13f.duckdb` after migration. Five
endpoints exercised across both rollup_types:

| Endpoint | Result |
|----------|--------|
| `GET /api/v1/summary?ticker=AAPL` | 200 |
| `GET /api/v1/query1?ticker=AAPL` | 200 |
| `GET /api/v1/query1?ticker=AAPL&rollup_type=decision_maker_v1` | 200 |
| `GET /api/v1/cross_ownership?tickers=MSFT,GOOGL&quarter=2025Q4` | 200 |
| `GET /api/v1/cross_ownership?tickers=MSFT,GOOGL&quarter=2025Q4&rollup_type=decision_maker_v1` | 200 |
| `GET /api/v1/flow_analysis?ticker=AAPL` | 200 |
| `GET /api/v1/flow_analysis?ticker=AAPL&rollup_type=decision_maker_v1` | 200 |

No errors, no 500s. Both EC and DM rollup paths resolve.

---

## 8. Phase 4 — peer-rotation smoke

`compute_peer_rotation` module imports clean against migrated schema.
The migrated `_materialize_parent_agg` SQL was exercised inline against
prod (AAPL Q3→Q4 2025 scope): 11,440 `h_agg_pair` rows produced;
`rollup_name` populated 11,440 / 11,440; `dm_rollup_name`
(now ERH-resolved) populated 11,440 / 11,440. ERH JOIN materialization
matches the prior denormalized read population.

---

## 9. CP-5 status after this PR

P0 pre-execution count: **9 / 11 PRs shipped.**

Remaining P0:
- **`conv-30-doc-sync`** — bundles `beneficial_ownership_v2.dm_rollup_*`
  drop (small; zero production readers per PR #295 §2) plus ROADMAP /
  NEXT_SESSION_CONTEXT updates for the full P0 arc.
- **CP-5.1** — read-layer scoping begins.

---

## 10. Out-of-scope discoveries / surprises

1. **PRIMARY KEY constraint blocks `ALTER TABLE DROP COLUMN`.** The
   fhv2 drop (PR #289) used `UNIQUE INDEX` on `row_id`, which DuckDB
   handles via `DROP INDEX` + `DROP COLUMN` + `CREATE INDEX`.
   `holdings_v2` instead carries a true `PRIMARY KEY`, whose implicit
   index cannot be dropped via `DROP INDEX` and whose constraint
   cannot be dropped via `ALTER TABLE DROP CONSTRAINT` (not implemented
   in DuckDB). The CTAS-and-swap workaround (`SELECT * EXCLUDE` →
   `RENAME` → re-`ADD CONSTRAINT`) is the canonical solution; future
   sister-table drops on tables with PRIMARY KEYs should follow the
   same pattern.

2. **PR #295's scope was incomplete.** It inventoried only
   `scripts/queries/`. Five additional pipeline reader sites
   (`compute_flows.py`, `build_summaries.py`, `compute_peer_rotation.py`,
   `compute_parent_fund_map.py`, `build_fixture.py`) read
   `holdings_v2.dm_rollup_*` to populate derived tables and would have
   broken the next pipeline run if left unmigrated. Findings doc
   updated; no chat blocker (pattern is identical to the queries/
   migration).

3. **Correlated scalar subquery vs. per-call CTE/JOIN.** The
   `_rollup_name_sql` helper returns a correlated subquery, while the
   pipeline files use explicit LEFT JOINs to ERH. Both produce identical
   results. The correlated form is preferred in user-facing queries
   because it slots into existing query structure with minimal change;
   the LEFT JOIN form is preferred in pipeline writers because the
   rollup expression must appear in `GROUP BY` clauses where DuckDB's
   query planner handles the JOIN more predictably than repeated
   correlated lookups across millions of grouped rows. This split is
   not strictly necessary — the correlated form would also work in the
   pipeline contexts — but matches the read pattern of each file.

4. **`compute_peer_rotation._materialize_parent_agg` keeps the column
   name `dm_rollup_name` on the `h_agg_pair` temp table.** Downstream
   `_insert_parent_flows` references `c.{rn_col}` where `rn_col` is
   `'dm_rollup_name'` per `_PARENT_ROLLUP_SPECS`. Because the temp
   table's column carries the same name and downstream callers are
   indifferent to the source, no further change cascades.

---

## 11. References

- PR #289 — `docs/findings/cp-5-fh2-dm-rollup-drop-results.md` (drop
  pattern, 6 readers + 6 writers + 1 migration). This PR is the sister
  follow-on; pattern is reused, with the CTAS-and-swap addition for
  PRIMARY KEY handling.
- PR #295 — `docs/findings/cp-5-sister-tables-sized-investigation-
  results.md` (drift quantification + `scripts/queries/` reader
  inventory, drives the SHIP-BEFORE-CP-5.1 recommendation).
- Migration manifest CSV:
  `data/working/cp-5-holdings-v2-dm-rollup-drop-migration-manifest.csv`.
- Pre-migration backup:
  `data/backups/13f_backup_20260506_065231` (3.2 GB EXPORT DATABASE).
