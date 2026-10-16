"""
Centrum Laboratory - Authentication Service

Responsibilities:
- Registration
- Email verification
- Supabase Auth account creation
- Login
- Access-token validation
- Password change
- Password reset
- Admin user management

Database architecture:

Supabase Auth
    auth.users.id
          |
          v
Users.AuthId
          |
          +-- Users.UserId
          +-- Users.Email
          +-- Users.FirstName
          +-- Users.LastName
          +-- Users.RoleId ------> Role.RoleId
          +-- Users.Department
          +-- Users.ContactNumber
          +-- Users.Status
          +-- Users.CreatedAt
          +-- Users.UpdatedAt

Passwords are stored ONLY in Supabase Auth.

Application profile information is stored in the "Users" table
and accessed through users_repository.py.
"""

import logging
import os
import re
import secrets
import string
import threading
from datetime import datetime, timedelta, timezone

from . import users_repository as users
from .database import DatabaseConfigError, get_client, new_auth_client
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


# =========================================================
# FIXED ADMIN ACCOUNT
# =========================================================
#
# Optional administrator account that does not require a
# corresponding row in the Users table.
#
# .env:
#
# ADMIN_EMAIL=admin@yourschool.edu.ph
# ADMIN_USERNAME=admin
# ADMIN_NAME=Administrator
#
# The password is stored in Supabase Auth.
# =========================================================


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

_LOGIN_UNAVAILABLE = (
    "Login is temporarily unavailable. Please try again later."
)


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
):
    email = users.normalize_email(email)

    if not valid_email(email):
        return {
            "success": False,
            "error": "Enter a valid email address.",
        }

    try:
        if email_taken(email):
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

    Supabase Auth verifies:
        Email + Password

    Users table provides:
        Role
        RoleId
        Status
        Department
        Name
        ContactNumber
        AuthId
    """

    email = _login_email(email)

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

        response = new_auth_client().auth.sign_in_with_password(
            {
                "email": email,
                "password": password,
            }
        )

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

    if not response or not response.user:
        try:
            locked = _login_failed(email)
        except _LoginLimitUnavailable:
            locked = None

        return {
            "success": False,
            "error": locked or ("Email or password is incorrect."),
        }

    # Correct password: reset the consecutive-failure counter.
    _login_clear(email)

    auth_user_id = response.user.id

    # -----------------------------------------------------
    # Fixed Admin
    # -----------------------------------------------------

    if _is_fixed_admin(email):

        return {
            "success": True,
            "user": _fixed_admin_user(
                email,
                auth_user_id,
            ),
            "access_token": (
                response.session.access_token if response.session else None
            ),
        }

    # -----------------------------------------------------
    # 2. Find application profile.
    #
    # AuthId is the preferred relationship.
    # -----------------------------------------------------

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

    return {
        "success": True,
        "user": user,
        "access_token": (response.session.access_token if response.session else None),
    }


# =========================================================
# SIGNED-IN USER FROM ACCESS TOKEN
# =========================================================

_SESSION_EXPIRED = "Your session has expired. " "Please log out and log in again."


def user_from_token(
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

        response = new_auth_client().auth.get_user(token)

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

        response = new_auth_client().auth.sign_in_with_password(
            {
                "email": email,
                "password": current_password,
            }
        )

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

    auth_user = getattr(
        response,
        "user",
        None,
    )

    if not auth_user:
        try:
            locked = _login_failed(email)
        except _LoginLimitUnavailable:
            locked = None

        return {
            "success": False,
            "error": locked or ("Your current password is incorrect."),
        }

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
    """

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