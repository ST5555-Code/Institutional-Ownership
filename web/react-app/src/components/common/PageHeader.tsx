interface Props {
  section: string
  title: string
  description: string
}

export function PageHeader({ section, title, description }: Props) {
  return (
    <div style={{ padding: '12px 12px 0', flexShrink: 0 }}>
      <div
        style={{
          fontSize: 9,
          fontFamily: "'Hanken Grotesk', sans-serif",
          fontWeight: 700,
          textTransform: 'uppercase',
          letterSpacing: '0.16em',
          color: 'var(--gold)',
        }}
      >
        {section}
      </div>
      <div
        style={{
          fontSize: 24,
          fontFamily: "'Inter', sans-serif",
          fontWeight: 300,
          color: 'var(--white)',
          marginTop: 4,
        }}
      >
        {title}
      </div>
      <div
        style={{
          fontSize: 13,
          fontFamily: "'Inter', sans-serif",
          fontWeight: 400,
          color: 'var(--text-dim)',
          marginTop: 4,
          marginBottom: 16,
        }}
      >
        {description}
      </div>
    </div>
  )
}
