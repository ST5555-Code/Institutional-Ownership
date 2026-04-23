# UI Audit Triage — ui-audit-01

_Generated: 2026-04-22. Read-only discovery pass. Tab list reflects live React registry at HEAD 9d26eb1._

**Tabs enumerated:** 12
**Endpoints walked:** 26 unique (28 fetch sites across tabs + shared shell)
**queries.py functions profiled:** 21 (plus 4 inline-SQL endpoints)

**DB used for timings:** `data/13f.duckdb` (prod), opened read-only.
**Representative args:** ticker=`AAPL` (fallback `MSFT` where AAPL 500s), quarter=`2025Q4` (MAX), rollup_type=`economic_control_v1`, entity_id=`2` (BlackRock / iShares), period=`1Q`, peers=`AAPL,MSFT,GOOGL,AMZN,META`.

> ⚠️ **Headline finding — block before other triage:** on the current prod DB, every `is_latest=TRUE` row for `quarter='2025Q4'` has `ticker IS NULL`. The real 3.2M rows with tickers are marked `is_latest=FALSE`. Every endpoint whose SQL filters `WHERE is_latest=TRUE AND quarter=LQ` — which is most of them — returns empty or 500s on production data today. Recent commits (9d26eb1, a7abb79) backfill `is_latest=TRUE` on the CI fixture only; the prod DB was not updated. Until this is resolved, the cold/warm numbers below for any 2025Q4 ticker query reflect the empty fast-path, not realistic steady-state cost.
>
> See Cross-tab → Technical anomalies for the full list of affected endpoints and the `query1()` NoneType crash that blocks Register + Entity Graph.

---

## Sector Rotation

**React component:** [web/react-app/src/components/tabs/SectorRotationTab.tsx](web/react-app/src/components/tabs/SectorRotationTab.tsx)

**Endpoints hit:**

| Endpoint | Router module | Handler |
|---|---|---|
| `/api/v1/sector_flows` | [scripts/api_market.py](scripts/api_market.py) | `api_sector_flows()` |
| `/api/v1/sector_flow_movers` | [scripts/api_market.py](scripts/api_market.py) | `api_sector_flow_movers()` |

**queries.py functions called:**

| Function | Line | Tables | Notes |
|---|---|---|---|
| `get_sector_flows()` | [L2083](scripts/queries.py:2083) | `holdings_v2` × `securities`/`market_data`, multi-quarter self-join | Global: no ticker, no rollup_type. Groups every holding by GICS sector across quarters. |
| `get_sector_flow_movers()` | [L2222](scripts/queries.py:2222) | `holdings_v2` × `securities`, 2-quarter diff | `rollup_type`-aware. Per-sector top movers between two quarters. |

**Query cost:**

| Function | Cold (ms) | Warm (ms) | Rows | Precomputed source? |
|---|---|---|---|---|
| `get_sector_flows()` | 725 | 792 | 1 | No |
| `get_sector_flow_movers()` | 201 | 201 | 1 | No |

**Technical notes:** Warm≈cold on both — DuckDB has no row cache for these; each call replays the full scan. `sector_flows` is a global view that doesn't vary by user and is quarter-refreshable → strong precompute target. `sector_flow_movers` is filtered by sector+quarter pair, smaller but still 200 ms every call.

**Bugs (visual):**
_[Serge]_

**Completeness gaps:**
_[Serge]_

**Precompute candidates:**

| Function | Tag | Rationale |
|---|---|---|
| `get_sector_flows()` | table | 725 ms full scan, global (no ticker), quarter-refreshable. Mirror the `investor_flows` pattern. |
| `get_sector_flow_movers()` | table | 200 ms per call; tuple-keyed on (q_from, q_to, sector, rollup_type) — materialize once per quarter ingest. |

---

## Entity Graph

**React component:** [web/react-app/src/components/tabs/EntityGraphTab.tsx](web/react-app/src/components/tabs/EntityGraphTab.tsx)

**Endpoints hit:**

| Endpoint | Router module | Handler |
|---|---|---|
| `/api/v1/entity_search` | [scripts/api_entities.py](scripts/api_entities.py) | `api_entity_search()` |
| `/api/v1/entity_market_summary` | [scripts/api_entities.py](scripts/api_entities.py) | `api_entity_market_summary()` |
| `/api/v1/query1` | [scripts/api_register.py](scripts/api_register.py) | `api_query1()` → `_execute_query(1)` |
| `/api/v1/entity_graph` | [scripts/api_entities.py](scripts/api_entities.py) | `api_entity_graph()` |
| `/api/v1/entity_children` | [scripts/api_entities.py](scripts/api_entities.py) | `api_entity_children()` (`level=fund`) |

