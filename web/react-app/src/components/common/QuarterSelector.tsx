interface Props {
  quarters: string[]
  value: string
  onChange: (q: string) => void
  disabled?: boolean
  formatLabel?: (q: string) => string
}

export function QuarterSelector({ quarters, value, onChange, disabled, formatLabel }: Props) {
  return (
    <div style={{ display: 'inline-flex' }}>
      {quarters.map((q, i) => {
        const active = q === value
        return (
          <button
            key={q}
            type="button"
            disabled={disabled}
            onClick={() => onChange(q)}
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
              cursor: disabled ? 'not-allowed' : 'pointer',
              opacity: disabled ? 0.5 : 1,
              transition: 'all 0.12s',
            }}
          >
            {formatLabel ? formatLabel(q) : q}
          </button>
        )
      })}
    </div>
  )
}
