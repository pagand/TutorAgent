# Answers to the implementer's questions

Read alongside `ADMIN_UI_PORT_PLAN.md`.
Everything below is copied from the real repo on branch `stage3-hardening`, so build against it rather than
inferring.

---

## A3 first, because it changes the rest: scope for this pass

**Build Phase 1 and Phase 2 fully, and Phase 3 as a real diff using the file contents in A1 below.**
Do not wait. Every file you asked for is reproduced here.

Skip Phase 4 (deleting `streamlit_app/`) entirely on this pass.
Streamlit is the only working admin console until the new one is verified in a browser, and the exam is
close.
Deleting it before the replacement is proven would leave no admin path at all if the port has a problem.
Phase 4 happens in a follow-up, after verification.

Write Phase 5 tests, but read A5 first - there is a trap there that will otherwise cost you the whole pass.

---

## A0. How to hand the work back (read before writing any code)

You are the first half of a two-stage handoff. You write the code with no repo access; a second agent
running inside the repo pastes it in, runs `pytest`, fixes what does not compile, and verifies it in a
browser. That second stage is on a very tight token budget, so **your output format decides whether this
works.**

**Emit complete files. Never diffs, patches, snippets, or "add this near line 40".**
Applying a diff requires reasoning about surrounding context, which is exactly the expensive thing the
second stage cannot afford. A whole file is a mechanical paste.

Format every file as its own fenced block preceded by its exact repo path:

````
### FILE: app/admin/queries.py
```python
<the complete file, top to bottom>
```
````

Deliver, in this order:

1. `app/admin/__init__.py`
2. `app/admin/queries.py` (Phase 1, complete)
3. `app/endpoints/admin_ui.py` (Phase 2, complete)
4. `tests/test_admin_ui.py` (Phase 5, complete, honouring A5)

For the three Phase 3 files that already exist and are only being edited
(`app/main.py`, `nginx/available/app.conf`, `docker-compose.yml`), do **not** reproduce them whole - you do
not have their full contents and would fabricate the parts you cannot see. Instead give, for each, the exact
old block and the exact new block using the excerpts in A1, clearly labelled `REPLACE THIS` / `WITH THIS`.
Those are small, bounded edits and are safe to hand over that way.

Finish with a short **ASSUMPTIONS** list: every place you guessed at a column name, a model attribute, or a
return shape. That list tells the second stage where to look first when something fails, instead of it
re-reading everything. Be specific and honest; an unlisted guess costs far more than a listed one.

Do not apologise for or narrate the guesses. Just list them.

---

## A1. The integration files

### `app/utils/db.py` (complete)

```python
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.utils.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_size=20,
    max_overflow=30,
    pool_timeout=30,
    pool_pre_ping=True,
)

AsyncSessionLocal = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session
```

Use it as `db: AsyncSession = Depends(get_db)`.

### `app/main.py`, the middleware you must edit

```python
@app.middleware("http")
async def api_key_middleware(request: Request, call_next):
    if not settings.api_key:
        return await call_next(request)
    if request.method == "OPTIONS":
        return await call_next(request)
    if request.url.path == "/":
        return await call_next(request)
    provided = request.headers.get("X-API-Key", "")
    if not hmac.compare_digest(provided.encode("utf-8", "replace"), settings.api_key.get_secret_value().encode("utf-8")):
        return JSONResponse(status_code=401, content={"detail": "Invalid or missing API key"})
    return await call_next(request)
```

Add the exemption immediately after the `request.url.path == "/"` check:

```python
    # Reachable only on the loopback-published 8501 port through the SSM
    # tunnel (docker-compose publishes nginx's 8501 on 127.0.0.1, and the
    # listen-80 block CloudFront talks to returns 404 for /admin). AWS IAM
    # plus SSM is the auth boundary here, which is the same trust model the
    # Streamlit dashboard had. Must stay a prefix match on /admin only.
    if request.url.path.startswith("/admin"):
        return await call_next(request)
```

### `app/main.py`, router registration (lines ~150-160)

```python
app.include_router(questions_router.router, prefix="/questions", tags=["Questions"])
app.include_router(answer_router.router, prefix="/answer", tags=["Answers"])
app.include_router(hints_router.router, prefix="/hints", tags=["Hints"])
app.include_router(users_router.router, prefix="/users", tags=["Users"])
app.include_router(preferences_router.router)
app.include_router(proactive_hints_router.router)
app.include_router(session_router)
app.include_router(chat_router)
app.include_router(action_log_router)
app.include_router(participants_router)
```

