import { useMemo } from 'react'
import { OverlapRow } from '../types/overlap'

interface Props {
  rows: OverlapRow[]
  subjectTicker: string
  secondTicker: string
  hasSecond: boolean
}

function hasSecShares(row: OverlapRow): boolean {
  return row.sec_shares != null && row.sec_shares > 0
}

export function SummaryTable({ rows, subjectTicker, secondTicker, hasSecond }: Props) {
  const results = useMemo(() => {
    return [25, 50].map(n => {
      const cohort = rows.slice(0, n)
      const overlap = hasSecond ? cohort.filter(r => r.is_overlap) : []
      const pctSecBySubj = overlap.reduce(
        (a, r) => a + (hasSecShares(r) && r.sec_pct_float != null ? r.sec_pct_float : 0), 0
      )
      const bySecDol = hasSecond
        ? [...rows].sort((a, b) => (b.sec_dollars || 0) - (a.sec_dollars || 0)).slice(0, n)
        : []
      const pctSubjBySec = bySecDol.reduce((a, r) => a + (r.subj_pct_float || 0), 0)
      return { n, overlapCount: overlap.length, pctSecBySubj, pctSubjBySec }
    })
  }, [rows, hasSecond])

  return (
    <div
      style={{
        marginTop: '10px',
        border: '1px solid #e2e8f0',
        borderRadius: '4px',
        padding: '8px',
        backgroundColor: '#fafafa',
      }}
    >
      <table className="w-full text-xs border-collapse">
        <thead>
          <tr className="border-b border-gray-300">
            <th className="text-left py-1 px-2 font-semibold text-gray-600">Cohort</th>
            <th className="text-right py-1 px-2 font-semibold text-gray-600">Overlap</th>
            <th className="text-right py-1 px-2 font-semibold text-gray-600">
              % of {secondTicker || '—'} owned by {subjectTicker || '—'} top N
            </th>
            <th className="text-right py-1 px-2 font-semibold text-gray-600">
              % of {subjectTicker || '—'} owned by {secondTicker || '—'} top N
            </th>
          </tr>
        </thead>
        <tbody>
          {results.map(r => (
            <tr key={r.n} className="border-b border-gray-100 hover:bg-gray-50 last:border-0">
              <td className="py-1 px-2 text-gray-700">Top {r.n}</td>
              <td className="text-right py-1 px-2 text-gray-700">{r.overlapCount}</td>
              <td className="text-right py-1 px-2 text-gray-700">
                {hasSecond ? r.pctSecBySubj.toFixed(2) + '%' : '—'}
              </td>
              <td className="text-right py-1 px-2 text-gray-700">
                {hasSecond ? r.pctSubjBySec.toFixed(2) + '%' : '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
