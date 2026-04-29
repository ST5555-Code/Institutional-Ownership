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
          fontSize: 9,
          fontWeight: 700,
          color: 'var(--text-dim)',
          textTransform: 'uppercase',
          letterSpacing: '0.16em',
          fontFamily: "'Hanken Grotesk', sans-serif",
        }}
      >
        Rollup
      </span>
      <div
        style={{
          display: 'inline-flex',
          backgroundColor: 'transparent',
        }}
      >
        {OPTIONS.map((o, i) => {
          const active = o.id === rollupType
          return (
            <button
              key={o.id}
              type="button"
              onClick={() => setRollupType(o.id)}
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
    </div>
  )
}
