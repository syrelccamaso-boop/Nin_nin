"""
CRUD functions for the existing Supabase table "Users".

Columns (PascalCase, exactly as in the database):
    UserId, Email, LastName, FirstName, RoleId, Department,
    ContactNumber, Status, CreatedAt

There is no Role (name) column: the role is stored only as RoleId. The
number <-> name mapping comes from .env (ROLE_ID_TEACHER=2, ...) or, if it
exists, a "Roles" lookup table. See role_id_for() / role_name_for().

The schema is used as-is; nothing here creates or alters tables.

Every function raises DatabaseError on failure. str(error) is a short,
user-safe message; the technical details go to the server log only.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone

from .database import DatabaseConfigError, get_client

logger = logging.getLogger("centrum.users")


TABLE = "Users"

COLUMNS = (
    "UserId",
    "Email",
    "LastName",
    "FirstName",
    "RoleId",
    "Department",
    "ContactNumber",
    "Status",
    "CreatedAt",
)

SELECT_COLUMNS = ",".join(COLUMNS)

# Optional column linking a row to its Supabase Auth login (auth.users.id).
AUTH_ID_COLUMN = "AuthId"

_has_auth_id_column = None  # None = not checked yet


def _auth_id_supported() -> bool:
    """True if Users has an AuthId column (checked once, then remembered)."""

    global _has_auth_id_column

    if _has_auth_id_column is None:

        try:
            get_client().table(TABLE).select(AUTH_ID_COLUMN).limit(1).execute()
            _has_auth_id_column = True

        except Exception as error:

            text = error_text(error).lower()

            if "42703" in text or "pgrst204" in text or "does not exist" in text:
                _has_auth_id_column = False
                logger.info("Users has no AuthId column; logins are matched by email.")
            else:
                # Unknown problem (network, key...) - don't cache, try again later.
                return False

    return _has_auth_id_column


def _columns() -> str:
    """Columns to select: the fixed list, plus AuthId when it exists."""

    return SELECT_COLUMNS + ("," + AUTH_ID_COLUMN if _auth_id_supported() else "")


# snake_case (used by the app) -> column name in the table
FIELD_MAP = {
    "user_id": "UserId",
    "email": "Email",
    "last_name": "LastName",
    "first_name": "FirstName",
    "role_id": "RoleId",
    "department": "Department",
    "contact_number": "ContactNumber",
    "status": "Status",
    "created_at": "CreatedAt",
}

# Columns the app may change with update_user()
UPDATABLE = {
    "email",
    "last_name",
    "first_name",
    "role_id",
    "department",
    "role",
    "contact_number",
    "status",
}

# Learned on the first insert: True if UserId is filled by the database
# (integer / identity column) instead of the Supabase Auth uuid.
_user_id_generated_by_db = False

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


# =========================================================
# ERRORS
# =========================================================


class DatabaseError(RuntimeError):
    """A database call failed. str(error) is safe to show to users."""

    def __init__(self, message: str, detail: str = "", code: str = ""):
        super().__init__(message)
        self.detail = detail
        self.code = code


def error_text(error: Exception) -> str:
    """One-line technical description for the server log (no keys/URLs)."""

    parts = [type(error).__name__]

    for attribute in ("status", "code", "message", "details", "hint"):

        value = getattr(error, attribute, None)

        if value:
            parts.append(f"{attribute}={value}")

    if len(parts) == 1:
        parts.append(str(error)[:300])

    return " | ".join(parts)


def _friendly(error: Exception) -> tuple[str, str]:
    """(user message, short code) for a database exception."""

    if isinstance(error, DatabaseConfigError):
        return (
            "The database connection isn't set up yet. "
            "Please contact the administrator.",
            "config",
        )

    text = error_text(error).lower()

    if "invalid api key" in text or "status=401" in text or "jwt" in text:
        return (
            "The database connection isn't configured correctly. "
            "Please contact the administrator.",
            "auth",
        )

    # Specific Postgres error codes first (their messages often mention
    # "column", so the generic checks below must come after these).
    if "23505" in text or "duplicate key" in text:
        return ("An account with this email already exists.", "duplicate")

    if "23514" in text or "check constraint" in text:
        return (
            "One of the values was rejected by the database. "
            "Please contact the administrator.",
            "check",
        )

    if "23502" in text or "not-null" in text:
        return (
            "Some required account information is missing. "
            "Please contact the administrator.",
            "not_null",
        )

    if "42501" in text or "row-level security" in text or "permission denied" in text:
        return (
            "The server isn't allowed to access user accounts "
            "(database permissions). Please contact the administrator.",
            "permission",
        )

    if (
        "42p01" in text
        or "pgrst205" in text
        or ("relation" in text and "does not exist" in text)
    ):
        return (
            "The Users table could not be found. " "Please contact the administrator.",
            "missing_table",
        )

    if "42703" in text or "pgrst204" in text or "column" in text:
        return (
            "The Users table doesn't match what the app expects. "
            "Please contact the administrator.",
            "missing_column",
        )

    if any(
        word in text
        for word in (
            "connect",
            "timeout",
            "timed out",
            "getaddrinfo",
            "name resolution",
        )
    ):
        return (
            "We can't reach the database right now. "
            "Please check your internet connection and try again.",
            "network",
        )

    return (
        "A database error occurred. Please try again later.",
        "unknown",
    )


def _run(action: str, operation):
    """Run a Supabase call, turning any failure into DatabaseError."""

    try:
        return operation(get_client())

    except DatabaseError:
        raise

    except Exception as error:

        message, code = _friendly(error)
        detail = error_text(error)

        logger.error("Database error while %s: %s", action, detail)

        raise DatabaseError(message, detail=detail, code=code) from None


# =========================================================
# HELPERS
# =========================================================


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def is_uuid(value) -> bool:
    return bool(_UUID_RE.match(str(value or "")))


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def to_app_user(row: dict | None) -> dict | None:
    """Convert a Users row to the snake_case dict the Streamlit app uses."""

    if not row:
        return None

    return {
        "id": row.get("UserId"),
        "user_id": row.get("UserId"),
        "email": row.get("Email") or "",
        "first_name": row.get("FirstName") or "",
        "last_name": row.get("LastName") or "",
        "role_id": row.get("RoleId"),
        # Name looked up from RoleId (e.g. 2 -> "Teacher").
        "role": role_name_for(row.get("RoleId")),
        "department": row.get("Department") or "",
        "contact_number": row.get("ContactNumber") or "",
        # Lower-case so "Active" / "active" / "ACTIVE" all compare the same.
        "status": (row.get("Status") or "").strip().lower(),
        "created_at": row.get("CreatedAt"),
        "auth_id": row.get(AUTH_ID_COLUMN),
    }


def _to_columns(fields: dict) -> dict:
    """snake_case keys -> table column names (unknown keys are rejected)."""

    row = {}

    for key, value in fields.items():

        column = FIELD_MAP.get(key)

        if column is None:
            raise ValueError(f"Unknown field: {key}")

        row[column] = value

    return row


# =========================================================
# READ
# =========================================================


def get_user_by_email(email: str) -> dict | None:
    """Return the raw Users row for this email (case-insensitive), or None."""

    email = normalize_email(email)

    if not email:
        return None

    def query(client):

        # Exact match first (emails are stored lower-case by this app).
        response = (
            client.table(TABLE).select(_columns()).eq("Email", email).limit(1).execute()
        )

        if response.data:
            return response.data[0]

        # Rows added by hand may use mixed case.
        response = (
            client.table(TABLE)
            .select(_columns())
            .ilike("Email", _escape_like(email))
            .limit(1)
            .execute()
        )

        return response.data[0] if response.data else None

    return _run("looking up a user by email", query)


def get_user_by_id(user_id) -> dict | None:

    def query(client):

        response = (
            client.table(TABLE)
            .select(_columns())
            .eq("UserId", user_id)
            .limit(1)
            .execute()
        )

        return response.data[0] if response.data else None

    return _run("looking up a user by id", query)


def email_exists(email: str) -> bool:
    return get_user_by_email(email) is not None


def list_users(
    status: str | None = None,
    role: str | None = None,
    limit: int = 500,
) -> list[dict]:
    """Raw Users rows, newest first. status/role filters ignore letter case."""

    def query(client):

        request = client.table(TABLE).select(_columns())

        if status:
            request = request.ilike("Status", _escape_like(status.strip()))

        if role:
            role_id = role_id_for(role)

            if role_id is None:
                return []

            request = request.eq("RoleId", role_id)

        response = (
            request.order("CreatedAt", desc=True)
            .limit(max(1, min(int(limit), 1000)))
            .execute()
        )

        return response.data or []

    return _run("listing users", query)


def check_connection() -> str | None:
    """None if the Users table can be read, else a short description."""

    try:
        _run(
            "checking the database connection",
            lambda client: client.table(TABLE).select(_columns()).limit(1).execute(),
        )
        return None

    except DatabaseError as error:
        return error.detail[:300] or str(error)


# =========================================================
# VALUE CONVENTIONS OF THE EXISTING DATA
# =========================================================


def status_value(canonical: str) -> str:
    """Write Status in the same letter case the table already uses.

    e.g. if existing rows say "Active", new rows get "Pending"/"Active".
    """

    canonical = canonical.strip().lower()

    try:
        rows = _run(
            "reading existing Status values",
            lambda client: client.table(TABLE).select("Status").limit(20).execute().data
            or [],
        )

    except DatabaseError:
        return canonical

    samples = [str(row.get("Status") or "") for row in rows if row.get("Status")]

    if any(sample.isupper() for sample in samples):
        return canonical.upper()

    if any(sample[:1].isupper() for sample in samples):
        return canonical.capitalize()

    return canonical


# ---------------------------------------------------------
# RoleId <-> role name
# ---------------------------------------------------------
# 1) .env:  ROLE_ID_ADMIN=1  ROLE_ID_TEACHER=2  ROLE_ID_TECHNICIAN=3
#    (use the numbers your data actually uses)
# 2) otherwise a "Roles" lookup table, if your database has one
#    (id column RoleId/Id, name column RoleName/Name/Role)

_roles_table_cache = None


def _parse_id(value: str):
    value = (value or "").strip()
    return int(value) if value.lstrip("-").isdigit() else value


def _roles_from_env() -> dict:
    """{role name: RoleId} from ROLE_ID_<NAME> variables in .env."""

    roles = {}

    for key, value in os.environ.items():

        if key.upper().startswith("ROLE_ID_") and value.strip():
            name = key[len("ROLE_ID_") :].replace("_", " ").title()
            roles[name] = _parse_id(value)

    return roles


def _roles_from_table() -> dict:
    """{role name: RoleId} from a Roles lookup table, or {} if there is none."""

    global _roles_table_cache

    if _roles_table_cache is not None:
        return _roles_table_cache

    _roles_table_cache = {}

    for table in ("Roles", "roles", "Role"):

        try:
            rows = get_client().table(table).select("*").limit(100).execute().data or []

        except Exception:
            continue

        for row in rows:

            role_id = next(
                (row[k] for k in ("RoleId", "Id", "id", "role_id") if k in row),
                None,
            )
            name = next(
                (
                    row[k]
                    for k in ("RoleName", "Name", "Role", "name", "role_name", "role")
                    if row.get(k)
                ),
                None,
            )

            if role_id is not None and name:
                _roles_table_cache[str(name).strip()] = role_id

        if _roles_table_cache:
            logger.info("Using the %s table for RoleId names.", table)
            break

    return _roles_table_cache


def _all_roles() -> dict:
    roles = dict(_roles_from_table())
    roles.update(_roles_from_env())  # .env wins
    return roles


def role_id_for(role: str):
    """RoleId for a role name (case-insensitive), or None if not configured."""

    wanted = (role or "").strip().lower()

    for name, role_id in _all_roles().items():
        if name.lower() == wanted:
            return role_id

    return None


def role_name_for(role_id) -> str:
    """Role name for a RoleId, or "" if unknown."""

    if role_id is None:
        return ""

    for name, value in _all_roles().items():
        if str(value) == str(role_id):
            return name

    return ""


def roles_problem() -> str | None:
    """Explain what's missing for registration (used by /health)."""

    missing = [
        name.title() for name in ("TEACHER", "TECHNICIAN") if role_id_for(name) is None
    ]

    if missing:
        return (
            "No RoleId configured for: "
            + ", ".join(missing)
            + ". Add ROLE_ID_"
            + "=..., ROLE_ID_".join(m.upper() for m in missing)
            + "=... to .env."
        )

    return None


