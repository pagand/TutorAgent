"""Stateless HTML admin UI (ADMIN_UI_PORT_PLAN.md, Phase 2).

Plain HTTP request/response, no websocket, no server-held session. Any page
must be fully recoverable with a browser refresh - every write is a POST
followed by a 303 redirect back to a GET, so a refresh never re-submits.

No template engine - a module of functions returning HTML strings, per the
plan. Every interpolated value that could contain student- or admin-authored
text is passed through html.escape.
"""
import csv
import datetime
import html
import io
import json
from urllib.parse import quote, urlparse

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin import queries
from app.services import metrics
from app.services.llm_quota import (
    CAP_GLOBAL_KEY,
    CAP_USER_KEY,
    get_cap_overrides,
    get_effective_caps,
    set_cap_override,
)
from app.utils.config import settings
from app.utils.db import get_db


class CSRFOriginMismatch(Exception):
    """Raised by _verify_same_origin; app.main registers the HTML handler for it."""


def render_csrf_rejected_page() -> HTMLResponse:
    body = (
        '<p class="error">Request rejected: its Origin/Referer did not match this site. '
        'A cross-site page cannot use this form to change admin data.</p>'
        '<p><a href="/admin/">Back to overview</a></p>'
    )
    return _page("Request rejected", body, status_code=403)


# CSRF protection: the SSM tunnel that puts this admin UI on 127.0.0.1:8501
# makes that origin reachable from ANY tab the admin's browser has open, not
# just this app - so any web page the admin happens to have open while the
# tunnel is up could silently POST a form to e.g. /admin/exam/extend-all or
# /admin/user/X/delete. This UI is stateless (no cookies, no session, no CSRF
# token) by design, so instead we require that mutating requests carry an
# Origin or Referer that matches this site's own Host - this is the same
# protection the retired Streamlit dashboard's XSRF setting gave us. A request
# with neither header is not a browser cross-site POST (browsers always send
# Origin on a cross-origin form submission); it's a non-browser client such as
# curl from inside an SSM session, which already required network access to
# the box and gains nothing from being blocked here, so it is allowed through
# to keep ops scripts working.
async def _verify_same_origin(request: Request) -> None:
    if request.method != "POST":
        return
    header_value = request.headers.get("origin") or request.headers.get("referer")
    if header_value is None:
        return
    if urlparse(header_value).netloc != request.headers.get("host", ""):
        raise CSRFOriginMismatch()


router = APIRouter(prefix="/admin", tags=["Admin"], dependencies=[Depends(_verify_same_origin)])

HINT_STYLES = ["adaptive", "Conceptual", "Analogy", "Socratic Question", "Worked Example"]

ACTION_TYPES = [
    "session_start", "session_complete", "session_submit", "session_expire", "timer_warning",
    "question_view", "question_navigate",
    "choice_select", "answer_focus", "answer_submit", "answer_skip",
    "hint_request", "hint_display", "hint_feedback",
    "intervention_offer", "intervention_accept", "intervention_reject",
    "chat_send",
    "profile_view", "preference_update",
    "timer_expired", "intervention_offered", "intervention_accepted",
    "intervention_rejected", "chat_message_sent",
]

LOG_TYPE_OPTIONS = ["Interaction Logs", "Chat Logs", "Intervention Logs", "Action Logs"]

EXPORT_COLUMNS = {
    "Interaction Logs": ["timestamp", "user_id", "ab_group", "question_id", "skill", "user_answer",
                          "is_correct", "hint_shown", "hint_style_used", "hint_text",
                          "user_feedback_rating", "bkt_change", "time_taken_ms"],
    "Chat Logs": ["timestamp", "user_id", "ab_group", "session_id", "question_number",
                  "user_message", "tutor_response"],
    "Intervention Logs": ["timestamp", "user_id", "ab_group", "session_id", "question_number",
                           "time_on_question_ms", "mastery_at_trigger", "reason", "accepted"],
    "Action Logs": ["timestamp", "user_id", "ab_group", "session_id", "action_type",
                     "question_number", "action_data"],
}

_CHART_COLORS = ["#4f46e5", "#10b981", "#f43f5e", "#fbbf24", "#0ea5e9", "#a855f7", "#14b8a6", "#f97316"]

