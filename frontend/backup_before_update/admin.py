"""
frontend/admin.py - Centrum Laboratory | Admin dashboard (Streamlit)

Admin dashboard for the Centrum Laboratory Computer Monitoring System.

Architecture
------------
Admin.py
    ↓
backend_client.py
    ↓
FastAPI main.py
    ↓
admin_service.py
    ↓
repository/database layer
    ↓
Supabase PostgreSQL

Important
---------
- Supabase PostgreSQL is the source of truth.
- Admin does NOT maintain a separate database or local copy.
- Admin does NOT directly access Supabase.
- Streamlit session state is used only for UI state/cache.
- lab_store.py is NOT used by Admin as a persistence layer.
- Teacher and Technician records are read from the same database records.
- Existing Admin UI/layout is preserved.

Pages
-----
Dashboard
Reports
Inventory
Analytics
Escalation
User Requests
My Profile

How it is opened:

    from frontend import admin
    admin.render(user)
"""

from __future__ import annotations

import logging

from datetime import timedelta

import streamlit as st

from . import backend_client
from . import inventory
from . import lab_data as D
from . import portal
from . import ui

from frontend.portal import (
    PER,
    badge,
    bars_h,
    bars_v,
    ic,
    lab_tile,
    pager,
    sort_select,
    stat,
)

# ===========================================================================
# Configuration
# ===========================================================================

ROLE = "Admin"

ALLOWED_ROLES = (
    "admin",
    "administrator",
)

P = "admin"

ss = st.session_state

logger = logging.getLogger(__name__)


# ===========================================================================
# Safe collection accessors
# ===========================================================================
#
# WHY THESE EXIST
# ---------------
# `dict.get(key, default)` only returns `default` when the key is ABSENT.
# When the key is PRESENT but holds `None`, it returns `None`.
#
# That matters here because the Admin API legitimately returns `None` for a
# collection it could not load. `admin_service.get_dashboard_data()` does:
#
#       except DatabaseError as error:
#           requests = None          # <-- key present, value None
#
# So `_rows(s, "requests")` yields `None`, not `[]`, and the next line
#
#       sum(u.get("st") == "pending" for u in _rows(s, "requests"))
#
# raises `TypeError: 'NoneType' object is not iterable` and the whole Admin
# page fails to render instead of degrading gracefully.
#
# This is the same class of defect as the backend bug that produced
# "0 out of 0 computers": a default that is applied on key-absence but not on
# an explicit null. These helpers close that gap in one place.
# ===========================================================================

def _as_list(value) -> list:
    """
    Coerce a backend collection into a list.

    Returns [] for None, for a missing value, or for any non-sequence,
    so callers can always iterate safely.
    """

    if isinstance(value, list):
        return value

    if isinstance(value, tuple):
        return list(value)

    return []


def _rows(source: dict | None, key: str) -> list:
    """
    Read a collection out of the Admin store.

    Safe when:
        - `source` is not a dict
        - `key` is absent
        - `key` is present but holds None
    """

    if not isinstance(source, dict):
        return []

    return _as_list(source.get(key))


def _created(r: dict):
    """
    Return a report's creation timestamp, or None when it is missing.

    Several places previously used `r["created"]` directly, which raises
    KeyError on a record the backend returned without that field.
    """

    if not isinstance(r, dict):
        return None

    return r.get("created")


def _has_computer(s: dict, lab, pc) -> bool:
    """
    Report whether a given (lab, pc) exists in the loaded computer data.

    The Admin store historically holds `computers` as a dict keyed by
    (lab, pc) tuples, but the backend's convenience field returns a LIST of
    computer records. Accept either shape so the "View computer" action does
    not silently disappear when the backend format changes.
    """

    computers = None

    if isinstance(s, dict):
        computers = s.get("computers")

    if isinstance(computers, dict):
        return (lab, pc) in computers

    if isinstance(computers, (list, tuple)):
        for c in computers:
            if not isinstance(c, dict):
                continue

            c_lab = c.get("lab", c.get("room"))
            c_pc = c.get("pc", c.get("number", c.get("unit_number")))

            if c_lab == lab and c_pc == pc:
                return True

    return False


PAGES = [
    ("dashboard", "Dashboard", "home"),
    ("reports", "Reports", "list"),
    ("inventory", "Inventory", "box"),
    ("analytics", "Analytics", "chart"),
    ("escalation", "Escalation", "up"),
    ("requests", "User Requests", "users"),
    ("profile", "My Profile", "user"),
]


SHELL = portal.Shell(P, ROLE, PAGES)

go = SHELL.go
open_modal = SHELL.open_modal
close_modal = SHELL.close_modal
toast = SHELL.toast

html = ui.html
btn = ui.btn
hit = ui.hit
box = ui.box
h = ui.h


# ===========================================================================
# Data loading
# ===========================================================================

def _empty_store(message: str = "") -> dict:
    """
    Create an empty UI store.

    This is only a UI fallback.

    It is NOT a database and must never be used as the permanent
    source of truth.
    """
    return D.empty_store(message)


def _fetch(token: str | None, preview: bool) -> dict:
    """
    Load Admin data from the backend.

    Normal flow:

        Admin
          ↓
        backend_client.get_admin_data()
          ↓
        GET /admin/dashboard
          ↓
        admin_service
          ↓
        repositories
          ↓
        Supabase PostgreSQL

    No local JSON or lab_store persistence is used here.
    """

    if preview:
        return _empty_store()

    if not token:
        return _empty_store(
            "Not connected to the server. "
            "Log out and log in again to load the latest Admin data."
        )

    try:
        result = backend_client.get_admin_data(token)
    except Exception:
        return _empty_store(
            "Could not connect to the server. "
            "Please try again."
        )

    if not result.get("success"):
        return _empty_store(
            result.get("error")
            or "Could not load Admin data. Please try again."
        )

    # -------------------------------------------------------------------
    # Diagnostic logging for the computer-count data path.
    #
    # This logs SHAPES AND COUNTS ONLY -- never tokens, passwords, emails
    # or record contents. It exists to show where the chain breaks:
    #
    #   backend JSON -> D.live_store() -> s -> D.lab_summary() -> counts
    #
    # If the backend reports computers here but the dashboard still shows
    # 0, the break is inside D.live_store()/D.lab_summary() in lab_data.py.
    # -------------------------------------------------------------------

    lab_payload = result.get("lab")

    if not isinstance(lab_payload, dict):
        lab_payload = {}

    logger.info(
        "Admin backend payload: "
        "lab.units=%d, lab.computers=%d, top-level computers=%d, "
        "reports=%d, requests=%s, problems=%s",
        len(_as_list(lab_payload.get("units"))),
        len(_as_list(lab_payload.get("computers"))),
        len(_as_list(result.get("computers"))),
        len(_as_list(lab_payload.get("reports"))),
        (
            "None"
            if result.get("requests") is None
            else len(_as_list(result.get("requests")))
        ),
        result.get("problems") or [],
    )

    try:
        built = D.live_store(result)
    except Exception:
        logger.exception(
            "D.live_store() raised while building the Admin store."
        )

        return _empty_store(
            "The server returned data that could not be displayed."
        )

    store_computers = (
        built.get("computers")
        if isinstance(built, dict)
        else None
    )

    logger.info(
        "Admin store built by D.live_store(): "
        "computers type=%s, computers len=%s, reports=%d, requests=%s",
        type(store_computers).__name__,
        (
            len(store_computers)
            if isinstance(store_computers, (list, tuple, dict))
            else "n/a"
        ),
        len(_rows(built, "reports")),
        (
            "None"
            if isinstance(built, dict)
            and built.get("requests") is None
            else len(_rows(built, "requests"))
        ),
    )

    return built


