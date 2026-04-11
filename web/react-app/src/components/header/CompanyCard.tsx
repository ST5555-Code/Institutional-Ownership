import { useAppStore } from '../../store/useAppStore'

function fmt(n: number | null) {
  if (n == null) return '—'
  if (n >= 1e9) return `$${(n / 1e9).toFixed(1)}B`
  if (n >= 1e6) return `$${(n / 1e6).toFixed(0)}M`
  return `$${n.toFixed(0)}`
}

export function CompanyCard() {
  const { company, loading } = useAppStore()
  if (loading) return <span style={{ color: '#94a3b8', fontSize: '12px' }}>Loading…</span>
  if (!company) return null
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
      <span style={{ fontWeight: 700, fontSize: '15px', color: '#ffffff' }}>{company.ticker}</span>
      <span style={{ color: '#cbd5e1', fontSize: '13px' }}>{company.company_name}</span>
      {company.market_cap != null && <span style={{ color: '#94a3b8', fontSize: '12px' }}>{fmt(company.market_cap)}</span>}
      <span style={{ color: '#64748b', fontSize: '11px' }}>{company.latest_quarter}</span>
    </div>
  )
}
