# Classification Display Audit (PR-1c)

**Branch:** `classification-display-audit`
**HEAD at start:** `8cf8ab0` (PR-1b peer-rotation-rebuild)
**Scope:** Read-only audit of every API endpoint and query module to map exactly where the `type`, `is_active`, `is_passive`, and related classification display fields are sourced from.
**Output:** This document. No code or data changes.

This audit is the foundation for PR-1d (display-fix). It identifies every place the display layer reads from a derived column (`is_actively_managed`, `manager_type`, `entity_type`) or a hardcoded label map (`_classify_fund_type`) instead of the canonical source (`fund_universe.fund_strategy` for funds, `entity_classification_history.classification` for parents).

---

## 1. Summary

### Endpoints audited

| Module | Routes | Classification-emitting routes |
|---|---:|---:|
| `api_register.py` | 5 | 5 (query1, query{N}, summary) |
| `api_cross.py` | 8 | 6 (cross_ownership × 2, fund_detail, two_company_overlap, two_company_subject, overlap_institution_detail) |
| `api_flows.py` | 7 | 6 (flow_analysis, holder_momentum, peer_rotation × 2, portfolio_context, ownership_trend_summary) |
| `api_fund.py` | 1 | 1 (fund_portfolio_managers) |
| `api_market.py` | 12 | 5 (smart_money, crowding, short_analysis: nport_detail / nport_by_fund / cross_ref / short_only_funds, sector_summary subset) |
| `api_entities.py` | 5 | 4 (entity_search, entity_children — wrapped, entity_graph, institution_hierarchy) |
| `api_config.py` | 2 | 0 |
| `admin_bp.py` | ~30 | 0 (admin-only; out of scope) |
| **Total user-facing** | **40** | **27** |

### Source classification

Counted by endpoint × emitted field. One endpoint can emit multiple classification fields and each is counted separately.

| Source kind | Count | What it reads |
|---|---:|---|
| **Canonical (parent)** | 4 | `entity_current.classification` / `entity_current.entity_type` (entity graph) |
| **Canonical (fund)** | 0 | No endpoint reads `fund_universe.fund_strategy` or `fund_holdings_v2.fund_strategy` |
| **Derived (parent)** | 18 | `holdings_v2.manager_type`, `holdings_v2.entity_type`, `holdings_v2.is_activist` |
| **Derived (fund)** | 12 | `fund_universe.is_actively_managed` |
| **Hardcoded (fund)** | 6 | `_classify_fund_type(fund_name)` keyword sweep |
| **NULL/broken** | 1 | `holder_momentum` level=fund N-PORT children carry `'type': None` (trend.py:295) |

### Headline

The display layer **does not read the canonical source** anywhere. Every fund-level `type` value is computed from one of two derived signals (`is_actively_managed`, name-based keyword sweep), and every parent-level `type` value comes from the legacy `manager_type` / `entity_type` columns on `holdings_v2`. PR-1a/PR-1b cleaned the canonical column but the display layer never saw the change.

---

## 2. Endpoint master table

Format: each row maps one classification-related field on one endpoint. Level = which branch of the function emits the row. Source columns describe SQL + Python transformation.

### Register / Holder Changes / Conviction surface

| Endpoint | Level | Response field | SQL source | Transformation | File:line |
|---|---|---|---|---|---|
| `/api/v1/query1` (Register) | parent (top 25) | `type` | `MAX(h.manager_type) FILTER … COALESCE(…,'unknown')` on `holdings_v2` | passthrough | [register.py:54](scripts/queries/register.py:54), [register.py:65](scripts/queries/register.py:65) |
| `/api/v1/query1` (Register) | fund (N-PORT children) | `type` | none — derived from fund name | `_classify_fund_type(k['institution'])` | [register.py:164](scripts/queries/register.py:164) |
| `/api/v1/query1` (Register) | fund (13F entity fallback) | `type` | `COALESCE(h.manager_type,'unknown')` on `holdings_v2` | passthrough | [register.py:127](scripts/queries/register.py:127), [register.py:153](scripts/queries/register.py:153) |
| `/api/v1/query2` (Holder Changes) | parent | `type` | `COALESCE(q4.manager_type, q1.manager_type, 'unknown')` on `holdings_v2` | passthrough | [register.py:309](scripts/queries/register.py:309), [register.py:377](scripts/queries/register.py:377) |
| `/api/v1/query2` (Holder Changes) | fund (N-PORT child) | `type` | hardcoded | `'type': None` (parent summary row sets `None`); 13F fallback uses parent's `manager_type` | [register.py:387](scripts/queries/register.py:387), [register.py:399](scripts/queries/register.py:399) |
| `/api/v1/query3` (Conviction list) | parent | `manager_type` | direct `manager_type` column on `holdings_v2` | passthrough | [register.py:464](scripts/queries/register.py:464), [register.py:511](scripts/queries/register.py:511) |
| `/api/v1/query3` (Conviction list) | fund (N-PORT) / fund (13F entity) | `manager_type` | inherited | child row inherits parent's `manager_type` | [register.py:700](scripts/queries/register.py:700), [register.py:715](scripts/queries/register.py:715) |
| `/api/v1/query4` (Active vs Passive split) | aggregate | `category` (label) | CASE WHEN `entity_type = 'passive'` / `entity_type = 'activist'` / `manager_type IN (…)` | server-side label mapping | [register.py:746-750](scripts/queries/register.py:746) |
| `/api/v1/query5` (Heatmap) | parent | `manager_type` | direct `manager_type` on `holdings_v2` | passthrough | [register.py:778](scripts/queries/register.py:778) |
| `/api/v1/query7` (Fund Portfolio) | parent (1 fund) | `manager_type` | `MAX(h.manager_type)` on `holdings_v2` | passthrough into `stats.manager_type` | [register.py:918](scripts/queries/register.py:918), [register.py:963](scripts/queries/register.py:963) |
| `/api/v1/query14` (AUM vs Position) | parent | `manager_type`, `is_activist` | direct columns on `holdings_v2` | passthrough | [register.py:1121-1122](scripts/queries/register.py:1121) |
| `/api/v1/query16` (Fund-level register) | fund | `type` | none — name-based | `_classify_fund_type(fund_name)` | [register.py:1229](scripts/queries/register.py:1229), [register.py:1241](scripts/queries/register.py:1241), [register.py:1268](scripts/queries/register.py:1268) |
| `/api/v1/summary` | aggregate | `type_breakdown[].type` | `COALESCE(manager_type,'unknown')` on `holdings_v2` | passthrough | [register.py:1359](scripts/queries/register.py:1359), [register.py:1369](scripts/queries/register.py:1369) |
| `/api/v1/summary` | aggregate | passive_value / active_value | CASE on `entity_type` | server-side bucket | [register.py:1350-1352](scripts/queries/register.py:1350) |

