/**
 * API types — mirrors the JSON shapes returned by scripts/app.py routes.
 *
 * Generated 2026-04-11 by inspecting live responses from a running Flask
 * instance (`python3 scripts/app.py --port 8001`). Field names and nullability
 * reflect the actual responses for ticker=EQT at quarter=2025Q4 — NOT the
 * route-name aliases used in REACT_MIGRATION.md. The React tab code must hit
 * the real route names noted in each section header.
 *
 * Nullability rule: Flask's clean_for_json() converts NaN / pd.NA / None to
 * JSON null, so optional numerics are typed `number | null`, not `number | undefined`.
 */

// ── Shared query parameters ───────────────────────────────────────────────
// The Flask backend accepts `rollup_type` on most ticker-scoped endpoints
// (query1/2/3/5/12/14, ownership_trend_summary, flow_analysis, cross_ownership,
// portfolio_context, peer_rotation, sector_flow_*). Default is fund-sponsor
// (`economic_control_v1`); `decision_maker_v1` reroutes sub-advised fund
// series to the actual investment adviser instead of the legal sponsor.

export type RollupType = 'economic_control_v1' | 'decision_maker_v1'

// ── Summary — /api/summary?ticker=EQT ─────────────────────────────────────

export interface SummaryTypeBreakdownRow {
  type: string
  value: number
}

export interface SummaryResponse {
  ticker: string
  company_name: string
  latest_quarter: string
  market_cap: number | null
  price: number | null
  price_date: string | null
  shares_float: number | null
  total_shares: number
  total_value: number
  total_pct_float: number
  active_value: number
  passive_value: number
  num_holders: number
  nport_coverage: number | null
  nport_funds: number | null
  nport_latest_date: string | null
  type_breakdown: SummaryTypeBreakdownRow[]
}

// ── Register — /api/query1?ticker=EQT ─────────────────────────────────────
// NOTE: No /api/register route exists. Register data is served via /api/query1.
// Response is a dict with rows[], all_totals, type_totals (dict keyed by type).

export interface RegisterRow {
  rank: number
  institution: string
  type: string
  level: number
  is_parent: boolean
  child_count: number
  shares: number | null
  value_live: number | null
  pct_float: number | null
  pct_aum: number | null
  aum: number | null
  nport_cov: number | null
  source: string | null
  subadviser_note: string | null
}

export interface RegisterAllTotals {
  count: number
  shares: number | null
  value_live: number | null
  pct_float: number | null
}

export interface RegisterTypeTotal {
  count: number
  shares: number | null
  value_live: number | null
  pct_float: number | null
}

export interface RegisterResponse {
  rows: RegisterRow[]
  all_totals: RegisterAllTotals
  // type_totals is keyed by manager_type (active, passive, hedge_fund, mixed,
  // quantitative, wealth_management, pension_insurance, strategic, SWF,
  // private_equity, endowment_foundation).
  type_totals: Record<string, RegisterTypeTotal>
}

// ── Ownership Trend — /api/ownership_trend_summary?ticker=EQT ─────────────
// NOTE: No /api/ownership_trend route. Real route is /api/ownership_trend_summary.
// Accepts level=parent|child and active_only=true|false query params.

export interface OwnershipTrendQuarter {
  quarter: string
  total_inst_shares: number
  total_inst_value: number
  holder_count: number
  pct_float: number
  active_value: number
  passive_value: number
  active_pct: number
  passive_pct: number
  net_holder_change: number | null
  net_shares_change: number | null
  signal: string | null
}

export interface OwnershipTrendSummary {
  net_new_holders: number
  total_shares_added: number
  total_dollar_flow: number
  trend: string
}

export interface OwnershipTrendResponse {
  level: string
  quarters: OwnershipTrendQuarter[]
  summary: OwnershipTrendSummary
}

// ── Holder Momentum — /api/holder_momentum?ticker=EQT ─────────────────────
// Returns a flat array (not wrapped in a dict). Accepts level, active_only,
// rollup_type. Parent rows (level=0) carry is_parent, child_count, rank.
// Child rows (level=1) lack rank. Both carry dynamic quarter keys (e.g.
// '2025Q1') with share counts as number | null.

