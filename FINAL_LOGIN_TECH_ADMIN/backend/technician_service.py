"""
Centrum Laboratory - Technician business logic.

Everything the Technician dashboard needs from the database lives here:
reading the computers and problem reports, resolving / flagging reports,
escalation status, and the technician's own profile and password.

It reuses the existing services instead of creating new ones:

    database.py          shared Supabase client (through users_repository._run)
    users_repository.py  Users table (contact number updates), DatabaseError
    auth_service.py      who is logged in (user_from_token), password change

No credentials are read here; database.py loads them from the root .env.

Supabase tables used (create them once in Supabase > SQL Editor)
-----------------------------------------------------------------
    create table if not exists "Computers" (
        "ComputerId"       bigint generated always as identity primary key,
        "Room"             text not null,                 -- e.g. 'CL 1'
        "UnitNumber"       integer not null check ("UnitNumber" > 0),
        "Status"           text not null default 'good'
                           check ("Status" in ('good', 'issue', 'replace')),
        "EscalationStatus" text not null default 'Pending review'
                           check ("EscalationStatus" in
                                  ('Pending review', 'Under inspection', 'Cleared')),
        "Hardware"         jsonb not null default '{}'::jsonb,  -- {"Processor": "...", ...}
        "Software"         jsonb not null default '[]'::jsonb,  -- [["Windows 10 Pro", "Licensed"], ...]
        "System"           jsonb not null default '{}'::jsonb,  -- {"Asset tag": "...", ...}
        "Lifecycle"        jsonb not null default '{}'::jsonb,  -- {"Deployed": "...", ...}
        "CreatedAt"        timestamptz not null default now(),
        unique ("Room", "UnitNumber")
    );

    create table if not exists "Reports" (
        "ReportId"       bigint generated always as identity primary key,
        "Room"           text not null,
        "UnitNumber"     integer not null,
        "ReportedBy"     text,                                -- Users.UserId of the teacher
        "ReporterName"   text not null default '',
        "Issues"         text[] not null default '{}',
        "Comment"        text not null default '',
        "Status"         text not null default 'progress'
                         check ("Status" in ('progress', 'resolved', 'followup')),
        "ResolutionNote" text not null default '',
        "HandledBy"      text,                                -- Users.UserId of the technician
        "HandledByName"  text not null default '',
        "CreatedAt"      timestamptz not null default now(),
        "UpdatedAt"      timestamptz
    );

    alter table "Computers" enable row level security;   -- the backend's service
    alter table "Reports"   enable row level security;   -- role key bypasses RLS
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from . import auth_service
from . import users_repository as users
from .users_repository import DatabaseError, _run

logger = logging.getLogger("centrum.technician")


# =========================================================
# SETTINGS
# =========================================================

TECHNICIAN_ROLE = "Technician"

COMPUTERS_TABLE = "Computers"
REPORTS_TABLE = "Reports"

# Same style as users_repository.SELECT_COLUMNS (plain comma-separated names).
COMPUTER_COLUMNS = ",".join(
    (
        "ComputerId",
        "Room",
        "UnitNumber",
        "Status",
        "EscalationStatus",
        "Hardware",
        "Software",
        "System",
        "Lifecycle",
    )
)
REPORT_COLUMNS = ",".join(
    (
        "ReportId",
        "Room",
        "UnitNumber",
        "ReporterName",
        "Issues",
        "Comment",
        "Status",
        "ResolutionNote",
        "HandledByName",
        "CreatedAt",
        "UpdatedAt",
    )
)

UNIT_STATUSES = ("good", "issue", "replace")
REPORT_STATUSES = ("progress", "resolved", "followup")
ESCALATION_STATUSES = ("Pending review", "Under inspection", "Cleared")

MAX_NOTE_LENGTH = 2000
PAGE_SIZE = 1000

_PHONE_ALLOWED = re.compile(r"^[0-9+()\-\s]+$")


# =========================================================
# ACCESS CHECK
# =========================================================


def is_technician(user: dict | None) -> bool:
    """True if the user's role (from auth_service / Users.RoleId) is Technician."""

    role = str((user or {}).get("role") or "").strip().lower()

    return role == TECHNICIAN_ROLE.lower()