### Cross-Ownership / Overlap surface

| Endpoint | Level | Response field | SQL source | Transformation | File:line |
|---|---|---|---|---|---|
| `/api/v1/cross_ownership` | parent | `type` | `MAX(h.manager_type)` on `holdings_v2` | passthrough | [cross.py:60](scripts/queries/cross.py:60), [cross.py:91](scripts/queries/cross.py:91), [cross.py:118](scripts/queries/cross.py:118) |
| `/api/v1/cross_ownership` (active_only) | parent | filter | `h.entity_type NOT IN ('passive')` | predicate | [cross.py:42](scripts/queries/cross.py:42) |
| `/api/v1/cross_ownership` | fund | `type` | NOT manager_type — falls back to `family_name` | `'type': row['family_name'] or 'fund'` (note: this overloads `type` to mean "family name", which is **not** active/passive — UI-visible bug) | [cross.py:215](scripts/queries/cross.py:215) |
| `/api/v1/cross_ownership` (active_only) | fund | filter | `COALESCE(fu.is_actively_managed, TRUE) = TRUE` on `fund_universe` | predicate (None treated as TRUE) | [cross.py:159](scripts/queries/cross.py:159) |
| `/api/v1/cross_ownership_top` | parent / fund | same as cross_ownership | (same code path) | (same) | [api_cross.py:67](scripts/api_cross.py:67) |
| `/api/v1/cross_ownership_fund_detail` | fund | `type` | `fu.is_actively_managed AS is_active` | label map: `is_active is True → 'active'`, `False → 'passive'`, `None → 'mixed'` | [cross.py:253](scripts/queries/cross.py:253), [cross.py:292-296](scripts/queries/cross.py:292) |
| `/api/v1/two_company_overlap` | parent | `manager_type` | `MAX(h.manager_type)` on `holdings_v2` | passthrough | [cross.py:336](scripts/queries/cross.py:336), [cross.py:380](scripts/queries/cross.py:380) |
| `/api/v1/two_company_overlap` | fund | `is_active`, `family_name` | `fu.is_actively_managed`, `fh.family_name` | `bool(is_active) if is_active is not None else None` (kept as `is_active` boolean field, NOT translated to active/passive label) | [cross.py:429](scripts/queries/cross.py:429), [cross.py:460](scripts/queries/cross.py:460) |
| `/api/v1/two_company_subject` | parent | `manager_type` | `MAX(h.manager_type)` on `holdings_v2` | passthrough | [cross.py:620](scripts/queries/cross.py:620), [cross.py:640](scripts/queries/cross.py:640) |
| `/api/v1/two_company_subject` | fund | `is_active`, `family_name` | `fu.is_actively_managed`, `fh.family_name` | same boolean form as two_company_overlap | [cross.py:674](scripts/queries/cross.py:674), [cross.py:699](scripts/queries/cross.py:699) |
| `/api/v1/overlap_institution_detail` | fund | `type` | `fu.is_actively_managed AS is_active` | label map: True→'active', False→'passive', None→'mixed' | [cross.py:533](scripts/queries/cross.py:533), [cross.py:554-558](scripts/queries/cross.py:554) |

### Flows / Trend surface

