"""
Centrum Laboratory - Supabase Database Connection

This module is responsible ONLY for creating and providing
Supabase clients.

Database operations and table-specific CRUD belong in repository
modules such as:

    users_repository.py
    computers_repository.py
    tickets_repository.py
    etc.

Current database architecture:

    Supabase PostgreSQL
            |
            v
       Supabase REST API
            |
            v
       supabase-py Client
            |
            +----------------------+
            |                      |
            v                      v
    users_repository.py       other repositories
            |
            v
        "Users"
            |
            +-- UserId
            +-- Email
            +-- FirstName
            +-- LastName
            +-- RoleId
            +-- Department
            +-- ContactNumber
            +-- Status
            +-- AuthId
            +-- CreatedAt
            +-- UpdatedAt

        "Role"
            |
            +-- RoleId
            +-- Role

Supabase Authentication:

    auth.users.id
          |
          v
    Users.AuthId

Passwords are stored ONLY in Supabase Auth.

Environment variables are loaded from .env:

    SUPABASE_URL=https://your-project-ref.supabase.co

    SUPABASE_SERVICE_ROLE_KEY=your_service_role_key

    SUPABASE_KEY=your_anon_or_service_key

    DATABASE_URL=postgresql://...    # optional

The backend prefers SUPABASE_SERVICE_ROLE_KEY.

DATABASE_URL is loaded for compatibility with other scripts/tools,
but is NOT used by the Supabase REST client in this application.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

from dotenv import find_dotenv, load_dotenv
from supabase import Client, create_client

logger = logging.getLogger("centrum.database")


# =========================================================
# PROJECT PATHS
# =========================================================

# Folder containing this database.py file.
BACKEND_DIR = Path(__file__).resolve().parent

# Project root.
#
# Expected structure:
#
# CL Monitoring System/
# │
# ├── .env
# ├── backend/
# │   ├── database.py
# │   ├── auth_service.py
# │   └── users_repository.py
# │
# └── frontend/
#
BASE_DIR = BACKEND_DIR.parent

# Primary .env location.
ENV_FILE = BASE_DIR / ".env"


# =========================================================
# LOAD ENVIRONMENT VARIABLES
# =========================================================
#
# Priority:
#
# 1. Project root .env
# 2. Backend .env
# 3. Current working directory / discovered .env
#
# Existing environment variables are NOT overwritten.
# =========================================================


def _load_environment() -> None:
    """
    Load environment variables from the project's .env files.

    Existing environment variables are preserved.
    """

    candidates = (
        ENV_FILE,
        BACKEND_DIR / ".env",
    )

    for candidate in candidates:
        if candidate.is_file():
            load_dotenv(
                dotenv_path=candidate,
                override=False,
            )

    # Also allow python-dotenv to discover an .env from the
    # directory where the application was started.
    discovered_env = find_dotenv(usecwd=True)

    if discovered_env:
        load_dotenv(
            discovered_env,
            override=False,
        )


_load_environment()


# =========================================================
# ENVIRONMENT VALUE CLEANING
# =========================================================


def _clean(value: str | None) -> str:
    """
    Clean an environment variable.

    Removes:
    - Leading/trailing whitespace
    - One pair of surrounding single/double quotes

    Example:

        "https://abc.supabase.co"

    becomes:

        https://abc.supabase.co
    """

    value = (value or "").strip()

    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1].strip()

    return value


# =========================================================
# SUPABASE CONFIGURATION
# =========================================================


SUPABASE_URL = _clean(os.getenv("SUPABASE_URL")).rstrip("/")


# Prefer the backend service-role key.
#
# The service-role key is required for backend operations such as:
#
# - Supabase Auth admin API
# - Password reset
# - Creating/deleting Auth users
# - Administrative Users CRUD
#
# If it is unavailable, SUPABASE_KEY is used as fallback.
SERVICE_ROLE_KEY = _clean(os.getenv("SUPABASE_SERVICE_ROLE_KEY"))

ANON_KEY = _clean(os.getenv("SUPABASE_KEY"))


SUPABASE_KEY = SERVICE_ROLE_KEY or ANON_KEY


USING_SERVICE_ROLE_KEY = bool(SERVICE_ROLE_KEY)


# =========================================================
# POSTGRESQL DATABASE URL
# =========================================================
#
# This is NOT used by the Supabase REST client.
#
# It is loaded because other scripts/tools may use it directly
# with PostgreSQL drivers such as:
#
#     psycopg
#     SQLAlchemy
#
# Example:
#
# DATABASE_URL=postgresql://postgres:password@host:5432/postgres
# =========================================================


DATABASE_URL = _clean(os.getenv("DATABASE_URL"))


# =========================================================
# REQUEST TIMEOUT (speed / reliability)
# =========================================================
#
# supabase-py waits up to 120 seconds for a database request by default.
# If Supabase is slow or the connection hangs, a request would block a
# server thread for two minutes - long after the Streamlit frontend (15-20 s)
# has already given up - and enough of them make the whole backend slow.
#
# Override in .env if needed:
#
#     SUPABASE_TIMEOUT_SECONDS=30
# =========================================================


def _timeout_seconds() -> float:
    try:
        value = float(_clean(os.getenv("SUPABASE_TIMEOUT_SECONDS")) or 30)
    except ValueError:
        value = 30.0

    return min(max(value, 3.0), 120.0)


SUPABASE_TIMEOUT_SECONDS = _timeout_seconds()


# =========================================================
# DATABASE CONFIGURATION ERROR
# =========================================================


class DatabaseConfigError(RuntimeError):
    """
    Raised when the Supabase connection configuration
    is missing or invalid.
    """

    pass


# =========================================================
# CONFIGURATION CHECK
# =========================================================


def config_problems() -> list[str]:
    """
    Return configuration problems without exposing
    credentials.

    No secret values are included in the returned messages.
    """

    problems: list[str] = []

    # -----------------------------------------------------
    # SUPABASE_URL
    # -----------------------------------------------------

    if not SUPABASE_URL:

        problems.append("SUPABASE_URL is missing from .env.")

    elif not SUPABASE_URL.startswith("https://"):

        problems.append("SUPABASE_URL must start with https://")

    # -----------------------------------------------------
    # SUPABASE KEY
    # -----------------------------------------------------

    if not SUPABASE_KEY:

        problems.append(
            "SUPABASE_SERVICE_ROLE_KEY " "(or SUPABASE_KEY) is missing from .env."
        )

    return problems


# =========================================================
# CLIENT STORAGE
# =========================================================


_client: Client | None = None

# The backend now reads several tables at the same time (perf.py). Without a
# lock, two threads asking for the client at the same moment could each
# create one.
_client_lock = threading.Lock()

# One client per speed-pool thread (see get_client).
_thread_clients = threading.local()


# =========================================================
# CREATE SUPABASE CLIENT
# =========================================================


def _make_client() -> Client:
    """
    Create a new Supabase client.

    This client is configured for backend/server-side use.

    Sessions are NOT persisted because the shared backend client
    must continue using the configured backend key rather than
    accidentally switching to a user's access token.
    """

    problems = config_problems()

    if problems:
        raise DatabaseConfigError(" ".join(problems))

    try:

        # -------------------------------------------------
        # ClientOptions compatibility
        #
        # Different supabase-py versions expose ClientOptions
        # from different locations.
        # -------------------------------------------------

        try:

            from supabase import ClientOptions

        except ImportError:

            from supabase.lib.client_options import ClientOptions

        try:
            options = ClientOptions(
                auto_refresh_token=False,
                persist_session=False,
                postgrest_client_timeout=SUPABASE_TIMEOUT_SECONDS,
            )
        except TypeError:
            # Older supabase-py without the timeout option.
            options = ClientOptions(
                auto_refresh_token=False,
                persist_session=False,
            )

        return create_client(
            SUPABASE_URL,
            SUPABASE_KEY,
            options=options,
        )

    except DatabaseConfigError:
        raise

    except Exception as error:

        # Never expose:
        #
        # - SUPABASE_URL
        # - SUPABASE_SERVICE_ROLE_KEY
        # - SUPABASE_KEY
        #
        # in the exception message.

        raise DatabaseConfigError(
            "Could not create the Supabase client " f"({type(error).__name__})."
        ) from None


# =========================================================
# SHARED DATABASE CLIENT
# =========================================================


def get_client() -> Client:
    """
    Return the shared backend Supabase client.

    Use this for:

    - Supabase REST database queries
    - Users CRUD
    - Role queries
    - Computers queries
    - Tickets
    - Reports
    - Software
    - Hardware
    - Unit history
    - Other backend database operations

    It can also be used for Supabase Auth ADMIN operations
    when the service-role key is configured.

    IMPORTANT:
        Never use this client for user sign-in or sign-up.

    Instead use:

        new_auth_client()

    This prevents a user's authentication session/token from
    replacing the backend's service-role authentication.
    """

    global _client

    # Threads of the speed pool (perf.py, named "centrum-...") each get their
    # OWN client, so parallel reads never share one HTTP/2 connection. Sharing
    # one connection between threads that query at the same moment can make
    # a query fail with a protocol error ("A database error occurred").
    if threading.current_thread().name.startswith("centrum-"):

        client = getattr(_thread_clients, "client", None)

        if client is None:
            client = _make_client()
            _thread_clients.client = client

        return client

    if _client is None:

        with _client_lock:

            if _client is None:

                _client = _make_client()

    return _client


# =========================================================
# NEW AUTH CLIENT
# =========================================================


def new_auth_client() -> Client:
    """
    Create a fresh, temporary Supabase client.

    Use this for user authentication operations such as:

        auth.sign_up()
        auth.sign_in_with_password()
        auth.get_user(access_token)

    This prevents the shared backend client from having its
    authentication state replaced by an individual user's session.
    """

    return _make_client()


# =========================================================
# CONNECTION STATUS
# =========================================================


def is_configured() -> bool:
    """
    Return True if the minimum Supabase configuration exists.

    This checks configuration only; it does not perform a
    network/database request.
    """

    return not config_problems()


# =========================================================
# SERVICE-ROLE STATUS
# =========================================================


def using_service_role() -> bool:
    """
    Return True when the backend is using the Supabase
    service-role key.
    """

    return USING_SERVICE_ROLE_KEY


# =========================================================
# DATABASE URL STATUS
# =========================================================


def round_trip_ms(table: str = "ReportStatus") -> float | None:
    """
    Time one tiny query to Supabase, in milliseconds (None if it failed).

    Use it to see how far away the database is. Every dashboard load makes
    several queries, so this number is paid many times per click. Above
    about 150 ms, check that the Supabase project's region is close to the
    server (for the Philippines: Southeast Asia / Singapore).

        python -c "from backend.database import round_trip_ms; print(round_trip_ms())"
    """

    try:
        client = get_client()
        start = time.perf_counter()
        client.table(table).select("*").limit(1).execute()
        return round((time.perf_counter() - start) * 1000, 1)
    except Exception as error:
        logger.warning("Round-trip check failed (%s).", type(error).__name__)
        return None


def has_database_url() -> bool:
    """
    Return True if DATABASE_URL is configured.

    DATABASE_URL is optional because this application uses
    Supabase REST rather than a direct PostgreSQL connection.
    """

    return bool(DATABASE_URL)


# =========================================================
# STARTUP CONFIGURATION LOGGING
# =========================================================
#
# Log configuration problems once when this module loads.
# Do not crash the application during import.
# =========================================================


for _problem in config_problems():

    logger.error(
        "Database configuration: %s",
        _problem,
    )


# =========================================================
# SERVICE-ROLE WARNING
# =========================================================
#
# The backend application performs administrative operations.
# Therefore, the service-role key is strongly preferred.
# =========================================================


if SUPABASE_KEY and not USING_SERVICE_ROLE_KEY:

    logger.warning(
        "SUPABASE_SERVICE_ROLE_KEY is not configured. "
        "The backend is using SUPABASE_KEY instead. "
        "Row-level security may block database operations, "
        "and Supabase Auth admin operations such as password "
        "reset, Auth user deletion, and account cleanup may fail."
    )


# =========================================================
# BACKWARD COMPATIBILITY
# =========================================================
#
# Older modules may contain:
#
#     from database import supabase
#
# Keep this alias so those modules do not immediately break.
#
# If configuration is incomplete, keep it as None instead of
# crashing the entire application during import.
# =========================================================


try:

    supabase: Client | None = get_client()

except DatabaseConfigError:

    supabase = None