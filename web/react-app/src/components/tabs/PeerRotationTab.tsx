import { useState } from 'react'
import { useAppStore } from '../../store/useAppStore'
import { useFetch } from '../../hooks/useFetch'
import type {
  PeerRotationResponse,
  PeerRotationDetailResponse,
  SubstitutionRow,
  TopSectorMover,
  EntityStoryRow,
  PeerRotationDetailEntity,
} from '../../types/api'
import {
  RollupToggle,
  FundViewToggle,
  ActiveOnlyToggle,
  ExportBar,
  FreshnessBadge,
  PageHeader,
} from '../common'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, Legend, Cell,
  ResponsiveContainer, ReferenceLine,
} from 'recharts'

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
  padding: '4px 8px', fontSize: 8, fontWeight: 700,
  textTransform: 'uppercase', letterSpacing: '0.16em', fontFamily: "'Hanken Grotesk', sans-serif",
  color: 'var(--text-dim)', backgroundColor: 'var(--header)',
  textAlign: 'left', borderBottom: '1px solid var(--line)',
  whiteSpace: 'nowrap', position: 'sticky', top: 0, zIndex: 3,
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
const CENTER_MSG: React.CSSProperties = { padding: 40, fontSize: 14, textAlign: 'center' }

// ── Component ──────────────────────────────────────────────────────────────

