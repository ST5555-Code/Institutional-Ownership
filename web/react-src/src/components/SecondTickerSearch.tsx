import React, { useState, useRef, useEffect, useCallback } from 'react'
import { TickerItem } from '../types/overlap'
import { useTickers } from '../hooks/useTickers'

interface Props {
  value: string
  onChange: (ticker: string) => void
}

export function SecondTickerSearch({ value, onChange }: Props) {
  const { tickers } = useTickers()
  const [inputVal, setInputVal] = useState(value)
  const [open, setOpen] = useState(false)
  const [matches, setMatches] = useState<TickerItem[]>([])
  const wrapRef = useRef<HTMLDivElement>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Close on outside click
  useEffect(() => {
    function handler(e: MouseEvent) {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const search = useCallback((q: string) => {
    if (!q) { setMatches([]); setOpen(false); return }
    const qu = q.toUpperCase()
    const results = tickers
      .filter(t =>
        t.ticker.toUpperCase().startsWith(qu) ||
        (t.name || '').toUpperCase().includes(qu)
      )
      .slice(0, 12)
    setMatches(results)
    setOpen(results.length > 0)
  }, [tickers])

  function handleInput(e: React.ChangeEvent<HTMLInputElement>) {
    const v = e.target.value
    setInputVal(v)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => search(v), 200)
  }

  function handleSelect(item: TickerItem) {
    setInputVal(item.ticker)
    setOpen(false)
    onChange(item.ticker)
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Escape') setOpen(false)
  }

  return (
    <div className="flex flex-col gap-1" ref={wrapRef} style={{ position: 'relative', zIndex: 9999 }}>
      <label className="text-xs font-medium text-gray-600 uppercase tracking-wide">
        Second Company
      </label>
      <div style={{ position: 'relative' }}>
        <input
          type="text"
          value={inputVal}
          onChange={handleInput}
          onKeyDown={handleKeyDown}
          onFocus={() => inputVal && search(inputVal)}
          placeholder="Ticker or company name..."
          className="w-56 px-3 py-1.5 text-sm border border-gray-300 rounded
                     focus:outline-none focus:ring-1 focus:ring-oxford-blue
                     focus:border-oxford-blue"
          autoComplete="off"
        />
        {open && matches.length > 0 && (
          <div
            style={{
              position: 'absolute',
              top: '100%',
              left: 0,
              zIndex: 9999,
              background: '#fff',
              border: '1px solid #ccc',
              borderRadius: '3px',
              maxHeight: '200px',
              overflowY: 'auto',
              minWidth: '280px',
              boxShadow: '0 4px 12px rgba(0,0,0,0.15)',
              marginTop: '4px',
            }}
          >
            {matches.map(item => (
              <div
                key={item.ticker}
                onMouseDown={() => handleSelect(item)}
                className="px-3 py-2 cursor-pointer hover:bg-blue-50
                           border-b border-gray-100 last:border-0"
              >
                <span className="font-semibold text-sm text-gray-900">
                  {item.ticker}
                </span>
                <span className="ml-2 text-xs text-gray-500 truncate">
                  {item.name}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
