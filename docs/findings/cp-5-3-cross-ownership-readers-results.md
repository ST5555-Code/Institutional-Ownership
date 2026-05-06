# CP-5.3 — Cross-Ownership reader migrations

Second reader migration PR for CP-5. Migrates the 3 CLEAN sites in
`scripts/queries/cross.py` to entity-keyed grouping via the
`inst_to_top_parent` climb (migration 027). Same
`top_parent_canonical_name_sql` helper pattern as PR #300 / Register.

Drill sites (C3 / C5) are deferred to `cp-5-2c-register-drill-hierarchy`
because their filer-tier ERH lookup does not match the new top-parent
canonical name produced by the migrated parent reads.

## 1. Phase 0 — pre-flight cleanup

Local worktree carried one stale untracked file
(`data/working/cp-5-1-view-vs-cte-benchmark.csv`) that PR #299 had
since landed on `origin/main`. Moved to `/tmp/` to avoid pull
collision, then `git pull origin main` cleanly fast-forwarded to
`e513078` (PR #300 merge). Branch `cp-5-3-cross-ownership-readers`
created off that HEAD inside the existing worktree. Latest migration
is 028; reader-only PR — no new migration needed.

## 2. Phase 1 — discovery

### 2.1 Cross-Ownership reader inventory

Scope per Bundle C §7.4: `scripts/queries/cross.py` is the primary
Cross-Ownership reader file. Three downstream consumers
(`scripts/api_*.py`, `web/`) reference `inst_parent_name` only as a
display field name in TypeScript types, not as a query path — none
are migration targets.

The 9 grep hits in `cross.py` resolve to **6 distinct sites** in 6
functions:

| site | function                                | shape                                        | class           |
|------|-----------------------------------------|----------------------------------------------|-----------------|
| C1   | `_cross_ownership_query`                | parent matrix (Top Investors / Top Holders) | CLEAN (3 sub-sites) |
| C2   | `_cross_ownership_fund_query`           | fund-level cross-ownership                   | NO_OP           |
| C3   | `get_cross_ownership_fund_detail`       | Top Investors fund drill                     | BLOCKED_DRILL   |
| C4   | `get_two_company_overlap`               | 2-Company Overlap institutional panel        | CLEAN (2 sub-sites) |
| C5   | `get_overlap_institution_detail`        | 2-Company Overlap institution drill          | BLOCKED_DRILL   |
| C6   | `get_two_company_subject`               | 2-Company Subject-only panel                 | CLEAN (1 sub-site) |

CLEAN total: 3 sites / 6 sub-sites name-coalesce swaps.

Full per-site classification with rationale:
[`data/working/cp-5-3-cross-ownership-reader-inventory.csv`](../../data/working/cp-5-3-cross-ownership-reader-inventory.csv).

### 2.2 BLOCKED_DRILL routing

C3 (`get_cross_ownership_fund_detail`) and C5
(`get_overlap_institution_detail`) drill into a parent's funds by
filtering `EXISTS (… WHERE e2.canonical_name = institution)` against
`decision_maker_v1` ERH. The lookup resolves to the **filer-tier**
canonical name. After the C1 / C4 / C6 migration, the parent name
returned to the front-end is the **top-parent** canonical name
(`inst_to_top_parent` climb). For multi-arm umbrellas — Capital Group
eid 12 with 3 wholly_owned filer arms (eid 6657 / 7125 / 7136) per
PR #287 — the two names diverge: top-parent returns
`"Capital Group / American Funds"`, filer-tier ERH returns
`"American Funds"` (or sibling brand names). The drill then misses.

Both sites need the EXISTS clause to climb via `inst_to_top_parent`
and compare against the top-parent canonical name. That is a real
query rewrite, not a 1-line swap, so they're routed to the existing
P1 sub-PR `cp-5-2c-register-drill-hierarchy` per the M-sized split
rule.

### 2.3 Helper composition check

`top_parent_canonical_name_sql('h')` covers Cross-Ownership needs
without extension. The expression is a self-contained correlated
subquery returning a name; it drops into CTE projections, GROUP BY
clauses, and pivot CASE expressions equivalently. The C1 multi-
ticker pivot wraps the helper in `SUM(CASE WHEN ph.ticker = '…')`
groupings — the helper sits at the parent_holdings projection layer,
unchanged shape.

The fund_parents CTE inside C1 is the one place where a second
climb was needed (see §3.1).

## 3. Phase 2 — reader migrations

### 3.1 C1 — `_cross_ownership_query`

Three coordinated swaps within the function so name shapes stay
consistent across the parent_holdings / portfolio_totals / fund_parents
CTEs, and the LEFT JOIN keys downstream:

1. **`parent_holdings` projection** (was: `COALESCE({rn},
   inst_parent_name, manager_name) as investor`). The `rn` variable
   referenced `_rollup_name_sql('h', rollup_type)` and threaded
   `rollup_type` through the function. Replaced with
   `top_parent_canonical_name_sql('h')`. Helper is rollup-type
   independent (climb traverses ownership-layer edges); the
   `rollup_type` parameter is preserved on the function signature
   for API compatibility but is now inert (`_ = rollup_type`),
   matching the `register.query1` convention.
2. **`portfolio_totals` projection** — same swap.
3. **`fund_parents` CTE** — added `inst_to_top_parent` climb to the
   ERH JOIN so the canonical name returned matches the migrated
   parent_holdings investor. Without the climb, multi-arm umbrellas
   (Capital Group eid 12) produce filer-tier names in `fund_parents`
   that fail the downstream `LEFT JOIN fund_parents fp ON fp.name =
   ph.investor`, silently flipping `has_fund_detail` from `True` to
   `False` for the umbrella row. The smoke test in §4.3 confirms the
   fix.

### 3.2 C4 — `get_two_company_overlap`

Two swaps in `subj_holders` and `sec_holders` CTEs. Both used the
literal `h.rollup_name` (legacy `economic_control_v1` denorm column),
not the rollup-type-parameterized `_rollup_name_sql`. Computed
`tpn = top_parent_canonical_name_sql('h')` once at function head;
both CTEs now reference `{tpn} as holder`.

The fund panel and overlap drill (`get_overlap_institution_detail`)
are not migrated here — drill blocked per §2.2.

### 3.3 C6 — `get_two_company_subject`

One swap in the `inst_rows` projection. Subject-only variant of C4;
same `tpn` helper at function head.

### 3.4 Migration manifest

Per-site before/after expressions:
[`data/working/cp-5-3-cross-ownership-migration-manifest.csv`](../../data/working/cp-5-3-cross-ownership-migration-manifest.csv).

### 3.5 BLOCKED sites — deferred routing

| site | defer to                                |
|------|-----------------------------------------|
| C3   | `cp-5-2c-register-drill-hierarchy`     |
| C5   | `cp-5-2c-register-drill-hierarchy`     |

The existing P1 ROADMAP entry from CP-5.2 expands to cover C3 + C5.
No new ROADMAP rows; the cross-ownership drills join the same
hierarchy work.

## 4. Phase 3 — validation

### 4.1 pytest

- Baseline (PR #300 / `e513078`): 434 passing, 5 skipped.
- Post-PR: **438 passing** (+4 new), **6 skipped** (+1 new — Capital
  Group bridge fixture-skip, same as the Register suite).

New tests in
[`tests/test_cp5_cross_ownership_unified.py`](../../tests/test_cp5_cross_ownership_unified.py):

- T1 — C1 single-ticker matrix SQL pattern parses + groups by
  canonical top-parent name.
- T2 — C1 multi-ticker pivot (Top Investors Across Group): no
  duplicate canonical names within result set (entity-keyed
  grouping invariant).
- T3 — fund_parents CTE climbs to top parent (pins the §3.1 fix).
- T4 — C4 / C6 overlap holder pattern parses + no-dup invariant.
- T5 — Capital Group umbrella aggregation through cross-ownership
  reader path (fixture-skip; validates PR #287 → CP-5.3).

`tests/test_app_ticker_validation.py` (BL-7) also exercises the
migrated readers via the FastAPI test client (38 tests through
`/api/v1/cross_ownership` / `/api/v1/two_company_overlap` routes).
Updated its `client` fixture to copy the committed fixture to a tmp
file and apply migrations 027 + 028 before booting — same wiring as
`tests/smoke/conftest.py` from PR #300. The BL-7 fixture pattern was
the only non-smoke test entry point that hit Cross-Ownership; once
the wiring landed, all 38 BL-7 tests passed unchanged.

### 4.2 React build

No frontend changes in this PR. Build skipped (matches PR #300 §4.3).

### 4.3 App smoke against live prod DB

Started the FastAPI app with `DB_PATH_OVERRIDE` pointing at the live
prod DuckDB (which carries migrations 027 + 028 from PR #300).

**Top Holders by Company — `/api/v1/cross_ownership?tickers=AAPL`:**

```
VANGUARD GROUP INC                $375,683,182,948    passive
BlackRock, Inc.                   $304,603,196,045    passive
STATE STREET CORP                 $159,108,483,417    passive
GEODE CAPITAL MANAGEMENT, LLC      $94,305,764,978    passive
FMR LLC                            $80,968,439,338    active
```

Numbers match PR #300 §3.6 spot-check exactly — same canonical
top-parent climb on the same data.

**Top Investors Across Group —
`/api/v1/cross_ownership?tickers=AAPL,MSFT,NVDA`:**

Top 5 hold the same parents in the same order, with per-ticker
breakdowns aggregating cleanly (Vanguard $1.13T across the 3 names;
BlackRock $943B; etc.). No duplicate canonical names in the top-25.

**Capital Group umbrella —
`/api/v1/cross_ownership?tickers=AAPL,MSFT,NVDA&limit=50`:**

Single row `"Capital Group / American Funds"` with AAPL=$40.77B,
MSFT=$92.19B, NVDA=$80.56B, `has_fund_detail=True`. The 3 Capital
Group filer arms (eid 6657 / 7125 / 7136 per PR #287) collapse
under one canonical eid 12 name through the cross-ownership reader
path — validates the umbrella bridges end-to-end. The
`has_fund_detail=True` flag confirms §3.1 fund_parents climb fix:
top-parent canonical name matches between parent_holdings and
fund_parents JOIN keys.

(A second `Capital`-named row appeared as `Himalaya Capital` —
substring coincidence, distinct entity. Not a duplication.)

**2-Company Overlap —
`/api/v1/two_company_overlap?subject=AAPL&second=MSFT&quarter=2025Q4`:**

50 institutional holders returned, ordered by subj_dollars desc.
Top 5 = same canonical Vanguard / BlackRock / SSGA / Geode / FMR
shape as the cross-ownership panel. Subj_dollars / sec_dollars
populate independently from migration's two CTE legs.

Each smoke check returned sensible numbers and entity-canonical
names. App stopped cleanly.

## 5. CP-5 status

3/6 CP-5.x execution PRs shipped:

- **CP-5.1** — PR #299 (`cp-5-1b-helper-and-view`) — view foundation,
  no reader migrations.
- **CP-5.2 partial** — PR #300 (`cp-5-2-register-partial-and-unified-quarter-fix`)
  — quarter-dimension fix (migration 028) + 4 of 7 Register sites.
- **CP-5.3** — this PR — Cross-Ownership 3 of 6 sites; 2 drill sites
  routed to `cp-5-2c-register-drill-hierarchy`.

Next: **CP-5.4** — Crowding / Conviction / Smart Money readers
(Bundle C §7.4 medium-sized, 3 features bundled if reader patterns
align). The CP-5.2 sub-PRs (`cp-5-2a` / `cp-5-2b` / `cp-5-2c`) are
chat-side architectural-decision-pending and may interleave with
CP-5.4.

## 6. Out-of-scope discoveries

### 6.1 BlackRock brand-vs-filer double-count visible in cross-ownership

Same as PR #300 §7.1: AAPL top-5 returns
`BlackRock, Inc.` (eid 3241) and the cross-ownership matrix would
also surface `BlackRock / iShares` (eid 2) as a separate row if
queried with broader limits. PR #300 §7.1 flagged this as an
`inst-eid-bridge` / cp-4c follow-up (post-CP-5 backlog). Confirmed
to persist on Cross-Ownership endpoints — same root cause, same
deferral.

### 6.2 BL-7 fixture-DB conftest pattern propagates

PR #300 added the migration-on-tmp-fixture pattern to
`tests/smoke/conftest.py`. CP-5.3 hit the same gap in
`tests/test_app_ticker_validation.py`: fixture-DB test that exercises
a reader path consuming `inst_to_top_parent`. Mirrored the smoke
conftest wiring inline in the BL-7 client fixture. Worth carrying
this forward as a pattern: any non-smoke fixture-DB test that hits a
CP-5-migrated reader will need the same tmp-fixture-with-views
bootstrap. Not a recurring problem yet (only 2 sites total: smoke +
BL-7), so I haven't lifted it into a shared conftest helper.

## 7. Files touched

| file                                                          | shape                                            |
|---------------------------------------------------------------|--------------------------------------------------|
| `scripts/queries/cross.py`                                    | C1 / C4 / C6 reader migrations + fund_parents climb fix |
| `tests/test_cp5_cross_ownership_unified.py`                   | new (4 pass, 1 fixture-skip)                     |
| `tests/test_app_ticker_validation.py`                         | client fixture: apply 027 + 028 to tmp copy     |
| `data/working/cp-5-3-cross-ownership-reader-inventory.csv`    | new (per-site classification)                    |
| `data/working/cp-5-3-cross-ownership-migration-manifest.csv`  | new (per-site before/after expressions)          |
| `docs/findings/cp-5-3-cross-ownership-readers-results.md`     | this doc                                         |

No migrations, no schema changes. Reader-only PR.
