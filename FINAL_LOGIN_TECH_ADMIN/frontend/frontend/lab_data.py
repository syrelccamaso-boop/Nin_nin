"""
frontend/lab_data.py - Centrum Laboratory | data behind the dashboards

Everything the admin, technician and teacher screens show and change lives in
one "store" dict per dashboard, kept in st.session_state:

    store = {
        "reports":   [report, ...],          # repair reports from teachers
        "computers": {(lab, pc): computer},  # the computer inventory (computers only)
        "requests":  [request, ...],         # account requests
        "decided":   [decision, ...],        # escalation decisions made here
        "live": bool, "notice": str,
    }

Signed-in admins and technicians start from the backend's data
(backend_client.get_admin_data / get_technician_data). The backend has no
endpoints yet for adding/editing computers, maintenance logs, escalation
decisions or teacher reports, so those changes are kept in this browser
session only. Technician report updates, account requests, contact numbers
and passwords go to the backend as before.
"""

from __future__ import annotations

import random
import re
from datetime import datetime, timedelta

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
LABS = [(1, "Southeast wing"), (2, "Southwest wing"), (3, "Northeast wing"), (4, "Northwest wing")]
WING = dict(LABS)
MAP_SEATS = 39  # computers drawn per laboratory on the floor map

ISSUES = ["No display", "Won't turn on", "No internet", "Keyboard / mouse", "Slow / freezing", "Software problem", "Other"]
STATUS = {
    "reported": ("Reported", "b-reported"),
    "repair": ("Under repair", "b-repair"),
    "escalated": ("Escalated", "b-escalated"),
    "fixed": ("Fixed", "b-fixed"),
}
OPEN = ("reported", "repair", "escalated")

TEACHERS = ["Maria Santos", "Ramon Aquino", "Liza Ramos", "Carlo Mendoza", "Grace Villanueva", "Paolo Reyes"]
TECHS = ["Jherome Domingo", "Mark Bautista"]
SAMPLE_TEACHER = "Alwyna Lopez"

# Hardware fields of a computer (label shown in the forms and the details).
HW_FIELDS = ["Processor", "Memory (RAM)", "Storage", "Graphics", "Monitor", "Keyboard & mouse", "Operating system"]
SPECS = {
    1: ["Intel Core i5-10400", "8 GB DDR4", "256 GB SSD", "Intel UHD 630", '21.5" LED', "USB keyboard & mouse", "Windows 11 Pro"],
    2: ["AMD Ryzen 5 3600", "16 GB DDR4", "512 GB SSD", "GeForce GT 1030", '21.5" LED', "USB keyboard & mouse", "Windows 11 Pro"],
    3: ["Intel Core i3-10100", "8 GB DDR4", "1 TB HDD", "Intel UHD 630", '21.5" LED', "USB keyboard & mouse", "Windows 10 Pro"],
    4: ["Intel Core i5-12400", "16 GB DDR4", "512 GB SSD", "Intel UHD 730", '23.8" IPS', "USB keyboard & mouse", "Windows 11 Pro"],
}
DEFAULT_SOFTWARE = [("Microsoft Office", "2021"), ("Google Chrome", "128"), ("Visual Studio Code", "1.92"),
                    ("Python", "3.11"), ("Windows Defender", "Active")]
COMMON_SOFTWARE = ["Microsoft Office", "Google Chrome", "Mozilla Firefox", "Visual Studio Code", "Python", "Java JDK",
                   "XAMPP", "NetBeans", "Adobe Photoshop", "AutoCAD", "Packet Tracer", "Windows Defender"]
MAINT_KINDS = ["Repair", "Hardware replacement", "Software installation", "Software update", "Software removal",
               "Cleaning / inspection", "Other"]


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def now() -> datetime:
    return datetime.now().replace(microsecond=0)


def ago(days: float = 0, hours: float = 0) -> datetime:
    return now() - timedelta(days=days, hours=hours)


def pad(n: int) -> str:
    return f"{int(n):02d}"


def pc_name(n: int) -> str:
    return f"PC {pad(n)}"


def lab_name(lab: int) -> str:
    return f"Centrum {lab}"


def asset_tag(lab: int, pc: int) -> str:
    return f"CL{lab}-PC{pad(pc)}"


