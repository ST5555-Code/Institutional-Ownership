interface Props {
  title: string
  children: React.ReactNode
}

export function SidebarSection({ title, children }: Props) {
  return (
    <div style={{ marginBottom: '8px' }}>
      <div style={{
        padding: '10px 16px 4px',
        fontSize: '9px', fontWeight: 700,
        letterSpacing: '0.16em',
        color: 'var(--gold)',
        textTransform: 'uppercase',
        fontFamily: "'Hanken Grotesk', sans-serif"
      }}>
        {title}
      </div>
      {children}
    </div>
  )
}
