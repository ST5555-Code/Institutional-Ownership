import { useState, useEffect } from 'react'
import { TickerItem } from '../types/overlap'

// Module-level cache — survives re-mounts
let _cache: TickerItem[] | null = null
let _loading = false
let _listeners: Array<(tickers: TickerItem[]) => void> = []

export function useTickers() {
  const [tickers, setTickers] = useState<TickerItem[]>(_cache || [])
  const [loading, setLoading] = useState(!_cache)

  useEffect(() => {
    if (_cache) {
      setTickers(_cache)
      setLoading(false)
      return
    }
    if (_loading) {
      _listeners.push(setTickers)
      return
    }
    _loading = true
    fetch('/api/tickers')
      .then(r => r.json())
      .then((data: TickerItem[]) => {
        _cache = data
        _loading = false
        setTickers(data)
        setLoading(false)
        _listeners.forEach(fn => fn(data))
        _listeners = []
      })
      .catch(() => {
        _loading = false
        setLoading(false)
      })
  }, [])

  return { tickers, loading }
}
