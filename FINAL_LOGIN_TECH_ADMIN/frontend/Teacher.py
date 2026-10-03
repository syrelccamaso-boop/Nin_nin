"""
Teacher.py - Centrum Laboratory | Teacher dashboard (Streamlit)

The screens follow centrum-laboratory-teacher_1.html (the same design as the
admin and technician dashboards): navy sidebar, top bar with notifications,
the live floor map and a 4-step "Report an Issue" form. The shared parts are
drawn by frontend/portal.py; the data helpers are in frontend/lab_data.py.

Pages
-----
Dashboard          stats, my recent reports, laboratory status
Report an Issue    1 Laboratory (map or list) -> 2 Computer -> 3 Problem
                   (+ details, urgency) -> 4 Review -> sent
My Reports         filter chips, Sort by, report details
Laboratory Status  live floor map; click a computer to see it and report it
My Profile         contact number, my activity, log out

Note: the backend has no teacher endpoints yet, so reports sent here and the
contact number are kept for this browser session only (the original HTML
design worked the same way). When the backend gets e.g. POST /teacher/reports,
call it from _submit() below.

How it is opened (app.py):

    import Teacher
    Teacher.render(user)

Just to look at it (no login needed), from the project root:

       streamlit run Teacher.py -- --preview
"""

from __future__ import annotations

import sys

import streamlit as st

from frontend import lab_data as D
from frontend import portal
from frontend import ui
from frontend.portal import badge, empty, ic, lab_tile, row, sort_select, stat

ROLE = "Teacher"
P = "teacher"  # session-state prefix for this dashboard (cleared on log out)
ss = st.session_state

DEMO_USER = {"name": "Alwyna Lopez", "email": "alwyna.lopez@isu.edu.ph", "contact_number": "0983 765 6748", "role": ROLE}

PAGES = [  # key, label, icon
    ("dashboard", "Dashboard", "home"), ("report", "Report an Issue", "plus"), ("reports", "My Reports", "list"),
    ("labs", "Laboratory Status", "map"), ("profile", "My Profile", "user"),
]
SHELL = portal.Shell(P, ROLE, PAGES)
go, open_modal, close_modal, toast = SHELL.go, SHELL.open_modal, SHELL.close_modal, SHELL.toast

html, btn, hit, box, h = ui.html, ui.btn, ui.hit, ui.box, ui.h

STEPS = [("lab", "Laboratory"), ("pc", "Computer"), ("problem", "Problem"), ("review", "Review")]
URGENCY = [("Normal", "Normal"), ("High", "High — class is using it now")]
_DESC = f"{P}_r_desc"  # the "Details" text box


# ===========================================================================
# Data (sample data kept in this session - see the note at the top)
# ===========================================================================
def store() -> dict:
    if f"{P}_data" not in ss:
        ss[f"{P}_data"] = D.make_personal(D.sample_store(), D.SAMPLE_TEACHER, me())
    return ss[f"{P}_data"]


def me() -> str:
    return ss.get(f"{P}_me", "Teacher")


def mine(s: dict) -> list[dict]:
    return sorted((r for r in s["reports"] if r["by"] == me()), key=lambda r: r["created"], reverse=True)


def view_report(rid: str) -> None:
    open_modal("report", rid)


# ===========================================================================
# Report an issue (callbacks)
# ===========================================================================
def draft() -> dict:
    return ss.setdefault(f"{P}_draft", {"lab": None, "pc": None, "issue": None, "urg": "Normal", "desc": "", "step": "lab"})


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
    d["lab"], d["pc"], d["step"] = lab, pc, "pc"


def pick_pc(pc: int) -> None:
    draft()["pc"] = pc


def pick(field: str, value: str) -> None:
    draft()[field] = value


def _submit() -> None:
    _keep_desc()
    d = draft()
    if not (d["lab"] and d["pc"] and d["issue"]):
        return toast("Pick the laboratory, the computer and the problem first.", False)
    r = D.add_report(store(), lab=d["lab"], pc=d["pc"], issue=d["issue"], desc=(d["desc"] or "").strip(),
                     urgency=d["urg"], by=me())
    d["step"], d["sent"] = "done", r["id"]
    toast(f"Report {r['id']} sent")


