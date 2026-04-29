import { useMemo, useState } from 'react'
import { useAppStore } from '../../store/useAppStore'
import { useFetch } from '../../hooks/useFetch'
import type {
  SectorFlowsResponse,
  SectorFlowMoversResponse,
} from '../../types/api'
import {
  FundViewToggle,
  ActiveOnlyToggle,
  ExportBar,
  ColumnGroupHeader,
  FreshnessBadge,
} from '../common'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, Cell,
  ResponsiveContainer, ReferenceLine,
} from 'recharts'

// ── GICS sector colors ─────────────────────────────────────────────────────

const SECTOR_COLORS: Record<string, string> = {
  'Technology': '#7aadde',
  'Health Care': 'var(--pos)',
  'Financials': 'var(--header)',
  'Energy': 'var(--gold)',
  'Consumer Discretionary': '#b09ee0',
  'Industrials': 'var(--gold)',
  'Communication Services': 'var(--text-mute)',
  'Consumer Staples': '#5cb87a',
  'Materials': 'var(--text-dim)',
  'Real Estate': 'var(--neg)',
  'Utilities': 'var(--text-dim)',
}

function sectorColor(sector: string): string {
  return SECTOR_COLORS[sector] || 'var(--text-dim)'
}

// ── Formatters ─────────────────────────────────────────────────────────────

const NUM_0 = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 })
const NUM_1 = new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 })

function fmtMm(v: number | null): string {
  if (v == null || v === 0) return '—'
  return `$${NUM_0.format(v / 1e6)}`
}

function SignedMm({ v }: { v: number | null }) {
  if (v == null || v === 0) return <>—</>
  const mm = v / 1e6
  if (v < 0) return <span style={{ color: 'var(--neg)' }}>({NUM_0.format(Math.abs(mm))})</span>
  return <span style={{ color: 'var(--pos)' }}>+{NUM_0.format(mm)}</span>
}

// ── Styles ─────────────────────────────────────────────────────────────────

const TH: React.CSSProperties = {
  padding: '7px 8px', fontSize: 9, fontWeight: 700,
  textTransform: 'uppercase', letterSpacing: '0.16em', fontFamily: "'Hanken Grotesk', sans-serif",
  color: 'var(--text-dim)', backgroundColor: 'var(--header)',
  textAlign: 'left', borderBottom: '1px solid var(--line)',
  whiteSpace: 'nowrap', position: 'sticky', top: 30, zIndex: 3,
}
const TH_R: React.CSSProperties = { ...TH, textAlign: 'right' }
const TD: React.CSSProperties = {
  padding: '5px 8px', fontSize: 12, color: 'var(--text)',
  borderBottom: '1px solid var(--line-soft)',
}
const TD_R: React.CSSProperties = {
  ...TD, textAlign: 'right', fontVariantNumeric: 'tabular-nums',
  fontFamily: "'JetBrains Mono', monospace",
}
const CENTER_MSG: React.CSSProperties = { padding: 40, fontSize: 14, textAlign: 'center' }

// Footer cell
const FC: React.CSSProperties = {
  padding: '5px 8px', fontSize: 11, fontWeight: 600,
  color: 'var(--white)', backgroundColor: 'var(--header)',
  position: 'sticky', bottom: 0, zIndex: 2,
  borderTop: '2px solid var(--header)',
}
const FCR: React.CSSProperties = { ...FC, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }

// ── Component ──────────────────────────────────────────────────────────────

