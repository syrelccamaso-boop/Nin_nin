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
                   (+ details, urgency) -> 4 Review -> sent
My Reports         filter chips, Sort by, report details
Laboratory Status  live floor map; click a computer to see it and report it
My Profile         contact number, my activity, log out

Centrum Assistant  the floating robot button (bottom right, every page) opens a
                   chat window (chatbot.py): how to report a problem, the status
                   of my reports, what the statuses mean, and buttons that open
                   the right page.

ReportStatus database mapping:
    1 = Reported
    2 = Under repair
    3 = Fixed
    4 = Escalated
    5 = Follow Up

Urgency: the backend report call only takes computer_id / issues / comment, so a
"High" urgency is stored as a tag at the start of the comment
(see _URGENCY_TAG) and read back in _report_from_db(). The technicians see the
tag in the report's details. If the backend later gets a real urgency field,
send it in _submit() and drop the tag.
"""

from __future__ import annotations

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


# ===========================================================================
# Report status
# ===========================================================================
_STATUS_ID_MAP = {1: "reported", 2: "repair", 3: "fixed", 4: "escalated", 5: "followup"}

_STATUS_TEXT = {
    "reported": {"reported", "report", "pending", "open", "waiting", "waiting for a technician"},
    "repair": {"under repair", "under_repair", "repair", "in repair", "being repaired", "progress", "in progress"},
    "fixed": {"fixed", "fix", "resolved", "complete", "completed"},
    "escalated": {"escalated", "escalate", "escalation"},
    "followup": {"follow up", "follow-up", "followup", "follow_up"},
}

_STATUS_LABELS = {
    "reported": "Reported",
    "repair": "Under repair",
    "fixed": "Fixed",
    "escalated": "Escalated",
    "followup": "Follow Up",
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
    """Follow Up and Escalated stay open: the issue is not Fixed yet."""
    return status in _OPEN_STATUSES


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

        # Same column -> label mapping as Admin/Technician; empty columns are left out.
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

    s["reports"] = [_report_from_db(r) for r in (result.get("reports") or []) if isinstance(r, dict)]
    return s


def _report_from_db(r: dict) -> dict:
    """Convert a backend report into the structure the Teacher UI uses."""
    # Reports.CreatedAt as stored (None when missing) - the Sent column uses it directly.
    sent_at = D.parse_dt(r.get("created_at") or r.get("CreatedAt"))
    created = sent_at or D.now()
    status = _status_from_report(r)

    # Issues
    issues = r.get("issues") or r.get("Issues") or []
    if isinstance(issues, str):
        issues = [i.strip() for i in issues.split(",") if i.strip()]
    issue_str = ", ".join(str(i) for i in issues) if issues else (r.get("issue") or r.get("Issue") or "Other")

    # Laboratory / computer
    lab = D.lab_of(r.get("room") or r.get("Room"))
    try:
        pc = int(r.get("unit_number") or r.get("UnitNumber") or 0)
    except (TypeError, ValueError):
        pc = 0

    reporter = str(r.get("reporter") or r.get("ReporterName") or r.get("reporter_name") or me())

    # Technician
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

    # Urgency is kept as a tag at the start of the comment (see the module docstring).
    comment = str(r.get("comment") or r.get("Comment") or "")
    urgency = "Normal"
    if comment.startswith(_URGENCY_TAG):
        urgency = "High"
        comment = comment[len(_URGENCY_TAG):].strip()

    # History: the dashboard row only gives the current status, so build a display history from it.
    history = [{"s": "reported", "t": created, "note": "Report sent"}]
    who = tech_name or "Technician"
    notes = {
        "repair": f"{who} started the repair",
        "followup": resolution_note or f"{who} requested a follow up",
        "escalated": resolution_note or "Report escalated to the admin",
        "fixed": resolution_note or "Report marked as fixed",
    }
    if status in notes:
        history.append({"s": status, "t": created, "note": notes[status]})

    return {
        "id": str(r.get("report_id") or r.get("ReportId") or r.get("id") or "—"),
        "db_id": r.get("report_id") or r.get("ReportId"),
        "lab": lab,
        "pc": pc,
        "issue": issue_str,
        "desc": comment,
        "by": reporter,
        "created": created,
        "sent": sent_at,
        "status": status,
        "urgency": urgency,
        "tech": tech_name,
        "local": False,
        "esc_note": resolution_note,
        "history": history,
    }


def store() -> dict:
    """Return cached data, fetching it from the backend on first access."""
    if f"{P}_data" not in ss:
        with st.spinner("Loading..."):
            ss[f"{P}_data"] = _fetch()
    return ss[f"{P}_data"]


def refresh() -> None:
    """Force a fresh backend fetch."""
    ss.pop(f"{P}_data", None)
    toast("Data refreshed")


def me() -> str:
    return ss.get(f"{P}_me", "Teacher")


def mine(s: dict) -> list[dict]:
    """All reports returned by the teacher API, newest first."""
    return sorted(s["reports"], key=lambda r: r["created"], reverse=True)


def view_report(rid: str) -> None:
    if any(r["id"] == rid for r in store()["reports"]):
        open_modal("report", rid)
    else:
        toast("That report is no longer available.", False)


# ===========================================================================
# Report an issue (callbacks)
# ===========================================================================
def draft() -> dict:
    return ss.setdefault(f"{P}_draft", {"lab": None, "pc": None, "issue": None, "urg": "Normal",
                                        "desc": "", "step": "lab"})


def _keep_desc() -> None:
    if _DESC in ss:
        draft()["desc"] = ss[_DESC]


def step_to(step: str) -> None:
    _keep_desc()
    draft()["step"] = step


def start_report(lab: int | None = None, pc: int | None = None) -> None:
    ss[f"{P}_draft"] = {"lab": lab, "pc": pc, "issue": None, "urg": "Normal", "desc": "",
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

    if not (d["lab"] and d["pc"] and d["issue"]):
        return toast("Pick the laboratory, the computer and the problem first.", False)

    desc = (d["desc"] or "").strip()
    if d["issue"] == "Other" and len(desc) < 5:
        d["step"] = "problem"
        return toast("Please describe the problem in Details when you choose “Other”.", False)

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

    # High urgency travels as a tag in the comment (the backend has no urgency field yet).
    comment = f"{_URGENCY_TAG} {desc}".strip() if d["urg"] == "High" else desc

    result = backend_client.submit_teacher_report(
        _token(), computer_id=computer_id, issues=[d["issue"]], comment=comment,
    )
    if not result.get("success"):
        return toast(result.get("error") or "Could not send the report.", False)

    refresh()

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
                        badge(r["status"]), last=i == len(recent) - 1, clickable=True),
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
            html('<div class="card-h"><div><h3>What\'s wrong?</h3><div class="sub">Pick the closest match, then add '
                 'any details that help.</div></div></div>')
            with box(f"{P}_issues", "issuegrid"):
                for i, issue in enumerate(D.ISSUES):
                    hit(f'<div class="issue{" on" if d["issue"] == issue else ""}">{h(issue)}</div>',
                        f"{P}_iss_{i}", pick, ("issue", issue))

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
                btn("Review report", f"{P}_prob_next", "primary", disabled=not d["issue"],
                    on_click=step_to, args=("review",))

        elif step == "review":
            html('<div class="card-h"><div><h3>Check your report</h3><div class="sub">Make sure everything is '
                 'right before you send it.</div></div></div>')
            rows = (("Reported by", me()),
                    ("Laboratory", f'{D.lab_name(d["lab"])} ({D.WING[d["lab"]]})'),
                    ("Computer", D.pc_name(d["pc"])),
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


T_FILTERS = [("all", "All"), ("reported", "Waiting"), ("repair", "Being repaired"), ("fixed", "Fixed")]


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
            hit(f'<div class="tt-row" style="{cols}"><div class="strong">{h(r["id"])}</div>'
                f'<div>{D.lab_name(r["lab"])}<div class="small">{D.pc_name(r["pc"])}</div></div>'
                f'<div>{h(r["issue"])}</div>'
                f'<div>{D.sent_date(r.get("sent", r["created"]))}</div>'
                f'<div>{badge(r["status"])}</div>'
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
                    status_badge = badge(r["status"]) if r else '<span class="badge b-fixed">Working</span>'
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
            icons = {"fixed": "check", "reported": "plus", "repair": "wrench", "escalated": "up", "followup": "wrench"}
            body = "".join(
                row(icons.get(e["s"], "wrench"), "ic-blue",
                    f'{_status_label(e["s"])} · {D.lab_name(r["lab"])} {D.pc_name(r["pc"])}',
                    f'{e["note"]} · {D.when(e["t"])}', last=i == len(items) - 1)
                for i, (r, e) in enumerate(items))
            html('<div class="card-h"><h3>My activity</h3></div>'
                 + (f'<div class="rows" style="margin-bottom:16px">{body}</div>' if body
                    else empty("Nothing yet.", "list")))
            SHELL.logout_button()


# ===========================================================================
# Pop-up windows
# ===========================================================================
def render_modal(s: dict) -> None:
    kind, ref = SHELL.modal
    if kind == "report":
        r = next((x for x in s["reports"] if x["id"] == ref), None)
        if r is None:
            return close_modal()
        with SHELL.window():
            html(portal.report_details(r))
            with box(f"{P}_m_act", "mactions"):
                btn("Close", f"{P}_m_close", "ghost", on_click=close_modal)
    elif kind and not SHELL.common_modal(kind):
        close_modal()


# ===========================================================================
# Centrum Assistant (the chatbot)
# ===========================================================================
# Wording and page names of the teacher dashboard for chatbot.py.
BOT_CONFIG = {
    "names": {"report": "Report an Issue", "myreports": "My Reports", "inventory": "Laboratory Status",
              "settings": "My Profile"},
    "pages": {"report": "report", "myreports": "reports", "inventory": "labs", "settings": "profile"},
    "status_groups": [("waiting for a technician", {"reported"}),
                      ("being repaired", {"repair", "followup"}),
                      ("escalated to the admin", {"escalated"}),
                      # chatbot.py looks for a group named "resolved" to tell open reports from finished ones
                      ("resolved", {"fixed"})],
    "status_help": ("**Reported** - your report is waiting for a technician to pick it up.\n"
                    "**Under repair** - a technician is working on the computer.\n"
                    "**Follow Up** - the technician needs a follow-up action before the report can be completed.\n"
                    "**Escalated** - it needs parts, a replacement or the admin's decision; it's still being handled.\n"
                    "**Fixed** - the computer is working again."),
    "report_howto": ("1. Open **{report}**.\n2. Pick the laboratory (tap the map or the list).\n"
                     "3. Pick the computer - the number is on the sticker on the monitor or system unit.\n"
                     "4. Choose what's wrong, add details and how urgent it is.\n"
                     "5. Check everything and press **Send report**.\nYour name and the time are added automatically."),
    "inventory_help": ("Open **{inventory}** to see the live floor map: hover a computer for its status, or click it "
                       "to see it and report it."),
    "contact_help": "You can update your contact number in **{settings}**.",
    "password_help": "Log out, then use **Forgot password?** on the login screen to get a reset code by email.",
    "urgent_help": ("When you report it, choose **High - class is using it now** under \"How urgent is it?\". "
                    "The technicians will see it marked as urgent in the report's details."),
    "wait_help": ("I can't promise a time - technicians work through the queue. Watch the status in {myreports}; "
                  "you also get a notification under the bell when it changes."),
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

    # floating robot button + chat window (position: fixed, bottom-right on every page)
    chatbot.render(P, user, _bot_reports(s), navigate=go, config=BOT_CONFIG)