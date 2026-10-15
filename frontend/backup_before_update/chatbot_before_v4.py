"""
frontend/chatbot.py - Centrum Assistant

A floating robot button + Messenger-style chat window for Streamlit.
Position, size, colours and layout are the original design.

How a message is answered (first match wins):

    1. ``external`` callback passed to render()          (optional)
    2. Direct answers built from the VERIFIED reports the dashboard passes in
       (report status, "which computer", "is it fixed", a specific report ID)
       and fixed dashboard help. No AI is involved, so these facts can never
       be invented.
    3. backend.ai_service.stream_chat()  - streams Gemini's answer, grounded in
       the lab knowledge base (or the knowledge base alone if Gemini is down).
    4. The built-in rule-based helper, with a visible notice that the AI is
       unavailable.

How streaming works in Streamlit: submitting a message only stores it as
"pending" and reruns. The rerun draws the panel with a typing indicator, then
streams the answer into the message area piece by piece, and finally reruns
once more to draw the suggestion chips.

Requires a Streamlit version that supports ``st.button(icon=...)``,
``st.container(key=...)`` and ``st.rerun()``.
"""

from __future__ import annotations

import base64
import html
import logging
import re
import time
from functools import lru_cache
from typing import Any, Callable, Iterator

import streamlit as st

from backend import ai_service

log = logging.getLogger("centrum.chatbot")

NAVY = "#141d33"
BLUE = "#2f6fe4"

MAX_INPUT_CHARS = 1000        # longest message a user can send
MAX_STORED_MESSAGES = 60      # chat history kept in session state
MAX_PROMPT_HISTORY = 8        # recent messages sent to the AI
MAX_PROMPT_REPORTS = 15       # reports sent to the AI (newest first)
PAINT_INTERVAL = 0.06         # seconds between streaming repaints

AI_DOWN_NOTICE = (
    "⚠️ The AI assistant isn't available right now, "
    "so I'm using the built-in helper.\n\n"
)
INTERRUPTED_NOTE = "\n\n_(The connection was interrupted, so this answer may be incomplete.)_"

_AI_SUGGEST = [
    ("ask", "Status of my reports"),
    ("ask", "How do I report an issue?"),
]


# ---------------------------------------------------------------------------
# Robot icon
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


@lru_cache(maxsize=1)
def _avatar_html() -> str:
    return f'<div class="bot-av sm">{robot_svg()}</div>'


# ---------------------------------------------------------------------------
# Styles (placeholders use %%TOKEN%% so they never collide with CSS syntax)
# ---------------------------------------------------------------------------

