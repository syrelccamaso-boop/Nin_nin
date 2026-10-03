import logging
import os

import requests
from urllib.parse import quote

logger = logging.getLogger("centrum.client")


# =========================================================
# BACKEND URL
# =========================================================
# Can be overridden with BACKEND_URL in the environment / .env.

DEFAULT_BACKEND_URL = "http://127.0.0.1:8000"


def _backend_url() -> str:

    return (
        os.getenv("BACKEND_URL", DEFAULT_BACKEND_URL).strip().rstrip("/")
        or DEFAULT_BACKEND_URL
    )


# =========================================================
# HELPERS
# =========================================================


def _get_error(response):
    """Always return a short, readable string (never a list or dict)."""

    try:

        data = response.json()

    except ValueError:

        return f"Backend error " f"({response.status_code})"

    detail = data.get("detail") if isinstance(data, dict) else None

    # FastAPI validation errors (422) send a list of problems.
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

    return "An error occurred."


def _admin_headers():
    """X-Admin-Token for the /users endpoints (ADMIN_API_TOKEN in .env)."""

    token = (os.getenv("ADMIN_API_TOKEN") or "").strip()

    return {"X-Admin-Token": token} if token else {}


def _post(path, payload, timeout=15):

    return _request("POST", path, payload=payload, timeout=timeout)


def _request(method, path, payload=None, params=None, headers=None, timeout=15):

    try:

        response = requests.request(
            method,
            f"{_backend_url()}{path}",
            json=payload,
            params=params,
            headers=headers,
            timeout=timeout,
        )

    except requests.exceptions.RequestException:

        logger.warning("Backend unreachable for %s", path)

        return {"success": False, "error": ("Unable to connect to the backend.")}

    if response.status_code == 200:

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

        return {"success": False, "error": "The backend sent an unexpected response."}

    return {"success": False, "error": _get_error(response)}


# =========================================================
# CHECK EMAIL
# =========================================================


def email_exists(email):

    try:

        response = requests.get(
            f"{_backend_url()}/auth/email-exists", params={"email": email}, timeout=10
        )

        if response.status_code == 200:

            return bool(response.json().get("exists", False))

        return False

    except (requests.exceptions.RequestException, ValueError):

        return False


# =========================================================
# SIGN UP
# =========================================================


def signup_user(
    email, first_name, last_name, department, role, password, contact_number=""
):

    payload = {
        "email": email,
        "first_name": first_name,
        "last_name": last_name,
        "department": department,
        "role": role,
        "password": password,
        "contact_number": contact_number,
    }

    return _post("/auth/signup", payload, timeout=20)


# =========================================================
# VERIFY CODE
# =========================================================


def verify_verification_code(email, code):

    payload = {"email": email, "code": code}

    return _post("/auth/verify-code", payload, timeout=10)


# =========================================================
# CREATE ACCOUNT
# =========================================================


def create_account(email):

    return _post("/auth/create-account", {"email": email}, timeout=15)


# =========================================================
# LOGIN
# =========================================================


def login_user(email, password):

    payload = {"email": email, "password": password}

    return _post("/auth/login", payload, timeout=15)


# =========================================================
# RESEND VERIFICATION CODE
# =========================================================


def resend_verification_code(email, first_name=""):

    payload = {"email": email, "first_name": first_name}

    return _post("/auth/resend-code", payload, timeout=20)


# =========================================================
# FORGOT PASSWORD
# =========================================================


def request_password_reset(email):

    return _post("/auth/forgot-password", {"email": email}, timeout=20)


def reset_password(email, code, new_password):

    payload = {"email": email, "code": code, "new_password": new_password}

    return _post("/auth/reset-password", payload, timeout=15)


# =========================================================
# USER MANAGEMENT (admin)  - needs ADMIN_API_TOKEN in .env
# =========================================================


def list_users(status=None, role=None):

    params = {
        key: value for key, value in (("status", status), ("role", role)) if value
    }

    return _request(
        "GET", "/users", params=params, headers=_admin_headers(), timeout=15
    )


def get_user(user_id):

    return _request("GET", f"/users/{user_id}", headers=_admin_headers(), timeout=10)


def update_user(user_id, **changes):

    return _request(
        "PATCH",
        f"/users/{user_id}",
        payload=changes,
        headers=_admin_headers(),
        timeout=15,
    )


def update_user_status(user_id, status):

    return _request(
        "PATCH",
        f"/users/{user_id}/status",
        payload={"status": status},
        headers=_admin_headers(),
        timeout=15,
    )


def delete_user(user_id):

    return _request("DELETE", f"/users/{user_id}", headers=_admin_headers(), timeout=15)


# =========================================================
# TECHNICIAN  - needs the access token returned by login_user()
# =========================================================


def _auth_headers(token):
    """Authorization header with the logged-in user's access token."""

    token = (token or "").strip()

    return {"Authorization": f"Bearer {token}"} if token else {}


def get_technician_data(token):

    return _request(
        "GET", "/technician/dashboard", headers=_auth_headers(token), timeout=20
    )


def update_report_status(token, report_id, status, note=""):

    return _request(
        "PATCH",
        f"/technician/reports/{quote(str(report_id), safe='')}",
        payload={"status": status, "note": note},
        headers=_auth_headers(token),
        timeout=15,
    )


def set_escalation_status(token, room, unit_number, status):

    return _request(
        "PATCH",
        "/technician/escalation",
        payload={"room": room, "unit_number": unit_number, "status": status},
        headers=_auth_headers(token),
        timeout=15,
    )


def update_contact_number(token, contact_number):

    return _request(
        "PATCH",
        "/technician/profile",
        payload={"contact_number": contact_number},
        headers=_auth_headers(token),
        timeout=15,
    )


def change_password(token, current_password, new_password):

    return _request(
        "POST",
        "/technician/change-password",
        payload={"current_password": current_password, "new_password": new_password},
        headers=_auth_headers(token),
        timeout=20,
    )


# =========================================================
# ADMIN DASHBOARD  - needs the access token returned by login_user()
# =========================================================


def get_admin_data(token):

    return _request("GET", "/admin/dashboard", headers=_auth_headers(token), timeout=20)


def decide_user_request(token, user_id, decision, reason=""):
    """decision: "approve" or "cancel"."""

    return _request(
        "PATCH",
        f"/admin/requests/{quote(str(user_id), safe='')}",
        payload={"decision": decision, "reason": reason},
        headers=_auth_headers(token),
        timeout=15,
    )


def admin_update_contact_number(token, contact_number):

    return _request(
        "PATCH",
        "/admin/profile",
        payload={"contact_number": contact_number},
        headers=_auth_headers(token),
        timeout=15,
    )


def admin_change_password(token, current_password, new_password):

    return _request(
        "POST",
        "/admin/change-password",
        payload={"current_password": current_password, "new_password": new_password},
        headers=_auth_headers(token),
        timeout=20,
    )
