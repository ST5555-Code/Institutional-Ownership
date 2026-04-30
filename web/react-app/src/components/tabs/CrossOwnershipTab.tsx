import { useEffect, useMemo, useRef, useState } from 'react'
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

type ViewMode = 'anchor' | 'top'

// ── Module-level state persistence across tab switches ─────────────────────
// React unmounts the component when switching tabs. We save key state here
// so it survives the round-trip and the user's selections are still there
// when they return.

let _persisted: {
  additionalTickers: string[]
  viewMode: ViewMode
  anchor: string
  activeOnly: boolean
  peerGroupId: string
  fundView: 'hierarchy' | 'fund'
} | null = null

// ── Peer groups ────────────────────────────────────────────────────────────

interface PeerGroupTicker { ticker: string; company_name: string; is_primary: boolean }
interface PeerGroup { group_id: string; group_name: string; tickers: PeerGroupTicker[] }

// ── Individual ticker search input with dropdown ───────────────────────────

interface TickerSlotProps {
  value: string
  onChange: (ticker: string) => void
  onClear: () => void
  placeholder?: string
}

function TickerSlot({ value, onChange, onClear, placeholder = 'Add ticker…' }: TickerSlotProps) {
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
      allTickers.filter(t => t.ticker.startsWith(q) || t.name?.toUpperCase().includes(q)).slice(0, 8),
    )
    setOpen(true)
  }, [input, allTickers])

  useEffect(() => {
    function h(e: MouseEvent) { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false) }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [])

  function select(ticker: string) {
    setInput('')
    setOpen(false)
    onChange(ticker)
  }

  // If a value is set, render as a pill
  if (value) {
    return (
      <div style={{
        display: 'inline-flex', alignItems: 'center', gap: 4,
        padding: '4px 8px', fontSize: 12, fontWeight: 600,
        backgroundColor: 'var(--gold)', color: 'var(--white)',
        borderRadius: 0, minWidth: 70,
      }}>
        {value}
        <button type="button" onClick={onClear}
          style={{ backgroundColor: 'transparent', border: 'none', color: 'var(--white)',
            cursor: 'pointer', padding: 0, fontSize: 14, lineHeight: 1 }}>×</button>
      </div>
    )
  }

  return (
    <div ref={ref} style={{ position: 'relative', display: 'inline-block' }}>
      <input type="text" value={input} placeholder={placeholder}
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
          width: 120, padding: '5px 8px', fontSize: 12, color: 'var(--text)',
          backgroundColor: 'var(--bg)', borderRadius: 0, outline: 'none',
          border: `1px solid ${focused ? 'var(--gold)' : 'var(--line)'}`,
          transition: 'border-color 0.1s',
        }}
      />
      {open && options.length > 0 && (
        <div style={{
          position: 'absolute', top: '100%', left: 0, marginTop: 2,
          width: 220, maxHeight: 200, overflowY: 'auto',
          backgroundColor: 'var(--panel)', border: '1px solid var(--line)',
          borderRadius: 0, boxShadow: '0 4px 12px rgba(0,0,0,0.08)', zIndex: 1000,
        }}>
          {options.map(o => (
            <div key={o.ticker} onMouseDown={() => select(o.ticker)}
              style={{ padding: '6px 10px', fontSize: 12, cursor: 'pointer', display: 'flex', gap: 8, alignItems: 'center' }}
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

const MAX_ADDITIONAL = 9 // header ticker + 9 additional = 10 max

export function CrossOwnershipTab() {
  const { ticker, rollupType } = useAppStore()

  // Restore persisted state or use defaults
  const [additionalTickers, setAdditionalTickers] = useState<string[]>(_persisted?.additionalTickers ?? [])
  const [viewMode, setViewMode] = useState<ViewMode>(_persisted?.viewMode ?? 'anchor')
  const [anchor, setAnchor] = useState<string>(_persisted?.anchor ?? '')
  const [activeOnly, setActiveOnly] = useState(_persisted?.activeOnly ?? false)
  const [selectedPeerGroup, setSelectedPeerGroup] = useState(_persisted?.peerGroupId ?? '')
  const [fundView, setFundView] = useState<'hierarchy' | 'fund'>(_persisted?.fundView ?? 'hierarchy')

  // Persist state on unmount
  useEffect(() => {
    return () => {
      _persisted = {
        additionalTickers,
        viewMode,
        anchor,
        activeOnly,
        peerGroupId: selectedPeerGroup,
        fundView,
      }
    }
  })

  // Peer groups
  const peerGroupsUrl = '/api/v1/peer_groups'
  const peerGroups = useFetch<PeerGroup[]>(peerGroupsUrl)

  // When peer group selected, populate additional tickers from group
  useEffect(() => {
    if (!selectedPeerGroup || !peerGroups.data) return
    const group = peerGroups.data.find(g => g.group_id === selectedPeerGroup)
    if (!group) return
    const headerUpper = (ticker || '').toUpperCase()
    const others = group.tickers
      .map(t => t.ticker)
      .filter(t => t !== headerUpper)
      .slice(0, MAX_ADDITIONAL)
    setAdditionalTickers(others)
  }, [selectedPeerGroup, peerGroups.data, ticker])

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

  // All tickers in the anchor selector
  const anchorOptions = groupTickers

  // Fetch URL — require at least 2 tickers for a meaningful cross-ownership
  // comparison. With only the subject ticker, Total and the single holding
  // column show the same number, which is confusing.
  const tickersStr = groupTickers.join(',')
  const needsMoreTickers = groupTickers.length < 2
  const url = useMemo(() => {
    if (!tickersStr || needsMoreTickers) return null
    if (viewMode === 'anchor') {
      const a = anchor && groupTickers.includes(anchor) ? anchor : groupTickers[0] || ''
      return `/api/v1/cross_ownership?tickers=${enc(tickersStr)}&anchor=${enc(a)}&active_only=${activeOnly}&limit=25&rollup_type=${rollupType}`
    }
    return `/api/v1/cross_ownership_top?tickers=${enc(tickersStr)}&active_only=${activeOnly}&limit=25&rollup_type=${rollupType}`
  }, [tickersStr, needsMoreTickers, viewMode, anchor, activeOnly, rollupType, groupTickers])

  const { data, loading, error } = useFetch<CrossOwnershipResponse>(url)

  const dataTickers = data?.tickers ?? []
  const totalCols = 5 + dataTickers.length

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

  // Additional ticker slot handlers
  function setSlot(index: number, ticker: string) {
    setAdditionalTickers(prev => {
      const next = [...prev]
      next[index] = ticker
      return next
    })
    setSelectedPeerGroup('') // clear peer group on manual edit
  }
  function clearSlot(index: number) {
    setAdditionalTickers(prev => prev.filter((_, i) => i !== index))
    setSelectedPeerGroup('')
  }
  function addSlot() {
    if (additionalTickers.length < MAX_ADDITIONAL) {
      setAdditionalTickers(prev => [...prev, ''])
    }
  }

  if (!ticker) {
    return <div style={CENTER_MSG}><span style={{ color: 'var(--text-dim)' }}>Enter a ticker to load cross-ownership</span></div>
  }

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', backgroundColor: 'var(--panel)', borderRadius: 0, boxShadow: '0 1px 2px rgba(0,0,0,0.04)', overflow: 'hidden' }}>
      {/* Header row: PageHeader (left) + FreshnessBadge + ExportBar (right) */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', padding: '0 12px', flexShrink: 0 }}>
        <div style={{ flex: 1 }}>
          <PageHeader
            section="Targeting"
            title="Cross-Ownership"
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
        <div style={{ display: 'flex', gap: 4 }}>
          {(['anchor', 'top'] as const).map(v => (
            <button key={v} type="button" onClick={() => setViewMode(v)}
              style={{
                padding: '5px 12px', fontSize: 11, borderRadius: 0, cursor: 'pointer',
                fontWeight: viewMode === v ? 700 : 400,
                color: viewMode === v ? '#000000' : 'var(--text-dim)',
                backgroundColor: viewMode === v ? 'var(--gold)' : 'transparent',
                border: '1px solid var(--line)',
                letterSpacing: '0.06em', textTransform: 'uppercase',
                fontFamily: "'Inter', sans-serif",
                transition: 'all 0.12s',
              }}>
              {v === 'anchor' ? 'By Anchor' : 'Across Group'}
            </button>
          ))}
        </div>

        {/* Ticker slots */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <span style={{ fontSize: 10, fontWeight: 600, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>Tickers</span>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
            {/* Header ticker — locked */}
            <span style={{
              display: 'inline-flex', alignItems: 'center', padding: '4px 8px',
              fontSize: 12, fontWeight: 700, backgroundColor: 'var(--header)',
              color: 'var(--white)', borderRadius: 0,
            }}>
              {headerTicker}
            </span>
            {/* Additional slots */}
            {additionalTickers.map((t, i) => (
              <TickerSlot key={i} value={t}
                onChange={v => setSlot(i, v)}
                onClear={() => clearSlot(i)}
              />
            ))}
            {additionalTickers.length < MAX_ADDITIONAL && (
              <button type="button" onClick={addSlot}
                style={{
                  padding: '4px 10px', fontSize: 12, color: 'var(--text-dim)',
                  backgroundColor: 'var(--panel)', border: '1px dashed var(--text-dim)',
                  borderRadius: 0, cursor: 'pointer',
                }}>
                + Add
              </button>
            )}
          </div>
        </div>

        {/* Peer group selector */}
        {peerGroups.data && peerGroups.data.length > 0 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <span style={{ fontSize: 10, fontWeight: 600, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>Peer Group</span>
            <select
              value={selectedPeerGroup}
              onChange={e => setSelectedPeerGroup(e.target.value)}
              style={{
                padding: '5px 10px', fontSize: 12, color: 'var(--text)',
                backgroundColor: 'var(--panel)', border: '1px solid var(--line)',
                borderRadius: 0, outline: 'none',
              }}>
              <option value="">— Select group —</option>
              {peerGroups.data.map(g => (
                <option key={g.group_id} value={g.group_id}>{g.group_name} ({g.tickers.length})</option>
              ))}
            </select>
          </div>
        )}

        {/* Anchor selector — only in anchor view */}
        {viewMode === 'anchor' && anchorOptions.length > 1 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <span style={{ fontSize: 10, fontWeight: 600, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>Anchor</span>
            <select
              value={anchor}
              onChange={e => setAnchor(e.target.value)}
              style={{
                padding: '5px 10px', fontSize: 12, color: 'var(--text)',
                backgroundColor: 'var(--panel)', border: '1px solid var(--line)',
                borderRadius: 0, outline: 'none',
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
            {/* Column order: Rank · Institution · Type · [ticker cols] · Group Total · % Portfolio
                Tickers grow in the middle; summary stays pinned at the right edge. */}
            <table style={{ width: '100%', borderCollapse: 'separate', borderSpacing: 0, tableLayout: 'fixed', fontSize: 13 }}>
              <colgroup>
                <col style={{ width: 60 }} />   {/* Rank — same as Register/Conviction */}
                <col style={{ width: 440 }} />  {/* Institution — same as Register/Conviction */}
                <col style={{ width: 120 }} />  {/* Type — same as Register/Conviction */}
                {dataTickers.map(t => <col key={t} style={{ width: 80 }} />)}
                <col style={{ width: 90 }} />   {/* Group Total — right edge */}
                <col style={{ width: 80 }} />   {/* % Portfolio — right edge */}
              </colgroup>
              <thead>
                <ColumnGroupHeader groups={[
                  { label: '', colSpan: 3 },
                  { label: 'Holdings', colSpan: dataTickers.length || 1 },
                  { label: 'Summary', colSpan: 2 },
                ]} />
                <tr>
                  <th style={TH_R}>Rank</th>
                  <th style={TH}>Institution</th>
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
                  const effectiveAnchor = anchor && groupTickers.includes(anchor) ? anchor : groupTickers[0]
                  return (
                    <tr key={inv.investor} style={{ backgroundColor: rowBg }}>
                      <td style={{ ...TD, textAlign: 'right', fontWeight: 700, color: 'var(--text-dim)' }}>{i + 1}</td>
                      <td style={{
                        ...TD, fontWeight: 600, whiteSpace: 'nowrap',
                        overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: 0,
                      }} title={inv.investor}>
                        <span style={{ display: 'inline-block', width: 14 }} />
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
                    <FooterCell>Total</FooterCell>
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

// ── Footer cell ─────────────────────────────────────────────────────────────

function FooterCell({ children, align = 'left' }: {
  children?: React.ReactNode; align?: 'left' | 'right'
}) {
  return (
    <td style={{
      padding: '7px 10px', fontSize: 13, fontWeight: 600,
      color: 'var(--white)', backgroundColor: 'var(--header)',
      position: 'sticky', bottom: 0, zIndex: 2,
      borderTop: '2px solid var(--header)',
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
