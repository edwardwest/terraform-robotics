"""Master plan sheet: an illustrated, print-ready plan of the master plan features, drawn as SVG.

The same SVG is the in-app preview and, converted by cairosvg, the PDF. Layout works in points (1/72 in) on an
11 × 17 or 24 × 36 in landscape sheet; the site is drawn north-up in its UTM zone at a standard engineering scale
(1 in = N ft). Pure: inputs in, SVG text out; no database or network (the base image is passed in).

Look: textured fills by category (crop rows, stipple, paving, hatching), tree symbols placed by each planting's
spacing, a faded aerial photo or terrain shading underneath, labels in callout columns with leader lines, a legend,
a plant schedule and a title block. Category colors come from the feature library; the interface stays monochrome.
"""

from __future__ import annotations

import base64
import math
import zlib
from dataclasses import dataclass, field
from datetime import date
from xml.sax.saxutils import escape

import numpy as np
import shapely
from shapely.geometry import LineString, Point, Polygon

SIZES = {"11x17": (1224.0, 792.0), "24x36": (2592.0, 1728.0)}
NICE_FT_PER_IN = [5, 10, 15, 20, 30, 40, 50, 60, 80, 100, 120, 150, 200, 250, 300, 400, 500, 600, 800, 1000, 1200,
                  1500, 2000, 2500, 3000, 4000, 5000, 6000, 8000, 10000]
FT = 0.3048
PAPER = "#f7f5ef"
INK = "#2c2c2a"
INK_2 = "#5f5e5a"
FONT = "Helvetica Neue, Helvetica, Liberation Sans, Arial, sans-serif"
MAX_TREES_PER_FEATURE = 900
MAX_TREES = 6000
MAX_LEADERS = 6

# Drawing order: ground covers first, then planted areas, water, built areas; lines; trees; buildings; points.
AREA_ORDER = ["habitat", "animals", "annuals", "fire", "trees", "energy", "access", "water", "structures"]


# ---- Inputs ----------------------------------------------------------------------------------------


@dataclass
class SheetFeature:
    """A master plan feature, projected to the sheet's UTM CRS (metres)."""
    id: str
    type: str
    type_label: str
    category: str
    label: str | None
    status: str
    build_phase: int
    geom: Point | LineString | Polygon
    props: dict = field(default_factory=dict)
    plant_count: int | None = None


@dataclass
class SheetInput:
    project_name: str
    address: str | None
    boundary: Polygon | None            # UTM
    features: list[SheetFeature]        # UTM, already filtered by the settings
    categories: list[dict]              # library categories (id, label, color)
    settings: dict
    contours: list[LineString] = field(default_factory=list)  # UTM
    base_png: bytes | None = None       # RGB image covering `base_bounds`
    base_bounds: tuple[float, float, float, float] | None = None
    base_credit: str | None = None
    today: date = field(default_factory=date.today)


# ---- Styles ----------------------------------------------------------------------------------------

# Tree symbol palettes: (canopy, highlight).
TREES = {
    "orchard": ("#6f9a4a", "#a3c46e"),
    "forest": ("#3f5c40", "#62805a"),
    "hedge": ("#3d5e3a", "#5f804e"),
    "riparian": ("#4f7f56", "#79a37c"),
    "shade": ("#55784f", "#86a86c"),
    "berry": ("#7a9a4e", "#b0c87a"),
}


@dataclass
class Style:
    fill: str = "none"
    stroke: str = "none"
    width: float = 0.0
    dash: str | None = None
    opacity: float = 1.0
    trees: str | None = None        # tree palette for symbols placed in/along the feature
    spacing_m: float = 6.0          # default symbol spacing when the feature has none
    canopy_m: float | None = None   # default canopy radius
    symbol: str | None = None       # point symbol: circle, square, box, bar
    casing: str | None = None       # line drawn under the stroke, wider


