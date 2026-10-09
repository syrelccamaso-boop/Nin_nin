"""
Centrum Laboratory - registration, login and password reset.

Passwords live in Supabase Auth (the Users table has no password column).
Profile data - Role, RoleId, Status, names, department - lives in the
existing "Users" table and is read/written through users_repository.
"""

import logging
import os
import re
import secrets
import string

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

MAX_CODE_ATTEMPTS = 5

# Roles whose new accounts wait for admin approval.
APPROVAL_ROLES = ("Technician",)

# Status values that may log in (compared in lower case).
LOGIN_ALLOWED_STATUSES = {"active", "approved"}


# =========================================================
# FIXED ADMIN ACCOUNT (optional)
# =========================================================
# One admin login that needs no row in the Users table.
#
#   .env:  ADMIN_EMAIL=admin@yourschool.edu.ph   (required to turn this on)
#          ADMIN_USERNAME=admin                  (optional: log in with this instead)
#          ADMIN_NAME=Administrator              (optional: name shown on the dashboard)
#
# The password is NOT in .env or in the code: it is the password of the
# Supabase Auth user with ADMIN_EMAIL (Authentication > Users > Add user,
# "Auto Confirm User" on). Change it with "Forgot password?" on the login
# screen - the reset code is emailed to ADMIN_EMAIL.


def _fixed_admin_email() -> str:

    return users.normalize_email(os.getenv("ADMIN_EMAIL"))


def _is_fixed_admin(email: str) -> bool:

    admin_email = _fixed_admin_email()

    return bool(admin_email) and users.normalize_email(email) == admin_email


def _login_email(name: str) -> str:
    """The email to sign in with: ADMIN_USERNAME is swapped for ADMIN_EMAIL."""

    name = users.normalize_email(name)

    username = (os.getenv("ADMIN_USERNAME") or "").strip().lower()

    if username and name == username and _fixed_admin_email():

        return _fixed_admin_email()

    return name


def _fixed_admin_user(email: str, auth_user_id) -> dict:
    """Same keys as users.to_app_user(), so app.py and Admin.py work unchanged."""

    return {
        "id": auth_user_id,
        "user_id": auth_user_id,
        "email": email,
        "first_name": (os.getenv("ADMIN_NAME") or "").strip() or "Administrator",
        "last_name": "",
        "role_id": None,
        "role": "Admin",
        "department": "",
        "contact_number": "",
        "status": "active",
        "created_at": None,
        "auth_id": auth_user_id,
    }


# Temporary storage for sign-up verification codes
verification_codes = {}


# Temporary storage for signup information
# (in memory: cleared when the server restarts)
pending_signups = {}


# Temporary storage for password reset codes
reset_codes = {}


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

        return (False, "Password must be at least 8 characters.")

    if not any(character.isupper() for character in password):

        return (False, "Password must have at least 1 uppercase letter.")

    if not any(character.isdigit() for character in password):

        return (False, "Password must have at least 1 digit.")

    # Same character set the Streamlit form checks.
    if not any(character in string.punctuation for character in password):

        return (False, "Password must have at least 1 special character.")

    return True, None


# =========================================================
# CLEAN NAME
# =========================================================


# =========================================================
# EMAIL EXISTS  (raises DatabaseError if the database fails)
# =========================================================


def email_taken(email: str) -> bool:

    # The fixed admin email is always taken, so nobody can sign up with it.
    return _is_fixed_admin(email) or users.email_exists(email)


# =========================================================
# GENERATE 6-DIGIT CODE
# =========================================================


def generate_verification_code() -> str:

    return f"{secrets.randbelow(1_000_000):06d}"


# =========================================================
# SHARED CODE CHECK
# =========================================================


def _check_code(store: dict, email: str, entered_code: str):
    """Check a code kept in `store`. Returns an error message, or None if correct."""

    data = store.get(email)

    if not data:

        return "No verification code was found. " "Please request a new code."

    if datetime.now(timezone.utc) > data["expires"]:

        store.pop(email, None)

        return "Your verification code has expired. " "Please request a new code."

    if data["attempts"] >= MAX_CODE_ATTEMPTS:

        store.pop(email, None)

        return "Too many incorrect attempts. " "Please request a new code."

    if len(entered_code) != 6 or not entered_code.isdigit():

        data["attempts"] += 1

        return "Verification code must contain " "exactly 6 digits."

    if not secrets.compare_digest(data["code"], entered_code):

        data["attempts"] += 1

        return "The verification code is incorrect."

    store.pop(email, None)

    return None


