import { useEffect, useState } from 'react'
import type { Envelope } from '../types/envelope'

/**
 * Phase 1-B2 — fetch hook for endpoints wrapped in the `{data, error, meta}`
 * envelope. Returns `data` directly (unwrapped) so tab components don't
 * have to do `r?.data?.rows` everywhere. Surfaces envelope-level errors
 * into the standard `error` string — same surface as `useFetch` so
 * migrating a tab from `useFetch` to `useFetchEnvelope` is usually a
 * one-line change.
 *
 * Metadata (`quarter`, `rollup_type`, `generated_at`) is returned too —
 * not required by every tab, but cheap to expose.
 */
export function useFetchEnvelope<T>(url: string | null): {
  data: T | null
  loading: boolean
  error: string | null
  meta: Envelope<T>['meta'] | null
} {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [meta, setMeta] = useState<Envelope<T>['meta'] | null>(null)

  useEffect(() => {
    if (!url) {
      setData(null)
      setLoading(false)
      setError(null)
      setMeta(null)
      return
    }
    let cancelled = false
    const ctrl = new AbortController()
    setLoading(true)
    setError(null)
    fetch(url, { signal: ctrl.signal })
      .then((r) => {
        if (!r.ok && r.status >= 500) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then((json: Envelope<T>) => {
        if (cancelled) return
        if (json?.error) {
          throw new Error(json.error.message || json.error.code)
        }
        setData(json?.data ?? null)
        setMeta(json?.meta ?? null)
        setError(null)
        setLoading(false)
      })
      .catch((e: unknown) => {
        if (cancelled) return
        if (e instanceof DOMException && e.name === 'AbortError') return
        setError(e instanceof Error ? e.message : String(e))
        setData(null)
        setLoading(false)
      })
    return () => {
      cancelled = true
      ctrl.abort()
    }
  }, [url])

  return { data, loading, error, meta }
}
