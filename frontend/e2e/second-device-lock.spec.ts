// frontend/e2e/second-device-lock.spec.ts
// Two browser contexts share one token, simulating two devices. Confirms the
// existing /login active_elsewhere handling (regression guard), and the new
// /quiz 409 handling (Stage 1a fix) for a proctor moving a student straight
// to /quiz on a spare device, bypassing /login entirely.
import { test, expect } from '@playwright/test'
import { loginAsToken, submitAnswerDirect, randomAttemptKey } from './helpers'

test('second device lock: /login shows active_elsewhere, /quiz shows device-conflict CTA, device A unaffected', async ({ browser }) => {
  const contextA = await browser.newContext()
  const pageA = await contextA.newPage()
  await loginAsToken(pageA, 'E2ELOCK')

  // Device B: a plain /login attempt with the same token, while A's lock is fresh.
  const contextB = await browser.newContext()
  const pageB = await contextB.newPage()
  await pageB.goto('/login')
  await pageB.getByPlaceholder(/Z7XN5Z4H/i).fill('E2ELOCK')
  await pageB.getByRole('button', { name: 'Continue' }).click()
  await expect(pageB.getByText('Token already in use')).toBeVisible()
  await expect(pageB.getByText('Try a different token')).toBeVisible()

  // Device B: bypass /login entirely (simulating a proctor moving the student
  // straight to /quiz on a spare device) — this hits /session/start's 409 directly.
  await pageB.evaluate(() => {
    localStorage.setItem('userId', 'E2ELOCK')
    localStorage.setItem('sessionId', 'device-b-session')
  })
  await pageB.goto('/quiz')
  await expect(pageB.getByText('This exam token is now active on another device.')).toBeVisible({ timeout: 15000 })
  const backToLogin = pageB.getByRole('link', { name: 'Back to login' })
  await expect(backToLogin).toBeVisible()
  await expect(pageB.getByRole('button', { name: 'Retry' })).toHaveCount(0)

  await backToLogin.click()
  await expect(pageB).toHaveURL(/\/login/)

  // Device A must be entirely unaffected throughout.
  await expect(pageA.getByText('Q1 of')).toBeVisible()

  // Row-level access control (Stage 3): a request carrying the right token
  // but the WRONG session_id — i.e. someone who only knows the token, not
  // the device-bound session_id device A is holding — must be rejected,
  // independent of any UI state. This is the direct-API guard for the
  // "any token holder can act as that student" IDOR finding.
  const forged = await submitAnswerDirect(pageA.request, {
    user_id: 'E2ELOCK',
    session_id: 'not-device-as-session-id',
    question_number: 5,
    attempt_key: randomAttemptKey(),
    user_answer: '1',
  })
  expect(forged.status()).toBe(403)

  await contextA.close()
  await contextB.close()
})
