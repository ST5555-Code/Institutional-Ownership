interface Props {
  value: boolean
  onChange: (v: boolean) => void
  label?: string
}

// Styled pill switch — hides the real <input type="checkbox"> for a11y and
// form semantics, paints the track/thumb with a <div>.

export function ActiveOnlyToggle({ value, onChange, label = 'Active Only' }: Props) {
  return (
    <label
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 8,
        cursor: 'pointer',
        userSelect: 'none',
      }}
    >
      <input
        type="checkbox"
        checked={value}
        onChange={(e) => onChange(e.target.checked)}
        style={{
          position: 'absolute',
          width: 1,
          height: 1,
          padding: 0,
          margin: -1,
          overflow: 'hidden',
          clip: 'rect(0 0 0 0)',
          whiteSpace: 'nowrap',
          border: 0,
        }}
      />
      <div
        style={{
          position: 'relative',
          width: 28,
          height: 16,
          borderRadius: 8,
          backgroundColor: value ? 'var(--glacier-blue)' : '#2d3f5e',
          transition: 'background 0.15s',
          flexShrink: 0,
        }}
      >
        <div
          style={{
            position: 'absolute',
            top: 2,
            left: value ? 14 : 2,
            width: 12,
            height: 12,
            borderRadius: '50%',
            backgroundColor: '#ffffff',
            transition: 'left 0.15s',
            boxShadow: '0 1px 2px rgba(0,0,0,0.2)',
          }}
        />
      </div>
      <span style={{ fontSize: 12, color: '#94a3b8' }}>{label}</span>
    </label>
  )
}
