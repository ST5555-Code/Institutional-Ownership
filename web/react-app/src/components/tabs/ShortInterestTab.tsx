import { useMemo } from 'react'
import { useAppStore } from '../../store/useAppStore'
import { useFetch } from '../../hooks/useFetch'
import type {
  ShortAnalysisResponse,
  NportDetailRow,
  CrossRefRow,
  ShortOnlyFundRow,
  NportByFundRow,
} from '../../types/api'
import { ExportBar, ColumnGroupHeader, FreshnessBadge, getTypeStyle } from '../common'
import {
  BarChart, Bar, LineChart, Line, XAxis, YAxis, Tooltip,
  ResponsiveContainer, ReferenceLine,
} from 'recharts'

// ── Formatters ─────────────────────────────────────────────────────────────

const NUM_0 = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 })
const NUM_1 = new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 })
const NUM_2 = new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const NUM_3 = new Intl.NumberFormat('en-US', { minimumFractionDigits: 3, maximumFractionDigits: 3 })

function fmtSharesMm(v: number | null): string {
  if (v == null || v === 0) return '—'
  return NUM_2.format(v / 1e6)
}

function fmtValueMm(v: number | null): string {
  if (v == null || v === 0) return '—'
  return `$${NUM_0.format(v / 1e6)}`
}

// ── Styles ─────────────────────────────────────────────────────────────────

