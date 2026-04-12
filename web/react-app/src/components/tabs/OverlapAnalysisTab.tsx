import { useEffect, useMemo, useRef, useState } from 'react'
import { useAppStore } from '../../store/useAppStore'
import { useFetch } from '../../hooks/useFetch'
import type {
  TwoCompanyOverlapResponse,
  TwoCompanyInstitutionalRow,
  TwoCompanyFundRow,
} from '../../types/api'
import {
  QuarterSelector,
  ExportBar,
  ColumnGroupHeader,
  getTypeStyle,
} from '../common'

// ── Formatters ─────────────────────────────────────────────────────────────

const NUM_0 = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 })
const NUM_2 = new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 })

function fmtValueMm(v: number | null): string {
  if (v == null) return '—'
  return `$${NUM_0.format(v / 1e6)}`
}

function fmtPct2(v: number | null): string {
  if (v == null) return '—'
  return `${NUM_2.format(v)}%`
}

// ── Styles (Register-consistent first 3 cols) ─────────────────────────────

const TH: React.CSSProperties = {
  padding: '8px 8px', fontSize: 10, fontWeight: 700,
  textTransform: 'uppercase', letterSpacing: '0.04em',
  color: '#ffffff', backgroundColor: 'var(--oxford-blue)',
  textAlign: 'left', borderBottom: '1px solid #1e2d47',
  whiteSpace: 'nowrap', position: 'sticky', top: 30, zIndex: 3,
}
const TH_R: React.CSSProperties = { ...TH, textAlign: 'right' }
const TD: React.CSSProperties = {
  padding: '6px 8px', fontSize: 12, color: '#1e293b',
  borderBottom: '1px solid #e5e7eb',
}
const TD_R: React.CSSProperties = {
  ...TD, textAlign: 'right', fontVariantNumeric: 'tabular-nums',
}
const BADGE: React.CSSProperties = {
  display: 'inline-block', padding: '1px 6px', fontSize: 10,
  fontWeight: 600, borderRadius: 3,
}
const CENTER_MSG: React.CSSProperties = { padding: 40, fontSize: 14, textAlign: 'center' }

const OVERLAP_ROW: React.CSSProperties = {
  backgroundColor: '#fffbeb',
  borderLeft: '3px solid var(--accent-gold)',
}

const QUARTERS = ['2025Q4', '2025Q3', '2025Q2', '2025Q1']
const TOTAL_COLS = 7

// ── Second ticker input with dropdown ──────────────────────────────────────

interface TickerSearchProps {
  value: string
  onSelect: (ticker: string | null) => void
}

