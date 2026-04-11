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

// Cohort math — bidirectional "true overlap both ways".
//
// For each cohort size N (25, 50), we compute two independent views:
//
//   Direction A: "the top N holders of SUBJECT collectively own X% of SECOND"
//     cohort = rows.slice(0, n)                        // top N by subj $
//     overlap = cohort.filter(is_overlap)
//     pctSecByTopSubj = sum(sec_pct_float over overlap)
//
//   Direction B: "the top N holders of SECOND collectively own Y% of SUBJECT"
//     cohortBySec = rows.sort(desc by sec_dollars).slice(0, n)
//                         .filter(is_overlap)
//     pctSubjByTopSec = sum(subj_pct_float over cohortBySec)
//
// Important caveat on Direction B: the backend only returns the top 50
// holders of the SUBJECT, so a holder who's top-N of SECOND but ranked 51+
// in SUBJECT is invisible to us. For mega-cap overlaps dominated by
// Vanguard / BlackRock / State Street (the same funds holding both), the
// approximation is tight. For thin-overlap cases it understates.
export function SummaryTable({ rows, subjectTicker, secondTicker, hasSecond }: Props) {
  const results = useMemo(() => {
    return [25, 50].map(n => {
      // Direction A — top N by subject dollars
      const cohortSubj = rows.slice(0, n)
      const overlapA = hasSecond ? cohortSubj.filter(r => r.is_overlap) : []
      const pctSecByTopSubj = overlapA.reduce(
        (a, r) => a + (hasSecShares(r) && r.sec_pct_float != null ? r.sec_pct_float : 0), 0
      )

      // Direction B — top N by second dollars, restricted to overlap rows
      const cohortSec = hasSecond
        ? [...rows]
            .sort((a, b) => (b.sec_dollars || 0) - (a.sec_dollars || 0))
            .slice(0, n)
            .filter(r => r.is_overlap)
        : []
      const pctSubjByTopSec = cohortSec.reduce(
        (a, r) => a + (r.subj_pct_float || 0), 0
      )

      return {
        n,
        overlapA: overlapA.length,
        overlapB: cohortSec.length,
        pctSecByTopSubj,
        pctSubjByTopSec,
      }
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
              {hasSecond ? `% ${sec} by top ${subj}` : '—'}
            </th>
            <th style={{ textAlign: 'right', padding: '4px 6px', fontWeight: 600, color: '#555' }}>
              {hasSecond ? `% ${subj} by top ${sec}` : '—'}
            </th>
          </tr>
        </thead>
        <tbody>
          {results.map(r => (
            <tr key={r.n} style={{ borderBottom: '1px solid #f0f0f0' }}>
              <td style={{ padding: '4px 6px', color: '#333' }}>Top {r.n}</td>
              <td style={{ textAlign: 'right', padding: '4px 6px', color: '#333' }}>
                {r.overlapA}
              </td>
              <td style={{ textAlign: 'right', padding: '4px 6px', color: '#333' }}>
                {hasSecond ? r.pctSecByTopSubj.toFixed(2) + '%' : '—'}
              </td>
              <td style={{ textAlign: 'right', padding: '4px 6px', color: '#333' }}>
                {hasSecond ? r.pctSubjByTopSec.toFixed(2) + '%' : '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
