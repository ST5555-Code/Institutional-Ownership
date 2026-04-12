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
} from '../common'
import {
  LineChart, Line, XAxis, YAxis, Tooltip, Legend,
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
  if (v < 0) return <span style={{ color: '#ef4444' }}>({NUM_0.format(Math.abs(mm))})</span>
  return <span style={{ color: '#27AE60' }}>+{NUM_0.format(mm)}</span>
}

// ── Styles ─────────────────────────────────────────────────────────────────

const TH: React.CSSProperties = {
  padding: '7px 8px', fontSize: 10, fontWeight: 700,
  textTransform: 'uppercase', letterSpacing: '0.04em',
  color: '#ffffff', backgroundColor: 'var(--oxford-blue)',
  textAlign: 'left', borderBottom: '1px solid #1e2d47',
  whiteSpace: 'nowrap', position: 'sticky', top: 0, zIndex: 3,
}
const TH_R: React.CSSProperties = { ...TH, textAlign: 'right' }
const TD: React.CSSProperties = {
  padding: '5px 8px', fontSize: 12, color: '#1e293b',
  borderBottom: '1px solid #e5e7eb',
}
const TD_R: React.CSSProperties = {
  ...TD, textAlign: 'right', fontVariantNumeric: 'tabular-nums',
}
const CENTER_MSG: React.CSSProperties = { padding: 40, fontSize: 14, textAlign: 'center' }

// ── Component ──────────────────────────────────────────────────────────────

