import base64
import re
from datetime import date, datetime
from html import escape

import streamlit as st
from logo import LOGO_URI

st.set_page_config(page_title="Centrum CMMS", layout="wide", initial_sidebar_state="expanded")

USER_NAME = "Alwyna Lopez"
USER_INITIALS = "AL"

ROOMS = ["CL 1", "CL 2", "CL 3", "CL 4"]
UNIT_COUNTS = {"CL 1": 35, "CL 2": 28, "CL 3": 30, "CL 4": 32}
ISSUE_OPTIONS = ["Won't turn on", "Slow performance", "No internet", "Blue screen (BSOD)",
                 "Missing keyboard", "Missing mouse", "Monitor issue", "Software error", "Other"]

# status key -> (label, colour class)
STATUS_META = {
    "progress": ("Being fixed", "amber"),
    "resolved": ("Resolved", "green"),
    "followup": ("Needs follow-up", "red"),
}
UNIT_STATUS_META = {
    "good": ("Good", "green"),
    "issue": ("Has issue", "amber"),
    "replace": ("Needs replacement", "red"),
}
FILTER_LABELS = {"all": "All", "good": "🟢 Good", "issue": "🟠 Have issue", "replace": "🔴 Need replacement"}
UNITS_PER_ROW = 7


# ---------- Small SVG helpers (embedded as data URIs so they always render) ----------
def svg_uri(svg: str) -> str:
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


def icon_uri(path: str, color: str) -> str:
    return svg_uri(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="{color}"><path d="{path}"/></svg>'
    )


ICON_PATHS = {
    "doc": "M14 2H6c-1.1 0-1.99.9-1.99 2L4 20c0 1.1.89 2 1.99 2H18c1.1 0 2-.9 2-2V8l-6-6zm2 16H8v-2h8v2zm0-4H8v-2h8v2zm-3-5V3.5L18.5 9H13z",
    "tool": "M22.7 19l-9.1-9.1c.9-2.3.4-5-1.5-6.9-2-2-5-2.4-7.4-1.3L9 6 6 9 1.6 4.7C.4 7.1.9 10.1 2.9 12.1c1.9 1.9 4.6 2.4 6.9 1.5l9.1 9.1c.4.4 1 .4 1.4 0l2.3-2.3c.5-.4.5-1.1.1-1.4z",
    "check": "M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z",
    "folder": "M10 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2h-8l-2-2z",
    "bell": "M12 22c1.1 0 2-.9 2-2h-4c0 1.1.89 2 2 2zm6-6v-5c0-3.07-1.64-5.64-4.5-6.32V4c0-.83-.67-1.5-1.5-1.5s-1.5.67-1.5 1.5v.68C7.63 5.36 6 7.92 6 11v5l-2 2v1h16v-1l-2-2z",
    "phone": "M6.62 10.79c1.44 2.83 3.76 5.14 6.59 6.59l2.2-2.2c.27-.27.67-.36 1.02-.24 1.12.37 2.33.57 3.57.57.55 0 1 .45 1 1V20c0 .55-.45 1-1 1-9.39 0-17-7.61-17-17 0-.55.45-1 1-1h3.5c.55 0 1 .45 1 1 0 1.25.2 2.45.57 3.57.11.35.03.74-.25 1.02l-2.2 2.2z",
    "mail": "M20 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2zm0 4l-8 5-8-5V6l8 5 8-5v2z",
    "person": "M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z",
    "search": "M15.5 14h-.79l-.28-.27A6.471 6.471 0 0 0 16 9.5 6.5 6.5 0 1 0 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z",
}

MONITOR_SVG = svg_uri(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 124">'
    '<defs><linearGradient id="s" x1="0" y1="0" x2="1" y2="1">'
    '<stop offset="0" stop-color="#3BB4F2"/><stop offset="1" stop-color="#0E86D4"/></linearGradient></defs>'
    '<rect x="6" y="4" width="108" height="88" rx="9" fill="#2B2B2F"/>'
    '<rect x="13" y="10" width="94" height="66" rx="3" fill="url(#s)"/>'
    '<path d="M13 10 H64 L13 62 Z" fill="#ffffff" opacity="0.18"/>'
    '<path d="M6 76 H114 V83 a9 9 0 0 1 -9 9 H15 a9 9 0 0 1 -9 -9 Z" fill="#DADBDE"/>'
    '<circle cx="60" cy="84" r="2.2" fill="#9A9BA0"/>'
    '<path d="M50 92 H70 L74 112 H46 Z" fill="#BDBEC2"/>'
    '<rect x="32" y="112" width="56" height="6" rx="3" fill="#CFD0D3"/></svg>'
)

# Settings list icons (coloured dots, as in the mockup)
SET_ICON_PROFILE = svg_uri(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><circle cx="12" cy="12" r="11" fill="#2E9E44"/>'
    f'<g transform="translate(5.4 5.4) scale(0.55)"><path d="{ICON_PATHS["person"]}" fill="#FFFFFF"/></g></svg>'
)
SET_ICON_NOTIF = svg_uri(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><circle cx="12" cy="12" r="11" fill="#F28C1B"/>'
    '<circle cx="12" cy="12" r="4.5" fill="#FFFFFF"/></svg>'
)
SET_ICON_SECURITY = svg_uri(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9" fill="none" '
    'stroke="#3B82F6" stroke-width="3.5"/></svg>'
)

UNIT_ICON = svg_uri(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#7c93c0" stroke-width="1.6">'
    '<rect x="3" y="4" width="18" height="12" rx="1"/><path d="M8 20h8M12 16v4"/></svg>'
)

# ---------- DESIGN ----------
CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

