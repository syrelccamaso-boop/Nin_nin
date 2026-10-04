"""
frontend/chatbot.py - Centrum Assistant: a floating robot button + Messenger-style chat window.

Look / behaviour
    * A navy robot button floats at the bottom-right of the page.
    * Clicking it opens a chat window (header, bubbles, suggestion chips, text box).
      The X in the header minimizes it back to the robot button.
    * Drawn once per rerun, so it shows on every page of the dashboard.

Adding it to a dashboard (see Teacher.py):

    from frontend import chatbot
    ...
    chatbot.render(P, user, my_reports, navigate=go, config=MY_BOT_CONFIG)

    reports   list of dicts: id, where ("Laboratory 1 - PC 05"), issue (str) or issues (list),
              status, date (text). Anything missing is skipped.
    navigate  function taking the dashboard's REAL page key (e.g. "reports").
    config    adapts the wording and page names to the dashboard - see DEFAULT_CONFIG below.

Answers
    A simple built-in helper (keyword rules); it is NOT a language model. To plug a real one in,
    pass `external=` to render():

        def my_llm(question: str, history: list[dict]) -> str | None:
            ...  # call your FastAPI endpoint / an LLM; return text, or None to use the built-in answers

Try it on its own:   streamlit run frontend/chatbot.py
"""

from __future__ import annotations

import base64
import html
import re
from typing import Callable

import streamlit as st

NAVY = "#141d33"
BLUE = "#2f6fe4"


# ---------------------------------------------------------------------------
# Robot icon (redrawn as SVG from the supplied picture)
# ---------------------------------------------------------------------------
def robot_svg(fg: str = "#ffffff", eye: str = NAVY) -> str:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        f'<circle cx="12" cy="3.9" r="1.8" fill="{fg}"/>'
        f'<rect x="11.2" y="5" width="1.6" height="2.6" fill="{fg}"/>'
        f'<rect x="2.4" y="11" width="3.2" height="4.8" rx="1.6" fill="{fg}"/>'
        f'<rect x="18.4" y="11" width="3.2" height="4.8" rx="1.6" fill="{fg}"/>'
        f'<rect x="4.6" y="7.2" width="14.8" height="12" rx="5.2" fill="{fg}"/>'
        f'<rect x="8.2" y="11.4" width="2.3" height="4.2" rx="1.15" fill="{eye}"/>'
        f'<rect x="13.5" y="11.4" width="2.3" height="4.2" rx="1.15" fill="{eye}"/>'
        "</svg>"
    )


