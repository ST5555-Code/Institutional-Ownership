import { useCallback, useEffect, useRef, useState } from 'react'
// useAppStore available for cross-tab navigation when filer→register is wired
import { useFetch } from '../../hooks/useFetch'
import type {
  EntitySearchResult,
  EntityGraphResponse,
  EntityGraphNode,
  EntityGraphEdge,
} from '../../types/api'
import { QuarterSelector, ExportBar } from '../common'
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

// ── React Flow: Institution + Filer graph only ─────────────────────────────

function layoutFilerGraph(nodes: EntityGraphNode[]): { rfNodes: RFNode[]; graphHeight: number } {
  const inst = nodes.filter(n => n.node_type === 'institution')
  const filers = nodes.filter(n => n.node_type === 'filer')
  const result: RFNode[] = []

  // Institution centered at top
  inst.forEach((n, i) => {
    result.push({ id: n.id, type: 'institution', position: { x: i * 200, y: 0 }, data: { label: n.display_name, aum: n.aum, entity_id: n.entity_id, node_type: n.node_type, classification: n.classification } })
  })

  // Filers in a grid: max COLS_PER_ROW per row, centered
  const COLS = Math.min(filers.length, 6)
  const X_GAP = 170
  const Y_GAP = 80
  const rows = Math.ceil(filers.length / COLS)
  const totalW = (COLS - 1) * X_GAP

  filers.forEach((n, i) => {
    const col = i % COLS
    const row = Math.floor(i / COLS)
    result.push({
      id: n.id, type: 'filer',
      position: { x: col * X_GAP - totalW / 2, y: 120 + row * Y_GAP },
      data: { label: n.display_name, aum: n.aum, entity_id: n.entity_id, node_type: n.node_type, cik: n.id.replace('filer-', '') },
    })
  })

  // Dynamic height: institution row + filer grid rows + padding
  const graphHeight = Math.max(220, 120 + rows * Y_GAP + 60)
  return { rfNodes: result, graphHeight }
}

function filerEdges(edges: EntityGraphEdge[], nodeIds: Set<string>): Edge[] {
  return edges
    .filter(e => nodeIds.has(e.from) && nodeIds.has(e.to))
    .map(e => ({
      id: `e-${e.from}-${e.to}`,
      source: e.from,
      target: e.to,
      style: { stroke: '#002147', strokeWidth: 2 },
    }))
}

// Custom node components
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

interface FundInfo {
  id: string
  name: string
  aum: number | null
  subAdviser: string | null  // external adviser name, null if self-managed
}

