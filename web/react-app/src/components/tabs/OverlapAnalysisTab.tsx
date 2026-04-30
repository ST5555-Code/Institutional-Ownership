import { useEffect, useMemo, useRef, useState } from 'react'
import { useAppStore } from '../../store/useAppStore'
import { useFetch } from '../../hooks/useFetch'
import { useTickers } from '../../hooks/useTickers'
import type {
  TwoCompanyOverlapResponse,
  TwoCompanyInstitutionalRow,
  TwoCompanyFundRow,
  OverlapInstitutionDetailResponse,
} from '../../types/api'
import {
  QuarterSelector,
  ExportBar,
  FreshnessBadge,
  PageHeader,
  getTypeStyle,
} from '../common'

// ── Formatters ─────────────────────────────────────────────────────────────

const NUM_0 = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 })
const NUM_2 = new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

function fmtValueMm(v: number | null): string {
  if (v == null || v === 0) return '—'
  return `$${NUM_0.format(v / 1e6)}`
}

function fmtPct2(v: number | null): string {
  if (v == null || v === 0) return '—'
  return `${NUM_2.format(v)}%`
}

function fmtQuarter(q: string): string {
  if (!q || q.length < 6) return q
  const qNum = q.slice(-2)
  const yr = q.slice(2, 4)
  return `${qNum} '${yr}`
}

// ── Styles ─────────────────────────────────────────────────────────────────

