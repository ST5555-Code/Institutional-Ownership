import { PendingRun } from './types'
import { fmtRelative, fmtScope } from './format'

interface Props {
  pending: PendingRun[]
  onViewDiff: (runId: string) => void
}

export function PendingCards({ pending, onViewDiff }: Props) {
  if (pending.length === 0) {
    return <div className="adm-muted" style={{ fontSize: 13 }}>No runs pending approval.</div>
  }
  return (
    <div>
      {pending.map(run => (
        <div key={run.run_id} className="adm-pending-card">
          <h3>{run.pipeline_name}</h3>
          <div className="adm-pending-meta">
            <span className="adm-mono">{run.run_id}</span>
            <span> · scope: <span className="adm-mono">{fmtScope(run.scope)}</span></span>
            <span> · staged {fmtRelative(run.pending_since)}</span>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button className="adm-btn adm-btn-accent" onClick={() => onViewDiff(run.run_id)}>
              View diff
            </button>
          </div>
        </div>
      ))}
    </div>
  )
}
