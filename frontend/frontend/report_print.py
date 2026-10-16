"""
frontend/report_print.py - Computer Laboratory | printable reports (Admin + Technician)

The "Print reports" page: pick what to report on, the filters and the page
layout, look at the preview, then print it or download it as a PDF.

Report types
------------
all_labs   All laboratories - computers, working units and reports per lab
lab        One laboratory   - its computers and its reports
inventory  Filtered inventory (laboratory, status, search text)
computer   One computer     - details, hardware, software, maintenance, reports
issues     Maintenance & issues - reports and maintenance work in a date range

Every report has a title, the report date, Printed by, Printed at, the filters
used, a summary and the matching records. The page header (institution,
subtitle, logo) can be changed or left out, and the page can be portrait or
landscape, A4 or Letter.

Data
----
The records come from the dashboard's store - the same data the dashboard
shows, loaded from the backend (Supabase) when signed in. "Generate report"
reloads it from the database first, so a printed report is always current.

PDF export uses ReportLab (pip install reportlab). Without it, "Print"
still works and the browser's "Save as PDF" can be used.

    rc = report_print.ReportCenter(SHELL, store, me, "Admin")
    rc.page(s)
"""

from __future__ import annotations

import base64
import html as _html
import io
from datetime import date, datetime, time, timedelta

import streamlit as st
import streamlit.components.v1 as components

from frontend import lab_data as D
from frontend import ui
from frontend.portal import ic

ss = st.session_state
html, btn, box, h = ui.html, ui.btn, ui.box, ui.h

TYPES = {
    "all_labs": "All laboratories (summary)",
    "lab": "Selected laboratory",
    "inventory": "Inventory (filtered)",
    "computer": "Individual computer",
    "issues": "Maintenance & issues",
}
DEFAULT_TITLES = {
    "all_labs": "Laboratory Status Report - All Laboratories",
    "lab": "Laboratory Report",
    "inventory": "Computer Inventory Report",
    "computer": "Computer Report",
    "issues": "Maintenance and Issues Report",
}
PC_STATUS_KEYS = ["ok", "reported", "repair", "escalated", "maint", "inactive"]
REPORT_STATUS_KEYS = ["reported", "repair", "escalated", "fixed"]
RANGES = {
    "30": "Last 30 days",
    "7": "Last 7 days",
    "90": "Last 90 days",
    "365": "Last 12 months",
    "all": "All time",
    "custom": "Custom dates",
}
PAPER = {"A4": (210, 297), "Letter": (216, 279)}


# ===========================================================================
# Building a report (no Streamlit here - easy to test)
# ===========================================================================
def _status_text(st_: str) -> str:
    return D.computer_status_label(st_)[0]


def _report_status_text(st_: str) -> str:
    return D.STATUS.get(st_, (st_,))[0]


def _dt(t) -> str:
    return D.sent_date_time(t) if t else "—"


def _d(t) -> str:
    return D.sent_date(t) if t else "—"


def _in_range(t, start, end) -> bool:
    if t is None:
        return start is None and end is None
    return (start is None or t >= start) and (end is None or t < end)


def _report_rows(reports: list[dict], with_lab: bool = True) -> list[list[str]]:
    rows = []
    for r in sorted(reports, key=lambda r: r.get("created") or datetime.min, reverse=True):
        row = [str(r.get("id", ""))]
        if with_lab:
            row.append(D.lab_name(r.get("lab")))
        row += [
            D.pc_name(r.get("pc") or 0),
            str(r.get("issue") or "—"),
            str(r.get("by") or "—"),
            str(r.get("tech") or "—"),
            _d(r.get("sent", r.get("created"))),
            _report_status_text(r.get("status")),
        ]
        rows.append(row)
    return rows


def _report_cols(with_lab: bool = True) -> list[tuple[str, float]]:
    cols = [("Report", 0.8)]
    if with_lab:
        cols.append(("Laboratory", 1.1))
    return cols + [
        ("Computer", 0.75),
        ("Problem", 1.6),
        ("Reported by", 1.2),
        ("Technician", 1.2),
        ("Sent", 0.95),
        ("Status", 0.95),
    ]


def _counts_line(c: dict) -> list[tuple[str, str]]:
    return [
        ("New reports", str(c["reported"])),
        ("Reports under repair", str(c["repair"])),
        ("Escalated reports", str(c["escalated"])),
        ("Fixed reports", str(c["fixed"])),
    ]


def _avg_fix(reports: list[dict]) -> str:
    secs = [
        (D.fixed_at(r) - r["created"]).total_seconds()
        for r in reports
        if D.fixed_at(r) and r.get("created") and D.fixed_at(r) >= r["created"]
    ]
    return D.dur(sum(secs) / len(secs)) if secs else "—"


def _maint_rows(s: dict, comps: list[dict], start, end) -> list[list[str]]:
    items = []
    for c in comps:
        for e in D.maintenance_history(s, c):
            if _in_range(e.get("t"), start, end):
                items.append((e["t"], c, e))
    items.sort(key=lambda x: x[0], reverse=True)
    return [
        [_dt(t), c["tag"], D.lab_name(c["lab"]), str(e.get("kind", "")), str(e.get("text", "")), str(e.get("by", ""))]
        for t, c, e in items
    ]


MAINT_COLS = [("Date", 1.1), ("Computer", 0.9), ("Laboratory", 1.0), ("Type", 1.1), ("Details", 2.6), ("By", 1.0)]