def when(t: datetime | None) -> str:
    """'Just now', '5 min ago', '3 hours ago', 'Yesterday', '4 days ago', 'Sep 12'."""
    if not t:
        return "—"
    d = now() - t
    m = round(d.total_seconds() / 60)
    if m < 1:
        return "Just now"
    if m < 60:
        return f"{m} min ago"
    h = round(m / 60)
    if h < 24:
        return f"{h} hour ago" if h == 1 else f"{h} hours ago"
    days = round(h / 24)
    if days < 7:
        return "Yesterday" if days == 1 else f"{days} days ago"
    return f"{t:%b} {t.day}"


def date_time(t: datetime | None) -> str:
    if not t:
        return "—"
    return f"{t:%b} {t.day}, {int(t.strftime('%I'))}:{t:%M %p}"


def dur(seconds: float) -> str:
    h = seconds / 3600
    if h < 1:
        return f"{max(1, round(seconds / 60))} min"
    if h < 24:
        return f"{h:.1f}".replace(".0", "") + " h"
    return f"{h / 24:.1f}".replace(".0", "") + " days"


def lab_of(room) -> int:
    m = re.search(r"\d+", str(room or ""))
    return int(m.group()) if m else 1


def _parse_dt(value) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.astimezone().replace(tzinfo=None) if dt.tzinfo else dt


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------
def make_report(rid, lab, pc, issue, desc, by, created, status, tech=None, start_after=0.6, fix_after=3.0,
                note=None, esc_note="", urgency="Normal", db_id=None) -> dict:
    r = {"id": rid, "db_id": db_id if db_id is not None else rid, "lab": lab, "pc": pc, "issue": issue, "desc": desc,
         "by": by, "created": created, "status": status, "urgency": urgency, "tech": None, "esc_note": esc_note,
         "history": [{"s": "reported", "t": created, "note": "Report sent"}]}
    if status != "reported":
        r["tech"] = tech or TECHS[0]
        r["history"].append({"s": "repair", "t": created + timedelta(hours=start_after),
                             "note": f"{r['tech']} started the repair"})
    if status == "escalated":
        r["history"].append({"s": "escalated", "t": created + timedelta(hours=5), "note": note or "Needs a replacement part"})
    if status == "fixed":
        r["history"].append({"s": "fixed", "t": created + timedelta(hours=fix_after), "note": note or "Fixed and tested"})
    return r


def fixed_at(r: dict) -> datetime | None:
    return next((h["t"] for h in r["history"] if h["s"] == "fixed"), None)


def sample_reports() -> list[dict]:
    R = make_report
    reports = [
        R("R-1042", 3, 12, "No display", "Monitor stays black even though the PC is on.", SAMPLE_TEACHER, ago(0, 1.5), "reported", urgency="High"),
        R("R-1041", 3, 27, "No internet", "Browser says no connection. Other PCs in the row work.", "Maria Santos", ago(0, 3), "reported"),
        R("R-1040", 1, 5, "Keyboard / mouse", "Several keys on the keyboard do not respond.", "Ramon Aquino", ago(0, 5), "reported"),
        R("R-1039", 4, 11, "Won't turn on", "No lights when pressing the power button.", SAMPLE_TEACHER, ago(0, 20), "repair", start_after=1),
        R("R-1038", 2, 30, "Slow / freezing", "Freezes when opening the IDE; needs a restart every time.", "Liza Ramos", ago(1, 2), "repair", tech=TECHS[1]),
        R("R-1037", 2, 2, "Won't turn on", "Power supply smells burnt.", "Carlo Mendoza", ago(2, 4), "escalated",
          esc_note="Power supply is damaged. Needs a replacement PSU (500 W). Not in stock."),
        R("R-1036", 1, 14, "No display", "Display flickers then goes off.", SAMPLE_TEACHER, ago(2, 6), "escalated",
          esc_note="Monitor panel is failing. Recommend replacing the monitor."),
        R("R-1035", 3, 3, "Software problem", "MS Office asks for activation.", "Grace Villanueva", ago(0, 7), "reported"),
        R("R-1034", 4, 21, "Keyboard / mouse", "Mouse cursor jumps around.", "Paolo Reyes", ago(1, 5), "repair", tech=TECHS[1]),
        R("R-1033", 1, 23, "No internet", "LAN port loose.", "Maria Santos", ago(0, 9), "reported"),
        R("R-1032", 2, 9, "Other", "Headset jack not working.", SAMPLE_TEACHER, ago(3, 2), "fixed", fix_after=4, note="Front audio cable reconnected"),
        R("R-1031", 3, 18, "Slow / freezing", "Very slow at startup.", "Ramon Aquino", ago(3, 6), "fixed", fix_after=6, note="Cleaned startup apps, added RAM"),
        R("R-1030", 4, 8, "No display", "Monitor cable missing.", SAMPLE_TEACHER, ago(5, 3), "fixed", fix_after=1.2, note="Replaced the VGA cable"),
        R("R-1029", 1, 31, "Software problem", "Python not installed.", "Liza Ramos", ago(6, 1), "fixed", fix_after=20, note="Installed Python 3.12"),
        R("R-1028", 2, 17, "Keyboard / mouse", "Mouse missing.", "Carlo Mendoza", ago(8, 2), "fixed", fix_after=2, note="New mouse issued"),
        R("R-1027", 4, 33, "No internet", "No IP address.", SAMPLE_TEACHER, ago(10, 5), "fixed", fix_after=5, note="Switch port replaced"),
    ]
    rand, rid = random.Random(42), 1026
    for w in range(1, 8):  # older history for the charts (8 weeks)
        for _ in range(4 + int(rand.random() * 6)):
            created = ago(w * 7 + int(rand.random() * 7), int(rand.random() * 10))
            if created > ago(10):
                continue
            lab = 1 + int(rand.random() * 4)
            reports.append(R(f"R-{rid}", lab, 1 + int(rand.random() * MAP_SEATS), ISSUES[int(rand.random() * len(ISSUES))],
                             "Earlier report.", TEACHERS[int(rand.random() * len(TEACHERS))], created, "fixed",
                             fix_after=1 + rand.random() * 30, tech=TECHS[int(rand.random() * 2)]))
            rid -= 1
    return reports