**queries.py functions called:**

| Function | Line | Tables | Notes |
|---|---|---|---|
| `search_entity_parents()` | [L4937](scripts/queries.py:4937) | `entity_current`, `entity_aliases` | Takes a shared `con`. Type-ahead prefix search, rollup parents only. |
| `get_market_summary()` | [L4375](scripts/queries.py:4375) | `holdings_v2` × `entity_current` / `entity_rollup_history` | Top-N global. Independent of ticker. `rollup_type`-aware. |
| `query1()` | [L795](scripts/queries.py:795) | `holdings_v2` + `fund_holdings_v2` (N-PORT merge), `entity_*` | Register function. `rollup_type` + `quarter` filter. |
| `build_entity_graph()` | [L5188](scripts/queries.py:5188) | `entity_current`, `entity_rollup_history`, `holdings_v2`, `fund_holdings_v2` | Takes `con`. Fans out nodes/edges to depth 2, optional sub-advisers. |
| `get_entity_filer_children()` | [L5038](scripts/queries.py:5038) | `entity_current`, `entity_rollup_history`, `holdings_v2` | Cascading dropdown — filer rollup. |
| `get_entity_fund_children()` | [L5109](scripts/queries.py:5109) | `fund_holdings_v2`, `entity_*` | Cascading dropdown — fund rollup. |

**Query cost (ticker=AAPL, quarter=2025Q4, rollup_type=economic_control_v1, entity_id=2):**

| Function | Cold (ms) | Warm (ms) | Rows | Precomputed source? |
|---|---|---|---|---|
| `search_entity_parents('black', con)` | 14.7 | 4.2 | 20 | No |
| `get_market_summary(limit=25)` | 102 | 101 | 25 | No |
| `query1('AAPL', rt, q)` | **ERR** | **ERR** | — | **500 — see anomaly** |
| `build_entity_graph(eid=2, …)` | 76 | 75 | 23 | No |
| `get_entity_filer_children(eid=2, q)` | 22 | 15 | 6 | No |
| `get_entity_fund_children(eid=2, 10000)` | 9 | 4 | 1 | No |

**Technical notes:**
- `query1()` raises `AttributeError: 'NoneType' object has no attribute 'lower'` at [queries.py:933](scripts/queries.py:933) for every ticker tested (AAPL, MSFT, NVDA, JPM). Root cause: one of the N-PORT `fund_holdings_v2` child rows has `institution=NULL`, and the dedup set comprehension `{c['institution'].lower() for c in nport_kids}` crashes. Callers in this tab: the "Institution holders of ticker X" panel (`tickerHoldersUrl`). Regression surface: Register tab (below) has the same blast radius.
- `build_entity_graph()` is steady ~75 ms regardless of warm/cold (no query cache) — acceptable per-user cost.
- `get_market_summary()` is global (ticker-independent) at 100 ms — cheap precompute win.
- `entity_search` inside this tab is **called twice** in different code paths ([L125 dropdown, L230 institution-by-name fallback](web/react-app/src/components/tabs/EntityGraphTab.tsx:230)) — request-scoped cache would collapse both.

**Bugs (visual):**
_[Serge]_

**Completeness gaps:**
_[Serge]_

**Precompute candidates:**

| Function | Tag | Rationale |
|---|---|---|
| `query1()` | **blocker** | Fix NoneType crash before anything else — see anomalies list. |
| `get_market_summary()` | table | Ticker-independent, global top-N, quarter-refreshable. 100 ms × every Entity Graph open. |
| `build_entity_graph()` | cache | 75 ms warm, (entity_id, quarter) key — scope memoize on the server. |
| `search_entity_parents()` | cache | Already fast warm (4 ms); request-scoped memoization collapses the duplicate call inside the same tab render. |
| `get_entity_filer_children` / `get_entity_fund_children` | leave | <25 ms; fan-out to dropdowns. |

---

## Register

**React component:** [web/react-app/src/components/tabs/RegisterTab.tsx](web/react-app/src/components/tabs/RegisterTab.tsx)

