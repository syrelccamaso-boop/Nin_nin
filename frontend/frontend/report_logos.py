"""
frontend/report_logos.py - Computer Laboratory | logos for printed reports

The Print reports page can show one logo on each side of the report header
(for example the ISU seal on the left and the department logo on the right).
Admins upload the logos once; they are kept in the project's data folder

    <project>/data/report_logos/<id>.png     (converted to PNG, max 600 px)
    <project>/data/report_logos/logos.json   [{"id", "name", "file", "added", "by"}]

next to the shared lab store, so every admin and technician on this server
can pick them. The system logo (assets/logo.png) is always available as
"Computer Laboratory (system logo)".

    logos()              -> [{"id", "name", "path"}]  (system logo first)
    path_of(id)          -> Path | None
    data_uri(id)         -> "data:image/png;base64,..." or ""
    add(name, raw, by)   -> (ok, message)
    remove(id)           -> bool
"""

from __future__ import annotations

import base64
import io
import json
import threading
import uuid
from pathlib import Path

from frontend import lab_store
from frontend import ui

SYSTEM = "system"
FOLDER = lab_store.DATA_FILE.parent / "report_logos"
INDEX = FOLDER / "logos.json"
MAX_BYTES = 4 * 1024 * 1024
MAX_SIDE = 600
_LOCK = threading.RLock()


def _read_index() -> list[dict]:
    try:
        raw = json.loads(INDEX.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [x for x in raw if isinstance(x, dict) and x.get("id") and x.get("file")]


def _write_index(items: list[dict]) -> None:
    FOLDER.mkdir(parents=True, exist_ok=True)
    tmp = INDEX.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(INDEX)


def logos() -> list[dict]:
    out = []
    sys_logo = ui.asset("logo.png") or ui.asset("logo-icon.png")
    if sys_logo:
        out.append({"id": SYSTEM, "name": "Computer Laboratory (system logo)", "path": sys_logo, "system": True})
    for x in _read_index():
        path = FOLDER / Path(x["file"]).name
        if path.is_file():
            out.append({"id": x["id"], "name": x.get("name") or "Logo", "path": path, "system": False})
    return out


def path_of(logo_id: str | None) -> Path | None:
    if not logo_id:
        return None
    for x in logos():
        if x["id"] == logo_id:
            return x["path"]
    return None


def data_uri(logo_id: str | None) -> str:
    path = path_of(logo_id)
    if not path:
        return ""
    try:
        return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()
    except OSError:
        return ""


def add(name: str, raw: bytes, by: str = "") -> tuple[bool, str]:
    """Check the upload is a real image, convert it to PNG and save it."""
    name = (name or "").strip()[:60]
    if not name:
        return False, "Give the logo a name, e.g. “ISU seal” or “CCSICT logo”."
    if not raw:
        return False, "Choose an image file first."
    if len(raw) > MAX_BYTES:
        return False, "That image is too large (4 MB at most)."
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(raw))
        img.load()
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA")
        img.thumbnail((MAX_SIDE, MAX_SIDE))
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        png = buf.getvalue()
    except Exception:
        return False, "That file isn't an image we can read. Use a PNG or JPG."
    with _LOCK:
        items = _read_index()
        if any((x.get("name") or "").lower() == name.lower() for x in items):
            return False, f"There is already a logo called “{name}”. Use another name or remove the old one."
        logo_id = uuid.uuid4().hex[:10]
        FOLDER.mkdir(parents=True, exist_ok=True)
        (FOLDER / f"{logo_id}.png").write_bytes(png)
        from frontend import lab_data as D

        items.append({"id": logo_id, "name": name, "file": f"{logo_id}.png",
                      "added": D.now().isoformat(), "by": by})
        _write_index(items)
    return True, f"“{name}” was added. You can now pick it for the left or right side of the header."


def remove(logo_id: str) -> bool:
    if not logo_id or logo_id == SYSTEM:
        return False
    with _LOCK:
        items = _read_index()
        keep = [x for x in items if x["id"] != logo_id]
        if len(keep) == len(items):
            return False
        try:
            (FOLDER / f"{logo_id}.png").unlink()
        except OSError:
            pass
        _write_index(keep)
    return True
