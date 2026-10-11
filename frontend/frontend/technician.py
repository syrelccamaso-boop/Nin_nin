"""
frontend/technician.py - Computer Laboratory | Technician dashboard (Streamlit)

The screens follow centrum-laboratory-technician_1.html (the same design as the
admin dashboard): navy sidebar, top bar with notifications, the live floor map
and pop-up windows. The shared parts are drawn by frontend/portal.py; the data
helpers are in frontend/lab_data.py.

Pages
-----
Dashboard        stats, live floor map (click a computer), "Needs attention"
                 list with Start buttons
Reports          filter chips, search, laboratory, Sort by; Start repair,
                 Mark fixed (with a note), Escalate (with a reason), View
Laboratory Map   map focused on one laboratory + its open reports
Inventory        the full computer inventory, same tools as the admin:
                 list / live map, search, filter, Sort by, Export CSV,
                 Add computer, computer details, Edit computer (details,
                 hardware, software, log maintenance) - saved for everyone
Analytics        time to fix, reports by laboratory / problem, computers
                 reported most often - filtered by laboratory
Print reports    report preview, printing and PDF export (frontend/report_print.py)
My Profile       contact number, password, my work, log out

Saving
------
Reports are read from the backend (backend_client.get_technician_data ->
/technician/dashboard) when you are signed in. Start repair, Mark fixed and
Escalate are saved with backend_client.update_report_status (status
"progress", "resolved" or "followup" with the note); the contact number and
password are saved as before. Teacher reports (kept in the shared lab store,
frontend/lab_store.py) are updated there, and the inventory is the shared one.

How it is opened (app.py):

    from frontend import technician
    technician.render(user)

Just to look at it (no login needed), from the project root:

       python -m streamlit run frontend/technician.py -- --preview
"""

from __future__ import annotations

import sys
from datetime import timedelta

import streamlit as st

from . import backend_client
from . import inventory
from . import lab_data as D
from . import lab_store
from . import portal
from . import report_print
from . import ui
from frontend.portal import (
    badge,
    bars_h,
    bars_v,
    empty,
    ic,
    lab_tile,
    pager,
    row,
    sort_select,
    stat,
)
ROLE = "Technician"
P = "tech"  # session-state prefix for this dashboard (cleared on log out)
ss = st.session_state


