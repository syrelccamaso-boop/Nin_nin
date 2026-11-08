from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from . import auth_service
from . import computers_repository as computers
from . import notification_service as notify
from . import perf
from . import users_repository as users
from .users_repository import DatabaseError, _run

# Speed: how long the full dashboard data (shared by every technician and
# admin) is reused. Any change clears it at once (main.py), so this only
# saves reloading the same tables on repeated reads.
DASHBOARD_CACHE_SECONDS = 60

# ReportStatus / ReportIssues almost never change.
LOOKUP_CACHE_SECONDS = 300

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


# Optional Computers columns used by the inventory.
COMPUTER_DETAIL_COLUMNS = ("Brand", "Model", "SerialNumber", "DateAdded", "LastServiced")

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

# When each step of a report happened (optional Reports columns, timestamptz).
# The report's own CreatedAt is when it was reported. Until the columns are
# added, everything still works; the history just can't show those times.
REPORT_DATE_COLUMNS = ("UnderRepairDate", "FixedDate", "EscalatedDate", "FollowUpDate")

# The Admin's decisions on escalations: one row per decision in the
# ReportDecisions table (ReportId, Decision approve|resolve|send_back, Note,
# DecidedBy, DecidedAt). Optional: without the table there is no history of
# decisions.
REPORT_DECISIONS_TABLE = "ReportDecisions"


def load_report_decisions() -> dict[int, list[dict]]:
    """{ReportId: [{decision, note, decided_at}, ...] oldest first}; {} when
    the ReportDecisions table doesn't exist."""
    try:
        rows = _select_all(
            REPORT_DECISIONS_TABLE,
            "DecisionId,ReportId,Decision,Note,DecidedAt",
            "DecisionId",
        )
    except DatabaseError as error:
        if error.code == "missing_table":
            return {}
        raise
    out: dict[int, list[dict]] = {}
    for row in rows:
        rid = _parse_int(row.get("ReportId"))
        if rid is None:
            continue
        out.setdefault(rid, []).append(
            {
                "decision": _safe_string(row.get("Decision")).lower(),
                "note": _safe_string(row.get("Note")),
                "decided_at": row.get("DecidedAt"),
            }
        )
    return out


def _without_missing_dates(action: str, changes: dict, run):
    """Run an update with the step date; if the date column doesn't exist
    yet, run it again without it."""
    try:
        return run(changes)
    except DatabaseError as error:
        if error.code != "missing_column" or not any(c in changes for c in REPORT_DATE_COLUMNS):
            raise
        logger.warning(
            "Reports has no step-date columns yet (%s) - saved %s without the date.",
            ", ".join(REPORT_DATE_COLUMNS),
            action,
        )
        return run({k: v for k, v in changes.items() if k not in REPORT_DATE_COLUMNS})
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

    base = (
        "ComputerId,"
        "Room,"
        "UnitNumber,"
        "Status,"
        "EscalationStatus,"
        "CreatedAt,"
        "UpdatedAt"
    )
    # Inventory columns (Brand, Model, SerialNumber, DateAdded, LastServiced):
    # read when they exist.
    try:
        rows = _select_all(
            COMPUTERS_TABLE,
            base + "," + ",".join(COMPUTER_DETAIL_COLUMNS),
            "ComputerId",
        )
    except DatabaseError as error:
        if error.code != "missing_column":
            raise
        rows = _select_all(COMPUTERS_TABLE, base, "ComputerId")

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

    # Computers.Status as stored (computer_status enum, e.g. 'Working').
    record_status = _safe_string(row.get("Status"))

    status = record_status.lower()

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

        # Inventory details (Computers columns, as stored).
        "record_status": record_status,
        "brand": _safe_string(row.get("Brand")),
        "model": _safe_string(row.get("Model")),
        "serial": _safe_string(row.get("SerialNumber")),
        "date_added": row.get("DateAdded"),
        "last_serviced": row.get("LastServiced"),

        # Each ComputerSoftware row with its SoftwareId (to update / remove it).
        "software_rows": [
            {
                "id": _parse_int(item.get("SoftwareId")),
                "name": _safe_string(item.get("SoftwareName")),
                "version": _safe_string(item.get("Version")),
                "installed": _safe_string(item.get("DateInstalled")),
            }
            for item in software_rows
            if isinstance(item, dict) and _safe_string(item.get("SoftwareName"))
        ],
    }


