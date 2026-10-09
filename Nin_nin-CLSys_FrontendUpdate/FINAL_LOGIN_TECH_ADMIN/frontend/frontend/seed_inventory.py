"""
frontend/seed_inventory.py - Centrum Laboratory | inventory seed (idempotent)

Fills the shared inventory (data/centrum_lab.json) with 40 computers for every
registered laboratory (lab_data.LABS -> Centrum 1-4 = 160 computers):

    asset ID      CL<lab>-PC<nn>   (unique: one per laboratory seat)
    brand/model   per laboratory batch (Dell, Lenovo, Acer, HP)
    serial no.    unique, in the maker's usual format
    CPU, RAM, storage, graphics, monitor, keyboard & mouse, OS (with realistic upgrades)
    software      per laboratory (programming, networking, multimedia...)
    status        Working / Under maintenance / Inactive
    date added    purchase batch of the laboratory, a few later replacements
    maintenance history: none (empty)

Run it from the project root (the folder with app.py):

    python -m frontend.seed_inventory            # add what is missing
    python -m frontend.seed_inventory --dry-run  # only show what would be added

Re-running it never creates duplicates: a computer whose asset ID (or seat)
already exists is skipped, and edits made in the app are kept. The data is
generated from a fixed random seed, so it is the same on every machine.
The app also calls seed() once when the inventory is empty.
"""

from __future__ import annotations

import random
import string
import sys
from datetime import datetime, timedelta
from pathlib import Path

if __package__ in (None, ""):  # `python frontend/seed_inventory.py`
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from frontend import lab_data as D  # noqa: E402

# ---------------------------------------------------------------------------
# One purchase batch per laboratory
# ---------------------------------------------------------------------------
BATCHES = {
    1: {"brand": "Dell", "model": "OptiPlex 3080 Tower", "bought": datetime(2021, 6, 14),
        "cpu": [("Intel Core i5-10500", 7), ("Intel Core i5-10400", 3)],
        "ram": [("8 GB DDR4-2666", 6), ("16 GB DDR4-2666", 4)],
        "disk": [("256 GB NVMe SSD", 6), ("512 GB NVMe SSD", 3), ("256 GB NVMe SSD + 1 TB HDD", 1)],
        "gpu": [("Intel UHD 630", 1)],
        "monitor": [('Dell E2220H 21.5" LED', 8), ('Dell E2222H 21.5" LED', 2)],
        "kbm": [("Dell KB216 keyboard & MS116 mouse", 1)],
        "os": [("Windows 11 Pro 23H2", 7), ("Windows 10 Pro 22H2", 3)],
        "software": [("Microsoft Office", "2021"), ("Google Chrome", "129"), ("Visual Studio Code", "1.93"),
                     ("Python", "3.12"), ("Mozilla Firefox", "130"), ("Windows Defender", "Active")]},
    2: {"brand": "Lenovo", "model": "ThinkCentre M75s Gen 2", "bought": datetime(2022, 1, 24),
        "cpu": [("AMD Ryzen 5 PRO 4650G", 6), ("AMD Ryzen 5 3600", 4)],
        "ram": [("16 GB DDR4-3200", 8), ("8 GB DDR4-3200", 2)],
        "disk": [("512 GB NVMe SSD", 7), ("256 GB NVMe SSD", 3)],
        "gpu": [("AMD Radeon Graphics (integrated)", 6), ("NVIDIA GeForce GT 1030 2 GB", 4)],
        "monitor": [('Lenovo ThinkVision T22i-20 21.5"', 1)],
        "kbm": [("Lenovo Calliope USB keyboard & mouse", 1)],
        "os": [("Windows 11 Pro 23H2", 1)],
        "software": [("Microsoft Office", "2021"), ("Google Chrome", "129"), ("Visual Studio Code", "1.93"),
                     ("Python", "3.12"), ("Java JDK", "21"), ("NetBeans", "22"), ("XAMPP", "8.2"),
                     ("Windows Defender", "Active")]},
    3: {"brand": "Acer", "model": "Veriton X2690G", "bought": datetime(2020, 8, 3),
        "cpu": [("Intel Core i3-10100", 6), ("Intel Core i3-12100", 4)],
        "ram": [("8 GB DDR4-2666", 7), ("16 GB DDR4-2666", 3)],
        "disk": [("1 TB HDD", 5), ("256 GB SATA SSD", 3), ("256 GB SATA SSD + 1 TB HDD", 2)],
        "gpu": [("Intel UHD 630", 6), ("Intel UHD 730", 4)],
        "monitor": [('Acer V226HQL 21.5"', 1)],
        "kbm": [("Acer USB keyboard & mouse", 1)],
        "os": [("Windows 10 Pro 22H2", 7), ("Windows 11 Pro 23H2", 3)],
        "software": [("Microsoft Office", "2019"), ("Google Chrome", "129"), ("Packet Tracer", "8.2.2"),
                     ("Wireshark", "4.2"), ("PuTTY", "0.81"), ("Windows Defender", "Active")]},
    4: {"brand": "HP", "model": "ProDesk 400 G9 SFF", "bought": datetime(2023, 7, 10),
        "cpu": [("Intel Core i5-12500", 7), ("Intel Core i5-12400", 3)],
        "ram": [("16 GB DDR4-3200", 7), ("32 GB DDR4-3200", 3)],
        "disk": [("512 GB NVMe SSD", 8), ("1 TB NVMe SSD", 2)],
        "gpu": [("Intel UHD 770", 1)],
        "monitor": [('HP P24 G5 23.8" IPS', 1)],
        "kbm": [("HP 125 USB keyboard & 128 mouse", 1)],
        "os": [("Windows 11 Pro 23H2", 1)],
        "software": [("Microsoft Office", "2021"), ("Google Chrome", "129"), ("Adobe Photoshop", "2024"),
                     ("AutoCAD", "2024"), ("Blender", "4.1"), ("Visual Studio Code", "1.93"),
                     ("Windows Defender", "Active")]},
}
INSTRUCTOR = {"cpu": "Intel Core i7-12700", "ram": "32 GB DDR4-3200", "disk": "1 TB NVMe SSD"}


