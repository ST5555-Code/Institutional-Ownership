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

  const subj = subjectTicker || '—'
  const sec = secondTicker || '—'

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
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px' }}>
        <thead>
          <tr style={{ borderBottom: '2px solid #002147' }}>
            <th style={{ textAlign: 'left', padding: '4px 6px', fontWeight: 600, color: '#555' }}>
              Cohort
            </th>
            <th style={{ textAlign: 'right', padding: '4px 6px', fontWeight: 600, color: '#555' }}>
              Overlap
            </th>
            <th style={{ textAlign: 'right', padding: '4px 6px', fontWeight: 600, color: '#555' }}>
              {hasSecond ? `% of ${sec} by ${subj}` : '—'}
            </th>
            <th style={{ textAlign: 'right', padding: '4px 6px', fontWeight: 600, color: '#555' }}>
              {hasSecond ? `% of ${subj} by ${sec}` : '—'}
            </th>
          </tr>
        </thead>
        <tbody>
          {results.map(r => (
            <tr key={r.n} style={{ borderBottom: '1px solid #f0f0f0' }}>
              <td style={{ padding: '4px 6px', color: '#333' }}>Top {r.n}</td>
              <td style={{ textAlign: 'right', padding: '4px 6px', color: '#333' }}>
                {r.overlapCount}
              </td>
              <td style={{ textAlign: 'right', padding: '4px 6px', color: '#333' }}>
                {hasSecond ? r.pctSecBySubj.toFixed(2) + '%' : '—'}
              </td>
              <td style={{ textAlign: 'right', padding: '4px 6px', color: '#333' }}>
                {hasSecond ? r.pctSubjBySec.toFixed(2) + '%' : '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
