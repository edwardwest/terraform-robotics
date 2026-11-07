"""Stage 2 outputs: the cost estimate (W6) and exports for people, GIS, CAD and machines (W7).

Quantities always come from the design geometry; unit costs come from the editable cost library.
"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import date
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response, StreamingResponse
from shapely.geometry import LineString, Point, Polygon, mapping
from shapely.ops import unary_union

from tr_geo import project_geometry

from . import schemas
from .auth import CurrentUser
from .common import _project_or_404, srid_of, terrain_or_404
from .db import execute, fetch_all, fetch_one
from .design_api import design_lines

router = APIRouter()

M_TO_FT = 3.28084
M2_PER_ACRE = 4046.8564224
M3_TO_YD3 = 1.30795062
TRACTOR_ACRES_PER_DAY = 15.0  # planning assumption for hillside keyline ripping
EXCAVATOR_YD3_PER_DAY = 150.0  # planning assumption for swale cut and berm placement
WGS84_PRJ = ('GEOGCS["GCS_WGS_1984",DATUM["D_WGS_1984",SPHEROID["WGS_1984",6378137.0,298.257223563]],'
             'PRIMEM["Greenwich",0.0],UNIT["Degree",0.0174532925199433]]')


# ---- Cost library ------------------------------------------------------------------------------


def cost_items_for(user: dict) -> dict[str, dict]:
    rows = fetch_all(
        """SELECT DISTINCT ON (item) item, label, unit, rate_low::float AS rate_low, rate_high::float AS rate_high, note,
                  owner_id IS NOT NULL AS custom
           FROM cost_items WHERE region = 'starter' AND (owner_id IS NULL OR owner_id = :uid)
           ORDER BY item, owner_id NULLS LAST""",
        uid=str(user["id"]),
    )
    return {r["item"]: r for r in rows}


@router.get("/api/cost-items", response_model=list[schemas.CostItem])
def list_cost_items(user: CurrentUser):
    return list(cost_items_for(user).values())


@router.put("/api/cost-items/{item}", response_model=schemas.CostItem)
def update_cost_item(item: str, body: schemas.CostItemUpdate, user: CurrentUser):
    base = fetch_one("SELECT label, unit, note FROM cost_items WHERE owner_id IS NULL AND region = 'starter' AND item = :item", item=item)
    if not base:
        raise HTTPException(404, "Unknown cost item")
    execute("DELETE FROM cost_items WHERE owner_id = :uid AND region = 'starter' AND item = :item", uid=str(user["id"]), item=item)
    execute(
        """INSERT INTO cost_items (owner_id, region, item, label, unit, rate_low, rate_high, note)
           VALUES (:uid, 'starter', :item, :label, :unit, :lo, :hi, :note)""",
        uid=str(user["id"]), item=item, label=base["label"], unit=base["unit"], lo=body.rate_low, hi=body.rate_high,
        note=base["note"],
    )
    return cost_items_for(user)[item]


@router.delete("/api/cost-items/{item}", status_code=204)
def reset_cost_item(item: str, user: CurrentUser):
    execute("DELETE FROM cost_items WHERE owner_id = :uid AND region = 'starter' AND item = :item", uid=str(user["id"]), item=item)


# ---- Quantities and estimate -------------------------------------------------------------------


def _project_crs(project_id: UUID) -> str:
    return terrain_or_404(project_id)["dem_crs"]


def quantities(project_id: UUID, project: dict) -> tuple[dict, list[dict], bool]:
    rows = design_lines(project_id)
    crs = _project_crs(project_id) if rows else None
    rips = [r for r in rows if r["kind"] in ("keyline", "rip")]
    swales = [r for r in rows if r["kind"] == "swale"]
    treated_m2 = 0.0
    if rips:
        boundary = project_geometry(_boundary_shape(project), "EPSG:4326", crs)
        zones = []
        for r in rips:
            g = project_geometry(r["geom"], "EPSG:4326", crs)
            spacing = float((r["params"] or {}).get("spacing_m", 5.0))
            zones.append(g.buffer(spacing / 2, cap_style="flat"))
        treated_m2 = unary_union(zones).intersection(boundary).area
    rip_m = sum(float(r["length_m"]) for r in rips)
    swale_m3 = sum(float((r["properties"] or {}).get("cut_volume_m3", 0)) for r in swales)
    berm_m = sum(float(r["length_m"]) for r in swales if (r["properties"] or {}).get("berm", True))
    q = {
        "site_acres": round(float(project["area_m2"] or 0) / M2_PER_ACRE, 2),
        "treated_acres": round(treated_m2 / M2_PER_ACRE, 2),
        "rip_length_ft": round(rip_m * M_TO_FT, 1),
        "rip_lines": float(len([r for r in rips if r["kind"] == "rip"])),
        "keylines": float(len([r for r in rips if r["kind"] == "keyline"])),
        "swales": float(len(swales)),
        "swale_length_ft": round(sum(float(r["length_m"]) for r in swales) * M_TO_FT, 1),
        "swale_cut_yd3": round(swale_m3 * M3_TO_YD3, 1),
        "swale_storage_gal": round(sum(float((r["properties"] or {}).get("storage_gal", 0)) for r in swales)),
        "berm_length_ft": round(berm_m * M_TO_FT, 1),
        "tractor_days": round(treated_m2 / M2_PER_ACRE / TRACTOR_ACRES_PER_DAY, 1) if rips else 0.0,
        "excavator_days": round(swale_m3 * M3_TO_YD3 / EXCAVATOR_YD3_PER_DAY, 1) if swales else 0.0,
    }
    draft = any((r["properties"] or {}).get("draft") for r in rows)
    return q, rows, draft


def _boundary_shape(project: dict) -> Polygon:
    from shapely.geometry import shape

    return shape(project["boundary"])


def build_estimate(project_id: UUID, user: dict, contingency_pct: float) -> dict:
    project = _project_or_404(project_id, user)
    q, rows, draft = quantities(project_id, project)
    costs = cost_items_for(user)

    def line(item: str, qty: float, basis: str) -> dict | None:
        if qty <= 0 or item not in costs:
            return None
        c = costs[item]
        return {"item": item, "label": c["label"], "quantity": round(qty, 2), "unit": c["unit"],
                "rate_low": c["rate_low"], "rate_high": c["rate_high"],
                "total_low": round(qty * c["rate_low"], 2), "total_high": round(qty * c["rate_high"], 2), "basis": basis}

    machines = (1 if q["treated_acres"] > 0 else 0) + (1 if q["swales"] > 0 else 0)
    lines = [
        line("rip_acre", q["treated_acres"], f"{q['rip_length_ft']:,.0f} ft of rip line over {q['treated_acres']:,.1f} acres"),
        line("layout_acre", q["treated_acres"], "Staking the keylines and pattern in the field"),
        line("swale_yd3", q["swale_cut_yd3"], f"{int(q['swales'])} swale(s), {q['swale_length_ft']:,.0f} ft long"),
        line("berm_ft", q["berm_length_ft"], "Berm on the downhill side of each swale"),
        line("mobilization", machines, "Tractor for ripping, excavator for swales"),
    ]
    lines = [ln for ln in lines if ln]
    build_low = sum(ln["total_low"] for ln in lines)
    build_high = sum(ln["total_high"] for ln in lines)
    design = costs.get("design_acre")
    fee_low = round(q["site_acres"] * design["rate_low"], 2) if design and lines else 0.0
    fee_high = round(q["site_acres"] * design["rate_high"], 2) if design and lines else 0.0
    cont_low = round(build_low * contingency_pct / 100, 2)
    cont_high = round(build_high * contingency_pct / 100, 2)
    return {
        "lines": lines,
        "build_low": round(build_low, 2), "build_high": round(build_high, 2),
        "design_fee_low": fee_low, "design_fee_high": fee_high,
        "contingency_pct": contingency_pct, "contingency_low": cont_low, "contingency_high": cont_high,
        "total_low": round(build_low + fee_low + cont_low, 2), "total_high": round(build_high + fee_high + cont_high, 2),
        "quantities": q,
        "draft": draft,
        "note": "Estimates: design geometry × an editable unit-cost library. Starter rates are placeholders; "
                "confirm with a local contractor before committing.",
    }


@router.get("/api/projects/{project_id}/estimate", response_model=schemas.Estimate)
def get_estimate(project_id: UUID, user: CurrentUser, contingency_pct: float = Query(15, ge=0, le=100)):
    return build_estimate(project_id, user, contingency_pct)


@router.get("/api/projects/{project_id}/estimate.xlsx")
def estimate_xlsx(project_id: UUID, user: CurrentUser, contingency_pct: float = Query(15, ge=0, le=100)):
    from openpyxl import Workbook
    from openpyxl.styles import Font

    project = _project_or_404(project_id, user)
    est = build_estimate(project_id, user, contingency_pct)
    wb = Workbook()
    ws = wb.active
    ws.title = "Estimate"
    bold = Font(bold=True)
    ws.append([f"{project['name']} — design and build estimate"])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append([project.get("address") or "", f"Prepared {date.today().isoformat()}"])
    if est["draft"]:
        ws.append(["DRAFT: design drawn on planning-grade terrain"])
    ws.append([])
    ws.append(["Item", "Quantity", "Unit", "Rate low", "Rate high", "Total low", "Total high", "Basis"])
    for c in ws[ws.max_row]:
        c.font = bold
    first = ws.max_row + 1
    for ln in est["lines"]:
        r = ws.max_row + 1
        ws.append([ln["label"], ln["quantity"], ln["unit"], ln["rate_low"], ln["rate_high"],
                   f"=B{r}*D{r}", f"=B{r}*E{r}", ln["basis"]])
    last = ws.max_row
    ws.append(["Build subtotal", None, None, None, None, f"=SUM(F{first}:F{last})", f"=SUM(G{first}:G{last})"])
    sub = ws.max_row
    ws.append(["Design fee", est["quantities"]["site_acres"], "acre", None, None, est["design_fee_low"], est["design_fee_high"]])
    fee = ws.max_row
    ws.append([f"Contingency ({contingency_pct:g}% of build)", None, None, None, None,
               f"=F{sub}*{contingency_pct / 100}", f"=G{sub}*{contingency_pct / 100}"])
    cont = ws.max_row
    ws.append(["Total", None, None, None, None, f"=F{sub}+F{fee}+F{cont}", f"=G{sub}+G{fee}+G{cont}"])
    for c in ws[ws.max_row]:
        c.font = bold
    for row in ws.iter_rows(min_row=first, max_row=ws.max_row, min_col=4, max_col=7):
        for c in row:
            c.number_format = '"$"#,##0.00'
    ws.append([])
    ws.append([est["note"]])
    q = wb.create_sheet("Quantities")
    q.append(["Quantity", "Value"])
    for k, v in est["quantities"].items():
        q.append([k.replace("_", " "), v])
    for col, width in zip("ABCDEFGH", (34, 12, 12, 12, 12, 14, 14, 60)):
        ws.column_dimensions[col].width = width
    buf = io.BytesIO()
    wb.save(buf)
    return _download(buf.getvalue(), f"{_slug(project['name'])}-estimate.xlsx",
                     "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ---- Exports -----------------------------------------------------------------------------------


def _slug(name: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in name).strip("-") or "project"


def _download(content: bytes, filename: str, media: str) -> Response:
    return Response(content, media_type=media, headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def _export_rows(project_id: UUID, user: dict):
    project = _project_or_404(project_id, user)
    rows = design_lines(project_id)
    kps = fetch_all(
        """SELECT ST_AsBinary(geom) AS g, properties FROM terrain_features
           WHERE project_id = :id AND layer = 'keypoints' ORDER BY properties->>'id'""",
        id=str(project_id),
    )
    from shapely import wkb

    keypoints = [(wkb.loads(bytes(k["g"])), k["properties"]) for k in kps]
    return project, rows, keypoints


def _element_props(r: dict) -> dict:
    p = r["properties"] or {}
    out = {"kind": r["kind"], "label": r["label"], "length_m": round(float(r["length_m"]), 1),
           "draft": bool(p.get("draft"))}
    for k in ("pass", "elevation_m", "width_m", "depth_m", "cut_volume_m3", "storage_gal", "keypoint_id", "position", "offset_m"):
        if k in p:
            out[k] = p[k]
    return out


@router.get("/api/projects/{project_id}/export/geojson")
def export_geojson(project_id: UUID, user: CurrentUser):
    project, rows, keypoints = _export_rows(project_id, user)
    feats = [{"type": "Feature", "geometry": project["boundary"], "properties": {"kind": "boundary", "label": project["name"]}}]
    feats += [{"type": "Feature", "geometry": mapping(g), "properties": {"kind": "keypoint", **p}} for g, p in keypoints]
    feats += [{"type": "Feature", "geometry": mapping(r["geom"]), "properties": _element_props(r)} for r in rows]
    body = json.dumps({"type": "FeatureCollection", "features": feats})
    return _download(body.encode(), f"{_slug(project['name'])}-design.geojson", "application/geo+json")


def _shapefile_zip(name: str, rows: list[dict], boundary: Polygon | None, keypoints: list) -> bytes:
    import shapefile  # pyshp

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        def add(stem: str, writer_fn):
            shp, shx, dbf = io.BytesIO(), io.BytesIO(), io.BytesIO()
            w = shapefile.Writer(shp=shp, shx=shx, dbf=dbf)
            writer_fn(w)
            w.close()
            for ext, b in (("shp", shp), ("shx", shx), ("dbf", dbf)):
                z.writestr(f"{name}/{stem}.{ext}", b.getvalue())
            z.writestr(f"{name}/{stem}.prj", WGS84_PRJ)

        def lines(w):
            w.shapeType = shapefile.POLYLINE
            for f, t, size in (("KIND", "C", 10), ("LABEL", "C", 24), ("PASS", "N", 6), ("LENGTH_M", "F", 12), ("ELEV_M", "F", 10), ("DIR", "C", 8)):
                w.field(f, t, size, 2 if t == "F" else 0)
            for r in rows:
                p = r["properties"] or {}
                w.line([list(r["geom"].coords)])
                w.record(r["kind"], r["label"] or "", int(p.get("pass", 0) or 0), round(float(r["length_m"]), 2),
                         float(p.get("elevation_m", p.get("z_start_m", 0)) or 0), r.get("direction", ""))

        add("design_lines", lines)
        if boundary is not None:
            def poly(w):
                w.shapeType = shapefile.POLYGON
                w.field("NAME", "C", 60)
                w.poly([list(boundary.exterior.coords)])
                w.record(name[:60])
            add("boundary", poly)
        if keypoints:
            def pts(w):
                w.shapeType = shapefile.POINT
                w.field("ID", "C", 10)
                w.field("ELEV_M", "F", 10, 2)
                for g, p in keypoints:
                    w.point(g.x, g.y)
                    w.record(p.get("id", ""), float(p.get("elevation_m", 0) or 0))
            add("keypoints", pts)
    return buf.getvalue()


@router.get("/api/projects/{project_id}/export/shapefile")
def export_shapefile(project_id: UUID, user: CurrentUser):
    project, rows, keypoints = _export_rows(project_id, user)
    data = _shapefile_zip(_slug(project["name"]), rows, _boundary_shape(project), keypoints)
    return _download(data, f"{_slug(project['name'])}-shapefile.zip", "application/zip")


@router.get("/api/projects/{project_id}/export/kml")
def export_kml(project_id: UUID, user: CurrentUser):
    from xml.sax.saxutils import escape

    project, rows, keypoints = _export_rows(project_id, user)
    widths = {"keyline": 4, "rip": 1.5, "swale": 5}

    def coords(geom) -> str:
        return " ".join(f"{x:.7f},{y:.7f},0" for x, y in geom.coords)

    parts = [f"<Placemark><name>{escape(project['name'])}</name><styleUrl>#boundary</styleUrl><Polygon><outerBoundaryIs><LinearRing>"
             f"<coordinates>{coords(_boundary_shape(project).exterior)}</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>"]
    for g, p in keypoints:
        parts.append(f"<Placemark><name>{escape(str(p.get('id', '')))}</name><Point><coordinates>{g.x:.7f},{g.y:.7f},0</coordinates></Point></Placemark>")
    for r in rows:
        parts.append(f"<Placemark><name>{escape(r['label'] or r['kind'])}</name><styleUrl>#{r['kind']}</styleUrl>"
                     f"<LineString><tessellate>1</tessellate><coordinates>{coords(r['geom'])}</coordinates></LineString></Placemark>")
    styles = "".join(f'<Style id="{k}"><LineStyle><color>ffffffff</color><width>{w}</width></LineStyle></Style>' for k, w in widths.items())
    styles += '<Style id="boundary"><LineStyle><color>ffffffff</color><width>2</width></LineStyle><PolyStyle><fill>0</fill></PolyStyle></Style>'
    kml = (f'<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
           f"<name>{escape(project['name'])}</name>{styles}{''.join(parts)}</Document></kml>")
    return _download(kml.encode(), f"{_slug(project['name'])}-design.kml", "application/vnd.google-earth.kml+xml")


@router.get("/api/projects/{project_id}/export/dxf")
def export_dxf(project_id: UUID, user: CurrentUser):
    """DXF in the site's UTM coordinates (metres), one layer per element type, contours included."""
    import ezdxf
    from shapely import wkb

    project, rows, keypoints = _export_rows(project_id, user)
    t = terrain_or_404(project_id)
    crs = t["dem_crs"]
    to = lambda g: project_geometry(g, "EPSG:4326", crs)  # noqa: E731
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 6  # metres
    for name, color in (("BOUNDARY", 7), ("KEYLINE", 1), ("RIP", 8), ("SWALE", 5), ("BERM", 3),
                        ("CONTOUR", 9), ("CONTOUR_INDEX", 252), ("KEYPOINT", 2)):
        doc.layers.add(name, color=color)
    msp = doc.modelspace()
    b = to(_boundary_shape(project))
    msp.add_lwpolyline(list(b.exterior.coords), close=True, dxfattribs={"layer": "BOUNDARY"})
    contours = fetch_all(
        """SELECT ST_AsBinary(ST_Transform(geom, :srid)) AS g, properties FROM terrain_features
           WHERE project_id = :id AND layer = 'contours'""",
        id=str(project_id), srid=srid_of(crs),
    )
    for c in contours:
        g = wkb.loads(bytes(c["g"])).simplify(0.3)  # 30 cm keeps the shape and cuts the file several-fold
        layer = "CONTOUR_INDEX" if (c["properties"] or {}).get("index") else "CONTOUR"
        z = float((c["properties"] or {}).get("elevation_m", 0))
        msp.add_lwpolyline(list(g.coords), dxfattribs={"layer": layer, "elevation": z})
    for r in rows:
        g = to(r["geom"])
        layer = {"keyline": "KEYLINE", "rip": "RIP", "swale": "SWALE"}[r["kind"]]
        msp.add_lwpolyline(list(g.coords), dxfattribs={"layer": layer})
        if r["kind"] == "swale" and (r["properties"] or {}).get("berm", True):
            berm = _berm_line(g, float((r["properties"] or {}).get("width_m", 1.8)), t)
            if berm is not None:
                msp.add_lwpolyline(list(berm.coords), dxfattribs={"layer": "BERM"})
    for g, p in keypoints:
        pt = to(g)
        msp.add_point((pt.x, pt.y), dxfattribs={"layer": "KEYPOINT"})
        msp.add_text(str(p.get("id", "")), height=3, dxfattribs={"layer": "KEYPOINT"}).set_placement((pt.x + 3, pt.y + 3))
    stream = io.StringIO()
    doc.write(stream)
    return _download(stream.getvalue().encode(), f"{_slug(project['name'])}-design-utm-m.dxf", "application/dxf")


