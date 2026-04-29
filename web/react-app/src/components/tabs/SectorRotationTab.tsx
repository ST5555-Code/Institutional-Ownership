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
  BarChart, Bar, XAxis, YAxis, Tooltip, LabelList,
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

// "$8.2B" / "($12.3B)" / "—" — for heatmap cells.
function fmtBillionsCell(v: number | null | undefined): string {
  if (v == null || !isFinite(v) || v === 0) return '—'
  const b = v / 1e9
  const abs = Math.abs(b)
  const s = abs >= 10 ? NUM_1.format(abs) : abs.toFixed(1)
  return v < 0 ? `($${s}B)` : `$${s}B`
}

// "$1B" / "($2B)" — integer billions for net-flows axis ticks and value labels.
function fmtBillionsInt(v: number | null | undefined): string {
  if (v == null || !isFinite(v)) return ''
  if (v === 0) return '$0B'
  const b = Math.round(v / 1e9)
  if (b === 0) {
    // sub-1B values — round to nearest 100M for readability
    const m = Math.round(v / 1e8) * 100
    if (m === 0) return '$0B'
    const text = `$${Math.abs(m / 1000).toFixed(1)}B`
    return v < 0 ? `(${text})` : text
  }
  const text = `$${Math.abs(b)}B`
  return v < 0 ? `(${text})` : text
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
  if (v < 0) return <span style={{ color: 'var(--neg)' }}>(${NUM_0.format(Math.abs(mm))}M)</span>
  return <span style={{ color: 'var(--pos)' }}>$+{NUM_0.format(mm)}M</span>
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
const TH_C: React.CSSProperties = { ...TH, textAlign: 'center' }
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
const FOOTNOTE: React.CSSProperties = {
  fontSize: 10, fontStyle: 'italic',
  color: 'var(--text-mute)',
  fontFamily: "'Inter', sans-serif",
  padding: '8px 14px',
}

// ── Component ──────────────────────────────────────────────────────────────

const COLOR_INST = '#7aadde'
const COLOR_FUND_HEX = '#c5a254'

export function SectorRotationTab() {
  const { rollupType } = useAppStore()

  const [fundView, setFundView] = useState<'hierarchy' | 'fund'>('hierarchy')
  const [activeOnly, setActiveOnly] = useState(false)
  const [selectedSector, setSelectedSector] = useState<string | null>(null)
  // Period selected in heatmap. null → use latest period.
  const [selectedPeriodTo, setSelectedPeriodTo] = useState<string | null>(null)
  const [moverDetail, setMoverDetail] = useState<{
    institution: string
    anchor: { x: number; y: number }
  } | null>(null)
  const [cellTooltip, setCellTooltip] = useState<{
    x: number; y: number
    sector: string; periodLabel: string
    inflow: number | null; outflow: number | null; net: number | null
  } | null>(null)

  const level = fundView === 'fund' ? 'fund' : 'parent'
  const ao = activeOnly ? '1' : '0'

  // Static fetches (KPI row + Net Flows chart) — never refetch on toggle.
  const summary = useFetch<SectorSummaryResponse>('/api/v1/sector_summary')
  const parentStatic = useFetch<SectorFlowsResponse>('/api/v1/sector_flows?level=parent&active_only=0')
  const fundStatic = useFetch<SectorFlowsResponse>('/api/v1/sector_flows?level=fund&active_only=0')

  // Toggleable fetch (heatmap + drives movers).
  const { data, loading, error } = useFetch<SectorFlowsResponse>(
    `/api/v1/sector_flows?active_only=${ao}&level=${level}`,
  )

  const periods = data?.periods ?? []

  // Sectors ranked 1..N by sum of net flow across all periods (desc)
  const ranked = useMemo(() => {
    if (!data) return []
    return [...data.sectors].sort((a, b) => (b.total_net || 0) - (a.total_net || 0))
  }, [data])

  // Auto-select rank-1 sector on data load and on toggle change.
  useEffect(() => {
    if (!data || ranked.length === 0) return
    const top = ranked[0].sector
    if (!ranked.some(s => s.sector === selectedSector)) {
      setSelectedSector(top)
      setSelectedPeriodTo(null)
      setMoverDetail(null)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, level, ao])

  // Reset transient ui state when toggle changes.
  useEffect(() => {
    setMoverDetail(null)
    setCellTooltip(null)
    setSelectedPeriodTo(null)
  }, [level, ao])
  useEffect(() => { setMoverDetail(null) }, [selectedSector])

  // Display quarters — the 4 most recent destination quarters from periods.
  // If fewer than 4 exist, pad with placeholders before the earliest one.
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

  // Mover period — explicit cell selection, else latest available period.
  const moverPeriod = useMemo(() => {
    if (selectedPeriodTo && periodByDest[selectedPeriodTo]) {
      return periodByDest[selectedPeriodTo]
    }
    return periods[periods.length - 1] ?? null
  }, [selectedPeriodTo, periodByDest, periods])

  // Movers fetch — selected sector + period.
  const moversUrl = selectedSector && moverPeriod
    ? `/api/v1/sector_flow_movers?from=${enc(moverPeriod.from)}&to=${enc(moverPeriod.to)}&sector=${enc(selectedSector)}&active_only=${ao}&level=${level}&rollup_type=${rollupType}`
    : null
  const movers = useFetch<SectorFlowMoversResponse>(moversUrl)

  // Net flows chart — sum each sector's net per period for parent + fund.
  // Compute from the static (active_only=0) responses so this never moves.
  // 4 destination columns; if fewer periods exist, pad with empty placeholders.
  const netFlowsChartData = useMemo(() => {
    const p = parentStatic.data
    const f = fundStatic.data
    const periodsRef = p?.periods ?? f?.periods ?? []
    const tail = periodsRef.slice(-4)
    const filled: (typeof periodsRef[number] | null)[] = [...tail]
    while (filled.length < 4) filled.unshift(null)
    return filled.map(period => {
      if (!period) {
        return {
          periodLabel: '',
          institutionalRaw: 0, fundRaw: 0,
          institutional: 0, fund: 0,
          institutionalInflow: 0, institutionalOutflow: 0,
          fundInflow: 0, fundOutflow: 0,
          empty: true,
        }
      }
      const key = `${period.from}_${period.to}`
      let instInflow = 0, instOutflow = 0, instNet = 0
      let fundInflow = 0, fundOutflow = 0, fundNet = 0
      ;(p?.sectors ?? []).forEach(s => {
        const f = s.flows[key]
        if (!f) return
        instInflow += f.inflow || 0
        instOutflow += f.outflow || 0
        instNet += f.net || 0
      })
      ;(f?.sectors ?? []).forEach(s => {
        const fl = s.flows[key]
        if (!fl) return
        fundInflow += fl.inflow || 0
        fundOutflow += fl.outflow || 0
        fundNet += fl.net || 0
      })
      return {
        periodLabel: fmtQuarterLabel(period.to),
        institutional: instNet / 1e9,
        institutionalRaw: instNet,
        institutionalInflow: instInflow,
        institutionalOutflow: instOutflow,
        fund: fundNet / 1e9,
        fundRaw: fundNet,
        fundInflow,
        fundOutflow,
        empty: false,
      }
    })
  }, [parentStatic.data, fundStatic.data])

  // Mover detail fetch.
  const moverDetailUrl = moverDetail && selectedSector && moverPeriod
    ? `/api/v1/sector_flow_mover_detail?from=${enc(moverPeriod.from)}&to=${enc(moverPeriod.to)}&sector=${enc(selectedSector)}&institution=${enc(moverDetail.institution)}&active_only=${ao}&level=${level}&rollup_type=${rollupType}`
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
            <NetFlowsCard data={netFlowsChartData} loading={parentStatic.loading || fundStatic.loading} />
          </div>

          {/* C. Sector heatmap — replaces both bar chart + sector table. */}
          <div style={{ backgroundColor: 'var(--card)', border: '1px solid var(--line)' }}>
            <div style={PANEL_TITLE}>Sector Rotation — Net Flow by Period</div>
            {loading && <div style={{ ...CENTER_MSG, color: 'var(--text-dim)' }}>Loading…</div>}
            {error && !loading && <div style={{ ...CENTER_MSG, color: 'var(--neg)' }}>Error: {error}</div>}
            {!loading && !error && ranked.length === 0 && (
              <div style={{ ...CENTER_MSG, color: 'var(--text-dim)' }}>No data.</div>
            )}
            {!loading && !error && ranked.length > 0 && (
              <SectorHeatmap
                ranked={ranked}
                displayQuarters={displayQuarters}
                periodByDest={periodByDest}
                selectedSector={selectedSector}
                onSelectRow={(s) => { setSelectedSector(s); setSelectedPeriodTo(null) }}
                onSelectCell={(s, q) => { setSelectedSector(s); setSelectedPeriodTo(q) }}
                onCellHover={(t) => setCellTooltip(t)}
              />
            )}
            <div style={{ ...FOOTNOTE, borderTop: '1px solid var(--line-soft)' }}>
              Flows reflect changes in position size net of share price appreciation.
            </div>
          </div>

          {/* D. Movers panel */}
          <div style={{ display: 'grid', gridTemplateColumns: '3fr 2fr', gap: 16 }}>
            <div /> {/* empty cell — heatmap above already spans full width */}
            <div style={{ backgroundColor: 'var(--card)', border: '1px solid var(--line)' }}>
              <div style={{ ...PANEL_TITLE, display: 'flex', justifyContent: 'space-between' }}>
                <span>
                  {selectedSector ?? '—'}
                  {selectedSector && moverPeriod && ` — ${fmtQuarterLabel(moverPeriod.to)}`}
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
                    {fundView === 'fund' ? 'No fund-level mover data available' : 'No mover data'}
                  </div>
                ) : (
                  <>
                    <div style={{
                      padding: '8px 14px', fontSize: 11, color: 'var(--text-dim)',
                      backgroundColor: 'var(--panel)', borderBottom: '1px solid var(--line-soft)',
                      display: 'flex', gap: 16, fontFamily: "'JetBrains Mono', monospace",
                    }}>
                      <span>Net <b style={{ color: movers.data.summary.net >= 0 ? 'var(--pos)' : 'var(--neg)' }}>
                        <SignedMm v={movers.data.summary.net} />
                      </b></span>
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
                      ...FOOTNOTE,
                      borderTop: '1px solid var(--line-soft)',
                    }}>
                      Flows reflect changes in position size net of share price appreciation.
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
              periodLabel={moverPeriod ? fmtQuarterLabel(moverPeriod.to) : ''}
              data={moverDetailFetch.data}
              loading={moverDetailFetch.loading}
              error={moverDetailFetch.error}
              onClose={() => setMoverDetail(null)}
            />
          )}

          {/* Heatmap cell hover tooltip — floats with cursor */}
          {cellTooltip && <CellTooltip {...cellTooltip} />}
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
  const breakdown = summary?.type_breakdown ?? []
  const sorted = [...breakdown].sort((a, b) => b.pct_aum - a.pct_aum)
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 8 }}>
        <KpiTile kicker="Total AUM" value={v(summary?.total_aum, fmtAum)} />
        <KpiTile kicker="Total Holders" value={v(summary?.total_holders, x => NUM_0.format(x))} />
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 6 }}>
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
  periodLabel: string
  institutional: number
  institutionalRaw: number
  institutionalInflow: number
  institutionalOutflow: number
  fund: number
  fundRaw: number
  fundInflow: number
  fundOutflow: number
  empty: boolean
}

