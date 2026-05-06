# cp-5-2-register-partial-and-unified-quarter-fix — results

PR scope (narrowed from original CP-5.2 framing per chat decision
2026-05-06): migration 028 quarter-dimension fix on
`unified_holdings` + 4 of 7 Register reader sites migrated to entity-
keyed canonical-name grouping. The remaining 3 sites surface chat-
side architectural blockers and route to follow-up PRs.

Predecessors: PR #299 (`cp-5-1b-helper-and-view`) which shipped the
foundation views without a quarter dimension and without reader
migrations.

## 1. Phase 1 discovery

### 1.1 unified_holdings + inst_to_top_parent state (pre-028)

`DESCRIBE unified_holdings` against prod returned 8 columns:
`top_parent_entity_id`, `top_parent_name`, `cusip`, `ticker`,
`thirteen_f_aum_b`, `fund_tier_aum_b`, `r5_aum_b`, `source_winner`.
No `quarter` column.

`DESCRIBE inst_to_top_parent` returned 3 columns: `entity_id`,
`top_parent_entity_id`, `hops_at_top`. Used as-is — climb shape is
quarter-independent.

Pre-migration view rowcount: 5,174,248.

### 1.2 Register 7-site reader inventory

Re-confirmed against current HEAD by grepping `register.py` for
`rollup_name | inst_parent_name | rollup_entity_id | dm_rollup`.
The Bundle C §7.4 7-site count is intact. Function names map to
current line numbers as follows (the Bundle C CSV's snapshotted line
numbers are stale):

| feature                  | function              | scope            |
|--------------------------|-----------------------|------------------|
| Register top-25          | query1 (line 39)      | clean            |
| Register N-PORT cov      | query1 sub-block      | **deferred** (Q7)|
| Register holders         | query2 (line 268)     | clean            |
| Register active/passive  | query3/4/5 (447, 740, 773) | **deferred** |
| Register flows           | query12 (line 1086)   | clean            |
| Register drill           | query14 (line 1117)   | **deferred** (Q7)|
| Register manager AUM     | query16 (line 1192)   | no-op (fund-tier)|

Output: [data/working/cp-5-2-register-reader-inventory.csv](../../data/working/cp-5-2-register-reader-inventory.csv).

### 1.3 Quarter dimension confirmation

Plan asserted `is_latest = TRUE` would pin to a single quarter.
**Confirmed false.** Probe against prod:

| table              | distinct quarters | range            |
|--------------------|------------------:|------------------|
| holdings_v2 (latest)|                4 | 2025Q1..2025Q4   |
| fund_holdings_v2 (latest)|          16 | 2022Q2..2026Q1   |

`is_latest` is per-series most-recent, not global most-recent.
PR #299's view collapsed across these multi-quarter sets, inflating
top-N AUM for any reader that needed single-quarter state. The
quarter-dimension fix in this PR is the corrective.

Output: [data/working/cp-5-2-quarter-dimension-confirmation.csv](../../data/working/cp-5-2-quarter-dimension-confirmation.csv).

## 2. Phase 2 view revision (migration 028)

### 2.1 Migration 028 DDL

`CREATE OR REPLACE VIEW unified_holdings` adding `quarter` to the
grain. Both `thirteen_f_leg` and `fund_tier_leg` group by quarter;
the `FULL OUTER JOIN` matches on quarter as well as
top_parent_entity_id, cusip, ticker.

Idempotent. Forward-only. Zero row mutations. View-only — rollback is
re-applying migration 027.

### 2.2 Guards passed (prod)

```
G1 quarter column present:              True
G2 distinct quarters in view:           16
G2 distinct quarters in holdings_v2:    4
G3 unified_holdings rows (post):        13,204,508
G4 Capital Group arms -> umbrella 12:   3 of 3
G5 Vanguard/AAPL rows visible:          6
```

Rowcount expanded 5.17M → 13.20M as expected — fund-tier leg
contributes 16 quarters of per-quarter rows where the prior view
collapsed them all into one. The expansion is grain-shape, not
double-counting.

### 2.3 PR #299 invariants preserved

- Capital Group umbrella eid 12 attracts 3 wholly_owned arms (G4).
- Method A canonical climb path unchanged.
- `r5_aum_b = GREATEST(thirteen_f_aum_b, fund_tier_aum_b)` semantics
  unchanged (per-quarter now).
- `source_winner` semantics unchanged.

## 3. Phase 3 reader migrations (4 sites)

### 3.1 Helper

