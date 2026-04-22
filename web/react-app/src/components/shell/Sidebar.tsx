import { SidebarSection } from './SidebarSection'
import { SidebarItem } from './SidebarItem'

export function Sidebar() {
  return (
    <nav style={{
      width: '200px', minWidth: '200px',
      backgroundColor: 'var(--sidebar-bg)',
      height: '100vh', overflowY: 'auto',
      borderRight: '1px solid #1e2d47',
      paddingTop: '20px'
    }}>
      <SidebarSection title="Market Snapshot & Trends">
        <SidebarItem id="sector-rotation" label="Sector Rotation" />
        <SidebarItem id="entity-graph" label="Entity Graph" />
      </SidebarSection>
      <SidebarSection title="Ownership">
        <SidebarItem id="register" label="Register" />
        <SidebarItem id="ownership-trend" label="Ownership Trend" />
        <SidebarItem id="conviction" label="Conviction" />
        <SidebarItem id="fund-portfolio" label="Fund Portfolio" />
      </SidebarSection>
      <SidebarSection title="Flow & Rotation">
        <SidebarItem id="flow-analysis" label="Flow Analysis" />
        <SidebarItem id="peer-rotation" label="Peer Rotation" />
      </SidebarSection>
      <SidebarSection title="Investor Targeting">
        <SidebarItem id="cross-ownership" label="Cross-Ownership" />
        <SidebarItem id="overlap-analysis" label="Overlap Analysis" />
        <SidebarItem id="short-interest" label="Short Interest" />
      </SidebarSection>
      <SidebarSection title="Reference">
        <SidebarItem id="data-source" label="Data Source" />
      </SidebarSection>
    </nav>
  )
}