# =========================================================
# CREATE
# =========================================================


def create_user(
    email: str,
    first_name: str,
    last_name: str,
    department: str,
    role: str,
    status: str,
    contact_number: str = "",
    user_id=None,
    role_id=None,
    auth_id=None,
) -> dict:
    """Insert a Users row and return it.

    Duplicate emails are refused before inserting. user_id is the Supabase
    Auth user id: it is stored in UserId when that column accepts it
    (uuid). If UserId is a number/identity column, the database assigns it.
    """

    email = normalize_email(email)

    if email_exists(email):
        raise DatabaseError(
            "An account with this email already exists.",
            code="duplicate",
        )

    row = {
        "Email": email,
        "FirstName": first_name.strip(),
        "LastName": last_name.strip(),
        "Department": department,
        "ContactNumber": (contact_number or "").strip() or None,
        "Status": status,
    }

    if role_id is None:
        role_id = role_id_for(role)

    if role_id is None:
        logger.error(
            "No RoleId configured for role %r - set ROLE_ID_%s in .env.",
            role,
            (role or "").strip().upper(),
        )
        raise DatabaseError(
            "Registration isn't set up for this role yet. "
            "Please contact the administrator.",
            code="role_config",
        )

    row["RoleId"] = role_id

    global _user_id_generated_by_db

    if auth_id is not None and _auth_id_supported():
        # Link the row to its login through AuthId; UserId is left to the
        # database unless it turns out to need the uuid as well.
        row[AUTH_ID_COLUMN] = auth_id

    elif user_id is not None and not _user_id_generated_by_db:
        row["UserId"] = user_id

    def insert(client, payload):
        response = client.table(TABLE).insert(payload).execute()
        return response.data[0] if response.data else payload

    # Adapt to the existing schema without changing it:
    #  - UserId is an integer/identity column -> let the database fill it
    #  - CreatedAt has no default            -> fill it ourselves
    for _attempt in range(3):

        try:
            return _run("creating a user", lambda client: insert(client, row))

        except DatabaseError as error:

            detail = error.detail.lower()

            if "UserId" in row and (
                "22p02" in detail  # invalid input syntax for integer
                or "428c9" in detail  # GENERATED ALWAYS identity column
                or ("userid" in detail and "identity" in detail)
            ):
                row.pop("UserId")
                _user_id_generated_by_db = True
                logger.info(
                    "UserId is generated by the database; "
                    "new rows will let the database assign it."
                )
                continue

            if "CreatedAt" not in row and "23502" in detail and "createdat" in detail:
                row["CreatedAt"] = datetime.now(timezone.utc).isoformat()
                continue

            raise

    return _run("creating a user", lambda client: insert(client, row))


