"""
frontend/admin.py - Centrum Laboratory | Admin dashboard (Streamlit)

The screens follow the admin design in centrum-laboratory-admin_1.html: navy
sidebar, top bar with notifications, white cards, chips, badges, the live floor
map, charts and pop-up windows. Shared parts are in frontend/portal.py, the
computer inventory (shared with the technician dashboard) in
frontend/inventory.py, data helpers in frontend/lab_data.py and the shared
store in frontend/lab_store.py.

Pages
-----
Dashboard     stats, live floor map (click a computer for its details),
              escalations, recent activity, laboratory tiles
Reports       filter chips, search, laboratory, Sort by, details window
Inventory     full inventory: list or live-map view, search, laboratory,
              status filter, Sort by, Export CSV, Add computer, computer
              details, Edit computer (details, hardware, software, log
              maintenance) - every change is saved for everyone
Analytics     stats, reports per week / laboratory / problem, laboratory
              health (Sort by)
Escalation    approve replacement / mark resolved / send back (asks first)
User Requests confirm or cancel account requests (Sort by)
My Profile    email, contact number, password, log out

Saving
------
- Reports and account requests are read from the backend
  (backend_client.get_admin_data -> /admin/dashboard) when you are signed in.
- Confirm / Cancel account request, contact number and password are saved
  through the backend, as before.
- The inventory, maintenance logs, escalation decisions on teacher reports and
  notifications are saved in the shared lab store (data/centrum_lab.json),
  because the backend has no endpoints for them yet.

How it is opened (app.py):

    from frontend import admin
    admin.render(user)

Just to look at it (no login needed), from the project root:

       python -m streamlit run frontend/admin.py -- --preview
"""

from __future__ import annotations

import sys
from datetime import timedelta

import streamlit as st

from frontend import backend_client
from frontend import inventory
from frontend import lab_data as D
from frontend import lab_store
from frontend import portal
from frontend import ui
from frontend.portal import PER, badge, bars_h, bars_v, ic, lab_tile, pager, sort_select, stat

ROLE = "Admin"
ALLOWED_ROLES = ("admin", "administrator")  # role names (lower-case) this page accepts
P = "admin"  # session-state prefix for this dashboard (cleared on log out)
ss = st.session_state

DEMO_USER = {"name": "Administrator", "email": "admin@isu.edu.ph", "contact_number": "", "role": ROLE}

PAGES = [  # key, label, icon
    ("dashboard", "Dashboard", "home"), ("reports", "Reports", "list"), ("inventory", "Inventory", "box"),
    ("analytics", "Analytics", "chart"), ("escalation", "Escalation", "up"), ("requests", "User Requests", "users"),
    ("profile", "My Profile", "user"),
]
SHELL = portal.Shell(P, ROLE, PAGES)
go, open_modal, close_modal, toast = SHELL.go, SHELL.open_modal, SHELL.close_modal, SHELL.toast

html, btn, hit, box, h = ui.html, ui.btn, ui.hit, ui.box, ui.h


# ===========================================================================
# Data
# ===========================================================================
def _fetch(token: str | None, preview: bool) -> dict:
    if preview:
        return D.empty_store()
    if not token:
        return D.empty_store("Not connected to the server - log out and log in again to load reports and "
                             "account requests. The inventory below is the shared one.")
    result = backend_client.get_admin_data(token)
    if not result.get("success"):
        return D.empty_store(f"Couldn't load live reports and account requests: {result.get('error') or 'unknown error'}. "
                             "Use Refresh to try again.")
    return D.live_store(result)


def store() -> dict:
    if f"{P}_data" not in ss:
        with st.spinner("Loading lab data..."):
            ss[f"{P}_data"] = _fetch(ss.get(ui.TOKEN_KEY), ss.get(f"{P}_preview", False))
    return lab_store.attach(ss[f"{P}_data"])


def refresh() -> None:
    ss.pop(f"{P}_data", None)
    toast("Data refreshed")


def me() -> str:
    return ss.get(f"{P}_me", "Admin")


INV = inventory.Inventory(SHELL, store, me, ROLE)
open_pc = INV.open_pc


