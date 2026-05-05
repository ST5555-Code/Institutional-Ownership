/**
 * API types — hand-written shapes for the JSON returned by scripts/app.py routes.
 *
 * Originally authored 2026-04-11 from live Flask responses; kept current as
 * the React code migrated to FastAPI (Batch 4-C, 2026-04-13). Post-4-C an
 * auto-generated companion file lives at `src/types/api-generated.ts`
 * (produced via `npx openapi-typescript http://localhost:8001/openapi.json
 * -o src/types/api-generated.ts`). The generated file covers every route
 * FastAPI knows about — including the 6 priority envelope types declared
 * via `response_model` (`Envelope_list_TickerRow__`, `Envelope_RegisterPayload_`,
 * `Envelope_ConvictionPayload_`, `Envelope_FlowAnalysisPayload_`,
 * `Envelope_OwnershipTrendPayload_`, `Envelope_EntityGraphPayload_`).
 *
 * The hand-written types below are still the working source of truth for
 * tab components. Migrating tab-by-tab to the generated types is a
 * follow-up: the auto-generated names are verbose, and the hand-written
 * shapes capture field nullability / numeric quirks (NaN → null, date
 * strings) that are more ergonomic in the React layer. Do both sides
 * update when the wire contract changes until the last tab is migrated.
 *
 * Nullability rule: serializers.clean_for_json() converts NaN / pd.NA /
 * None to JSON null, so optional numerics are typed `number | null`, not
 * `number | undefined`.
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
  total_pct_so: number
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
  pct_so: number | null
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
  pct_so: number | null
}

export interface RegisterTypeTotal {
  count: number
  shares: number | null
  value_live: number | null
  pct_so: number | null
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
  pct_so: number
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
  pct_so_moved: number
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
  pct_so_moved: number
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
  subject_sector_pct: number | null
  sector_rank: number | null
  industry_rank: number | null
  co_rank_in_sector: number | null
  diversity: number | null
  etf_pct: number | null
  unk_pct: number | null
  vs_spx: number | null
  // Each entry carries the GICS sector code and its weight as % of the
  // holder's total portfolio value (excluding Unknown + ETF sectors).
  top3: Array<{ code: string; weight_pct: number }>
  // Score field removed — deemed too subjective for display.
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

// Bug fixed: queries.py:1815 f-prefix was missing. Verified against live
// response — field names and types match.

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
  pct_of_so: number | null
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
  pct_so: number | null
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
  // holdings is keyed by ticker → position value (null when investor doesn't hold)
  holdings: Record<string, number | null>
  // True when fund_holdings_v2 has rows under this investor's DM rollup
  // (via entity_rollup_history) or family_name — controls expand-triangle render.
  has_fund_detail?: boolean
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
  subj_denom: number | null
  subj_pct_of_so_source: string | null
  sec_denom: number | null
  sec_pct_of_so_source: string | null
}

export interface TwoCompanyInstitutionalRow {
  holder: string
  manager_type: string | null
  is_overlap: boolean
  subj_shares: number | null
  subj_dollars: number | null
  subj_pct_so: number | null
  subj_pct_of_so_source: string | null
  sec_shares: number | null
  sec_dollars: number | null
  sec_pct_so: number | null
  sec_pct_of_so_source: string | null
}

export interface TwoCompanyFundRow {
  holder: string
  family_name: string | null
  series_id: string | null
  is_active: boolean
  is_overlap: boolean
  subj_shares: number | null
  subj_dollars: number | null
  subj_pct_so: number | null
  subj_pct_of_so_source: string | null
  sec_shares: number | null
  sec_dollars: number | null
  sec_pct_so: number | null
  sec_pct_of_so_source: string | null
}

export interface TwoCompanyOverlapResponse {
  meta: TwoCompanyMeta
  institutional: TwoCompanyInstitutionalRow[]
  fund: TwoCompanyFundRow[]
}

export interface OverlapInstitutionOverlapFund {
  fund_name: string
  series_id: string | null
  family_name: string | null
  type: string
  value_a: number
  value_b: number
}

export interface OverlapInstitutionSingleFund {
  fund_name: string
  series_id: string | null
  family_name: string | null
  type: string
  value: number
}

export interface OverlapInstitutionDetailResponse {
  institution: string
  subject: string
  second: string
  quarter: string
  overlapping: OverlapInstitutionOverlapFund[]
  ticker_a_only: OverlapInstitutionSingleFund[]
  ticker_b_only: OverlapInstitutionSingleFund[]
}

// ── Crowding / Short Interest — /api/crowding?ticker=EQT ──────────────────

export interface CrowdingHolder {
  holder: string
  manager_type: string | null
  pct_so: number | null
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

// ── Short Analysis — /api/short_analysis?ticker=EQT ───────────────────────

export interface ShortAnalysisSummary {
  short_funds: number
  short_shares: number
  short_value: number
  days_to_cover: number | null
  si_pct_so: number | null
  avg_short_vol_pct: number | null
  cross_ref_count: number
  quarters_available: string[]
}

export interface NportTrendRow {
  quarter: string
  fund_count: number
  short_shares: number
  short_value: number
}

export interface NportDetailRow {
  fund_name: string
  family_name: string | null
  type: string | null
  is_active: boolean
  short_shares: number
  short_value: number
  fund_aum_mm: number | null
  pct_of_nav: number | null
  quarter: string
  value_recomputed: boolean
}

export interface NportByFundRow {
  fund_name: string
  type: string | null
  // Dynamic quarter keys (e.g. '2025Q2') with share counts
  [quarter: string]: string | number | boolean | null | undefined
}

export interface ShortVolumeRow {
  report_date: string
  short_volume: number
  total_volume: number
  short_pct: number
}

export interface CrossRefRow {
  institution: string
  type: string | null
  long_shares: number
  long_value: number
  short_shares: number
  short_value: number
  net_exposure_pct: number
}

export interface ShortOnlyFundRow {
  fund_name: string
  family_name: string | null
  type: string | null
  short_shares: number
  short_value: number
  fund_aum_mm: number | null
}

export interface ShortAnalysisResponse {
  summary: ShortAnalysisSummary
  nport_trend: NportTrendRow[]
  nport_detail: NportDetailRow[]
  nport_by_fund: NportByFundRow[]
  short_volume: ShortVolumeRow[]
  cross_ref: CrossRefRow[]
  short_only_funds: ShortOnlyFundRow[]
}

// /api/v1/short_position_pct?ticker=X
export interface ShortPositionPctPoint {
  quarter: string
  pct: number
}
export interface ShortPositionPctResponse {
  ticker_data: ShortPositionPctPoint[]
  sector_avg: ShortPositionPctPoint[]
  industry_avg: ShortPositionPctPoint[]
  sector_name: string | null
  industry_name: string | null
}

// /api/v1/short_volume_comparison?ticker=X
export interface ShortVolumeComparisonPoint {
  date: string
  pct: number
}
export interface ShortVolumeComparisonResponse {
  ticker_data: ShortVolumeComparisonPoint[]
  sector_median: ShortVolumeComparisonPoint[]
  industry_median: ShortVolumeComparisonPoint[]
  sector_name: string | null
  industry_name: string | null
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

// ── Fund Quarter Completeness — /api/v1/fund_quarter_completeness ─────────

export interface FundQuarterCompletenessRow {
  quarter: string
  months_available: number
  complete: boolean
}

export type FundQuarterCompletenessResponse = FundQuarterCompletenessRow[]

// ── Sector Monthly Flows — /api/v1/sector_monthly_flows ───────────────────

export interface SectorMonthlyFlowRow {
  month: string  // 'YYYY-MM'
  net: number
}

export interface SectorMonthlyFlowsResponse {
  sector: string
  quarter: string
  months: SectorMonthlyFlowRow[]
}

// ── Sector Summary — /api/v1/sector_summary ───────────────────────────────

export interface SectorSummaryTypeBreakdown {
  type: string
  pct_aum: number
  aum: number
}

export interface SectorSummaryResponse {
  quarter: string
  total_aum: number
  total_holders: number
  type_breakdown: SectorSummaryTypeBreakdown[]
}

// ── Sector Flow Movers — /api/sector_flow_movers ──────────────────────────

export interface SectorFlowMover {
  institution: string
  net_flow: number
  buying: number
  selling: number
  positions_changed: number
}

export interface SectorFlowMoverSummary {
  buyers: number
  net: number
  inflow: number
  outflow: number
}

export interface SectorFlowMoversResponse {
  sector: string
  period: { from: string; to: string }
  summary: SectorFlowMoverSummary
  top_buyers: SectorFlowMover[]
  top_sellers: SectorFlowMover[]
}

// ── Sector Flow Mover Detail — /api/v1/sector_flow_mover_detail ───────────

export interface SectorFlowMoverDetailRow {
  ticker: string
  company_name: string | null
  net_flow: number | null
  shares_changed: number | null
}

export interface SectorFlowMoverDetailResponse {
  sector: string
  period: { from: string; to: string }
  institution: string
  level: string
  rows: SectorFlowMoverDetailRow[]
}

// ── Peer Rotation — /api/peer_rotation + /api/peer_rotation_detail ────────
// Note: active_only param uses '1'/'0' not 'true'/'false'.

export interface PeerRotationSubject {
  ticker: string
  sector: string
  industry: string
}

export interface PeerRotationPeriod {
  from: string
  to: string
  label: string
}

export interface SubstitutionRow {
  ticker: string
  industry: string
  net_peer_flow: number
  contra_subject_flow: number
  direction: string
  num_entities: number
  flows: Record<string, number>
}

export interface TopSectorMover {
  rank: number
  ticker: string
  industry: string
  net_flow: number
  inflow: number
  outflow: number
  is_subject: boolean
}

export interface EntityStoryContraPeer {
  ticker: string
  flow: number
}

export interface EntityStoryRow {
  entity: string
  subject_flow: number
  sector_flow: number
  top_contra_peers: EntityStoryContraPeer[]
}

export interface PeerRotationResponse {
  subject: PeerRotationSubject
  periods: PeerRotationPeriod[]
  // Keyed by period_key (e.g. "2025Q1_2025Q2") → { net: number }
  subject_flows: Record<string, { net: number }>
  sector_flows: Record<string, { net: number }>
  subject_pct_of_sector: Record<string, number>
  industry_substitutions: SubstitutionRow[]
  sector_substitutions: SubstitutionRow[]
  top_sector_movers: TopSectorMover[]
  entity_stories: EntityStoryRow[]
}

export interface PeerRotationDetailEntity {
  entity: string
  subject_flow: number
  peer_flow: number
}

export interface PeerRotationDetailResponse {
  ticker: string
  peer: string
  entities: PeerRotationDetailEntity[]
}

// ── Entity Market Summary — /api/entity_market_summary ────────────────────

export interface MarketSummaryRow {
  rank: number
  institution: string
  total_aum: number
  num_holdings: number
  num_ciks: number
  manager_type: string | null
  entity_id: number | null
  filer_count: number
  fund_count: number
  nport_coverage_pct: number | null
}

// ── Institution Hierarchy — /api/v1/institution_hierarchy ─────────────────

export interface InstitutionHierarchyFund {
  entity_id: number
  fund_name: string
  series_id: string | null
  nav: number | null
}

export interface InstitutionHierarchyFiler {
  entity_id: number
  name: string
  cik: string | null
  aum: number | null
  fund_count: number
  funds: InstitutionHierarchyFund[]
}

export interface InstitutionHierarchyResponse {
  entity_id: number
  institution: string
  quarter: string
  filers: InstitutionHierarchyFiler[]
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

// ── Quarter Config — /api/config/quarters ─────────────────────────────────
// Public endpoint loaded by the UI on every page (no auth). Renamed from
// /api/admin/quarter_config in ARCH-1A — legacy path still served until
// vanilla-JS frontend retirement (2026-04-20). This type is currently
// declared but unused; tabs hardcode quarter arrays today.

export interface QuarterConfigResponse {
  quarters: string[]
  // all three below are keyed by quarter → string value
  urls: Record<string, string>
  report_dates: Record<string, string>
  snapshot_dates: Record<string, string>
  config_file: string
}
