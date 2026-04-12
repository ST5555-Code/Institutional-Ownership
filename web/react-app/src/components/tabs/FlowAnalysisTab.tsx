import { useState } from 'react'
import { useAppStore } from '../../store/useAppStore'
import { useFetch } from '../../hooks/useFetch'
import type { FlowAnalysisResponse, FlowRow, QoqChartRow } from '../../types/api'
import {
  RollupToggle,
  FundViewToggle,
  ActiveOnlyToggle,
  ExportBar,
  getTypeStyle,
} from '../common'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip,
  ResponsiveContainer,
} from 'recharts'

// ── Formatters ─────────────────────────────────────────────────────────────

const NUM_0 = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 })
const NUM_1 = new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 })
const NUM_2 = new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

function fmtSharesMm(v: number | null): string {
  if (v == null || v === 0) return '—'
  return NUM_2.format(v / 1e6)
}

function fmtValueMm(v: number | null): string {
  if (v == null || v === 0) return '—'
  return `$${NUM_0.format(v / 1e6)}`
}

function fmtPct2(v: number | null): string {
  if (v == null || v === 0) return '—'
  return `${NUM_2.format(v)}%`
}

function Signed({ v, decimals = 2, suffix = '' }: { v: number | null; decimals?: number; suffix?: string }) {
  if (v == null || v === 0) return <>—</>
  const fmt = decimals === 2 ? NUM_2 : decimals === 1 ? NUM_1 : NUM_0
  if (v < 0) return <span style={{ color: '#ef4444' }}>({fmt.format(Math.abs(v))}{suffix})</span>
  return <span style={{ color: '#27AE60' }}>+{fmt.format(v)}{suffix}</span>
}

