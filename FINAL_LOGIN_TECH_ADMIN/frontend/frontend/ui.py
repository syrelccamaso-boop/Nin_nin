"""
frontend/ui.py - Centrum Laboratory | shared dashboard building blocks (Streamlit)

The dashboards keep the look of the original HTML design: the same sidebar,
topbar, cards, pills, tables, drawer, tabs and buttons, using the design's own
stylesheet (frontend/design.py). Display pieces are drawn with st.html using
the design's class names; everything you can click or type in is a real
Streamlit widget (buttons, text inputs, selects, toggles) dressed in that CSS.
No .html files, iframes or JavaScript are used.

    - who is signed in (normalize_user, require_user, logout_user)
    - sample data (used by --preview, or when the backend can't be reached)
    - Lab: rooms, units, unit status and unit details, built from sample data
      or from the backend's Computers + Reports rows
    - page pieces: shell (sidebar + topbar), stat cards, recent activity, room at
      a glance, reports table + report drawer, unit inventory, error analytics,
      escalation, settings

How the styling hooks work
--------------------------
- btn(label, key, kind): a st.button whose key carries a marker such as
  "__primary__" or "__ghostsm__"; the CSS styles it like .btn-primary etc.
- box(key, "card", "section", ...): a st.container whose key carries markers
  that give it the look/layout of a design block (card, row, drawer, ...).
- hit(markup, key, on_click): a design element (nav item, table row, unit
  card...) with an invisible button stretched over it, so the whole element
  is clickable, just like in the HTML version.

Needs Streamlit 1.39 or newer (keyed containers).
This file has no database, authentication or email code. The dashboards pass
in functions that call frontend/backend_client.py when something must be saved.
"""

from __future__ import annotations

import copy
import html as _html
import re
from datetime import datetime
from pathlib import Path

import streamlit as st

ss = st.session_state



FRONTEND_DIR = Path(__file__).resolve().parent
PROJECT_DIR = FRONTEND_DIR.parent


# ---------------------------------------------------------------------------
# Brand files (optional): assets/logo.png, assets/logo-icon.png, ...
# Looked for in <project>/assets first, then frontend/assets.
# ---------------------------------------------------------------------------
def asset(name: str) -> Path | None:
    for folder in (PROJECT_DIR / "assets", FRONTEND_DIR / "assets"):
        if (folder / name).is_file():
            return folder / name
    return None


@st.cache_data(show_spinner=False)
def _data_uri(path: str, mtime: float) -> str:
    import base64
    import mimetypes

    mime = mimetypes.guess_type(path)[0] or "image/png"
    return f"data:{mime};base64," + base64.b64encode(Path(path).read_bytes()).decode()


def asset_uri(name: str) -> str | None:
    path = asset(name)
    return _data_uri(str(path), path.stat().st_mtime) if path else None


def page_icon():
    """assets/logo-icon.png as the browser-tab icon (a monitor emoji if it's missing)."""
    path = asset("logo-icon.png")
    return str(path) if path else "\U0001f5a5\ufe0f"

# Where a login script may have stored the signed-in user, and the access token.
SESSION_KEYS = ("user", "auth_user", "current_user")
TOKEN_KEY = "auth_token"

# Session-state prefixes owned by the dashboards (cleared on log out).
DASHBOARD_PREFIXES = ("tech_", "admin_", "teacher_", "_keep_")


# ===========================================================================
# Who is signed in
# ===========================================================================
_FIELDS = {
    "first": ("first_name", "firstname"),
    "last": ("last_name", "lastname"),
    "full": ("full_name", "fullname", "name"),
    "email": ("email",),
    "phone": ("contact_number", "contactnumber", "contact", "phone", "phonenumber"),
    "role": ("role",),
}


def _pick(raw: dict, names: tuple[str, ...]) -> str:
    lowered = {str(k).lower(): v for k, v in raw.items()}
    for name in names:
        value = lowered.get(name)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def normalize_user(raw: dict) -> dict:
    """Turn a user row/dict from any login into {name, email, contact_number, role}."""
    first, last = _pick(raw, _FIELDS["first"]), _pick(raw, _FIELDS["last"])
    email = _pick(raw, _FIELDS["email"])
    name = _pick(raw, _FIELDS["full"]) or f"{first} {last}".strip() or email.split("@")[0]
    return {
        "name": name or "User",
        "email": email,
        "contact_number": _pick(raw, _FIELDS["phone"]),
        "role": _pick(raw, _FIELDS["role"]),
    }


def session_user() -> dict | None:
    for key in SESSION_KEYS:
        raw = ss.get(key)
        if isinstance(raw, dict) and raw:
            return normalize_user(raw)
    return None


def initials(name: str) -> str:
    words = (name or "").split()
    return ("".join(w[0] for w in words[:2]) or "?").upper()


def require_user(user: dict | None, role: str, allowed: tuple[str, ...]) -> dict:
    """The normalized user, or a message + st.stop() when they may not see this page."""
    user = normalize_user(user) if user else session_user()
    if user is None:
        st.warning("You're not signed in. Please log in first.")
        st.stop()
    if user["role"].lower() not in allowed:
        st.error(
            f"This page is for {role.lower()}s only (you're signed in as "
            f"{user['role'] or 'an unknown role'})."
        )
        st.stop()
    return user


def set_contact_number(number: str) -> None:
    """Keep the signed-in user in sync so a new number shows right away."""
    for key in SESSION_KEYS:
        if isinstance(ss.get(key), dict):
            ss[key]["contact_number"] = number


def logout_user() -> None:
    """Forget the user and the dashboard state; the app shows its login screen again."""
    for key in list(ss.keys()):
        if key in SESSION_KEYS or key == TOKEN_KEY or str(key).startswith(DASHBOARD_PREFIXES):
            ss.pop(key, None)
    ss["authenticated"] = False  # NewLogin.py-style login
    ss["page"] = "login"  # Supabase-style login
    ss["auth_view"] = "login"
    ss["cl_view"] = "auth"
    ss["cl_logged_out"] = True


def preview_logged_out() -> None:
    """In `--preview` mode, show a small 'logged out' screen after Log out."""
    if ss.get("cl_logged_out"):
        st.info("Logged out (preview).")
        if st.button("Back to preview"):
            ss["cl_logged_out"] = False
            st.rerun()
        st.stop()


# ===========================================================================
# Small helpers
# ===========================================================================
def esc(text) -> str:
    """Escape text so it shows literally inside st.markdown."""
    return re.sub(r"([\\`*_\[\]<>#~|$])", r"\\\1", str(text or ""))


def natural_key(text: str):
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", str(text))]


def room_label(room: str) -> str:
    """'CL 1' -> 'Centrum Laboratory 1'."""
    return re.sub(r"^CL\s*", "Centrum Laboratory ", str(room), flags=re.I)


def unit_label(n: int) -> str:
    return f"Unit {int(n):02d}"


def unit_key(room: str, n: int) -> str:
    return f"{room}-{int(n):02d}"


def split_key(key: str) -> tuple[str, int]:
    room, num = key.rsplit("-", 1)
    return room, int(num)


def _int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def fmt_dt(dt: datetime | None) -> str:
    """'Aug 21, 2026 · 8:19 AM'"""
    if not dt:
        return "—"
    return f"{dt:%b %d, %Y} · {int(dt.strftime('%I'))}:{dt:%M %p}"




def parse_dt(value) -> datetime | None:
    """ISO text from the backend -> local, naive datetime (None if it can't be read)."""
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.astimezone().replace(tzinfo=None) if dt.tzinfo else dt


def flash(prefix: str, message: str, ok: bool = True) -> None:
    """Queue a toast; it is shown on the next run (callbacks run before the page)."""
    ss.setdefault(f"{prefix}_flash", []).append((str(message or ""), "✅" if ok else "⚠️"))


def show_flash(prefix: str) -> None:
    for message, icon in ss.pop(f"{prefix}_flash", []):
        if message:
            st.toast(message, icon=icon)


def sticky(key: str, options: list | None = None):
    """Keep a widget's value while it is hidden (Streamlit forgets hidden widgets).

    Use as `st.radio(..., key=sticky("k", opts))` and call remember("k") after it.
    """
    store = "_keep_" + key
    if key not in ss and store in ss:
        ss[key] = ss[store]
    if options is not None and key in ss and ss[key] not in options:
        ss.pop(key)
    return key


def remember(key: str) -> None:
    ss["_keep_" + key] = ss.get(key)


def set_sticky(key: str, value) -> None:
    ss[key] = value
    ss["_keep_" + key] = value


# ===========================================================================
# Sample data (same as the original design files)
# ===========================================================================
ISSUE_TYPES = [
    "Won't turn on", "Slow performance", "No internet", "Blue screen (BSOD)",
    "Missing keyboard", "Missing mouse", "Monitor issue", "Software error",
]

SAMPLE_ROOMS = ["CL 1", "CL 2", "CL 3", "CL 4"]
SAMPLE_COUNTS = {"CL 1": 35, "CL 2": 28, "CL 3": 30, "CL 4": 32}
_CL1_STATUS = {2: "issue", 10: "issue", 12: "issue", 15: "replace"}
_EXTRA_STATUS = {"CL 2": {19: "issue", 7: "issue"}, "CL 3": {7: "replace", 3: "issue"}, "CL 4": {11: "issue"}}

_HW_I5 = {"Processor": "Intel Core i5-10400 @ 2.90GHz", "RAM": "8 GB DDR4", "Storage": "256 GB SSD",
          "GPU": "Intel UHD 630", "Monitor": '19" LED', "Peripherals": "Keyboard, Mouse"}
_HW_I3 = {"Processor": "Intel Core i3-10100 @ 3.60GHz", "RAM": "8 GB DDR4", "Storage": "256 GB SSD",
          "GPU": "Intel UHD 630", "Monitor": '19" LED', "Peripherals": "Keyboard, Mouse"}
_HW_OLD = {"Processor": "Intel Core i3-8100 @ 3.60GHz", "RAM": "4 GB DDR4", "Storage": "128 GB SSD",
           "GPU": "Intel UHD 630", "Monitor": '19" LED', "Peripherals": "Keyboard, Mouse"}
_LIFE = {"Deployed": "June 2023", "Warranty": "Expired Jun 2025", "Age": "3 yrs 3 mo", "Flag": "None"}
_LIFE_OLD = {"Deployed": "Jan 2020", "Warranty": "Expired Jan 2022", "Age": "6 yrs 8 mo", "Flag": "Needs replacement"}


def _h(date, issue, comment, action, status):
    return {"date": date, "issue": issue, "comment": comment, "action": action, "status": status}


