"""
frontend/portal.py - Computer Laboratory | the shared dashboard shell

The admin, technician and teacher dashboards follow one design (the
centrum-laboratory-*_1.html files share a stylesheet): a navy sidebar, a top
bar with notifications and the user chip, white cards, chips, badges, the live
floor map, charts and pop-up windows. This module draws those shared parts
with Streamlit; admin.py, technician.py and Teacher.py only build their pages.

Display parts use the design's own CSS and markup (frontend/portal_design.py);
every button, field and filter is a real Streamlit widget dressed to match:

    html(markup)            design markup (SVG icons kept)
    btn(label, key, kind)   a button; kind picks the look (primary, ghost, chip...)
    hit(markup, key, cb)    a whole design element made clickable
    box(key, *markers)      a container laid out by CSS markers (card, row, g2...)

A dashboard creates one Shell (its session-state prefix, menu and pages) and
calls shell.frame(...) to draw the sidebar and top bar around its content.
"""

from __future__ import annotations

import math
import re
from contextlib import contextmanager
from datetime import timedelta

import streamlit as st

from frontend import lab_data as D
from frontend import lab_store
from frontend import ui
from frontend.portal_design import ICON, MAP_SVG, PORTAL_CSS, SIDE_LOGO

ss = st.session_state
html, btn, hit, box, h = ui.html, ui.btn, ui.hit, ui.box, ui.h
PER = 25  # default table rows per page (the user can pick 10, 25, 50 or 100)
PER_OPTIONS = (10, 25, 50, 100)
PHONE_RE = re.compile(r"^(?:\+63|0)9\d{9}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
NOTIF_SHOWN = 15  # notifications listed in the notifications window

# The notifications button: a rounded bell with a little clapper and ring marks.
BELL_SVG = (
    '<svg class="nb-ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" '
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<path d="M6.2 10.2a5.8 5.8 0 0 1 11.6 0c0 4 1.3 5.9 2.1 6.8a.6.6 0 0 1-.45 1H4.55a.6.6 0 0 1-.45-1c.8-.9 2.1-2.8 2.1-6.8z"/>'
    '<path d="M10 20.6a2.2 2.2 0 0 0 4 0"/>'
    '<path class="nb-wave" d="M3 7.2a8.6 8.6 0 0 1 2.2-3.6M21 7.2a8.6 8.6 0 0 0-2.2-3.6"/>'
    "</svg>"
)

LEGEND = (
    '<div class="legend"><span><i style="background:var(--ok)"></i>Working</span>'
    '<span><i style="background:var(--rep)"></i>Reported</span>'
    '<span><i style="background:var(--fix)"></i>Under repair</span>'
    '<span><i style="background:var(--esc)"></i>Escalated</span>'
    '<span><i style="background:var(--maint)"></i>Under maintenance</span>'
    '<span><i style="background:#c3cad6"></i>Inactive</span></div>'
)


# ===========================================================================
# Small markup helpers
# ===========================================================================
def ic(name: str, cls: str = "") -> str:
    return (
        f'<svg class="i {cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{ICON.get(name, "")}</svg>'
    )


def badge(status: str) -> str:
    label, cls = D.STATUS.get(status, (status, "b-neutral"))
    return f'<span class="badge {cls}">{h(label)}</span>'


def comp_badge(status: str) -> str:
    label, cls = D.computer_status_label(status)
    return f'<span class="badge {cls}">{h(label)}</span>'


def tone(status: str) -> str:
    """Icon colour for a report or computer status."""
    return {
        "ok": "ic-blue",
        "reported": "ic-amber",
        "repair": "ic-red",
        "escalated": "ic-violet",
        "fixed": "ic-green",
        "maint": "ic-teal",
        "inactive": "ic-blue",
    }.get(status, "ic-blue")


def initials(name: str) -> str:
    words = name.split()
    return (
        (words[0][:2] if len(words) == 1 else words[0][0] + words[-1][0]).upper()
        if words
        else "?"
    )


def first_name(name: str) -> str:
    return (name.split() or ["there"])[0]


def greeting() -> str:
    hour = D.now().hour
    return (
        "Good morning"
        if hour < 12
        else "Good afternoon" if hour < 18 else "Good evening"
    )


def fmt_number(value: str) -> str:
    """'09171234567' -> '0917 123 4567' (anything else is shown as it is)."""
    digits = re.sub(r"[\s\-()]", "", str(value or ""))
    return (
        f"{digits[:4]} {digits[4:7]} {digits[7:]}"
        if re.fullmatch(r"09\d{9}", digits)
        else str(value or "")
    )


def stat(icon_name: str, tone_cls: str, num, label: str) -> str:
    return (
        f'<div class="card stat"><div class="ic {tone_cls}">{ic(icon_name)}</div><div><div class="num">{h(num)}</div>'
        f'<div class="lbl">{h(label)}</div></div></div>'
    )


def stats(*cards: str, cols: int = 4) -> None:
    html(f'<div class="grid g{cols}">' + "".join(cards) + "</div>")


def row(
    icon_name: str,
    tone_cls: str,
    title: str,
    sub: str,
    right: str = "",
    last: bool = False,
    clickable: bool = False,
) -> str:
    """A .row list item (icon, bold title, grey line, optional badge on the right). Text is escaped here."""
    cls = "row" + (" clickable" if clickable else "") + (" last" if last else "")
    return (
        f'<div class="{cls}"><div class="ic {tone_cls}">{ic(icon_name)}</div><div class="main-t"><b>{title}</b>'
        f"<span>{h(sub)}</span></div>{right}</div>"
    )


def empty(text: str, icon_name: str = "check") -> str:
    return f'<div class="empty">{ic(icon_name)}<div>{h(text)}</div></div>'


def report_details(r: dict) -> str:
    """The body of a report's details window (who, when, urgency, technician, progress)."""
    tl = "".join(
        f'<li><b>{D.STATUS[e["s"]][0]}</b> — {h(e["note"])}<span>{D.sent_date_time(e["t"])}</span></li>'
        for e in r["history"]
    )
    # Reports.CreatedAt as stored ("sent"); older reports without it fall back to "created".
    sent = r.get("sent", r["created"])
    reported = D.sent_date_time(sent) + (f" ({D.when(sent)})" if sent else "")
    esc = (
        f'<dt>Escalation note</dt><dd>{h(r["esc_note"])}</dd>'
        if r.get("esc_note")
        else ""
    )
    return (
        f'<div style="display:flex;gap:10px;align-items:center;margin-bottom:4px;padding-right:40px"><h3>{h(r["id"])} · '
        f'{h(r["issue"])}</h3>{badge(r["status"])}</div><div class="m-sub">{D.lab_name(r["lab"])} · {D.pc_name(r["pc"])}</div>'
        f'<dl class="kv"><dt>Reported by</dt><dd>{h(D.by_name(r))}</dd><dt>Reported</dt><dd>{reported}'
        f'</dd><dt>Urgency</dt><dd>{h(r["urgency"])}</dd><dt>Technician</dt>'
        f'<dd>{h(r["tech"] or "Not assigned yet")}</dd><dt>Details</dt><dd>{h(r["desc"] or "—")}</dd>{esc}</dl>'
        f'<h4 style="font-size:14px;margin-bottom:10px">Progress</h4><ul class="timeline">{tl}</ul>'
    )


# ===========================================================================
# How Streamlit's widgets fit into the design
# ===========================================================================
_PC_POS = [
    (int(m.group(1)), int(m.group(2)), float(m.group(3)), float(m.group(4)))
    for m in re.finditer(
        r'data-room="(\d+)" data-pc="(\d+)"[^>]*rotate\([-\d.]+ ([\d.]+) ([\d.]+)\)',
        MAP_SVG,
    )
]

GLUE_CSS = """
[data-testid="stToolbarActions"], [data-testid="stMainMenu"], [data-testid="stAppDeployButton"], [data-testid="stDecoration"],
[data-testid="stStatusWidget"], #MainMenu, footer { display: none !important; }
header[data-testid="stHeader"] { background: transparent !important; height: 0 !important; min-height: 0 !important; }
/* keep Streamlit's "open sidebar" arrow reachable (it is the only way back to the menu on phones) */
[data-testid="stSidebarCollapsedControl"], [data-testid="stExpandSidebarButton"] { position: fixed !important; top: 18px; left: 12px;
  z-index: 999990; display: flex !important; visibility: visible !important; opacity: 1 !important; }
[data-testid="stSidebarCollapsedControl"] button, [data-testid="stExpandSidebarButton"] { background: #fff !important;
  border: 1px solid var(--line) !important; border-radius: 12px !important; color: var(--navy) !important; }
.stApp:has(section[data-testid="stSidebar"][aria-expanded="false"]) .st-key-cl_top { padding-left: 68px; }
.stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"] { background: var(--bg) !important; }
.stApp, .stApp p, .stApp label, .stApp input, .stApp textarea, .stApp li, .stApp [data-baseweb="select"] {
  font-family: 'Open Sans', 'Segoe UI', Roboto, Arial, sans-serif; }
.stApp { color: var(--ink); -webkit-font-smoothing: antialiased; }
[data-testid="stMainBlockContainer"], .block-container { max-width: 100% !important; padding: 0 !important; }
:where([data-testid="stMain"], [data-testid="stSidebar"]) [data-testid="stVerticalBlock"] { gap: 0 !important; }
[data-testid="stMarkdownContainer"]:has(> .clx) { margin: 0 !important; }
[data-testid="stMarkdownContainer"] > .clx { display: block; }
.clx { font-size: 14.5px; line-height: 1.55; }

/* sidebar = .side */
section[data-testid="stSidebar"] { width: 256px !important; min-width: 256px !important; max-width: 256px !important;
  background: var(--navy-2) !important; border-right: 0 !important; }
section[data-testid="stSidebar"] > div { background: var(--navy-2) !important; }
[data-testid="stSidebarHeader"] { height: auto !important; min-height: 0 !important; padding: 10px 12px 0 !important;
  justify-content: flex-end; }
[data-testid="stSidebarHeader"] button { color: #8fa0c4 !important; }
[data-testid="stSidebarContent"] { overflow-x: hidden; }
/* menu scrolls on its own; "Log out" is pinned to the very bottom of the sidebar, whatever its height */
[data-testid="stSidebarUserContent"] { padding: 4px 16px 104px !important; }
.st-key-cl_sidefoot { position: fixed !important; left: 0; bottom: 0; width: 256px !important; z-index: 20;
  padding: 12px 16px 18px; margin: 0 !important; background: var(--navy-2);
  border-top: 1px solid rgba(255,255,255,.08); box-shadow: 0 -12px 24px rgba(15,26,51,.55); }
section[data-testid="stSidebar"][aria-expanded="false"] .st-key-cl_sidefoot { display: none !important; }
.st-key-cl_sidefoot .side-user { display: flex; gap: 10px; align-items: center; padding: 0 12px 10px; color: #8fa0c4;
  font-size: 12px; min-width: 0; }
.st-key-cl_sidefoot .side-user b { display: block; color: #fff; font: 600 13px 'Poppins', sans-serif; white-space: nowrap;
  overflow: hidden; text-overflow: ellipsis; }
.st-key-cl_sidefoot .side-user .avatar { width: 30px; height: 30px; font-size: 11.5px; }
.st-key-cl_nav [class*="st-key-hitwrap_"] { margin-bottom: 2px; }
[class*="st-key-hitwrap_"]:hover .nav-item:not(.active) { background: rgba(255,255,255,.06); color: #fff; }
.st-key-cl_sidefoot [class*="st-key-hitwrap_"]:hover .nav-item { background: rgba(229,72,77,.12); color: #ffb4b4; }

/* top bar = .top (a little taller and wider-spaced than the design, so the bell and profile breathe) */
.st-key-cl_top { position: sticky; top: 0; z-index: 90; min-height: 78px; padding: 0 36px; flex-direction: row !important;
  align-items: center; gap: 14px !important; background: rgba(255,255,255,.94); backdrop-filter: blur(10px);
  border-bottom: 1px solid var(--line); flex-wrap: nowrap; max-width: 100%; box-sizing: border-box; }
.st-key-cl_top > div { width: auto !important; flex: 0 0 auto; }
.st-key-cl_top > div:first-child { flex: 1 1 auto !important; min-width: 0; }
.adm-crumb { font-size: 12.5px; color: var(--faint); }
.adm-title { font: 600 20px 'Poppins', sans-serif; color: var(--navy); margin: 0; white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis; }
.st-key-cl_topright { flex-direction: row !important; align-items: center; gap: 12px !important; flex-wrap: nowrap;
  padding-left: 14px; border-left: 1px solid var(--line); margin-left: 4px; }
.st-key-cl_topright > div { width: auto !important; flex: 0 0 auto; }
.st-key-cl_bell [data-testid="stPopover"] button { position: relative; width: 44px; height: 44px; min-height: 0 !important;
  padding: 0 !important; border-radius: 12px !important; border: 1px solid var(--line) !important; background: #fff !important;
  color: var(--muted) !important; display: grid; place-items: center; overflow: visible !important; }
.st-key-cl_bell [data-testid="stPopover"] button:hover { color: var(--blue) !important; border-color: var(--blue-line) !important; }
.st-key-cl_bell [data-testid="stPopover"] button [data-testid="stIconMaterial"]:not(:first-child),
.st-key-cl_bell [data-testid="stPopover"] button svg:last-child:not(:first-child) { display: none; }
.st-key-cl_bell { width: auto !important; }
.st-key-cl_bell [data-testid="stPopover"] button::after { position: absolute; top: -6px; right: -6px; min-width: 19px; height: 19px;
  padding: 0 5px; border-radius: 999px; background: #e5484d; color: #fff; font: 700 10.5px/19px 'Poppins', sans-serif;
  text-align: center; box-shadow: 0 0 0 2px #fff; box-sizing: border-box; }
[data-testid="stPopoverBody"] { width: 380px; max-width: calc(100vw - 24px); max-height: min(560px, 80vh); overflow-y: auto;
  border-radius: 16px !important; border: 1px solid var(--line) !important;
  box-shadow: 0 20px 50px rgba(20,33,61,.16) !important; padding: 16px 16px 8px !important; }
[data-testid="stPopoverBody"] [data-testid="stVerticalBlock"] { gap: 0 !important; }
.st-key-cl_nhead { flex-direction: row !important; align-items: center; justify-content: space-between; margin-bottom: 10px;
  flex-wrap: nowrap; }
.st-key-cl_nhead > div { width: auto !important; }
.st-key-cl_nchips { margin-bottom: 8px; }
[class*="__nrow__"] { flex-direction: row !important; align-items: center; gap: 4px !important; flex-wrap: nowrap;
  border-bottom: 1px solid var(--line); }
[class*="__nrow__"] > div { width: auto !important; flex: 0 0 auto; }
[class*="__nrow__"] > div:first-child { flex: 1 1 auto !important; min-width: 0; }
[class*="__nrow__"] .row { border-bottom: 0; padding: 10px 4px; }
[class*="__nrow__"] .row .ic { width: 36px; height: 36px; border-radius: 10px; }
[class*="__nrow__"] .row .main-t b { white-space: normal; font-size: 13px; line-height: 1.35; }
.row.unread .main-t b::after { content: ""; display: inline-block; width: 7px; height: 7px; border-radius: 50%;
  background: var(--blue); margin-left: 6px; vertical-align: 2px; }
.row.isread { opacity: .72; }
[class*="__nmark__"] button { padding: 4px 8px !important; min-height: 0 !important; border-radius: 8px !important;
  border: 1px solid var(--line) !important; background: #fff !important; color: var(--muted) !important; font-size: 12px !important; }
[class*="__nmark__"] button:hover { color: var(--blue) !important; border-color: var(--blue-line) !important; }
.nfoot { font-size: 12px; color: var(--faint); text-align: center; padding: 10px 0 4px; }
.st-key-cl_userchip { width: auto !important; }
.user { padding: 5px 14px 5px 5px; gap: 10px; }
.user .avatar { width: 36px; height: 36px; }
.user .user-name { line-height: 1.15; max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.user .user-name small { display: block; font: 500 11.5px 'Open Sans', sans-serif; color: var(--faint); }
[class*="st-key-hitwrap_"]:hover .user { border-color: var(--blue-line); }
.st-key-cl_content { padding: 30px 36px; max-width: 1400px; }

/* layout blocks */
[class*="__card__"] { background: var(--card); border: 1px solid var(--line); border-radius: var(--radius); padding: 22px; min-width: 0; }
[class*="__mt__"] { margin-top: 20px; }
[class*="__g2__"], [class*="__g3__"], [class*="__g4__"], [class*="__gmap__"] { display: grid !important; gap: 20px !important; }
[class*="__g2__"] { grid-template-columns: minmax(0,1fr) minmax(0,1fr); }
[class*="__g3__"] { grid-template-columns: repeat(3, minmax(0,1fr)); }
[class*="__g4__"] { grid-template-columns: repeat(4, minmax(0,1fr)); }
[class*="__gmap__"] { grid-template-columns: minmax(0,1.25fr) minmax(0,1fr); align-items: start; }
[class*="__g2__"] > div, [class*="__g3__"] > div, [class*="__g4__"] > div, [class*="__gmap__"] > div { width: auto !important; min-width: 0; }
[class*="__stack__"] { gap: 20px !important; }
[class*="__cardh__"] { flex-direction: row !important; align-items: center; gap: 12px !important; margin-bottom: 16px; flex-wrap: wrap; }
[class*="__cardh__"] > div { width: auto !important; flex: 0 0 auto; }
[class*="__cardh__"] > div:first-child { flex: 1 1 auto !important; min-width: 0; }
[class*="__row__"], [class*="__rowend__"] { flex-direction: row !important; flex-wrap: wrap; align-items: center; gap: 8px !important; }
[class*="__rowend__"] { justify-content: flex-end; }
[class*="__center__"] { justify-content: center; }
[class*="__row__"] > div, [class*="__rowend__"] > div { width: auto !important; flex: 0 0 auto; }
[class*="__gap6__"] { gap: 6px !important; }
[class*="__spread__"] { flex-wrap: nowrap; }
[class*="__cardh__"] > [class*="__full__"] { flex: 1 1 100% !important; width: 100% !important; }
[class*="__spread__"] > div:first-child { flex: 1 1 auto !important; min-width: 0; }
[class*="__acts__"] { width: 170px !important; flex: 0 0 170px !important; justify-content: flex-end; }
[class*="__cardh__"] .hx3, .card-h .hx3 { font-size: 16px; font-weight: 600; margin: 0; }
[class*="__cardh__"] .sub, .card-h .sub { font-size: 12.5px; color: var(--faint); margin-top: 2px; }
[class*="__gap14__"] { gap: 14px !important; }
[class*="__gap10__"] { gap: 10px !important; }
[class*="__acts250__"] { width: 250px !important; flex: 0 0 250px !important; justify-content: flex-end; flex-wrap: nowrap; }
[class*="__attn__"] { border-bottom: 1px solid var(--line); }
[class*="__attn__"], [class*="__attnlast__"] { align-items: center; }
[class*="__stepacts__"] { flex-direction: row !important; justify-content: space-between; align-items: center; margin-top: 22px;
  gap: 10px !important; flex-wrap: wrap; }
[class*="__stepacts__"] > div { width: auto !important; }
[class*="__pcgrid__"] { display: grid !important; grid-template-columns: repeat(auto-fill, minmax(64px, 1fr)); gap: 8px !important; }
[class*="__labgrid__"] { display: grid !important; grid-template-columns: repeat(var(--cols, 8), minmax(0, 1fr)); gap: 6px !important; }
[class*="__labgrid__"] > div { width: auto !important; min-width: 0; }
[class*="__labgrid__"] .pc-btn { width: 100%; padding: 6px 2px 4px; }
[class*="__labgrid__"] .pc-btn svg { width: 18px; height: 18px; }
[class*="__issuegrid__"] { display: grid !important; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
  gap: 10px !important; margin-bottom: 18px; }
[class*="__pcgrid__"] > div, [class*="__issuegrid__"] > div { width: auto !important; min-width: 0; }
[class*="__pcgrid__"] .pc-btn, [class*="__issuegrid__"] .issue { width: 100%; }
[class*="st-key-hitwrap_"]:hover .pc-btn:not(.on) { border-color: var(--blue-line); background: #f7faff; }
[class*="st-key-hitwrap_"]:hover .issue:not(.on) { border-color: var(--blue-line); }
[class*="__pad0__"] { padding: 0 !important; overflow: hidden; }
[class*="__padh__"] { padding: 18px 22px 0 22px; }
[class*="__mactions__"] { flex-direction: row !important; gap: 10px !important; justify-content: flex-end; margin-top: 8px; flex-wrap: wrap; }
[class*="__mactions__"] > div { width: auto !important; }
[class*="__pager__"] { flex-direction: row !important; align-items: center; justify-content: space-between; margin-top: 18px; padding: 0 22px 18px; }
[class*="__pager__"] > div { width: auto !important; }
[class*="__formgrid__"] { display: grid !important; grid-template-columns: 1fr 1fr; gap: 0 14px !important; }
[class*="__formgrid__"] > div { width: auto !important; min-width: 0; }
[class*="__field__"] { margin-bottom: 14px; }
.adm-label { font: 600 13px 'Poppins', sans-serif; color: var(--navy); margin-bottom: 6px; }
.adm-help { font-size: 12px; color: var(--faint); margin-top: 4px; }
[class*="__trow__"] { flex-direction: row !important; align-items: center; gap: 6px !important; border-bottom: 1px solid var(--line);
  padding: 0 22px 0 0; flex-wrap: nowrap; }
[class*="__trow__"] > div { width: auto !important; flex: 0 0 auto; }
[class*="__trow__"] > div:first-child { flex: 1 1 auto !important; min-width: 0; }
/* whole-element click areas: an invisible button laid over the design element */
[class*="st-key-hitwrap_"] { position: relative; gap: 0 !important; }
[class*="st-key-hit_"] { position: absolute !important; inset: 0; z-index: 4; width: 100% !important; height: 100% !important; margin: 0 !important; }
[class*="st-key-hit_"] .stButton, [class*="st-key-hit_"] button { width: 100% !important; height: 100% !important;
  min-height: 0 !important; padding: 0 !important; opacity: 0 !important; cursor: pointer; }
.tt-head, .tt-row { display: grid; align-items: center; }
.tt-head > div { font: 600 12px 'Poppins', sans-serif; letter-spacing: .03em; color: var(--faint); text-transform: uppercase;
  padding: 10px 14px; border-bottom: 1px solid var(--line); background: #fafbfd; white-space: nowrap; }
.tt-row > div { padding: 13px 14px; font-size: 13.5px; min-width: 0; }
.tt-row { border-bottom: 1px solid var(--line); transition: background .12s; }
.tt-head > div:first-child, .tt-row > div:first-child { padding-left: 22px; }
.tt-head > div:last-child, .tt-row > div:last-child { padding-right: 22px; }
[class*="__trow__"] .tt-row { border-bottom: 0; }
[class*="st-key-hitwrap_"]:hover .tt-row, [class*="__trow__"]:hover { background: #fafbfe; }
.tt-row .strong { font-weight: 600; color: var(--navy); }
.tt-row .small { font-size: 12.5px; color: var(--faint); }
.tt-row .fakebtn { display: inline-flex; border: 1px solid var(--line); border-radius: 10px; padding: 6px 12px;
  font: 600 12.5px 'Poppins', sans-serif; color: var(--navy); background: #fff; }
[class*="st-key-hitwrap_"]:hover .tt-row .fakebtn { border-color: var(--blue-line); color: var(--blue); }
[class*="st-key-hitwrap_"]:hover .lab-tile { border-color: var(--blue-line); box-shadow: var(--shadow); }
[class*="st-key-hitwrap_"]:hover .row { background: #fafbfe; }
[class*="st-key-hitwrap_"] .clx > .row:not(.last) { border-bottom: 1px solid var(--line); }
.row.clickable { cursor: pointer; }

/* live floor map: an invisible button over every computer */
[class*="__mapbox__"] { position: relative; max-width: 560px; width: 100%; margin: 0 auto; }
[class*="__pcdot__"] { position: absolute !important; width: 2.9% !important; height: 2.9% !important; z-index: 5;
  transform: translate(-50%, -50%); margin: 0 !important; }
[class*="__pcdot__"] *, [class*="__pcdot__"] button { width: 100% !important; height: 100% !important; min-height: 0 !important; padding: 0 !important; }
[class*="__pcdot__"] button { opacity: 0 !important; border-radius: 50% !important; cursor: pointer; }
/* live monitoring: Working / Reported / Under repair / Escalated (+ maintenance, inactive) */
:root { --ok: #2fae66; --maint: #0e9f9a; }
.fp .pc.s-none { fill: #e3e8f0; }
.fp .pc.s-ok { fill: var(--ok); }
.fp .pc.s-reported { fill: var(--rep); }
.fp .pc.s-repair { fill: var(--fix); }
.fp .pc.s-escalated { fill: var(--esc); animation: blink 1.6s ease-in-out infinite; }
.fp .pc.s-maint { fill: var(--maint); }
.fp .pc.s-inactive { fill: #c3cad6; }
.pc-btn.s-ok svg { color: var(--ok); }
.pc-btn.s-reported svg { color: var(--rep); }
.pc-btn.s-repair svg { color: var(--fix); }
.pc-btn.s-escalated svg { color: var(--esc); }
.pc-btn.s-maint svg { color: var(--maint); }
.pc-btn.s-inactive { opacity: .55; }
.pc-btn.s-reported { border-color: #f6d59a; } .pc-btn.s-repair { border-color: #f1b9b9; }
.pc-btn.s-escalated { border-color: #cdb8fb; }
.b-maint { background: #dff5f4; color: #0b7a76; }
.ic-teal { background: #dff5f4; color: #0b7a76; }
.lab-grid-h { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; margin: 18px 0 8px; }
.lab-grid-h b { font: 600 14px 'Poppins', sans-serif; color: var(--navy); }
.lab-grid-h span { font-size: 12px; color: var(--faint); }
.lab-ic { width: 42px; height: 42px; flex: none; border-radius: 12px; background: var(--blue-soft); color: var(--blue);
  display: grid; place-items: center; }
.lab-ic svg { width: 22px; height: 22px; }
.stat-mini { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 10px; }
.stat-mini > div { border: 1px solid var(--line); border-radius: 12px; padding: 12px 14px; background: #fff; }
.stat-mini b { display: block; font: 700 22px 'Poppins', sans-serif; color: var(--navy); }
.stat-mini span { font-size: 12.5px; color: var(--faint); }
.stat-mini i { display: inline-block; width: 9px; height: 9px; border-radius: 50%; margin-right: 6px; }
table.t td.num, table.t th.num { text-align: right; }
.form-note { font-size: 12.5px; color: var(--faint); margin: -4px 0 14px; }
.req { color: #b42323; }
.kv dd small { color: var(--faint); font-weight: 400; }
.fp .pc.sel { stroke: var(--navy); stroke-width: 2.5; }
.unplaced { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; justify-content: center; margin-top: 10px; font-size: 12.5px; color: var(--muted); }

/* modal = .modal-bg + .modal */
[class*="__modal__"] { position: fixed !important; top: 50%; left: 50%; transform: translate(-50%, -50%);
  width: min(560px, calc(100vw - 40px)) !important; max-height: 90vh; overflow-y: auto; flex-wrap: nowrap;
  background: #fff; border-radius: 20px; padding: 26px; z-index: 1000020;
  box-shadow: 0 0 0 100vmax rgba(15,26,51,.45), 0 30px 70px rgba(0,0,0,.25); }
[class*="__modalwide__"] { width: min(760px, calc(100vw - 40px)) !important; }
[class*="__modal__"] .hx3 { font-size: 18px; margin: 0 0 4px; padding-right: 36px; }
[class*="__modal__"] .m-sub { color: var(--muted); font-size: 13.5px; margin-bottom: 18px; }
.stApp:has([class*="__modal__"]) [data-testid="stSidebar"] { filter: brightness(.55); pointer-events: none; }
[class*="__x__"] { position: absolute !important; top: 16px; right: 16px; width: auto !important; z-index: 3; }

/* buttons = .btn variants */
.stApp .stButton > button, .stApp .stFormSubmitButton > button { border-radius: 12px; font: 600 14px 'Poppins', sans-serif;
  padding: 11px 18px; min-height: 0; line-height: 1.2; box-shadow: none; white-space: nowrap; transition: background .15s, box-shadow .15s, color .15s; }
.stApp .stButton > button p { font: inherit !important; margin: 0; }
[class*="__primary"] button { background: var(--blue) !important; color: #fff !important; border: 0 !important;
  box-shadow: 0 8px 20px rgba(45,111,227,.25) !important; }
[class*="__primary"] button:hover { background: var(--blue-dk) !important; }
[class*="__primary"] button:disabled { background: #b9c9e6 !important; box-shadow: none !important; }
[class*="__ghost"] button { background: #fff !important; color: var(--navy) !important; border: 1px solid var(--line) !important; }
[class*="__ghost"] button:hover { border-color: var(--blue-line) !important; color: var(--blue) !important; }
[class*="__danger"] button { background: #fff !important; color: #b42323 !important; border: 1px solid #f3c7c7 !important; }
[class*="__danger"] button:hover { background: #fdf0f0 !important; }
[class*="__success"] button { background: var(--done) !important; color: #fff !important; border: 0 !important; }
[class*="__success"] button:hover { background: #0a7535 !important; }
[class*="sm__"] button { padding: 7px 12px !important; font-size: 12.5px !important; border-radius: 10px !important; }
[class*="__w__"], [class*="__w__"] .stButton, [class*="__w__"] button { width: 100% !important; justify-content: center; }
[class*="__link__"] button { background: none !important; border: 0 !important; color: var(--blue) !important; padding: 0 !important;
  font-weight: 600 !important; box-shadow: none !important; }
[class*="__link__"] button:hover { text-decoration: underline; }
[class*="__x__"] button { background: #fff !important; border: 1px solid var(--line) !important; border-radius: 10px !important;
  padding: 4px 9px !important; color: var(--muted) !important; }
[class*="__chip"] button { border: 1px solid var(--line) !important; background: #fff !important; color: var(--muted) !important;
  border-radius: 999px !important; padding: 6px 14px !important; font: 500 13px 'Poppins', sans-serif !important; }
[class*="__chip"] button:hover { border-color: var(--blue-line) !important; color: var(--navy) !important; }
[class*="__chipon__"] button { background: var(--navy) !important; border-color: var(--navy) !important; color: #fff !important; }
[class*="__chips__"] { flex-direction: row !important; flex-wrap: wrap; gap: 8px !important; }
[class*="__chips__"] > div { width: auto !important; }
[class*="__segs__"] { flex-direction: row !important; gap: 2px !important; background: #eef2f8; border-radius: 12px; padding: 3px;
  width: auto !important; }
[class*="__segs__"] > div { width: auto !important; }
[class*="__segb"] button { background: transparent !important; border: 0 !important; color: var(--muted) !important;
  border-radius: 9px !important; padding: 7px 12px !important; font: 500 13px 'Poppins', sans-serif !important; box-shadow: none !important; }
[class*="__segb"] button:hover { color: var(--navy) !important; }
[class*="__segbon__"] button { background: #fff !important; color: var(--navy) !important; box-shadow: 0 1px 3px rgba(20,33,61,.12) !important; }

/* inputs = .search / select.sel / .field */
.stApp [data-baseweb="input"], .stApp [data-baseweb="textarea"], .stApp [data-baseweb="select"] > div {
  border: 1px solid var(--line) !important; border-radius: 12px !important; background: #fff !important; }
.stApp [data-baseweb="input"]:focus-within, .stApp [data-baseweb="textarea"]:focus-within, .stApp [data-baseweb="select"] > div:focus-within {
  border-color: var(--blue) !important; box-shadow: 0 0 0 3px rgba(45,111,227,.15) !important; }
.stApp [data-baseweb="input"] > div, .stApp [data-baseweb="base-input"] { background: transparent !important; }
.stApp input, .stApp textarea, .stApp [data-baseweb="select"] { font-size: 14px !important; color: var(--ink) !important; }
[class*="__search__"] { min-width: 260px; flex: 1 1 260px !important; }
[class*="__search__"] input { padding-left: 36px !important; background: url("__SEARCH_BG__") no-repeat 12px center !important; }
[class*="__sel__"] { min-width: 150px; }
[class*="__selwide__"] { min-width: 200px; }
.stApp [data-testid="stWidgetLabel"] p { font: 600 13px 'Poppins', sans-serif !important; color: var(--navy); }
.stApp [data-baseweb="tag"] { background: var(--blue-soft) !important; color: var(--blue) !important; border-radius: 999px !important; }

/* ---------------------------------------------------------------------------
   Light mode everywhere. Streamlit follows the computer's dark mode for its own
   widgets (text boxes, dropdowns, calendars, pop-ups) even though the design is
   light - these rules keep every box, card and container light.
   (.streamlit/config.toml also sets base = "light".)
--------------------------------------------------------------------------- */
:root, .stApp { color-scheme: light; }
.stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"], [data-testid="stBottom"],
[data-testid="stBottomBlockContainer"] { background: var(--bg) !important; color: var(--ink) !important; }
[data-testid="stMain"] [data-testid="stMarkdownContainer"], [data-testid="stMain"] [data-testid="stWidgetLabel"],
[data-testid="stMain"] [data-testid="stWidgetLabel"] p, [data-testid="stMain"] [data-testid="stCaptionContainer"],
[data-testid="stMain"] [data-testid="stCheckbox"] label p, [data-testid="stMain"] .stRadio label p,
[data-testid="stPopoverBody"] [data-testid="stMarkdownContainer"] { color: var(--ink); }
.stApp [data-baseweb="input"], .stApp [data-baseweb="base-input"], .stApp [data-baseweb="textarea"],
.stApp [data-baseweb="select"] > div, .stApp [data-testid="stNumberInputContainer"],
.stApp [data-testid="stDateInput"] [data-baseweb="input"] { background-color: #fff !important; }
.stApp input, .stApp textarea { background-color: #fff !important; color: var(--ink) !important;
  -webkit-text-fill-color: var(--ink) !important; caret-color: var(--ink); }
.stApp input::placeholder, .stApp textarea::placeholder { color: var(--faint) !important;
  -webkit-text-fill-color: var(--faint) !important; opacity: 1; }
.stApp input:disabled, .stApp textarea:disabled { background-color: #f6f7fa !important; }
.stApp [data-baseweb="select"] div, .stApp [data-baseweb="select"] span { color: var(--ink); }
.stApp [data-baseweb="select"] svg, .stApp [data-baseweb="input"] svg { color: var(--muted); fill: currentColor; }
.stApp [data-baseweb="tag"] span { color: var(--blue) !important; }
.stApp [data-testid="stNumberInputStepDown"], .stApp [data-testid="stNumberInputStepUp"] {
  background: #f3f5f9 !important; color: var(--navy) !important; border: 0 !important; }
.stApp [data-testid="stNumberInputStepDown"]:hover, .stApp [data-testid="stNumberInputStepUp"]:hover {
  background: var(--blue-soft) !important; color: var(--blue) !important; }
/* dropdown lists, menus, calendars and pop-overs are drawn outside .stApp */
[data-baseweb="popover"] > div, [data-baseweb="popover"] [data-baseweb="menu"], [data-baseweb="popover"] ul,
[data-baseweb="popover"] [role="listbox"], [data-baseweb="calendar"], [data-baseweb="datepicker"] {
  background-color: #fff !important; color: var(--ink) !important; }
[data-baseweb="popover"] li, [data-baseweb="popover"] [role="option"] { background-color: #fff; color: var(--ink) !important; }
[data-baseweb="popover"] li:hover, [data-baseweb="popover"] [role="option"]:hover,
[data-baseweb="popover"] [aria-selected="true"][role="option"] { background-color: #eef3fd !important; }
[data-baseweb="calendar"] div, [data-baseweb="calendar"] button { background-color: transparent; color: var(--ink); }
[data-baseweb="calendar"] [role="gridcell"][aria-selected="true"] div { color: #fff !important; }
[data-baseweb="calendar"] svg { color: var(--navy); fill: currentColor; }
[data-testid="stPopoverBody"], [data-testid="stPopoverBody"] > div { background-color: #fff !important; color: var(--ink) !important; }
/* checkboxes: light box, blue when ticked */
.stApp label[data-baseweb="checkbox"] > span:first-of-type { background-color: #fff !important;
  border: 1.5px solid #c3cad6 !important; border-radius: 6px !important; }
.stApp label[data-baseweb="checkbox"]:has(input:checked) > span:first-of-type {
  background-color: var(--blue) !important; border-color: var(--blue) !important; }
/* any Streamlit button without one of the design looks */
.stApp .stButton > button, .stApp .stDownloadButton > button { background: #fff; color: var(--navy); border: 1px solid var(--line); }
.stApp [data-testid="stExpander"] details, .stApp [data-testid="stExpander"] summary { background: #fff; color: var(--ink); }
.stApp [data-testid="stVerticalBlockBorderWrapper"] { background: transparent; }
.stApp [data-testid="stAlert"] { color: var(--ink); }
.stApp [data-testid="stSpinner"] { color: var(--muted); }
.stApp iframe { background: #fff; border-radius: 12px; }
.stApp code { background: #eef1f6; color: var(--navy); }

/* ---------------------------------------------------------------------------
   Tables fit inside their cards
--------------------------------------------------------------------------- */
[class*="__pad0__"] { overflow-x: auto !important; overflow-y: hidden; }
[class*="__card__"]:not([class*="__pad0__"]) .table-wrap { margin-left: 0 !important; margin-right: 0 !important;
  margin-bottom: 0 !important; }
.table-wrap { max-width: 100%; overflow-x: auto; }
table.t { table-layout: auto; }
.t th { padding: 10px 12px; white-space: normal; line-height: 1.3; vertical-align: bottom; }
.t td { padding: 10px 12px; overflow-wrap: anywhere; }
.t th:first-child, .t td:first-child { padding-left: 18px; }
.t th:last-child, .t td:last-child { padding-right: 18px; }
.tt-head > div { white-space: normal !important; line-height: 1.3; padding: 10px 10px !important;
  overflow-wrap: anywhere; align-self: stretch; }
.tt-row > div { padding: 11px 10px !important; overflow-wrap: anywhere; }
.tt-head > div:first-child, .tt-row > div:first-child { padding-left: 18px !important; }
.tt-head > div:last-child, .tt-row > div:last-child { padding-right: 18px !important; }
[class*="__trow__"] .tt-row > div:last-child { padding-right: 10px !important; }
[class*="__padh__"] { padding: 16px 18px 0 18px; }
[class*="__pager__"] { padding: 0 18px 16px; margin-top: 14px; flex-wrap: wrap; gap: 10px !important; }
[class*="__perpage__"] { width: 92px !important; min-width: 92px !important; flex: 0 0 92px !important; }
[class*="__perpage__"] [data-baseweb="select"] > div { min-height: 34px; }

/* ---------------------------------------------------------------------------
   Notifications button (opens the notifications window)
--------------------------------------------------------------------------- */
.st-key-cl_bell { width: auto !important; }
.nbtn { position: relative; width: 44px; height: 44px; border-radius: 14px; border: 1px solid var(--line);
  background: var(--card); color: var(--muted); display: grid; place-items: center;
  transition: color .15s, border-color .15s, background .15s, transform .1s; }
.nbtn .nb-ic { width: 22px; height: 22px; transform-origin: 50% 15%; }
.nbtn .nb-wave { opacity: 0; transition: opacity .2s; }
.nbtn.has { color: var(--blue); border-color: var(--blue-line); }
.nbtn.has .nb-wave { opacity: .85; }
.nbtn.has .nb-ic { animation: nb-ring 1s ease .6s 2; }
.nb-count { position: absolute; top: -6px; right: -6px; min-width: 19px; height: 19px; padding: 0 5px; border-radius: 999px;
  background: #e5484d; color: #fff; font: 700 10.5px/19px 'Poppins', sans-serif; text-align: center;
  box-shadow: 0 0 0 2px var(--card); }
[class*="st-key-hitwrap_"]:hover .nbtn { color: var(--blue); border-color: var(--blue-line); background: var(--blue-soft); }
[class*="st-key-hitwrap_"]:hover .nbtn .nb-ic { animation: nb-ring .7s ease; }
[class*="st-key-hitwrap_"]:active .nbtn { transform: scale(.94); }
@keyframes nb-ring { 0%, 100% { transform: rotate(0); } 20% { transform: rotate(14deg); } 40% { transform: rotate(-12deg); }
  60% { transform: rotate(7deg); } 80% { transform: rotate(-4deg); } }
[class*="__nlist__"] { max-height: 56vh; overflow-y: auto; margin-top: 4px; }
.st-key-cl_nhead { flex-direction: row !important; align-items: center; justify-content: space-between; margin: 0 40px 12px 0;
  flex-wrap: nowrap; }
.st-key-cl_nhead > div { width: auto !important; }

/* ---------------------------------------------------------------------------
   Pressed / keyboard focus / selected states (light and dark)
--------------------------------------------------------------------------- */
.stApp .stButton > button:hover, .stApp .stDownloadButton > button:hover { border-color: var(--blue-line); color: var(--blue); }
.stApp .stButton > button:active, .stApp .stDownloadButton > button:active { transform: translateY(1px); }
.stApp .stButton > button:focus:not(:focus-visible) { outline: none; }
.stApp .stButton > button:focus-visible, .stApp .stDownloadButton > button:focus-visible,
.stApp .stFormSubmitButton > button:focus-visible { outline: 2px solid var(--blue) !important; outline-offset: 2px !important; }
[class*="st-key-hitwrap_"]:has(button:focus-visible) { outline: 2px solid var(--blue); outline-offset: 2px; border-radius: 14px; }
[class*="st-key-hitwrap_"]:active .row, [class*="st-key-hitwrap_"]:active .tt-row, [class*="st-key-hitwrap_"]:active .lab-tile,
[class*="st-key-hitwrap_"]:active .pc-btn, [class*="st-key-hitwrap_"]:active .issue, [class*="st-key-hitwrap_"]:active .user {
  filter: brightness(.97); transform: scale(.995); }
[class*="st-key-hitwrap_"]:active .nav-item { filter: brightness(1.1); }
.stApp [data-baseweb="tab-list"] button { color: var(--muted) !important; background: transparent !important; }
.stApp [data-baseweb="tab-list"] button:hover { color: var(--navy) !important; }
.stApp [data-baseweb="tab-list"] button[aria-selected="true"] { color: var(--blue) !important; }
.stApp [data-baseweb="tab-list"] button p { color: inherit !important; }
.stApp [data-baseweb="tab-highlight"] { background-color: var(--blue) !important; }
.stApp [data-baseweb="tab-border"] { background-color: var(--line) !important; }
.stApp [data-baseweb="select"] > div:focus-within, .stApp [data-baseweb="input"]:focus-within,
.stApp [data-baseweb="textarea"]:focus-within { border-color: var(--blue) !important; }

/* ---------------------------------------------------------------------------
   Buttons: one consistent system (height, padding, radius, readable text)
--------------------------------------------------------------------------- */
/* The label inside a Streamlit button sits in a markdown container; it must take
   the button's own colour (this is what made e.g. the selected "All · 14" chip
   unreadable: dark text on the navy background). */
.stApp button [data-testid="stMarkdownContainer"], .stApp button [data-testid="stMarkdownContainer"] p,
.stApp button p, .stApp button span:not([data-testid="stIconMaterial"]) { color: inherit !important; }
.stApp button [data-testid="stIconMaterial"] { color: inherit !important; font-size: 18px; }
.stApp :is([class*="__primary"], [class*="__ghost"], [class*="__danger"], [class*="__success"]) button {
  height: 40px; min-height: 40px !important; padding: 0 18px !important; border-radius: 12px !important;
  display: inline-flex; align-items: center; justify-content: center; gap: 6px; line-height: 1 !important;
  font: 600 14px 'Poppins', sans-serif !important; white-space: nowrap; }
.stApp :is([class*="__primarysm"], [class*="__ghostsm"], [class*="__dangersm"], [class*="__successsm"]) button {
  height: 36px; min-height: 36px !important; padding: 0 14px !important; border-radius: 10px !important;
  font-size: 13px !important; }
.stApp [class*="__chip"] button {
  height: 36px; min-height: 36px !important; padding: 0 16px !important; border-radius: 999px !important;
  font: 500 13px 'Poppins', sans-serif !important; display: inline-flex; align-items: center; white-space: nowrap; }
[class*="__chip__"] button:hover { background: #f4f7fd !important; border-color: var(--blue-line) !important; color: var(--navy) !important; }
[class*="__chipon__"] button, [class*="__chipon__"] button:hover, [class*="__chipon__"] button:focus,
[class*="__chipon__"] button:active { background: var(--navy) !important; border-color: var(--navy) !important;
  color: #fff !important; }
.stApp [class*="__segb"] button { height: 34px; min-height: 34px !important; padding: 0 14px !important;
  border-radius: 9px !important; }
[class*="__ghost"] button:active, [class*="__chip__"] button:active { background: #eef3fd !important; }
[class*="__primary"] button:active { background: var(--blue-dk) !important; color: #fff !important; }
[class*="__primary"] button:focus, [class*="__primary"] button:focus:not(:active) { color: #fff !important; }
[class*="__success"] button:focus, [class*="__success"] button:active { color: #fff !important; }
[class*="__danger"] button:active { background: #fbe4e4 !important; color: #b42323 !important; }
/* inputs and selects in the filter bars are 40px, like the buttons next to them */
.st-key-cl_content [data-baseweb="input"], .st-key-cl_content [data-baseweb="select"] > div { min-height: 40px; }
/* filter / control bars: everything vertically centred, even gaps */
[class*="__rowend__"], [class*="__row__"] { align-items: center !important; }
[class*="__cardh__"] > [class*="__row__"], [class*="__cardh__"] > [class*="__rowend__"] { gap: 8px !important; }
[class*="__chips__"] { gap: 8px !important; align-items: center; }
[class*="__mactions__"] { margin-top: 18px; padding-top: 16px; border-top: 1px solid var(--line); align-items: center; }

/* ---------------------------------------------------------------------------
   Table rows are as tall as their content (they were being stretched to fill
   the card, which left big empty bands above and below every row)
--------------------------------------------------------------------------- */
.stApp [class*="__trow__"], .stApp [class*="st-key-hitwrap_"] { flex: 0 0 auto !important; height: auto !important;
  min-height: 0 !important; }
.stApp [class*="__trow__"] > div, .stApp [class*="__trow__"] [data-testid="stElementContainer"],
.stApp [class*="__trow__"] [data-testid="stVerticalBlock"], .stApp [class*="__trow__"] [data-testid="stLayoutWrapper"] {
  height: auto !important; min-height: 0 !important; }
.stApp [class*="__trow__"] { align-items: center !important; padding-top: 0 !important; padding-bottom: 0 !important; }
.stApp [class*="__pad0__"] > [data-testid="stElementContainer"], .stApp [class*="__pad0__"] > [data-testid="stLayoutWrapper"],
.stApp [class*="__pad0__"] > [data-testid="stVerticalBlock"] { flex-grow: 0 !important; }
.tt-row > div { padding-top: 10px !important; padding-bottom: 10px !important; }

/* ---------------------------------------------------------------------------
   Three-dot (⋮) row menus (Users, Reports)
--------------------------------------------------------------------------- */
[class*="__kebab__"] { width: 44px !important; flex: 0 0 44px !important; justify-content: flex-end; }
[class*="__kebab__"] [data-testid="stPopover"] > div > button, [class*="__kebab__"] [data-testid="stPopover"] button {
  width: 36px !important; height: 36px !important; min-height: 36px !important; padding: 0 !important;
  border-radius: 10px !important; border: 1px solid var(--line) !important; background: #fff !important;
  color: var(--navy) !important; font: 700 18px/1 'Poppins', sans-serif !important; display: grid; place-items: center; }
[class*="__kebab__"] [data-testid="stPopover"] button:hover { border-color: var(--blue-line) !important; color: var(--blue) !important;
  background: #f4f7fd !important; }
[class*="__kebab__"] [data-testid="stPopover"] button [data-testid="stIconMaterial"]:not(:first-child),
[class*="__kebab__"] [data-testid="stPopover"] button svg:last-child:not(:first-child),
[class*="__kebab__"] [data-testid="stPopover"] button > div > div:last-child:not(:first-child) { display: none !important; }
[data-testid="stPopoverBody"]:has([class*="__umenu__"]) { width: 220px !important; min-width: 220px; padding: 6px !important;
  border-radius: 12px !important; }
[class*="__umenu__"] { gap: 2px !important; }
[class*="__menuitem"] button, [class*="__menuitem"] .stButton { width: 100% !important; }
[class*="__menuitem"] button { justify-content: flex-start !important; background: transparent !important; border: 0 !important;
  box-shadow: none !important; height: 38px !important; min-height: 38px !important; padding: 0 12px !important;
  border-radius: 8px !important; font: 500 13.5px 'Poppins', sans-serif !important; color: var(--navy) !important; }
[class*="__menuitem__"] button:hover { background: #f1f5fd !important; color: var(--blue) !important; }
[class*="__menuitemdanger__"] button { color: #b42323 !important; }
[class*="__menuitemdanger__"] button:hover { background: #fdf0f0 !important; color: #b42323 !important; }
[class*="__menuitemok__"] button { color: var(--done) !important; }
[class*="__menuitemok__"] button:hover { background: #e9f6ee !important; }
.acct-dates { display: grid; grid-template-columns: auto 1fr; gap: 2px 10px; font-size: 12.5px; line-height: 1.45; }
.acct-dates dt { color: var(--faint); white-space: nowrap; }
.acct-dates dd { margin: 0; color: var(--ink); font-weight: 500; white-space: nowrap; }

/* ---------------------------------------------------------------------------
   Change password card
--------------------------------------------------------------------------- */
[class*="__pwgrid__"] { display: grid !important; grid-template-columns: minmax(0, 1fr) 280px; gap: 28px !important;
  align-items: start; }
[class*="__pwgrid__"] > div { width: auto !important; min-width: 0; }
@media (max-width: 880px) { [class*="__pwgrid__"] { grid-template-columns: minmax(0, 1fr); } }
.pw-rules { background: #f7f9fc; border: 1px solid var(--line); border-radius: 14px; padding: 16px 18px; }
.pw-rules h4 { font: 600 13.5px 'Poppins', sans-serif; color: var(--navy); margin: 0 0 10px; }
.pw-rules ul { list-style: none; margin: 0; padding: 0; display: grid; gap: 7px; }
.pw-rules li { display: flex; gap: 9px; align-items: center; font-size: 13px; color: var(--muted); }
.pw-rules li i { width: 18px; height: 18px; border-radius: 50%; border: 1.5px solid #c3cad6; flex: none; display: grid;
  place-items: center; font-style: normal; font-size: 11px; color: transparent; }
.pw-rules li.ok { color: var(--done); }
.pw-rules li.ok i { background: var(--done); border-color: var(--done); color: #fff; }
.pw-err { color: #b42323; font-size: 12.5px; margin: -8px 0 12px; display: flex; gap: 6px; align-items: center; }
.pw-msg { display: flex; gap: 10px; align-items: flex-start; border-radius: 12px; padding: 11px 14px; font-size: 13.5px;
  margin-bottom: 16px; }
.pw-msg.ok { background: #e9f6ee; border: 1px solid #b9e3c8; color: #0b6b31; }
.pw-msg.err { background: #fdf0f0; border: 1px solid #f3c7c7; color: #9f1d1d; }
[class*="__pwfields__"] [data-testid="stTextInput"] { margin-bottom: 14px; }
[class*="__pwfields__"] [data-testid="stTextInputRootElement"] button { color: var(--muted) !important; }

/* toast = .toast */
[data-testid="stToast"] { background: var(--navy) !important; border-radius: 12px !important; box-shadow: 0 12px 30px rgba(0,0,0,.2) !important; }
[data-testid="stToast"], [data-testid="stToast"] p, [data-testid="stToast"] button { color: #fff !important; font-size: 13.5px; }

@media (max-width: 1180px) {
  [class*="__g4__"] { grid-template-columns: repeat(2, minmax(0,1fr)); }
  [class*="__gmap__"], [class*="__g2__"] { grid-template-columns: minmax(0,1fr); }
}
@media (max-width: 880px) {
  [class*="__labgrid__"] { grid-template-columns: repeat(5, minmax(0, 1fr)); }
  .st-key-cl_content { padding: 18px 16px; }
  .st-key-cl_top { padding: 0 16px 0 68px; min-height: 68px; gap: 10px !important; }
  .st-key-cl_topright { gap: 8px !important; padding-left: 10px; }
  [class*="__g3__"], [class*="__formgrid__"] { grid-template-columns: minmax(0,1fr); }
  .adm-crumb, .user .user-name, .sample-tag { display: none; }
  .user { padding: 3px; }
  .tt-hide-sm { display: none !important; }
  /* wide tables scroll sideways instead of squashing */
  [class*="__pad0__"] { overflow-x: auto !important; }
  .tt-head, .tt-row { min-width: 720px; }
  [class*="__trow__"] { min-width: 980px; }
  [class*="__cardh__"] { flex-wrap: wrap; }
  [class*="__search__"], [class*="__sel__"], [class*="__selwide__"] { min-width: 0; width: 100% !important; }
  [class*="__rowend__"] > div { flex: 1 1 160px; }
  [class*="__modal__"] { padding: 20px; border-radius: 16px; }
  .kv { grid-template-columns: 110px 1fr; }
}
@media (max-width: 520px) {
  [class*="__g4__"] { grid-template-columns: minmax(0,1fr); }
  .adm-title { font-size: 17px; }
  .st-key-cl_bell [data-testid="stPopover"] button { width: 40px; height: 40px; }
  .stat .num { font-size: 22px; }
}
""".replace(
    "__SEARCH_BG__",
    "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='16' height='16' "
    "viewBox='0 0 24 24' fill='none' stroke='%238b93a1' stroke-width='2' stroke-linecap='round'><circle cx='11' "
    "cy='11' r='7'/><path d='m20 20-3.5-3.5'/></svg>",
)

_CSS_CACHE: list[str] = []


def css() -> str:
    if not _CSS_CACHE:
        pos = "".join(
            f'[class*="_{lab}_{pc}__pcdot__"]{{left:{(cx + 6) / 612 * 100:.2f}%;top:{(cy + 6) / 612 * 100:.2f}%;}}'
            for lab, pc, cx, cy in _PC_POS
        )
        _CSS_CACHE.append(ui.scope_css(PORTAL_CSS + GLUE_CSS) + pos)
    return _CSS_CACHE[0]


# ===========================================================================
# Widgets used on several pages
# ===========================================================================
def sort_select(key: str, options: dict) -> str:
    """A 'Sort by' dropdown that keeps its value while the page is hidden."""
    k = ui.sticky(key, list(options))
    value = st.selectbox(
        "Sort by",
        list(options),
        format_func=options.get,
        key=k,
        label_visibility="collapsed",
    )
    ui.remember(k)
    return value


def _set(key: str, value) -> None:
    ss[key] = value


def per_page(key: str) -> int:
    """Rows per page chosen for the table whose page number is ss[key] (default PER)."""
    wkey = f"{key}_per__perpage__"
    value = ss[wkey] if wkey in ss else ss.get(f"_keep_{wkey}", PER)
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = PER
    return value if value in PER_OPTIONS else PER


def pager(key: str, page: int, total: int, per: int | None = None) -> None:
    """Shown rows, a "Rows per page" picker (10 / 25 / 50 / 100) and Previous / Next."""
    per = per or per_page(key)
    pages = max(1, -(-total // per))
    with box(f"{key}_pager", "pager"):
        shown = (
            f"{page * per + 1}–{min(total, (page + 1) * per)} of {total}"
            if total
            else "0 items"
        )
        html(f'<span class="muted" style="font-size:13px">{shown}</span>')
        with box(f"{key}_pager_btns", "row"):
            html('<span class="muted" style="font-size:13px">Rows per page</span>')
            sel_key = ui.sticky(f"{key}_per__perpage__", list(PER_OPTIONS))
            if sel_key not in ss:
                ss[sel_key] = per
            st.selectbox(
                "Rows per page",
                list(PER_OPTIONS),
                key=sel_key,
                label_visibility="collapsed",
                on_change=_set,
                args=(key, 0),
            )
            ui.remember(sel_key)
            btn(
                "Previous",
                f"{key}_prev",
                "ghostsm",
                disabled=page <= 0,
                on_click=_set,
                args=(key, page - 1),
            )
            btn(
                "Next",
                f"{key}_next",
                "ghostsm",
                disabled=page >= pages - 1,
                on_click=_set,
                args=(key, page + 1),
            )


def page_slice(rows: list, key: str, per: int | None = None) -> tuple[list, int]:
    per = per or per_page(key)
    page = max(0, min(ss.get(key, 0), max(0, (len(rows) - 1) // per)))
    return rows[page * per : (page + 1) * per], page


def field(
    label: str,
    key: str,
    placeholder: str = "",
    kind: str = "text",
    help_text: str = "",
    required: bool = False,
    options: list | None = None,
    max_chars: int | None = None,
) -> None:
    """A labelled input. kind: text, area or select (with options). required adds a red *."""
    with box(f"{key}_wrap", "field"):
        html(
            f'<div class="adm-label">{h(label)}'
            + (' <span class="req">*</span>' if required else "")
            + "</div>"
        )
        if kind == "area":
            st.text_area(
                label,
                key=key,
                placeholder=placeholder,
                label_visibility="collapsed",
                max_chars=max_chars,
            )
        elif kind == "select":
            opts = list(options or [])
            if ss.get(key) not in opts and opts:
                ss[key] = opts[0]
            st.selectbox(label, opts, key=key, label_visibility="collapsed")
        else:
            st.text_input(
                label,
                key=key,
                placeholder=placeholder,
                label_visibility="collapsed",
                max_chars=max_chars,
            )
        if help_text:
            html(f'<div class="adm-help">{h(help_text)}</div>')


def chart_table(rows, head) -> str:
    body = "".join(f"<tr><td>{h(label)}</td><td>{v}</td></tr>" for label, _, v in rows)
    return (
        f'<details class="chart-table"><summary class="link" style="font-size:12.5px">Show as table</summary>'
        f"<table><tr><th>{head[0]}</th><th>{head[1]}</th></tr>{body}</table></details>"
    )


def bars_v(rows: list[tuple], unit: str, head: tuple) -> str:
    """Column chart; rows are (label, short label, value)."""
    top = max([v for _, _, v in rows] + [1])
    cols = "".join(
        f'<div class="col" title="{h(label)}: {v} {unit}"><span class="val">{v}</span>'
        f'<div class="b" style="height:{v / top * 82:.1f}%"></div></div>'
        for label, _, v in rows
    )
    xs = "".join(f"<span>{h(short)}</span>" for _, short, _ in rows)
    return (
        f'<div class="chart"><div class="bars-v">{cols}</div><div class="bars-x">{xs}</div></div>'
        + chart_table(rows, head)
    )


def bars_h(rows: list[tuple], unit: str, head: tuple) -> str:
    """Bar chart; rows are (label, short label, value)."""
    top = max([v for _, _, v in rows] + [1])
    body = "".join(
        f'<div class="r" title="{h(label)}: {v} {unit}"><span>{h(label)}</span><div class="track">'
        f'<div class="fill" style="width:{v / top * 100:.1f}%"></div></div><b>{v}</b></div>'
        for label, _, v in rows
    )
    return f'<div class="bars-h">{body}</div>' + chart_table(rows, head)


# ===========================================================================
# Live floor map + laboratory tiles
# ===========================================================================
def map_svg(
    s: dict, ctx: str, focus: int | None = None, sel: tuple | None = None
) -> str:
    def paint(m):
        lab, pc = int(m.group(1)), int(m.group(2))
        st_ = D.pc_status(s, lab, pc) if (lab, pc) in s["computers"] else "none"
        cls = f"pc s-{st_}" + (" sel" if sel == (lab, pc) else "")
        return f'<rect class="{cls}" data-room="{lab}" data-pc="{pc}"'

    svg = re.sub(
        r'<rect class="pc" data-room="(\d+)" data-pc="(\d+)"',
        paint,
        MAP_SVG.replace("__P__", f"{ctx}_"),
    )
    if focus:
        svg = svg.replace('class="fp"', 'class="fp focus"', 1)
        svg = svg.replace(
            f'class="fp-pcs" data-room="{focus}"',
            f'class="fp-pcs on" data-room="{focus}"',
        )
        svg = svg.replace(
            f'class="fp-room" data-room="{focus}"',
            f'class="fp-room on" data-room="{focus}"',
        )
    return svg


def pc_tip(s: dict, lab: int, pc: int) -> str:
    r = D.pc_report(s, lab, pc)
    comp = s["computers"].get((lab, pc))
    name = f" ({comp['name']})" if comp and comp["name"] != comp["tag"] else ""
    head = f"{D.lab_name(lab)} · {D.pc_name(pc)}{name}"
    if r:
        return f"{head} — {D.STATUS[r['status']][0]}: {r['issue']}, {D.when(r['created'])}"
    return f"{head} — {D.computer_status_label(D.pc_status(s, lab, pc))[0]}"


def lab_grid(p: str, s: dict, ctx: str, lab: int, on_pc, sel: tuple | None = None) -> None:
    """A laboratory that is not on the round floor plan, drawn as rows of seats
    (Inventory -> Add laboratory sets how many seats per row)."""
    comps = D.lab_computers(s, lab)
    info = D.LAB_INFO.get(lab) or {}
    try:
        cols = max(2, min(12, int(info.get("cols") or 8)))
    except (TypeError, ValueError):
        cols = 8
    sm = D.lab_summary(s, lab)
    where = " · ".join(str(x) for x in (info.get("building") or info.get("wing"),
                                        f"Floor {info['floor']}" if info.get("floor") else "",
                                        info.get("room") if info.get("room") != info.get("name") else "") if x)
    html(
        f'<div class="lab-grid-h"><b>{h(D.lab_name(lab))}</b><span>{h(where)}'
        f'{" · " if where else ""}{sm["ok"]} of {sm["total"]} working</span></div>'
    )
    if not comps:
        html('<div class="empty" style="padding:14px">No computers registered in this laboratory yet.</div>')
        return
    html(f'<style>[class*="{p}_lgrid_{ctx}_{lab}__labgrid__"]{{--cols:{cols}}}</style>')
    with box(f"{p}_lgrid_{ctx}_{lab}", "labgrid"):
        for c in comps:
            st_ = D.pc_status(s, lab, c["pc"])
            on = " on" if sel == (lab, c["pc"]) else ""
            hit(
                f'<div class="pc-btn s-{st_}{on}" title="{h(pc_tip(s, lab, c["pc"]))}">{ic("pc")}'
                f'<small>{D.pad(c["pc"])}</small></div>',
                f"{p}_lg_{ctx}_{lab}_{c['pc']}",
                on_pc,
                (lab, c["pc"]),
            )


def live_map(
    p: str, s: dict, ctx: str, on_pc, focus: int | None = None, sel: tuple | None = None
) -> None:
    """The floor map with every computer clickable (hover shows its status).

    The four Centrum laboratories are on the round floor plan; laboratories
    added later are drawn underneath as seat grids."""
    show_svg = not focus or D.on_floor_map(focus)
    if show_svg:
        with box(f"{p}_map_{ctx}", "mapbox"):
            html(f'<div class="map-wrap">{map_svg(s, ctx, focus, sel)}</div>')
            for lab, pc, _, _ in _PC_POS:
                if (lab, pc) in s["computers"] and (not focus or focus == lab):
                    st.button(
                        f"{D.lab_name(lab)} {D.pc_name(pc)}",
                        key=f"pcb_{ctx}_{lab}_{pc}__pcdot__",
                        help=pc_tip(s, lab, pc),
                        on_click=on_pc,
                        args=(lab, pc),
                    )
    extra = [lab for lab, _ in D.LABS if not D.on_floor_map(lab) and (not focus or focus == lab)]
    for lab in extra:
        lab_grid(p, s, ctx, lab, on_pc, sel)
    html(LEGEND)
    off_map = sorted(
        k for k in s["computers"]
        if D.on_floor_map(k[0]) and k[1] > D.MAP_SEATS and (not focus or k[0] == focus)
    )
    if off_map:
        html(
            f'<div class="unplaced">{ic("info")} Not drawn on the floor map yet:</div>'
        )
        with box(f"{p}_offmap_{ctx}", "chips"):
            for lab, pc in off_map:
                btn(
                    D.asset_tag(lab, pc),
                    f"{p}_off_{ctx}_{lab}_{pc}",
                    "chip",
                    on_click=on_pc,
                    args=(lab, pc),
                )


def mini_map(lab: int) -> str:
    q = {1: (270, 360), 2: (180, 270), 3: (0, 90), 4: (90, 180)}
    out = '<svg class="mini" viewBox="0 0 40 40" aria-hidden="true">'
    for n in (1, 2, 3, 4):
        a0, a1 = math.radians(q[n][0] + 12), math.radians(q[n][1] - 12)

        def pt(a, rad):
            return f"{20 + rad * math.cos(a):.2f},{20 - rad * math.sin(a):.2f}"

        out += (
            f'<path d="M{pt(a0, 18)} A18,18 0 0 0 {pt(a1, 18)} L{pt(a1, 10)} A10,10 0 0 1 {pt(a0, 10)} Z" '
            f'fill="{"#2d6fe3" if n == lab else "#c9d8f5"}"/>'
        )
    return (
        out
        + '<circle cx="20" cy="20" r="6" fill="#14213d"/><circle cx="20" cy="20" r="2.4" fill="#fff"/></svg>'
    )


def lab_tile(s: dict, lab: int, on: bool = False) -> str:
    sm = D.lab_summary(s, lab)
    total = sm["total"] or 1
    need = sm["reported"] + sm["repair"]
    bar = f'<i style="width:{sm["ok"] / total * 100:.1f}%;background:var(--ok)"></i>'
    for key, color in (("reported", "--rep"), ("under_repair", "--fix"),
                       ("escalated", "--esc"), ("maint", "--maint")):
        if sm[key]:
            bar += f'<i style="width:{sm[key] / total * 100:.1f}%;background:var({color})"></i>'
    icon = mini_map(lab) if D.on_floor_map(lab) else f'<div class="lab-ic">{ic("building")}</div>'
    return (
        f'<div class="lab-tile{" on" if on else ""}">{icon}<div style="flex:1;min-width:0"><b>{h(D.lab_name(lab))}</b>'
        f'<span>{sm["ok"]} of {sm["total"]} working'
        + (f" · {need} need attention" if need else "")
        + "</span>"
        f'<div class="bar" title="{sm["ok"]} working, {sm["reported"]} reported, {sm["under_repair"]} under repair, '
        f'{sm["escalated"]} escalated, {sm["maint"]} under maintenance">{bar}</div></div></div>'
    )


def lab_tiles(p: str, s: dict, ctx: str, on_click, on: int | None = None) -> None:
    """The four laboratory tiles, stacked; clicking one calls on_click(lab)."""
    with box(f"{p}_tiles_{ctx}", "stack", "gap10"):
        for lab, _ in D.LABS:
            hit(
                lab_tile(s, lab, on=on == lab), f"{p}_lab_{ctx}_{lab}", on_click, (lab,)
            )


# ===========================================================================
# Laboratory analytics (Dashboard): computers, working units and reports per lab
# ===========================================================================
PERIODS = {
    "all": "All time",
    "7": "Last 7 days",
    "30": "Last 30 days",
    "90": "Last 90 days",
    "365": "Last 12 months",
}


def period_since(key: str):
    return None if key == "all" else D.now() - timedelta(days=int(key))


def lab_analytics(p: str, s: dict, ctx: str = "dash", title: str = "Laboratory analytics") -> None:
    """A card with a laboratory filter and a period filter showing, per
    laboratory: number of computers, units working, and how many reports are
    new, under repair, escalated and fixed."""
    with box(f"{p}_la_{ctx}", "card", "mt"):
        with box(f"{p}_la_h_{ctx}", "cardh"):
            html(
                f'<div><h3>{h(title)}</h3><div class="sub">Computers, working units and reports per '
                "laboratory. Filter by laboratory and period.</div></div>"
            )
            with box(f"{p}_la_ctl_{ctx}", "row"):
                labs = [0] + [lab for lab, _ in D.LABS]
                k = ui.sticky(f"{p}_la_lab_{ctx}__selwide__", labs)
                lab = st.selectbox(
                    "Laboratory",
                    labs,
                    format_func=lambda x: D.lab_name(x) if x else "All laboratories",
                    key=k,
                    label_visibility="collapsed",
                )
                ui.remember(k)
                k2 = ui.sticky(f"{p}_la_per_{ctx}__sel__", list(PERIODS))
                per = st.selectbox(
                    "Period",
                    list(PERIODS),
                    format_func=PERIODS.get,
                    key=k2,
                    label_visibility="collapsed",
                )
                ui.remember(k2)
        since = period_since(per)
        rows = D.lab_breakdown(s, [lab] if lab else None, since)

        def tot(k):
            return sum(r[k] for r in rows)

        computers, working, active = tot("pc_all"), tot("pc_ok"), tot("pc_total")
        pct = f" ({round(working / active * 100)}%)" if active else ""
        dot = '<i style="background:var({})"></i>'
        html(
            '<div class="stat-mini">'
            f'<div><b>{computers}</b><span>Computers</span></div>'
            f'<div><b>{working}</b><span>{dot.format("--ok")}Working units{pct}</span></div>'
            f'<div><b>{tot("r_reported")}</b><span>{dot.format("--rep")}New reports</span></div>'
            f'<div><b>{tot("r_repair")}</b><span>{dot.format("--fix")}Under repair</span></div>'
            f'<div><b>{tot("r_escalated")}</b><span>{dot.format("--esc")}Escalated</span></div>'
            f'<div><b>{tot("r_fixed")}</b><span>{dot.format("--done")}Fixed</span></div>'
            "</div>"
        )
        body = "".join(
            f'<tr><td class="strong">{h(r["name"])}<div class="small">{h(r["wing"])}</div></td>'
            f'<td class="num">{r["pc_all"]}</td>'
            f'<td class="num">{r["pc_ok"]} <span class="small">'
            f'({round(r["pc_ok"] / r["pc_total"] * 100) if r["pc_total"] else 0}%)</span></td>'
            f'<td class="num">{r["pc_inactive"]}</td>'
            f'<td class="num">{r["r_reported"]}</td><td class="num">{r["r_repair"]}</td>'
            f'<td class="num">{r["r_escalated"]}</td><td class="num">{r["r_fixed"]}</td>'
            f'<td class="num"><b>{r["r_total"]}</b></td></tr>'
            for r in rows
        )
        if len(rows) > 1:
            body += (
                f'<tr style="background:#fafbfd"><td class="strong">All laboratories</td><td class="num"><b>{computers}</b></td>'
                f'<td class="num"><b>{working}</b></td><td class="num"><b>{tot("pc_inactive")}</b></td>'
                f'<td class="num"><b>{tot("r_reported")}</b></td><td class="num"><b>{tot("r_repair")}</b></td>'
                f'<td class="num"><b>{tot("r_escalated")}</b></td><td class="num"><b>{tot("r_fixed")}</b></td>'
                f'<td class="num"><b>{tot("r_total")}</b></td></tr>'
            )
        html(
            '<div class="table-wrap" style="margin:16px 0 0"><table class="t"><thead><tr>'
            '<th>Laboratory</th><th class="num">Computers</th><th class="num">Working units</th>'
            '<th class="num">Inactive</th><th class="num">New reports</th><th class="num">Under repair</th>'
            '<th class="num">Escalated</th><th class="num">Fixed</th><th class="num">Total reports</th>'
            f"</tr></thead><tbody>{body}</tbody></table></div>"
            f'<div class="adm-help" style="margin-top:8px">Report counts: reports sent '
            f'{h(PERIODS[per].lower()) if per != "all" else "at any time"}, by their current status.</div>'
        )


# ===========================================================================
# The shell: sidebar, top bar, page + pop-up state
# ===========================================================================
class Shell:
    """One dashboard's frame. pages = [(key, label, icon), ...]."""

    def __init__(self, prefix: str, role: str, pages: list[tuple]):
        self.p = prefix
        self.role = role
        self.pages = pages
        self.titles = {k: label for k, label, _ in pages}

    # ---- state ------------------------------------------------------------
    @property
    def page(self) -> str:
        page = ss.get(f"{self.p}_page", self.pages[0][0])
        return page if page in self.titles else self.pages[0][0]

    @property
    def modal(self) -> tuple:
        return ss.get(f"{self.p}_modal") or (None, None)

    def go(self, page: str) -> None:
        ss[f"{self.p}_page"] = page
        ss.pop(f"{self.p}_modal", None)

    def open_modal(self, kind: str, ref=None) -> None:
        ss[f"{self.p}_modal"] = (kind, ref)

    def close_modal(self) -> None:
        ss.pop(f"{self.p}_modal", None)

    def toast(self, msg: str, ok: bool = True) -> None:
        ui.flash(self.p, msg, ok)

    # ---- frame ------------------------------------------------------------
    def frame(self, user: dict, s: dict, counts: dict, notifications: list) -> None:
        """Styles, sidebar, top bar and messages.

        notifications: list of dicts {id, icon, tone, title, sub, t, cb, args, roles?}. Items whose
        `roles` don't include this dashboard's role are left out; read marks are kept per user.
        """
        lab_store.sync_labs()  # laboratories added in the app (Inventory -> Add laboratory)
        st.markdown(f"<style>{css()}</style>", unsafe_allow_html=True)
        ui.install_loader()  # the "Working..." loading animation
        self._sidebar(user, counts)
        self._topbar(user, s, notifications)
        ui.show_flash(self.p)

    def content(self):
        return st.container(key="cl_content")

    def _sidebar(self, user: dict, counts: dict) -> None:
        with st.sidebar:
            html(
                f'<div class="side-logo">{SIDE_LOGO}</div><div class="side-label">{h(self.role)} menu</div>'
            )
            with st.container(key="cl_nav"):
                for key, label, icon_name in self.pages:
                    n = counts.get(key)
                    count = f'<span class="count">{n}</span>' if n else ""
                    active = " active" if key == self.page else ""
                    hit(
                        f'<div class="nav-item{active}">{ic(icon_name)}{h(label)}{count}</div>',
                        f"{self.p}_nav_{key}",
                        self.go,
                        (key,),
                    )
            # pinned to the bottom of the sidebar by CSS (.st-key-cl_sidefoot)
            with st.container(key="cl_sidefoot"):
                html(
                    f'<div class="side-user"><div class="avatar">{h(initials(user["name"]))}</div><div style="min-width:0">'
                    f'<b>{h(user["name"])}</b>{h(self.role)}</div></div>'
                )
                hit(
                    f'<div class="nav-item">{ic("logout")}Log out</div>',
                    f"{self.p}_nav_logout",
                    self.open_modal,
                    ("logout",),
                )

    # ---- notifications ------------------------------------------------------
    @staticmethod
    def user_key(user: dict) -> str:
        return (user.get("email") or user.get("name") or "user").strip().lower()

    def _visible(self, items: list) -> list:
        role = self.role.lower()
        out = [
            n
            for n in items
            if not n.get("roles") or role in [r.lower() for r in n["roles"]]
        ]
        seen, uniq = set(), []
        for n in sorted(out, key=lambda n: n.get("t") or D.now(), reverse=True):
            if n["id"] not in seen:
                seen.add(n["id"])
                uniq.append(n)
        return uniq

    def _open_notif(self, ukey: str, nid: str, cb, args) -> None:
        lab_store.mark_read(ukey, [nid])
        self.close_modal()  # close the notifications window, then open the item
        if cb:
            cb(*args)

    def _mark(self, ukey: str, ids: list) -> None:
        lab_store.mark_read(ukey, ids)
        self.toast(
            "Marked as read"
            if len(ids) == 1
            else f"{len(ids)} notifications marked as read"
        )

    def _bell(self, user: dict, items: list) -> None:
        """The notifications button in the top bar: a bell with the unread
        count. It opens the notifications window (no dropdown menu)."""
        ukey = self.user_key(user)
        items = self._visible(items)
        read = lab_store.read_ids(ukey)
        n_unread = sum(1 for n in items if n["id"] not in read)
        # what the notifications window shows (drawn later with the other pop-ups)
        ss[f"{self.p}_notif_ctx"] = (ukey, items)
        count = (
            f'<span class="nb-count">{"9+" if n_unread > 9 else n_unread}</span>'
            if n_unread else ""
        )
        label = f"Notifications · {n_unread} unread" if n_unread else "Notifications"
        with st.container(key="cl_bell"):
            hit(
                f'<div class="nbtn{" has" if n_unread else ""}" title="{h(label)}" aria-label="{h(label)}">'
                f"{BELL_SVG}{count}</div>",
                f"{self.p}_bell",
                self.open_modal,
                ("notifs",),
            )

    def notifications_window(self) -> None:
        """The notifications pop-up window (opened from the bell)."""
        ukey, items = ss.get(f"{self.p}_notif_ctx") or ("", [])
        read = lab_store.read_ids(ukey) if ukey else set()
        unread = [n for n in items if n["id"] not in read]
        n_unread = len(unread)
        view_key = f"{self.p}_nview"
        view = ss.get(view_key) or ("unread" if n_unread else "all")
        with self.window():
            with st.container(key="cl_nhead"):
                html(
                    f'<div><h3 style="margin:0">Notifications</h3><div class="m-sub" style="margin:2px 0 0">'
                    f'{n_unread} unread · {len(items)} in total</div></div>'
                )
                btn(
                    "Mark all as read",
                    f"{self.p}_nall",
                    "link",
                    disabled=not n_unread,
                    on_click=self._mark,
                    args=(ukey, [n["id"] for n in unread]),
                )
            with box("cl_nchips", "chips"):
                btn(
                    f"Unread · {n_unread}",
                    f"{self.p}_nv_unread",
                    "chipon" if view == "unread" else "chip",
                    on_click=_set,
                    args=(view_key, "unread"),
                )
                btn(
                    f"All · {len(items)}",
                    f"{self.p}_nv_all",
                    "chipon" if view == "all" else "chip",
                    on_click=_set,
                    args=(view_key, "all"),
                )
            shown = unread if view == "unread" else items
            if not shown:
                text = "You're all caught up." if items else "No notifications yet."
                html(
                    f'<div class="empty" style="padding:28px 10px">{ic("bell")}<div>{h(text)}</div>'
                    + (
                        '<div style="font-size:12px;margin-top:4px">Earlier notifications are under “All”.</div>'
                        if items and view == "unread"
                        else ""
                    )
                    + "</div>"
                )
            with box(f"{self.p}_nlist", "nlist"):
                for n in shown[:NOTIF_SHOWN]:
                    is_read = n["id"] in read
                    nid = re.sub(r"[^A-Za-z0-9]", "_", str(n["id"]))
                    cls = "row clickable " + ("isread" if is_read else "unread")
                    when = D.when(n["t"]) if n.get("t") else ""
                    sub = " · ".join(x for x in (n.get("sub") or "", when) if x)
                    with box(f"{self.p}_nrow_{nid}", "nrow"):
                        hit(
                            f'<div class="{cls}"><div class="ic {n.get("tone", "ic-blue")}">{ic(n.get("icon", "bell"))}</div>'
                            f'<div class="main-t"><b>{h(n["title"])}</b><span>{h(sub)}</span></div></div>',
                            f"{self.p}_notif_{nid}",
                            self._open_notif,
                            (ukey, n["id"], n.get("cb"), tuple(n.get("args") or ())),
                        )
                        if not is_read:
                            btn(
                                "✓",
                                f"{self.p}_nmk_{nid}",
                                "nmark",
                                help="Mark as read",
                                on_click=self._mark,
                                args=(ukey, [n["id"]]),
                            )
            if len(shown) > NOTIF_SHOWN:
                html(
                    f'<div class="nfoot">Showing the latest {NOTIF_SHOWN} of {len(shown)}.</div>'
                )
            elif view == "all" and items:
                html('<div class="nfoot">This is your notification history.</div>')

    def _topbar(self, user: dict, s: dict, items: list) -> None:
        with st.container(key="cl_top"):
            html(
                f'<div style="min-width:0"><div class="adm-crumb">Computer Laboratory · {h(self.role)}</div>'
                f'<div class="adm-title">{h(self.titles[self.page])}</div></div>'
            )
            with st.container(key="cl_topright"):
                if not s.get("live"):
                    html(
                        '<span class="badge b-neutral sample-tag" title="Not connected to the server. Changes are saved '
                        "on this app's server only.\">Offline</span>"
                    )
                self._bell(user, items)
                with st.container(key="cl_userchip"):
                    hit(
                        f'<div class="user" title="My profile"><div class="avatar">{h(initials(user["name"]))}</div>'
                        f'<div class="user-name">{h(user["name"])}<small>{h(self.role)}</small></div></div>',
                        f"{self.p}_user",
                        self.go,
                        ("profile",),
                    )

    # ---- pop-up windows ---------------------------------------------------
    @contextmanager
    def window(self, wide: bool = False):
        """A pop-up window with a close (✕) button."""
        with box(f"{self.p}_modal", "modal", *(["modalwide"] if wide else [])):
            btn("✕", f"{self.p}_mx", "x", on_click=self.close_modal, help="Close")
            yield

    def confirm(
        self, title: str, text: str, label: str, cb, args=(), danger: bool = True
    ) -> None:
        """Ask before doing something that can't be undone; cb(*args) runs on 'yes'."""
        ss[f"{self.p}_confirm"] = {
            "title": title,
            "text": text,
            "label": label,
            "cb": cb,
            "args": tuple(args),
            "danger": danger,
            "back": ss.get(f"{self.p}_modal"),
        }
        self.open_modal("confirm")

    def _confirm_yes(self) -> None:
        c = ss.pop(f"{self.p}_confirm", None)
        self.close_modal()
        if c:
            c["cb"](*c["args"])

    def _confirm_no(self) -> None:
        c = ss.pop(f"{self.p}_confirm", None)
        back = (c or {}).get("back")
        if back and back[0] != "confirm":
            ss[f"{self.p}_modal"] = back
        else:
            self.close_modal()

    def confirm_window(self) -> None:
        c = ss.get(f"{self.p}_confirm")
        if not c:
            return self.close_modal()
        with box(f"{self.p}_modal", "modal"):
            html(f'<h3>{h(c["title"])}</h3><div class="m-sub">{h(c["text"])}</div>')
            with box(f"{self.p}_cf_btns", "mactions"):
                btn("Cancel", f"{self.p}_cf_no", "ghost", on_click=self._confirm_no)
                btn(
                    c["label"],
                    f"{self.p}_cf_yes",
                    "danger" if c["danger"] else "primary",
                    on_click=self._confirm_yes,
                )

    def common_modal(self, kind: str) -> bool:
        """Draw the pop-ups every dashboard has (log out, confirm). True if `kind` was one of them."""
        if kind == "logout":
            self.logout_window()
        elif kind == "notifs":
            self.notifications_window()
        elif kind == "confirm":
            self.confirm_window()
        else:
            return False
        return True

    def logout_window(self) -> None:
        with box(f"{self.p}_modal", "modal"):
            html(
                '<h3>Log out?</h3><div class="m-sub">You\'ll go back to the Computer Laboratory login screen.</div>'
            )
            with box(f"{self.p}_lo_btns", "mactions"):
                btn("Stay", f"{self.p}_lo_stay", "ghost", on_click=self.close_modal)
                btn("Log out", f"{self.p}_lo_go", "primary", on_click=ui.logout_user)

    # ---- profile ----------------------------------------------------------
    def profile_head(self, user: dict, role_badge: str, status_badge: str) -> None:
        html(
            f'<div class="card profile-card"><div class="avatar-lg">{h(initials(user["name"]))}</div><div>'
            f'<div class="profile-fixed-name">{h(user["name"])}</div><div class="profile-role"><span class="badge b-neutral">'
            f'{h(role_badge)}</span><span class="badge b-fixed">{h(status_badge)}</span></div></div></div>'
        )

    def _start_edit(self, current: str) -> None:
        ss[f"{self.p}_editing_number"] = True
        ss[f"{self.p}_edit_number_in"] = "" if current == "Not set" else current

    def _save_number(self, save) -> None:
        value = re.sub(r"[\s\-()]", "", ss.get(f"{self.p}_edit_number_in") or "")
        if value and not PHONE_RE.match(value):
            return self.toast("Enter a mobile number like 09XX XXX XXXX.", False)
        ok, msg = save(value)
        self.toast(msg, ok)
        if ok:
            ss.pop(f"{self.p}_editing_number", None)

    def _start_email_edit(self, current: str) -> None:
        ss[f"{self.p}_editing_email"] = True
        ss[f"{self.p}_edit_email_in"] = "" if current == "Not set" else current
        ss[f"{self.p}_edit_email_pw"] = ""

    def _cancel_email_edit(self) -> None:
        ss.pop(f"{self.p}_editing_email", None)
        ss[f"{self.p}_edit_email_pw"] = ""

    def _save_email(self, save, user: dict) -> None:
        value = (ss.get(f"{self.p}_edit_email_in") or "").strip().lower()
        password = ss.get(f"{self.p}_edit_email_pw") or ""
        ss[f"{self.p}_edit_email_pw"] = ""  # never keep the password around
        if not EMAIL_RE.match(value):
            return self.toast("Enter a valid email address.", False)
        if value == (user.get("email") or "").strip().lower():
            return self.toast("That is already your email address.", False)
        if not password:
            return self.toast("Enter your current password to change your email.", False)
        try:
            ok, msg = save(value, password)
        except Exception:
            ok, msg = False, "Could not connect to the server. Your email was not changed."
        self.toast(msg, ok)
        if ok:
            user["email"] = value
            ss.pop(f"{self.p}_editing_email", None)

    def contact_card(self, user: dict, save_number, email_note: str = "", save_email=None) -> None:
        """Email and contact number.
        save_number(number) -> (ok, message).
        save_email(new_email, current_password) -> (ok, message): the email gets an Edit
        button. Without it, email_note makes Edit explain how to change it."""
        html('<div class="card-h"><h3>Contact information</h3></div>')
        number = fmt_number(user.get("contact_number") or "") or "Not set"
        for fld, label, icon_name, value in (
            ("email", "Email address", "mail", user.get("email") or "Not set"),
            ("number", "Contact number", "phone", number),
        ):
            with box(f"{self.p}_pf_{fld}", "row", "gap14", "spread"):
                html(
                    f'<div class="profile-field-row" style="border:0;padding:12px 0"><div class="ic">{ic(icon_name)}</div>'
                    f'<div class="f"><small>{label}</small><div class="v">{h(value)}</div></div></div>'
                )
                if fld == "number":
                    btn(
                        "Edit" if value != "Not set" else "Add",
                        f"{self.p}_pf_number_edit",
                        "ghostsm",
                        on_click=self._start_edit,
                        args=(value,),
                    )
                elif save_email:
                    btn(
                        "Edit",
                        f"{self.p}_pf_email_edit",
                        "ghostsm",
                        on_click=self._start_email_edit,
                        args=(value,),
                    )
                elif email_note:
                    btn(
                        "Edit",
                        f"{self.p}_pf_email_edit",
                        "ghostsm",
                        on_click=self.toast,
                        args=(email_note, False),
                    )
            if fld == "number" and ss.get(f"{self.p}_editing_number"):
                with box(f"{self.p}_pf_number_inl", "row"):
                    st.text_input(
                        label,
                        key=f"{self.p}_edit_number_in",
                        label_visibility="collapsed",
                        placeholder="09XX XXX XXXX",
                    )
                    btn(
                        "Save",
                        f"{self.p}_pf_number_save",
                        "primarysm",
                        on_click=self._save_number,
                        args=(save_number,),
                    )
                    btn(
                        "Cancel",
                        f"{self.p}_pf_number_cancel",
                        "ghostsm",
                        on_click=ss.pop,
                        args=(f"{self.p}_editing_number", None),
                    )
            if fld == "email" and save_email and ss.get(f"{self.p}_editing_email"):
                with box(f"{self.p}_pf_email_inl", "row"):
                    st.text_input(
                        "New email address",
                        key=f"{self.p}_edit_email_in",
                        label_visibility="collapsed",
                        placeholder="New email address",
                    )
                    st.text_input(
                        "Current password",
                        type="password",
                        key=f"{self.p}_edit_email_pw",
                        label_visibility="collapsed",
                        placeholder="Current password",
                    )
                    btn(
                        "Save",
                        f"{self.p}_pf_email_save",
                        "primarysm",
                        on_click=self._save_email,
                        args=(save_email, user),
                    )
                    btn(
                        "Cancel",
                        f"{self.p}_pf_email_cancel",
                        "ghostsm",
                        on_click=self._cancel_email_edit,
                    )
                html(
                    '<div class="adm-help" style="margin:0 0 10px">You log in with this email. '
                    "Enter your current password to confirm the change.</div>"
                )
            if fld == "email":
                html('<div style="border-bottom:1px solid var(--line)"></div>')

    # ---- change password ----------------------------------------------------
    PW_RULES = (
        ("len", "At least 8 characters", lambda p: len(p) >= 8),
        ("upper", "An uppercase letter (A–Z)", lambda p: any(c.isupper() for c in p)),
        ("lower", "A lowercase letter (a–z)", lambda p: any(c.islower() for c in p)),
        ("digit", "A number (0–9)", lambda p: any(c.isdigit() for c in p)),
        ("symbol", "A symbol, e.g. ! @ # $ %", lambda p: any(not c.isalnum() and not c.isspace() for c in p)),
    )

    def _pw_key(self, name: str) -> str:
        return f"{self.p}_pw_{name}"

    def _pw_clear(self, keep_message: bool = False) -> None:
        for k in ("cur", "new", "conf"):
            ss[self._pw_key(k)] = ""
        ss.pop(self._pw_key("errors"), None)
        if not keep_message:
            ss.pop(self._pw_key("result"), None)

    def _change_password(self, change) -> None:
        """Validate, then change the password through the backend (change(cur, new)
        calls the real authentication API; nothing is saved or faked here)."""
        cur, new, conf = (ss.get(self._pw_key(k)) or "" for k in ("cur", "new", "conf"))
        errors = {}
        if not cur:
            errors["cur"] = "Enter your current password."
        if not new:
            errors["new"] = "Enter a new password."
        elif not all(test(new) for _, _, test in self.PW_RULES):
            errors["new"] = "The new password doesn't meet all the requirements."
        elif cur and new == cur:
            errors["new"] = "The new password must be different from the current one."
        if not conf:
            errors["conf"] = "Type the new password again."
        elif new and conf != new:
            errors["conf"] = "The passwords don't match."
        ss.pop(self._pw_key("result"), None)
        if errors:
            ss[self._pw_key("errors")] = errors
            return
        ss.pop(self._pw_key("errors"), None)
        try:
            ok, msg = change(cur, new)
        except Exception:
            ok, msg = False, "Could not connect to the server. Your password was not changed."
        if ok:
            self._pw_clear()
            ss[self._pw_key("result")] = (True, msg or "Your password was updated.")
            self.toast("Password updated")
        else:
            # keep what was typed so it can be corrected; clear only the current password
            ss[self._pw_key("cur")] = ""
            ss[self._pw_key("result")] = (False, msg or "Your password was not changed.")

    def password_card(self, change) -> None:
        """change(current, new) -> (ok, message)."""
        errors = ss.get(self._pw_key("errors")) or {}
        result = ss.get(self._pw_key("result"))
        new_pw = ss.get(self._pw_key("new")) or ""
        conf_pw = ss.get(self._pw_key("conf")) or ""
        with box(f"{self.p}_pw", "card", "mt"):
            html(
                '<div class="card-h"><div class="ic ic-blue" style="width:42px;height:42px;border-radius:12px;'
                f'display:grid;place-items:center">{ic("shield")}</div><div><h3>Change password</h3>'
                '<div class="sub">Use a strong password that you don\'t use anywhere else. '
                "Use the eye icon to show or hide what you type.</div></div></div>"
            )
            if result:
                ok, msg = result
                html(
                    f'<div class="pw-msg {"ok" if ok else "err"}">{ic("check" if ok else "alert")}'
                    f"<span><b>{'Password updated.' if ok else 'Password not changed.'}</b> {h(msg)}</span></div>"
                )
            with box(f"{self.p}_pw_grid", "pwgrid"):
                with box(f"{self.p}_pw_fields", "pwfields"):
                    for k, label, placeholder in (
                        ("cur", "Current password", "Your current password"),
                        ("new", "New password", "At least 8 characters"),
                        ("conf", "Confirm new password", "Type the new password again"),
                    ):
                        st.text_input(
                            label,
                            type="password",
                            key=self._pw_key(k),
                            placeholder=placeholder,
                            autocomplete="current-password" if k == "cur" else "new-password",
                        )
                        if errors.get(k):
                            html(f'<div class="pw-err">{ic("alert")}<span>{h(errors[k])}</span></div>')
                rules = "".join(
                    f'<li class="{"ok" if test(new_pw) else ""}"><i>✓</i>{h(label)}</li>'
                    for _, label, test in self.PW_RULES
                )
                match = bool(new_pw) and new_pw == conf_pw
                rules += f'<li class="{"ok" if match else ""}"><i>✓</i>Both new passwords match</li>'
                html(f'<div class="pw-rules"><h4>Password requirements</h4><ul>{rules}</ul></div>')
            with box(f"{self.p}_pw_btn", "mactions"):
                btn("Cancel", f"{self.p}_pw_cancel", "ghost", on_click=self._pw_clear)
                btn(
                    "Update password",
                    f"{self.p}_pw_save",
                    "primary",
                    icon=":material/lock_reset:",
                    on_click=self._change_password,
                    args=(change,),
                )

    def logout_button(self) -> None:
        with box(f"{self.p}_pf_logout_row", "row"):
            btn(
                "Log out",
                f"{self.p}_pf_logout",
                "danger",
                icon=":material/logout:",
                on_click=self.open_modal,
                args=("logout",),
            )