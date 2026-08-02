// frontend/e2e/global-setup.ts
// Migrates the dedicated E2E database to head, then seeds the fixed Participant
// tokens used by every spec — both run before the suite starts. Python owns all
// DB writes (matching the rest of the repo's conventions); this just shells out
// to alembic and the seed script rather than touching Postgres directly. This
// means `npx playwright test` is self-contained beyond having Postgres running
// and `aitutor_e2e_db` created (`createdb aitutor_e2e_db`) — no manual alembic
// step required first.
import { execFileSync } from 'child_process'
import path from 'path'

export default async function globalSetup() {
  const dbUser = process.env.E2E_DB_USER || process.env.USER || 'postgres'
  const databaseUrl = process.env.E2E_DATABASE_URL || `postgresql+asyncpg://${dbUser}@localhost:5432/aitutor_e2e_db`
  const repoRoot = path.resolve(__dirname, '..', '..')
  const seedScript = path.join(__dirname, 'fixtures', 'seed_participants.py')
  const pythonBin = path.join(repoRoot, '.venv', 'bin', 'python3')
  const alembicBin = path.join(repoRoot, '.venv', 'bin', 'alembic')
  const env = { ...process.env, DATABASE_URL: databaseUrl }

  execFileSync(alembicBin, ['upgrade', 'head'], { cwd: repoRoot, env, stdio: 'inherit' })
  execFileSync(pythonBin, [seedScript], { cwd: repoRoot, env, stdio: 'inherit' })
}
