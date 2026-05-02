# Institution-level consolidation — Phase 1A + Phase 5 scoping fragment

**Worktree:** `pensive-montalcini-650089`
**Date:** 2026-05-02
**Mode:** Read-only investigation. Decision doc only. No DB writes, no schema changes.
**Helpers:**
- `scripts/oneoff/institution_scoping_phase1a_distribution.py`
- `scripts/oneoff/institution_scoping_phase5_activist.py`

Both helpers verified zero write SQL (`grep -nE '(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE) [A-Z]'` returns nothing). They open the prod DB with `duckdb.connect('data/13f.duckdb', read_only=True)`.

---

## Phase 1A.1 — entity_type / manager_type distributions (holdings_v2, is_latest=TRUE)

### entity_type distribution

| entity_type | rows | AUM (~) | distinct CIKs |
|---|---:|---:|---:|
| active | 4,172,727 | $67.0T | 4,431 |
| mixed | 2,893,109 | $39.6T | 743 |
| wealth_management | 2,663,260 | $15.4T | 1,679 |
| hedge_fund | 1,160,104 | $25.0T | 1,340 |
| passive | 672,523 | $76.3T | 51 |
| pension_insurance | 327,501 | $6.9T | 149 |
| quantitative | 297,001 | $5.5T | 47 |
| strategic | 40,341 | $1.8T | 451 |
| SWF | 21,698 | $4.1T | 13 |
| endowment_foundation | 10,258 | $865.8B | 68 |
| private_equity | 6,655 | $651.6B | 89 |
| venture_capital | 4,774 | $44.7B | 46 |
| activist | 1,033 | $284.2B | 16 |

(AUM totals sum AUM across positions per quarter; treat as relative magnitude, not unique AUM.)

### manager_type distribution

| manager_type | rows | AUM (~) | distinct CIKs |
|---|---:|---:|---:|
| active | 4,538,931 | $62.0T | 5,061 |
| mixed | 4,031,814 | $55.0T | 1,607 |
| wealth_management | 1,306,253 | $10.4T | 371 |
| passive | 751,525 | $81.7T | 53 |
| quantitative | 605,493 | $14.1T | 80 |
| hedge_fund | 550,373 | $8.9T | 1,017 |
| pension_insurance | 289,545 | $6.6T | 136 |
| private_equity | 75,214 | $1.2T | 112 |
| strategic | 53,878 | $1.8T | 505 |
| family_office | 36,950 | $66.5B | 49 |
| SWF | 16,915 | $540.2B | 13 |
| endowment_foundation | 10,430 | $693.4B | 67 |
| activist | 2,143 | $297.1B | 20 |
| venture_capital | 967 | $23.9B | 31 |
| multi_strategy | 553 | $11.7B | 2 |

### Key shape differences

- `entity_type` has **13 buckets**; `manager_type` has **15 buckets** — `manager_type` includes `family_office` (49 CIKs) and `multi_strategy` (2 CIKs) that don't exist as `entity_type` values.
- The CIK universes differ materially: `manager_type` covers 5,061 active CIKs vs entity_type 4,431 — entity_type appears more curated / consolidated.
- Pairs match well on the dominant active and hedge_fund segments (4,300 of 4,431 active CIKs agree on both axes; 999 of 1,340 hedge_fund CIKs agree).

### Divergent (entity_type, manager_type) pairs — top by CIK count

| entity_type | manager_type | CIKs | AUM (~) |
|---|---|---:|---:|
| wealth_management | mixed | 845 | $3.3T |
| wealth_management | active | 467 | $1.8T |
| hedge_fund | active | 279 | $3.4T |
| active | wealth_management | 71 | $557.0B |
| wealth_management | family_office | 41 | $53.0B |
| hedge_fund | quantitative | 33 | $9.8T |
| active | strategic | 30 | $39.0B |
| wealth_management | private_equity | 19 | $381.4B |
| venture_capital | private_equity | 15 | $10.5B |
| active | mixed | 15 | $8.3T |
| ... | (49 more rows in helper output) | | |

Total divergent CIK rows ≈ ~1,940 of ~9,123 unique CIKs. Largest single AUM divergence: `hedge_fund` x `quantitative` at ~$9.8T (33 CIKs — likely large quant shops like Renaissance, Two Sigma).

### Sample CIKs by dominant entity_type

