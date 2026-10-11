"""
frontend/lab_data.py - Centrum Laboratory | data behind the dashboards

Everything the admin, technician and teacher screens show and change lives in
one "store" dict per dashboard, kept in st.session_state:

    store = {
        "reports":   [report, ...],          # repair reports from teachers
        "computers": {(lab, pc): computer},  # the computer inventory (shared, see lab_store.py)
        "requests":  [request, ...],         # account requests (from the backend)
        "decided":   [decision, ...],        # escalation decisions made here
        "live": bool, "notice": str,
    }

There is NO built-in sample data any more. The computer inventory, teacher
reports, maintenance logs and notifications are kept in one shared store
(frontend/lab_store.py -> data/centrum_lab.json) so a change made by a
technician is seen by the admin and the teachers too. The inventory is filled
by the idempotent script frontend/seed_inventory.py (40 computers per lab).

This module has no Streamlit code (it is also used by the seed script).
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
LABS = [
    (1, "Southeast wing"),
    (2, "Southwest wing"),
    (3, "Northeast wing"),
    (4, "Northwest wing"),
]
WING = dict(LABS)
MAP_SEATS = 39  # computers drawn per laboratory on the floor map (seat 40+ are listed under the map)
COMPUTERS_PER_LAB = 40

ISSUES = [
    "No display",
    "Won't turn on",
    "No internet",
    "Keyboard / mouse",
    "Slow / freezing",
    "Software problem",
    "Other",
]
STATUS = {
    "reported": ("Reported", "b-reported"),
    "repair": ("Under repair", "b-repair"),
    "escalated": ("Escalated", "b-escalated"),
    "fixed": ("Fixed", "b-fixed"),
}
OPEN = ("reported", "repair", "escalated")

# The status of a computer's inventory record (set in the Add / Edit forms).
RECORD_STATUSES = ["Working", "Under maintenance", "Inactive"]
# A computer's live status: an open report wins, otherwise its record status.
PC_STATUS = {
    "ok": ("Working", "b-fixed"),
    "reported": ("Reported", "b-reported"),
    "repair": ("Under repair", "b-repair"),
    "escalated": ("Escalated", "b-escalated"),
    "maint": ("Under maintenance", "b-repair"),
    "inactive": ("Inactive", "b-neutral"),
}

# Hardware fields of a computer (label shown in the forms and the details).
HW_FIELDS = [
    "Processor",
    "Memory (RAM)",
    "Storage",
    "Graphics",
    "Monitor",
    "Keyboard & mouse",
    "Operating system",
]
REQUIRED_HW = ["Processor", "Memory (RAM)", "Storage", "Operating system"]
# Defaults that pre-fill the "Add computer" form for each laboratory.
SPECS = {
    1: [
        "Intel Core i5-10500",
        "8 GB DDR4",
        "256 GB NVMe SSD",
        "Intel UHD 630",
        'Dell E2220H 21.5"',
        "Dell USB keyboard & mouse",
        "Windows 11 Pro 23H2",
    ],
    2: [
        "AMD Ryzen 5 PRO 4650G",
        "16 GB DDR4",
        "512 GB NVMe SSD",
        "AMD Radeon (integrated)",
        'Lenovo T22i-20 21.5"',
        "Lenovo USB keyboard & mouse",
        "Windows 11 Pro 23H2",
    ],
    3: [
        "Intel Core i3-10100",
        "8 GB DDR4",
        "1 TB HDD",
        "Intel UHD 630",
        'Acer V226HQL 21.5"',
        "Acer USB keyboard & mouse",
        "Windows 10 Pro 22H2",
    ],
    4: [
        "Intel Core i5-12500",
        "16 GB DDR4",
        "512 GB NVMe SSD",
        "Intel UHD 770",
        'HP P24 G5 23.8"',
        "HP USB keyboard & mouse",
        "Windows 11 Pro 23H2",
    ],
}
DEFAULT_SOFTWARE = [
    ("Microsoft Office", "2021"),
    ("Google Chrome", "129"),
    ("Visual Studio Code", "1.93"),
    ("Python", "3.12"),
    ("Windows Defender", "Active"),
]
COMMON_SOFTWARE = [
    "Microsoft Office",
    "Google Chrome",
    "Mozilla Firefox",
    "Visual Studio Code",
    "Python",
    "Java JDK",
    "XAMPP",
    "NetBeans",
    "Adobe Photoshop",
    "AutoCAD",
    "Packet Tracer",
    "Windows Defender",
]
MAINT_KINDS = [
    "Repair",
    "Hardware replacement",
    "Software installation",
    "Software update",
    "Software removal",
    "Cleaning / inspection",
    "Other",
]


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
    """The unique asset ID of a computer (one per laboratory seat)."""
    return f"CL{int(lab)}-PC{pad(pc)}"


def when(t: datetime | None) -> str:
    """'Just now', '5 min ago', '3 hours ago', 'Yesterday', '4 days ago', 'Sep 12', 'Sep 12, 2023'."""
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
    return f"{t:%b} {t.day}" if t.year == now().year else f"{t:%b} {t.day}, {t.year}"


def date_only(t: datetime | None) -> str:
    return f"{t:%b} {t.day}, {t.year}" if t else "—"


def report_date(value) -> str:
    """Format a report's creation date safely."""
    dt = parse_dt(value)
    return date_only(dt)


