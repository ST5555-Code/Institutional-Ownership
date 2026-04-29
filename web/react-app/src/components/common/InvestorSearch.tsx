import { useState } from 'react'

interface Props {
  value: string
  onChange: (v: string) => void
  placeholder?: string
}

export function InvestorSearch({ value, onChange, placeholder = 'Search investor…' }: Props) {
  const [focused, setFocused] = useState(false)
  return (
    <div style={{ position: 'relative', display: 'inline-block' }}>
      <input
        type="text"
        value={value}
        placeholder={placeholder}
        autoComplete="off"
        autoCorrect="off"
        spellCheck={false}
        onChange={(e) => onChange(e.target.value)}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        style={{
          width: 200,
          padding: '6px 28px 6px 10px',
          fontSize: 13,
          color: 'var(--text)',
          backgroundColor: 'var(--bg)',
          border: `1px solid ${focused ? 'var(--gold)' : 'var(--line)'}`,
          borderRadius: 0,
          outline: 'none',
          transition: 'border-color 0.1s',
        }}
      />
      {value && (
        <button
          type="button"
          onClick={() => onChange('')}
          aria-label="Clear search"
          style={{
            position: 'absolute',
            right: 6,
            top: '50%',
            transform: 'translateY(-50%)',
            width: 18,
            height: 18,
            padding: 0,
            lineHeight: '16px',
            fontSize: 14,
            color: 'var(--text-dim)',
            backgroundColor: 'transparent',
            border: 'none',
            cursor: 'pointer',
          }}
        >
          ×
        </button>
      )}
    </div>
  )
}
