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

# Optional logo. If missing, a simple built-in wordmark is drawn instead.
LOGO_IMAGE = BASE_DIR / "assets" / "logo.png"

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


def _image_uri(path: Path | None) -> str | None:
    return _file_data_uri(str(path), path.stat().st_mtime) if path else None


def _svg_uri(svg: str) -> str:
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


def _logo_uri(logo: str | Path | None = None) -> str:
    """Logo passed in by the app, else the shared logo.py, else LOGO_IMAGE, else the built-in Centrum logo."""
    if logo:
        path = Path(logo)
        for candidate in (path, BASE_DIR / path, PROJECT_DIR / path):
            if candidate.is_file():
                return _image_uri(candidate)
    try:
        from logo import LOGO_URI  # logo.py sits next to login.py and app.py

        return LOGO_URI
    except ImportError:
        pass
    uri = _image_uri(_find_image(LOGO_IMAGE, ("logo",)))
    if uri:
        return uri
    return _svg_uri(LOGO_SVG)


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
.cl-panel-logo { margin-bottom: 36px; }
.cl-panel-logo svg { height: 46px; width: auto; display: block; }
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

/* small screens: panel off, card centred, logo shown in the card */
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
.cx-head img { height: 50px; display: block; margin: 0 auto; }
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
        f'<div class="cl-panel-logo">{LOGO_WHITE_SVG}</div>'
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