SAMPLE_UNIT_DETAILS = {
    "CL 1-02": {
        "hardware": _HW_I5,
        "software": [("Windows 10 Pro", "Licensed — up to date"), ("Google Chrome", "v128 — up to date"),
                     ("Microsoft Office 2019", "Licensed"), ("VS Code", "v1.92"), ("Antivirus (Defender)", "Active")],
        "system": {"OS build": "19045.4780", "Last update check": "Aug 20, 2026", "Domain": "CCSICT-LAB",
                   "Asset tag": "CL1-U02", "IP address": "192.168.14.32"},
        "lifecycle": _LIFE,
        "history": [
            _h("Aug 21, 2026 · 8:19 AM", "Slow performance", "Takes almost 5 minutes to boot and opens apps slowly.",
               "Cleared temp files and disabled unnecessary startup apps. Ran disk cleanup.", "progress"),
            _h("May 03, 2026 · 1:40 PM", "Slow performance", "Laggy during video playback.",
               "Updated GPU driver and added 4GB RAM stick.", "resolved"),
            _h("Jan 14, 2026 · 10:02 AM", "Software error", "Office kept crashing when saving files.",
               "Reinstalled Microsoft Office and applied latest patch.", "resolved"),
        ],
    },
    "CL 1-10": {
        "hardware": _HW_I5,
        "software": [("Windows 10 Pro", "Licensed — up to date"), ("Google Chrome", "v127 — update available"),
                     ("Microsoft Office 2019", "Licensed")],
        "system": {"OS build": "19045.4780", "Last update check": "Jul 30, 2026", "Domain": "CCSICT-LAB",
                   "Asset tag": "CL1-U10", "IP address": "192.168.14.40"},
        "lifecycle": _LIFE,
        "history": [
            _h("Aug 18, 2026 · 11:09 AM", "No internet", "Ethernet connected but no internet access shown.",
               "Checking network switch port.", "progress"),
            _h("Mar 02, 2026 · 9:15 AM", "No internet", "Same issue as before, keeps disconnecting.",
               "Replaced LAN cable and reset network adapter.", "resolved"),
        ],
    },
    "CL 1-12": {
        "hardware": _HW_I3,
        "software": [("Windows 10 Pro", "Licensed — up to date"), ("Google Chrome", "v128 — up to date")],
        "system": {"OS build": "19045.4780", "Last update check": "Aug 10, 2026", "Domain": "CCSICT-LAB",
                   "Asset tag": "CL1-U12", "IP address": "192.168.14.42"},
        "lifecycle": _LIFE,
        "history": [_h("Jul 30, 2026 · 2:05 PM", "Missing mouse", "Mouse is gone from the unit.",
                       "Replacement mouse issued from stock.", "resolved")],
    },
    "CL 1-15": {
        "hardware": dict(_HW_OLD, Monitor='19" LED (flickering)'),
        "software": [("Windows 10 Pro", "Licensed — outdated"), ("Google Chrome", "v119 — outdated")],
        "system": {"OS build": "19044.3086", "Last update check": "Feb 2, 2026", "Domain": "CCSICT-LAB",
                   "Asset tag": "CL1-U15", "IP address": "192.168.14.45"},
        "lifecycle": _LIFE_OLD,
        "history": [
            _h("Jul 01, 2026 · 10:05 AM", "Won't turn on", "No response even when plugged directly to outlet.",
               "Diagnosed failing PSU. 5th report on this unit — flagged for full inspection.", "followup"),
            _h("Apr 22, 2026 · 9:00 AM", "Won't turn on", "Powers on then shuts off after a few seconds.",
               "Cleaned dust from internals, reseated RAM.", "resolved"),
            _h("Feb 11, 2026 · 8:45 AM", "Slow performance", "Very slow to load anything.",
               "Ran malware scan, cleared disk space.", "resolved"),
            _h("Nov 06, 2025 · 1:20 PM", "Monitor issue", "Screen flickers on and off.", "Replaced VGA cable.", "resolved"),
            _h("Sep 15, 2025 · 10:30 AM", "Won't turn on", "Had to restart twice before it booted.",
               "Checked power supply, temporary fix applied.", "resolved"),
        ],
    },
    "CL 2-19": {
        "hardware": _HW_I3,
        "software": [("Windows 10 Pro", "Licensed — up to date"), ("Google Chrome", "v128 — up to date")],
        "system": {"OS build": "19045.4780", "Last update check": "Aug 5, 2026", "Domain": "CCSICT-LAB",
                   "Asset tag": "CL2-U19", "IP address": "192.168.15.29"},
        "lifecycle": {"Deployed": "Aug 2022", "Warranty": "Expired Aug 2024", "Age": "4 yrs 1 mo", "Flag": "None"},
        "history": [
            _h("Sep 10, 2026 · 9:20 AM", "No internet", "Wifi keeps dropping every few minutes.",
               "Reviewing network switch — 5th report on this unit, flagged for inspection.", "followup"),
            _h("Jul 22, 2026 · 10:00 AM", "No internet", "Can't connect at all.", "Reset network adapter.", "resolved"),
            _h("Jun 03, 2026 · 8:40 AM", "No internet", "Slow connection all period.", "Updated network driver.", "resolved"),
            _h("Apr 18, 2026 · 1:15 PM", "No internet", "Drops mid-class.", "Swapped ethernet cable.", "resolved"),
            _h("Feb 27, 2026 · 9:05 AM", "No internet", "No connection at startup.",
               "Restarted router, temporary fix.", "resolved"),
        ],
    },
    "CL 3-07": {
        "hardware": _HW_OLD,
        "software": [("Windows 10 Pro", "Licensed — outdated"), ("Google Chrome", "v121 — outdated")],
        "system": {"OS build": "19044.3086", "Last update check": "Mar 2026", "Domain": "CCSICT-LAB",
                   "Asset tag": "CL3-U07", "IP address": "192.168.16.17"},
        "lifecycle": _LIFE_OLD,
        "history": [
            _h("Sep 12, 2026 · 10:40 AM", "Won't turn on", "Powers on then immediately shuts off.",
               "Suspected failing PSU — 5th report, flagged for full inspection.", "followup"),
            _h("Jul 05, 2026 · 9:30 AM", "Won't turn on", "Had to jiggle the power cable to boot.",
               "Replaced power cable.", "resolved"),
            _h("May 14, 2026 · 1:00 PM", "Slow performance", "Very slow to open anything.", "Cleared disk space.", "resolved"),
            _h("Mar 02, 2026 · 8:50 AM", "Won't turn on", "Took 3 tries to power on.",
               "Cleaned internals, reseated components.", "resolved"),
            _h("Dec 11, 2025 · 10:10 AM", "Monitor issue", "Screen goes black randomly.", "Replaced VGA cable.", "resolved"),
        ],
    },
}


def sample_status(room: str, n: int) -> str:
    if room == "CL 1" and n in _CL1_STATUS:
        return _CL1_STATUS[n]
    if n in _EXTRA_STATUS.get(room, {}):
        return _EXTRA_STATUS[room][n]
    seed = ((ord(room[3]) if len(room) > 3 else 0) + n * 7) % 23
    return "issue" if seed == 3 else "replace" if seed == 11 else "good"


def sample_default_detail(room: str, n: int, status: str) -> dict:
    return {
        "hardware": dict(_HW_I3),
        "software": [("Windows 10 Pro", "Licensed — up to date"), ("Google Chrome", "v128 — up to date"),
                     ("Microsoft Office 2019", "Licensed")],
        "system": {"OS build": "19045.4780", "Last update check": "Aug 2026", "Domain": "CCSICT-LAB",
                   "Asset tag": f"{room.replace(' ', '')}-U{n:02d}", "IP address": f"192.168.14.{20 + n}"},
        "lifecycle": dict(_LIFE, Flag="Needs replacement" if status == "replace" else "None"),
        "history": [] if status == "good" else [
            _h("Jun 2026", "General issue", "", "Logged and pending review.",
               "followup" if status == "replace" else "progress")],
    }


def _empty_detail(room: str, n: int, status: str) -> dict:
    return {"hardware": {"Hardware": "Not recorded yet"}, "software": [("Software", "Not recorded yet")],
            "system": {"System": "Not recorded yet"}, "lifecycle": {"Lifecycle": "Not recorded yet"}, "history": []}


def make_report(code, teacher, room, unit, issues, comment, status, note, when, db_id=None, handled_by=""):
    return {"id": code, "db_id": db_id if db_id is not None else code, "teacher": teacher, "room": room,
            "unit": int(unit), "issues": list(issues), "comment": comment, "status": status, "note": note,
            "handled_by": handled_by, "when": when, "date": fmt_dt(when)}


def sample_reports() -> list[dict]:
    """All reports (technician)."""
    d = datetime
    return [
        make_report("CL-1032", "Alwyna Lopez", "CL 1", 2, ["Slow performance"], "Takes almost 5 minutes to boot and opens apps slowly.", "progress", "", d(2026, 8, 21, 8, 19)),
        make_report("CL-1033", "Ronel Castillo", "CL 2", 2, ["No internet"], "Ethernet connected but no internet access shown.", "progress", "", d(2026, 8, 18, 11, 9)),
        make_report("CL-1034", "Alwyna Lopez", "CL 1", 3, ["Won't turn on"], "No response even when plugged directly to outlet.", "progress", "", d(2026, 7, 1, 10, 5)),
        make_report("CL-1035", "Mika Reyes", "CL 3", 7, ["Won't turn on"], "Powers on then immediately shuts off.", "followup", "Suspected failing PSU. This is the 5th report on this unit — flagged for full inspection instead of another quick fix.", d(2026, 9, 12, 10, 40)),
        make_report("CL-1036", "Ronel Castillo", "CL 2", 19, ["No internet"], "Wifi keeps dropping every few minutes.", "followup", "Reviewed the network switch port. 5th report on this unit — flagged for inspection.", d(2026, 9, 10, 9, 20)),
        make_report("CL-1037", "Dario Fajardo", "CL 4", 11, ["Software error"], "Excel crashes when opening large files.", "progress", "", d(2026, 9, 8, 13, 15)),
        make_report("CL-1038", "Mika Reyes", "CL 3", 3, ["Missing keyboard"], "Keyboard is missing entirely.", "progress", "", d(2026, 9, 5, 9, 0)),
        make_report("CL-1028", "Alwyna Lopez", "CL 1", 12, ["Missing mouse"], "Mouse is gone from the unit.", "resolved", "Replacement mouse issued from stock.", d(2026, 7, 30, 14, 5)),
        make_report("CL-1029", "Ronel Castillo", "CL 2", 5, ["Monitor issue"], "Screen has a faint horizontal line.", "resolved", "Replaced the VGA cable.", d(2026, 7, 22, 10, 0)),
        make_report("CL-1030", "Dario Fajardo", "CL 4", 8, ["Slow performance"], "Slow to load browser.", "resolved", "Cleared cache and temp files, disabled startup bloat.", d(2026, 7, 15, 9, 30)),
        make_report("CL-1031", "Mika Reyes", "CL 3", 14, ["Software error"], "Word won't open.", "resolved", "Repaired the Office installation.", d(2026, 7, 10, 8, 45)),
        make_report("CL-1025", "Alwyna Lopez", "CL 1", 10, ["No internet"], "Same issue as before, keeps disconnecting.", "resolved", "Replaced LAN cable and reset the network adapter.", d(2026, 3, 2, 9, 15)),
    ]


def sample_teacher_reports(name: str) -> list[dict]:
    """The signed-in teacher's own reports (teacher preview)."""
    d = datetime
    rows = [
        ("CL-1039", "CL 3", 3, ["Won't turn on"], "followup", d(2026, 7, 1, 10, 5)),
        ("CL-1040", "CL 2", 2, ["No internet"], "progress", d(2026, 8, 18, 11, 9)),
        ("CL-1041", "CL 1", 2, ["Slow performance"], "resolved", d(2026, 8, 21, 8, 19)),
        ("CL-1028", "CL 1", 12, ["Missing mouse"], "resolved", d(2026, 7, 30, 14, 5)),
        ("CL-1029", "CL 2", 5, ["Monitor issue"], "resolved", d(2026, 7, 22, 10, 0)),
        ("CL-1030", "CL 4", 8, ["Slow performance"], "resolved", d(2026, 7, 15, 9, 30)),
        ("CL-1031", "CL 3", 14, ["Software error"], "resolved", d(2026, 7, 10, 8, 45)),
        ("CL-1025", "CL 1", 10, ["No internet"], "resolved", d(2026, 3, 2, 9, 15)),
        ("CL-1042", "CL 4", 5, ["Software error"], "progress", d(2026, 9, 5, 13, 0)),
    ]
    return [make_report(c, name, room, u, i, "", s, "", w) for c, room, u, i, s, w in rows]


def report_from_backend(r: dict) -> dict:
    """A row from /technician/dashboard -> the report dict used here."""
    status = str(r.get("status") or "progress").lower()
    if status not in REPORT_STATUS:
        status = "progress"
    issues = r.get("issues") or []
    if isinstance(issues, str):
        issues = [i.strip() for i in issues.split(",") if i.strip()]
    when = parse_dt(r.get("created_at"))
    report = make_report(
        str(r.get("code") or r.get("id") or "—"), str(r.get("reporter") or "Unknown"),
        str(r.get("room") or "CL 1"), _int(r.get("unit_number")), [str(i) for i in issues],
        str(r.get("comment") or ""), status, str(r.get("resolution_note") or ""),
        when or datetime.min, db_id=r.get("id"), handled_by=str(r.get("handled_by") or ""))
    if when is None:
        report["date"] = str(r.get("created_at") or "—")
    return report


# ===========================================================================
# Lab: rooms, units, statuses and unit details
# ===========================================================================
class Lab:
    def __init__(self, rooms, counts, details, status_fn, escalation, default_fn, sample):
        self.rooms: list[str] = rooms
        self.counts: dict[str, int] = counts
        self.details: dict[str, dict] = details
        self._status = status_fn
        self.escalation: dict[str, str] = escalation
        self._default = default_fn
        self.sample: bool = sample

    def status(self, room: str, n: int) -> str:
        return self._status(room, n)

    def detail(self, room: str, n: int) -> dict:
        return self.details.get(unit_key(room, n)) or self._default(room, n, self.status(room, n))

    def room_summary(self, room: str) -> dict:
        out = {"good": 0, "issue": 0, "replace": 0}
        for n in range(1, self.counts.get(room, 0) + 1):
            out[self.status(room, n)] += 1
        return out

    def escalated(self) -> list[tuple[str, str, int, list]]:
        """Units reported 5 or more times: (key, room, number, history), most reports first."""
        out = []
        for key, d in self.details.items():
            if len(d["history"]) >= 5:
                room, n = split_key(key)
                out.append((key, room, n, d["history"]))
        return sorted(out, key=lambda u: -len(u[3]))