def _pick(rng: random.Random, options: list[tuple[str, int]]) -> str:
    values, weights = zip(*options)
    return rng.choices(values, weights=weights, k=1)[0]


def _serial(rng: random.Random, brand: str) -> str:
    up, dig = string.ascii_uppercase + string.digits, string.digits
    if brand == "Dell":  # 7-character service tag
        return "".join(rng.choice(up) for _ in range(7))
    if brand == "Lenovo":
        return "PC2" + "".join(rng.choice(up) for _ in range(5))
    if brand == "Acer":
        return "DTVX2SP" + "".join(rng.choice(dig) for _ in range(13))
    return "4CE" + "".join(rng.choice(dig) for _ in range(3)) + "".join(rng.choice(up) for _ in range(4))  # HP


def build_computer(lab: int, pc: int, taken_serials: set[str]) -> dict:
    """The seed record for one seat (deterministic for a given lab and seat)."""
    b = BATCHES[lab]
    rng = random.Random(f"centrum-{lab}-{pc}")
    instructor = pc == D.COMPUTERS_PER_LAB
    hw = {
        "Processor": INSTRUCTOR["cpu"] if instructor else _pick(rng, b["cpu"]),
        "Memory (RAM)": INSTRUCTOR["ram"] if instructor else _pick(rng, b["ram"]),
        "Storage": INSTRUCTOR["disk"] if instructor else _pick(rng, b["disk"]),
        "Graphics": _pick(rng, b["gpu"]),
        "Monitor": _pick(rng, b["monitor"]),
        "Keyboard & mouse": _pick(rng, b["kbm"]),
        "Operating system": _pick(rng, b["os"]),
    }
    serial = _serial(rng, b["brand"])
    while serial in taken_serials:
        serial = _serial(rng, b["brand"])
    taken_serials.add(serial)
    # Most units came with the lab's batch; about one in eight is a later replacement.
    if rng.random() < 0.12 and not instructor:
        added = b["bought"] + timedelta(days=rng.randint(120, 700), hours=rng.randint(8, 16))
    else:
        added = b["bought"] + timedelta(days=rng.randint(0, 4), hours=rng.randint(8, 16), minutes=rng.randint(0, 59))
    added = min(added, D.now() - timedelta(days=3))
    roll = rng.random()
    status = "Inactive" if roll < 0.03 else "Under maintenance" if roll < 0.08 else "Working"
    if instructor:
        status = "Working"
    software = [{"name": n, "version": v} for n, v in b["software"]]
    notes = "Instructor station (teacher's desk)." if instructor else ""
    if status == "Inactive":
        notes = "Pulled from service, kept in the Technician Room for parts check."
    comp = D.new_computer(lab, pc, hw, software, name="Instructor PC" if instructor else "",
                          notes=notes, added=added.replace(second=0, microsecond=0), brand=b["brand"],
                          model=b["model"], serial=serial, status=status)
    comp["log"] = []  # no maintenance history for seeded computers
    return comp


def seed(data: dict, dry_run: bool = False) -> tuple[int, int]:
    """Add the missing seed computers to `data` (a lab_store store). Returns (added, skipped)."""
    comps = data["computers"]
    tags = {c["tag"] for c in comps.values()}
    serials = {str(c.get("serial", "")) for c in comps.values() if c.get("serial")}
    added = skipped = 0
    for lab, _wing in D.LABS:
        if lab not in BATCHES:
            continue
        for pc in range(1, D.COMPUTERS_PER_LAB + 1):
            tag = D.asset_tag(lab, pc)
            if (lab, pc) in comps or tag in tags:
                skipped += 1
                continue
            comp = build_computer(lab, pc, serials)
            if not dry_run:
                comps[(lab, pc)] = comp
                tags.add(tag)
            added += 1
    return added, skipped


def main(argv: list[str] | None = None) -> int:
    from frontend import lab_store  # imported here: no Streamlit needed

    argv = sys.argv[1:] if argv is None else argv
    dry = "--dry-run" in argv
    data = lab_store.load_file()
    before = len(data["computers"])
    added, skipped = seed(data, dry_run=dry)
    if not dry and added:
        lab_store.save_file(data)
    tags = [c["tag"] for c in data["computers"].values()]
    assert len(tags) == len(set(tags)), "duplicate asset IDs found"
    print(f"Inventory file: {lab_store.DATA_FILE}")
    print(f"Computers before: {before}")
    print(f"{'Would add' if dry else 'Added'}: {added}   Already there (skipped): {skipped}")
    print(f"Computers now: {before if dry else len(data['computers'])}")
    for lab, _ in D.LABS:
        n = sum(1 for c in data["computers"].values() if c["lab"] == lab)
        print(f"  {D.lab_name(lab)}: {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
