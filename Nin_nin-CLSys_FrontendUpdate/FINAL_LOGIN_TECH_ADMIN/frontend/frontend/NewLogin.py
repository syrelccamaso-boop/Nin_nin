"""
Centrum Laboratory - authentication screens (Log In, Sign Up, Reset password).

Sign-up flow:  form  ->  "Check your email" (6-digit code)  ->  "Request sent" / "Account created"
Reset flow:    email ->  6-digit code + new password  ->  back to Log In

All emails (verification codes and reset codes) are sent by the FastAPI
backend (backend/email_service.py). Accounts are stored in the Supabase
"Users" table and read through the backend - this file never talks to Brevo
or Supabase directly and needs none of their keys.

Run on its own to preview (from the project root):
                                python -m streamlit run frontend/NewLogin.py
Layout: a navy floor-plan panel on the left (desktop only) and the Log In /
Sign Up card on the right.

Use it in the main app (app.py):

    from frontend import NewLogin as login
    login.show("signup")                       # open a screen, e.g. from the homepage
    if not login.require_login(on_back=go_home):   # on_back adds "Back to home"
        st.stop()
    # ...the rest of your dashboard...

To log out (e.g. from the Settings page):   login.logout()

Admin helpers (for your admin page) - read/write the Supabase Users table
through the backend; need ADMIN_API_TOKEN in .env:
    login.list_pending_users()                 -> list of dicts waiting for approval
    login.set_user_status(user_id, "active")   -> approve  ("rejected" to decline)
                                                  returns None, or an error message

Needs Streamlit 1.39 or newer (container keys are used for styling).
"""

from __future__ import annotations

import base64
import functools
import hashlib
import hmac
import html
import logging
import mimetypes
import re
import secrets
import string
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

# The .env file sits in the project root, one level above frontend/. Load it by
# absolute path so it is found no matter which folder Streamlit is started from.
load_dotenv(
    Path(__file__).resolve().parent.parent / ".env"
)  # only for optional frontend settings such as BACKEND_URL

from frontend.backend_client import (  # noqa: E402  (after load_dotenv on purpose)
    create_account,
    email_exists,
    list_users as backend_list_users,
    login_user,
    request_password_reset as backend_request_password_reset,
    resend_verification_code,
    reset_password as backend_reset_password,
    signup_user,
    update_user_status as backend_update_user_status,
    verify_verification_code,
)

logger = logging.getLogger("centrum.login")

# ---------------------------------------------------------------------------
# Config - change these to match your project
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent  # CL Monitoring System/ (where app.py and .env are)

# Optional campus photo shown softly behind the navy floor-plan panel. Only the
# file name matters: if it isn't at this exact path, the page also looks in the
# project root, ./assets and the folders one or two levels below the project
# root (e.g. static/, images/). If none is found the panel is plain navy.
BG_IMAGE = BASE_DIR / "isu.jpg"

MIN_PASSWORD_LENGTH = 8

APP_SUBTITLE = "Computer Monitoring Management System"
ROLES = ("Teacher", "Technician")
DEPARTMENTS = ("CCSICT", "CAS", "CED", "CBAPA", "CON", "CA", "COE")

# Roles whose new accounts must be confirmed by an admin before they can log in.
APPROVAL_ROLES = ("Technician",)

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE_RE = re.compile(r"^(?:\+63|0)9\d{9}$")  # 09XXXXXXXXX or +639XXXXXXXXX

_GENERIC_ERROR = "Something went wrong. Please try again."


# ---------------------------------------------------------------------------
# Legacy in-memory prototype store.
#
# Sign up, log in and password reset go through the FastAPI backend and the
# Supabase Users table. create_user / authenticate below are kept only so old
# imports keep working; they do NOT see Supabase accounts.
# ---------------------------------------------------------------------------
@st.cache_resource
def _store() -> dict:
    return {"users": {}, "next_id": 1}


def _hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return salt.hex(), digest.hex()


def _user_dict(user: dict) -> dict:
    """The user without the password fields."""
    return {k: v for k, v in user.items() if k not in ("pw_salt", "pw_hash")}


def authenticate(email: str, password: str) -> dict | None:
    """(Legacy, in-memory) Return the user dict if the credentials are right."""
    user = _store()["users"].get(email.lower())
    if user is None:
        _hash_password(password)  # keep timing similar for unknown emails
        return None
    _, digest = _hash_password(password, bytes.fromhex(user["pw_salt"]))
    if not hmac.compare_digest(digest, user["pw_hash"]):
        return None
    return _user_dict(user)


