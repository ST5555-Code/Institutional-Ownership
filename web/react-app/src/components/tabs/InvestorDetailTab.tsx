import { useEffect, useMemo, useState } from 'react'
import { useFetch } from '../../hooks/useFetch'
import type {
  MarketSummaryRow,
  InstitutionHierarchyResponse,
  InstitutionHierarchyFiler,
} from '../../types/api'
import { QuarterSelector, ExportBar, FreshnessBadge, PageHeader, getTypeStyle } from '../common'

// ── Formatters ─────────────────────────────────────────────────────────────

const NUM_0 = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 })
const NUM_1 = new Intl.NumberFormat('en-US', { minimumFractionDigits: 1, maximumFractionDigits: 1 })

function dedupeBy<T>(rows: T[], keyOf: (r: T) => string | number | null | undefined): T[] {
  const seen = new Set<string | number>()
  const out: T[] = []
  for (const r of rows) {
    const k = keyOf(r)
    if (k == null) {
      out.push(r)
      continue
    }
    if (seen.has(k)) continue
    seen.add(k)
    out.push(r)
  }
  return out
}

function fmtAumB(v: number | null | undefined): string {
  if (v == null || v === 0) return '—'
  if (v >= 1e12) return `$${NUM_1.format(v / 1e12)}T`
  if (v >= 1e9) return `$${NUM_1.format(v / 1e9)}B`
  if (v >= 1e6) return `$${NUM_0.format(v / 1e6)}M`
  return `$${NUM_0.format(v)}`
}

// ── Badge styles ───────────────────────────────────────────────────────────

function nportBadgeStyle(cov: number | null): React.CSSProperties | null {
  if (cov == null || cov <= 0) return null
  if (cov >= 80) return { backgroundColor: 'var(--pos-soft)', color: 'var(--pos)' }
  if (cov >= 50) return { backgroundColor: 'var(--gold-soft)', color: 'var(--gold)' }
  return { backgroundColor: 'rgba(255,255,255,0.05)', color: 'var(--text-dim)' }
}

// ── Shared inline styles ───────────────────────────────────────────────────

const TH: React.CSSProperties = {
  padding: '4px 8px',
  fontSize: 8,
  fontWeight: 700,
  textTransform: 'uppercase',
  letterSpacing: '0.16em',
  fontFamily: "'Hanken Grotesk', sans-serif",
  color: 'var(--text-dim)',
  backgroundColor: 'var(--header)',
  textAlign: 'left',
  borderBottom: '1px solid var(--line)',
  whiteSpace: 'nowrap',
  position: 'sticky',
  top: 0,
  zIndex: 3,
}
const TH_R: React.CSSProperties = { ...TH, textAlign: 'right' }
const TD: React.CSSProperties = {
  padding: '4px 8px',
  fontSize: 12,
  color: 'var(--text)',
  borderBottom: '1px solid var(--line-soft)',
}
const TD_R: React.CSSProperties = {
  ...TD,
  textAlign: 'right',
  fontVariantNumeric: 'tabular-nums',
  fontFamily: "'JetBrains Mono', monospace",
}
const BADGE: React.CSSProperties = {
  display: 'inline-block',
  padding: '1px 6px',
  fontSize: 10,
  fontWeight: 600,
  borderRadius: 1,
}

// ── Quarter helpers ────────────────────────────────────────────────────────

const FALLBACK_QUARTERS = ['2025Q1', '2025Q2', '2025Q3', '2025Q4']

function quarterLabel(q: string): string {
  const m = q.match(/^(\d{4})Q([1-4])$/)
  if (!m) return q
  const yy = m[1].slice(-2)
  return `Q${m[2]} '${yy}`
}

// ── Component ──────────────────────────────────────────────────────────────

