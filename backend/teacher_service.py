# backend/teacher_service.py

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from backend.database import get_client
from . import auth_service
from . import notification_service as notify
from . import perf
from . import reports_repository as reports_repo
from . import technician_service
from . import users_repository as users

# Speed: the computers list (with hardware and software) is the same for
# every teacher, so it is shared for this many seconds. Any change clears it
# at once (main.py).
COMPUTERS_CACHE_SECONDS = 10

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
# The TABLE is "ReportCategory" (columns CategoryId, Category); "CategoryId" is
# only its key column.
REPORT_CATEGORY_TABLE = "ReportCategory"

# Reports.CategoryId must be a normal column the app can write. If it is still
# GENERATED ALWAYS AS IDENTITY, PostgreSQL refuses any value we send (error
# 428C9) and would number it 1, 2, 3, ... itself, which has nothing to do with
# the report's category. Run this once in the Supabase SQL editor:
CATEGORY_FIX_SQL = (
    'alter table public."Reports" alter column "CategoryId" drop identity if exists;'
)

# Reports columns that exist in the database (public."Reports"):
#   ReportId, ComputerId, ReportedBy, ReporterName, Issues (text[]), Comment,
#   ResolutionNote, HandledBy, CreatedAt, UpdatedAt, StatusId, CategoryId
# There is NO IssueId column: the selected problems are kept in Issues, and
# CategoryId (NOT NULL, FK -> ReportCategory.CategoryId) must always be sent,
# because its identity default would otherwise point at a category that may
# not exist.
REPORT_BASE_COLUMNS = (
    "ReportId, ComputerId, ReportedBy, ReporterName, Issues, Comment, "
    "ResolutionNote, HandledBy, CreatedAt, UpdatedAt, StatusId, CategoryId"
)


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

# Status ids used by the Teacher features (must match Teacher.py _STATUS_ID_MAP).
STATUS_REPORTED = 1
STATUS_UNDER_REPAIR = 2
STATUS_FIXED = 3
STATUS_ESCALATED = 4
STATUS_FOLLOW_UP = 5
# "Cancelled" is found by NAME in ReportStatus (see _find_cancelled_status_id), so
# it works whatever number the database gives it. teacher_migration.sql adds the row.
STATUS_CANCELLED_NAME = "Cancelled"

# A report still "Reported" for this long can be followed up, once per day.
# (Same numbers as Teacher.py FOLLOW_UP_AFTER_HOURS / FOLLOW_UP_EVERY_HOURS.)
FOLLOW_UP_AFTER_HOURS = 48
FOLLOW_UP_EVERY_HOURS = 24
MIN_REASON = 5

# Statuses that count as "still open" for the duplicate check.
OPEN_STATUS_IDS = {
    STATUS_REPORTED,
    STATUS_UNDER_REPAIR,
    STATUS_ESCALATED,
    STATUS_FOLLOW_UP,
}

# "same day" is judged in the school's time zone.
LOCAL_TZ = "Asia/Manila"

# A deactivated teacher gets Users.Status = "inactive" (users_repository matches the
# casing already used in your table). auth_service blocks login for that status, and
# an admin can switch the account back on with admin_set_status(..., "active").
USER_STATUS_INACTIVE = "inactive"

# New Reports columns (added by teacher_migration.sql).
REPORT_EXTRA_COLUMNS = "CancelReason, EditReason, LastFollowUpAt, FollowUpMessage"

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

    # Cached ReportStatus rows (they rarely change) instead of a query per report.
    row = next(
        (
            r
            for r in _status_rows()
            if str(r.get("StatusId")) == str(INITIAL_REPORT_STATUS_ID)
        ),
        None,
    )

    if not row:
        raise ValueError(
            "ReportStatus with StatusId=1 was not found. "
            "The Teacher report requires the 'Reported' status."
        )

    current_status = _clean_text(row.get("CurrentStatus"))

    if current_status.lower() != INITIAL_REPORT_STATUS_NAME.lower():
        raise ValueError(
            f"ReportStatus ID 1 is '{current_status}', not "
            f"'{INITIAL_REPORT_STATUS_NAME}'."
        )

    return row


def _table_missing(exc: Exception) -> bool:
    """True when Supabase says a table does not exist (PGRST205)."""
    text = str(exc).lower()
    return "pgrst205" in text or "could not find the table" in text


def _get_issue(issue_name: str) -> Dict[str, Any]:
    """
    Find an issue from ReportIssues using its exact database name.

    The ReportIssues table is optional: when it has been removed from the
    database, the problem name is accepted as typed/picked (it is stored in
    Reports.Issues and sorted into Hardware / Software by its name).
    """

    issue_name = _clean_text(issue_name)

    if not issue_name:
        raise ValueError("At least one issue must be selected.")

    client = get_supabase()

    try:
        response = (
            client.table(REPORT_ISSUES_TABLE)
            .select("*")
            .eq("Name", issue_name)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        if _table_missing(exc):
            return {"Name": issue_name}
        raise

    row = _first(response)

    if not row:
        raise ValueError(
            f"Report issue '{issue_name}' does not exist " "in the ReportIssues table."
        )

    return row


def _category_write_error(exc: Exception) -> Optional[RuntimeError]:
    """A clear error when the database refuses to store Reports.CategoryId
    because the column is still an identity column (or the id is unknown)."""
    text = str(exc)
    low = text.lower()
    if (
        "428c9" in low
        or ("non-default value" in low and "categoryid" in low)
        or ("can only be updated to default" in low and "categoryid" in low)
    ):
        return RuntimeError(
            'The database won\'t let the app set Reports."CategoryId" because the column '
            "is GENERATED ALWAYS AS IDENTITY. A category column must hold the id of a "
            "ReportCategory row, so run this once in the Supabase SQL editor and try "
            f"again:  {CATEGORY_FIX_SQL}"
        )
    if "reports_categoryid_fkey" in low or ("23503" in low and "categoryid" in low):
        return RuntimeError(
            "The report's category was not found in the ReportCategory table. "
            f"({text})"
        )
    return None


# ReportCategory holds two categories: "Hardware" and "Software".
# Every problem is sorted into one of them by its name (see _problem_category);
# the report's category comes from its first selected problem.
HARDWARE_CATEGORY = "Hardware"
SOFTWARE_CATEGORY = "Software"

# Words that make a problem a Hardware or a Software problem. Checked against
# the words of the problem name ("PeripheralMalfunction" -> peripheral,
# malfunction; "Keyboard / mouse" -> keyboard, mouse). Hardware is checked first.
HARDWARE_WORDS = (
    "hardware",
    "display",
    "monitor",
    "screen",
    "keyboard",
    "mouse",
    "peripheral",
    "power",
    "turn",
    "cable",
    "printer",
    "speaker",
    "headset",
    "headphone",
    "port",
    "usb",
    "fan",
    "battery",
    "missing",
    "broken",
    "damaged",
    "physical",
)
SOFTWARE_WORDS = (
    "software",
    "os",
    "operating",
    "program",
    "application",
    "app",
    "virus",
    "malware",
    "update",
    "install",
    "slow",
    "freez",
    "hang",
    "crash",
    "error",
    "internet",
    "connect",
    "network",
    "wifi",
    "browser",
    "login",
    "password",
    "license",
    "performance",
)
# Problems that match neither list (e.g. "Other") are saved as:
DEFAULT_CATEGORY = HARDWARE_CATEGORY


def _words(text: Any) -> List[str]:
    """'PeripheralMalfunction' -> ['peripheral', 'malfunction'];
    "Won't turn on" -> ['won', 't', 'turn', 'on']."""
    import re

    return [
        w.lower()
        for w in re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+", _clean_text(text))
    ]


def _problem_category(issue_name: str) -> str:
    """'Hardware' or 'Software' for a problem name."""
    words = _words(issue_name)

    def has(keywords) -> bool:
        return any(
            w == k or (len(k) >= 4 and w.startswith(k)) for w in words for k in keywords
        )

    if has(HARDWARE_WORDS):
        return HARDWARE_CATEGORY
    if has(SOFTWARE_WORDS):
        return SOFTWARE_CATEGORY
    return DEFAULT_CATEGORY


def _simple(text: Any) -> str:
    """Lower-case letters and digits only ("Keyboard / mouse" -> "keyboardmouse")."""
    return "".join(ch for ch in _clean_text(text).lower() if ch.isalnum())


def _resolve_category_id(
    issue_name: str,
    issue_row: Optional[Dict[str, Any]] = None,
    category: Optional[str] = None,
) -> int:
    """
    Reports.CategoryId: the ReportCategory row "Hardware" or "Software".

    `category` is what the teacher picked on the form (Hardware / Software) and
    is used as is. Without it the category is worked out from the problem name
    (see _problem_category).
    """

    if issue_row and issue_row.get("CategoryId") not in (None, ""):
        try:
            return int(issue_row["CategoryId"])
        except (TypeError, ValueError):
            pass

    def read_categories():
        return _response_data(
            get_supabase()
            .table(REPORT_CATEGORY_TABLE)
            .select("CategoryId, Category")
            .execute()
        )

    try:
        # Kept for a few minutes: the categories (Hardware / Software) rarely change.
        category_rows = perf.lookup(
            "report_categories",
            technician_service.LOOKUP_CACHE_SECONDS,
            read_categories,
        )
    except Exception as exc:
        raise RuntimeError(
            f"Could not read the {REPORT_CATEGORY_TABLE} table: {exc}"
        ) from exc

    picked = _simple(category)
    if picked == _simple(HARDWARE_CATEGORY):
        wanted = HARDWARE_CATEGORY
    elif picked == _simple(SOFTWARE_CATEGORY):
        wanted = SOFTWARE_CATEGORY
    else:
        wanted = _problem_category(issue_name)

    for row in category_rows:
        if row.get("CategoryId") is not None and _simple(
            row.get("Category")
        ) == _simple(wanted):
            return int(row["CategoryId"])

    raise ValueError(
        f"The {REPORT_CATEGORY_TABLE} table has no '{wanted}' category, so the "
        f"report can't be saved. Add it in Supabase (Category = '{wanted}')."
    )


MAX_ISSUE_LENGTH = 120


def _check_issue_names(issues: List[str]) -> None:
    """
    Reports.Issues is a plain text[] (no link to ReportIssues), so the problem
    the teacher selected is saved exactly as shown on the form.
    """
    for name in issues:
        if len(name) > MAX_ISSUE_LENGTH:
            raise ValueError(
                f"The problem name is too long (max {MAX_ISSUE_LENGTH} characters)."
            )


def _where(computer: Optional[Dict[str, Any]]) -> str:
    """'Centrum 1 PC 05' for a Computers row (for notification texts)."""
    if not computer:
        return "a computer"
    room = _clean_text(computer.get("Room")) or "Laboratory"
    try:
        return f"{room} PC {int(computer.get('UnitNumber')):02d}"
    except (TypeError, ValueError):
        return room


def _computer_for(report: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    try:
        return _get_computer(report.get("ComputerId"))
    except Exception:
        return None


def _issues_overlap(row_issues: Any, wanted: List[str]) -> bool:
    """True if a report's Issues share at least one problem with `wanted`."""
    have = {_simple(i) for i in _normalize_issues(row_issues)}
    return any(_simple(i) in have for i in wanted)


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


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value: Any) -> Optional[datetime]:
    """Parse a Supabase timestamp into an aware datetime (UTC if no zone)."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _hours_since(value: Any) -> float:
    dt = _parse_dt(value)
    if dt is None:
        return 0.0
    return (_now_utc() - dt).total_seconds() / 3600


def _local_tz():
    """The school's time zone. Windows has no time-zone database unless the
    'tzdata' package is installed, so fall back to Manila's fixed UTC+8
    (the Philippines has no daylight saving time)."""
    try:
        return ZoneInfo(LOCAL_TZ)
    except Exception:
        return timezone(timedelta(hours=8), "PHT")


def _same_local_day(a: datetime, b: datetime) -> bool:
    tz = _local_tz()
    return a.astimezone(tz).date() == b.astimezone(tz).date()


def _require_reason(reason: Any, action: str) -> str:
    reason = _clean_text(reason)
    if len(reason) < MIN_REASON:
        raise ValueError(f"Please give the reason for {action}.")
    return reason


def _get_own_report(teacher: Any, report_id: Any) -> Dict[str, Any]:
    """Load a report and make sure it belongs to this teacher."""
    user_id = _get_user_id(teacher)
    if user_id is None:
        raise ValueError("Unable to determine the teacher's Users.UserId.")

    # Accept the ReportId (25) or the code the screens show ("CL-0025").
    text = _clean_text(report_id)
    if text.upper().startswith("CL-"):
        text = text[3:]
    try:
        report_id = int(text)
    except (TypeError, ValueError):
        raise ValueError("Invalid ReportId.")

    base = (
        "ReportId, ComputerId, ReportedBy, ReporterName, Issues, Comment, "
        "HandledBy, StatusId, CategoryId, CreatedAt, UpdatedAt"
    )

    def load(columns: str):
        return (
            get_supabase()
            .table(REPORTS_TABLE)
            .select(columns)
            .eq("ReportId", report_id)
            .limit(1)
            .execute()
        )

    # The Teacher columns (CancelReason, EditReason, LastFollowUpAt,
    # FollowUpMessage) are optional: without them the report is still loaded
    # and `_has_extra` says they are missing.
    try:
        row = _first(load(base + ", " + REPORT_EXTRA_COLUMNS))
        if row is not None:
            row["_has_extra"] = True
    except Exception:
        row = _first(load(base))
        if row is not None:
            row["_has_extra"] = False

    if not row:
        raise ValueError(f"Report {report_id} does not exist.")
    if int(row.get("ReportedBy") or 0) != user_id:
        raise ValueError("You can only change your own reports.")
    return row


def _require_extra_columns(report: Dict[str, Any]) -> None:
    """Edit / Cancel store their reason in the Teacher columns."""
    if not report.get("_has_extra"):
        raise RuntimeError(
            "The Reports table is missing the new columns "
            f"({REPORT_EXTRA_COLUMNS}). Run teacher_migration.sql in Supabase."
        )


def _picked_up(report: Dict[str, Any]) -> bool:
    """
    True once a technician has acted on the report.

    Technicians stamp Reports.HandledBy when they change a report's status.
    New teacher reports have HandledBy empty (or, for reports made through
    reports_repository.create_report, equal to the reporter's own id).
    """
    handled = report.get("HandledBy")
    if handled in (None, ""):
        return False
    try:
        return int(handled) != int(report.get("ReportedBy") or 0)
    except (TypeError, ValueError):
        return True


def _status_rows() -> List[Dict[str, Any]]:
    # Shared, cached ReportStatus rows (see technician_service._status_rows).
    return technician_service._status_rows()


def _find_cancelled_status_id(
    rows: Optional[List[Dict[str, Any]]] = None,
) -> Optional[int]:
    """StatusId of the 'Cancelled' row, found by name (not by a fixed number)."""
    for row in rows if rows is not None else _status_rows():
        if _clean_text(row.get("CurrentStatus")).lower() in ("cancelled", "canceled"):
            try:
                return int(row["StatusId"])
            except (TypeError, ValueError, KeyError):
                continue
    return None


def _ensure_cancelled_status() -> int:
    """StatusId of 'Cancelled'; adds the ReportStatus row if it is missing."""
    found = _find_cancelled_status_id()
    if found is not None:
        return found

    try:
        response = (
            get_supabase()
            .table(REPORT_STATUS_TABLE)
            .insert({"CurrentStatus": STATUS_CANCELLED_NAME})
            .execute()
        )
        created = _first(response)
        perf.invalidate_lookups()  # ReportStatus has a new row
        if created and created.get("StatusId") is not None:
            reports_repo.invalidate_status_cache()
            return int(created["StatusId"])
    except Exception as exc:
        raise RuntimeError(
            "ReportStatus has no 'Cancelled' row and it could not be added. "
            f"Run teacher_migration.sql in Supabase. ({exc})"
        ) from exc

    found = _find_cancelled_status_id()
    if found is None:
        raise RuntimeError(
            "ReportStatus has no 'Cancelled' row. Run teacher_migration.sql in Supabase."
        )
    return found


def _recent_reports_for(user_id: int, computer_id: int) -> List[Dict[str, Any]]:
    """This teacher's latest reports on this computer (newest first)."""
    response = (
        get_supabase()
        .table(REPORTS_TABLE)
        .select("ReportId, StatusId, Issues, CreatedAt")
        .eq("ComputerId", computer_id)
        .eq("ReportedBy", user_id)
        .order("CreatedAt", desc=True)
        .limit(50)
        .execute()
    )
    return _response_data(response)


def _same_issue_reported_today(
    user_id: int,
    computer_id: int,
    issues: List[str],
    skip_report_id: Optional[int] = None,
    recent: Optional[List[Dict[str, Any]]] = None,
) -> bool:
    """Same teacher + computer + any of the same problems already reported today
    (cancelled ones don't count). Problems are compared by name in Reports.Issues.

    `recent`: the rows from _recent_reports_for(), when the caller already has
    them (saves reading the same rows twice)."""
    if recent is None:
        recent = _recent_reports_for(user_id, computer_id)
    rows = [r for r in recent if _issues_overlap(r.get("Issues"), issues)]
    if not rows:
        return False

    cancelled_id = _find_cancelled_status_id()
    now = _now_utc()
    for row in rows:
        if skip_report_id is not None and row.get("ReportId") == skip_report_id:
            continue
        if cancelled_id is not None and row.get("StatusId") == cancelled_id:
            continue
        created = _parse_dt(row.get("CreatedAt"))
        if created and _same_local_day(created, now):
            return True
    return False


# ============================================================
# COMPUTER DATA
# ============================================================


def get_computers() -> List[Dict[str, Any]]:
    """
    Get all computers together with their hardware and software.

    Speed: shared by every teacher for COMPUTERS_CACHE_SECONDS (any change
    clears it at once - see main.py).
    """

    return perf.cached("teacher_computers", COMPUTERS_CACHE_SECONDS, _load_computers)


def _load_computers() -> List[Dict[str, Any]]:
    # The three tables are read AT THE SAME TIME (they used to be read one
    # after another). _select_all reads in pages, so nothing is cut off at
    # Supabase's 1000-row limit (the hardware and software lists used to be).
    select_all = technician_service._select_all

    data = perf.parallel(
        computers=lambda: select_all(
            COMPUTERS_TABLE,
            "ComputerId,Room,UnitNumber,Status,EscalationStatus,CreatedAt,UpdatedAt",
            "ComputerId",
        ),
        hardware=lambda: select_all(
            HARDWARE_TABLE,
            "HardwareId,ComputerId,Processor,Ram,Storage,Peripherals,Graphics,"
            "Monitor,OperatingSystem,CreatedAt",
            "HardwareId",
        ),
        software=lambda: select_all(
            SOFTWARE_TABLE,
            "SoftwareId,ComputerId,SoftwareName,Version,DateInstalled,CreatedAt,UpdatedAt",
            # Paged by the unique id (paging by a non-unique name can skip rows);
            # sorted by name below.
            "SoftwareId",
        ),
    )

    computers = data["computers"]

    if not computers:
        return []

    # Same order as before: by Room, then UnitNumber.
    def room_unit(row):
        try:
            unit = int(row.get("UnitNumber") or 0)
        except (TypeError, ValueError):
            unit = 0
        return (str(row.get("Room") or ""), unit)

    computers.sort(key=room_unit)

    hardware_map: Dict[int, Dict[str, Any]] = {}
    software_map: Dict[int, List[Dict[str, Any]]] = {}

    for hardware in data["hardware"]:
        cid = hardware.get("ComputerId")

        if cid is not None:
            # Ordered by HardwareId, so the newest record wins (same rule
            # as technician_service).
            hardware_map[int(cid)] = hardware

    for software in sorted(
        data["software"], key=lambda r: str(r.get("SoftwareName") or "")
    ):
        cid = software.get("ComputerId")

        if cid is None:
            continue

        software_map.setdefault(int(cid), []).append(software)

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


# ------------------------------------------------------------
# Shared, short-lived reads (speed)
# ------------------------------------------------------------
#
# The Teacher dashboard used to make two separate chains of reads, one after
# another inside each chain:
#     Reports (this teacher) -> Computers -> Users
#     Reports (everyone)     -> Computers -> Users     (for the live map)
# plus Computers + ComputerHardware + ComputerSoftware for the computers.
#
# Now the dashboard reads FOUR tables at the same time, once:
#     Computers, Reports, Users (names), and the cached ReportStatus rows
# and builds both report lists from that one read. The hardware/software
# tables are no longer read for the dashboard: no Teacher screen shows them
# (GET /teacher/computers still returns them).
#
# These reads are shared by every teacher for TEACHER_DATA_CACHE_SECONDS.
# Any change (POST / PATCH / DELETE) clears them at once (main.py), so a new
# report or a status change shows on the next load.

TEACHER_DATA_CACHE_SECONDS = 10

# Reports that no longer mark a computer on the live map.
CLOSED_STATUS_NAMES = {"fixed", "cancelled", "canceled"}

_COMPUTER_COLUMNS = (
    "ComputerId,Room,UnitNumber,Status,EscalationStatus,CreatedAt,UpdatedAt"
)


def _columns(text: str) -> str:
    return ",".join(part.strip() for part in text.split(","))


def _load_computer_rows() -> List[Dict[str, Any]]:
    return technician_service._select_all(
        COMPUTERS_TABLE, _COMPUTER_COLUMNS, "ComputerId"
    )


def _cached_computer_rows() -> List[Dict[str, Any]]:
    return perf.cached(
        "teacher_computer_rows", TEACHER_DATA_CACHE_SECONDS, _load_computer_rows
    )


def _load_report_rows() -> List[Dict[str, Any]]:
    """Every Reports row (read in pages, so nothing is cut off at Supabase's
    1000-row limit), newest first."""
    select_all = technician_service._select_all
    try:
        rows = select_all(
            REPORTS_TABLE,
            _columns(REPORT_BASE_COLUMNS) + "," + _columns(REPORT_EXTRA_COLUMNS),
            "ReportId",
        )
    except Exception as exc:
        # teacher_migration.sql has not been run yet: keep the dashboard
        # working (without cancel/edit reasons and follow-up times).
        logger.warning(
            "Reports is missing the Teacher columns (%s) - run "
            "teacher_migration.sql. Falling back. (%s)",
            REPORT_EXTRA_COLUMNS,
            exc,
        )
        rows = select_all(REPORTS_TABLE, _columns(REPORT_BASE_COLUMNS), "ReportId")
    rows.sort(key=lambda r: str(r.get("CreatedAt") or ""), reverse=True)
    return rows


def _cached_report_rows() -> List[Dict[str, Any]]:
    return perf.cached(
        "teacher_report_rows", TEACHER_DATA_CACHE_SECONDS, _load_report_rows
    )


def _load_user_names() -> Dict[int, Dict[str, Any]]:
    rows = technician_service._select_all(
        USERS_TABLE, "UserId,FirstName,LastName,Email", "UserId"
    )
    out: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        try:
            out[int(row["UserId"])] = row
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _cached_user_names() -> Dict[int, Dict[str, Any]]:
    return perf.cached(
        "teacher_user_names", TEACHER_DATA_CACHE_SECONDS, _load_user_names
    )


def _report_data() -> Dict[str, Any]:
    """Computers, Reports and Users names, read at the same time."""
    return perf.parallel(
        computers=_cached_computer_rows,
        rows=_cached_report_rows,
        users=_cached_user_names,
    )


def _computers_by_id(rows: List[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    out: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        try:
            out[int(row["ComputerId"])] = row
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _normalize_reports(
    rows: List[Dict[str, Any]],
    computers_map: Dict[int, Dict[str, Any]],
    users_map: Dict[int, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Reports rows -> the dicts Teacher.py reads (same shape as before)."""

    statuses_map: Dict[int, str] = {}
    for status in _status_rows():
        sid = status.get("StatusId")
        if sid is not None:
            statuses_map[int(sid)] = _clean_text(status.get("CurrentStatus"))

    result = []

    for report in rows:

        computer_id = report.get("ComputerId")
        status_id = report.get("StatusId")
        category_id = report.get("CategoryId")
        handled_by = report.get("HandledBy")

        computer = (
            computers_map.get(int(computer_id)) if computer_id is not None else None
        )

        status_name = (
            statuses_map.get(int(status_id), "") if status_id is not None else ""
        )

        # The first selected problem (Reports has no IssueId column).
        report_issues = _normalize_issues(report.get("Issues"))
        issue_name = report_issues[0] if report_issues else ""

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
                "issue_id": None,
                "IssueId": None,
                "category_id": category_id,
                "CategoryId": category_id,
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
                # Read by Teacher._report_from_db() for Cancel / Edit / Follow up.
                "cancel_reason": report.get("CancelReason") or "",
                "CancelReason": report.get("CancelReason") or "",
                "edit_reason": report.get("EditReason") or "",
                "EditReason": report.get("EditReason") or "",
                "last_follow_up_at": report.get("LastFollowUpAt"),
                "LastFollowUpAt": report.get("LastFollowUpAt"),
                "follow_up_message": report.get("FollowUpMessage") or "",
                "FollowUpMessage": report.get("FollowUpMessage") or "",
            }
        )

    return result


def get_reports(
    user: Any = None, data: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """
    Get reports, newest first.

    If a teacher user is supplied, only reports created by that teacher are
    returned. `data`: the result of _report_data() when the caller already
    has it (the dashboard), so nothing is read twice.
    """

    user_id = None

    if user is not None:
        user_id = _get_user_id(user)
        if user_id is None:
            raise ValueError("Unable to determine the application UserId.")

    data = data or _report_data()

    rows = data["rows"]

    if user_id is not None:
        rows = [r for r in rows if str(r.get("ReportedBy")) == str(user_id)]

    return _normalize_reports(rows, _computers_by_id(data["computers"]), data["users"])


# ============================================================
# TEACHER DASHBOARD
# ============================================================


def _dashboard_computer(computer: Dict[str, Any]) -> Dict[str, Any]:
    """A Computers row in the shape get_computers() returns, without the
    hardware / software lists (no Teacher screen shows them)."""
    cid = int(computer["ComputerId"])
    return {
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
        "hardware": None,
        "software": [],
    }


def get_dashboard_data(user: Any) -> Dict[str, Any]:
    """
    Get all database-backed information required by Teacher.py, from ONE
    set of reads made at the same time (see _report_data).
    """

    user_id = _get_user_id(user)
    if user_id is None:
        raise ValueError("Unable to determine the application UserId.")

    data = _report_data()
    computers_map = _computers_by_id(data["computers"])

    def room_unit(row):
        try:
            unit = int(row.get("UnitNumber") or 0)
        except (TypeError, ValueError):
            unit = 0
        return (str(row.get("Room") or ""), unit)

    computers = [
        _dashboard_computer(row)
        for row in sorted(computers_map.values(), key=room_unit)
    ]

    every_report = _normalize_reports(data["rows"], computers_map, data["users"])

    return {
        "computers": computers,
        # Only this teacher's reports (My Reports, Dashboard, notifications).
        "reports": [
            r for r in every_report if str(r.get("ReportedBy")) == str(user_id)
        ],
        # Every OPEN report, trimmed, for the Laboratory Status live map only
        # (the same reports the Admin's map shows). Fixed and cancelled ones
        # never mark a computer, so they are not sent.
        "map_reports": [
            {k: r.get(k) for k in MAP_REPORT_FIELDS}
            for r in every_report
            if _clean_text(r.get("status_name")).lower() not in CLOSED_STATUS_NAMES
        ],
    }


# Only what the live map needs (computer, problem, status, technician, dates).
# Reporter names, comments and notes of other teachers are not sent.
MAP_REPORT_FIELDS = (
    "id",
    "db_id",
    "report_id",
    "ReportId",
    "computer_id",
    "ComputerId",
    "room",
    "Room",
    "unit_number",
    "UnitNumber",
    "issues",
    "Issues",
    "issue",
    "Issue",
    "handled_by",
    "HandledBy",
    "handled_by_name",
    "HandledByName",
    "status_id",
    "StatusId",
    "status_name",
    "CurrentStatus",
    "created_at",
    "CreatedAt",
    "updated_at",
    "UpdatedAt",
)


def get_map_reports() -> List[Dict[str, Any]]:
    """Every open report, trimmed to MAP_REPORT_FIELDS (kept for callers)."""
    return [
        {k: r.get(k) for k in MAP_REPORT_FIELDS}
        for r in get_reports(None)
        if _clean_text(r.get("status_name")).lower() not in CLOSED_STATUS_NAMES
    ]


# ============================================================
# SUBMIT TEACHER REPORT
# ============================================================


def submit_report(
    teacher: Any,
    computer_id: Any,
    issues: Any,
    comment: str = "",
    category: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a new Teacher report.

    Database mapping:

        Reports.ComputerId
        Reports.ReportedBy
        Reports.ReporterName
        Reports.Issues          <- the problem(s) the teacher selected
        Reports.Comment         <- the details the teacher typed (only that)
        Reports.ResolutionNote  <- empty; the technician's note goes here later
        Reports.HandledBy
        Reports.StatusId
        Reports.CategoryId      <- Hardware / Software, as picked on the form

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

    try:
        computer_number = int(computer_id)
    except (TypeError, ValueError):
        raise ValueError("Invalid ComputerId.")

    # Speed: the user, the computer and this teacher's recent reports on it
    # are read AT THE SAME TIME (they were read one after another, and the
    # recent reports were read twice).
    found = perf.parallel(
        user=lambda: _get_user(user_id),
        computer=lambda: _get_computer(computer_number),
        recent=lambda: _recent_reports_for(user_id, computer_number),
    )

    db_user = found["user"]

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

    computer = found["computer"]

    computer_id = int(computer["ComputerId"])

    # --------------------------------------------------------
    # Validate Issues
    # --------------------------------------------------------

    cleaned_issues = _normalize_issues(issues)

    if not cleaned_issues:
        raise ValueError("Please select at least one issue.")

    # --------------------------------------------------------
    # Problems and CategoryId
    # --------------------------------------------------------
    #
    # The selected problems are saved as they are in Issues.
    # CategoryId is the Hardware / Software choice from the form.
    #

    _check_issue_names(cleaned_issues)

    category_id = _resolve_category_id(cleaned_issues[0], category=category)

    # --------------------------------------------------------
    # Get actual initial status
    # --------------------------------------------------------

    initial_status = _get_initial_status()

    status_id = int(initial_status["StatusId"])

    # --------------------------------------------------------
    # Prevent duplicate active report
    # --------------------------------------------------------
    #
    # Same teacher + computer + SAME problem that is still open
    # (Reported / Under repair / Escalated / Follow Up). Fixed and
    # Cancelled reports no longer block a new report, and a different
    # problem on the same computer is allowed (Teacher.py says so).
    #
    # Same-day rule (also enforced in Teacher.py): the same problem on
    # the same computer can't be reported twice in one day.
    #

    client = get_supabase()

    recent = found["recent"]

    for existing in recent:

        if not _issues_overlap(existing.get("Issues"), cleaned_issues):
            continue

        try:
            existing_status = int(existing.get("StatusId"))
        except (TypeError, ValueError):
            continue

        if existing_status in OPEN_STATUS_IDS:

            raise ValueError(
                "You already have an open report for this problem on this "
                "computer. You can follow it in My Reports."
            )

    if _same_issue_reported_today(user_id, computer_id, cleaned_issues, recent=recent):
        raise ValueError(
            "This issue has already been reported today for this computer. "
            "If the same problem happens again, please report it tomorrow."
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
        "StatusId": status_id,
        # Required FK -> ReportCategory; always sent (see REPORT_BASE_COLUMNS).
        "CategoryId": category_id,
        # ReportId, CreatedAt: database defaults. UpdatedAt stays NULL until
        # the report is changed.
    }

    # --------------------------------------------------------
    # INSERT
    # --------------------------------------------------------

    try:

        response = client.table(REPORTS_TABLE).insert(row).execute()

    except Exception as exc:

        clear = _category_write_error(exc)
        if clear is not None:
            raise clear from exc

        raise RuntimeError(
            "Failed to insert the Teacher report into the " f"Reports table: {exc}"
        ) from exc

    inserted = _first(response)

    if not inserted:

        raise RuntimeError(
            "The report insert completed but Supabase returned " "no inserted record."
        )

    # --------------------------------------------------------
    # Notifications (best effort, never fail the report)
    # --------------------------------------------------------

    code = notify.report_code(inserted.get("ReportId"))
    problems = ", ".join(cleaned_issues)
    where = _where(computer)
    # Sent after the response, so the teacher doesn't wait for them.
    perf.background(
        notify.notify_technicians,
        "new_report",
        notify.message(
            f"New report · {where}", f"{code} · {problems} · by {teacher_name}"
        ),
    )
    perf.background(
        notify.notify_admins,
        "activity",
        notify.message(
            f"Report sent · {where}", f"{code} · {problems} · by {teacher_name}"
        ),
    )

    # --------------------------------------------------------
    # Return normalized result
    # --------------------------------------------------------

    return inserted


# ============================================================
# FOLLOW UP / EDIT / CANCEL A REPORT
# ============================================================
#
# Backs the buttons in Teacher.py "My Reports":
#   follow_up_teacher_report -> follow_up_report
#   update_teacher_report    -> update_report
#   cancel_teacher_report    -> cancel_report
#
# Rules (same as Teacher.py):
#   * only the teacher who sent the report can change it
#   * Edit / Cancel only while the report is still "Reported" and need a reason
#   * Follow up only while still "Reported", after FOLLOW_UP_AFTER_HOURS,
#     and at most once every FOLLOW_UP_EVERY_HOURS
#


def follow_up_report(
    teacher: Any,
    report_id: Any,
    message: str = "",
) -> Dict[str, Any]:
    """Send a follow-up on a report nobody has picked up yet."""

    report = _get_own_report(teacher, report_id)

    if report.get("StatusId") != STATUS_REPORTED:
        raise ValueError("Only a report that is still waiting can be followed up.")

    if _picked_up(report):
        raise ValueError("A technician has already picked this report up.")

    if _hours_since(report.get("CreatedAt")) < FOLLOW_UP_AFTER_HOURS:
        raise ValueError(
            f"You can follow up after {FOLLOW_UP_AFTER_HOURS // 24} days "
            "with no action."
        )

    # When was the last follow-up? Reports.FollowUpDate if that column
    # exists; else LastFollowUpAt; else Reports.UpdatedAt (a waiting report
    # only changes when the teacher edits it or follows it up).
    follow_up_date, has_follow_up_date = None, False
    try:
        dated = _first(
            get_supabase()
            .table(REPORTS_TABLE)
            .select("FollowUpDate")
            .eq("ReportId", report["ReportId"])
            .limit(1)
            .execute()
        )
        has_follow_up_date = True
        follow_up_date = (dated or {}).get("FollowUpDate")
    except Exception:
        pass  # column not added yet

    if has_follow_up_date:
        last = follow_up_date
    else:
        last = (
            report.get("LastFollowUpAt")
            if report.get("_has_extra")
            else report.get("UpdatedAt")
        )
    if last and _hours_since(last) < FOLLOW_UP_EVERY_HOURS:
        raise ValueError(
            "You already sent a follow-up today. You can send another one tomorrow."
        )

    now = _now_utc().isoformat()

    changes = {"UpdatedAt": now}
    if has_follow_up_date:
        changes["FollowUpDate"] = now
    if report.get("_has_extra"):
        changes.update(LastFollowUpAt=now, FollowUpMessage=_clean_text(message))

    response = (
        get_supabase()
        .table(REPORTS_TABLE)
        .update(changes)
        .eq("ReportId", report["ReportId"])
        .eq("StatusId", STATUS_REPORTED)
        .execute()
    )

    updated = _first(response)
    if not updated:
        raise RuntimeError("The follow-up was not saved (the report may have changed).")

    # Best effort: tell the active technicians (and the admins). Never fails
    # the follow-up; NotificationPreferences decide who gets it.
    text = _clean_text(message)
    code = notify.report_code(report["ReportId"])
    who = report.get("ReporterName") or "a teacher"
    details = f"{code} · still waiting for a technician · from {who}"
    if text:
        details += f" · {text}"

    def send():
        where = _where(_computer_for(report))
        notify.notify_technicians(
            "follow_up", notify.message(f"Follow-up · {where}", details)
        )
        notify.notify_admins(
            "activity", notify.message(f"Follow-up sent · {where}", details)
        )

    # Sent after the response, so the teacher doesn't wait for it.
    perf.background(send)

    return updated


def update_report(
    teacher: Any,
    report_id: Any,
    issues: Any,
    comment: str = "",
    reason: str = "",
    category: Optional[str] = None,
) -> Dict[str, Any]:
    """Edit the problem / details / urgency of a report that is still 'Reported'."""

    report = _get_own_report(teacher, report_id)

    if report.get("StatusId") != STATUS_REPORTED:
        raise ValueError(
            "You can only edit a report while it's still waiting for a technician."
        )

    if _picked_up(report):
        raise ValueError("A technician has already picked this report up.")

    _require_extra_columns(report)

    reason = _require_reason(reason, "the edit")

    cleaned_issues = _normalize_issues(issues)
    if not cleaned_issues:
        raise ValueError("Please select at least one issue.")

    _check_issue_names(cleaned_issues)
    category_id = _resolve_category_id(cleaned_issues[0], category=category)

    added = [
        i for i in cleaned_issues if not _issues_overlap(report.get("Issues"), [i])
    ]

    if added and _same_issue_reported_today(
        int(report["ReportedBy"]),
        int(report["ComputerId"]),
        added,
        skip_report_id=int(report["ReportId"]),
    ):
        raise ValueError(
            "This issue has already been reported today for this computer. "
            "If the same problem happens again, please report it tomorrow."
        )

    now = _now_utc().isoformat()

    try:
        response = (
            get_supabase()
            .table(REPORTS_TABLE)
            .update(
                {
                    "Issues": cleaned_issues,
                    "CategoryId": category_id,
                    "Comment": _clean_text(comment),
                    "EditReason": reason,
                    "UpdatedAt": now,
                }
            )
            .eq("ReportId", report["ReportId"])
            .eq("StatusId", STATUS_REPORTED)
            .execute()
        )
    except Exception as exc:
        clear = _category_write_error(exc)
        if clear is not None:
            raise clear from exc
        raise

    updated = _first(response)
    if not updated:
        raise RuntimeError(
            "The report was not updated (it may have just been picked up)."
        )

    def send():
        notify.notify_admins(
            "activity",
            notify.message(
                f"Report edited · {_where(_computer_for(report))}",
                f"{notify.report_code(report['ReportId'])} · {', '.join(cleaned_issues)} · "
                f"by {report.get('ReporterName') or 'a teacher'} · reason: {reason}",
            ),
        )

    # Sent after the response, so the teacher doesn't wait for it.
    perf.background(send)

    return updated


def cancel_report(
    teacher: Any,
    report_id: Any,
    reason: str = "",
) -> Dict[str, Any]:
    """Cancel a report that is still 'Reported' (StatusId 6)."""

    report = _get_own_report(teacher, report_id)

    if report.get("StatusId") != STATUS_REPORTED:
        raise ValueError(
            "You can only cancel a report while it's still waiting for a technician."
        )

    if _picked_up(report):
        raise ValueError("A technician has already picked this report up.")

    _require_extra_columns(report)

    reason = _require_reason(reason, "cancelling")

    cancelled_id = _ensure_cancelled_status()
    now = _now_utc().isoformat()

    response = (
        get_supabase()
        .table(REPORTS_TABLE)
        .update(
            {
                "StatusId": cancelled_id,
                "CancelReason": reason,
                "UpdatedAt": now,
            }
        )
        .eq("ReportId", report["ReportId"])
        .eq("StatusId", STATUS_REPORTED)
        .execute()
    )

    updated = _first(response)
    if not updated:
        raise RuntimeError(
            "The report was not cancelled (it may have just been picked up)."
        )

    def send():
        notify.notify_admins(
            "activity",
            notify.message(
                f"Report cancelled · {_where(_computer_for(report))}",
                f"{notify.report_code(report['ReportId'])} · "
                f"by {report.get('ReporterName') or 'a teacher'} · reason: {reason}",
            ),
        )

    # Sent after the response, so the teacher doesn't wait for it.
    perf.background(send)

    return updated


# ============================================================
# DEACTIVATE MY ACCOUNT
# ============================================================


def deactivate_account(user: Any, reason: str = "") -> Dict[str, Any]:
    """
    Deactivate the teacher's own account (Users.Status -> Inactive).

    Reports stay in the system; an admin can reactivate the account.
    auth_service checks Users.Status on every login/token, so this blocks
    access immediately. The auth user is NOT banned, so an admin can reactivate.
    """

    user_id = _get_user_id(user)
    if user_id is None:
        raise ValueError("Unable to determine Users.UserId.")

    reason = _require_reason(reason, "deactivating your account")

    _get_user(user_id)  # raises if the user does not exist

    updated = users.update_status(user_id, USER_STATUS_INACTIVE)
    if not updated:
        raise RuntimeError("The account was not deactivated.")

    logger.info(
        "Teacher UserId=%s deactivated their account. Reason: %s", user_id, reason
    )

    return updated


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

    try:
        response = (
            client.table(REPORT_ISSUES_TABLE)
            .select("IssueId, Name")
            .order("IssueId")
            .execute()
        )
    except Exception as exc:
        if _table_missing(exc):
            # No ReportIssues table any more: the Teacher form uses its own list.
            return []
        raise

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
