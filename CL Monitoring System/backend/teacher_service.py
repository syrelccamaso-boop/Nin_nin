# backend/teacher_service.py

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from backend.database import get_client
from . import auth_service

# database.py exports get_client; alias it so every call below is unchanged.
get_supabase = get_client

logger = logging.getLogger("centrum.teacher")

TEACHER_ROLE = "Teacher"

# ============================================================
# DATABASE TABLES
# ============================================================

COMPUTERS_TABLE = "Computers"
HARDWARE_TABLE = "ComputerHardware"
SOFTWARE_TABLE = "ComputerSoftware"
REPORTS_TABLE = "Reports"
USERS_TABLE = "Users"
REPORT_STATUS_TABLE = "ReportStatus"
REPORT_ISSUES_TABLE = "ReportIssues"


# ============================================================
# FIXED STATUS VALUES FROM DATABASE
# ============================================================
#
# ReportStatus currently contains:
#
# 1,   Reported
# 2,   under repair
# 3,   fixed
# 4,   Escalated
# 5,   Follow Up
#
# A newly submitted Teacher report starts as "Reported".
#

INITIAL_REPORT_STATUS_ID = 1
INITIAL_REPORT_STATUS_NAME = "Reported"

# =========================================================
# ACCESS CHECK
# =========================================================

TEACHER_ROLE = "Teacher"


def is_teacher(user: dict | None) -> bool:
    """
    Return True if the authenticated application's role is Teacher.
    """
    role = str((user or {}).get("role") or "").strip().lower()
    return role == TEACHER_ROLE.lower()