_CSS = """
<style>
/* ---------- Floating robot button ---------- */
.st-key-%%P%%_bot_fab {
    position: fixed !important;
    right: 24px;
    bottom: 24px;
    z-index: 1000000;
    width: auto !important;
}
.st-key-%%P%%_bot_fab button {
    width: 60px;
    height: 60px;
    min-height: 60px;
    padding: 0 !important;
    border: none !important;
    border-radius: 19px !important;
    background: %%NAVY%% url("%%ROBOT%%") center / 34px 34px no-repeat !important;
    box-shadow: 0 8px 24px rgba(20,29,51,.38);
    transition: transform .15s ease, box-shadow .15s ease;
}
.st-key-%%P%%_bot_fab button:hover {
    transform: translateY(-2px) scale(1.04);
    box-shadow: 0 12px 28px rgba(20,29,51,.45);
}
.st-key-%%P%%_bot_fab button p,
.st-key-%%P%%_bot_fab button span { display: none !important; }
.st-key-%%P%%_bot_fab button::after {
    content: "";
    position: absolute;
    right: -3px;
    top: -3px;
    width: 13px;
    height: 13px;
    border-radius: 50%;
    background: #31c48d;
    border: 2.5px solid #f3f5f9;
}

/* ---------- Chat window ---------- */
.st-key-%%P%%_bot_panel {
    position: fixed !important;
    right: 24px;
    bottom: 24px;
    z-index: 1000001;
    width: min(372px, calc(100vw - 24px)) !important;
    background: #fff;
    border: 1px solid #e4e8ee;
    border-radius: 20px;
    box-shadow: 0 14px 44px rgba(20,29,51,.30);
    overflow: hidden;
    padding: 0 !important;
    gap: 0 !important;
}
.st-key-%%P%%_bot_panel [data-testid="stElementContainer"] {
    width: 100% !important;
    margin: 0 !important;
}

/* ---------- Header ---------- */
.bot-head {
    display: flex;
    align-items: center;
    gap: 11px;
    padding: 14px 56px 14px 16px;
    background: linear-gradient(135deg, #141d33, #22305a);
}
.bot-av {
    width: 38px;
    height: 38px;
    flex: 0 0 38px;
    border-radius: 12px;
    background: rgba(255,255,255,.12);
    display: flex;
    align-items: center;
    justify-content: center;
}
.bot-av svg { width: 24px; height: 24px; }
.bot-av.sm {
    width: 26px;
    height: 26px;
    flex-basis: 26px;
    border-radius: 50%;
    background: %%NAVY%%;
}
.bot-av.sm svg { width: 16px; height: 16px; }
.bot-name { color: #fff; font-size: 15px; font-weight: 700; line-height: 1.2; }
.bot-sub {
    color: #b9c4e0;
    font-size: 12px;
    margin-top: 2px;
    display: flex;
    align-items: center;
    gap: 6px;
}
.bot-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #31c48d;
    display: inline-block;
}

/* ---------- Close button ---------- */
.st-key-%%P%%_bot_close {
    position: absolute !important;
    top: 12px;
    right: 12px;
    z-index: 3;
    width: auto !important;
}
.st-key-%%P%%_bot_close button {
    width: 34px;
    height: 34px;
    min-height: 34px;
    padding: 0 !important;
    border-radius: 50% !important;
    background: rgba(255,255,255,.14) !important;
    border: none !important;
    color: #fff !important;
}
.st-key-%%P%%_bot_close button:hover { background: rgba(255,255,255,.28) !important; }
.st-key-%%P%%_bot_close button p { display: none !important; }

/* ---------- Messages ---------- */
.botscroll {
    height: 330px;
    overflow-y: auto;
    overscroll-behavior: contain;
    display: flex;
    flex-direction: column-reverse;   /* keeps the newest message in view */
    background: #f7f8fb;
    padding: 14px 14px 6px;
}
.botmsgs { display: flex; flex-direction: column; gap: 9px; }
.brow { display: flex; align-items: flex-end; gap: 8px; }
.bm {
    max-width: 82%;
    padding: 9px 13px;
    font-size: 13.5px;
    line-height: 1.5;
    overflow-wrap: anywhere;
    border-radius: 18px;
    user-select: text;
    -webkit-user-select: text;
}
.bm.bot {
    background: #fff;
    border: 1px solid #e4e8ee;
    color: #1c2430;
    border-bottom-left-radius: 6px;
}
.bm.me {
    margin-left: auto;
    background: %%BLUE%%;
    color: #fff;
    border-bottom-right-radius: 6px;
}
.bm b { font-weight: 700; }
.bm code {
    background: rgba(20,29,51,.08);
    padding: 1px 5px;
    border-radius: 5px;
    font-size: 12.5px;
}
.bm.me code { background: rgba(255,255,255,.2); }
.bm.typing { padding: 12px 14px; }
.bm.typing span {
    display: inline-block;
    width: 6px;
    height: 6px;
    margin: 0 2px;
    border-radius: 50%;
    background: #a4adba;
    animation: botdot 1s infinite ease-in-out;
}
.bm.typing span:nth-child(2) { animation-delay: .15s; }
.bm.typing span:nth-child(3) { animation-delay: .3s; }
@keyframes botdot {
    0%, 80%, 100% { opacity: .3; transform: translateY(0); }
    40% { opacity: 1; transform: translateY(-3px); }
}
.bot-foot {
    font-size: 11px;
    color: #a4adba;
    text-align: center;
    padding: 2px 0 0;
    background: #f7f8fb;
}

/* ---------- Suggestion chips ---------- */
.st-key-%%P%%_bot_chips {
    background: #f7f8fb;
    padding: 6px 14px 10px !important;
    flex-direction: row !important;
    flex-wrap: wrap;
    gap: 6px !important;
}
.st-key-%%P%%_bot_chips [data-testid="stElementContainer"] {
    width: auto !important;
    flex: 0 0 auto;
}
.st-key-%%P%%_bot_chips button,
.st-key-%%P%%_bot_chips [data-testid^="stBaseButton"] {
    min-height: 0;
    padding: 5px 12px !important;
    border-radius: 100px !important;
    font-size: 12.5px;
    font-weight: 600;
    background: #eaf2ff !important;
    color: %%BLUE%% !important;
    border: 1px solid #b9d2fa !important;
    opacity: 1 !important;
}
.st-key-%%P%%_bot_chips button:hover,
.st-key-%%P%%_bot_chips [data-testid^="stBaseButton"]:hover {
    background: #d9e8ff !important;
    border-color: %%BLUE%% !important;
}
.st-key-%%P%%_bot_chips button p,
.st-key-%%P%%_bot_chips button div,
.st-key-%%P%%_bot_chips button span {
    font-size: 12.5px;
    color: %%BLUE%% !important;
    opacity: 1 !important;
}
/* Streamlit fades "stale" elements while a reply is being written, which made
   the chips look solid gray. Keep them fully readable. */
.st-key-%%P%%_bot_chips [data-stale="true"],
.st-key-%%P%%_bot_chips [data-stale="true"] * { opacity: 1 !important; }
.st-key-%%P%%_bot_chips [data-testid="stElementContainer"] { opacity: 1 !important; }

/* ---------- Input ---------- */
.st-key-%%P%%_bot_form_wrap {
    border-top: 1px solid #e4e8ee;
    background: #fff;
    padding: 10px 12px !important;
}
.st-key-%%P%%_bot_form_wrap [data-testid="stForm"] { border: none !important; padding: 0 !important; }
.st-key-%%P%%_bot_form_wrap [data-testid="stTextInput"] input {
    border-radius: 100px;
    background: #f1f3f8;
    border: 1px solid transparent;
    padding: 9px 14px;
    font-size: 13.5px;
}
.st-key-%%P%%_bot_form_wrap [data-testid="stTextInput"] input:focus {
    border-color: %%BLUE%%;
    background: #fff;
}
.st-key-%%P%%_bot_form_wrap [data-testid="stTextInput"] input::placeholder {
    color: #5b6b86 !important;
    opacity: 1 !important;
}
/* Keep the box readable (light blue, dark text) even while it is disabled
   or faded as "stale" during an answer. */
.st-key-%%P%%_bot_form_wrap [data-testid="stTextInput"] input:disabled {
    background: #eaf2ff !important;
    color: #1c2430 !important;
    -webkit-text-fill-color: #1c2430 !important;
    opacity: 1 !important;
    cursor: wait;
}
.st-key-%%P%%_bot_form_wrap [data-stale="true"],
.st-key-%%P%%_bot_form_wrap [data-stale="true"] * { opacity: 1 !important; }
.st-key-%%P%%_bot_form_wrap [data-testid="InputInstructions"] { display: none; }
.st-key-%%P%%_bot_form_wrap [data-testid="stFormSubmitButton"] button {
    width: 40px;
    height: 40px;
    min-height: 40px;
    padding: 0 !important;
    border-radius: 50% !important;
    background: %%BLUE%% !important;
    border: none !important;
    color: #fff !important;
}
.st-key-%%P%%_bot_form_wrap [data-testid="stFormSubmitButton"] button p { display: none !important; }

/* ---------- Dark mode (computer / browser set to dark) ---------- */
@media (prefers-color-scheme: dark) {
    .st-key-%%P%%_bot_panel { background: #131b2e; border-color: #253150; box-shadow: 0 24px 60px rgba(0,0,0,.55); }
    .st-key-%%P%%_bot_fab button::after { border-color: #0b1120; }
    .botscroll, .bot-foot, .st-key-%%P%%_bot_chips { background: #0f1729; }
    .bot-foot { color: #7f8aa1; }
    .bm.bot { background: #18223a; border-color: #253150; color: #e3e8f1; }
    .bm code { background: rgba(255,255,255,.08); }
    .bm.typing span { background: #6f7c96; }
    .st-key-%%P%%_bot_chips button,
    .st-key-%%P%%_bot_chips [data-testid^="stBaseButton"] {
        background: rgba(79,141,255,.14) !important; border-color: #36558f !important; color: #8fb6ff !important; }
    .st-key-%%P%%_bot_chips button:hover,
    .st-key-%%P%%_bot_chips [data-testid^="stBaseButton"]:hover { background: rgba(79,141,255,.26) !important; border-color: #4f8dff !important; }
    .st-key-%%P%%_bot_chips button p,
    .st-key-%%P%%_bot_chips button div,
    .st-key-%%P%%_bot_chips button span { color: #8fb6ff !important; }
    .st-key-%%P%%_bot_form_wrap { background: #131b2e; border-top-color: #253150; }
    .st-key-%%P%%_bot_form_wrap [data-testid="stTextInput"] input,
    .st-key-%%P%%_bot_form_wrap [data-testid="stTextInput"] input:focus {
        background: #0f1729 !important; color: #e3e8f1 !important; -webkit-text-fill-color: #e3e8f1 !important; }
    .st-key-%%P%%_bot_form_wrap [data-testid="stTextInput"] input::placeholder { color: #8a97b3 !important; }
    .st-key-%%P%%_bot_form_wrap [data-testid="stTextInput"] input:disabled {
        background: #18223a !important; color: #e3e8f1 !important; -webkit-text-fill-color: #e3e8f1 !important; }
}

@media (prefers-reduced-motion: reduce) {
    .st-key-%%P%%_bot_fab button { transition: none; }
    .bm.typing span { animation: none; opacity: .6; }
}
</style>
"""