# =========================================================
# SEND VERIFICATION CODE
# =========================================================


def start_email_verification(email: str, first_name: str = ""):

    email = users.normalize_email(email)

    if not valid_email(email):

        return {"success": False, "error": "Enter a valid email address."}

    # Duplicate check against the Users table
    try:

        if email_taken(email):

            return {
                "success": False,
                "error": "An account with this email already exists.",
            }

    except DatabaseError as error:

        return {"success": False, "error": str(error)}

    code = generate_verification_code()

    verification_codes[email] = {
        "code": code,
        "expires": datetime.now(timezone.utc) + CODE_TTL,
        "attempts": 0,
    }

    try:

        send_verification_email(recipient_email=email, code=code, first_name=first_name)

    except EmailSendError as error:

        # Don't leave a code stored if the email failed.
        verification_codes.pop(email, None)

        return {"success": False, "error": str(error)}

    except Exception:

        verification_codes.pop(email, None)

        logger.exception("Unexpected error while sending the verification email.")

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
        email=email, first_name=signup.get("first_name", "")
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
        "first_name": first_name.strip(),
        "last_name": last_name.strip(),
        "department": department,
        "role": role,
        "password": password,
        "contact_number": (contact_number or "").strip(),
        "verified": False,
    }


# =========================================================
# VERIFY CODE
# =========================================================


def verify_verification_code(email: str, entered_code: str):

    email = users.normalize_email(email)

    entered_code = (entered_code or "").strip()

    signup = pending_signups.get(email)

    # Already verified (e.g. account creation failed and the user
    # pressed Verify again) - don't ask for a new code.
    if signup and signup.get("verified") and email not in verification_codes:

        return {"success": True, "message": "Email verified successfully."}

    error = _check_code(verification_codes, email, entered_code)

    if error:

        return {"success": False, "error": error}

    if signup:

        signup["verified"] = True

    return {"success": True, "message": "Email verified successfully."}


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


def _create_auth_user(email: str, password: str) -> str:
    """Create the Supabase Auth user (holds the password) and return its id.

    Admin API first (service role key): the email is marked as confirmed,
    because the Brevo code already verified it, so Supabase sends no email
    of its own. Falls back to sign_up() on a throwaway client.
    """

    try:

        response = get_client().auth.admin.create_user(
            {"email": email, "password": password, "email_confirm": True}
        )

    except Exception as error:

        if not _is_permission_error(error):
            raise

        logger.warning(
            "Admin API not available (SUPABASE_SERVICE_ROLE_KEY not set); "
            "falling back to sign_up()."
        )

        response = new_auth_client().auth.sign_up(
            {"email": email, "password": password}
        )

    if not response or not response.user:
        raise RuntimeError("Supabase returned no user.")

    return response.user.id


def _delete_auth_user(auth_user_id: str) -> None:

    try:

        get_client().auth.admin.delete_user(auth_user_id)

    except Exception as error:

        logger.error(
            "Could not remove the Auth user (delete it in Supabase > "
            "Authentication > Users): %s",
            error_text(error),
        )


def _find_auth_user_id(email: str, row: dict | None):
    """Supabase Auth id for this email.

    Uses Users.AuthId when filled, or UserId if it holds the Auth uuid.
    Otherwise searches the Auth users with the admin API.
    """

    if row and users.is_uuid(row.get(users.AUTH_ID_COLUMN)):
        return row[users.AUTH_ID_COLUMN]

    if row and users.is_uuid(row.get("UserId")):
        return row["UserId"]

    admin = get_client().auth.admin
    page = 1

    while page <= 50:

        batch = admin.list_users(page=page, per_page=200) or []

        for auth_user in batch:

            if (getattr(auth_user, "email", "") or "").lower() == email:
                return auth_user.id

        if len(batch) < 200:
            break

        page += 1

    return None