function NetFlowsCard({ data, loading }: { data: NetFlowsRow[]; loading: boolean }) {
  return (
    <div style={{ backgroundColor: 'var(--card)', border: '1px solid var(--line)', display: 'flex', flexDirection: 'column' }}>
      <div style={PANEL_TITLE}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span>Net Flows</span>
          <NetFlowsLegend />
        </div>
      </div>
      <div style={{ padding: '12px 12px 8px', flex: 1, minHeight: 200 }}>
        {loading && <div style={{ ...CENTER_MSG, color: 'var(--text-dim)', padding: 20 }}>Loading…</div>}
        {!loading && (
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} barCategoryGap={20} barGap={4} margin={{ top: 24, right: 12, left: 0, bottom: 4 }}>
              <XAxis dataKey="periodLabel"
                tick={{ fontSize: 10, fill: 'var(--text-dim)', fontFamily: "'JetBrains Mono', monospace" }}
                stroke="var(--line)" />
              <YAxis tick={{ fontSize: 10, fill: 'var(--text-dim)', fontFamily: "'JetBrains Mono', monospace" }}
                tickFormatter={fmtBillionsInt} width={56}
                stroke="var(--line)" />
              <Tooltip cursor={{ fill: 'rgba(255,255,255,0.04)' }} content={({ active, payload, label }) => {
                if (!active || !payload || payload.length === 0) return null
                const row = payload[0].payload as NetFlowsRow
                if (row.empty) return null
                return (
                  <div style={{ backgroundColor: 'var(--bg)', color: 'var(--text)', padding: '8px 12px', border: '1px solid var(--line)', fontSize: 11, lineHeight: 1.6, fontFamily: "'Inter', sans-serif", boxShadow: '0 8px 24px rgba(0,0,0,0.4)' }}>
                    <div style={{ fontWeight: 600, color: 'var(--white)', marginBottom: 4 }}>{label}</div>
                    <NetFlowsTooltipBlock label="Institutional" color={COLOR_INST}
                      inflow={row.institutionalInflow} outflow={row.institutionalOutflow} net={row.institutionalRaw} />
                    <div style={{ height: 4 }} />
                    <NetFlowsTooltipBlock label="Fund" color={COLOR_FUND_HEX}
                      inflow={row.fundInflow} outflow={row.fundOutflow} net={row.fundRaw} />
                  </div>
                )
              }} />
              <Legend wrapperStyle={{ display: 'none' }} />
              <ReferenceLine y={0} stroke="var(--line)" />
              <Bar dataKey="institutional" name="Institutional" fill={COLOR_INST} isAnimationActive={false}>
                <LabelList dataKey="institutionalRaw" content={renderValueLabel} />
              </Bar>
              <Bar dataKey="fund" name="Fund" fill={COLOR_FUND_HEX} isAnimationActive={false}>
                <LabelList dataKey="fundRaw" content={renderValueLabel} />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  )
}

function NetFlowsLegend() {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
      <LegendSwatch color={COLOR_INST} label="Institutional" />
      <LegendSwatch color={COLOR_FUND_HEX} label="Fund" />
    </div>
  )
}

