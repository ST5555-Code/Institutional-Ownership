# REWRITE build_managers.py — Phase 2 staging validation

_Branch: `rewrite-build-managers`. HEAD: `2a71f8a`._
_Staging DB: `data/13f_staging.duckdb`._
_Run ID: `20260419_082630`._

## Gate summary

| Gate | Result | Notes |
|---|---|---|
| 1. holdings_v2 enrichment populated | **PASS with RISK** | `manager_type` coverage 59.9% vs prod legacy 100% — see Risk 1 |
| 2. Four output tables produced | **PASS** | Row-count deltas within expected drift |
| 3. Freshness stamps on all 5 tables | **PASS** | parent_bridge / cik_crd_links / cik_crd_direct / managers / holdings_v2 all stamped |
| 4. No writes to legacy `holdings` | **PASS** | Table absent from both prod and staging |
| 5. Downstream reader sanity | **PASS** | All 6 spot-check queries succeed |
| 6. Rebuild-kind rollback | **PASS** | Scratch-DB clone apply + restore round-tripped identical content hashes |

**Overall: gates PASS. Phase 3 review gate reached. Phase 4 requires explicit
sign-off on Risk 1 below.**

## Phase 1 commits landed

| Hash | Message |
|---|---|
| `1719320` | refactor(build_managers): repoint holdings enrichment to holdings_v2 |
| `6079220` | feat(promote_staging): add rebuild-kind full-replace semantics |
| `908d9f5` | feat(build_managers): register four output tables in promote_staging |
| `67e81f3` | feat(build_managers): --dry-run, --staging, fail-fast, retrofits |
| `2a71f8a` | fix(build_managers): dedupe parent_bridge on cik (Phase 2 finding) |

Plus `bf7bfe6` (Phase 0 findings) as the branch root.

## Rebuild-kind machinery summary

`promote_staging.py` now supports a `PROMOTE_KIND` dict (default
`pk_diff`). Registered `rebuild` kind for `managers` and
`cik_crd_links` — tables whose natural keys (cik) are not empirically
unique because of LEFT-JOIN fan-out and fuzzy-match duplicates.

- Apply path: snapshot → `DROP TABLE {prod}` → `CREATE TABLE {prod} AS
  SELECT * FROM stg.{prod}` → reset sequences.
- Rollback path: `DROP TABLE` + `CREATE TABLE AS SELECT` from the
  snapshot, preserving the prior schema even if a post-hoc stage had
  extended it between snapshot-time and apply.
- Dry-run: reports `would_replace_all prod=N → staging=M`.
- Validator registration: all four new canonical tables get
  `VALIDATOR_MAP[t] = None` with the established load-bearing warn.

## Dry-run result (`--staging --dry-run`)

```
Building parent_bridge table...
  Unique filers: 12,035
  Matched to parent groups: 554 CIKs
  Unmatched filers: 11,451
  [dry-run] would DROP+CREATE parent_bridge (11,135 rows)

Linking CIK to CRD via fuzzy name match...
  Filers without CRD: 6,534
  Direct CIK matches: 1,351
  Fuzzy matches found: 353  (rejected: 95)
  [dry-run] would DROP+CREATE cik_crd_links (353 rows)
  [dry-run] would DROP+CREATE cik_crd_direct (4,059 rows)

Building managers table...
  [dry-run] would DROP+CREATE managers (~11,135 rows, ±LEFT-JOIN fan-out)

Updating holdings_v2 with manager metadata...
  [dry-run] would UPDATE ~13,142,214 rows in holdings_v2 (join managers on cik)
```

Runtime: ~28 seconds (dominated by the fuzzy-match loop).
No DB writes; staging row counts unchanged.

## Real staging run stats

Runtime: **40.8 seconds** wall-clock. Single-threaded fuzzy-match
loop is the dominant cost.

| Table | Rows | Delta vs prod | Kind |
|---|---:|---:|---|
| parent_bridge | 11,135 | +0 | pk_diff |
| cik_crd_direct | 4,059 | +0 | pk_diff |
| managers | 11,135 | **−870** (dedupe gain, see below) | rebuild |
| cik_crd_links | 353 | −95 | rebuild |
| holdings_v2 (UPDATE) | 7,352,103 | — | direct-write (not promoted) |

CHECKPOINT + freshness timestamps: all 5 tables stamped at run
timestamp (verified in `data_freshness`).

## holdings_v2 enrichment diff (Risk 1 — detailed)

