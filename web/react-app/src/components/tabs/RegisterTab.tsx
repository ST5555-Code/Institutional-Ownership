import { useMemo, useState } from 'react'
import { useAppStore } from '../../store/useAppStore'
import { useFetch } from '../../hooks/useFetch'
import type { RegisterResponse, RegisterRow } from '../../types/api'
import {
  QuarterSelector,
  RollupToggle,
  FundViewToggle,
  ActiveOnlyToggle,
  InvestorTypeFilter,
  InvestorSearch,
  ExportBar,
  TableFooter,
  ColumnGroupHeader,
} from '../common'

// ── Formatters ─────────────────────────────────────────────────────────────

const NUM_0 = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 })
const NUM_1 = new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 })
const NUM_2 = new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 })

// All per-column formatters per spec:
//  Shares (MM): 2 decimals, no suffix     — value_live/1e6
//  Value ($MM): comma-sep, 0 decimals     — value_live/1e6
//  % Float: 1 decimal
//  AUM ($MM): comma-sep, 0 decimals       — backend pre-divided to $M
//  % of AUM: 2 decimals
//  N-PORT Cov: rounded int %

function fmtSharesMm(v: number | null): string {
  if (v == null) return '—'
  return NUM_2.format(v / 1e6)
}

function fmtValueMm(v: number | null): string {
  if (v == null) return '—'
  return `$${NUM_0.format(v / 1e6)}`
}

function fmtAumMm(v: number | null): string {
  if (v == null) return '—'
  return `$${NUM_0.format(v)}`
}

function fmtPctFloat(v: number | null): string {
  if (v == null) return '—'
  return `${NUM_1.format(v)}%`
}

// Negative percentages render as "(2.30%)" in red per spec. Kept from the
// prior implementation — query1 data is non-negative today, so this is
// defensive formatting for future tabs that share the helper.
function PctCell({ v }: { v: number | null }) {
  if (v == null) return <>—</>
  if (v < 0)
    return (
      <span style={{ color: '#c0392b' }}>({NUM_2.format(Math.abs(v))}%)</span>
    )
  return <>{NUM_2.format(v)}%</>
}

// ── Badge styles ───────────────────────────────────────────────────────────

function typeBadgeStyle(type: string | null): React.CSSProperties {
  const t = (type || '').toLowerCase()
  if (t === 'passive') return { backgroundColor: '#4A90D9', color: '#ffffff' }
  if (t === 'active' || t === 'hedge_fund')
    return { backgroundColor: '#002147', color: '#ffffff' }
  return { backgroundColor: '#cbd5e1', color: '#1e293b' }
}

function nportBadgeStyle(cov: number | null): React.CSSProperties | null {
  if (cov == null || cov <= 0) return null
  if (cov >= 80) return { backgroundColor: '#27AE60', color: '#ffffff' }
  if (cov >= 50) return { backgroundColor: '#F5A623', color: '#ffffff' }
  return { backgroundColor: '#94a3b8', color: '#ffffff' }
}

// ── Shared inline styles ───────────────────────────────────────────────────

const TH_STYLE: React.CSSProperties = {
  padding: '9px 10px',
  fontSize: 11,
  fontWeight: 700,
  textTransform: 'uppercase',
  letterSpacing: '0.04em',
  color: '#ffffff',
  backgroundColor: 'var(--oxford-blue)',
  textAlign: 'left',
  borderBottom: '1px solid #1e2d47',
  whiteSpace: 'nowrap',
  position: 'sticky',
  top: 0,
  zIndex: 3,
}

const TH_RIGHT: React.CSSProperties = { ...TH_STYLE, textAlign: 'right' }

const TD_STYLE: React.CSSProperties = {
  padding: '7px 10px',
  fontSize: 13,
  color: '#1e293b',
  borderBottom: '1px solid #e5e7eb',
}

const TD_RIGHT: React.CSSProperties = {
  ...TD_STYLE,
  textAlign: 'right',
  fontVariantNumeric: 'tabular-nums',
}

const BADGE: React.CSSProperties = {
  display: 'inline-block',
  padding: '2px 8px',
  fontSize: 11,
  fontWeight: 600,
  borderRadius: 3,
  letterSpacing: '0.02em',
}

// ── Grouping logic ─────────────────────────────────────────────────────────

interface RegisterGroup {
  parent: RegisterRow
  children: RegisterRow[]
}

function groupRows(rows: RegisterRow[]): RegisterGroup[] {
  const groups: RegisterGroup[] = []
  for (const r of rows) {
    if (r.level === 0) groups.push({ parent: r, children: [] })
    else if (r.level === 1 && groups.length > 0)
      groups[groups.length - 1].children.push(r)
  }
  return groups
}

const QUARTERS = ['2025Q4', '2025Q3', '2025Q2', '2025Q1']