@lru_cache(maxsize=32)
def _css(p: str) -> str:
    return (
        _CSS.replace("%%P%%", p)
        .replace("%%NAVY%%", NAVY)
        .replace("%%BLUE%%", BLUE)
        .replace("%%ROBOT%%", _data_uri(robot_svg()))
    )


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_CONFIG: dict = {
    "names": {
        "report": "Report an Issue",
        "myreports": "My Reports",
        "inventory": "Unit Inventory",
        "settings": "Settings",
    },
    "pages": {
        "report": "report",
        "myreports": "myreports",
        "inventory": "inventory",
        "settings": "settings",
    },
    "status_groups": [
        ("being fixed", {"progress"}),
        ("resolved", {"resolved"}),
        ("needing follow-up", {"followup"}),
    ],
    "status_help": (
        "**Being fixed** - the technician has your report and is working on it.\n"
        "**Resolved** - the problem is fixed.\n"
        "**Needs follow-up** - the fix didn't hold or the unit keeps having problems, "
        "so it's flagged for a closer look."
    ),
    "report_howto": (
        "1. Open **{report}**.\n"
        "2. Pick the room and the computer unit.\n"
        "3. Tick the issue type(s) and add a comment if you like.\n"
        "4. Review it, then **Confirm & submit**.\n"
        "Your name and the time are added automatically."
    ),
    "inventory_help": (
        "Open **{inventory}**, pick a lab, then tap a unit to see "
        "its hardware, software and past maintenance."
    ),
    "contact_help": "You can update your contact number in **{settings}**.",
    "password_help": "Log out and use **Forgot password?** on the login screen.",
    "urgent_help": None,
    "wait_help": (
        "I can't promise a time - the technician picks reports up from their queue. "
        "You can watch the status change in {myreports}, and it updates as soon as "
        "they start or finish."
    ),
    # Optional: callable(report: dict, user: dict) -> bool. When set, reports it
    # rejects are dropped before anything is shown or sent to the AI. Use it as
    # a second safety check if the reports list might ever contain other
    # people's records.
    "report_owner_check": None,
}