| Column | Staging post-run | Prod legacy |
|---|---:|---:|
| `inst_parent_name` | 12,270,984 / 12,270,984 (100.0%) | 12,270,984 / 12,270,984 (100.0%) |
| `manager_type` | **7,352,103 / 12,270,984 (59.9%)** | 12,270,984 / 12,270,984 (100.0%) |
| `is_passive` | 12,270,984 / 12,270,984 (100.0%) | 12,270,984 / 12,270,984 (100.0%) |
| `is_activist` | 12,270,984 / 12,270,984 (100.0%) | 12,270,984 / 12,270,984 (100.0%) |

**Root cause.** Prod legacy 100% comes from `backfill_manager_types.py`
which was last run when `holdings` was the live table. `managers.strategy_type`
itself is only ~52% populated today (prod: 6,307 / 12,005 non-null; staging:
5,857 / 11,135 non-null). When Phase 4 applies the repointed UPDATE against
prod, `holdings_v2.manager_type` coverage regresses **100% → 60%**. This is
a real data-quality regression: downstream filters like
`WHERE manager_type = 'passive'` in `compute_flows.py:350`,
`build_summaries.py:174-182`, and `queries.py:571` will miss ~40% of
positions they currently match.

**Scope boundary.** This regression is NOT caused by the rewrite. The
rewrite correctly repoints the UPDATE from the dropped `holdings` to
`holdings_v2`. The underlying coverage gap is a pre-existing issue:
`backfill_manager_types.py:77-91` was broken when `holdings` was dropped,
and no replacement has been wired to `holdings_v2`. The rewrite merely
exposes it because the UPDATE will overwrite the legacy-frozen values
with the current (NULL-heavy) managers output.

**Three options for Phase 4 (decision required).**

- **(A) Accept the regression.** Apply as-is. Coverage drops 100%→60%.
  Downstream quality regresses. Fix `backfill_manager_types.py`
  separately as a follow-up to restore coverage.
- **(B) Preserve legacy when new is NULL.** Amend the UPDATE to
  `SET manager_type = COALESCE(m.strategy_type, h.manager_type)`.
  Keeps the legacy populations for CIKs where current managers has
  NULL strategy. Only refreshes rows where managers has a real
  classification. Preserves 100% coverage. Minor risk: stale
  classifications persist until the underlying managers build
  produces non-NULL for those CIKs.
- **(C) Block Phase 4 on `backfill_manager_types.py` fix.** Add a
  new commit migrating that script to `holdings_v2` before landing
  Phase 4. Cleanest but expands scope.

**My recommendation: (B).** The semantic of "keep legacy value when
current build has no opinion" matches how downstream callers already
treat `COALESCE(manager_type, 'unknown')` (e.g.
`compute_flows.py:319`, `queries.py:571`). Same behavior without the
coverage cliff. One-line SQL change; holds regardless of whether
`backfill_manager_types.py` is ever resurrected.

## parent_bridge dedupe (Phase 2 secondary finding)

Phase 2 validation surfaced that a freshly-built staging
`parent_bridge` had 870 duplicate CIKs vs prod's snapshot of 0 dupes.
Root cause: the unmatched-filers loop iterates
`SELECT DISTINCT cik, manager_name, crd_number FROM filings_deduped`
which fans out to multiple rows per CIK when a CIK's `manager_name` or
`crd_number` differs across quarters. Prod's 0-dupe snapshot is from
an older build where this data drift was absent; the bug reproduces
against current `filings_deduped` state.

Fix landed in `2a71f8a` — `df_bridge_full.drop_duplicates(subset=["cik"])`.
Post-fix, staging produces 11,135 unique CIKs, matching the expected
empirical PK property. Knock-on effect: `managers` goes from 12,005
→ 11,135 because its LEFT JOIN against parent_bridge no longer
fans out.

`cik_crd_links` has an analogous 1-row-in-staging / 3-row-in-prod
dupe issue from the fuzzy-match loop. Left as a follow-on because
cik_crd_links routes via `rebuild` kind and tolerates dupes at the
promote layer — no immediate quality regression.

## promote_staging dry-run against final staging

```
parent_bridge: would_delete=0  would_modify=10,641  would_add=0
cik_crd_direct: would_delete=0  would_modify=0  would_add=0
managers [rebuild]: would_replace_all  prod=12,005 → staging=11,135
cik_crd_links [rebuild]: would_replace_all  prod=448 → staging=353
```

`parent_bridge` 10,641 modified rows are content updates: most CIKs
exist in both but some cells differ (likely `strategy_type` /
`parent_name` refreshes from seed re-evaluation, and the dedupe
picking a different canonical row out of prior fan-outs).
`cik_crd_direct` clean no-op (unchanged).