export interface HolderMomentumRow {
  institution: string
  type: string | null
  level: number
  is_parent: boolean
  child_count: number
  rank?: number
  change: number | null
  change_pct: number | null
  // Dynamic quarter keys accessed via bracket notation:
  //   (row as Record<string, unknown>)['2025Q1'] as number | null
  // Using index signature here is intentional — the quarter columns are
  // dynamic and change with each filing cycle.
  [quarter: string]: string | number | boolean | null | undefined
}

// ── Cohort Analysis — /api/cohort_analysis?ticker=EQT&from=2025Q3 ────────
// Returns { detail: CohortDetailRow[], summary: CohortSummary }.
// Accepts ticker, from (quarter), level, active_only, rollup_type.
// Detail rows represent cohort categories (Retained, Increased, Decreased,
// Unchanged, New Entries, Exits, Total) with optional nested children (top 5
// investors per category, level=2).

export interface CohortDetailChild {
  category: string
  level: number
  holders: number
  shares: number
  value: number
  avg_position: number
  pct_float_moved: number
  delta_shares: number | null
  delta_value: number | null
}

export interface CohortDetailRow {
  category: string
  level: number
  holders: number
  shares: number
  value: number
  avg_position: number
  pct_float_moved: number
  delta_shares: number | null
  delta_value: number | null
  has_children?: boolean
  is_parent?: boolean
  is_total?: boolean
  children?: CohortDetailChild[]
}

export interface CohortRetentionTrend {
  from: string
  to: string
  econ_retention: number
  active_holders_from: number
  active_holders_to: number
}

export interface CohortSummary {
  retention_rate: number
  econ_retention: number
  net_holders: number
  net_shares: number
  net_value: number
  from_quarter: string
  to_quarter: string
  active_only: boolean
  level: string
  // Counts of top-10 holders by cohort: {increased: 6, decreased: 4, ...}
  top10: Record<string, number>
  econ_retention_trend: CohortRetentionTrend[]
}

export interface CohortAnalysisResponse {
  detail: CohortDetailRow[]
  summary: CohortSummary
}

// ── Conviction — /api/portfolio_context?ticker=EQT ────────────────────────
// NOTE: No /api/conviction route. Real route is /api/portfolio_context.
// Quarter is implicit (uses server-side LATEST_QUARTER). Accepts level= and
// active_only= query params.

export interface ConvictionRow {
  rank?: number
  institution: string
  type: string
  level: number
  is_parent: boolean
  child_count: number
  value: number | null
  conviction_score: number | null
  subject_sector_pct: number | null
  sector_rank: number | null
  industry_rank: number | null
  co_rank_in_sector: number | null
  diversity: number | null
  etf_pct: number | null
  unk_pct: number | null
  vs_spx: number | null
  top3: string[]
  // Child rows carry their parent's institution name for filtering.
  // Not present on parent rows.
  parent_name?: string
  // N-PORT coverage — NOT returned by /api/portfolio_context today.
  // Added so the column can render "—" until the backend adds it.
  nport_cov?: number | null
}

export interface ConvictionResponse {
  level: string
  active_only: boolean
  subject_sector: string | null
  subject_sector_code: string | null
  subject_industry: string | null
  subject_spx_weight: number | null
  rows: ConvictionRow[]
}

// ── Fund Portfolio — /api/fund_portfolio_managers + /api/query7 ───────────
// Two endpoints feed this tab:
//   1. /api/fund_portfolio_managers?ticker=X — list of fund managers holding ticker
//   2. /api/query7?ticker=X&cik=Y — single fund's full portfolio (the drilldown)

export interface FundPortfolioManager {
  cik: string
  fund_name: string
  inst_parent_name: string
  manager_type: string
  position_value: number | null
}

