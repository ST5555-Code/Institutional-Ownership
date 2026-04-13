import { useEffect, useState } from 'react'

// Shape returned by /api/v1/freshness. Each row represents one precomputed
// table that a pipeline script has stamped after rebuild.
export interface FreshnessRow {
  table_name: string
  last_computed_at: string | null
  row_count: number | null
}

interface Props {
  // Table whose freshness this badge should surface. Must match a row in
  // the data_freshness table — e.g. 'summary_by_parent', 'investor_flows'.
  tableName: string
  // Optional label override; defaults to the table name.
  label?: string
}

// Per-table staleness thresholds (hours). Numbers encode the ARCHITECTURE_REVIEW.md
// Batch 3-A SLA table. The quarter-relative thresholds there (e.g. `quarter+30d`)
// are modelled here as day-offsets — approximately `quarter_length + days`, using
// 90d as a quarter proxy. Interpretation:
//   fresh ≤ amber               (neutral badge)
//   amber < age ≤ red           (warning)
//   age > red                   (danger)
// Tables not in this map get a neutral badge with a wider stale threshold.
const DEFAULT_SLA = { amber: 24 * 3, red: 24 * 14 }
const SLA: Record<string, { amber: number; red: number }> = {
  investor_flows: { amber: 24, red: 24 * 7 },
  ticker_flow_stats: { amber: 24, red: 24 * 7 },
  summary_by_parent: { amber: 24 * (90 + 7), red: 24 * (90 + 30) },
  summary_by_ticker: { amber: 24 * (90 + 7), red: 24 * (90 + 30) },
  beneficial_ownership_current: { amber: 48, red: 24 * 7 },
  fund_holdings_v2: { amber: 24 * (90 + 60), red: 24 * (90 + 120) },
}

type Status = 'fresh' | 'amber' | 'red' | 'never'

const PALETTE: Record<Status, { bg: string; fg: string; label: string }> = {
  fresh: { bg: '#ecfdf5', fg: '#047857', label: 'Fresh' },
  amber: { bg: '#fef3c7', fg: '#92400e', label: 'Stale' },
  red: { bg: '#fee2e2', fg: '#991b1b', label: 'Stale' },
  never: { bg: '#f1f5f9', fg: '#64748b', label: 'No data' },
}

// Module-level cache: one in-flight fetch shared across every badge on the
// page. The response is < 1 KB and rarely changes, so cache it for the
// lifetime of the SPA.
let freshnessCache: Promise<FreshnessRow[]> | null = null

function loadFreshness(): Promise<FreshnessRow[]> {
  if (freshnessCache) return freshnessCache
  freshnessCache = fetch('/api/v1/freshness')
    .then(r => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      return r.json()
    })
    .then(d => (d?.data ?? []) as FreshnessRow[])
    .catch(() => [] as FreshnessRow[])
  return freshnessCache
}

// Exposed for tests / forced refresh after a promote.
export function resetFreshnessCache() {
  freshnessCache = null
}

function humanizeAge(hours: number): string {
  if (hours < 1) return '<1h ago'
  if (hours < 48) return `${Math.round(hours)}h ago`
  const days = Math.round(hours / 24)
  if (days < 60) return `${days}d ago`
  const months = Math.round(days / 30)
  return `${months}mo ago`
}

function classify(tableName: string, lastComputedAt: string | null): { status: Status; ageHours: number | null } {
  if (!lastComputedAt) return { status: 'never', ageHours: null }
  // DuckDB TIMESTAMP serialises as 'YYYY-MM-DD HH:MM:SS[.ffffff]' — tack on a
  // 'Z' so Date() treats it as UTC; the server is UTC per ARCHITECTURE_REVIEW.md.
  const iso = lastComputedAt.includes('T')
    ? lastComputedAt
    : lastComputedAt.replace(' ', 'T') + (lastComputedAt.endsWith('Z') ? '' : 'Z')
  const ts = Date.parse(iso)
  if (Number.isNaN(ts)) return { status: 'never', ageHours: null }
  const ageHours = (Date.now() - ts) / (1000 * 60 * 60)
  const sla = SLA[tableName] ?? DEFAULT_SLA
  if (ageHours > sla.red) return { status: 'red', ageHours }
  if (ageHours > sla.amber) return { status: 'amber', ageHours }
  return { status: 'fresh', ageHours }
}

export function FreshnessBadge({ tableName, label }: Props) {
  const [row, setRow] = useState<FreshnessRow | null | undefined>(undefined)

  useEffect(() => {
    let cancelled = false
    loadFreshness().then(rows => {
      if (cancelled) return
      const match = rows.find(r => r.table_name === tableName) ?? null
      setRow(match)
    })
    return () => {
      cancelled = true
    }
  }, [tableName])

  if (row === undefined) return null // still loading
  const { status, ageHours } = classify(tableName, row?.last_computed_at ?? null)
  const palette = PALETTE[status]
  const age = ageHours !== null ? humanizeAge(ageHours) : 'never'
  const displayLabel = label ?? tableName

  return (
    <span
      title={`${displayLabel} — last updated ${row?.last_computed_at ?? 'never'}`}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        padding: '2px 8px',
        fontSize: 11,
        fontWeight: 500,
        color: palette.fg,
        backgroundColor: palette.bg,
        borderRadius: 10,
        lineHeight: '16px',
      }}
    >
      <span
        style={{
          width: 6,
          height: 6,
          borderRadius: '50%',
          backgroundColor: palette.fg,
          display: 'inline-block',
        }}
      />
      <span>{displayLabel}</span>
      <span style={{ opacity: 0.7 }}>·</span>
      <span>{status === 'never' ? palette.label : age}</span>
    </span>
  )
}
