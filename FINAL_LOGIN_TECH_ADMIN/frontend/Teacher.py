"""
Teacher.py - Centrum Laboratory | Teacher dashboard (Streamlit)

The screens keep the look of the original teacher HTML design (same sidebar,
dashboard cards, 3-step "Report an Issue" form with issue chips, My Reports
table, Unit Inventory and Settings) and are built in Python with Streamlit -
no HTML file or iframe. The shared pieces are in frontend/ui.py and the
design's stylesheet is in frontend/design.py.

Note: the backend has no teacher endpoints yet, so reports sent here, the
contact number and the notification switches are kept for this browser
session only (the original HTML design worked the same way). When the backend
gets e.g. POST /teacher/reports, call it from _submit() below.

How it is opened (app.py):

    import Teacher
    Teacher.render(user)

Just to look at it (no login needed), from the project root:

       streamlit run Teacher.py -- --preview
"""

from __future__ import annotations

import re
import sys
from datetime import datetime

import streamlit as st

from frontend import ui

ROLE = "Teacher"
P = "teacher"  # session-state prefix for this dashboard
ss = st.session_state

DEMO_USER = {
    "name": "Alwyna Lopez",
    "email": "alwyna.lopez@isu.edu.ph",
    "contact_number": "0983 765 6748",
    "role": ROLE,
}

ISSUES = ui.ISSUE_TYPES
OTHER = "Other"

# Form widgets. Streamlit forgets hidden widgets, so their values are copied
# into a draft while the Review step is shown, and put back for "Edit".
_F_ROOM, _F_UNIT, _F_OTHER, _F_COMMENT = (f"{P}_f_{k}" for k in ("room", "unit", "other", "comment"))
_SELECTED = f"{P}_issues"  # chosen issue chips (plain session value, not a widget)


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
def _data(user: dict) -> dict:
    if f"{P}_data" not in ss:
        ss[f"{P}_data"] = {"lab": ui.sample_lab(), "reports": ui.sample_teacher_reports(user["name"])}
    return ss[f"{P}_data"]


# ---------------------------------------------------------------------------
# Report an issue: callbacks
# ---------------------------------------------------------------------------
def _issue_list(selected: list[str], other: str) -> list[str]:
    issues = [i for i in ISSUES if i in selected]
    if OTHER in selected:
        issues += [s.strip() for s in (other or "").split(",") if s.strip()]
    return issues


def _toggle_issue(issue: str) -> None:
    chosen = list(ss.get(_SELECTED, []))
    if issue in chosen:
        chosen.remove(issue)
        if issue == OTHER:
            ss[_F_OTHER] = ""
    else:
        chosen.append(issue)
    ss[_SELECTED] = chosen


def _reset_form() -> None:
    for key in (_F_ROOM, _F_UNIT, _F_OTHER, _F_COMMENT, _SELECTED, f"{P}_draft", f"{P}_done_id"):
        ss.pop(key, None)
    ss[f"{P}_step"] = 1


def _to_review() -> None:
    selected = list(ss.get(_SELECTED, []))
    ss[f"{P}_draft"] = {
        "room": ss.get(_F_ROOM), "unit": ss.get(_F_UNIT), "other": ss.get(_F_OTHER) or "",
        "comment": (ss.get(_F_COMMENT) or "").strip(),
        "issues": _issue_list(selected, ss.get(_F_OTHER) or ""), "when": datetime.now(),
    }
    ss[f"{P}_step"] = 2


def _back_to_edit() -> None:
    d = ss.get(f"{P}_draft") or {}
    ss[_F_ROOM], ss[_F_UNIT] = d.get("room"), d.get("unit")
    ss[_F_OTHER], ss[_F_COMMENT] = d.get("other", ""), d.get("comment", "")
    ss[f"{P}_step"] = 1


def _submit(user_name: str) -> None:
    d = ss.get(f"{P}_draft")
    if not d:
        return _reset_form()
    reports = ss[f"{P}_data"]["reports"]
    numbers = [int(m.group(1)) for r in reports if (m := re.search(r"(\d+)$", r["id"]))]
    code = f"CL-{max(numbers, default=1042) + 1}"
    reports.insert(0, ui.make_report(code, user_name, d["room"], d["unit"], d["issues"], d["comment"],
                                     "progress", "", datetime.now()))
    ss[f"{P}_done_id"] = code
    ss[f"{P}_step"] = 3
    ui.flash(P, f"Report {code} submitted")


