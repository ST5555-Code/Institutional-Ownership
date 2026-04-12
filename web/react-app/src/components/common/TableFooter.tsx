interface FooterRow {
  label: string
  shares_mm: number | null
  value_mm: number | null
  pct_float: number | null
}

interface Props {
  rows: FooterRow[]
}

// Column layout mirrors the Register table: Rank · Institution · Type ·
// Shares · Value · % Float · [remaining cells empty]. When a tab uses this
// footer with a different column count, wrap it in a colgroup or pass
// additional empty cells downstream.

const NUM_1 = new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 })
const NUM_2 = new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 })

function fmtShares(v: number | null): string {
  if (v == null) return '—'
  return `${NUM_2.format(v)}M`
}

function fmtValue(v: number | null): string {
  if (v == null) return '—'
  if (v >= 1000) return `$${NUM_1.format(v / 1000)}B`
  return `$${NUM_1.format(v)}M`
}

function fmtPct(v: number | null): string {
  if (v == null) return '—'
  return `${NUM_2.format(v)}%`
}

const FOOTER_CELL: React.CSSProperties = {
  padding: '8px 10px',
  fontSize: 12,
  fontWeight: 600,
  color: '#ffffff',
  backgroundColor: 'var(--oxford-blue)',
}

const FOOTER_CELL_RIGHT: React.CSSProperties = {
  ...FOOTER_CELL,
  textAlign: 'right',
  fontVariantNumeric: 'tabular-nums',
}

export function TableFooter({ rows }: Props) {
  return (
    <tfoot style={{ borderTop: '2px solid var(--oxford-blue)' }}>
      {rows.map((r, i) => (
        <tr key={i}>
          <td style={FOOTER_CELL} />
          <td style={FOOTER_CELL}>{r.label}</td>
          <td style={FOOTER_CELL} />
          <td style={FOOTER_CELL_RIGHT}>{fmtShares(r.shares_mm)}</td>
          <td style={FOOTER_CELL_RIGHT}>{fmtValue(r.value_mm)}</td>
          <td style={FOOTER_CELL_RIGHT}>{fmtPct(r.pct_float)}</td>
          <td style={FOOTER_CELL} />
          <td style={FOOTER_CELL} />
          <td style={FOOTER_CELL} />
        </tr>
      ))}
    </tfoot>
  )
}
