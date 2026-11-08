"""
frontend/lab_layouts.py - Computer Laboratory | seat layout templates

Predefined layouts for laboratories added in the app (Inventory -> Add
laboratory). A template turns "N computers, W seats wide" into seat positions
on a grid; the front of the room (whiteboard / instructor) is at the top.

    TEMPLATES                      {id: (name, description)}
    positions(tpl, n, width)       -> ([(row, col), ...] one per computer, rows, cols)   1-based
    preview_svg(tpl, n, width)     -> a small SVG drawing of the room
    template_of(info)              -> the template id saved for a laboratory ("rows" if none)

Only the frontend uses this (the layout id is kept with the laboratory in the
shared lab store); the backend and the computers' records are not changed.
"""

from __future__ import annotations

import math

TEMPLATES = {
    "rows": ("Classroom rows", "Straight rows facing the front. Simple and fits the most computers."),
    "aisle": ("Rows with centre aisle", "Two blocks of rows with a walkway in the middle for easy access."),
    "ushape": ("U-shape", "Computers along the left, back and right walls; open space in the middle."),
    "perimeter": ("Perimeter + island", "Computers along the walls with a centre island of back-to-back desks."),
    "clusters": ("Clusters of 4", "Small pods of four computers - good for group work."),
}
DEFAULT = "rows"


def template_of(info: dict | None) -> str:
    tpl = (info or {}).get("layout")
    return tpl if tpl in TEMPLATES else DEFAULT


def _clamp_width(width) -> int:
    try:
        return max(2, min(12, int(width or 8)))
    except (TypeError, ValueError):
        return 8


def positions(tpl: str, n: int, width: int = 8) -> tuple[list[tuple[int, int]], int, int]:
    """Seat positions (row, col), 1-based, in seat order PC 01, PC 02, ...
    Returns (positions, rows, cols) - the size of the grid to draw."""
    n = max(0, int(n or 0))
    w = _clamp_width(width)
    if n == 0:
        return [], 1, w
    tpl = tpl if tpl in TEMPLATES else DEFAULT

    if tpl == "rows":
        return [(i // w + 1, i % w + 1) for i in range(n)], math.ceil(n / w), w

    if tpl == "aisle":
        left = math.ceil(w / 2)
        right = w - left
        cols = w + 1  # one empty column = the aisle
        out = []
        for i in range(n):
            r, c = divmod(i, w)
            out.append((r + 1, c + 1 if c < left else c + 2))
        return out, math.ceil(n / w), cols

    if tpl == "clusters":
        pods_per_row = max(1, w // 2)
        cols = pods_per_row * 3 - 1  # 2 seats + 1 gap per pod
        out = []
        for i in range(n):
            pod, seat = divmod(i, 4)
            pr, pc = divmod(pod, pods_per_row)
            out.append((pr * 3 + seat // 2 + 1, pc * 3 + seat % 2 + 1))
        rows = max(r for r, _ in out)
        return out, rows, cols

    if tpl == "ushape":
        # back wall: the chosen width, widened for big rooms so the U stays balanced
        cols = max(3, w, min(20, math.ceil(n / 2)))
        # depth of the side arms so that everything fits: back wall = cols seats
        side = max(1, math.ceil((n - cols) / 2)) if n > cols else 0
        rows = side + 1
        out = []
        for r in range(1, rows):  # left wall, front to back
            out.append((r, 1))
        for c in range(1, cols + 1):  # back wall, left to right
            out.append((rows, c))
        for r in range(rows - 1, 0, -1):  # right wall, back to front
            out.append((r, cols))
        if len(out) < n:  # more computers than the walls hold: extra row inside
            r = 1
            while len(out) < n:
                for c in range(3, cols - 1):
                    if len(out) >= n:
                        break
                    out.append((r + 1, c))
                r += 2
                rows = max(rows, r + 1)
        return out[:n], rows, cols

    # perimeter + centre island
    cols = max(5, w, min(20, math.ceil(n / 3)))
    # walls: left + back + right of depth d; island: 2 rows in the middle
    best = None
    for d in range(2, 40):
        rows = d + 1
        wall = (rows - 1) * 2 + cols
        island_cols = list(range(3, cols - 1))
        island_rows = [r for r in range(2, rows - 1, 3)]
        cap = wall + len(island_cols) * len(island_rows) * 2
        if cap >= n:
            best = (rows, island_cols, island_rows)
            break
    rows, island_cols, island_rows = best or (n, [], [])
    out = [(r, 1) for r in range(1, rows)]
    out += [(rows, c) for c in range(1, cols + 1)]
    out += [(r, cols) for r in range(rows - 1, 0, -1)]
    for r in island_rows:
        for dr in (0, 1):
            if r + dr < rows:
                out += [(r + dr, c) for c in island_cols]
    return out[:n], rows, cols


def preview_svg(tpl: str, n: int, width: int = 8, max_w: int = 360) -> str:
    """A small top-down drawing of the room: front (whiteboard) at the top,
    one rounded square per computer, numbered."""
    pos, rows, cols = positions(tpl, n, width)
    cell, gap, pad, front = 26, 6, 14, 26
    W = pad * 2 + cols * cell + (cols - 1) * gap
    H = pad * 2 + front + rows * cell + (rows - 1) * gap
    seats = "".join(
        f'<g><rect x="{pad + (c - 1) * (cell + gap)}" y="{pad + front + (r - 1) * (cell + gap)}" '
        f'width="{cell}" height="{cell - 6}" rx="4" fill="#e8f0fe" stroke="#2d6fe3" stroke-width="1.2"/>'
        f'<text x="{pad + (c - 1) * (cell + gap) + cell / 2}" y="{pad + front + (r - 1) * (cell + gap) + cell - 1}" '
        f'font-size="7" text-anchor="middle" fill="#14213d" font-family="sans-serif">{i + 1:02d}</text></g>'
        for i, (r, c) in enumerate(pos)
    )
    if not pos:
        seats = (f'<text x="{W / 2}" y="{pad + front + 14}" font-size="10" text-anchor="middle" fill="#8b93a1" '
                 'font-family="sans-serif">No computers yet</text>')
    board = (f'<rect x="{W * .25}" y="{pad - 4}" width="{W * .5}" height="6" rx="3" fill="#14213d"/>'
             f'<text x="{W / 2}" y="{pad + 14}" font-size="8.5" text-anchor="middle" fill="#5b6472" '
             'font-family="sans-serif">FRONT · whiteboard</text>')
    scale = min(1, max_w / W)
    return (f'<svg viewBox="0 0 {W} {H}" width="{W * scale:.0f}" height="{H * scale:.0f}" '
            f'xmlns="http://www.w3.org/2000/svg" role="img" aria-label="{TEMPLATES.get(tpl, TEMPLATES[DEFAULT])[0]} layout">'
            f'<rect x="1" y="1" width="{W - 2}" height="{H - 2}" rx="10" fill="#fafbfd" stroke="#d5dbe6" stroke-width="1.5"/>'
            f"{board}{seats}</svg>")
