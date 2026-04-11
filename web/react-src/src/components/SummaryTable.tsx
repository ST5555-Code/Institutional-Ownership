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
// See comments in the old SummaryTable for the full derivation.
// Direction A: top N of SUBJECT → how much of SECOND they own
// Direction B: top N of SECOND → how much of SUBJECT they own
//             (approximated from the top-50-subject universe the
//              backend returns)
export function SummaryTable({ rows, subjectTicker, secondTicker, hasSecond }: Props) {
  const results = useMemo(() => {
    return [25, 50].map(n => {
      const cohortSubj = rows.slice(0, n)
      const overlapA = hasSecond ? cohortSubj.filter(r => r.is_overlap) : []
      const pctSecByTopSubj = overlapA.reduce(
        (a, r) => a + (hasSecShares(r) && r.sec_pct_float != null ? r.sec_pct_float : 0), 0
      )

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
        pctSecByTopSubj,
        pctSubjByTopSec,
      }
    })
  }, [rows, hasSecond])

  const subj = subjectTicker || '—'
  const sec = secondTicker || '—'

  return (
    <div style={{ marginTop: '10px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
      {results.map(r => (
        <div
          key={r.n}
          style={{
            border: '1px solid #cbd5e0',
            borderRadius: '4px',
            backgroundColor: '#f7fafc',
            boxShadow: '0 1px 2px rgba(0,0,0,0.04)',
            padding: '10px 12px',
          }}
        >
          {/* Cohort header band */}
          <div
            style={{
              fontSize: '12px',
              fontWeight: 700,
              color: '#002147',
              paddingBottom: '6px',
              marginBottom: '8px',
              borderBottom: '1px solid #cbd5e0',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'baseline',
            }}
          >
            <span>Top {r.n}</span>
            <span style={{ fontSize: '11px', fontWeight: 500, color: '#718096' }}>
              {hasSecond ? `${r.overlapA} overlap holders` : '—'}
            </span>
          </div>

          {/* Metric rows */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', fontSize: '12px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span style={{ color: '#4a5568' }}>
                % of {sec} by {subj} top {r.n}
              </span>
              <span style={{ color: '#002147', fontWeight: 600 }}>
                {hasSecond ? r.pctSecByTopSubj.toFixed(2) + '%' : '—'}
              </span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span style={{ color: '#4a5568' }}>
                % of {subj} by {sec} top {r.n}
              </span>
              <span style={{ color: '#002147', fontWeight: 600 }}>
                {hasSecond ? r.pctSubjByTopSec.toFixed(2) + '%' : '—'}
              </span>
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}
