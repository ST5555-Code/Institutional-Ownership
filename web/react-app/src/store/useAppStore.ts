import { create } from 'zustand'
import type { CompanyData } from '../types/company'
import type { RollupType } from '../types/api'

interface AppState {
  ticker: string
  company: CompanyData | null
  quarter: string
  activeTab: string
  rollupType: RollupType
  loading: boolean
  setTicker: (ticker: string) => void
  loadCompany: (ticker: string) => Promise<void>
  setQuarter: (quarter: string) => void
  setActiveTab: (tab: string) => void
  setRollupType: (rollupType: RollupType) => void
}

export const useAppStore = create<AppState>((set) => ({
  ticker: '',
  company: null,
  quarter: '2025Q4',
  activeTab: 'investor-detail',
  rollupType: 'economic_control_v1',
  loading: false,
  setTicker: (ticker) => set({ ticker }),
  setQuarter: (quarter) => set({ quarter }),
  setActiveTab: (tab) => set({ activeTab: tab }),
  setRollupType: (rollupType) => set({ rollupType }),
  loadCompany: async (ticker) => {
    set({ loading: true })
    try {
      const res = await fetch(`/api/v1/summary?ticker=${encodeURIComponent(ticker)}`)
      if (!res.ok) throw new Error('fetch failed')
      const data = await res.json()
      set({ company: data, ticker })
    } catch {
      set({ company: null })
    } finally {
      set({ loading: false })
    }
  }
}))