Import your router with the `from app.endpoints.session import router as session_router` style (the newer
convention in that file) and add `app.include_router(admin_ui_router)` at the end.
The router carries its own `prefix="/admin"`, so do not pass a prefix here.

### `app/endpoints/action_log.py`, the convention to match

```python
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import UserActionLog, InterventionLog
from app.utils.authz import verify_session_owner
from app.utils.db import get_db
from app.utils.logger import logger

router = APIRouter(prefix="/log", tags=["Logging"])
```

Do **not** use `verify_session_owner` in the admin router. That is student-scoped row-level authz; the admin
path is deliberately unscoped, exactly as Streamlit was.

### `app/utils/config.py`, the fields you need

```
QUESTION_CSV_FILE_PATH: str = "prod/data/server_ready_questions.csv"
database_url: str
test_database_url: str
api_key: SecretStr | None
app_env: str
require_participant_token: bool
exam_duration_ms: int              # 25 * 60 * 1000 default
llm_max_calls_per_user_per_day: int  # 150
llm_max_calls_per_day: int           # 10000
bkt_p_t: float = 0.15
bkt_p_g: float = 0.2
bkt_p_s: float = 0.1
```

There is **no `bkt_p_l0`**. If `queries.py` referenced one, it defined it locally; check before using it.

### `nginx/nginx.conf`, the relevant maps

```nginx
resolver 127.0.0.11 valid=10s ipv6=off;

map $host $api_upstream    { default "api:8000"; }
map $host $streamlit_upstream { default "streamlit:8501"; }
map $http_upgrade $connection_upgrade { default upgrade; '' close; }
```

`$streamlit_upstream` and `$connection_upgrade` are used **only** by the 8501 block below. Leave both in
place on this pass - Phase 4 removes them together with the service. Removing them now while the streamlit
service still exists would break the running dashboard.

### `nginx/available/app.conf`, the two blocks you touch

The `listen 80` block is the CloudFront origin. It has `location /health`, `location /api/`, a
`location ~ ^/api/(hints|chat)/` regex, and `location = /api/participants/login`. It has **no
`location /`**, so `/admin` already 404s there. Add the explicit guard anyway, right after the
`location /health` block:

```nginx
    # Defense in depth. The admin UI is served on the loopback-only 8501
    # listener below, never to CloudFront. There is no `location /` here
    # today so /admin would already 404, but this makes that a decision
    # rather than an accident if a catch-all is ever added.
    location /admin {
        return 404;
    }
```

The current `listen 8501` block proxies to Streamlit. Replace its two `location` blocks with:

```nginx
    location / {
        proxy_pass         http://$api_upstream/admin/;
        proxy_http_version 1.1;
        proxy_set_header   Connection "";
        proxy_set_header   Host       $host;
        proxy_set_header   X-Real-IP  $remote_addr;
    }
```

Note the **trailing `/admin/`** on `proxy_pass`: that rewrites `/` to `/admin/` so the tunnel lands on the
dashboard root. Keep the `gzip` directives already in that block. Drop the `/static/` location and the
`Upgrade`/`Connection $connection_upgrade` websocket headers, which existed only for Streamlit.

Keep `listen 8501;` unchanged so the user's tunnel command still works verbatim:
`aws ssm start-session --target i-068fb380c5ec1d2d4 --document-name AWS-StartPortForwardingSession --parameters portNumber=8501,localPortNumber=8501`

### `docker-compose.yml`

nginx already publishes the port; **do not change this**:

```yaml
  nginx:
    ports:
      - "80:80"
      - "127.0.0.1:8501:8501"
```

Leave the `streamlit:` service in place on this pass (see A3). It currently has `expose: ["8501"]`,
`mem_limit: 1g`, and no published port.

---

## A2. Question text lookup

Use `app.services.question_service`. It is a module-level singleton loaded once during the FastAPI
lifespan, held **in memory**, so there is no file I/O at request time and **no thread offload is needed**:

```python
from app.services.question_service import question_service

question_service.get_question_by_id(question_id)  # -> Optional[Question]
question_service.get_all_questions()              # -> List[Question]
question_service.get_all_skills()                 # -> List[str]
```

Two things to watch:

- `questions_by_id` is keyed on `question.question_number`, not on a separate id field. The interaction logs'
  `question_id` corresponds to that number.
- A `Question` is an object with attributes (`question_number`, `question`, `options`, `correct_answer`,
  `question_type`, `skill`), **not** a dict and not a DataFrame row. `queries.py` used a pandas
  `QUESTIONS_DF` and indexed it; you are replacing that with attribute access.

Do not re-read the CSV.