def _cfg(config: dict | None) -> dict:
    """Merge a dashboard's overrides on top of DEFAULT_CONFIG (names/pages deep-merged)."""
    config = config or {}
    c = {**DEFAULT_CONFIG, **config}
    c["names"] = {**DEFAULT_CONFIG["names"], **config.get("names", {})}
    c["pages"] = {**DEFAULT_CONFIG["pages"], **config.get("pages", {})}
    return c


class _SafeNames(dict):
    """format_map helper: unknown {placeholders} are left as-is instead of raising."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def _fill(text: str | None, c: dict) -> str:
    if not text:
        return ""
    try:
        return text.format_map(_SafeNames(c["names"]))
    except (ValueError, IndexError):  # stray "{" or "}" in custom wording
        return text


def _status_word(status: Any, c: dict) -> str:
    for label, keys in c["status_groups"]:
        if status in keys:
            return label
    return str(status or "unknown")


def prompts(c: dict | None = None) -> list[tuple]:
    return [
        ("ask", "How do I report an issue?"),
        ("ask", "Status of my reports"),
        ("ask", "What do the statuses mean?"),
        ("ask", "Where can I see a computer's details?"),
    ]


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

_CTRL_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def _first_name(user: Any) -> str:
    name = user.get("name") if isinstance(user, dict) else None
    parts = str(name or "").split()
    return parts[0] if parts else ""


def _normalize(text: str) -> str:
    """Lowercase, straighten curly quotes, collapse whitespace."""
    text = str(text).lower().replace("’", "'").replace("‘", "'")
    return " ".join(text.split())


@lru_cache(maxsize=512)
def _term_re(term: str) -> re.Pattern:
    # Match at a word *start* so "report" hits "reports" but "map" doesn't hit "bitmap".
    return re.compile(r"(?<![a-z0-9])" + re.escape(term))


def _has(text: str, *terms: str) -> bool:
    return any(_term_re(t).search(text) for t in terms)


def _norm_id(x: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(x).lower())


def _issues(r: dict) -> str:
    v = r.get("issues") or r.get("issue") or []
    v = [v] if isinstance(v, str) else list(v)
    return ", ".join(str(i) for i in v) or "no issue listed"


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
    return (
        f"**{r.get('id', '?')}** - {_where(r)} "
        f"({_issues(r)}), {_status_word(r.get('status'), c)}"
    )


def _clean(value: Any, limit: int = 200) -> str:
    """Make user-supplied text safe and compact before it goes into an AI prompt."""
    text = " ".join(_CTRL_CHARS.sub(" ", str(value)).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _authorized_reports(reports: list[dict] | None, user: dict, c: dict) -> list[dict]:
    """Drop anything that is not a report dict, and apply the optional owner check."""
    items = [r for r in (reports or []) if isinstance(r, dict)]
    check = c.get("report_owner_check")
    if callable(check):
        kept = []
        for r in items:
            try:
                if check(r, user):
                    kept.append(r)
            except Exception:  # noqa: BLE001 - an unreadable record is not shown
                log.exception("report_owner_check failed for one report")
        return kept
    return items


# ---------------------------------------------------------------------------
# Built-in answer engine
#
# _route() returns (reply, suggestions, direct). ``direct`` is True when the
# reply is a complete, reliable answer on its own (built from the verified
# reports or fixed dashboard help), so no AI request is needed.
# ---------------------------------------------------------------------------

_GREETING_WORDS = {
    "hi", "hello", "hey", "hiya", "morning", "afternoon", "evening",
    "kumusta", "kamusta",
}

_STATUS_WORDS = ("status", "progress", "resolved", "follow up", "followup", "follow-up")

_REPORTS_Q = re.compile(
    r"(?<![a-z0-9])("
    r"my reports?|reports? ko|status of|status ng|my status|latest report|pending|any update|"
    r"how many reports?|which (computer|unit|pc)|my (issue|ticket)s?|"
    r"(has|have|is|was|are).{0,25}(fixed|resolved)|fixed yet|"
    r"natapos|naayos|ayos na|track (my|the) report"
    r")"
)

_INVENTORY_Q = re.compile(
    r"(?<![a-z0-9])("
    r"inventory|unit details|unit's details|computer details|computer's details|"
    r"floor map|lab(oratory)? status|specs? of|"
    r"where.{0,20}(see|find|check).{0,25}(computer|unit|pc)"
    r")"
)

_HOWTO_REPORT = re.compile(
    r"((how|paano|pano).{0,25}(report|mag.?report))|report an issue|"
    r"submit.{0,15}report|gumawa ng report"
)

_CONTACT_Q = re.compile(
    r"((contact|phone|mobile) (number|no)\b)|my number|update.{0,20}(contact|profile)|\bprofile\b"
)

_PASSWORD_Q = re.compile(r"forgot.{0,10}password|reset.{0,10}password|nakalimutan.{0,15}password")
_LAB_WORDS = ("computer", "pc", "unit", "lab ", "windows", "workstation")


def _route(
    text: str,
    user: dict,
    reports: list[dict],
    config: dict | None = None,
) -> tuple[str, list[tuple], bool]:
    c = _cfg(config)
    nm = c["names"]
    reports = reports or []

    def go(key: str) -> tuple:
        return ("go", f"Open {nm[key]}", key)

    default_prompts = prompts(c)
    t = _normalize(text)
    tn = _norm_id(t)
    first = _first_name(user)
    n_words = len(t.split())
    more = [("ask", "How do I report an issue?"), ("ask", "Status of my reports")]

    # A specific report the user owns, e.g. "what about CL-1043"
    hit = next(
        (
            r for r in reports
            if len(_norm_id(r.get("id", ""))) >= 3 and _norm_id(r["id"]) in tn
        ),
        None,
    )
    if hit:
        when = f"\nSent {hit['date']}." if hit.get("date") else ""
        return _describe(hit, c) + when, [go("myreports")], True

    # A report number that isn't one of the user's
    m = re.search(r"\bcl[-\s]?(\d{3,5})\b", t)
    if m:
        return (
            f"I couldn't verify **CL-{m.group(1)}** in your reports. "
            f"Open {nm['myreports']} to see everything you've sent.",
            [go("myreports")],
            True,
        )

    words = set(re.findall(r"[a-z']+", t))

    if n_words <= 4 and words & _GREETING_WORDS:
        return (
            f"Hi{' ' + first if first else ''}! What can I help you with?",
            default_prompts,
            True,
        )

    if n_words <= 6 and _has(t, "thank", "salamat"):
        return "You're welcome! Anything else I can help with?", more, True

    if _has(t, "mean", "difference", "ibig sabihin") and _has(t, *_STATUS_WORDS):
        return _fill(c["status_help"], c), [go("myreports")], True

    if _INVENTORY_Q.search(t):
        return _fill(c["inventory_help"], c), [go("inventory")], True

    if _REPORTS_Q.search(t):
        if not reports:
            return (
                "You haven't sent any reports yet. Need to report a problem?",
                [go("report")],
                True,
            )
        resolved_keys = next(
            (keys for label, keys in c["status_groups"] if label == "resolved"),
            {"resolved"},
        )
        open_reports = [r for r in reports if r.get("status") not in resolved_keys]
        counts = ", ".join(
            f"{sum(1 for r in reports if r.get('status') in keys)} {label}"
            for label, keys in c["status_groups"]
        )
        lines = [
            f"You have **{len(reports)}** report{'s' if len(reports) != 1 else ''}: {counts}."
        ]
        if open_reports:
            lines.append("Still open:")
            lines += [f"- {_describe(r, c)}" for r in open_reports[:5]]
            if len(open_reports) > 5:
                lines.append(f"...and {len(open_reports) - 5} more in {nm['myreports']}.")
        else:
            lines.append("All of them are resolved.")
            lines.append(f"Latest: {_describe(reports[0], c)}.")
        return "\n".join(lines), [go("myreports"), ("ask", "What do the statuses mean?")], True

    if c.get("urgent_help") and _has(t, "urgent", "urgency", "emergency", "asap"):
        return _fill(c["urgent_help"], c), [go("report")], True

    if _has(t, "how long", "when will", "how soon", "gaano katagal"):
        return _fill(c["wait_help"], c), [go("myreports")], True

    if _HOWTO_REPORT.search(t):
        return (
            "To report a problem:\n" + _fill(c["report_howto"], c),
            [go("report"), ("ask", "Status of my reports")],
            True,
        )

    if _CONTACT_Q.search(t):
        return _fill(c["contact_help"], c), [go("settings")], True

    if _PASSWORD_Q.search(t) and not any(w in t for w in _LAB_WORDS):
        return _fill(c["password_help"], c), [go("settings")], True

    if _has(t, "log out", "logout", "sign out"):
        return (
            f"You can log out from **{nm['settings']}** or from the menu at the top.",
            [go("settings")],
            True,
        )

    if n_words <= 4 and _has(t, "who are you", "what can you do", "help", "what do you do"):
        return (
            "I'm the Centrum Assistant. I can walk you through reporting a "
            "computer problem, check on the reports you've sent, and point "
            "you to the right page.",
            default_prompts,
            True,
        )

    # Everything below needs the AI (or the offline helper's best guess).
    if _has(
        t, "report", "issue", "problem", "broken", "not working", "won't",
        "wont", "slow", "internet", "keyboard", "mouse", "monitor",
        "turn on", "how do i", "how to",
    ):
        return (
            "To report a problem:\n" + _fill(c["report_howto"], c),
            [go("report"), ("ask", "Status of my reports")],
            False,
        )

    return (
        "I'm a simple helper, so I may have missed that. I can help with "
        "reporting a problem, checking your reports, and finding computer "
        "details. Try one of these:",
        default_prompts,
        False,
    )


def answer(
    text: str,
    user: dict,
    reports: list[dict],
    config: dict | None = None,
) -> tuple[str, list[tuple]]:
    """Rule-based reply. Returns (message, suggestions)."""
    reply, suggest, _direct = _route(text, user, reports, config)
    return reply, suggest


# ---------------------------------------------------------------------------
# AI context (verified data only)
# ---------------------------------------------------------------------------

def _reports_text(reports: list[dict], c: dict) -> str:
    """The signed-in user's reports as plain, prompt-safe lines (newest first)."""
    lines = [
        f"- ID: {_clean(r.get('id', 'Unknown'), 40)} | "
        f"Location: {_clean(_where(r) or 'Unknown', 60)} | "
        f"Issue: {_clean(_issues(r), 120)} | "
        f"Status: {_clean(_status_word(r.get('status'), c), 40)} | "
        f"Date: {_clean(r.get('date', 'Unknown'), 40)}"
        for r in reports[:MAX_PROMPT_REPORTS]
    ]
    if len(reports) > MAX_PROMPT_REPORTS:
        lines.append(f"(+{len(reports) - MAX_PROMPT_REPORTS} older reports not shown)")
    return "\n".join(lines)