# ===========================================================================
# Pages
# ===========================================================================
def page_dashboard(s: dict, user: dict) -> None:
    m = mine(s)
    with box(f"{P}_hello", "cardh"):
        html(f'<div class="hello" style="margin:0"><div><h2>{portal.greeting()}, {h(portal.first_name(user["name"]))}</h2>'
             "<p>Here's what's happening with the computers you reported.</p></div></div>")
        btn("Report an issue", f"{P}_hello_new", "primary", icon=":material/note_add:", on_click=start_report)
    total = ok = 0
    for lab, _ in D.LABS:
        sm = D.lab_summary(s, lab)
        total, ok = total + sm["total"], ok + sm["ok"]
    portal.stats(stat("alert", "ic-amber", sum(r["status"] == "reported" for r in m), "Waiting for a technician"),
                 stat("wrench", "ic-red", sum(r["status"] in ("repair", "escalated") for r in m), "Being repaired"),
                 stat("check", "ic-green", sum(r["status"] == "fixed" for r in m), "Fixed"),
                 stat("pc", "ic-blue", f"{round(ok / total * 100) if total else 0}%", "Lab computers working"))
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
                        f'{D.lab_name(r["lab"])} · {D.pc_name(r["pc"])} · {D.when(r["created"])}', badge(r["status"]),
                        last=i == len(recent) - 1, clickable=True), f"{P}_recent_{r['id']}", view_report, (r["id"],))
        with box(f"{P}_dlabs", "card"):
            with box(f"{P}_dlabs_h", "cardh"):
                html("<div><h3>Laboratory status</h3></div>")
                btn("Open map", f"{P}_dlabs_map", "link", on_click=go, args=("labs",))
            portal.lab_tiles(P, s, "dash", open_lab)


def open_lab(lab: int) -> None:
    ss[f"{P}_lab"], ss[f"{P}_lsel"] = lab, None
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
            html('<div class="card-h"><div><h3>Which laboratory are you in?</h3><div class="sub">Tap a computer on the map or '
                 'pick the room from the list.</div></div></div>')
            with box(f"{P}_r_grid", "gmap"):
                with box(f"{P}_r_mapcol", "stack"):
                    portal.live_map(P, s, "rep", pick_map_pc, focus=d["lab"])
                with box(f"{P}_r_tiles", "stack", "gap10"):
                    for lab, _ in D.LABS:
                        hit(lab_tile(s, lab, on=d["lab"] == lab), f"{P}_rlab_{lab}", pick_lab, (lab,))
        elif step == "pc":
            html(f'<div class="card-h"><div><h3>Which computer? <span class="muted" style="font-weight:500">· '
                 f'{D.lab_name(d["lab"])}</span></h3><div class="sub">The number is on the sticker on the monitor or the '
                 f'system unit.</div></div></div>')
            with box(f"{P}_pcs", "pcgrid"):
                for c in D.lab_computers(s, d["lab"]):
                    stt = D.pc_status(s, d["lab"], c["pc"])
                    label = "Working" if stt == "ok" else D.STATUS[stt][0]
                    on = " on" if d["pc"] == c["pc"] else ""
                    hit(f'<div class="pc-btn s-{stt}{on}" title="{D.pc_name(c["pc"])} — {label}">{ic("pc")}'
                        f'{D.pad(c["pc"])}<small>{label}</small></div>', f"{P}_pc_{c['pc']}", pick_pc, (c["pc"],))
            html('<div class="legend" style="justify-content:flex-start;margin-top:14px"><span><i style="background:#8aa6d8">'
                 '</i>Working</span><span><i style="background:var(--rep)"></i>Already reported</span><span>'
                 '<i style="background:var(--fix)"></i>Under repair</span></div>')
            r = D.pc_report(s, d["lab"], d["pc"]) if d["pc"] else None
            if r:
                html(f'<div class="demo-note mt">{ic("info")}<span>{D.pc_name(d["pc"])} was already reported '
                     f'{D.when(r["created"])} for <b>{h(r["issue"])}</b> ({D.STATUS[r["status"]][0].lower()}). You can '
                     f"still send a report if it's a different problem.</span></div>")
            with box(f"{P}_pc_btns", "stepacts"):
                btn("Back", f"{P}_pc_back", "ghost", icon=":material/arrow_back:", on_click=step_to, args=("lab",))
                btn("Continue", f"{P}_pc_next", "primary", disabled=not d["pc"], on_click=step_to, args=("problem",))
        elif step == "problem":
            html('<div class="card-h"><div><h3>What\'s wrong?</h3><div class="sub">Pick the closest match, then add any '
                 'details that help.</div></div></div>')
            with box(f"{P}_issues", "issuegrid"):
                for i, issue in enumerate(D.ISSUES):
                    hit(f'<div class="issue{" on" if d["issue"] == issue else ""}">{h(issue)}</div>', f"{P}_iss_{i}",
                        pick, ("issue", issue))
            if _DESC not in ss:
                ss[_DESC] = d["desc"]
            with box(f"{P}_desc_wrap", "field"):
                html('<div class="adm-label">Details <span class="muted" style="font-weight:400">(optional)</span></div>')
                st.text_area("Details", key=_DESC, max_chars=400, label_visibility="collapsed",
                             placeholder="For example: the screen stays black but the power light is on.")
            html('<div class="adm-label">How urgent is it?</div>')
            with box(f"{P}_urg", "chips"):
                for value, label in URGENCY:
                    btn(label, f"{P}_urg_{value}", "chipon" if d["urg"] == value else "chip", on_click=pick,
                        args=("urg", value))
            with box(f"{P}_prob_btns", "stepacts"):
                btn("Back", f"{P}_prob_back", "ghost", icon=":material/arrow_back:", on_click=step_to, args=("pc",))
                btn("Review report", f"{P}_prob_next", "primary", disabled=not d["issue"], on_click=step_to,
                    args=("review",))
        elif step == "review":
            html('<div class="card-h"><div><h3>Check your report</h3><div class="sub">Make sure everything is right before '
                 'you send it.</div></div></div>')
            rows = (("Reported by", me()), ("Laboratory", f'{D.lab_name(d["lab"])} ({D.WING[d["lab"]]})'),
                    ("Computer", D.pc_name(d["pc"])), ("Problem", d["issue"]), ("Details", (d["desc"] or "").strip() or "—"),
                    ("Urgency", d["urg"]))
            html("".join(f'<div class="review-row"><div class="review-label">{k}</div><div class="review-value">{h(v)}</div>'
                         f'</div>' for k, v in rows))
            with box(f"{P}_rev_btns", "stepacts"):
                btn("Edit", f"{P}_rev_back", "ghost", icon=":material/arrow_back:", on_click=step_to, args=("problem",))
                btn("Send report", f"{P}_send", "primary", on_click=_submit)
        else:  # sent
            r = next((x for x in s["reports"] if x["id"] == d.get("sent")), None)
            where = f'{D.lab_name(r["lab"])} · {D.pc_name(r["pc"])}' if r else "the computer"
            html(f'<div class="success"><div class="big">{ic("check")}</div><h3 style="font-size:22px">Report sent</h3>'
                 f'<p class="muted" style="max-width:440px;margin:8px auto 22px">{h(d.get("sent") or "")} for {where} went to the '
                 f"technicians. You'll see updates in My Reports. (Kept for this session only - the server doesn't take "
                 f"teacher reports yet.)</p></div>")
            with box(f"{P}_done_btns", "row", "center"):
                btn("Report another", f"{P}_again", "ghost", on_click=start_report)
                btn("View my reports", f"{P}_mine", "primary", on_click=go, args=("reports",))