function LegendSwatch({ color, label }: { color: string; label: string }) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
      <span style={{ width: 10, height: 10, backgroundColor: color, display: 'inline-block' }} />
      <span style={{
        fontSize: 9, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.16em',
        fontFamily: "'Hanken Grotesk', sans-serif", color: 'var(--text-dim)',
      }}>{label}</span>
    </span>
  )
}

function NetFlowsTooltipBlock({ label, color, inflow, outflow, net }: {
  label: string; color: string; inflow: number; outflow: number; net: number
}) {
  const fmtBn = (v: number) => {
    if (v === 0) return '—'
    const abs = Math.abs(v) / 1e9
    const s = abs >= 10 ? NUM_0.format(abs) : abs.toFixed(1)
    return v < 0 ? `($${s}B)` : `$${s}B`
  }
  return (
    <div style={{ minWidth: 160 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 2 }}>
        <span style={{ width: 8, height: 8, backgroundColor: color, display: 'inline-block' }} />
        <span style={{ fontSize: 9, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.16em',
          fontFamily: "'Hanken Grotesk', sans-serif", color: 'var(--text-dim)' }}>{label}</span>
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, fontFamily: "'JetBrains Mono', monospace" }}>
        <span style={{ color: 'var(--text-dim)' }}>Inflows</span>
        <span style={{ color: 'var(--pos)' }}>{fmtBn(inflow)}</span>
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, fontFamily: "'JetBrains Mono', monospace" }}>
        <span style={{ color: 'var(--text-dim)' }}>Outflows</span>
        <span style={{ color: 'var(--neg)' }}>{fmtBn(outflow)}</span>
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, fontFamily: "'JetBrains Mono', monospace" }}>
        <span style={{ color: 'var(--text-dim)' }}>Net</span>
        <span style={{ color: net >= 0 ? 'var(--pos)' : 'var(--neg)' }}>{fmtBn(net)}</span>
      </div>
    </div>
  )
}

