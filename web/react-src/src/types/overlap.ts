export interface TickerItem {
  ticker: string
  name: string
}

// OverlapRow matches the shape returned by
//   /api/two_company_subject  — sec_* always null
//   /api/two_company_overlap  — sec_* populated for overlap rows
//
// Institutional rows carry `manager_type`; fund rows carry
// `family_name`, `series_id`, `is_active`. The backend never sets both.
export interface OverlapRow {
  holder: string
  is_overlap: boolean
  // institutional-only
  manager_type?: string
  // fund-only
  family_name?: string
  series_id?: string
  is_active?: boolean
  // subject-side metrics (always populated)
  subj_shares: number | null
  subj_dollars: number | null
  subj_pct_float: number | null
  // second-ticker side (null when no second ticker selected,
  // or when the holder doesn't hold the second ticker)
  sec_shares: number | null
  sec_dollars: number | null
  sec_pct_float: number | null
}

export interface OverlapMeta {
  subject: string
  subject_name: string
  second: string | null
  second_name: string | null
  quarter: string
  subj_float: number | null
  sec_float: number | null
}

export interface OverlapResponse {
  institutional: OverlapRow[]
  fund: OverlapRow[]
  meta: OverlapMeta
}

export interface QuarterConfig {
  quarters: string[]
}