| Endpoint | Level | Response field | SQL source | Transformation | File:line |
|---|---|---|---|---|---|
| `/api/v1/flow_analysis` | parent | `manager_type` | `manager_type` on `holdings_v2` (precomputed `investor_flows` or live aggregation) | passthrough | [flows.py:340](scripts/queries/flows.py:340), [flows.py:496](scripts/queries/flows.py:496) |
| `/api/v1/flow_analysis` | fund | `manager_type` | unset (live path passes `mt = None` for fund level) | `None` literal | [flows.py:393](scripts/queries/flows.py:393), [flows.py:408](scripts/queries/flows.py:408), [flows.py:422](scripts/queries/flows.py:422) |
| `/api/v1/flow_analysis` (active_only fund) | fund | filter | `fu.is_actively_managed = true` | predicate | [flows.py:219](scripts/queries/flows.py:219), [flows.py:326](scripts/queries/flows.py:326) |
| `/api/v1/flow_analysis` qoq_charts | aggregate | bucket label | `COALESCE(h.manager_type,'unknown')` on `holdings_v2`; `if mt == 'passive'` | passthrough + Python branch | [flows.py:594](scripts/queries/flows.py:594), [flows.py:619](scripts/queries/flows.py:619) |
| `/api/v1/cohort_analysis` (active_only fund) | fund | filter | `fu.is_actively_managed = true` | predicate | [flows.py:219](scripts/queries/flows.py:219) |
| `/api/v1/cohort_analysis` econ_retention | parent | filter | `h.entity_type NOT IN ('passive','unknown')` | predicate | [flows.py:267](scripts/queries/flows.py:267), [flows.py:276](scripts/queries/flows.py:276) |
| `/api/v1/holder_momentum` | parent | `type` | `MAX(manager_type)` on `holdings_v2` | passthrough | [trend.py:141](scripts/queries/trend.py:141), [trend.py:275](scripts/queries/trend.py:275) |
| `/api/v1/holder_momentum` | fund (top-25 funds branch) | `type` | none — name-based | `_classify_fund_type(fn)` | [trend.py:84-88](scripts/queries/trend.py:84) |
| `/api/v1/holder_momentum` | fund (children of parent rows) | `type` | unset | hardcoded `'type': None` | [trend.py:295](scripts/queries/trend.py:295) |
| `/api/v1/holder_momentum` (active_only fund) | fund | filter | `fu.is_actively_managed = true` | predicate | [trend.py:43](scripts/queries/trend.py:43), [trend.py:335](scripts/queries/trend.py:335) |
| `/api/v1/ownership_trend_summary` | parent | aggregate | `entity_type NOT IN ('passive')` for `active_value`; `entity_type = 'passive'` for `passive_value` | server-side bucket | [trend.py:356-357](scripts/queries/trend.py:356) |
| `/api/v1/ownership_trend_summary` | fund | aggregate | `SUM(CASE WHEN fu.is_actively_managed = true …)` for active/passive | server-side bucket | [trend.py:341-343](scripts/queries/trend.py:341) |
| `/api/v1/ownership_trend_summary` (active_only) | parent or fund | filter | `entity_type IN (active_types)` | predicate | [trend.py:446](scripts/queries/trend.py:446), [trend.py:648](scripts/queries/trend.py:648) |
| `/api/v1/peer_rotation` / `/peer_rotation_detail` | parent or fund | (rows from `peer_rotation_flows`) | reads `peer_rotation_flows.entity_type` (precomputed by `compute_peer_rotation.py`) | passthrough | (PR-1b backfilled this; client reads it canonical now) |
| `/api/v1/portfolio_context` (Conviction) | parent | `type` | `MAX(manager_type) as mtype` on `holdings_v2` | `row_type = h_row.get('mtype') or 'unknown'` | [fund.py:104](scripts/queries/fund.py:104), [fund.py:279](scripts/queries/fund.py:279) |
| `/api/v1/portfolio_context` (Conviction) | fund (top-25 holders branch) | `type` | `MAX(fu.is_actively_managed) as is_active` on `fund_universe` | `row_type = 'active' if h_row.get('is_active') else 'passive'` (None → 'passive' by Python truthiness) | [fund.py:93](scripts/queries/fund.py:93), [fund.py:277](scripts/queries/fund.py:277) |
| `/api/v1/portfolio_context` (Conviction) | fund (N-PORT children of a parent) | `type` | `COALESCE(MAX(CAST(fu.is_actively_managed AS INTEGER)), 0)` on `fund_universe` | `'active' if fund_is_active.get(fund_name, False) else 'passive'` | [fund.py:338](scripts/queries/fund.py:338), [fund.py:344](scripts/queries/fund.py:344), [fund.py:365](scripts/queries/fund.py:365), [fund.py:385](scripts/queries/fund.py:385) |

### Fund / Market / Entities surface

| Endpoint | Level | Response field | SQL source | Transformation | File:line |
|---|---|---|---|---|---|
| `/api/v1/fund_portfolio_managers` | parent | `manager_type` | `MAX(manager_type)` on `holdings_v2` | passthrough; also filters `entity_type NOT IN ('passive')` | [api_fund.py](scripts/api_fund.py) lines 38-50 |
| `/api/v1/sector_summary` | aggregate | manager-type buckets | `manager_type` from `holdings_v2`; AUM bucketed by manager_type | server-side aggregation | [market.py:149](scripts/queries/market.py:149), [market.py:160](scripts/queries/market.py:160) |
| `/api/v1/sector_flows` (active filter) | parent / fund | filter | `entity_type IN ('active','hedge_fund','activist')` (parent) or fund_universe.is_actively_managed (fund) | predicate | [market.py:373](scripts/queries/market.py:373), [market.py:498](scripts/queries/market.py:498) |
| `/api/v1/short_analysis.nport_detail` | fund | `type`, `is_active` | `MAX(CAST(fu.is_actively_managed AS INTEGER)) as is_active` + `_classify_fund_type(fund_name)` | both: `is_active` boolean as int + name-based `type` label | [market.py:642](scripts/queries/market.py:642), [market.py:668](scripts/queries/market.py:668) |
| `/api/v1/short_analysis.nport_by_fund` | fund | `type`, `is_active` | `MAX(CAST(fu.is_actively_managed AS INTEGER)) as is_active` + `_classify_fund_type(fund_name)` | same | [market.py:679](scripts/queries/market.py:679), [market.py:691](scripts/queries/market.py:691) |
| `/api/v1/short_analysis.cross_ref` | parent | `type`, `manager_type` | `MAX(manager_type) as manager_type` on `holdings_v2` | `'type': lrow.get('manager_type') or 'unknown'` | [market.py:719](scripts/queries/market.py:719), [market.py:770](scripts/queries/market.py:770) |
| `/api/v1/short_analysis.short_only_funds` | fund | `type`, `is_active` | `MAX(CAST(fu.is_actively_managed AS INTEGER)) as is_active` + `_classify_fund_type(fund_name)` | same | [market.py:795](scripts/queries/market.py:795), [market.py:826](scripts/queries/market.py:826) |
| `/api/v1/smart_money` | parent | `manager_type` | `MAX(manager_type)` on `holdings_v2` | passthrough | [market.py:1054](scripts/queries/market.py:1054) |
| `/api/v1/entity_search` | parent | `entity_type`, `classification` | direct columns on `entity_current` | passthrough | [entities.py:14-26](scripts/queries/entities.py:14) |
| `/api/v1/entity_graph` (institution / sub_adviser nodes) | parent | `classification` | `entity_current.classification` | passthrough | [entities.py:14](scripts/queries/entities.py:14), [entities.py:473](scripts/queries/entities.py:473), [entities.py:531](scripts/queries/entities.py:531) |
| `/api/v1/entity_market_summary` / `institution_hierarchy` | parent | (no classification field emitted) | — | — | (audited; no classification field) |

