"""
frontend/lab_store.py - Computer Laboratory | the shared lab store

The backend has no endpoints yet for the computer inventory, maintenance logs,
teacher reports or notifications. So the frontend keeps them in ONE store
shared by every signed-in user of this Streamlit server, saved to

    <project>/data/centrum_lab.json

That way a computer a technician adds or edits shows up for the admin (and on
the teachers' floor map) straight away, a teacher's report reaches the
technicians, and notifications / "read" marks survive a restart.

    shared()                 -> the store dict (loaded once, reloaded if the file changes)
    save()                   -> write it back (call after every change)
    labs() / add_lab(info)   -> laboratories added in the app (Inventory -> Add laboratory)
    sync_labs()              -> register them in lab_data.LABS (called every run)
    record_account_date(...) -> remember when an account was confirmed /
                                cancelled / deactivated (shown when the
                                backend does not send that date itself)
    add_event(...)           -> a notification for some roles
    events_for(role, me)     -> the notifications one user may see
    read_ids(user) / mark_read(user, ids)

The inventory starts empty and is filled by frontend/seed_inventory.py (the
app also runs that idempotent seed once if the inventory is empty).
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from pathlib import Path

from frontend import lab_data as D

PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_FILE = Path(
    os.getenv("CENTRUM_DATA_FILE") or PROJECT_DIR / "data" / "centrum_lab.json"
)
MAX_EVENTS = 400
MAX_READ = 800

_LOCK = threading.RLock()
_STATE: dict = {"data": None, "mtime": None}


# ---------------------------------------------------------------------------
# JSON <-> store
# ---------------------------------------------------------------------------
def _dt(v):
    return v.isoformat() if hasattr(v, "isoformat") else v


def _comp_out(c: dict) -> dict:
    out = dict(c)
    out["added"], out["updated"] = _dt(c.get("added")), _dt(c.get("updated"))
    out["log"] = [{**e, "t": _dt(e["t"])} for e in c.get("log", [])]
    return out


def _comp_in(c: dict) -> dict:
    comp = D.new_computer(
        c["lab"],
        c["pc"],
        c.get("hardware") or {},
        c.get("software") or [],
        name=c.get("name", ""),
        notes=c.get("notes", ""),
        added=D.parse_dt(c.get("added")),
        brand=c.get("brand", ""),
        model=c.get("model", ""),
        serial=c.get("serial", ""),
        status=c.get("status", "Working"),
    )
    comp["updated"] = D.parse_dt(c.get("updated"))
    comp["log"] = [
        {**e, "t": D.parse_dt(e.get("t")) or D.now()} for e in c.get("log") or []
    ]
    return comp


def _report_out(r: dict) -> dict:
    out = dict(r)
    out["created"] = _dt(r["created"])
    out["history"] = [{**e, "t": _dt(e["t"])} for e in r["history"]]
    return out


def _report_in(r: dict) -> dict:
    out = dict(r)
    out["created"] = D.parse_dt(r.get("created")) or D.now()
    out["history"] = [
        {**e, "t": D.parse_dt(e.get("t")) or out["created"]}
        for e in r.get("history") or []
    ]
    out["local"] = True
    out.setdefault("urgency", "Normal")
    out.setdefault("esc_note", "")
    out.setdefault("tech", None)
    return out


def empty() -> dict:
    return {"version": 1, "computers": {}, "reports": [], "events": [], "read": {},
            "labs": [], "accounts": {}, "temp_pw": {}}


def load_file(path: Path = DATA_FILE) -> dict:
    """Read the store from disk (an empty store if the file is missing or broken)."""
    data = empty()
    if not path.is_file():
        return data
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        broken = path.with_suffix(".broken.json")
        try:
            path.replace(broken)  # keep the unreadable file for inspection, start fresh
        except OSError:
            pass
        return data
    for c in raw.get("computers") or []:
        try:
            comp = _comp_in(c)
        except (KeyError, TypeError, ValueError):
            continue
        data["computers"][(comp["lab"], comp["pc"])] = comp
    data["reports"] = [
        _report_in(r)
        for r in raw.get("reports") or []
        if isinstance(r, dict) and "id" in r
    ]
    data["events"] = [
        {**e, "t": D.parse_dt(e.get("t")) or D.now()}
        for e in raw.get("events") or []
        if isinstance(e, dict)
    ]
    data["read"] = {
        str(k): list(v)
        for k, v in (raw.get("read") or {}).items()
        if isinstance(v, list)
    }
    data["labs"] = [l for l in raw.get("labs") or [] if isinstance(l, dict) and l.get("id")]
    data["accounts"] = {
        str(k): dict(v)
        for k, v in (raw.get("accounts") or {}).items()
        if isinstance(v, dict)
    }
    data["temp_pw"] = {
        str(k).lower(): str(v) for k, v in (raw.get("temp_pw") or {}).items()
    }
    return data


def save_file(data: dict, path: Path = DATA_FILE) -> None:
    """Write the store atomically (temp file + rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    out = {
        "version": 1,
        "computers": [_comp_out(c) for _, c in sorted(data["computers"].items())],
        "reports": [_report_out(r) for r in data["reports"]],
        "events": [{**e, "t": _dt(e["t"])} for e in data["events"][-MAX_EVENTS:]],
        "read": {k: v[-MAX_READ:] for k, v in data["read"].items()},
        "labs": list(data.get("labs") or []),
        "accounts": dict(data.get("accounts") or {}),
        "temp_pw": dict(data.get("temp_pw") or {}),
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------------------
# The shared, in-memory copy
# ---------------------------------------------------------------------------
def _mtime() -> float | None:
    try:
        return DATA_FILE.stat().st_mtime
    except OSError:
        return None


def shared() -> dict:
    """The store every dashboard works on. Reloaded when the file was changed by
    someone else (e.g. the seed script was run while the app is open)."""
    with _LOCK:
        m = _mtime()
        if _STATE["data"] is None or (m is not None and m != _STATE["mtime"]):
            data = load_file()
            # Laboratories and computers come from the database only
            # (lab_data.register_db_labs); the "labs" kept in this file are
            # no longer used.
            if not data["computers"]:
                try:  # first run: fill the inventory once (idempotent)
                    from frontend import seed_inventory

                    seed_inventory.seed(data)
                except Exception:  # never block the app because of the seed
                    pass
            _STATE["data"] = data
            _write(data)
        return _STATE["data"]


def _write(data: dict) -> None:
    try:
        save_file(data)
        _STATE["mtime"] = _mtime()
    except OSError:
        _STATE["mtime"] = _mtime()  # read-only folder: keep working in memory


def save() -> None:
    with _LOCK:
        if _STATE["data"] is not None:
            _write(_STATE["data"])


def lock():
    return _LOCK


# ---------------------------------------------------------------------------
# Connecting a dashboard's store to the shared one (every run)
# ---------------------------------------------------------------------------
def attach(store: dict) -> dict:
    """Point a dashboard store at the shared inventory and reports.

    - computers: the database's computers only (empty when not connected).
    - reports:   live -> the backend's reports + teacher reports kept here;
                 offline -> the reports kept here.
    """
    data = shared()
    # The inventory is the database's (Computers / ComputerHardware /
    # ComputerSoftware / MaintenanceHistory): never the copy in this file.
    store.pop("units", None)
    store["computers"] = store.get("computers") if store.get("live") else {}
    if store.get("live"):
        store["reports"] = list(store.get("backend_reports") or []) + [
            r for r in data["reports"] if r.get("local")
        ]
    else:
        store["reports"] = data["reports"]
    return store


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------
def add_event(
    kind: str,
    title: str,
    sub: str,
    roles: tuple[str, ...],
    actor: str = "",
    to: str = "",
    ref: tuple | None = None,
    save_now: bool = True,
) -> dict:
    """kind: inventory | maintenance | report | status | escalation. roles: who sees it.
    to: only this person (e.g. the teacher who sent the report). actor never sees their own event.
    """
    e = {
        "id": uuid.uuid4().hex[:12],
        "t": D.now(),
        "kind": kind,
        "title": title,
        "sub": sub,
        "roles": [r.lower() for r in roles],
        "actor": actor,
        "to": to,
        "ref": list(ref) if ref else None,
    }
    with _LOCK:
        data = shared()
        data["events"].append(e)
        del data["events"][:-MAX_EVENTS]
        if save_now:
            save()
    return e


def events_for(role: str, me: str, limit: int = 40) -> list[dict]:
    role = role.lower()
    out = [
        e
        for e in shared()["events"]
        if role in e.get("roles", [])
        and e.get("actor") != me
        and (not e.get("to") or e.get("to") == me)
    ]
    return sorted(out, key=lambda e: e["t"], reverse=True)[:limit]


def read_ids(user: str) -> set[str]:
    return set(shared()["read"].get(user, []))


def mark_read(user: str, ids) -> None:
    ids = [i for i in ids if i]
    if not ids:
        return
    with _LOCK:
        data = shared()
        have = data["read"].setdefault(user, [])
        known = set(have)
        have.extend(i for i in ids if i not in known)
        del have[:-MAX_READ]
        save()


# ---------------------------------------------------------------------------
# Laboratories added in the app
# ---------------------------------------------------------------------------
LAB_FIELDS = ("id", "name", "code", "building", "wing", "floor", "room", "units",
              "cols", "layout", "desc", "specs", "created", "created_by")


def labs() -> list[dict]:
    return list(shared().get("labs") or [])


# The saved laboratory details label the database rooms (lab_data.register_db_labs).
D.LAB_DETAILS = lambda: labs()


def sync_labs() -> None:
    """Kept for the callers: laboratories now come from the database only
    (lab_data.register_db_labs, when the dashboard data is loaded), so the
    ones saved in this file are not registered any more."""
    return None


def add_lab(info: dict) -> dict:
    """Save a new laboratory (info has the LAB_FIELDS) and register it."""
    lab = {k: info.get(k) for k in LAB_FIELDS if info.get(k) is not None}
    lab["created"] = _dt(lab.get("created") or D.now())
    with _LOCK:
        data = shared()
        data.setdefault("labs", [])
        room = " ".join(str(lab.get("room") or lab.get("name") or "").split()).lower()
        data["labs"] = [
            l for l in data["labs"]
            if l.get("id") != lab["id"]
            and " ".join(str(l.get("room") or l.get("name") or "").split()).lower() != room
        ] + [lab]
        save()
    D.register_labs([lab])
    return lab


def update_lab(lab_id: int, changes: dict) -> dict | None:
    with _LOCK:
        data = shared()
        for l in data.setdefault("labs", []):
            if l.get("id") == lab_id:
                l.update({k: v for k, v in changes.items() if k in LAB_FIELDS})
                save()
                D.register_labs([l])
                return l
    return None


# ---------------------------------------------------------------------------
# Account dates (confirmation / cancellation / deactivation)
# ---------------------------------------------------------------------------
def record_account_date(user_id, what: str, by: str = "") -> None:
    """what: confirmed | cancelled | deactivated | reactivated."""
    if user_id in (None, ""):
        return
    with _LOCK:
        data = shared()
        rec = data.setdefault("accounts", {}).setdefault(str(user_id), {})
        rec[f"{what}_at"] = _dt(D.now())
        if by:
            rec[f"{what}_by"] = by
        save()


def account_dates(user_id) -> dict:
    rec = (shared().get("accounts") or {}).get(str(user_id)) or {}
    return {k: (D.parse_dt(v) if k.endswith("_at") else v) for k, v in rec.items()}


# ---------------------------------------------------------------------------
# Temporary passwords: accounts that must choose their own password at the
# first login (set when an Admin creates an account with a temporary password).
# Only the email and the date are kept here - never the password.
# ---------------------------------------------------------------------------
def mark_temp_password(email: str) -> None:
    email = (email or "").strip().lower()
    if not email:
        return
    with _LOCK:
        shared().setdefault("temp_pw", {})[email] = _dt(D.now())
        save()


def needs_password_change(email: str) -> bool:
    email = (email or "").strip().lower()
    return bool(email) and email in (shared().get("temp_pw") or {})


def clear_temp_password(email: str) -> None:
    email = (email or "").strip().lower()
    with _LOCK:
        if (shared().get("temp_pw") or {}).pop(email, None) is not None:
            save()