def store() -> dict:
    """
    Return the current Admin data.

    The cached object is only a Streamlit UI cache.

    The actual source of truth is Supabase through the backend.
    """

    key = f"{P}_data"

    if key not in ss:
        token = ss.get(ui.TOKEN_KEY)
        preview = ss.get(f"{P}_preview", False)

        with st.spinner("Loading lab data..."):
            ss[key] = _fetch(token, preview)

    return ss[key]


def refresh() -> None:
    """
    Clear the Admin UI cache.

    The next call to store() retrieves fresh data from the backend.
    """

    ss.pop(f"{P}_data", None)

    toast("Data refreshed")


def me() -> str:
    """
    Display name used for UI labels.

    This is not used for authorization.
    Authorization is performed by the backend using the access token.
    """

    return ss.get(f"{P}_me", "Admin")


# ===========================================================================
# Inventory
# ===========================================================================
#
# Inventory is being migrated separately.
#
# Keep the existing Inventory UI integration here, but Admin.py no longer
# performs local persistence itself.
#
# The next migration step will update inventory.py so that its CRUD operations
# use backend_client -> FastAPI -> repositories -> Supabase.
# ===========================================================================

INV = inventory.Inventory(
    SHELL,
    store,
    me,
    ROLE,
)

open_pc = INV.open_pc


# ===========================================================================
# Navigation callbacks
# ===========================================================================

def _reset_page(key: str) -> None:
    ss[key] = 0


def lab_reports(lab: int) -> None:
    ss[f"{P}_r_lab__sel__"] = lab
    ss[f"_keep_{P}_r_lab__sel__"] = lab
    ss[f"{P}_rfilter"] = "open"
    ss[f"{P}_rpage"] = 0

    go("reports")


# ===========================================================================
# Counts
# ===========================================================================

def _counts(s: dict) -> dict:
    """
    Calculate sidebar/header notification counts from the current
    backend-loaded Admin data.

    No local database is used.
    """

    reports = _rows(s, "reports")
    requests = _rows(s, "requests")

    return {
        "escalation": sum(
            r.get("status") == "escalated"
            for r in reports
        ),
        "requests": sum(
            u.get("st") == "pending"
            for u in requests
        ),
    }


# ===========================================================================
# Report helpers
# ===========================================================================

def _open_report(rid: str) -> None:
    """
    Open a report that exists in the currently loaded backend data.
    """

    reports = _rows(store(), "reports")

    if any(str(r.get("id")) == str(rid) for r in reports):
        open_modal("report", rid)
        return

    toast(
        "That report is no longer available. Refresh the data.",
        False,
    )


def _notifications(s: dict) -> list[dict]:
    """
    Build Admin notifications from backend-loaded data.

    Notifications are UI objects only.

    They are NOT persisted through lab_store.py.
    """

    out: list[dict] = []

    # ---------------------------------------------------------------
    # Escalated reports
    # ---------------------------------------------------------------

    for r in _rows(s, "reports"):

        if r.get("status") != "escalated":
            continue

        history = r.get("history") or []

        escalation_times = [
            e.get("t")
            for e in history
            if e.get("s") == "escalated"
            and e.get("t") is not None
        ]

        created = r.get("created") or D.now()

        latest_escalation = max(
            escalation_times,
            default=created,
        )

        lab = r.get("lab")
        pc = r.get("pc")

        out.append(
            {
                "id": f"esc:{r.get('id')}:{latest_escalation:%Y%m%d%H%M%S}",
                "icon": "up",
                "tone": "ic-violet",
                "title": (
                    f"Escalation · "
                    f"{D.lab_name(lab)} {D.pc_name(pc)}"
                ),
                "sub": (
                    r.get("esc_note")
                    or r.get("issue")
                    or "Escalated report"
                ),
                "t": latest_escalation,
                "cb": _open_report,
                "args": (r.get("id"),),
                "roles": ["admin"],
            }
        )

    # ---------------------------------------------------------------
    # Pending account requests
    # ---------------------------------------------------------------

    for u in _rows(s, "requests"):

        if u.get("st") != "pending":
            continue

        requested_at = u.get("t") or D.now()

        name = u.get("name") or "User"
        role = u.get("role") or ""
        dept = u.get("dept") or ""

        subtitle = f"{role} · {dept}".strip(" ·")

        out.append(
            {
                "id": f"req:{u.get('id')}",
                "icon": "users",
                "tone": "ic-violet",
                "title": f"Account request · {name}",
                "sub": subtitle,
                "t": requested_at,
                "cb": go,
                "args": ("requests",),
                "roles": ["admin"],
            }
        )

    return out


# ===========================================================================
# Admin escalation decisions
# ===========================================================================

_DECISIONS = {
    "approve": (
        "Approve the replacement?",
        "The report goes back to the technician as approved, under repair.",
        "Approve replacement",
    ),
    "resolve": (
        "Mark this report resolved?",
        "The report is closed as fixed and the teacher can see it.",
        "Mark resolved",
    ),
    "back": (
        "Send it back to the technician?",
        "The report goes back to 'Under repair' without a decision.",
        "Send back",
    ),
}


def _ask_decide(rid: str, what: str) -> None:
    """
    Display confirmation before changing an escalated report.

    Actual persistence is handled by the backend.
    """

    if what not in _DECISIONS:
        toast("Invalid escalation decision.", False)
        return

    title, text, label = _DECISIONS[what]

    SHELL.confirm(
        title,
        f"{rid}: {text}",
        label,
        _decide,
        (rid, what),
        danger=False,
    )


