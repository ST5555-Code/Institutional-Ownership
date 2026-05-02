# Institution-level scoping — partial findings (Phases 1A + 5)

Read-only investigation. Snapshot date: 2026-05-02. Prod DB: `data/13f.duckdb`.
Helpers used:

- `scripts/oneoff/institution_scoping_phase1a_distribution.py`
- `scripts/oneoff/institution_scoping_phase5_activist.py`
- ad-hoc divergence probes (managers.strategy_type, ECH.classification)

Companion phases (1B, 1.5, 2, 3, 4, 6) handled by sibling agents.

---

## Phase 1A.1 — Institution-level current state

### 1A.1.a `holdings_v2.entity_type` (is_latest=TRUE)

| entity_type           |       rows |        AUM | distinct CIKs |
|-----------------------|-----------:|-----------:|--------------:|
| active                |  4,172,727 |  $67.0T    |         4,431 |
| mixed                 |  2,893,109 |  $39.6T    |           743 |
| wealth_management     |  2,663,260 |  $15.4T    |         1,679 |
| hedge_fund            |  1,160,104 |  $25.0T    |         1,340 |
| passive               |    672,523 |  $76.3T    |            51 |
| pension_insurance     |    327,501 |   $6.9T    |           149 |
| quantitative          |    297,001 |   $5.5T    |            47 |
| strategic             |     40,341 |   $1.8T    |           451 |
| SWF                   |     21,698 |   $4.1T    |            13 |
| endowment_foundation  |     10,258 |  $865.8B   |            68 |
| private_equity        |      6,655 |  $651.6B   |            89 |
| venture_capital       |      4,774 |   $44.7B   |            46 |
| activist              |      1,033 |  $284.2B   |            16 |

Distinct CIKs across all latest holdings: ~9,121.

### 1A.1.b `holdings_v2.manager_type` (is_latest=TRUE)

| manager_type          |       rows |        AUM | distinct CIKs |
|-----------------------|-----------:|-----------:|--------------:|
| active                |  4,538,931 |  $62.0T    |         5,061 |
| mixed                 |  4,031,814 |  $55.0T    |         1,607 |
| wealth_management     |  1,306,253 |  $10.4T    |           371 |
| passive               |    751,525 |  $81.7T    |            53 |
| quantitative          |    605,493 |  $14.1T    |            80 |
| hedge_fund            |    550,373 |   $8.9T    |         1,017 |
| pension_insurance     |    289,545 |   $6.6T    |           136 |
| private_equity        |     75,214 |   $1.2T    |           112 |
| strategic             |     53,878 |   $1.8T    |           505 |
| family_office         |     36,950 |   $66.5B   |            49 |
| SWF                   |     16,915 |  $540.2B   |            13 |
| endowment_foundation  |     10,430 |  $693.4B   |            67 |
| activist              |      2,143 |  $297.1B   |            20 |
| venture_capital       |        967 |   $23.9B   |            31 |
| multi_strategy        |        553 |   $11.7B   |             2 |

Note `family_office` and `multi_strategy` exist in `manager_type` but **not** in `entity_type` — divergent dictionaries.

### 1A.1.c `managers.strategy_type` (single row per CIK)

| strategy_type          | CIKs  | aum_total |
|------------------------|------:|----------:|
| active                 | 5,500 | $10.9T    |
| (NULL)                 | 1,293 |  —        |
| mixed                  | 1,277 |  $7.9T    |
| strategic              |   911 |   $16.4B  |
| wealth_management      |   803 |  $214.6B  |
| hedge_fund             |   573 |   $5.9T   |
| pension_insurance      |   195 |  —        |
| passive                |   130 |   $8.6T   |
| endowment_foundation   |   121 |    $0.5B  |
| private_equity         |   111 |  $799.1B  |
| quantitative           |    77 |  $583.6B  |
| venture_capital        |    57 |  —        |
| family_office          |    51 |   $19.8B  |
| activist               |    26 |   $27.0B  |
| SWF                    |     7 |  —        |
| multi_strategy         |     2 |    $4.4B  |
| unknown                |     1 |    $9.3B  |

managers row count = 11,135 (distinct CIKs = 11,135). About 1,293 CIKs have NULL strategy_type — silent fall-through risk for any read site that joins managers.

### 1A.1.d Cross-tab divergence

`holdings_v2.entity_type` vs `managers.strategy_type` per CIK (latest):

