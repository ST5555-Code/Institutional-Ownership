interface Props {
  onExcel: () => void
  onPrint: () => void
  disabled?: boolean
}

const BTN_BASE: React.CSSProperties = {
  padding: '5px 12px',
  fontSize: 11,
  fontWeight: 600,
  border: 'none',
  borderRadius: 0,
  cursor: 'pointer',
  fontFamily: "'Inter', sans-serif",
  letterSpacing: '0.06em',
  textTransform: 'uppercase',
}

export function ExportBar({ onExcel, onPrint, disabled }: Props) {
  return (
    <div style={{ display: 'inline-flex', gap: 6 }}>
      <button
        type="button"
        disabled={disabled}
        onClick={onExcel}
        style={{
          ...BTN_BASE,
          color: '#000000',
          backgroundColor: 'var(--pos)',
          opacity: disabled ? 0.4 : 1,
          cursor: disabled ? 'not-allowed' : 'pointer',
        }}
      >
        ↓ Excel
      </button>
      <button
        type="button"
        disabled={disabled}
        onClick={onPrint}
        style={{
          ...BTN_BASE,
          color: 'var(--text-dim)',
          backgroundColor: 'var(--line)',
          opacity: disabled ? 0.4 : 1,
          cursor: disabled ? 'not-allowed' : 'pointer',
        }}
      >
        ⎙ Print
      </button>
    </div>
  )
}
