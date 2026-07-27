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
| [ ] | **P0** | **`GET /questions/` serves the answer key** | `app/endpoints/questions.py:11` returns `response_model=List[Question]`, and `Question` includes `correct_answer: str` (`app/models/question.py`). Unauthenticated, and fetched by the frontend at exam start. The TypeScript interface omits the field so nothing renders it, but **it is in the JSON on the wire**. Any student with devtools has every answer before question one. Neither CORS nor the planned API key fixes this, because the real frontend must call the endpoint and a static-export bundle cannot hide a key. Fix: a response model that strips `correct_answer`. |
| [ ] | **P0** | **`POST /answer/` is not idempotent** | `app/endpoints/answer.py:100-113` unconditionally inserts an `InteractionLog`. Axios times out at 90s and the submit catch only says "Failed to submit, please try again". If the server commits but the response is lost (restart, 504, blip), the student retries and a **second attempt is recorded**. State reconstruction then treats `realAttempts.length >= 2` as `wrong_2` (`QuizPageContent.tsx:151-155`), **permanently locking a question the student still had an attempt on**. This sits exactly in the outage path this document calls its headline test. Exam-invalidating. |
| [ ] | **P0** | No `443` mapping or cert volume in compose | `docker-compose.yml:42-45` exposes only `80:80` and mounts only `nginx.conf`. CLAUDE.md's sketch has both `443` and `./certbot:/etc/letsencrypt`; the real file has neither. Without the volume, every `docker compose down` destroys the certificates. |
| [ ] | **P0** | nginx rate limit keyed per source IP | `nginx.conf:13` uses `$binary_remote_addr`. If 50 students sit in one hall behind one NAT egress IP, they share a single 20 r/s bucket. A synchronised exam start (50 students x 3 init calls) blows past `burst=50` and returns **503 on `/session/start`**. The earlier "3.3 r/s, comfortable" analysis was wrong: it omitted the 25s heartbeat and the `/log/action` stream. |
| [ ] | **P1** | `draftAnswers` is not persisted | `QuizContext.tsx:221-229` saves only `{hints, chatHistory}`; `LOAD_QUIZ` resets drafts to `{}` (`:53`). A reload during an outage loses whatever the student had typed. Section B previously claimed the opposite. |
| [ ] | **P1** | 409 takeover unhandled at `/quiz` | `/session/start` raises 409 when another device holds the lock (`session.py:76-80`). `/login` distinguishes this state, but quiz init collapses every failure into "Failed to load quiz" with a Retry that keeps failing for up to 60s. A proctor moving a student to a spare laptop sees a dead retry loop with no explanation. |
| [ ] | **P1** | `LOG_LEVEL` defaults to DEBUG | `config.py:29` is `os.getenv("LOG_LEVEL", "DEBUG")` and `.env.docker.example` **does not set it at all**. A textbook-correct copy of the example runs DEBUG in production, into an unrotated log driver. Same trap class as the two config defaults in section H, applied to the variable that actually fills the disk. |
| [ ] | **P1** | Timeout ladder is inconsistent | Gemini client `timeout=60, max_retries=2` (`rag_agent.py:166-167`) is up to ~180s; nginx allows 120s; axios gives up at 90s. The client quits first while the backend keeps working. Worse, the hint catch is empty (`QuizPageContent.tsx:333`): the spinner stops and **nothing appears, with no message**. This is what fires under load. |
| [ ] | **P1** | No non-destructive per-student repair | Streamlit's only remedies are `reset_user_progress` (wipes interactions) and `delete_user`. With no backup, one mis-click during the exam is unrecoverable. |
| [ ] | **P2** | `GET /users/{user_id}/bkt` is broken | `users.py` calls `get_bkt_mastery` with 3 args; the signature takes 4 (`state_manager.py:49`). Every call 500s. Unused by the frontend, but it proves the 50-test suite has real coverage holes. |
| [ ] | **P2** | Results page never reveals skipped answers | `completed_answers` is populated only for correct or 2+ attempt questions (`state_manager.py:115-128`), but CLAUDE.md says results reveal answers for **all** questions. Spec violation students will notice. |

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

