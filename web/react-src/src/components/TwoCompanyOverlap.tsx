import React, { useState } from 'react'
import { QuarterSelector } from './QuarterSelector'
import { SecondTickerSearch } from './SecondTickerSearch'
import { OverlapTable } from './OverlapTable'
import { SummaryTable } from './SummaryTable'
import { useOverlapData } from '../hooks/useOverlapData'

interface Props {
  subjectTicker: string
}

// Shared panel title style so the institutional and fund panels line up
// pixel-for-pixel, which they don't when they rely on Tailwind class
// inheritance across two subtly different containers.
const panelTitleStyle: React.CSSProperties = {
  fontSize: '14px',
  fontWeight: 700,
  color: '#002147',
  margin: '0 0 8px 0',
  padding: 0,
  height: '20px',
  lineHeight: '20px',
}

interface ActiveToggleProps {
  active: boolean
  onToggle: () => void
}

function ActiveOnlyToggle({ active, onToggle }: ActiveToggleProps) {
  const base =
    'px-3 py-1 text-xs rounded border transition-colors select-none cursor-pointer'
  const cls = active
    ? 'bg-oxford-blue text-white border-oxford-blue'
    : 'bg-white text-gray-600 border-gray-300 hover:border-oxford-blue'
  return (
    <button type="button" onClick={onToggle} className={`${base} ${cls}`}>
      Active Only
    </button>
  )
}

export function TwoCompanyOverlap({ subjectTicker }: Props) {
  const [secondTicker, setSecondTicker] = useState('')
  const [quarter, setQuarter] = useState('')
  const [instActiveOnly, setInstActiveOnly] = useState(false)
  const [fundActiveOnly, setFundActiveOnly] = useState(false)

  const { data, loading, error } = useOverlapData(subjectTicker, secondTicker, quarter)

  const hasSecond = !!secondTicker && !!data?.meta?.second
  const instRows = data?.institutional || []
  const fundRows = data?.fund || []

  return (
    <div className="p-4 font-sans">
      {/* Controls */}
      <div className="flex gap-6 items-end flex-wrap mb-4">
        {/* Subject — read only display */}
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-gray-600 uppercase tracking-wide">
            Subject
          </label>
          <div
            className="px-3 py-1.5 text-sm bg-gray-50 border border-gray-200
                       rounded text-oxford-blue font-semibold min-w-20 text-center"
          >
            {subjectTicker || '—'}
          </div>
        </div>

        <SecondTickerSearch value={secondTicker} onChange={setSecondTicker} />
        <QuarterSelector value={quarter} onChange={setQuarter} />
      </div>

      {/* Error */}
      {error && (
        <div className="mb-4 px-3 py-2 bg-red-50 border border-red-200 rounded text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Loading */}
      {loading && (
        <div className="text-sm text-gray-500 py-4">Loading…</div>
      )}

      {/* Tables — inline style so the two panels are guaranteed equal width */}
      {!loading && data && (
        <div style={{ display: 'flex', gap: '20px', alignItems: 'flex-start' }}>
          {/* Institutional */}
          <div style={{ flex: 1, minWidth: 0 }}>
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                marginBottom: '8px',
              }}
            >
              <h3 style={panelTitleStyle}>Ownership Overlap by Institution</h3>
              <ActiveOnlyToggle
                active={instActiveOnly}
                onToggle={() => setInstActiveOnly(v => !v)}
              />
            </div>
            <OverlapTable
              rows={instRows}
              subjectTicker={subjectTicker}
              secondTicker={secondTicker}
              hasSecond={hasSecond}
              type="inst"
              activeOnly={instActiveOnly}
            />
            <SummaryTable
              rows={instRows}
              subjectTicker={subjectTicker}
              secondTicker={secondTicker}
              hasSecond={hasSecond}
            />
          </div>

          {/* Fund */}
          <div style={{ flex: 1, minWidth: 0 }}>
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                marginBottom: '8px',
              }}
            >
              <h3 style={panelTitleStyle}>Ownership Overlap by Fund</h3>
              <ActiveOnlyToggle
                active={fundActiveOnly}
                onToggle={() => setFundActiveOnly(v => !v)}
              />
            </div>
            <OverlapTable
              rows={fundRows}
              subjectTicker={subjectTicker}
              secondTicker={secondTicker}
              hasSecond={hasSecond}
              type="fund"
              activeOnly={fundActiveOnly}
            />
            <SummaryTable
              rows={fundRows}
              subjectTicker={subjectTicker}
              secondTicker={secondTicker}
              hasSecond={hasSecond}
            />
          </div>
        </div>
      )}

      {/* No data state */}
      {!loading && !data && !error && (
        <div className="text-sm text-gray-400 py-8 text-center">
          Load a ticker in the header to get started.
        </div>
      )}
    </div>
  )
}