def _new_report() -> None:
    _reset_form()


def _view_mine() -> None:
    _reset_form()
    ui.go(P, "myreports")


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------
def _dashboard(lab: ui.Lab, reports: list[dict]) -> None:
    ui.page_header("Overview", "Dashboard")
    count = lambda s: sum(r["status"] == s for r in reports)  # noqa: E731
    ui.stat_row([
        ("My Reports", len(reports), "all-time submissions", "blue", "doc"),
        ("Being Fixed (in progress)", count("progress"), "awaiting a fix", "amber", "clock"),
        ("Resolved", count("resolved"), "issues fixed", "green", "check"),
        ("Needs Follow-Up", count("followup"), "repeat or unresolved", "red", "flag"),
    ])
    ui.recent_activity(P, reports, ui.TEACHER_STATUS, lambda _rid: ui.go(P, "myreports"), show_teacher=False,
                       button=("View My Reports", ui.go, (P, "myreports")))
    ui.room_glance(P, lab, button=("View Inventory", ui.go, (P, "inventory")))


def _wizard_steps(step: int) -> None:
    parts = []
    for n, label in ((1, "Describe the issue"), (2, "Review"), (3, "Done")):
        state = "done" if n < step else "current" if n == step else ""
        if n > 1:
            parts.append('<div class="wz-line"></div>')
        parts.append(f'<div class="wz-step {state}"><div class="wz-num">{n}</div>'
                     f'<div class="wz-step-label">{label}</div></div>')
    ui.html(f'<div class="wizard-steps">{"".join(parts)}</div>')


def _report_form(lab: ui.Lab) -> None:
    with ui.box(f"{P}_form", "card", "formcard"):
        a, b = st.columns(2, gap="small")
        with a:
            ui.field_label("Room")
            if ss.get(_F_ROOM) not in lab.rooms:
                ss.pop(_F_ROOM, None)
            room = st.selectbox("Room", lab.rooms, format_func=ui.room_label, key=_F_ROOM,
                                placeholder="Select a room", label_visibility="collapsed",
                                **({} if _F_ROOM in ss else {"index": None}))
        with b:
            ui.field_label("Computer unit")
            units = list(range(1, lab.counts.get(room, 0) + 1)) if room else []
            if ss.get(_F_UNIT) not in units:
                ss.pop(_F_UNIT, None)
            unit = st.selectbox("Computer unit", units, format_func=ui.unit_label, key=_F_UNIT, disabled=not room,
                                placeholder="Select a unit" if room else "Select a room first",
                                label_visibility="collapsed", **({} if _F_UNIT in ss else {"index": None}))
        ui.html('<div style="height:20px"></div>')

        ui.field_label("Issue type", ' &nbsp;<span style="font-weight:400;color:var(--ink-300);">'
                                     '(select all that apply)</span>')
        selected = list(ss.get(_SELECTED, []))
        with ui.box(f"{P}_chips", "chips"):
            for issue in ISSUES + [OTHER]:
                on = issue in selected
                kind = ("chipotheron" if on else "chipother") if issue == OTHER else ("chipon" if on else "chip")
                ui.btn(issue, f"{P}_chip_{ISSUES.index(issue) if issue in ISSUES else 'other'}", kind,
                       on_click=_toggle_issue, args=(issue,))
        other = ""
        if OTHER in selected:
            ui.html('<div style="height:12px"></div>')
            ui.field_label("Describe the other issue(s)")
            other = st.text_input("Describe the other issue(s)", key=_F_OTHER, label_visibility="collapsed",
                                  placeholder="e.g. sticky spacebar, cracked casing")
            ui.html('<div class="helptext">Separate more than one with a comma.</div>')
        ui.html('<div style="height:20px"></div>')

        ui.field_label("Comment", ' &nbsp;<span style="font-weight:400;color:var(--ink-300);">(optional)</span>')
        st.text_area("Comment", key=_F_COMMENT, label_visibility="collapsed",
                     placeholder="Add any extra detail that could help the technician — when it started, "
                                 "what you were doing, etc.")
        ui.html('<div class="helptext" style="margin-top:14px;">Your name and the date &amp; time are added '
                'automatically when you submit.</div>')

        ready = bool(room and unit and _issue_list(selected, other))
        with ui.box(f"{P}_form_foot", "rowend", "footerline"):
            ui.btn("Discard", f"{P}_discard1", "ghost", on_click=_reset_form)
            ui.btn("Review report", f"{P}_review", "primary", disabled=not ready, on_click=_to_review)


