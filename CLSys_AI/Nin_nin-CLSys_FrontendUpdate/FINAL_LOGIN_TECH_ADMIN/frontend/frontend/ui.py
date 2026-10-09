"""
frontend/ui.py - Centrum Laboratory | Streamlit helpers shared by every screen

    - who is signed in: normalize_user, session_user, require_user,
      set_contact_number, logout_user, preview_logged_out
    - messages: flash (queue a toast) and show_flash
    - widgets that keep their value while hidden: sticky, remember
    - design markup: html, h, scope_css
    - styled widgets: btn, hit, box
    - assets/: asset, page_icon, page_config

How the styling hooks work
--------------------------
- btn(label, key, kind): a st.button whose key carries a marker such as
  "__primary__" or "__ghostsm__"; the dashboard CSS styles it like the
  design's .btn-primary etc.
- box(key, "card", "row", ...): a st.container whose key carries markers that
  give it the look/layout of a design block (card, row, grid, pop-up...).
- hit(markup, key, on_click): a design element (nav item, table row, tile...)
  with an invisible button stretched over it, so the whole element is
  clickable, just like in the HTML version.

The dashboards' shared shell (sidebar, top bar, floor map, pop-ups) is in
frontend/portal.py. Needs Streamlit 1.39 or newer (keyed containers).
This file has no database, authentication or email code.
"""
from __future__ import annotations

import html as _html
import re
from pathlib import Path

import streamlit as st


ss = st.session_state


FRONTEND_DIR = Path(__file__).resolve().parent


PROJECT_DIR = FRONTEND_DIR.parent


# ---------------------------------------------------------------------------
# Brand files (optional): assets/logo.png, assets/logo-icon.png, ...
# Looked for in <project>/assets first, then frontend/assets.
# ---------------------------------------------------------------------------
def asset(name: str) -> Path | None:
    for folder in (PROJECT_DIR / "assets", FRONTEND_DIR / "assets"):
        if (folder / name).is_file():
            return folder / name
    return None


def page_icon():
    """assets/logo-icon.png as the browser-tab icon (a monitor emoji if it's missing)."""
    path = asset("logo-icon.png")
    return str(path) if path else "\U0001f5a5\ufe0f"


# Where a login script may have stored the signed-in user, and the access token.
SESSION_KEYS = ("user", "auth_user", "current_user")


TOKEN_KEY = "auth_token"


# Session-state prefixes owned by the dashboards (cleared on log out).
DASHBOARD_PREFIXES = ("tech_", "admin_", "teacher_", "_keep_")


# ===========================================================================
# Who is signed in
# ===========================================================================
_FIELDS = {
    "first": ("first_name", "firstname", "fname", "given_name"),
    "last": ("last_name", "lastname", "lname", "surname", "family_name"),
    "full": ("full_name", "fullname", "name", "display_name"),
    "email": ("email", "email_address", "emailaddress"),
    "phone": ("contact_number", "contactnumber", "contact", "phone", "phonenumber", "phone_number", "mobile"),
    "role": ("role", "role_name", "rolename", "user_role", "userrole", "roles"),
}

KNOWN_ROLES = {"admin": "Admin", "administrator": "Admin", "teacher": "Teacher", "faculty": "Teacher",
               "instructor": "Teacher", "technician": "Technician", "tech": "Technician"}


def _pick(raw: dict, names: tuple[str, ...]) -> str:
    lowered = {str(k).lower(): v for k, v in raw.items()}
    for name in names:
        value = lowered.get(name)
        if isinstance(value, dict):  # e.g. {"role": {"name": "Admin"}} from a joined Roles table
            value = value.get("name") or value.get("Name") or value.get("role_name") or value.get("RoleName")
        elif isinstance(value, list) and value:
            value = value[0].get("name") if isinstance(value[0], dict) else value[0]
        if value not in (None, ""):
            return str(value).strip()
    return ""


def resolve_role(raw: dict) -> str:
    """The role name of a user row from the Users table: a role / role_name field, a joined Roles
    row, or Users.RoleId matched against ROLE_ID_ADMIN / ROLE_ID_TEACHER / ROLE_ID_TECHNICIAN (.env)."""
    import os

    role = _pick(raw, _FIELDS["role"])
    if role and not role.isdigit():
        return KNOWN_ROLES.get(role.lower(), role.title())
    role_id = role or _pick(raw, ("roleid", "role_id"))
    if role_id:
        for env, name in (("ROLE_ID_ADMIN", "Admin"), ("ROLE_ID_TEACHER", "Teacher"),
                          ("ROLE_ID_TECHNICIAN", "Technician")):
            if (os.getenv(env) or "").strip() == role_id:
                return name
    return ""


