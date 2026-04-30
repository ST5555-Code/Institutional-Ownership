import { useMemo } from 'react'
import { useAppStore } from '../../store/useAppStore'
import { useFetch } from '../../hooks/useFetch'
import type {
  ShortAnalysisResponse,
  NportDetailRow,
  CrossRefRow,
  ShortOnlyFundRow,
  NportByFundRow,
  ShortPositionPctResponse,
  ShortVolumeComparisonResponse,
} from '../../types/api'
import { ExportBar, ColumnGroupHeader, FreshnessBadge, PageHeader, getTypeStyle } from '../common'
import {
  Line, LineChart, XAxis, YAxis, Tooltip,
  ResponsiveContainer, CartesianGrid, Legend,
} from 'recharts'

// ── Formatters ─────────────────────────────────────────────────────────────

const NUM_0 = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 })
const NUM_1 = new Intl.NumberFormat('en-US', { minimumFractionDigits: 1, maximumFractionDigits: 1 })
const NUM_2 = new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const NUM_3 = new Intl.NumberFormat('en-US', { minimumFractionDigits: 3, maximumFractionDigits: 3 })

function fmtSharesMm(v: number | null): string {
  if (v == null || v === 0) return '—'
  return `${NUM_2.format(v / 1e6)} MM`
}

function fmtValueMm(v: number | null): string {
  if (v == null || v === 0) return '—'
  return `$${NUM_0.format(v / 1e6)}`
}

function fmtPct2(v: number | null): string {
  if (v == null) return '—'
  if (v === 0) return '—'
  return `${NUM_2.format(v)}%`
}

function fmtQuarter(v: string): string {
  if (!v || v.length < 6) return v
  const q = v.slice(-2)
  const yr = v.slice(2, 4)
  return `${q} '${yr}`
}

// ── Styles ─────────────────────────────────────────────────────────────────

