import { useAppStore } from '../../store/useAppStore'

interface Props {
  id: string
  label: string
}

export function SidebarItem({ id, label }: Props) {
  const { activeTab, setActiveTab } = useAppStore()
  const isActive = activeTab === id
  return (
    <button
      onClick={() => setActiveTab(id)}
      style={{
        backgroundColor: isActive ? 'var(--sidebar-active)' : 'transparent',
        borderLeft: isActive ? '3px solid var(--accent-gold)' : '3px solid transparent',
        color: isActive ? '#ffffff' : '#94a3b8',
        width: '100%', textAlign: 'left',
        padding: '8px 16px 8px 20px',
        fontSize: '13px', cursor: 'pointer',
        border: 'none', display: 'block',
        transition: 'background 0.15s, color 0.15s'
      }}
    >
      {label}
    </button>
  )
}
