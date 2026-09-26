"""
App.py - Centrum Laboratory | main entry point (Streamlit)

Run the whole system with:

    streamlit run App.py

What it does
------------
1. Makes sure the user database (from NewLogin.py) can hold Admin accounts.
2. Creates the sample accounts below (only if they don't exist yet).
3. Shows the Log In / Sign Up screens from NewLogin.py.
4. After a successful login, opens the right dashboard for the user's role:
       Admin      -> Admin.py
       Teacher    -> Teacher.py
       Technician -> Technician.py
   The "Log out" button on every dashboard brings you back to the login screen.

Files that must sit in the same folder as App.py:
    NewLogin.py, Admin.py, Teacher.py, Technician.py,
    centrum-laboratory-admin.html, centrum-laboratory-teacher.html,
    centrum-laboratory-technician.html
    (optional) isu.jpg background, assets/logo.svg
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import streamlit as st

import NewLogin

# ---------------------------------------------------------------------------
# Sample accounts (created on first run; existing accounts are never changed)
# ---------------------------------------------------------------------------
SAMPLE_ACCOUNTS = (
    {
        "role": "Admin",
        "first_name": "System",
        "last_name": "Administrator",
        "department": "Administration",
        "email": "admin@gmail.com",
        "password": "admin1234",
        "contact_number": "",
    },
    {
        "role": "Teacher",
        "first_name": "Alwyna",
        "last_name": "Lopez",
        "department": "CCSICT",
        "email": "teacher@gmail.com",
        "password": "teacher1234",
        "contact_number": "09837656748",
    },
    {
        "role": "Technician",
        "first_name": "Jherome",
        "last_name": "Domingo",
        "department": "CCSICT",
        "email": "technician@gmail.com",
        "password": "technician1234",
        "contact_number": "09171234567",
    },
)

# Same table as NewLogin.py, but the role check also allows 'Admin'.
_USERS_TABLE_SQL = """
CREATE TABLE {name} (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    role            TEXT NOT NULL CHECK (role IN ('Admin', 'Teacher', 'Technician')),
    first_name      TEXT NOT NULL,
    last_name       TEXT NOT NULL,
    department      TEXT NOT NULL,
    email           TEXT NOT NULL UNIQUE COLLATE NOCASE,
    contact_number  TEXT NOT NULL DEFAULT '',
    pw_salt         TEXT NOT NULL,
    pw_hash         TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'pending', 'rejected')),
    created_at      TEXT NOT NULL
)
"""

_COLUMNS = ("id, role, first_name, last_name, department, email, contact_number, "
            "pw_salt, pw_hash, status, created_at")


# ---------------------------------------------------------------------------
# Database setup
# ---------------------------------------------------------------------------
def _allow_admin_role(con: sqlite3.Connection) -> None:
    """Create the users table so it accepts 'Admin', or upgrade an existing one.

    NewLogin.py's table only allows Teacher/Technician. Because it uses
    CREATE TABLE IF NOT EXISTS, creating the table here first is enough.
    An older database file is rebuilt with its rows kept.
    """
    row = con.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'users'"
    ).fetchone()
    if row is None:
        con.execute(_USERS_TABLE_SQL.format(name="users"))
        return
    if "'Admin'" in row[0]:
        return  # already upgraded

    # SQLite can't change a CHECK constraint in place: copy into a new table.
    con.execute("PRAGMA foreign_keys = OFF")
    con.execute("DROP TABLE IF EXISTS users_new")
    con.execute(_USERS_TABLE_SQL.format(name="users_new"))
    con.execute(f"INSERT INTO users_new ({_COLUMNS}) SELECT {_COLUMNS} FROM users")
    con.execute("DROP TABLE users")
    con.execute("ALTER TABLE users_new RENAME TO users")


def _seed_accounts(con: sqlite3.Connection) -> None:
    for acc in SAMPLE_ACCOUNTS:
        exists = con.execute(
            "SELECT 1 FROM users WHERE email = ?", (acc["email"],)
        ).fetchone()
        if exists:
            continue
        salt, digest = NewLogin._hash_password(acc["password"])
        con.execute(
            "INSERT INTO users (role, first_name, last_name, department, email,"
            " contact_number, pw_salt, pw_hash, status, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)",
            (acc["role"], acc["first_name"], acc["last_name"], acc["department"],
             acc["email"], acc["contact_number"], salt, digest,
             datetime.now(timezone.utc).isoformat()),
        )


@st.cache_resource(show_spinner=False)
def setup_database() -> bool:
    """Runs once per server start."""
    con = sqlite3.connect(NewLogin.DB_PATH)
    try:
        with con:  # commits on success
            _allow_admin_role(con)
            _seed_accounts(con)
    finally:
        con.close()
    # Let NewLogin create its other table (password_resets) as usual.
    with NewLogin._db():
        pass
    return True


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------
def _open_dashboard(user: dict) -> None:
    role = str(user.get("role", "")).strip().lower()
    if role in ("admin", "administrator"):
        import Admin
        Admin.render(user)
    elif role == "teacher":
        import Teacher
        Teacher.render(user)
    elif role == "technician":
        import Technician
        Technician.render(user)
    else:
        st.error(f"Unknown role: {user.get('role') or 'none'}. Please contact the admin.")
        if st.button("Back to log in"):
            NewLogin.logout()
    st.stop()


def main() -> None:
    setup_database()

    ss = st.session_state
    user = ss.get("auth_user")
    if ss.get("authenticated") and isinstance(user, dict) and user:
        _open_dashboard(user)          # dashboards set their own wide layout

    # Not signed in: show Log In / Sign Up. The login button reruns the app,
    # and the next run lands in _open_dashboard above.
    if NewLogin.require_login():
        _open_dashboard(ss.get("auth_user") or {})


main()
