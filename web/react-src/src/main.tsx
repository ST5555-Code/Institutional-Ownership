import React from 'react'
import ReactDOM from 'react-dom/client'
import { ModuleRegistry, AllCommunityModule } from 'ag-grid-community'
import './index.css'
import { TwoCompanyOverlap } from './components/TwoCompanyOverlap'

ModuleRegistry.registerModules([AllCommunityModule])

let _root: ReturnType<typeof ReactDOM.createRoot> | null = null

function mountTco(ticker: string) {
  const el = document.getElementById('tco-react-root')
  if (!el) return
  // Defensive: if something outside React (a legacy innerHTML='' path, a
  // Flask hot reload, etc.) cleared the mount element, the cached _root's
  // fiber tree no longer matches the DOM. Drop and recreate the root so
  // React commits fresh into the clean element.
  if (_root && el.children.length === 0 && el.innerHTML === '') {
    _root = null
  }
  if (!_root) {
    _root = ReactDOM.createRoot(el)
  }
  _root.render(
    <React.StrictMode>
      <TwoCompanyOverlap subjectTicker={ticker} />
    </React.StrictMode>
  )
}

;(window as any).tcoActivate = mountTco
;(window as any).tcoMount = mountTco

// Auto-mount on load if element present. If switchTab fired before this
// bundle parsed, it stashed the current ticker on window.__tcoPendingTicker.
const pendingTicker = (window as any).__tcoPendingTicker || ''
;(window as any).__tcoPendingTicker = undefined
const existingRoot = document.getElementById('tco-react-root')
if (existingRoot) mountTco(pendingTicker)
