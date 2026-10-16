"""
Teacher.py - Centrum Laboratory | Teacher dashboard (Streamlit)

Data flow:
    Streamlit frontend
        -> backend_client
        -> FastAPI / teacher_service.py
        -> Supabase PostgreSQL

Pages
-----
Dashboard          stats, my recent reports, laboratory status
Report an Issue    1 Laboratory (map or list) -> 2 Computer -> 3 Problem
                   (Hardware / Software first, then the specific problem,
                   optional details, urgency) -> 4 Review -> sent
My Reports         filter chips, Sort by, report details
                   - Follow up   (report still "Reported" after FOLLOW_UP_AFTER_HOURS)
                   - Edit        (while still "Reported", reason required)
                   - Cancel      (while still "Reported", reason required)
Laboratory Status  live floor map; click a computer to see it and report it
My Profile         contact number, my activity, deactivate my account, log out

Centrum Assistant  the floating robot button (bottom right, every page) opens a
                   chat window (chatbot.py).

ReportStatus database mapping:
    1 = Reported
    2 = Under repair
    3 = Fixed
    4 = Escalated
    5 = Follow Up
    6 = Cancelled      <- new row needed in the ReportStatus table

Urgency: the backend report call only takes computer_id / issues / comment, so a
"High" urgency is stored as a tag at the start of the comment
(see _URGENCY_TAG) and read back in _report_from_db().

Same-day rule (frontend only): the same computer can't be reported for the same
problem twice on the same day. The teacher is told to report it again tomorrow
if the problem comes back. This keeps a unit from being flagged too quickly.

Backend calls used by the new features (see _call); until they exist in
backend_client.py the buttons show "not connected to the server yet":
    backend_client.follow_up_teacher_report(token, report_id=..., message=...)
    backend_client.update_teacher_report(token, report_id=..., issues=[...], comment=..., reason=...)
    backend_client.cancel_teacher_report(token, report_id=..., reason=...)
    backend_client.deactivate_my_account(token, reason=...)
"""

from __future__ import annotations

import re

import streamlit as st

from . import backend_client
from . import chatbot
from . import lab_data as D
from . import portal
from . import ui
from .portal import badge, empty, ic, lab_tile, row, sort_select, stat


ROLE = "Teacher"
P = "teacher"
ss = st.session_state

PAGES = [
    ("dashboard", "Dashboard", "home"),
    ("report", "Report an Issue", "plus"),
    ("reports", "My Reports", "list"),
    ("labs", "Laboratory Status", "map"),
    ("profile", "My Profile", "user"),
]

SHELL = portal.Shell(P, ROLE, PAGES)
go, open_modal, close_modal, toast = SHELL.go, SHELL.open_modal, SHELL.close_modal, SHELL.toast

html, btn, hit, box, h = ui.html, ui.btn, ui.hit, ui.box, ui.h

STEPS = [("lab", "Laboratory"), ("pc", "Computer"), ("problem", "Problem"), ("review", "Review")]
URGENCY = [("Normal", "Normal"), ("High", "High — class is using it now")]
_DESC = f"{P}_r_desc"
_URGENCY_TAG = "[HIGH - class is using it now]"
_ISSUE_TAG_START = "[ISSUE: "
_ISSUE_TAG_RE = re.compile(r"^\[ISSUE:\s*([^|\]]+)\|\s*([^\]]+)\]")

# Hardware / Software problem lists (edit these to match your lab).
CATEGORIES = [
    ("Hardware", "Hardware", "The computer or its parts: power, monitor, keyboard, mouse, cables"),
    ("Software", "Software", "Programs, Windows, accounts, viruses, network settings"),
]
HARDWARE_ISSUES = [
    "Won't turn on / no power",
    "No display / black screen",
    "Monitor problem (flicker, lines)",
    "Keyboard not working",
    "Mouse not working",
    "No internet (cable / port)",
    "Overheating / loud noise",
    "Other hardware problem",
]
SOFTWARE_ISSUES = [
    "Very slow / freezing",
    "Won't start Windows / stuck loading",
    "Program missing or won't open",
    "Can't log in to the computer",
    "Virus or pop-ups",
    "No internet (network settings)",
    "Error message keeps showing",
    "Other software problem",
]
ISSUES = {"Hardware": HARDWARE_ISSUES, "Software": SOFTWARE_ISSUES}

# A report that is still "Reported" (nobody picked it up) after this many hours
# can be followed up. One follow-up per report per day.
FOLLOW_UP_AFTER_HOURS = 48
FOLLOW_UP_EVERY_HOURS = 24

MIN_REASON = 5


# ===========================================================================
# Report status
# ===========================================================================
_STATUS_ID_MAP = {1: "reported", 2: "repair", 3: "fixed", 4: "escalated", 5: "followup", 6: "cancelled"}

_STATUS_TEXT = {
    "reported": {"reported", "report", "pending", "open", "waiting", "waiting for a technician"},
    "repair": {"under repair", "under_repair", "repair", "in repair", "being repaired", "progress", "in progress"},
    "fixed": {"fixed", "fix", "resolved", "complete", "completed"},
    "escalated": {"escalated", "escalate", "escalation"},
    "followup": {"follow up", "follow-up", "followup", "follow_up"},
    "cancelled": {"cancelled", "canceled", "cancel"},
}

_STATUS_LABELS = {
    "reported": "Reported",
    "repair": "Under repair",
    "fixed": "Fixed",
    "escalated": "Escalated",
    "followup": "Follow Up",
    "cancelled": "Cancelled",
}

_OPEN_STATUSES = {"reported", "repair", "followup", "escalated"}


def _normalize_report_status(value) -> str | None:
    """Turn a database/backend status value into the internal status key."""
    text = str(value).strip().lower() if value is not None else ""
    if not text:
        return None
    for key, names in _STATUS_TEXT.items():
        if text in names:
            return key
    return None


def _status_from_report(r: dict) -> str:
    """CurrentStatus text first, then StatusId, then 'reported'."""
    for name in ("current_status", "CurrentStatus", "status_name", "StatusName",
                 "status_text", "StatusText", "status", "Status"):
        normalized = _normalize_report_status(r.get(name))
        if normalized:
            return normalized

    status_id = r.get("status_id") if r.get("status_id") is not None else r.get("StatusId")
    try:
        status_id = int(status_id)
    except (TypeError, ValueError):
        status_id = None
    return _STATUS_ID_MAP.get(status_id, "reported")


def _status_label(status: str) -> str:
    return _STATUS_LABELS.get(status, "Reported")


def _status_is_open(status: str) -> bool:
    """Follow Up and Escalated stay open: the issue is not Fixed yet. Cancelled is closed."""
    return status in _OPEN_STATUSES


def _badge(status: str) -> str:
    """portal.badge() plus a grey badge for Cancelled."""
    if status == "cancelled":
        return ('<span class="badge" style="background:rgba(120,130,145,.16);color:#6b7280">'
                "Cancelled</span>")
    return badge(status)