// KNOWN BUG: /api/query7 is currently broken — queries.py:1815 uses a plain
// string for its WHERE clause that contains the literal `'{LQ}'` instead of
// an f-string substitution. DuckDB matches 0 rows and the route returns 404.
// The interface below reflects the intended shape per query7() code. When
// the bug is fixed, re-verify field names and nullability against live output.

export interface FundPortfolioStats {
  manager_name: string
  cik: string
  manager_type: string
  total_value: number
  num_positions: number
  top10_concentration_pct: number
}

export interface FundPortfolioPosition {
  rank: number
  ticker: string
  issuer_name: string | null
  sector: string | null
  shares: number | null
  market_value_live: number | null
  pct_of_portfolio: number | null
  pct_of_float: number | null
  market_cap: number | null
}

export interface FundPortfolioResponse {
  stats: FundPortfolioStats
  positions: FundPortfolioPosition[]
}

// ── Flow Analysis — /api/flow_analysis?ticker=EQT&period=1Q ───────────────
// NOTE: No /api/flows route. Real route is /api/flow_analysis.
// period format is `1Q`, `2Q`, `4Q` — NOT `Q1`, `Q2`, `Q4`.

export interface FlowRow {
  inst_parent_name: string
  manager_type: string
  from_shares: number | null
  from_value: number | null
  from_price: number | null
  to_shares: number | null
  to_value: number | null
  net_shares: number
  net_value: number | null
  pct_change: number | null
  pct_float: number | null
  raw_flow: number | null
  price_adj_flow: number | null
  price_effect: number | null
  flow_2q: number | null
  flow_4q: number | null
  momentum_ratio: number | null
  momentum_signal: string | null
  is_new_entry: boolean
  is_exit: boolean
}

export interface FlowTrendRow {
  quarter_from: string
  quarter_to: string
  flow_intensity_total: number
  flow_intensity_active: number
  flow_intensity_passive: number
  churn_active: number
  churn_nonpassive: number
}

export interface QoqChartRow {
  from: string
  to: string
  label: string
  flow_intensity_total: number
  flow_intensity_active: number
  churn_active: number
  churn_nonpassive: number
}

export interface FlowChartTickerRow {
  ticker: string
  flow_intensity_total: number
  flow_intensity_active: number
  flow_intensity_passive: number
  churn_active: number
  churn_nonpassive: number
}

export interface FlowAnalysisResponse {
  period: string
  level: string
  quarter_from: string
  quarter_to: string
  buyers: FlowRow[]
  sellers: FlowRow[]
  new_entries: FlowRow[]
  exits: FlowRow[]
  flow_trend: FlowTrendRow[]
  qoq_charts: QoqChartRow[]
  charts: {
    churn: FlowChartTickerRow[]
    flow_intensity: FlowChartTickerRow[]
  }
  // implied_prices is keyed by quarter string → computed price
  implied_prices: Record<string, number>
}

// ── Cross-Ownership — /api/cross_ownership?tickers=EQT ────────────────────
// NOTE: param name is `tickers` (plural, comma-separated), NOT `ticker`.
// No `quarter` param — uses server-side LATEST_QUARTER.

export interface CrossOwnershipInvestor {
  investor: string
  type: string
  total_across: number
  pct_of_portfolio: number | null
  // holdings is keyed by ticker → position value
  holdings: Record<string, number>
}

export interface CrossOwnershipResponse {
  tickers: string[]
  // companies is keyed by ticker → company_name
  companies: Record<string, string>
  investors: CrossOwnershipInvestor[]
}

// ── Two Companies Overlap — /api/two_company_overlap + /api/two_company_subject
// NOTE: param names are `subject` and `second`, NOT `ticker` and `ticker2`.
// /api/two_company_subject returns the same shape with all sec_* fields null.

export interface TwoCompanyMeta {
  quarter: string
  subject: string
  subject_name: string | null
  second: string | null
  second_name: string | null
  subj_float: number | null
  sec_float: number | null
}