def sample_lab() -> Lab:
    return Lab(list(SAMPLE_ROOMS), dict(SAMPLE_COUNTS), copy.deepcopy(SAMPLE_UNIT_DETAILS),
               sample_status, {}, sample_default_detail, sample=True)


def _or_missing(obj, label: str) -> dict:
    return dict(obj) if isinstance(obj, dict) and obj else {label: "Not recorded yet"}


def _software(items) -> list[tuple[str, str]]:
    if isinstance(items, dict):
        items = list(items.items())
    out = []
    for item in items or []:
        if isinstance(item, (list, tuple)) and item:
            out.append((str(item[0]), str(item[1]) if len(item) > 1 else ""))
        elif item:
            out.append((str(item), ""))
    return out or [("Software", "Not recorded yet")]


def live_lab(units: list[dict], reports: list[dict]) -> Lab:
    """Build the Lab from the backend's Computers rows and the reports."""
    stored, counts = {}, {}
    for u in units or []:
        room, n = str(u.get("room") or "").strip(), _int(u.get("number"))
        if room and n > 0:
            stored[unit_key(room, n)] = u
            counts[room] = max(counts.get(room, 0), n)
    for r in reports:
        counts[r["room"]] = max(counts.get(r["room"], 0), r["unit"])
    rooms = sorted(counts, key=natural_key) or ["CL 1"]

    open_keys, history = set(), {}
    for r in sorted(reports, key=lambda x: x["when"], reverse=True):
        k = unit_key(r["room"], r["unit"])
        if r["status"] != "resolved":
            open_keys.add(k)
        history.setdefault(k, []).append(_h(
            r["date"], r["issues"][0] if r["issues"] else "General issue", r["comment"],
            r["note"] or "Logged and pending review.", r["status"]))

    def status(room: str, n: int) -> str:
        k = unit_key(room, n)
        u = stored.get(k) or {}
        if u.get("status") == "replace":
            return "replace"
        if u.get("status") == "issue" or k in open_keys:
            return "issue"
        return "good"

    details = {}
    for k in set(stored) | set(history):
        u = stored.get(k) or {}
        details[k] = {
            "hardware": _or_missing(u.get("hardware"), "Hardware"),
            "software": _software(u.get("software")),
            "system": _or_missing(u.get("system"), "System"),
            "lifecycle": _or_missing(u.get("lifecycle"), "Lifecycle"),
            "history": history.get(k, []),
        }
    escalation = {k: u["escalation_status"] for k, u in stored.items() if u.get("escalation_status")}
    return Lab(rooms, {r: counts.get(r, 0) for r in rooms}, details, status, escalation,
               _empty_detail, sample=False)




# ===========================================================================
# Statuses (labels + the design's pill colours)
# ===========================================================================
REPORT_STATUS = {
    "progress": ("In Progress", "amber"),
    "resolved": ("Resolved", "green"),
    "followup": ("Needs Follow-Up", "red"),
}
TEACHER_STATUS = {
    "progress": ("Being fixed", "amber"),
    "resolved": ("Resolved", "green"),
    "followup": ("Needs follow-up", "red"),
}
UNIT_STATUS = {"good": ("Good", "green"), "issue": ("Has issue", "amber"), "replace": ("Needs replacement", "red")}
HIST_COLOR = {"resolved": "green", "progress": "amber", "followup": "red"}
_VERB = {"resolved": "Resolved", "progress": "Updated", "followup": "Flagged for follow-up"}


def history_sentence(h: dict) -> str:
    date_part = str(h.get("date", "")).split(" ·")[0].strip()
    weekday = ""
    try:
        weekday = datetime.strptime(date_part, "%b %d, %Y").strftime("%A") + ", "
    except ValueError:
        pass
    return f"{_VERB.get(h.get('status'), 'Updated')} on {weekday}{date_part}: {h.get('action', '')}"


# ===========================================================================
# HTML + styled-widget helpers
# ===========================================================================
def h(text) -> str:
    """Escape text for HTML."""
    return _html.escape(str(text if text is not None else ""))


_HEADING_OPEN = re.compile(r"<h([1-6])(\s|>)")
_HEADING_CLOSE = re.compile(r"</h[1-6]>")


def _markup(markup: str) -> str:
    """One line of HTML, headings turned into <div class="hxN"> (no Streamlit heading anchors)."""
    markup = " ".join(line.strip() for line in markup.strip().splitlines())
    markup = _HEADING_OPEN.sub(lambda m: f'<div class="hx{m.group(1)}"{m.group(2)}', markup)
    return _HEADING_CLOSE.sub("</div>", markup)


def html(markup: str) -> None:
    """Show a piece of the design (display only - clicks go to Streamlit buttons).

    It goes through st.markdown(unsafe_allow_html=True) - the same way the logo
    intro is drawn - so inline SVG (icons, the floor plan, the logo) is kept.
    The wrapper's "clx" class is what the scoped design CSS hangs on.
    """
    st.markdown(f'<div class="clx">{_markup(markup)}</div>', unsafe_allow_html=True)


# ---- design CSS -> scoped to the .clx wrappers ------------------------------------
_SKIP_SCOPE = ("[", ".st", "#MainMenu", "footer:not", "header[", "section[", ":root")
_TAG_HEADING = re.compile(r"(?<![\w.#-])h([1-6])(?![\w-])")


def _split_top(text: str, sep: str = ",") -> list[str]:
    out, depth, cur = [], 0, ""
    for ch in text:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if ch == sep and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    return out + [cur]


def _scope_selector(sel: str) -> str:
    sel = sel.strip()
    if not sel or any(token in sel for token in _SKIP_SCOPE):
        return sel
    sel = _TAG_HEADING.sub(r".hx\1", sel)
    if sel in ("html", "body"):
        return ".clx"
    return ".clx " + sel


