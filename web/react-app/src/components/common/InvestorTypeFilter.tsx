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

// DarkStyle category palette — translucent fills + colored text per category.
interface CatColor { bg: string; fg: string }
const TYPE_COLORS: Record<string, CatColor> = {
  passive:           { bg: 'rgba(92,140,200,0.12)', fg: '#7aadde' },
  active:            { bg: 'rgba(92,184,122,0.08)', fg: '#5cb87a' },
  hedge_fund:        { bg: 'rgba(224,90,90,0.08)',  fg: '#e05a5a' },
  wealth_management: { bg: 'rgba(197,162,84,0.08)', fg: 'var(--gold)' },
  pension_insurance: { bg: 'rgba(160,130,220,0.12)', fg: '#b09ee0' },
  mixed:             { bg: 'rgba(255,255,255,0.05)', fg: '#9a9aa6' },
  other:             { bg: 'rgba(255,255,255,0.05)', fg: '#9a9aa6' },
}

function labelFor(t: string): string {
  return TYPE_LABELS[t] || t.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

function colorFor(t: string): CatColor {
  return TYPE_COLORS[t] || TYPE_COLORS.other
}

const CHIP_BASE: React.CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 5,
  padding: '4px 10px',
  fontSize: 11,
  fontWeight: 500,
  borderRadius: 1,
  cursor: 'pointer',
  border: '1px solid var(--line)',
  userSelect: 'none',
  transition: 'all 0.12s',
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
          backgroundColor: allSelected ? 'var(--gold)' : 'transparent',
          color: allSelected ? '#000000' : 'var(--text-dim)',
          borderColor: allSelected ? 'var(--gold)' : 'var(--line)',
          fontWeight: allSelected ? 700 : 500,
        }}
      >
        All
      </button>
      {available.map((t) => {
        const isSelected = selected.has(t)
        const c = colorFor(t)
        return (
          <button
            key={t}
            type="button"
            onClick={() => toggle(t)}
            style={{
              ...CHIP_BASE,
              backgroundColor: isSelected ? c.bg : 'transparent',
              color: isSelected ? c.fg : 'var(--text-dim)',
              borderColor: isSelected ? c.fg : 'var(--line)',
            }}
          >
            {labelFor(t)}
          </button>
        )
      })}
    </div>
  )
}
