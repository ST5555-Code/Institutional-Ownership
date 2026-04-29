import { SidebarSection } from './SidebarSection'
import { SidebarItem } from './SidebarItem'

export function Sidebar() {
  return (
    <nav style={{
      width: '220px', minWidth: '220px',
      backgroundColor: 'var(--header)',
      height: '100vh', overflowY: 'auto',
      borderRight: '1px solid var(--line)',
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