def _decide(rid: str, what: str) -> None:
    """
    Submit an Admin escalation decision to the backend.

    IMPORTANT:
    There is intentionally NO lab_store.lock(),
    lab_store.save(), or local database write here.

    The next backend_client.py revision will provide:

        backend_client.admin_decide_escalation(...)

    which will call the Admin API and ultimately update Supabase.
    """

    s = store()

    report = next(
        (
            x
            for x in _rows(s, "reports")
            if str(x.get("id")) == str(rid)
        ),
        None,
    )

    if report is None:
        return toast(
            "That report is no longer available. Refresh the data.",
            False,
        )

    if report.get("status") != "escalated":
        return toast(
            f"{rid} was already handled. Refresh the data.",
            False,
        )

    token = ss.get(ui.TOKEN_KEY)

    if not token:
        return toast(
            "Your session has expired. Please log in again.",
            False,
        )

    try:
        result = backend_client.admin_decide_escalation(
            token,
            report_id=rid,
            decision=what,
        )
    except AttributeError:
        return toast(
            "The Admin escalation API is not available yet.",
            False,
        )
    except Exception:
        return toast(
            "Could not update the escalation.",
            False,
        )

    if not result.get("success"):
        return toast(
            result.get("error")
            or "Could not update the escalation.",
            False,
        )

    # Do not manually modify the report as a permanent local record.
    #
    # Clear the cache so the next render retrieves the actual state from
    # Supabase.
    ss.pop(f"{P}_data", None)

    message = result.get("message")

    if not message:
        message = {
            "approve": f"{rid} approved and returned to the technician.",
            "resolve": f"{rid} marked as resolved.",
            "back": f"{rid} sent back to the technician.",
        }.get(
            what,
            f"{rid} updated.",
        )

    toast(message)

    close_modal()


# ===========================================================================
# User account requests
# ===========================================================================

def _set_request(uid, st_: str) -> None:
    """
    Approve or reject a user account through the backend.

    The backend is responsible for:
        - authorization
        - loading the actual user
        - validating the current status
        - changing Users.Status
        - persisting the change to Supabase
    """

    s = store()

    user_request = next(
        (
            x
            for x in _rows(s, "requests")
            if str(x.get("id")) == str(uid)
        ),
        None,
    )

    if user_request is None:
        close_modal()

        return toast(
            "That account request is no longer available. Refresh the data.",
            False,
        )

    if user_request.get("st") != "pending":
        close_modal()

        return toast(
            "That request was already handled.",
            False,
        )

    if not s.get("live"):
        close_modal()

        return toast(
            "Not connected to the server. "
            "Log in again to manage account requests.",
            False,
        )

    if st_ == "active":
        decision = "approve"
    elif st_ in ("rejected", "cancelled", "inactive"):
        decision = "cancel"
    else:
        close_modal()

        return toast(
            "Invalid account request decision.",
            False,
        )

    token = ss.get(ui.TOKEN_KEY)

    if not token:
        close_modal()

        return toast(
            "Your session has expired. Please log in again.",
            False,
        )

    try:
        result = backend_client.decide_user_request(
            token,
            uid,
            decision,
            "",
        )
    except Exception:
        close_modal()

        return toast(
            "Could not update the account request.",
            False,
        )

    if not result.get("success"):
        close_modal()

        return toast(
            result.get("error")
            or "Could not save the decision.",
            False,
        )

    # The backend is now the source of truth.
    #
    # Clear cached Admin data instead of changing the local request object.
    ss.pop(f"{P}_data", None)

    name = user_request.get("name") or "User"

    if decision == "approve":
        default_message = (
            f"{name} confirmed — they can log in now."
        )
    else:
        default_message = (
            f"{name}'s request was cancelled."
        )

    toast(
        result.get("message")
        or default_message
    )

    close_modal()


# ===========================================================================
# Profile
# ===========================================================================

def _save_number(number: str) -> tuple[bool, str]:
    """
    Update Admin contact number through the backend.
    """

    s = store()

    if not s.get("live"):
        return (
            False,
            "Not connected to the server. "
            "Log in again to change your contact number.",
        )

    token = ss.get(ui.TOKEN_KEY)

    if not token:
        return (
            False,
            "Your session has expired. Please log in again.",
        )

    try:
        result = backend_client.admin_update_contact_number(
            token,
            number,
        )
    except Exception:
        return (
            False,
            "Could not update the contact number.",
        )

    if not result.get("success"):
        return (
            False,
            result.get("error")
            or "Could not save the number.",
        )

    saved = result.get("user")

    if isinstance(saved, dict):
        ui.set_contact_number(
            saved.get(
                "contact_number",
                number,
            )
        )
    else:
        ui.set_contact_number(number)

    return (
        True,
        result.get("message")
        or "Contact number updated.",
    )


def _change_password(
    current: str,
    new: str,
) -> tuple[bool, str]:
    """
    Change Admin password through the backend.
    """

    s = store()

    if not s.get("live"):
        return (
            False,
            "Not connected to the server. "
            "Log in again to change your password.",
        )

    token = ss.get(ui.TOKEN_KEY)

    if not token:
        return (
            False,
            "Your session has expired. Please log in again.",
        )

    try:
        result = backend_client.admin_change_password(
            token,
            current,
            new,
        )
    except Exception:
        return (
            False,
            "Could not change the password.",
        )

    if not result.get("success"):
        return (
            False,
            result.get("error")
            or "Could not change the password.",
        )

    return (
        True,
        result.get("message")
        or "Password updated.",
    )


# ===========================================================================
# Dashboard
# ===========================================================================