const TH: React.CSSProperties = {
  padding: '4px 8px', fontSize: 9, fontWeight: 700,
  textTransform: 'uppercase', letterSpacing: '0.16em', fontFamily: "'Hanken Grotesk', sans-serif",
  color: 'var(--text-dim)', backgroundColor: 'var(--header)',
  textAlign: 'left', borderBottom: '1px solid var(--line)',
  whiteSpace: 'nowrap',
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
const TD_TRUNC: React.CSSProperties = {
  ...TD, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: 0,
}
const BADGE: React.CSSProperties = {
  display: 'inline-block', padding: '1px 6px', fontSize: 10,
  fontWeight: 600, borderRadius: 1,
}
const CENTER_MSG: React.CSSProperties = { padding: 40, fontSize: 14, textAlign: 'center' }

const QUARTERS = ['2025Q4', '2025Q3', '2025Q2', '2025Q1']

// ── Second ticker input with dropdown ──────────────────────────────────────

interface TickerSearchProps {
  value: string
  onSelect: (ticker: string | null) => void
}

function SecondTickerInput({ value, onSelect }: TickerSearchProps) {
  const [input, setInput] = useState(value)
  const [options, setOptions] = useState<Array<{ ticker: string; name: string }>>([])
  const allTickers = useTickers()
  const [open, setOpen] = useState(false)
  const [focused, setFocused] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

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
          width: 180, padding: '6px 28px 6px 10px', fontSize: 13, color: 'var(--text)',
          backgroundColor: 'var(--bg)', borderRadius: 0, outline: 'none',
          border: `1px solid ${focused ? 'var(--gold)' : 'var(--line)'}`,
          transition: 'border-color 0.1s',
        }}
      />
      {input && <button type="button" onClick={clear} aria-label="Clear"
        style={{ position: 'absolute', right: 6, top: '50%', transform: 'translateY(-50%)', width: 18, height: 18, padding: 0, lineHeight: '16px', fontSize: 14, color: 'var(--text-dim)', backgroundColor: 'transparent', border: 'none', cursor: 'pointer' }}>×</button>}
      {open && options.length > 0 && (
        <div style={{ position: 'absolute', top: '100%', left: 0, marginTop: 2, width: 260, maxHeight: 220, overflowY: 'auto', backgroundColor: 'var(--panel)', border: '1px solid var(--line)', borderRadius: 0, boxShadow: '0 4px 12px rgba(0,0,0,0.08)', zIndex: 1000 }}>
          {options.map(o => (
            <div key={o.ticker} onMouseDown={() => select(o.ticker)}
              style={{ padding: '6px 10px', fontSize: 12, cursor: 'pointer', display: 'flex', gap: 8 }}
              onMouseEnter={e => (e.currentTarget.style.backgroundColor = 'var(--panel-hi)')}
              onMouseLeave={e => (e.currentTarget.style.backgroundColor = 'transparent')}>
              <span style={{ color: 'var(--gold)', fontWeight: 700, width: 48, flexShrink: 0 }}>{o.ticker}</span>
              <span style={{ color: 'var(--text-dim)', fontSize: 11, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{o.name}</span>
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

  const subjectUrl = subject && !secondTicker
    ? `/api/v1/two_company_subject?subject=${enc(subject)}&quarter=${enc(quarter)}`
    : null
  const overlapUrl = subject && secondTicker
    ? `/api/v1/two_company_overlap?subject=${enc(subject)}&second=${enc(secondTicker)}&quarter=${enc(quarter)}`
    : null

  const subjectData = useFetch<TwoCompanyOverlapResponse>(subjectUrl)
  const overlapData = useFetch<TwoCompanyOverlapResponse>(overlapUrl)

  const data = secondTicker ? overlapData.data : subjectData.data
  const loading = secondTicker ? overlapData.loading : subjectData.loading
  const error = secondTicker ? overlapData.error : subjectData.error

  const meta = data?.meta
  const second = meta?.second || secondTicker || ''
  const hasSecond = !!secondTicker

  const instRows = useMemo(() => {
    if (!data) return []
    let rows = data.institutional
    if (instActiveOnly) rows = rows.filter(r => (r.manager_type || '').toLowerCase() !== 'passive')
    return rows
  }, [data, instActiveOnly])

  const fundRows = useMemo(() => {
    if (!data) return []
    let rows = data.fund
    if (fundActiveOnly) rows = rows.filter(r => r.is_active !== false)
    return rows
  }, [data, fundActiveOnly])

  // Cross-ownership stats (computed from holders that appear in BOTH lists,
  // valued at their A holdings / B holdings respectively).
  const instStats = useMemo(() => computeOverlapStats(instRows), [instRows])
  const fundStats = useMemo(() => computeOverlapStats(fundRows), [fundRows])

  function onExcel() {
    if (!data) return
    const h = ['Rank', 'Holder', 'Type', `${subject} %`, `${second} %`, `${subject} $MM`, `${second} $MM`]
    const instCsv = instRows.map((r, i) => [
      i + 1, `"${r.holder.replace(/"/g, '""')}"`, r.manager_type || '',
      r.subj_pct_so?.toFixed(2) ?? '', r.sec_pct_so?.toFixed(2) ?? '',
      r.subj_dollars != null ? (r.subj_dollars / 1e6).toFixed(0) : '',
      r.sec_dollars != null ? (r.sec_dollars / 1e6).toFixed(0) : '',
    ])
    const fundCsv = fundRows.map((r, i) => [
      i + 1, `"${r.holder.replace(/"/g, '""')}"`, r.is_active ? 'active' : 'passive',
      r.subj_pct_so?.toFixed(2) ?? '', r.sec_pct_so?.toFixed(2) ?? '',
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
    return <div style={CENTER_MSG}><span style={{ color: 'var(--text-dim)' }}>Enter a ticker to load overlap analysis</span></div>
  }

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', backgroundColor: 'var(--panel)', borderRadius: 0, overflow: 'hidden' }}>
      {/* Header row */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', padding: '0 12px', flexShrink: 0 }}>
        <div style={{ flex: 1 }}>
          <PageHeader
            section="Targeting"
            title="Overlap Analysis"
            description="Pairwise holder overlap between securities. Identifies shared institutional ownership patterns."
          />
        </div>
        <div className="no-print" style={{ display: 'flex', alignItems: 'center', gap: 10, paddingTop: 14 }}>
          <FreshnessBadge tableName="summary_by_parent" label="register" />
          <ExportBar onExcel={onExcel} onPrint={() => window.print()} disabled={!data} />
        </div>
      </div>
      <style>{`@media print { .oa-controls { display:none!important } .no-print { display:none!important } }`}</style>

      {/* Controls */}
      <div className="oa-controls" style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'flex-end', gap: 12, padding: '10px 12px', backgroundColor: 'var(--panel)', border: '1px solid var(--line)', borderRadius: 0, margin: '0 12px', flexShrink: 0 }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <span style={{ fontSize: 10, fontWeight: 600, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>Second Ticker</span>
          <SecondTickerInput value={secondTicker || ''} onSelect={setSecondTicker} />
        </div>
        <QuarterSelector quarters={QUARTERS} value={quarter} onChange={setQuarter} formatLabel={fmtQuarter} />
      </div>

      {/* Content — vertically stacked tables */}
      {loading && <div style={{ ...CENTER_MSG, color: 'var(--text-dim)' }}>Loading…</div>}
      {error && !loading && <div style={{ ...CENTER_MSG, color: 'var(--neg)' }}>Error: {error}</div>}
      {data && !loading && (
        <div style={{ flex: 1, overflowY: 'auto', overflowX: 'auto' }}>
          <div style={{ padding: 12, display: 'flex', flexDirection: 'column', gap: 16 }}>
            {/* Institutional Level */}
            <div>
              <InstitutionalTable
                rows={instRows}
                subject={subject}
                second={second}
                hasSecond={hasSecond}
                quarter={quarter}
                activeOnly={instActiveOnly}
                onActiveOnlyChange={setInstActiveOnly}
              />
              {hasSecond && (
                <StatsRow
                  subject={subject}
                  second={second}
                  pctAOwnedByB={instStats.pctAOwnedByB}
                  pctBOwnedByA={instStats.pctBOwnedByA}
                  top25Overlap={instRows.slice(0, 25).filter(r => r.is_overlap).length}
                  overlapPct={instStats.overlapPct}
                />
              )}
            </div>

            {/* Fund Level */}
            <div>
              <FundTable
                rows={fundRows}
                subject={subject}
                second={second}
                hasSecond={hasSecond}
                activeOnly={fundActiveOnly}
                onActiveOnlyChange={setFundActiveOnly}
              />
              {hasSecond && (
                <StatsRow
                  subject={subject}
                  second={second}
                  pctAOwnedByB={fundStats.pctAOwnedByB}
                  pctBOwnedByA={fundStats.pctBOwnedByA}
                  top25Overlap={fundRows.slice(0, 25).filter(r => r.is_overlap).length}
                  overlapPct={fundStats.overlapPct}
                />
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Overlap-stat math ─────────────────────────────────────────────────────

interface OverlapStats {
  pctAOwnedByB: number | null
  pctBOwnedByA: number | null
  overlapPct: number
}

function computeOverlapStats(rows: Array<{ is_overlap: boolean; subj_dollars: number | null; sec_dollars: number | null }>): OverlapStats {
  let totalA = 0
  let totalB = 0
  let overlapA = 0
  let overlapB = 0
  let overlapCount = 0
  for (const r of rows) {
    const a = r.subj_dollars || 0
    const b = r.sec_dollars || 0
    totalA += a
    totalB += b
    if (r.is_overlap) {
      overlapA += a
      overlapB += b
      overlapCount += 1
    }
  }
  return {
    pctAOwnedByB: totalA > 0 ? (overlapA / totalA) * 100 : null,
    pctBOwnedByA: totalB > 0 ? (overlapB / totalB) * 100 : null,
    overlapPct: rows.length > 0 ? (overlapCount / rows.length) * 100 : 0,
  }
}

// ── Stats row (bottom of each table) ──────────────────────────────────────

interface StatsRowProps {
  subject: string
  second: string
  pctAOwnedByB: number | null
  pctBOwnedByA: number | null
  top25Overlap: number
  overlapPct: number
}

function StatsRow({ subject, second, pctAOwnedByB, pctBOwnedByA, top25Overlap, overlapPct }: StatsRowProps) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, marginTop: 8 }}>
      <StatBox
        kicker={`${subject} OWNED BY ${second} HOLDERS`}
        value={pctAOwnedByB != null ? `${NUM_2.format(pctAOwnedByB)}%` : '—'}
      />
      <StatBox
        kicker={`${second} OWNED BY ${subject} HOLDERS`}
        value={pctBOwnedByA != null ? `${NUM_2.format(pctBOwnedByA)}%` : '—'}
      />
      <StatBox kicker="TOP 25 OVERLAP" value={String(top25Overlap)} />
      <StatBox kicker="OVERLAP %" value={`${NUM_2.format(overlapPct)}%`} />
    </div>
  )
}

function StatBox({ kicker, value }: { kicker: string; value: string }) {
  return (
    <div style={{ backgroundColor: 'var(--card)', border: '1px solid var(--line)', borderRadius: 0, padding: 10 }}>
      <div style={{ fontSize: 9, fontFamily: "'Hanken Grotesk', sans-serif", fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.16em', color: 'var(--text-dim)', marginBottom: 6, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}
        title={kicker}>
        {kicker}
      </div>
      <div style={{ fontSize: 24, fontFamily: "'JetBrains Mono', monospace", fontWeight: 400, color: 'var(--gold)', fontVariantNumeric: 'tabular-nums', letterSpacing: '-0.01em' }}>
        {value}
      </div>
    </div>
  )
}

// ── TableBox shell with title bar + Active Only toggle ────────────────────

interface TableBoxProps {
  title: string
  activeOnly: boolean
  onActiveOnlyChange: (v: boolean) => void
  children: React.ReactNode
}

function TableBox({ title, activeOnly, onActiveOnlyChange, children }: TableBoxProps) {
  return (
    <div style={{ border: '1px solid var(--line)', borderRadius: 0, overflow: 'hidden', backgroundColor: 'var(--panel)' }}>
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '8px 12px',
        fontSize: 9, fontFamily: "'Hanken Grotesk', sans-serif",
        fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.16em',
        color: 'var(--text-dim)', backgroundColor: 'var(--header)',
        borderBottom: '1px solid var(--line)',
      }}>
        <span>{title}</span>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 10, color: 'var(--text-dim)', cursor: 'pointer', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
          <input type="checkbox" checked={activeOnly} onChange={e => onActiveOnlyChange(e.target.checked)} />
          Active Only
        </label>
      </div>
      <div style={{ overflow: 'auto' }}>{children}</div>
    </div>
  )
}

// ── Institutional table with expandable rows ──────────────────────────────

interface InstTableProps {
  rows: TwoCompanyInstitutionalRow[]
  subject: string
  second: string
  hasSecond: boolean
  quarter: string
  activeOnly: boolean
  onActiveOnlyChange: (v: boolean) => void
}

function InstitutionalTable({ rows, subject, second, hasSecond, quarter, activeOnly, onActiveOnlyChange }: InstTableProps) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  function toggle(key: string) {
    setExpanded(prev => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const colCount = 8
  return (
    <TableBox title="Institutional Level" activeOnly={activeOnly} onActiveOnlyChange={onActiveOnlyChange}>
      <table style={{ width: '100%', borderCollapse: 'separate', borderSpacing: 0, tableLayout: 'fixed', fontSize: 12 }}>
        <colgroup>
          <col style={{ width: 24 }} />   {/* expand */}
          <col style={{ width: 36 }} />   {/* # */}
          <col />                          {/* Institution */}
          <col style={{ width: 90 }} />   {/* Type */}
          <col style={{ width: 95 }} />   {/* A %SO */}
          <col style={{ width: 100 }} />  {/* A Value */}
          <col style={{ width: 95 }} />   {/* B %SO */}
          <col style={{ width: 100 }} />  {/* B Value */}
        </colgroup>
        <thead>
          <tr>
            <th style={TH} />
            <th style={TH_R}>#</th>
            <th style={TH}>Institution</th>
            <th style={TH}>Type</th>
            <th style={TH_R}>{subject} % SO</th>
            <th style={TH_R}>{subject} VALUE</th>
            <th style={TH_R}>{hasSecond ? `${second} % SO` : '—'}</th>
            <th style={TH_R}>{hasSecond ? `${second} VALUE` : '—'}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => {
            const canExpand = hasSecond && r.is_overlap
            const key = r.holder
            const isOpen = expanded.has(key)
            const ts = getTypeStyle(r.manager_type)
            return (
              <RowFragment
                key={key}
                rowKey={key}
                rank={i + 1}
                row={r}
                ts={ts}
                isOpen={isOpen}
                canExpand={canExpand}
                toggle={toggle}
                subject={subject}
                second={second}
                hasSecond={hasSecond}
                quarter={quarter}
              />
            )
          })}
          {rows.length === 0 && (
            <tr><td colSpan={colCount} style={{ ...TD, textAlign: 'center', padding: 20, color: 'var(--text-dim)' }}>No holders found</td></tr>
          )}
        </tbody>
      </table>
    </TableBox>
  )
}

interface RowFragmentProps {
  rowKey: string
  rank: number
  row: TwoCompanyInstitutionalRow
  ts: { bg: string; color: string; label: string }
  isOpen: boolean
  canExpand: boolean
  toggle: (k: string) => void
  subject: string
  second: string
  hasSecond: boolean
  quarter: string
}

function RowFragment({ rowKey, rank, row, ts, isOpen, canExpand, toggle, subject, second, hasSecond, quarter }: RowFragmentProps) {
  return (
    <>
      <tr>
        <td
          style={{
            ...TD,
            padding: '4px 0 4px 4px',
            textAlign: 'center',
            cursor: canExpand ? 'pointer' : 'default',
            userSelect: 'none',
          }}
          onClick={canExpand ? () => toggle(rowKey) : undefined}
        >
          {canExpand && (
            <span style={{
              display: 'inline-block', color: 'var(--gold)', fontSize: 9,
              transition: 'transform 0.12s',
              transform: isOpen ? 'rotate(90deg)' : 'rotate(0deg)',
            }}>▶</span>
          )}
        </td>
        <td style={{ ...TD, textAlign: 'right', fontWeight: 700, color: 'var(--text-dim)', fontSize: 11 }}>{rank}</td>
        <td
          style={{ ...TD_TRUNC, fontWeight: 500, cursor: canExpand ? 'pointer' : 'default' }}
          title={row.holder}
          onClick={canExpand ? () => toggle(rowKey) : undefined}
        >
          {row.holder}
        </td>
        <td style={TD}><span style={{ ...BADGE, backgroundColor: ts.bg, color: ts.color }}>{ts.label}</span></td>
        <td style={TD_R}>{fmtPct2(row.subj_pct_so)}</td>
        <td style={TD_R}>{fmtValueMm(row.subj_dollars)}</td>
        <td style={{ ...TD_R, color: row.sec_pct_so == null ? 'var(--text-dim)' : 'var(--text)' }}>{fmtPct2(row.sec_pct_so)}</td>
        <td style={{ ...TD_R, color: row.sec_dollars == null ? 'var(--text-dim)' : 'var(--text)' }}>{fmtValueMm(row.sec_dollars)}</td>
      </tr>
      {isOpen && canExpand && hasSecond && (
        <InstitutionDetail
          institution={row.holder}
          subject={subject}
          second={second}
          quarter={quarter}
        />
      )}
    </>
  )
}

// ── Institution detail rows (overlapping + non-overlapping funds) ─────────

interface InstitutionDetailProps {
  institution: string
  subject: string
  second: string
  quarter: string
}

function InstitutionDetail({ institution, subject, second, quarter }: InstitutionDetailProps) {
  const url = `/api/v1/overlap_institution_detail?subject=${enc(subject)}&second=${enc(second)}&institution=${enc(institution)}&quarter=${enc(quarter)}`
  const { data, loading, error } = useFetch<OverlapInstitutionDetailResponse>(url)

  // child-row left rail color matches RegisterTab (gold rail on first cell only)
  const childBg = 'rgba(197,162,84,0.03)'
  const colCount = 8

  if (loading) {
    return (
      <tr style={{ backgroundColor: childBg }}>
        <td style={{ ...TD, borderLeft: '2px solid var(--gold)' }} />
        <td colSpan={colCount - 1} style={{ ...TD, color: 'var(--text-dim)', fontStyle: 'italic' }}>Loading funds…</td>
      </tr>
    )
  }
  if (error || !data) {
    return (
      <tr style={{ backgroundColor: childBg }}>
        <td style={{ ...TD, borderLeft: '2px solid var(--gold)' }} />
        <td colSpan={colCount - 1} style={{ ...TD, color: 'var(--neg)' }}>{error || 'No data'}</td>
      </tr>
    )
  }

  const subHeaderRow = (key: string, label: string) => (
    <tr key={key} style={{ backgroundColor: childBg }}>
      <td style={{ ...TD, borderLeft: '2px solid var(--gold)', padding: 0 }} />
      <td colSpan={colCount - 1} style={{
        ...TD, padding: '6px 8px',
        fontSize: 9, fontFamily: "'Hanken Grotesk', sans-serif",
        fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.16em',
        color: 'var(--gold)', borderBottom: '1px solid var(--line-soft)',
      }}>
        {label}
      </td>
    </tr>
  )

  const rows: React.ReactElement[] = []
  if (data.overlapping.length > 0) {
    rows.push(subHeaderRow('oh', 'Overlapping Funds'))
    data.overlapping.forEach((f, i) => {
      const ts = getTypeStyle(f.type)
      rows.push(
        <tr key={`o-${i}-${f.series_id || f.fund_name}`} style={{ backgroundColor: childBg }}>
          <td style={{ ...TD, borderLeft: '2px solid var(--gold)' }} />
          <td style={TD} />
          <td style={{ ...TD_TRUNC, color: 'var(--text-mute)', paddingLeft: 24 }} title={f.fund_name}>
            <span style={{ color: 'var(--text-mute)', marginRight: 6, fontSize: 11 }}>└</span>
            {f.fund_name}
          </td>
          <td style={TD}><span style={{ ...BADGE, backgroundColor: ts.bg, color: ts.color }}>{ts.label}</span></td>
          <td style={{ ...TD_R, color: 'var(--text-dim)' }}>—</td>
          <td style={TD_R}>{fmtValueMm(f.value_a)}</td>
          <td style={{ ...TD_R, color: 'var(--text-dim)' }}>—</td>
          <td style={TD_R}>{fmtValueMm(f.value_b)}</td>
        </tr>
      )
    })
  }
  if (data.non_overlapping.length > 0) {
    rows.push(subHeaderRow('nh', 'Non-Overlapping Funds'))
    data.non_overlapping.forEach((f, i) => {
      const ts = getTypeStyle(f.type)
      const isA = f.holds === subject
      rows.push(
        <tr key={`n-${i}-${f.series_id || f.fund_name}`} style={{ backgroundColor: childBg }}>
          <td style={{ ...TD, borderLeft: '2px solid var(--gold)' }} />
          <td style={TD} />
          <td style={{ ...TD_TRUNC, color: 'var(--text-mute)', paddingLeft: 24 }} title={f.fund_name}>
            <span style={{ color: 'var(--text-mute)', marginRight: 6, fontSize: 11 }}>└</span>
            {f.fund_name}
          </td>
          <td style={TD}><span style={{ ...BADGE, backgroundColor: ts.bg, color: ts.color }}>{ts.label}</span></td>
          <td style={{ ...TD_R, color: 'var(--text-dim)' }}>—</td>
          <td style={{ ...TD_R, color: isA ? 'var(--text)' : 'var(--text-dim)' }}>{isA ? fmtValueMm(f.value) : '—'}</td>
          <td style={{ ...TD_R, color: 'var(--text-dim)' }}>—</td>
          <td style={{ ...TD_R, color: !isA ? 'var(--text)' : 'var(--text-dim)' }}>{!isA ? fmtValueMm(f.value) : '—'}</td>
        </tr>
      )
    })
  }
  if (rows.length === 0) {
    rows.push(
      <tr key="empty" style={{ backgroundColor: childBg }}>
        <td style={{ ...TD, borderLeft: '2px solid var(--gold)' }} />
        <td colSpan={colCount - 1} style={{ ...TD, color: 'var(--text-dim)', fontStyle: 'italic' }}>No fund-level data for this institution</td>
      </tr>
    )
  }
  return <>{rows}</>
}

// ── Fund table ─────────────────────────────────────────────────────────────

interface FundTableProps {
  rows: TwoCompanyFundRow[]
  subject: string
  second: string
  hasSecond: boolean
  activeOnly: boolean
  onActiveOnlyChange: (v: boolean) => void
}

function FundTable({ rows, subject, second, hasSecond, activeOnly, onActiveOnlyChange }: FundTableProps) {
  const colCount = 7
  return (
    <TableBox title="Fund Level" activeOnly={activeOnly} onActiveOnlyChange={onActiveOnlyChange}>
      <table style={{ width: '100%', borderCollapse: 'separate', borderSpacing: 0, tableLayout: 'fixed', fontSize: 12 }}>
        <colgroup>
          <col style={{ width: 36 }} />
          <col />
          <col style={{ width: 90 }} />
          <col style={{ width: 95 }} />
          <col style={{ width: 100 }} />
          <col style={{ width: 95 }} />
          <col style={{ width: 100 }} />
        </colgroup>
        <thead>
          <tr>
            <th style={TH_R}>#</th>
            <th style={TH}>Fund</th>
            <th style={TH}>Type</th>
            <th style={TH_R}>{subject} % SO</th>
            <th style={TH_R}>{subject} VALUE</th>
            <th style={TH_R}>{hasSecond ? `${second} % SO` : '—'}</th>
            <th style={TH_R}>{hasSecond ? `${second} VALUE` : '—'}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => {
            const label = r.is_active ? 'active' : r.is_active === false ? 'passive' : 'mixed'
            const ts = getTypeStyle(label)
            return (
              <tr key={r.series_id || r.holder}>
                <td style={{ ...TD, textAlign: 'right', fontWeight: 700, color: 'var(--text-dim)', fontSize: 11 }}>{i + 1}</td>
                <td style={{ ...TD_TRUNC, fontWeight: 500 }} title={r.holder}>{r.holder}</td>
                <td style={TD}><span style={{ ...BADGE, backgroundColor: ts.bg, color: ts.color }}>{ts.label}</span></td>
                <td style={TD_R}>{fmtPct2(r.subj_pct_so)}</td>
                <td style={TD_R}>{fmtValueMm(r.subj_dollars)}</td>
                <td style={{ ...TD_R, color: r.sec_pct_so == null ? 'var(--text-dim)' : 'var(--text)' }}>{fmtPct2(r.sec_pct_so)}</td>
                <td style={{ ...TD_R, color: r.sec_dollars == null ? 'var(--text-dim)' : 'var(--text)' }}>{fmtValueMm(r.sec_dollars)}</td>
              </tr>
            )
          })}
          {rows.length === 0 && (
            <tr><td colSpan={colCount} style={{ ...TD, textAlign: 'center', padding: 20, color: 'var(--text-dim)' }}>No funds found</td></tr>
          )}
        </tbody>
      </table>
    </TableBox>
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