# ===========================================================================
# Small helpers
# ===========================================================================
def _call(name: str, *args, **kwargs) -> dict:
    """Call backend_client.<name> if it exists; never crash the page."""
    fn = getattr(backend_client, name, None)
    if fn is None:
        return {"success": False, "offline": True, "error": "This feature isn't connected to the server yet."}
    try:
        return fn(*args, **kwargs) or {}
    except Exception as exc:  # network / server problems
        return {"success": False, "error": f"Could not reach the server: {exc}"}


def _hours_since(dt) -> float:
    if dt is None:
        return 0.0
    try:
        return (D.now() - dt).total_seconds() / 3600
    except Exception:
        return 0.0


def _is_today(dt) -> bool:
    if dt is None:
        return False
    try:
        return dt.date() == D.now().date()
    except Exception:
        return False


def _category_of(issue: str) -> str | None:
    if issue in SOFTWARE_ISSUES:
        return "Software"
    if issue in HARDWARE_ISSUES:
        return "Hardware"
    return None


def _is_other(issue: str | None) -> bool:
    return bool(issue) and (issue == "Other" or issue.startswith("Other "))


def _compose_comment(desc: str, urgency: str, issue: str | None = None, cat: str | None = None) -> str:
    """Comment sent to the backend: [urgency tag] [issue tag] details.

    The issue tag is only added when the problem name isn't in the ReportIssues
    table yet (see _submit); it keeps the real problem so the app can show it.
    """
    parts = []
    if urgency == "High":
        parts.append(_URGENCY_TAG)
    if issue:
        parts.append(f"{_ISSUE_TAG_START}{cat or _category_of(issue) or 'Other'} | {issue}]")
    desc = (desc or "").strip()
    if desc:
        parts.append(desc)
    return " ".join(parts)


def _read_issue_tag(comment: str) -> tuple[str | None, str | None, str]:
    """Pull '[ISSUE: Hardware | Mouse not working]' off the front of a comment."""
    m = _ISSUE_TAG_RE.match(comment or "")
    if not m:
        return None, None, comment
    return m.group(1).strip(), m.group(2).strip(), comment[m.end():].strip()


def _issue_missing(result: dict) -> bool:
    """True when the backend refused the report because the problem name isn't in ReportIssues."""
    err = str(result.get("error") or result.get("detail") or "").lower()
    return "reportissues" in err or "does not exist" in err


def _fallback_issue() -> str:
    """A problem name that already exists in the ReportIssues table."""
    names = list(getattr(D, "ISSUES", []) or [])
    if "Other" in names or not names:
        return "Other"
    return names[-1]


def _reload() -> None:
    """Drop cached data so the next run fetches it again (no toast)."""
    ss.pop(f"{P}_data", None)


# ---------------------------------------------------------------------------
# Changes saved on this computer only (until the backend has the endpoints)
# ---------------------------------------------------------------------------
_LOCAL = f"{P}_local_changes"


def _save_local(rid: str, **changes) -> None:
    ss.setdefault(_LOCAL, {}).setdefault(rid, {}).update(changes)


def _apply_local(r: dict) -> dict:
    ch = ss.get(_LOCAL, {}).get(r["id"])
    if not ch:
        return r
    if ch.get("issue"):
        r["issue"] = r["first_issue"] = ch["issue"]
        r["cat"] = _category_of(ch["issue"])
    for key in ("desc", "urgency", "edit_reason", "last_follow_up"):
        if key in ch:
            r[key] = ch[key]
    # A local cancel only counts while the database still says "Reported".
    if ch.get("cancelled") and r["status"] == "reported":
        r["status"] = "cancelled"
        r["cancel_reason"] = ch.get("cancel_reason", "")
        r["history"] = [r["history"][0], {"s": "cancelled", "t": ch.get("cancelled_at", r["created"]),
                                          "note": f"You cancelled this report — {r['cancel_reason']}"}]
    return r


# ===========================================================================
# Data
# ===========================================================================
def _token() -> str | None:
    return ss.get(ui.TOKEN_KEY)


def _fetch() -> dict:
    """Load dashboard data from the backend."""
    token = _token()
    if not token:
        return D.empty_store("Not connected — log out and log back in to load your data.")

    result = backend_client.get_teacher_dashboard(token)
    if not result.get("success"):
        return D.empty_store(f"Couldn't load data: {result.get('error') or 'unknown error'}. "
                             "Use Refresh to try again.")

    ss[f"{P}_raw_computers"] = result.get("computers") or []
    ss.pop(f"{P}_cid_map", None)
    return _build_store(result)


def _build_store(result: dict) -> dict:
    """Convert the backend dashboard response into the store the UI uses."""
    s = D.empty_store()
    s["live"] = True

    for comp in result.get("computers") or []:
        lab = D.lab_of(comp.get("Room") or comp.get("room"))
        try:
            pc = int(comp.get("UnitNumber") or comp.get("unit_number") or 0)
        except (TypeError, ValueError):
            continue
        if pc <= 0:
            continue

        hw = D.hardware_fields(comp.get("hardware") or {})
        sw = [{"name": str(i.get("SoftwareName") or i.get("software_name") or i.get("name") or ""),
               "version": str(i.get("Version") or i.get("version") or ""),
               "installed": str(i.get("DateInstalled") or i.get("date_installed") or "")}
              for i in (comp.get("software") or []) if isinstance(i, dict)]

        db_status = str(comp.get("Status") or comp.get("status") or "good").lower()
        rec_status = ("Under maintenance" if db_status == "issue"
                      else "Inactive" if db_status == "replace" else "Working")

        s["computers"][(lab, pc)] = D.new_computer(
            lab, pc, hw, sw,
            added=D.parse_dt(comp.get("CreatedAt") or comp.get("created_at")),
            status=rec_status,
        )

    reports = [_apply_local(_report_from_db(r)) for r in (result.get("reports") or []) if isinstance(r, dict)]
    # Cancelled reports are kept apart so the map and the lab counts ignore them.
    s["reports"] = [r for r in reports if r["status"] != "cancelled"]
    s["cancelled"] = [r for r in reports if r["status"] == "cancelled"]
    return s


