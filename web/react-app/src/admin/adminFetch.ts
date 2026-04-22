// Mirror of web/templates/admin.html adminFetch:
// - Cookie-based auth (HttpOnly admin_session, Path=/api/admin).
// - 401/403 → one-shot login prompt shared across concurrent callers.
// - 503 → admin disabled server-side.

let loginPromise: Promise<boolean> | null = null

async function doLogin(): Promise<boolean> {
  const token = prompt('Admin token — enter ADMIN_TOKEN env value:')
  if (!token) return false
  const res = await fetch('/api/admin/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'same-origin',
    body: JSON.stringify({ token }),
  })
  if (res.status === 503) {
    throw new Error('Admin disabled on server (503) — set ENABLE_ADMIN=1 and ADMIN_TOKEN')
  }
  return res.ok
}

function requestLogin(): Promise<boolean> {
  if (loginPromise) return loginPromise
  loginPromise = doLogin().finally(() => { loginPromise = null })
  return loginPromise
}

export class AdminAuthError extends Error {}
export class AdminDisabledError extends Error {}

export async function adminFetch(url: string, opts: RequestInit = {}): Promise<Response> {
  const init: RequestInit = { credentials: 'same-origin', ...opts }
  let res = await fetch(url, init)
  if (res.status === 401 || res.status === 403) {
    const ok = await requestLogin()
    if (ok) {
      res = await fetch(url, { credentials: 'same-origin', ...opts })
      if (res.ok) return res
    }
    throw new AdminAuthError('Admin auth failed')
  }
  if (res.status === 503) {
    throw new AdminDisabledError('Admin disabled on server (503)')
  }
  return res
}

export async function adminJson<T>(url: string, opts: RequestInit = {}): Promise<T> {
  const res = await adminFetch(url, opts)
  if (!res.ok) {
    let detail = ''
    try {
      const d = await res.json() as { detail?: { error?: string } | string; error?: string }
      const err = typeof d.detail === 'string' ? d.detail : d.detail?.error ?? d.error
      detail = err ? `: ${err}` : ''
    } catch { /* ignore */ }
    throw new Error(`${res.status} ${res.statusText}${detail}`)
  }
  return res.json() as Promise<T>
}

export async function adminLogout(): Promise<void> {
  try {
    await fetch('/api/admin/logout', { method: 'POST', credentials: 'same-origin' })
  } catch { /* swallow */ }
}