# =========================================================
# MAINTENANCE HISTORY
# =========================================================


def load_maintenance(users_by_id: dict | None = None) -> dict[int, list[dict]]:
    """
    MaintenanceHistory rows grouped by ComputerId:

        {ComputerId: [{"t", "kind", "text", "by"}, ...]}

    Description is saved as "<kind> — <text>" by the inventory. {} when the
    table doesn't exist.
    """

    return _group_maintenance(_load_maintenance_rows(), users_by_id)


def _load_maintenance_rows() -> list[dict]:
    """The raw MaintenanceHistory rows ([] when the table doesn't exist)."""

    try:
        return _select_all(
            MAINTENANCE_TABLE,
            "Id,ComputerId,TechnicianId,Description,DatePerformed,CreatedAt",
            "Id",
        )
    except DatabaseError as error:
        if error.code not in ("missing_table", "missing_column"):
            logger.warning("Maintenance history unavailable: %s", error)
        return []


def _group_maintenance(rows: list[dict], users_by_id: dict | None = None) -> dict[int, list[dict]]:
    """MaintenanceHistory rows grouped by ComputerId, with the staff names."""

    users_by_id = users_by_id or {}
    result: dict[int, list[dict]] = {}

    for row in rows:
        computer_id = _parse_int(row.get("ComputerId"))
        if computer_id is None:
            continue
        text = _safe_string(row.get("Description"))
        kind, sep, rest = text.partition(" — ")
        if not sep or len(kind) > 60:
            kind, rest = "Maintenance", text
        user = users_by_id.get(_parse_int(row.get("TechnicianId"))) or {}
        by = " ".join(
            x for x in (_safe_string(user.get("FirstName")), _safe_string(user.get("LastName"))) if x
        )
        result.setdefault(computer_id, []).append(
            {
                "t": row.get("DatePerformed") or row.get("CreatedAt"),
                "kind": kind.strip(),
                "text": rest.strip(),
                "by": by or "Staff",
            }
        )

    return result


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


def _status_rows() -> list[dict]:
    """
    ReportStatus rows (StatusId, CurrentStatus), kept for a few minutes.

    They were read again on every dashboard load and every status change.
    """

    return perf.lookup(
        "report_status_rows",
        LOOKUP_CACHE_SECONDS,
        lambda: _select_all(REPORT_STATUS_TABLE, "StatusId,CurrentStatus", "StatusId"),
    )