// LabelList content: render the bar's true value above (positive) or below (negative).
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function renderValueLabel(props: any) {
  const x = (props?.x as number) ?? 0
  const y = (props?.y as number) ?? 0
  const width = (props?.width as number) ?? 0
  const height = (props?.height as number) ?? 0
  const value = (props?.value as number) ?? 0
  if (!isFinite(value) || value === 0) return null
  const isNeg = value < 0
  const labelY = isNeg ? y + height + 11 : y - 5
  const text = fmtBillionsInt(value)
  return (
    <text x={x + width / 2} y={labelY}
      fontSize={9}
      fill="var(--text)"
      textAnchor="middle"
      fontFamily="'JetBrains Mono', monospace">
      {text}
    </text>
  )
}

// ── Sector Heatmap ─────────────────────────────────────────────────────────

interface HeatmapProps {
  ranked: { sector: string; total_net: number; flows: Record<string, { inflow: number; outflow: number; net: number }> }[]
  displayQuarters: string[]
  periodByDest: Record<string, { from: string; to: string; label: string }>
  selectedSector: string | null
  onSelectRow: (sector: string) => void
  onSelectCell: (sector: string, periodTo: string) => void
  onCellHover: (t: {
    x: number; y: number
    sector: string; periodLabel: string
    inflow: number | null; outflow: number | null; net: number | null
  } | null) => void
}

