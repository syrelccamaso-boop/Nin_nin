# Centrum Laboratory – frontend update

Unzip into the project root (the folder with `app.py`). Frontend only – no backend changes.

```
app.py  Home.py  Teacher.py
frontend/  admin.py  technician.py  portal.py  portal_design.py  ui.py  lab_data.py
           NewLogin.py  backend_client.py
           inventory.py       (new – inventory screen shared by Admin + Technician)
           lab_store.py       (new – shared store: data/centrum_lab.json)
           seed_inventory.py  (new – idempotent 40-computers-per-lab seed)
```

## Run
```
uvicorn backend.main:app --reload
streamlit run app.py
python -m frontend.seed_inventory            # optional: top up the inventory (safe to re-run)
python -m frontend.seed_inventory --dry-run  # show what would be added
```
On first start the app creates `data/centrum_lab.json` and seeds it once if the inventory is empty.

## What changed
- **Home page** – nav links (Home, Laboratories, Features, How It Works, About Us, Contact) are real buttons that
  scroll to their section; Log in / Register buttons; "Menu" button on small screens; clickable logo, lab cards,
  contact cards, footer links and "See How It Works".
- **Users table error** – `/users` list responses are no longer rejected as "unexpected response"; database
  errors about the Users table show one clear message; logins with no user row, no role, or a pending/inactive
  account are stopped with a message instead of opening a broken dashboard; roles are read from `role`,
  `role_name`, a joined Roles row, or `Users.RoleId` (+ `ROLE_ID_*` in .env).
- **Sidebar** – Log out is pinned to the bottom of the sidebar (with the signed-in user above it).
- **Header** – taller and wider, bell and profile chip grouped on the right, responsive on phones (and the
  "open sidebar" arrow stays reachable).
- **Notifications** – bell panel with unread count, Unread / All (history), mark one or all as read, empty
  state; items filtered by role (admin: escalations, account requests, new reports, inventory updates;
  technician: new reports, admin decisions, inventory updates; teacher: updates on their own reports).
  Read marks are saved per user.
- **Technician inventory** – same tools as the admin: full list / live map, search, lab filter, status
  chips, sort, Export CSV, computer details, Add computer, Edit (details, hardware, record status, software,
  maintenance log). Changes are saved in the shared store, so they show up for everyone.
- **Sample data removed** – no built-in sample reports, requests, computers or maintenance logs.
  The seed adds 40 computers per lab (asset ID, brand/model, unique serial, CPU, RAM, storage, GPU, monitor,
  OS, software, lab, status, date added) with no maintenance history.
- **Validation & feedback** – required fields, duplicate seat/serial checks, password rules, duplicate-report
  check for teachers, confirm dialogs (remove software, escalation decisions), success/error toasts,
  friendly error screen if a dashboard fails.