def style_for(f: SheetFeature, color: str) -> Style:
    t, c = f.type, f.category
    if t == "existing-forest":
        return Style(fill="url(#p-forest-floor)", trees="forest", spacing_m=9, canopy_m=4.6)
    if t == "riparian":
        return Style(fill="#c4d3b4", trees="riparian", spacing_m=6, canopy_m=3)
    if t == "meadow":
        return Style(fill="url(#p-meadow)")
    if t == "hedgerow":
        return Style(stroke="#7d9862", width=3, trees="hedge", spacing_m=2.5, canopy_m=1.4)
    if t in ("food-forest", "orchard"):
        return Style(fill="#c3cd9f", trees="orchard", spacing_m=5, canopy_m=2.4)
    if t == "berries":
        return Style(fill="#ccd3a8", trees="berry", spacing_m=2, canopy_m=0.9)
    if t == "windbreak":
        return Style(stroke="#6c8a58", width=2, trees="hedge", spacing_m=3.5, canopy_m=2.2)
    if t == "shade-tree":
        return Style(trees="shade", canopy_m=4)
    if c == "water":
        if f.geom.geom_type == "Polygon":
            return Style(fill="#a9c8e6", stroke="#4a7fb0", width=1.6)
        if f.geom.geom_type == "LineString":
            return Style(stroke="#4a7fb0", width=2.2 if t == "creek" else 1.6, dash=None if t == "creek" else "5 2.5")
        return Style(fill="#ffffff", stroke="#4a7fb0", width=1.4, symbol="circle")
    if c == "annuals":
        return Style(fill="url(#p-rows)", stroke="#8a6d2c", width=0.8)
    if c == "animals":
        if t == "fence":
            return Style(stroke="#5c4a2a", width=1.0, dash="1 3")
        if t == "gate":
            return Style(fill="#b23a2a", symbol="bar")
        if f.geom.geom_type == "Point":
            return Style(fill="#f3efe4", stroke="#5c4a2a", width=0.8, symbol="box")
        return Style(fill="url(#p-pasture)", stroke="#5c4a2a", width=0.8, dash="1 3")
    if c == "structures":
        if t == "high-tunnel":
            return Style(fill="#d5dde0", stroke="#6f7f86", width=1.0)
        if t == "gathering":
            return Style(fill="url(#p-pave)", stroke="#8b847a", width=0.8)
        return Style(fill="#8c4a4a", stroke="#5a2c2c", width=1.0)
    if c == "access":
        if t == "road":
            return Style(stroke="#e4e0d6", width=9, casing="#9d978a")
        if t == "path":
            return Style(stroke="#d2b47a", width=2.6, casing="#9a7f4d")
        if t == "parking":
            return Style(fill="#dcd8ce", stroke="#9d978a", width=0.8)
        return Style(fill="#ffffff", stroke=INK, width=1.0, symbol="square")
    if c == "energy":
        if t == "solar":
            return Style(fill="url(#p-solar)", stroke="#11202f", width=0.8)
        if t in ("biomass", "compost-area"):
            return Style(fill="url(#p-biomass)", stroke="#6b5532", width=0.6)
        return Style(fill="#8b6b3e", stroke="#5a4325", width=0.8, symbol="circle" if t == "compost" else "square")
    if c == "fire":
        if f.geom.geom_type == "Polygon":
            return Style(fill="url(#p-fire)", stroke="#c0552a", width=1.0, dash="6 3")
        if f.geom.geom_type == "LineString":
            return Style(stroke="#8b5a2b", width=3)
        return Style(fill="#c0392b", stroke="#ffffff", width=1.0, symbol="circle")
    if f.geom.geom_type == "Polygon":
        return Style(fill=color, stroke=INK_2, width=0.8, opacity=0.6)
    if f.geom.geom_type == "LineString":
        return Style(stroke=color, width=2)
    return Style(fill=color, stroke="#ffffff", width=1, symbol="circle")


def _defs(k: float) -> str:
    def pat(pid: str, size: float, body: str, rotate: float = 0) -> str:
        rot = f' patternTransform="rotate({rotate})"' if rotate else ""
        return (f'<pattern id="{pid}" width="{size:.2f}" height="{size:.2f}" patternUnits="userSpaceOnUse"{rot}>'
                f"{body}</pattern>")

    s = 3.2 * k
    pats = [
        pat("p-rows", s, f'<rect width="{s}" height="{s}" fill="#e3cf94"/><rect width="{s * 0.38:.2f}" height="{s}" fill="#9b7f3a"/>', 78),
        pat("p-pasture", 7 * k, f'<rect width="{7 * k}" height="{7 * k}" fill="#d3c79a"/>'
            f'<circle cx="{1.6 * k}" cy="{1.6 * k}" r="{0.55 * k}" fill="#8a7a4a"/>'
            f'<circle cx="{5.1 * k}" cy="{4.9 * k}" r="{0.55 * k}" fill="#8a7a4a"/>'),
        pat("p-meadow", 6 * k, f'<rect width="{6 * k}" height="{6 * k}" fill="#cfd4a2"/>'
            f'<circle cx="{1.4 * k}" cy="{1.5 * k}" r="{0.5 * k}" fill="#7f8a4a"/>'
            f'<circle cx="{4.4 * k}" cy="{4.2 * k}" r="{0.55 * k}" fill="#c98fb0"/>'),
        pat("p-forest-floor", 8 * k, f'<rect width="{8 * k}" height="{8 * k}" fill="#7d8f6a"/>'
            f'<circle cx="{2 * k}" cy="{2 * k}" r="{0.5 * k}" fill="#5c6e4c"/>'),
        pat("p-pave", 6 * k, f'<rect width="{6 * k}" height="{6 * k}" fill="#e6e1d6"/>'
            f'<path d="M0 0H{6 * k}M0 0V{6 * k}" stroke="#b9b2a4" stroke-width="{0.5 * k:.2f}"/>'),
        pat("p-solar", 4 * k, f'<rect width="{4 * k}" height="{4 * k}" fill="#2c3e55"/>'
            f'<path d="M0 0H{4 * k}M0 0V{4 * k}" stroke="#8aa0b8" stroke-width="{0.4 * k:.2f}"/>'),
        pat("p-biomass", 5 * k, f'<rect width="{5 * k}" height="{5 * k}" fill="#b99a6a"/>'
            f'<circle cx="{1.5 * k}" cy="{1.5 * k}" r="{0.7 * k}" fill="#7a5a32"/>'
            f'<circle cx="{3.8 * k}" cy="{3.6 * k}" r="{0.5 * k}" fill="#7a5a32"/>'),
        pat("p-fire", 6 * k, f'<line x1="0" y1="0" x2="0" y2="{6 * k}" stroke="#e0703a" stroke-width="{1.2 * k:.2f}" stroke-opacity="0.55"/>', 45),
    ]
    trees = "".join(
        f'<g id="t-{name}"><circle cx="0.22" cy="0.22" r="1" fill="#1f2a1c" fill-opacity="0.28"/>'
        f'<circle r="1" fill="{canopy}" stroke="#24321f" stroke-width="0.08"/>'
        f'<circle cx="-0.28" cy="-0.28" r="0.5" fill="{hi}" fill-opacity="0.75"/></g>'
        for name, (canopy, hi) in TREES.items())
    return f"<defs>{''.join(pats)}{trees}</defs>"