def scope_css(css: str) -> str:
    """Prefix the design's selectors with .clx so they win over Streamlit's own
    markdown styles, map h1-h6 to the .hxN divs, and move @import to the top."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    import_re = r"@import\s+(?:url\([^)]*\)|\"[^\"]*\"|'[^']*')[^;]*;"
    imports = re.findall(import_re, css)
    css = re.sub(import_re, "", css)

    def walk(text: str) -> str:
        out, i = [], 0
        while i < len(text):
            j = text.find("{", i)
            if j < 0:
                break
            head = text[i:j].strip()
            depth, k = 1, j + 1
            while k < len(text) and depth:
                depth += {"{": 1, "}": -1}.get(text[k], 0)
                k += 1
            body = text[j + 1:k - 1]
            if head.startswith("@media") or head.startswith("@supports"):
                out.append(f"{head}{{{walk(body)}}}")
            elif head.startswith("@"):
                out.append(f"{head}{{{body}}}")
            else:
                if head.strip() in ("html", "body"):  # page-level look: keep the font/colour, not the background
                    body = re.sub(r"background[^;]*;?", "", body)
                out.append(",".join(_scope_selector(s) for s in _split_top(head)) + f"{{{body}}}")
            i = k
        return "\n".join(out)

    headings = (".clx :is(.hx1,.hx2,.hx3,.hx4,.hx5,.hx6){display:block;font-weight:700;margin:0;}"
                ".clx .hx1{font-size:2em;}.clx .hx2{font-size:1.5em;}.clx .hx3{font-size:1.17em;}")
    return "\n".join(imports) + "\n" + headings + "\n" + walk(css)


def btn(label: str, key: str, kind: str = "ghost", *, full: bool = False, on_click=None, args=(),
        disabled: bool = False, icon: str | None = None, help: str | None = None) -> bool:
    """A Streamlit button dressed as one of the design's buttons.

    kind: primary, primarysm, ghost, ghostsm, success, dghost, dghostsm, danger,
    link, back, logout, chip, chipon, chipother, chipotheron, aichip, aichipon,
    tog, togon, rtab, rtabon, tabbtn, tabbtnon, umenu, umenudanger, x, pencil.
    """
    kwargs = {"icon": icon} if icon else {}
    return st.button(label, key=f"{key}__{kind}__" + ("w__" if full else ""), on_click=on_click, args=args,
                     disabled=disabled, help=help, **kwargs)


def hit(markup: str, key: str, on_click, args=()) -> None:
    """A design element (card, row, menu item...) that is clickable as a whole."""
    with st.container(key=f"hitwrap_{key}"):
        html(markup)
        st.button("open", key=f"hit_{key}", on_click=on_click, args=args)


def box(key: str, *marks: str):
    """st.container whose look comes from the CSS markers (card, section, row, rowend, ...)."""
    return st.container(key=key + "".join(f"__{m}__" for m in marks))


def pill(label: str, color: str) -> str:
    return f'<span class="pill {color}">{h(label)}</span>'


def report_pill(status: str, labels: dict = REPORT_STATUS) -> str:
    return pill(*labels.get(status, labels["progress"]))


def issue_tags(issues: list[str]) -> str:
    return '<div class="issue-tags">' + "".join(f'<span class="issue-tag">{h(i)}</span>' for i in issues) + "</div>"


def field_label(text: str, extra: str = "") -> None:
    html(f'<label class="field-label">{h(text)}{extra}</label>')


# ---- icons (the design's own SVGs) ---------------------------------------------
def _svg(body: str, size: int = 16, sw: float = 2, extra: str = "") -> str:
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            f'stroke-width="{sw}" {extra}>{body}</svg>')


_GEAR = ('<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.3 '
         '1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 '
         '.3-1.9 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 '
         '1.9.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0 '
         '-.3 1.9V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>')
ICON_PATHS = {
    "grid": '<rect x="3" y="3" width="7" height="9" rx="1"/><rect x="14" y="3" width="7" height="5" rx="1"/>'
            '<rect x="14" y="12" width="7" height="9" rx="1"/><rect x="3" y="16" width="7" height="5" rx="1"/>',
    "clockcircle": '<circle cx="12" cy="12" r="9"/><path d="M12 8v4l3 2"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "doc": '<path d="M6 3h9l5 5v13H6z"/><path d="M9 12h6M9 16h6M9 8h3"/>',
    "checklist": '<path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>',
    "monitor": '<rect x="3" y="4" width="18" height="12" rx="1"/><path d="M8 20h8M12 16v4"/>',
    "chart": '<path d="M3 3v18h18"/><path d="M7 15l4-5 3 3 5-7"/>',
    "warning": '<path d="M12 9v4M12 17h.01"/><path d="M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/>',
    "gear": _GEAR,
    "useradd": '<circle cx="9" cy="8" r="4"/><path d="M2 21c0-3.8 3.1-6 7-6s7 2.2 7 6"/><path d="M19 8v6M16 11h6"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "check": '<path d="M20 6L9 17l-5-5"/>',
    "flag": '<path d="M4 21V4a1 1 0 0 1 1-1h11l-2 5 2 5H6a1 1 0 0 0-1 1v7"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/>',
    "chevron": '<path d="M6 9l6 6 6-6"/>',
    "user": '<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 4-6 8-6s8 2 8 6"/>',
    "bell": '<path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.7 21a2 2 0 0 1-3.4 0"/>',
    "lock": '<rect x="5" y="11" width="14" height="9" rx="1.5"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 8h.01M11 12h1v4h1"/>',
    "phone": '<path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6 19.8 19.8 0 0 1-3.1-8.7A2 2 0 0 1 4.1 2h3a2 '
             '2 0 0 1 2 1.7c.1.9.3 1.8.6 2.7a2 2 0 0 1-.5 2.1L7.9 9.9a16 16 0 0 0 6 6l1.4-1.4a2 2 0 0 1 2.1-.5c.9.3 1.8.5 2.7.6a2 2 0 0 1 '
             '1.9 2.1z"/>',
    "mail": '<rect x="2" y="4" width="20" height="16" rx="2"/><path d="M2 7l10 6 10-6"/>',
    "robot": '<path d="M12 2a4 4 0 0 1 4 4v1a4 4 0 0 1-8 0V6a4 4 0 0 1 4-4z"/><path d="M6 21v-2a4 4 0 0 1 4-4h4a4 4 0 0 1 4 4v2"/>',
}


def icon(name: str, size: int = 16, sw: float = 2, extra: str = "") -> str:
    return _svg(ICON_PATHS[name], size, sw, extra)


# ===========================================================================
# Styling: the design CSS + how Streamlit's widgets fit into it
# ===========================================================================
_SEARCH_BG = ("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='14' height='14' viewBox='0 0 24 24' "
              "fill='none' stroke='%23a4adba' stroke-width='2'><circle cx='11' cy='11' r='7'/><path d='M21 21l-4.3-4.3'/></svg>")

STREAMLIT_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

/* ---- Streamlit chrome off, page background + font from the design ---- */
[data-testid="stToolbar"], [data-testid="stDecoration"], [data-testid="stStatusWidget"], #MainMenu, footer { display: none !important; }
header[data-testid="stHeader"] { background: transparent !important; height: 0 !important; }
.stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"] { background: var(--bg) !important; }
.stApp, .stApp p, .stApp label, .stApp input, .stApp textarea, .stApp button, .stApp li,
.stApp [data-baseweb="select"] { font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }
.stApp { color: var(--ink-900); -webkit-font-smoothing: antialiased; }
[data-testid="stMainBlockContainer"], .block-container { max-width: 100% !important; padding: 0 !important; }
:where([data-testid="stMain"], [data-testid="stSidebar"]) [data-testid="stVerticalBlock"] { gap: 0 !important; }
.stHtml, [data-testid="stHtml"] { width: 100%; }
[data-testid="stMarkdownContainer"]:has(> .clx) { margin: 0 !important; }
[data-testid="stMarkdownContainer"] > .clx { display: block; }
[data-testid="stElementContainer"]:has(> .stHtml:empty) { display: none; }

/* ---- sidebar = .sidebar ---- */
section[data-testid="stSidebar"] { width: 230px !important; min-width: 230px !important; max-width: 230px !important;
  background: var(--white) !important; border-right: 1px solid var(--line); }
section[data-testid="stSidebar"] > div { background: var(--white) !important; }
[data-testid="stSidebarHeader"] { height: 8px !important; min-height: 0 !important; padding: 0 !important; overflow: hidden; }
[data-testid="stSidebarUserContent"] { padding: 12px 14px 20px !important; }

/* ---- topbar + content ---- */
.st-key-cl_topbar { position: sticky; top: 0; z-index: 90; height: 60px; background: var(--white);
  border-bottom: 1px solid var(--line); flex-direction: row !important; align-items: center;
  justify-content: space-between; padding: 0 24px; flex-wrap: nowrap; }
.st-key-cl_topbar > div { width: auto !important; flex: 0 0 auto; }
.st-key-cl_topbar [data-testid="stPopover"] button { border: none !important; background: transparent !important;
  box-shadow: none !important; padding: 6px 8px !important; min-height: 0; color: var(--ink-900) !important; }
.st-key-cl_topbar [data-testid="stPopover"] button:hover { background: var(--bg) !important; }
.st-key-cl_topbar [data-testid="stPopover"] button p { font-size: 13px; font-weight: 600; }
.st-key-cl_topbar [data-testid="stPopover"] button::before { content: var(--cl-initials); width: 30px; height: 30px;
  border-radius: 50%; background: var(--blue-50); color: var(--blue-700); font-size: 12px; font-weight: 700;
  display: inline-flex; align-items: center; justify-content: center; margin-right: 10px; flex: 0 0 30px; }
[data-testid="stPopoverBody"] { padding: 6px !important; min-width: 180px; border-radius: 10px !important;
  border: 1px solid var(--line) !important; box-shadow: 0 8px 24px rgba(0,0,0,.12) !important; }
[data-testid="stPopoverBody"] [data-testid="stVerticalBlock"] { gap: 0 !important; }
.st-key-cl_content { padding: 26px 30px 60px; }

/* ---- design containers ---- */
[class*="__card__"] { background: var(--white); border: 1px solid var(--line); border-radius: var(--radius); box-shadow: var(--shadow); }
[class*="__section__"] { padding: 20px 22px; margin-bottom: 18px; }
[class*="__pad0__"] { padding: 0 !important; overflow: hidden; }
[class*="__gap__"] { gap: 14px !important; }
[class*="__gapsm__"] { gap: 8px !important; }
[class*="__gap10__"] { gap: 10px !important; }
.activity-card { margin-bottom: 0 !important; }
[class*="__formcard__"] { max-width: 640px; padding: 26px; }
[class*="__confirmcard__"] { max-width: 520px; }
[class*="__settingscard__"] { padding: 26px; margin-bottom: 18px; }
[class*="__esc__"] { padding: 20px 22px; margin-bottom: 14px; }
[class*="__row__"], [class*="__rowend__"], [class*="__rowbetween__"], [class*="__rowcenter__"] {
  flex-direction: row !important; flex-wrap: wrap; align-items: center; gap: 10px !important; }
[class*="__rowend__"] { justify-content: flex-end; }
[class*="__rowcenter__"] { justify-content: center; }
[class*="__rowbetween__"] { justify-content: space-between; }
[class*="__row__"] > div, [class*="__rowend__"] > div, [class*="__rowbetween__"] > div, [class*="__rowcenter__"] > div {
  width: auto !important; flex: 0 0 auto; }
[class*="__grow1__"] > div:first-child { flex: 1 1 0 !important; min-width: 0; }
[class*="__mb14__"] { margin-bottom: 14px; }
[class*="__mb16__"] { margin-bottom: 16px; }
[class*="__mb18__"] { margin-bottom: 18px; }
[class*="__footerline__"] { margin-top: 26px; padding-top: 20px; border-top: 1px solid var(--line); }
[class*="__fieldrow__"] { padding: 16px 0; border-bottom: 1px solid var(--line); flex-wrap: nowrap; }
[class*="__fieldrow__"] > div:first-child { flex: 1 1 auto !important; }
[class*="__togglerow__"] { padding: 16px 0; border-bottom: 1px solid var(--line); flex-wrap: nowrap; }
[class*="__togglerow__"] > div:first-child { flex: 1 1 auto !important; }
[class*="__nolast__"] { border-bottom: none !important; }

/* status toggle, room tabs, detail tabs */
[class*="__toggle__"] { flex-direction: row !important; background: var(--bg); border-radius: 8px; padding: 3px; gap: 2px !important; width: fit-content; }
[class*="__toggle__"] > div { width: auto !important; }
[class*="__togglefull__"] { width: 100% !important; }
[class*="__togglefull__"] > div { flex: 1 1 0 !important; }
[class*="__roomtabs__"] { flex-direction: row !important; gap: 6px !important; margin-bottom: 16px; border-bottom: 1px solid var(--line); flex-wrap: wrap; }
[class*="__roomtabs__"] > div { width: auto !important; }
[class*="__tabsrow__"] { flex-direction: row !important; gap: 4px !important; background: var(--bg); border-radius: 9px; padding: 4px; margin-bottom: 18px; width: fit-content; }
[class*="__tabsrow__"] > div { width: auto !important; }
[class*="__chips__"] { flex-direction: row !important; flex-wrap: wrap; gap: 8px !important; }
[class*="__chips__"] > div { width: auto !important; }
[class*="__aibox__"] { background: var(--blue-25); border: 1px solid var(--blue-50); border-radius: 10px; padding: 14px 16px; margin-top: 18px; }
[class*="__aichips__"] { flex-direction: row !important; flex-wrap: wrap; gap: 7px !important; }
[class*="__aichips__"] > div { width: auto !important; }
[class*="__unitgrid__"] { display: grid !important; grid-template-columns: repeat(auto-fill, minmax(130px, 1fr)); gap: 14px !important; }
[class*="__unitgrid__"] > div { width: auto !important; }
[class*="__actions__"] { flex-direction: row !important; gap: 10px !important; margin-top: 16px; }
[class*="__actions__"] > div { flex: 1 1 0 !important; width: auto !important; }
[class*="__reqbanner__"] { display: flex; flex-direction: row !important; align-items: center; gap: 14px !important;
  background: var(--blue-50); border: 1px solid #cfe0fb; border-radius: 12px; padding: 14px 18px; margin-bottom: 18px; }
[class*="__reqbanner__"] > div { width: auto !important; }
[class*="__reqbanner__"] > div:first-child { flex: 1 1 auto !important; }
[class*="__reqside__"] { border-right: 1px solid var(--line); height: 100%; }
[class*="__reqsidehead__"] { padding: 14px; border-bottom: 1px solid var(--line); gap: 10px !important; }
[class*="__reqlist__"] { max-height: 640px; overflow-y: auto; flex-wrap: nowrap; }
[class*="__reqfoot__"] { border-top: 1px solid var(--line); padding: 14px 26px; flex-wrap: nowrap; }
[class*="__reqfoot__"] > div:first-child { flex: 1 1 auto !important; }
[class*="__settingsmenu__"] { padding: 6px; }
[class*="__drawer__"] { position: fixed !important; top: 0; right: 0; bottom: 0; width: min(420px, 100vw) !important;
  background: var(--white); overflow-y: auto; padding: 26px; z-index: 1000010; flex-wrap: nowrap;
  box-shadow: 0 0 0 100vmax rgba(20,26,36,.4), -8px 0 24px rgba(0,0,0,.12); }
[class*="__modal__"] { position: fixed !important; top: 50%; left: 50%; transform: translate(-50%, -50%);
  width: min(440px, calc(100vw - 40px)) !important; padding: 24px; background: var(--white); border-radius: var(--radius);
  z-index: 1000020; box-shadow: 0 0 0 100vmax rgba(20,26,36,.45); gap: 0 !important; }
.sh3 { font-size: 14.5px; font-weight: 700; margin: 0; color: var(--ink-900); }
.dr-title { font-size: 17px; font-weight: 700; margin: 0 0 2px; }
.unit-h1 { font-size: 21px; font-weight: 700; margin: 0; }
.req-h2 { font-size: 18px; font-weight: 700; margin: 0 0 4px; }
.modal-h3 { margin: 0 0 6px; font-size: 16px; font-weight: 700; }
.modal-p { margin: 0 0 16px; font-size: 13px; color: var(--ink-500); line-height: 1.5; }
.settings-card-title { font-weight: 700; }
.rt-head, .rt-row { display: grid; gap: 0; align-items: start; }
.rt-head > div { text-align: left; font-size: 11.5px; letter-spacing: .03em; color: var(--ink-500); padding: 12px 16px;
  font-weight: 700; border-bottom: 1px solid var(--line); }
.rt-row { border-bottom: 1px solid var(--line); }
.rt-row > div { padding: 14px 16px; font-size: 13.5px; color: var(--ink-700); min-width: 0; }
.notice-bar { position: fixed; left: 50%; top: 12px; transform: translateX(-50%); z-index: 9999; background: #fff7e6;
  color: #8a5300; border: 1px solid #f3c77a; border-radius: 10px; padding: 8px 16px; font: 500 13px/1.4 system-ui, sans-serif;
  box-shadow: 0 4px 14px rgba(0,0,0,.08); max-width: 90%; text-align: center; }

/* ---- whole-element click areas (an invisible button over the design element) ---- */
[class*="st-key-hitwrap_"] { position: relative; gap: 0 !important; }
[class*="st-key-hit_"] { position: absolute !important; inset: 0; z-index: 4; width: 100% !important; height: 100% !important; margin: 0 !important; }
[class*="st-key-hit_"] .stButton, [class*="st-key-hit_"] button { width: 100% !important; height: 100% !important;
  min-height: 0 !important; padding: 0 !important; opacity: 0 !important; cursor: pointer; }
[class*="st-key-hitwrap_"]:hover .nav-item:not(.active) { background: var(--blue-25); }
[class*="st-key-hitwrap_"]:hover .unit-card { border-color: var(--blue-500); box-shadow: var(--shadow); }
[class*="st-key-hitwrap_"]:hover .rt-row { background: var(--blue-25); }
[class*="st-key-hitwrap_"]:hover .req-item:not(.selected) { background: var(--blue-25); }
[class*="st-key-hitwrap_"]:hover .settings-menu-item:not(.active) { background: var(--bg); }
[class*="st-key-hitwrap_"]:hover .activity-card { filter: brightness(.985); }
[class*="__navlist__"] [class*="st-key-hitwrap_"] { margin-bottom: 2px; }
[class*="__lastnoborder__"] > div:last-child .rt-row { border-bottom: none; }

/* ---- buttons: the design's .btn variants ---- */
.stApp .stButton > button, .stApp .stFormSubmitButton > button { border-radius: 8px; font-weight: 600; font-size: 13.5px;
  padding: 10px 16px; min-height: 0; line-height: 1.2; box-shadow: none; transition: background .12s; }
.stApp .stButton > button p { font-size: inherit !important; font-weight: inherit !important; margin: 0; }
[class*="__primary"] button, [class*="__success__"] button, [class*="__danger__"] button { color: #fff !important; border: none !important; }
[class*="__primary"] button { background: var(--blue-600) !important; }
[class*="__primary"] button:hover { background: var(--blue-700) !important; }
[class*="__primary"] button:disabled { background: #c6d4ef !important; color: #fff !important; cursor: not-allowed; }
[class*="__success__"] button { background: var(--green) !important; }
[class*="__success__"] button:hover { background: #188059 !important; }
[class*="__danger__"] button { background: var(--red) !important; }
[class*="__danger__"] button:hover { background: #b93a41 !important; }
[class*="__ghost"] button { background: var(--white) !important; color: var(--ink-700) !important; border: 1px solid var(--line) !important; }
[class*="__ghost"] button:hover { background: var(--bg) !important; }
[class*="__dghost"] button { background: var(--white) !important; color: var(--red) !important; border: 1px solid var(--line) !important; }
[class*="__dghost"] button:hover { background: var(--red-bg) !important; }
[class*="sm__"] button { padding: 7px 12px !important; font-size: 12.5px !important; }
[class*="__w__"], [class*="__w__"] .stButton, [class*="__w__"] button { width: 100% !important; justify-content: center; }
[class*="__link__"] button, [class*="__back__"] button, [class*="__x__"] button, [class*="__pencil__"] button {
  background: transparent !important; border: none !important; padding: 0 !important; min-height: 0 !important; box-shadow: none !important; }
[class*="__link__"] button { color: var(--blue-600) !important; font-size: 12.5px !important; }
[class*="__back__"] button { color: var(--blue-600) !important; font-size: 13px !important; margin-bottom: 14px; }
[class*="__x__"] { position: absolute !important; top: 18px; right: 18px; width: auto !important; z-index: 3; }
[class*="__x__"] button { color: var(--ink-500) !important; font-size: 18px !important; }
[class*="__pencil__"] button { color: var(--ink-300) !important; }
[class*="__pencil__"] button:hover { color: var(--blue-600) !important; }
[class*="__logout__"], [class*="__logout__"] button { width: 100% !important; }
[class*="__logout__"] button { margin-top: 12px; padding: 13px !important; border-radius: 10px !important; border: none !important;
  background: linear-gradient(180deg,#6b7280,#374151) !important; color: #fff !important; font-weight: 700 !important; }
[class*="__logout__"] button:hover { background: linear-gradient(180deg,#4b5563,#1f2937) !important; }
[class*="__chip"] button { border: 1px solid var(--line) !important; border-radius: 100px !important; padding: 8px 14px !important;
  font-size: 13px !important; font-weight: 500 !important; color: var(--ink-700) !important; background: var(--white) !important; }
[class*="__chipother"] button { border-style: dashed !important; }
[class*="__chipon__"] button, [class*="__chipotheron__"] button { background: var(--blue-600) !important; border-color: var(--blue-600) !important; color: #fff !important; }
[class*="__aichip"] button { background: var(--white) !important; border: 1px solid var(--line) !important; border-radius: 100px !important;
  padding: 7px 13px !important; font-size: 12.5px !important; font-weight: 400 !important; color: var(--ink-700) !important; }
[class*="__aichip"] button:hover { border-color: var(--blue-500) !important; }
[class*="__aichipon__"] button { background: var(--blue-50) !important; border-color: var(--blue-500) !important; color: var(--blue-700) !important; font-weight: 600 !important; }
[class*="__tog"] button { background: transparent !important; border: none !important; padding: 7px 13px !important; border-radius: 6px !important;
  font-size: 12.5px !important; color: var(--ink-500) !important; box-shadow: none !important; }
[class*="__togon__"] button { background: var(--white) !important; color: var(--ink-900) !important; box-shadow: var(--shadow) !important; }
[class*="__togglefull__"] button { width: 100% !important; padding: 7px 4px !important; }
[class*="__rtab"] button { background: transparent !important; border: none !important; border-bottom: 2px solid transparent !important;
  border-radius: 0 !important; padding: 11px 18px !important; font-size: 13.5px !important; color: var(--ink-500) !important; margin-bottom: -1px; }
[class*="__rtabon__"] button { color: var(--ink-900) !important; border-bottom-color: var(--blue-600) !important; }
[class*="__tabbtn"] button { background: transparent !important; border: none !important; padding: 8px 16px !important; border-radius: 7px !important;
  font-size: 13px !important; color: var(--ink-500) !important; }
[class*="__tabbtnon__"] button { background: var(--white) !important; color: var(--ink-900) !important; box-shadow: var(--shadow) !important; }
[class*="__umenu"], [class*="__umenu"] button { width: 100% !important; }
[class*="__umenu"] button { justify-content: flex-start !important; background: transparent !important; border: none !important;
  padding: 9px 10px !important; border-radius: 7px !important; font-size: 13px !important; color: var(--ink-700) !important; }
[class*="__umenu"] button:hover { background: var(--bg) !important; }
[class*="__umenudanger__"] button { color: var(--red) !important; }
[class*="__umenudanger__"] button:hover { background: var(--red-bg) !important; }

/* ---- inputs: the design's .input ---- */
.stApp [data-baseweb="input"], .stApp [data-baseweb="textarea"], .stApp [data-baseweb="select"] > div {
  border: 1px solid var(--line) !important; border-radius: 8px !important; background: var(--white) !important; }
.stApp [data-baseweb="input"]:focus-within, .stApp [data-baseweb="textarea"]:focus-within, .stApp [data-baseweb="select"] > div:focus-within {
  border-color: var(--blue-500) !important; box-shadow: 0 0 0 1px var(--blue-500) !important; }
.stApp [data-baseweb="input"] > div, .stApp [data-baseweb="base-input"] { background: transparent !important; }
.stApp input, .stApp textarea, .stApp [data-baseweb="select"] { font-size: 13.5px !important; color: var(--ink-900) !important; }
.stApp textarea { min-height: 70px; }
[class*="__search__"] input { padding-left: 34px !important; background: url("__SEARCH_BG__") no-repeat 11px center !important; }
[class*="__search__"] { min-width: 230px; }
[class*="__fsel__"] { min-width: 150px; }
[class*="__fselsm__"] { min-width: 120px; }
.stApp [data-testid="stWidgetLabel"] p { font-size: 13px; font-weight: 600; color: var(--ink-700); }
[class*="__invfilter__"] [role="radiogroup"] { gap: 14px; }
[class*="__invfilter__"] label p { font-size: 13px !important; color: var(--ink-700); }
[class*="__invfilter__"] [role="radiogroup"] > label:nth-child(n+2) [data-testid="stMarkdownContainer"]::before {
  content: ""; display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; vertical-align: 1px; }
[class*="__invfilter__"] [role="radiogroup"] > label:nth-child(2) [data-testid="stMarkdownContainer"]::before { background: var(--green); }
[class*="__invfilter__"] [role="radiogroup"] > label:nth-child(3) [data-testid="stMarkdownContainer"]::before { background: var(--amber); }
[class*="__invfilter__"] [role="radiogroup"] > label:nth-child(4) [data-testid="stMarkdownContainer"]::before { background: var(--red); }
[class*="__invfilter__"] [role="radiogroup"] [data-testid="stMarkdownContainer"] { display: inline-flex !important; align-items: center; gap: 0; }
[class*="__invfilter__"] [role="radiogroup"] [data-testid="stMarkdownContainer"] p { margin: 0 !important; }

/* ---- toast = .toast ---- */
[data-testid="stToast"] { background: var(--ink-900) !important; border-radius: 10px !important; box-shadow: 0 8px 24px rgba(0,0,0,.18) !important; }
[data-testid="stToast"], [data-testid="stToast"] p, [data-testid="stToast"] button { color: #fff !important; font-size: 13.5px; font-weight: 500; }

@media (max-width: 900px) {
  .stat-row { grid-template-columns: repeat(2, 1fr); }
  .glance-wrap { flex-wrap: wrap; }
  .st-key-cl_content { padding: 18px 16px 40px; }
  .st-key-cl_topbar .search { display: none; }
}
""".replace("__SEARCH_BG__", _SEARCH_BG)