_LIVE_STATUS = {"resolved": "fixed", "followup": "escalated"}


def report_from_backend(r: dict) -> dict:
    """A row from /admin/dashboard -> a report here. 'progress' is 'Under repair'
    once a technician has it, otherwise 'Reported'; 'followup' is 'Escalated'."""
    raw = str(r.get("status") or "progress").lower()
    handled = str(r.get("handled_by") or "")
    status = _LIVE_STATUS.get(raw, "repair" if handled else "reported")
    issues = r.get("issues") or []
    if isinstance(issues, str):
        issues = [i.strip() for i in issues.split(",") if i.strip()]
    created = _parse_dt(r.get("created_at")) or now()
    note = str(r.get("resolution_note") or "")
    rep = {"id": str(r.get("code") or r.get("id") or "—"), "db_id": r.get("id"), "lab": lab_of(r.get("room")),
           "pc": int(r.get("unit_number") or 0), "issue": ", ".join(map(str, issues)) or "Other",
           "desc": str(r.get("comment") or ""), "by": str(r.get("reporter") or "Unknown"), "created": created,
           "status": status, "urgency": "Normal", "tech": handled or None,
           "esc_note": note if status == "escalated" else "",
           "history": [{"s": "reported", "t": created, "note": "Report sent"}]}
    if status != "reported":
        rep["history"].append({"s": "repair", "t": created, "note": f"{handled or 'Technician'} started the repair"})
    if status in ("escalated", "fixed"):
        rep["history"].append({"s": status, "t": created, "note": note or STATUS[status][0]})
    return rep


# ---------------------------------------------------------------------------
# Computers (the inventory)
# ---------------------------------------------------------------------------
def new_computer(lab: int, pc: int, hardware: dict, software: list, name: str = "", notes: str = "",
                 added: datetime | None = None) -> dict:
    return {"lab": int(lab), "pc": int(pc), "tag": asset_tag(lab, pc), "name": name or asset_tag(lab, pc),
            "hardware": dict(hardware), "software": [dict(s) for s in software], "log": [], "notes": notes,
            "added": added}


