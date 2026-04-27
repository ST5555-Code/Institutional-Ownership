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
          backgroundColor: '#1a2a4a', border: '1px solid #2d3f5e',
          borderRadius: '4px', color: '#ffffff', padding: '6px 10px',
          fontSize: '13px', width: '140px', outline: 'none'
        }}
      />
      {open && (
        <div style={{
          position: 'absolute', top: '100%', left: 0, zIndex: 1000,
          backgroundColor: '#0d1526', border: '1px solid #2d3f5e',
          borderRadius: '4px', marginTop: '2px', width: '260px',
          maxHeight: '300px', overflowY: 'auto'
        }}>
          {options.map(o => (
            <div key={o.ticker} onMouseDown={() => select(o.ticker)} style={{
              padding: '7px 12px', cursor: 'pointer', display: 'flex',
              gap: '10px', alignItems: 'center'
            }}
            onMouseEnter={e => (e.currentTarget.style.backgroundColor = '#1a2a4a')}
            onMouseLeave={e => (e.currentTarget.style.backgroundColor = 'transparent')}
            >
              <span style={{ color: '#f5a623', fontWeight: 700, width: '52px', flexShrink: 0 }}>{o.ticker}</span>
              <span style={{ color: '#94a3b8', fontSize: '12px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{o.name}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
