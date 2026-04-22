export type StalenessStatus = 'fresh' | 'stale' | 'critical' | 'missing' | 'unknown'

export interface PipelineRow {
  name: string
  display_name: string | null
  cadence: string | null
  target_table: string | null
  stale_threshold_days: number | null
  staleness_status: StalenessStatus
  age_days: number | null
  last_refreshed: string | null
  registered: boolean
  currently_running: string | null
  last_run: { run_id: string; status: string; completed_at: string | null } | null
}

export interface PendingRun {
  run_id: string
  pipeline_name: string
  scope: Record<string, unknown>
  pending_since: string | null
  manifest_id?: number
}

export interface StatusPayload {
  pipelines: PipelineRow[]
  pending_runs: PendingRun[]
  last_probe_at: string | null
}

export interface ProbeResult {
  pipeline: string
  new_count: number | null
  latest_accession: string | null
  probed_at: string | null
  cached?: boolean
  note?: string
  error?: string
}

export interface DiffSummary {
  inserts: number
  flips: number
  anomalies: string[]
  qc_blocks: number
  qc_flags: number
  qc_warns: number
}

export interface DiffPayload {
  run_id: string
  pipeline_name: string
  scope: Record<string, unknown>
  summary: DiffSummary
  sample_rows: Record<string, unknown>[]
  staged_until: string | null
}