_STYLE = """
:root {
  --slate-900: #0f172a;
  --slate-700: #334155;
  --slate-500: #64748b;
  --slate-200: #e2e8f0;
  --slate-50: #f8fafc;
  --indigo-600: #4f46e5;
  --emerald-500: #10b981;
  --rose-500: #f43f5e;
  --amber-400: #fbbf24;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: Georgia, "Times New Roman", serif;
  background: var(--slate-50);
  color: var(--slate-900);
  font-size: 14px;
  line-height: 1.45;
}
.topbar { background: var(--slate-900); color: white; }
.topbar-inner { max-width: 1100px; margin: 0 auto; padding: 12px 24px; }
.topbar .brand { color: white; text-decoration: none; font-weight: bold; letter-spacing: 0.02em; }
.nav { background: #1e293b; }
.nav-inner { max-width: 1100px; margin: 0 auto; padding: 0 24px; display: flex; flex-wrap: wrap; }
.nav a { color: #cbd5e1; text-decoration: none; padding: 9px 16px; font-size: 13px; }
.nav a:hover { background: #334155; color: white; text-decoration: none; }
.nav a.active { background: var(--slate-50); color: var(--slate-900); font-weight: bold; }
.subnav { display: flex; flex-wrap: wrap; border-bottom: 1px solid var(--slate-200); margin: 14px 0 20px; }
.subnav a { padding: 7px 14px; font-size: 13px; color: var(--slate-700); border: 1px solid transparent; border-bottom: none; }
.subnav a:hover { background: white; text-decoration: none; }
.subnav a.active { background: white; border-color: var(--slate-200); color: var(--slate-900); font-weight: bold; margin-bottom: -1px; }
.subnav a.danger-tab { color: var(--rose-500); }
main { max-width: 1100px; margin: 0 auto; padding: 24px; }
a { color: var(--indigo-600); text-decoration: none; }
a:hover { text-decoration: underline; }
h1, h2, h3, h4 { color: var(--slate-900); font-family: Georgia, serif; }
h1 { font-size: 22px; border-bottom: 2px solid var(--slate-900); padding-bottom: 8px; }
h2 { font-size: 17px; margin-top: 32px; border-bottom: 1px solid var(--slate-200); padding-bottom: 4px; }
h3 { font-size: 14px; color: var(--slate-700); }
section { margin-bottom: 24px; }
.caption, .hint { color: var(--slate-500); font-size: 12px; }
.flash { background: #ecfdf5; border: 1px solid var(--emerald-500); color: #065f46; padding: 10px 14px; margin-bottom: 16px; font-size: 13px; }
.error { background: #fff1f2; border: 1px solid var(--rose-500); color: #9f1239; padding: 10px 14px; font-size: 13px; }
.info { color: var(--slate-500); font-style: italic; }
.warning { background: #fffbeb; border: 1px solid var(--amber-400); color: #92400e; padding: 8px 12px; font-size: 13px; }
.correct { color: var(--emerald-500); font-weight: bold; }
.wrong { color: var(--rose-500); font-weight: bold; }
.skipped { color: var(--amber-400); font-weight: bold; }
.kpi-row { display: flex; flex-wrap: wrap; gap: 16px; margin: 12px 0; }
.kpi { border: 1px solid var(--slate-200); background: white; padding: 10px 16px; min-width: 140px; }
.kpi-value { font-size: 20px; font-weight: bold; color: var(--indigo-600); }
.kpi-label { font-size: 11px; color: var(--slate-500); text-transform: uppercase; letter-spacing: 0.04em; }
table.data-table { border-collapse: collapse; width: 100%; font-size: 12px; background: white; }
table.data-table th, table.data-table td { border: 1px solid var(--slate-200); padding: 6px 8px; text-align: left; vertical-align: top; }
table.data-table th { background: var(--slate-900); color: white; font-weight: normal; }
table.data-table tr:nth-child(even) { background: var(--slate-50); }
.chart { width: 100%; max-width: 640px; height: auto; margin: 12px 0; }
.chart-bar { fill: var(--indigo-600); }
.chart-label { font-size: 11px; fill: var(--slate-700); }
.chart-value { font-size: 11px; fill: var(--slate-500); }
.chart-line { fill: none; stroke-width: 2; }
.chart-axis { stroke: var(--slate-200); stroke-width: 1; }
.legend { display: flex; gap: 12px; flex-wrap: wrap; font-size: 11px; margin-bottom: 4px; }
.legend-item { display: flex; align-items: center; gap: 4px; }
.legend-swatch { width: 10px; height: 10px; display: inline-block; }
form { margin: 8px 0; }
.inline-form { display: flex; align-items: end; gap: 8px; flex-wrap: wrap; }
.form-grid { display: flex; flex-wrap: wrap; gap: 12px; align-items: end; }
label { display: flex; flex-direction: column; font-size: 12px; gap: 4px; }
input, select, button { font-family: inherit; font-size: 13px; padding: 6px 8px; border: 1px solid var(--slate-200); }
button { background: var(--indigo-600); color: white; border: none; cursor: pointer; padding: 7px 14px; }
button:hover { opacity: 0.9; }
.button-row { display: flex; gap: 24px; flex-wrap: wrap; }
.button-row form { border: 1px solid var(--slate-200); background: white; padding: 10px; }
.danger-heading { color: var(--rose-500); }
.danger-zone { display: flex; gap: 16px; flex-wrap: wrap; }
.danger-card { border: 1px solid var(--rose-500); background: #fff1f2; padding: 12px; flex: 1; min-width: 240px; }
.danger-btn { background: var(--rose-500); }
.json-block, .text-block { background: var(--slate-900); color: var(--slate-50); padding: 12px; font-size: 11px; overflow-x: auto; white-space: pre-wrap; }
.callout { background: #eef2ff; border-left: 3px solid var(--indigo-600); padding: 6px 10px; font-size: 12px; }
code { background: var(--slate-200); padding: 1px 4px; font-size: 11px; }
details { margin: 8px 0; border: 1px solid var(--slate-200); background: white; padding: 6px 10px; }
summary { cursor: pointer; font-weight: bold; font-size: 13px; }
hr { border: none; border-top: 1px solid var(--slate-200); margin: 8px 0; }
"""


# --- Page shell and small helpers ---

# Ordered left to right by how likely you are to need it with an exam running.
# Exam is first and is the landing page: bulk timer extension and the LLM caps
# are the two controls a proctor reaches for under time pressure, and they used
# to sit below two research charts and the full roster table.
_TABS = [
    ("/admin/", "Exam"),
    ("/admin/students", "Students"),
    ("/admin/health", "Health"),
    ("/admin/export", "Export"),
    ("/admin/research", "Research"),
]


def _nav(active: str) -> str:
    items = []
    for href, label in _TABS:
        cls = ' class="active"' if label == active else ""
        items.append(f'<a href="{href}"{cls}>{label}</a>')
    return f'<nav class="nav"><div class="nav-inner">{"".join(items)}</div></nav>'


