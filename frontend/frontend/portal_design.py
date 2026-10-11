"""
frontend/portal_design.py - Computer Laboratory | the dashboard design

PORTAL_CSS is the stylesheet shared by the admin, technician and teacher
designs (centrum-laboratory-admin_1.html, -technician_1.html, -teacher_1.html
all use the same one), MAP_SVG their floor plan of the four laboratories (one
<rect> per computer), SIDE_LOGO the white logo in the navy sidebar and ICON the
line icons. frontend/portal.py builds the shared screen parts from these.
"""

PORTAL_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Poppins:wght@500;600;700&family=Open+Sans:wght@400;500;600;700&display=swap');
:root {
  --blue: #2d6fe3; --blue-dk: #1d4ed8; --blue-soft: #eaf1fd; --blue-line: #cfdcf6;
  --navy: #14213d; --navy-2: #0f1a33; --navy-3: #1b2a4d;
  --ink: #111827; --muted: #5b6472; --faint: #8b93a1; --line: #e6e9ef; --bg: #f3f5f9; --card: #fff;
  --ok: #a9c4f3; --rep: #f5a524; --fix: #d03b3b; --esc: #7c3aed; --done: #0c8a3e;
  --radius: 16px; --shadow: 0 12px 34px rgba(20, 33, 61, .08);
  --side: 256px;
}
* { box-sizing: border-box; }
body { background: var(--bg); color: var(--ink); font: 400 14.5px/1.55 'Open Sans', 'Segoe UI', Roboto, Arial, sans-serif;
  -webkit-font-smoothing: antialiased; }
h1, h2, h3, h4, .pf { font-family: 'Poppins', 'Segoe UI', Arial, sans-serif; color: var(--navy); margin: 0; }
button { font: inherit; cursor: pointer; }
input, select, textarea { font: inherit; color: var(--ink); }
svg.i { width: 20px; height: 20px; flex: none; }
.muted { color: var(--muted); }
.hide { display: none !important; }

/* ------------------------------------------------------------------ shell */
.app { display: grid; grid-template-columns: var(--side) 1fr; min-height: 100vh; }
.side { position: sticky; top: 0; height: 100vh; background: var(--navy-2); color: #c7d2e8; display: flex; flex-direction: column;
  padding: 22px 16px; z-index: 40; }
