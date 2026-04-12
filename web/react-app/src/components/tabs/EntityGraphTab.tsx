import { useCallback, useEffect, useRef, useState } from 'react'
import { useAppStore } from '../../store/useAppStore'
import { useFetch } from '../../hooks/useFetch'
import type {
  EntitySearchResult,
  EntityGraphResponse,
  EntityGraphNode,
  EntityGraphEdge,
} from '../../types/api'
import { QuarterSelector, ExportBar } from '../common'
import ReactFlow, {
  Background, Controls, MiniMap,
  useNodesState, useEdgesState,
  Handle, Position,
} from 'reactflow'
import 'reactflow/dist/style.css'
import type { NodeProps, Node as RFNode, Edge } from 'reactflow'

// ── Formatters ─────────────────────────────────────────────────────────────

const NUM_1 = new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 })
const NUM_0 = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 })

function fmtAum(v: number | null): string {
  if (v == null || v === 0) return '—'
  if (v >= 1e12) return `$${NUM_1.format(v / 1e12)}T`
  if (v >= 1e9) return `$${NUM_1.format(v / 1e9)}B`
  if (v >= 1e6) return `$${NUM_0.format(v / 1e6)}M`
  return `$${NUM_0.format(v)}`
}

// ── Layout algorithm ───────────────────────────────────────────────────────

function hierarchicalLayout(nodes: EntityGraphNode[]): Record<string, { x: number; y: number }> {
  const byLevel: Record<number, EntityGraphNode[]> = {}
  nodes.forEach(n => {
    const lvl = n.level ?? 2
    if (!byLevel[lvl]) byLevel[lvl] = []
    byLevel[lvl].push(n)
  })
  const positions: Record<string, { x: number; y: number }> = {}
  const Y_GAP = 150
  const X_GAP = 180
  Object.entries(byLevel).forEach(([lvl, lvlNodes]) => {
    const y = Number(lvl) * Y_GAP
    const totalWidth = (lvlNodes.length - 1) * X_GAP
    lvlNodes.forEach((n, i) => {
      positions[n.id] = { x: i * X_GAP - totalWidth / 2, y }
    })
  })
  return positions
}

// ── Transform backend → React Flow ─────────────────────────────────────────

function toFlowNodes(backendNodes: EntityGraphNode[]): RFNode[] {
  const positions = hierarchicalLayout(backendNodes)
  return backendNodes.map(n => ({
    id: n.id,
    type: n.node_type,
    position: positions[n.id] || { x: 0, y: 0 },
    data: {
      label: n.display_name || n.label,
      node_type: n.node_type,
      entity_id: n.entity_id,
      classification: n.classification,
      aum: n.aum,
      title: n.title,
      aum_type: n.aum_type,
    },
  }))
}

function toFlowEdges(backendEdges: EntityGraphEdge[]): Edge[] {
  return backendEdges.map(e => ({
    id: `e-${e.from}-${e.to}`,
    source: e.from,
    target: e.to,
    animated: false,
    style: {
      stroke: e.relationship_type === 'sub_adviser' ? '#C9B99A' : '#002147',
      strokeWidth: e.relationship_type === 'sub_adviser' ? 1 : 2,
      strokeDasharray: e.relationship_type === 'sub_adviser' ? '4 4' : undefined,
    },
  }))
}

// ── Custom node components ─────────────────────────────────────────────────

function InstitutionNode({ data }: NodeProps) {
  return (
    <div style={{ backgroundColor: '#002147', color: '#fff', borderRadius: 8, padding: '8px 14px', width: 160, minHeight: 50, textAlign: 'center', fontSize: 12, fontWeight: 600 }}>
      <Handle type="target" position={Position.Top} style={{ visibility: 'hidden' }} />
      <div>{data.label}</div>
      {data.aum != null && <div style={{ fontSize: 10, color: '#94a3b8', marginTop: 2 }}>{fmtAum(data.aum)}</div>}
      <Handle type="source" position={Position.Bottom} style={{ visibility: 'hidden' }} />
    </div>
  )
}

