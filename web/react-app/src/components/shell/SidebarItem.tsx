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
        backgroundColor: isActive ? 'var(--gold-soft)' : 'transparent',
        borderLeft: isActive ? '2px solid var(--gold)' : '2px solid transparent',
        color: isActive ? 'var(--white)' : 'var(--text-dim)',
        width: '100%', textAlign: 'left',
        padding: '8px 16px 8px 20px',
        fontSize: '13px', cursor: 'pointer',
        border: 'none', display: 'block',
        transition: 'all 0.12s'
      }}
    >
      {label}
    </button>
  )
}
