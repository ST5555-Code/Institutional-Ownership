interface Props {
  quarters: string[]
  value: string
  onChange: (q: string) => void
  disabled?: boolean
}

export function QuarterSelector({ quarters, value, onChange, disabled }: Props) {
  return (
    <div style={{ display: 'flex', gap: 6 }}>
      {quarters.map((q) => {
        const active = q === value
        return (
          <button
            key={q}
            type="button"
            disabled={disabled}
            onClick={() => onChange(q)}
            style={{
              padding: '5px 12px',
              fontSize: 12,
              fontWeight: active ? 600 : 400,
              color: active ? '#ffffff' : '#64748b',
              backgroundColor: active ? 'var(--oxford-blue)' : '#ffffff',
              border: `1px solid ${active ? 'var(--oxford-blue)' : '#e2e8f0'}`,
              borderRadius: 4,
              cursor: disabled ? 'not-allowed' : 'pointer',
              opacity: disabled ? 0.5 : 1,
              transition: 'background 0.1s, color 0.1s',
            }}
          >
            {q}
          </button>
        )
      })}
    </div>
  )
}
