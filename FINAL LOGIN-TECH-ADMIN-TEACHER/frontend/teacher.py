"""
frontend/teacher.py - Centrum Laboratory | Teacher dashboard (Streamlit)

The screen itself is the design in centrum-laboratory-teacher.html (kept in the
project root, or in frontend/). This file loads that design, puts the signed-in
teacher's name / email / number into it, fills it with live data, and connects
its buttons to Streamlit. To change how the dashboard looks, edit the HTML.

This file contains UI code only. Every read and write goes through
frontend/backend_client.py -> FastAPI (backend/main.py) ->
backend/teacher_service.py -> backend/database.py (Supabase).

How it is opened
----------------
app.py opens it after a successful login when the user's role (from
auth_service / Users.RoleId) is Teacher:

    from frontend import teacher
    teacher.render(user)

How the dashboard's buttons reach the backend
---------------------------------------------
The dashboard runs inside an iframe. "Submit report", the contact number
"Save" and "Update password" write a small JSON action into a hidden Streamlit
text box. Streamlit reruns, this file sends the action to the backend with
backend_client, and the page is redrawn with fresh data and a toast message.

Just to look at it (sample data, no login needed), from the project root:

       python -m streamlit run frontend/teacher.py -- --preview
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import streamlit as st

from frontend import backend_client

ROLE = "Teacher"
HTML_NAME = "centrum-laboratory-teacher.html"
_FRONTEND_DIR = Path(__file__).resolve().parent
_PROJECT_DIR = _FRONTEND_DIR.parent

# frontend/ first, then the project root (where the HTML files live now).
HTML_FILE = next(
    (p for p in (_FRONTEND_DIR / HTML_NAME, _PROJECT_DIR / HTML_NAME) if p.is_file()),
    _PROJECT_DIR / HTML_NAME,
)

# Where a login script may have stored the signed-in user.
_SESSION_KEYS = ("user", "auth_user", "current_user")

# Access token saved by NewLogin.py after /auth/login.
_TOKEN_KEY = "auth_token"

# Hidden text box the dashboard writes its actions into, and bookkeeping.
_ACTION_KEY = "cl_teacher_action"
_DONE_KEY = "cl_teacher_done_nonce"
_FLASH_KEY = "cl_teacher_flash"

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
    name = (
        _pick(raw, _FIELDS["full"]) or f"{first} {last}".strip() or email.split("@")[0]
    )
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
    for key in _SESSION_KEYS + (_TOKEN_KEY, _FLASH_KEY, _DONE_KEY):
        st.session_state.pop(key, None)
    st.session_state["authenticated"] = False  # NewLogin.py-style login
    st.session_state["page"] = "login"  # Supabase-style login
    st.session_state["auth_view"] = "login"
    st.session_state["cl_logged_out"] = True


# ---------------------------------------------------------------------------
# Dashboard actions -> backend_client
# ---------------------------------------------------------------------------
def _run_action(action: dict, token: str | None) -> dict:
    kind = action.get("type")

    if kind == "report":
        issues = action.get("issues")
        return backend_client.submit_report(
            token,
            action.get("room"),
            action.get("unit_number"),
            issues if isinstance(issues, list) else [],
            action.get("comment") or "",
        )

    if kind == "contact_number":
        result = backend_client.teacher_update_contact_number(
            token, action.get("contact_number")
        )
        saved = result.get("user") if result.get("success") else None
        if isinstance(saved, dict):
            # Keep the signed-in user in sync so the new number shows right away.
            for key in _SESSION_KEYS:
                if isinstance(st.session_state.get(key), dict):
                    st.session_state[key]["contact_number"] = saved.get(
                        "contact_number", ""
                    )
        return result

    if kind == "password":
        return backend_client.teacher_change_password(
            token,
            action.get("current_password") or "",
            action.get("new_password") or "",
        )

    return {"success": False, "error": "Unknown action."}


def _handle_action(token: str | None) -> None:
    """Run the action the dashboard left in the hidden text box (once)."""
    raw = st.session_state.get(_ACTION_KEY) or ""
    st.session_state[_ACTION_KEY] = ""  # clear it (also removes any password from it)
    if not raw:
        return
    try:
        action = json.loads(raw)
    except ValueError:
        return
    if not isinstance(action, dict):
        return

    nonce = str(action.get("nonce") or "")
    if not nonce or nonce == st.session_state.get(_DONE_KEY):
        return
    st.session_state[_DONE_KEY] = nonce

    if not token:
        result = {
            "success": False,
            "error": "Your session has expired. Please log out and log in again.",
        }
    else:
        result = _run_action(action, token)

    flash = {
        "message": (
            result.get("message") if result.get("success") else result.get("error")
        ),
        "page": str(action.get("page") or "dashboard"),
    }
    # A saved report reopens the "Report submitted" step with its number.
    report = result.get("report") if result.get("success") else None
    if action.get("type") == "report" and isinstance(report, dict):
        flash["report_code"] = report.get("code") or ""
    st.session_state[_FLASH_KEY] = flash


def _load_data(token: str | None) -> tuple[dict | None, str]:
    """(dashboard data, notice). data is None when the sample data must be shown."""
    if not token:
        return None, (
            "Showing sample data - please log out and log in again "
            "to load live data."
        )
    result = backend_client.get_teacher_data(token)
    if not result.get("success"):
        return (
            None,
            f"Showing sample data - {result.get('error') or 'could not load live data.'}",
        )
    return {
        "units": result.get("units") or [],
        "reports": result.get("reports") or [],
        "history": result.get("history") or [],
    }, ""


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

/* the real "Log out" button and the action box. The dashboard uses them. */
.st-key-cl_logout, .st-key-cl_teacher_action {
    position: absolute !important; left: -9999px !important;
    width: 1px !important; height: 1px !important; overflow: hidden !important;
}
</style>
"""

