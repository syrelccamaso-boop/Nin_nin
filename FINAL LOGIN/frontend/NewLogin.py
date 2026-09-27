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
Use it in the main app (top of app.py, before anything else is drawn):

    from frontend import NewLogin as login
    if not login.require_login(logo="path/to/your/logo.png"):   # same logo as app.py
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

# Your campus background photo. Only the file name matters: if it isn't at this
# exact path, the page also looks in the project root, ./assets and the folders
# one or two levels below the project root (e.g. static/, images/).
BG_IMAGE = BASE_DIR / "isu.jpg"

# How much to blur the background photo, in pixels. 0 = sharp, 6-10 = soft, 15+ = very blurry.
BG_BLUR_PX = 8

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

    # Send login request to backend
    result = login_user(email, password)

    # Backend says login failed
    if not result.get("success"):

        return _notify("err", result.get("error"))

    # Login successful
    ss.authenticated = True

    ss.auth_user = result.get("user")

    ss.auth_remember = bool(ss.get("login_remember"))

    ss.login_password = ""


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

    # validate name
    name_pattern = r"^[A-Za-z]+(?:[ '-][A-Za-z]+)*$"

    if not re.fullmatch(name_pattern, data["first"].strip().title()):
        st.error(
            "First name should contain letters, spaces, hyphens, or apostrophes only."
        )

    if not re.fullmatch(name_pattern, data["last"].strip().title):
        st.error(
            "Last name should contain letters, spaces, hyphens, or apostrophes only."
        )

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
        pending = user.get("status") == "pending"

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
    ss.auth_view = "login"
    ss.auth_notice = None
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


_FALLBACK_LOGO_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 190 54">'
    '<path d="M38 10 A19 19 0 1 0 38 40" stroke="#1d4ed8" stroke-width="9" '
    'fill="none" stroke-linecap="round"/>'
    '<text x="50" y="35" font-family="Arial, sans-serif" font-size="27" '
    'font-weight="800" fill="#14213d">entrum</text>'
    '<text x="142" y="48" text-anchor="end" font-family="Arial, sans-serif" '
    'font-size="8" font-weight="700" letter-spacing="1.2" fill="#14213d">LABORATORY</text>'
    "</svg>"
)


def _logo_uri(logo: str | Path | None = None) -> str:
    """Logo passed in by the app, else the shared logo.py (same as app.py), else LOGO_IMAGE, else the wordmark."""
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
    return (
        "data:image/svg+xml;base64,"
        + base64.b64encode(_FALLBACK_LOGO_SVG.encode()).decode()
    )


# ---------------------------------------------------------------------------
# Styling
# ---------------------------------------------------------------------------
_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Open+Sans:wght@400;600;700&display=swap');
 
