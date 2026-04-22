import { useState } from 'react'
import { Modal } from './Modal'
import { adminJson } from './adminFetch'

interface Props {
  pipeline: string
  onClose: () => void
  onStarted: (runIdPlaceholder: string) => void
}

// Default scope hints per pipeline, to reduce typing. The server accepts any
// dict; these are just UX defaults. Blank means "use pipeline default scope".
const SCOPE_HINTS: Record<string, { placeholder: string; sample: string }> = {
  '13f': { placeholder: 'e.g. 2026Q1', sample: '{"quarter":"2026Q1"}' },
  'nport': { placeholder: 'e.g. 2026-01', sample: '{"month":"2026-01"}' },
  'ncen': { placeholder: 'e.g. 2026Q1', sample: '{"quarter":"2026Q1"}' },
  '13dg': { placeholder: 'since last run', sample: '{}' },
  'short_interest': { placeholder: 'since last run', sample: '{}' },
  'market': { placeholder: 'tickers (comma-sep)', sample: '{}' },
}

export function RefreshModal({ pipeline, onClose, onStarted }: Props) {
  const [scope, setScope] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const hint = SCOPE_HINTS[pipeline] ?? { placeholder: 'JSON object or blank', sample: '{}' }

  async function submit() {
    let body: Record<string, unknown> = {}
    const s = scope.trim()
    if (s) {
      if (s.startsWith('{')) {
        try { body = JSON.parse(s) } catch { setErr('Invalid JSON'); return }
      } else if (/^\d{4}Q[1-4]$/.test(s)) {
        body = { quarter: s }
      } else if (/^\d{4}-\d{2}$/.test(s)) {
        body = { month: s }
      } else {
        body = { scope: s }
      }
    }
    setBusy(true); setErr(null)
    try {
      const res = await adminJson<{ run_id_placeholder: string }>(
        `/api/admin/refresh/${pipeline}`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        },
      )
      onStarted(res.run_id_placeholder)
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      title={`Refresh ${pipeline}`}
      onClose={onClose}
      footer={
        <>
          <button className="adm-btn adm-btn-outline" onClick={onClose} disabled={busy}>Cancel</button>
          <button className="adm-btn adm-btn-primary" onClick={submit} disabled={busy}>
            {busy ? 'Starting…' : 'Start refresh'}
          </button>
        </>
      }
    >
      <p style={{ marginBottom: 12, fontSize: 13 }}>
        Trigger a <b>{pipeline}</b> refresh. Leave scope blank to use the pipeline default.
      </p>
      <label style={{ fontSize: 12, color: '#64748b', display: 'block', marginBottom: 4 }}>
        Scope <span className="adm-mono">{hint.sample}</span>
      </label>
      <input
        className="adm-input"
        value={scope}
        onChange={e => setScope(e.target.value)}
        placeholder={hint.placeholder}
        autoFocus
      />
      {err && <div style={{ marginTop: 10, color: '#dc2626', fontSize: 12 }}>{err}</div>}
    </Modal>
  )
}
