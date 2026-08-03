# streamlit_app/admin_ops.py
# Bulk admin operations, kept separate from queries.py because that module
# imports streamlit and evaluates QUESTIONS_DF at import time — this module
# has neither, so it's directly testable under pytest and importable from
# an E2E fixture script without pulling in a streamlit runtime.
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

# Shared with frontend/e2e/fixtures/extend_all_timers.py, which runs the same
# UPDATE through an async session (Streamlit's Session here is sync) — kept as
# a single source of truth so the two paths can't silently drift apart.
EXTEND_ALL_TIMERS_SQL = (
    "UPDATE exam_sessions SET exam_duration_ms = exam_duration_ms + :extra WHERE submitted_at IS NULL"
)


def count_active_sessions(db: Session) -> int:
    """Returns the number of exam sessions not yet submitted — the set a bulk timer extension would affect."""
    result = db.execute(text("SELECT COUNT(*) FROM exam_sessions WHERE submitted_at IS NULL"))
    return result.scalar_one()


def extend_all_exam_timers(db: Session, extra_minutes: int) -> int:
    """Adds extra_minutes to exam_duration_ms for every unsubmitted session.

    Extends duration rather than shifting exam_start_ms backward, matching the
    existing per-student 'Adjust Timer' semantics (queries.extend_exam_timer)
    and preserving exam_start_ms as an accurate record of when each student
    actually began. Scoped to submitted_at IS NULL so a student who already
    finished (genuinely or via a stale-timer auto-submit) is left alone —
    that case has a separate per-student remedy (Reset Timer to NOW).
    Returns the number of rows updated.
    """
    extra_ms = extra_minutes * 60 * 1000
    result = db.execute(text(EXTEND_ALL_TIMERS_SQL), {"extra": extra_ms})
    db.commit()
    return result.rowcount


def get_llm_usage_last_24h(db: Session) -> dict:
    """Global and per-user LLM call counts in the rolling 24h window
    app/services/llm_quota.py caps against. What makes the Stage 4.5 spend
    cap operable during an exam instead of a silent tripwire — a proctor can
    see headroom before a real student ever gets capped.
    """
    global_count = db.execute(
        text("SELECT COUNT(*) FROM llm_usage_log WHERE created_at >= NOW() - INTERVAL '24 hours'")
    ).scalar_one()

    top_df = pd.read_sql(
        text(
            "SELECT user_id, COUNT(*) AS calls "
            "FROM llm_usage_log WHERE created_at >= NOW() - INTERVAL '24 hours' "
            "GROUP BY user_id ORDER BY calls DESC LIMIT 10"
        ),
        db.bind,
    )
    return {"global_count": int(global_count), "top_users": top_df}
