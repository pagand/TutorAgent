// frontend/e2e/timer-expiry.spec.ts
// Deterministically forces the session's exam_start_ms into the past (no real
// wall-clock waiting) so the client-side countdown reaches zero within seconds,
// then confirms auto-submit, redirect to /results, and that a stray reload
// afterward redirects straight back rather than re-showing the quiz.
import { test, expect } from '@playwright/test'
import { loginAsToken, expireSession } from './helpers'

test('timer expiry: countdown reaches zero, auto-submits, redirects to results', async ({ page }) => {
  await loginAsToken(page, 'E2ETIMER')

  // Rewrite the just-created session's exam_start_ms so ~3s remain, then
  // reload so the client re-syncs examStartMs/examDurationMs from the server
  // (idempotent /session/start returns the existing, now-near-expired row).
  expireSession('E2ETIMER', 3)
  await page.reload()
  await expect(page.getByText('Q1 of')).toBeVisible({ timeout: 15000 })

  await expect(page).toHaveURL(/\/results/, { timeout: 15000 })
  await expect(page.getByText("Time's up!")).toBeVisible()

  // A stray reload afterward must redirect straight back to /results.
  await page.goto('/quiz')
  await expect(page).toHaveURL(/\/results/, { timeout: 15000 })
})
