import { TickerInput } from '../header/TickerInput'
import { CompanyCard } from '../header/CompanyCard'

export function Header() {
  return (
    <header style={{
      backgroundColor: 'var(--header)',
      borderBottom: '1px solid var(--line)',
      padding: '0 20px',
      height: '48px',
      display: 'flex', alignItems: 'stretch', gap: '20px',
      flexShrink: 0
    }}>
      <div style={{
        width: 220 - 20,
        display: 'flex', flexDirection: 'column', justifyContent: 'center',
        color: 'var(--white)',
        fontWeight: 700,
        fontSize: '13px',
        letterSpacing: '0.16em',
        lineHeight: 1.2,
        textTransform: 'uppercase',
        fontFamily: "'Hanken Grotesk', sans-serif",
      }}>
        <span>SHAREHOLDER</span>
        <span>INTELLIGENCE</span>
      </div>
      <div style={{
        width: 1,
        backgroundColor: 'rgba(255,255,255,0.15)',
        alignSelf: 'stretch',
        flexShrink: 0,
      }} />
      <div style={{ display: 'flex', alignItems: 'center', gap: '20px', flex: 1 }}>
        <TickerInput />
        <CompanyCard />
      </div>
    </header>
  )
}