def _report_from_db(r: dict) -> dict:
    """Convert a backend report into the structure the Teacher UI uses."""
    sent_at = D.parse_dt(r.get("created_at") or r.get("CreatedAt"))
    created = sent_at or D.now()
    status = _status_from_report(r)

    issues = r.get("issues") or r.get("Issues") or []
    if isinstance(issues, str):
        issues = [i.strip() for i in issues.split(",") if i.strip()]
    issue_str = ", ".join(str(i) for i in issues) if issues else (r.get("issue") or r.get("Issue") or "Other")
    first_issue = str(issues[0]) if issues else issue_str

    lab = D.lab_of(r.get("room") or r.get("Room"))
    try:
        pc = int(r.get("unit_number") or r.get("UnitNumber") or 0)
    except (TypeError, ValueError):
        pc = 0

    reporter = str(r.get("reporter") or r.get("ReporterName") or r.get("reporter_name") or me())

    handled_by_id = r.get("handled_by") if r.get("handled_by") is not None else r.get("HandledBy")
    tech_raw = (r.get("handled_by_name") or r.get("HandledByName")
                or r.get("technician_name") or r.get("TechnicianName") or "")
    if str(tech_raw).strip():
        tech_name = str(tech_raw).strip()
    elif handled_by_id is not None and str(handled_by_id).strip() not in ("", "0"):
        tech_name = "Unknown technician"
    else:
        tech_name = None

    resolution_note = str(r.get("resolution_note") or r.get("ResolutionNote") or "").strip()
    cancel_reason = str(r.get("cancel_reason") or r.get("CancelReason") or "").strip()
    edit_reason = str(r.get("edit_reason") or r.get("EditReason") or "").strip()
    last_follow_up = D.parse_dt(r.get("last_follow_up_at") or r.get("LastFollowUpAt"))

    comment = str(r.get("comment") or r.get("Comment") or "")
    urgency = "Normal"
    if comment.startswith(_URGENCY_TAG):
        urgency = "High"
        comment = comment[len(_URGENCY_TAG):].strip()

    # Saved under a fallback name ("Other"): the real problem is in the issue tag.
    tag_cat, tag_issue, comment = _read_issue_tag(comment)
    if tag_issue:
        issue_str = first_issue = tag_issue

    history = [{"s": "reported", "t": created, "note": "Report sent"}]
    who = tech_name or "Technician"
    notes = {
        "repair": f"{who} started the repair",
        "followup": resolution_note or f"{who} requested a follow up",
        "escalated": resolution_note or "Report escalated to the admin",
        "fixed": resolution_note or "Report marked as fixed",
        "cancelled": f"You cancelled this report — {cancel_reason}" if cancel_reason else "You cancelled this report",
    }
    if status in notes:
        history.append({"s": status, "t": created, "note": notes[status]})

    return {
        "id": str(r.get("report_id") or r.get("ReportId") or r.get("id") or "—"),
        "db_id": r.get("report_id") or r.get("ReportId"),
        "lab": lab,
        "pc": pc,
        "issue": issue_str,
        "first_issue": first_issue,
        "cat": _category_of(first_issue) or (tag_cat if tag_cat in ISSUES else None),
        "desc": comment,
        "by": reporter,
        "created": created,
        "sent": sent_at,
        "status": status,
        "urgency": urgency,
        "tech": tech_name,
        "local": False,
        "esc_note": resolution_note,
        "cancel_reason": cancel_reason,
        "edit_reason": edit_reason,
        "last_follow_up": last_follow_up,
        "history": history,
    }


def store() -> dict:
    """Return cached data, fetching it from the backend on first access."""
    if f"{P}_data" not in ss:
        with ui.loading("Loading...", "Getting your lab's computers and reports"):
            ss[f"{P}_data"] = _fetch()
    return ss[f"{P}_data"]


def refresh() -> None:
    """Force a fresh backend fetch."""
    _reload()
    toast("Data refreshed")


def me() -> str:
    return ss.get(f"{P}_me", "Teacher")


def mine(s: dict) -> list[dict]:
    """All my reports (cancelled included), newest first."""
    return sorted(s["reports"] + s.get("cancelled", []), key=lambda r: r["created"], reverse=True)


def _find(rid: str) -> dict | None:
    return next((r for r in mine(store()) if r["id"] == rid), None)


def view_report(rid: str) -> None:
    if _find(rid):
        open_modal("report", rid)
    else:
        toast("That report is no longer available.", False)


def _reported_today(lab, pc, issue, skip_id: str | None = None) -> dict | None:
    """Same computer + same problem already reported today (cancelled ones don't count)."""
    return next((r for r in store()["reports"]
                 if r["id"] != skip_id and r["lab"] == lab and r["pc"] == pc
                 and issue in (r["issue"], r.get("first_issue"))
                 and _is_today(r.get("sent"))), None)


def _same_day_message(pc) -> str:
    return (f"This issue has already been reported today for {D.pc_name(pc)}. "
            "If the same problem happens again, please report it tomorrow.")


# ===========================================================================
# Follow up / edit / cancel
# ===========================================================================
def _can_edit(r: dict) -> bool:
    """Only while nobody has acted on it yet."""
    return r["status"] == "reported"


def _can_follow_up(r: dict) -> bool:
    if r["status"] != "reported":
        return False
    if _hours_since(r.get("sent") or r["created"]) < FOLLOW_UP_AFTER_HOURS:
        return False
    last = ss.get(f"{P}_followed", {}).get(r["id"]) or r.get("last_follow_up")
    return last is None or _hours_since(last) >= FOLLOW_UP_EVERY_HOURS


