import { TickerInput } from '../header/TickerInput'
import { CompanyCard } from '../header/CompanyCard'

export function Header() {
  return (
    <header style={{
      backgroundColor: 'var(--oxford-blue)',
      borderBottom: '1px solid #1e2d47',
      padding: '0 20px',
      height: '48px',
      display: 'flex', alignItems: 'center', gap: '20px',
      flexShrink: 0
    }}>
      <span style={{ color: '#ffffff', fontWeight: 700, fontSize: '14px', letterSpacing: '0.05em', marginRight: '8px' }}>
        13F
      </span>
      <TickerInput />
      <CompanyCard />
    </header>
  )
}