const TH: React.CSSProperties = {
  padding: '4px 8px', fontSize: 9, fontWeight: 700,
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
const TD_TRUNC: React.CSSProperties = {
  ...TD, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
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

  const posUrl = ticker ? `/api/v1/short_position_pct?ticker=${encodeURIComponent(ticker)}` : null
  const { data: posData } = useFetch<ShortPositionPctResponse>(posUrl)

  const volUrl = ticker ? `/api/v1/short_volume_comparison?ticker=${encodeURIComponent(ticker)}` : null
  const { data: volData } = useFetch<ShortVolumeComparisonResponse>(volUrl)

  function onExcel() {
    if (!data) return
    const csv: string[][] = []
    csv.push(['--- N-PORT Short Detail ---'])
    csv.push(['Fund', 'Family', 'Type', 'Short Shares (MM)', 'Short Value ($MM)', 'Fund AUM ($MM)', '% NAV', 'Quarter'])
    data.nport_detail.forEach(r => csv.push([
      `"${r.fund_name}"`, r.family_name || '', r.type || '',
      (r.short_shares / 1e6).toFixed(2), (r.short_value / 1e6).toFixed(0),
      r.fund_aum_mm?.toFixed(0) ?? '', r.pct_of_nav?.toFixed(3) ?? '', r.quarter,
    ]))
    csv.push([])
    csv.push(['--- Cross-Ref Long/Short ---'])
    csv.push(['Institution', 'Type', 'Long ($MM)', 'Short ($MM)', 'Net Exposure %'])
    data.cross_ref.forEach(r => csv.push([
      `"${r.institution}"`, r.type || '',
      (r.long_value / 1e6).toFixed(0), (r.short_value / 1e6).toFixed(0),
      r.net_exposure_pct.toFixed(1),
    ]))
    csv.push([])
    csv.push(['--- Short-Only Funds ---'])
    csv.push(['Fund', 'Family', 'Type', 'Short Shares (MM)', 'Short Value ($MM)', 'AUM ($MM)'])
    data.short_only_funds.forEach(r => csv.push([
      `"${r.fund_name}"`, r.family_name || '', r.type || '',
      (r.short_shares / 1e6).toFixed(2), (r.short_value / 1e6).toFixed(0),
      r.fund_aum_mm?.toFixed(0) ?? '',
    ]))
    downloadCsv(csv.map(r => r.join(',')).join('\n'), `short_interest_${ticker}.csv`)
  }

  if (!ticker) return <div style={CENTER_MSG}><span style={{ color: 'var(--text-dim)' }}>Enter a ticker to load short interest analysis</span></div>

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', backgroundColor: 'var(--panel)', borderRadius: 0, overflow: 'hidden' }}>
      <style>{`
        @media print {
          .si-controls { display:none!important }
          .si-wrap { height:auto!important; max-height:none!important; overflow:visible!important }
          .si-wrap * { max-height:none!important }
        }
      `}</style>

      {/* Header row: PageHeader (left) + ExportBar (right) */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', padding: '0 12px', flexShrink: 0 }}>
        <div style={{ flex: 1 }}>
          <PageHeader
            section="Targeting"
            title="Short Interest Analysis"
            description="Short interest trend, N-PORT short positions, and long/short cross-reference."
          />
        </div>
        <div className="si-controls" style={{ display: 'flex', alignItems: 'center', gap: 10, paddingTop: 14 }}>
          <FreshnessBadge tableName="beneficial_ownership_current" label="SC-13" />
          <ExportBar onExcel={onExcel} onPrint={() => window.print()} disabled={!data} />
        </div>
      </div>

      <div className="si-wrap" style={{ flex: 1, overflowY: 'auto', overflowX: 'auto' }}>
        {loading && <div style={{ ...CENTER_MSG, color: 'var(--text-dim)' }}>Loading…</div>}
        {error && !loading && <div style={{ ...CENTER_MSG, color: 'var(--neg)' }}>Error: {error}</div>}
        {data && !loading && (
          <div style={{ padding: 12, display: 'flex', flexDirection: 'column', gap: 10 }}>
            {/* KPI tiles row */}
            <div style={{ display: 'flex', gap: 10 }}>
              <KpiTile label="Short Funds" value={NUM_0.format(data.summary.short_funds)} />
              <KpiTile label="SI % SO" value={data.summary.si_pct_so != null ? fmtPct2(data.summary.si_pct_so) : '—'} />
              <KpiTile label="Short Shares" value={fmtSharesMm(data.summary.short_shares)} />
              <KpiTile label="Short Value" value={data.summary.short_value ? `$${NUM_0.format(data.summary.short_value)}` : '—'} />
              <KpiTile label="Days to Cover" value={data.summary.days_to_cover != null ? NUM_1.format(data.summary.days_to_cover) : '—'} />
            </div>

            {/* Charts row */}
            <div style={{ display: 'flex', gap: 10 }}>
              <ShortPositionPctChart data={posData} ticker={ticker} />
              <ShortVolumeChart data={volData} ticker={ticker} />
            </div>

            {/* Footnote */}
            <div style={{
              fontSize: 10, color: 'var(--text-mute)', fontStyle: 'italic',
              padding: '4px 4px',
            }}>
              Short Volume % reflects daily off-exchange volume reported to FINRA. It includes market-maker hedging and is not equivalent to short interest.
            </div>

            {/* Tables — stacked full width */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
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

// ── KPI tile ────────────────────────────────────────────────────────────────

function KpiTile({ label, value }: { label: string; value: string }) {
  return (
    <div style={{
      flex: 1,
      backgroundColor: 'var(--card)',
      border: '1px solid var(--line)',
      borderRadius: 0,
      padding: 10,
    }}>
      <div style={{
        fontSize: 9,
        fontFamily: "'Hanken Grotesk', sans-serif",
        fontWeight: 700,
        textTransform: 'uppercase',
        letterSpacing: '0.16em',
        color: 'var(--text-dim)',
        marginBottom: 6,
      }}>
        {label}
      </div>
      <div style={{
        fontSize: 18,
        fontFamily: "'JetBrains Mono', monospace",
        fontWeight: 500,
        color: 'var(--white)',
        fontVariantNumeric: 'tabular-nums',
      }}>
        {value}
      </div>
    </div>
  )
}

// ── Chart container ─────────────────────────────────────────────────────────

function ChartBox({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{
      flex: 1,
      backgroundColor: 'var(--panel)',
      border: '1px solid var(--line)',
      borderRadius: 0,
      display: 'flex',
      flexDirection: 'column',
    }}>
      <div style={{
        padding: '8px 12px',
        fontSize: 9,
        fontFamily: "'Hanken Grotesk', sans-serif",
        fontWeight: 700,
        textTransform: 'uppercase',
        letterSpacing: '0.16em',
        color: 'var(--text-dim)',
        borderBottom: '1px solid var(--line)',
      }}>
        {title}
      </div>
      <div style={{ padding: '8px 8px 4px' }}>{children}</div>
    </div>
  )
}

// ── Chart tooltip styling ───────────────────────────────────────────────────

const TOOLTIP_STYLE: React.CSSProperties = {
  backgroundColor: 'var(--bg)',
  border: '1px solid var(--line)',
  borderRadius: 0,
  padding: 8,
  fontFamily: "'JetBrains Mono', monospace",
  fontSize: 11,
  color: 'var(--text)',
  boxShadow: '0 8px 24px rgba(0,0,0,0.4)',
}

const AXIS_TICK = { fill: 'var(--text-dim)', fontFamily: "'JetBrains Mono', monospace", fontSize: 10 }

// ── Left chart: Short Position % of SO (Fund Level, Quarterly) ─────────────

interface CombinedQRow {
  quarter: string
  ticker_pct: number | null
  sector_pct: number | null
  industry_pct: number | null
}

function ShortPositionPctChart({ data, ticker }: { data: ShortPositionPctResponse | null; ticker: string }) {
  const merged: CombinedQRow[] = (() => {
    if (!data) return []
    const all = new Set<string>()
    data.ticker_data.forEach(p => all.add(p.quarter))
    data.sector_avg.forEach(p => all.add(p.quarter))
    data.industry_avg.forEach(p => all.add(p.quarter))
    const tMap = new Map(data.ticker_data.map(p => [p.quarter, p.pct]))
    const sMap = new Map(data.sector_avg.map(p => [p.quarter, p.pct]))
    const iMap = new Map(data.industry_avg.map(p => [p.quarter, p.pct]))
    return Array.from(all).sort().map(q => ({
      quarter: q,
      ticker_pct: tMap.get(q) ?? null,
      sector_pct: sMap.get(q) ?? null,
      industry_pct: iMap.get(q) ?? null,
    }))
  })()

  const sectorLabel = `${data?.sector_name ?? 'Sector'} Avg`
  const industryLabel = `${data?.industry_name ?? 'Industry'} Avg`

  return (
    <ChartBox title="Short Position % of SO (Fund Level, Quarterly)">
      {merged.length > 0 ? (
        <ResponsiveContainer width="100%" height={240}>
          <LineChart data={merged} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
            <CartesianGrid stroke="var(--line-soft)" strokeDasharray="2 2" vertical={false} />
            <XAxis dataKey="quarter" tick={AXIS_TICK} stroke="none" tickFormatter={fmtQuarter} />
            <YAxis tick={AXIS_TICK} stroke="none" tickFormatter={(v: number) => `${NUM_2.format(v)}%`} width={60} />
            <Tooltip
              contentStyle={TOOLTIP_STYLE}
              labelStyle={{ color: 'var(--white)', fontWeight: 700, marginBottom: 4 }}
              labelFormatter={(label: string) => fmtQuarter(label)}
              formatter={(v: number, name: string) => [v != null ? `${NUM_3.format(v)}%` : '—', name]}
            />
            <Legend
              verticalAlign="top"
              align="right"
              height={20}
              wrapperStyle={{ fontFamily: "'Hanken Grotesk', sans-serif", fontSize: 10, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.08em' }}
            />
            <Line type="monotone" dataKey="ticker_pct" name={ticker} stroke="var(--gold)" strokeWidth={2} dot={{ r: 3, fill: '#c5a254' }} />
            <Line type="monotone" dataKey="sector_pct" name={sectorLabel} stroke="var(--gold)" strokeDasharray="6 4" strokeWidth={1.5} dot={{ r: 2, fill: '#c5a254' }} />
            <Line type="monotone" dataKey="industry_pct" name={industryLabel} stroke="var(--glacier-blue, #7aadde)" strokeDasharray="2 4" strokeWidth={1.5} dot={{ r: 2, fill: '#7aadde' }} />
          </LineChart>
        </ResponsiveContainer>
      ) : (
        <div style={{ ...CENTER_MSG, color: 'var(--text-dim)' }}>No N-PORT short data available</div>
      )}
    </ChartBox>
  )
}

// ── Right chart: Daily Short Volume % (FINRA) ──────────────────────────────

interface CombinedDRow {
  date: string
  ticker_pct: number | null
  sector_pct: number | null
  industry_pct: number | null
}

function ShortVolumeChart({ data, ticker }: { data: ShortVolumeComparisonResponse | null; ticker: string }) {
  const merged: CombinedDRow[] = (() => {
    if (!data) return []
    const all = new Set<string>()
    data.ticker_data.forEach(p => all.add(p.date))
    data.sector_median.forEach(p => all.add(p.date))
    data.industry_median.forEach(p => all.add(p.date))
    const tMap = new Map(data.ticker_data.map(p => [p.date, p.pct]))
    const sMap = new Map(data.sector_median.map(p => [p.date, p.pct]))
    const iMap = new Map(data.industry_median.map(p => [p.date, p.pct]))
    return Array.from(all).sort().map(d => ({
      date: d,
      ticker_pct: tMap.get(d) ?? null,
      sector_pct: sMap.get(d) ?? null,
      industry_pct: iMap.get(d) ?? null,
    }))
  })()

  const sectorLabel = `${data?.sector_name ?? 'Sector'} Med`
  const industryLabel = `${data?.industry_name ?? 'Industry'} Med`

  return (
    <ChartBox title="Daily Short Volume % (FINRA)">
      {merged.length > 0 ? (
        <ResponsiveContainer width="100%" height={240}>
          <LineChart data={merged} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
            <CartesianGrid stroke="var(--line-soft)" strokeDasharray="2 2" vertical={false} />
            <XAxis
              dataKey="date"
              tick={AXIS_TICK}
              stroke="none"
              interval={Math.max(0, Math.floor(merged.length / 7))}
              tickFormatter={(v: string) => {
                const d = new Date(v)
                return `${d.getDate()} ${d.toLocaleString('en-US', { month: 'short' })}`
              }}
            />
            <YAxis tick={AXIS_TICK} stroke="none" tickFormatter={(v: number) => `${NUM_0.format(v)}%`} width={48} />
            <Tooltip
              contentStyle={TOOLTIP_STYLE}
              labelStyle={{ color: 'var(--white)', fontWeight: 700, marginBottom: 4 }}
              formatter={(v: number, name: string) => [v != null ? `${NUM_2.format(v)}%` : '—', name]}
            />
            <Legend
              verticalAlign="top"
              align="right"
              height={20}
              wrapperStyle={{ fontFamily: "'Hanken Grotesk', sans-serif", fontSize: 10, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.08em' }}
            />
            <Line type="monotone" dataKey="ticker_pct" name={ticker} stroke="var(--white)" strokeWidth={2} dot={{ r: 2, fill: 'var(--white)' }} />
            <Line type="monotone" dataKey="sector_pct" name={sectorLabel} stroke="var(--gold)" strokeDasharray="6 4" strokeWidth={1.5} dot={false} />
            <Line type="monotone" dataKey="industry_pct" name={industryLabel} stroke="var(--glacier-blue, #7aadde)" strokeDasharray="2 4" strokeWidth={1.5} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      ) : (
        <div style={{ ...CENTER_MSG, color: 'var(--text-dim)' }}>No FINRA short volume data available</div>
      )}
    </ChartBox>
  )
}

// ── Table container ─────────────────────────────────────────────────────────

function TableBox({ title, accentBottom = 'var(--line)', children }: {
  title: string
  accentBottom?: string
  children: React.ReactNode
}) {
  return (
    <div style={{ border: '1px solid var(--line)', borderRadius: 0, overflow: 'hidden', backgroundColor: 'var(--panel)' }}>
      <div style={{
        padding: '8px 12px',
        fontSize: 9,
        fontFamily: "'Hanken Grotesk', sans-serif",
        fontWeight: 700,
        textTransform: 'uppercase',
        letterSpacing: '0.16em',
        color: 'var(--text-dim)',
        backgroundColor: 'var(--header)',
        borderBottom: `1px solid ${accentBottom}`,
      }}>{title}</div>
      <div style={{ overflow: 'auto' }}>{children}</div>
    </div>
  )
}

// ── N-PORT Detail table ─────────────────────────────────────────────────────

function NportDetailTable({ rows }: { rows: NportDetailRow[] }) {
  return (
    <TableBox title="N-PORT Short Detail">
      <table style={{ width: '100%', borderCollapse: 'separate', borderSpacing: 0, tableLayout: 'fixed', fontSize: 12 }}>
        <colgroup>
          <col style={{ width: 28 }} /><col /><col style={{ width: 160 }} /><col style={{ width: 75 }} />
          <col style={{ width: 85 }} /><col style={{ width: 85 }} /><col style={{ width: 85 }} /><col style={{ width: 65 }} />
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
                <td style={{ ...TD_TRUNC, fontWeight: 500 }} title={r.fund_name}>{r.fund_name}</td>
                <td style={{ ...TD_TRUNC, fontSize: 11, color: 'var(--text-dim)' }} title={r.family_name || ''}>{r.family_name || '—'}</td>
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
    </TableBox>
  )
}

// ── Cross-Ref table ─────────────────────────────────────────────────────────

function CrossRefTable({ rows }: { rows: CrossRefRow[] }) {
  return (
    <TableBox title="Long + Short — Same Institution" accentBottom="var(--gold)">
      <table style={{ width: '100%', borderCollapse: 'separate', borderSpacing: 0, tableLayout: 'fixed', fontSize: 12 }}>
        <colgroup>
          <col style={{ width: 28 }} /><col /><col style={{ width: 75 }} />
          <col style={{ width: 85 }} /><col style={{ width: 85 }} /><col style={{ width: 75 }} />
        </colgroup>
        <thead><tr>
          <th style={TH}>#</th><th style={TH}>Institution</th><th style={TH}>Type</th>
          <th style={TH_R}>Long ($MM)</th><th style={TH_R}>Short ($MM)</th><th style={TH_R}>Net Exp %</th>
        </tr></thead>
        <tbody>
          {rows.map((r, i) => {
            const ts = getTypeStyle(r.type)
            const expColor = r.net_exposure_pct >= 80 ? 'var(--pos)' : r.net_exposure_pct >= 50 ? 'var(--gold)' : 'var(--neg)'
            return (
              <tr key={r.institution}>
                <td style={{ ...TD, textAlign: 'right', fontWeight: 700, color: 'var(--text-dim)', fontSize: 11 }}>{i + 1}</td>
                <td style={{ ...TD_TRUNC, fontWeight: 500 }} title={r.institution}>{r.institution}</td>
                <td style={TD}><span style={{ ...BADGE, backgroundColor: ts.bg, color: ts.color }}>{ts.label}</span></td>
                <td style={{ ...TD_R, color: 'var(--pos)' }}>{fmtValueMm(r.long_value)}</td>
                <td style={{ ...TD_R, color: 'var(--neg)' }}>{fmtValueMm(r.short_value)}</td>
                <td style={{ ...TD_R, color: expColor, fontWeight: 600 }}>{NUM_1.format(r.net_exposure_pct)}%</td>
              </tr>
            )
          })}
          {rows.length === 0 && <tr><td colSpan={6} style={{ ...TD, textAlign: 'center', padding: 20, color: 'var(--text-dim)' }}>No cross-ref data</td></tr>}
        </tbody>
      </table>
    </TableBox>
  )
}

// ── Short-Only table ────────────────────────────────────────────────────────

function ShortOnlyTable({ rows }: { rows: ShortOnlyFundRow[] }) {
  return (
    <TableBox title="Short-Only Funds (No 13F Long)">
      <table style={{ width: '100%', borderCollapse: 'separate', borderSpacing: 0, tableLayout: 'fixed', fontSize: 12 }}>
        <colgroup>
          <col style={{ width: 28 }} /><col /><col style={{ width: 160 }} /><col style={{ width: 75 }} />
          <col style={{ width: 85 }} /><col style={{ width: 85 }} /><col style={{ width: 65 }} />
        </colgroup>
        <thead><tr>
          <th style={TH}>#</th><th style={TH}>Fund</th><th style={TH}>Family</th><th style={TH}>Type</th>
          <th style={{ ...TH_R, color: 'var(--neg)' }}>Short (MM)</th><th style={{ ...TH_R, color: 'var(--neg)' }}>Value ($MM)</th><th style={TH_R}>% NAV</th>
        </tr></thead>
        <tbody>
          {rows.map((r, i) => {
            const ts = getTypeStyle(r.type)
            const pctNav = r.fund_aum_mm && r.fund_aum_mm > 0 && r.short_value
              ? (r.short_value / (r.fund_aum_mm * 1e6)) * 100
              : null
            return (
              <tr key={r.fund_name}>
                <td style={{ ...TD, textAlign: 'right', fontWeight: 700, color: 'var(--text-dim)', fontSize: 11 }}>{i + 1}</td>
                <td style={{ ...TD_TRUNC, fontWeight: 500 }} title={r.fund_name}>{r.fund_name}</td>
                <td style={{ ...TD_TRUNC, fontSize: 11, color: 'var(--text-dim)' }} title={r.family_name || ''}>{r.family_name || '—'}</td>
                <td style={TD}><span style={{ ...BADGE, backgroundColor: ts.bg, color: ts.color }}>{ts.label}</span></td>
                <td style={{ ...TD_R, color: 'var(--neg)' }}>{fmtSharesMm(r.short_shares)}</td>
                <td style={{ ...TD_R, color: 'var(--neg)' }}>{fmtValueMm(r.short_value)}</td>
                <td style={TD_R}>{pctNav != null ? `${NUM_3.format(pctNav)}%` : '—'}</td>
              </tr>
            )
          })}
          {rows.length === 0 && <tr><td colSpan={7} style={{ ...TD, textAlign: 'center', padding: 20, color: 'var(--text-dim)' }}>No short-only funds</td></tr>}
        </tbody>
      </table>
    </TableBox>
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
    <TableBox title="N-PORT By Fund — Short History">
      <table style={{ width: '100%', borderCollapse: 'separate', borderSpacing: 0, tableLayout: 'fixed', fontSize: 12 }}>
        <colgroup>
          <col style={{ width: 28 }} /><col /><col style={{ width: 160 }} /><col style={{ width: 75 }} />
          {qKeys.map(q => <col key={q} style={{ width: 75 }} />)}
        </colgroup>
        <thead>
          {qKeys.length > 0 && (
            <ColumnGroupHeader groups={[
              { label: '', colSpan: 4 },
              { label: 'Short Shares (MM)', colSpan: qKeys.length },
            ]} />
          )}
          <tr>
            <th style={TH}>#</th>
            <th style={TH}>Fund</th>
            <th style={TH}>Family</th>
            <th style={TH}>Type</th>
            {qKeys.map(q => <th key={q} style={{ ...TH_R, fontWeight: q === latestQ ? 700 : 600 }}>{fmtQuarter(q)}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => {
            const ts = getTypeStyle(r.type as string | null)
            const fam = (r.family_name as string | null | undefined) || '—'
            return (
              <tr key={r.fund_name as string}>
                <td style={{ ...TD, textAlign: 'right', fontWeight: 700, color: 'var(--text-dim)', fontSize: 11 }}>{i + 1}</td>
                <td style={{ ...TD_TRUNC, fontWeight: 500 }} title={r.fund_name as string}>{r.fund_name as string}</td>
                <td style={{ ...TD_TRUNC, fontSize: 11, color: 'var(--text-dim)' }} title={fam}>{fam}</td>
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
          {rows.length === 0 && <tr><td colSpan={4 + qKeys.length} style={{ ...TD, textAlign: 'center', padding: 20, color: 'var(--text-dim)' }}>No history</td></tr>}
        </tbody>
      </table>
    </TableBox>
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
