import { useEffect, useState } from 'react'

/**
 * Minimal fetch hook for the React migration. No external deps.
 *
 * Pass `url=null` to disable the fetch (e.g. while the ticker is empty).
 * Handles: AbortController cleanup on URL change / unmount, Flask-style
 * `{error: "..."}` error bodies, and a cancelled-flag guard so that
 * in-flight requests can't overwrite newer state after a re-fetch.
 */
export function useFetch<T>(url: string | null): {
  data: T | null
  loading: boolean
  error: string | null
} {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!url) {
      setData(null)
      setLoading(false)
      setError(null)
      return
    }
    let cancelled = false
    const ctrl = new AbortController()
    setLoading(true)
    setError(null)
    fetch(url, { signal: ctrl.signal })
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then((json) => {
        if (cancelled) return
        if (json && typeof json === 'object' && 'error' in json) {
          throw new Error(String((json as { error: unknown }).error))
        }
        setData(json as T)
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

  return { data, loading, error }
}
