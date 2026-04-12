import { useEffect, useMemo, useRef, useState } from 'react'
import { useAppStore } from '../../store/useAppStore'
import { useFetch } from '../../hooks/useFetch'
import type { ConvictionResponse, ConvictionRow } from '../../types/api'
import {
  RollupToggle,
  FundViewToggle,
  ActiveOnlyToggle,
  InvestorTypeFilter,
  ExportBar,
  TableFooter,
  ColumnGroupHeader,
} from '../common'

// ── Formatters ─────────────────────────────────────────────────────────────

const NUM_0 = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 })
const NUM_1 = new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 })

function fmtValueMm(v: number | null): string {
  if (v == null) return '—'
  return `$${NUM_0.format(v / 1e6)}`
}

function fmtPct1(v: number | null): string {
  if (v == null) return '—'
  return `${NUM_1.format(v)}%`
}

function fmtInt(v: number | null): string {
  if (v == null) return '—'
  return String(Math.round(v))
}

function SignedPct1({ v }: { v: number | null }) {
  if (v == null) return <>—</>
  if (v < 0) return <span style={{ color: '#ef4444' }}>({NUM_1.format(Math.abs(v))})</span>
  if (v > 0) return <span style={{ color: '#27AE60' }}>+{NUM_1.format(v)}</span>
  return <>{NUM_1.format(v)}</>
}

// ── Styles ─────────────────────────────────────────────────────────────────

const TH: React.CSSProperties = {
  padding: '9px 10px', fontSize: 11, fontWeight: 700,
  textTransform: 'uppercase', letterSpacing: '0.04em',
  color: '#ffffff', backgroundColor: 'var(--oxford-blue)',
  textAlign: 'left', borderBottom: '1px solid #1e2d47',
  whiteSpace: 'nowrap', position: 'sticky', top: 0, zIndex: 3,
}
const TH_R: React.CSSProperties = { ...TH, textAlign: 'right' }
const TD: React.CSSProperties = {
  padding: '7px 10px', fontSize: 13, color: '#1e293b',
  borderBottom: '1px solid #e5e7eb',
}
const TD_R: React.CSSProperties = {
  ...TD, textAlign: 'right', fontVariantNumeric: 'tabular-nums',
}
const BADGE: React.CSSProperties = {
  display: 'inline-block', padding: '2px 8px', fontSize: 11,
  fontWeight: 600, borderRadius: 3,
}
const CENTER_MSG: React.CSSProperties = { padding: 40, fontSize: 14, textAlign: 'center' }

function typeBadgeStyle(type: string | null): React.CSSProperties {
  const t = (type || '').toLowerCase()
  if (t === 'passive') return { backgroundColor: '#4A90D9', color: '#fff' }
  if (t === 'active' || t === 'hedge_fund') return { backgroundColor: '#002147', color: '#fff' }
  return { backgroundColor: '#cbd5e1', color: '#1e293b' }
}

function nportBadgeStyle(cov: number | null | undefined): React.CSSProperties | null {
  if (cov == null || cov <= 0) return null
  if (cov >= 80) return { backgroundColor: '#27AE60', color: '#fff' }
  if (cov >= 50) return { backgroundColor: '#F5A623', color: '#fff' }
  return { backgroundColor: '#94a3b8', color: '#fff' }
}

function scoreColor(s: number | null): string {
  if (s == null) return '#1e293b'
  if (s >= 70) return '#27AE60'
  if (s >= 40) return '#F5A623'
  return '#ef4444'
}

// ── Grouping ───────────────────────────────────────────────────────────────

interface ConvictionGroup { parent: ConvictionRow; children: ConvictionRow[] }

function groupRows(rows: ConvictionRow[]): ConvictionGroup[] {
  const groups: ConvictionGroup[] = []
  for (const r of rows) {
    if (r.level === 0) groups.push({ parent: r, children: [] })
    else if (r.level === 1 && groups.length > 0)
      groups[groups.length - 1].children.push(r)
  }
  return groups
}

// ── Fund-view rows ─────────────────────────────────────────────────────────

interface FundRow extends ConvictionRow { parentInstitution: string }

const TOTAL_COLS = 13

// ── InvestorSearchWithDropdown (local, same pattern as Register) ──────────

interface SearchProps { data: ConvictionRow[]; onSelect: (inst: string | null) => void }