_CSS_CACHE: dict[bool, str] = {}


def _scoped_css(teacher: bool) -> str:
    if teacher not in _CSS_CACHE:
        from frontend.design import DESIGN_CSS, TEACHER_CSS

        _CSS_CACHE[teacher] = scope_css(DESIGN_CSS + (TEACHER_CSS if teacher else "") + STREAMLIT_CSS)
    return _CSS_CACHE[teacher]


def inject_css(role: str, user: dict) -> None:
    ini = initials(user.get("name", "")).replace('"', "")
    css = _scoped_css(role.lower() == "teacher")
    st.markdown(f'<style>{css}:root{{--cl-initials:"{ini}";}}</style>', unsafe_allow_html=True)


# ===========================================================================
# Navigation + page shell (sidebar, topbar)
# ===========================================================================
def current_page(prefix: str, default: str = "dashboard") -> str:
    return ss.setdefault(f"{prefix}_page", default)


def go(prefix: str, page: str) -> None:
    ss[f"{prefix}_page"] = page
    if page == "inventory":
        ss.pop(f"{prefix}_unit", None)  # the grid, not the last unit
    if page != "reports":
        ss.pop(f"{prefix}_sel_report", None)  # close the report drawer


def go_settings(prefix: str, tab: str = "profile") -> None:
    go(prefix, "settings")
    ss[f"{prefix}_stab"] = tab


def open_unit(prefix: str, room: str, n: int) -> None:
    ss[f"{prefix}_page"] = "inventory"
    ss[f"{prefix}_unit"] = (room, int(n))
    ss[f"{prefix}_dtab"] = "hardware"
    ss.pop(f"{prefix}_sel_report", None)
    set_sticky(f"{prefix}_inv_room", room)


def close_unit(prefix: str) -> None:
    ss.pop(f"{prefix}_unit", None)


def open_report(prefix: str, report_id: str, page: str = "reports") -> None:
    """Go to the reports page with this report open in the drawer."""
    ss[f"{prefix}_page"] = page
    ss[f"{prefix}_sel_report"] = report_id


def close_report(prefix: str) -> None:
    ss.pop(f"{prefix}_sel_report", None)


def shell(prefix: str, role: str, groups: list, user: dict, menu_extra: list | None = None) -> None:
    """The sidebar (logo, role badge, navigation) and the topbar (search, user menu).

    groups: [(GROUP LABEL, [(page key, label, icon name, badge count or None), ...]), ...]
    menu_extra: more user-menu entries [(label, callback, args, material icon), ...]
    """
    from frontend.design import LOGO_URI as BUILT_IN_LOGO

    LOGO_URI = asset_uri("logo.png") or BUILT_IN_LOGO  # your assets/logo.png, else the design's logo
    inject_css(role, user)
    page = current_page(prefix)
    with st.sidebar:
        html(f'<div class="brand"><img class="brand-logo" src="{LOGO_URI}" alt="Centrum Laboratory">'
             f'<div class="role-badge">{h(role.upper())}</div></div>')
        for group, items in groups:
            html(f'<div class="nav-label">{h(group)}</div>')
            with box(f"{prefix}_navgroup_{group.lower()}", "navlist", "mb16"):
                for key, label, icon_name, count in items:
                    badge = f'<span class="nav-badge">{count}</span>' if count is not None else ""
                    active = " active" if key == page else ""
                    hit(f'<div class="nav-item{active}"><span class="nav-icon">{icon(icon_name, 17)}</span>'
                        f'{h(label)}{badge}</div>', f"{prefix}_nav_{key}", go, (prefix, key))

    with st.container(key="cl_topbar"):
        html(f'<div class="search">{icon("search", 15)} Search reports, units, rooms&hellip;</div>')
        with st.popover(user["name"]):
            btn("Settings", f"{prefix}_um_settings", "umenu", icon=":material/settings:",
                on_click=go_settings, args=(prefix, "profile"))
            for i, (label, func, args, mat_icon) in enumerate(menu_extra or []):
                btn(label, f"{prefix}_um_extra_{i}", "umenu", icon=mat_icon, on_click=func, args=args)
            btn("Log out", f"{prefix}_um_logout", "umenudanger", icon=":material/logout:", on_click=logout_user)


def notice(text: str) -> None:
    if text:
        html(f'<div class="notice-bar">{h(text)}</div>')


def page_header(group: str, title: str, subtitle: str = "") -> None:
    sub = f'<p class="page-sub">{h(subtitle)}</p>' if subtitle else '<div style="height:18px"></div>'
    html(f'<div class="crumbs">{h(group)} &nbsp;&rsaquo;&nbsp; <b>{h(title)}</b></div>'
         f'<p class="page-title">{h(title)}</p>{sub}')