def _load_report_statuses() -> dict[int, str]:
    """
    Load ReportStatus.

    Actual schema:

        StatusId
        CurrentStatus
    """

    rows = _status_rows()

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
        "cancelled",
        "canceled",
        "cancel",
    }:
        return "Cancelled"
    if normalized in {
        "cancelled",
        "canceled",
        "cancel",
    }:
        return "Cancelled"

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

    # Exact names first: "Reported" also normalises to "Under repair", so
    # without this "progress" picked the "Reported" row (StatusId 1) instead
    # of "under repair".
    exact = {
        "progress": ("under repair", "in progress", "progress", "repair"),
        "resolved": ("fixed", "resolved", "closed", "completed", "complete"),
    }.get(_safe_string(requested_status).lower(), ())

    for name in exact:
        for row in status_rows:
            if _safe_string(row.get("CurrentStatus")).lower() == name:
                status_id = _parse_int(row.get("StatusId"))
                if status_id is not None:
                    return status_id

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
    Load ReportIssues (kept for a few minutes - it rarely changes).

    Actual schema:

        IssueId
        Name
    """

    return perf.lookup("report_issues", LOOKUP_CACHE_SECONDS, _read_report_issues)


def _read_report_issues() -> dict[int, str]:
    try:
        rows = _select_all(
            REPORT_ISSUES_TABLE,
            "IssueId,Name",
            "IssueId",
        )
    except DatabaseError as error:
        # The ReportIssues table is optional (Reports.Issues holds the problem
        # names); without it the dashboards must still load.
        if error.code == "missing_table":
            return {}
        raise

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
        # When each step happened (None until the columns exist / the step happens).
        "under_repair_date": row.get("UnderRepairDate"),
        "fixed_date": row.get("FixedDate"),
        "escalated_date": row.get("EscalatedDate"),
        "follow_up_date": row.get("FollowUpDate"),
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

    # Speed: the same data is shared by every technician and admin, so it is
    # kept for DASHBOARD_CACHE_SECONDS. Any change clears it (main.py).
    return perf.cached("technician_dashboard", DASHBOARD_CACHE_SECONDS, _load_dashboard_data)


REPORT_COLUMNS = (
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
    "StatusId"
    # Reports has no IssueId column (problems are in Issues).
)


def _load_report_rows() -> list[dict]:
    """Every Reports row, with the optional step-date columns when they exist."""

    for extra in (
        REPORT_DATE_COLUMNS,
        (),
    ):
        try:
            return _select_all(
                REPORTS_TABLE,
                REPORT_COLUMNS + "".join("," + c for c in extra),
                "ReportId",
            )
        except DatabaseError as error:
            if error.code != "missing_column" or not extra:
                raise

    return []


def _load_dashboard_data() -> dict:
    # -----------------------------------------------------
    # Speed: every table is read AT THE SAME TIME (they don't depend on each
    # other). Before, the 9 reads ran one after another, so the dashboard
    # took 9 network round trips to Supabase.
    # -----------------------------------------------------

    data = perf.parallel(
        computers=_load_computers,
        hardware=_load_hardware,
        software=_load_software,
        users=_load_users,
        maintenance_rows=_load_maintenance_rows,
        statuses=_status_rows,
        issues=_load_report_issues,
        reports=_load_report_rows,
        decisions=load_report_decisions,
    )

    computers_by_id = data["computers"]
    users_by_id = data["users"]

    units = [
        _unit_from_row(
            row,
            data["hardware"],
            data["software"],
        )
        for row in computers_by_id.values()
    ]

    # Maintenance history of each computer (MaintenanceHistory, if it exists).
    maintenance = _group_maintenance(data["maintenance_rows"], users_by_id)
    for unit in units:
        unit["maintenance"] = maintenance.get(unit.get("id"), [])

    status_by_id = {
        _parse_int(row.get("StatusId")): _safe_string(row.get("CurrentStatus"))
        for row in data["statuses"]
        if _parse_int(row.get("StatusId")) is not None
    }

    reports = [
        _report_from_row(
            row,
            computers_by_id,
            users_by_id,
            status_by_id,
            data["issues"],
        )
        for row in data["reports"]
    ]

    # The Admin's decisions (ReportDecisions table, if it exists).
    decisions = data["decisions"]
    for report in reports:
        report["admin_decisions"] = decisions.get(report.get("id"), [])

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
# ONE REPORT (targeted reads)
# =========================================================
#
# Speed: changing one report used to re-read the WHOLE Computers and Users
# tables (and the admin's escalation decision re-read every table through
# get_dashboard_data) just to describe that one report. These read only the
# rows that report needs.


def _lookup_maps(rows: list[dict]) -> tuple[dict[int, dict], dict[int, dict]]:
    """Computers and Users rows needed to describe `rows`, by id."""

    computer_ids = sorted(
        {cid for cid in (_parse_int(r.get("ComputerId")) for r in rows) if cid is not None}
    )
    user_ids = sorted(
        {
            uid
            for r in rows
            for uid in (_parse_int(r.get("ReportedBy")), _parse_int(r.get("HandledBy")))
            if uid is not None
        }
    )

    def read_computers():
        if not computer_ids:
            return []
        return _run(
            "reading computers",
            lambda client: client.table(COMPUTERS_TABLE)
            .select("ComputerId,Room,UnitNumber,Status,EscalationStatus")
            .in_("ComputerId", computer_ids)
            .execute()
            .data
            or [],
        )

    def read_users():
        if not user_ids:
            return []
        return _run(
            "reading users",
            lambda client: client.table(USERS_TABLE)
            .select("UserId,FirstName,LastName,Email")
            .in_("UserId", user_ids)
            .execute()
            .data
            or [],
        )

    found = perf.parallel(computers=read_computers, users=read_users)

    computers_by_id = {
        cid: row
        for row in found["computers"]
        if (cid := _parse_int(row.get("ComputerId"))) is not None
    }
    users_by_id = {
        uid: row for row in found["users"] if (uid := _parse_int(row.get("UserId"))) is not None
    }

    return computers_by_id, users_by_id


def _normalize_one(row: dict) -> dict:
    """One Reports row in the same shape get_dashboard_data() returns."""

    computers_by_id, users_by_id = _lookup_maps([row])

    status_by_id = {
        _parse_int(item.get("StatusId")): _safe_string(item.get("CurrentStatus"))
        for item in _status_rows()
        if _parse_int(item.get("StatusId")) is not None
    }

    return _report_from_row(
        row,
        computers_by_id,
        users_by_id,
        status_by_id,
        _load_report_issues(),
    )


def get_report(report_id) -> dict | None:
    """One report, normalized like get_dashboard_data(); None if it doesn't exist."""

    number = _parse_int(report_id)

    if number is None:
        return None

    rows = _run(
        "reading a report",
        lambda client: client.table(REPORTS_TABLE)
        .select(REPORT_COLUMNS)
        .eq("ReportId", number)
        .limit(1)
        .execute()
        .data
        or [],
    )

    if not rows:
        return None

    return _normalize_one(rows[0])


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

    current = get_report(number)
    if current is None:
        return {"success": False, "error": "That report no longer exists."}
    if current.get("status") == "Cancelled":
        return {"success": False, "error": "This report was cancelled by the teacher."}
    # -----------------------------------------------------
    # Get actual ReportStatus rows (cached - they rarely change)
    # -----------------------------------------------------

    status_rows = _status_rows()

    current = _run(
        "reading a report",
        lambda client: client.table(REPORTS_TABLE)
        .select("StatusId")
        .eq("ReportId", number)
        .limit(1)
        .execute()
        .data
        or [],
    )
    if current:
        name = _load_report_statuses().get(_parse_int(current[0].get("StatusId")), "")
        if _normalize_report_status(name) == "Cancelled":
            return {
                "success": False,
                "error": "This report was cancelled by the teacher.",
            }
            
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
        "HandledBy": technician_id,
        "UpdatedAt": _now(),
    }

    # Reports.ResolutionNote holds the technician's own note (what was done /
    # why it was escalated). Starting a repair sends no note, so it doesn't
    # wipe a note that is already there.
    if note:
        changes["ResolutionNote"] = note

    # When this step happened.
    changes[
        {"progress": "UnderRepairDate", "resolved": "FixedDate", "followup": "EscalatedDate"}[
            requested_status
        ]
    ] = changes["UpdatedAt"]

    def save(values):
        def update(client):
            response = (
                client.table(REPORTS_TABLE).update(values).eq("ReportId", number).execute()
            )

            return response.data[0] if response.data else None

        return _run("updating a report", update)

    row = _without_missing_dates("a status change", changes, save)

    if not row:
        return {
            "success": False,
            "error": "That report no longer exists.",
        }

    # -----------------------------------------------------
    # Normalize the returned report exactly like get_dashboard_data(),
    # reading only the computer and people this report needs (it used to
    # re-read the whole Computers and Users tables).
    # -----------------------------------------------------

    normalized = _normalize_one(row)

    code = _report_code(number)

    message = {
        "progress": f"{code} moved to under repair",
        "resolved": f"{code} marked as fixed",
        "followup": f"{code} flagged for follow-up",
    }[requested_status]

    # ---- notifications (best effort; NotificationPreferences decide) ----
    # The teacher hears about THEIR OWN report only; the admins see what the
    # technician did (an escalation as an escalation).
    label = {"progress": "under repair", "resolved": "fixed", "followup": "escalated"}[
        requested_status
    ]
    where = (
        f"{normalized.get('room') or 'Laboratory'} PC {int(normalized.get('unit_number') or 0):02d}"
    )
    problems = normalized.get("issue") or "Report"
    tech_name = _person_name(technician)
    detail = f"{code} · {problems}" + (f" · {note}" if note else "")
    # Sent after the response (perf.background), so the technician doesn't
    # wait for every notification to be saved.
    perf.background(
        notify.notify_user,
        row.get("ReportedBy"),
        "report_update",
        notify.message(f"Your report is {label} · {where}", f"{detail} · by {tech_name}"),
    )
    if requested_status == "followup":
        perf.background(
            notify.notify_admins,
            "escalation",
            notify.message(f"Escalation · {where}", f"{detail} · by {tech_name}"),
        )
    else:
        perf.background(
            notify.notify_admins,
            "activity",
            notify.message(f"Report {label} · {where}", f"{detail} · by {tech_name}"),
        )

    return {
        "success": True,
        "message": message,
        "report": normalized,
    }