function InvestorSearchWithDropdown({ data, onSelect }: SearchProps) {
  const [value, setValue] = useState('')
  const [open, setOpen] = useState(false)
  const [focused, setFocused] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  const matches = useMemo(() => {
    if (value.length < 1) return [] as ConvictionRow[]
    const q = value.toLowerCase()
    return data.filter(r => r.level === 0 && r.institution.toLowerCase().includes(q)).slice(0, 10)
  }, [data, value])

  useEffect(() => {
    function h(e: MouseEvent) { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false) }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [])

  function select(inst: string) { setValue(inst); setOpen(false); onSelect(inst) }
  function clear() { setValue(''); setOpen(false); onSelect(null) }

  return (
    <div ref={ref} style={{ position: 'relative', display: 'inline-block' }}>
      <input type="text" value={value} placeholder="Search investor…"
        autoComplete="off" autoCorrect="off" spellCheck={false}
        onChange={e => { setValue(e.target.value); setOpen(e.target.value.length > 0) }}
        onFocus={() => { setFocused(true); if (value.length > 0) setOpen(true) }}
        onBlur={() => setFocused(false)}
        style={{ width: 200, padding: '6px 28px 6px 10px', fontSize: 13, color: '#1e293b', backgroundColor: '#fff', border: `1px solid ${focused ? 'var(--glacier-blue)' : '#e2e8f0'}`, borderRadius: 4, outline: 'none', transition: 'border-color 0.1s' }}
      />
      {value && <button type="button" onClick={clear} aria-label="Clear" style={{ position: 'absolute', right: 6, top: '50%', transform: 'translateY(-50%)', width: 18, height: 18, padding: 0, lineHeight: '16px', fontSize: 14, color: '#94a3b8', backgroundColor: 'transparent', border: 'none', cursor: 'pointer' }}>×</button>}
      {open && matches.length > 0 && (
        <div style={{ position: 'absolute', top: '100%', left: 0, marginTop: 2, width: 280, maxHeight: 240, overflowY: 'auto', backgroundColor: '#fff', border: '1px solid #e2e8f0', borderRadius: 4, boxShadow: '0 4px 12px rgba(0,0,0,0.08)', zIndex: 1000 }}>
          {matches.map(m => (
            <div key={m.institution} onMouseDown={() => select(m.institution)}
              style={{ padding: '7px 12px', fontSize: 13, color: '#1e293b', cursor: 'pointer' }}
              onMouseEnter={e => (e.currentTarget.style.backgroundColor = '#f4f6f9')}
              onMouseLeave={e => (e.currentTarget.style.backgroundColor = 'transparent')}>
              {m.institution}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Component ──────────────────────────────────────────────────────────────

export function ConvictionTab() {
  const { ticker, rollupType } = useAppStore()

  const [fundView, setFundView] = useState<'hierarchy' | 'fund'>('hierarchy')
  const [activeOnly, setActiveOnly] = useState(false)
  const [selectedTypes, setSelectedTypes] = useState<Set<string> | null>(null)
  const [selectedInstitution, setSelectedInstitution] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [scoreTooltipOpen, setScoreTooltipOpen] = useState(false)

  const tableWrapRef = useRef<HTMLDivElement>(null)

  function toggle(key: string) {
    setExpanded(prev => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key); else next.add(key)
      return next
    })
  }

  const level = fundView === 'fund' ? 'fund' : 'parent'
  const url = ticker
    ? `/api/portfolio_context?ticker=${enc(ticker)}&level=${level}&active_only=${activeOnly}&rollup_type=${rollupType}`
    : null
  const { data, loading, error } = useFetch<ConvictionResponse>(url)

  useEffect(() => { setSelectedInstitution(null) }, [ticker, rollupType])

  const availableTypes = useMemo(() => {
    if (!data) return [] as string[]
    const seen = new Set<string>()
    for (const r of data.rows) { if (r.level === 0 && r.type) seen.add(r.type) }
    return Array.from(seen).sort()
  }, [data])

  const effectiveTypes = selectedTypes ?? new Set(availableTypes)

  const groups = useMemo(() => {
    if (!data) return []
    return groupRows(data.rows).filter(g => {
      const t = (g.parent.type || '').toLowerCase()
      return effectiveTypes.size === 0 || effectiveTypes.has(t)
    })
  }, [data, effectiveTypes])

  const fundRows = useMemo<FundRow[]>(() => {
    if (fundView !== 'fund') return []
    const flat: FundRow[] = []
    for (const g of groups) {
      for (const c of g.children)
        flat.push({ ...c, parentInstitution: g.parent.institution })
    }
    flat.sort((a, b) => (b.value || 0) - (a.value || 0))
    return flat.map((r, i) => ({ ...r, rank: i + 1 }))
  }, [groups, fundView])

  const fundRowsDisplay = useMemo(() => {
    if (fundView !== 'fund' || selectedInstitution == null) return fundRows
    return fundRows.filter(r => r.parentInstitution === selectedInstitution)
  }, [fundRows, fundView, selectedInstitution])

  const visibleSums = useMemo(() => {
    const rows: ConvictionRow[] = fundView === 'fund' ? fundRowsDisplay : groups.map(g => g.parent)
    let value = 0
    for (const r of rows) value += r.value || 0
    return { count: rows.length, value }
  }, [groups, fundRowsDisplay, fundView])

  function handleSearchSelect(inst: string | null) {
    setSelectedInstitution(inst)
    if (inst == null || fundView === 'fund') return
    requestAnimationFrame(() => {
      const wrap = tableWrapRef.current
      if (!wrap) return
      const escaped = inst.replace(/"/g, '\\"')
      const el = wrap.querySelector(`tr[data-institution="${escaped}"]`) as HTMLElement | null
      if (!el) return
      el.scrollIntoView({ behavior: 'smooth', block: 'center' })
      el.classList.add('conviction-row-highlight')
      window.setTimeout(() => el.classList.remove('conviction-row-highlight'), 2000)
    })
  }

  function onExcel() {
    const h = ['Rank', 'Institution', 'Type', 'Value ($MM)', 'Sector %', 'vs SPX',
      'Score', 'Sector Rank', 'Co. Rank', 'Ind. Rank', 'Top 3', 'Diversity', 'Port. Coverage']
    const rows: ConvictionRow[] = fundView === 'fund' ? fundRowsDisplay
      : groups.flatMap(g => [g.parent, ...g.children])
    const csv = [h, ...rows.map(r => [
      r.rank ?? '', `"${(r.institution || '').replace(/"/g, '""')}"`, r.type || '',
      r.value != null ? (r.value / 1e6).toFixed(0) : '',
      r.subject_sector_pct != null ? r.subject_sector_pct.toFixed(1) : '',
      r.vs_spx != null ? r.vs_spx.toFixed(1) : '',
      r.conviction_score != null ? Math.round(r.conviction_score) : '',
      r.sector_rank ?? '', r.co_rank_in_sector ?? '', r.industry_rank ?? '',
      (r.top3 || []).join(', '), r.diversity ?? '',
      r.nport_cov != null ? Math.round(r.nport_cov) : '',
    ])].map(r => r.join(',')).join('\n')
    downloadCsv(csv, `conviction_${ticker}.csv`)
  }

  if (!ticker) return <div style={CENTER_MSG}><span style={{ color: '#94a3b8' }}>Enter a ticker to load conviction analysis</span></div>

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', backgroundColor: 'var(--card-bg)', borderRadius: 6, boxShadow: '0 1px 2px rgba(0,0,0,0.04)', overflow: 'hidden' }}>
      <style>{`
        @media print { .cv-controls { display:none!important } .cv-wrap { height:auto!important; overflow:visible!important } }
        .conviction-row-highlight > td { background-color: #fffbeb !important; transition: background-color 0.4s ease-in-out; }
      `}</style>

      {/* Controls bar */}
      <div className="cv-controls" style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'flex-end', gap: 16, padding: '12px 16px', backgroundColor: '#f8fafc', borderBottom: '1px solid #e2e8f0', flexShrink: 0 }}>
        <RollupToggle />
        <FundViewToggle value={fundView} onChange={setFundView} />
        <ActiveOnlyToggle value={activeOnly} onChange={setActiveOnly} label="Active Only" />
        {availableTypes.length > 0 && (
          <InvestorTypeFilter available={availableTypes} selected={effectiveTypes} onChange={setSelectedTypes} />
        )}
        <InvestorSearchWithDropdown data={data?.rows ?? []} onSelect={handleSearchSelect} />
        <div style={{ marginLeft: 'auto' }}>
          <ExportBar onExcel={onExcel} onPrint={() => window.print()} disabled={!data} />
        </div>
      </div>

      {/* Content */}
      <div ref={tableWrapRef} className="cv-wrap" style={{ flex: 1, overflowY: 'auto', overflowX: 'auto', position: 'relative' }}>
        {loading && <div style={{ ...CENTER_MSG, color: '#94a3b8' }}>Loading…</div>}
        {error && !loading && <div style={{ ...CENTER_MSG, color: '#ef4444' }}>Error: {error}</div>}
        {data && !loading && (
          <div style={{ padding: 16 }}>
            {/* Subject sector card */}
            <div style={{ display: 'flex', gap: 32, padding: '10px 16px', backgroundColor: 'var(--card-bg)', border: '1px solid #e2e8f0', borderRadius: 6, marginBottom: 12 }}>
              {data.subject_sector ? (
                <>
                  <InfoChip label="Sector" value={data.subject_sector} />
                  <InfoChip label="Industry" value={data.subject_industry || '—'} />
                  <InfoChip label="SPX Weight" value={data.subject_spx_weight != null ? `${NUM_1.format(data.subject_spx_weight)}%` : '—'} />
                </>
              ) : (
                <span style={{ color: '#94a3b8', fontSize: 13 }}>Sector data unavailable</span>
              )}
            </div>

            {/* Table */}
            <table style={{ width: '100%', borderCollapse: 'separate', borderSpacing: 0, tableLayout: 'fixed', fontSize: 13 }}>
              <colgroup>
                <col style={{ width: 50 }} />   {/* Rank */}
                <col />                          {/* Institution — flex */}
                <col style={{ width: 90 }} />    {/* Type */}
                <col style={{ width: 100 }} />   {/* Value */}
                <col style={{ width: 80 }} />    {/* Sector % */}
                <col style={{ width: 75 }} />    {/* vs SPX */}
                <col style={{ width: 65 }} />    {/* Score */}
                <col style={{ width: 85 }} />    {/* Sector Rank */}
                <col style={{ width: 80 }} />    {/* Co. Rank */}
                <col style={{ width: 80 }} />    {/* Ind. Rank */}
                <col style={{ width: 130 }} />   {/* Top 3 */}
                <col style={{ width: 70 }} />    {/* Diversity */}
                <col style={{ width: 105 }} />   {/* Port. Coverage */}
              </colgroup>
              <thead>
                <ColumnGroupHeader groups={[
                  { label: '', colSpan: 3 },
                  { label: 'Position', colSpan: 3 },
                  { label: 'Conviction', colSpan: 4 },
                  { label: 'Portfolio', colSpan: 3 },
                ]} />
                <tr>
                  <th style={TH_R}>Rank</th>
                  <th style={TH}>Institution</th>
                  <th style={TH}>Type</th>
                  <th style={TH_R}>Value ($MM)</th>
                  <th style={TH_R}>Sector %</th>
                  <th style={TH_R}>vs SPX</th>
                  <th style={TH_R} onMouseEnter={() => setScoreTooltipOpen(true)} onMouseLeave={() => setScoreTooltipOpen(false)}>
                    <span style={{ position: 'relative', display: 'inline-block' }}>
                      Score
                      <span style={{ cursor: 'help', color: '#94a3b8', fontSize: 12, marginLeft: 3 }}>ⓘ</span>
                      {scoreTooltipOpen && (
                        <span style={{ position: 'absolute', top: '100%', left: '50%', transform: 'translateX(-50%)', zIndex: 1000, marginTop: 4, backgroundColor: '#0d1526', color: '#e2e8f0', fontSize: 11, lineHeight: 1.6, padding: '8px 12px', borderRadius: 4, border: '1px solid #2d3f5e', width: 220, whiteSpace: 'pre-line', textAlign: 'left', fontWeight: 400, textTransform: 'none', letterSpacing: 0, display: 'block' }}>
                          <span style={{ display: 'block', fontWeight: 600, marginBottom: 4 }}>Conviction Score 0–100</span>
                          <span style={{ display: 'block' }}>Sector overweight vs SPX (+40)</span>
                          <span style={{ display: 'block' }}>Sector rank in portfolio (+20/10/5)</span>
                          <span style={{ display: 'block' }}>Company rank in sector (+15/10/5)</span>
                          <span style={{ display: 'block' }}>Industry rank (+15/10/5)</span>
                        </span>
                      )}
                    </span>
                  </th>
                  <th style={TH_R}>Sector Rank</th>
                  <th style={TH_R}>Co. Rank</th>
                  <th style={TH_R}>Ind. Rank</th>
                  <th style={TH}>Top 3 Sectors</th>
                  <th style={TH_R}>Diversity</th>
                  <th style={TH}>Port. Coverage</th>
                </tr>
              </thead>
              <tbody>
                {fundView === 'fund'
                  ? fundRowsDisplay.map(r => renderRow(r, `f:${r.rank}`, 0, false, false, toggle))
                  : groups.flatMap(g => {
                      const pkey = `${g.parent.rank}:${g.parent.institution}`
                      const canExpand = g.children.length >= 2
                      const isOpen = expanded.has(pkey)
                      const trs = [renderRow(g.parent, pkey, 0, canExpand, isOpen, toggle)]
                      if (isOpen) {
                        g.children.forEach((c, ci) => {
                          trs.push(renderRow(c, `${pkey}:${ci}`, 1, false, false, toggle, String(ci + 1)))
                        })
                      }
                      return trs
                    })
                }
                {(fundView === 'fund' ? fundRowsDisplay.length : groups.length) === 0 && (
                  <tr><td colSpan={TOTAL_COLS} style={{ ...TD, textAlign: 'center', padding: 30, color: '#64748b' }}>No rows match the current filters</td></tr>
                )}
              </tbody>
              <TableFooter totalColumns={TOTAL_COLS} rows={[{
                label: `Top ${visibleSums.count} Shown`,
                shares_mm: null,
                value_mm: visibleSums.value / 1e6,
                pct_float: null,
              }]} />
            </table>
          </div>
        )}
      </div>
    </div>
  )

}

// ── Helpers outside component ────────────────────────────────────────────

function InfoChip({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div style={{ fontSize: 10, fontWeight: 600, textTransform: 'uppercase', color: '#94a3b8', letterSpacing: '0.08em', marginBottom: 2 }}>{label}</div>
      <div style={{ fontSize: 13, color: '#1e293b' }}>{value}</div>
    </div>
  )
}

function renderRow(
  row: ConvictionRow, key: string, indent: 0 | 1,
  canExpand: boolean, isOpen: boolean, toggle: (k: string) => void,
  displayRank?: string,
) {
  const bg: React.CSSProperties = { backgroundColor: indent === 1 ? '#f8fafc' : '#fff' }
  const nameCell: React.CSSProperties = {
    ...TD, paddingLeft: indent === 1 ? 24 : 10,
    fontWeight: indent === 0 ? 600 : 400,
    color: indent === 0 ? '#0f172a' : '#475569',
    fontSize: indent === 1 ? 12 : 13,
    cursor: canExpand ? 'pointer' : 'default', userSelect: 'none',
    whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: 0,
  }
  const nport = nportBadgeStyle(row.nport_cov)
  return (
    <tr key={key} style={bg} data-institution={indent === 0 ? row.institution : undefined}>
      <td style={{ ...TD, textAlign: 'right', fontWeight: indent === 0 ? 700 : 400, color: indent === 0 ? '#64748b' : '#94a3b8', fontSize: indent === 1 ? 12 : 13 }}>
        {displayRank ?? row.rank ?? ''}
      </td>
      <td style={nameCell} title={row.institution} onClick={canExpand ? () => toggle(key) : undefined}>
        {indent === 0 && <span style={{ display: 'inline-block', width: 14, color: '#64748b', fontSize: 10 }}>{canExpand ? (isOpen ? '▼' : '▶') : ''}</span>}
        {row.institution}
      </td>
      <td style={TD}><span style={{ ...BADGE, ...typeBadgeStyle(row.type) }}>{row.type || 'unknown'}</span></td>
      <td style={TD_R}>{fmtValueMm(row.value)}</td>
      <td style={TD_R}>{fmtPct1(row.subject_sector_pct)}</td>
      <td style={TD_R}><SignedPct1 v={row.vs_spx} /></td>
      <td style={{ ...TD_R, fontWeight: 700, color: scoreColor(row.conviction_score) }}>{row.conviction_score != null ? Math.round(row.conviction_score) : '—'}</td>
      <td style={TD_R}>{fmtInt(row.sector_rank)}</td>
      <td style={TD_R}>{fmtInt(row.co_rank_in_sector)}</td>
      <td style={TD_R}>{fmtInt(row.industry_rank)}</td>
      <td style={TD}>
        <div style={{ display: 'flex', gap: 3, flexWrap: 'wrap' }}>
          {(row.top3 || []).map((s, i) => (
            <span key={i} style={{ backgroundColor: '#f4f6f9', color: '#475569', borderRadius: 10, padding: '2px 6px', fontSize: 11 }}>{s}</span>
          ))}
        </div>
      </td>
      <td style={TD_R}>{fmtInt(row.diversity)}</td>
      <td style={TD}>
        {nport && row.nport_cov != null ? (
          <span style={{ ...BADGE, ...nport, display: 'inline-block', minWidth: 48, textAlign: 'center' }}>{Math.round(row.nport_cov)}%</span>
        ) : '—'}
      </td>
    </tr>
  )
}

function enc(s: string) { return encodeURIComponent(s) }

function downloadCsv(csv: string, filename: string) {
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
  const u = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = u; a.download = filename
  document.body.appendChild(a); a.click()
  document.body.removeChild(a); URL.revokeObjectURL(u)
}