# ===========================================================================
# Dashboard pieces
# ===========================================================================
_STAT_COLOR = {"blue": "var(--blue-600)", "amber": "var(--amber)", "green": "var(--green)",
               "red": "var(--red)", "purple": "var(--purple)"}


def stat_row(stats: list[tuple]) -> None:
    """stats: (label, value, sub, colour, icon name)"""
    cards = []
    for label, value, sub, color, icon_name in stats:
        size = "font-size:18px;" if isinstance(value, str) and len(value) > 8 else ""
        sw = 2.2 if icon_name == "check" else 2
        cards.append(
            f'<div class="card stat-card"><div class="stat-top"><div class="stat-icon" style="color:{_STAT_COLOR[color]};">'
            f'{icon(icon_name, 16, sw)}</div><div class="stat-label">{h(label)}</div></div>'
            f'<div class="stat-value" style="{size}">{h(value)}</div><div class="stat-sub">{h(sub)}</div></div>')
    html(f'<div class="stat-row">{"".join(cards)}</div>')


def section_head(key: str, title: str, *, legend: bool = False, button: tuple | None = None,
                 link: tuple | None = None) -> None:
    """The card heading row. button/link: (label, callback, args)."""
    with box(key, "rowbetween", "mb14"):
        html(f'<div class="sh3">{title}</div>')
        with box(f"{key}_r", "row"):
            if legend:
                html('<div class="ra-legend"><span><span class="dot green"></span>Resolved</span>'
                     '<span><span class="dot amber"></span>In Progress</span>'
                     '<span><span class="dot red"></span>Follow-Up</span></div>')
            if button:
                btn(button[0], f"{key}_btn", "ghostsm", on_click=button[1], args=button[2])
            if link:
                btn(link[0], f"{key}_link", "link", on_click=link[1], args=link[2])


def recent_activity(prefix: str, reports: list[dict], labels: dict, on_open, *, show_teacher: bool,
                    button: tuple) -> None:
    with box(f"{prefix}_ra", "card", "section", "gap10"):
        section_head(f"{prefix}_ra_head", "Recent Activity", legend=True, button=button)
        recent = sorted(reports, key=lambda r: r["when"], reverse=True)[:5]
        if not recent:
            html('<div class="empty-state" style="padding:30px 0;">No reports yet.</div>')
        for r in recent:
            label, color = labels.get(r["status"], labels["progress"])
            who = f" &middot; reported by {h(r['teacher'])}" if show_teacher else ""
            more = f" +{len(r['issues']) - 1}" if len(r["issues"]) > 1 else ""
            first = r["issues"][0] if r["issues"] else "General issue"
            hit(f'<div class="activity-card st-{r["status"]}" style="cursor:pointer;"><div>'
                f'<div class="ac-title">{h(r["room"])} - {unit_label(r["unit"])}</div>'
                f'<div class="ac-sub">Issue: {len(r["issues"])}{who}</div>'
                f'<div class="ac-tag">{h(first)}{more}</div></div>'
                f'<div class="ac-right"><span class="pill {color}">{h(label)}</span>'
                f'<div class="ac-date-label" style="margin-top:8px;">Date &amp; Time</div>'
                f'<div class="ac-date-value">{h(r["date"])}</div></div></div>',
                f"{prefix}_act_{r['id']}", on_open, (r["id"],))


def room_glance(prefix: str, lab: Lab, button: tuple, last: bool = False) -> None:
    with box(f"{prefix}_glance", "card", "section"):
        section_head(f"{prefix}_glance_head", "Room at a Glance", button=button)
        with box(f"{prefix}_glance_sel", "row", "mb18"):
            html('<div style="font-size:13px;color:var(--ink-500);">Select Room:</div>')
            key = sticky(f"{prefix}_glance_room__fselsm__", lab.rooms)
            room = st.selectbox("Select room", lab.rooms, key=key, label_visibility="collapsed")
            remember(key)
        total = lab.counts.get(room, 0)
        s = lab.room_summary(room)
        top = total or 1
        ticks = [0, round(total * .25), round(total * .5), round(total * .75), total]
        number = room.split(" ")[-1]
        bars = "".join(
            f'<div class="glance-bar-row"><div class="glance-bar-track"><div class="glance-bar-fill" '
            f'style="width:{v / top * 100:.1f}%;background:{c};"></div></div></div>'
            for v, c in ((s["good"], "#a9d6f5"), (s["issue"], "#4a84ee"), (s["replace"], "#1c3f8f")))
        legend = "".join(
            f'<div class="glance-legend-row"><span class="dot" style="background:{c};"></span>{t}'
            f'<span class="glance-legend-count">{v}</span></div>'
            for t, v, c in (("Good (working)", s["good"], "#a9d6f5"), ("Not Good (Have issue)", s["issue"], "#4a84ee"),
                            ("Need for replacement", s["replace"], "#1c3f8f")))
        html(f'<div class="glance-wrap"><div class="glance-icon"><div class="glance-icon-box">'
             f'{_svg(ICON_PATHS["monitor"], 36, 1.8).replace("currentColor", "#fff")}</div>'
             f'<div class="glance-room-name">Centrum<br>Laboratory {h(number)}</div></div>'
             f'<div class="glance-chart">{bars}<div class="glance-axis">{"".join(f"<span>{t}</span>" for t in ticks)}</div></div>'
             f'<div class="glance-stats"><div class="glance-total-label">Total Computers</div>'
             f'<div class="glance-total-value">{total}</div>{legend}</div></div>')


def issuetype_rows(counts: dict[str, int], limit: int | None = None) -> str:
    items = sorted(counts.items(), key=lambda kv: -kv[1])[:limit]
    top = max([v for _, v in items] or [1])
    return "".join(
        f'<div class="issuetype-row"><div class="issuetype-name">{h(name)}</div>'
        f'<div class="issuetype-bar-wrap"><div class="issuetype-bar" style="width:{v / top * 100:.1f}%;"></div></div>'
        f'<div class="issuetype-count">{v}</div></div>' for name, v in items
    ) or '<div style="font-size:13px;color:var(--ink-500);">Nothing reported yet.</div>'


def issue_types_card(prefix: str, reports: list[dict]) -> None:
    with box(f"{prefix}_types", "card", "section"):
        section_head(f"{prefix}_types_head",
                     'Most Reported Issue Types <span style="font-weight:400;color:var(--ink-300);">(all rooms)</span>',
                     link=("Full analytics", go, (prefix, "analytics")))
        html(f'<div>{issuetype_rows(issue_counts(reports), 6)}</div>')


