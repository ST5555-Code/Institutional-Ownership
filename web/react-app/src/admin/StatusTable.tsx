import { PipelineRow, ProbeResult, StalenessStatus } from './types'
import { fmtAge, fmtRelative } from './format'

interface Props {
  pipelines: PipelineRow[]
  probes: Record<string, ProbeResult>
  onRefresh: (pipeline: string) => void
  onProbeOne: (pipeline: string) => void
}

const BADGE_CLASS: Record<StalenessStatus, string> = {
  fresh: 'adm-badge adm-badge-fresh',
  stale: 'adm-badge adm-badge-stale',
  critical: 'adm-badge adm-badge-critical',
  missing: 'adm-badge adm-badge-missing',
  unknown: 'adm-badge adm-badge-missing',
}
const DOT_CLASS: Record<StalenessStatus, string> = {
  fresh: 'adm-dot adm-dot-fresh',
  stale: 'adm-dot adm-dot-stale',
  critical: 'adm-dot adm-dot-critical',
  missing: 'adm-dot adm-dot-missing',
  unknown: 'adm-dot adm-dot-missing',
}

export function StatusTable({ pipelines, probes, onRefresh, onProbeOne }: Props) {
  return (
    <table className="adm-table">
      <thead>
        <tr>
          <th>Pipeline</th>
          <th>Cadence</th>
          <th>Last refresh</th>
          <th>Age</th>
          <th>Status</th>
          <th>New?</th>
          <th>Last run</th>
          <th style={{ textAlign: 'right' }}>Actions</th>
        </tr>
      </thead>
      <tbody>
        {pipelines.map(p => {
          const probe = probes[p.name]
          const running = p.currently_running
          const status: StalenessStatus = (p.staleness_status ?? 'unknown') as StalenessStatus
          return (
            <tr key={p.name}>
              <td>
                <div style={{ fontWeight: 600, color: 'var(--oxford-blue)' }}>
                  <span className={DOT_CLASS[status]} />{p.display_name || p.name}
                </div>
                <div className="adm-muted" style={{ fontSize: 11 }}>{p.name} · {p.target_table ?? '—'}</div>
              </td>
              <td className="adm-muted">{p.cadence ?? '—'}</td>
              <td>{fmtRelative(p.last_refreshed)}</td>
              <td>{fmtAge(p.age_days)}</td>
              <td>
                <span className={BADGE_CLASS[status]}>{status}</span>
                {running && <span className="adm-badge adm-badge-running" style={{ marginLeft: 6 }}>running</span>}
              </td>
              <td>
                {probe?.error ? (
                  <span style={{ color: '#dc2626', fontSize: 11 }}>probe failed</span>
                ) : probe?.new_count != null ? (
                  <span style={{ fontWeight: probe.new_count > 0 ? 700 : 400, color: probe.new_count > 0 ? '#16a34a' : '#64748b' }}>
                    {probe.new_count > 0 ? `+${probe.new_count}` : '0'}
                  </span>
                ) : probe?.note ? (
                  <span className="adm-muted" style={{ fontSize: 11 }}>n/a</span>
                ) : (
                  <button className="adm-btn adm-btn-outline" style={{ padding: '2px 8px', fontSize: 11 }} onClick={() => onProbeOne(p.name)}>
                    check
                  </button>
                )}
              </td>
              <td>
                {p.last_run ? (
                  <div>
                    <div style={{ fontSize: 12 }}>{p.last_run.status}</div>
                    <div className="adm-muted" style={{ fontSize: 11 }}>{fmtRelative(p.last_run.completed_at)}</div>
                  </div>
                ) : <span className="adm-muted">—</span>}
              </td>
              <td style={{ textAlign: 'right' }}>
                <button
                  className="adm-btn adm-btn-primary"
                  onClick={() => onRefresh(p.name)}
                  disabled={!p.registered || !!running}
                  title={!p.registered ? 'Pipeline not registered' : running ? `Already running (${running})` : `Refresh ${p.name}`}
                >
                  Refresh
                </button>
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}