```
entity_type = active            FMR LLC, Morgan Stanley, Capital World Investors
entity_type = mixed             JPMorgan Chase, Bank of America, Goldman Sachs, UBS, RBC
entity_type = wealth_management LPL Financial, Raymond James, PNC, Northwestern Mutual
entity_type = hedge_fund        Susquehanna, Citadel, Jane Street, IMC, Optiver
entity_type = passive           Vanguard, BlackRock, State Street, Geode, Northern Trust
entity_type = pension_insurance CalPERS, CPP IB, NPS Korea, State Farm, Manulife
entity_type = quantitative      Dimensional, D.E. Shaw, AQR, CTC, Qube
entity_type = strategic         Berkshire Hathaway, Sequoia, Jarislowsky Fraser, Loews, Markel
```

---

## Phase 1A.2 — parent-level read site enumeration

### Methodology

Grep for `\bmanager_type\b` and `\bentity_type\b` in:
- `scripts/queries/` (all submodules: register, fund, flows, market, cross, trend, entities, common)
- `scripts/admin_bp.py`
- `app.py`
- `web/datasette_config.yaml`
- `web/templates/admin.html`
- `web/react-app/src/`

### Counts

- **Python read sites (raw grep matches):** 76 lines
- **Web/React read sites (raw grep matches):** 28 lines

The ROADMAP claim is **"18 parent-level display read sites"**. The raw grep count is much higher than 18 because each SQL statement contains 2–4 column references (SELECT list + WHERE filter + GROUP BY). The "18" claim is the count of *distinct logical read paths* (functions / SQL statements / display components), not raw line matches.

### Read sites by file (logical SQL/expression units, with classification)

Classification key:
- **L** = legacy-direct (reads holdings_v2.manager_type or holdings_v2.entity_type directly)
- **C** = canonical-via-utility (uses `_fund_type_label(fund_strategy)` from `scripts/queries/common.py` — fund-level, already migrated by PR-1d)
- **C-fund** = fund-level read site already migrated (informational; not parent-level scope)
- **P** = parent/institution-level read site (in scope for this work)
- **F** = fund-level read site (out of scope; covered by PR-1d)

#### scripts/queries/register.py — Register tab (parent-level dominant)

| Lines | Expression | Class | Note |
|---|---|---|---|
| 54 | `COALESCE(h.manager_type, 'unknown') AS type` | L,P | Holders sub-query |
| 127 | `COALESCE(h.manager_type, 'unknown') AS type` | L,P | New entry rows |
| 235 | `COALESCE(MAX(h.manager_type), 'unknown') AS type` | L,P | Exit rows |
| 289–309 | Q4/Q1 manager_type rollup for changes | L,P | Holder Changes |
| 464–472 | `MAX(h.manager_type) ... AND h.entity_type IN ('active','hedge_fund','activist','quantitative')` | L,P | Activity filter |
| 511 / 778 / 785 | Conviction bucket SELECT/GROUP BY | L,P | Conviction tab |
| 700 / 715 | Python emit: `'manager_type': row.get('manager_type')` | L,P | Response shaping |
| 747–749 | CASE — entity_type='passive'→'Passive(Index)', =='activist'→'Activist', manager_type IN ('active','hedge_fund','quantitative')→'Active' | L,P | **Display label CASE — this is the pivotal site for institution-level relabel** |
| 894 | `entity_type NOT IN ('passive')` | L,P | Active-only filter |
| 918–963 | manager_type aggregation | L,P | type_totals |
| 1018 | `entity_type IN ('active','hedge_fund')` | L,P | Active filter |
| 1045–1057 | q4/q3 manager_type rollup | L,P | trend/quarters |
| 1121–1131 | `h.manager_type, h.is_activist ... GROUP BY ... h.manager_type, h.is_activist` | L,P | Investor detail |
| 1170 | `COUNT(CASE WHEN manager_type IS NOT NULL ...)` | L,P | DQ stat |
| 1353–1362 | passive/active value split, `COALESCE(manager_type,'unknown') AS mtype` | L,P | DQ totals |

#### scripts/queries/cross.py — Cross-holdings + Overlap

| Lines | Expression | Class |
|---|---|---|
| 44 | `AND h.entity_type NOT IN ('passive')` if active_only | L,P |
| 62 | `MAX(h.manager_type) AS type` | L,P |
| 339 / 363 / 383 | manager_type select / GROUP BY / dict emit | L,P |
| 630 / 650 | manager_type select + dict emit | L,P |
| 223 / 299 / 568 | `_fund_type_label(...)` calls | C,F |