function SignalBadge({ signal }: { signal: string | null }) {
  if (!signal) return <>—</>
  const color = signal.includes('↑') ? '#27AE60' : signal.includes('↓') ? '#ef4444' : '#94a3b8'
  return <span style={{ color, fontWeight: 600 }}>{signal}</span>
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
const BADGE: React.CSSProperties = {
  display: 'inline-block', padding: '1px 6px', fontSize: 10,
  fontWeight: 600, borderRadius: 3,
}
const CENTER_MSG: React.CSSProperties = { padding: 40, fontSize: 14, textAlign: 'center' }

type Period = '1Q' | '2Q' | '4Q'
const PERIODS: { id: Period; label: string }[] = [
  { id: '1Q', label: 'Last Quarter' },
  { id: '2Q', label: 'Last 2 Quarters' },
  { id: '4Q', label: 'Last 3 Quarters' },
]

// ── Component ──────────────────────────────────────────────────────────────

export function FlowAnalysisTab() {
  const { ticker, rollupType } = useAppStore()

  const [period, setPeriod] = useState<Period>('1Q')
  const [fundView, setFundView] = useState<'hierarchy' | 'fund'>('hierarchy')
  const [activeOnly, setActiveOnly] = useState(false)

  const level = fundView === 'fund' ? 'fund' : 'parent'

  const url = ticker
    ? `/api/flow_analysis?ticker=${enc(ticker)}&period=${period}&level=${level}&active_only=${activeOnly}&rollup_type=${rollupType}`
    : null
  const { data, loading, error } = useFetch<FlowAnalysisResponse>(url)

  function onExcel() {
    if (!data) return
    const bsH = ['Rank', 'Institution', 'Type', 'From Shares (MM)', 'To Shares (MM)', 'Net Shares (MM)', 'Net Value ($MM)', '% Chg', '% Float', 'Signal']
    const neH = ['Rank', 'Institution', 'Type', 'Shares (MM)', 'Value ($MM)', '% Float']
    const exH = ['Rank', 'Institution', 'Type', 'Prior Shares (MM)', 'Prior Value ($MM)', '% Float']

    const fmtBS = (rows: FlowRow[]) => rows.map((r, i) => [
      i + 1, `"${r.inst_parent_name.replace(/"/g, '""')}"`, r.manager_type || '',
      r.from_shares != null ? (r.from_shares / 1e6).toFixed(2) : '',
      r.to_shares != null ? (r.to_shares / 1e6).toFixed(2) : '',
      r.net_shares != null ? (r.net_shares / 1e6).toFixed(2) : '',
      r.net_value != null ? (r.net_value / 1e6).toFixed(0) : '',
      r.pct_change != null ? r.pct_change.toFixed(2) : '',
      r.pct_float != null ? r.pct_float.toFixed(2) : '',
      r.momentum_signal || '',
    ])
    const fmtNE = (rows: FlowRow[]) => rows.map((r, i) => [
      i + 1, `"${r.inst_parent_name.replace(/"/g, '""')}"`, r.manager_type || '',
      r.to_shares != null ? (r.to_shares / 1e6).toFixed(2) : '',
      r.to_value != null ? (r.to_value / 1e6).toFixed(0) : '',
      r.pct_float != null ? r.pct_float.toFixed(2) : '',
    ])
    const fmtEX = (rows: FlowRow[]) => rows.map((r, i) => [
      i + 1, `"${r.inst_parent_name.replace(/"/g, '""')}"`, r.manager_type || '',
      r.from_shares != null ? (r.from_shares / 1e6).toFixed(2) : '',
      r.from_value != null ? (r.from_value / 1e6).toFixed(0) : '',
      r.pct_float != null ? r.pct_float.toFixed(2) : '',
    ])

    const csv = [
      ['--- Buyers ---'], bsH, ...fmtBS(data.buyers), [],
      ['--- Sellers ---'], bsH, ...fmtBS(data.sellers), [],
      ['--- New Entries ---'], neH, ...fmtNE(data.new_entries), [],
      ['--- Exits ---'], exH, ...fmtEX(data.exits),
    ].map(r => r.join(',')).join('\n')
    downloadCsv(csv, `flow_analysis_${ticker}_${period}.csv`)
  }

  if (!ticker) return <div style={CENTER_MSG}><span style={{ color: '#94a3b8' }}>Enter a ticker to load flow analysis</span></div>

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', backgroundColor: 'var(--card-bg)', borderRadius: 6, boxShadow: '0 1px 2px rgba(0,0,0,0.04)', overflow: 'hidden' }}>
      <style>{`@media print { .fa-controls { display:none!important } }`}</style>

      {/* Controls */}
      <div className="fa-controls" style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'flex-end', gap: 16, padding: '12px 16px', backgroundColor: '#f8fafc', borderBottom: '1px solid #e2e8f0', flexShrink: 0 }}>
        <div style={{ display: 'flex', gap: 4 }}>
          {PERIODS.map(p => (
            <button key={p.id} type="button" onClick={() => setPeriod(p.id)}
              style={{
                padding: '5px 12px', fontSize: 12, borderRadius: 4, cursor: 'pointer',
                fontWeight: period === p.id ? 600 : 400,
                color: period === p.id ? '#fff' : '#64748b',
                backgroundColor: period === p.id ? 'var(--oxford-blue)' : '#fff',
                border: `1px solid ${period === p.id ? 'var(--oxford-blue)' : '#e2e8f0'}`,
              }}>
              {p.label}
            </button>
          ))}
        </div>
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
            <div style={{ fontSize: 12, color: '#64748b' }}>
              {data.quarter_from} → {data.quarter_to}
            </div>

            {/* 4 QoQ trend charts in 2×2 grid */}
            <ChartsRow qoqCharts={data.qoq_charts} />

            {/* Four sections 2×2 */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
              <FlowSection title="Buyers" rows={data.buyers} color="#27AE60" type="buyers" />
              <FlowSection title="New Entries" rows={data.new_entries} color="#002147" type="new_entries" />
              <FlowSection title="Sellers" rows={data.sellers} color="#ef4444" type="sellers" />
              <FlowSection title="Exits" rows={data.exits} color="#475569" type="exits" />
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Charts — 4 QoQ trend charts in a 2×2 grid ─────────────────────────────

function ChartsRow({ qoqCharts }: { qoqCharts: QoqChartRow[] }) {
  if (!qoqCharts || qoqCharts.length === 0) {
    return <div style={{ height: 200, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#94a3b8', fontSize: 13 }}>No chart data available</div>
  }

  const pctFmt = (v: number) => `${(v * 100).toFixed(1)}%`
  const pctTip = (v: number) => `${(v * 100).toFixed(2)}%`

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: 8 }}>
      <MiniChart title="Flow Intensity — Total" data={qoqCharts}
        bars={[{ key: 'flow_intensity_total', name: 'Total', fill: '#002147' }]}
        fmt={pctFmt} tip={pctTip} />
      <MiniChart title="Flow Intensity — Active Only" data={qoqCharts}
        bars={[{ key: 'flow_intensity_active', name: 'Active', fill: '#4A90D9' }]}
        fmt={pctFmt} tip={pctTip} />
      <MiniChart title="Churn — Non-Passive" data={qoqCharts}
        bars={[{ key: 'churn_nonpassive', name: 'Non-Passive', fill: '#002147' }]}
        fmt={pctFmt} tip={pctTip} />
      <MiniChart title="Churn — Active" data={qoqCharts}
        bars={[{ key: 'churn_active', name: 'Active', fill: '#f5a623' }]}
        fmt={pctFmt} tip={pctTip} />
    </div>
  )
}

