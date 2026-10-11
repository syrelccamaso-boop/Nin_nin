"""
Teacher.py - Centrum Laboratory | Teacher dashboard (Streamlit)

Teacher report data comes from:
    Streamlit frontend
        ↓
    backend_client
        ↓
    FastAPI / teacher_service.py
        ↓
    Supabase PostgreSQL

ReportStatus database mapping:
    1 = Reported
    2 = Under repair
    3 = Fixed
    4 = Escalated
    5 = Follow Up
"""

from __future__ import annotations

import streamlit as st

from . import backend_client
from . import chatbot
from . import lab_data as D
from . import portal
from . import ui
from frontend.portal import badge, empty, ic, lab_tile, row, sort_select, stat


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

go, open_modal, close_modal, toast = (
    SHELL.go,
    SHELL.open_modal,
    SHELL.close_modal,
    SHELL.toast,
)

html, btn, hit, box, h = ui.html, ui.btn, ui.hit, ui.box, ui.h


STEPS = [
    ("lab", "Laboratory"),
    ("pc", "Computer"),
    ("problem", "Problem"),
    ("review", "Review"),
]

URGENCY = [
    ("Normal", "Normal"),
    ("High", "High — class is using it now"),
]

_DESC = f"{P}_r_desc"


# ===========================================================================
# Report Status
# ===========================================================================

# Exact ReportStatus table in Supabase:
#
# StatusId | CurrentStatus
# ---------|--------------
#     1    | Reported
#     2    | Under repair
#     3    | Fixed
#     4    | Escalated
#     5    | Follow Up
#
# These are the frontend status keys used by Teacher.py.

_STATUS_ID_MAP = {
    1: "reported",
    2: "repair",
    3: "fixed",
    4: "escalated",
    5: "followup",
}


def _normalize_report_status(value) -> str | None:
    """
    Convert a database/backend status value into the internal Teacher.py
    status key.

    Supported database values:

        Reported     -> reported
        Under repair -> repair
        Fixed        -> fixed
        Escalated    -> escalated
        Follow Up    -> followup

    Also accepts the internal frontend values.
    """
    if value is None:
        return None

    text = str(value).strip().lower()

    if not text:
        return None

    # ------------------------------------------------------------------
    # Database CurrentStatus values
    # ------------------------------------------------------------------
    if text in {
        "reported",
        "report",
        "pending",
        "open",
        "waiting",
        "waiting for a technician",
    }:
        return "reported"

    if text in {
        "under repair",
        "under_repair",
        "repair",
        "in repair",
        "being repaired",
        "progress",
        "in progress",
    }:
        return "repair"

    if text in {
        "fixed",
        "fix",
        "resolved",
        "complete",
        "completed",
    }:
        return "fixed"

    if text in {
        "escalated",
        "escalate",
        "escalation",
    }:
        return "escalated"

    if text in {
        "follow up",
        "follow-up",
        "followup",
        "follow_up",
    }:
        return "followup"

    return None


def _status_from_report(r: dict) -> str:
    """
    Determine the report status.

    Priority:
        1. CurrentStatus/status text returned by backend
        2. StatusId
        3. reported fallback

    This prevents a frontend StatusId mapping from overriding the actual
    ReportStatus.CurrentStatus returned by the database.
    """

    # ------------------------------------------------------------------
    # Prefer actual status text from backend / ReportStatus table.
    # ------------------------------------------------------------------
    status_text_candidates = (
        r.get("current_status"),
        r.get("CurrentStatus"),
        r.get("status_name"),
        r.get("StatusName"),
        r.get("status_text"),
        r.get("StatusText"),
        r.get("status"),
        r.get("Status"),
    )

    for value in status_text_candidates:
        normalized = _normalize_report_status(value)
        if normalized:
            return normalized

    # ------------------------------------------------------------------
    # Fallback to StatusId.
    # ------------------------------------------------------------------
    status_id = (
        r.get("status_id")
        if r.get("status_id") is not None
        else r.get("StatusId")
    )

    try:
        status_id = int(status_id)
    except (TypeError, ValueError):
        status_id = None

    if status_id in _STATUS_ID_MAP:
        return _STATUS_ID_MAP[status_id]

    # Safe default.
    return "reported"


def _status_label(status: str) -> str:
    """
    Human-readable status label used by Teacher.py.

    The actual ReportStatus database terminology is preserved.
    """
    labels = {
        "reported": "Reported",
        "repair": "Under repair",
        "fixed": "Fixed",
        "escalated": "Escalated",
        "followup": "Follow Up",
    }

    return labels.get(status, "Reported")


def _status_is_open(status: str) -> bool:
    """
    Determine whether a report is still active/open.

    Follow Up and Escalated remain active because the issue has not been
    marked Fixed.
    """
    return status in {
        "reported",
        "repair",
        "followup",
        "escalated",
    }


# ===========================================================================
# Data
# ===========================================================================


def _token() -> str | None:
    return ss.get(ui.TOKEN_KEY)


def _fetch() -> dict:
    """Load dashboard data from the backend."""
    token = _token()

    if not token:
        return D.empty_store(
            "Not connected — log out and log back in to load your data."
        )

    result = backend_client.get_teacher_dashboard(token)

    if not result.get("success"):
        return D.empty_store(
            f"Couldn't load data: {result.get('error') or 'unknown error'}. "
            "Use Refresh to try again."
        )

    ss[f"{P}_raw_computers"] = result.get("computers") or []
    ss.pop(f"{P}_cid_map", None)

    return _build_store(result)