def build_report(s: dict, o: dict, printed_by: str, printed_at: datetime) -> dict:
    """Make the report described by the options `o` from the store `s`.

    Returns {title, meta: [(label, value)], summary: [(label, value)],
    sections: [{heading, columns: [(name, weight)], rows: [[...]], kv?: [(k, v)], note?}]}.
    """
    kind = o.get("type", "all_labs")
    start, end = o.get("start"), o.get("end")
    lab = o.get("lab") or 0
    reports = list(s.get("reports") or [])
    comps = list((s.get("computers") or {}).values())
    period = o.get("period_label") or "All time"
    meta = [
        ("Report date", D.sent_date(printed_at)),
        ("Printed by", printed_by or "—"),
        ("Printed at", D.sent_date_time(printed_at)),
        ("Data source", "Live database" if s.get("live") else "Offline data (not connected to the server)"),
    ]
    summary: list[tuple[str, str]] = []
    sections: list[dict] = []
    title = (o.get("title") or "").strip() or DEFAULT_TITLES.get(kind, "Report")

    def in_period(r):
        return _in_range(r.get("created"), start, end)

    if kind == "all_labs":
        labs = [l for l, _ in D.LABS]
        rows = D.lab_breakdown(s, labs)
        meta.append(("Laboratories", "All laboratories"))
        meta.append(("Report period", period))
        total = sum(r["pc_all"] for r in rows)
        working = sum(r["pc_ok"] for r in rows)
        active = sum(r["pc_total"] for r in rows)
        pr = [r for r in reports if in_period(r)]
        cnt = D.report_counts(pr)
        summary = [
            ("Laboratories", str(len(labs))),
            ("Computers", str(total)),
            ("Working units", f"{working}" + (f" ({round(working / active * 100)}%)" if active else "")),
            ("Inactive PCs", str(sum(r["pc_inactive"] for r in rows))),
            ("Reports in period", str(len(pr))),
            *_counts_line(cnt),
            ("Open right now", str(len(D.open_reports(s)))),
        ]
        sections.append({
            "heading": "Computers per laboratory (current status)",
            "columns": [("Laboratory", 1.4), ("Building / wing", 1.4), ("Computers", .8), ("Working", .8),
                        ("Reported", .8), ("Under repair", .9), ("Escalated", .8), ("Maintenance", .9),
                        ("Inactive", .7)],
            "rows": [[r["name"], r["wing"], r["pc_all"], r["pc_ok"], r["pc_reported"], r["pc_under_repair"],
                      r["pc_escalated"], r["pc_maint"], r["pc_inactive"]] for r in rows]
            + [["Total", "", total, working, sum(r["pc_reported"] for r in rows),
                sum(r["pc_under_repair"] for r in rows), sum(r["pc_escalated"] for r in rows),
                sum(r["pc_maint"] for r in rows), sum(r["pc_inactive"] for r in rows)]],
            "total_row": True,
        })
        by_lab = [(l, D.report_counts(pr, l)) for l in labs]
        sections.append({
            "heading": f"Reports per laboratory ({period.lower()})",
            "columns": [("Laboratory", 1.6), ("New", .8), ("Under repair", .9), ("Escalated", .8),
                        ("Fixed", .8), ("Total", .8), ("Avg. time to fix", 1.1)],
            "rows": [[D.lab_name(l), c["reported"], c["repair"], c["escalated"], c["fixed"], c["total"],
                      _avg_fix([r for r in pr if r.get("lab") == l])] for l, c in by_lab]
            + [["Total", cnt["reported"], cnt["repair"], cnt["escalated"], cnt["fixed"], cnt["total"], _avg_fix(pr)]],
            "total_row": True,
        })
        if o.get("include_reports", True):
            open_r = [r for r in D.open_reports(s)]
            sections.append({
                "heading": "Open reports (not fixed yet)",
                "columns": _report_cols(),
                "rows": _report_rows(open_r),
                "empty": "No open reports.",
            })

    elif kind == "lab":
        lab = lab or (D.LABS[0][0] if D.LABS else 1)
        info = D.LAB_INFO.get(lab) or {}
        meta.append(("Laboratory", D.lab_name(lab)))
        meta.append(("Report period", period))
        sm = D.lab_summary(s, lab)
        lab_reports = [r for r in reports if r.get("lab") == lab and in_period(r)]
        cnt = D.report_counts(lab_reports)
        summary = [
            ("Computers", str(sm["all"])),
            ("Working units", f"{sm['ok']}" + (f" ({round(sm['ok'] / sm['total'] * 100)}%)" if sm["total"] else "")),
            ("PCs reported", str(sm["reported"])),
            ("PCs under repair", str(sm["under_repair"])),
            ("PCs escalated", str(sm["escalated"])),
            ("PCs under maintenance", str(sm["maint"])),
            ("PCs inactive", str(sm["inactive"])),
            ("Reports in period", str(len(lab_reports))),
            *_counts_line(cnt),
            ("Avg. time to fix", _avg_fix(lab_reports)),
        ]
        kv = [("Laboratory", D.lab_name(lab)), ("Code", D.lab_code(lab)),
              ("Building / wing", str(info.get("building") or info.get("wing") or D.WING.get(lab, "")))]
        if info.get("floor"):
            kv.append(("Floor", str(info["floor"])))
        if info.get("room") and info.get("room") != D.lab_name(lab):
            kv.append(("Room", str(info["room"])))
        if info.get("desc"):
            kv.append(("Description", str(info["desc"])))
        sections.append({"heading": "Laboratory details", "kv": kv})
        if o.get("include_computers", True):
            lab_comps = D.lab_computers(s, lab)
            sections.append({
                "heading": "Computers",
                "columns": [("Asset ID", 1.0), ("Seat", .6), ("Name", 1.1), ("CPU · RAM · Storage", 2.4),
                            ("Operating system", 1.3), ("Status", 1.0), ("Last serviced", 1.0)],
                "rows": [[c["tag"], D.pc_name(c["pc"]), c["name"] if c["name"] != c["tag"] else "—",
                          D.spec_line(c) or "—", c["hardware"].get("Operating system", "—"),
                          _status_text(D.pc_status(s, lab, c["pc"])), _d(D.last_serviced(s, c))]
                         for c in lab_comps],
                "empty": "No computers registered in this laboratory.",
            })
        if o.get("include_reports", True):
            sections.append({
                "heading": f"Reports ({period.lower()})",
                "columns": _report_cols(with_lab=False),
                "rows": _report_rows(lab_reports, with_lab=False),
                "empty": "No reports in this period.",
            })

    elif kind == "inventory":
        statuses = o.get("statuses") or PC_STATUS_KEYS
        words = [w for w in str(o.get("search") or "").lower().split() if w]
        meta.append(("Laboratory", D.lab_name(lab) if lab else "All laboratories"))
        meta.append(("Status", ", ".join(_status_text(x) for x in statuses)
                     if set(statuses) != set(PC_STATUS_KEYS) else "All statuses"))
        if words:
            meta.append(("Search", " ".join(words)))
        picked = []
        for c in comps:
            if lab and c["lab"] != lab:
                continue
            st_ = D.pc_status(s, c["lab"], c["pc"])
            if st_ not in statuses:
                continue
            text = D.search_text(c)
            if not all(w in text for w in words):
                continue
            picked.append((c, st_))
        picked.sort(key=lambda x: (x[0]["lab"], x[0]["pc"]))
        by_status = {k: sum(1 for _, st_ in picked if st_ == k) for k in PC_STATUS_KEYS}
        summary = [("Computers listed", str(len(picked)))] + [
            (_status_text(k), str(v)) for k, v in by_status.items() if v or k in ("ok",)
        ]
        sections.append({
            "heading": "Computers",
            "columns": [("Asset ID", 1.0), ("Laboratory", 1.0), ("Seat", .6), ("Brand / model", 1.2),
                        ("Serial no.", 1.0), ("CPU · RAM · Storage", 2.2), ("Operating system", 1.2),
                        ("Status", .95), ("Date added", .95)],
            "rows": [[c["tag"], D.lab_name(c["lab"]), D.pc_name(c["pc"]),
                      " ".join(x for x in (c.get("brand"), c.get("model")) if x) or "—",
                      c.get("serial") or "—", D.spec_line(c) or "—",
                      c["hardware"].get("Operating system", "—"), _status_text(st_), _d(c.get("added"))]
                     for c, st_ in picked],
            "empty": "No computers match the filters.",
        })

    elif kind == "computer":
        key = tuple(o.get("computer") or ())
        comp = (s.get("computers") or {}).get(key)
        if comp is None:
            meta.append(("Computer", "—"))
            sections.append({"heading": "Computer", "kv": [("Computer", "Not found in the inventory.")]})
        else:
            lab_, pc = comp["lab"], comp["pc"]
            st_ = D.pc_status(s, lab_, pc)
            pc_reports = [r for r in reports if r.get("lab") == lab_ and r.get("pc") == pc and in_period(r)]
            history = [e for e in D.maintenance_history(s, comp) if _in_range(e.get("t"), start, end)]
            meta.append(("Computer", f"{comp['tag']} · {D.lab_name(lab_)} {D.pc_name(pc)}"))
            meta.append(("Report period", period))
            cnt = D.report_counts(pc_reports)
            summary = [
                ("Current status", _status_text(st_)),
                ("Reports in period", str(len(pc_reports))),
                *_counts_line(cnt),
                ("Maintenance entries", str(len(history))),
                ("Last serviced", _d(D.last_serviced(s, comp))),
            ]
            model = " ".join(x for x in (comp.get("brand"), comp.get("model")) if x)
            sections.append({"heading": "Computer details", "kv": [
                ("Asset ID", comp["tag"]), ("Name", comp["name"]),
                ("Laboratory", f"{D.lab_name(lab_)} ({D.WING.get(lab_, '')})"), ("Seat", D.pc_name(pc)),
                ("Brand / model", model or "—"), ("Serial number", comp.get("serial") or "—"),
                ("Record status", comp.get("status", "Working")), ("Live status", _status_text(st_)),
                ("Date added", _d(comp.get("added"))), ("Notes", comp.get("notes") or "—"),
            ]})
            sections.append({
                "heading": "Hardware",
                "columns": [("Component", 1.2), ("Details", 3.0)],
                "rows": [[k, v] for k, v in comp["hardware"].items()],
                "empty": "No hardware recorded.",
            })
            sections.append({
                "heading": "Software",
                "columns": [("Program", 2.0), ("Version", 1.0), ("Installed", 1.0)],
                "rows": [[x.get("name", ""), x.get("version") or "—", _d(D.parse_dt(x.get("installed")))]
                         for x in comp["software"]],
                "empty": "No software recorded.",
            })
            sections.append({
                "heading": f"Maintenance history ({period.lower()})",
                "columns": [("Date", 1.1), ("Type", 1.1), ("Details", 3.0), ("By", 1.0)],
                "rows": [[_dt(e["t"]), e.get("kind", ""), e.get("text", ""), e.get("by", "")]
                         for e in history],
                "empty": "No maintenance recorded in this period.",
            })
            sections.append({
                "heading": f"Reports ({period.lower()})",
                "columns": [c for c in _report_cols(with_lab=False) if c[0] != "Computer"],
                "rows": [[row[0]] + row[2:] for row in _report_rows(pc_reports, with_lab=False)],
                "empty": "No reports in this period.",
            })

    else:  # issues
        statuses = o.get("rstatuses") or REPORT_STATUS_KEYS
        meta.append(("Laboratory", D.lab_name(lab) if lab else "All laboratories"))
        meta.append(("Report period", period))
        meta.append(("Report status", ", ".join(_report_status_text(x) for x in statuses)
                     if set(statuses) != set(REPORT_STATUS_KEYS) else "All statuses"))
        pr = [r for r in reports if (not lab or r.get("lab") == lab) and in_period(r)
              and r.get("status") in statuses]
        cnt = D.report_counts(pr)
        by_issue: dict = {}
        for r in pr:
            by_issue[r.get("issue") or "Other"] = by_issue.get(r.get("issue") or "Other", 0) + 1
        lab_comps = [c for c in comps if not lab or c["lab"] == lab]
        maint = _maint_rows(s, lab_comps, start, end) if o.get("include_maint", True) else []
        summary = [("Reports", str(len(pr))), *_counts_line(cnt), ("Avg. time to fix", _avg_fix(pr))]
        if o.get("include_maint", True):
            summary.append(("Maintenance activities", str(len(maint))))
        sections.append({
            "heading": "Reports / issues",
            "columns": _report_cols(),
            "rows": _report_rows(pr),
            "empty": "No reports match the filters.",
        })
        if by_issue:
            sections.append({
                "heading": "Problems reported",
                "columns": [("Problem", 3.0), ("Reports", 1.0)],
                "rows": [[k, v] for k, v in sorted(by_issue.items(), key=lambda x: -x[1])],
            })
        if o.get("include_maint", True):
            sections.append({
                "heading": "Maintenance activities",
                "columns": MAINT_COLS,
                "rows": maint,
                "empty": "No maintenance recorded in this period.",
            })

    for sec in sections:
        sec["rows"] = [[("" if v is None else str(v)) for v in row] for row in sec.get("rows", [])]
    return {"title": title, "meta": meta, "summary": summary, "sections": sections}


