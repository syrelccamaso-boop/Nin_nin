"""
frontend/inventory.py - Centrum Laboratory | the computer inventory (Admin + Technician)

One inventory screen shared by the admin and technician dashboards, so both
get exactly the same tools:

    - full inventory list (or live floor-map view) with every computer's details
    - search, laboratory filter, status chips, Sort by, Export CSV
    - computer details: hardware, software, maintenance history
    - Add computer (validated form)
    - Edit computer: details & hardware (incl. record status), software
      install / update / remove, log maintenance

Every change is written to the shared lab store (frontend/lab_store.py), so it
is visible system-wide straight away (admin, technicians and the teachers'
floor map), is added to the computer's maintenance history and creates an
"inventory update" notification for the other role.

    inv = inventory.Inventory(SHELL, store, me, "Technician")
    inv.page(s)                         # the Inventory page
    inv.open_pc(lab, pc)                # open a computer's details pop-up
    inv.render_modal(s, kind, ref)      # True if it drew one of its pop-ups
"""

from __future__ import annotations

import csv
import io
import re

import streamlit as st

from frontend import lab_data as D
from frontend import lab_store
from frontend import portal
from frontend import ui
from frontend.portal import PER, comp_badge, ic, lab_tile, pager, sort_select, stat

ss = st.session_state
html, btn, hit, box, h = ui.html, ui.btn, ui.hit, ui.box, ui.h
_set, field = portal._set, portal.field

I_FILTERS = [("all", "All computers"), ("ok", "Working"), ("attention", "Needs attention"), ("inactive", "Inactive")]