export function InvestorDetailTab() {
  // Fetch tickers list to keep it in cache and to derive quarter availability
  // (the response is currently keyed by latest-quarter only, so we rely on the
  // static quarter list as a known stable enumeration).
  useFetch<unknown>('/api/v1/tickers')

  const quartersOldToNew = useMemo<string[]>(
    () => [...FALLBACK_QUARTERS].sort(),
    [],
  )

  const [quarter, setQuarter] = useState<string>(() => FALLBACK_QUARTERS[FALLBACK_QUARTERS.length - 1])

  const marketUrl = `/api/v1/entity_market_summary?limit=50&quarter=${encodeURIComponent(quarter)}`
  const market = useFetch<MarketSummaryRow[]>(marketUrl)

  const [openInst, setOpenInst] = useState<Set<number>>(new Set())
  const [openFiler, setOpenFiler] = useState<Set<number>>(new Set())
  const [hierarchy, setHierarchy] = useState<Record<number, InstitutionHierarchyResponse>>({})
  const [hierarchyLoading, setHierarchyLoading] = useState<Set<number>>(new Set())
  const [hierarchyError, setHierarchyError] = useState<Record<number, string>>({})

  useEffect(() => {
    setOpenInst(new Set())
    setOpenFiler(new Set())
    setHierarchy({})
    setHierarchyLoading(new Set())
    setHierarchyError({})
  }, [quarter])

  function toggleInst(entityId: number | null) {
    if (entityId == null) return
    setOpenInst((prev) => {
      const next = new Set(prev)
      if (next.has(entityId)) {
        next.delete(entityId)
      } else {
        next.add(entityId)
        if (!hierarchy[entityId] && !hierarchyLoading.has(entityId)) {
          setHierarchyLoading((p) => new Set(p).add(entityId))
          fetch(`/api/v1/institution_hierarchy?entity_id=${entityId}&quarter=${encodeURIComponent(quarter)}`)
            .then((r) => r.json())
            .then((json) => {
              if (json && typeof json === 'object' && 'error' in json) {
                throw new Error(String((json as { error: unknown }).error))
              }
              setHierarchy((p) => ({ ...p, [entityId]: json as InstitutionHierarchyResponse }))
            })
            .catch((e: unknown) => {
              setHierarchyError((p) => ({
                ...p,
                [entityId]: e instanceof Error ? e.message : String(e),
              }))
            })
            .finally(() => {
              setHierarchyLoading((p) => {
                const n = new Set(p)
                n.delete(entityId)
                return n
              })
            })
        }
      }
      return next
    })
  }

  function toggleFiler(filerEntityId: number) {
    setOpenFiler((prev) => {
      const next = new Set(prev)
      if (next.has(filerEntityId)) next.delete(filerEntityId)
      else next.add(filerEntityId)
      return next
    })
  }

  function onExcel() {
    if (!market.data) return
    const h = ['Rank', 'Institution', 'Type', 'AUM ($MM)', 'Filers', 'Funds', 'N-PORT Coverage']
    const csv = [
      h,
      ...market.data.map((r) => [
        r.rank,
        `"${r.institution}"`,
        r.manager_type || '',
        (r.total_aum / 1e6).toFixed(0),
        r.filer_count,
        r.fund_count,
        r.nport_coverage_pct ?? '',
      ]),
    ]
      .map((r) => r.join(','))
      .join('\n')
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
    const u = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = u
    a.download = `top_institutions_${quarter}.csv`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(u)
  }

  const labels = quartersOldToNew.map(quarterLabel)

  return (
    <div
      style={{
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        backgroundColor: 'var(--bg)',
        overflow: 'hidden',
      }}
    >
      {/* Header row: PageHeader (left) + FreshnessBadge + ExportBar (right) */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', padding: '0 12px', flexShrink: 0 }}>
        <div style={{ flex: 1 }}>
          <PageHeader
            section="Market Snapshot"
            title="Investor Detail"
            description="Top 50 institutions by AUM with expandable hierarchy: parent, 13F filers, and fund series."
          />
        </div>
        <div className="no-print" style={{ display: 'flex', alignItems: 'center', gap: 10, paddingTop: 14 }}>
          <FreshnessBadge tableName="summary_by_parent" label="register" />
          <ExportBar onExcel={onExcel} onPrint={() => window.print()} disabled={!market.data} />
        </div>
      </div>
      <style>{`@media print { .id-controls { display:none!important } .no-print { display:none!important } }`}</style>

      <div
        className="id-controls"
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          alignItems: 'flex-end',
          gap: 10,
          padding: '8px 12px',
          backgroundColor: 'var(--header)',
          borderBottom: '1px solid var(--line)',
          flexShrink: 0,
        }}
      >
        <QuarterSelector
          quarters={labels}
          value={quarterLabel(quarter)}
          onChange={(label) => {
            const idx = labels.indexOf(label)
            if (idx >= 0) setQuarter(quartersOldToNew[idx])
          }}
        />
      </div>

      <div style={{ flex: 1, overflowY: 'auto', position: 'relative' }}>
        <div style={{ padding: 10, backgroundColor: 'var(--panel)', minHeight: '100%' }}>
          {market.loading && (
            <div style={{ padding: 40, color: 'var(--text-dim)', textAlign: 'center' }}>
              Loading top institutions…
            </div>
          )}
          {market.error && (
            <div style={{ padding: 40, color: 'var(--neg)', textAlign: 'center' }}>Error: {market.error}</div>
          )}
          {market.data && (
            <table style={{ width: '100%', borderCollapse: 'separate', borderSpacing: 0, fontSize: 12 }}>
              <thead>
                <tr>
                  <th style={{ ...TH, width: 24 }} />
                  <th style={{ ...TH, width: 48 }}>Rank</th>
                  <th style={TH}>Institution</th>
                  <th style={TH}>Type</th>
                  <th style={TH_R}>AUM ($B)</th>
                  <th style={TH_R}>Filers</th>
                  <th style={TH_R}>Funds</th>
                  <th style={TH}>N-PORT Coverage</th>
                </tr>
              </thead>
              <tbody>
                {market.data.map((r) => {
                  const ts = getTypeStyle(r.manager_type)
                  const nport = nportBadgeStyle(r.nport_coverage_pct)
                  const canExpand = r.entity_id != null
                  const isOpen = r.entity_id != null && openInst.has(r.entity_id)
                  return (
                    <InstitutionRow
                      key={r.rank}
                      row={r}
                      ts={ts}
                      nport={nport}
                      canExpand={canExpand}
                      isOpen={isOpen}
                      onToggle={() => toggleInst(r.entity_id)}
                      hierarchy={r.entity_id != null ? hierarchy[r.entity_id] : undefined}
                      hierarchyLoading={r.entity_id != null && hierarchyLoading.has(r.entity_id)}
                      hierarchyError={r.entity_id != null ? hierarchyError[r.entity_id] : undefined}
                      openFiler={openFiler}
                      onToggleFiler={toggleFiler}
                    />
                  )
                })}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Row components ─────────────────────────────────────────────────────────

interface InstitutionRowProps {
  row: MarketSummaryRow
  ts: { bg: string; color: string; label: string }
  nport: React.CSSProperties | null
  canExpand: boolean
  isOpen: boolean
  onToggle: () => void
  hierarchy: InstitutionHierarchyResponse | undefined
  hierarchyLoading: boolean
  hierarchyError: string | undefined
  openFiler: Set<number>
  onToggleFiler: (filerEntityId: number) => void
}

function InstitutionRow({
  row,
  ts,
  nport,
  canExpand,
  isOpen,
  onToggle,
  hierarchy,
  hierarchyLoading,
  hierarchyError,
  openFiler,
  onToggleFiler,
}: InstitutionRowProps) {
  return (
    <>
      <tr
        onClick={canExpand ? onToggle : undefined}
        style={{ cursor: canExpand ? 'pointer' : 'default' }}
        onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'var(--panel-hi)')}
        onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = '')}
      >
        <td
          style={{
            ...TD,
            padding: '4px 0 4px 4px',
            textAlign: 'center',
            borderLeft: '2px solid transparent',
          }}
        >
          {canExpand && (
            <span
              style={{
                display: 'inline-block',
                color: 'var(--gold)',
                fontSize: 9,
                transition: 'transform 0.12s',
                transform: isOpen ? 'rotate(90deg)' : 'rotate(0deg)',
              }}
            >
              ▶
            </span>
          )}
        </td>
        <td style={{ ...TD, textAlign: 'right', fontWeight: 700, color: 'var(--text-dim)' }}>{row.rank}</td>
        <td style={{ ...TD, fontWeight: 600 }}>{row.institution}</td>
        <td style={TD}>
          <span style={{ ...BADGE, backgroundColor: ts.bg, color: ts.color }}>{ts.label}</span>
        </td>
        <td style={TD_R}>{fmtAumB(row.total_aum)}</td>
        <td style={TD_R}>{NUM_0.format(row.filer_count)}</td>
        <td style={TD_R}>{NUM_0.format(row.fund_count)}</td>
        <td style={TD}>
          {nport && row.nport_coverage_pct != null ? (
            <span style={{ ...BADGE, ...nport, display: 'inline-block', minWidth: 48, textAlign: 'center' }}>
              {Math.round(row.nport_coverage_pct)}%
            </span>
          ) : (
            <span style={{ color: 'var(--text-dim)' }}>—</span>
          )}
        </td>
      </tr>
      {isOpen && hierarchyLoading && (
        <tr>
          <td colSpan={8} style={{ ...TD, color: 'var(--text-dim)', padding: '12px 24px', backgroundColor: 'rgba(197,162,84,0.03)' }}>
            Loading filers…
          </td>
        </tr>
      )}
      {isOpen && hierarchyError && (
        <tr>
          <td colSpan={8} style={{ ...TD, color: 'var(--neg)', padding: '12px 24px', backgroundColor: 'rgba(197,162,84,0.03)' }}>
            Error: {hierarchyError}
          </td>
        </tr>
      )}
      {isOpen && hierarchy && hierarchy.filers.length === 0 && !hierarchyLoading && (
        <tr>
          <td colSpan={8} style={{ ...TD, color: 'var(--text-dim)', padding: '12px 24px', backgroundColor: 'rgba(197,162,84,0.03)' }}>
            No filer entities for {hierarchy.institution}.
          </td>
        </tr>
      )}
      {isOpen &&
        dedupeBy(hierarchy?.filers ?? [], (f) => f.entity_id).map((f) => (
          <FilerRows
            key={f.entity_id}
            filer={f}
            isOpen={openFiler.has(f.entity_id)}
            onToggle={() => onToggleFiler(f.entity_id)}
          />
        ))}
    </>
  )
}

