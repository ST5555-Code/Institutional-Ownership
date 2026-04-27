import { useEffect, useState } from 'react'

export interface TickerOption {
  ticker: string
  name: string
}

// Module-level cache. The ticker universe is small, stable for the
// lifetime of a page load, and consumed from at least three components
// (TickerInput, OverlapAnalysisTab, CrossOwnershipTab). One fetch per
// page; concurrent consumers share the in-flight promise.
let cache: TickerOption[] | null = null
let inflight: Promise<TickerOption[]> | null = null

function loadTickers(): Promise<TickerOption[]> {
  if (cache) return Promise.resolve(cache)
  if (inflight) return inflight
  inflight = fetch('/api/v1/tickers')
    .then((r) => r.json())
    .then((env: { data?: TickerOption[] }) => {
      cache = env?.data ?? []
      return cache
    })
    .catch(() => {
      inflight = null
      return [] as TickerOption[]
    })
  return inflight
}

export function useTickers(): TickerOption[] {
  const [tickers, setTickers] = useState<TickerOption[]>(() => cache ?? [])
  useEffect(() => {
    if (cache) return
    let cancelled = false
    loadTickers().then((t) => {
      if (!cancelled) setTickers(t)
    })
    return () => {
      cancelled = true
    }
  }, [])
  return tickers
}