**Endpoints hit:**

| Endpoint | Router module | Handler |
|---|---|---|
| `/api/v1/query1` | [scripts/api_register.py](scripts/api_register.py) | `api_query1()` → `_execute_query(1)` |

**queries.py functions called:**

| Function | Line | Tables | Notes |
|---|---|---|---|
| `query1()` | [L795](scripts/queries.py:795) | `holdings_v2`, `fund_holdings_v2`, `entity_*`, `market_data` | Full Register. `rollup_type` + `quarter` params threaded. Merges N-PORT children into 13F parents. |

**Query cost:**

| Function | Cold (ms) | Warm (ms) | Rows | Precomputed source? |
|---|---|---|---|---|
| `query1('AAPL', RT, '2025Q4')` | **ERR** | **ERR** | — | See anomaly |

**Technical notes:** `query1()` crashes for every ticker tested with `AttributeError: 'NoneType' object has no attribute 'lower'` at [queries.py:933](scripts/queries.py:933). The Register tab currently 500s for any ticker whose N-PORT merge path encounters an `institution IS NULL` child — which is every ticker I tested on prod DB. **This is the single most user-visible regression in the audit.**

**Bugs (visual):**
_[Serge]_

**Completeness gaps:**
_[Serge]_

**Precompute candidates:**

| Function | Tag | Rationale |
|---|---|---|
| `query1()` | **blocker** (then cache) | Null-safe the comprehension first. After that, (ticker, quarter, rollup_type) is a natural request-scoped cache key — Entity Graph calls this too (`tickerHoldersUrl`). |

---

## Ownership Trend

**React component:** [web/react-app/src/components/tabs/OwnershipTrendTab.tsx](web/react-app/src/components/tabs/OwnershipTrendTab.tsx)

**Endpoints hit:**

| Endpoint | Router module | Handler |
|---|---|---|
| `/api/v1/ownership_trend_summary` | [scripts/api_flows.py](scripts/api_flows.py) | `api_ownership_trend_summary()` |
| `/api/v1/holder_momentum` | [scripts/api_flows.py](scripts/api_flows.py) | `api_holder_momentum()` |
| `/api/v1/cohort_analysis` | [scripts/api_flows.py](scripts/api_flows.py) | `api_cohort_analysis()` |

**queries.py functions called:**

| Function | Line | Tables | Notes |
|---|---|---|---|
| `ownership_trend_summary()` | [L2664](scripts/queries.py:2664) | `holdings_v2` multi-quarter | `rollup_type`-aware trend rollup. |
| `holder_momentum()` | [L1198](scripts/queries.py:1198) | `holdings_v2` + `fund_holdings_v2`, multi-quarter | `rollup_type`-aware. |
| `cohort_analysis()` | [L2922](scripts/queries.py:2922) | `holdings_v2` + `fund_holdings_v2`, multi-quarter self-join | `rollup_type`-aware; `from_quarter` seed. |

**Query cost (ticker=AAPL, 2025Q4, EC-v1, cohortFrom=2024Q4):**

| Function | Cold (ms) | Warm (ms) | Rows | Precomputed source? |
|---|---|---|---|---|
| `ownership_trend_summary()` | 34.5 | 33.7 | 1 | No |
| `holder_momentum()` | 126 | 102 | 1 | No |
| `cohort_analysis()` | 497 | 493 | 1 | No |

**Technical notes:** Warm≈cold on all three → no query-cache benefit, each scan is full. `cohort_analysis` at ~500 ms is the long pole. All three funcs scan the full holdings history for the ticker, so they amortize well as precomputed per-ticker-per-quarter tables.

**Bugs (visual):**
_[Serge]_

**Completeness gaps:**
_[Serge]_

**Precompute candidates:**

| Function | Tag | Rationale |
|---|---|---|
| `cohort_analysis()` | table | 500 ms every call, ticker×from_quarter×rollup_type key, trivially quarter-refreshable. |
| `holder_momentum()` | table | 100 ms warm, ticker-scoped, same amortization story. |
| `ownership_trend_summary()` | leave | 34 ms — not worth the infra. |

---

## Conviction

**React component:** [web/react-app/src/components/tabs/ConvictionTab.tsx](web/react-app/src/components/tabs/ConvictionTab.tsx)

**Endpoints hit:**