def _build_store(result: dict) -> dict:
    """
    Convert the backend dashboard response into the store structure used
    by the Teacher UI.
    """

    s = D.empty_store()
    s["live"] = True

    # ------------------------------------------------------------------
    # Computers
    # ------------------------------------------------------------------
    for comp in result.get("computers") or []:

        lab = D.lab_of(
            comp.get("Room") or
            comp.get("room")
        )

        try:
            pc = int(
                comp.get("UnitNumber") or
                comp.get("unit_number") or
                0
            )
        except (TypeError, ValueError):
            continue

        if pc <= 0:
            continue

        hw_raw = comp.get("hardware") or {}

        # Same column -> label mapping as Admin/Technician; empty columns
        # are left out (no "None" values, no ids).
        hw = D.hardware_fields(hw_raw)

        sw_raw = comp.get("software") or []

        sw = [
            {
                "name": str(
                    item.get("SoftwareName")
                    or item.get("software_name")
                    or item.get("name")
                    or ""
                ),
                "version": str(
                    item.get("Version")
                    or item.get("version")
                    or ""
                ),
                "installed": str(
                    item.get("DateInstalled")
                    or item.get("date_installed")
                    or ""
                ),
            }
            for item in sw_raw
            if isinstance(item, dict)
        ]

        db_status = str(
            comp.get("Status")
            or comp.get("status")
            or "good"
        ).lower()

        rec_status = (
            "Under maintenance"
            if db_status == "issue"
            else "Inactive"
            if db_status == "replace"
            else "Working"
        )

        s["computers"][(lab, pc)] = D.new_computer(
            lab,
            pc,
            hw,
            sw,
            added=D.parse_dt(
                comp.get("CreatedAt")
                or comp.get("created_at")
            ),
            status=rec_status,
        )

    # ------------------------------------------------------------------
    # Reports
    # ------------------------------------------------------------------
    s["reports"] = [
        _report_from_db(r)
        for r in (result.get("reports") or [])
        if isinstance(r, dict)
    ]

    return s