const TH: React.CSSProperties = {
  padding: '4px 8px', fontSize: 8, fontWeight: 700,
  textTransform: 'uppercase', letterSpacing: '0.16em', fontFamily: "'Hanken Grotesk', sans-serif",
  color: 'var(--text-dim)', backgroundColor: 'var(--header)',
  textAlign: 'left', borderBottom: '1px solid var(--line)',
  whiteSpace: 'nowrap',
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

// ── Component ──────────────────────────────────────────────────────────────

export function ShortInterestTab() {
  const { ticker } = useAppStore()

  const url = ticker ? `/api/v1/short_analysis?ticker=${encodeURIComponent(ticker)}` : null
  const { data, loading, error } = useFetch<ShortAnalysisResponse>(url)

  function onExcel() {
    if (!data) return
    const csv: string[][] = []
    // N-PORT Detail
    csv.push(['--- N-PORT Short Detail ---'])
    csv.push(['Fund', 'Family', 'Type', 'Short Shares (MM)', 'Short Value ($MM)', 'Fund AUM ($MM)', '% NAV', 'Quarter'])
    data.nport_detail.forEach(r => csv.push([`"${r.fund_name}"`, r.family_name || '', r.type || '', (r.short_shares / 1e6).toFixed(2), (r.short_value / 1e6).toFixed(0), r.fund_aum_mm?.toFixed(0) ?? '', r.pct_of_nav?.toFixed(3) ?? '', r.quarter]))
    csv.push([])
    // Cross-ref
    csv.push(['--- Cross-Ref Long/Short ---'])
    csv.push(['Institution', 'Type', 'Long ($MM)', 'Short ($MM)', 'Net Exposure %'])
    data.cross_ref.forEach(r => csv.push([`"${r.institution}"`, r.type || '', (r.long_value / 1e6).toFixed(0), (r.short_value / 1e6).toFixed(0), r.net_exposure_pct.toFixed(1)]))
    csv.push([])
    // Short-only
    csv.push(['--- Short-Only Funds ---'])
    csv.push(['Fund', 'Family', 'Type', 'Short Shares (MM)', 'Short Value ($MM)', 'AUM ($MM)'])
    data.short_only_funds.forEach(r => csv.push([`"${r.fund_name}"`, r.family_name || '', r.type || '', (r.short_shares / 1e6).toFixed(2), (r.short_value / 1e6).toFixed(0), r.fund_aum_mm?.toFixed(0) ?? '']))
    downloadCsv(csv.map(r => r.join(',')).join('\n'), `short_interest_${ticker}.csv`)
  }

  if (!ticker) return <div style={CENTER_MSG}><span style={{ color: 'var(--text-dim)' }}>Enter a ticker to load short interest analysis</span></div>

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', backgroundColor: 'var(--panel)', borderRadius: 0, boxShadow: '0 1px 2px rgba(0,0,0,0.04)', overflow: 'hidden' }}>
      <style>{`
        @media print {
          .si-controls { display:none!important }
          .si-wrap { height:auto!important; max-height:none!important; overflow:visible!important }
          .si-wrap * { max-height:none!important }
        }
      `}</style>

      {/* Controls */}
      <div className="si-controls" style={{ display: 'flex', alignItems: 'center', padding: '8px 12px', backgroundColor: 'var(--panel)', borderBottom: '1px solid var(--line)', flexShrink: 0 }}>
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 10 }}>
          <FreshnessBadge tableName="beneficial_ownership_current" label="SC-13" />
          <ExportBar onExcel={onExcel} onPrint={() => window.print()} disabled={!data} />
        </div>
      </div>

      <div className="si-wrap" style={{ flex: 1, overflowY: 'auto', overflowX: 'auto' }}>
        {loading && <div style={{ ...CENTER_MSG, color: 'var(--text-dim)' }}>Loading…</div>}
        {error && !loading && <div style={{ ...CENTER_MSG, color: 'var(--neg)' }}>Error: {error}</div>}
        {data && !loading && (
          <div style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 16 }}>
            {/* Summary cards */}
            <div style={{ display: 'flex', gap: 24, padding: '12px 16px', backgroundColor: 'var(--panel)', border: '1px solid var(--line)', borderRadius: 0 }}>
              <MetricTile label="Short Funds" value={String(data.summary.short_funds)} color="var(--header)" />
              <MetricTile label="Short Shares (MM)" value={NUM_2.format(data.summary.short_shares / 1e6)} color="var(--neg)" />
              <MetricTile label="Avg Short Vol %" value={data.summary.avg_short_vol_pct != null ? `${NUM_1.format(data.summary.avg_short_vol_pct)}%` : '—'} color={data.summary.avg_short_vol_pct != null && data.summary.avg_short_vol_pct > 20 ? 'var(--neg)' : 'var(--header)'} />
              <MetricTile label="Cross-Ref" value={String(data.summary.cross_ref_count)} color="var(--header)" />
            </div>

            {/* Charts row */}
            <div style={{ display: 'flex', gap: 12 }}>
              {/* N-PORT trend chart */}
              <div style={{ flex: 1, border: '1px solid var(--line)', borderRadius: 0, overflow: 'hidden', backgroundColor: 'var(--panel)' }}>
                <div style={{ padding: '6px 12px', backgroundColor: 'var(--header)', color: 'var(--white)', fontSize: 12, fontWeight: 700 }}>N-PORT Short Positions by Quarter</div>
                <div style={{ padding: '8px 8px 4px' }}>
                  {data.nport_trend.length > 0 ? (
                    <ResponsiveContainer width="100%" height={180}>
                      <BarChart data={data.nport_trend} barSize={24}>
                        <XAxis dataKey="quarter" tick={{ fontSize: 10 }} />
                        <YAxis tick={{ fontSize: 9 }} tickFormatter={(v: number) => `${NUM_1.format(v / 1e6)}M`} width={48} />
                        <Tooltip content={({ active, payload }) => {
                          if (!active || !payload?.[0]) return null
                          const d = payload[0].payload as { quarter: string; fund_count: number; short_shares: number; short_value: number }
                          return (
                            <div style={{ backgroundColor: 'var(--bg)', color: 'var(--line)', padding: '8px 12px', borderRadius: 0, border: '1px solid var(--line)', fontSize: 11 }}>
                              <div style={{ fontWeight: 700 }}>{d.quarter}</div>
                              <div>Funds: {d.fund_count}</div>
                              <div>Shares: {NUM_2.format(d.short_shares / 1e6)}M</div>
                              <div>Value: {fmtValueMm(d.short_value)}</div>
                            </div>
                          )
                        }} />
                        <Bar dataKey="short_shares" fill="var(--neg)" radius={[2, 2, 0, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  ) : <div style={{ ...CENTER_MSG, color: 'var(--text-dim)' }}>No N-PORT short data available</div>}
                </div>
              </div>

              {/* FINRA short volume chart */}
              <div style={{ flex: 1, border: '1px solid var(--line)', borderRadius: 0, overflow: 'hidden', backgroundColor: 'var(--panel)' }}>
                <div style={{ padding: '6px 12px', backgroundColor: 'var(--header)', color: 'var(--white)', fontSize: 12, fontWeight: 700 }}>FINRA Daily Short % (60 days)</div>
                <div style={{ padding: '8px 8px 4px' }}>
                  {data.short_volume.length > 0 ? (
                    <ResponsiveContainer width="100%" height={180}>
                      <LineChart data={data.short_volume.slice(-60)}>
                        <XAxis dataKey="report_date" tick={{ fontSize: 9 }} interval={9} />
                        <YAxis tick={{ fontSize: 9 }} tickFormatter={(v: number) => `${v}%`} width={40} />
                        <Tooltip formatter={(v: number) => `${NUM_1.format(v)}%`} />
                        <ReferenceLine y={20} stroke="var(--text-dim)" strokeDasharray="3 3" label={{ value: '20%', position: 'right', fontSize: 9, fill: 'var(--text-dim)' }} />
                        <Line type="monotone" dataKey="short_pct" stroke="var(--neg)" strokeWidth={2} dot={false} />
                      </LineChart>
                    </ResponsiveContainer>
                  ) : <div style={{ ...CENTER_MSG, color: 'var(--text-dim)' }}>No FINRA short volume data available</div>}
                </div>
              </div>
            </div>

            {/* Four tables 2×2 */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
              <NportDetailTable rows={data.nport_detail} />
              <CrossRefTable rows={data.cross_ref} />
              <ShortOnlyTable rows={data.short_only_funds} />
              <NportByFundTable rows={data.nport_by_fund} />
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Metric tile ─────────────────────────────────────────────────────────────

function MetricTile({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div style={{ flex: 1 }}>
      <div style={{ fontSize: 10, fontWeight: 600, textTransform: 'uppercase', color: 'var(--text-dim)', letterSpacing: '0.08em', marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 18, fontWeight: 700, color }}>{value}</div>
    </div>
  )
}

// ── N-PORT Detail table ─────────────────────────────────────────────────────

function NportDetailTable({ rows }: { rows: NportDetailRow[] }) {
  return (
    <SectionBox title="N-PORT Short Detail" borderColor="var(--header)">
      <table style={{ width: '100%', borderCollapse: 'separate', borderSpacing: 0, tableLayout: 'fixed', fontSize: 12 }}>
        <colgroup>
          <col style={{ width: 28 }} /><col /><col style={{ width: 90 }} /><col style={{ width: 60 }} />
          <col style={{ width: 72 }} /><col style={{ width: 76 }} /><col style={{ width: 72 }} /><col style={{ width: 56 }} />
        </colgroup>
        <thead><tr>
          <th style={TH}>#</th><th style={TH}>Fund</th><th style={TH}>Family</th><th style={TH}>Type</th>
          <th style={TH_R}>Short (MM)</th><th style={TH_R}>Value ($MM)</th><th style={TH_R}>AUM ($MM)</th><th style={TH_R}>% NAV</th>
        </tr></thead>
        <tbody>
          {rows.map((r, i) => {
            const ts = getTypeStyle(r.type)
            return (
              <tr key={r.fund_name}>
                <td style={{ ...TD, textAlign: 'right', fontWeight: 700, color: 'var(--text-dim)', fontSize: 11 }}>{i + 1}</td>
                <td style={{ ...TD, fontWeight: 500, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: 0 }} title={r.fund_name}>{r.fund_name}</td>
                <td style={{ ...TD, fontSize: 11, color: 'var(--text-dim)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: 0 }} title={r.family_name || ''}>{r.family_name || '—'}</td>
                <td style={TD}><span style={{ ...BADGE, backgroundColor: ts.bg, color: ts.color }}>{ts.label}</span></td>
                <td style={{ ...TD_R, color: 'var(--neg)' }}>{fmtSharesMm(r.short_shares)}</td>
                <td style={{ ...TD_R, color: 'var(--neg)' }}>{r.value_recomputed ? '~' : ''}{fmtValueMm(r.short_value)}</td>
                <td style={TD_R}>{r.fund_aum_mm != null ? `$${NUM_0.format(r.fund_aum_mm)}` : '—'}</td>
                <td style={TD_R}>{r.pct_of_nav != null ? `${NUM_3.format(r.pct_of_nav)}%` : '—'}</td>
              </tr>
            )
          })}
          {rows.length === 0 && <tr><td colSpan={8} style={{ ...TD, textAlign: 'center', padding: 20, color: 'var(--text-dim)' }}>No data</td></tr>}
        </tbody>
      </table>
    </SectionBox>
  )
}

// ── Cross-Ref table ─────────────────────────────────────────────────────────

function CrossRefTable({ rows }: { rows: CrossRefRow[] }) {
  return (
    <SectionBox title="Long + Short — Same Institution" borderColor="var(--gold)">
      <table style={{ width: '100%', borderCollapse: 'separate', borderSpacing: 0, tableLayout: 'fixed', fontSize: 12 }}>
        <colgroup>
          <col /><col style={{ width: 60 }} /><col style={{ width: 76 }} /><col style={{ width: 76 }} /><col style={{ width: 72 }} />
        </colgroup>
        <thead><tr>
          <th style={TH}>Institution</th><th style={TH}>Type</th>
          <th style={TH_R}>Long ($MM)</th><th style={TH_R}>Short ($MM)</th><th style={TH_R}>Net Exp %</th>
        </tr></thead>
        <tbody>
          {rows.map(r => {
            const ts = getTypeStyle(r.type)
            const expColor = r.net_exposure_pct >= 80 ? 'var(--pos)' : r.net_exposure_pct >= 50 ? 'var(--gold)' : 'var(--neg)'
            return (
              <tr key={r.institution}>
                <td style={{ ...TD, fontWeight: 500, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: 0 }} title={r.institution}>{r.institution}</td>
                <td style={TD}><span style={{ ...BADGE, backgroundColor: ts.bg, color: ts.color }}>{ts.label}</span></td>
                <td style={{ ...TD_R, color: 'var(--pos)' }}>{fmtValueMm(r.long_value)}</td>
                <td style={{ ...TD_R, color: 'var(--neg)' }}>{fmtValueMm(r.short_value)}</td>
                <td style={{ ...TD_R, color: expColor, fontWeight: 600 }}>{NUM_1.format(r.net_exposure_pct)}%</td>
              </tr>
            )
          })}
          {rows.length === 0 && <tr><td colSpan={5} style={{ ...TD, textAlign: 'center', padding: 20, color: 'var(--text-dim)' }}>No cross-ref data</td></tr>}
        </tbody>
      </table>
    </SectionBox>
  )
}

// ── Short-Only table ────────────────────────────────────────────────────────

function ShortOnlyTable({ rows }: { rows: ShortOnlyFundRow[] }) {
  return (
    <SectionBox title="Short-Only (No 13F Long)" borderColor="var(--neg)">
      <table style={{ width: '100%', borderCollapse: 'separate', borderSpacing: 0, tableLayout: 'fixed', fontSize: 12 }}>
        <colgroup>
          <col style={{ width: 28 }} /><col /><col style={{ width: 90 }} /><col style={{ width: 60 }} />
          <col style={{ width: 72 }} /><col style={{ width: 76 }} /><col style={{ width: 72 }} />
        </colgroup>
        <thead><tr>
          <th style={TH}>#</th><th style={TH}>Fund</th><th style={TH}>Family</th><th style={TH}>Type</th>
          <th style={{ ...TH_R, color: 'var(--neg)' }}>Short (MM)</th><th style={{ ...TH_R, color: 'var(--neg)' }}>Value ($MM)</th><th style={TH_R}>AUM ($MM)</th>
        </tr></thead>
        <tbody>
          {rows.map((r, i) => {
            const ts = getTypeStyle(r.type)
            return (
              <tr key={r.fund_name}>
                <td style={{ ...TD, textAlign: 'right', fontWeight: 700, color: 'var(--text-dim)', fontSize: 11 }}>{i + 1}</td>
                <td style={{ ...TD, fontWeight: 500, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: 0 }} title={r.fund_name}>{r.fund_name}</td>
                <td style={{ ...TD, fontSize: 11, color: 'var(--text-dim)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: 0 }}>{r.family_name || '—'}</td>
                <td style={TD}><span style={{ ...BADGE, backgroundColor: ts.bg, color: ts.color }}>{ts.label}</span></td>
                <td style={{ ...TD_R, color: 'var(--neg)' }}>{fmtSharesMm(r.short_shares)}</td>
                <td style={{ ...TD_R, color: 'var(--neg)' }}>{fmtValueMm(r.short_value)}</td>
                <td style={TD_R}>{r.fund_aum_mm != null ? `$${NUM_0.format(r.fund_aum_mm)}` : '—'}</td>
              </tr>
            )
          })}
          {rows.length === 0 && <tr><td colSpan={7} style={{ ...TD, textAlign: 'center', padding: 20, color: 'var(--text-dim)' }}>No short-only funds</td></tr>}
        </tbody>
      </table>
    </SectionBox>
  )
}

// ── N-PORT by Fund table ────────────────────────────────────────────────────

function NportByFundTable({ rows }: { rows: NportByFundRow[] }) {
  const qKeys = useMemo(() => {
    if (!rows.length) return [] as string[]
    const qRe = /^\d{4}Q\d$/
    return Object.keys(rows[0]).filter(k => qRe.test(k)).sort()
  }, [rows])

  const latestQ = qKeys[qKeys.length - 1] || ''

  return (
    <SectionBox title="N-PORT Short History by Fund" borderColor="var(--header)">
      <table style={{ width: '100%', borderCollapse: 'separate', borderSpacing: 0, tableLayout: 'fixed', fontSize: 12 }}>
        <thead>
          {qKeys.length > 0 && (
            <ColumnGroupHeader groups={[
              { label: '', colSpan: 2 },
              { label: 'Short Shares (MM)', colSpan: qKeys.length },
            ]} />
          )}
          <tr>
            <th style={TH}>Fund</th>
            <th style={{ ...TH, width: 60 }}>Type</th>
            {qKeys.map(q => <th key={q} style={{ ...TH_R, fontWeight: q === latestQ ? 700 : 600, width: 72 }}>{q}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map(r => {
            const ts = getTypeStyle(r.type as string | null)
            return (
              <tr key={r.fund_name as string}>
                <td style={{ ...TD, fontWeight: 500, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: 0 }} title={r.fund_name as string}>{r.fund_name as string}</td>
                <td style={TD}><span style={{ ...BADGE, backgroundColor: ts.bg, color: ts.color }}>{ts.label}</span></td>
                {qKeys.map(q => {
                  const v = r[q] as number | null | undefined
                  const isLatest = q === latestQ
                  return <td key={q} style={{ ...TD_R, fontWeight: isLatest ? 700 : 400 }}>
                    {typeof v === 'number' && v !== 0 ? <span style={{ color: 'var(--neg)' }}>{NUM_2.format(Math.abs(v) / 1e6)}</span> : '—'}
                  </td>
                })}
              </tr>
            )
          })}
          {rows.length === 0 && <tr><td colSpan={2 + qKeys.length} style={{ ...TD, textAlign: 'center', padding: 20, color: 'var(--text-dim)' }}>No history</td></tr>}
        </tbody>
      </table>
    </SectionBox>
  )
}

// ── Section box wrapper ─────────────────────────────────────────────────────

function SectionBox({ title, borderColor, children }: { title: string; borderColor: string; children: React.ReactNode }) {
  return (
    <div style={{ border: '1px solid var(--line)', borderRadius: 0, overflow: 'hidden', display: 'flex', flexDirection: 'column', maxHeight: 350 }}>
      <div style={{ padding: '6px 12px', borderLeft: `3px solid ${borderColor}`, backgroundColor: 'var(--panel)', borderBottom: '1px solid var(--line)', flexShrink: 0 }}>
        <span style={{ fontWeight: 700, fontSize: 12, color: 'var(--text)' }}>{title}</span>
      </div>
      <div style={{ flex: 1, overflowY: 'auto' }}>{children}</div>
    </div>
  )
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function downloadCsv(csv: string, filename: string) {
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
  const u = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = u; a.download = filename
  document.body.appendChild(a); a.click()
  document.body.removeChild(a); URL.revokeObjectURL(u)
}