def _auth_error_message(error: Exception) -> str:
    """Short, user-safe explanation of a Supabase Auth failure."""

    if isinstance(error, DatabaseConfigError):
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
            "Try logging in, or ask the administrator to remove the "
            "old account."
        )

    if "database error" in text or "unexpected_failure" in text:
        # Supabase Auth itself failed to save the user - almost always a
        # trigger on auth.users that writes to another table and errors.
        return (
            "The login service couldn't save the new account "
            "(database trigger error). Please contact the administrator."
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

    email = users.normalize_email(email)

    signup = pending_signups.get(email)

    if not signup:

        return {
            "success": False,
            "error": ("Signup information was not found. " "Please start again."),
        }

    # Only create accounts for emails that passed the code check.
    if not signup.get("verified"):

        return {"success": False, "error": "Please verify your email first."}

    # -----------------------------------------------------
    # 1) Duplicate check (again - another sign-up may have
    #    finished while this user was reading the code)
    # -----------------------------------------------------

    try:

        if email_taken(email):

            pending_signups.pop(email, None)

            return {
                "success": False,
                "error": "An account with this email already exists.",
            }

        status = users.status_value(
            "pending" if signup["role"] in APPROVAL_ROLES else "active"
        )

        role_id = users.role_id_for(signup["role"])

        if role_id is None:

            logger.error(
                "No RoleId configured for role %r - set ROLE_ID_%s in .env.",
                signup["role"],
                signup["role"].upper(),
            )

            return {
                "success": False,
                "error": (
                    "Registration isn't set up for this role yet. "
                    "Please contact the administrator."
                ),
            }

    except DatabaseError as error:

        return {"success": False, "error": str(error)}

    # -----------------------------------------------------
    # 2) Create the Supabase Auth user (password)
    # -----------------------------------------------------

    try:

        auth_user_id = _create_auth_user(email, signup["password"])

    except Exception as error:

        logger.error("Supabase Auth user creation failed: %s", error_text(error))

        return {"success": False, "error": _auth_error_message(error)}

    # -----------------------------------------------------
    # 3) Insert the Users row
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
            user_id=auth_user_id,
            auth_id=auth_user_id,
            role_id=role_id,
        )

    except DatabaseError as error:

        # Don't leave an Auth user without a Users row - otherwise the
        # next attempt fails with "already registered".
        _delete_auth_user(auth_user_id)

        return {"success": False, "error": str(error)}

    pending_signups.pop(email, None)

    user = users.to_app_user(row)

    return {
        "success": True,
        "message": "Account created successfully.",
        "pending": user["status"] == "pending",
        "user": user,
    }


# =========================================================
# LOGIN
# =========================================================


def _status_error(status: str):
    """None if this Status may log in, otherwise the message to show."""

    status = (status or "").strip().lower()

    if status in LOGIN_ALLOWED_STATUSES:
        return None

    if status == "pending":
        return "Your account is waiting for admin approval."

    if status in ("rejected", "declined", "denied"):
        return "Your account request was rejected."

    if status in ("inactive", "disabled", "deactivated", "suspended", "blocked"):
        return "Your account has been deactivated. " "Please contact the administrator."

    return "Your account is not active yet. " "Please contact the administrator."


def authenticate(email: str, password: str):

    email = _login_email(email)

    # -----------------------------------------------
    # 1) Check the password with Supabase Auth
    #    (throwaway client, so the shared one keeps
    #    using the server key)
    # -----------------------------------------------

    try:

        response = new_auth_client().auth.sign_in_with_password(
            {"email": email, "password": password}
        )

    except Exception as error:

        text = error_text(error).lower()

        if "not confirmed" in text or "email_not_confirmed" in text:

            return {
                "success": False,
                "error": (
                    "Your email isn't confirmed in Supabase yet. "
                    "Please contact the administrator."
                ),
            }

        if "invalid login credentials" in text or "invalid_credentials" in text:

            return {"success": False, "error": "Email or password is incorrect."}

        if "rate limit" in text or "status=429" in text:

            return {
                "success": False,
                "error": (
                    "Too many login attempts. "
                    "Please wait a few minutes and try again."
                ),
            }

        logger.error("Supabase sign-in failed: %s", error_text(error))

        return {
            "success": False,
            "error": ("We couldn't log you in right now. " "Please try again later."),
        }

    if not response or not response.user:

        return {"success": False, "error": "Email or password is incorrect."}

    # Fixed admin account: no Users row needed.
    if _is_fixed_admin(email):

        return {
            "success": True,
            "user": _fixed_admin_user(email, response.user.id),
            "access_token": response.session.access_token if response.session else None,
        }

    # -----------------------------------------------
    # 2) Read Role / RoleId / Status from Users
    # -----------------------------------------------

    try:

        row = users.get_user_by_email(email)

    except DatabaseError as error:

        return {"success": False, "error": str(error)}

    if not row:

        logger.warning("Login OK but no Users row for this email.")

        return {
            "success": False,
            "error": (
                "No user profile was found for this email. "
                "Please contact the administrator."
            ),
        }

    user = users.to_app_user(row)

    # -----------------------------------------------
    # 3) Check Status before allowing login
    # -----------------------------------------------

    status_error = _status_error(user["status"])

    if status_error:

        return {"success": False, "error": status_error}

    return {
        "success": True,
        "user": user,
        "access_token": response.session.access_token if response.session else None,
    }