# ---- Geometry helpers ------------------------------------------------------------------------------


@dataclass
class Frame:
    """Maps UTM metres to sheet points."""
    x0: float
    y0: float
    x1: float
    y1: float
    cx_m: float
    cy_m: float
    m_per_pt: float
    ft_per_in: int

    def pt(self, x: float, y: float) -> tuple[float, float]:
        return ((self.x0 + self.x1) / 2 + (x - self.cx_m) / self.m_per_pt,
                (self.y0 + self.y1) / 2 - (y - self.cy_m) / self.m_per_pt)

    def path(self, coords, close: bool = False) -> str:
        pts = [self.pt(x, y) for x, y, *_ in coords]
        d = "M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in pts)
        return d + (" Z" if close else "")

    def bounds_m(self) -> tuple[float, float, float, float]:
        """The map frame's extent in metres (UTM)."""
        hw = (self.x1 - self.x0) / 2 * self.m_per_pt
        hh = (self.y1 - self.y0) / 2 * self.m_per_pt
        return self.cx_m - hw, self.cy_m - hh, self.cx_m + hw, self.cy_m + hh


def nice_scale(extent_w: float, extent_h: float, frame_w: float, frame_h: float) -> int:
    """Smallest standard 1 in = N ft scale at which the extent (metres) fits the frame (points)."""
    need = max(extent_w / frame_w, extent_h / frame_h) * 72 / FT  # ft per inch
    for n in NICE_FT_PER_IN:
        if n >= need:
            return n
    return int(math.ceil(need / 1000) * 1000)