| Endpoint | Router module | Handler |
|---|---|---|
| `/api/v1/portfolio_context` | [scripts/api_flows.py](scripts/api_flows.py) | `api_portfolio_context()` |

**queries.py functions called:**

| Function | Line | Tables | Notes |
|---|---|---|---|
| `portfolio_context()` | [L3415](scripts/queries.py:3415) | `holdings_v2` + `fund_holdings_v2` + `market_data` | `rollup_type`-aware. Portfolio concentration context. |

**Query cost:**

| Function | Cold (ms) | Warm (ms) | Rows | Precomputed source? |
|---|---|---|---|---|
| `portfolio_context('AAPL', …)` | 72 | 35 | 0 | No |

**Technical notes:** Warm-path halves cold (DuckDB page cache effect). Zero rows on AAPL is consistent with the `is_latest` inversion — retest after DB fix to confirm. Per user memory: recent session got this 2.7 s → 730 ms via `quarter` param threading; current 72 ms suggests that optimization is present.

**Bugs (visual):**
_[Serge]_

**Completeness gaps:**
_[Serge]_

**Precompute candidates:**

| Function | Tag | Rationale |
|---|---|---|
| `portfolio_context()` | leave | 35 ms warm is already in the "cheap" band. Revisit only if the is_latest fix changes row counts materially. |

---

## Fund Portfolio

**React component:** [web/react-app/src/components/tabs/FundPortfolioTab.tsx](web/react-app/src/components/tabs/FundPortfolioTab.tsx)

**Endpoints hit:**

| Endpoint | Router module | Handler |
|---|---|---|
| `/api/v1/fund_portfolio_managers` | [scripts/api_fund.py](scripts/api_fund.py) | `api_fund_portfolio_managers()` (inline SQL) |
| `/api/v1/query7` | [scripts/api_register.py](scripts/api_register.py) | `api_query(7)` → `_execute_query(7)` |

**queries.py functions called:**

| Function | Line | Tables | Notes |
|---|---|---|---|
| *(inline SQL in `api_fund.py`)* | handler L89 | `holdings_v2` | Ticker-scoped `GROUP BY cik, fund_name`, `is_latest = TRUE`. No rollup_type filter. |
| `query7()` | [L1854](scripts/queries.py:1854) | `holdings_v2` + `fund_holdings_v2` + `securities` | Fund-scoped portfolio detail; takes `cik` + optional `fund_name`. |

**Query cost:**

| Function | Cold (ms) | Warm (ms) | Rows | Precomputed source? |
|---|---|---|---|---|
| `fund_portfolio_managers` SQL | 20.6 | 20.2 | 0 | No |
| `query7(ticker, cik=None, …)` | 20.4 | 19.3 | 0 | No |

**Technical notes:** 0 rows for `fund_portfolio_managers` on AAPL is another instance of the `is_latest=TRUE` filter → empty fast path. `query7` was tested with `cik=None` because the manager lookup returned no rows to pivot off — a realistic retest requires the DB fix first.

**Bugs (visual):**
_[Serge]_

**Completeness gaps:**
_[Serge]_

**Precompute candidates:**

| Function | Tag | Rationale |
|---|---|---|
| inline SQL + `query7()` | leave | Both <25 ms. Not the bottleneck. Fix DB first, then re-time. |

---

## Flow Analysis

**React component:** [web/react-app/src/components/tabs/FlowAnalysisTab.tsx](web/react-app/src/components/tabs/FlowAnalysisTab.tsx)

**Endpoints hit:**

| Endpoint | Router module | Handler |
|---|---|---|
| `/api/v1/flow_analysis` | [scripts/api_flows.py](scripts/api_flows.py) | `api_flow_analysis()` |

**queries.py functions called:**

| Function | Line | Tables | Notes |
|---|---|---|---|
| `flow_analysis()` | [L3163](scripts/queries.py:3163) | `holdings_v2` + `fund_holdings_v2` + `securities`, multi-quarter diff | `rollup_type`-aware. `period` selects the quarter window. |

**Query cost:**

| Function | Cold (ms) | Warm (ms) | Rows | Precomputed source? |
|---|---|---|---|---|
| `flow_analysis('AAPL', period='1Q', …)` | 301 | 198 | 1 | No |

**Technical notes:** ~300 ms cold, 200 ms warm — moderate DuckDB page-cache benefit but no memoization. Ticker-scoped with a small parameter space (period ∈ {1Q, 2Q, 4Q, ...} × level × active_only × rollup_type) — a good candidate for a materialized per-ticker table refreshed at quarter close.

