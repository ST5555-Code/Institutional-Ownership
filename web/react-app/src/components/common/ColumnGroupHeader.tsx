interface Group {
  label: string
  colSpan: number
}

interface Props {
  groups: Group[]
}

const LABELED: React.CSSProperties = {
  padding: '6px 10px',
  fontSize: 11,
  fontWeight: 600,
  color: '#475569',
  textAlign: 'center',
  textTransform: 'uppercase',
  letterSpacing: '0.06em',
  borderBottom: '2px solid var(--sandstone)',
}

const EMPTY: React.CSSProperties = {
  padding: 0,
  border: 'none',
}

export function ColumnGroupHeader({ groups }: Props) {
  return (
    <tr>
      {groups.map((g, i) => (
        <th key={i} colSpan={g.colSpan} style={g.label ? LABELED : EMPTY}>
          {g.label}
        </th>
      ))}
    </tr>
  )
}