function FilerNode({ data }: NodeProps) {
  return (
    <div style={{ backgroundColor: '#4A90D9', color: '#fff', borderRadius: 6, padding: '6px 12px', width: 140, minHeight: 40, textAlign: 'center', fontSize: 11, fontWeight: 500 }}>
      <Handle type="target" position={Position.Top} style={{ visibility: 'hidden' }} />
      <div>{data.label}</div>
      <Handle type="source" position={Position.Bottom} style={{ visibility: 'hidden' }} />
    </div>
  )
}

function FundNode({ data }: NodeProps) {
  return (
    <div style={{ backgroundColor: '#2E7D32', color: '#fff', borderRadius: 6, padding: '5px 10px', width: 140, minHeight: 36, textAlign: 'center', fontSize: 10, fontWeight: 500 }}>
      <Handle type="target" position={Position.Top} style={{ visibility: 'hidden' }} />
      <div>{data.label}</div>
      <Handle type="source" position={Position.Bottom} style={{ visibility: 'hidden' }} />
    </div>
  )
}

function SubAdviserNode({ data }: NodeProps) {
  return (
    <div style={{ backgroundColor: '#C9B99A', color: '#002147', borderRadius: 6, padding: '5px 10px', width: 140, minHeight: 36, textAlign: 'center', fontSize: 10, fontWeight: 500, border: '1px dashed #8a7d66' }}>
      <Handle type="target" position={Position.Top} style={{ visibility: 'hidden' }} />
      <div>{data.label}</div>
      <Handle type="source" position={Position.Bottom} style={{ visibility: 'hidden' }} />
    </div>
  )
}

function ExpandTriggerNode({ data }: NodeProps) {
  return (
    <div style={{ backgroundColor: '#fff', color: '#999', borderRadius: 6, padding: '4px 8px', width: 120, minHeight: 30, textAlign: 'center', fontSize: 10, border: '1px dashed #ccc', cursor: 'pointer' }}>
      <Handle type="target" position={Position.Top} style={{ visibility: 'hidden' }} />
      <div>{data.label || '+ more funds…'}</div>
      <Handle type="source" position={Position.Bottom} style={{ visibility: 'hidden' }} />
    </div>
  )
}

const nodeTypes = {
  institution: InstitutionNode,
  filer: FilerNode,
  fund: FundNode,
  sub_adviser: SubAdviserNode,
  expand_trigger: ExpandTriggerNode,
}

// ── Entity search with dropdown ────────────────────────────────────────────