def _page(title: str, body: str, refresh: int | None = None, status_code: int = 200,
          active_tab: str = "") -> HTMLResponse:
    refresh_tag = f'<meta http-equiv="refresh" content="{refresh}">' if refresh else ""
    doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{html.escape(title)}</title>
{refresh_tag}
<style>{_STYLE}</style>
</head>
<body>
<header class="topbar"><div class="topbar-inner"><a class="brand" href="/admin/">DaTu AIR Admin</a></div></header>
{_nav(active_tab)}
<main>
{body}
</main>
</body>
</html>"""
    return HTMLResponse(doc, status_code=status_code)


# Manage first, on purpose: the timer, the session lock and the unlock repair are
# what a proctor opens a student's page to do. Danger is a separate tab so Reset
# Progress and Delete User are never on the screen you land on - both still
# require typing the exact user id, this just adds distance.
_USER_TABS = ["Manage", "Overview", "Answers", "Hints", "Chat", "Actions", "Danger"]


def _user_nav(user_id: str, active: str) -> str:
    uid = quote(user_id)
    items = []
    for label in _USER_TABS:
        classes = []
        if label == active:
            classes.append("active")
        if label == "Danger":
            classes.append("danger-tab")
        cls = f' class="{" ".join(classes)}"' if classes else ""
        items.append(f'<a href="/admin/user/{uid}?tab={label.lower()}"{cls}>{label}</a>')
    return f'<div class="subnav">{"".join(items)}</div>'


def _flash(msg: str | None) -> str:
    return f'<div class="flash">{html.escape(msg)}</div>' if msg else ""


def _redirect(url: str, msg: str) -> RedirectResponse:
    sep = "&" if "?" in url else "?"
    return RedirectResponse(url=f"{url}{sep}msg={quote(msg)}", status_code=303)


def _confirm_mismatch_response(user_id: str, action_label: str) -> HTMLResponse:
    body = (
        f'<p class="error">Confirmation text did not match the user id. '
        f'{html.escape(action_label)} was not performed.</p>'
        f'<p><a href="/admin/user/{html.escape(user_id)}">Back to user</a></p>'
    )
    return _page("Confirmation failed", body, status_code=400)


def _fmt_ts(ts, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    if ts is None:
        return "-"
    if hasattr(ts, "strftime"):
        return ts.strftime(fmt)
    return str(ts)


def _truncate(text_value, length: int = 200) -> str:
    if text_value is None:
        return ""
    text_value = str(text_value)
    return text_value if len(text_value) <= length else text_value[: length - 1] + "..."


def _yn(value) -> str:
    if value is None:
        return "-"
    return "Yes" if value else "No"


def _accepted_label(accepted) -> str:
    if accepted is True:
        return "Accepted"
    if accepted is False:
        return "Rejected"
    return "Offered"


# --- Chart and table builders ---

def _kpi_row(items: list[tuple[str, object]]) -> str:
    cells = "".join(
        f'<div class="kpi"><div class="kpi-value">{html.escape(str(v))}</div>'
        f'<div class="kpi-label">{html.escape(k)}</div></div>'
        for k, v in items
    )
    return f'<div class="kpi-row">{cells}</div>'


def _bar_chart(counts: dict, width: int = 480, bar_height: int = 28, gap: int = 10,
               max_value: float | None = None) -> str:
    if not counts:
        return '<p class="info">No data.</p>'
    max_val = max_value if max_value is not None else (max(counts.values()) or 1)
    # 150px label gutter on the left, plus room on the right for the value text.
    # Without that right gutter the longest bar runs to the viewBox edge and its
    # own value is clipped, which is exactly what "3" did on the live dashboard.
    chart_width = width - 150 - 40
    bars = []
    y = 10
    for label, value in counts.items():
        bar_w = max(1, int((value / max_val) * chart_width)) if max_val else 0
        value_label = f"{value:.2f}" if isinstance(value, float) else str(value)
        bars.append(
            f'<text x="0" y="{y + bar_height / 2 + 4:.0f}" class="chart-label">{html.escape(str(label))}</text>'
            f'<rect x="150" y="{y}" width="{bar_w}" height="{bar_height}" class="chart-bar"></rect>'
            f'<text x="{150 + bar_w + 6}" y="{y + bar_height / 2 + 4:.0f}" class="chart-value">{html.escape(value_label)}</text>'
        )
        y += bar_height + gap
    return f'<svg viewBox="0 0 {width} {y}" class="chart">{"".join(bars)}</svg>'


def _line_chart(trajectory: list[dict], width: int = 640, height: int = 240) -> str:
    if not trajectory:
        return '<p class="info">No data.</p>'
    skills = [k for k in trajectory[0].keys() if k != "interaction"]
    if not skills:
        return '<p class="info">No data.</p>'
    n = len(trajectory)
    pad = 30
    plot_w = width - 2 * pad
    plot_h = height - 2 * pad

    def _x(i):
        return pad + (i / max(1, n - 1)) * plot_w

    def _y(v):
        return pad + (1 - max(0.0, min(1.0, v))) * plot_h

    lines = []
    for idx, skill in enumerate(skills):
        color = _CHART_COLORS[idx % len(_CHART_COLORS)]
        pts = " ".join(f"{_x(i):.1f},{_y(row[skill]):.1f}" for i, row in enumerate(trajectory))
        lines.append(f'<polyline points="{pts}" class="chart-line" style="stroke:{color}"></polyline>')
    legend = "".join(
        f'<span class="legend-item"><span class="legend-swatch" '
        f'style="background:{_CHART_COLORS[i % len(_CHART_COLORS)]}"></span>{html.escape(str(s))}</span>'
        for i, s in enumerate(skills)
    )
    axis = (
        f'<line x1="{pad}" y1="{pad}" x2="{pad}" y2="{height - pad}" class="chart-axis"></line>'
        f'<line x1="{pad}" y1="{height - pad}" x2="{width - pad}" y2="{height - pad}" class="chart-axis"></line>'
    )
    svg = f'<svg viewBox="0 0 {width} {height}" class="chart">{axis}{"".join(lines)}</svg>'
    return f'<div class="legend">{legend}</div>{svg}'


class _RawHTML(str):
    """Marker: _simple_table renders this cell's content as-is, skipping html.escape."""


def _correctness_cell(is_correct) -> _RawHTML:
    if is_correct is None:
        return _RawHTML("-")
    cls = "correct" if is_correct else "wrong"
    return _RawHTML(f'<span class="{cls}">{"Yes" if is_correct else "No"}</span>')


def _simple_table(headers: list[str], rows: list[list]) -> str:
    thead = "".join(f"<th>{html.escape(str(h))}</th>" for h in headers)
    trs = []
    for row in rows:
        tds = "".join(
            f"<td>{v if isinstance(v, _RawHTML) else html.escape('' if v is None else str(v))}</td>"
            for v in row
        )
        trs.append(f"<tr>{tds}</tr>")
    return f'<table class="data-table"><thead><tr>{thead}</tr></thead><tbody>{"".join(trs)}</tbody></table>'


def _users_table(users: list[dict]) -> str:
    headers = ["user_id", "ab_group", "participant_status", "hint_style_pref", "created_at",
               "total_interactions", "correctness", "hints_used", "chat_messages",
               "remaining_min", "submitted"]
    thead = "".join(f"<th>{h}</th>" for h in headers)
    rows = []
    for u in users:
        created = _fmt_ts(u.get("created_at"), "%Y-%m-%d %H:%M")
        correctness = (
            f"{u['correct_answers'] / u['total_interactions']:.0%}"
            if u["total_interactions"] else "-"
        )
        uid = html.escape(str(u["user_id"]))
        user_link = f'<a href="/admin/user/{uid}">{uid}</a>'
        cells = [
            user_link,
            html.escape(str(u.get("ab_group") or "")),
            html.escape(str(u.get("participant_status") or "")),
            html.escape(str(u.get("hint_style_pref") or "")),
            html.escape(created),
            str(u["total_interactions"]),
            correctness,
            str(u["hints_used"]),
            str(u["chat_messages"]),
            html.escape("" if u["remaining_min"] is None else str(u["remaining_min"])),
            "Yes" if u["submitted"] else "No",
        ]
        rows.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
    return f'<table class="data-table"><thead><tr>{thead}</tr></thead><tbody>{"".join(rows)}</tbody></table>'


# --- Form builders ---

def _action_type_filter_form(user_id: str, selected: str | None) -> str:
    options = ['<option value="">All action types</option>']
    for a in ACTION_TYPES:
        sel = " selected" if a == selected else ""
        options.append(f'<option value="{html.escape(a)}"{sel}>{html.escape(a)}</option>')
    # The hidden tab field keeps a filter submission on the Actions tab; without
    # it this GET would drop the query param and bounce back to Manage.
    return f"""
    <form method="get" action="/admin/user/{html.escape(user_id)}" class="inline-form">
      <input type="hidden" name="tab" value="actions">
      <label>Filter by action type
        <select name="action_type">{"".join(options)}</select>
      </label>
      <button type="submit">Apply filter</button>
    </form>
    """