def _berm_line(swale: LineString, width_m: float, terrain: dict) -> LineString | None:
    """The berm runs along the downhill side of the swale."""
    from .common import dem_local_path, load_surface, terrain_version

    surface = load_surface(dem_local_path(terrain), terrain_version(terrain))
    off = width_m / 2 + 0.6
    cands = []
    for sign in (1, -1):
        o = swale.offset_curve(sign * off)
        if isinstance(o, LineString) and not o.is_empty:
            mid = o.interpolate(0.5, normalized=True)
            cands.append((surface.z1(mid.x, mid.y), o))
    return min(cands, key=lambda c: c[0])[1] if cands else None


@router.get("/api/projects/{project_id}/export/guidance")
def export_guidance(project_id: UUID, user: CurrentUser, format: str = Query("geojson", pattern="^(geojson|shapefile)$")):
    """Rip lines for GPS guidance, ordered top to bottom with alternating direction to cut turns."""
    project, rows, _ = _export_rows(project_id, user)
    lines = [r for r in rows if r["kind"] in ("keyline", "rip")]
    if not lines:
        raise HTTPException(409, "No keylines or rip lines to export yet")
    lines.sort(key=lambda r: -max(float((r["properties"] or {}).get("z_start_m", 0) or 0),
                                  float((r["properties"] or {}).get("z_end_m", 0) or 0)))
    prev_end = None
    for i, r in enumerate(lines, start=1):
        g: LineString = r["geom"]
        if prev_end is not None and Point(g.coords[-1]).distance(prev_end) < Point(g.coords[0]).distance(prev_end):
            g = LineString(list(g.coords)[::-1])
            r["direction"] = "reversed"
        else:
            r["direction"] = "forward"
        r["geom"] = g
        r["properties"] = {**(r["properties"] or {}), "pass": i}
        prev_end = Point(g.coords[-1])
    stem = f"{_slug(project['name'])}-guidance"
    if format == "shapefile":
        return _download(_shapefile_zip(stem, lines, None, []), f"{stem}.zip", "application/zip")
    feats = [{"type": "Feature", "geometry": mapping(r["geom"]),
              "properties": {**_element_props(r), "pass": r["properties"]["pass"], "direction": r["direction"]}} for r in lines]
    return _download(json.dumps({"type": "FeatureCollection", "features": feats}).encode(), f"{stem}.geojson", "application/geo+json")


@router.get("/api/projects/{project_id}/export/plan.pdf")
def export_pdf(project_id: UUID, user: CurrentUser, contingency_pct: float = Query(15, ge=0, le=100)):
    from .plan_pdf import render_plan

    project, rows, keypoints = _export_rows(project_id, user)
    t = terrain_or_404(project_id)
    est = build_estimate(project_id, user, contingency_pct)
    pdf = render_plan(project, rows, keypoints, t, est)
    return _download(pdf, f"{_slug(project['name'])}-plan-set.pdf", "application/pdf")


__all__ = ["router", "StreamingResponse"]
