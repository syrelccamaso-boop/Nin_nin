"""
Centrum Laboratory - Repository for all computer-related tables.

Covers the following tables (schema is the source of truth; no columns are
invented or renamed):

    Computers
    ---------
    ComputerId      bigint  GENERATED ALWAYS AS IDENTITY  PK
    Room            text    NOT NULL
    UnitNumber      integer NOT NULL  CHECK (UnitNumber > 0)
    Status          text    NOT NULL  DEFAULT 'good'
    EscalationStatus text   NOT NULL  DEFAULT 'Pending review'
                            CHECK IN ('Pending review', 'Under inspection', 'Cleared')
    CreatedAt       timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
    UpdatedAt       timestamptz DEFAULT CURRENT_TIMESTAMP

    ComputerHardware
    ----------------
    HardwareId  bigint  PK   (NOT GENERATED — caller supplies it per existing schema)
    ComputerId  bigint  NOT NULL  FK → Computers.ComputerId
    Processor   varchar (nullable)
    Ram         varchar (nullable)
    Storage     varchar (nullable)
    Peripherals text    (nullable)
    CreatedAt   timestamptz DEFAULT CURRENT_TIMESTAMP

    ComputerSoftware
    ----------------
    SoftwareId    bigint  GENERATED ALWAYS AS IDENTITY  PK
    ComputerId    bigint  NOT NULL  FK → Computers.ComputerId
    SoftwareName  varchar NOT NULL
    Version       varchar (nullable)
    DateInstalled date    (nullable)
    CreatedAt     timestamptz DEFAULT CURRENT_TIMESTAMP
    UpdatedAt     timestamptz DEFAULT CURRENT_TIMESTAMP

    HardwareReplacements
    --------------------
    ReplacementId      bigint  GENERATED ALWAYS AS IDENTITY  PK
    ComputerId         bigint  NOT NULL  FK → Computers.ComputerId
    ComponentReplaced  varchar NOT NULL
    OldComponent       varchar NOT NULL
    NewComponent       varchar NOT NULL
    DateReplaced       date    NOT NULL
    Reason             text    NOT NULL
    ReplacedBy         bigint  NOT NULL  FK → Users.UserId

    SoftwareUpdates
    ---------------
    Id           integer  PK   (NOT GENERATED — caller supplies it)
    ComputerId   bigint   NOT NULL  FK → Computers.ComputerId
    SoftwareName varchar  NOT NULL
    OldVersion   varchar  (nullable)
    NewVersion   varchar  NOT NULL
    UpdatedBy    bigint   NOT NULL  FK → Users.UserId
    UpdateDate   date     NOT NULL
    CreatedAt    timestamptz DEFAULT CURRENT_TIMESTAMP

    MaintenanceHistory
    ------------------
    Id            bigint  GENERATED ALWAYS AS IDENTITY  PK
    ComputerId    bigint  NOT NULL  FK → Computers.ComputerId
    TechnicianId  bigint  (nullable)  FK → Users.UserId
    Description   text    (nullable)
    DatePerformed timestamptz DEFAULT now()
    CreatedAt     timestamptz (nullable)

All searches and filters are applied by PostgreSQL (not in Python).
All writes stamp UpdatedAt where the schema has that column.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from .users_repository import DatabaseError, _escape_like, _run

logger = logging.getLogger("centrum.computers")


# =========================================================
# TABLE NAMES
# =========================================================

COMPUTERS_TABLE = "Computers"
HARDWARE_TABLE = "ComputerHardware"
SOFTWARE_TABLE = "ComputerSoftware"
HW_REPLACEMENTS_TABLE = "HardwareReplacements"
SW_UPDATES_TABLE = "SoftwareUpdates"
MAINTENANCE_TABLE = "MaintenanceHistory"

# =========================================================
# COLUMN LISTS (only columns that actually exist)
# =========================================================

COMPUTER_COLUMNS = (
    "ComputerId",
    "Room",
    "UnitNumber",
    "Status",
    "EscalationStatus",
    "CreatedAt",
    "UpdatedAt",
)

HARDWARE_COLUMNS = (
    "HardwareId",
    "ComputerId",
    "Processor",
    "Ram",
    "Storage",
    "Peripherals",
    "CreatedAt",
)

SOFTWARE_COLUMNS = (
    "SoftwareId",
    "ComputerId",
    "SoftwareName",
    "Version",
    "DateInstalled",
    "CreatedAt",
    "UpdatedAt",
)

HW_REPLACEMENT_COLUMNS = (
    "ReplacementId",
    "ComputerId",
    "ComponentReplaced",
    "OldComponent",
    "NewComponent",
    "DateReplaced",
    "Reason",
    "ReplacedBy",
)

SW_UPDATE_COLUMNS = (
    "Id",
    "ComputerId",
    "SoftwareName",
    "OldVersion",
    "NewVersion",
    "UpdatedBy",
    "UpdateDate",
    "CreatedAt",
)

MAINTENANCE_COLUMNS = (
    "Id",
    "ComputerId",
    "TechnicianId",
    "Description",
    "DatePerformed",
    "CreatedAt",
)

# Allowed values for CHECK constraints — use these constants everywhere.
UNIT_STATUSES = ("good", "issue", "replace")
ESCALATION_STATUSES = ("Pending review", "Under inspection", "Cleared")

PAGE_SIZE = 1000

# =========================================================
# SAFE SORT WHITELIST
# =========================================================

ALLOWED_SORT_FIELDS = {
    "computer_id": "ComputerId",
    "room": "Room",
    "unit_number": "UnitNumber",
    "status": "Status",
    "escalation_status": "EscalationStatus",
    "created_at": "CreatedAt",
    "updated_at": "UpdatedAt",
}


# =========================================================
# HELPERS
# =========================================================


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_iso() -> str:
    return date.today().isoformat()


def _parse_int(value) -> int | None:
    try:
        n = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def _select_all(table: str, columns: tuple | str, order: str) -> list[dict]:
    """Read every row of a table, paging by PAGE_SIZE."""

    cols = ",".join(columns) if isinstance(columns, tuple) else columns

    def read(client):
        rows, start = [], 0
        while True:
            response = (
                client.table(table)
                .select(cols)
                .order(order)
                .range(start, start + PAGE_SIZE - 1)
                .execute()
            )
            batch = response.data or []
            rows.extend(batch)
            if len(batch) < PAGE_SIZE:
                return rows
            start += PAGE_SIZE

    return _run(f"reading {table}", read)


def _resolve_sort(sort_by: str | None) -> tuple[str, bool]:
    """
    Resolve a user-supplied sort key into (db_column, descending).

    Accepts 'field' or '-field' (descending).  Falls back to ComputerId asc
    if the field is not whitelisted.
    """
    if not sort_by:
        return ("ComputerId", False)

    desc = sort_by.startswith("-")
    key = sort_by.lstrip("-").strip().lower()

    db_col = ALLOWED_SORT_FIELDS.get(key)
    if not db_col:
        return ("ComputerId", False)

    return (db_col, desc)


# =========================================================
# ROW → APP DICT CONVERTERS
# =========================================================


def computer_from_row(row: dict) -> dict:
    status = str(row.get("Status") or "").strip().lower()
    escalation = str(row.get("EscalationStatus") or "").strip()

    return {
        "id": row.get("ComputerId"),
        "computer_id": row.get("ComputerId"),
        "room": str(row.get("Room") or "").strip(),
        "unit_number": _parse_int(row.get("UnitNumber")) or 0,
        "status": status if status in UNIT_STATUSES else "good",
        "escalation_status": (
            escalation if escalation in ESCALATION_STATUSES else ESCALATION_STATUSES[0]
        ),
        "created_at": row.get("CreatedAt"),
        "updated_at": row.get("UpdatedAt"),
    }


def hardware_from_row(row: dict) -> dict:
    return {
        "hardware_id": row.get("HardwareId"),
        "computer_id": row.get("ComputerId"),
        "processor": row.get("Processor") or "",
        "ram": row.get("Ram") or "",
        "storage": row.get("Storage") or "",
        "peripherals": row.get("Peripherals") or "",
        "created_at": row.get("CreatedAt"),
    }


def software_from_row(row: dict) -> dict:
    return {
        "software_id": row.get("SoftwareId"),
        "computer_id": row.get("ComputerId"),
        "software_name": row.get("SoftwareName") or "",
        "version": row.get("Version") or "",
        "date_installed": row.get("DateInstalled"),
        "created_at": row.get("CreatedAt"),
        "updated_at": row.get("UpdatedAt"),
    }


def hw_replacement_from_row(row: dict) -> dict:
    return {
        "replacement_id": row.get("ReplacementId"),
        "computer_id": row.get("ComputerId"),
        "component_replaced": row.get("ComponentReplaced") or "",
        "old_component": row.get("OldComponent") or "",
        "new_component": row.get("NewComponent") or "",
        "date_replaced": row.get("DateReplaced"),
        "reason": row.get("Reason") or "",
        "replaced_by": row.get("ReplacedBy"),
    }


def sw_update_from_row(row: dict) -> dict:
    return {
        "id": row.get("Id"),
        "computer_id": row.get("ComputerId"),
        "software_name": row.get("SoftwareName") or "",
        "old_version": row.get("OldVersion") or "",
        "new_version": row.get("NewVersion") or "",
        "updated_by": row.get("UpdatedBy"),
        "update_date": row.get("UpdateDate"),
        "created_at": row.get("CreatedAt"),
    }


def maintenance_from_row(row: dict) -> dict:
    return {
        "id": row.get("Id"),
        "computer_id": row.get("ComputerId"),
        "technician_id": row.get("TechnicianId"),
        "description": row.get("Description") or "",
        "date_performed": row.get("DatePerformed"),
        "created_at": row.get("CreatedAt"),
    }


# =========================================================
# COMPUTERS  —  CREATE
# =========================================================


def create_computer(room: str, unit_number: int, status: str = "good") -> dict:
    """
    Insert a new Computers row.  ComputerId is GENERATED ALWAYS AS IDENTITY.
    """

    room = (room or "").strip()
    number = _parse_int(unit_number)

    if not room:
        raise ValueError("Room is required.")
    if number is None:
        raise ValueError("UnitNumber must be a positive integer.")
    if status not in UNIT_STATUSES:
        raise ValueError(f"Status must be one of {UNIT_STATUSES!r}.")

    now = _now_iso()
    row = {
        "Room": room,
        "UnitNumber": number,
        "Status": status,
        "EscalationStatus": ESCALATION_STATUSES[0],  # "Pending review"
        "CreatedAt": now,
        "UpdatedAt": now,
    }

    def insert(client):
        response = client.table(COMPUTERS_TABLE).insert(row).execute()
        return response.data[0] if response.data else None

    saved = _run("creating a computer", insert)
    if not saved:
        raise DatabaseError("The computer could not be saved.", code="insert_failed")
    return computer_from_row(saved)


# =========================================================
# COMPUTERS  —  READ
# =========================================================


def get_computer_by_id(computer_id) -> dict | None:
    """Return one computer by its primary key, or None."""

    def query(client):
        response = (
            client.table(COMPUTERS_TABLE)
            .select(",".join(COMPUTER_COLUMNS))
            .eq("ComputerId", computer_id)
            .limit(1)
            .execute()
        )
        return response.data[0] if response.data else None

    row = _run("getting a computer by id", query)
    return computer_from_row(row) if row else None


def get_computer_by_room_unit(room: str, unit_number) -> dict | None:
    """Return one computer by its (Room, UnitNumber) natural key, or None."""

    number = _parse_int(unit_number)
    room = (room or "").strip()

    if not room or number is None:
        return None

    def query(client):
        response = (
            client.table(COMPUTERS_TABLE)
            .select(",".join(COMPUTER_COLUMNS))
            .eq("Room", room)
            .eq("UnitNumber", number)
            .limit(1)
            .execute()
        )
        return response.data[0] if response.data else None

    row = _run("getting a computer by room/unit", query)
    return computer_from_row(row) if row else None


def list_computers(
    sort_by: str | None = None,
) -> list[dict]:
    """Return all computers, optionally sorted by an allowed field."""

    db_col, desc = _resolve_sort(sort_by)

    def read(client):
        rows, start = [], 0
        while True:
            response = (
                client.table(COMPUTERS_TABLE)
                .select(",".join(COMPUTER_COLUMNS))
                .order(db_col, desc=desc)
                .range(start, start + PAGE_SIZE - 1)
                .execute()
            )
            batch = response.data or []
            rows.extend(batch)
            if len(batch) < PAGE_SIZE:
                return rows
            start += PAGE_SIZE

    rows = _run("listing computers", read)
    return [computer_from_row(r) for r in rows if r.get("Room") and r.get("UnitNumber")]


def search_computers(
    search_term: str | None = None,
    room: str | None = None,
    status: str | None = None,
    escalation_status: str | None = None,
    sort_by: str | None = None,
    limit: int = 500,
) -> list[dict]:
    """
    Database-side filtering of Computers.

    search_term  – ilike on Room
    room         – exact match on Room
    status       – exact match on Status (must be 'good', 'issue', or 'replace')
    escalation_status – exact match on EscalationStatus
    sort_by      – whitelisted sort field (prefix with '-' for descending)
    """

    db_col, desc = _resolve_sort(sort_by)

    def query(client):
        request = client.table(COMPUTERS_TABLE).select(",".join(COMPUTER_COLUMNS))

        if room:
            request = request.eq("Room", room.strip())
        elif search_term:
            request = request.ilike("Room", f"%{_escape_like(search_term.strip())}%")

        if status:
            if status not in UNIT_STATUSES:
                raise ValueError(f"Invalid status: {status!r}")
            request = request.eq("Status", status)

        if escalation_status:
            if escalation_status not in ESCALATION_STATUSES:
                raise ValueError(f"Invalid escalation status: {escalation_status!r}")
            request = request.eq("EscalationStatus", escalation_status)

        response = (
            request.order(db_col, desc=desc)
            .limit(max(1, min(int(limit), 5000)))
            .execute()
        )
        return response.data or []

    rows = _run("searching computers", query)
    return [computer_from_row(r) for r in rows]


def get_computer_details(computer_id) -> dict | None:
    """
    Return full details for one computer: info + hardware + software +
    maintenance history, in a single logical call.
    """
    comp = get_computer_by_id(computer_id)
    if not comp:
        return None

    comp["hardware"] = get_hardware(computer_id)
    comp["software"] = list_software(computer_id)
    comp["maintenance_history"] = list_maintenance(computer_id)
    comp["hardware_replacements"] = list_hw_replacements(computer_id)
    return comp


# =========================================================
# COMPUTERS  —  UPDATE
# =========================================================


def update_computer(computer_id, changes: dict) -> dict | None:
    """
    Update a Computers row.  Only the fields listed below are writeable.
    Returns the updated computer dict, or None if not found.
    """

    WRITEABLE = {"Room", "UnitNumber", "Status", "EscalationStatus"}

    if not changes:
        return get_computer_by_id(computer_id)

    # Validate values that have CHECK constraints.
    if "Status" in changes and changes["Status"] not in UNIT_STATUSES:
        raise ValueError(
            f"Status must be one of {UNIT_STATUSES!r}, " f"got {changes['Status']!r}."
        )

    if (
        "EscalationStatus" in changes
        and changes["EscalationStatus"] not in ESCALATION_STATUSES
    ):
        raise ValueError(
            f"EscalationStatus must be one of {ESCALATION_STATUSES!r}, "
            f"got {changes['EscalationStatus']!r}."
        )

    unknown = set(changes) - WRITEABLE
    if unknown:
        raise ValueError(f"Unknown Computers fields: {sorted(unknown)}")

    row = dict(changes)
    row["UpdatedAt"] = _now_iso()

    def update(client):
        response = (
            client.table(COMPUTERS_TABLE)
            .update(row)
            .eq("ComputerId", computer_id)
            .execute()
        )
        return response.data[0] if response.data else None

    saved = _run("updating a computer", update)
    return computer_from_row(saved) if saved else None


def set_computer_status(computer_id, status: str) -> dict | None:
    """Convenience: update only Status."""
    return update_computer(computer_id, {"Status": status})


def set_escalation_status_by_id(computer_id, escalation_status: str) -> dict | None:
    """Convenience: update only EscalationStatus (by ComputerId PK)."""
    return update_computer(computer_id, {"EscalationStatus": escalation_status})


def set_escalation_status_by_room(
    room: str, unit_number, escalation_status: str
) -> dict | None:
    """
    Update EscalationStatus using the (Room, UnitNumber) natural key.
    Returns the updated dict, or None if the computer was not found.
    """

    existing = get_computer_by_room_unit(room, unit_number)
    if not existing:
        return None

    return set_escalation_status_by_id(existing["computer_id"], escalation_status)


# =========================================================
# COMPUTERS  —  DELETE
# =========================================================


def delete_computer(computer_id) -> bool:
    """
    Delete a Computers row.  Returns True if deleted.

    IMPORTANT: child rows in ComputerHardware, ComputerSoftware, Reports,
    MaintenanceHistory, HardwareReplacements, and SoftwareUpdates must be
    removed first (or have ON DELETE CASCADE defined in Supabase) to avoid
    FK violations.
    """

    def delete(client):
        response = (
            client.table(COMPUTERS_TABLE)
            .delete()
            .eq("ComputerId", computer_id)
            .execute()
        )
        return bool(response.data)

    return _run("deleting a computer", delete)


# =========================================================
# HARDWARE  —  CRUD
# =========================================================


def get_hardware(computer_id) -> dict | None:
    """Return the ComputerHardware row for a computer, or None."""

    def query(client):
        response = (
            client.table(HARDWARE_TABLE)
            .select(",".join(HARDWARE_COLUMNS))
            .eq("ComputerId", computer_id)
            .limit(1)
            .execute()
        )
        return response.data[0] if response.data else None

    row = _run("getting hardware", query)
    return hardware_from_row(row) if row else None


def upsert_hardware(computer_id, data: dict) -> dict:
    """
    Create or replace the ComputerHardware row for a computer.

    HardwareId is NOT an identity column in the schema, so the caller must
    supply it — or we use ComputerId as a stand-in (there is at most one
    hardware row per computer).
    """

    WRITEABLE = {"Processor", "Ram", "Storage", "Peripherals"}
    unknown = set(data) - WRITEABLE
    if unknown:
        raise ValueError(f"Unknown ComputerHardware fields: {sorted(unknown)}")

    existing = get_hardware(computer_id)

    row = {
        "ComputerId": computer_id,
        "Processor": data.get("Processor") or None,
        "Ram": data.get("Ram") or None,
        "Storage": data.get("Storage") or None,
        "Peripherals": data.get("Peripherals") or None,
    }

    if existing:

        def update(client):
            response = (
                client.table(HARDWARE_TABLE)
                .update(row)
                .eq("HardwareId", existing["hardware_id"])
                .execute()
            )
            return response.data[0] if response.data else None

        saved = _run("updating hardware", update)
    else:
        # HardwareId not GENERATED: use ComputerId as surrogate PK value.
        row["HardwareId"] = computer_id

        def insert(client):
            response = client.table(HARDWARE_TABLE).insert(row).execute()
            return response.data[0] if response.data else None

        saved = _run("inserting hardware", insert)

    return hardware_from_row(saved) if saved else row


def delete_hardware(computer_id) -> bool:
    def delete(client):
        response = (
            client.table(HARDWARE_TABLE)
            .delete()
            .eq("ComputerId", computer_id)
            .execute()
        )
        return bool(response.data)

    return _run("deleting hardware", delete)


# =========================================================
# SOFTWARE  —  CRUD
# =========================================================


def list_software(computer_id) -> list[dict]:
    """All ComputerSoftware rows for one computer."""

    def query(client):
        response = (
            client.table(SOFTWARE_TABLE)
            .select(",".join(SOFTWARE_COLUMNS))
            .eq("ComputerId", computer_id)
            .order("SoftwareName")
            .execute()
        )
        return response.data or []

    rows = _run("listing software", query)
    return [software_from_row(r) for r in rows]


def search_software(
    computer_id=None,
    software_name: str | None = None,
    limit: int = 200,
) -> list[dict]:
    """Filter ComputerSoftware rows by computer and/or name (partial, case-insensitive)."""

    def query(client):
        request = client.table(SOFTWARE_TABLE).select(",".join(SOFTWARE_COLUMNS))
        if computer_id is not None:
            request = request.eq("ComputerId", computer_id)
        if software_name:
            request = request.ilike(
                "SoftwareName", f"%{_escape_like(software_name.strip())}%"
            )
        return (
            request.order("SoftwareName")
            .limit(max(1, min(int(limit), 1000)))
            .execute()
            .data
            or []
        )

    rows = _run("searching software", query)
    return [software_from_row(r) for r in rows]


def get_software_by_id(software_id) -> dict | None:
    """Return a single ComputerSoftware row by its primary key."""

    def query(client):
        response = (
            client.table(SOFTWARE_TABLE)
            .select(",".join(SOFTWARE_COLUMNS))
            .eq("SoftwareId", software_id)
            .limit(1)
            .execute()
        )
        return response.data[0] if response.data else None

    row = _run("getting software by id", query)
    return software_from_row(row) if row else None


def add_software(
    computer_id,
    software_name: str,
    version: str = "",
    date_installed: str | None = None,
) -> dict:
    """Insert one ComputerSoftware row.  SoftwareId is GENERATED ALWAYS."""

    software_name = (software_name or "").strip()
    if not software_name:
        raise ValueError("SoftwareName is required.")

    now = _now_iso()
    row = {
        "ComputerId": computer_id,
        "SoftwareName": software_name,
        "Version": (version or "").strip() or None,
        "DateInstalled": date_installed or _today_iso(),
        "CreatedAt": now,
        "UpdatedAt": now,
    }

    def insert(client):
        response = client.table(SOFTWARE_TABLE).insert(row).execute()
        return response.data[0] if response.data else None

    saved = _run("adding software", insert)
    if not saved:
        raise DatabaseError("Software could not be saved.", code="insert_failed")
    return software_from_row(saved)


def update_software(software_id, version: str) -> dict | None:
    """Update the Version of one ComputerSoftware row."""

    row = {"Version": (version or "").strip() or None, "UpdatedAt": _now_iso()}

    def update(client):
        response = (
            client.table(SOFTWARE_TABLE)
            .update(row)
            .eq("SoftwareId", software_id)
            .execute()
        )
        return response.data[0] if response.data else None

    saved = _run("updating software", update)
    return software_from_row(saved) if saved else None


def delete_software(software_id) -> bool:
    def delete(client):
        response = (
            client.table(SOFTWARE_TABLE)
            .delete()
            .eq("SoftwareId", software_id)
            .execute()
        )
        return bool(response.data)

    return _run("deleting software", delete)


# =========================================================
# HARDWARE REPLACEMENTS  —  CRUD
# =========================================================


def list_hw_replacements(computer_id) -> list[dict]:
    """All HardwareReplacements rows for one computer."""

    def query(client):
        response = (
            client.table(HW_REPLACEMENTS_TABLE)
            .select(",".join(HW_REPLACEMENT_COLUMNS))
            .eq("ComputerId", computer_id)
            .order("DateReplaced", desc=True)
            .execute()
        )
        return response.data or []

    rows = _run("listing hardware replacements", query)
    return [hw_replacement_from_row(r) for r in rows]


def add_hw_replacement(
    computer_id,
    component_replaced: str,
    old_component: str,
    new_component: str,
    date_replaced: str,
    reason: str,
    replaced_by_user_id,
) -> dict:
    """Insert one HardwareReplacements row.  ReplacementId is GENERATED ALWAYS."""

    for label, value in [
        ("ComponentReplaced", component_replaced),
        ("OldComponent", old_component),
        ("NewComponent", new_component),
        ("Reason", reason),
    ]:
        if not (value or "").strip():
            raise ValueError(f"{label} is required.")

    row = {
        "ComputerId": computer_id,
        "ComponentReplaced": component_replaced.strip(),
        "OldComponent": old_component.strip(),
        "NewComponent": new_component.strip(),
        "DateReplaced": date_replaced or _today_iso(),
        "Reason": reason.strip(),
        "ReplacedBy": replaced_by_user_id,
    }

    def insert(client):
        response = client.table(HW_REPLACEMENTS_TABLE).insert(row).execute()
        return response.data[0] if response.data else None

    saved = _run("adding a hardware replacement", insert)
    if not saved:
        raise DatabaseError(
            "Hardware replacement could not be saved.", code="insert_failed"
        )
    return hw_replacement_from_row(saved)


def delete_hw_replacement(replacement_id) -> bool:
    def delete(client):
        response = (
            client.table(HW_REPLACEMENTS_TABLE)
            .delete()
            .eq("ReplacementId", replacement_id)
            .execute()
        )
        return bool(response.data)

    return _run("deleting a hardware replacement", delete)


# =========================================================
# SOFTWARE UPDATES  —  CRUD
# =========================================================


def list_sw_updates(computer_id) -> list[dict]:
    """All SoftwareUpdates rows for one computer."""

    def query(client):
        response = (
            client.table(SW_UPDATES_TABLE)
            .select(",".join(SW_UPDATE_COLUMNS))
            .eq("ComputerId", computer_id)
            .order("UpdateDate", desc=True)
            .execute()
        )
        return response.data or []

    rows = _run("listing software updates", query)
    return [sw_update_from_row(r) for r in rows]


def add_sw_update(
    id_: int,
    computer_id,
    software_name: str,
    new_version: str,
    updated_by_user_id,
    update_date: str | None = None,
    old_version: str = "",
) -> dict:
    """
    Insert one SoftwareUpdates row.
    Id is NOT GENERATED — the caller must supply a unique integer.
    """

    if not (software_name or "").strip():
        raise ValueError("SoftwareName is required.")
    if not (new_version or "").strip():
        raise ValueError("NewVersion is required.")

    row = {
        "Id": id_,
        "ComputerId": computer_id,
        "SoftwareName": software_name.strip(),
        "OldVersion": (old_version or "").strip() or None,
        "NewVersion": new_version.strip(),
        "UpdatedBy": updated_by_user_id,
        "UpdateDate": update_date or _today_iso(),
        "CreatedAt": _now_iso(),
    }

    def insert(client):
        response = client.table(SW_UPDATES_TABLE).insert(row).execute()
        return response.data[0] if response.data else None

    saved = _run("adding a software update record", insert)
    if not saved:
        raise DatabaseError(
            "Software update record could not be saved.", code="insert_failed"
        )
    return sw_update_from_row(saved)


# =========================================================
# MAINTENANCE HISTORY  —  CRUD
# =========================================================


def list_maintenance(computer_id) -> list[dict]:
    """All MaintenanceHistory rows for one computer, newest first."""

    def query(client):
        response = (
            client.table(MAINTENANCE_TABLE)
            .select(",".join(MAINTENANCE_COLUMNS))
            .eq("ComputerId", computer_id)
            .order("DatePerformed", desc=True)
            .execute()
        )
        return response.data or []

    rows = _run("listing maintenance history", query)
    return [maintenance_from_row(r) for r in rows]


def search_maintenance(
    computer_id=None,
    technician_id=None,
    description_term: str | None = None,
    limit: int = 200,
) -> list[dict]:
    """Filter MaintenanceHistory.  All filters optional, applied DB-side."""

    def query(client):
        request = client.table(MAINTENANCE_TABLE).select(",".join(MAINTENANCE_COLUMNS))
        if computer_id is not None:
            request = request.eq("ComputerId", computer_id)
        if technician_id is not None:
            request = request.eq("TechnicianId", technician_id)
        if description_term:
            request = request.ilike(
                "Description",
                f"%{_escape_like(description_term.strip())}%",
            )
        return (
            request.order("DatePerformed", desc=True)
            .limit(max(1, min(int(limit), 1000)))
            .execute()
            .data
            or []
        )

    rows = _run("searching maintenance history", query)
    return [maintenance_from_row(r) for r in rows]


def add_maintenance(
    computer_id,
    description: str,
    technician_id=None,
    date_performed: str | None = None,
) -> dict:
    """Insert one MaintenanceHistory row.  Id is GENERATED ALWAYS."""

    now = _now_iso()
    row = {
        "ComputerId": computer_id,
        "TechnicianId": technician_id or None,
        "Description": (description or "").strip() or None,
        "DatePerformed": date_performed or now,
        "CreatedAt": now,
    }

    def insert(client):
        response = client.table(MAINTENANCE_TABLE).insert(row).execute()
        return response.data[0] if response.data else None

    saved = _run("adding a maintenance record", insert)
    if not saved:
        raise DatabaseError(
            "Maintenance record could not be saved.", code="insert_failed"
        )
    return maintenance_from_row(saved)
