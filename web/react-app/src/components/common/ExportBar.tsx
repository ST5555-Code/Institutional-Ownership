interface Props {
  onExcel: () => void
  onPrint: () => void
  disabled?: boolean
}

const BTN_BASE: React.CSSProperties = {
  padding: '5px 12px',
  fontSize: 12,
  fontWeight: 500,
  color: '#ffffff',
  border: 'none',
  borderRadius: 4,
  cursor: 'pointer',
}

export function ExportBar({ onExcel, onPrint, disabled }: Props) {
  const style = (bg: string): React.CSSProperties => ({
    ...BTN_BASE,
    backgroundColor: bg,
    opacity: disabled ? 0.4 : 1,
    cursor: disabled ? 'not-allowed' : 'pointer',
  })
  return (
    <div style={{ display: 'inline-flex', gap: 6 }}>
      <button
        type="button"
        disabled={disabled}
        onClick={onExcel}
        style={style('#27AE60')}
      >
        ↓ Excel
      </button>
      <button
        type="button"
        disabled={disabled}
        onClick={onPrint}
        style={style('#475569')}
      >
        ⎙ Print
      </button>
    </div>
  )
}
