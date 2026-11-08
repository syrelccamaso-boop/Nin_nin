"""
frontend/first_login.py - Computer Laboratory | change a temporary password

Shown right after login, instead of the dashboard, when the account was given a
temporary password by an Admin (see admin.py -> Add New Admin Account, which
calls lab_store.mark_temp_password). The user must choose their own password
before they can continue. Only the email and date are kept in the shared store,
never a password.

The password is changed through the existing authentication API (the same calls
My Profile uses):

    Admin       backend_client.admin_change_password(token, current, new)
    Technician  backend_client.change_password(token, current, new)

Nothing is changed locally or faked: the flag is cleared only after the backend
confirms the new password.

    from frontend import first_login
    if first_login.required(user):
        first_login.render(user)
        st.stop()
"""

from __future__ import annotations

import streamlit as st

from frontend import backend_client
from frontend import lab_store
from frontend import portal
from frontend import ui

ss = st.session_state
html, btn, box, h = ui.html, ui.btn, ui.box, ui.h
K = "firstpw"

RULES = portal.Shell.PW_RULES


def required(user: dict) -> bool:
    email = (ui.normalize_user(user).get("email") or "").strip().lower()
    return bool(email) and lab_store.needs_password_change(email)


def _change(role: str, current: str, new: str) -> tuple[bool, str]:
    token = ss.get(ui.TOKEN_KEY)
    if not token:
        return False, "Your session has expired. Log out and log in again."
    role = (role or "").lower()
    try:
        if role in ("admin", "administrator"):
            result = backend_client.admin_change_password(token, current, new)
        elif role == "technician":
            result = backend_client.change_password(token, current, new)
        else:
            return False, "Password changes for this role are not available here. Please contact the administrator."
    except Exception:
        return False, "Could not connect to the server. Your password was not changed."
    if not result.get("success"):
        return False, result.get("error") or "Your password was not changed."
    return True, result.get("message") or "Your password was changed."


def _submit(user: dict) -> None:
    cur, new, conf = (ss.get(f"{K}_{k}") or "" for k in ("cur", "new", "conf"))
    errors = {}
    if not cur:
        errors["cur"] = "Enter the temporary password you were given."
    if not new:
        errors["new"] = "Choose a new password."
    elif not all(test(new) for _, _, test in RULES):
        errors["new"] = "The new password doesn't meet all the requirements."
    elif new == cur:
        errors["new"] = "The new password must be different from the temporary one."
    if not conf:
        errors["conf"] = "Type the new password again."
    elif new and conf != new:
        errors["conf"] = "The passwords don't match."
    ss[f"{K}_errors"] = errors
    ss.pop(f"{K}_result", None)
    if errors:
        return
    ok, msg = _change(user.get("role"), cur, new)
    for k in ("cur", "new", "conf"):
        ss[f"{K}_{k}"] = ""
    if ok:
        lab_store.clear_temp_password(user.get("email"))
        ss[f"{K}_done"] = True
        ui.flash("firstpw", "Your password was changed. Welcome!")
    else:
        ss[f"{K}_result"] = msg


def render(user: dict) -> None:
    user = ui.normalize_user(user)
    ui.page_config("Change your password")
    st.markdown(f"<style>{portal.css()}{_CSS}</style>", unsafe_allow_html=True)
    ui.install_loader()
    errors = ss.get(f"{K}_errors") or {}
    new_pw = ss.get(f"{K}_new") or ""
    conf_pw = ss.get(f"{K}_conf") or ""
    with st.container(key="cl_content"):
        with box("firstpw_card", "card", "fpcard"):
            html(
                f'<div class="fp-head"><div class="ic ic-blue">{portal.ic("shield")}</div><div>'
                f'<h3>Choose your own password</h3><div class="sub">Hi {h(portal.first_name(user["name"]))}! '
                "Your account was set up with a temporary password. For your security, please choose "
                "a new password before you continue.</div></div></div>"
            )
            if ss.get(f"{K}_result"):
                html(f'<div class="pw-msg err">{portal.ic("alert")}<span><b>Password not changed.</b> '
                     f'{h(ss[f"{K}_result"])}</span></div>')
            with box("firstpw_grid", "pwgrid"):
                with box("firstpw_fields", "pwfields"):
                    for k, label, ph in (
                        ("cur", "Temporary password", "The password you were given"),
                        ("new", "New password", "At least 8 characters"),
                        ("conf", "Confirm new password", "Type the new password again"),
                    ):
                        st.text_input(label, type="password", key=f"{K}_{k}", placeholder=ph,
                                      autocomplete="current-password" if k == "cur" else "new-password")
                        if errors.get(k):
                            html(f'<div class="pw-err">{portal.ic("alert")}<span>{h(errors[k])}</span></div>')
                rules = "".join(
                    f'<li class="{"ok" if test(new_pw) else ""}"><i>✓</i>{h(label)}</li>'
                    for _, label, test in RULES
                )
                match = bool(new_pw) and new_pw == conf_pw
                rules += f'<li class="{"ok" if match else ""}"><i>✓</i>Both new passwords match</li>'
                html(f'<div class="pw-rules"><h4>Password requirements</h4><ul>{rules}</ul></div>')
            with box("firstpw_btns", "mactions"):
                btn("Log out", "firstpw_logout", "ghost", icon=":material/logout:", on_click=ui.logout_user)
                btn("Save new password", "firstpw_save", "primary", icon=":material/lock_reset:",
                    on_click=_submit, args=(user,))


_CSS = """
.st-key-cl_content { max-width: 860px; margin: 6vh auto 0; }
.fp-head { display: flex; gap: 14px; align-items: flex-start; margin-bottom: 18px; }
.fp-head .ic { width: 46px; height: 46px; border-radius: 14px; display: grid; place-items: center; flex: none; }
.fp-head h3 { font: 600 19px 'Poppins', sans-serif; color: #14213d; margin: 0 0 4px; }
.fp-head .sub { font-size: 13.5px; color: #5b6472; }
section[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"] { display: none !important; }
"""