def create_user(
    role, first_name, last_name, department, email, password, contact_number=""
) -> str | None:
    """(Legacy, in-memory) Create an account. Returns an error message, or None."""
    store = _store()
    if email.lower() in store["users"]:
        return "An account with this email already exists."
    salt, digest = _hash_password(password)
    store["users"][email.lower()] = {
        "id": store["next_id"],
        "role": role,
        "first_name": first_name,
        "last_name": last_name,
        "department": department,
        "email": email,
        "contact_number": contact_number,
        "status": "pending" if role in APPROVAL_ROLES else "active",
        "pw_salt": salt,
        "pw_hash": digest,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    store["next_id"] += 1
    return None


def list_pending_users() -> list[dict]:
    """Accounts in the Users table waiting for admin approval.

    Returns [] if the backend can't be reached (the reason is logged).
    """
    result = backend_list_users(status="pending")
    if not result.get("success"):
        logger.error("Could not load pending users: %s", result.get("error"))
        return []
    return result.get("users") or []


def set_user_status(user_id, status: str) -> str | None:
    """Approve ('active') or decline ('rejected') an account in the Users table.

    Returns None on success, otherwise a short error message to show.
    """
    if status not in ("active", "pending", "rejected", "inactive"):
        raise ValueError(f"Unknown status: {status}")
    result = backend_update_user_status(user_id, status)
    if not result.get("success"):
        return result.get("error") or _GENERIC_ERROR
    return None


# ---------------------------------------------------------------------------
# Backend-backed helpers
# ---------------------------------------------------------------------------
def email_taken(email: str) -> bool:
    """Ask the backend (Supabase) whether the email is already registered."""
    return email_exists(email.strip().lower())


def request_password_reset(email: str) -> dict:
    """Ask the backend to email a 6-digit reset code (silent if not registered)."""
    return backend_request_password_reset(email.strip().lower())


def _password_error(password: str) -> str | None:
    """Same rules as the backend. Returns an error message, or None if OK."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Use at least {MIN_PASSWORD_LENGTH} characters for your password."
    if not any(char.isupper() for char in password):
        return "Password should have at least 1 uppercase letter."
    if not any(char.isdigit() for char in password):
        return "Password should have at least 1 digit."
    if not any(char in string.punctuation for char in password):
        return "Password should have at least 1 special character."
    return None


# ---------------------------------------------------------------------------
# Session state + callbacks
# ---------------------------------------------------------------------------
ss = st.session_state

_SIGNUP_FIELDS = (
    "su_first",
    "su_last",
    "su_dept",
    "su_email",
    "su_contact",
    "su_password",
    "su_confirm",
    "su_code",
)

_RESET_FIELDS = ("reset_email", "rs_code", "rs_password", "rs_confirm")


def _init_state() -> None:
    ss.setdefault("authenticated", False)
    ss.setdefault("auth_user", None)
    ss.setdefault("auth_token", None)  # Supabase access token from /auth/login
    ss.setdefault("auth_remember", False)
    ss.setdefault("auth_view", "login")  # "login" | "signup" | "reset"
    ss.setdefault("auth_notice", None)  # ("err" | "ok", message)
    ss.setdefault("signup_role", None)
    ss.setdefault("signup_step", "form")  # "form" | "verify" | "done"
    ss.setdefault(
        "signup_data", None
    )  # details typed on the form, kept while verifying
    ss.setdefault("signup_done", None)
    ss.setdefault("reset_step", "email")  # "email" | "code"
    ss.setdefault("reset_target", "")  # email the reset code was requested for


def _notify(kind: str, message) -> None:
    ss.auth_notice = (kind, str(message or _GENERIC_ERROR))


def _safe_callback(func):
    """Show a short message instead of a Streamlit traceback if a callback fails."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception:
            logger.exception("Error in %s", func.__name__)
            _notify("err", _GENERIC_ERROR)
            return None

    return wrapper


def _reset_signup() -> None:
    ss.signup_role = None
    ss.signup_step = "form"
    ss.signup_data = None
    ss.signup_done = None
    for key in _SIGNUP_FIELDS:
        ss.pop(key, None)


def _reset_password_state() -> None:
    ss.reset_step = "email"
    ss.reset_target = ""
    for key in _RESET_FIELDS:
        ss.pop(key, None)


def _go(view: str) -> None:
    ss.auth_view = view
    ss.auth_notice = None
    _reset_signup()
    _reset_password_state()


def show(view: str = "login") -> None:
    """Open the Log In ("login") or Sign Up ("signup") screen, e.g. from the homepage."""
    _init_state()
    _go("signup" if view == "signup" else "login")


def _set_role(role: str) -> None:
    ss.signup_role = role


@_safe_callback
def _do_login():

    ss.auth_notice = None

    email = (ss.get("login_email") or "").strip()

    password = ss.get("login_password") or ""

    # Check empty fields
    if not email or not password:

        return _notify("err", "Enter both your email and password.")

    if not _EMAIL_RE.match(email):

        return _notify("err", "Enter a valid email address.")

    # Send login request to backend
    result = login_user(email, password)

    # Backend says login failed
    if not result.get("success"):

        return _notify("err", result.get("error"))

    # The account row from the Supabase "Users" table must be there and have a role,
    # otherwise the dashboards can't open (this was the "Users table error").
    from frontend import ui  # local import: ui has no login code

    user = result.get("user")
    if not isinstance(user, dict) or not user:
        logger.error("Login succeeded but the backend sent no user row for %s", email)
        return _notify("err", "You were signed in, but your account details couldn't be read from the Users "
                              "table. Please contact the administrator.")
    info = ui.normalize_user(user)
    if info["role"].lower() not in ("admin", "administrator", "teacher", "technician"):
        logger.error("User %s has no usable role in the Users table: %r", email, info["role"])
        return _notify("err", "Your account has no role yet in the Users table, so no dashboard can open. "
                              "Please contact the administrator.")
    if info["status"] in ("pending",):
        return _notify("err", "Your account is waiting for the admin's approval. You can log in once it's confirmed.")
    if info["status"] in ("rejected", "inactive", "disabled", "cancelled"):
        return _notify("err", "This account is not active. Please contact the administrator.")

    # Login successful
    ss.authenticated = True

    ss.auth_user = {**user, "role": info["role"]}

    # Dashboards send this back to the backend so it knows who is calling.
    ss.auth_token = result.get("access_token")

    ss.auth_remember = bool(ss.get("login_remember"))

    ss.login_password = ""

    ss["cl_welcome"] = info["name"]


# --- sign-up: step 1 (details) ------------------------------------------------
@_safe_callback
def _do_signup() -> None:
    """Validate sign-up details, then ask the backend to save them and email a code."""

    ss.auth_notice = None

    # ============================================================
    # COLLECT SIGN-UP DATA
    # ============================================================
    data = {
        "first": (ss.get("su_first") or "").strip(),
        "last": (ss.get("su_last") or "").strip(),
        "dept": ss.get("su_dept"),
        "email": (ss.get("su_email") or "").strip().lower(),
        "contact": (ss.get("su_contact") or "").strip(),
        "password": ss.get("su_password") or "",
        "confirm": ss.get("su_confirm") or "",
    }

    role = ss.signup_role

    # ============================================================
    # VALIDATION
    # ============================================================

    if not role:
        return _notify("err", "Pick your role first: Teacher or Technician.")

    if not (
        data["first"]
        and data["last"]
        and data["dept"]
        and data["email"]
        and data["password"]
        and data["confirm"]
    ):
        return _notify("err", "Fill in every field except the contact number.")

    # Validate names (letters, spaces, hyphens, apostrophes)
    name_pattern = r"^[A-Za-z]+(?:[ '-][A-Za-z]+)*$"

    if not re.fullmatch(name_pattern, data["first"]):
        return _notify(
            "err",
            "First name should contain letters, spaces, hyphens, or apostrophes only.",
        )

    if not re.fullmatch(name_pattern, data["last"]):
        return _notify(
            "err",
            "Last name should contain letters, spaces, hyphens, or apostrophes only.",
        )

    data["first"] = data["first"].title()
    data["last"] = data["last"].title()

    # Validate email
    if not _EMAIL_RE.match(data["email"]):
        return _notify("err", "Enter a valid email address.")

    # Validate contact number
    if data["contact"]:
        compact = re.sub(r"[\s\-()]", "", data["contact"])

        if not _PHONE_RE.match(compact):
            return _notify("err", "Enter a valid mobile number, like 09XX XXX XXXX.")

        data["contact"] = compact

    # Validate password
    error = _password_error(data["password"])
    if error:
        return _notify("err", error)

    # Confirm password
    if data["password"] != data["confirm"]:
        return _notify("err", "The two passwords don't match.")

    # Check if email already exists (the backend checks again)
    if email_taken(data["email"]):
        return _notify("err", "An account with this email already exists.")

    # ============================================================
    # SAVE DETAILS ON THE BACKEND + SEND 6-DIGIT CODE BY EMAIL
    # ============================================================

    result = signup_user(
        email=data["email"],
        first_name=data["first"],
        last_name=data["last"],
        department=data["dept"],
        role=role,
        password=data["password"],
        contact_number=data["contact"],
    )

    if not result.get("success"):
        return _notify("err", result.get("error"))

    # Kept so "Edit details" can refill the form.
    ss.signup_data = data

    # ============================================================
    # SHOW VERIFICATION SCREEN
    # ============================================================

    ss.signup_step = "verify"


# --- sign-up: step 2 (email code) -----------------------------------------------
@_safe_callback
def _do_verify() -> None:
    ss.auth_notice = None
    data = ss.get("signup_data")
    if not data:
        return _go("signup")

    entered = (ss.get("su_code") or "").strip()
    if not entered:
        return _notify("err", "Enter the verification code.")
    if len(entered) != 6 or not entered.isdigit():
        return _notify("err", "Enter the 6-digit code.")

    # 1) The backend checks the code (expiry + attempt limit live there).
    result = verify_verification_code(data["email"], entered)
    if not result.get("success"):
        return _notify("err", result.get("error"))

    # 2) The backend creates the Supabase account from the saved details.
    result = create_account(data["email"])
    if not result.get("success"):
        return _notify("err", result.get("error"))

    user = result.get("user") or {}
    pending = result.get("pending")
    if pending is None:
        status = user.get("status")
        pending = (
            status == "pending" if status else ss.signup_role in APPROVAL_ROLES
        )

    ss.signup_done = {
        "first": data["first"],
        "role": ss.signup_role,
        "pending": bool(pending),
    }

    ss.signup_data = None
    ss.signup_step = "done"


def _restore_form() -> None:
    """Put the typed details back in the form (widgets forget their values when hidden)."""
    d = ss.get("signup_data") or {}
    ss.su_first = d.get("first", "")
    ss.su_last = d.get("last", "")
    ss.su_dept = d.get("dept")
    ss.su_email = d.get("email", "")
    ss.su_contact = d.get("contact", "")
    ss.su_password = d.get("password", "")
    ss.su_confirm = d.get("confirm", "")


def _edit_details() -> None:
    _restore_form()
    ss.auth_notice = None
    ss.signup_step = "form"


@_safe_callback
def _resend_code() -> None:
    data = ss.get("signup_data")
    if not data:
        return _go("signup")

    result = resend_verification_code(data["email"], data.get("first", ""))

    ss.su_code = ""

    if not result.get("success"):
        return _notify("err", result.get("error"))

    _notify("ok", "We sent you a new code.")


# --- forgot password ------------------------------------------------------------
@_safe_callback
def _do_reset() -> None:
    ss.auth_notice = None
    email = (ss.get("reset_email") or "").strip().lower()
    if not email:
        return _notify("err", "Enter your email address.")
    if not _EMAIL_RE.match(email):
        return _notify("err", "Enter a valid email address.")

    result = request_password_reset(email)
    if not result.get("success"):
        return _notify("err", result.get("error"))

    ss.reset_target = email
    ss.reset_step = "code"
    _notify("ok", "If that email is registered, a 6-digit reset code is on its way.")


@_safe_callback
def _resend_reset_code() -> None:
    email = ss.get("reset_target") or ""
    if not email:
        return _go("reset")

    result = request_password_reset(email)

    ss.rs_code = ""

    if not result.get("success"):
        return _notify("err", result.get("error"))

    _notify("ok", "If that email is registered, we sent a new code.")


@_safe_callback
def _do_reset_confirm() -> None:
    ss.auth_notice = None
    email = ss.get("reset_target") or ""
    if not email:
        return _go("reset")

    code = (ss.get("rs_code") or "").strip()
    password = ss.get("rs_password") or ""
    confirm = ss.get("rs_confirm") or ""

    if not code or not password or not confirm:
        return _notify("err", "Enter the code and your new password twice.")
    if len(code) != 6 or not code.isdigit():
        return _notify("err", "Enter the 6-digit code.")

    error = _password_error(password)
    if error:
        return _notify("err", error)
    if password != confirm:
        return _notify("err", "The two passwords don't match.")

    result = backend_reset_password(email, code, password)
    if not result.get("success"):
        return _notify("err", result.get("error"))

    _go("login")
    _notify("ok", "Your password has been updated. You can log in now.")


def logout() -> None:
    """Sign the user out and show the login screen again."""
    ss.authenticated = False
    ss.auth_user = None
    ss.auth_token = None
    ss.auth_view = "login"
    ss.auth_notice = ("ok", "You have been logged out.")
    st.rerun()


# ---------------------------------------------------------------------------
# Assets
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def _file_data_uri(path: str, mtime: float) -> str:
    mime = mimetypes.guess_type(path)[0] or "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(Path(path).read_bytes()).decode()


def _find_image(preferred: Path, hints: tuple[str, ...]) -> Path | None:
    if preferred.is_file():
        return preferred
    # same file name in ./assets or up to two folders below the project root
    for root in (BASE_DIR, PROJECT_DIR):
        for pattern in (
            f"assets/{preferred.name}",
            f"*/{preferred.name}",
            f"*/*/{preferred.name}",
        ):
            match = next(root.glob(pattern), None)
            if match and match.is_file():
                return match
    for folder in (BASE_DIR / "assets", BASE_DIR, PROJECT_DIR / "assets", PROJECT_DIR):
        if not folder.is_dir():
            continue
        for f in sorted(folder.iterdir()):
            if f.suffix.lower() in _IMAGE_EXTS and any(
                h in f.stem.lower() for h in hints
            ):
                return f
    return None


# ---------------------------------------------------------------------------
# Styling
# ---------------------------------------------------------------------------
_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Poppins:wght@500;600;700;800&family=Open+Sans:wght@400;500;600;700&display=swap');
:root { --blue: #2d6fe3; --blue-dk: #1d4ed8; --blue-soft: #eaf1fd; --navy: #14213d; --navy-2: #0f1a33;
        --muted: #5b6472; --faint: #8b93a1; --line: #e3e7ee; --panel: 46vw; }

/* --- page chrome ----------------------------------------------------------- */
[data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"],
[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"],
[data-testid="collapsedControl"], #MainMenu, footer { display: none !important; }
.stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"] {
  background: radial-gradient(700px 500px at 78% 30%, #eaf1fd 0%, rgba(234, 241, 253, 0) 70%), #f3f5f9 !important; }
html, body, .stApp, .stApp p, .stApp label, .stApp input, .stApp button {
  font-family: 'Open Sans', 'Segoe UI', Roboto, Arial, sans-serif; }

/* --- navy floor-plan panel (left) ---------------------------------------- */
.cl-panel { position: fixed; left: 0; top: 0; bottom: 0; width: var(--panel); z-index: 0; overflow: hidden;
  background: __PANEL_BG__; color: #c7d2e8; display: flex; flex-direction: column; padding: 40px 48px; }
.cl-panel-body { margin: auto 0; max-width: 560px; }
.cl-pill { display: inline-flex; align-items: center; gap: 8px; background: rgba(91, 147, 245, .16); color: #8fb3f7;
  font: 700 11.5px 'Poppins', sans-serif; letter-spacing: .08em; padding: 7px 14px; border-radius: 999px; }
.cl-pill i { width: 7px; height: 7px; border-radius: 50%; background: #5b93f5; }
.cl-panel h1 { font: 800 clamp(28px, 2.7vw, 42px)/1.12 'Poppins', sans-serif; color: #fff; margin: 18px 0 14px; letter-spacing: -.01em; padding: 0; }
.cl-panel h1 span { color: #5b93f5; }
.cl-panel p { font-size: 15px; line-height: 1.6; color: #b9c6e0; margin: 0 0 8px; max-width: 460px; }
.cl-map-wrap { position: relative; width: min(100%, 44vh, 420px); margin: 22px 0 0; }
.cl-map { width: 100%; height: auto; display: block; }
.cl-pc { fill: #5b7fc4; } .cl-rep { fill: #f5a524; animation: clBlink 1.6s ease-in-out infinite; } .cl-fix { fill: #e5484d; }
.cl-lbl { font: 700 13px 'Poppins', sans-serif; letter-spacing: .28em; fill: #6f7fa3; }
.cl-ping { transform-origin: 300px 300px; transform-box: view-box; animation: clPing 2.4s ease-out infinite; }
@keyframes clPing { 0% { transform: scale(1); opacity: .8; } 100% { transform: scale(3.2); opacity: 0; } }
@keyframes clBlink { 50% { opacity: .35; } }
.cl-legend { display: flex; gap: 16px; flex-wrap: wrap; font-size: 12px; color: #93a1bd; margin-top: 12px; }
.cl-legend i { display: inline-block; width: 11px; height: 8px; border-radius: 2px; margin-right: 6px; }
.cl-roles { display: flex; gap: 10px; flex-wrap: wrap; margin-top: auto; padding-top: 22px; font-size: 13px; color: #93a1bd; }
.cl-roles span { border: 1px solid rgba(255, 255, 255, .12); border-radius: 999px; padding: 6px 12px; }
@media (max-height: 760px) { .cl-map-wrap { display: none; } }

/* --- the white card (right) --------------------------------------------- */
[data-testid="stMainBlockContainer"], .stMainBlockContainer, .block-container {
  position: relative; z-index: 1;
  max-width: 470px !important;
  margin: 6vh auto 6vh max(calc(var(--panel) + (100vw - var(--panel) - 470px) / 2), calc(var(--panel) + 24px)) !important;
  padding: 30px 34px 34px !important;
  background: #fff; border-radius: 24px; border: 1px solid #e6e9ef;
  box-shadow: 0 30px 70px rgba(20, 33, 61, .10);
}
[data-testid="stMainBlockContainer"] [data-testid="stVerticalBlock"] { gap: .72rem; }
[data-testid="stMainBlockContainer"] [data-testid="stElementContainer"],
[data-testid="stMainBlockContainer"] .element-container { width: 100% !important; max-width: 100% !important; }
[data-testid="stMainBlockContainer"] [data-testid="stButton"] { width: 100%; }

/* small screens: panel off, card centred, subtitle shown in the card */
.cx-head { display: none; }
@media (max-width: 900px) {
  .cl-panel { display: none; }
  .cx-head { display: block; }
  [data-testid="stMainBlockContainer"], .stMainBlockContainer, .block-container {
    margin: 4vh auto !important; }
}
@media (max-width: 520px) {
  [data-testid="stMainBlockContainer"], .stMainBlockContainer, .block-container {
    margin: 2vh 12px !important; padding: 24px 20px 26px !important; max-width: none !important; border-radius: 20px; }
}

/* --- header text ---------------------------------------------------------- */
.cx-head { text-align: center; padding-bottom: 6px; }
.cx-sub { font-size: 10.5px; font-weight: 600; color: #5b6472; margin-top: 6px; letter-spacing: .02em; }
.cx-title { font: 700 24px/1.2 'Poppins', sans-serif; color: var(--navy); margin-top: 6px; }
.cx-desc { font-size: 13.5px; color: var(--muted); margin-top: 4px; padding-bottom: 6px; }
.cx-badge { width: 68px; height: 68px; border-radius: 50%; margin: 10px auto 4px; display: flex; align-items: center; justify-content: center; }
.cx-badge svg { width: 28px; height: 28px; }
.cx-badge.blue  { background: var(--blue-soft); color: var(--blue); box-shadow: 0 0 0 8px #f4f8fe; }
.cx-badge.green { background: #e3f4ea; color: #0c8a3e; box-shadow: 0 0 0 8px #f2faf5; }
.cx-badge.amber { background: #fff4df; color: #a86400; box-shadow: 0 0 0 8px #fffaf0; }
.cx-h1 { text-align: center; font: 700 23px/1.25 'Poppins', sans-serif; color: var(--navy); margin-top: 10px; }
.cx-p  { text-align: center; font-size: 14px; color: var(--muted); line-height: 1.55; padding: 0 4px 6px; }
.cx-note { display: flex; gap: 10px; align-items: flex-start; background: #f5f8fe; border: 1px solid #dbe6fb; color: #33507f;
  border-radius: 12px; padding: 10px 13px; font-size: 12.5px; line-height: 1.5; }
.cx-note b { color: var(--navy); }
.cx-note.amber { background: #fff8e8; border-color: #f6e2b3; color: #7a4a12; }
.cx-note svg { width: 16px; height: 16px; flex: none; margin-top: 1px; }

/* --- Log In / Sign Up switch -------------------------------------------- */
.st-key-authtabs { background: #eef1f6; border-radius: 14px; padding: 5px; }
.st-key-authtabs [data-testid="stHorizontalBlock"] { gap: 5px; }
.st-key-authtabs [data-testid="stButton"] { width: 100%; }
.st-key-authtabs button { width: 100%; height: 40px; min-height: 0; border: 0; border-radius: 10px; box-shadow: none; }
.st-key-authtabs button p { font: 600 13.5px 'Poppins', sans-serif; color: inherit; }
.st-key-tab_login_on button, .st-key-tab_signup_on button {
  background: #fff !important; color: var(--navy) !important; box-shadow: 0 2px 6px rgba(20, 33, 61, .12) !important; }
.st-key-tab_login_off button, .st-key-tab_signup_off button { background: transparent !important; color: #5b6472 !important; }

/* --- alerts ------------------------------------------------------------------ */
.cx-alert { border-radius: 12px; padding: 10px 14px; font-size: 13px; line-height: 1.45; }
.cx-alert.err { background: #fde8e8; color: #b42323; }
.cx-alert.ok  { background: #e3f4ea; color: #0c7a37; }

/* --- inputs ---------------------------------------------------------------- */
[data-testid="stWidgetLabel"] p { font: 600 13px 'Poppins', sans-serif; color: var(--navy); }
[data-testid="stWidgetLabel"] p span { font-weight: 400; }
[data-testid="stTextInput"] [data-baseweb="input"], [data-testid="stTextInputRootElement"],
[data-testid="stSelectbox"] [data-baseweb="select"] > div {
  background: #fff; border: 1px solid #dfe3ea; border-radius: 12px; min-height: 46px; }
[data-testid="stTextInput"] [data-baseweb="input"]:focus-within, [data-testid="stTextInputRootElement"]:focus-within,
[data-testid="stSelectbox"] [data-baseweb="select"] > div:focus-within {
  border-color: var(--blue); box-shadow: 0 0 0 3px rgba(45, 111, 227, .15); }
[data-testid="stTextInput"] [data-baseweb="base-input"] { background: transparent; border: 0; }
[data-testid="stTextInput"] input { color: #111827; -webkit-text-fill-color: #111827; font-size: 14.5px; background: transparent; }
[data-testid="stTextInput"] input::placeholder, [data-testid="stSelectbox"] input::placeholder {
  color: #9aa3b2; -webkit-text-fill-color: #9aa3b2; opacity: 1; }
[data-testid="stTextInput"] button { color: #8b93a1; background: transparent; }
[data-testid="stSelectbox"] [data-baseweb="select"] * { font-size: 14.5px; color: #111827; }
[data-testid="stSelectbox"] [data-baseweb="select"] svg { color: #8b93a1; }
[data-testid="InputInstructions"] { display: none; }
[data-testid="stCheckbox"] label p { font-size: 12.5px; font-weight: 400; color: #4b5563; }
.st-key-su_code input { text-align: center; letter-spacing: .4em; font-size: 18px; }
.st-key-su_code input::placeholder { letter-spacing: .4em; }
.st-key-rs_code input { text-align: center; letter-spacing: .4em; font-size: 18px; }
.st-key-rs_code input::placeholder { letter-spacing: .4em; }

/* --- forms ------------------------------------------------------------------- */
[data-testid="stForm"] { border: 0 !important; padding: 0 !important; background: transparent; }
[data-testid="stFormSubmitButton"] { margin-top: .4rem; }
.st-key-login_actions { order: 2; }
.st-key-login_submit  { order: 3; margin-top: .4rem; }

/* --- primary buttons --------------------------------------------------------- */
[data-testid="stBaseButton-primary"], [data-testid="stBaseButton-primaryFormSubmit"] {
  display: flex; margin: 0 auto; width: 100%; height: 48px; border: 0; border-radius: 12px;
  background: var(--blue); color: #fff; box-shadow: 0 10px 22px rgba(45, 111, 227, .28); }
[data-testid="stBaseButton-primary"] p, [data-testid="stBaseButton-primaryFormSubmit"] p {
  color: #fff; font: 600 15px 'Poppins', sans-serif; }
[data-testid="stBaseButton-primary"]:hover, [data-testid="stBaseButton-primaryFormSubmit"]:hover {
  background: var(--blue-dk); border: 0; }

/* --- text-link buttons ------------------------------------------------------- */
.st-key-forgot_link button, .st-key-back_link button, .st-key-resend_link button,
.st-key-edit_link button, .st-key-home_link button {
  background: transparent !important; border: 0 !important; box-shadow: none !important;
  padding: 0 !important; min-height: 0 !important; height: auto !important; width: auto !important; }
.st-key-forgot_link [data-testid="stFormSubmitButton"] { display: flex; justify-content: flex-end; }
.st-key-forgot_link button p { font: 600 12.5px 'Poppins', sans-serif; color: var(--blue); }
.st-key-back_link { display: flex; justify-content: center; }
.st-key-back_link button p, .st-key-home_link button p { font: 500 12.5px 'Poppins', sans-serif; color: #6b7280; }
.st-key-home_link { margin-bottom: -4px; }
.st-key-resend_link, .st-key-edit_link { display: flex; }
.st-key-edit_link { justify-content: flex-end; }
.st-key-resend_link button p, .st-key-edit_link button p { font: 600 14px 'Poppins', sans-serif; color: var(--blue); }
.st-key-forgot_link button:hover p, .st-key-back_link button:hover p, .st-key-resend_link button:hover p,
.st-key-edit_link button:hover p, .st-key-home_link button:hover p { text-decoration: underline; }
.st-key-home_link button:hover p { color: var(--blue); }

/* --- role picker (Teacher / Technician) -------------------------------------- */
[class*="st-key-role_"] button {
  width: 100%; height: auto; min-height: 108px; padding: 14px 8px; border-radius: 16px;
  background: #fff; border: 1.5px solid #e3e6ec; box-shadow: none; transition: border-color .15s, background .15s; }
[class*="st-key-role_"] button:hover { border-color: #cfdcf6; }
[class*="st-key-role_"] button > div { flex-direction: column; gap: 3px; }
[class*="st-key-role_"] [data-testid="stButton"] { width: 100%; }
[class*="st-key-role_"] button p { white-space: pre-line; text-align: center; font-size: 11.5px; line-height: 1.4; margin: 0; color: #6b7280; }
[class*="st-key-role_"] button strong { font: 600 14px 'Poppins', sans-serif; color: var(--navy); }
[class*="st-key-role_"] button span[role="img"] {
  display: block; margin: 0 auto 4px; font-size: 28px; line-height: 1; color: #6b7a90; vertical-align: baseline; }
.st-key-role_teacher_on button, .st-key-role_technician_on button {
  border: 1.5px solid var(--blue); background: #eef4fe; box-shadow: 0 0 0 3px rgba(45, 111, 227, .12); }
.st-key-role_teacher_on button span[role="img"], .st-key-role_technician_on button span[role="img"] { color: var(--blue); }
@media (prefers-reduced-motion: reduce) { .cl-rep, .cl-ping { animation: none !important; } }
</style>
"""


def _build_css() -> str:
    photo = _find_image(BG_IMAGE, ("background", "bg", "campus", "gate"))
    if photo:
        bg = ("linear-gradient(160deg, rgba(15, 26, 51, .93) 0%, rgba(15, 26, 51, .97) 60%), "
              f'url("{_file_data_uri(str(photo), photo.stat().st_mtime)}") center / cover no-repeat')
    else:
        bg = "radial-gradient(700px 520px at 20% 30%, #182a52 0%, #0f1a33 65%)"
    return _CSS.replace("__PANEL_BG__", bg)


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------
_ICONS = {
    "mail": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<rect x="3" y="5" width="18" height="14" rx="2"/><polyline points="3,7 12,13 21,7"/></svg>'
    ),
    "check": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" '
        'stroke-linecap="round" stroke-linejoin="round"><polyline points="5,13 10,18 19,7"/></svg>'
    ),
    "clock": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>'
    ),
    "info": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/></svg>'
    ),
}


def _panel() -> None:
    """The navy floor-plan panel on the left (desktop only)."""
    st.markdown(
        '<div class="cl-panel">'
        '<div class="cl-panel-body">'
        '<span class="cl-pill"><i></i>MONITOR. REPORT. RESOLVE.</span>'
        '<h1>Every computer,<br>every laboratory,<br><span>always ready.</span></h1>'
        '<p>Sign in to report a problem, follow a repair, or keep all four Centrum laboratories running.</p>'
        f'<div class="cl-map-wrap">{BRAND_MAP_SVG}</div>'
        '<div class="cl-legend"><span><i style="background:#5b7fc4"></i>Working</span>'
        '<span><i style="background:#f5a524"></i>Reported</span><span><i style="background:#e5484d"></i>Under repair</span></div>'
        '</div>'
        '<div class="cl-roles"><span>Teachers</span><span>Technicians</span><span>Admins</span></div>'
        '</div>',
        unsafe_allow_html=True,
    )


def _alert() -> None:
    if ss.auth_notice:
        kind, message = ss.auth_notice
        st.markdown(
            f'<div class="cx-alert {kind}">{html.escape(message)}</div>',
            unsafe_allow_html=True,
        )


def _heading(title: str, description: str) -> None:
    st.markdown(
        f'<div class="cx-title">{html.escape(title)}</div>'
        f'<div class="cx-desc">{html.escape(description)}</div>',
        unsafe_allow_html=True,
    )


def _centered_heading(icon: str, tone: str, title: str, text: str) -> None:
    st.markdown(
        f'<div class="cx-badge {tone}">{_ICONS[icon]}</div>'
        f'<div class="cx-h1">{html.escape(title)}</div>'
        f'<div class="cx-p">{html.escape(text)}</div>',
        unsafe_allow_html=True,
    )


def _note(text_html: str, tone: str = "") -> None:
    st.markdown(
        f'<div class="cx-note {tone}">{_ICONS["info"]}<span>{text_html}</span></div>',
        unsafe_allow_html=True,
    )


def _render_header() -> None:
    """Small-screen header: just the app subtitle (the logo was removed)."""
    st.markdown(
        f'<div class="cx-head"><div class="cx-sub">{APP_SUBTITLE}</div></div>',
        unsafe_allow_html=True,
    )


def _render_tabs() -> None:
    active = "signup" if ss.auth_view == "signup" else "login"
    with st.container(key="authtabs"):
        left, right = st.columns(2, gap="small")
        left.button(
            "Log In",
            key=f"tab_login_{'on' if active == 'login' else 'off'}",
            on_click=_go,
            args=("login",),
        )
        right.button(
            "Sign Up",
            key=f"tab_signup_{'on' if active == 'signup' else 'off'}",
            on_click=_go,
            args=("signup",),
        )


def _render_login() -> None:
    _heading("Welcome back", "Log in to your Centrum Laboratory account.")
    _alert()
    with st.form("login_form"):
        st.text_input("Email address", key="login_email", placeholder="you@isu.edu.ph")
        st.text_input(
            "Password", type="password", key="login_password", placeholder="Your password"
        )
        # Submit first in the DOM so Enter submits it; CSS moves it below the row.
        st.form_submit_button(
            "Log In", type="primary", key="login_submit", on_click=_do_login
        )
        with st.container(key="login_actions"):
            left, right = st.columns(2, vertical_alignment="center")
            left.checkbox("Remember me", key="login_remember")
            right.form_submit_button(
                "Forgot password?", key="forgot_link", on_click=_go, args=("reset",)
            )


def _render_signup() -> None:
    {"form": _render_signup_form, "verify": _render_verify, "done": _render_done}[
        ss.signup_step
    ]()


def _render_signup_form() -> None:
    _heading("Create your account", "Pick your role, then fill in your details.")
    _alert()

    role = ss.signup_role
    left, right = st.columns(2, gap="small")
    left.button(
        ":material/school:\n**Teacher**\nReport issues, track fixes",
        key=f"role_teacher_{'on' if role == 'Teacher' else 'off'}",
        on_click=_set_role,
        args=("Teacher",),
    )
    right.button(
        ":material/build:\n**Technician**\nFix, track, and analyze",
        key=f"role_technician_{'on' if role == 'Technician' else 'off'}",
        on_click=_set_role,
        args=("Technician",),
    )
    if role == "Technician":
        _note(
            "<b>Technician accounts need the admin's approval.</b> "
            "You can log in once it's confirmed.",
            "amber",
        )
    elif role == "Teacher":
        _note(
            "<b>Teacher accounts are ready right away.</b> "
            "You can report issues as soon as you sign up."
        )

    with st.form("signup_form"):
        a, b = st.columns(2, gap="small")
        a.text_input("First name", key="su_first", placeholder="Juan")
        b.text_input("Last name", key="su_last", placeholder="Dela Cruz")
        st.selectbox(
            "Department",
            DEPARTMENTS,
            index=None,
            placeholder="Select your department",
            key="su_dept",
        )
        st.text_input("Email address", key="su_email", placeholder="you@isu.edu.ph")
        st.text_input(
            "Contact number :gray[(optional)]",
            key="su_contact",
            placeholder="09XX XXX XXXX",
        )
        st.text_input(
            "Password",
            type="password",
            key="su_password",
            placeholder=f"At least {MIN_PASSWORD_LENGTH} characters",
        )
        st.text_input(
            "Confirm password",
            type="password",
            key="su_confirm",
            placeholder="Re-enter your password",
        )
        st.form_submit_button("Continue", type="primary", on_click=_do_signup)


def _render_verify() -> None:
    data = ss.signup_data or {}

    _centered_heading(
        "mail",
        "blue",
        "Check your email",
        f"We sent a 6-digit code to {data.get('email', 'your email')}.",
    )

    _alert()

    needs_approval = ss.signup_role in APPROVAL_ROLES

    with st.form("verify_form"):
        st.text_input(
            "Verification code",
            type="password",
            max_chars=6,
            key="su_code",
            placeholder="• • • • • •",
        )

        st.form_submit_button(
            "Verify & send request" if needs_approval else "Verify & create account",
            type="primary",
            on_click=_do_verify,
        )

    left, right = st.columns(2, gap="small")

    left.button("Resend code", key="resend_link", on_click=_resend_code)

    right.button("Edit details", key="edit_link", on_click=_edit_details)


def _render_done() -> None:
    info = ss.signup_done or {}
    first = info.get("first", "")
    if info.get("pending"):
        role = (info.get("role") or "account").lower()
        _centered_heading(
            "clock",
            "amber",
            "Request sent",
            f"Thanks, {first}! Your {role} account was sent to the laboratory admin. "
            "You can log in once it's confirmed.",
        )
    else:
        _centered_heading(
            "check",
            "green",
            "Account created",
            f"Thanks, {first}! Your account is ready. Log in to start reporting issues.",
        )
    st.button(
        "Back to log in", type="primary", key="done_back", on_click=_go, args=("login",)
    )


def _render_reset() -> None:
    if ss.reset_step == "code":
        return _render_reset_code()
    _heading(
        "Reset your password",
        "Enter your email and we'll send you a 6-digit reset code.",
    )
    _alert()
    with st.form("reset_form"):
        st.text_input("Email address", key="reset_email", placeholder="you@isu.edu.ph")
        st.form_submit_button("Send reset code", type="primary", on_click=_do_reset)
    st.button("\u2039 Back to log in", key="back_link", on_click=_go, args=("login",))


def _render_reset_code() -> None:
    _heading(
        "Enter your reset code",
        f"Check {ss.reset_target or 'your email'} for a 6-digit code, then choose a new password.",
    )
    _alert()
    with st.form("reset_code_form"):
        st.text_input(
            "Reset code",
            type="password",
            max_chars=6,
            key="rs_code",
            placeholder="\u2022 \u2022 \u2022 \u2022 \u2022 \u2022",
        )
        st.text_input(
            "New password",
            type="password",
            key="rs_password",
            placeholder=f"At least {MIN_PASSWORD_LENGTH} characters",
        )
        st.text_input(
            "Confirm new password",
            type="password",
            key="rs_confirm",
            placeholder="Re-enter your new password",
        )
        st.form_submit_button(
            "Reset password", type="primary", on_click=_do_reset_confirm
        )
    left, right = st.columns(2, gap="small")
    left.button("Resend code", key="resend_link", on_click=_resend_reset_code)
    right.button(
        "\u2039 Back to log in", key="back_link", on_click=_go, args=("login",)
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def _page_config() -> None:
    try:
        st.set_page_config(
            page_title="Centrum Laboratory - Log In",
            page_icon="\U0001f5a5\ufe0f",
            layout="wide",
            initial_sidebar_state="collapsed",
        )
    except st.errors.StreamlitAPIException:
        pass  # the main app already called set_page_config


def require_login(on_back=None) -> bool:
    """Draw the auth screens unless the user is signed in. Returns True when signed in.

    `on_back`: optional function; when given, a "Back to home" link is shown on the card.
    """
    _page_config()
    _init_state()
    if ss.authenticated:
        return True

    st.markdown(_build_css(), unsafe_allow_html=True)
    _panel()
    # "Check your email" and "Request sent" are stand-alone cards: no header, no tabs.
    standalone = ss.auth_view == "signup" and ss.signup_step != "form"
    if on_back is not None and not standalone:
        st.button("\u2039 Back to home", key="home_link", on_click=on_back)
    if not standalone:
        _render_header()
        _render_tabs()
    {"login": _render_login, "signup": _render_signup, "reset": _render_reset}[
        ss.auth_view
    ]()
    return False


# ---------------------------------------------------------------------------
# Built-in image (the floor plan). Edit only if you know SVG.
# ---------------------------------------------------------------------------
BRAND_MAP_SVG = r'''<svg class="cl-map" viewBox="-6 -6 612 612" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><defs><path id="clb-l1" d="M324.5,579.9 A281.0,281.0 0 0 0 579.9,324.5"/><path id="clb-l2" d="M20.1,324.5 A281.0,281.0 0 0 0 275.5,579.9"/><path id="clb-l3" d="M323.8,28.0 A273.0,273.0 0 0 1 572.0,276.2"/><path id="clb-l4" d="M28.0,276.2 A273.0,273.0 0 0 1 276.2,28.0"/></defs><circle cx="300" cy="300" r="277.0" fill="none" stroke="rgba(255,255,255,.04)" stroke-width="30"/><circle cx="300" cy="300" r="292" fill="none" stroke="rgba(255,255,255,.14)" stroke-width="1.5"/><path d="M300.0,556.0 A256,256 0 0 0 556.0,300.0 L422.0,300.0 A122,122 0 0 1 300.0,422.0 Z" fill="rgba(91,147,245,.10)" stroke="rgba(143,179,247,.35)" stroke-width="1.5"/><path d="M44.0,300.0 A256,256 0 0 0 300.0,556.0 L300.0,422.0 A122,122 0 0 1 178.0,300.0 Z" fill="rgba(91,147,245,.10)" stroke="rgba(143,179,247,.35)" stroke-width="1.5"/><path d="M556.0,300.0 A256,256 0 0 0 300.0,44.0 L300.0,178.0 A122,122 0 0 1 422.0,300.0 Z" fill="rgba(91,147,245,.10)" stroke="rgba(143,179,247,.35)" stroke-width="1.5"/><path d="M300.0,44.0 A256,256 0 0 0 44.0,300.0 L178.0,300.0 A122,122 0 0 1 300.0,178.0 Z" fill="rgba(91,147,245,.10)" stroke="rgba(143,179,247,.35)" stroke-width="1.5"/><rect x="277.0" y="42" width="46" height="146" fill="#0f1a33"/><rect x="277.0" y="412" width="46" height="146" fill="#0f1a33"/><rect x="42" y="277.0" width="146" height="46" fill="#0f1a33"/><rect x="412" y="277.0" width="146" height="46" fill="#0f1a33"/><circle cx="300" cy="300" r="98.0" fill="none" stroke="#ffffff" stroke-width="28"/><circle cx="394.7" cy="274.6" r="3.2" fill="#0f1a33"/><circle cx="369.3" cy="230.7" r="3.2" fill="#0f1a33"/><circle cx="325.4" cy="205.3" r="3.2" fill="#0f1a33"/><circle cx="274.6" cy="205.3" r="3.2" fill="#0f1a33"/><circle cx="230.7" cy="230.7" r="3.2" fill="#0f1a33"/><circle cx="205.3" cy="274.6" r="3.2" fill="#0f1a33"/><circle cx="205.3" cy="325.4" r="3.2" fill="#0f1a33"/><circle cx="230.7" cy="369.3" r="3.2" fill="#0f1a33"/><circle cx="274.6" cy="394.7" r="3.2" fill="#0f1a33"/><circle cx="325.4" cy="394.7" r="3.2" fill="#0f1a33"/><circle cx="369.3" cy="369.3" r="3.2" fill="#0f1a33"/><circle cx="394.7" cy="325.4" r="3.2" fill="#0f1a33"/><circle cx="300" cy="300" r="84" fill="#0f1a33"/><circle class="cl-ping" cx="300" cy="300" r="26" fill="none" stroke="#5b93f5" stroke-width="2"/><circle cx="300" cy="300" r="26" fill="#2d6fe3"/><g transform="translate(288 289)" fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><rect x="1" y="1" width="22" height="15" rx="2.5"/><path d="M8 21h8M12 16v5"/></g><rect class="cl-pc cl-ok" x="432.8" y="337.1" width="14" height="10" rx="2.5" transform="rotate(-253.3 439.8 342.1)"/><rect class="cl-pc cl-ok" x="424.0" y="359.4" width="14" height="10" rx="2.5" transform="rotate(-243.8 431.0 364.4)"/><rect class="cl-pc cl-ok" x="411.7" y="380.0" width="14" height="10" rx="2.5" transform="rotate(-234.4 418.7 385.0)"/><rect class="cl-pc cl-ok" x="396.2" y="398.2" width="14" height="10" rx="2.5" transform="rotate(-225.0 403.2 403.2)"/><rect class="cl-pc cl-rep" x="378.0" y="413.7" width="14" height="10" rx="2.5" transform="rotate(-215.6 385.0 418.7)"/><rect class="cl-pc cl-ok" x="357.4" y="426.0" width="14" height="10" rx="2.5" transform="rotate(-206.2 364.4 431.0)"/><rect class="cl-pc cl-ok" x="335.1" y="434.8" width="14" height="10" rx="2.5" transform="rotate(-196.7 342.1 439.8)"/><rect class="cl-pc cl-ok" x="460.6" y="333.8" width="14" height="10" rx="2.5" transform="rotate(-257.0 467.6 338.8)"/><rect class="cl-pc cl-ok" x="453.6" y="356.7" width="14" height="10" rx="2.5" transform="rotate(-249.0 460.6 361.7)"/><rect class="cl-pc cl-ok" x="443.4" y="378.4" width="14" height="10" rx="2.5" transform="rotate(-241.0 450.4 383.4)"/><rect class="cl-pc cl-ok" x="430.4" y="398.5" width="14" height="10" rx="2.5" transform="rotate(-233.0 437.4 403.5)"/><rect class="cl-pc cl-ok" x="414.6" y="416.6" width="14" height="10" rx="2.5" transform="rotate(-225.0 421.6 421.6)"/><rect class="cl-pc cl-ok" x="396.5" y="432.4" width="14" height="10" rx="2.5" transform="rotate(-217.0 403.5 437.4)"/><rect class="cl-pc cl-fix" x="376.4" y="445.4" width="14" height="10" rx="2.5" transform="rotate(-209.0 383.4 450.4)"/><rect class="cl-pc cl-ok" x="354.7" y="455.6" width="14" height="10" rx="2.5" transform="rotate(-201.0 361.7 460.6)"/><rect class="cl-pc cl-ok" x="331.8" y="462.6" width="14" height="10" rx="2.5" transform="rotate(-193.0 338.8 467.6)"/><rect class="cl-pc cl-ok" x="487.8" y="330.3" width="14" height="10" rx="2.5" transform="rotate(-259.7 494.8 335.3)"/><rect class="cl-pc cl-ok" x="482.1" y="353.6" width="14" height="10" rx="2.5" transform="rotate(-252.8 489.1 358.6)"/><rect class="cl-pc cl-ok" x="473.6" y="376.1" width="14" height="10" rx="2.5" transform="rotate(-245.8 480.6 381.1)"/><rect class="cl-pc cl-ok" x="462.5" y="397.3" width="14" height="10" rx="2.5" transform="rotate(-238.9 469.5 402.3)"/><rect class="cl-pc cl-ok" x="448.9" y="417.1" width="14" height="10" rx="2.5" transform="rotate(-231.9 455.9 422.1)"/><rect class="cl-pc cl-ok" x="433.0" y="435.0" width="14" height="10" rx="2.5" transform="rotate(-225.0 440.0 440.0)"/><rect class="cl-pc cl-rep" x="415.1" y="450.9" width="14" height="10" rx="2.5" transform="rotate(-218.1 422.1 455.9)"/><rect class="cl-pc cl-ok" x="395.3" y="464.5" width="14" height="10" rx="2.5" transform="rotate(-211.1 402.3 469.5)"/><rect class="cl-pc cl-ok" x="374.1" y="475.6" width="14" height="10" rx="2.5" transform="rotate(-204.2 381.1 480.6)"/><rect class="cl-pc cl-ok" x="351.6" y="484.1" width="14" height="10" rx="2.5" transform="rotate(-197.2 358.6 489.1)"/><rect class="cl-pc cl-ok" x="328.3" y="489.8" width="14" height="10" rx="2.5" transform="rotate(-190.3 335.3 494.8)"/><rect class="cl-pc cl-ok" x="512.7" y="338.6" width="14" height="10" rx="2.5" transform="rotate(-258.8 519.7 343.6)"/><rect class="cl-pc cl-ok" x="506.8" y="361.9" width="14" height="10" rx="2.5" transform="rotate(-252.6 513.8 366.9)"/><rect class="cl-pc cl-ok" x="498.4" y="384.4" width="14" height="10" rx="2.5" transform="rotate(-246.5 505.4 389.4)"/><rect class="cl-pc cl-ok" x="487.7" y="405.8" width="14" height="10" rx="2.5" transform="rotate(-240.3 494.7 410.8)"/><rect class="cl-pc cl-ok" x="474.7" y="426.0" width="14" height="10" rx="2.5" transform="rotate(-234.2 481.7 431.0)"/><rect class="cl-pc cl-ok" x="459.6" y="444.7" width="14" height="10" rx="2.5" transform="rotate(-228.1 466.6 449.7)"/><rect class="cl-pc cl-ok" x="442.7" y="461.6" width="14" height="10" rx="2.5" transform="rotate(-221.9 449.7 466.6)"/><rect class="cl-pc cl-ok" x="424.0" y="476.7" width="14" height="10" rx="2.5" transform="rotate(-215.8 431.0 481.7)"/><rect class="cl-pc cl-ok" x="403.8" y="489.7" width="14" height="10" rx="2.5" transform="rotate(-209.7 410.8 494.7)"/><rect class="cl-pc cl-ok" x="382.4" y="500.4" width="14" height="10" rx="2.5" transform="rotate(-203.5 389.4 505.4)"/><rect class="cl-pc cl-ok" x="359.9" y="508.8" width="14" height="10" rx="2.5" transform="rotate(-197.4 366.9 513.8)"/><rect class="cl-pc cl-ok" x="336.6" y="514.7" width="14" height="10" rx="2.5" transform="rotate(-191.2 343.6 519.7)"/><rect class="cl-pc cl-ok" x="250.9" y="434.8" width="14" height="10" rx="2.5" transform="rotate(-163.3 257.9 439.8)"/><rect class="cl-pc cl-fix" x="228.6" y="426.0" width="14" height="10" rx="2.5" transform="rotate(-153.8 235.6 431.0)"/><rect class="cl-pc cl-ok" x="208.0" y="413.7" width="14" height="10" rx="2.5" transform="rotate(-144.4 215.0 418.7)"/><rect class="cl-pc cl-ok" x="189.8" y="398.2" width="14" height="10" rx="2.5" transform="rotate(-135.0 196.8 403.2)"/><rect class="cl-pc cl-ok" x="174.3" y="380.0" width="14" height="10" rx="2.5" transform="rotate(-125.6 181.3 385.0)"/><rect class="cl-pc cl-ok" x="162.0" y="359.4" width="14" height="10" rx="2.5" transform="rotate(-116.2 169.0 364.4)"/><rect class="cl-pc cl-ok" x="153.2" y="337.1" width="14" height="10" rx="2.5" transform="rotate(-106.7 160.2 342.1)"/><rect class="cl-pc cl-ok" x="254.2" y="462.6" width="14" height="10" rx="2.5" transform="rotate(-167.0 261.2 467.6)"/><rect class="cl-pc cl-ok" x="231.3" y="455.6" width="14" height="10" rx="2.5" transform="rotate(-159.0 238.3 460.6)"/><rect class="cl-pc cl-ok" x="209.6" y="445.4" width="14" height="10" rx="2.5" transform="rotate(-151.0 216.6 450.4)"/><rect class="cl-pc cl-ok" x="189.5" y="432.4" width="14" height="10" rx="2.5" transform="rotate(-143.0 196.5 437.4)"/><rect class="cl-pc cl-ok" x="171.4" y="416.6" width="14" height="10" rx="2.5" transform="rotate(-135.0 178.4 421.6)"/><rect class="cl-pc cl-ok" x="155.6" y="398.5" width="14" height="10" rx="2.5" transform="rotate(-127.0 162.6 403.5)"/><rect class="cl-pc cl-ok" x="142.6" y="378.4" width="14" height="10" rx="2.5" transform="rotate(-119.0 149.6 383.4)"/><rect class="cl-pc cl-ok" x="132.4" y="356.7" width="14" height="10" rx="2.5" transform="rotate(-111.0 139.4 361.7)"/><rect class="cl-pc cl-ok" x="125.4" y="333.8" width="14" height="10" rx="2.5" transform="rotate(-103.0 132.4 338.8)"/><rect class="cl-pc cl-ok" x="257.7" y="489.8" width="14" height="10" rx="2.5" transform="rotate(-169.7 264.7 494.8)"/><rect class="cl-pc cl-ok" x="234.4" y="484.1" width="14" height="10" rx="2.5" transform="rotate(-162.8 241.4 489.1)"/><rect class="cl-pc cl-ok" x="211.9" y="475.6" width="14" height="10" rx="2.5" transform="rotate(-155.8 218.9 480.6)"/><rect class="cl-pc cl-ok" x="190.7" y="464.5" width="14" height="10" rx="2.5" transform="rotate(-148.9 197.7 469.5)"/><rect class="cl-pc cl-ok" x="170.9" y="450.9" width="14" height="10" rx="2.5" transform="rotate(-141.9 177.9 455.9)"/><rect class="cl-pc cl-ok" x="153.0" y="435.0" width="14" height="10" rx="2.5" transform="rotate(-135.0 160.0 440.0)"/><rect class="cl-pc cl-ok" x="137.1" y="417.1" width="14" height="10" rx="2.5" transform="rotate(-128.1 144.1 422.1)"/><rect class="cl-pc cl-ok" x="123.5" y="397.3" width="14" height="10" rx="2.5" transform="rotate(-121.1 130.5 402.3)"/><rect class="cl-pc cl-ok" x="112.4" y="376.1" width="14" height="10" rx="2.5" transform="rotate(-114.2 119.4 381.1)"/><rect class="cl-pc cl-ok" x="103.9" y="353.6" width="14" height="10" rx="2.5" transform="rotate(-107.2 110.9 358.6)"/><rect class="cl-pc cl-ok" x="98.2" y="330.3" width="14" height="10" rx="2.5" transform="rotate(-100.3 105.2 335.3)"/><rect class="cl-pc cl-ok" x="249.4" y="514.7" width="14" height="10" rx="2.5" transform="rotate(-168.8 256.4 519.7)"/><rect class="cl-pc cl-ok" x="226.1" y="508.8" width="14" height="10" rx="2.5" transform="rotate(-162.6 233.1 513.8)"/><rect class="cl-pc cl-fix" x="203.6" y="500.4" width="14" height="10" rx="2.5" transform="rotate(-156.5 210.6 505.4)"/><rect class="cl-pc cl-ok" x="182.2" y="489.7" width="14" height="10" rx="2.5" transform="rotate(-150.3 189.2 494.7)"/><rect class="cl-pc cl-ok" x="162.0" y="476.7" width="14" height="10" rx="2.5" transform="rotate(-144.2 169.0 481.7)"/><rect class="cl-pc cl-ok" x="143.3" y="461.6" width="14" height="10" rx="2.5" transform="rotate(-138.1 150.3 466.6)"/><rect class="cl-pc cl-ok" x="126.4" y="444.7" width="14" height="10" rx="2.5" transform="rotate(-131.9 133.4 449.7)"/><rect class="cl-pc cl-ok" x="111.3" y="426.0" width="14" height="10" rx="2.5" transform="rotate(-125.8 118.3 431.0)"/><rect class="cl-pc cl-ok" x="98.3" y="405.8" width="14" height="10" rx="2.5" transform="rotate(-119.7 105.3 410.8)"/><rect class="cl-pc cl-ok" x="87.6" y="384.4" width="14" height="10" rx="2.5" transform="rotate(-113.5 94.6 389.4)"/><rect class="cl-pc cl-ok" x="79.2" y="361.9" width="14" height="10" rx="2.5" transform="rotate(-107.4 86.2 366.9)"/><rect class="cl-pc cl-ok" x="73.3" y="338.6" width="14" height="10" rx="2.5" transform="rotate(-101.2 80.3 343.6)"/><rect class="cl-pc cl-ok" x="335.1" y="155.2" width="14" height="10" rx="2.5" transform="rotate(16.7 342.1 160.2)"/><rect class="cl-pc cl-ok" x="357.4" y="164.0" width="14" height="10" rx="2.5" transform="rotate(26.2 364.4 169.0)"/><rect class="cl-pc cl-rep" x="378.0" y="176.3" width="14" height="10" rx="2.5" transform="rotate(35.6 385.0 181.3)"/><rect class="cl-pc cl-ok" x="396.2" y="191.8" width="14" height="10" rx="2.5" transform="rotate(45.0 403.2 196.8)"/><rect class="cl-pc cl-ok" x="411.7" y="210.0" width="14" height="10" rx="2.5" transform="rotate(54.4 418.7 215.0)"/><rect class="cl-pc cl-ok" x="424.0" y="230.6" width="14" height="10" rx="2.5" transform="rotate(63.8 431.0 235.6)"/><rect class="cl-pc cl-ok" x="432.8" y="252.9" width="14" height="10" rx="2.5" transform="rotate(73.3 439.8 257.9)"/><rect class="cl-pc cl-ok" x="331.8" y="127.4" width="14" height="10" rx="2.5" transform="rotate(13.0 338.8 132.4)"/><rect class="cl-pc cl-ok" x="354.7" y="134.4" width="14" height="10" rx="2.5" transform="rotate(21.0 361.7 139.4)"/><rect class="cl-pc cl-ok" x="376.4" y="144.6" width="14" height="10" rx="2.5" transform="rotate(29.0 383.4 149.6)"/><rect class="cl-pc cl-ok" x="396.5" y="157.6" width="14" height="10" rx="2.5" transform="rotate(37.0 403.5 162.6)"/><rect class="cl-pc cl-rep" x="414.6" y="173.4" width="14" height="10" rx="2.5" transform="rotate(45.0 421.6 178.4)"/><rect class="cl-pc cl-ok" x="430.4" y="191.5" width="14" height="10" rx="2.5" transform="rotate(53.0 437.4 196.5)"/><rect class="cl-pc cl-ok" x="443.4" y="211.6" width="14" height="10" rx="2.5" transform="rotate(61.0 450.4 216.6)"/><rect class="cl-pc cl-ok" x="453.6" y="233.3" width="14" height="10" rx="2.5" transform="rotate(69.0 460.6 238.3)"/><rect class="cl-pc cl-ok" x="460.6" y="256.2" width="14" height="10" rx="2.5" transform="rotate(77.0 467.6 261.2)"/><rect class="cl-pc cl-ok" x="328.3" y="100.2" width="14" height="10" rx="2.5" transform="rotate(10.3 335.3 105.2)"/><rect class="cl-pc cl-ok" x="351.6" y="105.9" width="14" height="10" rx="2.5" transform="rotate(17.2 358.6 110.9)"/><rect class="cl-pc cl-ok" x="374.1" y="114.4" width="14" height="10" rx="2.5" transform="rotate(24.2 381.1 119.4)"/><rect class="cl-pc cl-ok" x="395.3" y="125.5" width="14" height="10" rx="2.5" transform="rotate(31.1 402.3 130.5)"/><rect class="cl-pc cl-ok" x="415.1" y="139.1" width="14" height="10" rx="2.5" transform="rotate(38.1 422.1 144.1)"/><rect class="cl-pc cl-ok" x="433.0" y="155.0" width="14" height="10" rx="2.5" transform="rotate(45.0 440.0 160.0)"/><rect class="cl-pc cl-ok" x="448.9" y="172.9" width="14" height="10" rx="2.5" transform="rotate(51.9 455.9 177.9)"/><rect class="cl-pc cl-ok" x="462.5" y="192.7" width="14" height="10" rx="2.5" transform="rotate(58.9 469.5 197.7)"/><rect class="cl-pc cl-ok" x="473.6" y="213.9" width="14" height="10" rx="2.5" transform="rotate(65.8 480.6 218.9)"/><rect class="cl-pc cl-ok" x="482.1" y="236.4" width="14" height="10" rx="2.5" transform="rotate(72.8 489.1 241.4)"/><rect class="cl-pc cl-rep" x="487.8" y="259.7" width="14" height="10" rx="2.5" transform="rotate(79.7 494.8 264.7)"/><rect class="cl-pc cl-ok" x="336.6" y="75.3" width="14" height="10" rx="2.5" transform="rotate(11.2 343.6 80.3)"/><rect class="cl-pc cl-ok" x="359.9" y="81.2" width="14" height="10" rx="2.5" transform="rotate(17.4 366.9 86.2)"/><rect class="cl-pc cl-ok" x="382.4" y="89.6" width="14" height="10" rx="2.5" transform="rotate(23.5 389.4 94.6)"/><rect class="cl-pc cl-ok" x="403.8" y="100.3" width="14" height="10" rx="2.5" transform="rotate(29.7 410.8 105.3)"/><rect class="cl-pc cl-ok" x="424.0" y="113.3" width="14" height="10" rx="2.5" transform="rotate(35.8 431.0 118.3)"/><rect class="cl-pc cl-ok" x="442.7" y="128.4" width="14" height="10" rx="2.5" transform="rotate(41.9 449.7 133.4)"/><rect class="cl-pc cl-ok" x="459.6" y="145.3" width="14" height="10" rx="2.5" transform="rotate(48.1 466.6 150.3)"/><rect class="cl-pc cl-ok" x="474.7" y="164.0" width="14" height="10" rx="2.5" transform="rotate(54.2 481.7 169.0)"/><rect class="cl-pc cl-ok" x="487.7" y="184.2" width="14" height="10" rx="2.5" transform="rotate(60.3 494.7 189.2)"/><rect class="cl-pc cl-ok" x="498.4" y="205.6" width="14" height="10" rx="2.5" transform="rotate(66.5 505.4 210.6)"/><rect class="cl-pc cl-ok" x="506.8" y="228.1" width="14" height="10" rx="2.5" transform="rotate(72.6 513.8 233.1)"/><rect class="cl-pc cl-ok" x="512.7" y="251.4" width="14" height="10" rx="2.5" transform="rotate(78.8 519.7 256.4)"/><rect class="cl-pc cl-ok" x="153.2" y="252.9" width="14" height="10" rx="2.5" transform="rotate(-73.3 160.2 257.9)"/><rect class="cl-pc cl-ok" x="162.0" y="230.6" width="14" height="10" rx="2.5" transform="rotate(-63.8 169.0 235.6)"/><rect class="cl-pc cl-ok" x="174.3" y="210.0" width="14" height="10" rx="2.5" transform="rotate(-54.4 181.3 215.0)"/><rect class="cl-pc cl-ok" x="189.8" y="191.8" width="14" height="10" rx="2.5" transform="rotate(-45.0 196.8 196.8)"/><rect class="cl-pc cl-ok" x="208.0" y="176.3" width="14" height="10" rx="2.5" transform="rotate(-35.6 215.0 181.3)"/><rect class="cl-pc cl-ok" x="228.6" y="164.0" width="14" height="10" rx="2.5" transform="rotate(-26.2 235.6 169.0)"/><rect class="cl-pc cl-ok" x="250.9" y="155.2" width="14" height="10" rx="2.5" transform="rotate(-16.7 257.9 160.2)"/><rect class="cl-pc cl-ok" x="125.4" y="256.2" width="14" height="10" rx="2.5" transform="rotate(-77.0 132.4 261.2)"/><rect class="cl-pc cl-ok" x="132.4" y="233.3" width="14" height="10" rx="2.5" transform="rotate(-69.0 139.4 238.3)"/><rect class="cl-pc cl-ok" x="142.6" y="211.6" width="14" height="10" rx="2.5" transform="rotate(-61.0 149.6 216.6)"/><rect class="cl-pc cl-fix" x="155.6" y="191.5" width="14" height="10" rx="2.5" transform="rotate(-53.0 162.6 196.5)"/><rect class="cl-pc cl-ok" x="171.4" y="173.4" width="14" height="10" rx="2.5" transform="rotate(-45.0 178.4 178.4)"/><rect class="cl-pc cl-ok" x="189.5" y="157.6" width="14" height="10" rx="2.5" transform="rotate(-37.0 196.5 162.6)"/><rect class="cl-pc cl-ok" x="209.6" y="144.6" width="14" height="10" rx="2.5" transform="rotate(-29.0 216.6 149.6)"/><rect class="cl-pc cl-ok" x="231.3" y="134.4" width="14" height="10" rx="2.5" transform="rotate(-21.0 238.3 139.4)"/><rect class="cl-pc cl-ok" x="254.2" y="127.4" width="14" height="10" rx="2.5" transform="rotate(-13.0 261.2 132.4)"/><rect class="cl-pc cl-ok" x="98.2" y="259.7" width="14" height="10" rx="2.5" transform="rotate(-79.7 105.2 264.7)"/><rect class="cl-pc cl-ok" x="103.9" y="236.4" width="14" height="10" rx="2.5" transform="rotate(-72.8 110.9 241.4)"/><rect class="cl-pc cl-ok" x="112.4" y="213.9" width="14" height="10" rx="2.5" transform="rotate(-65.8 119.4 218.9)"/><rect class="cl-pc cl-ok" x="123.5" y="192.7" width="14" height="10" rx="2.5" transform="rotate(-58.9 130.5 197.7)"/><rect class="cl-pc cl-fix" x="137.1" y="172.9" width="14" height="10" rx="2.5" transform="rotate(-51.9 144.1 177.9)"/><rect class="cl-pc cl-ok" x="153.0" y="155.0" width="14" height="10" rx="2.5" transform="rotate(-45.0 160.0 160.0)"/><rect class="cl-pc cl-ok" x="170.9" y="139.1" width="14" height="10" rx="2.5" transform="rotate(-38.1 177.9 144.1)"/><rect class="cl-pc cl-ok" x="190.7" y="125.5" width="14" height="10" rx="2.5" transform="rotate(-31.1 197.7 130.5)"/><rect class="cl-pc cl-ok" x="211.9" y="114.4" width="14" height="10" rx="2.5" transform="rotate(-24.2 218.9 119.4)"/><rect class="cl-pc cl-ok" x="234.4" y="105.9" width="14" height="10" rx="2.5" transform="rotate(-17.2 241.4 110.9)"/><rect class="cl-pc cl-ok" x="257.7" y="100.2" width="14" height="10" rx="2.5" transform="rotate(-10.3 264.7 105.2)"/><rect class="cl-pc cl-ok" x="73.3" y="251.4" width="14" height="10" rx="2.5" transform="rotate(-78.8 80.3 256.4)"/><rect class="cl-pc cl-ok" x="79.2" y="228.1" width="14" height="10" rx="2.5" transform="rotate(-72.6 86.2 233.1)"/><rect class="cl-pc cl-ok" x="87.6" y="205.6" width="14" height="10" rx="2.5" transform="rotate(-66.5 94.6 210.6)"/><rect class="cl-pc cl-ok" x="98.3" y="184.2" width="14" height="10" rx="2.5" transform="rotate(-60.3 105.3 189.2)"/><rect class="cl-pc cl-ok" x="111.3" y="164.0" width="14" height="10" rx="2.5" transform="rotate(-54.2 118.3 169.0)"/><rect class="cl-pc cl-ok" x="126.4" y="145.3" width="14" height="10" rx="2.5" transform="rotate(-48.1 133.4 150.3)"/><rect class="cl-pc cl-ok" x="143.3" y="128.4" width="14" height="10" rx="2.5" transform="rotate(-41.9 150.3 133.4)"/><rect class="cl-pc cl-ok" x="162.0" y="113.3" width="14" height="10" rx="2.5" transform="rotate(-35.8 169.0 118.3)"/><rect class="cl-pc cl-ok" x="182.2" y="100.3" width="14" height="10" rx="2.5" transform="rotate(-29.7 189.2 105.3)"/><rect class="cl-pc cl-ok" x="203.6" y="89.6" width="14" height="10" rx="2.5" transform="rotate(-23.5 210.6 94.6)"/><rect class="cl-pc cl-ok" x="226.1" y="81.2" width="14" height="10" rx="2.5" transform="rotate(-17.4 233.1 86.2)"/><rect class="cl-pc cl-ok" x="249.4" y="75.3" width="14" height="10" rx="2.5" transform="rotate(-11.2 256.4 80.3)"/><text class="cl-lbl"><textPath href="#clb-l1" startOffset="50%" text-anchor="middle" dominant-baseline="middle">CENTRUM 1</textPath></text><text class="cl-lbl"><textPath href="#clb-l2" startOffset="50%" text-anchor="middle" dominant-baseline="middle">CENTRUM 2</textPath></text><text class="cl-lbl"><textPath href="#clb-l3" startOffset="50%" text-anchor="middle" dominant-baseline="middle">CENTRUM 3</textPath></text><text class="cl-lbl"><textPath href="#clb-l4" startOffset="50%" text-anchor="middle" dominant-baseline="middle">CENTRUM 4</textPath></text></svg>'''


if __name__ == "__main__":
    # Preview mode (from the project root): `python -m streamlit run frontend/NewLogin.py`
    if require_login():
        user = ss.auth_user or {}
        st.success(
            f"Signed in as {user.get('first_name', '')} {user.get('last_name', '')} ({user.get('role', '')})"
        )
        st.button("Log out", on_click=logout)