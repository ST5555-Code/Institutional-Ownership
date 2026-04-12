import { useEffect, useMemo, useRef, useState } from 'react'
import { useAppStore } from '../../store/useAppStore'
import { useFetch } from '../../hooks/useFetch'
import type { RegisterResponse, RegisterRow } from '../../types/api'
import {
  QuarterSelector,
  RollupToggle,
  FundViewToggle,
  ActiveOnlyToggle,
  InvestorTypeFilter,
  ExportBar,
  TableFooter,
  ColumnGroupHeader,
} from '../common'

// ── Formatters ─────────────────────────────────────────────────────────────

const NUM_0 = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 })
const NUM_1 = new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 })
const NUM_2 = new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 })

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

// Defensive negative-percentage formatter kept from the prior file — query1
// doesn't return negatives today but this helper is handy for other tabs.
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

// Fund-view rows carry the parent institution alongside the child data so
// that Investor Search can filter fund rows by their owning parent.
interface FundViewRow extends RegisterRow {
  parentInstitution: string
}

const QUARTERS = ['2025Q4', '2025Q3', '2025Q2', '2025Q1']

// Column layout (12 cols):
//   1  Rank
//   2  Institution
//   3  Type
//   4  (empty spacer — pushes Shares/Value/%Float right by one Type-width)
//   5  Shares (MM)
//   6  Value ($MM)
//   7  % Float
//   8  (empty spacer — pushes AUM / % AUM / Port. Coverage further right)
//   9  AUM ($MM)
//  10  % of AUM
//  11  Port. Coverage
//  12  Trailing spacer (flex — absorbs remainder on wide viewports)
const TOTAL_COLS = 12

// ── InvestorSearchWithDropdown ────────────────────────────────────────────
// Local to this file per spec — the shared common/InvestorSearch stays a
// simple text input for other tabs. This variant adds a typeahead dropdown
// keyed off the response's parent rows (level=0), click-outside-to-close,
// and a × clear control that fires onSelect(null).

interface SearchProps {
  data: RegisterRow[]
  onSelect: (institution: string | null) => void
}

