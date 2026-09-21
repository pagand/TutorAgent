// frontend/e2e/experiment-arms.spec.ts
// The chat and ChatIQ arms are assigned in the manifest and are read-only to
// the student. Removing the panel is not access control, so the chat-off arm
// is also asserted against the endpoint itself, not only the DOM.
import { test, expect } from '@playwright/test'
import { loginAsToken, apiUrl } from './helpers'

test('chat-off arm: no chat panel, neutral profile wording, endpoint refuses', async ({ page, request }) => {
  await loginAsToken(page, 'E2ECHATOFF')

  await expect(page.getByPlaceholder('Ask a question…')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Chat with Tutor' })).toHaveCount(0)

  const sessionId = await page.evaluate(() => localStorage.getItem('sessionId'))
  const res = await request.post(`${apiUrl()}/chat/`, {
    data: { user_id: 'E2ECHATOFF', session_id: sessionId, question_number: 1, message: 'hello' },
  })
  expect(res.status()).toBe(403)

  await page.goto('/profile')
  await expect(page.getByText('Not available in this session')).toBeVisible()
  await expect(page.getByText('ChatIQ', { exact: true })).toHaveClass(/text-slate-500/)
})

test('chatiq-off arm: chat panel is present, ChatIQ reads as off', async ({ page }) => {
  await loginAsToken(page, 'E2ECHATIQOFF')

  await expect(page.getByPlaceholder('Ask a question…')).toBeVisible()

  await page.goto('/profile')
  await expect(page.getByText('Available in this session')).toBeVisible()
  await expect(page.getByText('ChatIQ', { exact: true })).toHaveClass(/text-slate-500/)
})

test('chatiq-on arm: the ChatIQ tag reads as on', async ({ page }) => {
  await loginAsToken(page, 'E2ECHATIQON')

  await expect(page.getByPlaceholder('Ask a question…')).toBeVisible()

  await page.goto('/profile')
  await expect(page.getByText('ChatIQ', { exact: true })).toHaveClass(/text-emerald-700/)
})
