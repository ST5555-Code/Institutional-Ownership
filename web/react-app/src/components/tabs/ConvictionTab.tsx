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
  getTypeStyle,
} from '../common'

// ── Formatters ─────────────────────────────────────────────────────────────

const NUM_0 = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 })
const NUM_1 = new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 })
const NUM_2 = new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

function fmtValueMm(v: number | null): string {
  if (v == null) return '—'
  return `$${NUM_0.format(v / 1e6)}`
}

function fmtPct2(v: number | null): string {
  if (v == null) return '—'
  return `${NUM_2.format(v)}%`
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
  // top: 30 sits below the sticky ColumnGroupHeader row (~30px tall)
  // so the sandstone underline stays visible during scroll.
  whiteSpace: 'nowrap', position: 'sticky', top: 30, zIndex: 3,
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

function nportBadgeStyle(cov: number | null | undefined): React.CSSProperties | null {
  if (cov == null || cov <= 0) return null
  if (cov >= 80) return { backgroundColor: '#27AE60', color: '#fff' }
  if (cov >= 50) return { backgroundColor: '#F5A623', color: '#fff' }
  return { backgroundColor: '#94a3b8', color: '#fff' }
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

interface FundRow extends ConvictionRow { parentInstitution: string }

const TOTAL_COLS = 14

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

  const tableWrapRef = useRef<HTMLDivElement>(null)

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

  // Fund view: when level=fund the API returns fund-series rows directly
  // at level=0 (no parent/child hierarchy). Use the parent rows from the
  // filtered groups — they ARE the fund data. Don't try to extract
  // children (there are none when level=fund).
  const fundRows = useMemo<FundRow[]>(() => {
    if (fundView !== 'fund') return []
    const flat: FundRow[] = groups.map(g => ({
      ...g.parent,
      parentInstitution: g.parent.institution,
    }))
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

  function toggle(key: string) {
    setExpanded(prev => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key); else next.add(key)
      return next
    })
  }

  function handleSearchSelect(inst: string | null) {
    setSelectedInstitution(inst)
    if (inst == null || fundView === 'fund') return
    requestAnimationFrame(() => {
      const wrap = tableWrapRef.current
      if (!wrap) return
      const el = wrap.querySelector(`tr[data-institution="${inst.replace(/"/g, '\\"')}"]`) as HTMLElement | null
      if (!el) return
      el.scrollIntoView({ behavior: 'smooth', block: 'center' })
      el.classList.add('cv-row-highlight')
      window.setTimeout(() => el.classList.remove('cv-row-highlight'), 2000)
    })
  }

  function onExcel() {
    const h = ['Rank', 'Institution', 'Type', 'Value ($MM)', 'Sector %', 'vs SPX',
      'Sector Rank', 'Co. Rank', 'Ind. Rank', 'Sector 1', 'S1 %', 'Sector 2', 'S2 %',
      'Sector 3', 'S3 %', 'Diversity', 'Port. Coverage']
    const rows: ConvictionRow[] = fundView === 'fund' ? fundRowsDisplay
      : groups.flatMap(g => [g.parent, ...g.children])
    const csv = [h, ...rows.map(r => [
      r.rank ?? '', `"${(r.institution || '').replace(/"/g, '""')}"`, r.type || '',
      r.value != null ? (r.value / 1e6).toFixed(0) : '',
      r.subject_sector_pct != null ? r.subject_sector_pct.toFixed(2) : '',
      r.vs_spx != null ? r.vs_spx.toFixed(2) : '',
      r.sector_rank ?? '', r.co_rank_in_sector ?? '', r.industry_rank ?? '',
      r.top3[0]?.code ?? '', r.top3[0]?.weight_pct ?? '',
      r.top3[1]?.code ?? '', r.top3[1]?.weight_pct ?? '',
      r.top3[2]?.code ?? '', r.top3[2]?.weight_pct ?? '',
      r.diversity ?? '',
      r.nport_cov != null ? Math.round(r.nport_cov) : '',
    ])].map(r => r.join(',')).join('\n')
    downloadCsv(csv, `conviction_${ticker}.csv`)
  }

  if (!ticker) return <div style={CENTER_MSG}><span style={{ color: '#94a3b8' }}>Enter a ticker to load conviction analysis</span></div>

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', backgroundColor: 'var(--card-bg)', borderRadius: 6, boxShadow: '0 1px 2px rgba(0,0,0,0.04)', overflow: 'hidden' }}>
      <style>{`
        @media print { .cv-controls { display:none!important } .cv-wrap { height:auto!important; overflow:visible!important } }
        .cv-row-highlight > td { background-color: #fffbeb !important; transition: background-color 0.4s ease-in-out; }
      `}</style>

      {/* Controls */}
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
                  <InfoChip label="SPX Weight" value={data.subject_spx_weight != null ? `${NUM_2.format(data.subject_spx_weight)}%` : '—'} />
                </>
              ) : (
                <span style={{ color: '#94a3b8', fontSize: 13 }}>Sector data unavailable</span>
              )}
            </div>

            {/* Table */}
            <table style={{ width: '100%', borderCollapse: 'separate', borderSpacing: 0, tableLayout: 'fixed', fontSize: 13 }}>
              <colgroup>
                {/* Match Register widths for first 3 cols */}
                <col style={{ width: 60 }} />   {/* Rank */}
                <col style={{ width: 440 }} />  {/* Institution */}
                <col style={{ width: 120 }} />  {/* Type */}
                {/* Position group */}
                <col style={{ width: 90 }} />   {/* Value */}
                <col style={{ width: 72 }} />   {/* Sector % */}
                <col style={{ width: 68 }} />   {/* vs SPX */}
                <col style={{ width: 72 }} />   {/* Sector Rank */}
                <col style={{ width: 68 }} />   {/* Co. Rank */}
                <col style={{ width: 68 }} />   {/* Ind. Rank */}
                {/* Portfolio group */}
                <col style={{ width: 90 }} />   {/* Sector 1 */}
                <col style={{ width: 90 }} />   {/* Sector 2 */}
                <col style={{ width: 90 }} />   {/* Sector 3 */}
                <col style={{ width: 64 }} />   {/* Diversity */}
                <col style={{ width: 80 }} />   {/* Port. Coverage */}
              </colgroup>
              <thead>
                <ColumnGroupHeader groups={[
                  { label: '', colSpan: 3 },
                  { label: 'Position', colSpan: 6 },
                  { label: 'Portfolio', colSpan: 5 },
                ]} />
                <tr>
                  <th style={TH_R}>Rank</th>
                  <th style={TH}>Institution</th>
                  <th style={TH}>Type</th>
                  <th style={TH_R}>Value ($MM)</th>
                  <th style={TH_R}>Sector %</th>
                  <th style={TH_R}>vs SPX</th>
                  <th style={TH_R}>Sector Rank</th>
                  <th style={TH_R}>Co. Rank</th>
                  <th style={TH_R}>Ind. Rank</th>
                  <th style={TH}>Sector 1</th>
                  <th style={TH}>Sector 2</th>
                  <th style={TH}>Sector 3</th>
                  <th style={TH_R}>Diversity</th>
                  <th style={TH}>Port. Coverage</th>
                </tr>
              </thead>
              <tbody>
                {fundView === 'fund'
                  ? fundRowsDisplay.map(r => renderRow(r, `f:${r.rank}`, 0, false, false, toggle))
                  : groups.flatMap(g => {
                      const pkey = groupKey(g.parent)
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

// ── Helpers ──────────────────────────────────────────────────────────────

function InfoChip({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div style={{ fontSize: 10, fontWeight: 600, textTransform: 'uppercase', color: '#94a3b8', letterSpacing: '0.08em', marginBottom: 2 }}>{label}</div>
      <div style={{ fontSize: 13, color: '#1e293b' }}>{value}</div>
    </div>
  )
}

function groupKey(parent: ConvictionRow): string {
  return `${parent.rank}:${parent.institution}`
}

function SectorCell({ entry }: { entry: { code: string; weight_pct: number } | undefined }) {
  if (!entry) return <td style={TD}>—</td>
  return (
    <td style={TD}>
      <span style={{ fontWeight: 600, color: '#1e293b', fontSize: 13 }}>{entry.code}</span>
      <span style={{ color: '#64748b', fontSize: 11, marginLeft: 4 }}>{entry.weight_pct}%</span>
    </td>
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
  const ts = getTypeStyle(row.type)
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
      <td style={TD}>
        <span style={{ ...BADGE, backgroundColor: ts.bg, color: ts.color }}>{ts.label}</span>
      </td>
      <td style={TD_R}>{fmtValueMm(row.value)}</td>
      <td style={TD_R}>{fmtPct2(row.subject_sector_pct)}</td>
      <td style={TD_R}><SignedPct1 v={row.vs_spx} /></td>
      <td style={TD_R}>{fmtInt(row.sector_rank)}</td>
      <td style={TD_R}>{fmtInt(row.co_rank_in_sector)}</td>
      <td style={TD_R}>{fmtInt(row.industry_rank)}</td>
      <SectorCell entry={row.top3[0]} />
      <SectorCell entry={row.top3[1]} />
      <SectorCell entry={row.top3[2]} />
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