def _waiting_text(r: dict) -> str:
    hours = _hours_since(r.get("sent") or r["created"])
    days = int(hours // 24)
    return f"{days} day{'s' if days != 1 else ''}" if days >= 1 else f"{int(hours)} hours"


def open_follow_up(rid: str) -> None:
    ss[f"{P}_fu_msg"] = ""
    open_modal("followup", rid)


def _send_follow_up(rid: str) -> None:
    r = _find(rid)
    if not r or not _can_follow_up(r):
        return toast("This report can't be followed up right now.", False)
    result = _call("follow_up_teacher_report", _token(), report_id=r["db_id"],
                   message=(ss.get(f"{P}_fu_msg") or "").strip())
    if not result.get("success") and not result.get("offline"):
        return toast(result.get("error") or "Could not send the follow-up.", False)
    ss.setdefault(f"{P}_followed", {})[rid] = D.now()
    _save_local(rid, last_follow_up=D.now())
    close_modal()
    _reload()
    toast("Follow-up sent to the technicians" if result.get("success")
          else "Follow-up saved on this computer (the server isn't connected for this yet)")


def open_edit(rid: str) -> None:
    r = _find(rid)
    if not r:
        return
    cat = r.get("cat") or "Hardware"
    ss[f"{P}_ed_cat"] = cat
    ss[f"{P}_ed_issue"] = r["first_issue"] if r["first_issue"] in ISSUES[cat] else ISSUES[cat][0]
    ss[f"{P}_ed_desc"] = r["desc"]
    ss[f"{P}_ed_urg"] = r["urgency"]
    ss[f"{P}_ed_reason"] = ""
    open_modal("edit", rid)


def _save_edit(rid: str) -> None:
    r = _find(rid)
    if not r or not _can_edit(r):
        return toast("You can only edit a report while it's still waiting for a technician.", False)

    issue = ss.get(f"{P}_ed_issue")
    desc = (ss.get(f"{P}_ed_desc") or "").strip()
    urg = ss.get(f"{P}_ed_urg") or "Normal"
    reason = (ss.get(f"{P}_ed_reason") or "").strip()

    if len(reason) < MIN_REASON:
        return toast("Please give the reason for the edit.", False)
    if _is_other(issue) and len(desc) < 5:
        return toast("Please describe the problem in Details when you choose “Other”.", False)
    if issue == r["first_issue"] and desc == r["desc"] and urg == r["urgency"]:
        return toast("Nothing was changed.", False)
    if issue != r["first_issue"] and _reported_today(r["lab"], r["pc"], issue, skip_id=rid):
        return toast(_same_day_message(r["pc"]), False)

    result = _call("update_teacher_report", _token(), report_id=r["db_id"], issues=[issue],
                   comment=_compose_comment(desc, urg), reason=reason)
    if not result.get("success") and _issue_missing(result):
        result = _call("update_teacher_report", _token(), report_id=r["db_id"], issues=[_fallback_issue()],
                       comment=_compose_comment(desc, urg, issue=issue), reason=reason)
    if not result.get("success") and not result.get("offline"):
        return toast(result.get("error") or "Could not update the report.", False)
    if result.get("offline"):
        _save_local(rid, issue=issue, desc=desc, urgency=urg, edit_reason=reason)
    close_modal()
    _reload()
    toast("Report updated" if result.get("success")
          else "Changes saved on this computer (the server isn't connected for this yet)")


def open_cancel(rid: str) -> None:
    ss[f"{P}_cx_reason"] = ""
    open_modal("cancel", rid)


def _confirm_cancel(rid: str) -> None:
    r = _find(rid)
    if not r or not _can_edit(r):
        return toast("You can only cancel a report while it's still waiting for a technician.", False)
    reason = (ss.get(f"{P}_cx_reason") or "").strip()
    if len(reason) < MIN_REASON:
        return toast("Please give the reason for cancelling.", False)

    result = _call("cancel_teacher_report", _token(), report_id=r["db_id"], reason=reason)
    if not result.get("success") and not result.get("offline"):
        return toast(result.get("error") or "Could not cancel the report.", False)
    if result.get("offline"):
        _save_local(rid, cancelled=True, cancel_reason=reason, cancelled_at=D.now())
    close_modal()
    _reload()
    toast("Report cancelled" if result.get("success")
          else "Cancelled on this computer (the server isn't connected for this yet)")


# ===========================================================================
# Deactivate my account
# ===========================================================================
def open_deactivate() -> None:
    ss[f"{P}_da_reason"] = ""
    ss[f"{P}_da_ok"] = False
    open_modal("deactivate", "me")


def _deactivate_me() -> None:
    reason = (ss.get(f"{P}_da_reason") or "").strip()
    if len(reason) < MIN_REASON:
        return toast("Please tell us why you're deactivating your account.", False)
    if not ss.get(f"{P}_da_ok"):
        return toast("Tick the box to confirm.", False)

    result = _call("deactivate_my_account", _token(), reason=reason)
    if not result.get("success"):
        return toast(result.get("error") or "Could not deactivate the account.", False)
    # Account is off: clear the session so the app goes back to the login screen.
    ss.clear()


# ===========================================================================
# Report an issue (callbacks)
# ===========================================================================
def draft() -> dict:
    d = ss.setdefault(f"{P}_draft", {"lab": None, "pc": None, "cat": None, "issue": None, "urg": "Normal",
                                     "desc": "", "step": "lab"})
    d.setdefault("cat", None)
    return d


def _keep_desc() -> None:
    if _DESC in ss:
        draft()["desc"] = ss[_DESC]


def step_to(step: str) -> None:
    _keep_desc()
    draft()["step"] = step


def start_report(lab: int | None = None, pc: int | None = None) -> None:
    ss[f"{P}_draft"] = {"lab": lab, "pc": pc, "cat": None, "issue": None, "urg": "Normal", "desc": "",
                        "step": "problem" if lab and pc else "pc" if lab else "lab"}
    ss.pop(_DESC, None)
    go("report")


def pick_lab(lab: int) -> None:
    d = draft()
    d["lab"], d["pc"], d["step"] = lab, None, "pc"


def pick_map_pc(lab: int, pc: int) -> None:
    d = draft()
    d["lab"], d["pc"], d["step"] = lab, None, "pc"
    pick_pc(pc)


def pick_pc(pc: int) -> None:
    d = draft()
    comp = store()["computers"].get((d["lab"], pc))
    if comp and comp.get("status") == "Inactive":
        return toast(f"{D.pc_name(pc)} is not in use (inactive). "
                     "Please tell the technician directly if it's needed.", False)
    d["pc"] = pc


def pick(field: str, value: str) -> None:
    draft()[field] = value


def pick_cat(cat: str) -> None:
    _keep_desc()
    d = draft()
    if d.get("cat") != cat:
        d["cat"], d["issue"] = cat, None


def pick_issue(issue: str) -> None:
    _keep_desc()
    d = draft()
    if _reported_today(d["lab"], d["pc"], issue):
        return toast(_same_day_message(d["pc"]), False)
    d["issue"] = issue


def _find_computer_id(lab: int, pc: int) -> int | None:
    key = f"{P}_cid_map"
    if key not in ss:
        mapping: dict[tuple[int, int], int] = {}
        for comp in ss.get(f"{P}_raw_computers") or []:
            l = D.lab_of(comp.get("Room") or comp.get("room"))
            try:
                p = int(comp.get("UnitNumber") or comp.get("unit_number") or 0)
                cid = int(comp.get("ComputerId") or comp.get("computer_id") or 0)
            except (TypeError, ValueError):
                continue
            if p > 0 and cid > 0:
                mapping[(l, p)] = cid
        ss[key] = mapping
    return ss[key].get((int(lab), int(pc)))


def _submit() -> None:
    _keep_desc()
    d = draft()

    if not (d["lab"] and d["pc"] and d.get("cat") and d["issue"]):
        return toast("Pick the laboratory, the computer, Hardware or Software, and the problem first.", False)

    desc = (d["desc"] or "").strip()
    if _is_other(d["issue"]) and len(desc) < 5:
        d["step"] = "problem"
        return toast("Please describe the problem in Details when you choose “Other”.", False)

    # Same computer + same problem already reported today -> wait until tomorrow.
    if _reported_today(d["lab"], d["pc"], d["issue"]):
        d["step"] = "problem"
        return toast(_same_day_message(d["pc"]), False)

    s = store()
    dup = next((r for r in s["reports"]
                if r["lab"] == d["lab"] and r["pc"] == d["pc"] and r["issue"] == d["issue"]
                and _status_is_open(r["status"])), None)
    if dup:
        return toast(f"{D.pc_name(d['pc'])} was already reported for “{d['issue']}” ({dup['id']}). "
                     "You can follow it in My Reports.", False)

    computer_id = _find_computer_id(d["lab"], d["pc"])
    if computer_id is None:
        return toast("Could not find that computer in the database. Please refresh and try again.", False)

    result = backend_client.submit_teacher_report(
        _token(), computer_id=computer_id, issues=[d["issue"]], comment=_compose_comment(desc, d["urg"]),
    )
    if not result.get("success") and _issue_missing(result):
        # The problem name isn't in the ReportIssues table yet: save it under an
        # existing name ("Other") and keep the real problem in the comment.
        result = backend_client.submit_teacher_report(
            _token(), computer_id=computer_id, issues=[_fallback_issue()],
            comment=_compose_comment(desc, d["urg"], issue=d["issue"], cat=d.get("cat")),
        )
    if not result.get("success"):
        return toast(result.get("error") or "Could not send the report.", False)

    _reload()

    inserted = result.get("report") or {}
    d["step"] = "done"
    d["sent"] = str(inserted.get("ReportId") or inserted.get("report_id") or "sent")
    toast("Report sent to the technicians")


# ===========================================================================
# Pages
# ===========================================================================
def page_dashboard(s: dict, user: dict) -> None:
    m = mine(s)

    with box(f"{P}_hello", "cardh"):
        html(f'<div class="hello" style="margin:0"><div><h2>{portal.greeting()}, '
             f'{h(portal.first_name(user["name"]))}</h2>'
             "<p>Here's what's happening with the computers you reported.</p></div></div>")
        btn("Report an issue", f"{P}_hello_new", "primary", icon=":material/note_add:", on_click=start_report)

    total = ok = 0
    for lab, _ in D.LABS:
        sm = D.lab_summary(s, lab)
        total, ok = total + sm["total"], ok + sm["ok"]

    portal.stats(
        stat("alert", "ic-amber", sum(r["status"] == "reported" for r in m), "Waiting for a technician"),
        stat("wrench", "ic-red", sum(r["status"] in ("repair", "followup", "escalated") for r in m), "Being repaired"),
        stat("check", "ic-green", sum(r["status"] == "fixed" for r in m), "Fixed"),
        stat("pc", "ic-blue", f"{round(ok / total * 100) if total else 0}%", "Lab computers working"),
    )

    waiting = [r for r in m if _can_follow_up(r)]
    if waiting:
        with box(f"{P}_fu_note", "row", "spread", "mt"):
            html(f'<div class="demo-note" style="margin:0">{ic("info")}<span>{len(waiting)} of your reports '
                 f"{'has' if len(waiting) == 1 else 'have'} been waiting over "
                 f"{FOLLOW_UP_AFTER_HOURS // 24} days with no action. You can send a follow-up.</span></div>")
            btn("Follow up", f"{P}_fu_note_btn", "ghostsm", icon=":material/notifications_active:",
                on_click=view_report, args=(waiting[0]["id"],))

    with box(f"{P}_dgrid", "gmap", "mt"):
        with box(f"{P}_drecent", "card"):
            with box(f"{P}_drecent_h", "cardh"):
                html("<div><h3>My recent reports</h3></div>")
                btn("See all", f"{P}_drecent_all", "link", on_click=go, args=("reports",))

            recent = m[:5]
            if not recent:
                html(empty("You haven't reported anything yet.", "list"))
            for i, r in enumerate(recent):
                hit(row("pc", portal.tone(r["status"]), h(r["issue"]),
                        f'{D.lab_name(r["lab"])} · {D.pc_name(r["pc"])} · {D.when(r["created"])}',
                        _badge(r["status"]), last=i == len(recent) - 1, clickable=True),
                    f"{P}_recent_{r['id']}", view_report, (r["id"],))

        with box(f"{P}_dlabs", "card"):
            with box(f"{P}_dlabs_h", "cardh"):
                html("<div><h3>Laboratory status</h3></div>")
                btn("Open map", f"{P}_dlabs_map", "link", on_click=go, args=("labs",))
            portal.lab_tiles(P, s, "dash", open_lab)


def open_lab(lab: int) -> None:
    ss[f"{P}_lab"] = lab
    ss[f"{P}_lsel"] = None
    go("labs")


def _stepper(step: str) -> None:
    order = [k for k, _ in STEPS]
    idx = order.index(step) if step in order else len(order)
    cells = ""
    for i, (_, label) in enumerate(STEPS):
        cls = "st on" if i == idx else "st done" if i < idx else "st"
        num = "&#10003;" if i < idx else str(i + 1)
        cells += f'<div class="{cls}"><span class="n">{num}</span><span class="t">{label}</span></div>'
    html(f'<div class="stepper">{cells}</div>')


def page_report(s: dict) -> None:
    d = draft()
    step = d["step"]
    _stepper(step)

    with box(f"{P}_step_{step}", "card"):
        if step == "lab":
            html('<div class="card-h"><div><h3>Which laboratory are you in?</h3><div class="sub">Tap a computer on '
                 'the map or pick the room from the list.</div></div></div>')
            with box(f"{P}_r_grid", "gmap"):
                with box(f"{P}_r_mapcol", "stack"):
                    portal.live_map(P, s, "rep", pick_map_pc, focus=d["lab"])
                with box(f"{P}_r_tiles", "stack", "gap10"):
                    for lab, _ in D.LABS:
                        hit(lab_tile(s, lab, on=d["lab"] == lab), f"{P}_rlab_{lab}", pick_lab, (lab,))

        elif step == "pc":
            html(f'<div class="card-h"><div><h3>Which computer? <span class="muted" style="font-weight:500">· '
                 f'{D.lab_name(d["lab"])}</span></h3><div class="sub">The number is on the sticker on the monitor '
                 'or the system unit.</div></div></div>')
            with box(f"{P}_pcs", "pcgrid"):
                for c in D.lab_computers(s, d["lab"]):
                    stt = D.pc_status(s, d["lab"], c["pc"])
                    label = D.computer_status_label(stt)[0]
                    on = " on" if d["pc"] == c["pc"] else ""
                    hit(f'<div class="pc-btn s-{stt}{on}" title="{D.pc_name(c["pc"])} — {label}">{ic("pc")}'
                        f'{D.pad(c["pc"])}<small>{label}</small></div>',
                        f"{P}_pc_{c['pc']}", pick_pc, (c["pc"],))
            html('<div class="legend" style="justify-content:flex-start;margin-top:14px">'
                 '<span><i style="background:#8aa6d8"></i>Working</span>'
                 '<span><i style="background:var(--rep)"></i>Already reported</span>'
                 '<span><i style="background:var(--fix)"></i>Under repair</span></div>')

            r = D.pc_report(s, d["lab"], d["pc"]) if d["pc"] else None
            if r:
                html(f'<div class="demo-note mt">{ic("info")}<span>{D.pc_name(d["pc"])} was already reported '
                     f'{D.when(r["created"])} for <b>{h(r["issue"])}</b> ({_status_label(r["status"]).lower()}). '
                     "You can still send a report if it's a different problem.</span></div>")

            with box(f"{P}_pc_btns", "stepacts"):
                btn("Back", f"{P}_pc_back", "ghost", icon=":material/arrow_back:", on_click=step_to, args=("lab",))
                btn("Continue", f"{P}_pc_next", "primary", disabled=not d["pc"], on_click=step_to, args=("problem",))

        elif step == "problem":
            html('<div class="card-h"><div><h3>What kind of problem is it?</h3><div class="sub">Choose Hardware or '
                 'Software first, then pick the closest match.</div></div></div>')
            with box(f"{P}_cats", "chips"):
                for cat, label, _ in CATEGORIES:
                    btn(label, f"{P}_cat_{cat}", "chipon" if d.get("cat") == cat else "chip",
                        on_click=pick_cat, args=(cat,))
            hint = next((desc for cat, _, desc in CATEGORIES if cat == d.get("cat")), None)
            if hint:
                html(f'<div class="muted" style="margin:8px 0 14px;font-size:13px">{h(hint)}</div>')

            if d.get("cat"):
                html('<div class="adm-label">What\'s wrong?</div>')
                with box(f"{P}_issues", "issuegrid"):
                    for i, issue in enumerate(ISSUES[d["cat"]]):
                        today = d["pc"] and _reported_today(d["lab"], d["pc"], issue)
                        cls = "issue" + (" on" if d["issue"] == issue else "")
                        style = ' style="opacity:.55"' if today else ""
                        note = ('<small style="display:block;font-weight:400">Reported today</small>'
                                if today else "")
                        hit(f'<div class="{cls}"{style}>{h(issue)}{note}</div>',
                            f"{P}_iss_{d['cat']}_{i}", pick_issue, (issue,))
            else:
                html('<div class="muted" style="margin:14px 0">Pick Hardware or Software to see the list of '
                     'problems.</div>')

            if _DESC not in ss:
                ss[_DESC] = d["desc"]
            with box(f"{P}_desc_wrap", "field"):
                html('<div class="adm-label">Details <span class="muted" style="font-weight:400">'
                     '(optional)</span></div>')
                st.text_area("Details", key=_DESC, max_chars=400, label_visibility="collapsed",
                             placeholder="For example: the screen stays black but the power light is on.")

            html('<div class="adm-label">How urgent is it?</div>')
            with box(f"{P}_urg", "chips"):
                for value, label in URGENCY:
                    btn(label, f"{P}_urg_{value}", "chipon" if d["urg"] == value else "chip",
                        on_click=pick, args=("urg", value))

            with box(f"{P}_prob_btns", "stepacts"):
                btn("Back", f"{P}_prob_back", "ghost", icon=":material/arrow_back:", on_click=step_to, args=("pc",))
                btn("Review report", f"{P}_prob_next", "primary", disabled=not (d.get("cat") and d["issue"]),
                    on_click=step_to, args=("review",))

        elif step == "review":
            html('<div class="card-h"><div><h3>Check your report</h3><div class="sub">Make sure everything is '
                 'right before you send it.</div></div></div>')
            rows = (("Reported by", me()),
                    ("Laboratory", f'{D.lab_name(d["lab"])} ({D.WING[d["lab"]]})'),
                    ("Computer", D.pc_name(d["pc"])),
                    ("Type", d.get("cat") or "—"),
                    ("Problem", d["issue"]),
                    ("Details", (d["desc"] or "").strip() or "—"),
                    ("Urgency", d["urg"]))
            html("".join(f'<div class="review-row"><div class="review-label">{k}</div>'
                         f'<div class="review-value">{h(v)}</div></div>' for k, v in rows))
            with box(f"{P}_rev_btns", "stepacts"):
                btn("Edit", f"{P}_rev_back", "ghost", icon=":material/arrow_back:", on_click=step_to, args=("problem",))
                btn("Send report", f"{P}_send", "primary", on_click=_submit)

        else:  # sent
            r = next((x for x in s["reports"] if x["id"] == d.get("sent")), None)
            where = f'{D.lab_name(r["lab"])} · {D.pc_name(r["pc"])}' if r else "the computer"
            html(f'<div class="success"><div class="big">{ic("check")}</div>'
                 '<h3 style="font-size:22px">Report sent</h3>'
                 f'<p class="muted" style="max-width:440px;margin:8px auto 22px">{h(d.get("sent") or "")} for '
                 f"{where} went to the technicians. You'll see their updates in My Reports and under the bell.</p></div>")
            with box(f"{P}_done_btns", "row", "center"):
                btn("Report another", f"{P}_again", "ghost", on_click=start_report)
                btn("View my reports", f"{P}_mine", "primary", on_click=go, args=("reports",))


T_FILTERS = [("all", "All"), ("reported", "Waiting"), ("repair", "Being repaired"), ("fixed", "Fixed"),
             ("cancelled", "Cancelled")]


def _t_match(r: dict, f: str) -> bool:
    if f == "all":
        return True
    if f == "repair":
        return r["status"] in {"repair", "followup", "escalated"}
    return r["status"] == f


def page_reports(s: dict) -> None:
    m = mine(s)
    flt = ss.setdefault(f"{P}_tfilter", "all")

    with box(f"{P}_tcard", "card", "pad0"):
        with box(f"{P}_thead", "cardh", "padh"):
            with box(f"{P}_tchips", "chips"):
                for key, label in T_FILTERS:
                    btn(f"{label} · {sum(_t_match(r, key) for r in m)}", f"{P}_tf_{key}",
                        "chipon" if flt == key else "chip",
                        on_click=lambda k=key: ss.__setitem__(f"{P}_tfilter", k))
            with box(f"{P}_tctl", "row"):
                how = sort_select(f"{P}_t_sort__selwide__",
                                  {k: f"Sort: {v}" for k, v in D.MY_REPORT_SORTS.items()})
                btn("New report", f"{P}_tnew", "primarysm", icon=":material/note_add:", on_click=start_report)

        rows = D.sort_reports([r for r in m if _t_match(r, flt)], how)
        cols = "grid-template-columns:96px minmax(0,1fr) minmax(0,1.2fr) minmax(0,1fr) 150px 92px;"
        html(f'<div class="tt-head" style="{cols}"><div>Report</div><div>Computer</div><div>Problem</div>'
             '<div>Sent</div><div>Status</div><div>&nbsp;</div></div>')

        if not rows:
            html(empty("No reports here.", "list"))
        for r in rows:
            waiting = (f'<div class="small" style="color:var(--rep)">No action for {_waiting_text(r)} '
                       "· follow up</div>" if _can_follow_up(r) else "")
            hit(f'<div class="tt-row" style="{cols}"><div class="strong">{h(r["id"])}</div>'
                f'<div>{D.lab_name(r["lab"])}<div class="small">{D.pc_name(r["pc"])}</div></div>'
                f'<div>{h(r["issue"])}<div class="small">{h(r.get("cat") or "")}</div></div>'
                f'<div>{D.sent_date(r.get("sent", r["created"]))}</div>'
                f'<div>{_badge(r["status"])}{waiting}</div>'
                '<div style="text-align:right"><span class="fakebtn">View</span></div></div>',
                f"{P}_t_{r['id']}", view_report, (r["id"],))


def _show_pc(lab: int, pc: int) -> None:
    ss[f"{P}_lsel"], ss[f"{P}_lab"] = (lab, pc), lab


def _focus(lab: int) -> None:
    ss[f"{P}_lab"] = None if ss.get(f"{P}_lab") == lab else lab
    ss[f"{P}_lsel"] = None


def page_labs(s: dict) -> None:
    focus, sel = ss.get(f"{P}_lab"), ss.get(f"{P}_lsel")

    with box(f"{P}_lgrid", "gmap"):
        with box(f"{P}_lmap", "card"):
            html('<div class="card-h"><div><h3>Centrum Laboratory</h3><div class="sub">Hover a computer to see its '
                 'status. Click one to report it.</div></div></div>')
            portal.live_map(P, s, "labs", _show_pc, focus=focus, sel=tuple(sel) if sel else None)

        with box(f"{P}_lside", "stack", "gap10"):
            for lab, _ in D.LABS:
                hit(lab_tile(s, lab, on=focus == lab), f"{P}_ltile_{lab}", _focus, (lab,))

            if sel:
                lab, pc = sel
                r = D.pc_report(s, lab, pc)
                with box(f"{P}_lpc", "card"):
                    status_badge = _badge(r["status"]) if r else '<span class="badge b-fixed">Working</span>'
                    description = (
                        f'<p class="muted" style="margin:0 0 14px">{h(r["issue"])} — reported '
                        f'{D.when(r["created"])}.</p>' if r
                        else '<p class="muted" style="margin:0 0 14px">No open reports for this computer.</p>')
                    html(f'<div class="pc-panel"><div class="ph">'
                         f'<div class="ic {"ic-amber" if r else "ic-blue"}">{ic("pc")}</div>'
                         f'<div><h3>{D.lab_name(lab)} · {D.pc_name(pc)}</h3>{status_badge}</div></div>'
                         f'{description}</div>')
                    with box(f"{P}_lpc_btn", "row"):
                        btn("Report this computer", f"{P}_lpc_report", "primary", icon=":material/add:",
                            on_click=start_report, args=(lab, pc))


def _save_number(number: str) -> tuple[bool, str]:
    token = _token()
    if not token:
        return False, "Not connected to the server — log out and log back in to save your contact number."

    result = backend_client.update_teacher_contact(token, number)
    if not result.get("success"):
        return False, result.get("error") or "Could not save the contact number."

    saved = result.get("user") if isinstance(result.get("user"), dict) else {}
    ui.set_contact_number(saved.get("contact_number") or saved.get("ContactNumber") or number)
    return True, result.get("message") or "Contact number updated."


def page_profile(s: dict, user: dict) -> None:
    SHELL.profile_head(user, "Teacher", "Active account")

    with box(f"{P}_pf_grid", "g2", "mt"):
        with box(f"{P}_pf_contact", "card"):
            SHELL.contact_card(user, _save_number)

        with box(f"{P}_pf_act", "card"):
            items = sorted(((r, e) for r in mine(s) for e in r["history"]),
                           key=lambda x: x[1]["t"], reverse=True)[:5]
            icons = {"fixed": "check", "reported": "plus", "repair": "wrench", "escalated": "up",
                     "followup": "wrench", "cancelled": "list"}
            body = "".join(
                row(icons.get(e["s"], "wrench"), "ic-blue",
                    f'{_status_label(e["s"])} · {D.lab_name(r["lab"])} {D.pc_name(r["pc"])}',
                    f'{e["note"]} · {D.when(e["t"])}', last=i == len(items) - 1)
                for i, (r, e) in enumerate(items))
            html('<div class="card-h"><h3>My activity</h3></div>'
                 + (f'<div class="rows" style="margin-bottom:16px">{body}</div>' if body
                    else empty("Nothing yet.", "list")))
            SHELL.logout_button()

    with box(f"{P}_pf_danger", "card", "mt"):
        html('<div class="card-h"><div><h3>Deactivate my account</h3><div class="sub">Use this if you are leaving '
             "the school or no longer need access. You won't be able to log in afterwards; the admin can turn "
             "your account back on.</div></div></div>")
        btn("Deactivate my account", f"{P}_pf_deact", "ghost", icon=":material/person_off:",
            on_click=open_deactivate)


# ===========================================================================
# Pop-up windows
# ===========================================================================
def _note_html(label: str, text: str) -> str:
    return (f'<div class="demo-note mt">{ic("info")}<span><b>{h(label)}:</b> {h(text)}</span></div>')


def render_modal(s: dict) -> None:
    kind, ref = SHELL.modal

    if kind == "report":
        r = _find(ref)
        if r is None:
            return close_modal()
        with SHELL.window():
            html(portal.report_details(r))
            if r.get("edit_reason"):
                html(_note_html("Edited", r["edit_reason"]))
            if r["status"] == "cancelled":
                html(_note_html("Cancelled", r.get("cancel_reason") or "No reason given"))
            elif r["status"] == "reported" and not _can_follow_up(r):
                if _hours_since(r.get("sent") or r["created"]) < FOLLOW_UP_AFTER_HOURS:
                    html(f'<div class="muted mt" style="font-size:13px">If no technician picks this up within '
                         f"{FOLLOW_UP_AFTER_HOURS // 24} days, you can send a follow-up.</div>")
                else:
                    html('<div class="muted mt" style="font-size:13px">Follow-up sent. You can send another one '
                         "tomorrow if there's still no action.</div>")
            with box(f"{P}_m_act", "mactions"):
                if _can_follow_up(r):
                    btn("Follow up", f"{P}_m_fu", "primary", icon=":material/notifications_active:",
                        on_click=open_follow_up, args=(r["id"],))
                if _can_edit(r):
                    btn("Edit", f"{P}_m_edit", "ghost", icon=":material/edit:", on_click=open_edit, args=(r["id"],))
                    btn("Cancel report", f"{P}_m_cancel", "ghost", icon=":material/cancel:",
                        on_click=open_cancel, args=(r["id"],))
                btn("Close", f"{P}_m_close", "ghost", on_click=close_modal)

    elif kind == "followup":
        r = _find(ref)
        if r is None or not _can_follow_up(r):
            return close_modal()
        with SHELL.window():
            html(f'<div class="card-h"><div><h3>Follow up {h(r["id"])}</h3><div class="sub">'
                 f'{D.lab_name(r["lab"])} · {D.pc_name(r["pc"])} · {h(r["issue"])} — waiting for '
                 f"{_waiting_text(r)} with no action.</div></div></div>")
            st.text_area("Message to the technicians (optional)", key=f"{P}_fu_msg", max_chars=300,
                         placeholder="For example: we have a class using this computer every morning.")
            with box(f"{P}_fu_act", "mactions"):
                btn("Back", f"{P}_fu_back", "ghost", on_click=view_report, args=(r["id"],))
                btn("Send follow-up", f"{P}_fu_send", "primary", on_click=_send_follow_up, args=(r["id"],))

    elif kind == "edit":
        r = _find(ref)
        if r is None or not _can_edit(r):
            return close_modal()
        with SHELL.window():
            html(f'<div class="card-h"><div><h3>Edit {h(r["id"])}</h3><div class="sub">'
                 f'{D.lab_name(r["lab"])} · {D.pc_name(r["pc"])}. You can edit while no technician has '
                 "picked it up yet.</div></div></div>")
            cats = [c for c, _, _ in CATEGORIES]
            if ss.get(f"{P}_ed_cat") not in cats:
                ss[f"{P}_ed_cat"] = cats[0]
            st.radio("Type of problem", cats, key=f"{P}_ed_cat", horizontal=True)
            options = ISSUES[ss[f"{P}_ed_cat"]]
            if ss.get(f"{P}_ed_issue") not in options:
                ss[f"{P}_ed_issue"] = options[0]
            st.selectbox("Problem", options, key=f"{P}_ed_issue")
            st.text_area("Details (optional)", key=f"{P}_ed_desc", max_chars=400)
            if ss.get(f"{P}_ed_urg") not in dict(URGENCY):
                ss[f"{P}_ed_urg"] = "Normal"
            st.radio("How urgent is it?", [v for v, _ in URGENCY], key=f"{P}_ed_urg", horizontal=True,
                     format_func=lambda v: dict(URGENCY)[v])
            st.text_area("Reason for the edit (required)", key=f"{P}_ed_reason", max_chars=300,
                         placeholder="For example: I picked the wrong problem.")
            with box(f"{P}_ed_act", "mactions"):
                btn("Back", f"{P}_ed_back", "ghost", on_click=view_report, args=(r["id"],))
                btn("Save changes", f"{P}_ed_save", "primary", on_click=_save_edit, args=(r["id"],))

    elif kind == "cancel":
        r = _find(ref)
        if r is None or not _can_edit(r):
            return close_modal()
        with SHELL.window():
            html(f'<div class="card-h"><div><h3>Cancel {h(r["id"])}?</h3><div class="sub">'
                 f'{D.lab_name(r["lab"])} · {D.pc_name(r["pc"])} · {h(r["issue"])}. The technicians will no '
                 "longer see it in their queue.</div></div></div>")
            st.text_area("Reason for cancelling (required)", key=f"{P}_cx_reason", max_chars=300,
                         placeholder="For example: the computer is working again after a restart.")
            with box(f"{P}_cx_act", "mactions"):
                btn("Keep report", f"{P}_cx_back", "ghost", on_click=view_report, args=(r["id"],))
                btn("Cancel report", f"{P}_cx_ok", "primary", on_click=_confirm_cancel, args=(r["id"],))

    elif kind == "deactivate":
        with SHELL.window():
            html('<div class="card-h"><div><h3>Deactivate my account</h3><div class="sub">You will be logged out '
                 "and won't be able to log in again until the admin reactivates your account. Your reports stay "
                 "in the system.</div></div></div>")
            st.text_area("Reason (required)", key=f"{P}_da_reason", max_chars=300,
                         placeholder="For example: I resigned / I'm transferring to another school.")
            st.checkbox("I understand that I won't be able to log in anymore.", key=f"{P}_da_ok")
            with box(f"{P}_da_act", "mactions"):
                btn("Back", f"{P}_da_back", "ghost", on_click=close_modal)
                btn("Deactivate", f"{P}_da_ok_btn", "primary", on_click=_deactivate_me)

    elif kind and not SHELL.common_modal(kind):
        close_modal()


# ===========================================================================
# Centrum Assistant (the chatbot)
# ===========================================================================
BOT_CONFIG = {
    "names": {"report": "Report an Issue", "myreports": "My Reports", "inventory": "Laboratory Status",
              "settings": "My Profile"},
    "pages": {"report": "report", "myreports": "reports", "inventory": "labs", "settings": "profile"},
    "status_groups": [("waiting for a technician", {"reported"}),
                      ("being repaired", {"repair", "followup"}),
                      ("escalated to the admin", {"escalated"}),
                      ("cancelled by you", {"cancelled"}),
                      # chatbot.py looks for a group named "resolved" to tell open reports from finished ones
                      ("resolved", {"fixed"})],
    "status_help": ("**Reported** - your report is waiting for a technician to pick it up. If nobody acts on it "
                    f"for {FOLLOW_UP_AFTER_HOURS // 24} days, open it in My Reports and press **Follow up**. "
                    "While it's still Reported you can also **Edit** or **Cancel** it (a reason is required).\n"
                    "**Under repair** - a technician is working on the computer.\n"
                    "**Follow Up** - the technician needs a follow-up action before the report can be completed.\n"
                    "**Escalated** - it needs parts, a replacement or the admin's decision; it's still being handled.\n"
                    "**Fixed** - the computer is working again.\n"
                    "**Cancelled** - you cancelled the report."),
    "report_howto": ("1. Open **{report}**.\n2. Pick the laboratory (tap the map or the list).\n"
                     "3. Pick the computer - the number is on the sticker on the monitor or system unit.\n"
                     "4. Choose **Hardware** or **Software**, then what's wrong. Add details (optional) and how "
                     "urgent it is.\n"
                     "5. Check everything and press **Send report**.\nYour name and the time are added automatically.\n"
                     "The same problem on the same computer can only be reported once a day."),
    "inventory_help": ("Open **{inventory}** to see the live floor map: hover a computer for its status, or click it "
                       "to see it and report it."),
    "contact_help": "You can update your contact number in **{settings}**.",
    "password_help": "Log out, then use **Forgot password?** on the login screen to get a reset code by email.",
    "urgent_help": ("When you report it, choose **High - class is using it now** under \"How urgent is it?\". "
                    "The technicians will see it marked as urgent in the report's details."),
    "wait_help": ("I can't promise a time - technicians work through the queue. Watch the status in {myreports}; "
                  f"if it's still Reported after {FOLLOW_UP_AFTER_HOURS // 24} days, open it and press "
                  "**Follow up**."),
}


def _bot_reports(s: dict) -> list[dict]:
    """My reports, newest first, in the shape the assistant reads."""
    return [{"id": r["id"], "where": f"{D.lab_name(r['lab'])} · {D.pc_name(r['pc'])}", "issue": r["issue"],
             "status": r["status"], "date": D.date_time(r["created"])} for r in mine(s)]


# ===========================================================================
# Notifications
# ===========================================================================
def _notifications(s: dict) -> list[dict]:
    """Every status change on my reports (repair, follow up, escalated, fixed)."""
    icons = {"repair": ("wrench", "ic-red"), "followup": ("wrench", "ic-amber"),
             "escalated": ("up", "ic-violet"), "fixed": ("check", "ic-green")}
    out = []
    for r in mine(s):
        for i, e in enumerate(r["history"][1:], start=1):
            if e["s"] == "cancelled":  # the teacher did this themself; no notification
                continue
            icon, tone_cls = icons.get(e["s"], ("bell", "ic-blue"))
            out.append({"id": f"upd:{r['id']}:{i}", "icon": icon, "tone": tone_cls,
                        "title": f"{r['id']} · {D.lab_name(r['lab'])} {D.pc_name(r['pc'])} "
                                 f"is {_status_label(e['s']).lower()}",
                        "sub": e["note"], "t": e["t"], "cb": view_report, "args": (r["id"],),
                        "roles": ["teacher"]})
    return out


# ===========================================================================
# Public entry point
# ===========================================================================
def render(user: dict | None = None) -> None:
    """Draw the Teacher dashboard for `user` (a dict from your login)."""
    ui.page_config(ROLE)
    user = ui.require_user(user, ROLE, (ROLE.lower(),))
    ss[f"{P}_me"] = user["name"]
    s = store()
    page = SHELL.page

    SHELL.frame(user, s, {"reports": sum(_status_is_open(r["status"]) for r in mine(s))}, _notifications(s))

    with SHELL.content():
        if s.get("notice") and page != "profile":
            with box(f"{P}_notice", "row", "spread"):
                html(f'<div class="demo-note" style="margin:0">{ic("info")}<span>{h(s["notice"])}</span></div>')
                btn("Refresh", f"{P}_refresh", "ghostsm", icon=":material/refresh:", on_click=refresh)
            html('<div style="height:18px"></div>')

        if page == "report":
            page_report(s)
        elif page == "reports":
            page_reports(s)
        elif page == "labs":
            page_labs(s)
        elif page == "profile":
            page_profile(s, user)
        else:
            page_dashboard(s, user)

        render_modal(s)

    chatbot.render(P, user, _bot_reports(s), navigate=go, config=BOT_CONFIG)