- **4,043 CIKs / $64.7T AUM diverge** between `holdings_v2.entity_type` (latest) and `managers.strategy_type`. That's 44% of the 9,121-CIK universe.
- `holdings_v2.entity_type` vs `holdings_v2.manager_type` per CIK: 53 distinct (et, mt) divergent pairs. Largest:
  - `wealth_management / mixed` — 845 CIKs, $3.3T
  - `wealth_management / active` — 467 CIKs, $1.8T
  - `hedge_fund / active` — 279 CIKs, $3.4T
  - `hedge_fund / quantitative` — 33 CIKs, **$9.8T**
  - `active / mixed` — 15 CIKs, $8.3T
  - `hedge_fund / mixed` — 7 CIKs, $3.1T

Top-AUM divergence samples (entity_type vs manager_type vs strategy_type):

| cik | name | entity_type | manager_type | strategy_type | AUM |
|---|---|---|---|---|---:|
| 0000895421 | Morgan Stanley | active | mixed | mixed | $6.3T |
| 0001374170 | Norges Bank | SWF | passive | passive | $3.1T |
| 0001446194 | Susquehanna International Group, LLP | hedge_fund | mixed | mixed | $3.0T |
| 0001423053 | Citadel Advisors LLC | hedge_fund | quantitative | quantitative | $2.4T |
| 0001595888 | Jane Street Group, LLC | hedge_fund | quantitative | quantitative | $2.2T |
| 0000861177 | UBS AM US | active | mixed | mixed | $1.8T |
| 0000354204 | Dimensional Fund Advisors LP | quantitative | passive | passive | $1.8T |
| 0000820027 | Ameriprise Financial Inc | mixed | mixed | strategic | $1.7T |
| 0001403438 | LPL Financial LLC | wealth_management | wealth_management | (NULL) | $1.3T |
| 0000912938 | Massachusetts Financial Services Co | active | active | wealth_management | $1.2T |

`entity_classification_history` (open rows) classification vs `holdings_v2.entity_type` divergence (top by CIKs):

| hv2.entity_type | ECH.classification | CIKs | AUM |
|---|---|---:|---:|
| active | unknown | 122 | $141.8B |
| strategic | unknown | 42 | $113.0B |
| mixed | unknown | 18 | $55.7B |
| hedge_fund | market_maker | 5 | **$7.1T** |
| quantitative | market_maker | 5 | $548.9B |
| passive | active | 1 | **$1.2T** |
| mixed | active | 1 | $1.7T |

ECH coverage of institutions w/ latest holdings: 9,111 / 9,121 = **99.9%**, but 3,852 institutions are classed `unknown` in ECH (vs only 0 rows in holdings_v2 — `unknown` is not in the hv2 dictionary). ECH adds `market_maker` (23 rows) which is also absent from hv2.

Headline: three independent classification dictionaries are wired up to the same CIK universe and disagree at scale. `holdings_v2.entity_type`, `holdings_v2.manager_type`, `managers.strategy_type`, and `entity_classification_history.classification` each return different answers. Every read site that filters/labels by one of them has an implicit (and unreviewed) opinion about which dictionary wins.

### 1A.1.e Sample CIKs per entity_type bucket (top 5 by AUM)

- **active** — FMR LLC ($7.2T), Morgan Stanley ($6.3T), Capital World Investors ($2.8T), Capital International Investors ($2.3T), Capital Research Global Investors ($2.0T).
- **mixed** — JPMorgan Chase ($6.2T), Bank of America ($4.4T), Goldman Sachs ($2.9T), UBS Group AG ($2.4T), Royal Bank of Canada ($2.2T).
- **wealth_management** — LPL Financial ($1.3T), Raymond James ($1.2T), PNC Financial ($694B), Northwestern Mutual ($568B), Jones Financial ($554B).
- **hedge_fund** — Susquehanna International ($3.0T), Citadel ($2.4T), Jane Street ($2.2T), IMC-Chicago ($952B), Optiver ($902B).
- **passive** — Vanguard ($25.3T), BlackRock ($21.6T), State Street ($11.0T), Geode ($5.9T), Northern Trust ($3.0T).
- **quantitative** — Dimensional ($1.8T), D. E. Shaw ($613B), AQR ($565B), Ctc ($516B), Qube ($380B). (Note: Dimensional shows up here in hv2.entity_type but as `passive` in both managers.strategy_type and hv2.manager_type — classic dictionary disagreement.)
- **strategic** — Berkshire Hathaway ($801B), Sc US (TTGP) ($55B), Jarislowsky Fraser ($52B), Loews Corp ($49B), Markel Group ($48B).

