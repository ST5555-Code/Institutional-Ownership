# CP-5.4 recon — Crowding / Conviction / Smart Money

Read-only investigation. Sizes the CP-5.4 reader-migration cohort
across Crowding, Conviction, and Smart Money per Bundle C §7.4 and
comprehensive-remediation §4.4. Per-site CLEAN / BLOCKED classification
plus a focused Conviction L-size deep dive (manager_aum,
portfolio_context, Direction/Since/Held column dependencies — all
three turn out to be false premises from the prompt).

Drives the chat-side decision on CP-5.4 PR shape: single bundled PR
of all CLEAN sites versus split PR with deferrals (CP-5.2 / CP-5.3
precedent) versus multi-PR carve-out for Conviction.

## 1. Phase 1 reader inventory

Inventory: [data/working/cp-5-4-reader-inventory.csv](../../data/working/cp-5-4-reader-inventory.csv).

Greps run (per Phase 1 scope):

```
grep -rn "rollup_name|inst_parent_name|rollup_entity_id|dm_rollup|dm_entity_id"
  scripts/queries/{market.py,fund.py} scripts/api_market.py scripts/api_fund.py
  web/

grep -rn "manager_aum|portfolio_context"
  scripts/queries/fund.py scripts/api_fund.py
```

### 1.1 Crowding sites (Bundle C size: M)

| id | site | shape | class |
|----|------|-------|------|
| C1 | `scripts/queries/market.py:135` | `COUNT(DISTINCT COALESCE(rollup_name, inst_parent_name, manager_name))` head query in `get_market_summary`. | CLEAN |
| C2 | `scripts/api_market.py:199` | `COALESCE(rollup_name, inst_parent_name, manager_name) as holder` GROUP BY in `/crowding` holders top-20. | CLEAN |

Per Bundle C §7.4b "Crowding | 4 sites" was an over-count. Only 2 sites
literally implement Crowding logic; the other "shared" sites in
Bundle C row aggregate were `market.py:710-730` (Sector Rotation,
not Crowding) and `market.py:1040-1130` (Entity Drilldown). Those
belong in CP-5.5 / CP-5.6 cohorts, not here. Comprehensive-
remediation §4.4 reconciles cleanly to "4 reader sites" total
across the 3 features.

### 1.2 Conviction sites (Bundle C size: L)

| id | site | shape | class |
|----|------|-------|------|
| CV1 | `scripts/queries/fund.py:110` | `portfolio_context` — top 25 holders for ticker; `COALESCE(rn_noalias, inst_parent_name, manager_name) as holder`. | CLEAN |
| CV2 | `scripts/queries/fund.py:179` + `:188` | `portfolio_context` — full per-holder portfolio for sector breakdown; same coalesce pattern in both SELECT and WHERE. | CLEAN |

Conviction's L-size sourcing turns out to be **internal pipeline
complexity**, not unmigrated infrastructure (see §3 deep dive). The
two CLEAN sub-sites convert to the existing
`top_parent_canonical_name_sql()` helper without new dependencies.

