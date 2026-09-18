import streamlit as st
from datetime import datetime

st.set_page_config(page_title="Centrum CMMS", layout="wide", initial_sidebar_state="expanded")

# DESIGN MGA REPA
st.markdown("""
<style>
    /* back is ground*/
    .stApp {
        background: #F1F5F9;
    }
    .block-container {
        padding-top: 4.5rem;
        max-width: 100%;
    }

    /* header and toolbar */
    header[data-testid="stHeader"] {
        background: #F1F5F9;
        box-shadow: none;
    }
    header[data-testid="stHeader"] * {
        color: #0F172A !important;
    }
    header[data-testid="stHeader"] svg {
        fill: #0F172A !important;
    }

    /* button para makita yung sidebar */
    [data-testid="collapsedControl"] {
        background: #0B1220 !important;
        border-radius: 0 8px 8px 0 !important;
        padding: 4px !important;
    }
    [data-testid="collapsedControl"] svg {
        fill: #14B8A6 !important;
    }

    /* mapalitan yung color ba depende sa theme */
    [data-testid="stMain"], [data-testid="stMain"] * {
        color: #0F172A !important;
    }
    [data-testid="stMain"] .stTextInput input::placeholder {
        color: #94A3B8 !important;
    }
    /* search box*/
    [data-testid="stMain"] [data-testid="stTextInput"] input {
        background: white !important;
        border: 1px solid #E2E8F0 !important;
        border-radius: 999px !important;
        width: 100% !important;
        box-sizing: border-box !important;
    }
    [data-testid="stMain"] [data-testid="stTextInput"] {
        width: 100% !important;
        max-width: 100% !important;
    }
    /* Bell button: square light icon button instead of default dark button */
    [data-testid="stMain"] [data-testid="stTextInput"] + div .stButton button,
    [data-testid="stMain"] .stButton button {
        background: white !important;
        border: 1px solid #E2E8F0 !important;
        border-radius: 10px !important;
    }

    /* sidebar */
    section[data-testid="stSidebar"] {
        background: #0B1220;
    }
    section[data-testid="stSidebar"] * {
        color: #CBD5E1;
    }
    section[data-testid="stSidebar"] .stButton button {
        background: transparent;
        border: none;
        color: #CBD5E1;
        text-align: left;
        font-size: 14px;
        padding: 8px 10px;
        border-radius: 8px;
        width: 100%;
    }
    section[data-testid="stSidebar"] .stButton button:hover {
        background: #1A2333;
        color: white;
    }
    .sidebar-section-label {
        color: #64748B;
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 0.05em;
        margin: 14px 0 4px 4px;
    }
    .sidebar-logo {
        display: flex;
        align-items: center;
        gap: 10px;
        margin-bottom: 4px;
    }
    .sidebar-logo-box {
        width: 34px; height: 34px;
        background: #14B8A6;
        border-radius: 8px;
        flex-shrink: 0;
    }
    .sidebar-brand-title { color: white; font-weight: 700; font-size: 15px; line-height: 1.1; }
    .sidebar-brand-sub { color: #64748B; font-size: 11px; }
    .sidebar-user-row {
        display: flex;
        align-items: center;
        gap: 10px;
        border-top: 1px solid #1E293B;
        padding-top: 14px;
        margin-top: 14px;
    }
    .avatar-circle {
        width: 32px; height: 32px;
        background: #14B8A6;
        border-radius: 50%;
        color: white;
        display: flex; align-items: center; justify-content: center;
        font-size: 12px; font-weight: 700;
        flex-shrink: 0;
    }

    /* top bar*/
    .topbar {
        display: flex;
        justify-content: flex-end;
        align-items: center;
        gap: 10px;
        margin-bottom: 4px;
    }

    /* cards */
    .stat-card {
        border: 1px solid #E2E8F0;
        border-top: 3px solid #22C55E;
        border-radius: 12px;
        padding: 16px 18px;
        background: white;
    }
    .stat-card.alert { border-top-color: #EF4444; }
    .stat-label { color: #64748B; font-size: 13px; font-weight: 500; }
    .stat-value { font-size: 32px; font-weight: 700; color: #0F172A; line-height: 1.2; }
    .stat-sub { color: #94A3B8; font-size: 11px; }

    /* Panels */
    .panel {
        background: white;
        border: 1px solid #E2E8F0;
        border-radius: 12px;
        padding: 18px 20px;
        height: 100%;
    }
    .panel-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 6px;
    }
    .panel-title { font-size: 16px; font-weight: 700; color: #0F172A; }
    .panel-link { color: #14B8A6; font-size: 13px; font-weight: 600; text-decoration: none; }

    /* Pills */
    .pill {
        border-radius: 999px;
        padding: 3px 10px;
        font-size: 11px;
        font-weight: 600;
        display: inline-block;
    }
    .pill-followup { background: #FDE8E8; color: #C0392B; }
    .pill-progress { background: #FDF3E3; color: #B9770E; }
    .pill-resolved { background: #E6F6EC; color: #1E8449; }

    /* Activity rows */
    .activity-row {
        display: flex;
        align-items: flex-start;
        gap: 12px;
        border-bottom: 1px solid #F1F5F9;
        padding: 12px 0;
    }
    .activity-row:last-child { border-bottom: none; }
    .icon-badge {
        width: 30px; height: 30px;
        border-radius: 8px;
        display: flex; align-items: center; justify-content: center;
        font-size: 13px;
        flex-shrink: 0;
        margin-top: 2px;
    }
    .icon-new { background: #DBEAFE; color: #2563EB; font-size: 9px; font-weight: 800; }
    .icon-progress { background: #FDF3E3; color: #B9770E; }
    .icon-resolved { background: #E6F6EC; color: #1E8449; }
    .activity-title { font-size: 14px; font-weight: 600; color: #0F172A; }
    .activity-sub { color: #94A3B8; font-size: 12px; margin-top: 2px; }

    /* Room cards */
    .room-card {
        border: 1px solid #E2E8F0;
        border-radius: 10px;
        padding: 12px 14px;
        background: #FAFBFC;
        margin-bottom: 10px;
    }
    .room-code { font-size: 12px; color: #64748B; font-weight: 600; }
    .room-units { font-size: 22px; font-weight: 700; color: #0F172A; }
    .room-units-label { font-size: 11px; color: #94A3B8; font-weight: 400; }
    .room-legend { font-size: 10px; color: #64748B; margin-top: 4px; line-height: 1.6; }
</style>
""", unsafe_allow_html=True)