function FilerRows({
  filer,
  isOpen,
  onToggle,
}: {
  filer: InstitutionHierarchyFiler
  isOpen: boolean
  onToggle: () => void
}) {
  const canExpand = filer.funds.length > 0
  return (
    <>
      <tr
        onClick={canExpand ? onToggle : undefined}
        style={{
          cursor: canExpand ? 'pointer' : 'default',
          backgroundColor: 'rgba(197,162,84,0.03)',
        }}
      >
        <td
          style={{
            ...TD,
            padding: '4px 0 4px 4px',
            textAlign: 'center',
            borderLeft: '2px solid var(--gold)',
          }}
        >
          {canExpand && (
            <span
              style={{
                display: 'inline-block',
                color: 'var(--gold)',
                fontSize: 9,
                transition: 'transform 0.12s',
                transform: isOpen ? 'rotate(90deg)' : 'rotate(0deg)',
              }}
            >
              ▶
            </span>
          )}
        </td>
        <td style={TD} />
        <td
          style={{
            ...TD,
            paddingLeft: 24,
            color: 'var(--text-mute)',
            fontSize: 12,
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            maxWidth: 0,
          }}
          title={filer.name}
        >
          <span style={{ color: 'var(--text-mute)', marginRight: 6, fontSize: 11 }}>└</span>
          {filer.name}
        </td>
        <td style={TD} />
        <td style={{ ...TD_R, fontSize: 12 }}>{fmtAumB(filer.aum)}</td>
        <td style={TD} />
        <td style={{ ...TD_R, fontSize: 12 }}>{NUM_0.format(filer.fund_count)}</td>
        <td style={TD} />
      </tr>
      {isOpen &&
        dedupeBy(filer.funds, (fund) => fund.series_id).map((fund) => (
          <tr key={fund.entity_id} style={{ backgroundColor: 'rgba(197,162,84,0.03)' }}>
            <td
              style={{
                ...TD,
                padding: '4px 0 4px 4px',
                borderLeft: '2px solid var(--gold)',
              }}
            />
            <td style={TD} />
            <td
              style={{
                ...TD,
                paddingLeft: 48,
                color: 'var(--text-mute)',
                fontSize: 12,
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                maxWidth: 0,
              }}
              title={fund.fund_name}
            >
              <span style={{ color: 'var(--text-mute)', marginRight: 6, fontSize: 11 }}>└</span>
              {fund.fund_name}
            </td>
            <td style={TD} />
            <td style={{ ...TD_R, fontSize: 12 }}>{fmtAumB(fund.nav)}</td>
            <td style={TD} />
            <td style={TD} />
            <td style={TD} />
          </tr>
        ))}
    </>
  )
}