def current_teacher(access_token: str) -> dict:
    """
    Validate the access token and ensure the current user is a teacher.

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

    if not is_teacher(result.get("user")):
        return {
            "success": False,
            "error": "This page is for teachers only.",
            "status_code": 403,
        }

    return result


# ============================================================
# HELPERS
# ============================================================


def _response_data(response: Any) -> List[Dict[str, Any]]:
    """
    Safely extract Supabase response data.
    """
    if response is None:
        return []

    data = getattr(response, "data", None)

    if data is None:
        return []

    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        return [data]

    return []


def _first(response: Any) -> Optional[Dict[str, Any]]:
    """
    Return the first row from a Supabase response.
    """
    rows = _response_data(response)
    return rows[0] if rows else None


def _clean_text(value: Any) -> str:
    """
    Convert a value to a trimmed string.
    """
    if value is None:
        return ""

    return str(value).strip()


def _normalize_issues(issues: Any) -> List[str]:
    """
    Normalize the Issues ARRAY before inserting into PostgreSQL.
    """

    if issues is None:
        return []

    if isinstance(issues, str):
        issues = [issues]

    if not isinstance(issues, (list, tuple, set)):
        issues = [issues]

    cleaned = []

    for issue in issues:
        issue = _clean_text(issue)

        if issue and issue not in cleaned:
            cleaned.append(issue)

    return cleaned


def _get_user_id(user: Any) -> Optional[int]:
    """
    Get the application Users.UserId.

    IMPORTANT:
    Reports.ReportedBy references Users.UserId,
    NOT auth.users.id.
    """

    if user is None:
        return None

    if isinstance(user, int):
        return user

    if isinstance(user, str):
        try:
            return int(user)
        except ValueError:
            return None

    if isinstance(user, dict):
        possible_keys = (
            "user_id",
            "UserId",
            "userid",
            "id",
        )

        for key in possible_keys:
            value = user.get(key)

            if value is None:
                continue

            try:
                return int(value)
            except (TypeError, ValueError):
                continue

    return None


def _person_name(user: Any) -> str:
    """
    Get the teacher's display name from the Users record/session object.
    """

    if not isinstance(user, dict):
        return ""

    name = _clean_text(user.get("name"))

    if name:
        return name

    first_name = _clean_text(user.get("FirstName") or user.get("first_name"))

    last_name = _clean_text(user.get("LastName") or user.get("last_name"))

    full_name = f"{first_name} {last_name}".strip()

    return full_name


def _status_name(status_id: Any) -> str:
    """
    Get the actual status name from ReportStatus.
    """

    try:
        status_id = int(status_id)
    except (TypeError, ValueError):
        return ""

    client = get_supabase()

    response = (
        client.table(REPORT_STATUS_TABLE)
        .select("StatusId, CurrentStatus")
        .eq("StatusId", status_id)
        .limit(1)
        .execute()
    )

    row = _first(response)

    if not row:
        return ""

    return _clean_text(row.get("CurrentStatus"))


def _get_initial_status() -> Dict[str, Any]:
    """
    Return the actual initial status row.

    The current database contains:
        StatusId = 1
        CurrentStatus = Reported

    This function verifies that the row still exists instead
    of blindly assuming the database is unchanged.
    """

    client = get_supabase()

    response = (
        client.table(REPORT_STATUS_TABLE)
        .select("StatusId, CurrentStatus")
        .eq("StatusId", INITIAL_REPORT_STATUS_ID)
        .limit(1)
        .execute()
    )

    row = _first(response)

    if not row:
        raise ValueError(
            "ReportStatus with StatusId=1 was not found. "
            "The Teacher report requires the 'Under repair' status."
        )

    current_status = _clean_text(row.get("CurrentStatus"))

    if current_status.lower() != INITIAL_REPORT_STATUS_NAME.lower():
        raise ValueError(
            f"ReportStatus ID 1 is '{current_status}', not "
            f"'{INITIAL_REPORT_STATUS_NAME}'."
        )

    return row


def _get_issue(issue_name: str) -> Dict[str, Any]:
    """
    Find an issue from ReportIssues using its exact database name.
    """

    issue_name = _clean_text(issue_name)

    if not issue_name:
        raise ValueError("At least one issue must be selected.")

    client = get_supabase()

    response = (
        client.table(REPORT_ISSUES_TABLE)
        .select("IssueId, Name")
        .eq("Name", issue_name)
        .limit(1)
        .execute()
    )

    row = _first(response)

    if not row:
        raise ValueError(
            f"Report issue '{issue_name}' does not exist " "in the ReportIssues table."
        )

    return row


def _get_computer(computer_id: Any) -> Dict[str, Any]:
    """
    Verify that the selected computer exists.
    """

    try:
        computer_id = int(computer_id)
    except (TypeError, ValueError):
        raise ValueError("Invalid ComputerId.")

    client = get_supabase()

    response = (
        client.table(COMPUTERS_TABLE)
        .select("ComputerId, Room, UnitNumber, Status, EscalationStatus")
        .eq("ComputerId", computer_id)
        .limit(1)
        .execute()
    )

    row = _first(response)

    if not row:
        raise ValueError(f"ComputerId {computer_id} does not exist.")

    return row


def _get_user(user_id: int) -> Dict[str, Any]:
    """
    Verify the application user using Users.UserId.
    """

    client = get_supabase()

    response = (
        client.table(USERS_TABLE)
        .select(
            "UserId, Email, FirstName, LastName, RoleId, "
            "Department, ContactNumber, Status, AuthId"
        )
        .eq("UserId", user_id)
        .limit(1)
        .execute()
    )

    row = _first(response)

    if not row:
        raise ValueError(f"UserId {user_id} does not exist in Users.")

    return row


# ============================================================
# AUTHENTICATION GUARD
# ============================================================


def is_teacher(user: dict | None) -> bool:
    """Return True when the authenticated user's role is Teacher."""
    role = str((user or {}).get("role") or "").strip().lower()
    return role == TEACHER_ROLE.lower()


def current_teacher(access_token: str) -> dict:
    """
    Validate the Supabase access token and verify the user is a Teacher.

    Returns:
        {"success": True, "user": {...}}
    or:
        {"success": False, "error": "...", "status_code": 401/403}

    Mirrors the pattern of technician_service.current_technician().
    """

    # Import here to mirror how technician_service does it (same package).
    from backend import auth_service  # noqa: PLC0415

    result = auth_service.user_from_token(access_token)

    if not result.get("success"):
        return {**result, "status_code": 401}

    if not is_teacher(result.get("user")):
        return {
            "success": False,
            "error": "This page is for teachers only.",
            "status_code": 403,
        }

    return result


# ============================================================
# COMPUTER DATA
# ============================================================


