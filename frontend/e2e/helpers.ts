// frontend/e2e/helpers.ts
// Shared helpers for the Stage 1b E2E suite.
import { Page, APIRequestContext, expect } from '@playwright/test'
import { execFileSync } from 'child_process'
import path from 'path'

const REPO_ROOT = path.resolve(__dirname, '..', '..')
const PYTHON_BIN = path.join(REPO_ROOT, '.venv', 'bin', 'python3')

/**
 * Test-only oracle: reads the correct answer for a question directly from the
 * CSV question_service loads from (frontend/e2e/fixtures/answer_key.py),
 * never over HTTP. GET /questions/ and POST /answer/ deliberately never
 * expose this field (Stage 1a) — tests that need a genuinely correct answer
 * must source it here, not from the network.
 */
export function getCorrectAnswer(questionNumber: number): string {
  const script = path.join(__dirname, 'fixtures', 'answer_key.py')
  const output = execFileSync(PYTHON_BIN, [script, String(questionNumber)], { cwd: REPO_ROOT }).toString()
  const lines = output.trim().split('\n')
  return lines[lines.length - 1].trim()
}

export function expireSession(userId: string, secondsRemaining = 3) {
  const script = path.join(__dirname, 'fixtures', 'expire_session.py')
  const dbUser = process.env.E2E_DB_USER || process.env.USER || 'postgres'
  const databaseUrl = process.env.E2E_DATABASE_URL || `postgresql+asyncpg://${dbUser}@localhost:5432/aitutor_e2e_db`
  execFileSync(PYTHON_BIN, [script, userId, String(secondsRemaining)], {
    cwd: REPO_ROOT,
    env: { ...process.env, DATABASE_URL: databaseUrl },
  })
}

/** Bulk-extends every unsubmitted session's timer, mirroring the Streamlit "Exam Control" action. */
export function extendAllTimers(extraMinutes: number) {
  const script = path.join(__dirname, 'fixtures', 'extend_all_timers.py')
  const dbUser = process.env.E2E_DB_USER || process.env.USER || 'postgres'
  const databaseUrl = process.env.E2E_DATABASE_URL || `postgresql+asyncpg://${dbUser}@localhost:5432/aitutor_e2e_db`
  execFileSync(PYTHON_BIN, [script, String(extraMinutes)], {
    cwd: REPO_ROOT,
    env: { ...process.env, DATABASE_URL: databaseUrl },
  })
}

export function apiUrl(): string {
  return process.env.E2E_API_URL || 'http://127.0.0.1:8000'
}

/** Logs in with a fresh (never-started) token and lands on /quiz with question 1 visible. */
export async function loginAsToken(page: Page, token: string) {
  await page.goto('/login')
  await page.getByPlaceholder(/Z7XN5Z4H/i).fill(token)
  await page.getByRole('button', { name: 'Continue' }).click()
  await page.getByRole('button', { name: 'Start Exam' }).click()
  await expect(page.getByText('Q1 of')).toBeVisible({ timeout: 15000 })
}

/** Submits an answer directly against the backend, bypassing the UI entirely. */
export async function submitAnswerDirect(request: APIRequestContext, payload: {
  user_id: string
  question_number: number
  attempt_key: string
  user_answer?: string
  skipped?: boolean
}) {
  return request.post(`${apiUrl()}/answer/`, { data: payload })
}

export async function getProfile(request: APIRequestContext, userId: string) {
  const res = await request.get(`${apiUrl()}/users/${userId}/profile`)
  return res.json()
}

export function randomAttemptKey(): string {
  return `e2e-attempt-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`
}
