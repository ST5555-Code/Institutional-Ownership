interface Group {
  label: string
  colSpan: number
}

interface Props {
  groups: Group[]
  /** When true (default) the whole row renders with an oxford-blue
   *  background so it stacks visually with the column-label row
   *  beneath it. Set false if the host table wants a light header. */
  darkFill?: boolean
}

export function ColumnGroupHeader({ groups, darkFill = true }: Props) {
  const bg = darkFill ? 'var(--header)' : 'transparent'
  const text = darkFill ? 'var(--white)' : 'var(--text-dim)'

  // When dark, pin both the group header row and (via the column label
  // row's own top offset) the label row so the sandstone underline stays
  // visible during scroll. The column label row should use top: ~30px
  // to sit below this row.
  const sticky: React.CSSProperties = darkFill
    ? { position: 'sticky', top: 0, zIndex: 4 }
    : {}

  const labeled: React.CSSProperties = {
    padding: '6px 10px',
    fontSize: 11,
    fontWeight: 600,
    color: text,
    backgroundColor: bg,
    textAlign: 'center',
    textTransform: 'uppercase',
    letterSpacing: '0.06em',
    borderBottom: '2px solid var(--gold)',
    ...sticky,
  }

  // Empty group cells carry the same dark fill so the row reads as one
  // continuous band — no border so the light-mode variant still looks
  // clean when darkFill is false.
  const empty: React.CSSProperties = {
    padding: 0,
    border: 'none',
    backgroundColor: bg,
    ...sticky,
  }

  return (
    <tr>
      {groups.map((g, i) => (
        <th key={i} colSpan={g.colSpan} style={g.label ? labeled : empty}>
          {g.label}
        </th>
      ))}
    </tr>
  )
}