def sent_date(value) -> str:
    """The Reports tables' "Sent" column: 'Oct 05, 2026', or 'N/A' when the
    report has no valid stored date (never today's date)."""
    dt = value if isinstance(value, datetime) else parse_dt(value)
    return f"{dt:%b %d, %Y}" if dt else "N/A"


def sent_date_time(value) -> str:
    """The report details window: 'Oct 05, 2026, 1:09 PM', or 'N/A' when there
    is no valid date."""
    dt = value if isinstance(value, datetime) else parse_dt(value)
    if not dt:
        return "N/A"
    return f"{dt:%b %d, %Y}, {int(dt.strftime('%I'))}:{dt:%M %p}"

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


def parse_dt(value) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.astimezone().replace(tzinfo=None) if dt.tzinfo else dt


_parse_dt = parse_dt  # old name


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------
def make_report(
    rid,
    lab,
    pc,
    issue,
    desc,
    by,
    created,
    status="reported",
    urgency="Normal",
    db_id=None,
    local=False,
) -> dict:
    return {
        "id": rid,
        "db_id": db_id if db_id is not None else rid,
        "lab": int(lab),
        "pc": int(pc),
        "issue": issue,
        "desc": desc,
        "by": by,
        "created": created,
        "status": status,
        "urgency": urgency,
        "tech": None,
        "esc_note": "",
        "local": local,
        "history": [{"s": "reported", "t": created, "note": "Report sent"}],
    }


def fixed_at(r: dict) -> datetime | None:
    """Return the actual resolution timestamp, if available."""
    for key in ("fixed_at", "resolved_at", "FixedAt", "ResolvedAt"):
        value = parse_dt(r.get(key))
        if value:
            return value

    # Local reports can use their recorded status-change history.
    if r.get("local"):
        for entry in reversed(r.get("history") or []):
            if entry.get("s") == "fixed":
                return parse_dt(entry.get("t"))

    return None

_LIVE_STATUS = {"resolved": "fixed", "followup": "escalated"}


def report_from_backend(r: dict) -> dict:
    """A row from /admin/dashboard or /technician/dashboard -> a report here. 'progress' is 'Under repair'
    once a technician has it, otherwise 'Reported'; 'followup' is 'Escalated'."""
    raw = str(r.get("status") or "progress").lower()
    handled = str(r.get("handled_by") or "")
    status = _LIVE_STATUS.get(raw, "repair" if handled else "reported")
    issues = r.get("issues") or []
    if isinstance(issues, str):
        issues = [i.strip() for i in issues.split(",") if i.strip()]
    sent_at = parse_dt(r.get("created_at"))  # Reports.CreatedAt; None when missing
    created = sent_at or now()
    note = str(r.get("resolution_note") or "")
    try:
        pc = int(r.get("unit_number") or 0)
    except (TypeError, ValueError):
        pc = 0
    rep = {
        "id": str(r.get("code") or r.get("id") or "—"),
        "db_id": r.get("id"),
        "lab": lab_of(r.get("room")),
        "pc": pc,
        "issue": ", ".join(map(str, issues)) or "Other",
        "desc": str(r.get("comment") or ""),
        "by": str(r.get("reporter") or "Unknown"),
        "created": created,
        "sent": sent_at,
        "status": status,
        "urgency": "Normal",
        "tech": handled or None,
        "local": False,
        "esc_note": note if status == "escalated" else "",
        "history": [{"s": "reported", "t": created, "note": "Report sent"}],
    }
    if status != "reported":
        rep["history"].append(
            {
                "s": "repair",
                "t": created,
                "note": f"{handled or 'Technician'} started the repair",
            }
        )
    if status in ("escalated", "fixed"):
        rep["history"].append(
            {"s": status, "t": created, "note": note or STATUS[status][0]}
        )
    return rep