# ---------- Session state ----------
if "reports" not in st.session_state:
    st.session_state.reports = [
        {"title": "Slow Performance on C1-02", "room_info": "Room 1 · Aug. 21, 8:14AM", "status": "Follow-Up",
         "description": "Reported slow boot and lag during class use.", "icon": "new"},
        {"title": "No Internet on C2-02", "room_info": "Room 1 · Aug. 18, 7:50AM", "status": "In Progress",
         "description": "Unit not connecting to school Wi-Fi.", "icon": "progress"},
        {"title": "Won't Turn On on C3-03", "room_info": "Room 1 · Aug. 4, 9:14AM", "status": "Resolved",
         "description": "Power supply was replaced and tested.", "icon": "resolved"},
    ]

if "rooms" not in st.session_state:
    st.session_state.rooms = [
        {"code": "CL 01", "units": 34, "good": 32, "issues": 1, "replace": 1},
        {"code": "CL 02", "units": 35, "good": 33, "issues": 2, "replace": 0},
        {"code": "CL 03", "units": 35, "good": 34, "issues": 0, "replace": 1},
        {"code": "CL 04", "units": 34, "good": 34, "issues": 0, "replace": 0},
    ]

if "page" not in st.session_state:
    st.session_state.page = "Home"

# ---------- Sidebar navigation ----------
NAV_ITEMS = [
    ("Home", "🏠", "Home"),
    ("Report", "➕", "Report an Issue"),
    ("Reports", "📋", f"My Reports ({len(st.session_state.reports)})"),
]

