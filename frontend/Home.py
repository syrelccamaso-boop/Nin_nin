"""
Home.py - Computer Laboratory | public homepage (Streamlit)

The homepage keeps the original design (navigation bar, hero with the Centrum
floor plan, stats strip, laboratories, features, how it works, about, call to
action, contact and footer). The design's sections are drawn with st.markdown
using the design's own CSS; everything you can click is a real Streamlit button
styled to match:

    nav bar      Home, Laboratories, Features, How It Works, About Us, Contact
                 (scroll to that section), Log in, Register; on small screens
                 the links move into a "Menu" button; the logo goes to the top
    hero         Get Started (sign up), See How It Works (scrolls)
    labs         each Centrum card opens the log in
    features     Teacher / Technician / Admin tabs + their sign up / log in button
    contact      Create an account, Log in, "Report a problem", "Account requests"
    footer       section links

Scrolling to a section uses a tiny script in a hidden frame
(streamlit.components.v1.html) because Streamlit buttons can't jump to anchors.

The buttons call the functions you pass to render():

    import Home
    Home.render(on_login=open_login, on_signup=open_signup)

Preview on its own:   streamlit run Home.py
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import streamlit as st

ss = st.session_state

# assets/logo-icon.png (next to app.py) is used as the browser-tab icon.
_HERE = Path(__file__).resolve().parent
_ICON = next((p for p in (_HERE / "assets" / "logo-icon.png", _HERE.parent / "assets" / "logo-icon.png") if p.is_file()), None)

TABS = [("teacher", "Teacher", ":material/school:"), ("technician", "Technician", ":material/build:"),
        ("admin", "Admin", ":material/verified_user:")]


try:
    from frontend.ui import _markup, scope_css
except ImportError:  # Home.py placed inside frontend/ and run from there
    from ui import _markup, scope_css  # type: ignore

_CSS: list[str] = []


def _css() -> str:
    """The homepage stylesheet, scoped to the .clx wrappers (built once)."""
    if not _CSS:
        _CSS.append(scope_css(HOME_CSS + STREAMLIT_CSS))
    return _CSS[0]


def _html(markup: str) -> None:
    """A section of the design. st.markdown keeps the inline SVG (icons, floor plan, logo)."""
    st.markdown(f'<div class="clx">{_markup(markup)}</div>', unsafe_allow_html=True)


NAV = [("home", "Home"), ("labs", "Laboratories"), ("features", "Features"), ("how", "How It Works"),
       ("about", "About Us"), ("contact", "Contact")]


def _preview_click(view: str) -> None:
    ss["home_preview_msg"] = f"In the app this opens the {'Sign Up' if view == 'signup' else 'Log In'} screen."


def _goto(section: str) -> None:
    """Nav link / footer link / 'See How It Works': scroll to that section of the page."""
    ss["home_section"] = section
    ss["home_scroll"] = section
    ss["home_scroll_n"] = ss.get("home_scroll_n", 0) + 1


def _anchor(section: str) -> None:
    st.markdown(f'<div class="clx"><div class="cl-anchor" id="cl-sec-{section}"></div></div>', unsafe_allow_html=True)


def _scroll_now() -> None:
    """Scroll the page to the section picked in the nav bar (a tiny script in a hidden frame)."""
    target = ss.pop("home_scroll", None)
    if not target:
        return
    try:
        import streamlit.components.v1 as components
    except ImportError:
        return
    nonce = ss.get("home_scroll_n", 0)
    script = (
        "<script>/* %s */(function(){var tries=0;function go(){var d=window.parent.document;"
        "var el=d.getElementById('cl-sec-%s');if(el){el.scrollIntoView({behavior:'smooth',block:'start'});return;}"
        "if(++tries<30){setTimeout(go,100);}}go();})();</script>" % (nonce, target))
    with st.container(key="home_js"):
        try:
            components.html(script, height=0)
        except Exception:  # never break the homepage because of the scroll helper
            pass


def _split(pattern: str, markup: str) -> list[str]:
    return re.findall(pattern, markup, re.S)


def render(on_login=None, on_signup=None) -> None:
    """Draw the homepage. `on_login` / `on_signup` run when those buttons are clicked."""
    try:
        st.set_page_config(page_title="Computer Laboratory", page_icon=str(_ICON) if _ICON else "\U0001F5A5️",
                           layout="wide", initial_sidebar_state="collapsed")
    except st.errors.StreamlitAPIException:
        pass

    actions = {
        "login": (on_login, ()) if on_login else (_preview_click, ("login",)),
        "signup": (on_signup, ()) if on_signup else (_preview_click, ("signup",)),
    }

    def open_view(view: str, notice: str | None = None) -> None:
        func, args = actions[view]
        func(*args)
        if notice:  # shown on the Log In card (NewLogin's message box)
            ss["auth_notice"] = ("ok", notice)

    def button(label: str, view: str, key: str, kind: str, icon: str | None = None, notice: str | None = None) -> None:
        extra = {"icon": icon} if icon else {}
        st.button(label, key=f"{key}__{kind}__", on_click=open_view, args=(view, notice), **extra)

    def link(section: str, label: str, key: str, kind: str = "hlink") -> None:
        on = ss.get("home_section", "home") == section and kind == "hlink"
        st.button(label, key=f"{key}_{section}__{kind}{'on' if on else ''}__", on_click=_goto, args=(section,))

    st.markdown(f"<style>{_css()}</style>", unsafe_allow_html=True)
    msg = ss.pop("home_preview_msg", None)
    if msg:
        st.toast(msg)

    # ---- navigation bar: logo (design) + real buttons ---------------------------
    _html(NAV_HTML)
    with st.container(key="home_logo"):
        st.button("Computer Laboratory home", key="cl_home_logo_btn", on_click=_goto, args=("home",))
    with st.container(key="home_navlinks"):
        for section, label in NAV:
            link(section, label, "cl_nav")
    with st.container(key="home_navbtn"):
        button("Log in", "login", "cl_home_login", "hghostnav", ":material/login:")
        button("Register", "signup", "cl_home_register", "hnav", ":material/person_add:")
        with st.container(key="home_menu"), st.popover(":material/menu: Menu"):
            for section, label in NAV:
                link(section, label, "cl_menu", "hmenu")
            button("Log in", "login", "cl_menu_login", "hmenu", ":material/login:")
            button("Register", "signup", "cl_menu_register", "hmenu", ":material/person_add:")

    # ---- hero ----------------------------------------------------------------
    _anchor("home")
    with st.container(key="home_hero"):
        left, right = st.columns([1.02, 1], gap="medium", vertical_alignment="center")
        with left:
            _html(f'<div class="hero" style="background:none;overflow:visible;">{HERO_LEFT_HTML}</div>')
            with st.container(key="home_ctas"):
                button("Get Started", "signup", "cl_home_start", "hprimary", ":material/arrow_forward:")
                st.button("See How It Works", key="cl_home_how__hghost__", on_click=_goto, args=("how",))
            _html(HERO_ROLES_HTML)
        with right:
            _html(HERO_ART_HTML)

    # ---- stats strip + laboratories (each lab card opens the log in) ---------------
    _html(STRIP_HTML)
    _anchor("labs")
    with st.container(key="home_labs"):
        _html(_split(r'<div class="sec-head reveal">.*?</div>\s*(?=<div class="labs">)', LABS_HTML)[0])
        with st.container(key="home_labgrid"):
            for i, card in enumerate(_split(r'<article class="lab reveal".*?</article>', LABS_HTML), start=1):
                with st.container(key=f"hitwrap_home_lab_{i}"):
                    _html(card.replace('class="lab reveal"', 'class="lab reveal clickable"'))
                    st.button(f"Centrum {i}", key=f"hit_home_lab_{i}", on_click=open_view,
                              args=("login", f"Log in to report a problem or check the computers in Centrum {i}."))

    # ---- features (role tabs) --------------------------------------------------
    _anchor("features")
    current = ss.get("home_tab", "teacher")
    with st.container(key="home_features"):
        _html(FEATURES_HEAD_HTML)
        with st.container(key="home_tabs"):
            for role, label, icon in TABS:
                st.button(label, key=f"cl_home_tab_{role}__htab{'on' if role == current else ''}__", icon=icon,
                          on_click=ss.__setitem__, args=("home_tab", role))
        left_html, label, view, grid_html = PANELS[current]
        left, right = st.columns([1, 1.1], gap="large", vertical_alignment="center")
        with left:
            _html(f"<div class=\"panel-left\">{left_html}</div>")
            button(label, view, f"cl_home_feat_{current}", "hprimarymt")
        with right:
            _html(grid_html)

    # ---- how it works + about ----------------------------------------------------
    _anchor("how")
    _html(HOW_HTML)
    _anchor("about")
    _html(ABOUT_HTML)

    # ---- call to action + contact --------------------------------------------------
    _anchor("contact")
    with st.container(key="home_contact"):
        with st.container(key="home_cta"):
            left, right = st.columns([1.3, 1], gap="medium", vertical_alignment="center")
            with left:
                _html(f"<div class=\"cta-text\">{CTA_LEFT_HTML}</div>")
            with right:
                with st.container(key="home_cta_btns"):
                    button("Create an account", "signup", "cl_home_cta_signup", "hwhite")
                    button("Log in", "login", "cl_home_cta_login", "hline")
        cards = _split(r'<div class="card reveal">.*?</p></div></div>', CONTACT_HTML)
        targets = [None, ("login", "Log in to send a report to the technicians."),
                   ("signup", "Technician accounts are confirmed by the admin before the first log in.")]
        with st.container(key="home_contactgrid"):
            for i, card in enumerate(cards):
                markup = f'<div class="contact" style="display:block;margin:0">{card}</div>'
                target = targets[i] if i < len(targets) else None
                if target:
                    with st.container(key=f"hitwrap_home_contact_{i}"):
                        _html(markup.replace('class="card reveal"', 'class="card reveal clickable"'))
                        st.button("Open", key=f"hit_home_contact_{i}", on_click=open_view, args=target)
                else:
                    _html(markup)

    # ---- footer: logo, real links, copyright ------------------------------------------
    with st.container(key="home_footer"):
        _html(_split(r'<a href="#home" class="flogo".*?</a>', FOOTER_HTML)[0].replace('href="#home" ', ""))
        with st.container(key="home_footnav"):
            for section, label in NAV[1:]:
                link(section, label, "cl_foot", "hfoot")
        _html(f'<div class="fcopy">© {datetime.now().year} Computer Laboratory · Computer Monitoring Management System</div>')

    _scroll_now()


# ---------------------------------------------------------------------------
# How Streamlit's widgets fit into the design
# ---------------------------------------------------------------------------
STREAMLIT_CSS = """
[data-testid="stToolbarActions"], [data-testid="stMainMenu"], [data-testid="stAppDeployButton"], [data-testid="stDecoration"],
[data-testid="stStatusWidget"], #MainMenu, footer:not(.cl-footer) { display: none !important; }
header[data-testid="stHeader"] { background: transparent !important; height: 0 !important; min-height: 0 !important; }
[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"], [data-testid="stExpandSidebarButton"] { display: none !important; }
.stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"] { background: #fff !important; }
[data-testid="stMain"] { scroll-behavior: smooth; }
[data-testid="stMainBlockContainer"], .block-container { max-width: 100% !important; padding: 0 !important; }
:where([data-testid="stMain"]) [data-testid="stVerticalBlock"] { gap: 0 !important; }
[data-testid="stMarkdownContainer"]:has(> .clx) { margin: 0 !important; }
[data-testid="stMarkdownContainer"] > .clx { display: block; }
.reveal { opacity: 1 !important; transform: none !important; }
.menu-btn, .mobile-menu { display: none !important; }
.cl-anchor { display: block; height: 0; scroll-margin-top: 80px; }
.st-key-home_js { position: absolute !important; width: 0 !important; height: 0 !important; overflow: hidden; }
.st-key-home_js iframe { width: 0 !important; height: 0 !important; border: 0; }

/* nav bar stays on top; real Streamlit buttons sit where the design has its links */
.nav { position: fixed !important; top: 0; left: 0; right: 0; border-color: var(--line) !important; }
.nav .nav-links, .nav .btn-login { display: none !important; }
.st-key-home_logo { position: fixed !important; top: 14px; left: max(24px, calc((100vw - 1200px) / 2)); z-index: 61;
  width: 140px !important; height: 48px; }
.st-key-home_logo button { width: 140px !important; height: 48px !important; opacity: 0 !important; cursor: pointer; }
.st-key-home_navlinks { position: fixed !important; top: 0; left: 50%; transform: translateX(-50%); height: 76px; z-index: 60;
  flex-direction: row !important; align-items: center; gap: 2px !important; width: auto !important; flex-wrap: nowrap; }
.st-key-home_navlinks > div, .st-key-home_navbtn > div { width: auto !important; flex: 0 0 auto; }
.st-key-home_navbtn { position: fixed !important; top: 14px; right: max(24px, calc((100vw - 1200px) / 2)); z-index: 62;
  width: auto !important; flex-direction: row !important; align-items: center; gap: 10px !important; flex-wrap: nowrap; }
.st-key-home_menu { display: none !important; }
.st-key-home_menu [data-testid="stPopover"] button { border-radius: 999px !important; border: 1.5px solid var(--line) !important;
  background: #fff !important; color: var(--navy) !important; padding: 9px 16px !important; min-height: 0 !important;
  font: 600 14px 'Poppins', sans-serif !important; }
[data-testid="stPopoverBody"] { border-radius: 16px !important; padding: 10px !important; min-width: 220px; }
[data-testid="stPopoverBody"] [data-testid="stVerticalBlock"] { gap: 2px !important; }
[class*="__hlink"] button { background: transparent !important; border: 0 !important; box-shadow: none !important;
  border-radius: 10px !important; padding: 8px 12px !important; min-height: 0 !important;
  font: 500 14.5px 'Poppins', sans-serif !important; color: #4b5563 !important; }
[class*="__hlink"] button p, [class*="__hmenu"] button p, [class*="__hfoot"] button p, [class*="__hghost"] button p { font: inherit !important; margin: 0; }
[class*="__hlink"] button:hover { color: var(--navy) !important; background: var(--bg-soft) !important; }
[class*="__hlinkon__"] button { color: var(--blue) !important; font-weight: 600 !important;
  box-shadow: inset 0 -2px 0 var(--blue) !important; border-radius: 0 !important; }
[class*="__hmenu"], [class*="__hmenu"] .stButton, [class*="__hmenu"] button { width: 100% !important; }
[class*="__hmenu"] button { justify-content: flex-start !important; background: transparent !important; border: 0 !important;
  padding: 10px 12px !important; min-height: 0 !important; border-radius: 10px !important;
  font: 500 15px 'Poppins', sans-serif !important; color: var(--navy) !important; }
[class*="__hmenu"] button:hover { background: var(--bg-soft) !important; color: var(--blue) !important; }
[class*="__hghost"] button { border-radius: 999px !important; font: 600 15px 'Poppins', sans-serif !important;
  padding: 12px 24px !important; min-height: 0 !important; background: #fff !important; color: var(--navy) !important;
  border: 1.5px solid var(--line) !important; }
[class*="__hghost"] button:hover { border-color: var(--blue-line) !important; color: var(--blue) !important; }
[class*="__hghostnav__"] button { padding: 10px 18px !important; font-size: 14.5px !important; }

/* whole-element click areas (lab cards, contact cards): an invisible button over the card */
[class*="st-key-hitwrap_"] { position: relative; gap: 0 !important; }
[class*="st-key-hit_"] { position: absolute !important; inset: 0; z-index: 4; width: 100% !important; height: 100% !important; margin: 0 !important; }
[class*="st-key-hit_"] .stButton, [class*="st-key-hit_"] button { width: 100% !important; height: 100% !important;
  min-height: 0 !important; padding: 0 !important; opacity: 0 !important; cursor: pointer; }
.lab.clickable, .card.clickable { cursor: pointer; }
[class*="st-key-hitwrap_"]:hover .lab { transform: translateY(-4px); box-shadow: var(--shadow); border-color: var(--blue-line); }
[class*="st-key-hitwrap_"]:hover .card { border-color: var(--blue-line); box-shadow: var(--shadow); }

/* sections built from Streamlit containers */
.st-key-home_hero { padding: 76px max(24px, calc((100% - 1200px) / 2)) 0;
  background: radial-gradient(900px 500px at 88% 40%, #eef4fe 0%, rgba(238, 244, 254, 0) 70%), #fff; }
.st-key-home_hero [data-testid="stHorizontalBlock"] { min-height: calc(100vh - 76px); padding: 48px 0 64px; }
.st-key-home_ctas { flex-direction: row !important; flex-wrap: wrap; gap: 14px !important; align-items: center; }
.st-key-home_ctas > div { width: auto !important; flex: 0 0 auto; }
.st-key-home_labs { padding: 104px max(24px, calc((100% - 1200px) / 2)); }
.st-key-home_labgrid { display: grid !important; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 22px !important; }
.st-key-home_labgrid > div { width: auto !important; min-width: 0; }
.st-key-home_features { background: var(--bg-soft); padding: 104px max(24px, calc((100% - 1200px) / 2)); }
.st-key-home_tabs { flex-direction: row !important; justify-content: center; gap: 8px !important; margin: -24px auto 44px;
  background: #fff; border: 1px solid var(--line); border-radius: 999px; padding: 6px; width: max-content !important;
  max-width: 100%; flex-wrap: wrap; }
.st-key-home_tabs > div { width: auto !important; }
.panel-left h3 { font-size: 28px; line-height: 1.25; margin: 10px 0 14px; }
.panel-left > p { color: var(--muted); margin: 0 0 24px; }
.st-key-home_contact { padding: 104px max(24px, calc((100% - 1200px) / 2)) 0; }
.st-key-home_cta { background: linear-gradient(120deg, var(--blue) 0%, var(--blue-dk) 100%); border-radius: 28px;
  padding: 56px; color: #fff; position: relative; overflow: hidden; }
.st-key-home_cta::after { content: ""; position: absolute; right: -80px; top: -80px; width: 320px; height: 320px;
  border-radius: 50%; border: 46px solid rgba(255, 255, 255, .08); pointer-events: none; }
.cta-text h2 { color: #fff !important; font-size: clamp(26px, 3vw, 36px); line-height: 1.2; margin-bottom: 10px; }
.cta-text p { margin: 0; color: #dbe7fd; }
.st-key-home_cta_btns { flex-direction: row !important; justify-content: flex-end; gap: 12px !important;
  flex-wrap: wrap; position: relative; z-index: 1; }
.st-key-home_cta_btns > div { width: auto !important; }
.st-key-home_contactgrid { display: grid !important; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 22px !important;
  margin-top: 44px; }
.st-key-home_contactgrid > div { width: auto !important; min-width: 0; }
.st-key-home_contactgrid .card { height: 100%; }
.st-key-home_footer { background: var(--navy-2); color: #aab6cf; margin-top: 104px; font-size: 14px;
  padding: 36px max(24px, calc((100% - 1200px) / 2)); flex-direction: row !important; align-items: center;
  justify-content: space-between; gap: 18px 24px !important; flex-wrap: wrap; }
.st-key-home_footer > div { width: auto !important; flex: 0 0 auto; }
.st-key-home_footer .flogo svg { height: 46px; width: auto; display: block; }
.fcopy { color: #aab6cf; font-size: 14px; }
.st-key-home_footnav { flex-direction: row !important; gap: 4px 6px !important; flex-wrap: wrap; }
.st-key-home_footnav > div { width: auto !important; }
[class*="__hfoot__"] button { background: transparent !important; border: 0 !important; color: #aab6cf !important;
  padding: 6px 10px !important; min-height: 0 !important; font: 500 14px 'Open Sans', sans-serif !important; }
[class*="__hfoot__"] button:hover { color: #fff !important; }

/* buttons = the design's .btn variants */
[class*="__hnav__"] button, [class*="__hprimary"] button, [class*="__hwhite__"] button, [class*="__hline__"] button {
  border-radius: 999px !important; font: 600 15px 'Poppins', sans-serif !important; padding: 13px 26px !important;
  min-height: 0 !important; transition: transform .15s, box-shadow .15s, background .15s; }
[class*="__hnav__"] button p, [class*="__hprimary"] button p, [class*="__hwhite__"] button p, [class*="__hline__"] button p,
[class*="__htab"] button p { font: inherit !important; margin: 0; }
[class*="__hnav__"] button, [class*="__hprimary"] button { background: var(--blue) !important; color: #fff !important;
  border: 0 !important; box-shadow: 0 10px 24px rgba(45, 111, 227, .30) !important; }
[class*="__hnav__"] button:hover, [class*="__hprimary"] button:hover { background: var(--blue-dk) !important;
  box-shadow: 0 12px 28px rgba(45, 111, 227, .38) !important; }
[class*="__hnav__"] button { padding: 11px 20px !important; font-size: 14.5px !important; }
[class*="__hprimary__"] button > div { flex-direction: row-reverse; }
[class*="__hprimarymt__"] { margin-top: 28px; }
[class*="__hwhite__"] button { background: #fff !important; color: var(--blue) !important; border: 0 !important; }
[class*="__hwhite__"] button:hover { background: #eef4fe !important; }
[class*="__hline__"] button { background: transparent !important; color: #fff !important;
  border: 1.5px solid rgba(255, 255, 255, .5) !important; }
[class*="__hline__"] button:hover { border-color: #fff !important; }
[class*="__htab"] button { border: 0 !important; background: transparent !important; border-radius: 999px !important;
  padding: 10px 22px !important; font: 600 14.5px 'Poppins', sans-serif !important; color: var(--muted) !important;
  min-height: 0 !important; box-shadow: none !important; }
[class*="__htab"] button:hover { color: var(--navy) !important; }
[class*="__htabon__"] button { background: var(--navy) !important; color: #fff !important; }
button:focus-visible { outline: 2px solid var(--blue) !important; outline-offset: 2px; }
[data-testid="stToast"] { background: var(--navy) !important; border-radius: 12px !important; }
[data-testid="stToast"], [data-testid="stToast"] p { color: #fff !important; font-size: 14px; }
@media (max-width: 1150px) {
  .st-key-home_navlinks { display: none !important; }
  .st-key-home_menu { display: block !important; }
}
@media (max-width: 1080px) {
  .st-key-home_labgrid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 900px) {
  .st-key-home_hero [data-testid="stHorizontalBlock"] { min-height: 0; padding-top: 36px; }
  .st-key-home_cta { padding: 40px 28px; }
  .st-key-home_cta_btns { justify-content: flex-start; }
  .st-key-home_contactgrid { grid-template-columns: minmax(0, 1fr); }
  .st-key-home_labs, .st-key-home_features { padding-top: 76px; padding-bottom: 76px; }
}
@media (max-width: 640px) {
  .st-key-home_navbtn [class*="__hghostnav__"] { display: none !important; }
  .st-key-home_navbtn { right: 16px; gap: 8px !important; }
  .st-key-home_logo { left: 16px; }
  [class*="__hnav__"] button { padding: 10px 14px !important; }
  .st-key-home_labgrid { grid-template-columns: minmax(0, 1fr); }
  .st-key-home_tabs { width: 100% !important; border-radius: 18px; }
  .st-key-home_footer { flex-direction: column !important; align-items: flex-start; }
}
@media (max-width: 420px) {
  .nav-logo svg { height: 36px !important; }
  .st-key-home_menu [data-testid="stPopover"] button { padding: 9px 12px !important; }
  [class*="__hnav__"] button p { font-size: 13.5px !important; }
}
"""


# ---------------------------------------------------------------------------
# The homepage design: its stylesheet and sections (edit to change the look)
# ---------------------------------------------------------------------------
HOME_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Poppins:wght@500;600;700;800&family=Open+Sans:wght@400;500;600;700&display=swap');
:root {
  --blue: #2d6fe3; --blue-dk: #1d4ed8; --blue-soft: #eaf1fd; --blue-line: #cfdcf6;
  --navy: #14213d; --navy-2: #0f1a33;
  --ink: #111827; --muted: #5b6472; --line: #e6e9ef; --bg-soft: #f5f7fb;
  --ok: #22a06b; --rep: #f59e0b; --fix: #e5484d;
  --radius: 16px;
  --shadow: 0 18px 50px rgba(20, 33, 61, .10);
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; scroll-padding-top: 84px; }
body { margin: 0; background: #fff; color: var(--ink);
  font: 400 16px/1.6 'Open Sans', 'Segoe UI', Roboto, Arial, sans-serif; -webkit-font-smoothing: antialiased; }
h1, h2, h3, h4, .brand-font { font-family: 'Poppins', 'Segoe UI', Arial, sans-serif; color: var(--navy); margin: 0; }
a { color: inherit; text-decoration: none; }
button { font: inherit; cursor: pointer; }
.wrap { width: min(1200px, 100% - 48px); margin: 0 auto; }
svg.icon { width: 20px; height: 20px; flex: none; }

/* ---------------------------------------------------------------- nav */
.nav { position: sticky; top: 0; z-index: 50; background: rgba(255, 255, 255, .92);
  backdrop-filter: saturate(160%) blur(10px); border-bottom: 1px solid transparent; transition: border-color .2s, box-shadow .2s; }
.nav.scrolled { border-color: var(--line); box-shadow: 0 6px 24px rgba(20, 33, 61, .06); }
.nav .wrap { display: flex; align-items: center; justify-content: space-between; height: 76px; gap: 24px; }
.nav-logo svg { height: 44px; width: auto; display: block; }
.nav-links { display: flex; gap: 34px; }
.nav-links a { position: relative; font: 500 14.5px 'Poppins', sans-serif; color: #4b5563; padding: 6px 0; transition: color .15s; }
.nav-links a:hover { color: var(--navy); }
.nav-links a.active { color: var(--blue); font-weight: 600; }
.nav-links a.active::after { content: ""; position: absolute; left: 0; right: 0; bottom: -2px; height: 2px;
  border-radius: 2px; background: var(--blue); }
.btn { display: inline-flex; align-items: center; justify-content: center; gap: 9px; border: 0; border-radius: 999px;
  font: 600 15px 'Poppins', sans-serif; padding: 13px 26px; transition: transform .15s, box-shadow .15s, background .15s; }
.btn:active { transform: translateY(1px); }
.btn-primary { background: var(--blue); color: #fff; box-shadow: 0 10px 24px rgba(45, 111, 227, .30); }
.btn-primary:hover { background: var(--blue-dk); box-shadow: 0 12px 28px rgba(45, 111, 227, .38); }
.btn-ghost { background: #fff; color: var(--navy); border: 1.5px solid var(--line); }
.btn-ghost:hover { border-color: var(--blue-line); color: var(--blue); }
.btn-sm { padding: 11px 22px; font-size: 14.5px; }
.menu-btn { display: none; background: none; border: 0; padding: 8px; color: var(--navy); }
.mobile-menu { display: none; }

/* ---------------------------------------------------------------- hero */
.hero { position: relative; overflow: hidden; background:
  radial-gradient(900px 500px at 88% 40%, #eef4fe 0%, rgba(238, 244, 254, 0) 70%), #fff; }
.hero .wrap { display: grid; grid-template-columns: 1.02fr 1fr; align-items: center; gap: 24px;
  min-height: calc(100vh - 76px); padding: 48px 0 64px; }
.pill { display: inline-flex; align-items: center; gap: 8px; background: var(--blue-soft); color: var(--blue);
  font: 700 12px 'Poppins', sans-serif; letter-spacing: .06em; padding: 8px 16px; border-radius: 999px; }
.pill .live { width: 8px; height: 8px; border-radius: 50%; background: var(--blue); box-shadow: 0 0 0 0 rgba(45, 111, 227, .5);
  animation: live 1.8s infinite; }
@keyframes live { 70% { box-shadow: 0 0 0 8px rgba(45, 111, 227, 0); } 100% { box-shadow: 0 0 0 0 rgba(45, 111, 227, 0); } }
.hero h1 { margin: 22px 0 22px; font-weight: 800; font-size: clamp(36px, 4.6vw, 62px); line-height: 1.08; letter-spacing: -.02em; }
.hero h1 .accent { color: var(--blue); display: block; }
.hero p.lead { font-size: 18px; color: var(--muted); max-width: 520px; margin: 0 0 32px; }
.hero-ctas { display: flex; flex-wrap: wrap; gap: 14px; }
.roles-row { display: flex; flex-wrap: wrap; gap: 22px; margin-top: 38px; color: var(--muted); font-size: 14px; }
.roles-row span { display: inline-flex; align-items: center; gap: 8px; }
.roles-row svg { color: var(--blue); }

.hero-art { position: relative; justify-self: end; width: min(620px, 100%); }
.hero-art::before { /* fade into the page on the left, like the reference */
  content: ""; position: absolute; inset: -10% auto -10% -12%; width: 30%; z-index: 2;
  background: linear-gradient(90deg, #fff 10%, rgba(255, 255, 255, 0)); pointer-events: none; }
.fp { width: 100%; height: auto; display: block; filter: drop-shadow(0 30px 50px rgba(20, 33, 61, .12)); }
.fp .pc { transition: transform .2s; }
.fp .pc-ok  { fill: #9fbdf2; }
.fp .pc-rep { fill: var(--rep); animation: blink 1.6s ease-in-out infinite; }
.fp .pc-fix { fill: var(--fix); }
.fp-room { transition: opacity .25s; }
.fp.focus .fp-room { opacity: .25; }
.fp.focus .fp-room.on { opacity: 1; }
.fp-lbl { font: 700 13px 'Poppins', sans-serif; letter-spacing: .28em; fill: #7d8aa3; }
.fp-tech { fill: #fff; stroke: #b9c9e6; stroke-width: 1.5; }
.fp-tech-t { font: 700 10px 'Poppins', sans-serif; letter-spacing: .08em; fill: var(--navy); }
.fp-ping { transform-origin: 300px 300px; transform-box: view-box; animation: ping 2.4s ease-out infinite; }
@keyframes ping { 0% { transform: scale(1); opacity: .8; } 100% { transform: scale(3.2); opacity: 0; } }
@keyframes blink { 50% { opacity: .35; } }

.float-card { position: absolute; z-index: 3; background: #fff; border: 1px solid var(--line); border-radius: 14px;
  box-shadow: var(--shadow); padding: 12px 14px; display: flex; gap: 12px; align-items: center; font-size: 13px;
  animation: floaty 6s ease-in-out infinite; }
.float-card b { display: block; font: 600 13.5px 'Poppins', sans-serif; color: var(--navy); }
.float-card small { color: var(--muted); font-size: 12px; }
.float-card .ic { width: 36px; height: 36px; border-radius: 10px; display: grid; place-items: center; flex: none; }
.fc-1 { top: 1%; left: 50%; margin-left: -118px; }
.fc-1 .ic { background: #fff4e0; color: #b86e00; }
.fc-2 { top: 44%; left: -6%; animation-delay: -3s; }
.fc-2 .ic { background: #e4f5ec; color: var(--ok); }
@keyframes floaty { 50% { transform: translateY(-8px); } }
.legend { position: absolute; z-index: 3; left: 50%; transform: translateX(-50%); bottom: 1%; white-space: nowrap; display: flex; gap: 14px; background: #fff;
  border: 1px solid var(--line); border-radius: 999px; padding: 8px 16px; font-size: 12.5px; color: var(--muted); box-shadow: var(--shadow); }
.legend i { display: inline-block; width: 10px; height: 8px; border-radius: 2px; margin-right: 6px; vertical-align: 1px; }

/* ---------------------------------------------------------------- stats strip */
.strip { background: var(--navy); color: #fff; }
.strip .wrap { display: grid; grid-template-columns: repeat(4, 1fr); }
.stat { padding: 30px 24px; display: flex; gap: 16px; align-items: center; border-left: 1px solid rgba(255, 255, 255, .08); }
.stat:first-child { border-left: 0; }
.stat .num { font: 700 30px 'Poppins', sans-serif; color: #fff; line-height: 1; }
.stat .lbl { color: #b9c6e0; font-size: 14px; line-height: 1.35; }
.stat .ic { width: 46px; height: 46px; border-radius: 12px; background: rgba(91, 147, 245, .16); color: #8fb3f7;
  display: grid; place-items: center; flex: none; }

/* ---------------------------------------------------------------- sections */
section.block { padding: 104px 0; }
section.soft { background: var(--bg-soft); }
.eyebrow { font: 700 12.5px 'Poppins', sans-serif; letter-spacing: .12em; color: var(--blue); text-transform: uppercase; }
.sec-head { text-align: center; max-width: 680px; margin: 0 auto 56px; }
.sec-head h2 { font-size: clamp(28px, 3.4vw, 40px); line-height: 1.18; margin: 12px 0 14px; letter-spacing: -.01em; }
.sec-head p { color: var(--muted); margin: 0; font-size: 17px; }

/* labs */
.labs { display: grid; grid-template-columns: repeat(4, 1fr); gap: 22px; }
.lab { background: #fff; border: 1px solid var(--line); border-radius: var(--radius); padding: 24px;
  transition: transform .2s, box-shadow .2s, border-color .2s; cursor: default; }
.lab:hover, .lab.on { transform: translateY(-4px); box-shadow: var(--shadow); border-color: var(--blue-line); }
.lab-top { display: flex; align-items: center; justify-content: space-between; margin-bottom: 18px; }
.lab-num { width: 52px; height: 52px; border-radius: 14px; background: var(--blue-soft); display: grid; place-items: center; }
.lab-num svg { width: 34px; height: 34px; }
.lab-tag { font-size: 12px; font-weight: 600; color: var(--muted); background: var(--bg-soft); padding: 4px 10px; border-radius: 999px; }
.lab h3 { font-size: 20px; margin-bottom: 6px; }
.lab p { color: var(--muted); font-size: 14.5px; margin: 0; }

/* features / roles */
.tabs { display: flex; justify-content: center; gap: 8px; margin: -24px auto 44px; background: #fff; border: 1px solid var(--line);
  border-radius: 999px; padding: 6px; width: max-content; max-width: 100%; }
.tab { border: 0; background: transparent; border-radius: 999px; padding: 10px 22px; font: 600 14.5px 'Poppins', sans-serif; color: var(--muted);
  display: inline-flex; gap: 8px; align-items: center; }
.tab.on { background: var(--navy); color: #fff; }
.panel { display: none; grid-template-columns: 1fr 1.1fr; gap: 48px; align-items: center; }
.panel.on { display: grid; animation: fade .35s ease; }
@keyframes fade { from { opacity: 0; transform: translateY(8px); } }
.panel h3 { font-size: 28px; line-height: 1.25; margin: 10px 0 14px; }
.panel > div > p { color: var(--muted); margin: 0 0 24px; }
.checks { list-style: none; padding: 0; margin: 0; display: grid; gap: 14px; }
.checks li { display: flex; gap: 12px; align-items: flex-start; }
.checks li svg { color: var(--blue); margin-top: 2px; }
.checks b { font-family: 'Poppins', sans-serif; font-weight: 600; color: var(--navy); }
.feat-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
.feat { background: #fff; border: 1px solid var(--line); border-radius: var(--radius); padding: 22px; }
.feat .ic { width: 44px; height: 44px; border-radius: 12px; background: var(--blue-soft); color: var(--blue);
  display: grid; place-items: center; margin-bottom: 14px; }
.feat h4 { font-size: 16px; margin-bottom: 4px; }
.feat p { margin: 0; color: var(--muted); font-size: 14px; line-height: 1.55; }

/* how it works */
.steps { display: grid; grid-template-columns: repeat(4, 1fr); gap: 22px; counter-reset: step; position: relative; }
.steps::before { content: ""; position: absolute; top: 34px; left: 12%; right: 12%; height: 2px;
  background: repeating-linear-gradient(90deg, var(--blue-line) 0 8px, transparent 8px 16px); }
.step { position: relative; text-align: center; padding: 0 10px; }
.step .bubble { position: relative; width: 68px; height: 68px; margin: 0 auto 20px; border-radius: 50%; background: #fff;
  border: 2px solid var(--blue-line); display: grid; place-items: center; color: var(--blue); }
.step .bubble::after { counter-increment: step; content: counter(step); position: absolute; top: -6px; right: -6px; width: 24px; height: 24px;
  border-radius: 50%; background: var(--blue); color: #fff; font: 700 12px/24px 'Poppins', sans-serif; }
.step h4 { font-size: 17px; margin-bottom: 6px; }
.step p { margin: 0; color: var(--muted); font-size: 14.5px; }
.who { display: inline-block; margin-top: 12px; font-size: 12px; font-weight: 600; color: var(--blue); background: var(--blue-soft);
  padding: 3px 10px; border-radius: 999px; }

/* about */
.about { display: grid; grid-template-columns: 1fr 1fr; gap: 64px; align-items: center; }
.about-art { background: var(--navy); border-radius: 24px; padding: 44px; position: relative; overflow: hidden; }
.about-art .logo-mark circle[fill="#14213d"] { fill: #fff; }
.about-art .logo-mark circle[fill="white"] { fill: var(--navy); }
.about-art .logo-mark svg { width: 62%; height: auto; display: block; margin: 0 auto; }
.about-art .map { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 30px; }
.about-art .map div { color: #c7d7f7; font-size: 13px; display: flex; gap: 10px; align-items: flex-start; line-height: 1.45; }
.about-art .map b { color: #fff; font-family: 'Poppins', sans-serif; font-weight: 600; display: block; }
.about-art .dot { width: 10px; height: 10px; border-radius: 3px; background: #5b93f5; flex: none; margin-top: 4px; }
.about h2 { font-size: clamp(28px, 3.2vw, 38px); line-height: 1.2; margin: 12px 0 18px; }
.about p { color: var(--muted); margin: 0 0 16px; }

/* CTA + contact */
.cta { background: linear-gradient(120deg, var(--blue) 0%, var(--blue-dk) 100%); border-radius: 28px; padding: 56px;
  display: grid; grid-template-columns: 1.3fr 1fr; gap: 32px; align-items: center; color: #fff; position: relative; overflow: hidden; }
.cta::after { content: ""; position: absolute; right: -80px; top: -80px; width: 320px; height: 320px; border-radius: 50%;
  border: 46px solid rgba(255, 255, 255, .08); }
.cta h2 { color: #fff; font-size: clamp(26px, 3vw, 36px); line-height: 1.2; margin-bottom: 10px; }
.cta p { margin: 0; color: #dbe7fd; }
.cta .btns { display: flex; gap: 12px; justify-content: flex-end; flex-wrap: wrap; position: relative; z-index: 1; }
.cta .btn-white { background: #fff; color: var(--blue); }
.cta .btn-white:hover { background: #eef4fe; }
.cta .btn-line { background: transparent; color: #fff; border: 1.5px solid rgba(255, 255, 255, .5); }
.cta .btn-line:hover { border-color: #fff; }
.contact { display: grid; grid-template-columns: repeat(3, 1fr); gap: 22px; margin-top: 44px; }
.contact .card { border: 1px solid var(--line); border-radius: var(--radius); padding: 22px; display: flex; gap: 16px; align-items: flex-start; }
.contact .ic { width: 44px; height: 44px; border-radius: 12px; background: var(--blue-soft); color: var(--blue); display: grid; place-items: center; flex: none; }
.contact h4 { font-size: 16px; margin-bottom: 2px; }
.contact p { margin: 0; color: var(--muted); font-size: 14.5px; }

footer { background: var(--navy-2); color: #aab6cf; padding: 44px 0; margin-top: 104px; font-size: 14px; }
footer .wrap { display: flex; align-items: center; justify-content: space-between; gap: 24px; flex-wrap: wrap; }
footer .flogo svg { height: 46px; width: auto; display: block; }
footer nav { display: flex; gap: 24px; flex-wrap: wrap; }
footer nav a:hover { color: #fff; }

/* reveal on scroll */
.reveal { opacity: 0; transform: translateY(18px); transition: opacity .6s ease, transform .6s ease; }
.reveal.in { opacity: 1; transform: none; }

.toast { position: fixed; left: 50%; bottom: 28px; transform: translate(-50%, 20px); background: var(--navy); color: #fff;
  padding: 12px 20px; border-radius: 12px; font-size: 14px; opacity: 0; transition: .25s; z-index: 99; pointer-events: none; }
.toast.show { opacity: 1; transform: translate(-50%, 0); }

/* ---------------------------------------------------------------- responsive */
@media (max-width: 1080px) {
  .nav-links { gap: 22px; }
  .labs { grid-template-columns: repeat(2, 1fr); }
  .strip .wrap { grid-template-columns: repeat(2, 1fr); }
  .stat:nth-child(3) { border-left: 0; }
}
@media (max-width: 900px) {
  .nav-links, .nav .btn-login { display: none; }
  .menu-btn { display: block; }
  .mobile-menu.open { display: grid; gap: 4px; padding: 8px 24px 20px; border-top: 1px solid var(--line); background: #fff; }
  .mobile-menu a { padding: 12px 0; font: 500 15px 'Poppins', sans-serif; color: var(--navy); border-bottom: 1px solid var(--line); }
  .mobile-menu .btn { margin-top: 12px; }
  .hero .wrap { grid-template-columns: 1fr; min-height: 0; padding-top: 36px; }
  .hero-art { justify-self: center; max-width: 520px; }
  .hero-art::before { display: none; }
  .panel, .about, .cta { grid-template-columns: 1fr; }
  .cta { padding: 40px 28px; }
  .cta .btns { justify-content: flex-start; }
  .steps { grid-template-columns: repeat(2, 1fr); row-gap: 40px; }
  .steps::before { display: none; }
  .contact { grid-template-columns: 1fr; }
  section.block { padding: 76px 0; }
}
@media (max-width: 560px) {
  .wrap { width: calc(100% - 32px); }
  .labs, .feat-grid, .steps { grid-template-columns: 1fr; }
  .strip .wrap { grid-template-columns: 1fr; }
  .stat { border-left: 0; border-top: 1px solid rgba(255, 255, 255, .08); padding: 20px 8px; }
  .stat:first-child { border-top: 0; }
  .fc-1 { top: -4%; } .fc-2 { left: 0; top: auto; bottom: 14%; }
  .legend { bottom: -14px; }
  .tabs { width: 100%; } .tab { padding: 10px 12px; flex: 1; justify-content: center; }
  .tab svg { display: none; }
  .about-art { padding: 28px; } .about-art .map { grid-template-columns: 1fr; }
}
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation: none !important; transition: none !important; }
  html { scroll-behavior: auto; }
  .reveal { opacity: 1; transform: none; }
}
"""

NAV_HTML = r'''<header class="nav" id="nav">
  <div class="wrap">
    <a href="#home" class="nav-logo" aria-label="Computer Laboratory home"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 429 128" role="img" aria-label="Computer Laboratory"><title>Computer Laboratory</title><defs><linearGradient id="h-room" x1="0" y1="0" x2="0.35" y2="1"><stop offset="0" stop-color="#3b7cf0"/><stop offset="1" stop-color="#1d4ed8"/></linearGradient></defs><mask id="h-cut" maskUnits="userSpaceOnUse"><rect x="2" y="4" width="120" height="120" fill="white"/><rect x="57.60" y="4" width="8.80" height="120" fill="black"/><rect x="2" y="59.60" width="60" height="8.80" fill="black"/></mask>
<path d="M107.70,28.29 A58.00,58.00 0 1 0 107.70,99.71 L88.93,85.04 A34.18,34.18 0 1 1 88.93,42.96 Z" fill="url(#h-room)" mask="url(#h-cut)"/>
<circle cx="62" cy="64" r="23.30" fill="#14213d"/>
<circle cx="62" cy="64" r="13.46" fill="#ffffff"/>
<circle cx="62" cy="64" r="7.25" fill="#2d6fe3"/>
<circle cx="79.13" cy="56.91" r="1.61" fill="#ffffff"/>
<circle cx="69.09" cy="46.87" r="1.61" fill="#ffffff"/>
<circle cx="54.91" cy="46.87" r="1.61" fill="#ffffff"/>
<circle cx="44.87" cy="56.91" r="1.61" fill="#ffffff"/>
<circle cx="44.87" cy="71.09" r="1.61" fill="#ffffff"/>
<circle cx="54.91" cy="81.13" r="1.61" fill="#ffffff"/>
<circle cx="69.09" cy="81.13" r="1.61" fill="#ffffff"/>
<circle cx="79.13" cy="71.09" r="1.61" fill="#ffffff"/><path d="M112.68 57.47Q112.68 51.45 115.34 46.865Q118 42.28 122.62 39.83Q127.24 37.38 132.98 37.38Q138.72 37.38 143.34 39.83Q147.96 42.28 150.62 46.865Q153.28 51.45 153.28 57.47Q153.28 63.49 150.585 68.075Q147.89 72.66 143.235 75.11Q138.58 77.56 132.84 77.56Q127.1 77.56 122.515 75.11Q117.93 72.66 115.305 68.11Q112.68 63.56 112.68 57.47ZM141.1 57.47Q141.1 52.78 138.755 50.26Q136.41 47.74 132.98 47.74Q129.48 47.74 127.17 50.225Q124.86 52.71 124.86 57.47Q124.86 62.16 127.135 64.68Q129.41 67.2 132.84 67.2Q136.27 67.2 138.685 64.68Q141.1 62.16 141.1 57.47ZM224.18 54.18V77H212.28V55.79Q212.28 52.01 210.285 49.945Q208.29 47.88 204.79 47.88Q201.29 47.88 199.295 49.945Q197.3 52.01 197.3 55.79V77H185.4V55.79Q185.4 52.01 183.405 49.945Q181.41 47.88 177.91 47.88Q174.41 47.88 172.415 49.945Q170.42 52.01 170.42 55.79V77H158.45V37.94H170.42V42.84Q172.24 40.39 175.18 38.955Q178.12 37.52 181.83 37.52Q186.24 37.52 189.705 39.41Q193.17 41.3 195.13 44.8Q197.16 41.58 200.66 39.55Q204.16 37.52 208.29 37.52Q215.57 37.52 219.875 41.93Q224.18 46.34 224.18 54.18ZM255.39 37.38Q260.22 37.38 264.14 39.83Q268.06 42.28 270.335 46.83Q272.61 51.38 272.61 57.4Q272.61 63.42 270.335 68.005Q268.06 72.59 264.14 75.075Q260.22 77.56 255.39 77.56Q251.33 77.56 248.215 75.88Q245.1 74.2 243.35 71.54V95.62H231.38V37.94H243.35V43.47Q245.1 40.74 248.18 39.06Q251.26 37.38 255.39 37.38ZM251.82 47.81Q248.25 47.81 245.765 50.4Q243.28 52.99 243.28 57.47Q243.28 61.95 245.765 64.54Q248.25 67.13 251.82 67.13Q255.39 67.13 257.91 64.505Q260.43 61.88 260.43 57.4Q260.43 52.92 257.945 50.365Q255.46 47.81 251.82 47.81ZM316.28 37.94V77H304.31V71.68Q302.49 74.27 299.375 75.845Q296.26 77.42 292.48 77.42Q288 77.42 284.57 75.425Q281.14 73.43 279.25 69.65Q277.36 65.87 277.36 60.76V37.94H289.26V59.15Q289.26 63.07 291.29 65.24Q293.32 67.41 296.75 67.41Q300.25 67.41 302.28 65.24Q304.31 63.07 304.31 59.15V37.94ZM345.46 66.85V77H339.37Q332.86 77 329.22 73.815Q325.58 70.63 325.58 63.42V47.88H320.82V37.94H325.58V28.42H337.55V37.94H345.39V47.88H337.55V63.56Q337.55 65.31 338.39 66.08Q339.23 66.85 341.19 66.85ZM387.52 60.34H360.43Q360.71 63.98 362.775 65.905Q364.84 67.83 367.85 67.83Q372.33 67.83 374.08 64.05H386.82Q385.84 67.9 383.285 70.98Q380.73 74.06 376.88 75.81Q373.03 77.56 368.27 77.56Q362.53 77.56 358.05 75.11Q353.57 72.66 351.05 68.11Q348.53 63.56 348.53 57.47Q348.53 51.38 351.015 46.83Q353.5 42.28 357.98 39.83Q362.46 37.38 368.27 37.38Q373.94 37.38 378.35 39.76Q382.76 42.14 385.245 46.55Q387.73 50.96 387.73 56.84Q387.73 58.52 387.52 60.34ZM375.48 53.69Q375.48 50.61 373.38 48.79Q371.28 46.97 368.13 46.97Q365.12 46.97 363.055 48.72Q360.99 50.47 360.5 53.69ZM417.05 37.52V50.19H413.76Q409.28 50.19 407.04 52.115Q404.8 54.04 404.8 58.87V77H392.83V37.94H404.8V44.45Q406.9 41.23 410.05 39.375Q413.2 37.52 417.05 37.52Z" fill="#14213d"/><path d="M117.437 109.707H123.295V112H114.595V94.675H117.437ZM152.478 108.46H145.224L143.977 112H141.011L147.218 94.65H150.508L156.716 112H153.724ZM151.68 106.142 148.863 98.09 146.021 106.142ZM188.391 107.338Q188.391 108.66 187.706 109.719Q187.02 110.779 185.724 111.389Q184.428 112 182.708 112H175.778V94.675H182.384Q184.154 94.675 185.425 95.273Q186.696 95.871 187.344 96.881Q187.992 97.891 187.992 99.137Q187.992 100.633 187.195 101.63Q186.397 102.627 185.051 103.101Q186.447 103.35 187.419 104.571Q188.391 105.793 188.391 107.338ZM178.619 101.954H182.134Q183.53 101.954 184.316 101.318Q185.101 100.683 185.101 99.486Q185.101 98.314 184.316 97.654Q183.53 96.993 182.134 96.993H178.619ZM185.549 107.039Q185.549 105.768 184.677 105.02Q183.805 104.272 182.359 104.272H178.619V109.682H182.458Q183.904 109.682 184.727 108.984Q185.549 108.286 185.549 107.039ZM206.905 103.3Q206.905 100.757 208.089 98.738Q209.273 96.719 211.305 95.585Q213.336 94.451 215.754 94.451Q218.197 94.451 220.229 95.585Q222.261 96.719 223.432 98.738Q224.604 100.757 224.604 103.3Q224.604 105.843 223.432 107.874Q222.261 109.906 220.229 111.04Q218.197 112.174 215.754 112.174Q213.336 112.174 211.305 111.04Q209.273 109.906 208.089 107.874Q206.905 105.843 206.905 103.3ZM221.687 103.3Q221.687 101.381 220.927 99.935Q220.167 98.489 218.821 97.716Q217.474 96.943 215.754 96.943Q214.034 96.943 212.688 97.716Q211.342 98.489 210.582 99.935Q209.821 101.381 209.821 103.3Q209.821 105.22 210.582 106.678Q211.342 108.136 212.688 108.921Q214.034 109.707 215.754 109.707Q217.474 109.707 218.821 108.921Q220.167 108.136 220.927 106.678Q221.687 105.22 221.687 103.3ZM252.765 112 248.776 105.07H246.607V112H243.766V94.675H249.748Q251.743 94.675 253.126 95.373Q254.51 96.071 255.195 97.242Q255.881 98.414 255.881 99.86Q255.881 101.555 254.896 102.939Q253.911 104.322 251.867 104.821L256.155 112ZM246.607 102.801H249.748Q251.344 102.801 252.154 102.004Q252.964 101.206 252.964 99.86Q252.964 98.514 252.166 97.753Q251.369 96.993 249.748 96.993H246.607ZM286.335 108.46H279.081L277.834 112H274.868L281.075 94.65H284.366L290.573 112H287.581ZM285.537 106.142 282.72 98.09 279.879 106.142ZM320.828 94.675V96.993H316.216V112H313.374V96.993H308.737V94.675ZM339.117 103.3Q339.117 100.757 340.301 98.738Q341.485 96.719 343.517 95.585Q345.548 94.451 347.966 94.451Q350.409 94.451 352.441 95.585Q354.473 96.719 355.644 98.738Q356.816 100.757 356.816 103.3Q356.816 105.843 355.644 107.874Q354.473 109.906 352.441 111.04Q350.409 112.174 347.966 112.174Q345.548 112.174 343.517 111.04Q341.485 109.906 340.301 107.874Q339.117 105.843 339.117 103.3ZM353.899 103.3Q353.899 101.381 353.139 99.935Q352.379 98.489 351.032 97.716Q349.686 96.943 347.966 96.943Q346.246 96.943 344.9 97.716Q343.554 98.489 342.794 99.935Q342.033 101.381 342.033 103.3Q342.033 105.22 342.794 106.678Q343.554 108.136 344.9 108.921Q346.246 109.707 347.966 109.707Q349.686 109.707 351.032 108.921Q352.379 108.136 353.139 106.678Q353.899 105.22 353.899 103.3ZM384.977 112 380.988 105.07H378.819V112H375.978V94.675H381.96Q383.955 94.675 385.338 95.373Q386.722 96.071 387.407 97.242Q388.093 98.414 388.093 99.86Q388.093 101.555 387.108 102.939Q386.123 104.322 384.079 104.821L388.367 112ZM378.819 102.801H381.96Q383.556 102.801 384.366 102.004Q385.176 101.206 385.176 99.86Q385.176 98.514 384.378 97.753Q383.581 96.993 381.96 96.993H378.819ZM420.94 94.675 415.206 105.718V112H412.365V105.718L406.606 94.675H409.772L413.786 103.175L417.799 94.675Z" fill="#14213d"/></svg></a>
    <nav class="nav-links" aria-label="Main">
      <a href="#home" class="active">Home</a>
      <a href="#labs">Laboratories</a>
      <a href="#features">Features</a>
      <a href="#how">How It Works</a>
      <a href="#about">About Us</a>
      <a href="#contact">Contact</a>
    </nav>
    <span class="btn btn-primary btn-sm btn-login" style="visibility:hidden">Login / Register</span>
    
  </div>
  </header>'''

HERO_LEFT_HTML = r'''<span class="pill"><span class="live"></span>MONITOR. REPORT. RESOLVE.</span>
      <h1>Every Computer,<br>Every Laboratory,
        <span class="accent">Always Ready.</span></h1>
      <p class="lead">Report a broken PC in seconds, let technicians track and fix it, and see the status
        of the Centrum, IT and CSSC laboratories in one place. Less downtime, more learning.</p>'''

HERO_ROLES_HTML = r'''<div class="roles-row">
        <span><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 10 12 5 2 10l10 5 10-5z"/><path d="M6 12v5c3 2 9 2 12 0v-5"/></svg>For Teachers</span>
        <span><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.5 2.5-2.4-.6-.6-2.4z"/></svg>For Technicians</span>
        <span><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6z"/><path d="m9 12 2 2 4-4"/></svg>For Admins</span>
      </div>'''

HERO_ART_HTML = r'''<div class="hero-art" aria-hidden="false">
      <svg class="fp" viewBox="0 0 600 600" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Centrum floor plan showing computer status in each laboratory"><defs><mask id="fp-cut" maskUnits="userSpaceOnUse"><rect width="600" height="600" fill="white"/><rect x="277.0" y="0" width="46" height="600" fill="black"/><rect x="0" y="277.0" width="600" height="46" fill="black"/></mask><linearGradient id="fp-room" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#eef4fe"/><stop offset="1" stop-color="#e3ecfc"/></linearGradient></defs><circle cx="300" cy="300" r="277.0" fill="none" stroke="#f3f6fb" stroke-width="30"/><circle cx="300" cy="300" r="292" fill="none" stroke="#d5deec" stroke-width="1.5"/><g mask="url(#fp-cut)"><circle cx="300" cy="300" r="189.0" fill="none" stroke="url(#fp-room)" stroke-width="134"/><circle cx="300" cy="300" r="256" fill="none" stroke="#b9c9e6" stroke-width="2"/><circle cx="300" cy="300" r="122" fill="none" stroke="#b9c9e6" stroke-width="2"/></g><rect x="277.0" y="44" width="46" height="144" fill="#f8fafd"/><rect x="277.0" y="412" width="46" height="144" fill="#f8fafd"/><rect x="44" y="277.0" width="144" height="46" fill="#f8fafd"/><rect x="412" y="277.0" width="144" height="46" fill="#f8fafd"/><rect class="fp-tech" x="496" y="281" width="54" height="38" rx="6"/><text class="fp-tech-t" x="523" y="304" text-anchor="middle">TECH</text><circle cx="300" cy="300" r="98.0" fill="none" stroke="#14213d" stroke-width="28"/><circle cx="394.7" cy="274.6" r="3.2" fill="#ffffff" opacity=".85"/><circle cx="369.3" cy="230.7" r="3.2" fill="#ffffff" opacity=".85"/><circle cx="325.4" cy="205.3" r="3.2" fill="#ffffff" opacity=".85"/><circle cx="274.6" cy="205.3" r="3.2" fill="#ffffff" opacity=".85"/><circle cx="230.7" cy="230.7" r="3.2" fill="#ffffff" opacity=".85"/><circle cx="205.3" cy="274.6" r="3.2" fill="#ffffff" opacity=".85"/><circle cx="205.3" cy="325.4" r="3.2" fill="#ffffff" opacity=".85"/><circle cx="230.7" cy="369.3" r="3.2" fill="#ffffff" opacity=".85"/><circle cx="274.6" cy="394.7" r="3.2" fill="#ffffff" opacity=".85"/><circle cx="325.4" cy="394.7" r="3.2" fill="#ffffff" opacity=".85"/><circle cx="369.3" cy="369.3" r="3.2" fill="#ffffff" opacity=".85"/><circle cx="394.7" cy="325.4" r="3.2" fill="#ffffff" opacity=".85"/><circle cx="300" cy="300" r="84" fill="#ffffff"/><circle class="fp-ping" cx="300" cy="300" r="26" fill="none" stroke="#2d6fe3" stroke-width="2"/><circle cx="300" cy="300" r="26" fill="#2d6fe3"/><g transform="translate(288 289)" fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><rect x="1" y="1" width="22" height="15" rx="2.5"/><path d="M8 21h8M12 16v5"/></g><g class="fp-room" data-room="1"><rect class="pc pc-ok" x="335.1" y="434.8" width="14" height="10" rx="2.5" transform="rotate(-196.7 342.1 439.8)"/><rect class="pc pc-ok" x="357.4" y="426.0" width="14" height="10" rx="2.5" transform="rotate(-206.2 364.4 431.0)"/><rect class="pc pc-ok" x="378.0" y="413.7" width="14" height="10" rx="2.5" transform="rotate(-215.6 385.0 418.7)"/><rect class="pc pc-ok" x="396.2" y="398.2" width="14" height="10" rx="2.5" transform="rotate(-225.0 403.2 403.2)"/><rect class="pc pc-ok" x="411.7" y="380.0" width="14" height="10" rx="2.5" transform="rotate(-234.4 418.7 385.0)"/><rect class="pc pc-rep" x="424.0" y="359.4" width="14" height="10" rx="2.5" transform="rotate(-243.8 431.0 364.4)"/><rect class="pc pc-ok" x="432.8" y="337.1" width="14" height="10" rx="2.5" transform="rotate(-253.3 439.8 342.1)"/><rect class="pc pc-ok" x="331.8" y="462.6" width="14" height="10" rx="2.5" transform="rotate(-193.0 338.8 467.6)"/><rect class="pc pc-ok" x="354.7" y="455.6" width="14" height="10" rx="2.5" transform="rotate(-201.0 361.7 460.6)"/><rect class="pc pc-ok" x="376.4" y="445.4" width="14" height="10" rx="2.5" transform="rotate(-209.0 383.4 450.4)"/><rect class="pc pc-ok" x="396.5" y="432.4" width="14" height="10" rx="2.5" transform="rotate(-217.0 403.5 437.4)"/><rect class="pc pc-ok" x="414.6" y="416.6" width="14" height="10" rx="2.5" transform="rotate(-225.0 421.6 421.6)"/><rect class="pc pc-ok" x="430.4" y="398.5" width="14" height="10" rx="2.5" transform="rotate(-233.0 437.4 403.5)"/><rect class="pc pc-ok" x="443.4" y="378.4" width="14" height="10" rx="2.5" transform="rotate(-241.0 450.4 383.4)"/><rect class="pc pc-fix" x="453.6" y="356.7" width="14" height="10" rx="2.5" transform="rotate(-249.0 460.6 361.7)"/><rect class="pc pc-ok" x="460.6" y="333.8" width="14" height="10" rx="2.5" transform="rotate(-257.0 467.6 338.8)"/><rect class="pc pc-ok" x="328.3" y="489.8" width="14" height="10" rx="2.5" transform="rotate(-190.3 335.3 494.8)"/><rect class="pc pc-ok" x="351.6" y="484.1" width="14" height="10" rx="2.5" transform="rotate(-197.2 358.6 489.1)"/><rect class="pc pc-ok" x="374.1" y="475.6" width="14" height="10" rx="2.5" transform="rotate(-204.2 381.1 480.6)"/><rect class="pc pc-ok" x="395.3" y="464.5" width="14" height="10" rx="2.5" transform="rotate(-211.1 402.3 469.5)"/><rect class="pc pc-ok" x="415.1" y="450.9" width="14" height="10" rx="2.5" transform="rotate(-218.1 422.1 455.9)"/><rect class="pc pc-ok" x="433.0" y="435.0" width="14" height="10" rx="2.5" transform="rotate(-225.0 440.0 440.0)"/><rect class="pc pc-ok" x="448.9" y="417.1" width="14" height="10" rx="2.5" transform="rotate(-231.9 455.9 422.1)"/><rect class="pc pc-rep" x="462.5" y="397.3" width="14" height="10" rx="2.5" transform="rotate(-238.9 469.5 402.3)"/><rect class="pc pc-ok" x="473.6" y="376.1" width="14" height="10" rx="2.5" transform="rotate(-245.8 480.6 381.1)"/><rect class="pc pc-ok" x="482.1" y="353.6" width="14" height="10" rx="2.5" transform="rotate(-252.8 489.1 358.6)"/><rect class="pc pc-ok" x="487.8" y="330.3" width="14" height="10" rx="2.5" transform="rotate(-259.7 494.8 335.3)"/><rect class="pc pc-ok" x="336.6" y="514.7" width="14" height="10" rx="2.5" transform="rotate(-191.2 343.6 519.7)"/><rect class="pc pc-ok" x="359.9" y="508.8" width="14" height="10" rx="2.5" transform="rotate(-197.4 366.9 513.8)"/><rect class="pc pc-ok" x="382.4" y="500.4" width="14" height="10" rx="2.5" transform="rotate(-203.5 389.4 505.4)"/><rect class="pc pc-ok" x="403.8" y="489.7" width="14" height="10" rx="2.5" transform="rotate(-209.7 410.8 494.7)"/><rect class="pc pc-ok" x="424.0" y="476.7" width="14" height="10" rx="2.5" transform="rotate(-215.8 431.0 481.7)"/><rect class="pc pc-ok" x="442.7" y="461.6" width="14" height="10" rx="2.5" transform="rotate(-221.9 449.7 466.6)"/><rect class="pc pc-ok" x="459.6" y="444.7" width="14" height="10" rx="2.5" transform="rotate(-228.1 466.6 449.7)"/><rect class="pc pc-ok" x="474.7" y="426.0" width="14" height="10" rx="2.5" transform="rotate(-234.2 481.7 431.0)"/><rect class="pc pc-ok" x="487.7" y="405.8" width="14" height="10" rx="2.5" transform="rotate(-240.3 494.7 410.8)"/><rect class="pc pc-ok" x="498.4" y="384.4" width="14" height="10" rx="2.5" transform="rotate(-246.5 505.4 389.4)"/><rect class="pc pc-ok" x="506.8" y="361.9" width="14" height="10" rx="2.5" transform="rotate(-252.6 513.8 366.9)"/><rect class="pc pc-ok" x="512.7" y="338.6" width="14" height="10" rx="2.5" transform="rotate(-258.8 519.7 343.6)"/></g><g class="fp-room" data-room="2"><rect class="pc pc-ok" x="153.2" y="337.1" width="14" height="10" rx="2.5" transform="rotate(-106.7 160.2 342.1)"/><rect class="pc pc-ok" x="162.0" y="359.4" width="14" height="10" rx="2.5" transform="rotate(-116.2 169.0 364.4)"/><rect class="pc pc-fix" x="174.3" y="380.0" width="14" height="10" rx="2.5" transform="rotate(-125.6 181.3 385.0)"/><rect class="pc pc-ok" x="189.8" y="398.2" width="14" height="10" rx="2.5" transform="rotate(-135.0 196.8 403.2)"/><rect class="pc pc-ok" x="208.0" y="413.7" width="14" height="10" rx="2.5" transform="rotate(-144.4 215.0 418.7)"/><rect class="pc pc-ok" x="228.6" y="426.0" width="14" height="10" rx="2.5" transform="rotate(-153.8 235.6 431.0)"/><rect class="pc pc-ok" x="250.9" y="434.8" width="14" height="10" rx="2.5" transform="rotate(-163.3 257.9 439.8)"/><rect class="pc pc-ok" x="125.4" y="333.8" width="14" height="10" rx="2.5" transform="rotate(-103.0 132.4 338.8)"/><rect class="pc pc-ok" x="132.4" y="356.7" width="14" height="10" rx="2.5" transform="rotate(-111.0 139.4 361.7)"/><rect class="pc pc-rep" x="142.6" y="378.4" width="14" height="10" rx="2.5" transform="rotate(-119.0 149.6 383.4)"/><rect class="pc pc-ok" x="155.6" y="398.5" width="14" height="10" rx="2.5" transform="rotate(-127.0 162.6 403.5)"/><rect class="pc pc-ok" x="171.4" y="416.6" width="14" height="10" rx="2.5" transform="rotate(-135.0 178.4 421.6)"/><rect class="pc pc-ok" x="189.5" y="432.4" width="14" height="10" rx="2.5" transform="rotate(-143.0 196.5 437.4)"/><rect class="pc pc-ok" x="209.6" y="445.4" width="14" height="10" rx="2.5" transform="rotate(-151.0 216.6 450.4)"/><rect class="pc pc-ok" x="231.3" y="455.6" width="14" height="10" rx="2.5" transform="rotate(-159.0 238.3 460.6)"/><rect class="pc pc-ok" x="254.2" y="462.6" width="14" height="10" rx="2.5" transform="rotate(-167.0 261.2 467.6)"/><rect class="pc pc-ok" x="98.2" y="330.3" width="14" height="10" rx="2.5" transform="rotate(-100.3 105.2 335.3)"/><rect class="pc pc-ok" x="103.9" y="353.6" width="14" height="10" rx="2.5" transform="rotate(-107.2 110.9 358.6)"/><rect class="pc pc-ok" x="112.4" y="376.1" width="14" height="10" rx="2.5" transform="rotate(-114.2 119.4 381.1)"/><rect class="pc pc-ok" x="123.5" y="397.3" width="14" height="10" rx="2.5" transform="rotate(-121.1 130.5 402.3)"/><rect class="pc pc-ok" x="137.1" y="417.1" width="14" height="10" rx="2.5" transform="rotate(-128.1 144.1 422.1)"/><rect class="pc pc-ok" x="153.0" y="435.0" width="14" height="10" rx="2.5" transform="rotate(-135.0 160.0 440.0)"/><rect class="pc pc-ok" x="170.9" y="450.9" width="14" height="10" rx="2.5" transform="rotate(-141.9 177.9 455.9)"/><rect class="pc pc-ok" x="190.7" y="464.5" width="14" height="10" rx="2.5" transform="rotate(-148.9 197.7 469.5)"/><rect class="pc pc-ok" x="211.9" y="475.6" width="14" height="10" rx="2.5" transform="rotate(-155.8 218.9 480.6)"/><rect class="pc pc-ok" x="234.4" y="484.1" width="14" height="10" rx="2.5" transform="rotate(-162.8 241.4 489.1)"/><rect class="pc pc-ok" x="257.7" y="489.8" width="14" height="10" rx="2.5" transform="rotate(-169.7 264.7 494.8)"/><rect class="pc pc-ok" x="73.3" y="338.6" width="14" height="10" rx="2.5" transform="rotate(-101.2 80.3 343.6)"/><rect class="pc pc-ok" x="79.2" y="361.9" width="14" height="10" rx="2.5" transform="rotate(-107.4 86.2 366.9)"/><rect class="pc pc-ok" x="87.6" y="384.4" width="14" height="10" rx="2.5" transform="rotate(-113.5 94.6 389.4)"/><rect class="pc pc-fix" x="98.3" y="405.8" width="14" height="10" rx="2.5" transform="rotate(-119.7 105.3 410.8)"/><rect class="pc pc-ok" x="111.3" y="426.0" width="14" height="10" rx="2.5" transform="rotate(-125.8 118.3 431.0)"/><rect class="pc pc-ok" x="126.4" y="444.7" width="14" height="10" rx="2.5" transform="rotate(-131.9 133.4 449.7)"/><rect class="pc pc-ok" x="143.3" y="461.6" width="14" height="10" rx="2.5" transform="rotate(-138.1 150.3 466.6)"/><rect class="pc pc-ok" x="162.0" y="476.7" width="14" height="10" rx="2.5" transform="rotate(-144.2 169.0 481.7)"/><rect class="pc pc-ok" x="182.2" y="489.7" width="14" height="10" rx="2.5" transform="rotate(-150.3 189.2 494.7)"/><rect class="pc pc-ok" x="203.6" y="500.4" width="14" height="10" rx="2.5" transform="rotate(-156.5 210.6 505.4)"/><rect class="pc pc-ok" x="226.1" y="508.8" width="14" height="10" rx="2.5" transform="rotate(-162.6 233.1 513.8)"/><rect class="pc pc-ok" x="249.4" y="514.7" width="14" height="10" rx="2.5" transform="rotate(-168.8 256.4 519.7)"/></g><g class="fp-room" data-room="3"><rect class="pc pc-ok" x="432.8" y="252.9" width="14" height="10" rx="2.5" transform="rotate(73.3 439.8 257.9)"/><rect class="pc pc-ok" x="424.0" y="230.6" width="14" height="10" rx="2.5" transform="rotate(63.8 431.0 235.6)"/><rect class="pc pc-ok" x="411.7" y="210.0" width="14" height="10" rx="2.5" transform="rotate(54.4 418.7 215.0)"/><rect class="pc pc-rep" x="396.2" y="191.8" width="14" height="10" rx="2.5" transform="rotate(45.0 403.2 196.8)"/><rect class="pc pc-ok" x="378.0" y="176.3" width="14" height="10" rx="2.5" transform="rotate(35.6 385.0 181.3)"/><rect class="pc pc-ok" x="357.4" y="164.0" width="14" height="10" rx="2.5" transform="rotate(26.2 364.4 169.0)"/><rect class="pc pc-ok" x="335.1" y="155.2" width="14" height="10" rx="2.5" transform="rotate(16.7 342.1 160.2)"/><rect class="pc pc-ok" x="460.6" y="256.2" width="14" height="10" rx="2.5" transform="rotate(77.0 467.6 261.2)"/><rect class="pc pc-ok" x="453.6" y="233.3" width="14" height="10" rx="2.5" transform="rotate(69.0 460.6 238.3)"/><rect class="pc pc-ok" x="443.4" y="211.6" width="14" height="10" rx="2.5" transform="rotate(61.0 450.4 216.6)"/><rect class="pc pc-ok" x="430.4" y="191.5" width="14" height="10" rx="2.5" transform="rotate(53.0 437.4 196.5)"/><rect class="pc pc-ok" x="414.6" y="173.4" width="14" height="10" rx="2.5" transform="rotate(45.0 421.6 178.4)"/><rect class="pc pc-ok" x="396.5" y="157.6" width="14" height="10" rx="2.5" transform="rotate(37.0 403.5 162.6)"/><rect class="pc pc-ok" x="376.4" y="144.6" width="14" height="10" rx="2.5" transform="rotate(29.0 383.4 149.6)"/><rect class="pc pc-ok" x="354.7" y="134.4" width="14" height="10" rx="2.5" transform="rotate(21.0 361.7 139.4)"/><rect class="pc pc-ok" x="331.8" y="127.4" width="14" height="10" rx="2.5" transform="rotate(13.0 338.8 132.4)"/><rect class="pc pc-ok" x="487.8" y="259.7" width="14" height="10" rx="2.5" transform="rotate(79.7 494.8 264.7)"/><rect class="pc pc-ok" x="482.1" y="236.4" width="14" height="10" rx="2.5" transform="rotate(72.8 489.1 241.4)"/><rect class="pc pc-rep" x="473.6" y="213.9" width="14" height="10" rx="2.5" transform="rotate(65.8 480.6 218.9)"/><rect class="pc pc-ok" x="462.5" y="192.7" width="14" height="10" rx="2.5" transform="rotate(58.9 469.5 197.7)"/><rect class="pc pc-ok" x="448.9" y="172.9" width="14" height="10" rx="2.5" transform="rotate(51.9 455.9 177.9)"/><rect class="pc pc-ok" x="433.0" y="155.0" width="14" height="10" rx="2.5" transform="rotate(45.0 440.0 160.0)"/><rect class="pc pc-ok" x="415.1" y="139.1" width="14" height="10" rx="2.5" transform="rotate(38.1 422.1 144.1)"/><rect class="pc pc-ok" x="395.3" y="125.5" width="14" height="10" rx="2.5" transform="rotate(31.1 402.3 130.5)"/><rect class="pc pc-ok" x="374.1" y="114.4" width="14" height="10" rx="2.5" transform="rotate(24.2 381.1 119.4)"/><rect class="pc pc-ok" x="351.6" y="105.9" width="14" height="10" rx="2.5" transform="rotate(17.2 358.6 110.9)"/><rect class="pc pc-ok" x="328.3" y="100.2" width="14" height="10" rx="2.5" transform="rotate(10.3 335.3 105.2)"/><rect class="pc pc-rep" x="512.7" y="251.4" width="14" height="10" rx="2.5" transform="rotate(78.8 519.7 256.4)"/><rect class="pc pc-ok" x="506.8" y="228.1" width="14" height="10" rx="2.5" transform="rotate(72.6 513.8 233.1)"/><rect class="pc pc-ok" x="498.4" y="205.6" width="14" height="10" rx="2.5" transform="rotate(66.5 505.4 210.6)"/><rect class="pc pc-ok" x="487.7" y="184.2" width="14" height="10" rx="2.5" transform="rotate(60.3 494.7 189.2)"/><rect class="pc pc-ok" x="474.7" y="164.0" width="14" height="10" rx="2.5" transform="rotate(54.2 481.7 169.0)"/><rect class="pc pc-ok" x="459.6" y="145.3" width="14" height="10" rx="2.5" transform="rotate(48.1 466.6 150.3)"/><rect class="pc pc-ok" x="442.7" y="128.4" width="14" height="10" rx="2.5" transform="rotate(41.9 449.7 133.4)"/><rect class="pc pc-ok" x="424.0" y="113.3" width="14" height="10" rx="2.5" transform="rotate(35.8 431.0 118.3)"/><rect class="pc pc-ok" x="403.8" y="100.3" width="14" height="10" rx="2.5" transform="rotate(29.7 410.8 105.3)"/><rect class="pc pc-ok" x="382.4" y="89.6" width="14" height="10" rx="2.5" transform="rotate(23.5 389.4 94.6)"/><rect class="pc pc-ok" x="359.9" y="81.2" width="14" height="10" rx="2.5" transform="rotate(17.4 366.9 86.2)"/><rect class="pc pc-ok" x="336.6" y="75.3" width="14" height="10" rx="2.5" transform="rotate(11.2 343.6 80.3)"/></g><g class="fp-room" data-room="4"><rect class="pc pc-ok" x="250.9" y="155.2" width="14" height="10" rx="2.5" transform="rotate(-16.7 257.9 160.2)"/><rect class="pc pc-ok" x="228.6" y="164.0" width="14" height="10" rx="2.5" transform="rotate(-26.2 235.6 169.0)"/><rect class="pc pc-ok" x="208.0" y="176.3" width="14" height="10" rx="2.5" transform="rotate(-35.6 215.0 181.3)"/><rect class="pc pc-ok" x="189.8" y="191.8" width="14" height="10" rx="2.5" transform="rotate(-45.0 196.8 196.8)"/><rect class="pc pc-ok" x="174.3" y="210.0" width="14" height="10" rx="2.5" transform="rotate(-54.4 181.3 215.0)"/><rect class="pc pc-ok" x="162.0" y="230.6" width="14" height="10" rx="2.5" transform="rotate(-63.8 169.0 235.6)"/><rect class="pc pc-ok" x="153.2" y="252.9" width="14" height="10" rx="2.5" transform="rotate(-73.3 160.2 257.9)"/><rect class="pc pc-ok" x="254.2" y="127.4" width="14" height="10" rx="2.5" transform="rotate(-13.0 261.2 132.4)"/><rect class="pc pc-ok" x="231.3" y="134.4" width="14" height="10" rx="2.5" transform="rotate(-21.0 238.3 139.4)"/><rect class="pc pc-ok" x="209.6" y="144.6" width="14" height="10" rx="2.5" transform="rotate(-29.0 216.6 149.6)"/><rect class="pc pc-ok" x="189.5" y="157.6" width="14" height="10" rx="2.5" transform="rotate(-37.0 196.5 162.6)"/><rect class="pc pc-rep" x="171.4" y="173.4" width="14" height="10" rx="2.5" transform="rotate(-45.0 178.4 178.4)"/><rect class="pc pc-ok" x="155.6" y="191.5" width="14" height="10" rx="2.5" transform="rotate(-53.0 162.6 196.5)"/><rect class="pc pc-ok" x="142.6" y="211.6" width="14" height="10" rx="2.5" transform="rotate(-61.0 149.6 216.6)"/><rect class="pc pc-ok" x="132.4" y="233.3" width="14" height="10" rx="2.5" transform="rotate(-69.0 139.4 238.3)"/><rect class="pc pc-ok" x="125.4" y="256.2" width="14" height="10" rx="2.5" transform="rotate(-77.0 132.4 261.2)"/><rect class="pc pc-ok" x="257.7" y="100.2" width="14" height="10" rx="2.5" transform="rotate(-10.3 264.7 105.2)"/><rect class="pc pc-ok" x="234.4" y="105.9" width="14" height="10" rx="2.5" transform="rotate(-17.2 241.4 110.9)"/><rect class="pc pc-ok" x="211.9" y="114.4" width="14" height="10" rx="2.5" transform="rotate(-24.2 218.9 119.4)"/><rect class="pc pc-ok" x="190.7" y="125.5" width="14" height="10" rx="2.5" transform="rotate(-31.1 197.7 130.5)"/><rect class="pc pc-ok" x="170.9" y="139.1" width="14" height="10" rx="2.5" transform="rotate(-38.1 177.9 144.1)"/><rect class="pc pc-fix" x="153.0" y="155.0" width="14" height="10" rx="2.5" transform="rotate(-45.0 160.0 160.0)"/><rect class="pc pc-ok" x="137.1" y="172.9" width="14" height="10" rx="2.5" transform="rotate(-51.9 144.1 177.9)"/><rect class="pc pc-ok" x="123.5" y="192.7" width="14" height="10" rx="2.5" transform="rotate(-58.9 130.5 197.7)"/><rect class="pc pc-ok" x="112.4" y="213.9" width="14" height="10" rx="2.5" transform="rotate(-65.8 119.4 218.9)"/><rect class="pc pc-ok" x="103.9" y="236.4" width="14" height="10" rx="2.5" transform="rotate(-72.8 110.9 241.4)"/><rect class="pc pc-ok" x="98.2" y="259.7" width="14" height="10" rx="2.5" transform="rotate(-79.7 105.2 264.7)"/><rect class="pc pc-ok" x="249.4" y="75.3" width="14" height="10" rx="2.5" transform="rotate(-11.2 256.4 80.3)"/><rect class="pc pc-ok" x="226.1" y="81.2" width="14" height="10" rx="2.5" transform="rotate(-17.4 233.1 86.2)"/><rect class="pc pc-ok" x="203.6" y="89.6" width="14" height="10" rx="2.5" transform="rotate(-23.5 210.6 94.6)"/><rect class="pc pc-ok" x="182.2" y="100.3" width="14" height="10" rx="2.5" transform="rotate(-29.7 189.2 105.3)"/><rect class="pc pc-ok" x="162.0" y="113.3" width="14" height="10" rx="2.5" transform="rotate(-35.8 169.0 118.3)"/><rect class="pc pc-ok" x="143.3" y="128.4" width="14" height="10" rx="2.5" transform="rotate(-41.9 150.3 133.4)"/><rect class="pc pc-ok" x="126.4" y="145.3" width="14" height="10" rx="2.5" transform="rotate(-48.1 133.4 150.3)"/><rect class="pc pc-ok" x="111.3" y="164.0" width="14" height="10" rx="2.5" transform="rotate(-54.2 118.3 169.0)"/><rect class="pc pc-ok" x="98.3" y="184.2" width="14" height="10" rx="2.5" transform="rotate(-60.3 105.3 189.2)"/><rect class="pc pc-ok" x="87.6" y="205.6" width="14" height="10" rx="2.5" transform="rotate(-66.5 94.6 210.6)"/><rect class="pc pc-ok" x="79.2" y="228.1" width="14" height="10" rx="2.5" transform="rotate(-72.6 86.2 233.1)"/><rect class="pc pc-ok" x="73.3" y="251.4" width="14" height="10" rx="2.5" transform="rotate(-78.8 80.3 256.4)"/></g><defs><path id="fp-lbl-1" d="M324.5,579.9 A281.0,281.0 0 0 0 579.9,324.5"/><path id="fp-lbl-2" d="M20.1,324.5 A281.0,281.0 0 0 0 275.5,579.9"/><path id="fp-lbl-3" d="M323.8,28.0 A273.0,273.0 0 0 1 572.0,276.2"/><path id="fp-lbl-4" d="M28.0,276.2 A273.0,273.0 0 0 1 276.2,28.0"/></defs><text class="fp-lbl"><textPath href="#fp-lbl-1" startOffset="50%" text-anchor="middle" dominant-baseline="middle">CENTRUM 1</textPath></text><text class="fp-lbl"><textPath href="#fp-lbl-2" startOffset="50%" text-anchor="middle" dominant-baseline="middle">CENTRUM 2</textPath></text><text class="fp-lbl"><textPath href="#fp-lbl-3" startOffset="50%" text-anchor="middle" dominant-baseline="middle">CENTRUM 3</textPath></text><text class="fp-lbl"><textPath href="#fp-lbl-4" startOffset="50%" text-anchor="middle" dominant-baseline="middle">CENTRUM 4</textPath></text></svg>
      <div class="float-card fc-1">
        <div class="ic"><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 9v4M12 17h.01"/><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/></svg></div>
        <div><b>New report · Centrum 3</b><small>PC 12 — No display</small></div>
      </div>
      <div class="float-card fc-2">
        <div class="ic"><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="m5 13 4 4L19 7"/></svg></div>
        <div><b>Fixed · Centrum 2</b><small>PC 07 — keyboard replaced</small></div>
      </div>
      <div class="legend"><span><i style="background:#9fbdf2"></i>Working</span><span><i style="background:var(--rep)"></i>Reported</span><span><i style="background:var(--fix)"></i>Under repair</span></div>
    </div>'''

STRIP_HTML = r'''<div class="strip">
  <div class="wrap">
    <div class="stat"><div class="ic"><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></svg></div><div><div class="num">4</div><div class="lbl">Computer laboratories</div></div></div>
    <div class="stat"><div class="ic"><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/><path d="M16 4.5a3.5 3.5 0 0 1 0 7M18.5 20a6.5 6.5 0 0 0-3-5.5"/></svg></div><div><div class="num">3</div><div class="lbl">User roles, one system</div></div></div>
    <div class="stat"><div class="ic"><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12h4l3-8 4 16 3-8h4"/></svg></div><div><div class="num">Live</div><div class="lbl">PC status per laboratory</div></div></div>
    <div class="stat"><div class="ic"><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6M8 13h8M8 17h5"/></svg></div><div><div class="num">1</div><div class="lbl">Place for every report</div></div></div>
  </div>
</div>'''

LABS_HTML = r'''<section class="block" id="labs">
  <div class="wrap">
    <div class="sec-head reveal">
      <div class="eyebrow">Our Laboratories</div>
      <h2>Four labs, one circular building</h2>
      <p>Every laboratory in the Centrum building is on the map. Pick a room to report a problem or check how its computers are doing.</p>
    </div>
    <div class="labs">
      <article class="lab reveal" data-room="1"><div class="lab-top"><div class="lab-num"><svg viewBox="0 0 40 40" aria-hidden="true"><path d="M23.74,37.61 A18,18 0 0 0 37.61,23.74 L29.78,22.08 A10,10 0 0 1 22.08,29.78 Z" fill="#2d6fe3"/><path d="M2.39,23.74 A18,18 0 0 0 16.26,37.61 L17.92,29.78 A10,10 0 0 1 10.22,22.08 Z" fill="#c9d8f5"/><path d="M37.61,16.26 A18,18 0 0 0 23.74,2.39 L22.08,10.22 A10,10 0 0 1 29.78,17.92 Z" fill="#c9d8f5"/><path d="M16.26,2.39 A18,18 0 0 0 2.39,16.26 L10.22,17.92 A10,10 0 0 1 17.92,10.22 Z" fill="#c9d8f5"/><circle cx="20" cy="20" r="6" fill="#14213d"/><circle cx="20" cy="20" r="2.4" fill="#fff"/></svg></div><span class="lab-tag">Southeast wing</span></div><h3>Centrum 1</h3><p>Between the main entrance lobby and the Technician Room.</p></article>
<article class="lab reveal" data-room="2"><div class="lab-top"><div class="lab-num"><svg viewBox="0 0 40 40" aria-hidden="true"><path d="M23.74,37.61 A18,18 0 0 0 37.61,23.74 L29.78,22.08 A10,10 0 0 1 22.08,29.78 Z" fill="#c9d8f5"/><path d="M2.39,23.74 A18,18 0 0 0 16.26,37.61 L17.92,29.78 A10,10 0 0 1 10.22,22.08 Z" fill="#2d6fe3"/><path d="M37.61,16.26 A18,18 0 0 0 23.74,2.39 L22.08,10.22 A10,10 0 0 1 29.78,17.92 Z" fill="#c9d8f5"/><path d="M16.26,2.39 A18,18 0 0 0 2.39,16.26 L10.22,17.92 A10,10 0 0 1 17.92,10.22 Z" fill="#c9d8f5"/><circle cx="20" cy="20" r="6" fill="#14213d"/><circle cx="20" cy="20" r="2.4" fill="#fff"/></svg></div><span class="lab-tag">Southwest wing</span></div><h3>Centrum 2</h3><p>Beside the main entrance lobby, on the fire-exit route.</p></article>
<article class="lab reveal" data-room="3"><div class="lab-top"><div class="lab-num"><svg viewBox="0 0 40 40" aria-hidden="true"><path d="M23.74,37.61 A18,18 0 0 0 37.61,23.74 L29.78,22.08 A10,10 0 0 1 22.08,29.78 Z" fill="#c9d8f5"/><path d="M2.39,23.74 A18,18 0 0 0 16.26,37.61 L17.92,29.78 A10,10 0 0 1 10.22,22.08 Z" fill="#c9d8f5"/><path d="M37.61,16.26 A18,18 0 0 0 23.74,2.39 L22.08,10.22 A10,10 0 0 1 29.78,17.92 Z" fill="#2d6fe3"/><path d="M16.26,2.39 A18,18 0 0 0 2.39,16.26 L10.22,17.92 A10,10 0 0 1 17.92,10.22 Z" fill="#c9d8f5"/><circle cx="20" cy="20" r="6" fill="#14213d"/><circle cx="20" cy="20" r="2.4" fill="#fff"/></svg></div><span class="lab-tag">Northeast wing</span></div><h3>Centrum 3</h3><p>Just north of the Technician Room in the east lobby.</p></article>
<article class="lab reveal" data-room="4"><div class="lab-top"><div class="lab-num"><svg viewBox="0 0 40 40" aria-hidden="true"><path d="M23.74,37.61 A18,18 0 0 0 37.61,23.74 L29.78,22.08 A10,10 0 0 1 22.08,29.78 Z" fill="#c9d8f5"/><path d="M2.39,23.74 A18,18 0 0 0 16.26,37.61 L17.92,29.78 A10,10 0 0 1 10.22,22.08 Z" fill="#c9d8f5"/><path d="M37.61,16.26 A18,18 0 0 0 23.74,2.39 L22.08,10.22 A10,10 0 0 1 29.78,17.92 Z" fill="#c9d8f5"/><path d="M16.26,2.39 A18,18 0 0 0 2.39,16.26 L10.22,17.92 A10,10 0 0 1 17.92,10.22 Z" fill="#2d6fe3"/><circle cx="20" cy="20" r="6" fill="#14213d"/><circle cx="20" cy="20" r="2.4" fill="#fff"/></svg></div><span class="lab-tag">Northwest wing</span></div><h3>Centrum 4</h3><p>Near the Socio-Cultural and Publication offices.</p></article>
    </div>
  </div>
</section>'''

FEATURES_HEAD_HTML = r'''<div class="sec-head reveal">
      <div class="eyebrow">Features</div>
      <h2>Built for everyone in the lab</h2>
      <p>Each role gets its own dashboard with exactly the tools it needs.</p>
    </div>'''

HOW_HTML = r'''<section class="block" id="how">
  <div class="wrap">
    <div class="sec-head reveal">
      <div class="eyebrow">How It Works</div>
      <h2>Broken to fixed in four steps</h2>
      <p>Every report is tracked from the moment it's sent until the computer is working again.</p>
    </div>
    <div class="steps reveal">
      <div class="step"><div class="bubble"><svg class="icon" style="width:28px;height:28px" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6M12 12v5M9.5 14.5h5"/></svg></div>
        <h4>Report</h4><p>Pick the lab and PC, choose what's wrong, and send it.</p><span class="who">Teacher</span></div>
      <div class="step"><div class="bubble"><svg class="icon" style="width:28px;height:28px" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.7 21a2 2 0 0 1-3.4 0"/></svg></div>
        <h4>Get notified</h4><p>The technician sees the new report right away, with its lab and PC.</p><span class="who">Technician</span></div>
      <div class="step"><div class="bubble"><svg class="icon" style="width:28px;height:28px" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.5 2.5-2.4-.6-.6-2.4z"/></svg></div>
        <h4>Repair</h4><p>The PC is marked under repair, or escalated if it needs more help.</p><span class="who">Technician</span></div>
      <div class="step"><div class="bubble"><svg class="icon" style="width:28px;height:28px" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/></svg></div>
        <h4>Resolved</h4><p>The teacher sees it's fixed, and the admin sees it in the reports.</p><span class="who">Everyone</span></div>
    </div>
  </div>
</section>'''

ABOUT_HTML = r'''<section class="block soft" id="about">
  <div class="wrap about">
    <div class="about-art reveal">
      <div class="logo-mark"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" role="img" aria-label="Computer Laboratory"><title>Computer Laboratory</title><defs><linearGradient id="k-room" x1="0" y1="0" x2="0.35" y2="1"><stop offset="0" stop-color="#3b7cf0"/><stop offset="1" stop-color="#1d4ed8"/></linearGradient></defs><mask id="k-cut" maskUnits="userSpaceOnUse"><rect x="69.68" y="69.68" width="372.64" height="372.64" fill="white"/><rect x="242.01" y="69.68" width="27.98" height="372.64" fill="black"/><rect x="69.68" y="242.01" width="186.32" height="27.98" fill="black"/></mask>
<path d="M401.25,142.52 A184.32,184.32 0 1 0 401.25,369.48 L341.59,322.87 A108.62,108.62 0 1 1 341.59,189.13 Z" fill="url(#k-room)" mask="url(#k-cut)"/>
<circle cx="256.0" cy="256.0" r="74.06" fill="#14213d"/>
<circle cx="256.0" cy="256.0" r="42.79" fill="white"/>
<circle cx="256.0" cy="256.0" r="23.04" fill="#2d6fe3"/>
<circle cx="310.43" cy="233.45" r="5.10" fill="white"/>
<circle cx="278.55" cy="201.57" r="5.10" fill="white"/>
<circle cx="233.45" cy="201.57" r="5.10" fill="white"/>
<circle cx="201.57" cy="233.45" r="5.10" fill="white"/>
<circle cx="201.57" cy="278.55" r="5.10" fill="white"/>
<circle cx="233.45" cy="310.43" r="5.10" fill="white"/>
<circle cx="278.55" cy="310.43" r="5.10" fill="white"/>
<circle cx="310.43" cy="278.55" r="5.10" fill="white"/></svg></div>
      <div class="map">
        <div><span class="dot"></span><span><b>Four rooms</b>Centrum 1 to 4 form the ring.</span></div>
        <div><span class="dot" style="background:#fff"></span><span><b>Four lobbies</b>The gaps that divide the rooms.</span></div>
        <div><span class="dot" style="background:#9fb6e4"></span><span><b>Central hallway</b>The navy ring that joins them.</span></div>
        <div><span class="dot" style="background:#3b7cf0;border-radius:50%"></span><span><b>Monitoring core</b>This system, at the centre.</span></div>
      </div>
    </div>
    <div class="reveal">
      <div class="eyebrow">About Us</div>
      <h2>Named after, and shaped like, the building it serves</h2>
      <p>The Centrum is a circular building with four computer laboratories around a central hallway. The IT Laboratory and the CSSC Laboratory are monitored here too.
        When a computer stops working, the fix used to depend on someone passing the message along.</p>
      <p>The Computer Monitoring Management System gives teachers, technicians and admins one shared place
        to report problems, follow repairs and see how every laboratory is doing.</p>
      <p>Even the logo comes from the floor plan: four rooms, four lobbies and the hallway, arranged into the letter C.</p>
    </div>
  </div>
</section>'''

CTA_LEFT_HTML = r'''<h2>Ready to report your first issue?</h2>
        <p>Create an account as a teacher or technician. Technician accounts are confirmed by the admin first.</p>'''

CONTACT_HTML = r'''<div class="contact">
      <div class="card reveal"><div class="ic"><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 21s-7-6.2-7-11.5A7 7 0 0 1 19 9.5C19 14.8 12 21 12 21z"/><circle cx="12" cy="9.5" r="2.5"/></svg></div>
        <div><h4>Visit us</h4><p>Technician Room, east lobby of the Centrum building.</p></div></div>
      <div class="card reveal"><div class="ic"><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.5 2.5-2.4-.6-.6-2.4z"/></svg></div>
        <div><h4>Report a problem</h4><p>Log in and send a report. It goes straight to the technicians.</p></div></div>
      <div class="card reveal"><div class="ic"><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6z"/><path d="m9 12 2 2 4-4"/></svg></div>
        <div><h4>Account requests</h4><p>New technician accounts are reviewed by the laboratory admin.</p></div></div></div>'''

FOOTER_HTML = r'''<footer class="cl-footer">
  <div class="wrap">
    <a href="#home" class="flogo" aria-label="Computer Laboratory"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 429 128" role="img" aria-label="Computer Laboratory"><title>Computer Laboratory</title><defs><linearGradient id="hd-room" x1="0" y1="0" x2="0.35" y2="1"><stop offset="0" stop-color="#5b93f5"/><stop offset="1" stop-color="#2d6fe3"/></linearGradient></defs><mask id="hd-cut" maskUnits="userSpaceOnUse"><rect x="2" y="4" width="120" height="120" fill="white"/><rect x="57.60" y="4" width="8.80" height="120" fill="black"/><rect x="2" y="59.60" width="60" height="8.80" fill="black"/></mask>
<path d="M107.70,28.29 A58.00,58.00 0 1 0 107.70,99.71 L88.93,85.04 A34.18,34.18 0 1 1 88.93,42.96 Z" fill="url(#hd-room)" mask="url(#hd-cut)"/>
<circle cx="62" cy="64" r="23.30" fill="#ffffff"/>
<circle cx="62" cy="64" r="13.46" fill="#14213d"/>
<circle cx="62" cy="64" r="7.25" fill="#2d6fe3"/>
<circle cx="79.13" cy="56.91" r="1.61" fill="#14213d"/>
<circle cx="69.09" cy="46.87" r="1.61" fill="#14213d"/>
<circle cx="54.91" cy="46.87" r="1.61" fill="#14213d"/>
<circle cx="44.87" cy="56.91" r="1.61" fill="#14213d"/>
<circle cx="44.87" cy="71.09" r="1.61" fill="#14213d"/>
<circle cx="54.91" cy="81.13" r="1.61" fill="#14213d"/>
<circle cx="69.09" cy="81.13" r="1.61" fill="#14213d"/>
<circle cx="79.13" cy="71.09" r="1.61" fill="#14213d"/><path d="M112.68 57.47Q112.68 51.45 115.34 46.865Q118 42.28 122.62 39.83Q127.24 37.38 132.98 37.38Q138.72 37.38 143.34 39.83Q147.96 42.28 150.62 46.865Q153.28 51.45 153.28 57.47Q153.28 63.49 150.585 68.075Q147.89 72.66 143.235 75.11Q138.58 77.56 132.84 77.56Q127.1 77.56 122.515 75.11Q117.93 72.66 115.305 68.11Q112.68 63.56 112.68 57.47ZM141.1 57.47Q141.1 52.78 138.755 50.26Q136.41 47.74 132.98 47.74Q129.48 47.74 127.17 50.225Q124.86 52.71 124.86 57.47Q124.86 62.16 127.135 64.68Q129.41 67.2 132.84 67.2Q136.27 67.2 138.685 64.68Q141.1 62.16 141.1 57.47ZM224.18 54.18V77H212.28V55.79Q212.28 52.01 210.285 49.945Q208.29 47.88 204.79 47.88Q201.29 47.88 199.295 49.945Q197.3 52.01 197.3 55.79V77H185.4V55.79Q185.4 52.01 183.405 49.945Q181.41 47.88 177.91 47.88Q174.41 47.88 172.415 49.945Q170.42 52.01 170.42 55.79V77H158.45V37.94H170.42V42.84Q172.24 40.39 175.18 38.955Q178.12 37.52 181.83 37.52Q186.24 37.52 189.705 39.41Q193.17 41.3 195.13 44.8Q197.16 41.58 200.66 39.55Q204.16 37.52 208.29 37.52Q215.57 37.52 219.875 41.93Q224.18 46.34 224.18 54.18ZM255.39 37.38Q260.22 37.38 264.14 39.83Q268.06 42.28 270.335 46.83Q272.61 51.38 272.61 57.4Q272.61 63.42 270.335 68.005Q268.06 72.59 264.14 75.075Q260.22 77.56 255.39 77.56Q251.33 77.56 248.215 75.88Q245.1 74.2 243.35 71.54V95.62H231.38V37.94H243.35V43.47Q245.1 40.74 248.18 39.06Q251.26 37.38 255.39 37.38ZM251.82 47.81Q248.25 47.81 245.765 50.4Q243.28 52.99 243.28 57.47Q243.28 61.95 245.765 64.54Q248.25 67.13 251.82 67.13Q255.39 67.13 257.91 64.505Q260.43 61.88 260.43 57.4Q260.43 52.92 257.945 50.365Q255.46 47.81 251.82 47.81ZM316.28 37.94V77H304.31V71.68Q302.49 74.27 299.375 75.845Q296.26 77.42 292.48 77.42Q288 77.42 284.57 75.425Q281.14 73.43 279.25 69.65Q277.36 65.87 277.36 60.76V37.94H289.26V59.15Q289.26 63.07 291.29 65.24Q293.32 67.41 296.75 67.41Q300.25 67.41 302.28 65.24Q304.31 63.07 304.31 59.15V37.94ZM345.46 66.85V77H339.37Q332.86 77 329.22 73.815Q325.58 70.63 325.58 63.42V47.88H320.82V37.94H325.58V28.42H337.55V37.94H345.39V47.88H337.55V63.56Q337.55 65.31 338.39 66.08Q339.23 66.85 341.19 66.85ZM387.52 60.34H360.43Q360.71 63.98 362.775 65.905Q364.84 67.83 367.85 67.83Q372.33 67.83 374.08 64.05H386.82Q385.84 67.9 383.285 70.98Q380.73 74.06 376.88 75.81Q373.03 77.56 368.27 77.56Q362.53 77.56 358.05 75.11Q353.57 72.66 351.05 68.11Q348.53 63.56 348.53 57.47Q348.53 51.38 351.015 46.83Q353.5 42.28 357.98 39.83Q362.46 37.38 368.27 37.38Q373.94 37.38 378.35 39.76Q382.76 42.14 385.245 46.55Q387.73 50.96 387.73 56.84Q387.73 58.52 387.52 60.34ZM375.48 53.69Q375.48 50.61 373.38 48.79Q371.28 46.97 368.13 46.97Q365.12 46.97 363.055 48.72Q360.99 50.47 360.5 53.69ZM417.05 37.52V50.19H413.76Q409.28 50.19 407.04 52.115Q404.8 54.04 404.8 58.87V77H392.83V37.94H404.8V44.45Q406.9 41.23 410.05 39.375Q413.2 37.52 417.05 37.52Z" fill="#ffffff"/><path d="M117.437 109.707H123.295V112H114.595V94.675H117.437ZM152.478 108.46H145.224L143.977 112H141.011L147.218 94.65H150.508L156.716 112H153.724ZM151.68 106.142 148.863 98.09 146.021 106.142ZM188.391 107.338Q188.391 108.66 187.706 109.719Q187.02 110.779 185.724 111.389Q184.428 112 182.708 112H175.778V94.675H182.384Q184.154 94.675 185.425 95.273Q186.696 95.871 187.344 96.881Q187.992 97.891 187.992 99.137Q187.992 100.633 187.195 101.63Q186.397 102.627 185.051 103.101Q186.447 103.35 187.419 104.571Q188.391 105.793 188.391 107.338ZM178.619 101.954H182.134Q183.53 101.954 184.316 101.318Q185.101 100.683 185.101 99.486Q185.101 98.314 184.316 97.654Q183.53 96.993 182.134 96.993H178.619ZM185.549 107.039Q185.549 105.768 184.677 105.02Q183.805 104.272 182.359 104.272H178.619V109.682H182.458Q183.904 109.682 184.727 108.984Q185.549 108.286 185.549 107.039ZM206.905 103.3Q206.905 100.757 208.089 98.738Q209.273 96.719 211.305 95.585Q213.336 94.451 215.754 94.451Q218.197 94.451 220.229 95.585Q222.261 96.719 223.432 98.738Q224.604 100.757 224.604 103.3Q224.604 105.843 223.432 107.874Q222.261 109.906 220.229 111.04Q218.197 112.174 215.754 112.174Q213.336 112.174 211.305 111.04Q209.273 109.906 208.089 107.874Q206.905 105.843 206.905 103.3ZM221.687 103.3Q221.687 101.381 220.927 99.935Q220.167 98.489 218.821 97.716Q217.474 96.943 215.754 96.943Q214.034 96.943 212.688 97.716Q211.342 98.489 210.582 99.935Q209.821 101.381 209.821 103.3Q209.821 105.22 210.582 106.678Q211.342 108.136 212.688 108.921Q214.034 109.707 215.754 109.707Q217.474 109.707 218.821 108.921Q220.167 108.136 220.927 106.678Q221.687 105.22 221.687 103.3ZM252.765 112 248.776 105.07H246.607V112H243.766V94.675H249.748Q251.743 94.675 253.126 95.373Q254.51 96.071 255.195 97.242Q255.881 98.414 255.881 99.86Q255.881 101.555 254.896 102.939Q253.911 104.322 251.867 104.821L256.155 112ZM246.607 102.801H249.748Q251.344 102.801 252.154 102.004Q252.964 101.206 252.964 99.86Q252.964 98.514 252.166 97.753Q251.369 96.993 249.748 96.993H246.607ZM286.335 108.46H279.081L277.834 112H274.868L281.075 94.65H284.366L290.573 112H287.581ZM285.537 106.142 282.72 98.09 279.879 106.142ZM320.828 94.675V96.993H316.216V112H313.374V96.993H308.737V94.675ZM339.117 103.3Q339.117 100.757 340.301 98.738Q341.485 96.719 343.517 95.585Q345.548 94.451 347.966 94.451Q350.409 94.451 352.441 95.585Q354.473 96.719 355.644 98.738Q356.816 100.757 356.816 103.3Q356.816 105.843 355.644 107.874Q354.473 109.906 352.441 111.04Q350.409 112.174 347.966 112.174Q345.548 112.174 343.517 111.04Q341.485 109.906 340.301 107.874Q339.117 105.843 339.117 103.3ZM353.899 103.3Q353.899 101.381 353.139 99.935Q352.379 98.489 351.032 97.716Q349.686 96.943 347.966 96.943Q346.246 96.943 344.9 97.716Q343.554 98.489 342.794 99.935Q342.033 101.381 342.033 103.3Q342.033 105.22 342.794 106.678Q343.554 108.136 344.9 108.921Q346.246 109.707 347.966 109.707Q349.686 109.707 351.032 108.921Q352.379 108.136 353.139 106.678Q353.899 105.22 353.899 103.3ZM384.977 112 380.988 105.07H378.819V112H375.978V94.675H381.96Q383.955 94.675 385.338 95.373Q386.722 96.071 387.407 97.242Q388.093 98.414 388.093 99.86Q388.093 101.555 387.108 102.939Q386.123 104.322 384.079 104.821L388.367 112ZM378.819 102.801H381.96Q383.556 102.801 384.366 102.004Q385.176 101.206 385.176 99.86Q385.176 98.514 384.378 97.753Q383.581 96.993 381.96 96.993H378.819ZM420.94 94.675 415.206 105.718V112H412.365V105.718L406.606 94.675H409.772L413.786 103.175L417.799 94.675Z" fill="#c7d7f7"/></svg></a>
    <nav><a href="#labs">Laboratories</a><a href="#features">Features</a><a href="#how">How It Works</a><a href="#about">About Us</a><a href="#contact">Contact</a></nav>
    <div>© <span id="yr">2026</span> Computer Laboratory · Computer Monitoring Management System</div>
  </div>
</footer>'''

# role -> (left column HTML, button label, 'login' or 'signup', feature-card grid HTML)
PANELS = {
    'teacher': (r'''<div class="eyebrow">For teachers</div><h3>Report issues in seconds, then follow the fix</h3><p>Spot a problem during class? Send it to the technicians without leaving the room.</p><ul class="checks"><li><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/></svg><span><b>Report a PC problem</b> — pick the lab, the PC and what's wrong.</span></li><li><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/></svg><span><b>Follow every report</b> — see when it's received, being repaired, and fixed.</span></li><li><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/></svg><span><b>Keep your details current</b> — update your contact number and email in your profile.</span></li></ul>''', 'Sign up as a teacher', 'signup',
             r'''<div class="feat-grid"><div class="feat"><div class="ic"><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6M12 12v5M9.5 14.5h5"/></svg></div><h4>Quick reports</h4><p>A short guided form with a review step before sending.</p></div><div class="feat"><div class="ic"><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg></div><h4>Live status</h4><p>Each report shows where it is right now.</p></div><div class="feat"><div class="ic"><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5M12 8v4l3 2"/></svg></div><h4>Report history</h4><p>All your past reports in one list.</p></div><div class="feat"><div class="ic"><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/></svg></div><h4>Your profile</h4><p>Your name, email and number, always up to date.</p></div></div>'''),
    'technician': (r'''<div class="eyebrow">For technicians</div><h3>Fix, track, and analyze every laboratory</h3><p>Every new report lands in one queue, with the lab and PC already filled in.</p><ul class="checks"><li><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/></svg><span><b>See new reports first</b> — sorted so nothing gets missed.</span></li><li><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/></svg><span><b>Update the repair status</b> — so teachers know what's happening.</span></li><li><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/></svg><span><b>Escalate the hard cases</b> — when a PC needs parts or the admin's help.</span></li></ul>''', 'Sign up as a technician', 'signup',
             r'''<div class="feat-grid"><div class="feat"><div class="ic"><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 6h16M4 12h16M4 18h10"/></svg></div><h4>Report queue</h4><p>One list for every laboratory.</p></div><div class="feat"><div class="ic"><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.5 2.5-2.4-.6-.6-2.4z"/></svg></div><h4>Repair updates</h4><p>Mark PCs under repair or fixed.</p></div><div class="feat"><div class="ic"><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5M5 12l7-7 7 7"/></svg></div><h4>Escalation</h4><p>Pass bigger problems to the admin.</p></div><div class="feat"><div class="ic"><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/></svg></div><h4>Analytics</h4><p>See which labs and PCs break most often.</p></div></div>'''),
    'admin': (r'''<div class="eyebrow">For admins</div><h3>See every lab, every report, every account</h3><p>Keep every laboratory running and decide who gets access.</p><ul class="checks"><li><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/></svg><span><b>Approve new accounts</b> — technician requests wait for your confirmation.</span></li><li><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/></svg><span><b>Watch every laboratory</b> — reports and PC status across the Centrum, IT and CSSC laboratories.</span></li><li><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/></svg><span><b>Handle escalations</b> — and keep the computer inventory current.</span></li></ul>''', 'Admin log in', 'login',
             r'''<div class="feat-grid"><div class="feat"><div class="ic"><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/><path d="M16 4.5a3.5 3.5 0 0 1 0 7M18.5 20a6.5 6.5 0 0 0-3-5.5"/></svg></div><h4>User requests</h4><p>Confirm or decline new sign-ups.</p></div><div class="feat"><div class="ic"><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6M8 13h8M8 17h5"/></svg></div><h4>Reports</h4><p>Every report from every lab.</p></div><div class="feat"><div class="ic"><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 8 12 3 3 8v8l9 5 9-5z"/><path d="M3 8l9 5 9-5M12 13v8"/></svg></div><h4>Inventory</h4><p>Every computer, its specs and history.</p></div><div class="feat"><div class="ic"><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 9v4M12 17h.01"/><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/></svg></div><h4>Escalations</h4><p>Problems that need your decision.</p></div></div>'''),
}


if __name__ == "__main__":
    render()