def _render_header(logo: str | Path | None = None) -> None:
    st.markdown(
        f'<div class="cx-head"><img src="{_logo_uri(logo)}" alt="Centrum Laboratory">'
        f'<div class="cx-sub">{APP_SUBTITLE}</div></div>',
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


def require_login(logo: str | Path | None = None, on_back=None) -> bool:
    """Draw the auth screens unless the user is signed in. Returns True when signed in.

    `logo`: optional path to your logo image (the built-in Centrum logo is used otherwise).
    `on_back`: optional function; when given, a "Back to home" link is shown on the card.
    """
    _page_config()
    _init_state()
    if ss.authenticated:
        return True

    st.markdown(_build_css(), unsafe_allow_html=True)
    _panel()
    # "Check your email" and "Request sent" are stand-alone cards: no logo, no tabs.
    standalone = ss.auth_view == "signup" and ss.signup_step != "form"
    if on_back is not None and not standalone:
        st.button("\u2039 Back to home", key="home_link", on_click=on_back)
    if not standalone:
        _render_header(logo)
        _render_tabs()
    {"login": _render_login, "signup": _render_signup, "reset": _render_reset}[
        ss.auth_view
    ]()
    return False


# ---------------------------------------------------------------------------
# Built-in images (the Centrum logo and the floor plan). Edit only if you know SVG.
# ---------------------------------------------------------------------------
LOGO_SVG = r'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 382 128" width="382" height="128" role="img" aria-label="Centrum Laboratory"><title>Centrum Laboratory</title><defs><linearGradient id="h-room" x1="0" y1="0" x2="0.35" y2="1"><stop offset="0" stop-color="#3b7cf0"/><stop offset="1" stop-color="#1d4ed8"/></linearGradient></defs><mask id="h-cut" maskUnits="userSpaceOnUse"><rect x="2" y="4" width="120" height="120" fill="white"/><rect x="57.60" y="4" width="8.80" height="120" fill="black"/><rect x="2" y="59.60" width="60" height="8.80" fill="black"/></mask>
<path d="M107.70,28.29 A58.00,58.00 0 1 0 107.70,99.71 L88.93,85.04 A34.18,34.18 0 1 1 88.93,42.96 Z" fill="url(#h-room)" mask="url(#h-cut)"/>
<circle cx="62" cy="64" r="23.30" fill="#14213d"/>
<circle cx="62" cy="64" r="13.46" fill="#ffffff"/>
<circle cx="62" cy="64" r="7.25" fill="#2d6fe3"/>
<circle cx="79.13" cy="56.91" r="1.61" fill="#ffffff"/>
<circle cx="69.09" cy="46.87" r="1.61" fill="#ffffff"/>
<circle cx="54.91" cy="46.87" r="1.61" fill="#ffffff"/>
<circle cx="44.87" cy="56.91" r="1.61" fill="#ffffff"/>
<circle cx="44.87" cy="71.09" r="1.61" fill="#ffffff"/>
<circle cx="54.91" cy="81.13" r="1.61" fill="#ffffff"/>
<circle cx="69.09" cy="81.13" r="1.61" fill="#ffffff"/>
<circle cx="79.13" cy="71.09" r="1.61" fill="#ffffff"/><path d="M151.67000000000002 60.34H124.58Q124.86 63.98 126.92500000000001 65.905Q128.99 67.83 132.0 67.83Q136.48 67.83 138.23 64.05H150.97Q149.99 67.9 147.435 70.98Q144.88 74.06 141.03 75.81Q137.18 77.56 132.42000000000002 77.56Q126.68 77.56 122.2 75.11Q117.72 72.66 115.19999999999999 68.11Q112.67999999999999 63.56 112.67999999999999 57.47Q112.67999999999999 51.379999999999995 115.16499999999999 46.83Q117.65 42.279999999999994 122.13 39.83Q126.61 37.379999999999995 132.42000000000002 37.379999999999995Q138.09 37.379999999999995 142.5 39.75999999999999Q146.91 42.13999999999999 149.39499999999998 46.55Q151.88 50.959999999999994 151.88 56.839999999999996Q151.88 58.519999999999996 151.67000000000002 60.34ZM139.63 53.69Q139.63 50.61 137.53 48.79Q135.43 46.97 132.28 46.97Q129.27 46.97 127.20500000000001 48.72Q125.14 50.47 124.65 53.69ZM195.83 54.17999999999999V77.0H183.93V55.79Q183.93 51.87 181.9 49.7Q179.87 47.53 176.44000000000003 47.53Q173.01000000000002 47.53 170.98000000000002 49.7Q168.95000000000002 51.87 168.95000000000002 55.79V77.0H156.98000000000002V37.94H168.95000000000002V43.12Q170.77 40.529999999999994 173.85000000000002 39.02499999999999Q176.93 37.519999999999996 180.78000000000003 37.519999999999996Q187.64000000000001 37.519999999999996 191.735 41.964999999999996Q195.83 46.41 195.83 54.17999999999999ZM224.73000000000005 66.85V77.0H218.64000000000004Q212.13000000000002 77.0 208.49 73.815Q204.85000000000002 70.63 204.85000000000002 63.42V47.879999999999995H200.09000000000003V37.94H204.85000000000002V28.419999999999995H216.82000000000005V37.94H224.66000000000003V47.879999999999995H216.82000000000005V63.56Q216.82000000000005 65.31 217.66000000000003 66.08Q218.50000000000003 66.85 220.46000000000004 66.85ZM254.40000000000003 37.519999999999996V50.19H251.11000000000004Q246.63000000000002 50.19 244.39000000000004 52.114999999999995Q242.15000000000003 54.04 242.15000000000003 58.87V77.0H230.18000000000004V37.94H242.15000000000003V44.449999999999996Q244.25000000000003 41.23 247.40000000000003 39.375Q250.55000000000004 37.519999999999996 254.40000000000003 37.519999999999996ZM297.51000000000005 37.94V77.0H285.5400000000001V71.68Q283.72 74.27 280.605 75.845Q277.49000000000007 77.42 273.71000000000004 77.42Q269.2300000000001 77.42 265.80000000000007 75.42500000000001Q262.37000000000006 73.43 260.48 69.65Q258.59000000000003 65.87 258.59000000000003 60.76V37.94H270.49000000000007V59.15Q270.49000000000007 63.07 272.5200000000001 65.24Q274.55000000000007 67.41 277.9800000000001 67.41Q281.4800000000001 67.41 283.5100000000001 65.24Q285.5400000000001 63.07 285.5400000000001 59.15V37.94ZM370.6500000000001 54.17999999999999V77.0H358.7500000000001V55.79Q358.7500000000001 52.01 356.7550000000001 49.94499999999999Q354.7600000000001 47.879999999999995 351.2600000000001 47.879999999999995Q347.7600000000001 47.879999999999995 345.7650000000001 49.94499999999999Q343.7700000000001 52.01 343.7700000000001 55.79V77.0H331.8700000000001V55.79Q331.8700000000001 52.01 329.8750000000001 49.94499999999999Q327.8800000000001 47.879999999999995 324.3800000000001 47.879999999999995Q320.8800000000001 47.879999999999995 318.8850000000001 49.94499999999999Q316.8900000000001 52.01 316.8900000000001 55.79V77.0H304.9200000000001V37.94H316.8900000000001V42.839999999999996Q318.7100000000001 40.38999999999999 321.6500000000001 38.955Q324.5900000000001 37.519999999999996 328.3000000000001 37.519999999999996Q332.7100000000001 37.519999999999996 336.17500000000007 39.41Q339.6400000000001 41.3 341.6000000000001 44.8Q343.6300000000001 41.58 347.1300000000001 39.55Q350.6300000000001 37.519999999999996 354.7600000000001 37.519999999999996Q362.0400000000001 37.519999999999996 366.3450000000001 41.92999999999999Q370.6500000000001 46.339999999999996 370.6500000000001 54.17999999999999Z" fill="#14213d"/><path d="M117.445 109.7H123.32V112.0H114.595V94.625H117.445ZM147.33277777777778 108.45H140.05777777777777L138.80777777777777 112.0H135.83277777777778L142.05777777777777 94.6H145.35777777777778L151.58277777777778 112.0H148.58277777777778ZM146.5327777777778 106.125 143.70777777777778 98.05 140.85777777777778 106.125ZM178.0955555555556 107.325Q178.0955555555556 108.65 177.4080555555556 109.7125Q176.7205555555556 110.775 175.4205555555556 111.3875Q174.1205555555556 112.0 172.39555555555557 112.0H165.4455555555556V94.625H172.0705555555556Q173.8455555555556 94.625 175.1205555555556 95.225Q176.39555555555557 95.825 177.04555555555558 96.8375Q177.6955555555556 97.85 177.6955555555556 99.1Q177.6955555555556 100.6 176.89555555555557 101.6Q176.0955555555556 102.6 174.7455555555556 103.075Q176.14555555555557 103.325 177.1205555555556 104.55000000000001Q178.0955555555556 105.775 178.0955555555556 107.325ZM168.29555555555558 101.925H171.8205555555556Q173.2205555555556 101.925 174.0080555555556 101.2875Q174.79555555555558 100.65 174.79555555555558 99.45Q174.79555555555558 98.275 174.0080555555556 97.61250000000001Q173.2205555555556 96.95 171.8205555555556 96.95H168.29555555555558ZM175.2455555555556 107.025Q175.2455555555556 105.75 174.3705555555556 105.0Q173.4955555555556 104.25 172.04555555555558 104.25H168.29555555555558V109.675H172.14555555555557Q173.5955555555556 109.675 174.4205555555556 108.975Q175.2455555555556 108.275 175.2455555555556 107.025ZM191.4083333333334 103.275Q191.4083333333334 100.725 192.5958333333334 98.69999999999999Q193.7833333333334 96.675 195.82083333333338 95.5375Q197.85833333333338 94.4 200.2833333333334 94.4Q202.73333333333338 94.4 204.77083333333337 95.5375Q206.80833333333337 96.675 207.98333333333338 98.69999999999999Q209.1583333333334 100.725 209.1583333333334 103.275Q209.1583333333334 105.825 207.98333333333338 107.86250000000001Q206.80833333333337 109.9 204.77083333333337 111.0375Q202.73333333333338 112.175 200.2833333333334 112.175Q197.85833333333338 112.175 195.82083333333338 111.0375Q193.7833333333334 109.9 192.5958333333334 107.86250000000001Q191.4083333333334 105.825 191.4083333333334 103.275ZM206.23333333333338 103.275Q206.23333333333338 101.35 205.47083333333336 99.9Q204.70833333333337 98.45 203.35833333333338 97.67500000000001Q202.00833333333338 96.9 200.2833333333334 96.9Q198.55833333333337 96.9 197.20833333333337 97.67500000000001Q195.85833333333338 98.45 195.09583333333336 99.9Q194.33333333333337 101.35 194.33333333333337 103.275Q194.33333333333337 105.2 195.09583333333336 106.6625Q195.85833333333338 108.125 197.20833333333337 108.9125Q198.55833333333337 109.7 200.2833333333334 109.7Q202.00833333333338 109.7 203.35833333333338 108.9125Q204.70833333333337 108.125 205.47083333333336 106.6625Q206.23333333333338 105.2 206.23333333333338 103.275ZM232.14611111111117 112.0 228.14611111111117 105.05H225.97111111111116V112.0H223.12111111111116V94.625H229.12111111111116Q231.12111111111116 94.625 232.50861111111118 95.325Q233.89611111111117 96.025 234.58361111111117 97.2Q235.27111111111117 98.375 235.27111111111117 99.825Q235.27111111111117 101.525 234.28361111111116 102.9125Q233.29611111111117 104.3 231.24611111111116 104.8L235.54611111111117 112.0ZM225.97111111111116 102.775H229.12111111111116Q230.72111111111116 102.775 231.53361111111116 101.975Q232.34611111111116 101.175 232.34611111111116 99.825Q232.34611111111116 98.475 231.54611111111114 97.7125Q230.74611111111116 96.95 229.12111111111116 96.95H225.97111111111116ZM260.558888888889 108.45H253.28388888888895L252.03388888888895 112.0H249.05888888888896L255.28388888888895 94.6H258.58388888888896L264.808888888889 112.0H261.808888888889ZM259.758888888889 106.125 256.933888888889 98.05 254.08388888888896 106.125ZM289.89666666666676 94.625V96.95H285.27166666666676V112.0H282.42166666666674V96.95H277.77166666666676V94.625ZM302.98444444444453 103.275Q302.98444444444453 100.725 304.17194444444453 98.69999999999999Q305.35944444444453 96.675 307.39694444444456 95.5375Q309.4344444444445 94.4 311.85944444444453 94.4Q314.3094444444445 94.4 316.3469444444445 95.5375Q318.3844444444445 96.675 319.5594444444445 98.69999999999999Q320.73444444444453 100.725 320.73444444444453 103.275Q320.73444444444453 105.825 319.5594444444445 107.86250000000001Q318.3844444444445 109.9 316.3469444444445 111.0375Q314.3094444444445 112.175 311.85944444444453 112.175Q309.4344444444445 112.175 307.39694444444456 111.0375Q305.35944444444453 109.9 304.17194444444453 107.86250000000001Q302.98444444444453 105.825 302.98444444444453 103.275ZM317.8094444444445 103.275Q317.8094444444445 101.35 317.04694444444453 99.9Q316.28444444444455 98.45 314.9344444444445 97.67500000000001Q313.5844444444445 96.9 311.85944444444453 96.9Q310.1344444444445 96.9 308.7844444444445 97.67500000000001Q307.4344444444445 98.45 306.67194444444453 99.9Q305.90944444444455 101.35 305.90944444444455 103.275Q305.90944444444455 105.2 306.67194444444453 106.6625Q307.4344444444445 108.125 308.7844444444445 108.9125Q310.1344444444445 109.7 311.85944444444453 109.7Q313.5844444444445 109.7 314.9344444444445 108.9125Q316.28444444444455 108.125 317.04694444444453 106.6625Q317.8094444444445 105.2 317.8094444444445 103.275ZM343.7222222222223 112.0 339.7222222222223 105.05H337.54722222222233V112.0H334.6972222222223V94.625H340.6972222222223Q342.6972222222223 94.625 344.0847222222223 95.325Q345.4722222222223 96.025 346.1597222222223 97.2Q346.8472222222223 98.375 346.8472222222223 99.825Q346.8472222222223 101.525 345.85972222222233 102.9125Q344.8722222222223 104.3 342.8222222222223 104.8L347.1222222222223 112.0ZM337.54722222222233 102.775H340.6972222222223Q342.29722222222233 102.775 343.10972222222233 101.975Q343.92222222222233 101.175 343.92222222222233 99.825Q343.92222222222233 98.475 343.1222222222223 97.7125Q342.3222222222223 96.95 340.6972222222223 96.95H337.54722222222233ZM374.5350000000001 94.625 368.7850000000001 105.7V112.0H365.93500000000006V105.7L360.1600000000001 94.625H363.3350000000001L367.36000000000007 103.15L371.3850000000001 94.625Z" fill="#14213d"/></svg>'''

LOGO_WHITE_SVG = r'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 382 128" role="img" aria-label="Centrum Laboratory"><title>Centrum Laboratory</title><defs><linearGradient id="hd-room" x1="0" y1="0" x2="0.35" y2="1"><stop offset="0" stop-color="#5b93f5"/><stop offset="1" stop-color="#2d6fe3"/></linearGradient></defs><mask id="hd-cut" maskUnits="userSpaceOnUse"><rect x="2" y="4" width="120" height="120" fill="white"/><rect x="57.60" y="4" width="8.80" height="120" fill="black"/><rect x="2" y="59.60" width="60" height="8.80" fill="black"/></mask>
<path d="M107.70,28.29 A58.00,58.00 0 1 0 107.70,99.71 L88.93,85.04 A34.18,34.18 0 1 1 88.93,42.96 Z" fill="url(#hd-room)" mask="url(#hd-cut)"/>
<circle cx="62" cy="64" r="23.30" fill="#ffffff"/>
<circle cx="62" cy="64" r="13.46" fill="#0f1a33"/>
<circle cx="62" cy="64" r="7.25" fill="#2d6fe3"/>
<circle cx="79.13" cy="56.91" r="1.61" fill="#0f1a33"/>
<circle cx="69.09" cy="46.87" r="1.61" fill="#0f1a33"/>
<circle cx="54.91" cy="46.87" r="1.61" fill="#0f1a33"/>
<circle cx="44.87" cy="56.91" r="1.61" fill="#0f1a33"/>
<circle cx="44.87" cy="71.09" r="1.61" fill="#0f1a33"/>
<circle cx="54.91" cy="81.13" r="1.61" fill="#0f1a33"/>
<circle cx="69.09" cy="81.13" r="1.61" fill="#0f1a33"/>
<circle cx="79.13" cy="71.09" r="1.61" fill="#0f1a33"/><path d="M151.67000000000002 60.34H124.58Q124.86 63.98 126.92500000000001 65.905Q128.99 67.83 132.0 67.83Q136.48 67.83 138.23 64.05H150.97Q149.99 67.9 147.435 70.98Q144.88 74.06 141.03 75.81Q137.18 77.56 132.42000000000002 77.56Q126.68 77.56 122.2 75.11Q117.72 72.66 115.19999999999999 68.11Q112.67999999999999 63.56 112.67999999999999 57.47Q112.67999999999999 51.379999999999995 115.16499999999999 46.83Q117.65 42.279999999999994 122.13 39.83Q126.61 37.379999999999995 132.42000000000002 37.379999999999995Q138.09 37.379999999999995 142.5 39.75999999999999Q146.91 42.13999999999999 149.39499999999998 46.55Q151.88 50.959999999999994 151.88 56.839999999999996Q151.88 58.519999999999996 151.67000000000002 60.34ZM139.63 53.69Q139.63 50.61 137.53 48.79Q135.43 46.97 132.28 46.97Q129.27 46.97 127.20500000000001 48.72Q125.14 50.47 124.65 53.69ZM195.83 54.17999999999999V77.0H183.93V55.79Q183.93 51.87 181.9 49.7Q179.87 47.53 176.44000000000003 47.53Q173.01000000000002 47.53 170.98000000000002 49.7Q168.95000000000002 51.87 168.95000000000002 55.79V77.0H156.98000000000002V37.94H168.95000000000002V43.12Q170.77 40.529999999999994 173.85000000000002 39.02499999999999Q176.93 37.519999999999996 180.78000000000003 37.519999999999996Q187.64000000000001 37.519999999999996 191.735 41.964999999999996Q195.83 46.41 195.83 54.17999999999999ZM224.73000000000005 66.85V77.0H218.64000000000004Q212.13000000000002 77.0 208.49 73.815Q204.85000000000002 70.63 204.85000000000002 63.42V47.879999999999995H200.09000000000003V37.94H204.85000000000002V28.419999999999995H216.82000000000005V37.94H224.66000000000003V47.879999999999995H216.82000000000005V63.56Q216.82000000000005 65.31 217.66000000000003 66.08Q218.50000000000003 66.85 220.46000000000004 66.85ZM254.40000000000003 37.519999999999996V50.19H251.11000000000004Q246.63000000000002 50.19 244.39000000000004 52.114999999999995Q242.15000000000003 54.04 242.15000000000003 58.87V77.0H230.18000000000004V37.94H242.15000000000003V44.449999999999996Q244.25000000000003 41.23 247.40000000000003 39.375Q250.55000000000004 37.519999999999996 254.40000000000003 37.519999999999996ZM297.51000000000005 37.94V77.0H285.5400000000001V71.68Q283.72 74.27 280.605 75.845Q277.49000000000007 77.42 273.71000000000004 77.42Q269.2300000000001 77.42 265.80000000000007 75.42500000000001Q262.37000000000006 73.43 260.48 69.65Q258.59000000000003 65.87 258.59000000000003 60.76V37.94H270.49000000000007V59.15Q270.49000000000007 63.07 272.5200000000001 65.24Q274.55000000000007 67.41 277.9800000000001 67.41Q281.4800000000001 67.41 283.5100000000001 65.24Q285.5400000000001 63.07 285.5400000000001 59.15V37.94ZM370.6500000000001 54.17999999999999V77.0H358.7500000000001V55.79Q358.7500000000001 52.01 356.7550000000001 49.94499999999999Q354.7600000000001 47.879999999999995 351.2600000000001 47.879999999999995Q347.7600000000001 47.879999999999995 345.7650000000001 49.94499999999999Q343.7700000000001 52.01 343.7700000000001 55.79V77.0H331.8700000000001V55.79Q331.8700000000001 52.01 329.8750000000001 49.94499999999999Q327.8800000000001 47.879999999999995 324.3800000000001 47.879999999999995Q320.8800000000001 47.879999999999995 318.8850000000001 49.94499999999999Q316.8900000000001 52.01 316.8900000000001 55.79V77.0H304.9200000000001V37.94H316.8900000000001V42.839999999999996Q318.7100000000001 40.38999999999999 321.6500000000001 38.955Q324.5900000000001 37.519999999999996 328.3000000000001 37.519999999999996Q332.7100000000001 37.519999999999996 336.17500000000007 39.41Q339.6400000000001 41.3 341.6000000000001 44.8Q343.6300000000001 41.58 347.1300000000001 39.55Q350.6300000000001 37.519999999999996 354.7600000000001 37.519999999999996Q362.0400000000001 37.519999999999996 366.3450000000001 41.92999999999999Q370.6500000000001 46.339999999999996 370.6500000000001 54.17999999999999Z" fill="#ffffff"/><path d="M117.445 109.7H123.32V112.0H114.595V94.625H117.445ZM147.33277777777778 108.45H140.05777777777777L138.80777777777777 112.0H135.83277777777778L142.05777777777777 94.6H145.35777777777778L151.58277777777778 112.0H148.58277777777778ZM146.5327777777778 106.125 143.70777777777778 98.05 140.85777777777778 106.125ZM178.0955555555556 107.325Q178.0955555555556 108.65 177.4080555555556 109.7125Q176.7205555555556 110.775 175.4205555555556 111.3875Q174.1205555555556 112.0 172.39555555555557 112.0H165.4455555555556V94.625H172.0705555555556Q173.8455555555556 94.625 175.1205555555556 95.225Q176.39555555555557 95.825 177.04555555555558 96.8375Q177.6955555555556 97.85 177.6955555555556 99.1Q177.6955555555556 100.6 176.89555555555557 101.6Q176.0955555555556 102.6 174.7455555555556 103.075Q176.14555555555557 103.325 177.1205555555556 104.55000000000001Q178.0955555555556 105.775 178.0955555555556 107.325ZM168.29555555555558 101.925H171.8205555555556Q173.2205555555556 101.925 174.0080555555556 101.2875Q174.79555555555558 100.65 174.79555555555558 99.45Q174.79555555555558 98.275 174.0080555555556 97.61250000000001Q173.2205555555556 96.95 171.8205555555556 96.95H168.29555555555558ZM175.2455555555556 107.025Q175.2455555555556 105.75 174.3705555555556 105.0Q173.4955555555556 104.25 172.04555555555558 104.25H168.29555555555558V109.675H172.14555555555557Q173.5955555555556 109.675 174.4205555555556 108.975Q175.2455555555556 108.275 175.2455555555556 107.025ZM191.4083333333334 103.275Q191.4083333333334 100.725 192.5958333333334 98.69999999999999Q193.7833333333334 96.675 195.82083333333338 95.5375Q197.85833333333338 94.4 200.2833333333334 94.4Q202.73333333333338 94.4 204.77083333333337 95.5375Q206.80833333333337 96.675 207.98333333333338 98.69999999999999Q209.1583333333334 100.725 209.1583333333334 103.275Q209.1583333333334 105.825 207.98333333333338 107.86250000000001Q206.80833333333337 109.9 204.77083333333337 111.0375Q202.73333333333338 112.175 200.2833333333334 112.175Q197.85833333333338 112.175 195.82083333333338 111.0375Q193.7833333333334 109.9 192.5958333333334 107.86250000000001Q191.4083333333334 105.825 191.4083333333334 103.275ZM206.23333333333338 103.275Q206.23333333333338 101.35 205.47083333333336 99.9Q204.70833333333337 98.45 203.35833333333338 97.67500000000001Q202.00833333333338 96.9 200.2833333333334 96.9Q198.55833333333337 96.9 197.20833333333337 97.67500000000001Q195.85833333333338 98.45 195.09583333333336 99.9Q194.33333333333337 101.35 194.33333333333337 103.275Q194.33333333333337 105.2 195.09583333333336 106.6625Q195.85833333333338 108.125 197.20833333333337 108.9125Q198.55833333333337 109.7 200.2833333333334 109.7Q202.00833333333338 109.7 203.35833333333338 108.9125Q204.70833333333337 108.125 205.47083333333336 106.6625Q206.23333333333338 105.2 206.23333333333338 103.275ZM232.14611111111117 112.0 228.14611111111117 105.05H225.97111111111116V112.0H223.12111111111116V94.625H229.12111111111116Q231.12111111111116 94.625 232.50861111111118 95.325Q233.89611111111117 96.025 234.58361111111117 97.2Q235.27111111111117 98.375 235.27111111111117 99.825Q235.27111111111117 101.525 234.28361111111116 102.9125Q233.29611111111117 104.3 231.24611111111116 104.8L235.54611111111117 112.0ZM225.97111111111116 102.775H229.12111111111116Q230.72111111111116 102.775 231.53361111111116 101.975Q232.34611111111116 101.175 232.34611111111116 99.825Q232.34611111111116 98.475 231.54611111111114 97.7125Q230.74611111111116 96.95 229.12111111111116 96.95H225.97111111111116ZM260.558888888889 108.45H253.28388888888895L252.03388888888895 112.0H249.05888888888896L255.28388888888895 94.6H258.58388888888896L264.808888888889 112.0H261.808888888889ZM259.758888888889 106.125 256.933888888889 98.05 254.08388888888896 106.125ZM289.89666666666676 94.625V96.95H285.27166666666676V112.0H282.42166666666674V96.95H277.77166666666676V94.625ZM302.98444444444453 103.275Q302.98444444444453 100.725 304.17194444444453 98.69999999999999Q305.35944444444453 96.675 307.39694444444456 95.5375Q309.4344444444445 94.4 311.85944444444453 94.4Q314.3094444444445 94.4 316.3469444444445 95.5375Q318.3844444444445 96.675 319.5594444444445 98.69999999999999Q320.73444444444453 100.725 320.73444444444453 103.275Q320.73444444444453 105.825 319.5594444444445 107.86250000000001Q318.3844444444445 109.9 316.3469444444445 111.0375Q314.3094444444445 112.175 311.85944444444453 112.175Q309.4344444444445 112.175 307.39694444444456 111.0375Q305.35944444444453 109.9 304.17194444444453 107.86250000000001Q302.98444444444453 105.825 302.98444444444453 103.275ZM317.8094444444445 103.275Q317.8094444444445 101.35 317.04694444444453 99.9Q316.28444444444455 98.45 314.9344444444445 97.67500000000001Q313.5844444444445 96.9 311.85944444444453 96.9Q310.1344444444445 96.9 308.7844444444445 97.67500000000001Q307.4344444444445 98.45 306.67194444444453 99.9Q305.90944444444455 101.35 305.90944444444455 103.275Q305.90944444444455 105.2 306.67194444444453 106.6625Q307.4344444444445 108.125 308.7844444444445 108.9125Q310.1344444444445 109.7 311.85944444444453 109.7Q313.5844444444445 109.7 314.9344444444445 108.9125Q316.28444444444455 108.125 317.04694444444453 106.6625Q317.8094444444445 105.2 317.8094444444445 103.275ZM343.7222222222223 112.0 339.7222222222223 105.05H337.54722222222233V112.0H334.6972222222223V94.625H340.6972222222223Q342.6972222222223 94.625 344.0847222222223 95.325Q345.4722222222223 96.025 346.1597222222223 97.2Q346.8472222222223 98.375 346.8472222222223 99.825Q346.8472222222223 101.525 345.85972222222233 102.9125Q344.8722222222223 104.3 342.8222222222223 104.8L347.1222222222223 112.0ZM337.54722222222233 102.775H340.6972222222223Q342.29722222222233 102.775 343.10972222222233 101.975Q343.92222222222233 101.175 343.92222222222233 99.825Q343.92222222222233 98.475 343.1222222222223 97.7125Q342.3222222222223 96.95 340.6972222222223 96.95H337.54722222222233ZM374.5350000000001 94.625 368.7850000000001 105.7V112.0H365.93500000000006V105.7L360.1600000000001 94.625H363.3350000000001L367.36000000000007 103.15L371.3850000000001 94.625Z" fill="#c7d7f7"/></svg>'''

BRAND_MAP_SVG = r'''<svg class="cl-map" viewBox="-6 -6 612 612" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><defs><path id="clb-l1" d="M324.5,579.9 A281.0,281.0 0 0 0 579.9,324.5"/><path id="clb-l2" d="M20.1,324.5 A281.0,281.0 0 0 0 275.5,579.9"/><path id="clb-l3" d="M323.8,28.0 A273.0,273.0 0 0 1 572.0,276.2"/><path id="clb-l4" d="M28.0,276.2 A273.0,273.0 0 0 1 276.2,28.0"/></defs><circle cx="300" cy="300" r="277.0" fill="none" stroke="rgba(255,255,255,.04)" stroke-width="30"/><circle cx="300" cy="300" r="292" fill="none" stroke="rgba(255,255,255,.14)" stroke-width="1.5"/><path d="M300.0,556.0 A256,256 0 0 0 556.0,300.0 L422.0,300.0 A122,122 0 0 1 300.0,422.0 Z" fill="rgba(91,147,245,.10)" stroke="rgba(143,179,247,.35)" stroke-width="1.5"/><path d="M44.0,300.0 A256,256 0 0 0 300.0,556.0 L300.0,422.0 A122,122 0 0 1 178.0,300.0 Z" fill="rgba(91,147,245,.10)" stroke="rgba(143,179,247,.35)" stroke-width="1.5"/><path d="M556.0,300.0 A256,256 0 0 0 300.0,44.0 L300.0,178.0 A122,122 0 0 1 422.0,300.0 Z" fill="rgba(91,147,245,.10)" stroke="rgba(143,179,247,.35)" stroke-width="1.5"/><path d="M300.0,44.0 A256,256 0 0 0 44.0,300.0 L178.0,300.0 A122,122 0 0 1 300.0,178.0 Z" fill="rgba(91,147,245,.10)" stroke="rgba(143,179,247,.35)" stroke-width="1.5"/><rect x="277.0" y="42" width="46" height="146" fill="#0f1a33"/><rect x="277.0" y="412" width="46" height="146" fill="#0f1a33"/><rect x="42" y="277.0" width="146" height="46" fill="#0f1a33"/><rect x="412" y="277.0" width="146" height="46" fill="#0f1a33"/><circle cx="300" cy="300" r="98.0" fill="none" stroke="#ffffff" stroke-width="28"/><circle cx="394.7" cy="274.6" r="3.2" fill="#0f1a33"/><circle cx="369.3" cy="230.7" r="3.2" fill="#0f1a33"/><circle cx="325.4" cy="205.3" r="3.2" fill="#0f1a33"/><circle cx="274.6" cy="205.3" r="3.2" fill="#0f1a33"/><circle cx="230.7" cy="230.7" r="3.2" fill="#0f1a33"/><circle cx="205.3" cy="274.6" r="3.2" fill="#0f1a33"/><circle cx="205.3" cy="325.4" r="3.2" fill="#0f1a33"/><circle cx="230.7" cy="369.3" r="3.2" fill="#0f1a33"/><circle cx="274.6" cy="394.7" r="3.2" fill="#0f1a33"/><circle cx="325.4" cy="394.7" r="3.2" fill="#0f1a33"/><circle cx="369.3" cy="369.3" r="3.2" fill="#0f1a33"/><circle cx="394.7" cy="325.4" r="3.2" fill="#0f1a33"/><circle cx="300" cy="300" r="84" fill="#0f1a33"/><circle class="cl-ping" cx="300" cy="300" r="26" fill="none" stroke="#5b93f5" stroke-width="2"/><circle cx="300" cy="300" r="26" fill="#2d6fe3"/><g transform="translate(288 289)" fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><rect x="1" y="1" width="22" height="15" rx="2.5"/><path d="M8 21h8M12 16v5"/></g><rect class="cl-pc cl-ok" x="432.8" y="337.1" width="14" height="10" rx="2.5" transform="rotate(-253.3 439.8 342.1)"/><rect class="cl-pc cl-ok" x="424.0" y="359.4" width="14" height="10" rx="2.5" transform="rotate(-243.8 431.0 364.4)"/><rect class="cl-pc cl-ok" x="411.7" y="380.0" width="14" height="10" rx="2.5" transform="rotate(-234.4 418.7 385.0)"/><rect class="cl-pc cl-ok" x="396.2" y="398.2" width="14" height="10" rx="2.5" transform="rotate(-225.0 403.2 403.2)"/><rect class="cl-pc cl-rep" x="378.0" y="413.7" width="14" height="10" rx="2.5" transform="rotate(-215.6 385.0 418.7)"/><rect class="cl-pc cl-ok" x="357.4" y="426.0" width="14" height="10" rx="2.5" transform="rotate(-206.2 364.4 431.0)"/><rect class="cl-pc cl-ok" x="335.1" y="434.8" width="14" height="10" rx="2.5" transform="rotate(-196.7 342.1 439.8)"/><rect class="cl-pc cl-ok" x="460.6" y="333.8" width="14" height="10" rx="2.5" transform="rotate(-257.0 467.6 338.8)"/><rect class="cl-pc cl-ok" x="453.6" y="356.7" width="14" height="10" rx="2.5" transform="rotate(-249.0 460.6 361.7)"/><rect class="cl-pc cl-ok" x="443.4" y="378.4" width="14" height="10" rx="2.5" transform="rotate(-241.0 450.4 383.4)"/><rect class="cl-pc cl-ok" x="430.4" y="398.5" width="14" height="10" rx="2.5" transform="rotate(-233.0 437.4 403.5)"/><rect class="cl-pc cl-ok" x="414.6" y="416.6" width="14" height="10" rx="2.5" transform="rotate(-225.0 421.6 421.6)"/><rect class="cl-pc cl-ok" x="396.5" y="432.4" width="14" height="10" rx="2.5" transform="rotate(-217.0 403.5 437.4)"/><rect class="cl-pc cl-fix" x="376.4" y="445.4" width="14" height="10" rx="2.5" transform="rotate(-209.0 383.4 450.4)"/><rect class="cl-pc cl-ok" x="354.7" y="455.6" width="14" height="10" rx="2.5" transform="rotate(-201.0 361.7 460.6)"/><rect class="cl-pc cl-ok" x="331.8" y="462.6" width="14" height="10" rx="2.5" transform="rotate(-193.0 338.8 467.6)"/><rect class="cl-pc cl-ok" x="487.8" y="330.3" width="14" height="10" rx="2.5" transform="rotate(-259.7 494.8 335.3)"/><rect class="cl-pc cl-ok" x="482.1" y="353.6" width="14" height="10" rx="2.5" transform="rotate(-252.8 489.1 358.6)"/><rect class="cl-pc cl-ok" x="473.6" y="376.1" width="14" height="10" rx="2.5" transform="rotate(-245.8 480.6 381.1)"/><rect class="cl-pc cl-ok" x="462.5" y="397.3" width="14" height="10" rx="2.5" transform="rotate(-238.9 469.5 402.3)"/><rect class="cl-pc cl-ok" x="448.9" y="417.1" width="14" height="10" rx="2.5" transform="rotate(-231.9 455.9 422.1)"/><rect class="cl-pc cl-ok" x="433.0" y="435.0" width="14" height="10" rx="2.5" transform="rotate(-225.0 440.0 440.0)"/><rect class="cl-pc cl-rep" x="415.1" y="450.9" width="14" height="10" rx="2.5" transform="rotate(-218.1 422.1 455.9)"/><rect class="cl-pc cl-ok" x="395.3" y="464.5" width="14" height="10" rx="2.5" transform="rotate(-211.1 402.3 469.5)"/><rect class="cl-pc cl-ok" x="374.1" y="475.6" width="14" height="10" rx="2.5" transform="rotate(-204.2 381.1 480.6)"/><rect class="cl-pc cl-ok" x="351.6" y="484.1" width="14" height="10" rx="2.5" transform="rotate(-197.2 358.6 489.1)"/><rect class="cl-pc cl-ok" x="328.3" y="489.8" width="14" height="10" rx="2.5" transform="rotate(-190.3 335.3 494.8)"/><rect class="cl-pc cl-ok" x="512.7" y="338.6" width="14" height="10" rx="2.5" transform="rotate(-258.8 519.7 343.6)"/><rect class="cl-pc cl-ok" x="506.8" y="361.9" width="14" height="10" rx="2.5" transform="rotate(-252.6 513.8 366.9)"/><rect class="cl-pc cl-ok" x="498.4" y="384.4" width="14" height="10" rx="2.5" transform="rotate(-246.5 505.4 389.4)"/><rect class="cl-pc cl-ok" x="487.7" y="405.8" width="14" height="10" rx="2.5" transform="rotate(-240.3 494.7 410.8)"/><rect class="cl-pc cl-ok" x="474.7" y="426.0" width="14" height="10" rx="2.5" transform="rotate(-234.2 481.7 431.0)"/><rect class="cl-pc cl-ok" x="459.6" y="444.7" width="14" height="10" rx="2.5" transform="rotate(-228.1 466.6 449.7)"/><rect class="cl-pc cl-ok" x="442.7" y="461.6" width="14" height="10" rx="2.5" transform="rotate(-221.9 449.7 466.6)"/><rect class="cl-pc cl-ok" x="424.0" y="476.7" width="14" height="10" rx="2.5" transform="rotate(-215.8 431.0 481.7)"/><rect class="cl-pc cl-ok" x="403.8" y="489.7" width="14" height="10" rx="2.5" transform="rotate(-209.7 410.8 494.7)"/><rect class="cl-pc cl-ok" x="382.4" y="500.4" width="14" height="10" rx="2.5" transform="rotate(-203.5 389.4 505.4)"/><rect class="cl-pc cl-ok" x="359.9" y="508.8" width="14" height="10" rx="2.5" transform="rotate(-197.4 366.9 513.8)"/><rect class="cl-pc cl-ok" x="336.6" y="514.7" width="14" height="10" rx="2.5" transform="rotate(-191.2 343.6 519.7)"/><rect class="cl-pc cl-ok" x="250.9" y="434.8" width="14" height="10" rx="2.5" transform="rotate(-163.3 257.9 439.8)"/><rect class="cl-pc cl-fix" x="228.6" y="426.0" width="14" height="10" rx="2.5" transform="rotate(-153.8 235.6 431.0)"/><rect class="cl-pc cl-ok" x="208.0" y="413.7" width="14" height="10" rx="2.5" transform="rotate(-144.4 215.0 418.7)"/><rect class="cl-pc cl-ok" x="189.8" y="398.2" width="14" height="10" rx="2.5" transform="rotate(-135.0 196.8 403.2)"/><rect class="cl-pc cl-ok" x="174.3" y="380.0" width="14" height="10" rx="2.5" transform="rotate(-125.6 181.3 385.0)"/><rect class="cl-pc cl-ok" x="162.0" y="359.4" width="14" height="10" rx="2.5" transform="rotate(-116.2 169.0 364.4)"/><rect class="cl-pc cl-ok" x="153.2" y="337.1" width="14" height="10" rx="2.5" transform="rotate(-106.7 160.2 342.1)"/><rect class="cl-pc cl-ok" x="254.2" y="462.6" width="14" height="10" rx="2.5" transform="rotate(-167.0 261.2 467.6)"/><rect class="cl-pc cl-ok" x="231.3" y="455.6" width="14" height="10" rx="2.5" transform="rotate(-159.0 238.3 460.6)"/><rect class="cl-pc cl-ok" x="209.6" y="445.4" width="14" height="10" rx="2.5" transform="rotate(-151.0 216.6 450.4)"/><rect class="cl-pc cl-ok" x="189.5" y="432.4" width="14" height="10" rx="2.5" transform="rotate(-143.0 196.5 437.4)"/><rect class="cl-pc cl-ok" x="171.4" y="416.6" width="14" height="10" rx="2.5" transform="rotate(-135.0 178.4 421.6)"/><rect class="cl-pc cl-ok" x="155.6" y="398.5" width="14" height="10" rx="2.5" transform="rotate(-127.0 162.6 403.5)"/><rect class="cl-pc cl-ok" x="142.6" y="378.4" width="14" height="10" rx="2.5" transform="rotate(-119.0 149.6 383.4)"/><rect class="cl-pc cl-ok" x="132.4" y="356.7" width="14" height="10" rx="2.5" transform="rotate(-111.0 139.4 361.7)"/><rect class="cl-pc cl-ok" x="125.4" y="333.8" width="14" height="10" rx="2.5" transform="rotate(-103.0 132.4 338.8)"/><rect class="cl-pc cl-ok" x="257.7" y="489.8" width="14" height="10" rx="2.5" transform="rotate(-169.7 264.7 494.8)"/><rect class="cl-pc cl-ok" x="234.4" y="484.1" width="14" height="10" rx="2.5" transform="rotate(-162.8 241.4 489.1)"/><rect class="cl-pc cl-ok" x="211.9" y="475.6" width="14" height="10" rx="2.5" transform="rotate(-155.8 218.9 480.6)"/><rect class="cl-pc cl-ok" x="190.7" y="464.5" width="14" height="10" rx="2.5" transform="rotate(-148.9 197.7 469.5)"/><rect class="cl-pc cl-ok" x="170.9" y="450.9" width="14" height="10" rx="2.5" transform="rotate(-141.9 177.9 455.9)"/><rect class="cl-pc cl-ok" x="153.0" y="435.0" width="14" height="10" rx="2.5" transform="rotate(-135.0 160.0 440.0)"/><rect class="cl-pc cl-ok" x="137.1" y="417.1" width="14" height="10" rx="2.5" transform="rotate(-128.1 144.1 422.1)"/><rect class="cl-pc cl-ok" x="123.5" y="397.3" width="14" height="10" rx="2.5" transform="rotate(-121.1 130.5 402.3)"/><rect class="cl-pc cl-ok" x="112.4" y="376.1" width="14" height="10" rx="2.5" transform="rotate(-114.2 119.4 381.1)"/><rect class="cl-pc cl-ok" x="103.9" y="353.6" width="14" height="10" rx="2.5" transform="rotate(-107.2 110.9 358.6)"/><rect class="cl-pc cl-ok" x="98.2" y="330.3" width="14" height="10" rx="2.5" transform="rotate(-100.3 105.2 335.3)"/><rect class="cl-pc cl-ok" x="249.4" y="514.7" width="14" height="10" rx="2.5" transform="rotate(-168.8 256.4 519.7)"/><rect class="cl-pc cl-ok" x="226.1" y="508.8" width="14" height="10" rx="2.5" transform="rotate(-162.6 233.1 513.8)"/><rect class="cl-pc cl-fix" x="203.6" y="500.4" width="14" height="10" rx="2.5" transform="rotate(-156.5 210.6 505.4)"/><rect class="cl-pc cl-ok" x="182.2" y="489.7" width="14" height="10" rx="2.5" transform="rotate(-150.3 189.2 494.7)"/><rect class="cl-pc cl-ok" x="162.0" y="476.7" width="14" height="10" rx="2.5" transform="rotate(-144.2 169.0 481.7)"/><rect class="cl-pc cl-ok" x="143.3" y="461.6" width="14" height="10" rx="2.5" transform="rotate(-138.1 150.3 466.6)"/><rect class="cl-pc cl-ok" x="126.4" y="444.7" width="14" height="10" rx="2.5" transform="rotate(-131.9 133.4 449.7)"/><rect class="cl-pc cl-ok" x="111.3" y="426.0" width="14" height="10" rx="2.5" transform="rotate(-125.8 118.3 431.0)"/><rect class="cl-pc cl-ok" x="98.3" y="405.8" width="14" height="10" rx="2.5" transform="rotate(-119.7 105.3 410.8)"/><rect class="cl-pc cl-ok" x="87.6" y="384.4" width="14" height="10" rx="2.5" transform="rotate(-113.5 94.6 389.4)"/><rect class="cl-pc cl-ok" x="79.2" y="361.9" width="14" height="10" rx="2.5" transform="rotate(-107.4 86.2 366.9)"/><rect class="cl-pc cl-ok" x="73.3" y="338.6" width="14" height="10" rx="2.5" transform="rotate(-101.2 80.3 343.6)"/><rect class="cl-pc cl-ok" x="335.1" y="155.2" width="14" height="10" rx="2.5" transform="rotate(16.7 342.1 160.2)"/><rect class="cl-pc cl-ok" x="357.4" y="164.0" width="14" height="10" rx="2.5" transform="rotate(26.2 364.4 169.0)"/><rect class="cl-pc cl-rep" x="378.0" y="176.3" width="14" height="10" rx="2.5" transform="rotate(35.6 385.0 181.3)"/><rect class="cl-pc cl-ok" x="396.2" y="191.8" width="14" height="10" rx="2.5" transform="rotate(45.0 403.2 196.8)"/><rect class="cl-pc cl-ok" x="411.7" y="210.0" width="14" height="10" rx="2.5" transform="rotate(54.4 418.7 215.0)"/><rect class="cl-pc cl-ok" x="424.0" y="230.6" width="14" height="10" rx="2.5" transform="rotate(63.8 431.0 235.6)"/><rect class="cl-pc cl-ok" x="432.8" y="252.9" width="14" height="10" rx="2.5" transform="rotate(73.3 439.8 257.9)"/><rect class="cl-pc cl-ok" x="331.8" y="127.4" width="14" height="10" rx="2.5" transform="rotate(13.0 338.8 132.4)"/><rect class="cl-pc cl-ok" x="354.7" y="134.4" width="14" height="10" rx="2.5" transform="rotate(21.0 361.7 139.4)"/><rect class="cl-pc cl-ok" x="376.4" y="144.6" width="14" height="10" rx="2.5" transform="rotate(29.0 383.4 149.6)"/><rect class="cl-pc cl-ok" x="396.5" y="157.6" width="14" height="10" rx="2.5" transform="rotate(37.0 403.5 162.6)"/><rect class="cl-pc cl-rep" x="414.6" y="173.4" width="14" height="10" rx="2.5" transform="rotate(45.0 421.6 178.4)"/><rect class="cl-pc cl-ok" x="430.4" y="191.5" width="14" height="10" rx="2.5" transform="rotate(53.0 437.4 196.5)"/><rect class="cl-pc cl-ok" x="443.4" y="211.6" width="14" height="10" rx="2.5" transform="rotate(61.0 450.4 216.6)"/><rect class="cl-pc cl-ok" x="453.6" y="233.3" width="14" height="10" rx="2.5" transform="rotate(69.0 460.6 238.3)"/><rect class="cl-pc cl-ok" x="460.6" y="256.2" width="14" height="10" rx="2.5" transform="rotate(77.0 467.6 261.2)"/><rect class="cl-pc cl-ok" x="328.3" y="100.2" width="14" height="10" rx="2.5" transform="rotate(10.3 335.3 105.2)"/><rect class="cl-pc cl-ok" x="351.6" y="105.9" width="14" height="10" rx="2.5" transform="rotate(17.2 358.6 110.9)"/><rect class="cl-pc cl-ok" x="374.1" y="114.4" width="14" height="10" rx="2.5" transform="rotate(24.2 381.1 119.4)"/><rect class="cl-pc cl-ok" x="395.3" y="125.5" width="14" height="10" rx="2.5" transform="rotate(31.1 402.3 130.5)"/><rect class="cl-pc cl-ok" x="415.1" y="139.1" width="14" height="10" rx="2.5" transform="rotate(38.1 422.1 144.1)"/><rect class="cl-pc cl-ok" x="433.0" y="155.0" width="14" height="10" rx="2.5" transform="rotate(45.0 440.0 160.0)"/><rect class="cl-pc cl-ok" x="448.9" y="172.9" width="14" height="10" rx="2.5" transform="rotate(51.9 455.9 177.9)"/><rect class="cl-pc cl-ok" x="462.5" y="192.7" width="14" height="10" rx="2.5" transform="rotate(58.9 469.5 197.7)"/><rect class="cl-pc cl-ok" x="473.6" y="213.9" width="14" height="10" rx="2.5" transform="rotate(65.8 480.6 218.9)"/><rect class="cl-pc cl-ok" x="482.1" y="236.4" width="14" height="10" rx="2.5" transform="rotate(72.8 489.1 241.4)"/><rect class="cl-pc cl-rep" x="487.8" y="259.7" width="14" height="10" rx="2.5" transform="rotate(79.7 494.8 264.7)"/><rect class="cl-pc cl-ok" x="336.6" y="75.3" width="14" height="10" rx="2.5" transform="rotate(11.2 343.6 80.3)"/><rect class="cl-pc cl-ok" x="359.9" y="81.2" width="14" height="10" rx="2.5" transform="rotate(17.4 366.9 86.2)"/><rect class="cl-pc cl-ok" x="382.4" y="89.6" width="14" height="10" rx="2.5" transform="rotate(23.5 389.4 94.6)"/><rect class="cl-pc cl-ok" x="403.8" y="100.3" width="14" height="10" rx="2.5" transform="rotate(29.7 410.8 105.3)"/><rect class="cl-pc cl-ok" x="424.0" y="113.3" width="14" height="10" rx="2.5" transform="rotate(35.8 431.0 118.3)"/><rect class="cl-pc cl-ok" x="442.7" y="128.4" width="14" height="10" rx="2.5" transform="rotate(41.9 449.7 133.4)"/><rect class="cl-pc cl-ok" x="459.6" y="145.3" width="14" height="10" rx="2.5" transform="rotate(48.1 466.6 150.3)"/><rect class="cl-pc cl-ok" x="474.7" y="164.0" width="14" height="10" rx="2.5" transform="rotate(54.2 481.7 169.0)"/><rect class="cl-pc cl-ok" x="487.7" y="184.2" width="14" height="10" rx="2.5" transform="rotate(60.3 494.7 189.2)"/><rect class="cl-pc cl-ok" x="498.4" y="205.6" width="14" height="10" rx="2.5" transform="rotate(66.5 505.4 210.6)"/><rect class="cl-pc cl-ok" x="506.8" y="228.1" width="14" height="10" rx="2.5" transform="rotate(72.6 513.8 233.1)"/><rect class="cl-pc cl-ok" x="512.7" y="251.4" width="14" height="10" rx="2.5" transform="rotate(78.8 519.7 256.4)"/><rect class="cl-pc cl-ok" x="153.2" y="252.9" width="14" height="10" rx="2.5" transform="rotate(-73.3 160.2 257.9)"/><rect class="cl-pc cl-ok" x="162.0" y="230.6" width="14" height="10" rx="2.5" transform="rotate(-63.8 169.0 235.6)"/><rect class="cl-pc cl-ok" x="174.3" y="210.0" width="14" height="10" rx="2.5" transform="rotate(-54.4 181.3 215.0)"/><rect class="cl-pc cl-ok" x="189.8" y="191.8" width="14" height="10" rx="2.5" transform="rotate(-45.0 196.8 196.8)"/><rect class="cl-pc cl-ok" x="208.0" y="176.3" width="14" height="10" rx="2.5" transform="rotate(-35.6 215.0 181.3)"/><rect class="cl-pc cl-ok" x="228.6" y="164.0" width="14" height="10" rx="2.5" transform="rotate(-26.2 235.6 169.0)"/><rect class="cl-pc cl-ok" x="250.9" y="155.2" width="14" height="10" rx="2.5" transform="rotate(-16.7 257.9 160.2)"/><rect class="cl-pc cl-ok" x="125.4" y="256.2" width="14" height="10" rx="2.5" transform="rotate(-77.0 132.4 261.2)"/><rect class="cl-pc cl-ok" x="132.4" y="233.3" width="14" height="10" rx="2.5" transform="rotate(-69.0 139.4 238.3)"/><rect class="cl-pc cl-ok" x="142.6" y="211.6" width="14" height="10" rx="2.5" transform="rotate(-61.0 149.6 216.6)"/><rect class="cl-pc cl-fix" x="155.6" y="191.5" width="14" height="10" rx="2.5" transform="rotate(-53.0 162.6 196.5)"/><rect class="cl-pc cl-ok" x="171.4" y="173.4" width="14" height="10" rx="2.5" transform="rotate(-45.0 178.4 178.4)"/><rect class="cl-pc cl-ok" x="189.5" y="157.6" width="14" height="10" rx="2.5" transform="rotate(-37.0 196.5 162.6)"/><rect class="cl-pc cl-ok" x="209.6" y="144.6" width="14" height="10" rx="2.5" transform="rotate(-29.0 216.6 149.6)"/><rect class="cl-pc cl-ok" x="231.3" y="134.4" width="14" height="10" rx="2.5" transform="rotate(-21.0 238.3 139.4)"/><rect class="cl-pc cl-ok" x="254.2" y="127.4" width="14" height="10" rx="2.5" transform="rotate(-13.0 261.2 132.4)"/><rect class="cl-pc cl-ok" x="98.2" y="259.7" width="14" height="10" rx="2.5" transform="rotate(-79.7 105.2 264.7)"/><rect class="cl-pc cl-ok" x="103.9" y="236.4" width="14" height="10" rx="2.5" transform="rotate(-72.8 110.9 241.4)"/><rect class="cl-pc cl-ok" x="112.4" y="213.9" width="14" height="10" rx="2.5" transform="rotate(-65.8 119.4 218.9)"/><rect class="cl-pc cl-ok" x="123.5" y="192.7" width="14" height="10" rx="2.5" transform="rotate(-58.9 130.5 197.7)"/><rect class="cl-pc cl-fix" x="137.1" y="172.9" width="14" height="10" rx="2.5" transform="rotate(-51.9 144.1 177.9)"/><rect class="cl-pc cl-ok" x="153.0" y="155.0" width="14" height="10" rx="2.5" transform="rotate(-45.0 160.0 160.0)"/><rect class="cl-pc cl-ok" x="170.9" y="139.1" width="14" height="10" rx="2.5" transform="rotate(-38.1 177.9 144.1)"/><rect class="cl-pc cl-ok" x="190.7" y="125.5" width="14" height="10" rx="2.5" transform="rotate(-31.1 197.7 130.5)"/><rect class="cl-pc cl-ok" x="211.9" y="114.4" width="14" height="10" rx="2.5" transform="rotate(-24.2 218.9 119.4)"/><rect class="cl-pc cl-ok" x="234.4" y="105.9" width="14" height="10" rx="2.5" transform="rotate(-17.2 241.4 110.9)"/><rect class="cl-pc cl-ok" x="257.7" y="100.2" width="14" height="10" rx="2.5" transform="rotate(-10.3 264.7 105.2)"/><rect class="cl-pc cl-ok" x="73.3" y="251.4" width="14" height="10" rx="2.5" transform="rotate(-78.8 80.3 256.4)"/><rect class="cl-pc cl-ok" x="79.2" y="228.1" width="14" height="10" rx="2.5" transform="rotate(-72.6 86.2 233.1)"/><rect class="cl-pc cl-ok" x="87.6" y="205.6" width="14" height="10" rx="2.5" transform="rotate(-66.5 94.6 210.6)"/><rect class="cl-pc cl-ok" x="98.3" y="184.2" width="14" height="10" rx="2.5" transform="rotate(-60.3 105.3 189.2)"/><rect class="cl-pc cl-ok" x="111.3" y="164.0" width="14" height="10" rx="2.5" transform="rotate(-54.2 118.3 169.0)"/><rect class="cl-pc cl-ok" x="126.4" y="145.3" width="14" height="10" rx="2.5" transform="rotate(-48.1 133.4 150.3)"/><rect class="cl-pc cl-ok" x="143.3" y="128.4" width="14" height="10" rx="2.5" transform="rotate(-41.9 150.3 133.4)"/><rect class="cl-pc cl-ok" x="162.0" y="113.3" width="14" height="10" rx="2.5" transform="rotate(-35.8 169.0 118.3)"/><rect class="cl-pc cl-ok" x="182.2" y="100.3" width="14" height="10" rx="2.5" transform="rotate(-29.7 189.2 105.3)"/><rect class="cl-pc cl-ok" x="203.6" y="89.6" width="14" height="10" rx="2.5" transform="rotate(-23.5 210.6 94.6)"/><rect class="cl-pc cl-ok" x="226.1" y="81.2" width="14" height="10" rx="2.5" transform="rotate(-17.4 233.1 86.2)"/><rect class="cl-pc cl-ok" x="249.4" y="75.3" width="14" height="10" rx="2.5" transform="rotate(-11.2 256.4 80.3)"/><text class="cl-lbl"><textPath href="#clb-l1" startOffset="50%" text-anchor="middle" dominant-baseline="middle">CENTRUM 1</textPath></text><text class="cl-lbl"><textPath href="#clb-l2" startOffset="50%" text-anchor="middle" dominant-baseline="middle">CENTRUM 2</textPath></text><text class="cl-lbl"><textPath href="#clb-l3" startOffset="50%" text-anchor="middle" dominant-baseline="middle">CENTRUM 3</textPath></text><text class="cl-lbl"><textPath href="#clb-l4" startOffset="50%" text-anchor="middle" dominant-baseline="middle">CENTRUM 4</textPath></text></svg>'''


if __name__ == "__main__":
    # Preview mode (from the project root): `python -m streamlit run frontend/NewLogin.py`
    if require_login():
        user = ss.auth_user or {}
        st.success(
            f"Signed in as {user.get('first_name', '')} {user.get('last_name', '')} ({user.get('role', '')})"
        )
        st.button("Log out", on_click=logout)
