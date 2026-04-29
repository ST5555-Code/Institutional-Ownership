import { useEffect, useMemo, useState } from 'react'
import { useAppStore } from '../../store/useAppStore'
import { useFetch } from '../../hooks/useFetch'
import type {
  SectorFlowsResponse,
  SectorFlowMoversResponse,
  SectorSummaryResponse,
} from '../../types/api'
import {
  FundViewToggle,
  ActiveOnlyToggle,
  ExportBar,
  FreshnessBadge,
} from '../common'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, Cell,
  ResponsiveContainer, ReferenceLine, Legend,
} from 'recharts'

// ── Formatters ─────────────────────────────────────────────────────────────

const NUM_0 = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 })
const NUM_1 = new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 })

function fmtAum(v: number | null | undefined): string {
  if (v == null || !isFinite(v)) return '—'
  const abs = Math.abs(v)
  if (abs >= 1e12) return `$${NUM_1.format(v / 1e12)}T`
  if (abs >= 1e9) return `$${NUM_0.format(v / 1e9)}B`
  if (abs >= 1e6) return `$${NUM_0.format(v / 1e6)}M`
  return `$${NUM_0.format(v)}`
}

function fmtMm(v: number | null | undefined): string {
  if (v == null || v === 0) return '—'
  return `$${NUM_0.format(v / 1e6)}`
}

function fmtPct(v: number | null | undefined): string {
  if (v == null || !isFinite(v)) return '—'
  return `${NUM_1.format(v * 100)}%`
}

function fmtQuarterLabel(q: string): string {
  // "2025Q2" → "Q2 '25"
  const m = /^(\d{4})Q(\d)$/.exec(q)
  if (!m) return q
  return `Q${m[2]} '${m[1].slice(2)}`
}

function SignedMm({ v }: { v: number | null }) {
  if (v == null || v === 0) return <>—</>
  const mm = v / 1e6
  if (v < 0) return <span style={{ color: 'var(--neg)' }}>({NUM_0.format(Math.abs(mm))})</span>
  return <span style={{ color: 'var(--pos)' }}>+{NUM_0.format(mm)}</span>
}

function SignedDollar({ v }: { v: number | null }) {
  if (v == null || v === 0) return <>—</>
  const mm = v / 1e6
  if (v < 0) return <span style={{ color: 'var(--neg)' }}>(${NUM_0.format(Math.abs(mm))})</span>
  return <span style={{ color: 'var(--pos)' }}>+${NUM_0.format(mm)}</span>
}

// ── Styles ─────────────────────────────────────────────────────────────────

const TH: React.CSSProperties = {
  padding: '7px 8px', fontSize: 9, fontWeight: 700,
  textTransform: 'uppercase', letterSpacing: '0.16em',
  fontFamily: "'Hanken Grotesk', sans-serif",
  color: 'var(--text-dim)', backgroundColor: 'var(--header)',
  textAlign: 'left', borderBottom: '1px solid var(--line)',
  whiteSpace: 'nowrap', position: 'sticky', top: 0, zIndex: 3,
}
const TH_R: React.CSSProperties = { ...TH, textAlign: 'right' }
const TD: React.CSSProperties = {
  padding: '6px 8px', fontSize: 12, color: 'var(--text)',
  borderBottom: '1px solid var(--line-soft)',
}
const TD_R: React.CSSProperties = {
  ...TD, textAlign: 'right', fontVariantNumeric: 'tabular-nums',
  fontFamily: "'JetBrains Mono', monospace",
}
const CENTER_MSG: React.CSSProperties = { padding: 40, fontSize: 14, textAlign: 'center' }

const KICKER: React.CSSProperties = {
  fontSize: 9, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.16em',
  fontFamily: "'Hanken Grotesk', sans-serif", color: 'var(--text-dim)',
}
const PANEL_TITLE: React.CSSProperties = {
  fontSize: 9, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.16em',
  fontFamily: "'Hanken Grotesk', sans-serif", color: 'var(--text-dim)',
  padding: '10px 14px', borderBottom: '1px solid var(--line)',
  backgroundColor: 'var(--card)',
}

// Period bar tints — three monochrome shades inside the same group
const PERIOD_FILLS = ['rgba(122,173,222,0.55)', 'rgba(122,173,222,0.78)', '#7aadde']