def _data_uri(svg: str) -> str:
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------
_CSS = """
<style>
/* ---- floating robot button ---- */
.st-key-__P___bot_fab { position:fixed !important; right:24px; bottom:24px; z-index:1000000; width:auto !important; }
.st-key-__P___bot_fab button {
  width:60px; height:60px; min-height:60px; padding:0 !important; border:none !important; border-radius:19px !important;
  background:__NAVY__ url("__ROBOT__") center / 34px 34px no-repeat !important;
  box-shadow:0 8px 24px rgba(20,29,51,.38); transition:transform .15s ease, box-shadow .15s ease;
}
.st-key-__P___bot_fab button:hover { transform:translateY(-2px) scale(1.04); box-shadow:0 12px 28px rgba(20,29,51,.45); }
.st-key-__P___bot_fab button p, .st-key-__P___bot_fab button span { display:none !important; }
.st-key-__P___bot_fab button::after {
  content:""; position:absolute; right:-3px; top:-3px; width:13px; height:13px; border-radius:50%;
  background:#31c48d; border:2.5px solid #f3f5f9;
}

/* ---- chat window ---- */
.st-key-__P___bot_panel {
  position:fixed !important; right:24px; bottom:24px; z-index:1000001;
  width:min(372px, calc(100vw - 24px)) !important; background:#fff; border:1px solid #e4e8ee; border-radius:20px;
  box-shadow:0 14px 44px rgba(20,29,51,.30); overflow:hidden; padding:0 !important; gap:0 !important;
}
.st-key-__P___bot_panel [data-testid="stElementContainer"] { width:100% !important; margin:0 !important; }
.bot-head { display:flex; align-items:center; gap:11px; padding:14px 56px 14px 16px; background:linear-gradient(135deg,#141d33,#22305a); }
.bot-av { width:38px; height:38px; flex:0 0 38px; border-radius:12px; background:rgba(255,255,255,.12); display:flex; align-items:center; justify-content:center; }
.bot-av svg { width:24px; height:24px; }
.bot-av.sm { width:26px; height:26px; flex-basis:26px; border-radius:50%; background:__NAVY__; }
.bot-av.sm svg { width:16px; height:16px; }
.bot-name { color:#fff; font-size:15px; font-weight:700; line-height:1.2; }
.bot-sub { color:#b9c4e0; font-size:12px; margin-top:2px; display:flex; align-items:center; gap:6px; }
.bot-dot { width:8px; height:8px; border-radius:50%; background:#31c48d; display:inline-block; }
.st-key-__P___bot_close { position:absolute !important; top:12px; right:12px; z-index:3; width:auto !important; }
.st-key-__P___bot_close button {
  width:34px; height:34px; min-height:34px; padding:0 !important; border-radius:50% !important;
  background:rgba(255,255,255,.14) !important; border:none !important; color:#fff !important;
}
.st-key-__P___bot_close button:hover { background:rgba(255,255,255,.28) !important; }
.st-key-__P___bot_close button p { display:none !important; }
.botscroll { height:330px; overflow-y:auto; display:flex; flex-direction:column-reverse; background:#f7f8fb; padding:14px 14px 6px; }
.botmsgs { display:flex; flex-direction:column; gap:9px; }
.brow { display:flex; align-items:flex-end; gap:8px; }
.bm { max-width:82%; padding:9px 13px; font-size:13.5px; line-height:1.5; word-wrap:break-word; border-radius:18px; }
.bm.bot { background:#fff; border:1px solid #e4e8ee; color:#1c2430; border-bottom-left-radius:6px; }
.bm.me { align-self:flex-end; margin-left:auto; background:__BLUE__; color:#fff; border-bottom-right-radius:6px; }
.bm b { font-weight:700; }
.bot-foot { font-size:11px; color:#a4adba; text-align:center; padding:2px 0 0; background:#f7f8fb; }

/* suggestion chips */
.st-key-__P___bot_chips { background:#f7f8fb; padding:6px 14px 10px !important; flex-direction:row !important; flex-wrap:wrap; gap:6px !important; }
.st-key-__P___bot_chips [data-testid="stElementContainer"] { width:auto !important; flex:0 0 auto; }
.st-key-__P___bot_chips button {
  min-height:0; padding:5px 12px !important; border-radius:100px !important; font-size:12.5px; font-weight:600;
  background:#fff !important; color:__BLUE__ !important; border:1px solid #cfe0fb !important;
}
.st-key-__P___bot_chips button:hover { background:#eaf2ff !important; }
.st-key-__P___bot_chips button p { font-size:12.5px; }

/* input row */
.st-key-__P___bot_form_wrap { border-top:1px solid #e4e8ee; background:#fff; padding:10px 12px !important; }
.st-key-__P___bot_form_wrap [data-testid="stForm"] { border:none !important; padding:0 !important; }
.st-key-__P___bot_form_wrap [data-testid="stTextInput"] input { border-radius:100px; background:#f1f3f8; border:1px solid transparent; padding:9px 14px; font-size:13.5px; }
.st-key-__P___bot_form_wrap [data-testid="stTextInput"] input:focus { border-color:__BLUE__; background:#fff; }
.st-key-__P___bot_form_wrap [data-testid="InputInstructions"] { display:none; }
.st-key-__P___bot_form_wrap [data-testid="stFormSubmitButton"] button {
  width:40px; height:40px; min-height:40px; padding:0 !important; border-radius:50% !important;
  background:__BLUE__ !important; border:none !important; color:#fff !important;
}
.st-key-__P___bot_form_wrap [data-testid="stFormSubmitButton"] button p { display:none !important; }
</style>
"""


def _css(p: str) -> str:
    return (_CSS.replace("__P__", p).replace("__NAVY__", NAVY).replace("__BLUE__", BLUE)
            .replace("__ROBOT__", _data_uri(robot_svg())))