function FundCard({ fund }: { fund: FundInfo }) {
  return (
    <div style={{
      padding: '8px 10px', borderRadius: 4,
      border: `1px solid ${fund.subAdviser ? '#C9B99A' : '#e2e8f0'}`,
      borderLeft: `3px solid ${fund.subAdviser ? '#C9B99A' : '#2E7D32'}`,
      backgroundColor: '#fff', fontSize: 11,
    }}>
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
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
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

export function EntityGraphTab() {
  // Local state only — no store dependency (market-structure tab)

  const [selectedEntityId, setSelectedEntityId] = useState<number | null>(null)
  const [selectedEntityName, setSelectedEntityName] = useState('')
  const [quarter, setQuarter] = useState('2025Q4')
  const [showSubAdvisers, setShowSubAdvisers] = useState(true)
  const [selectedFiler, setSelectedFiler] = useState<string | null>(null)

  const graphUrl = selectedEntityId
    ? `/api/entity_graph?entity_id=${selectedEntityId}&quarter=${enc(quarter)}&depth=2&include_sub_advisers=${showSubAdvisers}&top_n_funds=20`
    : null
  const { data, loading, error } = useFetch<EntityGraphResponse>(graphUrl)

  // Expand: fetch all fund children
  const [expanded, setExpanded] = useState(false)
  const [allFundNodes, setAllFundNodes] = useState<EntityGraphNode[]>([])

  useEffect(() => { setExpanded(false); setAllFundNodes([]); setSelectedFiler(null) }, [selectedEntityId, quarter, showSubAdvisers])

  function expandFunds() {
    if (!data || expanded) return
    fetch(`/api/entity_children?entity_id=${data.metadata.root_entity_id}&level=fund&top_n=0`)
      .then(r => r.json())
      .then((children: Array<{ entity_id: number; display_name: string; aum: number | null }>) => {
        const newNodes: EntityGraphNode[] = children.map(c => ({
          id: `fund-${c.entity_id}`, entity_id: c.entity_id, node_type: 'fund',
          display_name: c.display_name, label: c.display_name, title: c.display_name,
          level: 2, classification: null, aum: c.aum, aum_type: null,
          color: { background: '#2E7D32', border: '#1B5E20' }, font: { color: '#fff' },
        }))
        setAllFundNodes(newNodes)
        setExpanded(true)
      })
      .catch(() => {})
  }

  // React Flow: institution + filer nodes only
  const [nodes, setNodes, onNodesChange] = useNodesState([])
  const [edges, setEdges, onEdgesChange] = useEdgesState([])
  const [graphHeight, setGraphHeight] = useState(220)

  useEffect(() => {
    if (!data) { setNodes([]); setEdges([]); setGraphHeight(220); return }
    const graphNodes = data.nodes.filter(n => n.node_type === 'institution' || n.node_type === 'filer')
    const { rfNodes, graphHeight: h } = layoutFilerGraph(graphNodes)
    const nodeIds = new Set(graphNodes.map(n => n.id))
    setNodes(rfNodes)
    setEdges(filerEdges(data.edges, nodeIds))
    setGraphHeight(h)
  }, [data, setNodes, setEdges])

  // Build fund lists from data
  const fundNodes = expanded ? allFundNodes : (data?.nodes.filter(n => n.node_type === 'fund') ?? [])
  const subAdviserNodes = data?.nodes.filter(n => n.node_type === 'sub_adviser') ?? []

  // Build sub-adviser map: fund_id → adviser name (from sub_adviser edges)
  const subAdviserMap = new Map<string, string>()
  if (data) {
    for (const e of data.edges) {
      if (e.relationship_type === 'sub_adviser') {
        const saNode = subAdviserNodes.find(n => n.id === e.from)
        if (saNode) subAdviserMap.set(e.to, saNode.display_name)
      }
    }
  }

  // Split funds into owned vs sub-advised
  const ownedFunds: FundInfo[] = []
  const subAdvisedFunds: FundInfo[] = []
  for (const f of fundNodes) {
    const info: FundInfo = { id: f.id, name: f.display_name, aum: f.aum, subAdviser: subAdviserMap.get(f.id) || null }
    if (info.subAdviser) subAdvisedFunds.push(info)
    else ownedFunds.push(info)
  }
  ownedFunds.sort((a, b) => (b.aum || 0) - (a.aum || 0))
  subAdvisedFunds.sort((a, b) => (b.aum || 0) - (a.aum || 0))

  // AUM totals
  const totalAum = data?.nodes.find(n => n.node_type === 'institution')?.aum ?? null
  const ownedAum = ownedFunds.reduce((s, f) => s + (f.aum || 0), 0)
  const subAdvisedAum = subAdvisedFunds.reduce((s, f) => s + (f.aum || 0), 0)

  const handleNodeClick = useCallback((_: React.MouseEvent, node: RFNode) => {
    if (node.type === 'filer') {
      setSelectedFiler(prev => prev === node.id ? null : node.id)
    }
  }, [])

  function onExcel() {
    if (!data) return
    const h = ['ID', 'Type', 'Name', 'AUM', 'Classification']
    const csv = [h, ...data.nodes.map(n => [
      n.id, n.node_type, `"${n.display_name}"`, n.aum != null ? fmtAum(n.aum) : '', n.classification || '',
    ])].map(r => r.join(',')).join('\n')
    downloadCsv(csv, `entity_graph_${selectedEntityName.replace(/\s+/g, '_')}.csv`)
  }

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', backgroundColor: 'var(--shell-bg)', overflow: 'hidden' }}>
      <style>{`@media print { .eg-controls { display:none!important } }`}</style>

      {/* Controls */}
      <div className="eg-controls" style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'flex-end', gap: 16, padding: '10px 16px', backgroundColor: 'var(--sidebar-bg)', borderBottom: '1px solid #1e2d47', flexShrink: 0 }}>
        <EntitySearch onSelect={(id, name) => { setSelectedEntityId(id); setSelectedEntityName(name) }} />
        <QuarterSelector quarters={QUARTERS} value={quarter} onChange={q => { setQuarter(q); setSelectedFiler(null) }} />
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: '#94a3b8', cursor: 'pointer' }}>
          <input type="checkbox" checked={showSubAdvisers} onChange={e => setShowSubAdvisers(e.target.checked)} />
          Sub-Advisers
        </label>
        <div style={{ marginLeft: 'auto' }}>
          <ExportBar onExcel={onExcel} onPrint={() => window.print()} disabled={!data} />
        </div>
      </div>

      {/* Content */}
      <div style={{ flex: 1, overflowY: 'auto' }}>
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
            {/* Top: Filer graph */}
            {/* Graph height adapts to filer count: 1 filer = compact, 26 filers = taller grid */}
            <div style={{ height: graphHeight, borderBottom: '1px solid #1e2d47', flexShrink: 0 }}>
              <ReactFlow
                nodes={nodes} edges={edges}
                onNodesChange={onNodesChange} onEdgesChange={onEdgesChange}
                onNodeClick={handleNodeClick}
                nodeTypes={nodeTypes}
                fitView fitViewOptions={{ padding: 0.3 }}
                style={{ backgroundColor: 'var(--shell-bg)' }}
                proOptions={{ hideAttribution: true }}
              >
                <Background color="#1e2d47" gap={20} />
                <Controls style={{ bottom: 10, left: 10 }} />
              </ReactFlow>
            </div>

            {/* AUM summary bar */}
            <div style={{ display: 'flex', gap: 32, padding: '10px 20px', backgroundColor: 'var(--sidebar-bg)', borderBottom: '1px solid #1e2d47' }}>
              <AumChip label="Total AUM" value={fmtAum(totalAum)} />
              <AumChip label="Owned Funds" value={fmtAum(ownedAum)} count={ownedFunds.length} />
              {subAdvisedFunds.length > 0 && (
                <AumChip label="Sub-Advised" value={fmtAum(subAdvisedAum)} count={subAdvisedFunds.length} />
              )}
              <AumChip label="Filers" value={String(data.metadata.filer_count)} />
              <AumChip label="Quarter" value={data.metadata.quarter} />
              {data.metadata.truncated && !expanded && (
                <button type="button" onClick={expandFunds}
                  style={{ padding: '4px 12px', fontSize: 11, color: 'var(--glacier-blue)', backgroundColor: 'transparent', border: '1px solid var(--glacier-blue)', borderRadius: 4, cursor: 'pointer', alignSelf: 'center' }}>
                  Show all funds ({Object.values(data.metadata.total_funds_by_filer).reduce((a, b) => a + b, 0)})
                </button>
              )}
              {expanded && <span style={{ fontSize: 11, color: '#27AE60', alignSelf: 'center' }}>✓ All funds loaded</span>}
            </div>

            {/* Fund grids */}
            <div style={{ display: 'flex', gap: 0, flex: 1 }}>
              {/* Owned funds */}
              <div style={{ flex: subAdvisedFunds.length > 0 ? 3 : 1, padding: 16, overflowY: 'auto', borderRight: subAdvisedFunds.length > 0 ? '1px solid #e2e8f0' : undefined }}>
                <div style={{ fontSize: 12, fontWeight: 700, color: '#1e293b', marginBottom: 10, display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ display: 'inline-block', width: 10, height: 10, backgroundColor: '#2E7D32', borderRadius: 2 }} />
                  Owned Funds ({ownedFunds.length})
                  {selectedFiler && <span style={{ fontSize: 10, fontWeight: 400, color: '#64748b' }}>— filtered by filer click</span>}
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 8 }}>
                  {ownedFunds.map(f => <FundCard key={f.id} fund={f} />)}
                </div>
                {ownedFunds.length === 0 && <div style={{ color: '#94a3b8', fontSize: 13 }}>No fund data available</div>}
              </div>

              {/* Sub-advised funds (conditional) */}
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
      </div>
    </div>
  )
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function AumChip({ label, value, count }: { label: string; value: string; count?: number }) {
  return (
    <div>
      <div style={{ fontSize: 9, fontWeight: 600, textTransform: 'uppercase', color: '#64748b', letterSpacing: '0.08em' }}>{label}</div>
      <div style={{ fontSize: 14, fontWeight: 700, color: '#e2e8f0' }}>
        {value}
        {count != null && <span style={{ fontSize: 11, fontWeight: 400, color: '#94a3b8', marginLeft: 4 }}>({count})</span>}
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
