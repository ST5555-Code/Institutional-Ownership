# cp-5-fh2-dm-rollup-decision-recon — results

Read-only recon for **Gap 2** from [cp-5-bundle-c-discovery.md §7.5](./cp-5-bundle-c-discovery.md):

> `fund_holdings_v2.dm_rollup_entity_id` denormalization staleness. SSGA-class drift after each ERH rebuild. Either (a) backfill the denorm column after every ERH rebuild (loader contract), or (b) drop the column and rely on Method-A JOIN (read-side cost).

Method A read-time ERH JOIN was locked canonical in PR #280. This recon
sizes the two remediation paths so the chat can pick before any execute
PR is authored.

HEAD: f9bec76 (cp-5-capital-group-umbrella PR #287).

---

## 1. Column footprint baseline (Phase 1)

### 1.1 Population status — `fund_holdings_v2` (whole table)

| metric | count | % of total |
| --- | ---: | ---: |
| total rows                                  | 14,569,125 | 100.00% |
| `dm_rollup_entity_id` populated             | 14,484,762 |  99.42% |
| `dm_rollup_name` populated                  | 14,063,751 |  96.53% |
| `dm_rollup_entity_id IS NOT NULL` AND `dm_rollup_name IS NULL` | 421,011 | 2.89% |
| `is_latest = TRUE`                          | 14,565,870 |  99.98% |
| `is_latest = FALSE`                         | 3,255      |   0.02% |

Two notable shapes:

* **421,011 rows where eid is populated but name is NULL** — these are
  rows whose decision-maker rollup entity has no `is_preferred=TRUE`
  alias. Surfaces a parallel data-quality issue (loader joins
  `entity_aliases` on `is_preferred=TRUE AND valid_to=sentinel`; if no
  alias matches, name is NULL while eid is set).
* **`is_latest=FALSE` is only 3,255 rows** — ~0.02% of the table. The
  fh2 SCD model is barely exercised; effectively the entire table is
  the current view. Backfill scope simplifies: `is_latest=TRUE` is
  ~the whole table.

### 1.2 Drift quantification — Method A vs Method B (top 50 top-parents)

Method A: read-time `entity_rollup_history` JOIN on
`rollup_type='decision_maker_v1' AND valid_to='9999-12-31'`, then climb
`inst_to_top_parent`.

Method B: denormalized `fh.dm_rollup_entity_id` column, climbed via the
same `inst_to_tp` map.

Top 25 by absolute delta ([data/working/cp-5-fh2-dm-rollup-drift.csv](../../data/working/cp-5-fh2-dm-rollup-drift.csv)):

| eid | top-parent | A $B | B $B | Δ $B |
| ---: | --- | ---: | ---: | ---: |
| 8652 | PRINCIPAL REAL ESTATE INVESTORS LLC | 0.37 | 110.18 | −109.82 |
| 7316 | PRINCIPAL FINANCIAL GROUP INC | 779.52 | 669.70 | +109.82 |
| 4071 | VOYA INVESTMENTS, LLC | 0.00 | 85.08 | −85.08 |
| 2489 | Voya Financial, Inc. | 210.00 | 129.95 | +80.05 |
| 18338 | BlueCove Limited | 0.00 | 57.77 | −57.77 |
| 18096 | Dimensional Fund Advisors LP | 0.00 | 52.29 | −52.29 |
| 5026 | Dimensional Fund Advisors | 3,206.29 | 3,154.01 | +52.29 |
| 9953 | Matson Money. Inc. | 55.34 | 14.86 | +40.48 |
| 8968 | AFFILIATED MANAGERS GROUP | 124.65 | 94.80 | +29.85 |
| 2426 | YACKTMAN ASSET MANAGEMENT LP | 0.00 | 29.57 | −29.57 |
| 9523 | ORIX Corp Europe N.V. | 274.64 | 261.80 | +12.84 |
| 3241 | BlackRock, Inc. | 2,549.50 | 2,540.70 | +8.80 |

Drift cluster: every drift case is a "child→new-parent re-point" —
Method B holds the pre-rebuild rollup (e.g. eid 8652 →
old terminal); Method A correctly climbs to the new top-parent (e.g.
7316 Principal Financial). SSGA's $778B hit from Bundle C §7.1 has
since been partially absorbed by subsequent N-PORT promotes (`_bulk_enrich_run`
re-stamped diverged rows on later loads); SSGA no longer in top 25 by
abs(Δ) but the same drift mechanism is alive in 12 firms with
$1B–$110B gaps each.

Per-fund alignment (active 2025Q4 funds, dm_rollup_eid Method A vs B):

| metric | n | % |
| --- | ---: | ---: |
| n_funds | 14,033 | 100.00% |
| n_aligned | 13,767 | 98.10% |
| n_diverged | 266 | 1.90% |

Down from Bundle C §7.1's 5.0% — load activity since 2026-05-03
(cp-4b-author-ssga PR #271) has partially re-stamped fh2.

### 1.3 `is_latest=FALSE` analysis

3,255 rows total — 100% have both `dm_rollup_entity_id` and
`dm_rollup_name` populated. Population matches `is_latest=TRUE`
(99.42%/96.53%); historical SCD churn is negligible. Backfill
decision is academic: even if Path 2 limits to `is_latest=TRUE`, the
ignored is_latest=FALSE tail is 3,255 rows.

---

## 2. Reader inventory (Phase 2)

### 2.1 Aggregate hits — `dm_rollup_entity_id` ∪ `dm_rollup_name` across `scripts/`, `web/`, `tests/`

[data/working/cp-5-fh2-dm-rollup-readers.csv](../../data/working/cp-5-fh2-dm-rollup-readers.csv) — 165 unique (file, line) hits (deduped across patterns).

| code_path | hits | files |
| --- | ---: | ---: |
| INVESTIGATION (`scripts/oneoff/`) | 24 | 7 |
| MIGRATION (`scripts/migrations/`) | 4 | 1 |
| PRODUCTION_BACKEND (`scripts/pipeline/`) | 41 | 5 |
| PRODUCTION_FRONTEND (`web/`) | 1 | 1 |
| PRODUCTION_QUERY (`scripts/queries/`, `queries_helpers`) | 7 | 3 |
| PRODUCTION_SCRIPT (`scripts/*.py`) | 34 | 6 |
| TEST (`tests/`) | 10 | 3 |
| ARCHIVE (`scripts/archive/`) | varies (excluded by SKIP_DIRS in `__pycache__/retired/`) | — |

### 2.2 PRODUCTION reader sites that touch `fund_holdings_v2.dm_rollup_*`

Most production hits referencing `dm_rollup_*` columns are against
**other tables** (`holdings_v2`, `beneficial_ownership_v2`) which
share the same denormalized pattern but are out of scope per the
plan. Filtering to actual `fund_holdings_v2` reader sites:

| feature / file | role | line | size if dropped |
| --- | --- | --- | --- |
| Cross-Ownership `has_fund_detail` flag — `scripts/queries/cross.py` (in `_cross_ownership_query`) | READER (`SELECT DISTINCT dm_rollup_name FROM fund_holdings_v2 WHERE … UNION SELECT family_name`) | 82–84 | XS — replace `dm_rollup_name` with ERH JOIN to `entity_aliases.alias_name` |
| Cross-Ownership fund detail filter (`get_cross_ownership_fund_detail`) — `scripts/queries/cross.py` | READER FILTER (`WHERE fh.dm_rollup_name = ? OR fh.family_name = ?`) | 268 | S — replace LHS with `EXISTS (SELECT 1 FROM ERH/aliases JOIN ON entity_id WHERE alias_name = ?)` |
| Two-company overlap subj_set (`get_two_company_overlap`) — `scripts/queries/cross.py` | READER FILTER (same shape) | 522 | S — same migration |
| `scripts/queries/common.py:52,56` (`_get_rollup_columns`) | READER (column-name selector for dynamic SQL) | 52,56 | XS — selector returns alias-target column; migrate to `entity_aliases.alias_name` reference |
| `scripts/queries/trend.py:111` (column-name selector) | READER | 111 | XS — same as common.py |
| `scripts/build_summaries.py:65–66` (`ROLLUP_COL_PAIRS`) — used to drive `parent_13f` / `nport_per_rollup` aggregation | READER (`SELECT fh.dm_rollup_entity_id, SUM(fh.market_value_usd) FROM fund_holdings_v2 GROUP BY …`) | 65,66,238–250 | M — replace `nport_rid_col` parameter with a JOIN against ERH; preserve query semantics |
| `scripts/build_fixture.py:235–239` (`seed_sql` UNION) | READER (UNION seed for entity closure) | 235,239 | XS — drop the `dm_rollup_entity_id` UNION branch entirely; the existing `entity_id` + `rollup_entity_id` UNION branches plus the recursive ERH closure already cover the eid set |
| `web/react-app/src/types/api.ts:394` | DOC COMMENT only | 394 | XS — update comment |

**Net production reader-migration cost (Path 1):**

* 6 distinct touch sites in 5 files
* 3 sites are **column-name selectors** (queries/common.py,
  queries/trend.py, build_summaries.py ROLLUP_COL_PAIRS) — refactor
  the dispatcher to JOIN against ERH+aliases instead of selecting a
  pre-denormalized column.
* 3 sites are **direct SELECT/WHERE references** in cross.py — replace
  with subquery against `entity_rollup_history`/`entity_aliases`.
* 1 build_fixture UNION branch — delete.
* 1 frontend comment — update.

Estimated total work: **~150 LOC across 5 files**, all within an
established pattern (the ERH JOIN already exists in
`scripts/oneoff/cp_5_coverage_matrix_revalidation.py:138-149` and
`scripts/pipeline/load_nport.py:984-1037`).

### 2.3 Out-of-scope hits (same pattern, different tables)

For reference — these hits surfaced in the grep but read from
`holdings_v2` or `beneficial_ownership_v2`, which the plan does not
scope:

* `scripts/queries/common.py` and `queries/cross.py` filtering on
  `holdings_v2.dm_rollup_*` (13F path, separate column).
* `scripts/pipeline/compute_peer_rotation.py:406` — reads
  `holdings_v2.dm_rollup_name` via `MAX(dm_rollup_name)`.
* `scripts/pipeline/compute_parent_fund_map.py:492-493` — counts
  distinct `holdings_v2.dm_rollup_entity_id`.
* `scripts/enrich_13dg.py` — read+write of
  `beneficial_ownership_v2.dm_rollup_*`.
* `scripts/pipeline/load_13dg.py` — INSERT into
  `beneficial_ownership_v2.dm_rollup_*` columns.
* `scripts/pipeline/shared.py:440-540` (`update_holdings_rollup`) —
  writes `beneficial_ownership_v2.dm_rollup_*`.
* `scripts/load_13f_v2.py` — DDL + INSERT (NULL placeholder) into
  `holdings_v2.dm_rollup_*`.

These would form a sister scope — see §7.4 below.

---

## 3. Writer inventory (Phase 3)

### 3.1 Writers — `fund_holdings_v2.dm_rollup_*`

[data/working/cp-5-fh2-dm-rollup-writers.csv](../../data/working/cp-5-fh2-dm-rollup-writers.csv).

| site | function | scope | source of truth | when |
| --- | --- | --- | --- | --- |
| `scripts/pipeline/load_nport.py:773` | `_promote_append_is_latest` INSERT | per-row at promote (new is_latest=TRUE rows) | values from `staging.fund_holdings_v2` (already pre-enriched in step 0) | every N-PORT promote |
| `scripts/pipeline/load_nport.py:984-1037` | `_enrich_staging_entities` (pre-promote) | all staged rows for `series_touched` in run | ERH JOIN on `entity_identifiers.identifier_type='series_id'` | every N-PORT promote, step 0 |
| `scripts/pipeline/load_nport.py:1244-1287` | `_bulk_enrich_run` (post-promote safety net) | `is_latest=TRUE` rows for `series_touched` | same ERH JOIN | every N-PORT promote, step 3 |
| `scripts/enrich_fund_holdings_v2.py:331-348` | `_apply_batch` (BLOCK-2 full-scope) | rows `WHERE entity_id IS NULL AND series_id resolvable` | same ERH JOIN | manual run only; idempotent (NULL filter) |

Out of scope (sister tables): `scripts/pipeline/shared.py:440-540`
writes `beneficial_ownership_v2.dm_rollup_*` from a parallel ERH JOIN
keyed on filer CIK.

### 3.2 Staleness mechanism — empirical confirmation

Sampled 20 fh2 rows where Method A != Method B and both `loaded_at`
and `erh.computed_at` are populated. **20 / 20 had
`erh.computed_at > fh.loaded_at`** — the row was loaded BEFORE the
ERH was rebuilt. Confirmed pattern: loader writes denorm column from
ERH at load time, ERH gets re-derived later (cp-4b-author-* brand
bridge work, MERGE PRs, future entity edits), denorm column is not
updated, so it serves stale rollup_entity_id values until the next
promote that touches the same `series_id`.

Aggregate (table-wide) — `is_latest=TRUE` rows JOINed to ERH on
entity_id, decision_maker_v1, sentinel:

| bucket | rows | % of joined |
| --- | ---: | ---: |
| total joined | 14,481,507 | 100.00% |
| Method A != Method B (diverged) | 188,005 | 1.30% |
| diverged AND `erh.computed_at > fh.loaded_at` (STALE) | 118,579 | 63.07% of diverged |
| diverged AND `erh.computed_at <= fh.loaded_at` | 36 | 0.02% of diverged |

The remaining 69,390 diverged rows have NULL `loaded_at` or NULL
`erh.computed_at` (legacy DERA-loaded rows pre-`loaded_at`-stamping;
or `entity_rollup_history` rows authored without `computed_at`).
Mechanism still applies — these are pre-stamping rows that haven't
been re-touched by a later `_bulk_enrich_run`.

### 3.3 Out-of-scope discovery — `dm_rollup_name` aliases the EC rollup, not DM

While inspecting the writers I noticed that the four fh2 writer paths
populate `dm_rollup_name` from a JOIN against
`entity_aliases.entity_id = ec.rollup_entity_id` (note: the
**economic_control** rollup, not the **decision_maker** rollup):

```sql
-- scripts/pipeline/load_nport.py:986-1001 (and three sister paths)
LEFT JOIN entity_rollup_history ec
       ON ec.entity_id = ei.entity_id
      AND ec.rollup_type = 'economic_control_v1'  -- EC
LEFT JOIN entity_rollup_history dm
       ON dm.entity_id = ei.entity_id
      AND dm.rollup_type = 'decision_maker_v1'    -- DM
LEFT JOIN entity_aliases ea
       ON ea.entity_id = ec.rollup_entity_id      -- ← joins on EC, not DM
```

Compare with `scripts/pipeline/shared.py:484-487`
(beneficial_ownership_v2 enrichment), which correctly uses
`ea_dm.entity_id = dm.rollup_entity_id`. The fh2 writers' alias-source
is inconsistent with the column name.

This is a **separate defect** (semantic mislabel of `dm_rollup_name`)
worth surfacing but **out of scope** for the drop-vs-backfill
decision. If Path 1 (drop) wins, the defect retires with the column.
If Path 2 (backfill) wins, the backfill contract should write the
correct DM alias and the drift will surface even more rows changing
on the first backfill run (the 421,011 NULL-name rows would all
populate; many already-non-NULL rows would change to a different
alias).

---

## 4. Drop-column path sizing (Phase 4)

### 4.1 Read-side perf (Method A vs Method B)

Empirical wall-clock on warm cache, single connection
(`scripts/oneoff/cp_5_fh2_dm_rollup_decision_recon_phase4.py`):

| query shape | Method A | Method B | overhead |
| --- | ---: | ---: | --- |
| Aggregate (top-25 firms, no filter) | 51.1 ms | 29.7 ms | +21.3 ms (+71.8%) |
| Single-firm filter (Vanguard 2025Q4 top-100 tickers) | 77.4 ms | 13.9 ms | +63.6 ms (+457.8%) |

Absolute overhead: **<70ms per query**, all Method A queries return
under 100ms. Single-firm filter sees the worst relative slowdown
because Method B can resolve `WHERE dm_rollup_entity_id = ?` against
DuckDB's column zonemap directly while Method A must JOIN against ERH
before filtering.

For interactive readers (Cross-Ownership, summary builders, fund
flows) this is well within the human-imperceptible band. For peer
rotation rebuilds and scheduled batch jobs it is dominated by other
costs (parse, validate, write IO).

### 4.2 Reader migration cost

From §2.2:

* 6 production touch sites in 5 files
* All are mechanically uniform: replace direct column reference with
  `entity_rollup_history`+`entity_aliases` JOIN
* No new helper required — the JOIN shape is already canonical in
  `_enrich_staging_entities` and `_bulk_enrich_run`
* CP-5.1 already plans `build_top_parent_join` helper
  (per `cp_5_bundle_c_probe7_4_readers_writers.py:115`); the
  migration here is a strict subset

Sizing: **~150 LOC, 1 PR, S–M effort.**

### 4.3 Writer retirement cost

* 3 writer sites in `scripts/pipeline/load_nport.py` (lines 773,
  984-1037, 1244-1287)
* 1 writer site in `scripts/enrich_fund_holdings_v2.py:331-348`
* All 4 sites populate the same JOIN result; retiring is straightforward:
  drop the SET clauses for `dm_rollup_entity_id` and `dm_rollup_name`,
  delete `_enrich_staging_entities`/`_bulk_enrich_run` if the only
  remaining write is for the related `entity_id`/`rollup_entity_id`
  columns (these need to stay for the int-23 downgrade-refusal guard
  and for `enrich_fund_holdings_v2.py`'s scope filter)

Sizing: **~80 LOC retirement + careful test of int-23 guard, 1 PR, S effort.**

### 4.4 Schema migration cost

* `ALTER TABLE fund_holdings_v2 DROP COLUMN dm_rollup_entity_id`
* `ALTER TABLE fund_holdings_v2 DROP COLUMN dm_rollup_name`
* DuckDB DROP COLUMN: rewrites the table row-major (~24 GB on disk
  for `fund_holdings_v2` rolled in to the global 13f.duckdb file).
  Order-of-magnitude: tens of seconds to a few minutes. Not a
  downtime-critical event since it runs against a backup-snapshot DB
  during scheduled maintenance.
* Migration script in `scripts/migrations/` following the existing
  numbered pattern (latest is `005_beneficial_ownership_entity_rollups.py`,
  so `006_fh2_drop_dm_rollup_denorm.py`)
* Rollback path: re-add columns + run `enrich_fund_holdings_v2.py
  --apply` (idempotent, ~minutes against the full table)

Sizing: **1 migration file + smoke test, 1 PR, S effort.**

### 4.5 Total scope — Path 1 (drop)

* PR-A: reader migration (queries + build_summaries + build_fixture +
  frontend comment).
* PR-B: writer retirement (load_nport + enrich_fund_holdings_v2).
* PR-C: schema migration (`scripts/migrations/006_*.py`).

**3 PRs, ~250 LOC net deletion, S–M total effort, 1–2 sessions.**
Sequencing constraint: PR-A must merge before PR-B (readers must
stop reading the column before writers stop writing it); PR-C must
merge after PR-B (column must have no remaining writes before drop).
The 3-PR shape mirrors the cp-4b carve-out arc (recent precedent).

---

## 5. Backfill-contract path sizing (Phase 5)

### 5.1 Backfill mechanism options

* **Option A — Inline call after every ERH-touching script.** Author
  a one-shot helper (e.g.
  `scripts/refresh_dm_rollup_denorm.py`) that runs the canonical
  ERH+aliases JOIN against fh2. Add a manual call to it from each
  ERH-rebuild path: `build_entities.py`, `entity_sync.py promote`,
  `bootstrap_*_advisers.py`, `admin_bp.py` override approval flow,
  cp-4b-style brand-bridge author scripts, MERGE oneoffs. Simple but
  contract relies on author discipline.
* **Option B — Trigger or post-write callback.** DuckDB supports
  triggers in 1.x but not on UPDATE/DELETE for arbitrary subqueries;
  not a real option for this shape.
* **Option C — Periodic reconciliation script.** Scheduled cron / CI
  step runs the refresh at fixed cadence (daily? weekly?). Drift
  window is bounded by cadence; misses no event but adds latency
  between ERH change and denorm catch-up.
* **Option D — Hybrid (inline trigger calls into option C as a
  safety net).** Author scripts call the refresh inline; cron runs
  reconciliation as a daily / per-deploy gate.

Realistic choice is **C or D**. Option A requires touching ~15
ERH-write sites (per [§7.4 Bundle C writer audit](./cp-5-bundle-c-discovery.md))
plus every future cp-4b-style brand-bridge PR — high
contract-enforcement risk.

### 5.2 Backfill cost per run

From `phase4.py` benchmark:

* Full-table backfill JOIN (read shape, COUNT(*) over the JOIN tree):
  **38 ms** for 14.57M rows. CPU-only, no I/O.
* Diverged-only count (rows that would actually change): **2,850,674
  rows** in **57.9 ms**. This is the upper bound on what a "smart"
  backfill (only-update-where-different) would write.

Equivalent UPDATE wall-time will be larger because of:

* Write IO per row (DuckDB column writes)
* MVCC version chain growth
* If the backfill scopes to `is_latest=TRUE`: same ~14.5M scope as a
  full refresh
* If the backfill scopes to "rows where Method B != Method A": ~2.85M
  rows

Order-of-magnitude estimate: **30 seconds to 5 minutes per full
backfill** based on prior `enrich_fund_holdings_v2.py` runtimes
(tens-of-millions-rows, single-digit minutes).

### 5.3 Backfill reliability risks

* **Race conditions.** ERH rebuild + backfill are not transactional
  together. If the ERH rebuild is mid-flight and the backfill reads
  ERH state, the result is either pre-rebuild or post-rebuild
  consistent — but only at the row level. A multi-step ERH rebuild
  (entity merge that closes one ERH row and opens another in two
  separate statements) has a window where the denorm catches an
  intermediate state. **Mitigation:** scope ERH rebuilds to a single
  transaction (already the case in cp-4b-style merges per memory).
* **Idempotency.** Same JOIN run twice produces the same output. ✓
* **Coverage decision.** Should the backfill update `is_latest=FALSE`
  rows? Per §1.3, only 3,255 rows. Cost is negligible. **Recommend
  `WHERE TRUE` (full table) for symmetry; idempotent and
  near-zero cost on the historical tail.**
* **Contract drift.** New ERH-write sites are added periodically (every
  cp-4b-style PR adds 1; bootstrap scripts each add 1). If backfill
  is the contract, every new ERH-write must call (or be covered by)
  the backfill. The current ERH writer audit lists ~15 sites; that's
  growing. Risks producing the same drift the recon documented.
* **Backfill of the parallel `dm_rollup_name` defect.** Per §3.3, the
  current writer joins `entity_aliases` on the EC rollup, not the DM
  rollup. The backfill contract would either inherit this bug (matches
  prior writer for column-stable) or fix it (changes 421K + many
  more rows on first backfill, requires explicit decision and
  user-facing diff review).

### 5.4 Total scope — Path 2 (backfill)

* PR-A: backfill helper (`scripts/refresh_dm_rollup_denorm.py` —
  full-table UPDATE with `--scope is_latest|all|diverged-only`,
  `--dry-run` default, idempotent NULL/!= guard).
* PR-B: integration — call the helper from each ERH-write path's
  post-write block, OR add a cron / scheduled job that runs daily.
* PR-C: documentation — `docs/contracts/erh-fh2-denorm-contract.md`
  describing the contract, owner, runbook, and "every new
  ERH-write must call this" rule.
* PR-D: gate — add a CI check that surfaces any fh2 row where Method
  A != Method B as a CP-5 data-quality WARN. Already foreshadowed in
  Bundle C §7.1 ("Method B has a separate role as a cache invalidation
  signal").

**4 PRs, ~400 LOC net addition (backfill helper + tests + contract
docs + CI gate), M total effort, 2–3 sessions.** Plus ongoing
maintenance burden: every future cp-4b-style PR carries a "did you
trigger the backfill?" review checklist. Plus the parallel
`dm_rollup_name` defect (§3.3) must be resolved at the same time — at
minimum surfaced in the contract as a known-deviation, ideally fixed.

---

## 6. Recommendation (Phase 6)

### 6.1 Trade-off summary

| dimension | Path 1 (drop) | Path 2 (backfill) |
| --- | --- | --- |
| Total LOC | ~250 net deletion | ~400 net addition |
| PRs | 3 | 4 |
| Sessions | 1–2 | 2–3 |
| Read-side perf | +20–65 ms per query (still <100ms) | unchanged (denorm column hit) |
| Drift risk | none (column gone) | persistent — every new ERH-write site is a contract edge |
| Contract surface | none | ~15 ERH-write sites today + every future merge/bridge |
| Schema simplicity | +2 columns retired | +2 columns retained |
| Future-proofing | clean (CP-5.1 helper-driven) | accumulating (each new ERH path needs hook) |
| Sister-table impact | clean — same retirement available for `holdings_v2` and `beneficial_ownership_v2` later | each table replicates the same contract burden |
| `dm_rollup_name` semantic defect (§3.3) | retires with the column | needs explicit fix in backfill — touches ~400K rows, requires user-visible diff review |

### 6.2 Recommendation — **Path 1 (drop column)**

Rationale:

1. **Reader-migration cost is small.** 6 sites in 5 files, all
   uniform shape. The replacement JOIN is already used canonically by
   the loader writers and Bundle C helpers; it is not new code.
2. **Read-side perf cost is acceptable.** All measured Method A
   queries land under 100ms wall-clock. The single-firm filter is
   the worst case (+457%), and the absolute number is +63ms — well
   within human-imperceptible. CP-5.1 already plans to refactor these
   readers anyway (per the bundle-c probe 7.4 inventory).
3. **Drift risk eliminated.** Path 2's contract is fragile — every
   future cp-4b-style brand-bridge or MERGE PR is a new opportunity
   to forget the backfill call. The recon already surfaces 12 firms
   with $1B–$110B drift today despite the existing
   `_bulk_enrich_run` safety net. Adding a separate backfill contract
   doubles the moving parts without removing the underlying
   "denormalization without invalidation" anti-pattern.
4. **Sister-table opportunity.** The same drift mechanism will
   eventually need to be solved for `holdings_v2` and
   `beneficial_ownership_v2`. Path 1's pattern is reusable; Path 2's
   contract triples the surface area.
5. **CP-5.1 alignment.** Method A is the canonical climb mechanism
   for CP-5.1 (locked PR #280). Path 1 finishes that lock-in by
   retiring the alternative; Path 2 keeps both alive in tension.
6. **`dm_rollup_name` semantic defect retires for free.**
   The §3.3 alias-on-EC-instead-of-DM bug needs no separate fix
   under Path 1; it disappears with the column.

### 6.3 If Path 2 wins despite the recommendation

Implementation should:

* Pick **Option C (periodic reconciliation script)** as the
  primary mechanism — a daily cron or post-deploy hook, not an
  inline call from each ERH-write site.
* Surface drift via CP-5 data-quality gate — fail if Method A vs
  Method B divergence exceeds 1% or $5B AUM. Today's state would
  fail.
* Fix the `dm_rollup_name` semantic defect in the same PR — change
  the JOIN from `ea.entity_id = ec.rollup_entity_id` to
  `ea.entity_id = dm.rollup_entity_id`, accept the ~400K row diff,
  and document the change in release notes.

### 6.4 If Path 3 (cache view / materialized view) is considered

Not recommended:

* DuckDB does not support traditional materialized views with
  refresh contracts; a regular `VIEW` would just be Method A under a
  different name (no perf benefit). A `CREATE TABLE AS` snapshot
  would inherit Path 2's drift risk.
* Path 3 reverses to Path 2's mechanism with extra schema; no
  meaningful win.

---

## 7. Open questions for chat decision

### 7.1 Path lock — Path 1 (drop) / Path 2 (backfill) / Path 3 (cache view)

This recon recommends **Path 1**. Chat to lock.

### 7.2 Migration sequencing relative to CP-5.1

If Path 1: should the 3-PR arc precede CP-5.1, ride alongside, or
follow? Recommendation: **precede CP-5.1**. PR-A's reader migration
is a natural prerequisite for CP-5.1's `build_top_parent_join` helper
(per Bundle C probe 7.4 reader inventory). PR-B and PR-C can ride
during or after CP-5.1.

If Path 2: can run parallel to CP-5.1 — the column stays and the
reader pattern is unchanged.

### 7.3 Sister-table treatment

Should `holdings_v2.dm_rollup_*` and `beneficial_ownership_v2.dm_rollup_*`
follow the same path as fh2? They share the same drift mechanism.
Recommendation: **same path, separate PR cohorts** (each table has
its own writer/reader fan-out; combining would balloon scope).
Out of CP-5.1 critical path either way. Surface as
`cp-5-h2-dm-rollup-decision` and `cp-5-bo2-dm-rollup-decision` in
the post-CP-5 backlog.

### 7.4 Whether to fix the `dm_rollup_name` semantic defect (§3.3) independently

Currently the column "dm_rollup_name" is populated with the
**economic_control** rollup's preferred alias, not the
**decision_maker** rollup's. If Path 1 wins, the question is moot.
If Path 2 wins, the defect must be addressed in the same PR or
explicitly deferred.

---

## 8. Out-of-scope discoveries

1. **`dm_rollup_name` writer joins on EC rollup, not DM rollup**
   (§3.3) — semantic defect on the column being analyzed. Not a
   drift issue, a different bug. Important to surface for Path 2's
   PR review.
2. **fh2 SCD model is barely exercised** (§1.3) — only 3,255
   `is_latest=FALSE` rows in 14.57M total. The SCD apparatus
   (is_latest, accession_number, row_id) is mostly inactive on this
   table.
3. **`dm_rollup_entity_id` populated rate is 99.42%** (§1.1) —
   higher than fh2's `entity_id` populated rate (last reported
   ~85% in [SYSTEM_AUDIT_2026_04_17.md](../SYSTEM_AUDIT_2026_04_17.md)
   §10.1, but `enrich_fund_holdings_v2.py` BLOCK-2 work since then
   has likely closed most of the gap). Worth reconciling the two
   metrics in a follow-up.
4. **Sister-table parallel pattern.** The same denormalize-from-ERH
   pattern is encoded into `holdings_v2.dm_rollup_*` and
   `beneficial_ownership_v2.dm_rollup_*`. Sister tables share the
   same drift mechanism and will eventually need the same decision.

---

## 9. Artifacts

* [data/working/cp-5-fh2-dm-rollup-drift.csv](../../data/working/cp-5-fh2-dm-rollup-drift.csv) — top 50 top-parents, Method A vs Method B
* [data/working/cp-5-fh2-dm-rollup-readers.csv](../../data/working/cp-5-fh2-dm-rollup-readers.csv) — every (file, line) hit for `dm_rollup_entity_id` and `dm_rollup_name`
* [data/working/cp-5-fh2-dm-rollup-writers.csv](../../data/working/cp-5-fh2-dm-rollup-writers.csv) — writer inventory with scope + source-of-truth + when-runs
* `scripts/oneoff/cp_5_fh2_dm_rollup_decision_recon_phase1.py` — column footprint + drift quantification
* `scripts/oneoff/cp_5_fh2_dm_rollup_decision_recon_phase2.py` — reader inventory grep+classify
* `scripts/oneoff/cp_5_fh2_dm_rollup_decision_recon_phase3.py` — writer inventory + staleness mechanism characterization
* `scripts/oneoff/cp_5_fh2_dm_rollup_decision_recon_phase4.py` — Method A vs Method B perf benchmarks + backfill cost simulation