export function PeerRotationTab() {
  const { ticker, rollupType } = useAppStore()

  const [fundView, setFundView] = useState<'hierarchy' | 'fund'>('hierarchy')
  const [activeOnly, setActiveOnly] = useState(false)
  const [selectedPeer, setSelectedPeer] = useState<string | null>(null)

  const level = fundView === 'fund' ? 'fund' : 'parent'
  const ao = activeOnly ? '1' : '0'

  const url = ticker
    ? `/api/peer_rotation?ticker=${enc(ticker)}&active_only=${ao}&level=${level}&rollup_type=${rollupType}`
    : null
  const { data, loading, error } = useFetch<PeerRotationResponse>(url)

  // Detail fetch — only when a peer is selected
  const detailUrl = ticker && selectedPeer
    ? `/api/peer_rotation_detail?ticker=${enc(ticker)}&peer=${enc(selectedPeer)}&active_only=${ao}&level=${level}&rollup_type=${rollupType}`
    : null
  const detail = useFetch<PeerRotationDetailResponse>(detailUrl)

  // Build chart data from subject_flows + sector_flows keyed by period
  const chartData = data ? data.periods.map(p => {
    const key = `${p.from}_${p.to}`
    return {
      label: p.label,
      subject: (data.subject_flows[key]?.net || 0) / 1e6,
      sector: (data.sector_flows[key]?.net || 0) / 1e6,
    }
  }) : []

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

  if (!ticker) return <div style={CENTER_MSG}><span style={{ color: '#94a3b8' }}>Enter a ticker to load peer rotation</span></div>

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', backgroundColor: 'var(--card-bg)', borderRadius: 6, boxShadow: '0 1px 2px rgba(0,0,0,0.04)', overflow: 'hidden' }}>
      <style>{`@media print { .pr-controls { display:none!important } }`}</style>

      {/* Controls */}
      <div className="pr-controls" style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'flex-end', gap: 16, padding: '12px 16px', backgroundColor: '#f8fafc', borderBottom: '1px solid #e2e8f0', flexShrink: 0 }}>
        <RollupToggle />
        <FundViewToggle value={fundView} onChange={setFundView} />
        <ActiveOnlyToggle value={activeOnly} onChange={setActiveOnly} label="Active Only" />
        <div style={{ marginLeft: 'auto' }}>
          <ExportBar onExcel={onExcel} onPrint={() => window.print()} disabled={!data} />
        </div>
      </div>

      {/* Content */}
      <div style={{ flex: 1, overflowY: 'auto', overflowX: 'auto' }}>
        {loading && <div style={{ ...CENTER_MSG, color: '#94a3b8' }}>Loading…</div>}
        {error && !loading && <div style={{ ...CENTER_MSG, color: '#ef4444' }}>Error: {error}</div>}
        {data && !loading && (
          <div style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 16 }}>
            {/* Subject card */}
            <div style={{ display: 'flex', gap: 24, padding: '10px 16px', backgroundColor: 'var(--card-bg)', border: '1px solid #e2e8f0', borderRadius: 6 }}>
              <InfoChip label="Ticker" value={data.subject.ticker} />
              <InfoChip label="Sector" value={data.subject.sector} />
              <InfoChip label="Industry" value={data.subject.industry} />
            </div>

            {/* Flow trend chart */}
            {chartData.length > 0 ? (
              <div style={{ border: '1px solid #e2e8f0', borderRadius: 6, overflow: 'hidden', backgroundColor: '#fff' }}>
                <div style={{ padding: '6px 12px', backgroundColor: 'var(--oxford-blue)', color: '#fff', fontSize: 12, fontWeight: 700 }}>Flow Trend — Subject vs Sector</div>
                <div style={{ padding: '8px 8px 4px' }}>
                  <ResponsiveContainer width="100%" height={160}>
                    <LineChart data={chartData}>
                      <XAxis dataKey="label" tick={{ fontSize: 10 }} />
                      <YAxis tick={{ fontSize: 9 }} tickFormatter={(v: number) => `$${NUM_1.format(v)}M`} width={56} />
                      <Tooltip formatter={(v: number) => `$${NUM_1.format(v)}M`} />
                      <Legend wrapperStyle={{ fontSize: 11 }} />
                      <ReferenceLine y={0} stroke="#94a3b8" strokeDasharray="3 3" />
                      <Line type="monotone" dataKey="subject" name="Subject" stroke="#f5a623" strokeWidth={2} dot={{ r: 4 }} />
                      <Line type="monotone" dataKey="sector" name="Sector" stroke="#4A90D9" strokeWidth={2} dot={{ r: 4 }} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </div>
            ) : (
              <div style={{ ...CENTER_MSG, color: '#94a3b8' }}>Insufficient period data</div>
            )}

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
    <div style={{ border: '1px solid #e2e8f0', borderRadius: 6, overflow: 'hidden' }}>
      <div style={{ padding: '6px 12px', backgroundColor: 'var(--oxford-blue)', color: '#fff', fontSize: 12, fontWeight: 700 }}>{title}</div>
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
                    backgroundColor: isSubj ? '#fef9c3' : isSel ? '#eff6ff' : undefined,
                    cursor: 'pointer',
                  }}>
                  <td style={{ ...TD, textAlign: 'right', fontWeight: 700, color: '#64748b', fontSize: 11 }}>{i + 1}</td>
                  <td style={{ ...TD, fontWeight: 700, color: 'var(--glacier-blue)' }}>{r.ticker}</td>
                  <td style={{ ...TD, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: 0 }} title={r.industry}>{r.industry}</td>
                  <td style={TD_R}><SignedMm v={r.net_peer_flow} /></td>
                  <td style={TD_R}><span style={{ color: '#27AE60' }}>{fmtMm(r.contra_subject_flow)}</span></td>
                  <td style={TD_R}>
                    {r.net_peer_flow < 0 ? <span style={{ color: '#ef4444' }}>({NUM_0.format(Math.abs(r.net_peer_flow - r.contra_subject_flow) / 1e6)})</span> : '—'}
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
    <div style={{ border: '1px solid #e2e8f0', borderRadius: 6, overflow: 'hidden' }}>
      <div style={{ padding: '6px 12px', backgroundColor: 'var(--oxford-blue)', color: '#fff', fontSize: 12, fontWeight: 700 }}>Top Sector Movers</div>
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
              <tr key={r.ticker} style={{ backgroundColor: r.is_subject ? '#fef9c3' : undefined }}>
                <td style={{ ...TD, textAlign: 'right', fontWeight: 700, color: '#64748b', fontSize: 11 }}>{r.rank}</td>
                <td style={{ ...TD, fontWeight: 700, color: 'var(--glacier-blue)' }}>{r.ticker}</td>
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
    <div style={{ border: '1px solid #e2e8f0', borderRadius: 6, overflow: 'hidden' }}>
      <div style={{ padding: '6px 12px', backgroundColor: 'var(--oxford-blue)', color: '#fff', fontSize: 12, fontWeight: 700 }}>Entity Stories</div>
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
                <td style={{ ...TD, fontSize: 11, color: '#64748b', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: 0 }}
                  title={r.top_contra_peers.map(p => `${p.ticker} (${p.flow >= 0 ? '+' : ''}$${NUM_0.format(p.flow / 1e6)}M)`).join(', ')}>
                  {r.top_contra_peers.slice(0, 3).map((p, i) => (
                    <span key={p.ticker}>
                      {i > 0 && ', '}
                      <span style={{ color: p.flow >= 0 ? '#27AE60' : '#ef4444' }}>
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
    <div style={{ backgroundColor: 'var(--card-bg)', border: '1px solid #e2e8f0', borderRadius: 6, padding: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <span style={{ fontWeight: 700, fontSize: 14, color: 'var(--oxford-blue)' }}>
          {ticker} ↔ {peer} — Entity Breakdown
        </span>
        <button type="button" onClick={onClose}
          style={{ backgroundColor: 'transparent', border: 'none', fontSize: 18, color: '#94a3b8', cursor: 'pointer', lineHeight: 1 }}>×</button>
      </div>
      {loading && <div style={{ color: '#94a3b8', fontSize: 13 }}>Loading…</div>}
      {!loading && entities.length === 0 && <div style={{ color: '#94a3b8', fontSize: 13 }}>No entity data</div>}
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
      <div style={{ fontSize: 10, fontWeight: 600, textTransform: 'uppercase', color: '#94a3b8', letterSpacing: '0.08em', marginBottom: 2 }}>{label}</div>
      <div style={{ fontSize: 13, color: '#1e293b' }}>{value}</div>
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