# =========================================================
# UPDATE
# =========================================================


def update_user(user_id, changes: dict) -> dict | None:
    """Update allowed fields (snake_case keys). Returns the updated row."""

    unknown = set(changes) - UPDATABLE

    if unknown:
        raise ValueError(f"These fields can't be updated: {sorted(unknown)}")

    if not changes:
        return get_user_by_id(user_id)

    changes = dict(changes)

    # "role" is a name; the table only stores RoleId.
    if "role" in changes:
        role = changes.pop("role")
        role_id = role_id_for(role)

        if role_id is None:
            raise ValueError(f"Unknown role: {role}")

        changes["role_id"] = role_id

    row = _to_columns(changes)

    if "Email" in row:
        row["Email"] = normalize_email(row["Email"])

        other = get_user_by_email(row["Email"])

        if other and str(other.get("UserId")) != str(user_id):
            raise DatabaseError(
                "An account with this email already exists.",
                code="duplicate",
            )

    def update(client):
        response = client.table(TABLE).update(row).eq("UserId", user_id).execute()
        return response.data[0] if response.data else None

    return _run("updating a user", update)


def update_status(user_id, status: str) -> dict | None:
    """Set Status (e.g. "active", "pending", "rejected")."""

    return update_user(user_id, {"status": status_value(status)})


# =========================================================
# DELETE
# =========================================================


def delete_user(user_id) -> bool:
    """Delete a Users row. Returns True if a row was removed."""

    def delete(client):
        response = client.table(TABLE).delete().eq("UserId", user_id).execute()
        return bool(response.data)

    return _run("deleting a user", delete)
