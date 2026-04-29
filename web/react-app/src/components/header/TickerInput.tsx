import { useState, useEffect, useRef } from 'react'
import { useAppStore } from '../../store/useAppStore'
import { useTickers, type TickerOption } from '../../hooks/useTickers'

export function TickerInput() {
  const { loadCompany } = useAppStore()
  const [value, setValue] = useState('')
  const [options, setOptions] = useState<TickerOption[]>([])
  const allTickers = useTickers()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (value.length < 1) { setOptions([]); setOpen(false); return }
    const q = value.toUpperCase()
    const matches = allTickers
      .filter(t => t.ticker.startsWith(q) || t.name?.toUpperCase().includes(q))
      .slice(0, 10)
    setOptions(matches)
    setOpen(matches.length > 0)
  }, [value, allTickers])

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  function select(ticker: string) {
    setValue(ticker)
    setOpen(false)
    loadCompany(ticker)
  }

  return (
    <div ref={ref} style={{ position: 'relative' }}>
      <input
        value={value}
        onChange={e => setValue(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter' && value) select(value.toUpperCase()) }}
        placeholder="Ticker…"
        autoComplete="off"
        autoCorrect="off"
        spellCheck={false}
        style={{
          backgroundColor: 'var(--bg)',
          border: '1px solid var(--line)',
          borderRadius: 0,
          color: 'var(--white)',
          padding: '6px 10px',
          fontSize: '12px',
          fontFamily: "'Inter', sans-serif",
          letterSpacing: '0.04em',
          width: '140px',
          outline: 'none'
        }}
      />
      {open && (
        <div style={{
          position: 'absolute', top: '100%', left: 0, zIndex: 1000,
          backgroundColor: 'var(--panel)',
          border: '1px solid var(--line)',
          borderRadius: 0,
          boxShadow: '0 12px 40px rgba(0,0,0,0.5)',
          marginTop: '2px', width: '260px',
          maxHeight: '300px', overflowY: 'auto'
        }}>
          {options.map(o => (
            <div key={o.ticker} onMouseDown={() => select(o.ticker)} style={{
              padding: '7px 12px', cursor: 'pointer', display: 'flex',
              gap: '10px', alignItems: 'center',
              transition: 'all 0.12s'
            }}
            onMouseEnter={e => (e.currentTarget.style.backgroundColor = 'var(--panel-hi)')}
            onMouseLeave={e => (e.currentTarget.style.backgroundColor = 'transparent')}
            >
              <span style={{
                color: 'var(--gold)',
                fontWeight: 700,
                width: '52px',
                flexShrink: 0,
                fontFamily: "'JetBrains Mono', monospace",
              }}>{o.ticker}</span>
              <span style={{
                color: 'var(--text-dim)',
                fontSize: '12px',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap'
              }}>{o.name}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