def _unlock_question_form(user_id: str, states: list[dict]) -> str:
    """Picker for the non-destructive repair. Only locked questions are offered."""
    uid = html.escape(user_id)
    locked = [s for s in states if s["locked"]]
    if not locked:
        return '<p class="info">No locked questions. Nothing to unlock.</p>'
    options = "".join(
        f'<option value="{s["question_id"]}">'
        f'Q{s["question_id"]} - {html.escape(_truncate(s.get("question") or "", 60))} ({s["reason"]})'
        f'</option>'
        for s in locked
    )
    return f"""
    <form method="post" action="/admin/user/{uid}/question/unlock" class="inline-form">
      <label>Locked question
        <select name="question_id">{options}</select>
      </label>
      <button type="submit">Unlock Question</button>
    </form>
    <p class="hint">
      Voids this question's attempts so the student can answer it again. The rows are
      <strong>not deleted</strong> - they stay in the CSV export, so the research record still
      shows what happened and that an admin intervened.
      <strong>The student must reload their browser</strong> for the question to become
      answerable: unlike a timer change there is no heartbeat pushing this to an open tab.
    </p>
    <p class="warning">
      Use this when the system locked a student wrongly, not to grant a second chance. Once a
      question reaches 2 failed attempts the answer key for it has already been sent to that
      student's browser.
    </p>
    """


def _cap_override_form(global_cap: int, user_cap: int, overrides: dict) -> str:
    """Live LLM cap control. Raising a cap used to mean an SSM session, a .env
    edit and an api restart, mid-exam, under time pressure."""
    active = ""
    if overrides:
        parts = ", ".join(f"{k} = {v}" for k, v in sorted(overrides.items()))
        active = (
            f'<p class="warning"><strong>Override active:</strong> {html.escape(parts)}. '
            f'These persist across an api restart. Clear them after the exam.</p>'
        )
    return f"""
    {active}
    <form method="post" action="/admin/settings/llm-caps" class="form-grid">
      <label>Global calls per day
        <input type="number" name="global_cap" value="{global_cap}" min="1" max="1000000" required>
      </label>
      <label>Per-user calls per day
        <input type="number" name="user_cap" value="{user_cap}" min="1" max="100000" required>
      </label>
      <button type="submit">Apply Caps</button>
    </form>
    <form method="post" action="/admin/settings/llm-caps/clear">
      <button type="submit">Reset to .env values</button>
    </form>
    """


def _edit_profile_form(user_id: str, ab_group: str, hint_style: str, intervention_pref: str) -> str:
    ab_options = "".join(
        f'<option value="{v}"{" selected" if ab_group == v else ""}>{v}</option>'
        for v in ["adaptive", "free_choice"]
    )
    hint_options = "".join(
        f'<option value="{html.escape(v)}"{" selected" if hint_style == v else ""}>{html.escape(v)}</option>'
        for v in HINT_STYLES
    )
    intervention_options = "".join(
        f'<option value="{v}"{" selected" if intervention_pref == v else ""}>{v}</option>'
        for v in ["proactive", "manual"]
    )
    return f"""
    <form method="post" action="/admin/user/{html.escape(user_id)}/prefs" class="form-grid">
      <label>A/B Group <select name="ab_group">{ab_options}</select></label>
      <label>Hint Style <select name="hint_style_preference">{hint_options}</select></label>
      <label>Intervention Preference <select name="intervention_preference">{intervention_options}</select></label>
      <button type="submit">Save Profile Changes</button>
    </form>
    """


def _timer_forms(user_id: str) -> str:
    uid = html.escape(user_id)
    return f"""
    <div class="button-row">
      <form method="post" action="/admin/user/{uid}/timer/reset">
        <button type="submit">Reset Timer to NOW</button>
        <p class="hint">Restarts the exam clock from this moment. Clears submitted flag.</p>
      </form>
      <form method="post" action="/admin/user/{uid}/timer/extend" class="inline-form">
        <label>Adjust minutes (negative to reduce)
          <input type="number" name="extra_minutes" value="10" min="-120" max="120" step="5" required>
        </label>
        <button type="submit">Adjust Timer</button>
      </form>
      <form method="post" action="/admin/user/{uid}/session-lock/clear">
        <button type="submit">Clear Session Lock</button>
        <p class="hint">Clears the active device lock so the student can re-enter from any device.</p>
      </form>
    </div>
    """


def _danger_zone_forms(user_id: str) -> str:
    uid = html.escape(user_id)
    return f"""
    <div class="danger-zone">
      <div class="danger-card">
        <h4>Reset User Progress</h4>
        <p>Deletes all interaction history and skill mastery, resets participant to unused.</p>
        <form method="post" action="/admin/user/{uid}/progress/reset">
          <label>Type <code>{uid}</code> to confirm
            <input type="text" name="confirm_token" required>
          </label>
          <button type="submit" class="danger-btn">Reset Progress</button>
        </form>
      </div>
      <div class="danger-card">
        <h4>Delete User</h4>
        <p>Permanently deletes the user and all data.</p>
        <form method="post" action="/admin/user/{uid}/delete">
          <label>Type <code>{uid}</code> to confirm
            <input type="text" name="confirm_token" required>
          </label>
          <button type="submit" class="danger-btn">Delete User</button>
        </form>
      </div>
    </div>
    """


# --- Routes: overview ---

@router.get("/", response_class=HTMLResponse)
async def admin_home(db: AsyncSession = Depends(get_db), msg: str | None = None,
                      refresh: str | None = None):
    """Exam tab: only the controls that matter with an exam actually running."""
    active_count = await queries.count_active_sessions(db)
    llm_usage = await queries.get_llm_usage_last_24h(db)
    global_cap, user_cap = await get_effective_caps(db)
    overrides = await get_cap_overrides(db)

    body = [_flash(msg), "<h1>Exam Control</h1>"]

    body.append("<h2>Bulk Timer Extension</h2>")
    body.append(
        '<p class="caption">The remedy for a mid-exam outage. Students who have already '
        'submitted are untouched; for one student use their Manage tab instead. This reaches an '
        'already-open tab within one 25s heartbeat, no reload needed.</p>'
    )
    body.append(_kpi_row([("Unsubmitted sessions (affected by extension)", active_count)]))
    body.append("""
    <form method="post" action="/admin/exam/extend-all" class="inline-form">
      <label>Minutes to add to every unsubmitted session (negative to reduce)
        <input type="number" name="extra_minutes" value="10" min="-120" max="120" step="5" required>
      </label>
      <button type="submit">Apply to All Unsubmitted Sessions</button>
    </form>
    """)

    body.append("<h2>LLM Usage (last 24h)</h2>")
    headroom = max(0, global_cap - llm_usage["global_count"])
    body.append(
        '<p class="caption">Rolling 24h window, the same window app/services/llm_quota.py caps '
        'against. Nothing alerts when a cap is approached, it simply starts rejecting hint and '
        'chat requests, so this is worth a glance if usage looks heavy.</p>'
    )
    body.append(_kpi_row([
        ("Global calls (24h)", llm_usage["global_count"]),
        ("Global headroom remaining", headroom),
        ("Global cap", global_cap),
        ("Per-user cap", user_cap),
    ]))
    if llm_usage["top_users"]:
        body.append("<h3>Top consumers (24h)</h3>")
        body.append(_simple_table(["user_id", "calls"], [[u["user_id"], u["calls"]] for u in llm_usage["top_users"]]))

    body.append("<h3>Adjust caps live</h3>")
    body.append(_cap_override_form(global_cap, user_cap, overrides))

    toggle = (
        '<a href="/admin/?refresh=10">Enable 10s auto-refresh</a>' if refresh != "10"
        else '<a href="/admin/">Disable auto-refresh</a>'
    )
    body.append(f'<p class="caption">{toggle}</p>')

    return _page("Exam Control", "\n".join(body),
                 refresh=10 if refresh == "10" else None, active_tab="Exam")