.stApp, .stApp p, .stApp label, .stApp input, .stApp textarea, .stApp h1, .stApp h2, .stApp h3 {
    font-family: 'Inter', 'Segoe UI', sans-serif;
}
.stApp { background: #F4F5F7; }
.block-container, [data-testid="stMainBlockContainer"] {
    padding: 4rem 2rem 2rem 2rem;
    max-width: 100%;
}

/* Desktop: keep our top bar, but leave Streamlit's expand/collapse controls alive */
@media (min-width: 900px) {
    header[data-testid="stHeader"] { background: transparent; }
    [data-testid="stAppDeployButton"] { display: none; }
    .block-container, [data-testid="stMainBlockContainer"] { padding-top: 0; }

    /* Only force the width while the sidebar is OPEN */
    section[data-testid="stSidebar"][aria-expanded="true"] {
        width: 250px !important;
        min-width: 250px !important;
    }
}

/* ---- Sidebar ---- */
section[data-testid="stSidebar"] {
    background: #FFFFFF;
    border-right: 1px solid #E5E7EB;
    box-shadow: 2px 0 8px rgba(15, 23, 42, 0.06);
}
section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] { padding-top: 0.9rem; }
section[data-testid="stSidebar"] [data-testid="stVerticalBlock"] { gap: 0.25rem; }
section[data-testid="stSidebar"] .stButton { width: 100%; }
section[data-testid="stSidebar"] .stButton button {
    background: transparent;
    border: none;
    color: #111827;
    font-size: 14px;
    font-weight: 400;
    padding: 0.55rem 0.6rem;
    border-radius: 8px;
    width: 100%;
    justify-content: flex-start;
    box-shadow: none;
}
section[data-testid="stSidebar"] .stButton button > div { justify-content: flex-start; gap: 0.6rem; }
section[data-testid="stSidebar"] .stButton button * { color: inherit !important; }
section[data-testid="stSidebar"] .stButton button:hover { background: #F1F5F9; color: #111827; }
.sidebar-section-label {
    color: #8A8F98;
    font-size: 10.5px;
    font-weight: 600;
    letter-spacing: 0.06em;
    line-height: 1.2;
    margin: 20px 0 12px 12px;
}
.sidebar-logo { display: flex; align-items: center; justify-content: flex-start; padding: 0 0 14px 2px; }
.sidebar-logo img { width: 100%; max-width: 160px; height: auto; }
/* logo sits in the top row; the collapse arrow stays at the right of that row */
section[data-testid="stSidebar"] [data-testid="stSidebarHeader"] { height: 0; min-height: 0; padding: 0; margin: 0; }
section[data-testid="stSidebar"] [data-testid="stSidebarCollapseButton"] { position: absolute; top: 0.9rem; right: 0.75rem; }

/* ---- Top bar ---- */
.st-key-topbar {
    background: #FFFFFF;
    width: calc(100% + 4rem);
    max-width: none;
    margin: 0 -2rem 0.75rem -2rem;
    padding: 0.8rem 2rem;
    box-shadow: 0 1px 5px rgba(15, 23, 42, 0.10);
}
.st-key-topbar div[data-baseweb="input"],
.st-key-topbar div[data-baseweb="base-input"] {
    background: #FFFFFF !important;
    border-radius: 999px !important;
}
.st-key-topbar div[data-baseweb="input"] { border: 1px solid #D5DAE1 !important; }
.st-key-topbar input {
    font-size: 12.5px;
    padding-right: 42px !important;
    background: transparent url("__SEARCH_ICON__") no-repeat right 14px center !important;
    background-size: 16px !important;
}
.topbar-right { display: flex; align-items: center; justify-content: flex-end; gap: 14px; }
.bell {
    width: 34px; height: 34px; border-radius: 50%;
    background: #FFFFFF; border: 1px solid #E5E7EB;
    box-shadow: 0 1px 3px rgba(15, 23, 42, 0.12);
    display: flex; align-items: center; justify-content: center;
}
.bell img { width: 16px; height: 16px; }
.avatar {
    width: 34px; height: 34px; border-radius: 50%;
    background: linear-gradient(180deg, #3B8FE8, #1565C0);
    color: #FFFFFF; font-size: 12px; font-weight: 700;
    display: flex; align-items: center; justify-content: center;
}
.user-name { font-size: 12px; font-weight: 600; color: #111827; }
.user-chevron { color: #6B7280; font-size: 11px; }

/* ---- Breadcrumb + headings ---- */
.breadcrumb { font-size: 11px; font-weight: 600; color: #6B7280; margin: 8px 0 14px 2px; }
.breadcrumb b { color: #111827; }
.breadcrumb span { margin: 0 6px; color: #9CA3AF; }
.section-title { font-size: 12px; font-weight: 700; color: #6B7280; margin: 20px 0 8px 2px; }
.page-title { font-size: 22px; font-weight: 700; color: #1C2430; margin: 0 0 4px 0; }
.page-sub { font-size: 13.5px; color: #6B7686; margin: 0 0 22px 0; }

/* ---- Stat cards ---- */
.stat-card {
    background: #FFFFFF;
    border-radius: 8px;
    padding: 16px 18px 12px 18px;
    box-shadow: 0 2px 8px rgba(15, 23, 42, 0.16);
    min-height: 118px;
}
.stat-icon {
    width: 22px; height: 22px; border-radius: 5px;
    display: flex; align-items: center; justify-content: center;
    margin-bottom: 8px;
}
.stat-icon img { width: 14px; height: 14px; }
.stat-label { color: #8A8F98; font-size: 12.5px; font-weight: 700; }
.stat-label span { font-weight: 400; }
.stat-value { font-size: 36px; font-weight: 400; color: #111827; line-height: 1.1; }

/* ---- Dashboard panels (st.container with key) ---- */
.st-key-activity_panel, .st-key-room_panel {
    background: #FFFFFF;
    border-radius: 10px;
    padding: 16px 20px 20px 20px;
    box-shadow: 0 1px 6px rgba(15, 23, 42, 0.10);
}
[data-testid="stMain"] .stButton button {
    background: #FFFFFF;
    border: 1px solid #E5E7EB;
    border-radius: 999px;
    box-shadow: 0 1px 3px rgba(15, 23, 42, 0.18);
    color: #111827;
    font-size: 11.5px;
    font-weight: 600;
    min-height: 2rem;
    padding: 0.2rem 1rem;
}
[data-testid="stMain"] .stButton button:hover { border-color: #1E6FD9; color: #1E6FD9; }
.st-key-view_reports, .st-key-view_inventory { display: flex; justify-content: flex-end; }
.st-key-activity_panel [data-baseweb="select"] > div,
.st-key-room_panel [data-baseweb="select"] > div {
    min-height: 2rem; font-size: 12px; border-radius: 6px;
}

/* ---- Recent activity ---- */
.legend { display: flex; gap: 16px; align-items: center; font-size: 9.5px; color: #4B5563; }
.dot { width: 6px; height: 6px; border-radius: 50%; display: inline-block; margin-right: 5px; }
.act-card {
    display: flex; justify-content: space-between; align-items: flex-start;
    background: #FFFFFF;
    border-left: 4px solid #9CA3AF;
    border-radius: 4px;
    box-shadow: 0 1px 5px rgba(15, 23, 42, 0.18);
    padding: 12px 16px;
    margin-top: 12px;
}
.act-card.resolved { border-left-color: #1E9E5A; }
.act-card.progress { border-left-color: #F5C06F; }
.act-card.followup { border-left-color: #B3261E; }
.act-title { font-size: 15px; font-weight: 600; color: #111827; }
.act-issue { font-size: 11px; color: #6B7280; margin-top: 1px; }
.act-issue b { color: #2563EB; font-weight: 500; }
.chip {
    display: inline-block; background: #EEF0F3; color: #374151;
    border-radius: 999px; padding: 2px 10px; font-size: 10px; margin: 6px 6px 0 0;
}
.act-right { text-align: right; flex-shrink: 0; margin-left: 16px; }
.act-dt-label { font-size: 9.5px; color: #9CA3AF; }
.act-dt { font-size: 10.5px; color: #6B7280; }
.empty { color: #9CA3AF; font-size: 13px; padding: 24px 0; text-align: center; }

/* ---- Room at glance ---- */
.rg-label { font-size: 10px; color: #6B7280; white-space: nowrap; }
.rg-divider { border-top: 1px solid #6B7280; margin: 8px 0 20px 0; }
.rg-monitor { text-align: center; }
.rg-monitor img { width: 110px; height: auto; }
.rg-monitor div { font-size: 11px; font-weight: 600; color: #111827; line-height: 1.3; margin-top: 10px; }
.chart { padding-right: 14px; }
.chart-plot {
    height: 150px;
    border-left: 1px solid #374151; border-bottom: 1px solid #374151;
    display: flex; flex-direction: column; justify-content: space-around;
    padding: 6px 0;
}
.bar { height: 28px; }
.chart-axis { position: relative; height: 18px; margin-top: 3px; }
.chart-axis span {
    position: absolute; transform: translateX(-50%);
    font-size: 10px; color: #4B5563;
}
.rg-total { text-align: right; font-size: 11px; color: #374151; }
.rg-total b { font-size: 32px; font-weight: 400; color: #111827; margin-left: 6px; vertical-align: middle; }
.rg-legend {
    border: 1px solid #E5E7EB; border-radius: 4px;
    box-shadow: 0 1px 5px rgba(15, 23, 42, 0.18);
    padding: 8px 12px 2px 12px; margin-top: 8px;
}
.rg-legend-item { font-size: 10px; color: #374151; margin-bottom: 8px; }
.rg-legend-item b { display: block; font-size: 20px; font-weight: 400; color: #111827; }

/* =====================================================================
   Pages from the HTML prototype (Report, My Reports, Unit Inventory)
   ===================================================================== */
[data-testid="stMain"] [data-testid="stWidgetLabel"] p {
    font-size: 13px; font-weight: 600; color: #3A4453;
}
.field-label { font-size: 13px; font-weight: 600; color: #3A4453; margin: 4px 0 6px 0; }
.field-label span { font-weight: 400; color: #A4ADBA; }

.pcard {
    background: #FFFFFF; border: 1px solid #E4E8EE; border-radius: 10px;
    box-shadow: 0 1px 2px rgba(28, 36, 48, .06), 0 1px 1px rgba(28, 36, 48, .04);
}
.st-key-form_card, .st-key-review_card, .st-key-done_card {
    background: #FFFFFF; border: 1px solid #E4E8EE; border-radius: 10px;
    box-shadow: 0 1px 2px rgba(28, 36, 48, .06), 0 1px 1px rgba(28, 36, 48, .04);
    padding: 26px; max-width: 680px;
}
.st-key-done_card { max-width: 560px; text-align: center; padding: 40px 30px; }
.st-key-done_card .stButton { display: flex; justify-content: center; }

/* Buttons on the prototype pages: 8px radius, flat, full width of their column */
.st-key-form_card .stButton, .st-key-review_card .stButton { width: 100%; }
.st-key-form_card .stButton button, .st-key-review_card .stButton button,
.st-key-done_card .stButton button, .st-key-back_inv button {
    width: 100%; border-radius: 8px; box-shadow: none;
    font-size: 13.5px; min-height: 2.5rem; padding: 0.4rem 1rem;
}
.st-key-done_card .stButton button { width: auto; }
[data-testid="stMain"] .stButton button[data-testid="stBaseButton-primary"],
[data-testid="stMain"] .stButton button[kind="primary"] {
    background: #2F6FE4; border-color: #2F6FE4; color: #FFFFFF;
}
[data-testid="stMain"] .stButton button[data-testid="stBaseButton-primary"]:hover,
[data-testid="stMain"] .stButton button[kind="primary"]:hover { background: #2555B8; border-color: #2555B8; }
[data-testid="stMain"] .stButton button[data-testid="stBaseButton-primary"]:disabled,
[data-testid="stMain"] .stButton button[kind="primary"]:disabled { background: #C6D4EF; border-color: #C6D4EF; }
[data-testid="stMain"] .stButton button[data-testid="stBaseButton-primary"] *,
[data-testid="stMain"] .stButton button[kind="primary"] * { color: #FFFFFF !important; }
.st-key-discard_2 button { color: #D5474F; }
.st-key-back_inv button {
    background: transparent !important; border: none !important; width: auto;
    color: #2F6FE4 !important; font-weight: 600; padding-left: 0;
}

.form-rule { border-top: 1px solid #E4E8EE; margin: 18px 0 16px 0; }

/* Wizard */
.wizard-steps { display: flex; align-items: center; margin-bottom: 22px; }
.wz-step { display: flex; align-items: center; gap: 9px; }
.wz-num {
    width: 26px; height: 26px; border-radius: 50%; background: #F3F5F9; border: 1px solid #E4E8EE;
    display: flex; align-items: center; justify-content: center;
    font-size: 12px; font-weight: 700; color: #6B7686; flex: 0 0 26px;
}
.wz-step.done .wz-num { background: #1F9D6F; border-color: #1F9D6F; color: #fff; }
.wz-step.current .wz-num { background: #2F6FE4; border-color: #2F6FE4; color: #fff; }
.wz-label { font-size: 13px; font-weight: 600; color: #6B7686; }
.wz-step.current .wz-label, .wz-step.done .wz-label { color: #1C2430; }
.wz-line { width: 56px; height: 1px; background: #E4E8EE; margin: 0 10px; }

/* Review + confirmation */
.review-row { display: flex; justify-content: space-between; padding: 12px 0; border-bottom: 1px solid #E4E8EE; gap: 20px; }
.review-row:last-of-type { border-bottom: none; }
.review-label { font-size: 12.5px; color: #6B7686; font-weight: 600; flex: 0 0 150px; }
.review-value { font-size: 13.5px; color: #1C2430; text-align: right; flex: 1; }
.review-chips { display: flex; flex-wrap: wrap; gap: 6px; justify-content: flex-end; }
.review-note {
    background: #F4F8FF; border: 1px solid #EAF2FF; border-radius: 8px; padding: 12px 14px;
    font-size: 12.5px; color: #2555B8; margin: 18px 0 4px 0;
}
.confirm-icon {
    width: 56px; height: 56px; border-radius: 50%; background: #E7F7F0; color: #1F9D6F;
    display: flex; align-items: center; justify-content: center; margin: 0 auto 18px auto;
}
.confirm-id { font-family: ui-monospace, monospace; background: #F3F5F9; border-radius: 6px; padding: 3px 9px; font-size: 13px; color: #3A4453; }
.confirm-title { margin: 0 0 8px 0; font-size: 19px; font-weight: 700; color: #1C2430; }
.confirm-text { color: #6B7686; font-size: 13.5px; margin: 0 0 18px 0; }

/* Pills / tags */
.pill { display: inline-flex; align-items: center; font-size: 12px; font-weight: 600; padding: 4px 10px; border-radius: 100px; }
.pill.green { background: #E7F7F0; color: #1F9D6F; }
.pill.amber { background: #FDF1DE; color: #D98B1C; }
.pill.red { background: #FBE9EA; color: #D5474F; }
.issue-tag {
    display: inline-block; background: #F3F5F9; border: 1px solid #E4E8EE; border-radius: 6px;
    padding: 2px 8px; font-size: 11.5px; color: #3A4453;
}

/* My Reports */
.st-key-reports_search input {
    padding-left: 34px !important;
    background: transparent url("__SEARCH_ICON__") no-repeat left 11px center !important;
    background-size: 15px !important;
}
.count-badge { font-size: 13px; color: #6B7686; text-align: right; }
.count-badge b { color: #1C2430; }
.sortby-label { font-size: 13px; color: #6B7686; text-align: right; white-space: nowrap; }
table.reports-table { width: 100%; border-collapse: collapse; font-size: 13.5px; }
table.reports-table th {
    text-align: left; font-size: 11.5px; letter-spacing: .03em; color: #6B7686;
    padding: 12px 16px; border-bottom: 1px solid #E4E8EE; font-weight: 700;
}
table.reports-table td { padding: 14px 16px; border-bottom: 1px solid #E4E8EE; vertical-align: top; color: #3A4453; }
table.reports-table tr:last-child td { border-bottom: none; }
table.reports-table tbody tr:hover { background: #F4F8FF; }
.rep-id { font-family: ui-monospace, monospace; font-size: 12.5px; color: #6B7686; }
.rep-unit { font-weight: 600; color: #1C2430; }
.issue-tags { display: flex; flex-wrap: wrap; gap: 5px; max-width: 220px; }
.empty-state { padding: 60px 20px; text-align: center; color: #6B7686; }

/* Unit Inventory */
.inv-count { font-size: 13px; color: #6B7686; }
.inv-count b { color: #1C2430; }
.st-key-inv_filter { display: flex; justify-content: flex-end; }
[data-testid="stMain"] [class*="st-key-unit_"] { width: 100%; }
[data-testid="stMain"] [class*="st-key-unit_"] .stButton { width: 100%; }
[data-testid="stMain"] [class*="st-key-unit_"] button {
    position: relative; width: 100%; flex-direction: column; gap: 6px;
    height: auto; min-height: 92px; padding: 16px 8px 12px 8px;
    border-radius: 10px; background: #FFFFFF; border: 1px solid #E4E8EE; box-shadow: none;
}
[data-testid="stMain"] [class*="st-key-unit_"] button * { font-size: 13px; font-weight: 600; color: #1C2430 !important; }
[data-testid="stMain"] [class*="st-key-unit_"] button::before {
    content: ""; display: block; width: 34px; height: 34px;
    background: url("__UNIT_ICON__") center / contain no-repeat;
}
[data-testid="stMain"] [class*="st-key-unit_"] button:hover {
    border-color: #4A84EE; box-shadow: 0 1px 2px rgba(28, 36, 48, .06);
}

/* Unit detail */
.unit-title-row { display: flex; align-items: center; gap: 12px; }
.unit-title-row h1 { font-size: 21px; margin: 0; padding: 0; color: #1C2430; }
.unit-sub { color: #6B7686; font-size: 13px; margin: 6px 0 16px 0; }
table.spec-table { width: 100%; border-collapse: collapse; }
table.spec-table td { padding: 11px 4px; border-bottom: 1px solid #E4E8EE; font-size: 13.5px; }
table.spec-table tr:last-child td { border-bottom: none; }
.spec-key { color: #6B7686; width: 42%; }
.spec-val { color: #1C2430; font-weight: 600; text-align: right; }
.sw-list { list-style: none; margin: 0; padding: 0; }
.sw-list li { display: flex; justify-content: space-between; padding: 10px 2px; border-bottom: 1px solid #E4E8EE; font-size: 13.5px; }
.sw-list li:last-child { border-bottom: none; }
.sw-name { color: #1C2430; font-weight: 500; }
.sw-meta { color: #A4ADBA; font-size: 12px; }
.history-item { display: flex; gap: 14px; padding: 16px 0; border-bottom: 1px solid #E4E8EE; }
.history-item:last-child { border-bottom: none; }
.history-rail { flex: 0 0 12px; padding-top: 5px; }
.history-dot { width: 9px; height: 9px; border-radius: 50%; }
.history-body { flex: 1; }
.history-top { display: flex; justify-content: space-between; gap: 10px; margin-bottom: 4px; }
.history-issue { font-size: 13.5px; font-weight: 600; color: #1C2430; }
.history-date { font-size: 12px; color: #A4ADBA; white-space: nowrap; }
.history-comment { font-size: 13px; color: #6B7686; margin: 4px 0; font-style: italic; }
.history-action { font-size: 13px; color: #3A4453; background: #F3F5F9; border-radius: 7px; padding: 8px 10px; margin-top: 6px; }
.history-action b { color: #1C2430; }
.side-card { padding: 18px; margin-bottom: 16px; }
.side-card h4 { margin: 0 0 12px 0; font-size: 13px; text-transform: uppercase; letter-spacing: .03em; color: #6B7686; }
.issue-count-big { font-size: 30px; font-weight: 700; color: #1C2430; }
.issue-count-label { font-size: 12.5px; color: #6B7686; }

/* =====================================================================
   Settings
   ===================================================================== */
.st-key-settings_card, .st-key-profile_card, .st-key-notif_card, .st-key-security_card {
    background: #FFFFFF; border-radius: 10px; padding: 22px 24px; max-width: 520px;
    box-shadow: 0 1px 3px rgba(28, 36, 48, .10);
}
.st-key-settings_card { padding: 8px 22px; gap: 0; }
.card-title { font-size: 15px; font-weight: 700; color: #111827; }
.card-sub { font-size: 11.5px; color: #9CA3AF; margin: 2px 0 12px 0; }
.rule { border-top: 1px solid #E5E7EB; margin: 2px 0 8px 0; }

/* Settings list rows */
[data-testid="stMain"] .st-key-settings_card .stButton { width: 100%; }
[data-testid="stMain"] .st-key-settings_card .stButton button {
    width: 100%; justify-content: flex-start; gap: 10px;
    background: transparent; border: none; border-bottom: 1px solid #DDE1E7; border-radius: 0; box-shadow: none;
    padding: 13px 2px; min-height: 0; font-size: 13px; font-weight: 500; color: #4B5563;
}
[data-testid="stMain"] .st-key-settings_card .stButton button > div { justify-content: flex-start; }
[data-testid="stMain"] .st-key-settings_card .stButton button:hover { background: #F7F9FC; color: #111827; border-color: #DDE1E7; }
.st-key-settings_card button::before {
    content: ""; width: 18px; height: 18px; flex: 0 0 18px;
    background-size: contain; background-repeat: no-repeat; background-position: center;
}
.st-key-set_profile button::before { background-image: url("__ICON_PROFILE__"); }
.st-key-set_notifications button::before { background-image: url("__ICON_NOTIF__"); }
.st-key-set_security button::before { background-image: url("__ICON_SECURITY__"); }

/* Logout */
.st-key-logout { max-width: 520px; margin-top: 6px; }
.st-key-logout .stButton { width: 100%; }
[data-testid="stMain"] .st-key-logout .stButton button {
    width: 100%; background: linear-gradient(90deg, #BFC0C2, #575859); border: none; border-radius: 8px;
    box-shadow: none; font-size: 12.5px; font-weight: 700; min-height: 2.3rem;
}
[data-testid="stMain"] .st-key-logout .stButton button * { color: #FFFFFF !important; }

/* Profile */
.avatar-img { border-radius: 50%; object-fit: cover; display: block; }
.photo-hint { font-size: 10.5px; color: #9CA3AF; margin-top: 4px; }
.prof-label { font-size: 11.5px; color: #4B5563; font-weight: 600; margin-top: 14px; }
.prof-name { font-size: 12.5px; color: #9CA3AF; border-bottom: 1px solid #DDE1E7; padding: 6px 0 8px 0; }
.prof-contact { display: flex; align-items: center; gap: 8px; font-size: 12.5px; color: #111827; padding: 5px 0; }
.prof-contact img { width: 13px; height: 13px; opacity: .7; }
[data-testid="stMain"] [data-testid="stPopover"] button {
    border-radius: 6px; font-size: 11.5px; min-height: 1.9rem; padding: 0.15rem 0.8rem; box-shadow: none;
}
[data-testid="stMain"] .st-key-edit_contact button, [data-testid="stMain"] .st-key-forgot button {
    background: transparent; border: none; box-shadow: none; min-height: 0; width: auto;
    padding: 2px 0; font-size: 11.5px; font-weight: 600;
}
[data-testid="stMain"] .st-key-edit_contact button *, [data-testid="stMain"] .st-key-forgot button * { color: #2F6FE4 !important; }
[data-testid="stMain"] .st-key-edit_contact button:hover, [data-testid="stMain"] .st-key-forgot button:hover { background: transparent; }

/* Notification toggles */
.notif-title { font-size: 13px; font-weight: 600; color: #1F2937; }
.notif-desc { font-size: 11px; color: #9CA3AF; margin-top: 1px; }
.st-key-notif_card [class*="st-key-n_"] { display: flex; justify-content: flex-end; }

/* Password */
.pw-hint { font-size: 10.5px; color: #9CA3AF; margin: -6px 0 6px 0; }
.st-key-change_pw { margin-top: 6px; }
.st-key-change_pw .stButton { width: 100%; }
[data-testid="stMain"] .st-key-change_pw .stButton button { width: 100%; border-radius: 999px; min-height: 2.3rem; font-size: 12.5px; }

/* Signed-out screen */
.st-key-signed_out_card {
    background: #FFFFFF; border: 1px solid #E4E8EE; border-radius: 10px; padding: 36px 30px;
    text-align: center; margin-top: 12vh; box-shadow: 0 1px 3px rgba(28, 36, 48, .10);
}
.st-key-signed_out_card .stButton { display: flex; justify-content: center; }

/* full-width nav pills / settings rows (Streamlit wraps each keyed button in a shrink-to-fit container) */
section[data-testid="stSidebar"] [class*="st-key-nav_"] { width: 100%; }
.st-key-set_profile, .st-key-set_notifications, .st-key-set_security { width: 100%; }
.st-key-logout { width: 100%; }

/* visible borders for inputs sitting on white cards */
.st-key-form_card, .st-key-review_card, .st-key-profile_card, .st-key-security_card { --field-border: #D5DAE1; }
.st-key-form_card [data-testid="stTextInputRootElement"], .st-key-form_card [data-testid="stTextAreaRootElement"],
.st-key-form_card [data-baseweb="select"] > div, .st-key-form_card [data-testid="stSelectbox"] div:has(> input),
.st-key-profile_card [data-testid="stTextInputRootElement"], .st-key-security_card [data-testid="stTextInputRootElement"] {
    border: 1px solid #D5DAE1 !important; border-radius: 8px !important;
}
.st-key-change_pw { width: 100%; }
[data-testid="stMain"] [data-testid="stPopover"] button * { font-size: 11.5px; }
.photo-hint { margin-top: -6px; }
</style>
"""
st.markdown(
    CSS.replace("__SEARCH_ICON__", icon_uri(ICON_PATHS["search"], "#6B7280")).replace("__UNIT_ICON__", UNIT_ICON)
       .replace("__ICON_PROFILE__", SET_ICON_PROFILE).replace("__ICON_NOTIF__", SET_ICON_NOTIF)
       .replace("__ICON_SECURITY__", SET_ICON_SECURITY),
    unsafe_allow_html=True,
)


# ---------- Unit data ----------
CL1_STATUS = {2: "issue", 10: "issue", 12: "issue", 15: "replace"}


def status_for(room: str, num: int) -> str:
    """good / issue / replace for a unit. CL 1 matches the mockup; other rooms are fixed pseudo-data."""
    if room == "CL 1":
        return CL1_STATUS.get(num, "good")
    seed = (ord(room[3]) + num * 7) % 23
    if seed == 3:
        return "issue"
    if seed == 11:
        return "replace"
    return "good"


def room_counts(room: str) -> dict:
    statuses = [status_for(room, n) for n in range(1, UNIT_COUNTS[room] + 1)]
    return {
        "units": len(statuses),
        "good": statuses.count("good"),
        "issues": statuses.count("issue"),
        "replace": statuses.count("replace"),
    }


BASE_HW = {"Processor": "Intel Core i3-10100 @ 3.60GHz", "RAM": "8 GB DDR4", "Storage": "256 GB SSD",
           "GPU": "Intel UHD 630", "Monitor": '19" LED', "Peripherals": "Keyboard, Mouse"}
BASE_LIFE = {"Deployed": "June 2023", "Warranty": "Expired Jun 2025", "Age": "3 yrs 3 mo", "Flag": "None"}
DOMAIN = "CCSICT-LAB"
DONE_BY = "Resolved by J. Domingo"


def _detail(hw=None, software=(), system=None, life=None, history=()):
    return {
        "hardware": {**BASE_HW, **(hw or {})},
        "software": list(software),
        "system": system,
        "lifecycle": {**BASE_LIFE, **(life or {})},
        "history": list(history),
    }


UNIT_DETAILS = {
    "CL 1-02": _detail(
        hw={"Processor": "Intel Core i5-10400 @ 2.90GHz"},
        software=[("Windows 10 Pro", "Licensed — up to date"), ("Google Chrome", "v128 — up to date"),
                  ("Microsoft Office 2019", "Licensed"), ("VS Code", "v1.92"), ("Antivirus (Defender)", "Active")],
        system={"OS build": "19045.4780", "Last update check": "Aug 20, 2026", "Domain": DOMAIN,
                "Asset tag": "CL1-U02", "IP address": "192.168.14.32"},
        history=[
            {"date": "Aug 21, 2026 · 8:19 AM", "issue": "Slow performance",
             "comment": "Takes almost 5 minutes to boot and opens apps slowly.",
             "action": "Cleared temp files and disabled unnecessary startup apps. Ran disk cleanup.",
             "status": "progress", "by": "In progress"},
            {"date": "May 03, 2026 · 1:40 PM", "issue": "Slow performance", "comment": "Laggy during video playback.",
             "action": "Updated GPU driver and added 4GB RAM stick.", "status": "resolved", "by": DONE_BY},
            {"date": "Jan 14, 2026 · 10:02 AM", "issue": "Software error",
             "comment": "Office kept crashing when saving files.",
             "action": "Reinstalled Microsoft Office and applied latest patch.", "status": "resolved", "by": DONE_BY},
        ],
    ),
    "CL 1-10": _detail(
        hw={"Processor": "Intel Core i5-10400 @ 2.90GHz"},
        software=[("Windows 10 Pro", "Licensed — up to date"), ("Google Chrome", "v127 — update available"),
                  ("Microsoft Office 2019", "Licensed")],
        system={"OS build": "19045.4780", "Last update check": "Jul 30, 2026", "Domain": DOMAIN,
                "Asset tag": "CL1-U10", "IP address": "192.168.14.40"},
        history=[
            {"date": "Aug 18, 2026 · 11:09 AM", "issue": "No internet",
             "comment": "Ethernet connected but no internet access shown.",
             "action": "Checking network switch port — technician notified.", "status": "progress", "by": "In progress"},
            {"date": "Mar 02, 2026 · 9:15 AM", "issue": "No internet",
             "comment": "Same issue as before, keeps disconnecting.",
             "action": "Replaced LAN cable and reset network adapter.", "status": "resolved", "by": DONE_BY},
        ],
    ),
    "CL 1-12": _detail(
        software=[("Windows 10 Pro", "Licensed — up to date"), ("Google Chrome", "v128 — up to date")],
        system={"OS build": "19045.4780", "Last update check": "Aug 10, 2026", "Domain": DOMAIN,
                "Asset tag": "CL1-U12", "IP address": "192.168.14.42"},
        history=[
            {"date": "Jul 30, 2026 · 2:05 PM", "issue": "Missing mouse", "comment": "Mouse is gone from the unit.",
             "action": "Replacement mouse issued from stock.", "status": "resolved", "by": DONE_BY},
        ],
    ),
    "CL 1-15": _detail(
        hw={"Processor": "Intel Core i3-8100 @ 3.60GHz", "RAM": "4 GB DDR4", "Storage": "128 GB SSD",
            "Monitor": '19" LED (flickering)'},
        software=[("Windows 10 Pro", "Licensed — outdated"), ("Google Chrome", "v119 — outdated")],
        system={"OS build": "19044.3086", "Last update check": "Feb 2, 2026", "Domain": DOMAIN,
                "Asset tag": "CL1-U15", "IP address": "192.168.14.45"},
        life={"Deployed": "Jan 2020", "Warranty": "Expired Jan 2022", "Age": "6 yrs 8 mo", "Flag": "Needs replacement"},
        history=[
            {"date": "Jul 01, 2026 · 10:05 AM", "issue": "Won't turn on",
             "comment": "No response even when plugged directly to outlet.",
             "action": "Diagnosed failing PSU. 5th report on this unit — flagged for full inspection.",
             "status": "followup", "by": "Needs follow-up"},
            {"date": "Apr 22, 2026 · 9:00 AM", "issue": "Won't turn on",
             "comment": "Powers on then shuts off after a few seconds.",
             "action": "Cleaned dust from internals, reseated RAM.", "status": "resolved", "by": DONE_BY},
            {"date": "Feb 11, 2026 · 8:45 AM", "issue": "Slow performance", "comment": "Very slow to load anything.",
             "action": "Ran malware scan, cleared disk space.", "status": "resolved", "by": DONE_BY},
            {"date": "Nov 06, 2025 · 1:20 PM", "issue": "Monitor issue", "comment": "Screen flickers on and off.",
             "action": "Replaced VGA cable.", "status": "resolved", "by": DONE_BY},
            {"date": "Sep 15, 2025 · 10:30 AM", "issue": "Won't turn on", "comment": "Had to restart twice before it booted.",
             "action": "Checked power supply, temporary fix applied.", "status": "resolved", "by": DONE_BY},
        ],
    ),
}


def unit_detail(room: str, num: int, status: str) -> dict:
    known = UNIT_DETAILS.get(f"{room}-{num:02d}")
    if known:
        return known
    history = []
    if status != "good":
        replace = status == "replace"
        history = [{"date": "Jun 2026", "issue": "General issue", "comment": "",
                    "action": "Logged and pending review.",
                    "status": "followup" if replace else "progress",
                    "by": "Needs follow-up" if replace else "In progress"}]
    return _detail(
        software=[("Windows 10 Pro", "Licensed — up to date"), ("Google Chrome", "v128 — up to date"),
                  ("Microsoft Office 2019", "Licensed")],
        system={"OS build": "19045.4780", "Last update check": "Aug 2026", "Domain": DOMAIN,
                "Asset tag": f'{room.replace(" ", "")}-U{num:02d}', "IP address": f"192.168.14.{20 + num}"},
        life={"Flag": "Needs replacement" if status == "replace" else "None"},
        history=history,
    )


# ---------- Session state ----------
EMPTY_DRAFT = {"room": None, "unit": None, "sel": [], "other": "", "issues": [], "comment": "", "when": ""}

if "reports" not in st.session_state:
    st.session_state.reports = [
        {"id": "CL-1039", "room": "CL 1", "unit": "03", "issues": ["Won't turn on"], "status": "followup",
         "dt": datetime(2026, 7, 1, 10, 5)},
        {"id": "CL-1040", "room": "CL 2", "unit": "02", "issues": ["No internet"], "status": "progress",
         "dt": datetime(2026, 8, 18, 11, 9)},
        {"id": "CL-1041", "room": "CL 1", "unit": "02", "issues": ["Slow performance"], "status": "resolved",
         "dt": datetime(2026, 8, 21, 8, 19)},
    ]
if "report_counter" not in st.session_state:
    st.session_state.report_counter = 1041
if "page" not in st.session_state:
    st.session_state.page = "Home"
if "report_step" not in st.session_state:
    st.session_state.report_step = 1
if "draft" not in st.session_state:
    st.session_state.draft = dict(EMPTY_DRAFT)
if "inv_unit" not in st.session_state:
    st.session_state.inv_unit = None
if "settings_view" not in st.session_state:
    st.session_state.settings_view = "hub"
if "logged_out" not in st.session_state:
    st.session_state.logged_out = False
if "profile" not in st.session_state:
    st.session_state.profile = {"phone": "0983 765 6748", "email": "alwyna.lopez@isu.edu.ph"}
if "editing_contact" not in st.session_state:
    st.session_state.editing_contact = False
if "photo_uri" not in st.session_state:
    st.session_state.photo_uri = None
    st.session_state.photo_id = None
if "notif" not in st.session_state:
    st.session_state.notif = {"status": True, "followup": True, "email": False, "weekly": False}
if "pw_updated" not in st.session_state:
    st.session_state.pw_updated = date(2025, 7, 1)


# ---------- Helpers ----------
def room_name(code: str) -> str:
    return f"Centrum Laboratory {code.split()[1]}"


def clock(dt: datetime) -> str:
    return dt.strftime("%I:%M %p").lstrip("0")


def format_when(dt: datetime) -> str:
    """Dashboard style: August 21, 2026 | 8:19 AM"""
    return f'{dt.strftime("%B")} {dt.day}, {dt.year} | {clock(dt)}'


def format_short(dt: datetime) -> str:
    """Table / review style: Aug 21, 2026 · 8:19 AM"""
    return f'{dt.strftime("%b %d, %Y")} · {clock(dt)}'


def page_header(title: str, sub: str | None = None):
    html = f'<div class="page-title">{escape(title)}</div>'
    if sub:
        html += f'<div class="page-sub">{escape(sub)}</div>'
    st.markdown(html, unsafe_allow_html=True)


def avatar_html(size: int = 34) -> str:
    """Round avatar: the uploaded photo if there is one, otherwise the user's initials."""
    photo = st.session_state.get("photo_uri")
    if photo:
        return f'<img class="avatar-img" src="{photo}" style="width:{size}px;height:{size}px;" alt="">'
    return (f'<div class="avatar" style="width:{size}px;height:{size}px;font-size:{round(size * 0.36)}px;">'
            f'{USER_INITIALS}</div>')


def issue_tags(issues) -> str:
    return "".join(f'<span class="issue-tag">{escape(i)}</span>' for i in issues)


def report_card(r: dict) -> str:
    chips = "".join(f'<span class="chip">{escape(i)}</span>' for i in r["issues"])
    return (
        f'<div class="act-card {r["status"]}">'
        '<div style="flex:1;">'
        f'<div class="act-title">{escape(r["room"])} - Unit {escape(r["unit"])}</div>'
        f'<div class="act-issue">Issue: <b>{len(r["issues"])}</b></div>'
        f'<div>{chips}</div>'
        '</div>'
        '<div class="act-right">'
        '<div class="act-dt-label">Date &amp; Time:</div>'
        f'<div class="act-dt">{format_when(r["dt"])}</div>'
        '</div></div>'
    )


def stat_card(label_html: str, value: int, icon: str, fg: str, bg: str) -> str:
    return (
        '<div class="stat-card">'
        f'<div class="stat-icon" style="background:{bg};"><img src="{icon_uri(ICON_PATHS[icon], fg)}" alt=""></div>'
        f'<div class="stat-label">{label_html}</div>'
        f'<div class="stat-value">{value}</div>'
        '</div>'
    )


def spec_table(data: dict) -> str:
    rows = "".join(
        f'<tr><td class="spec-key">{escape(k)}</td><td class="spec-val">{escape(v)}</td></tr>'
        for k, v in data.items()
    )
    return f'<table class="spec-table">{rows}</table>'


def wizard_html(step: int) -> str:
    labels = ["Describe the issue", "Review", "Done"]
    parts = []
    for i, label in enumerate(labels, 1):
        cls = "done" if i < step else ("current" if i == step else "")
        parts.append(f'<div class="wz-step {cls}"><div class="wz-num">{i}</div><div class="wz-label">{label}</div></div>')
    return '<div class="wizard-steps">' + '<div class="wz-line"></div>'.join(parts) + '</div>'


# ---------- Callbacks ----------
def go(page: str):
    st.session_state.page = page
    if page == "Inventory":
        st.session_state.inv_unit = None
    if page == "Settings":
        st.session_state.settings_view = "hub"
        st.session_state.editing_contact = False


def open_inventory(room: str):
    st.session_state.inv_room = room
    go("Inventory")


def open_unit(room: str, num: int):
    st.session_state.inv_unit = (room, num)


def close_unit():
    st.session_state.inv_unit = None


def reset_report():
    st.session_state.draft = dict(EMPTY_DRAFT)
    st.session_state.report_step = 1


def go_review():
    ss = st.session_state
    room = ss.get("f_room")
    unit = ss.get(f"f_unit_{room}")
    sel = list(ss.get("f_issues") or [])
    other = ss.get("f_other", "") if "Other" in sel else ""
    issues = [i for i in sel if i != "Other"]
    if "Other" in sel:
        issues += [s.strip() for s in other.split(",") if s.strip()]
    ss.draft = {"room": room, "unit": unit, "sel": sel, "other": other, "issues": issues,
                "comment": (ss.get("f_comment") or "").strip(), "when": format_short(datetime.now())}
    ss.report_step = 2


def back_to_edit():
    st.session_state.report_step = 1


def submit_report():
    ss = st.session_state
    d = ss.draft
    ss.report_counter += 1
    rid = f"CL-{ss.report_counter}"
    ss.reports.insert(0, {"id": rid, "room": d["room"], "unit": d["unit"], "issues": d["issues"],
                          "status": "progress", "dt": datetime.now()})
    ss.last_report_id = rid
    ss.toast_msg = f"Report {rid} submitted"
    ss.draft = dict(EMPTY_DRAFT)
    ss.report_step = 3


# ----- Settings callbacks -----
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^[0-9+()\-\s]{7,20}$")


def open_settings(view: str):
    st.session_state.settings_view = view
    st.session_state.editing_contact = False


def logout():
    st.session_state.logged_out = True


def login():
    st.session_state.logged_out = False
    go("Home")


def set_editing(value: bool):
    st.session_state.editing_contact = value
    st.session_state.pop("profile_error", None)


def save_contact():
    ss = st.session_state
    phone = (ss.get("pf_phone") or "").strip()
    email = (ss.get("pf_email") or "").strip()
    if not PHONE_RE.match(phone):
        ss.profile_error = "Enter a valid phone number."
    elif not EMAIL_RE.match(email):
        ss.profile_error = "Enter a valid email address."
    else:
        ss.profile = {"phone": phone, "email": email}
        ss.editing_contact = False
        ss.pop("profile_error", None)
        ss.toast_msg = "Contact info updated"


def remove_photo():
    ss = st.session_state
    current = ss.get("photo_upload")
    ss.photo_uri = None
    ss.photo_id = getattr(current, "file_id", None)  # so the uploader doesn't re-add it


def set_notif(key: str):
    st.session_state.notif[key] = st.session_state[f"n_{key}"]


def forgot_password():
    st.session_state.toast_msg = f'Reset link sent to {st.session_state.profile["email"]}'


def change_password():
    ss = st.session_state
    cur, new, conf = ss.get("pw_cur", ""), ss.get("pw_new", ""), ss.get("pw_conf", "")
    if not cur:
        ss.pw_msg = ("error", "Enter your current password.")
    elif len(new) < 8:
        ss.pw_msg = ("error", "The new password must be at least 8 characters.")
    elif new == cur:
        ss.pw_msg = ("error", "The new password must be different from the current one.")
    elif new != conf:
        ss.pw_msg = ("error", "The new passwords don't match.")
    else:
        ss.pw_updated = date.today()
        ss.pw_cur = ss.pw_new = ss.pw_conf = ""
        ss.pw_msg = ("success", "Password updated.")


# ---------- Signed-out screen ----------
if st.session_state.logged_out:
    st.markdown(
        "<style>section[data-testid='stSidebar'], header[data-testid='stHeader'], "
        "[data-testid='stSidebarCollapsedControl'] { display: none !important; }</style>",
        unsafe_allow_html=True,
    )
    _, mid_col, _ = st.columns([1, 1.2, 1])
    with mid_col:
        with st.container(key="signed_out_card"):
            st.markdown(
                f'<img src="{LOGO_URI}" alt="Centrum Laboratory" style="width:190px;display:block;margin:0 auto 22px auto;">'
                "<div class='confirm-title'>You've been logged out</div>"
                "<div class='confirm-text'>See you next time.</div>",
                unsafe_allow_html=True,
            )
            st.button("Log back in", key="login", type="primary", on_click=login)
    st.stop()


# ---------- Sidebar navigation ----------
NAV = [
    ("OVERVIEW", [("Home", "speed", "Dashboard")]),
    ("REPORTING", [("Report", "add", "Report an Issue"), ("Reports", "assignment", "My Reports")]),
    ("ASSETS", [("Inventory", "desktop_windows", "Unit Inventory")]),
    ("SYSTEM", [("Settings", "tune", "Settings")]),
]
BREADCRUMBS = {
    "Home": ("Overview", "Dashboard"),
    "Report": ("Reporting", "Report an Issue"),
    "Reports": ("Reporting", "My Reports"),
    "Inventory": ("Assets", "Unit Inventory"),
    "Settings": ("System", "Settings"),
}

with st.sidebar:
    st.markdown(
        f'<div class="sidebar-logo"><img src="{LOGO_URI}" alt="Centrum Laboratory"></div>',
        unsafe_allow_html=True,
    )
    for section, items in NAV:
        st.markdown(f'<div class="sidebar-section-label">{section}</div>', unsafe_allow_html=True)
        for page_key, icon, label in items:
            st.button(label, icon=f":material/{icon}:",
                      key=f"nav_{page_key}", on_click=go, args=(page_key,))

    # Highlight the active nav button (Streamlit adds .st-key-<key> to each keyed widget)
    st.markdown(
        f"""<style>
        .st-key-nav_{st.session_state.page} button {{
            background: linear-gradient(180deg, #3B8FE8, #1565C0) !important;
            color: #FFFFFF !important;
            font-weight: 600 !important;
            box-shadow: 0 2px 6px rgba(21, 101, 192, 0.35) !important;
        }}
        </style>""",
        unsafe_allow_html=True,
    )


# ---------- Top bar (search + notifications + user) ----------
with st.container(key="topbar"):
    search_col, _, user_col = st.columns([3, 4, 2.2], vertical_alignment="center")
    with search_col:
        st.text_input("Search", placeholder="Search reports, units, rooms...",
                      label_visibility="collapsed", key="search")
    with user_col:
        st.markdown(
            '<div class="topbar-right">'
            f'<div class="bell"><img src="{icon_uri(ICON_PATHS["bell"], "#374151")}" alt=""></div>'
            f'{avatar_html(34)}'
            f'<div class="user-name">{escape(USER_NAME)}</div>'
            '<div class="user-chevron">&#9013;</div>'
            '</div>',
            unsafe_allow_html=True,
        )

SETTINGS_TITLES = {"profile": "Profile", "notifications": "Notifications", "security": "Password &amp; Security"}
crumbs = list(BREADCRUMBS[st.session_state.page])
if st.session_state.page == "Settings" and st.session_state.settings_view != "hub":
    crumbs.append(SETTINGS_TITLES[st.session_state.settings_view])
crumbs_html = "<span>&rsaquo;</span>".join(crumbs[:-1] + [f"<b>{crumbs[-1]}</b>"])
st.markdown(f'<div class="breadcrumb">{crumbs_html}</div>', unsafe_allow_html=True)

toast_msg = st.session_state.pop("toast_msg", None)
if toast_msg:
    st.toast(toast_msg, icon="✅")

page = st.session_state.page

# =====================================================================
# DASHBOARD
# =====================================================================
if page == "Home":
    reports = st.session_state.reports

    total = len(reports)
    in_progress = sum(1 for r in reports if r["status"] == "progress")
    resolved = sum(1 for r in reports if r["status"] == "resolved")
    follow_up = sum(1 for r in reports if r["status"] == "followup")

    cards = [
        ("My Reports", total, "doc", "#2563EB", "#DBEAFE"),
        ('Being Fixed <span>(In progress)</span>', in_progress, "tool", "#2563EB", "#DBEAFE"),
        ("Resolved", resolved, "check", "#16A34A", "#DCFCE7"),
        ("Needs Follow-Up", follow_up, "folder", "#DC2626", "#FEE2E2"),
    ]
    for col, (label, value, icon, fg, bg) in zip(st.columns(4), cards):
        with col:
            st.markdown(stat_card(label, value, icon, fg, bg), unsafe_allow_html=True)

    # ----- Recent activity -----
    st.markdown('<div class="section-title">Recent Activity</div>', unsafe_allow_html=True)
    with st.container(key="activity_panel"):
        legend_col, year_col, btn_col = st.columns([6, 1.2, 1.8], vertical_alignment="center")
        with legend_col:
            st.markdown(
                '<div class="legend">'
                '<span><i class="dot" style="background:#1E9E5A;"></i>Resolved</span>'
                '<span><i class="dot" style="background:#F5C06F;"></i>In Progress</span>'
                '<span><i class="dot" style="background:#B3261E;"></i>Follow-Up</span>'
                '</div>',
                unsafe_allow_html=True,
            )
        with year_col:
            this_year = datetime.now().year
            # this year plus the previous five, and any older year that already has a report
            years = sorted({r["dt"].year for r in reports} | set(range(this_year - 5, this_year + 1)), reverse=True)
            year = st.selectbox("Year", years, label_visibility="collapsed", key="activity_year")
        with btn_col:
            st.button("View My Reports", key="view_reports", on_click=go, args=("Reports",))
 
        recent = sorted((r for r in reports if r["dt"].year == year),
                        key=lambda r: r["dt"], reverse=True)[:3]
        if recent:
            st.markdown("".join(report_card(r) for r in recent), unsafe_allow_html=True)
        else:
            st.markdown('<div class="empty">No reports for this year yet.</div>', unsafe_allow_html=True)
    # ----- Room at a glance -----
    st.markdown('<div class="section-title">Room at glance</div>', unsafe_allow_html=True)
    with st.container(key="room_panel"):
        label_col, select_col, _, inv_col = st.columns([0.9, 1.1, 5, 1.6], vertical_alignment="center")
        with label_col:
            st.markdown('<div class="rg-label">Select Room:</div>', unsafe_allow_html=True)
        with select_col:
            code = st.selectbox("Room", ROOMS, label_visibility="collapsed", key="glance_room")
        with inv_col:
            st.button("View Inventory", key="view_inventory", on_click=open_inventory, args=(code,))

        room = room_counts(code)
        st.markdown('<div class="rg-divider"></div>', unsafe_allow_html=True)

        monitor_col, chart_col, total_col = st.columns([1.3, 4, 1.7], vertical_alignment="center")

        with monitor_col:
            st.markdown(
                f'<div class="rg-monitor"><img src="{MONITOR_SVG}" alt="">'
                f'<div>Centrum<br>Laboratory {escape(code.split()[-1])}</div></div>',
                unsafe_allow_html=True,
            )

        with chart_col:
            axis_max = max(5, -(-room["units"] // 5) * 5)  # round up to a multiple of 5
            bars = [(room["good"], "#A9DCFB"), (room["issues"], "#1E88FF"), (room["replace"], "#0B4DA8")]
            bars_html = "".join(
                f'<div class="bar" style="width:{value / axis_max * 100:.2f}%; background:{color};"></div>'
                for value, color in bars
            )
            ticks_html = "".join(
                f'<span style="left:{t / axis_max * 100:.2f}%;">{t}</span>'
                for t in range(0, axis_max + 1, 5)
            )
            st.markdown(
                f'<div class="chart"><div class="chart-plot">{bars_html}</div>'
                f'<div class="chart-axis">{ticks_html}</div></div>',
                unsafe_allow_html=True,
            )

        with total_col:
            st.markdown(
                f'<div class="rg-total">Total Computers:<b>{room["units"]}</b></div>'
                '<div class="rg-legend">'
                f'<div class="rg-legend-item"><i class="dot" style="background:#A9DCFB;"></i>Good (working)<b>{room["good"]}</b></div>'
                f'<div class="rg-legend-item"><i class="dot" style="background:#1E88FF;"></i>Not Good (Have issue)<b>{room["issues"]}</b></div>'
                f'<div class="rg-legend-item"><i class="dot" style="background:#0B4DA8;"></i>Need for replacement<b>{room["replace"]}</b></div>'
                '</div>',
                unsafe_allow_html=True,
            )

# =====================================================================
# REPORT AN ISSUE  (3-step wizard: describe -> review -> done)
# =====================================================================
elif page == "Report":
    page_header("Report an Issue", "Tell us what's wrong — the technician gets notified right away.")

    step = st.session_state.report_step
    draft = st.session_state.draft
    st.markdown(wizard_html(step), unsafe_allow_html=True)

    # ----- Step 1: describe -----
    if step == 1:
        with st.container(key="form_card"):
            room_col, unit_col = st.columns(2)
            with room_col:
                room = st.selectbox(
                    "Room", ROOMS, index=ROOMS.index(draft["room"]) if draft["room"] else None,
                    placeholder="Select a room", format_func=room_name, key="f_room",
                )
            with unit_col:
                if room:
                    units = [f"{i:02d}" for i in range(1, UNIT_COUNTS[room] + 1)]
                    unit_index = units.index(draft["unit"]) if draft["room"] == room and draft["unit"] in units else None
                    unit = st.selectbox(
                        "Computer unit", units, index=unit_index, placeholder="Select a unit",
                        format_func=lambda u: f"Unit {u}", key=f"f_unit_{room}",
                    )
                else:
                    unit = None
                    st.selectbox("Computer unit", [], index=None, placeholder="Select a room first",
                                 disabled=True, key="f_unit_none")

            st.markdown('<div class="field-label">Issue type <span>(select all that apply)</span></div>',
                        unsafe_allow_html=True)
            selected = st.pills("Issue type", ISSUE_OPTIONS, selection_mode="multi", default=draft["sel"],
                                label_visibility="collapsed", key="f_issues") or []
            other_on = "Other" in selected
            other_text = ""
            if other_on:
                other_text = st.text_input("Describe the other issue(s)", value=draft["other"],
                                           placeholder="e.g. sticky spacebar, cracked casing", key="f_other")
                st.caption("Separate more than one with a comma.")

            st.text_area("Comment (optional)", value=draft["comment"], key="f_comment",
                         placeholder="Add any extra detail that could help the technician — when it started, "
                                     "what you were doing, etc.")
            st.caption("Your name and the date & time are added automatically when you submit.")

            has_issue = any(i != "Other" for i in selected) or (other_on and bool(other_text.strip()))
            valid = bool(room and unit and has_issue)

            st.markdown('<div class="form-rule"></div>', unsafe_allow_html=True)
            _, discard_col, review_col = st.columns([4, 1.1, 1.7])
            with discard_col:
                st.button("Discard", key="discard_1", on_click=reset_report)
            with review_col:
                st.button("Review report", key="to_review", type="primary", disabled=not valid, on_click=go_review)

    # ----- Step 2: review -----
    elif step == 2:
        with st.container(key="review_card"):
            rows = [
                ("Reported by", escape(USER_NAME)),
                ("Date &amp; time", escape(draft["when"])),
                ("Room", escape(room_name(draft["room"]))),
                ("Computer unit", f'Unit {escape(draft["unit"])}'),
                ("Issue type(s)", f'<div class="review-chips">{issue_tags(draft["issues"])}</div>'),
                ("Comment", escape(draft["comment"]) or "&mdash;"),
            ]
            st.markdown(
                "".join(
                    f'<div class="review-row"><div class="review-label">{k}</div><div class="review-value">{v}</div></div>'
                    for k, v in rows
                )
                + '<div class="review-note">Once submitted, this report can\'t be edited or deleted. '
                  'The technician will pick it up from here.</div>'
                  '<div class="form-rule"></div>',
                unsafe_allow_html=True,
            )
            _, discard_col, edit_col, confirm_col = st.columns([2, 1.1, 0.9, 1.9])
            with discard_col:
                st.button("Discard", key="discard_2", on_click=reset_report)
            with edit_col:
                st.button("Edit", key="edit", on_click=back_to_edit)
            with confirm_col:
                st.button("Confirm & submit", key="confirm", type="primary", on_click=submit_report)

    # ----- Step 3: done -----
    else:
        with st.container(key="done_card"):
            rid = escape(st.session_state.get("last_report_id", "CL-0000"))
            st.markdown(
                '<div class="confirm-icon"><svg width="26" height="26" viewBox="0 0 24 24" fill="none" '
                'stroke="currentColor" stroke-width="2.5"><path d="M20 6L9 17l-5-5"/></svg></div>'
                '<div class="confirm-title">Report submitted</div>'
                f'<div class="confirm-text">Report <span class="confirm-id">{rid}</span> is now in the '
                "technician's queue. You'll see its status update in My Reports.</div>",
                unsafe_allow_html=True,
            )
            again_col, view_col = st.columns(2)
            with again_col:
                st.button("Report another issue", key="again", on_click=reset_report)
            with view_col:
                st.button("View my reports", key="view_mine", type="primary", on_click=go, args=("Reports",))

# =====================================================================
# MY REPORTS
# =====================================================================
elif page == "Reports":
    page_header("My Reports", "Reports you've sent. You can track their status here — the technician handles the fix.")

    search_col, sort_label_col, sort_col, _, count_col = st.columns([2.4, 0.8, 1.5, 3, 1.2], vertical_alignment="center")
    with search_col:
        query = st.text_input("Search reports", placeholder="Search room, unit, or issue",
                              label_visibility="collapsed", key="reports_search").strip().lower()
    with sort_label_col:
        st.markdown('<div class="sortby-label">Sort by</div>', unsafe_allow_html=True)
    with sort_col:
        sort_by = st.selectbox("Sort by", ["Newest first", "Oldest first", "Status", "Room"],
                               label_visibility="collapsed", key="reports_sort")

    items = [r for r in st.session_state.reports
             if not query or query in f'{r["room"]} unit {r["unit"]} {" ".join(r["issues"])}'.lower()]
    if sort_by == "Newest first":
        items.sort(key=lambda r: r["dt"], reverse=True)
    elif sort_by == "Oldest first":
        items.sort(key=lambda r: r["dt"])
    elif sort_by == "Status":
        items.sort(key=lambda r: r["status"])
    else:
        items.sort(key=lambda r: r["room"])

    with count_col:
        st.markdown(f'<div class="count-badge"><b>{len(items)}</b> reports</div>', unsafe_allow_html=True)

    if items:
        body = "".join(
            '<tr>'
            f'<td class="rep-id">{escape(r["id"])}</td>'
            f'<td><div class="rep-unit">{escape(r["room"])} &mdash; Unit {escape(r["unit"])}</div></td>'
            f'<td><div class="issue-tags">{issue_tags(r["issues"])}</div></td>'
            f'<td><span class="pill {STATUS_META[r["status"]][1]}">{STATUS_META[r["status"]][0]}</span></td>'
            f'<td style="white-space:nowrap;color:#6B7686;">{format_short(r["dt"])}</td>'
            '</tr>'
            for r in items
        )
        st.markdown(
            '<div class="pcard" style="overflow:hidden;"><table class="reports-table"><thead><tr>'
            '<th>Report ID</th><th>Room / Unit</th><th>Issue type(s)</th><th>Status</th><th>Date &amp; time</th>'
            f'</tr></thead><tbody>{body}</tbody></table></div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown('<div class="pcard"><div class="empty-state">No reports match your search.</div></div>',
                    unsafe_allow_html=True)

# =====================================================================
# UNIT INVENTORY  (grid -> unit detail)
# =====================================================================
elif page == "Inventory":
    opened = st.session_state.inv_unit

    # ----- Grid view -----
    if opened is None:
        page_header("Unit Inventory", "Tap a unit to see its full hardware, software, and maintenance history.")

        if "inv_room" not in st.session_state:
            st.session_state.inv_room = "CL 1"
        st.segmented_control("Room", ROOMS, format_func=room_name, key="inv_room", label_visibility="collapsed")
        room = st.session_state.get("inv_room") or "CL 1"
        total = UNIT_COUNTS[room]

        count_col, filter_col = st.columns([1, 3], vertical_alignment="center")
        with count_col:
            st.markdown(f'<div class="inv-count"><b>{total}</b> computer(s)</div>', unsafe_allow_html=True)
        with filter_col:
            flt = st.radio("Filter", list(FILTER_LABELS), format_func=FILTER_LABELS.get, horizontal=True,
                           label_visibility="collapsed", key="inv_filter")

        # status dot on every non-good unit card
        dot_colors = {"issue": "#D98B1C", "replace": "#D5474F"}
        dot_css = "".join(
            f'.st-key-unit_{room.replace(" ", "")}_{n:02d} button::after{{content:"";position:absolute;'
            f'top:10px;right:10px;width:8px;height:8px;border-radius:50%;background:{dot_colors[status_for(room, n)]};}}'
            for n in range(1, total + 1) if status_for(room, n) != "good"
        )
        st.markdown(f"<style>{dot_css}</style>", unsafe_allow_html=True)

        units = [n for n in range(1, total + 1) if flt == "all" or status_for(room, n) == flt]
        if not units:
            st.markdown('<div class="empty">No units match this filter.</div>', unsafe_allow_html=True)
        for start in range(0, len(units), UNITS_PER_ROW):
            cols = st.columns(UNITS_PER_ROW)
            for col, n in zip(cols, units[start:start + UNITS_PER_ROW]):
                with col:
                    st.button(f"Unit {n:02d}", key=f'unit_{room.replace(" ", "")}_{n:02d}',
                              on_click=open_unit, args=(room, n))

    # ----- Unit detail view -----
    else:
        room, num = opened
        status = status_for(room, num)
        data = unit_detail(room, num, status)
        status_label, status_cls = UNIT_STATUS_META[status]

        st.button("Back to Unit Inventory", icon=":material/chevron_left:", key="back_inv", on_click=close_unit)
        st.markdown(
            f'<div class="unit-title-row"><h1>Unit {num:02d}</h1>'
            f'<span class="pill {status_cls}">{status_label}</span></div>'
            f'<div class="unit-sub">{escape(room_name(room))}</div>',
            unsafe_allow_html=True,
        )

        main_col, side_col = st.columns([2.6, 1])
        with main_col:
            tab_hw, tab_sw, tab_sys, tab_hist = st.tabs(["Hardware", "Software", "System", "Maintenance history"])
            with tab_hw:
                st.markdown(f'<div class="pcard" style="padding:22px;">{spec_table(data["hardware"])}</div>',
                            unsafe_allow_html=True)
            with tab_sw:
                items_html = "".join(
                    f'<li><span class="sw-name">{escape(n)}</span><span class="sw-meta">{escape(m)}</span></li>'
                    for n, m in data["software"]
                )
                st.markdown(f'<div class="pcard" style="padding:22px;"><ul class="sw-list">{items_html}</ul></div>',
                            unsafe_allow_html=True)
            with tab_sys:
                st.markdown(f'<div class="pcard" style="padding:22px;">{spec_table(data["system"])}</div>',
                            unsafe_allow_html=True)
            with tab_hist:
                dot = {"resolved": "#1F9D6F", "progress": "#D98B1C", "followup": "#D5474F"}
                if data["history"]:
                    hist_html = "".join(
                        '<div class="history-item">'
                        f'<div class="history-rail"><div class="history-dot" style="background:{dot[h["status"]]};"></div></div>'
                        '<div class="history-body">'
                        f'<div class="history-top"><div class="history-issue">{escape(h["issue"])}</div>'
                        f'<div class="history-date">{escape(h["date"])}</div></div>'
                        + (f'<div class="history-comment">&ldquo;{escape(h["comment"])}&rdquo;</div>' if h["comment"] else "")
                        + f'<div class="history-action"><b>{escape(h["by"])}:</b> {escape(h["action"])}</div>'
                        '</div></div>'
                        for h in data["history"]
                    )
                else:
                    hist_html = '<div class="empty" style="text-align:left;">No issues reported for this unit yet.</div>'
                st.markdown(f'<div class="pcard" style="padding:22px;">{hist_html}</div>', unsafe_allow_html=True)

        with side_col:
            st.markdown(
                '<div class="pcard side-card"><h4>Issues logged</h4>'
                f'<div class="issue-count-big">{len(data["history"])}</div>'
                '<div class="issue-count-label">total reports on this unit</div></div>'
                f'<div class="pcard side-card"><h4>Lifecycle</h4>{spec_table(data["lifecycle"])}</div>',
                unsafe_allow_html=True,
            )

# =====================================================================
# SETTINGS
# =====================================================================
elif page == "Settings":
    ss = st.session_state
    view = ss.settings_view

    # ----- Settings list -----
    if view == "hub":
        page_header("Settings")
        with st.container(key="settings_card"):
            st.button("Profile", key="set_profile", on_click=open_settings, args=("profile",))
            st.button("Notifications", key="set_notifications", on_click=open_settings, args=("notifications",))
            st.button("Password and Security", key="set_security", on_click=open_settings, args=("security",))
        st.button("Logout", key="logout", on_click=logout)

    # ----- Profile details -----
    elif view == "profile":
        p = ss.profile
        with st.container(key="profile_card"):
            st.markdown('<div class="card-title">Profile details</div>', unsafe_allow_html=True)

            avatar_col, photo_col = st.columns([1, 4], vertical_alignment="center")
            with avatar_col:
                st.markdown(avatar_html(52), unsafe_allow_html=True)
            with photo_col:
                with st.popover("Change photo"):
                    upload = st.file_uploader("Upload a photo", type=["jpg", "jpeg", "png"], key="photo_upload")
                    if upload is not None:
                        file_id = getattr(upload, "file_id", f"{upload.name}-{upload.size}")
                        if upload.size > 2 * 1024 * 1024:
                            st.error("That file is over 2MB. Choose a smaller one.")
                        elif file_id != ss.photo_id:
                            mime = "image/png" if upload.name.lower().endswith(".png") else "image/jpeg"
                            ss.photo_uri = f"data:{mime};base64," + base64.b64encode(upload.getvalue()).decode()
                            ss.photo_id = file_id
                            ss.toast_msg = "Profile photo updated"
                            st.rerun()
                    if ss.photo_uri:
                        st.button("Remove photo", key="rm_photo", on_click=remove_photo)
                st.markdown('<div class="photo-hint">JPG or PNG, up to 2MB</div>', unsafe_allow_html=True)

            st.markdown(
                f'<div class="prof-label">Full name</div><div class="prof-name">{escape(USER_NAME)}</div>'
                '<div class="prof-label">Contact info</div>',
                unsafe_allow_html=True,
            )
            if not ss.editing_contact:
                info_col, edit_col = st.columns([5, 1.2], vertical_alignment="center")
                with info_col:
                    st.markdown(
                        f'<div class="prof-contact"><img src="{icon_uri(ICON_PATHS["phone"], "#374151")}" alt="">{escape(p["phone"])}</div>'
                        f'<div class="prof-contact"><img src="{icon_uri(ICON_PATHS["mail"], "#374151")}" alt="">{escape(p["email"])}</div>',
                        unsafe_allow_html=True,
                    )
                with edit_col:
                    st.button("Edit", icon=":material/edit:", key="edit_contact", on_click=set_editing, args=(True,))
            else:
                st.text_input("Phone number", value=p["phone"], key="pf_phone")
                st.text_input("Email", value=p["email"], key="pf_email")
                if "profile_error" in ss:
                    st.error(ss.profile_error)
                save_col, cancel_col, _ = st.columns([1.2, 1.2, 3])
                with save_col:
                    st.button("Save", key="save_contact", type="primary", on_click=save_contact)
                with cancel_col:
                    st.button("Cancel", key="cancel_contact", on_click=set_editing, args=(False,))

    # ----- Notification preferences -----
    elif view == "notifications":
        items = [
            ("status", "Report status updates", "Get notified when a technician starts or finishes fixing your report."),
            ("followup", "Follow-up flags", "Get notified if a unit you reported is flagged for repeated issues."),
            ("email", "Email notifications", "Send the above updates to your email as well as in-app."),
            ("weekly", "Weekly summary", "A Monday recap of all your open and resolved reports."),
        ]
        with st.container(key="notif_card"):
            st.markdown(
                '<div class="card-title">Notification preferences</div>'
                '<div class="card-sub">Choose how you want to hear about updates on your reports.</div>',
                unsafe_allow_html=True,
            )
            for key, title, desc in items:
                text_col, toggle_col = st.columns([5, 1], vertical_alignment="center")
                with text_col:
                    st.markdown(f'<div class="notif-title">{title}</div><div class="notif-desc">{desc}</div>',
                                unsafe_allow_html=True)
                with toggle_col:
                    st.toggle(title, value=ss.notif[key], key=f"n_{key}", label_visibility="collapsed",
                              on_change=set_notif, args=(key,))
                st.markdown('<div class="rule"></div>', unsafe_allow_html=True)
            st.caption("Changes are saved automatically.")

    # ----- Password & security -----
    elif view == "security":
        with st.container(key="security_card"):
            st.markdown('<div class="card-title">Change Password</div>', unsafe_allow_html=True)
            st.text_input(f"Current password (last updated {ss.pw_updated:%d/%m/%Y})", type="password",
                          key="pw_cur", placeholder="Enter current password")
            st.text_input("New password", type="password", key="pw_new")
            st.markdown('<div class="pw-hint">At least 8 characters</div>', unsafe_allow_html=True)
            st.text_input("Confirm new password", type="password", key="pw_conf",
                          placeholder="Re-enter new password")
            st.button("Forgotten your password?", key="forgot", on_click=forgot_password)
            st.button("Change password", key="change_pw", type="primary", on_click=change_password)
            message = ss.pop("pw_msg", None)
            if message:
                (st.success if message[0] == "success" else st.error)(message[1])