function SecondTickerInput({ value, onSelect }: TickerSearchProps) {
  const [input, setInput] = useState(value)
  const [options, setOptions] = useState<Array<{ ticker: string; name: string }>>([])
  const [allTickers, setAllTickers] = useState<Array<{ ticker: string; name: string }>>([])
  const [open, setOpen] = useState(false)
  const [focused, setFocused] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    fetch('/api/tickers').then(r => r.json()).then(setAllTickers).catch(() => {})
  }, [])

  useEffect(() => { setInput(value) }, [value])

  useEffect(() => {
    if (input.length < 1) { setOptions([]); setOpen(false); return }
    const q = input.toUpperCase()
    setOptions(allTickers.filter(t => t.ticker.startsWith(q) || t.name?.toUpperCase().includes(q)).slice(0, 8))
    setOpen(true)
  }, [input, allTickers])

  useEffect(() => {
    function h(e: MouseEvent) { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false) }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [])

  function select(ticker: string) { setInput(ticker); setOpen(false); onSelect(ticker) }
  function clear() { setInput(''); setOpen(false); onSelect(null) }

  return (
    <div ref={ref} style={{ position: 'relative', display: 'inline-block' }}>
      <input type="text" value={input} placeholder="Add second ticker…"
        autoComplete="off" autoCorrect="off" spellCheck={false}
        onChange={e => setInput(e.target.value)}
        onKeyDown={e => {
          if (e.key === 'Enter' && input.trim()) {
            const t = input.trim().toUpperCase()
            if (allTickers.some(x => x.ticker === t)) select(t)
          }
        }}
        onFocus={() => { setFocused(true); if (input.length > 0) setOpen(true) }}
        onBlur={() => setFocused(false)}
        style={{
          width: 180, padding: '6px 28px 6px 10px', fontSize: 13, color: '#1e293b',
          backgroundColor: '#fff', borderRadius: 4, outline: 'none',
          border: `1px solid ${focused ? 'var(--glacier-blue)' : '#e2e8f0'}`,
          transition: 'border-color 0.1s',
        }}
      />
      {input && <button type="button" onClick={clear} aria-label="Clear"
        style={{ position: 'absolute', right: 6, top: '50%', transform: 'translateY(-50%)', width: 18, height: 18, padding: 0, lineHeight: '16px', fontSize: 14, color: '#94a3b8', backgroundColor: 'transparent', border: 'none', cursor: 'pointer' }}>×</button>}
      {open && options.length > 0 && (
        <div style={{ position: 'absolute', top: '100%', left: 0, marginTop: 2, width: 260, maxHeight: 220, overflowY: 'auto', backgroundColor: '#fff', border: '1px solid #e2e8f0', borderRadius: 4, boxShadow: '0 4px 12px rgba(0,0,0,0.08)', zIndex: 1000 }}>
          {options.map(o => (
            <div key={o.ticker} onMouseDown={() => select(o.ticker)}
              style={{ padding: '6px 10px', fontSize: 12, cursor: 'pointer', display: 'flex', gap: 8 }}
              onMouseEnter={e => (e.currentTarget.style.backgroundColor = '#f4f6f9')}
              onMouseLeave={e => (e.currentTarget.style.backgroundColor = 'transparent')}>
              <span style={{ color: 'var(--accent-gold)', fontWeight: 700, width: 48, flexShrink: 0 }}>{o.ticker}</span>
              <span style={{ color: '#94a3b8', fontSize: 11, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{o.name}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Component ──────────────────────────────────────────────────────────────

export function OverlapAnalysisTab() {
  const { ticker, quarter, setQuarter } = useAppStore()

  const [secondTicker, setSecondTicker] = useState<string | null>(null)
  const [instActiveOnly, setInstActiveOnly] = useState(false)
  const [fundActiveOnly, setFundActiveOnly] = useState(false)

  const subject = (ticker || '').toUpperCase()

  // Fetch subject-only on tab load, overlap when second ticker selected
  const subjectUrl = subject && !secondTicker
    ? `/api/two_company_subject?subject=${enc(subject)}&quarter=${enc(quarter)}`
    : null
  const overlapUrl = subject && secondTicker
    ? `/api/two_company_overlap?subject=${enc(subject)}&second=${enc(secondTicker)}&quarter=${enc(quarter)}`
    : null

  const subjectData = useFetch<TwoCompanyOverlapResponse>(subjectUrl)
  const overlapData = useFetch<TwoCompanyOverlapResponse>(overlapUrl)

  const data = secondTicker ? overlapData.data : subjectData.data
  const loading = secondTicker ? overlapData.loading : subjectData.loading
  const error = secondTicker ? overlapData.error : subjectData.error

  const meta = data?.meta
  const second = meta?.second || secondTicker || ''

  // Filter institutional rows
  const instRows = useMemo(() => {
    if (!data) return []
    let rows = data.institutional
    if (instActiveOnly) rows = rows.filter(r => (r.manager_type || '').toLowerCase() !== 'passive')
    return rows
  }, [data, instActiveOnly])

  // Filter fund rows
  const fundRows = useMemo(() => {
    if (!data) return []
    let rows = data.fund
    if (fundActiveOnly) rows = rows.filter(r => r.is_active !== false)
    return rows
  }, [data, fundActiveOnly])

  // CSV export — both panels in one file
  function onExcel() {
    if (!data) return
    const h = ['Rank', 'Holder', 'Type', `${subject} %`, `${second} %`, `${subject} $MM`, `${second} $MM`]
    const instCsv = instRows.map((r, i) => [
      i + 1, `"${r.holder.replace(/"/g, '""')}"`, r.manager_type || '',
      r.subj_pct_float?.toFixed(2) ?? '', r.sec_pct_float?.toFixed(2) ?? '',
      r.subj_dollars != null ? (r.subj_dollars / 1e6).toFixed(0) : '',
      r.sec_dollars != null ? (r.sec_dollars / 1e6).toFixed(0) : '',
    ])
    const fundCsv = fundRows.map((r, i) => [
      i + 1, `"${r.holder.replace(/"/g, '""')}"`, r.is_active ? 'active' : 'passive',
      r.subj_pct_float?.toFixed(2) ?? '', r.sec_pct_float?.toFixed(2) ?? '',
      r.subj_dollars != null ? (r.subj_dollars / 1e6).toFixed(0) : '',
      r.sec_dollars != null ? (r.sec_dollars / 1e6).toFixed(0) : '',
    ])
    const csv = [
      ['--- Institutional ---'], h, ...instCsv,
      [], ['--- Fund ---'], h, ...fundCsv,
    ].map(r => r.join(',')).join('\n')
    downloadCsv(csv, `overlap_${subject}_${second || 'only'}_${quarter}.csv`)
  }

  if (!ticker) {
    return <div style={CENTER_MSG}><span style={{ color: '#94a3b8' }}>Enter a ticker to load overlap analysis</span></div>
  }

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', backgroundColor: 'var(--card-bg)', borderRadius: 6, boxShadow: '0 1px 2px rgba(0,0,0,0.04)', overflow: 'hidden' }}>
      <style>{`@media print { .oa-controls { display:none!important } }`}</style>

      {/* Controls */}
      <div className="oa-controls" style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'flex-end', gap: 16, padding: '12px 16px', backgroundColor: '#f8fafc', borderBottom: '1px solid #e2e8f0', flexShrink: 0 }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <span style={{ fontSize: 10, fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.08em' }}>Second Ticker</span>
          <SecondTickerInput value={secondTicker || ''} onSelect={setSecondTicker} />
        </div>
        <QuarterSelector quarters={QUARTERS} value={quarter} onChange={setQuarter} />
        <div style={{ marginLeft: 'auto' }}>
          <ExportBar onExcel={onExcel} onPrint={() => window.print()} disabled={!data} />
        </div>
      </div>

      {/* Content — two panels */}
      {loading && <div style={{ ...CENTER_MSG, color: '#94a3b8' }}>Loading…</div>}
      {error && !loading && <div style={{ ...CENTER_MSG, color: '#ef4444' }}>Error: {error}</div>}
      {data && !loading && (
        <div style={{ display: 'flex', flex: 1, gap: 12, padding: 16, overflow: 'hidden' }}>
          {/* Institutional panel */}
          <PanelTable
            title="Institutional"
            rows={instRows}
            subject={subject}
            second={second}
            hasSecond={!!secondTicker}
            activeOnly={instActiveOnly}
            onActiveOnlyChange={setInstActiveOnly}
            activeLabel="Active Only"
            renderType={(r) => {
              const ts = getTypeStyle((r as TwoCompanyInstitutionalRow).manager_type)
              return <span style={{ ...BADGE, backgroundColor: ts.bg, color: ts.color }}>{ts.label}</span>
            }}
          />
          {/* Fund panel */}
          <PanelTable
            title="Fund"
            rows={fundRows}
            subject={subject}
            second={second}
            hasSecond={!!secondTicker}
            activeOnly={fundActiveOnly}
            onActiveOnlyChange={setFundActiveOnly}
            activeLabel="Active Only"
            renderType={(r) => {
              const fr = r as TwoCompanyFundRow
              const label = fr.is_active ? 'active' : 'passive'
              const ts = getTypeStyle(label)
              return <span style={{ ...BADGE, backgroundColor: ts.bg, color: ts.color }}>{ts.label}</span>
            }}
          />
        </div>
      )}
    </div>
  )
}

// ── Panel table (shared for inst + fund) ────────────────────────────────────

type AnyRow = TwoCompanyInstitutionalRow | TwoCompanyFundRow

interface PanelProps {
  title: string
  rows: AnyRow[]
  subject: string
  second: string
  hasSecond: boolean
  activeOnly: boolean
  onActiveOnlyChange: (v: boolean) => void
  activeLabel: string
  renderType: (row: AnyRow) => React.ReactNode
}

function PanelTable({
  title, rows, subject, second, hasSecond,
  activeOnly, onActiveOnlyChange, activeLabel, renderType,
}: PanelProps) {
  // Overlap cohort stats
  const top25Overlap = rows.slice(0, 25).filter(r => r.is_overlap).length
  const top50Overlap = rows.slice(0, 50).filter(r => r.is_overlap).length
  const overlapPct = rows.length > 0 ? (rows.filter(r => r.is_overlap).length / rows.length * 100) : 0

  // Footer sums
  const sum15 = sumRows(rows.slice(0, 15))
  const sum25 = sumRows(rows.slice(0, 25))

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', border: '1px solid #e2e8f0', borderRadius: 6 }}>
      {/* Panel header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 12px', backgroundColor: '#f8fafc', borderBottom: '1px solid #e2e8f0', flexShrink: 0 }}>
        <span style={{ fontWeight: 700, fontSize: 13, color: 'var(--oxford-blue)' }}>{title}</span>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: '#64748b', cursor: 'pointer' }}>
          <input type="checkbox" checked={activeOnly} onChange={e => onActiveOnlyChange(e.target.checked)} />
          {activeLabel}
        </label>
      </div>

      {/* Scrollable table */}
      <div style={{ flex: 1, overflowY: 'auto', overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'separate', borderSpacing: 0, tableLayout: 'fixed', fontSize: 12 }}>
          <colgroup>
            <col style={{ width: 36 }} />
            <col />
            <col style={{ width: 80 }} />
            <col style={{ width: 72 }} />
            <col style={{ width: 72 }} />
            <col style={{ width: 80 }} />
            <col style={{ width: 80 }} />
          </colgroup>
          <thead>
            <ColumnGroupHeader groups={[
              { label: '', colSpan: 3 },
              { label: '% Owned', colSpan: 2 },
              { label: 'Value ($MM)', colSpan: 2 },
            ]} />
            <tr>
              <th style={TH_R}>#</th>
              <th style={TH}>Holder</th>
              <th style={TH}>Type</th>
              <th style={TH_R}>{subject} %</th>
              <th style={TH_R}>{hasSecond ? `${second} %` : '—'}</th>
              <th style={TH_R}>{subject} $</th>
              <th style={TH_R}>{hasSecond ? `${second} $` : '—'}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => {
              const isOv = r.is_overlap && hasSecond
              return (
                <tr key={r.holder} style={isOv ? OVERLAP_ROW : undefined}>
                  <td style={{ ...TD, textAlign: 'right', fontWeight: 700, color: '#64748b', fontSize: 11 }}>{i + 1}</td>
                  <td style={{ ...TD, fontWeight: 500, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: 0 }} title={r.holder}>
                    {r.holder}
                  </td>
                  <td style={TD}>{renderType(r)}</td>
                  <td style={TD_R}>{fmtPct2(r.subj_pct_float)}</td>
                  <td style={{ ...TD_R, color: r.sec_pct_float == null ? '#cbd5e1' : '#1e293b' }}>
                    {fmtPct2(r.sec_pct_float)}
                  </td>
                  <td style={TD_R}>{fmtValueMm(r.subj_dollars)}</td>
                  <td style={{ ...TD_R, color: r.sec_dollars == null ? '#cbd5e1' : '#1e293b' }}>
                    {fmtValueMm(r.sec_dollars)}
                  </td>
                </tr>
              )
            })}
            {rows.length === 0 && (
              <tr><td colSpan={TOTAL_COLS} style={{ ...TD, textAlign: 'center', padding: 20, color: '#64748b' }}>No holders found</td></tr>
            )}
          </tbody>
          <tfoot>
            <FooterRow label="Top 15" sums={sum15} bottomPx={33} />
            <FooterRow label="Top 25" sums={sum25} bottomPx={0} />
          </tfoot>
        </table>
      </div>

      {/* Cohort summary */}
      {hasSecond && (
        <div style={{ display: 'flex', gap: 16, padding: '10px 12px', borderTop: '1px solid #e2e8f0', backgroundColor: '#f8fafc', flexShrink: 0 }}>
          <Tile label="Top 25 overlap" value={String(top25Overlap)} />
          <Tile label="Top 50 overlap" value={String(top50Overlap)} />
          <Tile label="Overlap %" value={`${overlapPct.toFixed(1)}%`} />
        </div>
      )}
    </div>
  )
}

// ── Footer row ──────────────────────────────────────────────────────────────

interface RowSums {
  subjPct: number; secPct: number; subjVal: number; secVal: number
}

function sumRows(rows: AnyRow[]): RowSums {
  let subjPct = 0, secPct = 0, subjVal = 0, secVal = 0
  for (const r of rows) {
    subjPct += r.subj_pct_float || 0
    secPct += r.sec_pct_float || 0
    subjVal += r.subj_dollars || 0
    secVal += r.sec_dollars || 0
  }
  return { subjPct, secPct, subjVal, secVal }
}

function FooterRow({ label, sums, bottomPx }: { label: string; sums: RowSums; bottomPx: number }) {
  const s: React.CSSProperties = {
    padding: '6px 8px', fontSize: 12, fontWeight: 600,
    color: '#ffffff', backgroundColor: 'var(--oxford-blue)',
    position: 'sticky', bottom: bottomPx, zIndex: 2,
    borderTop: '2px solid var(--oxford-blue)',
  }
  const sr: React.CSSProperties = { ...s, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }
  return (
    <tr>
      <td style={s} />
      <td style={s}>{label}</td>
      <td style={s} />
      <td style={sr}>{fmtPct2(sums.subjPct)}</td>
      <td style={sr}>{fmtPct2(sums.secPct)}</td>
      <td style={sr}>{fmtValueMm(sums.subjVal)}</td>
      <td style={sr}>{fmtValueMm(sums.secVal)}</td>
    </tr>
  )
}

function Tile({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ flex: 1 }}>
      <div style={{ fontSize: 10, fontWeight: 600, textTransform: 'uppercase', color: '#94a3b8', letterSpacing: '0.08em', marginBottom: 2 }}>{label}</div>
      <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--oxford-blue)' }}>{value}</div>
    </div>
  )
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function enc(s: string) { return encodeURIComponent(s) }

function downloadCsv(csv: string, filename: string) {
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
  const u = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = u; a.download = filename
  document.body.appendChild(a); a.click()
  document.body.removeChild(a); URL.revokeObjectURL(u)
}
