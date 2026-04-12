interface FooterRow {
  label: string
  shares_mm: number | null
  value_mm: number | null
  pct_float: number | null
}

interface Props {
  rows: FooterRow[]
  totalColumns: number
  /** Row height in px for sticky-bottom offset stacking. Default 33. */
  rowHeightPx?: number
  /** Empty cells inserted between the type cell and the shares cell.
   *  Use when the host table has spacer columns between Type and
   *  Shares so the footer's number cells line up with the body.
   *  Default 0. */
  skipBeforeNumbers?: number
  /** Empty cells inserted between the %-float cell and the trailing
   *  filler. Use when the host table has spacer columns between
   *  %-float and whatever columns follow. Default 0. */
  skipAfterNumbers?: number
}

// Column layout: Rank · Institution · Type · Shares · Value · % Float ·
// [filler empties to fill totalColumns]. The caller decides how many total
// columns the host table has — filler count = totalColumns - 6.
//
// Sticky-bottom stacking: footer rows use position: sticky + bottom: Npx
// so they stay pinned at the bottom edge of the scrolling tbody. With N
// rows in DOM order [row0, row1, ..., rowLast], the visually-bottom row
// needs bottom: 0 and each earlier row needs bottom: rowHeight * (distance
// from bottom). That way DOM order matches visual stacking top→bottom.

const NAMED_COL_COUNT = 6

const NUM_0 = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 })
const NUM_1 = new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 })
const NUM_2 = new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

function fmtShares(v: number | null): string {
  if (v == null) return '—'
  return NUM_2.format(v)
}

function fmtValue(v: number | null): string {
  if (v == null) return '—'
  if (v >= 1000) return `$${NUM_1.format(v / 1000)}B`
  return `$${NUM_0.format(v)}M`
}

function fmtPct(v: number | null): string {
  if (v == null) return '—'
  return `${NUM_2.format(v)}%`
}

function cellStyle(bottomPx: number): React.CSSProperties {
  return {
    padding: '7px 10px',
    fontSize: 13,
    fontWeight: 600,
    color: '#ffffff',
    backgroundColor: 'var(--oxford-blue)',
    position: 'sticky',
    bottom: bottomPx,
    zIndex: 2,
    // First sticky row gets the top accent border; subsequent rows draw a
    // thinner internal divider so the stacked rows read as one footer block.
    borderTop: '2px solid var(--oxford-blue)',
  }
}

function cellStyleRight(bottomPx: number): React.CSSProperties {
  return {
    ...cellStyle(bottomPx),
    textAlign: 'right',
    fontVariantNumeric: 'tabular-nums',
  }
}

export function TableFooter({
  rows,
  totalColumns,
  rowHeightPx = 33,
  skipBeforeNumbers = 0,
  skipAfterNumbers = 0,
}: Props) {
  const fillerCount = Math.max(
    0,
    totalColumns - NAMED_COL_COUNT - skipBeforeNumbers - skipAfterNumbers,
  )
  return (
    <tfoot>
      {rows.map((r, i) => {
        // Row 0 (top of footer) needs the largest bottom offset so it stacks
        // above Row 1 which sits at bottom: 0. For N rows: bottomPx =
        // (N - 1 - i) * rowHeight.
        const bottomPx = (rows.length - 1 - i) * rowHeightPx
        return (
          <tr key={i}>
            <td style={cellStyle(bottomPx)} />
            <td style={cellStyle(bottomPx)}>{r.label}</td>
            <td style={cellStyle(bottomPx)} />
            {Array.from({ length: skipBeforeNumbers }, (_, j) => (
              <td key={`sb${j}`} style={cellStyle(bottomPx)} />
            ))}
            <td style={cellStyleRight(bottomPx)}>{fmtShares(r.shares_mm)}</td>
            <td style={cellStyleRight(bottomPx)}>{fmtValue(r.value_mm)}</td>
            <td style={cellStyleRight(bottomPx)}>{fmtPct(r.pct_float)}</td>
            {Array.from({ length: skipAfterNumbers }, (_, j) => (
              <td key={`sa${j}`} style={cellStyle(bottomPx)} />
            ))}
            {Array.from({ length: fillerCount }, (_, j) => (
              <td key={`f${j}`} style={cellStyle(bottomPx)} />
            ))}
          </tr>
        )
      })}
    </tfoot>
  )
}