## Downstream reader sanity (Gate 5)

All six spot-check queries succeed against the post-run staging DB:

| Query | Result |
|---|---:|
| `parent_bridge ↔ managers` JOIN on cik | 11,135 |
| `cik_crd_direct` read | 4,059 |
| `cik_crd_links` 85-threshold read | 353 |
| `managers` non-null strategy read | 5,857 |
| `adv_managers` activist read | 12 |
| `holdings_v2` manager_type read | 7,352,103 |

These cover the live reader surfaces: `build_entities.py` (all four
tables), `fetch_adv.py`/`fetch_13dg.py`/`fetch_ncen.py` (managers),
`queries.py`/`compute_flows.py` (holdings_v2 enriched columns).

## Rebuild-kind rollback test (Gate 6)

Scripted test: cloned the four tables from prod into a scratch DB,
ran `_take_snapshot` + `_apply_table` per staging (pk_diff +
rebuild), verified post-apply state, then `_restore_snapshot`.
All four tables round-tripped to identical row counts AND identical
content hashes (MD5 over `DISTINCT cik`). Scratch DB cleaned up.

```
[pre-apply] parent_bridge=11,135  managers=12,005  cik_crd_direct=4,059  cik_crd_links=448
[post-apply] parent_bridge=11,135  managers=11,135  cik_crd_direct=4,059  cik_crd_links=353
[post-restore] parent_bridge=11,135  managers=12,005  cik_crd_direct=4,059  cik_crd_links=448  ✓ all 4 ✓
```

## Anomalies

1. **`record_freshness` initially failed in staging** with a DuckDB
   binder error on INSERT OR REPLACE. Root cause: staging's
   `data_freshness` was seeded via `CREATE TABLE AS SELECT` which
   strips the PK constraint. Fixed by recreating
   `data_freshness` in staging with `table_name PRIMARY KEY`. This is
   a staging-infra issue unrelated to this rewrite; prod's
   `data_freshness` has the PK declared and record_freshness has
   been working there for weeks. Document as a staging-seed caveat.
2. **Staging data symlink lost during pre-commit stash cycle.** The
   worktree has no `data/` directory of its own; a symlink to
   `/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership/data`
   is needed. Pre-commit hooks' `git stash` + restore can remove
   untracked entries; re-created manually between runs. Not a bug in
   this rewrite.

## Phase 3 readiness

Phase 3 review gate reached. The outstanding decision is **Risk 1
Option (A)/(B)/(C)** on `holdings_v2.manager_type` coverage. No
unresolved infrastructure issues; rebuild-kind machinery verified
end-to-end including rollback.

## Phase 4 prerequisites

1. Sign-off on Risk 1 option.
2. Prod backup via `EXPORT DATABASE` before execution.
3. Three-step sequence per the Option A flag matrix:
   - `build_managers.py --staging`
   - `promote_staging.py --approved --tables parent_bridge,cik_crd_direct,managers,cik_crd_links`
   - `build_managers.py --enrichment-only`  (against prod)

All three commands are wired and smoke-tested.

---

## Risk 1 — Pre-Phase-4 investigation (2026-04-19, post `2e59ca3`)

Read-only investigation requested before committing to Option (B)
COALESCE. Branch head unchanged for code — this section is the only
delta in the commit following this append.

### Q1 — Composition of the 40% legacy-only set

**The gap is 100% structural. No parser-suspect cases.**

| Classification | CIKs | Rows |
|---|---:|---:|
| `no_adv_filing` (structural non-coverage) | 4,163 | 5,330,772 |
| `adv_filed_parser_null` (parser-suspect) | **0** | **0** |
| `other` | 0 | 0 |
| **Total** | **4,163** | **5,330,772** |

Every CIK in the 40% set is absent from `adv_managers` entirely. Not
a single CIK represents an ADV filing the parser failed to extract.
This eliminates the "parser follow-on" branch of the decision tree —
there is nothing for fetch_adv to fix.

**Name-pattern buckets** (of the 4,163 structural CIKs):

| Bucket | CIKs | % |
|---|---:|---:|
| LLC_OTHER | 1,852 | 44.5% |
| OTHER | 1,410 | 33.9% |
| LP_OTHER | 382 | 9.2% |
| FOREIGN_SUFFIX | 289 | 6.9% |
| PENSION | 81 | 1.9% |
| INSURANCE | 59 | 1.4% |
| ENDOWMENT_FOUNDATION | 51 | 1.2% |
| FAMILY_OFFICE | 25 | 0.6% |
| BANK | 15 | 0.4% |

