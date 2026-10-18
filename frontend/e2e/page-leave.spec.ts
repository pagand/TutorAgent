// frontend/e2e/page-leave.spec.ts
// A page_leave is recorded only when the page goes hidden and visible again
// within one page lifetime, for more than 5 seconds, while the exam is running. Visibility is simulated
// by overriding document.visibilityState and dispatching visibilitychange.
import { test, expect, Page } from '@playwright/test'
import { loginAsToken } from './helpers'

async function setVisibility(page: Page, state: 'hidden' | 'visible') {
  await page.evaluate((s) => {
    Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => s })
    document.dispatchEvent(new Event('visibilitychange'))
  }, state)
}

interface Leave {
  question_number: number
  action_data: { left_at: number; returned_at: number; away_ms: number }
}

function trackLeaves(page: Page) {
  const leaves: Leave[] = []
  page.on('request', (req) => {
    if (req.method() === 'POST' && req.url().endsWith('/log/action')) {
      const body = req.postDataJSON()
      if (body.action_type === 'page_leave') leaves.push(body)
    }
  })
  return leaves
}

test('page_leave: an absence of 5 seconds or less logs nothing and shows no banner', async ({ page }) => {
  const leaves = trackLeaves(page)
  await loginAsToken(page, 'E2ELEAVEA')

  await setVisibility(page, 'hidden')
  await page.waitForTimeout(1500)
  await setVisibility(page, 'visible')
  await page.waitForTimeout(500)

  expect(leaves.length).toBe(0)
  await expect(page.getByText('This is recorded.')).toHaveCount(0)
})

test('page_leave: an absence over 5 seconds logs one event and shows the banner', async ({ page }) => {
  const leaves = trackLeaves(page)
  await loginAsToken(page, 'E2ELEAVED')

  await setVisibility(page, 'hidden')
  await page.waitForTimeout(6000)
  await setVisibility(page, 'visible')

  await expect(page.getByText('This is recorded.')).toBeVisible()
  await expect(page.getByText(/You left the exam page for \d+ s\./)).toBeVisible()
  await expect.poll(() => leaves.length).toBe(1)
  expect(leaves[0].question_number).toBe(1)
  expect(leaves[0].action_data.away_ms).toBeGreaterThan(5000)
  expect(leaves[0].action_data.returned_at - leaves[0].action_data.left_at).toBe(leaves[0].action_data.away_ms)

  await page.getByRole('button', { name: 'Dismiss notice' }).click()
  await expect(page.getByText('This is recorded.')).toHaveCount(0)

  // A visible event with no preceding hidden one logs nothing.
  await setVisibility(page, 'visible')
  await page.waitForTimeout(300)
  expect(leaves.length).toBe(1)
})

test('page_leave: a reload logs nothing and shows no banner', async ({ page }) => {
  const leaves = trackLeaves(page)
  await loginAsToken(page, 'E2ELEAVEB')
  await setVisibility(page, 'hidden')
  await page.reload()
  await expect(page.getByText('Q1 of')).toBeVisible({ timeout: 15000 })
  await page.waitForTimeout(500)
  expect(leaves.length).toBe(0)
  await expect(page.getByText('This is recorded.')).toHaveCount(0)
})

test('page_leave: nothing is logged before the session starts or after submit', async ({ page }) => {
  const leaves = trackLeaves(page)
  await page.goto('/login')
  await setVisibility(page, 'hidden')
  await setVisibility(page, 'visible')

  await loginAsToken(page, 'E2ELEAVEC')
  await page.getByRole('button', { name: 'Submit Exam' }).click()
  await page.getByRole('button', { name: 'Yes, submit exam' }).click()
  await expect(page).toHaveURL(/results/, { timeout: 15000 })
  await setVisibility(page, 'hidden')
  await setVisibility(page, 'visible')
  await page.waitForTimeout(500)
  expect(leaves.length).toBe(0)
})

test.describe('quiz header and nav strip layout', () => {
  for (const width of [1440, 1920, 390]) {
    test(`nav strip aligns with header and card at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 })
      await loginAsToken(page, `E2ELAYOUT${[1440, 1920, 390].indexOf(width) + 1}`)
      const logo = page.getByAltText('DaTu AIR')
      await expect(logo).toBeVisible()
      const first = await page.locator('button[title^="Q1:"]').boundingBox()
      const logoBox = await logo.boundingBox()
      const card = await page.getByText('Q1 of').boundingBox()
      expect(first).not.toBeNull()
      expect(Math.abs(first!.x - logoBox!.x)).toBeLessThanOrEqual(1)
      if (width >= 1440) expect(first!.x).toBeGreaterThan(50)
      expect(card).not.toBeNull()
      // No horizontal page scroll (wrap, not overflow).
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
      expect(overflow).toBeLessThanOrEqual(0)
      await page.screenshot({ path: `test-results/quiz-${width}.png` })
    })
  }
})
