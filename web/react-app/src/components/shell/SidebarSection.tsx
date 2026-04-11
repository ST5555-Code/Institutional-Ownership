interface Props {
  title: string
  children: React.ReactNode
}

export function SidebarSection({ title, children }: Props) {
  return (
    <div style={{ marginBottom: '8px' }}>
      <div style={{
        padding: '10px 16px 4px',
        fontSize: '10px', fontWeight: 700,
        letterSpacing: '0.08em',
        color: '#4a5568', textTransform: 'uppercase'
      }}>
        {title}
      </div>
      {children}
    </div>
  )
}