**Bugs (visual):**
_[Serge]_

**Completeness gaps:**
_[Serge]_

**Precompute candidates:**

| Function | Tag | Rationale |
|---|---|---|
| `flow_analysis()` | table | 300 ms × every Flow Analysis open; bounded key space; fits the `ticker_flow_stats` pattern directly. |

---

## Peer Rotation

**React component:** [web/react-app/src/components/tabs/PeerRotationTab.tsx](web/react-app/src/components/tabs/PeerRotationTab.tsx)

**Endpoints hit:**

| Endpoint | Router module | Handler |
|---|---|---|
| `/api/v1/peer_rotation` | [scripts/api_flows.py](scripts/api_flows.py) | `api_peer_rotation()` |
| `/api/v1/peer_rotation_detail` | [scripts/api_flows.py](scripts/api_flows.py) | `api_peer_rotation_detail()` |

**queries.py functions called:**

| Function | Line | Tables | Notes |
|---|---|---|---|
| `get_peer_rotation()` | [L4483](scripts/queries.py:4483) | `holdings_v2` + peer/sector join, multi-quarter substitution detection | `rollup_type`-aware. Full-peer-universe scan per call. |
| `get_peer_rotation_detail()` | [L4772](scripts/queries.py:4772) | Same tables, narrowed to (subject, peer) pair | `rollup_type`-aware. |

**Query cost:**

| Function | Cold (ms) | Warm (ms) | Rows | Precomputed source? |
|---|---|---|---|---|
| `get_peer_rotation('AAPL', …)` | **11,421** | **11,522** | 1 | No |
| `get_peer_rotation_detail('AAPL','MSFT', …)` | 635 | 617 | 1 | No |

**Technical notes:** `get_peer_rotation()` at **11.4 seconds** cold AND warm is the single worst hot path in the audit — warm==cold proves DuckDB has no useful cache for this query shape, so every user re-pays the full substitution scan. Peer Rotation tab is effectively unusable today. Detail view at 600 ms is also slow; same profile (warm==cold).

**Bugs (visual):**
_[Serge]_

**Completeness gaps:**
_[Serge]_

**Precompute candidates:**

| Function | Tag | Rationale |
|---|---|---|
| `get_peer_rotation()` | **table (priority)** | 11.4 s per call. Materialize a per-ticker-per-rollup_type rotation table at quarter close. Keys: (ticker, active_only, level, rollup_type). Clear `investor_flows`-style precompute pattern. |
| `get_peer_rotation_detail()` | table | 600 ms × every peer row drill-down. Materialize the (subject, peer) pair table alongside the rotation table. |

---

## Cross-Ownership

**React component:** [web/react-app/src/components/tabs/CrossOwnershipTab.tsx](web/react-app/src/components/tabs/CrossOwnershipTab.tsx)

**Endpoints hit:**

| Endpoint | Router module | Handler |
|---|---|---|
| `/api/v1/tickers` | [scripts/api_register.py](scripts/api_register.py) | `api_tickers()` (shared autocomplete) |
| `/api/v1/peer_groups` | [scripts/api_cross.py](scripts/api_cross.py) | `api_peer_groups()` (inline SQL) |
| `/api/v1/cross_ownership` | [scripts/api_cross.py](scripts/api_cross.py) | `api_cross_ownership()` |
| `/api/v1/cross_ownership_top` | [scripts/api_cross.py](scripts/api_cross.py) | `api_cross_ownership_top()` |

**queries.py functions called:**

| Function | Line | Tables | Notes |
|---|---|---|---|
| *(inline SQL)* `/tickers` | api_register L55 | `holdings_v2` | `GROUP BY ticker`, `is_latest=TRUE`. |
| *(inline SQL)* `/peer_groups` | api_cross L129 | `peer_groups` | Reference table. |
| `_cross_ownership_query()` | [L4277](scripts/queries.py:4277) | `holdings_v2`, ticker IN (…) multi-ticker group | `rollup_type`-aware. Called twice: once with `anchor`, once without (the two "views"). |

**Query cost:**

