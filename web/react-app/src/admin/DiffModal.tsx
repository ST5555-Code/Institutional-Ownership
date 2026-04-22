import { useEffect, useState } from 'react'
import { Modal } from './Modal'
import { adminJson } from './adminFetch'
import { DiffPayload } from './types'
import { fmtNum, fmtScope } from './format'

interface Props {
  runId: string
  onClose: () => void
  onApproved: () => void
  onRejected: () => void
  onToast: (msg: string, err?: boolean) => void
}

export function DiffModal({ runId, onClose, onApproved, onRejected, onToast }: Props) {
  const [data, setData] = useState<DiffPayload | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState<'approve' | 'reject' | null>(null)

  useEffect(() => {
    let cancelled = false
    adminJson<DiffPayload>(`/api/admin/runs/${runId}/diff`)
      .then(d => { if (!cancelled) setData(d) })
      .catch(e => { if (!cancelled) setErr(e instanceof Error ? e.message : String(e)) })
    return () => { cancelled = true }
  }, [runId])

  async function approve() {
    if (!confirm(`Approve promote of ${fmtNum(data?.summary.inserts ?? 0)} staged rows to production?`)) return
    setBusy('approve')
    try {
      await adminJson(`/api/admin/runs/${runId}/approve`, { method: 'POST' })
      onToast(`Approved ${runId}`)
      onApproved()
    } catch (e) {
      onToast(e instanceof Error ? e.message : String(e), true)
    } finally {
      setBusy(null)
    }
  }

  async function reject() {
    const reason = prompt('Reason for rejection (optional):') ?? ''
    if (!confirm(`Reject run ${runId}? Staging is retained for inspection.`)) return
    setBusy('reject')
    try {
      await adminJson(`/api/admin/runs/${runId}/reject`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason }),
      })
      onToast(`Rejected ${runId}`)
      onRejected()
    } catch (e) {
      onToast(e instanceof Error ? e.message : String(e), true)
    } finally {
      setBusy(null)
    }
  }

  const sampleColumns = data?.sample_rows?.length
    ? Object.keys(data.sample_rows[0]).slice(0, 6)
    : []

  return (
    <Modal
      title={`Diff — ${runId}`}
      onClose={onClose}
      footer={
        <>
          <button className="adm-btn adm-btn-outline" onClick={onClose} disabled={busy !== null}>Close</button>
          <button className="adm-btn adm-btn-danger" onClick={reject} disabled={busy !== null || !data}>
            {busy === 'reject' ? 'Rejecting…' : 'Reject'}
          </button>
          <button className="adm-btn adm-btn-success" onClick={approve} disabled={busy !== null || !data}>
            {busy === 'approve' ? 'Approving…' : 'Approve'}
          </button>
        </>
      }
    >
      {err && <div style={{ color: '#dc2626', fontSize: 13 }}>{err}</div>}
      {!data && !err && <div className="adm-muted">Loading diff…</div>}
      {data && (
        <>
          <div style={{ marginBottom: 14, fontSize: 13 }}>
            <div><b>Pipeline:</b> {data.pipeline_name}</div>
            <div><b>Scope:</b> <span className="adm-mono">{fmtScope(data.scope)}</span></div>
            {data.staged_until && <div><b>Staging expires:</b> {data.staged_until}</div>}
          </div>
          <div className="adm-pending-stats">
            <div className="stat"><span className="v">{fmtNum(data.summary.inserts)}</span><span className="l">Inserts</span></div>
            <div className="stat"><span className="v">{fmtNum(data.summary.flips)}</span><span className="l">Flips</span></div>
            <div className="stat"><span className="v">{fmtNum(data.summary.qc_blocks)}</span><span className="l">QC blocks</span></div>
            <div className="stat"><span className="v">{fmtNum(data.summary.qc_flags)}</span><span className="l">QC flags</span></div>
            <div className="stat"><span className="v">{fmtNum(data.summary.qc_warns)}</span><span className="l">QC warns</span></div>
          </div>
          {data.summary.anomalies?.length > 0 && (
            <div style={{ marginTop: 14, padding: 10, background: '#fef9c3', borderRadius: 4, fontSize: 12, color: '#854d0e' }}>
              <b>Anomalies:</b>
              <ul style={{ marginTop: 6, paddingLeft: 18 }}>
                {data.summary.anomalies.map((a, i) => <li key={i}>{a}</li>)}
              </ul>
            </div>
          )}
          {sampleColumns.length > 0 && (
            <div style={{ marginTop: 16 }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--oxford-blue)', marginBottom: 6 }}>
                Sample rows ({data.sample_rows.length})
              </div>
              <div style={{ maxHeight: 240, overflow: 'auto', border: '1px solid #e2e8f0', borderRadius: 4 }}>
                <table className="adm-table">
                  <thead>
                    <tr>{sampleColumns.map(c => <th key={c}>{c}</th>)}</tr>
                  </thead>
                  <tbody>
                    {data.sample_rows.slice(0, 20).map((row, i) => (
                      <tr key={i}>
                        {sampleColumns.map(c => (
                          <td key={c} className="adm-mono" style={{ fontSize: 11, maxWidth: 180, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {row[c] == null ? '' : String(row[c])}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}
    </Modal>
  )
}