def page_dashboard(
    s: dict,
    user: dict,
) -> None:

    with box(
        f"{P}_hello",
        "cardh",
    ):
        html(
            f'<div class="hello" style="margin:0">'
            f'<div>'
            f'<h2>Welcome back, {h(user["name"])}</h2>'
            f"<p>An overview of all four Centrum laboratories.</p>"
            f"</div>"
            f"</div>"
        )

        with box(
            f"{P}_hello_btns",
            "row",
        ):
            btn(
                "Account requests",
                f"{P}_hello_req",
                "ghost",
                icon=":material/group:",
                on_click=go,
                args=("requests",),
            )

            btn(
                "Escalations",
                f"{P}_hello_esc",
                "primary",
                icon=":material/arrow_upward:",
                on_click=go,
                args=("escalation",),
            )

    # ------------------------------------------------------------------
    # Computer statistics
    # ------------------------------------------------------------------

    total = 0
    ok = 0

    per_lab: list[str] = []

    for lab, _ in D.LABS:
        summary = D.lab_summary(
            s,
            lab,
        )

        if not isinstance(summary, dict):
            summary = {}

        lab_total = summary.get("total") or 0
        lab_ok = summary.get("ok") or 0

        total += lab_total
        ok += lab_ok

        per_lab.append(
            f"{D.lab_name(lab)}={lab_ok}/{lab_total}"
        )

    # Counts only -- no record contents. If this logs 0/0 for every lab while
    # the backend payload logged a non-zero computer count in _fetch(), then
    # D.lab_summary() in lab_data.py is where the data is being lost.
    logger.info(
        "Admin dashboard computer counts: total=%d, ok=%d, per-lab: %s",
        total,
        ok,
        ", ".join(per_lab),
    )

    pending = sum(
        u.get("st") == "pending"
        for u in _rows(s, "requests")
    )

    open_count = len(
        D.open_reports(s)
    )

    html(
        '<div class="grid g4">'
        + stat(
            "pc",
            "ic-blue",
            total,
            f"Computers in {len(D.LABS)} laboratories",
        )
        + stat(
            "check",
            "ic-green",
            (
                f"{round(ok / total * 100)}%"
                if total
                else "0%"
            ),
            f"{ok} of {total} computers working",
        )
        + stat(
            "alert",
            "ic-amber",
            open_count,
            "Open reports",
        )
        + stat(
            "users",
            "ic-violet",
            pending,
            "Accounts waiting for approval",
        )
        + "</div>"
    )

    # ------------------------------------------------------------------
    # Main dashboard grid
    # ------------------------------------------------------------------

    with box(
        f"{P}_dgrid",
        "gmap",
        "mt",
    ):

        # --------------------------------------------------------------
        # Live floor map
        # --------------------------------------------------------------

        with box(
            f"{P}_dmapcard",
            "card",
        ):
            html(
                '<div class="card-h">'
                "<div>"
                "<h3>Live floor map</h3>"
                '<div class="sub">'
                "Hover a computer for its status, click it for its "
                "hardware, software and maintenance history."
                "</div>"
                "</div>"
                "</div>"
            )

            kind, ref = SHELL.modal

            portal.live_map(
                P,
                s,
                "dash",
                open_pc,
                sel=(
                    tuple(ref)
                    if kind == "pc" and ref
                    else None
                ),
            )

        # --------------------------------------------------------------
        # Right column
        # --------------------------------------------------------------

        with box(
            f"{P}_dright",
            "stack",
        ):

            escalated = [
                r
                for r in _rows(s, "reports")
                if r.get("status") == "escalated"
            ]

            # ----------------------------------------------------------
            # Escalation summary
            # ----------------------------------------------------------

            with box(
                f"{P}_desc",
                "card",
            ):

                with box(
                    f"{P}_desc_h",
                    "cardh",
                ):

                    # Only consider escalated reports that actually carry a
                    # creation timestamp -- `r["created"]` previously raised
                    # KeyError on a record without that field.
                    escalated_times = [
                        t
                        for t in (
                            _created(r)
                            for r in escalated
                        )
                        if t is not None
                    ]

                    oldest = (
                        D.when(min(escalated_times))
                        if escalated_times
                        else ""
                    )

                    title = (
                        f"{len(escalated)} escalation"
                        f"{'s' if len(escalated) != 1 else ''}"
                        " need your decision"
                        if escalated
                        else "No escalations"
                    )

                    subtitle = (
                        f"Oldest from {oldest}"
                        if escalated
                        else
                        "Technicians have everything they need."
                    )

                    html(
                        '<div style="display:flex;gap:12px;'
                        'align-items:center">'
                        '<div class="ic ic-violet" '
                        'style="width:40px;height:40px;'
                        'border-radius:12px;display:grid;'
                        'place-items:center">'
                        f"{ic('up')}"
                        "</div>"
                        "<div>"
                        f"<h3>{h(title)}</h3>"
                        f'<div class="sub">{h(subtitle)}</div>'
                        "</div>"
                        "</div>"
                    )

                    if escalated:
                        btn(
                            "Review",
                            f"{P}_desc_btn",
                            "primarysm",
                            on_click=go,
                            args=("escalation",),
                        )

            # ----------------------------------------------------------
            # Recent report activity
            # ----------------------------------------------------------

            with box(
                f"{P}_dact",
                "card",
            ):

                with box(
                    f"{P}_dact_h",
                    "cardh",
                ):
                    html(
                        "<div>"
                        "<h3>Recent activity</h3>"
                        "</div>"
                    )

                    btn(
                        "All reports",
                        f"{P}_dact_all",
                        "link",
                        on_click=go,
                        args=("reports",),
                    )

                events = sorted(
                    (
                        (r, ev)
                        for r in _rows(s, "reports")
                        for ev in (r.get("history") or [])
                    ),
                    key=lambda x: x[1].get("t") or D.now(),
                    reverse=True,
                )[:6]

                if not events:
                    html(
                        '<div class="empty">'
                        "No activity yet."
                        "</div>"
                    )

                for i, (r, ev) in enumerate(events):

                    event_status = ev.get("s")

                    tone = {
                        "fixed": "ic-green",
                        "reported": "ic-amber",
                        "escalated": "ic-violet",
                    }.get(
                        event_status,
                        "ic-red",
                    )

                    icon_name = {
                        "fixed": "check",
                        "reported": "alert",
                        "escalated": "up",
                    }.get(
                        event_status,
                        "wrench",
                    )

                    if event_status == "reported":
                        text = (
                            f"{D.by_name(r)}: "
                            f"{r.get('issue', '')}"
                        )
                    else:
                        text = (
                            ev.get("note")
                            or r.get("issue")
                            or "Report updated"
                        )

                    last = (
                        " last"
                        if i == len(events) - 1
                        else ""
                    )

                    report_id = r.get("id")

                    hit(
                        f'<div class="row clickable{last}">'
                        f'<div class="ic {tone}">'
                        f"{ic(icon_name)}"
                        "</div>"
                        '<div class="main-t">'
                        f"<b>"
                        f"{h(D.STATUS.get(event_status, (event_status or 'Updated',))[0])}"
                        f" · "
                        f"{h(D.lab_name(r.get('lab')))} "
                        f"{h(D.pc_name(r.get('pc')))}"
                        f"</b>"
                        f"<span>"
                        f"{h(text)}"
                        f" · "
                        f"{D.when(ev.get('t'))}"
                        f"</span>"
                        "</div>"
                        "</div>",
                        f"{P}_act_{i}",
                        open_modal,
                        ("report", report_id),
                    )

    # ------------------------------------------------------------------
    # Laboratory tiles
    # ------------------------------------------------------------------

    with box(
        f"{P}_dlabs",
        "g4",
        "mt",
    ):
        for lab, _ in D.LABS:
            hit(
                lab_tile(s, lab),
                f"{P}_dlab_{lab}",
                lab_reports,
                (lab,),
            )


# ===========================================================================
# Reports
# ===========================================================================

R_FILTERS = [
    ("all", "All"),
    ("open", "Open"),
    ("reported", "New"),
    ("repair", "Under repair"),
    ("escalated", "Escalated"),
    ("fixed", "Fixed"),
]


def _r_match(
    r: dict,
    f: str,
) -> bool:

    if f == "all":
        return True

    if f == "open":
        return r.get("status") in D.OPEN

    return r.get("status") == f


