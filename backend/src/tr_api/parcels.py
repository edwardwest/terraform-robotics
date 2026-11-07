"""Address search and county parcel lookup, from free public services.

- Geocoding: the US Census Bureau geocoder first, then county address records, then OpenStreetMap Nominatim.
- Parcels: county GIS parcel layers (ArcGIS REST). Each county is one entry in PROVIDERS; adding a county
  with an ArcGIS parcel service is a few lines of config.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import httpx
from fastapi import APIRouter, HTTPException, Query
from shapely.geometry import Point, shape

from . import schemas
from .auth import CurrentUser

router = APIRouter()

USER_AGENT = "TerraformRobotics/0.1 (site survey app; contact via terraformrobotics)"
TIMEOUT = httpx.Timeout(12.0)
STREET_TYPES = {"RD", "ROAD", "ST", "STREET", "AVE", "AVENUE", "LN", "LANE", "DR", "DRIVE", "WAY", "CT", "COURT",
                "HWY", "HIGHWAY", "BLVD", "PL", "PLACE", "TRL", "TRAIL", "CIR", "CIRCLE"}


@dataclass(frozen=True)
class ArcGisParcels:
    """A county parcel layer on ArcGIS REST, with the field names it uses."""

    name: str
    url: str  # .../FeatureServer/0
    bbox: tuple[float, float, float, float]  # lon/lat coverage
    apn: str
    address: str
    city: str | None
    acres: str | None

    def covers(self, lng: float, lat: float) -> bool:
        w, s, e, n = self.bbox
        return w <= lng <= e and s <= lat <= n

    def fields(self) -> str:
        return ",".join(f for f in (self.apn, self.address, self.city, self.acres) if f)

    def to_parcel(self, feat: dict) -> dict:
        p = feat.get("properties") or {}
        geom = shape(feat["geometry"])
        parts = 1
        if geom.geom_type == "MultiPolygon":
            parts = len(geom.geoms)
            geom = max(geom.geoms, key=lambda g: g.area)  # the site boundary is one polygon; keep the main part
        addr = p.get(self.address)
        if addr and self.city and p.get(self.city):
            addr = f"{addr}, {p[self.city]}"
        return {
            "apn": p.get(self.apn),
            "address": addr.title() if isinstance(addr, str) else addr,
            "acres": p.get(self.acres) if self.acres else None,
            "boundary": {"type": "Polygon", "coordinates": [[list(c) for c in ring.coords] for ring in (geom.exterior, *geom.interiors)]},
            "source": self.name if parts == 1 else f"{self.name} (largest of {parts} parts)",
        }


PROVIDERS = [
    ArcGisParcels(
        name="Sonoma County assessor parcels",
        url="https://socogis.sonomacounty.ca.gov/map/rest/services/CRAPublic/Parcels_Public_Sync/FeatureServer/0",
        bbox=(-123.54, 38.10, -122.34, 38.86),
        apn="APN", address="SitusFormatted1", city="SitusCity", acres="LandSizeAcres",
    ),
]


def _get(url: str, params: dict) -> dict | list:
    with httpx.Client(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}) as client:
        r = client.get(url, params=params)
        r.raise_for_status()
        return r.json()


def _parse_address(q: str) -> tuple[str, str] | None:
    """('700', 'FREESTONE RANCH') from '700 Freestone Ranch Road, Sebastopol CA 95472'."""
    street = q.split(",")[0].upper()
    m = re.match(r"\s*(\d+)\s+(.+)", street)
    if not m:
        return None
    words = [w for w in re.sub(r"[^A-Z0-9 ]", " ", m.group(2)).split() if w]
    while words and words[-1] in STREET_TYPES:
        words.pop()
    return (m.group(1), " ".join(words)) if words else None


def census_geocode(q: str) -> list[dict]:
    data = _get("https://geocoding.geo.census.gov/geocoder/locations/onelineaddress",
                {"address": q, "benchmark": "Public_AR_Current", "format": "json"})
    out = []
    for m in data.get("result", {}).get("addressMatches", [])[:5]:
        c = m["coordinates"]
        out.append({"label": m["matchedAddress"].title(), "lng": c["x"], "lat": c["y"], "source": "US Census geocoder"})
    return out


def county_address_search(q: str) -> list[dict]:
    parsed = _parse_address(q)
    if not parsed:
        return []
    num, street = parsed
    out = []
    for p in PROVIDERS:
        try:
            for f in parcels_by_situs(p, num, street)[:5]:
                c = shape(f["boundary"]).representative_point()
                out.append({"label": f["address"] or f["apn"], "lng": c.x, "lat": c.y, "source": p.name})
        except httpx.HTTPError:
            continue
    return out


def nominatim_geocode(q: str) -> list[dict]:
    data = _get("https://nominatim.openstreetmap.org/search", {"q": q, "format": "jsonv2", "limit": 5, "countrycodes": "us"})
    return [{"label": d["display_name"], "lng": float(d["lon"]), "lat": float(d["lat"]), "source": "OpenStreetMap"} for d in data]


def parcels_by_situs(p: ArcGisParcels, num: str, street: str) -> list[dict]:
    like = f"{num} {street}".replace("'", "''")
    data = _get(f"{p.url}/query", {"where": f"UPPER({p.address}) LIKE '{like}%'", "outFields": p.fields(),
                                   "outSR": 4326, "geometryPrecision": 7, "f": "geojson"})
    return [p.to_parcel(f) for f in data.get("features", []) if f.get("geometry")]


def parcel_at(lng: float, lat: float) -> dict | None:
    for p in PROVIDERS:
        if not p.covers(lng, lat):
            continue
        data = _get(f"{p.url}/query", {"geometry": f"{lng},{lat}", "geometryType": "esriGeometryPoint", "inSR": 4326,
                                       "spatialRel": "esriSpatialRelIntersects", "outFields": p.fields(), "outSR": 4326,
                                       "geometryPrecision": 7, "f": "geojson"})
        feats = [f for f in data.get("features", []) if f.get("geometry")]
        pt = Point(lng, lat)
        feats.sort(key=lambda f: shape(f["geometry"]).distance(pt))
        if feats:
            return p.to_parcel(feats[0])
    return None


@router.get("/api/geocode", response_model=list[schemas.GeocodeResult])
def geocode(user: CurrentUser, q: str = Query(..., min_length=3, max_length=200)):
    results: list[dict] = []
    for fn in (census_geocode, county_address_search):
        try:
            results += fn(q)
        except httpx.HTTPError:
            continue
    if not results:
        try:
            results = nominatim_geocode(q)
        except httpx.HTTPError:
            pass
    seen, out = set(), []
    for r in results:
        key = (round(r["lng"], 4), round(r["lat"], 4))
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out[:8]


@router.get("/api/parcels/at", response_model=schemas.Parcel)
def get_parcel_at(user: CurrentUser, lng: float = Query(..., ge=-180, le=180), lat: float = Query(..., ge=-90, le=90)):
    if not any(p.covers(lng, lat) for p in PROVIDERS):
        raise HTTPException(404, "No county parcel source covers this location yet. Draw the boundary or upload a file.")
    try:
        parcel = parcel_at(lng, lat)
    except httpx.HTTPError:
        raise HTTPException(502, "The county parcel service did not respond. Try again, or draw the boundary.")
    if not parcel:
        raise HTTPException(404, "No parcel found at this point")
    return parcel


@router.get("/api/parcels/coverage")
def parcel_coverage(user: CurrentUser):
    return [{"name": p.name, "bbox": list(p.bbox)} for p in PROVIDERS]