| Function | Cold (ms) | Warm (ms) | Rows | Precomputed source? |
|---|---|---|---|---|
| `/tickers` inline SQL | 29 | 10 | **0 — see anomaly** | No |
| `/peer_groups` inline SQL | 1.8 | 0.3 | 27 | No |
| `_cross_ownership_query(anchor='AAPL')` | 31 | 30 | 1 | No |
| `_cross_ownership_query(anchor=None)` | 31 | 30 | 1 | No |

**Technical notes:** Cross-ownership itself is fast (~30 ms). `/tickers` returns 0 — see DB state anomaly. Note: `CrossOwnershipTab` fetches `/api/v1/tickers` *directly* rather than reading from a shared hook — the same file is fetched independently by `OverlapAnalysisTab.tsx:79`, `TickerInput.tsx:15`, and this tab. 3 duplicate fetches per session load are an easy shared-cache win.

**Bugs (visual):**
_[Serge]_

**Completeness gaps:**
_[Serge]_

**Precompute candidates:**

| Function | Tag | Rationale |
|---|---|---|
| `_cross_ownership_query()` | leave | 30 ms steady. Not the bottleneck. |
| `/api/v1/tickers` (shared) | cache | Hits 3 tabs directly plus `TickerInput`. Session-lifetime cache at hook level collapses ≥3 fetches to 1. |
| `/api/v1/peer_groups` | leave | <2 ms. |

---

## Overlap Analysis

**React component:** [web/react-app/src/components/tabs/OverlapAnalysisTab.tsx](web/react-app/src/components/tabs/OverlapAnalysisTab.tsx)

**Endpoints hit:**

| Endpoint | Router module | Handler |
|---|---|---|
| `/api/v1/tickers` | [scripts/api_register.py](scripts/api_register.py) | `api_tickers()` (duplicate of shell) |
| `/api/v1/two_company_subject` | [scripts/api_cross.py](scripts/api_cross.py) | `api_two_company_subject()` |
| `/api/v1/two_company_overlap` | [scripts/api_cross.py](scripts/api_cross.py) | `api_two_company_overlap()` |

**queries.py functions called:**

| Function | Line | Tables | Notes |
|---|---|---|---|
| `get_two_company_subject()` | [L5609](scripts/queries.py:5609) | `holdings_v2`, `entity_*` | Top-50 holders for subject alone (pre-select render). |
| `get_two_company_overlap()` | [L5436](scripts/queries.py:5436) | `holdings_v2` + `fund_holdings_v2`, two-ticker join | Institutional + fund-level holder comparison. |

**Query cost:**

| Function | Cold (ms) | Warm (ms) | Rows | Precomputed source? |
|---|---|---|---|---|
| `get_two_company_subject('AAPL', q, con)` | 91 | 74 | 1 | No |
| `get_two_company_overlap('AAPL','MSFT', q, con)` | 117 | 112 | 1 | No |

**Technical notes:** Both ~100 ms — acceptable per-call, combinatorial key space (O(tickers²)) rules out precompute. `/tickers` is a duplicate fetch — same shared-cache opportunity as the Cross-Ownership tab.

**Bugs (visual):**
_[Serge]_

**Completeness gaps:**
_[Serge]_

**Precompute candidates:**

| Function | Tag | Rationale |
|---|---|---|
| `get_two_company_subject` | leave | 74 ms warm. |
| `get_two_company_overlap` | leave | 112 ms warm; key space O(n²) — not worth materializing. |

---

## Short Interest

**React component:** [web/react-app/src/components/tabs/ShortInterestTab.tsx](web/react-app/src/components/tabs/ShortInterestTab.tsx)

**Endpoints hit:**

| Endpoint | Router module | Handler |
|---|---|---|
| `/api/v1/short_analysis` | [scripts/api_market.py](scripts/api_market.py) | `api_short_analysis()` |

**queries.py functions called:**

| Function | Line | Tables | Notes |
|---|---|---|---|
| `short_interest_analysis()` | [L3790](scripts/queries.py:3790) | `holdings_v2` + `fund_holdings_v2` + `short_interest` (FINRA), `market_data` | `rollup_type`-aware. Composes N-PORT shorts + FINRA + long-side cross-ref. |

**Query cost:**

| Function | Cold (ms) | Warm (ms) | Rows | Precomputed source? |
|---|---|---|---|---|
| `short_interest_analysis('AAPL', …)` | 152 | 133 | 1 | No |

**Technical notes:** 150 ms is moderate. Ticker-scoped, rollup_type-aware, quarter-refreshable — fits the precompute pattern but benefit is marginal unless tab is high-traffic.