class Inventory:
    def __init__(self, shell, store_fn, me_fn, role: str):
        self.shell = shell
        self.p = shell.p
        self.store = store_fn
        self.me = me_fn
        self.role = role

    # ------------------------------------------------------------------ helpers
    def _ek(self, name: str) -> str:
        return f"{self.p}_ed_{re.sub(r'[^a-z0-9]+', '_', name.lower())}"

    def toast(self, msg: str, ok: bool = True) -> None:
        self.shell.toast(msg, ok)

    def _changed(self, comp: dict, text: str, kind: str = "inventory") -> None:
        """Save the shared store and tell the other role about it."""
        lab_store.save()
        lab_store.add_event(kind, f"{comp['tag']} · {text}", f"{D.lab_name(comp['lab'])} {D.pc_name(comp['pc'])} · by {self.me()}",
                            roles=("admin", "technician"), actor=self.me(), ref=("pc", comp["lab"], comp["pc"]))

    def _comp(self, lab: int, pc: int) -> dict | None:
        return self.store()["computers"].get((lab, pc))

    @staticmethod
    def _hw_labels(comp: dict) -> list[str]:
        return D.HW_FIELDS + [k for k in comp["hardware"] if k not in D.HW_FIELDS]

    # ------------------------------------------------------------------ details
    def open_pc(self, lab: int, pc: int) -> None:
        if (lab, pc) not in self.store()["computers"]:
            return self.toast(f"{D.asset_tag(lab, pc)} isn't in the inventory.", False)
        ss[f"{self.p}_pctab"] = "hardware"
        self.shell.open_modal("pc", (lab, pc))

    def computer_details(self, s: dict, comp: dict, ctx: str, in_modal: bool) -> None:
        p = self.p
        lab, pc = comp["lab"], comp["pc"]
        status = D.pc_status(s, lab, pc)
        name = f" · {h(comp['name'])}" if comp["name"] != comp["tag"] else ""
        model = " ".join(x for x in (comp.get("brand"), comp.get("model")) if x)
        html(f'<div class="pc-panel"><div class="ph"><div class="ic {portal.tone(status)}">{ic("pc")}</div><div style="flex:1;min-width:0">'
             f'<h3 style="font-size:17px">{h(comp["tag"])}{name}</h3><div class="sub" style="font-size:12.5px;color:var(--faint)">'
             f'{D.lab_name(lab)} · {D.pc_name(pc)} · {D.WING.get(lab, "")}' + (f" · {h(model)}" if model else "")
             + f'</div></div>{comp_badge(status)}</div></div>')
        r = D.pc_report(s, lab, pc)
        if r:
            with box(f"{p}_pcrep_{ctx}", "row", "gap14"):
                html(f'<div class="demo-note" style="margin:0 0 14px">{ic("alert")}<span><b>{h(r["id"])}</b> · '
                     f'{h(r["issue"])} · {D.when(r["created"])}</span></div>')
                btn("View report", f"{p}_pcrep_btn_{ctx}", "ghostsm", on_click=self.shell.open_modal, args=("report", r["id"]))

        history = D.maintenance_history(s, comp)
        tab_key = f"{p}_pctab"
        tab = ss.get(tab_key, "hardware")
        with box(f"{p}_pctabs_{ctx}", "chips"):
            for key, label in (("hardware", "Details & hardware"), ("software", f"Software · {len(comp['software'])}"),
                               ("history", f"Maintenance history · {len(history)}")):
                btn(label, f"{p}_pct_{ctx}_{key}", "chipon" if tab == key else "chip", on_click=_set, args=(tab_key, key))
        html('<div style="height:14px"></div>')
        if tab == "software":
            rows = "".join(f'<dt>{h(x["name"])}</dt><dd>{h(x["version"] or "—")}</dd>' for x in comp["software"])
            html(f'<dl class="kv">{rows}</dl>' if rows else '<div class="empty">No software recorded.</div>')
        elif tab == "history":
            with box(f"{p}_hist_sort_{ctx}", "row"):
                html('<span class="muted" style="font-size:13px">Sort by</span>')
                how = sort_select(f"{p}_hist_sort__sel__", D.HISTORY_SORTS)
            if how == "old":
                history = sorted(history, key=lambda e: e["t"])
            elif how == "kind":
                history = sorted(history, key=lambda e: (e["kind"], -e["t"].timestamp()))
            html('<div style="height:12px"></div>')
            items = "".join(f'<li><b>{h(e["kind"])}</b> — {h(e["text"])}<span>{D.date_time(e["t"])} · {h(e["by"])}</span></li>'
                            for e in history)
            html(f'<ul class="timeline">{items}</ul>' if items else '<div class="empty">No maintenance recorded yet.</div>')
        else:
            rows = (f'<dt>Asset ID</dt><dd>{h(comp["tag"])}</dd><dt>Laboratory</dt><dd>{D.lab_name(lab)} '
                    f'<small>({h(D.WING.get(lab, ""))})</small></dd><dt>Record status</dt><dd>{h(comp.get("status", "Working"))}</dd>')
            if model:
                rows += f'<dt>Brand / model</dt><dd>{h(model)}</dd>'
            if comp.get("serial"):
                rows += f'<dt>Serial number</dt><dd>{h(comp["serial"])}</dd>'
            rows += "".join(f'<dt>{h(k)}</dt><dd>{h(v)}</dd>' for k, v in comp["hardware"].items())
            rows += f'<dt>Date added</dt><dd>{D.date_only(comp.get("added"))}</dd>'
            if comp.get("notes"):
                rows += f'<dt>Notes</dt><dd>{h(comp["notes"])}</dd>'
            last = D.last_serviced(s, comp)
            rows += f'<dt>Last serviced</dt><dd>{D.when(last) if last else "—"}</dd>'
            html(f'<dl class="kv">{rows}</dl>')
        with box(f"{p}_pcact_{ctx}", "mactions"):
            btn("Log maintenance", f"{p}_pc_log_{ctx}", "ghost", on_click=self.open_edit, args=(lab, pc, "log"))
            btn("Edit computer", f"{p}_pc_edit_{ctx}", "primary", icon=":material/edit:", on_click=self.open_edit,
                args=(lab, pc, "details"))
            if in_modal:
                btn("Close", f"{p}_pc_close_{ctx}", "ghost", on_click=self.shell.close_modal)

    # ------------------------------------------------------------------ edit (callbacks)
    def open_edit(self, lab: int, pc: int, tab: str = "details") -> None:
        comp = self._comp(lab, pc)
        if comp is None:
            return self.toast("That computer is no longer in the inventory.", False)
        ek = self._ek
        ss[ek("name")] = comp["name"]
        ss[ek("notes")] = comp.get("notes", "")
        ss[ek("brand")] = comp.get("brand", "")
        ss[ek("model")] = comp.get("model", "")
        ss[ek("serial")] = comp.get("serial", "")
        ss[ek("status")] = comp.get("status", "Working")
        for label in self._hw_labels(comp):
            ss[ek("hw " + label)] = comp["hardware"].get(label, "")
        for k in ("sw name", "sw version", "log text"):
            ss[ek(k)] = ""
        ss[ek("log by")] = self.me()
        ss.pop(f"{self.p}_sw_upd", None)
        ss[f"{self.p}_edtab"] = tab
        self.shell.open_modal("edit", (lab, pc))

    def _save_details(self, lab: int, pc: int) -> None:
        s, ek = self.store(), self._ek
        comp = self._comp(lab, pc)
        if comp is None:
            return self.toast("That computer is no longer in the inventory.", False)
        hw = {label: ss.get(ek("hw " + label), "") or "" for label in self._hw_labels(comp)}
        with lab_store.lock():
            ok, msg = D.update_details(s, comp, name=ss.get(ek("name"), "") or "", notes=ss.get(ek("notes"), "") or "",
                                       hardware=hw, by=self.me(), brand=ss.get(ek("brand"), "") or "",
                                       model=ss.get(ek("model"), "") or "", serial=ss.get(ek("serial"), "") or "",
                                       status=ss.get(ek("status")))
            if ok:
                self._changed(comp, "details updated")
        self.toast(msg, ok)
        if ok:
            self.shell.open_modal("pc", (lab, pc))
            ss[f"{self.p}_pctab"] = "history"

    def _install(self, lab: int, pc: int) -> None:
        comp, ek = self._comp(lab, pc), self._ek
        if comp is None:
            return
        name = ss.get(ek("sw name"), "") or ""
        with lab_store.lock():
            ok, msg = D.install_software(comp, name, ss.get(ek("sw version"), "") or "", self.me())
            if ok:
                self._changed(comp, f"software: {name.strip()}", "maintenance")
        self.toast(msg, ok)
        if ok:
            ss[ek("sw name")] = ""
            ss[ek("sw version")] = ""

    def _start_sw_update(self, name: str, version: str) -> None:
        ss[f"{self.p}_sw_upd"] = name
        ss[self._ek("sw new version")] = version

    def _cancel_sw_update(self) -> None:
        ss.pop(f"{self.p}_sw_upd", None)

    def _sw_update(self, lab: int, pc: int, name: str) -> None:
        comp = self._comp(lab, pc)
        if comp is None:
            return
        with lab_store.lock():
            ok, msg = D.update_software(comp, name, ss.get(self._ek("sw new version"), "") or "", self.me())
            if ok:
                self._changed(comp, f"{name} updated", "maintenance")
        self.toast(msg, ok)
        if ok:
            ss.pop(f"{self.p}_sw_upd", None)

    def _sw_remove(self, lab: int, pc: int, name: str) -> None:
        comp = self._comp(lab, pc)
        if comp is not None:
            with lab_store.lock():
                ok, msg = D.remove_software(comp, name, self.me())
                if ok:
                    self._changed(comp, f"{name} removed", "maintenance")
            self.toast(msg, ok)
        ss[f"{self.p}_edtab"] = "software"
        self.shell.open_modal("edit", (lab, pc))

    def _ask_sw_remove(self, lab: int, pc: int, name: str) -> None:
        self.shell.confirm(f"Remove {name}?", f"It is taken off {D.asset_tag(lab, pc)} and the removal is added to the "
                           f"computer's maintenance history.", "Remove", self._sw_remove, (lab, pc, name))

    def _save_log(self, lab: int, pc: int) -> None:
        comp, ek = self._comp(lab, pc), self._ek
        if comp is None:
            return
        kind = ss.get(ek("log kind")) or "Repair"
        with lab_store.lock():
            ok, msg = D.log_maintenance(comp, kind, ss.get(ek("log text"), "") or "", ss.get(ek("log by"), "") or self.me())
            if ok:
                self._changed(comp, f"maintenance logged ({kind.lower()})", "maintenance")
        self.toast(msg, ok)
        if ok:
            self.shell.open_modal("pc", (lab, pc))
            ss[f"{self.p}_pctab"] = "history"

    # ------------------------------------------------------------------ add (callbacks)
    def open_add(self) -> None:
        s, ek = self.store(), self._ek
        focus = ss.get(f"{self.p}_i_lab__sel__") or 1
        lab = focus if focus in D.WING else 1
        ss[ek("add lab")] = lab
        ss[ek("add pc")] = str(D.next_free_pc(s, lab))
        for k in ("add name", "add notes", "add brand", "add model", "add serial", "add sw other"):
            ss[ek(k)] = ""
        ss[ek("add status")] = "Working"
        for label, value in zip(D.HW_FIELDS, D.SPECS[lab]):
            ss[ek("add hw " + label)] = value
        ss[ek("add sw")] = [n for n, _ in D.DEFAULT_SOFTWARE if n in D.COMMON_SOFTWARE]
        self.shell.open_modal("add")

    def _add_lab_changed(self) -> None:
        s, ek = self.store(), self._ek
        lab = ss.get(ek("add lab")) or 1
        ss[ek("add pc")] = str(D.next_free_pc(s, lab))
        for label, value in zip(D.HW_FIELDS, D.SPECS.get(lab, D.SPECS[1])):
            ss[ek("add hw " + label)] = value

    def _save_add(self) -> None:
        s, ek = self.store(), self._ek
        lab = int(ss.get(ek("add lab")) or 1)
        raw = str(ss.get(ek("add pc")) or "").strip()
        if not raw.isdigit() or not 1 <= int(raw) <= 999:
            return self.toast("Enter the computer's seat number in the laboratory (1–999).", False)
        pc = int(raw)
        hw = {label: ss.get(ek("add hw " + label), "") or "" for label in D.HW_FIELDS}
        defaults = dict(D.DEFAULT_SOFTWARE)
        software = [{"name": n, "version": defaults.get(n, "")} for n in ss.get(ek("add sw")) or []]
        for item in (ss.get(ek("add sw other")) or "").split(","):
            item = item.strip()
            if item:
                parts = item.rsplit(" ", 1)
                ver = parts[1] if len(parts) == 2 and re.match(r"^v?[\d.]+$", parts[1]) else ""
                name = parts[0] if ver else item
                if not any(x["name"].lower() == name.lower() for x in software):
                    software.append({"name": name, "version": ver})
        with lab_store.lock():
            ok, msg = D.add_computer(s, lab=lab, pc=pc, name=ss.get(ek("add name"), "") or "", hardware=hw,
                                     software=software, notes=ss.get(ek("add notes"), "") or "", by=self.me(),
                                     brand=ss.get(ek("add brand"), "") or "", model=ss.get(ek("add model"), "") or "",
                                     serial=ss.get(ek("add serial"), "") or "", status=ss.get(ek("add status")) or "Working")
            if ok:
                self._changed(s["computers"][(lab, pc)], "added to the inventory")
        self.toast(msg, ok)
        if ok:
            ss[f"{self.p}_pctab"] = "hardware"
            ss[f"{self.p}_inv_sel"] = (lab, pc)
            self.shell.open_modal("pc", (lab, pc))

    # ------------------------------------------------------------------ the page
    def _reset_page(self) -> None:
        ss[f"{self.p}_ipage"] = 0

    def _clear_filters(self) -> None:
        p = self.p
        for k in (f"{p}_i_q__search__", f"_keep_{p}_i_q__search__"):
            ss[k] = ""
        for k in (f"{p}_i_lab__sel__", f"_keep_{p}_i_lab__sel__"):
            ss[k] = 0
        ss[f"{p}_ifilter"] = "all"
        ss[f"{p}_ipage"] = 0

    @staticmethod
    def _csv(s: dict, rows: list[dict]) -> str:
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["Asset ID", "Name", "Laboratory", "Seat", "Brand", "Model", "Serial number", "Record status",
                    "Live status"] + D.HW_FIELDS + ["Software", "Date added", "Notes"])
        for c in rows:
            st_ = D.computer_status_label(D.pc_status(s, c["lab"], c["pc"]))[0]
            w.writerow([c["tag"], c["name"], D.lab_name(c["lab"]), c["pc"], c.get("brand", ""), c.get("model", ""),
                        c.get("serial", ""), c.get("status", ""), st_] + [c["hardware"].get(f, "") for f in D.HW_FIELDS]
                       + ["; ".join(f'{x["name"]} {x["version"]}'.strip() for x in c["software"]),
                          D.date_only(c.get("added")), c.get("notes", "")])
        return buf.getvalue()

    def page(self, s: dict) -> None:
        p = self.p
        comps = list(s["computers"].values())
        statuses = {(c["lab"], c["pc"]): D.pc_status(s, c["lab"], c["pc"]) for c in comps}
        attention = ("reported", "repair", "escalated", "maint")
        html('<div class="grid g4">'
             + stat("pc", "ic-blue", len(comps), f"Computers in {len(D.LABS)} laboratories")
             + stat("check", "ic-green", sum(v == "ok" for v in statuses.values()), "Working")
             + stat("alert", "ic-amber", sum(v in attention for v in statuses.values()), "Need attention")
             + stat("wrench", "ic-violet", sum(v == "inactive" for v in statuses.values()), "Inactive")
             + "</div>")
        view = ss.setdefault(f"{p}_iview", "list")
        flt = ss.setdefault(f"{p}_ifilter", "all")
        page_key = f"{p}_ipage"

        def match_status(st_, f):
            return f == "all" or (f == "ok" and st_ == "ok") or (f == "attention" and st_ in attention) or \
                (f == "inactive" and st_ == "inactive")

        with box(f"{p}_icard", "card", "pad0", "mt"):
            with box(f"{p}_ihead", "cardh", "padh"):
                with box(f"{p}_ichips", "chips"):
                    for key, label in I_FILTERS:
                        n = sum(match_status(v, key) for v in statuses.values())
                        btn(f"{label} · {n}", f"{p}_if_{key}", "chipon" if flt == key else "chip",
                            on_click=lambda k=key: (ss.__setitem__(f"{p}_ifilter", k), ss.__setitem__(page_key, 0)))
                with box(f"{p}_ictl", "row", "spread", "full"):
                    with box(f"{p}_iview_wrap", "row"), box(f"{p}_iview", "segs"):
                        for key, label, icon in (("list", "List", ":material/format_list_bulleted:"),
                                                 ("map", "Live map", ":material/radar:")):
                            btn(label, f"{p}_iv_{key}", "segbon" if view == key else "segb", icon=icon,
                                on_click=_set, args=(f"{p}_iview", key))
                    q = st.text_input("Search", placeholder="Search asset ID, CPU, serial, software...",
                                      label_visibility="collapsed", key=ui.sticky(f"{p}_i_q__search__"),
                                      on_change=self._reset_page)
                    labs = [0] + [l for l, _ in D.LABS]
                    lab = st.selectbox("Laboratory", labs, format_func=lambda x: D.lab_name(x) if x else "All labs",
                                       key=ui.sticky(f"{p}_i_lab__sel__", labs), label_visibility="collapsed",
                                       on_change=self._reset_page)
                    how = sort_select(f"{p}_i_sort__selwide__", {k: f"Sort: {v}" for k, v in D.INVENTORY_SORTS.items()})
                    ui.remember(f"{p}_i_q__search__")
                    ui.remember(f"{p}_i_lab__sel__")
                    btn("Add computer", f"{p}_i_add", "primarysm", icon=":material/add:", on_click=self.open_add)

            words = [w for w in (q or "").strip().lower().split() if w]

            def match(c):
                if not match_status(statuses[(c["lab"], c["pc"])], flt):
                    return False
                if lab and c["lab"] != lab:
                    return False
                text = D.search_text(c)
                return all(w in text for w in words)

            rows = D.sort_computers(s, [c for c in comps if match(c)], how)
            filtered = bool(words or lab or flt != "all")
            with box(f"{p}_ibar", "row", "spread", "padh"):
                html(f'<span class="muted" style="font-size:13px">{len(rows)} of {len(comps)} computers'
                     + (" match your filters" if filtered else "") + "</span>")
                with box(f"{p}_ibar_btns", "row"):
                    if filtered:
                        btn("Clear filters", f"{p}_i_clear", "ghostsm", icon=":material/filter_alt_off:",
                            on_click=self._clear_filters)
                    st.download_button("Export CSV", data=self._csv(s, rows), file_name="centrum-inventory.csv",
                                       mime="text/csv", key=f"{p}_i_csv__ghostsm__", disabled=not rows)
            html('<div style="height:12px"></div>')
            if view == "map":
                self._inventory_map(s, rows, lab)
                return
            page = min(ss.get(page_key, 0), max(0, (len(rows) - 1) // PER))
            cols = ("grid-template-columns:minmax(0,1.05fr) minmax(0,.9fr) minmax(0,2fr) minmax(0,1.1fr) 140px "
                    "minmax(0,.9fr);")
            html(f'<div class="tt-head" style="{cols}"><div>Asset ID</div><div>Location</div><div>CPU · RAM · Storage</div>'
                 f'<div class="tt-hide-sm">Operating system</div><div>Status</div><div>Date added</div></div>')
            if not rows:
                html(f'<div class="empty">{ic("search")}<div>No computers match.</div>'
                     + ('<div style="font-size:12.5px;margin-top:4px">Try clearing the filters.</div>' if filtered else "")
                     + "</div>")
            for c in rows[page * PER:(page + 1) * PER]:
                hw = c["hardware"]
                sub = c["name"] if c["name"] != c["tag"] else " ".join(x for x in (c.get("brand"), c.get("model")) if x)
                hit(f'<div class="tt-row" style="{cols}"><div class="strong">{h(c["tag"])}<div class="small">{h(sub)}</div></div>'
                    f'<div>{D.lab_name(c["lab"])}<div class="small">{D.pc_name(c["pc"])}</div></div>'
                    f'<div class="small" style="color:var(--muted)">{h(D.spec_line(c))}<div class="small">'
                    f'{h(hw.get("Graphics", ""))}</div></div>'
                    f'<div class="tt-hide-sm small" style="color:var(--muted)">{h(hw.get("Operating system", "—"))}</div>'
                    f'<div>{comp_badge(statuses[(c["lab"], c["pc"])])}</div>'
                    f'<div class="small" style="color:var(--muted)">{D.date_only(c.get("added"))}</div></div>',
                    f"{p}_i_{c['lab']}_{c['pc']}", self.open_pc, (c["lab"], c["pc"]))
            pager(page_key, page, len(rows))

    def _inv_select(self, lab: int, pc: int) -> None:
        ss[f"{self.p}_inv_sel"] = (lab, pc)
        ss[f"{self.p}_pctab"] = "hardware"

    def _inv_focus(self, lab: int) -> None:
        current = ss.get(f"{self.p}_inv_focus")
        ss[f"{self.p}_inv_focus"] = None if current == lab else lab

    def _inventory_map(self, s: dict, rows: list[dict], lab_filter: int) -> None:
        p = self.p
        focus = lab_filter or ss.get(f"{p}_inv_focus")
        sel = ss.get(f"{p}_inv_sel")
        sel = tuple(sel) if sel else None
        if sel not in s["computers"]:
            sel = None
        with box(f"{p}_imap", "gmap"):
            with box(f"{p}_imap_l", "stack"):
                html('<div style="padding:0 22px"><div class="sub" style="font-size:12.5px;color:var(--faint)">Click a computer '
                     'to see its details. Pick a laboratory below to zoom in on it.</div></div>')
                portal.live_map(p, s, "inv", self._inv_select, focus=focus, sel=sel)
                with box(f"{p}_imap_labs", "g2"):
                    for lab, _ in D.LABS:
                        hit(lab_tile(s, lab, on=focus == lab), f"{p}_ilab_{lab}", self._inv_focus, (lab,))
                html('<div style="height:22px"></div>')
            with box(f"{p}_imap_r", "card"):
                if sel:
                    self.computer_details(s, s["computers"][sel], "inv", in_modal=False)
                else:
                    html(f'<div class="empty">{ic("pc")}<div>Select a computer on the map to see its hardware, software '
                         f'and maintenance history.</div><div style="margin-top:8px">{len(rows)} computer(s) match your '
                         f'filters.</div></div>')

    # ------------------------------------------------------------------ pop-ups
    def modal_pc(self, s: dict, key) -> None:
        comp = s["computers"].get(tuple(key))
        if comp is None:
            return self.shell.close_modal()
        with self.shell.window(wide=True):
            self.computer_details(s, comp, "modal", in_modal=True)

    def modal_edit(self, s: dict, key) -> None:
        p, ek = self.p, self._ek
        lab, pc = key
        comp = s["computers"].get((lab, pc))
        if comp is None:
            return self.shell.close_modal()
        tab = ss.get(f"{p}_edtab", "details")
        with self.shell.window(wide=True):
            html(f'<h3>Edit {h(comp["tag"])}</h3><div class="m-sub">{D.lab_name(lab)} · {D.pc_name(pc)}. Every change is '
                 f'saved for everyone and added to this computer\'s maintenance history.</div>')
            with box(f"{p}_ed_tabs", "chips"):
                for k, label in (("details", "Details & hardware"), ("software", "Software"), ("log", "Log maintenance")):
                    btn(label, f"{p}_edt_{k}", "chipon" if tab == k else "chip", on_click=_set, args=(f"{p}_edtab", k))
            html('<div style="height:16px"></div>')
            if tab == "software":
                if not comp["software"]:
                    html('<div class="empty" style="padding:16px">No software recorded yet.</div>')
                for i, item in enumerate(comp["software"]):
                    with box(f"{p}_sw_{i}", "trow"):
                        html(f'<div class="tt-row" style="grid-template-columns:1.5fr 1fr"><div class="strong">{h(item["name"])}</div>'
                             f'<div class="small">{h(item["version"] or "—")}</div></div>')
                        with box(f"{p}_sw_act_{i}", "row", "gap6"):
                            btn("Update", f"{p}_sw_up_{i}", "ghostsm", on_click=self._start_sw_update,
                                args=(item["name"], item["version"]))
                            btn("Remove", f"{p}_sw_rm_{i}", "dangersm", on_click=self._ask_sw_remove,
                                args=(lab, pc, item["name"]))
                    if ss.get(f"{p}_sw_upd") == item["name"]:
                        with box(f"{p}_sw_upd_row_{i}", "row"):
                            st.text_input("New version", key=ek("sw new version"), placeholder="New version",
                                          label_visibility="collapsed")
                            btn("Save update", f"{p}_sw_upd_save_{i}", "primarysm", on_click=self._sw_update,
                                args=(lab, pc, item["name"]))
                            btn("Cancel", f"{p}_sw_upd_cancel_{i}", "ghostsm", on_click=self._cancel_sw_update)
                html('<div style="height:18px"></div><div class="adm-label">Install software</div>')
                with box(f"{p}_sw_add", "formgrid"):
                    st.text_input("Program", key=ek("sw name"), placeholder="Program, e.g. Java JDK",
                                  label_visibility="collapsed")
                    st.text_input("Version", key=ek("sw version"), placeholder="Version, e.g. 21", label_visibility="collapsed")
                with box(f"{p}_sw_add_btn", "mactions"):
                    btn("Done", f"{p}_sw_done", "ghost", on_click=self.open_pc, args=(lab, pc))
                    btn("Install", f"{p}_sw_install", "primary", icon=":material/add:", on_click=self._install, args=(lab, pc))
            elif tab == "log":
                field("Type of work", ek("log kind"), kind="select", options=D.MAINT_KINDS, required=True)
                field("What was done", ek("log text"), "For example: replaced the power supply (500 W)", kind="area",
                      required=True, max_chars=500)
                field("Done by", ek("log by"))
                with box(f"{p}_log_btns", "mactions"):
                    btn("Cancel", f"{p}_log_cancel", "ghost", on_click=self.open_pc, args=(lab, pc))
                    btn("Save to history", f"{p}_log_save", "primary", on_click=self._save_log, args=(lab, pc))
            else:
                html('<div class="form-note">Fields marked <span class="req">*</span> are required.</div>')
                with box(f"{p}_ed_grid", "formgrid"):
                    field("Computer name", ek("name"), comp["tag"])
                    field("Record status", ek("status"), kind="select", options=D.RECORD_STATUSES)
                    field("Brand", ek("brand"), "e.g. Dell")
                    field("Model", ek("model"), "e.g. OptiPlex 3080")
                    field("Serial number", ek("serial"), "Unique serial / service tag")
                    html('<div></div>')
                    for label in self._hw_labels(comp):
                        field(label, ek("hw " + label), required=label in D.REQUIRED_HW)
                field("Notes", ek("notes"), "Anything else worth knowing", kind="area", max_chars=500)
                with box(f"{p}_ed_btns", "mactions"):
                    btn("Cancel", f"{p}_ed_cancel", "ghost", on_click=self.open_pc, args=(lab, pc))
                    btn("Save changes", f"{p}_ed_save", "primary", icon=":material/save:", on_click=self._save_details,
                        args=(lab, pc))

    def modal_add(self, s: dict) -> None:
        p, ek = self.p, self._ek
        with self.shell.window(wide=True):
            html('<h3>Add computer</h3><div class="m-sub">Register a new computer in a laboratory. It is added to the inventory '
                 'and the live map for everyone, and its maintenance history starts today.</div>'
                 '<div class="form-note">Fields marked <span class="req">*</span> are required.</div>')
            labs = [l for l, _ in D.LABS]
            if ss.get(ek("add lab")) not in labs:
                ss[ek("add lab")] = labs[0]
            lab = ss[ek("add lab")]
            with box(f"{p}_add_grid", "formgrid"):
                with box(f"{p}_add_lab", "field"):
                    html('<div class="adm-label">Assigned laboratory <span class="req">*</span></div>')
                    st.selectbox("Assigned laboratory", labs, key=ek("add lab"), label_visibility="collapsed",
                                 format_func=lambda x: f"{D.lab_name(x)} · {D.WING[x]}", on_change=self._add_lab_changed)
                field("Seat number", ek("add pc"), "e.g. 41", required=True, max_chars=3,
                      help_text=f"Asset ID will be {D.asset_tag(lab, 0)[:-2]}NN. Next free seat in {D.lab_name(lab)}: "
                                f"{D.next_free_pc(s, lab)}. Seats 1–{D.MAP_SEATS} are drawn on the floor map.")
                field("Computer name", ek("add name"), "Optional, e.g. Instructor PC")
                field("Record status", ek("add status"), kind="select", options=D.RECORD_STATUSES, required=True)
                field("Brand", ek("add brand"), "e.g. Dell")
                field("Model", ek("add model"), "e.g. OptiPlex 3080")
                field("Serial number", ek("add serial"), "Unique serial / service tag")
                html('<div></div>')
                for label in D.HW_FIELDS:
                    field(label, ek("add hw " + label), required=label in D.REQUIRED_HW)
            with box(f"{p}_add_sw", "field"):
                html('<div class="adm-label">Installed software</div>')
                st.multiselect("Installed software", D.COMMON_SOFTWARE, key=ek("add sw"), label_visibility="collapsed",
                               placeholder="Choose programs")
            field("Other software", ek("add sw other"), "Comma separated, e.g. Unity 2022.3, Blender 4.1")
            field("Notes", ek("add notes"), "Supplier, warranty, property number...", kind="area", max_chars=500)
            with box(f"{p}_add_btns", "mactions"):
                btn("Cancel", f"{p}_add_cancel", "ghost", on_click=self.shell.close_modal)
                btn("Add computer", f"{p}_add_save", "primary", icon=":material/add:", on_click=self._save_add)

    def render_modal(self, s: dict, kind: str, ref) -> bool:
        if kind == "pc":
            self.modal_pc(s, ref)
        elif kind == "edit":
            self.modal_edit(s, ref)
        elif kind == "add":
            self.modal_add(s)
        else:
            return False
        return True


def event_notifications(role: str, me: str, open_pc, open_report) -> list[dict]:
    """Shared-store events (inventory updates, reports...) -> notification items for the bell."""
    icons = {"inventory": ("box", "ic-blue"), "maintenance": ("wrench", "ic-green"), "report": ("alert", "ic-amber"),
             "status": ("check", "ic-green"), "escalation": ("up", "ic-violet")}
    out = []
    for e in lab_store.events_for(role, me):
        icon, tone_cls = icons.get(e.get("kind"), ("bell", "ic-blue"))
        ref = e.get("ref") or []
        cb, args = None, ()
        if ref and ref[0] == "pc" and open_pc and len(ref) == 3:
            cb, args = open_pc, (int(ref[1]), int(ref[2]))
        elif ref and ref[0] == "report" and open_report and len(ref) == 2:
            cb, args = open_report, (ref[1],)
        out.append({"id": "ev:" + e["id"], "icon": icon, "tone": tone_cls, "title": e["title"], "sub": e.get("sub", ""),
                    "t": e["t"], "cb": cb, "args": args, "roles": e.get("roles")})
    return out
