"""PDF plan set (11 × 17 in, landscape): keyline layout sheet, swale and rip-line schedule, estimate summary."""

from __future__ import annotations

import io
import math
from datetime import date

from reportlab.lib.colors import Color, black, white
from reportlab.lib.pagesizes import landscape
from reportlab.pdfgen import canvas
from shapely import wkb
from shapely.geometry import shape

from tr_geo import project_geometry

from .db import fetch_all

PAGE = landscape((11 * 72, 17 * 72))
M_TO_FT = 3.28084
INK = black
GREY = Color(0.55, 0.55, 0.55)
LIGHT = Color(0.82, 0.82, 0.82)
MARGIN = 36


def _fmt_ft(m: float) -> str:
    return f"{m * M_TO_FT:,.0f}"


def render_plan(project: dict, rows: list[dict], keypoints: list, terrain: dict, estimate: dict) -> bytes:
    crs = terrain["dem_crs"]
    to = lambda g: project_geometry(g, "EPSG:4326", crs)  # noqa: E731
    boundary = to(shape(project["boundary"]))
    srid = int(crs.split(":")[1])
    layers = {}
    for name in ("contours", "valleys", "ridges"):
        rs = fetch_all(
            """SELECT ST_AsBinary(ST_Transform(geom, :srid)) AS g, properties FROM terrain_features
               WHERE project_id = :id AND layer = :layer""",
            id=str(project["id"]), layer=name, srid=srid,
        )
        layers[name] = [(wkb.loads(bytes(r["g"])), r["properties"] or {}) for r in rs]
    elements = [(r, to(r["geom"])) for r in rows]
    kps = [(to(g), p) for g, p in keypoints]
    draft = estimate.get("draft")

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=PAGE)
    c.setTitle(f"{project['name']} plan set")
    c.setAuthor("Terraform Robotics")
    _layout_sheet(c, project, boundary, layers, elements, kps, draft)
    c.showPage()
    _schedule_sheet(c, project, elements, estimate, draft)
    c.showPage()
    c.save()
    return buf.getvalue()


def _title_block(c: canvas.Canvas, project: dict, sheet: str, title: str, draft: bool) -> None:
    w, h = PAGE
    x0 = w - MARGIN - 230
    c.setStrokeColor(INK)
    c.setLineWidth(1)
    c.rect(x0, MARGIN, 230, h - 2 * MARGIN)
    y = h - MARGIN - 28
    c.setFont("Helvetica-Bold", 13)
    c.drawString(x0 + 14, y, "TERRAFORM ROBOTICS")
    y -= 30
    c.setFont("Helvetica-Bold", 16)
    for line in _wrap(project["name"], 24):
        c.drawString(x0 + 14, y, line)
        y -= 19
    c.setFont("Helvetica", 9)
    for line in _wrap(project.get("address") or "", 40):
        c.drawString(x0 + 14, y, line)
        y -= 12
    y -= 10
    c.setFont("Helvetica", 9)
    acres = (project.get("area_m2") or 0) / 4046.8564224
    for k, v in (("Area", f"{acres:,.1f} acres"), ("Prepared", date.today().isoformat()), ("Sheet", sheet)):
        c.setFillColor(GREY)
        c.drawString(x0 + 14, y, k.upper())
        c.setFillColor(INK)
        c.drawString(x0 + 90, y, v)
        y -= 14
    y -= 8
    c.setFont("Helvetica-Bold", 12)
    c.drawString(x0 + 14, y, title)
    if draft:
        y -= 26
        c.setFillColor(INK)
        c.rect(x0 + 14, y - 6, 202, 22, fill=1)
        c.setFillColor(white)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(x0 + 22, y + 1, "DRAFT: PLANNING-GRADE TERRAIN")
        c.setFillColor(INK)
        y -= 22
        c.setFont("Helvetica", 8)
        for line in _wrap("Lines may be off by a metre or more in the field. Confirm with a drone LiDAR or RTK survey before ripping.", 42):
            c.drawString(x0 + 14, y, line)
            y -= 10
    c.setFont("Helvetica", 7)
    c.setFillColor(GREY)
    for i, line in enumerate(_wrap("Lines are computed from the terrain model, never drawn by hand. Costs are estimates; confirm with a local contractor.", 46)):
        c.drawString(x0 + 14, MARGIN + 30 - i * 9, line)
    c.setFillColor(INK)