---

## 3. Query module audit

Grep of every classification-column read in `scripts/queries/` and `scripts/api_*.py`. Grouped by file.

### `scripts/queries/common.py`

- `_classify_fund_type(fund_name)` definition: [common.py:292-320](scripts/queries/common.py:292). Hardcoded keyword sweep — `INDEX|ETF|MSCI|FTSE|STOXX|NIKKEI|TOTAL STOCK|...|S&P 500|RUSSELL 1000|...` → `'passive'`, else `'active'`. No path returns `'mixed'`. Defaults to `'active'` when fund_name is empty.
- `get_13f_children`: SELECT `COALESCE(h.manager_type,'unknown') as type` from `holdings_v2`. [common.py:681](scripts/queries/common.py:681), [common.py:697](scripts/queries/common.py:697). Used by Register / Conviction children.

### `scripts/queries/register.py`

- query1 (Register): `manager_type` × 2 reads ([register.py:54](scripts/queries/register.py:54), [register.py:127](scripts/queries/register.py:127), [register.py:235](scripts/queries/register.py:235)); N-PORT children typed via `_classify_fund_type` ([register.py:164](scripts/queries/register.py:164)).
- query2 (Holder Changes): `manager_type` reads at [register.py:289](scripts/queries/register.py:289), [register.py:298](scripts/queries/register.py:298), [register.py:309](scripts/queries/register.py:309). Parent summary row emits `'type': None` for N-PORT children at [register.py:387](scripts/queries/register.py:387).
- query3 (Conviction list): `manager_type` at [register.py:464](scripts/queries/register.py:464), [register.py:511](scripts/queries/register.py:511); `entity_type IN (...)` filter at [register.py:472](scripts/queries/register.py:472).
- query4 (Active vs Passive split): CASE on both `entity_type` and `manager_type` at [register.py:746-750](scripts/queries/register.py:746). Server emits human-readable category labels.
- query5 (Heatmap): `manager_type` at [register.py:778](scripts/queries/register.py:778), [register.py:785](scripts/queries/register.py:785).
- query7 (Fund Portfolio stats): `MAX(manager_type)` at [register.py:918](scripts/queries/register.py:918), emitted as `stats.manager_type` at [register.py:963](scripts/queries/register.py:963).
- query10 (Position Changes): `manager_type` at [register.py:1045](scripts/queries/register.py:1045), [register.py:1057](scripts/queries/register.py:1057).
- query14 (AUM vs Position): `manager_type` and `is_activist` at [register.py:1121-1122](scripts/queries/register.py:1121).
- query15 (DB stats): `with_manager_type` coverage at [register.py:1170](scripts/queries/register.py:1170).
- query16 (Fund-level register): `_classify_fund_type` at [register.py:1229](scripts/queries/register.py:1229), [register.py:1268](scripts/queries/register.py:1268). **Does not read `fund_universe.fund_strategy` or `is_actively_managed`** despite operating exclusively on fund_holdings_v2.
- _get_summary_impl: `manager_type` aggregation at [register.py:1359](scripts/queries/register.py:1359); active/passive split via `entity_type` at [register.py:1350-1352](scripts/queries/register.py:1350).

### `scripts/queries/cross.py`

- `_cross_ownership_query` parent: `MAX(h.manager_type) as type` at [cross.py:60](scripts/queries/cross.py:60), [cross.py:91](scripts/queries/cross.py:91); active_only filter on `entity_type NOT IN ('passive')` at [cross.py:42](scripts/queries/cross.py:42). Emits `row['type']` at [cross.py:118](scripts/queries/cross.py:118).
- `_cross_ownership_fund_query`: active_only filter on `COALESCE(fu.is_actively_managed, TRUE) = TRUE` at [cross.py:159](scripts/queries/cross.py:159). **Critical bug:** emits `'type': row['family_name'] or 'fund'` at [cross.py:215](scripts/queries/cross.py:215) — overloads the `type` field with family name (e.g. `'Vanguard'`, `'BlackRock'`) instead of an active/passive label. Frontend sees `type='Vanguard'` and renders an unknown badge.
- `get_cross_ownership_fund_detail`: `fu.is_actively_managed AS is_active` at [cross.py:253](scripts/queries/cross.py:253). Label map at [cross.py:292-296](scripts/queries/cross.py:292): `True→'active'`, `False→'passive'`, `None→'mixed'`.
- `get_two_company_overlap`: parent `MAX(h.manager_type)` at [cross.py:336](scripts/queries/cross.py:336); fund `fu.is_actively_managed` at [cross.py:429](scripts/queries/cross.py:429). Fund response keeps `is_active` as a boolean (or None) at [cross.py:460](scripts/queries/cross.py:460) — does not derive a label.
- `get_overlap_institution_detail`: `fu.is_actively_managed` at [cross.py:533](scripts/queries/cross.py:533); same label map as `cross_ownership_fund_detail` at [cross.py:554-558](scripts/queries/cross.py:554).
- `get_two_company_subject`: parent `manager_type` at [cross.py:620](scripts/queries/cross.py:620); fund `is_actively_managed` at [cross.py:674](scripts/queries/cross.py:674), boolean response at [cross.py:699](scripts/queries/cross.py:699).

### `scripts/queries/fund.py` (Conviction / portfolio_context)

