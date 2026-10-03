"""
frontend/portal.py - Centrum Laboratory | the shared dashboard shell

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

import streamlit as st

from frontend import lab_data as D
from frontend import ui
from frontend.portal_design import ICON, MAP_SVG, PORTAL_CSS, SIDE_LOGO

ss = st.session_state
html, btn, hit, box, h = ui.html, ui.btn, ui.hit, ui.box, ui.h
PER = 12  # table rows per page
PHONE_RE = re.compile(r"^(?:\+63|0)9\d{9}$")

LEGEND = ('<div class="legend"><span><i style="background:var(--ok)"></i>Working</span><span><i style="background:var(--rep)">'
          '</i>Reported</span><span><i style="background:var(--fix)"></i>Under repair / escalated</span></div>')


# ===========================================================================
# Small markup helpers
# ===========================================================================
def ic(name: str, cls: str = "") -> str:
    return (f'<svg class="i {cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
            f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{ICON.get(name, "")}</svg>')


def badge(status: str) -> str:
    label, cls = D.STATUS.get(status, (status, "b-neutral"))
    return f'<span class="badge {cls}">{h(label)}</span>'


def comp_badge(status: str) -> str:
    label, cls = D.computer_status_label(status)
    return f'<span class="badge {cls}">{h(label)}</span>'


def tone(status: str) -> str:
    """Icon colour for a report or computer status."""
    return {"ok": "ic-blue", "reported": "ic-amber", "repair": "ic-red", "escalated": "ic-violet",
            "fixed": "ic-green"}.get(status, "ic-blue")


def initials(name: str) -> str:
    words = name.split()
    return (words[0][:2] if len(words) == 1 else words[0][0] + words[-1][0]).upper() if words else "?"


def first_name(name: str) -> str:
    return (name.split() or ["there"])[0]


def greeting() -> str:
    hour = D.now().hour
    return "Good morning" if hour < 12 else "Good afternoon" if hour < 18 else "Good evening"


def fmt_number(value: str) -> str:
    """'09171234567' -> '0917 123 4567' (anything else is shown as it is)."""
    digits = re.sub(r"[\s\-()]", "", str(value or ""))
    return f"{digits[:4]} {digits[4:7]} {digits[7:]}" if re.fullmatch(r"09\d{9}", digits) else str(value or "")


def stat(icon_name: str, tone_cls: str, num, label: str) -> str:
    return (f'<div class="card stat"><div class="ic {tone_cls}">{ic(icon_name)}</div><div><div class="num">{h(num)}</div>'
            f'<div class="lbl">{h(label)}</div></div></div>')


def stats(*cards: str, cols: int = 4) -> None:
    html(f'<div class="grid g{cols}">' + "".join(cards) + "</div>")


def row(icon_name: str, tone_cls: str, title: str, sub: str, right: str = "", last: bool = False,
        clickable: bool = False) -> str:
    """A .row list item (icon, bold title, grey line, optional badge on the right). Text is escaped here."""
    cls = "row" + (" clickable" if clickable else "") + (" last" if last else "")
    return (f'<div class="{cls}"><div class="ic {tone_cls}">{ic(icon_name)}</div><div class="main-t"><b>{title}</b>'
            f'<span>{h(sub)}</span></div>{right}</div>')


def empty(text: str, icon_name: str = "check") -> str:
    return f'<div class="empty">{ic(icon_name)}<div>{h(text)}</div></div>'


def report_details(r: dict) -> str:
    """The body of a report's details window (who, when, urgency, technician, progress)."""
    tl = "".join(f'<li><b>{D.STATUS[e["s"]][0]}</b> — {h(e["note"])}<span>{D.date_time(e["t"])}</span></li>' for e in r["history"])
    esc = f'<dt>Escalation note</dt><dd>{h(r["esc_note"])}</dd>' if r.get("esc_note") else ""
    return (f'<div style="display:flex;gap:10px;align-items:center;margin-bottom:4px;padding-right:40px"><h3>{h(r["id"])} · '
            f'{h(r["issue"])}</h3>{badge(r["status"])}</div><div class="m-sub">{D.lab_name(r["lab"])} · {D.pc_name(r["pc"])}</div>'
            f'<dl class="kv"><dt>Reported by</dt><dd>{h(D.by_name(r))}</dd><dt>Reported</dt><dd>{D.date_time(r["created"])} '
            f'({D.when(r["created"])})</dd><dt>Urgency</dt><dd>{h(r["urgency"])}</dd><dt>Technician</dt>'
            f'<dd>{h(r["tech"] or "Not assigned yet")}</dd><dt>Details</dt><dd>{h(r["desc"] or "—")}</dd>{esc}</dl>'
            f'<h4 style="font-size:14px;margin-bottom:10px">Progress</h4><ul class="timeline">{tl}</ul>')


