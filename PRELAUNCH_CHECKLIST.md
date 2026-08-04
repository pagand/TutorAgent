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

**Five rows added 2026-08-03, at the top, and they are the most serious in the document.**
They were found while answering a direct question about what an outsider could do to the deployed system, and three of them were reproduced against a running instance rather than inferred.
The common thread is that every prior control (this checklist, two `/security-review` passes, and the Stage 3 authorization work) was reasoning about *student versus student*, and none of them asked what someone holding **no token at all** could do.
The answer is: create an account, start an exam, download the paper, and use the tutor as an unmetered LLM.
They are recorded here rather than fixed in place because they now own their own stage (4.5) in the execution sequence above.

| | Pri | Item | Detail |
|---|---|---|---|
| [x] | **P0** | **The exam token is not required to use the API at all: anyone on the internet can create an account and use it** | **Found 2026-08-03, reproduced live against a running instance. Fixed (Stage 4.5).** `POST /users/` calls `get_user_or_create` (`app/state_manager.py:16-37`), which creates a `User` row for *any* string, with no check that a matching `Participant` exists. `POST /session/start` then succeeds (its concurrent-device guard is inside `if participant:`, so a participant-less id skips it entirely), and from that point `verify_session_owner` is a **no-op** for that identity by explicit design (`app/utils/authz.py:38-40`: "No-op when user_id has no Participant row"). Reproduced end to end: `POST /users/ {"user_id":"attacker-1785782983"}` → 200; `POST /session/start` → 200 with a live 25-minute exam clock; `POST /chat/` → 200 with a real Gemini-generated tutor response. **Fixed** by `settings.require_participant_token` (default `true`): `POST /users/` now 403s any `user_id` with no `Participant` row before it ever creates a `User`, and `verify_session_owner`'s participant-less exemption is now conditional on the same flag (`app/utils/authz.py`), rather than unconditional. The flag defaults off only inside `tests/conftest.py`'s shared fixture, so the ~40 pre-existing tests using ad-hoc ids keep working without seeding Participant rows; the gate itself is proven with the flag forced on in `tests/test_participant_gate.py`. Re-reproduced live against `.venv` uvicorn with the flag on: all four calls from the original finding (`/users/`, `/session/start`, `/questions/`, `/chat/`) now return 403 for the same attacker id, and `/hints/` too. **Why every prior control missed it:** the row three below (now also fixed) records this exemption as one of "two deliberate exemptions", the item was marked `[x]` fixed, and `/security-review` passed over it twice, because the threat model everyone (including the reviews) was working to was *student-versus-student* (can token A act as token B), never *outsider-versus-system* (what about someone holding no token at all). This is exactly the failure mode the audit record at the bottom of this document warns about: "a good inventory of *known* work and a poor detector of *unknown* risk." |
| [x] | **P0** | **No ceiling on LLM spend: the only limit is a per-IP network rate limit calibrated 44x too high** | **Found 2026-08-03. Fixed (Stage 4.5).** `nginx/available/plain.conf` and `tls.conf` capped `/hints|chat/` at `5r/s` per source IP. That is a *network* control and cannot see `user_id`, so it bounded nothing per-account and nothing globally. Arithmetic at `gemini-2.5-flash-lite` ($0.10/M in, $0.40/M out) and this document's own ~3,000-in/250-out per-call working, so $0.0004/call: a **fully maxed-out legitimate exam** (50 students × 22 hints + 44 chat turns each = 3,300 calls) costs **$1.32**. What the old rate limit permitted from **one IP**: $3.00 per 25-minute window, **$57.60 over an 8-hour exam day**, $172.80 over 24h. **Fixed** with an in-app cap where `user_id` is actually visible: `app/services/llm_quota.py`'s `reserve_llm_call`, a rolling-24h count against `LLM_MAX_CALLS_PER_USER_PER_DAY=150` ($0.06/user, 2.3x the legitimate 66-call maximum) and `LLM_MAX_CALLS_PER_DAY=10000` ($4.00/day global ceiling, 3x a full exam), backed by a new `llm_usage_log` table. Reserved *before* the LLM call runs, so a call that then fails still counts. Wired into both `/hints/` and `/chat/` immediately before the existing release-commit. With nginx no longer the last line of defense against cost, its zones were resized up for capacity instead (`api` 50→100r/s, `llm` 5→20r/s) so a synchronised 50-student hall start isn't itself throttled. Proven by test (`tests/test_llm_quota.py`: per-user trips at exactly the limit and not below it, global trips independently of per-user, a reservation survives even when nothing after it runs, stale rows outside the 24h window don't count) and live against real Gemini calls (`LLM_MAX_CALLS_PER_USER_PER_DAY=1`, 1st hint 200, 2nd 429 with a specific "reached the maximum" detail). A Streamlit panel (System-Wide Analytics → LLM Usage) shows the rolling 24h global count and top consumers, so the cap is operable during an exam, not just a silent tripwire; raising it mid-exam is an `.env` edit + `docker compose up -d api`, no data loss. |
| [x] | **P0** | **`GET /questions/` serves the entire exam paper to anyone, with no token** | **Found 2026-08-03. Fixed (Stage 4.5).** Distinct from the answer-key row below, which was already fixed. `PublicQuestion` correctly strips `correct_answer`, but `GET /questions/` had **no authorization of any kind** (`app/endpoints/questions.py:20`, confirmed by AST scan of every route) and was reachable by anyone the instant the box was up. All questions, full text, all multiple-choice options, and the `skill` label, were downloadable before the exam opened. **Fixed** by gating both `GET /questions/` and `GET /questions/{n}` behind `verify_session_owner(allow_if_completed=True)`, matching every other student endpoint — now requires a `user_id` (and, mid-exam, a matching `session_id`) query param. Frontend's `getQuestions` now sends `session_id`; both call sites (`QuizPageContent.tsx`, `results/page.tsx`) already had it in scope. Proven by test (`tests/test_questions.py`: rejects a non-manifest id, rejects a mismatched `session_id`, accepts a matching one, 422 with no `user_id` at all) and by the full E2E suite (all 6 specs green, including the new `session_id` param on every `/questions/` call). |
| [x] | **P1** | **`POST /participants/login` is an unauthenticated name-disclosure oracle** | Returns `404 {"detail":"Invalid token"}` for an unknown token and `200` carrying the participant's real `name` and `group` for a valid one (`app/endpoints/participants.py:44-51`), with no rate limit beyond the shared `api` zone. **Brute force is not the risk and was checked:** tokens are 8 chars from a 31-symbol alphabet via `secrets.choice` (`prod/generate_tokens.py:38-40`) = 8.5×10¹¹ keyspace; with ~50 live tokens a 1% hit chance needs ~1.7×10⁸ guesses. The real issue is narrower: anyone who obtains or shoulder-surfs a single token can confirm it and learn the student's name, and the endpoint deliberately creates no DB rows so nothing is logged. **Decided (Stage 4.5):** keep `name` in the response — it's the login screen's "Welcome, <name>" pre-exam confirmation that the student typed the right token, genuine UX value — and close the gap two other ways instead: a dedicated `login` nginx zone (`1r/s` burst 10, `location = /participants/login`, both `plain.conf` and `tls.conf`) tight enough to blunt enumeration while leaving room for a normal student's retries, and a `logger.warning` on every invalid-token probe (`app/endpoints/participants.py`) so the endpoint's previously-silent 404 path now leaves a trace. |
| [x] | **P2** | `/docs`, `/redoc`, `/openapi.json` exposure depends entirely on `API_KEY` being set | **Fixed (Stage 4.5).** `app/main.py:78` disables all three when `settings.api_key` is truthy, which is the intended production posture and is wired by `scripts/ec2-bootstrap.sh`. The coupling was emergent rather than asserted. **Fixed** with an explicit boot-time assertion in `app/main.py`'s `lifespan`, gated on `APP_ENV=production` (set by `scripts/ec2-bootstrap.sh`, absent in local `.venv` dev so it can't false-positive there): raises `RuntimeError` unless `API_KEY` is set, `ALLOWED_ORIGIN != "*"`, and `REQUIRE_PARTICIPANT_TOKEN` is on — a misconfigured box now fails loudly at boot instead of silently serving a weaker posture. |
| [x] | **P0** | **`alembic/` is not in git** | **Fixed.** `alembic/` and `alembic.ini` are now tracked (`.gitignore:25`'s `alembic*` line removed). `alembic.ini`'s personal dev DSN was neutralised to a placeholder; `alembic/env.py` now calls `load_dotenv()` so local `.venv` runs still resolve the real `DATABASE_URL` from `.env`. |
| [x] | **P0** | **`prod/data/` is not in git** | **Fixed, by design choice rather than by tracking it.** `prod/data/` stays gitignored (answer key + participant tokens should never enter git history) and is now also excluded via `.dockerignore` so it can never be baked into an image layer. It arrives only through the existing read-only bind mount, copied out-of-band (`scp`) as a documented deploy step in `README.md` and CLAUDE.md 3.3. **Corrected finding:** the original "sys.exit(1), second crash loop" claim was wrong — `question_service.load_questions` only logs on `FileNotFoundError` (`app/services/question_service.py:72-73`) and `ingest_pdf` returns early on a missing PDF (`app/services/pdf_ingestion.py:20-22`); the API boots healthy and silently serves an empty quiz. Closed instead with a fail-fast guard in `app/main.py`'s `lifespan`: raises `RuntimeError` if zero questions load, converting the silent failure into a loud boot failure. |
| [x] | **P0** | **`GET /questions/` serves the answer key** | **Fixed (Stage 1a).** Added `PublicQuestion` (`app/models/question.py`) — same shape minus `correct_answer` — and switched both `questions.py` endpoints to build it via explicit field construction (robust against the test fixture's mocked question object too, not just real `Question` instances). `correct_answer` is now absent from `GET /questions/` and `GET /questions/{n}` on the wire, verified by `tests/test_questions.py` and a live network-response check during manual smoke testing. |
| [x] | **P0** | **`POST /answer/` is not idempotent** | **Fixed (Stage 1a).** Added `attempt_key` (client-generated, stable across retries of the same submission, rotated on a genuinely new attempt) to `AnswerRequest` and a matching `attempt_key` column + unique index `(user_id, question_id, attempt_key)` on `InteractionLog` (migration `f3a1c9d47b2e`). `submit_answer` now checks for an existing row with the same key first and returns the already-committed outcome with zero mutation on a replay, before doing anything else. Locked in by `tests/test_answer.py` (exact-one-row + no-double-counting assertions) and the `outage-and-resume` E2E spec (`frontend/e2e/outage-and-resume.spec.ts`), which reproduces "server commits, browser never sees the reply" via network interception and confirms the retry does not falsely produce `wrong_2`. |
| [x] | **P0** | **`POST /answer/` leaks `correct_answer` on every response** | **Fixed (Stage 1a).** Removed `correct_answer` from `AnswerResponse` entirely. Frontend no longer reads `result.correct_answer` (`QuizPageContent.tsx`'s `SUBMIT_RESULT` dispatch dropped the field); `saveAndRedirect` now sources the results-page answer key from `GET /users/{id}/profile`'s `completed_answers` instead, matching the pattern already used by the reload-recovery path and `results/page.tsx`'s slow path. Verified with no `correct_answer` key on any `/answer/` response, live and in `tests/test_answer.py`. |
| [x] | **P0** | **No server-side cap on wrong attempts** | **Fixed (Stage 1a), with a correction to this row's own proposed fix.** `consecutive_errors >= 2` (as originally suggested here) is the wrong condition — it lives on `SkillMastery`, scoped per `(user_id, skill)`, not per question, so using it would lock a student out of a fresh question the moment a *different* question sharing the same skill had two wrong attempts. Implemented instead: count real `InteractionLog` rows (`user_answer IS NOT NULL`) for the exact `(user_id, question_id)`; reject (`409`) a 3rd submission — answer or skip — once 2 exist with none correct. Covered by `tests/test_answer.py` (including a dedicated test proving the cap is per-question, not per-skill) and `critical-path.spec.ts`'s direct-API assertion that a 3rd attempt is rejected independent of the UI. |
| [x] | **P0** | No `443` mapping or cert volume in compose | **Fixed (Stage 3).** `docker-compose.yml`'s `nginx` service now maps `443:443` and mounts `./certbot:/etc/letsencrypt`. The cert itself still needs Stage 5's certbot run against real DNS; this closes the compose-side blocker that would have destroyed it on every `docker compose down` once one exists. |
| [x] | **P0** | nginx rate limit keyed per source IP | **Fixed (Stage 3), with a correction: splitting the zone, not just raising it.** `nginx.conf` now has two zones - `api` (raised from `rate=20r/s burst=50` to `rate=50r/s burst=200`, covering session/timer/logging/answer/questions) and a new `llm` zone (`rate=5r/s burst=20`) applied only to `/hints/` and `/chat/` via a dedicated `location ~ ^/(hints|chat)/` block. Splitting matters because the expensive LLM routes previously shared the same bucket as cheap traffic - a hint/chat burst could starve session/heartbeat calls, and conversely had no cap of their own at all. Both zones stay keyed on `$binary_remote_addr` - correct for this architecture since the recorded decision explicitly rejects an ALB/NLB in front of the API (only the frontend goes through CloudFront), so there is no proxy between nginx and the client to obscure the real IP. |
| [x] | **P1** | `draftAnswers` is not persisted | **Fixed (Stage 1a).** `draftAnswers` now included in the `quizCache_<userId>` payload alongside `hints`/`chatHistory`; `LOAD_QUIZ` seeds drafts from the cache instead of resetting to `{}`. Verified live (type a partial answer, reload, text survives) and by `outage-and-resume.spec.ts` / `reload-recovery.spec.ts`. |
| [x] | **P1** | 409 takeover unhandled at `/quiz` | **Fixed (Stage 1a).** `init()`'s catch block now checks `err.response?.status === 409` and shows a specific "This exam token is now active on another device." message with a "Back to login" link, instead of a Retry button that reloads into the same 409. Deliberately routes back to `/login`'s existing `active_elsewhere` state machine rather than duplicating its copy. Verified live (device A holds the lock, device B loads `/quiz` directly) and by `second-device-lock.spec.ts`. |
| [x] | **P1** | `LOG_LEVEL` defaults to DEBUG | **Fixed (Stage 2).** `config.py:29`'s fallback changed to `os.getenv("LOG_LEVEL", "INFO")`, and `.env.docker.example` now sets `LOG_LEVEL=INFO` explicitly. Same trap class as the two config defaults in section H, applied to the variable that actually fills the disk. Guarded by `tests/test_config.py` (source-literal assertion, since local dev's `.env` deliberately sets `DEBUG` and would otherwise mask a regression of the code-level fallback). |
| [x] | **P1** | Timeout ladder is inconsistent | **Fixed (Stage 3).** Gemini client tightened from `timeout=60, max_retries=2` (~180s worst case) to `timeout=30, max_retries=1` (~60s worst case) - `rag_agent.py`. Now strictly under both nginx's 120s `proxy_read_timeout` and axios's 90s client timeout, so the client no longer gives up while the backend (and the billed Gemini call) keep running. The empty hint catch is also fixed: `handleRequestHint` now sets a `hintError` state and renders it inline, with a friendlier "temporarily unavailable" message specifically for 429/5xx responses (`QuizPageContent.tsx`, mirrored in `ChatPanel.tsx` for chat). |
| [ ] | **P1** | No non-destructive per-student repair | Streamlit's only remedies are `reset_user_progress` (wipes interactions) and `delete_user`. With no backup, one mis-click during the exam is unrecoverable. |
| [x] | **P2** | `GET /users/{user_id}/bkt` is broken | **Fixed (Stage 3).** `users.py`'s call site corrected to `get_bkt_mastery(db, user_id, skill, default)`, matching `state_manager.py:49`'s real signature. Still unused by the frontend, but it was touched anyway while gating it with `verify_session_owner` (see the new row below), and a dedicated regression test (`tests/test_authz.py::test_bkt_endpoint_returns_200_not_500`) now locks in the 200. |
| [ ] | **P2** | Results page never reveals skipped answers | `completed_answers` is populated only for correct or 2+ attempt questions (`state_manager.py:115-128`), but CLAUDE.md says results reveal answers for **all** questions. Spec violation students will notice. Assessed during Stage 3 and deliberately left out of that stage's scope, it's a correctness/spec gap, not a security finding, and no later stage in the execution sequence owns it either. Still needs a home before go-live. |
| [x] | **P0** | **`POST /session/start` crashes on a concurrent-request race** | **Found and fixed during Stage 1b.** Two near-simultaneous `/session/start` calls for the same never-before-started user (e.g. a double-click, a retried request after a network blip, or — how this was actually caught — React StrictMode's dev-mode double effect invocation racing two `init()` calls) hit `ExamSession`'s unique constraint, entering the existing `except IntegrityError: await db.rollback()` recovery path. That path re-fetched `exam_session` but not `participant`, which had been loaded earlier in the same now-rolled-back transaction; mutating the stale `participant` object further down crashed with `sqlalchemy.exc.MissingGreenlet` on commit, 500ing the request outright — the exact class of failure the outage-and-resume requirement is supposed to survive, just triggered by a race instead of a network outage. Fixed by re-fetching `participant` inside the `except IntegrityError` branch too (`app/endpoints/session.py`). **No regression guard exists for this fix.** It has no dedicated pytest case (reliably reproducing the race requires real concurrency, not the shared-session pytest fixture) and, despite an earlier version of this note claiming otherwise, no E2E coverage either — `playwright.config.ts` deliberately serves the static export rather than `next dev` specifically *to avoid* React StrictMode's double-effect invocation, which is what originally surfaced this bug, so the E2E suite structurally cannot reproduce it. If this regresses, only a real concurrent-load test (e.g. Stage 6's k6 run, or a manual double-click test) would catch it. |
| [x] | **P0** | **A bulk timer extension would never reach an already-open `/quiz` tab** | **Found and fixed during Stage 2**, while tracing the bulk-extension deliverable back to the resume requirement it exists for. `POST /session/heartbeat` already returned `ms_remaining`, but `QuizPageContent.tsx` discarded it — the countdown ran purely off `examStartMs`/`examDurationMs` captured once at init (`TimerBar.tsx`). An admin bulk extension changes only the DB row; an open tab would still hit its stale zero, `handleTimerExpire` would fire `submitSession`, and the participant would be marked `completed` — locking the student out of the exact exam the extension existed to save. Fixed by having `HeartbeatResponse` also return `exam_start_ms`/`exam_duration_ms`, and dispatching a new `SYNC_TIMER` action from the existing 25s heartbeat poll whenever either value changes (`app/endpoints/session.py`, `QuizContext.tsx`, `QuizPageContent.tsx`). Guarded by `tests/test_session.py::test_heartbeat_reflects_bulk_timer_extension` (server side) and `frontend/e2e/outage-and-resume.spec.ts`'s new timer-compensation assertion (full chain: admin action → DB → heartbeat → reducer → rendered countdown, no reload). |
| [x] | **P0** | **No authorization anywhere - any token holder can act as any other student** | **Found and fixed during Stage 3.** Every endpoint carrying a `user_id` took it verbatim from the request body/path with no check that the caller owned it. The recorded decision ("no auth system, user ID is the only identifier, acceptable for exam scope") covered reads; it did not cover destructive cross-student writes. Concretely, one token was enough to: `DELETE` another student's exam, force-`/session/submit` them into a permanent lockout, `/session/logout` them to steal their device lock, `/session/start` to burn their clock before they logged in, or read any student's full `interaction_history` and `completed_answers` (real correct-answer strings) via `GET /users/{id}/profile`. Fixed with `app/utils/authz.py`'s `verify_session_owner` - every such endpoint now checks the caller's `session_id` against `Participant.active_session_id`, the device lock `POST /session/start` already claims. Two deliberate exemptions: participant-less (ad-hoc/dev/test) `user_id`s no-op, since there's no lock to enforce for identities the manifest never issued a token for; and profile/bkt/remaining reads exempt a *completed* participant from the session_id check (`allow_if_completed=True`), so a student can view their own results from a different device after finishing (`/results`'s documented slow path) - this does not reopen the original problem for in-progress exams, only for exams that are already over, matching the accepted "token is the sole credential" baseline. `DELETE /users/{id}` removed outright (zero consumers, verified). Guarded by `tests/test_authz.py` (8 cases) and new assertions in `second-device-lock.spec.ts` (403 on a forged `session_id`) and a new `results-cross-device.spec.ts` spec (the completed-exam cross-device case actually renders, not silently blank). |
| [x] | **P0** | **`POST /users/` leaked any participant's full exam data with zero access control** | **Found by an independent `/security-review` pass, and fixed, during Stage 3** - after the row above landed, not before. `create_user` returned `get_user_profile_with_session`'s full payload (`interaction_history`, `completed_answers`, `skill_mastery`) for *any* `user_id`, gated by nothing, because this endpoint runs before `POST /session/start` claims the device lock the row above's fix depends on - gating it the same way would have 403'd every legitimate login instead of closing anything. A token alone (the same login-page `createUser(token)` call every real student makes) was enough to read another student's live in-progress exam state, including revealed correct answers for any question they'd locked or gotten right. Fixed by having `create_user` return only `{user_id, created_at, preferences}` rather than delegating to the full-profile helper at all - `preferences` is the one field the frontend's free_choice hint-style UI actually needs at creation time, and holds nothing more sensitive than an A/B group and a hint-style setting. Guarded by `tests/test_authz.py::test_create_user_does_not_leak_another_participants_exam_data`. Re-reviewed clean by a second `/security-review` pass after the fix. |

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

- `/security-review`, user-triggered
- **Gate:** all blocking findings fixed
- Rationale: reviewing code that is already serving the public internet is backwards. The API key middleware must land first (stage 2) so the review assesses the real security posture.

**Widened during execution.** The stage turned out to own more than "run a review": exploration ahead of the review surfaced that the backend had no authorization at all (any token holder could act as any other student), which the recorded review alone wouldn't have caught without code already being changed first. Actual scope: row-level access control (`app/utils/authz.py`), exposure hardening (hint debug fields, server-sourced chat history, `SecretStr`, input bounds), the section 0/D deploy-config items with no other stage owner (SSL block placement, 443/cert volume, nginx rate-limit split, Streamlit compose service, log rotation, `.dockerignore`/`.gitignore` tightening), and the timeout-ladder/silent-failure items from section 0/B, then the review against the real (now-hardened) diff. `/security-review` ran twice and found one further High finding (`POST /users/`, see section 0) between the two passes. **Gate closed.**

### Stage 4 — Infrastructure
Terraform, full scope including EC2 user-data bootstrap, per the recorded decision.

- t3.medium, budgets, cost tags, Elastic IP, S3, CloudFront, no NAT Gateway
- **Gate:** `terraform plan` reviewed, clean apply, and a `destroy` plus re-apply reproduces the box identically
- **`terraform/` written and `terraform plan` reviewed line-by-line against the signed-off manifest (Artifact `d23447ec`): 36 resources, matches exactly, no drift.** Three deltas from that manifest approved this session: root EBS 30GB → 20GB (measured estimate + 100% headroom, -$0.80/mo), 2GB swap file (closes the open question from 2026-08-02), 90-day backup retention (closes the open question in section J below). Cost Anomaly Detection also added (closes the P1 two rows down). New idle floor: **$5.66/mo** (was $6.46). Full reasoning in `/Users/pedram/.claude/plans/complete-stage-5-of-snuggly-bear.md`. **Apply not yet run** - gated on a separate go-ahead per this stage's own rule.

### Stage 4.5, Access control, cost ceiling, and closed-state UX — DONE

**Inserted 2026-08-03, blocked Stage 5, and is now closed.**
Stage 4 built the infrastructure to put this app on the public internet, and doing so surfaced that the app is not safe to *be* on the public internet.
Three of these are section 0 P0s found by reproducing an attack against a running instance; the fourth is the maintenance-state item promoted to P0 in section H.

None of this is infrastructure work, so it does not belong in Stage 4, and all of it must be true *before* anything is reachable, so it cannot wait for Stage 5.

- [x] **Require a manifest token.** `POST /users/` rejects any `user_id` with no `Participant` row when `settings.require_participant_token` is on (production default). `verify_session_owner`'s participant-less exemption is now conditional on the same flag rather than unconditional — off only in `tests/conftest.py`'s shared fixture, so ad-hoc-identity tests keep working without seeding Participant rows.
- [x] **Gate `GET /questions/`** behind the same session ownership check as every other student endpoint (`allow_if_completed=True`), so the paper is not downloadable before the exam.
- [x] **Cap LLM spend in the application**, where `user_id` is visible and nginx's per-IP zone is not: `LLM_MAX_CALLS_PER_USER_PER_DAY=150` and `LLM_MAX_CALLS_PER_DAY=10000`, rolling 24h, sized off the $1.32 full-exam figure in section 0. New `llm_usage_log` table, `app/services/llm_quota.py`, wired into `/hints/` and `/chat/`, visible in Streamlit.
- [x] **Ship the closed-state screen** so the frontend, which is up 24/7 at $0, says the exam is closed instead of showing a server error. Self-toggling: `/login` probes `GET /` on mount, a failed probe *is* the closed state — no build flag or status file to keep in sync with the actual backend.
- [x] **Set the UX latency budget** (p50 < 6s, p95 < 15s for hints/chat, 90s kept as the hard timeout) **and time the RAG cold start**: measured at 2.00s against the real source doc and Google embedding API — not the risk the original wording implied, no warming step needed.

Also closed while the code was open for this stage, since they share the same threat model and files: the `/participants/login` name-oracle P1 (dedicated nginx rate zone + invalid-token logging, name kept per recorded decision) and the `/docs`/`/redoc` P2 boot-assertion coupling. One Terraform addition riding along at $0: a CloudFront response-headers policy on the frontend distribution (HSTS, content-type/frame options, referrer policy, CSP), matching the security headers nginx already sets for the API.

- **Gate — passed.** The section 0 reproduction was re-run live against `.venv` uvicorn with the flag on: `POST /users/`, `/session/start`, `GET /questions/`, `/chat/`, `/hints/` all reject the same non-manifest attacker id that previously succeeded end to end. The per-user and global LLM caps are proven by test (`tests/test_llm_quota.py`) and live against real Gemini calls. Full backend suite (108 tests, up from 91) and all 6 Playwright E2E specs green.

### Stage 5 — Deploy and verify
- Deploy, then post-deploy configuration verification (open ports, TLS, headers, CORS enforcement)
- **Gate:** verification clean
- **Architecture changed mid-stage, 2026-08-04.** The original plan (two domains, `api.air.da-tu.ca` on its own cert via certbot) was replaced with D1: the API moved behind the same CloudFront distribution as the frontend, at `/api/*`. Driver was F1 — certbot's renewal path checked a host path it never wrote to, so HTTPS never actually came up even after a successful issuance. Rather than fix a renewal path that had never once worked, it was deleted (D2), along with both EventBridge cert-renewal schedules and `api.air.da-tu.ca` itself (D4). The CloudFront-to-origin hop is plaintext by explicit tradeoff (D3, recorded verbatim in `docs/OPS_RUNBOOK.html` §1). Full reasoning in `~/.claude/plans/do-the-stage-5-velvety-duckling.md`.
- **Both registrar records now needed are in a single message**, sent this stage: the ACM validation CNAME (unchanged) and a CNAME for `air.da-tu.ca` pointing at the CloudFront distribution's default domain (created via `enable_custom_domain = false`, so the distribution exists and serves on `d2u3k75qofedmd.cloudfront.net` without waiting on DNS). The previously-sent `api.air.da-tu.ca` A-record request was explicitly withdrawn. Once the registrar publishes both, flipping `enable_custom_domain = true` and re-applying attaches the real domain and ACM cert — a distribution update, not a rebuild.
- **The full V1-V10 verification gate passed** against the CloudFront default domain, with no need to wait on the registrar: prefix routing and stripping across every endpoint, cache isolation (no caching on `/api/*`, confirmed via `x-cache: Miss` on every request), real client-IP rate limiting (nginx correctly resolves the true client through `X-Forwarded-For`, not a CloudFront edge IP — this is what makes the per-IP zones mean anything with an edge in front), the origin genuinely unreachable except from CloudFront's published ranges, auth/cookie posture, and the 502/504 debugging matrix (both a transient CloudFront-level timeout and a fast nginx-level 502 observed live by deliberately stopping the `api` container and, separately, the whole instance).
- **Found and fixed live, unrelated to the CloudFront migration:** `LLM_PROVIDER` was never set in production (see section H) — every deployed hint and chat call had been trying to reach a nonexistent local Ollama server. Predates this stage entirely; caught only because chat was tested against a real deployed box for the first time.
- Closed a real gap found earlier in this stage: nothing seeded the `participants` table on a fresh box. Added `prod/seed_participants.py` (upsert-only, never touches `status`/`active_session_id`/`started_at`/`last_seen_at` on an existing row, so a mid-exam re-seed is safe), wired into `scripts/ec2-bootstrap.sh` after the healthcheck passes. New `scripts/update-prod-data.sh` gives a ~10s no-reboot participant refresh path.
- First-boot validation found and fixed three real bugs, all now on `main`: two SIGPIPE-under-pipefail cases (a `curl | grep -m1 | cut` in the buildx-install block of `user_data.sh.tftpl`, and a `crontab -l | grep -v` on a fresh user with no crontab in `ec2-bootstrap.sh`), and a `.dockerignore` gap that let root-owned `certbot/` state break every `docker compose build` after the first cert attempt (moot now that certbot is deleted, but the leftover `certbot/` directory from an earlier session's real attempt had to be manually cleaned off this box once, during this stage's own re-bootstrap).
- **A structural gotcha found and documented, not fully fixed:** `ec2-bootstrap.sh`'s first action rewrites its own source file (`git reset --hard`), so an already-running invocation finishes executing its stale in-memory copy — any code change to this script needs the systemd unit triggered twice to actually take effect (or a full instance reboot). Hit twice live this stage. See `docs/OPS_RUNBOOK.html` §2.
- Instance stopped between every verification session, per standing operational rule — never left running once a session's testing is done.
- Still open: the DNS-dependent tail (attach alias + ACM cert once the registrar responds, re-run V1-V5 over the real domain), F5 (version pinning, deliberately deferred), and Stage 6's rehearsal/load test.

### Stage 6 — Rehearsal
- Full dress rehearsal with real tokens, plus k6 at 50 VUs against real Gemini
- **Gate:** p95 targets met (< 5s non-LLM, < 90s for hints and chat), and the outage-and-resume test passes against the real stack

### Stage 7 — Operations runbook
- `docs/OPS_RUNBOOK.html`: a self-contained, internal-only HTML runbook covering the system map, start/stop, health checks, code-promotion path (with costed CI/CD recommendations, not implemented), prod data updates, log retrieval, monitoring, incident response, what Streamlit can/cannot do, the exam-day sequence, and a prioritized recommendations list.
- Documentation and recommendations only — no CI/CD implemented, no application code changed.
- **Gate:** every command in it traces to a real file in this repo; every Streamlit claim checked against `streamlit_app/app.py`.

---

## A. Data safety and recovery

| | Pri | Item | Detail |
|---|---|---|---|
| [x] | **P0** | Automated Postgres backup | **Fixed (Stage 2).** `scripts/backup.sh` runs `pg_dump -Fc` to a timestamped file, prunes past `BACKUP_RETENTION_DAYS` (default 14), and uploads to `BACKUP_S3_URI` when that var is set — unset until Stage 4 creates the bucket, so dumps stay local under `BACKUP_DIR` until then. Works both against a directly-reachable `DATABASE_URL` (local dev) and via `docker compose exec` (`DOCKER_DB_SERVICE=db`, since 5432 stays unexposed on EC2 by design). Verified against the real dev DB: a live 96K dump of all 9 tables. Cron line documented in `README.md` and referenced from `SKILL.md` §3.3 for Stage 4's bootstrap to install. |
| [x] | **P0** | F2 — nightly backups were writing to a bucket the instance couldn't write to | **Found and fixed, Stage 5.** Once Stage 4 created buckets, `ec2-bootstrap.sh` set `BACKUP_S3_URI=s3://${OPS_BUCKET}/backups` — but `terraform/iam.tf`'s instance role only ever granted `s3:PutObject` on `aitutor-backups-<account>`, a *separate* bucket; the ops-bucket statement was read-only. Every nightly `aws s3 cp` got AccessDenied, `backup.sh` exited non-zero under `set -e`, and the failure landed only in `backups/cron.log`, which nothing monitors. **The system would have believed it had off-box backups and had none.** Fixed by pointing `BACKUP_S3_URI` at the correct bucket (`aitutor-backups-$(aws sts get-caller-identity --query Account --output text)`), derived at boot rather than threaded through `user_data.sh.tftpl` (which would force a full instance replacement on every edit). Also corrected the working assumption that the nightly cron is meaningful coverage at all — see `docs/OPS_RUNBOOK.html` §5b: it only runs while the instance runs, and this box is stopped between exams by design, so a single-day exam very likely never fires it. The real protection is a dump taken immediately before stopping the box (§10 exam-day runbook, step 8). |
| [x] | **P1** | F3 — the instance role could write backups but never read them back | **Found and fixed, Stage 5.** The IAM statement was `PutObject` only — no `GetObject`, no `ListBucket` on the backups bucket, so nothing on the box could pull a dump down; no restore path existed at all despite backups (once F2 was also fixed) actually landing. Fixed in `terraform/iam.tf`: renamed to `ReadWriteBackups` (`PutObject` + `GetObject`) plus a separate `ListBackups` statement scoped to the bucket ARN. |
| [ ] | **P0** | EBS snapshot before and after each exam | Manual or scripted. Two clicks that make the whole exam recoverable. Deferred to section K's exam-day runbook — no EC2 instance exists yet to snapshot. |
| [x] | **P0** | Restore drill | **Fixed (Stage 2).** `scripts/restore_drill.sh` creates a scratch DB, calls `pg_restore` directly to restore the newest dump into it (own `psql`/`pg_restore` calls, not a shared code path with `restore.sh`), compares every table's row count against the source, and drops the scratch DB. Run live against the dev DB: all 9 tables matched (`users` 55, `interaction_logs` 1051, `user_action_logs` 1522, etc.) — a genuine restore, not just a dump that was never opened. `scripts/restore.sh` (the separate, general-purpose restore path) requires an explicit target (`TARGET_DATABASE_URL` or `DOCKER_DB_SERVICE`), with no default, so it can't silently overwrite production; verified live too, restoring into a scratch DB via an explicit target URL. |
| [x] | **P1** | Docker log rotation | **Already fixed, found stale while correcting this section's EBS size (Stage 5).** `docker-compose.yml`'s `x-logging` anchor caps every service at `max-size: "10m"`, `max-file: "3"` (10MB × 3 = 30MB per service, ~120MB total across `db`/`api`/`nginx`/`streamlit`) — far short of filling the 30GB root disk even under sustained `LOG_LEVEL=DEBUG`. |
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
| [x] | **P0** | Instance size t3.small → t3.medium | **Already closed, per F6 in the Stage 5 handoff plan** — `terraform.tfvars`'s `instance_type = "t3.medium"` was set during Stage 4 and never regressed. Verified live during Stage 5: `aws ec2 describe-instances --instance-ids i-0b0d93da111a1e907 --query 'Reservations[].Instances[].InstanceType'` returns `t3.medium`. |
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

### Perceived performance and UX, added 2026-08-03

The existing pass criteria (`p95 < 5s` non-LLM, `< 90s` for hints and chat) are **survivability thresholds, not UX targets**, and nothing in this document has ever set the latter.
In a 25-minute exam a 90-second hint consumes **6% of the student's total time** while they sit looking at a spinner, and a student who requests three slow hints loses nearly a fifth of the exam to waiting.
That is a grading-fairness problem as much as a UX one, because the time cost is invisible in the results and falls unevenly on the students who most need help.

| | Pri | Item | Detail |
|---|---|---|---|
| [x] | **P0** | Set a real UX latency budget, separate from the survivability threshold | **Decided (Stage 4.5).** **p50 < 6s and p95 < 15s** for hints and chat, with the existing 90s kept only as the hard timeout before an error is shown. **Single-user, uncached latency measured live against real Gemini** to sanity-check the budget before committing to it: 3 hints (varied `user_answer` per call so each hit a fresh, non-cached prompt) at 1.12s / 0.76s / 0.87s, 3 chat turns (varied message) at 0.80s / 0.67s / 0.84s — all comfortably inside the budget with room to spare. **What this does NOT prove:** these are one request at a time, locally, with no concurrent load and no network hop through nginx/CloudFront. The number that actually matters — p95 under 50 simultaneous students — is still unmeasured and is Stage 6's k6 run to answer, not this one. |
| [x] | **P0** | Measure and fix RAG cold start on the first hint | **Measured (Stage 4.5), and it's a non-issue — but note what this number is and isn't.** `ingest_pdf()` + `ensure_rag_components_initialized()` run exactly **once**, in `app/main.py`'s `lifespan`, when the container/uvicorn process boots — not per request and not per student. It's the one-time cost of `aws ec2 start-instances` on exam morning, amortized across every student and every hint/chat call that follows, not a per-user latency. Ran it against a scratch `chroma_persist_dir` with the real Google embedding API and the real `prod/data/source.pdf` (7 pages → 21 chunks), simulating a fresh-EBS first boot. **Total: 2.00s** (`ingest_pdf` 1.95s, RAG init 0.06s) — the source document is small enough that this was never going to be the bottleneck the original wording implied. No warming step needed in the runbook. Per-request hint/chat latency (the number that actually affects each student, every time they ask for help) is the row above, not this one. |
| [ ] | **P1** | Decide what the student sees during a slow LLM call | There is a spinner, but no progress signal, no elapsed indicator, and no "this can take up to a minute" reassurance. At 90s the student cannot distinguish *working* from *broken*, and the natural response is to retry, which doubles the load precisely when the system is already slow. |
| [ ] | **P1** | Confirm the single worker holds 50 concurrent students | The two blocking paths documented immediately above (Chroma retrieval capped at a 6-slot executor with synchronous embedding HTTP calls, and the SQLite cache calling sync `lookup`/`update` directly on the event loop) mean the single mandatory worker is a plausible throughput ceiling. This is the specific thing Stage 6's k6 run plus `docker stats` exists to answer, and it should be treated as a real risk rather than a formality. |
| [ ] | **P1** | Frontend performance budget and first-paint check | The static export is 1.3 MB served from CloudFront, which should be fast, but no LCP/TTI number has ever been captured and no budget is set. Worth one Lighthouse run against the real CloudFront domain before go-live, particularly on a mid-range phone over campus wifi rather than a laptop on ethernet. |
| [ ] | **P2** | Verify CloudFront cache behaviour for the export | `CachingOptimized` is attached (`terraform/frontend.tf`) and the CloudFront Function rewrites directory paths, but cache-hit ratio and the invalidation flow after a redeploy are unverified. A stale `index.html` served to a student mid-exam-window is a real failure mode. |

---

## D. Security

| | Pri | Item | Detail |
|---|---|---|---|
| [x] | **P0** | Implement `X-API-Key` middleware | **Fixed (Stage 2).** `app/main.py` now has an `@app.middleware("http")` handler registered *before* `CORSMiddleware` (Starlette applies the last-added middleware outermost, so CORS must end up outermost to attach CORS headers to this middleware's own 401s). Unset `API_KEY` passes every request through unchanged (dev/E2E default); `GET /` and `OPTIONS` preflights are always exempt (compose healthcheck, nginx `/health`, and CORS preflights can't carry custom headers). Compares with `hmac.compare_digest`. Frontend sends `X-API-Key` from `NEXT_PUBLIC_API_KEY` only when that build var is set (`apiClient.ts`). `.env.docker.example` has an `API_KEY` entry now, explicitly labeled obscurity-not-secrecy since `NEXT_PUBLIC_*` vars are readable in any built static bundle. Verified live: 401 with no/wrong header, 200 with the correct header, 200 for `/` and `OPTIONS` regardless. Guarded by `tests/test_api_key.py` (6 cases). |
| [x] | **P0** | Set `ALLOWED_ORIGIN` to the real CloudFront domain | **Already closed, per F6 in the Stage 5 handoff plan** — `scripts/ec2-bootstrap.sh` writes `ALLOWED_ORIGIN=https://${DOMAIN_FRONTEND}` (i.e. `https://air.da-tu.ca`) into `.env` on every boot. Verified live: `docker compose exec api env \| grep ALLOWED_ORIGIN` on the deployed box returns the real domain, not `*`. Stage 5 made this largely moot anyway — the API now lives on the same CloudFront distribution as the frontend (`/api/*`), so real browser traffic is same-origin and never triggers CORS at all; this remains as defense-in-depth for any direct cross-origin caller. |
| [x] | **P0** | HTTPS via certbot | **Resolved by deletion, not by fixing certbot (Stage 5, D1/D2).** Investigating this row surfaced F1 (below): certbot's renewal path checked a host path (`/etc/letsencrypt/live/...`) that certbot never actually wrote to on the host — only inside the container — so HTTPS never came up even after a successful issuance, and every boot silently re-ran `certonly` from scratch. Rather than fix a renewal path that had never once worked, the API moved behind the existing CloudFront distribution as `/api/*` (D1): TLS now terminates at CloudFront using its own default or ACM-validated certificate, certbot and both nginx server-block variants (`plain.conf`/`tls.conf`) are deleted entirely, and `api.air.da-tu.ca` no longer exists. The CloudFront-to-origin hop is plaintext by explicit, recorded tradeoff (D3) — see `docs/OPS_RUNBOOK.html` §1. Verified live over `https://d2u3k75qofedmd.cloudfront.net` (V1-V10 in the Stage 5 plan, all passed). |
| [x] | **P0** | Fix the commented SSL block placement | **Fixed (Stage 3).** Moved to the top level of `http {}`, a sibling of the `:80` server block rather than nested inside it. Verified with `nginx -t` against a scratch copy with the block uncommented and a throwaway self-signed cert - syntax valid. Also picked up security headers (HSTS, `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`) and `server_tokens off` while the file was open, both inside the SSL block and (headers only, HSTS excluded) on the plain-`:80` block that serves today. |
| [x] | **P2** | Frontend (CloudFront) had no security headers at all | **Found and fixed (Stage 4.5).** nginx sets HSTS/content-type/frame/referrer headers for the API (row above), but the static frontend distribution had none. Added `aws_cloudfront_response_headers_policy` in `terraform/frontend.tf`, attached via `response_headers_policy_id` on the default cache behavior: same header set as the API plus a CSP scoped to `connect-src 'self' https://{domain_api}` (the static export talks to nothing else). Cost: $0, one added resource (36 → 37 against the Stage 4 signed-off manifest). `terraform fmt` and `terraform validate` clean; not yet in a `terraform plan` diff since no AWS credentials were available in this session — do that before the next apply. |
| [x] | **P1** | Streamlit admin bound to localhost only | **Fixed (Stage 3).** Added as a compose service, `ports: ["127.0.0.1:8501:8501"]` - the container itself still binds `0.0.0.0:8501` internally (required for Docker's port-forward to reach it at all), but the *host* only accepts connections to that forwarded port from its own loopback, so nothing external can reach it regardless of container-internal binding. Reached via `ssh -L 8501:localhost:8501`, per the recorded decision. Talks to Postgres directly over the compose network (`streamlit_app/app.py`), never through the API, so none of Stage 3's new API-level row-level access control applies to it or needs to - it's the trusted admin path by construction. |
| [x] | **P1** | Keep Postgres port unexposed | **Confirmed unaffected.** Compose still maps no `5432`; the new `streamlit` service reaches `db` over the compose network like `api` does, not the internet. |
| [x] | **P1** | Restrict port 22 to a known IP, or use SSM | **Fixed (Stage 4).** `terraform/network.tf`'s `aws_security_group.app` allows only 80 and 443 inbound; port 22 is absent entirely. Shell access is SSM Session Manager only (`aws ssm start-session`), via the instance role's `AmazonSSMManagedInstanceCore` attachment (`terraform/iam.tf`). |
| [x] | **P0** | Run `/security-review` **before** the first deploy | **Done (Stage 3), twice.** First pass found one High finding (see the `POST /users/` row in section 0); fixed, then a second pass over the full updated diff plus a separate non-diff-scoped pass over files the diff-scoped tool couldn't see (Dockerfile, `streamlit_app/`, `alembic/`, `prod/generate_tokens.py`) both came back clean. |
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
| [x] | **P0** | End-to-end test suite | **Fixed (Stage 1b), extended in Stage 3 and Stage 4.5.** `frontend/e2e/` has 6 Playwright specs (critical-path, outage-and-resume, second-device-lock, reload-recovery, timer-expiry, and Stage 3's `results-cross-device`) exercising the real student path in a real browser, run against a static-export build and a dedicated `aitutor_e2e_db`, verified green against Stage 4.5's changes with no spec modifications needed (the suite already seeds real `Participant` tokens, so it runs at the production `require_participant_token` posture unmodified). `"test:e2e": "playwright test"` in `frontend/package.json`. Backend pytest count is now 108 (was 50 at Stage 1, 64 after Stage 1b, 91 after Stage 2/3, +17 in Stage 4.5 for the manifest gate, LLM quota, and questions gating). |
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
| [x] | **P0** | Write the Terraform | **Fixed (Stage 4).** `terraform/` holds the full root module: network, compute, iam, frontend, backups, guardrails, outputs. `terraform validate` clean, `terraform plan` reviewed and matches the signed-off 36-resource manifest exactly. |
| [x] | **P0** | AWS Budgets alert | **Fixed (Stage 4).** `terraform/guardrails.tf`'s `aws_budgets_budget.monthly`: $15/mo threshold, email at 80% actual and 100% forecast. |
| [x] | **P1** | Cost Anomaly Detection | **Fixed (Stage 4).** `aws_ce_anomaly_monitor` + `aws_ce_anomaly_subscription` in `terraform/guardrails.tf`, daily email. Added as a delta from the original signed-off manifest (was scoped out, is free), approved this session. |
| [x] | **P1** | Tag everything `project=aitutor` | **Fixed (Stage 4).** `default_tags` on both AWS providers in `terraform/main.tf` sets `Project=AITutorApp` and `CostCenter=exam` account-wide, no per-resource tagging needed. |
| [x] | **P1** | Review every `terraform plan` before apply | **Process, not code.** `terraform plan` was reviewed resource-by-resource against the signed-off manifest before this stage's apply gate opened; the same review happens before every future apply. |
| [x] | **P1** | F4 — the Elastic IP had no destroy guard | **Found and fixed, Stage 5.** `aws_eip.api` had no `lifecycle` block — one untargeted `terraform destroy` would have released the address permanently, and re-obtaining it means redoing the registrar handshake. Fixed with `lifecycle { prevent_destroy = true }` (`terraform/compute.tf`). The EIP's role changed this stage too: it's no longer a registrar-facing DNS target (that record was withdrawn, D4), it's CloudFront's `/api/*` origin address, and it has to stay stable across every stop/start of a box that's deliberately stopped between exams. |
| [ ] | **P1** | F5 — nothing is version-pinned, so a rebuild is not reproducible | **Explicitly deferred, Stage 5** (see the Stage 5 plan's "out of scope" section). Five independently floating layers: the AMI (`most_recent = true`, already bit once — its 30GB root snapshot forced `root_volume_gb` up from the planned 20GB), `repo_ref = "main"` rather than a tagged commit, Python deps on range constraints with no lockfile (`chromadb`'s on-disk index format is the specific risk — a version bump can make an archived `chroma_data` volume fail to load), floating base image tags (`python:3.11-slim`, `postgres:16-alpine`, `nginx:alpine`), and — moot since Stage 5 deleted certbot — its `:latest` tag. Deliberately left open: fixing it now would mean editing `terraform/templates/user_data.sh.tftpl`, and any edit there forces a full instance replacement (`user_data_replace_on_change = true`), which is exactly the kind of unnecessary risk this stage was trying to avoid while other changes were still landing. |

**Services needed:** EC2 (stopped except exams), EBS **30GB** gp3 (~$2.40/mo, bills while stopped — the AMI's own root snapshot needs 30GB, see the F5 row above and the Stage 4/5 AMI-drift note in `docs/OPS_RUNBOOK.html` §11), Elastic IP, S3, CloudFront (1TB free tier).

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
| [x] | **P0** | `LLM_PROVIDER` code default is `ollama`, not `google` — and production never set it | **Found and fixed live, Stage 5, the most serious config-default gap in this section.** `.env.docker.example` documents `LLM_PROVIDER=google` as required, but `scripts/ec2-bootstrap.sh`'s `.env` render never wrote it — this is a different bug class than the `EXAM_DURATION_MS`/`GOOGLE_MODEL_NAME` rows above, whose code-level fallbacks were already corrected to safe values; here the fallback (`ollama`, `app/utils/config.py:37`) is actively wrong for production, since nothing named `localhost:11434` exists on the box. Every deployed hint and chat call was trying to reach a nonexistent local Ollama server. **Not a Stage 5 regression** — this predates the CloudFront migration entirely and would have shipped to real students, caught only because this stage tested `/chat/` against a real deployed box for the first time. Two different failure shapes masked it: `hints.py`'s own try/except silently degrades to a canned `"..."`/`hint_style: "error"` fallback rather than erroring, so hints looked like they were "working" (200 OK) while producing no real AI content; `chat.py` has no such fallback and hard-fails, which is what actually surfaced this live (a chat call through CloudFront hung to a 504, and the same call against the origin directly returned the Ollama connection-refused traceback). Fixed by adding `LLM_PROVIDER=google` to the `.env` heredoc. Re-verified live post-fix: chat returns a real contextual response in 1.14s, hints return a genuine `hint_style: "Analogy"` (etc.) response in 1.23s, both through CloudFront. **Not yet guarded by a boot-time assertion** — see the recommendation in `docs/OPS_RUNBOOK.html` §11 to add one alongside the existing `APP_ENV=production` check in `app/main.py`'s `lifespan`. |
| [x] | **P0** | `chroma_db` bind mount ownership | **Fixed.** Replaced the `./chroma_db` bind mount with a named Docker volume (`chroma_data`) in `docker-compose.yml`. A named volume is seeded from the image path, which `Dockerfile:34-35` already chowns to `appuser`, so ownership is correct by construction with nothing to remember in Stage 4 user-data. This is Linux-only breakage — macOS Docker Desktop maps bind-mount ownership to the host user, so it would not have been caught by a local Stage 0 run; it had to be designed out rather than tested out. As a side effect this also removes the dev/Docker `chroma_db` collision noted in section I. |
| [x] | **P1** | Certificate renewal while EC2 is stopped | **Superseded, Stage 5 — the mechanism this row describes no longer exists, and the problem it solved is gone too.** Stage 4's fix (`aws_scheduler_schedule.monthly_start`/`monthly_stop` booting the box monthly for certbot renewal) is deleted along with certbot and both EventBridge schedules (D1/D2). Investigating this exact renewal path surfaced F1: it checked a host filesystem path certbot never actually wrote to, so HTTPS never came up even after a successful issuance — the "fix" this row originally recorded had never once worked. TLS now terminates at CloudFront, which manages its own certificate lifecycle; there is nothing left on the EC2 side to renew. |
| [x] | **P0** | Maintenance state for frontend-up / backend-down | **Promoted P1 → P0 on 2026-08-03. Fixed (Stage 4.5).** CloudFront serves the frontend permanently and at $0 (1.3 MB is far inside the always-free tier, and it is *not* part of the $5.66/mo idle floor, which is entirely Elastic IP + EBS), so the site is reachable 24/7 while the backend is stopped between exams, which is most of the year. Previously the student typed their token and got a red inline `"Could not reach the server. Please try again."`, reading as *the app is broken* rather than *the exam is closed*. **Fixed** with a self-toggling closed-state screen rather than a build flag: `/login` probes `GET /` on mount (that route is already exempt from both the API-key middleware and CORS credentials) and shows a quiet "Checking exam status…" state, then either the normal token form or a dedicated "The exam is not currently open" screen with a "Check again" button. A failed probe *is* the closed state by construction — nothing to keep in sync with the actual backend across a rebuild/redeploy. Verified live (stop the backend, load `/login`, closed screen renders; start it, "Check again" recovers) and by the full E2E suite passing unmodified (the probe resolves to "open" against a live backend in well under Playwright's default timeout). |
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

Resolved (Stage 4):

| Decision | Answer | Consequence |
|---|---|---|
| Backup retention | **90 days**, in the Terraform-managed backup bucket (`terraform/backups.tf`) | `scripts/backup.sh`'s `BACKUP_S3_URI` now has a real target with a lifecycle rule; dumps expire automatically rather than accumulating forever. |
| Swap file | **Yes, 2GB** on the root volume | Was the one open question from 2026-08-02, answered this session. With `mem_limit` set and `memswap_limit` unset, a transient memory spike degrades instead of OOM-killing a container mid-exam. Counted into the 20GB root volume sizing. |

Still open:

| | Question | Detail |
|---|---|---|
| [ ] | Expected concurrent peak | 50 is the planning number. Confirm whether that is simultaneous or staggered arrival, which changes the DB pool and rate limit sizing. **Now also blocks Stage 4.5's cap sizing**, the per-user and global LLM limits have to be set above the true legitimate peak, and a synchronised 50-student start is a different number from staggered arrival. |
| [ ] | Number of participants per exam | Confirm the real cohort size. `prod/data/participants.csv` currently holds 3 rows (dev), and the dev DB has 3 participants; every cost and capacity figure in this document assumes 50. |

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

Recounted mechanically on 2026-08-03, after Stage 4.5 (parsed from the tables, not tallied by hand):

| Priority | Open | Done | Total | Meaning |
|---|---|---|---|---|
| P0 | **2** | 37 | 39 | Blocks go-live |
| P1 | **19** | 18 | 37 | Should be fixed before go-live |
| P2 | **10** | 4 | 14 | Post-exam cleanup |
| **Total actionable** | **31** | **59** | **90** | Every actionable item carries a priority |

**Updated 2026-08-04, Stage 5.** Three of the five previously-open P0s closed this stage: the t3.small→t3.medium resize and `ALLOWED_ORIGIN` were already done in the repo and just needed verification-with-evidence (F6 in the Stage 5 handoff plan); HTTPS via certbot closed by deletion rather than by fixing it (D1/D2 — investigating it surfaced F1, the reason certbot never worked). One new P0 found and fixed live during this stage's own verification and unrelated to the CloudFront migration itself: `LLM_PROVIDER` was never set in production, silently breaking hints and chat via the wrong code-default provider (`ollama`) — see section H. Four more findings from the Stage 5 handoff plan's own defect list (F2-F5): F2 (nightly backups writing to a bucket the instance couldn't write to) and F3 (no read-back path once they did) both fixed in section A; F4 (Elastic IP had no destroy guard) fixed in section G; F5 (nothing is version-pinned) deliberately deferred, recorded as open in section G. **The 2 remaining open P0s** — EBS snapshot cadence and the full dress rehearsal — are the only ones left, and both are runbook/rehearsal items, not application security or infrastructure gaps; neither can be closed by more code.

Counts rose from 53 after the audit: six new P0s in section 0, several new P1s, and three demotions where the original premise was wrong.
Three more P0s added afterward: the `POST /answer/` answer-key leak and missing server-side attempt cap (section 0), plus the resulting pytest gap for that endpoint (section F) — found by direct code inspection when asked whether exam-integrity constraints (timer, answer secrecy, attempt limits) had verification coverage anywhere in the plan. The timer checked out as solid; the other two hadn't been caught by the original audit.
One more P0 added during Stage 2: the heartbeat-reconciliation gap in section 0, found while tracing the bulk timer extension back to the resume requirement it exists for — without it, the extension would have been cosmetic for exactly the outage scenario it was built to cover.
Two more P0s added during Stage 3, both in section 0: the complete absence of authorization across the student API, and, found only after fixing that, `POST /users/` still leaking any participant's full exam data via a path the first fix couldn't cover without breaking every login. Both are now fixed; the count records that they existed, not that they're still open.

**Five more added 2026-08-03, after Stage 4** (three P0, one P1, one P2 in section 0), plus the section H maintenance-state item promoted P1 → P0 and two new P0s in section C for perceived performance. These came from asking what an *outsider* could do to the deployed system, which is a question this document had never posed. The Stage 3 authorization work, recorded two paragraphs up as fixed, is genuinely fixed for the threat it was scoped to (student versus student) and left the front door open, because a participant-less identity has no lock to check and was therefore exempted by design. Counted honestly: the previous total of 72 understated the work, and the P0 count going *up* this late is the finding, not a bookkeeping detail.

**All of Stage 4.5's block is now fixed** (2026-08-03, same day): manifest-token gate, `GET /questions/` gating, in-app LLM spend cap, closed-state screen, UX latency budget decided, RAG cold start measured and found negligible. Two riders closed alongside it (`/participants/login` name-oracle rate limiting, the `/docs` boot-assertion coupling) plus one new $0 Terraform addition (CloudFront response headers), which is why the P2 total rose from 13 to 14 rather than only losing an open row. 17 new backend tests (91 → 108); the full Playwright E2E suite passes unmodified, since it already runs at the production `require_participant_token` posture.

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
