import { useCallback, useEffect, useRef, useState } from 'react'
import { useAppStore } from '../../store/useAppStore'
import { useFetch } from '../../hooks/useFetch'
import type {
  EntitySearchResult,
  EntityGraphResponse,
  EntityGraphNode,
  EntityGraphEdge,
  MarketSummaryRow,
  RegisterResponse,
} from '../../types/api'
import { QuarterSelector, ExportBar, getTypeStyle } from '../common'
import ReactFlow, {
  Background, Controls,
  useNodesState, useEdgesState,
  Handle, Position,
} from 'reactflow'
import 'reactflow/dist/style.css'
import type { NodeProps, Node as RFNode, Edge } from 'reactflow'

// ── Formatters ─────────────────────────────────────────────────────────────

const NUM_0 = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 })
const NUM_1 = new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 })
const NUM_P1 = new Intl.NumberFormat('en-US', { minimumFractionDigits: 1, maximumFractionDigits: 1 })
const NUM_2 = new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

function fmtAum(v: number | null): string {
  if (v == null || v === 0) return '—'
  if (v >= 1e12) return `$${NUM_1.format(v / 1e12)}T`
  if (v >= 1e9) return `$${NUM_1.format(v / 1e9)}B`
  if (v >= 1e6) return `$${NUM_0.format(v / 1e6)}M`
  return `$${NUM_0.format(v)}`
}

// ── Styles ─────────────────────────────────────────────────────────────────

const TH: React.CSSProperties = { padding: '7px 10px', fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.04em', color: '#ffffff', backgroundColor: 'var(--oxford-blue)', textAlign: 'left', borderBottom: '1px solid #1e2d47', whiteSpace: 'nowrap' }
const TH_R: React.CSSProperties = { ...TH, textAlign: 'right' }
const TD: React.CSSProperties = { padding: '7px 10px', fontSize: 13, color: '#1e293b', borderBottom: '1px solid #e5e7eb' }
const TD_R: React.CSSProperties = { ...TD, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }
const BADGE: React.CSSProperties = { display: 'inline-block', padding: '2px 8px', fontSize: 11, fontWeight: 600, borderRadius: 3 }
const FC: React.CSSProperties = { padding: '7px 10px', fontSize: 13, fontWeight: 600, color: '#fff', backgroundColor: 'var(--oxford-blue)', position: 'sticky', bottom: 0, zIndex: 2, borderTop: '2px solid var(--oxford-blue)' }
const FCR: React.CSSProperties = { ...FC, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }

// ── React Flow layout ──────────────────────────────────────────────────────

function layoutFilerGraph(nodes: EntityGraphNode[]): { rfNodes: RFNode[]; graphHeight: number } {
  const inst = nodes.filter(n => n.node_type === 'institution')
  const filers = nodes.filter(n => n.node_type === 'filer')
  const result: RFNode[] = []
  inst.forEach((n, i) => {
    result.push({ id: n.id, type: 'institution', position: { x: i * 200, y: 0 }, data: { label: n.display_name, aum: n.aum, entity_id: n.entity_id, node_type: n.node_type, classification: n.classification } })
  })
  const COLS = Math.min(filers.length, 6)
  const X_GAP = 170; const Y_GAP = 80
  const rows = Math.ceil(filers.length / (COLS || 1))
  const totalW = (COLS - 1) * X_GAP
  filers.forEach((n, i) => {
    const col = i % COLS; const row = Math.floor(i / COLS)
    result.push({ id: n.id, type: 'filer', position: { x: col * X_GAP - totalW / 2, y: 120 + row * Y_GAP }, data: { label: n.display_name, aum: n.aum, entity_id: n.entity_id, node_type: n.node_type } })
  })
  return { rfNodes: result, graphHeight: Math.max(220, 120 + rows * Y_GAP + 60) }
}

function filerEdges(edges: EntityGraphEdge[], nodeIds: Set<string>): Edge[] {
  return edges.filter(e => nodeIds.has(e.from) && nodeIds.has(e.to)).map(e => ({
    id: `e-${e.from}-${e.to}`, source: e.from, target: e.to, style: { stroke: '#002147', strokeWidth: 2 },
  }))
}

function InstitutionNode({ data }: NodeProps) {
  return (
    <div style={{ backgroundColor: '#002147', color: '#fff', borderRadius: 8, padding: '10px 16px', minWidth: 180, textAlign: 'center', fontSize: 13, fontWeight: 700 }}>
      <Handle type="source" position={Position.Bottom} style={{ visibility: 'hidden' }} />
      <div>{data.label}</div>
      {data.aum != null && <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 3 }}>{fmtAum(data.aum)}</div>}
    </div>
  )
}
function FilerNode({ data }: NodeProps) {
  return (
    <div style={{ backgroundColor: '#4A90D9', color: '#fff', borderRadius: 6, padding: '7px 12px', minWidth: 140, textAlign: 'center', fontSize: 11, fontWeight: 500 }}>
      <Handle type="target" position={Position.Top} style={{ visibility: 'hidden' }} />
      <div style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: 160 }}>{data.label}</div>
      {data.aum != null && <div style={{ fontSize: 9, color: 'rgba(255,255,255,0.7)', marginTop: 2 }}>{fmtAum(data.aum)}</div>}
    </div>
  )
}
const nodeTypes = { institution: InstitutionNode, filer: FilerNode }

