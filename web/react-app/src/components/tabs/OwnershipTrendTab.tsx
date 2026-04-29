import { useMemo, useState } from 'react'
import { useAppStore } from '../../store/useAppStore'
import { useFetch } from '../../hooks/useFetch'
import { useFetchEnvelope } from '../../hooks/useFetchEnvelope'
import type {
  OwnershipTrendResponse,
  OwnershipTrendQuarter,
  HolderMomentumRow,
  CohortAnalysisResponse,
  CohortDetailRow,
} from '../../types/api'
import {
  RollupToggle,
  ActiveOnlyToggle,
  FundViewToggle,
  ExportBar,
  FreshnessBadge,
} from '../common'

// ── Formatters ─────────────────────────────────────────────────────────────

const NUM_0 = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 })
const NUM_1 = new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 })
const NUM_2 = new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

function fmtSharesMm(v: number | null): string {
  if (v == null || v === 0) return '—'
  return NUM_2.format(v / 1e6)
}

function fmtValueMm(v: number | null): string {
  if (v == null || v === 0) return '—'
  return `$${NUM_0.format(v / 1e6)}`
}

function fmtPct2(v: number | null): string {
  if (v == null || v === 0) return '—'
  return `${NUM_2.format(v)}%`
}

// Signed numeric formatting: +X.XX / (X.XX) with green/red coloring.
function SignedCell({ v, decimals = 2 }: { v: number | null; decimals?: number }) {
  if (v == null || v === 0) return <>—</>
  const fmt = decimals === 2 ? NUM_2 : decimals === 1 ? NUM_1 : NUM_0
  if (v < 0)
    return <span style={{ color: 'var(--neg)' }}>({fmt.format(Math.abs(v))})</span>
  if (v > 0)
    return <span style={{ color: 'var(--pos)' }}>+{fmt.format(v)}</span>
  return <>{fmt.format(v)}</>
}

function SignedPctCell({ v }: { v: number | null }) {
  if (v == null || v === 0) return <>—</>
  if (v < 0)
    return <span style={{ color: 'var(--neg)' }}>({NUM_2.format(Math.abs(v))}%)</span>
  if (v > 0)
    return <span style={{ color: 'var(--pos)' }}>+{NUM_2.format(v)}%</span>
  return <>{NUM_2.format(v)}%</>
}

// ── Shared styles ──────────────────────────────────────────────────────────

const TH: React.CSSProperties = {
  padding: '4px 8px', fontSize: 8, fontWeight: 700,
  textTransform: 'uppercase', letterSpacing: '0.16em', fontFamily: "'Hanken Grotesk', sans-serif",
  color: 'var(--text-dim)', backgroundColor: 'var(--header)',
  textAlign: 'left', borderBottom: '1px solid var(--line)',
  whiteSpace: 'nowrap', position: 'sticky', top: 0, zIndex: 3,
}
const TH_R: React.CSSProperties = { ...TH, textAlign: 'right' }
const TD: React.CSSProperties = {
  padding: '4px 8px', fontSize: 12, color: 'var(--text)',
  borderBottom: '1px solid var(--line-soft)',
}
const TD_R: React.CSSProperties = {
  ...TD, textAlign: 'right', fontVariantNumeric: 'tabular-nums',
  fontFamily: "'JetBrains Mono', monospace",
}
const BADGE: React.CSSProperties = {
  display: 'inline-block', padding: '1px 6px', fontSize: 10,
  fontWeight: 600, borderRadius: 1,
}

function typeBadgeStyle(type: string | null): React.CSSProperties {
  const t = (type || '').toLowerCase()
  if (t === 'passive') return { backgroundColor: '#7aadde', color: 'var(--white)' }
  if (t === 'active' || t === 'hedge_fund') return { backgroundColor: 'var(--header)', color: 'var(--white)' }
  return { backgroundColor: 'var(--text-dim)', color: 'var(--text)' }
}

const CENTER_MSG: React.CSSProperties = { padding: 40, fontSize: 14, textAlign: 'center' }

