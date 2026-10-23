"""
Centrum Laboratory - in-app notifications.

Uses two existing tables (no schema changes):

    Notifications
        NotificationId  bigint identity PK
        UserId          bigint  FK -> Users.UserId   (who receives it)
        Message         text                          ("Title — details")
        IsRead          boolean default false
        CreatedAt       timestamptz default now()
        UpdatedAt       timestamptz default now()

    NotificationPreferences   (one row per role)
        RoleId          FK -> Role.RoleId
        NewReport       report activity: new reports, follow-ups, status
                        updates, edits / cancellations
        Escalation      escalated reports
        (EmailNotifications / WeeklySummary are not in-app notifications)

Who is told what
----------------
    Teacher     only about THEIR OWN reports (status updates)       -> NewReport
    Technician  new reports and follow-ups that need attention     -> NewReport
    Admin       what teachers and technicians do:
                  reports sent / edited / cancelled / updated      -> NewReport
                  escalations                                      -> Escalation
                  account requests and new accounts (no preference
                  column covers these, so they are always sent)

A preference that is false means the notification is not created for anyone
with that role. A role without a NotificationPreferences row, or a NULL
preference, counts as "on".

Every function that CREATES notifications is best effort: a failure is
logged and never breaks the action that triggered it (submitting a report,
changing its status...).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Iterable

from . import users_repository as users
from .users_repository import DatabaseError, _run

logger = logging.getLogger("centrum.notifications")

NOTIFICATIONS_TABLE = "Notifications"
PREFERENCES_TABLE = "NotificationPreferences"

# kind of notification -> NotificationPreferences column that switches it on/off
KIND_PREFERENCE = {
    "new_report": "NewReport",
    "follow_up": "NewReport",
    "report_update": "NewReport",
    "activity": "NewReport",
    "escalation": "Escalation",
    "account": None,  # no preference column: always sent
}

ADMIN_ROLE_NAMES = ("Admin", "Administrator")
TECHNICIAN_ROLE = "Technician"

MAX_MESSAGE = 500
LIST_LIMIT = 50


# =========================================================
# HELPERS
# =========================================================


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _int(value) -> int | None:
    try:
        n = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def report_code(report_id) -> str:
    """ReportId -> the code every screen shows (25 -> CL-0025)."""
    n = _int(report_id)
    return f"CL-{n:04d}" if n is not None else f"CL-{report_id}"


def message(title: str, details: str = "") -> str:
    """'Title — details', trimmed to fit (the screens split it at ' — ')."""
    text = str(title or "").strip()
    details = " ".join(str(details or "").split())
    if details:
        text = f"{text} — {details}"
    return text[:MAX_MESSAGE]


# =========================================================
# PREFERENCES
# =========================================================


def _preferences() -> dict:
    """{RoleId: NotificationPreferences row}."""
    rows = _run(
        "reading notification preferences",
        lambda client: client.table(PREFERENCES_TABLE).select("*").execute().data or [],
    )
    out = {}
    for row in rows:
        rid = _int(row.get("RoleId"))
        if rid is not None:
            out[rid] = row
    return out


def allowed(role_id, kind: str, prefs: dict | None = None) -> bool:
    """Does this role want notifications of this kind?"""
    column = KIND_PREFERENCE.get(kind)
    if column is None:
        return True
    rid = _int(role_id)
    if rid is None:
        return True
    if prefs is None:
        try:
            prefs = _preferences()
        except DatabaseError as error:
            logger.warning("Notification preferences unavailable (%s); sending anyway.", error)
            return True
    row = prefs.get(rid)
    if not row:
        return True
    value = row.get(column)
    return True if value is None else bool(value)


# =========================================================
# CREATE (best effort)
# =========================================================


def _insert(user_ids: Iterable[int], text: str) -> int:
    rows = [
        {"UserId": uid, "Message": text, "IsRead": False}
        for uid in dict.fromkeys(u for u in user_ids if u is not None)
    ]
    if not rows:
        return 0
    _run(
        "creating notifications",
        lambda client: client.table(NOTIFICATIONS_TABLE).insert(rows).execute(),
    )
    return len(rows)


def notify_user(user_id, kind: str, text: str) -> int:
    """Notify one user (e.g. the teacher who sent a report), if their role
    allows this kind. Returns how many notifications were created."""
    try:
        uid = _int(user_id)
        if uid is None or not text:
            return 0
        row = users.get_user_by_id(uid)
        if not row or str(row.get("Status") or "").strip().lower() not in ("active", "approved"):
            return 0
        if not allowed(row.get("RoleId"), kind):
            return 0
        return _insert([uid], text)
    except Exception as exc:  # never break the action that triggered it
        logger.warning("Could not notify user %s: %s", user_id, exc)
        return 0


def notify_role(role_names, kind: str, text: str, exclude_user_id=None) -> int:
    """Notify every active user of a role (role_names: one name or several
    spellings), if that role allows this kind."""
    if isinstance(role_names, str):
        role_names = (role_names,)
    try:
        if not text:
            return 0
        prefs = None
        try:
            prefs = _preferences()
        except DatabaseError as error:
            logger.warning("Notification preferences unavailable (%s); sending anyway.", error)
            prefs = {}
        skip = _int(exclude_user_id)
        recipients: list[int] = []
        for name in role_names:
            role_id = users.role_id_for(name)
            if role_id is None or not allowed(role_id, kind, prefs):
                continue
            for row in users.list_users(status="active", role=name, limit=1000):
                uid = _int(row.get("UserId"))
                if uid is not None and uid != skip:
                    recipients.append(uid)
        return _insert(recipients, text)
    except Exception as exc:
        logger.warning("Could not notify role %s: %s", role_names, exc)
        return 0


def notify_admins(kind: str, text: str, exclude_user_id=None) -> int:
    return notify_role(ADMIN_ROLE_NAMES, kind, text, exclude_user_id)


def notify_technicians(kind: str, text: str, exclude_user_id=None) -> int:
    return notify_role(TECHNICIAN_ROLE, kind, text, exclude_user_id)


# =========================================================
# READ / MARK AS READ
# =========================================================


def list_for_user(user_id, limit: int = LIST_LIMIT) -> list[dict]:
    """The user's own notifications, newest first."""
    uid = _int(user_id)
    if uid is None:
        return []
    limit = max(1, min(int(limit or LIST_LIMIT), 200))

    rows = _run(
        "reading notifications",
        lambda client: (
            client.table(NOTIFICATIONS_TABLE)
            .select("NotificationId, Message, IsRead, CreatedAt")
            .eq("UserId", uid)
            .order("CreatedAt", desc=True)
            .limit(limit)
            .execute()
            .data
            or []
        ),
    )

    out = []
    for row in rows:
        text = str(row.get("Message") or "")
        title, _, details = text.partition(" — ")
        code = re.search(r"\bCL-\d+\b", text)
        out.append(
            {
                "id": row.get("NotificationId"),
                "message": text,
                "title": title.strip(),
                "details": details.strip(),
                "report_code": code.group(0) if code else None,
                "read": bool(row.get("IsRead")),
                "created_at": row.get("CreatedAt"),
            }
        )
    return out


def mark_read(user_id, ids=None) -> int:
    """Mark the user's notifications as read (all of them when ids is None).
    Only the user's own rows are ever changed."""
    uid = _int(user_id)
    if uid is None:
        return 0
    wanted = None
    if ids is not None:
        wanted = [n for n in (_int(i) for i in ids) if n is not None]
        if not wanted:
            return 0

    def update(client):
        query = (
            client.table(NOTIFICATIONS_TABLE)
            .update({"IsRead": True, "UpdatedAt": _now()})
            .eq("UserId", uid)
            .eq("IsRead", False)
        )
        if wanted is not None:
            query = query.in_("NotificationId", wanted)
        return query.execute().data or []

    return len(_run("marking notifications as read", update))


__all__ = [
    "allowed",
    "list_for_user",
    "mark_read",
    "message",
    "notify_admins",
    "notify_role",
    "notify_technicians",
    "notify_user",
    "report_code",
]