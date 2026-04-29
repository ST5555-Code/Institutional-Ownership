import { TickerInput } from '../header/TickerInput'
import { CompanyCard } from '../header/CompanyCard'

export function Header() {
  return (
    <header style={{
      backgroundColor: 'var(--header)',
      borderBottom: '1px solid var(--line)',
      padding: '0 20px',
      height: '48px',
      display: 'flex', alignItems: 'center', gap: '20px',
      flexShrink: 0
    }}>
      <span style={{
        color: 'var(--gold)',
        fontWeight: 700,
        fontSize: '12px',
        letterSpacing: '0.16em',
        textTransform: 'uppercase',
        fontFamily: "'Hanken Grotesk', sans-serif",
        marginRight: '8px'
      }}>
        13F
      </span>
      <TickerInput />
      <CompanyCard />
    </header>
  )
}