export interface TwoCompanyInstitutionalRow {
  holder: string
  manager_type: string | null
  is_overlap: boolean
  subj_shares: number | null
  subj_dollars: number | null
  subj_pct_float: number | null
  sec_shares: number | null
  sec_dollars: number | null
  sec_pct_float: number | null
}

export interface TwoCompanyFundRow {
  holder: string
  family_name: string | null
  series_id: string | null
  is_active: boolean
  is_overlap: boolean
  subj_shares: number | null
  subj_dollars: number | null
  subj_pct_float: number | null
  sec_shares: number | null
  sec_dollars: number | null
  sec_pct_float: number | null
}

export interface TwoCompanyOverlapResponse {
  meta: TwoCompanyMeta
  institutional: TwoCompanyInstitutionalRow[]
  fund: TwoCompanyFundRow[]
}

// ── Crowding / Short Interest — /api/crowding?ticker=EQT ──────────────────

export interface CrowdingHolder {
  holder: string
  manager_type: string | null
  pct_float: number | null
  value: number | null
}

export interface CrowdingShortHistoryRow {
  report_date: string
  short_volume: number | null
  total_volume: number | null
  short_pct: number | null
}

export interface CrowdingResponse {
  holders: CrowdingHolder[]
  // Only present when the short_interest table is loaded server-side.
  short_history?: CrowdingShortHistoryRow[]
}

// ── Sector Rotation — /api/sector_flows ───────────────────────────────────
// NOTE: No /api/sector_rotation route. Real route is /api/sector_flows.
// Returns all available quarter transitions, no quarter param.

export interface SectorFlowStats {
  managers: number
  inflow: number
  outflow: number
  net: number
  new_positions: number
  exits: number
}

export interface SectorFlowRow {
  sector: string
  total_net: number
  latest_net: number
  // flows is keyed by "fromQuarter_toQuarter" (e.g. "2025Q3_2025Q4")
  flows: Record<string, SectorFlowStats>
}

export interface SectorFlowPeriod {
  from: string
  to: string
  label: string
}

export interface SectorFlowsResponse {
  periods: SectorFlowPeriod[]
  sectors: SectorFlowRow[]
}

// ── Entity Graph — /api/entity_search + /api/entity_children + /api/entity_graph

export interface EntitySearchResult {
  entity_id: number
  display_name: string
  entity_type: string
  classification: string | null
}

export interface EntityChild {
  entity_id: number
  display_name: string
  cik: string | null
  aum: number | null
}

export interface EntityGraphNodeColor {
  background: string
  border: string
}

export interface EntityGraphNodeFont {
  color: string
}

export interface EntityGraphNode {
  id: string
  entity_id: number
  node_type: string
  display_name: string
  label: string
  title: string
  level: number
  classification: string | null
  aum: number | null
  aum_type: string | null
  color: EntityGraphNodeColor
  font: EntityGraphNodeFont
}

export interface EntityGraphEdgeColor {
  color: string
}

export interface EntityGraphEdge {
  from: string
  to: string
  arrows: string
  dashes: boolean
  relationship_type: string
  color: EntityGraphEdgeColor
}

export interface EntityGraphMetadata {
  root_entity_id: number
  root_name: string
  selected_entity_id: number
  breadcrumb: string
  quarter: string
  filer_count: number
  // both keyed by filer_entity_id (as string) → fund count
  shown_funds_by_filer: Record<string, number>
  total_funds_by_filer: Record<string, number>
  truncated: boolean
}

export interface EntityGraphResponse {
  nodes: EntityGraphNode[]
  edges: EntityGraphEdge[]
  metadata: EntityGraphMetadata
}

// ── Quarter Config — /api/admin/quarter_config ────────────────────────────
// NOTE: Real route is /api/admin/quarter_config (not /api/quarter_config).
// INF12 left this endpoint ungated because the public UI loads it every page.

export interface QuarterConfigResponse {
  quarters: string[]
  // all three below are keyed by quarter → string value
  urls: Record<string, string>
  report_dates: Record<string, string>
  snapshot_dates: Record<string, string>
  config_file: string
}