function EntitySearch({ onSelect }: { onSelect: (entityId: number, name: string) => void }) {
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
        .then((data: EntitySearchResult[]) => {
          setResults(data.slice(0, 10))
          setOpen(data.length > 0)
        })
        .catch(() => {})
    }, 300)
  }

  function select(r: EntitySearchResult) {
    setInput(r.display_name)
    setOpen(false)
    onSelect(r.entity_id, r.display_name)
  }

  return (
    <div ref={ref} style={{ position: 'relative', display: 'inline-block' }}>
      <input type="text" value={input} placeholder="Search institution…"
        autoComplete="off" autoCorrect="off" spellCheck={false}
        onChange={e => handleInput(e.target.value)}
        onFocus={() => { if (results.length > 0) setOpen(true) }}
        style={{
          width: 260, padding: '6px 10px', fontSize: 13, color: '#fff',
          backgroundColor: '#1a2a4a', border: '1px solid #2d3f5e',
          borderRadius: 4, outline: 'none',
        }}
      />
      {open && results.length > 0 && (
        <div style={{ position: 'absolute', top: '100%', left: 0, marginTop: 2, width: 320, maxHeight: 280, overflowY: 'auto', backgroundColor: '#0d1526', border: '1px solid #2d3f5e', borderRadius: 4, boxShadow: '0 4px 12px rgba(0,0,0,0.3)', zIndex: 1000 }}>
          {results.map(r => (
            <div key={r.entity_id} onMouseDown={() => select(r)}
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
  const { setTicker, setActiveTab } = useAppStore()

  const [selectedEntityId, setSelectedEntityId] = useState<number | null>(null)
  const [selectedEntityName, setSelectedEntityName] = useState<string>('')
  const [quarter, setQuarter] = useState('2025Q4')
  const [showSubAdvisers, setShowSubAdvisers] = useState(true)
  const [selectedNode, setSelectedNode] = useState<Record<string, unknown> | null>(null)

  // Graph fetch
  const graphUrl = selectedEntityId
    ? `/api/entity_graph?entity_id=${selectedEntityId}&quarter=${enc(quarter)}&depth=2&include_sub_advisers=${showSubAdvisers}&top_n_funds=20`
    : null
  const { data, loading, error } = useFetch<EntityGraphResponse>(graphUrl)

  // React Flow state
  const [nodes, setNodes, onNodesChange] = useNodesState([])
  const [edges, setEdges, onEdgesChange] = useEdgesState([])

  // Update React Flow when data changes
  useEffect(() => {
    if (!data) { setNodes([]); setEdges([]); return }
    setNodes(toFlowNodes(data.nodes))
    setEdges(toFlowEdges(data.edges))
  }, [data, setNodes, setEdges])

  function handleEntitySelect(entityId: number, name: string) {
    setSelectedEntityId(entityId)
    setSelectedEntityName(name)
    setSelectedNode(null)
  }

  // Expand trigger click
  const handleNodeClick = useCallback((_: React.MouseEvent, node: RFNode) => {
    if (node.type === 'expand_trigger' && data) {
      // Fetch all fund children and merge
      fetch(`/api/entity_children?entity_id=${data.metadata.root_entity_id}&level=fund&top_n=0`)
        .then(r => r.json())
        .then((children: Array<{ entity_id: number; display_name: string; aum: number | null }>) => {
          if (!data) return
          // Build new fund nodes + edges from children
          const existingIds = new Set(data.nodes.map(n => n.id))
          const newNodes: EntityGraphNode[] = children
            .filter(c => !existingIds.has(`fund-${c.entity_id}`))
            .map(c => ({
              id: `fund-${c.entity_id}`,
              entity_id: c.entity_id,
              node_type: 'fund',
              display_name: c.display_name,
              label: c.display_name,
              title: c.display_name,
              level: 2,
              classification: null,
              aum: c.aum,
              aum_type: null,
              color: { background: '#2E7D32', border: '#1B5E20' },
              font: { color: '#FFFFFF' },
            }))
          // Remove expand trigger node
          const filteredNodes = data.nodes.filter(n => n.node_type !== 'expand_trigger')
          const allNodes = [...filteredNodes, ...newNodes]
          // Add edges from filers to new funds (connect to root filer)
          const rootFiler = data.nodes.find(n => n.node_type === 'filer')
          const newEdges: EntityGraphEdge[] = newNodes.map(n => ({
            from: rootFiler?.id || `filer-${data.metadata.root_entity_id}`,
            to: n.id,
            arrows: 'to',
            dashes: false,
            relationship_type: 'fund_sponsor',
            color: { color: '#002147' },
          }))
          const filteredEdges = data.edges.filter(e => {
            // Remove edges to expand trigger
            return !e.to.includes('expand')
          })
          setNodes(toFlowNodes(allNodes))
          setEdges(toFlowEdges([...filteredEdges, ...newEdges]))
        })
        .catch(() => {})
    } else {
      // Show detail panel
      setSelectedNode(node.data as Record<string, unknown>)
    }
  }, [data, setNodes, setEdges])

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
        <EntitySearch onSelect={handleEntitySelect} />
        <QuarterSelector quarters={QUARTERS} value={quarter} onChange={q => { setQuarter(q); setSelectedNode(null) }} />
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: '#94a3b8', cursor: 'pointer' }}>
          <input type="checkbox" checked={showSubAdvisers} onChange={e => setShowSubAdvisers(e.target.checked)} />
          Sub-Advisers
        </label>
        <div style={{ marginLeft: 'auto' }}>
          <ExportBar onExcel={onExcel} onPrint={() => window.print()} disabled={!data} />
        </div>
      </div>

      {/* Content */}
      <div style={{ flex: 1, display: 'flex', position: 'relative' }}>
        {/* Graph canvas */}
        <div style={{ flex: 1 }}>
          {!selectedEntityId && (
            <div style={{ height: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 12 }}>
              <div style={{ fontSize: 32, color: '#2d3f5e' }}>🔍</div>
              <div style={{ color: '#94a3b8', fontSize: 14 }}>Search for an institution to view its entity graph</div>
            </div>
          )}
          {loading && <div style={{ padding: 40, color: '#94a3b8', fontSize: 14, textAlign: 'center' }}>Loading graph…</div>}
          {error && !loading && <div style={{ padding: 40, color: '#ef4444', fontSize: 14, textAlign: 'center' }}>Error: {error}</div>}
          {data && !loading && (
            <ReactFlow
              nodes={nodes}
              edges={edges}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onNodeClick={handleNodeClick}
              nodeTypes={nodeTypes}
              fitView
              fitViewOptions={{ padding: 0.2 }}
              style={{ backgroundColor: 'var(--shell-bg)' }}
            >
              <Background color="#1e2d47" gap={20} />
              <Controls style={{ bottom: 10, left: 10 }} />
              <MiniMap
                nodeColor={(n) => {
                  if (n.type === 'institution') return '#002147'
                  if (n.type === 'filer') return '#4A90D9'
                  if (n.type === 'fund') return '#2E7D32'
                  if (n.type === 'sub_adviser') return '#C9B99A'
                  return '#999'
                }}
                style={{ bottom: 10, right: selectedNode ? 290 : 10 }}
              />
            </ReactFlow>
          )}
        </div>

        {/* Detail panel */}
        {selectedNode && (
          <div style={{
            width: 280, borderLeft: '3px solid var(--oxford-blue)',
            backgroundColor: 'var(--card-bg)', padding: 16,
            overflowY: 'auto', flexShrink: 0,
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
              <span style={{ fontWeight: 700, fontSize: 14, color: '#1e293b' }}>Node Detail</span>
              <button type="button" onClick={() => setSelectedNode(null)}
                style={{ backgroundColor: 'transparent', border: 'none', fontSize: 18, color: '#94a3b8', cursor: 'pointer' }}>×</button>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <DetailRow label="Name" value={String(selectedNode['label'] || '—')} />
              <DetailRow label="Type" value={String(selectedNode['node_type'] || '—')} />
              {selectedNode['classification'] ? <DetailRow label="Classification" value={String(selectedNode['classification'])} /> : null}
              {selectedNode['aum'] != null ? <DetailRow label="AUM" value={fmtAum(selectedNode['aum'] as number)} /> : null}
              {selectedNode['entity_id'] ? <DetailRow label="Entity ID" value={String(selectedNode['entity_id'])} /> : null}
              {selectedNode['node_type'] === 'filer' && (
                <button type="button" onClick={() => {
                  setTicker(String(selectedNode['label'] || ''))
                  setActiveTab('register')
                }}
                style={{ padding: '6px 10px', fontSize: 12, color: 'var(--glacier-blue)', backgroundColor: 'transparent', border: '1px solid var(--glacier-blue)', borderRadius: 4, cursor: 'pointer', marginTop: 8 }}>
                  View in Register →
                </button>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div style={{ fontSize: 10, fontWeight: 600, textTransform: 'uppercase', color: '#94a3b8', letterSpacing: '0.08em', marginBottom: 1 }}>{label}</div>
      <div style={{ fontSize: 13, color: '#1e293b' }}>{value}</div>
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