**1a. Localized correctness fixes first:** answer idempotency, draft persistence, 409 handling at `/quiz`, strip `correct_answer` from `GET /questions/`.

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
| [ ] | **P0** | Automated Postgres backup | No backup of any kind exists today. All exam data lives in one `postgres_data` volume on one EBS disk. Add `pg_dump` to S3 on a cron, plus a retention policy. |
| [ ] | **P0** | EBS snapshot before and after each exam | Manual or scripted. Two clicks that make the whole exam recoverable. |
| [ ] | **P0** | Restore drill | A backup that has never been restored is not a backup. Restore into a scratch DB once and confirm row counts. |
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
| [ ] | **P0** | Bulk timer extension in admin | **This is the core blocker for the resume requirement, not just a nice safety valve.** `ms_remaining` is wall-clock (`app/endpoints/session.py:119`), so a 10-minute outage silently costs every student 10 minutes. The only remedy today is per-student "Adjust Timer", which is 50 clicks under pressure. Implementation: apply the existing adjust logic to all active sessions at once by shifting `exam_start_ms` forward by N minutes. No schema change needed. |
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
| [ ] | **P2** | ~~Raise DB pool above 50~~ | **Corrected by audit, demoted from P0. The original premise was wrong.** Both LLM endpoints explicitly release the connection *before* the slow call: `hints.py:54-55` carries the comment "Release the DB connection before the slow LLM call so the pool isn't exhausted", and `chat.py:97-98` does the same. A committed `AsyncSession` returns its connection to the pool, so sessions are held for millisecond queries only, never across a Gemini call. 25 connections is ample for 50 students. Raising it is harmless but blocks nothing. |
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
| [ ] | **P0** | Implement `X-API-Key` middleware | CLAUDE.md's "What's Built" claims this exists. It does not. `app/main.py` has exactly one middleware (`CORSMiddleware`, line 84). Frontend sends only `Content-Type` (`frontend/src/services/apiClient.ts:4-8`). `.env.docker.example` has no `API_KEY` entry. Phase 3.5 would have skipped this as a no-op. |
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
| [ ] | **P0** | End-to-end test suite | **There are zero frontend tests.** No `test` script in `frontend/package.json`, no Playwright, Cypress or Vitest. The 50 passing pytest tests cover backend endpoints only. Nothing has ever exercised the real student path in a real browser. |
| [ ] | **P0** | E2E coverage of the critical path | Token login → session start → correct answer → wrong twice (lock) → skip → hint + rating → chat → **reload mid-exam** (recovery) → timer expiry → results page. |
| [ ] | **P0** | E2E outage-and-resume test | **The headline test, given the stated contingency requirement.** Start an exam, kill the API container mid-question, confirm the student sees a retryable error rather than being ejected, restart the API, confirm the student resumes with all prior answers intact, then confirm the timer was compensated. This is the only way to verify the resume requirement actually holds. |
| [ ] | **P0** | E2E second-device test | Confirm the `active_elsewhere` session lock behaves as designed. |
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
| [ ] | **P1** | `EXAM_DURATION_MS` code default is 20 minutes | **Corrected finding.** `.env.docker.example` *does* set `EXAM_DURATION_MS=1500000`, which is exactly 25 minutes, so a correct deploy is fine. The risk is narrower than first reported: the fallback in `app/utils/config.py:74` is 20 minutes, so any deploy that misses the env var silently runs a 5-minute-short exam. Align the code default to 25 minutes so the trap cannot fire. |
| [ ] | **P1** | `GOOGLE_MODEL_NAME` code default is a different model | `.env.docker.example` correctly sets `gemini-2.5-flash-lite`, but the fallback in `app/utils/config.py:48` is `gemini-1.5-flash-latest`. If the env var is ever unset, the system silently runs a different model, which also invalidates every entry in the LLM cache. Align the default. |
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
| P0 | 24 | Blocks go-live |
| P1 | 31 | Should be fixed before go-live |
| P2 | 11 | Post-exam cleanup |
| **Total actionable** | **66** | Every actionable item carries a priority |

Counts rose from 53 after the audit: six new P0s in section 0, several new P1s, and three demotions where the original premise was wrong.

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
