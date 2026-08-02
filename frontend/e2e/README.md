# E2E test suite (Stage 1b)

Playwright specs covering the critical path, outage-and-resume, second-device
lock, reload recovery, and timer expiry. Runs against a real static-export
build (`npm run build` + `serve`, not `next dev`) and a dedicated local
Postgres database, isolated from your normal dev DB.

## One-time setup

```bash
createdb aitutor_e2e_db
```

That's it — `npx playwright test` runs `alembic upgrade head` against it and
seeds the fixture participant tokens automatically (`e2e/global-setup.ts`).

## Running

From `frontend/`, with the backend's `.venv` available at `../.venv` (used to
shell out to alembic and the Python fixture scripts):

```bash
# Terminal 1 — backend, pointed at the E2E database
DATABASE_URL=postgresql+asyncpg://<user>@localhost:5432/aitutor_e2e_db \
  ../.venv/bin/uvicorn app.main:app --port 8000
# (run from the repo root, not frontend/)

# Terminal 2 — the suite itself
cd frontend
npx playwright test
```

`playwright.config.ts` starts the frontend for you (`npm run build && npx serve out`)
against `E2E_API_URL` (defaults to `http://127.0.0.1:8000`). The backend is
**not** started automatically — it needs the `DATABASE_URL` override above
before `playwright test` runs, so start it yourself first.

## Env vars (all optional, sensible defaults for local dev)

| Var | Default | Used for |
|---|---|---|
| `E2E_DATABASE_URL` | `postgresql+asyncpg://$USER@localhost:5432/aitutor_e2e_db` | alembic + seed script (`global-setup.ts`) |
| `E2E_DB_USER` | `$USER` | shorthand to override just the user in the default `E2E_DATABASE_URL` |
| `E2E_API_URL` | `http://127.0.0.1:8000` | frontend build's `NEXT_PUBLIC_API_URL`, and `helpers.ts`'s direct API calls |
| `E2E_BASE_URL` | `http://localhost:3000` | Playwright's `baseURL` and the `webServer` it manages |

## Gate

All 5 specs green locally, no AWS spend. If hint/chat specs are flaky, it's
almost always real Gemini latency (RAG cold start) — see
`PRELAUNCH_CHECKLIST.md` section B — not a real failure.