T_FILTERS = [("all", "All"), ("reported", "Waiting"), ("repair", "Being repaired"), ("fixed", "Fixed")]


def _t_match(r: dict, f: str) -> bool:
    return f == "all" or (r["status"] in ("repair", "escalated") if f == "repair" else r["status"] == f)


def page_reports(s: dict) -> None:
    m = mine(s)
    flt = ss.setdefault(f"{P}_tfilter", "all")
    with box(f"{P}_tcard", "card", "pad0"):
        with box(f"{P}_thead", "cardh", "padh"):
            with box(f"{P}_tchips", "chips"):
                for key, label in T_FILTERS:
                    btn(f"{label} · {sum(_t_match(r, key) for r in m)}", f"{P}_tf_{key}", "chipon" if flt == key else "chip",
                        on_click=lambda k=key: ss.__setitem__(f"{P}_tfilter", k))
            with box(f"{P}_tctl", "row"):
                how = sort_select(f"{P}_t_sort__selwide__", {k: f"Sort: {v}" for k, v in D.MY_REPORT_SORTS.items()})
                btn("New report", f"{P}_tnew", "primarysm", icon=":material/note_add:", on_click=start_report)
        rows = D.sort_reports([r for r in m if _t_match(r, flt)], how)
        cols = "grid-template-columns:96px minmax(0,1fr) minmax(0,1.2fr) minmax(0,1fr) 150px 92px;"
        html(f'<div class="tt-head" style="{cols}"><div>Report</div><div>Computer</div><div>Problem</div><div>Sent</div>'
             f'<div>Status</div><div>&nbsp;</div></div>')
        if not rows:
            html(empty("No reports here.", "list"))
        for r in rows:
            hit(f'<div class="tt-row" style="{cols}"><div class="strong">{h(r["id"])}</div><div>{D.lab_name(r["lab"])}'
                f'<div class="small">{D.pc_name(r["pc"])}</div></div><div>{h(r["issue"])}</div><div>{D.when(r["created"])}</div>'
                f'<div>{badge(r["status"])}</div><div style="text-align:right"><span class="fakebtn">View</span></div></div>',
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
            html('<div class="card-h"><div><h3>Centrum Laboratory</h3><div class="sub">Hover a computer to see its status. '
                 'Click one to report it.</div></div></div>')
            portal.live_map(P, s, "labs", _show_pc, focus=focus, sel=tuple(sel) if sel else None)
        with box(f"{P}_lside", "stack", "gap10"):
            for lab, _ in D.LABS:
                hit(lab_tile(s, lab, on=focus == lab), f"{P}_ltile_{lab}", _focus, (lab,))
            if sel:
                lab, pc = sel
                r = D.pc_report(s, lab, pc)
                with box(f"{P}_lpc", "card"):
                    html(f'<div class="pc-panel"><div class="ph"><div class="ic {"ic-amber" if r else "ic-blue"}">{ic("pc")}</div>'
                         f'<div><h3>{D.lab_name(lab)} · {D.pc_name(pc)}</h3>'
                         + (badge(r["status"]) if r else '<span class="badge b-fixed">Working</span>') + '</div></div>'
                         + (f'<p class="muted" style="margin:0 0 14px">{h(r["issue"])} — reported {D.when(r["created"])}.</p>' if r
                            else '<p class="muted" style="margin:0 0 14px">No open reports for this computer.</p>') + "</div>")
                    with box(f"{P}_lpc_btn", "row"):
                        btn("Report this computer", f"{P}_lpc_report", "primary", icon=":material/add:", on_click=start_report,
                            args=(lab, pc))


def _save_number(number: str) -> tuple[bool, str]:
    ui.set_contact_number(number)
    return True, "Contact number updated (kept for this session - the server doesn't save teacher profiles yet)"


def page_profile(s: dict, user: dict) -> None:
    SHELL.profile_head(user, "Teacher", "Active account")
    with box(f"{P}_pf_grid", "g2", "mt"):
        with box(f"{P}_pf_contact", "card"):
            SHELL.contact_card(user, _save_number)
        with box(f"{P}_pf_act", "card"):
            items = sorted(((r, e) for r in mine(s) for e in r["history"]), key=lambda x: x[1]["t"], reverse=True)[:5]
            icons = {"fixed": "check", "reported": "plus"}
            body = "".join(row(icons.get(e["s"], "wrench"), "ic-blue",
                               f'{D.STATUS[e["s"]][0]} · {D.lab_name(r["lab"])} {D.pc_name(r["pc"])}',
                               f'{e["note"]} · {D.when(e["t"])}', last=i == len(items) - 1) for i, (r, e) in enumerate(items))
            html('<div class="card-h"><h3>My activity</h3></div>'
                 + (f'<div class="rows" style="margin-bottom:16px">{body}</div>' if body else empty("Nothing yet.", "list")))
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
    elif kind == "logout":
        SHELL.logout_window()


# ===========================================================================
# Public entry point
# ===========================================================================
def _notifications(s: dict) -> list[tuple]:
    items = sorted(((r, e) for r in mine(s) for e in r["history"][1:]), key=lambda x: x[1]["t"], reverse=True)[:6]
    return [("bell", "ic-blue", f"{D.lab_name(r['lab'])} · {D.pc_name(r['pc'])} is {D.STATUS[e['s']][0].lower()}",
             f"{e['note']} · {D.when(e['t'])}", view_report, (r["id"],)) for r, e in items]


def render(user: dict | None = None) -> None:
    """Draw the Teacher dashboard for `user` (a dict from your login)."""
    ui.page_config(ROLE)
    user = ui.require_user(user, ROLE, (ROLE.lower(),))
    ss[f"{P}_me"] = user["name"]
    s = store()
    page = SHELL.page
    SHELL.frame(user, s, {"reports": sum(r["status"] in D.OPEN for r in mine(s))}, _notifications(s))
    with SHELL.content():
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


# ---------------------------------------------------------------------------
# `streamlit run Teacher.py -- --preview`
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    current = ui.session_user()
    if current is None and "--preview" in sys.argv[1:]:
        ui.preview_logged_out()
        current = DEMO_USER
    if current is None:
        st.warning("You're not signed in. Log in from the main app first, or preview this "
                   "page with:  streamlit run Teacher.py -- --preview")
        st.stop()
    render(current)
