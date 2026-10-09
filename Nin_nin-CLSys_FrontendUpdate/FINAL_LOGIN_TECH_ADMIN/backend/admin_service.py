"""
Centrum Laboratory - Admin business logic.

Everything the Admin dashboard needs from the backend lives here. It adds no
new database code of its own; it reuses the existing services:

    auth_service.py        who is logged in (user_from_token), the existing
                           admin user functions (admin_list_users,
                           admin_get_user, admin_set_status), password change
    users_repository.py    Users table (through auth_service), DatabaseError
    technician_service.py  the shared lab data (Computers + Reports tables)
                           and the contact number update
    database.py            the shared Supabase client (used by the modules above)

No credentials are read here; database.py loads them from the root .env.

User Requests (Admin > User Requests tab)
-----------------------------------------
A request is a Teacher/Technician row in the Users table:

    Users.Status   pending            -> "Pending"     (can be confirmed / cancelled)
                   active / approved  -> "Confirmed"   (can log in)
                   rejected           -> "Cancelled"   (login is refused)

Confirming sets Status to "active", cancelling sets it to "rejected"
(auth_service.admin_set_status). Other statuses (e.g. "inactive") are not
shown on this tab.
"""

from __future__ import annotations

import logging

from . import auth_service
from . import technician_service
from .users_repository import DatabaseError

logger = logging.getLogger("centrum.admin")


# =========================================================
# SETTINGS
# =========================================================

ADMIN_ROLES = ("admin", "administrator")

REQUEST_ROLES = ("teacher", "technician")

# Users.Status (lower-case) -> User Requests tab
REQUEST_STATUS = {
    "pending": "pending",
    "active": "approved",
    "approved": "approved",
    "rejected": "cancelled",
}

DECISIONS = {
    "approve": "active",
    "cancel": "rejected",
}


# =========================================================
# ACCESS CHECK
# =========================================================


def is_admin(user: dict | None) -> bool:
    """True if the user's role (from auth_service / Users.RoleId) is Admin."""

    role = str((user or {}).get("role") or "").strip().lower()

    return role in ADMIN_ROLES


def current_admin(access_token: str) -> dict:
    """Who is calling? Uses the existing login (auth_service.user_from_token).

    Works for the fixed admin account (ADMIN_EMAIL in .env) too.
    Returns {"success": True, "user": {...}} or {"success": False, "error": ...,
    "status_code": 401 | 403}.
    """

    result = auth_service.user_from_token(access_token)

    if not result.get("success"):

        return {**result, "status_code": 401}

    if not is_admin(result["user"]):

        return {
            "success": False,
            "error": "This page is for administrators only.",
            "status_code": 403,
        }

    return result


# =========================================================
# HELPERS
# =========================================================


def _full_name(user: dict) -> str:

    name = f"{user.get('first_name') or ''} {user.get('last_name') or ''}".strip()

    return name or (user.get("email") or "").split("@")[0] or "User"


def _request_from_user(user: dict) -> dict | None:
    """A Users row (auth_service format) as a User Requests record, or None."""

    role = str(user.get("role") or "").strip().lower()
    status = REQUEST_STATUS.get(str(user.get("status") or "").strip().lower())

    if role not in REQUEST_ROLES or not status or user.get("user_id") in (None, ""):
        return None

    return {
        "id": str(user["user_id"]),
        "full_name": _full_name(user),
        "role": role,
        "email": user.get("email") or "",
        "contact": user.get("contact_number") or "",
        "department": user.get("department") or "",
        "submitted_at": user.get("created_at"),
        "status": status,
    }


# =========================================================
# DASHBOARD DATA
# =========================================================


def get_dashboard_data() -> dict:
    """Lab data (computers + reports) and user requests for the Admin dashboard.

    Each part is loaded on its own, so a problem with one (for example the
    Reports table not being created yet) doesn't hide the other. Problems are
    listed in "problems"; the missing part is None.
    """

    problems = []

    # Lab data: the same read the Technician dashboard uses.
    try:
        lab = technician_service.get_dashboard_data()
        lab = {"units": lab.get("units") or [], "reports": lab.get("reports") or []}

    except DatabaseError as error:
        lab = None
        problems.append(f"Lab data: {error}")

    # User requests: the existing admin user list.
    try:
        listed = auth_service.admin_list_users()
        requests = [
            record
            for record in (_request_from_user(u) for u in listed.get("users") or [])
            if record
        ]

    except DatabaseError as error:
        requests = None
        problems.append(f"User requests: {error}")

    return {"success": True, "lab": lab, "requests": requests, "problems": problems}


# =========================================================
# USER REQUESTS
# =========================================================


def decide_user_request(user_id, decision: str, reason: str = "") -> dict:
    """Confirm (Status -> active) or cancel (Status -> rejected) a pending request.

    The cancel reason is only logged: the Users table has no column for it.
    """

    decision = (decision or "").strip().lower()

    if decision not in DECISIONS:

        return {"success": False, "error": "Invalid decision."}

    if user_id in (None, ""):

        return {"success": False, "error": "Invalid user."}

    found = auth_service.admin_get_user(user_id)

    if not found.get("success"):

        return {"success": False, "error": "That user no longer exists."}

    request = _request_from_user(found["user"])

    if request is None:

        return {
            "success": False,
            "error": "Only Teacher and Technician requests can be changed here.",
        }

    if request["status"] != "pending":

        return {"success": False, "error": "This request was already decided."}

    result = auth_service.admin_set_status(user_id, DECISIONS[decision])

    if not result.get("success"):

        return result

    name = request["full_name"]

    if decision == "cancel":

        reason = (reason or "").strip()

        if reason:
            logger.info(
                "Request for user %s cancelled. Reason: %s", user_id, reason[:500]
            )

        message = f"{name}'s request was cancelled"

    else:

        message = f"{name} confirmed \u2014 they can log in now"

    return {
        "success": True,
        "message": message,
        "request": _request_from_user(result["user"]),
    }


# =========================================================
# PROFILE / PASSWORD  (reuse technician_service and auth_service)
# =========================================================


def update_contact_number(admin: dict, contact_number: str) -> dict:

    if auth_service._is_fixed_admin(admin.get("email") or ""):

        return {
            "success": False,
            "error": (
                "The built-in admin account has no user profile, "
                "so its number can't be saved."
            ),
        }

    # Same validation and Users update the Technician settings use.
    return technician_service.update_contact_number(admin, contact_number)


def change_password(admin: dict, current_password: str, new_password: str) -> dict:

    return auth_service.change_password(
        email=admin.get("email") or "",
        current_password=current_password,
        new_password=new_password,
    )


__all__ = [
    "change_password",
    "current_admin",
    "decide_user_request",
    "get_dashboard_data",
    "is_admin",
    "update_contact_number",
]
