import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { useFetch } from '../../hooks/useFetch'
import { FreshnessBadge, PageHeader } from '../common'

interface DataSourcesPayload {
  content: string
  last_modified: string
}

const WRAP: React.CSSProperties = {
  height: '100%',
  display: 'flex',
  flexDirection: 'column',
  backgroundColor: 'var(--panel)',
  borderRadius: 0,
  boxShadow: '0 1px 2px rgba(0,0,0,0.04)',
  overflow: 'hidden',
}
const HEADER: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 10,
  padding: '8px 12px',
  backgroundColor: 'var(--panel)',
  borderBottom: '1px solid var(--line)',
  flexShrink: 0,
}
const SUB: React.CSSProperties = {
  fontSize: 11,
  color: 'var(--text-dim)',
}
const BODY: React.CSSProperties = {
  flex: 1,
  overflowY: 'auto',
  padding: '24px 32px',
  color: 'var(--text)',
  fontSize: 13,
  lineHeight: 1.6,
}
const CENTER_MSG: React.CSSProperties = { padding: 40, fontSize: 14, textAlign: 'center' }

function fmtDate(iso: string): string {
  try {
    return new Date(iso).toISOString().slice(0, 10)
  } catch {
    return iso
  }
}

export function DataSourceTab() {
  const { data, loading, error } = useFetch<DataSourcesPayload>('/api/v1/data-sources')

  return (
    <div style={WRAP}>
      <PageHeader
        section="Reference"
        title="Data Source"
        description="Filing coverage, data freshness, and pipeline status across all SEC data sources."
      />
      <div style={HEADER}>
        {data && <div style={SUB}>Last updated: {fmtDate(data.last_modified)}</div>}
        <div style={{ marginLeft: 'auto' }}>
          <FreshnessBadge tableName="holdings_v2" label="13F" />
        </div>
      </div>

      <div style={BODY}>
        {loading && <div style={{ ...CENTER_MSG, color: 'var(--text-dim)' }}>Loading…</div>}
        {error && !loading && (
          <div style={{ ...CENTER_MSG, color: 'var(--neg)' }}>Error: {error}</div>
        )}
        {data && !loading && (
          <div className="ds-markdown">
            <style>{`
              .ds-markdown { color: var(--text); }
              .ds-markdown h1 { font-size: 22px; font-weight: 700; color: var(--white); font-family: 'Hanken Grotesk', sans-serif; margin: 0 0 16px; padding-bottom: 8px; border-bottom: 2px solid var(--gold); }
              .ds-markdown h2 { font-size: 17px; font-weight: 700; color: var(--white); font-family: 'Hanken Grotesk', sans-serif; margin: 28px 0 10px; padding-bottom: 4px; border-bottom: 1px solid var(--line); }
              .ds-markdown h3 { font-size: 14px; font-weight: 600; color: var(--white); font-family: 'Hanken Grotesk', sans-serif; margin: 20px 0 8px; }
              .ds-markdown p { margin: 0 0 10px; color: var(--text); }
              .ds-markdown ul, .ds-markdown ol { margin: 0 0 12px 20px; padding: 0; color: var(--text); }
              .ds-markdown li { margin-bottom: 4px; }
              .ds-markdown strong { color: var(--white); font-weight: 700; }
              .ds-markdown em { color: var(--text-dim); }
              .ds-markdown hr { border: none; border-top: 1px solid var(--line); margin: 24px 0; }
              .ds-markdown code { background: var(--panel-hi); color: var(--gold); font-family: 'JetBrains Mono', monospace; font-size: 12px; padding: 1px 5px; border-radius: 0; }
              .ds-markdown pre { background: var(--bg); color: var(--text); border: 1px solid var(--line); font-family: 'JetBrains Mono', monospace; font-size: 12px; padding: 12px 14px; border-radius: 0; overflow-x: auto; margin: 0 0 14px; line-height: 1.5; }
              .ds-markdown pre code { background: transparent; color: inherit; padding: 0; }
              .ds-markdown table { border-collapse: collapse; width: 100%; margin: 0 0 16px; font-size: 12px; color: var(--text); }
              .ds-markdown th { background: var(--header); color: var(--text-dim); font-family: 'Hanken Grotesk', sans-serif; padding: 6px 10px; text-align: left; font-weight: 700; font-size: 9px; text-transform: uppercase; letter-spacing: 0.16em; border: 1px solid var(--line); }
              .ds-markdown td { padding: 5px 10px; border: 1px solid var(--line-soft); vertical-align: top; }
              .ds-markdown tr:nth-child(even) td { background: rgba(255,255,255,0.015); }
              .ds-markdown a { color: var(--gold); text-decoration: none; }
              .ds-markdown a:hover { text-decoration: underline; }
            `}</style>
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{data.content}</ReactMarkdown>

            {/* TODO p2-06: Add cadence timeline SVG from PIPELINE_CADENCE */}
            <div
              data-timeline-slot
              style={{
                marginTop: 24,
                minHeight: 0,
                /* Reserved for the runtime-generated cadence timeline (design §9). */
              }}
            />
          </div>
        )}
      </div>
    </div>
  )
}
