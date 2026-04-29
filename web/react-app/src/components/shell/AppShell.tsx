import { Sidebar } from './Sidebar'
import { Header } from './Header'
import { useAppStore } from '../../store/useAppStore'
import { ErrorBoundary } from '../common'
import { lazy, Suspense } from 'react'

const TAB_MAP: Record<string, React.LazyExoticComponent<() => React.ReactElement>> = {
  'sector-rotation': lazy(() => import('../tabs/SectorRotationTab').then(m => ({ default: m.SectorRotationTab }))),
  'entity-graph': lazy(() => import('../tabs/EntityGraphTab').then(m => ({ default: m.EntityGraphTab }))),
  'register': lazy(() => import('../tabs/RegisterTab').then(m => ({ default: m.RegisterTab }))),
  'ownership-trend': lazy(() => import('../tabs/OwnershipTrendTab').then(m => ({ default: m.OwnershipTrendTab }))),
  'conviction': lazy(() => import('../tabs/ConvictionTab').then(m => ({ default: m.ConvictionTab }))),
  'fund-portfolio': lazy(() => import('../tabs/FundPortfolioTab').then(m => ({ default: m.FundPortfolioTab }))),
  'flow-analysis': lazy(() => import('../tabs/FlowAnalysisTab').then(m => ({ default: m.FlowAnalysisTab }))),
  'peer-rotation': lazy(() => import('../tabs/PeerRotationTab').then(m => ({ default: m.PeerRotationTab }))),
  'cross-ownership': lazy(() => import('../tabs/CrossOwnershipTab').then(m => ({ default: m.CrossOwnershipTab }))),
  'overlap-analysis': lazy(() => import('../tabs/OverlapAnalysisTab').then(m => ({ default: m.OverlapAnalysisTab }))),
  'short-interest': lazy(() => import('../tabs/ShortInterestTab').then(m => ({ default: m.ShortInterestTab }))),
  'data-source': lazy(() => import('../tabs/DataSourceTab').then(m => ({ default: m.DataSourceTab }))),
}

export function AppShell() {
  const { activeTab } = useAppStore()
  const TabComponent = TAB_MAP[activeTab]
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', overflow: 'hidden' }}>
      <Header />
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
        <Sidebar />
        <main style={{ flex: 1, overflowY: 'auto', backgroundColor: 'var(--bg)', padding: '20px' }}>
          <ErrorBoundary key={activeTab} tab={activeTab}>
            <Suspense fallback={<div style={{ color: 'var(--text-mute)', padding: '20px' }}>Loading…</div>}>
              {TabComponent ? <TabComponent /> : <div>Tab not found</div>}
            </Suspense>
          </ErrorBoundary>
        </main>
      </div>
    </div>
  )
}
