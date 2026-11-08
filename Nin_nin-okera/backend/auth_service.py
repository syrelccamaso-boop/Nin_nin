# auth_service.py

import logging
import os
import re
import secrets
import string
import threading
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import requests
from requests.adapters import HTTPAdapter

from . import perf
from . import users_repository as users
from .database import (
    ANON_KEY,
    SERVICE_ROLE_KEY,
    SUPABASE_URL,
    DatabaseConfigError,
    get_client,
    new_auth_client,
)
from .email_service import (
    EmailSendError,
    send_password_reset_email,
    send_verification_email,
)
from .users_repository import DatabaseError, error_text

logger = logging.getLogger("centrum.auth")


# =========================================================
# SETTINGS
# =========================================================

CODE_TTL = timedelta(minutes=10)

# Wrong guesses allowed per issued 6-digit code. The 3rd wrong guess
# invalidates the code; a new one must be requested.
MAX_CODE_ATTEMPTS = 3

# After the 3rd wrong guess, no new code can be requested for this long
# (the same 10 minutes a code stays valid).
CODE_BLOCK_TIME = CODE_TTL

# Code issuing limits, per email and per purpose (signup / reset).
CODE_RESEND_COOLDOWN = timedelta(seconds=60)
CODE_ISSUE_WINDOW = timedelta(hours=1)
MAX_CODES_PER_WINDOW = 5

# Login: 5 consecutive wrong passwords lock password attempts for that
# email for LOGIN_LOCK_TIME (temporary - never a permanent lock).
# Counted on the server in the "LoginAttempts" table (see
# backend/sql/login_attempts.sql), so a refresh or restart can't reset it.
MAX_LOGIN_FAILURES = 5
LOGIN_LOCK_TIME = timedelta(minutes=15)

# Roles whose newly created accounts require admin approval.
APPROVAL_ROLES = ("Technician",)

# Users with these statuses are allowed to log in.
LOGIN_ALLOWED_STATUSES = {
    "active",
    "approved",
}


def _fixed_admin_email() -> str:
    return users.normalize_email(os.getenv("ADMIN_EMAIL"))


def _is_fixed_admin(email: str) -> bool:
    admin_email = _fixed_admin_email()

    return bool(admin_email) and users.normalize_email(email) == admin_email


def _login_email(name: str) -> str:
    """
    Convert ADMIN_USERNAME to ADMIN_EMAIL if configured.
    Otherwise return the normalized email.
    """

    name = users.normalize_email(name)

    username = (os.getenv("ADMIN_USERNAME") or "").strip().lower()

    if username and name == username and _fixed_admin_email():
        return _fixed_admin_email()

    return name


def _fixed_admin_user(email: str, auth_user_id) -> dict:
    """
    Return the same application-user structure produced by
    users.to_app_user().

    The fixed admin does not have a Users table row.
    """

    return {
        "id": auth_user_id,
        "user_id": auth_user_id,
        "email": email,
        "first_name": ((os.getenv("ADMIN_NAME") or "").strip() or "Administrator"),
        "last_name": "",
        "role_id": None,
        "role": "Admin",
        "department": "",
        "contact_number": "",
        "status": "active",
        "created_at": None,
        "updated_at": None,
        "date_confirmed": None,
        "auth_id": auth_user_id,
    }


# =========================================================
# TEMPORARY STORAGE
# =========================================================

# Temporary email-verification codes.
# Cleared when the server restarts.
verification_codes = {}

# Temporary signup information.
# Cleared when the server restarts.
pending_signups = {}

# Temporary password-reset codes.
# Cleared when the server restarts.
reset_codes = {}

# When codes were sent: {(purpose, email): [datetime, ...]}.
code_issues = {}

# No new code until this time, after 3 wrong guesses:
# {(purpose, email): datetime}.
code_blocks = {}

# Guards the three dicts above: FastAPI runs sync routes in a thread
# pool, so two requests could otherwise race on the same attempt counter.
_codes_lock = threading.RLock()


# =========================================================
# EMAIL VALIDATION
# =========================================================

EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def valid_email(email: str) -> bool:
    return bool(EMAIL_REGEX.match((email or "").strip()))


# =========================================================
# PASSWORD VALIDATION
# =========================================================


def validate_password(password: str):
    password = password or ""

    if len(password) < 8:
        return (
            False,
            "Password must be at least 8 characters.",
        )

    if not any(character.islower() for character in password):
        return (
            False,
            "Password must have at least 1 lowercase letter.",
        )

    if not any(character.isupper() for character in password):
        return (
            False,
            "Password must have at least 1 uppercase letter.",
        )

    if not any(character.isdigit() for character in password):
        return (
            False,
            "Password must have at least 1 digit.",
        )

    if not any(character in string.punctuation for character in password):
        return (
            False,
            "Password must have at least 1 special character.",
        )

    return True, None


# =========================================================
# EMAIL EXISTS
# =========================================================


def email_taken(email: str) -> bool:
    """
    Check whether an email already belongs to:

    1. The fixed administrator account, or
    2. A Users table account.
    """

    return _is_fixed_admin(email) or users.email_exists(email)


# =========================================================
# GENERATE 6-DIGIT CODE
# =========================================================


def generate_verification_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


# =========================================================
# SHARED CODE CHECK
# =========================================================


def _check_code(
    store: dict,
    email: str,
    entered_code: str,
):
    """
    Validate a temporary six-digit verification code.

    Returns:
        None        -> code is valid
        str         -> error message
    """

    purpose = "reset" if store is reset_codes else "signup"

    with _codes_lock:

        data = store.get(email)

        if not data:
            return "No verification code was found. " "Please request a new code."

        if datetime.now(timezone.utc) > data["expires"]:
            store.pop(email, None)

            return "Your verification code has expired. " "Please request a new code."

        if data["attempts"] >= MAX_CODE_ATTEMPTS:
            store.pop(email, None)
            code_blocks[(purpose, email)] = datetime.now(timezone.utc) + CODE_BLOCK_TIME

            return _code_block_message(CODE_BLOCK_TIME)

        if (
            len(entered_code) == 6
            and entered_code.isdigit()
            and secrets.compare_digest(data["code"], entered_code)
        ):
            # Used once, then gone: a code can't be reused.
            store.pop(email, None)

            return None

        data["attempts"] += 1
        left = MAX_CODE_ATTEMPTS - data["attempts"]

        if left <= 0:
            # 3rd wrong guess: this code is no longer valid, and no new code
            # can be requested for CODE_BLOCK_TIME (10 minutes).
            store.pop(email, None)
            code_blocks[(purpose, email)] = datetime.now(timezone.utc) + CODE_BLOCK_TIME

            return "The verification code is incorrect. " + _code_block_message(
                CODE_BLOCK_TIME
            )

        return (
            "The verification code is incorrect. "
            f"{left} attempt{'s' if left != 1 else ''} left."
        )


