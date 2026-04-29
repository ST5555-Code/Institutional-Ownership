import { useEffect, useMemo, useRef, useState } from 'react'
import { useAppStore } from '../../store/useAppStore'
import { useFetch } from '../../hooks/useFetch'
import type {
  SectorFlowsResponse,
  SectorFlowMoversResponse,
  SectorFlowMoverDetailResponse,
  SectorSummaryResponse,
} from '../../types/api'
import {
  FundViewToggle,
  ActiveOnlyToggle,
  ExportBar,
  FreshnessBadge,
  getTypeStyle,
} from '../common'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, Cell, LabelList,
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


function fmtQuarterLabel(q: string): string {
  // "2025Q2" → "Q2 '25"
  const m = /^(\d{4})Q(\d)$/.exec(q)
  if (!m) return q
  return `Q${m[2]} '${m[1].slice(2)}`
}

// Y-axis tick formatter — returns "$X.YB" or "($X.YB)" for negatives.
function fmtBillionTick(v: number): string {
  if (v == null || !isFinite(v)) return ''
  if (v === 0) return '$0B'
  const abs = Math.abs(v)
  const text = abs >= 1 ? `$${NUM_1.format(abs)}B` : `$${NUM_0.format(abs * 1000)}M`
  return v < 0 ? `(${text})` : text
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
  const [moverDetail, setMoverDetail] = useState<{
    institution: string
    anchor: { x: number; y: number }
  } | null>(null)

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
      setMoverDetail(null)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, level, ao])

  // Close any open mover-detail popup when level/active toggle changes.
  useEffect(() => { setMoverDetail(null) }, [level, ao, selectedSector])

  // Movers fetch — latest period of selected sector
  const latestPeriod = periods[periods.length - 1] ?? null
  const moversUrl = selectedSector && latestPeriod
    ? `/api/v1/sector_flow_movers?from=${enc(latestPeriod.from)}&to=${enc(latestPeriod.to)}&sector=${enc(selectedSector)}&active_only=${ao}&level=${level}&rollup_type=${rollupType}`
    : null
  const movers = useFetch<SectorFlowMoversResponse>(moversUrl)

  // Display quarters for table — last 4 destination quarters from periods.
  // If fewer than 4 periods exist, pad to 4 with placeholders before the
  // earliest one. Always 4 columns regardless of level.
  const displayQuarters = useMemo(() => {
    if (!periods.length) return [] as string[]
    const dests = periods.map(p => p.to)
    const tail = dests.slice(-4)
    if (tail.length === 4) return tail
    const placeholders: string[] = []
    const first = tail[0]
    const m = /^(\d{4})Q(\d)$/.exec(first || '')
    if (m) {
      let y = parseInt(m[1], 10)
      let q = parseInt(m[2], 10)
      const need = 4 - tail.length
      for (let i = 0; i < need; i++) {
        q -= 1
        if (q < 1) { q = 4; y -= 1 }
        placeholders.unshift(`${y}Q${q}`)
      }
    }
    return [...placeholders, ...tail]
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

  // Broken/compressed Y-axis. If any bar exceeds 3× the median absolute
  // value, cap the domain at 2× median so the rest of the bars remain
  // readable. Outlier bars are clipped (allowDataOverflow) and labeled
  // with their true value above/below the cap.
  const sectorAxis = useMemo(() => computeBrokenAxis(
    sectorChartData.flatMap(row =>
      (data?.periods ?? []).map((_, pi) => row[`p${pi}`] as number)
    )
  ), [sectorChartData, data?.periods])

  const netFlowsAxis = useMemo(() => computeBrokenAxis(
    netFlowsChartData.flatMap(d => [d.institutional, d.fund])
  ), [netFlowsChartData])

  // Mover detail fetch — drives the click-through drill-down popup.
  const moverDetailUrl = moverDetail && selectedSector && latestPeriod
    ? `/api/v1/sector_flow_mover_detail?from=${enc(latestPeriod.from)}&to=${enc(latestPeriod.to)}&sector=${enc(selectedSector)}&institution=${enc(moverDetail.institution)}&active_only=${ao}&level=${level}&rollup_type=${rollupType}`
    : null
  const moverDetailFetch = useFetch<SectorFlowMoverDetailResponse>(moverDetailUrl)

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
            <NetFlowsCard data={netFlowsChartData} loading={parentStatic.loading || fundStatic.loading} axis={netFlowsAxis} />
          </div>

          {/* C. Sector rotation chart — broken-axis when outliers present */}
          <div style={{ backgroundColor: 'var(--card)', border: '1px solid var(--line)' }}>
            <div style={{ ...PANEL_TITLE, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span>Sector Rotation — Net Flow by Period</span>
              {sectorAxis.broken && (
                <span style={{
                  fontSize: 9, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.16em',
                  color: 'var(--gold)', fontFamily: "'Hanken Grotesk', sans-serif",
                }}>
                  axis compressed · ⌇ marks outlier
                </span>
              )}
            </div>
            <div style={{ padding: '12px 12px 4px', height: 320 }}>
              {loading && <div style={{ ...CENTER_MSG, color: 'var(--text-dim)' }}>Loading…</div>}
              {error && !loading && <div style={{ ...CENTER_MSG, color: 'var(--neg)' }}>Error: {error}</div>}
              {!loading && !error && sectorChartData.length > 0 && (
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={sectorChartData} barCategoryGap={20} barGap={0}>
                    <XAxis dataKey="sector"
                      tick={{ fontSize: 10, fill: 'var(--text-dim)', fontFamily: "'JetBrains Mono', monospace" }}
                      interval={0} angle={-25} textAnchor="end" height={70}
                      tickFormatter={truncateSector}
                      stroke="var(--line)" />
                    <YAxis tick={{ fontSize: 10, fill: 'var(--text-dim)', fontFamily: "'JetBrains Mono', monospace" }}
                      tickFormatter={fmtBillionTick} width={64}
                      domain={sectorAxis.domain} allowDataOverflow={sectorAxis.broken}
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
                        {sectorAxis.broken && (
                          <LabelList dataKey={`p${pi}`} content={renderClipLabel(sectorAxis.cap)} />
                        )}
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
                <span>
                  {selectedSector ?? '—'}
                  {selectedSector && latestPeriod && ` — ${fmtQuarterLabel(latestPeriod.to)}`}
                </span>
                <span style={{ color: 'var(--text-mute)', textTransform: 'none', letterSpacing: '0.04em' }}>
                  {fundView === 'fund' ? 'fund' : 'parent'}
                </span>
              </div>
              {!selectedSector && (
                <div style={{ ...CENTER_MSG, color: 'var(--text-dim)' }}>Select a sector</div>
              )}
              {selectedSector && movers.loading && (
                <div style={{ ...CENTER_MSG, color: 'var(--text-dim)' }}>Loading movers…</div>
              )}
              {selectedSector && !movers.loading && movers.error && (
                <div style={{ ...CENTER_MSG, color: 'var(--neg)' }}>Error: {movers.error}</div>
              )}
              {selectedSector && !movers.loading && !movers.error && movers.data && (
                movers.data.top_buyers.length === 0 && movers.data.top_sellers.length === 0 ? (
                  <div style={{ ...CENTER_MSG, color: 'var(--text-dim)' }}>
                    {fundView === 'fund' ? 'No fund-level mover data' : 'No mover data'}
                  </div>
                ) : (
                  <>
                    <div style={{
                      padding: '8px 14px', fontSize: 11, color: 'var(--text-dim)',
                      backgroundColor: 'var(--panel)', borderBottom: '1px solid var(--line-soft)',
                      display: 'flex', gap: 16, fontFamily: "'JetBrains Mono', monospace",
                    }}>
                      <span>Net <b style={{ color: movers.data.summary.net >= 0 ? 'var(--pos)' : 'var(--neg)' }}>{fmtMm(movers.data.summary.net)}</b></span>
                      <span>Mgrs <b style={{ color: 'var(--text)' }}>{NUM_0.format(movers.data.summary.buyers)}</b></span>
                    </div>
                    <MoverTable title="Top Buyers" rows={movers.data.top_buyers} accent="var(--pos)"
                      onClickInstitution={(institution, e) => setMoverDetail({
                        institution,
                        anchor: { x: e.clientX, y: e.clientY },
                      })} />
                    <MoverTable title="Top Sellers" rows={movers.data.top_sellers} accent="var(--neg)"
                      onClickInstitution={(institution, e) => setMoverDetail({
                        institution,
                        anchor: { x: e.clientX, y: e.clientY },
                      })} />
                    <div style={{
                      padding: '8px 14px', fontSize: 10, fontStyle: 'italic',
                      color: 'var(--text-mute)', borderTop: '1px solid var(--line-soft)',
                      fontFamily: "'Inter', sans-serif",
                    }}>
                      Flows reflect changes in position size net of share price appreciation. Click an institution for ticker-level detail.
                    </div>
                  </>
                )
              )}
            </div>
          </div>

          {/* Mover detail popup */}
          {moverDetail && (
            <MoverDetailPopup
              institution={moverDetail.institution}
              anchor={moverDetail.anchor}
              sector={selectedSector || ''}
              periodLabel={latestPeriod ? fmtQuarterLabel(latestPeriod.to) : ''}
              data={moverDetailFetch.data}
              loading={moverDetailFetch.loading}
              error={moverDetailFetch.error}
              onClose={() => setMoverDetail(null)}
            />
          )}

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

function KpiMini({ label, color, value }: { label: string; color: string; value: string }) {
  return (
    <div style={{
      backgroundColor: 'var(--card)', border: '1px solid var(--line)',
      padding: '6px 10px',
      display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8,
    }}>
      <div style={{
        fontSize: 9, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.16em',
        fontFamily: "'Hanken Grotesk', sans-serif", color,
        whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
      }}>{label}</div>
      <div style={{
        fontSize: 13, fontFamily: "'JetBrains Mono', monospace",
        color: 'var(--white)', letterSpacing: '-0.01em', fontWeight: 400,
        fontVariantNumeric: 'tabular-nums',
      }}>{value}</div>
    </div>
  )
}

function KpiRow({ summary, loading }: { summary: SectorSummaryResponse | null; loading: boolean }) {
  const v = (n: number | null | undefined, fmt: (x: number) => string) =>
    loading || summary == null ? '…' : fmt(n ?? 0)
  const breakdown = summary?.type_breakdown ?? []
  const sorted = [...breakdown].sort((a, b) => b.pct_aum - a.pct_aum)
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 8 }}>
        <KpiTile kicker="Total AUM" value={v(summary?.total_aum, fmtAum)} />
        <KpiTile kicker="Total Holders" value={v(summary?.total_holders, x => NUM_0.format(x))} />
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(120px, 1fr))', gap: 6 }}>
        {loading && [0,1,2].map(i => <KpiMini key={i} label="…" color="var(--text-dim)" value="…" />)}
        {!loading && sorted.map(t => {
          const style = getTypeStyle(t.type)
          return (
            <KpiMini key={t.type} label={style.label || t.type}
              color={style.color}
              value={`${NUM_1.format(t.pct_aum)}%`} />
          )
        })}
        {!loading && sorted.length === 0 && (
          <div style={{ ...CENTER_MSG, gridColumn: '1 / -1', padding: 8 }}>—</div>
        )}
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

function NetFlowsCard({ data, loading, axis }: { data: NetFlowsRow[]; loading: boolean; axis: ReturnType<typeof computeBrokenAxis> }) {
  return (
    <div style={{ backgroundColor: 'var(--card)', border: '1px solid var(--line)', display: 'flex', flexDirection: 'column' }}>
      <div style={{ ...PANEL_TITLE, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span>Net Flows</span>
        {axis.broken && (
          <span style={{
            fontSize: 9, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.16em',
            color: 'var(--gold)', fontFamily: "'Hanken Grotesk', sans-serif",
          }}>axis compressed</span>
        )}
      </div>
      <div style={{ padding: '8px 12px 8px', flex: 1, minHeight: 200 }}>
        {loading && <div style={{ ...CENTER_MSG, color: 'var(--text-dim)', padding: 20 }}>Loading…</div>}
        {!loading && (
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} barCategoryGap={12} barGap={2}>
              <XAxis dataKey="period" tick={{ fontSize: 9, fill: 'var(--text-dim)', fontFamily: "'JetBrains Mono', monospace" }} stroke="var(--line)" />
              <YAxis tick={{ fontSize: 9, fill: 'var(--text-dim)', fontFamily: "'JetBrains Mono', monospace" }}
                tickFormatter={fmtBillionTick} width={56}
                domain={axis.domain} allowDataOverflow={axis.broken}
                stroke="var(--line)" />
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
                {axis.broken && <LabelList dataKey="institutional" content={renderClipLabel(axis.cap)} />}
              </Bar>
              <Bar dataKey="fund" name="Fund" isAnimationActive={false}>
                {data.map((d, i) => <Cell key={i} fill={d.fund >= 0 ? 'var(--pos)' : 'var(--neg)'} fillOpacity={0.55} />)}
                {axis.broken && <LabelList dataKey="fund" content={renderClipLabel(axis.cap)} />}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  )
}

// ── Mover table ────────────────────────────────────────────────────────────

function MoverTable({ title, rows, accent, onClickInstitution }: {
  title: string
  rows: Array<{ institution: string; net_flow: number; buying: number; selling: number; positions_changed: number }>
  accent: string
  onClickInstitution?: (institution: string, e: React.MouseEvent) => void
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
            <tr key={r.institution}
              onClick={onClickInstitution ? (e) => onClickInstitution(r.institution, e) : undefined}
              style={{ cursor: onClickInstitution ? 'pointer' : undefined, transition: 'all 0.12s' }}
              onMouseOver={onClickInstitution ? (e) => { (e.currentTarget as HTMLElement).style.backgroundColor = 'var(--panel-hi)' } : undefined}
              onMouseOut={onClickInstitution ? (e) => { (e.currentTarget as HTMLElement).style.backgroundColor = '' } : undefined}>
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

// ── Mover detail popup ────────────────────────────────────────────────────

function MoverDetailPopup({
  institution, anchor, sector, periodLabel, data, loading, error, onClose,
}: {
  institution: string
  anchor: { x: number; y: number }
  sector: string
  periodLabel: string
  data: SectorFlowMoverDetailResponse | null
  loading: boolean
  error: string | null
  onClose: () => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose()
    }
    function handleEsc(e: KeyboardEvent) { if (e.key === 'Escape') onClose() }
    // Defer to next tick so the click that opened the popup doesn't close it
    const t = setTimeout(() => document.addEventListener('mousedown', handleClick), 0)
    document.addEventListener('keydown', handleEsc)
    return () => {
      clearTimeout(t)
      document.removeEventListener('mousedown', handleClick)
      document.removeEventListener('keydown', handleEsc)
    }
  }, [onClose])

  // Anchor near the click but keep within viewport.
  const W = 380
  const H = 280
  const left = Math.min(Math.max(8, anchor.x - W / 2), window.innerWidth - W - 8)
  const top = Math.min(anchor.y + 12, window.innerHeight - H - 8)

  return (
    <div ref={ref} style={{
      position: 'fixed', left, top, width: W, zIndex: 50,
      backgroundColor: 'var(--panel)', color: 'var(--text)',
      border: '1px solid var(--line)',
      boxShadow: '0 12px 40px rgba(0,0,0,0.5)',
      fontFamily: "'Inter', sans-serif",
    }}>
      <div style={{
        backgroundColor: 'var(--header)', padding: '8px 12px',
        borderBottom: '1px solid var(--line)',
        display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8,
      }}>
        <div style={{ minWidth: 0 }}>
          <div style={{
            fontSize: 9, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.16em',
            fontFamily: "'Hanken Grotesk', sans-serif", color: 'var(--text-dim)',
          }}>Top ticker moves</div>
          <div style={{
            fontSize: 12, fontWeight: 600, color: 'var(--white)',
            whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
          }} title={institution}>{institution}</div>
          <div style={{ fontSize: 10, color: 'var(--text-mute)', marginTop: 2 }}>
            {sector}{periodLabel ? ` · ${periodLabel}` : ''}
          </div>
        </div>
        <button onClick={onClose} type="button" style={{
          backgroundColor: 'transparent', border: 'none', color: 'var(--text-dim)',
          cursor: 'pointer', fontSize: 16, padding: 0, lineHeight: 1,
        }}>×</button>
      </div>
      {loading && <div style={{ padding: 24, textAlign: 'center', color: 'var(--text-dim)', fontSize: 11 }}>Loading…</div>}
      {error && <div style={{ padding: 16, color: 'var(--neg)', fontSize: 11 }}>Error: {error}</div>}
      {!loading && !error && data && data.rows.length === 0 && (
        <div style={{ padding: 24, textAlign: 'center', color: 'var(--text-dim)', fontSize: 11 }}>No detail rows.</div>
      )}
      {!loading && !error && data && data.rows.length > 0 && (
        <table style={{ width: '100%', borderCollapse: 'separate', borderSpacing: 0, fontSize: 11, tableLayout: 'fixed' }}>
          <colgroup>
            <col style={{ width: 64 }} />
            <col />
            <col style={{ width: 90 }} />
          </colgroup>
          <thead>
            <tr>
              <th style={{ ...TH }}>Ticker</th>
              <th style={{ ...TH }}>Company</th>
              <th style={{ ...TH_R }}>Net Flow</th>
            </tr>
          </thead>
          <tbody>
            {data.rows.map(r => (
              <tr key={r.ticker}>
                <td style={{ ...TD, padding: '6px 10px', fontFamily: "'JetBrains Mono', monospace", color: 'var(--gold)', fontSize: 11 }}>{r.ticker}</td>
                <td style={{ ...TD, padding: '6px 10px', fontSize: 11, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }} title={r.company_name || ''}>
                  {r.company_name || '—'}
                </td>
                <td style={{ ...TD_R, padding: '6px 10px', fontSize: 11 }}><SignedDollar v={r.net_flow} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

// ── Helpers ────────────────────────────────────────────────────────────────

function enc(s: string) { return encodeURIComponent(s) }

// Truncate sector names to keep X-axis readable.
function truncateSector(s: string): string {
  if (!s) return ''
  if (s.length <= 16) return s
  return s.slice(0, 14) + '…'
}

// Detect outlier (>3× median absolute) and return a capped Y-axis domain
// at ±2× median. When an outlier exists, callers should set
// allowDataOverflow on the YAxis and render a clip-label above/below
// the bars whose true value exceeds the cap.
function computeBrokenAxis(values: number[]): {
  domain: [number | string, number | string]
  cap: number
  broken: boolean
} {
  const finite = values.filter(v => typeof v === 'number' && isFinite(v) && v !== 0)
  if (finite.length < 4) return { domain: ['auto', 'auto'], cap: Infinity, broken: false }
  const abs = finite.map(Math.abs).sort((a, b) => a - b)
  const median = abs[Math.floor(abs.length / 2)] || 0
  const max = abs[abs.length - 1]
  if (median <= 0 || max <= 3 * median) return { domain: ['auto', 'auto'], cap: Infinity, broken: false }
  const cap = 2 * median
  const hasNeg = finite.some(v => v < 0)
  return { domain: [hasNeg ? -cap : 0, cap], cap, broken: true }
}

// Recharts LabelList content factory — when |value| > cap, show the true
// value above (positive) or below (negative) the clipped bar with a
// gold compression marker.
function renderClipLabel(cap: number) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return function ClipLabel(props: any) {
    const x = (props?.x as number) ?? 0
    const y = (props?.y as number) ?? 0
    const width = (props?.width as number) ?? 0
    const height = (props?.height as number) ?? 0
    const value = (props?.value as number) ?? 0
    if (!isFinite(value) || Math.abs(value) <= cap) return null
    const isNeg = value < 0
    const labelY = isNeg ? y + height + 11 : y - 5
    const text = fmtBillionTick(value)
    return (
      <g>
        <text x={x + width / 2} y={labelY}
          fontSize={9}
          fill="var(--gold)"
          textAnchor="middle"
          fontFamily="'JetBrains Mono', monospace">
          {text} ⌇
        </text>
      </g>
    )
  }
}

function tableYear(qs: string[]): string {
  if (!qs.length) return ''
  const years = new Set<string>()
  qs.forEach(q => {
    const m = /^(\d{4})Q\d$/.exec(q)
    if (m) years.add(m[1])
  })
  const sorted = [...years].sort()
  if (sorted.length === 0) return ''
  if (sorted.length === 1) return sorted[0]
  return `${sorted[0]}–${sorted[sorted.length - 1]}`
}

function downloadCsv(csv: string, filename: string) {
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
  const u = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = u; a.download = filename
  document.body.appendChild(a); a.click()
  document.body.removeChild(a); URL.revokeObjectURL(u)
}