# ---------------------------------------------------------------------------
# Computers (the inventory)
# ---------------------------------------------------------------------------
def new_computer(
    lab: int,
    pc: int,
    hardware: dict,
    software: list,
    name: str = "",
    notes: str = "",
    added: datetime | None = None,
    brand: str = "",
    model: str = "",
    serial: str = "",
    status: str = "Working",
) -> dict:
    tag = asset_tag(lab, pc)
    return {
        "lab": int(lab),
        "pc": int(pc),
        "tag": tag,
        "name": name or tag,
        "brand": brand,
        "model": model,
        "serial": serial,
        "status": status if status in RECORD_STATUSES else "Working",
        "hardware": dict(hardware),
        "software": [dict(s) for s in software],
        "log": [],
        "notes": notes,
        "added": added or now(),
        "updated": None,
    }


# ComputerHardware column -> the hardware label the screens use (HW_FIELDS).
HW_COLUMNS = {
    "Processor": "Processor",
    "Ram": "Memory (RAM)",
    "Storage": "Storage",
    "Graphics": "Graphics",
    "Monitor": "Monitor",
    "Peripherals": "Keyboard & mouse",
    "OperatingSystem": "Operating system",
    "operating_system": "Operating system",
    **{f: f for f in HW_FIELDS},
}


def hardware_fields(row) -> dict:
    """A ComputerHardware record -> {screen label: value}. Only columns that have
    a value in the database are kept; nothing is filled in."""
    out = {}
    if not isinstance(row, dict):
        return out
    for col, label in HW_COLUMNS.items():
        value = row.get(col)
        value = "" if value is None else str(value).strip()
        if value and label not in out:
            out[label] = value
    return out


def computers_from_units(units: list[dict]) -> dict:
    """Computers stored in the backend (/... units) -> inventory records."""
    comps = {}
    for u in units or []:
        lab = lab_of(u.get("room"))
        try:
            pc = int(u.get("number") or 0)
        except (TypeError, ValueError):
            continue
        if pc <= 0:
            continue
        # Only what ComputerHardware holds for this ComputerId - no default specs.
        hw = hardware_fields(u.get("hardware"))
        for k, v in hardware_fields(u.get("system")).items():
            hw.setdefault(k, v)
        sw_raw = u.get("software") or []
        if isinstance(sw_raw, dict):
            sw_raw = list(sw_raw.items())
        sw = []
        for item in sw_raw:
            if isinstance(item, (list, tuple)) and item:
                sw.append(
                    {
                        "name": str(item[0]),
                        "version": str(item[1]) if len(item) > 1 else "",
                        "installed": str(item[2] or "") if len(item) > 2 else "",
                    }
                )
            elif isinstance(item, dict):
                sw.append(
                    {
                        "name": str(item.get("name", "")),
                        "version": str(item.get("version", "")),
                        "installed": str(item.get("installed") or ""),
                    }
                )
        comps[(lab, pc)] = new_computer(
            lab,
            pc,
            {str(k): str(v) for k, v in hw.items()},
            sw,
            name=str(u.get("name") or ""),
            added=parse_dt(u.get("created_at")),
        )
    return comps


# ---------------------------------------------------------------------------
# Account requests
# ---------------------------------------------------------------------------
_REQ_STATUS = {
    "active": "active",
    "approved": "active",
    "confirmed": "active",
    "pending": "pending",
    "rejected": "rejected",
    "cancelled": "rejected",
    "canceled": "rejected",
    "declined": "rejected",
}