def page_reports(s: dict) -> None:

    flt = ss.setdefault(
        f"{P}_rfilter",
        "all",
    )

    page_key = f"{P}_rpage"

    with box(
        f"{P}_rcard",
        "card",
        "pad0",
    ):

        with box(
            f"{P}_rhead",
            "cardh",
            "padh",
        ):

            # ----------------------------------------------------------
            # Status filters
            # ----------------------------------------------------------

            with box(
                f"{P}_rchips",
                "chips",
            ):

                for key, label in R_FILTERS:

                    count = sum(
                        _r_match(r, key)
                        for r in _rows(s, "reports")
                    )

                    btn(
                        f"{label} · {count}",
                        f"{P}_rf_{key}",
                        (
                            "chipon"
                            if flt == key
                            else "chip"
                        ),
                        on_click=lambda k=key: (
                            ss.__setitem__(
                                f"{P}_rfilter",
                                k,
                            ),
                            ss.__setitem__(
                                page_key,
                                0,
                            ),
                        ),
                    )

            # ----------------------------------------------------------
            # Search/filter controls
            # ----------------------------------------------------------

            with box(
                f"{P}_rctl",
                "rowend",
                "full",
            ):

                q = st.text_input(
                    "Search",
                    placeholder=(
                        "Search report, PC or person"
                    ),
                    label_visibility="collapsed",
                    key=ui.sticky(
                        f"{P}_r_q__search__"
                    ),
                    on_change=_reset_page,
                    args=(page_key,),
                )

                labs = [0] + [
                    lab
                    for lab, _ in D.LABS
                ]

                lab = st.selectbox(
                    "Laboratory",
                    labs,
                    format_func=(
                        lambda x:
                        D.lab_name(x)
                        if x
                        else "All labs"
                    ),
                    key=ui.sticky(
                        f"{P}_r_lab__sel__",
                        labs,
                    ),
                    label_visibility="collapsed",
                    on_change=_reset_page,
                    args=(page_key,),
                )

                how = sort_select(
                    f"{P}_r_sort__selwide__",
                    {
                        k: f"Sort: {v}"
                        for k, v in D.REPORT_SORTS.items()
                    },
                )

                ui.remember(
                    f"{P}_r_q__search__"
                )

                ui.remember(
                    f"{P}_r_lab__sel__"
                )

        q = (
            q or ""
        ).strip().lower()

        rows = []

        for r in _rows(s, "reports"):

            if not _r_match(r, flt):
                continue

            if lab and r.get("lab") != lab:
                continue

            search_text = (
                f"{r.get('id', '')} "
                f"{D.pc_name(r.get('pc'))} "
                f"{D.lab_name(r.get('lab'))} "
                f"{D.by_name(r)} "
                f"{r.get('tech') or ''} "
                f"{r.get('issue') or ''}"
            ).lower()

            if q and q not in search_text:
                continue

            rows.append(r)

        rows = D.sort_reports(
            rows,
            how,
        )

        page = min(
            ss.get(page_key, 0),
            max(
                0,
                (len(rows) - 1) // PER,
            ),
        )

        cols = (
            "grid-template-columns:"
            "86px "
            "minmax(0,1.1fr) "
            "minmax(0,1.2fr) "
            "minmax(0,1.2fr) "
            "minmax(0,1.1fr) "
            "108px "
            "128px "
            "100px;"
        )

        html(
            f'<div class="tt-head" style="{cols}">'
            "<div>Report</div>"
            "<div>Computer</div>"
            "<div>Problem</div>"
            "<div>Reported by</div>"
            "<div>Technician</div>"
            "<div>Sent</div>"
            "<div>Status</div>"
            "<div>&nbsp;</div>"
            "</div>"
        )

        if not rows:
            html(
                '<div class="empty">'
                "No reports match."
                "</div>"
            )

        for r in rows[
            page * PER:
            (page + 1) * PER
        ]:

            report_id = r.get("id")

            hit(
                f'<div class="tt-row" style="{cols}">'
                f'<div class="strong">'
                f"{h(report_id)}"
                f"</div>"
                f"<div>"
                f"{h(D.lab_name(r.get('lab')))}"
                f'<div class="small">'
                f"{h(D.pc_name(r.get('pc')))}"
                f"</div>"
                f"</div>"
                f"<div>"
                f"{h(r.get('issue') or '—')}"
                f"</div>"
                f"<div>"
                f"{h(D.by_name(r))}"
                f"</div>"
                f"<div>"
                f"{h(r.get('tech') or '—')}"
                f"</div>"
                f"<div>"
                f"{D.sent_date(r.get('sent', r.get('created')))}"
                f"</div>"
                f"<div>"
                f"{badge(r.get('status'))}"
                f"</div>"
                f'<div style="text-align:right">'
                f'<span class="fakebtn">View</span>'
                f"</div>"
                f"</div>",
                f"{P}_r_{report_id}",
                open_modal,
                ("report", report_id),
            )

        pager(
            page_key,
            page,
            len(rows),
        )


# ===========================================================================
# Analytics
# ===========================================================================

