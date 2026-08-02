// frontend/e2e/reload-recovery.spec.ts
// Mixed state (correct, wrong_1, skipped, unsubmitted draft) survives a clean
// reload: states/prior answers reconstructed from server interaction history,
// draft restored from localStorage, timer continues server-authoritatively.
import { test, expect } from '@playwright/test'
import { loginAsToken, getCorrectAnswer } from './helpers'

async function answer(page: import('@playwright/test').Page, value: string) {
  const radioCount = await page.locator('input[type="radio"]').count()
  if (radioCount > 0) {
    await page.locator(`input[type="radio"][value="${value}"]`).check()
  } else {
    await page.getByPlaceholder('Type your answer…').fill(value)
  }
}

test('reload recovery: mixed question states and an unsubmitted draft survive a clean reload', async ({ page }) => {
  await loginAsToken(page, 'E2ERELOAD')

  // Q1: correct.
  const q1Correct = getCorrectAnswer(1)
  await answer(page, q1Correct)
  await page.getByRole('button', { name: 'Submit Answer' }).click()
  await expect(page.getByText('✓ Correct!')).toBeVisible()

  // Q2: wrong once (stays resumable, not locked).
  await page.locator('button[title^="Q2:"]').click()
  const q2Correct = getCorrectAnswer(2)
  const q2Wrong = q2Correct === '1' ? '2' : '1'
  await answer(page, q2Wrong)
  await page.getByRole('button', { name: 'Submit Answer' }).click()
  await expect(page.getByText('1 attempt remaining')).toBeVisible()

  // Q3: skip. Skipping auto-advances to Q4, unlike answer submission.
  await page.locator('button[title^="Q3:"]').click()
  await page.getByRole('button', { name: 'Skip' }).click()
  await expect(page.locator('button[title^="Q3:"]')).toHaveAttribute('title', /skipped/)
  await expect(page.getByText('Q4 of')).toBeVisible()

  // Q4: unsubmitted draft.
  const q4RadioCount = await page.locator('input[type="radio"]').count()
  let q4DraftText = ''
  if (q4RadioCount === 0) {
    q4DraftText = 'draft answer for Q4'
    await page.getByPlaceholder('Type your answer…').fill(q4DraftText)
  } else {
    await page.locator('input[type="radio"]').first().check()
  }

  const timerBefore = await page.locator('span.font-mono').textContent()

  await page.reload()
  // Reload resumes at the first resumable question (Q2, still wrong_1), not
  // wherever the view happened to be before reload — navigate back to Q4.
  await expect(page.getByText('Q2 of')).toBeVisible({ timeout: 15000 })

  // States reconstructed from server interaction history.
  await expect(page.locator('button[title^="Q1:"]')).toHaveAttribute('title', /correct/)
  await expect(page.locator('button[title^="Q2:"]')).toHaveAttribute('title', /wrong_1/)
  await expect(page.locator('button[title^="Q3:"]')).toHaveAttribute('title', /skipped/)

  await page.locator('button[title^="Q4:"]').click()
  await expect(page.getByText('Q4 of')).toBeVisible()

  // Draft restored on Q4.
  if (q4RadioCount === 0) {
    await expect(page.getByPlaceholder('Type your answer…')).toHaveValue(q4DraftText)
  } else {
    await expect(page.locator('input[type="radio"]').first()).toBeChecked()
  }

  // Timer kept running server-side across the reload (didn't reset to full duration).
  const timerAfter = await page.locator('span.font-mono').textContent()
  expect(timerAfter).not.toBeNull()
  expect(timerBefore).not.toBeNull()
  const toSeconds = (t: string) => {
    const [m, s] = t.split(':').map(Number)
    return m * 60 + s
  }
  expect(toSeconds(timerAfter!)).toBeLessThanOrEqual(toSeconds(timerBefore!))
})