// ── Sub-view types ─────────────────────────────────────────────────────────

type SubView = 'quarterly' | 'holders' | 'cohort'

const SUB_TABS: { id: SubView; label: string }[] = [
  { id: 'quarterly', label: 'Quarterly Summary' },
  { id: 'holders', label: 'Holder Changes' },
  { id: 'cohort', label: 'Cohort Analysis' },
]

// Quarters for the "from" selector on Cohort sub-view (exclude latest
// since you can't cohort-compare latest to itself).
const COHORT_FROM_QUARTERS = ['2025Q3', '2025Q2', '2025Q1']

// ── Main component ─────────────────────────────────────────────────────────

export function OwnershipTrendTab() {
  const { ticker, rollupType } = useAppStore()

  // Local UI state
  const [subView, setSubView] = useState<SubView>('quarterly')
  const [activeOnly, setActiveOnly] = useState(false)
  const [fundView, setFundView] = useState<'hierarchy' | 'fund'>('hierarchy')
  const [cohortFrom, setCohortFrom] = useState('2025Q3')

  const level = fundView === 'fund' ? 'fund' : 'parent'
  const aoStr = activeOnly ? 'true' : 'false'

  // Fetch URLs — null when no ticker, only the active sub-view's URL triggers a fetch
  const trendUrl = ticker && subView === 'quarterly'
    ? `/api/v1/ownership_trend_summary?ticker=${enc(ticker)}&level=${level}&active_only=${aoStr}&rollup_type=${rollupType}`
    : null
  const momentumUrl = ticker && subView === 'holders'
    ? `/api/v1/holder_momentum?ticker=${enc(ticker)}&level=${level}&active_only=${aoStr}&rollup_type=${rollupType}`
    : null
  const cohortUrl = ticker && subView === 'cohort'
    ? `/api/v1/cohort_analysis?ticker=${enc(ticker)}&from=${enc(cohortFrom)}&level=${level}&active_only=${aoStr}&rollup_type=${rollupType}`
    : null

  const trend = useFetchEnvelope<OwnershipTrendResponse>(trendUrl)
  const momentum = useFetch<HolderMomentumRow[]>(momentumUrl)
  const cohort = useFetch<CohortAnalysisResponse>(cohortUrl)

  // Active fetch state
  const loading = subView === 'quarterly' ? trend.loading
    : subView === 'holders' ? momentum.loading
    : cohort.loading
  const error = subView === 'quarterly' ? trend.error
    : subView === 'holders' ? momentum.error
    : cohort.error

  // ── Export ─────────────────────────────────────────────────────────────────

  function onExcel() {
    let csv = ''
    if (subView === 'quarterly' && trend.data) {
      const h = ['Quarter', 'Holders', 'Shares (MM)', '% SO', 'Value ($MM)', 'Active %', 'Passive %', 'Net Change', 'Signal']
      csv = [h, ...trend.data.quarters.map(q => [
        q.quarter, q.holder_count, (q.total_inst_shares / 1e6).toFixed(2),
        q.pct_so.toFixed(2), (q.total_inst_value / 1e6).toFixed(0),
        q.active_pct.toFixed(2), q.passive_pct.toFixed(2),
        q.net_shares_change != null ? (q.net_shares_change / 1e6).toFixed(2) : '',
        q.signal || '',
      ])].map(r => r.join(',')).join('\n')
    } else if (subView === 'holders' && momentum.data) {
      const qKeys = extractQuarterKeys(momentum.data)
      const h = ['Rank', 'Institution', 'Type', ...qKeys.map(q => `${q} Shares (MM)`), 'Change (MM)', 'Chg %']
      csv = [h, ...momentum.data.filter(r => r.level === 0).map(r => [
        r.rank ?? '', `"${(r.institution || '').replace(/"/g, '""')}"`, r.type || '',
        ...qKeys.map(q => { const v = (r as Record<string, unknown>)[q]; return typeof v === 'number' ? (v / 1e6).toFixed(2) : '' }),
        r.change != null ? (r.change / 1e6).toFixed(2) : '', r.change_pct != null ? r.change_pct.toFixed(2) : '',
      ])].map(r => r.join(',')).join('\n')
    } else if (subView === 'cohort' && cohort.data) {
      const h = ['Category', 'Holders', 'Shares (MM)', 'Value ($MM)', 'Avg Position ($MM)', 'Δ Shares (MM)', 'Δ Value ($MM)', '% SO Moved']
      csv = [h, ...cohort.data.detail.map(r => [
        `"${r.category}"`, r.holders, (r.shares / 1e6).toFixed(2), (r.value / 1e6).toFixed(0),
        (r.avg_position / 1e6).toFixed(1),
        r.delta_shares != null ? (r.delta_shares / 1e6).toFixed(2) : '',
        r.delta_value != null ? (r.delta_value / 1e6).toFixed(0) : '',
        r.pct_so_moved.toFixed(2),
      ])].map(r => r.join(',')).join('\n')
    }
    if (!csv) return
    downloadCsv(csv, `ownership_trend_${subView}_${ticker}.csv`)
  }

  if (!ticker) {
    return <div style={CENTER_MSG}><span style={{ color: 'var(--text-dim)' }}>Enter a ticker to load the ownership trend</span></div>
  }

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', backgroundColor: 'var(--panel)', borderRadius: 0, boxShadow: '0 1px 2px rgba(0,0,0,0.04)', overflow: 'hidden' }}>
      <style>{`@media print { .ot-controls { display:none!important } .ot-wrap { height:auto!important; overflow:visible!important } }`}</style>

      {/* Controls bar */}
      <div className="ot-controls" style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'flex-end', gap: 10, padding: '8px 12px', backgroundColor: 'var(--panel)', borderBottom: '1px solid var(--line)', flexShrink: 0 }}>
        {/* Sub-view tabs */}
        <div style={{ display: 'flex', gap: 4 }}>
          {SUB_TABS.map(t => (
            <button key={t.id} type="button" onClick={() => setSubView(t.id)}
              style={{
                padding: '5px 12px', fontSize: 12, borderRadius: 0, cursor: 'pointer',
                fontWeight: subView === t.id ? 600 : 400,
                color: subView === t.id ? 'var(--white)' : 'var(--text-dim)',
                backgroundColor: subView === t.id ? 'var(--header)' : 'transparent',
                border: `1px solid ${subView === t.id ? 'var(--header)' : 'var(--line)'}`,
              }}>
              {t.label}
            </button>
          ))}
        </div>
        <RollupToggle />
        <ActiveOnlyToggle value={activeOnly} onChange={setActiveOnly} label="Active Only" />
        <FundViewToggle value={fundView} onChange={setFundView} />
        {subView === 'cohort' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <span style={{ fontSize: 10, fontWeight: 600, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>From Quarter</span>
            <div style={{ display: 'flex', gap: 4 }}>
              {COHORT_FROM_QUARTERS.map(q => (
                <button key={q} type="button" onClick={() => setCohortFrom(q)}
                  style={{
                    padding: '5px 11px', fontSize: 12, borderRadius: 0, cursor: 'pointer',
                    fontWeight: cohortFrom === q ? 600 : 400,
                    color: cohortFrom === q ? 'var(--white)' : 'var(--text-dim)',
                    backgroundColor: cohortFrom === q ? 'var(--header)' : 'transparent',
                    border: `1px solid ${cohortFrom === q ? 'var(--header)' : 'var(--line)'}`,
                  }}>
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 10 }}>
          <FreshnessBadge tableName="investor_flows" label="flows" />
          <ExportBar onExcel={onExcel} onPrint={() => window.print()} disabled={loading} />
        </div>
      </div>

      {/* Content area */}
      <div className="ot-wrap" style={{ flex: 1, overflowY: 'auto', overflowX: 'auto', position: 'relative' }}>
        {loading && <div style={{ ...CENTER_MSG, color: 'var(--text-dim)' }}>Loading…</div>}
        {error && !loading && <div style={{ ...CENTER_MSG, color: 'var(--neg)' }}>Error: {error}</div>}
        {!loading && !error && subView === 'quarterly' && trend.data && <QuarterlySummaryView data={trend.data} />}
        {!loading && !error && subView === 'holders' && momentum.data && <HolderChangesView data={momentum.data} />}
        {!loading && !error && subView === 'cohort' && cohort.data && <CohortAnalysisView data={cohort.data} />}
      </div>
    </div>
  )
}

// ── Sub-view 1: Quarterly Summary ──────────────────────────────────────────

function QuarterlySummaryView({ data }: { data: OwnershipTrendResponse }) {
  const s = data.summary
  const trendColor = s.trend.includes('↑') ? 'var(--pos)' : s.trend.includes('↓') ? 'var(--neg)' : 'var(--header)'
  const sharesColor = s.total_shares_added >= 0 ? 'var(--pos)' : 'var(--neg)'
  const holdersColor = s.net_new_holders >= 0 ? 'var(--pos)' : 'var(--neg)'

  return (
    <div style={{ padding: 16 }}>
      {/* Summary card */}
      <div style={{ display: 'flex', gap: 24, padding: 16, backgroundColor: 'var(--panel)', border: '1px solid var(--line)', borderRadius: 0, marginBottom: 16 }}>
        <MetricTile label="Trend" value={s.trend} color={trendColor} />
        <MetricTile label="Total Shares Added (MM)" value={`${s.total_shares_added >= 0 ? '+' : ''}${NUM_2.format(s.total_shares_added / 1e6)}`} color={sharesColor} />
        <MetricTile label="Net New Holders" value={`${s.net_new_holders >= 0 ? '+' : ''}${s.net_new_holders}`} color={holdersColor} />
      </div>

      {/* Table */}
      <table style={{ width: '100%', borderCollapse: 'separate', borderSpacing: 0, tableLayout: 'fixed', fontSize: 13 }}>
        <thead>
          <tr>
            <th style={TH}>Quarter</th>
            <th style={TH_R}>Holders</th>
            <th style={TH_R}>Shares (MM)</th>
            <th style={TH_R}>% SO</th>
            <th style={TH_R}>Value ($MM)</th>
            <th style={TH_R}>Active %</th>
            <th style={TH_R}>Passive %</th>
            <th style={TH_R}>Net Change</th>
            <th style={TH}>Signal</th>
          </tr>
        </thead>
        <tbody>
          {data.quarters.map((q: OwnershipTrendQuarter) => (
            <tr key={q.quarter}>
              <td style={{ ...TD, fontWeight: 600 }}>{q.quarter}</td>
              <td style={TD_R}>{NUM_0.format(q.holder_count)}</td>
              <td style={TD_R}>{fmtSharesMm(q.total_inst_shares)}</td>
              <td style={TD_R}>{fmtPct2(q.pct_so)}</td>
              <td style={TD_R}>{fmtValueMm(q.total_inst_value)}</td>
              <td style={TD_R}>{fmtPct2(q.active_pct)}</td>
              <td style={TD_R}>{fmtPct2(q.passive_pct)}</td>
              <td style={TD_R}><SignedCell v={q.net_shares_change != null ? q.net_shares_change / 1e6 : null} /></td>
              <td style={TD}><SignalBadge signal={q.signal} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function SignalBadge({ signal }: { signal: string | null }) {
  if (!signal) return <>—</>
  const color = signal.includes('↑') ? 'var(--pos)' : signal.includes('↓') ? 'var(--neg)' : 'var(--text-dim)'
  return <span style={{ color, fontWeight: 600 }}>{signal}</span>
}

function MetricTile({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div style={{ flex: 1 }}>
      <div style={{ fontSize: 10, fontWeight: 600, textTransform: 'uppercase', color: 'var(--text-dim)', letterSpacing: '0.08em', marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 18, fontWeight: 700, color }}>{value}</div>
    </div>
  )
}

// ── Sub-view 2: Holder Changes ─────────────────────────────────────────────

interface HolderGroup {
  parent: HolderMomentumRow
  children: HolderMomentumRow[]
}

function groupMomentumRows(rows: HolderMomentumRow[]): HolderGroup[] {
  const groups: HolderGroup[] = []
  for (const r of rows) {
    if (r.level === 0) groups.push({ parent: r, children: [] })
    else if (r.level === 1 && groups.length > 0)
      groups[groups.length - 1].children.push(r)
  }
  return groups
}

function extractQuarterKeys(rows: HolderMomentumRow[]): string[] {
  if (!rows.length) return []
  const qRe = /^\d{4}Q\d$/
  return Object.keys(rows[0]).filter(k => qRe.test(k)).sort()
}

function HolderChangesView({ data }: { data: HolderMomentumRow[] }) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const groups = useMemo(() => groupMomentumRows(data), [data])
  const qKeys = useMemo(() => extractQuarterKeys(data), [data])

  function toggle(key: string) {
    setExpanded(prev => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key); else next.add(key)
      return next
    })
  }

  return (
    <div style={{ padding: 16 }}>
      <table style={{ width: '100%', borderCollapse: 'separate', borderSpacing: 0, tableLayout: 'fixed', fontSize: 13 }}>
        <thead>
          <tr>
            <th style={{ ...TH_R, width: 60 }}>Rank</th>
            <th style={TH}>Institution</th>
            <th style={TH}>Type</th>
            {qKeys.map(q => <th key={q} style={TH_R}>{q}</th>)}
            <th style={TH_R}>Change</th>
            <th style={TH_R}>Chg %</th>
          </tr>
        </thead>
        <tbody>
          {groups.flatMap(g => {
            const pkey = `${g.parent.rank}:${g.parent.institution}`
            const canExpand = g.children.length >= 2
            const isOpen = expanded.has(pkey)
            const trs = [renderMomentumRow(g.parent, pkey, 0, canExpand, isOpen, toggle, qKeys)]
            if (isOpen) {
              g.children.forEach((c, ci) => {
                trs.push(renderMomentumRow(c, `${pkey}:${ci}`, 1, false, false, toggle, qKeys, String(ci + 1)))
              })
            }
            return trs
          })}
          {groups.length === 0 && (
            <tr><td colSpan={5 + qKeys.length} style={{ ...TD, textAlign: 'center', padding: 30, color: 'var(--text-dim)' }}>No data</td></tr>
          )}
        </tbody>
      </table>
    </div>
  )
}

function renderMomentumRow(
  row: HolderMomentumRow, key: string, indent: 0 | 1,
  canExpand: boolean, isOpen: boolean, toggle: (k: string) => void,
  qKeys: string[], displayRank?: string,
) {
  const bg: React.CSSProperties = { backgroundColor: indent === 1 ? 'var(--panel)' : 'transparent' }
  const nameCell: React.CSSProperties = {
    ...TD, paddingLeft: indent === 1 ? 24 : 10,
    fontWeight: indent === 0 ? 600 : 400,
    color: indent === 0 ? 'var(--text)' : 'var(--text-mute)',
    fontSize: indent === 1 ? 12 : 13,
    cursor: canExpand ? 'pointer' : 'default', userSelect: 'none',
    whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
  }
  return (
    <tr key={key} style={bg}>
      <td style={{ ...TD, textAlign: 'right', fontWeight: indent === 0 ? 700 : 400, color: indent === 0 ? 'var(--text-dim)' : 'var(--text-dim)', fontSize: indent === 1 ? 12 : 13, width: 60 }}>
        {displayRank ?? row.rank ?? ''}
      </td>
      <td style={nameCell} title={row.institution} onClick={canExpand ? () => toggle(key) : undefined}>
        {indent === 0 && (
          <span style={{ display: 'inline-block', width: 14, color: 'var(--text-dim)', fontSize: 10 }}>
            {canExpand ? (isOpen ? '▼' : '▶') : ''}
          </span>
        )}
        {row.institution}
      </td>
      <td style={TD}>
        {row.type && <span style={{ ...BADGE, ...typeBadgeStyle(row.type) }}>{row.type}</span>}
      </td>
      {qKeys.map(q => {
        const v = (row as Record<string, unknown>)[q]
        return <td key={q} style={TD_R}>{typeof v === 'number' ? fmtSharesMm(v) : '—'}</td>
      })}
      <td style={TD_R}><SignedCell v={row.change != null ? row.change / 1e6 : null} /></td>
      <td style={TD_R}><SignedPctCell v={row.change_pct} /></td>
    </tr>
  )
}

// ── Sub-view 3: Cohort Analysis ────────────────────────────────────────────

const COHORT_COLORS: Record<string, React.CSSProperties> = {
  'Retained': { borderLeft: '3px solid var(--header)' },
  'Increased': { borderLeft: '3px solid var(--pos)' },
  'Decreased': { borderLeft: '3px solid var(--neg)' },
  'Unchanged': { borderLeft: '3px solid var(--text-dim)' },
  'New Entries': { backgroundColor: 'rgba(92,184,122,0.08)', borderLeft: '3px solid var(--pos)' },
  'Exits': { backgroundColor: 'rgba(224,90,90,0.08)', borderLeft: '3px solid var(--neg)' },
}

function CohortAnalysisView({ data }: { data: CohortAnalysisResponse }) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const s = data.summary

  function toggle(key: string) {
    setExpanded(prev => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key); else next.add(key)
      return next
    })
  }

  return (
    <div style={{ padding: 16 }}>
      <table style={{ width: '100%', borderCollapse: 'separate', borderSpacing: 0, tableLayout: 'fixed', fontSize: 13 }}>
        <thead>
          <tr>
            <th style={TH}>Category</th>
            <th style={TH_R}>Holders</th>
            <th style={TH_R}>Shares (MM)</th>
            <th style={TH_R}>Value ($MM)</th>
            <th style={TH_R}>Avg Position ($MM)</th>
            <th style={TH_R}>Δ Shares (MM)</th>
            <th style={TH_R}>Δ Value ($MM)</th>
            <th style={TH_R}>% SO Moved</th>
          </tr>
        </thead>
        <tbody>
          {data.detail.map((r: CohortDetailRow) => {
            const isTotal = r.is_total
            const cohortStyle = COHORT_COLORS[r.category] || {}
            const isOpen = expanded.has(r.category)
            const canExpand = r.has_children && r.children && r.children.length > 0

            const rowStyle: React.CSSProperties = isTotal
              ? { backgroundColor: 'var(--header)' }
              : { ...cohortStyle }
            const cellColor = isTotal ? 'var(--white)' : 'var(--text)'
            const cellWeight = (isTotal || r.level === 0) ? 600 : 400

            const trs = [(
              <tr key={r.category} style={rowStyle}>
                <td style={{ ...TD, fontWeight: cellWeight, color: cellColor, cursor: canExpand ? 'pointer' : 'default', userSelect: 'none', paddingLeft: r.level === 1 ? 24 : 10, ...(isTotal ? { backgroundColor: 'var(--header)' } : {}) }}
                  onClick={canExpand ? () => toggle(r.category) : undefined}>
                  {canExpand && (
                    <span style={{ display: 'inline-block', width: 14, color: isTotal ? 'var(--white)' : 'var(--text-dim)', fontSize: 10 }}>
                      {isOpen ? '▼' : '▶'}
                    </span>
                  )}
                  {r.category}
                </td>
                <td style={{ ...TD_R, color: cellColor, fontWeight: cellWeight, ...(isTotal ? { backgroundColor: 'var(--header)' } : {}) }}>{NUM_0.format(r.holders)}</td>
                <td style={{ ...TD_R, color: cellColor, fontWeight: cellWeight, ...(isTotal ? { backgroundColor: 'var(--header)' } : {}) }}>{fmtSharesMm(r.shares)}</td>
                <td style={{ ...TD_R, color: cellColor, fontWeight: cellWeight, ...(isTotal ? { backgroundColor: 'var(--header)' } : {}) }}>{fmtValueMm(r.value)}</td>
                <td style={{ ...TD_R, color: cellColor, fontWeight: cellWeight, ...(isTotal ? { backgroundColor: 'var(--header)' } : {}) }}>{`$${NUM_1.format(r.avg_position / 1e6)}`}</td>
                <td style={{ ...TD_R, ...(isTotal ? { backgroundColor: 'var(--header)', color: cellColor, fontWeight: cellWeight } : {}) }}><SignedCell v={r.delta_shares != null ? r.delta_shares / 1e6 : null} /></td>
                <td style={{ ...TD_R, ...(isTotal ? { backgroundColor: 'var(--header)', color: cellColor, fontWeight: cellWeight } : {}) }}><SignedCell v={r.delta_value != null ? r.delta_value / 1e6 : null} decimals={0} /></td>
                <td style={{ ...TD_R, color: cellColor, fontWeight: cellWeight, ...(isTotal ? { backgroundColor: 'var(--header)' } : {}) }}>{fmtPct2(r.pct_so_moved)}</td>
              </tr>
            )]

            if (isOpen && r.children) {
              r.children.forEach((c, ci) => {
                trs.push(
                  <tr key={`${r.category}:${ci}`} style={{ backgroundColor: 'var(--panel)' }}>
                    <td style={{ ...TD, paddingLeft: 32, fontWeight: 400, color: 'var(--text-mute)', fontSize: 12 }}>
                      {ci + 1}. {c.category}
                    </td>
                    <td style={TD_R}>{NUM_0.format(c.holders)}</td>
                    <td style={TD_R}>{fmtSharesMm(c.shares)}</td>
                    <td style={TD_R}>{fmtValueMm(c.value)}</td>
                    <td style={TD_R}>{`$${NUM_1.format(c.avg_position / 1e6)}`}</td>
                    <td style={TD_R}><SignedCell v={c.delta_shares != null ? c.delta_shares / 1e6 : null} /></td>
                    <td style={TD_R}><SignedCell v={c.delta_value != null ? c.delta_value / 1e6 : null} decimals={0} /></td>
                    <td style={TD_R}>{fmtPct2(c.pct_so_moved)}</td>
                  </tr>
                )
              })
            }

            return trs
          }).flat()}
        </tbody>
      </table>

      {/* Summary metrics */}
      <div style={{ display: 'flex', gap: 24, padding: 16, backgroundColor: 'var(--panel)', border: '1px solid var(--line)', borderRadius: 0, marginTop: 16 }}>
        <MetricTile label={`${s.from_quarter} → ${s.to_quarter}`} value="Cohort Analysis" color="var(--header)" />
        <MetricTile label="Retention Rate" value={`${NUM_2.format(s.retention_rate)}%`} color="var(--header)" />
        <MetricTile label="Economic Retention" value={`${NUM_2.format(s.econ_retention)}%`} color="var(--header)" />
        <MetricTile label="Net Holders" value={`${s.net_holders >= 0 ? '+' : ''}${s.net_holders}`} color={s.net_holders >= 0 ? 'var(--pos)' : 'var(--neg)'} />
        <MetricTile label="Net Shares (MM)" value={`${s.net_shares >= 0 ? '+' : ''}${NUM_2.format(s.net_shares / 1e6)}`} color={s.net_shares >= 0 ? 'var(--pos)' : 'var(--neg)'} />
        <MetricTile label="Net Value ($MM)" value={`${s.net_value >= 0 ? '+' : ''}$${NUM_0.format(s.net_value / 1e6)}`} color={s.net_value >= 0 ? 'var(--pos)' : 'var(--neg)'} />
      </div>
    </div>
  )
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function enc(s: string): string { return encodeURIComponent(s) }

function downloadCsv(csv: string, filename: string) {
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}