// ── Component ──────────────────────────────────────────────────────────────

export function SectorRotationTab() {
  const { rollupType } = useAppStore()

  const [fundView, setFundView] = useState<'hierarchy' | 'fund'>('hierarchy')
  const [activeOnly, setActiveOnly] = useState(false)
  const [selectedSector, setSelectedSector] = useState<string | null>(null)
  const [excludeOutliers, setExcludeOutliers] = useState(false)

  const level = fundView === 'fund' ? 'fund' : 'parent'
  const ao = activeOnly ? '1' : '0'

  // Static fetches (KPI row + net flows chart) — never refetch
  const summary = useFetch<SectorSummaryResponse>('/api/v1/sector_summary')
  const parentStatic = useFetch<SectorFlowsResponse>('/api/v1/sector_flows?level=parent&active_only=0')
  const fundStatic = useFetch<SectorFlowsResponse>('/api/v1/sector_flows?level=fund&active_only=0')

  // Toggleable fetch (chart + table + drives movers)
  const { data, loading, error } = useFetch<SectorFlowsResponse>(
    `/api/v1/sector_flows?active_only=${ao}&level=${level}`,
  )

  const periods = data?.periods ?? []

  // Sectors ranked 1..N by sum of net flow across all periods (desc)
  const ranked = useMemo(() => {
    if (!data) return []
    return [...data.sectors].sort((a, b) => (b.total_net || 0) - (a.total_net || 0))
  }, [data])

  // Auto-select rank-1 sector on data load and on toggle change
  useEffect(() => {
    if (!data || ranked.length === 0) return
    const top = ranked[0].sector
    if (!ranked.some(s => s.sector === selectedSector)) {
      setSelectedSector(top)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, level, ao])

  // Movers fetch — latest period of selected sector
  const latestPeriod = periods[periods.length - 1] ?? null
  const moversUrl = selectedSector && latestPeriod
    ? `/api/v1/sector_flow_movers?from=${enc(latestPeriod.from)}&to=${enc(latestPeriod.to)}&sector=${enc(selectedSector)}&active_only=${ao}&level=${level}&rollup_type=${rollupType}`
    : null
  const movers = useFetch<SectorFlowMoversResponse>(moversUrl)

  // Display quarters for table — Q1..Q4 of the latest period's destination year.
  // Quarters without matching period data render as placeholder columns.
  const displayQuarters = useMemo(() => {
    if (!periods.length) return [] as string[]
    const last = periods[periods.length - 1]
    const m = /^(\d{4})Q\d$/.exec(last.to)
    if (!m) return periods.map(p => p.to)
    const y = m[1]
    return [`${y}Q1`, `${y}Q2`, `${y}Q3`, `${y}Q4`]
  }, [periods])

  const periodByDest = useMemo(() => {
    const m: Record<string, typeof periods[number]> = {}
    periods.forEach(p => { m[p.to] = p })
    return m
  }, [periods])

  // Sector grouped chart — one row per sector with one column per period
  const sectorChartData = useMemo(() => {
    if (!data) return []
    return ranked.map((s, i) => {
      const row: Record<string, number | string> = {
        rank: i + 1,
        sector: s.sector,
        label: `${i + 1}. ${s.sector}`,
      }
      data.periods.forEach((p, pi) => {
        const key = `${p.from}_${p.to}`
        row[`p${pi}`] = (s.flows[key]?.net || 0) / 1e9
        row[`p${pi}_raw`] = s.flows[key]?.net || 0
      })
      return row
    })
  }, [data, ranked])

  // Net flows chart — sum each sector's net per period for parent + fund.
  // Compute from the static (active_only=0) responses so this never moves.
  const netFlowsChartData = useMemo(() => {
    const p = parentStatic.data
    const f = fundStatic.data
    const periodsRef = p?.periods ?? f?.periods ?? []
    return periodsRef.map(period => {
      const key = `${period.from}_${period.to}`
      const inst = (p?.sectors ?? []).reduce((sum, s) => sum + (s.flows[key]?.net || 0), 0)
      const fund = (f?.sectors ?? []).reduce((sum, s) => sum + (s.flows[key]?.net || 0), 0)
      return {
        period: period.label,
        institutional: inst / 1e9,
        institutionalRaw: inst,
        fund: fund / 1e9,
        fundRaw: fund,
      }
    })
  }, [parentStatic.data, fundStatic.data])

  // Y-axis bounds for sector chart. When excludeOutliers is on, clamp to ±2σ
  // of all bar values so a single extreme sector doesn't compress the rest.
  const sectorYDomain = useMemo<[number | string, number | string]>(() => {
    if (!excludeOutliers) return ['auto', 'auto']
    const vals: number[] = []
    sectorChartData.forEach(row => {
      ;(data?.periods ?? []).forEach((_, pi) => {
        const v = row[`p${pi}`] as number
        if (typeof v === 'number' && isFinite(v)) vals.push(v)
      })
    })
    if (vals.length < 3) return ['auto', 'auto']
    const mean = vals.reduce((s, x) => s + x, 0) / vals.length
    const variance = vals.reduce((s, x) => s + (x - mean) ** 2, 0) / vals.length
    const sd = Math.sqrt(variance)
    const lo = mean - 2 * sd
    const hi = mean + 2 * sd
    return [Math.min(0, lo), Math.max(0, hi)]
  }, [excludeOutliers, sectorChartData, data?.periods])

  const sectorOutliersClipped = useMemo(() => {
    if (!excludeOutliers) return 0
    const [lo, hi] = sectorYDomain
    if (typeof lo !== 'number' || typeof hi !== 'number') return 0
    let n = 0
    sectorChartData.forEach(row => {
      ;(data?.periods ?? []).forEach((_, pi) => {
        const v = row[`p${pi}`] as number
        if (typeof v === 'number' && (v < lo || v > hi)) n += 1
      })
    })
    return n
  }, [excludeOutliers, sectorYDomain, sectorChartData, data?.periods])

  function onExcel() {
    if (!data) return
    const h = ['Rank', 'Sector', 'Total Net ($MM)', ...periods.map(p => `${p.label} Net ($MM)`)]
    const csv = [h, ...ranked.map((s, i) => [
      i + 1,
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
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', backgroundColor: 'var(--bg)', overflow: 'hidden' }}>
      <style>{`
        @media print {
          .sr-controls { display:none!important }
          .sr-wrap { height:auto!important; max-height:none!important; overflow:visible!important }
          .sr-wrap * { max-height:none!important }
        }
      `}</style>

      {/* Controls */}
      <div className="sr-controls" style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 16, padding: '12px 16px', backgroundColor: 'var(--panel)', borderBottom: '1px solid var(--line)', flexShrink: 0 }}>
        <FundViewToggle value={fundView} onChange={setFundView} />
        <ActiveOnlyToggle value={activeOnly} onChange={setActiveOnly} label="Active Only" />
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 10 }}>
          <FreshnessBadge tableName="investor_flows" label="flows" />
          <ExportBar onExcel={onExcel} onPrint={() => window.print()} disabled={!data} />
        </div>
      </div>

      {/* Content */}
      <div className="sr-wrap" style={{ flex: 1, overflowY: 'auto', overflowX: 'auto' }}>
        <div style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 16 }}>

          {/* B. KPI block (compact, 2 tiers) + Net Flows chart (2fr / 3fr) — STATIC */}
          <div style={{ display: 'grid', gridTemplateColumns: '2fr 3fr', gap: 16, alignItems: 'stretch' }}>
            <KpiRow summary={summary.data} loading={summary.loading} />
            <NetFlowsCard data={netFlowsChartData} loading={parentStatic.loading || fundStatic.loading} />
          </div>

          {/* C. Sector rotation chart — toggle-driven */}
          <div style={{ backgroundColor: 'var(--card)', border: '1px solid var(--line)' }}>
            <div style={{ ...PANEL_TITLE, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span>Sector Rotation — Net Flow by Period</span>
              <label style={{
                display: 'inline-flex', alignItems: 'center', gap: 6,
                fontSize: 9, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.16em',
                color: excludeOutliers ? 'var(--gold)' : 'var(--text-dim)',
                cursor: 'pointer', userSelect: 'none',
              }}>
                <input
                  type="checkbox"
                  checked={excludeOutliers}
                  onChange={e => setExcludeOutliers(e.target.checked)}
                  style={{ accentColor: 'var(--gold)', cursor: 'pointer', margin: 0 }}
                />
                Exclude outliers
                {excludeOutliers && sectorOutliersClipped > 0 && (
                  <span style={{ color: 'var(--text-mute)', fontWeight: 400, letterSpacing: '0.04em', textTransform: 'none' }}>
                    ({sectorOutliersClipped} clipped)
                  </span>
                )}
              </label>
            </div>
            <div style={{ padding: '12px 12px 4px', height: 320 }}>
              {loading && <div style={{ ...CENTER_MSG, color: 'var(--text-dim)' }}>Loading…</div>}
              {error && !loading && <div style={{ ...CENTER_MSG, color: 'var(--neg)' }}>Error: {error}</div>}
              {!loading && !error && sectorChartData.length > 0 && (
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={sectorChartData} barCategoryGap={20} barGap={0}>
                    <XAxis dataKey="label" tick={{ fontSize: 10, fill: 'var(--text-dim)', fontFamily: "'JetBrains Mono', monospace" }}
                      interval={0} angle={-25} textAnchor="end" height={70}
                      stroke="var(--line)" />
                    <YAxis tick={{ fontSize: 10, fill: 'var(--text-dim)', fontFamily: "'JetBrains Mono', monospace" }}
                      tickFormatter={(v: number) => `$${NUM_1.format(v)}B`} width={56}
                      domain={sectorYDomain} allowDataOverflow={excludeOutliers}
                      stroke="var(--line)" />
                    <Tooltip cursor={{ fill: 'rgba(255,255,255,0.04)' }} content={({ active, payload, label }) => {
                      if (!active || !payload || payload.length === 0) return null
                      const row = payload[0].payload as Record<string, number | string>
                      return (
                        <div style={{ backgroundColor: 'var(--panel)', color: 'var(--text)', padding: '8px 12px', border: '1px solid var(--line)', fontSize: 11, lineHeight: 1.6, fontFamily: "'Inter', sans-serif", boxShadow: '0 12px 40px rgba(0,0,0,0.5)' }}>
                          <div style={{ fontWeight: 600, color: 'var(--white)', marginBottom: 4 }}>{label}</div>
                          {(data?.periods ?? []).map((p, pi) => {
                            const raw = (row[`p${pi}_raw`] as number) || 0
                            return (
                              <div key={pi} style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
                                <span style={{ color: 'var(--text-dim)' }}>{p.label}</span>
                                <span style={{ color: raw >= 0 ? 'var(--pos)' : 'var(--neg)', fontFamily: "'JetBrains Mono', monospace" }}>{fmtMm(raw)}</span>
                              </div>
                            )
                          })}
                        </div>
                      )
                    }} />
                    <ReferenceLine y={0} stroke="var(--line)" />
                    {(data?.periods ?? []).map((_, pi) => (
                      <Bar key={pi} dataKey={`p${pi}`} fill={PERIOD_FILLS[pi] || '#7aadde'} isAnimationActive={false}>
                        {sectorChartData.map((d, i) => {
                          const v = (d[`p${pi}`] as number) || 0
                          return <Cell key={i} fill={v >= 0 ? (PERIOD_FILLS[pi] || '#7aadde') : 'var(--neg)'} />
                        })}
                      </Bar>
                    ))}
                  </BarChart>
                </ResponsiveContainer>
              )}
            </div>
          </div>

          {/* D + E. Sector table + movers panel */}
          <div style={{ display: 'grid', gridTemplateColumns: '3fr 2fr', gap: 16 }}>
            {/* Sector table */}
            <div style={{ backgroundColor: 'var(--card)', border: '1px solid var(--line)' }}>
              <div style={PANEL_TITLE}>Sector Ranking</div>
              <div style={{ maxHeight: 500, overflowY: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'separate', borderSpacing: 0, tableLayout: 'fixed', fontSize: 12 }}>
                  <colgroup>
                    <col style={{ width: 50 }} />
                    <col style={{ width: 170 }} />
                    {displayQuarters.map(q => <col key={q} style={{ width: 90 }} />)}
                    <col style={{ width: 110 }} />
                  </colgroup>
                  <thead>
                    {/* Year group header */}
                    <tr>
                      <th style={{ ...TH, top: 0, borderBottom: 'none' }} />
                      <th style={{ ...TH, top: 0, borderBottom: 'none' }} />
                      <th colSpan={displayQuarters.length} style={{
                        ...TH, top: 0, textAlign: 'center', borderBottom: '1px solid var(--line-soft)',
                        color: 'var(--text-dim)',
                      }}>
                        {tableYear(displayQuarters)}
                      </th>
                      <th style={{
                        ...TH_R, top: 0, borderBottom: 'none',
                        borderLeft: '2px solid var(--gold)',
                        backgroundColor: 'var(--card)',
                      }} />
                    </tr>
                    <tr>
                      <th style={{ ...TH_R, top: 26 }}>#</th>
                      <th style={{ ...TH, top: 26 }}>Sector</th>
                      {displayQuarters.map(q => (
                        <th key={q} style={{ ...TH_R, top: 26 }}>{fmtQuarterLabel(q)}</th>
                      ))}
                      <th style={{
                        ...TH_R, top: 26,
                        borderLeft: '2px solid var(--gold)',
                        backgroundColor: 'var(--card)',
                        color: 'var(--gold)',
                      }}>Total Net</th>
                    </tr>
                  </thead>
                  <tbody>
                    {ranked.map((s, i) => {
                      const isSel = s.sector === selectedSector
                      return (
                        <tr key={s.sector}
                          onClick={() => setSelectedSector(s.sector)}
                          style={{
                            backgroundColor: isSel ? 'var(--gold-soft)' : undefined,
                            borderLeft: isSel ? '2px solid var(--gold)' : '2px solid transparent',
                            cursor: 'pointer',
                            transition: 'all 0.12s',
                          }}>
                          <td style={{ ...TD_R, color: 'var(--text-dim)' }}>{i + 1}</td>
                          <td style={{ ...TD, fontWeight: 500, color: isSel ? 'var(--white)' : 'var(--text)' }}>{s.sector}</td>
                          {displayQuarters.map(q => {
                            const p = periodByDest[q]
                            if (!p) {
                              return <td key={q} style={{ ...TD_R, color: 'var(--text-mute)' }}>—</td>
                            }
                            const key = `${p.from}_${p.to}`
                            const n = s.flows[key]?.net ?? null
                            return <td key={q} style={TD_R}><SignedMm v={n} /></td>
                          })}
                          <td style={{
                            ...TD_R,
                            borderLeft: '2px solid var(--gold)',
                            backgroundColor: isSel ? 'var(--gold-soft)' : 'var(--card)',
                            fontWeight: 600,
                          }}>
                            <SignedMm v={s.total_net} />
                          </td>
                        </tr>
                      )
                    })}
                    {ranked.length === 0 && !loading && (
                      <tr><td colSpan={3 + displayQuarters.length} style={{ ...TD, textAlign: 'center', color: 'var(--text-dim)', padding: 30 }}>No data.</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Movers panel */}
            <div style={{ backgroundColor: 'var(--card)', border: '1px solid var(--line)' }}>
              <div style={{ ...PANEL_TITLE, display: 'flex', justifyContent: 'space-between' }}>
                <span>Movers — {selectedSector ?? '—'}</span>
                <span style={{ color: 'var(--text-mute)' }}>{latestPeriod?.label ?? ''}</span>
              </div>
              {!selectedSector && (
                <div style={{ ...CENTER_MSG, color: 'var(--text-dim)' }}>Select a sector</div>
              )}
              {selectedSector && movers.loading && (
                <div style={{ ...CENTER_MSG, color: 'var(--text-dim)' }}>Loading movers…</div>
              )}
              {selectedSector && !movers.loading && movers.data && (
                <>
                  <div style={{
                    padding: '8px 14px', fontSize: 11, color: 'var(--text-dim)',
                    backgroundColor: 'var(--panel)', borderBottom: '1px solid var(--line-soft)',
                    display: 'flex', gap: 16, fontFamily: "'JetBrains Mono', monospace",
                  }}>
                    <span>Net <b style={{ color: movers.data.summary.net >= 0 ? 'var(--pos)' : 'var(--neg)' }}>{fmtMm(movers.data.summary.net)}</b></span>
                    <span>Mgrs <b style={{ color: 'var(--text)' }}>{NUM_0.format(movers.data.summary.buyers)}</b></span>
                  </div>
                  <MoverTable title="Top Buyers" rows={movers.data.top_buyers} accent="var(--pos)" />
                  <MoverTable title="Top Sellers" rows={movers.data.top_sellers} accent="var(--neg)" />
                  <div style={{
                    padding: '8px 14px', fontSize: 10, fontStyle: 'italic',
                    color: 'var(--text-mute)', borderTop: '1px solid var(--line-soft)',
                    fontFamily: "'Inter', sans-serif",
                  }}>
                    Flows reflect changes in position size net of share price appreciation.
                  </div>
                </>
              )}
            </div>
          </div>

        </div>
      </div>
    </div>
  )
}

// ── KPI Row ────────────────────────────────────────────────────────────────

function KpiTile({ kicker, value }: { kicker: string; value: string }) {
  return (
    <div style={{
      backgroundColor: 'var(--card)', border: '1px solid var(--line)',
      padding: 10, display: 'flex', flexDirection: 'column', justifyContent: 'center',
    }}>
      <div style={{ ...KICKER, fontSize: 9 }}>{kicker}</div>
      <div style={{
        fontSize: 18, fontFamily: "'JetBrains Mono', monospace",
        color: 'var(--white)', letterSpacing: '-0.01em', fontWeight: 400,
        fontVariantNumeric: 'tabular-nums', marginTop: 4,
      }}>{value}</div>
    </div>
  )
}

function KpiMini({ kicker, value }: { kicker: string; value: string }) {
  return (
    <div style={{
      backgroundColor: 'var(--card)', border: '1px solid var(--line)',
      padding: '6px 10px',
      display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8,
    }}>
      <div style={{ ...KICKER, fontSize: 9 }}>{kicker}</div>
      <div style={{
        fontSize: 14, fontFamily: "'JetBrains Mono', monospace",
        color: 'var(--white)', letterSpacing: '-0.01em', fontWeight: 400,
        fontVariantNumeric: 'tabular-nums',
      }}>{value}</div>
    </div>
  )
}

function KpiRow({ summary, loading }: { summary: SectorSummaryResponse | null; loading: boolean }) {
  const v = (n: number | null | undefined, fmt: (x: number) => string) =>
    loading || summary == null ? '…' : fmt(n ?? 0)
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 8 }}>
        <KpiTile kicker="Total AUM" value={v(summary?.total_aum, fmtAum)} />
        <KpiTile kicker="Total Holders" value={v(summary?.total_holders, x => NUM_0.format(x))} />
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}>
        <KpiMini kicker="Active" value={v(summary?.pct_active, fmtPct)} />
        <KpiMini kicker="Passive" value={v(summary?.pct_passive, fmtPct)} />
        <KpiMini kicker="Hedge Fund" value={v(summary?.pct_hedge_fund, fmtPct)} />
      </div>
    </div>
  )
}

