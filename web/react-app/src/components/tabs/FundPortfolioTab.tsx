import { useEffect, useMemo, useState } from 'react'
import { useAppStore } from '../../store/useAppStore'
import { useFetch } from '../../hooks/useFetch'
import type {
  FundPortfolioManager,
  FundPortfolioResponse,
} from '../../types/api'
import { ExportBar, FreshnessBadge, PageHeader, TableFooter, getTypeStyle } from '../common'

// ── Formatters ─────────────────────────────────────────────────────────────

const NUM_0 = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 })
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
const BADGE: React.CSSProperties = {
  display: 'inline-block', padding: '1px 6px', fontSize: 10,
  fontWeight: 600, borderRadius: 1,
}
const CENTER_MSG: React.CSSProperties = { padding: 40, fontSize: 14, textAlign: 'center' }

const TOTAL_COLS = 8

// ── Component ──────────────────────────────────────────────────────────────

export function FundPortfolioTab() {
  const { ticker, loadCompany, setActiveTab } = useAppStore()

  function navigateToRegister(nextTicker: string | null) {
    if (!nextTicker) return
    const t = nextTicker.toUpperCase()
    if (t === (ticker || '').toUpperCase()) return
    loadCompany(t)
    setActiveTab('register')
  }

  // Selected manager state — cik + fund_name needed for query7
  const [selectedCik, setSelectedCik] = useState<string | null>(null)
  const [selectedFundName, setSelectedFundName] = useState<string | null>(null)

  // Fetch manager list
  const managersUrl = ticker
    ? `/api/v1/fund_portfolio_managers?ticker=${enc(ticker)}`
    : null
  const managers = useFetch<FundPortfolioManager[]>(managersUrl)

  // Auto-select first manager when ticker changes or managers reload
  useEffect(() => {
    if (managers.data && managers.data.length > 0) {
      const first = managers.data[0]
      setSelectedCik(first.cik)
      setSelectedFundName(first.fund_name)
    } else {
      setSelectedCik(null)
      setSelectedFundName(null)
    }
  }, [managers.data])

  // Fetch portfolio for selected manager
  const portfolioUrl = ticker && selectedCik
    ? `/api/v1/query7?ticker=${enc(ticker)}&cik=${enc(selectedCik)}${selectedFundName ? `&fund_name=${enc(selectedFundName)}` : ''}`
    : null
  const portfolio = useFetch<FundPortfolioResponse>(portfolioUrl)

  // Footer totals
  const totals = useMemo(() => {
    if (!portfolio.data) return { shares: 0, value: 0 }
    let shares = 0, value = 0
    for (const p of portfolio.data.positions) {
      shares += p.shares || 0
      value += p.market_value_live || 0
    }
    return { shares, value }
  }, [portfolio.data])

  // CSV export
  function onExcel() {
    if (!portfolio.data) return
    const h = ['Rank', 'Ticker', 'Company', 'Sector', 'Shares (MM)', 'Value ($MM)', '% Portfolio', '% SO']
    const csv = [h, ...portfolio.data.positions.map(p => [
      p.rank,
      p.ticker || '',
      `"${(p.issuer_name || '').replace(/"/g, '""')}"`,
      p.sector || '',
      p.shares != null ? (p.shares / 1e6).toFixed(2) : '',
      p.market_value_live != null ? (p.market_value_live / 1e6).toFixed(0) : '',
      p.pct_of_portfolio != null ? p.pct_of_portfolio.toFixed(2) : '',
      p.pct_of_so != null ? p.pct_of_so.toFixed(2) : '',
    ])].map(r => r.join(',')).join('\n')
    downloadCsv(csv, `fund_portfolio_${ticker}_${selectedCik}.csv`)
  }

  // Manager selection handler
  function onManagerChange(e: React.ChangeEvent<HTMLSelectElement>) {
    const idx = parseInt(e.target.value)
    if (!managers.data || isNaN(idx)) return
    const m = managers.data[idx]
    setSelectedCik(m.cik)
    setSelectedFundName(m.fund_name)
  }

  // Current selection index for <select>
  const selectedIdx = useMemo(() => {
    if (!managers.data || !selectedCik) return 0
    const idx = managers.data.findIndex(m => m.cik === selectedCik && m.fund_name === selectedFundName)
    return idx >= 0 ? idx : 0
  }, [managers.data, selectedCik, selectedFundName])

  if (!ticker) {
    return <div style={CENTER_MSG}><span style={{ color: 'var(--text-dim)' }}>Enter a ticker to load fund portfolios</span></div>
  }

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', backgroundColor: 'var(--panel)', borderRadius: 0, boxShadow: '0 1px 2px rgba(0,0,0,0.04)', overflow: 'hidden' }}>
      {/* Header row: PageHeader (left) + FreshnessBadge + ExportBar (right) */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', padding: '0 12px', flexShrink: 0 }}>
        <div style={{ flex: 1 }}>
          <PageHeader
            section="Ownership"
            title="Fund Portfolio"
            description="Individual fund holdings for any active institutional holder. Select a manager to view positions."
          />
        </div>
        <div className="no-print" style={{ display: 'flex', alignItems: 'center', gap: 10, paddingTop: 14 }}>
          <FreshnessBadge tableName="fund_holdings_v2" label="N-PORT" />
          <ExportBar onExcel={onExcel} onPrint={() => window.print()} disabled={!portfolio.data} />
        </div>
      </div>
      <style>{`
        @media print { .fp-controls { display:none!important } .no-print { display:none!important } .fp-wrap { height:auto!important; overflow:visible!important } }
        .fp-ticker-link:hover { text-decoration: underline; }
      `}</style>

      {/* Controls bar */}
      <div className="fp-controls" style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 12, padding: '10px 12px', backgroundColor: 'var(--panel)', border: '1px solid var(--line)', borderRadius: 0, margin: '0 12px', flexShrink: 0 }}>
        <select
          value={selectedIdx}
          onChange={onManagerChange}
          disabled={!managers.data || managers.data.length === 0}
          style={{
            flex: 1, padding: '6px 10px', fontSize: 13, color: 'var(--text)',
            backgroundColor: 'var(--bg)', border: '1px solid var(--line)',
            borderRadius: 0, outline: 'none',
          }}
        >
          {managers.loading && <option>Loading managers…</option>}
          {managers.data && managers.data.length === 0 && (
            <option>No active managers found for {ticker}</option>
          )}
          {managers.data && managers.data.map((m, i) => (
            <option key={`${m.cik}:${m.fund_name}`} value={i}>
              {m.fund_name} — {m.inst_parent_name} ({m.manager_type})
            </option>
          ))}
        </select>
      </div>

      {/* Content */}
      <div className="fp-wrap" style={{ flex: 1, overflowY: 'auto', overflowX: 'auto', position: 'relative' }}>
        {portfolio.loading && <div style={{ ...CENTER_MSG, color: 'var(--text-dim)' }}>Loading portfolio…</div>}
        {!portfolio.loading && !portfolio.data && !portfolio.error && (
          <div style={{ ...CENTER_MSG, color: 'var(--text-dim)' }}>Select a manager to view their portfolio</div>
        )}
        {portfolio.error && !portfolio.loading && (
          <div style={{ ...CENTER_MSG, color: 'var(--neg)' }}>Error: {portfolio.error}</div>
        )}
        {portfolio.data && !portfolio.loading && (
          <div style={{ padding: 16 }}>
            {/* Stats card */}
            <StatsCard stats={portfolio.data.stats} />

            {/* Table */}
            <table style={{ width: '100%', borderCollapse: 'separate', borderSpacing: 0, tableLayout: 'fixed', fontSize: 13 }}>
              <colgroup>
                <col style={{ width: 44 }} />   {/* Rank */}
                <col style={{ width: 72 }} />   {/* Ticker */}
                <col />                          {/* Company — flex */}
                <col style={{ width: 130 }} />  {/* Sector */}
                <col style={{ width: 90 }} />   {/* Shares */}
                <col style={{ width: 90 }} />   {/* Value */}
                <col style={{ width: 80 }} />   {/* % Portfolio */}
                <col style={{ width: 72 }} />   {/* % SO */}
              </colgroup>
              <thead>
                <tr>
                  <th style={TH_R}>Rank</th>
                  <th style={TH}>Ticker</th>
                  <th style={TH}>Company</th>
                  <th style={TH}>Sector</th>
                  <th style={TH_R}>Shares (MM)</th>
                  <th style={TH_R}>Value ($MM)</th>
                  <th style={TH_R}>% Portfolio</th>
                  <th style={TH_R}>% SO</th>
                </tr>
              </thead>
              <tbody>
                {portfolio.data.positions.map(p => {
                  const isSubject = ticker && p.ticker === ticker.toUpperCase()
                  const rowBg: React.CSSProperties = isSubject
                    ? { backgroundColor: 'rgba(197,162,84,0.12)' }
                    : {}
                  const canNav = !!p.ticker && !isSubject
                  return (
                    <tr key={p.rank} style={rowBg}>
                      <td style={{ ...TD, textAlign: 'right', fontWeight: 700, color: 'var(--text-dim)' }}>{p.rank}</td>
                      <td
                        style={{
                          ...TD,
                          fontWeight: isSubject ? 700 : 600,
                          color: 'var(--gold)',
                          cursor: canNav ? 'pointer' : 'default',
                        }}
                        className={canNav ? 'fp-ticker-link' : undefined}
                        title={canNav ? `Open Register for ${p.ticker}` : undefined}
                        onClick={canNav ? () => navigateToRegister(p.ticker) : undefined}
                      >
                        {p.ticker}
                      </td>
                      <td style={{ ...TD, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: 0, fontWeight: isSubject ? 600 : 400 }} title={p.issuer_name || ''}>{p.issuer_name || '—'}</td>
                      <td style={{ ...TD, color: 'var(--text-dim)', fontSize: 12 }}>{p.sector || '—'}</td>
                      <td style={TD_R}>{fmtSharesMm(p.shares)}</td>
                      <td style={TD_R}>{fmtValueMm(p.market_value_live)}</td>
                      <td style={TD_R}>{fmtPct2(p.pct_of_portfolio)}</td>
                      <td style={TD_R}>{fmtPct2(p.pct_of_so)}</td>
                    </tr>
                  )
                })}
                {portfolio.data.positions.length === 0 && (
                  <tr><td colSpan={TOTAL_COLS} style={{ ...TD, textAlign: 'center', padding: 30, color: 'var(--text-dim)' }}>No positions found</td></tr>
                )}
              </tbody>
              <TableFooter totalColumns={TOTAL_COLS} rows={[{
                label: 'Total',
                shares_mm: totals.shares / 1e6,
                value_mm: totals.value / 1e6,
                pct_so: null,
              }]} />
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Stats card ──────────────────────────────────────────────────────────────

function StatsCard({ stats }: { stats: FundPortfolioResponse['stats'] }) {
  const ts = getTypeStyle(stats.manager_type)
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 24, padding: '12px 16px', backgroundColor: 'var(--panel)', border: '1px solid var(--line)', borderRadius: 0, marginBottom: 12, flexWrap: 'wrap' }}>
      <div>
        <span style={{ fontWeight: 700, fontSize: 15, color: 'var(--text)' }}>{stats.manager_name}</span>
        <span style={{ ...BADGE, backgroundColor: ts.bg, color: ts.color, marginLeft: 10 }}>{ts.label}</span>
      </div>
      <MetricTile label="Total Value" value={fmtValueMm(stats.total_value)} />
      <MetricTile label="Positions" value={String(stats.num_positions)} />
      <MetricTile label="Top 10 Conc." value={`${stats.top10_concentration_pct.toFixed(2)}%`} />
    </div>
  )
}

function MetricTile({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div style={{ fontSize: 10, fontWeight: 600, textTransform: 'uppercase', color: 'var(--text-dim)', letterSpacing: '0.08em', marginBottom: 2 }}>{label}</div>
      <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text)' }}>{value}</div>
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