def request_from_backend(r: dict) -> dict:
    name = (
        r.get("full_name")
        or " ".join(str(r.get(k) or "") for k in ("first_name", "last_name")).strip()
    )
    return {
        "id": r.get("id"),
        "name": str(name or r.get("email") or "Unknown"),
        "email": str(r.get("email") or ""),
        "dept": str(r.get("department") or ""),
        "role": str(r.get("role") or "").title(),
        "t": parse_dt(r.get("submitted_at") or r.get("created_at")),
        "st": _REQ_STATUS.get(str(r.get("status") or "").lower(), "pending"),
        "done": parse_dt(r.get("decided_at")),
    }


# ---------------------------------------------------------------------------
# The store
# ---------------------------------------------------------------------------
def empty_store(notice: str = "") -> dict:
    return {
        "reports": [],
        "backend_reports": [],
        "computers": {},
        "requests": [],
        "decided": [],
        "live": False,
        "notice": notice,
    }


def live_store(result: dict) -> dict:
    """The admin dashboard data (/admin/dashboard) -> a store.

    ROOT CAUSE OF "0 out of 0 computers" (fixed here)
    -------------------------------------------------
    This function used to write the data it built under keys that nothing
    reads:

        store["units"]           = computers_from_units(...)   # built OK
        store["backend_reports"] = [report_from_backend(r) ...] # built OK

    But every consumer reads the keys declared in this module's docstring:

        lab_computers()  -> store["computers"]
        pc_status()      -> store["computers"]
        lab_summary()    -> store["computers"]   (via lab_computers)
        open_reports()   -> store["reports"]
        pc_report()      -> store["reports"]

    Because `empty_store()` initialises `"computers": {}` and `"reports": []`,
    those keys kept their EMPTY defaults while the real, correctly-converted
    records sat unread under `"units"` / `"backend_reports"`.

    So `lab_summary()` counted an empty dict for every laboratory and the
    Admin dashboard rendered "0 Computers in 4 laboratories",
    "0% / 0 of 0 computers working" and "0 Open reports" even though the
    backend had returned real rows from the Supabase `Computers` table.

    The fix writes the canonical keys. The legacy keys are kept as aliases
    pointing at the same objects so any other caller that still reads
    `"units"` / `"backend_reports"` keeps working unchanged.
    """
    store = empty_store()
    store["live"] = True
    problems = [str(p) for p in result.get("problems") or []]
    lab = result.get("lab")
    if isinstance(lab, dict):
        reports = [
            report_from_backend(r)
            for r in lab.get("reports") or []
            if isinstance(r, dict)
        ]
        # Canonical key read by open_reports(), pc_report(), the dashboards.
        store["reports"] = reports
        # Legacy alias - same list object, kept for backwards compatibility.
        store["backend_reports"] = reports

        # The backend calls these "units"; the inventory/count helpers call
        # them "computers". computers_from_units() already returns the
        # {(lab, pc): computer} mapping those helpers expect.
        computers = computers_from_units(lab.get("units") or [])
        # Canonical key read by lab_computers(), pc_status(), lab_summary().
        store["computers"] = computers
        # Legacy alias - same dict object.
        store["units"] = computers
    if isinstance(result.get("requests"), list):
        store["requests"] = [
            request_from_backend(r)
            for r in result["requests"]
            if isinstance(r, dict)
            and str(r.get("role") or "").lower() in ("teacher", "technician")
        ]
    store["notice"] = (
        ("Some live data couldn't be loaded - " + " ".join(problems))
        if problems
        else ""
    )
    return store


def technician_store(result: dict) -> dict:
    """The technician dashboard data (/technician/dashboard: units + reports) -> a store.

    This had the same key mismatch as live_store() above. The canonical keys
    are now written as well; the legacy keys are kept as aliases to the same
    objects, so this change is purely additive and cannot remove anything the
    Technician screens already relied on.
    """
    store = empty_store()
    store["live"] = True
    reports = [
        report_from_backend(r)
        for r in result.get("reports") or []
        if isinstance(r, dict)
    ]
    store["reports"] = reports
    store["backend_reports"] = reports

    computers = computers_from_units(result.get("units") or [])
    store["computers"] = computers
    store["units"] = computers
    return store


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------
def by_name(r: dict) -> str:
    return r["by"]