export function PeerRotationTab() {
  const { ticker, rollupType } = useAppStore()

  const [fundView, setFundView] = useState<'hierarchy' | 'fund'>('hierarchy')
  const [activeOnly, setActiveOnly] = useState(false)
  const [selectedPeer, setSelectedPeer] = useState<string | null>(null)
  const [periodCount, setPeriodCount] = useState<1 | 2 | 3>(3)
  // Popup state for movers chart click
  const [moverPopup, setMoverPopup] = useState<{ ticker: string; inflow: number; outflow: number; net: number; x: number; y: number } | null>(null)

  const level = fundView === 'fund' ? 'fund' : 'parent'
  const ao = activeOnly ? '1' : '0'

  const url = ticker
    ? `/api/v1/peer_rotation?ticker=${enc(ticker)}&active_only=${ao}&level=${level}&rollup_type=${rollupType}`
    : null
  const { data, loading, error } = useFetch<PeerRotationResponse>(url)

  // Detail fetch — only when a peer is selected
  const detailUrl = ticker && selectedPeer
    ? `/api/v1/peer_rotation_detail?ticker=${enc(ticker)}&peer=${enc(selectedPeer)}&active_only=${ao}&level=${level}&rollup_type=${rollupType}`
    : null
  const detail = useFetch<PeerRotationDetailResponse>(detailUrl)

  // Build chart data — filter to last N periods based on selector
  const allChartData = data ? data.periods.map(p => {
    const key = `${p.from}_${p.to}`
    return {
      label: p.label,
      ticker: (data.subject_flows[key]?.net || 0) / 1e6,
      sector: (data.sector_flows[key]?.net || 0) / 1e6,
      pctOfIndustry: data.subject_pct_of_sector[key] ?? null,
    }
  }) : []
  // Period filter: take last N entries from the periods array
  const chartData = allChartData.slice(-periodCount)

  function onExcel() {
    if (!data) return
    const csv: string[][] = []
    csv.push(['--- Industry Substitutions ---'])
    csv.push(['Rank', 'Ticker', 'Industry', 'Net Flow ($MM)', 'Direction'])
    data.industry_substitutions.forEach((r, i) => {
      csv.push([String(i + 1), r.ticker, r.industry, (r.net_peer_flow / 1e6).toFixed(0), r.direction])
    })
    csv.push([])
    csv.push(['--- Sector Substitutions ---'])
    csv.push(['Rank', 'Ticker', 'Industry', 'Net Flow ($MM)', 'Direction'])
    data.sector_substitutions.forEach((r, i) => {
      csv.push([String(i + 1), r.ticker, r.industry, (r.net_peer_flow / 1e6).toFixed(0), r.direction])
    })
    csv.push([])
    csv.push(['--- Top Sector Movers ---'])
    csv.push(['Rank', 'Ticker', 'Industry', 'Net Flow ($MM)'])
    data.top_sector_movers.forEach(r => {
      csv.push([String(r.rank), r.ticker, r.industry, (r.net_flow / 1e6).toFixed(0)])
    })
    csv.push([])
    csv.push(['--- Entity Stories ---'])
    csv.push(['Institution', 'Subject Flow ($MM)', 'Sector Flow ($MM)', 'Top Contra Peers'])
    data.entity_stories.forEach(r => {
      const peers = r.top_contra_peers.map(p => `${p.ticker} (${p.flow >= 0 ? '+' : ''}$${NUM_0.format(p.flow / 1e6)}M)`).join(', ')
      csv.push([`"${r.entity}"`, (r.subject_flow / 1e6).toFixed(0), (r.sector_flow / 1e6).toFixed(0), `"${peers}"`])
    })
    downloadCsv(csv.map(r => r.join(',')).join('\n'), `peer_rotation_${ticker}.csv`)
  }

  if (!ticker) return <div style={CENTER_MSG}><span style={{ color: 'var(--text-dim)' }}>Enter a ticker to load peer rotation</span></div>

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', backgroundColor: 'var(--panel)', borderRadius: 0, boxShadow: '0 1px 2px rgba(0,0,0,0.04)', overflow: 'hidden' }}>
      {/* Header row: PageHeader (left) + FreshnessBadge + ExportBar (right) */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', padding: '0 12px', flexShrink: 0 }}>
        <div style={{ flex: 1 }}>
          <PageHeader
            section="Flow & Rotation"
            title="Peer Rotation"
            description="Cross-name rotation across a peer group. Identifies capital shifting between related securities."
          />
        </div>
        <div className="no-print" style={{ display: 'flex', alignItems: 'center', gap: 10, paddingTop: 14 }}>
          <FreshnessBadge tableName="investor_flows" label="flows" />
          <ExportBar onExcel={onExcel} onPrint={() => window.print()} disabled={!data} />
        </div>
      </div>
      <style>{`
        @media print {
          .pr-controls { display:none!important }
          .no-print { display:none!important }
          .pr-wrap { height:auto!important; max-height:none!important; overflow:visible!important }
          .pr-wrap * { max-height:none!important }
        }
      `}</style>

      {/* Controls */}
      <div className="pr-controls" style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'flex-end', gap: 10, padding: '8px 12px', backgroundColor: 'var(--panel)', borderBottom: '1px solid var(--line)', flexShrink: 0 }}>
        {/* Period selector */}
        <div style={{ display: 'flex', gap: 4 }}>
          {([{ n: 1 as const, label: 'Last Quarter' }, { n: 2 as const, label: 'Last 2 Quarters' }, { n: 3 as const, label: 'Last 3 Quarters' }]).map(p => (
            <button key={p.n} type="button" onClick={() => setPeriodCount(p.n)}
              style={{
                padding: '5px 12px', fontSize: 12, borderRadius: 0, cursor: 'pointer',
                fontWeight: periodCount === p.n ? 600 : 400,
                color: periodCount === p.n ? 'var(--white)' : 'var(--text-dim)',
                backgroundColor: periodCount === p.n ? 'var(--header)' : 'transparent',
                border: `1px solid ${periodCount === p.n ? 'var(--header)' : 'var(--line)'}`,
              }}>
              {p.label}
            </button>
          ))}
        </div>
        <RollupToggle />
        <FundViewToggle value={fundView} onChange={setFundView} />
        <ActiveOnlyToggle value={activeOnly} onChange={setActiveOnly} label="Active Only" />
      </div>

      {/* Content */}
      <div className="pr-wrap" style={{ flex: 1, overflowY: 'auto', overflowX: 'auto' }}>
        {loading && <div style={{ ...CENTER_MSG, color: 'var(--text-dim)' }}>Loading…</div>}
        {error && !loading && <div style={{ ...CENTER_MSG, color: 'var(--neg)' }}>Error: {error}</div>}
        {data && !loading && (
          <div style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 16 }}>
            {/* Subject card */}
            <div style={{ display: 'flex', gap: 24, padding: '10px 16px', backgroundColor: 'var(--panel)', border: '1px solid var(--line)', borderRadius: 0 }}>
              <InfoChip label="Ticker" value={data.subject.ticker} />
              <InfoChip label="Sector" value={data.subject.sector} />
              <InfoChip label="Industry" value={data.subject.industry} />
            </div>

            {/* Charts row — flow bar chart left, placeholder right */}
            <div style={{ display: 'flex', gap: 12 }}>
              {/* Left: ticker vs sector flow bars per period */}
              {chartData.length > 0 ? (
                <div style={{ flex: 1, border: '1px solid var(--line)', borderRadius: 0, overflow: 'hidden', backgroundColor: 'var(--panel)' }}>
                  <div style={{ padding: '6px 12px', backgroundColor: 'var(--header)', color: 'var(--white)', fontSize: 12, fontWeight: 700, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span>{data.subject.ticker} vs {data.subject.sector} Sector — Flow by Quarter</span>
                    <span style={{ fontSize: 11, fontWeight: 400, color: 'var(--text-dim)' }}>
                      % of industry flow to {data.subject.ticker}: {data.subject_pct_of_sector.total != null ? `${data.subject_pct_of_sector.total}%` : '—'}
                    </span>
                  </div>
                  <div style={{ padding: '8px 8px 4px' }}>
                    <ResponsiveContainer width="100%" height={180}>
                      <BarChart data={chartData} barSize={20} barGap={2}>
                        <XAxis dataKey="label" tick={{ fontSize: 10 }} />
                        <YAxis tick={{ fontSize: 9 }} tickFormatter={(v: number) => `$${NUM_1.format(v)}M`} width={56} />
                        <Tooltip formatter={(v: number) => `$${NUM_1.format(v)}M`} />
                        <Legend wrapperStyle={{ fontSize: 11 }} />
                        <ReferenceLine y={0} stroke="var(--text-dim)" strokeDasharray="3 3" />
                        <Bar dataKey="ticker" name={data.subject.ticker} fill="var(--gold)" radius={[2, 2, 0, 0]} />
                        <Bar dataKey="sector" name="Sector" fill="#7aadde" radius={[2, 2, 0, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              ) : (
                <div style={{ flex: 1, ...CENTER_MSG, color: 'var(--text-dim)', border: '1px solid var(--line)', borderRadius: 0 }}>Insufficient period data</div>
              )}

              {/* Right: Top Sector Movers chart */}
              <div style={{ flex: 1, border: '1px solid var(--line)', borderRadius: 0, overflow: 'hidden', backgroundColor: 'var(--panel)', position: 'relative' }}>
                <div style={{ padding: '6px 12px', backgroundColor: 'var(--header)', color: 'var(--white)', fontSize: 12, fontWeight: 700 }}>Top Sector Movers — Net Flow</div>
                <div style={{ padding: '8px 8px 4px' }}>
                  <ResponsiveContainer width="100%" height={180}>
                    <BarChart
                      data={data.top_sector_movers.map(m => ({
                        ticker: m.ticker,
                        net: m.net_flow / 1e6,
                        inflow: m.inflow,
                        outflow: m.outflow,
                        netRaw: m.net_flow,
                        isSubject: m.is_subject,
                      }))}
                      barSize={24}
                      onClick={(state) => {
                        if (state && state.activePayload && state.activePayload[0]) {
                          const d = state.activePayload[0].payload as { ticker: string; inflow: number; outflow: number; netRaw: number }
                          setMoverPopup({
                            ticker: d.ticker,
                            inflow: d.inflow,
                            outflow: d.outflow,
                            net: d.netRaw,
                            x: 0, y: 0,
                          })
                        }
                      }}
                    >
                      <XAxis dataKey="ticker" tick={{ fontSize: 10 }} />
                      <YAxis tick={{ fontSize: 9 }} tickFormatter={(v: number) => `$${NUM_1.format(v)}M`} width={56} />
                      <Tooltip content={({ active, payload }) => {
                        if (!active || !payload || !payload[0]) return null
                        const d = payload[0].payload as { ticker: string; inflow: number; outflow: number; netRaw: number; isSubject: boolean }
                        return (
                          <div style={{ backgroundColor: 'var(--bg)', color: 'var(--line)', padding: '8px 12px', borderRadius: 0, border: '1px solid var(--line)', fontSize: 11, lineHeight: 1.6 }}>
                            <div style={{ fontWeight: 700, marginBottom: 4 }}>{d.ticker}{d.isSubject ? ' (Subject)' : ''}</div>
                            <div><span style={{ color: 'var(--pos)' }}>Inflow:</span> ${NUM_0.format(d.inflow / 1e6)}M</div>
                            <div><span style={{ color: 'var(--neg)' }}>Outflow:</span> (${NUM_0.format(Math.abs(d.outflow) / 1e6)}M)</div>
                            <div style={{ borderTop: '1px solid var(--line)', marginTop: 4, paddingTop: 4, fontWeight: 600 }}>
                              Net: <span style={{ color: d.netRaw >= 0 ? 'var(--pos)' : 'var(--neg)' }}>${NUM_0.format(d.netRaw / 1e6)}M</span>
                            </div>
                          </div>
                        )
                      }} />
                      <ReferenceLine y={0} stroke="var(--text-dim)" strokeDasharray="3 3" />
                      <Bar dataKey="net" radius={[2, 2, 0, 0]}>
                        {data.top_sector_movers.map((m, idx) => (
                          <Cell key={idx} fill={m.is_subject ? 'var(--gold)' : 'var(--header)'} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
                {/* Click popup overlay */}
                {moverPopup && (
                  <div style={{ position: 'absolute', top: 40, right: 12, backgroundColor: 'var(--bg)', color: 'var(--line)', padding: '10px 14px', borderRadius: 0, border: '1px solid var(--line)', fontSize: 12, lineHeight: 1.7, zIndex: 10, minWidth: 160 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                      <span style={{ fontWeight: 700, fontSize: 13 }}>{moverPopup.ticker}</span>
                      <button type="button" onClick={() => setMoverPopup(null)} style={{ backgroundColor: 'transparent', border: 'none', color: 'var(--text-dim)', cursor: 'pointer', fontSize: 14 }}>×</button>
                    </div>
                    <div><span style={{ color: 'var(--pos)' }}>Inflow:</span> ${NUM_0.format(moverPopup.inflow / 1e6)}M</div>
                    <div><span style={{ color: 'var(--neg)' }}>Outflow:</span> (${NUM_0.format(Math.abs(moverPopup.outflow) / 1e6)}M)</div>
                    <div style={{ borderTop: '1px solid var(--line)', marginTop: 4, paddingTop: 4, fontWeight: 600 }}>
                      Net: <span style={{ color: moverPopup.net >= 0 ? 'var(--pos)' : 'var(--neg)' }}>${NUM_0.format(moverPopup.net / 1e6)}M</span>
                    </div>
                  </div>
                )}
              </div>
            </div>

            {/* Two-column layout */}
            <div style={{ display: 'flex', gap: 12 }}>
              {/* Left 60% */}
              <div style={{ flex: 3, display: 'flex', flexDirection: 'column', gap: 12 }}>
                <SectionTable title="Industry Substitutions" rows={data.industry_substitutions}
                  selectedPeer={selectedPeer} onSelectPeer={setSelectedPeer} subject={data.subject.ticker} />
                <SectionTable title="Sector Substitutions" rows={data.sector_substitutions}
                  selectedPeer={selectedPeer} onSelectPeer={setSelectedPeer} subject={data.subject.ticker} />
              </div>
              {/* Right 40% */}
              <div style={{ flex: 2, display: 'flex', flexDirection: 'column', gap: 12 }}>
                <MoversTable rows={data.top_sector_movers} />
                <StoriesTable rows={data.entity_stories} />
              </div>
            </div>

            {/* Detail panel */}
            {selectedPeer && (
              <DetailPanel
                ticker={data.subject.ticker}
                peer={selectedPeer}
                entities={detail.data?.entities || []}
                loading={detail.loading}
                onClose={() => setSelectedPeer(null)}
              />
            )}
          </div>
        )}
      </div>
    </div>
  )
}

// ── Substitution table ──────────────────────────────────────────────────────

function SectionTable({ title, rows, selectedPeer, onSelectPeer, subject }: {
  title: string; rows: SubstitutionRow[]; selectedPeer: string | null
  onSelectPeer: (t: string | null) => void; subject: string
}) {
  return (
    <div style={{ border: '1px solid var(--line)', borderRadius: 0, overflow: 'hidden' }}>
      <div style={{ padding: '6px 12px', backgroundColor: 'var(--header)', color: 'var(--white)', fontSize: 12, fontWeight: 700 }}>{title}</div>
      <div style={{ maxHeight: 280, overflowY: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'separate', borderSpacing: 0, tableLayout: 'fixed', fontSize: 12 }}>
          <colgroup>
            <col style={{ width: 30 }} />
            <col style={{ width: 64 }} />
            <col />
            <col style={{ width: 80 }} />
            <col style={{ width: 72 }} />
            <col style={{ width: 72 }} />
          </colgroup>
          <thead>
            <tr>
              <th style={TH}>#</th>
              <th style={TH}>Ticker</th>
              <th style={TH}>Industry</th>
              <th style={TH_R}>Net Flow</th>
              <th style={TH_R}>Inflow</th>
              <th style={TH_R}>Outflow</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => {
              const isSubj = r.ticker === subject
              const isSel = r.ticker === selectedPeer
              return (
                <tr key={r.ticker}
                  onClick={() => onSelectPeer(isSel ? null : r.ticker)}
                  style={{
                    backgroundColor: isSubj ? 'rgba(197,162,84,0.12)' : isSel ? 'rgba(122,173,222,0.08)' : undefined,
                    cursor: 'pointer',
                  }}>
                  <td style={{ ...TD, textAlign: 'right', fontWeight: 700, color: 'var(--text-dim)', fontSize: 11 }}>{i + 1}</td>
                  <td style={{ ...TD, fontWeight: 700, color: 'var(--gold)' }}>{r.ticker}</td>
                  <td style={{ ...TD, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: 0 }} title={r.industry}>{r.industry}</td>
                  <td style={TD_R}><SignedMm v={r.net_peer_flow} /></td>
                  <td style={TD_R}><span style={{ color: 'var(--pos)' }}>{fmtMm(r.contra_subject_flow)}</span></td>
                  <td style={TD_R}>
                    {r.net_peer_flow < 0 ? <span style={{ color: 'var(--neg)' }}>({NUM_0.format(Math.abs(r.net_peer_flow - r.contra_subject_flow) / 1e6)})</span> : '—'}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ── Top Sector Movers ───────────────────────────────────────────────────────

function MoversTable({ rows }: { rows: TopSectorMover[] }) {
  return (
    <div style={{ border: '1px solid var(--line)', borderRadius: 0, overflow: 'hidden' }}>
      <div style={{ padding: '6px 12px', backgroundColor: 'var(--header)', color: 'var(--white)', fontSize: 12, fontWeight: 700 }}>Top Sector Movers</div>
      <div style={{ maxHeight: 240, overflowY: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'separate', borderSpacing: 0, tableLayout: 'fixed', fontSize: 12 }}>
          <colgroup>
            <col style={{ width: 30 }} />
            <col style={{ width: 56 }} />
            <col />
            <col style={{ width: 80 }} />
          </colgroup>
          <thead>
            <tr>
              <th style={TH}>#</th>
              <th style={TH}>Ticker</th>
              <th style={TH}>Industry</th>
              <th style={TH_R}>Net Flow</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(r => (
              <tr key={r.ticker} style={{ backgroundColor: r.is_subject ? 'rgba(197,162,84,0.12)' : undefined }}>
                <td style={{ ...TD, textAlign: 'right', fontWeight: 700, color: 'var(--text-dim)', fontSize: 11 }}>{r.rank}</td>
                <td style={{ ...TD, fontWeight: 700, color: 'var(--gold)' }}>{r.ticker}</td>
                <td style={{ ...TD, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: 0 }} title={r.industry}>{r.industry}</td>
                <td style={TD_R}><SignedMm v={r.net_flow} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ── Entity Stories ──────────────────────────────────────────────────────────

function StoriesTable({ rows }: { rows: EntityStoryRow[] }) {
  return (
    <div style={{ border: '1px solid var(--line)', borderRadius: 0, overflow: 'hidden' }}>
      <div style={{ padding: '6px 12px', backgroundColor: 'var(--header)', color: 'var(--white)', fontSize: 12, fontWeight: 700 }}>Entity Stories</div>
      <div style={{ maxHeight: 240, overflowY: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'separate', borderSpacing: 0, tableLayout: 'fixed', fontSize: 12 }}>
          <colgroup>
            <col />
            <col style={{ width: 72 }} />
            <col style={{ width: 72 }} />
            <col style={{ width: 140 }} />
          </colgroup>
          <thead>
            <tr>
              <th style={TH}>Institution</th>
              <th style={TH_R}>Subj Flow</th>
              <th style={TH_R}>Sect Flow</th>
              <th style={TH}>Top Contra Peers</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(r => (
              <tr key={r.entity}>
                <td style={{ ...TD, fontWeight: 500, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: 0 }} title={r.entity}>{r.entity}</td>
                <td style={TD_R}><SignedMm v={r.subject_flow} /></td>
                <td style={TD_R}><SignedMm v={r.sector_flow} /></td>
                <td style={{ ...TD, fontSize: 11, color: 'var(--text-dim)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: 0 }}
                  title={r.top_contra_peers.map(p => `${p.ticker} (${p.flow >= 0 ? '+' : ''}$${NUM_0.format(p.flow / 1e6)}M)`).join(', ')}>
                  {r.top_contra_peers.slice(0, 3).map((p, i) => (
                    <span key={p.ticker}>
                      {i > 0 && ', '}
                      <span style={{ color: p.flow >= 0 ? 'var(--pos)' : 'var(--neg)' }}>
                        {p.ticker} {p.flow >= 0 ? '+' : ''}${NUM_0.format(p.flow / 1e6)}M
                      </span>
                    </span>
                  ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ── Detail panel ────────────────────────────────────────────────────────────

function DetailPanel({ ticker, peer, entities, loading, onClose }: {
  ticker: string; peer: string; entities: PeerRotationDetailEntity[]
  loading: boolean; onClose: () => void
}) {
  return (
    <div style={{ backgroundColor: 'var(--panel)', border: '1px solid var(--line)', borderRadius: 0, padding: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <span style={{ fontWeight: 700, fontSize: 14, color: 'var(--header)' }}>
          {ticker} ↔ {peer} — Entity Breakdown
        </span>
        <button type="button" onClick={onClose}
          style={{ backgroundColor: 'transparent', border: 'none', fontSize: 18, color: 'var(--text-dim)', cursor: 'pointer', lineHeight: 1 }}>×</button>
      </div>
      {loading && <div style={{ color: 'var(--text-dim)', fontSize: 13 }}>Loading…</div>}
      {!loading && entities.length === 0 && <div style={{ color: 'var(--text-dim)', fontSize: 13 }}>No entity data</div>}
      {!loading && entities.length > 0 && (
        <table style={{ width: '100%', borderCollapse: 'separate', borderSpacing: 0, tableLayout: 'fixed', fontSize: 12 }}>
          <colgroup>
            <col />
            <col style={{ width: 100 }} />
            <col style={{ width: 100 }} />
            <col style={{ width: 100 }} />
          </colgroup>
          <thead>
            <tr>
              <th style={TH}>Institution</th>
              <th style={TH_R}>Subject Flow</th>
              <th style={TH_R}>Peer Flow</th>
              <th style={TH_R}>Net</th>
            </tr>
          </thead>
          <tbody>
            {entities.slice(0, 20).map(e => (
              <tr key={e.entity}>
                <td style={{ ...TD, fontWeight: 500, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: 0 }} title={e.entity}>{e.entity}</td>
                <td style={TD_R}><SignedMm v={e.subject_flow} /></td>
                <td style={TD_R}><SignedMm v={e.peer_flow} /></td>
                <td style={TD_R}><SignedMm v={e.subject_flow + e.peer_flow} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function InfoChip({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div style={{ fontSize: 10, fontWeight: 600, textTransform: 'uppercase', color: 'var(--text-dim)', letterSpacing: '0.08em', marginBottom: 2 }}>{label}</div>
      <div style={{ fontSize: 13, color: 'var(--text)' }}>{value}</div>
    </div>
  )
}

function enc(s: string) { return encodeURIComponent(s) }

function downloadCsv(csv: string, filename: string) {
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
  const u = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = u; a.download = filename
  document.body.appendChild(a); a.click()
  document.body.removeChild(a); URL.revokeObjectURL(u)
}
