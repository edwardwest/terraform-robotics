"""Master plan feature library (rules/plan_features.yaml) and the arithmetic on placed features.

Pure: YAML in, dicts out; no database, no network. Measurements (area, length) are computed by PostGIS and passed in.
"""

from __future__ import annotations

from functools import lru_cache
from importlib import resources

import yaml

from . import interventions as iv

GEOMETRIES = {"point": "Point", "line": "LineString", "polygon": "Polygon"}
FIELDS = {"species", "building", "capacity"}
ROOFS = ("gable", "hip", "shed", "flat")
STATUSES = ("proposed", "existing")
BUILD_PHASES = (1, 2, 3)


@lru_cache(maxsize=1)
def library() -> dict:
    data = yaml.safe_load(resources.files("tr_kb").joinpath("rules/plan_features.yaml").read_text())
    cats = {c["id"] for c in data["categories"]}
    catalog = iv.by_id()
    seen = set()
    for t in data["types"]:
        if t["id"] in seen:
            raise ValueError(f"Duplicate plan feature type {t['id']}")
        seen.add(t["id"])
        if t["category"] not in cats:
            raise ValueError(f"{t['id']}: unknown category {t['category']}")
        if t["geometry"] not in GEOMETRIES:
            raise ValueError(f"{t['id']}: unknown geometry {t['geometry']}")
        t.setdefault("intervention", None)
        t.setdefault("status", "proposed")
        t.setdefault("fields", [])
        t.setdefault("defaults", {})
        if t["intervention"] and t["intervention"] not in catalog:
            raise ValueError(f"{t['id']}: unknown intervention {t['intervention']}")
        if not set(t["fields"]) <= FIELDS:
            raise ValueError(f"{t['id']}: unknown fields {set(t['fields']) - FIELDS}")
        if t["intervention"] and catalog[t["intervention"]].get("tool"):
            raise ValueError(f"{t['id']}: {t['intervention']} is laid out by a design tool, not drawn")
    return data


def types_by_id() -> dict[str, dict]:
    return {t["id"]: t for t in library()["types"]}


def categories_by_id() -> dict[str, dict]:
    return {c["id"]: c for c in library()["categories"]}


def type_for_intervention(intervention_id: str) -> dict | None:
    """The first feature type that places this intervention (the one the "To place" list draws with)."""
    return next((t for t in library()["types"] if t["intervention"] == intervention_id), None)


def plant_count(ftype: dict, props: dict, area_m2: float | None, length_m: float | None) -> int | None:
    """Plants implied by the spacing settings: area / (row × plant spacing) for areas, length / spacing × rows for lines,
    one for a single tree. None when the type has no species list or the spacing is not set."""
    if "species" not in ftype["fields"]:
        return None
    geom = ftype["geometry"]
    if geom == "point":
        return 1
    plant = props.get("plant_spacing_m")
    if not plant or plant <= 0:
        return None
    if geom == "line" and length_m:
        rows = int(props.get("rows") or 1)
        return max(1, int(length_m // plant) + 1) * rows
    row = props.get("row_spacing_m")
    if geom == "polygon" and area_m2 and row and row > 0:
        return max(1, int(area_m2 / (row * plant)))
    return None


def measured_quantity(intervention_id: str, features: list[dict]) -> float | None:
    """The plan quantity for an intervention from its placed features, in the catalog's quantity basis (metric).

    `features` carry type, area_m2, length_m and props. None when nothing placed measures it, or when the basis
    can't be measured from the drawing (a volume with no capacity entered)."""
    item = iv.by_id().get(intervention_id)
    basis = ((item or {}).get("quantity") or {}).get("basis")
    if not basis:
        return None
    feats = [f for f in features if types_by_id().get(f["type"], {}).get("intervention") == intervention_id
             and f.get("status", "proposed") == "proposed"]
    if not feats:
        return None
    if basis == "area_m2":
        total = sum(float(f.get("area_m2") or 0) for f in feats)
    elif basis == "length_m":
        total = sum(float(f.get("length_m") or 0) for f in feats)
    elif basis == "count":
        total = float(len(feats))  # one coop, tree, check dam or system per placed feature
    elif basis == "volume_m3":
        caps = [float((f.get("props") or {}).get("capacity_m3") or 0) for f in feats]
        if not any(caps):
            return None
        total = sum(caps)
    else:
        return None
    return round(total, 2) if total > 0 else None


def public_library() -> dict:
    """The library as the web app needs it."""
    data = library()
    catalog = iv.by_id()
    return {
        "version": str(data["version"]),
        "categories": data["categories"],
        "types": [{**{k: t[k] for k in ("id", "label", "category", "geometry", "intervention", "status", "fields", "defaults")},
                   "intervention_title": catalog[t["intervention"]]["title"] if t["intervention"] else None}
                  for t in data["types"]],
        "roofs": list(ROOFS),
    }