def current_technician(access_token: str) -> dict:
    """Who is calling? Uses the existing login (auth_service.user_from_token).

    Returns {"success": True, "user": {...}} or {"success": False, "error": ...,
    "status_code": 401 | 403}.
    """

    result = auth_service.user_from_token(access_token)

    if not result.get("success"):

        return {**result, "status_code": 401}

    if not is_technician(result["user"]):

        return {
            "success": False,
            "error": "This page is for technicians only.",
            "status_code": 403,
        }

    return result


# =========================================================
# HELPERS
# =========================================================


def _now() -> str:

    return datetime.now(timezone.utc).isoformat()


def _as_dict(value) -> dict:

    return {str(k): str(v) for k, v in value.items()} if isinstance(value, dict) else {}


def _as_pairs(value) -> list[list[str]]:
    """Software list as [[name, detail], ...] - accepts a few JSON shapes."""

    if isinstance(value, dict):
        return [[str(k), str(v)] for k, v in value.items()]

    pairs = []

    for item in value if isinstance(value, list) else []:

        if isinstance(item, (list, tuple)) and item:
            pairs.append([str(item[0]), str(item[1]) if len(item) > 1 else ""])

        elif isinstance(item, dict):
            name = item.get("name") or item.get("Name") or ""
            detail = (
                item.get("detail") or item.get("status") or item.get("version") or ""
            )
            if name:
                pairs.append([str(name), str(detail)])

        elif item:
            pairs.append([str(item), ""])

    return pairs


def _parse_int(value) -> int | None:

    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None

    return number if number > 0 else None


def _person_name(user: dict) -> str:

    name = f"{user.get('first_name') or ''} {user.get('last_name') or ''}".strip()

    return name or (user.get("email") or "").split("@")[0] or "Technician"


