"""
frontend/lab_data.py - Computer Laboratory | data behind the dashboards

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
# The four laboratories drawn on the round floor-plan SVG. Laboratories added
# later (Inventory -> Add laboratory) are drawn as a seat grid instead.
MAP_LABS = (1, 4)
MAP_SEATS = 39  # computers drawn per laboratory on the floor map (seat 40+ are listed under the map)
COMPUTERS_PER_LAB = 40

# Extra details of every laboratory (name, code, building, floor, room, layout...).
# Filled by register_labs() from the shared lab store (frontend/lab_store.py).
LAB_INFO: dict[int, dict] = {
    lab: {"id": lab, "name": f"Centrum {lab}", "code": f"CL{lab}", "wing": wing,
          "building": "Centrum Building", "floor": "", "room": f"Centrum {lab}",
          "units": COMPUTERS_PER_LAB, "cols": 8, "desc": "", "builtin": True}
    for lab, wing in LABS
}

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
    "cancelled": ("Cancelled", "b-neutral"),
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
    "maint": ("Under maintenance", "b-maint"),
    "inactive": ("Inactive", "b-neutral"),
}
# The four live statuses shown on the monitoring map, in order.
LIVE_STATUSES = ("ok", "reported", "repair", "escalated")

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
    info = LAB_INFO.get(lab) if isinstance(lab, int) else None
    return (info or {}).get("name") or f"Centrum {lab}"


def lab_code(lab: int) -> str:
    info = LAB_INFO.get(lab) if isinstance(lab, int) else None
    return (info or {}).get("code") or f"CL{lab}"


def on_floor_map(lab: int) -> bool:
    """True for the laboratories drawn on the round floor-plan SVG."""
    return MAP_LABS[0] <= int(lab or 0) <= MAP_LABS[1]


def register_labs(labs: list[dict]) -> None:
    """Add/refresh laboratories (from the shared store) in LABS, WING and LAB_INFO.

    LABS / WING are changed in place, so every module that reads D.LABS sees the
    new laboratories straight away. The four built-in laboratories always stay.
    """
    for raw in labs or []:
        try:
            lab = int(raw.get("id"))
        except (TypeError, ValueError, AttributeError):
            continue
        if lab <= 0:
            continue
        info = {**LAB_INFO.get(lab, {}), **{k: v for k, v in raw.items() if v not in (None,)}}
        info["id"] = lab
        info.setdefault("name", f"Centrum {lab}")
        info.setdefault("code", f"CL{lab}")
        info["wing"] = str(info.get("wing") or info.get("building") or "")
        LAB_INFO[lab] = info
        WING[lab] = info["wing"]
    LABS[:] = sorted(WING.items())


# The laboratories built into the app (drawn on the floor map).
_BUILTIN_LABS = list(LABS)
_BUILTIN_INFO = {lab: dict(info) for lab, info in LAB_INFO.items()}


def _builtin_lab_of(room: str) -> int | None:
    """The built-in laboratory a Computers.Room belongs to, if any."""
    text = " ".join(str(room or "").split()).lower()
    if not text:
        return None
    for lab, info in _BUILTIN_INFO.items():
        for key in ("room", "name", "code"):
            if text == str(info.get(key) or "").strip().lower():
                return lab
    m = re.search(r"\d+", text)
    if m and int(m.group()) in _BUILTIN_INFO:
        return int(m.group())
    return None


# Saved details of laboratories added with "Add laboratory" (name, code,
# building, floor, seats per row...): set by lab_store. They only label a
# Room that exists in the database; a laboratory is never listed from them.
LAB_DETAILS = lambda: []  # noqa: E731


def _saved_details() -> dict[str, dict]:
    """{room (lower case): saved details}; the latest entry for a room wins."""
    out: dict[str, dict] = {}
    try:
        saved = LAB_DETAILS() or []
    except Exception:
        saved = []
    for info in saved:
        if isinstance(info, dict):
            room = " ".join(str(info.get("room") or info.get("name") or "").split()).lower()
            if room:
                out[room] = info
    return out


def register_db_labs(units) -> None:
    """The laboratories, from the database only: the built-in ones plus one
    laboratory per other Computers.Room. units: the computers (dicts with
    'room' / 'Room' and 'id' / 'ComputerId'); a room's laboratory number
    follows the order its first computer was added, so it stays the same.

    LABS / WING / LAB_INFO are rebuilt in place (every module sees them)."""
    first: dict[str, tuple[int, str]] = {}
    for u in units or []:
        if not isinstance(u, dict):
            continue
        room = " ".join(str(u.get("room") or u.get("Room") or "").split())
        if not room or _builtin_lab_of(room) is not None:
            continue
        try:
            cid = int(u.get("id") or u.get("ComputerId") or u.get("computer_id") or 0)
        except (TypeError, ValueError):
            cid = 0
        key = room.lower()
        if key not in first or cid < first[key][0]:
            first[key] = (cid, room)
    LAB_INFO.clear()
    LAB_INFO.update({lab: dict(info) for lab, info in _BUILTIN_INFO.items()})
    WING.clear()
    WING.update(dict(_BUILTIN_LABS))
    details = _saved_details()
    rooms = [room for _, room in sorted(first.values())]
    # A room added with "Add laboratory" keeps its number (asset IDs such as
    # CL5-PC01); the other rooms get the next free numbers.
    used = set(_BUILTIN_INFO)
    wanted: dict[str, int] = {}
    for room in rooms:
        try:
            n = int((details.get(room.lower()) or {}).get("id") or 0)
        except (TypeError, ValueError):
            n = 0
        if n > 0 and n not in used:
            wanted[room] = n
            used.add(n)
    for room in rooms:
        lab = wanted.get(room)
        if lab is None:
            # The lowest free number, so the numbers of the other rooms stay
            # the same when a laboratory is added.
            lab = max(_BUILTIN_INFO) + 1
            while lab in used:
                lab += 1
            used.add(lab)
        saved = details.get(room.lower()) or {}
        info = {
            "id": lab, "name": room, "code": f"CL{lab}", "wing": "", "building": "",
            "floor": "", "room": room, "units": 0, "cols": 8, "desc": "", "builtin": False,
        }
        if wanted.get(room) == lab:
            info.update({k: v for k, v in saved.items() if v not in (None, "") and k != "id"})
            info["room"] = room
        info["wing"] = str(info.get("wing") or info.get("building") or "")
        LAB_INFO[lab] = info
        WING[lab] = info["wing"]
    LABS[:] = sorted(WING.items())


def next_lab_id() -> int:
    return max([lab for lab, _ in LABS] + [0]) + 1


def asset_tag(lab: int, pc: int) -> str:
    """The unique asset ID of a computer (one per laboratory seat)."""
    return f"{lab_code(int(lab))}-PC{pad(pc)}"


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
    """Computers.Room / Reports room text -> laboratory number.

    A laboratory added in the app is matched on its room, name or code first
    (e.g. "Computer Lab A"); otherwise the first number in the text is used
    ("Centrum 3" -> 3)."""
    text = str(room or "").strip().lower()
    if text:
        for lab, info in LAB_INFO.items():
            for key in ("room", "name", "code"):
                if text == str(info.get(key) or "").strip().lower():
                    return lab
    m = re.search(r"\d+", text)
    return int(m.group()) if m else 1


def lab_room(lab: int) -> str:
    """The room text sent to the backend for a laboratory (Computers.Room)."""
    info = LAB_INFO.get(lab) or {}
    return str(info.get("room") or info.get("name") or f"Centrum {lab}")


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

# Status text from the backend -> status here. technician_service sends the
# labels "Under repair" / "Fixed" / "Follow Up"; the raw codes "resolved" /
# "followup" are accepted too. Anything else is "Under repair" once a
# technician has it, otherwise "Reported".
_LIVE_STATUS = {
    "resolved": "fixed",
    "fixed": "fixed",
    "followup": "escalated",
    "follow up": "escalated",
    "follow-up": "escalated",
    "cancelled": "cancelled",  # added
    "canceled": "cancelled",
}


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
    # Reports.UpdatedAt: set by the backend on every status change, so it is
    # when the report reached its CURRENT status. Earlier steps are not stored
    # in the database (there is no report-history table).
    changed = parse_dt(r.get("updated_at"))
    if changed and changed < created:
        changed = None
    note = str(r.get("resolution_note") or "")
    try:
        pc = int(r.get("unit_number") or 0)
    except (TypeError, ValueError):
        pc = 0
    rep = {
        "id": str(r.get("code") or r.get("id") or "—"),
        "db_id": r.get("id"),
        "computer_id": r.get("computer_id") or r.get("ComputerId"),
        "lab": lab_of(r.get("room")),
        "pc": pc,
        "issue": ", ".join(map(str, issues)) or "Other",
        # Each problem the teacher picked, kept separately.
        "issues": [str(i) for i in issues] or ["Other"],
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
    # When each step happened: Reports.UnderRepairDate / EscalatedDate /
    # FixedDate / FollowUpDate (once those columns exist); otherwise only
    # the current step's time is known (UpdatedAt).
    repair_at = parse_dt(r.get("under_repair_date"))
    escalated_at = parse_dt(r.get("escalated_date"))
    fixed_at_ = parse_dt(r.get("fixed_date"))
    follow_at = parse_dt(r.get("follow_up_date"))
    if fixed_at_:
        rep["fixed_at"] = fixed_at_  # read by fixed_at() (time to fix in Analytics)

    def step(s, note_text, when, current, label=None):
        e = {"s": s, "note": note_text}
        if label:
            e["label"] = label
        when = when or (changed if current else None)
        if when:
            e["t"] = when
        else:
            # Not stored: created is only a placeholder for sorting; it is
            # shown as "Time not recorded".
            e.update(t=created, t_unknown=True)
        rep["history"].append(e)

    if follow_at:
        # s="reported" so screens that only know the four statuses still work;
        # the label shows it as a follow-up.
        step("reported", "The teacher followed up: still waiting for a technician",
             follow_at, False, label="Follow-up")
    if (status not in ("reported", "cancelled")) or repair_at:
        step("repair", f"{handled or 'Technician'} started the repair", repair_at,
             status == "repair" and not escalated_at)
    # The Admin's decisions on escalations (ReportDecisions table), oldest first.
    decisions = [d for d in r.get("admin_decisions") or [] if isinstance(d, dict)]
    last = decisions[-1] if decisions else {}
    decision = str(last.get("decision") or "")
    decided_at = parse_dt(last.get("decided_at"))
    resolved_by_admin = decision == "resolve"

    if status == "escalated" or escalated_at:
        # ResolutionNote still holds the technician's escalation reason while
        # the report is escalated, and after an admin decision until the
        # technician writes a new note (marks it fixed).
        reason_kept = status == "escalated" or (
            decision and (resolved_by_admin or status == "repair")
        )
        step("escalated", note if reason_kept and note else "Escalated to the admin",
             escalated_at, status == "escalated")
    labels = {
        "approve": ("repair", "Replacement approved"),
        "resolve": ("fixed", "Resolved by the admin"),
        "send_back": ("repair", "Sent back to the technician"),
    }
    for d in decisions:
        kind, label = labels.get(str(d.get("decision")), ("repair", "Admin decision"))
        step(kind, str(d.get("note") or label), parse_dt(d.get("decided_at")), False, label=label)

    if status == "cancelled":
        step("cancelled", "Cancelled by the teacher", None, True)
  
    if status == "fixed" and not (resolved_by_admin and (not fixed_at_ or fixed_at_ == decided_at)):
        # (when the admin resolved it, the decision above is the "fixed" step)
        step("fixed", note or STATUS["fixed"][0], fixed_at_, True)
    # Steps in the order they happened (unknown times keep their place).
    first = rep["history"][0]
    known = sorted((e for e in rep["history"][1:] if not e.get("t_unknown")), key=lambda e: e["t"])
    ordered, it = [first], iter(known)
    for e in rep["history"][1:]:
        ordered.append(e if e.get("t_unknown") else next(it))
    rep["history"] = ordered
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
        # Computers.Status as stored (computer_status enum).
        "status": str(status or "").strip() or "Working",
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
    register_db_labs(units)
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
        sw_raw = u.get("software_rows") or u.get("software") or []
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
                        # ComputerSoftware.SoftwareId (update / remove it).
                        "id": item.get("id"),
                    }
                )
        comps[(lab, pc)] = new_computer(
            lab,
            pc,
            {str(k): str(v) for k, v in hw.items()},
            sw,
            name=str(u.get("name") or ""),
            added=parse_dt(u.get("date_added")) or parse_dt(u.get("created_at")),
            brand=str(u.get("brand") or ""),
            model=str(u.get("model") or ""),
            serial=str(u.get("serial") or ""),
            status=str(u.get("record_status") or "Working"),
        )
        # Maintenance history from MaintenanceHistory.
        comps[(lab, pc)]["log"] = [
            {
                "t": parse_dt(e.get("t")) or parse_dt(u.get("created_at")) or now(),
                "kind": str(e.get("kind") or "Maintenance"),
                "text": str(e.get("text") or ""),
                "by": str(e.get("by") or "Staff"),
            }
            for e in u.get("maintenance") or []
            if isinstance(e, dict)
        ]
        comps[(lab, pc)]["last_serviced"] = parse_dt(u.get("last_serviced"))
        comps[(lab, pc)]["updated"] = parse_dt(u.get("updated_at"))
        # Computers.ComputerId, shown as "Computer ID" (e.g. in Analytics).
        comps[(lab, pc)]["db_id"] = u.get("id") or u.get("computer_id") or u.get("ComputerId")
        # Computers.Room as stored (Add laboratory checks new rooms against it).
        comps[(lab, pc)]["room"] = str(u.get("room") or "")
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


_REQ_STATUS.update({"inactive": "inactive", "deactivated": "inactive",
                    "disabled": "inactive", "suspended": "inactive"})


def _field(r: dict, *names):
    """The first non-empty value among several possible column names
    (snake_case from the API, or PascalCase straight from Supabase)."""
    lowered = {str(k).lower(): v for k, v in r.items()}
    for n in names:
        v = lowered.get(n.lower())
        if isinstance(v, dict):
            v = v.get("name") or v.get("Name") or v.get("role_name") or v.get("RoleName")
        if v not in (None, ""):
            return v
    return None


def split_name(full: str) -> tuple[str, str]:
    parts = str(full or "").split()
    if not parts:
        return "", ""
    return " ".join(parts[:-1]) if len(parts) > 1 else parts[0], parts[-1] if len(parts) > 1 else ""


def request_from_backend(r: dict) -> dict:
    """A Users row (account request or account) -> the dict the screens use.

    first / last name are kept separate; the dates of creation, confirmation
    (activation), cancellation and deactivation are read when the backend sends
    them (several column spellings are accepted)."""
    first = str(_field(r, "first_name", "firstname", "FirstName") or "").strip()
    last = str(_field(r, "last_name", "lastname", "LastName") or "").strip()
    full = str(_field(r, "full_name", "fullname", "name") or "").strip()
    if not (first or last) and full:
        first, last = split_name(full)
    name = f"{first} {last}".strip() or full
    email = str(_field(r, "email", "Email") or "")
    status_raw = str(_field(r, "status", "Status", "account_status") or "").lower()
    st = _REQ_STATUS.get(status_raw, "pending" if not status_raw else status_raw)
    created = parse_dt(_field(r, "created_at", "CreatedAt", "date_created", "submitted_at"))
    # Users."DateConfirmed" only (nullable). Never taken from CreatedAt,
    # UpdatedAt or any other timestamp; NULL stays None and shows as "—".
    confirmed = parse_dt(_field(r, "date_confirmed", "DateConfirmed"))
    cancelled = parse_dt(_field(r, "cancelled_at", "canceled_at", "CancelledAt",
                                "rejected_at", "RejectedAt"))
    deactivated = parse_dt(_field(r, "deactivated_at", "DeactivatedAt", "disabled_at"))
    modified = parse_dt(_field(r, "updated_at", "UpdatedAt", "modified_at", "date_modified", "ModifiedAt"))
    decided = parse_dt(_field(r, "decided_at", "DecidedAt", "updated_status_at"))
    if decided and not cancelled and st == "rejected":
        cancelled = decided
    return {
        "id": _field(r, "id", "user_id", "UserId"),
        "first": first,
        "last": last,
        "name": str(name or email or "Unknown"),
        "email": email,
        "phone": str(_field(r, "contact_number", "ContactNumber", "phone") or ""),
        "dept": str(_field(r, "department", "Department") or ""),
        "role": str(_field(r, "role", "role_name", "Role") or "").title(),
        "t": created,
        "created": created,
        "st": st,
        "confirmed": confirmed,
        "cancelled": cancelled,
        "deactivated": deactivated,
        "modified": modified,
        "done": decided or confirmed or cancelled,
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
        # Laboratories come from the database rooms (before reports are mapped).
        register_db_labs(lab.get("units") or [])
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
        # Admin requests are listed too, so more than one Admin can be confirmed.
        store["requests"] = [
            request_from_backend(r)
            for r in result["requests"]
            if isinstance(r, dict)
            and str(r.get("role") or "").lower()
            in ("teacher", "technician", "admin", "administrator")
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
    # Laboratories come from the database rooms (before reports are mapped).
    register_db_labs(result.get("units") or [])
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


def _report_index(store: dict) -> dict:
    """{(lab, pc): [reports]} for the store's reports, built once.

    Speed: pc_report() / pc_reports() used to scan EVERY report for each call,
    and drawing the live map calls them several times for each of its ~156
    computers on every click. The index holds the same report dicts (not
    copies), so a status change made in place is seen at once; it is rebuilt
    when the reports list is replaced (refresh, attach) or its length changes
    (a report added or removed)."""
    reports = store.get("reports") or []
    cached = store.get("_ridx")
    if cached is not None and cached[0] is reports and cached[1] == len(reports):
        return cached[2]
    by_pc: dict = {}
    for r in reports:
        by_pc.setdefault((r.get("lab"), r.get("pc")), []).append(r)
    store["_ridx"] = (reports, len(reports), by_pc)
    return by_pc


def pc_report(store: dict, lab: int, pc: int) -> dict | None:
    mine = [r for r in _report_index(store).get((lab, pc), ()) if r["status"] in OPEN]
    return max(mine, key=lambda r: r["created"]) if mine else None


def pc_reports(store: dict, lab: int, pc: int) -> list[dict]:
    """Every report for one computer, each one separately: open reports first,
    then closed ones; newest first within each group."""
    mine = _report_index(store).get((lab, pc), [])
    return sorted(
        mine,
        key=lambda r: (
            r.get("status") not in OPEN,
            -(r["created"].timestamp() if r.get("created") else 0),
        ),
    )


def report_issues(r: dict) -> list[str]:
    """The separate problems of one report (a teacher can pick several)."""
    raw = r.get("issues")
    if isinstance(raw, (list, tuple)):
        items = [str(x).strip() for x in raw if str(x).strip()]
    else:
        items = [x.strip() for x in str(r.get("issue") or "").split(",") if x.strip()]
    return items or [str(r.get("issue") or "Other")]


def problem_rows(reports: list[dict]) -> list[dict]:
    """One row per problem per computer: a report with two problems becomes two
    rows. Each row is a copy of its report with "issue" set to that one problem,
    plus part / parts ("problem 1 of 2") and a unique row_key. The report's id,
    status, technician and history are shared, because the database keeps one
    status per report."""
    out = []
    for r in reports or []:
        items = report_issues(r)
        for i, issue in enumerate(items, 1):
            out.append(
                {**r, "issue": issue, "part": i, "parts": len(items),
                 "row_key": f"{r.get('id')}_{i}"}
            )
    return out


def pc_problem_rows(store: dict, lab: int, pc: int) -> list[dict]:
    """One computer's reports as problem rows - the same rows the Reports
    page shows (a report with two problems is two entries)."""
    return problem_rows(pc_reports(store, lab, pc))


def find_problem_row(reports: list[dict], ref) -> dict | None:
    """The problem row for `ref`: a row_key from the Reports page (e.g.
    "CL-0023_2"), or a plain report id (then its first problem)."""
    rows = problem_rows(reports)
    ref = str(ref)
    return next((r for r in rows if r["row_key"] == ref), None) or next(
        (r for r in rows if str(r.get("id")) == ref), None
    )


def open_report_counts(store: dict) -> dict:
    """{(lab, pc): number of open reports} - to mark computers with several."""
    counts: dict = {}
    for r in store.get("reports") or []:
        if r.get("status") in OPEN:
            key = (r.get("lab"), r.get("pc"))
            counts[key] = counts.get(key, 0) + 1
    return counts


def pc_status(store: dict, lab: int, pc: int) -> str:
    """ok / reported / repair / escalated (open report) / maint / inactive (record status)."""
    r = pc_report(store, lab, pc)
    if r:
        return r["status"]
    comp = store["computers"].get((lab, pc))
    rec = str((comp or {}).get("status") or "Working").strip().lower()
    return (
        "maint"
        if "maint" in rec
        else "inactive" if "inactive" in rec else "ok"
    )


def lab_computers(store: dict, lab: int) -> list[dict]:
    return sorted(
        (c for c in store["computers"].values() if c["lab"] == lab),
        key=lambda c: c["pc"],
    )


def lab_summary(store: dict, lab: int) -> dict:
    """Counts for a laboratory. Inactive computers are not part of the total.

    "repair" counts every computer that is not usable because it is being
    worked on (under repair, escalated or under maintenance) - the older
    screens read it that way. "under_repair", "escalated" and "maint" split it.
    """
    s = {"total": 0, "ok": 0, "reported": 0, "repair": 0, "under_repair": 0,
         "escalated": 0, "maint": 0, "inactive": 0, "all": 0}
    for c in lab_computers(store, lab):
        st = pc_status(store, lab, c["pc"])
        s["all"] += 1
        if st == "inactive":
            s["inactive"] += 1
            continue
        s["total"] += 1
        if st == "ok":
            s["ok"] += 1
        elif st == "reported":
            s["reported"] += 1
        else:
            s["repair"] += 1
            s[{"repair": "under_repair", "escalated": "escalated"}.get(st, "maint")] += 1
    return s


def report_counts(reports: list[dict], lab: int | None = None,
                  since: datetime | None = None, match=None) -> dict:
    """How many reports are new, under repair, escalated and fixed (optionally
    for one laboratory and only reports sent since a date)."""
    out = {"reported": 0, "repair": 0, "escalated": 0, "fixed": 0, "total": 0}
    for r in reports or []:
        if lab and r.get("lab") != lab:
            continue
        created = r.get("created")
        if since and (not created or created < since):
            continue
        if match is not None and not match(created):
            continue
        st = r.get("status")
        if st in out:
            out[st] += 1
        out["total"] += 1
    return out


def lab_breakdown(store: dict, labs: list[int] | None = None,
                  since: datetime | None = None, match=None) -> list[dict]:
    """One row per laboratory: computers, working units and report counts."""
    rows = []
    for lab in labs or [l for l, _ in LABS]:
        sm = lab_summary(store, lab)
        rc = report_counts(store.get("reports") or [], lab, since, match)
        rows.append({"lab": lab, "name": lab_name(lab), "wing": WING.get(lab, ""),
                     **{f"pc_{k}": v for k, v in sm.items()},
                     **{f"r_{k}": v for k, v in rc.items()}})
    return rows


def most_reported(store: dict, lab: int | None = None,
                  since: datetime | None = None, match=None) -> list[dict]:
    """Computers ranked by how many issue reports they received (most first;
    ties: the most recently reported first). Uses the store's reports, i.e.
    the Reports records loaded from the database."""
    groups: dict = {}
    for r in store.get("reports") or []:
        if lab and r.get("lab") != lab:
            continue
        created = r.get("created")
        if since and (not created or created < since):
            continue
        if match is not None and not match(created):
            continue
        key = (r.get("lab"), r.get("pc"))
        if not key[1]:
            continue
        g = groups.setdefault(key, {"reports": [], "computer_id": None})
        g["reports"].append(r)
        g["computer_id"] = g["computer_id"] or r.get("computer_id")
    rows = []
    for (lab_, pc), g in groups.items():
        comp = (store.get("computers") or {}).get((lab_, pc)) or {}
        reps = g["reports"]
        issues: dict = {}
        for r in reps:
            for part in str(r.get("issue") or "Other").split(","):
                part = part.strip() or "Other"
                issues[part] = issues.get(part, 0) + 1
        rows.append({
            "lab": lab_,
            "pc": pc,
            "db_id": comp.get("db_id") or g["computer_id"],
            "tag": comp.get("tag") or asset_tag(lab_, pc),
            "name": comp.get("name") or asset_tag(lab_, pc),
            "total": len(reps),
            "open": sum(r.get("status") in OPEN for r in reps),
            "fixed": sum(r.get("status") == "fixed" for r in reps),
            "last": max((r.get("created") for r in reps if r.get("created")), default=None),
            "top_issue": max(issues.items(), key=lambda x: x[1])[0] if issues else "—",
            "status": pc_status(store, lab_, pc) if comp else None,
        })
    rows.sort(key=lambda x: (-x["total"], -(x["last"].timestamp() if x["last"] else 0)))
    for i, x in enumerate(rows, 1):
        x["rank"] = i
    return rows


def last_serviced(store: dict, comp: dict) -> datetime | None:
    times = [e["t"] for e in maintenance_history(store, comp)]
    if comp.get("last_serviced"):
        times.append(comp["last_serviced"])
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
    "cancelled": 7,
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
    "name": "First name (A–Z)",
    "last": "Last name (A–Z)",
    "dept": "Department",
}
USER_SORTS = {
    "modified": "Date modified (newest)",
    "last": "Last name (A–Z)",
    "name": "First name (A–Z)",
    "new": "Date created (newest)",
    "old": "Date created (oldest)",
    "role": "Role",
    "status": "Status",
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
        return sorted(rows, key=lambda u: (u.get("first") or u["name"]).lower())
    if how == "last":
        return sorted(rows, key=lambda u: ((u.get("last") or "").lower(), (u.get("first") or "").lower()))
    if how == "modified":
        return sorted(rows, key=lambda u: u.get("modified") or u.get("created") or datetime.min, reverse=True)
    if how == "role":
        return sorted(rows, key=lambda u: (u.get("role", "").lower(), (u.get("last") or "").lower()))
    if how == "status":
        return sorted(rows, key=lambda u: (u.get("st", ""), (u.get("last") or "").lower()))
    if how == "dept":
        return sorted(rows, key=lambda u: (u["dept"].lower(), u["name"].lower()))
    return sorted(rows, key=t, reverse=True)
