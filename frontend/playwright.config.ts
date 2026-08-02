// frontend/playwright.config.ts
import { defineConfig, devices } from '@playwright/test'

const baseURL = process.env.E2E_BASE_URL || 'http://localhost:3000'

export default defineConfig({
  testDir: './e2e',
  globalSetup: require.resolve('./e2e/global-setup.ts'),
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: 'list',
  // Generous: some specs make real Gemini calls (hint, chat), which can be
  // slow on a cold RAG start (per PRELAUNCH_CHECKLIST.md section B).
  timeout: 180000,
  use: {
    baseURL,
    trace: 'retain-on-failure',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
  // Serves the real static export (npm run build) rather than `next dev` — this
  // is what students actually experience (CloudFront serving static files in
  // prod), and it avoids dev-server-only artifacts (React StrictMode's double
  // effect invocation, Next dev's RSC navigation quirks) that don't reflect
  // real behavior and would otherwise make this suite flaky for the wrong reasons.
  webServer: {
    // No -s/--single: Next's static export already has a real index.html per
    // route directory (login/, quiz/, results/, ...) with its own trailing-slash
    // redirects; -s's SPA fallback rewrites any near-miss (e.g. /quiz without
    // the trailing slash) to the root index.html, which always redirects to
    // /login — that silently broke page.reload() on every non-root route.
    command: 'npm run build && npx serve out -l 3000',
    url: baseURL,
    reuseExistingServer: !process.env.CI,
    timeout: 180000,
    env: {
      NEXT_PUBLIC_API_URL: process.env.E2E_API_URL || 'http://127.0.0.1:8000',
    },
  },
})