/* --- page chrome & background ------------------------------------------ */
[data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"],
[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"],
[data-testid="collapsedControl"], #MainMenu, footer { display: none !important; }
[data-testid="stAppViewContainer"], [data-testid="stMain"] { background: transparent !important; }
.stApp { background: transparent; }
/* the photo sits on its own layer so only the photo is blurred, not the card */
.stApp::before {
  content: ""; position: fixed; inset: -24px; z-index: 0; pointer-events: none;
  background: __BACKGROUND__; filter: blur(__BLUR__px);
}
[data-testid="stAppViewContainer"] { position: relative; z-index: 1; }
 
html, body, .stApp, .stApp p, .stApp label, .stApp input, .stApp button {
  font-family: 'Open Sans', 'Segoe UI', Roboto, Arial, sans-serif;
}
 
/* --- the white card ------------------------------------------------------ */
[data-testid="stMainBlockContainer"], .stMainBlockContainer, .block-container {
  max-width: 480px !important;
  margin: 5vh auto !important;
  padding: 32px 32px 34px !important;
  background: #fff;
  border-radius: 24px;
  box-shadow: 0 24px 70px rgba(6, 30, 60, .35);
}
[data-testid="stMainBlockContainer"] [data-testid="stVerticalBlock"] { gap: .7rem; }
/* Streamlit wraps each widget in a shrink-to-fit box on newer versions: make it fill its column */
[data-testid="stMainBlockContainer"] [data-testid="stElementContainer"],
[data-testid="stMainBlockContainer"] .element-container { width: 100% !important; max-width: 100% !important; }
[data-testid="stMainBlockContainer"] [data-testid="stButton"] { width: 100%; }
@media (max-width: 520px) {
  [data-testid="stMainBlockContainer"], .stMainBlockContainer, .block-container {
    margin: 3vh 12px !important; padding: 24px 20px 26px !important; max-width: none !important;
  }
}
 
/* --- header text ---------------------------------------------------------- */
.cx-head { text-align: center; padding-bottom: 14px; }
.cx-head img { height: 56px; display: block; margin: 0 auto; }
.cx-sub { font-size: 10.5px; font-weight: 600; color: #5b6472; margin-top: 4px; }
.cx-title { font-size: 18px; font-weight: 700; color: #111827; line-height: 1.2; margin-top: 4px; }
.cx-desc { font-size: 12.5px; color: #6b7280; margin-top: 3px; padding-bottom: 8px; }
 
/* centered headings used on the "Check your email" / "Request sent" screens */
.cx-badge {
  width: 64px; height: 64px; border-radius: 50%; margin: 6px auto 4px;
  display: flex; align-items: center; justify-content: center;
}
.cx-badge svg { width: 26px; height: 26px; }
.cx-badge.blue  { background: #e7effd; color: #2d6fe3; }
.cx-badge.green { background: #e3f4ec; color: #1f9d63; }
.cx-h1 { text-align: center; font-size: 22px; font-weight: 700; color: #111827; line-height: 1.25; margin-top: 6px; }
.cx-p  { text-align: center; font-size: 14px; color: #6b7280; line-height: 1.5; padding: 0 4px 6px; }
 
/* prototype notice (amber box) */
.cx-notice {
  background: #fdeedd; color: #7a4a12; border-radius: 10px;
  padding: 14px 16px; font-size: 13.5px; line-height: 1.55;
}
.cx-notice code {
  background: #fff; color: #7a4a12; padding: 2px 8px; border-radius: 6px;
  font-family: Consolas, 'Courier New', monospace; font-weight: 700; font-size: 13px;
}
 
/* --- Log In / Sign Up switch ---------------------------------------------- */
.st-key-authtabs { background: #e8eaef; border-radius: 12px; padding: 4px; }
.st-key-authtabs [data-testid="stHorizontalBlock"] { gap: 4px; }
.st-key-authtabs [data-testid="stButton"] { width: 100%; }
.st-key-authtabs button {
  width: 100%; height: 38px; min-height: 0; border: 0; border-radius: 9px;
  font-size: 13px; font-weight: 600; box-shadow: none;
}
.st-key-authtabs button p { font-size: 13px; font-weight: 600; color: inherit; }
.st-key-tab_login_on button, .st-key-tab_signup_on button {
  background: #fff !important; color: #111827 !important;
  box-shadow: 0 1px 3px rgba(0, 0, 0, .18) !important;
}
.st-key-tab_login_off button, .st-key-tab_signup_off button {
  background: transparent !important; color: #4b5563 !important;
}
 
/* --- alerts ---------------------------------------------------------------- */
.cx-alert { border-radius: 10px; padding: 10px 14px; font-size: 12.5px; line-height: 1.45; }
.cx-alert.err { background: #fbe1e1; color: #b4322a; }
.cx-alert.ok  { background: #dcf3e5; color: #1f7a45; }
 
/* --- inputs ------------------------------------------------------------------ */
[data-testid="stWidgetLabel"] p { font-size: 13px; font-weight: 600; color: #1f2937; }
[data-testid="stWidgetLabel"] p span { font-weight: 400; }
 
[data-testid="stTextInput"] [data-baseweb="input"], [data-testid="stTextInputRootElement"],
[data-testid="stSelectbox"] [data-baseweb="select"] > div {
  background: #fff; border: 1px solid #dfe3ea; border-radius: 12px; min-height: 46px;
}
[data-testid="stTextInput"] [data-baseweb="input"]:focus-within,
[data-testid="stTextInputRootElement"]:focus-within,
[data-testid="stSelectbox"] [data-baseweb="select"] > div:focus-within {
  border-color: #2d6fe3; box-shadow: 0 0 0 3px rgba(45, 111, 227, .15);
}
[data-testid="stTextInput"] [data-baseweb="base-input"] { background: transparent; border: 0; }
[data-testid="stTextInput"] input {
  color: #111827; -webkit-text-fill-color: #111827; font-size: 14.5px; background: transparent;
}
[data-testid="stTextInput"] input::placeholder,
[data-testid="stSelectbox"] input::placeholder { color: #9aa3b2; -webkit-text-fill-color: #9aa3b2; opacity: 1; }
[data-testid="stTextInput"] button { color: #8b93a1; background: transparent; }
[data-testid="stSelectbox"] [data-baseweb="select"] * { font-size: 14.5px; color: #111827; }
[data-testid="stSelectbox"] [data-baseweb="select"] svg { color: #8b93a1; }
[data-testid="InputInstructions"] { display: none; }
[data-testid="stCheckbox"] label p { font-size: 12px; font-weight: 400; color: #4b5563; }
 
/* verification code box: big, centered dots */
.st-key-su_code input { text-align: center; letter-spacing: .4em; font-size: 18px; }
.st-key-su_code input::placeholder { letter-spacing: .4em; }
.st-key-rs_code input { text-align: center; letter-spacing: .4em; font-size: 18px; }
.st-key-rs_code input::placeholder { letter-spacing: .4em; }
 
/* --- forms ------------------------------------------------------------------- */
[data-testid="stForm"] { border: 0 !important; padding: 0 !important; background: transparent; }
[data-testid="stFormSubmitButton"] { margin-top: .4rem; }
/* Log In button is first in the DOM (so Enter submits it) but shown last */
.st-key-login_actions { order: 2; }
.st-key-login_submit  { order: 3; margin-top: .4rem; }
 
/* --- primary (blue) buttons ------------------------------------------------- */
[data-testid="stBaseButton-primary"], [data-testid="stBaseButton-primaryFormSubmit"] {
  display: flex; margin: 0 auto; width: 100%; height: 48px; border: 0; border-radius: 10px;
  background: #2d6fe3; color: #fff; box-shadow: none;
}
[data-testid="stBaseButton-primary"] p, [data-testid="stBaseButton-primaryFormSubmit"] p {
  color: #fff; font-size: 15px; font-weight: 600;
}
[data-testid="stBaseButton-primary"]:hover, [data-testid="stBaseButton-primaryFormSubmit"]:hover {
  background: #2460cc; border: 0;
}
 
/* --- text-link buttons ---------------------------------------------------- */
.st-key-forgot_link button, .st-key-back_link button,
.st-key-resend_link button, .st-key-edit_link button {
  background: transparent !important; border: 0 !important; box-shadow: none !important;
  padding: 0 !important; min-height: 0 !important; height: auto !important; width: auto !important;
}
.st-key-forgot_link [data-testid="stFormSubmitButton"] { display: flex; justify-content: flex-end; }
.st-key-forgot_link button p { font-size: 12px; font-weight: 600; color: #2d6fe3; }
.st-key-back_link { display: flex; justify-content: center; }
.st-key-back_link button p { font-size: 12px; font-weight: 500; color: #6b7280; }
.st-key-resend_link, .st-key-edit_link { display: flex; }
.st-key-edit_link { justify-content: flex-end; }
.st-key-resend_link button p, .st-key-edit_link button p { font-size: 14px; font-weight: 600; color: #2d6fe3; }
.st-key-forgot_link button:hover p, .st-key-back_link button:hover p,
.st-key-resend_link button:hover p, .st-key-edit_link button:hover p { text-decoration: underline; }
 
/* --- role picker (Teacher / Technician) ---------------------------------------- */
.st-key-role_teacher_on button, .st-key-role_teacher_off button,
.st-key-role_technician_on button, .st-key-role_technician_off button {
  width: 100%; height: auto; min-height: 104px; padding: 14px 8px; border-radius: 14px;
  background: #fff; border: 1px solid #e3e6ec; box-shadow: none;
}
.st-key-role_teacher_on button > div, .st-key-role_teacher_off button > div,
.st-key-role_technician_on button > div, .st-key-role_technician_off button > div {
  flex-direction: column; gap: 3px;
}
.st-key-role_teacher_on [data-testid="stButton"], .st-key-role_teacher_off [data-testid="stButton"],
.st-key-role_technician_on [data-testid="stButton"], .st-key-role_technician_off [data-testid="stButton"] {
  width: 100%;
}
.st-key-role_teacher_on button p, .st-key-role_teacher_off button p,
.st-key-role_technician_on button p, .st-key-role_technician_off button p {
  white-space: pre-line; text-align: center; font-size: 11.5px; line-height: 1.4; margin: 0; color: #6b7280;
}
.st-key-role_teacher_on button strong, .st-key-role_teacher_off button strong,
.st-key-role_technician_on button strong, .st-key-role_technician_off button strong {
  font-size: 13.5px; color: #111827;
}
[class*="st-key-role_"] button span[role="img"] {
  display: block; margin: 0 auto 4px; font-size: 28px; line-height: 1; color: #6b7a90; vertical-align: baseline;
}
.st-key-role_teacher_on button, .st-key-role_technician_on button {
  border: 1.5px solid #2d6fe3; background: #eef4fe;
}
.st-key-role_teacher_on button span[role="img"], .st-key-role_technician_on button span[role="img"] {
  color: #2d6fe3;
}
</style>
"""


def _build_css() -> str:
    bg = _image_uri(_find_image(BG_IMAGE, ("background", "bg", "campus", "gate")))
    if bg:
        background = (
            "linear-gradient(180deg, rgba(8, 60, 110, .20), rgba(8, 60, 110, .05)), "
            f'url("{bg}") center / cover no-repeat'
        )
    else:  # no photo found: sky-to-lawn gradient so the page still looks right
        background = "linear-gradient(180deg, #2b7fc0 0%, #86bde8 48%, #5c8a4a 100%)"
    return _CSS.replace("__BACKGROUND__", background).replace(
        "__BLUR__", str(BG_BLUR_PX)
    )


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
}


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
    _heading("Welcome back", "Sign in to your Centrum Laboratory account")
    _alert()
    with st.form("login_form"):
        st.text_input("Email Address", key="login_email")
        st.text_input("Password", type="password", key="login_password")
        # Submit first in the DOM so Enter submits it; CSS moves it below the row.
        st.form_submit_button(
            "Log In", type="primary", key="login_submit", on_click=_do_login
        )
        with st.container(key="login_actions"):
            left, right = st.columns(2, vertical_alignment="center")
            left.checkbox("Remember Me", key="login_remember")
            right.form_submit_button(
                "Forgot password?", key="forgot_link", on_click=_go, args=("reset",)
            )


def _render_signup() -> None:
    {"form": _render_signup_form, "verify": _render_verify, "done": _render_done}[
        ss.signup_step
    ]()


def _render_signup_form() -> None:
    _heading("Create your account", "Pick your role, then fill in the details.")
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
            placeholder="At least 8 characters",
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
            "check",
            "green",
            "Request sent",
            f"Thanks, {first}! Your {role} account request was sent to the admin. "
            "You can log in once it's confirmed.",
        )
    else:
        _centered_heading(
            "check",
            "green",
            "Account created",
            f"Thanks, {first}! Your account is ready. You can log in now.",
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
        st.text_input("Email Address", key="reset_email")
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
            placeholder="At least 8 characters",
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
            page_title="Centrum Laboratory",
            page_icon="\U0001f5a5\ufe0f",
            layout="centered",
            initial_sidebar_state="collapsed",
        )
    except st.errors.StreamlitAPIException:
        pass  # the main app already called set_page_config


def require_login(logo: str | Path | None = None) -> bool:
    """Draw the auth screens unless the user is signed in. Returns True when signed in.

    `logo` is the path to your logo image - pass the same one app.py uses.
    """
    _page_config()
    _init_state()
    if ss.authenticated:
        return True

    st.markdown(_build_css(), unsafe_allow_html=True)
    # "Check your email" and "Request sent" are stand-alone cards: no logo, no tabs.
    standalone = ss.auth_view == "signup" and ss.signup_step != "form"
    if not standalone:
        _render_header(logo)
        _render_tabs()
    {"login": _render_login, "signup": _render_signup, "reset": _render_reset}[
        ss.auth_view
    ]()
    return False


if __name__ == "__main__":
    # Preview mode (from the project root): `python -m streamlit run frontend/NewLogin.py`
    if require_login():
        user = ss.auth_user or {}
        st.success(
            f"Signed in as {user.get('first_name', '')} {user.get('last_name', '')} ({user.get('role', '')})"
        )
        st.button("Log out", on_click=logout)