- top-25 holders branch (level=fund): SELECT `MAX(fu.is_actively_managed) as is_active` at [fund.py:93](scripts/queries/fund.py:93). `active_only` filter at [fund.py:90](scripts/queries/fund.py:90).
- top-25 holders branch (level=parent): SELECT `MAX(manager_type) as mtype` at [fund.py:104](scripts/queries/fund.py:104).
- Row-type assignment at [fund.py:276-279](scripts/queries/fund.py:276): `if level == 'fund': row_type = 'active' if h_row.get('is_active') else 'passive'`. **None becomes 'passive' here** (Python truthiness of None is False).
- N-PORT children (parent-mode children): SELECT `COALESCE(MAX(CAST(fu.is_actively_managed AS INTEGER)), 0) as is_active` at [fund.py:338](scripts/queries/fund.py:338); same `True/None→passive` collapse at [fund.py:365](scripts/queries/fund.py:365), [fund.py:385](scripts/queries/fund.py:385).

### `scripts/queries/flows.py`

- `_compute_flows_live`: `MAX(manager_type) as manager_type` at [flows.py:340](scripts/queries/flows.py:340), [flows.py:347](scripts/queries/flows.py:347). Fund-level path passes `mt = None` ([flows.py:393](scripts/queries/flows.py:393), [flows.py:408](scripts/queries/flows.py:408), [flows.py:422](scripts/queries/flows.py:422)) and emits `'manager_type': mt or ''`.
- Precomputed fallback: `manager_type` selected from `investor_flows` at [flows.py:496](scripts/queries/flows.py:496).
- `cohort_analysis`: fund branch filters via `fu.is_actively_managed = true` at [flows.py:219](scripts/queries/flows.py:219); parent econ-retention filters via `entity_type NOT IN ('passive','unknown')` at [flows.py:267](scripts/queries/flows.py:267), [flows.py:276](scripts/queries/flows.py:276).
- `flow_analysis` qoq_charts: `COALESCE(h.manager_type,'unknown') as mtype` at [flows.py:594](scripts/queries/flows.py:594); branch on `mt == 'passive'` at [flows.py:619](scripts/queries/flows.py:619).

### `scripts/queries/trend.py`

- `holder_momentum` fund branch: `_classify_fund_type(fn)` at [trend.py:84](scripts/queries/trend.py:84); active_only filter on `fu.is_actively_managed = true` at [trend.py:43](scripts/queries/trend.py:43), [trend.py:335](scripts/queries/trend.py:335).
- `holder_momentum` parent branch: `MAX(manager_type) as type` at [trend.py:141](scripts/queries/trend.py:141), passthrough at [trend.py:275](scripts/queries/trend.py:275). N-PORT child rows hardcoded to `'type': None` at [trend.py:295](scripts/queries/trend.py:295).
- `ownership_trend_summary`: parent uses `entity_type NOT IN ('passive')` / `= 'passive'` at [trend.py:356-357](scripts/queries/trend.py:356); fund uses `fu.is_actively_managed = true` at [trend.py:341-343](scripts/queries/trend.py:341); active_only predicate uses `entity_type IN (active_types)` at [trend.py:446](scripts/queries/trend.py:446), [trend.py:648](scripts/queries/trend.py:648).

### `scripts/queries/market.py`

- `sector_summary`: AUM-by-`manager_type` aggregation at [market.py:149-152](scripts/queries/market.py:149); response field `type` at [market.py:160](scripts/queries/market.py:160).
- `sector_flows` / `sector_flow_movers`: active filter `entity_type IN ('active','hedge_fund','activist')` at [market.py:373](scripts/queries/market.py:373), [market.py:498](scripts/queries/market.py:498).
- `short_analysis.nport_detail`: `CAST(fu.is_actively_managed AS INTEGER) as is_active` at [market.py:642](scripts/queries/market.py:642); response also adds name-based `type` via `_classify_fund_type` at [market.py:668](scripts/queries/market.py:668). Both fields emitted.
- `short_analysis.nport_by_fund`: `MAX(CAST(fu.is_actively_managed AS INTEGER)) as is_active` at [market.py:679](scripts/queries/market.py:679); name-based `type` at [market.py:691](scripts/queries/market.py:691).
- `short_analysis.cross_ref`: `MAX(manager_type) as manager_type` at [market.py:719](scripts/queries/market.py:719); response `'type': lrow.get('manager_type') or 'unknown'` at [market.py:770](scripts/queries/market.py:770).
- `short_analysis.short_only_funds`: `MAX(CAST(fu.is_actively_managed AS INTEGER)) as is_active` at [market.py:795](scripts/queries/market.py:795); response `_classify_fund_type` at [market.py:826](scripts/queries/market.py:826). **Both signals are emitted on the same row but never reconciled — they can disagree** (e.g. fund_universe says active, name keyword sweep says passive).
- `smart_money`: `MAX(manager_type) as manager_type` at [market.py:1054](scripts/queries/market.py:1054).

### `scripts/queries/entities.py`

- `search_entity_parents`: SELECT `entity_type, classification` from `entity_current` at [entities.py:14](scripts/queries/entities.py:14). Emits both as response fields at [entities.py:23-26](scripts/queries/entities.py:23).
- `get_entity_by_id`: same columns at [entities.py:35](scripts/queries/entities.py:35), emitted at [entities.py:42-46](scripts/queries/entities.py:42).
- `get_entity_sub_advisers`: `classification` from `entity_current` at [entities.py:321](scripts/queries/entities.py:321), emitted at [entities.py:335](scripts/queries/entities.py:335).
- `_eg_node_institution`, `_eg_node_sub_adviser`: copy `classification` into vis.js node payload at [entities.py:473](scripts/queries/entities.py:473), [entities.py:531](scripts/queries/entities.py:531).

### `scripts/api_fund.py`

- `/fund_portfolio_managers`: `MAX(manager_type) as manager_type` from `holdings_v2`; filter `entity_type NOT IN ('passive')`. Lines 38-50 of the file.

---

## 4. Conviction `is_active=None` — root cause trace

The PR-1a spot-check claimed: *"Conviction tab at level=fund returns `is_active=None` for all rows even though `type='passive'` resolves correctly."*

### What actually happens

