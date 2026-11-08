"""
Centrum Laboratory - the computer inventory, read from and saved to Supabase.

Used by the Admin and Technician Inventory pages (no local JSON copy).

Tables (no schema changes):

    Computers           Room, UnitNumber, Status (computer_status enum,
                        DEFAULT 'Working'), EscalationStatus (DEFAULT
                        'Pending review'), Brand, Model, SerialNumber,
                        DateAdded, LastServiced, CreatedAt, UpdatedAt
                        UNIQUE (Room, UnitNumber), UnitNumber > 0
    ComputerHardware    one row per computer: Processor, Ram, Storage,
                        Graphics, Monitor, Peripherals, OperatingSystem
    ComputerSoftware    SoftwareName, Version, DateInstalled
    MaintenanceHistory  ComputerId, TechnicianId, Description, DatePerformed
                        (optional: everything works without it, the
                        history just isn't saved)

Every change to a computer also adds its lines to MaintenanceHistory
("<kind> — <what changed>"), which is what the "Maintenance history" tab
shows, and stamps Computers.UpdatedAt (and LastServiced for maintenance).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from . import technician_service as tech
from .users_repository import DatabaseError, _run

logger = logging.getLogger("centrum.inventory")

COMPUTERS = tech.COMPUTERS_TABLE
HARDWARE = tech.COMPUTER_HARDWARE_TABLE
SOFTWARE = tech.COMPUTER_SOFTWARE_TABLE
MAINTENANCE = tech.MAINTENANCE_TABLE

# Screen label -> ComputerHardware column.
HW_COLUMNS = {
    "Processor": "Processor",
    "Memory (RAM)": "Ram",
    "Storage": "Storage",
    "Graphics": "Graphics",
    "Monitor": "Monitor",
    "Keyboard & mouse": "Peripherals",
    "Operating system": "OperatingSystem",
}

# Computers columns the inventory edits (payload key -> column).
DETAIL_COLUMNS = {
    "brand": "Brand",
    "model": "Model",
    "serial": "SerialNumber",
    "status": "Status",
}

MAX_TEXT = 500
DESCRIPTION_SEPARATOR = " — "


# =========================================================
# HELPERS
# =========================================================


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return date.today().isoformat()


def _clean(value, limit: int = MAX_TEXT) -> str:
    return " ".join(str(value or "").split())[:limit]


def _room(value) -> str:
    return " ".join(str(value or "").split())


def _fail(message: str, code: str = "") -> dict:
    out = {"success": False, "error": message}
    if code:
        out["code"] = code
    return out


def _db_error(error: DatabaseError, what: str) -> dict:
    """A DatabaseError -> a message that says what the database refused."""
    detail = str(getattr(error, "detail", "") or "").lower()
    if "invalid input value for enum" in detail or "22p02" in detail:
        return _fail(
            f"The database doesn't accept that computer status ({what}). "
            "Pick another status.",
            "invalid_status",
        )
    if error.code == "duplicate":
        return _fail(
            "That laboratory and computer number are already in the database "
            "(each Room and UnitNumber must be unique).",
            "duplicate",
        )
    if error.code == "check":
        return _fail("The database refused one of the values (check constraint).", "check")
    return _fail(str(error), error.code or "")


def _actor_id(user: dict) -> int | None:
    """Users.UserId of the signed-in user (None for the built-in admin)."""
    for key in ("user_id", "id"):
        n = tech._parse_int((user or {}).get(key))
        if n is not None:
            return n
    return None


def _actor_name(user: dict) -> str:
    user = user or {}
    name = f"{user.get('first_name') or ''} {user.get('last_name') or ''}".strip()
    return name or str(user.get("email") or "Staff")


def _get_computer(computer_id) -> dict | None:
    cid = tech._parse_int(computer_id)
    if cid is None:
        return None
    rows = _run(
        "reading a computer",
        lambda c: c.table(COMPUTERS).select("ComputerId,Room,UnitNumber,Status").eq("ComputerId", cid).execute().data or [],
    )
    return rows[0] if rows else None


def _update_computer_row(computer_id: int, values: dict) -> None:
    """Update Computers (UpdatedAt stamped). Optional columns that don't
    exist are dropped and the update retried."""
    values = {**values, "UpdatedAt": _now()}
    while True:
        try:
            _run(
                "updating a computer",
                lambda c: c.table(COMPUTERS).update(values).eq("ComputerId", computer_id).execute(),
            )
            return
        except DatabaseError as error:
            missing = _missing_column(error, values)
            if not missing:
                raise
            values.pop(missing)


def _missing_column(error: DatabaseError, values: dict) -> str | None:
    if error.code != "missing_column":
        return None
    detail = str(getattr(error, "detail", "") or "")
    for key in values:
        if key != "UpdatedAt" and (f"'{key}'" in detail or f'"{key}"' in detail):
            return key
    for key in ("LastServiced", "DateAdded", "Model", "Brand", "SerialNumber"):
        if key in values:
            return key
    return None


def add_history(computer_id: int, lines, user: dict, done_by: str = "") -> int:
    """Add maintenance lines [{kind, text}] to MaintenanceHistory.
    Best effort: returns how many were saved (0 if the table is missing)."""
    rows = []
    actor = _actor_id(user)
    who = _clean(done_by, 80)
    for line in lines or []:
        if not isinstance(line, dict):
            continue
        kind = _clean(line.get("kind"), 60) or "Other"
        text = _clean(line.get("text"))
        if not text:
            continue
        if who and who.lower() != _actor_name(user).lower():
            text = f"{text} (done by {who})"
        rows.append(
            {
                "ComputerId": computer_id,
                "TechnicianId": actor,
                "Description": f"{kind}{DESCRIPTION_SEPARATOR}{text}"[:MAX_TEXT * 2],
                "DatePerformed": _now(),
            }
        )
    if not rows:
        return 0
    try:
        _run("saving the maintenance history", lambda c: c.table(MAINTENANCE).insert(rows).execute())
    except DatabaseError as error:
        logger.warning("Maintenance history not saved for computer %s: %s", computer_id, error)
        return 0
    return len(rows)


# =========================================================
# HARDWARE
# =========================================================


def _save_hardware(computer_id: int, hardware: dict) -> None:
    """Write the hardware labels to the computer's ComputerHardware row
    (updated when it exists, created otherwise)."""
    values = {
        col: _clean(hardware.get(label), 255) or None
        for label, col in HW_COLUMNS.items()
        if label in hardware
    }
    if not values:
        return
    existing = _run(
        "reading the computer's hardware",
        lambda c: c.table(HARDWARE).select("HardwareId").eq("ComputerId", computer_id).order("HardwareId").execute().data or [],
    )
    if existing:
        hid = existing[-1].get("HardwareId")
        _run(
            "saving the computer's hardware",
            lambda c: c.table(HARDWARE).update(values).eq("HardwareId", hid).execute(),
        )
        return
    row = {"ComputerId": computer_id, **values}
    try:
        _run("saving the computer's hardware", lambda c: c.table(HARDWARE).insert(row).execute())
    except DatabaseError as error:
        # HardwareId is not an identity column in some databases: give it the
        # next number and try again.
        if error.code not in ("not_null",):
            raise
        rows = _run(
            "reading hardware ids",
            lambda c: c.table(HARDWARE).select("HardwareId").order("HardwareId", desc=True).limit(1).execute().data or [],
        )
        next_id = (tech._parse_int(rows[0].get("HardwareId")) or 0) + 1 if rows else 1
        _run(
            "saving the computer's hardware",
            lambda c: c.table(HARDWARE).insert({"HardwareId": next_id, **row}).execute(),
        )


# =========================================================
# COMPUTERS
# =========================================================


def create_computer(user: dict, data: dict) -> dict:
    """Add one computer: a Computers row (+ hardware, software, history)."""
    room = _room(data.get("room"))
    unit = tech._parse_int(data.get("unit_number"))
    if not room:
        return _fail("Pick a laboratory.")
    if unit is None or not 1 <= unit <= 999:
        return _fail("Enter the computer's seat number in the laboratory (1–999).")

    existing = tech._select_all(COMPUTERS, "ComputerId,Room,UnitNumber,SerialNumber", "ComputerId")
    if any(_room(r.get("Room")).lower() == room.lower() and tech._parse_int(r.get("UnitNumber")) == unit for r in existing):
        return _fail(f"{room} already has a computer number {unit} in the database.", "duplicate")
    serial = _clean(data.get("serial"), 120)
    if serial and any(_clean(r.get("SerialNumber"), 120).lower() == serial.lower() for r in existing):
        return _fail(f"Another computer already has serial number {serial}.", "duplicate")

    row = {"Room": room, "UnitNumber": unit, "DateAdded": _today()}
    for key, col in DETAIL_COLUMNS.items():
        value = _clean(data.get(key), 120)
        if value:
            row[col] = value
    try:
        while True:
            try:
                saved = _run("adding a computer", lambda c: c.table(COMPUTERS).insert(row).execute().data or [])
                break
            except DatabaseError as error:
                missing = _missing_column(error, row)
                if not missing:
                    raise
                row.pop(missing)
    except DatabaseError as error:
        return _db_error(error, row.get("Status", ""))

    if not saved:
        saved = _run(
            "reading the new computer",
            lambda c: c.table(COMPUTERS).select("ComputerId").eq("Room", room).eq("UnitNumber", unit).execute().data or [],
        )
    computer_id = tech._parse_int((saved[0] if saved else {}).get("ComputerId"))
    if computer_id is None:
        return _fail("The computer was saved but could not be read back. Refresh the data.")

    problems = []
    try:
        _save_hardware(computer_id, data.get("hardware") or {})
    except DatabaseError as error:
        problems.append(f"hardware not saved ({error})")
    for item in data.get("software") or []:
        result = _insert_software(computer_id, item.get("name"), item.get("version"))
        if not result.get("success"):
            problems.append(result.get("error"))
    add_history(computer_id, data.get("history"), user)

    return {
        "success": True,
        "computer_id": computer_id,
        "message": "Computer added" + (f" ({'; '.join(problems)})" if problems else ""),
    }


def update_computer(user: dict, computer_id, data: dict) -> dict:
    """Edit a computer: Brand / Model / SerialNumber / Status in Computers,
    hardware in ComputerHardware, and the change lines in the history."""
    try:
        current = _get_computer(computer_id)
    except DatabaseError as error:
        return _db_error(error, "")
    if not current:
        return _fail("That computer is no longer in the database. Refresh the data.", "not_found")
    cid = tech._parse_int(current.get("ComputerId"))

    values = {}
    for key, col in DETAIL_COLUMNS.items():
        if key in data and data[key] is not None:
            values[col] = _clean(data[key], 120) or None
    if "Status" in values and not values["Status"]:
        values.pop("Status")  # NOT NULL: keep the current status
    if values.get("SerialNumber"):
        others = tech._select_all(COMPUTERS, "ComputerId,SerialNumber", "ComputerId")
        if any(
            tech._parse_int(r.get("ComputerId")) != cid
            and _clean(r.get("SerialNumber"), 120).lower() == values["SerialNumber"].lower()
            for r in others
        ):
            return _fail(f"Another computer already has serial number {values['SerialNumber']}.", "duplicate")
    try:
        _update_computer_row(cid, values)
        if isinstance(data.get("hardware"), dict):
            _save_hardware(cid, data["hardware"])
    except DatabaseError as error:
        return _db_error(error, values.get("Status", ""))
    add_history(cid, data.get("history"), user)
    return {"success": True, "computer_id": cid}


def log_maintenance(user: dict, computer_id, kind: str, text: str, done_by: str = "") -> dict:
    try:
        current = _get_computer(computer_id)
    except DatabaseError as error:
        return _db_error(error, "")
    if not current:
        return _fail("That computer is no longer in the database. Refresh the data.", "not_found")
    text = _clean(text)
    if len(text) < 5:
        return _fail("Add a bit more detail about what was done.")
    cid = tech._parse_int(current.get("ComputerId"))
    saved = add_history(cid, [{"kind": kind, "text": text}], user, done_by)
    if not saved:
        return _fail(
            "The maintenance history could not be saved to the database "
            f'(is there a "{MAINTENANCE}" table?).'
        )
    try:
        _update_computer_row(cid, {"LastServiced": _today()})
    except DatabaseError:
        pass
    return {"success": True}


# =========================================================
# SOFTWARE
# =========================================================


def _insert_software(computer_id: int, name, version) -> dict:
    name, version = _clean(name, 120), _clean(version, 60)
    if not name:
        return _fail("Enter the program's name.")
    row = {"ComputerId": computer_id, "SoftwareName": name, "Version": version or None, "DateInstalled": _today()}
    try:
        _run("installing software", lambda c: c.table(SOFTWARE).insert(row).execute())
    except DatabaseError as error:
        return _fail(f"{name} could not be saved: {error}")
    return {"success": True}


def _software_rows(computer_id: int) -> list[dict]:
    return _run(
        "reading the computer's software",
        lambda c: c.table(SOFTWARE).select("SoftwareId,SoftwareName,Version").eq("ComputerId", computer_id).execute().data or [],
    )


def install_software(user: dict, computer_id, name, version, history=None) -> dict:
    """Install a program (or update it when the computer already has it)."""
    try:
        current = _get_computer(computer_id)
        if not current:
            return _fail("That computer is no longer in the database. Refresh the data.", "not_found")
        cid = tech._parse_int(current.get("ComputerId"))
        name = _clean(name, 120)
        same = next((r for r in _software_rows(cid) if _clean(r.get("SoftwareName"), 120).lower() == name.lower()), None)
    except DatabaseError as error:
        return _db_error(error, "")
    if same:
        return update_software(user, same.get("SoftwareId"), version, history)
    result = _insert_software(cid, name, version)
    if result.get("success"):
        add_history(cid, history, user)
        _touch(cid)
    return result


def _software(software_id) -> dict | None:
    sid = tech._parse_int(software_id)
    if sid is None:
        return None
    rows = _run(
        "reading software",
        lambda c: c.table(SOFTWARE).select("SoftwareId,ComputerId,SoftwareName,Version").eq("SoftwareId", sid).execute().data or [],
    )
    return rows[0] if rows else None


def update_software(user: dict, software_id, version, history=None) -> dict:
    version = _clean(version, 60)
    if not version:
        return _fail("Enter a new version number.")
    try:
        row = _software(software_id)
        if not row:
            return _fail("That program is no longer installed. Refresh the data.", "not_found")
        _run(
            "updating software",
            lambda c: c.table(SOFTWARE).update({"Version": version, "UpdatedAt": _now()}).eq("SoftwareId", row["SoftwareId"]).execute(),
        )
    except DatabaseError as error:
        return _db_error(error, "")
    cid = tech._parse_int(row.get("ComputerId"))
    add_history(cid, history, user)
    _touch(cid)
    return {"success": True}


def remove_software(user: dict, software_id, history=None) -> dict:
    try:
        row = _software(software_id)
        if not row:
            return _fail("That program is no longer installed. Refresh the data.", "not_found")
        _run(
            "removing software",
            lambda c: c.table(SOFTWARE).delete().eq("SoftwareId", row["SoftwareId"]).execute(),
        )
    except DatabaseError as error:
        return _db_error(error, "")
    cid = tech._parse_int(row.get("ComputerId"))
    add_history(cid, history, user)
    _touch(cid)
    return {"success": True}


def _touch(computer_id: int | None) -> None:
    if computer_id is None:
        return
    try:
        _update_computer_row(computer_id, {})
    except DatabaseError:
        pass


__all__ = [
    "add_history",
    "create_computer",
    "install_software",
    "log_maintenance",
    "remove_software",
    "update_computer",
    "update_software",
]