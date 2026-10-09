"""
app.py - Centrum Laboratory | main entry point (Streamlit)

Run from the project root (CL Monitoring System/), in two terminals:

    uvicorn backend.main:app --reload      # 1) FastAPI backend
    streamlit run app.py                   # 2) this app

What happens
------------
1. Centrum logo intro   - plays once per browser visit (about 4 seconds), then fades out.
2. Homepage (Home.py)   - nav links scroll to their section; "Log in", "Register",
                          "Get Started", the lab cards and "Sign up" open the login screens.
3. Log In / Sign Up / Reset password (frontend/NewLogin.py).
   NewLogin talks to the FastAPI backend through frontend/backend_client.py.
   The backend (backend/main.py -> auth_service.py -> users_repository.py ->
   database.py) checks passwords with Supabase Auth, reads the Supabase
   "Users" table, and sends codes by email through email_service.py (Brevo).
4. After a successful login, opens the right dashboard for the user's role:
       Admin      -> frontend/admin.py
                     (data through backend_client -> backend/admin_service.py)
       Teacher    -> Teacher.py
       Technician -> frontend/technician.py
                     (data through backend_client -> backend/technician_service.py)
   The role name comes from Users.RoleId (ROLE_ID_ADMIN, ROLE_ID_TEACHER,
   ROLE_ID_TECHNICIAN in .env, or a Roles table).
   The "Log out" button on every dashboard brings you back to the login screen.

This file contains no database, authentication or email code and needs no
Supabase or Brevo keys - those stay in the backend.

Every screen is built in Python with Streamlit and keeps the look of the
HTML designs: the admin, technician and teacher dashboards share one design
(stylesheet and floor map in frontend/portal_design.py, the shared sidebar,
top bar, floor map and pop-ups in frontend/portal.py, data helpers in
frontend/lab_data.py, small Streamlit helpers in frontend/ui.py). The
centrum-laboratory-*.html files are no longer needed.

Files that must sit in the same folder as app.py:
    Teacher.py, Home.py (frontend/Home.py also works)

Shared lab data (inventory, teacher reports, maintenance logs, notifications):
    data/centrum_lab.json  - created on first run; fill / top up the inventory with
                             python -m frontend.seed_inventory   (safe to re-run)

Brand files (optional, all included in the project zip):
    assets/logo.png        Centrum Laboratory logo - login card
    assets/logo-icon.png   the "C" mark - browser-tab icon
    assets/logo-stacked.png, assets/logo-white.png   other versions of the logo
    media/centrum-intro.mp4, media/centrum-intro.gif the logo intro as a video / GIF
    media/homepage.png, media/homepage-hero.png      pictures of the homepage
    (optional) isu.jpg campus photo for the login screen
"""

from __future__ import annotations

import logging

import streamlit as st

from frontend import NewLogin
from frontend import ui

try:  # Home.py may sit next to app.py (preferred) or inside frontend/
    import Home
except ImportError:
    from frontend import Home

logger = logging.getLogger("centrum.app")

PLAY_INTRO = True  # set to False to skip the logo intro

ss = st.session_state


# ---------------------------------------------------------------------------
# Moving between screens
# ---------------------------------------------------------------------------
def open_login() -> None:
    ss["cl_view"] = "auth"
    NewLogin.show("login")


def open_signup() -> None:
    ss["cl_view"] = "auth"
    NewLogin.show("signup")


def back_home() -> None:
    ss["cl_view"] = "home"