1. **`/api/v1/portfolio_context?level=fund` does not emit `is_active` in its response at all.** Walking the row builder ([fund.py:281-299](scripts/queries/fund.py:281), [fund.py:362-401](scripts/queries/fund.py:362)) the keys returned are: `rank, institution, type, value, subject_sector_pct, vs_spx, conviction_score, sector_rank, co_rank_in_sector, industry_rank, top3, diversity, unk_pct, etf_pct, level, is_parent, child_count, parent_name`. No `is_active`.

2. **The `type` field at level=fund is computed from `is_actively_managed` with a buggy None-collapse.**
   - SQL ([fund.py:93](scripts/queries/fund.py:93)): `MAX(fu.is_actively_managed) as is_active` — left-joined to `fund_universe`. Funds missing from `fund_universe` get `is_active = None`.
   - Python ([fund.py:277](scripts/queries/fund.py:277)): `row_type = 'active' if h_row.get('is_active') else 'passive'`. Because Python's truthiness treats `None` as False, **any fund with no `fund_universe` row collapses to `type='passive'`** — even though the canonical answer is "unknown" or, post-PR-1a, `'mixed'` per the convention used in `get_cross_ownership_fund_detail`.
   - Same collapse on N-PORT children of a parent row at [fund.py:344](scripts/queries/fund.py:344) → [fund.py:365](scripts/queries/fund.py:365), [fund.py:385](scripts/queries/fund.py:385).

3. **Where the user's `is_active=None` observation likely came from:** the *intermediate* Python dict in `_cross_ownership_fund_detail` at [cross.py:274](scripts/queries/cross.py:274) carries `'is_active': is_active` — but the final response only emits the `type` label, not `is_active`. Or the user inspected the SQL query result rather than the JSON envelope. Either way the underlying signal (`fund_universe.is_actively_managed` returning None for funds not in fund_universe) is real.

### What PR-1a actually changed

Per the COMPLETED row in [ROADMAP.md:88](ROADMAP.md): *"`fund_universe.is_actively_managed IS NULL` count dropped from 658 → 0, neutralising the `cross.py:159` `COALESCE(…, TRUE)` SYN leak for these series."*

