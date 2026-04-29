interface Props {
  value: 'hierarchy' | 'fund'
  onChange: (v: 'hierarchy' | 'fund') => void
}

interface Option {
  id: 'hierarchy' | 'fund'
  label: string
}

const OPTIONS: Option[] = [
  { id: 'hierarchy', label: 'Institution' },
  { id: 'fund', label: 'Fund' },
]

export function FundViewToggle({ value, onChange }: Props) {
  return (
    <div
      style={{
        display: 'inline-flex',
        backgroundColor: 'transparent',
      }}
    >
      {OPTIONS.map((o, i) => {
        const active = o.id === value
        return (
          <button
            key={o.id}
            type="button"
            onClick={() => onChange(o.id)}
            style={{
              padding: '5px 12px',
              fontSize: 11,
              fontWeight: active ? 700 : 400,
              color: active ? '#000000' : 'var(--text-dim)',
              backgroundColor: active ? 'var(--gold)' : 'transparent',
              border: '1px solid var(--line)',
              borderLeft: i === 0 ? '1px solid var(--line)' : 'none',
              borderRadius: 0,
              fontFamily: "'Inter', sans-serif",
              letterSpacing: '0.06em',
              textTransform: 'uppercase',
              cursor: 'pointer',
              transition: 'all 0.12s',
            }}
          >
            {o.label}
          </button>
        )
      })}
    </div>
  )
}