// ── Fund card ──────────────────────────────────────────────────────────────

interface FundInfo { id: string; name: string; aum: number | null; subAdviser: string | null }
function FundCard({ fund }: { fund: FundInfo }) {
  return (
    <div style={{ padding: '8px 10px', borderRadius: 4, border: `1px solid ${fund.subAdviser ? '#C9B99A' : '#e2e8f0'}`, borderLeft: `3px solid ${fund.subAdviser ? '#C9B99A' : '#2E7D32'}`, backgroundColor: '#fff', fontSize: 11 }}>
      <div style={{ fontWeight: 600, color: '#1e293b', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }} title={fund.name}>{fund.name}</div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 3 }}>
        <span style={{ color: '#64748b', fontSize: 10 }}>{fmtAum(fund.aum)}</span>
        {fund.subAdviser && <span style={{ color: '#8a7d66', fontSize: 9, fontStyle: 'italic' }}>{fund.subAdviser}</span>}
      </div>
    </div>
  )
}

// ── Entity search ──────────────────────────────────────────────────────────

function EntitySearch({ onSelect }: { onSelect: (id: number, name: string) => void }) {
  const [input, setInput] = useState('')
  const [results, setResults] = useState<EntitySearchResult[]>([])
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(() => {
    function h(e: MouseEvent) { if (ref.current && !ref.current.contains(e.target as HTMLElement)) setOpen(false) }
    document.addEventListener('mousedown', h); return () => document.removeEventListener('mousedown', h)
  }, [])
  function handleInput(v: string) {
    setInput(v)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    if (v.length < 2) { setResults([]); setOpen(false); return }
    debounceRef.current = setTimeout(() => {
      fetch(`/api/entity_search?q=${encodeURIComponent(v)}`)
        .then(r => r.json()).then((data: EntitySearchResult[]) => { setResults(data.slice(0, 10)); setOpen(data.length > 0) }).catch(() => {})
    }, 300)
  }
  return (
    <div ref={ref} style={{ position: 'relative', display: 'inline-block' }}>
      <input type="text" value={input} placeholder="Search institution…" autoComplete="off" autoCorrect="off" spellCheck={false}
        onChange={e => handleInput(e.target.value)} onFocus={() => { if (results.length > 0) setOpen(true) }}
        style={{ width: 260, padding: '6px 10px', fontSize: 13, color: '#fff', backgroundColor: '#1a2a4a', border: '1px solid #2d3f5e', borderRadius: 4, outline: 'none' }} />
      {open && results.length > 0 && (
        <div style={{ position: 'absolute', top: '100%', left: 0, marginTop: 2, width: 320, maxHeight: 280, overflowY: 'auto', backgroundColor: '#0d1526', border: '1px solid #2d3f5e', borderRadius: 4, boxShadow: '0 4px 12px rgba(0,0,0,0.3)', zIndex: 1000 }}>
          {results.map(r => (
            <div key={r.entity_id} onMouseDown={() => { setInput(r.display_name); setOpen(false); onSelect(r.entity_id, r.display_name) }}
              style={{ padding: '7px 12px', cursor: 'pointer' }} onMouseEnter={e => (e.currentTarget.style.backgroundColor = '#1a2a4a')} onMouseLeave={e => (e.currentTarget.style.backgroundColor = 'transparent')}>
              <div style={{ color: '#fff', fontWeight: 600, fontSize: 13 }}>{r.display_name}</div>
              <div style={{ color: '#94a3b8', fontSize: 11 }}>{r.classification || r.entity_type}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Component ──────────────────────────────────────────────────────────────

const QUARTERS = ['2025Q4', '2025Q3', '2025Q2', '2025Q1']
type ViewMode = 'market' | 'company'

export function EntityGraphTab() {
  const { ticker, rollupType } = useAppStore()

  const [viewMode, setViewMode] = useState<ViewMode>('market')
  const [quarter, setQuarter] = useState('2025Q4')
  const [showSubAdvisers, setShowSubAdvisers] = useState(true)

  // Company mode state
  const [selectedEntityId, setSelectedEntityId] = useState<number | null>(null)
  const [selectedEntityName, setSelectedEntityName] = useState('')
  const [selectedFiler, setSelectedFiler] = useState<string | null>(null)
  const [expanded, setExpanded] = useState(false)
  const [allFundNodes, setAllFundNodes] = useState<EntityGraphNode[]>([])

  // Modal state (floating entity detail on row click)
  const [modalEntityId, setModalEntityId] = useState<number | null>(null)
  const [modalEntityName, setModalEntityName] = useState('')

  // Market mode: always shows market leaderboard (ignores ticker)
  const marketUrl = viewMode === 'market' ? '/api/entity_market_summary?limit=25' : null
  const market = useFetch<MarketSummaryRow[]>(marketUrl)

  // Company mode: ticker holder table (when ticker is set)
  const tickerHoldersUrl = viewMode === 'company' && ticker
    ? `/api/query1?ticker=${enc(ticker)}&rollup_type=${rollupType}`
    : null
  const tickerHolders = useFetch<RegisterResponse>(tickerHoldersUrl)

  // Modal graph fetch
  const modalGraphUrl = modalEntityId
    ? `/api/entity_graph?entity_id=${modalEntityId}&quarter=${enc(quarter)}&depth=2&include_sub_advisers=${showSubAdvisers}&top_n_funds=20`
    : null
  const modalGraph = useFetch<EntityGraphResponse>(modalGraphUrl)

  // Company graph fetch
  const graphUrl = viewMode === 'company' && selectedEntityId
    ? `/api/entity_graph?entity_id=${selectedEntityId}&quarter=${enc(quarter)}&depth=2&include_sub_advisers=${showSubAdvisers}&top_n_funds=20`
    : null
  const { data, loading, error } = useFetch<EntityGraphResponse>(graphUrl)

  useEffect(() => { setExpanded(false); setAllFundNodes([]); setSelectedFiler(null) }, [selectedEntityId, quarter, showSubAdvisers])

  // React Flow state (Company mode)
  const [nodes, setNodes, onNodesChange] = useNodesState([])
  const [edges, setEdges, onEdgesChange] = useEdgesState([])
  const [graphHeight, setGraphHeight] = useState(220)

  useEffect(() => {
    if (!data) { setNodes([]); setEdges([]); setGraphHeight(220); return }
    const gn = data.nodes.filter(n => n.node_type === 'institution' || n.node_type === 'filer')
    const { rfNodes, graphHeight: h } = layoutFilerGraph(gn)
    const nids = new Set(gn.map(n => n.id))
    setNodes(rfNodes); setEdges(filerEdges(data.edges, nids)); setGraphHeight(h)
  }, [data, setNodes, setEdges])

  const activeCo = viewMode === 'company' ? data : null
  const fundNodes = expanded ? allFundNodes : (activeCo?.nodes.filter(n => n.node_type === 'fund') ?? [])
  const subAdviserNodes = activeCo?.nodes.filter(n => n.node_type === 'sub_adviser') ?? []
  const subAdviserMap = new Map<string, string>()
  if (activeCo) { for (const e of activeCo.edges) { if (e.relationship_type === 'sub_adviser') { const sa = subAdviserNodes.find(n => n.id === e.from); if (sa) subAdviserMap.set(e.to, sa.display_name) } } }
  const ownedFunds = fundNodes.filter(f => !subAdviserMap.has(f.id)).map(f => ({ id: f.id, name: f.display_name, aum: f.aum, subAdviser: null as string | null })).sort((a, b) => (b.aum || 0) - (a.aum || 0))
  const subAdvisedFunds = fundNodes.filter(f => subAdviserMap.has(f.id)).map(f => ({ id: f.id, name: f.display_name, aum: f.aum, subAdviser: subAdviserMap.get(f.id) || null })).sort((a, b) => (b.aum || 0) - (a.aum || 0))

  function expandFunds() {
    if (!activeCo || expanded) return
    fetch(`/api/entity_children?entity_id=${activeCo.metadata.root_entity_id}&level=fund&top_n=0`)
      .then(r => r.json()).then((children: Array<{ entity_id: number; display_name: string; aum: number | null }>) => {
        setAllFundNodes(children.map(c => ({ id: `fund-${c.entity_id}`, entity_id: c.entity_id, node_type: 'fund', display_name: c.display_name, label: c.display_name, title: c.display_name, level: 2, classification: null, aum: c.aum, aum_type: null, color: { background: '#2E7D32', border: '#1B5E20' }, font: { color: '#fff' } })))
        setExpanded(true)
      }).catch(() => {})
  }

  const handleNodeClick = useCallback((_: React.MouseEvent, node: RFNode) => { if (node.type === 'filer') setSelectedFiler(prev => prev === node.id ? null : node.id) }, [])

  // Row click in ticker holders: search entity by name → open modal
  function handleHolderClick(institutionName: string) {
    fetch(`/api/entity_search?q=${encodeURIComponent(institutionName.substring(0, 30))}`)
      .then(r => r.json())
      .then((results: EntitySearchResult[]) => {
        if (results.length > 0) {
          setModalEntityId(results[0].entity_id)
          setModalEntityName(institutionName)
        }
      }).catch(() => {})
  }

  // Row click in market summary
  function handleMarketClick(entityId: number | null, name: string) {
    if (entityId) { setModalEntityId(entityId); setModalEntityName(name) }
  }

  function onExcel() {
    if (viewMode === 'market' && !ticker && market.data) {
      const h = ['Rank', 'Institution', 'AUM ($MM)', 'Type', 'Filers', 'Funds', 'Holdings', 'Fund Cov %']
      const csv = [h, ...market.data.map(r => [r.rank, `"${r.institution}"`, (r.total_aum / 1e6).toFixed(0), r.manager_type || '', r.filer_count, r.fund_count, r.num_holdings, r.nport_coverage_pct ?? ''])].map(r => r.join(',')).join('\n')
      downloadCsv(csv, 'market_summary.csv')
    } else if (viewMode === 'market' && ticker && tickerHolders.data) {
      const h = ['Rank', 'Institution', 'Type', 'Value ($MM)', '% Float', 'AUM ($MM)']
      const csv = [h, ...tickerHolders.data.rows.filter(r => r.level === 0).map(r => [r.rank, `"${r.institution}"`, r.type, r.value_live ? (r.value_live / 1e6).toFixed(0) : '', r.pct_float?.toFixed(2) ?? '', r.aum ?? ''])].map(r => r.join(',')).join('\n')
      downloadCsv(csv, `entity_holders_${ticker}.csv`)
    } else if (activeCo) {
      const h = ['ID', 'Type', 'Name', 'AUM']
      const csv = [h, ...activeCo.nodes.map(n => [n.id, n.node_type, `"${n.display_name}"`, n.aum != null ? fmtAum(n.aum) : ''])].map(r => r.join(',')).join('\n')
      downloadCsv(csv, `entity_graph_${selectedEntityName.replace(/\s+/g, '_')}.csv`)
    }
  }

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', backgroundColor: 'var(--shell-bg)', overflow: 'hidden' }}>
      <style>{`@media print { .eg-controls { display:none!important } }`}</style>

      {/* Controls */}
      <div className="eg-controls" style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'flex-end', gap: 16, padding: '10px 16px', backgroundColor: 'var(--sidebar-bg)', borderBottom: '1px solid #1e2d47', flexShrink: 0 }}>
        <div style={{ display: 'flex', gap: 4 }}>
          {(['market', 'company'] as const).map(m => (
            <button key={m} type="button" onClick={() => setViewMode(m)}
              style={{ padding: '5px 12px', fontSize: 12, borderRadius: 4, cursor: 'pointer', fontWeight: viewMode === m ? 600 : 400, color: viewMode === m ? '#fff' : '#94a3b8', backgroundColor: viewMode === m ? 'var(--oxford-blue)' : '#1a2a4a', border: `1px solid ${viewMode === m ? 'var(--oxford-blue)' : '#2d3f5e'}` }}>
              {m === 'market' ? 'Market' : 'Company'}
            </button>
          ))}
        </div>
        {viewMode === 'company' && <EntitySearch onSelect={(id, name) => {
          setSelectedEntityId(id); setSelectedEntityName(name)
          // Also open floating modal so the diagram shows immediately
          setModalEntityId(id); setModalEntityName(name)
        }} />}
        <QuarterSelector quarters={QUARTERS} value={quarter} onChange={q => { setQuarter(q); setModalEntityId(null) }} />
        {viewMode === 'company' && !ticker && (
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: '#94a3b8', cursor: 'pointer' }}>
            <input type="checkbox" checked={showSubAdvisers} onChange={e => setShowSubAdvisers(e.target.checked)} /> Sub-Advisers
          </label>
        )}
        <div style={{ marginLeft: 'auto' }}>
          <ExportBar onExcel={onExcel} onPrint={() => window.print()} disabled={viewMode === 'market' ? !market.data : (ticker ? !tickerHolders.data : !data)} />
        </div>
      </div>

      {/* Content */}
      <div style={{ flex: 1, overflowY: 'auto', position: 'relative' }}>
        {/* ── MARKET MODE — always market leaderboard ── */}
        {viewMode === 'market' && (
          <div style={{ padding: 16, backgroundColor: 'var(--card-bg)', minHeight: '100%' }}>
            {market.loading && <div style={{ padding: 40, color: '#94a3b8', textAlign: 'center' }}>Loading market summary…</div>}
            {market.error && <div style={{ padding: 40, color: '#ef4444', textAlign: 'center' }}>Error: {market.error}</div>}
            {market.data && (() => {
              const totalAum = market.data.reduce((s, r) => s + r.total_aum, 0)
              const totalFilers = market.data.reduce((s, r) => s + r.filer_count, 0)
              const totalFunds = market.data.reduce((s, r) => s + r.fund_count, 0)
              const totalHoldings = market.data.reduce((s, r) => s + r.num_holdings, 0)
              return (
              <table style={{ width: '100%', borderCollapse: 'separate', borderSpacing: 0, fontSize: 13 }}>
                <thead><tr>
                  <th style={{ ...TH, width: 40 }}>#</th><th style={TH}>Institution</th><th style={TH}>Type</th>
                  <th style={TH_R}>AUM ($MM)</th><th style={TH_R}>% of Total</th><th style={TH_R}>Filers</th>
                  <th style={TH_R}>Funds</th><th style={TH_R}>Holdings</th><th style={TH_R}>Fund Cov %</th>
                </tr></thead>
                <tbody>
                  {market.data.map(r => {
                    const ts = getTypeStyle(r.manager_type)
                    const pct = totalAum > 0 ? (r.total_aum / totalAum * 100) : 0
                    const covStyle = r.nport_coverage_pct != null && r.nport_coverage_pct > 0 ? r.nport_coverage_pct >= 80 ? { color: '#27AE60' } : r.nport_coverage_pct >= 50 ? { color: '#F5A623' } : { color: '#94a3b8' } : { color: '#cbd5e1' }
                    return (
                      <tr key={r.rank} onClick={() => handleMarketClick(r.entity_id, r.institution)} style={{ cursor: 'pointer' }}
                        onMouseEnter={e => (e.currentTarget.style.backgroundColor = '#f8fafc')} onMouseLeave={e => (e.currentTarget.style.backgroundColor = '')}>
                        <td style={{ ...TD, textAlign: 'right', fontWeight: 700, color: '#64748b' }}>{r.rank}</td>
                        <td style={{ ...TD, fontWeight: 600 }}>{r.institution}</td>
                        <td style={TD}><span style={{ ...BADGE, backgroundColor: ts.bg, color: ts.color }}>{ts.label}</span></td>
                        <td style={TD_R}>{NUM_0.format(r.total_aum / 1e6)}</td>
                        <td style={TD_R}>{NUM_P1.format(pct)}%</td>
                        <td style={TD_R}>{NUM_0.format(r.filer_count)}</td>
                        <td style={TD_R}>{NUM_0.format(r.fund_count)}</td>
                        <td style={TD_R}>{NUM_0.format(r.num_holdings)}</td>
                        <td style={{ ...TD_R, ...covStyle, fontWeight: 600 }}>{r.nport_coverage_pct != null && r.nport_coverage_pct > 0 ? `${Math.round(r.nport_coverage_pct)}%` : '—'}</td>
                      </tr>
                    )
                  })}
                </tbody>
                <tfoot><tr>
                  <td style={FC} /><td style={FC}>Top {market.data.length} Total</td><td style={FC} />
                  <td style={FCR}>{NUM_0.format(totalAum / 1e6)}</td><td style={FCR}>100.0%</td>
                  <td style={FCR}>{NUM_0.format(totalFilers)}</td><td style={FCR}>{NUM_0.format(totalFunds)}</td>
                  <td style={FCR}>{NUM_0.format(totalHoldings)}</td><td style={FC} />
                </tr></tfoot>
              </table>)
            })()}
          </div>
        )}

        {/* ── COMPANY MODE ── */}
        {viewMode === 'company' && (
          <>
            {/* Ticker set: show top holders table with modal on click */}
            {ticker && (
              <div style={{ padding: 16, backgroundColor: 'var(--card-bg)', minHeight: '100%' }}>
                <div style={{ fontSize: 14, fontWeight: 700, color: '#1e293b', marginBottom: 12 }}>Top Holders of {ticker.toUpperCase()} — click to view entity structure</div>
                {tickerHolders.loading && <div style={{ padding: 40, color: '#94a3b8', textAlign: 'center' }}>Loading holders…</div>}
                {tickerHolders.error && <div style={{ padding: 40, color: '#ef4444', textAlign: 'center' }}>Error: {tickerHolders.error}</div>}
                {tickerHolders.data && (() => {
                  const parentRows = tickerHolders.data.rows.filter(r => r.level === 0)
                  const totalValue = parentRows.reduce((s, r) => s + (r.value_live || 0), 0)
                  const totalPctFloat = parentRows.reduce((s, r) => s + (r.pct_float || 0), 0)
                  return (
                  <table style={{ width: '100%', borderCollapse: 'separate', borderSpacing: 0, fontSize: 13 }}>
                    <thead><tr>
                      <th style={{ ...TH, width: 40 }}>#</th><th style={TH}>Institution</th><th style={TH}>Type</th>
                      <th style={TH_R}>Value ($MM)</th><th style={TH_R}>% Float</th><th style={TH_R}>AUM ($MM)</th>
                    </tr></thead>
                    <tbody>
                      {parentRows.map((r, i) => {
                        const ts = getTypeStyle(r.type)
                        return (
                          <tr key={i} onClick={() => handleHolderClick(r.institution)} style={{ cursor: 'pointer' }}
                            onMouseEnter={e => (e.currentTarget.style.backgroundColor = '#f8fafc')} onMouseLeave={e => (e.currentTarget.style.backgroundColor = '')}>
                            <td style={{ ...TD, textAlign: 'right', fontWeight: 700, color: '#64748b' }}>{r.rank}</td>
                            <td style={{ ...TD, fontWeight: 600 }}>{r.institution}</td>
                            <td style={TD}><span style={{ ...BADGE, backgroundColor: ts.bg, color: ts.color }}>{ts.label}</span></td>
                            <td style={TD_R}>{r.value_live != null && r.value_live !== 0 ? `$${NUM_0.format(r.value_live / 1e6)}` : '—'}</td>
                            <td style={TD_R}>{r.pct_float != null && r.pct_float !== 0 ? `${NUM_2.format(r.pct_float)}%` : '—'}</td>
                            <td style={TD_R}>{r.aum != null && r.aum !== 0 ? `$${NUM_0.format(r.aum)}` : '—'}</td>
                          </tr>
                        )
                      })}
                    </tbody>
                    <tfoot><tr>
                      <td style={FC} /><td style={FC}>Top {parentRows.length} Total</td><td style={FC} />
                      <td style={FCR}>{totalValue > 0 ? `$${NUM_0.format(totalValue / 1e6)}` : '—'}</td>
                      <td style={FCR}>{totalPctFloat > 0 ? `${NUM_2.format(totalPctFloat)}%` : '—'}</td>
                      <td style={FC} />
                    </tr></tfoot>
                  </table>)
                })()}
              </div>
            )}

            {/* No ticker: entity search + React Flow diagram */}
            {!ticker && (
              <>
                {!selectedEntityId && (
                  <div style={{ height: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 12 }}>
                    <div style={{ fontSize: 32, color: '#2d3f5e' }}>🔍</div>
                    <div style={{ color: '#94a3b8', fontSize: 14 }}>Search for an institution to view its entity structure</div>
                  </div>
                )}
                {loading && <div style={{ padding: 40, color: '#94a3b8', textAlign: 'center' }}>Loading…</div>}
                {error && !loading && <div style={{ padding: 40, color: '#ef4444', textAlign: 'center' }}>Error: {error}</div>}
            {data && !loading && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
                <div style={{ height: graphHeight, borderBottom: '1px solid #1e2d47', flexShrink: 0 }}>
                  <ReactFlow nodes={nodes} edges={edges} onNodesChange={onNodesChange} onEdgesChange={onEdgesChange} onNodeClick={handleNodeClick} nodeTypes={nodeTypes} fitView fitViewOptions={{ padding: 0.3 }} style={{ backgroundColor: 'var(--shell-bg)' }} proOptions={{ hideAttribution: true }}>
                    <Background color="#1e2d47" gap={20} /><Controls style={{ bottom: 10, left: 10 }} />
                  </ReactFlow>
                </div>
                <div style={{ display: 'flex', gap: 32, padding: '10px 20px', backgroundColor: 'var(--sidebar-bg)', borderBottom: '1px solid #1e2d47' }}>
                  <AumChip label="Total AUM" value={fmtAum(data.nodes.find(n => n.node_type === 'institution')?.aum ?? null)} />
                  <AumChip label="Owned Funds" value={fmtAum(ownedFunds.reduce((s, f) => s + (f.aum || 0), 0))} count={ownedFunds.length} />
                  {subAdvisedFunds.length > 0 && <AumChip label="Sub-Advised" value={fmtAum(subAdvisedFunds.reduce((s, f) => s + (f.aum || 0), 0))} count={subAdvisedFunds.length} />}
                  <AumChip label="Filers" value={String(data.metadata.filer_count)} />
                  {selectedFiler && <span style={{ fontSize: 11, color: '#64748b', alignSelf: 'center' }}>Filer: {selectedFiler}</span>}
                  {data.metadata.truncated && !expanded && (
                    <button type="button" onClick={expandFunds} style={{ padding: '4px 12px', fontSize: 11, color: 'var(--glacier-blue)', backgroundColor: 'transparent', border: '1px solid var(--glacier-blue)', borderRadius: 4, cursor: 'pointer', alignSelf: 'center' }}>
                      Show all funds ({Object.values(data.metadata.total_funds_by_filer).reduce((a, b) => a + b, 0)})
                    </button>
                  )}
                  {expanded && <span style={{ fontSize: 11, color: '#27AE60', alignSelf: 'center' }}>✓ All funds loaded</span>}
                </div>
                <div style={{ display: 'flex', gap: 0, flex: 1 }}>
                  <div style={{ flex: subAdvisedFunds.length > 0 ? 3 : 1, padding: 16, overflowY: 'auto', borderRight: subAdvisedFunds.length > 0 ? '1px solid #e2e8f0' : undefined }}>
                    <div style={{ fontSize: 12, fontWeight: 700, color: '#1e293b', marginBottom: 10, display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{ display: 'inline-block', width: 10, height: 10, backgroundColor: '#2E7D32', borderRadius: 2 }} /> Owned Funds ({ownedFunds.length})
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 8 }}>
                      {ownedFunds.map(f => <FundCard key={f.id} fund={f} />)}
                    </div>
                    {ownedFunds.length === 0 && <div style={{ color: '#94a3b8', fontSize: 13 }}>No fund data available</div>}
                  </div>
                  {subAdvisedFunds.length > 0 && (
                    <div style={{ flex: 2, padding: 16, overflowY: 'auto', backgroundColor: '#faf9f7' }}>
                      <div style={{ fontSize: 12, fontWeight: 700, color: '#1e293b', marginBottom: 10, display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span style={{ display: 'inline-block', width: 10, height: 10, backgroundColor: '#C9B99A', borderRadius: 2 }} /> Sub-Advised Funds ({subAdvisedFunds.length})
                      </div>
                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 8 }}>
                        {subAdvisedFunds.map(f => <FundCard key={f.id} fund={f} />)}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}
              </>
            )}
          </>
        )}

        {/* ── FLOATING MODAL — entity structure detail ── */}
        {modalEntityId && (
          <div style={{ position: 'fixed', inset: 0, zIndex: 100, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
            onClick={() => setModalEntityId(null)}>
            <div style={{ position: 'absolute', inset: 0, backgroundColor: 'rgba(0,0,0,0.5)' }} />
            <div style={{ position: 'relative', width: '90%', maxWidth: 1100, maxHeight: '85vh', backgroundColor: 'var(--card-bg)', borderRadius: 8, boxShadow: '0 20px 60px rgba(0,0,0,0.3)', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}
              onClick={e => e.stopPropagation()}>
              {/* Modal header */}
              <div style={{ padding: '12px 20px', backgroundColor: 'var(--oxford-blue)', color: '#fff', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexShrink: 0 }}>
                <span style={{ fontWeight: 700, fontSize: 15 }}>{modalEntityName} — Entity Structure</span>
                <button type="button" onClick={() => setModalEntityId(null)} style={{ backgroundColor: 'transparent', border: 'none', color: '#94a3b8', cursor: 'pointer', fontSize: 20 }}>×</button>
              </div>
              {/* Modal content */}
              <div style={{ flex: 1, overflowY: 'auto', padding: 16, color: '#1e293b' }}>
                {modalGraph.loading && <div style={{ padding: 40, color: '#94a3b8', textAlign: 'center' }}>Loading entity structure…</div>}
                {modalGraph.error && <div style={{ padding: 40, color: '#ef4444', textAlign: 'center' }}>Error: {modalGraph.error}</div>}
                {modalGraph.data && <ModalGraphContent data={modalGraph.data} quarter={quarter} />}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Modal graph content ─────────────────────────────────────────────────────

function ModalGraphContent({ data, quarter }: { data: EntityGraphResponse; quarter: string }) {
  const filers = data.nodes.filter(n => n.node_type === 'filer')
  const funds = data.nodes.filter(n => n.node_type === 'fund')
  const subAdviserNodes = data.nodes.filter(n => n.node_type === 'sub_adviser')
  const instAum = data.nodes.find(n => n.node_type === 'institution')?.aum
  const instName = data.metadata.root_name
  const totalFunds = Object.values(data.metadata.total_funds_by_filer).reduce((a, b) => a + b, 0)

  // Sub-adviser map
  const saMap = new Map<string, string>()
  for (const e of data.edges) { if (e.relationship_type === 'sub_adviser') { const sa = subAdviserNodes.find(n => n.id === e.from); if (sa) saMap.set(e.to, sa.display_name) } }

  const owned = funds.filter(f => !saMap.has(f.id)).sort((a, b) => (b.aum || 0) - (a.aum || 0))
  const subAdvised = funds.filter(f => saMap.has(f.id)).sort((a, b) => (b.aum || 0) - (a.aum || 0))

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* Summary */}
      <div style={{ display: 'flex', gap: 32, padding: '10px 16px', backgroundColor: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 6 }}>
        <SummaryTile label="Institution" value={instName} />
        <SummaryTile label="Total AUM" value={fmtAum(instAum ?? null)} />
        <SummaryTile label="Filers" value={String(filers.length)} />
        <SummaryTile label="Funds Shown" value={String(funds.length)} sub={data.metadata.truncated ? `of ${totalFunds}` : undefined} />
        <SummaryTile label="Quarter" value={quarter} />
      </div>

      {/* Filers */}
      {filers.length > 0 && (
        <div>
          <div style={{ fontSize: 12, fontWeight: 700, color: '#4A90D9', marginBottom: 6, display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ display: 'inline-block', width: 10, height: 10, backgroundColor: '#4A90D9', borderRadius: 2 }} /> Filers ({filers.length})
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {filers.map(f => (
              <span key={f.id} style={{ padding: '4px 10px', fontSize: 11, backgroundColor: '#4A90D9', color: '#fff', borderRadius: 4 }}>{f.display_name}{f.aum ? ` · ${fmtAum(f.aum)}` : ''}</span>
            ))}
          </div>
        </div>
      )}

      {/* Owned funds */}
      <div>
        <div style={{ fontSize: 12, fontWeight: 700, color: '#1e293b', marginBottom: 8, display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ display: 'inline-block', width: 10, height: 10, backgroundColor: '#2E7D32', borderRadius: 2 }} /> Owned Funds ({owned.length})
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 6 }}>
          {owned.map(f => (
            <div key={f.id} style={{ padding: '5px 8px', fontSize: 11, backgroundColor: '#fff', border: '1px solid #e2e8f0', borderLeft: '3px solid #2E7D32', borderRadius: 3 }}>
              <div style={{ fontWeight: 600, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }} title={f.display_name}>{f.display_name}</div>
              <div style={{ color: '#64748b', marginTop: 1 }}>{fmtAum(f.aum)}</div>
            </div>
          ))}
          {owned.length === 0 && <div style={{ color: '#94a3b8', fontSize: 13 }}>No fund data</div>}
        </div>
      </div>

      {/* Sub-advised funds */}
      {subAdvised.length > 0 && (
        <div>
          <div style={{ fontSize: 12, fontWeight: 700, color: '#1e293b', marginBottom: 8, display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ display: 'inline-block', width: 10, height: 10, backgroundColor: '#C9B99A', borderRadius: 2 }} /> Sub-Advised Funds ({subAdvised.length})
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 6 }}>
            {subAdvised.map(f => (
              <div key={f.id} style={{ padding: '5px 8px', fontSize: 11, backgroundColor: '#faf9f7', border: '1px solid #C9B99A', borderLeft: '3px solid #C9B99A', borderRadius: 3 }}>
                <div style={{ fontWeight: 600, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }} title={f.display_name}>{f.display_name}</div>
                <div style={{ color: '#8a7d66', marginTop: 1, fontStyle: 'italic' }}>{saMap.get(f.id)} · {fmtAum(f.aum)}</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function SummaryTile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (<div><div style={{ fontSize: 9, fontWeight: 600, textTransform: 'uppercase', color: '#64748b', letterSpacing: '0.08em' }}>{label}</div><div style={{ fontSize: 14, fontWeight: 700, color: '#1e293b' }}>{value}{sub && <span style={{ fontSize: 10, fontWeight: 400, color: '#94a3b8', marginLeft: 4 }}>{sub}</span>}</div></div>)
}

function AumChip({ label, value, count }: { label: string; value: string; count?: number }) {
  return (<div><div style={{ fontSize: 9, fontWeight: 600, textTransform: 'uppercase', color: '#64748b', letterSpacing: '0.08em' }}>{label}</div><div style={{ fontSize: 14, fontWeight: 700, color: '#e2e8f0' }}>{value}{count != null && <span style={{ fontSize: 11, fontWeight: 400, color: '#94a3b8', marginLeft: 4 }}>({count})</span>}</div></div>)
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
