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

// Cohort math — symmetric, unbiased.
//
// For each cohort size N (25, 50):
//   1. Take the top N holders of the SUBJECT ticker (`rows` is already
//      sorted desc by subj_dollars by the backend).
//   2. Filter to the overlap subset — holders who also hold the second
//      ticker (is_overlap === true on the row).
//   3. Sum subj_pct_float across that subset      → % of subject owned
//                                                    by the overlap
//                                                    holders (concentration
//                                                    within the cohort).
//   4. Sum sec_pct_float across that same subset  → % of second owned
//                                                    by the overlap
//                                                    holders.
//
// Both percentages describe the SAME group of holders (the overlap
// intersection inside the top N of the subject), so they're directly
// comparable. The previous implementation re-sorted by sec_dollars and
// took the top N of that, which was structurally biased: the backend
// only returns the top 50 holders of the SUBJECT, so any AR-heavy holder
// ranked below 50 in EQT was silently dropped.
export function SummaryTable({ rows, subjectTicker, secondTicker, hasSecond }: Props) {
  const results = useMemo(() => {
    return [25, 50].map(n => {
      const cohort = rows.slice(0, n)
      const overlap = hasSecond ? cohort.filter(r => r.is_overlap) : []
      const pctSubj = overlap.reduce(
        (a, r) => a + (r.subj_pct_float || 0), 0
      )
      const pctSec = overlap.reduce(
        (a, r) => a + (hasSecShares(r) && r.sec_pct_float != null ? r.sec_pct_float : 0), 0
      )
      return { n, overlapCount: overlap.length, pctSubj, pctSec }
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
              {hasSecond ? `% of ${subj} held` : '—'}
            </th>
            <th style={{ textAlign: 'right', padding: '4px 6px', fontWeight: 600, color: '#555' }}>
              {hasSecond ? `% of ${sec} held` : '—'}
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
                {hasSecond ? r.pctSubj.toFixed(2) + '%' : '—'}
              </td>
              <td style={{ textAlign: 'right', padding: '4px 6px', color: '#333' }}>
                {hasSecond ? r.pctSec.toFixed(2) + '%' : '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
