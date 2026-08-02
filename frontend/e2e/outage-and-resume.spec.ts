// frontend/e2e/outage-and-resume.spec.ts
// The headline test. Simulates a lost response (server commits, browser never
// sees the reply) via Playwright network interception — never Docker, per
// CLAUDE.md's "do not run Docker locally" rule. Confirms the retry is deduped
// server-side (no false wrong_2 lock), that an unsubmitted draft survives reload,
// and (Stage 2) that a bulk admin timer extension reaches this already-open tab
// within one heartbeat, with no reload — the other half of "restart services,
// retain data, resume the exam."
import { test, expect } from '@playwright/test'
import { loginAsToken, getCorrectAnswer, getProfile, extendAllTimers } from './helpers'

test('outage-and-resume: lost response is deduped, draft survives reload', async ({ page }) => {
  await loginAsToken(page, 'E2EOUTAGE')

  // Q1: answer normally (no interception) to confirm the golden path still works.
  const q1Correct = getCorrectAnswer(1)
  const q1RadioCount = await page.locator('input[type="radio"]').count()
  if (q1RadioCount > 0) {
    await page.locator(`input[type="radio"][value="${q1Correct}"]`).check()
  } else {
    await page.getByPlaceholder('Type your answer…').fill(q1Correct)
  }
  await page.getByRole('button', { name: 'Submit Answer' }).click()
  await expect(page.getByText('✓ Correct!')).toBeVisible()

  // Q2: simulate an outage on the FIRST /answer/ request only — the real
  // request reaches the server and commits, but the browser never sees the reply.
  await page.locator('button[title^="Q2:"]').click()
  const q2Correct = getCorrectAnswer(2)
  const q2Wrong = q2Correct === '1' ? '2' : '1'

  let lostOnce = false
  await page.route('**/answer/', async (route) => {
    const postData = route.request().postDataJSON()
    if (postData.question_number === 2 && !lostOnce) {
      lostOnce = true
      await route.fetch() // real request — server processes and commits it
      await route.abort('failed') // browser never receives the response
    } else {
      await route.continue()
    }
  })

  const q2RadioCount = await page.locator('input[type="radio"]').count()
  if (q2RadioCount > 0) {
    await page.locator(`input[type="radio"][value="${q2Wrong}"]`).check()
  } else {
    await page.getByPlaceholder('Type your answer…').fill(q2Wrong)
  }
  await page.getByRole('button', { name: 'Submit Answer' }).click()
  await expect(page.getByText('Failed to submit. Please try again.')).toBeVisible()

  // Confirm the precondition is real: the server already committed the log
  // row despite the browser having received nothing.
  const profileAfterLoss = await getProfile(page.request, 'E2EOUTAGE');
  const q2LogsAfterLoss = profileAfterLoss.interaction_history.filter((l: { question_id: number }) => l.question_id === 2)
  expect(q2LogsAfterLoss.length).toBe(1)

  // Retry with the same unmodified answer — attemptKeyRef was preserved
  // across the failed attempt, so this must be deduped server-side.
  await page.getByRole('button', { name: 'Submit Answer' }).click()
  await expect(page.getByText('1 attempt remaining')).toBeVisible()

  const profileAfterRetry = await getProfile(page.request, 'E2EOUTAGE')
  const q2LogsAfterRetry = profileAfterRetry.interaction_history.filter((l: { question_id: number }) => l.question_id === 2)
  expect(q2LogsAfterRetry.length).toBe(1) // still exactly one row — no duplicate from the retry

  // The question must be wrong_1, not falsely wrong_2 — the exact failure this fixes.
  const q2NavButton = page.locator('button[title^="Q2:"]')
  await expect(q2NavButton).toHaveAttribute('title', /wrong_1/)

  await page.unroute('**/answer/')

  // Draft persistence: type into Q3 without submitting, reload, confirm it survives.
  await page.locator('button[title^="Q3:"]').click()
  const draftText = 'unsubmitted draft text'
  const q3RadioCount = await page.locator('input[type="radio"]').count()
  if (q3RadioCount > 0) {
    // MC question — "draft" is a selection rather than free text.
    await page.locator('input[type="radio"]').first().check()
  } else {
    await page.getByPlaceholder('Type your answer…').fill(draftText)
  }
  await page.reload()
  // Reload resumes at the first resumable question (Q2, still wrong_1), not
  // wherever the view happened to be before reload — navigate back to Q3.
  await expect(page.getByText('Q2 of')).toBeVisible({ timeout: 15000 })
  await page.locator('button[title^="Q3:"]').click()
  await expect(page.getByText('Q3 of')).toBeVisible()

  if (q3RadioCount > 0) {
    await expect(page.locator('input[type="radio"]').first()).toBeChecked()
  } else {
    await expect(page.getByPlaceholder('Type your answer…')).toHaveValue(draftText)
  }

  // Timer compensation (Stage 2): a bulk admin extension only touches the DB.
  // It must reach this already-open tab via the next heartbeat (≤25s) — with
  // no reload — or the extension is cosmetic for the exact outage it exists
  // to cover, and a stale-timer tab would auto-submit itself right through it.
  const timerLocator = page.getByTestId('timer-remaining')
  const parseRemaining = (text: string | null) => {
    const [min, sec] = (text || '0:00').split(':').map(Number)
    return min * 60 + sec
  }
  const beforeSeconds = parseRemaining(await timerLocator.textContent())

  extendAllTimers(10)

  await expect(async () => {
    const afterSeconds = parseRemaining(await timerLocator.textContent())
    // ~10 minutes added; allow for the few seconds of tick drift between reads.
    expect(afterSeconds - beforeSeconds).toBeGreaterThan(9 * 60)
    // 45s timeout: the 25s heartbeat interval's phase is arbitrary (it restarts
    // on the page.reload() above), so worst case is ~26-27s before the next tick.
  }).toPass({ timeout: 45000 })
})