Adjacent BLOCKED reference (not a Conviction migration site, but
called by Conviction's parent-level rendering):

| id | site | shape | class |
|----|------|-------|------|
| CV3 | `scripts/queries/common.py:488-820` | `get_nport_children_batch` fund-tier NPORT family bridge (REGEX NAME). | BLOCKED_NPORT_BRIDGE (out-of-CP-5.4 scope) |

CV3 is Bundle C row 26 (NPORT family bridge, sized L, target =
RETIRE / replace with entity-keyed lookup). It is **not** in the
critical path of Conviction's CLEAN swap because the function
already works today (regex name match) and the migrated CV1/CV2
output is consumed by it as input names — the swap is upstream of
the bridge, not downstream.

### 1.3 Smart Money sites (Bundle C size: M)

| id | site | shape | class |
|----|------|-------|------|
| SM1 | `scripts/api_market.py:280` | `/smart_money` longs aggregation by `manager_type` GROUP BY (no rollup pattern). | N/A_NO_ROLLUP_PATTERN |
| SM2 | `scripts/api_market.py:299` | `/smart_money` N-PORT shorts panel keyed on `fund_name` only. | N/A_NO_ROLLUP_PATTERN |

Bundle C §7.4b's "Smart Money shares Crowding readers" refers to
**aggregate denominator semantics** (the latest-quarter manager-
type snapshot from `get_market_summary`), not literal SQL reuse.
The two `/smart_money` subqueries do not carry the COALESCE rollup
fallback pattern. Smart Money inherits any C1 migration fix
transitively — no separate Smart Money migration site exists.

### 1.4 Adjacent (out-of-Bundle-C-scope) site

| id | site | shape | class |
|----|------|-------|------|
| FPM1 | `scripts/api_fund.py:42` | `/fund_portfolio_managers` — `MAX(COALESCE(rollup_name, inst_parent_name, manager_name)) as inst_parent_name` GROUP BY `cik, fund_name`. | OUT_OF_BUNDLE_C_SCOPE_BUT_CLEAN |

Bundle C's 27-row inventory enumerated `scripts/queries/*` only;
`scripts/api_*.py` reader sites with rollup patterns weren't
scanned. C2 (api_market.py /crowding) is a second example of the
same accounting gap. Both are CLEAN if migrated. Surface for chat
as Q-1.

### 1.5 Live-DB verification

Read-only probe `scripts/oneoff/cp_5_4_recon.py` exercises every
CLEAN site against the prod DuckDB on 2025Q4 / AAPL:

```
[C1 market_summary] quarter=2025Q4 total_holders=8437
[C2 crowding AAPL] holders=20 top=Vanguard Group
[CV1 conviction_top_holders AAPL] holders=25 top=Vanguard Group
[bridge inst_to_top_parent] climbable_entities=27312
[SM1 smart_money AAPL] manager_types=15
[Phase3 manager_aum] CONFIRMED ABSENT from all CP-5.4 target files
recon OK
```

All sites return non-empty results; helper bridge
(`inst_to_top_parent` + ERH) is reachable on prod.

## 2. Phase 2 site classification

### 2.1 CLEAN site count by feature

| feature | CLEAN sites | sub-sites |
|---------|------------:|----------:|
| Crowding | 2 | 2 |
| Conviction | 1 endpoint / 2 sub-sites | 2 |
| Smart Money | 0 (no rollup pattern present) | 0 |
| **Total CP-5.4 in-scope** | **3 endpoints / 4 sub-sites** | **4** |
| Adjacent (FPM1) | 1 | 1 |

### 2.2 BLOCKED sites by class with routing

| class | sites | route |
|-------|-------|-------|
| BLOCKED_Q7 | 0 | n/a |
| BLOCKED_MGR_TYPE | 0 | n/a |
| BLOCKED_DRILL | 0 | n/a |
| BLOCKED_MANAGER_AUM | 0 | n/a — false premise (see §3.1) |
| BLOCKED_DIRECTION_HELD | 0 | n/a — false premise (see §3.3) |
| BLOCKED_NPORT_BRIDGE | 1 (CV3) | Bundle C row 26 — RETIRE / replace fund-tier NPORT family bridge with entity-keyed lookup. Not on Conviction CLEAN swap critical path. Defer to a dedicated post-CP-5.4 PR or the existing NPORT bridge cohort. |

CP-5.4 has **zero BLOCKED migration sites** in the
classification taxonomy used by CP-5.2 / CP-5.3.

### 2.3 New BLOCKED classifications surfaced

None. The two prompt-suggested new classes
(`BLOCKED_MANAGER_AUM`, `BLOCKED_DIRECTION_HELD`) do not apply —
both are false premises rooted in a misread of Conviction's
output schema and dependencies (see §3).

## 3. Phase 3 Conviction L-size deep dive

The prompt hypothesised three L-size drivers for Conviction:
manager_aum joins, portfolio_context columns, and a
Direction/Since/Held metadata column family. Each was verified
against the live code; all three turn out to be false premises.

### 3.1 manager_aum dependency analysis

**Finding: ABSENT.** No `manager_aum` token exists in any of:

- `scripts/queries/fund.py`
- `scripts/queries/market.py`
- `scripts/api_market.py`
- `scripts/api_fund.py`

Confirmed via `confirm_no_manager_aum_in_targets()` in the recon
probe. Bundle C §7.4b's "Conviction (portfolio_context + flows) |
... + manager_aum" routing was about a hypothetical "flows" sub-
component which would have lived in `scripts/queries/flows.py` if
materialised. flows.py is `Flows` feature (CP-5.5 scope per
remediation §4.5), not Conviction. The "+ manager_aum" half of
the row routes into CP-5.5, not CP-5.4.

CP-5.4 does not need any manager_aum upstream view, sub-PR, or
new view extension.

### 3.2 portfolio_context dependency analysis

**Finding: portfolio_context is a function name, not a table /
column.** It is the symbol in `scripts/queries/fund.py:44`:

```
def portfolio_context(ticker, level='parent', active_only=False,
                      rollup_type='economic_control_v1', quarter=LQ):
```

The function consumes `holdings_v2` + `fund_holdings_v2` +
`fund_universe` + `market_data` + `benchmark_weights`. None of
those tables provide a "portfolio context" column to drill into.
The L-size complexity is the **5-query pandas pipeline**:

1. `top_holders_df` — top 25 parents by latest-quarter value
2. `portfolio_df` — full per-holder ticker positions for sector breakdown
3. `get_nport_children_batch` — top 5 N-PORT children per parent (CV3 BLOCKED reference)
4. `child_portfolio_df` — full per-child portfolios
5. `fund_meta_df` — per-fund strategy lookup for type label

Plus a vectorised `_compute_metrics()` Python aggregate that
calculates sector rank, co-rank in sector, industry rank, top-3
sectors, diversity, unknown-pct, and ETF-pct.

No new infrastructure needed. The migration only swaps the
`COALESCE(rollup_name, ...)` literal in queries 1 and 2 to the
existing `top_parent_canonical_name_sql()` helper.

### 3.3 Direction / Since / Held columns

**Finding: NOT in Conviction's output schema.** The
`portfolio_context` return rows carry these fields (per
fund.py:289-307 + 371-389):

```
rank, institution, type, value, subject_sector_pct, vs_spx,
conviction_score, sector_rank, co_rank_in_sector, industry_rank,
top3, diversity, unk_pct, etf_pct, level, is_parent, child_count,
parent_name
```

No `direction`, `since`, or `held` field. The React `ConvictionTab`
column header list also does not include them (verified via the
`onExcel()` header array in `web/react-app/src/components/tabs/
ConvictionTab.tsx`). Multi-quarter `LAG / LEAD / COUNT OVER`
constructs do not appear in the function body.

If a future feature adds Direction/Since/Held to Conviction it
will be a quarter-dimension query against the migrated
`unified_holdings` view — no new infrastructure beyond what PR
#300 already supports. Out of scope for CP-5.4.

## 4. Phase 4 CP-5.4 PR shape recommendation

### 4.1 Recommended split pattern

**A — single PR for all 3 features.** All 4 in-scope CLEAN sub-
sites migrate via one helper swap with no deferrals:

- `top_parent_canonical_name_sql()` for the 3 sub-sites that
  return the holder name as a column (C1 inside COUNT DISTINCT,
  CV1 SELECT, CV2 SELECT + WHERE pair).
- `top_parent_canonical_name_sql('h')` table-aliased for the api-
  level C2 site (`/crowding` holders).

No new helpers, no new view extensions, no new test fixtures
beyond CP-5.2's pattern.

Smart Money carries no migration site of its own; the C1 migration
covers the aggregate-denominator inheritance.

### 4.2 Open question for chat — adjacent FPM1

Two equally valid routings for `scripts/api_fund.py:42`:

- **(a)** Bundle into the same CP-5.4 PR. It carries an identical
  rollup-coalesce pattern, swaps via the same helper, and would
  otherwise need its own one-line follow-up.
- **(b)** Defer to a `cp-5-x-api-rollup-sweep` PR that gathers all
  `scripts/api_*.py` rollup-pattern sites Bundle C missed. C2
  itself sits in the same "Bundle C did not enumerate api files"
  hole; this would be the principled close.

Recommendation: **(a)** — bundle into CP-5.4. Conviction tab and
Fund Portfolio tab share UI proximity (both consume the parent
brand-canonical name); shipping them together avoids visible drift
where one tab shows post-migration canonical names and the
sibling tab still shows pre-migration COALESCE fallbacks for
several days. The "api files weren't enumerated" point is
recorded here for chat to ratify or override.

### 4.3 Execute prompt sketch

If chat picks shape A + bundle FPM1, the cp-5-4-execute prompt
phases:

1. **Phase 1 reader manifest** — re-confirm the 5 CLEAN sub-sites
   (C1, C2, CV1, CV2-SELECT, CV2-WHERE) and FPM1 against HEAD;
   flag any drift.
2. **Phase 2 migration** — swap each site to
   `top_parent_canonical_name_sql()` (noalias for C1, alias `h`
   for C2 / CV2 / FPM1, noalias variant for CV1 since the GROUP
   BY targets a derived column). Update CV2's WHERE clause IN-list
   to match the migrated SELECT expression so groupings remain
   self-consistent.
3. **Phase 3 validation** —
   - new `tests/test_cp5_4_crowding_conviction_smart_money.py`
     covering: (a) `/crowding` holders panel returns a non-empty
     top-20 with at least one canonical-named holder, (b)
     `portfolio_context` parent-level returns 25 holders with
     stable ranks across the migration boundary, (c)
     `portfolio_context` carries no internal name drift between
     `top_holders_df` and `portfolio_df` (every holder in the
     parent set must appear in the per-holder portfolio frame),
     (d) `/smart_money` aggregate `holders` count for each
     manager_type matches the C1 distinct-holder count broken out
     by type within rounding (sanity that Smart Money's shared-
     denominator semantics still hold after the C1 swap).
   - smoke regen for the 3 endpoints
     (`/crowding`, `/portfolio_context`, `/smart_money`).
   - React build green.
4. **Phase 4 sign-off** — pytest 438 baseline → 438 + Δ
   (estimate Δ ≈ 6-8). No fixture or migration changes.

### 4.4 Test growth estimate

| baseline (HEAD post-PR #301) | estimated CP-5.4 add | new total |
|------------------------------:|---------------------:|----------:|
| 438 passed | +6 to +8 | 444-446 |

No fixture rebuild, no migration. Test-count delta is bounded by
the sub-site count (4 in-scope + FPM1) plus a Smart Money shared-
denominator sanity case.

## 5. Open questions for chat

1. **Q-1 Bundle FPM1 into CP-5.4?** Recommendation in §4.2 is
   yes. Alternative is a dedicated `cp-5-x-api-rollup-sweep`. Pick
   one before authoring cp-5-4-execute prompt.
2. **Q-2 CV3 routing.** `get_nport_children_batch` fund-tier NPORT
   bridge is BLOCKED at Bundle C row 26 (RETIRE-and-replace, L).
   Conviction renders parents fine without the migration; CV3
   migration belongs in a future Workstream-3 fund-to-parent
   linkage PR (per remediation §5.6) or a dedicated NPORT-bridge
   cohort. Confirm route before that PR is authored — does NOT
   block CP-5.4.
3. **Q-3 Bundle C reader-inventory hygiene.** Bundle C's 27-row
   CSV scoped `scripts/queries/*` only. C2 and FPM1 surface
   `scripts/api_*.py` as a second reader layer. Should there be a
   one-shot api-files inventory commit so future CP-5.x recons
   don't re-discover the gap? Lightweight and read-only.

## 6. Out-of-scope discoveries

### 6.1 BlackRock brand-vs-filer double-count visibility

Same caveat from CP-5.2 §7.1 / CP-5.3 §6 applies: AAPL Conviction
top-25 will surface both eid 3241 ("BlackRock, Inc.") and eid 2
("BlackRock / iShares") after migration, each carrying hundreds
of $B. This is the brand-vs-filer duplication tracked under
`inst-eid-bridge` / cp-4c (post-CP-5 backlog per remediation
§5.5). Out of scope for CP-5.4; flagged so visual-QC of the
migrated `/crowding` and `/portfolio_context` panels does not
mis-classify it as a regression.

### 6.2 `/crowding` and `/smart_money` have no React consumer today

Neither endpoint is bound to a React tab — only the typegen at
`web/react-app/src/types/api-generated.ts` references them.
ConvictionTab consumes `/portfolio_context` (Conviction's
endpoint) and FundPortfolioTab consumes
`/fund_portfolio_managers`. The migration is correctness-forward
(other clients / future tabs / direct API users still call
`/crowding`) but deserves a chat-side note: there is no end-user
visual-QC anchor for C2 or SM1/2 today.

### 6.3 Conviction's parent rendering already calls CV3

Even though CV3 is BLOCKED-and-deferred for the bridge swap, the
parent-level Conviction render today invokes it via
`get_nport_children_batch`. The migrated CV1 holder names feed
**into** CV3 as `parent_list`. After CP-5.4, holders in
parent_list will be entity-canonical names; CV3's regex matcher
must continue to accept those (it does — regex is name-string
based, agnostic to whether the name is rollup-derived or top-
parent-derived). No correctness break, but the canonical-name set
will shift slightly where the climb resolves to a different
canonical than the legacy COALESCE order. Visual-QC anchor:
verify Top-5 N-PORT children counts under each parent stay
sensible on AAPL post-migration.

## 7. Files touched (this PR)

| file | shape |
|------|-------|
| `scripts/oneoff/cp_5_4_recon.py` | new — read-only probe |
| `data/working/cp-5-4-reader-inventory.csv` | new |
| `docs/findings/cp-5-4-recon-results.md` | new (this doc) |