# =========================================================
# SIGNED-IN USER FROM AN ACCESS TOKEN
# =========================================================
# /auth/login returns a Supabase access token. Dashboards send it back
# (Authorization: Bearer ...) so the backend knows who is calling.


_SESSION_EXPIRED = "Your session has expired. Please log out and log in again."


def user_from_token(access_token: str):
    """The logged-in user for a Supabase access token, with the same checks as login."""

    token = (access_token or "").strip()

    if not token:

        return {"success": False, "error": "Please log in first."}

    try:

        # Throwaway client, like authenticate(): the shared one keeps the server key.
        response = new_auth_client().auth.get_user(token)

    except DatabaseConfigError as error:

        logger.error("Token check failed: %s", error)

        return {
            "success": False,
            "error": (
                "The database connection isn't set up yet. "
                "Please contact the administrator."
            ),
        }

    except Exception as error:

        text = error_text(error).lower()

        if any(word in text for word in ("expired", "invalid", "jwt", "401", "403")):

            return {"success": False, "error": _SESSION_EXPIRED}

        logger.error("Supabase token check failed: %s", error_text(error))

        return {
            "success": False,
            "error": "We couldn't check your login right now. Please try again.",
        }

    auth_user = getattr(response, "user", None)

    email = users.normalize_email(getattr(auth_user, "email", "") or "")

    if not email:

        return {"success": False, "error": _SESSION_EXPIRED}

    if _is_fixed_admin(email):

        return {"success": True, "user": _fixed_admin_user(email, auth_user.id)}

    try:

        row = users.get_user_by_email(email)

    except DatabaseError as error:

        return {"success": False, "error": str(error)}

    if not row:

        return {
            "success": False,
            "error": (
                "No user profile was found for this email. "
                "Please contact the administrator."
            ),
        }

    user = users.to_app_user(row)

    status_error = _status_error(user["status"])

    if status_error:

        return {"success": False, "error": status_error}

    return {"success": True, "user": user}


# =========================================================
# CHANGE PASSWORD (signed in, knows the current password)
# =========================================================


def change_password(email: str, current_password: str, new_password: str):

    email = users.normalize_email(email)

    if not current_password:

        return {"success": False, "error": "Enter your current password."}

    valid, error = validate_password(new_password)

    if not valid:

        return {"success": False, "error": error}

    if new_password == current_password:

        return {
            "success": False,
            "error": "Choose a new password that is different from the current one.",
        }

    # 1) Check the current password with Supabase Auth (throwaway client)
    try:

        response = new_auth_client().auth.sign_in_with_password(
            {"email": email, "password": current_password}
        )

    except Exception as error:

        text = error_text(error).lower()

        if "invalid login credentials" in text or "invalid_credentials" in text:

            return {"success": False, "error": "Your current password is incorrect."}

        if "rate limit" in text or "status=429" in text:

            return {
                "success": False,
                "error": "Too many attempts. Please wait a few minutes and try again.",
            }

        logger.error("Password check failed: %s", error_text(error))

        return {
            "success": False,
            "error": "We couldn't check your password right now. Please try again.",
        }

    auth_user = getattr(response, "user", None)

    if not auth_user:

        return {"success": False, "error": "Your current password is incorrect."}

    # 2) Save the new password (same admin call as complete_password_reset)
    try:

        get_client().auth.admin.update_user_by_id(
            auth_user.id, {"password": new_password}
        )

    except Exception as error:

        logger.error(
            "Password update failed (the backend needs "
            "SUPABASE_SERVICE_ROLE_KEY for admin calls): %s",
            error_text(error),
        )

        return {
            "success": False,
            "error": (
                "We couldn't update your password. " "Please contact the administrator."
            ),
        }

    return {"success": True, "message": "Password updated"}


# =========================================================
# DATABASE CHECK (used by /health)
# =========================================================