# ---------------------------------------------------------------------------
# Built-in answers
# ---------------------------------------------------------------------------
# Logical page names used inside the answers -> shown to the user via `names`,
# and mapped to the dashboard's real page keys via `pages`.
DEFAULT_CONFIG: dict = {
    "names": {"report": "Report an Issue", "myreports": "My Reports", "inventory": "Unit Inventory", "settings": "Settings"},
    "pages": {"report": "report", "myreports": "myreports", "inventory": "inventory", "settings": "settings"},
    # (label, set of report statuses) - used for "how many reports" and for naming a report's status
    "status_groups": [("being fixed", {"progress"}), ("resolved", {"resolved"}), ("needing follow-up", {"followup"})],
    "status_help": ("**Being fixed** - the technician has your report and is working on it.\n"
                    "**Resolved** - the problem is fixed.\n"
                    "**Needs follow-up** - the fix didn't hold or the unit keeps having problems, so it's flagged for a closer look."),
    "report_howto": ("1. Open **{report}**.\n2. Pick the room and the computer unit.\n"
                     "3. Tick the issue type(s) and add a comment if you like.\n4. Review it, then **Confirm & submit**.\n"
                     "Your name and the time are added automatically."),
    "inventory_help": "Open **{inventory}**, pick a lab, then tap a unit to see its hardware, software and past maintenance.",
    "contact_help": "You can update your contact number in **{settings}**.",
    "password_help": "Log out and use **Forgot password?** on the login screen.",
    "urgent_help": None,
    "wait_help": ("I can't promise a time - the technician picks reports up from their queue. You can watch the "
                  "status change in {myreports}, and it updates as soon as they start or finish."),
}


def _cfg(config: dict | None) -> dict:
    c = {**DEFAULT_CONFIG, **(config or {})}
    c["names"] = {**DEFAULT_CONFIG["names"], **(config or {}).get("names", {})}
    c["pages"] = {**DEFAULT_CONFIG["pages"], **(config or {}).get("pages", {})}
    return c


def _fill(text: str, c: dict) -> str:
    return text.format(**c["names"]) if text else text


def _status_word(status, c: dict) -> str:
    for label, keys in c["status_groups"]:
        if status in keys:
            return label
    return str(status or "unknown")


def prompts(c: dict) -> list[tuple]:
    return [("ask", "How do I report an issue?"), ("ask", "Status of my reports"),
            ("ask", "What do the statuses mean?"), ("ask", "Where can I see a computer's details?")]


def _has(t: str, *words: str) -> bool:
    return any(w in t for w in words)


def _norm(x) -> str:
    return re.sub(r"[^a-z0-9]", "", str(x).lower())


def _issues(r: dict) -> str:
    v = r.get("issues") or r.get("issue") or []
    v = [v] if isinstance(v, str) else list(v)
    return ", ".join(v) or "no issue listed"


def _where(r: dict) -> str:
    if r.get("where"):
        return str(r["where"])
    unit = r.get("unit")
    try:
        unit = f"Unit {int(unit):02d}"
    except (TypeError, ValueError):
        unit = str(unit or "")
    return f"{r.get('room', '')} {unit}".strip()


def _describe(r: dict, c: dict) -> str:
    return f"**{r.get('id', '?')}** - {_where(r)} ({_issues(r)}), {_status_word(r.get('status'), c)}"