def tree_points(f: SheetFeature, st: Style, budget: int) -> tuple[list[tuple[float, float]], float]:
    """Symbol positions (metres) and canopy radius (metres) for a planted feature."""
    g = f.geom
    p = f.props or {}
    plant = float(p.get("plant_spacing_m") or st.spacing_m)
    row = float(p.get("row_spacing_m") or plant)
    canopy = st.canopy_m or 2.0
    if p.get("height_m"):
        canopy = min(max(float(p["height_m"]) * 0.35, 0.6), 9.0)
    if g.geom_type == "Point":
        return [(g.x, g.y)], canopy
    cap = max(1, min(MAX_TREES_PER_FEATURE, budget))
    if g.geom_type == "LineString":
        rows = int(p.get("rows") or 1)
        n = max(1, int(g.length // plant) + 1)
        if n * rows > cap:
            plant *= n * rows / cap
            n = max(1, int(g.length // plant) + 1)
        pts = []
        for r in range(rows):
            off = (r - (rows - 1) / 2) * max(plant * 0.8, 1.0)
            line = g.offset_curve(off) if off else g
            if line.is_empty or line.geom_type != "LineString":
                line = g
            for i in range(n):
                q = line.interpolate(i / max(n - 1, 1), normalized=True)
                pts.append((q.x, q.y))
        return pts, min(canopy, plant * 0.6)
    # Polygon: a grid at the planting spacing (rows run east-west for now), jittered for natural areas.
    minx, miny, maxx, maxy = g.bounds
    est = g.area / (plant * row)
    if est > cap:
        f_ = math.sqrt(est / cap)
        plant, row = plant * f_, row * f_
    xs = np.arange(minx + plant / 2, maxx, plant)
    ys = np.arange(miny + row / 2, maxy, row)
    if not len(xs) or not len(ys):
        c = g.representative_point()
        return [(c.x, c.y)], canopy
    X, Y = np.meshgrid(xs, ys)
    if f.type in ("existing-forest", "riparian"):
        rng = np.random.default_rng(zlib.crc32(f.id.encode()))
        X = X + rng.uniform(-0.35, 0.35, X.shape) * plant
        Y = Y + rng.uniform(-0.35, 0.35, Y.shape) * row
    else:
        X[1::2] += plant / 2 if f.type == "food-forest" else 0  # offset rows read as a food forest
    inside = shapely.contains_xy(g.buffer(-min(plant, row) * 0.25), X, Y)
    pts = list(zip(X[inside].tolist(), Y[inside].tolist()))
    if not pts:
        c = g.representative_point()
        pts = [(c.x, c.y)]
    return pts, min(canopy, min(plant, row) * 0.62)


def _anchor(g) -> tuple[float, float]:
    if g.geom_type == "Point":
        return g.x, g.y
    if g.geom_type == "LineString":
        q = g.interpolate(0.5, normalized=True)
        return q.x, q.y
    q = g.representative_point()
    return q.x, q.y


def _wrap(text: str, width: int, max_lines: int = 2) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1][: max(1, width - 1)].rstrip() + "…"
    return lines or [""]


def _spread(ys: list[float], gaps: list[float], lo: float, hi: float) -> list[float]:
    """Push label positions apart (each needs gaps[i] below the previous), keeping them within [lo, hi]."""
    out = list(ys)
    for i in range(len(out)):
        out[i] = max(out[i], lo if i == 0 else out[i - 1] + gaps[i - 1])
    if out and out[-1] > hi:
        out[-1] = hi
        for i in range(len(out) - 2, -1, -1):
            out[i] = min(out[i], out[i + 1] - gaps[i])
    return out


# ---- Render ----------------------------------------------------------------------------------------


def frame_for(settings: dict, features: list[SheetFeature], boundary: Polygon | None) -> Frame:
    """Where the map sits on the sheet and at what scale: everything drawn fits at the next standard scale."""
    W, H = SIZES[settings.get("size", "11x17")]
    k = W / 1224
    m = 24 * k
    panel = 250 * k
    strip = 118 * k if settings.get("labels", "callouts") == "callouts" else 0
    fx0, fy0 = m + strip, m
    fx1, fy1 = W - m - panel - 14 * k - strip, H - m
    geoms = [f.geom for f in features] + ([boundary] if boundary is not None else [])
    if geoms:
        minx, miny, maxx, maxy = shapely.GeometryCollection(geoms).bounds
    else:
        minx = miny = 0.0
        maxx = maxy = 100.0
    pad = max(maxx - minx, maxy - miny, 20) * 0.06
    minx, miny, maxx, maxy = minx - pad, miny - pad, maxx + pad, maxy + pad
    ft_in = nice_scale(maxx - minx, maxy - miny, fx1 - fx0, fy1 - fy0)
    return Frame(fx0, fy0, fx1, fy1, (minx + maxx) / 2, (miny + maxy) / 2, ft_in * FT / 72, ft_in)


def render(inp: SheetInput) -> str:
    s = inp.settings
    W, H = SIZES[s.get("size", "11x17")]
    k = W / 1224
    m = 24 * k
    panel = 250 * k
    labels_mode = s.get("labels", "callouts")
    colors = {c["id"]: c["color"] for c in inp.categories}
    frame = frame_for(s, inp.features, inp.boundary)
    fx0, fy0, fx1, fy1 = frame.x0, frame.y0, frame.x1, frame.y1

    out: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{W:.0f}pt" height="{H:.0f}pt" '
        f'viewBox="0 0 {W:.0f} {H:.0f}" font-family="{FONT}">',
        _defs(k),
        f'<clipPath id="map"><rect x="{fx0:.1f}" y="{fy0:.1f}" width="{fx1 - fx0:.1f}" height="{fy1 - fy0:.1f}"/></clipPath>',
        f'<rect width="{W:.0f}" height="{H:.0f}" fill="{PAPER}"/>',
        '<g clip-path="url(#map)">',
    ]

    # Base: photo or shading, else plain sage.
    if inp.base_png and inp.base_bounds:
        bx0, by0, bx1, by1 = inp.base_bounds
        (ix0, iy0), (ix1, iy1) = frame.pt(bx0, by1), frame.pt(bx1, by0)
        b64 = base64.b64encode(inp.base_png).decode()
        out.append(f'<image x="{ix0:.1f}" y="{iy0:.1f}" width="{ix1 - ix0:.1f}" height="{iy1 - iy0:.1f}" '
                   f'preserveAspectRatio="none" xlink:href="data:image/png;base64,{b64}"/>')
    else:
        out.append(f'<rect x="{fx0:.1f}" y="{fy0:.1f}" width="{fx1 - fx0:.1f}" height="{fy1 - fy0:.1f}" fill="#a9b39c"/>')

    if s.get("contours", True) and inp.contours:
        d = " ".join(frame.path(c.coords) for c in inp.contours if c.length > 0)
        out.append(f'<path d="{d}" fill="none" stroke="#6f7a62" stroke-opacity="0.55" stroke-width="{0.5 * k:.2f}"/>')

    feats = sorted(inp.features, key=lambda f: (
        0 if f.geom.geom_type == "Polygon" and f.category != "structures" else
        1 if f.geom.geom_type == "LineString" else 3 if f.geom.geom_type == "Polygon" else 4,
        AREA_ORDER.index(f.category) if f.category in AREA_ORDER else 99))
    trees: list[tuple[float, float, float, str, float]] = []  # y, x, r(pt), palette, opacity (drawn sorted by y)
    tree_budget = MAX_TREES

    for f in feats:
        st = style_for(f, colors.get(f.category, "#888888"))
        op = st.opacity * (0.7 if f.status == "existing" else 1.0)
        g = f.geom
        if g.geom_type == "Polygon":
            out.append(f'<path d="{frame.path(g.exterior.coords, close=True)}" fill="{st.fill}" fill-opacity="{op:.2f}" '
                       f'stroke="{st.stroke}" stroke-width="{st.width * k:.2f}"'
                       + (f' stroke-dasharray="{_dash(st.dash, k)}"' if st.dash else "") + "/>")
        elif g.geom_type == "LineString":
            d = frame.path(g.coords)
            if st.casing:
                out.append(f'<path d="{d}" fill="none" stroke="{st.casing}" stroke-width="{(st.width + 1.6) * k:.2f}" '
                           f'stroke-linecap="round" stroke-linejoin="round" stroke-opacity="{op:.2f}"/>')
            if st.stroke != "none":
                out.append(f'<path d="{d}" fill="none" stroke="{st.stroke}" stroke-width="{st.width * k:.2f}" '
                           f'stroke-linecap="round" stroke-linejoin="round" stroke-opacity="{op:.2f}"'
                           + (f' stroke-dasharray="{_dash(st.dash, k)}"' if st.dash else "") + "/>")
        elif st.symbol:
            out.append(_symbol(st, *frame.pt(g.x, g.y), k, op))
        if st.trees and tree_budget > 0:
            pts, canopy = tree_points(f, st, tree_budget)
            tree_budget -= len(pts)
            r = min(max(canopy / frame.m_per_pt, 1.1 * k), 16 * k)
            for x, y in pts:
                px, py = frame.pt(x, y)
                trees.append((py, px, r, st.trees, op))

    for py, px, r, pal, op in sorted(trees):
        out.append(f'<use xlink:href="#t-{pal}" transform="translate({px:.1f} {py:.1f}) scale({r:.2f})"'
                   + (f' opacity="{op:.2f}"' if op < 1 else "") + "/>")

    if inp.boundary is not None:
        out.append(f'<path d="{frame.path(inp.boundary.exterior.coords, close=True)}" fill="none" stroke="{INK}" '
                   f'stroke-width="{1.2 * k:.2f}" stroke-dasharray="{9 * k:.1f} {3 * k:.1f} {2 * k:.1f} {3 * k:.1f}"/>')
    out.append("</g>")
    out.append(f'<rect x="{fx0:.1f}" y="{fy0:.1f}" width="{fx1 - fx0:.1f}" height="{fy1 - fy0:.1f}" fill="none" '
               f'stroke="{INK}" stroke-width="{0.8 * k:.2f}"/>')

    if labels_mode != "off":
        out.append(_labels(inp, frame, W, H, k, labels_mode))

    out.append(_panel(inp, frame, W, H, k, m, panel, colors))
    out.append("</svg>")
    return "".join(out)


def _dash(d: str, k: float) -> str:
    return " ".join(f"{float(v) * k:.1f}" for v in d.split())


def _symbol(st: Style, x: float, y: float, k: float, op: float) -> str:
    r = 3.4 * k
    common = f'fill="{st.fill}" stroke="{st.stroke}" stroke-width="{st.width * k:.2f}" opacity="{op:.2f}"'
    if st.symbol == "circle":
        return f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" {common}/>'
    if st.symbol == "bar":
        return f'<rect x="{x - 4 * k:.1f}" y="{y - 1.3 * k:.1f}" width="{8 * k:.1f}" height="{2.6 * k:.1f}" {common}/>'
    if st.symbol == "box":
        return (f'<rect x="{x - r:.1f}" y="{y - r * 0.8:.1f}" width="{2 * r:.1f}" height="{1.6 * r:.1f}" {common}/>'
                f'<path d="M{x - r:.1f} {y - r * 0.8:.1f} L{x:.1f} {y - r * 1.5:.1f} L{x + r:.1f} {y - r * 0.8:.1f}" '
                f'fill="none" stroke="{st.stroke}" stroke-width="{st.width * k:.2f}"/>')
    return f'<rect x="{x - r:.1f}" y="{y - r:.1f}" width="{2 * r:.1f}" height="{2 * r:.1f}" {common}/>'


def label_groups(features: list[SheetFeature], hidden: set[str]) -> dict[str, list[SheetFeature]]:
    """Features grouped by their label text (one callout with several leaders per group), minus hidden ones."""
    groups: dict[str, list[SheetFeature]] = {}
    for f in features:
        text = (f.label or f.type_label).strip().upper()
        if text and text not in hidden:
            groups.setdefault(text, []).append(f)
    return groups


def _labels(inp: SheetInput, frame: Frame, W: float, H: float, k: float, mode: str) -> str:
    s = inp.settings
    hidden = set(s.get("hidden_labels") or [])
    positions = s.get("label_positions") or {}
    size = 8.2 * k
    lh = size * 1.18
    out = []
    groups = label_groups(inp.features, hidden)
    mid = (frame.x0 + frame.x1) / 2
    sides: dict[str, list[dict]] = {"left": [], "right": []}
    placed: list[dict] = []
    for text, fs in groups.items():
        anchors = [frame.pt(*_anchor(f.geom)) for f in fs][:MAX_LEADERS]
        ax = sum(a[0] for a in anchors) / len(anchors)
        ay = sum(a[1] for a in anchors) / len(anchors)
        item = {"text": text, "lines": _wrap(text, 20), "anchors": anchors, "ax": ax, "ay": ay}
        if text in positions:
            fx, fy = positions[text]
            item.update(x=fx * W, y=fy * H, align="start", free=True)
            placed.append(item)
        elif mode == "callouts":
            sides["left" if ax < mid else "right"].append(item)
        else:
            item.update(x=ax, y=ay, align="middle", free=False)
            placed.append(item)
    for side, items in sides.items():
        items.sort(key=lambda i: i["ay"])
        ys = _spread([i["ay"] for i in items], [lh * len(i["lines"]) + 5 * k for i in items],
                     frame.y0 + 10 * k, frame.y1 - lh * 2)
        for i, y in zip(items, ys):
            i.update(y=y, free=False, align="end" if side == "left" else "start",
                     x=frame.x0 - 8 * k if side == "left" else frame.x1 + 8 * k)
            placed.append(i)

    for i in placed:
        n = len(i["lines"])
        text_w = max(len(line) for line in i["lines"]) * size * 0.62
        if mode == "on_features" and not i.get("free"):
            # Centered on the feature with a light halo; no leaders.
            y0 = i["y"] - (n - 1) * lh / 2
            tspans = "".join(f'<tspan x="{i["x"]:.1f}" y="{y0 + j * lh:.1f}">{escape(line)}</tspan>' for j, line in enumerate(i["lines"]))
            out.append(f'<g class="lbl" data-key="{escape(i["text"], {chr(34): "&quot;"})}" data-x="{i["x"]:.1f}" data-y="{y0:.1f}">'
                       f'<text text-anchor="middle" font-size="{size:.1f}" font-weight="700" letter-spacing="{0.4 * k:.2f}" '
                       f'fill="none" stroke="#ffffff" stroke-width="{2.6 * k:.1f}" stroke-linejoin="round">{tspans}</text>'
                       f'<text text-anchor="middle" font-size="{size:.1f}" font-weight="700" letter-spacing="{0.4 * k:.2f}" fill="{INK}">{tspans}</text></g>')
            continue
        x, y = i["x"], i["y"]
        # Leader start: the label edge facing the anchors.
        if i["align"] == "end":
            lx = x + 3 * k
        elif i["align"] == "start":
            lx = x - 3 * k if i["ax"] < x else x + text_w + 3 * k
        else:
            lx = x
        ly = y - size * 0.35
        for ax, ay in i["anchors"]:
            out.append(f'<path d="M{lx:.1f} {ly:.1f} L{ax:.1f} {ay:.1f}" stroke="{INK}" stroke-width="{0.55 * k:.2f}" fill="none"/>'
                       f'<circle cx="{ax:.1f}" cy="{ay:.1f}" r="{1.3 * k:.1f}" fill="{INK}"/>')
        tspans = "".join(f'<tspan x="{x:.1f}" y="{y + j * lh:.1f}">{escape(line)}</tspan>' for j, line in enumerate(i["lines"]))
        halo = ('fill="none" stroke="#ffffff" stroke-opacity="0.85" stroke-width="{:.1f}" stroke-linejoin="round"'
                .format(2.4 * k)) if i.get("free") else None
        body = (f'<text text-anchor="{i["align"]}" font-size="{size:.1f}" font-weight="700" letter-spacing="{0.4 * k:.2f}" {halo}>{tspans}</text>'
                if halo else "")
        body += f'<text text-anchor="{i["align"]}" font-size="{size:.1f}" font-weight="700" letter-spacing="{0.4 * k:.2f}" fill="{INK}">{tspans}</text>'
        out.append(f'<g class="lbl" data-key="{escape(i["text"], {chr(34): "&quot;"})}" data-x="{x:.1f}" data-y="{y:.1f}" '
                   f'data-align="{i["align"]}">{body}</g>')
    return "".join(out)


def _text(x: float, y: float, s: str, size: float, weight: int = 400, fill: str = INK, anchor: str = "start",
          spacing: float = 0.0, italic: bool = False) -> str:
    extra = f' letter-spacing="{spacing:.2f}"' if spacing else ""
    extra += ' font-style="italic"' if italic else ""
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size:.1f}" font-weight="{weight}" fill="{fill}" '
            f'text-anchor="{anchor}"{extra}>{escape(s)}</text>')