export function SectorRotationTab() {
  const { rollupType } = useAppStore()

  const [fundView, setFundView] = useState<'hierarchy' | 'fund'>('hierarchy')
  const [activeOnly, setActiveOnly] = useState(false)
  const [selectedSector, setSelectedSector] = useState<string | null>(null)
  const [periodCount, setPeriodCount] = useState<1 | 2 | 3>(3)

  const level = fundView === 'fund' ? 'fund' : 'parent'
  const ao = activeOnly ? '1' : '0'

  // Market-wide — no ticker dependency. Load on tab activation.
  const url = `/api/v1/sector_flows?active_only=${ao}&level=${level}`
  const { data, loading, error } = useFetch<SectorFlowsResponse>(url)

  // Filter periods based on period selector (last N)
  const allPeriods = data?.periods ?? []
  const periods = allPeriods.slice(-periodCount)

  // Movers fetch — on sector row click, for the selected period range's latest
  const latestPeriod = periods[periods.length - 1] ?? null
  const moversUrl = selectedSector && latestPeriod
    ? `/api/v1/sector_flow_movers?from=${enc(latestPeriod.from)}&to=${enc(latestPeriod.to)}&sector=${enc(selectedSector)}&active_only=${ao}&level=${level}&rollup_type=${rollupType}`
    : null
  const movers = useFetch<SectorFlowMoversResponse>(moversUrl)

  // Sort sectors by latest_net descending for chart + table
  const sortedSectors = useMemo(() => {
    if (!data) return []
    return [...data.sectors].sort((a, b) => b.latest_net - a.latest_net)
  }, [data])

  // periods already computed above from allPeriods.slice(-periodCount)

  // Chart data — latest period net per sector
  const chartData = useMemo(() => {
    if (!data || !latestPeriod) return []
    const key = `${latestPeriod.from}_${latestPeriod.to}`
    return sortedSectors.map(s => ({
      sector: s.sector.length > 12 ? s.sector.substring(0, 12) + '…' : s.sector,
      sectorFull: s.sector,
      net: (s.flows[key]?.net || 0) / 1e9,
      netRaw: s.flows[key]?.net || 0,
      inflow: s.flows[key]?.inflow || 0,
      outflow: s.flows[key]?.outflow || 0,
    }))
  }, [data, sortedSectors, latestPeriod])

  // Footer totals
  const footerTotals = useMemo(() => {
    if (!data) return { totalNet: 0, periods: {} as Record<string, number> }
    let totalNet = 0
    const byPeriod: Record<string, number> = {}
    for (const p of periods) {
      const key = `${p.from}_${p.to}`
      byPeriod[key] = 0
    }
    for (const s of data.sectors) {
      totalNet += s.total_net
      for (const p of periods) {
        const key = `${p.from}_${p.to}`
        byPeriod[key] += s.flows[key]?.net || 0
      }
    }
    return { totalNet, periods: byPeriod }
  }, [data, periods])

  function onExcel() {
    if (!data) return
    const h = ['Sector', 'Total Net ($MM)', ...periods.map(p => `${p.label} Net ($MM)`)]
    const csv = [h, ...sortedSectors.map(s => [
      `"${s.sector}"`, (s.total_net / 1e6).toFixed(0),
      ...periods.map(p => {
        const key = `${p.from}_${p.to}`
        const n = s.flows[key]?.net
        return n != null ? (n / 1e6).toFixed(0) : ''
      }),
    ])].map(r => r.join(',')).join('\n')
    downloadCsv(csv, 'sector_rotation.csv')
  }

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', backgroundColor: 'var(--panel)', borderRadius: 0, boxShadow: '0 1px 2px rgba(0,0,0,0.04)', overflow: 'hidden' }}>
      <style>{`
        @media print {
          .sr-controls { display:none!important }
          .sr-wrap { height:auto!important; max-height:none!important; overflow:visible!important }
          .sr-wrap * { max-height:none!important }
        }
      `}</style>

      {/* Controls */}
      <div className="sr-controls" style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'flex-end', gap: 16, padding: '12px 16px', backgroundColor: 'var(--panel)', borderBottom: '1px solid var(--line)', flexShrink: 0 }}>
        {/* Period selector */}
        <div style={{ display: 'flex', gap: 4 }}>
          {([{ n: 1 as const, label: 'Last Quarter' }, { n: 2 as const, label: 'Last 2 Quarters' }, { n: 3 as const, label: 'Last 3 Quarters' }]).map(p => (
            <button key={p.n} type="button" onClick={() => setPeriodCount(p.n)}
              style={{
                padding: '5px 12px', fontSize: 11, borderRadius: 0, cursor: 'pointer',
                fontWeight: periodCount === p.n ? 700 : 400,
                color: periodCount === p.n ? '#000000' : 'var(--text-dim)',
                backgroundColor: periodCount === p.n ? 'var(--gold)' : 'transparent',
                border: '1px solid var(--line)',
                letterSpacing: '0.06em', textTransform: 'uppercase',
                fontFamily: "'Inter', sans-serif",
                transition: 'all 0.12s',
              }}>
              {p.label}
            </button>
          ))}
        </div>
        <FundViewToggle value={fundView} onChange={setFundView} />
        <ActiveOnlyToggle value={activeOnly} onChange={setActiveOnly} label="Active Only" />
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 10 }}>
          <FreshnessBadge tableName="investor_flows" label="flows" />
          <ExportBar onExcel={onExcel} onPrint={() => window.print()} disabled={!data} />
        </div>
      </div>

      {/* Content */}
      <div className="sr-wrap" style={{ flex: 1, overflowY: 'auto', overflowX: 'auto' }}>
        {loading && <div style={{ ...CENTER_MSG, color: 'var(--text-dim)' }}>Loading…</div>}
        {error && !loading && <div style={{ ...CENTER_MSG, color: 'var(--neg)' }}>Error: {error}</div>}
        {data && !loading && (
          <div style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 16 }}>
            {/* Sector flow chart */}
            {chartData.length > 0 && (
              <div style={{ border: '1px solid var(--line)', borderRadius: 0, overflow: 'hidden', backgroundColor: 'var(--panel)' }}>
                <div style={{ padding: '6px 12px', backgroundColor: 'var(--header)', color: 'var(--white)', fontSize: 12, fontWeight: 700 }}>
                  Sector Net Flow — {latestPeriod?.label}
                </div>
                <div style={{ padding: '8px 8px 4px' }}>
                  <ResponsiveContainer width="100%" height={200}>
                    <BarChart data={chartData} barSize={28}>
                      <XAxis dataKey="sector" tick={{ fontSize: 9 }} interval={0} angle={-20} textAnchor="end" height={40} />
                      <YAxis tick={{ fontSize: 9 }} tickFormatter={(v: number) => `$${NUM_1.format(v)}B`} width={52} />
                      <Tooltip content={({ active, payload }) => {
                        if (!active || !payload || !payload[0]) return null
                        const d = payload[0].payload as { sectorFull: string; netRaw: number; inflow: number; outflow: number }
                        return (
                          <div style={{ backgroundColor: 'var(--bg)', color: 'var(--line)', padding: '8px 12px', borderRadius: 0, border: '1px solid var(--line)', fontSize: 11, lineHeight: 1.6 }}>
                            <div style={{ fontWeight: 700, marginBottom: 4 }}>{d.sectorFull}</div>
                            <div>Net: <span style={{ color: d.netRaw >= 0 ? 'var(--pos)' : 'var(--neg)' }}>{fmtMm(d.netRaw)}</span></div>
                            <div><span style={{ color: 'var(--pos)' }}>Inflow:</span> {fmtMm(d.inflow)}</div>
                            <div><span style={{ color: 'var(--neg)' }}>Outflow:</span> {fmtMm(d.outflow)}</div>
                          </div>
                        )
                      }} />
                      <ReferenceLine y={0} stroke="var(--text-dim)" strokeDasharray="3 3" />
                      <Bar dataKey="net" radius={[2, 2, 0, 0]}>
                        {chartData.map((d, i) => (
                          <Cell key={i} fill={d.net >= 0 ? sectorColor(d.sectorFull) : 'var(--neg)'} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>
            )}

            {/* Table + detail panel */}
            <div style={{ display: 'flex', gap: 12 }}>
              {/* Left: sector table */}
              <div style={{ flex: 3, border: '1px solid var(--line)', borderRadius: 0, overflow: 'hidden' }}>
                <div style={{ maxHeight: 500, overflowY: 'auto' }}>
                  <table style={{ width: '100%', borderCollapse: 'separate', borderSpacing: 0, tableLayout: 'fixed', fontSize: 12 }}>
                    <colgroup>
                      <col style={{ width: 160 }} />
                      <col style={{ width: 100 }} />
                      {periods.map(p => <col key={p.label} style={{ width: 90 }} />)}
                    </colgroup>
                    <thead>
                      <ColumnGroupHeader groups={[
                        { label: '', colSpan: 2 },
                        { label: 'Net Flow by Period', colSpan: periods.length || 1 },
                      ]} />
                      <tr>
                        <th style={TH}>Sector</th>
                        <th style={TH_R}>Total Net</th>
                        {periods.map(p => <th key={p.label} style={TH_R}>{p.label}</th>)}
                      </tr>
                    </thead>
                    <tbody>
                      {sortedSectors.map(s => {
                        const isSel = s.sector === selectedSector
                        return (
                          <tr key={s.sector}
                            onClick={() => setSelectedSector(isSel ? null : s.sector)}
                            style={{ backgroundColor: isSel ? 'rgba(122,173,222,0.08)' : undefined, cursor: 'pointer' }}>
                            <td style={{ ...TD, fontWeight: 600, borderLeft: `3px solid ${sectorColor(s.sector)}`, paddingLeft: 10 }}>
                              {s.sector}
                            </td>
                            <td style={TD_R}><SignedMm v={s.total_net} /></td>
                            {periods.map(p => {
                              const key = `${p.from}_${p.to}`
                              const n = s.flows[key]?.net ?? null
                              return <td key={p.label} style={TD_R}><SignedMm v={n} /></td>
                            })}
                          </tr>
                        )
                      })}
                    </tbody>
                    <tfoot>
                      <tr>
                        <td style={FC}>Total</td>
                        <td style={FCR}><span style={{ color: footerTotals.totalNet >= 0 ? 'var(--pos)' : 'var(--neg)' }}>{fmtMm(footerTotals.totalNet)}</span></td>
                        {periods.map(p => {
                          const key = `${p.from}_${p.to}`
                          const n = footerTotals.periods[key] || 0
                          return <td key={p.label} style={FCR}><span style={{ color: n >= 0 ? 'var(--pos)' : 'var(--neg)' }}>{fmtMm(n)}</span></td>
                        })}
                      </tr>
                    </tfoot>
                  </table>
                </div>
              </div>

              {/* Right: mover detail panel */}
              <div style={{ flex: 2 }}>
                {!selectedSector && (
                  <div style={{ ...CENTER_MSG, color: 'var(--text-dim)', border: '1px dashed var(--text-dim)', borderRadius: 0, minHeight: 200, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                    Click a sector to see top movers
                  </div>
                )}
                {selectedSector && movers.loading && (
                  <div style={{ ...CENTER_MSG, color: 'var(--text-dim)' }}>Loading movers…</div>
                )}
                {selectedSector && !movers.loading && movers.data && (
                  <div style={{ border: '1px solid var(--line)', borderRadius: 0, overflow: 'hidden' }}>
                    {/* Header */}
                    <div style={{ padding: '8px 12px', backgroundColor: 'var(--header)', color: 'var(--white)', fontSize: 12, fontWeight: 700, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span>{selectedSector} — {latestPeriod?.label}</span>
                      <button type="button" onClick={() => setSelectedSector(null)}
                        style={{ backgroundColor: 'transparent', border: 'none', color: 'var(--text-dim)', cursor: 'pointer', fontSize: 16 }}>×</button>
                    </div>
                    {/* Summary */}
                    <div style={{ padding: '6px 12px', fontSize: 11, color: 'var(--text-dim)', backgroundColor: 'var(--panel)', borderBottom: '1px solid var(--line)', display: 'flex', gap: 16 }}>
                      <span>Net: <b style={{ color: movers.data.summary.net >= 0 ? 'var(--pos)' : 'var(--neg)' }}>{fmtMm(movers.data.summary.net)}</b></span>
                      <span>Managers: <b>{NUM_0.format(movers.data.summary.buyers)}</b></span>
                    </div>
                    {/* Buyers */}
                    <MoverTable title="Top Buyers" rows={movers.data.top_buyers} color="var(--pos)" />
                    {/* Sellers */}
                    <MoverTable title="Top Sellers" rows={movers.data.top_sellers} color="var(--neg)" />
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Mover table ─────────────────────────────────────────────────────────────

function MoverTable({ title, rows, color }: {
  title: string
  rows: Array<{ institution: string; net_flow: number; buying: number; selling: number; positions_changed: number }>
  color: string
}) {
  return (
    <div>
      <div style={{ padding: '5px 12px', backgroundColor: color, color: 'var(--white)', fontSize: 11, fontWeight: 700 }}>{title}</div>
      <table style={{ width: '100%', borderCollapse: 'separate', borderSpacing: 0, fontSize: 11 }}>
        <thead>
          <tr>
            <th style={{ ...TH, fontSize: 9, padding: '4px 6px' }}>#</th>
            <th style={{ ...TH, fontSize: 9, padding: '4px 6px' }}>Institution</th>
            <th style={{ ...TH_R, fontSize: 9, padding: '4px 6px' }}>Net Flow</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={r.institution}>
              <td style={{ ...TD, fontSize: 11, padding: '3px 6px', width: 24, textAlign: 'right', color: 'var(--text-dim)' }}>{i + 1}</td>
              <td style={{ ...TD, fontSize: 11, padding: '3px 6px', fontWeight: 500, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: 0 }} title={r.institution}>{r.institution}</td>
              <td style={{ ...TD_R, fontSize: 11, padding: '3px 6px' }}><SignedMm v={r.net_flow} /></td>
            </tr>
          ))}
          {rows.length === 0 && <tr><td colSpan={3} style={{ ...TD, textAlign: 'center', color: 'var(--text-dim)', padding: 10 }}>None</td></tr>}
        </tbody>
      </table>
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