# Runs inside the dashboard, after the page's own script.
_BRIDGE = r"""
<script>
/* ---- added by frontend/teacher.py: signed-in user, live data, Streamlit hooks ---- */
(function () {
  var P = __PAYLOAD__;
  var U = P.user;
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

  /* ---------------- live data from the backend ---------------- */
  function pad2(n) { return String(n).padStart(2, '0'); }
  function unitKey(room, n) { return room + '-' + pad2(n); }
  function fmtDate(iso) {
    var d = new Date(iso);
    if (isNaN(d)) return iso || '';
    return d.toLocaleDateString('en-US', {month: 'short', day: '2-digit', year: 'numeric'}) +
           ' \u00b7 ' + d.toLocaleTimeString('en-US', {hour: 'numeric', minute: '2-digit'});
  }
  function roomLabel(room) { return room.replace(/^CL\s*/i, 'Centrum Laboratory '); }
  function byRoomName(a, b) { return a.localeCompare(b, undefined, {numeric: true}); }
  function toPageReport(r) {
    var d = new Date(r.created_at);
    return {id: r.code, dbId: r.id, room: r.room,
            unit: 'Unit ' + pad2(r.unit_number), unitNumber: r.unit_number,
            issues: r.issues, comment: r.comment, status: r.status,
            resolutionNote: r.resolution_note, handledBy: r.handled_by,
            date: fmtDate(r.created_at), sortDate: isNaN(d) ? new Date(0) : d};
  }

  function applyData(D) {
    /* the teacher's own reports -> the page's `reports` list (My Reports, stats) */
    reports = D.reports.map(toPageReport);
    var all = D.history.map(toPageReport);   /* every report: unit status + history */

    /* computers -> rooms, unit counts, statuses, details */
    var stored = {}, rooms = [], counts = {};
    D.units.forEach(function (u) {
      stored[unitKey(u.room, u.number)] = u;
      if (rooms.indexOf(u.room) < 0) rooms.push(u.room);
      counts[u.room] = Math.max(counts[u.room] || 0, u.number);
    });
    if (!rooms.length) rooms.push('CL 1');
    rooms.sort(byRoomName);

    ROOMS.length = 0;
    rooms.forEach(function (r) { ROOMS.push(r); });
    Object.keys(UNIT_COUNTS).forEach(function (k) { delete UNIT_COUNTS[k]; });
    rooms.forEach(function (r) { UNIT_COUNTS[r] = counts[r] || 0; });

    var open = {}, history = {};
    all.slice().sort(function (a, b) { return b.sortDate - a.sortDate; }).forEach(function (r) {
      var k = unitKey(r.room, r.unitNumber);
      if (r.status !== 'resolved') open[k] = true;
      (history[k] = history[k] || []).push({
        date: r.date, issue: r.issues[0] || 'General issue', comment: r.comment,
        action: r.resolutionNote || 'Logged and pending review.', status: r.status,
        by: r.status === 'resolved' ? 'Resolved by ' + (r.handledBy || 'technician')
           : (r.status === 'followup' ? 'Needs follow-up' : 'In progress')
      });
    });

    /* stored status wins for "replace"; an open report means "issue" */
    statusFor = function (room, n) {
      var k = unitKey(room, n), u = stored[k];
      if (u && u.status === 'replace') return 'replace';
      if ((u && u.status === 'issue') || open[k]) return 'issue';
      return 'good';
    };

    function noData(obj, label) {
      return Object.keys(obj || {}).length ? obj : (function () { var o = {}; o[label] = 'Not recorded yet'; return o; })();
    }
    Object.keys(UNIT_DETAILS).forEach(function (k) { delete UNIT_DETAILS[k]; });
    Object.keys(stored).concat(Object.keys(history)).forEach(function (k) {
      if (UNIT_DETAILS[k]) return;
      var u = stored[k] || {};
      UNIT_DETAILS[k] = {
        hardware: noData(u.hardware, 'Hardware'),
        software: (u.software && u.software.length) ? u.software : [['Software', 'Not recorded yet']],
        system: noData(u.system, 'System'),
        lifecycle: noData(u.lifecycle, 'Lifecycle'),
        history: history[k] || []
      };
    });
    defaultDetail = function (room, n, status) {
      return {hardware: {'Hardware': 'Not recorded yet'}, software: [['Software', 'Not recorded yet']],
              system: {'System': 'Not recorded yet'}, lifecycle: {'Lifecycle': 'Not recorded yet'}, history: []};
    };

    /* room pickers: report form + dashboard glance */
    var form = document.getElementById('f-room');
    if (form) form.innerHTML = '<option value="">Select a room</option>' + rooms.map(function (r) {
      return '<option value="' + escapeHtml(r) + '">' + escapeHtml(roomLabel(r)) + '</option>'; }).join('');
    var glance = document.getElementById('glance-room-select');
    if (glance) glance.innerHTML = rooms.map(function (r) {
      return '<option value="' + escapeHtml(r) + '">' + escapeHtml(r) + '</option>'; }).join('');
    if (rooms.indexOf(currentRoom) < 0) currentRoom = rooms[0];
    initRoomTabs();
    resetForm();         /* unit list follows the new rooms */
    renderDashboard();   /* stat cards and room glance */
  }

  /* ---------------- actions -> hidden Streamlit text box ---------------- */
  function currentPage() {
    var n = document.querySelector('.nav-item.active');
    var page = n ? n.dataset.page : 'dashboard';
    if (page === 'settings') {
      var s = document.querySelector('.settings-menu-item.active');
      if (s && s.dataset.stab) page += ':' + s.dataset.stab;
    }
    return page;
  }

  function sendAction(action) {
    try {
      var W = window.parent;
      var input = W.document.querySelector('.st-key-cl_teacher_action input');
      if (!input) throw new Error('action box missing');
      action.nonce = Date.now() + '-' + Math.random().toString(36).slice(2);
      action.page = currentPage();
      var setter = Object.getOwnPropertyDescriptor(W.HTMLInputElement.prototype, 'value').set;
      input.focus();
      setter.call(input, JSON.stringify(action));
      input.dispatchEvent(new W.Event('input', {bubbles: true}));
      input.blur();   /* Streamlit saves the text box on blur -> rerun */
      return true;
    } catch (e) {
      showToast('Could not reach the server - please refresh the page.');
      return false;
    }
  }

  function hookActions() {
    /* "Submit report" on the review step */
    submitReport = function () {
      var room = document.getElementById('f-room').value;
      var unit = document.getElementById('f-unit').value;
      var num = parseInt(String(unit).replace(/\D/g, ''), 10);
      var issues = currentIssueList();
      var comment = document.getElementById('f-comment').value.trim();
      if (!room || !num) { showToast('Select a room and a computer unit'); return; }
      if (!issues.length) { showToast('Pick at least one issue'); return; }
      if (sendAction({type: 'report', room: room, unit_number: num,
                      issues: issues, comment: comment})) {
        showToast('Submitting...');
      }
    };

    saveInlineEdit = function (field) {
      var input = document.getElementById('profile-' + field + '-input');
      var val = input.value.trim();
      if (!val) { showToast('Enter a value first'); return; }
      if (field !== 'number') { showToast('To change this, please contact the administrator.'); return; }
      if (sendAction({type: 'contact_number', contact_number: val})) {
        document.getElementById('profile-' + field + '-edit').style.display = 'none';
        showToast('Saving...');
      }
    };

    var pwBtn = document.querySelector('#spanel-security .form-footer .btn-primary');
    if (pwBtn) pwBtn.onclick = function () {
      var cur = document.getElementById('pw-current').value;
      var nw = document.getElementById('pw-new').value;
      var cf = document.getElementById('pw-confirm').value;
      if (!cur || !nw || !cf) { showToast('Fill in all three password fields'); return; }
      if (nw !== cf) { showToast("The new passwords don't match"); return; }
      if (sendAction({type: 'password', current_password: cur, new_password: nw})) {
        ['pw-current', 'pw-new', 'pw-confirm'].forEach(function (id) { document.getElementById(id).value = ''; });
        showToast('Saving...');
      }
    };
  }

  if (P.data) {
    try {
      applyData(P.data);
      hookActions();
    } catch (e) {
      P.notice = 'Could not show the live data (' + e.message + ').';
    }
  }

  /* notice banner (sample data / problems loading) */
  if (P.notice) {
    var bar = document.createElement('div');
    bar.textContent = P.notice;
    bar.style.cssText = 'position:fixed;left:50%;top:12px;transform:translateX(-50%);z-index:9999;' +
      'background:#fff7e6;color:#8a5300;border:1px solid #f3c77a;border-radius:10px;padding:8px 16px;' +
      'font:500 13px/1.4 system-ui,sans-serif;box-shadow:0 4px 14px rgba(0,0,0,.08);max-width:90%;text-align:center;';
    document.body.appendChild(bar);
  }

  /* back to the page the user was on, then show the result */
  var target = ((P.flash && P.flash.page) || 'dashboard').split(':');
  if (!document.getElementById('page-' + target[0])) target = ['dashboard'];
  if (typeof goTo === 'function') goTo(target[0]);
  if (target[1] && document.getElementById('spanel-' + target[1])) switchSettingsTab(target[1]);

  /* a saved report: show the existing "Report submitted" step with its number */
  if (P.flash && P.flash.report_code && document.getElementById('report-step-done')) {
    goTo('report');
    document.getElementById('done-report-id').textContent = P.flash.report_code;
    document.getElementById('report-step-form').style.display = 'none';
    document.getElementById('report-step-review').style.display = 'none';
    document.getElementById('report-step-done').style.display = 'block';
    setWizard(3);
  }
  if (P.flash && P.flash.message) showToast(P.flash.message);

  /* fill the browser window */
  function fit() {
    try {
      var f = window.frameElement, h = window.parent.innerHeight;
      if (f && h) { f.style.height = h + 'px'; f.setAttribute('height', h); }
    } catch (e) {}
  }
  fit();
  try {
    var W = window.parent;
    if (W.__clFit) W.removeEventListener('resize', W.__clFit);
    W.__clFit = fit;
    W.addEventListener('resize', fit);
  } catch (e) {}
})();
</script>
"""


