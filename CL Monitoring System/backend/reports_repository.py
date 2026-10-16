"""
Centrum Laboratory - Repository for report-related tables.

Covers:

    Reports
    -------
    ReportId        bigint  GENERATED ALWAYS AS IDENTITY  PK
    ComputerId      bigint  NOT NULL  FK → Computers.ComputerId
    ReportedBy      bigint  NOT NULL  FK → Users.UserId
    ReporterName    text    NOT NULL  DEFAULT ''
    Issues          text[]  NOT NULL  DEFAULT '{}'
    Comment         text    NOT NULL  DEFAULT ''
    ResolutionNote  text    NOT NULL  DEFAULT ''
    HandledBy       bigint  NOT NULL  FK → Users.UserId
    CreatedAt       timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
    UpdatedAt       timestamptz
    IssueId         integer (nullable)  FK → ReportIssues.IssueId
    StatusId        bigint  NOT NULL  FK → ReportStatus.StatusId

    ReportStatus
    ------------
    StatusId       bigint  PK
    CurrentStatus  text    NOT NULL

    ReportIssues
    ------------
    IssueId  integer  GENERATED ALWAYS AS IDENTITY  PK
    Name     varchar  NOT NULL  UNIQUE

    Notifications
    -------------
    NotificationId  bigint  GENERATED ALWAYS AS IDENTITY  PK
    UserId          bigint  NOT NULL  FK → Users.UserId
    Message         text    NOT NULL
    IsRead          boolean NOT NULL DEFAULT false
    CreatedAt       timestamptz NOT NULL DEFAULT now()
    UpdatedAt       timestamptz DEFAULT now()

    NotificationPreferences
    -----------------------
    Id                  integer  PK  (NOT GENERATED — caller supplies it)
    UserId              bigint   FK → Users.UserId
    EmailNotifications  boolean  NOT NULL DEFAULT false
    WeeklySummary       boolean  NOT NULL DEFAULT true
    NewReport           boolean  (nullable)
    Escalation          boolean  DEFAULT true
    CreatedAt           timestamptz DEFAULT now()
    UpdatedAt           timestamptz

IMPORTANT SCHEMA NOTES
-----------------------
* Reports.HandledBy is NOT NULL in the schema.  New reports that have no
  handler yet must supply a placeholder value (e.g. the reporter's own UserId,
  or a sentinel UserId=0 if that row exists).  This repository uses the
  reporter's UserId as the placeholder for new records and documents this.
* Reports.StatusId FK → ReportStatus.StatusId.  The status string (e.g.
  'progress', 'resolved', 'followup') is stored in ReportStatus.CurrentStatus;
  every read that needs the string must either join or do a secondary lookup.
  This repository caches the StatusId <-> CurrentStatus mapping.
* Reports.IssueId FK → ReportIssues.IssueId — nullable; kept for the primary
  issue category while Issues (text[]) stores the full list.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from .users_repository import DatabaseError, _escape_like, _run

logger = logging.getLogger("centrum.reports")


# =========================================================
# TABLE NAMES
# =========================================================

REPORTS_TABLE = "Reports"
STATUS_TABLE = "ReportStatus"
ISSUES_TABLE = "ReportIssues"
NOTIF_TABLE = "Notifications"
NOTIF_PREF_TABLE = "NotificationPreferences"


# =========================================================
# COLUMN LISTS  (only columns that exist in the schema)
# =========================================================

REPORT_COLUMNS = (
    "ReportId",
    "ComputerId",
    "ReportedBy",
    "ReporterName",
    "Issues",
    "Comment",
    "ResolutionNote",
    "HandledBy",
    "CreatedAt",
    "UpdatedAt",
    "IssueId",
    "StatusId",
)

STATUS_COLUMNS = ("StatusId", "CurrentStatus")

ISSUE_COLUMNS = ("IssueId", "Name")

NOTIF_COLUMNS = (
    "NotificationId",
    "UserId",
    "Message",
    "IsRead",
    "CreatedAt",
    "UpdatedAt",
)

NOTIF_PREF_COLUMNS = (
    "Id",
    "UserId",
    "EmailNotifications",
    "WeeklySummary",
    "NewReport",
    "Escalation",
    "CreatedAt",
    "UpdatedAt",
)

PAGE_SIZE = 1000

# =========================================================
# STATUS ID CACHE
# =========================================================
# Maps CurrentStatus (lower-case) <-> StatusId.
# Loaded once, invalidated by invalidate_status_cache().

_status_cache: dict[str, int] | None = None  # "progress" -> 1 etc.
_status_id_to_name: dict[int, str] | None = None


def _load_status_cache() -> None:
    global _status_cache, _status_id_to_name

    if _status_cache is not None:
        return

    _status_cache = {}
    _status_id_to_name = {}

    def query(client):
        return (
            client.table(STATUS_TABLE).select(",".join(STATUS_COLUMNS)).execute().data
            or []
        )

    try:
        rows = _run("loading ReportStatus", query)
        for row in rows:
            sid = row.get("StatusId")
            name = (row.get("CurrentStatus") or "").strip().lower()
            if sid is not None and name:
                _status_cache[name] = sid
                _status_id_to_name[sid] = name
    except DatabaseError as exc:
        logger.warning("Could not load ReportStatus: %s", exc)


def invalidate_status_cache() -> None:
    global _status_cache, _status_id_to_name
    _status_cache = None
    _status_id_to_name = None


def status_id_for(status_name: str) -> int | None:
    """Return the StatusId for a status string (case-insensitive), or None."""
    _load_status_cache()
    return (_status_cache or {}).get((status_name or "").strip().lower())


def status_name_for(status_id) -> str:
    """Return the CurrentStatus string for a StatusId, or 'unknown'."""
    _load_status_cache()
    return (_status_id_to_name or {}).get(status_id, "unknown")


def ensure_status(name: str) -> int:
    """
    Return the StatusId for name, inserting it into ReportStatus if missing.
    Useful for first-time setup; in production the rows should already exist.
    """
    sid = status_id_for(name)
    if sid is not None:
        return sid

    def insert(client):
        response = (
            client.table(STATUS_TABLE).insert({"CurrentStatus": name.strip()}).execute()
        )
        return response.data[0] if response.data else None

    row = _run(f"inserting ReportStatus '{name}'", insert)
    if row:
        invalidate_status_cache()
        return row["StatusId"]

    raise DatabaseError(f"Could not create status '{name}'.", code="insert_failed")


# =========================================================
# HELPERS
# =========================================================


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_int(value) -> int | None:
    try:
        n = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def _report_code(report_id) -> str:
    n = _parse_int(report_id)
    return f"CL-{n:04d}" if n else f"CL-{report_id}"


def report_from_row(row: dict) -> dict:
    issues = row.get("Issues") or []
    if isinstance(issues, str):
        issues = [issues]

    status_id = row.get("StatusId")
    status_str = status_name_for(status_id) if status_id is not None else "progress"

    return {
        "id": row.get("ReportId"),
        "report_id": row.get("ReportId"),
        "code": _report_code(row.get("ReportId")),
        "computer_id": row.get("ComputerId"),
        "reported_by": row.get("ReportedBy"),  # Users.UserId FK
        "reporter_name": (row.get("ReporterName") or "").strip() or "Unknown",
        "issues": [str(i) for i in issues if str(i).strip()] or ["General issue"],
        "comment": row.get("Comment") or "",
        "status": status_str,
        "status_id": status_id,
        "resolution_note": row.get("ResolutionNote") or "",
        "handled_by": row.get("HandledBy"),  # Users.UserId FK
        "issue_id": row.get("IssueId"),  # ReportIssues FK (nullable)
        "created_at": row.get("CreatedAt"),
        "updated_at": row.get("UpdatedAt"),
    }


# =========================================================
# REPORT ISSUES  (lookup table)
# =========================================================

_issues_cache: list[dict] | None = None


def list_report_issues() -> list[dict]:
    """All rows from ReportIssues: [{issue_id, name}, ...]."""

    global _issues_cache

    if _issues_cache is not None:
        return _issues_cache

    def query(client):
        return (
            client.table(ISSUES_TABLE)
            .select(",".join(ISSUE_COLUMNS))
            .order("Name")
            .execute()
            .data
            or []
        )

    rows = _run("listing report issues", query)
    _issues_cache = [
        {"issue_id": r.get("IssueId"), "name": r.get("Name") or ""} for r in rows
    ]
    return _issues_cache


def issue_id_for(name: str) -> int | None:
    """Return the IssueId for an issue Name (case-insensitive), or None."""
    name_lower = (name or "").strip().lower()
    for issue in list_report_issues():
        if issue["name"].lower() == name_lower:
            return issue["issue_id"]
    return None


# =========================================================
# REPORTS  —  CREATE
# =========================================================


def create_report(
    computer_id,
    reported_by_user_id,
    reporter_name: str,
    issues: list[str],
    status_name: str = "progress",
    comment: str = "",
    issue_id: int | None = None,
    handled_by_user_id=None,
) -> dict:
    """
    Insert a new Reports row and return it as an app dict.

    ReportId        is GENERATED ALWAYS AS IDENTITY.
    StatusId        is resolved from status_name via the ReportStatus table.
    HandledBy       is NOT NULL in the schema; defaults to reported_by_user_id
                    (the reporter) when no handler is assigned yet.
    """

    status_id = status_id_for(status_name)
    if status_id is None:
        raise DatabaseError(
            f"Unknown report status: {status_name!r}. "
            "Add it to the ReportStatus table first.",
            code="unknown_status",
        )

    clean_issues = [str(i).strip() for i in (issues or []) if str(i).strip()]
    if not clean_issues:
        raise ValueError("At least one issue is required.")

    now = _now_iso()

    row = {
        "ComputerId": computer_id,
        "ReportedBy": reported_by_user_id,
        "ReporterName": (reporter_name or "").strip(),
        "Issues": clean_issues,
        "Comment": (comment or "").strip(),
        "ResolutionNote": "",
        # HandledBy NOT NULL — use reporter as placeholder until assigned.
        "HandledBy": (
            handled_by_user_id
            if handled_by_user_id is not None
            else reported_by_user_id
        ),
        "StatusId": status_id,
        "IssueId": issue_id,
        "CreatedAt": now,
    }

    def insert(client):
        response = client.table(REPORTS_TABLE).insert(row).execute()
        return response.data[0] if response.data else None

    saved = _run("creating a report", insert)
    if not saved:
        raise DatabaseError("The report could not be saved.", code="insert_failed")
    return report_from_row(saved)


# =========================================================
# REPORTS  —  READ
# =========================================================


def get_report_by_id(report_id) -> dict | None:
    def query(client):
        response = (
            client.table(REPORTS_TABLE)
            .select(",".join(REPORT_COLUMNS))
            .eq("ReportId", report_id)
            .limit(1)
            .execute()
        )
        return response.data[0] if response.data else None

    row = _run("getting a report", query)
    return report_from_row(row) if row else None


def list_reports(limit: int = 1000) -> list[dict]:
    """All reports, oldest first (ReportId order)."""

    def read(client):
        rows, start = [], 0
        while True:
            response = (
                client.table(REPORTS_TABLE)
                .select(",".join(REPORT_COLUMNS))
                .order("ReportId")
                .range(start, start + PAGE_SIZE - 1)
                .execute()
            )
            batch = response.data or []
            rows.extend(batch)
            if len(batch) < PAGE_SIZE:
                return rows
            start += PAGE_SIZE

    rows = _run("listing reports", read)
    return [report_from_row(r) for r in rows]


def get_reports_by_computer(computer_id) -> list[dict]:
    """All reports for one computer (by ComputerId FK)."""

    def query(client):
        response = (
            client.table(REPORTS_TABLE)
            .select(",".join(REPORT_COLUMNS))
            .eq("ComputerId", computer_id)
            .order("CreatedAt", desc=True)
            .execute()
        )
        return response.data or []

    rows = _run("getting reports by computer", query)
    return [report_from_row(r) for r in rows]


def get_reports_by_user(user_id) -> list[dict]:
    """All reports submitted by one user (ReportedBy FK)."""

    def query(client):
        response = (
            client.table(REPORTS_TABLE)
            .select(",".join(REPORT_COLUMNS))
            .eq("ReportedBy", user_id)
            .order("CreatedAt", desc=True)
            .execute()
        )
        return response.data or []

    rows = _run("getting reports by user", query)
    return [report_from_row(r) for r in rows]


def search_reports(
    computer_id=None,
    reported_by: int | None = None,
    status_name: str | None = None,
    reporter_name_term: str | None = None,
    created_after: str | None = None,
    created_before: str | None = None,
    limit: int = 500,
) -> list[dict]:
    """
    Database-side filtering of Reports.

    computer_id         – FK exact match
    reported_by         – FK exact match on ReportedBy (Users.UserId)
    status_name         – resolved to StatusId, then exact match
    reporter_name_term  – ilike on ReporterName
    created_after       – ISO timestamp (>=)
    created_before      – ISO timestamp (<=)
    """

    def query(client):
        request = client.table(REPORTS_TABLE).select(",".join(REPORT_COLUMNS))

        if computer_id is not None:
            request = request.eq("ComputerId", computer_id)

        if reported_by is not None:
            request = request.eq("ReportedBy", reported_by)

        if status_name:
            sid = status_id_for(status_name)
            if sid is None:
                return []  # unknown status → no results
            request = request.eq("StatusId", sid)

        if reporter_name_term:
            request = request.ilike(
                "ReporterName",
                f"%{_escape_like(reporter_name_term.strip())}%",
            )

        if created_after:
            request = request.gte("CreatedAt", created_after)

        if created_before:
            request = request.lte("CreatedAt", created_before)

        return (
            request.order("CreatedAt", desc=True)
            .limit(max(1, min(int(limit), 5000)))
            .execute()
            .data
            or []
        )

    rows = _run("searching reports", query)
    return [report_from_row(r) for r in rows]


# =========================================================
# REPORTS  —  UPDATE
# =========================================================


def update_report_status(
    report_id,
    status_name: str,
    resolution_note: str,
    handled_by_user_id,
) -> dict | None:
    """
    Change a report's status and resolution note.
    Returns the updated report dict, or None if not found.
    """

    sid = status_id_for(status_name)
    if sid is None:
        raise ValueError(
            f"Unknown report status: {status_name!r}. " "Check the ReportStatus table."
        )

    row = {
        "StatusId": sid,
        "ResolutionNote": (resolution_note or "").strip(),
        "HandledBy": handled_by_user_id,
        "UpdatedAt": _now_iso(),
    }

    def update(client):
        response = (
            client.table(REPORTS_TABLE).update(row).eq("ReportId", report_id).execute()
        )
        return response.data[0] if response.data else None

    saved = _run("updating a report", update)
    return report_from_row(saved) if saved else None


# =========================================================
# REPORTS  —  DELETE
# =========================================================


def delete_report(report_id) -> bool:
    def delete(client):
        response = (
            client.table(REPORTS_TABLE).delete().eq("ReportId", report_id).execute()
        )
        return bool(response.data)

    return _run("deleting a report", delete)


# =========================================================
# NOTIFICATIONS  —  CRUD
# =========================================================


def create_notification(user_id, message: str) -> dict:
    """Insert one Notifications row.  NotificationId is GENERATED ALWAYS."""

    if not (message or "").strip():
        raise ValueError("Notification message is required.")

    now = _now_iso()
    row = {
        "UserId": user_id,
        "Message": message.strip(),
        "IsRead": False,
        "CreatedAt": now,
        "UpdatedAt": now,
    }

    def insert(client):
        response = client.table(NOTIF_TABLE).insert(row).execute()
        return response.data[0] if response.data else None

    saved = _run("creating a notification", insert)
    if not saved:
        raise DatabaseError("Notification could not be saved.", code="insert_failed")
    return saved


def list_notifications(user_id, unread_only: bool = False) -> list[dict]:
    """Return notifications for one user, newest first."""

    def query(client):
        request = (
            client.table(NOTIF_TABLE)
            .select(",".join(NOTIF_COLUMNS))
            .eq("UserId", user_id)
        )
        if unread_only:
            request = request.eq("IsRead", False)
        return request.order("CreatedAt", desc=True).execute().data or []

    return _run("listing notifications", query)


def mark_notification_read(notification_id) -> bool:
    def update(client):
        response = (
            client.table(NOTIF_TABLE)
            .update({"IsRead": True, "UpdatedAt": _now_iso()})
            .eq("NotificationId", notification_id)
            .execute()
        )
        return bool(response.data)

    return _run("marking notification read", update)


def delete_notification(notification_id) -> bool:
    def delete(client):
        response = (
            client.table(NOTIF_TABLE)
            .delete()
            .eq("NotificationId", notification_id)
            .execute()
        )
        return bool(response.data)

    return _run("deleting a notification", delete)


# =========================================================
# NOTIFICATION PREFERENCES  —  CRUD
# =========================================================


def get_notification_preferences(user_id) -> dict | None:
    def query(client):
        response = (
            client.table(NOTIF_PREF_TABLE)
            .select(",".join(NOTIF_PREF_COLUMNS))
            .eq("UserId", user_id)
            .limit(1)
            .execute()
        )
        return response.data[0] if response.data else None

    return _run("getting notification preferences", query)


def upsert_notification_preferences(
    pref_id: int,
    user_id,
    email_notifications: bool = False,
    weekly_summary: bool = True,
    new_report: bool | None = None,
    escalation: bool = True,
) -> dict:
    """
    Create or update notification preferences.
    Id is NOT GENERATED — caller supplies a unique integer.
    """

    now = _now_iso()
    row = {
        "Id": pref_id,
        "UserId": user_id,
        "EmailNotifications": email_notifications,
        "WeeklySummary": weekly_summary,
        "NewReport": new_report,
        "Escalation": escalation,
        "UpdatedAt": now,
    }

    existing = get_notification_preferences(user_id)

    if existing:
        row.pop("Id", None)
        row.pop("CreatedAt", None)

        def update(client):
            response = (
                client.table(NOTIF_PREF_TABLE)
                .update(row)
                .eq("UserId", user_id)
                .execute()
            )
            return response.data[0] if response.data else None

        saved = _run("updating notification preferences", update)
    else:
        row["CreatedAt"] = now

        def insert(client):
            response = client.table(NOTIF_PREF_TABLE).insert(row).execute()
            return response.data[0] if response.data else None

        saved = _run("inserting notification preferences", insert)

    return saved or row