---

## A4. Confirmation UX for destructive actions

**One "Danger Zone" section at the bottom of the user page, with a single confirm input per button.**

Concretely: Reset Progress and Delete User each get their own `<form>`, and each form contains its own
`<input name="confirm_token">` plus its own submit button. They are grouped visually under one "Danger Zone"
heading with a red border, but they do not share an input.

Reason: a single shared field that unlocks both buttons means a proctor who typed the token intending to
reset progress is one mis-click away from deleting the user, and delete is unrecoverable mid-exam. The
sections look alike and the stakes do not. Separate inputs make the two actions independently deliberate.

Server side, reject with **400** and a visible error when `confirm_token != user_id`. Do not silently
redirect on mismatch: a proctor under time pressure must be told it did not happen.

---

## A5. The trap in Phase 5 you have not hit yet

**`tests/conftest.py` runs on in-memory SQLite. Much of the Streamlit SQL is Postgres-only.**

```python
TEST_DB_URL = "sqlite+aiosqlite:///:memory:"
```

Known Postgres-only constructs in the code you are porting:

- `update_user_preferences`: `UPDATE users SET preferences = CAST(preferences AS jsonb) || CAST(:prefs AS jsonb)` - `jsonb` and `||` do not exist in SQLite
- `get_llm_usage_last_24h`: `NOW() - INTERVAL '24 hours'` - not valid SQLite

**Do not rewrite the SQL to be portable.** Production is Postgres and parity with the existing behaviour
matters more than test convenience; a "portable" rewrite of the jsonb merge would silently change merge
semantics and could corrupt a student's preferences mid-exam.

Instead:

1. Port the SQL as-is, preserving exact semantics.
2. Write SQLite-compatible tests for everything that works there: all GET routes, `reset_exam_timer`,
   `extend_exam_timer`, `clear_session_lock`, `reset_user_progress`, `delete_user`,
   `count_active_sessions`, `extend_all_exam_timers`, the confirmation-token rejection, and the API-key
   exemption scoping.
3. For the two Postgres-only paths, mark the tests `@pytest.mark.skipif` with a clear reason naming the
   construct, rather than weakening the query. Say so in your report.

If you find a third Postgres-only construct, treat it the same way and list it.

### The fixtures to use

```python
@pytest_asyncio.fixture(scope="function")
async def db_session(db_engine): ...   # AsyncSession on in-memory SQLite

@pytest_asyncio.fixture(scope="function")
async def client(db_session): ...      # httpx AsyncClient, ASGITransport(app=app)
                                       # get_db overridden, lifespan side effects patched out
```

The `client` fixture already patches out RAG init, PDF ingestion and question loading, and sets
`settings.require_participant_token = False`. Use `client` for route tests and `db_session` to assert the DB
changed. Seed rows with the ORM models from `app.models.user` (`User`, `ExamSession`, ...), the way
`tests/test_admin_bulk_timer.py` does.

**API-key exemption test:** the `client` fixture does not set `API_KEY`, and the middleware short-circuits
when `settings.api_key` is falsy, so the exemption is not exercised by default. Set
`settings.api_key = SecretStr("test-key")` inside the test (restore it afterwards) and assert that
`/admin/` returns 200 without the header while a non-admin path returns 401 without it. That is the whole
point of the test, so do not let it pass vacuously.

---

## Other things that matter

- **Async only.** `await db.execute(text(...))`, then `.mappings().all()` for rows and `.scalar_one()` for
  counts. `queries.py` passed `_db.connection()` to `pd.read_sql`; there is no equivalent and no pandas in
  the new path. Never call sync psycopg2 from the API process - it blocks the event loop, which is a
  production outage, not a style issue.
- **No pandas anywhere in `app/admin/`.** Dropping it is part of the point: it was contributing to the
  memory pressure that killed the Streamlit container.
- **No new dependencies.** Stdlib `csv`, `html`, `json`, `io` only.
- **Never use the em dash character** anywhere, including code comments and HTML copy. Plain dash or comma.
- **No Alembic migration.** There is no schema change. If you think you need one, stop and report instead.
- **Do not commit or push.** Leave the work uncommitted for review.
- **Do not touch** the student-facing frontend, the quiz endpoints, `prod/data/` (gitignored, contains real
  exam tokens and the answer key, must never enter git), or `PRELAUNCH_CHECKLIST.md`.
- **HTML escaping is not optional.** Chat messages, hint text and free-text answers are student-authored and
  land in the admin's browser. Escape every interpolated value with `html.escape`. This is the one place the
  new UI could be *less* safe than Streamlit, which escaped by default.
