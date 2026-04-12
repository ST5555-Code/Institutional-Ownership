# React Migration Plan
_Created: 2026-04-11_

## Architecture Decision
Parallel build — new React app in web/react-app/, existing app on localhost:8001 untouched until cut over.

## Tech Stack
- React 19 + TypeScript
- Vite (port 5174, proxy /api/* → Flask 8001)
- Tailwind CSS v3
- AG Grid Community v35
- Zustand for shared state

## Color Scheme
Dark navy shell + light content area (Bloomberg pattern)
- Shell bg: #0a0f1e
- Sidebar bg: #0d1526
- Sidebar active: #1a2a4a
- Accent gold: #f5a623
- Content bg: #f4f6f9
- Card bg: #ffffff
- Oxford Blue retained: #002147
- Glacier Blue retained: #4A90D9

## Navigation — Left Sidebar, 4 sections, 11 tabs

### Overall Market
- Sector Rotation
- Entity Graph

### Ownership
- Register
- Ownership Trend
- Conviction
- Fund Portfolio

### Flow & Rotation
- Flow Analysis
- Peer Rotation

### Investor Targeting
- Cross-Ownership
- Overlap Analysis (rebuilt clean — was 2 Companies Overlap)
- Short Interest

## Phase 1 — Shell Only (no tab content)
Build: AppShell, Sidebar, Header, TickerContext (Zustand), tab placeholders
End state: localhost:5174 shows full shell with ticker input, company card, sidebar navigation
Existing app: localhost:8001 completely untouched

## Zustand Store Shape
interface AppState {
  ticker: string
  company: CompanyData | null
  quarter: string
  loading: boolean
  setTicker: (ticker: string) => void
  loadCompany: (ticker: string) => Promise<void>
  setQuarter: (quarter: string) => void
}
loadCompany calls /api/summary?ticker=X

## File Structure
web/react-app/
├── package.json
├── vite.config.ts
├── tailwind.config.js
├── tsconfig.json
├── index.html
└── src/
    ├── main.tsx
    ├── App.tsx
    ├── store/
    │   └── useAppStore.ts
    ├── types/
    │   └── company.ts
    ├── components/
    │   ├── shell/
    │   │   ├── AppShell.tsx
    │   │   ├── Sidebar.tsx
    │   │   ├── SidebarSection.tsx
    │   │   ├── SidebarItem.tsx
    │   │   └── Header.tsx
    │   ├── header/
    │   │   ├── TickerInput.tsx
    │   │   ├── CompanyCard.tsx
    │   │   └── ViewToggle.tsx
    │   └── tabs/
    │       ├── SectorRotationTab.tsx
    │       ├── EntityGraphTab.tsx
    │       ├── RegisterTab.tsx
    │       ├── OwnershipTrendTab.tsx
    │       ├── ConvictionTab.tsx
    │       ├── FundPortfolioTab.tsx
    │       ├── FlowAnalysisTab.tsx
    │       ├── PeerRotationTab.tsx
    │       ├── CrossOwnershipTab.tsx
    │       ├── OverlapAnalysisTab.tsx
    │       └── ShortInterestTab.tsx
    └── styles/
        └── globals.css

## Cut Over
When all tabs migrated and validated:
- Flask serves web/react-app/dist/ instead of index.html
- One line change in app.py
- Revert in 30 seconds if needed
- web/react-src/ (POC) retired and deleted

## Open Items (do not build yet)
- Playwright visual regression testing (add when 3+ tabs migrated)
- Auth/token handling for /api/admin/* endpoints (INF12)
- Activist flag as red highlight on Register + Conviction (not a tab)
- Short Interest tab in Investor Targeting section

## Backend Migration Plan

### Current state
- Flask dev server, single process
- DuckDB single-writer with staging + readonly snapshot pattern
- Manual pipeline execution from terminal
- INF12: token auth on /api/admin/* endpoints
- Localhost only

### Migration order (do not build until frontend Phase 6 complete)

| Priority | Component | Action | When |
|----------|-----------|--------|------|
| 1 | Flask serving | Replace dev server with Gunicorn + Nginx | First external user |
| 2 | Authentication | Flask-JWT or Auth0, per-user access control | Same time as Gunicorn |
| 3 | Pipeline scheduling | APScheduler inside Flask or Airflow | When running with a team |
| 4 | PostgreSQL | Migrate entity MDM tables if write concurrency becomes an issue | If needed |
| 5 | Cloud deployment | Railway (Flask) + Vercel (React) or combined EC2 | When productizing |

### What does NOT need to change
- DuckDB for analytics queries — works fine for multi-user reads
- Flask API routes and queries.py — already clean, React calls same endpoints
- Data pipeline scripts — unchanged
- Staging workflow for entity changes — unchanged
