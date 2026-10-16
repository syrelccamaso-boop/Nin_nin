"""
Centrum Laboratory - Technician business logic.

This service is aligned with the current PostgreSQL/Supabase schema.

Database tables used by this module:

    Users
    Computers
    ComputerHardware
    ComputerSoftware
    Reports
    ReportStatus
    ReportIssues
    MaintenanceHistory
    HardwareReplacements
    SoftwareUpdates

Important:
    The frontend does not need to know the database schema directly.
    This service converts database records into the normalized structure
    expected by the Technician frontend.

Authentication and user/profile operations continue to reuse:

    database.py
    users_repository.py
    auth_service.py
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from . import auth_service
from . import computers_repository as computers
from . import users_repository as users
from .users_repository import DatabaseError, _run

logger = logging.getLogger("centrum.technician")


# =========================================================
# SETTINGS
# =========================================================

TECHNICIAN_ROLE = "Technician"

COMPUTERS_TABLE = "Computers"
COMPUTER_HARDWARE_TABLE = "ComputerHardware"
COMPUTER_SOFTWARE_TABLE = "ComputerSoftware"

REPORTS_TABLE = "Reports"
REPORT_STATUS_TABLE = "ReportStatus"
REPORT_ISSUES_TABLE = "ReportIssues"

USERS_TABLE = "Users"

MAINTENANCE_TABLE = "MaintenanceHistory"
REPLACEMENTS_TABLE = "HardwareReplacements"
SOFTWARE_UPDATES_TABLE = "SoftwareUpdates"


UNIT_STATUSES = (
    "good",
    "issue",
    "replace",
)

ESCALATION_STATUSES = (
    "Pending review",
    "Under inspection",
    "Cleared",
)
# These are the semantic statuses used by the existing technician frontend.
#
# They are NOT columns in Reports.
# Reports.StatusId points to ReportStatus.StatusId.
#
# The actual values are obtained from ReportStatus.CurrentStatus.
REPORT_STATUSES = (
    "progress",
    "resolved",
    "followup",
)

MAX_NOTE_LENGTH = 2000
PAGE_SIZE = 1000

_PHONE_ALLOWED = re.compile(r"^[0-9+()\-\s]+$")


# =========================================================
# ACCESS CHECK
# =========================================================


def is_technician(user: dict | None) -> bool:
    """
    Return True if the authenticated application's role is Technician.
    """
    role = str((user or {}).get("role") or "").strip().lower()
    return role == TECHNICIAN_ROLE.lower()


def current_technician(access_token: str) -> dict:
    """
    Validate the access token and ensure the current user is a technician.

    Returns:
        {
            "success": True,
            "user": {...}
        }

    or:

        {
            "success": False,
            "error": "...",
            "status_code": 401/403
        }
    """

    result = auth_service.user_from_token(access_token)

    if not result.get("success"):
        return {
            **result,
            "status_code": 401,
        }

    if not is_technician(result.get("user")):
        return {
            "success": False,
            "error": "This page is for technicians only.",
            "status_code": 403,
        }

    return result


# =========================================================
# BASIC HELPERS
# =========================================================


def _now() -> str:
    """Return the current UTC timestamp as ISO-8601."""
    return datetime.now(timezone.utc).isoformat()


def _parse_int(value) -> int | None:
    """
    Safely convert a value to a positive integer.
    """
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None

    return number if number > 0 else None


def _person_name(user: dict | None) -> str:
    """
    Convert an application user dictionary to a display name.
    """

    user = user or {}

    name = (f"{user.get('first_name') or ''} " f"{user.get('last_name') or ''}").strip()

    if name:
        return name

    email = str(user.get("email") or "").strip()

    if email:
        return email.split("@")[0]

    return "Technician"


def _safe_string(value) -> str:
    """
    Convert None/non-string values safely to text.
    """
    if value is None:
        return ""

    return str(value).strip()


def _as_issue_list(value) -> list[str]:
    """
    Convert PostgreSQL text[] data into a normal Python list.

    Examples accepted:

        ["Keyboard", "Mouse"]

        "Keyboard"

        None
    """

    if value is None:
        return []

    if isinstance(value, str):
        value = value.strip()

        if not value:
            return []

        return [value]

    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]

    return [str(value).strip()]


def _as_pairs(value) -> list[list[str]]:
    """
    Convert software rows into the format historically expected
    by the technician frontend:

        [
            ["Windows", "11"],
            ["Chrome", "140"]
        ]

    This helper is retained for frontend compatibility.
    """

    if not isinstance(value, list):
        return []

    result: list[list[str]] = []

    for item in value:
        if not isinstance(item, dict):
            continue

        name = (
            item.get("SoftwareName")
            or item.get("software_name")
            or item.get("name")
            or item.get("Name")
            or ""
        )

        version = item.get("Version") or item.get("version") or ""

        installed = item.get("DateInstalled") or item.get("date_installed") or ""

        if name:
            result.append(
                [
                    str(name),
                    str(version),
                    str(installed),
                ]
            )

    return result


def _report_code(report_id) -> str:
    """
    Convert a database ReportId into the existing frontend code.

    Example:

        1 -> CL-0001
        25 -> CL-0025
    """

    number = _parse_int(report_id)

    if number is None:
        return f"CL-{report_id}"

    return f"CL-{number:04d}"


# =========================================================
# DATABASE READ HELPERS
# =========================================================


def _select_all(
    table: str,
    columns: str = "*",
    order: str | None = None,
) -> list[dict]:
    """
    Read all rows from a table in pages.

    Supabase/PostgREST responses can be limited, so this keeps
    requesting pages until the returned batch is smaller than PAGE_SIZE.
    """

    def read(client):
        rows: list[dict] = []
        start = 0

        while True:
            query = client.table(table).select(columns)

            if order:
                query = query.order(order)

            response = query.range(start, start + PAGE_SIZE - 1).execute()

            batch = response.data or []

            rows.extend(batch)

            if len(batch) < PAGE_SIZE:
                return rows

            start += PAGE_SIZE

    return _run(f"reading {table}", read)


# =========================================================
# USERS
# =========================================================


def _load_users() -> dict[int, dict]:
    """
    Load Users and index them by UserId.

    Actual Users schema:

        UserId
        Email
        LastName
        FirstName
        RoleId
        Department
        ContactNumber
        Status
        AuthId
        CreatedAt
        UpdatedAt
    """

    rows = _select_all(
        USERS_TABLE,
        (
            "UserId,"
            "Email,"
            "LastName,"
            "FirstName,"
            "RoleId,"
            "Department,"
            "ContactNumber,"
            "Status,"
            "AuthId,"
            "CreatedAt,"
            "UpdatedAt"
        ),
        "UserId",
    )

    result: dict[int, dict] = {}

    for row in rows:
        user_id = _parse_int(row.get("UserId"))

        if user_id is not None:
            result[user_id] = row

    return result


def _user_display_name(
    user_id,
    users_by_id: dict[int, dict],
) -> str:
    """
    Resolve Users.UserId into a display name.
    """

    number = _parse_int(user_id)

    if number is None:
        return ""

    user = users_by_id.get(number)

    if not user:
        return ""

    first = _safe_string(user.get("FirstName"))
    last = _safe_string(user.get("LastName"))

    name = f"{first} {last}".strip()

    if name:
        return name

    return _safe_string(user.get("Email"))


# =========================================================
# COMPUTERS
# =========================================================


def _load_computers() -> dict[int, dict]:
    """
    Load Computers and index by ComputerId.

    Actual Computers schema:

        ComputerId
        Room
        UnitNumber
        Status
        EscalationStatus
        CreatedAt
        UpdatedAt
    """

    rows = _select_all(
        COMPUTERS_TABLE,
        (
            "ComputerId,"
            "Room,"
            "UnitNumber,"
            "Status,"
            "EscalationStatus,"
            "CreatedAt,"
            "UpdatedAt"
        ),
        "ComputerId",
    )

    result: dict[int, dict] = {}

    for row in rows:
        computer_id = _parse_int(row.get("ComputerId"))

        if computer_id is not None:
            result[computer_id] = row

    return result


def _unit_from_row(
    row: dict,
    hardware_by_computer: dict[int, list[dict]] | None = None,
    software_by_computer: dict[int, list[dict]] | None = None,
) -> dict:
    """
    Convert an actual Computers row into the normalized frontend unit.

    Hardware and software are loaded from their separate tables.
    """

    computer_id = _parse_int(row.get("ComputerId"))

    status = _safe_string(row.get("Status")).lower()

    if status not in UNIT_STATUSES:
        status = "good"

    escalation = _safe_string(row.get("EscalationStatus"))

    if escalation not in ESCALATION_STATUSES:
        escalation = "Pending review"

    hardware_rows = (
        hardware_by_computer.get(computer_id, [])
        if hardware_by_computer and computer_id is not None
        else []
    )

    software_rows = (
        software_by_computer.get(computer_id, [])
        if software_by_computer and computer_id is not None
        else []
    )

    hardware = {}

    if hardware_rows:
        # ComputerHardware has one HardwareId per hardware record.
        # If multiple rows exist, the latest row is preferred.
        hardware_row = hardware_rows[-1]

        hardware = {
            "Processor": _safe_string(hardware_row.get("Processor")),
            "Ram": _safe_string(hardware_row.get("Ram")),
            "Storage": _safe_string(hardware_row.get("Storage")),
            "Peripherals": _safe_string(hardware_row.get("Peripherals")),
            "Graphics": _safe_string(hardware_row.get("Graphics")),
            "Monitor": _safe_string(hardware_row.get("Monitor")),
            "OperatingSystem": _safe_string(hardware_row.get("OperatingSystem")),
        }

    software = _as_pairs(software_rows)

    # The operating system is stored in ComputerHardware.OperatingSystem
    # (the Computers table has no OperatingSystem column).
    operating_system = hardware.get("OperatingSystem", "")

    return {
        "id": computer_id,
        "room": _safe_string(row.get("Room")),
        "number": _parse_int(row.get("UnitNumber")) or 0,
        "status": status,
        "escalation_status": escalation,

        # Operating system accessible directly by the frontend.
        "operating_system": operating_system,

        # Kept for compatibility with the existing frontend.
        "hardware": hardware,
        "software": software,

        # Retained for compatibility with the previous data structure.
        "system": {
            "operating_system": operating_system,
        },

        "lifecycle": {},
        "created_at": row.get("CreatedAt"),
        "updated_at": row.get("UpdatedAt"),
    }



# =========================================================
# COMPUTER HARDWARE
# =========================================================


def _load_hardware() -> dict[int, list[dict]]:
    """
    Load ComputerHardware records grouped by ComputerId.
    """

    rows = _select_all(
        COMPUTER_HARDWARE_TABLE,
        (
            "ComputerId,"
            "Processor,"
            "Ram,"
            "Storage,"
            "Peripherals,"
            "Graphics,"
            "Monitor,"
            "OperatingSystem,"
            "CreatedAt,"
            "HardwareId"
        ),
        "HardwareId",
    )

    result: dict[int, list[dict]] = {}

    for row in rows:
        computer_id = _parse_int(row.get("ComputerId"))

        if computer_id is None:
            continue

        result.setdefault(computer_id, []).append(row)

    return result


# =========================================================
# COMPUTER SOFTWARE
# =========================================================


def _load_software() -> dict[int, list[dict]]:
    """
    Load ComputerSoftware records grouped by ComputerId.
    """

    rows = _select_all(
        COMPUTER_SOFTWARE_TABLE,
        (
            "SoftwareId,"
            "ComputerId,"
            "SoftwareName,"
            "Version,"
            "DateInstalled,"
            "CreatedAt,"
            "UpdatedAt"
        ),
        "SoftwareId",
    )

    result: dict[int, list[dict]] = {}

    for row in rows:
        computer_id = _parse_int(row.get("ComputerId"))

        if computer_id is None:
            continue

        result.setdefault(computer_id, []).append(row)

    return result


# =========================================================
# REPORT STATUS
# =========================================================


def _load_report_statuses() -> dict[int, str]:
    """
    Load ReportStatus.

    Actual schema:

        StatusId
        CurrentStatus
    """

    rows = _select_all(
        REPORT_STATUS_TABLE,
        "StatusId,CurrentStatus",
        "StatusId",
    )

    result: dict[int, str] = {}

    for row in rows:
        status_id = _parse_int(row.get("StatusId"))

        if status_id is None:
            continue

        result[status_id] = _safe_string(row.get("CurrentStatus"))

    return result


def _normalize_report_status(status_name: str) -> str:
    """
    Convert the database's CurrentStatus into the semantic status
    used by the existing technician frontend.

    The database remains the source of truth.

    Recognized examples:

        progress
        in progress
        pending
        open
        reported
            -> progress

        resolved
        closed
        completed
        fixed
            -> resolved

        followup
        follow-up
        for follow-up
            -> followup

    If the database contains an unknown status, progress is used
    as the safe frontend fallback.
    """

    value = _safe_string(status_name).lower()

    normalized = re.sub(r"[_\-]+", " ", value)
    normalized = re.sub(r"\s+", " ", normalized).strip()

    if normalized in {
        "progress",
        "in progress",
        "pending",
        "open",
        "reported",
        "new",
    }:
        return "Under repair"

    if normalized in {
        "resolved",
        "resolve",
        "closed",
        "completed",
        "complete",
        "fixed",
    }:
        return "Fixed"

    if normalized in {
        "followup",
        "follow up",
        "for follow up",
        "for follow-up",
        "follow-up",
    }:
        return "Follow Up"

    return "Under repair"


def _find_status_id(
    requested_status: str,
    status_rows: list[dict],
) -> int | None:
    """
    Find the actual ReportStatus.StatusId corresponding to a frontend
    semantic status.

    We do not assume numeric StatusId values such as 1/2/3.

    Instead, the CurrentStatus value in the database is examined.
    """

    requested = _normalize_report_status(requested_status)

    for row in status_rows:
        current_status = _safe_string(row.get("CurrentStatus"))

        if _normalize_report_status(current_status) == requested:
            status_id = _parse_int(row.get("StatusId"))

            if status_id is not None:
                return status_id

    return None


# =========================================================
# REPORT ISSUES
# =========================================================


def _load_report_issues() -> dict[int, str]:
    """
    Load ReportIssues.

    Actual schema:

        IssueId
        Name
    """

    rows = _select_all(
        REPORT_ISSUES_TABLE,
        "IssueId,Name",
        "IssueId",
    )

    result: dict[int, str] = {}

    for row in rows:
        issue_id = _parse_int(row.get("IssueId"))

        if issue_id is None:
            continue

        result[issue_id] = _safe_string(row.get("Name"))

    return result


# =========================================================
# REPORT NORMALIZATION
# =========================================================


def _report_from_row(
    row: dict,
    computers_by_id: dict[int, dict],
    users_by_id: dict[int, dict],
    status_by_id: dict[int, str],
    issue_by_id: dict[int, str],
) -> dict:
    """
    Convert an actual Reports database row into the structure expected
    by the Technician frontend.
    """

    report_id = _parse_int(row.get("ReportId"))

    computer_id = _parse_int(row.get("ComputerId"))

    reported_by = _parse_int(row.get("ReportedBy"))

    handled_by = _parse_int(row.get("HandledBy"))

    computer = computers_by_id.get(computer_id) if computer_id is not None else None

    # -----------------------------------------------------
    # Computer information
    # -----------------------------------------------------

    room = ""

    unit_number = 0

    if computer:
        room = _safe_string(computer.get("Room"))

        unit_number = _parse_int(computer.get("UnitNumber")) or 0

    # -----------------------------------------------------
    # Reporter
    # -----------------------------------------------------

    reporter_name = _safe_string(row.get("ReporterName"))

    if not reporter_name:
        reporter_name = _user_display_name(
            reported_by,
            users_by_id,
        )

    if not reporter_name:
        reporter_name = "Unknown"

    # -----------------------------------------------------
    # Issues
    # -----------------------------------------------------

    issues = _as_issue_list(row.get("Issues"))

    issue_id = _parse_int(row.get("IssueId"))

    # If IssueId exists and is known, include the actual issue
    # name when it isn't already present in Issues[].
    if issue_id is not None:
        issue_name = issue_by_id.get(issue_id)

        if issue_name and issue_name not in issues:
            issues.insert(0, issue_name)

    if not issues:
        issues = ["General issue"]

    # -----------------------------------------------------
    # Status
    # -----------------------------------------------------

    status_id = _parse_int(row.get("StatusId"))

    database_status = status_by_id.get(status_id, "") if status_id is not None else ""

    frontend_status = _normalize_report_status(database_status)

    # -----------------------------------------------------
    # Technician
    # -----------------------------------------------------

    handled_by_name = _user_display_name(
        handled_by,
        users_by_id,
    )

    return {
        "id": report_id,
        "db_id": report_id,
        "code": _report_code(report_id),
        "computer_id": computer_id,
        "room": room,
        "unit_number": unit_number,
        "reporter": reporter_name,
        "reported_by": reported_by,
        "issues": issues,
        # Existing frontend commonly uses singular "issue".
        "issue": ", ".join(issues),
        "comment": _safe_string(row.get("Comment")),
        # Frontend-facing semantic status.
        "status": frontend_status,
        # Keep database status information available too.
        "status_id": status_id,
        "database_status": database_status,
        "resolution_note": _safe_string(row.get("ResolutionNote")),
        "handled_by": handled_by_name,
        "handled_by_id": handled_by,
        # Existing frontend often displays this as "tech".
        "tech": handled_by_name,
        "created_at": row.get("CreatedAt"),
        "updated_at": row.get("UpdatedAt"),
        "created": row.get("CreatedAt"),
        "updated": row.get("UpdatedAt"),
    }


# =========================================================
# DASHBOARD DATA
# =========================================================


def get_dashboard_data() -> dict:
    """
    Return all data required by the Technician dashboard.

    The database schema is:

        Computers
            |
            +-- ComputerHardware
            |
            +-- ComputerSoftware
            |
            +-- Reports
                    |
                    +-- Users (ReportedBy)
                    +-- Users (HandledBy)
                    +-- ReportStatus
                    +-- ReportIssues
    """

    # -----------------------------------------------------
    # Load computers
    # -----------------------------------------------------

    computers_by_id = _load_computers()

    # -----------------------------------------------------
    # Load hardware/software
    # -----------------------------------------------------

    hardware_by_computer = _load_hardware()
    software_by_computer = _load_software()

    units = [
        _unit_from_row(
            row,
            hardware_by_computer,
            software_by_computer,
        )
        for row in computers_by_id.values()
    ]

    # -----------------------------------------------------
    # Load supporting data
    # -----------------------------------------------------

    users_by_id = _load_users()

    status_rows = _select_all(
        REPORT_STATUS_TABLE,
        "StatusId,CurrentStatus",
        "StatusId",
    )

    status_by_id = {
        _parse_int(row.get("StatusId")): _safe_string(row.get("CurrentStatus"))
        for row in status_rows
        if _parse_int(row.get("StatusId")) is not None
    }

    issue_by_id = _load_report_issues()

    # -----------------------------------------------------
    # Load reports
    # -----------------------------------------------------

    report_rows = _select_all(
        REPORTS_TABLE,
        (
            "ReportId,"
            "ComputerId,"
            "ReportedBy,"
            "ReporterName,"
            "Issues,"
            "Comment,"
            "ResolutionNote,"
            "HandledBy,"
            "CreatedAt,"
            "UpdatedAt,"
            "IssueId,"
            "StatusId"
        ),
        "ReportId",
    )

    reports = [
        _report_from_row(
            row,
            computers_by_id,
            users_by_id,
            status_by_id,
            issue_by_id,
        )
        for row in report_rows
    ]

    # Only return reports connected to an existing computer.
    reports = [
        report for report in reports if report.get("computer_id") in computers_by_id
    ]

    units = [unit for unit in units if unit.get("room") and unit.get("number")]

    return {
        "success": True,
        "units": units,
        "reports": reports,
    }


# =========================================================
# REPORTS
# =========================================================


def update_report_status(
    report_id,
    status: str,
    note: str,
    technician: dict,
) -> dict:
    """
    Update a report's status.

    IMPORTANT:

        Reports.StatusId is a foreign key.

    Therefore this function does NOT write a text value to
    Reports.Status.

    It first resolves the requested frontend status to the actual
    ReportStatus.StatusId.
    """

    number = _parse_int(report_id)

    if number is None:
        return {
            "success": False,
            "error": "Invalid report.",
        }

    requested_status = _safe_string(status).lower()

    if requested_status not in REPORT_STATUSES:
        return {
            "success": False,
            "error": "Invalid report status.",
        }

    note = _safe_string(note)

    if requested_status == "resolved" and not note:
        return {
            "success": False,
            "error": "Add a short solution note first.",
        }

    if requested_status == "followup" and not note:
        return {
            "success": False,
            "error": "Add a short note on what was tried.",
        }

    if len(note) > MAX_NOTE_LENGTH:
        return {
            "success": False,
            "error": (f"The note is too long " f"(max {MAX_NOTE_LENGTH} characters)."),
        }

    technician_id = _parse_int(technician.get("user_id"))

    if technician_id is None:
        return {
            "success": False,
            "error": "Your technician account could not be identified.",
        }

    # -----------------------------------------------------
    # Get actual ReportStatus rows
    # -----------------------------------------------------

    status_rows = _select_all(
        REPORT_STATUS_TABLE,
        "StatusId,CurrentStatus",
        "StatusId",
    )

    status_id = _find_status_id(
        requested_status,
        status_rows,
    )

    if status_id is None:
        return {
            "success": False,
            "error": (
                f"No ReportStatus entry exists for "
                f"'{requested_status}'. "
                "Check the ReportStatus table."
            ),
        }

    # -----------------------------------------------------
    # Update report
    # -----------------------------------------------------

    changes = {
        "StatusId": status_id,
        "ResolutionNote": note,
        "HandledBy": technician_id,
        "UpdatedAt": _now(),
    }

    def update(client):
        response = (
            client.table(REPORTS_TABLE).update(changes).eq("ReportId", number).execute()
        )

        return response.data[0] if response.data else None

    row = _run(
        "updating a report",
        update,
    )

    if not row:
        return {
            "success": False,
            "error": "That report no longer exists.",
        }

    # -----------------------------------------------------
    # Re-read supporting data so the returned report is
    # normalized exactly like get_dashboard_data().
    # -----------------------------------------------------

    computers_by_id = _load_computers()
    users_by_id = _load_users()

    status_by_id = {
        _parse_int(item.get("StatusId")): _safe_string(item.get("CurrentStatus"))
        for item in status_rows
        if _parse_int(item.get("StatusId")) is not None
    }

    issue_by_id = _load_report_issues()

    normalized = _report_from_row(
        row,
        computers_by_id,
        users_by_id,
        status_by_id,
        issue_by_id,
    )

    code = _report_code(number)

    message = {
        "progress": f"{code} moved to under repair",
        "resolved": f"{code} marked as fixed",
        "followup": f"{code} flagged for follow-up",
    }[requested_status]

    return {
        "success": True,
        "message": message,
        "report": normalized,
    }


# =========================================================
# ESCALATION
# =========================================================


def set_escalation_status(
    room: str,
    unit_number,
    status: str,
) -> dict:
    """
    Update Computers.EscalationStatus.

    Valid database values:

        Pending review
        Under inspection
        Cleared
    """

    room = _safe_string(room)

    number = _parse_int(unit_number)

    status = _safe_string(status)

    if not room or number is None:
        return {
            "success": False,
            "error": "Invalid computer.",
        }

    if status not in ESCALATION_STATUSES:
        return {
            "success": False,
            "error": "Invalid escalation status.",
        }

    def update(client):
        response = (
            client.table(COMPUTERS_TABLE)
            .update(
                {
                    "EscalationStatus": status,
                    "UpdatedAt": _now(),
                }
            )
            .eq("Room", room)
            .eq("UnitNumber", number)
            .execute()
        )

        return response.data[0] if response.data else None

    row = _run(
        "updating escalation status",
        update,
    )

    if not row:
        return {
            "success": False,
            "error": (f"{room} unit {number:02d} " "is not in the Computers table."),
        }

    computer_id = _parse_int(row.get("ComputerId"))

    hardware_by_computer = _load_hardware()
    software_by_computer = _load_software()

    return {
        "success": True,
        "message": "Escalation status updated",
        "unit": _unit_from_row(
            row,
            hardware_by_computer,
            software_by_computer,
        ),
    }


# =========================================================
# PROFILE
# =========================================================


def update_contact_number(
    technician: dict,
    contact_number: str,
) -> dict:
    """
    Update Users.ContactNumber through users_repository.
    """

    value = _safe_string(contact_number)

    if not value:
        return {
            "success": False,
            "error": "Enter a value first",
        }

    digits = re.sub(r"\D", "", value)

    if not _PHONE_ALLOWED.fullmatch(value) or not 7 <= len(digits) <= 15:
        return {
            "success": False,
            "error": "Enter a valid contact number.",
        }

    user_id = technician.get("user_id")

    if _parse_int(user_id) is None:
        return {
            "success": False,
            "error": ("Your user profile could not be found."),
        }

    try:
        row = users.update_user(
            user_id,
            {
                "contact_number": value,
            },
        )
    except ValueError as error:
        return {
            "success": False,
            "error": str(error),
        }

    if not row:
        return {
            "success": False,
            "error": ("Your user profile could not be found."),
        }

    return {
        "success": True,
        "message": "Number updated",
        "user": users.to_app_user(row),
    }


# =========================================================
# PASSWORD
# =========================================================


def change_password(
    technician: dict,
    current_password: str,
    new_password: str,
) -> dict:
    """
    Reuse the existing authentication service.
    """

    return auth_service.change_password(
        email=technician.get("email") or "",
        current_password=current_password,
        new_password=new_password,
    )


# =========================================================
# INVENTORY — COMPUTERS (delegating to computers_repository)
# =========================================================


def inventory_list_computers(
    search_term: str | None = None,
    room: str | None = None,
    status: str | None = None,
    escalation_status: str | None = None,
    sort_by: str | None = None,
) -> dict:
    """
    Return the computer inventory for the Technician dashboard.

    If search_term, room, status or escalation_status is given, filtering
    is applied database-side.  sort_by accepts a whitelisted field name
    (prefix with '-' for descending).
    """
    has_filters = any([search_term, room, status, escalation_status])

    try:
        if has_filters:
            rows = computers.search_computers(
                search_term=search_term,
                room=room,
                status=status,
                escalation_status=escalation_status,
                sort_by=sort_by,
            )
        else:
            rows = computers.list_computers(sort_by=sort_by)
    except ValueError as e:
        return {"success": False, "error": str(e)}

    return {"success": True, "computers": rows}


def inventory_get_computer(computer_id) -> dict:
    """Return full details for one computer."""
    cid = _parse_int(computer_id)
    if cid is None:
        return {"success": False, "error": "Invalid computer ID."}

    details = computers.get_computer_details(cid)
    if not details:
        return {"success": False, "error": "Computer not found."}

    return {"success": True, "computer": details}


def inventory_create_computer(
    room: str,
    unit_number,
    status: str = "good",
) -> dict:
    """Create a new Computers row via the repository."""
    try:
        comp = computers.create_computer(room, unit_number, status)
    except ValueError as e:
        return {"success": False, "error": str(e)}

    return {"success": True, "message": "Computer added.", "computer": comp}


def inventory_update_computer(computer_id, changes: dict) -> dict:
    """Update a Computers row (status, room, unit number, escalation)."""
    cid = _parse_int(computer_id)
    if cid is None:
        return {"success": False, "error": "Invalid computer ID."}

    existing = computers.get_computer_by_id(cid)
    if not existing:
        return {"success": False, "error": "Computer not found."}

    try:
        updated = computers.update_computer(cid, changes)
    except ValueError as e:
        return {"success": False, "error": str(e)}

    if not updated:
        return {"success": False, "error": "Computer could not be updated."}

    return {"success": True, "message": "Computer updated.", "computer": updated}


# =========================================================
# INVENTORY — HARDWARE
# =========================================================


def inventory_get_hardware(computer_id) -> dict:
    """Return the hardware record for one computer."""
    cid = _parse_int(computer_id)
    if cid is None:
        return {"success": False, "error": "Invalid computer ID."}

    existing = computers.get_computer_by_id(cid)
    if not existing:
        return {"success": False, "error": "Computer not found."}

    hw = computers.get_hardware(cid)
    return {"success": True, "hardware": hw}


def inventory_upsert_hardware(computer_id, data: dict) -> dict:
    """Create or update the hardware record for one computer."""
    cid = _parse_int(computer_id)
    if cid is None:
        return {"success": False, "error": "Invalid computer ID."}

    existing = computers.get_computer_by_id(cid)
    if not existing:
        return {"success": False, "error": "Computer not found."}

    try:
        hw = computers.upsert_hardware(cid, data)
    except ValueError as e:
        return {"success": False, "error": str(e)}

    return {"success": True, "message": "Hardware saved.", "hardware": hw}


# =========================================================
# INVENTORY — SOFTWARE
# =========================================================


def inventory_list_software(computer_id) -> dict:
    """Return all software for one computer."""
    cid = _parse_int(computer_id)
    if cid is None:
        return {"success": False, "error": "Invalid computer ID."}

    existing = computers.get_computer_by_id(cid)
    if not existing:
        return {"success": False, "error": "Computer not found."}

    rows = computers.list_software(cid)
    return {"success": True, "software": rows}


def inventory_add_software(
    computer_id,
    software_name: str,
    version: str = "",
    date_installed: str | None = None,
) -> dict:
    """Install a software record on a computer."""
    cid = _parse_int(computer_id)
    if cid is None:
        return {"success": False, "error": "Invalid computer ID."}

    existing = computers.get_computer_by_id(cid)
    if not existing:
        return {"success": False, "error": "Computer not found."}

    try:
        sw = computers.add_software(cid, software_name, version, date_installed)
    except ValueError as e:
        return {"success": False, "error": str(e)}

    return {"success": True, "message": "Software installed.", "software": sw}


def inventory_update_software(software_id, version: str) -> dict:
    """Update the version of an installed software record."""
    sid = _parse_int(software_id)
    if sid is None:
        return {"success": False, "error": "Invalid software ID."}

    existing = computers.get_software_by_id(sid)
    if not existing:
        return {"success": False, "error": "Software record not found."}

    updated = computers.update_software(sid, version)
    if not updated:
        return {"success": False, "error": "Software could not be updated."}

    return {"success": True, "message": "Software updated.", "software": updated}


def inventory_delete_software(software_id) -> dict:
    """Remove a software record."""
    sid = _parse_int(software_id)
    if sid is None:
        return {"success": False, "error": "Invalid software ID."}

    existing = computers.get_software_by_id(sid)
    if not existing:
        return {"success": False, "error": "Software record not found."}

    deleted = computers.delete_software(sid)
    if not deleted:
        return {"success": False, "error": "Software could not be removed."}

    return {"success": True, "message": "Software removed."}


# =========================================================
# INVENTORY — MAINTENANCE HISTORY
# =========================================================


def inventory_list_maintenance(computer_id) -> dict:
    """Return maintenance history for one computer."""
    cid = _parse_int(computer_id)
    if cid is None:
        return {"success": False, "error": "Invalid computer ID."}

    existing = computers.get_computer_by_id(cid)
    if not existing:
        return {"success": False, "error": "Computer not found."}

    rows = computers.list_maintenance(cid)
    return {"success": True, "maintenance_history": rows}


def inventory_add_maintenance(
    computer_id,
    description: str,
    technician_id=None,
    date_performed: str | None = None,
) -> dict:
    """Log a maintenance record for a computer."""
    cid = _parse_int(computer_id)
    if cid is None:
        return {"success": False, "error": "Invalid computer ID."}

    existing = computers.get_computer_by_id(cid)
    if not existing:
        return {"success": False, "error": "Computer not found."}

    if not (description or "").strip():
        return {"success": False, "error": "Description is required."}

    record = computers.add_maintenance(cid, description, technician_id, date_performed)
    return {
        "success": True,
        "message": "Maintenance record saved.",
        "maintenance": record,
    }


# =========================================================
# INVENTORY — HARDWARE REPLACEMENTS
# =========================================================


def inventory_list_hw_replacements(computer_id) -> dict:
    """Return hardware replacement records for one computer."""
    cid = _parse_int(computer_id)
    if cid is None:
        return {"success": False, "error": "Invalid computer ID."}

    existing = computers.get_computer_by_id(cid)
    if not existing:
        return {"success": False, "error": "Computer not found."}

    rows = computers.list_hw_replacements(cid)
    return {"success": True, "hardware_replacements": rows}


def inventory_add_hw_replacement(
    computer_id,
    component_replaced: str,
    old_component: str,
    new_component: str,
    date_replaced: str,
    reason: str,
    technician_id,
) -> dict:
    """Record a hardware replacement for a computer."""
    cid = _parse_int(computer_id)
    if cid is None:
        return {"success": False, "error": "Invalid computer ID."}

    existing = computers.get_computer_by_id(cid)
    if not existing:
        return {"success": False, "error": "Computer not found."}

    try:
        record = computers.add_hw_replacement(
            cid,
            component_replaced,
            old_component,
            new_component,
            date_replaced,
            reason,
            technician_id,
        )
    except ValueError as e:
        return {"success": False, "error": str(e)}

    return {
        "success": True,
        "message": "Hardware replacement recorded.",
        "hardware_replacement": record,
    }


# =========================================================
# PUBLIC API
# =========================================================

__all__ = [
    "DatabaseError",
    "change_password",
    "current_technician",
    "get_dashboard_data",
    "inventory_add_hw_replacement",
    "inventory_add_maintenance",
    "inventory_add_software",
    "inventory_create_computer",
    "inventory_delete_software",
    "inventory_get_computer",
    "inventory_get_hardware",
    "inventory_list_computers",
    "inventory_list_hw_replacements",
    "inventory_list_maintenance",
    "inventory_list_software",
    "inventory_update_computer",
    "inventory_update_software",
    "inventory_upsert_hardware",
    "is_technician",
    "set_escalation_status",
    "update_contact_number",
    "update_report_status",
]