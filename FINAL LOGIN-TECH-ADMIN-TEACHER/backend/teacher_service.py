"""
Centrum Laboratory - Teacher business logic.

Everything the Teacher dashboard needs from the backend lives here: the lab
computers, the teacher's own problem reports, the repair history of each unit,
submitting a new report, and the teacher's own profile and password.

It adds no new connection or login code; it reuses the existing services:

    auth_service.py        who is logged in (user_from_token), password change
    users_repository.py    Users table (contact number, through
                           technician_service), _run() + DatabaseError
    technician_service.py  the shared lab data: Computers + Reports tables,
                           their column lists and row -> dict helpers
    database.py            the shared Supabase client (used by the modules above)
    email_service.py       used by auth_service for verification / reset codes

No credentials are read here; database.py loads them from the root .env.

Tables used (created once - see the SQL at the top of technician_service.py)
------------------------------------------------------------------------------
    "Computers"  read   - rooms, units, statuses, specs
    "Reports"    read   - the teacher's reports + every unit's repair history
                 insert - a new report (Status 'progress'); technicians then
                          resolve / flag it from their dashboard
"""

from __future__ import annotations

import logging

from . import auth_service
from . import technician_service as lab
from .users_repository import DatabaseError, _run

logger = logging.getLogger("centrum.teacher")


# =========================================================
# SETTINGS
# =========================================================

TEACHER_ROLE = "Teacher"

# The shared report columns plus ReportedBy, to pick out the teacher's own reports.
REPORT_COLUMNS = lab.REPORT_COLUMNS + ",ReportedBy"

MAX_ISSUES = 10
MAX_ISSUE_LENGTH = 100
MAX_COMMENT_LENGTH = lab.MAX_NOTE_LENGTH
MAX_ROOM_LENGTH = 50


# =========================================================
# ACCESS CHECK
# =========================================================


def is_teacher(user: dict | None) -> bool:
    """True if the user's role (from auth_service / Users.RoleId) is Teacher."""

    role = str((user or {}).get("role") or "").strip().lower()

    return role == TEACHER_ROLE.lower()


def current_teacher(access_token: str) -> dict:
    """Who is calling? Uses the existing login (auth_service.user_from_token).

    Returns {"success": True, "user": {...}} or {"success": False, "error": ...,
    "status_code": 401 | 403}.
    """

    result = auth_service.user_from_token(access_token)

    if not result.get("success"):

        return {**result, "status_code": 401}

    if not is_teacher(result["user"]):

        return {
            "success": False,
            "error": "This page is for teachers only.",
            "status_code": 403,
        }

    return result


# =========================================================
# HELPERS
# =========================================================


def _same_user(value, user_id) -> bool:

    return user_id not in (None, "") and str(value or "").strip() == str(user_id)


def _clean_issues(issues) -> list[str] | str:
    """Cleaned issue list, or an error message."""

    if isinstance(issues, str):
        issues = [issues]

    if not isinstance(issues, (list, tuple)):
        return "Pick at least one issue."

    cleaned = []

    for issue in issues:

        text = " ".join(str(issue or "").split())

        if not text:
            continue

        if len(text) > MAX_ISSUE_LENGTH:
            return f"Each issue can be at most {MAX_ISSUE_LENGTH} characters."

        if text.lower() not in (i.lower() for i in cleaned):
            cleaned.append(text)

    if not cleaned:
        return "Pick at least one issue."

    if len(cleaned) > MAX_ISSUES:
        return f"Pick at most {MAX_ISSUES} issues."

    return cleaned


# =========================================================
# DASHBOARD DATA
# =========================================================


def get_dashboard_data(teacher: dict) -> dict:
    """Computers, the teacher's own reports, and every unit's repair history.

    "history" has no reporter names, so teachers don't see who else reported.
    Raises DatabaseError (handled by main.py) if Supabase can't be read.
    """

    units = [
        lab._unit_from_row(row)
        for row in lab._select_all(
            lab.COMPUTERS_TABLE, lab.COMPUTER_COLUMNS, "ComputerId"
        )
    ]

    rows = lab._select_all(lab.REPORTS_TABLE, REPORT_COLUMNS, "ReportId")

    user_id = teacher.get("user_id")

    mine = [
        lab._report_from_row(row)
        for row in rows
        if _same_user(row.get("ReportedBy"), user_id)
    ]

    history = []

    for row in rows:

        report = lab._report_from_row(row)
        report["reporter"] = ""  # privacy: history is shared between teachers
        history.append(report)

    return {
        "success": True,
        "units": [unit for unit in units if unit["room"] and unit["number"]],
        "reports": [report for report in mine if report["room"]],
        "history": [report for report in history if report["room"]],
    }


# =========================================================
# SUBMIT A REPORT
# =========================================================


def submit_report(
    teacher: dict, room: str, unit_number, issues, comment: str = ""
) -> dict:
    """Save a new problem report (Status 'progress') for one computer."""

    room = " ".join(str(room or "").split())
    number = lab._parse_int(unit_number)

    if not room or len(room) > MAX_ROOM_LENGTH or number is None:

        return {"success": False, "error": "Select a room and a computer unit."}

    cleaned = _clean_issues(issues)

    if isinstance(cleaned, str):

        return {"success": False, "error": cleaned}

    comment = (comment or "").strip()

    if len(comment) > MAX_COMMENT_LENGTH:

        return {
            "success": False,
            "error": f"The comment is too long (max {MAX_COMMENT_LENGTH} characters).",
        }

    user_id = teacher.get("user_id")

    if user_id in (None, ""):

        return {"success": False, "error": "Your user profile could not be found."}

    # The unit must exist in Computers (the dashboard only offers those).
    def find_unit(client):
        response = (
            client.table(lab.COMPUTERS_TABLE)
            .select("ComputerId")
            .eq("Room", room)
            .eq("UnitNumber", number)
            .limit(1)
            .execute()
        )
        return bool(response.data)

    if not _run("checking a computer unit", find_unit):

        return {
            "success": False,
            "error": f"{room} unit {number:02d} is not in the Computers table.",
        }

    row = {
        "Room": room,
        "UnitNumber": number,
        "ReportedBy": str(user_id),
        "ReporterName": lab._person_name(teacher),
        "Issues": cleaned,
        "Comment": comment,
        "Status": "progress",
    }

    def insert(client):
        response = client.table(lab.REPORTS_TABLE).insert(row).execute()
        return response.data[0] if response.data else None

    saved = _run("saving a report", insert)

    if not saved:

        return {"success": False, "error": "The report could not be saved."}

    report = lab._report_from_row(saved)

    logger.info("Report %s submitted for %s unit %02d", report["code"], room, number)

    return {
        "success": True,
        "message": f"Report {report['code']} submitted",
        "report": report,
    }


# =========================================================
# PROFILE / PASSWORD  (reuse technician_service and auth_service)
# =========================================================


def update_contact_number(teacher: dict, contact_number: str) -> dict:

    # Same validation and Users update the Technician settings use.
    return lab.update_contact_number(teacher, contact_number)


def change_password(teacher: dict, current_password: str, new_password: str) -> dict:

    return auth_service.change_password(
        email=teacher.get("email") or "",
        current_password=current_password,
        new_password=new_password,
    )


__all__ = [
    "DatabaseError",
    "change_password",
    "current_teacher",
    "get_dashboard_data",
    "is_teacher",
    "submit_report",
    "update_contact_number",
]
