"""
Centrum Laboratory - Admin business logic.

Everything the Admin dashboard needs from the backend lives here.

Architecture
------------
The Admin service does NOT access Supabase directly.

It reuses the existing backend services/repositories:

    auth_service.py
        - identifies the authenticated user
        - validates Admin access
        - manages Admin/user account operations
        - password changes

    technician_service.py
        - shared laboratory/dashboard data
        - existing computer/report-related operations
        - contact-number update

    users_repository.py
        - shared Users database access through auth_service
        - DatabaseError

The frontend must never perform Admin database operations directly.

IMPORTANT
---------
The shared Supabase PostgreSQL database remains the source of truth.

This service must NOT create another local source of truth.
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

ADMIN_ROLES = (
    "admin",
    "administrator",
)

REQUEST_ROLES = (
    "teacher",
    "technician",
)


# Users.Status -> User Requests display status
REQUEST_STATUS = {
    "pending": "pending",
    "active": "approved",
    "approved": "approved",
    "rejected": "cancelled",
}


# Admin user-request decisions -> Users.Status
DECISIONS = {
    "approve": "active",
    "cancel": "rejected",
}


# Admin escalation decisions
ESCALATION_DECISIONS = (
    "approve",
    "resolve",
    "send_back",
)


# =========================================================
# ACCESS CHECK
# =========================================================

def is_admin(user: dict | None) -> bool:
    """
    Return True when the authenticated user's role is Admin.

    The role must come from the backend-authenticated user record.
    The frontend must not be trusted to supply the role.
    """

    role = str(
        (user or {}).get("role") or ""
    ).strip().lower()

    return role in ADMIN_ROLES


def current_admin(access_token: str) -> dict:
    """
    Resolve and validate the authenticated Admin.

    Returns the authenticated user when valid.
    """

    if not access_token:
        return {
            "success": False,
            "error": "Authentication token is required.",
            "status_code": 401,
        }

    result = auth_service.user_from_token(access_token)

    if not result.get("success"):
        return {
            **result,
            "status_code": 401,
        }

    user = result.get("user") or {}

    if not is_admin(user):
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
    """
    Build a display name from the authenticated Users data.
    """

    name = (
        f"{user.get('first_name') or ''} "
        f"{user.get('last_name') or ''}"
    ).strip()

    return (
        name
        or (user.get("email") or "").split("@")[0]
        or "User"
    )


def _request_from_user(user: dict) -> dict | None:
    """
    Convert a Users/auth_service user record into the User Requests
    structure consumed by the Admin frontend.

    Only Teacher and Technician accounts are included.
    """

    role = str(
        user.get("role") or ""
    ).strip().lower()

    status = REQUEST_STATUS.get(
        str(
            user.get("status") or ""
        ).strip().lower()
    )

    if (
        role not in REQUEST_ROLES
        or not status
        or user.get("user_id") in (None, "")
    ):
        return None

    return {
        "id": str(user["user_id"]),
        "full_name": _full_name(user),
        "role": role,
        "email": user.get("email") or "",
        "contact": user.get("contact_number") or "",
        "department": user.get("department") or "",
        "submitted_at": user.get("created_at"),
        # Users."DateConfirmed" (nullable) - passed through unchanged.
        "date_confirmed": user.get("date_confirmed"),
        "status": status,
    }


# =========================================================
# NORMALIZE LAB DATA
# =========================================================

def _normalize_lab_data(lab: dict | None) -> dict:
    """
    Normalize the dashboard data returned by technician_service.

    IMPORTANT (root cause of the "0 out of 0 computers" bug):
    ------------------------------------------------------------
    technician_service.get_dashboard_data() NEVER returns a "computers"
    key. It returns:

        {"success": True, "units": [...], "reports": [...]}

    The real computer records live under "units".

    An earlier version of this function always defaulted a missing
    "computers" key to an empty list `[]` *before* checking whether the
    key was even present:

        computers = normalized.get("computers")   # -> None (key absent)
        if computers is None:
            computers = normalized.get("Computers")  # -> None
        if computers is None:
            computers = []                            # <-- always hits this
        normalized["computers"] = computers           # -> []

    Then `_get_computers_from_lab()` did:

        computers = lab.get("computers")
        if isinstance(computers, list):   # [] IS a list -> True!
            return computers              # returns [] and NEVER falls
                                           # through to check lab["units"]

    Because `isinstance([], list)` is True, the empty placeholder was
    indistinguishable from "genuinely zero computers", so the real data
    in `units` was always shadowed. That is why the Admin dashboard
    showed "0 out of 0 computers" even though real rows exist in the
    `Computers` table.

    Fix: resolve "units" and "reports" FIRST (these hold the real data
    from technician_service), and only derive "computers" from "units"
    when the "computers" key is genuinely absent from the source dict
    -- not merely falsy/empty -- so an explicitly-returned empty list
    is still respected as a legitimate "zero computers" answer.
    """

    if not isinstance(lab, dict):
        return {
            "computers": [],
            "units": [],
            "reports": [],
        }

    normalized = dict(lab)

    # -----------------------------------------------------
    # Resolve units FIRST -- this is where technician_service
    # actually puts the real computer records.
    # -----------------------------------------------------

    units = normalized.get("units")

    if units is None:
        units = normalized.get("Units")

    if units is None:
        units = []

    normalized["units"] = units

    # -----------------------------------------------------
    # Resolve reports.
    # -----------------------------------------------------

    reports = normalized.get("reports")

    if reports is None:
        reports = normalized.get("Reports")

    if reports is None:
        reports = []

    normalized["reports"] = reports

    # -----------------------------------------------------
    # Resolve computers.
    #
    # Only fall back to the empty-list default when the key is
    # genuinely ABSENT (checked with "in", not ".get() is None"),
    # so a dict that legitimately includes "computers": [] is not
    # confused with one that never had the key at all. When the key
    # truly is absent, fall back to the real "units" list rather than
    # an empty placeholder -- this is the actual fix.
    # -----------------------------------------------------

    if "computers" in normalized and normalized["computers"] is not None:
        computers = normalized["computers"]
    elif "Computers" in normalized and normalized["Computers"] is not None:
        computers = normalized["Computers"]
    else:
        computers = units  # real data, not []
    
    # -----------------------------------------------------
    # Normalize operating-system fields.
    #
    # Supports:
    #   operating_system
    #   system["operating_system"]
    #   OperatingSystem
    # -----------------------------------------------------

    for computer in computers:
        if not isinstance(computer, dict):
            continue

        system = computer.get("system")

        if not isinstance(system, dict):
            system = {}

        operating_system = (
            computer.get("operating_system")
            or system.get("operating_system")
            or computer.get("OperatingSystem")
            or ""
        )

        operating_system = str(operating_system).strip()

        # Standard field for frontend display.
        computer["operating_system"] = operating_system

        # Preserve the nested structure if the frontend uses it.
        system["operating_system"] = operating_system
        computer["system"] = system

    # Save the normalized computer records.
    normalized["computers"] = computers

    return normalized


def _get_computers_from_lab(lab: dict | None) -> list:
    """
    Return the computer records from normalized lab data.

    After _normalize_lab_data() runs, lab["computers"] is already
    correctly resolved (falling back to the real "units" data when no
    "computers" key was ever supplied). This function just reads it,
    with a defensive fallback to "units" in case it is ever called on
    a dict that was not normalized first.
    """

    if not isinstance(lab, dict):
        return []

    computers = lab.get("computers")

    if isinstance(computers, list):
        return computers

    units = lab.get("units")

    if isinstance(units, list):
        return units

    return []


# =========================================================
# DASHBOARD DATA
# =========================================================

def get_dashboard_data() -> dict:
    """
    Load all shared Admin dashboard data.

    Data sources:

        lab
            -> technician_service.get_dashboard_data()

        requests
            -> auth_service.admin_list_users()

    IMPORTANT:
    ----------
    This function does not directly access Supabase.

    It also DOES NOT discard fields returned by
    technician_service.get_dashboard_data().
    """

    problems: list[str] = []

    # =====================================================
    # SHARED LABORATORY DATA
    # =====================================================

    try:
        raw_lab = technician_service.get_dashboard_data()

        lab = _normalize_lab_data(raw_lab)

        computers = _get_computers_from_lab(lab)

        # Ensure the computer records retain the operating system
        # fetched from the Computers table by technician_service.
        for computer in computers:
            if not isinstance(computer, dict):
                continue

            system = computer.get("system")
            if not isinstance(system, dict):
                system = {}

            operating_system = (
                computer.get("operating_system")
                or system.get("operating_system")
                or computer.get("OperatingSystem")
                or ""
            )

            computer["operating_system"] = operating_system
            system["operating_system"] = operating_system
            computer["system"] = system

        logger.info(
            "Admin dashboard laboratory data loaded: "
            "computers=%d, units=%d, reports=%d",
            len(computers),
            len(lab.get("units") or []),
            len(lab.get("reports") or []),
        )

    except DatabaseError as error:
        logger.exception(
            "Unable to load Admin laboratory data."
        )

        lab = {
            "computers": [],
            "units": [],
            "reports": [],
        }

        problems.append(
            f"Lab data: {error}"
        )

    except Exception as error:
        logger.exception(
            "Unexpected Admin laboratory-data error."
        )

        lab = {
            "computers": [],
            "units": [],
            "reports": [],
        }

        problems.append(
            f"Lab data: {error}"
        )

    # =====================================================
    # USER REQUESTS
    # =====================================================

    try:
        listed = auth_service.admin_list_users()

        users = []

        if isinstance(listed, dict):
            users = listed.get("users") or []

        requests = [
            record
            for record in (
                _request_from_user(user)
                for user in users
                if isinstance(user, dict)
            )
            if record
        ]

    except DatabaseError as error:
        logger.exception(
            "Unable to load Admin user requests."
        )

        requests = None

        problems.append(
            f"User requests: {error}"
        )

    except Exception as error:
        logger.exception(
            "Unexpected Admin user-request error."
        )

        requests = None

        problems.append(
            f"User requests: {error}"
        )

    # =====================================================
    # RESPONSE
    # =====================================================

    return {
        "success": True,

        "lab": lab,

        "requests": requests,

        "problems": problems,

        # -------------------------------------------------
        # Convenience field for Admin frontend.
        #
        # This prevents the frontend from having to guess
        # whether computers are under "computers" or "units".
        # -------------------------------------------------

        "computers": _get_computers_from_lab(lab),
    }


# =========================================================
# USER REQUESTS
# =========================================================

def decide_user_request(
    user_id,
    decision: str,
    reason: str = "",
) -> dict:
    """
    Confirm or cancel a pending Teacher/Technician account request.

    approve:
        Users.Status -> active

    cancel:
        Users.Status -> rejected
    """

    decision = (
        decision or ""
    ).strip().lower()

    if decision not in DECISIONS:
        return {
            "success": False,
            "error": "Invalid decision.",
        }

    if user_id in (None, ""):
        return {
            "success": False,
            "error": "Invalid user.",
        }

    # =====================================================
    # GET CURRENT USER
    # =====================================================

    found = auth_service.admin_get_user(user_id)

    if not found.get("success"):
        return {
            "success": False,
            "error": "That user no longer exists.",
        }

    user = found.get("user") or {}

    request = _request_from_user(user)

    if request is None:
        return {
            "success": False,
            "error": (
                "Only Teacher and Technician requests "
                "can be changed here."
            ),
        }

    # =====================================================
    # PREVENT DOUBLE DECISIONS
    # =====================================================

    if request["status"] != "pending":
        return {
            "success": False,
            "error": "This request was already decided.",
        }

    # =====================================================
    # UPDATE USERS.STATUS
    # =====================================================

    result = auth_service.admin_set_status(
        user_id,
        DECISIONS[decision],
    )

    if not result.get("success"):
        return result

    name = request["full_name"]

    # =====================================================
    # CANCELLATION REASON
    # =====================================================

    if decision == "cancel":

        reason = (
            reason or ""
        ).strip()

        if reason:
            logger.info(
                "Request for user %s cancelled. Reason: %s",
                user_id,
                reason[:500],
            )

        message = (
            f"{name}'s request was cancelled"
        )

    else:

        message = (
            f"{name} confirmed — they can log in now"
        )

    updated_user = result.get("user") or {}

    return {
        "success": True,
        "message": message,
        "request": _request_from_user(updated_user),
    }


# =========================================================
# ADMIN ESCALATION
# =========================================================

def decide_escalation(
    admin: dict,
    report_id,
    decision: str,
) -> dict:
    """
    Process an Admin decision for an escalated report.

    Decisions:

        approve
            -> Under inspection

        resolve
            -> Cleared

        send_back
            -> Pending review
    """

    # =====================================================
    # VALIDATE ADMIN
    # =====================================================

    if not is_admin(admin):
        return {
            "success": False,
            "error": "Administrator access is required.",
        }

    # =====================================================
    # VALIDATE REPORT
    # =====================================================

    if report_id in (None, ""):
        return {
            "success": False,
            "error": "Invalid report.",
        }

    # =====================================================
    # VALIDATE DECISION
    # =====================================================

    decision = (
        decision or ""
    ).strip().lower()

    if decision not in ESCALATION_DECISIONS:
        return {
            "success": False,
            "error": (
                "Invalid escalation decision. "
                "Expected approve, resolve, or send_back."
            ),
        }

    # =====================================================
    # LOAD SHARED LAB DATA
    # =====================================================

    try:
        lab = _normalize_lab_data(
            technician_service.get_dashboard_data()
        )

    except DatabaseError as error:
        logger.exception(
            "Unable to load report %s for Admin escalation.",
            report_id,
        )

        return {
            "success": False,
            "error": f"Unable to load the report: {error}",
        }

    except Exception:
        logger.exception(
            "Unexpected error loading report %s.",
            report_id,
        )

        return {
            "success": False,
            "error": "Unable to load the report.",
        }

    reports = lab.get("reports") or []

    # =====================================================
    # LOCATE REPORT
    # =====================================================

    report = None

    target_id = str(report_id)

    for item in reports:

        if not isinstance(item, dict):
            continue

        item_id = item.get("report_id")

        if item_id is None:
            item_id = item.get("ReportId")

        if item_id is None:
            item_id = item.get("id")

        if item_id is None:
            continue

        if str(item_id) == target_id:
            report = item
            break

    if report is None:
        return {
            "success": False,
            "error": "That report no longer exists.",
        }

    # =====================================================
    # EXTRACT COMPUTER INFORMATION
    # =====================================================

    computer_id = report.get("computer_id")

    if computer_id is None:
        computer_id = report.get("ComputerId")

    room = (
        report.get("room")
        or report.get("Room")
        or ""
    )

    unit_number = report.get("unit_number")

    if unit_number is None:
        unit_number = report.get("UnitNumber")

    # =====================================================
    # RESOLVE ESCALATION STATUS
    # =====================================================

    if decision == "approve":

        escalation_status = "Under inspection"

    elif decision == "resolve":

        escalation_status = "Cleared"

    else:

        escalation_status = "Pending review"

    # =====================================================
    # GET ESCALATION SETTER
    # =====================================================

    setter = getattr(
        technician_service,
        "set_escalation_status",
        None,
    )

    if not callable(setter):

        logger.error(
            "technician_service.set_escalation_status "
            "is not available."
        )

        return {
            "success": False,
            "error": (
                "The backend escalation operation "
                "is not available yet."
            ),
        }

    # =====================================================
    # UPDATE SHARED DATABASE
    # =====================================================

    try:

        result = setter(
            room=room,
            unit_number=unit_number,
            status=escalation_status,
            computer_id=computer_id,
        )

    except TypeError:

        # Compatibility with positional implementations.
        try:

            result = setter(
                room,
                unit_number,
                escalation_status,
                computer_id,
            )

        except Exception:

            logger.exception(
                "Unable to update escalation for report %s.",
                report_id,
            )

            return {
                "success": False,
                "error": "Unable to update the escalation.",
            }

    except Exception:

        logger.exception(
            "Unable to update escalation for report %s.",
            report_id,
        )

        return {
            "success": False,
            "error": "Unable to update the escalation.",
        }

    if not result or not result.get("success", False):

        return result or {
            "success": False,
            "error": "Unable to update the escalation.",
        }

    # =====================================================
    # RESPONSE
    # =====================================================

    messages = {
        "approve": (
            "The escalation was approved and is now "
            "under inspection."
        ),

        "resolve": (
            "The escalation was resolved."
        ),

        "send_back": (
            "The escalation was sent back for review."
        ),
    }

    return {
        "success": True,
        "message": messages[decision],
        "report_id": report_id,
        "decision": decision,
        "escalation_status": escalation_status,
        "report": report,
    }


# =========================================================
# PROFILE / PASSWORD
# =========================================================

def update_contact_number(
    admin: dict,
    contact_number: str,
) -> dict:
    """
    Update the authenticated Admin's contact number.

    The built-in fixed Admin account has no Users profile row,
    so its contact number cannot be saved using the normal
    Users update flow.
    """

    if auth_service._is_fixed_admin(
        admin.get("email") or ""
    ):
        return {
            "success": False,
            "error": (
                "The built-in admin account has no user profile, "
                "so its number can't be saved."
            ),
        }

    return technician_service.update_contact_number(
        admin,
        contact_number,
    )


def change_password(
    admin: dict,
    current_password: str,
    new_password: str,
) -> dict:
    """
    Change the authenticated Admin's password.

    Password handling remains inside auth_service.
    """

    return auth_service.change_password(
        email=admin.get("email") or "",
        current_password=current_password,
        new_password=new_password,
    )


def change_email(
    admin: dict,
    new_email: str,
    current_password: str,
) -> dict:
    """
    Change the authenticated Admin's own email (login + Users.Email).

    The current password is required.
    """

    return auth_service.change_own_email(
        email=admin.get("email") or "",
        current_password=current_password,
        new_email=new_email,
    )


# =========================================================
# PUBLIC API
# =========================================================

__all__ = [
    "change_email",
    "change_password",
    "current_admin",
    "decide_escalation",
    "decide_user_request",
    "get_dashboard_data",
    "is_admin",
    "update_contact_number",
]