- **Every page must survive a refresh.** That property is the entire reason this port exists. No page may
  depend on prior state, and every POST must redirect (303) so a refresh never re-submits.
- **Report honestly.** Give the real `pytest` output with pass/fail counts. If something does not work, say


---

# agent response

## Phase 3 edit blocks

### FILE: app/main.py (edit 1 of 2, middleware exemption)
```
REPLACE THIS:
    if request.url.path == "/":
        return await call_next(request)
    provided = request.headers.get("X-API-Key", "")

WITH THIS:
    if request.url.path == "/":
        return await call_next(request)
    # Reachable only on the loopback-published 8501 port through the SSM
    # tunnel (docker-compose publishes nginx's 8501 on 127.0.0.1, and the
    # listen-80 block CloudFront talks to returns 404 for /admin). AWS IAM
    # plus SSM is the auth boundary here, the same trust model the
    # Streamlit dashboard had. Must stay a prefix match on /admin only.
    if request.url.path.startswith("/admin"):
        return await call_next(request)
    provided = request.headers.get("X-API-Key", "")
```
This edit anchors on the middleware you pasted verbatim, so `old_str` is an exact match.

### FILE: app/main.py (edit 2 of 2, router registration)
```
REPLACE THIS:
app.include_router(action_log_router)
app.include_router(participants_router)

WITH THIS:
app.include_router(action_log_router)
app.include_router(participants_router)
from app.endpoints.admin_ui import router as admin_ui_router
app.include_router(admin_ui_router)
```
Also an exact match on text you pasted verbatim. The import is placed right before its use rather than moved up to the top-of-file import block, since I can't see that block - safe to relocate for style, functionally identical either way.

### FILE: nginx/available/app.conf (two edits, best-effort anchors)
```
EDIT 1, inside the listen 80 block, right after the location /health block:

I was not given the literal text of that block (only that it exists), so
I cannot give an exact old_str for it without fabricating content I have
not seen. Insert this new location block immediately after location
/health closes:

    # Defense in depth. The admin UI is served on the loopback-only 8501
    # listener below, never to CloudFront. There is no `location /` here
    # today so /admin would already 404, but this makes that a decision
    # rather than an accident if a catch-all is ever added.
    location /admin {
        return 404;
    }

EDIT 2, inside the listen 8501 block:

I was told this block currently has two location blocks (one proxying to
Streamlit with websocket/Upgrade headers, one for /static/), but not given
their literal text, so again no exact old_str. Replace both of that
block's location blocks with this single one, keeping the existing gzip
directives and `listen 8501;` untouched:

    location / {
        proxy_pass         http://$api_upstream/admin/;
        proxy_http_version 1.1;
        proxy_set_header   Connection "";
        proxy_set_header   Host       $host;
        proxy_set_header   X-Real-IP  $remote_addr;
    }
```
Both `app/main.py` edits are exact, since that source was pasted to me verbatim. These two nginx edits are not - flagged in ASSUMPTIONS, and the second-stage agent should confirm placement against the real file rather than trust a mechanical `old_str` match here.

### FILE: docker-compose.yml
No edit this pass. Per your note, the nginx port mapping (`127.0.0.1:8501:8501`) must not change, and the `streamlit` service must stay running until the new UI is verified in a browser (Phase 4 deferred). There is nothing to change in `docker-compose.yml` yet - that comes in the Phase 4 follow-up.

## ASSUMPTIONS

