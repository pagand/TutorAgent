# In-process request and LLM telemetry, rendered by the admin Health tab.
#
# Deliberately memory-only. Everything here is touched on the hot path of every
# student request, so the design constraint is that recording costs a
# perf_counter() pair, a deque append and an integer increment - no DB write, no
# file write, no lock.
#
# entrypoint.sh runs uvicorn with no --workers flag, so there is exactly one
# process and one event loop. That is what makes plain module state both correct
# (it sees 100% of traffic) and free (no cross-process aggregation). It would be
# neither if the worker count ever changed, and the single worker is already
# mandatory for an unrelated reason - the SQLite LLM cache is not multi-process
# safe (CLAUDE.md, Tech Stack).
#
# All of it is lost on `docker compose restart api`. The durable record is the
# JSON line per request that app/main.py's middleware writes to stdout.
import asyncio
import time
from collections import deque
from datetime import datetime, timezone

# Bounded by construction. This box has been walked into its cgroup memory cap
# before (PRELAUNCH_CHECKLIST.md, the Streamlit reconnect storm), so nothing
# here is allowed to grow with traffic: ~20 routes x 500 floats plus 100 error
# records plus 300 lag samples is well under 1MB no matter how long the exam runs.
_SAMPLES_PER_ROUTE = 500
_MAX_ERRORS = 100
_MAX_LAG_SAMPLES = 300

_started_at = time.time()

# route template -> {"durations": deque, "count": int, "c4xx": int, "c5xx": int}
_routes: dict[str, dict] = {}

# endpoint ("hints" / "chat") -> deque of durations for the LLM call ALONE,
# measured around the ainvoke, not the whole request. Kept separate because
# "were hints slow?" is a question about Gemini, not about our own overhead.
_llm: dict[str, deque] = {}

_errors: deque = deque(maxlen=_MAX_ERRORS)
_loop_lag: deque = deque(maxlen=_MAX_LAG_SAMPLES)

in_flight = 0
_total_requests = 0

# CPU percent needs a delta between two reads, so the previous sample is kept
# here and consumed by the next call to container_stats().
_last_cpu: tuple[float, float] | None = None


def record_request(route: str, status: int, duration_ms: float) -> None:
    """Called once per request by the middleware. Must stay allocation-light."""
    global _total_requests
    _total_requests += 1
    stat = _routes.get(route)
    if stat is None:
        stat = {"durations": deque(maxlen=_SAMPLES_PER_ROUTE), "count": 0, "c4xx": 0, "c5xx": 0}
        _routes[route] = stat
    stat["durations"].append(duration_ms)
    stat["count"] += 1
    if 400 <= status < 500:
        stat["c4xx"] += 1
    elif status >= 500:
        stat["c5xx"] += 1


def record_error(route: str, status: int, request_id: str, detail: str) -> None:
    """A 5xx or an unhandled exception. This ring buffer is what the Health tab
    shows instead of making someone tail `docker compose logs` over SSM."""
    _errors.append({
        "at": datetime.now(timezone.utc),
        "route": route,
        "status": status,
        "request_id": request_id,
        "detail": detail[:300],
    })


def record_llm(endpoint: str, duration_ms: float) -> None:
    series = _llm.get(endpoint)
    if series is None:
        series = deque(maxlen=_SAMPLES_PER_ROUTE)
        _llm[endpoint] = series
    series.append(duration_ms)


def percentile(values: list[float], p: float) -> float | None:
    """Nearest-rank. Called only when the Health tab is rendered, never on the
    hot path, so sorting a 500-element list here costs a student nothing."""
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round(p / 100.0 * len(ordered) + 0.5)) - 1))
    return ordered[idx]


def _series_summary(values: list[float]) -> dict:
    return {
        "n": len(values),
        "p50": percentile(values, 50),
        "p95": percentile(values, 95),
        "max": max(values) if values else None,
    }


async def sample_loop_lag(interval: float = 1.0) -> None:
    """Sleeps `interval` and records how much longer than that it actually took.

    This is the most direct available signal for the two blocking paths
    PRELAUNCH_CHECKLIST.md section C documents as the single-worker throughput
    suspects: the SQLite LLM cache calling sync lookup/update straight on the
    event loop, and the 6-slot Chroma executor making synchronous embedding HTTP
    calls. Both stall the loop, and a stalled loop shows up here as lag long
    before it shows up as a complaint.
    """
    loop = asyncio.get_running_loop()
    while True:
        start = loop.time()
        await asyncio.sleep(interval)
        _loop_lag.append(max(0.0, (loop.time() - start - interval) * 1000.0))


def _read_int(path: str) -> int | None:
    try:
        with open(path) as handle:
            return int(handle.read().strip())
    except (OSError, ValueError):
        return None


def container_stats() -> dict:
    """Memory and CPU for THIS container only, from cgroup v2.

    Deliberately not db/nginx: reading other containers' stats needs the Docker
    socket mounted into this container, which is a container-escape path. Those
    stay a `docker stats` call over SSM.
    """
    global _last_cpu
    mem_current = _read_int("/sys/fs/cgroup/memory.current")
    mem_max = _read_int("/sys/fs/cgroup/memory.max")  # None when the file reads "max"

    cpu_percent = None
    usage_usec = None
    try:
        with open("/sys/fs/cgroup/cpu.stat") as handle:
            for line in handle:
                if line.startswith("usage_usec "):
                    usage_usec = int(line.split()[1])
                    break
    except (OSError, ValueError, IndexError):
        usage_usec = None

    if usage_usec is not None:
        now = time.time()
        if _last_cpu is not None:
            prev_usec, prev_wall = _last_cpu
            elapsed = now - prev_wall
            if elapsed > 0:
                cpu_percent = ((usage_usec - prev_usec) / 1_000_000.0) / elapsed * 100.0
        _last_cpu = (usage_usec, now)

    return {
        "mem_bytes": mem_current,
        "mem_limit_bytes": mem_max,
        "cpu_percent": cpu_percent,
    }


def snapshot() -> dict:
    """Everything the Health tab renders. Pure reads of process memory, zero DB
    queries, which is why a 5s auto-refresh on that page costs nothing."""
    routes = []
    total_4xx = 0
    total_5xx = 0
    for route, stat in _routes.items():
        values = list(stat["durations"])
        total_4xx += stat["c4xx"]
        total_5xx += stat["c5xx"]
        summary = _series_summary(values)
        summary.update({"route": route, "count": stat["count"], "c4xx": stat["c4xx"], "c5xx": stat["c5xx"]})
        routes.append(summary)
    routes.sort(key=lambda r: r["count"], reverse=True)

    lag = list(_loop_lag)
    return {
        "uptime_s": time.time() - _started_at,
        "total_requests": _total_requests,
        "total_4xx": total_4xx,
        "total_5xx": total_5xx,
        "in_flight": in_flight,
        "routes": routes,
        "llm": {name: _series_summary(list(series)) for name, series in _llm.items()},
        "errors": list(_errors),
        "loop_lag": _series_summary(lag),
        "container": container_stats(),
    }


def reset() -> None:
    """Test-only. The app itself never resets; a restart is the only real reset."""
    global _total_requests, in_flight, _last_cpu
    _routes.clear()
    _llm.clear()
    _errors.clear()
    _loop_lag.clear()
    _total_requests = 0
    in_flight = 0
    _last_cpu = None
