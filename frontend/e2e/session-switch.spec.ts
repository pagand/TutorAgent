// frontend/e2e/session-switch.spec.ts
// Regression guards for the bug bash of 2026-08-04, where re-entering the app
// in the same browser broke the exam. Both cases share one root cause: the
// QuizProvider lives in the root layout, so its state survives every
// client-side navigation, and nothing reset it on logout.
//
// 1. Logging out and back in on the SAME token minted a fresh sessionId, but
//    QuizPageContent's init guard matched on userId alone and skipped init, so
//    startSession never claimed the lock for the new sessionId and every
//    answer/hint 403'd with "Failed to submit. Please try again." until a hard
//    reload rebuilt the provider.
// 2. Handing the browser to a DIFFERENT token inherited the previous student's
//    isComplete and their unscoped `examResults`, redirecting the new student
//    straight to /results and exposing the previous student's answer key.
import { test, expect } from '@playwright/test'
import { loginAsToken, getCorrectAnswer } from './helpers'

/** Answers the question currently on screen, handling both MC and free-text. */
async function answerCurrent(page: import('@playwright/test').Page, value: string) {
  const radioCount = await page.locator('input[type="radio"]').count()
  if (radioCount > 0) {
    await page.locator(`input[type="radio"][value="${value}"]`).check()
  } else {
    await page.getByPlaceholder('Type your answer…').fill(value)
  }
  await page.getByRole('button', { name: 'Submit Answer' }).click()
}

test('logging out and back in on the same token can still submit, with no reload', async ({ page }) => {
  await loginAsToken(page, 'E2ESWITCHA')

  // Log out through the profile page, which is the path a student actually has.
  // Navigate by clicking the in-app link, NOT page.goto: a hard navigation
  // tears down the QuizProvider, which is the very thing whose survival across
  // client-side navigation causes this bug. A goto here makes the test pass
  // against the unfixed code.
  page.on('dialog', (d) => d.accept())
  await page.getByRole('link', { name: 'Profile' }).first().click()
  await expect(page).toHaveURL(/\/profile/)
  await page.getByRole('button', { name: /log out/i }).click()
  await expect(page).toHaveURL(/\/login/)

  // Back in on the same token. Logging out clears the saved userId, so the
  // token is retyped. Resuming mints a NEW sessionId, which is precisely what
  // the old init guard ignored.
  await page.getByPlaceholder(/Z7XN5Z4H/i).fill('E2ESWITCHA')
  await page.getByRole('button', { name: 'Continue' }).click()
  await page.getByRole('button', { name: 'Resume Exam' }).click()
  await expect(page.getByText('Q1 of')).toBeVisible({ timeout: 15000 })

  // The regression: this submit 403'd because the context still held the
  // pre-logout sessionId. No reload between logging back in and submitting.
  await answerCurrent(page, getCorrectAnswer(1))
  await expect(page.getByText('✓ Correct!')).toBeVisible({ timeout: 15000 })
  await expect(page.getByText('Failed to submit. Please try again.')).toHaveCount(0)
})

test('switching tokens in the same browser starts a fresh exam and leaks nothing', async ({ page }) => {
  await loginAsToken(page, 'E2ESWITCHB')
  await answerCurrent(page, getCorrectAnswer(1))
  await expect(page.getByText('✓ Correct!')).toBeVisible({ timeout: 15000 })

  await page.getByRole('button', { name: 'Submit Exam' }).click()
  await page.getByRole('button', { name: 'Yes, submit exam' }).click()
  await expect(page).toHaveURL(/\/results/)
  await expect(page.getByText(/1\/25 correct/).first()).toBeVisible()

  // Hand the machine to the next student.
  await page.getByRole('button', { name: /Return to login/i }).click()
  await expect(page).toHaveURL(/\/login/)
  await page.getByRole('button', { name: 'Use a different token' }).click()

  // No trace of the previous student may survive the handover. The unscoped
  // `examResults` key is what previously let the next student read their
  // results and revealed answer key.
  const leftovers = await page.evaluate(() =>
    Object.keys(localStorage).filter(
      (k) => k === 'examResults' || k.startsWith('examResults_') || k.startsWith('quizCache_')
    )
  )
  expect(leftovers).toEqual([])

  // The new student must reach the quiz, not inherit the previous one's
  // completed state and get bounced to /results.
  await page.getByPlaceholder(/Z7XN5Z4H/i).fill('E2ESWITCHC')
  await page.getByRole('button', { name: 'Continue' }).click()
  await page.getByRole('button', { name: 'Start Exam' }).click()
  await expect(page.getByText('Q1 of')).toBeVisible({ timeout: 15000 })
  await expect(page).not.toHaveURL(/\/results/)
})