- `DEFAULT_BKT_P_L0 = 0.1` in `app/admin/queries.py` - `settings` has no `bkt_p_l0`. This is display-only (replays a trajectory chart, never writes `skill_mastery`), but confirm whether production sources the real initial-mastery prior somewhere else before trusting the constant.
- `question_service.get_question_by_id(row["question_id"])` is assumed to accept `interaction_logs.question_id` directly and that it lines up with `Question.question_number`'s type. If the types differ (str vs int), the question-text join in `get_interaction_history` will silently return `None` for every row instead of erroring.
- Test seeding deliberately deviates from the "seed via ORM models" instruction. I only have confirmed model names for `User`, `ExamSession`, `UserActionLog`, `InterventionLog` (from the `action_log.py` import you showed); I'd have had to guess `InteractionLog`, `ChatLog`, `SkillMastery`, `Participant`, and all their field names. `tests/test_admin_ui.py` seeds with raw `INSERT` statements using the exact table/column names already present in the ported SQL instead, which I have high confidence in. If the real schema has additional NOT NULL columns with no default that the admin queries never touch, these inserts will need those columns added.
- Beyond the two Postgres-only constructs you flagged, `preferences->>'ab_group'` (used in `get_all_users_summary`, `get_all_interaction_logs`, `get_chat_logs`, `get_intervention_logs`, `get_action_logs`) is a third one. Modern SQLite (3.38+) supports the same `->>` syntax, so I gated the affected tests on `sqlite3.sqlite_version_info >= (3, 38, 0)` instead of an outright skip. I haven't verified the CI's actual SQLite version, or that `aiosqlite` links the same libsqlite3 the stdlib `sqlite3` module reports. If it's older, most GET-route tests here will skip, including the full user-detail page test, since that route calls `get_chat_logs`/`get_intervention_logs`/`get_action_logs` internally regardless of what's rendered.
- `EXTEND_ALL_TIMERS_SQL` now exists in `app/admin/queries.py`, but I did not update `frontend/e2e/fixtures/extend_all_timers.py` or `tests/test_admin_bulk_timer.py` to import from there - neither file was in the requested deliverable list and I don't have their contents. Since `streamlit_app/` is untouched this pass, nothing is currently broken, but the plan's "single source of truth" is duplicated until that follow-up happens.
- SQLAlchemy async result handling: I assumed `result.mappings().all()` / `.mappings().first()` return dict-like `RowMapping` objects that `dict()` cleanly, and `result.scalar_one()` / `.rowcount` behave the same as sync SQLAlchemy. Matches the `get_db()` you gave me, but I haven't seen the pinned SQLAlchemy version.
- Timestamp columns (`created_at`, `timestamp`, `last_updated`) are assumed to come back as Python `datetime.datetime` objects, so `.strftime()` / `.date()` work directly in `admin_ui.py`. If a driver path returns strings instead, display formatting and the export date-range filter break.
- `exam_start_ms` / `exam_duration_ms` are assumed to be plain integers usable in millisecond arithmetic, matching the original `int(...)` casts.
- I read "strict CSP" plus the explicit "No JS" callout on auto-refresh as intent for the whole admin surface, not just that one meta tag, so there is zero inline `<script>` or `onchange=` anywhere in `admin_ui.py` (e.g. the action-type filter is a plain select-plus-submit-button, not an auto-submitting one). If real interactivity is wanted somewhere, that's a deliberate addition, not something I left out by accident.
- I dropped Streamlit's export preview step (first-100-rows preview, per-column checkbox picker) and export a fixed column set per log type instead. The plan's Phase 2 route list only specifies `GET /admin/export` and `GET|POST /admin/export/download`, no preview route, so I read that as intentional for the stateless redesign rather than an oversight.
- Confirmation-mismatch on Reset Progress / Delete User returns a rendered HTML page with status 400, not FastAPI's default JSON error body, since a proctor needs to see it in-browser, not raw JSON.
- The two `nginx/available/app.conf` edit anchors are best-effort reconstructions, not verified literal matches, since I was told what surrounds them but not given their exact text. Both `app/main.py` edits are exact, since that source was pasted to me verbatim.

## Review

What I'm confident in: Phase 1 (`app/admin/queries.py`) is a faithful, semantics-preserving port - every SQL string is byte-identical to what you gave me except sync-to-async mechanics, and the Python-side KPI/trajectory math was worked through by hand against the pandas original rather than eyeballed. Phase 2 follows the plan's own decisions (stateless, POST-Redirect-GET, per-action confirm inputs, no JS) without improvising new ones. The two `app/main.py` edits are exact matches against text you pasted, so they should paste in cleanly.

The one real risk: the `preferences->>'ab_group'` operator touches almost every list/log query, which means almost every GET-route test in this file is conditional on the test SQLite build. First thing to check when `pytest` runs is whether `SQLITE_SUPPORTS_JSON_ARROW` evaluates true - if it's false, most of the coverage here goes gray (skipped) rather than red or green, which looks like less coverage than it is. Second thing to check is the raw-SQL seed helpers against the actual schema - if any table has a NOT NULL column the ported queries never reference, those inserts will fail loudly and the fix is just adding the column to the seed helper, not a design problem.

Not done, on purpose: `docker-compose.yml` is untouched (nothing to change while Streamlit stays up), `frontend/e2e/fixtures/extend_all_timers.py` and `tests/test_admin_bulk_timer.py` still point at `streamlit_app.admin_ops` (still works, just duplicated), and Phase 4 (deleting `streamlit_app/`) hasn't been touched at all. The plan itself says verification has to be a real browser through the tunnel, not curl - that step obviously can't happen from this side of the handoff.
  so. Do not report success you have not verified.
