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
  PageHeader,
  getTypeStyle,
} from '../common'

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
  padding: '4px 8px', fontSize: 8, fontWeight: 700,
  textTransform: 'uppercase', letterSpacing: '0.16em',
  fontFamily: "'Hanken Grotesk', sans-serif",
  color: 'var(--text-dim)', backgroundColor: 'var(--header)',
  textAlign: 'left', borderBottom: '1px solid var(--line)',
  whiteSpace: 'nowrap', position: 'sticky', top: 0, zIndex: 3,
}
const TH_R: React.CSSProperties = { ...TH, textAlign: 'right' }
const TH_C: React.CSSProperties = { ...TH, textAlign: 'center' }
const TD: React.CSSProperties = {
  padding: '4px 8px', fontSize: 12, color: 'var(--text)',
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

// Short display labels for KPI manager-type tiles. Falls back to typeConfig label.
const KPI_SHORT_LABEL: Record<string, string> = {
  wealth_management:    'Wealth Mgmt',
  quantitative:         'Quant',
  pension_insurance:    'Pension',
  endowment_foundation: 'Endowment',
  family_office:        'Family Office',
  multi_strategy:       'Multi-Strat',
  hedge_fund:           'Quant/HF',
  private_equity:       'PE',
  venture_capital:      'VC',
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
    title: string; periodLabel: string
    inflow: number | null; outflow: number | null; net: number | null
  } | null>(null)

  const level = fundView === 'fund' ? 'fund' : 'parent'
  const ao = activeOnly ? '1' : '0'

  // Static fetches (KPI row + Net Flows heatmap) — never refetch on toggle.
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

  // Auto-select rank-1 sector on data load and on every toggle change.
  useEffect(() => {
    if (!data || ranked.length === 0) return
    setSelectedSector(ranked[0].sector)
    setSelectedPeriodTo(null)
    setMoverDetail(null)
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

  // Net Flows heatmap data — sum across all sectors per period for parent + fund.
  // Always uses static (active_only=0) responses.
  const netFlowsHeatmap = useMemo(() => {
    const p = parentStatic.data
    const f = fundStatic.data
    const periodsRef = p?.periods ?? f?.periods ?? []
    const tail = periodsRef.slice(-4)

    // Pad to 4 columns with placeholders if fewer.
    const filled: (typeof periodsRef[number] | null)[] = [...tail]
    while (filled.length < 4) filled.unshift(null)

    function aggregate(resp: SectorFlowsResponse | null, period: typeof periodsRef[number] | null) {
      if (!resp || !period) return { inflow: 0, outflow: 0, net: 0 }
      const key = `${period.from}_${period.to}`
      let inflow = 0, outflow = 0, net = 0
      resp.sectors.forEach(s => {
        const fl = s.flows[key]
        if (!fl) return
        inflow += fl.inflow || 0
        outflow += fl.outflow || 0
        net += fl.net || 0
      })
      return { inflow, outflow, net }
    }

    const instCells = filled.map(period => aggregate(p, period))
    const fundCells = filled.map(period => aggregate(f, period))

    const sumCells = (cells: { inflow: number; outflow: number; net: number }[]) =>
      cells.reduce((acc, c) => ({
        inflow: acc.inflow + c.inflow,
        outflow: acc.outflow + c.outflow,
        net: acc.net + c.net,
      }), { inflow: 0, outflow: 0, net: 0 })

    return {
      quarters: filled.map(period => period?.to ?? ''),
      rows: [
        { label: 'Institutional', color: COLOR_INST, cells: instCells, total: sumCells(instCells) },
        { label: 'Fund',          color: COLOR_FUND_HEX, cells: fundCells, total: sumCells(fundCells) },
      ],
    }
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
      <PageHeader
        section="Market Snapshot"
        title="Sector Rotation"
        description="Net institutional flows by sector. Heatmap view with drill-down to top movers per sector."
      />
      <style>{`
        @media print {
          .sr-controls { display:none!important }
          .sr-wrap { height:auto!important; max-height:none!important; overflow:visible!important }
          .sr-wrap * { max-height:none!important }
        }
      `}</style>

      {/* Controls */}
      <div className="sr-controls" style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 10, padding: '8px 12px', backgroundColor: 'var(--panel)', borderBottom: '1px solid var(--line)', flexShrink: 0 }}>
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

          {/* Top row: KPI block (2fr) + Net Flows heatmap (3fr) — STATIC */}
          <div style={{ display: 'grid', gridTemplateColumns: '2fr 3fr', gap: 16, alignItems: 'stretch' }}>
            <KpiRow summary={summary.data} loading={summary.loading} />
            <NetFlowsHeatmap
              data={netFlowsHeatmap}
              loading={parentStatic.loading || fundStatic.loading}
              onCellHover={setCellTooltip}
            />
          </div>

          {/* Main row: sector heatmap (flex 3) + movers panel (flex 2) */}
          <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start' }}>
            <div style={{ flex: 3, minWidth: 0, backgroundColor: 'var(--card)', border: '1px solid var(--line)' }}>
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

            <div style={{ flex: 2, minWidth: 0 }}>
              {!selectedSector ? (
                <div style={{
                  border: '1px dashed var(--line)',
                  padding: 40, textAlign: 'center',
                  color: 'var(--text-dim)', fontSize: 12,
                  fontFamily: "'Inter', sans-serif",
                  backgroundColor: 'transparent',
                }}>
                  Click a sector to see top movers
                </div>
              ) : (
                <div style={{ backgroundColor: 'var(--card)', border: '1px solid var(--line)' }}>
                  <div style={{ ...PANEL_TITLE, display: 'flex', justifyContent: 'space-between' }}>
                    <span>
                      {selectedSector}
                      {moverPeriod && ` — ${fmtQuarterLabel(moverPeriod.to)}`}
                    </span>
                    <span style={{ color: 'var(--text-mute)', textTransform: 'none', letterSpacing: '0.04em' }}>
                      {fundView === 'fund' ? 'fund' : 'parent'}
                    </span>
                  </div>
                  {movers.loading && (
                    <div style={{ ...CENTER_MSG, color: 'var(--text-dim)' }}>Loading movers…</div>
                  )}
                  {!movers.loading && movers.error && (
                    <div style={{ ...CENTER_MSG, color: 'var(--neg)' }}>Error: {movers.error}</div>
                  )}
                  {!movers.loading && !movers.error && movers.data && (
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
      minWidth: 0,
    }}>
      <div style={{
        fontSize: 9, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.14em',
        fontFamily: "'Hanken Grotesk', sans-serif", color,
        lineHeight: 1.25,
        minWidth: 0, flex: 1,
        overflowWrap: 'anywhere',
      }}>{label}</div>
      <div style={{
        fontSize: 14, fontFamily: "'JetBrains Mono', monospace",
        color: 'var(--white)', letterSpacing: '-0.01em', fontWeight: 400,
        fontVariantNumeric: 'tabular-nums', flexShrink: 0,
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
          const label = KPI_SHORT_LABEL[t.type] || style.label || t.type
          return (
            <KpiMini key={t.type} label={label}
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

// ── Net Flows Heatmap (static) ─────────────────────────────────────────────

interface NetFlowsCell {
  inflow: number
  outflow: number
  net: number
}
interface NetFlowsHeatmapData {
  quarters: string[]   // 4 destination quarters; '' for placeholder cols
  rows: {
    label: string
    color: string
    cells: NetFlowsCell[]
    total: NetFlowsCell
  }[]
}

function NetFlowsHeatmap({ data, loading, onCellHover }: {
  data: NetFlowsHeatmapData
  loading: boolean
  onCellHover: (t: {
    x: number; y: number
    title: string; periodLabel: string
    inflow: number | null; outflow: number | null; net: number | null
  } | null) => void
}) {
  // Color intensity scale across the 4-column data cells (exclude total).
  const scaleRef = useMemo(() => {
    let m = 0
    data.rows.forEach(r => r.cells.forEach(c => {
      if (isFinite(c.net)) m = Math.max(m, Math.abs(c.net))
    }))
    return m * 0.4
  }, [data])

  // Separate scale for total column.
  const totalScaleRef = useMemo(() => {
    let m = 0
    data.rows.forEach(r => { if (isFinite(r.total.net)) m = Math.max(m, Math.abs(r.total.net)) })
    return m * 0.4
  }, [data])

  return (
    <div style={{ backgroundColor: 'var(--card)', border: '1px solid var(--line)', display: 'flex', flexDirection: 'column' }}>
      <div style={PANEL_TITLE}>Net Flows</div>
      <div style={{ padding: '12px 12px 12px', flex: 1 }}>
        {loading && <div style={{ ...CENTER_MSG, color: 'var(--text-dim)', padding: 20 }}>Loading…</div>}
        {!loading && (
          <table style={{ width: '100%', borderCollapse: 'separate', borderSpacing: 0, tableLayout: 'fixed', fontSize: 12 }}>
            <colgroup>
              <col style={{ width: 130 }} />
              {data.quarters.map((_, i) => <col key={i} />)}
              <col style={{ width: 110 }} />
            </colgroup>
            <thead>
              <tr>
                <th style={{ ...TH, position: 'static' }} />
                {data.quarters.map((q, i) => (
                  <th key={i} style={{ ...TH_C, position: 'static' }}>
                    {q ? fmtQuarterLabel(q) : ''}
                  </th>
                ))}
                <th style={{ ...TH_R, position: 'static', color: 'var(--gold)' }}>Total Net</th>
              </tr>
            </thead>
            <tbody>
              {data.rows.map((r, rowIdx) => {
                const isLast = rowIdx === data.rows.length - 1
                return (
                  <tr key={r.label}>
                    <td style={{
                      ...TD,
                      borderBottom: isLast ? 'none' : TD.borderBottom,
                      fontFamily: "'Inter', sans-serif",
                      fontWeight: 500,
                      color: 'var(--text)',
                      whiteSpace: 'nowrap',
                    }}>
                      <span style={{
                        display: 'inline-flex', alignItems: 'center', gap: 8,
                      }}>
                        <span style={{
                          width: 10, height: 10, backgroundColor: r.color,
                          display: 'inline-block', flexShrink: 0,
                        }} />
                        <span>{r.label}</span>
                      </span>
                    </td>
                    {r.cells.map((c, i) => (
                      <HeatCell
                        key={i}
                        value={c.net}
                        maxRef={scaleRef}
                        onClick={() => {}}
                        onHover={(pos) => {
                          if (!pos) { onCellHover(null); return }
                          onCellHover({
                            x: pos.x, y: pos.y,
                            title: r.label,
                            periodLabel: data.quarters[i] ? fmtQuarterLabel(data.quarters[i]) : '',
                            inflow: c.inflow, outflow: c.outflow, net: c.net,
                          })
                        }}
                        cellBorderBottom={isLast ? 'none' : undefined}
                      />
                    ))}
                    <HeatCell
                      value={r.total.net}
                      maxRef={totalScaleRef}
                      onClick={() => {}}
                      onHover={(pos) => {
                        if (!pos) { onCellHover(null); return }
                        onCellHover({
                          x: pos.x, y: pos.y,
                          title: r.label, periodLabel: 'Total',
                          inflow: r.total.inflow, outflow: r.total.outflow, net: r.total.net,
                        })
                      }}
                      cellBorderLeft="2px solid var(--gold)"
                      cellBackground="var(--card)"
                      cellBorderBottom={isLast ? 'none' : undefined}
                    />
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
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
    title: string; periodLabel: string
    inflow: number | null; outflow: number | null; net: number | null
  } | null) => void
}

function SectorHeatmap({
  ranked, displayQuarters, periodByDest, selectedSector,
  onSelectRow, onSelectCell, onCellHover,
}: HeatmapProps) {
  // Compute global max abs across all visible quarter cells for color intensity scaling.
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

  // Totals row — sum across sectors per quarter, plus grand total.
  const totalsRow = useMemo(() => {
    const perQuarter: Record<string, { inflow: number; outflow: number; net: number }> = {}
    let grandInflow = 0, grandOutflow = 0, grandNet = 0
    displayQuarters.forEach(q => {
      const p = periodByDest[q]
      if (!p) { perQuarter[q] = { inflow: 0, outflow: 0, net: 0 }; return }
      let inflow = 0, outflow = 0, net = 0
      ranked.forEach(s => {
        const fl = s.flows[`${p.from}_${p.to}`]
        if (!fl) return
        inflow += fl.inflow || 0
        outflow += fl.outflow || 0
        net += fl.net || 0
      })
      perQuarter[q] = { inflow, outflow, net }
      grandInflow += inflow
      grandOutflow += outflow
      grandNet += net
    })
    return { perQuarter, total: { inflow: grandInflow, outflow: grandOutflow, net: grandNet } }
  }, [ranked, displayQuarters, periodByDest])

  // Scale for total_net column (sectors + totals row's grand total).
  const totalNetScaleRef = useMemo(() => {
    let m = 0
    ranked.forEach(s => { if (isFinite(s.total_net)) m = Math.max(m, Math.abs(s.total_net)) })
    if (isFinite(totalsRow.total.net)) m = Math.max(m, Math.abs(totalsRow.total.net))
    return m * 0.4
  }, [ranked, totalsRow])

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
                      onClick={(e) => {
                        e?.stopPropagation()
                        if (p) onSelectCell(s.sector, q)
                      }}
                      onHover={(pos) => {
                        if (!pos) { onCellHover(null); return }
                        onCellHover({
                          x: pos.x, y: pos.y,
                          title: s.sector,
                          periodLabel: fmtQuarterLabel(q),
                          inflow: flow?.inflow ?? null,
                          outflow: flow?.outflow ?? null,
                          net: v,
                        })
                      }}
                    />
                  )
                })}
                <HeatCell
                  value={s.total_net}
                  maxRef={totalNetScaleRef}
                  onClick={() => {}}
                  onHover={(pos) => {
                    if (!pos) { onCellHover(null); return }
                    onCellHover({
                      x: pos.x, y: pos.y,
                      title: s.sector, periodLabel: 'Total',
                      inflow: null, outflow: null, net: s.total_net,
                    })
                  }}
                  cellBorderLeft="2px solid var(--gold)"
                  cellBackground={isSel ? 'var(--gold-soft)' : 'var(--card)'}
                />
              </tr>
            )
          })}

          {/* Totals row */}
          <tr style={{ backgroundColor: 'var(--header)' }}>
            <td style={{
              ...TD_R, color: 'var(--text-dim)',
              borderTop: '2px solid var(--gold)',
              backgroundColor: 'var(--header)',
              fontWeight: 700,
            }} />
            <td style={{
              ...TD,
              borderTop: '2px solid var(--gold)',
              backgroundColor: 'var(--header)',
              color: 'var(--white)', fontWeight: 700,
              textTransform: 'uppercase', letterSpacing: '0.08em', fontSize: 11,
              fontFamily: "'Hanken Grotesk', sans-serif",
            }}>Total</td>
            {displayQuarters.map(q => {
              const cell = totalsRow.perQuarter[q] ?? { inflow: 0, outflow: 0, net: 0 }
              return (
                <HeatCell
                  key={q}
                  value={cell.net}
                  maxRef={scaleRef}
                  onClick={() => {}}
                  onHover={(pos) => {
                    if (!pos) { onCellHover(null); return }
                    onCellHover({
                      x: pos.x, y: pos.y,
                      title: 'Total', periodLabel: fmtQuarterLabel(q),
                      inflow: cell.inflow, outflow: cell.outflow, net: cell.net,
                    })
                  }}
                  cellBorderTop="2px solid var(--gold)"
                  cellBackground="var(--header)"
                />
              )
            })}
            <HeatCell
              value={totalsRow.total.net}
              maxRef={totalNetScaleRef}
              onClick={() => {}}
              onHover={(pos) => {
                if (!pos) { onCellHover(null); return }
                onCellHover({
                  x: pos.x, y: pos.y,
                  title: 'Total', periodLabel: 'Total',
                  inflow: totalsRow.total.inflow, outflow: totalsRow.total.outflow, net: totalsRow.total.net,
                })
              }}
              cellBorderLeft="2px solid var(--gold)"
              cellBorderTop="2px solid var(--gold)"
              cellBackground="var(--header)"
            />
          </tr>
        </tbody>
      </table>
    </div>
  )
}

function HeatCell({
  value, maxRef, onClick, onHover,
  cellBorderLeft, cellBorderTop, cellBorderBottom, cellBackground,
}: {
  value: number | null
  maxRef: number
  onClick: (e?: React.MouseEvent) => void
  onHover: (pos: { x: number; y: number } | null) => void
  cellBorderLeft?: string
  cellBorderTop?: string
  cellBorderBottom?: string
  cellBackground?: string
}) {
  const noData = value == null || !isFinite(value) || value === 0
  let bg = 'transparent'
  let fg: string = 'var(--text-mute)'
  if (!noData) {
    const intensity = Math.min(0.6, Math.max(0.05, (Math.abs(value as number) / Math.max(maxRef, 1)) * 0.6))
    if ((value as number) >= 0) {
      bg = `rgba(92,184,122,${intensity})`
      fg = '#5cb87a'
    } else {
      bg = `rgba(224,90,90,${intensity})`
      fg = '#e05a5a'
    }
  }
  const cellStyle: React.CSSProperties = {
    ...TD_R,
    textAlign: 'center',
    padding: '4px 6px',
    cursor: noData ? 'default' : 'pointer',
  }
  if (cellBorderLeft) cellStyle.borderLeft = cellBorderLeft
  if (cellBorderTop) cellStyle.borderTop = cellBorderTop
  if (cellBorderBottom !== undefined) cellStyle.borderBottom = cellBorderBottom
  if (cellBackground) cellStyle.backgroundColor = cellBackground
  return (
    <td
      onClick={onClick}
      onMouseEnter={(e) => onHover({ x: e.clientX, y: e.clientY })}
      onMouseMove={(e) => onHover({ x: e.clientX, y: e.clientY })}
      onMouseLeave={() => onHover(null)}
      style={cellStyle}
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

function CellTooltip({ x, y, title, periodLabel, inflow, outflow, net }: {
  x: number; y: number
  title: string; periodLabel: string
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
  const showInOut = inflow != null || outflow != null
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
      <div style={{ color: 'var(--white)', fontWeight: 600, marginBottom: 2 }}>{title}</div>
      {periodLabel && <div style={{ color: 'var(--text-mute)', fontSize: 10, marginBottom: 4 }}>{periodLabel}</div>}
      {showInOut && (
        <>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: "'JetBrains Mono', monospace" }}>
            <span style={{ color: 'var(--text-dim)' }}>Inflows</span>
            <span style={{ color: 'var(--pos)' }}>{fmtBn(inflow)}</span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: "'JetBrains Mono', monospace" }}>
            <span style={{ color: 'var(--text-dim)' }}>Outflows</span>
            <span style={{ color: 'var(--neg)' }}>{fmtBn(outflow)}</span>
          </div>
        </>
      )}
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
