# Pre-Launch Checklist — Phase 3 Go-Live

Everything that must be considered, implemented, or verified before 50 students sit a proctored exam on this system.
Nothing here is implemented yet unless the box is ticked.
Priorities: **P0** blocks go-live, **P1** should be fixed before go-live, **P2** is post-exam cleanup.

Findings are recorded with the file and line that produced them so nothing has to be re-derived.

---

## Section 0 — Deploy blockers and exam integrity

Found by independent audit, all verified directly against the code.
These outrank everything below them.
Four of them would have caused an exam-day failure that nothing else in this document would have caught.

| | Pri | Item | Detail |
|---|---|---|---|
| [x] | **P0** | **`alembic/` is not in git** | **Fixed.** `alembic/` and `alembic.ini` are now tracked (`.gitignore:25`'s `alembic*` line removed). `alembic.ini`'s personal dev DSN was neutralised to a placeholder; `alembic/env.py` now calls `load_dotenv()` so local `.venv` runs still resolve the real `DATABASE_URL` from `.env`. |
| [x] | **P0** | **`prod/data/` is not in git** | **Fixed, by design choice rather than by tracking it.** `prod/data/` stays gitignored (answer key + participant tokens should never enter git history) and is now also excluded via `.dockerignore` so it can never be baked into an image layer. It arrives only through the existing read-only bind mount, copied out-of-band (`scp`) as a documented deploy step in `README.md` and CLAUDE.md 3.3. **Corrected finding:** the original "sys.exit(1), second crash loop" claim was wrong — `question_service.load_questions` only logs on `FileNotFoundError` (`app/services/question_service.py:72-73`) and `ingest_pdf` returns early on a missing PDF (`app/services/pdf_ingestion.py:20-22`); the API boots healthy and silently serves an empty quiz. Closed instead with a fail-fast guard in `app/main.py`'s `lifespan`: raises `RuntimeError` if zero questions load, converting the silent failure into a loud boot failure. |
| [x] | **P0** | **`GET /questions/` serves the answer key** | **Fixed (Stage 1a).** Added `PublicQuestion` (`app/models/question.py`) — same shape minus `correct_answer` — and switched both `questions.py` endpoints to build it via explicit field construction (robust against the test fixture's mocked question object too, not just real `Question` instances). `correct_answer` is now absent from `GET /questions/` and `GET /questions/{n}` on the wire, verified by `tests/test_questions.py` and a live network-response check during manual smoke testing. |
| [x] | **P0** | **`POST /answer/` is not idempotent** | **Fixed (Stage 1a).** Added `attempt_key` (client-generated, stable across retries of the same submission, rotated on a genuinely new attempt) to `AnswerRequest` and a matching `attempt_key` column + unique index `(user_id, question_id, attempt_key)` on `InteractionLog` (migration `f3a1c9d47b2e`). `submit_answer` now checks for an existing row with the same key first and returns the already-committed outcome with zero mutation on a replay, before doing anything else. Locked in by `tests/test_answer.py` (exact-one-row + no-double-counting assertions) and the `outage-and-resume` E2E spec (`frontend/e2e/outage-and-resume.spec.ts`), which reproduces "server commits, browser never sees the reply" via network interception and confirms the retry does not falsely produce `wrong_2`. |
| [x] | **P0** | **`POST /answer/` leaks `correct_answer` on every response** | **Fixed (Stage 1a).** Removed `correct_answer` from `AnswerResponse` entirely. Frontend no longer reads `result.correct_answer` (`QuizPageContent.tsx`'s `SUBMIT_RESULT` dispatch dropped the field); `saveAndRedirect` now sources the results-page answer key from `GET /users/{id}/profile`'s `completed_answers` instead, matching the pattern already used by the reload-recovery path and `results/page.tsx`'s slow path. Verified with no `correct_answer` key on any `/answer/` response, live and in `tests/test_answer.py`. |
| [x] | **P0** | **No server-side cap on wrong attempts** | **Fixed (Stage 1a), with a correction to this row's own proposed fix.** `consecutive_errors >= 2` (as originally suggested here) is the wrong condition — it lives on `SkillMastery`, scoped per `(user_id, skill)`, not per question, so using it would lock a student out of a fresh question the moment a *different* question sharing the same skill had two wrong attempts. Implemented instead: count real `InteractionLog` rows (`user_answer IS NOT NULL`) for the exact `(user_id, question_id)`; reject (`409`) a 3rd submission — answer or skip — once 2 exist with none correct. Covered by `tests/test_answer.py` (including a dedicated test proving the cap is per-question, not per-skill) and `critical-path.spec.ts`'s direct-API assertion that a 3rd attempt is rejected independent of the UI. |
| [ ] | **P0** | No `443` mapping or cert volume in compose | `docker-compose.yml:42-45` exposes only `80:80` and mounts only `nginx.conf`. CLAUDE.md's sketch has both `443` and `./certbot:/etc/letsencrypt`; the real file has neither. Without the volume, every `docker compose down` destroys the certificates. |
| [ ] | **P0** | nginx rate limit keyed per source IP | `nginx.conf:13` uses `$binary_remote_addr`. If 50 students sit in one hall behind one NAT egress IP, they share a single 20 r/s bucket. A synchronised exam start (50 students x 3 init calls) blows past `burst=50` and returns **503 on `/session/start`**. The earlier "3.3 r/s, comfortable" analysis was wrong: it omitted the 25s heartbeat and the `/log/action` stream. |
| [x] | **P1** | `draftAnswers` is not persisted | **Fixed (Stage 1a).** `draftAnswers` now included in the `quizCache_<userId>` payload alongside `hints`/`chatHistory`; `LOAD_QUIZ` seeds drafts from the cache instead of resetting to `{}`. Verified live (type a partial answer, reload, text survives) and by `outage-and-resume.spec.ts` / `reload-recovery.spec.ts`. |
| [x] | **P1** | 409 takeover unhandled at `/quiz` | **Fixed (Stage 1a).** `init()`'s catch block now checks `err.response?.status === 409` and shows a specific "This exam token is now active on another device." message with a "Back to login" link, instead of a Retry button that reloads into the same 409. Deliberately routes back to `/login`'s existing `active_elsewhere` state machine rather than duplicating its copy. Verified live (device A holds the lock, device B loads `/quiz` directly) and by `second-device-lock.spec.ts`. |
| [x] | **P1** | `LOG_LEVEL` defaults to DEBUG | **Fixed (Stage 2).** `config.py:29`'s fallback changed to `os.getenv("LOG_LEVEL", "INFO")`, and `.env.docker.example` now sets `LOG_LEVEL=INFO` explicitly. Same trap class as the two config defaults in section H, applied to the variable that actually fills the disk. Guarded by `tests/test_config.py` (source-literal assertion, since local dev's `.env` deliberately sets `DEBUG` and would otherwise mask a regression of the code-level fallback). |
| [ ] | **P1** | Timeout ladder is inconsistent | Gemini client `timeout=60, max_retries=2` (`rag_agent.py:166-167`) is up to ~180s; nginx allows 120s; axios gives up at 90s. The client quits first while the backend keeps working. Worse, the hint catch is empty (`QuizPageContent.tsx:333`): the spinner stops and **nothing appears, with no message**. This is what fires under load. |
| [ ] | **P1** | No non-destructive per-student repair | Streamlit's only remedies are `reset_user_progress` (wipes interactions) and `delete_user`. With no backup, one mis-click during the exam is unrecoverable. |
| [ ] | **P2** | `GET /users/{user_id}/bkt` is broken | `users.py` calls `get_bkt_mastery` with 3 args; the signature takes 4 (`state_manager.py:49`). Every call 500s. Unused by the frontend, but it proves the 50-test suite has real coverage holes. |
| [ ] | **P2** | Results page never reveals skipped answers | `completed_answers` is populated only for correct or 2+ attempt questions (`state_manager.py:115-128`), but CLAUDE.md says results reveal answers for **all** questions. Spec violation students will notice. |
| [x] | **P0** | **`POST /session/start` crashes on a concurrent-request race** | **Found and fixed during Stage 1b.** Two near-simultaneous `/session/start` calls for the same never-before-started user (e.g. a double-click, a retried request after a network blip, or — how this was actually caught — React StrictMode's dev-mode double effect invocation racing two `init()` calls) hit `ExamSession`'s unique constraint, entering the existing `except IntegrityError: await db.rollback()` recovery path. That path re-fetched `exam_session` but not `participant`, which had been loaded earlier in the same now-rolled-back transaction; mutating the stale `participant` object further down crashed with `sqlalchemy.exc.MissingGreenlet` on commit, 500ing the request outright — the exact class of failure the outage-and-resume requirement is supposed to survive, just triggered by a race instead of a network outage. Fixed by re-fetching `participant` inside the `except IntegrityError` branch too (`app/endpoints/session.py`). **No regression guard exists for this fix.** It has no dedicated pytest case (reliably reproducing the race requires real concurrency, not the shared-session pytest fixture) and, despite an earlier version of this note claiming otherwise, no E2E coverage either — `playwright.config.ts` deliberately serves the static export rather than `next dev` specifically *to avoid* React StrictMode's double-effect invocation, which is what originally surfaced this bug, so the E2E suite structurally cannot reproduce it. If this regresses, only a real concurrent-load test (e.g. Stage 6's k6 run, or a manual double-click test) would catch it. |
| [x] | **P0** | **A bulk timer extension would never reach an already-open `/quiz` tab** | **Found and fixed during Stage 2**, while tracing the bulk-extension deliverable back to the resume requirement it exists for. `POST /session/heartbeat` already returned `ms_remaining`, but `QuizPageContent.tsx` discarded it — the countdown ran purely off `examStartMs`/`examDurationMs` captured once at init (`TimerBar.tsx`). An admin bulk extension changes only the DB row; an open tab would still hit its stale zero, `handleTimerExpire` would fire `submitSession`, and the participant would be marked `completed` — locking the student out of the exact exam the extension existed to save. Fixed by having `HeartbeatResponse` also return `exam_start_ms`/`exam_duration_ms`, and dispatching a new `SYNC_TIMER` action from the existing 25s heartbeat poll whenever either value changes (`app/endpoints/session.py`, `QuizContext.tsx`, `QuizPageContent.tsx`). Guarded by `tests/test_session.py::test_heartbeat_reflects_bulk_timer_extension` (server side) and `frontend/e2e/outage-and-resume.spec.ts`'s new timer-compensation assertion (full chain: admin action → DB → heartbeat → reducer → rendered countdown, no reload). |

---

## Execution sequence

Agreed order of work. Each stage has a gate that must pass before the next begins.
No stage starts without explicit go-ahead.

### Stage 0 — Clean-clone deploy test

**Added after audit, and it is the urgent one.**
Clone this repo into a scratch directory and run `docker compose up --build` against that clone, not against the working copy.

This is roughly 20 minutes and it catches the two hard deploy blockers in section 0, neither of which any amount of Playwright-against-dev would ever surface, because dev has the untracked files sitting on disk.
Stage 4's own gate (a `destroy` and re-apply reproduces the box) is unachievable until this passes, so finding it later means rewriting the bootstrap.

- **Gate:** a fresh clone builds, migrates, loads questions, and answers `curl http://localhost/` with the welcome payload

### Stage 1 — Correctness fixes, then E2E

**Reordered after audit.** The original plan put Playwright first.
That was wrong, for a concrete reason: the headline outage-and-resume test cannot be written correctly until the answer-idempotency and draft-persistence decisions are made, because **the test's assertions are the intended behavior**.
Writing it first means writing it, changing the behavior in the next stage, and rewriting it. That rework lands on the most valuable test in the suite.

The claim that E2E was needed because resume "cannot be verified by reading code" was also only half true.
Reading the code found the idempotency bug, the draft loss and the 409 gap, and a naive E2E test would likely have missed all three: the duplicate submission only manifests on a reload *after* a lost response, the draft loss only if the test types without submitting, the 409 only if localStorage is cleared.

**1a. Localized correctness fixes first:** answer idempotency, draft persistence, 409 handling at `/quiz`, strip `correct_answer` from `GET /questions/` **and from `POST /answer/`'s response**, and add a server-side cap rejecting a question's 3rd+ attempt. (Implemented as a per-question count of real `InteractionLog` attempts, not `consecutive_errors >= 2` as originally written here — see the corrected finding on the "No server-side cap on wrong attempts" row above; `consecutive_errors` is scoped per-skill and would have locked unrelated questions.)

**1b. Then Playwright**, locking that behavior in.

- Covers: outage-and-resume, critical path, second-device lock, reload recovery, timer expiry
- **Gate:** all tests green locally
- Cost: nothing beyond LLM calls. No AWS spend.

### Stage 2 — Resume-critical hardening
The fixes that the resume requirement and the exam itself depend on.

- Bulk timer extension, backups plus a restore drill, DB pool sizing, API key middleware, config default alignment (`EXAM_DURATION_MS`, `GOOGLE_MODEL_NAME`)
- **Gate:** stage 1 tests still green, and extended to cover the new behavior

### Stage 3 — Security and code review
Both reviews run here, **before** anything is deployed.

- `/security-review` and `/code-review ultra`, user-triggered
- **Gate:** all blocking findings fixed
- Rationale: reviewing code that is already serving the public internet is backwards. The API key middleware must land first (stage 2) so the review assesses the real security posture.

### Stage 4 — Infrastructure
Terraform, full scope including EC2 user-data bootstrap, per the recorded decision.

- t3.medium, budgets, cost tags, Elastic IP, S3, CloudFront, no NAT Gateway
- **Gate:** `terraform plan` reviewed, clean apply, and a `destroy` plus re-apply reproduces the box identically

### Stage 5 — Deploy and verify
- Deploy, then post-deploy configuration verification (open ports, TLS, headers, CORS enforcement)
- **Gate:** verification clean

### Stage 6 — Rehearsal
- Full dress rehearsal with real tokens, plus k6 at 50 VUs against real Gemini
- **Gate:** p95 targets met (< 5s non-LLM, < 90s for hints and chat), and the outage-and-resume test passes against the real stack

---

## A. Data safety and recovery

| | Pri | Item | Detail |
|---|---|---|---|
| [x] | **P0** | Automated Postgres backup | **Fixed (Stage 2).** `scripts/backup.sh` runs `pg_dump -Fc` to a timestamped file, prunes past `BACKUP_RETENTION_DAYS` (default 14), and uploads to `BACKUP_S3_URI` when that var is set — unset until Stage 4 creates the bucket, so dumps stay local under `BACKUP_DIR` until then. Works both against a directly-reachable `DATABASE_URL` (local dev) and via `docker compose exec` (`DOCKER_DB_SERVICE=db`, since 5432 stays unexposed on EC2 by design). Verified against the real dev DB: a live 96K dump of all 9 tables. Cron line documented in `README.md` and referenced from `SKILL.md` §3.3 for Stage 4's bootstrap to install. |
| [ ] | **P0** | EBS snapshot before and after each exam | Manual or scripted. Two clicks that make the whole exam recoverable. Deferred to section K's exam-day runbook — no EC2 instance exists yet to snapshot. |
| [x] | **P0** | Restore drill | **Fixed (Stage 2).** `scripts/restore_drill.sh` creates a scratch DB, calls `pg_restore` directly to restore the newest dump into it (own `psql`/`pg_restore` calls, not a shared code path with `restore.sh`), compares every table's row count against the source, and drops the scratch DB. Run live against the dev DB: all 9 tables matched (`users` 55, `interaction_logs` 1051, `user_action_logs` 1522, etc.) — a genuine restore, not just a dump that was never opened. `scripts/restore.sh` (the separate, general-purpose restore path) requires an explicit target (`TARGET_DATABASE_URL` or `DOCKER_DB_SERVICE`), with no default, so it can't silently overwrite production; verified live too, restoring into a scratch DB via an explicit target URL. |
| [ ] | **P1** | Docker log rotation | Default `json-file` driver is unbounded. With `LOG_LEVEL=DEBUG` a long exam can fill the 20GB disk and take Postgres down with it. Set `max-size` / `max-file` in compose. |
| [ ] | **P1** | Persist app logs to disk | Logs go to stdout only (`app/utils/logger.py`) and vanish when the container is recreated. Ship to a file on EBS so post-exam triage is possible. |
| [ ] | **P1** | `LOG_LEVEL=INFO` in production `.env` | Currently `DEBUG` in dev `.env`. Must not carry over to EC2. |

**What is already safe:** Postgres named volume survives `restart`, `down`, and EC2 stop/start.
`chroma_db/` (vector store plus `llm_cache.db`, `rag_agent.py:148`) is a bind mount onto EBS and also survives.
Only `docker compose down -v` or instance termination destroys data.

---

## B. Incident response during the exam

**Stated requirement:** if the system fails, it must be possible to restart the exam services, retain all captured data, and have students resume where they left off.

**How close we already are.** Verified against the code, most of this works:

| Failure mode | Current behavior | Status |
|---|---|---|
| Answer submit during outage | Inline "Failed to submit. Please try again.", state unchanged, retry succeeds (`QuizPageContent.tsx:372`) | Works |
| Skip during outage | Same pattern (`QuizPageContent.tsx:403`) | Works |
| Heartbeat during outage | Silently ignored, 25s loop continues (`QuizPageContent.tsx:225`) | Works, student is not ejected |
| Page reload during outage | Init error screen with a retry button (`QuizPageContent.tsx:235-240`) | Recoverable |
| Container crash | `restart: unless-stopped` on all three services | Self-heals |
| Committed data | Every answer, chat message and action log commits per request | Survives |
| Hints and chat history | `localStorage.quizCache_<userId>` | Survives |
| ~~Draft answers~~ | **Corrected by audit.** Only `{hints, chatHistory}` are persisted (`QuizContext.tsx:221-229`); `LOAD_QUIZ` resets drafts to `{}` (`:53`) | **Lost on reload** |

**What breaks resume.** The original version of this document claimed the timer was the only thing.
That was wrong. Audit found three more, all in section 0:

1. The timer, below.
2. **`POST /answer/` is not idempotent**, so an outage-induced retry can permanently lock a question. This is the most likely real-world failure of the resume requirement.
3. **Draft answers are lost** on any reload during an outage.
4. **The 409 takeover path** shows a dead retry loop if a student is moved to another device.

| | Pri | Item | Detail |
|---|---|---|---|
| [x] | **P0** | Bulk timer extension in admin | **Fixed (Stage 2), with a correction to this row's own proposed implementation.** Shifting `exam_start_ms` forward (as originally suggested here) would falsify the recorded exam start time, which is research data; implemented instead as `exam_duration_ms = exam_duration_ms + N minutes`, matching the existing per-student "Adjust Timer" semantics. New `streamlit_app/admin_ops.py` (`extend_all_exam_timers`, `count_active_sessions`) scoped to `submitted_at IS NULL` so already-finished students are untouched; wired into a new "Exam Control" section on the System-Wide Analytics view with an affected-count preview before applying. **This alone would have been cosmetic** — see the new heartbeat-reconciliation row above this table — without also fixing the frontend to actually pick up the change on an open tab. Guarded by `tests/test_admin_bulk_timer.py` and the E2E timer-compensation assertion. |
| [ ] | **P1** | Surface connection loss to the student | Heartbeat failure is swallowed silently, so a student sees nothing wrong until they try to submit. A passive "reconnecting" indicator is calmer than a submit failure appearing out of nowhere. |
| [ ] | **P1** | Graceful LLM failure handling | Billing is on the paid tier so quota is not the ceiling it would have been, but a 429 or Gemini outage should surface as "hint unavailable, try again" rather than a broken UI. |
| [ ] | **P1** | Document expected cold-start delay | `start_period: 120s` on the healthcheck implies RAG singletons (`app/services/rag_agent.py:24-29`) take a while to re-initialize. The first hint after any restart will be slow. Proctors should know this is normal. |
| [ ] | **P2** | Consider a "pause exam" concept | Out of scope for this exam, but the wall-clock timer has no pause. Worth recording as a known limitation. |

**What already works:** `docker compose restart api` loses no interaction data.
Every answer, chat message and action log commits per request.
Alembic re-runs idempotently.
Students survive a browser reload via `localStorage.quizCache_<userId>`.

---

## C. Capacity and performance

| | Pri | Item | Detail |
|---|---|---|---|
| [x] | **P2** | ~~Raise DB pool above 50~~ | **Corrected by audit, demoted from P0. The original premise was wrong.** Both LLM endpoints explicitly release the connection *before* the slow call: `hints.py:54-55` carries the comment "Release the DB connection before the slow LLM call so the pool isn't exhausted", and `chat.py:97-98` does the same. A committed `AsyncSession` returns its connection to the pool, so sessions are held for millisecond queries only, never across a Gemini call. 25 connections is ample for 50 students. Raising it is harmless but blocks nothing. **Raised anyway (Stage 2)** — `app/utils/db.py`'s `pool_size` 10→20, `max_overflow` 15→30 (50 total, up from 25) — free headroom while this stage already owned the file. |
| [ ] | **P0** | Instance size t3.small → t3.medium | t3.small is 2GB. Compose asks for `api` 2g + `nginx` 128m + Postgres + host OS. Oversubscribed. t3.medium is ~$0.04/hr and only runs during exams. |
| [ ] | **P1** | Verify SQLite LLM cache under concurrency | `set_llm_cache(SQLiteCache(...))` is a global sync cache. 50 concurrent writers on one file can raise "database is locked". Never tested at that level. |
| [ ] | **P1** | Confirm Gemini paid-tier rate limits | Billing is enabled, so the ceiling is high, but confirm the actual RPM ceiling for `gemini-2.5-flash-lite` on this project and check it comfortably exceeds peak load. |
| [ ] | **P1** | Measure real cache hit rate before trusting it | See the caching note below. The cache is correctly wired, but its hit rate on this workload is unmeasured and probably low. |

### LLM cache and model, verified state

Caching is correctly configured and requires no changes to switch on:

| Aspect | Status | Evidence |
|---|---|---|
| Cache enabled by default | Yes | `use_llm_cache: bool = True` (`app/utils/config.py:33`), `USE_LLM_CACHE=true` (`.env.docker.example`) |
| Backing store | SQLite at `./chroma_db/llm_cache.db` | `app/services/rag_agent.py:148` |
| Persistence | Survives restarts and EC2 stop/start | `./chroma_db` is a bind mount onto EBS |
| Determinism | `temperature=0` | `app/services/rag_agent.py:163` — identical prompts return identical output, which is what makes caching sound here |
| Test model | `gemini-2.5-flash-lite` | Already set in `.env.docker.example`; code default needs aligning, see section H |

**The caveat worth knowing before relying on it.** LangChain's `SQLiteCache` keys on the exact prompt string plus model parameters.
Hint prompts embed per-user history and BKT mastery, and chat prompts embed the full conversation history.
Both vary per student and per attempt, so **in a real 50-student exam the hit rate will be low**, and caching should not be counted on to reduce exam-day load or cost.

Where it genuinely pays off is repeated identical runs, which is exactly the E2E and load-testing case.
For those to hit cache, tests must use a fixed user with deterministic prior state, otherwise every run re-embeds the varying history and misses.

| | Pri | Item | Detail |
|---|---|---|---|
| [ ] | **P1** | Design E2E fixtures for cache hits | Fixed user IDs with seeded, deterministic interaction history, so repeated test runs hit the cache instead of billing a fresh LLM call each time. |
| [ ] | **P2** | Log cache hit or miss per LLM call | Turns the hit rate from an assumption into a number. Feeds naturally into the observability middleware in section E. |

**Async claim, corrected by audit.** The Gemini call itself is genuinely `await ...ainvoke` (`rag_agent.py:244`, `chat.py:109`), so that part does not block.
But "properly async end to end" was overstated, and two steps in the same request are not:

- **Chroma retrieval** has no native async in `langchain_chroma`, so it falls through to `run_in_executor`, capping concurrency at asyncio's default pool of `min(32, cpu_count+4)` = 6 on a 2-vCPU box, with each slot making a **synchronous** Google embedding HTTP call.
- **The SQLite LLM cache** extends `SQLAlchemyCache`, which overrides neither `alookup` nor `aupdate`, so LangChain's base implementation calls the sync method **directly on the event loop**. Every cache read and write blocks the single worker.

So the single-worker constraint may well be a throughput problem. This needs measuring under load, not assuming.

**Rate limiting, corrected by audit.** The earlier "20r/s burst 50 is comfortable, only 3.3 r/s" was wrong and was the most dangerous sentence in the original document.
It counted only the 15s intervention poll, omitting the 25s heartbeat and the `/log/action` stream.
More importantly the zone is keyed per source IP, so a hall of students behind one NAT shares one bucket. See section 0.

---

## D. Security

| | Pri | Item | Detail |
|---|---|---|---|
| [x] | **P0** | Implement `X-API-Key` middleware | **Fixed (Stage 2).** `app/main.py` now has an `@app.middleware("http")` handler registered *before* `CORSMiddleware` (Starlette applies the last-added middleware outermost, so CORS must end up outermost to attach CORS headers to this middleware's own 401s). Unset `API_KEY` passes every request through unchanged (dev/E2E default); `GET /` and `OPTIONS` preflights are always exempt (compose healthcheck, nginx `/health`, and CORS preflights can't carry custom headers). Compares with `hmac.compare_digest`. Frontend sends `X-API-Key` from `NEXT_PUBLIC_API_KEY` only when that build var is set (`apiClient.ts`). `.env.docker.example` has an `API_KEY` entry now, explicitly labeled obscurity-not-secrecy since `NEXT_PUBLIC_*` vars are readable in any built static bundle. Verified live: 401 with no/wrong header, 200 with the correct header, 200 for `/` and `OPTIONS` regardless. Guarded by `tests/test_api_key.py` (6 cases). |
| [ ] | **P0** | Set `ALLOWED_ORIGIN` to the real CloudFront domain | Currently `*` in both `.env` and `.env.docker.example`. Wiring exists (`app/main.py:75`), only the value is missing. |
| [ ] | **P0** | HTTPS via certbot | `nginx/nginx.conf` is HTTP only. |
| [ ] | **P0** | Fix the commented SSL block placement | The placeholder `server {}` block is nested *inside* the existing `server {}` block. Uncommenting as-is produces an invalid config. It must move to the top level of `http {}`. |
| [ ] | **P1** | Streamlit admin bound to localhost only | Decided: add Streamlit as a compose service bound to `127.0.0.1:8501`, never `0.0.0.0`, reached via `ssh -L 8501:localhost:8501`. Gives compose reproducibility with SSH-grade security. Rejected: public `/admin` behind basic auth, which adds internet-facing attack surface (timer resets, user deletion, manifest access) without removing the need for SSH. |
| [ ] | **P1** | Keep Postgres port unexposed | Compose currently maps no `5432`. Keep it that way. Streamlit reaches the DB over the compose network, not the internet. |
| [ ] | **P1** | Restrict port 22 to a known IP, or use SSM | SSH remains the emergency access path regardless, so it should be locked down rather than open to the world. |
| [ ] | **P0** | Run `/security-review` and `/code-review ultra` **before** the first deploy | Both are code-level reviews and must gate the deploy, never follow it. Sequencing: after the API key middleware lands (otherwise the review certifies a layer that does not exist), and before `terraform apply` puts anything on the public internet. |
| [ ] | **P1** | Post-deploy configuration verification | Distinct from the code review above, and the only part that legitimately happens after deploy, because it can only be tested against running infrastructure: confirm no unexpected open ports, TLS configuration and cert chain are valid, security headers are present, and `ALLOWED_ORIGIN` actually rejects other origins. |

---

## E. Observability and triage

| | Pri | Item | Detail |
|---|---|---|---|
| [ ] | **P1** | Request logging middleware | No correlation ID exists. Nothing links an app log line to a `user_id`. "It broke at 10:42" currently means grepping stdout by timestamp and guessing. One JSON line per request (method, path, status, `duration_ms`, `user_id`, `request_id`) is roughly 40 lines of code and converts triage from guesswork to grep. |
| [ ] | **P1** | Structured (JSON) logging | `app/utils/logger.py` uses a plain-text formatter, so no field queries are possible. |
| [ ] | **P1** | Latency metrics | Cannot currently answer "were hints slow during the exam?" after the fact. Falls out of the middleware above. |
| [ ] | **P2** | Error alerting | An unhandled 500 goes to stdout and nowhere else. Nobody is paged. Acceptable if a proctor is actively watching the dashboard. |

**What already exists, and is genuinely good:** timestamped `user_action_logs` covering `session_start`, `question_view`, `choice_select`, `answer_submit`, `hint_request`, `hint_display`, `hint_feedback`, and all three intervention states (`app/models/user.py:110-134`).
Plus `chat_logs`, `intervention_logs.reason`, and `interaction_logs` with `time_taken_ms`, `hint_text`, `bkt_change`.
Reconstructing any individual student's full timeline from the DB is already possible.
The gap is entirely in *failure* visibility, not in *behavioural* data.

---

## F. Testing and rehearsal

| | Pri | Item | Detail |
|---|---|---|---|
| [x] | **P0** | End-to-end test suite | **Fixed (Stage 1b).** `frontend/e2e/` now has 5 Playwright specs (critical-path, outage-and-resume, second-device-lock, reload-recovery, timer-expiry) exercising the real student path in a real browser, run against a static-export build and a dedicated `aitutor_e2e_db`. `"test:e2e": "playwright test"` in `frontend/package.json`. Backend pytest count is now 64 (was 50). |
| [x] | **P0** | No pytest coverage for `POST /answer/` at all | **Fixed (Stage 1a).** Added `tests/test_answer.py` (12 cases: leak checks, idempotent replay with no duplicate row/double-counted `consecutive_errors`, new-attempt-key creates a genuine second attempt, 3rd-attempt rejection for both answers and skips, per-question not per-skill cap scoping, correct answer not blocked by the wrong-attempt cap, already-correct questions reject further submissions, 404 unaffected) and `tests/test_questions.py`. Full suite: 64/64 passing (up from 50). |
| [x] | **P0** | E2E coverage of the critical path | **Fixed (Stage 1b).** `frontend/e2e/critical-path.spec.ts` covers login → correct → wrong twice (locked) → skip → hint + rating → chat → results; `reload-recovery.spec.ts` covers the mid-exam reload case separately; `timer-expiry.spec.ts` covers expiry. **Scope note preserved:** the UI-driven parts confirm the frontend locks correctly, but `critical-path.spec.ts` also makes a direct API call (bypassing the UI) asserting the server-side attempt cap rejects a 3rd submission independent of what the UI renders — that's the part a pure UI test can't catch. |
| [x] | **P0** | E2E outage-and-resume test | **Fixed (Stage 1b), extended in Stage 2.** `frontend/e2e/outage-and-resume.spec.ts` simulates the outage via Playwright network interception (real request reaches the server and commits, the browser is made to never see the reply) rather than killing a Docker container — running Docker locally is explicitly forbidden by CLAUDE.md's Dev Workflow rule (it corrupts the dev `chroma_db` bind mount). Confirms the student sees a retryable error, the retry is deduped server-side (no false `wrong_2` lock), and drafts survive reload. **Stage 2 addition:** now also confirms timer compensation — a bulk admin extension (`frontend/e2e/fixtures/extend_all_timers.py`) reaches the already-open tab's rendered countdown within one heartbeat, with no reload. Full suite verified green: all 5 specs pass locally (`outage-and-resume` at 28.4s, consistent with the ≤25s heartbeat wait this assertion needs). |
| [x] | **P0** | E2E second-device test | **Fixed (Stage 1b).** `frontend/e2e/second-device-lock.spec.ts` covers both the existing `/login` `active_elsewhere` behavior and the new `/quiz` 409 handling (a proctor moving a student straight to `/quiz` on a second device, bypassing `/login`). |
| [ ] | **P0** | Full dress rehearsal on the real AWS stack | Seed real tokens, run the real flow, watch the real dashboard. Not a staging approximation. |
| [ ] | **P1** | k6 load test that hits Gemini for real | Phase 3.6 specifies 50 VUs. It must make real LLM calls, otherwise it validates nothing about the actual failure mode. Pass criteria: p95 < 5s non-LLM, < 90s for hints and chat. |

---

## G. AWS provisioning and cost control

| | Pri | Item | Detail |
|---|---|---|---|
| [ ] | **P0** | Write the Terraform | No IaC exists. Zero `.tf` files, no `cdk.json`. Phase 3.1 is a blank slate. |
| [ ] | **P0** | AWS Budgets alert | Low threshold, email notification. |
| [ ] | **P1** | Cost Anomaly Detection | Free. |
| [ ] | **P1** | Tag everything `project=aitutor` | Enables cost allocation reporting. |
| [ ] | **P1** | Review every `terraform plan` before apply | The guardrail that actually prevents surprise resources. |

**Services needed:** EC2 (stopped except exams), EBS 20GB gp3 (~$1.60/mo, bills while stopped), Elastic IP, S3, CloudFront (1TB free tier).

**Services to explicitly avoid:** RDS, ALB/NLB, **NAT Gateway** (the classic ~$32/mo surprise; avoid by putting EC2 in a public subnet with an Internet Gateway), ECS/Fargate, WAF, Secrets Manager, CloudWatch custom metrics.

**Elastic IP tradeoff, decided:** an EIP costs ~$0.005/hr while the instance is stopped, about $3.60/mo.
Without it the public IP changes on every start, breaking the DNS A record and the TLS certificate.
Pay the $3.60.

---

## H. Configuration correctness

| | Pri | Item | Detail |
|---|---|---|---|
| [x] | **P1** | `EXAM_DURATION_MS` code default is 20 minutes | **Fixed (Stage 2).** `app/utils/config.py:74`'s fallback changed to `25 * 60 * 1000`, matching `.env.docker.example`'s `EXAM_DURATION_MS=1500000`. A deploy that misses the env var now runs the correct duration instead of 5 minutes short. Guarded by `tests/test_config.py` (source-literal assertion, chosen over asserting the resolved `settings.exam_duration_ms` because that value would already be correct locally via `.env`, masking a regression of the code-level fallback itself). |
| [x] | **P1** | `GOOGLE_MODEL_NAME` code default is a different model | **Fixed (Stage 2).** `app/utils/config.py:48`'s fallback changed to `gemini-2.5-flash-lite`, matching `.env.docker.example`. An unset env var no longer silently switches models or invalidates the LLM cache. Guarded by `tests/test_config.py`. |
| [x] | **P0** | `chroma_db` bind mount ownership | **Fixed.** Replaced the `./chroma_db` bind mount with a named Docker volume (`chroma_data`) in `docker-compose.yml`. A named volume is seeded from the image path, which `Dockerfile:34-35` already chowns to `appuser`, so ownership is correct by construction with nothing to remember in Stage 4 user-data. This is Linux-only breakage — macOS Docker Desktop maps bind-mount ownership to the host user, so it would not have been caught by a local Stage 0 run; it had to be designed out rather than tested out. As a side effect this also removes the dev/Docker `chroma_db` collision noted in section I. |
| [ ] | **P1** | Certificate renewal while EC2 is stopped | Let's Encrypt certs last 90 days and renewal needs port 80 reachable. If the box stays stopped for months the cert expires and renewal fails silently, discovered on exam morning. Boot monthly, or run renewal on startup. |
| [ ] | **P1** | Maintenance state for frontend-up / backend-down | CloudFront serves the frontend permanently while EC2 is stopped, so any visitor gets raw network errors. Decide what they should see instead. |
| [x] | **P1** | Add `./data:/app/data` volume, or confirm unnecessary | **Confirmed unnecessary.** `grep` of `app/` finds `data/questions.csv` and `data/source_material.pdf` only in commented-out dev/eval config lines (`app/utils/config.py:12-13`); the live prod config (`config.py:20-21`) points at `prod/data/...` exclusively. Nothing in the app reads from `/app/data` at runtime. CLAUDE.md's compose sketch updated to drop the stale `./data:/app/data` line and reflect the real mounts (`chroma_data` volume + `./prod/data:/app/prod/data:ro`), so the sketch no longer conflicts with `docker-compose.yml`. |
| [ ] | **P2** | Fix the stub migration comment | `alembic/versions/a9df95bc2767_..._fix_pk_integer_for_action_chat_logs.py` has `pass` in both `upgrade()` and `downgrade()`, which CLAUDE.md explicitly bans. **Verified harmless**: `73cefad687ac` already creates both tables with `sa.Integer()` PKs, so it was a redundant autogenerate. It needs a comment saying so, otherwise it looks exactly like the failure mode the parity rule warns about. |
| [ ] | **P2** | Correct `progress.md:17` | Claims "All Alembic migrations real (no `pass` stubs)". One stub remains, per the row above. |

---

## I. Hygiene and cleanup

| | Pri | Item | Detail |
|---|---|---|---|
| [ ] | **P2** | Stray SQLite files | `aistutor.db` and `aitutor.db` sit unreferenced in the repo root (note the typo variant). Not used by any config. |
| [ ] | **P2** | Stale Chroma directories | `chroma_db_old/` and `chroma_db_old_evaluation/`. |
| [ ] | **P2** | Document the dev/Docker `chroma_db` collision | Dev and the Docker bind mount share `./chroma_db`, so running Docker locally writes into the dev vector store and its LLM cache. This is the concrete reason behind CLAUDE.md's "do not run Docker locally" rule, and it should say so. |

---

## J. Decisions

Resolved:

| Decision | Answer | Consequence |
|---|---|---|
| Exam date | **Not set** | Work to a quality bar, not a deadline. All P0 and P1 are in scope. Certificate auto-renewal matters more, since the box may sit stopped for a long time. |
| EC2 instance | **Fresh, nothing provisioned** | Terraform does a clean create. Size it t3.medium from the start rather than resizing later. |
| Terraform scope | **Everything, including EC2 user-data bootstrap** | A rebuilt instance comes back identical, with Docker installed, repo cloned and certbot run. More upfront work, no exam-morning surprises. |
| Failure contingency | **Restart services, retain data, resume the exam** | Availability failure must be recoverable rather than fatal. This promotes bulk timer extension to a P0 blocker and makes an outage-and-resume E2E test the single most important test to write. |
| Admin access | **Streamlit in compose bound to `127.0.0.1:8501`, reached by SSH tunnel** | SSH-grade security with compose reproducibility. Public `/admin` rejected: it adds internet-facing attack surface without removing the need for SSH. |
| Elastic IP | **Pay the ~$3.60/mo idle cost** | Keeps the DNS A record and TLS certificate stable across stop/start. |
| Gemini tier | **Paid, billing enabled** | Rate limit is not the ceiling it would have been on free tier. Still add 429 handling for outages. |

Still open:

| | Question | Detail |
|---|---|---|
| [ ] | Backup retention | How long exam data must be kept after the exam, and where. Matters more for the research data than the grades. |
| [ ] | Expected concurrent peak | 50 is the planning number. Confirm whether that is simultaneous or staggered arrival, which changes the DB pool and rate limit sizing. |

---

## K. Exam day runbook

Existing draft is in CLAUDE.md Phase 3.7.
It needs these additions before it is trustworthy:

- [ ] EBS snapshot immediately **before** starting the instance
- [ ] Verify certificate expiry date during boot checks
- [ ] Confirm `EXAM_DURATION_MS` reads 25 minutes, not the 20-minute default
- [ ] Smoke test one real token end to end before handing tokens out
- [ ] Note the expected slow first hint (RAG cold start)
- [ ] Keep an SSH session open and a tunnel to the Streamlit dashboard for the duration
- [ ] EBS snapshot and `pg_dump` immediately **after** the exam, before stopping the instance

---

## Summary counts

| Priority | Count | Meaning |
|---|---|---|
| P0 | 28 | Blocks go-live |
| P1 | 31 | Should be fixed before go-live |
| P2 | 11 | Post-exam cleanup |
| **Total actionable** | **70** | Every actionable item carries a priority |

Counts rose from 53 after the audit: six new P0s in section 0, several new P1s, and three demotions where the original premise was wrong.
Three more P0s added afterward: the `POST /answer/` answer-key leak and missing server-side attempt cap (section 0), plus the resulting pytest gap for that endpoint (section F) — found by direct code inspection when asked whether exam-integrity constraints (timer, answer secrecy, attempt limits) had verification coverage anywhere in the plan. The timer checked out as solid; the other two hadn't been caught by the original audit.
One more P0 added during Stage 2: the heartbeat-reconciliation gap in section 0, found while tracing the bulk timer extension back to the resume requirement it exists for — without it, the extension would have been cosmetic for exactly the outage scenario it was built to cover.

Nine further checkboxes deliberately carry no priority, because they are not build work:

- **2 open questions** in section J (backup retention, expected concurrent peak). These need answers, not implementation.
- **7 exam-day runbook steps** in section K. These are executed on the day, not before it.

## Audit record

This document was independently audited against the codebase after its first draft.
Result, so the reliability of each part is known rather than assumed:

| Part of the document | Reliability |
|---|---|
| File and line citations (~40 checked) | ~95% accurate, no fabricated paths |
| Absence claims (6 checked) | 6 of 6 held, including across `streamlit_app/`, `evaluation/`, `prod/` and lockfiles |
| **Reasoning and "what already works" claims** | **Only 2 of 6 survived intact.** Sections B and C both led with a conclusion that did not hold |

The audit's summary judgement is worth keeping in view: this was "a good inventory of *known* work and a poor detector of *unknown* risk", finding nothing that required reasoning across two files, which is exactly where all four exam-integrity and deploy-blocking issues lived.

Treat any future "verified" or "already sound" block in this document as an assertion until someone re-checks it.

**Genuinely verified healthy:** 50/50 backend tests pass, the frontend static export builds (6 pages, not the 9 first reported), committed session and interaction data survives restarts, and behavioural logging coverage is comprehensive.

One caveat on that last point: the `UserActionLog` docstring names are stale.
It documents `intervention_offered/accepted/rejected`, `session_complete` and `timer_expired`, while the app actually emits `intervention_offer/accept/reject`, `session_submit` and `session_expire`.
Anyone writing analysis queries from the docstring gets empty result sets.