// ── Net Flows Card ─────────────────────────────────────────────────────────

interface NetFlowsRow {
  period: string
  institutional: number
  institutionalRaw: number
  fund: number
  fundRaw: number
}

function NetFlowsCard({ data, loading }: { data: NetFlowsRow[]; loading: boolean }) {
  return (
    <div style={{ backgroundColor: 'var(--card)', border: '1px solid var(--line)', display: 'flex', flexDirection: 'column' }}>
      <div style={PANEL_TITLE}>Net Flows</div>
      <div style={{ padding: '8px 12px 8px', flex: 1, minHeight: 200 }}>
        {loading && <div style={{ ...CENTER_MSG, color: 'var(--text-dim)', padding: 20 }}>Loading…</div>}
        {!loading && (
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} barCategoryGap={12} barGap={2}>
              <XAxis dataKey="period" tick={{ fontSize: 9, fill: 'var(--text-dim)', fontFamily: "'JetBrains Mono', monospace" }} stroke="var(--line)" />
              <YAxis tick={{ fontSize: 9, fill: 'var(--text-dim)', fontFamily: "'JetBrains Mono', monospace" }}
                tickFormatter={(v: number) => `$${NUM_0.format(v)}B`} width={42} stroke="var(--line)" />
              <Tooltip cursor={{ fill: 'rgba(255,255,255,0.04)' }} content={({ active, payload, label }) => {
                if (!active || !payload || payload.length === 0) return null
                const row = payload[0].payload as NetFlowsRow
                return (
                  <div style={{ backgroundColor: 'var(--panel)', color: 'var(--text)', padding: '8px 12px', border: '1px solid var(--line)', fontSize: 11, lineHeight: 1.6, fontFamily: "'Inter', sans-serif", boxShadow: '0 12px 40px rgba(0,0,0,0.5)' }}>
                    <div style={{ fontWeight: 600, color: 'var(--white)', marginBottom: 4 }}>{label}</div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
                      <span style={{ color: 'var(--text-dim)' }}>Institutional</span>
                      <span style={{ color: row.institutionalRaw >= 0 ? 'var(--pos)' : 'var(--neg)', fontFamily: "'JetBrains Mono', monospace" }}>{fmtMm(row.institutionalRaw)}</span>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
                      <span style={{ color: 'var(--text-dim)' }}>Fund</span>
                      <span style={{ color: row.fundRaw >= 0 ? 'var(--pos)' : 'var(--neg)', fontFamily: "'JetBrains Mono', monospace" }}>{fmtMm(row.fundRaw)}</span>
                    </div>
                  </div>
                )
              }} />
              <Legend wrapperStyle={{ fontSize: 9, fontFamily: "'Hanken Grotesk', sans-serif", textTransform: 'uppercase', letterSpacing: '0.16em', color: 'var(--text-dim)' }} iconSize={8} verticalAlign="top" align="right" />
              <ReferenceLine y={0} stroke="var(--line)" />
              <Bar dataKey="institutional" name="Institutional" isAnimationActive={false}>
                {data.map((d, i) => <Cell key={i} fill={d.institutional >= 0 ? 'var(--pos)' : 'var(--neg)'} />)}
              </Bar>
              <Bar dataKey="fund" name="Fund" isAnimationActive={false}>
                {data.map((d, i) => <Cell key={i} fill={d.fund >= 0 ? 'var(--pos)' : 'var(--neg)'} fillOpacity={0.55} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  )
}

// ── Mover table ────────────────────────────────────────────────────────────

function MoverTable({ title, rows, accent }: {
  title: string
  rows: Array<{ institution: string; net_flow: number; buying: number; selling: number; positions_changed: number }>
  accent: string
}) {
  return (
    <div>
      <div style={{
        padding: '6px 14px', fontSize: 9, fontWeight: 700,
        textTransform: 'uppercase', letterSpacing: '0.16em',
        fontFamily: "'Hanken Grotesk', sans-serif",
        color: accent, backgroundColor: 'var(--panel)',
        borderBottom: '1px solid var(--line-soft)',
      }}>{title}</div>
      <table style={{ width: '100%', borderCollapse: 'separate', borderSpacing: 0, fontSize: 11, tableLayout: 'fixed' }}>
        <colgroup>
          <col style={{ width: 26 }} />
          <col />
          <col style={{ width: 90 }} />
        </colgroup>
        <tbody>
          {rows.map((r, i) => (
            <tr key={r.institution}>
              <td style={{ ...TD, fontSize: 11, padding: '4px 8px', textAlign: 'right', color: 'var(--text-mute)' }}>{i + 1}</td>
              <td style={{ ...TD, fontSize: 11, padding: '4px 8px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }} title={r.institution}>{r.institution}</td>
              <td style={{ ...TD_R, fontSize: 11, padding: '4px 8px' }}><SignedDollar v={r.net_flow} /></td>
            </tr>
          ))}
          {rows.length === 0 && <tr><td colSpan={3} style={{ ...TD, textAlign: 'center', color: 'var(--text-mute)', padding: 10 }}>None</td></tr>}
        </tbody>
      </table>
    </div>
  )
}

// ── Helpers ────────────────────────────────────────────────────────────────

function enc(s: string) { return encodeURIComponent(s) }

function tableYear(qs: string[]): string {
  if (!qs.length) return ''
  const m = /^(\d{4})Q\d$/.exec(qs[0])
  return m ? m[1] : ''
}

function downloadCsv(csv: string, filename: string) {
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
  const u = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = u; a.download = filename
  document.body.appendChild(a); a.click()
  document.body.removeChild(a); URL.revokeObjectURL(u)
}