@router.get("/students", response_class=HTMLResponse)
async def admin_students(db: AsyncSession = Depends(get_db), msg: str | None = None):
    users = await queries.get_all_users_summary(db)
    body = [_flash(msg), "<h1>Students</h1>"]
    if not users:
        body.append('<p class="info">No users yet.</p>')
    else:
        body.append(_kpi_row([
            ("Total Users", len(users)),
            ("Started", sum(1 for u in users if u["total_interactions"])),
            ("Submitted", sum(1 for u in users if u["submitted"])),
        ]))
        body.append('<p class="caption">Click a token to open that student.</p>')
        body.append(_users_table(users))
    return _page("Students", "\n".join(body), active_tab="Students")


@router.get("/research", response_class=HTMLResponse)
async def admin_research(db: AsyncSession = Depends(get_db), msg: str | None = None):
    """Aggregate analytics. Deliberately off the landing page: none of this is
    actionable while an exam is running."""
    users = await queries.get_all_users_summary(db)
    body = [_flash(msg), "<h1>Research Analytics</h1>"]
    if not users:
        body.append('<p class="info">No users yet.</p>')
        return _page("Research Analytics", "\n".join(body), active_tab="Research")

    adaptive = sum(1 for u in users if u["ab_group"] == "adaptive")
    free_choice = sum(1 for u in users if u["ab_group"] == "free_choice")
    body.append(_kpi_row([
        ("Total Users", len(users)),
        ("Adaptive Group", adaptive),
        ("Free Choice Group", free_choice),
        ("Total Interactions", sum(u["total_interactions"] for u in users)),
    ]))

    ab_counts: dict = {}
    for u in users:
        key = u["ab_group"] or "unknown"
        ab_counts[key] = ab_counts.get(key, 0) + 1
    body.append("<h2>A/B Group Distribution</h2>")
    body.append(_bar_chart(ab_counts))

    fc_users = [u for u in users if u["ab_group"] == "free_choice"]
    body.append("<h2>Hint Style Preferences (free_choice group)</h2>")
    if fc_users:
        style_counts: dict = {}
        for u in fc_users:
            key = u["hint_style_pref"] or "unset"
            style_counts[key] = style_counts.get(key, 0) + 1
        body.append(_bar_chart(style_counts))
    else:
        body.append('<p class="info">No free_choice users yet.</p>')

    return _page("Research Analytics", "\n".join(body), active_tab="Research")


# --- Routes: health ---

def _ms(value) -> str:
    return "-" if value is None else f"{value:,.0f} ms"


def _duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    return f"{seconds // 3600}h {(seconds % 3600) // 60}m"


@router.get("/health", response_class=HTMLResponse)
async def admin_health(refresh: str | None = None):
    """Live server health. Takes no db session at all, on purpose.

    Every number here is read from process memory, so auto-refresh costs nothing
    and this page stays usable exactly when the database is the thing in trouble.
    """
    snap = metrics.snapshot()

    body = ["<h1>Server Health</h1>"]
    body.append(
        '<p class="caption">In-process counters, no database queries. '
        '<strong>All of it resets on <code>docker compose restart api</code></strong> - the '
        'durable record is the one JSON line per request in <code>docker compose logs api</code>, '
        'joinable by <code>request_id</code>.</p>'
    )

    container = snap["container"]
    mem_label = "-"
    if container["mem_bytes"] is not None:
        mem_mb = container["mem_bytes"] / (1024 * 1024)
        if container["mem_limit_bytes"]:
            limit_mb = container["mem_limit_bytes"] / (1024 * 1024)
            mem_label = f"{mem_mb:,.0f} / {limit_mb:,.0f} MB"
        else:
            mem_label = f"{mem_mb:,.0f} MB"
    cpu_label = "-" if container["cpu_percent"] is None else f"{container['cpu_percent']:.1f}%"

    body.append(_kpi_row([
        ("Uptime", _duration(snap["uptime_s"])),
        ("Requests", f"{snap['total_requests']:,}"),
        ("4xx", snap["total_4xx"]),
        ("5xx", snap["total_5xx"]),
        ("In flight", snap["in_flight"]),
        ("api memory", mem_label),
        ("api CPU", cpu_label),
    ]))
    body.append(
        '<p class="caption">Memory and CPU are for the <code>api</code> container only. '
        'Reading <code>db</code> and <code>nginx</code> would need the Docker socket mounted in '
        'here, which is a container-escape path, so those stay a <code>docker stats</code> call '
        'over SSM. CPU is measured between two loads of this page, so the first read shows "-".</p>'
    )

    lag = snap["loop_lag"]
    body.append("<h2>Event loop lag</h2>")
    body.append(
        '<p class="caption">How much longer than 1.000s a 1s sleep actually took. Near zero is '
        'healthy. Sustained lag means something is blocking the single worker - the two known '
        'suspects are the SQLite LLM cache (its sync lookup/update run straight on the event '
        'loop) and Chroma retrieval (a 6-slot executor making synchronous embedding calls).</p>'
    )
    body.append(_kpi_row([
        ("p50", _ms(lag["p50"])),
        ("p95", _ms(lag["p95"])),
        ("max", _ms(lag["max"])),
        ("samples", lag["n"]),
    ]))

    body.append("<h2>LLM and retrieval latency</h2>")
    body.append(
        '<p class="caption">The Gemini and Chroma calls timed on their own, separately from the '
        'request that wrapped them. UX budget for hints and chat is p50 &lt; 6s, p95 &lt; 15s.</p>'
    )
    if snap["llm"]:
        body.append(_simple_table(
            ["call", "n", "p50", "p95", "max"],
            [[name, s["n"], _ms(s["p50"]), _ms(s["p95"]), _ms(s["max"])]
             for name, s in sorted(snap["llm"].items())],
        ))
    else:
        body.append('<p class="info">No hint or chat calls since this process started.</p>')

    body.append("<h2>Request latency by route</h2>")
    if snap["routes"]:
        body.append(_simple_table(
            ["route", "n", "p50", "p95", "max", "4xx", "5xx"],
            [[r["route"], r["count"], _ms(r["p50"]), _ms(r["p95"]), _ms(r["max"]),
              r["c4xx"], _RawHTML(f'<span class="wrong">{r["c5xx"]}</span>') if r["c5xx"] else "0"]
             for r in snap["routes"]],
        ))
        body.append(
            '<p class="caption">Percentiles are over the last 500 requests per route. Routes are '
            'path templates, so every student shares one <code>/answer/</code> row rather than '
            'creating one each.</p>'
        )
    else:
        body.append('<p class="info">No requests recorded yet.</p>')

    body.append("<h2>Recent errors</h2>")
    if snap["errors"]:
        body.append(_simple_table(
            ["when", "route", "status", "request_id", "detail"],
            [[_fmt_ts(e["at"]), e["route"], e["status"], e["request_id"], _truncate(e["detail"], 160)]
             for e in reversed(snap["errors"])],
        ))
        body.append(
            '<p class="caption">Last 100 only. Grep the api log for the <code>request_id</code> '
            'to get every log line from that same request.</p>'
        )
    else:
        body.append('<p class="info">No 5xx responses or unhandled exceptions recorded.</p>')

    toggle = (
        '<a href="/admin/health?refresh=5">Enable 5s auto-refresh</a>' if refresh != "5"
        else '<a href="/admin/health">Disable auto-refresh</a>'
    )
    body.append(f'<p class="caption">{toggle}</p>')

    return _page("Server Health", "\n".join(body),
                 refresh=5 if refresh == "5" else None, active_tab="Health")


