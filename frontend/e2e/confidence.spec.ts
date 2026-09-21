// frontend/e2e/confidence.spec.ts
// The confidence bar nudges once, then lets an empty submission through.
// Asserted at the network level, because "the button did nothing" and "the
// button submitted and the UI hasn't repainted yet" look identical in the DOM.
import { test, expect } from '@playwright/test'
import { loginAsToken, getCorrectAnswer } from './helpers'

async function answerMcOrFitb(page: import('@playwright/test').Page, value: string) {
  const radioCount = await page.locator('input[type="radio"]').count()
  if (radioCount > 0) {
    await page.locator(`input[type="radio"][value="${value}"]`).check()
  } else {
    await page.getByPlaceholder('Type your answer…').fill(value)
  }
}

test('confidence: first submit is nudged, second submits null, a set level is sent', async ({ page }) => {
  const answerPayloads: string[] = []
  page.on('request', (req) => {
    if (req.method() === 'POST' && req.url().includes('/answer/')) {
      answerPayloads.push(req.postData() || '')
    }
  })

  await loginAsToken(page, 'E2ECONF')

  // Q1: leave the bar untouched. The first Submit must not reach the network.
  await answerMcOrFitb(page, getCorrectAnswer(1))
  const submit = page.getByRole('button', { name: 'Submit Answer' })
  await submit.click()
  await expect(page.getByText('How confident are you?')).toBeVisible()
  expect(answerPayloads).toHaveLength(0)

  // Second click goes through, with no confidence in the payload.
  await submit.click()
  await expect(page.getByText('✓ Correct!')).toBeVisible()
  expect(answerPayloads).toHaveLength(1)
  expect(JSON.parse(answerPayloads[0]).confidence).toBeUndefined()

  // Q2: setting a level submits it on the first click, with no nudge.
  await page.locator('button[title^="Q2:"]').click()
  await answerMcOrFitb(page, getCorrectAnswer(2))
  await page.getByLabel('Confidence 7 of 10').click()
  await page.getByRole('button', { name: 'Submit Answer' }).click()
  await expect(page.getByText('✓ Correct!')).toBeVisible()
  expect(answerPayloads).toHaveLength(2)
  expect(JSON.parse(answerPayloads[1]).confidence).toBe(7)
})

// The bar's ten segments are the tap targets, so their width at phone size is
// a correctness property, not a cosmetic one: with the anchors kept inline
// they collapse to ~17px each at 390px wide.
test.describe('phone width', () => {
  test.use({ viewport: { width: 390, height: 844 } })

  test('confidence: segments stay tappable and the anchors move below the bar', async ({ page }) => {
    await loginAsToken(page, 'E2EMOBILE')

    const segment = page.getByLabel('Confidence 1 of 10')
    const box = await segment.boundingBox()
    expect(box).not.toBeNull()
    expect(box!.width).toBeGreaterThan(24)
    expect(box!.height).toBeGreaterThan(24)

    // guessing/certain render twice in the markup, one for each breakpoint;
    // at this width the inline pair is hidden and the stacked pair shows.
    await expect(page.getByText('guessing')).toHaveCount(2)
    const visible = await page.getByText('guessing').evaluateAll(
      (els) => els.filter((el) => (el as HTMLElement).offsetParent !== null).length
    )
    expect(visible).toBe(1)
  })
})
