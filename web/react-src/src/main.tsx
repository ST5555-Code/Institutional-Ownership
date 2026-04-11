import React from 'react'
import ReactDOM from 'react-dom/client'
import './index.css'

// Placeholder — will be replaced with TwoCompanyOverlap component
function TcoPlaceholder() {
  return (
    <div className="p-6 border border-gray-200 rounded bg-white">
      <h2 className="text-lg font-semibold" style={{ color: 'var(--oxford-blue)' }}>
        2 Companies Overlap — React POC
      </h2>
      <p className="mt-2 text-sm text-gray-500">
        React + TypeScript + Tailwind + AG Grid scaffold mounted successfully.
      </p>
    </div>
  )
}

// Mount function — called by existing app.js when tab activates
function mountTco(ticker: string) {
  const root = document.getElementById('tco-react-root')
  if (!root) return
  ReactDOM.createRoot(root).render(
    <React.StrictMode>
      <TcoPlaceholder />
    </React.StrictMode>
  )
}

// Expose to existing vanilla JS layer
;(window as any).tcoMount = mountTco
;(window as any).tcoActivate = (ticker: string) => mountTco(ticker)

// Auto-mount if element already exists on page load
const existingRoot = document.getElementById('tco-react-root')
if (existingRoot) {
  mountTco('')
}