# --- Routes: user detail ---

@router.get("/user/{user_id}", response_class=HTMLResponse)
async def admin_user_detail(user_id: str, db: AsyncSession = Depends(get_db),
                             msg: str | None = None, action_type: str | None = None,
                             tab: str = "manage"):
    profile = await queries.get_user_profile(db, user_id)
    if not profile:
        body = (
            f'<p class="error">No user found for id {html.escape(user_id)}.</p>'
            '<p><a href="/admin/">Back to overview</a></p>'
        )
        return _page("User not found", body, status_code=404)

    if tab not in ("manage", "overview", "answers", "hints", "chat", "actions", "danger"):
        tab = "manage"
    active_label = next(label for label in _USER_TABS if label.lower() == tab)

    prefs = profile.get("preferences") or {}
    ab_group = prefs.get("ab_group", "unknown")
    hint_style = prefs.get("hint_style_preference", "-")
    intervention_pref = prefs.get("intervention_preference", "-")

    body = [_flash(msg), '<p><a href="/admin/students">Back to overview</a></p>']
    body.append(f'<h1>User: {html.escape(user_id)}</h1>')
    body.append(
        f'<p class="caption">A/B Group: <strong>{html.escape(str(ab_group))}</strong> '
        f'| Hint style: <strong>{html.escape(str(hint_style))}</strong> '
        f'| Intervention: <strong>{html.escape(str(intervention_pref))}</strong></p>'
    )
    body.append(_user_nav(user_id, active_label))

    if tab == "manage":
        session_info = await queries.get_exam_session_info(db, user_id)
        participant_info = await queries.get_participant_info(db, user_id)
        states = await queries.get_question_states(db, user_id)

        body.append('<section><h2>Timer Management</h2>')
        if session_info:
            body.append(_kpi_row([
                ("Remaining", f"{session_info['remaining_min']} min"),
                ("Duration", f"{session_info['exam_duration_ms'] // 60000} min"),
                ("Submitted", "Yes" if session_info["submitted"] else "No"),
            ]))
        else:
            body.append('<p class="info">No exam session started yet.</p>')
        if participant_info:
            lock_label = participant_info.get("active_session_id") or "-"
            last_seen = participant_info.get("last_seen_at") or "-"
            body.append(
                f'<p class="caption">Participant status: <strong>{html.escape(str(participant_info.get("status") or "?"))}</strong>'
                f' | Lock: <code>{html.escape(str(lock_label))}</code>'
                f' | Last seen: {html.escape(str(last_seen))}</p>'
            )
        body.append(_timer_forms(user_id))
        body.append('</section>')

        body.append('<section><h2>Repair</h2>')
        body.append(_unlock_question_form(user_id, states))
        body.append('</section>')

        body.append('<section><h3>Edit Profile</h3>')
        body.append(_edit_profile_form(user_id, ab_group, hint_style, intervention_pref))
        body.append('</section>')

    elif tab == "overview":
        kpis = await queries.get_user_kpis(db, user_id)
        mastery = await queries.get_skill_mastery(db, user_id)
        trajectory = await queries.get_skill_mastery_trajectory(db, user_id)

        body.append('<section><h2>Key Performance Indicators</h2>')
        avg_rating = kpis["avg_hint_rating"]
        avg_rating_display = avg_rating if isinstance(avg_rating, str) else f"{avg_rating:.2f}"
        body.append(_kpi_row([
            ("Overall Correctness", f"{kpis['overall_correctness']:.1%}"),
            ("Avg. Attempts to Correct", f"{kpis['avg_attempts_to_correct']:.2f}"),
            ("Total Hints Received", kpis["total_hints"]),
            ("Avg. Hint Rating", avg_rating_display),
        ]))
        body.append('<h3>Raw Profile Data</h3>')
        body.append(f'<pre class="json-block">{html.escape(json.dumps(profile, indent=2, default=str))}</pre>')
        body.append('</section>')

        body.append('<section><h2>Skill Mastery Trajectory</h2>')
        if trajectory:
            body.append(_line_chart(trajectory))
        else:
            body.append('<p class="info">No interaction history to build trajectory.</p>')
        if mastery:
            body.append('<h3>Current Mastery by Skill</h3>')
            body.append(_bar_chart({m["skill_id"]: m["mastery_level"] for m in mastery}, max_value=1.0))
            body.append('<details><summary>Raw Data</summary>')
            body.append(_simple_table(
                ["skill_id", "mastery_level", "consecutive_errors", "last_updated"],
                [[m["skill_id"], f"{m['mastery_level']:.4f}", m["consecutive_errors"], _fmt_ts(m["last_updated"])]
                 for m in mastery],
            ))
            body.append('</details>')
        body.append('</section>')

    elif tab == "answers":
        history = await queries.get_interaction_history(db, user_id)

        body.append('<section><h2>Interaction History</h2>')
        if history:
            body.append(_simple_table(
                ["timestamp", "question_id", "question", "user_answer", "is_correct", "skill",
                 "hint_shown", "hint_style_used", "user_feedback_rating", "bkt_change"],
                [[_fmt_ts(r["timestamp"]), r["question_id"], _truncate(r.get("question")),
                  r["user_answer"], _correctness_cell(r["is_correct"]), r["skill"], _yn(r["hint_shown"]),
                  r["hint_style_used"], r["user_feedback_rating"],
                  None if r["bkt_change"] is None else f"{r['bkt_change']:.4f}"]
                 for r in history],
            ))
        else:
            body.append('<p class="info">No interaction history.</p>')
        body.append('</section>')

    elif tab == "hints":
        history = await queries.get_interaction_history(db, user_id)
        interventions = await queries.get_intervention_logs(db, user_id=user_id)

        body.append('<section><h2>Hints and Interventions</h2>')
        if history:
            grouped: dict = {}
            for row in history:
                grouped.setdefault(row["question_id"], []).append(row)
            for qid, rows in grouped.items():
                question_text = rows[0].get("question") or f"Question {qid}"
                status = "Correct" if any(r["is_correct"] for r in rows) else "Incorrect"
                title = f"Q{qid}: {_truncate(question_text, 70)} ({status})"
                body.append(f'<details><summary>{html.escape(title)}</summary>')
                for r in sorted(rows, key=lambda r: r["timestamp"]):
                    body.append(f'<p><strong>{_fmt_ts(r["timestamp"])}</strong></p>')
                    if r["user_answer"] is not None:
                        ans = f'<code>{html.escape(str(r["user_answer"]))}</code>'
                    else:
                        ans = '<span class="skipped">Skipped</span>'
                    correct_label = (
                        '<span class="correct">Correct</span>' if r["is_correct"]
                        else '<span class="wrong">Incorrect</span>'
                    )
                    body.append(f'<p>Answer: {ans} - {correct_label}</p>')
                    if r.get("bkt_change") is not None:
                        body.append(f'<p>BKT change: <code>{r["bkt_change"]:.4f}</code></p>')
                    if r.get("hint_shown"):
                        rating = r.get("user_feedback_rating")
                        body.append(
                            f'<p class="callout">Hint style: <code>{html.escape(str(r.get("hint_style_used") or ""))}</code>'
                            f' | Rating: <code>{rating if rating is not None else "-"}/5</code></p>'
                        )
                        if r.get("hint_text"):
                            body.append(f'<pre class="text-block">{html.escape(str(r["hint_text"]))}</pre>')
                    body.append('<hr>')
                body.append('</details>')
        else:
            body.append('<p class="info">No data.</p>')

        body.append('<h3>Intervention Events</h3>')
        if interventions:
            body.append(_simple_table(
                ["timestamp", "question_number", "time_on_question_ms", "mastery_at_trigger", "accepted"],
                [[_fmt_ts(iv["timestamp"]), iv["question_number"], iv["time_on_question_ms"],
                  iv["mastery_at_trigger"], _accepted_label(iv["accepted"])] for iv in interventions],
            ))
        else:
            body.append('<p class="info">No intervention events logged.</p>')
        body.append('</section>')

    elif tab == "chat":
        chats = await queries.get_chat_logs(db, user_id=user_id)

        body.append('<section><h2>Chat Log</h2>')
        if chats:
            for c in sorted(chats, key=lambda c: c["timestamp"]):
                body.append(f'<p><strong>Q{c["question_number"]} - {_fmt_ts(c["timestamp"], "%H:%M:%S")}</strong></p>')
                body.append(f'<p>Student: {html.escape(str(c["user_message"]))}</p>')
                body.append(f'<p>Tutor: {html.escape(str(c["tutor_response"]))}</p>')
                body.append('<hr>')
            body.append(
                f'<p><a href="/admin/export/download?log_type=Chat+Logs&user_id={quote(user_id)}">'
                f'Download this user\'s chat log as CSV</a></p>'
            )
        else:
            body.append('<p class="info">No chat messages.</p>')
        body.append('</section>')

    elif tab == "actions":
        actions = await queries.get_action_logs(db, user_id=user_id, action_type=action_type)

        body.append('<section><h2>Action Log</h2>')
        body.append(_action_type_filter_form(user_id, action_type))
        if actions:
            body.append(_simple_table(
                ["timestamp", "action_type", "question_number", "action_data"],
                [[_fmt_ts(a["timestamp"]), a["action_type"], a["question_number"],
                  _truncate(json.dumps(a["action_data"], default=str) if a["action_data"] else "")]
                 for a in actions],
            ))
        else:
            body.append('<p class="info">No action events logged yet.</p>')
        body.append('</section>')

    elif tab == "danger":
        body.append('<section>')
        body.append('<h3 class="danger-heading">Danger Zone</h3>')
        body.append('<p class="warning">These actions are irreversible.</p>')
        body.append(_danger_zone_forms(user_id))
        body.append('</section>')

    return _page(f"User {user_id}", "\n".join(body), active_tab="Students")


