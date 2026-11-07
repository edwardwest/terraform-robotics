"""USDA PLANTS species and traits from a Darwin Core Archive (the EOL/Zenodo "USDA plant traits" export).

The archive's meta.xml names the core (taxa) and extension (measurements) files and their columns, so the
parser follows it rather than assuming file names. USDA PLANTS is a US government work (public domain).
"""

from __future__ import annotations

import csv
import io
import re
import tarfile
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict

LICENSE = "US government work (public domain)"
SOURCE = "USDA PLANTS (via EOL trait export)"

# Friendly names for common trait URIs/labels; anything else keeps the last path segment of its URI.
TRAIT_ALIASES = {
    "growth habit": "growth_habit", "growthhabit": "growth_habit", "growth_habit": "growth_habit",
    "drought tolerance": "drought_tolerance", "droughttolerance": "drought_tolerance",
    "nitrogen fixation": "nitrogen_fixation", "nitrogenfixation": "nitrogen_fixation",
    "shade tolerance": "shade_tolerance", "shadetolerance": "shade_tolerance",
    "minimum temperature": "min_temp_f", "temperature, minimum": "min_temp_f", "temperatureminimum": "min_temp_f",
    "mature height": "mature_height_ft", "height, mature": "mature_height_ft", "heightmature": "mature_height_ft",
    "duration": "duration", "lifespan": "lifespan", "native status": "native_status", "nativestatus": "native_status",
    "growth rate": "growth_rate", "growthrate": "growth_rate", "fire resistance": "fire_resistance",
    "moisture use": "moisture_use", "salinity tolerance": "salinity_tolerance", "ph, minimum": "ph_min",
    "ph, maximum": "ph_max", "precipitation, minimum": "precip_min_in", "precipitation, maximum": "precip_max_in",
    "root depth, minimum": "root_depth_min_in", "palatable browse animal": "browse_palatability",
    "palatable graze animal": "graze_palatability", "fruit/seed abundance": "fruit_seed_abundance",
}


def trait_key(measurement_type: str) -> str:
    t = measurement_type.strip()
    seg = re.split(r"[/#]", t.rstrip("/"))[-1] if "://" in t else t
    norm = re.sub(r"[_\s]+", " ", re.sub(r"([a-z])([A-Z])", r"\1 \2", seg)).strip().lower()
    for k in (norm, norm.replace(" ", ""), t.lower()):
        if k in TRAIT_ALIASES:
            return TRAIT_ALIASES[k]
    return re.sub(r"[^a-z0-9]+", "_", norm).strip("_")[:60] or "trait"


class Archive:
    """Read files from a .tar.gz, .zip or directory-like mapping of name -> bytes."""

    def __init__(self, data: bytes):
        self.files: dict[str, bytes] = {}
        bio = io.BytesIO(data)
        if zipfile.is_zipfile(bio):
            with zipfile.ZipFile(bio) as z:
                for n in z.namelist():
                    if not n.endswith("/"):
                        self.files[n.split("/")[-1]] = z.read(n)
        else:
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as t:
                for m in t.getmembers():
                    if m.isfile():
                        self.files[m.name.split("/")[-1]] = t.extractfile(m).read()

    def table(self, spec: ET.Element, ns: str) -> list[dict[str, str]]:
        name = spec.find(f"{ns}files/{ns}location").text.strip().split("/")[-1]
        delim = (spec.get("fieldsTerminatedBy") or "\\t").encode().decode("unicode_escape")
        skip = int(spec.get("ignoreHeaderLines") or 0)
        cols = {int(f.get("index")): f.get("term").rstrip("/").split("/")[-1]
                for f in spec.findall(f"{ns}field") if f.get("index") is not None}
        for tag in ("id", "coreid"):
            el = spec.find(f"{ns}{tag}")
            if el is not None:
                cols.setdefault(int(el.get("index")), "_id")
        text = self.files[name].decode("utf-8", errors="replace")
        quote = spec.get("fieldsEnclosedBy") or ""
        reader = (csv.reader(io.StringIO(text), delimiter=delim, quotechar=quote) if quote
                  else csv.reader(io.StringIO(text), delimiter=delim, quoting=csv.QUOTE_NONE))
        rows = list(reader)[skip:]
        return [{cols[i]: v for i, v in enumerate(r) if i in cols} for r in rows if r]


def parse_dwca(data: bytes) -> list[dict]:
    """Species rows: {symbol, scientific_name, common_name, family, traits{...}}."""
    arc = Archive(data)
    meta = ET.fromstring(arc.files["meta.xml"])
    ns = "{http://rs.tdwg.org/dwc/text/}" if meta.tag.startswith("{") else ""
    tables = {}
    for spec in [meta.find(f"{ns}core"), *meta.findall(f"{ns}extension")]:
        if spec is None:
            continue
        row_type = spec.get("rowType", "").rstrip("/").split("/")[-1]
        tables[row_type] = arc.table(spec, ns)
    taxa = tables.get("Taxon", [])
    by_taxon: dict[str, dict] = {}
    for t in taxa:
        tid = t.get("taxonID") or t.get("_id")
        if not tid or not t.get("scientificName"):
            continue
        by_taxon[tid] = {
            "symbol": _symbol(t, tid),
            "scientific_name": t["scientificName"].strip(),
            "common_name": (t.get("vernacularName") or "").strip() or None,
            "family": (t.get("family") or "").strip() or None,
            "traits": {},
        }
    occ_taxon = {o.get("occurrenceID") or o.get("_id"): o.get("taxonID") for o in tables.get("Occurrence", [])}
    values: dict[str, dict[str, set]] = defaultdict(lambda: defaultdict(set))
    for m in tables.get("MeasurementOrFact", []):
        tid = m.get("taxonID") or occ_taxon.get(m.get("occurrenceID") or m.get("_id"))
        if tid not in by_taxon or not m.get("measurementType"):
            continue
        val = (m.get("measurementValue") or "").strip()
        if not val:
            continue
        val = re.split(r"[/#]", val.rstrip("/"))[-1] if "://" in val else val
        unit = (m.get("measurementUnit") or "").strip()
        values[tid][trait_key(m["measurementType"])].add(val + (f" {unit.split('/')[-1]}" if unit and "://" in unit else ""))
    for tid, tv in values.items():
        by_taxon[tid]["traits"] = {k: sorted(v)[0] if len(v) == 1 else sorted(v) for k, v in tv.items()}
    if not by_taxon:
        raise ValueError("No taxa found in the archive; check its meta.xml")
    # one row per USDA symbol (the archive can repeat a taxon under several ids)
    out: dict[str, dict] = {}
    for row in by_taxon.values():
        cur = out.get(row["symbol"])
        if cur is None or len(row["traits"]) > len(cur["traits"]):
            out[row["symbol"]] = row
    return list(out.values())


def _symbol(t: dict, tid: str) -> str:
    """The USDA symbol when the id carries one (e.g. 'QUAG' or '.../QUAG'); otherwise the whole id, so taxa never merge."""
    for k in ("taxonID", "_id"):
        v = (t.get(k) or "").strip()
        last = re.split(r"[/:#]", v)[-1]
        if re.fullmatch(r"[A-Z][A-Z0-9]{2,7}", last):
            return last
    return re.sub(r"[^A-Za-z0-9_.-]", "", tid)[:40] or tid