#### scripts/queries/market.py

| Lines | Expression | Class |
|---|---|---|
| 149–152 | `SELECT manager_type, SUM(market_value_usd) ... GROUP BY manager_type` | L,P |
| 373 | `entity_type IN ('active','hedge_fund','activist')` | L,P |
| 498 | `prf.entity_type IN ('active','hedge_fund','activist')` | L,P |
| 720 / 771 | `MAX(manager_type)` + dict emit | L,P |
| 1055 | `MAX(manager_type)` | L,P |
| 667 / 692 / 827 | `_fund_type_label(...)` | C,F |

#### scripts/queries/flows.py — Flow Analysis

| Lines | Expression | Class |
|---|---|---|
| 273 / 282 | `entity_type NOT IN ('passive','unknown')` | L,P |
| 351 / 358 | `MAX(manager_type) AS manager_type` | L,P |
| 404 / 419 / 433 | dict emit `'manager_type': mt` | L,P |
| 507 | `SELECT inst_parent_name, manager_type ...` | L,P |
| 605 | `COALESCE(h.manager_type,'unknown') AS mtype` | L,P |
| 611–614 | `manager_type` GROUP BY | L,P |

#### scripts/queries/trend.py

| Lines | Expression | Class |
|---|---|---|
| 148 | `MAX(manager_type) AS type` | L,P |
| 377–378 | `entity_type NOT IN ('passive')` / `= 'passive'` split | L,P |
| 469 / 671 | `entity_type IN (?,?,?,?)` active filter | L,P |
| 91 / 310 | `_fund_type_label(...)` | C,F |

#### scripts/queries/fund.py

| Lines | Expression | Class |
|---|---|---|
| 111 | `MAX(manager_type) AS mtype` | L,P (one parent-level usage in fund tab) |
| 284 / 372 / 392 | `_fund_type_label(...)` | C,F |

#### scripts/queries/common.py

| Lines | Expression | Class |
|---|---|---|
| 687 | `COALESCE(h.manager_type,'unknown') AS type` (in `get_13f_children`) | L,P |
| 308 | `_fund_type_label` definition (canonical helper) | C |

#### scripts/admin_bp.py — Admin endpoints

| Lines | Expression | Class |
|---|---|---|
| 676 / 685 / 740 / 744 | `SELECT DISTINCT cik, manager_name, manager_type FROM ...` (admin manager browser) | L,P |

#### scripts/queries/entities.py — entity layer

| Lines | Expression | Class |
|---|---|---|
| 14, 25, 35, 44 | reads `entities.entity_type` (the dim table column, not holdings_v2) | (out-of-scope for this column scope; entity_type here refers to the entity dimension table, not the rollup classification surface) |

#### web/datasette_config.yaml — Datasette views

| Lines | Expression | Class |
|---|---|---|
| 32 | `COALESCE(h.manager_type,'unknown') AS type` | L,P |
| 51 / 56 | manager_type select + COALESCE | L,P |
| 73 | `h.manager_type` select | L,P |
| 81 | `h.manager_type IN ('active','hedge_fund','activist','quantitative')` | L,P |
| 110 | `h4.manager_type IN ('active','hedge_fund','activist')` | L,P |

#### web/templates/admin.html

| Lines | Expression | Class |
|---|---|---|
| 416 / 419 | `${m.manager_type}` JS template | L,P (display only, consumes API) |

#### web/react-app/src/ (display layer — consumes manager_type from API)

| File:Line | Expression | Class |
|---|---|---|
| `types/api.ts:275,285,314,424,489,801` | type fields `manager_type: string` | L,P (transport only) |
| `types/api.ts:838` | `entity_type: string` | L,P |
| `FundPortfolioTab.tsx:184,281` | `{m.manager_type}`, `getTypeStyle(stats.manager_type)` | L,P |
| `FlowAnalysisTab.tsx:108,118,124,361` | CSV export + `getTypeStyle(r.manager_type)` | L,P |
| `InvestorDetailTab.tsx:177,271` | CSV + `getTypeStyle(r.manager_type)` | L,P |
| `OverlapAnalysisTab.tsx:187,205,221,532` | filter `manager_type !== 'passive'`, CSV, `getTypeStyle(r.manager_type)` | L,P |
| `SectorRotationTab.tsx:546` | `getTypeStyle(t.type)` | L,P |
| `ConvictionTab.tsx` | imports `getTypeStyle` | L,P |