def issue_counts(reports: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in reports:
        for i in r["issues"]:
            counts[i] = counts.get(i, 0) + 1
    return counts


# ===========================================================================
# Reports table + report drawer
# ===========================================================================
SORTS = {"date-desc": "Newest first", "date-asc": "Oldest first", "status": "Status", "room": "Room"}


def sort_reports(reports: list[dict], how: str) -> list[dict]:
    if how == "date-asc":
        return sorted(reports, key=lambda r: r["when"])
    if how == "status":
        return sorted(reports, key=lambda r: r["status"])
    if how == "room":
        return sorted(reports, key=lambda r: natural_key(r["room"]))
    return sorted(reports, key=lambda r: r["when"], reverse=True)


AI_SUGGESTIONS = {
    "Won't turn on": ["Check the power cable and outlet connection", "Test the unit on a different outlet/extension",
                      "Inspect the PSU for signs of failure", "Reseat RAM and check for beep codes on boot"],
    "Slow performance": ["Clear temp files and browser cache", "Disable unnecessary startup apps",
                         "Run a malware/antivirus scan", "Check available disk space and free some up"],
    "No internet": ["Reset the network adapter", "Swap the ethernet cable",
                    "Check the switch port the unit is connected to", "Update the network driver"],
    "Blue screen (BSOD)": ["Check the latest Windows update logs", "Update or roll back the GPU driver",
                           "Run memory diagnostics (Windows Memory Diagnostic)", "Reseat RAM sticks"],
    "Missing keyboard": ["Issue a replacement keyboard from stock", "Log the missing peripheral for inventory follow-up"],
    "Missing mouse": ["Issue a replacement mouse from stock", "Log the missing peripheral for inventory follow-up"],
    "Monitor issue": ["Replace the VGA/HDMI cable", "Test the monitor on a different unit to isolate the fault",
                      "Adjust display settings/refresh rate"],
    "Software error": ["Repair or reinstall the affected application", "Apply the latest software patch/update",
                       "Check for conflicting background programs"],
}
_GENERIC_SUGGESTIONS = ["Restart the unit and retest", "Inspect related hardware connections",
                        "Escalate to Unit Inventory for a full spec check"]


def suggestions_for(issues: list[str]) -> list[str]:
    out: list[str] = []
    for issue in issues:
        for s in AI_SUGGESTIONS.get(issue, _GENERIC_SUGGESTIONS):
            if s not in out:
                out.append(s)
    return out[:5]


def _apply_suggestion(note_key: str, picked_key: str, index: int, text: str) -> None:
    current = (ss.get(note_key) or "").strip()
    ss[note_key] = f"{current}; {text}" if current else text
    ss[picked_key] = index


def _set(key: str, value) -> None:
    ss[key] = value


def reports_page(prefix: str, reports: list[dict], lab: Lab, subtitle: str, on_action) -> None:
    """Toolbar, the reports table and the report drawer. on_action=None makes it view-only."""
    page_header("Reporting", "Reports", subtitle)
    status_key = f"{prefix}_rep_status_v"
    status = ss.setdefault(status_key, "all")

    with box(f"{prefix}_rep_tb", "rowbetween", "mb16"):
        with box(f"{prefix}_rep_tbl", "row"):
            q = st.text_input("Search", placeholder="Search unit, teacher, issue", label_visibility="collapsed",
                              key=sticky(f"{prefix}_rep_q__search__"))
            rooms = [""] + lab.rooms
            room = st.selectbox("Room", rooms, key=sticky(f"{prefix}_rep_room__fsel__", rooms),
                                format_func=lambda r: room_label(r) if r else "All rooms", label_visibility="collapsed")
            html('<div class="sortby">Sort by</div>')
            sort = st.selectbox("Sort by", list(SORTS), format_func=SORTS.get, label_visibility="collapsed",
                                key=sticky(f"{prefix}_rep_sort__fselsm__"))
            for k in (f"{prefix}_rep_q__search__", f"{prefix}_rep_room__fsel__", f"{prefix}_rep_sort__fselsm__"):
                remember(k)
        with box(f"{prefix}_rep_tbr", "row"):
            with box(f"{prefix}_rep_stog", "toggle"):
                for value, label in (("all", "All"), ("progress", "In Progress"), ("followup", "Follow-Up"),
                                     ("resolved", "Resolved")):
                    btn(label, f"{prefix}_stog_{value}", "togon" if value == status else "tog",
                        on_click=_set, args=(status_key, value))
            count_slot = st.empty()

    q = (q or "").strip().lower()
    shown = [r for r in reports
             if (status == "all" or r["status"] == status) and (not room or r["room"] == room)
             and (not q or q in f"{r['room']} {unit_label(r['unit'])} {r['teacher']} {' '.join(r['issues'])}".lower())]
    shown = sort_reports(shown, sort)
    with count_slot:
        html(f'<div class="count-badge"><b>{len(shown)}</b> reports</div>')

    cols = "grid-template-columns:110px 1.3fr 1.4fr 1.2fr 140px;"
    with box(f"{prefix}_rep_table", "card", "pad0", "lastnoborder"):
        html(f'<div class="rt-head" style="{cols}"><div>REPORT ID</div><div>UNIT</div><div>ISSUE TYPE(S)</div>'
             f'<div>DATE &amp; TIME</div><div>STATUS</div></div>')
        if not shown:
            html('<div class="empty-state">No reports match your filters.</div>')
        for r in shown:
            hit(f'<div class="rt-row" style="{cols}"><div class="rep-id">{h(r["id"])}</div>'
                f'<div><div class="rep-unit">{h(r["room"])} &mdash; {unit_label(r["unit"])}</div>'
                f'<div class="rep-teacher">{h(r["teacher"])}</div></div>'
                f'<div>{issue_tags(r["issues"])}</div>'
                f'<div style="white-space:nowrap;color:var(--ink-500);">{h(r["date"])}</div>'
                f'<div>{report_pill(r["status"])}</div></div>',
                f"{prefix}_row_{r['id']}", open_report, (prefix, r["id"]))

    selected = next((r for r in reports if r["id"] == ss.get(f"{prefix}_sel_report")), None)
    if selected is not None:
        report_drawer(prefix, selected, on_action)


def report_drawer(prefix: str, r: dict, on_action) -> None:
    rid = r["id"]
    with box(f"{prefix}_drawer", "drawer"):
        btn("✕", f"{prefix}_dr_close", "x", on_click=close_report, args=(prefix,))
        html(f'<div class="dr-header"><div class="dr-title">{h(r["room"])} &mdash; {unit_label(r["unit"])}</div>'
             f'<span>{report_pill(r["status"])}</span></div>'
             f'<div class="drawer-sub">{h(rid)}</div>'
             f'<div class="dr-meta-grid"><div><div class="drawer-label">Reported by</div>'
             f'<div class="drawer-value">{h(r["teacher"])}</div></div>'
             f'<div><div class="drawer-label">Date &amp; time</div><div class="drawer-value">{h(r["date"])}</div></div></div>'
             f'<div class="drawer-row"><div class="drawer-label">Issue type(s)</div>{issue_tags(r["issues"])}</div>'
             f'<div class="drawer-row" style="border-bottom:none;padding-bottom:0;"><div class="drawer-label">Teacher\'s comment</div>'
             f'<div class="drawer-comment-box">{h(r["comment"] or "No additional comment.")}</div></div>'
             f'<div style="height:16px"></div>')
        btn("View unit profile", f"{prefix}_dr_unit", "ghostsm", full=True, icon=":material/computer:",
            on_click=open_unit, args=(prefix, r["room"], r["unit"]))

        resolved = r["status"] == "resolved"
        if on_action is None:  # view-only: show the technician note
            label = "Solution logged" if resolved else "Technician's note"
            text = r["note"] or ("No solution note was left." if resolved
                                 else "The technician hasn't logged anything on this yet.")
            html(f'<div style="margin-top:18px;"><div class="drawer-label">{label}</div>'
                 f'<div class="drawer-comment-box" style="font-style:normal;">{h(text)}</div></div>')
            return
        if resolved:
            html(f'<div style="margin-top:18px;"><div class="drawer-label">Solution logged</div>'
                 f'<div class="drawer-comment-box" style="font-style:normal;">{h(r["note"] or "No solution note was left.")}</div></div>')
            return

        note_key = f"{prefix}_note_{rid}"
        picked_key = f"{prefix}_picked_{rid}"
        if note_key not in ss:
            ss[note_key] = r["note"] or ""
        with box(f"{prefix}_dr_ai", "aibox"):
            html(f'<div class="ai-box-head">{icon("robot", 15)} AI-suggested solutions</div>'
                 '<p class="ai-box-sub">Based on the reported issue. Tap one to drop it into the note below, '
                 'then edit as needed.</p>')
            with box(f"{prefix}_dr_aichips", "aichips"):
                for i, text in enumerate(suggestions_for(r["issues"])):
                    btn(text, f"{prefix}_sug_{rid}_{i}", "aichipon" if ss.get(picked_key) == i else "aichip",
                        on_click=_apply_suggestion, args=(note_key, picked_key, i, text))
        html('<label class="field-label" style="margin-top:16px;">Solution / notes</label>')
        st.text_area("Solution / notes", key=note_key, label_visibility="collapsed",
                     placeholder="What did you do to fix this? (required before resolving or flagging)")
        with box(f"{prefix}_dr_actions", "actions"):
            btn("Needs follow-up", f"{prefix}_fu_{rid}", "dghost", full=True, icon=":material/warning:",
                on_click=on_action, args=(r, "followup", note_key))
            btn("Mark as resolved", f"{prefix}_res_{rid}", "success", full=True, icon=":material/check:",
                on_click=on_action, args=(r, "resolved", note_key))


# ===========================================================================
# Unit inventory
# ===========================================================================
_MONITOR_GREY = _svg(ICON_PATHS["monitor"], 34, 1.6).replace("currentColor", "#7c93c0")


def spec_table(data: dict) -> str:
    return ('<table class="spec-table">' + "".join(
        f'<tr><td class="spec-key">{h(k)}</td><td class="spec-val">{h(v)}</td></tr>' for k, v in data.items())
        + "</table>")


def history_html(history: list[dict]) -> str:
    if not history:
        return '<div style="padding:20px 0;color:var(--ink-500);font-size:13.5px;">No issues reported for this unit yet.</div>'
    out = []
    for item in history:
        comment = (f'<div class="history-comment">&ldquo;{h(item["comment"])}&rdquo;</div>' if item.get("comment") else "")
        out.append(f'<div class="history-item"><div class="history-rail"><div class="history-dot" '
                   f'style="background:var(--{HIST_COLOR.get(item.get("status"), "amber")});"></div></div>'
                   f'<div class="history-body"><div class="history-issue">{h(item.get("issue"))}</div>{comment}'
                   f'<div class="history-action">{h(history_sentence(item))}</div></div></div>')
    return "".join(out)


def inventory_page(prefix: str, lab: Lab, subtitle: str,
                   tabs: tuple[str, ...] = ("hardware", "software", "system", "history")) -> None:
    unit = ss.get(f"{prefix}_unit")
    if unit:
        return unit_detail(prefix, lab, unit[0], unit[1], tabs)

    page_header("Assets", "Unit Inventory", subtitle)
    room_key = f"{prefix}_inv_room"
    room = ss.get(room_key) if ss.get(room_key) in lab.rooms else lab.rooms[0]
    with box(f"{prefix}_roomtabs", "roomtabs"):
        for r in lab.rooms:
            btn(room_label(r), f"{prefix}_rt_{r}", "rtabon" if r == room else "rtab",
                on_click=set_sticky, args=(room_key, r))

    total = lab.counts.get(room, 0)
    filters = ["all", "good", "issue", "replace"]
    names = {"all": "All", "good": "Good", "issue": "Have issue", "replace": "Need replacement"}
    with box(f"{prefix}_inv_tb", "rowbetween", "mb16"):
        html(f'<div style="font-size:13px;color:var(--ink-500);"><span>{total}</span> computer(s)</div>')
        flt_key = sticky(f"{prefix}_inv_filter__invfilter__", filters)
        flt = st.radio("Show", filters, format_func=names.get, horizontal=True, key=flt_key,
                       label_visibility="collapsed")
        remember(flt_key)

    units = [n for n in range(1, total + 1) if flt == "all" or lab.status(room, n) == flt]
    if not units:
        html('<div style="padding:40px;text-align:center;color:var(--ink-500);">No units match this filter.</div>')
        return
    with box(f"{prefix}_unitgrid", "unitgrid"):
        for n in units:
            status = lab.status(room, n)
            dot = "" if status == "good" else f'<span class="dot {UNIT_STATUS[status][1]} status-dot"></span>'
            hit(f'<div class="unit-card">{dot}{_MONITOR_GREY}<div class="unit-card-name">{unit_label(n)}</div></div>',
                f"{prefix}_u_{room}_{n}", open_unit, (prefix, room, n))


def unit_detail(prefix: str, lab: Lab, room: str, n: int, tabs: tuple[str, ...]) -> None:
    btn("Back to Unit Inventory", f"{prefix}_unit_back", "back", icon=":material/chevron_left:",
        on_click=close_unit, args=(prefix,))
    status = lab.status(room, n)
    d = lab.detail(room, n)
    label, color = UNIT_STATUS[status]
    html(f'<div class="unit-detail-header" style="margin-bottom:20px;"><div><div class="unit-title-row">'
         f'<div class="unit-h1">{unit_label(n)}</div><span class="pill {color}">{h(label)}</span></div>'
         f'<p style="color:var(--ink-500);font-size:13px;margin:6px 0 0;">{h(room_label(room))}</p></div></div>')

    names = {"hardware": "Hardware", "software": "Software", "system": "System", "history": "Maintenance history"}
    tab_key = f"{prefix}_dtab"
    tab = ss.get(tab_key) if ss.get(tab_key) in tabs else tabs[0]
    main, side = st.columns([2.6, 1], gap="medium")
    with main:
        with box(f"{prefix}_dtabs", "tabsrow"):
            for t in tabs:
                btn(names[t], f"{prefix}_dt_{t}", "tabbtnon" if t == tab else "tabbtn", on_click=_set, args=(tab_key, t))
        if tab == "software":
            body = '<ul class="sw-list">' + "".join(
                f'<li><span class="sw-name">{h(a)}</span><span class="sw-meta">{h(b)}</span></li>'
                for a, b in d["software"]) + "</ul>"
        elif tab == "history":
            body = history_html(d["history"])
        else:
            body = spec_table(d[tab])
        html(f'<div class="card" style="padding:22px;">{body}</div>')
    with side:
        html(f'<div class="card side-card"><h4>Issues logged</h4><div class="issue-count-big">{len(d["history"])}</div>'
             f'<div class="issue-count-label">total reports on this unit</div></div>'
             f'<div class="card side-card"><h4>Lifecycle</h4>{spec_table(d["lifecycle"])}</div>')


# ===========================================================================
# Error analytics
# ===========================================================================
def analytics_page(prefix: str, lab: Lab, reports: list[dict]) -> None:
    page_header("Insights", "Error Analytics", "Which units and rooms need the most attention.")
    keys = set(lab.details) | {unit_key(r["room"], r["unit"]) for r in reports}
    newest = sorted(reports, key=lambda r: r["when"], reverse=True)

    def info(key: str):
        room, n = split_key(key)
        d = lab.details.get(key)
        if d:
            last = d["history"][0] if d["history"] else {}
            return room, n, len(d["history"]), last.get("issue", "—"), last.get("date", "—")
        mine = [r for r in newest if r["room"] == room and r["unit"] == n]
        last = mine[0] if mine else None
        return (room, n, len(mine), (last["issues"][0] if last and last["issues"] else "—"),
                (last or {}).get("date", "—"))

    ranked = sorted((u for u in map(info, keys) if u[2] > 0), key=lambda u: -u[2])[:6]
    room_stats = []
    for room in lab.rooms:
        s = lab.room_summary(room)
        room_stats.append((room, s["issue"] + s["replace"], lab.counts.get(room, 0)))
    types = issue_counts(reports)
    if lab.sample:  # the sample design also counts the older unit history
        for d in lab.details.values():
            for item in d["history"]:
                types[item["issue"]] = types.get(item["issue"], 0) + 1
    top_type = max(types.items(), key=lambda kv: kv[1]) if types else None
    top_room = max(room_stats, key=lambda r: r[1]) if room_stats else ("—", 0, 0)

    stat_row([
        ("Units with errors", sum(r[1] for r in room_stats), f"across all {len(lab.rooms)} labs", "amber", "monitor"),
        ("Most affected room", "CL " + top_room[0].split(" ")[-1], f"{top_room[1]} units flagged", "blue", "flag"),
        ("Most common issue", top_type[0] if top_type else "—", f"{top_type[1]} reports" if top_type else "",
         "purple", "clock"),
        ("Flagged for inspection", sum(1 for u in ranked if u[2] >= 5), "5+ repeat reports", "red", "flag"),
    ])
    rows = "".join(
        f'<tr><td class="rep-id">{i + 1}</td><td><div class="rep-unit">Centrum Lab {h(room.split(" ")[-1])} &mdash; '
        f'{unit_label(n)}</div></td><td style="font-weight:700;color:var(--ink-900);">{count}</td>'
        f'<td><div class="issue-tags"><span class="issue-tag">{h(issue)}</span></div></td>'
        f'<td style="white-space:nowrap;color:var(--ink-500);">{h(date)}</td>'
        f'<td>{pill("Escalated", "red") if count >= 5 else pill("Watching", "amber")}</td></tr>'
        for i, (room, n, count, issue, date) in enumerate(ranked))
    room_bars = "".join(
        f'<div class="room-health-row"><div class="room-health-name">Centrum Lab {h(room.split(" ")[-1])}</div>'
        f'<div class="issuetype-bar-wrap"><div class="issuetype-bar" style="width:{(bad / total * 100) if total else 0:.1f}%;'
        f'background:var(--amber);"></div></div><div class="room-health-count">{bad} / {total}</div></div>'
        for room, bad, total in room_stats)
    html(f'<div class="card section-card" style="margin-bottom:18px;overflow:hidden;padding:0;">'
         f'<div class="section-head" style="padding:20px 22px 0;"><div class="sh3">Most Frequently Reported Units</div></div>'
         f'<table class="reports-table" style="margin-top:8px;"><thead><tr><th>#</th><th>Unit</th><th>Reports</th>'
         f'<th>Most common issue</th><th>Last reported</th><th>Status</th></tr></thead><tbody>{rows}</tbody></table></div>'
         f'<div class="analytics-grid"><div class="card section-card"><div class="section-head"><div class="sh3">'
         f'Units With Errors, by Room</div></div>{room_bars}</div>'
         f'<div class="card section-card"><div class="section-head"><div class="sh3">Most Common Issue Types</div></div>'
         f'{issuetype_rows(types)}</div></div>')


# ===========================================================================
# Escalation
# ===========================================================================
ESCALATION_STATES = ["Pending review", "Under inspection", "Cleared"]


def escalation_page(prefix: str, lab: Lab, on_change) -> None:
    """on_change(key, room, n, widget_key) saves a new status; None means view-only."""
    page_header("Insights", "Escalation", "Units flagged for deeper inspection." + ("" if on_change else " View only."))
    html(f'<div class="escalation-banner">{icon("warning", 20)}<div class="escalation-banner-text">A unit is flagged '
         'here automatically once it\'s been reported <b>5 or more times</b> &mdash; repeated fixes that aren\'t sticking '
         'usually mean the root problem hasn\'t been found yet, so it\'s worth a full inspection instead of another '
         'quick patch.</div></div>')
    units = lab.escalated()
    if not units:
        html('<div class="card" style="padding:50px;text-align:center;color:var(--ink-500);">'
             'No units are currently escalated.</div>')
    for key, room, n, history in units:
        with box(f"{prefix}_esc_{key}", "card", "esc"):
            chips = "".join(f'<span class="esc-timeline-chip">{h(str(x["date"]).split(" ·")[0])}</span>'
                            for x in history[:5])
            html(f'<div class="esc-top"><div><div class="esc-unit">Centrum Laboratory {h(room.split(" ")[-1])} &mdash; '
                 f'{unit_label(n)}</div><div class="esc-room">Repeatedly reported for: {h(history[0]["issue"])}</div></div>'
                 f'<div class="esc-count-box"><div class="esc-count-num">{len(history)}</div>'
                 f'<div class="esc-count-label">REPORTS</div></div></div><div class="esc-timeline">{chips}</div>')
            current = lab.escalation.get(key) or "Pending review"
            options = ESCALATION_STATES + ([current] if current not in ESCALATION_STATES else [])
            widget = f"{prefix}_escsel_{key}__fsel__"
            if widget not in ss:
                ss[widget] = current
            with box(f"{prefix}_escfoot_{key}", "rowbetween"):
                st.selectbox("Escalation status", options, key=widget, disabled=on_change is None,
                             label_visibility="collapsed", on_change=on_change,
                             args=(key, room, n, widget) if on_change else None)
                btn("View full history", f"{prefix}_eschist_{key}", "ghostsm", icon=":material/computer:",
                    on_click=open_unit, args=(prefix, room, n))


# ===========================================================================
# Settings
# ===========================================================================
def password_strength(pw: str) -> tuple[str, str, str]:
    score = sum([len(pw) >= 8, bool(re.search(r"[A-Z]", pw)), bool(re.search(r"\d", pw)),
                 bool(re.search(r"[^A-Za-z0-9]", pw))])
    return [("25%", "var(--red)", "Weak"), ("25%", "var(--red)", "Weak"), ("50%", "var(--amber)", "Fair"),
            ("75%", "#3b82f6", "Good"), ("100%", "var(--green)", "Strong")][score]


def _submit_password(prefix: str, handler) -> None:
    cur, new, conf = (ss.get(f"{prefix}_pw_{k}") or "" for k in ("cur", "new", "conf"))
    if not cur or not new or not conf:
        return flash(prefix, "Fill in all three password fields", ok=False)
    if new != conf:
        return flash(prefix, "The new passwords don't match", ok=False)
    ok, message = handler(cur, new)
    flash(prefix, message, ok)
    if ok:
        for k in ("cur", "new", "conf"):
            ss[f"{prefix}_pw_{k}"] = ""


def _save_field(prefix: str, field: str, handler) -> None:
    value = (ss.get(f"{prefix}_edit_{field}_in") or "").strip()
    if not value:
        return flash(prefix, "Enter a value first", ok=False)
    ok, message = handler(value)
    flash(prefix, message, ok)
    if ok:
        ss.pop(f"{prefix}_editing_{field}", None)


def _start_edit(prefix: str, field: str, current: str) -> None:
    ss[f"{prefix}_editing_{field}"] = True
    ss[f"{prefix}_edit_{field}_in"] = current if current and current.lower() != "not set" else ""


def _inline_edit(prefix: str, field: str, placeholder: str, handler, pad: str = "0") -> None:
    with box(f"{prefix}_inl_{field}", "gapsm"):
        st.text_input(field, key=f"{prefix}_edit_{field}_in", placeholder=placeholder, label_visibility="collapsed")
        with box(f"{prefix}_inl_{field}_btns", "row"):
            btn("Save", f"{prefix}_inl_{field}_save", "primarysm", on_click=_save_field, args=(prefix, field, handler))
            btn("Cancel", f"{prefix}_inl_{field}_cancel", "ghostsm", on_click=ss.pop,
                args=(f"{prefix}_editing_{field}", None))
        html(f'<div style="height:{pad}"></div>')


def settings_page(prefix: str, user: dict, *, profile_style: str, notifications: list[tuple[str, str, bool]],
                  notif_intro: str, save_number, save_email=None, email_message: str = "",
                  change_password) -> None:
    """profile_style 'teacher' or 'staff'. Handlers return (ok, message)."""
    page_header("System", "Settings", "Manage your profile, notifications, and password.")
    tab = ss.get(f"{prefix}_stab") or "profile"
    menu, content = st.columns([1, 2.9], gap="medium")
    with menu:
        with box(f"{prefix}_smenu", "card", "settingsmenu"):
            for key, label, color, icon_name in (("profile", "Profile", "purple", "user"),
                                                 ("notifications", "Notifications", "orange", "bell"),
                                                 ("security", "Password and Security", "blue", "lock")):
                active = " active" if key == tab else ""
                last = ' style="border-bottom:none;"' if key == "security" else ""
                hit(f'<div class="settings-menu-item{active}"{last}><span class="settings-menu-icon {color}">'
                    f'{icon(icon_name, 16)}</span><span class="settings-menu-label">{label}</span></div>',
                    f"{prefix}_smenu_{key}", _set, (f"{prefix}_stab", key))
        btn("Logout", f"{prefix}_settings_logout", "logout", on_click=logout_user)

    with content:
        if tab == "notifications":
            with box(f"{prefix}_notif", "card", "settingscard"):
                html(f'<div class="settings-card-title">Notification preferences</div>'
                     f'<p class="helptext" style="margin:-8px 0 18px;">{h(notif_intro)}</p>')
                for i, (title, sub, default) in enumerate(notifications):
                    marks = ("togglerow", "nolast") if i == len(notifications) - 1 else ("togglerow",)
                    with box(f"{prefix}_notif_row_{i}", *marks):
                        html(f'<div><div class="toggle-row-title">{h(title)}</div>'
                             f'<div class="toggle-row-sub">{h(sub)}</div></div>')
                        st.toggle(title, value=default, key=f"{prefix}_notif_{i}", label_visibility="collapsed")
                with box(f"{prefix}_notif_foot", "rowend"):
                    btn("Save changes", f"{prefix}_notif_save", "primary", on_click=flash,
                        args=(prefix, "Notification preferences saved"))
        elif tab == "security":
            with box(f"{prefix}_pw", "card", "settingscard"):
                html('<div class="settings-card-title">Change password</div>')
                field_label("Current password")
                st.text_input("Current password", type="password", key=f"{prefix}_pw_cur",
                              placeholder="Enter current password", label_visibility="collapsed")
                html('<div style="height:20px"></div>')
                a, b = st.columns(2, gap="small")
                with a:
                    field_label("New password")
                    new = st.text_input("New password", type="password", key=f"{prefix}_pw_new",
                                        placeholder="At least 8 characters", label_visibility="collapsed")
                with b:
                    field_label("Confirm new password")
                    st.text_input("Confirm new password", type="password", key=f"{prefix}_pw_conf",
                                  placeholder="Re-enter new password", label_visibility="collapsed")
                if new:
                    width, color, label = password_strength(new)
                    html(f'<div class="pw-strength" style="margin:14px 0 0;"><div class="pw-strength-bar">'
                         f'<div class="pw-strength-fill" style="width:{width};background:{color};"></div></div>'
                         f'<div class="helptext">{label}</div></div>')
                with box(f"{prefix}_pw_foot", "rowend"):
                    html('<div style="height:12px"></div>')
                    btn("Update password", f"{prefix}_pw_save", "primary", on_click=_submit_password,
                        args=(prefix, change_password))
            with box(f"{prefix}_sessions", "card", "settingscard"):
                html('<div class="settings-card-title">Active sessions</div>'
                     '<p class="helptext" style="margin:-8px 0 16px;">Sign out from other devices you may have logged into.</p>')
                with box(f"{prefix}_sessions_row", "row"):
                    btn("Sign out of other devices", f"{prefix}_signout_all", "dghostsm",
                        on_click=flash, args=(prefix, "Signed out of all other sessions"))
        elif profile_style == "teacher":
            _teacher_profile(prefix, user, save_number)
        else:
            _staff_profile(prefix, user, save_number, save_email, email_message)


def _staff_profile(prefix: str, user: dict, save_number, save_email, email_message: str) -> None:
    """Technician profile card."""
    with box(f"{prefix}_profile", "card", "settingscard"):
        html(f'<div class="settings-card-title">Profile</div><div class="profile-row">'
             f'<div class="avatar-lg">{h(initials(user["name"]))}</div><div>'
             f'<div class="profile-fixed-name">{h(user["name"])}</div>'
             f'<div class="helptext" style="margin-top:4px;">Your name is set on your account and can\'t be changed.</div>'
             f'</div></div>')
        email, number = user.get("email") or "", user.get("contact_number") or ""
        for field, label, value, placeholder in (("email", "Email address", email, "you@isu.edu.ph"),
                                                 ("number", "Contact number", number, "09XX XXX XXXX")):
            marks = ("rowbetween", "fieldrow") + (("nolast",) if field == "number" else ())
            with box(f"{prefix}_pf_{field}", *marks):
                html(f'<div><div class="profile-field-label">{label}</div>'
                     f'<div class="profile-field-value">{h(value or "Not set")}</div></div>')
                if field == "email" and save_email is None:
                    btn("Edit" if value else "Add", f"{prefix}_pf_{field}_edit", "ghostsm",
                        on_click=flash, args=(prefix, email_message, False))
                else:
                    btn("Edit" if value or field == "number" else "Add", f"{prefix}_pf_{field}_edit", "ghostsm",
                        on_click=_start_edit, args=(prefix, field, value))
            if ss.get(f"{prefix}_editing_{field}"):
                _inline_edit(prefix, field, placeholder, save_number if field == "number" else save_email, "16px")


def _teacher_profile(prefix: str, user: dict, save_number) -> None:
    with box(f"{prefix}_profile", "card", "settingscard"):
        html('<div class="settings-card-title">Profile details</div>')
        with box(f"{prefix}_pf_photo", "row", "mb18"):
            html(f'<div class="avatar-lg">{h(initials(user["name"]))}</div>')
            with box(f"{prefix}_pf_photo_r", "gapsm"):
                btn("Change photo", f"{prefix}_pf_photo_btn", "ghostsm", on_click=flash,
                    args=(prefix, "Profile photos aren't available yet", False))
                html('<div class="helptext" style="margin-top:0;">JPG or PNG, up to 2MB.</div>')
        html(f'<div class="profile-fixed-block"><div class="profile-field-label">Full Name</div>'
             f'<div class="profile-fixed-name muted">{h(user["name"])}</div></div><hr class="profile-divider">'
             f'<div class="profile-field-label" style="margin-bottom:12px;">Contact info</div>')
        number = user.get("contact_number") or ""
        with box(f"{prefix}_pf_number", "row"):
            html(f'<div class="contact-info-row" style="margin:0;">{icon("phone", 15)}'
                 f'<span class="contact-info-value">{h(number or "Not set")}</span></div>')
            btn("", f"{prefix}_pf_number_edit", "pencil", icon=":material/edit:", help="Edit contact number",
                on_click=_start_edit, args=(prefix, "number", number))
        if ss.get(f"{prefix}_editing_number"):
            _inline_edit(prefix, "number", "09XX XXX XXXX", save_number, "6px")
        html(f'<div class="contact-info-row" style="margin-bottom:0;">{icon("mail", 15)}'
             f'<span class="contact-info-value">{h(user.get("email") or "Not set")}</span></div>')


def page_config(title: str) -> None:
    try:
        st.set_page_config(page_title=f"Centrum Laboratory - {title}", page_icon=page_icon(),
                           layout="wide", initial_sidebar_state="expanded")
    except st.errors.StreamlitAPIException:
        pass  # app.py already called set_page_config