def _report_from_db(r: dict) -> dict:
    """
    Convert a backend report into the structure expected by Teacher.py.

    Important:
        StatusId = 3 is ALWAYS Fixed.
        StatusId = 4 is ALWAYS Escalated.

    The function first uses the actual CurrentStatus text returned by the
    backend, then falls back to StatusId.
    """

    # Reports.CreatedAt as stored in the database (None when missing).
    # The Sent column uses this directly so it never shows today's date
    # for a report without a stored date.
    sent_at = D.parse_dt(
        r.get("created_at")
        or r.get("CreatedAt")
    )

    created = sent_at or D.now()

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------
    status = _status_from_report(r)

    # ------------------------------------------------------------------
    # Issues
    # ------------------------------------------------------------------
    issues = (
        r.get("issues")
        or r.get("Issues")
        or []
    )

    if isinstance(issues, str):
        issues = [
            i.strip()
            for i in issues.split(",")
            if i.strip()
        ]

    issue_str = (
        ", ".join(str(i) for i in issues)
        if issues
        else (
            r.get("issue")
            or r.get("Issue")
            or "Other"
        )
    )

    # ------------------------------------------------------------------
    # Laboratory / Computer
    # ------------------------------------------------------------------
    lab = D.lab_of(
        r.get("room")
        or r.get("Room")
    )

    try:
        pc = int(
            r.get("unit_number")
            or r.get("UnitNumber")
            or 0
        )
    except (TypeError, ValueError):
        pc = 0

    # ------------------------------------------------------------------
    # Reporter
    # ------------------------------------------------------------------
    reporter = str(
        r.get("reporter")
        or r.get("ReporterName")
        or r.get("reporter_name")
        or me()
    )

    # ------------------------------------------------------------------
    # Technician
    # ------------------------------------------------------------------
    handled_by_id = (
        r.get("handled_by")
        if r.get("handled_by") is not None
        else r.get("HandledBy")
    )

    tech_name_raw = (
        r.get("handled_by_name")
        or r.get("HandledByName")
        or r.get("technician_name")
        or r.get("TechnicianName")
        or ""
    )

    if str(tech_name_raw).strip():
        tech_name = str(tech_name_raw).strip()

    elif (
        handled_by_id is not None
        and str(handled_by_id).strip() not in ("", "0")
    ):
        tech_name = "Unknown technician"

    else:
        tech_name = None

    # ------------------------------------------------------------------
    # Resolution note
    # ------------------------------------------------------------------
    resolution_note = str(
        r.get("resolution_note")
        or r.get("ResolutionNote")
        or ""
    ).strip()

    # ------------------------------------------------------------------
    # History
    #
    # We only know the exact current StatusId from the dashboard row unless
    # teacher_service returns a full history. Therefore we build a display
    # history based on the current status.
    # ------------------------------------------------------------------
    history = [
        {
            "s": "reported",
            "t": created,
            "note": "Report sent",
        }
    ]

    if status == "repair":
        history.append(
            {
                "s": "repair",
                "t": created,
                "note": (
                    f"{tech_name or 'Technician'} "
                    "started the repair"
                ),
            }
        )

    elif status == "followup":
        history.append(
            {
                "s": "followup",
                "t": created,
                "note": (
                    resolution_note
                    or f"{tech_name or 'Technician'} "
                       "requested a follow up"
                ),
            }
        )

    elif status == "escalated":
        history.append(
            {
                "s": "escalated",
                "t": created,
                "note": (
                    resolution_note
                    or "Report escalated to the admin"
                ),
            }
        )

    elif status == "fixed":
        history.append(
            {
                "s": "fixed",
                "t": created,
                "note": (
                    resolution_note
                    or "Report marked as fixed"
                ),
            }
        )

    return {
        "id": str(
            r.get("report_id")
            or r.get("ReportId")
            or r.get("id")
            or "—"
        ),

        "db_id": (
            r.get("report_id")
            or r.get("ReportId")
        ),

        "lab": lab,
        "pc": pc,
        "issue": issue_str,

        "desc": str(
            r.get("comment")
            or r.get("Comment")
            or ""
        ),

        "by": reporter,
        "created": created,
        "sent": sent_at,

        # Normalized frontend status.
        "status": status,

        "urgency": "Normal",
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
    return ss.get(
        f"{P}_me",
        "Teacher",
    )


def mine(s: dict) -> list[dict]:
    """All reports returned by the teacher API."""

    return sorted(
        s["reports"],
        key=lambda r: r["created"],
        reverse=True,
    )


def view_report(rid: str) -> None:
    if any(
        r["id"] == rid
        for r in store()["reports"]
    ):
        open_modal("report", rid)
    else:
        toast(
            "That report is no longer available.",
            False,
        )


# ===========================================================================
# Report an issue
# ===========================================================================


def draft() -> dict:
    return ss.setdefault(
        f"{P}_draft",
        {
            "lab": None,
            "pc": None,
            "issue": None,
            "urg": "Normal",
            "desc": "",
            "step": "lab",
        },
    )


def _keep_desc() -> None:
    if _DESC in ss:
        draft()["desc"] = ss[_DESC]


def step_to(step: str) -> None:
    _keep_desc()
    draft()["step"] = step


def start_report(
    lab: int | None = None,
    pc: int | None = None,
) -> None:

    ss[f"{P}_draft"] = {
        "lab": lab,
        "pc": pc,
        "issue": None,
        "urg": "Normal",
        "desc": "",
        "step": (
            "problem"
            if lab and pc
            else "pc"
            if lab
            else "lab"
        ),
    }

    ss.pop(_DESC, None)

    go("report")


def pick_lab(lab: int) -> None:
    d = draft()

    d["lab"] = lab
    d["pc"] = None
    d["step"] = "pc"


def pick_map_pc(
    lab: int,
    pc: int,
) -> None:

    d = draft()

    d["lab"] = lab
    d["pc"] = None
    d["step"] = "pc"

    pick_pc(pc)


def pick_pc(pc: int) -> None:
    d = draft()

    comp = store()["computers"].get(
        (d["lab"], pc)
    )

    if comp and comp.get("status") == "Inactive":
        return toast(
            f"{D.pc_name(pc)} is not in use (inactive). "
            "Please tell the technician directly if it's needed.",
            False,
        )

    d["pc"] = pc


def pick(
    field: str,
    value: str,
) -> None:
    draft()[field] = value


def _submit() -> None:
    _keep_desc()

    d = draft()

    if not (
        d["lab"]
        and d["pc"]
        and d["issue"]
    ):
        return toast(
            "Pick the laboratory, the computer and the problem first.",
            False,
        )

    desc = (
        d["desc"]
        or ""
    ).strip()

    if (
        d["issue"] == "Other"
        and len(desc) < 5
    ):
        d["step"] = "problem"

        return toast(
            "Please describe the problem in Details "
            "when you choose “Other”.",
            False,
        )

    s = store()

    dup = next(
        (
            r
            for r in s["reports"]
            if (
                r["lab"] == d["lab"]
                and r["pc"] == d["pc"]
                and r["issue"] == d["issue"]
                and _status_is_open(r["status"])
            )
        ),
        None,
    )

    if dup:
        return toast(
            f"{D.pc_name(d['pc'])} was already reported for "
            f"“{d['issue']}” ({dup['id']}). "
            "You can follow it in My Reports.",
            False,
        )

    computer_id = _find_computer_id(
        d["lab"],
        d["pc"],
    )

    if computer_id is None:
        return toast(
            "Could not find that computer in the database. "
            "Please refresh and try again.",
            False,
        )

    result = backend_client.submit_teacher_report(
        _token(),
        computer_id=computer_id,
        issues=[d["issue"]],
        comment=desc,
    )

    if not result.get("success"):
        return toast(
            result.get("error")
            or "Could not send the report.",
            False,
        )

    refresh()

    inserted = result.get("report") or {}

    report_id = str(
        inserted.get("ReportId")
        or inserted.get("report_id")
        or "sent"
    )

    d["step"] = "done"
    d["sent"] = report_id

    toast("Report sent to the technicians")


def _find_computer_id(
    lab: int,
    pc: int,
) -> int | None:

    key = f"{P}_cid_map"

    if key not in ss:

        raw = ss.get(
            f"{P}_raw_computers"
        ) or []

        mapping: dict[
            tuple[int, int],
            int,
        ] = {}

        for comp in raw:

            l = D.lab_of(
                comp.get("Room")
                or comp.get("room")
            )

            try:
                p = int(
                    comp.get("UnitNumber")
                    or comp.get("unit_number")
                    or 0
                )

                cid = int(
                    comp.get("ComputerId")
                    or comp.get("computer_id")
                    or 0
                )

            except (
                TypeError,
                ValueError,
            ):
                continue

            if p > 0 and cid > 0:
                mapping[(l, p)] = cid

        ss[key] = mapping

    return ss[key].get(
        (
            int(lab),
            int(pc),
        )
    )


# ===========================================================================
# Dashboard
# ===========================================================================


def page_dashboard(
    s: dict,
    user: dict,
) -> None:

    m = mine(s)

    with box(
        f"{P}_hello",
        "cardh",
    ):

        html(
            f'<div class="hello" style="margin:0">'
            f'<div><h2>{portal.greeting()}, '
            f'{h(portal.first_name(user["name"]))}</h2>'
            "<p>Here's what's happening with the computers "
            "you reported.</p></div></div>"
        )

        btn(
            "Report an issue",
            f"{P}_hello_new",
            "primary",
            icon=":material/note_add:",
            on_click=start_report,
        )

    total = 0
    ok = 0

    for lab, _ in D.LABS:

        sm = D.lab_summary(
            s,
            lab,
        )

        total += sm["total"]
        ok += sm["ok"]

    portal.stats(
        stat(
            "alert",
            "ic-amber",
            sum(
                r["status"] == "reported"
                for r in m
            ),
            "Waiting for a technician",
        ),

        stat(
            "wrench",
            "ic-red",
            sum(
                r["status"]
                in (
                    "repair",
                    "followup",
                    "escalated",
                )
                for r in m
            ),
            "Being repaired",
        ),

        stat(
            "check",
            "ic-green",
            sum(
                r["status"] == "fixed"
                for r in m
            ),
            "Fixed",
        ),

        stat(
            "pc",
            "ic-blue",
            f"{round(ok / total * 100) if total else 0}%",
            "Lab computers working",
        ),
    )

    with box(
        f"{P}_dgrid",
        "gmap",
        "mt",
    ):

        with box(
            f"{P}_drecent",
            "card",
        ):

            with box(
                f"{P}_drecent_h",
                "cardh",
            ):

                html(
                    "<div><h3>My recent reports</h3></div>"
                )

                btn(
                    "See all",
                    f"{P}_drecent_all",
                    "link",
                    on_click=go,
                    args=("reports",),
                )

            recent = m[:5]

            if not recent:
                html(
                    empty(
                        "You haven't reported anything yet.",
                        "list",
                    )
                )

            for i, r in enumerate(recent):

                hit(
                    row(
                        "pc",
                        portal.tone(r["status"]),
                        h(r["issue"]),
                        f'{D.lab_name(r["lab"])} · '
                        f'{D.pc_name(r["pc"])} · '
                        f'{D.when(r["created"])}',
                        badge(r["status"]),
                        last=i == len(recent) - 1,
                        clickable=True,
                    ),
                    f"{P}_recent_{r['id']}",
                    view_report,
                    (r["id"],),
                )

        with box(
            f"{P}_dlabs",
            "card",
        ):

            with box(
                f"{P}_dlabs_h",
                "cardh",
            ):

                html(
                    "<div><h3>Laboratory status</h3></div>"
                )

                btn(
                    "Open map",
                    f"{P}_dlabs_map",
                    "link",
                    on_click=go,
                    args=("labs",),
                )

            portal.lab_tiles(
                P,
                s,
                "dash",
                open_lab,
            )


def open_lab(lab: int) -> None:
    ss[f"{P}_lab"] = lab
    ss[f"{P}_lsel"] = None

    go("labs")


def _stepper(step: str) -> None:

    order = [
        k
        for k, _
        in STEPS
    ]

    idx = (
        order.index(step)
        if step in order
        else len(order)
    )

    cells = ""

    for i, (_, label) in enumerate(STEPS):

        cls = (
            "st on"
            if i == idx
            else "st done"
            if i < idx
            else "st"
        )

        num = (
            "&#10003;"
            if i < idx
            else str(i + 1)
        )

        cells += (
            f'<div class="{cls}">'
            f'<span class="n">{num}</span>'
            f'<span class="t">{label}</span>'
            "</div>"
        )

    html(
        f'<div class="stepper">{cells}</div>'
    )


# ===========================================================================
# Report page
# ===========================================================================


def page_report(s: dict) -> None:

    d = draft()
    step = d["step"]

    _stepper(step)

    with box(
        f"{P}_step_{step}",
        "card",
    ):

        if step == "lab":

            html(
                '<div class="card-h">'
                "<div><h3>Which laboratory are you in?</h3>"
                '<div class="sub">Tap a computer on the map or '
                "pick the room from the list.</div></div></div>"
            )

            with box(
                f"{P}_r_grid",
                "gmap",
            ):

                with box(
                    f"{P}_r_mapcol",
                    "stack",
                ):

                    portal.live_map(
                        P,
                        s,
                        "rep",
                        pick_map_pc,
                        focus=d["lab"],
                    )

                with box(
                    f"{P}_r_tiles",
                    "stack",
                    "gap10",
                ):

                    for lab, _ in D.LABS:

                        hit(
                            lab_tile(
                                s,
                                lab,
                                on=d["lab"] == lab,
                            ),
                            f"{P}_rlab_{lab}",
                            pick_lab,
                            (lab,),
                        )

        elif step == "pc":

            html(
                f'<div class="card-h"><div><h3>'
                f'Which computer? <span class="muted" '
                f'style="font-weight:500">· '
                f'{D.lab_name(d["lab"])}</span></h3>'
                f'<div class="sub">The number is on the sticker '
                f'on the monitor or the system unit.</div>'
                "</div></div>"
            )

            with box(
                f"{P}_pcs",
                "pcgrid",
            ):

                for c in D.lab_computers(
                    s,
                    d["lab"],
                ):

                    stt = D.pc_status(
                        s,
                        d["lab"],
                        c["pc"],
                    )

                    label = D.computer_status_label(
                        stt
                    )[0]

                    on = (
                        " on"
                        if d["pc"] == c["pc"]
                        else ""
                    )

                    hit(
                        f'<div class="pc-btn s-{stt}{on}" '
                        f'title="{D.pc_name(c["pc"])} — {label}">'
                        f'{ic("pc")}'
                        f'{D.pad(c["pc"])}'
                        f'<small>{label}</small></div>',
                        f"{P}_pc_{c['pc']}",
                        pick_pc,
                        (c["pc"],),
                    )

            html(
                '<div class="legend" '
                'style="justify-content:flex-start;margin-top:14px">'
                '<span><i style="background:#8aa6d8"></i>Working</span>'
                '<span><i style="background:var(--rep)"></i>'
                "Already reported</span>"
                '<span><i style="background:var(--fix)"></i>'
                "Under repair</span>"
                "</div>"
            )

            r = (
                D.pc_report(
                    s,
                    d["lab"],
                    d["pc"],
                )
                if d["pc"]
                else None
            )

            if r:

                html(
                    f'<div class="demo-note mt">'
                    f'{ic("info")}<span>'
                    f'{D.pc_name(d["pc"])} was already reported '
                    f'{D.when(r["created"])} for '
                    f'<b>{h(r["issue"])}</b> '
                    f'({_status_label(r["status"]).lower()}). '
                    f"You can still send a report if it's a different "
                    f"problem.</span></div>"
                )

            with box(
                f"{P}_pc_btns",
                "stepacts",
            ):

                btn(
                    "Back",
                    f"{P}_pc_back",
                    "ghost",
                    icon=":material/arrow_back:",
                    on_click=step_to,
                    args=("lab",),
                )

                btn(
                    "Continue",
                    f"{P}_pc_next",
                    "primary",
                    disabled=not d["pc"],
                    on_click=step_to,
                    args=("problem",),
                )

        elif step == "problem":

            html(
                '<div class="card-h">'
                "<div><h3>What's wrong?</h3>"
                '<div class="sub">Pick the closest match, then add any '
                "details that help.</div></div></div>"
            )

            with box(
                f"{P}_issues",
                "issuegrid",
            ):

                for i, issue in enumerate(D.ISSUES):

                    hit(
                        f'<div class="issue'
                        f'{" on" if d["issue"] == issue else ""}'
                        f'">{h(issue)}</div>',
                        f"{P}_iss_{i}",
                        pick,
                        ("issue", issue),
                    )

            if _DESC not in ss:
                ss[_DESC] = d["desc"]

            with box(
                f"{P}_desc_wrap",
                "field",
            ):

                html(
                    '<div class="adm-label">Details '
                    '<span class="muted" style="font-weight:400">'
                    "(optional)</span></div>"
                )

                st.text_area(
                    "Details",
                    key=_DESC,
                    max_chars=400,
                    label_visibility="collapsed",
                    placeholder=(
                        "For example: the screen stays black "
                        "but the power light is on."
                    ),
                )

            html(
                '<div class="adm-label">How urgent is it?</div>'
            )

            with box(
                f"{P}_urg",
                "chips",
            ):

                for value, label in URGENCY:

                    btn(
                        label,
                        f"{P}_urg_{value}",
                        (
                            "chipon"
                            if d["urg"] == value
                            else "chip"
                        ),
                        on_click=pick,
                        args=("urg", value),
                    )

            with box(
                f"{P}_prob_btns",
                "stepacts",
            ):

                btn(
                    "Back",
                    f"{P}_prob_back",
                    "ghost",
                    icon=":material/arrow_back:",
                    on_click=step_to,
                    args=("pc",),
                )

                btn(
                    "Review report",
                    f"{P}_prob_next",
                    "primary",
                    disabled=not d["issue"],
                    on_click=step_to,
                    args=("review",),
                )

        elif step == "review":

            html(
                '<div class="card-h">'
                "<div><h3>Check your report</h3>"
                '<div class="sub">Make sure everything is right before '
                "you send it.</div></div></div>"
            )

            rows = (
                ("Reported by", me()),
                (
                    "Laboratory",
                    f'{D.lab_name(d["lab"])} '
                    f'({D.WING[d["lab"]]})',
                ),
                (
                    "Computer",
                    D.pc_name(d["pc"]),
                ),
                (
                    "Problem",
                    d["issue"],
                ),
                (
                    "Details",
                    (d["desc"] or "").strip() or "—",
                ),
                (
                    "Urgency",
                    d["urg"],
                ),
            )

            html(
                "".join(
                    f'<div class="review-row">'
                    f'<div class="review-label">{k}</div>'
                    f'<div class="review-value">{h(v)}</div>'
                    f"</div>"
                    for k, v in rows
                )
            )

            with box(
                f"{P}_rev_btns",
                "stepacts",
            ):

                btn(
                    "Edit",
                    f"{P}_rev_back",
                    "ghost",
                    icon=":material/arrow_back:",
                    on_click=step_to,
                    args=("problem",),
                )

                btn(
                    "Send report",
                    f"{P}_send",
                    "primary",
                    on_click=_submit,
                )

        else:

            r = next(
                (
                    x
                    for x in s["reports"]
                    if x["id"] == d.get("sent")
                ),
                None,
            )

            where = (
                f'{D.lab_name(r["lab"])} · '
                f'{D.pc_name(r["pc"])}'
                if r
                else "the computer"
            )

            html(
                f'<div class="success">'
                f'<div class="big">{ic("check")}</div>'
                f'<h3 style="font-size:22px">Report sent</h3>'
                f'<p class="muted" style="max-width:440px;'
                f'margin:8px auto 22px">'
                f'{h(d.get("sent") or "")} for {where} went to the '
                f"technicians. You'll see their updates in My Reports "
                f"and under the bell.</p></div>"
            )

            with box(
                f"{P}_done_btns",
                "row",
                "center",
            ):

                btn(
                    "Report another",
                    f"{P}_again",
                    "ghost",
                    on_click=start_report,
                )

                btn(
                    "View my reports",
                    f"{P}_mine",
                    "primary",
                    on_click=go,
                    args=("reports",),
                )


# ===========================================================================
# My Reports
# ===========================================================================


T_FILTERS = [
    ("all", "All"),
    ("reported", "Waiting"),
    ("repair", "Being repaired"),
    ("fixed", "Fixed"),
]


def _t_match(
    r: dict,
    f: str,
) -> bool:

    if f == "all":
        return True

    if f == "repair":
        return r["status"] in {
            "repair",
            "followup",
            "escalated",
        }

    return r["status"] == f


def page_reports(s: dict) -> None:

    m = mine(s)

    flt = ss.setdefault(
        f"{P}_tfilter",
        "all",
    )

    with box(
        f"{P}_tcard",
        "card",
        "pad0",
    ):

        with box(
            f"{P}_thead",
            "cardh",
            "padh",
        ):

            with box(
                f"{P}_tchips",
                "chips",
            ):

                for key, label in T_FILTERS:

                    btn(
                        f"{label} · "
                        f"{sum(_t_match(r, key) for r in m)}",
                        f"{P}_tf_{key}",
                        (
                            "chipon"
                            if flt == key
                            else "chip"
                        ),
                        on_click=lambda k=key:
                            ss.__setitem__(
                                f"{P}_tfilter",
                                k,
                            ),
                    )

            with box(
                f"{P}_tctl",
                "row",
            ):

                how = sort_select(
                    f"{P}_t_sort__selwide__",
                    {
                        k: f"Sort: {v}"
                        for k, v
                        in D.MY_REPORT_SORTS.items()
                    },
                )

                btn(
                    "New report",
                    f"{P}_tnew",
                    "primarysm",
                    icon=":material/note_add:",
                    on_click=start_report,
                )

        rows = D.sort_reports(
            [
                r
                for r in m
                if _t_match(r, flt)
            ],
            how,
        )

        cols = (
            "grid-template-columns:"
            "96px minmax(0,1fr) "
            "minmax(0,1.2fr) "
            "minmax(0,1fr) "
            "150px 92px;"
        )

        html(
            f'<div class="tt-head" style="{cols}">'
            "<div>Report</div>"
            "<div>Computer</div>"
            "<div>Problem</div>"
            "<div>Sent</div>"
            "<div>Status</div>"
            "<div>&nbsp;</div>"
            "</div>"
        )

        if not rows:
            html(
                empty(
                    "No reports here.",
                    "list",
                )
            )

        for r in rows:

            hit(
                f'<div class="tt-row" style="{cols}">'
                f'<div class="strong">{h(r["id"])}</div>'
                f'<div>{D.lab_name(r["lab"])}'
                f'<div class="small">{D.pc_name(r["pc"])}</div></div>'
                f'<div>{h(r["issue"])}</div>'
                f'<div>{D.sent_date(r.get("sent", r["created"]))}</div>'
                f'<div>{badge(r["status"])}</div>'
                f'<div style="text-align:right">'
                f'<span class="fakebtn">View</span>'
                f"</div></div>",
                f"{P}_t_{r['id']}",
                view_report,
                (r["id"],),
            )


# ===========================================================================
# Laboratory Status
# ===========================================================================


def _show_pc(
    lab: int,
    pc: int,
) -> None:

    ss[f"{P}_lsel"] = (
        lab,
        pc,
    )

    ss[f"{P}_lab"] = lab


def _focus(lab: int) -> None:

    ss[f"{P}_lab"] = (
        None
        if ss.get(f"{P}_lab") == lab
        else lab
    )

    ss[f"{P}_lsel"] = None


def page_labs(s: dict) -> None:

    focus = ss.get(f"{P}_lab")
    sel = ss.get(f"{P}_lsel")

    with box(
        f"{P}_lgrid",
        "gmap",
    ):

        with box(
            f"{P}_lmap",
            "card",
        ):

            html(
                '<div class="card-h">'
                "<div><h3>Centrum Laboratory</h3>"
                '<div class="sub">Hover a computer to see its status. '
                "Click one to report it.</div></div></div>"
            )

            portal.live_map(
                P,
                s,
                "labs",
                _show_pc,
                focus=focus,
                sel=tuple(sel) if sel else None,
            )

        with box(
            f"{P}_lside",
            "stack",
            "gap10",
        ):

            for lab, _ in D.LABS:

                hit(
                    lab_tile(
                        s,
                        lab,
                        on=focus == lab,
                    ),
                    f"{P}_ltile_{lab}",
                    _focus,
                    (lab,),
                )

            if sel:

                lab, pc = sel

                r = D.pc_report(
                    s,
                    lab,
                    pc,
                )

                with box(
                    f"{P}_lpc",
                    "card",
                ):

                    status_badge = (
                        badge(r["status"])
                        if r
                        else '<span class="badge b-fixed">Working</span>'
                    )

                    description = (
                        f'<p class="muted" style="margin:0 0 14px">'
                        f'{h(r["issue"])} — reported '
                        f'{D.when(r["created"])}.</p>'
                        if r
                        else '<p class="muted" style="margin:0 0 14px">'
                             "No open reports for this computer.</p>"
                    )

                    html(
                        f'<div class="pc-panel">'
                        f'<div class="ph">'
                        f'<div class="ic '
                        f'{"ic-amber" if r else "ic-blue"}">'
                        f'{ic("pc")}</div>'
                        f"<div><h3>"
                        f"{D.lab_name(lab)} · "
                        f"{D.pc_name(pc)}"
                        f"</h3>"
                        f"{status_badge}"
                        f"</div></div>"
                        f"{description}"
                        f"</div>"
                    )

                    with box(
                        f"{P}_lpc_btn",
                        "row",
                    ):

                        btn(
                            "Report this computer",
                            f"{P}_lpc_report",
                            "primary",
                            icon=":material/add:",
                            on_click=start_report,
                            args=(lab, pc),
                        )


# ===========================================================================
# Profile
# ===========================================================================


def _save_number(
    number: str,
) -> tuple[bool, str]:

    token = _token()

    if not token:
        return (
            False,
            "Not connected to the server — "
            "log out and log back in to save your contact number.",
        )

    result = backend_client.update_teacher_contact(
        token,
        number,
    )

    if not result.get("success"):
        return (
            False,
            result.get("error")
            or "Could not save the contact number.",
        )

    saved = (
        result.get("user")
        if isinstance(
            result.get("user"),
            dict,
        )
        else {}
    )

    ui.set_contact_number(
        saved.get("contact_number")
        or saved.get("ContactNumber")
        or number
    )

    return (
        True,
        result.get("message")
        or "Contact number updated.",
    )


def page_profile(
    s: dict,
    user: dict,
) -> None:

    SHELL.profile_head(
        user,
        "Teacher",
        "Active account",
    )

    with box(
        f"{P}_pf_grid",
        "g2",
        "mt",
    ):

        with box(
            f"{P}_pf_contact",
            "card",
        ):

            SHELL.contact_card(
                user,
                _save_number,
            )

        with box(
            f"{P}_pf_act",
            "card",
        ):

            items = sorted(
                (
                    (r, e)
                    for r in mine(s)
                    for e in r["history"]
                ),
                key=lambda x: x[1]["t"],
                reverse=True,
            )[:5]

            icons = {
                "fixed": "check",
                "reported": "plus",
                "repair": "wrench",
                "escalated": "up",
                "followup": "wrench",
            }

            body = "".join(
                row(
                    icons.get(
                        e["s"],
                        "wrench",
                    ),
                    "ic-blue",
                    f'{_status_label(e["s"])} · '
                    f'{D.lab_name(r["lab"])} '
                    f'{D.pc_name(r["pc"])}',
                    f'{e["note"]} · '
                    f'{D.when(e["t"])}',
                    last=i == len(items) - 1,
                )
                for i, (r, e)
                in enumerate(items)
            )

            html(
                '<div class="card-h"><h3>My activity</h3></div>'
                +
                (
                    f'<div class="rows" style="margin-bottom:16px">'
                    f'{body}</div>'
                    if body
                    else empty(
                        "Nothing yet.",
                        "list",
                    )
                )
            )

            SHELL.logout_button()


# ===========================================================================
# Pop-up windows
# ===========================================================================


def render_modal(s: dict) -> None:

    kind, ref = SHELL.modal

    if kind == "report":

        r = next(
            (
                x
                for x in s["reports"]
                if x["id"] == ref
            ),
            None,
        )

        if r is None:
            return close_modal()

        with SHELL.window():

            html(
                portal.report_details(r)
            )

            with box(
                f"{P}_m_act",
                "mactions",
            ):

                btn(
                    "Close",
                    f"{P}_m_close",
                    "ghost",
                    on_click=close_modal,
                )

    elif kind and not SHELL.common_modal(kind):
        close_modal()


# ===========================================================================
# Centrum Assistant
# ===========================================================================


BOT_CONFIG = {
    "names": {
        "report": "Report an Issue",
        "myreports": "My Reports",
        "inventory": "Laboratory Status",
        "settings": "My Profile",
    },

    "pages": {
        "report": "report",
        "myreports": "reports",
        "inventory": "labs",
        "settings": "profile",
    },

    "status_groups": [
        (
            "waiting for a technician",
            {"reported"},
        ),
        (
            "being repaired",
            {"repair", "followup"},
        ),
        (
            "escalated to the admin",
            {"escalated"},
        ),
        (
            "fixed",
            {"fixed"},
        ),
    ],

    "status_help": (
        "**Reported** - your report is waiting for a technician to pick it up.\n"
        "**Under repair** - a technician is working on the computer.\n"
        "**Follow Up** - the technician needs a follow-up action before the report can be completed.\n"
        "**Escalated** - it needs parts, a replacement or the admin's decision; it's still being handled.\n"
        "**Fixed** - the computer is working again."
    ),

    "report_howto": (
        "1. Open **{report}**.\n"
        "2. Pick the laboratory (tap the map or the list).\n"
        "3. Pick the computer - the number is on the sticker on the monitor or system unit.\n"
        "4. Choose what's wrong, add details and how urgent it is.\n"
        "5. Check everything and press **Send report**.\n"
        "Your name and the time are added automatically."
    ),

    "inventory_help": (
        "Open **{inventory}** to see the live floor map: "
        "hover a computer for its status, or click it to see it and report it."
    ),

    "contact_help": (
        "You can update your contact number in **{settings}**."
    ),

    "password_help": (
        "Log out, then use **Forgot password?** on the login screen "
        "to get a reset code by email."
    ),

    "urgent_help": (
        'When you report it, choose **High - class is using it now** '
        'under "How urgent is it?". Technicians see urgent reports first.'
    ),

    "wait_help": (
        "I can't promise a time - technicians work through the queue, "
        "urgent reports first. Watch the status in {myreports}; you also "
        "get a notification under the bell when it changes."
    ),
}


def _bot_reports(
    s: dict,
) -> list[dict]:

    """My reports, newest first, for the assistant."""

    return [
        {
            "id": r["id"],
            "where": (
                f"{D.lab_name(r['lab'])} · "
                f"{D.pc_name(r['pc'])}"
            ),
            "issue": r["issue"],
            "status": r["status"],
            "date": D.date_time(r["created"]),
        }
        for r in mine(s)
    ]


# ===========================================================================
# Notifications
# ===========================================================================


def _notifications(
    s: dict,
) -> list[dict]:

    """
    Build notifications from database-backed report status.

    Statuses:
        repair
        followup
        escalated
        fixed
    """

    icons = {
        "repair": (
            "wrench",
            "ic-red",
        ),

        "followup": (
            "wrench",
            "ic-amber",
        ),

        "escalated": (
            "up",
            "ic-violet",
        ),

        "fixed": (
            "check",
            "ic-green",
        ),
    }

    out = []

    for r in mine(s):

        for i, e in enumerate(
            r["history"][1:],
            start=1,
        ):

            icon, tone_cls = icons.get(
                e["s"],
                (
                    "bell",
                    "ic-blue",
                ),
            )

            out.append(
                {
                    "id": (
                        f"upd:{r['id']}:{i}"
                    ),

                    "icon": icon,

                    "tone": tone_cls,

                    "title": (
                        f"{r['id']} · "
                        f"{D.lab_name(r['lab'])} "
                        f"{D.pc_name(r['pc'])} "
                        f"is "
                        f"{_status_label(e['s']).lower()}"
                    ),

                    "sub": e["note"],

                    "t": e["t"],

                    "cb": view_report,

                    "args": (
                        r["id"],
                    ),

                    "roles": [
                        "teacher"
                    ],
                }
            )

    return out


# ===========================================================================
# Public entry point
# ===========================================================================


def render(
    user: dict | None = None,
) -> None:

    ui.page_config(ROLE)

    user = ui.require_user(
        user,
        ROLE,
        (
            ROLE.lower(),
        ),
    )

    ss[f"{P}_me"] = user["name"]

    s = store()

    page = SHELL.page

    SHELL.frame(
        user,
        s,
        {
            "reports": sum(
                _status_is_open(r["status"])
                for r in mine(s)
            )
        },
        _notifications(s),
    )

    with SHELL.content():

        if (
            s.get("notice")
            and page not in ("profile",)
        ):

            with box(
                f"{P}_notice",
                "row",
                "spread",
            ):

                html(
                    f'<div class="demo-note" '
                    f'style="margin:0">'
                    f'{ic("info")}'
                    f'<span>{h(s["notice"])}</span>'
                    f"</div>"
                )

                btn(
                    "Refresh",
                    f"{P}_refresh",
                    "ghostsm",
                    icon=":material/refresh:",
                    on_click=refresh,
                )

            html(
                '<div style="height:18px"></div>'
            )

        if page == "report":
            page_report(s)

        elif page == "reports":
            page_reports(s)

        elif page == "labs":
            page_labs(s)

        elif page == "profile":
            page_profile(
                s,
                user,
            )

        else:
            page_dashboard(
                s,
                user,
            )

        render_modal(s)

    chatbot.render(
        P,
        user,
        _bot_reports(s),
        navigate=go,
        config=BOT_CONFIG,
    )