def _wrap(text: str, width: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width and cur:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return lines


def _layout_sheet(c, project, boundary, layers, elements, kps, draft) -> None:
    w, h = PAGE
    _title_block(c, project, "1 of 2", "Keyline layout", draft)
    fx0, fy0 = MARGIN, MARGIN
    fw, fh = w - 2 * MARGIN - 230 - 14, h - 2 * MARGIN
    c.setLineWidth(1)
    c.rect(fx0, fy0, fw, fh)
    minx, miny, maxx, maxy = boundary.bounds
    pad = 0.06 * max(maxx - minx, maxy - miny)
    minx, miny, maxx, maxy = minx - pad, miny - pad, maxx + pad, maxy + pad
    scale = min(fw / (maxx - minx), fh / (maxy - miny))
    ox = fx0 + (fw - (maxx - minx) * scale) / 2
    oy = fy0 + (fh - (maxy - miny) * scale) / 2
    P = lambda x, y: (ox + (x - minx) * scale, oy + (y - miny) * scale)  # noqa: E731

    def path(geom, width, color, dash=None):
        coords = list(geom.coords)
        if len(coords) < 2:
            return
        p = c.beginPath()
        p.moveTo(*P(*coords[0]))
        for xy in coords[1:]:
            p.lineTo(*P(*xy))
        c.setLineWidth(width)
        c.setStrokeColor(color)
        c.setDash(*(dash or ()))
        c.drawPath(p, stroke=1, fill=0)
        c.setDash()

    for g, props in layers["contours"]:
        if props.get("index"):
            path(g, 0.35, LIGHT)
    for g, _ in layers["valleys"]:
        path(g, 0.6, GREY, (4, 3))
    for g, _ in layers["ridges"]:
        path(g, 0.6, GREY, (1, 2))
    for r, g in elements:
        if r["kind"] == "rip":
            path(g, 0.45, Color(0.25, 0.25, 0.25))
    for r, g in elements:
        if r["kind"] == "keyline":
            path(g, 1.8, INK)
        elif r["kind"] == "swale":
            path(g, 2.6, INK)
    path(boundary.exterior, 1.6, INK)
    c.setFont("Helvetica-Bold", 7)
    for r, g in elements:
        if r["kind"] in ("keyline", "swale"):
            mid = g.interpolate(0.5, normalized=True)
            x, y = P(mid.x, mid.y)
            c.setFillColor(white)
            c.rect(x + 3, y + 2, 7 + 4.2 * len(r["label"] or ""), 10, fill=1, stroke=0)
            c.setFillColor(INK)
            c.drawString(x + 5, y + 4.5, r["label"] or "")
    for g, p in kps:
        x, y = P(g.x, g.y)
        c.setFillColor(white)
        c.setStrokeColor(INK)
        c.setLineWidth(1)
        d = 4.5
        pth = c.beginPath()
        pth.moveTo(x, y + d); pth.lineTo(x + d, y); pth.lineTo(x, y - d); pth.lineTo(x - d, y); pth.close()
        c.drawPath(pth, stroke=1, fill=1)
        c.setFillColor(INK)
        c.setFont("Helvetica-Bold", 7)
        c.drawString(x + 7, y - 2.5, str(p.get("id", "")))

    # Scale bar (feet) and north arrow.
    target_ft = (fw * 0.22) / scale * M_TO_FT
    nice = 10 ** math.floor(math.log10(target_ft))
    for m in (5, 2, 1):
        if nice * m <= target_ft:
            nice *= m
            break
    bar = nice / M_TO_FT * scale
    bx, by = fx0 + 18, fy0 + 18
    c.setFillColor(INK)
    c.rect(bx, by, bar / 2, 4, fill=1, stroke=1)
    c.setFillColor(white)
    c.rect(bx + bar / 2, by, bar / 2, 4, fill=1, stroke=1)
    c.setFillColor(INK)
    c.setFont("Helvetica", 7)
    c.drawString(bx, by + 8, "0")
    c.drawRightString(bx + bar, by + 8, f"{nice:,.0f} ft")
    nx, ny = fx0 + fw - 30, fy0 + fh - 50
    pth = c.beginPath()
    pth.moveTo(nx, ny + 26); pth.lineTo(nx + 7, ny); pth.lineTo(nx, ny + 6); pth.lineTo(nx - 7, ny); pth.close()
    c.drawPath(pth, stroke=1, fill=1)
    c.setFont("Helvetica-Bold", 9)
    c.drawCentredString(nx, ny - 12, "N")

    # Legend.
    lx, ly = fx0 + 18, fy0 + fh - 20
    c.setFillColor(white)
    c.rect(lx - 8, ly - 92, 150, 102, fill=1, stroke=1)
    c.setFillColor(INK)
    items = [("Property line", 1.6, INK, None), ("Keyline", 1.8, INK, None), ("Rip line", 0.45, Color(0.25, 0.25, 0.25), None),
             ("Swale on contour", 2.6, INK, None), ("Valley", 0.6, GREY, (4, 3)), ("Ridge", 0.6, GREY, (1, 2)),
             ("Index contour", 0.35, LIGHT, None)]
    c.setFont("Helvetica", 7.5)
    for i, (label, width, color, dash) in enumerate(items):
        y = ly - i * 12
        c.setStrokeColor(color)
        c.setLineWidth(width)
        c.setDash(*(dash or ()))
        c.line(lx, y + 2.5, lx + 26, y + 2.5)
        c.setDash()
        c.drawString(lx + 34, y, label)


def _schedule_sheet(c, project, elements, estimate, draft) -> None:
    w, h = PAGE
    _title_block(c, project, "2 of 2", "Schedules and estimate", draft)
    x, y = MARGIN, h - MARGIN - 10
    right = w - MARGIN - 230 - 24

    def heading(text):
        nonlocal y
        c.setFont("Helvetica-Bold", 12)
        c.drawString(x, y, text)
        y -= 6
        c.setLineWidth(0.8)
        c.line(x, y, right, y)
        y -= 14

    def table(cols, rows_, widths):
        nonlocal y
        c.setFont("Helvetica-Bold", 8)
        cx = x
        for col, wd in zip(cols, widths):
            c.drawString(cx, y, col)
            cx += wd
        y -= 12
        c.setFont("Helvetica", 8)
        for r in rows_:
            cx = x
            height = 1
            for val, wd in zip(r, widths):
                wrapped = _wrap(str(val), max(int(wd / 4.3), 4)) or [""]
                for i, line in enumerate(wrapped[:4]):
                    c.drawString(cx, y - i * 10, line)
                height = max(height, min(len(wrapped), 4))
                cx += wd
            y -= 11 + (height - 1) * 10
            if y < MARGIN + 30:
                break
        y -= 10

    q = estimate["quantities"]
    heading("Estimate summary")
    rows_ = [[ln["label"], f"{ln['quantity']:,.1f} {ln['unit']}", f"${ln['rate_low']:,.2f}–${ln['rate_high']:,.2f}",
              f"${ln['total_low']:,.0f}–${ln['total_high']:,.0f}"] for ln in estimate["lines"]]
    rows_.append(["Design fee", f"{q['site_acres']:,.1f} acre", "", f"${estimate['design_fee_low']:,.0f}–${estimate['design_fee_high']:,.0f}"])
    rows_.append([f"Contingency ({estimate['contingency_pct']:g}%)", "", "", f"${estimate['contingency_low']:,.0f}–${estimate['contingency_high']:,.0f}"])
    rows_.append(["TOTAL", "", "", f"${estimate['total_low']:,.0f}–${estimate['total_high']:,.0f}"])
    table(["Item", "Quantity", "Unit cost", "Total"], rows_, [220, 140, 150, 150])

    swales = [(r, g) for r, g in elements if r["kind"] == "swale"]
    if swales:
        heading("Swale schedule")
        table(["Swale", "Elevation (ft)", "Length (ft)", "Width × depth (ft)", "Cut (cu yd)", "Storage (gal)", "Notes"],
              [[r["label"], f"{(r['properties'] or {}).get('elevation_m', 0) * M_TO_FT:,.1f}", _fmt_ft(float(r["length_m"])),
                f"{(r['properties'] or {}).get('width_m', 0) * M_TO_FT:.1f} × {(r['properties'] or {}).get('depth_m', 0) * M_TO_FT:.1f}",
                f"{(r['properties'] or {}).get('cut_volume_m3', 0) * 1.30795:,.0f}", f"{(r['properties'] or {}).get('storage_gal', 0):,}",
                "; ".join((r["properties"] or {}).get("notes", []))] for r, g in swales],
              [50, 80, 70, 100, 70, 80, 300])

    keylines = [(r, g) for r, g in elements if r["kind"] == "keyline"]
    rips = [(r, g) for r, g in elements if r["kind"] == "rip"]
    if keylines or rips:
        heading("Keylines and rip pattern")
        table(["Line", "Length (ft)", "Grade", "Spacing (ft)", "Rip lines", "Pattern"],
              [[r["label"], _fmt_ft(float(r["length_m"])), f"1:{round(1 / float((r['params'] or {}).get('grade', 1 / 300)))}",
                f"{float((r['params'] or {}).get('spacing_m', 0)) * M_TO_FT:.0f}",
                str(sum(1 for rr, _ in rips if rr["group_id"] == r["group_id"])),
                f"{(r['params'] or {}).get('pattern', '')}, {(r['params'] or {}).get('extent', '')}"] for r, g in keylines],
              [120, 90, 70, 90, 80, 200])
        flagged = [(r, g) for r, g in rips if (r["properties"] or {}).get("notes")]
        c.setFont("Helvetica", 8)
        c.drawString(x, y, f"{len(rips)} rip lines, {q['rip_length_ft']:,.0f} ft in total, over {q['treated_acres']:,.1f} acres. "
                           f"{len(flagged)} have notes; see the app for each line.")
        y -= 20