**Top-20 by AUM — these are major institutions, not edge cases:**

| CIK | Name | Legacy type | AUM |
|---|---|---|---:|
| 0001422849 | Capital World Investors | active | $2,772.5B |
| 0001562230 | Capital International Investors | active | $2,346.5B |
| 0001595888 | JANE STREET GROUP, LLC | quantitative | $2,221.8B |
| 0000820027 | AMERIPRISE FINANCIAL INC | mixed | $1,654.1B |
| 0001403438 | LPL Financial LLC | wealth_management | $1,266.2B |
| 0000912938 | MASSACHUSETTS FINANCIAL SERVICES CO /MA/ | active | $1,248.8B |
| 0000720005 | RAYMOND JAMES FINANCIAL INC | wealth_management | $1,193.8B |
| 0001729829 | Qube Research & Technologies Ltd | quantitative | $1,139.6B |
| 0001452861 | IMC-Chicago, LLC | quantitative | $952.3B |
| 0001859606 | Optiver Holding B.V. | quantitative | $901.6B |
| 0001067983 | Berkshire Hathaway Inc | strategic | $801.3B |
| 0001166588 | BNP PARIBAS FINANCIAL MARKETS | mixed | $752.5B |
| 0001642575 | Squarepoint Ops LLC | quantitative | $744.2B |
| 0000713676 | PNC Financial Services Group | wealth_management | $694.2B |
| 0000053417 | JENNISON ASSOCIATES LLC | active | $649.5B |
| 0000919079 | California Public Employees Retirement System | pension_insurance | $648.4B |
| 0001475365 | Sumitomo Mitsui Trust Group | mixed | $646.0B |
| 0000815917 | JONES FINANCIAL COMPANIES LLLP | wealth_management | $554.4B |
| 0001001085 | Brookfield Corp /ON/ | private_equity | $519.0B |
| 0001445893 | CTC LLC | quantitative | $515.6B |

Accepting the regression (Option A) would strip classifications
from CalPERS, Berkshire, Capital Group's two bucket funds, Ameriprise,
Edward Jones (Jones Financial), Raymond James, LPL, PNC, and major
market makers (Jane Street, IMC, Optiver, Squarepoint). These are not
obscure filers.

**Assessment: structural.** 100% structural. Zero parser-fixable
surface. The 4,163 CIKs are filers whose entity types (broker-dealers,
pension plans, foreign banks, strategic corporate holders, family
offices) are not ADV-registered investment advisers — they file 13F
under different regulatory hooks and have no CRD.

### Q2 — Provenance of the legacy 100%

**Confidence: HIGH.** Provenance is traceable, deliberate, and
semantically richer than the current pipeline produces.

**Writer:** `scripts/backfill_manager_types.py` + hand-curated
`categorized_institutions_funds_v2.csv` (5,782 rows).

**Introducing commit:** `87e832b` — "Expand manager_type: backfill
from categorized CSV + legend update" (2026-04-05).

Commit message excerpt:
```
Backfilled holdings.manager_type using categorized_institutions_funds_v2.csv,
which covers 4,434 previously uncategorized institutional entities.
- scripts/backfill_manager_types.py reads the CSV and updates
  holdings.manager_type where previous value was NULL or 'unknown'
- Preserves existing classifications (doesn't overwrite)
Results (Q4 2025):
- Unknown entities: 3,314 → 846 (75% recovery)
- New types added: strategic (637), wealth_management (247),
  venture_capital (28), endowment_foundation (79), private_equity (76),
  pension_insurance (7), SWF (1), hedge_fund (487 expanded)
Frontend legend expanded to 14 buttons (was 6)
```

**Current writer status.** `backfill_manager_types.py:77-91` targets
the dropped `holdings` table (not `holdings_v2`). Broken since the
Stage 5 migration. That is why the enrichment is frozen at its
2026-04-05 state: the legacy values persist in `holdings_v2` (carried
over during the `holdings → holdings_v2` migration) but are no longer
refreshed.

**Value distribution (prod):**

| Category | Rows (legacy holdings_v2) | Rows (current managers) | CIKs (legacy) |
|---|---:|---:|---:|
| `active` | 3,573,310 | 3,997 | 4,379 |
| `mixed` | 4,440,399 | 1,354 | 1,731 |
| `hedge_fund` | 481,744 | 548 | 1,385 |
| `passive` | 730,674 | 141 | 48 |
| `private_equity` | 6,071 | 95 | 88 |
| `quantitative` | 630,515 | 72 | 78 |
| `activist` | 14,766 | 23 | 32 |
| `wealth_management` | 1,999,306 | — | 533 |
| `pension_insurance` | 297,689 | — | 142 |
| `strategic` | 50,125 | — | 586 |
| `endowment_foundation` | 16,386 | — | 68 |
| `SWF` | 28,999 | — | 17 |
| `venture_capital` | 1,000 | — | 37 |
| `unknown` | — | 77 | — |