def _pages_text(c: dict) -> str:
    nm = c["names"]
    return (
        f"- {nm['report']}: submit a new computer problem report\n"
        f"- {nm['myreports']}: see the teacher's reports and their status\n"
        f"- {nm['inventory']}: laboratory status and per-computer hardware, "
        "software and maintenance history\n"
        f"- {nm['settings']}: contact number and account options"
    )


# ---------------------------------------------------------------------------
# State + callbacks
# ---------------------------------------------------------------------------

def _k(p: str, name: str) -> str:
    return f"{p}_bot_{name}"


def _greeting(user: dict, c: dict) -> dict:
    first = _first_name(user)
    return {
        "role": "bot",
        "suggest": prompts(c),
        "text": (
            f"Hi{' ' + first if first else ''}! I'm the **Centrum Assistant**. "
            "I can help you report a computer problem, check on your reports, "
            "or find your way around."
        ),
    }


def _set_open(p: str, value: bool) -> None:
    st.session_state[_k(p, "open")] = value


def _ask(p: str, text: str, ctx: dict) -> None:
    """
    Callback: store the question and mark it pending. The answer itself is
    produced (and streamed) during the rerun in _run_pending().
    """
    ss = st.session_state
    text = " ".join(_CTRL_CHARS.sub(" ", text or "").split())[:MAX_INPUT_CHARS]
    if not text:
        return                      # empty input
    if ss.get(_k(p, "pending")):
        return                      # an answer is already being written

    msgs: list[dict] = ss[_k(p, "msgs")]
    msgs.append({"role": "me", "text": text})
    del msgs[:-MAX_STORED_MESSAGES]
    ss[_k(p, "pending")] = text
    ss[_k(p, "turn")] = ss.get(_k(p, "turn"), 0) + 1


