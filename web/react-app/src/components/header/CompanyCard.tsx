import { useAppStore } from '../../store/useAppStore'

function fmt(n: number | null) {
  if (n == null) return '—'
  if (n >= 1e9) return `$${(n / 1e9).toFixed(1)}B`
  if (n >= 1e6) return `$${(n / 1e6).toFixed(0)}M`
  return `$${n.toFixed(0)}`
}

export function CompanyCard() {
  const { company, loading } = useAppStore()
  if (loading) return <span style={{ color: 'var(--text-mute)', fontSize: '12px' }}>Loading…</span>
  if (!company) return null
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
      <span style={{
        fontWeight: 600,
        fontSize: '15px',
        color: 'var(--white)',
        fontFamily: "'Hanken Grotesk', sans-serif",
        letterSpacing: '0.02em',
      }}>{company.ticker}</span>
      <span style={{ color: 'var(--text-dim)', fontSize: '13px' }}>{company.company_name}</span>
      {company.market_cap != null && (
        <span style={{
          color: 'var(--text-dim)',
          fontSize: '12px',
          fontFamily: "'JetBrains Mono', monospace",
        }}>{fmt(company.market_cap)}</span>
      )}
      <span style={{
        color: 'var(--text-mute)',
        fontSize: '11px',
        fontFamily: "'JetBrains Mono', monospace",
        letterSpacing: '0.06em',
      }}>{company.latest_quarter}</span>
    </div>
  )
}