function SectorHeatmap({
  ranked, displayQuarters, periodByDest, selectedSector,
  onSelectRow, onSelectCell, onCellHover,
}: HeatmapProps) {
  // Compute global max abs across all visible cells for color intensity scaling.
  const globalMax = useMemo(() => {
    let m = 0
    ranked.forEach(s => {
      displayQuarters.forEach(q => {
        const p = periodByDest[q]; if (!p) return
        const n = s.flows[`${p.from}_${p.to}`]?.net
        if (n != null && isFinite(n)) m = Math.max(m, Math.abs(n))
      })
    })
    return m
  }, [ranked, displayQuarters, periodByDest])

  // Scale relative to 40% of global max to keep mid-range cells visible.
  const scaleRef = globalMax * 0.4

  return (
    <div style={{ maxHeight: 600, overflowY: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'separate', borderSpacing: 0, tableLayout: 'fixed', fontSize: 12 }}>
        <colgroup>
          <col style={{ width: 50 }} />
          <col style={{ width: 200 }} />
          {displayQuarters.map(q => <col key={q} style={{ width: 110 }} />)}
          <col style={{ width: 130 }} />
        </colgroup>
        <thead>
          <tr>
            <th style={{ ...TH, top: 0, borderBottom: 'none' }} />
            <th style={{ ...TH, top: 0, borderBottom: 'none' }} />
            <th colSpan={displayQuarters.length} style={{
              ...TH_C, top: 0, borderBottom: '1px solid var(--line-soft)',
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
            <th style={{ ...TH_R, top: 26 }}>Rank</th>
            <th style={{ ...TH, top: 26 }}>Sector</th>
            {displayQuarters.map(q => (
              <th key={q} style={{ ...TH_C, top: 26 }}>{fmtQuarterLabel(q)}</th>
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
                onClick={() => onSelectRow(s.sector)}
                style={{
                  backgroundColor: isSel ? 'var(--gold-soft)' : undefined,
                  cursor: 'pointer',
                  transition: 'all 0.12s',
                }}
                onMouseOver={(e) => {
                  if (!isSel) (e.currentTarget as HTMLElement).style.backgroundColor = 'var(--panel-hi)'
                }}
                onMouseOut={(e) => {
                  if (!isSel) (e.currentTarget as HTMLElement).style.backgroundColor = ''
                }}>
                <td style={{
                  ...TD_R, color: 'var(--text-dim)',
                  borderLeft: isSel ? '2px solid var(--gold)' : '2px solid transparent',
                }}>{i + 1}</td>
                <td style={{ ...TD, fontWeight: 500, color: isSel ? 'var(--white)' : 'var(--text)' }}>{s.sector}</td>
                {displayQuarters.map(q => {
                  const p = periodByDest[q]
                  const flow = p ? s.flows[`${p.from}_${p.to}`] : null
                  const v = flow?.net ?? null
                  return (
                    <HeatCell
                      key={q}
                      value={v}
                      maxRef={scaleRef}
                      sector={s.sector}
                      periodLabel={fmtQuarterLabel(q)}
                      inflow={flow?.inflow ?? null}
                      outflow={flow?.outflow ?? null}
                      onClick={(e) => {
                        e.stopPropagation()
                        if (p) onSelectCell(s.sector, q)
                      }}
                      onHover={(pos) => {
                        if (!pos) { onCellHover(null); return }
                        onCellHover({
                          x: pos.x, y: pos.y,
                          sector: s.sector,
                          periodLabel: fmtQuarterLabel(q),
                          inflow: flow?.inflow ?? null,
                          outflow: flow?.outflow ?? null,
                          net: v,
                        })
                      }}
                    />
                  )
                })}
                <td style={{
                  ...TD_R,
                  borderLeft: '2px solid var(--gold)',
                  backgroundColor: 'var(--card)',
                  fontWeight: 600,
                  fontFamily: "'JetBrains Mono', monospace",
                  color: (s.total_net ?? 0) >= 0 ? 'var(--pos)' : 'var(--neg)',
                }}>
                  {fmtBillionsCell(s.total_net)}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function HeatCell({
  value, maxRef, onClick, onHover,
}: {
  value: number | null
  maxRef: number
  sector: string
  periodLabel: string
  inflow: number | null
  outflow: number | null
  onClick: (e: React.MouseEvent) => void
  onHover: (pos: { x: number; y: number } | null) => void
}) {
  const noData = value == null || !isFinite(value) || value === 0
  let bg = 'transparent'
  let fg: string = 'var(--text-mute)'
  if (!noData) {
    const intensity = Math.min(0.6, Math.max(0.05, (Math.abs(value) / Math.max(maxRef, 1)) * 0.6))
    if (value >= 0) {
      bg = `rgba(92,184,122,${intensity})`
      fg = '#5cb87a'
    } else {
      bg = `rgba(224,90,90,${intensity})`
      fg = '#e05a5a'
    }
  }
  return (
    <td
      onClick={onClick}
      onMouseEnter={(e) => onHover({ x: e.clientX, y: e.clientY })}
      onMouseMove={(e) => onHover({ x: e.clientX, y: e.clientY })}
      onMouseLeave={() => onHover(null)}
      style={{
        ...TD_R,
        textAlign: 'center',
        padding: '4px 6px',
        cursor: noData ? 'default' : 'pointer',
      }}
    >
      <span style={{
        display: 'inline-block',
        backgroundColor: bg,
        color: fg,
        padding: '6px 8px',
        borderRadius: 2,
        fontFamily: "'JetBrains Mono', monospace",
        fontSize: 11,
        minWidth: 70,
      }}>
        {fmtBillionsCell(value)}
      </span>
    </td>
  )
}

function CellTooltip({ x, y, sector, periodLabel, inflow, outflow, net }: {
  x: number; y: number
  sector: string; periodLabel: string
  inflow: number | null; outflow: number | null; net: number | null
}) {
  const fmtBn = (v: number | null) => {
    if (v == null || !isFinite(v) || v === 0) return '—'
    const abs = Math.abs(v) / 1e9
    const s = abs >= 10 ? NUM_0.format(abs) : abs.toFixed(1)
    return v < 0 ? `($${s}B)` : `$${s}B`
  }
  // Position near cursor, clamp to viewport.
  const W = 240, H = 110
  const left = Math.min(Math.max(8, x + 14), window.innerWidth - W - 8)
  const top = Math.min(Math.max(8, y - H - 10), window.innerHeight - H - 8)
  return (
    <div style={{
      position: 'fixed', left, top, width: W, zIndex: 60,
      backgroundColor: 'var(--bg)', color: 'var(--text)',
      border: '1px solid var(--line)', borderRadius: 0,
      padding: '8px 12px', fontSize: 11, lineHeight: 1.5,
      fontFamily: "'Inter', sans-serif",
      boxShadow: '0 8px 24px rgba(0,0,0,0.4)',
      pointerEvents: 'none',
    }}>
      <div style={{ color: 'var(--white)', fontWeight: 600, marginBottom: 2 }}>{sector}</div>
      <div style={{ color: 'var(--text-mute)', fontSize: 10, marginBottom: 4 }}>{periodLabel}</div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: "'JetBrains Mono', monospace" }}>
        <span style={{ color: 'var(--text-dim)' }}>Inflows</span>
        <span style={{ color: 'var(--pos)' }}>{fmtBn(inflow)}</span>
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: "'JetBrains Mono', monospace" }}>
        <span style={{ color: 'var(--text-dim)' }}>Outflows</span>
        <span style={{ color: 'var(--neg)' }}>{fmtBn(outflow)}</span>
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: "'JetBrains Mono', monospace" }}>
        <span style={{ color: 'var(--text-dim)' }}>Net</span>
        <span style={{ color: (net ?? 0) >= 0 ? 'var(--pos)' : 'var(--neg)' }}>{fmtBn(net)}</span>
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
      <table style={{ width: '100%', borderCollapse: 'separate', borderSpacing: 0, fontSize: 11 }}>
        <colgroup>
          <col style={{ width: 26 }} />
          <col />
          <col style={{ width: 130 }} />
        </colgroup>
        <tbody>
          {rows.map((r, i) => (
            <tr key={r.institution}
              onClick={onClickInstitution ? (e) => onClickInstitution(r.institution, e) : undefined}
              style={{ cursor: onClickInstitution ? 'pointer' : undefined, transition: 'all 0.12s' }}
              onMouseOver={onClickInstitution ? (e) => { (e.currentTarget as HTMLElement).style.backgroundColor = 'var(--panel-hi)' } : undefined}
              onMouseOut={onClickInstitution ? (e) => { (e.currentTarget as HTMLElement).style.backgroundColor = '' } : undefined}>
              <td style={{ ...TD, fontSize: 11, padding: '4px 8px', textAlign: 'right', color: 'var(--text-mute)' }}>{i + 1}</td>
              <td style={{ ...TD, fontSize: 11, padding: '4px 8px' }} title={r.institution}>{r.institution}</td>
              <td style={{ ...TD_R, fontSize: 11, padding: '4px 8px' }}><SignedMm v={r.net_flow} /></td>
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
  const W = 420
  const H = 320
  const left = Math.min(Math.max(8, anchor.x - W / 2), window.innerWidth - W - 8)
  const top = Math.min(anchor.y + 12, window.innerHeight - H - 8)

  return (
    <div ref={ref} style={{
      position: 'fixed', left, top, width: W, zIndex: 50,
      backgroundColor: 'var(--panel)', color: 'var(--text)',
      border: '1px solid var(--line)', borderRadius: 0,
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
            <col style={{ width: 110 }} />
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
                <td style={{ ...TD_R, padding: '6px 10px', fontSize: 11 }}><SignedMm v={r.net_flow} /></td>
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