# --- Routes: user actions (POST-Redirect-GET) ---

@router.post("/user/{user_id}/prefs")
async def admin_update_prefs(user_id: str,
                              ab_group: str = Form(...),
                              hint_style_preference: str = Form(...),
                              intervention_preference: str = Form(...),
                              db: AsyncSession = Depends(get_db)):
    await queries.update_user_preferences(db, user_id, {
        "ab_group": ab_group,
        "hint_style_preference": hint_style_preference,
        "intervention_preference": intervention_preference,
    })
    return _redirect(f"/admin/user/{quote(user_id)}", f"Updated profile for {user_id}.")


@router.post("/user/{user_id}/timer/reset")
async def admin_timer_reset(user_id: str, db: AsyncSession = Depends(get_db)):
    await queries.reset_exam_timer(db, user_id)
    return _redirect(f"/admin/user/{quote(user_id)}", f"Timer reset for {user_id}.")


@router.post("/user/{user_id}/timer/extend")
async def admin_timer_extend(user_id: str, extra_minutes: int = Form(...), db: AsyncSession = Depends(get_db)):
    await queries.extend_exam_timer(db, user_id, extra_minutes)
    word = "Added" if extra_minutes >= 0 else "Removed"
    return _redirect(f"/admin/user/{quote(user_id)}", f"{word} {abs(extra_minutes)} min for {user_id}.")


@router.post("/user/{user_id}/session-lock/clear")
async def admin_clear_lock(user_id: str, db: AsyncSession = Depends(get_db)):
    await queries.clear_session_lock(db, user_id)
    return _redirect(f"/admin/user/{quote(user_id)}", f"Session lock cleared for {user_id}.")