def page_analytics(s: dict) -> None:

    now = D.now()

    reports = _rows(s, "reports")

    d30 = [
        r
        for r in reports
        if _created(r) is not None
        and _created(r) > now - timedelta(days=30)
    ]

    # A report only contributes to fix-time statistics when it has BOTH a
    # fixed timestamp and a creation timestamp. Requiring `created` here is
    # what makes the `in24` calculation below safe -- it previously did
    # `D.fixed_at(r) - r["created"]` over this list and raised KeyError on
    # any fixed report whose `created` field was missing.
    fixed = [
        r
        for r in reports
        if D.fixed_at(r)
        and _created(r) is not None
    ]

    def avg_fix(lst):
        seconds = [
            (
                D.fixed_at(r) - _created(r)
            ).total_seconds()
            for r in lst
            if D.fixed_at(r)
            and _created(r) is not None
        ]

        return (
            sum(seconds) / len(seconds)
            if seconds
            else 0
        )

    fixed_30 = [
        r
        for r in fixed
        if D.fixed_at(r)
        and D.fixed_at(r) > now - timedelta(days=30)
    ]

    average = avg_fix(fixed_30)

    in24 = (
        round(
            sum(
                (
                    D.fixed_at(r)
                    - _created(r)
                ).total_seconds()
                <= 86400
                for r in fixed
            )
            / len(fixed)
            * 100
        )
        if fixed
        else None
    )

    html(
        '<div class="grid g3">'
        + stat(
            "list",
            "ic-blue",
            len(d30),
            "Reports in the last 30 days",
        )
        + stat(
            "clock",
            "ic-green",
            D.dur(average)
            if average
            else "–",
            "Average time to fix",
        )
        + stat(
            "check",
            "ic-violet",
            (
                f"{in24}%"
                if in24 is not None
                else "–"
            ),
            "Fixed within 24 hours",
        )
        + "</div>"
    )

    # ------------------------------------------------------------------
    # Reports per week
    # ------------------------------------------------------------------

    weeks = []

    for w in range(7, -1, -1):

        start = now - timedelta(
            days=(w + 1) * 7
        )

        end = now - timedelta(
            days=w * 7
        )

        d = start + timedelta(days=1)

        weeks.append(
            (
                f"Week of {d:%b} {d.day}",
                (
                    "This wk"
                    if w == 0
                    else f"{d:%b} {d.day}"
                ),
                sum(
                    start < _created(r) <= end
                    for r in reports
                    if _created(r) is not None
                ),
            )
        )

    html(
        '<div class="card mt">'
        '<div class="card-h">'
        '<div>'
        '<h3>Reports per week</h3>'
        '<div class="sub">'
        "All laboratories, last 8 weeks"
        "</div>"
        "</div>"
        "</div>"
        f'{bars_v(weeks, "reports", ("Week", "Reports"))}'
        "</div>"
    )

    # ------------------------------------------------------------------
    # Reports by laboratory
    # ------------------------------------------------------------------

    by_lab = [
        (
            D.lab_name(lab),
            D.lab_name(lab),
            sum(
                r.get("lab") == lab
                for r in d30
            ),
        )
        for lab, _ in D.LABS
    ]

    # ------------------------------------------------------------------
    # Reports by issue
    # ------------------------------------------------------------------

    by_issue = sorted(
        (
            (
                issue,
                issue,
                sum(
                    r.get("issue") == issue
                    for r in d30
                ),
            )
            for issue in D.ISSUES
        ),
        key=lambda x: -x[2],
    )

    extra = sorted(
        {
            r.get("issue")
            for r in d30
            if r.get("issue")
        }
        - set(D.ISSUES)
    )

    by_issue += [
        (
            issue,
            issue,
            sum(
                r.get("issue") == issue
                for r in d30
            ),
        )
        for issue in extra
    ]

    html(
        '<div class="grid g2 mt">'
        '<div class="card">'
        '<div class="card-h">'
        '<div>'
        '<h3>Reports by laboratory</h3>'
        '<div class="sub">Last 30 days</div>'
        "</div>"
        "</div>"
        f'{bars_v(by_lab, "reports", ("Laboratory", "Reports"))}'
        "</div>"
        '<div class="card">'
        '<div class="card-h">'
        '<div>'
        '<h3>Reports by problem</h3>'
        '<div class="sub">Last 30 days</div>'
        "</div>"
        "</div>"
        f'{bars_h(by_issue, "reports", ("Problem", "Reports"))}'
        "</div>"
        "</div>"
    )

    # ------------------------------------------------------------------
    # Laboratory health
    # ------------------------------------------------------------------

    health = []

    for lab, wing in D.LABS:

        summary = D.lab_summary(
            s,
            lab,
        )

        total = summary.get(
            "total",
            0,
        )

        working = summary.get(
            "ok",
            0,
        )

        health.append(
            {
                "lab": lab,
                "wing": wing,
                "ok": working,
                "total": total,
                "pct": (
                    working / total
                    if total
                    else 0
                ),
                "open": sum(
                    r.get("lab") == lab
                    for r in D.open_reports(s)
                ),
                "recent": sum(
                    r.get("lab") == lab
                    for r in d30
                ),
                "fix": avg_fix(
                    [
                        r
                        for r in fixed
                        if r.get("lab") == lab
                    ]
                ),
            }
        )

    with box(
        f"{P}_health",
        "card",
        "pad0",
        "mt",
    ):

        with box(
            f"{P}_health_h",
            "cardh",
            "padh",
        ):
            html(
                "<div>"
                "<h3>Laboratory health</h3>"
                "</div>"
            )

            with box(
                f"{P}_health_sort",
                "row",
            ):
                how = sort_select(
                    f"{P}_health_sort__selwide__",
                    {
                        k: f"Sort: {v}"
                        for k, v
                        in D.HEALTH_SORTS.items()
                    },
                )

        keys = {
            "working": lambda x: x["pct"],
            "open": lambda x: -x["open"],
            "recent": lambda x: -x["recent"],
            "fix": lambda x: -x["fix"],
        }

        health.sort(
            key=keys.get(
                how,
                lambda x: x["lab"],
            )
        )

        rows = "".join(
            f'<tr>'
            f'<td class="strong">'
            f"{D.lab_name(x['lab'])}"
            f'<div class="small">'
            f"{h(x['wing'])}"
            f"</div>"
            f"</td>"
            f"<td>"
            f"{x['ok']} of {x['total']} "
            f'<span class="small">'
            f"({round(x['pct'] * 100)}%)"
            f"</span>"
            f"</td>"
            f"<td>{x['open']}</td>"
            f"<td>{x['recent']}</td>"
            f"<td>"
            f"{D.dur(x['fix']) if x['fix'] else '&ndash;'}"
            f"</td>"
            f"</tr>"
            for x in health
        )

        html(
            '<div class="table-wrap" style="margin:0">'
            '<table class="t">'
            "<thead>"
            "<tr>"
            "<th>Laboratory</th>"
            "<th>Working now</th>"
            "<th>Open reports</th>"
            "<th>Reports (30 days)</th>"
            "<th>Avg. time to fix</th>"
            "</tr>"
            "</thead>"
            f"<tbody>{rows}</tbody>"
            "</table>"
            "</div>"
        )


# ===========================================================================
# Escalation page
# ===========================================================================

