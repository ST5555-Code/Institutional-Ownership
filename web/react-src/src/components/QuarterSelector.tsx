import { useState, useEffect } from 'react'

interface Props {
  value: string
  onChange: (quarter: string) => void
}

export function QuarterSelector({ value, onChange }: Props) {
  const [quarters, setQuarters] = useState<string[]>([])

  useEffect(() => {
    fetch('/api/admin/quarter_config')
      .then(r => r.json())
      .then(data => {
        const qs: string[] = [...(data.quarters || [])].reverse()
        setQuarters(qs)
        if (!value && qs.length > 0) onChange(qs[0])
      })
      .catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div className="flex flex-col gap-1">
      <label className="text-xs font-medium text-gray-600 uppercase tracking-wide">
        Quarter
      </label>
      <div className="flex gap-1 flex-wrap">
        {quarters.map(q => (
          <button
            key={q}
            onClick={() => onChange(q)}
            className={`px-3 py-1 text-xs rounded border transition-colors ${
              q === value
                ? 'bg-oxford-blue text-white border-oxford-blue'
                : 'bg-white text-gray-700 border-gray-300 hover:border-oxford-blue hover:text-oxford-blue'
            }`}
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  )
}