.side-logo { padding: 4px 10px 24px; }
.side-logo svg { height: 40px; width: auto; display: block; }
.side-label { font: 600 11px 'Poppins', sans-serif; letter-spacing: .12em; color: #6f7fa3; padding: 14px 12px 8px; text-transform: uppercase; }
.nav-item { display: flex; align-items: center; gap: 12px; width: 100%; border: 0; background: transparent; color: #c7d2e8;
  padding: 11px 12px; border-radius: 12px; font: 500 14px 'Poppins', sans-serif; text-align: left; transition: background .15s, color .15s; }
.nav-item:hover { background: rgba(255, 255, 255, .06); color: #fff; }
.nav-item.active { background: var(--blue); color: #fff; box-shadow: 0 8px 20px rgba(45, 111, 227, .35); }
.nav-item .count { margin-left: auto; background: rgba(255, 255, 255, .14); color: #fff; font-size: 11.5px; font-weight: 600;
  padding: 1px 8px; border-radius: 999px; }
.nav-item.active .count { background: rgba(255, 255, 255, .25); }
.side-foot { margin-top: auto; border-top: 1px solid rgba(255, 255, 255, .08); padding-top: 14px; }
.side-foot .nav-item:hover { background: rgba(229, 72, 77, .12); color: #ffb4b4; }

.main { min-width: 0; display: flex; flex-direction: column; }
.top { position: sticky; top: 0; z-index: 30; display: flex; align-items: center; gap: 16px; height: 70px; padding: 0 28px;
  background: rgba(255, 255, 255, .92); backdrop-filter: blur(10px); border-bottom: 1px solid var(--line); }
.top h1 { font-size: 19px; font-weight: 600; }
.top .crumb { font-size: 12.5px; color: var(--faint); }
.top-right { margin-left: auto; display: flex; align-items: center; gap: 10px; }
.icon-btn { position: relative; width: 40px; height: 40px; border-radius: 12px; border: 1px solid var(--line); background: #fff;
  display: grid; place-items: center; color: var(--muted); }
.icon-btn:hover { color: var(--blue); border-color: var(--blue-line); }
.icon-btn .dot { position: absolute; top: 8px; right: 9px; width: 8px; height: 8px; border-radius: 50%; background: var(--fix);
  border: 2px solid #fff; }
.user { display: flex; align-items: center; gap: 10px; padding: 4px 12px 4px 4px; border-radius: 999px; border: 1px solid var(--line);
  background: #fff; cursor: pointer; font: 600 13.5px 'Poppins', sans-serif; color: var(--navy); }
.user:hover { border-color: var(--blue-line); }
.avatar { width: 34px; height: 34px; border-radius: 50%; background: linear-gradient(135deg, #3b7cf0, #1d4ed8); color: #fff;
  display: grid; place-items: center; font: 600 13px 'Poppins', sans-serif; flex: none; }
.menu-btn { display: none; }
.content { padding: 28px; max-width: 1360px; width: 100%; }
.page { display: none; }
.page.on { display: block; animation: pageIn .3s ease; }
@keyframes pageIn { from { opacity: 0; transform: translateY(6px); } }
.scrim { display: none; }

/* ------------------------------------------------------------------ building blocks */
.grid { display: grid; gap: 20px; }
.g4 { grid-template-columns: repeat(4, 1fr); }
.g3 { grid-template-columns: repeat(3, 1fr); }
.g2 { grid-template-columns: 1fr 1fr; }
.g-map { grid-template-columns: minmax(0, 1.25fr) minmax(0, 1fr); }
.card { background: var(--card); border: 1px solid var(--line); border-radius: var(--radius); padding: 22px; min-width: 0; }
.card-h { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; }
.card-h h3 { font-size: 16px; font-weight: 600; }
.card-h .sub { font-size: 12.5px; color: var(--faint); }
.card-h .right { margin-left: auto; display: flex; gap: 8px; align-items: center; }
.mt { margin-top: 20px; }

.hello { display: flex; align-items: center; justify-content: space-between; gap: 20px; flex-wrap: wrap; margin-bottom: 22px; }
.hello h2 { font-size: 24px; font-weight: 700; }
.hello p { margin: 4px 0 0; color: var(--muted); }

.stat { display: flex; gap: 14px; align-items: center; }
.stat .ic { width: 48px; height: 48px; border-radius: 14px; display: grid; place-items: center; flex: none; }
.stat .num { font: 700 26px/1.1 'Poppins', sans-serif; color: var(--navy); }
.stat .lbl { font-size: 13px; color: var(--muted); }
.ic-blue { background: var(--blue-soft); color: var(--blue); }
.ic-amber { background: #fff4df; color: #a86400; }
.ic-red { background: #fde8e8; color: #b42323; }
.ic-green { background: #e3f4ea; color: var(--done); }
.ic-violet { background: #efe9fe; color: #5b21b6; }

.btn { display: inline-flex; align-items: center; justify-content: center; gap: 8px; border: 0; border-radius: 12px;
  padding: 11px 18px; font: 600 14px 'Poppins', sans-serif; transition: background .15s, box-shadow .15s, color .15s; white-space: nowrap; }
.btn-primary { background: var(--blue); color: #fff; box-shadow: 0 8px 20px rgba(45, 111, 227, .25); }
.btn-primary:hover { background: var(--blue-dk); }
.btn-primary:disabled { background: #b9c9e6; box-shadow: none; cursor: not-allowed; }
.btn-ghost { background: #fff; color: var(--navy); border: 1px solid var(--line); }
.btn-ghost:hover { border-color: var(--blue-line); color: var(--blue); }
.btn-sm { padding: 7px 12px; font-size: 12.5px; border-radius: 10px; }
.btn-danger { background: #fff; color: #b42323; border: 1px solid #f3c7c7; }
.btn-danger:hover { background: #fdf0f0; }
.btn-success { background: var(--done); color: #fff; }
.btn-success:hover { background: #0a7535; }
.link { background: none; border: 0; color: var(--blue); font-weight: 600; padding: 0; }
.link:hover { text-decoration: underline; }

.chips { display: flex; gap: 8px; flex-wrap: wrap; }
.chip { border: 1px solid var(--line); background: #fff; color: var(--muted); border-radius: 999px; padding: 6px 14px;
  font: 500 13px 'Poppins', sans-serif; }
.chip:hover { border-color: var(--blue-line); color: var(--navy); }
.chip.on { background: var(--navy); border-color: var(--navy); color: #fff; }
.chip .n { opacity: .7; margin-left: 4px; }

.badge { display: inline-flex; align-items: center; gap: 6px; font: 600 12px 'Poppins', sans-serif; padding: 3px 10px;
  border-radius: 999px; white-space: nowrap; }
.badge::before { content: ""; width: 7px; height: 7px; border-radius: 50%; background: currentColor; }
.b-reported { background: #fff4df; color: #9a5b00; }
.b-repair { background: #fde8e8; color: #b42323; }
.b-escalated { background: #efe9fe; color: #5b21b6; }
.b-fixed { background: #e3f4ea; color: var(--done); }
.b-pending { background: #fff4df; color: #9a5b00; }
.b-neutral { background: var(--bg); color: var(--muted); }
.b-neutral::before { display: none; }

.search { display: flex; align-items: center; gap: 8px; border: 1px solid var(--line); background: #fff; border-radius: 12px;
  padding: 0 12px; height: 40px; color: var(--faint); min-width: 220px; }
.search input { border: 0; outline: 0; background: transparent; width: 100%; }
.search:focus-within { border-color: var(--blue); box-shadow: 0 0 0 3px rgba(45, 111, 227, .15); }
select.sel { height: 40px; border: 1px solid var(--line); border-radius: 12px; background: #fff; padding: 0 12px; }

/* tables */
.table-wrap { overflow-x: auto; margin: 0 -22px -22px; }
table.t { width: 100%; border-collapse: collapse; font-size: 13.5px; }
.t th { text-align: left; font: 600 12px 'Poppins', sans-serif; letter-spacing: .03em; color: var(--faint); text-transform: uppercase;
  padding: 10px 14px; border-bottom: 1px solid var(--line); background: #fafbfd; white-space: nowrap; }
.t td { padding: 13px 14px; border-bottom: 1px solid var(--line); vertical-align: middle; }
.t tr:last-child td { border-bottom: 0; }
.t tbody tr { transition: background .12s; }
.t tbody tr:hover { background: #fafbfe; }
.t th:first-child, .t td:first-child { padding-left: 22px; }
.t th:last-child, .t td:last-child { padding-right: 22px; }
.t .strong { font-weight: 600; color: var(--navy); }
.t .small { font-size: 12.5px; color: var(--faint); }
.t .actions { display: flex; gap: 6px; justify-content: flex-end; flex-wrap: wrap; }
.empty { text-align: center; padding: 40px 20px; color: var(--faint); }
.empty svg { width: 40px; height: 40px; color: #c3cad6; margin-bottom: 8px; }

/* list rows */
.rows { display: grid; gap: 2px; }
.row { display: flex; align-items: center; gap: 14px; padding: 12px 4px; border-bottom: 1px solid var(--line); }
.row:last-child { border-bottom: 0; }
.row .ic { width: 40px; height: 40px; border-radius: 12px; display: grid; place-items: center; flex: none; }
.row .main-t { min-width: 0; flex: 1; }
.row .main-t b { display: block; font: 600 14px 'Poppins', sans-serif; color: var(--navy); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.row .main-t span { font-size: 12.5px; color: var(--faint); }

/* ------------------------------------------------------------------ floor map */
.map-wrap { position: relative; max-width: 560px; margin: 0 auto; }
.fp { width: 100%; height: auto; display: block; }
.fp .pc { fill: var(--ok); cursor: pointer; transition: opacity .2s; }
.fp .pc.s-reported { fill: var(--rep); }
.fp .pc.s-repair, .fp .pc.s-escalated { fill: var(--fix); }
.fp .pc.s-reported { animation: blink 1.6s ease-in-out infinite; }
.fp .pc:hover, .fp .pc.sel { stroke: var(--navy); stroke-width: 2.5; }
.fp .fp-room { cursor: pointer; transition: fill .2s; }
.fp .fp-room:hover { fill: #dde8fb; }
.fp.focus .fp-pcs { opacity: .22; }
.fp.focus .fp-pcs.on { opacity: 1; }
.fp.focus .fp-room.on { fill: #d8e5fc; stroke: var(--blue); }
.fp-lbl { font: 700 13px 'Poppins', sans-serif; letter-spacing: .28em; fill: #7d8aa3; pointer-events: none; }
.fp-tech { font: 700 10px 'Poppins', sans-serif; letter-spacing: .08em; fill: var(--navy); }
.fp-ping { transform-origin: 300px 300px; transform-box: view-box; animation: ping 2.4s ease-out infinite; }
@keyframes ping { 0% { transform: scale(1); opacity: .8; } 100% { transform: scale(3.2); opacity: 0; } }
@keyframes blink { 50% { opacity: .4; } }
.legend { display: flex; gap: 16px; flex-wrap: wrap; justify-content: center; font-size: 12.5px; color: var(--muted); margin-top: 10px; }
.legend i { display: inline-block; width: 12px; height: 9px; border-radius: 2px; margin-right: 6px; vertical-align: 0; }
.tip { position: fixed; z-index: 90; pointer-events: none; background: var(--navy); color: #fff; font-size: 12.5px; padding: 8px 11px;
  border-radius: 10px; box-shadow: 0 10px 24px rgba(0, 0, 0, .2); opacity: 0; transition: opacity .12s; max-width: 240px; line-height: 1.4; }
.tip b { font-family: 'Poppins', sans-serif; font-weight: 600; }
.tip.show { opacity: 1; }

/* lab overview tiles */
.lab-tile { border: 1px solid var(--line); border-radius: 14px; padding: 14px; display: flex; gap: 12px; align-items: center; background: #fff;
  text-align: left; width: 100%; transition: border-color .15s, box-shadow .15s; }
.lab-tile:hover, .lab-tile.on { border-color: var(--blue-line); box-shadow: var(--shadow); }
.lab-tile.on { border-color: var(--blue); }
.lab-tile svg.mini { width: 42px; height: 42px; flex: none; }
.lab-tile b { display: block; font: 600 14px 'Poppins', sans-serif; color: var(--navy); }
.lab-tile span { font-size: 12.5px; color: var(--faint); }
.bar { height: 6px; border-radius: 6px; background: #eef1f6; overflow: hidden; display: flex; gap: 2px; margin-top: 6px; }
.bar i { display: block; height: 100%; }

/* ------------------------------------------------------------------ charts */
.chart { position: relative; }
.bars-v { display: flex; align-items: flex-end; gap: 14px; height: 200px; padding: 0 4px; border-bottom: 1px solid var(--line);
  background-image: linear-gradient(var(--line) 1px, transparent 1px); background-size: 100% 25%; background-position: 0 -1px; }
.bars-v .col { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: flex-end; height: 100%; cursor: default; }
.bars-v .val { font: 600 12px 'Poppins', sans-serif; color: var(--navy); margin-bottom: 4px; }
.bars-v .b { width: min(46px, 70%); background: var(--blue); border-radius: 4px 4px 0 0; transition: height .5s ease, background .15s; min-height: 2px; }
.bars-v .col:hover .b { background: var(--blue-dk); }
.bars-x { display: flex; gap: 14px; padding: 8px 4px 0; }
.bars-x span { flex: 1; text-align: center; font-size: 12px; color: var(--muted); }
.bars-h { display: grid; gap: 12px; }
.bars-h .r { display: grid; grid-template-columns: 120px 1fr 34px; align-items: center; gap: 10px; font-size: 13px; }
.bars-h .r span:first-child { color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.bars-h .track { height: 12px; background: #f1f4f9; border-radius: 0 4px 4px 0; }
.bars-h .fill { height: 100%; background: var(--blue); border-radius: 0 4px 4px 0; transition: width .5s ease; min-width: 2px; }
.bars-h .r:hover .fill { background: var(--blue-dk); }
.bars-h .r b { font: 600 13px 'Poppins', sans-serif; color: var(--navy); text-align: right; }
.chart-table { margin-top: 12px; }
.chart-table table { width: 100%; border-collapse: collapse; font-size: 13px; }
.chart-table td, .chart-table th { padding: 6px 8px; border-bottom: 1px solid var(--line); text-align: left; }

/* ------------------------------------------------------------------ forms, modal, toast */
.field { display: grid; gap: 6px; margin-bottom: 16px; }
.field label { font: 600 13px 'Poppins', sans-serif; color: var(--navy); }
.field input, .field select, .field textarea { border: 1px solid var(--line); border-radius: 12px; padding: 11px 13px; background: #fff; outline: 0; }
.field textarea { min-height: 96px; resize: vertical; }
.field input:focus, .field select:focus, .field textarea:focus { border-color: var(--blue); box-shadow: 0 0 0 3px rgba(45, 111, 227, .15); }
.modal-bg { position: fixed; inset: 0; background: rgba(15, 26, 51, .45); z-index: 80; display: none; align-items: center; justify-content: center; padding: 20px; }
.modal-bg.show { display: flex; animation: pageIn .2s ease; }
.modal { background: #fff; border-radius: 20px; width: min(520px, 100%); max-height: 90vh; overflow: auto; padding: 26px; box-shadow: 0 30px 70px rgba(0, 0, 0, .25); }
.modal h3 { font-size: 18px; margin-bottom: 4px; }
.modal .m-sub { color: var(--muted); font-size: 13.5px; margin-bottom: 18px; }
.modal .m-actions { display: flex; gap: 10px; justify-content: flex-end; margin-top: 8px; flex-wrap: wrap; }
.kv { display: grid; grid-template-columns: 130px 1fr; gap: 8px 14px; font-size: 13.5px; margin-bottom: 18px; }
.kv dt { color: var(--faint); }
.kv dd { margin: 0; color: var(--ink); font-weight: 500; }
.timeline { list-style: none; margin: 0 0 16px; padding: 0 0 0 18px; border-left: 2px solid var(--line); }
.timeline li { position: relative; padding: 0 0 14px 6px; font-size: 13px; }
.timeline li::before { content: ""; position: absolute; left: -25px; top: 3px; width: 12px; height: 12px; border-radius: 50%;
  background: #fff; border: 2px solid var(--blue); }
.timeline li b { font-family: 'Poppins', sans-serif; font-weight: 600; color: var(--navy); }
.timeline li span { display: block; color: var(--faint); font-size: 12px; }
.toast { position: fixed; left: 50%; bottom: 26px; transform: translate(-50%, 16px); background: var(--navy); color: #fff; padding: 12px 18px;
  border-radius: 12px; font-size: 13.5px; opacity: 0; transition: .25s; z-index: 99; pointer-events: none; max-width: calc(100% - 32px);
  display: flex; gap: 10px; align-items: center; box-shadow: 0 12px 30px rgba(0, 0, 0, .2); }
.toast.show { opacity: 1; transform: translate(-50%, 0); }
.demo-note { display: flex; gap: 10px; align-items: flex-start; background: #fff8e8; border: 1px solid #f6e2b3; color: #7a4a12; border-radius: 12px;
  padding: 10px 14px; font-size: 13px; margin-bottom: 18px; }

/* ------------------------------------------------------------------ profile */
.profile-card { display: flex; gap: 22px; align-items: center; flex-wrap: wrap; }
.avatar-lg { width: 84px; height: 84px; border-radius: 50%; background: linear-gradient(135deg, #3b7cf0, #1d4ed8); color: #fff;
  display: grid; place-items: center; font: 600 28px 'Poppins', sans-serif; box-shadow: 0 0 0 6px var(--blue-soft); flex: none; }
.profile-fixed-name { font: 700 22px 'Poppins', sans-serif; color: var(--navy); }
.profile-role { display: flex; gap: 8px; margin-top: 6px; flex-wrap: wrap; }
.profile-field-row { display: flex; align-items: center; gap: 16px; padding: 16px 0; border-bottom: 1px solid var(--line); flex-wrap: wrap; }
.profile-field-row:last-child { border-bottom: 0; }
.profile-field-row .ic { width: 42px; height: 42px; border-radius: 12px; background: var(--blue-soft); color: var(--blue); display: grid; place-items: center; flex: none; }
.profile-field-row .f { flex: 1; min-width: 180px; }
.profile-field-row .f small { display: block; font-size: 12px; color: var(--faint); }
.profile-field-row .f .v, .contact-info-value { font: 600 14.5px 'Poppins', sans-serif; color: var(--navy); word-break: break-word; }
.inline-edit { display: none; gap: 8px; align-items: center; flex-wrap: wrap; margin-top: 6px; }
.inline-edit.open { display: flex; }
.inline-edit input { border: 1px solid var(--line); border-radius: 10px; padding: 8px 12px; min-width: 200px; outline: 0; }
.inline-edit input:focus { border-color: var(--blue); box-shadow: 0 0 0 3px rgba(45, 111, 227, .15); }

/* ------------------------------------------------------------------ responsive */
@media (max-width: 1180px) {
  .g4 { grid-template-columns: repeat(2, 1fr); }
  .g-map, .g2 { grid-template-columns: 1fr; }
}
@media (max-width: 880px) {
  .app { grid-template-columns: 1fr; }
  .side { position: fixed; left: 0; top: 0; bottom: 0; width: 272px; transform: translateX(-100%); transition: transform .25s ease; }
  .side.open { transform: none; box-shadow: 20px 0 50px rgba(0, 0, 0, .3); }
  .scrim.show { display: block; position: fixed; inset: 0; background: rgba(15, 26, 51, .4); z-index: 35; }
  .menu-btn { display: grid; }
  .top { padding: 0 16px; gap: 10px; }
  .top .crumb, .user .user-name { display: none; }
  .user { padding: 3px; }
  .content { padding: 18px 16px; }
  .g3 { grid-template-columns: 1fr; }
  .search { min-width: 0; flex: 1; }
}
@media (max-width: 520px) {
  .g4 { grid-template-columns: 1fr 1fr; gap: 12px; }
  .g4 .stat { flex-direction: column; align-items: flex-start; gap: 10px; }
  .card { padding: 18px; }
  .table-wrap { margin: 0 -18px -18px; }
  .kv { grid-template-columns: 1fr; gap: 2px; }
  .kv dd { margin-bottom: 8px; }
  .bars-h .r { grid-template-columns: 96px 1fr 30px; }
  .hello h2 { font-size: 20px; }
}
@media (prefers-reduced-motion: reduce) { *, *::before, *::after { animation: none !important; transition: none !important; } }

/* notifications popover */
.notif { position: absolute; right: 0; top: 50px; width: 340px; max-width: calc(100vw - 32px); background: #fff; border: 1px solid var(--line);
  border-radius: 16px; box-shadow: 0 20px 50px rgba(20, 33, 61, .16); padding: 16px 16px 6px; display: none; z-index: 60; }
.notif.show { display: block; animation: pageIn .18s ease; }
.notif .row { padding: 10px 0; }
.sample-tag { font-size: 11.5px; }
@media (max-width: 880px) { .sample-tag { display: none; } .notif { position: fixed; right: 16px; top: 64px; } }

/* stepper (teacher report form) */
.stepper { display: flex; gap: 8px; margin-bottom: 22px; flex-wrap: wrap; }
.stepper .st { flex: 1; min-width: 120px; display: flex; gap: 10px; align-items: center; padding: 12px 14px; border-radius: 14px;
  background: #fff; border: 1px solid var(--line); color: var(--faint); font: 500 13px 'Poppins', sans-serif; }
.stepper .st .n { width: 26px; height: 26px; border-radius: 50%; display: grid; place-items: center; background: var(--bg); font-weight: 600; flex: none; }
.stepper .st.on { border-color: var(--blue); color: var(--navy); }
.stepper .st.on .n { background: var(--blue); color: #fff; }
.stepper .st.done { color: var(--navy); }
.stepper .st.done .n { background: #e3f4ea; color: var(--done); }
.pc-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(64px, 1fr)); gap: 8px; }
.pc-btn { border: 1.5px solid var(--line); background: #fff; border-radius: 12px; padding: 10px 4px 8px; display: grid; justify-items: center; gap: 2px;
  font: 600 12.5px 'Poppins', sans-serif; color: var(--navy); transition: border-color .12s, background .12s; }
.pc-btn svg { width: 22px; height: 22px; color: #8aa6d8; }
.pc-btn:hover { border-color: var(--blue-line); background: #f7faff; }
.pc-btn.on { border-color: var(--blue); background: var(--blue-soft); box-shadow: 0 0 0 3px rgba(45, 111, 227, .15); }
.pc-btn.s-reported svg { color: var(--rep); }
.pc-btn.s-repair svg, .pc-btn.s-escalated svg { color: var(--fix); }
.pc-btn small { font: 500 10.5px 'Open Sans', sans-serif; color: var(--faint); }
.issue-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); gap: 10px; margin-bottom: 18px; }
.issue { border: 1.5px solid var(--line); background: #fff; border-radius: 12px; padding: 12px 14px; text-align: left; font: 500 13.5px 'Poppins', sans-serif; color: var(--navy); }
.issue:hover { border-color: var(--blue-line); }
.issue.on { border-color: var(--blue); background: var(--blue-soft); }
.review-row { display: grid; grid-template-columns: 150px 1fr; gap: 14px; padding: 13px 0; border-bottom: 1px solid var(--line); }
.review-row:last-child { border-bottom: 0; }
.review-label { color: var(--faint); font-size: 13.5px; }
.review-value { font: 600 14px 'Poppins', sans-serif; color: var(--navy); word-break: break-word; }
.step-actions { display: flex; justify-content: space-between; gap: 10px; margin-top: 22px; flex-wrap: wrap; }
.success { text-align: center; padding: 30px 10px; }
.success .big { width: 72px; height: 72px; border-radius: 50%; background: #e3f4ea; color: var(--done); display: grid; place-items: center; margin: 0 auto 14px; }
.success .big svg { width: 34px; height: 34px; }
.pc-panel .ph { display: flex; gap: 12px; align-items: center; margin-bottom: 14px; }
.pc-panel .ph .ic { width: 46px; height: 46px; border-radius: 14px; display: grid; place-items: center; }
@media (max-width: 520px) { .review-row { grid-template-columns: 1fr; gap: 2px; } .stepper .st span.t { display: none; } .stepper .st { min-width: 0; justify-content: center; } }
"""

MAP_SVG = r"""<svg class="fp" viewBox="-6 -6 612 612" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Floor plan of the Centrum laboratories with the status of every computer"><defs><linearGradient id="__P__g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#f2f6fe"/><stop offset="1" stop-color="#e6eefc"/></linearGradient><path id="__P__l1" d="M324.5,579.9 A281.0,281.0 0 0 0 579.9,324.5"/><path id="__P__l2" d="M20.1,324.5 A281.0,281.0 0 0 0 275.5,579.9"/><path id="__P__l3" d="M323.8,28.0 A273.0,273.0 0 0 1 572.0,276.2"/><path id="__P__l4" d="M28.0,276.2 A273.0,273.0 0 0 1 276.2,28.0"/></defs><circle cx="300" cy="300" r="277.0" fill="none" stroke="#f3f6fb" stroke-width="30"/><circle cx="300" cy="300" r="292" fill="none" stroke="#d5deec" stroke-width="1.5"/><path class="fp-room" data-room="1" d="M300.0,556.0 A256,256 0 0 0 556.0,300.0 L422.0,300.0 A122,122 0 0 1 300.0,422.0 Z" fill="url(#__P__g)" stroke="#b9c9e6" stroke-width="2"/><path class="fp-room" data-room="2" d="M44.0,300.0 A256,256 0 0 0 300.0,556.0 L300.0,422.0 A122,122 0 0 1 178.0,300.0 Z" fill="url(#__P__g)" stroke="#b9c9e6" stroke-width="2"/><path class="fp-room" data-room="3" d="M556.0,300.0 A256,256 0 0 0 300.0,44.0 L300.0,178.0 A122,122 0 0 1 422.0,300.0 Z" fill="url(#__P__g)" stroke="#b9c9e6" stroke-width="2"/><path class="fp-room" data-room="4" d="M300.0,44.0 A256,256 0 0 0 44.0,300.0 L178.0,300.0 A122,122 0 0 1 300.0,178.0 Z" fill="url(#__P__g)" stroke="#b9c9e6" stroke-width="2"/><rect x="277.0" y="42" width="46" height="146" fill="#f8fafd"/><rect x="277.0" y="412" width="46" height="146" fill="#f8fafd"/><rect x="42" y="277.0" width="146" height="46" fill="#f8fafd"/><rect x="412" y="277.0" width="146" height="46" fill="#f8fafd"/><rect x="496" y="281" width="54" height="38" rx="6" fill="#fff" stroke="#b9c9e6" stroke-width="1.5"/><text class="fp-tech" x="523" y="304" text-anchor="middle">TECH</text><circle cx="300" cy="300" r="98.0" fill="none" stroke="#14213d" stroke-width="28"/><circle cx="394.7" cy="274.6" r="3.2" fill="#fff" opacity=".85"/><circle cx="369.3" cy="230.7" r="3.2" fill="#fff" opacity=".85"/><circle cx="325.4" cy="205.3" r="3.2" fill="#fff" opacity=".85"/><circle cx="274.6" cy="205.3" r="3.2" fill="#fff" opacity=".85"/><circle cx="230.7" cy="230.7" r="3.2" fill="#fff" opacity=".85"/><circle cx="205.3" cy="274.6" r="3.2" fill="#fff" opacity=".85"/><circle cx="205.3" cy="325.4" r="3.2" fill="#fff" opacity=".85"/><circle cx="230.7" cy="369.3" r="3.2" fill="#fff" opacity=".85"/><circle cx="274.6" cy="394.7" r="3.2" fill="#fff" opacity=".85"/><circle cx="325.4" cy="394.7" r="3.2" fill="#fff" opacity=".85"/><circle cx="369.3" cy="369.3" r="3.2" fill="#fff" opacity=".85"/><circle cx="394.7" cy="325.4" r="3.2" fill="#fff" opacity=".85"/><circle cx="300" cy="300" r="84" fill="#fff"/><circle class="fp-ping" cx="300" cy="300" r="26" fill="none" stroke="#2d6fe3" stroke-width="2"/><circle cx="300" cy="300" r="26" fill="#2d6fe3"/><g transform="translate(288 289)" fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><rect x="1" y="1" width="22" height="15" rx="2.5"/><path d="M8 21h8M12 16v5"/></g><g class="fp-pcs" data-room="1"><rect class="pc" data-room="1" data-pc="1" x="432.8" y="337.1" width="14" height="10" rx="2.5" transform="rotate(-253.3 439.8 342.1)"/><rect class="pc" data-room="1" data-pc="2" x="424.0" y="359.4" width="14" height="10" rx="2.5" transform="rotate(-243.8 431.0 364.4)"/><rect class="pc" data-room="1" data-pc="3" x="411.7" y="380.0" width="14" height="10" rx="2.5" transform="rotate(-234.4 418.7 385.0)"/><rect class="pc" data-room="1" data-pc="4" x="396.2" y="398.2" width="14" height="10" rx="2.5" transform="rotate(-225.0 403.2 403.2)"/><rect class="pc" data-room="1" data-pc="5" x="378.0" y="413.7" width="14" height="10" rx="2.5" transform="rotate(-215.6 385.0 418.7)"/><rect class="pc" data-room="1" data-pc="6" x="357.4" y="426.0" width="14" height="10" rx="2.5" transform="rotate(-206.2 364.4 431.0)"/><rect class="pc" data-room="1" data-pc="7" x="335.1" y="434.8" width="14" height="10" rx="2.5" transform="rotate(-196.7 342.1 439.8)"/><rect class="pc" data-room="1" data-pc="8" x="460.6" y="333.8" width="14" height="10" rx="2.5" transform="rotate(-257.0 467.6 338.8)"/><rect class="pc" data-room="1" data-pc="9" x="453.6" y="356.7" width="14" height="10" rx="2.5" transform="rotate(-249.0 460.6 361.7)"/><rect class="pc" data-room="1" data-pc="10" x="443.4" y="378.4" width="14" height="10" rx="2.5" transform="rotate(-241.0 450.4 383.4)"/><rect class="pc" data-room="1" data-pc="11" x="430.4" y="398.5" width="14" height="10" rx="2.5" transform="rotate(-233.0 437.4 403.5)"/><rect class="pc" data-room="1" data-pc="12" x="414.6" y="416.6" width="14" height="10" rx="2.5" transform="rotate(-225.0 421.6 421.6)"/><rect class="pc" data-room="1" data-pc="13" x="396.5" y="432.4" width="14" height="10" rx="2.5" transform="rotate(-217.0 403.5 437.4)"/><rect class="pc" data-room="1" data-pc="14" x="376.4" y="445.4" width="14" height="10" rx="2.5" transform="rotate(-209.0 383.4 450.4)"/><rect class="pc" data-room="1" data-pc="15" x="354.7" y="455.6" width="14" height="10" rx="2.5" transform="rotate(-201.0 361.7 460.6)"/><rect class="pc" data-room="1" data-pc="16" x="331.8" y="462.6" width="14" height="10" rx="2.5" transform="rotate(-193.0 338.8 467.6)"/><rect class="pc" data-room="1" data-pc="17" x="487.8" y="330.3" width="14" height="10" rx="2.5" transform="rotate(-259.7 494.8 335.3)"/><rect class="pc" data-room="1" data-pc="18" x="482.1" y="353.6" width="14" height="10" rx="2.5" transform="rotate(-252.8 489.1 358.6)"/><rect class="pc" data-room="1" data-pc="19" x="473.6" y="376.1" width="14" height="10" rx="2.5" transform="rotate(-245.8 480.6 381.1)"/><rect class="pc" data-room="1" data-pc="20" x="462.5" y="397.3" width="14" height="10" rx="2.5" transform="rotate(-238.9 469.5 402.3)"/><rect class="pc" data-room="1" data-pc="21" x="448.9" y="417.1" width="14" height="10" rx="2.5" transform="rotate(-231.9 455.9 422.1)"/><rect class="pc" data-room="1" data-pc="22" x="433.0" y="435.0" width="14" height="10" rx="2.5" transform="rotate(-225.0 440.0 440.0)"/><rect class="pc" data-room="1" data-pc="23" x="415.1" y="450.9" width="14" height="10" rx="2.5" transform="rotate(-218.1 422.1 455.9)"/><rect class="pc" data-room="1" data-pc="24" x="395.3" y="464.5" width="14" height="10" rx="2.5" transform="rotate(-211.1 402.3 469.5)"/><rect class="pc" data-room="1" data-pc="25" x="374.1" y="475.6" width="14" height="10" rx="2.5" transform="rotate(-204.2 381.1 480.6)"/><rect class="pc" data-room="1" data-pc="26" x="351.6" y="484.1" width="14" height="10" rx="2.5" transform="rotate(-197.2 358.6 489.1)"/><rect class="pc" data-room="1" data-pc="27" x="328.3" y="489.8" width="14" height="10" rx="2.5" transform="rotate(-190.3 335.3 494.8)"/><rect class="pc" data-room="1" data-pc="28" x="512.7" y="338.6" width="14" height="10" rx="2.5" transform="rotate(-258.8 519.7 343.6)"/><rect class="pc" data-room="1" data-pc="29" x="506.8" y="361.9" width="14" height="10" rx="2.5" transform="rotate(-252.6 513.8 366.9)"/><rect class="pc" data-room="1" data-pc="30" x="498.4" y="384.4" width="14" height="10" rx="2.5" transform="rotate(-246.5 505.4 389.4)"/><rect class="pc" data-room="1" data-pc="31" x="487.7" y="405.8" width="14" height="10" rx="2.5" transform="rotate(-240.3 494.7 410.8)"/><rect class="pc" data-room="1" data-pc="32" x="474.7" y="426.0" width="14" height="10" rx="2.5" transform="rotate(-234.2 481.7 431.0)"/><rect class="pc" data-room="1" data-pc="33" x="459.6" y="444.7" width="14" height="10" rx="2.5" transform="rotate(-228.1 466.6 449.7)"/><rect class="pc" data-room="1" data-pc="34" x="442.7" y="461.6" width="14" height="10" rx="2.5" transform="rotate(-221.9 449.7 466.6)"/><rect class="pc" data-room="1" data-pc="35" x="424.0" y="476.7" width="14" height="10" rx="2.5" transform="rotate(-215.8 431.0 481.7)"/><rect class="pc" data-room="1" data-pc="36" x="403.8" y="489.7" width="14" height="10" rx="2.5" transform="rotate(-209.7 410.8 494.7)"/><rect class="pc" data-room="1" data-pc="37" x="382.4" y="500.4" width="14" height="10" rx="2.5" transform="rotate(-203.5 389.4 505.4)"/><rect class="pc" data-room="1" data-pc="38" x="359.9" y="508.8" width="14" height="10" rx="2.5" transform="rotate(-197.4 366.9 513.8)"/><rect class="pc" data-room="1" data-pc="39" x="336.6" y="514.7" width="14" height="10" rx="2.5" transform="rotate(-191.2 343.6 519.7)"/></g><g class="fp-pcs" data-room="2"><rect class="pc" data-room="2" data-pc="1" x="250.9" y="434.8" width="14" height="10" rx="2.5" transform="rotate(-163.3 257.9 439.8)"/><rect class="pc" data-room="2" data-pc="2" x="228.6" y="426.0" width="14" height="10" rx="2.5" transform="rotate(-153.8 235.6 431.0)"/><rect class="pc" data-room="2" data-pc="3" x="208.0" y="413.7" width="14" height="10" rx="2.5" transform="rotate(-144.4 215.0 418.7)"/><rect class="pc" data-room="2" data-pc="4" x="189.8" y="398.2" width="14" height="10" rx="2.5" transform="rotate(-135.0 196.8 403.2)"/><rect class="pc" data-room="2" data-pc="5" x="174.3" y="380.0" width="14" height="10" rx="2.5" transform="rotate(-125.6 181.3 385.0)"/><rect class="pc" data-room="2" data-pc="6" x="162.0" y="359.4" width="14" height="10" rx="2.5" transform="rotate(-116.2 169.0 364.4)"/><rect class="pc" data-room="2" data-pc="7" x="153.2" y="337.1" width="14" height="10" rx="2.5" transform="rotate(-106.7 160.2 342.1)"/><rect class="pc" data-room="2" data-pc="8" x="254.2" y="462.6" width="14" height="10" rx="2.5" transform="rotate(-167.0 261.2 467.6)"/><rect class="pc" data-room="2" data-pc="9" x="231.3" y="455.6" width="14" height="10" rx="2.5" transform="rotate(-159.0 238.3 460.6)"/><rect class="pc" data-room="2" data-pc="10" x="209.6" y="445.4" width="14" height="10" rx="2.5" transform="rotate(-151.0 216.6 450.4)"/><rect class="pc" data-room="2" data-pc="11" x="189.5" y="432.4" width="14" height="10" rx="2.5" transform="rotate(-143.0 196.5 437.4)"/><rect class="pc" data-room="2" data-pc="12" x="171.4" y="416.6" width="14" height="10" rx="2.5" transform="rotate(-135.0 178.4 421.6)"/><rect class="pc" data-room="2" data-pc="13" x="155.6" y="398.5" width="14" height="10" rx="2.5" transform="rotate(-127.0 162.6 403.5)"/><rect class="pc" data-room="2" data-pc="14" x="142.6" y="378.4" width="14" height="10" rx="2.5" transform="rotate(-119.0 149.6 383.4)"/><rect class="pc" data-room="2" data-pc="15" x="132.4" y="356.7" width="14" height="10" rx="2.5" transform="rotate(-111.0 139.4 361.7)"/><rect class="pc" data-room="2" data-pc="16" x="125.4" y="333.8" width="14" height="10" rx="2.5" transform="rotate(-103.0 132.4 338.8)"/><rect class="pc" data-room="2" data-pc="17" x="257.7" y="489.8" width="14" height="10" rx="2.5" transform="rotate(-169.7 264.7 494.8)"/><rect class="pc" data-room="2" data-pc="18" x="234.4" y="484.1" width="14" height="10" rx="2.5" transform="rotate(-162.8 241.4 489.1)"/><rect class="pc" data-room="2" data-pc="19" x="211.9" y="475.6" width="14" height="10" rx="2.5" transform="rotate(-155.8 218.9 480.6)"/><rect class="pc" data-room="2" data-pc="20" x="190.7" y="464.5" width="14" height="10" rx="2.5" transform="rotate(-148.9 197.7 469.5)"/><rect class="pc" data-room="2" data-pc="21" x="170.9" y="450.9" width="14" height="10" rx="2.5" transform="rotate(-141.9 177.9 455.9)"/><rect class="pc" data-room="2" data-pc="22" x="153.0" y="435.0" width="14" height="10" rx="2.5" transform="rotate(-135.0 160.0 440.0)"/><rect class="pc" data-room="2" data-pc="23" x="137.1" y="417.1" width="14" height="10" rx="2.5" transform="rotate(-128.1 144.1 422.1)"/><rect class="pc" data-room="2" data-pc="24" x="123.5" y="397.3" width="14" height="10" rx="2.5" transform="rotate(-121.1 130.5 402.3)"/><rect class="pc" data-room="2" data-pc="25" x="112.4" y="376.1" width="14" height="10" rx="2.5" transform="rotate(-114.2 119.4 381.1)"/><rect class="pc" data-room="2" data-pc="26" x="103.9" y="353.6" width="14" height="10" rx="2.5" transform="rotate(-107.2 110.9 358.6)"/><rect class="pc" data-room="2" data-pc="27" x="98.2" y="330.3" width="14" height="10" rx="2.5" transform="rotate(-100.3 105.2 335.3)"/><rect class="pc" data-room="2" data-pc="28" x="249.4" y="514.7" width="14" height="10" rx="2.5" transform="rotate(-168.8 256.4 519.7)"/><rect class="pc" data-room="2" data-pc="29" x="226.1" y="508.8" width="14" height="10" rx="2.5" transform="rotate(-162.6 233.1 513.8)"/><rect class="pc" data-room="2" data-pc="30" x="203.6" y="500.4" width="14" height="10" rx="2.5" transform="rotate(-156.5 210.6 505.4)"/><rect class="pc" data-room="2" data-pc="31" x="182.2" y="489.7" width="14" height="10" rx="2.5" transform="rotate(-150.3 189.2 494.7)"/><rect class="pc" data-room="2" data-pc="32" x="162.0" y="476.7" width="14" height="10" rx="2.5" transform="rotate(-144.2 169.0 481.7)"/><rect class="pc" data-room="2" data-pc="33" x="143.3" y="461.6" width="14" height="10" rx="2.5" transform="rotate(-138.1 150.3 466.6)"/><rect class="pc" data-room="2" data-pc="34" x="126.4" y="444.7" width="14" height="10" rx="2.5" transform="rotate(-131.9 133.4 449.7)"/><rect class="pc" data-room="2" data-pc="35" x="111.3" y="426.0" width="14" height="10" rx="2.5" transform="rotate(-125.8 118.3 431.0)"/><rect class="pc" data-room="2" data-pc="36" x="98.3" y="405.8" width="14" height="10" rx="2.5" transform="rotate(-119.7 105.3 410.8)"/><rect class="pc" data-room="2" data-pc="37" x="87.6" y="384.4" width="14" height="10" rx="2.5" transform="rotate(-113.5 94.6 389.4)"/><rect class="pc" data-room="2" data-pc="38" x="79.2" y="361.9" width="14" height="10" rx="2.5" transform="rotate(-107.4 86.2 366.9)"/><rect class="pc" data-room="2" data-pc="39" x="73.3" y="338.6" width="14" height="10" rx="2.5" transform="rotate(-101.2 80.3 343.6)"/></g><g class="fp-pcs" data-room="3"><rect class="pc" data-room="3" data-pc="1" x="335.1" y="155.2" width="14" height="10" rx="2.5" transform="rotate(16.7 342.1 160.2)"/><rect class="pc" data-room="3" data-pc="2" x="357.4" y="164.0" width="14" height="10" rx="2.5" transform="rotate(26.2 364.4 169.0)"/><rect class="pc" data-room="3" data-pc="3" x="378.0" y="176.3" width="14" height="10" rx="2.5" transform="rotate(35.6 385.0 181.3)"/><rect class="pc" data-room="3" data-pc="4" x="396.2" y="191.8" width="14" height="10" rx="2.5" transform="rotate(45.0 403.2 196.8)"/><rect class="pc" data-room="3" data-pc="5" x="411.7" y="210.0" width="14" height="10" rx="2.5" transform="rotate(54.4 418.7 215.0)"/><rect class="pc" data-room="3" data-pc="6" x="424.0" y="230.6" width="14" height="10" rx="2.5" transform="rotate(63.8 431.0 235.6)"/><rect class="pc" data-room="3" data-pc="7" x="432.8" y="252.9" width="14" height="10" rx="2.5" transform="rotate(73.3 439.8 257.9)"/><rect class="pc" data-room="3" data-pc="8" x="331.8" y="127.4" width="14" height="10" rx="2.5" transform="rotate(13.0 338.8 132.4)"/><rect class="pc" data-room="3" data-pc="9" x="354.7" y="134.4" width="14" height="10" rx="2.5" transform="rotate(21.0 361.7 139.4)"/><rect class="pc" data-room="3" data-pc="10" x="376.4" y="144.6" width="14" height="10" rx="2.5" transform="rotate(29.0 383.4 149.6)"/><rect class="pc" data-room="3" data-pc="11" x="396.5" y="157.6" width="14" height="10" rx="2.5" transform="rotate(37.0 403.5 162.6)"/><rect class="pc" data-room="3" data-pc="12" x="414.6" y="173.4" width="14" height="10" rx="2.5" transform="rotate(45.0 421.6 178.4)"/><rect class="pc" data-room="3" data-pc="13" x="430.4" y="191.5" width="14" height="10" rx="2.5" transform="rotate(53.0 437.4 196.5)"/><rect class="pc" data-room="3" data-pc="14" x="443.4" y="211.6" width="14" height="10" rx="2.5" transform="rotate(61.0 450.4 216.6)"/><rect class="pc" data-room="3" data-pc="15" x="453.6" y="233.3" width="14" height="10" rx="2.5" transform="rotate(69.0 460.6 238.3)"/><rect class="pc" data-room="3" data-pc="16" x="460.6" y="256.2" width="14" height="10" rx="2.5" transform="rotate(77.0 467.6 261.2)"/><rect class="pc" data-room="3" data-pc="17" x="328.3" y="100.2" width="14" height="10" rx="2.5" transform="rotate(10.3 335.3 105.2)"/><rect class="pc" data-room="3" data-pc="18" x="351.6" y="105.9" width="14" height="10" rx="2.5" transform="rotate(17.2 358.6 110.9)"/><rect class="pc" data-room="3" data-pc="19" x="374.1" y="114.4" width="14" height="10" rx="2.5" transform="rotate(24.2 381.1 119.4)"/><rect class="pc" data-room="3" data-pc="20" x="395.3" y="125.5" width="14" height="10" rx="2.5" transform="rotate(31.1 402.3 130.5)"/><rect class="pc" data-room="3" data-pc="21" x="415.1" y="139.1" width="14" height="10" rx="2.5" transform="rotate(38.1 422.1 144.1)"/><rect class="pc" data-room="3" data-pc="22" x="433.0" y="155.0" width="14" height="10" rx="2.5" transform="rotate(45.0 440.0 160.0)"/><rect class="pc" data-room="3" data-pc="23" x="448.9" y="172.9" width="14" height="10" rx="2.5" transform="rotate(51.9 455.9 177.9)"/><rect class="pc" data-room="3" data-pc="24" x="462.5" y="192.7" width="14" height="10" rx="2.5" transform="rotate(58.9 469.5 197.7)"/><rect class="pc" data-room="3" data-pc="25" x="473.6" y="213.9" width="14" height="10" rx="2.5" transform="rotate(65.8 480.6 218.9)"/><rect class="pc" data-room="3" data-pc="26" x="482.1" y="236.4" width="14" height="10" rx="2.5" transform="rotate(72.8 489.1 241.4)"/><rect class="pc" data-room="3" data-pc="27" x="487.8" y="259.7" width="14" height="10" rx="2.5" transform="rotate(79.7 494.8 264.7)"/><rect class="pc" data-room="3" data-pc="28" x="336.6" y="75.3" width="14" height="10" rx="2.5" transform="rotate(11.2 343.6 80.3)"/><rect class="pc" data-room="3" data-pc="29" x="359.9" y="81.2" width="14" height="10" rx="2.5" transform="rotate(17.4 366.9 86.2)"/><rect class="pc" data-room="3" data-pc="30" x="382.4" y="89.6" width="14" height="10" rx="2.5" transform="rotate(23.5 389.4 94.6)"/><rect class="pc" data-room="3" data-pc="31" x="403.8" y="100.3" width="14" height="10" rx="2.5" transform="rotate(29.7 410.8 105.3)"/><rect class="pc" data-room="3" data-pc="32" x="424.0" y="113.3" width="14" height="10" rx="2.5" transform="rotate(35.8 431.0 118.3)"/><rect class="pc" data-room="3" data-pc="33" x="442.7" y="128.4" width="14" height="10" rx="2.5" transform="rotate(41.9 449.7 133.4)"/><rect class="pc" data-room="3" data-pc="34" x="459.6" y="145.3" width="14" height="10" rx="2.5" transform="rotate(48.1 466.6 150.3)"/><rect class="pc" data-room="3" data-pc="35" x="474.7" y="164.0" width="14" height="10" rx="2.5" transform="rotate(54.2 481.7 169.0)"/><rect class="pc" data-room="3" data-pc="36" x="487.7" y="184.2" width="14" height="10" rx="2.5" transform="rotate(60.3 494.7 189.2)"/><rect class="pc" data-room="3" data-pc="37" x="498.4" y="205.6" width="14" height="10" rx="2.5" transform="rotate(66.5 505.4 210.6)"/><rect class="pc" data-room="3" data-pc="38" x="506.8" y="228.1" width="14" height="10" rx="2.5" transform="rotate(72.6 513.8 233.1)"/><rect class="pc" data-room="3" data-pc="39" x="512.7" y="251.4" width="14" height="10" rx="2.5" transform="rotate(78.8 519.7 256.4)"/></g><g class="fp-pcs" data-room="4"><rect class="pc" data-room="4" data-pc="1" x="153.2" y="252.9" width="14" height="10" rx="2.5" transform="rotate(-73.3 160.2 257.9)"/><rect class="pc" data-room="4" data-pc="2" x="162.0" y="230.6" width="14" height="10" rx="2.5" transform="rotate(-63.8 169.0 235.6)"/><rect class="pc" data-room="4" data-pc="3" x="174.3" y="210.0" width="14" height="10" rx="2.5" transform="rotate(-54.4 181.3 215.0)"/><rect class="pc" data-room="4" data-pc="4" x="189.8" y="191.8" width="14" height="10" rx="2.5" transform="rotate(-45.0 196.8 196.8)"/><rect class="pc" data-room="4" data-pc="5" x="208.0" y="176.3" width="14" height="10" rx="2.5" transform="rotate(-35.6 215.0 181.3)"/><rect class="pc" data-room="4" data-pc="6" x="228.6" y="164.0" width="14" height="10" rx="2.5" transform="rotate(-26.2 235.6 169.0)"/><rect class="pc" data-room="4" data-pc="7" x="250.9" y="155.2" width="14" height="10" rx="2.5" transform="rotate(-16.7 257.9 160.2)"/><rect class="pc" data-room="4" data-pc="8" x="125.4" y="256.2" width="14" height="10" rx="2.5" transform="rotate(-77.0 132.4 261.2)"/><rect class="pc" data-room="4" data-pc="9" x="132.4" y="233.3" width="14" height="10" rx="2.5" transform="rotate(-69.0 139.4 238.3)"/><rect class="pc" data-room="4" data-pc="10" x="142.6" y="211.6" width="14" height="10" rx="2.5" transform="rotate(-61.0 149.6 216.6)"/><rect class="pc" data-room="4" data-pc="11" x="155.6" y="191.5" width="14" height="10" rx="2.5" transform="rotate(-53.0 162.6 196.5)"/><rect class="pc" data-room="4" data-pc="12" x="171.4" y="173.4" width="14" height="10" rx="2.5" transform="rotate(-45.0 178.4 178.4)"/><rect class="pc" data-room="4" data-pc="13" x="189.5" y="157.6" width="14" height="10" rx="2.5" transform="rotate(-37.0 196.5 162.6)"/><rect class="pc" data-room="4" data-pc="14" x="209.6" y="144.6" width="14" height="10" rx="2.5" transform="rotate(-29.0 216.6 149.6)"/><rect class="pc" data-room="4" data-pc="15" x="231.3" y="134.4" width="14" height="10" rx="2.5" transform="rotate(-21.0 238.3 139.4)"/><rect class="pc" data-room="4" data-pc="16" x="254.2" y="127.4" width="14" height="10" rx="2.5" transform="rotate(-13.0 261.2 132.4)"/><rect class="pc" data-room="4" data-pc="17" x="98.2" y="259.7" width="14" height="10" rx="2.5" transform="rotate(-79.7 105.2 264.7)"/><rect class="pc" data-room="4" data-pc="18" x="103.9" y="236.4" width="14" height="10" rx="2.5" transform="rotate(-72.8 110.9 241.4)"/><rect class="pc" data-room="4" data-pc="19" x="112.4" y="213.9" width="14" height="10" rx="2.5" transform="rotate(-65.8 119.4 218.9)"/><rect class="pc" data-room="4" data-pc="20" x="123.5" y="192.7" width="14" height="10" rx="2.5" transform="rotate(-58.9 130.5 197.7)"/><rect class="pc" data-room="4" data-pc="21" x="137.1" y="172.9" width="14" height="10" rx="2.5" transform="rotate(-51.9 144.1 177.9)"/><rect class="pc" data-room="4" data-pc="22" x="153.0" y="155.0" width="14" height="10" rx="2.5" transform="rotate(-45.0 160.0 160.0)"/><rect class="pc" data-room="4" data-pc="23" x="170.9" y="139.1" width="14" height="10" rx="2.5" transform="rotate(-38.1 177.9 144.1)"/><rect class="pc" data-room="4" data-pc="24" x="190.7" y="125.5" width="14" height="10" rx="2.5" transform="rotate(-31.1 197.7 130.5)"/><rect class="pc" data-room="4" data-pc="25" x="211.9" y="114.4" width="14" height="10" rx="2.5" transform="rotate(-24.2 218.9 119.4)"/><rect class="pc" data-room="4" data-pc="26" x="234.4" y="105.9" width="14" height="10" rx="2.5" transform="rotate(-17.2 241.4 110.9)"/><rect class="pc" data-room="4" data-pc="27" x="257.7" y="100.2" width="14" height="10" rx="2.5" transform="rotate(-10.3 264.7 105.2)"/><rect class="pc" data-room="4" data-pc="28" x="73.3" y="251.4" width="14" height="10" rx="2.5" transform="rotate(-78.8 80.3 256.4)"/><rect class="pc" data-room="4" data-pc="29" x="79.2" y="228.1" width="14" height="10" rx="2.5" transform="rotate(-72.6 86.2 233.1)"/><rect class="pc" data-room="4" data-pc="30" x="87.6" y="205.6" width="14" height="10" rx="2.5" transform="rotate(-66.5 94.6 210.6)"/><rect class="pc" data-room="4" data-pc="31" x="98.3" y="184.2" width="14" height="10" rx="2.5" transform="rotate(-60.3 105.3 189.2)"/><rect class="pc" data-room="4" data-pc="32" x="111.3" y="164.0" width="14" height="10" rx="2.5" transform="rotate(-54.2 118.3 169.0)"/><rect class="pc" data-room="4" data-pc="33" x="126.4" y="145.3" width="14" height="10" rx="2.5" transform="rotate(-48.1 133.4 150.3)"/><rect class="pc" data-room="4" data-pc="34" x="143.3" y="128.4" width="14" height="10" rx="2.5" transform="rotate(-41.9 150.3 133.4)"/><rect class="pc" data-room="4" data-pc="35" x="162.0" y="113.3" width="14" height="10" rx="2.5" transform="rotate(-35.8 169.0 118.3)"/><rect class="pc" data-room="4" data-pc="36" x="182.2" y="100.3" width="14" height="10" rx="2.5" transform="rotate(-29.7 189.2 105.3)"/><rect class="pc" data-room="4" data-pc="37" x="203.6" y="89.6" width="14" height="10" rx="2.5" transform="rotate(-23.5 210.6 94.6)"/><rect class="pc" data-room="4" data-pc="38" x="226.1" y="81.2" width="14" height="10" rx="2.5" transform="rotate(-17.4 233.1 86.2)"/><rect class="pc" data-room="4" data-pc="39" x="249.4" y="75.3" width="14" height="10" rx="2.5" transform="rotate(-11.2 256.4 80.3)"/></g><text class="fp-lbl"><textPath href="#__P__l1" startOffset="50%" text-anchor="middle" dominant-baseline="middle">CENTRUM 1</textPath></text><text class="fp-lbl"><textPath href="#__P__l2" startOffset="50%" text-anchor="middle" dominant-baseline="middle">CENTRUM 2</textPath></text><text class="fp-lbl"><textPath href="#__P__l3" startOffset="50%" text-anchor="middle" dominant-baseline="middle">CENTRUM 3</textPath></text><text class="fp-lbl"><textPath href="#__P__l4" startOffset="50%" text-anchor="middle" dominant-baseline="middle">CENTRUM 4</textPath></text></svg>"""

SIDE_LOGO = r"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 429 128" role="img" aria-label="Computer Laboratory"><title>Computer Laboratory</title><defs><linearGradient id="hd-room" x1="0" y1="0" x2="0.35" y2="1"><stop offset="0" stop-color="#5b93f5"/><stop offset="1" stop-color="#2d6fe3"/></linearGradient></defs><mask id="hd-cut" maskUnits="userSpaceOnUse"><rect x="2" y="4" width="120" height="120" fill="white"/><rect x="57.60" y="4" width="8.80" height="120" fill="black"/><rect x="2" y="59.60" width="60" height="8.80" fill="black"/></mask>
<path d="M107.70,28.29 A58.00,58.00 0 1 0 107.70,99.71 L88.93,85.04 A34.18,34.18 0 1 1 88.93,42.96 Z" fill="url(#hd-room)" mask="url(#hd-cut)"/>
<circle cx="62" cy="64" r="23.30" fill="#ffffff"/>
<circle cx="62" cy="64" r="13.46" fill="#0f1a33"/>
<circle cx="62" cy="64" r="7.25" fill="#2d6fe3"/>
<circle cx="79.13" cy="56.91" r="1.61" fill="#0f1a33"/>
<circle cx="69.09" cy="46.87" r="1.61" fill="#0f1a33"/>
<circle cx="54.91" cy="46.87" r="1.61" fill="#0f1a33"/>
<circle cx="44.87" cy="56.91" r="1.61" fill="#0f1a33"/>
<circle cx="44.87" cy="71.09" r="1.61" fill="#0f1a33"/>
<circle cx="54.91" cy="81.13" r="1.61" fill="#0f1a33"/>
<circle cx="69.09" cy="81.13" r="1.61" fill="#0f1a33"/>
<circle cx="79.13" cy="71.09" r="1.61" fill="#0f1a33"/><path d="M112.68 57.47Q112.68 51.45 115.34 46.865Q118 42.28 122.62 39.83Q127.24 37.38 132.98 37.38Q138.72 37.38 143.34 39.83Q147.96 42.28 150.62 46.865Q153.28 51.45 153.28 57.47Q153.28 63.49 150.585 68.075Q147.89 72.66 143.235 75.11Q138.58 77.56 132.84 77.56Q127.1 77.56 122.515 75.11Q117.93 72.66 115.305 68.11Q112.68 63.56 112.68 57.47ZM141.1 57.47Q141.1 52.78 138.755 50.26Q136.41 47.74 132.98 47.74Q129.48 47.74 127.17 50.225Q124.86 52.71 124.86 57.47Q124.86 62.16 127.135 64.68Q129.41 67.2 132.84 67.2Q136.27 67.2 138.685 64.68Q141.1 62.16 141.1 57.47ZM224.18 54.18V77H212.28V55.79Q212.28 52.01 210.285 49.945Q208.29 47.88 204.79 47.88Q201.29 47.88 199.295 49.945Q197.3 52.01 197.3 55.79V77H185.4V55.79Q185.4 52.01 183.405 49.945Q181.41 47.88 177.91 47.88Q174.41 47.88 172.415 49.945Q170.42 52.01 170.42 55.79V77H158.45V37.94H170.42V42.84Q172.24 40.39 175.18 38.955Q178.12 37.52 181.83 37.52Q186.24 37.52 189.705 39.41Q193.17 41.3 195.13 44.8Q197.16 41.58 200.66 39.55Q204.16 37.52 208.29 37.52Q215.57 37.52 219.875 41.93Q224.18 46.34 224.18 54.18ZM255.39 37.38Q260.22 37.38 264.14 39.83Q268.06 42.28 270.335 46.83Q272.61 51.38 272.61 57.4Q272.61 63.42 270.335 68.005Q268.06 72.59 264.14 75.075Q260.22 77.56 255.39 77.56Q251.33 77.56 248.215 75.88Q245.1 74.2 243.35 71.54V95.62H231.38V37.94H243.35V43.47Q245.1 40.74 248.18 39.06Q251.26 37.38 255.39 37.38ZM251.82 47.81Q248.25 47.81 245.765 50.4Q243.28 52.99 243.28 57.47Q243.28 61.95 245.765 64.54Q248.25 67.13 251.82 67.13Q255.39 67.13 257.91 64.505Q260.43 61.88 260.43 57.4Q260.43 52.92 257.945 50.365Q255.46 47.81 251.82 47.81ZM316.28 37.94V77H304.31V71.68Q302.49 74.27 299.375 75.845Q296.26 77.42 292.48 77.42Q288 77.42 284.57 75.425Q281.14 73.43 279.25 69.65Q277.36 65.87 277.36 60.76V37.94H289.26V59.15Q289.26 63.07 291.29 65.24Q293.32 67.41 296.75 67.41Q300.25 67.41 302.28 65.24Q304.31 63.07 304.31 59.15V37.94ZM345.46 66.85V77H339.37Q332.86 77 329.22 73.815Q325.58 70.63 325.58 63.42V47.88H320.82V37.94H325.58V28.42H337.55V37.94H345.39V47.88H337.55V63.56Q337.55 65.31 338.39 66.08Q339.23 66.85 341.19 66.85ZM387.52 60.34H360.43Q360.71 63.98 362.775 65.905Q364.84 67.83 367.85 67.83Q372.33 67.83 374.08 64.05H386.82Q385.84 67.9 383.285 70.98Q380.73 74.06 376.88 75.81Q373.03 77.56 368.27 77.56Q362.53 77.56 358.05 75.11Q353.57 72.66 351.05 68.11Q348.53 63.56 348.53 57.47Q348.53 51.38 351.015 46.83Q353.5 42.28 357.98 39.83Q362.46 37.38 368.27 37.38Q373.94 37.38 378.35 39.76Q382.76 42.14 385.245 46.55Q387.73 50.96 387.73 56.84Q387.73 58.52 387.52 60.34ZM375.48 53.69Q375.48 50.61 373.38 48.79Q371.28 46.97 368.13 46.97Q365.12 46.97 363.055 48.72Q360.99 50.47 360.5 53.69ZM417.05 37.52V50.19H413.76Q409.28 50.19 407.04 52.115Q404.8 54.04 404.8 58.87V77H392.83V37.94H404.8V44.45Q406.9 41.23 410.05 39.375Q413.2 37.52 417.05 37.52Z" fill="#ffffff"/><path d="M117.437 109.707H123.295V112H114.595V94.675H117.437ZM152.478 108.46H145.224L143.977 112H141.011L147.218 94.65H150.508L156.716 112H153.724ZM151.68 106.142 148.863 98.09 146.021 106.142ZM188.391 107.338Q188.391 108.66 187.706 109.719Q187.02 110.779 185.724 111.389Q184.428 112 182.708 112H175.778V94.675H182.384Q184.154 94.675 185.425 95.273Q186.696 95.871 187.344 96.881Q187.992 97.891 187.992 99.137Q187.992 100.633 187.195 101.63Q186.397 102.627 185.051 103.101Q186.447 103.35 187.419 104.571Q188.391 105.793 188.391 107.338ZM178.619 101.954H182.134Q183.53 101.954 184.316 101.318Q185.101 100.683 185.101 99.486Q185.101 98.314 184.316 97.654Q183.53 96.993 182.134 96.993H178.619ZM185.549 107.039Q185.549 105.768 184.677 105.02Q183.805 104.272 182.359 104.272H178.619V109.682H182.458Q183.904 109.682 184.727 108.984Q185.549 108.286 185.549 107.039ZM206.905 103.3Q206.905 100.757 208.089 98.738Q209.273 96.719 211.305 95.585Q213.336 94.451 215.754 94.451Q218.197 94.451 220.229 95.585Q222.261 96.719 223.432 98.738Q224.604 100.757 224.604 103.3Q224.604 105.843 223.432 107.874Q222.261 109.906 220.229 111.04Q218.197 112.174 215.754 112.174Q213.336 112.174 211.305 111.04Q209.273 109.906 208.089 107.874Q206.905 105.843 206.905 103.3ZM221.687 103.3Q221.687 101.381 220.927 99.935Q220.167 98.489 218.821 97.716Q217.474 96.943 215.754 96.943Q214.034 96.943 212.688 97.716Q211.342 98.489 210.582 99.935Q209.821 101.381 209.821 103.3Q209.821 105.22 210.582 106.678Q211.342 108.136 212.688 108.921Q214.034 109.707 215.754 109.707Q217.474 109.707 218.821 108.921Q220.167 108.136 220.927 106.678Q221.687 105.22 221.687 103.3ZM252.765 112 248.776 105.07H246.607V112H243.766V94.675H249.748Q251.743 94.675 253.126 95.373Q254.51 96.071 255.195 97.242Q255.881 98.414 255.881 99.86Q255.881 101.555 254.896 102.939Q253.911 104.322 251.867 104.821L256.155 112ZM246.607 102.801H249.748Q251.344 102.801 252.154 102.004Q252.964 101.206 252.964 99.86Q252.964 98.514 252.166 97.753Q251.369 96.993 249.748 96.993H246.607ZM286.335 108.46H279.081L277.834 112H274.868L281.075 94.65H284.366L290.573 112H287.581ZM285.537 106.142 282.72 98.09 279.879 106.142ZM320.828 94.675V96.993H316.216V112H313.374V96.993H308.737V94.675ZM339.117 103.3Q339.117 100.757 340.301 98.738Q341.485 96.719 343.517 95.585Q345.548 94.451 347.966 94.451Q350.409 94.451 352.441 95.585Q354.473 96.719 355.644 98.738Q356.816 100.757 356.816 103.3Q356.816 105.843 355.644 107.874Q354.473 109.906 352.441 111.04Q350.409 112.174 347.966 112.174Q345.548 112.174 343.517 111.04Q341.485 109.906 340.301 107.874Q339.117 105.843 339.117 103.3ZM353.899 103.3Q353.899 101.381 353.139 99.935Q352.379 98.489 351.032 97.716Q349.686 96.943 347.966 96.943Q346.246 96.943 344.9 97.716Q343.554 98.489 342.794 99.935Q342.033 101.381 342.033 103.3Q342.033 105.22 342.794 106.678Q343.554 108.136 344.9 108.921Q346.246 109.707 347.966 109.707Q349.686 109.707 351.032 108.921Q352.379 108.136 353.139 106.678Q353.899 105.22 353.899 103.3ZM384.977 112 380.988 105.07H378.819V112H375.978V94.675H381.96Q383.955 94.675 385.338 95.373Q386.722 96.071 387.407 97.242Q388.093 98.414 388.093 99.86Q388.093 101.555 387.108 102.939Q386.123 104.322 384.079 104.821L388.367 112ZM378.819 102.801H381.96Q383.556 102.801 384.366 102.004Q385.176 101.206 385.176 99.86Q385.176 98.514 384.378 97.753Q383.581 96.993 381.96 96.993H378.819ZM420.94 94.675 415.206 105.718V112H412.365V105.718L406.606 94.675H409.772L413.786 103.175L417.799 94.675Z" fill="#c7d7f7"/></svg>"""

ICON = {
    "home": '<path d="M3 11 12 4l9 7"/><path d="M5 10v10h14V10"/><path d="M10 20v-6h4v6"/>',
    "plus": '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6M12 12v5M9.5 14.5h5"/>',
    "list": '<path d="M8 6h13M8 12h13M8 18h13"/><circle cx="3.5" cy="6" r="1"/><circle cx="3.5" cy="12" r="1"/><circle cx="3.5" cy="18" r="1"/>',
    "map": '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="3.5"/><path d="M12 3v5.5M12 15.5V21M3 12h5.5"/>',
    "user": '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
    "users": '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/><path d="M16 4.5a3.5 3.5 0 0 1 0 7M18.5 20a6.5 6.5 0 0 0-3-5.5"/>',
    "logout": '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="m16 17 5-5-5-5M21 12H9"/>',
    "bell": '<path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.7 21a2 2 0 0 1-3.4 0"/>',
    "menu": '<path d="M4 7h16M4 12h16M4 17h16"/>',
    "chart": '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
    "box": '<path d="M21 8 12 3 3 8v8l9 5 9-5z"/><path d="M3 8l9 5 9-5M12 13v8"/>',
    "up": '<path d="M12 19V5M5 12l7-7 7 7"/>',
    "wrench": '<path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.5 2.5-2.4-.6-.6-2.4z"/>',
    "check": '<circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/>',
    "alert": '<path d="M12 9v4M12 17h.01"/><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "pc": '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>',
    "mail": '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/>',
    "phone": '<path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1 1 .4 1.9.7 2.8a2 2 0 0 1-.5 2.1L8 9.9a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.4c.9.3 1.8.6 2.8.7a2 2 0 0 1 1.7 2z"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
    "shield": '<path d="M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6z"/><path d="m9 12 2 2 4-4"/>',
    "x": '<path d="M18 6 6 18M6 6l12 12"/>',
    "arrow": '<path d="M5 12h14M13 6l6 6-6 6"/>',
    "back": '<path d="M19 12H5M11 18l-6-6 6-6"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
    "building": '<path d="M4 21V5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v16"/><path d="M16 9h2a2 2 0 0 1 2 2v10M8 7h4M8 11h4M8 15h4M2 21h20"/>',
    "print": '<path d="M6 9V3h12v6"/><rect x="3" y="9" width="18" height="8" rx="2"/><path d="M6 14h12v7H6z"/>',
    "file": '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6M8 13h8M8 17h5"/>',
    "accounts": '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/><path d="m16 11 2 2 4-4"/>',
}
