import { useCallback, useEffect, useRef, useState } from 'react'
import { useFetch } from '../../hooks/useFetch'
import type {
  EntitySearchResult,
  EntityGraphResponse,
  EntityGraphNode,
  EntityGraphEdge,
  MarketSummaryRow,
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

function fmtAum(v: number | null): string {
  if (v == null || v === 0) return '—'
  if (v >= 1e12) return `$${NUM_1.format(v / 1e12)}T`
  if (v >= 1e9) return `$${NUM_1.format(v / 1e9)}B`
  if (v >= 1e6) return `$${NUM_0.format(v / 1e6)}M`
  return `$${NUM_0.format(v)}`
}

// ── Styles ─────────────────────────────────────────────────────────────────

const TH: React.CSSProperties = {
  padding: '7px 10px', fontSize: 11, fontWeight: 700,
  textTransform: 'uppercase', letterSpacing: '0.04em',
  color: '#ffffff', backgroundColor: 'var(--oxford-blue)',
  textAlign: 'left', borderBottom: '1px solid #1e2d47',
  whiteSpace: 'nowrap',
}
const TH_R: React.CSSProperties = { ...TH, textAlign: 'right' }
const TD: React.CSSProperties = {
  padding: '7px 10px', fontSize: 13, color: '#1e293b',
  borderBottom: '1px solid #e5e7eb',
}
const TD_R: React.CSSProperties = {
  ...TD, textAlign: 'right', fontVariantNumeric: 'tabular-nums',
}
const BADGE: React.CSSProperties = {
  display: 'inline-block', padding: '2px 8px', fontSize: 11,
  fontWeight: 600, borderRadius: 3,
}

// ── React Flow layout + nodes (Company mode) ──────────────────────────────

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
    id: `e-${e.from}-${e.to}`, source: e.from, target: e.to,
    style: { stroke: '#002147', strokeWidth: 2 },
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
        .then(r => r.json())
        .then((data: EntitySearchResult[]) => { setResults(data.slice(0, 10)); setOpen(data.length > 0) })
        .catch(() => {})
    }, 300)
  }

  return (
    <div ref={ref} style={{ position: 'relative', display: 'inline-block' }}>
      <input type="text" value={input} placeholder="Search institution…"
        autoComplete="off" autoCorrect="off" spellCheck={false}
        onChange={e => handleInput(e.target.value)}
        onFocus={() => { if (results.length > 0) setOpen(true) }}
        style={{ width: 260, padding: '6px 10px', fontSize: 13, color: '#fff', backgroundColor: '#1a2a4a', border: '1px solid #2d3f5e', borderRadius: 4, outline: 'none' }}
      />
      {open && results.length > 0 && (
        <div style={{ position: 'absolute', top: '100%', left: 0, marginTop: 2, width: 320, maxHeight: 280, overflowY: 'auto', backgroundColor: '#0d1526', border: '1px solid #2d3f5e', borderRadius: 4, boxShadow: '0 4px 12px rgba(0,0,0,0.3)', zIndex: 1000 }}>
          {results.map(r => (
            <div key={r.entity_id} onMouseDown={() => { setInput(r.display_name); setOpen(false); onSelect(r.entity_id, r.display_name) }}
              style={{ padding: '7px 12px', cursor: 'pointer' }}
              onMouseEnter={e => (e.currentTarget.style.backgroundColor = '#1a2a4a')}
              onMouseLeave={e => (e.currentTarget.style.backgroundColor = 'transparent')}>
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
  const [viewMode, setViewMode] = useState<ViewMode>('market')
  const [quarter, setQuarter] = useState('2025Q4')
  const [showSubAdvisers, setShowSubAdvisers] = useState(true)

  // Company mode state
  const [selectedEntityId, setSelectedEntityId] = useState<number | null>(null)
  const [selectedEntityName, setSelectedEntityName] = useState('')
  const [selectedFiler, setSelectedFiler] = useState<string | null>(null)
  const [expanded, setExpanded] = useState(false)
  const [allFundNodes, setAllFundNodes] = useState<EntityGraphNode[]>([])

  // Market mode state
  const [expandedMarketRow, setExpandedMarketRow] = useState<number | null>(null)

  // Market summary fetch
  const marketUrl = viewMode === 'market' ? '/api/entity_market_summary?limit=25' : null
  const market = useFetch<MarketSummaryRow[]>(marketUrl)

  // Company graph fetch
  const graphUrl = viewMode === 'company' && selectedEntityId
    ? `/api/entity_graph?entity_id=${selectedEntityId}&quarter=${enc(quarter)}&depth=2&include_sub_advisers=${showSubAdvisers}&top_n_funds=20`
    : null
  const { data, loading, error } = useFetch<EntityGraphResponse>(graphUrl)

  // Market mode: expanded row graph fetch
  const expandedRowGraphUrl = viewMode === 'market' && expandedMarketRow
    ? `/api/entity_graph?entity_id=${expandedMarketRow}&quarter=${enc(quarter)}&depth=2&include_sub_advisers=${showSubAdvisers}&top_n_funds=20`
    : null
  const expandedGraph = useFetch<EntityGraphResponse>(expandedRowGraphUrl)

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

  // Company mode funds
  const activeCo = viewMode === 'company' ? data : null
  const fundNodes = expanded ? allFundNodes : (activeCo?.nodes.filter(n => n.node_type === 'fund') ?? [])
  const subAdviserNodes = activeCo?.nodes.filter(n => n.node_type === 'sub_adviser') ?? []
  const subAdviserMap = new Map<string, string>()
  if (activeCo) {
    for (const e of activeCo.edges) {
      if (e.relationship_type === 'sub_adviser') {
        const sa = subAdviserNodes.find(n => n.id === e.from)
        if (sa) subAdviserMap.set(e.to, sa.display_name)
      }
    }
  }
  const ownedFunds = fundNodes.filter(f => !subAdviserMap.has(f.id)).map(f => ({ id: f.id, name: f.display_name, aum: f.aum, subAdviser: null as string | null })).sort((a, b) => (b.aum || 0) - (a.aum || 0))
  const subAdvisedFunds = fundNodes.filter(f => subAdviserMap.has(f.id)).map(f => ({ id: f.id, name: f.display_name, aum: f.aum, subAdviser: subAdviserMap.get(f.id) || null })).sort((a, b) => (b.aum || 0) - (a.aum || 0))

  function expandFunds() {
    if (!activeCo || expanded) return
    fetch(`/api/entity_children?entity_id=${activeCo.metadata.root_entity_id}&level=fund&top_n=0`)
      .then(r => r.json())
      .then((children: Array<{ entity_id: number; display_name: string; aum: number | null }>) => {
        setAllFundNodes(children.map(c => ({
          id: `fund-${c.entity_id}`, entity_id: c.entity_id, node_type: 'fund',
          display_name: c.display_name, label: c.display_name, title: c.display_name,
          level: 2, classification: null, aum: c.aum, aum_type: null,
          color: { background: '#2E7D32', border: '#1B5E20' }, font: { color: '#fff' },
        })))
        setExpanded(true)
      }).catch(() => {})
  }

  const handleNodeClick = useCallback((_: React.MouseEvent, node: RFNode) => {
    if (node.type === 'filer') setSelectedFiler(prev => prev === node.id ? null : node.id)
  }, [])

  function onExcel() {
    if (viewMode === 'market' && market.data) {
      const h = ['Rank', 'Institution', 'AUM ($B)', 'Type', 'Filers', 'Funds', 'Holdings']
      const csv = [h, ...market.data.map(r => [r.rank, `"${r.institution}"`, (r.total_aum / 1e9).toFixed(1), r.manager_type || '', r.filer_count, r.fund_count, r.num_holdings])].map(r => r.join(',')).join('\n')
      downloadCsv(csv, 'market_summary.csv')
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
        {/* Mode toggle */}
        <div style={{ display: 'flex', gap: 4 }}>
          {(['market', 'company'] as const).map(m => (
            <button key={m} type="button" onClick={() => setViewMode(m)}
              style={{ padding: '5px 12px', fontSize: 12, borderRadius: 4, cursor: 'pointer', fontWeight: viewMode === m ? 600 : 400, color: viewMode === m ? '#fff' : '#94a3b8', backgroundColor: viewMode === m ? 'var(--oxford-blue)' : '#1a2a4a', border: `1px solid ${viewMode === m ? 'var(--oxford-blue)' : '#2d3f5e'}` }}>
              {m === 'market' ? 'Market' : 'Company'}
            </button>
          ))}
        </div>
        {viewMode === 'company' && <EntitySearch onSelect={(id, name) => { setSelectedEntityId(id); setSelectedEntityName(name) }} />}
        <QuarterSelector quarters={QUARTERS} value={quarter} onChange={q => { setQuarter(q); setExpandedMarketRow(null) }} />
        {viewMode === 'company' && (
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: '#94a3b8', cursor: 'pointer' }}>
            <input type="checkbox" checked={showSubAdvisers} onChange={e => setShowSubAdvisers(e.target.checked)} />
            Sub-Advisers
          </label>
        )}
        <div style={{ marginLeft: 'auto' }}>
          <ExportBar onExcel={onExcel} onPrint={() => window.print()} disabled={viewMode === 'market' ? !market.data : !data} />
        </div>
      </div>

      {/* Content */}
      <div style={{ flex: 1, overflowY: 'auto' }}>
        {/* ── MARKET MODE ── */}
        {viewMode === 'market' && (
          <div style={{ padding: 16, backgroundColor: 'var(--card-bg)', minHeight: '100%' }}>
            {market.loading && <div style={{ padding: 40, color: '#94a3b8', textAlign: 'center' }}>Loading market summary…</div>}
            {market.error && <div style={{ padding: 40, color: '#ef4444', textAlign: 'center' }}>Error: {market.error}</div>}
            {market.data && (() => {
              const NUM_3B = new Intl.NumberFormat('en-US', { minimumFractionDigits: 3, maximumFractionDigits: 3 })
              const NUM_P1 = new Intl.NumberFormat('en-US', { minimumFractionDigits: 1, maximumFractionDigits: 1 })
              const totalAum = market.data.reduce((s, r) => s + r.total_aum, 0)
              const totalFilers = market.data.reduce((s, r) => s + r.filer_count, 0)
              const totalFunds = market.data.reduce((s, r) => s + r.fund_count, 0)
              const totalHoldings = market.data.reduce((s, r) => s + r.num_holdings, 0)
              const COLS = 9
              const FC: React.CSSProperties = { padding: '7px 10px', fontSize: 13, fontWeight: 600, color: '#fff', backgroundColor: 'var(--oxford-blue)', position: 'sticky', bottom: 0, zIndex: 2, borderTop: '2px solid var(--oxford-blue)' }
              const FCR: React.CSSProperties = { ...FC, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }
              return (
              <table style={{ width: '100%', borderCollapse: 'separate', borderSpacing: 0, fontSize: 13 }}>
                <thead>
                  <tr>
                    <th style={{ ...TH, width: 40 }}>#</th>
                    <th style={TH}>Institution</th>
                    <th style={TH}>Type</th>
                    <th style={TH_R}>AUM ($B)</th>
                    <th style={TH_R}>% of Total</th>
                    <th style={TH_R}>Filers</th>
                    <th style={TH_R}>Funds</th>
                    <th style={TH_R}>Holdings</th>
                    <th style={TH_R}>Fund Cov %</th>
                  </tr>
                </thead>
                <tbody>
                  {market.data.map(r => {
                    const isExpanded = expandedMarketRow === r.entity_id
                    const ts = getTypeStyle(r.manager_type)
                    const pctOfTotal = totalAum > 0 ? (r.total_aum / totalAum * 100) : 0
                    const covStyle = r.nport_coverage_pct != null && r.nport_coverage_pct > 0
                      ? r.nport_coverage_pct >= 80 ? { color: '#27AE60' }
                        : r.nport_coverage_pct >= 50 ? { color: '#F5A623' }
                        : { color: '#94a3b8' }
                      : { color: '#cbd5e1' }
                    return [
                      <tr key={r.rank}
                        onClick={() => setExpandedMarketRow(isExpanded ? null : r.entity_id)}
                        style={{ cursor: 'pointer', backgroundColor: isExpanded ? '#eff6ff' : undefined }}>
                        <td style={{ ...TD, textAlign: 'right', fontWeight: 700, color: '#64748b' }}>{r.rank}</td>
                        <td style={{ ...TD, fontWeight: 600 }}>
                          <span style={{ display: 'inline-block', width: 14, color: '#64748b', fontSize: 10 }}>
                            {isExpanded ? '▼' : '▶'}
                          </span>
                          {r.institution}
                        </td>
                        <td style={TD}><span style={{ ...BADGE, backgroundColor: ts.bg, color: ts.color }}>{ts.label}</span></td>
                        <td style={TD_R}>{NUM_3B.format(r.total_aum / 1e9)}</td>
                        <td style={TD_R}>{NUM_P1.format(pctOfTotal)}%</td>
                        <td style={TD_R}>{NUM_0.format(r.filer_count)}</td>
                        <td style={TD_R}>{NUM_0.format(r.fund_count)}</td>
                        <td style={TD_R}>{NUM_0.format(r.num_holdings)}</td>
                        <td style={{ ...TD_R, ...covStyle, fontWeight: 600 }}>
                          {r.nport_coverage_pct != null && r.nport_coverage_pct > 0 ? `${Math.round(r.nport_coverage_pct)}%` : '—'}
                        </td>
                      </tr>,
                      isExpanded && r.entity_id && (
                        <tr key={`${r.rank}-detail`}>
                          <td colSpan={COLS} style={{ padding: 0, borderBottom: '2px solid var(--oxford-blue)' }}>
                            <MarketRowDetail data={expandedGraph.data} loading={expandedGraph.loading} quarter={quarter} />
                          </td>
                        </tr>
                      ),
                    ]
                  }).flat().filter(Boolean)}
                </tbody>
                <tfoot>
                  <tr>
                    <td style={FC} />
                    <td style={FC}>Top {market.data.length} Total</td>
                    <td style={FC} />
                    <td style={FCR}>{NUM_3B.format(totalAum / 1e9)}</td>
                    <td style={FCR}>100.0%</td>
                    <td style={FCR}>{NUM_0.format(totalFilers)}</td>
                    <td style={FCR}>{NUM_0.format(totalFunds)}</td>
                    <td style={FCR}>{NUM_0.format(totalHoldings)}</td>
                    <td style={FC} />
                  </tr>
                </tfoot>
              </table>
              )
            })()}
          </div>
        )}

        {/* ── COMPANY MODE ── */}
        {viewMode === 'company' && (
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
                    <Background color="#1e2d47" gap={20} />
                    <Controls style={{ bottom: 10, left: 10 }} />
                  </ReactFlow>
                </div>
                {/* AUM bar */}
                <div style={{ display: 'flex', gap: 32, padding: '10px 20px', backgroundColor: 'var(--sidebar-bg)', borderBottom: '1px solid #1e2d47' }}>
                  <AumChip label="Total AUM" value={fmtAum(data.nodes.find(n => n.node_type === 'institution')?.aum ?? null)} />
                  <AumChip label="Owned Funds" value={fmtAum(ownedFunds.reduce((s, f) => s + (f.aum || 0), 0))} count={ownedFunds.length} />
                  {subAdvisedFunds.length > 0 && <AumChip label="Sub-Advised" value={fmtAum(subAdvisedFunds.reduce((s, f) => s + (f.aum || 0), 0))} count={subAdvisedFunds.length} />}
                  <AumChip label="Filers" value={String(data.metadata.filer_count)} />
                  {selectedFiler && <span style={{ fontSize: 11, color: '#64748b', alignSelf: 'center' }}>Filer selected: {selectedFiler}</span>}
                  {data.metadata.truncated && !expanded && (
                    <button type="button" onClick={expandFunds} style={{ padding: '4px 12px', fontSize: 11, color: 'var(--glacier-blue)', backgroundColor: 'transparent', border: '1px solid var(--glacier-blue)', borderRadius: 4, cursor: 'pointer', alignSelf: 'center' }}>
                      Show all funds ({Object.values(data.metadata.total_funds_by_filer).reduce((a, b) => a + b, 0)})
                    </button>
                  )}
                  {expanded && <span style={{ fontSize: 11, color: '#27AE60', alignSelf: 'center' }}>✓ All funds loaded</span>}
                </div>
                {/* Fund grids */}
                <div style={{ display: 'flex', gap: 0, flex: 1 }}>
                  <div style={{ flex: subAdvisedFunds.length > 0 ? 3 : 1, padding: 16, overflowY: 'auto', borderRight: subAdvisedFunds.length > 0 ? '1px solid #e2e8f0' : undefined }}>
                    <div style={{ fontSize: 12, fontWeight: 700, color: '#1e293b', marginBottom: 10, display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{ display: 'inline-block', width: 10, height: 10, backgroundColor: '#2E7D32', borderRadius: 2 }} />
                      Owned Funds ({ownedFunds.length})
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 8 }}>
                      {ownedFunds.map(f => <FundCard key={f.id} fund={f} />)}
                    </div>
                    {ownedFunds.length === 0 && <div style={{ color: '#94a3b8', fontSize: 13 }}>No fund data available</div>}
                  </div>
                  {subAdvisedFunds.length > 0 && (
                    <div style={{ flex: 2, padding: 16, overflowY: 'auto', backgroundColor: '#faf9f7' }}>
                      <div style={{ fontSize: 12, fontWeight: 700, color: '#1e293b', marginBottom: 10, display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span style={{ display: 'inline-block', width: 10, height: 10, backgroundColor: '#C9B99A', borderRadius: 2 }} />
                        Sub-Advised Funds ({subAdvisedFunds.length})
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
      </div>
    </div>
  )
}

// ── Market row expanded detail ─────────────────────────────────────────────

function MarketRowDetail({ data, loading, quarter }: {
  data: EntityGraphResponse | null; loading: boolean; quarter: string
}) {
  if (loading) return <div style={{ padding: 20, color: '#94a3b8', fontSize: 13 }}>Loading structure…</div>
  if (!data) return <div style={{ padding: 20, color: '#94a3b8', fontSize: 13 }}>Select to load</div>

  const filers = data.nodes.filter(n => n.node_type === 'filer')
  const funds = data.nodes.filter(n => n.node_type === 'fund')
  const instAum = data.nodes.find(n => n.node_type === 'institution')?.aum

  return (
    <div style={{ padding: '12px 20px 16px', backgroundColor: '#f8fafc', display: 'flex', flexDirection: 'column', gap: 12, color: '#1e293b' }}>
      {/* Summary tiles */}
      <div style={{ display: 'flex', gap: 24 }}>
        <SummaryTile label="Total AUM" value={fmtAum(instAum ?? null)} />
        <SummaryTile label="Filers" value={String(filers.length)} />
        <SummaryTile label="Top Funds" value={String(funds.length)} sub={data.metadata.truncated ? `of ${Object.values(data.metadata.total_funds_by_filer).reduce((a, b) => a + b, 0)}` : undefined} />
        <SummaryTile label="Quarter" value={quarter} />
      </div>
      {/* Filers row */}
      {filers.length > 0 && (
        <div>
          <div style={{ fontSize: 11, fontWeight: 700, color: '#4A90D9', marginBottom: 6 }}>Filers ({filers.length})</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {filers.slice(0, 12).map(f => (
              <span key={f.id} style={{ padding: '3px 8px', fontSize: 10, backgroundColor: '#4A90D9', color: '#fff', borderRadius: 3, whiteSpace: 'nowrap' }}>{f.display_name}</span>
            ))}
            {filers.length > 12 && <span style={{ padding: '3px 8px', fontSize: 10, color: '#64748b' }}>+{filers.length - 12} more</span>}
          </div>
        </div>
      )}
      {/* Funds grid */}
      {funds.length > 0 && (
        <div>
          <div style={{ fontSize: 11, fontWeight: 700, color: '#2E7D32', marginBottom: 6 }}>Top Funds ({funds.length})</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 6 }}>
            {funds.map(f => (
              <div key={f.id} style={{ padding: '5px 8px', fontSize: 10, backgroundColor: '#fff', border: '1px solid #e2e8f0', borderLeft: '3px solid #2E7D32', borderRadius: 3 }}>
                <div style={{ fontWeight: 600, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }} title={f.display_name}>{f.display_name}</div>
                <div style={{ color: '#64748b', marginTop: 1 }}>{fmtAum(f.aum)}</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function SummaryTile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div>
      <div style={{ fontSize: 9, fontWeight: 600, textTransform: 'uppercase', color: '#64748b', letterSpacing: '0.08em' }}>{label}</div>
      <div style={{ fontSize: 14, fontWeight: 700, color: '#1e293b' }}>
        {value}
        {sub && <span style={{ fontSize: 10, fontWeight: 400, color: '#94a3b8', marginLeft: 4 }}>{sub}</span>}
      </div>
    </div>
  )
}

function AumChip({ label, value, count }: { label: string; value: string; count?: number }) {
  return (
    <div>
      <div style={{ fontSize: 9, fontWeight: 600, textTransform: 'uppercase', color: '#64748b', letterSpacing: '0.08em' }}>{label}</div>
      <div style={{ fontSize: 14, fontWeight: 700, color: '#e2e8f0' }}>
        {value}{count != null && <span style={{ fontSize: 11, fontWeight: 400, color: '#94a3b8', marginLeft: 4 }}>({count})</span>}
      </div>
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
