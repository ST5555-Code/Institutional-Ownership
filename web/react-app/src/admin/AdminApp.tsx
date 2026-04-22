import { useCallback, useEffect, useRef, useState } from 'react'
import { AdminAuthError, AdminDisabledError, adminJson, adminLogout } from './adminFetch'
import { StatusPayload, ProbeResult } from './types'
import { AdminLogin } from './AdminLogin'
import { StatusTable } from './StatusTable'
import { PendingCards } from './PendingCards'
import { Reminders } from './Reminders'
import { RefreshModal } from './RefreshModal'
import { DiffModal } from './DiffModal'
import { fmtRelative } from './format'

type AuthState = 'checking' | 'authed' | 'login' | 'disabled'

const POLL_MS = 30_000

export function AdminApp() {
  const [auth, setAuth] = useState<AuthState>('checking')
  const [disabledMsg, setDisabledMsg] = useState<string | null>(null)
  const [status, setStatus] = useState<StatusPayload | null>(null)
  const [probes, setProbes] = useState<Record<string, ProbeResult>>({})
  const [err, setErr] = useState<string | null>(null)
  const [refreshFor, setRefreshFor] = useState<string | null>(null)
  const [diffFor, setDiffFor] = useState<string | null>(null)
  const [toast, setToast] = useState<{ msg: string; err: boolean } | null>(null)
  const [probingAll, setProbingAll] = useState(false)
  const pollRef = useRef<number | null>(null)

  const showToast = useCallback((msg: string, isErr = false) => {
    setToast({ msg, err: isErr })
    window.setTimeout(() => setToast(null), 4000)
  }, [])

  const loadStatus = useCallback(async () => {
    try {
      const d = await adminJson<StatusPayload>('/api/admin/status')
      setStatus(d)
      setErr(null)
      setAuth('authed')
    } catch (e) {
      if (e instanceof AdminAuthError) { setAuth('login'); return }
      if (e instanceof AdminDisabledError) {
        setAuth('disabled')
        setDisabledMsg('Admin disabled on server — set ENABLE_ADMIN=1 and ADMIN_TOKEN, then restart.')
        return
      }
      setErr(e instanceof Error ? e.message : String(e))
    }
  }, [])

  useEffect(() => { loadStatus() }, [loadStatus])

  // 30-second polling, pauses when tab hidden.
  useEffect(() => {
    if (auth !== 'authed') return
    const tick = () => { if (!document.hidden) loadStatus() }
    pollRef.current = window.setInterval(tick, POLL_MS)
    const onVis = () => { if (!document.hidden) loadStatus() }
    document.addEventListener('visibilitychange', onVis)
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current)
      document.removeEventListener('visibilitychange', onVis)
    }
  }, [auth, loadStatus])

  async function probeOne(pipeline: string) {
    try {
      const p = await adminJson<ProbeResult>(`/api/admin/probe/${pipeline}?force=true`)
      setProbes(prev => ({ ...prev, [pipeline]: p }))
    } catch (e) {
      setProbes(prev => ({ ...prev, [pipeline]: {
        pipeline, new_count: null, latest_accession: null, probed_at: null,
        error: e instanceof Error ? e.message : String(e),
      } }))
    }
  }

  async function probeAll() {
    if (!status) return
    setProbingAll(true)
    try {
      await Promise.all(status.pipelines.map(p => probeOne(p.name)))
    } finally {
      setProbingAll(false)
    }
  }

  async function logout() {
    await adminLogout()
    setStatus(null)
    setAuth('login')
  }

  if (auth === 'checking') {
    return <div style={{ padding: 40, textAlign: 'center', color: '#64748b' }}>Loading…</div>
  }
  if (auth === 'disabled') {
    return <AdminLogin onSuccess={() => setAuth('checking')} disabledMessage={disabledMsg} />
  }
  if (auth === 'login') {
    return <AdminLogin onSuccess={() => { setAuth('checking'); loadStatus() }} />
  }

  const lastProbeAt = status?.last_probe_at ?? null

  return (
    <>
      <div className="adm-header">
        <h1>13F Pipeline Dashboard</h1>
        <div style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
          <a href="/admin">← Legacy admin tools</a>
          <a href="/">Research app</a>
          <button className="link" onClick={logout}>Logout</button>
        </div>
      </div>

      <div className="adm-container">
        {err && (
          <div className="adm-card" style={{ background: '#fef2f2', borderLeft: '4px solid #dc2626' }}>
            <div style={{ color: '#991b1b', fontSize: 13 }}>
              <b>Error:</b> {err}
              <button className="adm-btn adm-btn-outline" style={{ marginLeft: 12 }} onClick={loadStatus}>Retry</button>
            </div>
          </div>
        )}

        {status && (
          <Reminders
            pipelines={status.pipelines}
            probes={probes}
            onRefresh={name => setRefreshFor(name)}
          />
        )}

        <div className="adm-card">
          <h2>
            <span>Pipeline status</span>
            <span style={{ display: 'flex', gap: 10, alignItems: 'center', fontWeight: 400 }}>
              {lastProbeAt && <span className="adm-muted" style={{ fontSize: 11 }}>probes {fmtRelative(lastProbeAt)}</span>}
              <button className="adm-btn adm-btn-outline" onClick={probeAll} disabled={probingAll || !status}>
                {probingAll ? 'Probing…' : 'Check all probes'}
              </button>
              <button className="adm-btn adm-btn-outline" onClick={loadStatus}>Refresh</button>
            </span>
          </h2>
          {!status ? (
            <div className="adm-muted">Loading…</div>
          ) : (
            <StatusTable
              pipelines={status.pipelines}
              probes={probes}
              onRefresh={name => setRefreshFor(name)}
              onProbeOne={probeOne}
            />
          )}
        </div>

        {status && (
          <div className="adm-card">
            <h2>
              <span>Pending approval ({status.pending_runs.length})</span>
            </h2>
            <PendingCards
              pending={status.pending_runs}
              onViewDiff={runId => setDiffFor(runId)}
            />
          </div>
        )}
      </div>

      {refreshFor && (
        <RefreshModal
          pipeline={refreshFor}
          onClose={() => setRefreshFor(null)}
          onStarted={runIdPlaceholder => {
            setRefreshFor(null)
            showToast(`Started: ${runIdPlaceholder}`)
            loadStatus()
          }}
        />
      )}

      {diffFor && (
        <DiffModal
          runId={diffFor}
          onClose={() => setDiffFor(null)}
          onApproved={() => { setDiffFor(null); loadStatus() }}
          onRejected={() => { setDiffFor(null); loadStatus() }}
          onToast={showToast}
        />
      )}

      {toast && (
        <div className={`adm-toast${toast.err ? ' error' : ''}`}>{toast.msg}</div>
      )}
    </>
  )
}
