import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useAppStore } from '../../store/useAppStore'
import { useFetch } from '../../hooks/useFetch'
import type { CrossOwnershipResponse } from '../../types/api'
import {
  RollupToggle,
  ActiveOnlyToggle,
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

// ── Styles ─────────────────────────────────────────────────────────────────

const TH: React.CSSProperties = {
  padding: '9px 10px', fontSize: 11, fontWeight: 700,
  textTransform: 'uppercase', letterSpacing: '0.04em',
  color: '#ffffff', backgroundColor: 'var(--oxford-blue)',
  textAlign: 'left', borderBottom: '1px solid #1e2d47',
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

// ── View type ──────────────────────────────────────────────────────────────

type ViewMode = 'anchor' | 'top'

// ── Ticker pill tag input ────────────────────────────────────────────��─────

interface TickerInputProps {
  tickers: string[]
  onChange: (tickers: string[]) => void
  maxTickers?: number
}

function TickerTagInput({ tickers, onChange, maxTickers = 10 }: TickerInputProps) {
  const [inputValue, setInputValue] = useState('')
  const [flash, setFlash] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  // Load the allTickers list on mount for validation
  const [allTickers, setAllTickers] = useState<Set<string>>(new Set())
  useEffect(() => {
    fetch('/api/tickers')
      .then(r => r.json())
      .then((list: Array<{ ticker: string }>) => {
        setAllTickers(new Set(list.map(t => t.ticker)))
      })
      .catch(() => {})
  }, [])

  const addTicker = useCallback((raw: string) => {
    const t = raw.trim().toUpperCase()
    if (!t) return
    if (tickers.includes(t)) return
    if (tickers.length >= maxTickers) return
    if (allTickers.size > 0 && !allTickers.has(t)) {
      setFlash(true)
      setTimeout(() => setFlash(false), 400)
      return
    }
    onChange([...tickers, t])
    setInputValue('')
  }, [tickers, onChange, maxTickers, allTickers])

  function removeTicker(t: string) {
    onChange(tickers.filter(x => x !== t))
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault()
      addTicker(inputValue)
    } else if (e.key === 'Backspace' && !inputValue && tickers.length > 0) {
      onChange(tickers.slice(0, -1))
    }
  }

  function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
    const v = e.target.value
    if (v.includes(',') || v.includes(' ')) {
      const parts = v.split(/[, ]+/)
      for (const p of parts) addTicker(p)
      setInputValue('')
    } else {
      setInputValue(v)
    }
  }

  return (
    <div
      onClick={() => inputRef.current?.focus()}
      style={{
        display: 'flex', flexWrap: 'wrap', gap: 4, alignItems: 'center',
        minWidth: 240, padding: '4px 8px',
        backgroundColor: '#ffffff', border: `1px solid ${flash ? '#ef4444' : '#e2e8f0'}`,
        borderRadius: 4, cursor: 'text', transition: 'border-color 0.2s',
      }}
    >
      {tickers.map(t => (
        <span key={t} style={{
          display: 'inline-flex', alignItems: 'center', gap: 3,
          padding: '2px 6px', fontSize: 12, fontWeight: 600,
          backgroundColor: 'var(--glacier-blue)', color: '#fff',
          borderRadius: 3,
        }}>
          {t}
          <button type="button" onClick={(e) => { e.stopPropagation(); removeTicker(t) }}
            style={{ backgroundColor: 'transparent', border: 'none', color: '#fff',
              cursor: 'pointer', padding: 0, fontSize: 13, lineHeight: 1 }}>
            ×
          </button>
        </span>
      ))}
      <input
        ref={inputRef}
        type="text"
        value={inputValue}
        onChange={handleChange}
        onKeyDown={handleKeyDown}
        placeholder={tickers.length === 0 ? 'Add tickers…' : ''}
        autoComplete="off" autoCorrect="off" spellCheck={false}
        style={{
          flex: 1, minWidth: 60, padding: '4px 0', fontSize: 13,
          border: 'none', outline: 'none', backgroundColor: 'transparent',
          color: '#1e293b',
        }}
      />
    </div>
  )
}

// ── Component ──────────────────────────────────────────────────────────────