def _send(p: str, ctx: dict) -> None:
    _ask(p, st.session_state.get(_k(p, "input"), ""), ctx)


def _reset(p: str, ctx: dict) -> None:
    ss = st.session_state
    ss[_k(p, "msgs")] = [_greeting(ctx["user"], ctx["config"])]
    ss[_k(p, "pending")] = None
    ss[_k(p, "turn")] = ss.get(_k(p, "turn"), 0) + 1


def _go(p: str, page: str, ctx: dict) -> None:
    """``page`` is a logical name (report / myreports / inventory / settings)."""
    navigate = ctx.get("navigate")
    if navigate:
        navigate(ctx["config"]["pages"].get(page, page))


# ---------------------------------------------------------------------------
# Producing a reply (a generator, so the UI can stream it)
# ---------------------------------------------------------------------------

def _stream_reply(text: str, prior: list[dict], ctx: dict, out: dict) -> Iterator[str]:
    """
    Yield the reply in pieces. ``out["suggest"]`` is set to the chips to show
    afterwards. ``prior`` is the conversation BEFORE this question.
    """
    # 1. Optional custom AI function supplied by the dashboard
    if ctx.get("external"):
        try:
            reply = ctx["external"](text, prior + [{"role": "me", "text": text}])
            if reply:
                out["suggest"] = _AI_SUGGEST
                yield str(reply)
                return
        except Exception:  # noqa: BLE001
            log.exception("External AI function failed")

    # 2. Direct answers from verified data / fixed dashboard help
    reply, suggest, direct = _route(text, ctx["user"], ctx["reports"], ctx["config"])
    if direct:
        out["suggest"] = suggest
        yield reply
        return

    # 3. Gemini (streamed), grounded in the knowledge base
    user = ctx["user"] if isinstance(ctx["user"], dict) else {}
    produced = False
    try:
        for piece in ai_service.stream_chat(
            text,
            [{"role": m.get("role"), "text": m.get("text", "")} for m in prior[-MAX_PROMPT_HISTORY:]],
            teacher_name=_first_name(user) or "Teacher",
            role=str(user.get("role") or "teacher").lower(),
            reports_text=_reports_text(ctx["reports"], ctx["config"]),
            pages_text=_pages_text(ctx["config"]),
        ):
            produced = True
            yield piece
    except Exception:  # noqa: BLE001 - an AI failure must never break the dashboard
        log.exception("AI request failed")
        if produced:
            out["suggest"] = _AI_SUGGEST
            yield INTERRUPTED_NOTE
            return

    if produced:
        out["suggest"] = _AI_SUGGEST
        return

    # 4. Built-in helper, with a visible notice
    out["suggest"] = suggest
    yield AI_DOWN_NOTICE + reply