def get_computers() -> List[Dict[str, Any]]:
    """
    Get all computers together with their hardware and software.
    """

    client = get_supabase()

    response = client.table(COMPUTERS_TABLE).select("""
            ComputerId,
            Room,
            UnitNumber,
            Status,
            EscalationStatus,
            CreatedAt,
            UpdatedAt
            """).order("Room").order("UnitNumber").execute()

    computers = _response_data(response)

    if not computers:
        return []

    computer_ids = [
        row.get("ComputerId") for row in computers if row.get("ComputerId") is not None
    ]

    hardware_map: Dict[int, Dict[str, Any]] = {}
    software_map: Dict[int, List[Dict[str, Any]]] = {}

    if computer_ids:

        hardware_response = client.table(HARDWARE_TABLE).select("""
                HardwareId,
                ComputerId,
                Processor,
                Ram,
                Storage,
                Peripherals,
                Graphics,
                Monitor,
                OperatingSystem,
                CreatedAt
                """).in_("ComputerId", computer_ids).order("HardwareId").execute()

        for hardware in _response_data(hardware_response):
            cid = hardware.get("ComputerId")

            if cid is not None:
                # Ordered by HardwareId, so the newest record wins (same rule
                # as technician_service).
                hardware_map[int(cid)] = hardware

        software_response = client.table(SOFTWARE_TABLE).select("""
                SoftwareId,
                ComputerId,
                SoftwareName,
                Version,
                DateInstalled,
                CreatedAt,
                UpdatedAt
                """).in_("ComputerId", computer_ids).order("SoftwareName").execute()

        for software in _response_data(software_response):
            cid = software.get("ComputerId")

            if cid is None:
                continue

            cid = int(cid)

            software_map.setdefault(cid, []).append(software)

    result = []

    for computer in computers:

        cid = computer.get("ComputerId")

        if cid is None:
            continue

        cid = int(cid)

        result.append(
            {
                "computer_id": cid,
                "ComputerId": cid,
                "room": computer.get("Room"),
                "Room": computer.get("Room"),
                "unit_number": computer.get("UnitNumber"),
                "UnitNumber": computer.get("UnitNumber"),
                "status": computer.get("Status"),
                "Status": computer.get("Status"),
                "escalation_status": computer.get("EscalationStatus"),
                "EscalationStatus": computer.get("EscalationStatus"),
                "created_at": computer.get("CreatedAt"),
                "CreatedAt": computer.get("CreatedAt"),
                "updated_at": computer.get("UpdatedAt"),
                "UpdatedAt": computer.get("UpdatedAt"),
                "hardware": hardware_map.get(cid),
                "software": software_map.get(cid, []),
            }
        )

    return result


# ============================================================
# REPORT DATA
# ============================================================