def _report_review(user: dict) -> None:
    d = ss.get(f"{P}_draft") or {}
    with ui.box(f"{P}_review_card", "card", "formcard"):
        issues = "".join(f'<span class="issue-tag">{ui.h(i)}</span>' for i in d.get("issues", []))
        room = d.get("room") or ""
        rows = [
            ("Reported by", ui.h(user["name"])),
            ("Date &amp; time", ui.h(ui.fmt_dt(d.get("when")))),
            ("Room", f"Centrum Laboratory {ui.h(room.split(' ')[-1])}"),
            ("Computer unit", ui.unit_label(d.get("unit") or 0)),
            ("Issue type(s)", f'<div class="review-chips">{issues}</div>'),
            ("Comment", ui.h(d.get("comment")) or "&mdash;"),
        ]
        note_icon = ui.icon("info", 15, extra='style="flex:0 0 15px;margin-top:1px;"')
        ui.html("".join(f'<div class="review-row"><div class="review-label">{label}</div>'
                        f'<div class="review-value">{value}</div></div>' for label, value in rows)
                + f'<div class="review-note">{note_icon}'
                  '<div>Once submitted, this report can\'t be edited or deleted. The technician will pick it up '
                  'from here.</div></div>')
        with ui.box(f"{P}_review_foot", "rowend", "footerline"):
            ui.btn("Discard", f"{P}_discard2", "dghost", on_click=_reset_form)
            ui.btn("Edit", f"{P}_edit", "ghost", on_click=_back_to_edit)
            ui.btn("Confirm & submit", f"{P}_submit", "primary", on_click=_submit, args=(user["name"],))


def _report_done() -> None:
    with ui.box(f"{P}_done_card", "card", "confirmcard"):
        ui.html(f'<div class="confirm-wrap" style="padding-bottom:18px;"><div class="confirm-icon">'
                f'{ui.icon("check", 26, 2.5)}</div><div style="margin:0 0 8px;font-size:19px;font-weight:700;">'
                f'Report submitted</div><p style="color:var(--ink-500);font-size:13.5px;margin:0;">Report '
                f'<span class="confirm-id">{ui.h(ss.get(f"{P}_done_id", "CL-0000"))}</span> is now in the '
                f'technician\'s queue. You\'ll see its status update in My Reports.</p></div>')
        with ui.box(f"{P}_done_btns", "rowcenter"):
            ui.btn("Report another issue", f"{P}_another", "ghost", on_click=_new_report)
            ui.btn("View my reports", f"{P}_view_mine", "primary", on_click=_view_mine)
        ui.html('<div style="height:40px"></div>')


def _report_page(lab: ui.Lab, user: dict) -> None:
    ui.page_header("Reporting", "Report an Issue", "Tell us what's wrong — the technician gets notified right away.")
    step = ss.setdefault(f"{P}_step", 1)
    _wizard_steps(step)
    if step == 2:
        _report_review(user)
    elif step == 3:
        with st.container(key=f"{P}_done_wrap"):
            _report_done()
    else:
        _report_form(lab)


