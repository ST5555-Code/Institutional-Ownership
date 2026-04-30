import { Fragment, useEffect, useMemo, useRef, useState } from 'react'
import { useAppStore } from '../../store/useAppStore'
import { useFetch } from '../../hooks/useFetch'
import { useTickers } from '../../hooks/useTickers'
import type { CrossOwnershipResponse } from '../../types/api'
import {
  RollupToggle,
  ActiveOnlyToggle,
  FundViewToggle,
  ExportBar,
  ColumnGroupHeader,
  FreshnessBadge,
  PageHeader,
  getTypeStyle,
} from '../common'
import { fmtQuarter } from '../common/formatters'

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

function fmtSharesMm(v: number | null): string {
  if (v == null || v === 0) return '—'
  return NUM_2.format(v / 1e6)
}

// ── Styles (Register-consistent first 3 columns) ──────────────────────────

const TH: React.CSSProperties = {
  padding: '4px 8px', fontSize: 8, fontWeight: 700,
  textTransform: 'uppercase', letterSpacing: '0.16em', fontFamily: "'Hanken Grotesk', sans-serif",
  color: 'var(--text-dim)', backgroundColor: 'var(--header)',
  textAlign: 'left', borderBottom: '1px solid var(--line)',
  whiteSpace: 'nowrap', position: 'sticky', top: 30, zIndex: 3,
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
const CENTER_MSG: React.CSSProperties = { padding: 40, fontSize: 14, textAlign: 'center' }

// Overlap row: investor holds ALL tickers in the group with non-null values.
const OVERLAP_BG = 'rgba(122,173,222,0.08)'
const CHILD_BG = 'rgba(197,162,84,0.03)'

type ViewMode = 'anchor' | 'top'
type PeerMode = 'industry' | 'sector' | 'custom'

// ── Module-level state persistence across tab switches ─────────────────────

let _persisted: {
  additionalTickers: string[]
  viewMode: ViewMode
  anchor: string
  activeOnly: boolean
  peerMode: PeerMode
  fundView: 'hierarchy' | 'fund'
} | null = null

// ── Peer-tickers response ──────────────────────────────────────────────────

interface PeerTickersResponse {
  ticker: string
  sector: string | null
  industry: string | null
  sector_peers: string[]
  industry_peers: string[]
}

// ── Fund-detail response ───────────────────────────────────────────────────

interface FundDetailFund {
  fund_name: string
  series_id: string | null
  type: string
  value: number
  shares: number
}
interface FundDetailResponse {
  institution: string
  anchor: string
  funds: FundDetailFund[]
}

// ── Inline ticker input (always visible, adds on Enter) ────────────────────

interface AddTickerInputProps {
  onAdd: (ticker: string) => void
  existing: Set<string>
  disabled?: boolean
}

function AddTickerInput({ onAdd, existing, disabled }: AddTickerInputProps) {
  const [input, setInput] = useState('')
  const [options, setOptions] = useState<Array<{ ticker: string; name: string }>>([])
  const allTickers = useTickers()
  const [open, setOpen] = useState(false)
  const [focused, setFocused] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (input.length < 1) { setOptions([]); setOpen(false); return }
    const q = input.toUpperCase()
    setOptions(
      allTickers
        .filter(t => !existing.has(t.ticker))
        .filter(t => t.ticker.startsWith(q) || t.name?.toUpperCase().includes(q))
        .slice(0, 8),
    )
    setOpen(true)
  }, [input, allTickers, existing])

  useEffect(() => {
    function h(e: MouseEvent) { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false) }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [])

  function commit(ticker: string) {
    if (existing.has(ticker)) return
    onAdd(ticker)
    setInput('')
    setOpen(false)
  }

  return (
    <div ref={ref} style={{ position: 'relative', display: 'inline-block' }}>
      <input
        type="text"
        value={input}
        placeholder={disabled ? 'Max reached' : 'Add ticker…'}
        autoComplete="off"
        autoCorrect="off"
        spellCheck={false}
        disabled={disabled}
        onChange={e => setInput(e.target.value)}
        onKeyDown={e => {
          if (e.key === 'Enter' && input.trim()) {
            const t = input.trim().toUpperCase()
            if (allTickers.some(x => x.ticker === t) && !existing.has(t)) commit(t)
          }
        }}
        onFocus={() => { setFocused(true); if (input.length > 0) setOpen(true) }}
        onBlur={() => setFocused(false)}
        style={{
          width: 120, padding: '5px 8px', fontSize: 12, color: 'var(--text)',
          backgroundColor: 'var(--bg)', borderRadius: 0, outline: 'none',
          border: `1px solid ${focused ? 'var(--gold)' : 'var(--line)'}`,
          transition: 'border-color 0.1s',
          fontFamily: "'JetBrains Mono', monospace",
        }}
      />
      {open && options.length > 0 && (
        <div style={{
          position: 'absolute', top: '100%', left: 0, marginTop: 2,
          width: 240, maxHeight: 220, overflowY: 'auto',
          backgroundColor: 'var(--panel)', border: '1px solid var(--line)',
          borderRadius: 0, boxShadow: '0 12px 40px rgba(0,0,0,0.5)', zIndex: 1000,
        }}>
          {options.map(o => (
            <div
              key={o.ticker}
              onMouseDown={() => commit(o.ticker)}
              style={{ padding: '6px 10px', fontSize: 12, cursor: 'pointer', display: 'flex', gap: 8, alignItems: 'center' }}
              onMouseEnter={e => (e.currentTarget.style.backgroundColor = 'var(--panel-hi)')}
              onMouseLeave={e => (e.currentTarget.style.backgroundColor = 'transparent')}
            >
              <span style={{ color: 'var(--gold)', fontWeight: 700, width: 56, flexShrink: 0, fontFamily: "'JetBrains Mono', monospace" }}>{o.ticker}</span>
              <span style={{ color: 'var(--text-dim)', fontSize: 11, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{o.name}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Pill for an existing ticker (with ✕ remove) ────────────────────────────

function TickerPill({ value, onClear, locked }: { value: string; onClear?: () => void; locked?: boolean }) {
  return (
    <div style={{
      display: 'inline-flex', alignItems: 'center', gap: 4,
      padding: '4px 8px', fontSize: 12, fontWeight: 700,
      backgroundColor: locked ? 'var(--header)' : 'var(--gold)',
      color: locked ? 'var(--white)' : '#000',
      borderRadius: 0, fontFamily: "'JetBrains Mono', monospace",
    }}>
      {value}
      {!locked && onClear && (
        <button
          type="button"
          onClick={onClear}
          style={{
            backgroundColor: 'transparent', border: 'none', color: '#000',
            cursor: 'pointer', padding: 0, fontSize: 14, lineHeight: 1,
          }}
        >×</button>
      )}
    </div>
  )
}

// ── Component ──────────────────────────────────────────────────────────────

const MAX_ADDITIONAL = 9 // header ticker + 9 additional = 10 max

export function CrossOwnershipTab() {
  const { ticker, rollupType, quarter } = useAppStore()

  // Restore persisted state or use defaults
  const [additionalTickers, setAdditionalTickers] = useState<string[]>(_persisted?.additionalTickers ?? [])
  const [viewMode, setViewMode] = useState<ViewMode>(_persisted?.viewMode ?? 'anchor')
  const [anchor, setAnchor] = useState<string>(_persisted?.anchor ?? '')
  const [activeOnly, setActiveOnly] = useState(_persisted?.activeOnly ?? false)
  const [peerMode, setPeerMode] = useState<PeerMode>(_persisted?.peerMode ?? 'custom')
  const [fundView, setFundView] = useState<'hierarchy' | 'fund'>(_persisted?.fundView ?? 'hierarchy')
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  // Persist state on unmount
  useEffect(() => {
    return () => {
      _persisted = {
        additionalTickers,
        viewMode,
        anchor,
        activeOnly,
        peerMode,
        fundView,
      }
    }
  })

  // Peer-tickers fetch — sector + industry classifications for the loaded ticker
  const peerUrl = ticker ? `/api/v1/peer_tickers?ticker=${encodeURIComponent(ticker)}` : null
  const peers = useFetch<PeerTickersResponse>(peerUrl)

  // When peer mode changes (industry/sector), populate additional tickers from peers
  useEffect(() => {
    if (peerMode === 'custom' || !peers.data) return
    const headerUpper = (ticker || '').toUpperCase()
    const list = peerMode === 'industry' ? peers.data.industry_peers : peers.data.sector_peers
    const others = list.filter(t => t !== headerUpper).slice(0, MAX_ADDITIONAL)
    setAdditionalTickers(others)
  }, [peerMode, peers.data, ticker])

  // Set anchor to header ticker on load
  useEffect(() => {
    if (ticker && !anchor) setAnchor(ticker.toUpperCase())
  }, [ticker, anchor])

  // Build full ticker list: header ticker + additionals (deduped)
  const headerTicker = (ticker || '').toUpperCase()
  const groupTickers = useMemo(() => {
    const set = new Set<string>()
    if (headerTicker) set.add(headerTicker)
    for (const t of additionalTickers) if (t) set.add(t)
    return Array.from(set)
  }, [headerTicker, additionalTickers])
  const groupSet = useMemo(() => new Set(groupTickers), [groupTickers])
  const anchorOptions = groupTickers

  // Effective anchor — falls back to first ticker when current anchor isn't in group
  const effectiveAnchor = anchor && groupTickers.includes(anchor) ? anchor : groupTickers[0] || ''

  // level=parent|fund for the API
  const apiLevel = fundView === 'fund' ? 'fund' : 'parent'

  // Fetch URL — require at least 2 tickers for a meaningful cross-ownership comparison.
  const tickersStr = groupTickers.join(',')
  const needsMoreTickers = groupTickers.length < 2
  const url = useMemo(() => {
    if (!tickersStr || needsMoreTickers) return null
    if (viewMode === 'anchor') {
      return `/api/v1/cross_ownership?tickers=${enc(tickersStr)}&anchor=${enc(effectiveAnchor)}&active_only=${activeOnly}&limit=25&rollup_type=${rollupType}&level=${apiLevel}`
    }
    return `/api/v1/cross_ownership_top?tickers=${enc(tickersStr)}&active_only=${activeOnly}&limit=25&rollup_type=${rollupType}&level=${apiLevel}`
  }, [tickersStr, needsMoreTickers, viewMode, effectiveAnchor, activeOnly, rollupType, apiLevel])

  // Reset expanded set when the URL (data context) changes — stale keys are harmless
  // but resetting keeps drill-downs from re-opening with mismatched data.
  useEffect(() => { setExpanded(new Set()) }, [url])

  const { data, loading, error } = useFetch<CrossOwnershipResponse>(url)

  const dataTickers = data?.tickers ?? []
  // 1 (expand) + 3 (Rank/Inst/Type) + tickers + 2 (Group Total / % Portfolio)
  const totalCols = 1 + 3 + dataTickers.length + 2

  // Overlap detection: investor holds ALL group tickers with non-null value
  function isOverlap(holdings: Record<string, number | null>): boolean {
    return dataTickers.every(t => holdings[t] != null)
  }

  // Footer sums
  const footerSums = useMemo(() => {
    if (!data) return null
    let totalAcross = 0
    const perTicker: Record<string, number> = {}
    for (const t of dataTickers) perTicker[t] = 0
    for (const inv of data.investors) {
      totalAcross += inv.total_across || 0
      for (const t of dataTickers) perTicker[t] += inv.holdings[t] || 0
    }
    return { totalAcross, perTicker }
  }, [data, dataTickers])

  function toggleExpand(key: string) {
    setExpanded(prev => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  // CSV export
  function onExcel() {
    if (!data) return
    const h = ['Rank', 'Institution', 'Type',
      ...dataTickers.map(t => `${t} ($MM)`),
      'Group Total ($MM)', '% Portfolio']
    const csv = [h, ...data.investors.map((inv, i) => [
      i + 1, `"${inv.investor.replace(/"/g, '""')}"`, inv.type || '',
      ...dataTickers.map(t => { const v = inv.holdings[t]; return v != null ? (v / 1e6).toFixed(0) : '' }),
      inv.total_across != null ? (inv.total_across / 1e6).toFixed(0) : '',
      inv.pct_of_portfolio != null ? inv.pct_of_portfolio.toFixed(2) : '',
    ])].map(r => r.join(',')).join('\n')
    downloadCsv(csv, `cross_ownership_${groupTickers.join('_')}.csv`)
  }

  function removeAdditional(t: string) {
    setAdditionalTickers(prev => prev.filter(x => x !== t))
    setPeerMode('custom')
  }
  function addAdditional(t: string) {
    if (additionalTickers.length >= MAX_ADDITIONAL) return
    setAdditionalTickers(prev => prev.includes(t) ? prev : [...prev, t])
    setPeerMode('custom')
  }

  if (!ticker) {
    return <div style={CENTER_MSG}><span style={{ color: 'var(--text-dim)' }}>Enter a ticker to load cross-ownership</span></div>
  }

  const titleQuarter = fmtQuarter(quarter)
  const title = titleQuarter ? `Cross-Ownership (${titleQuarter})` : 'Cross-Ownership'

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', backgroundColor: 'var(--panel)', borderRadius: 0, boxShadow: '0 1px 2px rgba(0,0,0,0.04)', overflow: 'hidden' }}>
      {/* Header row: PageHeader (left) + FreshnessBadge + ExportBar (right) */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', padding: '0 12px', flexShrink: 0 }}>
        <div style={{ flex: 1 }}>
          <PageHeader
            section="Targeting"
            title={title}
            description="Multi-ticker institutional holder comparison. Add tickers to see who owns what across the group."
          />
        </div>
        <div className="no-print" style={{ display: 'flex', alignItems: 'center', gap: 10, paddingTop: 14 }}>
          <FreshnessBadge tableName="summary_by_parent" label="register" />
          <ExportBar onExcel={onExcel} onPrint={() => window.print()} disabled={!data} />
        </div>
      </div>
      <style>{`@media print { .co-controls { display:none!important } .no-print { display:none!important } .co-wrap { height:auto!important; overflow:visible!important } }`}</style>

      {/* Controls */}
      <div className="co-controls" style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'flex-end', gap: 12, padding: '10px 12px', backgroundColor: 'var(--panel)', border: '1px solid var(--line)', borderRadius: 0, margin: '0 12px', flexShrink: 0 }}>
        {/* View toggle */}
        <div style={{ display: 'flex', gap: 0 }}>
          {(['anchor', 'top'] as const).map((v, i) => (
            <button key={v} type="button" onClick={() => setViewMode(v)}
              style={{
                padding: '5px 12px', fontSize: 11, borderRadius: 0, cursor: 'pointer',
                fontWeight: viewMode === v ? 700 : 400,
                color: viewMode === v ? '#000000' : 'var(--text-dim)',
                backgroundColor: viewMode === v ? 'var(--gold)' : 'transparent',
                border: '1px solid var(--line)', borderLeft: i === 0 ? '1px solid var(--line)' : 'none',
                letterSpacing: '0.06em', textTransform: 'uppercase',
                fontFamily: "'Inter', sans-serif",
                transition: 'all 0.12s',
              }}>
              {v === 'anchor' ? 'By Anchor' : 'Across Group'}
            </button>
          ))}
        </div>

        {/* Peer Group dropdown — Industry / Sector / Custom */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <span style={{ fontSize: 9, fontWeight: 700, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.16em', fontFamily: "'Hanken Grotesk', sans-serif" }}>Peer Group</span>
          <select
            value={peerMode}
            onChange={e => setPeerMode(e.target.value as PeerMode)}
            style={{
              padding: '5px 10px', fontSize: 12, color: 'var(--text)',
              backgroundColor: 'var(--bg)', border: '1px solid var(--line)',
              borderRadius: 0, outline: 'none', minWidth: 180,
              fontFamily: "'Inter', sans-serif",
            }}>
            <option value="custom">Custom</option>
            {peers.data?.industry && (
              <option value="industry">{peers.data.industry} Peers ({peers.data.industry_peers.length})</option>
            )}
            {peers.data?.sector && (
              <option value="sector">{peers.data.sector} Peers ({peers.data.sector_peers.length})</option>
            )}
          </select>
        </div>

        {/* Ticker pills + inline input */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <span style={{ fontSize: 9, fontWeight: 700, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.16em', fontFamily: "'Hanken Grotesk', sans-serif" }}>Tickers</span>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
            <TickerPill value={headerTicker} locked />
            {additionalTickers.map(t => (
              <TickerPill key={t} value={t} onClear={() => removeAdditional(t)} />
            ))}
            <AddTickerInput
              onAdd={addAdditional}
              existing={groupSet}
              disabled={additionalTickers.length >= MAX_ADDITIONAL}
            />
          </div>
        </div>

        {/* Anchor selector — only in anchor view */}
        {viewMode === 'anchor' && anchorOptions.length > 1 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <span style={{ fontSize: 9, fontWeight: 700, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.16em', fontFamily: "'Hanken Grotesk', sans-serif" }}>Anchor</span>
            <select
              value={anchor}
              onChange={e => setAnchor(e.target.value)}
              style={{
                padding: '5px 10px', fontSize: 12, color: 'var(--text)',
                backgroundColor: 'var(--bg)', border: '1px solid var(--line)',
                borderRadius: 0, outline: 'none',
                fontFamily: "'JetBrains Mono', monospace",
              }}>
              {anchorOptions.map(t => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
        )}

        <RollupToggle />
        <FundViewToggle value={fundView} onChange={setFundView} />
        <ActiveOnlyToggle value={activeOnly} onChange={setActiveOnly} label="Active Only" />
      </div>

      {/* Content */}
      <div className="co-wrap" style={{ flex: 1, overflowY: 'auto', overflowX: 'auto', position: 'relative' }}>
        {loading && <div style={{ ...CENTER_MSG, color: 'var(--text-dim)' }}>Loading…</div>}
        {error && !loading && <div style={{ ...CENTER_MSG, color: 'var(--neg)' }}>Error: {error}</div>}
        {!loading && needsMoreTickers && (
          <div style={{ ...CENTER_MSG, color: 'var(--text-dim)' }}>Add at least one comparison ticker or select a peer group to see cross-ownership analysis</div>
        )}
        {data && !loading && (
          <div style={{ padding: 16 }}>
            {/* Column order: ▶ · Rank · Institution · Type · [ticker cols] · Group Total · % Portfolio */}
            <table style={{ width: '100%', borderCollapse: 'separate', borderSpacing: 0, tableLayout: 'fixed', fontSize: 13 }}>
              <colgroup>
                <col style={{ width: 24 }} />   {/* Expand triangle */}
                <col style={{ width: 60 }} />   {/* Rank */}
                <col style={{ width: 416 }} />  {/* Institution */}
                <col style={{ width: 120 }} />  {/* Type */}
                {dataTickers.map(t => <col key={t} style={{ width: 80 }} />)}
                <col style={{ width: 90 }} />   {/* Group Total */}
                <col style={{ width: 80 }} />   {/* % Portfolio */}
              </colgroup>
              <thead>
                <ColumnGroupHeader groups={[
                  { label: '', colSpan: 4 },
                  { label: 'Holdings', colSpan: dataTickers.length || 1 },
                  { label: 'Summary', colSpan: 2 },
                ]} />
                <tr>
                  <th style={TH} />
                  <th style={TH_R}>Rank</th>
                  <th style={TH}>{fundView === 'fund' ? 'Fund' : 'Institution'}</th>
                  <th style={TH}>Type</th>
                  {dataTickers.map(t => <th key={t} style={TH_R}>{t}</th>)}
                  <th style={TH_R}>Group Total</th>
                  <th style={TH_R}>% Portfolio</th>
                </tr>
              </thead>
              <tbody>
                {data.investors.map((inv, i) => {
                  const ts = getTypeStyle(inv.type)
                  const overlap = dataTickers.length > 1 && isOverlap(inv.holdings)
                  const rowBg = overlap ? OVERLAP_BG : undefined
                  const rowKey = `${i}:${inv.investor}`
                  const isOpen = expanded.has(rowKey)
                  // Fund-level rows are individual fund series; no parent→fund drill-down.
                  const canExpand = fundView !== 'fund'
                  return (
                    <Fragment key={rowKey}>
                      <tr style={{ backgroundColor: rowBg }}>
                        <td
                          style={{
                            ...TD, padding: '4px 0 4px 4px', textAlign: 'center',
                            cursor: canExpand ? 'pointer' : 'default', userSelect: 'none',
                          }}
                          onClick={canExpand ? () => toggleExpand(rowKey) : undefined}
                        >
                          {canExpand && (
                            <span style={{
                              display: 'inline-block', color: 'var(--gold)', fontSize: 9,
                              transition: 'transform 0.12s',
                              transform: isOpen ? 'rotate(90deg)' : 'rotate(0deg)',
                            }}>▶</span>
                          )}
                        </td>
                        <td style={{ ...TD, textAlign: 'right', fontWeight: 700, color: 'var(--text-dim)' }}>{i + 1}</td>
                        <td
                          style={{
                            ...TD, fontWeight: 600, whiteSpace: 'nowrap',
                            overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: 0,
                            cursor: canExpand ? 'pointer' : 'default', userSelect: 'none',
                          }}
                          title={inv.investor}
                          onClick={canExpand ? () => toggleExpand(rowKey) : undefined}
                        >
                          {inv.investor}
                        </td>
                        <td style={TD}>
                          <span style={{ ...BADGE, backgroundColor: ts.bg, color: ts.color }}>{ts.label}</span>
                        </td>
                        {dataTickers.map(t => {
                          const v = inv.holdings[t]
                          const isAnchorCol = viewMode === 'anchor' && t === effectiveAnchor
                          return (
                            <td key={t} style={{
                              ...TD_R,
                              backgroundColor: isAnchorCol && !overlap ? 'rgba(122,173,222,0.08)' : undefined,
                              color: v == null ? 'var(--text-dim)' : 'var(--text)',
                            }}>
                              {v != null ? fmtValueMm(v) : '—'}
                            </td>
                          )
                        })}
                        <td style={TD_R}>{fmtValueMm(inv.total_across)}</td>
                        <td style={TD_R}>{fmtPct2(inv.pct_of_portfolio)}</td>
                      </tr>
                      {isOpen && canExpand && (
                        <FundDetailRows
                          institution={inv.investor}
                          anchor={effectiveAnchor}
                          tickers={groupTickers}
                          quarter={quarter}
                          totalCols={totalCols}
                        />
                      )}
                    </Fragment>
                  )
                })}
                {data.investors.length === 0 && (
                  <tr><td colSpan={totalCols} style={{ ...TD, textAlign: 'center', padding: 30, color: 'var(--text-dim)' }}>No investors found</td></tr>
                )}
              </tbody>
              {footerSums && (
                <tfoot>
                  <tr>
                    <FooterCell />
                    <FooterCell />
                    <FooterCell>Group Total</FooterCell>
                    <FooterCell />
                    {dataTickers.map(t => (
                      <FooterCell key={t} align="right">{fmtValueMm(footerSums.perTicker[t] || 0)}</FooterCell>
                    ))}
                    <FooterCell align="right">{fmtValueMm(footerSums.totalAcross)}</FooterCell>
                    <FooterCell />
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

// ── Fund-detail child rows ─────────────────────────────────────────────────

interface FundDetailRowsProps {
  institution: string
  anchor: string
  tickers: string[]
  quarter: string
  totalCols: number
}

function FundDetailRows({ institution, anchor, tickers, quarter, totalCols }: FundDetailRowsProps) {
  const url = anchor && institution
    ? `/api/v1/cross_ownership_fund_detail?tickers=${enc(tickers.join(','))}&institution=${enc(institution)}&anchor=${enc(anchor)}&quarter=${enc(quarter)}`
    : null
  const { data, loading, error } = useFetch<FundDetailResponse>(url)

  const railCell: React.CSSProperties = {
    ...TD, padding: 0, borderLeft: '2px solid var(--gold)', backgroundColor: CHILD_BG,
  }

  if (loading) {
    return (
      <tr style={{ backgroundColor: CHILD_BG }}>
        <td style={railCell} />
        <td colSpan={totalCols - 1} style={{ ...TD, color: 'var(--text-dim)', fontStyle: 'italic', backgroundColor: CHILD_BG }}>
          Loading top funds…
        </td>
      </tr>
    )
  }
  if (error || !data) {
    return (
      <tr style={{ backgroundColor: CHILD_BG }}>
        <td style={railCell} />
        <td colSpan={totalCols - 1} style={{ ...TD, color: 'var(--neg)', backgroundColor: CHILD_BG }}>
          {error || 'No fund data'}
        </td>
      </tr>
    )
  }

  if (data.funds.length === 0) {
    return (
      <tr style={{ backgroundColor: CHILD_BG }}>
        <td style={railCell} />
        <td colSpan={totalCols - 1} style={{ ...TD, color: 'var(--text-dim)', fontStyle: 'italic', backgroundColor: CHILD_BG }}>
          No N-PORT funds report holding {anchor} under this institution
        </td>
      </tr>
    )
  }

  return (
    <>
      {data.funds.map((f, i) => {
        const ts = getTypeStyle(f.type)
        return (
          <tr key={`fd-${i}-${f.series_id || f.fund_name}`} style={{ backgroundColor: CHILD_BG }}>
            <td style={railCell} />
            <td style={{ ...TD, backgroundColor: CHILD_BG }} />
            <td
              style={{
                ...TD, color: 'var(--text-mute)', paddingLeft: 24,
                whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: 0,
                backgroundColor: CHILD_BG,
              }}
              title={f.fund_name}
            >
              <span style={{ color: 'var(--text-mute)', marginRight: 6, fontSize: 11 }}>└</span>
              {f.fund_name}
            </td>
            <td style={{ ...TD, backgroundColor: CHILD_BG }}>
              <span style={{ ...BADGE, backgroundColor: ts.bg, color: ts.color }}>{ts.label}</span>
            </td>
            {/* Per-ticker holding columns: blank — drill-down focuses on the anchor */}
            {tickers.map(t => (
              <td key={t} style={{ ...TD_R, color: 'var(--text-dim)', backgroundColor: CHILD_BG }}>—</td>
            ))}
            {/* Group Total column repurposed as the anchor $MM value */}
            <td style={{ ...TD_R, backgroundColor: CHILD_BG }}>{fmtValueMm(f.value)}</td>
            {/* % Portfolio column repurposed as shares (MM) */}
            <td style={{ ...TD_R, backgroundColor: CHILD_BG }}>{fmtSharesMm(f.shares)}</td>
          </tr>
        )
      })}
    </>
  )
}

// ── Footer cell ─────────────────────────────────────────────────────────────

function FooterCell({ children, align = 'left' }: {
  children?: React.ReactNode; align?: 'left' | 'right'
}) {
  return (
    <td style={{
      padding: '7px 10px', fontSize: 13, fontWeight: 700,
      color: 'var(--gold)', backgroundColor: 'rgba(197,162,84,0.03)',
      position: 'sticky', bottom: 0, zIndex: 2,
      borderTop: '2px solid var(--gold)',
      textAlign: align, fontVariantNumeric: align === 'right' ? 'tabular-nums' : undefined,
      fontFamily: align === 'right' ? "'JetBrains Mono', monospace" : "'Inter', sans-serif",
      letterSpacing: align === 'left' ? '0.06em' : undefined,
      textTransform: align === 'left' ? 'uppercase' : undefined,
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