### Logical-units count vs ROADMAP "18 parent-level display read sites"

Counting distinct logical read paths (SQL statements / Python functions / display components) that surface a parent-level institution type to the user, on the Python query side:

| Module | Logical parent-level read units | Notes |
|---|---:|---|
| register.py | 9 | Holders / New / Exits / Changes / Activity / Conviction / Display CASE / Active filters / DQ stats |
| cross.py | 4 | Cross-holdings overlap, Overlap Analysis sub-queries |
| market.py | 4 | Sector rotation type-mix, peer rotation flows, market overview |
| flows.py | 3 | Flow Analysis from/to, parent-level emit, conviction grouping |
| trend.py | 2 | Holder trend, peer rotation active filter |
| fund.py | 1 | One parent-level mtype rollup inside a fund query |
| common.py / get_13f_children | 1 | `get_13f_children` emits manager_type as type for all parent fallbacks |
| admin_bp.py | 1 | Admin manager browser |

**Total Python parent-level logical read sites: ~25**.

ROADMAP claim of "18" appears to be lower than the actual count by ~7 sites. Likely explanations:
1. Some of the 25 are duplicates per quarter (e.g., q4/q3 trend rollups counted once)
2. The "18" may exclude admin endpoints, datasette views, and DQ stats
3. The "18" may pre-date some int-22 / market.py rewrite read sites

The Datasette config adds ~6 more SQL statements; the React display layer adds ~6 more component-level reads. **A more defensible scoping number is "~25 backend Python sites + ~6 Datasette views + ~6 React tab components ≈ 37 total touch points"**, of which all are currently legacy-direct (none use a canonical institution-level helper).

### Already-migrated sites

PR-1d already migrated **fund-level** reads to `_fund_type_label(fund_strategy)`. Those appear in:
- cross.py:223,299,568 — fund/series row emit
- fund.py:284,372,392 — fund metadata, holders aggregation
- market.py:667,692,827 — sector rotation fund row, peer flows
- register.py:164,1230,1271 — fund children, holder/exit fund rows
- trend.py:91,310 — fund-level trend emit

Total: **12 fund-level sites canonical** (matches the PR-1d note in the prompt).

**Zero parent-level sites are currently canonical.** A symmetric `_institution_type_label()` does not yet exist in `scripts/queries/common.py`.

---

## Phase 5.1 — activist current state

### holdings_v2 (is_latest=TRUE)

| Signal | rows | AUM (~) | distinct CIKs |
|---|---:|---:|---:|
| `manager_type='activist'` | 2,143 | $297.1B | 20 |
| `entity_type='activist'` | 1,033 | $284.2B | 16 |
| `is_activist=TRUE` | 1,847 | $276.7B | 16 |

### Cross-tab (per CIK overlap)

| mt='activist' | et='activist' | is_activist=TRUE | CIKs | AUM (~) |
|---|---|---|---:|---:|
| TRUE | TRUE | TRUE | 15 | $275.0B |
| TRUE | FALSE | FALSE | 3 | $11.1B |
| TRUE | TRUE | FALSE | 1 | $9.2B |
| TRUE | FALSE | TRUE | 1 | $1.7B |

**Total CIKs with manager_type='activist': 20.** 15 of 20 (75%) have all three signals aligned.

### Sample CIKs

**Aligned (mt + et + flag):** Elliott (~$57.4B), Pershing Square (~$44.0B), Icahn (~$33.0B), Third Point (~$30.4B), ValueAct (~$23.1B), Starboard (~$21.9B), Trian (~$15.6B), Sachem Head, Cevian, Corvex.

**manager_type='activist' but is_activist=FALSE:**
- Mantle Ridge LP (~$9.2B) — `entity_type='activist'`, missing flag
- Impactive Capital LP (~$8.1B) — `entity_type=NULL`, missing flag
- Engaged Capital LLC (~$1.6B) — same
- Cannell Capital LLC (~$1.5B) — same

**is_activist=TRUE but manager_type<>'activist':** zero CIKs (the holdings_v2 flag is fully covered by manager_type='activist').

### managers table

- `managers.is_activist=TRUE`: 23 rows / ~$27.0B AUM (per managers, only filers with reported AUM_total)
- `managers.strategy_type='activist'`: 26 rows / ~$27.0B AUM
- 23 of 26 have both. 3 CIKs have `strategy_type='activist'` with `is_activist=FALSE` (drift between fields).