def page_escalation(s: dict) -> None:

    with box(
        f"{P}_e_top",
        "cardh",
    ):
        html(
            '<p class="muted" style="margin:0">'
            "Technicians escalate a report when a computer needs "
            "parts, a replacement or your decision."
            "</p>"
        )

        with box(
            f"{P}_e_sort",
            "row",
        ):
            how = sort_select(
                f"{P}_e_sort__selwide__",
                {
                    k: f"Sort: {v}"
                    for k, v
                    in D.ESCALATION_SORTS.items()
                },
            )

    lst = [
        r
        for r in _rows(s, "reports")
        if r.get("status") == "escalated"
    ]

    keys = {
        "new": lambda r: -(
            _created(r).timestamp()
            if _created(r) is not None
            else 0
        ),
        "lab": lambda r: (
            r.get("lab"),
            r.get("created"),
        ),
        "computer": lambda r: (
            r.get("lab"),
            r.get("pc"),
        ),
    }

    lst.sort(
        key=keys.get(
            how,
            lambda r: r.get("created"),
        )
    )

    if not lst:
        html(
            '<div class="card">'
            '<div class="empty">'
            f"{ic('check')}"
            "<div>No escalations right now.</div>"
            "</div>"
            "</div>"
        )

    with box(
        f"{P}_e_list",
        "g2",
    ):

        for r in lst:

            report_id = r.get("id")

            with box(
                f"{P}_e_{report_id}",
                "card",
            ):

                html(
                    '<div class="card-h">'
                    '<div class="ic ic-violet" '
                    'style="width:44px;height:44px;'
                    'border-radius:12px;display:grid;'
                    'place-items:center">'
                    f"{ic('up')}"
                    "</div>"
                    "<div>"
                    f"<h3>"
                    f"{h(D.lab_name(r.get('lab')))}"
                    f" · "
                    f"{h(D.pc_name(r.get('pc')))}"
                    f"</h3>"
                    '<div class="sub">'
                    f"{h(report_id)}"
                    f" · "
                    f"{h(r.get('issue') or '')}"
                    f" · reported "
                    f"{D.when(r.get('created'))}"
                    "</div>"
                    "</div>"
                    "</div>"
                    '<dl class="kv">'
                    "<dt>Technician</dt>"
                    "<dd>"
                    f"{h(r.get('tech') or '—')}"
                    "</dd>"
                    "<dt>What's needed</dt>"
                    "<dd>"
                    f"{h(r.get('esc_note') or 'No note')}"
                    "</dd>"
                    "<dt>Reported by</dt>"
                    "<dd>"
                    f"{h(D.by_name(r))}"
                    "</dd>"
                    "</dl>"
                )

                with box(
                    f"{P}_e_btns_{report_id}",
                    "row",
                ):

                    btn(
                        "Approve replacement",
                        f"{P}_e_ap_{report_id}",
                        "primarysm",
                        on_click=_ask_decide,
                        args=(
                            report_id,
                            "approve",
                        ),
                    )

                    btn(
                        "Mark resolved",
                        f"{P}_e_rs_{report_id}",
                        "successsm",
                        on_click=_ask_decide,
                        args=(
                            report_id,
                            "resolve",
                        ),
                    )

                    btn(
                        "Send back",
                        f"{P}_e_bk_{report_id}",
                        "ghostsm",
                        on_click=_ask_decide,
                        args=(
                            report_id,
                            "back",
                        ),
                    )

                    btn(
                        "Details",
                        f"{P}_e_hi_{report_id}",
                        "ghostsm",
                        on_click=open_modal,
                        args=(
                            "report",
                            report_id,
                        ),
                    )

    # ------------------------------------------------------------------
    # Recently decided
    #
    # This section previously depended on lab_store["decided"].
    #
    # Since Admin no longer maintains a local persistence layer, it only
    # displays decisions when they are returned by the backend.
    # ------------------------------------------------------------------

    decided = s.get("decided") or []

    if decided:

        rows = "".join(
            f'<div class="row">'
            f'<div class="ic ic-green">'
            f"{ic('check')}"
            f"</div>"
            f'<div class="main-t">'
            f"<b>"
            f"{h(d.get('r', {}).get('id', ''))}"
            f" · "
            f"{h(D.lab_name(d.get('r', {}).get('lab')))}"
            f" "
            f"{h(D.pc_name(d.get('r', {}).get('pc')))}"
            f"</b>"
            f"<span>"
            f"{h(d.get('text') or '')}"
            f" · "
            f"{D.when(d.get('t'))}"
            f"</span>"
            f"</div>"
            f"{badge(d.get('r', {}).get('status'))}"
            f"</div>"
            for d in reversed(decided)
        )

    else:

        rows = (
            '<div class="empty" style="padding:20px">'
            "Decisions are stored by the backend and will appear "
            "here when returned by the Admin API."
            "</div>"
        )

    html(
        '<div class="card mt">'
        '<div class="card-h">'
        "<h3>Recently decided</h3>"
        "</div>"
        '<div class="rows">'
        f"{rows}"
        "</div>"
        "</div>"
    )


# ===========================================================================
# User requests
# ===========================================================================

def page_requests(s: dict) -> None:

    if not s.get("live"):
        html(
            '<div class="demo-note">'
            f"{ic('info')}"
            "<span>"
            "<b>Not connected to the server.</b> "
            "Account requests are loaded from the server. "
            "Log in again to see and manage them."
            "</span>"
            "</div>"
        )

    pending = [
        u
        for u in _rows(s, "requests")
        if u.get("st") == "pending"
    ]

    with box(
        f"{P}_u_card",
        "card",
        "pad0",
    ):

        with box(
            f"{P}_u_head",
            "cardh",
            "padh",
        ):

            html(
                '<div>'
                "<h3>Waiting for approval</h3>"
                '<div class="sub">'
                "New technician accounts can't log in "
                "until you confirm them."
                "</div>"
                "</div>"
            )

            with box(
                f"{P}_u_sort",
                "row",
            ):
                how = sort_select(
                    f"{P}_u_sort__selwide__",
                    {
                        k: f"Sort: {v}"
                        for k, v
                        in D.REQUEST_SORTS.items()
                    },
                )

        grid = (
            "minmax(0,1.4fr) "
            "minmax(0,1.6fr) "
            "minmax(0,.8fr) "
            "minmax(0,.8fr) "
            "minmax(0,.9fr)"
        )

        cols = (
            f"grid-template-columns:{grid};"
        )

        html(
            '<div class="tt-head" '
            f'style="grid-template-columns:{grid} 198px">'
            "<div>Name</div>"
            "<div>Email</div>"
            "<div>Department</div>"
            "<div>Role</div>"
            "<div>Requested</div>"
            '<div style="text-align:right">'
            "Decision"
            "</div>"
            "</div>"
        )

        if not pending:
            html(
                '<div class="empty">'
                f"{ic('check')}"
                "<div>No account requests waiting.</div>"
                "</div>"
            )

        for u in D.sort_requests(
            pending,
            how,
        ):

            name = u.get("name") or "User"

            initials = "".join(
                word[0]
                for word in name.split()[:2]
                if word
            ).upper()

            with box(
                f"{P}_u_{u.get('id')}",
                "trow",
            ):

                html(
                    f'<div class="tt-row" style="{cols}">'
                    "<div>"
                    '<div style="display:flex;'
                    'gap:10px;align-items:center">'
                    '<div class="avatar" '
                    'style="width:32px;height:32px;'
                    'font-size:12px;'
                    'background:linear-gradient('
                    '135deg,#6b7a90,#14213d)">'
                    f"{h(initials)}"
                    "</div>"
                    f'<span class="strong">'
                    f"{h(name)}"
                    "</span>"
                    "</div>"
                    "</div>"
                    f"<div>{h(u.get('email') or '')}</div>"
                    f"<div>{h(u.get('dept') or '')}</div>"
                    "<div>"
                    '<span class="badge b-neutral">'
                    f"{h(u.get('role') or '')}"
                    "</span>"
                    "</div>"
                    f"<div>{D.when(u.get('t'))}</div>"
                    "</div>"
                )

                with box(
                    f"{P}_u_act_{u.get('id')}",
                    "row",
                    "gap6",
                    "acts",
                ):

                    btn(
                        "Confirm",
                        f"{P}_u_ok_{u.get('id')}",
                        "successsm",
                        on_click=_set_request,
                        args=(
                            u.get("id"),
                            "active",
                        ),
                    )

                    btn(
                        "Cancel",
                        f"{P}_u_no_{u.get('id')}",
                        "dangersm",
                        on_click=open_modal,
                        args=(
                            "cancelreq",
                            u.get("id"),
                        ),
                    )

    # ------------------------------------------------------------------
    # Previously handled requests
    # ------------------------------------------------------------------

    handled = [
        u
        for u in _rows(s, "requests")
        if u.get("st") != "pending"
    ]

    with box(
        f"{P}_u_done",
        "card",
        "pad0",
        "mt",
    ):

        with box(
            f"{P}_u_done_h",
            "cardh",
            "padh",
        ):

            html(
                "<div>"
                "<h3>Recently handled</h3>"
                "</div>"
            )

            with box(
                f"{P}_u_done_sort",
                "row",
            ):
                how2 = sort_select(
                    f"{P}_u_done_sort__selwide__",
                    {
                        k: f"Sort: {v}"
                        for k, v
                        in D.REQUEST_SORTS.items()
                    },
                )

        rows = "".join(
            f"<tr>"
            f'<td class="strong">'
            f"{h(u.get('name') or 'User')}"
            f"</td>"
            f"<td>{h(u.get('email') or '')}</td>"
            f"<td>{h(u.get('role') or '')}</td>"
            f"<td>"
            + (
                '<span class="badge b-fixed">'
                "Confirmed"
                "</span>"
                if u.get("st") == "active"
                else
                '<span class="badge b-repair">'
                "Cancelled"
                "</span>"
            )
            + f"</td>"
            f"<td>{D.when(u.get('done'))}</td>"
            f"</tr>"
            for u in D.sort_requests(
                handled,
                how2,
                done=True,
            )
        )

        html(
            '<div class="table-wrap" style="margin:0">'
            '<table class="t">'
            "<thead>"
            "<tr>"
            "<th>Name</th>"
            "<th>Email</th>"
            "<th>Role</th>"
            "<th>Decision</th>"
            "<th>When</th>"
            "</tr>"
            "</thead>"
            "<tbody>"
            + (
                rows
                or
                '<tr>'
                '<td colspan="5">'
                '<div class="empty" style="padding:20px">'
                "Nothing yet."
                "</div>"
                "</td>"
                "</tr>"
            )
            + "</tbody>"
            "</table>"
            "</div>"
        )


