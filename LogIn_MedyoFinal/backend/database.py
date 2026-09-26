"""
Centrum Laboratory - Supabase connection.

Reads credentials from .env (never hardcode them):

    SUPABASE_URL=https://your-project-ref.supabase.co
    SUPABASE_SERVICE_ROLE_KEY=your_service_role_key   # preferred on the backend
    SUPABASE_KEY=your_anon_or_service_key             # used if the one above is empty
    DATABASE_URL=postgresql://...                     # optional, not needed by this app

The backend uses the Supabase REST client (supabase-py). DATABASE_URL is only
loaded so other tools/scripts can use it; the app does not require it.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import find_dotenv, load_dotenv
from supabase import Client, create_client

logger = logging.getLogger("centrum.database")


# =========================================================
# LOAD .env
# =========================================================
# Project root first (same as before), then the backend folder, then the
# folder uvicorn was started from. Existing variables are never overwritten.

BACKEND_DIR = Path(__file__).resolve().parent
BASE_DIR = BACKEND_DIR.parent
ENV_FILE = BASE_DIR / ".env"

for _candidate in (ENV_FILE, BACKEND_DIR / ".env"):
    if _candidate.is_file():
        load_dotenv(_candidate)

load_dotenv(find_dotenv(usecwd=True))


def _clean(value: str | None) -> str:
    """Strip whitespace and one pair of surrounding quotes."""

    value = (value or "").strip()

    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1].strip()

    return value


SUPABASE_URL = _clean(os.getenv("SUPABASE_URL")).rstrip("/")
SUPABASE_KEY = _clean(os.getenv("SUPABASE_SERVICE_ROLE_KEY")) or _clean(
    os.getenv("SUPABASE_KEY")
)
USING_SERVICE_ROLE_KEY = bool(_clean(os.getenv("SUPABASE_SERVICE_ROLE_KEY")))

# Optional - loaded for completeness, not used by the REST client.
DATABASE_URL = _clean(os.getenv("DATABASE_URL"))


# =========================================================
# ERRORS
# =========================================================


class DatabaseConfigError(RuntimeError):
    """SUPABASE_URL / key missing or invalid in .env."""


def config_problems() -> list[str]:
    """What's wrong with the connection settings (never includes values)."""

    problems = []

    if not SUPABASE_URL:
        problems.append("SUPABASE_URL is missing from .env.")

    elif not SUPABASE_URL.startswith("https://"):
        problems.append("SUPABASE_URL must start with https://")

    if not SUPABASE_KEY:
        problems.append(
            "SUPABASE_SERVICE_ROLE_KEY (or SUPABASE_KEY) is missing from .env."
        )

    return problems


# =========================================================
# CLIENTS
# =========================================================

_client: Client | None = None


def _make_client() -> Client:

    problems = config_problems()

    if problems:
        raise DatabaseConfigError(" ".join(problems))

    try:
        # Server-side client: no session saved, no background token refresh.
        try:
            from supabase import ClientOptions
        except ImportError:  # older supabase-py
            from supabase.lib.client_options import ClientOptions

        options = ClientOptions(
            auto_refresh_token=False,
            persist_session=False,
        )

        return create_client(SUPABASE_URL, SUPABASE_KEY, options=options)

    except DatabaseConfigError:
        raise

    except Exception as error:
        # Don't include the key or URL in the message.
        raise DatabaseConfigError(
            f"Could not create the Supabase client ({type(error).__name__})."
        ) from None


def get_client() -> Client:
    """Shared client for database queries and admin calls.

    Never call auth.sign_in_with_password / auth.sign_up on this client:
    that would replace the server key with the user's token for every
    later query. Use new_auth_client() for those.
    """

    global _client

    if _client is None:
        _client = _make_client()

    return _client


def new_auth_client() -> Client:
    """A fresh, throwaway client for sign-in / sign-up calls."""

    return _make_client()


# Log once at startup instead of crashing uvicorn with a traceback.
for _problem in config_problems():
    logger.error("Database configuration: %s", _problem)

if SUPABASE_KEY and not USING_SERVICE_ROLE_KEY:
    logger.warning(
        "SUPABASE_SERVICE_ROLE_KEY is not set. With the anon key, row-level "
        "security may block reading/writing the Users table, and admin "
        "features (password reset, account cleanup) will not work."
    )


# Backward compatibility: older code imported `supabase` from this module.
try:
    supabase: Client | None = get_client()
except DatabaseConfigError:
    supabase = None
