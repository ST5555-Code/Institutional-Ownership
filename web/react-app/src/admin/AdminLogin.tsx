import { useState } from 'react'
import { AdminDisabledError } from './adminFetch'

interface Props {
  onSuccess: () => void
  disabledMessage?: string | null
}

export function AdminLogin({ onSuccess, disabledMessage }: Props) {
  const [token, setToken] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true); setErr(null)
    try {
      const res = await fetch('/api/admin/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({ token }),
      })
      if (res.status === 503) throw new AdminDisabledError('Admin disabled on server (503)')
      if (!res.ok) { setErr('Invalid token'); return }
      onSuccess()
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="adm-login-wrap">
      <h1>Admin Dashboard</h1>
      {disabledMessage ? (
        <p style={{ color: '#dc2626' }}>{disabledMessage}</p>
      ) : (
        <p>Enter the ADMIN_TOKEN env value to continue.</p>
      )}
      {!disabledMessage && (
        <form onSubmit={submit}>
          <input
            className="adm-input"
            type="password"
            value={token}
            onChange={e => setToken(e.target.value)}
            placeholder="admin token"
            autoFocus
            style={{ marginBottom: 12 }}
          />
          <button type="submit" className="adm-btn adm-btn-primary" disabled={busy || !token} style={{ width: '100%' }}>
            {busy ? 'Signing in…' : 'Sign in'}
          </button>
          {err && <div style={{ color: '#dc2626', fontSize: 12, marginTop: 10 }}>{err}</div>}
        </form>
      )}
    </div>
  )
}