# ===========================================================================
# How Streamlit's widgets fit into the design
# ===========================================================================
_PC_POS = [(int(m.group(1)), int(m.group(2)), float(m.group(3)), float(m.group(4))) for m in re.finditer(
    r'data-room="(\d+)" data-pc="(\d+)"[^>]*rotate\([-\d.]+ ([\d.]+) ([\d.]+)\)', MAP_SVG)]

GLUE_CSS = """
[data-testid="stToolbar"], [data-testid="stDecoration"], [data-testid="stStatusWidget"], #MainMenu, footer { display: none !important; }
header[data-testid="stHeader"] { background: transparent !important; height: 0 !important; }
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
[data-testid="stSidebarHeader"] { height: 8px !important; min-height: 0 !important; padding: 0 !important; overflow: hidden; }
[data-testid="stSidebarUserContent"] { padding: 14px 16px 22px !important; min-height: calc(100vh - 8px);
  display: flex; flex-direction: column; }
[data-testid="stSidebarUserContent"] div:has(.st-key-cl_sidefoot) { flex: 1 1 auto; display: flex; flex-direction: column; }
.st-key-cl_sidefoot { border-top: 1px solid rgba(255,255,255,.08); padding-top: 14px; margin-top: auto !important; }
.st-key-cl_nav [class*="st-key-hitwrap_"] { margin-bottom: 2px; }
[class*="st-key-hitwrap_"]:hover .nav-item:not(.active) { background: rgba(255,255,255,.06); color: #fff; }
.st-key-cl_sidefoot [class*="st-key-hitwrap_"]:hover .nav-item { background: rgba(229,72,77,.12); color: #ffb4b4; }

/* top bar = .top */
.st-key-cl_top { position: sticky; top: 0; z-index: 90; height: 70px; padding: 0 28px; flex-direction: row !important;
  align-items: center; gap: 10px !important; background: rgba(255,255,255,.92); backdrop-filter: blur(10px);
  border-bottom: 1px solid var(--line); flex-wrap: nowrap; }
.st-key-cl_top > div { width: auto !important; flex: 0 0 auto; }
.st-key-cl_top > div:first-child { flex: 1 1 auto !important; min-width: 0; }
.adm-crumb { font-size: 12.5px; color: var(--faint); }
.adm-title { font: 600 19px 'Poppins', sans-serif; color: var(--navy); margin: 0; }
.st-key-cl_top [data-testid="stPopover"] button { width: 40px; height: 40px; min-height: 0 !important; padding: 0 !important;
  border-radius: 12px !important; border: 1px solid var(--line) !important; background: #fff !important; color: var(--muted) !important; }
.st-key-cl_top [data-testid="stPopover"] button:hover { color: var(--blue) !important; border-color: var(--blue-line) !important; }
.st-key-cl_top [data-testid="stPopover"] button [data-testid="stIconMaterial"]:not(:first-child),
.st-key-cl_top [data-testid="stPopover"] button svg:last-child:not(:first-child) { display: none; }
.st-key-cl_bell_dot [data-testid="stPopover"] button { position: relative; }
.st-key-cl_bell_dot [data-testid="stPopover"] button::after { content: ""; position: absolute; top: 9px; right: 10px; width: 7px;
  height: 7px; border-radius: 50%; background: #e5484d; box-shadow: 0 0 0 2px #fff; }
.st-key-cl_bell, .st-key-cl_bell_dot { width: auto !important; }
[data-testid="stPopoverBody"] { width: 340px; max-width: calc(100vw - 32px); border-radius: 16px !important;
  border: 1px solid var(--line) !important; box-shadow: 0 20px 50px rgba(20,33,61,.16) !important; padding: 16px 16px 6px !important; }
[data-testid="stPopoverBody"] [data-testid="stVerticalBlock"] { gap: 0 !important; }
.st-key-cl_userchip { width: auto !important; }
[class*="st-key-hitwrap_"]:hover .user { border-color: var(--blue-line); }
.st-key-cl_content { padding: 28px; max-width: 1360px; }

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
.fp .pc.s-none { fill: #e3e8f0; }
.fp .pc.s-ok { fill: var(--ok); }
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
[class*="__search__"] { min-width: 220px; }
[class*="__search__"] input { padding-left: 36px !important; background: url("__SEARCH_BG__") no-repeat 12px center !important; }
[class*="__sel__"] { min-width: 150px; }
[class*="__selwide__"] { min-width: 200px; }
.stApp [data-testid="stWidgetLabel"] p { font: 600 13px 'Poppins', sans-serif !important; color: var(--navy); }
.stApp [data-baseweb="tag"] { background: var(--blue-soft) !important; color: var(--blue) !important; border-radius: 999px !important; }

/* toast = .toast */
[data-testid="stToast"] { background: var(--navy) !important; border-radius: 12px !important; box-shadow: 0 12px 30px rgba(0,0,0,.2) !important; }
[data-testid="stToast"], [data-testid="stToast"] p, [data-testid="stToast"] button { color: #fff !important; font-size: 13.5px; }

@media (max-width: 1180px) {
  [class*="__g4__"] { grid-template-columns: repeat(2, minmax(0,1fr)); }
  [class*="__gmap__"], [class*="__g2__"] { grid-template-columns: minmax(0,1fr); }
}
@media (max-width: 880px) {
  .st-key-cl_content { padding: 18px 16px; }
  .st-key-cl_top { padding: 0 16px; }
  [class*="__g3__"], [class*="__formgrid__"] { grid-template-columns: minmax(0,1fr); }
  .adm-crumb, .user .user-name, .sample-tag { display: none; }
  .tt-hide-sm { display: none !important; }
}
""".replace("__SEARCH_BG__", "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='16' height='16' "
            "viewBox='0 0 24 24' fill='none' stroke='%238b93a1' stroke-width='2' stroke-linecap='round'><circle cx='11' "
            "cy='11' r='7'/><path d='m20 20-3.5-3.5'/></svg>")