def open_reports(store: dict) -> list[dict]:
    return [r for r in store["reports"] if r["status"] in OPEN]


def pc_report(store: dict, lab: int, pc: int) -> dict | None:
    mine = [
        r
        for r in store["reports"]
        if r["lab"] == lab and r["pc"] == pc and r["status"] in OPEN
    ]
    return max(mine, key=lambda r: r["created"]) if mine else None


def pc_status(store: dict, lab: int, pc: int) -> str:
    """ok / reported / repair / escalated (open report) / maint / inactive (record status)."""
    r = pc_report(store, lab, pc)
    if r:
        return r["status"]
    comp = store["computers"].get((lab, pc))
    rec = (comp or {}).get("status", "Working")
    return (
        "maint"
        if rec == "Under maintenance"
        else "inactive" if rec == "Inactive" else "ok"
    )


def lab_computers(store: dict, lab: int) -> list[dict]:
    return sorted(
        (c for c in store["computers"].values() if c["lab"] == lab),
        key=lambda c: c["pc"],
    )


def lab_summary(store: dict, lab: int) -> dict:
    """Counts for a laboratory. Inactive computers are not part of the total."""
    s = {"total": 0, "ok": 0, "reported": 0, "repair": 0, "inactive": 0}
    for c in lab_computers(store, lab):
        st = pc_status(store, lab, c["pc"])
        if st == "inactive":
            s["inactive"] += 1
            continue
        s["total"] += 1
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
                out.append(
                    {
                        "t": h["t"],
                        "kind": "Repair",
                        "text": f"{r['issue']}: {h['note']} ({r['id']})",
                        "by": r.get("tech") or "Technician",
                    }
                )
    return sorted(out, key=lambda e: e["t"], reverse=True)


def computer_status_label(st: str) -> tuple[str, str]:
    return PC_STATUS.get(st) or STATUS.get(st, (st, "b-neutral"))


def spec_line(comp: dict) -> str:
    hw = comp["hardware"]
    return " · ".join(
        v for k, v in hw.items() if k in ("Processor", "Memory (RAM)", "Storage") and v
    ) or " · ".join(list(hw.values())[:3])


def search_text(comp: dict) -> str:
    return " ".join(
        [
            comp["tag"],
            comp["name"],
            comp.get("brand", ""),
            comp.get("model", ""),
            comp.get("serial", ""),
            comp.get("status", ""),
            lab_name(comp["lab"]),
            pc_name(comp["pc"]),
            comp.get("notes", ""),
        ]
        + list(comp["hardware"].values())
        + [x["name"] for x in comp["software"]]
    ).lower()


# ---------------------------------------------------------------------------
# Changes (the caller saves the shared store afterwards)
# ---------------------------------------------------------------------------
def log(comp: dict, kind: str, text: str, by: str) -> None:
    comp["log"].append({"t": now(), "kind": kind, "text": text, "by": by})
    comp["updated"] = now()


def next_free_pc(store: dict, lab: int) -> int:
    used = {c["pc"] for c in store["computers"].values() if c["lab"] == lab}
    n = 1
    while n in used:
        n += 1
    return n


def _serial_taken(store: dict, serial: str, skip: tuple | None = None) -> bool:
    serial = serial.strip().lower()
    return bool(serial) and any(
        k != skip and str(c.get("serial", "")).strip().lower() == serial
        for k, c in store["computers"].items()
    )


def missing_hw(hardware: dict) -> list[str]:
    return [f for f in REQUIRED_HW if not str(hardware.get(f, "")).strip()]


def add_computer(
    store: dict,
    *,
    lab: int,
    pc: int,
    name: str,
    hardware: dict,
    software: list[dict],
    notes: str,
    by: str,
    brand: str = "",
    model: str = "",
    serial: str = "",
    status: str = "Working",
) -> tuple[bool, str]:
    if lab not in WING:
        return False, "Pick a laboratory."
    if (lab, pc) in store["computers"]:
        return (
            False,
            f"{asset_tag(lab, pc)} already exists in {lab_name(lab)}. Pick another computer number.",
        )
    missing = missing_hw(hardware)
    if missing:
        return False, "Fill in: " + ", ".join(missing) + "."
    if _serial_taken(store, serial):
        return False, f"Another computer already has serial number {serial.strip()}."
    comp = new_computer(
        lab,
        pc,
        {k: v.strip() for k, v in hardware.items() if v.strip()},
        software,
        name=name.strip(),
        notes=notes.strip(),
        added=now(),
        brand=brand.strip(),
        model=model.strip(),
        serial=serial.strip(),
        status=status,
    )
    log(
        comp,
        "Added",
        f"Registered in {lab_name(lab)} as {comp['tag']}"
        + (f" with {len(software)} program(s)" if software else ""),
        by,
    )
    store["computers"][(lab, pc)] = comp
    return True, f"{comp['tag']} added to the inventory"