# ===========================================================================
# Profile page
# ===========================================================================

def page_profile(
    user: dict,
) -> None:

    SHELL.profile_head(
        user,
        "Admin",
        "Full access",
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
                email_note=(
                    "Email changes must be made in Supabase "
                    "(the login uses this email)."
                ),
            )

        with box(
            f"{P}_pf_account",
            "card",
        ):
            html(
                '<div class="card-h">'
                "<h3>Account</h3>"
                "</div>"
                '<p class="muted" style="margin:0 0 16px">'
                "You can approve accounts, handle escalations "
                "and manage the computer inventory of every "
                "laboratory."
                "</p>"
            )

            SHELL.logout_button()

    SHELL.password_card(
        _change_password
    )


# ===========================================================================
# Report modal
# ===========================================================================

def modal_report(
    s: dict,
    rid: str,
) -> None:

    report = next(
        (
            x
            for x in _rows(s, "reports")
            if str(x.get("id")) == str(rid)
        ),
        None,
    )

    if report is None:
        return close_modal()

    with SHELL.window():

        html(
            portal.report_details(report)
        )

        with box(
            f"{P}_m_act",
            "mactions",
        ):

            if _has_computer(
                s,
                report.get("lab"),
                report.get("pc"),
            ):

                btn(
                    "View computer",
                    f"{P}_m_pc",
                    "ghost",
                    on_click=open_pc,
                    args=(
                        report.get("lab"),
                        report.get("pc"),
                    ),
                )

            if report.get("status") == "escalated":

                btn(
                    "Decide on escalation",
                    f"{P}_m_esc",
                    "primary",
                    on_click=go,
                    args=("escalation",),
                )

            btn(
                "Close",
                f"{P}_m_close",
                "ghost",
                on_click=close_modal,
            )


# ===========================================================================
# Cancel request modal
# ===========================================================================

def modal_cancel_request(
    ref,
) -> None:

    user_request = next(
        (
            x
            for x in _rows(store(), "requests")
            if str(x.get("id")) == str(ref)
        ),
        None,
    )

    if user_request is None:
        return close_modal()

    name = user_request.get(
        "name",
        "User",
    )

    role = user_request.get(
        "role",
        "user",
    )

    with box(
        f"{P}_modal",
        "modal",
    ):

        html(
            f"<h3>"
            f"Cancel {h(name)}'s request?"
            f"</h3>"
            f'<div class="m-sub">'
            f"They won't be able to log in as a "
            f"{h(str(role).lower() or 'user')}. "
            "They can sign up again later."
            f"</div>"
        )

        with box(
            f"{P}_cr_btns",
            "mactions",
        ):

            btn(
                "Keep request",
                f"{P}_cr_keep",
                "ghost",
                on_click=close_modal,
            )

            btn(
                "Cancel request",
                f"{P}_cr_go",
                "danger",
                on_click=_set_request,
                args=(
                    ref,
                    "rejected",
                ),
            )


# ===========================================================================
# Modal dispatcher
# ===========================================================================

def render_modal(
    s: dict,
) -> None:

    kind, ref = (
        ss.get(f"{P}_modal")
        or (None, None)
    )

    if not kind:
        return

    if kind == "report":
        modal_report(
            s,
            ref,
        )

    elif kind == "cancelreq":
        modal_cancel_request(
            ref,
        )

    else:

        # Inventory modals are handled by inventory.py.
        handled = INV.render_modal(
            s,
            kind,
            ref,
        )

        if not handled:

            common_handled = (
                SHELL.common_modal(kind)
            )

            if not common_handled:
                close_modal()


# ===========================================================================
# Public entry point
# ===========================================================================

def render(
    user: dict | None = None,
    preview: bool = False,
) -> None:
    """
    Draw the Admin dashboard.

    `user` is supplied by the existing login/authentication flow.

    The frontend role is used for UI routing only. Actual Admin
    authorization must be performed by the backend using the access token.
    """

    ui.page_config(ROLE)

    user = ui.require_user(
        user,
        ROLE,
        ALLOWED_ROLES,
    )

    ss[f"{P}_preview"] = preview
    ss[f"{P}_me"] = user["name"]

    s = store()

    page = SHELL.page

    SHELL.frame(
        user,
        s,
        _counts(s),
        _notifications(s),
    )

    with SHELL.content():

        # --------------------------------------------------------------
        # Backend notice
        # --------------------------------------------------------------

        if (
            s.get("notice")
            and page not in (
                "inventory",
                "profile",
            )
        ):

            with box(
                f"{P}_notice",
                "row",
                "spread",
            ):

                html(
                    f'<div class="demo-note" '
                    f'style="margin:0">'
                    f"{ic('info')}"
                    f"<span>"
                    f"{h(s['notice'])}"
                    f"</span>"
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

        # --------------------------------------------------------------
        # Page routing
        # --------------------------------------------------------------

        if page == "reports":
            page_reports(s)

        elif page == "inventory":
            INV.page(s)

        elif page == "analytics":
            page_analytics(s)

        elif page == "escalation":
            page_escalation(s)

        elif page == "requests":
            page_requests(s)

        elif page == "profile":
            page_profile(user)

        else:
            page_dashboard(
                s,
                user,
            )

        # --------------------------------------------------------------
        # Modal
        # --------------------------------------------------------------
        render_modal(s)