PAGES = [  # key, label, icon
    ("dashboard", "Dashboard", "home"),
    ("reports", "Reports", "list"),
    ("labs", "Laboratory Map", "map"),
    ("inventory", "Inventory", "box"),
    ("analytics", "Analytics", "chart"),
    ("print", "Print reports", "print"),
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


# ===========================================================================
# Data
# ===========================================================================
def _fetch(token: str | None, preview: bool) -> dict:
    if preview:
        return D.empty_store()
    if not token:
        return D.empty_store(
            "Not connected to the server - log out and log in again to load the reports stored there. "
            "Teacher reports sent in this app and the shared inventory are shown."
        )
    result = backend_client.get_technician_data(token)
    if result.get("success"):
        return D.technician_store(result)
    return D.empty_store(
        f"Couldn't load the server's reports: {result.get('error') or 'unknown error'}. "
        "Use Refresh to try again."
    )


def store() -> dict:
    if f"{P}_data" not in ss:
        with ui.loading("Loading lab data...", "Getting the latest reports"):
            ss[f"{P}_data"] = _fetch(
                ss.get(ui.TOKEN_KEY), ss.get(f"{P}_preview", False)
            )
    data = ss[f"{P}_data"]
    # When connected, the inventory comes from Supabase (Computers /
    # ComputerHardware / ComputerSoftware), exactly as on the Admin dashboard.
    # lab_store.attach() must not replace it with the local data/centrum_lab.json
    # copy, or Technician and Admin show different computers.
    db_computers = dict(data["computers"]) if data.get("live") else None
    s = lab_store.attach(data)
    if db_computers is not None:
        s["computers"] = db_computers
    return s


def refresh() -> None:
    ss.pop(f"{P}_data", None)
    toast("Data refreshed")


def me() -> str:
    return ss.get(f"{P}_me", "Technician")


def find(rid: str) -> dict | None:
    return next((r for r in store()["reports"] if r["id"] == rid), None)


INV = inventory.Inventory(SHELL, store, me, ROLE)
REPORTS = report_print.ReportCenter(SHELL, store, me, ROLE)


# ===========================================================================
# Actions (callbacks)
# ===========================================================================
def _save(r: dict, status: str, note: str) -> bool:
    """Change a report's status here and, when signed in, in the database."""
    s = store()
    if s["live"] and not r.get("local"):
        result = backend_client.update_report_status(
            ss.get(ui.TOKEN_KEY), r["db_id"], D.BACKEND_STATUS[status], note
        )
        if not result.get("success"):
            toast(result.get("error") or "Could not save the change.", False)
            return False
    with lab_store.lock():
        if status != "reported" and not r.get("tech"):
            r["tech"] = me()
        D.set_report_status(s, r, status, note, me())
        if r.get("local"):
            lab_store.save()
        where = f"{D.lab_name(r['lab'])} {D.pc_name(r['pc'])} · {r['issue']}"
        label = D.STATUS[status][0].lower()
        lab_store.add_event(
            "status",
            f"Your report {r['id']} is {label}",
            f"{where} · {me()}",
            roles=("teacher",),
            actor=me(),
            to=r["by"],
            ref=("report", r["id"]),
        )
        if status == "escalated":
            lab_store.add_event(
                "escalation",
                f"Escalated · {r['id']}",
                f"{where} · {note}",
                roles=("admin",),
                actor=me(),
                ref=("report", r["id"]),
            )
    return True


def start_repair(rid: str) -> None:
    r = find(rid)
    if r and r["status"] == "reported":
        r["tech"] = me()
        if _save(r, "repair", f"{me()} started the repair"):
            toast(f"{r['id']} is now under repair")
            close_modal()


def ask(kind: str, rid: str) -> None:
    ss.pop(f"{P}_note", None)
    open_modal(kind, rid)


def do_fixed(rid: str) -> None:
    r = find(rid)
    note = (ss.get(f"{P}_note") or "").strip() or "Fixed and tested"
    if r and _save(r, "fixed", note):
        toast(f"{r['id']} marked fixed. The teacher can see it now.")
        close_modal()


def do_escalate(rid: str) -> None:
    r = find(rid)
    note = (ss.get(f"{P}_note") or "").strip()
    if not note:
        return toast("Add a short reason so the admin knows what's needed.", False)
    if r and _save(r, "escalated", f"Escalated: {note}"):
        r["esc_note"] = note
        toast(f"{r['id']} sent to the admin")
        close_modal()


def open_report(rid: str) -> None:
    open_modal("report", rid)


def pc_clicked(lab: int, pc: int) -> None:
    r = D.pc_report(store(), lab, pc)
    if r:
        return open_modal("report", r["id"])
    INV.open_pc(lab, pc)


def focus_lab(lab: int) -> None:
    ss[f"{P}_lab"] = None if ss.get(f"{P}_lab") == lab else lab


def _actions(r: dict, key: str, small: bool = True) -> None:
    """Start repair / Mark fixed / Escalate, depending on the report's status."""
    sm = "sm" if small else ""
    if r["status"] == "reported":
        btn(
            "Start repair",
            f"{P}_go_{key}",
            "primary" + sm,
            on_click=start_repair,
            args=(r["id"],),
        )
    if r["status"] in ("repair", "escalated"):
        btn(
            "Mark fixed",
            f"{P}_fx_{key}",
            "success" + sm,
            on_click=ask,
            args=("fixed", r["id"]),
        )
    if r["status"] == "repair":
        btn(
            "Escalate",
            f"{P}_es_{key}",
            "ghost" + sm,
            on_click=ask,
            args=("escalate", r["id"]),
        )


# ===========================================================================
# Pages
# ===========================================================================
def page_dashboard(s: dict, user: dict) -> None:
    new = sum(r["status"] == "reported" for r in s["reports"])
    with box(f"{P}_hello", "cardh"):
        sub = (
            f"{new} new report{' is' if new == 1 else 's are'} waiting for a technician."
            if new
            else "No new reports. Nice work."
        )
        html(
            f'<div class="hello" style="margin:0"><div><h2>{portal.greeting()}, {h(portal.first_name(user["name"]))}</h2>'
            f"<p>{h(sub)}</p></div></div>"
        )
        btn(
            "Open report queue",
            f"{P}_hello_q",
            "primary",
            icon=":material/format_list_bulleted:",
            on_click=go,
            args=("reports",),
        )
    week = D.now() - timedelta(days=7)
    portal.stats(
        stat("alert", "ic-amber", new, "New reports"),
        stat(
            "wrench",
            "ic-red",
            sum(r["status"] == "repair" for r in s["reports"]),
            "Under repair",
        ),
        stat(
            "up",
            "ic-violet",
            sum(r["status"] == "escalated" for r in s["reports"]),
            "Escalated to admin",
        ),
        stat(
            "check",
            "ic-green",
            sum(
                r["status"] == "fixed" and (D.fixed_at(r) or week) > week
                for r in s["reports"]
            ),
            "Fixed in the last 7 days",
        ),
    )
    with box(f"{P}_dgrid", "gmap", "mt"):
        with box(f"{P}_dmap", "card"):
            html(
                '<div class="card-h"><div><h3>Live floor map</h3><div class="sub">Click a computer to see its report and '
                "update it.</div></div></div>"
            )
            portal.live_map(P, s, "dash", pc_clicked)
        with box(f"{P}_dattn", "card"):
            with box(f"{P}_dattn_h", "cardh"):
                html("<div><h3>Needs attention</h3></div>")
                btn("See all", f"{P}_dattn_all", "link", on_click=go, args=("reports",))
            todo = D.sort_open(D.open_reports(s))[:6]
            if not todo:
                html(empty("Everything is working."))
            for i, r in enumerate(todo):
                high = (
                    ' <span class="badge b-repair" style="margin-left:4px">High</span>'
                    if r["urgency"] == "High"
                    else ""
                )
                with box(
                    f"{P}_att_{r['id']}",
                    "row",
                    "spread",
                    "attn" if i < len(todo) - 1 else "attnlast",
                ):
                    hit(
                        row(
                            "pc",
                            portal.tone(r["status"]),
                            f'{D.lab_name(r["lab"])} · {D.pc_name(r["pc"])}{high}',
                            f'{r["issue"]} · {D.when(r["created"])}',
                            last=True,
                            clickable=True,
                        ),
                        f"{P}_attrow_{r['id']}",
                        open_report,
                        (r["id"],),
                    )
                    if r["status"] == "reported":
                        btn(
                            "Start",
                            f"{P}_start_{r['id']}",
                            "primarysm",
                            on_click=start_repair,
                            args=(r["id"],),
                        )
                    else:
                        html(badge(r["status"]))
    portal.lab_analytics(P, s, "dash")


Q_FILTERS = [
    ("open", "All open"),
    ("reported", "New"),
    ("repair", "Under repair"),
    ("escalated", "Escalated"),
    ("fixed", "Fixed"),
]


def _q_match(r: dict, f: str) -> bool:
    return r["status"] in D.OPEN if f == "open" else r["status"] == f


def _reset_page() -> None:
    ss[f"{P}_qpage"] = 0


def _report_from_list(lab: int, flt: str) -> None:
    """Reports page -> "Generate report" (Maintenance & issues, same filters)."""
    rst = ["reported", "repair", "escalated"] if flt == "open" else [flt]
    report_print.open_generator(SHELL, "issues", lab=lab or 0, rstatuses=rst)


def page_reports(s: dict) -> None:
    flt = ss.setdefault(f"{P}_qfilter", "open")
    with box(f"{P}_qcard", "card", "pad0"):
        with box(f"{P}_qhead", "cardh", "padh"):
            with box(f"{P}_qchips", "chips"):
                for key, label in Q_FILTERS:
                    n = sum(_q_match(r, key) for r in s["reports"])
                    btn(
                        f"{label} · {n}",
                        f"{P}_qf_{key}",
                        "chipon" if flt == key else "chip",
                        on_click=lambda k=key: (
                            ss.__setitem__(f"{P}_qfilter", k),
                            _reset_page(),
                        ),
                    )
            with box(f"{P}_qctl", "rowend", "full"):
                q = st.text_input(
                    "Search",
                    placeholder="Search report, PC or teacher",
                    label_visibility="collapsed",
                    key=ui.sticky(f"{P}_q_q__search__"),
                    on_change=_reset_page,
                )
                labs = [0] + [lab for lab, _ in D.LABS]
                lab = st.selectbox(
                    "Laboratory",
                    labs,
                    format_func=lambda x: D.lab_name(x) if x else "All labs",
                    key=ui.sticky(f"{P}_q_lab__sel__", labs),
                    label_visibility="collapsed",
                    on_change=_reset_page,
                )
                how = sort_select(
                    f"{P}_q_sort__selwide__",
                    {k: f"Sort: {v}" for k, v in D.QUEUE_SORTS.items()},
                )
                btn(
                    "Generate report",
                    f"{P}_q_genrep",
                    "primarysm",
                    icon=":material/description:",
                    on_click=_report_from_list,
                    args=(lab, flt),
                )
                ui.remember(f"{P}_q_q__search__")
                ui.remember(f"{P}_q_lab__sel__")
        q = (q or "").strip().lower()
        rows = [
            r
            for r in s["reports"]
            if _q_match(r, flt)
            and (not lab or r["lab"] == lab)
            and (
                not q
                or q
                in f"{r['id']} {D.pc_name(r['pc'])} {D.lab_name(r['lab'])} {D.by_name(r)} {r['issue']}".lower()
            )
        ]
        rows = D.sort_reports(rows, how)
        grid = "86px minmax(0,1fr) minmax(0,1.1fr) minmax(0,1.1fr) minmax(0,.9fr) 120px"
        html(
            f'<div class="tt-head" style="grid-template-columns:{grid} 278px"><div>Report</div><div>Computer</div>'
            f"<div>Problem</div><div>Reported by</div><div>Sent</div><div>Status</div>"
            f'<div style="text-align:right">Actions</div></div>'
        )
        if not rows:
            html(empty("No reports match."))
        shown, page = portal.page_slice(rows, f"{P}_qpage")
        for r in shown:
            high = (
                '<div><span class="badge b-repair" style="font-size:11px">High</span></div>'
                if r["urgency"] == "High" and r["status"] != "fixed"
                else ""
            )
            with box(f"{P}_q_{r['id']}", "trow"):
                html(
                    f'<div class="tt-row" style="grid-template-columns:{grid}"><div class="strong">{h(r["id"])}{high}</div>'
                    f'<div>{D.lab_name(r["lab"])}<div class="small">{D.pc_name(r["pc"])}</div></div><div>{h(r["issue"])}</div>'
                    f'<div>{h(D.by_name(r))}</div><div>{D.sent_date(r.get("sent", r["created"]))}</div><div>{badge(r["status"])}</div></div>'
                )
                with box(f"{P}_q_act_{r['id']}", "row", "gap6", "acts250"):
                    _actions(r, f"q_{r['id']}")
                    btn(
                        "View",
                        f"{P}_qv_{r['id']}",
                        "ghostsm",
                        on_click=open_report,
                        args=(r["id"],),
                    )
        pager(f"{P}_qpage", page, len(rows))


def page_labs(s: dict) -> None:
    focus = ss.get(f"{P}_lab")
    with box(f"{P}_lgrid", "gmap"):
        with box(f"{P}_lmap", "card"):
            html(
                '<div class="card-h"><div><h3>Computer Laboratories</h3><div class="sub">Pick a laboratory to focus on it, or '
                "click a computer to see its history.</div></div></div>"
            )
            portal.live_map(P, s, "labs", pc_clicked, focus=focus)
        with box(f"{P}_lside", "stack", "gap10"):
            for lab, _ in D.LABS:
                hit(
                    lab_tile(s, lab, on=focus == lab),
                    f"{P}_ltile_{lab}",
                    focus_lab,
                    (lab,),
                )
            with box(f"{P}_ldetail", "card"):
                if not focus:
                    html(
                        '<p class="muted" style="margin:0">Pick a laboratory to list its open reports.</p>'
                    )
                else:
                    html(
                        f'<div class="card-h"><h3>Open in {D.lab_name(focus)}</h3></div>'
                    )
                    todo = D.sort_open(
                        [r for r in D.open_reports(s) if r["lab"] == focus]
                    )
                    if not todo:
                        html(empty("No open reports."))
                    for i, r in enumerate(todo):
                        hit(
                            f'<div class="row clickable{" last" if i == len(todo) - 1 else ""}"><div class="main-t">'
                            f'<b>{D.pc_name(r["pc"])} · {h(r["issue"])}</b><span>{D.when(r["created"])}</span></div>'
                            f'{badge(r["status"])}</div>',
                            f"{P}_lrow_{r['id']}",
                            open_report,
                            (r["id"],),
                        )


def page_analytics(s: dict) -> None:
    now = D.now()
    with box(f"{P}_an_filter", "cardh"):
        html('<p class="muted" style="margin:0">Analytics for <b>all laboratories</b> or one laboratory.</p>')
        with box(f"{P}_an_filter_r", "row"):
            labs = [0] + [lab for lab, _ in D.LABS]
            key = ui.sticky(f"{P}_an_lab__selwide__", labs)
            lab_f = st.selectbox(
                "Laboratory",
                labs,
                format_func=lambda x: D.lab_name(x) if x else "All laboratories",
                key=key,
                label_visibility="collapsed",
            )
            ui.remember(key)
    reports = [r for r in s["reports"] if not lab_f or r["lab"] == lab_f]
    scope = D.lab_name(lab_f) if lab_f else "All laboratories"
    d30_all = [r for r in s["reports"] if r["created"] > now - timedelta(days=30)]
    d30 = [r for r in reports if r["created"] > now - timedelta(days=30)]
    fixed30 = [
        r
        for r in reports
        if (D.fixed_at(r) or now - timedelta(days=99)) > now - timedelta(days=30)
    ]
    times = [(D.fixed_at(r) - r["created"]).total_seconds() for r in fixed30]
    week = sum(
        (D.fixed_at(r) or now - timedelta(days=99)) > now - timedelta(days=7)
        for r in reports
    )
    portal.stats(
        stat(
            "clock",
            "ic-blue",
            D.dur(sum(times) / len(times)) if times else "–",
            "Average time to fix (last 30 days)",
        ),
        stat("check", "ic-green", week, "Fixed this week"),
        stat("alert", "ic-amber", sum(r["status"] in D.OPEN for r in reports), "Open right now"),
        cols=3,
    )
    by_lab = [
        (D.lab_name(lab), D.lab_name(lab), sum(r["lab"] == lab for r in d30_all))
        for lab, _ in D.LABS
    ]
    by_issue = sorted(
        ((x, x, sum(r["issue"] == x for r in d30)) for x in D.ISSUES),
        key=lambda t: -t[2],
    )
    html(
        '<div class="grid g2 mt">'
        f'<div class="card"><div class="card-h"><div><h3>Reports by laboratory</h3><div class="sub">Last 30 days</div></div></div>'
        f'{bars_v(by_lab, "reports", ("Laboratory", "Reports"))}</div>'
        f'<div class="card"><div class="card-h"><div><h3>Reports by problem</h3><div class="sub">{h(scope)}, last 30 days</div></div></div>'
        f'{bars_h(by_issue, "reports", ("Problem", "Reports"))}</div></div>'
    )
    counts: dict = {}
    for r in reports:
        if r["created"] > now - timedelta(days=60):
            counts[(r["lab"], r["pc"])] = counts.get((r["lab"], r["pc"]), 0) + 1
    top = sorted(
        ((k, n) for k, n in counts.items() if n > 1), key=lambda x: (-x[1], x[0])
    )[:5]
    rows = "".join(
        row(
            "pc",
            "ic-blue",
            f"{D.lab_name(lab)} · {D.pc_name(pc)}",
            D.WING.get(lab, ""),
            f'<span class="badge b-neutral">{n} reports</span>',
            last=i == len(top) - 1,
        )
        for i, ((lab, pc), n) in enumerate(top)
    )
    html(
        '<div class="card mt"><div class="card-h"><div><h3>Computers reported most often</h3><div class="sub">Last 60 days. '
        "These may need a closer look.</div></div></div>"
        + (
            f'<div class="rows">{rows}</div>'
            if rows
            else empty("No computer was reported more than once.")
        )
        + "</div>"
    )


def _save_number(number: str) -> tuple[bool, str]:
    if not store()["live"]:
        return (
            False,
            "Not connected to the server - log in again to change your contact number.",
        )
    result = backend_client.update_contact_number(ss.get(ui.TOKEN_KEY), number)
    if not result.get("success"):
        return False, result.get("error") or "Could not save the number."
    saved = result.get("user") if isinstance(result.get("user"), dict) else {}
    ui.set_contact_number(saved.get("contact_number", number))
    return True, result.get("message") or "Contact number updated"


def _change_password(current: str, new: str) -> tuple[bool, str]:
    if not store()["live"]:
        return (
            False,
            "Not connected to the server - log in again to change your password.",
        )
    result = backend_client.change_password(ss.get(ui.TOKEN_KEY), current, new)
    if not result.get("success"):
        return False, result.get("error") or "Could not change the password."
    return True, result.get("message") or "Password updated"


def page_profile(s: dict, user: dict) -> None:
    SHELL.profile_head(user, "Technician", "Approved by admin")
    mine = [r for r in s["reports"] if r.get("tech") == user["name"]]
    with box(f"{P}_pf_grid", "g2", "mt"):
        with box(f"{P}_pf_contact", "card"):
            SHELL.contact_card(
                user,
                _save_number,
                email_note="To change your email, please contact the administrator.",
            )
        with box(f"{P}_pf_work", "card"):
            html(
                '<div class="card-h"><h3>My work</h3></div><div class="grid g2" style="margin-bottom:16px">'
                + stat(
                    "wrench",
                    "ic-red",
                    sum(r["status"] == "repair" for r in mine),
                    "Repairs in progress",
                ).replace('class="card stat"', 'class="stat"')
                + stat(
                    "check",
                    "ic-green",
                    sum(r["status"] == "fixed" for r in mine),
                    "Fixed by me",
                ).replace('class="card stat"', 'class="stat"')
                + "</div>"
            )
            SHELL.logout_button()
    SHELL.password_card(_change_password)


# ===========================================================================
# Pop-up windows
# ===========================================================================
def modal_report(s: dict, rid: str) -> None:
    r = find(rid)
    if r is None:
        return close_modal()
    with SHELL.window():
        html(portal.report_details(r))
        with box(f"{P}_m_act", "mactions"):
            _actions(r, "m", small=False)
            btn("Close", f"{P}_m_close", "ghost", on_click=close_modal)


def modal_note(kind: str, rid: str) -> None:
    r = find(rid)
    if r is None:
        return close_modal()
    with SHELL.window():
        if kind == "fixed":
            html(
                f'<h3>Mark {h(r["id"])} as fixed</h3><div class="m-sub">{D.lab_name(r["lab"])} · {D.pc_name(r["pc"])} — '
                f'{h(r["issue"])}</div>'
            )
            portal.field(
                "What did you do?",
                f"{P}_note",
                "For example: replaced the VGA cable and tested the display.",
                kind="area",
            )
        else:
            html(
                f'<h3>Escalate {h(r["id"])} to the admin</h3><div class="m-sub">Use this when the computer needs parts, '
                f"a replacement, or a decision.</div>"
            )
            portal.field(
                "Reason",
                f"{P}_note",
                "For example: power supply is damaged and there's no spare in stock.",
                kind="area",
            )
        with box(f"{P}_n_act", "mactions"):
            btn("Cancel", f"{P}_n_cancel", "ghost", on_click=close_modal)
            if kind == "fixed":
                btn(
                    "Mark fixed",
                    f"{P}_n_fixed",
                    "success",
                    on_click=do_fixed,
                    args=(rid,),
                )
            else:
                btn(
                    "Escalate",
                    f"{P}_n_escalate",
                    "primary",
                    on_click=do_escalate,
                    args=(rid,),
                )


def render_modal(s: dict) -> None:
    kind, ref = SHELL.modal
    if kind == "report":
        modal_report(s, ref)
    elif kind in ("fixed", "escalate"):
        modal_note(kind, ref)
    elif kind and not INV.render_modal(s, kind, ref) and not SHELL.common_modal(kind):
        close_modal()


# ===========================================================================
# Public entry point
# ===========================================================================
def _open_report_safe(rid: str) -> None:
    if find(rid):
        open_report(rid)
    else:
        toast("That report is no longer available.", False)


def _notifications(s: dict) -> list[dict]:
    """New reports waiting for a technician, admin decisions and inventory updates by others."""
    new = [r for r in s["reports"] if r["status"] == "reported"]
    out = [
        {
            "id": f"new:{r['id']}",
            "icon": "alert",
            "tone": "ic-amber",
            "title": f"New report · {D.lab_name(r['lab'])} {D.pc_name(r['pc'])}"
            + (" · High" if r["urgency"] == "High" else ""),
            "sub": f"{r['issue']} · {D.by_name(r)}",
            "t": r["created"],
            "cb": open_report,
            "args": (r["id"],),
            "roles": ["technician"],
        }
        for r in new
    ]
    return out + inventory.event_notifications(
        "technician", me(), INV.open_pc, _open_report_safe
    )


def render(user: dict | None = None, preview: bool = False) -> None:
    """Draw the Technician dashboard for `user` (a dict from your login)."""
    ui.page_config(ROLE)
    user = ui.require_user(user, ROLE, (ROLE.lower(),))
    ss[f"{P}_preview"] = preview
    ss[f"{P}_me"] = user["name"]
    lab_store.sync_labs()  # laboratories added in the app, before the data is read
    s = store()
    page = SHELL.page
    SHELL.frame(
        user,
        s,
        {"reports": sum(r["status"] == "reported" for r in s["reports"])},
        _notifications(s),
    )
    with SHELL.content():
        if s.get("notice") and page not in ("inventory", "profile", "print"):
            with box(f"{P}_notice", "row", "spread"):
                html(
                    f'<div class="demo-note" style="margin:0">{ic("info")}<span>{h(s["notice"])}</span></div>'
                )
                btn(
                    "Refresh",
                    f"{P}_refresh",
                    "ghostsm",
                    icon=":material/refresh:",
                    on_click=refresh,
                )
            html('<div style="height:18px"></div>')
        if page == "reports":
            page_reports(s)
        elif page == "labs":
            page_labs(s)
        elif page == "inventory":
            INV.page(s)
        elif page == "analytics":
            page_analytics(s)
        elif page == "print":
            REPORTS.page(s)
        elif page == "profile":
            page_profile(s, user)
        else:
            page_dashboard(s, user)
        render_modal(s)