def _run_pending(p: str, text: str, ctx: dict, slot) -> None:
    """Stream the answer for the pending question into ``slot``, then finish."""
    ss = st.session_state
    msgs: list[dict] = ss[_k(p, "msgs")]
    prior = msgs[:-1]               # everything before the question itself

    out: dict = {"suggest": None}
    parts: list[str] = []
    last_paint = 0.0

    try:
        for piece in _stream_reply(text, prior, ctx, out):
            parts.append(piece)
            now = time.monotonic()
            if now - last_paint >= PAINT_INTERVAL:
                last_paint = now
                slot.markdown(
                    _bubbles(msgs + [{"role": "bot", "text": "".join(parts) + " ▍"}]),
                    unsafe_allow_html=True,
                )
    except Exception:  # noqa: BLE001
        log.exception("Unexpected error while answering")

    reply = "".join(parts).strip()
    if not reply:
        reply = "Sorry, something went wrong on my side. Please try again in a moment."
        out["suggest"] = prompts(ctx["config"])

    msgs.append({"role": "bot", "text": reply, "suggest": out["suggest"]})
    del msgs[:-MAX_STORED_MESSAGES]
    ss[_k(p, "pending")] = None
    st.rerun()


# ---------------------------------------------------------------------------
# Drawing helpers
# ---------------------------------------------------------------------------

_BOLD = re.compile(r"\*\*(.+?)\*\*")
_CODE = re.compile(r"`([^`\n]+)`")
_ITALIC = re.compile(r"(?<![*\w])[*_](?!\s)([^*_\n]+?)(?<!\s)[*_](?![*\w])")
_BULLET = re.compile(r"^\s*[-*]\s+")


def _fmt(text: str) -> str:
    """Escape HTML first (safe), then apply a small, safe Markdown subset."""
    lines = []
    for raw in str(text).split("\n"):
        indent = min(len(raw) - len(raw.lstrip(" ")), 6)
        line = html.escape(raw.strip())
        line = _BULLET.sub("• ", line)
        line = _CODE.sub(r"<code>\1</code>", line)
        line = _BOLD.sub(r"<b>\1</b>", line)
        line = _ITALIC.sub(r"<i>\1</i>", line)
        lines.append("&nbsp;" * indent + line)
    return "<br>".join(lines)


_TYPING_ROW = (
    '<div class="brow">{av}<div class="bm bot typing" aria-label="Assistant is typing">'
    "<span></span><span></span><span></span></div></div>"
)


def _bubbles(msgs: list[dict], typing: bool = False) -> str:
    rows = []
    for m in msgs:
        body = _fmt(m.get("text", ""))
        if m.get("role") == "me":
            rows.append(f'<div class="brow"><div class="bm me">{body}</div></div>')
        else:
            rows.append(
                f'<div class="brow">{_avatar_html()}<div class="bm bot">{body}</div></div>'
            )
    if typing:
        rows.append(_TYPING_ROW.format(av=_avatar_html()))
    return f'<div class="botscroll"><div class="botmsgs">{"".join(rows)}</div></div>'


_HEADER_HTML = (
    '<div class="bot-head">'
    f'<div class="bot-av">{robot_svg()}</div>'
    "<div>"
    '<div class="bot-name">Centrum Assistant</div>'
    '<div class="bot-sub"><span class="bot-dot"></span>Here to help</div>'
    "</div>"
    "</div>"
)


# ---------------------------------------------------------------------------
# Main render
# ---------------------------------------------------------------------------

