import { useMemo, useState } from 'react'
import { useAppStore } from '../../store/useAppStore'
import { useFetch } from '../../hooks/useFetch'
import type { RegisterResponse, RegisterRow } from '../../types/api'

// ── Formatters ─────────────────────────────────────────────────────────────

const NUM_0 = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 })
const NUM_1 = new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 })
const NUM_2 = new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 })

function formatShares(v: number | null): string {
  if (v == null) return '—'
  return `${NUM_2.format(v / 1e6)}M`
}

// Adaptive: $X.XXB if >=$1B, else $XXXM.
function formatValue(v: number | null): string {
  if (v == null) return '—'
  const sign = v < 0 ? '-' : ''
  const abs = Math.abs(v)
  if (abs >= 1e9) return `${sign}$${NUM_2.format(abs / 1e9)}B`
  return `${sign}$${NUM_0.format(abs / 1e6)}M`
}

// query1.aum is pre-converted to $M by the backend.
function formatAumMm(v: number | null): string {
  if (v == null) return '—'
  if (v >= 1000) return `$${NUM_1.format(v / 1000)}B`
  return `$${NUM_0.format(v)}M`
}

// Negative percentages render as "(2.30%)" in red per spec.
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
  if (t === 'passive')
    return { backgroundColor: '#4A90D9', color: '#ffffff' }
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
  fontSize: '11px',
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
}

const TD_STYLE: React.CSSProperties = {
  padding: '7px 10px',
  fontSize: '13px',
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
  fontSize: '11px',
  fontWeight: 600,
  borderRadius: 3,
  letterSpacing: '0.02em',
}

// ── Grouping logic ─────────────────────────────────────────────────────────
// query1 returns rows flat: [parent (level=0), child1 (level=1), child2, ...,
// parent (level=0), child1, ...]. is_parent=true only when has N-PORT kids.
// We group them here so the UI can collapse/expand each parent.

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

// ── Quarter selector ──────────────────────────────────────────────────────
// /api/query1 currently ignores the quarter param (hard-coded LATEST_QUARTER
// on the server). The selector is wired to useAppStore so that Phase-3 tabs
// can share it, but it's cosmetic on this tab until the backend accepts
// a quarter parameter. Flagged inline below the control row.

const QUARTERS = ['2025Q4', '2025Q3', '2025Q2', '2025Q1']

// ── Component ──────────────────────────────────────────────────────────────