# ===========================================================================
# Navigation (callbacks)
# ===========================================================================
def _reset_page(key: str) -> None:
    ss[key] = 0


def lab_reports(lab: int) -> None:
    ss[f"{P}_r_lab__sel__"] = lab
    ss[f"_keep_{P}_r_lab__sel__"] = lab
    ss[f"{P}_rfilter"] = "open"
    ss[f"{P}_rpage"] = 0
    go("reports")


def _counts(s: dict) -> dict:
    return {"escalation": sum(r["status"] == "escalated" for r in s["reports"]),
            "requests": sum(u["st"] == "pending" for u in s["requests"])}


def _open_report(rid: str) -> None:
    if any(r["id"] == rid for r in store()["reports"]):
        open_modal("report", rid)
    else:
        toast("That report is no longer available.", False)


def _notifications(s: dict) -> list[dict]:
    """Escalations and account requests waiting for the admin, new teacher reports and inventory updates."""
    out = []
    for r in s["reports"]:
        if r["status"] == "escalated":
            t = max((e["t"] for e in r["history"] if e["s"] == "escalated"), default=r["created"])
            out.append({"id": f"esc:{r['id']}:{t:%Y%m%d%H%M%S}", "icon": "up", "tone": "ic-violet",
                        "title": f"Escalation · {D.lab_name(r['lab'])} {D.pc_name(r['pc'])}",
                        "sub": r["esc_note"] or r["issue"], "t": t, "cb": _open_report, "args": (r["id"],),
                        "roles": ["admin"]})
    for u in s["requests"]:
        if u["st"] == "pending":
            out.append({"id": f"req:{u['id']}", "icon": "users", "tone": "ic-violet",
                        "title": f"Account request · {u['name']}", "sub": f"{u['role']} · {u['dept']}".strip(" ·"),
                        "t": u["t"] or D.now(), "cb": go, "args": ("requests",), "roles": ["admin"]})
    out += inventory.event_notifications("admin", me(), open_pc, _open_report)
    return out


# ===========================================================================
# Other actions (callbacks)
# ===========================================================================
_DECISIONS = {"approve": ("Approve the replacement?", "The report goes back to the technician as approved, under repair.",
                          "Approve replacement"),
              "resolve": ("Mark this report resolved?", "The report is closed as fixed and the teacher can see it.",
                          "Mark resolved"),
              "back": ("Send it back to the technician?", "The report goes back to 'Under repair' without a decision.",
                       "Send back")}


def _ask_decide(rid: str, what: str) -> None:
    title, text, label = _DECISIONS[what]
    SHELL.confirm(title, f"{rid}: {text}", label, _decide, (rid, what), danger=False)


def _decide(rid: str, what: str) -> None:
    s = store()
    r = next((x for x in s["reports"] if x["id"] == rid), None)
    if r is None:
        return toast("That report is no longer available.", False)
    if r["status"] != "escalated":
        return toast(f"{rid} was already handled.", False)
    with lab_store.lock():
        text = D.decide_escalation(s, r, what, me())
        lab_store.save()
        lab_store.add_event("escalation", f"{r['id']} · {text}", f"{D.lab_name(r['lab'])} {D.pc_name(r['pc'])} · {r['issue']}",
                            roles=("technician",), actor=me(), ref=("report", r["id"]))
        if what == "resolve":
            lab_store.add_event("status", f"Your report {r['id']} was resolved",
                                f"{D.lab_name(r['lab'])} {D.pc_name(r['pc'])} · {r['issue']}", roles=("teacher",),
                                actor=me(), to=r["by"], ref=("report", r["id"]))
    toast(text + ("" if r.get("local") or not s["live"] else " (saved here - the server has no endpoint for this yet)"))
    close_modal()


def _set_request(uid, st_: str) -> None:
    s = store()
    u = next((x for x in s["requests"] if x["id"] == uid), None)
    if u is None or u["st"] != "pending":
        close_modal()
        return toast("That request was already handled.", False)
    decision = "approve" if st_ == "active" else "cancel"
    done = f"{u['name']} confirmed — they can log in now" if st_ == "active" else f"{u['name']}'s request cancelled"
    if not s["live"]:
        close_modal()
        return toast("Not connected to the server - log in again to decide on account requests.", False)
    result = backend_client.decide_user_request(ss.get(ui.TOKEN_KEY), uid, decision, "")
    if not result.get("success"):
        close_modal()
        return toast(result.get("error") or "Could not save the decision.", False)
    u["st"], u["done"] = st_, D.now()
    toast(result.get("message") or done)
    close_modal()


def _save_number(number: str) -> tuple[bool, str]:
    if not store()["live"]:
        return False, "Not connected to the server - log in again to change your contact number."
    result = backend_client.admin_update_contact_number(ss.get(ui.TOKEN_KEY), number)
    if not result.get("success"):
        return False, result.get("error") or "Could not save the number."
    saved = result.get("user") if isinstance(result.get("user"), dict) else {}
    ui.set_contact_number(saved.get("contact_number", number))
    return True, result.get("message") or "Contact number updated"


def _change_password(current: str, new: str) -> tuple[bool, str]:
    if not store()["live"]:
        return False, "Not connected to the server - log in again to change your password."
    result = backend_client.admin_change_password(ss.get(ui.TOKEN_KEY), current, new)
    if not result.get("success"):
        return False, result.get("error") or "Could not change the password."
    return True, result.get("message") or "Password updated"


# ===========================================================================
# Pages
# ===========================================================================
def page_dashboard(s: dict, user: dict) -> None:
    with box(f"{P}_hello", "cardh"):
        html(f'<div class="hello" style="margin:0"><div><h2>Welcome back, {h(user["name"])}</h2>'
             f'<p>An overview of all four Centrum laboratories.</p></div></div>')
        with box(f"{P}_hello_btns", "row"):
            btn("Account requests", f"{P}_hello_req", "ghost", icon=":material/group:", on_click=go, args=("requests",))
            btn("Escalations", f"{P}_hello_esc", "primary", icon=":material/arrow_upward:", on_click=go, args=("escalation",))
    total = ok = 0
    for lab, _ in D.LABS:
        sm = D.lab_summary(s, lab)
        total, ok = total + sm["total"], ok + sm["ok"]
    pending = sum(u["st"] == "pending" for u in s["requests"])
    html('<div class="grid g4">' + stat("pc", "ic-blue", total, f"Computers in {len(D.LABS)} laboratories")
         + stat("check", "ic-green", f"{round(ok / total * 100) if total else 0}%", f"{ok} of {total} computers working")
         + stat("alert", "ic-amber", len(D.open_reports(s)), "Open reports")
         + stat("users", "ic-violet", pending, "Accounts waiting for approval") + "</div>")

    with box(f"{P}_dgrid", "gmap", "mt"):
        with box(f"{P}_dmapcard", "card"):
            html('<div class="card-h"><div><h3>Live floor map</h3><div class="sub">Hover a computer for its status, '
                 'click it for its hardware, software and maintenance history.</div></div></div>')
            kind, ref = SHELL.modal
            portal.live_map(P, s, "dash", open_pc, sel=tuple(ref) if kind == "pc" and ref else None)
        with box(f"{P}_dright", "stack"):
            esc = [r for r in s["reports"] if r["status"] == "escalated"]
            with box(f"{P}_desc", "card"):
                with box(f"{P}_desc_h", "cardh"):
                    oldest = D.when(min(r["created"] for r in esc)) if esc else ""
                    title = f"{len(esc)} escalation{'s' if len(esc) != 1 else ''} need your decision" if esc else "No escalations"
                    sub = f"Oldest from {oldest}" if esc else "Technicians have everything they need."
                    html(f'<div style="display:flex;gap:12px;align-items:center"><div class="ic ic-violet" style="width:40px;height:40px;'
                         f'border-radius:12px;display:grid;place-items:center">{ic("up")}</div><div><h3>{h(title)}</h3>'
                         f'<div class="sub">{h(sub)}</div></div></div>')
                    if esc:
                        btn("Review", f"{P}_desc_btn", "primarysm", on_click=go, args=("escalation",))
            with box(f"{P}_dact", "card"):
                with box(f"{P}_dact_h", "cardh"):
                    html("<div><h3>Recent activity</h3></div>")
                    btn("All reports", f"{P}_dact_all", "link", on_click=go, args=("reports",))
                events = sorted(((r, ev) for r in s["reports"] for ev in r["history"]), key=lambda x: x[1]["t"], reverse=True)[:6]
                if not events:
                    html('<div class="empty">No activity yet.</div>')
                for i, (r, ev) in enumerate(events):
                    tone = {"fixed": "ic-green", "reported": "ic-amber", "escalated": "ic-violet"}.get(ev["s"], "ic-red")
                    icon_name = {"fixed": "check", "reported": "alert", "escalated": "up"}.get(ev["s"], "wrench")
                    text = f"{D.by_name(r)}: {r['issue']}" if ev["s"] == "reported" else ev["note"]
                    last = " last" if i == len(events) - 1 else ""
                    hit(f'<div class="row clickable{last}"><div class="ic {tone}">{ic(icon_name)}</div><div class="main-t">'
                        f'<b>{D.STATUS[ev["s"]][0]} · {D.lab_name(r["lab"])} {D.pc_name(r["pc"])}</b>'
                        f'<span>{h(text)} · {D.when(ev["t"])}</span></div></div>', f"{P}_act_{i}", open_modal, ("report", r["id"]))
    with box(f"{P}_dlabs", "g4", "mt"):
        for lab, _ in D.LABS:
            hit(lab_tile(s, lab), f"{P}_dlab_{lab}", lab_reports, (lab,))


R_FILTERS = [("all", "All"), ("open", "Open"), ("reported", "New"), ("repair", "Under repair"), ("escalated", "Escalated"),
             ("fixed", "Fixed")]


def _r_match(r: dict, f: str) -> bool:
    return f == "all" or (r["status"] in D.OPEN if f == "open" else r["status"] == f)


def page_reports(s: dict) -> None:
    flt = ss.setdefault(f"{P}_rfilter", "all")
    page_key = f"{P}_rpage"
    with box(f"{P}_rcard", "card", "pad0"):
        with box(f"{P}_rhead", "cardh", "padh"):
            with box(f"{P}_rchips", "chips"):
                for key, label in R_FILTERS:
                    n = sum(_r_match(r, key) for r in s["reports"])
                    btn(f"{label} · {n}", f"{P}_rf_{key}", "chipon" if flt == key else "chip",
                        on_click=lambda k=key: (ss.__setitem__(f"{P}_rfilter", k), ss.__setitem__(page_key, 0)))
            with box(f"{P}_rctl", "rowend", "full"):
                q = st.text_input("Search", placeholder="Search report, PC or person", label_visibility="collapsed",
                                  key=ui.sticky(f"{P}_r_q__search__"), on_change=_reset_page, args=(page_key,))
                labs = [0] + [l for l, _ in D.LABS]
                lab = st.selectbox("Laboratory", labs, format_func=lambda x: D.lab_name(x) if x else "All labs",
                                   key=ui.sticky(f"{P}_r_lab__sel__", labs), label_visibility="collapsed",
                                   on_change=_reset_page, args=(page_key,))
                how = sort_select(f"{P}_r_sort__selwide__", {k: f"Sort: {v}" for k, v in D.REPORT_SORTS.items()})
                ui.remember(f"{P}_r_q__search__")
                ui.remember(f"{P}_r_lab__sel__")
        q = (q or "").strip().lower()
        rows = [r for r in s["reports"] if _r_match(r, flt) and (not lab or r["lab"] == lab)
                and (not q or q in f"{r['id']} {D.pc_name(r['pc'])} {D.lab_name(r['lab'])} {D.by_name(r)} {r['tech'] or ''} {r['issue']}".lower())]
        rows = D.sort_reports(rows, how)
        page = min(ss.get(page_key, 0), max(0, (len(rows) - 1) // PER))
        cols = "grid-template-columns:86px minmax(0,1.1fr) minmax(0,1.2fr) minmax(0,1.2fr) minmax(0,1.1fr) 108px 128px 100px;"
        html(f'<div class="tt-head" style="{cols}"><div>Report</div><div>Computer</div><div>Problem</div><div>Reported by</div>'
             f'<div>Technician</div><div>Sent</div><div>Status</div><div>&nbsp;</div></div>')
        if not rows:
            html('<div class="empty">No reports match.</div>')
        for r in rows[page * PER:(page + 1) * PER]:
            hit(f'<div class="tt-row" style="{cols}"><div class="strong">{h(r["id"])}</div>'
                f'<div>{D.lab_name(r["lab"])}<div class="small">{D.pc_name(r["pc"])}</div></div><div>{h(r["issue"])}</div>'
                f'<div>{h(D.by_name(r))}</div><div>{h(r["tech"] or "—")}</div><div>{D.when(r["created"])}</div>'
                f'<div>{badge(r["status"])}</div><div style="text-align:right"><span class="fakebtn">View</span></div></div>',
                f"{P}_r_{r['id']}", open_modal, ("report", r["id"]))
        pager(page_key, page, len(rows))


def page_analytics(s: dict) -> None:
    now = D.now()
    d30 = [r for r in s["reports"] if r["created"] > now - timedelta(days=30)]
    fixed = [r for r in s["reports"] if D.fixed_at(r)]

    def avg_fix(lst):
        secs = [(D.fixed_at(r) - r["created"]).total_seconds() for r in lst if D.fixed_at(r)]
        return sum(secs) / len(secs) if secs else 0

    a = avg_fix([r for r in fixed if D.fixed_at(r) > now - timedelta(days=30)])
    in24 = round(sum((D.fixed_at(r) - r["created"]).total_seconds() <= 86400 for r in fixed) / len(fixed) * 100) if fixed else None
    html('<div class="grid g3">' + stat("list", "ic-blue", len(d30), "Reports in the last 30 days")
         + stat("clock", "ic-green", D.dur(a) if a else "–", "Average time to fix")
         + stat("check", "ic-violet", f"{in24}%" if in24 is not None else "–", "Fixed within 24 hours") + "</div>")
    weeks = []
    for w in range(7, -1, -1):
        start, end = now - timedelta(days=(w + 1) * 7), now - timedelta(days=w * 7)
        d = start + timedelta(days=1)
        weeks.append((f"Week of {d:%b} {d.day}", "This wk" if w == 0 else f"{d:%b} {d.day}",
                      sum(start < r["created"] <= end for r in s["reports"])))
    html(f'<div class="card mt"><div class="card-h"><div><h3>Reports per week</h3><div class="sub">All laboratories, last 8 weeks'
         f'</div></div></div>{bars_v(weeks, "reports", ("Week", "Reports"))}</div>')
    by_lab = [(D.lab_name(l), D.lab_name(l), sum(r["lab"] == l for r in d30)) for l, _ in D.LABS]
    by_issue = sorted(((x, x, sum(r["issue"] == x for r in d30)) for x in D.ISSUES), key=lambda t: -t[2])
    extra = sorted({r["issue"] for r in d30} - set(D.ISSUES))
    by_issue += [(x, x, sum(r["issue"] == x for r in d30)) for x in extra]
    html(f'<div class="grid g2 mt"><div class="card"><div class="card-h"><div><h3>Reports by laboratory</h3><div class="sub">'
         f'Last 30 days</div></div></div>{bars_v(by_lab, "reports", ("Laboratory", "Reports"))}</div>'
         f'<div class="card"><div class="card-h"><div><h3>Reports by problem</h3><div class="sub">Last 30 days</div></div></div>'
         f'{bars_h(by_issue, "reports", ("Problem", "Reports"))}</div></div>')

    health = []
    for lab, wing in D.LABS:
        sm = D.lab_summary(s, lab)
        health.append({"lab": lab, "wing": wing, "ok": sm["ok"], "total": sm["total"],
                       "pct": sm["ok"] / sm["total"] if sm["total"] else 0,
                       "open": sum(r["lab"] == lab for r in D.open_reports(s)),
                       "recent": sum(r["lab"] == lab for r in d30), "fix": avg_fix([r for r in fixed if r["lab"] == lab])})
    with box(f"{P}_health", "card", "pad0", "mt"):
        with box(f"{P}_health_h", "cardh", "padh"):
            html('<div><h3>Laboratory health</h3></div>')
            with box(f"{P}_health_sort", "row"):
                how = sort_select(f"{P}_health_sort__selwide__", {k: f"Sort: {v}" for k, v in D.HEALTH_SORTS.items()})
        keys = {"working": lambda x: x["pct"], "open": lambda x: -x["open"], "recent": lambda x: -x["recent"],
                "fix": lambda x: -x["fix"]}
        health.sort(key=keys.get(how, lambda x: x["lab"]))
        rows = "".join(
            f'<tr><td class="strong">{D.lab_name(x["lab"])}<div class="small">{h(x["wing"])}</div></td><td>{x["ok"]} of {x["total"]} '
            f'<span class="small">({round(x["pct"] * 100)}%)</span></td><td>{x["open"]}</td><td>{x["recent"]}</td>'
            f'<td>{D.dur(x["fix"]) if x["fix"] else "&ndash;"}</td></tr>' for x in health)
        html(f'<div class="table-wrap" style="margin:0"><table class="t"><thead><tr><th>Laboratory</th><th>Working now</th>'
             f'<th>Open reports</th><th>Reports (30 days)</th><th>Avg. time to fix</th></tr></thead><tbody>{rows}</tbody></table></div>')


def page_escalation(s: dict) -> None:
    with box(f"{P}_e_top", "cardh"):
        html('<p class="muted" style="margin:0">Technicians escalate a report when a computer needs parts, a replacement or '
             'your decision.</p>')
        with box(f"{P}_e_sort", "row"):
            how = sort_select(f"{P}_e_sort__selwide__", {k: f"Sort: {v}" for k, v in D.ESCALATION_SORTS.items()})
    lst = [r for r in s["reports"] if r["status"] == "escalated"]
    keys = {"new": lambda r: -r["created"].timestamp(), "lab": lambda r: (r["lab"], r["created"]),
            "computer": lambda r: (r["lab"], r["pc"])}
    lst.sort(key=keys.get(how, lambda r: r["created"]))
    if not lst:
        html(f'<div class="card"><div class="empty">{ic("check")}<div>No escalations right now.</div></div></div>')
    with box(f"{P}_e_list", "g2"):
        for r in lst:
            with box(f"{P}_e_{r['id']}", "card"):
                html(f'<div class="card-h"><div class="ic ic-violet" style="width:44px;height:44px;border-radius:12px;display:grid;'
                     f'place-items:center">{ic("up")}</div><div><h3>{D.lab_name(r["lab"])} · {D.pc_name(r["pc"])}</h3>'
                     f'<div class="sub">{h(r["id"])} · {h(r["issue"])} · reported {D.when(r["created"])}</div></div></div>'
                     f'<dl class="kv"><dt>Technician</dt><dd>{h(r["tech"] or "&mdash;")}</dd><dt>What\'s needed</dt>'
                     f'<dd>{h(r["esc_note"] or "No note")}</dd><dt>Reported by</dt><dd>{h(D.by_name(r))}</dd></dl>')
                with box(f"{P}_e_btns_{r['id']}", "row"):
                    btn("Approve replacement", f"{P}_e_ap_{r['id']}", "primarysm", on_click=_ask_decide, args=(r["id"], "approve"))
                    btn("Mark resolved", f"{P}_e_rs_{r['id']}", "successsm", on_click=_ask_decide, args=(r["id"], "resolve"))
                    btn("Send back", f"{P}_e_bk_{r['id']}", "ghostsm", on_click=_ask_decide, args=(r["id"], "back"))
                    btn("Details", f"{P}_e_hi_{r['id']}", "ghostsm", on_click=open_modal, args=("report", r["id"]))
    done = list(reversed(s["decided"]))
    rows = "".join(f'<div class="row"><div class="ic ic-green">{ic("check")}</div><div class="main-t"><b>{h(d["r"]["id"])} · '
                   f'{D.lab_name(d["r"]["lab"])} {D.pc_name(d["r"]["pc"])}</b><span>{h(d["text"])} · {D.when(d["t"])}</span>'
                   f'</div>{badge(d["r"]["status"])}</div>' for d in done)
    html(f'<div class="card mt"><div class="card-h"><h3>Recently decided</h3></div><div class="rows">'
         + (rows or '<div class="empty" style="padding:20px">Decisions you make here will show up in this list.</div>') + "</div></div>")


def page_requests(s: dict) -> None:
    if not s["live"]:
        html(f'<div class="demo-note">{ic("info")}<span><b>Not connected to the server.</b> Account requests are '
             f'loaded from the server - log out and log in again to see and decide on them.</span></div>')
    pending = [u for u in s["requests"] if u["st"] == "pending"]
    with box(f"{P}_u_card", "card", "pad0"):
        with box(f"{P}_u_head", "cardh", "padh"):
            html('<div><h3>Waiting for approval</h3><div class="sub">New technician accounts '
                 'can\'t log in until you confirm them.</div></div>')
            with box(f"{P}_u_sort", "row"):
                how = sort_select(f"{P}_u_sort__selwide__", {k: f"Sort: {v}" for k, v in D.REQUEST_SORTS.items()})
        grid = "minmax(0,1.4fr) minmax(0,1.6fr) minmax(0,.8fr) minmax(0,.8fr) minmax(0,.9fr)"
        cols = f"grid-template-columns:{grid};"
        html(f'<div class="tt-head" style="grid-template-columns:{grid} 198px"><div>Name</div><div>Email</div>'
             f'<div>Department</div><div>Role</div><div>Requested</div><div style="text-align:right">Decision</div></div>')
        if not pending:
            html(f'<div class="empty">{ic("check")}<div>No account requests waiting.</div></div>')
        for u in D.sort_requests(pending, how):
            ini = "".join(w[0] for w in u["name"].split()[:2]).upper()
            with box(f"{P}_u_{u['id']}", "trow"):
                html(f'<div class="tt-row" style="{cols}"><div><div style="display:flex;gap:10px;align-items:center"><div class="avatar" '
                     f'style="width:32px;height:32px;font-size:12px;background:linear-gradient(135deg,#6b7a90,#14213d)">{h(ini)}</div>'
                     f'<span class="strong">{h(u["name"])}</span></div></div><div>{h(u["email"])}</div><div>{h(u["dept"])}</div>'
                     f'<div><span class="badge b-neutral">{h(u["role"])}</span></div><div>{D.when(u["t"])}</div></div>')
                with box(f"{P}_u_act_{u['id']}", "row", "gap6", "acts"):
                    btn("Confirm", f"{P}_u_ok_{u['id']}", "successsm", on_click=_set_request, args=(u["id"], "active"))
                    btn("Cancel", f"{P}_u_no_{u['id']}", "dangersm", on_click=open_modal, args=("cancelreq", u["id"]))
    handled = [u for u in s["requests"] if u["st"] != "pending"]
    with box(f"{P}_u_done", "card", "pad0", "mt"):
        with box(f"{P}_u_done_h", "cardh", "padh"):
            html('<div><h3>Recently handled</h3></div>')
            with box(f"{P}_u_done_sort", "row"):
                how2 = sort_select(f"{P}_u_done_sort__selwide__", {k: f"Sort: {v}" for k, v in D.REQUEST_SORTS.items()})
        rows = "".join(
            f'<tr><td class="strong">{h(u["name"])}</td><td>{h(u["email"])}</td><td>{h(u["role"])}</td><td>'
            + ('<span class="badge b-fixed">Confirmed</span>' if u["st"] == "active" else '<span class="badge b-repair">Cancelled</span>')
            + f'</td><td>{D.when(u["done"])}</td></tr>' for u in D.sort_requests(handled, how2, done=True))
        html('<div class="table-wrap" style="margin:0"><table class="t"><thead><tr><th>Name</th><th>Email</th><th>Role</th>'
             '<th>Decision</th><th>When</th></tr></thead><tbody>'
             + (rows or '<tr><td colspan="5"><div class="empty" style="padding:20px">Nothing yet.</div></td></tr>') + "</tbody></table></div>")


def page_profile(user: dict) -> None:
    SHELL.profile_head(user, "Admin", "Full access")
    with box(f"{P}_pf_grid", "g2", "mt"):
        with box(f"{P}_pf_contact", "card"):
            SHELL.contact_card(user, _save_number,
                               email_note="Email changes must be made in Supabase (the login uses this email).")
        with box(f"{P}_pf_account", "card"):
            html('<div class="card-h"><h3>Account</h3></div><p class="muted" style="margin:0 0 16px">You can approve accounts, '
                 'handle escalations and manage the computer inventory of every laboratory.</p>')
            SHELL.logout_button()
    SHELL.password_card(_change_password)


# ===========================================================================
# Pop-up windows
# ===========================================================================
def modal_report(s: dict, rid: str) -> None:
    r = next((x for x in s["reports"] if x["id"] == rid), None)
    if r is None:
        return close_modal()
    with SHELL.window():
        html(portal.report_details(r))
        with box(f"{P}_m_act", "mactions"):
            if (r["lab"], r["pc"]) in s["computers"]:
                btn("View computer", f"{P}_m_pc", "ghost", on_click=open_pc, args=(r["lab"], r["pc"]))
            if r["status"] == "escalated":
                btn("Decide on escalation", f"{P}_m_esc", "primary", on_click=go, args=("escalation",))
            btn("Close", f"{P}_m_close", "ghost", on_click=close_modal)


def modal_cancel_request(ref) -> None:
    u = next((x for x in store()["requests"] if x["id"] == ref), None)
    if u is None:
        return close_modal()
    with box(f"{P}_modal", "modal"):
        html(f"<h3>Cancel {h(u['name'])}'s request?</h3><div class=\"m-sub\">They won't be able to log in as a "
             f"{h(u['role'].lower() or 'user')}. They can sign up again later.</div>")
        with box(f"{P}_cr_btns", "mactions"):
            btn("Keep request", f"{P}_cr_keep", "ghost", on_click=close_modal)
            btn("Cancel request", f"{P}_cr_go", "danger", on_click=_set_request, args=(ref, "rejected"))


def render_modal(s: dict) -> None:
    kind, ref = ss.get(f"{P}_modal") or (None, None)
    if not kind:
        return
    if kind == "report":
        modal_report(s, ref)
    elif kind == "cancelreq":
        modal_cancel_request(ref)
    elif not INV.render_modal(s, kind, ref) and not SHELL.common_modal(kind):
        close_modal()


# ===========================================================================
# Public entry point
# ===========================================================================
def render(user: dict | None = None, preview: bool = False) -> None:
    """Draw the Admin dashboard for `user` (a dict from your login)."""
    ui.page_config(ROLE)
    user = ui.require_user(user, ROLE, ALLOWED_ROLES)
    ss[f"{P}_preview"] = preview
    ss[f"{P}_me"] = user["name"]
    s = store()
    page = SHELL.page
    SHELL.frame(user, s, _counts(s), _notifications(s))
    with SHELL.content():
        if s.get("notice") and page not in ("inventory", "profile"):
            with box(f"{P}_notice", "row", "spread"):
                html(f'<div class="demo-note" style="margin:0">{ic("info")}<span>{h(s["notice"])}</span></div>')
                btn("Refresh", f"{P}_refresh", "ghostsm", icon=":material/refresh:", on_click=refresh)
            html('<div style="height:18px"></div>')
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
            page_dashboard(s, user)
        render_modal(s)


# ---------------------------------------------------------------------------
# `python -m streamlit run frontend/admin.py -- --preview`
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    preview = "--preview" in sys.argv[1:]
    current = ui.session_user()
    if current is None and preview:
        ui.preview_logged_out()
        current = DEMO_USER
    if current is None:
        st.warning("You're not signed in. Log in from the main app first, or preview this "
                   "page with:  python -m streamlit run frontend/admin.py -- --preview")
        st.stop()
    render(current, preview=preview)
