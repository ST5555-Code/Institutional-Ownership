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
        gap: 2,
        padding: 2,
        backgroundColor: '#ffffff',
        border: '1px solid #e2e8f0',
        borderRadius: 6,
      }}
    >
      {OPTIONS.map((o) => {
        const active = o.id === value
        return (
          <button
            key={o.id}
            type="button"
            onClick={() => onChange(o.id)}
            style={{
              padding: '5px 12px',
              fontSize: 12,
              fontWeight: active ? 600 : 400,
              color: active ? '#ffffff' : '#64748b',
              backgroundColor: active ? 'var(--oxford-blue)' : '#f4f6f9',
              border: 'none',
              borderRadius: 4,
              cursor: 'pointer',
              transition: 'background 0.1s, color 0.1s',
            }}
          >
            {o.label}
          </button>
        )
      })}
    </div>
  )
}