**Bugs (visual):**
_[Serge]_

**Completeness gaps:**
_[Serge]_

**Precompute candidates:**

| Function | Tag | Rationale |
|---|---|---|
| `short_interest_analysis()` | table *or* cache | Borderline — 130 ms warm. Only materialize if Serge confirms the tab is hot. Otherwise leave. |

---

## Data Source

**React component:** [web/react-app/src/components/tabs/DataSourceTab.tsx](web/react-app/src/components/tabs/DataSourceTab.tsx)

**Endpoints hit:**

| Endpoint | Router module | Handler |
|---|---|---|
| `/api/v1/data-sources` | [scripts/api_config.py](scripts/api_config.py) | `api_data_sources()` (reads `docs/data_sources.md`) |

**queries.py functions called:**

None — file-system read, no DB touch.

**Query cost:**

| Function | Cold (ms) | Warm (ms) | Rows | Precomputed source? |
|---|---|---|---|---|
| `api_data_sources()` | ~1 ms (file read) | ~1 ms | 1 | N/A |

**Technical notes:** Not a DB endpoint. Low cost, no action needed.

**Bugs (visual):**
_[Serge]_

**Completeness gaps:**
_[Serge]_

**Precompute candidates:**

| Function | Tag | Rationale |
|---|---|---|
| — | leave | Static file read. |

---

## Shared / cross-tab endpoints

These are not tab-specific but fire on every page load or ticker change. Profiled once here to avoid repeating them per-tab.

| Endpoint | Fired from | Handler | Cold (ms) | Warm (ms) | Tag | Rationale |
|---|---|---|---|---|---|---|
| `/api/v1/summary` | [useAppStore.ts:33](web/react-app/src/store/useAppStore.ts:33) | `api_summary()` → `get_summary()` [L4164](scripts/queries.py:4164) | 258 | 0 | cache | 258 ms first-load, effectively free on retry. Module-level memoization already collapses warm; keep. |
| `/api/v1/tickers` | `TickerInput.tsx:15`, `CrossOwnershipTab.tsx:95`, `OverlapAnalysisTab.tsx:79` | `api_tickers()` inline SQL | 29 | 10 | cache | 3× per session load today; share via a session-scoped hook. |
| `/api/v1/freshness` | `FreshnessBadge.tsx:53` | `api_freshness()` (`data_freshness` table) | 6.5 | 0.5 | cache | Already wired through `freshnessCache` module singleton in the badge; leave. |

---

# Cross-tab summary

## Technical anomalies (Code session)

1. **`is_latest=TRUE` inversion on prod DB for `quarter='2025Q4'`.** Every `is_latest=TRUE` row has `ticker IS NULL`; every row with a ticker has `is_latest=FALSE`. Previous quarters (2025Q2, Q3) store only `is_latest=TRUE`. Recent commits 9d26eb1 and a7abb79 backfill the CI fixture but did not touch `data/13f.duckdb`. Affected endpoints (all filter `WHERE is_latest=TRUE AND quarter=LQ`):
   - `/api/v1/tickers` — returns 0 rows → every autocomplete is empty.
   - `/api/v1/fund_portfolio_managers` — 0 rows on AAPL.
   - `/api/v1/portfolio_context` — 0 rows on AAPL.
   - Most 2025Q4-filtering queries inside `queries.py` (`query1`, `flow_analysis`, `ownership_trend_summary`, etc.) — will return empty as soon as the NoneType bug is fixed.
   - No 500s, just silent empties.
   - Recommended next step: either re-run the fixture-rebuild backfill against `data/13f.duckdb`, or push a migration that flips the inverted rows for 2025Q4.

2. **`query1()` crashes on every ticker** with `AttributeError: 'NoneType' object has no attribute 'lower'` at [queries.py:933](scripts/queries.py:933). Triggered by an N-PORT `fund_holdings_v2` child with `institution=NULL`; the set-comprehension `{c['institution'].lower() for c in nport_kids}` has no null guard. Reproduced with AAPL, MSFT, NVDA, JPM. Breaks the Register tab and the Entity Graph "ticker holders" panel. One-line fix: `c['institution'].lower() for c in nport_kids if c.get('institution')` — logged here per session protocol, **not** applied.