def normalize_user(raw: dict) -> dict:
    """Turn a user row/dict from any login into {name, email, contact_number, role}."""
    raw = raw if isinstance(raw, dict) else {}
    first, last = _pick(raw, _FIELDS["first"]), _pick(raw, _FIELDS["last"])
    email = _pick(raw, _FIELDS["email"])
    name = _pick(raw, ("full_name", "fullname", "display_name")) or f"{first} {last}".strip() or \
        _pick(raw, ("name",)) or email.split("@")[0]
    return {
        "name": name or "User",
        "email": email,
        "contact_number": _pick(raw, _FIELDS["phone"]),
        "role": resolve_role(raw),
        "status": _pick(raw, ("status", "account_status", "accountstatus")).lower(),
    }


def session_user() -> dict | None:
    for key in SESSION_KEYS:
        raw = ss.get(key)
        if isinstance(raw, dict) and raw:
            return normalize_user(raw)
    return None


def require_user(user: dict | None, role: str, allowed: tuple[str, ...]) -> dict:
    """The normalized user, or a message + st.stop() when they may not see this page."""
    user = normalize_user(user) if user else session_user()
    if user is None:
        st.warning("You're not signed in. Please log in first.")
        st.stop()
    if user["role"].lower() not in allowed:
        st.error(
            f"This page is for {role.lower()}s only (you're signed in as "
            f"{user['role'] or 'an unknown role'})."
        )
        st.stop()
    return user


def set_contact_number(number: str) -> None:
    """Keep the signed-in user in sync so a new number shows right away."""
    for key in SESSION_KEYS:
        if isinstance(ss.get(key), dict):
            ss[key]["contact_number"] = number


def logout_user() -> None:
    """Forget the user and the dashboard state; the app shows its login screen again."""
    for key in list(ss.keys()):
        if key in SESSION_KEYS or key == TOKEN_KEY or str(key).startswith(DASHBOARD_PREFIXES):
            ss.pop(key, None)
    ss["authenticated"] = False  # NewLogin.py-style login
    ss["page"] = "login"  # Supabase-style login
    ss["auth_view"] = "login"
    ss["cl_view"] = "auth"
    ss["cl_logged_out"] = True
    ss["auth_notice"] = ("ok", "You have been logged out.")


def preview_logged_out() -> None:
    """In `--preview` mode, show a small 'logged out' screen after Log out."""
    if ss.get("cl_logged_out"):
        st.info("Logged out (preview).")
        if st.button("Back to preview"):
            ss["cl_logged_out"] = False
            st.rerun()
        st.stop()


def flash(prefix: str, message: str, ok: bool = True) -> None:
    """Queue a toast; it is shown on the next run (callbacks run before the page)."""
    ss.setdefault(f"{prefix}_flash", []).append((str(message or ""), "✅" if ok else "⚠️"))


def show_flash(prefix: str) -> None:
    for message, icon in ss.pop(f"{prefix}_flash", []):
        if message:
            st.toast(message, icon=icon)


def sticky(key: str, options: list | None = None):
    """Keep a widget's value while it is hidden (Streamlit forgets hidden widgets).

    Use as `st.radio(..., key=sticky("k", opts))` and call remember("k") after it.
    """
    store = "_keep_" + key
    if key not in ss and store in ss:
        ss[key] = ss[store]
    if options is not None and key in ss and ss[key] not in options:
        ss.pop(key)
    return key


def remember(key: str) -> None:
    ss["_keep_" + key] = ss.get(key)


# ===========================================================================
# HTML + styled-widget helpers
# ===========================================================================
def h(text) -> str:
    """Escape text for HTML."""
    return _html.escape(str(text if text is not None else ""))


_HEADING_OPEN = re.compile(r"<h([1-6])(\s|>)")


_HEADING_CLOSE = re.compile(r"</h[1-6]>")


def _markup(markup: str) -> str:
    """One line of HTML, headings turned into <div class="hxN"> (no Streamlit heading anchors)."""
    markup = " ".join(line.strip() for line in markup.strip().splitlines())
    markup = _HEADING_OPEN.sub(lambda m: f'<div class="hx{m.group(1)}"{m.group(2)}', markup)
    return _HEADING_CLOSE.sub("</div>", markup)


