"""
Teacher.py - Centrum Laboratory | Teacher dashboard (Streamlit)

The screen itself is the design in centrum-laboratory-teacher.html (keep it in the
same folder as this file). This file loads that design, puts the signed-in
teacher's name / email / number into it, and connects its "Log out" buttons to
Streamlit. To change how the dashboard looks, edit the HTML; to change how it
connects to your login or database, edit this file.

Use it from your login script
-----------------------------
1) After a successful login, keep the user and rerun:

       st.session_state["user"] = user_row      # the row from your Users table
       st.rerun()

2) Near the top of the login script (before the login card is drawn):

       user = st.session_state.get("user")
       if user and str(user.get("Role", user.get("role", ""))).lower() == "teacher":
           import Teacher
           Teacher.render(user)
           st.stop()

Just to look at it (no login needed):

       streamlit run Teacher.py -- --preview
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import streamlit as st

ROLE = "Teacher"
HTML_FILE = Path(__file__).resolve().parent / "centrum-laboratory-teacher.html"

# Shown only by `streamlit run Teacher.py -- --preview`.
DEMO_USER = {
    "name": "Alwyna Lopez",
    "email": "alwyna.lopez@isu.edu.ph",
    "contact_number": "0983 765 6748",
    "role": ROLE,
}

# Where a login script may have stored the signed-in user.
_SESSION_KEYS = ("user", "auth_user", "current_user")

# Column names we understand (case-insensitive), so both a Supabase "Users" row
# (FirstName, LastName, Role ...) and a plain dict (first_name, last_name ...) work.
_FIELDS = {
    "first": ("first_name", "firstname"),
    "last": ("last_name", "lastname"),
    "full": ("full_name", "fullname", "name"),
    "email": ("email",),
    "phone": ("contact_number", "contactnumber", "contact", "phone", "phonenumber"),
    "role": ("role",),
}


# ---------------------------------------------------------------------------
# Who is signed in
# ---------------------------------------------------------------------------
def _pick(raw: dict, names: tuple[str, ...]) -> str:
    lowered = {str(k).lower(): v for k, v in raw.items()}
    for name in names:
        value = lowered.get(name)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def normalize_user(raw: dict) -> dict:
    """Turn a user row/dict from any login into {name, email, contact_number, role}."""
    first, last = _pick(raw, _FIELDS["first"]), _pick(raw, _FIELDS["last"])
    email = _pick(raw, _FIELDS["email"])
    name = _pick(raw, _FIELDS["full"]) or f"{first} {last}".strip() or email.split("@")[0]
    return {
        "name": name or "User",
        "email": email,
        "contact_number": _pick(raw, _FIELDS["phone"]),
        "role": _pick(raw, _FIELDS["role"]),
    }


def session_user() -> dict | None:
    for key in _SESSION_KEYS:
        raw = st.session_state.get(key)
        if isinstance(raw, dict) and raw:
            return normalize_user(raw)
    return None


def _logout() -> None:
    """Forget the user and send the app back to its login screen."""
    for key in _SESSION_KEYS:
        st.session_state.pop(key, None)
    st.session_state["authenticated"] = False   # NewLogin.py-style login
    st.session_state["page"] = "login"          # Supabase-style login
    st.session_state["auth_view"] = "login"
    st.session_state["cl_logged_out"] = True


# ---------------------------------------------------------------------------
# Page chrome: make Streamlit get out of the way of the dashboard
# ---------------------------------------------------------------------------
_PAGE_CSS = """
<style>
html, body, body .stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"] {
    background: #f3f5f9 !important;
}
[data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"],
[data-testid="stSidebar"], [data-testid="stSidebarNav"], [data-testid="collapsedControl"],
[data-testid="stStatusWidget"], footer, #MainMenu { display: none !important; }
.block-container, [data-testid="stMainBlockContainer"] {
    max-width: 100% !important; padding: 0 !important;
}
[data-testid="stVerticalBlock"] { gap: 0 !important; }
/* the dashboard fills the whole browser window */
iframe { border: 0 !important; display: block; height: 100vh !important; height: 100dvh !important; }
[data-testid="stElementContainer"]:has(> iframe), .element-container:has(> iframe) {
    height: 100vh !important; height: 100dvh !important;
    flex: 0 0 100vh !important; flex: 0 0 100dvh !important;
}

/* the real "Log out" button. The dashboard's own Log out buttons click it. */
.st-key-cl_logout {
    position: absolute !important; left: -9999px !important;
    width: 1px !important; height: 1px !important; overflow: hidden !important;
}
</style>
"""

# Runs inside the dashboard, after the page's own script.
_BRIDGE = r"""
<script>
/* ---- added by Teacher.py: signed-in user + Streamlit hooks ---- */
(function () {
  var U = __USER__;
  var name = U.name || 'User';
  var ini = name.trim().split(/\s+/).map(function (w) { return w[0]; })
                 .slice(0, 2).join('').toUpperCase() || '?';

  /* name, initials, phone */
  document.querySelectorAll('.user > div:not(.avatar)').forEach(function (el) { el.textContent = name; });
  document.querySelectorAll('.avatar, .avatar-lg').forEach(function (el) { el.textContent = ini; });
  var fixed = document.querySelector('.profile-fixed-name');
  if (fixed) fixed.textContent = name;
  var num = document.getElementById('profile-number-display');
  if (num) num.textContent = U.contact_number || 'Not set';

  /* teacher: "Reported by", email, and don't prefill the edit box with the placeholder */
  var rb = document.querySelector('#report-step-review .review-row .review-value');
  if (rb) rb.textContent = name;
  document.querySelectorAll('.contact-info-value:not([id])').forEach(function (el) {
    el.textContent = U.email || 'Not set';
  });
  var _toggle = window.toggleInlineEdit;
  window.toggleInlineEdit = function (field) {
    _toggle(field);
    var i = document.getElementById('profile-' + field + '-input');
    if (i && i.value === 'Not set') i.value = '';
  };

  /* Log out -> the hidden Streamlit button (see _PAGE_CSS) */
  window.logout = function () {
    try {
      var btn = window.parent.document.querySelector('.st-key-cl_logout button');
      if (btn) { btn.click(); return; }
    } catch (e) {}
    showToast('Could not log out - please refresh the page.');
  };

  /* fill the browser window */
  function fit() {
    try {
      var f = window.frameElement, h = window.parent.innerHeight;
      if (f && h) { f.style.height = h + 'px'; f.setAttribute('height', h); }
    } catch (e) {}
  }
  fit();
  try {
    var P = window.parent;
    if (P.__clFit) P.removeEventListener('resize', P.__clFit);
    P.__clFit = fit;
    P.addEventListener('resize', fit);
  } catch (e) {}
})();
</script>
"""


@st.cache_data(show_spinner=False)
def _read_html(path: str, mtime: float) -> str:
    # `mtime` is only here so editing the HTML file refreshes the page.
    return Path(path).read_text(encoding="utf-8")


def _build_page(user: dict) -> str:
    html = _read_html(str(HTML_FILE), HTML_FILE.stat().st_mtime)
    payload = json.dumps(user).replace("</", "<\\/")     # keep the user's text from closing the <script>
    bridge = _BRIDGE.replace("__USER__", payload)
    head, sep, tail = html.rpartition("</body>")
    return head + bridge + sep + tail if sep else html + bridge


def _show(page_html: str) -> None:
    """Put the dashboard on screen. (Height is stretched to the window by _PAGE_CSS / _BRIDGE.)"""
    if hasattr(st, "iframe"):                        # newer Streamlit
        st.iframe(page_html, height=900)
    else:                                            # older Streamlit
        import streamlit.components.v1 as components
        components.html(page_html, height=900, scrolling=True)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def render(user: dict | None = None) -> None:
    """Draw the Teacher dashboard for `user` (a dict from your login)."""
    try:
        st.set_page_config(
            page_title="Centrum Laboratory - Teacher",
            page_icon="\U0001F5A5\uFE0F",
            layout="wide",
            initial_sidebar_state="collapsed",
        )
    except st.errors.StreamlitAPIException:
        pass  # your login script already called set_page_config

    user = normalize_user(user) if user else session_user()
    if user is None:
        st.warning("You're not signed in. Please log in first.")
        st.stop()
    if user["role"].lower() != ROLE.lower():
        st.error(f"This page is for {ROLE.lower()}s only (you're signed in as "
                 f"{user['role'] or 'an unknown role'}).")
        st.stop()
    if not HTML_FILE.exists():
        st.error(f"Can't find {HTML_FILE.name}. Put it in the same folder as Teacher.py.")
        st.stop()

    st.markdown(_PAGE_CSS, unsafe_allow_html=True)
    if st.button("Log out", key="cl_logout"):
        _logout()
        st.rerun()
    _show(_build_page(user))


# ---------------------------------------------------------------------------
# `streamlit run Teacher.py` (or used as a page in a pages/ folder)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    preview = "--preview" in sys.argv[1:]
    current = session_user()

    if current is None and preview:
        if st.session_state.get("cl_logged_out"):
            st.info("Logged out (preview).")
            if st.button("Back to preview"):
                st.session_state["cl_logged_out"] = False
                st.rerun()
            st.stop()
        current = DEMO_USER

    if current is None:
        st.warning("You're not signed in. Log in from the main app first, or preview this "
                   "page with:  streamlit run Teacher.py -- --preview")
        st.stop()

    render(current)