def database_problem():
    """None if the Users table can be read, otherwise a short description."""

    return users.check_connection()


def roles_problem():
    """None if Teacher/Technician have a RoleId, otherwise what to add to .env."""

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

        return {"success": False, "error": "Enter a valid email address."}

    try:

        row = users.get_user_by_email(email)

    except DatabaseError as error:

        return {"success": False, "error": str(error)}

    # The fixed admin has no Users row; the reset still works because
    # complete_password_reset() finds its Supabase Auth login by email.
    if not row and _is_fixed_admin(email):

        row = {
            "Email": email,
            "FirstName": (os.getenv("ADMIN_NAME") or "").strip() or "Administrator",
        }

    # Same answer whether or not the email exists,
    # so the form can't be used to discover accounts.
    if not row:

        return {"success": True, "message": _RESET_SENT_MESSAGE}

    code = generate_verification_code()

    reset_codes[email] = {
        "code": code,
        "expires": datetime.now(timezone.utc) + CODE_TTL,
        "attempts": 0,
        "row": row,
    }

    try:

        send_password_reset_email(
            recipient_email=email, code=code, first_name=row.get("FirstName") or ""
        )

    except EmailSendError as error:

        reset_codes.pop(email, None)

        return {"success": False, "error": str(error)}

    except Exception:

        reset_codes.pop(email, None)

        logger.exception("Unexpected error while sending the reset email.")

        return {
            "success": False,
            "error": "We couldn't send the reset email. Please try again later.",
        }

    return {"success": True, "message": _RESET_SENT_MESSAGE}


# =========================================================
# FORGOT PASSWORD - SET NEW PASSWORD
# =========================================================


def complete_password_reset(email: str, code: str, new_password: str):

    email = users.normalize_email(email)

    code = (code or "").strip()

    valid, error = validate_password(new_password)

    if not valid:

        return {"success": False, "error": error}

    # Read the saved row before _check_code removes the entry.
    row = (reset_codes.get(email) or {}).get("row")

    error = _check_code(reset_codes, email, code)

    if error:

        return {"success": False, "error": error}

    try:

        auth_user_id = _find_auth_user_id(email, row)

        if not auth_user_id:

            return {
                "success": False,
                "error": (
                    "This account has no login yet. "
                    "Please contact the administrator."
                ),
            }

        # Needs the Supabase *service role* key on the backend.
        get_client().auth.admin.update_user_by_id(
            auth_user_id, {"password": new_password}
        )

    except Exception as error:

        logger.error(
            "Password update failed (the backend needs "
            "SUPABASE_SERVICE_ROLE_KEY for admin calls): %s",
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
        "message": "Your password has been updated. You can log in now.",
    }


# =========================================================
# ADMIN - USER MANAGEMENT (Users table CRUD)
# =========================================================


def admin_list_users(status: str = None, role: str = None):

    rows = users.list_users(status=status, role=role)

    return {"success": True, "users": [users.to_app_user(row) for row in rows]}


def admin_get_user(user_id):

    row = users.get_user_by_id(user_id)

    if not row:

        return {"success": False, "error": "User not found."}

    return {"success": True, "user": users.to_app_user(row)}


def admin_update_user(user_id, changes: dict):

    try:

        row = users.update_user(user_id, changes)

    except ValueError as error:

        return {"success": False, "error": str(error)}

    if not row:

        return {"success": False, "error": "User not found."}

    return {"success": True, "user": users.to_app_user(row)}


def admin_set_status(user_id, status: str):

    status = (status or "").strip().lower()

    if status not in ("active", "pending", "rejected", "inactive"):

        return {
            "success": False,
            "error": "Status must be active, pending, rejected or inactive.",
        }

    row = users.update_status(user_id, status)

    if not row:

        return {"success": False, "error": "User not found."}

    return {"success": True, "user": users.to_app_user(row)}


def admin_delete_user(user_id):
    """Delete the Users row and, if found, its Supabase Auth login."""

    row = users.get_user_by_id(user_id)

    if not row:

        return {"success": False, "error": "User not found."}

    users.delete_user(user_id)

    try:

        auth_user_id = _find_auth_user_id(users.normalize_email(row.get("Email")), row)

        if auth_user_id:
            _delete_auth_user(auth_user_id)

    except Exception as error:

        logger.error(
            "Users row deleted, but the Auth login could not be removed: %s",
            error_text(error),
        )

    return {"success": True, "message": "User deleted."}