def _panel(inp: SheetInput, frame: Frame, W: float, H: float, k: float, m: float, pw: float, colors: dict) -> str:
    s = inp.settings
    x = W - m - pw
    out = [f'<line x1="{x - 7 * k:.1f}" y1="{m:.1f}" x2="{x - 7 * k:.1f}" y2="{H - m:.1f}" stroke="#d3d1c7" stroke-width="{0.8 * k:.2f}"/>']
    y = m + 12 * k
    eyebrow = 7.2 * k
    body = 8.4 * k

    # Legend: categories in use, each with the swatch its features draw with.
    used = []
    for c in inp.categories:
        fs = [f for f in inp.features if f.category == c["id"]]
        if fs:
            used.append((c, fs[0]))
    out.append(_text(x, y, "LEGEND", eyebrow, 700, INK_2, spacing=1.2 * k))
    y += 14 * k
    for c, sample in used:
        st = style_for(sample, colors.get(c["id"], "#888"))
        sw, sh = 22 * k, 12 * k
        if sample.geom.geom_type == "LineString" and st.stroke != "none":
            if st.casing:
                out.append(f'<line x1="{x:.1f}" y1="{y - sh / 2 + 1 * k:.1f}" x2="{x + sw:.1f}" y2="{y - sh / 2 + 1 * k:.1f}" stroke="{st.casing}" stroke-width="{min(st.width + 1.6, 8) * k:.2f}"/>')
            out.append(f'<line x1="{x:.1f}" y1="{y - sh / 2 + 1 * k:.1f}" x2="{x + sw:.1f}" y2="{y - sh / 2 + 1 * k:.1f}" stroke="{st.stroke}" stroke-width="{min(st.width, 6.4) * k:.2f}"'
                       + (f' stroke-dasharray="{_dash(st.dash, k)}"' if st.dash else "") + "/>")
        elif sample.geom.geom_type == "Point" and st.symbol:
            out.append(_symbol(st, x + sw / 2, y - sh / 2 + 1 * k, k, 1.0))
        else:
            fill = st.fill if st.fill != "none" else colors.get(c["id"], "#888")
            out.append(f'<rect x="{x:.1f}" y="{y - sh + 2 * k:.1f}" width="{sw:.1f}" height="{sh:.1f}" fill="{fill}" stroke="{INK_2}" stroke-width="{0.4 * k:.2f}"/>')
        if st.trees:
            out.append(f'<use xlink:href="#t-{st.trees}" transform="translate({x + sw / 2:.1f} {y - sh / 2 + 2 * k:.1f}) scale({4.2 * k:.2f})"/>')
        out.append(_text(x + sw + 8 * k, y, c["label"], body))
        y += 16 * k
    if any(f.status == "existing" for f in inp.features):
        out.append(_text(x, y, "Existing features are drawn lighter.", 7.4 * k, fill=INK_2))
        y += 13 * k
    if inp.boundary is not None:
        out.append(f'<line x1="{x:.1f}" y1="{y - 4 * k:.1f}" x2="{x + 22 * k:.1f}" y2="{y - 4 * k:.1f}" stroke="{INK}" stroke-width="{1.2 * k:.2f}" stroke-dasharray="{9 * k:.1f} {3 * k:.1f} {2 * k:.1f} {3 * k:.1f}"/>')
        out.append(_text(x + 30 * k, y, "Property line", body))
        y += 16 * k
    if s.get("contours", True) and inp.contours:
        out.append(f'<line x1="{x:.1f}" y1="{y - 4 * k:.1f}" x2="{x + 22 * k:.1f}" y2="{y - 4 * k:.1f}" stroke="#6f7a62" stroke-width="{0.6 * k:.2f}"/>')
        out.append(_text(x + 30 * k, y, "Contours", body))
        y += 16 * k

    # North arrow and scale bar.
    y += 8 * k
    nx = x + 10 * k
    out.append(f'<path d="M{nx:.1f} {y - 2 * k:.1f} L{nx + 7 * k:.1f} {y + 20 * k:.1f} L{nx:.1f} {y + 14 * k:.1f} L{nx - 7 * k:.1f} {y + 20 * k:.1f} Z" fill="{INK}"/>')
    out.append(_text(nx, y + 32 * k, "N", 9 * k, 700, anchor="middle"))
    bar_ft = _bar_length(frame.ft_per_in)
    bar_pt = bar_ft / frame.ft_per_in * 72
    bx = x + 34 * k
    seg = bar_pt / 4
    for i in range(4):
        out.append(f'<rect x="{bx + i * seg:.1f}" y="{y + 8 * k:.1f}" width="{seg:.1f}" height="{4 * k:.1f}" '
                   f'fill="{INK if i % 2 == 0 else "#ffffff"}" stroke="{INK}" stroke-width="{0.5 * k:.2f}"/>')
    out.append(_text(bx, y + 22 * k, "0", 7.4 * k, fill=INK_2))
    out.append(_text(bx + bar_pt, y + 22 * k, f"{bar_ft:,} ft", 7.4 * k, fill=INK_2, anchor="middle"))
    out.append(_text(bx, y + 33 * k, f"1 in = {frame.ft_per_in:,} ft", 7.4 * k, fill=INK_2))
    y += 50 * k

    # Title block, bottom-up.
    tb_h = 132 * k
    tb_y = H - m - tb_h
    notes = (s.get("notes") or "").strip()

    # Plant schedule between the legend and notes / title block.
    sched_bottom = tb_y - 12 * k
    note_lines = _wrap(notes, 46, max_lines=10) if notes else []
    if note_lines:
        sched_bottom -= 18 * k + len(note_lines) * 11 * k
    if s.get("schedule", True):
        y = _schedule(inp, x, y, pw, sched_bottom, k, out)
    if note_lines:
        ny = tb_y - 12 * k - len(note_lines) * 11 * k
        out.append(_text(x, ny - 8 * k, "NOTES", eyebrow, 700, INK_2, spacing=1.2 * k))
        for j, line in enumerate(note_lines):
            out.append(_text(x, ny + 6 * k + j * 11 * k, line, 8 * k))

    out.append(f'<rect x="{x:.1f}" y="{tb_y:.1f}" width="{pw:.1f}" height="{tb_h:.1f}" fill="none" stroke="{INK}" stroke-width="{0.8 * k:.2f}"/>')
    ty = tb_y + 24 * k
    out.append(_text(x + 10 * k, ty, s.get("title") or "Master plan", 17 * k, 700))
    ty += 17 * k
    for line in _wrap(inp.project_name, 34, 2):
        out.append(_text(x + 10 * k, ty, line, 9.5 * k, 700))
        ty += 12 * k
    addr = s.get("subtitle") if s.get("subtitle") is not None else inp.address
    for line in _wrap(addr or "", 42, 2):
        if line:
            out.append(_text(x + 10 * k, ty, line, 8 * k, fill=INK_2))
            ty += 11 * k
    ty = max(ty, tb_y + 82 * k)
    phases = int(s.get("phases") or 0)
    meta = [
        f"Prepared by {s['prepared_by']}" if s.get("prepared_by") else None,
        f"{inp.today:%B} {inp.today.day}, {inp.today.year} · {s.get('size', '11x17').replace('x', ' × ')} in",
        "Phases 1–3" if phases in (0, 3) else ("Phase 1" if phases == 1 else "Phases 1–2"),
    ]
    for line in [ln for ln in meta if ln]:
        out.append(_text(x + 10 * k, ty, line, 7.6 * k, fill=INK_2))
        ty += 10.5 * k
    out.append(_text(x + pw - 10 * k, tb_y + tb_h - 9 * k, "Concept plan. Not for construction.", 7 * k, fill="#993c1d", anchor="end"))
    credit = "Terraform Robotics" + (f" · {inp.base_credit}" if inp.base_credit else "")
    out.append(_text(x + 10 * k, tb_y + tb_h - 9 * k, credit, 6.6 * k, fill="#888780"))
    return "".join(out)