@st.cache_data(show_spinner=False)
def _read_html(path: str, mtime: float) -> str:
    # `mtime` is only here so editing the HTML file refreshes the page.
    return Path(path).read_text(encoding="utf-8")


def _build_page(user: dict, data: dict | None, notice: str, flash: dict | None) -> str:
    html = _read_html(str(HTML_FILE), HTML_FILE.stat().st_mtime)
    payload = {"user": user, "data": data, "notice": notice, "flash": flash}
    # keep the user's text from closing the <script>
    payload_js = json.dumps(payload).replace("</", "<\\/")
    bridge = _BRIDGE.replace("__PAYLOAD__", payload_js)
    head, sep, tail = html.rpartition("</body>")
    return head + bridge + sep + tail if sep else html + bridge


def _show(page_html: str) -> None:
    """Put the dashboard on screen. (Height is stretched to the window by _PAGE_CSS / _BRIDGE.)"""
    if hasattr(st, "iframe"):  # newer Streamlit
        st.iframe(page_html, height=900)
    else:  # older Streamlit
        import streamlit.components.v1 as components

        components.html(page_html, height=900, scrolling=True)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def render(user: dict | None = None, preview: bool = False) -> None:
    """Draw the Teacher dashboard for `user` (a dict from your login)."""
    try:
        st.set_page_config(
            page_title="Centrum Laboratory - Teacher",
            page_icon="\U0001f5a5\ufe0f",
            layout="wide",
            initial_sidebar_state="collapsed",
        )
    except st.errors.StreamlitAPIException:
        pass  # your login script already called set_page_config

    token = st.session_state.get(_TOKEN_KEY)
    if not preview:
        _handle_action(token)  # before the user is read: it may update the number

    user = normalize_user(user) if user else session_user()
    if user is None:
        st.warning("You're not signed in. Please log in first.")
        st.stop()
    if user["role"].lower() != ROLE.lower():
        st.error(
            f"This page is for {ROLE.lower()}s only (you're signed in as "
            f"{user['role'] or 'an unknown role'})."
        )
        st.stop()
    if not HTML_FILE.exists():
        st.error(f"Can't find {HTML_NAME}. Put it in the project root or in frontend/.")
        st.stop()

    data, notice = (None, "") if preview else _load_data(token)
    flash = st.session_state.pop(_FLASH_KEY, None)

    st.markdown(_PAGE_CSS, unsafe_allow_html=True)
    if st.button("Log out", key="cl_logout"):
        _logout()
        st.rerun()
    st.text_input("Teacher action", key=_ACTION_KEY, label_visibility="collapsed")
    _show(_build_page(user, data, notice, flash))