def update_details(
    store: dict,
    comp: dict,
    *,
    name: str,
    notes: str,
    hardware: dict,
    by: str,
    brand: str | None = None,
    model: str | None = None,
    serial: str | None = None,
    status: str | None = None,
) -> tuple[bool, str]:
    missing = [
        f for f in REQUIRED_HW if f in hardware and not str(hardware.get(f, "")).strip()
    ]
    if missing:
        return False, "These can't be empty: " + ", ".join(missing) + "."
    if serial is not None and _serial_taken(
        store, serial, skip=(comp["lab"], comp["pc"])
    ):
        return False, f"Another computer already has serial number {serial.strip()}."
    changes = 0
    name, notes = name.strip(), notes.strip()
    if name and name != comp["name"]:
        log(comp, "Details updated", f"Name: {comp['name']} → {name}", by)
        comp["name"] = name
        changes += 1
    for key, label, value in (
        ("brand", "Brand", brand),
        ("model", "Model", model),
        ("serial", "Serial number", serial),
    ):
        if value is None:
            continue
        value = value.strip()
        if value != comp.get(key, ""):
            log(
                comp,
                "Details updated",
                f"{label}: {comp.get(key) or 'none'} → {value or 'none'}",
                by,
            )
            comp[key] = value
            changes += 1
    if status and status in RECORD_STATUSES and status != comp.get("status", "Working"):
        log(comp, "Status changed", f"{comp.get('status', 'Working')} → {status}", by)
        comp["status"] = status
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
    return (
        True,
        f"{comp['tag']} saved — {changes} change{'s' if changes > 1 else ''} added to its maintenance history",
    )


def install_software(comp: dict, name: str, version: str, by: str) -> tuple[bool, str]:
    name, version = name.strip(), version.strip()
    if not name:
        return False, "Enter the program's name."
    existing = next(
        (s for s in comp["software"] if s["name"].lower() == name.lower()), None
    )
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
        return False, "Enter a new version number."
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
    if len(text.strip()) < 5:
        return False, "Add a bit more detail about what was done."
    log(comp, kind, text.strip(), by.strip() or "Staff")
    return True, f"Maintenance logged for {comp['tag']}"


def set_report_status(
    store: dict, r: dict, status: str, note: str, by: str | None = None
) -> None:
    r["status"] = status
    if status != "reported" and not r.get("tech") and by:
        r["tech"] = by
    r["history"].append({"s": status, "t": now(), "note": note})


# Report status names the technician backend uses (see report_from_backend).
BACKEND_STATUS = {"repair": "progress", "fixed": "resolved", "escalated": "followup"}


def next_report_id(reports: list[dict]) -> str:
    nums = [
        int(m.group(1))
        for r in reports
        for m in [re.match(r"R-(\d+)$", str(r["id"]))]
        if m
    ]
    return f"R-{max(nums + [1000]) + 1}"


def add_report(
    store: dict, *, lab: int, pc: int, issue: str, desc: str, urgency: str, by: str
) -> dict:
    """A new report from a teacher (kept in the shared store)."""
    r = make_report(
        next_report_id(store["reports"]),
        lab,
        pc,
        issue,
        desc,
        by,
        now(),
        "reported",
        urgency=urgency,
        local=True,
    )
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
        log(
            comp,
            "Escalation",
            f"{r['id']}: {text}" + (f" — {r['esc_note']}" if r.get("esc_note") else ""),
            by,
        )
    store["decided"].append({"r": r, "text": text, "t": now()})
    return text


