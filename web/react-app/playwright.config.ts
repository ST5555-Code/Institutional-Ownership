import { defineConfig, devices } from '@playwright/test'

// Visual regression scaffolding for the React app.
// Prerequisites before running:
//   1. Flask backend on http://localhost:8001 (python3 scripts/app.py)
//   2. Chromium downloaded (npx playwright install chromium)
// The dev server (vite on :5174) is started by Playwright automatically.

export default defineConfig({
  testDir: './tests/visual',
  timeout: 60_000,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: 'http://localhost:5174',
    viewport: { width: 1440, height: 900 },
    trace: 'retain-on-failure',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:5174',
    reuseExistingServer: true,
    timeout: 30_000,
  },
  expect: {
    // Full-page screenshots against live backend data will drift; allow a
    // modest pixel-diff threshold so colour-level changes (badge palette,
    // layout shifts) are still caught while small numeric updates aren't.
    toHaveScreenshot: { maxDiffPixelRatio: 0.02, animations: 'disabled' },
  },
})