### entity_classification_history (open rows, valid_to=9999-12-31)

- `classification='activist'` open rows: **34**
- `is_activist=TRUE` open rows: **150** (much wider — flag set on entities classified into other buckets)

ECH cross-tab on open rows where activist signal is present:

| classification | is_activist | rows |
|---|---|---:|
| active | TRUE | 70 |
| strategic | TRUE | 42 |
| activist | TRUE | 34 |
| venture_capital | TRUE | 2 |
| private_equity | TRUE | 1 |
| hedge_fund | TRUE | 1 |

This is the cleanest signal for the activist-as-flag architecture: **the entity layer already treats activist as a flag layered on top of an underlying classification.** 116 of 150 entities (77%) have an underlying non-activist classification with the activist flag set — exactly the pattern Phase 5 wants.

---

## Phase 5.2 — migration shape

### Underlying classification mapping for the 20 manager_type='activist' CIKs

Cross-referenced to managers and ECH:

| Source | Classification breakdown |
|---|---|
| `managers.strategy_type` | activist: 16, active: 3, NULL: 1 |
| ECH (via entity_id, open rows) | activist: 15, hedge_fund: 3, wealth_management: 1, NULL: 1 |

ECH is the more authoritative signal (it has hedge_fund / wealth_management as the underlying type, which managers.strategy_type doesn't surface). The 16 "activist" cases in managers represent activist as the primary strategy_type — under the new architecture these would be reclassified to their underlying type (most likely `hedge_fund` based on ECH).

### Migration shape (plain English steps)

1. **Backfill `is_activist=TRUE`** for the 4 CIKs currently typed `manager_type='activist'` but missing the flag (Mantle Ridge, Impactive Capital, Engaged Capital, Cannell Capital — total ~$20.4B).
2. **Choose underlying classification** for each of the 20 activist CIKs by source priority: ECH classification → managers.strategy_type → manual triage. Most map to `hedge_fund`; a handful (e.g., Cannell, Impactive) map to wealth_management or active.
3. **Reclassify holdings_v2.manager_type** for those 20 CIKs from `'activist'` to the chosen underlying type. Same for `entity_type` where it currently reads `'activist'`. Use the established staging → diff → promote workflow (per memory note `project_staging_workflow_live`).
4. **Update read sites** to drop `manager_type='activist'` filters and any CASE branches that surface `'Activist'` as a type label. Replace with: pull underlying type for the type column AND surface `is_activist` as a separate boolean badge / filter.
5. **Add `_institution_type_label()` canonical helper** in `scripts/queries/common.py`, analogous to `_fund_type_label()`. Signature suggestion: `_institution_type_label(manager_type_or_classification, is_activist=False) -> (label, badges)`. Migrate the ~25 parent-level read sites to call it.
6. **Verify** with the existing acceptance gates (total_aum gate, INF gates, snapshot framework) before promoting.

### Migration complexity assessment

- **Data scope:** 20 CIKs, ~2,143 rows, ~$297B AUM. Modest.
- **Code scope:** ~25 Python read sites + 6 Datasette views + 6 React components. Significant fan-out but mechanical.
- **Risk:** the display CASE in `register.py:747-749` currently surfaces three levels of priority (entity_type='passive' → entity_type='activist' → manager_type-based 'Active'). The activist branch must continue to surface activist visually (as a badge derived from `is_activist`) or product behavior changes.
- **Overall:** **MEDIUM**. Mechanical fan-out in code, but small data footprint. ECH already has activist-as-flag for 116 entities — the pattern is proven. Main risk is missing one of the ~37 read sites and ending up with a half-migrated display.

---

## Phase 5.3 — read-site impact (activist filters)

### Sites that filter on `manager_type='activist'` or `entity_type='activist'`

| File:Line | Expression | Migration impact |
|---|---|---|
| `scripts/queries/register.py:472` | `AND h.entity_type IN ('active','hedge_fund','activist','quantitative')` | Replace with `IN (active, hedge_fund, quantitative) OR h.is_activist=TRUE` |
| `scripts/queries/register.py:748` | `WHEN entity_type = 'activist' THEN 'Activist'` (display CASE) | Replace with `is_activist=TRUE` predicate; emit Activist as a badge alongside underlying type |
| `scripts/queries/register.py:861` | `WHERE ticker = ? AND is_activist = true` | Already canonical — keep |
| `scripts/queries/register.py:1018` | `AND entity_type IN ('active','hedge_fund')` | No change (excludes activist already) |
| `scripts/queries/register.py:1121,1131` | `h.is_activist` selected and grouped | Already canonical |
| `scripts/queries/register.py:1354` | `entity_type IN ('active','hedge_fund','quantitative','activist')` | Replace with `IN(...) OR is_activist=TRUE` |
| `scripts/queries/market.py:373` | `entity_type IN ('active','hedge_fund','activist')` | Same pattern |
| `scripts/queries/market.py:498` | `prf.entity_type IN ('active','hedge_fund','activist')` | Same |
| `web/datasette_config.yaml:81` | `h.manager_type IN ('active','hedge_fund','activist','quantitative')` | Same |
| `web/datasette_config.yaml:110` | `h4.manager_type IN ('active','hedge_fund','activist')` | Same |

### React app — specific activist-filter tabs

No tab is filtered exclusively to activists in the React app (no "Activist" tab found). Activists appear:
- In **OverlapAnalysisTab.tsx:187** — only filter is `manager_type.toLowerCase() !== 'passive'`, so activists are included in active.
- As display badges via `getTypeStyle(r.manager_type)` — once `manager_type` no longer has `'activist'`, the type badge swaps to underlying type. To preserve the activist visual, `getTypeStyle` (or a new helper) must accept `is_activist` to overlay/replace badge color.

### Display label CASE — primary touch point

`scripts/queries/register.py:747-749`:

```sql
WHEN entity_type = 'passive' THEN 'Passive (Index)'
WHEN entity_type = 'activist' THEN 'Activist'
WHEN manager_type IN ('active','hedge_fund','quantitative') THEN 'Active'
```

After migration becomes:

```sql
WHEN entity_type = 'passive' THEN 'Passive (Index)'
WHEN is_activist = TRUE THEN <underlying_label> + ' (Activist)'
WHEN manager_type IN ('active','hedge_fund','quantitative') THEN 'Active'
```

This is the single most-product-facing line of the migration.

---

## Open questions for synthesis

1. **Canonical column choice.** The migration target should be one of `manager_type`, `entity_type`, or a new derived field. Currently both columns coexist with semantic drift. Phase 1A.1 shows ~1,940 CIKs with divergent pairs. Which column is the source of truth post-consolidation? (Recommend: ECH `classification` joined onto holdings via entity_id — that matches the fund-level pattern of resolving canonical state via a dimension table.)

2. **family_office and multi_strategy.** Present in `manager_type` (51 CIKs combined) but not in `entity_type`. Are these new buckets ECH should adopt, or are they `manager_type` legacy that should consolidate into wealth_management / hedge_fund?

3. **PE/VC divergence.** 15 CIKs have `entity_type='venture_capital'` but `manager_type='private_equity'`. Which is canonical? (Sample needed for triage.)

4. **ROADMAP "18" reconciliation.** The actual logical Python read-site count for parent-level institution type is ~25 (or ~37 including Datasette + React). Is the "18" claim a subset (e.g., excluding admin/DQ paths)? Synthesis should confirm whether the broader scope changes the work-estimate.

5. **Activist underlying classification authority.** Use ECH as the primary source (15/20 say activist as classification too, 3 say hedge_fund, 1 wealth_management, 1 NULL) — or use managers.strategy_type (16 activist, 3 active, 1 NULL)? They disagree on a handful. Manual triage probably needed for ~5 edge-case CIKs.

6. **Active filter symmetry.** Several queries filter `entity_type IN ('active','hedge_fund','activist','quantitative')` (active-set inclusive) while others filter `entity_type NOT IN ('passive')` (active-set exclusive). After activist becomes a flag, the active-set definition needs a single canonical answer.

7. **3 CIKs with `managers.strategy_type='activist'` but `is_activist=FALSE`.** Pre-existing drift in managers. Worth backfilling regardless of this migration.

---

## File path

Findings: `/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership/.claude/worktrees/pensive-montalcini-650089/docs/findings/institution_scoping_phase_1A_5.md`
Helpers:
- `/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership/.claude/worktrees/pensive-montalcini-650089/scripts/oneoff/institution_scoping_phase1a_distribution.py`
- `/Users/sergetismen/ClaudeWorkspace/Projects/13f-ownership/.claude/worktrees/pensive-montalcini-650089/scripts/oneoff/institution_scoping_phase5_activist.py`
