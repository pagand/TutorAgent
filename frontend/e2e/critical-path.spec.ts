// frontend/e2e/critical-path.spec.ts
// Login -> correct answer -> wrong twice (locked) -> skip -> hint + rating -> chat -> results.
// Also asserts, at the network level (not just UI non-rendering), that correct_answer
// never appears on the wire for /questions/ or /answer/ (Stage 1a regression guard).
import { test, expect } from '@playwright/test'
import { loginAsToken, getCorrectAnswer, submitAnswerDirect } from './helpers'

function wrongOption(correct: string, exclude: string[] = []): string {
  for (const v of ['1', '2', '3', '4']) {
    if (v !== correct && !exclude.includes(v)) return v
  }
  throw new Error('no wrong option available among 1-4')
}

async function answerMcOrFitb(page: import('@playwright/test').Page, value: string) {
  const radioCount = await page.locator('input[type="radio"]').count()
  if (radioCount > 0) {
    await page.locator(`input[type="radio"][value="${value}"]`).check()
  } else {
    await page.getByPlaceholder('Type your answer…').fill(value)
  }
}

test('critical path: correct, locked wrong, skip, hint+rating, chat, results — no correct_answer leak', async ({ page }) => {
  const leakedResponses: string[] = []
  page.on('response', async (res) => {
    const url = res.url()
    if (!url.includes('/questions/') && !url.includes('/answer/')) return
    const contentType = res.headers()['content-type'] || ''
    if (!contentType.includes('application/json')) return
    try {
      const body = await res.text()
      if (body.includes('correct_answer')) leakedResponses.push(url)
    } catch { /* ignore bodies that can't be read */ }
  })

  await loginAsToken(page, 'E2ECRITPATH')

  // Q1: correct answer.
  const q1Correct = getCorrectAnswer(1)
  await answerMcOrFitb(page, q1Correct)
  await page.getByRole('button', { name: 'Submit Answer' }).click()
  await expect(page.getByText('✓ Correct!')).toBeVisible()

  // Q2: wrong twice -> locked.
  await page.locator('button[title^="Q2:"]').click()
  const q2Correct = getCorrectAnswer(2)
  const q2Wrong1 = wrongOption(q2Correct)
  await answerMcOrFitb(page, q2Wrong1)
  await page.getByRole('button', { name: 'Submit Answer' }).click()
  await expect(page.getByText('1 attempt remaining')).toBeVisible()

  const q2Wrong2 = wrongOption(q2Correct, [q2Wrong1])
  await answerMcOrFitb(page, q2Wrong2)
  await page.getByRole('button', { name: 'Submit Answer' }).click()
  await expect(page.getByText('✗ Locked — Move on to the next question')).toBeVisible()

  // Server-side cap must reject a 3rd submission independently of the UI —
  // even a genuinely correct answer, once locked.
  const thirdAttempt = await submitAnswerDirect(page.request, {
    user_id: 'E2ECRITPATH',
    question_number: 2,
    attempt_key: `e2e-extra-${Date.now()}`,
    user_answer: q2Correct,
  })
  expect(thirdAttempt.status()).toBe(409)

  // Q3: skip. Skipping auto-advances to the next resumable question (Q4),
  // unlike answer submission, which never auto-advances.
  await page.locator('button[title^="Q3:"]').click()
  await page.getByRole('button', { name: 'Skip' }).click()
  await expect(page.locator('button[title^="Q3:"]')).toHaveAttribute('title', /skipped/)
  await expect(page.getByText('Q4 of')).toBeVisible()

  // Q4: hint + star rating, then answer correctly.
  await page.getByRole('button', { name: 'Get Hint' }).click()
  await expect(page.getByText('Was this hint helpful?')).toBeVisible({ timeout: 30000 })
  await page.locator('button:has-text("★")').nth(4).click()

  const q4Correct = getCorrectAnswer(4)
  await answerMcOrFitb(page, q4Correct)
  await page.getByRole('button', { name: 'Submit Answer' }).click()
  await expect(page.getByText('✓ Correct!')).toBeVisible()

  // Chat with tutor (panel is open by default — only toggle it if collapsed).
  const chatInput = page.getByPlaceholder('Ask a question…')
  if (!(await chatInput.isVisible())) {
    await page.getByText('Chat with Tutor').click()
  }
  await chatInput.fill('Can you explain this concept?')
  const chatResponsePromise = page.waitForResponse(
    (res) => res.url().includes('/chat/') && res.request().method() === 'POST',
    { timeout: 90000 }
  )
  await page.getByRole('button', { name: 'Send' }).click()
  const chatRes = await chatResponsePromise
  expect(chatRes.status()).toBe(200)
  await expect(page.locator('div.rounded-br-none')).toHaveCount(1)
  await expect(page.locator('div.rounded-bl-none')).toHaveCount(1)

  // End the exam early and check the results summary.
  await page.getByRole('button', { name: 'Submit Exam' }).click()
  await page.getByRole('button', { name: 'Yes, submit exam' }).click()
  await expect(page).toHaveURL(/\/results/)
  await expect(page.getByText(/2\/25 correct/).first()).toBeVisible()

  expect(leakedResponses).toEqual([])
})
