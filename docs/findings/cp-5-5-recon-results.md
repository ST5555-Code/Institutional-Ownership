# CP-5.5 recon — Sector Rotation + New-Exits + AUM + Activist scoping

**Branch:** cp-5-5-recon
**Base:** main @ 1c98658 (PR #304 — `cp-5-bundle-c-api-files-extension`)
**Mode:** read-only investigation — no DB writes
**Pytest baseline:** 444 passed, 6 skipped (unchanged)

Drives chat-side decision on CP-5.5 PR shape (single bundled PR vs split with
deferrals vs multi-PR carve-out) per Bundle C §7.4 and the §4.5 outline in
`docs/findings/cp-5-comprehensive-remediation.md`.

Binder-ambiguity rule (PR #303 §6.4) baked in: every site without a
`FROM <table>, <cte>` cross-join shape can use either alias or noalias variant
of `top_parent_canonical_name_sql()`; sites with cross-join shape default to
alias variant. Recon flag column `binder_risk_flag` records the result per
site.

---

## 1. Phase 1 cohort load

### 1.1 9 PENDING_CP5_5 sites confirmed

`scripts/oneoff/cp_5_5_load_cohort.py` re-reads the extended inventory
(`data/working/cp-5-bundle-c-readers-extended.csv`) and confirms 9 rows
tagged `PENDING_CP5_5`. No cohort drift since PR #304.

### 1.2 Per-feature distribution (CSV labels)

| CSV feature label | Count |
|---|---|
| Sector flow movers | 1 |
| Flows entry+peer | 1 |
| Flows cohort by manager_type | 1 |
| Flows ownership trend | 1 |
| Flows peer rotation | 1 |
| Trend holder momentum | 1 |
| Trend distinct holders | 1 |
| Entity AUM subtree | 1 |
| Rollup-join helper | 1 |

### 1.3 Mapping to prompt's 4-feature scope

The prompt frames CP-5.5 as four features: Sector Rotation, New-Exits, AUM,
Activist. The CSV's actual labels split differently:

| Prompt feature | Sites | CSV labels |
|---|---|---|
| Sector Rotation | 2 | Sector flow movers (S1), Flows peer rotation (S5) |
| New-Exits / Flows | 3 | Flows entry+peer (S2), Flows cohort (S3), Flows ownership trend (S4) |
| AUM | 1 | Entity AUM subtree (S8) |
| Activist | 0 | — no dedicated site |
| (out-of-scope vs prompt) | 2 | Trend holder momentum (S6), Trend distinct holders (S7) |
| (helper layer) | 1 | Rollup-join helper (S9) |

**Open question Q1:** Activist has no dedicated reader site in the cohort.
Activist filtering is layered into S1 / S5 / similar via
`entity_type IN ('active', 'hedge_fund', 'activist')` predicates on the
precomputed table — handled implicitly by the precompute's existing
`entity_type` column. No standalone activist site needs migrating in CP-5.5.
Confirm with chat that this matches the intended Bundle C §7.4 scope; if not,
the activist scope target may already be covered by precompute layer (and
therefore lands in CP-5.5b precompute-rebuild sub-arc rather than CP-5.5
main).

---

## 2. Phase 2 site-level discovery

Full per-site classification: `data/working/cp-5-5-reader-inventory.csv`.

### 2.1 Per-site classification summary

| Site | File:line | Function | Class | Notes |
|---|---|---|---|---|
| S1 | market.py:316 | get_sector_flow_movers | BLOCKED_FLOWS_PRECOMPUTE | parent path reads peer_rotation_flows.entity column |
| S2 | flows.py:457 | flow_analysis | PARTIAL | live path CLEAN; precomputed path BLOCKED |
| S3 | flows.py:189 | cohort_analysis | CLEAN | name-coalesce → top_parent_canonical_name_sql |
| S4 | flows.py:506 | (flow_analysis investor_flows read) | BLOCKED_FLOWS_PRECOMPUTE | inner read of S2; subsumed |
| S5 | trend.py:649 | get_peer_rotation_detail | BLOCKED_FLOWS_PRECOMPUTE | CSV path drift — actually trend.py not flows.py |
| S6 | trend.py:31 | holder_momentum | CLEAN | parent_name + rollup_eid passthrough |
| S7 | trend.py:325 | ownership_trend_summary | CLEAN | COUNT(DISTINCT COALESCE(...)) inside aggregate |
| S8 | entities.py:119 | compute_aum_for_subtree | OTHER_VIEW_SWAP | CIK-set filter on holdings_v2; not name-coalesce |
| S9 | queries_helpers.py:116 | rollup_join | HELPER_REFACTOR | helper layer, not reader site |

### 2.2 BINDER_RISK sites flagged

**None.** No site in the cohort uses `FROM <table>, <cte>` cross-join shape.
Most sites use single-table `FROM holdings_v2` (with optional alias) or
`FROM peer_rotation_flows` / `FROM investor_flows` (single-table precompute
read). Subqueries appear inside WHERE clauses or as CTEs joined via explicit
`JOIN ... ON` (not comma-join).

The standing PR #303 §6.4 finding does not block any CP-5.5 site, but the
execute prompt should still default to the alias variant of
`top_parent_canonical_name_sql('h')` for consistency with CP-5.2 / CP-5.3 /
CP-5.4 precedent. Sites without an existing alias on the holdings table
(e.g., S7) require adding alias `h` as part of the migration.

### 2.3 BLOCKED sites by class with routing

**BLOCKED_FLOWS_PRECOMPUTE** (3 sites: S1, S4, S5; S2 partial):
- Root cause: `peer_rotation_flows.entity` and `investor_flows.inst_parent_name`
  are pre-aggregated by canonical-name string, not by `top_parent_entity_id`.
  Reader-side migration would require the precomputed tables to expose a
  `top_parent_entity_id` column (or equivalent stable key) and the readers
  to GROUP BY that key instead of the name string.
- Required upstream work:
  - `scripts/compute_peer_rotation.py` — rebuild keyed by tp_eid
  - `scripts/compute_flows.py` — rebuild keyed by tp_eid (investor_flows +
    shares_history derivatives)
  - Migration adding `top_parent_entity_id` columns to both precompute
    tables; backfill on production DB
- Routing: **CP-5.5b precompute-rebuild sub-arc** (separate PR sequence)

**OTHER_VIEW_SWAP** (1 site: S8):
- Root cause: `compute_aum_for_subtree` joins a CIK-set CTE to
  `holdings_v2 h WHERE h.cik IN (...)`. The migration class isn't the
  name-coalesce → `top_parent_canonical_name_sql` swap that defines CP-5.2
  through CP-5.4. Instead it would swap the holdings target to
  `unified_holdings` (R5 view) for live-quarter AUM consistency with the
  rest of the entity-graph reader path.
- Risk: low — `unified_holdings` view already covers parent-tier `holdings_v2`
  with `is_latest=TRUE` semantics absorbed (per CP-5.2 PR #300). Migration
  is a one-line `FROM holdings_v2 h` → `FROM unified_holdings h` swap plus
  removing redundant `is_latest = TRUE` predicate.
- Routing: **CP-5.5 main** if scope tight enough; otherwise own small PR.
  Recommend folding in.

### 2.4 Per-feature deep dive

#### Sector Rotation (2 sites — S1, S5)

Both sites read the `peer_rotation_flows` precompute table directly. The
rebuild dependency is a single upstream change (`compute_peer_rotation.py`)
that benefits both. Defer together to CP-5.5b.

Fund path of S1 (`get_sector_flow_movers` level='fund') uses
`COALESCE(family_name, fund_name)` on `fund_holdings_v2` — this is a fund-
tier identification pattern unrelated to the parent-tier rollup migration
and is left unchanged.

#### New-Exits / Flows (3 sites — S2, S3, S4)

Mixed cohort:

- **S3 (cohort_analysis)** — purely live (no precompute path). Uses
  `COALESCE(rn, inst_parent_name, manager_name) AS investor`. CLEAN — direct
  swap to `top_parent_canonical_name_sql('h')` with alias added.
  Multi-quarter loop iterates `QUARTERS` with separate executes per QoQ
  transition for `econ_retention_trend`; no LAG/LEAD shape. Each query is
  independently CLEAN.

- **S2 (flow_analysis)** — split. Live fallback `_compute_flows_live` (at
  flows.py:316) is CLEAN. Precomputed `investor_flows` read at flows.py:506+
  is BLOCKED on rebuild. Recommended: ship live-path swap in CP-5.5 main;
  defer precomputed-path swap to CP-5.5b (which lands once `investor_flows`
  has the `top_parent_entity_id` column).

- **S4** — inner precompute read inside `flow_analysis`. Practically
  subsumed by S2; listed as separate site by CSV labelling. Routes to
  CP-5.5b together with S2's precomputed half.

#### AUM (1 site — S8)

`compute_aum_for_subtree` is a different migration class than CP-5.2-5.4
(see §2.3 OTHER_VIEW_SWAP). Recommend folding into CP-5.5 main as a small
parallel change — surface is one `FROM` swap in a recursive-CTE block.

If chat decides CP-5.5 main should remain strictly name-coalesce-themed,
spin S8 off as its own micro-PR (`cp-5-aum-subtree-unified-holdings-swap`).

#### Activist (0 dedicated sites)

No dedicated reader site. Activist filtering is a row-level predicate on
the precompute layer's `entity_type` column. If chat agrees, treat
"activist" coverage as implicit in the CP-5.5b precompute rebuild and close
the activist scope without a separate workstream.

---

## 3. Phase 3 PR shape recommendation

### 3.1 Recommended split — Option B with explicit deferrals

Ship in CP-5.5 main:
- **S3** cohort_analysis — name-coalesce swap
- **S6** holder_momentum — name-coalesce swap (parent_name) + rollup_eid
  passthrough preserved
- **S7** ownership_trend_summary — alias add + name-coalesce swap inside
  COUNT(DISTINCT)
- **S2 live half** flow_analysis._compute_flows_live — name-coalesce swap
- **S8** compute_aum_for_subtree — `FROM unified_holdings` swap (small,
  parallel change; recommend fold-in)
- **S9** rollup_join helper — only if `build_top_parent_join` sibling helper
  is in fact needed by the migration. Recon's read: existing
  `top_parent_canonical_name_sql` already covers the climb shape for all
  CP-5.5 main sites without requiring a new JOIN-fragment helper. **Defer
  S9 unless concrete consumer surfaces during execution.**

Defer to CP-5.5b precompute-rebuild sub-arc:
- **S1** get_sector_flow_movers (parent path)
- **S2 precomputed half** (flow_analysis.investor_flows read)
- **S4** investor_flows read (subsumed by S2)
- **S5** get_peer_rotation_detail

CP-5.5b workstream sketch:
1. Migration adding `top_parent_entity_id` to `peer_rotation_flows` and
   `investor_flows`
2. `scripts/compute_peer_rotation.py` rebuild keyed by tp_eid (+ backfill)
3. `scripts/compute_flows.py` rebuild keyed by tp_eid (+ backfill)
4. 4 reader-site swaps (S1, S2-precomputed, S4, S5)
5. Parity validation — pre/post sums on a fixed cohort

Activist scope (per §2.4 deep-dive): closes implicitly with CP-5.5b
precompute rebuild via existing `entity_type` column.

### 3.2 Execute prompt sketch (CP-5.5 main)

Phases:
- **Phase 1** — reader manifest by feature (5-6 CLEAN sites listed
  explicitly with file:line + before/after SQL fragment)
- **Phase 2** — migration application (alias variant uniformly per binder
  rule, even though no site is binder-risk, for consistency precedent)
- **Phase 3** — validation
  - All 5-6 sites: pre/post `unified_holdings`-aware tests confirming row
    counts and aggregate sums equal within 1e-6
  - S8: AUM subtree test on a known entity (e.g., Vanguard rollup) pre/post
    swap returns same float to 1e-6
  - S6 / S7: multi-quarter coverage — confirm holder_count and
    `change_pct` per-quarter values unchanged
- **Phase 4** — pytest 444 → expected ~448-452 (4-8 new tests for the new
  validation cases)

### 3.3 Test growth estimate

Baseline: 444 passing. CP-5.5 main estimated +6 tests:
- 1 per CLEAN site for name-coalesce swap parity (S2 live, S3, S6, S7)
- 1 for S8 unified_holdings swap parity
- 1 for multi-quarter holder_momentum coverage

Expected post-merge: 450 passing. CP-5.5b adds ~4-6 more tests per site
(precompute-keyed-by-tp_eid parity); estimated 454-460 after CP-5.5b
lands.

---

## 4. Open questions for chat

- **Q1** — Activist scope: confirm "no dedicated reader site" mapping is
  intended per Bundle C §7.4. If chat expected an activist-named site,
  surface it (recon found none).
- **Q2** — S8 routing: fold into CP-5.5 main (recon recommendation) or
  spin off as own micro-PR to keep CP-5.5 main strictly name-coalesce
  themed.
- **Q3** — S9 inclusion: defer (recon recommendation) or land
  `build_top_parent_join` helper proactively to set up CP-5.6 (Tier-3
  sentinel) consumers?
- **Q4** — CP-5.5b sequencing: precompute-rebuild before or after CP-5.6
  (View 2 Tier-3 sentinel)? CP-5.6 likely doesn't depend on precompute
  rebuild, so they can run in parallel.

---

## 5. Out-of-scope discoveries / surprises

- **CSV path drift on S5** — `cp-5-bundle-c-readers-extended.csv` records
  `flows.py:600-625 peer_rotation_detail`, but the function
  (`get_peer_rotation_detail`) lives in `trend.py:649`. CSV file path is
  wrong. Suggest a follow-up doc fix in conv-31-doc-sync to correct the
  inventory row; not blocking for CP-5.5 since recon resolves the actual
  file:line.
- **CSV stale line numbers across cohort** — most other rows also have
  approximate line numbers (e.g., `flow_analysis` listed as flows.py:240-285
  but defined at flows.py:457). Function names resolved authoritatively;
  line-number column is illustrative not canonical.
- **BlackRock brand-vs-filer double-count expected on AUM panels** (S8) —
  out-of-scope for CP-5.5 because compute_aum_for_subtree walks
  `entity_relationships` excluding `sub_adviser` only, so brand-tier double
  counts would reflect any existing parent_bridge edges that introduce both
  the brand eid and filer eid into the subtree.
- **CV3 NPORT bridge regex** — applies to fund-tier paths only, none of the
  CP-5.5 sites use the CV3 bridge directly.
- **PR #303 §6.4 binder rule** — does not block any CP-5.5 site (no cross-
  join FROM shape encountered); execute prompt still defaults to alias
  variant for precedent consistency.