def _code_block_message(remaining: timedelta) -> str:
    minutes = max(1, -(-int(remaining.total_seconds()) // 60))
    return (
        "Too many incorrect attempts. "
        f"You can request a new code in {minutes} minute{'s' if minutes != 1 else ''}."
    )


def _code_issue_error(purpose: str, email: str):
    """
    Server-side limit on sending codes, so asking for a new code can't be
    used to get unlimited guesses: one code per CODE_RESEND_COOLDOWN and
    at most MAX_CODES_PER_WINDOW per CODE_ISSUE_WINDOW, per email.

    Returns None (and records the send) when allowed, otherwise an error.
    """

    now = datetime.now(timezone.utc)
    key = (purpose, email)

    with _codes_lock:

        blocked_until = code_blocks.get(key)

        if blocked_until and blocked_until > now:
            return _code_block_message(blocked_until - now)

        code_blocks.pop(key, None)

        recent = [t for t in code_issues.get(key, []) if now - t < CODE_ISSUE_WINDOW]

        if recent and now - recent[-1] < CODE_RESEND_COOLDOWN:
            wait = int((CODE_RESEND_COOLDOWN - (now - recent[-1])).total_seconds()) + 1

            code_issues[key] = recent

            return f"Please wait {wait} seconds before requesting another code."

        if len(recent) >= MAX_CODES_PER_WINDOW:
            code_issues[key] = recent

            return (
                "Too many codes were requested for this email. "
                "Please try again in an hour."
            )

        recent.append(now)
        code_issues[key] = recent

    return None


# =========================================================
# LOGIN ATTEMPT LIMIT (server-side, persistent)
# =========================================================
#
# Backed by the "LoginAttempts" table and the login_attempt_* SQL
# functions in backend/sql/login_attempts.sql (run once in Supabase).
# The functions lock the row, so parallel requests can't slip past the
# limit: every login attempt reserves one of the 5 tries BEFORE the
# password is checked, and is refunded if the check failed for a reason
# other than a wrong password (network, Supabase outage...).
#
# Locks are per email and always expire (LOGIN_LOCK_TIME). The same rules
# apply to unregistered emails, so the response never reveals whether an
# account exists.
# =========================================================

_LOGIN_UNAVAILABLE = "Login is temporarily unavailable. Please try again later."


class _LoginLimitUnavailable(RuntimeError):
    pass


def _login_rpc(function: str, email: str) -> dict:
    def call(client):
        return client.rpc(
            function,
            {
                "p_email": email,
                "p_max": MAX_LOGIN_FAILURES,
                "p_lock_seconds": int(LOGIN_LOCK_TIME.total_seconds()),
            },
        ).execute()

    try:
        response = users._run(f"checking login attempts ({function})", call)
    except DatabaseError as error:
        logger.error(
            "Login attempt limit unavailable - has backend/sql/login_attempts.sql "
            "been run in Supabase? %s",
            error.detail or error,
        )
        raise _LoginLimitUnavailable() from None

    data = response.data
    if isinstance(data, list):
        data = data[0] if data else {}
    return data if isinstance(data, dict) else {}


def _lock_message(seconds) -> str:
    minutes = max(1, -(-int(seconds or 0) // 60))
    return (
        "Too many failed password attempts. "
        f"Please try again in {minutes} minute{'s' if minutes != 1 else ''}."
    )


def _login_begin(email: str):
    """Reserve one password attempt. Returns an error message when blocked."""
    result = _login_rpc("login_attempt_begin", email)
    if result.get("allowed"):
        return None
    return _lock_message(result.get("retry_after"))


def _reset_lock_error(email: str):
    """
    Password reset is not allowed while the email is temporarily locked
    after 5 failed passwords. Read-only: it doesn't use up an attempt.
    Returns an error message while locked, otherwise None.
    """
    try:
        result = _login_rpc("login_lock_status", email)
    except _LoginLimitUnavailable:
        return _LOGIN_UNAVAILABLE

    if result.get("locked"):
        minutes = max(1, -(-int(result.get("retry_after") or 0) // 60))
        return (
            "This account is temporarily locked after too many failed "
            "password attempts. You can reset your password in "
            f"{minutes} minute{'s' if minutes != 1 else ''}."
        )
    return None


def _login_failed(email: str):
    """Record a wrong password. Returns the lock message when this locked it."""
    result = _login_rpc("login_attempt_failed", email)
    if result.get("locked"):
        return _lock_message(result.get("retry_after"))
    return None


def _login_refund(email: str) -> None:
    """The check failed for a reason other than the password: don't count it."""
    try:
        _login_rpc("login_attempt_refund", email)
    except _LoginLimitUnavailable:
        pass


def _login_clear(email: str) -> None:
    """Correct password: reset the consecutive-failure counter."""
    try:
        _login_rpc("login_attempt_clear", email)
    except _LoginLimitUnavailable:
        pass


# =========================================================
# SEND VERIFICATION CODE
# =========================================================


def start_email_verification(
    email: str,
    first_name: str = "",
    check_taken: bool = True,
):
    """check_taken=False when the caller has just checked the email itself
    (POST /auth/signup does), so the same lookup isn't run twice."""

    email = users.normalize_email(email)

    if not valid_email(email):
        return {
            "success": False,
            "error": "Enter a valid email address.",
        }

    try:
        if check_taken and email_taken(email):
            return {
                "success": False,
                "error": ("An account with this email " "already exists."),
            }

    except DatabaseError as error:
        return {
            "success": False,
            "error": str(error),
        }

    issue_error = _code_issue_error("signup", email)

    if issue_error:
        return {
            "success": False,
            "error": issue_error,
        }

    code = generate_verification_code()

    # Replaces (and so invalidates) any earlier code for this email.
    with _codes_lock:
        verification_codes[email] = {
            "code": code,
            "expires": (datetime.now(timezone.utc) + CODE_TTL),
            "attempts": 0,
        }

    try:
        send_verification_email(
            recipient_email=email,
            code=code,
            first_name=first_name,
        )

    except EmailSendError as error:
        verification_codes.pop(email, None)

        return {
            "success": False,
            "error": str(error),
        }

    except Exception:
        verification_codes.pop(email, None)

        logger.exception("Unexpected error while sending " "the verification email.")

        return {
            "success": False,
            "error": (
                "We couldn't send the verification email. " "Please try again later."
            ),
        }

    return {
        "success": True,
        "message": ("A 6-digit verification code " "has been sent to your email."),
    }


# =========================================================
# RESEND VERIFICATION CODE
# =========================================================


def resend_verification_code(email: str):
    email = users.normalize_email(email)

    signup = pending_signups.get(email)

    if not signup:
        return {
            "success": False,
            "error": ("Signup information was not found. " "Please start again."),
        }

    return start_email_verification(
        email=email,
        first_name=signup.get(
            "first_name",
            "",
        ),
    )


# =========================================================
# STORE SIGNUP DATA
# =========================================================


def save_pending_signup(
    email: str,
    first_name: str,
    last_name: str,
    department: str,
    role: str,
    password: str,
    contact_number: str = "",
):
    email = users.normalize_email(email)

    pending_signups[email] = {
        "first_name": (first_name or "").strip(),
        "last_name": (last_name or "").strip(),
        "department": (department or "").strip(),
        "role": (role or "").strip(),
        "password": password,
        "contact_number": (contact_number or "").strip(),
        "verified": False,
    }


# =========================================================
# VERIFY EMAIL CODE
# =========================================================


def verify_verification_code(
    email: str,
    entered_code: str,
):
    email = users.normalize_email(email)

    entered_code = (entered_code or "").strip()

    signup = pending_signups.get(email)

    # Already verified.
    if signup and signup.get("verified") and email not in verification_codes:
        return {
            "success": True,
            "message": "Email verified successfully.",
        }

    error = _check_code(
        verification_codes,
        email,
        entered_code,
    )

    if error:
        return {
            "success": False,
            "error": error,
        }

    if signup:
        signup["verified"] = True

    return {
        "success": True,
        "message": "Email verified successfully.",
    }


# =========================================================
# SUPABASE AUTH HELPERS
# =========================================================
# ---------------------------------------------------------
# Password sign-in over a shared HTTP session (speed)
# ---------------------------------------------------------
#
# new_auth_client() built a brand-new Supabase client (and a new HTTPS
# connection) on EVERY login. This calls Supabase Auth's password grant
# directly over one shared keep-alive session. It keeps no session state,
# so it is safe to share between users and threads.

_auth_http = requests.Session()
_auth_http.mount(
    "https://",
    HTTPAdapter(pool_connections=4, pool_maxsize=20),
)


class _AuthHttpError(RuntimeError):
    """Supabase Auth refused the request. The message carries the Supabase
    error code and 'status=<http status>', which authenticate() matches on
    (invalid_credentials, email_not_confirmed, status=429...)."""


def _password_sign_in(email: str, password: str) -> dict:
    """
    Check email + password with Supabase Auth.

    Returns {"user_id": <auth.users.id>, "access_token": <jwt>}.
    Raises _AuthHttpError when Supabase refuses, or another exception when
    it can't be reached (authenticate() treats those as 'not a wrong
    password' and refunds the attempt).
    """

    key = ANON_KEY or SERVICE_ROLE_KEY

    if not SUPABASE_URL or not key:
        raise DatabaseConfigError(
            "SUPABASE_URL and SUPABASE_KEY (or SUPABASE_SERVICE_ROLE_KEY) "
            "are required."
        )

    response = _auth_http.post(
        f"{SUPABASE_URL}/auth/v1/token",
        params={"grant_type": "password"},
        headers={"apikey": key, "Content-Type": "application/json"},
        json={"email": email, "password": password},
        timeout=15,
    )

    if response.status_code == 200:
        data = response.json()
        auth_user = data.get("user") or {}

        if not auth_user.get("id") or not data.get("access_token"):
            raise _AuthHttpError("unexpected_response status=502")

        return {
            "user_id": auth_user["id"],
            "access_token": data["access_token"],
        }

    try:
        body = response.json()
    except ValueError:
        body = {}

    code = body.get("error_code") or body.get("error") or ""
    message = (
        body.get("msg") or body.get("error_description") or body.get("message") or ""
    )

    # e.g. "invalid_credentials Invalid login credentials status=400"
    raise _AuthHttpError(f"{code} {message} status={response.status_code}")


def _prefetch_dashboard(role: str) -> None:
    """
    Speed: warm the shared dashboard cache while the browser is still
    switching from the login screen to the dashboard, so the dashboard's
    first request finds the data already loaded (or loading).

    Admin and Technician dashboards both read technician_service's data.
    Best effort: a failure here never affects the login.
    """

    role = str(role or "").strip().lower()

    if role not in (
        "admin",
        "administrator",
        "technician",
        "teacher",
    ):
        return

    def run() -> None:
        try:
            # Imported here: these services import auth_service.
            if role in ("admin", "administrator"):
                from . import admin_service
                admin_service.get_dashboard_data()
                
            elif role == "teacher":
                from . import teacher_service
                teacher_service._report_data()
                
            else:
                from . import technician_service
                technician_service.get_dashboard_data()
                
        except Exception:
            logger.exception("Dashboard prefetch failed.")

    threading.Thread(target=run, name="prefetch", daemon=True).start()

def _is_permission_error(error: Exception) -> bool:
    text = error_text(error).lower()

    return (
        "not allowed" in text
        or "not_admin" in text
        or "status=401" in text
        or "status=403" in text
        or "invalid jwt" in text
    )


def _create_auth_user(
    email: str,
    password: str,
) -> str:
    """
    Create the Supabase Auth account.

    The password belongs to Supabase Auth, NOT the Users table.

    Admin API is preferred because the email has already been
    verified through the application's verification process.

    If the service-role key is unavailable, sign_up() is used
    as a fallback.
    """

    try:
        response = get_client().auth.admin.create_user(
            {
                "email": email,
                "password": password,
                "email_confirm": True,
            }
        )

    except Exception as error:

        if not _is_permission_error(error):
            raise

        logger.warning(
            "Admin API not available "
            "(SUPABASE_SERVICE_ROLE_KEY may not be set); "
            "falling back to sign_up()."
        )

        response = new_auth_client().auth.sign_up(
            {
                "email": email,
                "password": password,
            }
        )

    if not response or not response.user:
        raise RuntimeError("Supabase returned no user.")

    return response.user.id


def _delete_auth_user(
    auth_user_id: str,
) -> None:
    """
    Delete the Supabase Auth user.

    Used as a rollback when the Auth account was created
    successfully but the corresponding Users row could not
    be created.
    """

    try:
        get_client().auth.admin.delete_user(auth_user_id)

    except Exception as error:
        logger.error(
            "Could not remove the Auth user "
            "(delete it in Supabase > Authentication > Users): %s",
            error_text(error),
        )


# =========================================================
# FIND AUTH USER ID
# =========================================================


def _find_auth_user_id(
    email: str,
    row: dict | None,
):
    """
    Return the Supabase Auth UUID associated with a Users row.

    PRIMARY:
        Users.AuthId

    LEGACY FALLBACK:
        Search Supabase Auth users by email.

    Users.UserId must NEVER be treated as a Supabase Auth UUID.
    """

    # -----------------------------------------------------
    # 1. Preferred relationship: Users.AuthId
    # -----------------------------------------------------

    if row:
        auth_id = row.get(users.AUTH_ID_COLUMN)

        if users.is_uuid(auth_id):
            return str(auth_id)

    # -----------------------------------------------------
    # 2. Legacy fallback: search Auth users by email
    # -----------------------------------------------------

    email = users.normalize_email(email)

    admin = get_client().auth.admin

    page = 1

    while page <= 50:

        batch = (
            admin.list_users(
                page=page,
                per_page=200,
            )
            or []
        )

        for auth_user in batch:

            auth_email = (
                (
                    getattr(
                        auth_user,
                        "email",
                        "",
                    )
                    or ""
                )
                .strip()
                .lower()
            )

            if auth_email == email:
                return auth_user.id

        if len(batch) < 200:
            break

        page += 1

    return None


# =========================================================
# GET APPLICATION USER
# =========================================================


def _get_application_user(
    auth_user_id: str,
    email: str,
):
    """
    Find the Users profile belonging to a Supabase Auth user.

    PRIMARY:
        Users.AuthId

    LEGACY FALLBACK:
        Users.Email

    If a Users row already contains an AuthId, it MUST match
    the authenticated Supabase Auth user's ID.
    """

    # -----------------------------------------------------
    # 1. Primary lookup: AuthId
    # -----------------------------------------------------

    row = users.get_user_by_auth_id(auth_user_id)

    if row:
        return row

    # -----------------------------------------------------
    # 2. Legacy fallback: Email
    # -----------------------------------------------------

    row = users.get_user_by_email(email)

    if not row:
        return None

    stored_auth_id = row.get(users.AUTH_ID_COLUMN)

    # If AuthId already exists, verify that it belongs
    # to the same authenticated user.
    if stored_auth_id:

        if str(stored_auth_id).lower() != str(auth_user_id).lower():
            logger.error(
                "AuthId mismatch for user %s: " "Users.AuthId=%s, auth.users.id=%s",
                email,
                stored_auth_id,
                auth_user_id,
            )

            return None

    return row


# =========================================================
# AUTH ERROR MESSAGE
# =========================================================


def _auth_error_message(
    error: Exception,
) -> str:
    """
    Convert a Supabase Auth exception into a
    user-safe message.
    """

    if isinstance(
        error,
        DatabaseConfigError,
    ):
        return (
            "The database connection isn't set up yet. "
            "Please contact the administrator."
        )

    text = error_text(error).lower()

    if (
        "already registered" in text
        or "already been registered" in text
        or "email_exists" in text
        or "user_already_exists" in text
    ):
        return (
            "An account with this email already exists. "
            "Try logging in, or ask the administrator "
            "to remove the old account."
        )

    if "database error" in text or "unexpected_failure" in text:
        return (
            "The login service couldn't save the new account "
            "(database trigger error). "
            "Please contact the administrator."
        )

    if "signups not allowed" in text or "signup_disabled" in text:
        return (
            "New sign-ups are turned off in Supabase. "
            "Please contact the administrator."
        )

    if "email_address_invalid" in text or (
        "email address" in text and "invalid" in text
    ):
        return "Supabase rejected this email address. " "Please use a different email."

    if "rate limit" in text or "status=429" in text:
        return (
            "Too many sign-ups were attempted. "
            "Please wait a few minutes and try again."
        )

    if "weak" in text or "password" in text:
        return (
            "That password was rejected. "
            "Please go back and choose a stronger password."
        )

    return "We couldn't create your account. " "Please try again later."


# =========================================================
# CREATE ACCOUNT
# =========================================================


def create_account(email: str):
    """
    Complete the registration process.

    Process:

    1. Get verified signup information.
    2. Check duplicate email.
    3. Resolve RoleId from the Role table.
    4. Determine account Status.
    5. Create Supabase Auth user.
    6. Insert Users row with AuthId.
    7. Roll back Auth user if Users insert fails.
    """

    email = users.normalize_email(email)

    signup = pending_signups.get(email)

    if not signup:
        return {
            "success": False,
            "error": ("Signup information was not found. " "Please start again."),
        }

    # -----------------------------------------------------
    # Email must already be verified.
    # -----------------------------------------------------

    if not signup.get("verified"):
        return {
            "success": False,
            "error": "Please verify your email first.",
        }

    # The password rules are enforced here too, so a request that skips
    # the sign-up form can't create an account with a weak password.
    valid, password_error = validate_password(signup.get("password"))

    if not valid:
        pending_signups.pop(email, None)

        return {
            "success": False,
            "error": password_error,
        }

    # -----------------------------------------------------
    # 1. Duplicate check
    # -----------------------------------------------------

    try:

        if email_taken(email):
            pending_signups.pop(
                email,
                None,
            )

            return {
                "success": False,
                "error": ("An account with this email " "already exists."),
            }

        # -------------------------------------------------
        # Determine initial status.
        #
        # Technician -> pending
        # Other allowed roles -> active
        # -------------------------------------------------

        requested_status = "pending" if signup["role"] in APPROVAL_ROLES else "active"

        status = users.status_value(requested_status)

        # -------------------------------------------------
        # Resolve RoleId from Role table.
        # -------------------------------------------------

        role_id = users.role_id_for(signup["role"])

        if role_id is None:

            logger.error(
                "No RoleId configured for role %r.",
                signup["role"],
            )

            return {
                "success": False,
                "error": (
                    "Registration isn't set up "
                    "for this role yet. "
                    "Please contact the administrator."
                ),
            }

    except DatabaseError as error:

        return {
            "success": False,
            "error": str(error),
        }

    # -----------------------------------------------------
    # 2. Create Supabase Auth user
    # -----------------------------------------------------

    try:

        auth_user_id = _create_auth_user(
            email,
            signup["password"],
        )

    except Exception as error:

        logger.error(
            "Supabase Auth user creation failed: %s",
            error_text(error),
        )

        return {
            "success": False,
            "error": _auth_error_message(error),
        }

    # -----------------------------------------------------
    # 3. Insert Users row
    # -----------------------------------------------------
    #
    # IMPORTANT:
    #
    # AuthId = Supabase auth.users.id
    #
    # UserId is generated by PostgreSQL.
    #
    # CreatedAt / UpdatedAt are handled by the database
    # defaults/repository.
    # -----------------------------------------------------

    try:

        row = users.create_user(
            email=email,
            first_name=signup["first_name"],
            last_name=signup["last_name"],
            department=signup["department"],
            role=signup["role"],
            status=status,
            contact_number=signup["contact_number"],
            auth_id=auth_user_id,
            role_id=role_id,
            # email_taken() was checked a moment ago, above.
            check_email=False,
        )

    except DatabaseError as error:

        # Roll back Supabase Auth account so an orphaned
        # authentication account is not left behind.

        _delete_auth_user(auth_user_id)

        return {
            "success": False,
            "error": str(error),
        }

    # -----------------------------------------------------
    # Verify the Users.AuthId relationship.
    # -----------------------------------------------------

    auth_id = row.get(users.AUTH_ID_COLUMN)

    if not auth_id:

        logger.error(
            "Login account created but Users.AuthId " "is missing for %s.",
            email,
        )

        # The Users row is already created but improperly
        # linked. Remove the Auth account to prevent an
        # unusable orphaned login.
        _delete_auth_user(auth_user_id)

        return {
            "success": False,
            "error": (
                "Your account is not correctly linked "
                "to the login service. "
                "Please contact the administrator."
            ),
        }

    # FIX:
    # The old version incorrectly referenced
    # response.user.id here.
    #
    # create_account() has no "response" variable.
    # The correct Auth ID is auth_user_id.

    if str(auth_id).lower() != str(auth_user_id).lower():

        logger.error(
            "AuthId mismatch for %s: " "Users.AuthId=%s, auth.users.id=%s",
            email,
            auth_id,
            auth_user_id,
        )

        return {
            "success": False,
            "error": (
                "Your account is not correctly linked "
                "to the login service. "
                "Please contact the administrator."
            ),
        }

    pending_signups.pop(
        email,
        None,
    )

    user = users.to_app_user(row)

    # Tell the admins (best effort; never fails the sign-up).
    try:
        from . import notification_service as notify

        name = (
            f"{user.get('first_name', '')} {user.get('last_name', '')}".strip() or email
        )
        details = f"{user.get('role') or signup['role']} · {user.get('department') or ''} · {email}"
        from .perf import background

        # Sent after the response, so the new user doesn't wait for it.
        if user["status"] == "pending":
            background(
                notify.notify_admins,
                "account",
                notify.message(f"Account request · {name}", details),
            )
        else:
            background(
                notify.notify_admins,
                "account",
                notify.message(f"New account · {name}", details),
            )
    except Exception as exc:
        logger.warning("Could not notify admins about the new account: %s", exc)

    return {
        "success": True,
        "message": "Account created successfully.",
        "pending": (user["status"] == "pending"),
        "user": user,
    }


# =========================================================
# LOGIN STATUS CHECK
# =========================================================


def _status_error(status: str):
    """
    Return None if the account is allowed to log in.
    Otherwise return the appropriate error message.
    """

    status = (status or "").strip().lower()

    if status in LOGIN_ALLOWED_STATUSES:
        return None

    if status == "pending":
        return "Your account is waiting for " "admin approval."

    if status in (
        "rejected",
        "declined",
        "denied",
    ):
        return "Your account request was rejected."

    if status in (
        "inactive",
        "disabled",
        "deactivated",
        "suspended",
        "blocked",
    ):
        return "Your account has been deactivated. " "Please contact the administrator."

    return "Your account is not active yet. " "Please contact the administrator."


# =========================================================
# LOGIN / AUTHENTICATE
# =========================================================


def authenticate(
    email: str,
    password: str,
):
    """
    Authenticate the user through Supabase Auth.

    Speed:
      * the Users row is read at the same time as the attempt-counter check
        (they don't depend on each other), instead of after the password check;
      * the password is checked over a shared keep-alive HTTP session
        (_password_sign_in) instead of building a new Supabase client;
      * the dashboard data starts loading right away (_prefetch_dashboard).

    Security is unchanged: the attempt is reserved BEFORE the password is
    checked, the profile is only used after the password is correct, and the
    Users.AuthId must still match the signed-in Supabase user.
    """

    email = _login_email(email)

    fixed_admin = _is_fixed_admin(email)

    # Start reading the Users row now; it runs while the attempt counter is
    # checked below. (The built-in Admin has no Users row.)
    profile_future = (
        None if fixed_admin else perf.submit(users.get_user_by_email, email)
    )

    # -----------------------------------------------------
    # 0. Password attempt limit (5 consecutive failures).
    # -----------------------------------------------------

    try:
        blocked = _login_begin(email)
    except _LoginLimitUnavailable:
        return {
            "success": False,
            "error": _LOGIN_UNAVAILABLE,
        }

    if blocked:
        return {
            "success": False,
            "error": blocked,
        }

    # -----------------------------------------------------
    # 1. Check password through Supabase Auth.
    # -----------------------------------------------------

    try:

        signed_in = _password_sign_in(email, password)

    except Exception as error:

        text = error_text(error).lower()

        if "invalid login credentials" in text or "invalid_credentials" in text:
            try:
                locked = _login_failed(email)
            except _LoginLimitUnavailable:
                locked = None

            return {
                "success": False,
                "error": locked or "Email or password is incorrect.",
            }

        # Anything else is not a wrong password: give the attempt back.
        _login_refund(email)

        if "not confirmed" in text or "email_not_confirmed" in text:
            return {
                "success": False,
                "error": (
                    "Your email isn't confirmed "
                    "in Supabase yet. "
                    "Please contact the administrator."
                ),
            }

        if "rate limit" in text or "status=429" in text:
            return {
                "success": False,
                "error": (
                    "Too many login attempts. "
                    "Please wait a few minutes "
                    "and try again."
                ),
            }

        logger.error(
            "Supabase sign-in failed: %s",
            error_text(error),
        )

        return {
            "success": False,
            "error": ("We couldn't log you in right now. " "Please try again later."),
        }

    # Correct password: reset the consecutive-failure counter
    # (after the response; the user doesn't wait for it).
    perf.background(_login_clear, email)

    auth_user_id = signed_in["user_id"]

    access_token = signed_in["access_token"]

    # -----------------------------------------------------
    # Fixed Admin
    # -----------------------------------------------------

    if fixed_admin:

        user = _fixed_admin_user(
            email,
            auth_user_id,
        )

        _remember_token(access_token, user)

        _prefetch_dashboard(user["role"])

        return {
            "success": True,
            "user": user,
            "access_token": access_token,
        }

    # -----------------------------------------------------
    # 2. Find application profile.
    #
    # The row was already requested by e-mail (profile_future). It is only
    # accepted when its AuthId matches the signed-in Supabase user (or is
    # still empty, as before). Otherwise the full lookup is used: AuthId
    # first, then the e-mail with the same AuthId check.
    # -----------------------------------------------------

    row = None

    try:
        row = profile_future.result()
    except DatabaseError:
        row = None  # the full lookup below tries again and reports the error

    if row:
        stored_auth_id = row.get(users.AUTH_ID_COLUMN)

        if stored_auth_id and str(stored_auth_id).lower() != str(auth_user_id).lower():
            row = None

    if not row:

        try:

            row = _get_application_user(
                auth_user_id=auth_user_id,
                email=email,
            )

        except DatabaseError as error:

            return {
                "success": False,
                "error": str(error),
            }

    if not row:

        logger.warning(
            "Authenticated Supabase user has no " "matching Users profile: %s",
            email,
        )

        return {
            "success": False,
            "error": (
                "No user profile was found for this login. "
                "Please contact the administrator."
            ),
        }

    # -----------------------------------------------------
    # 3. Convert database row to application user.
    # -----------------------------------------------------

    user = users.to_app_user(row)

    # -----------------------------------------------------
    # 4. Check account status.
    # -----------------------------------------------------

    status_error = _status_error(user["status"])

    if status_error:

        return {
            "success": False,
            "error": status_error,
        }

    _remember_token(access_token, user)

    _prefetch_dashboard(user["role"])

    return {
        "success": True,
        "user": user,
        "access_token": access_token,
    }


# =========================================================
# SIGNED-IN USER FROM ACCESS TOKEN
# =========================================================

_SESSION_EXPIRED = "Your session has expired. " "Please log out and log in again."


# ---------------------------------------------------------
# Token check cache (speed)
# ---------------------------------------------------------
#
# Every API request checks the access token. That used to mean: create a
# brand-new Supabase client, ask Supabase Auth about the token, then read the
# Users row - three slow steps on EVERY click. Now:
#
# * one Supabase client is reused for token checks (get_user(token) does not
#   store a session, so sharing it is safe), and
# * a token that checked out is remembered for TOKEN_CACHE_SECONDS, never
#   past the token's own expiry time.
#
# main.py calls forget_cached_tokens() after every change (POST / PATCH /
# DELETE ...), so a deactivated account or a changed role takes effect on the
# very next request.

TOKEN_CACHE_SECONDS = 60
_TOKEN_CACHE_MAX = 2000

_token_cache: dict[str, tuple[float, dict]] = {}
_token_lock = threading.Lock()
_token_client = None


def _token_auth_client():
    global _token_client

    if _token_client is None:
        _token_client = new_auth_client()

    return _token_client


def _token_key(token: str) -> str:
    import hashlib

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _token_expiry(token: str) -> float | None:
    """The token's own 'exp' time (seconds since 1970), or None.

    Only read to cap how long a result is cached - the token itself was
    already verified by Supabase Auth."""

    import base64
    import json

    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        exp = json.loads(base64.urlsafe_b64decode(payload)).get("exp")
        return float(exp) if exp else None
    except Exception:
        return None


def _remember_token(access_token: str | None, user: dict) -> None:
    """
    Speed: the login has just proven this token (Supabase signed it in) and
    read the user's profile, so the dashboard's first request doesn't need to
    ask Supabase Auth and the Users table again (two round trips). Same rules
    as user_from_token(): TOKEN_CACHE_SECONDS, never past the token's expiry.
    """

    import copy
    import time

    token = (access_token or "").strip()

    if not token or not user:
        return

    now = time.time()
    until = now + TOKEN_CACHE_SECONDS
    expiry = _token_expiry(token)

    if expiry is not None:
        until = min(until, expiry - 5)

    if until <= now:
        return

    with _token_lock:
        if len(_token_cache) >= _TOKEN_CACHE_MAX:
            _token_cache.clear()
        _token_cache[_token_key(token)] = (
            until,
            {"success": True, "user": copy.deepcopy(user)},
        )


def forget_cached_tokens() -> None:
    """Forget every remembered token check (called after any change)."""

    with _token_lock:
        _token_cache.clear()


def user_from_token(
    access_token: str,
):
    """
    Get the application user from a Supabase access token.

    Successful checks are remembered for a short time (see
    TOKEN_CACHE_SECONDS above); failures are never remembered.
    """

    import copy
    import time

    token = (access_token or "").strip()

    if not token:
        return _user_from_token_uncached(token)

    key = _token_key(token)
    now = time.time()

    with _token_lock:
        hit = _token_cache.get(key)

    if hit is not None and hit[0] > now:
        return copy.deepcopy(hit[1])

    result = _user_from_token_uncached(token)

    if result.get("success"):
        until = now + TOKEN_CACHE_SECONDS
        expiry = _token_expiry(token)

        if expiry is not None:
            until = min(until, expiry - 5)

        if until > now:
            with _token_lock:
                if len(_token_cache) >= _TOKEN_CACHE_MAX:
                    _token_cache.clear()
                _token_cache[key] = (until, copy.deepcopy(result))

    return result


def _user_from_token_uncached(
    access_token: str,
):
    """
    Get the application user from a Supabase access token.

    Flow:

        Access Token
             |
             v
        Supabase Auth
             |
             v
        auth.users.id
             |
             v
        Users.AuthId
             |
             v
        Application User
    """

    token = (access_token or "").strip()

    if not token:
        return {
            "success": False,
            "error": "Please log in first.",
        }

    # -----------------------------------------------------
    # Validate Supabase access token.
    # -----------------------------------------------------

    try:

        response = _token_auth_client().auth.get_user(token)

    except DatabaseConfigError as error:

        logger.error(
            "Token check failed: %s",
            error,
        )

        return {
            "success": False,
            "error": (
                "The database connection isn't "
                "set up yet. "
                "Please contact the administrator."
            ),
        }

    except Exception as error:

        text = error_text(error).lower()

        if any(
            word in text
            for word in (
                "expired",
                "invalid",
                "jwt",
                "401",
                "403",
            )
        ):
            return {
                "success": False,
                "error": _SESSION_EXPIRED,
            }

        logger.error(
            "Supabase token check failed: %s",
            error_text(error),
        )

        return {
            "success": False,
            "error": ("We couldn't check your login " "right now. Please try again."),
        }

    auth_user = getattr(
        response,
        "user",
        None,
    )

    if not auth_user:
        return {
            "success": False,
            "error": _SESSION_EXPIRED,
        }

    auth_user_id = auth_user.id

    email = users.normalize_email(
        getattr(
            auth_user,
            "email",
            "",
        )
        or ""
    )

    if not email:
        return {
            "success": False,
            "error": _SESSION_EXPIRED,
        }

    # -----------------------------------------------------
    # Fixed admin
    # -----------------------------------------------------

    if _is_fixed_admin(email):

        return {
            "success": True,
            "user": _fixed_admin_user(
                email,
                auth_user_id,
            ),
        }

    # -----------------------------------------------------
    # Primary lookup: AuthId
    # -----------------------------------------------------

    try:

        row = users.get_user_by_auth_id(auth_user_id)

        # Legacy fallback for existing rows where
        # AuthId has not yet been populated.
        if not row:

            row = users.get_user_by_email(email)

    except DatabaseError as error:

        return {
            "success": False,
            "error": str(error),
        }

    if not row:

        return {
            "success": False,
            "error": (
                "No user profile was found for this email. "
                "Please contact the administrator."
            ),
        }

    # -----------------------------------------------------
    # Verify AuthId.
    # -----------------------------------------------------

    auth_id = row.get(users.AUTH_ID_COLUMN)

    if not auth_id:

        return {
            "success": False,
            "error": (
                "Your account is not correctly linked "
                "to the login service. "
                "Please contact the administrator."
            ),
        }

    if str(auth_id).lower() != str(auth_user_id).lower():

        logger.error(
            "Token AuthId mismatch: " "Users.AuthId=%s, auth.users.id=%s",
            auth_id,
            auth_user_id,
        )

        return {
            "success": False,
            "error": (
                "Your account is not correctly linked "
                "to the login service. "
                "Please contact the administrator."
            ),
        }

    # -----------------------------------------------------
    # Convert to application user.
    # -----------------------------------------------------

    user = users.to_app_user(row)

    status_error = _status_error(user["status"])

    if status_error:

        return {
            "success": False,
            "error": status_error,
        }

    return {
        "success": True,
        "user": user,
    }


# =========================================================
# CHANGE PASSWORD
# =========================================================


def change_password(
    email: str,
    current_password: str,
    new_password: str,
):
    email = users.normalize_email(email)

    if not current_password:
        return {
            "success": False,
            "error": ("Enter your current password."),
        }

    valid, error = validate_password(new_password)

    if not valid:
        return {
            "success": False,
            "error": error,
        }

    if new_password == current_password:
        return {
            "success": False,
            "error": (
                "Choose a new password that is " "different from the current one."
            ),
        }

    # -----------------------------------------------------
    # 1. Verify current password (same 5-attempt limit as login).
    # -----------------------------------------------------

    try:
        blocked = _login_begin(email)
    except _LoginLimitUnavailable:
        return {
            "success": False,
            "error": _LOGIN_UNAVAILABLE,
        }

    if blocked:
        return {
            "success": False,
            "error": blocked,
        }

    try:

        signed_in = _password_sign_in(email, current_password)

    except Exception as error:

        text = error_text(error).lower()

        if "invalid login credentials" in text or "invalid_credentials" in text:
            try:
                locked = _login_failed(email)
            except _LoginLimitUnavailable:
                locked = None

            return {
                "success": False,
                "error": locked or ("Your current password is incorrect."),
            }

        _login_refund(email)

        if "rate limit" in text or "status=429" in text:
            return {
                "success": False,
                "error": (
                    "Too many attempts. " "Please wait a few minutes " "and try again."
                ),
            }

        logger.error(
            "Password check failed: %s",
            error_text(error),
        )

        return {
            "success": False,
            "error": (
                "We couldn't check your password " "right now. Please try again."
            ),
        }

    # _password_sign_in() raises when the password is wrong, so reaching this
    # line means it was correct (the old "if not auth_user" block is gone).
    auth_user = SimpleNamespace(id=signed_in["user_id"])

    _login_clear(email)
    
    # -----------------------------------------------------
    # 2. Update password in Supabase Auth.
    # -----------------------------------------------------

    try:

        get_client().auth.admin.update_user_by_id(
            auth_user.id,
            {"password": new_password},
        )

    except Exception as error:

        logger.error(
            "Password update failed "
            "(backend needs "
            "SUPABASE_SERVICE_ROLE_KEY): %s",
            error_text(error),
        )

        return {
            "success": False,
            "error": (
                "We couldn't update your password. " "Please contact the administrator."
            ),
        }

    return {
        "success": True,
        "message": "Password updated",
    }


# =========================================================
# CHANGE EMAIL (login + profile together)
# =========================================================
#
# The login checks the email stored in Supabase Auth (auth.users), while the
# app shows Users.Email. Both must change together, or the user would have to
# keep logging in with the old email.
# =========================================================


def _fail(message: str) -> dict:
    return {"success": False, "error": message}


def _set_auth_email(auth_user_id: str, email: str) -> None:
    get_client().auth.admin.update_user_by_id(
        auth_user_id,
        {"email": email, "email_confirm": True},
    )


def _change_email(row: dict, new_email: str, other_changes: dict | None = None) -> dict:
    """
    Change a user's email in Supabase Auth first, then in Users (together
    with any other Users changes). If the Users update fails, the Auth email
    is put back, so the two never disagree.
    """

    new_email = users.normalize_email(new_email)
    old_email = users.normalize_email(row.get("Email"))

    try:
        auth_user_id = _find_auth_user_id(old_email, row)
    except Exception as error:
        logger.error(
            "Could not find the login for %s: %s", old_email, error_text(error)
        )
        auth_user_id = None

    if not auth_user_id:
        return _fail(
            "This account has no login yet, so its email can't be changed. "
            "Please contact the administrator."
        )

    try:
        _set_auth_email(auth_user_id, new_email)
    except Exception as error:
        logger.error("Changing the login email failed: %s", error_text(error))
        text = error_text(error).lower()
        if "already" in text or "email_exists" in text:
            return _fail("An account with this email already exists.")
        return _fail(
            "We couldn't change the login email "
            "(the backend needs SUPABASE_SERVICE_ROLE_KEY). Please try again later."
        )

    def revert() -> None:
        try:
            _set_auth_email(auth_user_id, old_email)
        except Exception as error:
            logger.error(
                "Users update failed AND the login email could not be put back "
                "for %s - fix it in Supabase > Authentication > Users: %s",
                old_email,
                error_text(error),
            )

    try:
        updated = users.update_user(
            row.get("UserId"),
            {**(other_changes or {}), "email": new_email},
        )
    except (ValueError, DatabaseError) as error:
        revert()
        return _fail(str(error))

    if not updated:
        revert()
        return _fail("User not found.")

    return {"success": True, "user": users.to_app_user(updated)}


def change_own_email(
    email: str,
    current_password: str,
    new_email: str,
):
    """
    A signed-in user changes their own email. The current password is
    required (same 5-attempt limit as login).
    """

    email = users.normalize_email(email)
    new_email = users.normalize_email(new_email)

    if _is_fixed_admin(email):
        return _fail(
            "The built-in admin account's email is set in .env (ADMIN_EMAIL) "
            "and can't be changed here."
        )

    if not valid_email(new_email):
        return _fail("Enter a valid email address.")

    if new_email == email:
        return _fail("That is already your email address.")

    if not current_password:
        return _fail("Enter your current password.")

    try:
        if email_taken(new_email):
            return _fail("An account with this email already exists.")

        row = users.get_user_by_email(email)

    except DatabaseError as error:
        return _fail(str(error))

    if not row:
        return _fail("No user profile was found for this login.")

    # ---- confirm it's really them: check the current password ----

    try:
        blocked = _login_begin(email)
    except _LoginLimitUnavailable:
        return _fail(_LOGIN_UNAVAILABLE)

    if blocked:
        return _fail(blocked)
    
    try:
        signed_in = _password_sign_in(email, current_password)
    except Exception as error:
        text = error_text(error).lower()

        if "invalid login credentials" in text or "invalid_credentials" in text:
            try:
                locked = _login_failed(email)
            except _LoginLimitUnavailable:
                locked = None
            return _fail(locked or "Your current password is incorrect.")

        _login_refund(email)
        logger.error("Password check failed: %s", error_text(error))
        return _fail("We couldn't check your password right now. Please try again.")

    auth_user = SimpleNamespace(id=signed_in["user_id"])

    _login_clear(email)

    stored = row.get(users.AUTH_ID_COLUMN)

    if stored and str(stored).lower() != str(auth_user.id).lower():
        return _fail(
            "Your account is not correctly linked to the login service. "
            "Please contact the administrator."
        )

    result = _change_email(row, new_email)

    if result.get("success"):
        result["message"] = "Email updated. Use the new email the next time you log in."

    return result


# =========================================================
# DATABASE CHECK
# =========================================================


def database_problem():
    """
    None if the Users table can be read.
    Otherwise returns a short database error.
    """

    return users.check_connection()


def roles_problem():
    """
    Check whether the required application roles
    can be resolved through users_repository.
    """

    return users.roles_problem()


# =========================================================
# FORGOT PASSWORD - SEND RESET CODE
# =========================================================

_RESET_SENT_MESSAGE = (
    "If that email is registered, " "a 6-digit reset code is on its way."
)


def start_password_reset(email: str):
    email = users.normalize_email(email)

    if not valid_email(email):
        return {
            "success": False,
            "error": "Enter a valid email address.",
        }

    # Applied before the account lookup, to registered and unregistered
    # emails alike, so it doesn't reveal whether the email has an account.
    # No reset while the email is locked (checked for any email, so it
    # doesn't reveal whether an account exists).
    lock_error = _reset_lock_error(_login_email(email))

    if lock_error:
        return {
            "success": False,
            "error": lock_error,
        }

    issue_error = _code_issue_error("reset", email)

    if issue_error:
        return {
            "success": False,
            "error": issue_error,
        }

    try:

        row = users.get_user_by_email(email)

    except DatabaseError as error:

        return {
            "success": False,
            "error": str(error),
        }

    # Fixed admin has no Users row.
    if not row and _is_fixed_admin(email):
        row = {
            "Email": email,
            "FirstName": ((os.getenv("ADMIN_NAME") or "").strip() or "Administrator"),
        }

    # Do not reveal whether the email exists.
    if not row:

        return {
            "success": True,
            "message": _RESET_SENT_MESSAGE,
        }

    code = generate_verification_code()

    # Replaces (and so invalidates) any earlier reset code for this email.
    with _codes_lock:
        reset_codes[email] = {
            "code": code,
            "expires": (datetime.now(timezone.utc) + CODE_TTL),
            "attempts": 0,
            "row": row,
        }

    try:

        send_password_reset_email(
            recipient_email=email,
            code=code,
            first_name=(row.get("FirstName") or ""),
        )

    except EmailSendError as error:

        reset_codes.pop(
            email,
            None,
        )

        return {
            "success": False,
            "error": str(error),
        }

    except Exception:

        reset_codes.pop(
            email,
            None,
        )

        logger.exception("Unexpected error while sending " "the reset email.")

        return {
            "success": False,
            "error": ("We couldn't send the reset email. " "Please try again later."),
        }

    return {
        "success": True,
        "message": _RESET_SENT_MESSAGE,
    }


# =========================================================
# FORGOT PASSWORD - SET NEW PASSWORD
# =========================================================


def complete_password_reset(
    email: str,
    code: str,
    new_password: str,
):
    email = users.normalize_email(email)

    code = (code or "").strip()

    lock_error = _reset_lock_error(_login_email(email))

    if lock_error:
        return {
            "success": False,
            "error": lock_error,
        }

    valid, error = validate_password(new_password)

    if not valid:
        return {
            "success": False,
            "error": error,
        }

    # Save the row before _check_code removes the
    # reset_codes entry.
    row = (reset_codes.get(email) or {}).get("row")

    error = _check_code(
        reset_codes,
        email,
        code,
    )

    if error:
        return {
            "success": False,
            "error": error,
        }

    try:

        # -------------------------------------------------
        # Find Auth user.
        #
        # AuthId is preferred.
        # Email search is only a legacy fallback.
        # -------------------------------------------------

        auth_user_id = _find_auth_user_id(
            email,
            row,
        )

        if not auth_user_id:
            return {
                "success": False,
                "error": (
                    "This account has no login yet. "
                    "Please contact the administrator."
                ),
            }

        # -------------------------------------------------
        # Update password in Supabase Auth.
        # -------------------------------------------------

        get_client().auth.admin.update_user_by_id(
            auth_user_id,
            {"password": new_password},
        )

    except Exception as error:

        logger.error(
            "Password update failed "
            "(backend needs "
            "SUPABASE_SERVICE_ROLE_KEY): %s",
            error_text(error),
        )

        return {
            "success": False,
            "error": (
                "We couldn't update your password. " "Please contact the administrator."
            ),
        }

    # New password set: start the failed-password count fresh.
    _login_clear(_login_email(email))

    return {
        "success": True,
        "message": ("Your password has been updated. " "You can log in now."),
    }


# =========================================================
# ADMIN - USER MANAGEMENT
# =========================================================


def admin_list_users(
    status: str = None,
    role: str = None,
):
    """
    List Users table records through users_repository.
    """

    rows = users.list_users(
        status=status,
        role=role,
    )

    return {
        "success": True,
        "users": [users.to_app_user(row) for row in rows],
    }


def admin_get_user(user_id):
    """
    Get one application user by Users.UserId.
    """

    row = users.get_user_by_id(user_id)

    if not row:
        return {
            "success": False,
            "error": "User not found.",
        }

    return {
        "success": True,
        "user": users.to_app_user(row),
    }


def admin_update_user(
    user_id,
    changes: dict,
):
    """
    Update a Users table record.

    Field validation and schema restrictions are handled
    by users_repository.update_user().

    A changed email is also changed in Supabase Auth, so the user logs in
    with the new email.
    """

    if "email" in changes:

        try:
            current = users.get_user_by_id(user_id)
        except DatabaseError as error:
            return {"success": False, "error": str(error)}

        if not current:
            return {"success": False, "error": "User not found."}

        new_email = users.normalize_email(changes.get("email"))

        if new_email != users.normalize_email(current.get("Email")):

            if not valid_email(new_email):
                return {"success": False, "error": "Enter a valid email address."}

            if _is_fixed_admin(new_email):
                return {
                    "success": False,
                    "error": "An account with this email already exists.",
                }

            other = {k: v for k, v in changes.items() if k != "email"}

            return _change_email(current, new_email, other)

    try:

        row = users.update_user(
            user_id,
            changes,
        )

    except ValueError as error:

        return {
            "success": False,
            "error": str(error),
        }

    except DatabaseError as error:

        return {
            "success": False,
            "error": str(error),
        }

    if not row:

        return {
            "success": False,
            "error": "User not found.",
        }

    return {
        "success": True,
        "user": users.to_app_user(row),
    }


def admin_set_status(
    user_id,
    status: str,
):
    """
    Update a user's account status.

    Supported statuses:
        active
        pending
        rejected
        inactive
    """

    status = (status or "").strip().lower()

    allowed_statuses = {
        "active",
        "pending",
        "rejected",
        "inactive",
    }

    if status not in allowed_statuses:

        return {
            "success": False,
            "error": ("Status must be active, pending, " "rejected or inactive."),
        }

    try:

        row = users.update_status(
            user_id,
            status,
        )

    except DatabaseError as error:

        return {
            "success": False,
            "error": str(error),
        }

    if not row:

        return {
            "success": False,
            "error": "User not found.",
        }

    return {
        "success": True,
        "user": users.to_app_user(row),
    }


def admin_delete_user(
    user_id,
):
    """
    Delete an application user and its corresponding
    Supabase Auth account.

    Users.AuthId is used to identify the Supabase Auth
    account whenever possible.
    """

    # -----------------------------------------------------
    # Find Users row first.
    # -----------------------------------------------------

    row = users.get_user_by_id(user_id)

    if not row:

        return {
            "success": False,
            "error": "User not found.",
        }

    # -----------------------------------------------------
    # Get AuthId directly from Users.
    # -----------------------------------------------------

    auth_user_id = row.get(users.AUTH_ID_COLUMN)

    # -----------------------------------------------------
    # Delete Users row.
    # -----------------------------------------------------

    try:

        users.delete_user(user_id)

    except DatabaseError as error:

        return {
            "success": False,
            "error": str(error),
        }

    # -----------------------------------------------------
    # Delete corresponding Supabase Auth account.
    # -----------------------------------------------------

    try:

        if users.is_uuid(auth_user_id):

            _delete_auth_user(auth_user_id)

        else:

            # Legacy fallback for rows that still have
            # no AuthId.
            email = users.normalize_email(row.get("Email"))

            legacy_auth_id = _find_auth_user_id(
                email,
                row,
            )

            if legacy_auth_id:
                _delete_auth_user(legacy_auth_id)

    except Exception as error:

        logger.error(
            "Users row deleted, but the Auth login " "could not be removed: %s",
            error_text(error),
        )

    return {
        "success": True,
        "message": "User deleted.",
    }