def answer(text: str, user: dict, reports: list[dict], config: dict | None = None) -> tuple[str, list[tuple]]:
    """Return (reply, suggestions) for what the user typed."""
    c = _cfg(config)
    nm = c["names"]
    go = lambda key: ("go", f"Open {nm[key]}", key)  # noqa: E731
    P_ = prompts(c)
    t = " ".join(text.lower().split())
    tn = _norm(t)
    first = (user.get("name") or "").split(" ")[0]
    more = [("ask", "How do I report an issue?"), ("ask", "Status of my reports")]

    # a report number typed by the user, e.g. "status of CL-1042"
    hit = next((r for r in reports if _norm(r.get("id", "")) and _norm(r["id"]) in tn), None)
    if hit:
        when = f"\nSent {hit['date']}." if hit.get("date") else ""
        return _describe(hit, c) + when, [go("myreports")]
    m = re.search(r"\b(cl|r)[-\s]?(\d{3,5})\b", t)  # report numbers look like CL-1042 or R-1042
    if m:
        rid = f"{m.group(1).upper()}-{m.group(2)}"
        return (f"I can't find **{rid}** in your reports. Open {nm['myreports']} to see everything you've sent.",
                [go("myreports")])

    words = set(re.findall(r"[a-z']+", t))
    if len(words) <= 4 and (words & {"hi", "hello", "hey", "hiya", "morning", "afternoon", "evening"}):
        return f"Hi{' ' + first if first else ''}! What can I help you with?", P_

    if _has(t, "thank", "thanks", "salamat"):
        return "You're welcome! Anything else I can help with?", more

    if _has(t, "mean", "difference", "what is in progress", "what's in progress", "what does follow"):
        return _fill(c["status_help"], c), [go("myreports")]

    if _has(t, "my report", "my reports", "status", "track", "check on", "how many", "latest", "pending", "any update"):
        if not reports:
            return "You haven't sent any reports yet. Need to report a problem?", [go("report")]
        parts = ", ".join(f"{sum(1 for r in reports if r.get('status') in keys)} {label}"
                          for label, keys in c["status_groups"])
        return (f"You have **{len(reports)}** report{'s' if len(reports) != 1 else ''}: {parts}.\n"
                f"Latest: {_describe(reports[0], c)}."), [go("myreports"), ("ask", "What do the statuses mean?")]

    if _has(t, "urgent", "urgency", "priority", "emergency", "asap") and c["urgent_help"]:
        return _fill(c["urgent_help"], c), [go("report")]

    if _has(t, "how long", "when will", "how soon", "fixed yet", "technician"):
        return _fill(c["wait_help"], c), [go("myreports")]

    if _has(t, "inventory", "unit details", "unit's", "computer's", "hardware", "software", "specs", "history",
            "details", "floor map", "map", "laboratory status", "lab status"):
        return _fill(c["inventory_help"], c), [go("inventory")]

    if _has(t, "report", "issue", "problem", "broken", "not working", "won't", "wont", "slow", "internet",
            "keyboard", "mouse", "monitor", "turn on", "how do i", "how to"):
        return "To report a problem:\n" + _fill(c["report_howto"], c), [go("report"), ("ask", "Status of my reports")]

    if _has(t, "contact", "number", "phone", "profile"):
        return _fill(c["contact_help"], c), [go("settings")]

    if _has(t, "password", "forgot"):
        return _fill(c["password_help"], c), [go("settings")]

    if _has(t, "log out", "logout", "sign out"):
        return f"You can log out from **{nm['settings']}** or from the menu at the top.", [go("settings")]

    if _has(t, "who are you", "what can you do", "help", "what do you do"):
        return ("I'm the Centrum Assistant. I can walk you through reporting a computer problem, check on the "
                "reports you've sent, and point you to the right page."), P_

    return ("I'm a simple helper, so I may have missed that. I can help with reporting a problem, checking your "
            "reports, and finding computer details. Try one of these:"), P_


# ---------------------------------------------------------------------------
# State + callbacks
# ---------------------------------------------------------------------------
def _k(p: str, name: str) -> str:
    return f"{p}_bot_{name}"


def _greeting(user: dict, c: dict) -> dict:
    first = (user.get("name") or "").split(" ")[0]
    return {"role": "bot", "suggest": prompts(c),
            "text": f"Hi{' ' + first if first else ''}! I'm the **Centrum Assistant**. I can help you report a "
                    "computer problem, check on your reports, or find your way around."}


def _set_open(p: str, value: bool) -> None:
    st.session_state[_k(p, "open")] = value


def _ask(p: str, text: str, ctx: dict) -> None:
    text = (text or "").strip()
    if not text:
        return
    msgs: list[dict] = st.session_state[_k(p, "msgs")]
    msgs.append({"role": "me", "text": text})
    reply, suggest = None, None
    if ctx.get("external"):
        try:
            reply = ctx["external"](text, msgs)
        except Exception:  # never let a failing backend break the page
            reply = None
    if reply is None:
        reply, suggest = answer(text, ctx["user"], ctx["reports"], ctx["config"])
    else:
        suggest = [("ask", "Status of my reports")]
    msgs.append({"role": "bot", "text": reply, "suggest": suggest})
    del msgs[:-60]


def _send(p: str, ctx: dict) -> None:
    _ask(p, st.session_state.get(_k(p, "input"), ""), ctx)


def _go(p: str, page: str, ctx: dict) -> None:
    """page is a logical name ("report", "myreports", "inventory", "settings")."""
    if ctx.get("navigate"):
        ctx["navigate"](ctx["config"]["pages"].get(page, page))


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------
def _fmt(text: str) -> str:
    out = html.escape(text).replace("\n", "<br>")
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", out)


