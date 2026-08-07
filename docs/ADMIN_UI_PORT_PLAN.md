# Plan: replace the Streamlit admin dashboard with a stateless FastAPI admin UI

Status: **not started.** Written 2026-08-07 after diagnosing why the Streamlit dashboard is unusable.
Hand this file to an implementer as-is.

---

## Why Streamlit is being retired

Measured on the live box on 2026-08-07. Everything except Streamlit is clean:

| Layer | Measured | Verdict |
|---|---|---|
| Postgres | full user-detail query set = 62 ms | fine |
| SSM tunnel | 640 KB/s throughput, 21 ms RTT | fine |
| nginx | websocket probe with nginx bypassed behaves identically | fine |
| Postgres locks | 0 locks, 0 blocked queries during a hang | fine |
| Streamlit | see below | broken |

The decisive observation: while the UI showed "running", the Streamlit process sat at **0.34% CPU** with
Postgres idle.
The server was not slow, it was doing nothing, and the browser was waiting on a reply that never came.

Two distinct failures were reproduced:

1. **Permanent session wedge.** The page goes blank with the "Stop" indicator live, and a full browser
   refresh does *not* recover it.
   Only `docker compose restart streamlit` clears it.
   During an exam this means the admin console can become permanently useless until someone opens an SSM
   session to the box.
2. **Silent death loop.** The container died 5 times in 12 minutes (07:44, 07:47, 07:49, 07:51, 07:53),
   every death correlated with the dashboard actually being used, and every death with no traceback in the
   container log.
   No traceback rules out a Python exception and points at a signal.
   Streamlit holds a live session per browser *connection*, not per user, so a dropped websocket reconnects
   into a new session while the old one is still held; that walks memory into the cgroup cap, the kill drops
   every websocket at once, and the storm restarts.

Both are consequences of the same architectural choice: a stateful, websocket-only, rerun-the-whole-script
UI with no HTTP fallback and no recovery path.
That is the wrong shape for exam-day operations, and it is not worth tuning.

### Already fixed (deployed, commit 19d4e96)

- `streamlit` `mem_limit` raised 384m to 1g. It idled at 223 MB against the old cap, leaving no room to
  absorb a reconnect storm. Host has ~2.9 GB spare.
- `ecs-agent` crash loop stopped. `amazon/amazon-ecs-agent` was exiting 1 and restarting every ~17 seconds,
  forever, because this box runs plain Docker Compose and was never an ECS cluster member.
  Disabled with `systemctl disable --now ecs`. Reversible with `systemctl enable --now ecs`.

These reduce the chance of death. **They do not fix the wedge.** The wedge is why this port exists.

---

## Security model (decided)

The SSM tunnel is the authentication boundary. There is no login form and no admin password, deliberately:
access is gated by AWS IAM plus SSM, which is stronger than a shared secret and leaves no credential to leak
in a bundle. A password would only add a second, weaker credential in front of the same door.

- Admin lives at `/admin` on the **existing FastAPI app**. Never under `/api/`, so the CloudFront
  origin-secret path cannot reach it.
- Published only on `127.0.0.1:8501` via nginx, reachable solely through the existing
  `aws ssm start-session ... portNumber=8501,localPortNumber=8501` command. That command does not change.
- The nginx `listen 80` block (the CloudFront origin) gets an explicit `location /admin { return 404; }` as
  defense in depth, so the surface can never be served externally even if a `location /` is added there later.
- `/admin` is exempt from `api_key_middleware` in `app/main.py`, because it is unreachable except on the
  loopback-published port. This is the same trust model the Streamlit dashboard already had.

---

## Architecture (decided, do not redesign)

Serve the admin UI from the existing FastAPI app.
No new service, no new container, no Node, no new runtime, no new port.
The API is already running and stable, already owns the models and the async DB session, and a second
service would cost memory and money on a t3 box.

The replacement must be **stateless**: plain HTTP request/response, no websocket, no server-held session.
Any page must be fully recoverable with a browser refresh. That property is the entire point.

### Integration facts

- Async DB session dependency: `get_db()` in `app/utils/db.py`, yields `AsyncSession`. The app is asyncpg
  and async throughout.
- `streamlit_app/queries.py` and `streamlit_app/admin_ops.py` are **sync** (psycopg2 + pandas). The SQL must
  be **ported to async** SQLAlchemy returning plain dicts and lists.
  Do not introduce pandas into the API path and do not call sync psycopg2 from the async app; either would
  block the event loop.
- Existing router/`Depends(get_db)` style: see `app/endpoints/action_log.py`.

### Existing importers that must keep working

- `tests/test_admin_bulk_timer.py` imports `count_active_sessions`, `extend_all_exam_timers`
- `frontend/e2e/fixtures/extend_all_timers.py` imports `EXTEND_ALL_TIMERS_SQL`

`EXTEND_ALL_TIMERS_SQL` stays a single source of truth shared with the e2e fixture. Move it to the new
module and update both importers.

---

## Phases

### Phase 1, async admin data layer

New package `app/admin/` with `queries.py`. Port every query from `streamlit_app/queries.py` and
`streamlit_app/admin_ops.py` to async, returning plain dicts and lists:

`get_all_user_ids`, `get_all_users_summary`, `get_user_profile`, `get_user_kpis`, `get_skill_mastery`,
`get_skill_mastery_trajectory`, `get_interaction_history`, `get_raw_interaction_history`,
`get_all_interaction_logs`, `get_chat_logs`, `get_intervention_logs`, `get_action_logs`,
`get_exam_session_info`, `get_participant_info`, `reset_user_progress`, `delete_user`,
`update_user_preferences`, `reset_exam_timer`, `extend_exam_timer`, `clear_session_lock`,
`count_active_sessions`, `extend_all_exam_timers`, `get_llm_usage_last_24h`, plus whatever `QUESTIONS_DF`
provided (prefer `app.services.question_service` over re-reading the CSV).

