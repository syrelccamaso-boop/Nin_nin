"""
app.py - Centrum Laboratory | main entry point (Streamlit)

Run from the project root (CL Monitoring System/), in two terminals:

    uvicorn backend.main:app --reload      # 1) FastAPI backend
    streamlit run app.py                   # 2) this app

What it does
------------
1. Shows the Log In / Sign Up / Reset password screens from frontend/NewLogin.py.
   NewLogin talks to the FastAPI backend through frontend/backend_client.py.
   The backend (backend/main.py -> auth_service.py -> users_repository.py ->
   database.py) checks passwords with Supabase Auth, reads the Supabase
   "Users" table, and sends codes by email through email_service.py (Brevo).
2. After a successful login, opens the right dashboard for the user's role:
       Admin      -> Admin.py
       Teacher    -> Teacher.py
       Technician -> Technician.py
   The role name comes from Users.RoleId (ROLE_ID_ADMIN, ROLE_ID_TEACHER,
   ROLE_ID_TECHNICIAN in .env, or a Roles table).
   The "Log out" button on every dashboard brings you back to the login screen.

This file contains no database, authentication or email code and needs no
Supabase or Brevo keys - those stay in the backend.

Files that must sit in the same folder as app.py:
    Admin.py, Teacher.py, Technician.py,
    centrum-laboratory-admin.html, centrum-laboratory-teacher.html,
    centrum-laboratory-technician.html
    (optional) isu.jpg background, assets/logo.png
"""

from __future__ import annotations

import streamlit as st

from frontend import NewLogin


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
        st.error(
            f"Unknown role: {user.get('role') or 'none'}. Please contact the admin."
        )
        if st.button("Back to log in"):
            NewLogin.logout()
    st.stop()


def main() -> None:
    ss = st.session_state
    user = ss.get("auth_user")
    if ss.get("authenticated") and isinstance(user, dict) and user:
        _open_dashboard(user)  # dashboards set their own wide layout

    # Not signed in: show Log In / Sign Up. The login button reruns the app,
    # and the next run lands in _open_dashboard above.
    if NewLogin.require_login():
        _open_dashboard(ss.get("auth_user") or {})


main()