def _bubbles(msgs: list[dict]) -> str:
    av = f'<div class="bot-av sm">{robot_svg()}</div>'
    rows = []
    for m in msgs:
        if m["role"] == "me":
            rows.append(f'<div class="brow"><div class="bm me">{_fmt(m["text"])}</div></div>')
        else:
            rows.append(f'<div class="brow">{av}<div class="bm bot">{_fmt(m["text"])}</div></div>')
    return f'<div class="botscroll"><div class="botmsgs">{"".join(rows)}</div></div>'


def render(p: str, user: dict, reports: list[dict] | None = None, *,
           navigate: Callable[[str], None] | None = None,
           external: Callable[[str, list[dict]], str | None] | None = None,
           config: dict | None = None) -> None:
    """Draw the floating robot button / chat window. Call once per run, after the page content.

    p         session-state prefix of the dashboard (e.g. "teacher"); keeps widget keys unique
    user      dict with at least "name"
    reports   the signed-in user's reports, newest first (lets the assistant answer "status of my reports")
    navigate  callback taking the dashboard's real page key -> opens that page
    external  optional function(question, history) -> reply text, or None to use the built-in answers
    config    wording / page-name overrides, see DEFAULT_CONFIG
    """
    ss = st.session_state
    ss.setdefault(_k(p, "open"), False)
    cfg = _cfg(config)
    ss.setdefault(_k(p, "msgs"), [_greeting(user, cfg)])
    reports = reports or []
    ctx = {"user": user, "reports": reports, "navigate": navigate, "external": external, "config": cfg}

    st.markdown(_css(p), unsafe_allow_html=True)

    if not ss[_k(p, "open")]:
        with st.container(key=_k(p, "fab")):
            st.button("Open assistant", key=_k(p, "fab_btn"), help="Chat with Centrum Assistant",
                      on_click=_set_open, args=(p, True))
        return

    msgs: list[dict] = ss[_k(p, "msgs")]
    with st.container(key=_k(p, "panel")):
        st.markdown(
            f'<div class="bot-head"><div class="bot-av">{robot_svg()}</div><div>'
            '<div class="bot-name">Centrum Assistant</div>'
            '<div class="bot-sub"><span class="bot-dot"></span>Here to help</div></div></div>',
            unsafe_allow_html=True)
        with st.container(key=_k(p, "close")):
            st.button("Close chat", key=_k(p, "close_btn"), icon=":material/close:", help="Minimize",
                      on_click=_set_open, args=(p, False))

        st.markdown(_bubbles(msgs), unsafe_allow_html=True)

        last = msgs[-1] if msgs else None
        suggest = (last or {}).get("suggest") if last and last["role"] == "bot" else None
        if suggest:
            with st.container(key=_k(p, "chips")):
                for i, s in enumerate(suggest):
                    if s[0] == "ask":
                        st.button(s[1], key=_k(p, f"chip_{len(msgs)}_{i}"), on_click=_ask, args=(p, s[1], ctx))
                    else:
                        st.button(f"{s[1]} \u203a", key=_k(p, f"chip_{len(msgs)}_{i}"),
                                  on_click=_go, args=(p, s[2], ctx))

        with st.container(key=_k(p, "form_wrap")):
            with st.form(_k(p, "form"), clear_on_submit=True, border=False):
                c1, c2 = st.columns([6, 1], vertical_alignment="center")
                c1.text_input("Message", key=_k(p, "input"), placeholder="Ask the assistant...",
                              label_visibility="collapsed")
                c2.form_submit_button("Send", icon=":material/send:", on_click=_send, args=(p, ctx))
        st.markdown('<div class="bot-foot">Automated helper - not a person</div>', unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# `streamlit run frontend/chatbot.py`  (stand-alone demo)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    st.set_page_config(page_title="Chatbot demo", layout="wide")
    st.title("Dashboard")
    st.caption("Demo page - the robot button is at the bottom right.")
    _demo_user = {"name": "Alwyna Lopez"}
    _demo_reports = [
        {"id": "CL-1043", "room": "CL 1", "unit": 3, "issues": ["Slow performance"], "status": "progress", "date": "Oct 02, 2026"},
        {"id": "CL-1042", "room": "CL 2", "unit": 7, "issues": ["No internet"], "status": "resolved", "date": "Sep 28, 2026"},
        {"id": "CL-1041", "room": "CL 1", "unit": 15, "issues": ["Won't turn on"], "status": "followup", "date": "Sep 20, 2026"},
    ]
    render("demo", _demo_user, _demo_reports, navigate=lambda page: st.toast(f"Would open: {page}"))
