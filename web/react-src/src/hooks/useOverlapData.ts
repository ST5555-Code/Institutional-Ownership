import { useState, useEffect, useRef } from 'react'
import { OverlapResponse } from '../types/overlap'

interface UseOverlapDataResult {
  data: OverlapResponse | null
  loading: boolean
  error: string | null
}

export function useOverlapData(
  subject: string,
  second: string,
  quarter: string
): UseOverlapDataResult {
  const [data, setData] = useState<OverlapResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    if (!subject || !quarter) return

    // Abort previous request
    if (abortRef.current) abortRef.current.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setLoading(true)
    setError(null)

    const url = second
      ? `/api/two_company_overlap?subject=${encodeURIComponent(subject)}&second=${encodeURIComponent(second)}&quarter=${encodeURIComponent(quarter)}`
      : `/api/two_company_subject?subject=${encodeURIComponent(subject)}&quarter=${encodeURIComponent(quarter)}`

    fetch(url, { signal: controller.signal })
      .then(r => r.json())
      .then((json: OverlapResponse & { error?: string }) => {
        if (json.error) throw new Error(json.error)
        setData(json)
        setLoading(false)
      })
      .catch(err => {
        if (err.name === 'AbortError') return
        setError(err.message || 'Failed to load data')
        setLoading(false)
      })

    return () => controller.abort()
  }, [subject, second, quarter])

  return { data, loading, error }
}
