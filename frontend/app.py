"""
app.py - Computer Laboratory | main entry point (Streamlit)

Run from the project root (CL Monitoring System/), in two terminals:

    uvicorn backend.main:app --reload      # 1) FastAPI backend
    streamlit run app.py                   # 2) this app

What happens
------------
1. Centrum logo intro   - plays once per browser visit (about 4 seconds), then fades out.
2. Homepage (Home.py)   - "Login / Register", "Get Started" and "Sign up" open the login screens.
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
    Teacher.py, Home.py (or frontend/Home.py)

Brand files (optional, all included in the project zip):
    assets/logo.png        Computer Laboratory logo - login card
    assets/logo-icon.png   the "C" mark - browser-tab icon
    assets/logo-stacked.png, assets/logo-white.png   other versions of the logo
    media/centrum-intro.mp4, media/centrum-intro.gif the logo intro as a video / GIF
    media/homepage.png, media/homepage-hero.png      pictures of the homepage
    (optional) isu.jpg campus photo for the login screen
"""

from __future__ import annotations

import streamlit as st

from frontend import NewLogin

try:  # Home.py may sit next to app.py or inside frontend/
    from frontend import Home
except ImportError:
    import Home

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
def _open_dashboard(user: dict) -> None:
    role = str(user.get("role", "")).strip().lower()
    if role in ("admin", "administrator"):
        from frontend import admin

        admin.render(user)
    elif role == "teacher":
        import frontend.Teacher as Teacher

        Teacher.render(user)
    elif role == "technician":
        from frontend import technician

        technician.render(user)
    else:
        st.error(
            f"Unknown role: {user.get('role') or 'none'}. Please contact the admin."
        )
        if st.button("Back to log in"):
            NewLogin.logout()
    st.stop()


