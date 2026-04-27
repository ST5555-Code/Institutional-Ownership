# API Endpoint Classification

_Freeze artifact — produced by Phase 1 Batch 1-B1 (2026-04-13). Extracted
from `scripts/app.py` to `docs/endpoint_classification.md` as part of Phase
4 Batch 4-A (Blueprint split)._

Every `/api/v1/*` route is categorized by two orthogonal dimensions:

- **Quarter** — `latest-only` (no `quarter` param, always `LATEST_QUARTER`)
  vs `quarter-aware` (reads `quarter`, validates, passes through).
- **Rollup** — `rollup-agnostic` (no `rollup_type` effect) vs `rollup-aware`
  (reads `rollup_type`, dispatches via `_RT_AWARE_QUERIES` for query endpoints).

Phase 4 Batch 4-A consumes this table — routes sharing a category cluster
into the same domain Blueprint. **Do not change a row's category without
updating this doc AND the downstream consumer.**

`/api/admin/*` lives on `admin_bp` (`scripts/admin_bp.py`), token-auth gated.
The legacy `/api/*` public mount was removed 2026-04-13 with the vanilla-JS
retirement — everything public is `/api/v1/*` only.

| Path                                | Quarter        | Rollup            | Notes |
|-------------------------------------|----------------|-------------------|-------|
| `/api/v1/freshness`                 | n/a (meta)     | n/a               | `data_freshness` snapshot — ARCH-3A |
| `/api/v1/data-sources`              | n/a (meta)     | n/a               | `docs/data_sources.md` markdown payload |
| `/api/v1/tickers`                   | latest-only    | rollup-agnostic   | enveloped (Phase 1-B2) |
| `/api/v1/summary`                   | latest-only    | rollup-agnostic   | bare |
| `/api/v1/fund_portfolio_managers`   | latest-only    | rollup-agnostic   | |
| `/api/v1/smart_money`               | latest-only    | rollup-agnostic   | |
| `/api/v1/crowding`                  | latest-only    | rollup-agnostic   | |
| `/api/v1/sector_flows`              | latest-only    | rollup-agnostic   | |
| `/api/v1/peer_groups`               | latest-only    | rollup-agnostic   | |
| `/api/v1/peer_groups/<group_id>`    | latest-only    | rollup-agnostic   | |
| `/api/v1/entity_search`             | latest-only    | rollup-agnostic   | |
| `/api/v1/entity_market_summary`     | latest-only    | rollup-agnostic   | |
| `/api/v1/short_analysis`            | latest-only    | rollup-aware      | threaded in Batch 1-A |
| `/api/v1/ownership_trend_summary`   | latest-only    | rollup-aware      | enveloped (Phase 1-B2) |
| `/api/v1/cohort_analysis`           | latest-only    | rollup-aware      | |
| `/api/v1/holder_momentum`           | latest-only    | rollup-aware      | |
| `/api/v1/flow_analysis`             | latest-only    | rollup-aware      | enveloped (Phase 1-B2) |
| `/api/v1/cross_ownership`           | latest-only    | rollup-aware      | |
| `/api/v1/cross_ownership_top`       | latest-only    | rollup-aware      | |
| `/api/v1/peer_rotation`             | latest-only    | rollup-aware      | |
| `/api/v1/peer_rotation_detail`     | latest-only    | rollup-aware      | |
| `/api/v1/portfolio_context`         | latest-only    | rollup-aware      | enveloped (Phase 1-B2) |
| `/api/v1/sector_flow_movers`        | latest-only    | rollup-aware      | |
| `/api/v1/entity_children`           | quarter-aware  | rollup-agnostic   | graph layer sits below rollup |
| `/api/v1/entity_graph`              | quarter-aware  | rollup-agnostic   | enveloped (Phase 1-B2) |
| `/api/v1/two_company_overlap`       | quarter-aware  | rollup-agnostic   | |
| `/api/v1/two_company_subject`       | quarter-aware  | rollup-agnostic   | |
| `/api/v1/query<int:qnum>`           | quarter-aware  | rollup-aware      | for qnum in `_RT_AWARE_QUERIES = {1,2,3,5,12,14}` |
| `/api/v1/query1`                    | quarter-aware  | rollup-aware      | dedicated enveloped route (Phase 1-B2); bypasses generic `/query<N>` |
| `/api/v1/export/query<int:qnum>`    | quarter-aware  | rollup-aware      | mirrors `/api/v1/query` — fixed Batch 1-B1 |

11 dead routes removed by `dead-endpoints` (2026-04-27): `config/quarters`,
`amendments`, `manager_profile`, `fund_rollup_context`, `fund_behavioral_profile`,
`nport_shorts`, `entity_resolve`, `sector_flow_detail`, `short_long`,
`short_volume`, `heatmap`. See PR linked from ROADMAP COMPLETED section.

## Phase 4 Batch 4-A Blueprint mapping

| Blueprint file          | Routes                                                                |
|-------------------------|-----------------------------------------------------------------------|
| `api_config.py`         | freshness, data-sources                                               |
| `api_register.py`       | tickers, summary, query<N>, query1, export/query<N>                   |
| `api_fund.py`           | fund_portfolio_managers                                               |
| `api_flows.py`          | flow_analysis, ownership_trend_summary, cohort_analysis, holder_momentum, peer_rotation, peer_rotation_detail, portfolio_context |
| `api_entities.py`       | entity_search, entity_children, entity_graph, entity_market_summary   |
| `api_market.py`         | sector_flows, sector_flow_movers, short_analysis, crowding, smart_money |
| `api_cross.py`          | cross_ownership, cross_ownership_top, two_company_overlap, two_company_subject, peer_groups, peer_groups/<group_id> |