def _bar_length(ft_per_in: int) -> int:
    """A round scale-bar length near 1.6 in at this scale."""
    target = ft_per_in * 1.6
    for n in [5, 10, 20, 25, 40, 50, 100, 200, 250, 400, 500, 1000, 2000, 2500, 5000, 10000, 20000]:
        if n >= target * 0.75:
            return n
    return int(target)


def schedule_rows(features: list[SheetFeature]) -> list[dict]:
    """Planted features with species, spacing and plant counts (for the sheet's plant schedule)."""
    rows = []
    for f in features:
        species = (f.props or {}).get("species") or []
        if not species and f.plant_count is None:
            continue
        names = [(sp.get("common_name") or sp.get("scientific_name") or sp["symbol"]) for sp in species]
        p = f.props or {}
        spacing = None
        if p.get("plant_spacing_m"):
            spacing = f"{p['plant_spacing_m'] / FT:.0f} ft" + (f" × {p['row_spacing_m'] / FT:.0f} ft" if p.get("row_spacing_m") and f.geom.geom_type == "Polygon" else "")
        rows.append({"label": f.label or f.type_label, "species": ", ".join(n[:1].upper() + n[1:] for n in names) or "Species to choose",
                     "spacing": spacing, "count": f.plant_count})
    return rows