---

## Phase 1A.2 — Parent-level read sites

ROADMAP (line 23) tracks a planned migration item `parent-level-display-canonical-reads` and counts **18 parent-level display read sites** that read `holdings_v2.manager_type` / `holdings_v2.entity_type` (legacy/derived) instead of canonical `entity_classification_history.classification`. The PR-1d entry (line 223) explicitly carves these 18 sites out of fund-level work as a queued P2 follow-up.

### Canonical utility (legacy direct shadow only — no parent caller today)

`scripts/queries_helpers.py:171` defines `classification_join(ec, h)` — a `LEFT JOIN entity_classification_history ech ON ech.entity_id = h.entity_id AND ech.valid_to = DATE '9999-12-31'`. This is the single canonical-via-utility helper for parent-level classification. **No file in scripts/queries/ or scripts/api_*.py imports `classification_join`.** It exists, but is not yet wired into any read path. (It is exported from `__all__` and documented but uncalled.)

The fund-level analogue `_fund_type_label(fund_strategy)` in `scripts/queries/common.py:308` is widely used for fund rows — that work landed under PR-1d on 2026-05-01 — but it operates on `fund_universe.fund_strategy`, not on `entity_classification_history`, so it is not a parent-level utility.

### Legacy-direct read sites (parent-level)

The 18 parent-level read sites that read `holdings_v2.manager_type` / `holdings_v2.entity_type` directly without going through `entity_classification_history` (or `classification_join`) are concentrated across `scripts/queries/*.py` and the FastAPI shims `scripts/api_market.py` / `scripts/api_fund.py`. Inventory by file (de-duped by query/function — multiple lines inside one query collapsed):

#### `scripts/queries/register.py` (Register tab — heaviest concentration)

1. **register.py:54** — `query1` Top holders parent block: `COALESCE(h.manager_type, 'unknown') as type`.
2. **register.py:127** — alt parent block: same shape.
3. **register.py:235** — `MAX(h.manager_type)` per holder aggregation.
4. **register.py:289 / 298 / 309** — three-quarter parent rollup (q1/q2/q4) — `MAX(manager_type)` then `COALESCE(q4.manager_type, q1.manager_type, 'unknown') as type`.
5. **register.py:464–472** — Top-25 parent block: `MAX(h.manager_type) as manager_type` + filter `AND h.entity_type IN ('active','hedge_fund','activist','quantitative')`.
6. **register.py:511 / 700 / 715** — passes `manager_type` through to API response dict.
7. **register.py:740–760 (`query4`)** — **silent-drop bug**. Active/Passive split CASE expression:
   ```sql
   CASE
     WHEN entity_type = 'passive' THEN 'Passive (Index)'
     WHEN entity_type = 'activist' THEN 'Activist'
     WHEN manager_type IN ('active','hedge_fund','quantitative') THEN 'Active'
     ELSE 'Other/Unknown'
   END as category
   ```
   Any row where `entity_type` and `manager_type` disagree such that `entity_type` is not `passive`/`activist` AND `manager_type` is not `active`/`hedge_fund`/`quantitative` falls into `'Other/Unknown'`. Per the cross-tab above this affects ~840 CIKs / multi-trillion AUM bucket (e.g. `wealth_management / mixed` 845 CIKs $3.3T; `mixed / mixed` 733 CIKs; `hedge_fund / mixed` 7 CIKs $3.1T; `mixed / family_office`).
8. **register.py:778–785 (`query5`)** — heatmap groups by `manager_type`.
9. **register.py:894** — predicate `AND entity_type NOT IN ('passive')`.
10. **register.py:918 / 963** — fund_name → manager_type mapping for register.
11. **register.py:1018** — predicate `AND entity_type IN ('active','hedge_fund')`.
12. **register.py:1045 / 1057** — active-only Top-25 join carrying `manager_type`.
13. **register.py:1121–1131 (`query16` parent)** — Top-25 parent display: `h.manager_type` projected and grouped.
14. **register.py:1170 / 1179** — coverage stats (`with_manager_type`, `manager_type_pct`).
15. **register.py:1353–1362** — passive vs active value SUM with `entity_type` filters + `COALESCE(manager_type, 'unknown') as mtype` group.