function MiniChart({ title, data, bars, fmt, tip }: {
  title: string
  data: QoqChartRow[]
  bars: Array<{ key: string; name: string; fill: string }>
  fmt: (v: number) => string
  tip: (v: number) => string
}) {
  return (
    <div style={{ border: '1px solid #e2e8f0', borderRadius: 6, padding: '6px 8px', backgroundColor: '#fff' }}>
      <div style={{ fontSize: 10, color: '#64748b', marginBottom: 2, fontWeight: 600 }}>{title}</div>
      <ResponsiveContainer width="100%" height={110}>
        <BarChart data={data} barSize={14}>
          <XAxis dataKey="label" tick={{ fontSize: 9 }} />
          <YAxis tick={{ fontSize: 8 }} tickFormatter={fmt} width={40} />
          <Tooltip formatter={tip} />
          {bars.map(b => (
            <Bar key={b.key} dataKey={b.key} name={b.name} fill={b.fill} radius={[2, 2, 0, 0]} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

// ── Section table ───────────────────────────────────────────────────────────

interface SectionProps {
  title: string
  rows: FlowRow[]
  color: string
  type: 'buyers' | 'sellers' | 'new_entries' | 'exits'
}

function FlowSection({ title, rows, type }: SectionProps) {
  const isBuyerSeller = type === 'buyers' || type === 'sellers'
  const isPositive = type === 'buyers' || type === 'new_entries'
  // Title bar: top sections (buyers/new entries) green, bottom (sellers/exits) red
  const titleBg = isPositive ? '#27AE60' : '#ef4444'
  const colCount = isBuyerSeller ? 10 : 6

  // Compute totals for sticky footer
  const totals = rows.reduce(
    (acc, r) => ({
      fromShares: acc.fromShares + (r.from_shares || 0),
      toShares: acc.toShares + (r.to_shares || 0),
      netShares: acc.netShares + (r.net_shares || 0),
      netValue: acc.netValue + (r.net_value || 0),
      fromValue: acc.fromValue + (r.from_value || 0),
      toValue: acc.toValue + (r.to_value || 0),
      pctFloat: acc.pctFloat + (r.pct_float || 0),
    }),
    { fromShares: 0, toShares: 0, netShares: 0, netValue: 0, fromValue: 0, toValue: 0, pctFloat: 0 },
  )

  const FC: React.CSSProperties = {
    padding: '5px 8px', fontSize: 11, fontWeight: 600,
    color: '#ffffff', backgroundColor: 'var(--oxford-blue)',
    position: 'sticky', bottom: 0, zIndex: 2,
    borderTop: '2px solid var(--oxford-blue)',
  }
  const FCR: React.CSSProperties = { ...FC, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }

  return (
    <div style={{ border: '1px solid #e2e8f0', borderRadius: 6, display: 'flex', flexDirection: 'column', maxHeight: 350, overflow: 'hidden' }}>
      {/* Title bar — green for inflow sections, red for outflow */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px', backgroundColor: titleBg, flexShrink: 0 }}>
        <span style={{ fontWeight: 700, fontSize: 13, color: '#ffffff' }}>{title}</span>
        <span style={{ fontSize: 11, color: 'rgba(255,255,255,0.7)', backgroundColor: 'rgba(255,255,255,0.2)', padding: '1px 6px', borderRadius: 8 }}>{rows.length}</span>
      </div>

      <div style={{ flex: 1, overflowY: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'separate', borderSpacing: 0, tableLayout: 'fixed', fontSize: 12 }}>
          <colgroup>
            <col style={{ width: 30 }} />
            <col />  {/* Institution — flex */}
            <col style={{ width: 62 }} />
            {isBuyerSeller ? (
              <>
                <col style={{ width: 72 }} />
                <col style={{ width: 72 }} />
                <col style={{ width: 72 }} />
                <col style={{ width: 72 }} />
                <col style={{ width: 56 }} />
                <col style={{ width: 56 }} />
                <col style={{ width: 36 }} />
              </>
            ) : (
              <>
                <col style={{ width: 72 }} />
                <col style={{ width: 76 }} />
                <col style={{ width: 56 }} />
              </>
            )}
          </colgroup>
          <thead>
            <tr>
              <th style={{ ...TH, width: undefined }}>#</th>
              <th style={TH}>Institution</th>
              <th style={{ ...TH, width: undefined }}>Type</th>
              {isBuyerSeller ? (
                <>
                  <th style={TH_R}>From</th>
                  <th style={TH_R}>To</th>
                  <th style={TH_R}>Net</th>
                  <th style={TH_R}>Net $</th>
                  <th style={TH_R}>% Chg</th>
                  <th style={TH_R}>Δ% Flt</th>
                  <th style={TH}>Sig</th>
                </>
              ) : type === 'new_entries' ? (
                <>
                  <th style={TH_R}>Shares</th>
                  <th style={TH_R}>Value</th>
                  <th style={TH_R}>% Flt</th>
                </>
              ) : (
                <>
                  <th style={TH_R}>Prior</th>
                  <th style={TH_R}>Prior $</th>
                  <th style={TH_R}>% Flt</th>
                </>
              )}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => {
              const ts = getTypeStyle(r.manager_type)
              return (
                <tr key={r.inst_parent_name}>
                  <td style={{ ...TD, textAlign: 'right', fontWeight: 700, color: '#64748b', fontSize: 11 }}>{i + 1}</td>
                  <td style={{ ...TD, fontWeight: 500, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: 0 }} title={r.inst_parent_name}>
                    {r.inst_parent_name}
                  </td>
                  <td style={TD}>
                    <span style={{ ...BADGE, backgroundColor: ts.bg, color: ts.color }}>{ts.label}</span>
                  </td>
                  {isBuyerSeller ? (
                    <>
                      <td style={TD_R}>{fmtSharesMm(r.from_shares)}</td>
                      <td style={TD_R}>{fmtSharesMm(r.to_shares)}</td>
                      <td style={TD_R}><Signed v={r.net_shares != null ? r.net_shares / 1e6 : null} /></td>
                      <td style={TD_R}><Signed v={r.net_value != null ? r.net_value / 1e6 : null} decimals={0} /></td>
                      <td style={TD_R}><Signed v={r.pct_change} decimals={1} suffix="%" /></td>
                      <td style={TD_R}>{fmtPct2(r.pct_float)}</td>
                      <td style={TD}><SignalBadge signal={r.momentum_signal} /></td>
                    </>
                  ) : type === 'new_entries' ? (
                    <>
                      <td style={TD_R}>{fmtSharesMm(r.to_shares)}</td>
                      <td style={TD_R}>{fmtValueMm(r.to_value)}</td>
                      <td style={TD_R}>{fmtPct2(r.pct_float)}</td>
                    </>
                  ) : (
                    <>
                      <td style={TD_R}>{fmtSharesMm(r.from_shares)}</td>
                      <td style={TD_R}>{fmtValueMm(r.from_value)}</td>
                      <td style={TD_R}>{fmtPct2(r.pct_float)}</td>
                    </>
                  )}
                </tr>
              )
            })}
            {rows.length === 0 && (
              <tr><td colSpan={colCount} style={{ ...TD, textAlign: 'center', padding: 20, color: '#64748b' }}>No data</td></tr>
            )}
          </tbody>
          {rows.length > 0 && (
            <tfoot>
              <tr>
                <td style={FC} />
                <td style={FC}>Total</td>
                <td style={FC} />
                {isBuyerSeller ? (
                  <>
                    <td style={FCR}>{fmtSharesMm(totals.fromShares)}</td>
                    <td style={FCR}>{fmtSharesMm(totals.toShares)}</td>
                    <td style={FCR}><span style={{ color: totals.netShares >= 0 ? '#27AE60' : '#ef4444' }}>{totals.netShares !== 0 ? NUM_2.format(totals.netShares / 1e6) : '—'}</span></td>
                    <td style={FCR}><span style={{ color: totals.netValue >= 0 ? '#27AE60' : '#ef4444' }}>{totals.netValue !== 0 ? `$${NUM_0.format(totals.netValue / 1e6)}` : '—'}</span></td>
                    <td style={FC} />
                    <td style={FCR}>{fmtPct2(totals.pctFloat)}</td>
                    <td style={FC} />
                  </>
                ) : type === 'new_entries' ? (
                  <>
                    <td style={FCR}>{fmtSharesMm(totals.toShares)}</td>
                    <td style={FCR}>{fmtValueMm(totals.toValue)}</td>
                    <td style={FCR}>{fmtPct2(totals.pctFloat)}</td>
                  </>
                ) : (
                  <>
                    <td style={FCR}>{fmtSharesMm(totals.fromShares)}</td>
                    <td style={FCR}>{fmtValueMm(totals.fromValue)}</td>
                    <td style={FCR}>{fmtPct2(totals.pctFloat)}</td>
                  </>
                )}
              </tr>
            </tfoot>
          )}
        </table>
      </div>
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
