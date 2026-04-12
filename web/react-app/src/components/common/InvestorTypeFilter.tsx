interface Props {
  available: string[]
  selected: Set<string>
  onChange: (selected: Set<string>) => void
}

const TYPE_LABELS: Record<string, string> = {
  passive: 'Passive',
  active: 'Active',
  hedge_fund: 'Hedge Fund',
  wealth_management: 'Wealth Mgmt',
  pension_insurance: 'Pension / Insurance',
  mixed: 'Mixed',
  other: 'Other',
}

// Background colors when selected. Unselected always uses the neutral
// white/border style so the gold accent reads cleanly on the dark shell.
const TYPE_COLORS: Record<string, string> = {
  passive: '#4A90D9',
  active: '#002147',
  hedge_fund: '#7B2D8B',
  wealth_management: '#2D6A4F',
  pension_insurance: '#B45309',
  mixed: '#475569',
  other: '#475569',
}

function labelFor(t: string): string {
  return TYPE_LABELS[t] || t.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

function colorFor(t: string): string {
  return TYPE_COLORS[t] || TYPE_COLORS.other
}

const CHIP_BASE: React.CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 5,
  padding: '4px 10px',
  fontSize: 12,
  fontWeight: 500,
  borderRadius: 12,
  cursor: 'pointer',
  border: '1px solid #e2e8f0',
  userSelect: 'none',
  transition: 'background 0.1s, color 0.1s, border-color 0.1s',
}

export function InvestorTypeFilter({ available, selected, onChange }: Props) {
  const allSelected = available.length > 0 && available.every((t) => selected.has(t))

  function toggle(t: string) {
    const next = new Set(selected)
    if (next.has(t)) next.delete(t)
    else next.add(t)
    onChange(next)
  }

  function selectAll() {
    onChange(new Set(available))
  }

  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center' }}>
      <button
        type="button"
        onClick={selectAll}
        style={{
          ...CHIP_BASE,
          backgroundColor: allSelected ? 'var(--oxford-blue)' : '#ffffff',
          color: allSelected ? '#ffffff' : '#94a3b8',
          borderColor: allSelected ? 'var(--oxford-blue)' : '#e2e8f0',
        }}
      >
        All
      </button>
      {available.map((t) => {
        const isSelected = selected.has(t)
        const bg = colorFor(t)
        return (
          <button
            key={t}
            type="button"
            onClick={() => toggle(t)}
            style={{
              ...CHIP_BASE,
              backgroundColor: isSelected ? bg : '#ffffff',
              color: isSelected ? '#ffffff' : '#94a3b8',
              borderColor: isSelected ? bg : '#e2e8f0',
            }}
          >
            {labelFor(t)}
          </button>
        )
      })}
    </div>
  )
}