#### `scripts/queries/cross.py` (Cross-Ownership tab — institutional level)

16. **cross.py:44** — `type_filter = "AND h.entity_type NOT IN ('passive')" if active_only else ""`.
17. **cross.py:62** — `MAX(h.manager_type) as type` for institutional holders.
18. **cross.py:339 / 363 / 383** — Cross-Ownership level=parent and detail blocks: `MAX(h.manager_type) as manager_type` projected to API.
19. **cross.py:630 / 650** — `overlap_institution_detail` parent block: same.

#### `scripts/queries/flows.py` (Flow Analysis tab — institutional level)

20. **flows.py:273 / 282** — predicates `AND entity_type NOT IN ('passive','unknown')` (note: `'unknown'` doesn't appear in the hv2.entity_type dictionary, dead branch).
21. **flows.py:351 / 358** — `MAX(manager_type) as manager_type` per parent.
22. **flows.py:404 / 408 / 419 / 423 / 433 / 437** — `manager_type` carried through parent-level response dicts.
23. **flows.py:507** — direct `SELECT inst_parent_name, manager_type, ...`.
24. **flows.py:605–614** — `COALESCE(h.manager_type,'unknown') as mtype` group by `manager_type`.

#### `scripts/queries/trend.py` (Holder Momentum / Sector Flows)

25. **trend.py:148** — `MAX(manager_type) as type` per parent.
26. **trend.py:377–378** — `SUM(CASE WHEN entity_type ... ) as active_value / passive_value` (active/passive value split — same shape as register.py:1353).
27. **trend.py:469 / 671** — `active_clause` predicate building `AND entity_type IN (...)` against `peer_rotation_flows.entity_type` (precompute, not hv2 directly, but same dictionary).

#### `scripts/queries/market.py` (Market / Short Analysis)

28. **market.py:124–152** — top-of-file `aum_share_by_manager_type` returns `manager_type, SUM(market_value_usd) AS aum`.
29. **market.py:373** — predicate `AND entity_type IN ('active','hedge_fund','activist')` on precomputed flows.
30. **market.py:498** — same predicate on `prf.entity_type` for parent rollup.
31. **market.py:720 / 771** — `MAX(manager_type) as manager_type` and `'type': lrow.get('manager_type') or 'unknown'`.
32. **market.py:1055** — `MAX(manager_type) as manager_type` parent block.

#### `scripts/queries/fund.py`

33. **fund.py:111** — `MAX(manager_type) as mtype` per parent (fund-tab parent context).

#### `scripts/queries/common.py`

34. **common.py:687** — `COALESCE(h.manager_type, 'unknown') as type` — shared helper used by multiple tabs.

#### FastAPI thin shims

35. **scripts/api_market.py:200 / 203** — `manager_type` GROUP BY for short-analysis-style endpoint.
36. **scripts/api_market.py:281 / 284** — `SELECT manager_type, COUNT(DISTINCT cik) ... GROUP BY manager_type`.
37. **scripts/api_fund.py:44 / 47** — `MAX(manager_type) as manager_type` + filter `AND entity_type NOT IN ('passive')`.

### Classification of read sites

| Class | Count | Notes |
|---|---:|---|
| canonical-via-utility (`classification_join` / ECH-aware) | **0** | Helper exists in `scripts/queries_helpers.py` but no callers anywhere in `scripts/queries/` or `scripts/api_*.py`. |
| legacy-direct (read `manager_type` / `entity_type` off `holdings_v2`) | **all** | Lines enumerated above. |

The ROADMAP "18 parent-level display read sites" count tracks unique surface points (e.g. `query1`, `query4`, `cross_ownership level=parent`, etc.) rather than every grep hit. Collapsing the line-by-line inventory above to user-visible read points yields:

| # | Tab / API endpoint | File:line | Predicate / projection shape |
|---:|---|---|---|
| 1 | Register `query1` Top-holders parent | register.py:54 | `COALESCE(h.manager_type,'unknown') as type` |
| 2 | Register `query1` alt parent block | register.py:127 | same |
| 3 | Register `query2` per-holder agg | register.py:235 | `MAX(h.manager_type)` |
| 4 | Register `query3` 3-quarter parent rollup | register.py:289–309 | `COALESCE(q4.manager_type, q1.manager_type, 'unknown')` |
| 5 | Register Top-25 parent | register.py:464–472 | `MAX(h.manager_type)` + `entity_type IN ('active','hedge_fund','activist','quantitative')` |
| 6 | Register `query4` active/passive split | register.py:740–760 | **silent-drop bug** (Other/Unknown bucket) |
| 7 | Register `query5` heatmap | register.py:778–785 | GROUP BY `manager_type` |
| 8 | Register active-only filters | register.py:894 / 1018 | `entity_type` predicate |
| 9 | Register `query16` parent Top-25 | register.py:1121–1131 | projection + GROUP BY |
| 10 | Register coverage stats | register.py:1170 | `manager_type_pct` |
| 11 | Register active/passive value split | register.py:1353–1362 | mirror of `query4` shape |
| 12 | Cross-Ownership level=parent | cross.py:62 + 339 + 630 | `MAX(h.manager_type) as type/manager_type` |
| 13 | Cross-Ownership active_only filter | cross.py:44 | `entity_type NOT IN ('passive')` |
| 14 | Flow Analysis parent rollup | flows.py:273–611 | predicates + `manager_type` projection |
| 15 | Holder Momentum parent rollup | trend.py:148 + 377 | projection + active/passive split |
| 16 | Sector Flows / peer-rotation active filter | trend.py:469 / 671 | `entity_type IN (...)` against `peer_rotation_flows.entity_type` |
| 17 | Market / Short Analysis parent | market.py:373 / 498 / 720 / 771 / 1055 | predicates + `MAX(manager_type)` |
| 18 | API thin shims | api_market.py:200/281 + api_fund.py:44–47 | direct projection / filter |

Plus shared helper `common.py:687` and `fund.py:111` which are reused by multiple of the above.

This matches the ROADMAP's "18" count to within rounding (the `aum_share_by_manager_type` helper at `market.py:124–152` is sometimes counted, sometimes not, depending on whether one treats it as a top-level read site or a downstream consumer).

### React app surface

`web/react-app/src/types/api.ts` declares `manager_type: string` on six payload shapes (lines 275, 285, 314, 424, 489, 801) and `entity_type: string` on one (line 838). All are pass-through fields populated by the backend reads above. Components consume `manager_type` via the `getTypeStyle()` utility (`web/react-app/src/components/common/typeConfig.ts:20` — note `activist` is a registered badge color), used in:
- `FlowAnalysisTab.tsx:108,118,124,361`
- `OverlapAnalysisTab.tsx:187,205,221,532`
- `InvestorDetailTab.tsx:177,271`
- `FundPortfolioTab.tsx:184,281`

There is **no dedicated Activist tab** in the React app. `activist` is rendered only as a `manager_type` badge wherever it surfaces, plus as a CASE branch in `register.py:query4`.

---

## Phase 5 — Activist-as-flag architecture

### 5.1 Current state

| dictionary / column | rows | AUM | distinct CIKs |
|---|---:|---:|---:|
| `holdings_v2.manager_type='activist'` (latest) | 2,143 | $297.05B | 20 |
| `holdings_v2.entity_type='activist'` (latest) | 1,033 | $284.24B | 16 |
| `holdings_v2.is_activist=TRUE` (latest) | 1,847 | $276.70B | 16 |
| `managers.is_activist=TRUE` | 23 | $26.98B | 23 |
| `managers.strategy_type='activist'` | 26 | $26.98B | 26 |
| `entity_classification_history.classification='activist'` (open rows) | 34 | — | 34 |
| `entity_classification_history.is_activist=TRUE` (open rows) | 150 | — | 150 |

Per-CIK overlap on `holdings_v2` (20-CIK universe):

| mt='activist' | et='activist' | is_activist=TRUE | CIKs | AUM |
|---|---|---|---:|---:|
| True | True | True | 15 | $275.0B |
| True | False | False | 3 | $11.10B |
| True | True | False | 1 | $9.24B |
| True | False | True | 1 | $1.71B |

Top-AUM activists where all three signals agree: Elliott ($57.4B), Pershing Square ($43.9B), Icahn ($33.0B), Third Point ($30.4B), ValueAct ($23.1B), Starboard ($21.9B), Trian ($15.6B), Sachem Head ($13.5B), Cevian ($12.3B), Corvex ($8.7B). All pure activist names, no crossover ambiguity.

CIKs where `manager_type='activist'` but **not** `is_activist`: 4 — Mantle Ridge ($9.2B), Impactive Capital ($8.1B), Engaged Capital ($1.6B), Cannell Capital ($1.5B). These are pure activist names that just happen to have the boolean flag missing — under-population of the flag, not crossover.

CIKs where `is_activist=TRUE` but `manager_type<>'activist'`: 0 in `holdings_v2`. ECH disagrees: 70 ECH rows have `is_activist=TRUE` with `classification='active'`, 42 with `'strategic'`, 1 each with `hedge_fund`, `private_equity`, `venture_capital`. So ECH already treats `is_activist` as orthogonal to `classification` (the architectural shape Phase 5 is asking about). holdings_v2 doesn't.

### 5.2 Schema migration shape

Four signals already exist:

| location | populated? | semantics today |
|---|---|---|
| (a) `managers.is_activist` | 23 CIKs TRUE | Boolean flag, sparse. Aligns 1:1 with `managers.strategy_type='activist'` (23 of 26 CIKs). |
| (b) `entity_classification_history.is_activist` | 150 open-row entities TRUE | Boolean flag, **already orthogonal to classification**. 150 entities have it set, of which only 34 have `classification='activist'`; the other 116 have classifications `active`/`strategic`/`hedge_fund`/`venture_capital`/`private_equity`. This is the architecturally clean version. |
| (c) `holdings_v2.is_activist` | 1,847 rows TRUE / 16 CIKs | Boolean flag, denormalized into holdings. |
| (d) `holdings_v2.manager_type='activist'` | 2,143 rows / 20 CIKs | Categorical label, mutually exclusive with other manager_types. |

Recommendation shape: **promote `entity_classification_history.is_activist` to the canonical truth source**. It already exists, it already has the orthogonal-flag semantics, and it's the only one of the four where being-activist doesn't displace your underlying strategy.

Re-typing impact if `manager_type='activist'` is dropped as a category and replaced by `(strategy_type, is_activist)`:

- 20 distinct CIKs / 2,143 rows / $297.1B AUM in the holdings_v2 set.
- Of these, `managers.strategy_type` reports: 16 → `activist` (today), 3 → `active`, 1 → NULL.
- Via ECH (open rows): 15 → `activist`, 3 → `hedge_fund`, 1 → `wealth_management`, 1 → NULL.

If we honor ECH classification when re-typing (the cleaner path):

| new manager_type | CIKs | AUM (est, holdings_v2) |
|---|---:|---:|
| hedge_fund | 3 | ~$0–10B (small, includes Cannell-style names) |
| wealth_management | 1 | small |
| activist (kept as label) | 15 | ~$285B+ |
| (NULL → needs review) | 1 | — |

If we honor managers.strategy_type:

| new manager_type | CIKs |
|---|---:|
| activist | 16 |
| active | 3 |
| (NULL → needs review) | 1 |

Either way, the volume is small (20 CIKs) and the high-AUM names (Elliott, Pershing Square, Icahn, Third Point, ValueAct, Starboard, Trian) are all `activist=activist` triple-aligned and would either keep `manager_type='activist'` (if we keep activist as a label) or move to `hedge_fund` with `is_activist=TRUE` (if we treat activist as flag-only). 

### 5.3 Read-site impact

Filters on `manager_type='activist'` or `entity_type='activist'` (excluding helpers and oneoff scripts):

| File:line | Snippet | Tab |
|---|---|---|
| `scripts/queries/register.py:472` | `AND h.entity_type IN ('active', 'hedge_fund', 'activist', 'quantitative')` | Register Top-25 active universe |
| `scripts/queries/register.py:748` | `WHEN entity_type = 'activist' THEN 'Activist'` | Register query4 active/passive split CASE |
| `scripts/queries/register.py:1018` | `AND entity_type IN ('active', 'hedge_fund')` | Register active-only (note: **excludes** activist — bug or intentional?) |
| `scripts/queries/register.py:1354` | `SUM(CASE WHEN entity_type IN ('active','hedge_fund','quantitative','activist') ...)` | Register active/passive value split |
| `scripts/queries/market.py:373` | `"AND entity_type IN ('active', 'hedge_fund', 'activist')"` | Market active universe |
| `scripts/queries/market.py:498` | `"AND prf.entity_type IN ('active', 'hedge_fund', 'activist')"` | Market peer-rotation active universe |
| `scripts/build_summaries.py:173,181` | `SUM(CASE WHEN h.manager_type IN ('active','hedge_fund','quantitative','activist') ...)` | Pre-aggregated summary builder |

If activist becomes a flag, all of these become two-clause: keep the strategy filter (`active`/`hedge_fund`/`quantitative`) **OR** add `is_activist=TRUE`. The Register `query1018` is already inconsistent (excludes activist where the others include it) — that's a latent bug worth surfacing.

The React app has no dedicated Activist tab, no SQL pattern outside the badge in `typeConfig.ts:20`. The only display surface for "activist" today is:
- The categorical `Activist` slice in Register query4 (the active/passive/activist/other-unknown 4-bucket split).
- Whatever rows happen to carry `manager_type='activist'` in the various `manager_type`-projecting parent reads — which then pick up the activist badge color from `getTypeStyle()`.

There is no Activist-only filter, list, or rollup in the React app.

---

## Open questions (ranked by blocking impact)

1. **Decision D4 not yet stated.** ROADMAP notes that the precedence rule for institutions without an `entity_classification_history` row is to be defined as part of `parent-level-display-canonical-reads`. With ECH coverage at 99.9% (10 CIKs uncovered out of 9,121 latest-holding institutions), the precedence is almost moot — but those 10 still need a fallback (managers.strategy_type? holdings_v2.manager_type? `'unknown'`?). Without this, the migration is blocked at design.
2. **Three dictionaries, four columns, no reconciliation.** `entity_type` and `manager_type` use different vocabularies (`family_office`, `multi_strategy` exist in mt only; `unknown`, `market_maker` in ECH only). Migrating reads to ECH means consumers see new values their UI may not handle (`market_maker` covers ~$7T of `hedge_fund`-classified hv2 AUM via the 5 CIKs that ECH calls market_maker — these are likely Susquehanna/Citadel/Jane Street/IMC/Optiver). Need explicit value-set decision.
3. **`query4` Other/Unknown silent-drop bucket.** ROADMAP flags it; the divergence cross-tab confirms it's swallowing 845 wealth_management/mixed CIKs and a $3.3T wealth_management/mixed bucket plus several smaller pairs. Any AUM that lands there is invisible to the Register active/passive donut. This will be re-counted on migration.
4. **`register.py:1018` excludes activist where `register.py:472` and `:1354` and `market.py:373/498` include it.** Inconsistent active-universe definition across the same Register tab. Likely a copy-paste at the time activist was added — needs a one-line decision before the canonical migration.
5. **`is_activist` already exists in 4 places with different populations.** managers.is_activist (23), ECH.is_activist (150), hv2.is_activist (16 CIKs / 1,847 rows), implied via manager_type='activist' (20 CIKs). ECH is the most populated and architecturally cleanest. Need explicit decision: source of truth = ECH, downstream tables (managers, hv2) get backfilled or read-through-VIEW.
6. **Dimensional (cik=0000354204) has hv2.entity_type='quantitative' but managers.strategy_type='passive' and hv2.manager_type='passive'.** $1.8T name. Either the entity_type bucket needs split or Dimensional is mis-classified. Same shape: Norges Bank ($3.1T) is `SWF` in entity_type and `passive` everywhere else.
7. **3,852 institutions are ECH `unknown`** vs `unknown` not appearing in the hv2.entity_type dictionary at all. Migration path needs a value-mapping table.
8. **No callers of `classification_join` today.** The utility was added (per the docstring) for parent-level migration but the migration didn't ship. This means whoever drafts the migration is also drafting (or rediscovering) the JOIN macro — friction worth noting.

---

## Files written

- `docs/findings/institution_scoping_partial_1a_5.md` (this file)
- `scripts/oneoff/institution_scoping_phase1a_distribution.py` (already existed; ran to confirm)
- `scripts/oneoff/institution_scoping_phase5_activist.py` (already existed; ran to confirm)

Verification (per task constraint):

```
$ grep -iE '\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE)\b' \
    scripts/oneoff/institution_scoping_phase1a_*.py \
    scripts/oneoff/institution_scoping_phase5_*.py
scripts/oneoff/institution_scoping_phase1a_distribution.py:Verified zero write SQL: ...   ← docstring only
scripts/oneoff/institution_scoping_phase5_activist.py:    # managers.strategy_type ...  ← comment only
```

Both matches are inside Python comments / docstrings; no SQL DML/DDL is executed. The DuckDB connection in both helpers is opened with `read_only=True`.