with st.sidebar:
    st.markdown(
        '<div class="sidebar-logo"><div class="sidebar-logo-box"></div>'
        '<div><div class="sidebar-brand-title">CENTRUM CMMS</div>'
        '<div class="sidebar-brand-sub">Teacher Workplace</div></div></div>',
        unsafe_allow_html=True,
    )

    st.markdown('<div class="sidebar-section-label">OVERVIEW</div>', unsafe_allow_html=True)
    for page_key, icon, label in NAV_ITEMS:
        if page_key == "Report":
            st.markdown('<div class="sidebar-section-label">REPORTING</div>', unsafe_allow_html=True)
        if st.button(f"{icon}  {label}", use_container_width=True, key=f"nav_{page_key}"):
            st.session_state.page = page_key

    # higlight yung button ba
    active_key = f"nav_{st.session_state.page}"
    st.markdown(
        f"""<style>
        .st-key-{active_key} button {{
            background: #142033 !important;
            color: white !important;
            font-weight: 600 !important;
            border-left: 3px solid #14B8A6 !important;
            padding-left: 7px !important;
        }}
        </style>""",
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="sidebar-user-row"><div class="avatar-circle">JR</div>'
        '<div><div style="color:white; font-size:13px; font-weight:600;">Juanita Reyes</div>'
        '<div style="color:#64748B; font-size:11px;">Teacher</div></div></div>',
        unsafe_allow_html=True,
    )

# ---------- Helper: status pill ----------
def status_pill(status):
    css_class = {"Follow-Up": "pill-followup", "In Progress": "pill-progress", "Resolved": "pill-resolved"}[status]
    return f'<span class="pill {css_class}">{status}</span>'

def icon_badge(icon):
    if icon == "new":
        return '<div class="icon-badge icon-new">NEW</div>'
    elif icon == "progress":
        return '<div class="icon-badge icon-progress">⚡</div>'
    else:
        return '<div class="icon-badge icon-resolved">✓</div>'

# ---------- Top bar (search + bell) ----------
_, search_col, bell_col = st.columns([3, 1.6, 0.35])
with search_col:
    st.text_input("Search", placeholder="🔍  Search reports, units, rooms...", label_visibility="collapsed")
with bell_col:
    st.button("🔔", use_container_width=True)

# ---------- HOME PAGE ----------
if st.session_state.page == "Home":
    st.title("Good day, Juan")

    open_count = sum(1 for r in st.session_state.reports if r["status"] == "Follow-Up")
    progress_count = sum(1 for r in st.session_state.reports if r["status"] == "In Progress")
    resolved_count = sum(1 for r in st.session_state.reports if r["status"] == "Resolved")
    followup_count = open_count

    col1, col2, col3, col4 = st.columns(4)
    stats = [
        (col1, "My Open Reports", open_count, "awaiting technician", False),
        (col2, "Being Fixed", progress_count, "In Progress", False),
        (col3, "Resolved", resolved_count, "Marked fixed by technician", False),
        (col4, "Needs Follow-Up", followup_count, "Sent back to technician", True),
    ]
    for col, label, value, sub, alert in stats:
        with col:
            alert_class = "alert" if alert else ""
            st.markdown(
                f'<div class="stat-card {alert_class}">'
                f'<div class="stat-label">{label}</div>'
                f'<div class="stat-value">{value}</div>'
                f'<div class="stat-sub">{sub}</div>'
                '</div>',
                unsafe_allow_html=True,
            )

    st.write("")
    left, right = st.columns([2, 1])

    with left:
        rows_html = "".join(
            f'<div class="activity-row">{icon_badge(r.get("icon", "new"))}'
            f'<div><div class="activity-title">{r["title"]} &nbsp;{status_pill(r["status"])}</div>'
            f'<div class="activity-sub">{r["room_info"]}</div></div></div>'
            for r in st.session_state.reports
        )
        panel_html = (
            '<div class="panel">'
            '<div class="panel-header">'
            '<div class="panel-title">Recent activity</div>'
            '<span class="panel-link">View my Reports &rarr;</span>'
            '</div>'
            f'{rows_html}'
            '</div>'
        )
        st.markdown(panel_html, unsafe_allow_html=True)

    with right:
        room_cards = "".join(
            '<div class="room-card">'
            f'<div class="room-code">{room["code"]}</div>'
            f'<div class="room-units">{room["units"]} <span class="room-units-label">Units</span></div>'
            '<div class="room-legend">'
            f'🟢 {room["good"]} good<br>'
            f'🟡 {room["issues"]} with issues<br>'
            f'🔴 {room["replace"]} for replacement'
            '</div></div>'
            for room in st.session_state.rooms
        )
        panel_html = (
            '<div class="panel">'
            '<div class="panel-header"><div class="panel-title">Room at glance</div></div>'
            '<div style="display:grid; grid-template-columns:1fr 1fr; gap:10px;">'
            f'{room_cards}'
            '</div></div>'
        )
        st.markdown(panel_html, unsafe_allow_html=True)
