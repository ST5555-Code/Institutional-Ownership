import { test, expect, Page } from '@playwright/test'

const TICKER = 'AAPL'

const TABS = [
  { id: 'sector-rotation',  label: 'Sector Rotation' },
  { id: 'investor-detail',  label: 'Investor Detail' },
  { id: 'register',         label: 'Register' },
  { id: 'ownership-trend',  label: 'Ownership Trend' },
  { id: 'conviction',       label: 'Conviction' },
  { id: 'fund-portfolio',   label: 'Fund Portfolio' },
  { id: 'flow-analysis',    label: 'Flow Analysis' },
  { id: 'peer-rotation',    label: 'Peer Rotation' },
  { id: 'cross-ownership',  label: 'Cross-Ownership' },
  { id: 'overlap-analysis', label: 'Overlap Analysis' },
  { id: 'short-interest',   label: 'Short Interest' },
] as const

async function loadTicker(page: Page, ticker: string) {
  await page.goto('/')
  const input = page.getByPlaceholder(/ticker/i)
  await input.fill(ticker)
  await input.press('Enter')
  await expect(page.getByText('APPLE INC').first()).toBeVisible({ timeout: 15_000 })
}

async function openTab(page: Page, label: string) {
  await page.getByRole('button', { name: label, exact: true }).click()
  await page.waitForLoadState('networkidle', { timeout: 45_000 })
  // Small settle delay so chart transitions finish before snapshot.
  await page.waitForTimeout(400)
}

for (const tab of TABS) {
  test(`tab ${tab.id} renders`, async ({ page }) => {
    await loadTicker(page, TICKER)
    await openTab(page, tab.label)
    await expect(page).toHaveScreenshot(`${tab.id}.png`, { fullPage: true })
  })
}