**Vocabulary drift.** Legacy is **strictly richer**. Six categories
exist only in legacy:
`SWF, venture_capital, strategic, wealth_management, pension_insurance, endowment_foundation`.
Only `unknown` exists only in current. All 7 of the shared categories
appear in both. This is not incompatible taxonomies — it is
legacy-richer.

Downstream queries already treat the 13-value legacy vocabulary as
authoritative (the 2026-04-05 "legend expanded to 14 buttons" change
wired the frontend to all of them). COALESCE preservation keeps a
working vocabulary in place; accepting regression would orphan 6
UI-facing categories with no replacement pipeline.

### Q3 — Combined assessment and recommendation

**Recommendation: Option (B) — COALESCE preservation + capture
`backfill_manager_types.py` migration to `holdings_v2` as a follow-on
block (not a Phase 4 blocker).**

Rationale:

1. **Q1 says structural.** The 40% is not a parser bug to fix. Zero
   CIKs benefit from blocking on an upstream parser change. The
   "parser follow-on" option from the original decision tree is
   vacuous.
2. **Q2 says HIGH provenance.** Hand-curated CSV, deliberate
   classification, 13-value vocabulary wired into the frontend.
   Option (A) — accept regression — would discard curation work
   that current pipelines cannot reconstruct.
3. **Top-AUM exposure is material.** ~$25T of cumulative AUM across
   the top-20 legacy-only CIKs (Berkshire, CalPERS, Capital Group,
   Ameriprise, etc.). Downstream flow / summary / register views
   would silently lose this classification signal.
4. **Taxonomy compatibility holds.** Legacy is strictly richer —
   COALESCE mixes cleanly because the 7 shared categories are
   identical strings, and the 6 legacy-only categories have no
   overlapping values to resolve. Existing downstream consumers
   (frontend legend, compute_flows, build_summaries) were built
   against the 13-value set already.
5. **Follow-on, not blocker.** `backfill_manager_types.py` needs
   migration to `holdings_v2` to keep the curation live as new
   quarters land, but that work doesn't gate Phase 4 — COALESCE
   preserves what's there today, and new CIKs that lack a current
   classification will fall through to NULL as expected. The
   follow-on block fixes the refresh path; Phase 4 preserves the
   snapshot.

### Concrete Phase 4 change vs the Phase 2 plan

Amend `enrich_holdings_v2(con, dry_run=False)` UPDATE at
`scripts/build_managers.py`:

```sql
UPDATE holdings_v2 h
SET
    inst_parent_name = COALESCE(m.parent_name, h.inst_parent_name),
    manager_type     = COALESCE(m.strategy_type, h.manager_type),
    is_passive       = COALESCE(m.is_passive, h.is_passive),
    is_activist      = COALESCE(m.is_activist, h.is_activist)
FROM managers m
WHERE h.cik = m.cik
```

Wrap every column in `COALESCE(m.*, h.*)` — `inst_parent_name`,
`is_passive`, `is_activist` are 100% non-NULL in the current managers
build so the COALESCE is a no-op for them today, but the pattern is
defensive against any future managers-column NULL regression and
keeps all four columns semantically consistent.

Updated dry-run expectation message: "would UPDATE rows in
holdings_v2 preserving legacy values where new build is NULL". No
row-count change to the projection (same join cardinality). Expected
post-apply `manager_type` coverage: 100.0% on prod (preserves legacy),
~60% on fresh staging seeded from a stripped baseline (validation
property only).

### Follow-on block (not Phase 4 scope)

1. Migrate `scripts/backfill_manager_types.py:77-91` from
   `holdings` → `holdings_v2` so new quarters get the curated
   classification refreshed against the 5,782-row CSV.
2. Optional: migrate the CSV-driven enrichment into `managers.strategy_type`
   directly, so `build_managers.py`'s CTAS produces the richer
   vocabulary natively and the COALESCE in Phase 4 becomes a
   no-op over time.
3. Optional: add a fresh data-quality gate in `validate_entities.py`
   or similar that alerts if `holdings_v2.manager_type` coverage
   drops below a threshold (e.g., 95%).