def play_intro_once() -> None:
    """The logo intro, drawn on top of the page (pure SVG + CSS, so nothing waits for it)."""
    if not PLAY_INTRO or ss.get("cl_intro_shown"):
        return
    ss["cl_intro_shown"] = True
    st.markdown(INTRO_HTML, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------
def _teacher_module():
    try:  # Teacher.py sits next to app.py (or inside frontend/)
        import Teacher
    except ImportError:
        from frontend import Teacher
    return Teacher


def _back_to_login() -> None:
    ui.logout_user()


def _open_dashboard(user: dict) -> None:
    role = ui.normalize_user(user)["role"].lower()  # role / role_name / Users.RoleId
    welcome = ss.pop("cl_welcome", None)
    if welcome:
        st.toast(f"Welcome back, {welcome.split()[0]}!", icon="👋")
    try:
        if role in ("admin", "administrator"):
            from frontend import admin

            admin.render(user)
        elif role == "teacher":
            _teacher_module().render(user)
        elif role == "technician":
            from frontend import technician

            technician.render(user)
        else:
            st.error(
                f"Your account has no known role ({user.get('role') or 'none'}) in the Users table, "
                "so no dashboard can open. Please contact the admin."
            )
            st.button("Back to log in", on_click=_back_to_login, type="primary")
    except Exception as exc:  # show a friendly message instead of a traceback
        if type(exc).__name__ in ("StopException", "RerunException"):  # Streamlit's own control flow
            raise
        logger.exception("Dashboard failed for role %s", role)
        st.error("Something went wrong while opening your dashboard. Please try again.")
        c1, c2 = st.columns(2)
        c1.button("Try again", key="cl_retry")
        c2.button("Back to log in", key="cl_err_back", on_click=_back_to_login)
    st.stop()


def main() -> None:
    ss.setdefault("cl_view", "home")

    # 4. Signed in: open the dashboard (dashboards set their own wide layout).
    user = ss.get("auth_user")
    if ss.get("authenticated") and isinstance(user, dict) and user:
        _open_dashboard(user)

    # 2. Homepage, with the intro on top of it the first time.
    if ss["cl_view"] == "home":
        Home.render(on_login=open_login, on_signup=open_signup)
        play_intro_once()
        return

    # 3. Log In / Sign Up. The login button reruns the app, and the next run
    #    lands in _open_dashboard above.
    if NewLogin.require_login(on_back=back_home):
        _open_dashboard(ss.get("auth_user") or {})
    play_intro_once()  # in case someone lands here first


# ---------------------------------------------------------------------------
# The logo intro (SVG + CSS). A video version is in media/centrum-intro.mp4.
# ---------------------------------------------------------------------------
INTRO_HTML = r'''<style>
.cli-splash {
  position: fixed; inset: 0; z-index: 2147483000;
  display: flex; align-items: center; justify-content: center;
  background: radial-gradient(ellipse at 50% 45%, #182a52 0%, #0f1a33 62%);
  animation: cli-out .6s ease-in 4.0s forwards;
}
.cli-logo { width: min(560px, 84vw); height: auto; overflow: visible; }
.cli-logo * { transform-box: view-box; }

/* core pops in, then the pulse rings ripple out */
.cli-core { transform-origin: 62px 64px; transform: scale(0);
  animation: cli-pop .45s cubic-bezier(.34,1.56,.64,1) .15s forwards, cli-beat 1.1s ease-in-out 3.0s 1; }
.cli-pulse { transform-origin: 62px 64px; opacity: 0; }
.cli-pulse1 { animation: cli-ripple 1.1s ease-out .35s forwards; }
.cli-pulse2 { animation: cli-ripple 1.1s ease-out .75s forwards; }

/* hallway ring draws itself, columns switch on like PCs booting */
.cli-hall { animation: cli-draw .6s cubic-bezier(.65,0,.35,1) .45s forwards; }
.cli-dot { opacity: 0; animation: cli-fade .18s ease-out forwards; }

/* the four Centrum rooms slide in from outside, in floor-plan order */
.cli-room { opacity: 0; transform-origin: 62px 64px; }
.cli-room-se { animation: cli-room-se .55s cubic-bezier(.22,1,.36,1) .85s forwards; }
.cli-room-sw { animation: cli-room-sw .55s cubic-bezier(.22,1,.36,1) .97s forwards; }
.cli-room-ne { animation: cli-room-ne .55s cubic-bezier(.22,1,.36,1) 1.09s forwards; }
.cli-room-nw { animation: cli-room-nw .55s cubic-bezier(.22,1,.36,1) 1.21s forwards; }

/* the mark builds in the centre, then slides left to make room for the name */
.cli-mark { transform: translateX(129.0px);
  animation: cli-slide .75s cubic-bezier(.65,0,.35,1) 1.55s forwards; }
@keyframes cli-slide { to { transform: none; } }

/* wordmark: letters rise, LABORATORY closes its spacing */
.cli-letter { opacity: 0; transform: translateY(18px);
  animation: cli-rise .5s cubic-bezier(.22,1,.36,1) forwards; }
.cli-sub { opacity: 0; transform-origin: 111px 107px;
  animation: cli-track .8s cubic-bezier(.22,1,.36,1) 2.35s forwards; }

@keyframes cli-pop    { to { transform: scale(1); } }
@keyframes cli-beat   { 0%,100% { transform: scale(1); } 50% { transform: scale(1.18); } }
@keyframes cli-ripple { 0% { opacity: .9; transform: scale(1); } 100% { opacity: 0; transform: scale(7.5); } }
@keyframes cli-draw   { to { stroke-dashoffset: 0; } }
@keyframes cli-fade   { to { opacity: 1; } }
@keyframes cli-rise   { to { opacity: 1; transform: none; } }
@keyframes cli-track  { from { opacity: 0; transform: scaleX(1.25); } to { opacity: 1; transform: none; } }
@keyframes cli-room-se { from { transform: translate(14px,14px) scale(.9); } to { opacity: 1; transform: none; } }
@keyframes cli-room-sw { from { transform: translate(-14px,14px) scale(.9); } to { opacity: 1; transform: none; } }
@keyframes cli-room-ne { from { transform: translate(14px,-14px) scale(.9); } to { opacity: 1; transform: none; } }
@keyframes cli-room-nw { from { transform: translate(-14px,-14px) scale(.9); } to { opacity: 1; transform: none; } }
@keyframes cli-out {
  0%   { opacity: 1; }
  99%  { opacity: 0; visibility: visible; }
  100% { opacity: 0; visibility: hidden; pointer-events: none; }
}
@media (prefers-reduced-motion: reduce) { .cli-splash { display: none; } }
</style><div class="cli-splash"><svg class="cli-logo" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 382 128" role="img" aria-label="Centrum Laboratory"><defs><linearGradient id="cli-room" x1="0" y1="0" x2="0.35" y2="1"><stop offset="0" stop-color="#5b93f5"/><stop offset="1" stop-color="#2d6fe3"/></linearGradient><mask id="cli-cut" maskUnits="userSpaceOnUse"><rect x="2" y="4" width="120" height="120" fill="white"/><rect x="57.60" y="4" width="8.80" height="120" fill="black"/><rect x="2" y="59.60" width="60" height="8.80" fill="black"/></mask><clipPath id="cli-q-se"><rect x="62" y="64" width="60" height="60"/></clipPath><clipPath id="cli-q-sw"><rect x="2" y="64" width="60" height="60"/></clipPath><clipPath id="cli-q-ne"><rect x="62" y="4" width="60" height="60"/></clipPath><clipPath id="cli-q-nw"><rect x="2" y="4" width="60" height="60"/></clipPath></defs><g class="cli-mark"><circle class="cli-pulse cli-pulse1" cx="62" cy="64" r="7.25" fill="none" stroke="#5b93f5" stroke-width="2"/><circle class="cli-pulse cli-pulse2" cx="62" cy="64" r="7.25" fill="none" stroke="#5b93f5" stroke-width="2"/><g class="cli-room cli-room-se"><g clip-path="url(#cli-q-se)"><path d="M107.70,28.29 A58.00,58.00 0 1 0 107.70,99.71 L88.93,85.04 A34.18,34.18 0 1 1 88.93,42.96 Z" fill="url(#cli-room)" mask="url(#cli-cut)"/></g></g><g class="cli-room cli-room-sw"><g clip-path="url(#cli-q-sw)"><path d="M107.70,28.29 A58.00,58.00 0 1 0 107.70,99.71 L88.93,85.04 A34.18,34.18 0 1 1 88.93,42.96 Z" fill="url(#cli-room)" mask="url(#cli-cut)"/></g></g><g class="cli-room cli-room-ne"><g clip-path="url(#cli-q-ne)"><path d="M107.70,28.29 A58.00,58.00 0 1 0 107.70,99.71 L88.93,85.04 A34.18,34.18 0 1 1 88.93,42.96 Z" fill="url(#cli-room)" mask="url(#cli-cut)"/></g></g><g class="cli-room cli-room-nw"><g clip-path="url(#cli-q-nw)"><path d="M107.70,28.29 A58.00,58.00 0 1 0 107.70,99.71 L88.93,85.04 A34.18,34.18 0 1 1 88.93,42.96 Z" fill="url(#cli-room)" mask="url(#cli-cut)"/></g></g><circle class="cli-hall" cx="62" cy="64" r="18.38" fill="none" stroke="#ffffff" stroke-width="9.84" stroke-dasharray="115.51" stroke-dashoffset="115.51" transform="rotate(-90 62 64)"/><circle class="cli-dot" style="animation-delay:0.95s" cx="69.09" cy="46.87" r="1.61" fill="#0f1a33"/><circle class="cli-dot" style="animation-delay:1.01s" cx="79.13" cy="56.91" r="1.61" fill="#0f1a33"/><circle class="cli-dot" style="animation-delay:1.07s" cx="79.13" cy="71.09" r="1.61" fill="#0f1a33"/><circle class="cli-dot" style="animation-delay:1.13s" cx="69.09" cy="81.13" r="1.61" fill="#0f1a33"/><circle class="cli-dot" style="animation-delay:1.19s" cx="54.91" cy="81.13" r="1.61" fill="#0f1a33"/><circle class="cli-dot" style="animation-delay:1.25s" cx="44.87" cy="71.09" r="1.61" fill="#0f1a33"/><circle class="cli-dot" style="animation-delay:1.31s" cx="44.87" cy="56.91" r="1.61" fill="#0f1a33"/><circle class="cli-dot" style="animation-delay:1.37s" cx="54.91" cy="46.87" r="1.61" fill="#0f1a33"/><circle class="cli-core" cx="62" cy="64" r="7.25" fill="#3b7cf0"/></g><path class="cli-letter" style="animation-delay:1.95s" d="M151.67000000000002 60.34H124.58Q124.86 63.98 126.92500000000001 65.905Q128.99 67.83 132.0 67.83Q136.48 67.83 138.23 64.05H150.97Q149.99 67.9 147.435 70.98Q144.88 74.06 141.03 75.81Q137.18 77.56 132.42000000000002 77.56Q126.68 77.56 122.2 75.11Q117.72 72.66 115.19999999999999 68.11Q112.67999999999999 63.56 112.67999999999999 57.47Q112.67999999999999 51.379999999999995 115.16499999999999 46.83Q117.65 42.279999999999994 122.13 39.83Q126.61 37.379999999999995 132.42000000000002 37.379999999999995Q138.09 37.379999999999995 142.5 39.75999999999999Q146.91 42.13999999999999 149.39499999999998 46.55Q151.88 50.959999999999994 151.88 56.839999999999996Q151.88 58.519999999999996 151.67000000000002 60.34ZM139.63 53.69Q139.63 50.61 137.53 48.79Q135.43 46.97 132.28 46.97Q129.27 46.97 127.20500000000001 48.72Q125.14 50.47 124.65 53.69Z" fill="#ffffff"/><path class="cli-letter" style="animation-delay:2.02s" d="M195.82999999999998 54.17999999999999V77.0H183.92999999999998V55.79Q183.92999999999998 51.87 181.89999999999998 49.7Q179.87 47.53 176.44 47.53Q173.01 47.53 170.98 49.7Q168.95 51.87 168.95 55.79V77.0H156.98V37.94H168.95V43.12Q170.76999999999998 40.529999999999994 173.84999999999997 39.02499999999999Q176.92999999999998 37.519999999999996 180.78 37.519999999999996Q187.64 37.519999999999996 191.73499999999999 41.964999999999996Q195.82999999999998 46.41 195.82999999999998 54.17999999999999Z" fill="#ffffff"/><path class="cli-letter" style="animation-delay:2.09s" d="M224.73000000000002 66.85V77.0H218.64000000000001Q212.13 77.0 208.49 73.815Q204.85 70.63 204.85 63.42V47.879999999999995H200.09V37.94H204.85V28.419999999999995H216.82V37.94H224.66V47.879999999999995H216.82V63.56Q216.82 65.31 217.66 66.08Q218.5 66.85 220.46 66.85Z" fill="#ffffff"/><path class="cli-letter" style="animation-delay:2.16s" d="M254.4 37.519999999999996V50.19H251.11Q246.63 50.19 244.39 52.114999999999995Q242.15 54.04 242.15 58.87V77.0H230.18V37.94H242.15V44.449999999999996Q244.25 41.23 247.4 39.375Q250.55 37.519999999999996 254.4 37.519999999999996Z" fill="#ffffff"/><path class="cli-letter" style="animation-delay:2.23s" d="M297.51000000000005 37.94V77.0H285.54V71.68Q283.72 74.27 280.605 75.845Q277.49 77.42 273.71000000000004 77.42Q269.23 77.42 265.8 75.42500000000001Q262.37 73.43 260.48 69.65Q258.59000000000003 65.87 258.59000000000003 60.76V37.94H270.49V59.15Q270.49 63.07 272.52 65.24Q274.55 67.41 277.98 67.41Q281.48 67.41 283.51 65.24Q285.54 63.07 285.54 59.15V37.94Z" fill="#ffffff"/><path class="cli-letter" style="animation-delay:2.30s" d="M370.65000000000003 54.17999999999999V77.0H358.75000000000006V55.79Q358.75000000000006 52.01 356.75500000000005 49.94499999999999Q354.76000000000005 47.879999999999995 351.26000000000005 47.879999999999995Q347.76000000000005 47.879999999999995 345.76500000000004 49.94499999999999Q343.77000000000004 52.01 343.77000000000004 55.79V77.0H331.87000000000006V55.79Q331.87000000000006 52.01 329.87500000000006 49.94499999999999Q327.88000000000005 47.879999999999995 324.38000000000005 47.879999999999995Q320.88000000000005 47.879999999999995 318.88500000000005 49.94499999999999Q316.89000000000004 52.01 316.89000000000004 55.79V77.0H304.92V37.94H316.89000000000004V42.839999999999996Q318.71000000000004 40.38999999999999 321.65000000000003 38.955Q324.59000000000003 37.519999999999996 328.30000000000007 37.519999999999996Q332.71000000000004 37.519999999999996 336.17500000000007 39.41Q339.64000000000004 41.3 341.6 44.8Q343.63000000000005 41.58 347.13000000000005 39.55Q350.63000000000005 37.519999999999996 354.76000000000005 37.519999999999996Q362.0400000000001 37.519999999999996 366.345 41.92999999999999Q370.65000000000003 46.339999999999996 370.65000000000003 54.17999999999999Z" fill="#ffffff"/><g class="cli-sub"><path d="M117.445 109.7H123.32V112.0H114.595V94.625H117.445Z" fill="#c7d7f7"/><path d="M147.33277777777778 108.45H140.05777777777777L138.80777777777777 112.0H135.83277777777778L142.05777777777777 94.6H145.35777777777778L151.58277777777778 112.0H148.58277777777778ZM146.5327777777778 106.125 143.70777777777778 98.05 140.85777777777778 106.125Z" fill="#c7d7f7"/><path d="M178.09555555555556 107.325Q178.09555555555556 108.65 177.40805555555556 109.7125Q176.72055555555556 110.775 175.42055555555555 111.3875Q174.12055555555557 112.0 172.39555555555555 112.0H165.44555555555556V94.625H172.07055555555556Q173.84555555555556 94.625 175.12055555555554 95.225Q176.39555555555555 95.825 177.04555555555555 96.8375Q177.69555555555556 97.85 177.69555555555556 99.1Q177.69555555555556 100.6 176.89555555555557 101.6Q176.09555555555556 102.6 174.74555555555557 103.075Q176.14555555555555 103.325 177.12055555555554 104.55000000000001Q178.09555555555556 105.775 178.09555555555556 107.325ZM168.29555555555555 101.925H171.82055555555556Q173.22055555555556 101.925 174.00805555555556 101.2875Q174.79555555555555 100.65 174.79555555555555 99.45Q174.79555555555555 98.275 174.00805555555556 97.61250000000001Q173.22055555555556 96.95 171.82055555555556 96.95H168.29555555555555ZM175.24555555555557 107.025Q175.24555555555557 105.75 174.37055555555557 105.0Q173.49555555555557 104.25 172.04555555555555 104.25H168.29555555555555V109.675H172.14555555555555Q173.59555555555556 109.675 174.42055555555555 108.975Q175.24555555555557 108.275 175.24555555555557 107.025Z" fill="#c7d7f7"/><path d="M191.40833333333336 103.275Q191.40833333333336 100.725 192.59583333333336 98.69999999999999Q193.78333333333336 96.675 195.82083333333335 95.5375Q197.85833333333335 94.4 200.28333333333336 94.4Q202.73333333333335 94.4 204.77083333333334 95.5375Q206.80833333333334 96.675 207.98333333333335 98.69999999999999Q209.15833333333336 100.725 209.15833333333336 103.275Q209.15833333333336 105.825 207.98333333333335 107.86250000000001Q206.80833333333334 109.9 204.77083333333334 111.0375Q202.73333333333335 112.175 200.28333333333336 112.175Q197.85833333333335 112.175 195.82083333333335 111.0375Q193.78333333333336 109.9 192.59583333333336 107.86250000000001Q191.40833333333336 105.825 191.40833333333336 103.275ZM206.23333333333335 103.275Q206.23333333333335 101.35 205.47083333333336 99.9Q204.70833333333334 98.45 203.35833333333335 97.67500000000001Q202.00833333333335 96.9 200.28333333333336 96.9Q198.55833333333334 96.9 197.20833333333334 97.67500000000001Q195.85833333333335 98.45 195.09583333333336 99.9Q194.33333333333334 101.35 194.33333333333334 103.275Q194.33333333333334 105.2 195.09583333333336 106.6625Q195.85833333333335 108.125 197.20833333333334 108.9125Q198.55833333333334 109.7 200.28333333333336 109.7Q202.00833333333335 109.7 203.35833333333335 108.9125Q204.70833333333334 108.125 205.47083333333336 106.6625Q206.23333333333335 105.2 206.23333333333335 103.275Z" fill="#c7d7f7"/><path d="M232.14611111111114 112.0 228.14611111111114 105.05H225.97111111111113V112.0H223.12111111111113V94.625H229.12111111111113Q231.12111111111113 94.625 232.50861111111112 95.325Q233.89611111111114 96.025 234.58361111111114 97.2Q235.27111111111114 98.375 235.27111111111114 99.825Q235.27111111111114 101.525 234.28361111111116 102.9125Q233.29611111111114 104.3 231.24611111111113 104.8L235.54611111111114 112.0ZM225.97111111111113 102.775H229.12111111111113Q230.72111111111113 102.775 231.53361111111113 101.975Q232.34611111111113 101.175 232.34611111111113 99.825Q232.34611111111113 98.475 231.54611111111114 97.7125Q230.74611111111113 96.95 229.12111111111113 96.95H225.97111111111113Z" fill="#c7d7f7"/><path d="M260.55888888888893 108.45H253.2838888888889L252.0338888888889 112.0H249.0588888888889L255.2838888888889 94.6H258.5838888888889L264.80888888888893 112.0H261.80888888888893ZM259.7588888888889 106.125 256.93388888888893 98.05 254.0838888888889 106.125Z" fill="#c7d7f7"/><path d="M289.8966666666667 94.625V96.95H285.2716666666667V112.0H282.4216666666667V96.95H277.7716666666667V94.625Z" fill="#c7d7f7"/><path d="M302.9844444444445 103.275Q302.9844444444445 100.725 304.1719444444445 98.69999999999999Q305.3594444444445 96.675 307.39694444444444 95.5375Q309.43444444444447 94.4 311.8594444444445 94.4Q314.30944444444447 94.4 316.3469444444445 95.5375Q318.38444444444445 96.675 319.55944444444447 98.69999999999999Q320.7344444444445 100.725 320.7344444444445 103.275Q320.7344444444445 105.825 319.55944444444447 107.86250000000001Q318.38444444444445 109.9 316.3469444444445 111.0375Q314.30944444444447 112.175 311.8594444444445 112.175Q309.43444444444447 112.175 307.39694444444444 111.0375Q305.3594444444445 109.9 304.1719444444445 107.86250000000001Q302.9844444444445 105.825 302.9844444444445 103.275ZM317.80944444444447 103.275Q317.80944444444447 101.35 317.0469444444445 99.9Q316.2844444444445 98.45 314.93444444444447 97.67500000000001Q313.58444444444444 96.9 311.8594444444445 96.9Q310.13444444444445 96.9 308.7844444444445 97.67500000000001Q307.43444444444447 98.45 306.6719444444445 99.9Q305.9094444444445 101.35 305.9094444444445 103.275Q305.9094444444445 105.2 306.6719444444445 106.6625Q307.43444444444447 108.125 308.7844444444445 108.9125Q310.13444444444445 109.7 311.8594444444445 109.7Q313.58444444444444 109.7 314.93444444444447 108.9125Q316.2844444444445 108.125 317.0469444444445 106.6625Q317.80944444444447 105.2 317.80944444444447 103.275Z" fill="#c7d7f7"/><path d="M343.72222222222223 112.0 339.72222222222223 105.05H337.5472222222223V112.0H334.69722222222225V94.625H340.69722222222225Q342.69722222222225 94.625 344.08472222222224 95.325Q345.47222222222223 96.025 346.15972222222223 97.2Q346.84722222222223 98.375 346.84722222222223 99.825Q346.84722222222223 101.525 345.8597222222222 102.9125Q344.87222222222226 104.3 342.82222222222225 104.8L347.12222222222226 112.0ZM337.5472222222223 102.775H340.69722222222225Q342.2972222222223 102.775 343.1097222222223 101.975Q343.9222222222223 101.175 343.9222222222223 99.825Q343.9222222222223 98.475 343.12222222222226 97.7125Q342.32222222222225 96.95 340.69722222222225 96.95H337.5472222222223Z" fill="#c7d7f7"/><path d="M374.535 94.625 368.785 105.7V112.0H365.935V105.7L360.16 94.625H363.33500000000004L367.36 103.15L371.38500000000005 94.625Z" fill="#c7d7f7"/></g></svg></div>'''


main()
