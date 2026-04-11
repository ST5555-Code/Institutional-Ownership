import { create } from 'zustand'
import type { CompanyData } from '../types/company'

interface AppState {
  ticker: string
  company: CompanyData | null
  quarter: string
  activeTab: string
  loading: boolean
  setTicker: (ticker: string) => void
  loadCompany: (ticker: string) => Promise<void>
  setQuarter: (quarter: string) => void
  setActiveTab: (tab: string) => void
}

export const useAppStore = create<AppState>((set) => ({
  ticker: '',
  company: null,
  quarter: '2025Q4',
  activeTab: 'register',
  loading: false,
  setTicker: (ticker) => set({ ticker }),
  setQuarter: (quarter) => set({ quarter }),
  setActiveTab: (tab) => set({ activeTab: tab }),
  loadCompany: async (ticker) => {
    set({ loading: true })
    try {
      const res = await fetch(`/api/summary?ticker=${encodeURIComponent(ticker)}`)
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
