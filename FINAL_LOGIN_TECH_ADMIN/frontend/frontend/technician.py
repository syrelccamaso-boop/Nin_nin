"""
frontend/technician.py - Centrum Laboratory | Technician dashboard (Streamlit)

The screens keep the look of the original technician HTML design (same
sidebar, cards, table, report drawer...) and are built in Python with
Streamlit - no HTML file or iframe. The shared pieces are in frontend/ui.py and
the design's stylesheet is in frontend/design.py.

This file contains UI code only. Every read and write goes through
frontend/backend_client.py -> FastAPI (backend/main.py) ->
backend/technician_service.py -> backend/database.py (Supabase).

How it is opened
----------------
app.py opens it after a successful login when the user's role (from
auth_service / Users.RoleId) is Technician:

    from frontend import technician
    technician.render(user)

Pages
-----
Dashboard, Reports (resolve / flag for follow-up with a note), Unit Inventory,
Error Analytics, Escalation (status is saved), Settings (contact number and
password are saved). Live data is loaded once and kept in the session; it is
loaded again after every change, or with "Refresh data" in the user menu.

Just to look at it (sample data, no login needed), from the project root:

       python -m streamlit run frontend/technician.py -- --preview
"""

from __future__ import annotations

import sys

import streamlit as st

from frontend import backend_client
from frontend import ui

ROLE = "Technician"
P = "tech"  # session-state prefix for this dashboard
ss = st.session_state

DEMO_USER = {
    "name": "Jherome Domingo",
    "email": "jherome.domingo@isu.edu.ph",
    "contact_number": "0917 123 4567",
    "role": ROLE,
}


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
def _fetch(token: str | None, preview: bool) -> dict:
    """{lab, reports, live, notice}"""
    sample = {"lab": ui.sample_lab(), "reports": ui.sample_reports(), "live": False}
    if preview:
        return {**sample, "notice": ""}
    if not token:
        return {**sample, "notice": "Showing sample data - please log out and log in again to load live data."}
    result = backend_client.get_technician_data(token)
    if not result.get("success"):
        return {**sample, "notice": f"Showing sample data - {result.get('error') or 'could not load live data.'}"}
    reports = [ui.report_from_backend(r) for r in result.get("reports") or []]
    return {"lab": ui.live_lab(result.get("units") or [], reports), "reports": reports,
            "live": True, "notice": ""}


def _data(token: str | None, preview: bool) -> dict:
    if f"{P}_data" not in ss:
        with st.spinner("Loading lab data..."):
            ss[f"{P}_data"] = _fetch(token, preview)
    return ss[f"{P}_data"]


def _reload() -> None:
    ss.pop(f"{P}_data", None)


# ---------------------------------------------------------------------------
# Actions (callbacks)
# ---------------------------------------------------------------------------
def _report_action(report: dict, status: str, note_key: str) -> None:
    note = (ss.get(note_key) or "").strip()
    if not note:
        msg = "Add a short solution note first" if status == "resolved" else "Add a short note on what was tried"
        return ui.flash(P, msg, ok=False)
    done = f"{report['id']} marked as resolved" if status == "resolved" else f"{report['id']} flagged for follow-up"

    if ss[f"{P}_data"]["live"]:
        result = backend_client.update_report_status(ss.get(ui.TOKEN_KEY), report["db_id"], status, note)
        if not result.get("success"):
            return ui.flash(P, result.get("error"), ok=False)
        ui.flash(P, result.get("message") or done)
        _reload()
    else:  # sample data: change it for this session
        report["status"], report["note"] = status, note
        ui.flash(P, done)
    ss.pop(note_key, None)
    ui.close_report(P)


def _escalation_changed(key: str, room: str, n: int, widget: str) -> None:
    value = ss.get(widget)
    data = ss[f"{P}_data"]
    if data["live"]:
        result = backend_client.set_escalation_status(ss.get(ui.TOKEN_KEY), room, n, value)
        if not result.get("success"):
            ss.pop(widget, None)  # show the saved value again
            return ui.flash(P, result.get("error"), ok=False)
        ui.flash(P, result.get("message") or "Escalation status updated")
    else:
        ui.flash(P, "Escalation status updated")
    data["lab"].escalation[key] = value


def _save_number(number: str) -> tuple[bool, str]:
    if not ss[f"{P}_data"]["live"]:
        ui.set_contact_number(number)
        return True, "Number updated (sample data)"
    result = backend_client.update_contact_number(ss.get(ui.TOKEN_KEY), number)
    if not result.get("success"):
        return False, result.get("error")
    saved = result.get("user") if isinstance(result.get("user"), dict) else {}
    ui.set_contact_number(saved.get("contact_number", number))
    return True, result.get("message") or "Number updated"