Added `top_parent_canonical_name_sql(alias)` to
[scripts/queries/common.py](../../scripts/queries/common.py).
Correlated subquery that climbs `inst_to_top_parent` from
`{alias}.entity_id` and resolves `entities.canonical_name`. Wrapped
in `COALESCE(...,inst_parent_name, manager_name)` so rows whose
`entity_id` has no climb (rare in prod, common in fixture / edge
cases) degrade to legacy denorm columns rather than NULL — the API
boundary requires non-NULL `institution`.

### 3.2 query1 (Register top-25)

5 sub-sites within the function migrated to `top_parent_canonical_name_sql`:

1. Parents top-25 (lines 50–80): canonical-name grouping for the
   ranked-25 result set.
2. AUM fallback (lines 95–104): same expression so the IN-filter
   keys match step 1's parent_names.
3. 13F children fetch (lines 130–148): same expression so
   children-by-parent join is consistent.
4. all_totals (lines 245–256): same expression for the all-investor
   beyond-top-25 totals.

**Not migrated within query1**: the N-PORT coverage block
(lines 117–129) still reads `summary_by_parent` keyed on legacy
`inst_parent_name`. This is **best-effort enrichment** wrapped in
try/except — silent miss for parents whose canonical climb-name
diverges from the loader-time `inst_parent_name`. Tracked as
[cp-5-2a-summary-by-parent-rebuild](#cp-5-2a) (Q7).

### 3.3 query2 (4-quarter ownership change)

Top_parents pick (lines 282–292) and `q1_agg`/`q4_agg` CTEs
(lines 294–311) all migrated to `top_parent_canonical_name_sql`. The
`FULL OUTER JOIN` on `cik + manager_name` is unchanged; canonical
parent_name is a derived column and doesn't affect join correctness.

### 3.4 query12 (concentration analysis)

Full rewrite. Cleanest demonstration of the migration pattern —
single SQL block, single grouping expression, no enrichment
sidecars. Returns canonical entity-keyed top-20 holders by
cumulative pct_so.

### 3.5 query16 (fund-level register)

**No-op confirmation.** query16 reads `fund_holdings_v2` directly
ranked by `fh.fund_name` / `fh.series_id`. It does not use the
institutional `COALESCE(rollup_name, inst_parent_name, manager_name)`
pattern. Already entity-canonical via fund_name / series_id. Listed
in chat-decided 4-site scope as a no-op confirmation only; left
untouched. Migration plan's CSV labelled it "Register manager AUM"
(holdings_v2 + manager_aum) — that label was stale. Current query16
is fund-level and uses neither holdings_v2 nor managers.

### 3.6 Smoke validation against prod

Spot-check query AAPL 2025Q4 entity-keyed top-5:

```
VANGUARD GROUP INC                $375.68B    (legacy: Vanguard Group $376.29B)
BlackRock, Inc.                   $304.60B    (legacy: BlackRock / iShares $304.60B)
STATE STREET CORP                 $159.11B    (legacy: State Street / SSGA $159.11B)
GEODE CAPITAL MANAGEMENT, LLC      $94.31B    (legacy: Geode Capital Management)
FMR LLC                            $80.97B    (legacy: Fidelity / FMR)
```

Names shift to entity-canonical; dollar values match within rounding.
Capital Group AAPL exposure: 3 distinct CIKs (eid 6657 / 7125 / 7136)
aggregate cleanly under one canonical name "Capital Group / American
Funds" with $40.77B total — validates PR #287 umbrella through the
reader path.

## 4. Phase 4 validation

### 4.1 pytest

Baseline: 426 passing on main (PR #299 added 10).
Post-PR: **434 passing** (+8 new), 5 skipped (Capital Group bridge
fixture-skip + cycle-truncation fixture-skip).

New tests in [tests/test_cp5_register_unified.py](../../tests/test_cp5_register_unified.py):
T1 (quarter column + legacy column preservation), T2 (quarter
coverage), T3 (per-quarter grain), T4 (helper SQL × 2 alias modes),
T5 (Capital Group reader-path aggregation, fixture-skip), T6 (query12
SQL parses + groups), T7 (query1 ranking SQL parses).

### 4.2 Smoke endpoint regen

`tests/smoke/conftest.py` and `tests/smoke/capture_snapshots.py` now
apply migrations 027 + 028 to a tmp copy of the committed fixture
before booting the FastAPI test client. The committed fixture has
tables only; views are migration-managed. Snapshot regen ran clean.

`test_smoke_endpoints.py` query1 sentinel updated from
`institution == "Vanguard Group"` (legacy rollup_name denorm) to
`institution.lower().startswith("vanguard")` (canonical now reads
`"VANGUARD GROUP INC"`).

### 4.3 React build

No frontend changes in this PR. Build skipped.

## 5. CP-5 status

2/6 CP-5.x execution PRs shipped:

- **CP-5.1** — PR #299 (`cp-5-1b-helper-and-view`) — view foundation,
  no reader migrations.
- **CP-5.2 partial** — this PR — quarter-dimension fix + 4 of 7
  Register sites.

Next: CP-5.2 follow-ups (cp-5-2a/b/c per §6 below) before CP-5.3.

## 6. Deferred site routing

Three of the original 7 Register sites are deferred to follow-up
PRs because each requires infrastructure beyond a name-coalesce
swap.

### 6.1 cp-5-2a-summary-by-parent-rebuild  <a id="cp-5-2a"></a>

**Deferred site:** `register.py:104-115` (N-PORT coverage lookup
inside query1) **and** `register.py:560-660` (query14 drill — same
table dependency).

**Blocker:** `summary_by_parent` is keyed on
`inst_parent_name` (text), not `top_parent_entity_id`. Bundle C
**Open Q7** unresolved: rebuild as new entity-keyed table
alongside legacy NAME-keyed (cutover later) **vs** in-place rebuild
with downtime window?

**Status:** P1 ROADMAP entry added. Routes to chat-side architectural
decision before any PR. Then ships as `cp-5-2a-summary-by-parent-rebuild`
or bundles into CP-5.3 if Q7 resolves cleanly.

### 6.2 cp-5-2b-manager-type-imputation-recon

**Deferred sites:** `register.py:447-770` (query3, query4, query5 —
active/passive analysis).

**Blocker:** Comprehensive remediation §4.2 cites "manager_type
imputation" as a CP-5.2 dependency. Whether this is a genuine new
imputation layer or whether ECH `entity_classification_history` already
provides what these queries need (i.e., `'active'`/`'passive'`/etc.
in `classification`) is unconfirmed.

**Status:** P1 ROADMAP entry added. Routes to small read-only
investigation PR. Then either ships alongside this PR's reader
migrations (if no new imputation needed) or as its own scoped PR.

### 6.3 cp-5-2c-register-drill-hierarchy

**Deferred site:** `register.py:560-660` (query14 drill).

**Blocker:** Bundle C §7.4 cites "tp_to_filer hierarchy" as the
target shape. Most complex of the 3 — depends on cp-5-2a's
summary_by_parent rebuild for the parent-side keys, and a separate
filer-tier hierarchy walk that doesn't exist today.

**Status:** P1 ROADMAP entry added. Blocked on cp-5-2a. Likely its
own PR after Q7 resolution.

## 7. Out-of-scope discoveries

### 7.1 BlackRock double-count visible in unified_holdings

AAPL top-5 spot-check exposed two BlackRock entries in the
top_parent set: eid 3241 "BlackRock, Inc." and eid 2 "BlackRock /
iShares". Each carries hundreds of $B. This is the brand-vs-filer
duplication tracked under `inst-eid-bridge` / cp-4c (post-CP-5
backlog). Out of scope for this PR; flagged so the visual-QC
phase of CP-5.2 follow-ups doesn't surface it as a regression.

### 7.2 Fixture lacks committed views

The committed CI fixture
(`tests/fixtures/13f_fixture.duckdb`) carries tables only — views
are migration-managed and re-created in test setup. PR #299's smoke
tests didn't exercise reader paths that consume `inst_to_top_parent`,
so this lifecycle gap was invisible until CP-5.2 migrated query1.
The conftest + capture_snapshots updates in this PR pin the pattern;
future CP-5.x PRs that touch readers will inherit the wiring.

## 8. Files touched

| file                                                        | shape                          |
|-------------------------------------------------------------|--------------------------------|
| `scripts/migrations/028_unified_holdings_quarter_dimension.py` | new                            |
| `scripts/queries/common.py`                                 | + helper                       |
| `scripts/queries/register.py`                               | query1, query2, query12, query16 docstring |
| `tests/test_cp5_register_unified.py`                        | new (8 pass, 1 skip)           |
| `tests/smoke/conftest.py`                                   | apply 027 + 028 in tmp         |
| `tests/smoke/capture_snapshots.py`                          | apply 027 + 028 in tmp         |
| `tests/smoke/test_smoke_endpoints.py`                       | query1 sentinel update         |
| `tests/fixtures/responses/*.json`                           | snapshot regen (4 files)       |
| `data/working/cp-5-2-register-reader-inventory.csv`         | new                            |
| `data/working/cp-5-2-quarter-dimension-confirmation.csv`    | new                            |
| `docs/findings/cp-5-2-register-partial-and-unified-quarter-fix-results.md` | new (this doc) |
| `ROADMAP.md`                                                | + 3 P1 cp-5-2{a,b,c} entries   |