def sample_computers() -> dict:
    comps = {}
    for lab, _ in LABS:
        hw = dict(zip(HW_FIELDS, SPECS[lab]))
        sw = [{"name": n, "version": v} for n, v in DEFAULT_SOFTWARE]
        for pc in range(1, MAP_SEATS + 1):
            comps[(lab, pc)] = new_computer(lab, pc, hw, sw, added=ago(400))
    c = comps[(3, 18)]  # a few earlier upgrades, so maintenance history has examples
    c["log"].append({"t": ago(3, 0), "kind": "Hardware replacement", "text": "Memory (RAM): 8 GB DDR4 → 16 GB DDR4", "by": TECHS[0]})
    c["hardware"]["Memory (RAM)"] = "16 GB DDR4"
    c = comps[(1, 31)]
    c["log"].append({"t": ago(5, 4), "kind": "Software update", "text": "Python 3.11 → 3.12", "by": TECHS[0]})
    next(s for s in c["software"] if s["name"] == "Python")["version"] = "3.12"
    comps[(2, 9)]["log"].append({"t": ago(20), "kind": "Cleaning / inspection", "text": "Dust cleaning and thermal paste", "by": TECHS[1]})
    return comps


def computers_from_units(units: list[dict]) -> dict:
    comps = {}
    for u in units or []:
        lab, pc = lab_of(u.get("room")), int(u.get("number") or 0)
        if pc <= 0:
            continue
        hw = dict(u.get("hardware") or {}) or dict(zip(HW_FIELDS, SPECS.get(lab, SPECS[1])))
        system = u.get("system") or {}
        if isinstance(system, dict):
            for k, v in system.items():
                hw.setdefault(str(k), v)
        sw_raw = u.get("software") or []
        if isinstance(sw_raw, dict):
            sw_raw = list(sw_raw.items())
        sw = []
        for item in sw_raw:
            if isinstance(item, (list, tuple)) and item:
                sw.append({"name": str(item[0]), "version": str(item[1]) if len(item) > 1 else ""})
            elif isinstance(item, dict):
                sw.append({"name": str(item.get("name", "")), "version": str(item.get("version", ""))})
        comps[(lab, pc)] = new_computer(lab, pc, {str(k): str(v) for k, v in hw.items()}, sw, name=str(u.get("name") or ""))
    return comps


# ---------------------------------------------------------------------------
# Account requests
# ---------------------------------------------------------------------------
def sample_requests() -> list[dict]:
    return [
        {"id": 1, "name": "Kevin Castillo", "email": "kevin.castillo@isu.edu.ph", "dept": "CCSICT", "role": "Technician", "t": ago(0, 4), "st": "pending", "done": None},
        {"id": 2, "name": "Andrea Lim", "email": "andrea.lim@isu.edu.ph", "dept": "COE", "role": "Technician", "t": ago(1, 3), "st": "pending", "done": None},
        {"id": 3, "name": "Rafael Cruz", "email": "rafael.cruz@isu.edu.ph", "dept": "CCSICT", "role": "Technician", "t": ago(2, 8), "st": "pending", "done": None},
        {"id": 4, "name": "Joy Navarro", "email": "joy.navarro@isu.edu.ph", "dept": "CAS", "role": "Technician", "t": ago(5), "st": "active", "done": ago(4)},
    ]


_REQ_STATUS = {"active": "active", "approved": "active", "confirmed": "active", "pending": "pending",
               "rejected": "rejected", "cancelled": "rejected", "canceled": "rejected", "declined": "rejected"}


def request_from_backend(r: dict) -> dict:
    return {"id": r.get("id"), "name": str(r.get("full_name") or r.get("email") or "Unknown"),
            "email": str(r.get("email") or ""), "dept": str(r.get("department") or ""),
            "role": str(r.get("role") or "").title(), "t": _parse_dt(r.get("submitted_at")),
            "st": _REQ_STATUS.get(str(r.get("status") or "").lower(), "pending"), "done": _parse_dt(r.get("decided_at"))}


# ---------------------------------------------------------------------------
# The store
# ---------------------------------------------------------------------------
def sample_store(notice: str = "") -> dict:
    return {"reports": sample_reports(), "computers": sample_computers(), "requests": sample_requests(),
            "decided": [], "live": False, "notice": notice}


def live_store(result: dict) -> dict:
    store = sample_store()
    store["live"] = True
    problems = [str(p) for p in result.get("problems") or []]
    lab = result.get("lab")
    if isinstance(lab, dict):
        store["reports"] = [report_from_backend(r) for r in lab.get("reports") or []]
        comps = computers_from_units(lab.get("units") or [])
        if comps:
            store["computers"] = comps
        else:
            problems.append("No computers are stored yet, so the sample inventory is shown.")
    if isinstance(result.get("requests"), list):
        store["requests"] = [request_from_backend(r) for r in result["requests"]
                             if str(r.get("role") or "").lower() in ("teacher", "technician")]
    store["notice"] = ("Sample data is shown where live data couldn't be loaded - " + " ".join(problems)) if problems else ""
    return store