def _my_reports(reports: list[dict]) -> None:
    ui.page_header("Reporting", "My Reports",
                   "Reports you've sent. You can track their status here — the technician handles the fix.")
    with ui.box(f"{P}_mine_tb", "rowbetween", "mb16"):
        with ui.box(f"{P}_mine_tbl", "row"):
            q = st.text_input("Search", placeholder="Search room, unit, or issue", label_visibility="collapsed",
                              key=ui.sticky(f"{P}_mine_q__search__"))
            ui.html('<div class="sortby">Sort by</div>')
            sort = st.selectbox("Sort by", list(ui.SORTS), format_func=ui.SORTS.get, label_visibility="collapsed",
                                key=ui.sticky(f"{P}_mine_sort__fselsm__"))
            ui.remember(f"{P}_mine_q__search__")
            ui.remember(f"{P}_mine_sort__fselsm__")
        count_slot = st.empty()

    q = (q or "").strip().lower()
    shown = ui.sort_reports(
        [r for r in reports
         if not q or q in f"{r['room']} {ui.unit_label(r['unit'])} {' '.join(r['issues'])}".lower()], sort)
    with count_slot:
        ui.html(f'<div class="count-badge"><b>{len(shown)}</b> reports</div>')

    if shown:
        rows = "".join(
            f'<tr style="cursor:default;"><td class="rep-id">{ui.h(r["id"])}</td>'
            f'<td><div class="rep-unit">{ui.h(r["room"])} &mdash; {ui.unit_label(r["unit"])}</div></td>'
            f'<td>{ui.issue_tags(r["issues"])}</td><td>{ui.report_pill(r["status"], ui.TEACHER_STATUS)}</td>'
            f'<td style="white-space:nowrap;color:var(--ink-500);">{ui.h(r["date"])}</td></tr>' for r in shown)
        body = (f'<table class="reports-table"><thead><tr><th>Report ID</th><th>Room / Unit</th><th>Issue type(s)</th>'
                f'<th>Status</th><th>Date &amp; time</th></tr></thead><tbody>{rows}</tbody></table>')
    else:
        body = (f'<div class="empty-state">{ui.icon("doc", 34, 1.6)}<div>No reports match your search.</div></div>')
    ui.html(f'<div class="card" style="overflow:hidden;">{body}</div>')


def _save_number(number: str) -> tuple[bool, str]:
    ui.set_contact_number(number)
    return True, "Contact number updated"


def _change_password(current: str, new: str) -> tuple[bool, str]:
    return False, ("Teacher passwords can't be changed here yet. Log out and use "
                   "\"Forgot password?\" on the login screen.")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def render(user: dict | None = None) -> None:
    """Draw the Teacher dashboard for `user` (a dict from your login)."""
    ui.page_config(ROLE)
    user = ui.require_user(user, ROLE, (ROLE.lower(),))
    data = _data(user)
    lab, reports = data["lab"], data["reports"]

    groups = [
        ("OVERVIEW", [("dashboard", "Dashboard", "clockcircle", None)]),
        ("REPORTING", [("report", "Report an Issue", "plus", None), ("myreports", "My Reports", "doc", None)]),
        ("ASSETS", [("inventory", "Unit Inventory", "monitor", None)]),
        ("SYSTEM", [("settings", "Settings", "gear", None)]),
    ]
    ui.shell(P, ROLE, groups, user)
    ui.show_flash(P)

    with st.container(key="cl_content"):
        page = ui.current_page(P)
        if page == "report":
            _report_page(lab, user)
        elif page == "myreports":
            _my_reports(reports)
        elif page == "inventory":
            ui.inventory_page(P, lab, "Tap a unit to see its full hardware, software, and maintenance history.",
                              tabs=("hardware", "software", "history"))
        elif page == "settings":
            ui.settings_page(
                P, user, profile_style="teacher",
                notif_intro="Choose how you want to hear about updates on your reports.",
                notifications=[
                    ("Report status updates", "Get notified when a technician starts or finishes fixing your report.", True),
                    ("Follow-up flags", "Get notified if a unit you reported is flagged for repeated issues.", True),
                    ("Email notifications", "Send the above updates to your email as well as in-app.", False),
                    ("Weekly summary", "A Monday recap of all your open and resolved reports.", False),
                ],
                save_number=_save_number, change_password=_change_password)
        else:
            _dashboard(lab, reports)


# ---------------------------------------------------------------------------
# `streamlit run Teacher.py -- --preview`
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    preview = "--preview" in sys.argv[1:]
    current = ui.session_user()
    if current is None and preview:
        ui.preview_logged_out()
        current = DEMO_USER
    if current is None:
        st.warning("You're not signed in. Log in from the main app first, or preview this "
                   "page with:  streamlit run Teacher.py -- --preview")
        st.stop()
    render(current)