def _select_all(table: str, columns: str, order: str) -> list[dict]:
    """Read every row of a table, page by page (Supabase caps one response)."""

    def read(client):

        rows, start = [], 0

        while True:

            response = (
                client.table(table)
                .select(columns)
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


def _unit_from_row(row: dict) -> dict:

    status = str(row.get("Status") or "").strip().lower()
    escalation = str(row.get("EscalationStatus") or "").strip()

    return {
        "id": row.get("ComputerId"),
        "room": str(row.get("Room") or "").strip(),
        "number": _parse_int(row.get("UnitNumber")) or 0,
        "status": status if status in UNIT_STATUSES else "good",
        "escalation_status": (
            escalation if escalation in ESCALATION_STATUSES else ESCALATION_STATUSES[0]
        ),
        "hardware": _as_dict(row.get("Hardware")),
        "software": _as_pairs(row.get("Software")),
        "system": _as_dict(row.get("System")),
        "lifecycle": _as_dict(row.get("Lifecycle")),
    }


def _report_code(report_id) -> str:

    number = _parse_int(report_id)

    return f"CL-{number:04d}" if number else f"CL-{report_id}"


def _report_from_row(row: dict) -> dict:

    issues = row.get("Issues") or []

    if isinstance(issues, str):
        issues = [issues]

    status = str(row.get("Status") or "").strip().lower()

    return {
        "id": row.get("ReportId"),
        "code": _report_code(row.get("ReportId")),
        "room": str(row.get("Room") or "").strip(),
        "unit_number": _parse_int(row.get("UnitNumber")) or 0,
        "reporter": (row.get("ReporterName") or "").strip() or "Unknown",
        "issues": [str(i) for i in issues if str(i).strip()] or ["General issue"],
        "comment": row.get("Comment") or "",
        "status": status if status in REPORT_STATUSES else "progress",
        "resolution_note": row.get("ResolutionNote") or "",
        "handled_by": (row.get("HandledByName") or "").strip(),
        "created_at": row.get("CreatedAt"),
        "updated_at": row.get("UpdatedAt"),
    }


# =========================================================
# DASHBOARD DATA
# =========================================================


def get_dashboard_data() -> dict:
    """All computers and reports for the Technician dashboard.

    Raises DatabaseError (handled by main.py) if Supabase can't be read.
    """

    units = [
        _unit_from_row(row)
        for row in _select_all(COMPUTERS_TABLE, COMPUTER_COLUMNS, "ComputerId")
    ]

    reports = [
        _report_from_row(row)
        for row in _select_all(REPORTS_TABLE, REPORT_COLUMNS, "ReportId")
    ]

    return {
        "success": True,
        "units": [unit for unit in units if unit["room"] and unit["number"]],
        "reports": [report for report in reports if report["room"]],
    }


# =========================================================
# REPORTS
# =========================================================


def update_report_status(report_id, status: str, note: str, technician: dict) -> dict:
    """Resolve a report or flag it for follow-up (a note is required)."""

    number = _parse_int(report_id)

    if number is None:

        return {"success": False, "error": "Invalid report."}

    status = (status or "").strip().lower()

    if status not in REPORT_STATUSES:

        return {"success": False, "error": "Invalid report status."}

    note = (note or "").strip()

    if status == "resolved" and not note:

        return {"success": False, "error": "Add a short solution note first."}

    if status == "followup" and not note:

        return {"success": False, "error": "Add a short note on what was tried."}

    if len(note) > MAX_NOTE_LENGTH:

        return {
            "success": False,
            "error": f"The note is too long (max {MAX_NOTE_LENGTH} characters).",
        }

    changes = {
        "Status": status,
        "ResolutionNote": note,
        "HandledBy": str(technician.get("user_id") or ""),
        "HandledByName": _person_name(technician),
        "UpdatedAt": _now(),
    }

    def update(client):
        response = (
            client.table(REPORTS_TABLE).update(changes).eq("ReportId", number).execute()
        )
        return response.data[0] if response.data else None

    row = _run("updating a report", update)

    if not row:

        return {"success": False, "error": "That report no longer exists."}

    code = _report_code(number)

    message = {
        "resolved": f"{code} marked as resolved",
        "followup": f"{code} flagged for follow-up",
        "progress": f"{code} moved back to in progress",
    }[status]

    return {"success": True, "message": message, "report": _report_from_row(row)}


# =========================================================
# ESCALATION
# =========================================================


def set_escalation_status(room: str, unit_number, status: str) -> dict:
    """Pending review / Under inspection / Cleared for one computer."""

    room = (room or "").strip()
    number = _parse_int(unit_number)
    status = (status or "").strip()

    if not room or number is None:

        return {"success": False, "error": "Invalid computer."}

    if status not in ESCALATION_STATUSES:

        return {"success": False, "error": "Invalid escalation status."}

    def update(client):
        response = (
            client.table(COMPUTERS_TABLE)
            .update({"EscalationStatus": status})
            .eq("Room", room)
            .eq("UnitNumber", number)
            .execute()
        )
        return response.data[0] if response.data else None

    row = _run("updating escalation status", update)

    if not row:

        return {
            "success": False,
            "error": f"{room} unit {number:02d} is not in the Computers table.",
        }

    return {
        "success": True,
        "message": "Escalation status updated",
        "unit": _unit_from_row(row),
    }


# =========================================================
# PROFILE / PASSWORD  (reuse users_repository and auth_service)
# =========================================================


def update_contact_number(technician: dict, contact_number: str) -> dict:

    value = (contact_number or "").strip()

    if not value:

        return {"success": False, "error": "Enter a value first"}

    digits = re.sub(r"\D", "", value)

    if not _PHONE_ALLOWED.match(value) or not 7 <= len(digits) <= 15:

        return {"success": False, "error": "Enter a valid contact number."}

    user_id = technician.get("user_id")

    if user_id in (None, ""):

        return {"success": False, "error": "Your user profile could not be found."}

    try:
        row = users.update_user(user_id, {"contact_number": value})

    except ValueError as error:

        return {"success": False, "error": str(error)}

    if not row:

        return {"success": False, "error": "Your user profile could not be found."}

    return {
        "success": True,
        "message": "Number updated",
        "user": users.to_app_user(row),
    }


def change_password(technician: dict, current_password: str, new_password: str) -> dict:

    return auth_service.change_password(
        email=technician.get("email") or "",
        current_password=current_password,
        new_password=new_password,
    )


__all__ = [
    "DatabaseError",
    "change_password",
    "current_technician",
    "get_dashboard_data",
    "is_technician",
    "set_escalation_status",
    "update_contact_number",
    "update_report_status",
]