# ===========================================================================
# HTML (preview + print)
# ===========================================================================
def _logo_data_uri() -> str:
    path = ui.asset("logo.png") or ui.asset("logo-icon.png")
    if not path:
        return ""
    try:
        return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()
    except OSError:
        return ""


def to_html(rep: dict, layout: dict, printable: bool = True) -> str:
    e = _html.escape
    orient = layout.get("orientation", "portrait")
    paper = layout.get("paper", "A4")
    head = ""
    if layout.get("header", True):
        logo = _logo_data_uri() if layout.get("logo", True) else ""
        head = (
            '<header class="rh">'
            + (f'<img src="{logo}" alt="">' if logo else "")
            + f'<div><div class="inst">{e(layout.get("institution") or "")}</div>'
            + (f'<div class="subt">{e(layout.get("subtitle") or "")}</div>' if layout.get("subtitle") else "")
            + (f'<div class="addr">{e(layout.get("address") or "")}</div>' if layout.get("address") else "")
            + "</div></header>"
        )
    meta = "".join(f"<div><span>{e(k)}</span><b>{e(v)}</b></div>" for k, v in rep["meta"])
    summ = "".join(f"<div><b>{e(v)}</b><span>{e(k)}</span></div>" for k, v in rep["summary"])
    body = ""
    for sec in rep["sections"]:
        body += f'<h2>{e(sec["heading"])}</h2>'
        if sec.get("kv"):
            body += '<table class="kv">' + "".join(
                f"<tr><th>{e(k)}</th><td>{e(v)}</td></tr>" for k, v in sec["kv"]) + "</table>"
            continue
        if not sec["rows"]:
            body += f'<p class="none">{e(sec.get("empty") or "No records.")}</p>'
            continue
        total = sum(w for _, w in sec["columns"]) or 1
        cols = "".join(f'<col style="width:{w / total * 100:.1f}%">' for _, w in sec["columns"])
        th = "".join(f"<th>{e(c)}</th>" for c, _ in sec["columns"])
        rows = sec["rows"]
        trs = ""
        for i, row in enumerate(rows):
            cls = ' class="tot"' if sec.get("total_row") and i == len(rows) - 1 else ""
            trs += f"<tr{cls}>" + "".join(f"<td>{e(v)}</td>" for v in row) + "</tr>"
        body += (f'<table class="grid"><colgroup>{cols}</colgroup><thead><tr>{th}</tr></thead>'
                 f'<tbody>{trs}</tbody></table><div class="cnt">{len(rows) - (1 if sec.get("total_row") else 0)} record(s)</div>')
    toolbar = (
        '<div class="bar noprint"><button onclick="window.print()">Print</button>'
        f'<span>{e(paper)} · {e(orient.title())}. In the print window choose "Save as PDF" to keep a copy.</span></div>'
        if printable else ""
    )
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>{e(rep['title'])}</title><style>
@page {{ size: {paper} {orient}; margin: 14mm 12mm 16mm; }}
* {{ box-sizing: border-box; }}
body {{ font: 10.5pt/1.45 'Segoe UI', Roboto, Arial, sans-serif; color: #1c2433; margin: 0; background: #eef1f6; }}
.page {{ background: #fff; margin: 12px auto; padding: 14mm 12mm; max-width: {'297mm' if orient == 'landscape' else '210mm'};
  box-shadow: 0 4px 18px rgba(20,33,61,.12); }}
.rh {{ display: flex; gap: 14px; align-items: center; border-bottom: 2px solid #14213d; padding-bottom: 10px; margin-bottom: 14px; }}
.rh img {{ height: 52px; }}
.inst {{ font: 700 15pt 'Poppins', 'Segoe UI', sans-serif; color: #14213d; }}
.subt {{ font-size: 10.5pt; color: #4b5568; }} .addr {{ font-size: 9pt; color: #6b7385; }}
h1 {{ font: 700 16pt 'Poppins', 'Segoe UI', sans-serif; color: #14213d; margin: 0 0 8px; }}
h2 {{ font: 600 11.5pt 'Poppins', 'Segoe UI', sans-serif; color: #14213d; margin: 18px 0 6px; page-break-after: avoid; }}
.meta {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 4px 18px; font-size: 9.5pt; margin-bottom: 12px; }}
.meta span {{ color: #6b7385; margin-right: 6px; }}
.sum {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(110px, 1fr)); gap: 6px; margin: 6px 0 4px; }}
.sum div {{ border: 1px solid #dfe4ee; border-radius: 6px; padding: 6px 8px; }}
.sum b {{ display: block; font-size: 13pt; color: #14213d; }} .sum span {{ font-size: 8.5pt; color: #6b7385; }}
table {{ width: 100%; border-collapse: collapse; table-layout: fixed; }}
table.grid th {{ background: #14213d; color: #fff; font-weight: 600; font-size: 9pt; text-align: left; padding: 5px 6px; }}
table.grid td {{ border-bottom: 1px solid #e3e7ef; padding: 4px 6px; font-size: 9pt; vertical-align: top; word-wrap: break-word; }}
table.grid tbody tr:nth-child(even) td {{ background: #f7f9fc; }}
table.grid tr.tot td {{ font-weight: 700; background: #eef2f8 !important; border-top: 1.5px solid #14213d; }}
table.grid thead {{ display: table-header-group; }} table.grid tr {{ page-break-inside: avoid; }}
table.kv th {{ text-align: left; width: 28%; color: #6b7385; font-weight: 500; padding: 3px 6px; font-size: 9.5pt; vertical-align: top; }}
table.kv td {{ padding: 3px 6px; font-size: 9.5pt; }}
.cnt {{ font-size: 8.5pt; color: #6b7385; margin-top: 3px; }} .none {{ color: #6b7385; font-style: italic; }}
.foot {{ margin-top: 18px; border-top: 1px solid #dfe4ee; padding-top: 6px; font-size: 8.5pt; color: #6b7385; display: flex; justify-content: space-between; }}
.bar {{ position: sticky; top: 0; z-index: 2; display: flex; gap: 12px; align-items: center; background: #14213d; color: #dbe3f3;
  padding: 8px 14px; font-size: 12px; }}
.bar button {{ background: #2d6fe3; color: #fff; border: 0; border-radius: 8px; padding: 7px 16px; font: 600 13px sans-serif; cursor: pointer; }}
@media print {{ body {{ background: #fff; }} .noprint {{ display: none !important; }}
  .page {{ box-shadow: none; margin: 0; padding: 0; max-width: none; }} }}
</style></head><body>{toolbar}<div class="page">{head}<h1>{e(rep['title'])}</h1><div class="meta">{meta}</div>
<h2>Summary</h2><div class="sum">{summ}</div>{body}
<div class="foot"><span>{e(layout.get('institution') or 'Computer Laboratory')} · {e(rep['title'])}</span>
<span>Printed by {e(dict(rep['meta']).get('Printed by', ''))} · {e(dict(rep['meta']).get('Printed at', ''))}</span></div>
</div></body></html>"""


# ===========================================================================
# PDF (ReportLab)
# ===========================================================================
def pdf_available() -> bool:
    try:
        import reportlab  # noqa: F401
    except ImportError:
        return False
    return True


def to_pdf(rep: dict, layout: dict) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4, landscape, letter, portrait
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table,
                                    TableStyle)

    def x(t):
        return _html.escape(str(t if t is not None else ""))

    size = {"A4": A4, "Letter": letter}.get(layout.get("paper", "A4"), A4)
    size = landscape(size) if layout.get("orientation") == "landscape" else portrait(size)
    buf = io.BytesIO()
    margin = 12 * mm
    doc = SimpleDocTemplate(buf, pagesize=size, leftMargin=margin, rightMargin=margin,
                            topMargin=14 * mm, bottomMargin=16 * mm, title=rep["title"],
                            author=dict(rep["meta"]).get("Printed by", ""))
    width = size[0] - 2 * margin
    ss_ = getSampleStyleSheet()
    navy = colors.HexColor("#14213d")
    grey = colors.HexColor("#6b7385")
    st_inst = ParagraphStyle("inst", parent=ss_["Normal"], fontName="Helvetica-Bold", fontSize=14, leading=17, textColor=navy)
    st_sub = ParagraphStyle("sub", parent=ss_["Normal"], fontSize=9.5, leading=12, textColor=colors.HexColor("#4b5568"))
    st_h1 = ParagraphStyle("h1", parent=ss_["Normal"], fontName="Helvetica-Bold", fontSize=15, leading=19, textColor=navy, spaceAfter=6)
    st_h2 = ParagraphStyle("h2", parent=ss_["Normal"], fontName="Helvetica-Bold", fontSize=11, leading=14, textColor=navy, spaceBefore=10, spaceAfter=4)
    st_cell = ParagraphStyle("cell", parent=ss_["Normal"], fontSize=8, leading=10, alignment=TA_LEFT)
    st_head = ParagraphStyle("head", parent=st_cell, fontName="Helvetica-Bold", textColor=colors.white)
    st_meta = ParagraphStyle("meta", parent=ss_["Normal"], fontSize=8.5, leading=11)
    st_none = ParagraphStyle("none", parent=ss_["Normal"], fontSize=8.5, textColor=grey, fontName="Helvetica-Oblique")
    story = []

    if layout.get("header", True):
        text = [Paragraph(x(layout.get("institution") or ""), st_inst)]
        if layout.get("subtitle"):
            text.append(Paragraph(x(layout["subtitle"]), st_sub))
        if layout.get("address"):
            text.append(Paragraph(x(layout["address"]), st_sub))
        logo_path = (ui.asset("logo.png") or ui.asset("logo-icon.png")) if layout.get("logo", True) else None
        cells = []
        if logo_path:
            try:
                from reportlab.lib.utils import ImageReader
                iw, ih = ImageReader(str(logo_path)).getSize()
                hgt = 14 * mm
                cells.append(Image(str(logo_path), width=hgt * iw / ih, height=hgt))
            except Exception:
                cells = []
        tbl = Table([cells + [text]], colWidths=([None] if cells else []) + [None])
        tbl.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                 ("LINEBELOW", (0, 0), (-1, -1), 1.5, navy), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
        tbl.hAlign = "LEFT"
        story += [tbl, Spacer(1, 8)]

    story.append(Paragraph(x(rep["title"]), st_h1))
    meta = [Paragraph(f'<font color="#6b7385">{x(k)}:</font> <b>{x(v)}</b>', st_meta) for k, v in rep["meta"]]
    per_row = 3
    meta_rows = [meta[i:i + per_row] + [""] * (per_row - len(meta[i:i + per_row])) for i in range(0, len(meta), per_row)]
    mt = Table(meta_rows, colWidths=[width / per_row] * per_row)
    mt.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 1),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
    story += [mt, Paragraph("Summary", st_h2)]

    sp = [Paragraph(f'<font size="12"><b>{x(v)}</b></font><br/><font color="#6b7385" size="7.5">{x(k)}</font>', st_cell)
          for k, v in rep["summary"]]
    n = max(1, int(width // (32 * mm)))
    srows = [sp[i:i + n] + [""] * (n - len(sp[i:i + n])) for i in range(0, len(sp), n)] or [[""]]
    stbl = Table(srows, colWidths=[width / n] * n)
    stbl.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), .5, colors.HexColor("#dfe4ee")),
                              ("INNERGRID", (0, 0), (-1, -1), .5, colors.HexColor("#dfe4ee")),
                              ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(stbl)

    for sec in rep["sections"]:
        heading = Paragraph(x(sec["heading"]), st_h2)
        if sec.get("kv"):
            kv = Table([[Paragraph(f'<font color="#6b7385">{x(k)}</font>', st_cell), Paragraph(x(v), st_cell)]
                        for k, v in sec["kv"]], colWidths=[width * .28, width * .72])
            kv.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 2), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                    ("LINEBELOW", (0, 0), (-1, -1), .3, colors.HexColor("#e3e7ef"))]))
            story.append(KeepTogether([heading, kv]))
            continue
        if not sec["rows"]:
            story.append(KeepTogether([heading, Paragraph(x(sec.get("empty") or "No records."), st_none)]))
            continue
        total = sum(w for _, w in sec["columns"]) or 1
        widths = [width * w / total for _, w in sec["columns"]]
        data = [[Paragraph(x(c), st_head) for c, _ in sec["columns"]]]
        data += [[Paragraph(x(v), st_cell) for v in row] for row in sec["rows"]]
        t = Table(data, colWidths=widths, repeatRows=1)
        style = [("BACKGROUND", (0, 0), (-1, 0), navy), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                 ("LINEBELOW", (0, 1), (-1, -1), .3, colors.HexColor("#e3e7ef")),
                 ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7f9fc")]),
                 ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                 ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4)]
        if sec.get("total_row"):
            style += [("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#eef2f8")),
                      ("LINEABOVE", (0, -1), (-1, -1), 1, navy),
                      ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold")]
        t.setStyle(TableStyle(style))
        n_rec = len(sec["rows"]) - (1 if sec.get("total_row") else 0)
        story += [heading, t, Paragraph(f'<font color="#6b7385" size="7.5">{n_rec} record(s)</font>', st_cell)]

    foot_l = f'{layout.get("institution") or "Computer Laboratory"} · {rep["title"]}'
    m = dict(rep["meta"])
    foot_r = f'Printed by {m.get("Printed by", "")} · {m.get("Printed at", "")}'

    def footer(canvas, doc_):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(grey)
        canvas.drawString(margin, 9 * mm, foot_l[:110])
        canvas.drawRightString(size[0] - margin, 9 * mm, f"{foot_r}   ·   Page {doc_.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()


# ===========================================================================
# Opening the generator from another page (Inventory / Reports "Generate report")
# ===========================================================================
def open_generator(shell, kind: str, *, lab: int = 0, statuses=None, rstatuses=None,
                   search: str = "", period: str = "all") -> None:
    """Go to the "Print reports" page with the report type and filters already
    set from the page the user was on, reload the data from the database and
    show the preview straight away."""
    p = shell.p

    def put(key, value):
        ss[key] = value
        ss["_keep_" + key] = value

    put(f"{p}_rp_type__selwide__", kind)
    put(f"{p}_rp_title", DEFAULT_TITLES.get(kind, "Report"))
    if kind in ("inventory", "issues"):
        put(f"{p}_rp_lab0__sel__", lab or 0)
    elif kind == "lab" and lab:
        put(f"{p}_rp_lab1__sel__", lab)
    if statuses is not None:
        put(f"{p}_rp_pcst", list(statuses) or list(PC_STATUS_KEYS))
    if rstatuses is not None:
        put(f"{p}_rp_rst", list(rstatuses) or list(REPORT_STATUS_KEYS))
    put(f"{p}_rp_search__search__", search or "")
    if kind != "inventory":
        put(f"{p}_rp_range__sel__", period if period in RANGES else "all")
    if ss.get(ui.TOKEN_KEY) and not ss.get(f"{p}_preview"):
        ss.pop(f"{p}_data", None)  # read the latest records from the database
    ss[f"{p}_rp_at"] = D.now()
    ss[f"{p}_rp_show"] = True
    shell.go("print")


# ===========================================================================
# The page
# ===========================================================================
class ReportCenter:
    def __init__(self, shell, store_fn, me_fn, role: str):
        self.shell = shell
        self.p = shell.p
        self.store = store_fn
        self.me = me_fn
        self.role = role

    def k(self, name: str) -> str:
        return f"{self.p}_rp_{name}"

    # ---- callbacks ---------------------------------------------------------
    def _generate(self) -> None:
        """Reload the data from the database, then show the preview."""
        if ss.get(ui.TOKEN_KEY) and not ss.get(f"{self.p}_preview"):
            ss.pop(f"{self.p}_data", None)
        ss[self.k("at")] = D.now()
        ss[self.k("show")] = True

    def _hide(self) -> None:
        ss[self.k("show")] = False

    def _type_changed(self) -> None:
        kind = ss.get(self.k("type__selwide__"))
        ss[self.k("title")] = DEFAULT_TITLES.get(kind, "Report")
        ss[self.k("show")] = False

    # ---- widgets -----------------------------------------------------------
    def _sel(self, label: str, name: str, options: list, fmt=None, wide=False, on_change=None):
        key = ui.sticky(self.k(name) + ("__selwide__" if wide else "__sel__"), options)
        with box(key + "_f", "field"):
            html(f'<div class="adm-label">{h(label)}</div>')
            value = st.selectbox(label, options, format_func=fmt or str, key=key,
                                 label_visibility="collapsed", on_change=on_change)
        ui.remember(key)
        return value

    def _options(self, s: dict) -> tuple[dict, dict]:
        p = self.p
        o: dict = {}
        kinds = list(TYPES)
        kind = self._sel("Report type", "type", kinds, TYPES.get, wide=True, on_change=self._type_changed)
        o["type"] = kind
        labs = [lab for lab, _ in D.LABS]
        with box(f"{p}_rp_fgrid", "formgrid"):
            if kind == "lab":
                o["lab"] = self._sel("Laboratory", "lab1", labs, D.lab_name)
            elif kind in ("inventory", "issues"):
                o["lab"] = self._sel("Laboratory", "lab0", [0] + labs,
                                     lambda x: D.lab_name(x) if x else "All laboratories")
            elif kind == "computer":
                lab = self._sel("Laboratory", "clab", labs, D.lab_name)
                pcs = [c["pc"] for c in D.lab_computers(s, lab)]
                if pcs:
                    pc = self._sel("Computer", f"cpc_{lab}", pcs,
                                   lambda n: f"{D.asset_tag(lab, n)} · {D.pc_name(n)}")
                    o["computer"] = (lab, pc)
                else:
                    html('<div class="adm-help" style="margin-top:28px">No computers in this laboratory.</div>')
                    o["computer"] = None
            if kind != "inventory":
                rng = self._sel("Report period", "range", list(RANGES), RANGES.get)
                o["range"] = rng
            if kind == "inventory":
                key = ui.sticky(self.k("search__search__"))
                with box(key + "_f", "field"):
                    html('<div class="adm-label">Search</div>')
                    st.text_input("Search", key=key, placeholder="Asset ID, CPU, serial, software...",
                                  label_visibility="collapsed")
                ui.remember(key)
                o["search"] = ss.get(key) or ""
        if kind != "inventory" and o.get("range") == "custom":
            with box(f"{p}_rp_dates", "formgrid"):
                today = date.today()
                for name, label, default in (("from", "From", today - timedelta(days=30)), ("to", "To", today)):
                    key = self.k(name)
                    if key not in ss:
                        ss[key] = ss.get("_keep_" + key) or default
                    with box(key + "_f", "field"):
                        html(f'<div class="adm-label">{label}</div>')
                        st.date_input(label, key=key, label_visibility="collapsed", format="MM/DD/YYYY")
                    ui.remember(key)
        if kind == "inventory":
            key = ui.sticky(self.k("pcst"))
            if key not in ss:
                ss[key] = list(PC_STATUS_KEYS)
            with box(key + "_f", "field"):
                html('<div class="adm-label">Computer status</div>')
                st.multiselect("Computer status", PC_STATUS_KEYS, key=key, format_func=_status_text,
                               label_visibility="collapsed", placeholder="All statuses")
            ui.remember(key)
            o["statuses"] = ss.get(key) or list(PC_STATUS_KEYS)
        if kind == "issues":
            key = ui.sticky(self.k("rst"))
            if key not in ss:
                ss[key] = list(REPORT_STATUS_KEYS)
            with box(key + "_f", "field"):
                html('<div class="adm-label">Report status</div>')
                st.multiselect("Report status", REPORT_STATUS_KEYS, key=key, format_func=_report_status_text,
                               label_visibility="collapsed", placeholder="All statuses")
            ui.remember(key)
            o["rstatuses"] = ss.get(key) or list(REPORT_STATUS_KEYS)
        with box(f"{p}_rp_inc", "row"):
            if kind in ("all_labs", "lab"):
                o["include_reports"] = self._check("Include the reports list", "increp", True)
            if kind == "lab":
                o["include_computers"] = self._check("Include the computer list", "incpc", True)
            if kind == "issues":
                o["include_maint"] = self._check("Include maintenance activities", "incmt", True)

        # period -> start / end
        rng = o.get("range", "all")
        if rng == "custom":
            d1 = ss.get(self.k("from")) or date.today() - timedelta(days=30)
            d2 = ss.get(self.k("to")) or date.today()
            if d1 > d2:
                d1, d2 = d2, d1
            o["start"] = datetime.combine(d1, time.min)
            o["end"] = datetime.combine(d2 + timedelta(days=1), time.min)
            o["period_label"] = f"{D.sent_date(o['start'])} to {D.sent_date(datetime.combine(d2, time.min))}"
        elif rng and rng != "all":
            o["start"] = D.now() - timedelta(days=int(rng))
            o["end"] = None
            o["period_label"] = f"{RANGES[rng]} ({D.sent_date(o['start'])} to {D.sent_date(D.now())})"
        else:
            o["start"] = o["end"] = None
            o["period_label"] = "All time"
        return o, {}

    def _check(self, label: str, name: str, default: bool) -> bool:
        key = self.k(name)
        if key not in ss:
            ss[key] = ss.get("_keep_" + key, default)
        st.checkbox(label, key=key)
        ui.remember(key)
        return bool(ss.get(key))

    def _text(self, label: str, name: str, default: str, placeholder: str = "", max_chars: int = 120) -> str:
        key = self.k(name)
        if key not in ss:
            ss[key] = ss.get("_keep_" + key, default)
        with box(key + "_f", "field"):
            html(f'<div class="adm-label">{h(label)}</div>')
            st.text_input(label, key=key, placeholder=placeholder, label_visibility="collapsed", max_chars=max_chars)
        ui.remember(key)
        return str(ss.get(key) or "")

    def _layout(self, kind: str) -> dict:
        p = self.p
        lay: dict = {}
        if self.k("title") not in ss:
            ss[self.k("title")] = ss.get("_keep_" + self.k("title")) or DEFAULT_TITLES.get(kind, "Report")
        lay["title"] = self._text("Report title", "title", DEFAULT_TITLES.get(kind, "Report"))
        with box(f"{p}_rp_lay_row", "row"):
            lay["header"] = self._check("Show the page header", "hdr", True)
            if lay["header"]:
                lay["logo"] = self._check("Show the logo", "logo", True)
        if lay["header"]:
            with box(f"{p}_rp_hgrid", "formgrid"):
                lay["institution"] = self._text("Header line (institution)", "inst", "Computer Laboratory")
                lay["subtitle"] = self._text("Header subtitle", "subt", "Centrum Laboratories · IT Laboratory · CSSC Laboratory")
            lay["address"] = self._text("Header note (address, department...)", "addr", "",
                                        "Optional, e.g. Centrum Building, Main Campus")
        else:
            lay["institution"] = str(ss.get(self.k("inst")) or "Computer Laboratory")
        with box(f"{p}_rp_page", "row"):
            html('<span class="adm-label" style="margin:0 6px 0 0">Orientation</span>')
            okey = self.k("orient")
            ss.setdefault(okey, ss.get("_keep_" + okey, "portrait"))
            with box(f"{p}_rp_orient", "segs"):
                for val, label, icon in (("portrait", "Portrait", ":material/crop_portrait:"),
                                         ("landscape", "Landscape", ":material/crop_landscape:")):
                    btn(label, f"{p}_rp_o_{val}", "segbon" if ss[okey] == val else "segb", icon=icon,
                        on_click=self._set_keep, args=(okey, val))
            html('<span class="adm-label" style="margin:0 6px 0 14px">Paper</span>')
            pkey = self.k("paper")
            ss.setdefault(pkey, ss.get("_keep_" + pkey, "A4"))
            with box(f"{p}_rp_paper", "segs"):
                for val in PAPER:
                    btn(val, f"{p}_rp_pp_{val}", "segbon" if ss[pkey] == val else "segb",
                        on_click=self._set_keep, args=(pkey, val))
        lay["orientation"] = ss[okey]
        lay["paper"] = ss[pkey]
        return lay

    @staticmethod
    def _set_keep(key: str, value) -> None:
        ss[key] = value
        ss["_keep_" + key] = value

    # ---- page --------------------------------------------------------------
    def page(self, s: dict) -> None:
        p = self.p
        with box(f"{p}_rp_grid", "g2"):
            with box(f"{p}_rp_what", "card"):
                html('<div class="card-h"><div><h3>What to report on</h3><div class="sub">The records come '
                     "from the database and follow the filters below.</div></div></div>")
                o, _ = self._options(s)
            with box(f"{p}_rp_how", "card"):
                html('<div class="card-h"><div><h3>Page layout</h3><div class="sub">Title, header and '
                     "orientation of the printed report.</div></div></div>")
                lay = self._layout(o["type"])
        o["title"] = lay["title"]
        with box(f"{p}_rp_go", "rowend", "mt"):
            if ss.get(self.k("show")):
                btn("Hide preview", f"{p}_rp_hide", "ghost", on_click=self._hide)
            btn("Generate report", f"{p}_rp_gen", "primary", icon=":material/description:",
                on_click=self._generate)
        if not ss.get(self.k("show")):
            html(f'<div class="card mt"><div class="empty">{ic("file")}<div>Choose the report and its layout, '
                 "then press <b>Generate report</b> to see the preview, print it or save it as a PDF.</div></div></div>")
            return
        printed_at = ss.get(self.k("at")) or D.now()
        rep = build_report(s, o, self.me(), printed_at)
        page_html = to_html(rep, lay)
        stamp = f"{printed_at:%Y%m%d-%H%M}"
        slug = "".join(ch if ch.isalnum() else "-" for ch in rep["title"].lower()).strip("-")[:50] or "report"
        with box(f"{p}_rp_out", "card", "mt"):
            with box(f"{p}_rp_out_h", "cardh"):
                n = sum(len(sec.get("rows") or []) for sec in rep["sections"])
                html(f'<div><h3>Preview</h3><div class="sub">{h(rep["title"])} · {n} record row(s) · '
                     f'{h(lay["paper"])} {h(lay["orientation"])} · generated {D.sent_date_time(printed_at)}</div></div>')
                with box(f"{p}_rp_dl", "row"):
                    if pdf_available():
                        try:
                            pdf = to_pdf(rep, lay)
                        except Exception as error:  # never break the page because of the PDF
                            pdf = None
                            html(f'<span class="small" style="color:#b42323">PDF export failed: {h(error)}</span>')
                        if pdf:
                            st.download_button("Download PDF", data=pdf, file_name=f"{slug}-{stamp}.pdf",
                                               mime="application/pdf", key=f"{p}_rp_pdf__primarysm__")
                    else:
                        html('<span class="small muted">PDF export needs ReportLab '
                             '(<code>pip install reportlab</code>). Use Print → Save as PDF meanwhile.</span>')
                    st.download_button("Download HTML", data=page_html.encode("utf-8"),
                                       file_name=f"{slug}-{stamp}.html", mime="text/html",
                                       key=f"{p}_rp_html__ghostsm__")
            html('<div class="adm-help" style="margin-bottom:8px">Use the <b>Print</b> button at the top of the '
                 "preview to print it (or choose “Save as PDF” in the print window).</div>")
            components.html(page_html, height=900, scrolling=True)