Preserve the exact SQL semantics. Do not improve the queries.

### Phase 2, admin UI router

New `app/endpoints/admin_ui.py`, `APIRouter(prefix="/admin")`, returning `HTMLResponse`.
No template engine unless one is already in requirements; a module of functions returning HTML strings is
fine and preferred.
Escape every interpolated value with `html.escape` - tokens, chat text, hint text and answers are all
untrusted enough to break the page.

Styling: one inline `<style>` block. No external CSS, JS or fonts of any kind (strict CSP, and the box is
reached over a tunnel). Match the design language in CLAUDE.md: `slate-900` primary, `indigo-600` accent,
`slate-50` background, `emerald-500` correct, `rose-500` wrong, `amber-400` skipped.
Dense and academic. It has to look right, not merely work.

Routes, at full parity with Streamlit:

- `GET /admin/` system overview: total users, adaptive vs free_choice counts, total interactions, A/B
  distribution, hint style breakdown, the full all-users summary table (`user_id`, `ab_group`,
  `participant_status`, `hint_style_pref`, `created_at`, `total_interactions`, correctness, `hints_used`,
  `chat_messages`, `remaining_min`, `submitted`), Exam Control (unsubmitted count plus bulk extend form),
  and LLM usage last 24h (global count, headroom against `settings.llm_max_calls_per_day`, top 10 consumers).
  Each `user_id` links to its detail page.
- `GET /admin/user/{user_id}` renders every section on one page, no round-trip tabs (use `<details>` or
  plain sections): KPIs, raw profile JSON, skill mastery and trajectory, interaction history, hints and
  interventions grouped by question, chat log, action log with an `action_type` filter as a GET query param,
  intervention events, exam session and participant info, and the admin action forms.
- `GET /admin/export` form; `GET|POST /admin/export/download` CSV via `StreamingResponse` and the stdlib
  `csv` module. Same filters Streamlit had: user scope, log type (Interaction/Chat/Intervention/Action),
  date from/to, action type, hint-only, correct/incorrect, and column selection.
- Actions, all POST, all POST-Redirect-GET (303) back to the page with a `?msg=` flash, so a refresh never
  re-submits: `POST /admin/user/{id}/prefs`, `/timer/reset`, `/timer/extend`, `/session-lock/clear`,
  `/progress/reset`, `/delete`, and `POST /admin/exam/extend-all`.
- Charts: server-generated inline SVG, simple bar and line. If a chart exceeds ~40 lines of code, render a
  table instead. Do not build a charting library.

Destructive actions (`/progress/reset`, `/delete`) must require typing the exact user token into a confirm
field and reject a mismatch.
Streamlit had no confirmation at all and `docs/OPS_RUNBOOK.html` explicitly flags that as a risk; this
closes it.

Auto-refresh on `GET /admin/` only: emit `<meta http-equiv="refresh" content="10">` when `?refresh=10` is
present, with plain links to toggle it. No JS.

### Phase 3, exposure and wiring

- Include the router in `app/main.py`.
- Exempt paths starting with `/admin` from `api_key_middleware`, with a comment explaining the loopback-only
  reachability.
- `nginx/available/app.conf`: in the `listen 8501` block, replace the Streamlit proxying with a proxy to
  `$api_upstream` rewriting `/` to `/admin/`; drop the websocket and `/static/` handling that existed only
  for Streamlit. Add `location /admin { return 404; }` to the `listen 80` block.
- `nginx/nginx.conf`: remove `$streamlit_upstream` and `$connection_upgrade` only if nothing else uses them.
- `docker-compose.yml`: remove the `streamlit` service. Keep nginx's `127.0.0.1:8501:8501` mapping so the
  tunnel command is unchanged. Ensure nginx `depends_on` api.
- Remove `streamlit` from requirements if nothing else needs it.

### Phase 4, retire Streamlit

Only after Phases 1-3 pass. Delete `streamlit_app/`, repoint `tests/test_admin_bulk_timer.py` and
`frontend/e2e/fixtures/extend_all_timers.py` at the new module, update `README.md`, and update the
Streamlit-specific operating instructions in `docs/OPS_RUNBOOK.html`.
Do not rewrite unrelated parts of those docs.

### Phase 5, tests

New `tests/test_admin_ui.py` following `tests/conftest.py` conventions:

- every GET returns 200 and contains expected marker text
- each action POST performs its DB change and returns 303
- destructive actions are rejected on a confirmation mismatch and succeed on a match
- `/admin` is exempt from the API key while a non-admin path with a bad key still 401s, guarding that the
  exemption is correctly scoped

Keep `tests/test_admin_bulk_timer.py` green.

---

## Constraints

- No schema changes, so no Alembic migration. If one seems necessary, stop and report.
- Do not touch the student-facing frontend, the quiz endpoints, or anything unrelated.
- Do not add dependencies.
- Run `pytest` and report the real result.
- Verification is a real browser through the tunnel asserting visible text, not `curl` (CLAUDE.md 0.1).

---

## Interim operating note

Until this ships, the Streamlit dashboard can still wedge mid-exam.
The recovery is one command over SSM, and it is the only recovery:

```
docker compose restart streamlit
```

A blank dashboard with a live "Stop" indicator, or a spinner that a refresh does not clear, is this bug.
It is not the tunnel and it is not the database.