const TOTAL_COLS = 9

// ── Component ──────────────────────────────────────────────────────────────

export function RegisterTab() {
  const { ticker, quarter, setQuarter, rollupType } = useAppStore()

  // Local UI state
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [activeOnly, setActiveOnly] = useState(false)
  const [fundView, setFundView] = useState<'hierarchy' | 'fund'>('hierarchy')
  const [search, setSearch] = useState('')
  // `selectedTypes` is null until we've seen a response — then it becomes
  // the full set of types present in the data. `null` = "all selected, show
  // everything" so the user doesn't see a flashing empty chip row.
  const [selectedTypes, setSelectedTypes] = useState<Set<string> | null>(null)

  // URL: rollup_type is the only param query1 actually honors today. The
  // quarter selector is cosmetic (see note below) but kept in the URL
  // string so Vite's HMR replays the fetch if/when the backend starts
  // accepting it without requiring a code edit here.
  const url = ticker
    ? `/api/query1?ticker=${encodeURIComponent(ticker)}&rollup_type=${rollupType}&quarter=${encodeURIComponent(quarter)}`
    : null
  const { data, loading, error } = useFetch<RegisterResponse>(url)

  // Available types derived from the parent rows of the current response.
  const availableTypes = useMemo(() => {
    if (!data) return [] as string[]
    const seen = new Set<string>()
    for (const r of data.rows) {
      if (r.level === 0 && r.type) seen.add(r.type)
    }
    return Array.from(seen).sort()
  }, [data])

  // Reset the type-filter selection to "everything" whenever the set of
  // available types changes (new ticker, new rollup). The first render
  // after a fetch will see `selectedTypes === null` and treat it as all.
  const effectiveSelectedTypes = selectedTypes ?? new Set(availableTypes)

  // ── Grouping + filtering ─────────────────────────────────────────────────
  //
  // 1. Group flat rows into {parent, children}
  // 2. Drop parent groups whose type is not in the selected-types set
  // 3. If activeOnly: drop parent groups where type === 'passive'
  // 4. If search: drop parent groups whose institution doesn't contain text
  // 5. In fund view: flatten to child rows, re-rank, drop parents entirely.
  //    Child rows inherit the parent filter decisions from step 2-4 — i.e.
  //    children of a passive parent are hidden under activeOnly even though
  //    the child row itself might have a different `type`.

  const groups = useMemo(() => {
    if (!data) return []
    const all = groupRows(data.rows)
    const q = search.trim().toLowerCase()
    return all.filter((g) => {
      const t = (g.parent.type || '').toLowerCase()
      if (effectiveSelectedTypes.size > 0 && !effectiveSelectedTypes.has(t)) {
        return false
      }
      if (activeOnly && t === 'passive') return false
      if (q && !(g.parent.institution || '').toLowerCase().includes(q)) {
        return false
      }
      return true
    })
  }, [data, activeOnly, search, effectiveSelectedTypes])

  // Fund-view rows: flatten children from filtered groups, sort by
  // value_live desc, re-rank 1..N.
  const fundRows = useMemo(() => {
    if (fundView !== 'fund') return [] as RegisterRow[]
    const flat: RegisterRow[] = []
    for (const g of groups) {
      for (const c of g.children) flat.push(c)
    }
    flat.sort((a, b) => (b.value_live || 0) - (a.value_live || 0))
    return flat.map((r, i) => ({ ...r, rank: i + 1 }))
  }, [groups, fundView])

  // ── Footer totals ────────────────────────────────────────────────────────
  // `visibleRows` in the spec means post-filter, so we sum what the user
  // actually sees. In hierarchy view that's the parent rows; in fund view
  // that's the flat child rows.

  const visibleSums = useMemo(() => {
    const rows: RegisterRow[] =
      fundView === 'fund' ? fundRows : groups.map((g) => g.parent)
    let shares = 0
    let valueLive = 0
    let pctFloat = 0
    for (const r of rows) {
      shares += r.shares || 0
      valueLive += r.value_live || 0
      pctFloat += r.pct_float || 0
    }
    return { count: rows.length, shares, valueLive, pctFloat }
  }, [groups, fundRows, fundView])

  // ── Handlers ─────────────────────────────────────────────────────────────

  function toggle(key: string) {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  function onExcel() {
    // CSV export of the currently-visible rows (post-filter, post-view).
    // Tracking ticket for real .xlsx export if the user wants it later.
    const header = [
      'Rank',
      'Institution',
      'Type',
      'Shares (MM)',
      'Value ($MM)',
      '% Float',
      'AUM ($MM)',
      '% of AUM',
      'N-PORT Cov',
    ]
    const rows: RegisterRow[] =
      fundView === 'fund'
        ? fundRows
        : groups.flatMap((g) =>
            expanded.has(groupKey(g.parent))
              ? [g.parent, ...g.children]
              : [g.parent],
          )
    const csvRows = rows.map((r) => [
      r.rank,
      `"${(r.institution || '').replace(/"/g, '""')}"`,
      r.type || '',
      r.shares != null ? (r.shares / 1e6).toFixed(2) : '',
      r.value_live != null ? (r.value_live / 1e6).toFixed(0) : '',
      r.pct_float != null ? r.pct_float.toFixed(1) : '',
      r.aum != null ? r.aum.toFixed(0) : '',
      r.pct_aum != null ? r.pct_aum.toFixed(2) : '',
      r.nport_cov != null ? Math.round(r.nport_cov) : '',
    ])
    const csv = [header, ...csvRows].map((row) => row.join(',')).join('\n')
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `register_${ticker}_${quarter}.csv`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  function onPrint() {
    window.print()
  }

  // ── Early returns ────────────────────────────────────────────────────────

  if (!ticker) {
    return (
      <div style={CENTER_MSG}>
        <span style={{ color: '#94a3b8' }}>
          Enter a ticker to load the register
        </span>
      </div>
    )
  }

  // ── Render ───────────────────────────────────────────────────────────────

  return (
    <div
      style={{
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        backgroundColor: 'var(--card-bg)',
        borderRadius: 6,
        boxShadow: '0 1px 2px rgba(0,0,0,0.04)',
        overflow: 'hidden',
      }}
    >
      {/* Print CSS — hide controls, keep the table */}
      <style>{`
        @media print {
          .register-controls-bar { display: none !important; }
          .register-tab-container { height: auto !important; overflow: visible !important; }
          .register-table-wrap { overflow: visible !important; }
        }
      `}</style>

      {/* Controls bar */}
      <div
        className="register-controls-bar"
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          alignItems: 'flex-end',
          gap: 16,
          padding: '12px 16px',
          backgroundColor: '#f8fafc',
          borderBottom: '1px solid #e2e8f0',
          flexShrink: 0,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <QuarterSelector
            quarters={QUARTERS}
            value={quarter}
            onChange={setQuarter}
          />
          <span
            title="Quarter selector takes effect on tabs that support it"
            style={{
              cursor: 'help',
              color: '#94a3b8',
              fontSize: 14,
              userSelect: 'none',
            }}
          >
            ⓘ
          </span>
        </div>
        <RollupToggle />
        <FundViewToggle value={fundView} onChange={setFundView} />
        <ActiveOnlyToggle
          value={activeOnly}
          onChange={setActiveOnly}
          label="Active Only"
        />
        {availableTypes.length > 0 && (
          <InvestorTypeFilter
            available={availableTypes}
            selected={effectiveSelectedTypes}
            onChange={setSelectedTypes}
          />
        )}
        <InvestorSearch value={search} onChange={setSearch} />
        <div style={{ marginLeft: 'auto' }}>
          <ExportBar onExcel={onExcel} onPrint={onPrint} disabled={!data} />
        </div>
      </div>

      {/* Table container */}
      <div
        className="register-table-wrap"
        style={{
          flex: 1,
          overflowY: 'auto',
          position: 'relative',
        }}
      >
        {loading && (
          <div style={{ ...CENTER_MSG, color: '#94a3b8' }}>Loading…</div>
        )}
        {error && !loading && (
          <div style={{ ...CENTER_MSG, color: '#ef4444' }}>Error: {error}</div>
        )}
        {data && !loading && (
          <table
            style={{
              width: '100%',
              borderCollapse: 'separate',
              borderSpacing: 0,
              fontSize: 13,
            }}
          >
            <thead>
              <ColumnGroupHeader
                groups={[
                  { label: '', colSpan: 6 },
                  { label: 'Investor', colSpan: 3 },
                ]}
              />
              <tr>
                <th style={{ ...TH_RIGHT, width: 60 }}>Rank</th>
                <th style={TH_STYLE}>Institution</th>
                <th style={TH_STYLE}>Type</th>
                <th style={TH_RIGHT}>Shares (MM)</th>
                <th style={TH_RIGHT}>Value ($MM)</th>
                <th style={TH_RIGHT}>% Float</th>
                <th style={TH_RIGHT}>AUM ($MM)</th>
                <th style={TH_RIGHT}>% of AUM</th>
                <th style={TH_STYLE}>N-PORT Cov</th>
              </tr>
            </thead>
            <tbody>
              {fundView === 'fund'
                ? fundRows.map((r) => renderRow(r, `f:${r.rank}`, 0, false, false, toggle))
                : groups.flatMap((g) => {
                    const pkey = groupKey(g.parent)
                    const canExpand = g.children.length >= 2
                    const isOpen = expanded.has(pkey)
                    const trs = [
                      renderRow(g.parent, pkey, 0, canExpand, isOpen, toggle),
                    ]
                    if (isOpen) {
                      g.children.forEach((c, ci) => {
                        trs.push(
                          renderRow(
                            c,
                            `${pkey}:${ci}`,
                            1,
                            false,
                            false,
                            toggle,
                            `${g.parent.rank}${String.fromCharCode(97 + ci)}`,
                          ),
                        )
                      })
                    }
                    return trs
                  })}
              {(fundView === 'fund' ? fundRows.length : groups.length) === 0 && (
                <tr>
                  <td
                    colSpan={TOTAL_COLS}
                    style={{
                      ...TD_STYLE,
                      textAlign: 'center',
                      padding: '30px 10px',
                      color: '#64748b',
                    }}
                  >
                    No rows match the current filters
                  </td>
                </tr>
              )}
            </tbody>
            <TableFooter
              totalColumns={TOTAL_COLS}
              rows={[
                {
                  label: `Top ${visibleSums.count} Shown`,
                  shares_mm: visibleSums.shares / 1e6,
                  value_mm: visibleSums.valueLive / 1e6,
                  pct_float: visibleSums.pctFloat,
                },
                {
                  label: `All Holders (${data.all_totals.count})`,
                  shares_mm:
                    data.all_totals.shares != null
                      ? data.all_totals.shares / 1e6
                      : null,
                  value_mm:
                    data.all_totals.value_live != null
                      ? data.all_totals.value_live / 1e6
                      : null,
                  pct_float: data.all_totals.pct_float,
                },
              ]}
            />
          </table>
        )}
      </div>
    </div>
  )
}

// ── Helpers ──────────────────────────────────────────────────────────────

const CENTER_MSG: React.CSSProperties = {
  padding: 40,
  fontSize: 14,
  textAlign: 'center',
}

function groupKey(parent: RegisterRow): string {
  return `${parent.rank}:${parent.institution}`
}

// renderRow is a plain function (not a component) so it returns a <tr>
// suitable for direct insertion into <tbody>. `displayRank` overrides the
// rank label for child rows in hierarchy view (e.g. "1a", "1b").
function renderRow(
  row: RegisterRow,
  key: string,
  indent: 0 | 1,
  canExpand: boolean,
  isOpen: boolean,
  toggle: (k: string) => void,
  displayRank?: string,
) {
  const rowBg: React.CSSProperties = {
    backgroundColor: indent === 1 ? '#f8fafc' : '#ffffff',
  }
  const nameCell: React.CSSProperties = {
    ...TD_STYLE,
    paddingLeft: indent === 1 ? 28 : 10,
    fontWeight: indent === 0 ? 600 : 400,
    color: indent === 0 ? '#0f172a' : '#475569',
    fontSize: indent === 1 ? 12 : 13,
    cursor: canExpand ? 'pointer' : 'default',
    userSelect: 'none',
  }
  const nport = nportBadgeStyle(row.nport_cov)
  return (
    <tr key={key} style={rowBg}>
      <td
        style={{
          ...TD_STYLE,
          textAlign: 'right',
          fontWeight: indent === 0 ? 700 : 400,
          color: indent === 0 ? '#64748b' : '#94a3b8',
          fontSize: indent === 1 ? 11 : 13,
          width: 60,
        }}
      >
        {displayRank ?? row.rank}
      </td>
      <td
        style={nameCell}
        title={row.institution}
        onClick={canExpand ? () => toggle(key) : undefined}
      >
        {canExpand && (
          <span
            style={{
              display: 'inline-block',
              width: 14,
              color: '#64748b',
              fontSize: 10,
            }}
          >
            {isOpen ? '▼' : '▶'}
          </span>
        )}
        {row.institution}
        {row.subadviser_note && (
          <span
            style={{
              fontSize: 11,
              color: '#64748b',
              marginLeft: 6,
              fontStyle: 'italic',
            }}
          >
            ({row.subadviser_note})
          </span>
        )}
      </td>
      <td style={TD_STYLE}>
        <span style={{ ...BADGE, ...typeBadgeStyle(row.type) }}>
          {row.type || 'unknown'}
        </span>
      </td>
      <td style={TD_RIGHT}>{fmtSharesMm(row.shares)}</td>
      <td style={TD_RIGHT}>{fmtValueMm(row.value_live)}</td>
      <td style={TD_RIGHT}>{fmtPctFloat(row.pct_float)}</td>
      <td style={TD_RIGHT}>{fmtAumMm(row.aum)}</td>
      <td style={TD_RIGHT}>
        <PctCell v={row.pct_aum} />
      </td>
      <td style={TD_STYLE}>
        {nport && row.nport_cov != null ? (
          <span style={{ ...BADGE, ...nport }}>
            {Math.round(row.nport_cov)}%
          </span>
        ) : (
          '—'
        )}
      </td>
    </tr>
  )
}