export function CrossOwnershipTab() {
  const { ticker, rollupType } = useAppStore()

  const [viewMode, setViewMode] = useState<ViewMode>('anchor')
  const [groupTickers, setGroupTickers] = useState<string[]>([])
  const [anchor, setAnchor] = useState<string>('')
  const [activeOnly, setActiveOnly] = useState(false)

  // Pre-populate with header ticker on tab activation / ticker change
  useEffect(() => {
    if (ticker) {
      const upper = ticker.toUpperCase()
      setGroupTickers(prev => {
        if (prev.length === 0 || (prev.length === 1 && prev[0] !== upper)) return [upper]
        return prev
      })
      setAnchor(upper)
    }
  }, [ticker])

  // Build fetch URL
  const tickersStr = groupTickers.join(',')
  const url = useMemo(() => {
    if (!tickersStr) return null
    const base = viewMode === 'anchor'
      ? `/api/cross_ownership?tickers=${enc(tickersStr)}&anchor=${enc(anchor || groupTickers[0] || '')}&active_only=${activeOnly}&limit=25&rollup_type=${rollupType}`
      : `/api/cross_ownership_top?tickers=${enc(tickersStr)}&active_only=${activeOnly}&limit=25&rollup_type=${rollupType}`
    return base
  }, [tickersStr, viewMode, anchor, activeOnly, rollupType, groupTickers])

  const { data, loading, error } = useFetch<CrossOwnershipResponse>(url)

  // Dynamic ticker columns from response
  const dataTickers = data?.tickers ?? []
  const totalCols = 5 + dataTickers.length

  // Footer sums
  const footerSums = useMemo(() => {
    if (!data) return null
    let totalAcross = 0
    const perTicker: Record<string, number> = {}
    for (const t of dataTickers) perTicker[t] = 0
    for (const inv of data.investors) {
      totalAcross += inv.total_across || 0
      for (const t of dataTickers) {
        perTicker[t] += inv.holdings[t] || 0
      }
    }
    return { totalAcross, perTicker }
  }, [data, dataTickers])

  // CSV export
  function onExcel() {
    if (!data) return
    const h = ['Rank', 'Institution', 'Type', 'Total ($MM)', '% Portfolio',
      ...dataTickers.map(t => `${t} ($MM)`)]
    const csv = [h, ...data.investors.map((inv, i) => [
      i + 1,
      `"${inv.investor.replace(/"/g, '""')}"`,
      inv.type || '',
      inv.total_across != null ? (inv.total_across / 1e6).toFixed(0) : '',
      inv.pct_of_portfolio != null ? inv.pct_of_portfolio.toFixed(2) : '',
      ...dataTickers.map(t => {
        const v = inv.holdings[t]
        return v != null ? (v / 1e6).toFixed(0) : ''
      }),
    ])].map(r => r.join(',')).join('\n')
    downloadCsv(csv, `cross_ownership_${groupTickers.join('_')}.csv`)
  }

  if (!ticker) {
    return <div style={CENTER_MSG}><span style={{ color: '#94a3b8' }}>Enter a ticker to load cross-ownership</span></div>
  }

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', backgroundColor: 'var(--card-bg)', borderRadius: 6, boxShadow: '0 1px 2px rgba(0,0,0,0.04)', overflow: 'hidden' }}>
      <style>{`@media print { .co-controls { display:none!important } .co-wrap { height:auto!important; overflow:visible!important } }`}</style>

      {/* Controls */}
      <div className="co-controls" style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'flex-end', gap: 16, padding: '12px 16px', backgroundColor: '#f8fafc', borderBottom: '1px solid #e2e8f0', flexShrink: 0 }}>
        {/* View toggle */}
        <div style={{ display: 'flex', gap: 4 }}>
          {(['anchor', 'top'] as const).map(v => (
            <button key={v} type="button" onClick={() => setViewMode(v)}
              style={{
                padding: '5px 12px', fontSize: 12, borderRadius: 4, cursor: 'pointer',
                fontWeight: viewMode === v ? 600 : 400,
                color: viewMode === v ? '#fff' : '#64748b',
                backgroundColor: viewMode === v ? 'var(--oxford-blue)' : '#fff',
                border: `1px solid ${viewMode === v ? 'var(--oxford-blue)' : '#e2e8f0'}`,
              }}>
              {v === 'anchor' ? 'By Anchor' : 'Across Group'}
            </button>
          ))}
        </div>

        {/* Ticker group */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <span style={{ fontSize: 10, fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.08em' }}>Tickers (max 10)</span>
          <TickerTagInput tickers={groupTickers} onChange={setGroupTickers} />
        </div>

        {/* Anchor selector — only in anchor view */}
        {viewMode === 'anchor' && groupTickers.length > 0 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <span style={{ fontSize: 10, fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.08em' }}>Anchor</span>
            <select
              value={anchor}
              onChange={e => setAnchor(e.target.value)}
              style={{
                padding: '5px 10px', fontSize: 12, color: '#1e293b',
                backgroundColor: '#fff', border: '1px solid #e2e8f0',
                borderRadius: 4, outline: 'none',
              }}>
              {groupTickers.map(t => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
        )}

        <RollupToggle />
        <ActiveOnlyToggle value={activeOnly} onChange={setActiveOnly} label="Active Only" />
        <div style={{ marginLeft: 'auto' }}>
          <ExportBar onExcel={onExcel} onPrint={() => window.print()} disabled={!data} />
        </div>
      </div>

      {/* Content */}
      <div className="co-wrap" style={{ flex: 1, overflowY: 'auto', overflowX: 'auto', position: 'relative' }}>
        {loading && <div style={{ ...CENTER_MSG, color: '#94a3b8' }}>Loading…</div>}
        {error && !loading && <div style={{ ...CENTER_MSG, color: '#ef4444' }}>Error: {error}</div>}
        {!loading && !data && !error && groupTickers.length === 0 && (
          <div style={{ ...CENTER_MSG, color: '#94a3b8' }}>Add tickers above to load cross-ownership data</div>
        )}
        {data && !loading && (
          <div style={{ padding: 16 }}>
            <table style={{ width: '100%', borderCollapse: 'separate', borderSpacing: 0, tableLayout: 'fixed', fontSize: 13 }}>
              <colgroup>
                <col style={{ width: 60 }} />   {/* Rank */}
                <col style={{ width: 440 }} />  {/* Institution */}
                <col style={{ width: 120 }} />  {/* Type */}
                <col style={{ width: 90 }} />   {/* Total */}
                <col style={{ width: 80 }} />   {/* % Portfolio */}
                {dataTickers.map(t => <col key={t} style={{ width: 80 }} />)}
              </colgroup>
              <thead>
                <ColumnGroupHeader groups={[
                  { label: '', colSpan: 3 },
                  { label: 'Summary', colSpan: 2 },
                  { label: 'Holdings', colSpan: dataTickers.length || 1 },
                ]} />
                <tr>
                  <th style={TH_R}>Rank</th>
                  <th style={TH}>Institution</th>
                  <th style={TH}>Type</th>
                  <th style={TH_R}>Total ($MM)</th>
                  <th style={TH_R}>% Portfolio</th>
                  {dataTickers.map(t => (
                    <th key={t} style={TH_R}>{t}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.investors.map((inv, i) => {
                  const ts = getTypeStyle(inv.type)
                  const headerTicker = ticker?.toUpperCase() || ''
                  return (
                    <tr key={inv.investor}>
                      <td style={{ ...TD, textAlign: 'right', fontWeight: 700, color: '#64748b' }}>{i + 1}</td>
                      <td style={{ ...TD, fontWeight: 600, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: 0 }} title={inv.investor}>
                        <span style={{ display: 'inline-block', width: 14 }} />
                        {inv.investor}
                      </td>
                      <td style={TD}>
                        <span style={{ ...BADGE, backgroundColor: ts.bg, color: ts.color }}>{ts.label}</span>
                      </td>
                      <td style={TD_R}>{fmtValueMm(inv.total_across)}</td>
                      <td style={TD_R}>{fmtPct2(inv.pct_of_portfolio)}</td>
                      {dataTickers.map(t => {
                        const v = inv.holdings[t]
                        const isAnchor = viewMode === 'anchor' && t === (anchor || groupTickers[0])
                        const isSubject = t === headerTicker
                        return (
                          <td key={t} style={{
                            ...TD_R,
                            backgroundColor: isAnchor ? '#eff6ff' : undefined,
                            fontWeight: isSubject ? 700 : undefined,
                            color: v == null ? '#cbd5e1' : undefined,
                          }}>
                            {v != null ? fmtValueMm(v) : '—'}
                          </td>
                        )
                      })}
                    </tr>
                  )
                })}
                {data.investors.length === 0 && (
                  <tr><td colSpan={totalCols} style={{ ...TD, textAlign: 'center', padding: 30, color: '#64748b' }}>No investors found</td></tr>
                )}
              </tbody>
              {footerSums && (
                <tfoot>
                  <tr>
                    {/* Use manual footer instead of TableFooter since column
                        structure is dynamic and doesn't match TableFooter's
                        fixed named-column layout. */}
                    <FooterCell bottomPx={0} />
                    <FooterCell bottomPx={0}>Total</FooterCell>
                    <FooterCell bottomPx={0} />
                    <FooterCell bottomPx={0} align="right">{fmtValueMm(footerSums.totalAcross)}</FooterCell>
                    <FooterCell bottomPx={0} />
                    {dataTickers.map(t => (
                      <FooterCell key={t} bottomPx={0} align="right">
                        {fmtValueMm(footerSums.perTicker[t] || 0)}
                      </FooterCell>
                    ))}
                  </tr>
                </tfoot>
              )}
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Footer cell ─────────────────────────────────────────────────────────────
// Inline tfoot cell matching the TableFooter style. Used instead of the
// shared TableFooter because the column count is dynamic and doesn't fit
// the fixed named-column layout.

function FooterCell({ children, bottomPx = 0, align = 'left' }: {
  children?: React.ReactNode
  bottomPx?: number
  align?: 'left' | 'right'
}) {
  return (
    <td style={{
      padding: '7px 10px', fontSize: 13, fontWeight: 600,
      color: '#ffffff', backgroundColor: 'var(--oxford-blue)',
      position: 'sticky', bottom: bottomPx, zIndex: 2,
      borderTop: '2px solid var(--oxford-blue)',
      textAlign: align, fontVariantNumeric: align === 'right' ? 'tabular-nums' : undefined,
    }}>
      {children}
    </td>
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