def technician_store(result: dict) -> dict:
    """The technician dashboard data (/technician/dashboard: units + reports) -> a store."""
    store = sample_store()
    store["live"], store["requests"] = True, []
    store["reports"] = [report_from_backend(r) for r in result.get("reports") or []]
    comps = computers_from_units(result.get("units") or [])
    if comps:
        store["computers"] = comps
    else:
        store["notice"] = "No computers are stored yet, so the floor map shows the sample computers."
    return store


def make_personal(store: dict, sample_name: str, name: str) -> dict:
    """In the sample data the work of `sample_name` (a teacher or technician)
    belongs to whoever is signed in."""
    if name and name != sample_name:
        for r in store["reports"]:
            for key in ("by", "tech"):
                if r.get(key) == sample_name:
                    r[key] = name
            for e in r["history"]:
                e["note"] = e["note"].replace(sample_name, name)
    return store


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------
def by_name(r: dict) -> str:
    return r["by"]


def open_reports(store: dict) -> list[dict]:
    return [r for r in store["reports"] if r["status"] in OPEN]


def pc_report(store: dict, lab: int, pc: int) -> dict | None:
    mine = [r for r in store["reports"] if r["lab"] == lab and r["pc"] == pc and r["status"] in OPEN]
    return max(mine, key=lambda r: r["created"]) if mine else None


def pc_status(store: dict, lab: int, pc: int) -> str:
    r = pc_report(store, lab, pc)
    return r["status"] if r else "ok"


def lab_computers(store: dict, lab: int) -> list[dict]:
    return sorted((c for c in store["computers"].values() if c["lab"] == lab), key=lambda c: c["pc"])


def lab_summary(store: dict, lab: int) -> dict:
    s = {"total": 0, "ok": 0, "reported": 0, "repair": 0}
    for c in lab_computers(store, lab):
        s["total"] += 1
        st = pc_status(store, lab, c["pc"])
        s["ok" if st == "ok" else "reported" if st == "reported" else "repair"] += 1
    return s


def last_serviced(store: dict, comp: dict) -> datetime | None:
    times = [e["t"] for e in maintenance_history(store, comp)]
    return max(times) if times else None


def maintenance_history(store: dict, comp: dict) -> list[dict]:
    """Every maintenance activity on this computer, newest first: entries logged
    here (hardware/software changes, manual logs, escalation decisions) plus the
    repairs closed on its reports."""
    out = [dict(e) for e in comp["log"]]
    for r in store["reports"]:
        if r["lab"] != comp["lab"] or r["pc"] != comp["pc"]:
            continue
        for h in r["history"]:
            if h["s"] == "fixed":
                out.append({"t": h["t"], "kind": "Repair", "text": f"{r['issue']}: {h['note']} ({r['id']})",
                            "by": r.get("tech") or "Technician"})
    return sorted(out, key=lambda e: e["t"], reverse=True)


def computer_status_label(st: str) -> tuple[str, str]:
    return ("Working", "b-fixed") if st == "ok" else STATUS.get(st, (st, "b-neutral"))


# ---------------------------------------------------------------------------
# Changes (kept in the session)
# ---------------------------------------------------------------------------
def log(comp: dict, kind: str, text: str, by: str) -> None:
    comp["log"].append({"t": now(), "kind": kind, "text": text, "by": by})


def next_free_pc(store: dict, lab: int) -> int:
    used = {c["pc"] for c in store["computers"].values() if c["lab"] == lab}
    n = 1
    while n in used:
        n += 1
    return n


def add_computer(store: dict, *, lab: int, pc: int, name: str, hardware: dict, software: list[dict], notes: str,
                 by: str) -> tuple[bool, str]:
    if (lab, pc) in store["computers"]:
        return False, f"{asset_tag(lab, pc)} already exists in {lab_name(lab)}."
    if not any(v.strip() for v in hardware.values()):
        return False, "Add at least the processor, memory or storage."
    comp = new_computer(lab, pc, {k: v.strip() for k, v in hardware.items() if v.strip()}, software,
                        name=name.strip(), notes=notes.strip(), added=now())
    log(comp, "Added", f"Registered in {lab_name(lab)} as {comp['tag']}"
        + (f" with {len(software)} program(s)" if software else ""), by)
    store["computers"][(lab, pc)] = comp
    return True, f"{comp['tag']} added to the inventory"