function InvestorSearchWithDropdown({ data, onSelect }: SearchProps) {
  const [value, setValue] = useState('')
  const [open, setOpen] = useState(false)
  const [focused, setFocused] = useState(false)
  const wrapRef = useRef<HTMLDivElement>(null)

  const matches = useMemo(() => {
    if (value.length < 1) return [] as RegisterRow[]
    const q = value.toLowerCase()
    return data
      .filter((r) => r.level === 0 && r.institution.toLowerCase().includes(q))
      .slice(0, 10)
  }, [data, value])

  useEffect(() => {
    function handleMouseDown(e: MouseEvent) {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handleMouseDown)
    return () => document.removeEventListener('mousedown', handleMouseDown)
  }, [])

  function select(institution: string) {
    setValue(institution)
    setOpen(false)
    onSelect(institution)
  }

  function clear() {
    setValue('')
    setOpen(false)
    onSelect(null)
  }

  return (
    <div
      ref={wrapRef}
      style={{ position: 'relative', display: 'inline-block' }}
    >
      <input
        type="text"
        value={value}
        placeholder="Search investor…"
        autoComplete="off"
        autoCorrect="off"
        spellCheck={false}
        onChange={(e) => {
          const v = e.target.value
          setValue(v)
          setOpen(v.length > 0)
        }}
        onFocus={() => {
          setFocused(true)
          if (value.length > 0) setOpen(true)
        }}
        onBlur={() => setFocused(false)}
        style={{
          width: 200,
          padding: '6px 28px 6px 10px',
          fontSize: 13,
          color: '#1e293b',
          backgroundColor: '#ffffff',
          border: `1px solid ${focused ? 'var(--glacier-blue)' : '#e2e8f0'}`,
          borderRadius: 4,
          outline: 'none',
          transition: 'border-color 0.1s',
        }}
      />
      {value && (
        <button
          type="button"
          onClick={clear}
          aria-label="Clear search"
          style={{
            position: 'absolute',
            right: 6,
            top: '50%',
            transform: 'translateY(-50%)',
            width: 18,
            height: 18,
            padding: 0,
            lineHeight: '16px',
            fontSize: 14,
            color: '#94a3b8',
            backgroundColor: 'transparent',
            border: 'none',
            cursor: 'pointer',
          }}
        >
          ×
        </button>
      )}
      {open && matches.length > 0 && (
        <div
          style={{
            position: 'absolute',
            top: '100%',
            left: 0,
            marginTop: 2,
            width: 280,
            maxHeight: 240,
            overflowY: 'auto',
            backgroundColor: '#ffffff',
            border: '1px solid #e2e8f0',
            borderRadius: 4,
            boxShadow: '0 4px 12px rgba(0,0,0,0.08)',
            zIndex: 1000,
          }}
        >
          {matches.map((m) => (
            <div
              key={m.institution}
              // onMouseDown fires before the input's blur handler — without
              // this the click would close the dropdown before selecting.
              onMouseDown={() => select(m.institution)}
              style={{
                padding: '7px 12px',
                fontSize: 13,
                color: '#1e293b',
                cursor: 'pointer',
              }}
              onMouseEnter={(e) =>
                (e.currentTarget.style.backgroundColor = '#f4f6f9')
              }
              onMouseLeave={(e) =>
                (e.currentTarget.style.backgroundColor = 'transparent')
              }
            >
              {m.institution}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Component ──────────────────────────────────────────────────────────────

export function RegisterTab() {
  const { ticker, quarter, setQuarter, rollupType } = useAppStore()

  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [activeOnly, setActiveOnly] = useState(false)
  const [fundView, setFundView] = useState<'hierarchy' | 'fund'>('hierarchy')
  const [selectedTypes, setSelectedTypes] = useState<Set<string> | null>(null)
  // Search-selection state: when non-null in fund view, filters fund rows
  // to those owned by this parent institution. In hierarchy view it's
  // only used to scroll/highlight — the list is not filtered.
  const [selectedInstitution, setSelectedInstitution] = useState<string | null>(
    null,
  )
  // Controls the Port. Coverage column-header tooltip. Lives at component
  // level so re-renders caused by other state changes don't wipe it.
  const [portTooltipOpen, setPortTooltipOpen] = useState(false)

  const tableWrapRef = useRef<HTMLDivElement>(null)

  const url = ticker
    ? `/api/query1?ticker=${encodeURIComponent(ticker)}&rollup_type=${rollupType}&quarter=${encodeURIComponent(quarter)}`
    : null
  const { data, loading, error } = useFetch<RegisterResponse>(url)

  // Clear the search selection whenever the ticker/rollup changes, so a
  // stale highlight doesn't get re-applied to a completely different
  // response.
  useEffect(() => {
    setSelectedInstitution(null)
  }, [ticker, rollupType])

  // Available types derived from parent rows in the current response.
  const availableTypes = useMemo(() => {
    if (!data) return [] as string[]
    const seen = new Set<string>()
    for (const r of data.rows) {
      if (r.level === 0 && r.type) seen.add(r.type)
    }
    return Array.from(seen).sort()
  }, [data])

  const effectiveSelectedTypes = selectedTypes ?? new Set(availableTypes)

  // Filter-pipeline for the parent-level groups. Child rows inherit their
  // parent's pass/fail decision in hierarchy view.
  const groups = useMemo(() => {
    if (!data) return []
    const all = groupRows(data.rows)
    return all.filter((g) => {
      const t = (g.parent.type || '').toLowerCase()
      if (effectiveSelectedTypes.size > 0 && !effectiveSelectedTypes.has(t)) {
        return false
      }
      if (activeOnly && t === 'passive') return false
      return true
    })
  }, [data, activeOnly, effectiveSelectedTypes])

  // Flatten children from the filtered groups for fund view, carry their
  // parent institution, sort by value_live desc, re-rank 1..N.
  const fundRows = useMemo<FundViewRow[]>(() => {
    if (fundView !== 'fund') return []
    const flat: FundViewRow[] = []
    for (const g of groups) {
      for (const c of g.children) {
        flat.push({ ...c, parentInstitution: g.parent.institution })
      }
    }
    flat.sort((a, b) => (b.value_live || 0) - (a.value_live || 0))
    return flat.map((r, i) => ({ ...r, rank: i + 1 }))
  }, [groups, fundView])

  // Fund-view search filter: only applied when the user has picked a
  // specific investor from the dropdown while in fund view.
  const fundRowsDisplay = useMemo<FundViewRow[]>(() => {
    if (fundView !== 'fund' || selectedInstitution == null) return fundRows
    return fundRows.filter(
      (r) => r.parentInstitution === selectedInstitution,
    )
  }, [fundRows, fundView, selectedInstitution])

  // Totals footer sums the rows the user actually sees (post-filter).
  const visibleSums = useMemo(() => {
    const rows: RegisterRow[] =
      fundView === 'fund' ? fundRowsDisplay : groups.map((g) => g.parent)
    let shares = 0
    let valueLive = 0
    let pctFloat = 0
    for (const r of rows) {
      shares += r.shares || 0
      valueLive += r.value_live || 0
      pctFloat += r.pct_float || 0
    }
    return { count: rows.length, shares, valueLive, pctFloat }
  }, [groups, fundRowsDisplay, fundView])

  function toggle(key: string) {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  // ── Search selection handler ─────────────────────────────────────────────
  // In hierarchy view: scroll the matching parent row into the viewport and
  // apply a 2-second pale-gold highlight. The highlight uses a CSS class
  // (defined in the <style> block below) rather than inline style so React's
  // reconciler can't stomp it mid-fade if the component re-renders.
  //
  // In fund view: set state so fundRowsDisplay filters to the matching
  // parent's fund series. The list contracts, no scroll/highlight needed.

  function handleSearchSelect(institution: string | null) {
    setSelectedInstitution(institution)
    if (institution == null) return
    if (fundView === 'fund') return
    requestAnimationFrame(() => {
      const wrap = tableWrapRef.current
      if (!wrap) return
      const escaped = institution.replace(/"/g, '\\"')
      const el = wrap.querySelector(
        `tr[data-institution="${escaped}"]`,
      ) as HTMLElement | null
      if (!el) return
      el.scrollIntoView({ behavior: 'smooth', block: 'center' })
      el.classList.add('register-row-highlight')
      window.setTimeout(() => {
        el.classList.remove('register-row-highlight')
      }, 2000)
    })
  }

  // ── Export handlers ──────────────────────────────────────────────────────

  function onExcel() {
    const header = [
      'Rank',
      'Institution',
      'Type',
      'Shares (MM)',
      'Value ($MM)',
      '% Float',
      'AUM ($MM)',
      '% of AUM',
      'Port. Coverage',
    ]
    const rows: RegisterRow[] =
      fundView === 'fund'
        ? fundRowsDisplay
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
    const dlUrl = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = dlUrl
    a.download = `register_${ticker}_${quarter}.csv`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(dlUrl)
  }

  function onPrint() {
    window.print()
  }

  // ── Early return ─────────────────────────────────────────────────────────

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
      className="register-tab-container"
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
      {/* Print CSS + highlight class. !important on the highlight so it
          survives mid-fade React re-renders that would otherwise restore
          the row's inline backgroundColor. */}
      <style>{`
        @media print {
          .register-controls-bar { display: none !important; }
          .register-tab-container { height: auto !important; overflow: visible !important; }
          .register-table-wrap { overflow: visible !important; }
        }
        .register-row-highlight > td {
          background-color: #fffbeb !important;
          transition: background-color 0.4s ease-in-out;
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
        <InvestorSearchWithDropdown
          data={data?.rows ?? []}
          onSelect={handleSearchSelect}
        />
        <div style={{ marginLeft: 'auto' }}>
          <ExportBar onExcel={onExcel} onPrint={onPrint} disabled={!data} />
        </div>
      </div>

      {/* Table container */}
      <div
        ref={tableWrapRef}
        className="register-table-wrap"
        style={{
          flex: 1,
          overflowY: 'auto',
          // Safety scroll when the nine fixed-width data columns
          // overflow a narrow viewport. On wide viewports the spacer
          // col soaks up the slack and no horizontal scroll appears.
          overflowX: 'auto',
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
              // Fixed layout: columns are sized from <colgroup> below and
              // ignore body-cell content width. This is what keeps the
              // Institution column from expanding when Fund view swaps in
              // long fund-series names.
              tableLayout: 'fixed',
            }}
          >
            <colgroup>
              <col style={{ width: 60 }} />
              {/* Institution: fixed at 440 so it doesn't balloon on Fund
                  view and gives enough room for most parent names. */}
              <col style={{ width: 440 }} />
              <col style={{ width: 120 }} /> {/* Type */}
              <col style={{ width: 120 }} /> {/* empty gap 1 */}
              <col style={{ width: 120 }} /> {/* Shares */}
              <col style={{ width: 120 }} /> {/* Value */}
              <col style={{ width: 120 }} /> {/* % Float */}
              <col style={{ width: 120 }} /> {/* empty gap 2 */}
              <col style={{ width: 120 }} /> {/* AUM */}
              <col style={{ width: 120 }} /> {/* % of AUM */}
              <col style={{ width: 120 }} /> {/* Port. Coverage */}
              {/* Trailing spacer: absorbs remainder on wide viewports. */}
              <col />
            </colgroup>
            <thead>
              <ColumnGroupHeader
                groups={[
                  // cols 1-8: Rank, Inst, Type, gap, Shares, Value, %F, gap
                  { label: '', colSpan: 8 },
                  // cols 9-11: AUM, % AUM, Port. Coverage
                  { label: 'Investor', colSpan: 3 },
                  // col 12: trailing spacer
                  { label: '', colSpan: 1 },
                ]}
              />
              <tr>
                <th style={TH_RIGHT}>Rank</th>
                <th style={TH_STYLE}>Institution</th>
                <th style={TH_STYLE}>Type</th>
                <th style={TH_STYLE} />
                <th style={TH_RIGHT}>Shares (MM)</th>
                <th style={TH_RIGHT}>Value ($MM)</th>
                <th style={TH_RIGHT}>% Float</th>
                <th style={TH_STYLE} />
                <th style={TH_RIGHT}>AUM ($MM)</th>
                <th style={TH_RIGHT}>% of AUM</th>
                <th
                  style={TH_STYLE}
                  onMouseEnter={() => setPortTooltipOpen(true)}
                  onMouseLeave={() => setPortTooltipOpen(false)}
                >
                  {/* Inner relatively-positioned wrapper so the absolute
                      tooltip has an unambiguous containing block (avoids
                      any browser-specific quirks around position:sticky
                      as a positioning context). */}
                  <span
                    style={{ position: 'relative', display: 'inline-block' }}
                  >
                    Port. Coverage
                    {portTooltipOpen && (
                      <span
                        style={{
                          position: 'absolute',
                          top: '100%',
                          left: '50%',
                          transform: 'translateX(-50%)',
                          zIndex: 1000,
                          marginTop: 4,
                          backgroundColor: '#0d1526',
                          color: '#e2e8f0',
                          fontSize: 11,
                          lineHeight: 1.6,
                          padding: '8px 12px',
                          borderRadius: 4,
                          border: '1px solid #2d3f5e',
                          width: 200,
                          whiteSpace: 'pre-line',
                          textAlign: 'left',
                          fontWeight: 400,
                          textTransform: 'none',
                          letterSpacing: 0,
                          display: 'block',
                        }}
                      >
                        <span
                          style={{
                            display: 'block',
                            fontWeight: 600,
                            marginBottom: 4,
                          }}
                        >
                          Port. Coverage — % of AUM visible in N-PORT filings
                        </span>
                        <span style={{ display: 'block' }}>
                          <span style={{ color: '#27AE60' }}>■</span>
                          {' Green   ≥ 80%  High confidence'}
                        </span>
                        <span style={{ display: 'block' }}>
                          <span style={{ color: '#F5A623' }}>■</span>
                          {' Amber  50–79%  Partial coverage'}
                        </span>
                        <span style={{ display: 'block' }}>
                          <span style={{ color: '#94a3b8' }}>■</span>
                          {' Grey     1–49%  Low coverage'}
                        </span>
                        <span
                          style={{ display: 'block', color: '#94a3b8' }}
                        >
                          {'  No badge   No N-PORT data'}
                        </span>
                      </span>
                    )}
                  </span>
                </th>
                {/* Trailing spacer — absorbs horizontal slack so the
                    nine data columns are pinned to their specified
                    widths and don't stretch on wide viewports. */}
                <th style={TH_STYLE} />
              </tr>
            </thead>
            <tbody>
              {fundView === 'fund'
                ? fundRowsDisplay.map((r) =>
                    renderRow(r, `f:${r.rank}`, 0, false, false, toggle),
                  )
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
                            String(ci + 1),
                          ),
                        )
                      })
                    }
                    return trs
                  })}
              {(fundView === 'fund'
                ? fundRowsDisplay.length
                : groups.length) === 0 && (
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
              skipBeforeNumbers={1}
              skipAfterNumbers={1}
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

// renderRow returns a <tr>. `displayRank` overrides the rank column for
// child rows (fix 2: 1, 2, 3... not 1a, 1b, 1c). Parent rows get a
// data-institution attribute so the search highlight handler can find
// them via querySelector.
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
    paddingLeft: indent === 1 ? 24 : 10,
    fontWeight: indent === 0 ? 600 : 400,
    color: indent === 0 ? '#0f172a' : '#475569',
    fontSize: indent === 1 ? 12 : 13,
    cursor: canExpand ? 'pointer' : 'default',
    userSelect: 'none',
    // Long fund-series names must truncate with ellipsis instead of
    // wrapping or expanding the column. The title attribute below
    // surfaces the full name on hover.
    whiteSpace: 'nowrap',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    maxWidth: 0,
  }
  const nport = nportBadgeStyle(row.nport_cov)
  return (
    <tr
      key={key}
      style={rowBg}
      data-institution={indent === 0 ? row.institution : undefined}
    >
      <td
        style={{
          ...TD_STYLE,
          textAlign: 'right',
          fontWeight: indent === 0 ? 700 : 400,
          color: indent === 0 ? '#64748b' : '#94a3b8',
          fontSize: indent === 1 ? 12 : 13,
        }}
      >
        {displayRank ?? row.rank}
      </td>
      <td
        style={nameCell}
        title={row.institution}
        onClick={canExpand ? () => toggle(key) : undefined}
      >
        {/* Caret slot — always reserved for indent=0 rows so fund view,
            hierarchy-expanded parents, and single-child parents all align
            institution text at the same offset. Empty content when the
            row can't expand; a real arrow when it can. Child rows
            (indent=1) don't get this slot — they rely on paddingLeft:24
            to land text at the same offset. */}
        {indent === 0 && (
          <span
            style={{
              display: 'inline-block',
              width: 14,
              color: '#64748b',
              fontSize: 10,
            }}
          >
            {canExpand ? (isOpen ? '▼' : '▶') : ''}
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
      {/* Gap 1: pushes Shares/Value/%Float one Type-width to the right. */}
      <td style={TD_STYLE} />
      <td style={TD_RIGHT}>{fmtSharesMm(row.shares)}</td>
      <td style={TD_RIGHT}>{fmtValueMm(row.value_live)}</td>
      <td style={TD_RIGHT}>{fmtPctFloat(row.pct_float)}</td>
      {/* Gap 2: pushes AUM / %AUM / Port. Coverage one more to the right. */}
      <td style={TD_STYLE} />
      <td style={TD_RIGHT}>{fmtAumMm(row.aum)}</td>
      <td style={TD_RIGHT}>
        <PctCell v={row.pct_aum} />
      </td>
      <td style={TD_STYLE}>
        {nport && row.nport_cov != null ? (
          <span
            style={{
              ...BADGE,
              ...nport,
              display: 'inline-block',
              minWidth: 48,
              textAlign: 'center',
            }}
          >
            {Math.round(row.nport_cov)}%
          </span>
        ) : (
          '—'
        )}
      </td>
      {/* Trailing spacer cell — matches the <col /> at the end of the
          colgroup so the nine data columns keep their specified widths. */}
      <td style={{ ...TD_STYLE, padding: 0, border: 'none' }} />
    </tr>
  )
}