def _schedule(inp: SheetInput, x: float, y: float, pw: float, bottom: float, k: float, out: list[str]) -> float:
    rows = schedule_rows(inp.features)
    if not rows or y + 40 * k > bottom:
        return y
    out.append(_text(x, y, "PLANT SCHEDULE", 7.2 * k, 700, INK_2, spacing=1.2 * k))
    y += 14 * k
    out.append(_text(x + pw, y - 14 * k, "PLANTS", 7.2 * k, 700, INK_2, anchor="end", spacing=1.2 * k))
    shown = 0
    for r in rows:
        lines = _wrap(r["species"], 44, 2)
        need = 11 * k + len(lines) * 10 * k + (10 * k if r["spacing"] else 0) + 5 * k
        if y + need > bottom - 12 * k:
            break
        out.append(_text(x, y, r["label"], 8.4 * k, 700))
        out.append(_text(x + pw, y, f"{r['count']:,}" if r["count"] else "–", 8.4 * k, 700, anchor="end"))
        y += 11 * k
        for line in lines:
            out.append(_text(x, y, line, 7.8 * k, fill=INK_2))
            y += 10 * k
        if r["spacing"]:
            out.append(_text(x, y, f"Spacing {r['spacing']}", 7.4 * k, fill="#888780"))
            y += 10 * k
        out.append(f'<line x1="{x:.1f}" y1="{y - 4 * k:.1f}" x2="{x + pw:.1f}" y2="{y - 4 * k:.1f}" stroke="#e1ded4" stroke-width="{0.5 * k:.2f}"/>')
        y += 5 * k
        shown += 1
    if shown < len(rows):
        out.append(_text(x, y + 2 * k, f"{len(rows) - shown} more in the GeoJSON or KML export.", 7.4 * k, fill=INK_2))
        y += 14 * k
    return y + 6 * k