def html(markup: str) -> None:
    """Show a piece of the design (display only - clicks go to Streamlit buttons).

    It goes through st.markdown(unsafe_allow_html=True) - the same way the logo
    intro is drawn - so inline SVG (icons, the floor plan, the logo) is kept.
    The wrapper's "clx" class is what the scoped design CSS hangs on.
    """
    st.markdown(f'<div class="clx">{_markup(markup)}</div>', unsafe_allow_html=True)


# ---- design CSS -> scoped to the .clx wrappers ------------------------------------
_SKIP_SCOPE = ("[", ".st", "#MainMenu", "footer:not", "header[", "section[", ":root")


_TAG_HEADING = re.compile(r"(?<![\w.#-])h([1-6])(?![\w-])")


def _split_top(text: str, sep: str = ",") -> list[str]:
    out, depth, cur = [], 0, ""
    for ch in text:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if ch == sep and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    return out + [cur]


def _scope_selector(sel: str) -> str:
    sel = sel.strip()
    if not sel or any(token in sel for token in _SKIP_SCOPE):
        return sel
    sel = _TAG_HEADING.sub(r".hx\1", sel)
    if sel in ("html", "body"):
        return ".clx"
    return ".clx " + sel


def scope_css(css: str) -> str:
    """Prefix the design's selectors with .clx so they win over Streamlit's own
    markdown styles, map h1-h6 to the .hxN divs, and move @import to the top."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    import_re = r"@import\s+(?:url\([^)]*\)|\"[^\"]*\"|'[^']*')[^;]*;"
    imports = re.findall(import_re, css)
    css = re.sub(import_re, "", css)

    def walk(text: str) -> str:
        out, i = [], 0
        while i < len(text):
            j = text.find("{", i)
            if j < 0:
                break
            head = text[i:j].strip()
            depth, k = 1, j + 1
            while k < len(text) and depth:
                depth += {"{": 1, "}": -1}.get(text[k], 0)
                k += 1
            body = text[j + 1:k - 1]
            if head.startswith("@media") or head.startswith("@supports"):
                out.append(f"{head}{{{walk(body)}}}")
            elif head.startswith("@"):
                out.append(f"{head}{{{body}}}")
            else:
                if head.strip() in ("html", "body"):  # page-level look: keep the font/colour, not the background
                    body = re.sub(r"background[^;]*;?", "", body)
                out.append(",".join(_scope_selector(s) for s in _split_top(head)) + f"{{{body}}}")
            i = k
        return "\n".join(out)

    headings = (".clx :is(.hx1,.hx2,.hx3,.hx4,.hx5,.hx6){display:block;font-weight:700;margin:0;}"
                ".clx .hx1{font-size:2em;}.clx .hx2{font-size:1.5em;}.clx .hx3{font-size:1.17em;}")
    return "\n".join(imports) + "\n" + headings + "\n" + walk(css)


def btn(label: str, key: str, kind: str = "ghost", *, full: bool = False, on_click=None, args=(),
        disabled: bool = False, icon: str | None = None, help: str | None = None) -> bool:
    """A Streamlit button dressed as one of the design's buttons.

    kind: primary, primarysm, ghost, ghostsm, success, successsm, danger,
    dangersm, link, x, chip, chipon, segb, segbon (see GLUE_CSS in portal.py).
    """
    kwargs = {"icon": icon} if icon else {}
    return st.button(label, key=f"{key}__{kind}__" + ("w__" if full else ""), on_click=on_click, args=args,
                     disabled=disabled, help=help, **kwargs)


def hit(markup: str, key: str, on_click, args=()) -> None:
    """A design element (card, row, menu item...) that is clickable as a whole."""
    with st.container(key=f"hitwrap_{key}"):
        html(markup)
        st.button("open", key=f"hit_{key}", on_click=on_click, args=args)


def box(key: str, *marks: str):
    """st.container whose look comes from the CSS markers (card, section, row, rowend, ...)."""
    return st.container(key=key + "".join(f"__{m}__" for m in marks))


def page_config(title: str) -> None:
    try:
        st.set_page_config(page_title=f"Centrum Laboratory - {title}", page_icon=page_icon(),
                           layout="wide", initial_sidebar_state="expanded")
    except st.errors.StreamlitAPIException:
        pass  # app.py already called set_page_config