After PR-1a, every series in `fund_universe` has `is_actively_managed` populated. **But `fund_holdings_v2` can still reference a `series_id` not present in `fund_universe`** (e.g. funds parsed from N-PORT but never canonicalized in fund_universe — in particular the 3,184 `series_id='UNKNOWN'` orphan rows from PR-1a Phase 3, or any newer series_id that hasn't yet been added to fund_universe). For those rows the LEFT JOIN at [fund.py:95](scripts/queries/fund.py:95) and [fund.py:340](scripts/queries/fund.py:340) returns `is_active=None`, which collapses to `'passive'` via the bug above.

### The actual bug at fund.py:277

```python
if level == 'fund':
    row_type = 'active' if h_row.get('is_active') else 'passive'
```

This is doing two things wrong:

1. **Reading from `is_actively_managed` instead of `fund_strategy`.** The canonical column is `fund_universe.fund_strategy ∈ {equity, index, balanced, multi_asset, bond_or_other, excluded, final_filing}`. The display layer collapses this 7-value taxonomy to a 2-value (`active`/`passive`) display via the legacy `is_actively_managed` derived column. Post-PR-1a/1b, the canonical value lives at `fund_strategy`; the display layer should read it directly and apply its own collapse.

2. **Mapping None → 'passive' silently.** The convention used elsewhere in the same module's sibling endpoints ([cross.py:292-296](scripts/queries/cross.py:292), [cross.py:554-558](scripts/queries/cross.py:554)) maps `None → 'mixed'`. Conviction is the only place that maps `None → 'passive'`.

PR-1d should fix both. Either:
- (A) keep reading `is_actively_managed` and just fix the None-collapse to match the `'mixed'` convention, **or**
- (B) read `fund_strategy` directly and adopt a single label map `{equity, balanced, multi_asset, bond_or_other → 'active'; index → 'passive'; excluded, final_filing → 'mixed'/'unknown'}` consistently across all fund-level endpoints.

(The choice between A and B is a decision for the user — see §7.)

---

## 5. `type` field — full label-map audit

### Fund-level paths

There are **three independent fund-level type paths** with three different label maps:

**Path 1 — `is_actively_managed`-driven, two-bucket (active/passive)**
- Conviction (portfolio_context fund branch + parent-children): None silently collapses to `'passive'`. [fund.py:277](scripts/queries/fund.py:277), [fund.py:365](scripts/queries/fund.py:365), [fund.py:385](scripts/queries/fund.py:385).

**Path 2 — `is_actively_managed`-driven, three-bucket (active/passive/mixed)**
- `get_cross_ownership_fund_detail`. [cross.py:292-296](scripts/queries/cross.py:292).
- `get_overlap_institution_detail`. [cross.py:554-558](scripts/queries/cross.py:554).

**Path 3 — name-based via `_classify_fund_type`, two-bucket (active/passive only — never None or mixed)**
- `query1` Register N-PORT children. [register.py:164](scripts/queries/register.py:164).
- `query16` fund-level register. [register.py:1229](scripts/queries/register.py:1229), [register.py:1241](scripts/queries/register.py:1241).
- `holder_momentum` level=fund. [trend.py:84](scripts/queries/trend.py:84).
- `short_analysis.nport_detail` / `nport_by_fund` / `short_only_funds`. [market.py:668](scripts/queries/market.py:668), [market.py:691](scripts/queries/market.py:691), [market.py:826](scripts/queries/market.py:826).

**Path 4 — direct field name overload (NOT a label map)**
- `_cross_ownership_fund_query` emits `'type': family_name or 'fund'` — overloads `type` with the fund family name. [cross.py:215](scripts/queries/cross.py:215). **This is a UI-visible bug:** Cross-Ownership level=fund renders a Vanguard / BlackRock / etc. badge in the type column instead of an active/passive label.

**Path 5 — None hardcoded**
- `holder_momentum` parent-mode N-PORT children. [trend.py:295](scripts/queries/trend.py:295). Frontend renders `null` / `—`.

### Parent-level paths

Two independent parent-level type paths:

**Path A — `manager_type` direct passthrough**
- `query1`, `query2`, `query5`, `query7`, `query10`, `query14`, `query16`, `cross_ownership` parent, `two_company_overlap` parent, `two_company_subject` parent, `flow_analysis` parent (precomputed and live), `holder_momentum` parent, `portfolio_context` parent, `smart_money`, `short_analysis.cross_ref`, `fund_portfolio_managers`, `_get_summary_impl.type_breakdown`. All read `MAX(manager_type)` from `holdings_v2` directly and emit it as `type` or `manager_type` with `COALESCE(…, 'unknown')` defaulting.

**Path B — `entity_type`-driven label**
- `query4` (`'Passive (Index)' / 'Activist' / 'Active' / 'Other/Unknown'`). [register.py:746-750](scripts/queries/register.py:746).
- `_get_summary_impl` active/passive split. [register.py:1350-1352](scripts/queries/register.py:1350).
- `ownership_trend_summary` parent. [trend.py:356-357](scripts/queries/trend.py:356).
- `cohort_analysis` parent econ_retention filter. [flows.py:267](scripts/queries/flows.py:267).
- `flow_analysis` qoq_charts. [flows.py:619](scripts/queries/flows.py:619).
- `cross_ownership` `active_only`. [cross.py:42](scripts/queries/cross.py:42).
- `query3` `entity_type IN (...)`. [register.py:472](scripts/queries/register.py:472).

### Inconsistency: `manager_type` vs `entity_type`

The two parent-level columns are not identical:

| `manager_type` values | `entity_type` values |
|---|---|
| `active`, `passive`, `mixed`, `hedge_fund`, `activist`, `quantitative`, `unknown`, NULL | `active`, `passive`, `hedge_fund`, `activist`, `quantitative`, `unknown` (set via `entity_classification_history`) |

`query4` ([register.py:746-750](scripts/queries/register.py:746)) buckets into 4 categories using **both** columns in a single CASE: passive comes from `entity_type='passive'` while active comes from `manager_type IN (...)`. If the two columns disagree on a row (e.g. `entity_type='active'` but `manager_type='passive'`), that row falls into "Other/Unknown" instead of either bucket — silent data drop.

---

## 6. Cross-reference with PR-1a spot-check observations

The PR-1a closing notes flagged two anomalies:

### Anomaly 1 — `type` display reads derived columns

> *"API responses include a `type` field showing values like `passive` / `active` / `mixed`. These are NOT read from `fund_strategy` directly. They are derived from `is_actively_managed` (fund-level) or `manager_type` (parent-level), which are themselves derivatives of the canonical columns."*

**Confirmed.** No endpoint reads `fund_strategy` (fund) or `entity_classification_history.classification` (parent). The closest direct read is `entities.py` reading `entity_current.classification` for the entity graph and entity search dropdown, but this is not used by any of the analytical tabs (Register, Conviction, Flow, Cross-Ownership, etc.).

### Anomaly 2 — Conviction `is_active=None` for all fund rows

> *"Conviction tab at level=fund returns is_active=None for all rows even though type='passive' resolves correctly."*

**Partially confirmed, with refinement.** The `/api/v1/portfolio_context` response does not actually emit `is_active`; only `type` is emitted. But the underlying issue is real: for funds whose `series_id` is absent from `fund_universe` (or where `is_actively_managed` is otherwise NULL), the LEFT JOIN at [fund.py:95](scripts/queries/fund.py:95) yields `None`, which the Python row builder at [fund.py:277](scripts/queries/fund.py:277) silently maps to `'passive'`. This is the bug. Post-PR-1a, `fund_universe` rows are fully populated, so this should now only fire for series in `fund_holdings_v2` not present in `fund_universe` (the `series_id='UNKNOWN'` orphan cohort and any new series not yet canonicalized).

### Anomaly 3 — Cross-Ownership level=fund emits family name as `type`

Surfaced during this audit, **not** in the PR-1a notes. [cross.py:215](scripts/queries/cross.py:215) sets `'type': row['family_name'] or 'fund'`, which means fund-level Cross-Ownership rows show e.g. `type='Vanguard'` instead of `type='passive'`. Almost certainly a copy-paste bug that nobody noticed because the parent path uses `manager_type` and there's no shared schema test.

### Anomaly 4 — Holder Momentum parent-mode children emit `type=None`

[trend.py:295](scripts/queries/trend.py:295) hardcodes `'type': None` for fund children of parent rows in Holder Momentum. Probably intentional to avoid mis-typing N-PORT children with the parent's `manager_type`, but the result is a blank column in the UI.

### Anomaly 5 — `manager_type` vs `entity_type` divergence in `query4`

Surfaced during this audit. Active/passive split bucketing reads from two different columns; rows where they disagree silently fall to "Other/Unknown".

### Anomaly 6 — `short_only_funds` emits two contradictory signals

[market.py:826](scripts/queries/market.py:826) emits `_classify_fund_type` (name-based) for `type` while also returning `is_active` from `fund_universe.is_actively_managed`. The two can disagree. Frontend probably reads only `type` and ignores `is_active`, but the contract is broken.

---

## 7. Decisions pending for PR-1d

Before PR-1d (display-fix) can be drafted, the user needs to make these decisions. Each line is a decision, not a recommendation.

### D1. Single canonical source for fund-level `type`

Choose one:
- **(A)** Read `fund_universe.fund_strategy` directly and apply a single Python label map across every fund endpoint. Drops `is_actively_managed` from all read paths. Cleanest long-term; aligns with PR-3 (drop `is_actively_managed`).
- **(B)** Keep reading `is_actively_managed` everywhere and just fix the inconsistencies (None-collapse rule, family-name overload, name-keyword fallback). Smaller PR; defers the canonical cutover until PR-3.

### D2. Label map for fund-level `type`

If (A) above: define the map. Strawman:
- `equity, balanced, multi_asset, bond_or_other` → `'active'`
- `index` → `'passive'`
- `excluded, final_filing` → `'excluded'` (new bucket) or `'unknown'`
- NULL series_id (no fund_universe row) → `'unknown'`

If (B): standardize the existing `is_actively_managed` collapse:
- `True` → `'active'`
- `False` → `'passive'`
- `None` → `'mixed'` (matches existing cross.py convention) or `'unknown'`

### D3. Replace `_classify_fund_type` with a DB-backed source

Five endpoints use the name-keyword sweep ([common.py:292-320](scripts/queries/common.py:292)). Choose:
- **(A)** Replace every call site with a fund_universe / fund_strategy lookup. Requires an extra JOIN where the current code only queries holdings_v2.
- **(B)** Keep `_classify_fund_type` only for fund_name-only paths where no series_id is reachable, and replace it everywhere a series_id is available.
- **(C)** Delete `_classify_fund_type` entirely and require a series_id at every call site.

### D4. Parent-level: which column wins, `manager_type` or `entity_type`?

The split bucketing in `query4` ([register.py:746-750](scripts/queries/register.py:746)) and the `cohort_analysis` filter in [flows.py:267](scripts/queries/flows.py:267) read different columns. Decide:
- **(A)** Always read `entity_type` (the canonical one set by `entity_classification_history`).
- **(B)** Always read `manager_type` (the legacy one).
- **(C)** Define a precedence (e.g. prefer `entity_type` when populated, fall back to `manager_type`).

(This decision sits one level above this audit's scope — institution-level display audit — but `query4` and the active/passive UI on the Conviction tab and Summary card depend on it. PR-1d may need to sketch a position even if the full institution audit comes later.)

### D5. Cross-Ownership level=fund `type` field

The current emission is `family_name or 'fund'` ([cross.py:215](scripts/queries/cross.py:215)). Decide whether PR-1d:
- **(A)** Replaces it with the canonical fund-level type label.
- **(B)** Keeps `family_name` but renames the field to `family` and adds a separate `type` field.
- **(C)** Both (A) and a separate `family_name` field.

### D6. Holder Momentum parent-mode children `type=None`

[trend.py:295](scripts/queries/trend.py:295) deliberately hardcodes None. Decide whether PR-1d:
- **(A)** Looks up the canonical fund-strategy label for these children (one extra JOIN).
- **(B)** Leaves it as-is and accepts the blank column in the UI.

### D7. `short_analysis` two-signal contract

[market.py:642+668](scripts/queries/market.py:642), [market.py:679+691](scripts/queries/market.py:679), [market.py:795+826](scripts/queries/market.py:795) all emit both `is_active` (from `is_actively_managed`) and `type` (from `_classify_fund_type`) on the same row. Decide whether PR-1d:
- **(A)** Picks one signal (canonical `fund_strategy` per D1) and removes the other from the response.
- **(B)** Keeps both but documents which one the UI consumes.

### D8. Conviction-tab schema vs the user's observation

The PR-1a spot-check claimed `is_active=None` is in the Conviction response, but the audit shows `is_active` is not actually a response field on `/api/v1/portfolio_context`. Decide whether PR-1d:
- **(A)** Adds `is_active` (or `fund_strategy`) to the Conviction response so the UI can debug-render it.
- **(B)** Treats the user's observation as an artefact of inspecting a different endpoint and proceeds without the field.

---

## 8. Out-of-scope follow-ups identified

These surfaced during the audit but belong to later PRs per the PR-1c spec.

- **PR-1d (display-fix):** the actual fixes once D1-D8 are decided.
- **PR-1e (rename `index` → `passive`):** still listed as PR-1c in [ROADMAP.md:22](ROADMAP.md) — needs a header bump after this PR lands. Out of scope for this audit.
- **PR-2 (extend `INDEX_PATTERNS`):** the name-based classifier in `_classify_fund_type` ([common.py:299-318](scripts/queries/common.py:299)) is extremely narrow — only 14 keywords + 11 index combos. Coverage gaps will surface in any name-based fallback path until PR-2 lands.
- **PR-3 (drop `is_actively_managed`, `fund_category`):** depends on D1=(A) here.
- **PR-4 (rename `equity` → `active`):** out of scope.
- **Institution-level display audit (entity_type, manager_type):** mentioned in D4 above; full audit deferred to a separate sequence.

---

## 9. Schema sanity notes

Verified during the audit:
- `entity_current` is a VIEW (per memory). Reads in `entities.py` are correct.
- `fund_universe.is_actively_managed` is BOOLEAN and post-PR-1a is non-NULL for every row in `fund_universe`. The remaining `is_active=None` failure mode comes from `series_id` values in `fund_holdings_v2` that have no `fund_universe` row.
- `holdings_v2.manager_type` and `holdings_v2.entity_type` are independent columns — both are populated by upstream entity / classification pipelines. They overlap on values (`active`, `passive`, etc.) but are not redundant. `entity_type` is canonically derived from `entity_classification_history.classification`; `manager_type` is the legacy column kept for compatibility.
- `fund_holdings_v2.fund_strategy` exists post-PR-1a and matches `fund_universe.fund_strategy` for all rows that have a `fund_universe` join (5,471,830 rows reconciled in PR-1a Phase 3). Not read by any API/queries module.
- `peer_rotation_flows.entity_type` — at fund level, post-PR-1b, takes its values from `fund_universe.fund_strategy` (`equity / index / excluded / balanced / multi_asset / bond_or_other / final_filing`), not from `is_actively_managed`. This is the only place in the runtime where the canonical taxonomy reaches the API; the `peer_rotation` endpoints pass it through unchanged.