def _change_password(current: str, new: str) -> tuple[bool, str]:
    if not ss[f"{P}_data"]["live"]:
        return True, "Password updated (sample data - nothing was saved)"
    result = backend_client.change_password(ss.get(ui.TOKEN_KEY), current, new)
    if not result.get("success"):
        return False, result.get("error")
    return True, result.get("message") or "Password updated"


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------
def _dashboard(lab: ui.Lab, reports: list[dict]) -> None:
    ui.page_header("Overview", "Dashboard", "A snapshot of what needs your attention across all four labs.")
    count = lambda s: sum(r["status"] == s for r in reports)  # noqa: E731
    ui.stat_row([
        ("Total Reports", len(reports), f"across all {len(lab.rooms)} labs", "blue", "doc"),
        ("In Progress", count("progress"), "being worked on", "amber", "clock"),
        ("Resolved", count("resolved"), "issues fixed", "green", "check"),
        ("Needs Follow-Up", count("followup"), "repeat or unresolved", "red", "flag"),
    ])
    ui.recent_activity(P, reports, ui.REPORT_STATUS, lambda rid: ui.open_report(P, rid), show_teacher=True,
                       button=("View All Reports", ui.go, (P, "reports")))
    ui.room_glance(P, lab, button=("View Inventory", ui.go, (P, "inventory")))
    ui.issue_types_card(P, reports)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def render(user: dict | None = None, preview: bool = False) -> None:
    """Draw the Technician dashboard for `user` (a dict from your login)."""
    ui.page_config(ROLE)
    user = ui.require_user(user, ROLE, (ROLE.lower(),))
    data = _data(ss.get(ui.TOKEN_KEY), preview)
    lab, reports = data["lab"], data["reports"]

    open_reports = sum(r["status"] in ("progress", "followup") for r in reports)
    groups = [
        ("OVERVIEW", [("dashboard", "Dashboard", "grid", None)]),
        ("REPORTING", [("reports", "Reports", "checklist", open_reports)]),
        ("ASSETS", [("inventory", "Unit Inventory", "monitor", None)]),
        ("INSIGHTS", [("analytics", "Error Analytics", "chart", None),
                      ("escalation", "Escalation", "warning", len(lab.escalated()))]),
        ("SYSTEM", [("settings", "Settings", "gear", None)]),
    ]
    extra = [("Refresh data", _reload, (), ":material/refresh:")] if data["live"] else []
    ui.shell(P, ROLE, groups, user, menu_extra=extra)
    ui.show_flash(P)
    ui.notice(data["notice"])

    with st.container(key="cl_content"):
        page = ui.current_page(P)
        if page == "reports":
            ui.reports_page(P, reports, lab,
                            "Update reports as you go. Resolve one and it's done \u2014 flag it for follow-up if a "
                            "fix didn't hold, or it just stays In Progress until you get to it.",
                            on_action=_report_action)
        elif page == "inventory":
            ui.inventory_page(P, lab, "Full hardware, software, and maintenance history for every unit.")
        elif page == "analytics":
            ui.analytics_page(P, lab, reports)
        elif page == "escalation":
            ui.escalation_page(P, lab, on_change=_escalation_changed)
        elif page == "settings":
            ui.settings_page(
                P, user, profile_style="staff",
                notif_intro="Choose how you want to hear about lab activity.",
                notifications=[
                    ("New report submitted", "Get notified the moment a teacher reports an issue in any room.", True),
                    ("Unit escalated", "Get notified when a unit hits the 5-report escalation threshold.", True),
                    ("Email notifications", "Send the above updates to your email as well as in-app.", False),
                    ("Weekly summary", "A Monday recap of unresolved reports and flagged units.", True),
                ],
                save_number=_save_number, save_email=None,
                email_message="To change your email, please contact the administrator.",
                change_password=_change_password)
        else:
            _dashboard(lab, reports)


# ---------------------------------------------------------------------------
# `python -m streamlit run frontend/technician.py -- --preview`
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    preview = "--preview" in sys.argv[1:]
    current = ui.session_user()
    if current is None and preview:
        ui.preview_logged_out()
        current = DEMO_USER
    if current is None:
        st.warning("You're not signed in. Log in from the main app first, or preview this "
                   "page with:  python -m streamlit run frontend/technician.py -- --preview")
        st.stop()
    render(current, preview=preview)