def admin_set_report_status(report_id, status: str, note: str) -> dict:
    """
    An Admin's decision on an escalated report: set Reports.StatusId to
    "under repair" (status="progress") or "fixed" (status="resolved"), with
    the decision as ResolutionNote. HandledBy (the technician) is kept.
    """

    number = _parse_int(report_id)

    if number is None:
        return {"success": False, "error": "Invalid report."}

    status = _safe_string(status).lower()

    if status not in ("progress", "resolved"):
        return {"success": False, "error": "Invalid report status."}

    status_rows = _status_rows()
    status_id = _find_status_id(status, status_rows)

    if status_id is None:
        return {
            "success": False,
            "error": f"No ReportStatus entry exists for '{status}'. Check the ReportStatus table.",
        }

    changes = {
        "StatusId": status_id,
        "ResolutionNote": _safe_string(note)[:MAX_NOTE_LENGTH],
        "UpdatedAt": _now(),
    }

    row = _run(
        "saving the admin decision",
        lambda client: (
            client.table(REPORTS_TABLE).update(changes).eq("ReportId", number).execute().data
            or [None]
        )[0],
    )

    if not row:
        return {"success": False, "error": "That report no longer exists."}

    return {"success": True, "row": row}


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

    # Only this computer's hardware and software (it used to read the whole
    # ComputerHardware and ComputerSoftware tables).
    hardware_by_computer: dict[int, list[dict]] = {}
    software_by_computer: dict[int, list[dict]] = {}

    if computer_id is not None:
        hardware_by_computer[computer_id] = _run(
            "reading the computer's hardware",
            lambda client: client.table(COMPUTER_HARDWARE_TABLE)
            .select(
                "ComputerId,Processor,Ram,Storage,Peripherals,Graphics,"
                "Monitor,OperatingSystem,CreatedAt,HardwareId"
            )
            .eq("ComputerId", computer_id)
            .order("HardwareId")
            .execute()
            .data
            or [],
        )
        software_by_computer[computer_id] = _run(
            "reading the computer's software",
            lambda client: client.table(COMPUTER_SOFTWARE_TABLE)
            .select("SoftwareId,ComputerId,SoftwareName,Version,DateInstalled,CreatedAt,UpdatedAt")
            .eq("ComputerId", computer_id)
            .order("SoftwareId")
            .execute()
            .data
            or [],
        )

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