def main() -> None:
    ss.setdefault("cl_view", "home")

    # 4. Signed in: open the dashboard (dashboards set their own wide layout).
    user = ss.get("auth_user")
    if ss.get("authenticated") and isinstance(user, dict) and user:
        _open_dashboard(user)

    # The "Working..." loading animation (logging in, signing up...).
    from frontend import ui

    ui.install_loader()

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
</style><div class="cli-splash"><svg class="cli-logo" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 429 128" role="img" aria-label="Computer Laboratory"><defs><linearGradient id="cli-room" x1="0" y1="0" x2="0.35" y2="1"><stop offset="0" stop-color="#5b93f5"/><stop offset="1" stop-color="#2d6fe3"/></linearGradient><mask id="cli-cut" maskUnits="userSpaceOnUse"><rect x="2" y="4" width="120" height="120" fill="white"/><rect x="57.60" y="4" width="8.80" height="120" fill="black"/><rect x="2" y="59.60" width="60" height="8.80" fill="black"/></mask><clipPath id="cli-q-se"><rect x="62" y="64" width="60" height="60"/></clipPath><clipPath id="cli-q-sw"><rect x="2" y="64" width="60" height="60"/></clipPath><clipPath id="cli-q-ne"><rect x="62" y="4" width="60" height="60"/></clipPath><clipPath id="cli-q-nw"><rect x="2" y="4" width="60" height="60"/></clipPath></defs><g class="cli-mark"><circle class="cli-pulse cli-pulse1" cx="62" cy="64" r="7.25" fill="none" stroke="#5b93f5" stroke-width="2"/><circle class="cli-pulse cli-pulse2" cx="62" cy="64" r="7.25" fill="none" stroke="#5b93f5" stroke-width="2"/><g class="cli-room cli-room-se"><g clip-path="url(#cli-q-se)"><path d="M107.70,28.29 A58.00,58.00 0 1 0 107.70,99.71 L88.93,85.04 A34.18,34.18 0 1 1 88.93,42.96 Z" fill="url(#cli-room)" mask="url(#cli-cut)"/></g></g><g class="cli-room cli-room-sw"><g clip-path="url(#cli-q-sw)"><path d="M107.70,28.29 A58.00,58.00 0 1 0 107.70,99.71 L88.93,85.04 A34.18,34.18 0 1 1 88.93,42.96 Z" fill="url(#cli-room)" mask="url(#cli-cut)"/></g></g><g class="cli-room cli-room-ne"><g clip-path="url(#cli-q-ne)"><path d="M107.70,28.29 A58.00,58.00 0 1 0 107.70,99.71 L88.93,85.04 A34.18,34.18 0 1 1 88.93,42.96 Z" fill="url(#cli-room)" mask="url(#cli-cut)"/></g></g><g class="cli-room cli-room-nw"><g clip-path="url(#cli-q-nw)"><path d="M107.70,28.29 A58.00,58.00 0 1 0 107.70,99.71 L88.93,85.04 A34.18,34.18 0 1 1 88.93,42.96 Z" fill="url(#cli-room)" mask="url(#cli-cut)"/></g></g><circle class="cli-hall" cx="62" cy="64" r="18.38" fill="none" stroke="#ffffff" stroke-width="9.84" stroke-dasharray="115.51" stroke-dashoffset="115.51" transform="rotate(-90 62 64)"/><circle class="cli-dot" style="animation-delay:0.95s" cx="69.09" cy="46.87" r="1.61" fill="#0f1a33"/><circle class="cli-dot" style="animation-delay:1.01s" cx="79.13" cy="56.91" r="1.61" fill="#0f1a33"/><circle class="cli-dot" style="animation-delay:1.07s" cx="79.13" cy="71.09" r="1.61" fill="#0f1a33"/><circle class="cli-dot" style="animation-delay:1.13s" cx="69.09" cy="81.13" r="1.61" fill="#0f1a33"/><circle class="cli-dot" style="animation-delay:1.19s" cx="54.91" cy="81.13" r="1.61" fill="#0f1a33"/><circle class="cli-dot" style="animation-delay:1.25s" cx="44.87" cy="71.09" r="1.61" fill="#0f1a33"/><circle class="cli-dot" style="animation-delay:1.31s" cx="44.87" cy="56.91" r="1.61" fill="#0f1a33"/><circle class="cli-dot" style="animation-delay:1.37s" cx="54.91" cy="46.87" r="1.61" fill="#0f1a33"/><circle class="cli-core" cx="62" cy="64" r="7.25" fill="#3b7cf0"/></g><path class="cli-letter" style="animation-delay:1.95s" d="M112.68 57.47Q112.68 51.45 115.34 46.865Q118 42.28 122.62 39.83Q127.24 37.38 132.98 37.38Q138.72 37.38 143.34 39.83Q147.96 42.28 150.62 46.865Q153.28 51.45 153.28 57.47Q153.28 63.49 150.585 68.075Q147.89 72.66 143.235 75.11Q138.58 77.56 132.84 77.56Q127.1 77.56 122.515 75.11Q117.93 72.66 115.305 68.11Q112.68 63.56 112.68 57.47ZM141.1 57.47Q141.1 52.78 138.755 50.26Q136.41 47.74 132.98 47.74Q129.48 47.74 127.17 50.225Q124.86 52.71 124.86 57.47Q124.86 62.16 127.135 64.68Q129.41 67.2 132.84 67.2Q136.27 67.2 138.685 64.68Q141.1 62.16 141.1 57.47Z" fill="#ffffff"/><path class="cli-letter" style="animation-delay:2.02s" d="M224.18 54.18V77H212.28V55.79Q212.28 52.01 210.285 49.945Q208.29 47.88 204.79 47.88Q201.29 47.88 199.295 49.945Q197.3 52.01 197.3 55.79V77H185.4V55.79Q185.4 52.01 183.405 49.945Q181.41 47.88 177.91 47.88Q174.41 47.88 172.415 49.945Q170.42 52.01 170.42 55.79V77H158.45V37.94H170.42V42.84Q172.24 40.39 175.18 38.955Q178.12 37.52 181.83 37.52Q186.24 37.52 189.705 39.41Q193.17 41.3 195.13 44.8Q197.16 41.58 200.66 39.55Q204.16 37.52 208.29 37.52Q215.57 37.52 219.875 41.93Q224.18 46.34 224.18 54.18Z" fill="#ffffff"/><path class="cli-letter" style="animation-delay:2.09s" d="M255.39 37.38Q260.22 37.38 264.14 39.83Q268.06 42.28 270.335 46.83Q272.61 51.38 272.61 57.4Q272.61 63.42 270.335 68.005Q268.06 72.59 264.14 75.075Q260.22 77.56 255.39 77.56Q251.33 77.56 248.215 75.88Q245.1 74.2 243.35 71.54V95.62H231.38V37.94H243.35V43.47Q245.1 40.74 248.18 39.06Q251.26 37.38 255.39 37.38ZM251.82 47.81Q248.25 47.81 245.765 50.4Q243.28 52.99 243.28 57.47Q243.28 61.95 245.765 64.54Q248.25 67.13 251.82 67.13Q255.39 67.13 257.91 64.505Q260.43 61.88 260.43 57.4Q260.43 52.92 257.945 50.365Q255.46 47.81 251.82 47.81Z" fill="#ffffff"/><path class="cli-letter" style="animation-delay:2.16s" d="M316.28 37.94V77H304.31V71.68Q302.49 74.27 299.375 75.845Q296.26 77.42 292.48 77.42Q288 77.42 284.57 75.425Q281.14 73.43 279.25 69.65Q277.36 65.87 277.36 60.76V37.94H289.26V59.15Q289.26 63.07 291.29 65.24Q293.32 67.41 296.75 67.41Q300.25 67.41 302.28 65.24Q304.31 63.07 304.31 59.15V37.94Z" fill="#ffffff"/><path class="cli-letter" style="animation-delay:2.23s" d="M345.46 66.85V77H339.37Q332.86 77 329.22 73.815Q325.58 70.63 325.58 63.42V47.88H320.82V37.94H325.58V28.42H337.55V37.94H345.39V47.88H337.55V63.56Q337.55 65.31 338.39 66.08Q339.23 66.85 341.19 66.85Z" fill="#ffffff"/><path class="cli-letter" style="animation-delay:2.30s" d="M387.52 60.34H360.43Q360.71 63.98 362.775 65.905Q364.84 67.83 367.85 67.83Q372.33 67.83 374.08 64.05H386.82Q385.84 67.9 383.285 70.98Q380.73 74.06 376.88 75.81Q373.03 77.56 368.27 77.56Q362.53 77.56 358.05 75.11Q353.57 72.66 351.05 68.11Q348.53 63.56 348.53 57.47Q348.53 51.38 351.015 46.83Q353.5 42.28 357.98 39.83Q362.46 37.38 368.27 37.38Q373.94 37.38 378.35 39.76Q382.76 42.14 385.245 46.55Q387.73 50.96 387.73 56.84Q387.73 58.52 387.52 60.34ZM375.48 53.69Q375.48 50.61 373.38 48.79Q371.28 46.97 368.13 46.97Q365.12 46.97 363.055 48.72Q360.99 50.47 360.5 53.69Z" fill="#ffffff"/><path class="cli-letter" style="animation-delay:2.37s" d="M417.05 37.52V50.19H413.76Q409.28 50.19 407.04 52.115Q404.8 54.04 404.8 58.87V77H392.83V37.94H404.8V44.45Q406.9 41.23 410.05 39.375Q413.2 37.52 417.05 37.52Z" fill="#ffffff"/><g class="cli-sub"><path d="M117.437 109.707H123.295V112H114.595V94.675H117.437Z" fill="#c7d7f7"/><path d="M152.478 108.46H145.224L143.977 112H141.011L147.218 94.65H150.508L156.716 112H153.724ZM151.68 106.142 148.863 98.09 146.021 106.142Z" fill="#c7d7f7"/><path d="M188.391 107.338Q188.391 108.66 187.706 109.719Q187.02 110.779 185.724 111.389Q184.428 112 182.708 112H175.778V94.675H182.384Q184.154 94.675 185.425 95.273Q186.696 95.871 187.344 96.881Q187.992 97.891 187.992 99.137Q187.992 100.633 187.195 101.63Q186.397 102.627 185.051 103.101Q186.447 103.35 187.419 104.571Q188.391 105.793 188.391 107.338ZM178.619 101.954H182.134Q183.53 101.954 184.316 101.318Q185.101 100.683 185.101 99.486Q185.101 98.314 184.316 97.654Q183.53 96.993 182.134 96.993H178.619ZM185.549 107.039Q185.549 105.768 184.677 105.02Q183.805 104.272 182.359 104.272H178.619V109.682H182.458Q183.904 109.682 184.727 108.984Q185.549 108.286 185.549 107.039Z" fill="#c7d7f7"/><path d="M206.905 103.3Q206.905 100.757 208.089 98.738Q209.273 96.719 211.305 95.585Q213.336 94.451 215.754 94.451Q218.197 94.451 220.229 95.585Q222.261 96.719 223.432 98.738Q224.604 100.757 224.604 103.3Q224.604 105.843 223.432 107.874Q222.261 109.906 220.229 111.04Q218.197 112.174 215.754 112.174Q213.336 112.174 211.305 111.04Q209.273 109.906 208.089 107.874Q206.905 105.843 206.905 103.3ZM221.687 103.3Q221.687 101.381 220.927 99.935Q220.167 98.489 218.821 97.716Q217.474 96.943 215.754 96.943Q214.034 96.943 212.688 97.716Q211.342 98.489 210.582 99.935Q209.821 101.381 209.821 103.3Q209.821 105.22 210.582 106.678Q211.342 108.136 212.688 108.921Q214.034 109.707 215.754 109.707Q217.474 109.707 218.821 108.921Q220.167 108.136 220.927 106.678Q221.687 105.22 221.687 103.3Z" fill="#c7d7f7"/><path d="M252.765 112 248.776 105.07H246.607V112H243.766V94.675H249.748Q251.743 94.675 253.126 95.373Q254.51 96.071 255.195 97.242Q255.881 98.414 255.881 99.86Q255.881 101.555 254.896 102.939Q253.911 104.322 251.867 104.821L256.155 112ZM246.607 102.801H249.748Q251.344 102.801 252.154 102.004Q252.964 101.206 252.964 99.86Q252.964 98.514 252.166 97.753Q251.369 96.993 249.748 96.993H246.607Z" fill="#c7d7f7"/><path d="M286.335 108.46H279.081L277.834 112H274.868L281.075 94.65H284.366L290.573 112H287.581ZM285.537 106.142 282.72 98.09 279.879 106.142Z" fill="#c7d7f7"/><path d="M320.828 94.675V96.993H316.216V112H313.374V96.993H308.737V94.675Z" fill="#c7d7f7"/><path d="M339.117 103.3Q339.117 100.757 340.301 98.738Q341.485 96.719 343.517 95.585Q345.548 94.451 347.966 94.451Q350.409 94.451 352.441 95.585Q354.473 96.719 355.644 98.738Q356.816 100.757 356.816 103.3Q356.816 105.843 355.644 107.874Q354.473 109.906 352.441 111.04Q350.409 112.174 347.966 112.174Q345.548 112.174 343.517 111.04Q341.485 109.906 340.301 107.874Q339.117 105.843 339.117 103.3ZM353.899 103.3Q353.899 101.381 353.139 99.935Q352.379 98.489 351.032 97.716Q349.686 96.943 347.966 96.943Q346.246 96.943 344.9 97.716Q343.554 98.489 342.794 99.935Q342.033 101.381 342.033 103.3Q342.033 105.22 342.794 106.678Q343.554 108.136 344.9 108.921Q346.246 109.707 347.966 109.707Q349.686 109.707 351.032 108.921Q352.379 108.136 353.139 106.678Q353.899 105.22 353.899 103.3Z" fill="#c7d7f7"/><path d="M384.977 112 380.988 105.07H378.819V112H375.978V94.675H381.96Q383.955 94.675 385.338 95.373Q386.722 96.071 387.407 97.242Q388.093 98.414 388.093 99.86Q388.093 101.555 387.108 102.939Q386.123 104.322 384.079 104.821L388.367 112ZM378.819 102.801H381.96Q383.556 102.801 384.366 102.004Q385.176 101.206 385.176 99.86Q385.176 98.514 384.378 97.753Q383.581 96.993 381.96 96.993H378.819Z" fill="#c7d7f7"/><path d="M420.94 94.675 415.206 105.718V112H412.365V105.718L406.606 94.675H409.772L413.786 103.175L417.799 94.675Z" fill="#c7d7f7"/></g></svg></div>'''


main()