def update_details(store: dict, comp: dict, *, name: str, notes: str, hardware: dict, by: str) -> tuple[bool, str]:
    changes = 0
    name, notes = name.strip(), notes.strip()
    if name and name != comp["name"]:
        log(comp, "Details updated", f"Name: {comp['name']} → {name}", by)
        comp["name"] = name
        changes += 1
    if notes != comp.get("notes", ""):
        comp["notes"] = notes
        log(comp, "Details updated", "Notes updated", by)
        changes += 1
    for label, value in hardware.items():
        value = value.strip()
        old = comp["hardware"].get(label, "")
        if value == old:
            continue
        if not value:
            comp["hardware"].pop(label, None)
            log(comp, "Hardware replacement", f"{label}: {old} removed", by)
        else:
            comp["hardware"][label] = value
            log(comp, "Hardware replacement", f"{label}: {old or 'none'} → {value}", by)
        changes += 1
    if not changes:
        return False, "Nothing changed."
    return True, f"{comp['tag']} updated — {changes} change{'s' if changes > 1 else ''} added to its maintenance history"


def install_software(comp: dict, name: str, version: str, by: str) -> tuple[bool, str]:
    name, version = name.strip(), version.strip()
    if not name:
        return False, "Enter the program's name."
    existing = next((s for s in comp["software"] if s["name"].lower() == name.lower()), None)
    if existing:
        return update_software(comp, existing["name"], version, by)
    comp["software"].append({"name": name, "version": version})
    log(comp, "Software installation", f"Installed {name} {version}".strip(), by)
    return True, f"{name} installed on {comp['tag']}"


def update_software(comp: dict, name: str, version: str, by: str) -> tuple[bool, str]:
    item = next((s for s in comp["software"] if s["name"] == name), None)
    version = version.strip()
    if item is None:
        return False, f"{name} isn't installed."
    if not version or version == item["version"]:
        return False, "Enter the new version."
    log(comp, "Software update", f"{name} {item['version']} → {version}", by)
    item["version"] = version
    return True, f"{name} updated to {version}"


def remove_software(comp: dict, name: str, by: str) -> tuple[bool, str]:
    item = next((s for s in comp["software"] if s["name"] == name), None)
    if item is None:
        return False, f"{name} isn't installed."
    comp["software"].remove(item)
    log(comp, "Software removal", f"Removed {name} {item['version']}".strip(), by)
    return True, f"{name} removed from {comp['tag']}"


def log_maintenance(comp: dict, kind: str, text: str, by: str) -> tuple[bool, str]:
    if not text.strip():
        return False, "Describe what was done."
    log(comp, kind, text.strip(), by.strip() or "Admin")
    return True, f"Maintenance logged for {comp['tag']}"


def set_report_status(store: dict, r: dict, status: str, note: str, by: str | None = None) -> None:
    r["status"] = status
    if status != "reported" and not r.get("tech") and by:
        r["tech"] = by
    r["history"].append({"s": status, "t": now(), "note": note})


# Report status names the technician backend uses (see report_from_backend).
BACKEND_STATUS = {"repair": "progress", "fixed": "resolved", "escalated": "followup"}


def add_report(store: dict, *, lab: int, pc: int, issue: str, desc: str, urgency: str, by: str) -> dict:
    """A new report from a teacher (kept in this session)."""
    nums = [int(m.group(1)) for r in store["reports"] for m in [re.match(r"R-(\d+)$", str(r["id"]))] if m]
    r = make_report(f"R-{max(nums + [1000]) + 1}", lab, pc, issue, desc, by, now(), "reported", urgency=urgency)
    store["reports"].append(r)
    return r


def decide_escalation(store: dict, r: dict, what: str, by: str) -> str:
    if what == "approve":
        text = f"Replacement approved by {by}"
        set_report_status(store, r, "repair", text)
    elif what == "resolve":
        text = f"Marked resolved by {by}"
        set_report_status(store, r, "fixed", text)
    else:
        text = f"Sent back to the technician by {by}"
        set_report_status(store, r, "repair", text)
    comp = store["computers"].get((r["lab"], r["pc"]))
    if comp is not None and what != "back":
        log(comp, "Escalation", f"{r['id']}: {text}" + (f" — {r['esc_note']}" if r.get("esc_note") else ""), by)
    store["decided"].append({"r": r, "text": text, "t": now()})
    return text