def render(
    p: str,
    user: dict,
    reports: list[dict] | None = None,
    *,
    navigate: Callable[[str], None] | None = None,
    external: Callable[[str, list[dict]], str | None] | None = None,
    config: dict | None = None,
) -> None:
    """
    Draw the floating robot button / chat window.

    p         Session-state prefix, e.g. "teacher" (keeps several dashboards separate).
    user      Signed-in user dict (uses "name" and, optionally, "role").
    reports   The signed-in user's OWN reports, newest first, loaded by the
              dashboard from the database. The chatbot never queries other
              users' data and never changes a report.
    navigate  Callback that opens one of the dashboard's real pages.
    external  Optional custom AI function ``(text, messages) -> str | None``.
    config    Dashboard-specific wording and page names (see DEFAULT_CONFIG).
    """
    ss = st.session_state
    cfg = _cfg(config)
    user = user if isinstance(user, dict) else {}

    ss.setdefault(_k(p, "open"), False)
    ss.setdefault(_k(p, "turn"), 0)
    ss.setdefault(_k(p, "pending"), None)
    if _k(p, "msgs") not in ss:
        ss[_k(p, "msgs")] = [_greeting(user, cfg)]

    ctx = {
        "user": user,
        "reports": _authorized_reports(reports, user, cfg),
        "navigate": navigate,
        "external": external,
        "config": cfg,
    }

    st.markdown(_css(p), unsafe_allow_html=True)

    # ----- Closed: just the floating button -----
    if not ss[_k(p, "open")]:
        with st.container(key=_k(p, "fab")):
            st.button(
                "Open assistant",
                key=_k(p, "fab_btn"),
                help="Chat with Centrum Assistant",
                on_click=_set_open,
                args=(p, True),
            )
        return

    # ----- Open: chat panel -----
    msgs: list[dict] = ss[_k(p, "msgs")]
    turn = ss[_k(p, "turn")]
    pending = ss[_k(p, "pending")]

    with st.container(key=_k(p, "panel")):
        st.markdown(_HEADER_HTML, unsafe_allow_html=True)

        with st.container(key=_k(p, "close")):
            st.button(
                "Close chat",
                key=_k(p, "close_btn"),
                icon=":material/close:",
                help="Minimize",
                on_click=_set_open,
                args=(p, False),
            )

        # The message area lives in a slot so a streaming answer can update it.
        slot = st.empty()
        slot.markdown(_bubbles(msgs, typing=bool(pending)), unsafe_allow_html=True)

        # Suggestion chips (hidden while an answer is being written)
        last = msgs[-1] if msgs else None
        suggest = last.get("suggest") if last and last.get("role") == "bot" else None
        show_reset = len(msgs) > 2

        if not pending and (suggest or show_reset):
            with st.container(key=_k(p, "chips")):
                for i, s in enumerate(suggest or []):
                    chip_key = _k(p, f"chip_{turn}_{i}")
                    if s[0] == "ask":
                        st.button(s[1], key=chip_key, on_click=_ask, args=(p, s[1], ctx))
                    else:
                        st.button(f"{s[1]} ›", key=chip_key, on_click=_go, args=(p, s[2], ctx))
                if show_reset:
                    st.button(
                        "↺ New chat",
                        key=_k(p, f"reset_{turn}"),
                        help="Clear this conversation",
                        on_click=_reset,
                        args=(p, ctx),
                    )

        with st.container(key=_k(p, "form_wrap")):
            with st.form(_k(p, "form"), clear_on_submit=True, border=False):
                c1, c2 = st.columns([6, 1], vertical_alignment="center")
                c1.text_input(
                    "Message",
                    key=_k(p, "input"),
                    placeholder="Ask about a computer problem or your reports...",
                    max_chars=MAX_INPUT_CHARS,
                    disabled=bool(pending),
                    label_visibility="collapsed",
                )
                c2.form_submit_button(
                    "Send",
                    icon=":material/send:",
                    disabled=bool(pending),
                    on_click=_send,
                    args=(p, ctx),
                )

        st.markdown(
            '<div class="bot-foot">Automated helper - not a person</div>',
            unsafe_allow_html=True,
        )

        # Write the answer last, so the whole panel is already on screen.
        if pending:
            _run_pending(p, pending, ctx, slot)


# ---------------------------------------------------------------------------
# Stand-alone demo:  streamlit run frontend/chatbot.py
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    st.set_page_config(page_title="Chatbot demo", layout="wide")
    st.title("Dashboard")
    st.caption("Demo page - the robot button is at the bottom right.")

    render(
        "demo",
        {"name": "Alwyna Lopez", "role": "teacher"},
        [
            {"id": "CL-1043", "room": "CL 1", "unit": 3,
             "issues": ["Slow performance"], "status": "progress", "date": "Oct 02, 2026"},
            {"id": "CL-1042", "room": "CL 2", "unit": 7,
             "issues": ["No internet"], "status": "resolved", "date": "Sep 28, 2026"},
            {"id": "CL-1041", "room": "CL 1", "unit": 15,
             "issues": ["Won't turn on"], "status": "followup", "date": "Sep 20, 2026"},
        ],
        navigate=lambda page: st.toast(f"Would open: {page}"),
    )