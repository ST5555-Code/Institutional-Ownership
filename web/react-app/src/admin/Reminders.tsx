import { PipelineRow, ProbeResult } from './types'

interface Props {
  pipelines: PipelineRow[]
  probes: Record<string, ProbeResult>
  onRefresh: (pipeline: string) => void
}

export function Reminders({ pipelines, probes, onRefresh }: Props) {
  const items: { pipeline: PipelineRow; newCount: number }[] = []
  for (const p of pipelines) {
    const probe = probes[p.name]
    if (probe?.new_count && probe.new_count > 0 && !p.currently_running) {
      items.push({ pipeline: p, newCount: probe.new_count })
    }
  }
  if (items.length === 0) return null
  return (
    <div className="adm-card">
      <h2>Reminders</h2>
      {items.map(({ pipeline, newCount }) => (
        <div key={pipeline.name} className="adm-reminder" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <b>{pipeline.display_name || pipeline.name}</b> — {newCount} new filing{newCount === 1 ? '' : 's'} available on EDGAR.
          </div>
          <button className="adm-btn adm-btn-accent" onClick={() => onRefresh(pipeline.name)}>
            Refresh now
          </button>
        </div>
      ))}
    </div>
  )
}