def get_reports(user: Any = None) -> List[Dict[str, Any]]:
    """
    Get reports.

    If a teacher user is supplied, only reports created by that
    teacher are returned.
    """

    client = get_supabase()

    query = client.table(REPORTS_TABLE).select("""
            ReportId,
            ComputerId,
            ReportedBy,
            ReporterName,
            Issues,
            Comment,
            ResolutionNote,
            HandledBy,
            CreatedAt,
            UpdatedAt,
            IssueId,
            StatusId
            """)

    if user is not None:

        user_id = _get_user_id(user)

        if user_id is None:
            raise ValueError("Unable to determine the application UserId.")

        query = query.eq("ReportedBy", user_id)

    response = query.order("CreatedAt", desc=True).execute()

    reports = _response_data(response)

    if not reports:
        return []

    computer_ids = list(
        {int(row["ComputerId"]) for row in reports if row.get("ComputerId") is not None}
    )

    user_ids = list(
        {int(row["HandledBy"]) for row in reports if row.get("HandledBy") is not None}
    )

    computers_map: Dict[int, Dict[str, Any]] = {}
    users_map: Dict[int, Dict[str, Any]] = {}
    statuses_map: Dict[int, str] = {}
    issues_map: Dict[int, str] = {}

    # --------------------------------------------------------
    # Computers
    # --------------------------------------------------------

    if computer_ids:

        computer_response = (
            client.table(COMPUTERS_TABLE)
            .select("ComputerId, Room, UnitNumber, Status")
            .in_("ComputerId", computer_ids)
            .execute()
        )

        for computer in _response_data(computer_response):

            cid = computer.get("ComputerId")

            if cid is not None:
                computers_map[int(cid)] = computer

    # --------------------------------------------------------
    # Handlers
    # --------------------------------------------------------

    if user_ids:

        users_response = (
            client.table(USERS_TABLE)
            .select("UserId, FirstName, LastName, Email")
            .in_("UserId", user_ids)
            .execute()
        )

        for person in _response_data(users_response):

            uid = person.get("UserId")

            if uid is not None:
                users_map[int(uid)] = person

    # --------------------------------------------------------
    # Statuses
    # --------------------------------------------------------

    status_response = (
        client.table(REPORT_STATUS_TABLE).select("StatusId, CurrentStatus").execute()
    )

    for status in _response_data(status_response):

        sid = status.get("StatusId")

        if sid is not None:
            statuses_map[int(sid)] = _clean_text(status.get("CurrentStatus"))

    # --------------------------------------------------------
    # Issues
    # --------------------------------------------------------

    issue_response = client.table(REPORT_ISSUES_TABLE).select("IssueId, Name").execute()

    for issue in _response_data(issue_response):

        iid = issue.get("IssueId")

        if iid is not None:
            issues_map[int(iid)] = _clean_text(issue.get("Name"))

    # --------------------------------------------------------
    # Normalize
    # --------------------------------------------------------

    result = []

    for report in reports:

        computer_id = report.get("ComputerId")
        status_id = report.get("StatusId")
        issue_id = report.get("IssueId")
        handled_by = report.get("HandledBy")

        computer = (
            computers_map.get(int(computer_id)) if computer_id is not None else None
        )

        status_name = (
            statuses_map.get(int(status_id), "") if status_id is not None else ""
        )

        issue_name = issues_map.get(int(issue_id), "") if issue_id is not None else ""

        handler = users_map.get(int(handled_by)) if handled_by is not None else None

        handler_name = ""

        if handler:
            handler_name = (
                f"{_clean_text(handler.get('FirstName'))} "
                f"{_clean_text(handler.get('LastName'))}"
            ).strip()

        result.append(
            {
                "id": report.get("ReportId"),
                "db_id": report.get("ReportId"),
                "report_id": report.get("ReportId"),
                "ReportId": report.get("ReportId"),
                "computer_id": computer_id,
                "ComputerId": computer_id,
                "room": (computer.get("Room") if computer else None),
                "Room": (computer.get("Room") if computer else None),
                "unit_number": (computer.get("UnitNumber") if computer else None),
                "UnitNumber": (computer.get("UnitNumber") if computer else None),
                "reported_by": report.get("ReportedBy"),
                "ReportedBy": report.get("ReportedBy"),
                "reporter": report.get("ReporterName"),
                "ReporterName": report.get("ReporterName"),
                "issues": report.get("Issues") or [],
                "Issues": report.get("Issues") or [],
                "issue": issue_name,
                "Issue": issue_name,
                "issue_id": issue_id,
                "IssueId": issue_id,
                "comment": report.get("Comment") or "",
                "Comment": report.get("Comment") or "",
                "resolution_note": (report.get("ResolutionNote") or ""),
                "ResolutionNote": (report.get("ResolutionNote") or ""),
                "handled_by": handled_by,
                "HandledBy": handled_by,
                "handled_by_name": handler_name,
                "HandledByName": handler_name,
                "status_id": status_id,
                "StatusId": status_id,
                "status_name": status_name,
                "CurrentStatus": status_name,
                "created_at": report.get("CreatedAt"),
                "CreatedAt": report.get("CreatedAt"),
                "updated_at": report.get("UpdatedAt"),
                "UpdatedAt": report.get("UpdatedAt"),
            }
        )

    return result


# ============================================================
# TEACHER DASHBOARD
# ============================================================


def get_dashboard_data(user: Any) -> Dict[str, Any]:
    """
    Get all database-backed information required by Teacher.py.
    """

    return {
        "computers": get_computers(),
        "reports": get_reports(user),
    }


# ============================================================
# SUBMIT TEACHER REPORT
# ============================================================