3. **`get_peer_rotation()` is 11.4 s cold AND warm.** Single hottest code path in the audit. Warm==cold means DuckDB caches nothing useful for this query shape; every user re-pays the full scan. Peer Rotation tab is effectively unusable without precompute.

4. **`/api/v1/tickers` is fetched 3× per session load** (TickerInput, CrossOwnershipTab, OverlapAnalysisTab). Each tab opens its own independent fetch with no shared cache hook. Trivial to consolidate.

5. **Endpoints defined in routers but not called from any tab** (may be dead code or modal-only callers that were removed): `/api/v1/config/quarters`, `/api/v1/amendments`, `/api/v1/manager_profile`, `/api/v1/fund_rollup_context`, `/api/v1/fund_behavioral_profile`, `/api/v1/nport_shorts`, `/api/v1/entity_resolve`, `/api/v1/sector_flow_detail`, `/api/v1/short_long`, `/api/v1/short_volume`, `/api/v1/crowding`, `/api/v1/smart_money`, `/api/v1/heatmap`, `/api/v1/peer_groups/{group_id}`, `/api/v1/export/query{qnum}`. Informational — out of scope for this audit to prune.

## Prioritized bug list
_[Serge — consolidated from per-tab visual notes post-walkthrough]_

## Prioritized completeness gap list
_[Serge — consolidated from per-tab gap notes post-walkthrough]_

## Precompute build plan

Sorted by impact (cold-ms × probable call-rate):

| Target | Tool | Tabs served | Est. effort | Priority |
|---|---|---|---|---|
| `peer_rotation_by_ticker` precomputed table | new `compute_peer_rotation.py` + `SourcePipeline` subclass | Peer Rotation | 2–3 days | **P0 (11.4 s blocker)** |
| `peer_rotation_detail_by_pair` precomputed table | bundled with P0 | Peer Rotation | +0.5 day | **P0** |
| `sector_flows_rollup` precomputed table | new `compute_sector_flows.py` | Sector Rotation | 1–2 days | P1 |
| `sector_flow_movers_by_quarter_sector` table | bundled with above | Sector Rotation | +0.5 day | P1 |
| `cohort_by_ticker_from` precomputed table | new `compute_cohort.py` | Ownership Trend | 1 day | P1 |
| `flow_analysis_by_ticker_period` precomputed table | extend `compute_flows.py` | Flow Analysis | 1 day | P2 |
| `market_summary_top25` precomputed table | trivial; quarter-refreshable | Entity Graph | 0.5 day | P2 |
| `holder_momentum_by_ticker` precomputed table | bundled with trend | Ownership Trend | 0.5 day | P2 |
| Shared-session cache for `/api/v1/tickers` | React hook change | Cross-Ownership, Overlap, Shell | <0.5 day | P3 (react-only) |
| Request-scoped memo for `/api/v1/entity_search` | FastAPI dep or React hook | Entity Graph | <0.5 day | P3 |

## Work item routing

**React-only (ships before int-09 Step 4):**
- Consolidate `/api/v1/tickers` to a single shared hook — replace direct `fetch('/api/v1/tickers')` in `CrossOwnershipTab:95`, `OverlapAnalysisTab:79`, `TickerInput:15` with `useTickers()` (session-scoped cache).
- Collapse duplicate `/api/v1/entity_search` call inside `EntityGraphTab` (L125 + L230).
- Any visual / completeness items Serge flags per-tab above.

**Bundle with int-09 Step 4 (queries.py structural touch):**
- Fix `query1()` NoneType crash at `queries.py:933` (one-line null guard; breaks Register + Entity Graph today).
- Fix `is_latest=TRUE` inversion on prod DB `data/13f.duckdb` for 2025Q4 (backfill or migration; gates everything else).
- Build `peer_rotation_by_ticker` + `peer_rotation_detail_by_pair` precomputed tables and switch the `get_peer_rotation*` functions to read from them.
- Build `sector_flows_rollup` + `sector_flow_movers_by_quarter_sector` precomputed tables.
- Build `cohort_by_ticker_from`, `flow_analysis_by_ticker_period`, `market_summary_top25`, `holder_momentum_by_ticker` tables (optional — lower priority).

**Open for Serge to confirm:**
- Whether `short_interest_analysis()` (~130 ms) warrants a precompute table or stays live — depends on tab traffic.
- Whether the "dead" endpoint list above should be triaged (delete vs. keep) in a follow-up audit.