# ---------------------------------------------------------------------------
# Sorting
# ---------------------------------------------------------------------------
STATUS_ORDER = {"reported": 0, "repair": 1, "escalated": 2, "fixed": 3, "ok": 4}

REPORT_SORTS = {
    "new": "Newest first", "old": "Oldest first", "status": "Status", "computer": "Computer",
    "lab": "Laboratory", "by": "Reported by (A–Z)", "issue": "Problem (A–Z)",
}


def sort_reports(rows: list[dict], how: str) -> list[dict]:
    keys = {
        "old": lambda r: r["created"],
        "status": lambda r: (STATUS_ORDER.get(r["status"], 9), -r["created"].timestamp()),
        "computer": lambda r: (r["lab"], r["pc"]),
        "lab": lambda r: (r["lab"], -r["created"].timestamp()),
        "by": lambda r: (by_name(r).lower(), -r["created"].timestamp()),
        "issue": lambda r: (r["issue"].lower(), -r["created"].timestamp()),
    }
    if how == "priority":
        return sort_open(rows)
    if how in keys:
        return sorted(rows, key=keys[how])
    return sorted(rows, key=lambda r: r["created"], reverse=True)


def sort_open(rows: list[dict]) -> list[dict]:
    """Work order: new reports first, then under repair, then escalated; urgent ones first; oldest first."""
    order = {"reported": 0, "repair": 1, "escalated": 2, "fixed": 3}
    return sorted(rows, key=lambda r: (order.get(r["status"], 9), r["urgency"] != "High", r["created"]))


QUEUE_SORTS = {"priority": "Work order", **REPORT_SORTS}
MY_REPORT_SORTS = {"new": "Newest first", "old": "Oldest first", "status": "Status", "computer": "Computer",
                   "issue": "Problem (A–Z)"}


INVENTORY_SORTS = {
    "tag": "Asset tag (A–Z)", "tag_desc": "Asset tag (Z–A)", "name": "Computer name (A–Z)",
    "lab": "Laboratory", "status": "Status", "serviced_new": "Last serviced (newest)",
    "serviced_old": "Last serviced (oldest)", "added": "Recently added",
}


def sort_computers(store: dict, rows: list[dict], how: str) -> list[dict]:
    if how == "tag_desc":
        return sorted(rows, key=lambda c: (c["lab"], c["pc"]), reverse=True)
    if how == "name":
        return sorted(rows, key=lambda c: c["name"].lower())
    if how == "lab":
        return sorted(rows, key=lambda c: (c["lab"], c["pc"]))
    if how == "status":
        return sorted(rows, key=lambda c: (STATUS_ORDER.get(pc_status(store, c["lab"], c["pc"]), 9), c["lab"], c["pc"]))
    if how in ("serviced_new", "serviced_old"):
        dated = [(last_serviced(store, c), c) for c in rows]
        never = [c for t, c in dated if t is None]
        done = sorted(((t, c) for t, c in dated if t is not None), key=lambda x: x[0], reverse=how == "serviced_new")
        return [c for _, c in done] + never
    if how == "added":
        return sorted(rows, key=lambda c: c.get("added") or datetime.min, reverse=True)
    return sorted(rows, key=lambda c: (c["lab"], c["pc"]))


ESCALATION_SORTS = {"old": "Oldest first", "new": "Newest first", "lab": "Laboratory", "computer": "Computer"}
REQUEST_SORTS = {"new": "Newest first", "old": "Oldest first", "name": "Name (A–Z)", "dept": "Department"}
HEALTH_SORTS = {"lab": "Laboratory", "working": "Working now (lowest first)", "open": "Open reports (most first)",
                "recent": "Reports, 30 days (most first)", "fix": "Avg. time to fix (slowest first)"}
HISTORY_SORTS = {"new": "Newest first", "old": "Oldest first", "kind": "Type"}


def sort_requests(rows: list[dict], how: str, done: bool = False) -> list[dict]:
    t = (lambda u: u.get("done") or u.get("t") or datetime.min) if done else (lambda u: u.get("t") or datetime.min)
    if how == "old":
        return sorted(rows, key=t)
    if how == "name":
        return sorted(rows, key=lambda u: u["name"].lower())
    if how == "dept":
        return sorted(rows, key=lambda u: (u["dept"].lower(), u["name"].lower()))
    return sorted(rows, key=t, reverse=True)