_CSS_CACHE: list[str] = []


def css() -> str:
    if not _CSS_CACHE:
        pos = "".join(f'[class*="_{lab}_{pc}__pcdot__"]{{left:{(cx + 6) / 612 * 100:.2f}%;top:{(cy + 6) / 612 * 100:.2f}%;}}'
                      for lab, pc, cx, cy in _PC_POS)
        _CSS_CACHE.append(ui.scope_css(PORTAL_CSS + GLUE_CSS) + pos)
    return _CSS_CACHE[0]


# ===========================================================================
# Widgets used on several pages
# ===========================================================================
def sort_select(key: str, options: dict) -> str:
    """A 'Sort by' dropdown that keeps its value while the page is hidden."""
    k = ui.sticky(key, list(options))
    value = st.selectbox("Sort by", list(options), format_func=options.get, key=k, label_visibility="collapsed")
    ui.remember(k)
    return value


def _set(key: str, value) -> None:
    ss[key] = value


def pager(key: str, page: int, total: int, per: int = PER) -> None:
    pages = max(1, -(-total // per))
    with box(f"{key}_pager", "pager"):
        shown = f"{page * per + 1}–{min(total, (page + 1) * per)} of {total}" if total else "0 items"
        html(f'<span class="muted" style="font-size:13px">{shown}</span>')
        with box(f"{key}_pager_btns", "row"):
            btn("Previous", f"{key}_prev", "ghostsm", disabled=page <= 0, on_click=_set, args=(key, page - 1))
            btn("Next", f"{key}_next", "ghostsm", disabled=page >= pages - 1, on_click=_set, args=(key, page + 1))


def page_slice(rows: list, key: str, per: int = PER) -> tuple[list, int]:
    page = min(ss.get(key, 0), max(0, (len(rows) - 1) // per))
    return rows[page * per:(page + 1) * per], page


def field(label: str, key: str, placeholder: str = "", kind: str = "text", help_text: str = "") -> None:
    with box(f"{key}_wrap", "field"):
        html(f'<div class="adm-label">{h(label)}</div>')
        if kind == "area":
            st.text_area(label, key=key, placeholder=placeholder, label_visibility="collapsed")
        else:
            st.text_input(label, key=key, placeholder=placeholder, label_visibility="collapsed")
        if help_text:
            html(f'<div class="adm-help">{h(help_text)}</div>')


def chart_table(rows, head) -> str:
    body = "".join(f"<tr><td>{h(label)}</td><td>{v}</td></tr>" for label, _, v in rows)
    return (f'<details class="chart-table"><summary class="link" style="font-size:12.5px">Show as table</summary>'
            f'<table><tr><th>{head[0]}</th><th>{head[1]}</th></tr>{body}</table></details>')


def bars_v(rows: list[tuple], unit: str, head: tuple) -> str:
    """Column chart; rows are (label, short label, value)."""
    top = max([v for _, _, v in rows] + [1])
    cols = "".join(f'<div class="col" title="{h(label)}: {v} {unit}"><span class="val">{v}</span>'
                   f'<div class="b" style="height:{v / top * 82:.1f}%"></div></div>' for label, _, v in rows)
    xs = "".join(f"<span>{h(short)}</span>" for _, short, _ in rows)
    return f'<div class="chart"><div class="bars-v">{cols}</div><div class="bars-x">{xs}</div></div>' + chart_table(rows, head)


def bars_h(rows: list[tuple], unit: str, head: tuple) -> str:
    """Bar chart; rows are (label, short label, value)."""
    top = max([v for _, _, v in rows] + [1])
    body = "".join(f'<div class="r" title="{h(label)}: {v} {unit}"><span>{h(label)}</span><div class="track">'
                   f'<div class="fill" style="width:{v / top * 100:.1f}%"></div></div><b>{v}</b></div>' for label, _, v in rows)
    return f'<div class="bars-h">{body}</div>' + chart_table(rows, head)


# ===========================================================================
# Live floor map + laboratory tiles
# ===========================================================================
def map_svg(s: dict, ctx: str, focus: int | None = None, sel: tuple | None = None) -> str:
    def paint(m):
        lab, pc = int(m.group(1)), int(m.group(2))
        st_ = D.pc_status(s, lab, pc) if (lab, pc) in s["computers"] else "none"
        cls = f"pc s-{st_}" + (" sel" if sel == (lab, pc) else "")
        return f'<rect class="{cls}" data-room="{lab}" data-pc="{pc}"'
    svg = re.sub(r'<rect class="pc" data-room="(\d+)" data-pc="(\d+)"', paint, MAP_SVG.replace("__P__", f"{ctx}_"))
    if focus:
        svg = svg.replace('class="fp"', 'class="fp focus"', 1)
        svg = svg.replace(f'class="fp-pcs" data-room="{focus}"', f'class="fp-pcs on" data-room="{focus}"')
        svg = svg.replace(f'class="fp-room" data-room="{focus}"', f'class="fp-room on" data-room="{focus}"')
    return svg


def pc_tip(s: dict, lab: int, pc: int) -> str:
    r = D.pc_report(s, lab, pc)
    comp = s["computers"].get((lab, pc))
    name = f" ({comp['name']})" if comp and comp["name"] != comp["tag"] else ""
    head = f"{D.lab_name(lab)} · {D.pc_name(pc)}{name}"
    return f"{head} — " + (f"{D.STATUS[r['status']][0]}: {r['issue']}, {D.when(r['created'])}" if r else "Working")


def live_map(p: str, s: dict, ctx: str, on_pc, focus: int | None = None, sel: tuple | None = None) -> None:
    """The floor map with every computer clickable (hover shows its status)."""
    with box(f"{p}_map_{ctx}", "mapbox"):
        html(f'<div class="map-wrap">{map_svg(s, ctx, focus, sel)}</div>')
        for lab, pc, _, _ in _PC_POS:
            if (lab, pc) in s["computers"] and (not focus or focus == lab):
                st.button(f"{D.lab_name(lab)} {D.pc_name(pc)}", key=f"pcb_{ctx}_{lab}_{pc}__pcdot__",
                          help=pc_tip(s, lab, pc), on_click=on_pc, args=(lab, pc))
    html(LEGEND)
    off_map = sorted(k for k in s["computers"] if k[1] > D.MAP_SEATS and (not focus or k[0] == focus))
    if off_map:
        html(f'<div class="unplaced">{ic("info")} Not drawn on the floor map yet:</div>')
        with box(f"{p}_offmap_{ctx}", "chips"):
            for lab, pc in off_map:
                btn(D.asset_tag(lab, pc), f"{p}_off_{ctx}_{lab}_{pc}", "chip", on_click=on_pc, args=(lab, pc))


def mini_map(lab: int) -> str:
    q = {1: (270, 360), 2: (180, 270), 3: (0, 90), 4: (90, 180)}
    out = '<svg class="mini" viewBox="0 0 40 40" aria-hidden="true">'
    for n in (1, 2, 3, 4):
        a0, a1 = math.radians(q[n][0] + 12), math.radians(q[n][1] - 12)

        def pt(a, rad):
            return f"{20 + rad * math.cos(a):.2f},{20 - rad * math.sin(a):.2f}"
        out += (f'<path d="M{pt(a0, 18)} A18,18 0 0 0 {pt(a1, 18)} L{pt(a1, 10)} A10,10 0 0 1 {pt(a0, 10)} Z" '
                f'fill="{"#2d6fe3" if n == lab else "#c9d8f5"}"/>')
    return out + '<circle cx="20" cy="20" r="6" fill="#14213d"/><circle cx="20" cy="20" r="2.4" fill="#fff"/></svg>'


def lab_tile(s: dict, lab: int, on: bool = False) -> str:
    sm = D.lab_summary(s, lab)
    total = sm["total"] or 1
    need = sm["reported"] + sm["repair"]
    bar = f'<i style="width:{sm["ok"] / total * 100:.1f}%;background:var(--ok)"></i>'
    if sm["reported"]:
        bar += f'<i style="width:{sm["reported"] / total * 100:.1f}%;background:var(--rep)"></i>'
    if sm["repair"]:
        bar += f'<i style="width:{sm["repair"] / total * 100:.1f}%;background:var(--fix)"></i>'
    return (f'<div class="lab-tile{" on" if on else ""}">{mini_map(lab)}<div style="flex:1;min-width:0"><b>{D.lab_name(lab)}</b>'
            f'<span>{sm["ok"]} of {sm["total"]} working' + (f' · {need} need attention' if need else "") + '</span>'
            f'<div class="bar" title="{sm["ok"]} working, {sm["reported"]} reported, {sm["repair"]} under repair">{bar}</div></div></div>')


def lab_tiles(p: str, s: dict, ctx: str, on_click, on: int | None = None) -> None:
    """The four laboratory tiles, stacked; clicking one calls on_click(lab)."""
    with box(f"{p}_tiles_{ctx}", "stack", "gap10"):
        for lab, _ in D.LABS:
            hit(lab_tile(s, lab, on=on == lab), f"{p}_lab_{ctx}_{lab}", on_click, (lab,))


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
    def frame(self, user: dict, s: dict, counts: dict, notifications: list[tuple]) -> None:
        """Styles, sidebar, top bar and messages. notifications = [(icon, tone, title, sub, on_click, args)]."""
        st.markdown(f"<style>{css()}</style>", unsafe_allow_html=True)
        self._sidebar(counts)
        self._topbar(user, s, notifications)
        ui.show_flash(self.p)

    def content(self):
        return st.container(key="cl_content")

    def _sidebar(self, counts: dict) -> None:
        with st.sidebar:
            html(f'<div class="side-logo">{SIDE_LOGO}</div><div class="side-label">{h(self.role)} menu</div>')
            with st.container(key="cl_nav"):
                for key, label, icon_name in self.pages:
                    n = counts.get(key)
                    count = f'<span class="count">{n}</span>' if n else ""
                    active = " active" if key == self.page else ""
                    hit(f'<div class="nav-item{active}">{ic(icon_name)}{h(label)}{count}</div>', f"{self.p}_nav_{key}",
                        self.go, (key,))
            with st.container(key="cl_sidefoot"):
                hit(f'<div class="nav-item">{ic("logout")}Log out</div>', f"{self.p}_nav_logout", self.open_modal, ("logout",))

    def _topbar(self, user: dict, s: dict, items: list[tuple]) -> None:
        with st.container(key="cl_top"):
            html(f'<div><div class="adm-crumb">{h(self.role)}</div><div class="adm-title">{h(self.titles[self.page])}</div></div>')
            if not s["live"]:
                html('<span class="badge b-neutral sample-tag" title="These pages show sample data.">Sample data</span>')
            with st.container(key="cl_bell_dot" if items else "cl_bell"), st.popover(":material/notifications:"):
                html('<div class="card-h" style="margin-bottom:6px"><h3>Notifications</h3></div>')
                if not items:
                    html('<div class="empty">Nothing new</div>')
                for i, (icon_name, tone_cls, title, sub, cb, args) in enumerate(items):
                    hit(row(icon_name, tone_cls, h(title), sub, last=i == len(items) - 1, clickable=True),
                        f"{self.p}_notif_{i}", cb, args)
            with st.container(key="cl_userchip"):
                hit(f'<div class="user" title="My profile"><div class="avatar">{h(initials(user["name"]))}</div>'
                    f'<div class="user-name">{h(user["name"])}</div></div>', f"{self.p}_user", self.go, ("profile",))

    # ---- pop-up windows ---------------------------------------------------
    @contextmanager
    def window(self, wide: bool = False):
        """A pop-up window with a close (✕) button."""
        with box(f"{self.p}_modal", "modal", *(["modalwide"] if wide else [])):
            btn("✕", f"{self.p}_mx", "x", on_click=self.close_modal)
            yield

    def logout_window(self) -> None:
        with box(f"{self.p}_modal", "modal"):
            html("<h3>Log out?</h3><div class=\"m-sub\">You'll go back to the Centrum Laboratory login screen.</div>")
            with box(f"{self.p}_lo_btns", "mactions"):
                btn("Stay", f"{self.p}_lo_stay", "ghost", on_click=self.close_modal)
                btn("Log out", f"{self.p}_lo_go", "primary", on_click=ui.logout_user)

    # ---- profile ----------------------------------------------------------
    def profile_head(self, user: dict, role_badge: str, status_badge: str) -> None:
        html(f'<div class="card profile-card"><div class="avatar-lg">{h(initials(user["name"]))}</div><div>'
             f'<div class="profile-fixed-name">{h(user["name"])}</div><div class="profile-role"><span class="badge b-neutral">'
             f'{h(role_badge)}</span><span class="badge b-fixed">{h(status_badge)}</span></div></div></div>')

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

    def contact_card(self, user: dict, save_number, email_note: str = "") -> None:
        """Email (read-only; with email_note an Edit button explains how to change it) and contact number.
        save_number(number) -> (ok, message)."""
        html('<div class="card-h"><h3>Contact information</h3></div>')
        number = fmt_number(user.get("contact_number") or "") or "Not set"
        for fld, label, icon_name, value in (("email", "Email address", "mail", user.get("email") or "Not set"),
                                             ("number", "Contact number", "phone", number)):
            with box(f"{self.p}_pf_{fld}", "row", "gap14", "spread"):
                html(f'<div class="profile-field-row" style="border:0;padding:12px 0"><div class="ic">{ic(icon_name)}</div>'
                     f'<div class="f"><small>{label}</small><div class="v">{h(value)}</div></div></div>')
                if fld == "number":
                    btn("Edit" if value != "Not set" else "Add", f"{self.p}_pf_number_edit", "ghostsm",
                        on_click=self._start_edit, args=(value,))
                elif email_note:
                    btn("Edit", f"{self.p}_pf_email_edit", "ghostsm", on_click=self.toast, args=(email_note, False))
            if fld == "number" and ss.get(f"{self.p}_editing_number"):
                with box(f"{self.p}_pf_number_inl", "row"):
                    st.text_input(label, key=f"{self.p}_edit_number_in", label_visibility="collapsed",
                                  placeholder="09XX XXX XXXX")
                    btn("Save", f"{self.p}_pf_number_save", "primarysm", on_click=self._save_number, args=(save_number,))
                    btn("Cancel", f"{self.p}_pf_number_cancel", "ghostsm", on_click=ss.pop,
                        args=(f"{self.p}_editing_number", None))
            if fld == "email":
                html('<div style="border-bottom:1px solid var(--line)"></div>')

    def _change_password(self, change) -> None:
        cur, new, conf = (ss.get(f"{self.p}_pw_{k}") or "" for k in ("cur", "new", "conf"))
        if not cur or not new or not conf:
            return self.toast("Fill in all three password fields", False)
        if new != conf:
            return self.toast("The new passwords don't match", False)
        ok, msg = change(cur, new)
        self.toast(msg, ok)
        if ok:
            for k in ("cur", "new", "conf"):
                ss[f"{self.p}_pw_{k}"] = ""

    def password_card(self, change) -> None:
        """change(current, new) -> (ok, message)."""
        with box(f"{self.p}_pw", "card", "mt"):
            html('<div class="card-h"><div><h3>Change password</h3><div class="sub">Use at least 8 characters with an uppercase '
                 'letter, a number and a symbol.</div></div></div>')
            with box(f"{self.p}_pw_grid", "g3"):
                for k, label in (("cur", "Current password"), ("new", "New password"), ("conf", "Confirm new password")):
                    st.text_input(label, type="password", key=f"{self.p}_pw_{k}")
            with box(f"{self.p}_pw_btn", "rowend", "mt"):
                btn("Update password", f"{self.p}_pw_save", "primary", on_click=self._change_password, args=(change,))

    def logout_button(self) -> None:
        with box(f"{self.p}_pf_logout_row", "row"):
            btn("Log out", f"{self.p}_pf_logout", "danger", icon=":material/logout:", on_click=self.open_modal,
                args=("logout",))