# ---------------------------------------------------------------------------
# Sorting
# ---------------------------------------------------------------------------
STATUS_ORDER = {
    "reported": 0,
    "repair": 1,
    "escalated": 2,
    "maint": 3,
    "fixed": 4,
    "ok": 5,
    "inactive": 6,
}

REPORT_SORTS = {
    "new": "Newest first",
    "old": "Oldest first",
    "status": "Status",
    "computer": "Computer",
    "lab": "Laboratory",
    "by": "Reported by (A–Z)",
    "issue": "Problem (A–Z)",
}


def sort_reports(rows: list[dict], how: str) -> list[dict]:
    keys = {
        "old": lambda r: r["created"],
        "status": lambda r: (
            STATUS_ORDER.get(r["status"], 9),
            -r["created"].timestamp(),
        ),
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
    return sorted(
        rows,
        key=lambda r: (order.get(r["status"], 9), r["urgency"] != "High", r["created"]),
    )


QUEUE_SORTS = {"priority": "Work order", **REPORT_SORTS}
MY_REPORT_SORTS = {
    "new": "Newest first",
    "old": "Oldest first",
    "status": "Status",
    "computer": "Computer",
    "issue": "Problem (A–Z)",
}


INVENTORY_SORTS = {
    "tag": "Asset ID (A–Z)",
    "tag_desc": "Asset ID (Z–A)",
    "name": "Computer name (A–Z)",
    "lab": "Laboratory",
    "status": "Status",
    "added_new": "Date added (newest)",
    "added_old": "Date added (oldest)",
    "serviced_new": "Last serviced (newest)",
    "serviced_old": "Last serviced (oldest)",
    "cpu": "Processor (A–Z)",
}


def sort_computers(store: dict, rows: list[dict], how: str) -> list[dict]:
    if how == "tag_desc":
        return sorted(rows, key=lambda c: (c["lab"], c["pc"]), reverse=True)
    if how == "name":
        return sorted(rows, key=lambda c: c["name"].lower())
    if how == "lab":
        return sorted(rows, key=lambda c: (c["lab"], c["pc"]))
    if how == "cpu":
        return sorted(
            rows,
            key=lambda c: (
                c["hardware"].get("Processor", "").lower(),
                c["lab"],
                c["pc"],
            ),
        )
    if how == "status":
        return sorted(
            rows,
            key=lambda c: (
                STATUS_ORDER.get(pc_status(store, c["lab"], c["pc"]), 9),
                c["lab"],
                c["pc"],
            ),
        )
    if how in ("serviced_new", "serviced_old"):
        dated = [(last_serviced(store, c), c) for c in rows]
        never = [c for t, c in dated if t is None]
        done = sorted(
            ((t, c) for t, c in dated if t is not None),
            key=lambda x: x[0],
            reverse=how == "serviced_new",
        )
        return [c for _, c in done] + never
    if how in ("added_new", "added", "added_old"):
        return sorted(
            rows,
            key=lambda c: (c.get("added") or datetime.min, -c["lab"], -c["pc"]),
            reverse=how != "added_old",
        )
    return sorted(rows, key=lambda c: (c["lab"], c["pc"]))


ESCALATION_SORTS = {
    "old": "Oldest first",
    "new": "Newest first",
    "lab": "Laboratory",
    "computer": "Computer",
}
REQUEST_SORTS = {
    "new": "Newest first",
    "old": "Oldest first",
    "name": "Name (A–Z)",
    "dept": "Department",
}
HEALTH_SORTS = {
    "lab": "Laboratory",
    "working": "Working now (lowest first)",
    "open": "Open reports (most first)",
    "recent": "Reports, 30 days (most first)",
    "fix": "Avg. time to fix (slowest first)",
}
HISTORY_SORTS = {"new": "Newest first", "old": "Oldest first", "kind": "Type"}


def sort_requests(rows: list[dict], how: str, done: bool = False) -> list[dict]:
    t = (
        (lambda u: u.get("done") or u.get("t") or datetime.min)
        if done
        else (lambda u: u.get("t") or datetime.min)
    )
    if how == "old":
        return sorted(rows, key=t)
    if how == "name":
        return sorted(rows, key=lambda u: u["name"].lower())
    if how == "dept":
        return sorted(rows, key=lambda u: (u["dept"].lower(), u["name"].lower()))
    return sorted(rows, key=t, reverse=True)