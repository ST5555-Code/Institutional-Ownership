import { useAppStore } from '../../store/useAppStore'
import type { RollupType } from '../../types/api'

interface Option {
  id: RollupType
  label: string
}

const OPTIONS: Option[] = [
  { id: 'economic_control_v1', label: 'Fund Sponsor' },
  { id: 'decision_maker_v1', label: 'Inv. Decision' },
]

export function RollupToggle() {
  const { rollupType, setRollupType } = useAppStore()
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
      <span
        style={{
          fontSize: 10,
          fontWeight: 600,
          color: '#94a3b8',
          textTransform: 'uppercase',
          letterSpacing: '0.08em',
        }}
      >
        Rollup
      </span>
      <div
        style={{
          display: 'inline-flex',
          gap: 2,
          padding: 2,
          backgroundColor: '#0d1526',
          borderRadius: 6,
        }}
      >
        {OPTIONS.map((o) => {
          const active = o.id === rollupType
          return (
            <button
              key={o.id}
              type="button"
              onClick={() => setRollupType(o.id)}
              style={{
                padding: '5px 12px',
                fontSize: 12,
                fontWeight: active ? 700 : 400,
                color: active ? '#0a0f1e' : '#94a3b8',
                backgroundColor: active ? 'var(--accent-gold)' : '#1a2a4a',
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
    </div>
  )
}
