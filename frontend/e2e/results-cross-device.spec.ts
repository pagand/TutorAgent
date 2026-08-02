// frontend/e2e/results-cross-device.spec.ts
// A completed exam's results must be viewable from a device that never held
// the session lock — the "slow path" in app/results/page.tsx, reached when a
// student re-enters their token on a fresh browser after finishing elsewhere.
// Regression guard for a Stage 3 hardening hazard: gating GET /users/{id}/profile
// on the session_id that claimed the lock would otherwise 403 this exact case,
// since a fresh browser has no sessionId in localStorage at all.
import { test, expect } from '@playwright/test'
import { loginAsToken, getCorrectAnswer } from './helpers'

test('results cross-device: a fresh browser with no session_id can still view a completed exam', async ({ browser }) => {
  const deviceA = await browser.newContext()
  const pageA = await deviceA.newPage()
  await loginAsToken(pageA, 'E2EXDEVICE')

  const q1Correct = getCorrectAnswer(1)
  const q1RadioCount = await pageA.locator('input[type="radio"]').count()
  if (q1RadioCount > 0) {
    await pageA.locator(`input[type="radio"][value="${q1Correct}"]`).check()
  } else {
    await pageA.getByPlaceholder('Type your answer…').fill(q1Correct)
  }
  await pageA.getByRole('button', { name: 'Submit Answer' }).click()
  await expect(pageA.getByText('✓ Correct!')).toBeVisible()

  // Q2: wrong twice -> locked, so its correct answer is genuinely revealed
  // on /results (unlike Q1, where the "correct" status suppresses the
  // reveal since the student's own answer already shown it was right) —
  // this is what makes the profile-fetch assertion below meaningful.
  await pageA.locator('button[title^="Q2:"]').click()
  const q2Correct = getCorrectAnswer(2)
  const wrongOption = (correct: string) => (['1', '2', '3', '4'].find((v) => v !== correct) as string)
  const q2Wrong1 = wrongOption(q2Correct)
  const q2RadioCount = await pageA.locator('input[type="radio"]').count()
  if (q2RadioCount > 0) {
    await pageA.locator(`input[type="radio"][value="${q2Wrong1}"]`).check()
  } else {
    await pageA.getByPlaceholder('Type your answer…').fill(q2Wrong1)
  }
  await pageA.getByRole('button', { name: 'Submit Answer' }).click()
  await expect(pageA.getByText('1 attempt remaining')).toBeVisible()

  const q2Wrong2 = ['1', '2', '3', '4'].find((v) => v !== q2Correct && v !== q2Wrong1) as string
  if (q2RadioCount > 0) {
    await pageA.locator(`input[type="radio"][value="${q2Wrong2}"]`).check()
  } else {
    await pageA.getByPlaceholder('Type your answer…').fill(q2Wrong2)
  }
  await pageA.getByRole('button', { name: 'Submit Answer' }).click()
  await expect(pageA.getByText('✗ Locked — Move on to the next question')).toBeVisible()

  await pageA.getByRole('button', { name: 'Submit Exam' }).click()
  await pageA.getByRole('button', { name: 'Yes, submit exam' }).click()
  await expect(pageA).toHaveURL(/\/results/)
  await deviceA.close()

  // Device B: a completely fresh context — no localStorage, no sessionId,
  // never held the lock. Only the token itself.
  const deviceB = await browser.newContext()
  const pageB = await deviceB.newPage()
  await pageB.goto('/login')
  await pageB.getByPlaceholder(/Z7XN5Z4H/i).fill('E2EXDEVICE')
  await pageB.getByRole('button', { name: 'Continue' }).click()
  await expect(pageB).toHaveURL(/\/results/, { timeout: 15000 })

  // The answer key must actually render, not come back blank from a 403 —
  // Q2 is locked (wrong_2), so its correct answer is only visible here if
  // the profile fetch (gated by session_id) actually succeeded.
  await expect(pageB.getByText(/1\/25 correct/).first()).toBeVisible()
  await expect(pageB.getByText(/Correct answer:/).first()).toBeVisible()

  await deviceB.close()
})