def submit_report(
    teacher: Any,
    computer_id: Any,
    issues: Any,
    comment: str = "",
) -> Dict[str, Any]:
    """
    Create a new Teacher report.

    Database mapping:

        Reports.ComputerId
        Reports.ReportedBy
        Reports.ReporterName
        Reports.Issues
        Reports.Comment
        Reports.ResolutionNote
        Reports.HandledBy
        Reports.IssueId
        Reports.StatusId

    New reports use:
        StatusId = 1
        CurrentStatus = Reported
    """

    # --------------------------------------------------------
    # Validate UserId
    # --------------------------------------------------------

    user_id = _get_user_id(teacher)

    if user_id is None:
        raise ValueError("Unable to determine the teacher's Users.UserId.")

    # --------------------------------------------------------
    # Verify user exists
    # --------------------------------------------------------

    db_user = _get_user(user_id)

    # --------------------------------------------------------
    # Verify teacher name
    # --------------------------------------------------------

    teacher_name = _person_name(teacher)

    if not teacher_name:

        teacher_name = (
            f"{_clean_text(db_user.get('FirstName'))} "
            f"{_clean_text(db_user.get('LastName'))}"
        ).strip()

    if not teacher_name:
        teacher_name = _clean_text(db_user.get("Email"))

    # --------------------------------------------------------
    # Validate Computer
    # --------------------------------------------------------

    computer = _get_computer(computer_id)

    computer_id = int(computer["ComputerId"])

    # --------------------------------------------------------
    # Validate Issues
    # --------------------------------------------------------

    cleaned_issues = _normalize_issues(issues)

    if not cleaned_issues:
        raise ValueError("Please select at least one issue.")

    # --------------------------------------------------------
    # Resolve IssueId
    # --------------------------------------------------------
    #
    # Reports has one IssueId, while Issues is an ARRAY.
    #
    # We use the first selected issue as IssueId while preserving
    # all selected issues in the Issues array.
    #

    first_issue = _get_issue(cleaned_issues[0])

    issue_id = int(first_issue["IssueId"])

    # --------------------------------------------------------
    # Get actual initial status
    # --------------------------------------------------------

    initial_status = _get_initial_status()

    status_id = int(initial_status["StatusId"])

    # --------------------------------------------------------
    # Prevent duplicate active report
    # --------------------------------------------------------
    #
    # Only prevent duplicates for the same teacher + computer
    # when the existing report is not already fixed.
    #

    client = get_supabase()

    existing_response = (
        client.table(REPORTS_TABLE)
        .select("""
            ReportId,
            StatusId
            """)
        .eq("ComputerId", computer_id)
        .eq("ReportedBy", user_id)
        .order("CreatedAt", desc=True)
        .limit(20)
        .execute()
    )

    existing_reports = _response_data(existing_response)

    active_statuses = {
        1,  # Reported
        2,  # under repair
        3,  # fixed
        4,  # Escalated
        5,  # Follow Up
    }

    for existing in existing_reports:

        existing_status = existing.get("StatusId")

        try:
            existing_status = int(existing_status)
        except (TypeError, ValueError):
            continue

        if existing_status in active_statuses:

            raise ValueError(
                "You already have an active report for this computer. "
                "Please wait until the existing report is resolved."
            )

    # --------------------------------------------------------
    # Prepare INSERT
    # --------------------------------------------------------

    row = {
        "ComputerId": computer_id,
        "ReportedBy": user_id,
        "ReporterName": teacher_name,
        "Issues": cleaned_issues,
        "Comment": _clean_text(comment),
        "ResolutionNote": "",
        # HandledBy is nullable in the actual database.
        # Technician assignment can happen later.
        "HandledBy": None,
        "IssueId": issue_id,
        "StatusId": status_id,
    }

    # --------------------------------------------------------
    # INSERT
    # --------------------------------------------------------

    try:

        response = client.table(REPORTS_TABLE).insert(row).execute()

    except Exception as exc:

        raise RuntimeError(
            "Failed to insert the Teacher report into the " f"Reports table: {exc}"
        ) from exc

    inserted = _first(response)

    if not inserted:

        raise RuntimeError(
            "The report insert completed but Supabase returned " "no inserted record."
        )

    # --------------------------------------------------------
    # Return normalized result
    # --------------------------------------------------------

    return inserted


# ============================================================
# PROFILE
# ============================================================


def get_profile(user: Any) -> Optional[Dict[str, Any]]:
    """
    Get the current Teacher profile.
    """

    user_id = _get_user_id(user)

    if user_id is None:
        return None

    try:
        return _get_user(user_id)
    except Exception:
        return None


def update_contact_number(
    user: Any,
    contact_number: str,
) -> Dict[str, Any]:
    """
    Update Users.ContactNumber.
    """

    user_id = _get_user_id(user)

    if user_id is None:
        raise ValueError("Unable to determine Users.UserId.")

    contact_number = _clean_text(contact_number)

    client = get_supabase()

    response = (
        client.table(USERS_TABLE)
        .update({"ContactNumber": contact_number})
        .eq("UserId", user_id)
        .execute()
    )

    updated = _first(response)

    if not updated:
        raise RuntimeError("The contact number was not updated.")

    return updated


# ============================================================
# REPORT ISSUE OPTIONS
# ============================================================


def get_report_issues() -> List[Dict[str, Any]]:
    """
    Get available report issues directly from ReportIssues.
    """

    client = get_supabase()

    response = (
        client.table(REPORT_ISSUES_TABLE)
        .select("IssueId, Name")
        .order("IssueId")
        .execute()
    )

    return _response_data(response)


# ============================================================
# REPORT STATUS OPTIONS
# ============================================================


def get_report_statuses() -> List[Dict[str, Any]]:
    """
    Get report statuses directly from ReportStatus.
    """

    client = get_supabase()

    response = (
        client.table(REPORT_STATUS_TABLE)
        .select("StatusId, CurrentStatus")
        .order("StatusId")
        .execute()
    )

    return _response_data(response)