from __future__ import annotations

import logging
import os
import time
from urllib.parse import quote
import threading

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger("centrum.client")


# =========================================================
# SHARED HTTP SESSION (speed)
# =========================================================
#
# requests.get()/requests.request() open a brand-new TCP connection for
# every call. One Session keeps connections to the backend open
# (keep-alive) and reuses them, so each request skips the connection
# setup. This is shared by every dashboard and every Streamlit user of
# this server process; a Session is safe to use from several threads for
# plain requests like these.
#
# Only GET requests are retried (once, on a dropped connection), so a
# POST/PATCH is never sent twice.

_POOL_SIZE = 20


def _make_session() -> requests.Session:
    session = requests.Session()
    adapter = HTTPAdapter(
        pool_connections=4,
        pool_maxsize=_POOL_SIZE,
        max_retries=Retry(
            total=1,
            connect=1,
            read=0,
            allowed_methods=frozenset({"GET"}),
            backoff_factor=0.2,
        ),
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


_SESSION = _make_session()

# =========================================================
# TIMING (measure which backend calls are slow)
# =========================================================
#
# Every call to the backend is timed and written to the terminal, e.g.
#
#     HTTP GET /admin/dashboard -> ok in 1840 ms  <-- SLOW
#
# Only the method, the path and the time are logged: never the query string,
# the payload or the token.
#
# Turn it off when you are done measuring (.env):
#
#     CL_TIMING=0

TIMING = os.getenv("CL_TIMING", "1").strip().lower() not in {"0", "false", "no", "off"}

SLOW_MS = 500  # calls at or above this are marked SLOW

# Per-script-run totals, read by app.py ([rerun] line). Thread-local, so one
# user's run never mixes with another's.
_timing = threading.local()


def reset_http_time() -> None:
    _timing.calls = 0
    _timing.ms = 0.0


def http_time() -> tuple[int, float]:
    """(number of backend calls, total milliseconds) since reset_http_time()."""
    return getattr(_timing, "calls", 0), getattr(_timing, "ms", 0.0)


# =========================================================
# BACKEND URL
# =========================================================

DEFAULT_BACKEND_URL = "http://127.0.0.1:8000"


def _backend_url() -> str:
    """
    Return the configured FastAPI backend URL.

    BACKEND_URL can be provided through the environment.

    Example:
        BACKEND_URL=http://127.0.0.1:8000
    """
    return (
        os.getenv("BACKEND_URL", DEFAULT_BACKEND_URL).strip().rstrip("/")
        or DEFAULT_BACKEND_URL
    )


# =========================================================
# HTTP / RESPONSE HELPERS
# =========================================================


def _get_error(response) -> str:
    """
    Extract a useful error message from a FastAPI response.
    """
    try:
        data = response.json()
    except ValueError:
        return f"Backend error ({response.status_code})"

    detail = data.get("detail") if isinstance(data, dict) else None

    if isinstance(detail, list):
        messages = [
            str(item.get("msg", "")) for item in detail if isinstance(item, dict)
        ]

        return (
            "; ".join(message for message in messages if message)
            or "Some of the information sent was invalid."
        )

    if detail:
        return str(detail)

    if isinstance(data, dict):
        error = data.get("error")
        if error:
            return str(error)

        message = data.get("message")
        if message:
            return str(message)

    return "An error occurred."


def _admin_headers() -> dict:
    """
    Return the legacy X-Admin-Token header.

    This remains only for existing backend routes that still require
    ADMIN_API_TOKEN.

    New Admin routes should preferably use the authenticated user's
    Bearer access token instead.
    """
    token = (os.getenv("ADMIN_API_TOKEN") or "").strip()

    return {"X-Admin-Token": token} if token else {}


def _auth_headers(token: str) -> dict:
    """
    Return Bearer authentication headers.
    """
    token = (token or "").strip()

    return {"Authorization": f"Bearer {token}"} if token else {}


def _request_inner(
    method,
    path,
    payload=None,
    params=None,
    headers=None,
    timeout=15,
) -> dict:
    """
    Send an HTTP request to the FastAPI backend.

    Successful HTTP responses are accepted for all 2xx status codes.

    The backend is expected to return JSON objects such as:

        {
            "success": true,
            ...
        }

    If the backend returns a non-dict JSON value, the client reports it
    as an unexpected response.
    """

    try:
        response = _SESSION.request(
            method,
            f"{_backend_url()}{path}",
            json=payload,
            params=params,
            headers=headers,
            timeout=timeout,
        )

    except requests.exceptions.RequestException:
        logger.warning("Backend unreachable for %s", path)

        return {
            "success": False,
            "error": "Unable to connect to the backend.",
            "status_code": 0,  # 0 = never reached the backend
        }

    # -----------------------------------------------------
    # Successful HTTP response
    # -----------------------------------------------------

    if 200 <= response.status_code < 300:

        # 204 No Content
        if response.status_code == 204:
            return {
                "success": True,
            }

        try:
            data = response.json()

        except ValueError:
            return {
                "success": False,
                "error": "The backend sent an unreadable response.",
            }

        if isinstance(data, dict):
            data.setdefault("success", True)
            return data

        return {
            "success": False,
            "error": "The backend sent an unexpected response.",
        }

    # -----------------------------------------------------
    # Failed HTTP response
    # -----------------------------------------------------

    return {
        "success": False,
        "error": _get_error(response),
        "status_code": response.status_code,
    }


def _request(
    method,
    path,
    payload=None,
    params=None,
    headers=None,
    timeout=15,
) -> dict:
    """
    Same as _request_inner(), plus one timing line per call (see TIMING).
    """

    if not TIMING:
        return _request_inner(method, path, payload, params, headers, timeout)

    start = time.perf_counter()
    result = None

    try:
        result = _request_inner(method, path, payload, params, headers, timeout)
        return result
    finally:
        ms = (time.perf_counter() - start) * 1000
        _timing.calls = getattr(_timing, "calls", 0) + 1
        _timing.ms = getattr(_timing, "ms", 0.0) + ms
        state = "ok" if isinstance(result, dict) and result.get("success") else "FAIL"
        logger.warning(
            "HTTP %s %s -> %s in %.0f ms%s",
            method,
            path,
            state,
            ms,
            "  <-- SLOW" if ms >= SLOW_MS else "",
        )


def _post(path, payload, timeout=15) -> dict:
    """
    Convenience helper for POST requests.
    """
    return _request(
        "POST",
        path,
        payload=payload,
        timeout=timeout,
    )


# =========================================================
# AUTH
# =========================================================


def email_exists(email: str) -> bool:
    """
    Check whether an email already exists.
    """
    start = time.perf_counter()

    try:
        response = _SESSION.get(
            f"{_backend_url()}/auth/email-exists",
            params={"email": email},
            timeout=10,
        )
        if TIMING:
            logger.warning(
                "HTTP GET /auth/email-exists in %.0f ms",
                (time.perf_counter() - start) * 1000,
            )

        if response.status_code == 200:
            return bool(response.json().get("exists", False))

        return False

    except (
        requests.exceptions.RequestException,
        ValueError,
    ):
        return False


def signup_user(
    email,
    first_name,
    last_name,
    department,
    role,
    password,
    contact_number="",
) -> dict:
    """
    Create/sign up a user.
    """
    return _post(
        "/auth/signup",
        {
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
            "department": department,
            "role": role,
            "password": password,
            "contact_number": contact_number,
        },
        timeout=20,
    )


def verify_verification_code(
    email: str,
    code: str,
) -> dict:
    """
    Verify an email verification code.
    """
    return _post(
        "/auth/verify-code",
        {
            "email": email,
            "code": code,
        },
        timeout=10,
    )


def create_account(email: str) -> dict:
    """
    Create an account after verification.
    """
    return _post(
        "/auth/create-account",
        {
            "email": email,
        },
        timeout=15,
    )


def login_user(
    email: str,
    password: str,
) -> dict:
    """
    Authenticate a user and obtain an access token.
    """
    return _post(
        "/auth/login",
        {
            "email": email,
            "password": password,
        },
        timeout=15,
    )


def resend_verification_code(
    email: str,
    first_name: str = "",
) -> dict:
    """
    Resend the verification code.
    """
    return _post(
        "/auth/resend-code",
        {
            "email": email,
            "first_name": first_name,
        },
        timeout=20,
    )


def request_password_reset(email: str) -> dict:
    """
    Request a password reset.
    """
    return _post(
        "/auth/forgot-password",
        {
            "email": email,
        },
        timeout=20,
    )


def reset_password(
    email: str,
    code: str,
    new_password: str,
) -> dict:
    """
    Reset a user's password.
    """
    return _post(
        "/auth/reset-password",
        {
            "email": email,
            "code": code,
            "new_password": new_password,
        },
        timeout=15,
    )


# =========================================================
# USER MANAGEMENT
# =========================================================
#
# These endpoints currently use X-Admin-Token because the existing
# backend routes use that authentication mechanism.
#
# Do not remove these until those backend routes are migrated.
# =========================================================


def list_users(
    status=None,
    role=None,
    search=None,
    department=None,
    token="",
) -> dict:
    """
    List users using the existing administrative user endpoint.

    token: the logged-in Admin's access token (accepted by the backend
    instead of ADMIN_API_TOKEN).
    """

    params = {
        key: value
        for key, value in [
            ("status", status),
            ("role", role),
            ("search", search),
            ("department", department),
        ]
        if value
    }

    return _request(
        "GET",
        "/users",
        params=params,
        headers={**_admin_headers(), **_auth_headers(token)},
        timeout=15,
    )


def get_user(user_id, token="") -> dict:
    """
    Get a user by UserId.
    """
    return _request(
        "GET",
        f"/users/{quote(str(user_id), safe='')}",
        headers={**_admin_headers(), **_auth_headers(token)},
        timeout=10,
    )


def update_user(
    user_id,
    token="",
    **changes,
) -> dict:
    """
    Update user fields.
    """
    return _request(
        "PATCH",
        f"/users/{quote(str(user_id), safe='')}",
        payload=changes,
        headers={**_admin_headers(), **_auth_headers(token)},
        timeout=15,
    )


def update_user_status(
    user_id,
    status: str,
    token: str = "",
) -> dict:
    """
    Update a user's status.
    """
    return _request(
        "PATCH",
        f"/users/{quote(str(user_id), safe='')}/status",
        payload={"status": status},
        headers={**_admin_headers(), **_auth_headers(token)},
        timeout=15,
    )


def delete_user(user_id, token="") -> dict:
    """
    Delete a user.
    """
    return _request(
        "DELETE",
        f"/users/{quote(str(user_id), safe='')}",
        headers={**_admin_headers(), **_auth_headers(token)},
        timeout=15,
    )


# =========================================================
# COMPUTERS
# =========================================================


def list_computers(
    room=None,
    status=None,
    escalation_status=None,
    search=None,
    token="",
) -> dict:
    """
    List/search computers.

    Bearer authentication is included when a token is supplied.

    The legacy X-Admin-Token is retained for compatibility with the
    current computer endpoint.
    """

    params = {
        key: value
        for key, value in [
            ("room", room),
            ("status", status),
            ("escalation_status", escalation_status),
            ("search", search),
        ]
        if value
    }

    headers = {
        **_admin_headers(),
        **_auth_headers(token),
    }

    return _request(
        "GET",
        "/computers",
        params=params,
        headers=headers,
        timeout=15,
    )


def get_computer(
    computer_id: int,
    token: str = "",
) -> dict:
    """
    Get one computer by ComputerId.
    """
    return _request(
        "GET",
        f"/computers/{quote(str(computer_id), safe='')}",
        headers=_auth_headers(token),
        timeout=15,
    )


def create_computer(
    room: str,
    unit_number: int,
    status: str = "good",
    token: str = "",
) -> dict:
    """
    Create a computer.

    The token is optional for backwards compatibility.
    """
    headers = {
        **_admin_headers(),
        **_auth_headers(token),
    }

    return _request(
        "POST",
        "/computers",
        payload={
            "room": room,
            "unit_number": unit_number,
            "status": status,
        },
        headers=headers,
        timeout=15,
    )


def update_computer(
    computer_id: int,
    changes: dict,
    token: str = "",
) -> dict:
    """
    Update a computer.
    """
    headers = {
        **_admin_headers(),
        **_auth_headers(token),
    }

    return _request(
        "PATCH",
        f"/computers/{quote(str(computer_id), safe='')}",
        payload=changes,
        headers=headers,
        timeout=15,
    )


def delete_computer(
    computer_id: int,
    token: str = "",
) -> dict:
    """
    Delete a computer.
    """
    headers = {
        **_admin_headers(),
        **_auth_headers(token),
    }

    return _request(
        "DELETE",
        f"/computers/{quote(str(computer_id), safe='')}",
        headers=headers,
        timeout=15,
    )


# =========================================================
# HARDWARE
# =========================================================


def upsert_hardware(
    computer_id: int,
    data: dict,
    token: str = "",
) -> dict:
    """
    Create or update the hardware record for a computer.
    """
    headers = {
        **_admin_headers(),
        **_auth_headers(token),
    }

    return _request(
        "PUT",
        f"/computers/{quote(str(computer_id), safe='')}/hardware",
        payload=data,
        headers=headers,
        timeout=15,
    )


# =========================================================
# SOFTWARE
# =========================================================


def list_software(
    computer_id: int,
    token: str = "",
) -> dict:
    """
    List software installed on a computer.
    """
    return _request(
        "GET",
        f"/computers/{quote(str(computer_id), safe='')}/software",
        headers=_auth_headers(token),
        timeout=15,
    )


def add_software(
    computer_id: int,
    software_name: str,
    version: str = "",
    date_installed: str | None = None,
    token: str = "",
) -> dict:
    """
    Install/add software to a computer.
    """
    return _request(
        "POST",
        f"/computers/{quote(str(computer_id), safe='')}/software",
        payload={
            "software_name": software_name,
            "version": version,
            "date_installed": date_installed,
        },
        headers=_auth_headers(token),
        timeout=15,
    )


def update_software(
    computer_id: int,
    software_id: int,
    version: str,
    token: str = "",
) -> dict:
    """
    Update a software version.
    """
    return _request(
        "PATCH",
        (
            f"/computers/{quote(str(computer_id), safe='')}"
            f"/software/{quote(str(software_id), safe='')}"
        ),
        payload={
            "version": version,
        },
        headers=_auth_headers(token),
        timeout=15,
    )


def delete_software(
    computer_id: int,
    software_id: int,
    token: str = "",
) -> dict:
    """
    Delete installed software.
    """
    return _request(
        "DELETE",
        (
            f"/computers/{quote(str(computer_id), safe='')}"
            f"/software/{quote(str(software_id), safe='')}"
        ),
        headers=_auth_headers(token),
        timeout=15,
    )


# =========================================================
# HARDWARE REPLACEMENTS
# =========================================================


def add_hw_replacement(
    computer_id: int,
    component_replaced: str,
    old_component: str,
    new_component: str,
    reason: str,
    date_replaced: str | None = None,
    token: str = "",
) -> dict:
    """
    Record a hardware replacement.
    """
    return _request(
        "POST",
        f"/computers/{quote(str(computer_id), safe='')}/replacements",
        payload={
            "component_replaced": component_replaced,
            "old_component": old_component,
            "new_component": new_component,
            "date_replaced": date_replaced,
            "reason": reason,
        },
        headers=_auth_headers(token),
        timeout=15,
    )


# =========================================================
# MAINTENANCE
# =========================================================


def add_maintenance_record(
    computer_id: int,
    description: str,
    date_performed: str | None = None,
    token: str = "",
) -> dict:
    """
    Add a maintenance record.

    The backend determines the authenticated technician/admin identity
    from the access token.
    """
    return _request(
        "POST",
        "/technician/maintenance",
        payload={
            "computer_id": computer_id,
            "description": description,
            "date_performed": date_performed,
        },
        headers=_auth_headers(token),
        timeout=15,
    )


# =========================================================
# REPORTS
# =========================================================


def search_reports(
    computer_id=None,
    reported_by=None,
    status=None,
    reporter_name=None,
    created_after=None,
    created_before=None,
    limit=200,
    token="",
) -> dict:
    """
    Search reports using backend/database-side filtering.

    This should be preferred over loading all reports and filtering
    them in Streamlit.
    """

    params = {
        key: value
        for key, value in [
            ("computer_id", computer_id),
            ("reported_by", reported_by),
            ("status", status),
            ("reporter_name", reporter_name),
            ("created_after", created_after),
            ("created_before", created_before),
            ("limit", limit),
        ]
        if value is not None
    }

    return _request(
        "GET",
        "/reports",
        params=params,
        headers=_auth_headers(token),
        timeout=20,
    )


# =========================================================
# TECHNICIAN
# =========================================================


def get_technician_data(
    token: str,
) -> dict:
    """
    GET /technician/dashboard
    """
    return _request(
        "GET",
        "/technician/dashboard",
        headers=_auth_headers(token),
        timeout=20,
    )


def update_report_status(
    token: str,
    report_id,
    status: str,
    note: str = "",
) -> dict:
    """
    Update a report's technician status.
    """
    return _request(
        "PATCH",
        f"/technician/reports/{quote(str(report_id), safe='')}",
        payload={
            "status": status,
            "note": note,
        },
        headers=_auth_headers(token),
        timeout=15,
    )


def set_escalation_status(
    token: str,
    room: str,
    unit_number: int,
    status: str,
    computer_id: int | None = None,
) -> dict:
    """
    Update the escalation status of a computer/report.

    computer_id is optional for compatibility with the existing
    Technician backend API.
    """
    payload = {
        "room": room,
        "unit_number": unit_number,
        "status": status,
    }

    if computer_id is not None:
        payload["computer_id"] = computer_id

    return _request(
        "PATCH",
        "/technician/escalation",
        payload=payload,
        headers=_auth_headers(token),
        timeout=15,
    )


def update_contact_number(
    token: str,
    contact_number: str,
) -> dict:
    """
    Update the authenticated technician's contact number.
    """
    return _request(
        "PATCH",
        "/technician/profile",
        payload={
            "contact_number": contact_number,
        },
        headers=_auth_headers(token),
        timeout=15,
    )


def change_password(
    token: str,
    current_password: str,
    new_password: str,
) -> dict:
    """
    Change the authenticated technician's password.
    """
    return _request(
        "POST",
        "/technician/change-password",
        payload={
            "current_password": current_password,
            "new_password": new_password,
        },
        headers=_auth_headers(token),
        timeout=20,
    )


# =========================================================
# TEACHER
# =========================================================


def get_teacher_data(
    token: str,
) -> dict:
    """
    GET /teacher/dashboard

    Returns computers with hardware/software information and the
    authenticated teacher's reports.
    """
    return _request(
        "GET",
        "/teacher/dashboard",
        headers=_auth_headers(token),
        timeout=20,
    )


# Alias used by Teacher.py.
get_teacher_dashboard = get_teacher_data


def submit_report(
    token: str,
    room: str,
    unit_number: int,
    issues: list,
    comment: str = "",
) -> dict:
    """
    POST /teacher/reports

    Backend resolves ComputerId from room + unit_number.
    """
    return _request(
        "POST",
        "/teacher/reports",
        payload={
            "room": room,
            "unit_number": unit_number,
            "issues": issues,
            "comment": comment,
        },
        headers=_auth_headers(token),
        timeout=15,
    )


def submit_teacher_report(
    token: str,
    computer_id: int,
    issues: list,
    comment: str = "",
    category: str = "",
) -> dict:
    """
    POST /teacher/reports

    Used when Teacher.py already knows ComputerId.
    """
    return _request(
        "POST",
        "/teacher/reports",
        payload={
            "computer_id": computer_id,
            "issues": issues,
            "comment": comment,
            "category": category,
        },
        headers=_auth_headers(token),
        timeout=15,
    )


def follow_up_teacher_report(
    token: str,
    report_id,
    message: str = "",
) -> dict:
    """
    POST /teacher/reports/{report_id}/follow-up

    report_id: the ReportId (25) or its code ("CL-0025"). The backend checks
    the rules (own report, still waiting, 2 days old, once a day), saves it
    and notifies the technicians.
    """
    return _request(
        "POST",
        f"/teacher/reports/{quote(str(report_id), safe='')}/follow-up",
        payload={"message": message or ""},
        headers=_auth_headers(token),
        timeout=15,
    )


def cancel_teacher_report(token: str, report_id, reason: str = "") -> dict:
    """POST /teacher/reports/{report_id}/cancel"""
    return _request(
        "POST",
        f"/teacher/reports/{quote(str(report_id), safe='')}/cancel",
        payload={"reason": reason or ""},
        headers=_auth_headers(token),
        timeout=15,
    )


def get_teacher_profile(
    token: str,
) -> dict:
    """
    GET /teacher/profile
    """
    return _request(
        "GET",
        "/teacher/profile",
        headers=_auth_headers(token),
        timeout=15,
    )


def update_teacher_contact(
    token: str,
    contact_number: str,
) -> dict:
    """
    PATCH /teacher/profile
    """
    return _request(
        "PATCH",
        "/teacher/profile",
        payload={
            "contact_number": contact_number,
        },
        headers=_auth_headers(token),
        timeout=15,
    )


def get_teacher_report_issues(
    token: str,
) -> dict:
    """
    GET /teacher/report-issues
    """
    return _request(
        "GET",
        "/teacher/report-issues",
        headers=_auth_headers(token),
        timeout=15,
    )


def get_teacher_report_statuses(
    token: str,
) -> dict:
    """
    GET /teacher/report-statuses
    """
    return _request(
        "GET",
        "/teacher/report-statuses",
        headers=_auth_headers(token),
        timeout=15,
    )


def get_teacher_reports(
    token: str,
) -> dict:
    """
    GET /teacher/reports

    Returns only the authenticated teacher's reports.
    """
    return _request(
        "GET",
        "/teacher/reports",
        headers=_auth_headers(token),
        timeout=20,
    )


def get_teacher_computers(
    token: str,
) -> dict:
    """
    GET /teacher/computers

    Returns computers with hardware and software.
    """
    return _request(
        "GET",
        "/teacher/computers",
        headers=_auth_headers(token),
        timeout=20,
    )


# =========================================================
# NOTIFICATIONS (any role; the backend returns only the user's own)
# =========================================================


def get_notifications(token: str, limit: int = 50) -> dict:
    """
    GET /notifications -> {"success": True, "notifications": [...]}
    """
    return _request(
        "GET",
        "/notifications",
        params={"limit": limit},
        headers=_auth_headers(token),
        timeout=15,
    )


def mark_notifications_read(token: str, ids: list | None = None) -> dict:
    """
    PATCH /notifications/read  (ids=None marks all as read)
    """
    return _request(
        "PATCH",
        "/notifications/read",
        payload={"ids": ids},
        headers=_auth_headers(token),
        timeout=15,
    )


# =========================================================
# ADMIN DASHBOARD
# =========================================================


def get_admin_data(
    token: str,
) -> dict:
    """
    GET /admin/dashboard

    Returns the Admin dashboard data from the FastAPI backend.
    """
    return _request(
        "GET",
        "/admin/dashboard",
        headers=_auth_headers(token),
        timeout=20,
    )


# =========================================================
# ADMIN USER REQUESTS
# =========================================================


def admin_list_requests(
    token: str,
    search: str | None = None,
    role: str | None = None,
    department: str | None = None,
) -> dict:
    """
    GET /admin/requests

    Backend-side filtering is used when search/role/department are
    supplied.
    """

    params = {
        key: value
        for key, value in [
            ("search", search),
            ("role", role),
            ("department", department),
        ]
        if value
    }

    return _request(
        "GET",
        "/admin/requests",
        params=params,
        headers=_auth_headers(token),
        timeout=15,
    )


def decide_user_request(
    token: str,
    user_id,
    decision: str,
    reason: str = "",
) -> dict:
    """
    PATCH /admin/requests/{user_id}

    Approve or cancel a pending account request.
    """
    return _request(
        "PATCH",
        f"/admin/requests/{quote(str(user_id), safe='')}",
        payload={
            "decision": decision,
            "reason": reason,
        },
        headers=_auth_headers(token),
        timeout=15,
    )


# =========================================================
# ADMIN ESCALATIONS
# =========================================================


def admin_decide_escalation(
    token: str,
    report_id,
    decision: str,
) -> dict:
    """
    Decide an escalated teacher report as Admin.

    Expected backend route:

        PATCH /admin/reports/{report_id}/escalation

    Expected payload:

        {
            "decision": "approve"
        }

    or:

        {
            "decision": "resolve"
        }

    The exact accepted decision values must be enforced by the backend.

    IMPORTANT:
    The backend route/service must exist before this frontend operation
    can work.
    """
    return _request(
        "PATCH",
        f"/admin/reports/{quote(str(report_id), safe='')}/escalation",
        payload={
            "decision": decision,
        },
        headers=_auth_headers(token),
        timeout=15,
    )


# =========================================================
# INVENTORY (Admin and Technician) -> Supabase
# =========================================================
#
# history: the lines added to MaintenanceHistory, [{"kind", "text"}].


def inv_add_computer(token: str, data: dict) -> dict:
    """POST /inventory/computers: {room, unit_number, brand, model, serial,
    status, hardware {label: value}, software [{name, version}], history}."""
    return _request("POST", "/inventory/computers", payload=data,
                    headers=_auth_headers(token), timeout=30)


def inv_update_computer(token: str, computer_id, data: dict) -> dict:
    """PATCH /inventory/computers/{id}: {brand, model, serial, status,
    hardware {label: value}, history}."""
    return _request("PATCH", f"/inventory/computers/{quote(str(computer_id), safe='')}",
                    payload=data, headers=_auth_headers(token), timeout=30)


def inv_install_software(token: str, computer_id, name: str, version: str, history=None) -> dict:
    return _request("POST", f"/inventory/computers/{quote(str(computer_id), safe='')}/software",
                    payload={"name": name, "version": version, "history": history or []},
                    headers=_auth_headers(token), timeout=15)


def inv_update_software(token: str, software_id, version: str, history=None) -> dict:
    return _request("PATCH", f"/inventory/software/{quote(str(software_id), safe='')}",
                    payload={"version": version, "history": history or []},
                    headers=_auth_headers(token), timeout=15)


def inv_remove_software(token: str, software_id, history=None) -> dict:
    return _request("POST", f"/inventory/software/{quote(str(software_id), safe='')}/remove",
                    payload={"history": history or []},
                    headers=_auth_headers(token), timeout=15)


def inv_log_maintenance(token: str, computer_id, kind: str, text: str, done_by: str = "") -> dict:
    return _request("POST", f"/inventory/computers/{quote(str(computer_id), safe='')}/maintenance",
                    payload={"kind": kind, "text": text, "done_by": done_by},
                    headers=_auth_headers(token), timeout=15)


def admin_create_laboratory(
    token: str,
    room: str,
    units: int,
    hardware: dict | None = None,
) -> dict:
    """
    Add a laboratory's computer units to public."Computers" (Admin only).

        POST /admin/laboratories   {"room": "...", "units": 40}

    Every unit gets Room = room and UnitNumber 1..units; the backend refuses
    a room that already has computers. The response lists the saved rows:

        {"success": true, "room": "...", "computers": [{"id", "room",
         "unit_number", "status", ...}, ...]}
    """
    return _request(
        "POST",
        "/admin/laboratories",
        payload={
            "room": room,
            "units": int(units),
            "hardware": hardware or {},
        },
        headers=_auth_headers(token),
        timeout=30,
    )


# =========================================================
# ADMIN PROFILE
# =========================================================


def admin_update_contact_number(
    token: str,
    contact_number: str,
) -> dict:
    """
    PATCH /admin/profile

    Updates the authenticated Admin's contact number.
    """
    return _request(
        "PATCH",
        "/admin/profile",
        payload={
            "contact_number": contact_number,
        },
        headers=_auth_headers(token),
        timeout=15,
    )


def admin_change_email(
    token: str,
    new_email: str,
    current_password: str,
) -> dict:
    """
    POST /admin/email

    Changes the authenticated Admin's own email (the login email and
    Users.Email). The current password is required.
    """
    return _request(
        "POST",
        "/admin/email",
        payload={
            "new_email": new_email,
            "current_password": current_password,
        },
        headers=_auth_headers(token),
        timeout=20,
    )


def admin_change_password(
    token: str,
    current_password: str,
    new_password: str,
) -> dict:
    """
    POST /admin/change-password
    """
    return _request(
        "POST",
        "/admin/change-password",
        payload={
            "current_password": current_password,
            "new_password": new_password,
        },
        headers=_auth_headers(token),
        timeout=20,
    )
