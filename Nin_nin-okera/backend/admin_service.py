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
from datetime import date

from . import auth_service
from . import notification_service as notify
from . import perf

from . import technician_service
from . import users_repository as users
from .users_repository import DatabaseError, _run

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

    role = str((user or {}).get("role") or "").strip().lower()

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

    name = (f"{user.get('first_name') or ''} " f"{user.get('last_name') or ''}").strip()

    return name or (user.get("email") or "").split("@")[0] or "User"


def _request_from_user(user: dict) -> dict | None:
    """
    Convert a Users/auth_service user record into the User Requests
    structure consumed by the Admin frontend.

    Only Teacher and Technician accounts are included.
    """

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

    # Speed: the user list is read at the same time as the laboratory data
    # (it was read only after the laboratory data had finished).
    users_future = perf.submit(
        lambda: perf.cached("admin_users", 30, auth_service.admin_list_users)
    )
    # =====================================================
    # SHARED LABORATORY DATA
    # =====================================================

    try:
        raw_lab = technician_service.get_dashboard_data()

        # _normalize_lab_data() already fills in operating_system / system
        # for every computer, so it is not repeated here.
        lab = _normalize_lab_data(raw_lab)

        computers = _get_computers_from_lab(lab)

        logger.info(
            "Admin dashboard laboratory data loaded: "
            "computers=%d, units=%d, reports=%d",
            len(computers),
            len(lab.get("units") or []),
            len(lab.get("reports") or []),
        )

    except DatabaseError as error:
        logger.exception("Unable to load Admin laboratory data.")

        lab = {
            "computers": [],
            "units": [],
            "reports": [],
        }

        problems.append(f"Lab data: {error}")

    except Exception as error:
        logger.exception("Unexpected Admin laboratory-data error.")

        lab = {
            "computers": [],
            "units": [],
            "reports": [],
        }

        problems.append(f"Lab data: {error}")

    # =====================================================
    # USER REQUESTS
    # =====================================================

    try:
        listed = users_future.result()

        users = []

        if isinstance(listed, dict):
            users = listed.get("users") or []

        requests = [
            record
            for record in (
                _request_from_user(user) for user in users if isinstance(user, dict)
            )
            if record
        ]

    except DatabaseError as error:
        logger.exception("Unable to load Admin user requests.")

        requests = None

        problems.append(f"User requests: {error}")

    except Exception as error:
        logger.exception("Unexpected Admin user-request error.")

        requests = None

        problems.append(f"User requests: {error}")

    # =====================================================
    # RESPONSE
    # =====================================================

    # Speed: the computers used to be sent three times (lab.units,
    # lab.computers - the same list - and a top-level "computers").
    # Only send what the frontend reads.
    payload_lab = {k: v for k, v in lab.items() if k != "computers"}

    return {
        "success": True,
        "lab": payload_lab,
        "requests": requests,
        "problems": problems,
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

    decision = (decision or "").strip().lower()

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

    # Speed: the Users row is read ONCE and handed to update_status (it used
    # to be read here, then again inside the status update).
    try:
        row = users.get_user_by_id(user_id)
    except DatabaseError as error:
        return {"success": False, "error": str(error)}

    if not row:
        return {
            "success": False,
            "error": "That user no longer exists.",
        }

    user = users.to_app_user(row) or {}

    request = _request_from_user(user)

    if request is None:
        return {
            "success": False,
            "error": ("Only Teacher and Technician requests " "can be changed here."),
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

    # Same as auth_service.admin_set_status(), reusing the row read above.
    try:
        updated_row = users.update_status(user_id, DECISIONS[decision], current=row)
    except DatabaseError as error:
        return {"success": False, "error": str(error)}

    if not updated_row:
        return {"success": False, "error": "User not found."}

    result = {"success": True, "user": users.to_app_user(updated_row)}

    name = request["full_name"]

    # =====================================================
    # CANCELLATION REASON
    # =====================================================

    if decision == "cancel":

        reason = (reason or "").strip()

        if reason:
            logger.info(
                "Request for user %s cancelled. Reason: %s",
                user_id,
                reason[:500],
            )

        message = f"{name}'s request was cancelled"

    else:

        message = f"{name} confirmed — they can log in now"

    updated_user = result.get("user") or {}

    return {
        "success": True,
        "message": message,
        "request": _request_from_user(updated_user),
    }


# =========================================================
# ADMIN ESCALATION
# =========================================================


def _has_decisions_table() -> bool:
    """True when the ReportDecisions table exists."""

    try:
        _run(
            "checking ReportDecisions",
            lambda client: client.table(technician_service.REPORT_DECISIONS_TABLE)
            .select("DecisionId")
            .limit(1)
            .execute(),
        )
        return True
    except DatabaseError as error:
        if error.code != "missing_table":
            raise
        return False


def decide_escalation(
    admin: dict,
    report_id,
    decision: str,
) -> dict:
    """
    The Admin's decision on an escalated report.

        approve     replacement approved: the report goes back to the
                    technician as "under repair";
                    Computers.EscalationStatus -> Under inspection
        resolve     closed as fixed;
                    Computers.EscalationStatus -> Cleared
        send_back   back to the technician as "under repair" without a
                    decision ("back" is accepted too);
                    Computers.EscalationStatus -> Pending review

    report_id may be the ReportId (1) or the code the screens show ("CL-0001").
    Saved in Reports (StatusId, UpdatedAt) and Computers (EscalationStatus);
    the teacher who sent the report and the technician are notified.
    """

    if not is_admin(admin):
        return {"success": False, "error": "Administrator access is required."}

    decision = (decision or "").strip().lower()
    decision = {"back": "send_back", "sendback": "send_back"}.get(decision, decision)

    if decision not in ESCALATION_DECISIONS:
        return {
            "success": False,
            "error": "Invalid escalation decision. Expected approve, resolve, or send_back.",
        }

    text = str(report_id or "").strip()
    if text.upper().startswith("CL-"):
        text = text[3:]
    try:
        number = int(text)
    except ValueError:
        return {"success": False, "error": "Invalid report."}

    # ---- the report, as the dashboards see it --------------------------
    # Speed: read only this report (it used to load the whole dashboard -
    # every computer, user, report, hardware and software row).
    try:
        report = technician_service.get_report(number)
    except Exception as error:
        logger.exception(
            "Unable to load report %s for an escalation decision.", report_id
        )
        return {"success": False, "error": f"Unable to load the report: {error}"}

    if report is None:
        return {"success": False, "error": "That report no longer exists."}

    # technician_service shows a technician escalation ("Follow Up") as "Follow Up"
    if "follow" not in str(report.get("status") or "").lower():
        return {
            "success": False,
            "error": "This report is not escalated any more. Refresh the data.",
        }

    # ---- new report status ---------------------------------------------
    wanted = "resolved" if decision == "resolve" else "progress"

    escalation_status = {
        "approve": "Under inspection",
        "resolve": "Cleared",
        "send_back": "Pending review",
    }[decision]

    admin_name = (
        f"{admin.get('first_name') or ''} {admin.get('last_name') or ''}".strip()
        or (admin.get("email") or "Admin").split("@")[0]
    )
    note = {
        "approve": f"Replacement approved by {admin_name}",
        "resolve": f"Marked resolved by {admin_name}",
        "send_back": f"Sent back to the technician by {admin_name}",
    }[decision]

    # Saved here (not through a technician_service helper), so this file
    # works with any version of technician_service.py.
    status_rows = technician_service._status_rows()
    status_id = technician_service._find_status_id(wanted, status_rows)
    if status_id is None:
        return {
            "success": False,
            "error": f"No ReportStatus entry exists for '{wanted}'. Check the ReportStatus table.",
        }

    now = technician_service._now()

    # Is there a ReportDecisions table? Then the decision is saved there (one
    # row per decision) and the technician's note (ResolutionNote) is kept.
    # Without it, the decision goes into ResolutionNote as before.
    try:
        # Kept for a few minutes: whether the table exists doesn't change.
        has_decisions_table = perf.lookup(
            "has_report_decisions_table",
            technician_service.LOOKUP_CACHE_SECONDS,
            _has_decisions_table,
        )
    except DatabaseError as error:
        return {"success": False, "error": str(error)}

    changes = {"StatusId": status_id, "UpdatedAt": now}
    if not has_decisions_table:
        changes["ResolutionNote"] = note
    if decision == "resolve":
        changes["FixedDate"] = now  # when it was fixed

    def save(values):
        def update(client):
            response = (
                client.table(technician_service.REPORTS_TABLE)
                .update(values)
                .eq("ReportId", number)
                .execute()
            )
            return response.data[0] if response.data else None

        return _run("saving the admin decision", update)

    attempts = [changes, {k: v for k, v in changes.items() if k != "FixedDate"}]

    row = None
    for i, values in enumerate(attempts):
        try:
            row = save(values)
            break
        except DatabaseError as error:
            if error.code != "missing_column" or i == len(attempts) - 1:
                return {"success": False, "error": str(error)}

    if not row:
        return {"success": False, "error": "That report no longer exists."}

    # ---- the decision itself (ReportDecisions) -------------------------
    if has_decisions_table:
        decided_by = admin.get("user_id")
        try:
            decided_by = int(decided_by)
        except (TypeError, ValueError):
            decided_by = None
        try:
            _run(
                "saving the decision",
                lambda client: client.table(technician_service.REPORT_DECISIONS_TABLE)
                .insert(
                    {
                        "ReportId": number,
                        "Decision": decision,
                        "Note": note,
                        "DecidedBy": decided_by,
                        "DecidedAt": now,
                    }
                )
                .execute(),
            )
        except DatabaseError:
            # The report is already updated; keep the decision in its note.
            logger.exception(
                "Decision on report %s not saved in ReportDecisions.", report_id
            )
            try:
                save({"ResolutionNote": note})
            except DatabaseError:
                pass

    # ---- the computer's escalation status (best effort) ----------------
    # Speed: one UPDATE by ComputerId. technician_service.set_escalation_status()
    # also re-read the computer's hardware and software afterwards (two more
    # round trips) to build a result this function never used.
    try:
        computer_id = report.get("computer_id")
        if computer_id is not None:
            _run(
                "updating escalation status",
                lambda client: client.table(technician_service.COMPUTERS_TABLE)
                .update({"EscalationStatus": escalation_status, "UpdatedAt": now})
                .eq("ComputerId", computer_id)
                .execute(),
            )
        else:
            technician_service.set_escalation_status(
                report.get("room"), report.get("unit_number"), escalation_status
            )
    except Exception:
        logger.exception(
            "Escalation status of report %s's computer not updated.", report_id
        )

    # ---- notifications (best effort; preferences decide) ---------------
    code = report.get("code") or f"CL-{number:04d}"
    where = f"{report.get('room') or 'Laboratory'} PC {int(report.get('unit_number') or 0):02d}"
    label = {
        "approve": "replacement approved",
        "resolve": "fixed",
        "send_back": "sent back",
    }[decision]
    details = f"{code} · {report.get('issue') or 'Report'} · {note}"
    # Sent after the response, so the admin doesn't wait for them.
    perf.background(
        notify.notify_user,
        row.get("ReportedBy"),
        "report_update",
        notify.message(
            f"Your report is {'fixed' if decision == 'resolve' else 'under repair'} · {where}",
            details,
        ),
    )
    if row.get("HandledBy") is not None:
        perf.background(
            notify.notify_user,
            row.get("HandledBy"),
            "escalation",
            notify.message(f"Escalation {label} · {where}", details),
        )

    messages = {
        "approve": f"{code} approved and returned to the technician.",
        "resolve": f"{code} marked as resolved.",
        "send_back": f"{code} sent back to the technician.",
    }

    return {
        "success": True,
        "message": messages[decision],
        "report_id": number,
        "decision": decision,
        "escalation_status": escalation_status,
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

    if auth_service._is_fixed_admin(admin.get("email") or ""):
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
# ADD LABORATORY (Computers table)
# =========================================================
#
#   public."Computers"
#       ComputerId        identity         (never sent)
#       Room              text NOT NULL    the laboratory's room
#       UnitNumber        int  NOT NULL    > 0
#       Status            computer_status  DEFAULT 'Working'        (not sent)
#       EscalationStatus  text             DEFAULT 'Pending review' (not sent)
#       CreatedAt / UpdatedAt              DEFAULT CURRENT_TIMESTAMP (not sent)
#       DateAdded         date NULL        today
#       UNIQUE ("Room", "UnitNumber")

MAX_LAB_UNITS = 200
MAX_ROOM_LENGTH = 100

_COMPUTER_READ_COLUMNS = (
    "ComputerId,Room,UnitNumber,Status,EscalationStatus,CreatedAt,UpdatedAt,DateAdded"
)


def _clean_room(room) -> str:
    return " ".join(str(room or "").split())


def _lab_rows(room: str) -> list[dict]:
    """The Computers rows of one room, read back from Supabase."""

    def read(client, columns):
        return (
            client.table(technician_service.COMPUTERS_TABLE)
            .select(columns)
            .eq("Room", room)
            .order("UnitNumber")
            .execute()
            .data
            or []
        )

    try:
        return _run(
            "reading the laboratory's computers",
            lambda c: read(c, _COMPUTER_READ_COLUMNS),
        )
    except DatabaseError as error:
        if error.code != "missing_column":
            raise
        return _run(
            "reading the laboratory's computers",
            lambda c: read(
                c,
                "ComputerId,Room,UnitNumber,Status,EscalationStatus,CreatedAt,UpdatedAt",
            ),
        )


def create_laboratory(admin: dict, room, units, hardware: dict | None = None) -> dict:
    """
    Save a new laboratory's computer units to public."Computers":
    one row per unit, Room = the laboratory's room, UnitNumber = 1..units.

    Refused when the room already has computers (case and spacing ignored),
    so no (Room, UnitNumber) pair is ever duplicated. All units are inserted
    in one statement: either every unit is saved or none is.

    Returns the rows as stored in Supabase.
    """

    room = _clean_room(room)

    if not room:
        return {"success": False, "error": "Enter the laboratory's room."}

    if len(room) > MAX_ROOM_LENGTH:
        return {
            "success": False,
            "error": f"Keep the room under {MAX_ROOM_LENGTH} characters.",
        }

    try:
        units = int(units)
    except (TypeError, ValueError):
        return {
            "success": False,
            "error": "The number of computer units must be a whole number.",
        }

    # A laboratory exists in the database through its computers, so it
    # needs at least one unit.
    if not 1 <= units <= MAX_LAB_UNITS:
        return {
            "success": False,
            "error": f"Number of computer units: 1 to {MAX_LAB_UNITS}.",
        }

    # Duplicate check against what is actually in the database.
    try:
        existing = technician_service._select_all(
            technician_service.COMPUTERS_TABLE,
            "ComputerId,Room,UnitNumber",
            "ComputerId",
        )
    except DatabaseError as error:
        return {"success": False, "error": str(error)}

    key = room.lower()
    taken = [row for row in existing if _clean_room(row.get("Room")).lower() == key]

    if taken:
        return {
            "success": False,
            "code": "duplicate",
            "error": (
                f'The room "{_clean_room(taken[0].get("Room"))}" already has '
                f"{len(taken)} computer unit(s) in the database. "
                "Use another room for the new laboratory."
            ),
        }

    today = date.today().isoformat()  # DateAdded: the server's local date

    rows = [
        {"Room": room, "UnitNumber": number, "DateAdded": today}
        for number in range(1, units + 1)
    ]

    def insert(values):
        return _run(
            "adding the laboratory's computers",
            lambda client: client.table(technician_service.COMPUTERS_TABLE)
            .insert(values)
            .execute(),
        )

    try:
        try:
            insert(rows)
        except DatabaseError as error:
            if error.code != "missing_column":
                raise
            insert([{k: v for k, v in r.items() if k != "DateAdded"} for r in rows])
    except DatabaseError as error:
        if error.code == "duplicate":
            return {
                "success": False,
                "code": "duplicate",
                "error": (
                    f'Computers for room "{room}" already exist in the database '
                    "(each Room and UnitNumber must be unique). Refresh and use "
                    "another room."
                ),
            }
        return {"success": False, "error": str(error)}

    try:
        saved = _lab_rows(room)
    except DatabaseError as error:
        saved = None
        read_error = error
    else:
        read_error = None

    # The hardware specs picked on the form, for every new unit.
    hw_failed = 0
    if (
        saved
        and isinstance(hardware, dict)
        and any(str(v or "").strip() for v in hardware.values())
    ):
        from . import inventory_service

        # Speed: the specs are saved for all units at the same time (one
        # after another, a 40-unit laboratory took 40 round trips).
        futures = [
            (
                row.get("ComputerId"),
                perf.submit(
                    inventory_service._save_hardware, row.get("ComputerId"), hardware
                ),
            )
            for row in saved
        ]
        for computer_id, future in futures:
            try:
                future.result()
            except DatabaseError as error:
                hw_failed += 1
                logger.warning(
                    "Hardware not saved for computer %s: %s", computer_id, error
                )

    if read_error is not None:
        error = read_error
        return {
            "success": True,
            "room": room,
            "computers": [],
            "message": f"{units} computer unit(s) saved, but they could not be read back: {error}",
        }

    logger.info(
        "Laboratory %r added by %s: %d computer unit(s).",
        room,
        admin.get("email") or admin.get("name") or "admin",
        len(saved),
    )

    return {
        "success": True,
        "room": room,
        "computers": [
            {
                "id": row.get("ComputerId"),
                "room": row.get("Room"),
                "unit_number": row.get("UnitNumber"),
                "status": row.get("Status"),
                "escalation_status": row.get("EscalationStatus"),
                "created_at": row.get("CreatedAt"),
                "date_added": row.get("DateAdded"),
            }
            for row in saved
        ],
        "message": f"{len(saved)} computer unit(s) saved."
        + (
            f" The hardware specs could not be saved for {hw_failed} of them."
            if hw_failed
            else ""
        ),
    }


# =========================================================
# PUBLIC API
# =========================================================

__all__ = [
    "change_email",
    "change_password",
    "create_laboratory",
    "current_admin",
    "decide_escalation",
    "decide_user_request",
    "get_dashboard_data",
    "is_admin",
    "update_contact_number",
]
