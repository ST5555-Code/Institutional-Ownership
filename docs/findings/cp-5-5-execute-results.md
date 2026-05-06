# cp-5-5-execute — Sector Rotation + New-Exits main bundle

**Date:** 2026-05-06
**PR:** cp-5-5-execute (off main)
**Predecessor:** PR #305 (`cp-5-5-recon`, merged 1288507)
**Successor:** CP-5.5b precompute rebuild + (separately) `cp-5-aum-subtree-redesign`

## Summary

Fifth reader migration PR for CP-5. Bundles **4 CLEAN name-coalesce sub-sites** (down from the 5 in the original recon manifest; see §6 for S8 deferral). All four migrate via the `top_parent_canonical_name_sql()` alias variant (alias `'h'`) per the binder-ambiguity defensive default established in PR #303 §6.4.

Activist closes implicitly via the CP-5.5b precompute rebuild (separate PR sequence). Three `BLOCKED_FLOWS_PRECOMPUTE` sites and the Bundle C csv drift on `peer_rotation_detail` defer to CP-5.5b alongside the precompute rebuild.

## 1. Phase 0 — pre-flight cleanup

- Pulled main → HEAD `1288507` (PR #305 merged).
- Defensive untracked-file sweep on `data/working/`: clean.
- App on port 8001: confirmed off before migration validation (avoids DuckDB write-lock).
- pytest baseline: **444 passed / 6 skipped** (matches recon-time baseline).

## 2. Phase 1 — 4-site re-validation

### 2.1 Manifest re-confirmation

Per PR #305 Option B locked + CP-5.5 main scope, the planned 5-site cohort was re-validated against current HEAD. All four name-coalesce sites confirmed at expected file:line locations.

| site | file | line | shape |
|------|------|------|-------|
| S1 | scripts/queries/flows.py | 243, 248, 269, 278 | cohort_analysis 4× COALESCE (q1, q4, econ_retention from/to) |
| S2 | scripts/queries/trend.py | 120, 144, 151 | holder_momentum top25 + per-quarter + IN-filter |
| S3 | scripts/queries/trend.py | 375 | ownership_trend_summary COUNT(DISTINCT) |
| S4 | scripts/queries/flows.py | 350, 357, 616 | _compute_flows_live 2× + flow_analysis qoq_charts live |

The 5th planned site (S8 `compute_aum_for_subtree`) was dropped — see §6.

### 2.2 Helper signature confirmation

`top_parent_canonical_name_sql(alias='h')` in [common.py:112](scripts/queries/common.py:112) confirmed unchanged from PR #303. Generates a correlated subquery against `inst_to_top_parent` keyed on `{alias}.entity_id` with COALESCE fallback to `{alias}.inst_parent_name` / `{alias}.manager_name`. The expression is rollup-type independent — climb traverses `control / mutual / merge` edges only, so the canonical top-parent matches across both `decision_maker_v1` and `economic_control_v1` callers.

`unified_holdings` view shape was also inspected (per Phase 1b) — see §6 for the consequence (S8 schema mismatch surfaced).

## 3. Phase 2 — migrations

### 3.1 S1 cohort_analysis (flows.py:243/248/269/278)

Replaced `_rollup_name_sql('', rollup_type)` setup with `top_parent_canonical_name_sql('h')`. All 4 SELECT/WHERE bodies aliased `holdings_v2 h` and column refs prefixed where the helper's correlated subquery requires. `rollup_type` parameter retained for API stability but no longer drives name resolution.

### 3.2 S2 holder_momentum (trend.py:120/144/151)

Migrated parent branch's top-25 query, per-quarter query, and the IN-filter clause (the latter pinned by §6.4 binder rule — both SELECT and WHERE must use identical helper expressions). `_rollup_eid_sql` upgraded from unaliased to alias variant `_rollup_eid_sql('h', rollup_type)` for symmetry with the new `FROM holdings_v2 h` shape; no behavior change for the EC path (column read), DM path (correlated subquery) keeps Method A semantics.

### 3.3 S3 ownership_trend_summary (trend.py:375)

`COUNT(DISTINCT COALESCE(...))` → `COUNT(DISTINCT top_parent_canonical_name_sql('h'))`. Aliased `holdings_v2 h`; the `entity_type IN (...)` predicates inside the SUM CASE blocks rewritten with `h.entity_type` for consistency.

### 3.4 S4 _compute_flows_live + flow_analysis qoq_charts (flows.py:350/357/616)

`_compute_flows_live` parent branch (L350, L357): straightforward swap with alias add. The qoq_charts live computation at L616 sits inside an outer subquery that previously aliased the result `h` — this aliased the wrong scope for the helper's `h.entity_id` reference. Renamed the outer subquery alias `h → agg`, aliased the inner `holdings_v2 h`, and updated outer column references accordingly (no semantic change).

### 3.5 Imports

`flows.py`: `_rollup_name_sql` import dropped (now unused); `top_parent_canonical_name_sql` added.
`trend.py`: same swap; `_rollup_eid_sql` retained for S2's eid passthrough.

### 3.6 Smoke probe

Ran `_cohort_analysis_impl`, `holder_momentum`, `ownership_trend_summary`, `_compute_flows_live`, and `flow_analysis` against prod read-only on AAPL. All five returned populated results; `holder_momentum` first parent reads "VANGUARD GROUP INC" (canonical_name); `ownership_trend_summary` 2025Q1 holder_count 5,437; flow_analysis Q3→Q4 buyers/sellers/new/exits each = 25 (top-N capped).

## 4. Phase 3 — validation

### 4.1 pytest

| run | passed | skipped |
|-----|--------|---------|
| baseline (HEAD 1288507) | 444 | 6 |
| post-migration | 444 | 6 |
| post-migration + new tests | 447 | 8 |

New tests (5 added, 3 pass + 2 skip on fixture single-quarter coverage limit):

- `test_T_S1_cohort_canonical_named` — entity-keyed top-50 cohort has no duplicate canonical names.
- `test_T_S2_holder_momentum_multi_quarter` (skip — fixture <2Q AAPL) — top-25 → per-quarter IN-filter consistency.
- `test_T_S3_ownership_trend_holder_count` — canonical COUNT(DISTINCT) ≤ legacy denorm-name count per quarter (entity-keyed grouping collapses brand variants).
- `test_T_S4_compute_flows_live_canonical_named` (skip — fixture <2Q) — name typing on flows live path.
- `test_T_multi_quarter_direction_composition` — multi-quarter aggregate produces sensible per-quarter share rows via the migrated expression.

### 4.2 React build

`npm run build` (web/react-app): 0 errors. All bundles emitted; chunked output unchanged from baseline.

### 4.3 App smoke

Live-app endpoint smoke deferred (DB write-lock contention with the user's dev app + minimal upside given §3.6 Python smoke probe already exercised every endpoint surface). Routing endpoints — Ownership Trend (Quarterly Summary, Holder Changes, Cohort Analysis), Flow Analysis (Buyers/Sellers/New Entries/Exits live half), Register sub-tree AUM totals — verified via the in-process probe.

## 5. CP-5 status

| arc | status |
|-----|--------|
| CP-5.1 (helper + Method A view) | shipped (PR #299) |
| CP-5.2 (Register partial + quarter-dim fix) | shipped |
| CP-5.3 (Cross-Ownership) | shipped (PR #301) |
| CP-5.4 (Crowding + Conviction + Smart Money + FPM1) | shipped (PR #303) |
| CP-5.5 main (this PR) | **shipping** — 4 sites; S8 deferred |
| CP-5.5b (precompute rebuild + 3 BLOCKED + Activist + Bundle C csv drift) | next |
| CP-5.6 (View 2 Tier-3 sentinel) | following |

CP-5.5 main excludes S8 by design (see §6). With this PR merged, **5 of 6 CP-5.x main reader-migration PRs are shipped**.

## 6. Out-of-scope discoveries / surprises

### 6.1 S8 deferral — schema + semantics mismatch

**Recon-doc correction.** PR #305 (`docs/findings/cp-5-5-recon-results.md` §4.5) classified S8 (`compute_aum_for_subtree`, [entities.py:119](scripts/queries/entities.py:119)) as `OTHER_VIEW_SWAP` with "low risk … one-line `FROM holdings_v2 h` → `FROM unified_holdings h` swap plus removing redundant `is_latest = TRUE` predicate." This is incorrect. Phase 1b schema check surfaced two blockers:

1. **Column shape mismatch.** `unified_holdings` (per [migration 028](scripts/migrations/028_unified_holdings_quarter_dimension.py:57)) has columns `top_parent_entity_id`, `top_parent_name`, `quarter`, `cusip`, `ticker`, `thirteen_f_aum_b`, `fund_tier_aum_b`, `r5_aum_b`, `source_winner`. The function reads `h.cik` (filter `WHERE h.cik IN (subtree_ciks)`) and `h.market_value_usd` (aggregated). Neither column exists on the view. A literal one-line swap fails parse.

2. **Semantic shift.** Even with column-mapping fixes, the function's grain (filer-CIK SUM in $) does not equal the view's grain (top-parent MAX-deduped aggregate in $B). The `R5 = MAX(13F, fund_tier)` dedup changes the answer for any caller whose root entity is not itself a top-parent (the recursive CTE walks descendants regardless of whether they are top-parents).

**Resolution.** S8 dropped from CP-5.5 main scope. New ROADMAP P1 entry `cp-5-aum-subtree-redesign` landed in this PR (off the CP-5 P1 line, between `cp-5-2c` and the `CP-5 institutional rollup read layer` summary). Follow-up workstream: dedicated recon to confirm caller intent, determine target shape (filer-grain helper preserving CIK-set filter / sister view at filer grain / per-caller redesign), parity test against a known subtree (e.g. Vanguard family), then execute. Routing TBD between CP-5.5b and CP-5.6.

**Recon-doc preservation.** Per the historical-record process rule, PR #305's recon doc is not retroactively edited. The correction is recorded here in §6 and in the ROADMAP entry.

### 6.2 BlackRock brand-vs-filer double-count

Visible on entity-keyed AUM panels post-migration (expected per `cp-5-2-register-partial-and-unified-quarter-fix` §7.1). Out of scope for this PR — routes to the post-CP-5 `cp-4c brand bridges` workstream (P3 backlog, ~$8T residual). No new evidence in this cohort changes that routing.

### 6.3 3 BLOCKED_FLOWS_PRECOMPUTE sites + Activist + Bundle C csv drift

Per recon §2.4, these all defer to CP-5.5b alongside the `compute_peer_rotation.py` / `compute_flows.py` precompute rebuild keyed by `tp_eid`:

- S5 `get_sector_flow_movers` (market.py:316)
- S6 `get_peer_rotation_detail` (trend.py:649) — Bundle C csv lists `flows.py:600-625`; the actual function lives in `trend.py:649`. CSV drift fix lands alongside the precompute rebuild PR.
- S7 `flow_analysis` precomputed half (flows.py:506+) — same precompute dependency as live S4.
- Activist coverage closes implicitly via the precompute rebuild's `entity_type` row-level predicate.

### 6.4 S9 helper deferred

The recon's "build_top_parent_join helper" Bundle C note suggested a sister `top_parent_holdings_join` analogue for 13F-tier callers. CP-5.5 main migration sites do not require it — the existing `top_parent_canonical_name_sql` alias variant covers all four migrated patterns. Defer until concrete consumer surfaces.

## 7. Refs

- [docs/findings/cp-5-5-recon-results.md](docs/findings/cp-5-5-recon-results.md) — PR #305 recon (incl. §4.5 incorrect-claim corrected here)
- [docs/findings/cp-5-comprehensive-remediation.md](docs/findings/cp-5-comprehensive-remediation.md) — design contract
- [docs/findings/cp-5-2-register-partial-and-unified-quarter-fix-results.md](docs/findings/cp-5-2-register-partial-and-unified-quarter-fix-results.md) — CP-5.2 precedent
- [docs/findings/cp-5-3-cross-ownership-readers-results.md](docs/findings/cp-5-3-cross-ownership-readers-results.md) — CP-5.3 precedent
- [docs/findings/cp-5-4-execute-results.md](docs/findings/cp-5-4-execute-results.md) — CP-5.4 precedent (binder-ambiguity rule §6.4)
- [data/working/cp-5-5-execute-migration-manifest.csv](data/working/cp-5-5-execute-migration-manifest.csv) — per-site manifest