@router.post("/user/{user_id}/question/unlock")
async def admin_unlock_question(user_id: str, question_id: int = Form(...), db: AsyncSession = Depends(get_db)):
    voided = await queries.void_question_attempts(db, user_id, question_id)
    if voided:
        msg = f"Unlocked question {question_id} for {user_id} ({voided} attempt row(s) voided)."
    else:
        msg = f"No attempt rows found to void for question {question_id} - nothing was unlocked."
    return _redirect(f"/admin/user/{quote(user_id)}?tab=manage", msg)


@router.post("/user/{user_id}/progress/reset")
async def admin_reset_progress(user_id: str, confirm_token: str = Form(...), db: AsyncSession = Depends(get_db)):
    if confirm_token != user_id:
        return _confirm_mismatch_response(user_id, "Reset Progress")
    await queries.reset_user_progress(db, user_id)
    return _redirect(f"/admin/user/{quote(user_id)}", f"Reset progress for {user_id}.")


@router.post("/user/{user_id}/delete")
async def admin_delete_user(user_id: str, confirm_token: str = Form(...), db: AsyncSession = Depends(get_db)):
    if confirm_token != user_id:
        return _confirm_mismatch_response(user_id, "Delete User")
    await queries.delete_user(db, user_id)
    return _redirect("/admin/students", f"Deleted user {user_id}.")


@router.post("/exam/extend-all")
async def admin_extend_all(extra_minutes: int = Form(...), db: AsyncSession = Depends(get_db)):
    affected = await queries.extend_all_exam_timers(db, extra_minutes)
    word = "Added" if extra_minutes >= 0 else "Removed"
    return _redirect("/admin/", f"{word} {abs(extra_minutes)} min for {affected} unsubmitted session(s).")


@router.post("/settings/llm-caps")
async def admin_set_llm_caps(global_cap: int = Form(...), user_cap: int = Form(...), db: AsyncSession = Depends(get_db)):
    await set_cap_override(db, CAP_GLOBAL_KEY, global_cap)
    await set_cap_override(db, CAP_USER_KEY, user_cap)
    await db.commit()
    return _redirect("/admin/", f"LLM caps updated: global={global_cap}, per-user={user_cap}.")


@router.post("/settings/llm-caps/clear")
async def admin_clear_llm_caps(db: AsyncSession = Depends(get_db)):
    await set_cap_override(db, CAP_GLOBAL_KEY, None)
    await set_cap_override(db, CAP_USER_KEY, None)
    await db.commit()
    return _redirect("/admin/", "LLM caps reset to .env values.")


# --- Routes: export ---

@router.get("/export", response_class=HTMLResponse)
async def admin_export_form(db: AsyncSession = Depends(get_db)):
    user_ids = await queries.get_all_user_ids(db)
    user_options = "".join(f'<option value="{html.escape(u)}">{html.escape(u)}</option>' for u in user_ids)
    log_type_options = "".join(f'<option value="{html.escape(t)}">{html.escape(t)}</option>' for t in LOG_TYPE_OPTIONS)
    action_type_options = "".join(f'<option value="{html.escape(a)}">{html.escape(a)}</option>' for a in ACTION_TYPES)
    body = f"""
    <h1>Export Data</h1>
    <p class="caption">Filter and export any combination of logs as CSV.</p>
    <form method="get" action="/admin/export/download" class="form-grid">
      <label>User scope
        <select name="user_id"><option value="">All Users</option>{user_options}</select>
      </label>
      <label>Log type <select name="log_type">{log_type_options}</select></label>
      <label>From date (optional) <input type="date" name="date_from"></label>
      <label>To date (optional) <input type="date" name="date_to"></label>
      <label>Action type filter (Action Logs only)
        <select name="action_type"><option value="">All action types</option>{action_type_options}</select>
      </label>
      <label><input type="checkbox" name="hint_only" value="1"> Only rows where hint was shown (Interaction Logs only)</label>
      <label>Correct filter (Interaction Logs only)
        <select name="correct_filter">
          <option value="all">All</option>
          <option value="correct">Correct only</option>
          <option value="incorrect">Incorrect only</option>
        </select>
      </label>
      <button type="submit">Download CSV</button>
    </form>
    """
    return _page("Export Data", body)


def _parse_date(value: str | None) -> datetime.date | None:
    if not value:
        return None
    try:
        return datetime.date.fromisoformat(value)
    except ValueError:
        return None


def _export_cell(value):
    if isinstance(value, (dict, list)):
        return json.dumps(value, default=str)
    return value


async def _load_export_rows(db: AsyncSession, log_type: str, user_id: str | None, action_type: str | None):
    if log_type == "Chat Logs":
        return await queries.get_chat_logs(db, user_id=user_id)
    if log_type == "Intervention Logs":
        return await queries.get_intervention_logs(db, user_id=user_id)
    if log_type == "Action Logs":
        return await queries.get_action_logs(db, user_id=user_id, action_type=action_type)
    return await queries.get_all_interaction_logs(db, user_id=user_id)


@router.api_route("/export/download", methods=["GET", "POST"])
async def admin_export_download(request: Request, db: AsyncSession = Depends(get_db)):
    params = await request.form() if request.method == "POST" else request.query_params

    log_type = params.get("log_type") or "Interaction Logs"
    if log_type not in EXPORT_COLUMNS:
        log_type = "Interaction Logs"
    user_id = params.get("user_id") or None
    action_type = params.get("action_type") or None
    date_from = _parse_date(params.get("date_from"))
    date_to = _parse_date(params.get("date_to"))
    hint_only = params.get("hint_only") in ("1", "true", "on")
    correct_filter = params.get("correct_filter") or "all"

    rows = await _load_export_rows(db, log_type, user_id, action_type)

    if log_type == "Interaction Logs":
        if hint_only:
            rows = [r for r in rows if r["hint_shown"]]
        if correct_filter == "correct":
            rows = [r for r in rows if r["is_correct"]]
        elif correct_filter == "incorrect":
            rows = [r for r in rows if not r["is_correct"]]

    if date_from:
        rows = [r for r in rows if r["timestamp"] and r["timestamp"].date() >= date_from]
    if date_to:
        rows = [r for r in rows if r["timestamp"] and r["timestamp"].date() <= date_to]

    columns = EXPORT_COLUMNS[log_type]

    def _generate():
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(columns)
        yield buf.getvalue()
        buf.seek(0)
        buf.truncate(0)
        for row in rows:
            writer.writerow([_export_cell(row.get(c)) for c in columns])
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate(0)

    filename = log_type.lower().replace(" ", "_")
    if user_id:
        filename += f"_{user_id}"
    filename += ".csv"

    return StreamingResponse(
        _generate(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )