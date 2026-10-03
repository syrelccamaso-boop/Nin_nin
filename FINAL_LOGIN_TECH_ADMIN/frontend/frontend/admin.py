"""
frontend/admin.py - Centrum Laboratory | Admin dashboard (Streamlit)

The screens follow the admin design in centrum-laboratory-admin_1.html: navy
sidebar, top bar with notifications, white cards, chips, badges, the live floor
map, charts and pop-up windows. It is built in Python with Streamlit (no HTML
file or iframe): display parts use the design's own CSS and markup
(frontend/admin_design.py), every button, field and filter is a real Streamlit
widget dressed to match. Data and changes are in frontend/admin_data.py.

Pages
-----
Dashboard     stats, live floor map (click a computer for its details),
              escalations, recent activity, laboratory tiles
Reports       filter chips, search, laboratory, Sort by, details window
Inventory     computers only: list or live-map view, search, laboratory,
              status filter, Sort by, Add computer, computer details
              (hardware, software, maintenance history), Edit computer
              (hardware changes, software install/update/remove, log
              maintenance) - every change is added to maintenance history
Analytics     stats, reports per week / laboratory / problem, laboratory
              health (Sort by)
Escalation    approve replacement / mark resolved / send back (Sort by)
User Requests confirm or cancel account requests (Sort by)
My Profile    email, contact number, password, log out

Saving
------
- Reports, computers and account requests are read from the backend
  (backend_client.get_admin_data -> /admin/dashboard) when you are signed in.
- Confirm / Cancel account request, contact number and password are saved
  through the backend, as before.
- The backend has no endpoints yet for adding or editing computers, logging
  maintenance or deciding escalations, so those changes are kept for this
  browser session only (a note in the top bar says so).

How it is opened (app.py):

    from frontend import admin
    admin.render(user)

Just to look at it (sample data, no login needed), from the project root:

       python -m streamlit run frontend/admin.py -- --preview
"""

from __future__ import annotations

import re
import sys
from datetime import timedelta

import streamlit as st

from frontend import backend_client
from frontend import lab_data as D
from frontend import portal
from frontend import ui
from frontend.portal import PER, badge, bars_h, bars_v, comp_badge, ic, lab_tile, pager, sort_select, stat

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
_set, field = portal._set, portal.field

html, btn, hit, box, h = ui.html, ui.btn, ui.hit, ui.box, ui.h


# ===========================================================================
# Data
# ===========================================================================
def _fetch(token: str | None, preview: bool) -> dict:
    if preview:
        return D.sample_store()
    if not token:
        return D.sample_store("Showing sample data - please log out and log in again to load live data.")
    result = backend_client.get_admin_data(token)
    if not result.get("success"):
        return D.sample_store(f"Showing sample data - {result.get('error') or 'could not load live data.'}")
    return D.live_store(result)


def store() -> dict:
    if f"{P}_data" not in ss:
        with st.spinner("Loading lab data..."):
            ss[f"{P}_data"] = _fetch(ss.get(ui.TOKEN_KEY), ss.get(f"{P}_preview", False))
    return ss[f"{P}_data"]


def me() -> str:
    return ss.get(f"{P}_me", "Admin")


def _session_only() -> str:
    return "" if not store()["live"] else " (saved for this session - not in the database yet)"


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


def _notifications(s: dict) -> list[tuple]:
    out = []
    for r in s["reports"]:
        if r["status"] == "escalated":
            out.append(("up", "ic-violet", f"Escalated · {D.lab_name(r['lab'])} {D.pc_name(r['pc'])}",
                        r["esc_note"] or r["issue"], go, ("escalation",)))
    for u in s["requests"]:
        if u["st"] == "pending":
            out.append(("users", "ic-violet", f"Account request · {u['name']}", f"{u['role']} · {D.when(u['t'])}",
                        go, ("requests",)))
    return out[:6]


# ===========================================================================
# Computer details (used in the pop-up and in the inventory map view)
# ===========================================================================
def open_pc(lab: int, pc: int) -> None:
    ss[f"{P}_pctab"] = "hardware"
    open_modal("pc", (lab, pc))


def computer_details(s: dict, comp: dict, ctx: str, in_modal: bool) -> None:
    lab, pc = comp["lab"], comp["pc"]
    status = D.pc_status(s, lab, pc)
    tone = {"ok": "ic-blue", "reported": "ic-amber", "repair": "ic-red", "escalated": "ic-violet"}[status]
    name = f" · {h(comp['name'])}" if comp["name"] != comp["tag"] else ""
    html(f'<div class="pc-panel"><div class="ph"><div class="ic {tone}">{ic("pc")}</div><div style="flex:1;min-width:0">'
         f'<h3 style="font-size:17px">{h(comp["tag"])}{name}</h3><div class="sub" style="font-size:12.5px;color:var(--faint)">'
         f'{D.lab_name(lab)} · {D.pc_name(pc)} · {D.WING.get(lab, "")}</div></div>{comp_badge(status)}</div></div>')
    r = D.pc_report(s, lab, pc)
    if r:
        with box(f"{P}_pcrep_{ctx}", "row", "gap14"):
            html(f'<div class="demo-note" style="margin:0 0 14px">{ic("alert")}<span><b>{h(r["id"])}</b> · '
                 f'{h(r["issue"])} · {D.when(r["created"])}</span></div>')
            btn("View report", f"{P}_pcrep_btn_{ctx}", "ghostsm", on_click=open_modal, args=("report", r["id"]))

    history = D.maintenance_history(s, comp)
    tab_key = f"{P}_pctab"
    tab = ss.get(tab_key, "hardware")
    with box(f"{P}_pctabs_{ctx}", "chips"):
        for key, label in (("hardware", "Hardware"), ("software", f"Software · {len(comp['software'])}"),
                           ("history", f"Maintenance history · {len(history)}")):
            btn(label, f"{P}_pct_{ctx}_{key}", "chipon" if tab == key else "chip", on_click=_set, args=(tab_key, key))
    html('<div style="height:14px"></div>')
    if tab == "software":
        rows = "".join(f'<dt>{h(x["name"])}</dt><dd>{h(x["version"] or "—")}</dd>' for x in comp["software"])
        html(f'<dl class="kv">{rows}</dl>' if rows else '<div class="empty">No software recorded.</div>')
    elif tab == "history":
        with box(f"{P}_hist_sort_{ctx}", "row"):
            html('<span class="muted" style="font-size:13px">Sort by</span>')
            how = sort_select(f"{P}_hist_sort__sel__", D.HISTORY_SORTS)
        if how == "old":
            history = sorted(history, key=lambda e: e["t"])
        elif how == "kind":
            history = sorted(history, key=lambda e: (e["kind"], -e["t"].timestamp()))
        html('<div style="height:12px"></div>')
        items = "".join(f'<li><b>{h(e["kind"])}</b> — {h(e["text"])}<span>{D.date_time(e["t"])} · {h(e["by"])}</span></li>'
                        for e in history)
        html(f'<ul class="timeline">{items}</ul>' if items else '<div class="empty">No maintenance recorded yet.</div>')
    else:
        rows = "".join(f'<dt>{h(k)}</dt><dd>{h(v)}</dd>' for k, v in comp["hardware"].items())
        rows += f'<dt>Asset tag</dt><dd>{h(comp["tag"])}</dd>'
        if comp.get("notes"):
            rows += f'<dt>Notes</dt><dd>{h(comp["notes"])}</dd>'
        last = D.last_serviced(s, comp)
        rows += f'<dt>Last serviced</dt><dd>{D.when(last) if last else "—"}</dd>'
        html(f'<dl class="kv">{rows}</dl>')
    with box(f"{P}_pcact_{ctx}", "mactions"):
        btn("Log maintenance", f"{P}_pc_log_{ctx}", "ghost", on_click=open_edit, args=(lab, pc, "log"))
        btn("Edit computer", f"{P}_pc_edit_{ctx}", "primary", on_click=open_edit, args=(lab, pc, "details"))
        if in_modal:
            btn("Close", f"{P}_pc_close_{ctx}", "ghost", on_click=close_modal)


# ===========================================================================
# Inventory changes (callbacks)
# ===========================================================================
def _ek(name: str) -> str:
    return f"{P}_ed_{re.sub(r'[^a-z0-9]+', '_', name.lower())}"


def open_edit(lab: int, pc: int, tab: str = "details") -> None:
    comp = store()["computers"][(lab, pc)]
    ss[_ek("name")] = comp["name"]
    ss[_ek("notes")] = comp.get("notes", "")
    for label in _hw_labels(comp):
        ss[_ek("hw " + label)] = comp["hardware"].get(label, "")
    for k in ("sw name", "sw version", "log text"):
        ss[_ek(k)] = ""
    ss[_ek("log by")] = me()
    ss.pop(f"{P}_sw_upd", None)
    ss[f"{P}_edtab"] = tab
    open_modal("edit", (lab, pc))


def _hw_labels(comp: dict) -> list[str]:
    return D.HW_FIELDS + [k for k in comp["hardware"] if k not in D.HW_FIELDS]


def _save_details(lab: int, pc: int) -> None:
    s = store()
    comp = s["computers"][(lab, pc)]
    hw = {label: ss.get(_ek("hw " + label), "") or "" for label in _hw_labels(comp)}
    ok, msg = D.update_details(s, comp, name=ss.get(_ek("name"), ""), notes=ss.get(_ek("notes"), ""), hardware=hw, by=me())
    toast(msg + (_session_only() if ok else ""), ok)
    if ok:
        open_modal("pc", (lab, pc))
        ss[f"{P}_pctab"] = "history"


def _install(lab: int, pc: int) -> None:
    comp = store()["computers"][(lab, pc)]
    ok, msg = D.install_software(comp, ss.get(_ek("sw name"), ""), ss.get(_ek("sw version"), ""), me())
    toast(msg + (_session_only() if ok else ""), ok)
    if ok:
        ss[_ek("sw name")] = ""
        ss[_ek("sw version")] = ""


def _start_sw_update(name: str, version: str) -> None:
    ss[f"{P}_sw_upd"] = name
    ss[_ek("sw new version")] = version


def _sw_update(lab: int, pc: int, name: str) -> None:
    comp = store()["computers"][(lab, pc)]
    ok, msg = D.update_software(comp, name, ss.get(_ek("sw new version"), ""), me())
    toast(msg + (_session_only() if ok else ""), ok)
    if ok:
        ss.pop(f"{P}_sw_upd", None)


def _sw_remove(lab: int, pc: int, name: str) -> None:
    comp = store()["computers"][(lab, pc)]
    ok, msg = D.remove_software(comp, name, me())
    toast(msg + (_session_only() if ok else ""), ok)


def _save_log(lab: int, pc: int) -> None:
    comp = store()["computers"][(lab, pc)]
    ok, msg = D.log_maintenance(comp, ss.get(_ek("log kind")) or "Repair", ss.get(_ek("log text"), ""),
                                ss.get(_ek("log by"), "") or me())
    toast(msg + (_session_only() if ok else ""), ok)
    if ok:
        open_modal("pc", (lab, pc))
        ss[f"{P}_pctab"] = "history"


def open_add() -> None:
    s = store()
    lab = 1
    ss[_ek("add lab")] = lab
    ss[_ek("add pc")] = str(D.next_free_pc(s, lab))
    ss[_ek("add name")] = ""
    ss[_ek("add notes")] = ""
    for label, value in zip(D.HW_FIELDS, D.SPECS[lab]):
        ss[_ek("add hw " + label)] = value
    ss[_ek("add sw")] = [n for n, _ in D.DEFAULT_SOFTWARE if n in D.COMMON_SOFTWARE]
    ss[_ek("add sw other")] = ""
    open_modal("add")


def _add_lab_changed() -> None:
    s = store()
    lab = ss.get(_ek("add lab")) or 1
    ss[_ek("add pc")] = str(D.next_free_pc(s, lab))
    for label, value in zip(D.HW_FIELDS, D.SPECS.get(lab, D.SPECS[1])):
        ss[_ek("add hw " + label)] = value


def _save_add() -> None:
    s = store()
    lab = int(ss.get(_ek("add lab")) or 1)
    raw = str(ss.get(_ek("add pc")) or "").strip()
    if not raw.isdigit() or not 1 <= int(raw) <= 999:
        return toast("Enter the computer's number in the laboratory (1–999).", False)
    pc = int(raw)
    hw = {label: ss.get(_ek("add hw " + label), "") or "" for label in D.HW_FIELDS}
    defaults = dict(D.DEFAULT_SOFTWARE)
    software = [{"name": n, "version": defaults.get(n, "")} for n in ss.get(_ek("add sw")) or []]
    for item in (ss.get(_ek("add sw other")) or "").split(","):
        if item.strip():
            parts = item.strip().rsplit(" ", 1)
            ver = parts[1] if len(parts) == 2 and re.match(r"^v?[\d.]+$", parts[1]) else ""
            software.append({"name": parts[0] if ver else item.strip(), "version": ver})
    ok, msg = D.add_computer(s, lab=lab, pc=pc, name=ss.get(_ek("add name"), "") or "", hardware=hw, software=software,
                             notes=ss.get(_ek("add notes"), "") or "", by=me())
    toast(msg + (_session_only() if ok else ""), ok)
    if ok:
        ss[f"{P}_pctab"] = "hardware"
        ss[f"{P}_inv_sel"] = (lab, pc)
        open_modal("pc", (lab, pc))


# ===========================================================================
# Other actions (callbacks)
# ===========================================================================
def _decide(rid: str, what: str) -> None:
    s = store()
    r = next((x for x in s["reports"] if x["id"] == rid), None)
    if r is None:
        return
    text = D.decide_escalation(s, r, what, me())
    toast(text + _session_only())
    close_modal()


def _set_request(uid, st_: str) -> None:
    s = store()
    u = next((x for x in s["requests"] if x["id"] == uid), None)
    if u is None or u["st"] != "pending":
        return close_modal()
    decision = "approve" if st_ == "active" else "cancel"
    done = f"{u['name']} confirmed — they can log in now" if st_ == "active" else f"{u['name']}'s request cancelled"
    if s["live"]:
        result = backend_client.decide_user_request(ss.get(ui.TOKEN_KEY), uid, decision, "")
        if not result.get("success"):
            close_modal()
            return toast(result.get("error") or "Could not save the decision.", False)
        done = result.get("message") or done
    u["st"], u["done"] = st_, D.now()
    toast(done + ("" if s["live"] else " (sample only)"))
    close_modal()


def _save_number(number: str) -> tuple[bool, str]:
    if not store()["live"]:
        ui.set_contact_number(number)
        return True, "Contact number updated (sample data)"
    result = backend_client.admin_update_contact_number(ss.get(ui.TOKEN_KEY), number)
    if not result.get("success"):
        return False, result.get("error") or "Could not save the number."
    saved = result.get("user") if isinstance(result.get("user"), dict) else {}
    ui.set_contact_number(saved.get("contact_number", number))
    return True, result.get("message") or "Contact number updated"


def _change_password(current: str, new: str) -> tuple[bool, str]:
    if not store()["live"]:
        return True, "Password updated (sample data - nothing was saved)"
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
            portal.live_map(P, s, "dash", open_pc, sel=ss.get(f"{P}_modal", (None, None))[1] if ss.get(f"{P}_modal", (None,))[0] == "pc" else None)
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


I_FILTERS = [("all", "All computers"), ("ok", "Working"), ("attention", "Needs attention"), ("escalated", "Escalated")]


def page_inventory(s: dict) -> None:
    comps = list(s["computers"].values())
    statuses = {(c["lab"], c["pc"]): D.pc_status(s, c["lab"], c["pc"]) for c in comps}
    html('<div class="grid g4">'
         + stat("pc", "ic-blue", len(comps), "Computers")
         + stat("check", "ic-green", sum(v == "ok" for v in statuses.values()), "Working")
         + stat("alert", "ic-amber", sum(v == "reported" for v in statuses.values()), "Reported")
         + stat("wrench", "ic-red", sum(v in ("repair", "escalated") for v in statuses.values()), "Under repair / escalated")
         + "</div>")
    view = ss.setdefault(f"{P}_iview", "list")
    flt = ss.setdefault(f"{P}_ifilter", "all")
    page_key = f"{P}_ipage"
    with box(f"{P}_icard", "card", "pad0", "mt"):
        with box(f"{P}_ihead", "cardh", "padh"):
            with box(f"{P}_ichips", "chips"):
                for key, label in I_FILTERS:
                    btn(label, f"{P}_if_{key}", "chipon" if flt == key else "chip",
                        on_click=lambda k=key: (ss.__setitem__(f"{P}_ifilter", k), ss.__setitem__(page_key, 0)))
            with box(f"{P}_ictl", "row", "spread", "full"):
                with box(f"{P}_iview_wrap", "row"), box(f"{P}_iview", "segs"):
                    for key, label, icon in (("list", "List", ":material/format_list_bulleted:"),
                                             ("map", "Live map", ":material/radar:")):
                        btn(label, f"{P}_iv_{key}", "segbon" if view == key else "segb", icon=icon,
                            on_click=_set, args=(f"{P}_iview", key))
                q = st.text_input("Search", placeholder="Search computers or software", label_visibility="collapsed",
                                  key=ui.sticky(f"{P}_i_q__search__"), on_change=_reset_page, args=(page_key,))
                labs = [0] + [l for l, _ in D.LABS]
                lab = st.selectbox("Laboratory", labs, format_func=lambda x: D.lab_name(x) if x else "All labs",
                                   key=ui.sticky(f"{P}_i_lab__sel__", labs), label_visibility="collapsed",
                                   on_change=_reset_page, args=(page_key,))
                how = sort_select(f"{P}_i_sort__selwide__", {k: f"Sort: {v}" for k, v in D.INVENTORY_SORTS.items()})
                ui.remember(f"{P}_i_q__search__")
                ui.remember(f"{P}_i_lab__sel__")
                btn("Add computer", f"{P}_i_add", "primarysm", icon=":material/add:", on_click=open_add)

        def match(c):
            st_ = statuses[(c["lab"], c["pc"])]
            if flt == "ok" and st_ != "ok" or flt == "attention" and st_ == "ok" or flt == "escalated" and st_ != "escalated":
                return False
            if lab and c["lab"] != lab:
                return False
            text = " ".join([c["tag"], c["name"], D.lab_name(c["lab"]), D.pc_name(c["pc"]), c.get("notes", "")]
                            + list(c["hardware"].values()) + [x["name"] for x in c["software"]]).lower()
            return not q or q.strip().lower() in text

        rows = D.sort_computers(s, [c for c in comps if match(c)], how)
        if view == "map":
            _inventory_map(s, rows, lab)
            return
        page = min(ss.get(page_key, 0), max(0, (len(rows) - 1) // PER))
        cols = "grid-template-columns:minmax(0,1.1fr) minmax(0,1fr) minmax(0,2fr) minmax(0,.8fr) 130px 136px;"
        html(f'<div class="tt-head" style="{cols}"><div>Computer</div><div>Location</div><div>Hardware</div>'
             f'<div class="tt-hide-sm">Software</div><div>Status</div><div>Last serviced</div></div>')
        if not rows:
            html('<div class="empty">No computers match.</div>')
        for c in rows[page * PER:(page + 1) * PER]:
            hw = c["hardware"]
            spec = " · ".join(v for k, v in hw.items() if k in ("Processor", "Memory (RAM)", "Storage")) or \
                " · ".join(list(hw.values())[:3])
            last = D.last_serviced(s, c)
            name = f'<div class="small">{h(c["name"])}</div>' if c["name"] != c["tag"] else ""
            hit(f'<div class="tt-row" style="{cols}"><div class="strong">{h(c["tag"])}{name}</div>'
                f'<div>{D.lab_name(c["lab"])}<div class="small">{D.pc_name(c["pc"])}</div></div>'
                f'<div class="small" style="color:var(--muted)">{h(spec)}<div class="small">{h(hw.get("Monitor", ""))}</div></div>'
                f'<div class="tt-hide-sm">{len(c["software"])} programs</div><div>{comp_badge(statuses[(c["lab"], c["pc"])])}</div>'
                f'<div>{D.when(last) if last else "<span class=small>&mdash;</span>"}</div></div>',
                f"{P}_i_{c['lab']}_{c['pc']}", open_pc, (c["lab"], c["pc"]))
        pager(page_key, page, len(rows))


def _inv_select(lab: int, pc: int) -> None:
    ss[f"{P}_inv_sel"] = (lab, pc)
    ss[f"{P}_pctab"] = "hardware"


def _inv_focus(lab: int) -> None:
    current = ss.get(f"{P}_inv_focus")
    ss[f"{P}_inv_focus"] = None if current == lab else lab


def _inventory_map(s: dict, rows: list[dict], lab_filter: int) -> None:
    focus = lab_filter or ss.get(f"{P}_inv_focus")
    sel = ss.get(f"{P}_inv_sel")
    if sel not in s["computers"]:
        sel = None
    with box(f"{P}_imap", "gmap"):
        with box(f"{P}_imap_l", "stack"):
            html('<div style="padding:0 22px"><div class="sub" style="font-size:12.5px;color:var(--faint)">Click a computer to see '
                 'its details. Pick a laboratory below to zoom in on it.</div></div>')
            portal.live_map(P, s, "inv", _inv_select, focus=focus, sel=sel)
            with box(f"{P}_imap_labs", "g2"):
                for lab, _ in D.LABS:
                    hit(lab_tile(s, lab, on=focus == lab), f"{P}_ilab_{lab}", _inv_focus, (lab,))
            html('<div style="height:22px"></div>')
        with box(f"{P}_imap_r", "card"):
            if sel:
                computer_details(s, s["computers"][sel], "inv", in_modal=False)
            else:
                html(f'<div class="empty">{ic("pc")}<div>Select a computer on the map to see its hardware, software '
                     f'and maintenance history.</div><div style="margin-top:8px">{len(rows)} computer(s) match your filters.</div></div>')


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
                    btn("Approve replacement", f"{P}_e_ap_{r['id']}", "primarysm", on_click=_decide, args=(r["id"], "approve"))
                    btn("Mark resolved", f"{P}_e_rs_{r['id']}", "successsm", on_click=_decide, args=(r["id"], "resolve"))
                    btn("Send back", f"{P}_e_bk_{r['id']}", "ghostsm", on_click=_decide, args=(r["id"], "back"))
                    btn("History", f"{P}_e_hi_{r['id']}", "ghostsm", on_click=open_modal, args=("report", r["id"]))
    done = list(reversed(s["decided"]))
    rows = "".join(f'<div class="row"><div class="ic ic-green">{ic("check")}</div><div class="main-t"><b>{h(d["r"]["id"])} · '
                   f'{D.lab_name(d["r"]["lab"])} {D.pc_name(d["r"]["pc"])}</b><span>{h(d["text"])} · {D.when(d["t"])}</span>'
                   f'</div>{badge(d["r"]["status"])}</div>' for d in done)
    html(f'<div class="card mt"><div class="card-h"><h3>Recently decided</h3></div><div class="rows">'
         + (rows or '<div class="empty" style="padding:20px">Decisions you make here will show up in this list.</div>') + "</div></div>")


def page_requests(s: dict) -> None:
    if not s["live"]:
        html(f'<div class="demo-note">{ic("info")}<span><b>Sample list.</b> Confirm and Cancel only change this list while '
             f'you are not signed in to the backend.</span></div>')
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


def modal_pc(s: dict, key: tuple) -> None:
    comp = s["computers"].get(tuple(key))
    if comp is None:
        return close_modal()
    with SHELL.window(wide=True):
        computer_details(s, comp, "modal", in_modal=True)


def modal_edit(s: dict, key: tuple) -> None:
    lab, pc = key
    comp = s["computers"].get((lab, pc))
    if comp is None:
        return close_modal()
    tab = ss.get(f"{P}_edtab", "details")
    with SHELL.window(wide=True):
        html(f'<h3>Edit {h(comp["tag"])}</h3><div class="m-sub">{D.lab_name(lab)} · {D.pc_name(pc)}. Every change is '
             f'added to this computer\'s maintenance history.</div>')
        with box(f"{P}_ed_tabs", "chips"):
            for k, label in (("details", "Details & hardware"), ("software", "Software"), ("log", "Log maintenance")):
                btn(label, f"{P}_edt_{k}", "chipon" if tab == k else "chip", on_click=_set, args=(f"{P}_edtab", k))
        html('<div style="height:16px"></div>')
        if tab == "software":
            if not comp["software"]:
                html('<div class="empty" style="padding:16px">No software recorded yet.</div>')
            for i, item in enumerate(comp["software"]):
                with box(f"{P}_sw_{i}", "trow"):
                    html(f'<div class="tt-row" style="grid-template-columns:1.5fr 1fr"><div class="strong">{h(item["name"])}</div>'
                         f'<div class="small">{h(item["version"] or "&mdash;")}</div></div>')
                    with box(f"{P}_sw_act_{i}", "row", "gap6"):
                        btn("Update", f"{P}_sw_up_{i}", "ghostsm", on_click=_start_sw_update, args=(item["name"], item["version"]))
                        btn("Remove", f"{P}_sw_rm_{i}", "dangersm", on_click=_sw_remove, args=(lab, pc, item["name"]))
                if ss.get(f"{P}_sw_upd") == item["name"]:
                    with box(f"{P}_sw_upd_row_{i}", "row"):
                        st.text_input("New version", key=_ek("sw new version"), placeholder="New version",
                                      label_visibility="collapsed")
                        btn("Save update", f"{P}_sw_upd_save_{i}", "primarysm", on_click=_sw_update, args=(lab, pc, item["name"]))
                        btn("Cancel", f"{P}_sw_upd_cancel_{i}", "ghostsm", on_click=ss.pop, args=(f"{P}_sw_upd", None))
            html('<div style="height:18px"></div><div class="adm-label">Install software</div>')
            with box(f"{P}_sw_add", "formgrid"):
                st.text_input("Program", key=_ek("sw name"), placeholder="Program, e.g. Java JDK", label_visibility="collapsed")
                st.text_input("Version", key=_ek("sw version"), placeholder="Version, e.g. 21", label_visibility="collapsed")
            with box(f"{P}_sw_add_btn", "mactions"):
                btn("Install", f"{P}_sw_install", "primary", icon=":material/add:", on_click=_install, args=(lab, pc))
                btn("Done", f"{P}_sw_done", "ghost", on_click=open_pc, args=(lab, pc))
        elif tab == "log":
            with box(f"{P}_log_kind", "field"):
                html('<div class="adm-label">Type of work</div>')
                if ss.get(_ek("log kind")) not in D.MAINT_KINDS:
                    ss[_ek("log kind")] = D.MAINT_KINDS[0]
                st.selectbox("Type of work", D.MAINT_KINDS, key=_ek("log kind"), label_visibility="collapsed")
            field("What was done", _ek("log text"), "For example: replaced the power supply (500 W)", kind="area")
            field("Done by", _ek("log by"))
            with box(f"{P}_log_btns", "mactions"):
                btn("Cancel", f"{P}_log_cancel", "ghost", on_click=open_pc, args=(lab, pc))
                btn("Save to history", f"{P}_log_save", "primary", on_click=_save_log, args=(lab, pc))
        else:
            with box(f"{P}_ed_grid", "formgrid"):
                field("Computer name", _ek("name"), comp["tag"])
                html('<div></div>')
                for label in _hw_labels(comp):
                    field(label, _ek("hw " + label))
            field("Notes", _ek("notes"), "Anything else worth knowing", kind="area")
            with box(f"{P}_ed_btns", "mactions"):
                btn("Cancel", f"{P}_ed_cancel", "ghost", on_click=open_pc, args=(lab, pc))
                btn("Save changes", f"{P}_ed_save", "primary", on_click=_save_details, args=(lab, pc))


def modal_add(s: dict) -> None:
    with SHELL.window(wide=True):
        html('<h3>Add computer</h3><div class="m-sub">Register a new computer in a laboratory. It is added to the inventory, '
             'the live map and its maintenance history starts today.</div>')
        labs = [l for l, _ in D.LABS]
        if ss.get(_ek("add lab")) not in labs:
            ss[_ek("add lab")] = labs[0]
        lab = ss[_ek("add lab")]
        with box(f"{P}_add_grid", "formgrid"):
            with box(f"{P}_add_lab", "field"):
                html('<div class="adm-label">Assigned laboratory</div>')
                st.selectbox("Assigned laboratory", labs, key=_ek("add lab"), label_visibility="collapsed",
                             format_func=lambda x: f"{D.lab_name(x)} · {D.WING[x]}", on_change=_add_lab_changed)
            field("Computer number (seat)", _ek("add pc"), "e.g. 40",
                   help_text=f"Next free number in {D.lab_name(lab)}: {D.next_free_pc(s, lab)}. "
                             f"Numbers 1–{D.MAP_SEATS} are drawn on the floor map.")
            field("Computer name", _ek("add name"), "Optional, e.g. Instructor PC")
            html('<div></div>')
            for label in D.HW_FIELDS:
                field(label, _ek("add hw " + label))
        with box(f"{P}_add_sw", "field"):
            html('<div class="adm-label">Installed software</div>')
            st.multiselect("Installed software", D.COMMON_SOFTWARE, key=_ek("add sw"), label_visibility="collapsed",
                           placeholder="Choose programs")
        field("Other software", _ek("add sw other"), "Comma separated, e.g. Unity 2022.3, Blender 4.1")
        field("Notes", _ek("add notes"), "Serial number, supplier, warranty...", kind="area")
        with box(f"{P}_add_btns", "mactions"):
            btn("Cancel", f"{P}_add_cancel", "ghost", on_click=close_modal)
            btn("Add computer", f"{P}_add_save", "primary", icon=":material/add:", on_click=_save_add)


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
    if kind == "report":
        modal_report(s, ref)
    elif kind == "pc":
        modal_pc(s, ref)
    elif kind == "edit":
        modal_edit(s, ref)
    elif kind == "add":
        modal_add(s)
    elif kind == "cancelreq":
        modal_cancel_request(ref)
    elif kind == "logout":
        SHELL.logout_window()


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
        if s.get("notice"):
            html(f'<div class="demo-note">{ic("info")}<span>{h(s["notice"])}</span></div>')
        if page == "reports":
            page_reports(s)
        elif page == "inventory":
            page_inventory(s)
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