export function RegisterTab() {
  const { ticker, quarter, setQuarter } = useAppStore()
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [activeOnly, setActiveOnly] = useState(false)

  const url = ticker ? `/api/query1?ticker=${encodeURIComponent(ticker)}` : null
  const { data, loading, error } = useFetch<RegisterResponse>(url)

  const groups = useMemo(() => {
    if (!data) return []
    const all = groupRows(data.rows)
    if (!activeOnly) return all
    return all.filter(
      (g) => (g.parent.type || '').toLowerCase() !== 'passive',
    )
  }, [data, activeOnly])

  function toggle(key: string) {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  if (!ticker) {
    return (
      <div style={{ padding: 40, color: '#64748b', fontSize: 14 }}>
        Type a ticker in the header to load the register.
      </div>
    )
  }

  return (
    <div
      style={{
        backgroundColor: 'var(--card-bg)',
        borderRadius: 6,
        padding: 16,
        boxShadow: '0 1px 2px rgba(0,0,0,0.04)',
      }}
    >
      {/* Controls */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 16,
          marginBottom: 12,
          flexWrap: 'wrap',
        }}
      >
        <div style={{ display: 'flex', gap: 4 }}>
          {QUARTERS.map((q) => (
            <button
              key={q}
              onClick={() => setQuarter(q)}
              style={{
                padding: '5px 11px',
                fontSize: 12,
                border: '1px solid #d1d5db',
                backgroundColor:
                  quarter === q ? 'var(--oxford-blue)' : '#ffffff',
                color: quarter === q ? '#ffffff' : '#334155',
                cursor: 'pointer',
                borderRadius: 3,
                fontWeight: quarter === q ? 600 : 400,
              }}
            >
              {q}
            </button>
          ))}
        </div>
        <label
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            fontSize: 13,
            color: '#334155',
            cursor: 'pointer',
          }}
        >
          <input
            type="checkbox"
            checked={activeOnly}
            onChange={(e) => setActiveOnly(e.target.checked)}
          />
          Active only
        </label>
        <span
          style={{
            fontSize: 11,
            color: '#94a3b8',
            fontStyle: 'italic',
          }}
        >
          Quarter selector is cosmetic — /api/query1 uses server latest
          quarter
        </span>
      </div>

      {loading && (
        <div style={{ color: '#64748b', padding: 20 }}>Loading register…</div>
      )}
      {error && (
        <div style={{ color: '#c0392b', padding: 20 }}>Error: {error}</div>
      )}

      {data && !loading && (
        <>
          <div style={{ overflowX: 'auto' }}>
            <table
              style={{
                width: '100%',
                borderCollapse: 'collapse',
                fontSize: 13,
              }}
            >
              <thead>
                <tr>
                  <th style={{ ...TH_STYLE, textAlign: 'right', width: 44 }}>
                    #
                  </th>
                  <th style={TH_STYLE}>Institution</th>
                  <th style={TH_STYLE}>Type</th>
                  <th style={{ ...TH_STYLE, textAlign: 'right' }}>Shares</th>
                  <th style={{ ...TH_STYLE, textAlign: 'right' }}>Value</th>
                  <th style={{ ...TH_STYLE, textAlign: 'right' }}>% Float</th>
                  <th style={{ ...TH_STYLE, textAlign: 'right' }}>
                    AUM ($M)
                  </th>
                  <th style={{ ...TH_STYLE, textAlign: 'right' }}>% of AUM</th>
                  <th style={TH_STYLE}>N-PORT Cov</th>
                </tr>
              </thead>
              <tbody>
                {groups.flatMap((g) => {
                  const pkey = `${g.parent.rank}:${g.parent.institution}`
                  const canExpand = g.children.length >= 2
                  const isOpen = expanded.has(pkey)
                  const trs = [renderRow(g.parent, pkey, 0, canExpand, isOpen, toggle)]
                  if (isOpen) {
                    g.children.forEach((c, ci) => {
                      trs.push(renderRow(c, `${pkey}:${ci}`, 1, false, false, toggle))
                    })
                  }
                  return trs
                })}
              </tbody>
            </table>
          </div>
          {groups.length === 0 && (
            <div
              style={{
                padding: 30,
                textAlign: 'center',
                color: '#64748b',
              }}
            >
              {activeOnly
                ? 'No active-only holders (toggle off "Active only" to see passive parents)'
                : `No holders found for ${ticker}`}
            </div>
          )}
          {data.all_totals && (
            <div
              style={{
                marginTop: 10,
                padding: '8px 10px',
                fontSize: 12,
                color: '#475569',
                backgroundColor: '#f8fafc',
                borderTop: '1px solid #e5e7eb',
              }}
            >
              {`All investors: ${data.all_totals.count} holders · `}
              {formatValue(data.all_totals.value_live)}
              {' · '}
              {data.all_totals.pct_float != null
                ? `${NUM_2.format(data.all_totals.pct_float)}% float`
                : '—'}
            </div>
          )}
        </>
      )}
    </div>
  )
}

// renderRow is a plain function (not a component) so it can return a <tr>
// inside <tbody> without React wrapping concerns. Keys are stable per row.
function renderRow(
  row: RegisterRow,
  key: string,
  indent: 0 | 1,
  canExpand: boolean,
  isOpen: boolean,
  toggle: (k: string) => void,
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
          color: '#64748b',
          width: 44,
        }}
      >
        {indent === 0 ? row.rank : ''}
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
      <td style={TD_RIGHT}>{formatShares(row.shares)}</td>
      <td style={TD_RIGHT}>{formatValue(row.value_live)}</td>
      <td style={TD_RIGHT}>
        <PctCell v={row.pct_float} />
      </td>
      <td style={TD_RIGHT}>{formatAumMm(row.aum)}</td>
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
